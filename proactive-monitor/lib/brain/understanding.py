# lib/brain/understanding.py
"""
ソウルくんの脳 - 理解層（Understanding Layer）

このファイルには、ユーザーの入力から真の意図を推論する理解層を定義します。
省略の補完、曖昧性の解消、感情の検出等を行います。

設計書: docs/13_brain_architecture.md
設計書: docs/14_brain_refactoring_plan.md（Phase B: SYSTEM_CAPABILITIES拡張）

【理解の6つの要素】
1. 意図（Intent）: 何をしたいのか
2. 対象（Entity）: 誰/何について
3. 時間（Time）: いつのこと
4. 緊急度（Urgency）: どのくらい急ぎ
5. 感情（Emotion）: どんな気持ち
6. 文脈（Context）: 前の会話との繋がり

【v10.30.0 変更点】
- INTENT_KEYWORDSの静的定義を非推奨化
- SYSTEM_CAPABILITIESのbrain_metadata.intent_keywordsから動的にキーワード辞書を構築
- 新機能追加時はSYSTEM_CAPABILITIESへの追加のみで対応可能に（設計書7.3準拠）
- _calculate_intent_scoreにnegativeキーワード処理を追加
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple, Callable

from lib.brain.models import (
    BrainContext,
    UnderstandingResult,
    ResolvedEntity,
    UrgencyLevel,
    ConfidenceLevel,
)
from lib.brain.constants import (
    PRONOUNS,
    TIME_EXPRESSIONS,
    URGENCY_KEYWORDS,
    CONFIRMATION_THRESHOLD,
    AUTO_EXECUTE_THRESHOLD,
    DANGEROUS_ACTIONS,
)

logger = logging.getLogger(__name__)


# =============================================================================
# 感情検出の定数
# =============================================================================

EMOTION_KEYWORDS: Dict[str, List[str]] = {
    "困っている": [
        "困った", "困ってる", "困っている", "わからない", "分からない",
        "どうしよう", "どうすれば", "助けて", "ヘルプ", "help",
    ],
    "急いでいる": [
        "急いで", "急ぎ", "すぐ", "至急", "緊急", "今すぐ", "ASAP",
    ],
    "怒っている": [
        "なんで", "どうして", "ふざけ", "おかしい", "ありえない",
    ],
    "喜んでいる": [
        "うれしい", "嬉しい", "やった", "できた", "ありがとう", "感謝",
    ],
    "落ち込んでいる": [
        "だめ", "ダメ", "つらい", "辛い", "しんどい", "やる気でない",
        "モチベーション", "元気ない",
    ],
}

# =============================================================================
# 意図キーワードマッピング - フォールバック専用
# =============================================================================

# ⚠️ DEPRECATED (v10.30.0): このINTENT_KEYWORDS定数は非推奨です。
# 新しいアクションを追加する場合は、SYSTEM_CAPABILITIESのbrain_metadata.intent_keywords
# を使用してください。
#
# この定数は以下の目的でのみ残しています：
# 1. 後方互換性: brain_metadataがないアクションのフォールバック
# 2. 移行期間中のバックアップ
#
# 設計書参照: docs/13_brain_architecture.md セクション7.3
# 設計書参照: docs/14_brain_refactoring_plan.md Phase B
#
# 推奨される新しい方法:
# SYSTEM_CAPABILITIES["action_name"]["brain_metadata"]["intent_keywords"] = {
#     "primary": [...],
#     "secondary": [...],
#     "modifiers": [...],
#     "negative": [...],
#     "confidence_boost": 0.85,
# }
INTENT_KEYWORDS: Dict[str, Dict[str, Any]] = {
    "chatwork_task_create": {
        "primary": ["タスク作成", "タスク追加", "タスク作って", "依頼して", "お願い"],
        "secondary": ["タスク", "仕事", "やること"],
        "modifiers": ["作成", "追加", "作って", "お願い", "依頼"],
        "confidence_boost": 0.85,
    },
    "chatwork_task_search": {
        "primary": ["タスク検索", "タスク確認", "タスク教えて", "タスク一覧"],
        "secondary": ["タスク", "仕事", "やること"],
        "modifiers": ["検索", "教えて", "見せて", "一覧", "確認"],
        "confidence_boost": 0.85,
    },
    "chatwork_task_complete": {
        "primary": ["タスク完了", "タスク終わった", "タスクできた"],
        "secondary": ["タスク", "仕事"],
        "modifiers": ["完了", "終わった", "できた", "done", "済み"],
        "confidence_boost": 0.85,
    },
    # v10.44.0: goal_registration を精緻化、goal_review / goal_consult 追加
    # v10.47.0: 「目標設定したい」「目標を設定」「ゴールを決めたい」を追加（registry.pyと統一）
    "goal_registration": {
        "primary": ["目標登録", "目標を登録", "新しく目標", "目標を新規", "目標作成", "目標を作", "目標設定したい", "目標を設定", "目標を立てたい", "ゴールを決めたい", "ゴール設定", "ゴールを設定"],
        "secondary": ["登録したい", "作りたい", "新規作成", "設定したい", "立てたい", "決めたい"],
        "modifiers": ["登録", "新規", "新しく", "作成", "設定", "立て", "決め"],
        "negative": ["一覧", "表示", "出して", "確認", "整理", "削除", "修正", "過去", "登録済み", "もともと", "多すぎ", "ぐちゃぐちゃ", "どっち優先", "理由", "数字で", "どう決める", "迷う", "方針", "進捗", "報告", "状況", "どうなった"],
        "confidence_boost": 0.85,
    },
    "goal_review": {
        # v10.52.0: 他ドメインとの誤マッチを防ぐため、目標固有の表現のみに限定
        "primary": ["目標一覧", "目標を見せて", "目標を表示", "目標を出して", "登録済みの目標", "過去の目標", "ゴール一覧", "ゴールを見せて"],
        # secondaryからドメイン非依存のキーワードを削除（"一覧", "削除", "見せて"等）
        "secondary": ["目標", "ゴール"],
        "modifiers": ["整理", "修正", "多すぎ", "ぐちゃぐちゃ", "過去", "もともと", "登録済み", "最新"],
        "negative": ["登録したい", "新規", "新しく", "作りたい", "設定したい", "タスク", "仕事", "組織図", "組織", "ナレッジ", "知識", "部署"],
        "confidence_boost": 0.90,
    },
    "goal_consult": {
        "primary": ["どっち優先", "どう決めたらいい", "目標相談", "目標の決め方", "優先順位"],
        "secondary": ["迷う", "迷って", "方針", "アドバイス", "理由", "数字で", "どっちがいい"],
        "modifiers": ["相談", "教えて", "アドバイス"],
        "negative": ["登録したい", "一覧", "表示", "整理"],
        "confidence_boost": 0.90,
    },
    "goal_progress_report": {
        "primary": ["目標進捗", "目標報告"],
        "secondary": ["目標", "ゴール"],
        "modifiers": ["進捗", "報告", "どれくらい"],
        "negative": ["一覧", "表示", "整理", "設定したい", "立てたい", "登録したい", "作りたい", "新規", "決めたい"],
        "confidence_boost": 0.8,
    },
    "goal_status_check": {
        # v10.52.0: "どうなった" パターンを追加
        "primary": ["達成率", "進捗確認", "どれくらい達成", "目標の進捗", "目標どうなった", "目標どうなってる"],
        "secondary": ["進捗", "状況", "どうなった", "どうなってる"],
        "modifiers": ["確認", "教えて"],
        "negative": ["一覧", "表示", "整理", "削除", "修正", "設定", "登録", "新規"],
        "confidence_boost": 0.85,  # 0.8 → 0.85 に上げて goal_progress_report より優先
    },
    "save_memory": {
        "primary": ["人を覚えて", "社員を記憶"],
        "secondary": ["覚えて", "記憶して", "メモして"],
        "modifiers": ["人", "さん", "社員"],
        "confidence_boost": 0.85,
    },
    "learn_knowledge": {
        "primary": ["知識を覚えて", "ナレッジ追加"],
        "secondary": ["覚えて", "記憶して", "メモして"],
        "modifiers": [],
        "confidence_boost": 0.8,
    },
    "forget_knowledge": {
        # v10.52.0: ナレッジ削除パターンを拡充、confidence_boostを上げる
        "primary": ["知識を忘れて", "ナレッジ削除", "ナレッジを削除", "知識を削除", "覚えたことを削除"],
        "secondary": ["忘れて", "削除して", "消して"],
        "modifiers": ["削除", "消す", "忘れ"],
        "confidence_boost": 0.85,
    },
    "query_knowledge": {
        "primary": ["教えて", "知りたい"],
        "secondary": ["就業規則", "規則", "ルール", "マニュアル", "手順", "方法"],
        "modifiers": [],
        "confidence_boost": 0.8,
    },
    "query_org_chart": {
        # v10.52.0: 組織図表示パターンを拡充、confidence_boostを上げる
        "primary": ["組織図", "部署一覧", "組織図を見せて", "組織構造"],
        "secondary": ["組織", "部署", "チーム", "誰が", "担当者", "上司", "部下"],
        "modifiers": ["見せて", "表示", "教えて"],
        "confidence_boost": 0.85,
    },
    "announcement_create": {
        "primary": ["アナウンスして", "お知らせして"],
        "secondary": ["アナウンス", "お知らせ", "連絡して", "送って"],
        "modifiers": [],
        "confidence_boost": 0.8,
    },
    "daily_reflection": {
        "primary": ["振り返り", "日報"],
        "secondary": ["今日一日", "反省"],
        "modifiers": [],
        "confidence_boost": 0.75,
    },
    "general_conversation": {
        "primary": [],
        "secondary": [],
        "modifiers": [],
        "confidence_boost": 0.5,
    },
    # v10.44.1: Connection Query（DM可能な相手一覧）- 優先度強化
    "connection_query": {
        "primary": [
            "DMできる相手",
            "DMできる人",
            "1on1で繋がってる",
            "直接チャットできる相手",
            "個別で繋がってる人",
        ],
        "secondary": [
            "DM", "1on1", "個別", "繋がってる", "直接", "話せる", "チャットできる",
        ],
        "modifiers": [
            "教えて", "一覧", "誰", "全員", "名前", "どんな人",
        ],
        "negative": ["タスク", "目標", "記憶", "覚えて"],
        "confidence_boost": 1.2,  # 最優先に近づける
    },
}


# =============================================================================
# LLMプロンプト
# =============================================================================

UNDERSTANDING_PROMPT = """あなたは「ソウルくん」の理解層です。
ユーザーの発言から、真の意図を推論してください。

【あなたの仕事】
1. ユーザーが「何をしたいのか」を推論する
2. 省略されている情報を、コンテキストから補完する
3. 曖昧な表現を具体的に解決する
4. 確信度を評価する（0.0〜1.0）

【コンテキスト情報】
{context}

【ユーザーの発言】
{message}

【認識可能な意図】
- chatwork_task_create: タスクを作成・追加・依頼
- chatwork_task_search: タスクを検索・確認・一覧表示
- chatwork_task_complete: タスクを完了
- goal_registration: 目標設定を開始
- goal_progress_report: 目標の進捗を報告
- goal_status_check: 目標の状況を確認
- save_memory: 人物情報を記憶
- learn_knowledge: 知識・ナレッジを記憶
- forget_knowledge: 知識・ナレッジを削除
- query_knowledge: 会社知識・ナレッジを検索
- query_org_chart: 組織・部署・担当者を確認
- announcement_create: アナウンス・お知らせを送信
- daily_reflection: 振り返り・日報を作成
- general_conversation: 一般的な会話・雑談

【出力形式】
必ず以下のJSON形式で出力してください。他の文字は含めないでください。
{{
  "intent": "推論した意図（上記のいずれか）",
  "entities": {{
    "person": "対象の人物（解決済み）",
    "object": "対象の物事",
    "time": "時間（解決済み、ISO形式またはnull）",
    "urgency": "low/medium/high"
  }},
  "resolved_ambiguities": [
    {{"original": "曖昧表現", "resolved": "解決後", "source": "解決に使った情報源"}}
  ],
  "confidence": 0.0から1.0の数値,
  "reasoning": "この推論をした理由（日本語で簡潔に）",
  "detected_emotion": "検出した感情（困っている/急いでいる/怒っている/喜んでいる/落ち込んでいる/なし）",
  "needs_confirmation": true または false,
  "confirmation_options": ["候補1", "候補2"]
}}
"""


# =============================================================================
# BrainUnderstandingクラス
# =============================================================================


class BrainUnderstanding:
    """
    脳の理解層

    ユーザーの入力から真の意図を推論する。
    省略の補完、曖昧性の解消、感情の検出等を行う。

    v10.30.0: SYSTEM_CAPABILITIESのbrain_metadata.intent_keywordsから
    動的にキーワード辞書を構築するように変更。

    使用例:
        understanding = BrainUnderstanding(
            capabilities=SYSTEM_CAPABILITIES,  # v10.30.0追加
            get_ai_response_func=get_ai_response,
            org_id="org_soulsyncs"
        )
        result = await understanding.understand(
            message="あれどうなった？",
            context=brain_context
        )
    """

    def __init__(
        self,
        capabilities: Optional[Dict[str, Dict]] = None,
        get_ai_response_func: Optional[Callable] = None,
        org_id: str = "",
        use_llm: bool = True,
    ):
        """
        Args:
            capabilities: SYSTEM_CAPABILITIES（機能カタログ）v10.30.0追加
            get_ai_response_func: AI応答生成関数
            org_id: 組織ID
            use_llm: LLMを使用するかどうか（Falseならキーワードマッチのみ）
        """
        self.capabilities = capabilities or {}
        self.get_ai_response = get_ai_response_func
        self.org_id = org_id
        self.use_llm = use_llm and get_ai_response_func is not None

        # 有効な機能のみをフィルタ
        self.enabled_capabilities = {
            key: cap for key, cap in self.capabilities.items()
            if cap.get("enabled", True)
        }

        # v10.30.0: SYSTEM_CAPABILITIESのbrain_metadataから動的にキーワード辞書を構築
        # 設計書7.3準拠: INTENT_KEYWORDSをSYSTEM_CAPABILITIESに統合
        self.intent_keywords = self._build_intent_keywords()

        logger.info(
            f"BrainUnderstanding initialized: org_id={org_id}, "
            f"capabilities={len(self.enabled_capabilities)}, "
            f"intent_keywords={len(self.intent_keywords)}, "
            f"use_llm={self.use_llm}"
        )

    # =========================================================================
    # キーワード辞書の動的構築（v10.30.0）
    # =========================================================================

    def _build_intent_keywords(self) -> Dict[str, Dict[str, Any]]:
        """
        SYSTEM_CAPABILITIESのbrain_metadataからキーワード辞書を動的に構築

        設計書7.3準拠: INTENT_KEYWORDSをSYSTEM_CAPABILITIESに統合
        これにより、新機能追加時にSYSTEM_CAPABILITIESへの追加のみで対応可能に。

        後方互換性: capabilitiesが渡されていない場合は、静的なINTENT_KEYWORDSを返す

        構築される辞書の形式:
        {
            "action_key": {
                "primary": ["キーワード1", "キーワード2"],
                "secondary": ["キーワード3"],
                "modifiers": ["修飾語"],
                "negative": ["除外ワード"],
                "confidence_boost": 0.85,
            }
        }

        Returns:
            Dict[str, Dict[str, Any]]: アクション名をキーとしたキーワード辞書
        """
        # 後方互換性: capabilitiesが渡されていない場合は静的INTENT_KEYWORDSを使用
        if not self.enabled_capabilities:
            logger.debug(
                "No capabilities provided, using static INTENT_KEYWORDS for backward compatibility"
            )
            return INTENT_KEYWORDS.copy()

        keywords = {}

        for key, cap in self.enabled_capabilities.items():
            brain_metadata = cap.get("brain_metadata", {})
            intent_keywords = brain_metadata.get("intent_keywords", {})

            if intent_keywords:
                # brain_metadataから取得
                keywords[key] = {
                    "primary": intent_keywords.get("primary", []),
                    "secondary": intent_keywords.get("secondary", []),
                    "modifiers": intent_keywords.get("modifiers", []),
                    "negative": intent_keywords.get("negative", []),
                    "confidence_boost": intent_keywords.get("confidence_boost", 0.8),
                }
            else:
                # brain_metadataがない場合はフォールバック（後方互換性）
                # INTENT_KEYWORDS（静的定義）から取得
                fallback = INTENT_KEYWORDS.get(key, {})
                if fallback:
                    keywords[key] = fallback
                    logger.debug(
                        f"Using fallback INTENT_KEYWORDS for '{key}' "
                        "(brain_metadata.intent_keywords not found)"
                    )

        # 統計情報をログ出力
        from_metadata = sum(
            1 for k in keywords
            if self.enabled_capabilities.get(k, {}).get("brain_metadata", {}).get("intent_keywords")
        )
        from_fallback = len(keywords) - from_metadata

        logger.debug(
            f"Intent keywords built: "
            f"total={len(keywords)}, "
            f"from_metadata={from_metadata}, "
            f"from_fallback={from_fallback}"
        )

        return keywords

    # =========================================================================
    # メインエントリーポイント
    # =========================================================================

    async def understand(
        self,
        message: str,
        context: BrainContext,
    ) -> UnderstandingResult:
        """
        ユーザーの入力から意図を推論

        Args:
            message: ユーザーのメッセージ
            context: 脳のコンテキスト（記憶層から取得）

        Returns:
            UnderstandingResult: 理解結果
        """
        start_time = time.time()

        try:
            # Step 1: 前処理
            normalized = message.strip()

            # Step 2: 代名詞の検出
            detected_pronouns = self._detect_pronouns(normalized)

            # Step 3: 省略の検出
            detected_abbreviations = self._detect_abbreviations(normalized, context)

            # Step 4: 緊急度の検出
            urgency = self._detect_urgency(normalized)

            # Step 5: 感情の検出
            emotion = self._detect_emotion(normalized)

            # Step 6: LLMまたはキーワードマッチで意図を推論
            if self.use_llm and (detected_pronouns or detected_abbreviations):
                # LLMを使って曖昧性を解決
                result = await self._understand_with_llm(
                    message=normalized,
                    context=context,
                    detected_pronouns=detected_pronouns,
                    detected_abbreviations=detected_abbreviations,
                    urgency=urgency,
                    emotion=emotion,
                )
            else:
                # キーワードマッチ（フォールバック）
                result = self._understand_with_keywords(
                    message=normalized,
                    context=context,
                    urgency=urgency,
                    emotion=emotion,
                )

            # Step 7: 代名詞の解決（LLMで解決できなかった場合）
            if detected_pronouns and not result.resolved_ambiguities:
                resolved = self._resolve_pronouns(
                    message=normalized,
                    pronouns=detected_pronouns,
                    context=context,
                )
                result.resolved_ambiguities.extend(resolved)
                # 解決できなかった場合は確認モード
                if any(r.resolved == r.original for r in resolved):
                    result.needs_confirmation = True
                    result.confirmation_reason = "曖昧な表現があります"
                    result.confirmation_options = self._generate_confirmation_options(
                        pronouns=detected_pronouns,
                        context=context,
                    )

            # Step 8: 処理時間を記録
            result.processing_time_ms = self._elapsed_ms(start_time)

            logger.info(
                f"Understanding complete: intent={result.intent}, "
                f"confidence={result.intent_confidence:.2f}, "
                f"time={result.processing_time_ms}ms"
            )

            return result

        except Exception as e:
            logger.error(f"Error in understanding: {type(e).__name__}")
            # v10.29.5: Codex指摘修正 - エラー詳細をユーザーに見せない（10の鉄則準拠）
            # 内部エラー情報はログのみに記録し、ユーザーには汎用メッセージを表示
            return UnderstandingResult(
                raw_message=message,
                intent="general_conversation",
                intent_confidence=0.3,
                entities={},
                needs_confirmation=True,
                confirmation_reason="もう少し詳しく教えていただけますか？",
                reasoning="Understanding error occurred",  # 内部用（ユーザーには非表示）
                processing_time_ms=self._elapsed_ms(start_time),
            )

    # =========================================================================
    # LLMを使った理解
    # =========================================================================

    async def _understand_with_llm(
        self,
        message: str,
        context: BrainContext,
        detected_pronouns: List[str],
        detected_abbreviations: List[str],
        urgency: str,
        emotion: str,
    ) -> UnderstandingResult:
        """
        LLMを使って意図を推論

        曖昧表現がある場合にLLMを使用する。
        """
        try:
            # コンテキストをプロンプト用に整形
            context_text = self._format_context_for_prompt(context)

            # プロンプト生成
            prompt = UNDERSTANDING_PROMPT.format(
                context=context_text,
                message=message,
            )

            # LLM呼び出し
            if self.get_ai_response:
                response = await self._call_llm(prompt)

                if response:
                    # レスポンスをパース
                    parsed = self._parse_llm_response(response)

                    if parsed:
                        return UnderstandingResult(
                            raw_message=message,
                            intent=parsed.get("intent", "general_conversation"),
                            intent_confidence=parsed.get("confidence", 0.5),
                            entities=parsed.get("entities", {}),
                            resolved_ambiguities=[
                                ResolvedEntity(
                                    original=a.get("original", ""),
                                    resolved=a.get("resolved", ""),
                                    entity_type="unknown",
                                    source=a.get("source", "LLM"),
                                )
                                for a in parsed.get("resolved_ambiguities", [])
                            ],
                            needs_confirmation=parsed.get("needs_confirmation", False),
                            confirmation_options=parsed.get("confirmation_options", []),
                            reasoning=parsed.get("reasoning", "LLM推論"),
                        )

            # LLM失敗時はキーワードマッチにフォールバック
            logger.warning("LLM understanding failed, falling back to keywords")
            return self._understand_with_keywords(
                message=message,
                context=context,
                urgency=urgency,
                emotion=emotion,
            )

        except Exception as e:
            logger.error(f"Error in LLM understanding: {type(e).__name__}")
            return self._understand_with_keywords(
                message=message,
                context=context,
                urgency=urgency,
                emotion=emotion,
            )

    async def _call_llm(self, prompt: str) -> Optional[str]:
        """
        LLMを呼び出す

        get_ai_response_funcをラップして呼び出す。
        """
        try:
            if self.get_ai_response:
                import asyncio
                if asyncio.iscoroutinefunction(self.get_ai_response):
                    result: Optional[str] = await self.get_ai_response(prompt)
                    return result
                else:
                    # 同期関数はイベントループをブロックするためto_threadで実行
                    sync_result: Optional[str] = await asyncio.to_thread(
                        self.get_ai_response, prompt
                    )
                    return sync_result
            return None
        except Exception as e:
            logger.error(f"Error calling LLM: {type(e).__name__}")
            return None

    def _parse_llm_response(self, response: str) -> Optional[Dict[str, Any]]:
        """
        LLMレスポンスをパース

        JSONを抽出してパースする。
        """
        try:
            # JSON部分を抽出
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                json_str = json_match.group()
                parsed: Dict[str, Any] = json.loads(json_str)
                return parsed
            return None
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM response as JSON: {type(e).__name__}")
            return None

    def _format_context_for_prompt(self, context: BrainContext) -> str:
        """
        コンテキストをプロンプト用に整形
        """
        parts = []

        # 直近の会話
        if context.recent_conversation:
            parts.append("【直近の会話】")
            for msg in context.recent_conversation[-5:]:  # 最新5件
                role = "ユーザー" if msg.role == "user" else "ソウルくん"
                parts.append(f"  {role}: {msg.content[:100]}")

        # 直近のタスク
        if context.recent_tasks:
            parts.append("\n【直近のタスク】")
            for task in context.recent_tasks[:3]:  # 最新3件
                # taskはdictまたはオブジェクトの可能性がある
                body = task.get("body", "") if isinstance(task, dict) else getattr(task, "body", "")
                assignee = task.get("assignee_name", "") if isinstance(task, dict) else getattr(task, "assignee_name", "")
                if body:
                    parts.append(f"  - {body[:50]}（{assignee}）")

        # 人物情報
        # person_infoはPersonInfoデータクラスまたはdictの可能性がある
        if context.person_info:
            parts.append("\n【記憶している人物】")
            names = []
            for p in context.person_info[:5]:
                name = p.get("name") if isinstance(p, dict) else getattr(p, "name", None)
                if name:
                    names.append(name)
            if names:
                parts.append(f"  {', '.join(names)}")

        # アクティブな目標
        if context.active_goals:
            parts.append("\n【アクティブな目標】")
            for goal in context.active_goals[:2]:
                parts.append(f"  - {goal.title}")

        return "\n".join(parts) if parts else "（コンテキストなし）"

    # =========================================================================
    # キーワードマッチによる理解（フォールバック）
    # =========================================================================

    def _understand_with_keywords(
        self,
        message: str,
        context: BrainContext,
        urgency: str = "low",
        emotion: str = "",
    ) -> UnderstandingResult:
        """
        キーワードマッチで意図を推論（フォールバック）

        LLMを使わない簡易的な意図推論。

        v10.30.0: SYSTEM_CAPABILITIESのbrain_metadata.intent_keywordsから
        動的に構築されたself.intent_keywordsを使用。
        """
        normalized = message.lower().strip()

        best_intent = "general_conversation"
        best_confidence = 0.5
        entities: Dict[str, Any] = {}

        # v10.30.0: インスタンス変数から動的に取得（旧: INTENT_KEYWORDS定数）
        # 各意図についてスコアリング
        for intent, keywords in self.intent_keywords.items():
            score = self._calculate_intent_score(normalized, keywords)
            if score > best_confidence:
                best_confidence = score
                best_intent = intent

        # エンティティを抽出
        entities = self._extract_entities(message, context)
        entities["urgency"] = urgency

        # 確認が必要か判定
        needs_confirmation = best_confidence < CONFIRMATION_THRESHOLD

        return UnderstandingResult(
            raw_message=message,
            intent=best_intent,
            intent_confidence=best_confidence,
            entities=entities,
            needs_confirmation=needs_confirmation,
            confirmation_reason="確信度が低いです" if needs_confirmation else None,
            reasoning=f"Keyword matching: {best_intent} (confidence: {best_confidence:.2f})",
        )

    def _calculate_intent_score(
        self,
        message: str,
        keywords: Dict[str, Any],
    ) -> float:
        """
        意図のスコアを計算

        v10.30.0: SYSTEM_CAPABILITIESのbrain_metadata.intent_keywordsから
        動的に構築されたキーワード辞書を使用。

        スコアリングロジック:
        - negativeキーワードがあれば即座に0.0
        - プライマリキーワード: マッチでconfidence_boost（デフォルト0.8）
        - セカンダリ+モディファイア: 両方マッチでconfidence_boost
        - セカンダリのみ: confidence_boost - 0.15

        Args:
            message: 小文字化されたメッセージ
            keywords: キーワード辞書（primary, secondary, modifiers, negative, confidence_boost）

        Returns:
            float: 意図マッチスコア（0.0〜1.0）
        """
        score = 0.0

        # v10.30.0: negativeキーワードチェック（decision.pyと同様）
        negative = keywords.get("negative", [])
        for neg in negative:
            if neg in message:
                return 0.0

        # プライマリキーワード（完全マッチ）
        primary = keywords.get("primary", [])
        for kw in primary:
            if kw in message:
                score = max(score, keywords.get("confidence_boost", 0.8))
                break

        # セカンダリ + モディファイア
        secondary = keywords.get("secondary", [])
        modifiers = keywords.get("modifiers", [])

        has_secondary = any(kw in message for kw in secondary)
        has_modifier = any(kw in message for kw in modifiers)

        if has_secondary and has_modifier:
            score = max(score, keywords.get("confidence_boost", 0.8))
        elif has_secondary:
            score = max(score, keywords.get("confidence_boost", 0.8) - 0.15)

        return score

    def _extract_entities(
        self,
        message: str,
        context: BrainContext,
    ) -> Dict[str, Any]:
        """
        メッセージからエンティティを抽出
        """
        entities: Dict[str, Any] = {}

        # 人物名の抽出
        # person_infoはPersonInfoデータクラスまたはdictの可能性がある
        if context.person_info:
            for person in context.person_info:
                # dictの場合とdataclassの場合の両方に対応
                person_name = person.get("name") if isinstance(person, dict) else getattr(person, "name", None)
                if person_name and person_name in message:
                    entities["person"] = person_name
                    break

        # 時間表現の解決
        for expr, meaning in TIME_EXPRESSIONS.items():
            if expr in message:
                entities["time_expression"] = expr
                entities["time"] = self._resolve_time_expression(meaning)
                break

        return entities

    def _resolve_time_expression(self, meaning: str) -> Optional[str]:
        """
        時間表現を具体的な日時に解決
        """
        now = datetime.now()

        mappings = {
            "today": now.date().isoformat(),
            "tomorrow": (now + timedelta(days=1)).date().isoformat(),
            "day_after_tomorrow": (now + timedelta(days=2)).date().isoformat(),
            "yesterday": (now - timedelta(days=1)).date().isoformat(),
            "day_before_yesterday": (now - timedelta(days=2)).date().isoformat(),
            "next_week": (now + timedelta(weeks=1)).date().isoformat(),
            "last_week": (now - timedelta(weeks=1)).date().isoformat(),
            "this_week": now.date().isoformat(),
            "next_month": (now.replace(day=1) + timedelta(days=32)).replace(day=1).isoformat(),
            "last_month": (now.replace(day=1) - timedelta(days=1)).replace(day=1).isoformat(),
            "this_month": now.replace(day=1).date().isoformat(),
        }

        return mappings.get(meaning)

    # =========================================================================
    # 代名詞の検出と解決
    # =========================================================================

    def _detect_pronouns(self, message: str) -> List[str]:
        """
        メッセージから代名詞を検出
        """
        detected = []
        for pronoun in PRONOUNS:
            if pronoun in message:
                detected.append(pronoun)
        return detected

    def _resolve_pronouns(
        self,
        message: str,
        pronouns: List[str],
        context: BrainContext,
    ) -> List[ResolvedEntity]:
        """
        代名詞を解決

        直近の会話やタスクから候補を抽出し、解決を試みる。
        """
        resolved = []

        for pronoun in pronouns:
            candidates = self._get_pronoun_candidates(pronoun, context)

            if len(candidates) == 1:
                # 候補が1つなら自動解決
                resolved.append(ResolvedEntity(
                    original=pronoun,
                    resolved=candidates[0]["value"],
                    entity_type=candidates[0]["type"],
                    source=candidates[0]["source"],
                    confidence=0.8,
                ))
            elif len(candidates) > 1:
                # 候補が複数なら解決失敗（確認モードへ）
                resolved.append(ResolvedEntity(
                    original=pronoun,
                    resolved=pronoun,  # 解決できず
                    entity_type="ambiguous",
                    source="multiple_candidates",
                    confidence=0.3,
                ))
            else:
                # 候補なし
                resolved.append(ResolvedEntity(
                    original=pronoun,
                    resolved=pronoun,  # 解決できず
                    entity_type="unknown",
                    source="no_candidates",
                    confidence=0.2,
                ))

        return resolved

    def _get_pronoun_candidates(
        self,
        pronoun: str,
        context: BrainContext,
    ) -> List[Dict[str, Any]]:
        """
        代名詞の解決候補を取得
        """
        candidates = []

        # 「あの人」「その人」などの人物代名詞
        if "人" in pronoun:
            # 直近の会話から人物を抽出
            if context.recent_conversation:
                for msg in reversed(context.recent_conversation):
                    if msg.sender_name:
                        candidates.append({
                            "value": msg.sender_name,
                            "type": "person",
                            "source": "recent_conversation",
                        })
                        break

        # 「あれ」「それ」などの物事代名詞
        else:
            # 直近のタスクから候補を抽出
            if context.recent_tasks:
                for task in context.recent_tasks[:3]:
                    # taskはdictまたはオブジェクトの可能性がある
                    body = task.get("body", "") if isinstance(task, dict) else getattr(task, "body", "")
                    if body:
                        candidates.append({
                            "value": body[:30],
                            "type": "task",
                            "source": "recent_tasks",
                        })

            # 直近の会話から話題を抽出
            if context.recent_conversation:
                for msg in reversed(context.recent_conversation[-3:]):
                    if msg.role == "user":
                        # 会話の主要なトピックを抽出（簡易的に最初の名詞句）
                        candidates.append({
                            "value": msg.content[:30],
                            "type": "topic",
                            "source": "recent_conversation",
                        })
                        break

        return candidates[:5]  # 最大5候補

    # =========================================================================
    # 省略の検出と補完
    # =========================================================================

    def _detect_abbreviations(
        self,
        message: str,
        context: BrainContext,
    ) -> List[str]:
        """
        省略されている情報を検出

        「完了にして」（何を？）、「送って」（誰に？何を？）等
        """
        abbreviations = []

        # 動詞のみで目的語がない場合
        verb_only_patterns = [
            (r"完了(にして|して)", "タスクの指定がありません"),
            (r"送って", "送信先・内容の指定がありません"),
            (r"教えて$", "知りたい内容の指定がありません"),
            (r"作って$", "作成内容の指定がありません"),
            (r"追加して$", "追加内容の指定がありません"),
            (r"削除して$", "削除対象の指定がありません"),
        ]

        for pattern, reason in verb_only_patterns:
            if re.search(pattern, message):
                # コンテキストから補完可能か確認
                can_complete = self._can_complete_abbreviation(pattern, context)
                if not can_complete:
                    abbreviations.append(reason)

        return abbreviations

    def _can_complete_abbreviation(
        self,
        pattern: str,
        context: BrainContext,
    ) -> bool:
        """
        省略が補完可能か判定
        """
        if "完了" in pattern:
            # 直近のタスクが1つなら補完可能
            return len(context.recent_tasks) == 1

        if "送って" in pattern:
            # 直近の会話で送信先が言及されていれば補完可能
            if context.recent_conversation:
                for msg in reversed(context.recent_conversation[-3:]):
                    # person_infoはPersonInfoデータクラスまたはdictの可能性がある
                    person_names = [
                        p.get("name") if isinstance(p, dict) else getattr(p, "name", None)
                        for p in context.person_info
                    ]
                    if "に" in msg.content and any(
                        name and name in msg.content for name in person_names
                    ):
                        return True
            return False

        return False

    # =========================================================================
    # 緊急度と感情の検出
    # =========================================================================

    def _detect_urgency(self, message: str) -> str:
        """
        メッセージから緊急度を検出
        """
        for keyword, level in URGENCY_KEYWORDS.items():
            if keyword in message:
                urgency_level: str = str(level)
                return urgency_level
        return "low"

    def _detect_emotion(self, message: str) -> str:
        """
        メッセージから感情を検出
        """
        for emotion, keywords in EMOTION_KEYWORDS.items():
            for keyword in keywords:
                if keyword in message:
                    return emotion
        return ""

    # =========================================================================
    # 確認モード
    # =========================================================================

    def _generate_confirmation_options(
        self,
        pronouns: List[str],
        context: BrainContext,
    ) -> List[str]:
        """
        確認モードの選択肢を生成
        """
        options = []

        for pronoun in pronouns:
            candidates = self._get_pronoun_candidates(pronoun, context)
            for candidate in candidates[:3]:
                options.append(candidate["value"])

        return list(dict.fromkeys(options))[:4]  # 重複排除、最大4つ

    # =========================================================================
    # ヘルパー
    # =========================================================================

    def _elapsed_ms(self, start_time: float) -> int:
        """経過時間をミリ秒で返す"""
        return int((time.time() - start_time) * 1000)


# =============================================================================
# モジュールレベルのヘルパー関数
# =============================================================================


def is_ambiguous_message(message: str) -> bool:
    """
    メッセージが曖昧かどうかを判定

    代名詞や省略が含まれている場合にTrueを返す。
    """
    for pronoun in PRONOUNS:
        if pronoun in message:
            return True

    # 短すぎるメッセージ
    if len(message.strip()) < 5:
        return True

    return False


def extract_intent_keywords(message: str) -> List[str]:
    """
    メッセージから意図を示すキーワードを抽出
    """
    keywords = []
    normalized = message.lower()

    all_keywords = []
    for intent_data in INTENT_KEYWORDS.values():
        all_keywords.extend(intent_data.get("primary", []))
        all_keywords.extend(intent_data.get("secondary", []))
        all_keywords.extend(intent_data.get("modifiers", []))

    for kw in set(all_keywords):
        if kw and kw in normalized:
            keywords.append(kw)

    return keywords
