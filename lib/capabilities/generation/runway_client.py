# lib/capabilities/generation/runway_client.py
"""
Phase G5: 動画生成能力 - Runway APIクライアント

このモジュールは、Runway Gen-3 Alpha APIとの通信を行うクライアントを提供します。

設計書: docs/20_next_generation_capabilities.md
Author: Claude Opus 4.5
Created: 2026-01-28
"""

import os
import logging
import asyncio
from typing import Optional, Dict, Any, Callable
import httpx

from .constants import (
    RUNWAY_API_URL,
    RUNWAY_API_TIMEOUT_SECONDS,
    RUNWAY_MAX_RETRIES,
    RUNWAY_RETRY_DELAY_SECONDS,
    RUNWAY_POLL_INTERVAL_SECONDS,
    RUNWAY_MAX_POLL_ATTEMPTS,
    RUNWAY_GEN3_MODEL,
    VideoProvider,
    VideoResolution,
    VideoDuration,
    VideoAspectRatio,
)
from .exceptions import (
    RunwayAPIError,
    RunwayRateLimitError,
    RunwayTimeoutError,
    RunwayQuotaExceededError,
    RunwayServerError,
    VideoContentPolicyViolationError,
)


# =============================================================================
# ロガー設定
# =============================================================================

logger = logging.getLogger(__name__)


# =============================================================================
# Runway APIクライアント
# =============================================================================


