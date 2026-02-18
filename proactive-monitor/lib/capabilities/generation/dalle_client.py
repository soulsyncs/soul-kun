# lib/capabilities/generation/dalle_client.py
"""
Phase G2: 画像生成能力 - DALL-E APIクライアント

このモジュールは、OpenAI DALL-E APIとの通信を行うクライアントを提供します。

設計書: docs/20_next_generation_capabilities.md セクション5.4
Author: Claude Opus 4.5
Created: 2026-01-27
"""

import os
import logging
from typing import Optional, Dict, Any
import httpx

from .constants import (
    DALLE_API_URL,
    DALLE_API_TIMEOUT_SECONDS,
    DALLE_MAX_RETRIES,
    DALLE_RETRY_DELAY_SECONDS,
    DEFAULT_IMAGE_MODEL,
    DALLE2_MODEL,
    ImageProvider,
    ImageSize,
    ImageQuality,
    ImageStyle,
)
from .exceptions import (
    DALLEAPIError,
    DALLERateLimitError,
    DALLETimeoutError,
    DALLEQuotaExceededError,
    ContentPolicyViolationError,
)


# =============================================================================
# ロガー設定
# =============================================================================

logger = logging.getLogger(__name__)


# =============================================================================
# DALL-E APIクライアント
# =============================================================================


