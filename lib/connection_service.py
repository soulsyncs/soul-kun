"""
ChatWork接続情報クエリサービス

ソウルくんがDMできる相手（1on1）の一覧を提供する。

【セキュリティ方針】
- OWNER（CEO/Admin）: 全1on1ルームを開示
- 非OWNER: 「この情報は代表のみ開示可能」と拒否

【10の鉄則準拠】
- #1: organization_id でフィルタ
- #3: Cloud Loggingで監査ログ出力
- #8: エラーメッセージに機密情報を含めない
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from lib.chatwork import ChatworkClient, ChatworkAsyncClient

logger = logging.getLogger(__name__)


# =============================================================================
# 定数
# =============================================================================

# CEO アカウントID（lib/brain/ceo_learning.py と同期）
CEO_ACCOUNT_IDS = [
    "1728974",  # 菊地雅克（カズさん）
]


# =============================================================================
# データクラス
# =============================================================================

class ConnectionPolicy(str, Enum):
    """接続情報の開示ポリシー"""
    OWNER = "owner"         # CEO/Admin - フル開示
    NON_OWNER = "non_owner"  # 拒否


@dataclass
class DirectMessageRoom:
    """1on1 DMルーム情報"""
    room_id: int
    partner_name: str
    unread_count: int = 0


@dataclass
class ConnectionQueryResult:
    """接続クエリの結果"""
    allowed: bool
    policy: ConnectionPolicy
    total_count: int = 0
    rooms: List[DirectMessageRoom] = field(default_factory=list)
    message: str = ""
    truncated: bool = False  # 件数上限で切られたか


# =============================================================================
# ConnectionService
# =============================================================================

class ConnectionService:
    """
    ChatWork接続情報クエリサービス

    使用例:
        service = ConnectionService(chatwork_client=client, org_id="...")
        result = service.query_connections(account_id="1728974")
    """

    MAX_DISPLAY_COUNT = 30  # 表示上限

    def __init__(
        self,
        chatwork_client: "ChatworkClient",
        org_id: str,
    ):
        """
        Args:
            chatwork_client: ChatworkClient インスタンス
            org_id: 組織ID（監査ログ用）
        """
        self.chatwork_client = chatwork_client
        self.org_id = org_id
        logger.info(f"[ConnectionService] initialized: org_id={org_id}")

    def is_owner(self, account_id: str) -> bool:
        """
        OWNER（開示権限者）かどうかを判定

        Args:
            account_id: ChatWorkアカウントID

        Returns:
            True: CEO または Admin
        """
        account_id_str = str(account_id)

        # 1. CEO判定
        if account_id_str in CEO_ACCOUNT_IDS:
            return True

        # 2. AdminConfig判定（遅延インポート）
        try:
            from lib.admin_config import get_admin_config
            config = get_admin_config(self.org_id)
            if config and config.is_admin(account_id_str):
                return True
        except ImportError:
            logger.warning("[ConnectionService] admin_config not available")
        except Exception as e:
            logger.warning(f"[ConnectionService] AdminConfig check failed: {e}")

        return False

    def get_direct_message_rooms(self) -> List[DirectMessageRoom]:
        """
        1on1 DMルーム一覧を取得

        Returns:
            DirectMessageRoom のリスト
        """
        dm_rooms = self.chatwork_client.list_direct_message_rooms()

        return [
            DirectMessageRoom(
                room_id=r.room_id,
                partner_name=r.name,
                unread_count=r.unread_num,
            )
            for r in dm_rooms
        ]

    def query_connections(
        self,
        account_id: str,
        max_count: Optional[int] = None,
    ) -> ConnectionQueryResult:
        """
        接続情報をクエリ

        Args:
            account_id: リクエスト者のアカウントID
            max_count: 表示上限（省略時はMAX_DISPLAY_COUNT）

        Returns:
            ConnectionQueryResult
        """
        max_count = max_count or self.MAX_DISPLAY_COUNT
        account_id_str = str(account_id)

        # 権限チェック
        if not self.is_owner(account_id_str):
            logger.info(
                f"[ConnectionService] Access denied: account_id={account_id_str}"
            )
            return ConnectionQueryResult(
                allowed=False,
                policy=ConnectionPolicy.NON_OWNER,
                message=(
                    "この情報は代表のみ開示可能ウル🐺\n"
                    "自分のDM一覧はChatWork側で確認してね！"
                ),
            )

        # DMルーム取得
        try:
            rooms = self.get_direct_message_rooms()
            total_count = len(rooms)
            truncated = total_count > max_count
            display_rooms = rooms[:max_count]

            # メッセージ生成
            names = [r.partner_name for r in display_rooms]
            names_text = "、".join(names)

            if total_count == 0:
                message = "ソウルくんはまだ誰ともDMで繋がっていないウル🐺"
            elif truncated:
                message = (
                    f"ソウルくんは {total_count} 人と1on1でつながってるウル🐺\n\n"
                    f"（上位{max_count}件を表示）\n{names_text}"
                )
            else:
                message = (
                    f"ソウルくんは {total_count} 人と1on1でつながってるウル🐺\n\n"
                    f"{names_text}"
                )

            logger.info(
                f"[ConnectionService] Query success: "
                f"account_id={account_id_str}, count={total_count}"
            )

            return ConnectionQueryResult(
                allowed=True,
                policy=ConnectionPolicy.OWNER,
                total_count=total_count,
                rooms=display_rooms,
                message=message,
                truncated=truncated,
            )

        except Exception as e:
            logger.error(f"[ConnectionService] Error: {e}")
            return ConnectionQueryResult(
                allowed=True,  # 権限はあったが取得失敗
                policy=ConnectionPolicy.OWNER,
                message="接続情報の取得に失敗したウル🐺",
            )


# =============================================================================
# 非同期版
# =============================================================================

class AsyncConnectionService:
    """
    ChatWork接続情報クエリサービス（非同期版）
    """

    MAX_DISPLAY_COUNT = 30

    def __init__(
        self,
        chatwork_client: "ChatworkAsyncClient",
        org_id: str,
    ):
        self.chatwork_client = chatwork_client
        self.org_id = org_id

    def is_owner(self, account_id: str) -> bool:
        """OWNER判定（同期版と同じロジック）"""
        account_id_str = str(account_id)

        if account_id_str in CEO_ACCOUNT_IDS:
            return True

        try:
            from lib.admin_config import get_admin_config
            config = get_admin_config(self.org_id)
            if config and config.is_admin(account_id_str):
                return True
        except Exception:
            pass

        return False

    async def get_direct_message_rooms(self) -> List[DirectMessageRoom]:
        """1on1 DMルーム一覧を取得（非同期）"""
        dm_rooms = await self.chatwork_client.list_direct_message_rooms()

        return [
            DirectMessageRoom(
                room_id=r.room_id,
                partner_name=r.name,
                unread_count=r.unread_num,
            )
            for r in dm_rooms
        ]

    async def query_connections(
        self,
        account_id: str,
        max_count: Optional[int] = None,
    ) -> ConnectionQueryResult:
        """接続情報をクエリ（非同期）"""
        max_count = max_count or self.MAX_DISPLAY_COUNT
        account_id_str = str(account_id)

        if not self.is_owner(account_id_str):
            return ConnectionQueryResult(
                allowed=False,
                policy=ConnectionPolicy.NON_OWNER,
                message=(
                    "この情報は代表のみ開示可能ウル🐺\n"
                    "自分のDM一覧はChatWork側で確認してね！"
                ),
            )

        try:
            rooms = await self.get_direct_message_rooms()
            total_count = len(rooms)
            truncated = total_count > max_count
            display_rooms = rooms[:max_count]

            names = [r.partner_name for r in display_rooms]
            names_text = "、".join(names)

            if total_count == 0:
                message = "ソウルくんはまだ誰ともDMで繋がっていないウル🐺"
            elif truncated:
                message = (
                    f"ソウルくんは {total_count} 人と1on1でつながってるウル🐺\n\n"
                    f"（上位{max_count}件を表示）\n{names_text}"
                )
            else:
                message = (
                    f"ソウルくんは {total_count} 人と1on1でつながってるウル🐺\n\n"
                    f"{names_text}"
                )

            return ConnectionQueryResult(
                allowed=True,
                policy=ConnectionPolicy.OWNER,
                total_count=total_count,
                rooms=display_rooms,
                message=message,
                truncated=truncated,
            )

        except Exception as e:
            logger.error(f"[AsyncConnectionService] Error: {e}")
            return ConnectionQueryResult(
                allowed=True,
                policy=ConnectionPolicy.OWNER,
                message="接続情報の取得に失敗したウル🐺",
            )
