# handlers/zoom_meeting_handler.py
"""
Zoom議事録ハンドラー

ZoomBrainInterfaceへの薄いラッパー。
同期I/OはZoomBrainInterface内でasyncio.to_thread()でラップ済み（CLAUDE.md §3-2 #6）。

Author: Claude Opus 4.6
Created: 2026-02-10
"""

import logging
from typing import Any, Dict

from lib.brain.models import HandlerResult

logger = logging.getLogger(__name__)


async def handle_zoom_meeting_minutes(
    room_id: str,
    account_id: str,
    sender_name: str,
    params: Dict[str, Any],
    **kwargs,
) -> HandlerResult:
    """
    Zoom議事録生成を処理する。

    Brain経由で呼び出され、議事録結果をBrainに返す。
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

    from lib.meetings.zoom_brain_interface import ZoomBrainInterface

    interface = ZoomBrainInterface(pool, organization_id)

    get_ai_response_func = kwargs.get("get_ai_response_func")

    return await interface.process_zoom_minutes(
        room_id=room_id,
        account_id=account_id,
        meeting_title=params.get("meeting_title"),
        zoom_meeting_id=params.get("zoom_meeting_id"),
        zoom_user_email=params.get("zoom_user_email"),
        get_ai_response_func=get_ai_response_func,
    )
