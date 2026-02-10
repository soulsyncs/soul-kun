"""
Chatwork APIクライアントモジュール

同期（Flask）と非同期（FastAPI）の両方に対応したChatwork APIクライアント。

使用例（Flask/Cloud Functions - 同期）:
    from lib.chatwork import ChatworkClient

    client = ChatworkClient()
    client.send_message(room_id=12345, message="Hello!")
    rooms = client.get_rooms()

使用例（FastAPI - 非同期）:
    from lib.chatwork import ChatworkAsyncClient

    client = ChatworkAsyncClient()
    await client.send_message(room_id=12345, message="Hello!")
    rooms = await client.get_rooms()

Phase 4対応:
    - テナント別APIトークン対応
    - レート制限の自動ハンドリング
    - リトライ機能
"""

from typing import Optional, List, Dict, Any, Union, cast
from dataclasses import dataclass
import time

import httpx

from lib.config import get_settings
from lib.secrets import get_secret_cached


@dataclass
class ChatworkMessage:
    """Chatworkメッセージの構造体"""
    message_id: str
    room_id: int
    account_id: int
    account_name: str
    body: str
    send_time: int


@dataclass
class ChatworkRoom:
    """Chatworkルームの構造体"""
    room_id: int
    name: str
    type: str  # "my", "direct", "group"
    role: str
    sticky: bool
    unread_num: int
    mention_num: int


@dataclass
class ChatworkTask:
    """Chatworkタスクの構造体"""
    task_id: int
    room_id: int
    account_id: int
    assigned_by_account_id: Optional[int]
    body: str
    limit_time: Optional[int]
    status: str  # "open", "done"


class ChatworkClientBase:
    """
    Chatwork APIクライアントの基底クラス

    共通のロジックを定義。
    """

    API_BASE_URL = "https://api.chatwork.com/v2"

    def __init__(
        self,
        api_token: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ):
        """
        Args:
            api_token: APIトークン（省略時はSecret Managerから取得）
            tenant_id: テナントID（Phase 4: テナント別トークン用）
        """
        self._api_token = api_token
        self._tenant_id = tenant_id
        self._settings = get_settings()

    def _get_api_token(self) -> str:
        """APIトークンを取得"""
        if self._api_token:
            return self._api_token

        # Phase 4: テナント別トークン対応
        if self._tenant_id:
            return get_secret_cached(
                f"{self._tenant_id}-chatwork-token"
            )

        return get_secret_cached("SOULKUN_CHATWORK_TOKEN")

    def _get_headers(self) -> Dict[str, str]:
        """リクエストヘッダーを取得"""
        return {
            "X-ChatWorkToken": self._get_api_token(),
            "Content-Type": "application/x-www-form-urlencoded",
        }