class RunwayClient:
    """
    Runway APIクライアント

    Runway Gen-3 Alpha APIを使用して動画を生成する。

    使用例:
        client = RunwayClient(api_key="...")
        result = await client.generate(
            prompt="A cat walking through a garden",
            duration=VideoDuration.STANDARD_10S,
        )

        # タスク完了を待つ
        result = await client.wait_for_completion(result["task_id"])
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout_seconds: int = RUNWAY_API_TIMEOUT_SECONDS,
        max_retries: int = RUNWAY_MAX_RETRIES,
    ):
        """
        初期化

        Args:
            api_key: Runway API Key（省略時は環境変数から取得）
            timeout_seconds: タイムアウト秒数
            max_retries: 最大リトライ回数
        """
        self._api_key = api_key or os.environ.get("RUNWAY_API_KEY")
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._api_url = RUNWAY_API_URL

    async def generate(
        self,
        prompt: str,
        model: str = RUNWAY_GEN3_MODEL,
        duration: VideoDuration = VideoDuration.STANDARD_10S,
        resolution: VideoResolution = VideoResolution.FULL_HD_1080P,
        aspect_ratio: VideoAspectRatio = VideoAspectRatio.LANDSCAPE_16_9,
        source_image_url: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        動画生成タスクを開始

        Args:
            prompt: 動画の説明（英語推奨）
            model: 使用するモデル
            duration: 動画長さ（秒）
            resolution: 解像度
            aspect_ratio: アスペクト比
            source_image_url: 入力画像URL（画像→動画生成時）
            seed: シード値（再現性のため）

        Returns:
            {
                "task_id": "...",
                "status": "PENDING",
                "progress": 0,
            }
        """
        if not self._api_key:
            raise RunwayAPIError(
                message="RUNWAY_API_KEY is not set",
                details={"reason": "API key missing"},
            )

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "X-Runway-Version": "2024-09-13",
        }

        # リクエストボディを構築
        body = {
            "promptText": prompt,
            "model": model,
            "duration": int(duration.value),
            "ratio": aspect_ratio.value,
        }

        # 画像→動画の場合
        if source_image_url:
            body["promptImage"] = source_image_url

        # シード値（オプション）
        if seed is not None:
            body["seed"] = seed

        logger.info(f"Starting video generation: model={model}, duration={duration.value}s")
        logger.debug(f"Request body: {body}")

        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(
                    f"{self._api_url}/v1/image_to_video",
                    headers=headers,
                    json=body,
                )

                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    raise RunwayRateLimitError(
                        retry_after=int(retry_after) if retry_after else None
                    )

                if response.status_code == 401:
                    raise RunwayAPIError(
                        message="Invalid API key",
                        details={"status_code": 401},
                    )

                if response.status_code == 402:
                    raise RunwayQuotaExceededError()

                if response.status_code >= 500:
                    raise RunwayServerError(
                        status_code=response.status_code,
                        message=response.text,
                    )

                if response.status_code != 200:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", response.text)

                    # コンテンツポリシー違反チェック
                    if "policy" in error_msg.lower() or "inappropriate" in error_msg.lower():
                        raise VideoContentPolicyViolationError(reason=error_msg)

                    raise RunwayAPIError(
                        message=error_msg,
                        details={"status_code": response.status_code, "response": error_data},
                    )

                data = response.json()
                task_id = data.get("id")

                logger.info(f"Video generation started: task_id={task_id}")

                return {
                    "task_id": task_id,
                    "status": "PENDING",
                    "progress": 0,
                }

        except httpx.TimeoutException:
            raise RunwayTimeoutError(timeout_seconds=self._timeout_seconds)
        except (RunwayAPIError, RunwayRateLimitError, RunwayTimeoutError,
                RunwayQuotaExceededError, RunwayServerError, VideoContentPolicyViolationError):
            raise
        except Exception as e:
            logger.error(f"Unexpected error in Runway API: {str(e)}")
            raise RunwayAPIError(
                message=str(e),
                original_error=e,
            )

    async def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """
        タスクのステータスを取得

        Args:
            task_id: タスクID

        Returns:
            {
                "task_id": "...",
                "status": "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED",
                "progress": 0-100,
                "output_url": "..." (成功時),
                "error": "..." (失敗時),
            }
        """
        if not self._api_key:
            raise RunwayAPIError(
                message="RUNWAY_API_KEY is not set",
            )

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "X-Runway-Version": "2024-09-13",
        }

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.get(
                    f"{self._api_url}/v1/tasks/{task_id}",
                    headers=headers,
                )

                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    raise RunwayRateLimitError(
                        retry_after=int(retry_after) if retry_after else None
                    )

                if response.status_code != 200:
                    raise RunwayAPIError(
                        message=f"Failed to get task status: {response.text}",
                        details={"status_code": response.status_code},
                    )

                data = response.json()

                status = data.get("status", "PENDING")
                progress = data.get("progress", 0)

                result = {
                    "task_id": task_id,
                    "status": status,
                    "progress": progress,
                }

                # 成功時は出力URLを取得
                if status == "SUCCEEDED":
                    output = data.get("output", [])
                    if output:
                        result["output_url"] = output[0]  # 最初の出力
                    result["createdAt"] = data.get("createdAt")

                # 失敗時はエラーメッセージを取得
                if status == "FAILED":
                    result["error"] = data.get("failure", "Unknown error")
                    result["failure_code"] = data.get("failureCode")

                return result

        except httpx.TimeoutException:
            raise RunwayTimeoutError(timeout_seconds=60)
        except (RunwayAPIError, RunwayRateLimitError, RunwayTimeoutError):
            raise
        except Exception as e:
            logger.error(f"Error getting task status: {str(e)}")
            raise RunwayAPIError(
                message=str(e),
                original_error=e,
            )

    async def wait_for_completion(
        self,
        task_id: str,
        poll_interval: float = RUNWAY_POLL_INTERVAL_SECONDS,
        max_attempts: int = RUNWAY_MAX_POLL_ATTEMPTS,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> Dict[str, Any]:
        """
        タスクの完了を待つ

        Args:
            task_id: タスクID
            poll_interval: ポーリング間隔（秒）
            max_attempts: 最大ポーリング回数
            progress_callback: 進捗コールバック関数（オプション）

        Returns:
            完了時のタスク情報
        """
        logger.info(f"Waiting for task completion: {task_id}")

        for attempt in range(max_attempts):
            status_result = await self.get_task_status(task_id)
            status = status_result.get("status")
            progress = status_result.get("progress", 0)

            logger.debug(f"Task {task_id}: status={status}, progress={progress}%")

            if progress_callback:
                progress_callback(int(progress or 0), str(status or ""))

            if status == "SUCCEEDED":
                logger.info(f"Task {task_id} completed successfully")
                return status_result

            if status == "FAILED":
                error_msg = status_result.get("error", "Unknown error")
                failure_code = status_result.get("failure_code", "")

                # コンテンツポリシー違反チェック
                if "policy" in error_msg.lower() or failure_code == "CONTENT_MODERATION":
                    raise VideoContentPolicyViolationError(reason=error_msg)

                raise RunwayAPIError(
                    message=f"Video generation failed: {error_msg}",
                    details={"failure_code": failure_code},
                )

            await asyncio.sleep(poll_interval)

        raise RunwayTimeoutError(timeout_seconds=int(poll_interval * max_attempts))

    async def cancel_task(self, task_id: str) -> bool:
        """
        タスクをキャンセル

        Args:
            task_id: タスクID

        Returns:
            キャンセル成功かどうか
        """
        if not self._api_key:
            raise RunwayAPIError(message="RUNWAY_API_KEY is not set")

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "X-Runway-Version": "2024-09-13",
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.delete(
                    f"{self._api_url}/v1/tasks/{task_id}",
                    headers=headers,
                )

                if response.status_code in (200, 204):
                    logger.info(f"Task {task_id} cancelled successfully")
                    return True

                logger.warning(f"Failed to cancel task {task_id}: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"Error cancelling task: {str(e)}")
            return False


# =============================================================================
# ファクトリ関数
# =============================================================================


def create_runway_client(
    api_key: Optional[str] = None,
    timeout_seconds: int = RUNWAY_API_TIMEOUT_SECONDS,
) -> RunwayClient:
    """
    RunwayClientを作成

    Args:
        api_key: Runway API Key（省略時は環境変数から取得）
        timeout_seconds: タイムアウト秒数

    Returns:
        RunwayClient
    """
    return RunwayClient(
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )
