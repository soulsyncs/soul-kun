# lib/channels/telegram_adapter.py
"""
Telegramチャネルアダプター — Step B-1: テレグラム窓口

Telegram Bot API固有のメッセージ処理ロジックを統一インターフェースに実装する。
社長専用窓口（Level 6のみ）。

【設計原則】
- CLAUDE.md §1: 全入力は脳を通る → アダプターは正規化と送受信のみ
- CLAUDE.md §8: 権限レベル6（社長/CFO）のみ利用可
- 脳バイパス禁止: アダプターはメッセージの判断をしない
- DB非依存: アダプター層はDBアクセスしない

Telegram Bot API reference:
  https://core.telegram.org/bots/api

Author: Claude Opus 4.6
Created: 2026-02-17
"""

import hashlib
import hmac
import logging
import os
import re
from typing import Any, Dict, Optional

import httpx

from lib.channels.base import ChannelAdapter, ChannelMessage, SendResult

logger = logging.getLogger(__name__)

# 環境変数
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CEO_CHAT_ID = os.environ.get("TELEGRAM_CEO_CHAT_ID", "")
TELEGRAM_API_BASE = "https://api.telegram.org"


# =============================================================================
# Telegramメッセージ処理ユーティリティ
# =============================================================================


def verify_telegram_webhook(request_data: bytes, secret_token: str, received_hash: str) -> bool:
    """
    Telegram Webhookの署名を検証する。

    Telegram Bot API v6.1+のX-Telegram-Bot-Api-Secret-Token方式。
    Webhookの登録時にsecret_tokenを設定し、
    リクエストヘッダーのX-Telegram-Bot-Api-Secret-Tokenと一致するか確認。

    Args:
        request_data: リクエストボディ（未使用だが将来のために保持）
        secret_token: 登録時に設定したシークレットトークン
        received_hash: リクエストヘッダーから取得したトークン

    Returns:
        True: 検証OK
    """
    if not secret_token or not received_hash:
        return False
    return hmac.compare_digest(secret_token, received_hash)


def is_telegram_ceo(chat_id: str) -> bool:
    """
    Telegramの送信者が社長（CEO）かどうかを判定する。

    環境変数 TELEGRAM_CEO_CHAT_ID と比較。
    Step B-2: 社長専用窓口の権限チェック。

    Args:
        chat_id: Telegramのchat_id

    Returns:
        True: 社長のchat_id
    """
    ceo_chat_id = os.environ.get("TELEGRAM_CEO_CHAT_ID", "")
    if not ceo_chat_id:
        logger.warning("TELEGRAM_CEO_CHAT_ID is not set — rejecting all Telegram messages")
        return False
    return str(chat_id) == str(ceo_chat_id)


def clean_telegram_message(text: str) -> str:
    """
    Telegramメッセージからボット固有のプレフィックスを除去する。

    - /start, /helpなどのコマンドプレフィックス
    - @botname メンションの除去
    - 先頭・末尾の空白正規化

    Args:
        text: 元のメッセージ本文

    Returns:
        クリーニング済みメッセージ
    """
    if not text:
        return ""

    cleaned = text.strip()

    # /command@botname 形式のコマンドプレフィックスを除去
    cleaned = re.sub(r"^/\w+(@\w+)?\s*", "", cleaned)

    # @botname メンションを除去
    bot_username = os.environ.get("TELEGRAM_BOT_USERNAME", "")
    if bot_username:
        cleaned = cleaned.replace(f"@{bot_username}", "").strip()

    return cleaned


