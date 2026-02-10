# lib/capabilities/generation/video_generator.py
"""
Phase G5: 動画生成能力 - 動画ジェネレーター

このモジュールは、Runway等の動画生成AIを使用して動画を生成する機能を提供します。

設計書: docs/20_next_generation_capabilities.md
Author: Claude Opus 4.5
Created: 2026-01-28
"""

import os
import logging
import json
from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import UUID
import httpx

from .constants import (
    GenerationType,
    GenerationStatus,
    VideoProvider,
    VideoResolution,
    VideoDuration,
    VideoAspectRatio,
    VideoStyle,
    DEFAULT_VIDEO_PROVIDER,
    DEFAULT_VIDEO_RESOLUTION,
    DEFAULT_VIDEO_DURATION,
    DEFAULT_VIDEO_ASPECT_RATIO,
    DEFAULT_VIDEO_STYLE,
    RUNWAY_GEN3_MODEL,
    RUNWAY_GEN3_TURBO_MODEL,
    MAX_VIDEO_PROMPT_LENGTH,
    VIDEO_COST_JPY,
    VIDEO_STYLE_PROMPT_MODIFIERS,
    SUPPORTED_RESOLUTIONS_BY_PROVIDER,
    SUPPORTED_DURATIONS_BY_PROVIDER,
    VIDEO_PROMPT_OPTIMIZATION_TEMPLATE,
    FEATURE_FLAG_VIDEO,
)
from .models import (
    VideoRequest,
    VideoResult,
    VideoOptimizedPrompt,
    GenerationMetadata,
    GenerationInput,
    GenerationOutput,
)
from .exceptions import (
    VideoGenerationError,
    VideoPromptEmptyError,
    VideoPromptTooLongError,
    VideoInvalidResolutionError,
    VideoInvalidDurationError,
    VideoFeatureDisabledError,
    wrap_video_generation_error,
)
from .runway_client import RunwayClient, create_runway_client
from .base import BaseGenerator


# =============================================================================
# ロガー設定
# =============================================================================

logger = logging.getLogger(__name__)


# =============================================================================
# 動画ジェネレーター
# =============================================================================