class DALLEClient:
    """
    DALL-E APIクライアント

    OpenAI DALL-E APIを使用して画像を生成する。
    DALL-E 3とDALL-E 2の両方に対応。

    使用例:
        client = DALLEClient(api_key="sk-...")
        result = await client.generate(
            prompt="A futuristic office with AI assistants",
            size=ImageSize.SQUARE_1024,
            quality=ImageQuality.HD,
        )
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout_seconds: int = DALLE_API_TIMEOUT_SECONDS,
        max_retries: int = DALLE_MAX_RETRIES,
    ):
        """
        初期化

        Args:
            api_key: OpenAI API Key（省略時は環境変数から取得）
            timeout_seconds: タイムアウト秒数
            max_retries: 最大リトライ回数
        """
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self._api_key:
            try:
                from lib.secrets import get_secret_cached
                self._api_key = get_secret_cached("OPENAI_API_KEY")
            except (ImportError, Exception):
                pass
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._api_url = DALLE_API_URL

    async def generate(
        self,
        prompt: str,
        model: str = DEFAULT_IMAGE_MODEL,
        size: ImageSize = ImageSize.SQUARE_1024,
        quality: ImageQuality = ImageQuality.STANDARD,
        style: ImageStyle = ImageStyle.VIVID,
        n: int = 1,
        response_format: str = "url",  # "url" or "b64_json"
    ) -> Dict[str, Any]:
        """
        画像を生成

        Args:
            prompt: 画像の説明（英語推奨）
            model: 使用するモデル（dall-e-3, dall-e-2）
            size: 画像サイズ
            quality: 画像品質（DALL-E 3のみ）
            style: 画像スタイル（DALL-E 3のみ）
            n: 生成枚数（DALL-E 3は1固定）
            response_format: レスポンス形式

        Returns:
            生成結果（url/b64_json, revised_prompt等）

        Raises:
            DALLEAPIError: API呼び出しに失敗した場合
        """
        if not self._api_key:
            raise DALLEAPIError(
                message="OpenAI API key not configured",
                error_code="API_KEY_MISSING",
                model=model,
            )

        # ペイロード構築
        payload = {
            "model": model,
            "prompt": prompt,
            "size": size.value,
            "n": 1 if model == DEFAULT_IMAGE_MODEL else n,  # DALL-E 3は1固定
            "response_format": response_format,
        }

        # DALL-E 3専用オプション
        if model == DEFAULT_IMAGE_MODEL:
            payload["quality"] = quality.value
            # styleはvivid/naturalのみ（カスタムスタイルはプロンプトで対応）
            if style in (ImageStyle.VIVID, ImageStyle.NATURAL):
                payload["style"] = style.value
            else:
                payload["style"] = ImageStyle.VIVID.value

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        logger.info(f"DALL-E API call: model={model}, size={size.value}, quality={quality.value}")

        # リトライロジック
        last_error: Optional[DALLEAPIError] = None
        for attempt in range(self._max_retries):
            try:
                async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                    response = await client.post(
                        self._api_url,
                        headers=headers,
                        json=payload,
                    )

                    # エラーレスポンス処理
                    if response.status_code != 200:
                        await self._handle_error_response(response, model)

                    # 成功
                    result = response.json()
                    logger.info(f"DALL-E API success: {len(result.get('data', []))} image(s)")

                    # 結果を整形して返す
                    return self._format_response(result, model)

            except httpx.TimeoutException:
                last_error = DALLETimeoutError(
                    model=model,
                    timeout_seconds=self._timeout_seconds,
                )
                logger.warning(f"DALL-E API timeout (attempt {attempt + 1}/{self._max_retries})")

            except (DALLERateLimitError, DALLETimeoutError) as e:
                last_error = e
                if attempt < self._max_retries - 1:
                    import asyncio
                    await asyncio.sleep(DALLE_RETRY_DELAY_SECONDS * (attempt + 1))
                    continue
                raise

            except DALLEAPIError:
                raise

            except Exception as e:
                raise DALLEAPIError(
                    message=f"DALL-E API error: {str(e)}",
                    model=model,
                    original_error=e,
                )

        # リトライ回数超過
        if last_error:
            raise last_error
        raise DALLEAPIError(
            message="DALL-E API failed after retries",
            model=model,
        )

    async def _handle_error_response(
        self,
        response: httpx.Response,
        model: str,
    ) -> None:
        """
        エラーレスポンスを処理

        Args:
            response: HTTPレスポンス
            model: 使用モデル

        Raises:
            適切な例外
        """
        status_code = response.status_code

        try:
            error_data = response.json()
            error_message = error_data.get("error", {}).get("message", "Unknown error")
            error_code = error_data.get("error", {}).get("code", "")
        except Exception:
            error_message = response.text or "Unknown error"
            error_code = ""

        logger.error(f"DALL-E API error: {status_code} - {error_message}")

        # レート制限
        if status_code == 429:
            retry_after = response.headers.get("Retry-After")
            raise DALLERateLimitError(
                model=model,
                retry_after=int(retry_after) if retry_after else None,
            )

        # クォータ超過
        if status_code == 402 or "quota" in error_message.lower():
            raise DALLEQuotaExceededError(model=model)

        # コンテンツポリシー違反
        if (
            status_code == 400
            and ("content_policy" in error_code or "safety" in error_message.lower())
        ):
            raise ContentPolicyViolationError(
                details={"error_message": error_message}
            )

        # その他のエラー
        raise DALLEAPIError(
            message=error_message,
            error_code=f"HTTP_{status_code}",
            model=model,
            details={"status_code": status_code},
        )

    def _format_response(
        self,
        result: Dict[str, Any],
        model: str,
    ) -> Dict[str, Any]:
        """
        APIレスポンスを整形

        Args:
            result: APIレスポンス
            model: 使用モデル

        Returns:
            整形された結果
        """
        data = result.get("data", [])
        if not data:
            return {
                "success": False,
                "error": "No image generated",
            }

        image_data = data[0]
        formatted = {
            "success": True,
            "model": model,
            "url": image_data.get("url"),
            "b64_json": image_data.get("b64_json"),
            "revised_prompt": image_data.get("revised_prompt"),
        }

        return formatted


# =============================================================================
# ファクトリ関数
# =============================================================================


def create_dalle_client(
    api_key: Optional[str] = None,
    timeout_seconds: int = DALLE_API_TIMEOUT_SECONDS,
) -> DALLEClient:
    """
    DALLEClientを作成

    Args:
        api_key: OpenAI API Key
        timeout_seconds: タイムアウト秒数

    Returns:
        DALLEClient: DALL-Eクライアント
    """
    return DALLEClient(
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )
