# lib/capabilities/generation/base.py
"""
Phase G1: 文書生成能力 - 基底クラス

このモジュールは、生成プロセッサーの基底クラスを提供します。

設計書: docs/20_next_generation_capabilities.md セクション6
Author: Claude Opus 4.5
Created: 2026-01-27
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, TYPE_CHECKING
from uuid import UUID
import logging
import os
import json
import httpx

from .constants import (
    GenerationType,
    GenerationStatus,
    QualityLevel,
    DEFAULT_GENERATION_MODEL,
    HIGH_QUALITY_MODEL,
    FAST_MODEL,
    TEMPERATURE_SETTINGS,
)
from .models import (
    GenerationMetadata,
    GenerationInput,
    GenerationOutput,
)

if TYPE_CHECKING:
    from asyncpg import Pool


# =============================================================================
# ロガー設定
# =============================================================================

logger = logging.getLogger(__name__)


# =============================================================================
# LLMクライアント
# =============================================================================


class LLMClient:
    """
    LLMクライアント

    OpenRouter/Anthropic APIを使用してLLM呼び出しを行う。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://openrouter.ai/api/v1",
        default_model: str = DEFAULT_GENERATION_MODEL,
        timeout_seconds: int = 120,
    ):
        """
        初期化

        Args:
            api_key: API Key（省略時は環境変数から取得）
            base_url: APIのベースURL
            default_model: デフォルトモデル
            timeout_seconds: タイムアウト秒数
        """
        self._api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        self._base_url = base_url
        self._default_model = default_model
        self._timeout_seconds = timeout_seconds

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        response_format: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        テキストを生成

        Args:
            prompt: ユーザープロンプト
            system_prompt: システムプロンプト
            model: 使用モデル
            temperature: 温度パラメータ
            max_tokens: 最大トークン数
            response_format: レスポンス形式（"json"など）

        Returns:
            生成結果（text, tokens_used, model等）
        """
        model = model or self._default_model

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if response_format == "json":
            # Anthropicモデルの場合はJSONモードを指定
            if "claude" in model.lower():
                # Claude はresponse_formatをサポートしていないため、プロンプトで指示
                pass
            else:
                payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://soulsyncs.co.jp",
            "X-Title": "Soul-kun Generation",
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                result = response.json()

                # レスポンス解析
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                usage = result.get("usage", {})

                return {
                    "text": content,
                    "model": model,
                    "input_tokens": usage.get("prompt_tokens", 0),
                    "output_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                }

        except httpx.HTTPStatusError as e:
            logger.error(f"LLM API error: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"LLM call failed: {str(e)}")
            raise

    async def generate_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.3,
    ) -> Dict[str, Any]:
        """
        JSON形式でテキストを生成

        Args:
            prompt: ユーザープロンプト
            system_prompt: システムプロンプト
            model: 使用モデル
            temperature: 温度パラメータ

        Returns:
            パース済みJSONオブジェクト
        """
        # プロンプトにJSON指示を追加
        json_instruction = "\n\n必ずJSON形式で出力してください。コードブロックは使わず、純粋なJSONのみを出力してください。"
        enhanced_prompt = prompt + json_instruction

        result = await self.generate(
            prompt=enhanced_prompt,
            system_prompt=system_prompt,
            model=model,
            temperature=temperature,
            response_format="json",
        )

        text = result.get("text", "")

        # JSONをパース
        try:
            # コードブロックを除去
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]

            parsed = json.loads(text.strip())
            result["parsed"] = parsed
            return result

        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse failed: {str(e)}, text: {text[:200]}")
            result["parsed"] = None
            result["parse_error"] = str(e)
            return result

    def get_model_for_quality(self, quality_level: QualityLevel) -> str:
        """品質レベルに応じたモデルを取得"""
        if quality_level == QualityLevel.PREMIUM:
            return HIGH_QUALITY_MODEL
        elif quality_level == QualityLevel.HIGH_QUALITY:
            return HIGH_QUALITY_MODEL
        elif quality_level == QualityLevel.DRAFT:
            return FAST_MODEL
        return DEFAULT_GENERATION_MODEL


# =============================================================================
# 基底ジェネレーター
# =============================================================================


class BaseGenerator(ABC):
    """
    生成プロセッサーの基底クラス

    全ての生成タイプに共通する機能を提供。
    """

    def __init__(
        self,
        pool: "Pool",
        organization_id: UUID,
        api_key: Optional[str] = None,
    ):
        """
        初期化

        Args:
            pool: データベース接続プール
            organization_id: 組織ID
            api_key: LLM API Key
        """
        self._pool = pool
        self._organization_id = organization_id
        self._llm_client = LLMClient(api_key=api_key)
        self._generation_type = GenerationType.DOCUMENT  # サブクラスで上書き

    @property
    def generation_type(self) -> GenerationType:
        """生成タイプを取得"""
        return self._generation_type

    @abstractmethod
    async def generate(self, input_data: GenerationInput) -> GenerationOutput:
        """
        生成を実行

        Args:
            input_data: 入力データ

        Returns:
            生成結果
        """
        pass

    @abstractmethod
    def validate(self, input_data: GenerationInput) -> None:
        """
        入力を検証

        Args:
            input_data: 入力データ

        Raises:
            ValidationError: 検証エラー
        """
        pass

    # =========================================================================
    # ユーティリティメソッド
    # =========================================================================

    def _create_metadata(
        self,
        user_id: Optional[UUID] = None,
    ) -> GenerationMetadata:
        """メタデータを作成"""
        return GenerationMetadata(
            organization_id=self._organization_id,
            user_id=user_id,
        )

    def _log_generation_start(
        self,
        generation_type: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """生成開始をログ出力"""
        logger.info(
            f"Generation started: type={generation_type}, "
            f"org_id={self._organization_id}, "
            f"details={details}"
        )

    def _log_generation_complete(
        self,
        success: bool,
        processing_time_ms: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """生成完了をログ出力"""
        log_level = logging.INFO if success else logging.WARNING
        logger.log(
            log_level,
            f"Generation completed: success={success}, "
            f"org_id={self._organization_id}, "
            f"time_ms={processing_time_ms}, "
            f"details={details}"
        )

    async def _call_llm(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        task_type: str = "content",
        quality_level: QualityLevel = QualityLevel.STANDARD,
    ) -> Dict[str, Any]:
        """
        LLMを呼び出す

        Args:
            prompt: プロンプト
            system_prompt: システムプロンプト
            temperature: 温度（省略時はtask_typeから決定）
            task_type: タスクタイプ（温度決定用）
            quality_level: 品質レベル（モデル決定用）

        Returns:
            LLM応答
        """
        # 温度を決定
        if temperature is None:
            temperature = TEMPERATURE_SETTINGS.get(task_type, 0.3)

        # モデルを決定
        model = self._llm_client.get_model_for_quality(quality_level)

        return await self._llm_client.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model=model,
            temperature=temperature,
        )

    async def _call_llm_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        task_type: str = "content",
        quality_level: QualityLevel = QualityLevel.STANDARD,
    ) -> Dict[str, Any]:
        """
        LLMを呼び出してJSON応答を取得

        Args:
            prompt: プロンプト
            system_prompt: システムプロンプト
            temperature: 温度
            task_type: タスクタイプ
            quality_level: 品質レベル

        Returns:
            パース済みJSON応答
        """
        if temperature is None:
            temperature = TEMPERATURE_SETTINGS.get(task_type, 0.3)

        model = self._llm_client.get_model_for_quality(quality_level)

        return await self._llm_client.generate_json(
            prompt=prompt,
            system_prompt=system_prompt,
            model=model,
            temperature=temperature,
        )

    def _calculate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        model: str,
    ) -> float:
        """
        コストを計算

        Args:
            input_tokens: 入力トークン数
            output_tokens: 出力トークン数
            model: モデル名

        Returns:
            推定コスト（円）
        """
        # 1000トークンあたりのコスト（円）
        cost_per_1k = {
            "claude-opus-4-5-20251101": 15.0,
            "claude-sonnet-4-20250514": 3.0,
            "claude-3-5-haiku-20241022": 0.25,
        }

        input_cost_per_1k = cost_per_1k.get(model, 3.0)
        output_cost_per_1k = input_cost_per_1k * 5  # 出力は5倍

        input_cost = (input_tokens / 1000) * input_cost_per_1k
        output_cost = (output_tokens / 1000) * output_cost_per_1k

        return input_cost + output_cost