class VideoGenerator(BaseGenerator):
    """
    動画ジェネレーター

    Runway等の動画生成AIを使用して動画を生成する。

    使用例:
        generator = VideoGenerator(pool, org_id)
        result = await generator.generate(GenerationInput(
            generation_type=GenerationType.VIDEO,
            organization_id=org_id,
            video_request=VideoRequest(
                organization_id=org_id,
                prompt="猫が庭を歩いている",
            ),
        ))
    """

    def __init__(
        self,
        pool,
        organization_id: UUID,
        api_key: Optional[str] = None,
        runway_api_key: Optional[str] = None,
    ):
        """
        初期化

        Args:
            pool: データベース接続プール
            organization_id: 組織ID
            api_key: OpenRouter API Key（プロンプト最適化用）
            runway_api_key: Runway API Key（動画生成用）
        """
        super().__init__(
            pool=pool,
            organization_id=organization_id,
            api_key=api_key,
        )
        self._api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        self._runway_api_key = runway_api_key or os.environ.get("RUNWAY_API_KEY")
        self._runway_client = create_runway_client(api_key=self._runway_api_key)

    # =========================================================================
    # メイン処理
    # =========================================================================

    @wrap_video_generation_error
    async def generate(self, input_data: GenerationInput) -> GenerationOutput:
        """
        動画を生成

        Args:
            input_data: 生成入力

        Returns:
            GenerationOutput: 生成結果
        """
        request = input_data.video_request
        if not request:
            raise VideoGenerationError(
                message="video_request is required",
                error_code="MISSING_REQUEST",
            )

        # 入力検証
        self._validate_request(request)

        # メタデータ初期化
        metadata = GenerationMetadata(
            organization_id=request.organization_id,
            user_id=request.user_id,
        )

        logger.info(f"Starting video generation: org={request.organization_id}")

        # 結果オブジェクト作成
        result = VideoResult(
            status=GenerationStatus.GENERATING,
            provider=request.provider,
            resolution=request.resolution,
            duration=request.duration,
            aspect_ratio=request.aspect_ratio,
            style=request.style,
            metadata=metadata,
        )

        try:
            # コスト事前計算
            result.estimated_cost_jpy = self._calculate_cost(request)

            # プロンプト最適化
            optimized = await self._optimize_prompt(
                request.prompt,
                request.style,
            )
            result.optimized_prompt = optimized
            prompt_to_use = optimized.optimized_prompt if optimized else request.prompt
            result.prompt_used = prompt_to_use

            # スタイル修飾子を適用
            if request.style and request.style.value in VIDEO_STYLE_PROMPT_MODIFIERS:
                prompt_to_use = self._apply_style_modifier(prompt_to_use, request.style)

            # モデル選択
            model = self._select_model(request.provider)

            # 動画生成開始
            gen_result = await self._runway_client.generate(
                prompt=prompt_to_use,
                model=model,
                duration=request.duration or DEFAULT_VIDEO_DURATION,
                resolution=request.resolution or DEFAULT_VIDEO_RESOLUTION,
                aspect_ratio=request.aspect_ratio or DEFAULT_VIDEO_ASPECT_RATIO,
                source_image_url=request.source_image_url,
            )

            task_id = gen_result.get("task_id")
            result.runway_task_id = task_id

            # 完了を待つ
            if not task_id:
                raise VideoGenerationError(
                    message="No task_id returned from Runway API",
                    error_code="MISSING_TASK_ID",
                )
            completion_result = await self._runway_client.wait_for_completion(
                task_id=task_id,
                progress_callback=lambda p, s: logger.debug(f"Progress: {p}%, Status: {s}"),
            )

            # 結果を設定
            result.video_url = completion_result.get("output_url")
            result.actual_cost_jpy = result.estimated_cost_jpy  # 実際のコスト

            # 成功
            result.complete(success=True)

            logger.info(f"Video generation completed: {result.video_url}")

        except VideoGenerationError:
            raise
        except Exception as e:
            logger.error(f"Video generation failed: {str(e)}")
            result.complete(
                success=False,
                error_message=str(e),
                error_code="GENERATION_FAILED",
            )
            raise VideoGenerationError(
                message=f"Video generation failed: {str(e)}",
                error_code="GENERATION_FAILED",
                original_error=e,
            )

        return GenerationOutput(
            generation_type=GenerationType.VIDEO,
            success=result.success,
            status=result.status,
            video_result=result,
            metadata=metadata,
        )

    # =========================================================================
    # 検証
    # =========================================================================

    def validate(self, input_data: GenerationInput) -> None:
        """
        入力を検証

        Args:
            input_data: 入力データ
        """
        request = input_data.video_request
        if not request:
            raise VideoGenerationError(
                message="video_request is required",
                error_code="MISSING_REQUEST",
            )
        self._validate_request(request)

    def _validate_request(self, request: VideoRequest) -> None:
        """リクエストを検証"""
        # プロンプト検証
        if not request.prompt or not request.prompt.strip():
            raise VideoPromptEmptyError()

        if len(request.prompt) > MAX_VIDEO_PROMPT_LENGTH:
            raise VideoPromptTooLongError(
                actual_length=len(request.prompt),
                max_length=MAX_VIDEO_PROMPT_LENGTH,
            )

        # 解像度検証
        provider_key = request.provider.value if request.provider else DEFAULT_VIDEO_PROVIDER.value
        supported_resolutions: frozenset[str] = SUPPORTED_RESOLUTIONS_BY_PROVIDER.get(provider_key, frozenset())
        resolution_value = request.resolution.value if request.resolution else DEFAULT_VIDEO_RESOLUTION.value

        if resolution_value not in supported_resolutions:
            raise VideoInvalidResolutionError(
                resolution=resolution_value,
                provider=provider_key,
                supported_resolutions=list(supported_resolutions),
            )

        # 動画長検証
        supported_durations: frozenset[str] = SUPPORTED_DURATIONS_BY_PROVIDER.get(provider_key, frozenset())
        duration_value = request.duration.value if request.duration else DEFAULT_VIDEO_DURATION.value

        if duration_value not in supported_durations:
            raise VideoInvalidDurationError(
                duration=duration_value,
                provider=provider_key,
                supported_durations=list(supported_durations),
            )

    # =========================================================================
    # コスト計算
    # =========================================================================

    def _calculate_cost(self, request: VideoRequest) -> float:  # type: ignore[override]
        """コストを計算"""
        provider = request.provider or DEFAULT_VIDEO_PROVIDER
        duration = request.duration or DEFAULT_VIDEO_DURATION

        key = f"{provider.value}_{duration.value}"
        return VIDEO_COST_JPY.get(key, 50.0)  # デフォルト50円

    # =========================================================================
    # プロンプト処理
    # =========================================================================

    async def _optimize_prompt(
        self,
        prompt: str,
        style: Optional[VideoStyle] = None,
    ) -> Optional[VideoOptimizedPrompt]:
        """
        プロンプトを最適化

        LLMを使用して日本語プロンプトを英語に変換し、
        動画生成に適した形式に最適化する。
        """
        if not self._api_key:
            # APIキーがない場合はそのまま返す
            return VideoOptimizedPrompt(
                original_prompt=prompt,
                optimized_prompt=prompt,
            )

        try:
            system_prompt = VIDEO_PROMPT_OPTIMIZATION_TEMPLATE.format(
                original_prompt=prompt,
                style=style.value if style else "realistic",
            )

            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "anthropic/claude-3-haiku",
                        "messages": [
                            {"role": "user", "content": system_prompt}
                        ],
                        "max_tokens": 500,
                    },
                )

                if response.status_code != 200:
                    logger.warning(f"Prompt optimization failed: {response.status_code}")
                    return VideoOptimizedPrompt(
                        original_prompt=prompt,
                        optimized_prompt=prompt,
                    )

                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

                # JSONをパース
                try:
                    # JSONブロックを抽出
                    if "```json" in content:
                        json_str = content.split("```json")[1].split("```")[0].strip()
                    elif "{" in content:
                        start = content.index("{")
                        end = content.rindex("}") + 1
                        json_str = content[start:end]
                    else:
                        json_str = content

                    parsed = json.loads(json_str)

                    return VideoOptimizedPrompt(
                        original_prompt=prompt,
                        optimized_prompt=parsed.get("optimized_prompt", prompt),
                        japanese_summary=parsed.get("japanese_summary", ""),
                        warnings=parsed.get("warnings", []),
                        tokens_used=data.get("usage", {}).get("total_tokens", 0),
                    )
                except (json.JSONDecodeError, ValueError):
                    # パース失敗時はコンテンツをそのまま使用
                    return VideoOptimizedPrompt(
                        original_prompt=prompt,
                        optimized_prompt=content.strip() if content else prompt,
                    )

        except Exception as e:
            logger.warning(f"Prompt optimization error: {str(e)}")
            return VideoOptimizedPrompt(
                original_prompt=prompt,
                optimized_prompt=prompt,
            )

    def _apply_style_modifier(self, prompt: str, style: VideoStyle) -> str:
        """スタイル修飾子を適用"""
        modifier = VIDEO_STYLE_PROMPT_MODIFIERS.get(style.value, "")
        if modifier:
            return f"{prompt}, {modifier}"
        return prompt

    # =========================================================================
    # モデル選択
    # =========================================================================

    def _select_model(self, provider: Optional[VideoProvider] = None) -> str:
        """モデルを選択"""
        if provider == VideoProvider.RUNWAY_GEN3_TURBO:
            return RUNWAY_GEN3_TURBO_MODEL
        return RUNWAY_GEN3_MODEL


# =============================================================================
# ファクトリ関数
# =============================================================================


def create_video_generator(
    pool,
    organization_id: UUID,
    api_key: Optional[str] = None,
    runway_api_key: Optional[str] = None,
) -> VideoGenerator:
    """
    VideoGeneratorを作成

    Args:
        pool: データベース接続プール
        organization_id: 組織ID
        api_key: OpenRouter API Key（プロンプト最適化用）
        runway_api_key: Runway API Key（動画生成用）

    Returns:
        VideoGenerator
    """
    return VideoGenerator(
        pool=pool,
        organization_id=organization_id,
        api_key=api_key,
        runway_api_key=runway_api_key,
    )
