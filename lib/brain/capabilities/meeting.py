"""
Meeting handlers for CapabilityBridge.

会議文字起こし（Phase C MVP0）および
Zoom議事録（Phase C Case C）のハンドラー群。
"""

import logging
from typing import Any, Callable, Dict, Optional

from lib.brain.models import HandlerResult

logger = logging.getLogger(__name__)


async def handle_meeting_transcription(
    pool,
    org_id: str,
    room_id: str,
    account_id: str,
    sender_name: str,
    params: Dict[str, Any],
    feature_flags: Optional[Dict[str, bool]] = None,
    llm_caller: Optional[Callable] = None,
    **kwargs,
) -> HandlerResult:
    """
    会議文字起こしハンドラー — MeetingBrainInterfaceに委譲

    Args:
        pool: DBコネクションプール
        org_id: 組織ID
        room_id: ChatWorkルームID
        account_id: ユーザーアカウントID
        sender_name: 送信者名
        params: パラメータ
        feature_flags: フィーチャーフラグ（ENABLE_MEETING_MINUTESの確認用）
        llm_caller: LLM呼び出し関数（議事録生成有効時に注入）

    Returns:
        HandlerResult
    """
    from handlers.meeting_handler import handle_meeting_upload

    extra_kwargs: Dict[str, Any] = {}
    if feature_flags and feature_flags.get("ENABLE_MEETING_MINUTES", False) and llm_caller:
        extra_kwargs["get_ai_response_func"] = llm_caller
        extra_kwargs["enable_minutes"] = True

    return await handle_meeting_upload(
        room_id=room_id,
        account_id=account_id,
        sender_name=sender_name,
        params=params,
        pool=pool,
        organization_id=org_id,
        **extra_kwargs,
        **kwargs,
    )


async def handle_zoom_meeting_minutes(
    pool,
    org_id: str,
    room_id: str,
    account_id: str,
    sender_name: str,
    params: Dict[str, Any],
    **kwargs,
) -> HandlerResult:
    """
    Zoom議事録ハンドラー — ZoomBrainInterfaceに委譲

    Args:
        pool: DBコネクションプール
        org_id: 組織ID
        room_id: ChatWorkルームID
        account_id: ユーザーアカウントID
        sender_name: 送信者名
        params: パラメータ

    Returns:
        HandlerResult
    """
    from handlers.zoom_meeting_handler import handle_zoom_meeting_minutes as _handle

    return await _handle(
        room_id=room_id,
        account_id=account_id,
        sender_name=sender_name,
        params=params,
        pool=pool,
        organization_id=org_id,
        **kwargs,
    )
