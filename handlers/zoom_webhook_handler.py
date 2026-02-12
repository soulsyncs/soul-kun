# handlers/zoom_webhook_handler.py
"""
Zoom Webhookイベントハンドラー

recording.completed Webhookイベントを処理し、
ZoomBrainInterfaceを呼び出して議事録を自動生成する。

フロー:
1. Webhook署名検証 → 不正リクエスト拒否
2. endpoint.url_validation → チャレンジ応答
3. recording.completed → カレンダー照合 → ルーム自動判定 → 議事録生成
4. 冪等性チェック → 重複処理防止

Phase 3: Google Calendar連携追加
Phase 4: ChatWorkルーム自動振り分け統合

Author: Claude Opus 4.6
Created: 2026-02-13
Updated: 2026-02-13 (Phase 3+4統合)
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from lib.admin_config import DEFAULT_ADMIN_ROOM_ID, DEFAULT_BOT_ACCOUNT_ID
from lib.brain.models import HandlerResult

logger = logging.getLogger(__name__)

# ソウルくんのChatWorkアカウントID（admin_configのSoTから取得）
SOULKUN_ACCOUNT_ID = DEFAULT_BOT_ACCOUNT_ID


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
    topic = meeting_obj.get("topic", "Zoomミーティング")
    host_email = meeting_obj.get("host_email", "")
    start_time = meeting_obj.get("start_time", "")
    recording_files = meeting_obj.get("recording_files", [])

    # VTTファイルの有無を確認
    has_transcript = any(
        f.get("file_type") == "TRANSCRIPT" for f in recording_files
    )

    # CLAUDE.md §3-2 #8: PIIをログに含めない（topic/host_emailはマスク）
    logger.info(
        "Zoom webhook: recording.completed meeting_id=%s, has_transcript=%s, host=%s",
        meeting_id_raw,
        has_transcript,
        host_email[:3] + "***" if host_email else "unknown",
    )

    if not pool or not organization_id:
        return HandlerResult(
            success=False,
            message="システム設定エラー（DB接続またはorganization_id未設定）",
            data={},
        )

    # Phase 3: Google Calendar照合（オプショナル）
    calendar_description = None
    calendar_event_title = None
    calendar_attendees = []
    calendar_event = await _lookup_calendar_event(start_time, topic)
    if calendar_event:
        calendar_description = calendar_event.description
        calendar_event_title = calendar_event.title
        calendar_attendees = calendar_event.attendees
        logger.info(
            "Calendar event matched: has_cw_tag=%s, attendees=%d",
            calendar_event.has_cw_tag,
            len(calendar_attendees),
        )

    # Phase 4: ルーム自動振り分け（DB I/Oを含むためto_thread）
    resolved_room_id = await asyncio.to_thread(
        _resolve_room_id, pool, organization_id, topic, calendar_description
    )

    from lib.meetings.zoom_brain_interface import ZoomBrainInterface

    interface = ZoomBrainInterface(pool, organization_id)

    # Webhook経由: meeting_idを直接指定して録画を取得
    zoom_meeting_id = str(meeting_id_raw) if meeting_id_raw else None

    result = await interface.process_zoom_minutes(
        room_id=resolved_room_id,
        account_id=SOULKUN_ACCOUNT_ID,
        meeting_title=calendar_event_title or topic,
        zoom_meeting_id=zoom_meeting_id,
        zoom_user_email=host_email or None,
        get_ai_response_func=get_ai_response_func,
    )

    # Webhook起点であることをデータに記録
    if result.data:
        result.data["trigger"] = "webhook"
        result.data["webhook_event"] = "recording.completed"
        result.data["room_resolved_by"] = (
            "calendar+router" if calendar_event else "router"
        )
        if calendar_attendees:
            result.data["attendee_count"] = len(calendar_attendees)

    return result


async def _lookup_calendar_event(
    start_time_str: str, topic: str
) -> Optional[Any]:
    """
    Google Calendar照合（Phase 3）。

    ENABLE_GOOGLE_CALENDAR=trueの場合のみ実行。
    エラー時はNoneを返し、議事録生成は継続する。
    """
    try:
        from lib.meetings.google_calendar_client import create_calendar_client_from_env

        client = create_calendar_client_from_env()
        if client is None:
            return None

        # Zoom start_timeをパース
        if not start_time_str:
            return None

        zoom_start = datetime.fromisoformat(
            start_time_str.replace("Z", "+00:00")
        )

        return await asyncio.to_thread(
            client.find_matching_event,
            zoom_start,
            zoom_topic=topic,
        )
    except Exception as e:
        logger.warning(
            "Calendar lookup failed (non-fatal): %s", type(e).__name__
        )
        return None


def _resolve_room_id(
    pool,
    organization_id: str,
    topic: str,
    calendar_description: Optional[str],
) -> str:
    """
    ChatWorkルーム自動振り分け（Phase 4）。

    room_routerを使って投稿先を判定する。
    エラー時はDEFAULT_ADMIN_ROOM_IDにフォールバック。
    """
    try:
        from lib.meetings.room_router import MeetingRoomRouter

        router = MeetingRoomRouter(pool, organization_id)
        result = router.resolve_room(
            meeting_title=topic,
            calendar_description=calendar_description,
        )
        logger.info(
            "Room resolved: room_id=%s, method=%s, confidence=%.2f",
            result.room_id,
            result.routing_method,
            result.confidence,
        )
        return result.room_id
    except Exception as e:
        logger.warning(
            "Room routing failed (fallback to admin): %s", type(e).__name__
        )
        return DEFAULT_ADMIN_ROOM_ID
