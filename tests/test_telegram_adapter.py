"""
TelegramChannelAdapter テスト — Step B-1

Telegramアダプターの主要機能をテスト:
- Webhook署名検証
- CEO権限チェック
- メッセージ解析（プライベートチャット、グループ、トピック）
- メッセージクリーニング
- ボット宛判定
"""

import os
import pytest
from unittest.mock import patch, MagicMock

from lib.channels.telegram_adapter import (
    TelegramChannelAdapter,
    verify_telegram_webhook,
    is_telegram_ceo,
    clean_telegram_message,
    extract_telegram_update,
)


# =============================================================================
# Webhook署名検証
# =============================================================================


class TestVerifyTelegramWebhook:
    """Telegram Webhook署名検証のテスト"""

    def test_valid_token(self):
        """正しいシークレットトークンで検証成功"""
        assert verify_telegram_webhook(b"body", "my-secret", "my-secret") is True

    def test_invalid_token(self):
        """不正なトークンで検証失敗"""
        assert verify_telegram_webhook(b"body", "my-secret", "wrong-token") is False

    def test_empty_secret(self):
        """シークレット未設定で検証失敗"""
        assert verify_telegram_webhook(b"body", "", "any-token") is False

    def test_empty_received(self):
        """受信トークン未設定で検証失敗"""
        assert verify_telegram_webhook(b"body", "my-secret", "") is False


# =============================================================================
# CEO権限チェック
# =============================================================================


class TestIsTelegramCeo:
    """CEO権限チェックのテスト"""

    @patch.dict(os.environ, {"TELEGRAM_CEO_CHAT_ID": "123456"})
    def test_ceo_chat_id_matches(self):
        """CEOのchat_idが一致"""
        assert is_telegram_ceo("123456") is True

    @patch.dict(os.environ, {"TELEGRAM_CEO_CHAT_ID": "123456"})
    def test_non_ceo_chat_id(self):
        """CEO以外のchat_id"""
        assert is_telegram_ceo("999999") is False

    @patch.dict(os.environ, {"TELEGRAM_CEO_CHAT_ID": ""})
    def test_ceo_id_not_set(self):
        """CEO IDが未設定の場合は全拒否"""
        assert is_telegram_ceo("123456") is False


# =============================================================================
# メッセージクリーニング
# =============================================================================


class TestCleanTelegramMessage:
    """Telegramメッセージクリーニングのテスト"""

    def test_plain_text(self):
        """通常テキストはそのまま"""
        assert clean_telegram_message("こんにちは") == "こんにちは"

    def test_empty_text(self):
        """空文字列"""
        assert clean_telegram_message("") == ""

    def test_none_text(self):
        """None"""
        assert clean_telegram_message(None) == ""

    def test_command_removal(self):
        """コマンドプレフィックスの除去"""
        assert clean_telegram_message("/start") == ""
        assert clean_telegram_message("/help") == ""

    def test_command_with_text(self):
        """コマンド+テキスト"""
        assert clean_telegram_message("/ask 明日の予定は？") == "明日の予定は？"

    def test_command_with_botname(self):
        """コマンド+ボット名"""
        assert clean_telegram_message("/ask@soulkun_bot 明日は？") == "明日は？"

    @patch.dict(os.environ, {"TELEGRAM_BOT_USERNAME": "soulkun_bot"})
    def test_botname_mention_removal(self):
        """@ボット名メンションの除去"""
        assert clean_telegram_message("@soulkun_bot 調べて") == "調べて"

    def test_whitespace_trimming(self):
        """前後の空白トリミング"""
        assert clean_telegram_message("  テスト  ") == "テスト"


# =============================================================================
# Telegram Update 解析
# =============================================================================


class TestExtractTelegramUpdate:
    """Telegram Update解析のテスト"""

    def test_normal_message(self):
        """通常のプライベートメッセージ"""
        update = {
            "message": {
                "message_id": 42,
                "from": {"id": 111, "first_name": "カズ", "username": "kazu"},
                "chat": {"id": 111, "type": "private"},
                "text": "明日の予定は？",
            }
        }
        result = extract_telegram_update(update)
        assert result is not None
        assert result["chat_id"] == "111"
        assert result["chat_type"] == "private"
        assert result["user_id"] == "111"
        assert result["first_name"] == "カズ"
        assert result["text"] == "明日の予定は？"
        assert result["message_id"] == "42"
        assert result["is_topic"] is False

    def test_group_message_with_topic(self):
        """グループのトピック内メッセージ"""
        update = {
            "message": {
                "message_id": 100,
                "from": {"id": 111, "first_name": "カズ"},
                "chat": {"id": -1001234567890, "type": "supergroup"},
                "text": "経営会議の議題を整理して",
                "is_topic_message": True,
                "message_thread_id": 999,
            }
        }
        result = extract_telegram_update(update)
        assert result is not None
        assert result["is_topic"] is True
        assert result["topic_id"] == "999"
        assert result["chat_type"] == "supergroup"

    def test_no_message(self):
        """メッセージなしのUpdate（callback_query等）"""
        update = {"callback_query": {"id": "123"}}
        result = extract_telegram_update(update)
        assert result is None

    def test_no_text(self):
        """テキストなし（写真メッセージ等）"""
        update = {
            "message": {
                "message_id": 50,
                "from": {"id": 111, "first_name": "カズ"},
                "chat": {"id": 111, "type": "private"},
                "photo": [{"file_id": "xxx"}],
            }
        }
        result = extract_telegram_update(update)
        assert result is None

    def test_edited_message_ignored(self):
        """編集メッセージは無視"""
        update = {
            "edited_message": {
                "message_id": 42,
                "from": {"id": 111, "first_name": "カズ"},
                "chat": {"id": 111, "type": "private"},
                "text": "修正後テキスト",
            }
        }
        result = extract_telegram_update(update)
        assert result is None


