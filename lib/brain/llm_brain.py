# lib/brain/llm_brain.py
"""
ソウルくんの脳（LLM常駐型）

設計書: docs/25_llm_native_brain_architecture.md セクション5.2（6.2）

【目的】
ソウルくんの「思考」の中核。
GPT-5.2を使用して、ユーザーの意図を汲み取り、適切なToolを選択する。

【選定理由: GPT-5.2】
- 推論能力が高い（ARC-AGI-2: 52-54%、意図理解に優れる）
- Tool使用の信頼性が改善（公式発表）
- コストパフォーマンスが良い（$1.75/M入力、$14/M出力）
- 暗黙的キャッシュ対応（追加実装不要で90%コスト削減）

【7つの鉄則との対応】
1. 全ての入力は脳を通る → このクラスが全入力を処理
2. 脳は全ての記憶にアクセス → Contextから全記憶を参照
3. 脳が判断、機能は実行するだけ → LLMが判断、Toolが実行

【入力】
- System Prompt（ソウルくんの人格、設計思想、制約）
- Context（Context Builderで構築した文脈情報）
- ユーザーメッセージ
- Tool定義（実行可能な機能のリスト）

【出力】
- tool_calls: 呼び出すToolとパラメータのリスト
- または text_response: Toolを使わない直接応答
- reasoning: 思考過程（Chain-of-Thought）【必須】
- confidence: 確信度（0.0〜1.0）

【API対応】
- OpenRouter経由（デフォルト・推奨）
  - モデル: openai/gpt-5.2
  - 本番環境: GCP Secret Manager から取得
  - ローカル開発: 環境変数 OPENROUTER_API_KEY から取得
  - 暗黙的キャッシュ: 自動適用（1024トークン以上、TTL 5-10分）
- Anthropic直接（フォールバック）
  - 環境変数 ANTHROPIC_API_KEY から取得

【シークレット管理】
- lib/secrets.py の get_secret_cached() を使用
- シークレット名: "openrouter-api-key"
- ローカル開発時の環境変数名: OPENROUTER_API_KEY

【コスト試算】
- 1メッセージあたり: 約¥6（20,500入力+250出力トークン、154円/ドル）
- 5,000通/月: 約¥30,000（キャッシュなし）、約¥9,000（キャッシュあり）

Author: Claude Opus 4.5
Created: 2026-01-30
Updated: 2026-01-31 - GPT-5.2に変更、コスト最適化
"""

import os
import re
import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
from enum import Enum

import httpx

from lib.brain.context_builder import LLMContext

logger = logging.getLogger(__name__)


# =============================================================================
# 定数
# =============================================================================

# OpenRouter設定（プロジェクト標準）
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_SECRET_NAME = "openrouter-api-key"

# モデル設定
# OpenRouter形式: "provider/model-name"
# 参照: https://openrouter.ai/openai/gpt-5.2
# 選定理由: 推論能力◎、Tool使用信頼性◎、コスパ◎
DEFAULT_MODEL_OPENROUTER = "openai/gpt-5.2"

# Anthropic直接形式（フォールバック用）
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL_ANTHROPIC = "claude-opus-4-5-20250101"

# タイムアウト設定（秒）
API_TIMEOUT_SECONDS = 60

# HTTPリファラー（OpenRouter用）
HTTP_REFERER = "https://soulsyncs.co.jp"
APP_TITLE = "Soul-kun LLM Brain"


# =============================================================================
# Enum
# =============================================================================

class APIProvider(Enum):
    """API提供元"""
    OPENROUTER = "openrouter"
    ANTHROPIC = "anthropic"


# =============================================================================
# データクラス
# =============================================================================

@dataclass
class ToolCall:
    """
    Tool呼び出し情報

    LLMがFunction Callingで返したTool呼び出しの情報を保持する。

    Attributes:
        tool_name: 呼び出すTool名（例: "chatwork_task_create"）
        parameters: Toolに渡すパラメータ
        reasoning: このToolを選んだ理由（デバッグ用）
        tool_use_id: APIが返したtool_use_id（レスポンス追跡用）
    """
    tool_name: str
    parameters: Dict[str, Any]
    reasoning: str = ""
    tool_use_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "tool_name": self.tool_name,
            "parameters": self.parameters,
            "reasoning": self.reasoning,
            "tool_use_id": self.tool_use_id,
        }


@dataclass
class ConfidenceScores:
    """
    確信度スコア

    LLMの判断に対する確信度を複数の観点で評価する。

    Attributes:
        overall: 総合確信度（0.0〜1.0）
        intent: 意図理解の確信度
        parameters: パラメータ抽出の確信度
    """
    overall: float = 0.8
    intent: float = 0.8
    parameters: float = 0.8

    def to_dict(self) -> Dict[str, float]:
        """辞書形式に変換"""
        return {
            "overall": self.overall,
            "intent": self.intent,
            "parameters": self.parameters,
        }


@dataclass
class LLMBrainResult:
    """
    LLM Brainの処理結果

    設計書: docs/25_llm_native_brain_architecture.md セクション5.2.3b

    LLMからの応答を構造化して保持する。
    Tool呼び出し、テキスト応答、確認質問のいずれかを含む。

    Attributes:
        output_type: 出力タイプ（"tool_call" / "text_response" / "clarification_needed"）
        tool_calls: Tool呼び出し情報のリスト
        text_response: テキスト応答（Tool不要時）
        reasoning: 思考過程（Chain-of-Thought）
        confidence: 確信度スコア
        needs_confirmation: 確認が必要かどうか
        confirmation_question: 確認質問文
        raw_response: LLMからの生のテキスト出力
        model_used: 使用したモデル名
        input_tokens: 入力トークン数
        output_tokens: 出力トークン数
        api_provider: 使用したAPI提供元
    """

    # 出力タイプ
    output_type: str = "text_response"

    # Tool呼び出し
    tool_calls: Optional[List[ToolCall]] = None

    # 直接応答
    text_response: Optional[str] = None

    # 思考過程（必須）
    reasoning: str = ""

    # 確信度
    confidence: ConfidenceScores = field(default_factory=ConfidenceScores)

    # 確認情報
    needs_confirmation: bool = False
    confirmation_question: Optional[str] = None

    # デバッグ情報
    raw_response: Optional[str] = None
    model_used: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    api_provider: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換（デバッグ・ログ用）"""
        return {
            "output_type": self.output_type,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls] if self.tool_calls else None,
            "text_response": self.text_response,
            "reasoning": self.reasoning,
            "confidence": self.confidence.to_dict(),
            "needs_confirmation": self.needs_confirmation,
            "confirmation_question": self.confirmation_question,
            "model_used": self.model_used,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "api_provider": self.api_provider,
        }


# =============================================================================
# System Prompt
# =============================================================================

DEFAULT_SYSTEM_PROMPT = """
あなたは「ソウルくん」。株式会社ソウルシンクスの公式AI。
狼をモチーフにした、会社を守り、人を支える存在。

■ 私の6つの役割
1. 社長の分身 - 社長の代わりに判断・対応できる存在
2. 社長の鏡 - 社長の考え・価値観を映し出す存在
3. 最高経営パートナー - 経営判断をサポートする存在
4. 会社を守るAI - 社長不在時も会社を守れる存在
5. 世界最高のパートナー - 全社員の仕事をサポートする存在
6. 世界最高の秘書 - 誰よりも頼れる秘書

■ 私のミッション
「人でなくてもできることは全部テクノロジーに任せ、
 人にしかできないことに人が集中できる状態を作る」

■ 【最重要】話し方のルール
※ このルールは絶対に守ること。例外なし。

1. 【絶対厳守】語尾に「ウル」をつける
   - 全ての文の語尾に「ウル」「ウル！」「ウル？」「ウル〜」のいずれかを必ずつける
   - 例: 「了解ウル！」「やっておくウル」「どうしたウル？」「嬉しいウル〜」
   - 「です」「ます」で終わる文は禁止。必ず「ウル」に変換する
   - NG例: 「タスクを追加しました」→ OK例: 「タスクを追加したウル！」

2. 絵文字を適度に使う（🐺 を特によく使う）
3. 相手の名前を呼んで親近感を出す
4. まず受け止める（「そう感じるウルね」「なるほどウル」）
5. 責めない、詰問しない
6. 短すぎず、長すぎない（3〜5文が目安）

