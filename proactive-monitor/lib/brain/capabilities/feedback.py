"""
Feedback handler for CapabilityBridge.

CEOフィードバック生成のハンドラー。
"""

import logging
from typing import Any, Dict
from uuid import UUID

from lib.brain.models import HandlerResult

logger = logging.getLogger(__name__)


def _parse_org_uuid(org_id: str) -> UUID:
    if isinstance(org_id, UUID):
        return org_id
    try:
        return UUID(org_id)
    except (ValueError, TypeError, AttributeError):
        import uuid as uuid_mod
        return uuid_mod.uuid5(uuid_mod.NAMESPACE_OID, str(org_id))


def _safe_parse_uuid(value) -> "UUID | None":
    if not value:
        return None
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        import uuid as uuid_mod
        return uuid_mod.uuid5(uuid_mod.NAMESPACE_OID, str(value))


async def handle_feedback_generation(
    pool,
    org_id: str,
    room_id: str,
    account_id: str,
    sender_name: str,
    params: Dict[str, Any],
    **kwargs,
) -> HandlerResult:
    """
    CEOフィードバック生成ハンドラー

    Args:
        pool: DBコネクションプール
        org_id: 組織ID
        room_id: ChatWorkルームID
        account_id: ユーザーアカウントID
        sender_name: 送信者名
        params: パラメータ
            - target_user_id: 対象ユーザーID（オプション）
            - period: 期間（week/month/quarter）

    Returns:
        HandlerResult
    """
    try:
        from lib.capabilities.feedback import CEOFeedbackEngine
        from lib.capabilities.feedback.ceo_feedback_engine import CEOFeedbackSettings

        target_user_id = params.get("target_user_id")
        period = params.get("period", "week")

        org_uuid = _parse_org_uuid(org_id)

        recipient_id = _safe_parse_uuid(target_user_id or account_id)
        if recipient_id is None:
            return HandlerResult(
                success=False,
                message="対象ユーザーを特定できなかったウル🐺",
            )

        settings = CEOFeedbackSettings(
            recipient_user_id=recipient_id,
            recipient_name=sender_name,
        )

        import asyncio
        conn = await asyncio.to_thread(pool.connect)
        try:
            engine = CEOFeedbackEngine(
                conn=conn,
                organization_id=org_uuid,
                settings=settings,
            )

            query = f"{period}のフィードバック"
            feedback, _delivery_result = await engine.analyze_on_demand(
                query=query,
                deliver=False,
            )
        finally:
            await asyncio.to_thread(conn.close)

        return HandlerResult(
            success=True,
            message=feedback.summary or "フィードバックを生成したウル🐺",
            data={"feedback_id": feedback.feedback_id},
        )

    except ImportError:
        return HandlerResult(
            success=False,
            message="フィードバック機能が利用できないウル🐺",
        )
    except Exception as e:
        logger.error("[Feedback] Feedback generation failed: %s", type(e).__name__, exc_info=True)
        return HandlerResult(
            success=False,
            message="フィードバックの生成中にエラーが発生したウル🐺",
        )
