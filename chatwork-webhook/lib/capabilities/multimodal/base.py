# lib/capabilities/multimodal/base.py
"""
Phase M1: Multimodal入力能力 - 基盤クラス

このモジュールは、全てのMultimodalプロセッサーの基盤クラスを定義します。
各プロセッサー（Image, PDF, URL）はこのクラスを継承します。

設計書: docs/20_next_generation_capabilities.md セクション5
Author: Claude Opus 4.5
Created: 2026-01-27
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import UUID, uuid4
import logging
import os
import hashlib
import httpx

from .constants import (
    InputType,
    ProcessingStatus,
    ContentConfidenceLevel,
    VISION_MODELS,
    DEFAULT_VISION_MODEL,
    VISION_API_TIMEOUT_SECONDS,
    SAVE_PROCESSING_LOGS,
)
from .exceptions import (
    MultimodalBaseException,
    ValidationError,
    VisionAPIError,
    VisionAPITimeoutError,
    VisionAPIRateLimitError,
    wrap_multimodal_error,
)
from .models import (
    ProcessingMetadata,
    ExtractedEntity,
    MultimodalInput,
    MultimodalOutput,
)


# =============================================================================
# ロガー設定
# =============================================================================

logger = logging.getLogger(__name__)


# =============================================================================
# Vision APIクライアント
# =============================================================================


class VisionAPIClient:
    """
    Vision APIクライアント

    複数のVision APIプロバイダーを統一インターフェースで呼び出す。
    Model Orchestratorとは独立して動作（将来的に統合予定）。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_model: str = DEFAULT_VISION_MODEL,
        timeout_seconds: int = VISION_API_TIMEOUT_SECONDS,
    ):
        """
        初期化

        Args:
            api_key: OpenRouter API Key（省略時は環境変数から取得）
            default_model: デフォルトのVisionモデル
            timeout_seconds: タイムアウト秒数
        """
        self._api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        self._default_model = default_model
        self._timeout_seconds = timeout_seconds
        self._api_url = "https://openrouter.ai/api/v1/chat/completions"

    async def analyze_image(
        self,
        image_data: bytes,
        prompt: str,
        model: Optional[str] = None,
        max_tokens: int = 2000,
        temperature: float = 0.3,
    ) -> Dict[str, Any]:
        """
        画像を解析する

        Args:
            image_data: 画像のバイナリデータ
            prompt: 解析指示のプロンプト
            model: 使用するモデル（省略時はデフォルト）
            max_tokens: 最大出力トークン数
            temperature: 温度パラメータ

        Returns:
            解析結果（content, input_tokens, output_tokens）

        Raises:
            VisionAPIError: API呼び出しに失敗した場合
        """
        if not self._api_key:
            raise VisionAPIError("OpenRouter API key not configured")

        model = model or self._default_model

        # Base64エンコード
        import base64
        image_base64 = base64.b64encode(image_data).decode('utf-8')

        # 画像フォーマット検出
        image_format = self._detect_image_format(image_data)
        data_url = f"data:image/{image_format};base64,{image_base64}"

        # リクエスト構築
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://soulkun.soulsyncs.co.jp",
            "X-Title": "Soulkun Multimodal Processor",
        }

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt,
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": data_url,
                            },
                        },
                    ],
                }
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(
                    self._api_url,
                    headers=headers,
                    json=payload,
                )

                # レート制限チェック
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    raise VisionAPIRateLimitError(
                        model=model,
                        retry_after=int(retry_after) if retry_after else None,
                    )

                response.raise_for_status()
                data = response.json()

                # レスポンス解析
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                input_tokens = usage.get("prompt_tokens", 0)
                output_tokens = usage.get("completion_tokens", 0)

                return {
                    "content": content,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "model": model,
                }

        except httpx.TimeoutException:
            raise VisionAPITimeoutError(model=model, timeout_seconds=self._timeout_seconds)
        except httpx.HTTPError as e:
            raise VisionAPIError(
                message=f"Vision API HTTP error ({type(e).__name__})",
                model=model,
                original_error=e,
            )
        except VisionAPIError:
            raise
        except Exception as e:
            raise VisionAPIError(
                message=f"Vision API error ({type(e).__name__})",
                model=model,
                original_error=e,
            )

    async def analyze_with_fallback(
        self,
        image_data: bytes,
        prompt: str,
        max_tokens: int = 2000,
        temperature: float = 0.3,
    ) -> Dict[str, Any]:
        """
        フォールバック付きで画像を解析

        プライマリモデルが失敗した場合、フォールバックモデルを試行する。

        Args:
            image_data: 画像のバイナリデータ
            prompt: 解析指示のプロンプト
            max_tokens: 最大出力トークン数
            temperature: 温度パラメータ

        Returns:
            解析結果

        Raises:
            VisionAPIError: 全てのモデルで失敗した場合
        """
        last_error: Optional[VisionAPIError] = None

        for model_info in VISION_MODELS:
            model_id = model_info["model_id"]
            try:
                logger.debug(f"Trying Vision model: {model_id}")
                result = await self.analyze_image(
                    image_data=image_data,
                    prompt=prompt,
                    model=model_id,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                result["fallback_used"] = model_id != VISION_MODELS[0]["model_id"]
                return result

            except VisionAPIRateLimitError:
                logger.warning(f"Rate limit for {model_id}, trying next model")
                last_error = VisionAPIRateLimitError(model=model_id)
            except VisionAPIError as e:
                logger.warning(f"Vision API error for {model_id}: {e.message}")
                last_error = e

        # 全てのモデルで失敗
        raise last_error or VisionAPIError("All Vision models failed")

    @staticmethod
    def _detect_image_format(data: bytes) -> str:
        """画像フォーマットを検出"""
        # マジックナンバーで判定
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            return "png"
        elif data[:2] == b'\xff\xd8':
            return "jpeg"
        elif data[:6] in (b'GIF87a', b'GIF89a'):
            return "gif"
        elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            return "webp"
        elif data[:2] == b'BM':
            return "bmp"
        else:
            return "jpeg"  # デフォルト


# =============================================================================
# 基盤プロセッサークラス
# =============================================================================


class BaseMultimodalProcessor(ABC):
    """
    Multimodalプロセッサーの基盤クラス

    全てのプロセッサー（Image, PDF, URL）はこのクラスを継承し、
    以下のメソッドを実装する:
    - process(): データを処理して結果を返す
    - validate(): 入力を検証する
    """

    def __init__(
        self,
        pool,
        organization_id: str,
        api_key: Optional[str] = None,
        input_type: InputType = InputType.IMAGE,
    ):
        """
        初期化

        Args:
            pool: データベース接続プール（SQLAlchemy Engine）
            organization_id: 組織ID
            api_key: OpenRouter API Key
            input_type: 入力タイプ
        """
        self._pool = pool
        self._organization_id = organization_id
        self._api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        self._input_type = input_type

        # Vision APIクライアント
        self._vision_client = VisionAPIClient(api_key=self._api_key)

        # 処理ID（ログ用）
        self._processing_id: Optional[str] = None

    # =========================================================================
    # 抽象メソッド（サブクラスで実装必須）
    # =========================================================================

    @abstractmethod
    async def process(self, input_data: MultimodalInput) -> MultimodalOutput:
        """
        データを処理

        Args:
            input_data: 入力データ

        Returns:
            MultimodalOutput: 処理結果
        """
        pass

    @abstractmethod
    def validate(self, input_data: MultimodalInput) -> None:
        """
        入力を検証

        Args:
            input_data: 入力データ

        Raises:
            ValidationError: 検証に失敗した場合
        """
        pass

    # =========================================================================
    # 共通メソッド
    # =========================================================================

    def _create_processing_metadata(self) -> ProcessingMetadata:
        """処理メタデータを作成"""
        self._processing_id = str(uuid4())
        return ProcessingMetadata(
            processing_id=self._processing_id,
            organization_id=self._organization_id,
            started_at=datetime.now(),
            input_type=self._input_type,
            status=ProcessingStatus.PROCESSING,
        )

    def _complete_processing_metadata(
        self,
        metadata: ProcessingMetadata,
        success: bool,
        error_message: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> ProcessingMetadata:
        """処理メタデータを完了"""
        metadata.completed_at = datetime.now()
        metadata.processing_time_ms = int(
            (metadata.completed_at - metadata.started_at).total_seconds() * 1000
        )
        metadata.status = ProcessingStatus.COMPLETED if success else ProcessingStatus.FAILED
        metadata.error_message = error_message
        metadata.error_code = error_code
        return metadata

    def _calculate_confidence_level(self, score: float) -> ContentConfidenceLevel:
        """確信度レベルを計算"""
        return ContentConfidenceLevel.from_score(score)

    def _validate_organization_id(self) -> None:
        """組織IDを検証"""
        if not self._organization_id:
            raise ValidationError(
                message="organization_id is required",
                field="organization_id",
            )

    def _compute_hash(self, data: bytes) -> str:
        """データのハッシュを計算"""
        return hashlib.sha256(data).hexdigest()

    def _truncate_text(self, text: str, max_length: int, suffix: str = "...") -> str:
        """テキストを切り詰める"""
        if len(text) <= max_length:
            return text
        return text[:max_length - len(suffix)] + suffix

    def _log_processing_start(self, input_type: str, details: Optional[Dict] = None):
        """処理開始をログ"""
        log_data = {
            "processing_id": self._processing_id,
            "organization_id": self._organization_id,
            "input_type": input_type,
        }
        if details:
            log_data.update(details)
        logger.info(f"Multimodal processing started: {input_type}", extra=log_data)

    def _log_processing_complete(
        self,
        success: bool,
        processing_time_ms: int,
        details: Optional[Dict] = None,
    ):
        """処理完了をログ"""
        log_data = {
            "processing_id": self._processing_id,
            "organization_id": self._organization_id,
            "success": success,
            "processing_time_ms": processing_time_ms,
        }
        if details:
            log_data.update(details)

        if success:
            logger.info("Multimodal processing completed", extra=log_data)
        else:
            logger.warning("Multimodal processing failed", extra=log_data)

    async def _save_processing_log(
        self,
        metadata: ProcessingMetadata,
        input_hash: Optional[str] = None,
        output_summary: Optional[str] = None,
    ) -> None:
        """
        処理ログをDBに保存

        Args:
            metadata: 処理メタデータ
            input_hash: 入力データのハッシュ
            output_summary: 出力の要約
        """
        if not SAVE_PROCESSING_LOGS:
            return

        try:
            # TODO: DBテーブル作成後に実装
            # multimodal_processing_logsテーブルに保存
            logger.debug(
                f"Processing log saved: {metadata.processing_id}",
                extra={"metadata": metadata.to_dict()},
            )
        except Exception as e:
            logger.warning(f"Failed to save processing log: {e}")

    # =========================================================================
    # エンティティ抽出ヘルパー
    # =========================================================================

    def _extract_entities_from_text(
        self,
        text: str,
        entity_types: Optional[List[str]] = None,
    ) -> List[ExtractedEntity]:
        """
        テキストからエンティティを抽出

        簡易的なパターンマッチングによる抽出。
        より高度な抽出はVision APIまたは専用NERモデルで行う。

        Args:
            text: 入力テキスト
            entity_types: 抽出するエンティティタイプ

        Returns:
            抽出されたエンティティのリスト
        """
        import re

        entities = []

        # 金額パターン
        amount_pattern = r'[¥￥]?\s*[\d,]+(?:\.\d+)?\s*(?:円|万円|億円)?'
        for match in re.finditer(amount_pattern, text):
            value = match.group().strip()
            if value and any(c.isdigit() for c in value):
                entities.append(ExtractedEntity(
                    entity_type="amount",
                    value=value,
                    confidence=0.8,
                    start_position=match.start(),
                    end_position=match.end(),
                ))

        # 日付パターン
        date_patterns = [
            r'\d{4}[年/-]\d{1,2}[月/-]\d{1,2}日?',
            r'\d{1,2}[月/-]\d{1,2}日?',
            r'\d{4}/\d{2}/\d{2}',
        ]
        for pattern in date_patterns:
            for match in re.finditer(pattern, text):
                entities.append(ExtractedEntity(
                    entity_type="date",
                    value=match.group(),
                    confidence=0.9,
                    start_position=match.start(),
                    end_position=match.end(),
                ))

        # 電話番号パターン
        phone_pattern = r'(?:\d{2,4}[-\s]?\d{2,4}[-\s]?\d{4}|\d{10,11})'
        for match in re.finditer(phone_pattern, text):
            entities.append(ExtractedEntity(
                entity_type="phone",
                value=match.group(),
                confidence=0.7,
                start_position=match.start(),
                end_position=match.end(),
            ))

        # メールアドレスパターン
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        for match in re.finditer(email_pattern, text):
            entities.append(ExtractedEntity(
                entity_type="email",
                value=match.group(),
                confidence=0.95,
                start_position=match.start(),
                end_position=match.end(),
            ))

        # URLパターン
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        for match in re.finditer(url_pattern, text):
            entities.append(ExtractedEntity(
                entity_type="url",
                value=match.group(),
                confidence=0.95,
                start_position=match.start(),
                end_position=match.end(),
            ))

        return entities

    # =========================================================================
    # プロンプトテンプレート
    # =========================================================================

    def _get_image_analysis_prompt(self, instruction: Optional[str] = None) -> str:
        """画像解析用プロンプトを取得"""
        base_prompt = """以下の画像を詳細に分析してください。

分析項目：
1. 画像の種類（写真、文書、図解、グラフ等）
2. 画像の内容の説明
3. 画像内のテキスト（OCR）- 全て正確に抽出してください
4. 検出された固有表現（人名、組織名、日付、金額、場所等）
5. 構造化できる情報（領収書、名刺等の場合はJSON形式で）

回答はJSON形式で以下の構造で返してください：
```json
{
    "image_type": "document|photo|diagram|chart|screenshot|other",
    "description": "画像の説明",
    "extracted_text": "抽出されたテキスト全文",
    "entities": [
        {"type": "person|organization|date|amount|location|other", "value": "値", "confidence": 0.0-1.0}
    ],
    "structured_data": {
        // 領収書なら: {"store_name": "", "date": "", "amount": "", "items": []}
        // 名刺なら: {"name": "", "company": "", "title": "", "email": "", "phone": ""}
    },
    "confidence": 0.0-1.0
}
```"""

        if instruction:
            base_prompt += f"\n\n追加の指示: {instruction}"

        return base_prompt

    def _get_url_analysis_prompt(
        self,
        content: str,
        instruction: Optional[str] = None,
    ) -> str:
        """URL解析用プロンプトを取得"""
        base_prompt = f"""以下のWebページコンテンツを分析してください。

コンテンツ:
{content[:10000]}

分析項目：
1. ページの種類（ニュース、ブログ、ドキュメント、サービスページ等）
2. 要約（3-5文）
3. 重要ポイント（3-5個の箇条書き）
4. 検出された固有表現

回答はJSON形式で以下の構造で返してください：
```json
{{
    "page_type": "news|blog|document|service|other",
    "summary": "要約",
    "key_points": ["ポイント1", "ポイント2", ...],
    "entities": [
        {{"type": "person|organization|date|product|other", "value": "値"}}
    ],
    "relevance_keywords": ["キーワード1", "キーワード2", ...]
}}
```"""

        if instruction:
            base_prompt += f"\n\n追加の指示: {instruction}"

        return base_prompt