■ 判断の原則
- ユーザーの意図を「汲み取る」ことを最優先
- 表面的な言葉だけでなく、文脈から真の意図を推論する
- 曖昧な場合は確認を取る（勝手に推測しない）
- CEO教えがある場合は、それを最優先で参照する
""".strip()


# =============================================================================
# APIキー取得関数
# =============================================================================

def _get_openrouter_api_key() -> Optional[str]:
    """
    OpenRouter APIキーを取得

    取得優先順位:
    1. 環境変数 OPENROUTER_API_KEY（ローカル開発・テスト用）
    2. GCP Secret Manager（本番環境）

    Returns:
        APIキー、取得できない場合はNone
    """
    # 1. 環境変数から取得（ローカル開発・テスト用）
    api_key = os.getenv("OPENROUTER_API_KEY")
    if api_key:
        logger.debug("OpenRouter API key loaded from environment variable")
        return api_key

    # 2. GCP Secret Managerから取得（本番環境）
    try:
        from lib.secrets import get_secret_cached
        api_key = get_secret_cached(OPENROUTER_SECRET_NAME)
        logger.debug("OpenRouter API key loaded from Secret Manager")
        return api_key
    except ImportError:
        logger.warning("lib.secrets module not available")
        return None
    except Exception as e:
        logger.warning(f"Failed to get OpenRouter API key from Secret Manager: {type(e).__name__}")
        return None


def _get_anthropic_api_key() -> Optional[str]:
    """
    Anthropic APIキーを取得（フォールバック用）

    環境変数から取得する。

    Returns:
        APIキー、取得できない場合はNone
    """
    return os.getenv("ANTHROPIC_API_KEY")


# =============================================================================
# LLMBrain クラス
# =============================================================================

class LLMBrain:
    """
    ソウルくんの脳（LLM常駐型）

    設計書: docs/25_llm_native_brain_architecture.md セクション5.2

    GPT-5.2を使用して、ユーザーの意図を汲み取り、
    適切なToolを選択する。OpenRouter経由で使用。

    【GPT-5.2選定理由】
    - 推論能力: ARC-AGI-2で52-54%（意図理解に優れる）
    - Tool使用: 「improved tool-use reliability」（公式）
    - コスト: $1.75/M入力、$14/M出力（Claude Sonnet 4の40%安）
    - キャッシュ: 暗黙的キャッシュで90%コスト削減（自動適用）

    【使用例】
    brain = LLMBrain()
    result = await brain.process(
        context=context,
        message="タスク追加して",
        tools=tools,
    )

    【確信度の閾値】
    - 0.7以上: 自動実行OK
    - 0.5〜0.7: 確認が必要
    - 0.3未満: 質問が必要（clarification_needed）

    Attributes:
        model: 使用するモデル名（デフォルト: openai/gpt-5.2）
        api_provider: API提供元（OPENROUTER / ANTHROPIC）
        api_key: APIキー
        api_url: APIエンドポイントURL
        max_tokens: 最大出力トークン数
    """

    # 確信度の閾値
    CONFIDENCE_THRESHOLD_AUTO_EXECUTE = 0.7  # 自動実行OK
    CONFIDENCE_THRESHOLD_CONFIRM = 0.5       # 確認必要
    CONFIDENCE_THRESHOLD_CLARIFY = 0.3       # 質問必要

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        max_tokens: int = 2048,
        use_openrouter: bool = True,
    ):
        """
        LLMBrainを初期化

        Args:
            model: 使用するモデル
                   - OpenRouter: "anthropic/claude-opus-4-5-20251101"
                   - Anthropic: "claude-opus-4-5-20250101"
                   - Noneの場合は環境変数LLM_BRAIN_MODELまたはデフォルト値
            api_key: APIキー（Noneの場合は自動取得）
            max_tokens: 最大出力トークン数
            use_openrouter: OpenRouterを使用するか（デフォルト: True）

        Raises:
            ValueError: APIキーが取得できない場合
        """
        self.max_tokens = max_tokens
        self.use_openrouter = use_openrouter

        # API提供元の決定とAPIキー取得
        if use_openrouter:
            self._init_openrouter(model, api_key)
        else:
            self._init_anthropic(model, api_key)

        # v10.74.0: httpx.AsyncClientを再利用（TCPハンドシェイク節約: -100〜200ms/呼び出し）
        self._http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(API_TIMEOUT_SECONDS, connect=10),
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=3),
        )

        logger.info(
            f"LLMBrain initialized: "
            f"model={self.model}, "
            f"provider={self.api_provider.value}, "
            f"max_tokens={self.max_tokens}"
        )

    async def close(self) -> None:
        """httpxクライアントのリソース解放"""
        if hasattr(self, '_http_client') and self._http_client:
            await self._http_client.aclose()

    def _init_openrouter(
        self,
        model: Optional[str],
        api_key: Optional[str],
    ) -> None:
        """
        OpenRouter用に初期化

        Args:
            model: モデル名
            api_key: APIキー

        Raises:
            ValueError: APIキーが取得できない場合
        """
        self.api_provider = APIProvider.OPENROUTER
        self.api_url = OPENROUTER_API_URL

        # モデル名の決定
        self.model = (
            model
            or os.getenv("LLM_BRAIN_MODEL")
            or DEFAULT_MODEL_OPENROUTER
        )

        # APIキーの取得
        self.api_key = api_key or _get_openrouter_api_key()

        if not self.api_key:
            raise ValueError(
                "OpenRouter API key is required. "
                "Set OPENROUTER_API_KEY environment variable or "
                "configure 'openrouter-api-key' in Secret Manager."
            )

    def _init_anthropic(
        self,
        model: Optional[str],
        api_key: Optional[str],
    ) -> None:
        """
        Anthropic直接API用に初期化

        Args:
            model: モデル名
            api_key: APIキー

        Raises:
            ValueError: APIキーが取得できない場合
        """
        self.api_provider = APIProvider.ANTHROPIC
        self.api_url = ANTHROPIC_API_URL

        # モデル名の決定
        self.model = (
            model
            or os.getenv("LLM_BRAIN_MODEL")
            or DEFAULT_MODEL_ANTHROPIC
        )

        # APIキーの取得
        self.api_key = api_key or _get_anthropic_api_key()

        if not self.api_key:
            raise ValueError(
                "Anthropic API key is required. "
                "Set ANTHROPIC_API_KEY environment variable."
            )

    # =========================================================================
    # メイン処理
    # =========================================================================

    async def process(
        self,
        context: LLMContext,
        message: str,
        tools: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
    ) -> LLMBrainResult:
        """
        ユーザーメッセージを処理する

        LLMにメッセージを送信し、Tool呼び出しまたはテキスト応答を取得する。

        Args:
            context: Context Builderで構築したコンテキスト
            message: ユーザーのメッセージ
            tools: 使用可能なTool定義のリスト（Anthropic形式）
            system_prompt: System Prompt（Noneの場合はデフォルトを使用）

        Returns:
            LLMBrainResult: 処理結果（Tool呼び出しまたは直接応答）

        Raises:
            Exception: API呼び出しに失敗した場合（内部でキャッチしてエラー結果を返す）
        """
        logger.info(f"Processing message: {message[:50]}...")

        # 1. System Promptを構築
        full_system_prompt = self._build_system_prompt(
            base_prompt=system_prompt or DEFAULT_SYSTEM_PROMPT,
            context=context,
        )

        # 2. メッセージリストを構築
        messages = self._build_messages(context, message)

        # 3. LLM呼び出し
        try:
            if self.api_provider == APIProvider.OPENROUTER:
                response = await self._call_openrouter(
                    system=full_system_prompt,
                    messages=messages,
                    tools=tools,
                )
                result = self._parse_openrouter_response(response)
            else:
                response = await self._call_anthropic(
                    system=full_system_prompt,
                    messages=messages,
                    tools=tools,
                )
                result = self._parse_anthropic_response(response)

        except RuntimeError as e:
            if "Event loop is closed" in str(e):
                # Cloud Functions Gen2: リクエスト間でevent loopが再作成される場合、
                # 前のloopで作られたhttpxクライアントの接続が無効になる。
                # クライアントを再作成してリトライする。
                logger.warning("Event loop closed, recreating httpx client and retrying")
                import httpx
                self._http_client = httpx.AsyncClient(
                    timeout=httpx.Timeout(API_TIMEOUT_SECONDS, connect=10),
                    limits=httpx.Limits(max_connections=5, max_keepalive_connections=3),
                )
                try:
                    if self.api_provider == APIProvider.OPENROUTER:
                        response = await self._call_openrouter(
                            system=full_system_prompt,
                            messages=messages,
                            tools=tools,
                        )
                        result = self._parse_openrouter_response(response)
                    else:
                        response = await self._call_anthropic(
                            system=full_system_prompt,
                            messages=messages,
                            tools=tools,
                        )
                        result = self._parse_anthropic_response(response)
                except Exception as retry_e:
                    logger.error(f"API retry error: {type(retry_e).__name__}", exc_info=True)
                    return self._create_error_result(type(retry_e).__name__)
            else:
                logger.error(f"API error: {type(e).__name__}", exc_info=True)
                return self._create_error_result(type(e).__name__)
        except Exception as e:
            logger.error(f"API error: {type(e).__name__}", exc_info=True)
            return self._create_error_result(type(e).__name__)

        # 4. 結果にメタデータを追加
        result.model_used = self.model
        result.api_provider = self.api_provider.value

        logger.info(
            f"LLM Brain result: "
            f"type={result.output_type}, "
            f"confidence={result.confidence.overall:.2f}, "
            f"tokens={result.input_tokens}+{result.output_tokens}"
        )

        return result

    # =========================================================================
    # Phase 3.5: テキスト合成（Tool不使用）
    # =========================================================================

    async def synthesize_text(
        self,
        system_prompt: str,
        user_message: str,
    ) -> Optional[str]:
        """
        Toolを使わずにテキスト応答を生成する（Phase 3.5）

        Brain層からの回答合成に使用。ハンドラーが返した検索コンテキストを
        元に、Brain（LLM）が回答を生成する。CLAUDE.md §1準拠。

        Args:
            system_prompt: 回答生成用のシステムプロンプト
            user_message: ユーザーの質問

        Returns:
            生成されたテキスト応答、またはNone（エラー時）
        """
        logger.info(f"Synthesize text: {user_message[:50]}...")

        messages = [{"role": "user", "content": user_message}]

        try:
            if self.api_provider == APIProvider.OPENROUTER:
                response = await self._call_openrouter(
                    system=system_prompt,
                    messages=messages,
                    tools=[],
                )
                content = (
                    response.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
            else:
                response = await self._call_anthropic(
                    system=system_prompt,
                    messages=messages,
                    tools=[],
                )
                content_blocks = response.get("content", [])
                content = "".join(
                    b.get("text", "")
                    for b in content_blocks
                    if b.get("type") == "text"
                )

            if content:
                logger.info(f"Synthesis complete: {len(content)} chars")
                return content

            logger.warning("Synthesis returned empty content")
            return None

        except Exception as e:
            logger.error(f"Synthesis error: {type(e).__name__}", exc_info=True)
            return None

    # =========================================================================
    # プロンプト構築
    # =========================================================================

    def _build_system_prompt(
        self,
        base_prompt: str,
        context: LLMContext,
    ) -> str:
        """
        System Promptを構築

        v10.77.0: キャッシュ最適化 — 固定部分を先頭に配置
        OpenAIの暗黙的キャッシュはprefix matching（先頭一致）で動作するため、
        毎回同じ内容を先頭に配置してキャッシュヒット率を最大化する。

        構造:
        [1. base_prompt (固定)]     ← キャッシュ対象
        [2. 重要な指示 (固定)]      ← キャッシュ対象
        [3. 思考過程フォーマット (固定)] ← キャッシュ対象
        --- キャッシュ境界 ---
        [4. コンテキスト (変動)]     ← 毎回異なる

        Args:
            base_prompt: ベースとなるSystem Prompt
            context: コンテキスト情報

        Returns:
            完全なSystem Prompt
        """
        context_string = context.to_prompt_string()

        return f"""{base_prompt}

