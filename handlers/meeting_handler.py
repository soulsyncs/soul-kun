# handlers/meeting_handler.py
"""
Phase C MVP0: 会議文字起こしハンドラー

MeetingBrainInterfaceへの薄いラッパー。
同期DB呼び出しは asyncio.to_thread() でラップ（CLAUDE.md §3-2 #6）。

Author: Claude Opus 4.6
Created: 2026-02-10
"""

import asyncio
import logging
from typing import Any, Dict

from lib.brain.models import HandlerResult

logger = logging.getLogger(__name__)


async def handle_meeting_upload(
    room_id: str,
    account_id: str,
    sender_name: str,
    params: Dict[str, Any],
    **kwargs,
) -> HandlerResult:
    """
    会議音声アップロードを処理する。

    Brain経由で呼び出され、文字起こし結果をBrainに返す。
    ChatWork投稿はBrainが判断する（Brain bypass防止）。
    """
    pool = kwargs.get("pool")
    organization_id = kwargs.get("organization_id", "")

    if not pool or not organization_id:
        return HandlerResult(
            success=False,
            message="システム設定エラー（DB接続またはorganization_id未設定）",
            data={},
        )

    audio_data = params.get("audio_data") or params.get("audio_file")
    if not audio_data:
        return HandlerResult(
            success=False,
            message="音声データが指定されていません。音声ファイルをアップロードしてください。",
            data={},
        )

    get_ai_response_func = kwargs.get("get_ai_response_func")
    enable_minutes = kwargs.get("enable_minutes", False)

    from lib.meetings.meeting_brain_interface import MeetingBrainInterface

    interface = MeetingBrainInterface(pool, organization_id)
    return await interface.process_meeting_upload(
        audio_data=audio_data,
        room_id=room_id,
        account_id=account_id,
        title=params.get("meeting_title"),
        meeting_type=params.get("meeting_type", "unknown"),
        get_ai_response_func=get_ai_response_func,
        enable_minutes=enable_minutes,
    )


async def handle_meeting_status(
    room_id: str,
    account_id: str,
    sender_name: str,
    params: Dict[str, Any],
    **kwargs,
) -> HandlerResult:
    """会議のステータスを照会する"""
    pool = kwargs.get("pool")
    organization_id = kwargs.get("organization_id", "")

    if not pool or not organization_id:
        return HandlerResult(
            success=False,
            message="システム設定エラー",
            data={},
        )

    meeting_id = params.get("meeting_id")
    if not meeting_id:
        return HandlerResult(
            success=False,
            message="会議IDが指定されていません。",
            data={},
        )

    from lib.meetings.meeting_brain_interface import MeetingBrainInterface

    interface = MeetingBrainInterface(pool, organization_id)
    return await interface.get_meeting_summary(meeting_id)