# =============================================================================
# TelegramChannelAdapter
# =============================================================================


class TestTelegramChannelAdapterPlatform:
    """プラットフォーム名テスト"""

    def test_platform_name(self):
        adapter = TelegramChannelAdapter(bot_token="test", ceo_chat_id="123")
        assert adapter.platform_name == "telegram"


class TestTelegramChannelAdapterParseWebhook:
    """parse_webhook テスト"""

    @patch.dict(os.environ, {"TELEGRAM_CEO_CHAT_ID": "111"})
    def test_parse_private_message(self):
        """プライベートメッセージの解析"""
        adapter = TelegramChannelAdapter(bot_token="test", ceo_chat_id="111")
        update = {
            "message": {
                "message_id": 42,
                "from": {"id": 111, "first_name": "カズ", "last_name": "菊地"},
                "chat": {"id": 111, "type": "private"},
                "text": "明日の予定は？",
            }
        }
        msg = adapter.parse_webhook(update)
        assert msg is not None
        assert msg.platform == "telegram"
        assert msg.sender_name == "カズ 菊地"
        assert msg.body == "明日の予定は？"
        assert msg.is_bot_addressed is True  # プライベートは常にTrue
        assert msg.metadata["is_ceo"] is True
        assert msg.metadata["is_private"] is True

    @patch.dict(os.environ, {"TELEGRAM_CEO_CHAT_ID": "999"})
    def test_parse_non_ceo_message(self):
        """CEO以外のメッセージ"""
        adapter = TelegramChannelAdapter(bot_token="test", ceo_chat_id="999")
        update = {
            "message": {
                "message_id": 42,
                "from": {"id": 111, "first_name": "他の人"},
                "chat": {"id": 111, "type": "private"},
                "text": "こんにちは",
            }
        }
        msg = adapter.parse_webhook(update)
        assert msg is not None
        assert msg.metadata["is_ceo"] is False

    def test_parse_invalid_update(self):
        """無効なUpdate"""
        adapter = TelegramChannelAdapter(bot_token="test")
        assert adapter.parse_webhook({}) is None
        assert adapter.parse_webhook({"callback_query": {}}) is None

    def test_parse_command_cleaned(self):
        """コマンドメッセージがクリーニングされる"""
        adapter = TelegramChannelAdapter(bot_token="test")
        update = {
            "message": {
                "message_id": 42,
                "from": {"id": 111, "first_name": "カズ"},
                "chat": {"id": 111, "type": "private"},
                "text": "/ask 明日の予定教えて",
            }
        }
        msg = adapter.parse_webhook(update)
        assert msg is not None
        assert msg.body == "明日の予定教えて"

    @patch.dict(os.environ, {"TELEGRAM_CEO_CHAT_ID": "111"})
    def test_parse_topic_message(self):
        """トピック付きメッセージ"""
        adapter = TelegramChannelAdapter(bot_token="test", ceo_chat_id="111")
        update = {
            "message": {
                "message_id": 100,
                "from": {"id": 111, "first_name": "カズ"},
                "chat": {"id": -1001234567890, "type": "supergroup"},
                "text": "経営会議の議題は？",
                "is_topic_message": True,
                "message_thread_id": 55,
            }
        }
        msg = adapter.parse_webhook(update)
        assert msg is not None
        assert msg.room_id == "55"  # topic_idがroom_idになる
        assert msg.metadata["is_topic"] is True
        assert msg.metadata["topic_id"] == "55"


class TestTelegramChannelAdapterSendMessage:
    """send_message テスト"""

    def test_send_without_token(self):
        """トークン未設定で送信失敗"""
        adapter = TelegramChannelAdapter(bot_token="")
        result = adapter.send_message("123", "テスト")
        assert result.success is False
        assert "not configured" in result.error

    @patch("lib.channels.telegram_adapter.httpx.Client")
    def test_send_success(self, mock_client_cls):
        """正常送信"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": {"message_id": 42}}
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        adapter = TelegramChannelAdapter(bot_token="test-token")
        result = adapter.send_message("123", "テストメッセージ")
        assert result.success is True
        assert result.message_id == "42"

    @patch("lib.channels.telegram_adapter.httpx.Client")
    def test_send_api_error(self, mock_client_cls):
        """API エラー"""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        adapter = TelegramChannelAdapter(bot_token="test-token")
        result = adapter.send_message("123", "テスト")
        assert result.success is False


class TestTelegramChannelAdapterIsAddressed:
    """ボット宛判定テスト"""

    def test_command_addressed(self):
        """コマンドはボット宛"""
        adapter = TelegramChannelAdapter(bot_token="test")
        assert adapter.is_addressed_to_bot("/ask 質問") is True

    def test_plain_text_not_addressed(self):
        """普通のテキストはボット宛ではない"""
        adapter = TelegramChannelAdapter(bot_token="test")
        assert adapter.is_addressed_to_bot("普通の会話") is False

    @patch.dict(os.environ, {"TELEGRAM_BOT_USERNAME": "soulkun_bot"})
    def test_mention_addressed(self):
        """@メンションはボット宛"""
        adapter = TelegramChannelAdapter(bot_token="test")
        assert adapter.is_addressed_to_bot("@soulkun_bot 明日の予定") is True

    def test_empty_not_addressed(self):
        """空文字列はボット宛ではない"""
        adapter = TelegramChannelAdapter(bot_token="test")
        assert adapter.is_addressed_to_bot("") is False