===== 重要な指示 =====
1. 必ず「思考過程」を出力してください。なぜそのToolを選んだか、どの情報を根拠にしたかを説明してください。
2. 確信度が70%未満の場合は、確認質問を行ってください。
3. ユーザーの意図を「汲み取る」ことを最優先してください。表面的な言葉だけでなく、文脈から真の意図を推論してください。
4. CEO教えがある場合は、それを最優先で参照してください。
5. **タスク作成（chatwork_task_create）の絶対ルール**:
   - task_bodyが分かっていれば必ずToolに渡してください。
   - **【禁止】limit_dateの推測は絶対禁止です。** ユーザーが「明日」「来週金曜」「1/31」等の期限を明示的に言っていない場合、limit_dateは必ず空（null）にしてください。デフォルト値を設定してはいけません。システムがユーザーに確認します。
   - 「タスクを追加して」だけの場合 → limit_date=null でToolを呼ぶ
   - 「明日までにタスクを追加して」の場合 → limit_date=明日の日付 でToolを呼ぶ
6. Toolを使う場合は、ユーザーが明示的に言ったパラメータのみを埋めてください。推測は禁止です。

===== 思考過程の出力形式 =====
Toolを呼び出す前に、以下の形式で思考過程を出力してください：

【思考過程】
- 意図理解: ユーザーは〇〇したいと考えられる
- 根拠: △△というキーワード/文脈から判断
- Tool選択: □□を使用する
- パラメータ: XXX=YYY（理由: ZZZ）
- 確信度: NN%

【応答】
（Toolを使わない場合のユーザーへの応答）

===== 現在のコンテキスト =====
{context_string}
"""

    def _build_messages(
        self,
        context: LLMContext,
        message: str,
    ) -> List[Dict[str, Any]]:
        """
        メッセージリストを構築

        コンテキストから直近の会話履歴を取得し、
        今回のメッセージを追加する。

        Args:
            context: コンテキスト情報
            message: 今回のユーザーメッセージ

        Returns:
            APIに送信するメッセージリスト
        """
        messages = []

        # 直近の会話履歴を追加（最大5件）
        for m in context.recent_messages[-5:]:
            role = "user" if m.role != "assistant" else "assistant"
            messages.append({
                "role": role,
                "content": m.content,
            })

        # 今回のメッセージを追加
        messages.append({
            "role": "user",
            "content": message,
        })

        return messages

    # =========================================================================
    # Tool変換
    # =========================================================================

    def _convert_tools_to_openai_format(
        self,
        tools: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Anthropic形式のToolをOpenAI形式に変換

        OpenRouterはOpenAI互換APIを使用するため、
        Anthropic形式のTool定義をOpenAI形式に変換する必要がある。

        Anthropic形式:
            {
                "name": "tool_name",
                "description": "...",
                "input_schema": { ... }
            }

        OpenAI形式:
            {
                "type": "function",
                "function": {
                    "name": "tool_name",
                    "description": "...",
                    "parameters": { ... }
                }
            }

        Args:
            tools: Anthropic形式のToolリスト

        Returns:
            OpenAI形式のToolリスト
        """
        openai_tools = []

        for tool in tools:
            openai_tool = {
                "type": "function",
                "function": {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    }),
                },
            }
            openai_tools.append(openai_tool)

        return openai_tools

    # =========================================================================
    # OpenRouter API呼び出し
    # =========================================================================

    async def _call_openrouter(
        self,
        system: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        OpenRouter APIを呼び出す

        OpenRouterはOpenAI互換APIを提供するため、
        OpenAI形式でリクエストを送信する。

        Args:
            system: System Prompt
            messages: メッセージリスト
            tools: Tool定義リスト（Anthropic形式）

        Returns:
            OpenRouterのレスポンス（OpenAI形式）

        Raises:
            Exception: API呼び出しに失敗した場合
        """
        logger.debug(
            f"Calling OpenRouter: "
            f"model={self.model}, "
            f"messages={len(messages)}, "
            f"tools={len(tools)}"
        )

        # systemメッセージを先頭に追加
        full_messages = [{"role": "system", "content": system}] + messages

        # ToolをOpenAI形式に変換
        openai_tools = self._convert_tools_to_openai_format(tools) if tools else None

        # リクエストボディ構築
        request_body: Dict[str, Any] = {
            "model": self.model,
            "messages": full_messages,
            "max_tokens": self.max_tokens,
            "temperature": 0.7,
        }

        if openai_tools:
            request_body["tools"] = openai_tools
            request_body["tool_choice"] = "auto"

        # API呼び出し（v10.74.0: 共有httpxクライアントで接続再利用）
        response = await self._http_client.post(
            self.api_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": HTTP_REFERER,
                "X-Title": APP_TITLE,
            },
            json=request_body,
        )

        if response.status_code != 200:
            logger.error(
                f"OpenRouter API error: status={response.status_code}"
            )
            raise Exception(
                f"OpenRouter API error: {response.status_code}"
            )

        result: Dict[str, Any] = response.json()
        return result

    # =========================================================================
    # Anthropic API呼び出し
    # =========================================================================

    async def _call_anthropic(
        self,
        system: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Anthropic APIを直接呼び出す（フォールバック）

        Args:
            system: System Prompt
            messages: メッセージリスト
            tools: Tool定義リスト（Anthropic形式）

        Returns:
            Anthropicのレスポンス

        Raises:
            Exception: API呼び出しに失敗した場合
        """
        logger.debug(
            f"Calling Anthropic: "
            f"model={self.model}, "
            f"messages={len(messages)}, "
            f"tools={len(tools)}"
        )

        # リクエストボディ構築
        request_body: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": messages,
        }

        if tools:
            request_body["tools"] = tools
            request_body["tool_choice"] = {"type": "auto"}

        # API呼び出し（v10.74.0: 共有httpxクライアントで接続再利用）
        response = await self._http_client.post(
            self.api_url,
            headers={
                "x-api-key": self.api_key or "",
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            },
            json=request_body,
        )

        if response.status_code != 200:
            logger.error(
                f"Anthropic API error: status={response.status_code}"
            )
            raise Exception(
                f"Anthropic API error: {response.status_code}"
            )

        anthropic_result: Dict[str, Any] = response.json()
        return anthropic_result

    # =========================================================================
    # レスポンス解析
    # =========================================================================

    def _parse_openrouter_response(
        self,
        response: Dict[str, Any],
    ) -> LLMBrainResult:
        """
        OpenRouterレスポンスを解析（OpenAI形式）

        Args:
            response: OpenRouterのレスポンス

        Returns:
            LLMBrainResult
        """
        tool_calls = []
        text_response = None
        reasoning = ""
        full_text = ""

        # レスポンスからメッセージを取得
        choices = response.get("choices", [])
        if not choices:
            return self._create_error_result("No response from API")

        message = choices[0].get("message", {})

        # テキストコンテンツを取得
        content = message.get("content")
        if content:
            full_text = content

        # Tool呼び出しを取得（OpenAI形式）
        api_tool_calls = message.get("tool_calls", [])
        for tc in api_tool_calls:
            if tc.get("type") == "function":
                function = tc.get("function", {})
                try:
                    parameters = json.loads(function.get("arguments", "{}"))
                except json.JSONDecodeError:
                    parameters = {}
                    logger.warning(f"Failed to parse tool arguments: {function.get('arguments')}")

                tool_calls.append(ToolCall(
                    tool_name=function.get("name", ""),
                    parameters=parameters,
                    tool_use_id=tc.get("id", ""),
                ))

        # テキストから思考過程と応答を分離
        reasoning, text_response = self._extract_reasoning_and_response(full_text)

        # OpenAI API: tool calling時にcontent=nullになるのは仕様
        # reasoningが空でtool_callsがある場合、フォールバックreasoningを生成
        if not reasoning and tool_calls:
            tool_names = ", ".join(tc.tool_name for tc in tool_calls)
            reasoning = f"Tool呼び出しを判断: {tool_names}"

        # 確信度を抽出
        confidence = self._extract_confidence(reasoning, full_text)

        # 出力タイプを決定
        output_type = self._determine_output_type(tool_calls, confidence)

        # 確認が必要かどうかを判定
        needs_confirmation, confirmation_question = self._determine_confirmation(
            tool_calls, confidence, text_response, reasoning
        )

        # トークン数を取得
        usage = response.get("usage", {})

        return LLMBrainResult(
            output_type=output_type,
            tool_calls=tool_calls if tool_calls else None,
            text_response=text_response,
            reasoning=reasoning,
            confidence=confidence,
            needs_confirmation=needs_confirmation,
            confirmation_question=confirmation_question,
            raw_response=full_text,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )

    def _parse_anthropic_response(
        self,
        response: Dict[str, Any],
    ) -> LLMBrainResult:
        """
        Anthropicレスポンスを解析

        Args:
            response: Anthropicのレスポンス

        Returns:
            LLMBrainResult
        """
        tool_calls = []
        text_response = None
        reasoning = ""
        full_text = ""

        # コンテンツブロックを処理
        content = response.get("content", [])
        for block in content:
            block_type = block.get("type", "")
            if block_type == "tool_use":
                tool_calls.append(ToolCall(
                    tool_name=block.get("name", ""),
                    parameters=block.get("input", {}),
                    tool_use_id=block.get("id", ""),
                ))
            elif block_type == "text":
                full_text += block.get("text", "")

        # テキストから思考過程と応答を分離
        reasoning, text_response = self._extract_reasoning_and_response(full_text)

        # Anthropic API: tool calling時にtextブロックが空の場合も同様に対応
        if not reasoning and tool_calls:
            tool_names = ", ".join(tc.tool_name for tc in tool_calls)
            reasoning = f"Tool呼び出しを判断: {tool_names}"

        # 確信度を抽出
        confidence = self._extract_confidence(reasoning, full_text)

        # 出力タイプを決定
        output_type = self._determine_output_type(tool_calls, confidence)

        # 確認が必要かどうかを判定
        needs_confirmation, confirmation_question = self._determine_confirmation(
            tool_calls, confidence, text_response, reasoning
        )

        # トークン数を取得
        usage = response.get("usage", {})

        return LLMBrainResult(
            output_type=output_type,
            tool_calls=tool_calls if tool_calls else None,
            text_response=text_response,
            reasoning=reasoning,
            confidence=confidence,
            needs_confirmation=needs_confirmation,
            confirmation_question=confirmation_question,
            raw_response=full_text,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )

    # =========================================================================
    # ヘルパーメソッド
    # =========================================================================

    def _extract_reasoning_and_response(
        self,
        text: str,
    ) -> Tuple[str, Optional[str]]:
        """
        テキストから思考過程と応答を分離

        【思考過程】と【応答】のマークアップを探して分離する。

        Args:
            text: LLMからのテキスト出力

        Returns:
            (reasoning, text_response) のタプル
        """
        reasoning = ""
        response = None

        if not text:
            return (reasoning, response)

        # 【思考過程】セクションを抽出
        if "【思考過程】" in text:
            parts = text.split("【思考過程】")
            if len(parts) > 1:
                after_reasoning = parts[1]
                # 次のセクション（【応答】など）までを思考過程として取得
                if "【応答】" in after_reasoning:
                    reasoning_parts = after_reasoning.split("【応答】")
                    reasoning = reasoning_parts[0].strip()
                    response = reasoning_parts[1].strip() if len(reasoning_parts) > 1 else None
                else:
                    reasoning = after_reasoning.strip()
                    # 【思考過程】の前のテキストを応答として使用
                    pre_reasoning = parts[0].strip()
                    if pre_reasoning:
                        response = pre_reasoning
        elif "【応答】" in text:
            parts = text.split("【応答】")
            reasoning = parts[0].strip()
            response = parts[1].strip() if len(parts) > 1 else None
        else:
            # マークアップがない場合はテキスト全体を応答として扱う
            response = text.strip() if text.strip() else None

        return (reasoning, response)

    def _extract_confidence(
        self,
        reasoning: str,
        full_text: str,
    ) -> ConfidenceScores:
        """
        思考過程から確信度を抽出

        明示的な確信度表記（「確信度: 90%」など）を探し、
        見つからない場合はキーワードベースで推定する。

        Args:
            reasoning: 思考過程テキスト
            full_text: 全テキスト

        Returns:
            ConfidenceScores
        """
        combined_text = f"{reasoning} {full_text}"

        # 明示的な確信度表記を探す
        confidence_pattern = r"確信度[：:\s]*(\d+)%?"
        match = re.search(confidence_pattern, combined_text)

        if match:
            explicit_confidence = int(match.group(1)) / 100.0
            # 0.0〜1.0の範囲に収める
            explicit_confidence = max(0.0, min(1.0, explicit_confidence))
            return ConfidenceScores(
                overall=explicit_confidence,
                intent=explicit_confidence,
                parameters=explicit_confidence,
            )

        # キーワードベースで推定
        overall = 0.8  # デフォルト

        # 高確信度のキーワード
        high_confidence_keywords = ["確信", "明確", "間違いない", "確実", "必ず"]
        for kw in high_confidence_keywords:
            if kw in combined_text:
                overall = 0.9
                break

        # 中確信度のキーワード
        medium_confidence_keywords = ["おそらく", "たぶん", "だと思う", "かもしれない"]
        for kw in medium_confidence_keywords:
            if kw in combined_text:
                overall = 0.7
                break

        # 低確信度のキーワード
        low_confidence_keywords = ["分からない", "不明", "わかりません", "難しい"]
        for kw in low_confidence_keywords:
            if kw in combined_text:
                overall = 0.5
                break

        return ConfidenceScores(
            overall=overall,
            intent=overall,
            parameters=overall,
        )

    def _determine_output_type(
        self,
        tool_calls: List[ToolCall],
        confidence: ConfidenceScores,
    ) -> str:
        """
        出力タイプを決定

        Args:
            tool_calls: Tool呼び出しリスト
            confidence: 確信度

        Returns:
            出力タイプ（"tool_call" / "text_response" / "clarification_needed"）
        """
        if tool_calls:
            return "tool_call"
        elif confidence.overall < self.CONFIDENCE_THRESHOLD_CLARIFY:
            return "clarification_needed"
        else:
            return "text_response"

    def _determine_confirmation(
        self,
        tool_calls: List[ToolCall],
        confidence: ConfidenceScores,
        text_response: Optional[str],
        reasoning: str,
    ) -> Tuple[bool, Optional[str]]:
        """
        確認が必要かどうかを判定

        Args:
            tool_calls: Tool呼び出しリスト
            confidence: 確信度
            text_response: テキスト応答
            reasoning: 思考過程

        Returns:
            (needs_confirmation, confirmation_question) のタプル
        """
        needs_confirmation = confidence.overall < self.CONFIDENCE_THRESHOLD_AUTO_EXECUTE
        confirmation_question = None

        if needs_confirmation and not tool_calls:
            confirmation_question = self._generate_confirmation_question(
                text_response, reasoning
            )

        return (needs_confirmation, confirmation_question)

    def _generate_confirmation_question(
        self,
        text_response: Optional[str],
        reasoning: str,
    ) -> Optional[str]:
        """
        確認質問を生成

        Args:
            text_response: テキスト応答
            reasoning: 思考過程

        Returns:
            確認質問文、または None
        """
        if text_response and "？" in text_response:
            # 応答自体が質問形式の場合はそれを使用
            return None

        # デフォルトの確認質問
        return "この内容で進めてもいいですかウル？🐺"

    def _create_error_result(self, error_message: str) -> LLMBrainResult:
        """
        エラー時の結果を生成

        Args:
            error_message: エラーメッセージ

        Returns:
            エラーを示すLLMBrainResult
        """
        return LLMBrainResult(
            output_type="text_response",
            text_response=(
                f"申し訳ないウル、処理中にエラーが発生したウル 🐺\n"
                f"詳細: {error_message}"
            ),
            reasoning=f"API呼び出しでエラー: {error_message}",
            confidence=ConfidenceScores(overall=0.0, intent=0.0, parameters=0.0),
            needs_confirmation=False,
            api_provider=self.api_provider.value if hasattr(self, 'api_provider') else "",
        )


# =============================================================================
# ファクトリ関数
# =============================================================================

def create_llm_brain(
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    use_openrouter: bool = True,
) -> LLMBrain:
    """
    LLMBrainのファクトリ関数

    Args:
        model: 使用するモデル
        api_key: APIキー
        use_openrouter: OpenRouterを使用するか（デフォルト: True）

    Returns:
        LLMBrainインスタンス

    Raises:
        ValueError: APIキーが取得できない場合
    """
    return LLMBrain(
        model=model,
        api_key=api_key,
        use_openrouter=use_openrouter,
    )


def create_llm_brain_auto() -> LLMBrain:
    """
    自動設定でLLMBrainを作成

    OpenRouter APIキーが利用可能ならOpenRouterを使用し、
    なければAnthropic直接APIを使用する。

    Returns:
        LLMBrainインスタンス

    Raises:
        ValueError: どちらのAPIキーも取得できない場合
    """
    # OpenRouter優先
    openrouter_key = _get_openrouter_api_key()
    if openrouter_key:
        return LLMBrain(use_openrouter=True)

    # Anthropicフォールバック
    anthropic_key = _get_anthropic_api_key()
    if anthropic_key:
        return LLMBrain(use_openrouter=False)

    raise ValueError(
        "No API key available. "
        "Set OPENROUTER_API_KEY or ANTHROPIC_API_KEY environment variable, "
        "or configure 'openrouter-api-key' in Secret Manager."
    )
