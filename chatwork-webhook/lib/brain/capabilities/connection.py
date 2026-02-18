"""
Connection handler for CapabilityBridge.

DM可能な相手一覧（Connection Query）のハンドラー。
"""

import logging
from typing import Any, Dict

from lib.brain.models import HandlerResult

logger = logging.getLogger(__name__)


async def handle_connection_query(
    pool,
    org_id: str,
    room_id: str,
    account_id: str,
    sender_name: str,
    params: Dict[str, Any],
    **kwargs,
) -> HandlerResult:
    """
    接続クエリハンドラー（DM可能な相手一覧）

    セキュリティ:
    - OWNER（CEO/Admin）のみ全リストを開示
    - 非OWNERには拒否メッセージ

    Args:
        pool: DBコネクションプール（未使用、ConnectionServiceがAPI経由で取得）
        org_id: 組織ID
        room_id: ChatWorkルームID
        account_id: リクエスト者のアカウントID
        sender_name: 送信者名
        params: パラメータ（未使用）

    Returns:
        HandlerResult
    """
    try:
        from lib.connection_service import ConnectionService
        from lib.connection_logger import get_connection_logger
        from lib.chatwork import ChatworkClient

        client = ChatworkClient()

        service = ConnectionService(
            chatwork_client=client,
            org_id=org_id,
        )
        result = service.query_connections(account_id)

        conn_logger = get_connection_logger()
        conn_logger.log_query(
            requester_user_id=account_id,
            allowed=result.allowed,
            result_count=result.total_count,
            organization_id=org_id,
            room_id=room_id,
        )

        data: Dict[str, Any] = (
            {
                "allowed": result.allowed,
                "total_count": result.total_count,
                "truncated": result.truncated,
            }
            if result.allowed
            else {}
        )

        return HandlerResult(
            success=True,
            message=result.message,
            data=data,
        )

    except ImportError as e:
        logger.error("[Connection] Connection query import error: %s", type(e).__name__)
        return HandlerResult(
            success=False,
            message="接続クエリ機能が利用できないウル🐺",
        )
    except Exception as e:
        logger.error("[Connection] Connection query failed: %s", type(e).__name__, exc_info=True)
        return HandlerResult(
            success=False,
            message="接続情報の取得に失敗したウル🐺",
        )