def extract_telegram_update(update: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Telegram Updateオブジェクトからメッセージ情報を抽出する。

    対応するUpdate型:
    - message: 通常のメッセージ
    - edited_message: 編集されたメッセージ（無視）
    - channel_post: チャンネル投稿（無視）

    Args:
        update: Telegram Bot API Update object

    Returns:
        dict: {chat_id, user_id, username, first_name, text, message_id, is_topic, topic_id}
        None: 処理不要なUpdate
    """
    # 通常のメッセージのみ処理
    msg = update.get("message")
    if not msg:
        return None

    # テキストメッセージのみ対応（写真・動画等は将来対応）
    text = msg.get("text", "")
    if not text:
        return None

    chat = msg.get("chat", {})
    sender = msg.get("from", {})

    # トピック対応（Telegram supergroup の forum topic）
    is_topic = msg.get("is_topic_message", False)
    topic_id = msg.get("message_thread_id")

    return {
        "chat_id": str(chat.get("id", "")),
        "chat_type": chat.get("type", "private"),  # private, group, supergroup
        "user_id": str(sender.get("id", "")),
        "username": sender.get("username", ""),
        "first_name": sender.get("first_name", "ゲスト"),
        "last_name": sender.get("last_name", ""),
        "text": text,
        "message_id": str(msg.get("message_id", "")),
        "is_topic": is_topic,
        "topic_id": str(topic_id) if topic_id else "",
    }


# =============================================================================
# TelegramChannelAdapter
# =============================================================================


class TelegramChannelAdapter(ChannelAdapter):
    """
    Telegram Bot API用のチャネルアダプター

    社長専用窓口として、プライベートチャットとグループトピックに対応。
    send_message()はTelegram Bot API (sendMessage)を使用。
    """

    def __init__(self, bot_token: str = "", ceo_chat_id: str = ""):
        """
        Args:
            bot_token: Telegram Bot APIトークン
            ceo_chat_id: 社長のchat_id（権限チェック用）
        """
        self._bot_token = bot_token or TELEGRAM_BOT_TOKEN
        self._ceo_chat_id = ceo_chat_id or TELEGRAM_CEO_CHAT_ID
        self._api_base = f"{TELEGRAM_API_BASE}/bot{self._bot_token}"

    @property
    def platform_name(self) -> str:
        return "telegram"

    def parse_webhook(self, request_data: Dict[str, Any]) -> Optional[ChannelMessage]:
        """
        Telegram Webhook UpdateをChannelMessageに変換する。

        Args:
            request_data: Telegram Bot API Update object (JSON)

        Returns:
            ChannelMessage（正常時）、None（無効なリクエスト時）
        """
        extracted = extract_telegram_update(request_data)
        if not extracted:
            return None

        chat_id = extracted["chat_id"]
        user_id = extracted["user_id"]
        raw_text = extracted["text"]
        first_name = extracted["first_name"]
        last_name = extracted.get("last_name", "")
        sender_name = f"{first_name} {last_name}".strip() if last_name else first_name

        # メッセージのクリーニング
        cleaned_text = clean_telegram_message(raw_text)
        if not cleaned_text:
            return None

        # プライベートチャットは常にボット宛
        is_private = extracted["chat_type"] == "private"

        # グループ内メッセージの判定
        # /command でボットに話しかけた場合 or @botname でメンションした場合
        is_addressed = is_private or self.is_addressed_to_bot(raw_text)

        # CEO権限チェック（メタデータに含めて後段で判定）
        is_ceo = is_telegram_ceo(chat_id)

        # room_idの決定: トピックありならtopic_id、なければchat_id
        room_id = extracted["topic_id"] if extracted["is_topic"] else chat_id

        return ChannelMessage(
            platform="telegram",
            room_id=room_id,
            sender_id=user_id,
            sender_name=sender_name,
            body=cleaned_text,
            raw_body=raw_text,
            message_id=extracted["message_id"],
            is_bot_addressed=is_addressed,
            is_broadcast=False,  # Telegramにbroadcastの概念はない
            is_from_bot=False,  # Webhookでボット自身のメッセージは来ない
            event_type="message",
            metadata={
                "chat_id": chat_id,
                "chat_type": extracted["chat_type"],
                "is_private": is_private,
                "is_topic": extracted["is_topic"],
                "topic_id": extracted["topic_id"],
                "is_ceo": is_ceo,
                "username": extracted["username"],
            },
        )

    def send_message(
        self,
        room_id: str,
        message: str,
        reply_to: Optional[str] = None,
    ) -> SendResult:
        """
        Telegram Bot APIでメッセージを送信する。

        Args:
            room_id: chat_id（送信先）
            message: メッセージ本文（Markdown V2形式非対応、プレーンテキスト）
            reply_to: 返信先のmessage_id（省略可）

        Returns:
            SendResult
        """
        if not self._bot_token:
            return SendResult(success=False, error="TELEGRAM_BOT_TOKEN is not configured")

        try:
            url = f"{self._api_base}/sendMessage"
            payload: Dict[str, Any] = {
                "chat_id": room_id,
                "text": message,
            }
            if reply_to:
                payload["reply_to_message_id"] = int(reply_to)

            # 同期HTTPリクエスト（asyncio.to_threadで呼ばれる前提）
            with httpx.Client(timeout=30.0) as client:
                response = client.post(url, json=payload)

            if response.status_code == 200:
                result_data = response.json()
                msg_id = str(result_data.get("result", {}).get("message_id", ""))
                return SendResult(success=True, message_id=msg_id)

            logger.error(
                "Telegram sendMessage failed: status=%d body=%s",
                response.status_code,
                response.text[:200],
            )
            return SendResult(
                success=False,
                error=f"Telegram API error: {response.status_code}",
            )

        except Exception as e:
            logger.error("Telegram send_message error: %s", e, exc_info=True)
            return SendResult(success=False, error=str(e))

    def get_sender_name(self, room_id: str, sender_id: str) -> str:
        """
        送信者の表示名を取得する。

        Telegram Webhookにfirst_nameが含まれるため、
        通常はparse_webhook()で取得済み。
        このメソッドは後から名前を取得する必要がある場合のフォールバック。

        Args:
            room_id: chat_id
            sender_id: user_id

        Returns:
            表示名（取得失敗時は"ゲスト"）
        """
        if not self._bot_token:
            return "ゲスト"

        try:
            url = f"{self._api_base}/getChatMember"
            with httpx.Client(timeout=10.0) as client:
                response = client.post(url, json={
                    "chat_id": room_id,
                    "user_id": int(sender_id),
                })

            if response.status_code == 200:
                data = response.json()
                user = data.get("result", {}).get("user", {})
                first = user.get("first_name", "")
                last = user.get("last_name", "")
                return f"{first} {last}".strip() if last else (first or "ゲスト")

        except Exception as e:
            logger.warning("Telegram get_sender_name failed: %s", e)

        return "ゲスト"

    def clean_message(self, raw_body: str) -> str:
        """Telegramメッセージをクリーニング"""
        return clean_telegram_message(raw_body)

    def is_addressed_to_bot(self, raw_body: str) -> bool:
        """
        メッセージがボット宛かどうかを判定

        - /command で始まるメッセージ
        - @botname を含むメッセージ
        - プライベートチャットは常にTrue（parse_webhookで判定済み）
        """
        if not raw_body:
            return False

        # /command 形式
        if raw_body.startswith("/"):
            return True

        # @botname メンション
        bot_username = os.environ.get("TELEGRAM_BOT_USERNAME", "")
        if bot_username and f"@{bot_username}" in raw_body:
            return True

        return False
