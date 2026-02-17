"""
ChatWorkChannelAdapter テスト

ChatWorkアダプターのファイル検出・メッセージ解析をテスト。
"""

import os
import pytest
from unittest.mock import patch, MagicMock

from lib.channels.chatwork_adapter import (
    ChatworkChannelAdapter,
    clean_chatwork_message,
    is_mention_to_bot,
    is_toall_mention,
    is_bot_reply_loop,
    extract_chatwork_files,
)


# =============================================================================
# ファイル抽出テスト
# =============================================================================


class TestExtractChatworkFiles:
    """extract_chatwork_files のテスト"""

    def test_single_file(self):
        """1つのファイル添付を検出"""
        body = "[To:10909425]ソウルくん\nこの資料を見てください\n[download:123456]"
        result = extract_chatwork_files(body)
        assert len(result) == 1
        assert result[0]["file_id"] == "123456"

    def test_multiple_files(self):
        """複数ファイル添付を検出"""
        body = "[To:10909425]ソウルくん\n資料2点です\n[download:111][download:222]"
        result = extract_chatwork_files(body)
        assert len(result) == 2
        assert result[0]["file_id"] == "111"
        assert result[1]["file_id"] == "222"

    def test_no_files(self):
        """ファイルなし"""
        body = "[To:10909425]ソウルくん\nこんにちは"
        result = extract_chatwork_files(body)
        assert result == []

    def test_empty_body(self):
        """空メッセージ"""
        assert extract_chatwork_files("") == []
        assert extract_chatwork_files(None) == []

    def test_file_with_text(self):
        """テキスト中にdownloadタグが埋まっている場合"""
        body = "添付ファイル: [download:999] を確認ウル"
        result = extract_chatwork_files(body)
        assert len(result) == 1
        assert result[0]["file_id"] == "999"


# =============================================================================
# parse_webhook ファイル対応テスト
# =============================================================================


class TestChatworkAdapterParseWebhookFiles:
    """parse_webhook のファイル対応テスト"""

    def test_message_with_file(self):
        """ファイル付きメッセージがプレースホルダー付きで解析される"""
        adapter = ChatworkChannelAdapter(bot_account_id="10909425")
        data = {
            "webhook_event_type": "mention_to_me",
            "webhook_event": {
                "room_id": 12345,
                "body": "[To:10909425]ソウルくん\nこの資料見て\n[download:888]",
                "message_id": "msg001",
                "from_account_id": 67890,
            },
        }
        msg = adapter.parse_webhook(data)
        assert msg is not None
        assert "[ファイルを送信]" in msg.body
        assert "この資料見て" in msg.body
        assert msg.metadata["files"] == [{"file_id": "888"}]

    def test_message_with_multiple_files(self):
        """複数ファイル付きメッセージ"""
        adapter = ChatworkChannelAdapter(bot_account_id="10909425")
        data = {
            "webhook_event_type": "mention_to_me",
            "webhook_event": {
                "room_id": 12345,
                "body": "[To:10909425]ソウルくん\n資料です\n[download:111][download:222]",
                "message_id": "msg002",
                "from_account_id": 67890,
            },
        }
        msg = adapter.parse_webhook(data)
        assert msg is not None
        assert "[ファイル2件を送信]" in msg.body
        assert len(msg.metadata["files"]) == 2

    def test_message_without_file(self):
        """ファイルなしメッセージはプレースホルダーなし"""
        adapter = ChatworkChannelAdapter(bot_account_id="10909425")
        data = {
            "webhook_event_type": "mention_to_me",
            "webhook_event": {
                "room_id": 12345,
                "body": "[To:10909425]ソウルくん\nこんにちは",
                "message_id": "msg003",
                "from_account_id": 67890,
            },
        }
        msg = adapter.parse_webhook(data)
        assert msg is not None
        assert "[ファイル" not in msg.body
        assert msg.metadata["files"] == []

    def test_file_only_message(self):
        """テキストなし、ファイルのみ（メンション+ファイル）"""
        adapter = ChatworkChannelAdapter(bot_account_id="10909425")
        data = {
            "webhook_event_type": "mention_to_me",
            "webhook_event": {
                "room_id": 12345,
                "body": "[To:10909425]\n[download:555]",
                "message_id": "msg004",
                "from_account_id": 67890,
            },
        }
        msg = adapter.parse_webhook(data)
        assert msg is not None
        assert msg.body == "[ファイルを送信]"
        assert msg.metadata["files"] == [{"file_id": "555"}]

    def test_multiple_files_no_text(self):
        """テキストなし、複数ファイルのみ"""
        adapter = ChatworkChannelAdapter(bot_account_id="10909425")
        data = {
            "webhook_event_type": "mention_to_me",
            "webhook_event": {
                "room_id": 12345,
                "body": "[To:10909425]\n[download:111][download:222][download:333]",
                "message_id": "msg005",
                "from_account_id": 67890,
            },
        }
        msg = adapter.parse_webhook(data)
        assert msg is not None
        assert msg.body == "[ファイル3件を送信]"
        assert len(msg.metadata["files"]) == 3


# =============================================================================
# 既存機能のテスト（回帰テスト）
# =============================================================================


class TestCleanChatworkMessage:
    """メッセージクリーニングの回帰テスト"""

    def test_mention_removal(self):
        """メンションタグの除去"""
        body = "[To:10909425]ソウルくん\nこんにちは"
        result = clean_chatwork_message(body)
        assert "10909425" not in result
        assert "こんにちは" in result

    def test_empty(self):
        assert clean_chatwork_message("") == ""
        assert clean_chatwork_message(None) == ""

    def test_download_tag_removed(self):
        """[download:XXX]タグはクリーニングで除去される"""
        body = "資料です [download:123]"
        result = clean_chatwork_message(body)
        assert "download" not in result
        assert "資料です" in result


class TestIsMentionToBot:
    """ボット宛判定の回帰テスト"""

    def test_direct_mention(self):
        assert is_mention_to_bot("[To:10909425]ソウルくん テスト") is True

    def test_reply(self):
        assert is_mention_to_bot("[rp aid=10909425 to=12345-msg1]") is True

    def test_not_mentioned(self):
        assert is_mention_to_bot("普通のメッセージ") is False


class TestChatworkAdapterBasics:
    """アダプター基本テスト"""

    def test_platform_name(self):
        adapter = ChatworkChannelAdapter()
        assert adapter.platform_name == "chatwork"

    def test_parse_invalid_data(self):
        adapter = ChatworkChannelAdapter()
        assert adapter.parse_webhook({}) is None
        assert adapter.parse_webhook(None) is None

    def test_parse_mention_event(self):
        """mention_to_meイベントの解析"""
        adapter = ChatworkChannelAdapter(bot_account_id="10909425")
        data = {
            "webhook_event_type": "mention_to_me",
            "webhook_event": {
                "room_id": 12345,
                "body": "[To:10909425]ソウルくん\n明日の予定は？",
                "message_id": "msg100",
                "from_account_id": 67890,
            },
        }
        msg = adapter.parse_webhook(data)
        assert msg is not None
        assert msg.platform == "chatwork"
        assert msg.room_id == "12345"
        assert msg.sender_id == "67890"
        assert msg.is_bot_addressed is True
        assert "明日の予定" in msg.body