class ChatworkClient(ChatworkClientBase):
    """
    Chatwork API 同期クライアント

    Flask / Cloud Functions で使用。
    """

    def __init__(
        self,
        api_token: Optional[str] = None,
        tenant_id: Optional[str] = None,
        timeout: float = 10.0,
        max_retries: int = 3,
    ):
        super().__init__(api_token, tenant_id)
        self._timeout = timeout
        self._max_retries = max_retries

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
    ) -> Any:
        """
        HTTP リクエストを送信（リトライ付き）
        """
        url = f"{self.API_BASE_URL}{endpoint}"
        headers = self._get_headers()

        for attempt in range(self._max_retries):
            try:
                response = httpx.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    data=data,
                    timeout=self._timeout,
                )

                # レート制限
                if response.status_code == 429:
                    retry_after = int(
                        response.headers.get("Retry-After", "60")
                    )
                    if attempt < self._max_retries - 1:
                        time.sleep(retry_after)
                        continue
                    raise ChatworkRateLimitError(
                        f"Rate limited. Retry after {retry_after}s"
                    )

                # 成功
                if response.status_code in (200, 204):
                    if response.status_code == 204:
                        return None
                    return response.json()

                # その他のエラー
                raise ChatworkAPIError(
                    f"API error: {response.status_code} - {response.text}"
                )

            except httpx.TimeoutException:
                if attempt < self._max_retries - 1:
                    time.sleep(1)
                    continue
                raise ChatworkTimeoutError("Request timed out")

        raise ChatworkAPIError("Max retries exceeded")

    # =========================================================================
    # メッセージ API
    # =========================================================================

    def send_message(
        self,
        room_id: int,
        message: str,
        reply_to: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        メッセージを送信

        Args:
            room_id: ルームID
            message: メッセージ本文
            reply_to: 返信先アカウントID（オプション）

        Returns:
            {"message_id": "..."}
        """
        if reply_to:
            message = f"[rp aid={reply_to}][/rp]\n{message}"

        result: Dict[str, Any] = self._request(
            "POST",
            f"/rooms/{room_id}/messages",
            data={"body": message},
        )
        return result

    def get_messages(
        self,
        room_id: int,
        force: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        ルームのメッセージを取得

        Args:
            room_id: ルームID
            force: True の場合、既読メッセージも取得

        Returns:
            メッセージのリスト
        """
        params = {"force": 1} if force else {}
        result: List[Dict[str, Any]] = self._request(
            "GET",
            f"/rooms/{room_id}/messages",
            params=params,
        )
        return result if result else []

    # =========================================================================
    # ルーム API
    # =========================================================================

    def get_rooms(self) -> List[ChatworkRoom]:
        """
        参加しているルーム一覧を取得

        Returns:
            ChatworkRoom のリスト
        """
        result = self._request("GET", "/rooms")
        return [
            ChatworkRoom(
                room_id=r["room_id"],
                name=r["name"],
                type=r["type"],
                role=r["role"],
                sticky=r.get("sticky", False),
                unread_num=r.get("unread_num", 0),
                mention_num=r.get("mention_num", 0),
            )
            for r in result
        ]

    def list_direct_message_rooms(self) -> List[ChatworkRoom]:
        """
        ダイレクトメッセージ（1on1）ルーム一覧を取得

        ChatWork の room_type は3種類:
        - "my": マイチャット（自分のみ）
        - "direct": ダイレクトメッセージ（1on1対話）
        - "group": グループチャット

        Returns:
            type="direct" の ChatworkRoom リスト
        """
        all_rooms = self.get_rooms()
        return [r for r in all_rooms if r.type == "direct"]

    def get_room_members(self, room_id: int) -> List[Dict[str, Any]]:
        """
        ルームのメンバー一覧を取得

        Args:
            room_id: ルームID

        Returns:
            メンバーのリスト
        """
        result: List[Dict[str, Any]] = self._request("GET", f"/rooms/{room_id}/members")
        return result

    # =========================================================================
    # タスク API
    # =========================================================================

    def get_tasks(
        self,
        room_id: int,
        status: str = "open",
        assigned_by_account_id: Optional[int] = None,
    ) -> List[ChatworkTask]:
        """
        ルームのタスク一覧を取得

        Args:
            room_id: ルームID
            status: "open" or "done"
            assigned_by_account_id: 依頼者のアカウントID

        Returns:
            ChatworkTask のリスト
        """
        params: Dict[str, Any] = {"status": status}
        if assigned_by_account_id:
            params["assigned_by_account_id"] = assigned_by_account_id

        result = self._request(
            "GET",
            f"/rooms/{room_id}/tasks",
            params=params,
        )

        return [
            ChatworkTask(
                task_id=t["task_id"],
                room_id=room_id,
                account_id=t["account"]["account_id"],
                assigned_by_account_id=t.get(
                    "assigned_by_account", {}
                ).get("account_id"),
                body=t["body"],
                limit_time=t.get("limit_time"),
                status=t["status"],
            )
            for t in (result or [])
        ]

    def create_task(
        self,
        room_id: int,
        body: str,
        to_ids: List[int],
        limit_time: Optional[int] = None,
        limit_type: str = "date",
    ) -> Dict[str, Any]:
        """
        タスクを作成

        Args:
            room_id: ルームID
            body: タスク内容
            to_ids: 担当者のアカウントIDリスト
            limit_time: 期限（UNIXタイムスタンプ）
            limit_type: "date" or "time"

        Returns:
            {"task_ids": [...]}
        """
        data: Dict[str, Any] = {
            "body": body,
            "to_ids": ",".join(map(str, to_ids)),
        }
        if limit_time:
            data["limit"] = limit_time
            data["limit_type"] = limit_type

        result: Dict[str, Any] = self._request(
            "POST",
            f"/rooms/{room_id}/tasks",
            data=data,
        )
        return result


class ChatworkAsyncClient(ChatworkClientBase):
    """
    Chatwork API 非同期クライアント

    FastAPI で使用。
    """

    def __init__(
        self,
        api_token: Optional[str] = None,
        tenant_id: Optional[str] = None,
        timeout: float = 10.0,
        max_retries: int = 3,
    ):
        super().__init__(api_token, tenant_id)
        self._timeout = timeout
        self._max_retries = max_retries
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """非同期HTTPクライアントを取得"""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def close(self) -> None:
        """クライアントを閉じる"""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
    ) -> Any:
        """HTTP リクエストを送信（非同期・リトライ付き）"""
        import asyncio

        url = f"{self.API_BASE_URL}{endpoint}"
        headers = self._get_headers()
        client = await self._get_client()

        for attempt in range(self._max_retries):
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    data=data,
                )

                if response.status_code == 429:
                    retry_after = int(
                        response.headers.get("Retry-After", "60")
                    )
                    if attempt < self._max_retries - 1:
                        await asyncio.sleep(retry_after)
                        continue
                    raise ChatworkRateLimitError(
                        f"Rate limited. Retry after {retry_after}s"
                    )

                if response.status_code in (200, 204):
                    if response.status_code == 204:
                        return None
                    return response.json()

                raise ChatworkAPIError(
                    f"API error: {response.status_code} - {response.text}"
                )

            except httpx.TimeoutException:
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(1)
                    continue
                raise ChatworkTimeoutError("Request timed out")

        raise ChatworkAPIError("Max retries exceeded")

    async def send_message(
        self,
        room_id: int,
        message: str,
        reply_to: Optional[int] = None,
    ) -> Dict[str, Any]:
        """メッセージを送信（非同期）"""
        if reply_to:
            message = f"[rp aid={reply_to}][/rp]\n{message}"

        result: Dict[str, Any] = await self._request(
            "POST",
            f"/rooms/{room_id}/messages",
            data={"body": message},
        )
        return result

    async def get_rooms(self) -> List[ChatworkRoom]:
        """ルーム一覧を取得（非同期）"""
        result = await self._request("GET", "/rooms")
        return [
            ChatworkRoom(
                room_id=r["room_id"],
                name=r["name"],
                type=r["type"],
                role=r["role"],
                sticky=r.get("sticky", False),
                unread_num=r.get("unread_num", 0),
                mention_num=r.get("mention_num", 0),
            )
            for r in result
        ]

    async def list_direct_message_rooms(self) -> List[ChatworkRoom]:
        """ダイレクトメッセージ（1on1）ルーム一覧を取得（非同期）"""
        all_rooms = await self.get_rooms()
        return [r for r in all_rooms if r.type == "direct"]


# =============================================================================
# 例外クラス
# =============================================================================

class ChatworkError(Exception):
    """Chatwork API エラーの基底クラス"""
    pass


class ChatworkAPIError(ChatworkError):
    """API エラー"""
    pass


class ChatworkRateLimitError(ChatworkError):
    """レート制限エラー"""
    pass


class ChatworkTimeoutError(ChatworkError):
    """タイムアウトエラー"""
    pass
