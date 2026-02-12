# handlers/zoom_webhook_handler.py
"""
Zoom Webhookイベントハンドラー

recording.completed Webhookイベントを処理し、
ZoomBrainInterfaceを呼び出して議事録を自動生成する。

フロー:
1. Webhook署名検証 → 不正リクエスト拒否
2. endpoint.url_validation → チャレンジ応答
3. recording.completed → 議事録生成パイプライン起動
4. 冪等性チェック → 重複処理防止

Author: Claude Opus 4.6
Created: 2026-02-13
"""

import asyncio
import logging
import os
from typing import Any, Dict, Optional

from lib.brain.models import HandlerResult

logger = logging.getLogger(__name__)

# デフォルト投稿先: 管理部ルーム（Phase 4でルーム自動振り分け実装予定）
DEFAULT_ROOM_ID = os.environ.get("ZOOM_DEFAULT_ROOM_ID", "405315911")

# ソウルくんのChatWorkアカウントID
SOULKUN_ACCOUNT_ID = "10909425"


async def handle_zoom_webhook_event(
    event_type: str,
    payload: Dict[str, Any],
    pool,
    organization_id: str,
    get_ai_response_func=None,
) -> HandlerResult:
    """
    Zoom Webhookイベントを処理する。

    Args:
        event_type: Zoomイベントタイプ（"recording.completed" 等）
        payload: Webhookペイロードの "payload" 部分
        pool: DB接続プール
        organization_id: 組織ID（CLAUDE.md鉄則#1）
        get_ai_response_func: LLM呼び出し関数（Brain側から注入）

    Returns:
        HandlerResult with processing status
    """
    if event_type != "recording.completed":
        logger.info("Zoom webhook: ignoring event type=%s", event_type)
        return HandlerResult(
            success=True,
            message=f"Event type '{event_type}' ignored",
            data={"event_type": event_type, "action": "ignored"},
        )

    # recording.completed イベントを処理
    meeting_obj = payload.get("object", {})
    meeting_id_raw = meeting_obj.get("id")
    meeting_uuid = meeting_obj.get("uuid", "")
    topic = meeting_obj.get("topic", "Zoomミーティング")
    host_email = meeting_obj.get("host_email", "")
    start_time = meeting_obj.get("start_time", "")
    recording_files = meeting_obj.get("recording_files", [])

    # VTTファイルの有無を確認
    has_transcript = any(
        f.get("file_type") == "TRANSCRIPT" for f in recording_files
    )

    # CLAUDE.md §3-2 #8: PIIをログに含めない（host_emailはマスク）
    logger.info(
        "Zoom webhook: recording.completed topic=%s, has_transcript=%s, host=%s",
        topic,
        has_transcript,
        host_email[:3] + "***" if host_email else "unknown",
    )

    if not pool or not organization_id:
        return HandlerResult(
            success=False,
            message="システム設定エラー（DB接続またはorganization_id未設定）",
            data={},
        )

    from lib.meetings.zoom_brain_interface import ZoomBrainInterface

    interface = ZoomBrainInterface(pool, organization_id)

    # Webhook経由: meeting_idを直接指定して録画を取得
    zoom_meeting_id = str(meeting_id_raw) if meeting_id_raw else None

    result = await interface.process_zoom_minutes(
        room_id=DEFAULT_ROOM_ID,
        account_id=SOULKUN_ACCOUNT_ID,
        meeting_title=topic,
        zoom_meeting_id=zoom_meeting_id,
        zoom_user_email=host_email or None,
        get_ai_response_func=get_ai_response_func,
    )

    # Webhook起点であることをデータに記録
    if result.data:
        result.data["trigger"] = "webhook"
        result.data["webhook_event"] = "recording.completed"

    return result
