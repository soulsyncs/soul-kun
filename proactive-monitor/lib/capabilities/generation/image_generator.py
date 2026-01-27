# lib/capabilities/generation/image_generator.py
"""
Phase G2: 画像生成能力 - 画像ジェネレーター

このモジュールは、DALL-E等の画像生成AIを使用して画像を生成する機能を提供します。

設計書: docs/20_next_generation_capabilities.md セクション5.4
Author: Claude Opus 4.5
Created: 2026-01-27
"""

import os
import logging
import json
import re
import base64
from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import UUID
import httpx

from .constants import (
    GenerationType,
    GenerationStatus,
    ImageProvider,
    ImageSize,
    ImageQuality,
    ImageStyle,
    DEFAULT_IMAGE_PROVIDER,
    DEFAULT_IMAGE_SIZE,
    DEFAULT_IMAGE_QUALITY,
    DEFAULT_IMAGE_STYLE,
    DEFAULT_IMAGE_MODEL,
    DALLE2_MODEL,
    MAX_PROMPT_LENGTH,
    IMAGE_COST_JPY,
    STYLE_PROMPT_MODIFIERS,
    IMAGE_PROMPT_OPTIMIZATION_TEMPLATE,
    SUPPORTED_SIZES_BY_PROVIDER,
    SUPPORTED_QUALITY_BY_PROVIDER,
    FEATURE_FLAG_IMAGE,
)
from .models import (
    ImageRequest,
    ImageResult,
    OptimizedPrompt,
    GenerationMetadata,
    GenerationInput,
    GenerationOutput,
)
from .exceptions import (
    ImageGenerationError,
    ImagePromptEmptyError,
    ImagePromptTooLongError,
    ImageInvalidSizeError,
    ImageInvalidQualityError,
    ImageFeatureDisabledError,
    wrap_image_generation_error,
)
from .dalle_client import DALLEClient, create_dalle_client
from .base import BaseGenerator


# =============================================================================
# ロガー設定
# =============================================================================

logger = logging.getLogger(__name__)


# =============================================================================
# 画像ジェネレーター
# =============================================================================


class ImageGenerator(BaseGenerator):
    """
    画像ジェネレーター

    DALL-E等の画像生成AIを使用して画像を生成する。

    使用例:
        generator = ImageGenerator(pool, org_id)
        result = await generator.generate(GenerationInput(
            generation_type=GenerationType.IMAGE,
            organization_id=org_id,
            image_request=ImageRequest(
                organization_id=org_id,
                prompt="未来的なオフィス",
            ),
        ))
    """

    def __init__(
        self,
        pool,
        organization_id: UUID,
        api_key: Optional[str] = None,
        openai_api_key: Optional[str] = None,
    ):
        """
        初期化

        Args:
            pool: データベース接続プール
            organization_id: 組織ID
            api_key: OpenRouter API Key（プロンプト最適化用）
            openai_api_key: OpenAI API Key（DALL-E用）
        """
        super().__init__(
            pool=pool,
            organization_id=organization_id,
            api_key=api_key,
        )
        self._openai_api_key = openai_api_key or os.environ.get("OPENAI_API_KEY")
        self._dalle_client = create_dalle_client(api_key=self._openai_api_key)

    # =========================================================================
    # メイン処理
    # =========================================================================

    @wrap_image_generation_error
    async def generate(self, input_data: GenerationInput) -> GenerationOutput:
        """
        画像を生成

        Args:
            input_data: 生成入力

        Returns:
            GenerationOutput: 生成結果
        """
        request = input_data.image_request
        if not request:
            raise ImageGenerationError(
                message="image_request is required",
                error_code="MISSING_REQUEST",
            )

        # 入力検証
        self._validate_request(request)

        # メタデータ初期化
        metadata = GenerationMetadata(
            organization_id=request.organization_id,
            user_id=request.user_id,
        )

        logger.info(f"Starting image generation: org={request.organization_id}")

        try:
            # 1. プロンプト最適化（オプション）
            optimized = await self._optimize_prompt(
                user_prompt=request.prompt,
                style=request.style,
                instruction=request.instruction,
                negative_prompt=request.negative_prompt,
            )

            # 使用するプロンプト決定
            prompt_to_use = optimized.optimized_prompt if optimized else request.prompt

            # 2. モデル選択
            model = self._select_model(request.provider, request.quality)

            # 3. DALL-E API呼び出し
            dalle_result = await self._dalle_client.generate(
                prompt=prompt_to_use,
                model=model,
                size=request.size,
                quality=request.quality,
                style=request.style,
            )

            if not dalle_result.get("success"):
                raise ImageGenerationError(
                    message=dalle_result.get("error", "Image generation failed"),
                    error_code="DALLE_FAILED",
                )

            # 4. 結果構築
            result = ImageResult(
                status=GenerationStatus.COMPLETED,
                success=True,
                image_url=dalle_result.get("url"),
                prompt_used=prompt_to_use,
                optimized_prompt=optimized,
                provider=request.provider,
                size=request.size,
                quality=request.quality,
                style=request.style,
                revised_prompt=dalle_result.get("revised_prompt"),
                estimated_cost_jpy=self._calculate_cost(request),
                metadata=metadata,
            )

            # 5. Google Driveに保存（オプション）
            if request.save_to_drive and dalle_result.get("url"):
                drive_result = await self._save_to_drive(
                    image_url=dalle_result["url"],
                    folder_id=request.drive_folder_id,
                    filename=self._generate_filename(request),
                )
                if drive_result:
                    result.drive_url = drive_result.get("url")
                    result.drive_file_id = drive_result.get("file_id")

            # 6. ChatWorkに送信（オプション）
            if request.send_to_chatwork and request.chatwork_room_id:
                await self._send_to_chatwork(
                    image_url=result.drive_url or result.image_url,
                    room_id=request.chatwork_room_id,
                    message=self._build_chatwork_message(result),
                )
                result.chatwork_sent = True

            # メタデータ完了
            metadata.complete(success=True)
            result.metadata = metadata

            logger.info(
                f"Image generation completed: cost=¥{result.estimated_cost_jpy:.0f}"
            )

            return GenerationOutput(
                generation_type=GenerationType.IMAGE,
                success=True,
                status=GenerationStatus.COMPLETED,
                image_result=result,
                metadata=metadata,
            )

        except ImageGenerationError:
            raise

        except Exception as e:
            logger.error(f"Image generation failed: {e}")
            metadata.complete(success=False, error_message=str(e))

            return GenerationOutput(
                generation_type=GenerationType.IMAGE,
                success=False,
                status=GenerationStatus.FAILED,
                image_result=ImageResult(
                    status=GenerationStatus.FAILED,
                    success=False,
                    error_message=str(e),
                    metadata=metadata,
                ),
                metadata=metadata,
                error_message=str(e),
            )

    # =========================================================================
    # 検証
    # =========================================================================

    def validate(self, input_data: GenerationInput) -> None:
        """
        入力を検証

        Args:
            input_data: 生成入力

        Raises:
            ImageGenerationError: 検証に失敗した場合
        """
        if input_data.image_request:
            self._validate_request(input_data.image_request)

    def _validate_request(self, request: ImageRequest) -> None:
        """リクエストを検証"""
        # プロンプトチェック
        if not request.prompt or not request.prompt.strip():
            raise ImagePromptEmptyError()

        if len(request.prompt) > MAX_PROMPT_LENGTH:
            raise ImagePromptTooLongError(
                actual_length=len(request.prompt),
                max_length=MAX_PROMPT_LENGTH,
            )

        # サイズチェック
        supported_sizes = SUPPORTED_SIZES_BY_PROVIDER.get(request.provider.value, set())
        if request.size.value not in supported_sizes:
            raise ImageInvalidSizeError(
                size=request.size.value,
                provider=request.provider.value,
                supported_sizes=list(supported_sizes),
            )

        # 品質チェック
        supported_qualities = SUPPORTED_QUALITY_BY_PROVIDER.get(request.provider.value, set())
        if request.quality.value not in supported_qualities:
            raise ImageInvalidQualityError(
                quality=request.quality.value,
                provider=request.provider.value,
            )

    # =========================================================================
    # プロンプト最適化
    # =========================================================================

    async def _optimize_prompt(
        self,
        user_prompt: str,
        style: ImageStyle,
        instruction: str = "",
        negative_prompt: str = "",
    ) -> Optional[OptimizedPrompt]:
        """
        プロンプトを最適化

        日本語プロンプトを英語に翻訳し、DALL-E 3に最適な形式に変換する。
        """
        if not self._api_key:
            # APIキーがない場合は最適化をスキップ
            logger.warning("Skipping prompt optimization: no API key")
            return OptimizedPrompt(
                original_prompt=user_prompt,
                optimized_prompt=self._apply_style_modifier(user_prompt, style),
            )

        # スタイル修飾子
        style_modifier = STYLE_PROMPT_MODIFIERS.get(style.value, "")

        # 追加指示を構築
        additional_instruction = instruction
        if negative_prompt:
            additional_instruction += f"\n避けるべき要素: {negative_prompt}"

        prompt = IMAGE_PROMPT_OPTIMIZATION_TEMPLATE.format(
            user_prompt=user_prompt,
            style=style_modifier or style.value,
            instruction=additional_instruction or "特になし",
        )

        try:
            result = await self._call_llm_json(prompt)
            parsed = result.get("parsed", {})

            return OptimizedPrompt(
                original_prompt=user_prompt,
                optimized_prompt=parsed.get("optimized_prompt", user_prompt),
                japanese_summary=parsed.get("japanese_summary", ""),
                warnings=parsed.get("warnings", []),
                tokens_used=result.get("total_tokens", 0),
            )

        except Exception as e:
            logger.warning(f"Prompt optimization failed: {e}")
            # 失敗時はスタイル修飾子を追加するだけ
            return OptimizedPrompt(
                original_prompt=user_prompt,
                optimized_prompt=self._apply_style_modifier(user_prompt, style),
            )

    def _apply_style_modifier(self, prompt: str, style: ImageStyle) -> str:
        """スタイル修飾子を適用"""
        modifier = STYLE_PROMPT_MODIFIERS.get(style.value)
        if modifier:
            return f"{prompt}, {modifier}"
        return prompt

    async def _call_llm_json(self, prompt: str) -> Dict[str, Any]:
        """LLMを呼び出してJSONレスポンスを取得"""
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://soulkun.soulsyncs.co.jp",
            "X-Title": "Soulkun Image Generator",
        }

        payload = {
            "model": "google/gemini-2.0-flash-001",
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 1000,
            "temperature": 0.3,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]

            # JSONを解析
            parsed = self._parse_json_response(content)

            return {
                "parsed": parsed,
                "total_tokens": data.get("usage", {}).get("total_tokens", 0),
            }

    def _parse_json_response(self, content: str) -> Dict[str, Any]:
        """LLMレスポンスからJSONを解析"""
        # JSON部分を抽出
        json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # 直接JSONとして解析を試みる
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        return {}

    # =========================================================================
    # モデル選択
    # =========================================================================

    def _select_model(
        self,
        provider: ImageProvider,
        quality: ImageQuality,
    ) -> str:
        """使用するモデルを選択"""
        if provider == ImageProvider.DALLE3:
            return DEFAULT_IMAGE_MODEL
        elif provider == ImageProvider.DALLE2:
            return DALLE2_MODEL
        else:
            # デフォルトはDALL-E 3
            return DEFAULT_IMAGE_MODEL

    # =========================================================================
    # コスト計算
    # =========================================================================

    def _calculate_cost(self, request: ImageRequest) -> float:
        """コストを計算"""
        key = f"{request.provider.value}_{request.quality.value}_{request.size.value}"
        return IMAGE_COST_JPY.get(key, 6.0)  # デフォルト6円

    # =========================================================================
    # ファイル名生成
    # =========================================================================

    def _generate_filename(self, request: ImageRequest) -> str:
        """ファイル名を生成"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # プロンプトから最初の20文字を取得（ファイル名に使える文字のみ）
        prompt_part = re.sub(r'[^\w\s-]', '', request.prompt[:20]).strip().replace(' ', '_')
        return f"soulkun_image_{timestamp}_{prompt_part}.png"

    # =========================================================================
    # Google Drive保存
    # =========================================================================

    async def _save_to_drive(
        self,
        image_url: str,
        folder_id: Optional[str] = None,
        filename: str = "image.png",
    ) -> Optional[Dict[str, str]]:
        """Google Driveに画像を保存"""
        # TODO: Google Drive API連携実装
        # 現時点では未実装（将来対応）
        logger.info(f"Google Drive save not yet implemented: {filename}")
        return None

    # =========================================================================
    # ChatWork送信
    # =========================================================================

    async def _send_to_chatwork(
        self,
        image_url: str,
        room_id: str,
        message: str,
    ) -> bool:
        """ChatWorkに画像を送信"""
        # TODO: ChatWork API連携実装
        # 現時点では未実装（将来対応）
        logger.info(f"ChatWork send not yet implemented: room={room_id}")
        return False

    def _build_chatwork_message(self, result: ImageResult) -> str:
        """ChatWork用メッセージを構築"""
        lines = [
            "[info][title]画像生成完了[/title]",
        ]
        if result.image_url:
            lines.append(f"画像URL: {result.image_url}")
        if result.drive_url:
            lines.append(f"Google Drive: {result.drive_url}")
        lines.append(f"コスト: ¥{result.estimated_cost_jpy:.0f}")
        lines.append("[/info]")
        return "\n".join(lines)


# =============================================================================
# ファクトリ関数
# =============================================================================


def create_image_generator(
    pool,
    organization_id: UUID,
    api_key: Optional[str] = None,
    openai_api_key: Optional[str] = None,
) -> ImageGenerator:
    """
    ImageGeneratorを作成

    Args:
        pool: データベース接続プール
        organization_id: 組織ID
        api_key: OpenRouter API Key（プロンプト最適化用）
        openai_api_key: OpenAI API Key（DALL-E用）

    Returns:
        ImageGenerator: 画像ジェネレーター
    """
    return ImageGenerator(
        pool=pool,
        organization_id=organization_id,
        api_key=api_key,
        openai_api_key=openai_api_key,
    )
