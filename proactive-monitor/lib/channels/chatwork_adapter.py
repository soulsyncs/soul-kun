# lib/channels/chatwork_adapter.py
"""
ChatWorkチャネルアダプター

ChatWork固有のメッセージ処理ロジックを統一インターフェースに実装する。
main.pyから抽出したclean_chatwork_message(), is_mention_or_reply_to_soulkun()等を
ChannelAdapterの形に統合。

【設計原則】
- CLAUDE.md 2-1: 脳バイパス禁止 → アダプターは正規化と送受信のみ
- CLAUDE.md 9: SQLパラメータ化 → DB操作なし（アダプター層はDB非依存）
- 既存のlib/chatwork.py ChatworkClientを内部利用

Author: Claude Code
Created: 2026-02-07
"""

import os
import re
import logging
from typing import Optional, Dict, Any

from lib.channels.base import ChannelAdapter, ChannelMessage, SendResult

logger = logging.getLogger(__name__)

# ソウルくんのChatWorkアカウントID（環境変数 or デフォルト）
SOULKUN_ACCOUNT_ID = os.environ.get("SOULKUN_ACCOUNT_ID", "10909425")


# =============================================================================
# ChatWorkメッセージ処理ユーティリティ
# =============================================================================


def clean_chatwork_message(body: str) -> str:
    """
    ChatWorkメッセージからプラットフォーム固有タグを除去

    main.pyのclean_chatwork_message()を移設。

    処理内容:
    - [To:XXXXX] メンションタグ除去
    - [rp aid=XXXXX][/rp] 返信タグ除去
    - [info], [code]等の装飾タグ除去
    - 連続空白の正規化

    Args:
        body: 元のメッセージ本文

    Returns:
        クリーニング済みテキスト
    """
    if not body:
        return ""

    if not isinstance(body, str):
        try:
            body = str(body)
        except Exception:
            return ""

    try:
        clean = body
        # [To:XXXXX] メンションタグ（敬称付き）
        clean = re.sub(r'\[To:\d+\]\s*[^\n\[]*(?:さん|くん|ちゃん|様|氏)?', '', clean)
        # [rp aid=XXXXX][/rp] 返信タグ
        clean = re.sub(r'\[rp aid=\d+[^\]]*\]\[/rp\]', '', clean)
        # [info], [/info], [code], [/code] 等の装飾タグ
        clean = re.sub(r'\[/?[a-zA-Z]+\]', '', clean)
        # 残りのブラケットタグ
        clean = re.sub(r'\[.*?\]', '', clean)
        # 前後の空白と連続空白の正規化
        clean = clean.strip()
        clean = re.sub(r'\s+', ' ', clean)
        return clean
    except Exception as e:
        logger.warning("clean_chatwork_message error: %s", e)
        return body


def is_mention_to_bot(body: str, bot_account_id: str = SOULKUN_ACCOUNT_ID) -> bool:
    """
    メッセージがボット宛のメンションまたは返信かどうかを判定

    main.pyのis_mention_or_reply_to_soulkun()を移設・汎用化。

    Args:
        body: 元のメッセージ本文
        bot_account_id: ボットのアカウントID

    Returns:
        ボット宛かどうか
    """
    if not body or not isinstance(body, str):
        return False

    try:
        # メンションパターン: [To:10909425]
        if f"[To:{bot_account_id}]" in body:
            return True
        # 返信ボタンパターン: [rp aid=10909425 to=...]
        if f"[rp aid={bot_account_id}" in body:
            return True
        return False
    except Exception as e:
        logger.warning("is_mention_to_bot error: %s", e)
        return False


def is_toall_mention(body: str) -> bool:
    """
    オールメンション（[toall]）かどうかを判定

    オールメンションはアナウンス用途のため、ボットは反応しない。

    Args:
        body: 元のメッセージ本文

    Returns:
        [toall]が含まれていればTrue
    """
    if not body or not isinstance(body, str):
        return False

    try:
        return "[toall]" in body.lower()
    except Exception as e:
        logger.warning("is_toall_mention error: %s", e)
        return False


def is_bot_reply_loop(body: str) -> bool:
    """
    ボットの返信パターンを検出（無限ループ防止）

    ソウルくんの返信には「ウル」が含まれ、かつ返信タグがある場合、
    それはボットの返信なので無視する。

    Args:
        body: 元のメッセージ本文

    Returns:
        ボットの返信ループパターンかどうか
    """
    if not body or not isinstance(body, str):
        return False

    return "ウル" in body and "[rp aid=" in body


# =============================================================================
# ChatWorkチャネルアダプター
# =============================================================================


class ChatworkChannelAdapter(ChannelAdapter):
    """
    ChatWork用チャネルアダプター

    ChatWork Webhookからのイベントを統一メッセージ型に変換し、
    ChatWork APIへのメッセージ送信を提供する。

    内部でlib/chatwork.py のChatworkClientを利用する。
    """

    def __init__(
        self,
        bot_account_id: str = SOULKUN_ACCOUNT_ID,
        chatwork_client=None,
    ):
        """
        Args:
            bot_account_id: ボットのChatWorkアカウントID
            chatwork_client: ChatworkClientインスタンス（省略時は内部生成）
        """
        self._bot_account_id = bot_account_id
        self._client = chatwork_client

    def _get_client(self):
        """遅延初期化でChatworkClientを取得"""
        if self._client is None:
            from lib.chatwork import ChatworkClient
            self._client = ChatworkClient()
        return self._client

    @property
    def platform_name(self) -> str:
        return "chatwork"

    def parse_webhook(self, request_data: Dict[str, Any]) -> Optional[ChannelMessage]:
        """
        ChatWork Webhookイベントを統一メッセージ型に変換

        ChatWork Webhookの形式:
        {
            "webhook_event_type": "mention_to_me",
            "webhook_event": {
                "room_id": 12345,
                "body": "[To:10909425]ソウルくん こんにちは",
                "message_id": "msg123",
                "from_account_id": 67890,  # mention_to_meの場合
                "account_id": 67890,       # それ以外の場合
            }
        }

        Args:
            request_data: Webhookリクエストボディ

        Returns:
            ChannelMessage（パース成功時）、None（無効なデータ時）
        """
        if not request_data or "webhook_event" not in request_data:
            return None

        event = request_data["webhook_event"]
        event_type = request_data.get("webhook_event_type", "")

        room_id = str(event.get("room_id", ""))
        raw_body = event.get("body", "")
        message_id = str(event.get("message_id", ""))

        # 送信者ID: イベントタイプによりフィールド名が異なる
        if event_type == "mention_to_me":
            sender_id = str(event.get("from_account_id", ""))
        else:
            sender_id = str(event.get("account_id", ""))

        # メッセージのクリーニングと判定
        clean_body = self.clean_message(raw_body)
        is_addressed = self.is_addressed_to_bot(raw_body) or event_type == "mention_to_me"
        is_from_bot = sender_id == self._bot_account_id
        is_loop = is_bot_reply_loop(raw_body)

        # CRITICAL-1: [toall] + 直接メンションの場合はbroadcastにしない
        # toallはアナウンス用途だが、直接メンションされていれば応答すべき
        is_broadcast_toall = is_toall_mention(raw_body) and not is_addressed

        return ChannelMessage(
            platform="chatwork",
            room_id=room_id,
            sender_id=sender_id,
            sender_name="",  # 後でget_sender_name()で解決
            body=clean_body,
            raw_body=raw_body,
            message_id=message_id,
            is_bot_addressed=is_addressed,
            is_broadcast=is_broadcast_toall or is_loop,
            is_from_bot=is_from_bot,
            event_type=event_type,
            # CRITICAL-2: PII保護 - 生のwebhookイベントを保存しない
            metadata={
                "room_id": event.get("room_id"),
                "message_id": event.get("message_id"),
            },
        )

    def send_message(
        self,
        room_id: str,
        message: str,
        reply_to: Optional[str] = None,
    ) -> SendResult:
        """
        ChatWorkにメッセージを送信

        Args:
            room_id: 送信先ルームID
            message: メッセージ本文
            reply_to: 返信先アカウントID（現在未使用）

        Returns:
            SendResult
        """
        # HIGH-3: room_idのバリデーション
        try:
            rid = int(room_id)
        except (ValueError, TypeError):
            logger.warning("Invalid room_id: %s", room_id)
            return SendResult(success=False, error=f"Invalid room_id: {room_id}")

        try:
            client = self._get_client()
            result = client.send_message(
                room_id=rid,
                message=message,
                reply_to=int(reply_to) if reply_to else None,
            )
            return SendResult(
                success=True,
                message_id=str(result) if result else "",
            )
        except Exception as e:
            logger.warning("ChatWork send_message error: %s", e)
            return SendResult(success=False, error=str(e))

    def get_sender_name(self, room_id: str, sender_id: str) -> str:
        """
        送信者の表示名をChatWork APIから取得

        Args:
            room_id: ルームID
            sender_id: アカウントID

        Returns:
            表示名（取得失敗時は"ゲスト"）
        """
        try:
            rid = int(room_id)
        except (ValueError, TypeError):
            logger.warning("Invalid room_id for get_sender_name: %s", room_id)
            return "ゲスト"

        try:
            client = self._get_client()
            members = client.get_room_members(rid)
            for member in members:
                if str(member.get("account_id")) == str(sender_id):
                    return member.get("name", "ゲスト")
        except Exception as e:
            logger.warning("ChatWork get_sender_name error: %s", e)
        return "ゲスト"

    def clean_message(self, raw_body: str) -> str:
        """ChatWork固有タグを除去"""
        return clean_chatwork_message(raw_body)

    def is_addressed_to_bot(self, raw_body: str) -> bool:
        """ボット宛メンション・返信を判定"""
        return is_mention_to_bot(raw_body, self._bot_account_id)
