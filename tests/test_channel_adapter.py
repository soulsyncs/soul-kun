# tests/test_channel_adapter.py
"""
チャネルアダプターのユニットテスト

Phase 2-A: チャネルアダプターパターン
- base.py: ChannelMessage, ChannelAdapter, SendResult
- chatwork_adapter.py: ChatworkChannelAdapter, ユーティリティ関数
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timezone

from lib.channels.base import ChannelMessage, ChannelAdapter, SendResult
from lib.channels.chatwork_adapter import (
    ChatworkChannelAdapter,
    clean_chatwork_message,
    is_mention_to_bot,
    is_toall_mention,
    is_bot_reply_loop,
    SOULKUN_ACCOUNT_ID,
)


# =============================================================================
# フィクスチャ
# =============================================================================


@pytest.fixture
def mock_client():
    """ChatworkClientのモック"""
    return Mock()


@pytest.fixture
def adapter(mock_client):
    """ChatworkChannelAdapterインスタンス"""
    return ChatworkChannelAdapter(chatwork_client=mock_client)


def make_webhook_data(
    body="[To:10909425]ソウルくん\nこんにちは",
    room_id=12345,
    message_id="msg001",
    from_account_id=67890,
    event_type="mention_to_me",
):
    """テスト用Webhookデータ生成ヘルパー"""
    event = {
        "room_id": room_id,
        "body": body,
        "message_id": message_id,
    }
    if event_type == "mention_to_me":
        event["from_account_id"] = from_account_id
    else:
        event["account_id"] = from_account_id
    return {
        "webhook_event_type": event_type,
        "webhook_event": event,
    }


# =============================================================================
# clean_chatwork_message テスト
# =============================================================================


class TestCleanChatworkMessage:
    """ChatWorkメッセージクリーニングのテスト"""

    def test_remove_to_tag(self):
        """[To:XXXXX]タグの除去"""
        result = clean_chatwork_message("[To:10909425]ソウルくん\nこんにちは")
        assert "[To:" not in result
        assert "こんにちは" in result

    def test_remove_rp_tag(self):
        """[rp aid=XXXXX][/rp]タグの除去"""
        result = clean_chatwork_message("[rp aid=10909425 to=123][/rp]質問です")
        assert "[rp" not in result
        assert "質問です" in result

    def test_remove_info_tag(self):
        """[info][/info]タグの除去"""
        result = clean_chatwork_message("[info]メモです[/info]")
        assert "[info]" not in result
        assert "メモです" in result

    def test_remove_code_tag(self):
        """[code][/code]タグの除去"""
        result = clean_chatwork_message("[code]print('hello')[/code]")
        assert "[code]" not in result

    def test_normalize_whitespace(self):
        """連続空白の正規化"""
        result = clean_chatwork_message("  hello   world  ")
        assert result == "hello world"

    def test_none_input(self):
        """None入力"""
        result = clean_chatwork_message(None)
        assert result == ""

    def test_empty_string(self):
        """空文字列"""
        result = clean_chatwork_message("")
        assert result == ""

    def test_non_string_input(self):
        """非文字列入力"""
        result = clean_chatwork_message(12345)
        assert result == "12345"

    def test_plain_text_unchanged(self):
        """タグなしテキストはそのまま"""
        result = clean_chatwork_message("タスク追加して")
        assert result == "タスク追加して"

    def test_complex_message(self):
        """複合タグメッセージ"""
        body = "[To:10909425]ソウルくん\n[info]田中さんの件[/info]\nよろしく"
        result = clean_chatwork_message(body)
        assert "[To:" not in result
        assert "[info]" not in result
        assert "田中さんの件" in result
        assert "よろしく" in result


# =============================================================================
# is_mention_to_bot テスト
# =============================================================================


class TestIsMentionToBot:
    """ボット宛メンション判定のテスト"""

    def test_direct_mention(self):
        """直接メンション"""
        assert is_mention_to_bot("[To:10909425]ソウルくん こんにちは") is True

    def test_reply_button(self):
        """返信ボタン"""
        assert is_mention_to_bot("[rp aid=10909425 to=123]質問です") is True

    def test_no_mention(self):
        """メンションなし"""
        assert is_mention_to_bot("普通のメッセージです") is False

    def test_other_user_mention(self):
        """他ユーザーへのメンション"""
        assert is_mention_to_bot("[To:99999]田中さん") is False

    def test_none_input(self):
        """None入力"""
        assert is_mention_to_bot(None) is False

    def test_empty_input(self):
        """空文字列"""
        assert is_mention_to_bot("") is False

    def test_custom_bot_id(self):
        """カスタムボットID"""
        assert is_mention_to_bot("[To:12345]bot", bot_account_id="12345") is True
        assert is_mention_to_bot("[To:12345]bot", bot_account_id="99999") is False


# =============================================================================
# is_toall_mention テスト
# =============================================================================


class TestIsToallMention:
    """オールメンション判定のテスト"""

    def test_toall_present(self):
        """[toall]あり"""
        assert is_toall_mention("[toall]お知らせです") is True

    def test_toall_uppercase(self):
        """大文字[TOALL]"""
        assert is_toall_mention("[TOALL]アナウンス") is True

    def test_no_toall(self):
        """[toall]なし"""
        assert is_toall_mention("[To:10909425]こんにちは") is False

    def test_none_input(self):
        """None入力"""
        assert is_toall_mention(None) is False


# =============================================================================
# is_bot_reply_loop テスト
# =============================================================================


class TestIsBotReplyLoop:
    """ボット返信ループ検出のテスト"""

    def test_loop_pattern(self):
        """ウル + 返信タグ = ループ"""
        assert is_bot_reply_loop("了解ウル[rp aid=67890]") is True

    def test_no_uru(self):
        """ウルなし"""
        assert is_bot_reply_loop("[rp aid=67890]質問です") is False

    def test_no_rp_tag(self):
        """返信タグなし"""
        assert is_bot_reply_loop("了解ウル") is False

    def test_none_input(self):
        """None入力"""
        assert is_bot_reply_loop(None) is False


# =============================================================================
# ChannelMessage テスト
# =============================================================================


class TestChannelMessage:
    """ChannelMessageデータクラスのテスト"""

    def test_should_process_normal(self):
        """通常メッセージは処理すべき"""
        msg = ChannelMessage(
            platform="chatwork", room_id="123", sender_id="456",
            sender_name="田中", body="こんにちは", raw_body="[To:10909425]こんにちは",
            is_bot_addressed=True,
        )
        assert msg.should_process is True

    def test_should_not_process_from_bot(self):
        """ボット自身のメッセージは処理しない"""
        msg = ChannelMessage(
            platform="chatwork", room_id="123", sender_id="456",
            sender_name="bot", body="返答", raw_body="返答",
            is_from_bot=True, is_bot_addressed=True,
        )
        assert msg.should_process is False
        assert msg.skip_reason == "own_message"

    def test_should_not_process_broadcast(self):
        """ブロードキャストは処理しない"""
        msg = ChannelMessage(
            platform="chatwork", room_id="123", sender_id="456",
            sender_name="田中", body="お知らせ", raw_body="[toall]お知らせ",
            is_broadcast=True, is_bot_addressed=True,
        )
        assert msg.should_process is False
        assert msg.skip_reason == "broadcast"

    def test_should_not_process_not_addressed(self):
        """ボット宛でないメッセージは処理しない"""
        msg = ChannelMessage(
            platform="chatwork", room_id="123", sender_id="456",
            sender_name="田中", body="雑談", raw_body="雑談",
            is_bot_addressed=False,
        )
        assert msg.should_process is False
        assert msg.skip_reason == "not_addressed"

    def test_should_not_process_empty_body(self):
        """空のメッセージは処理しない"""
        msg = ChannelMessage(
            platform="chatwork", room_id="123", sender_id="456",
            sender_name="田中", body="", raw_body="[To:10909425]",
            is_bot_addressed=True,
        )
        assert msg.should_process is False
        assert msg.skip_reason == "empty_message"

    def test_skip_reason_empty_when_processable(self):
        """処理可能なメッセージのskip_reasonは空"""
        msg = ChannelMessage(
            platform="chatwork", room_id="123", sender_id="456",
            sender_name="田中", body="質問", raw_body="[To:10909425]質問",
            is_bot_addressed=True,
        )
        assert msg.skip_reason == ""


# =============================================================================
# SendResult テスト
# =============================================================================


class TestSendResult:
    """SendResultデータクラスのテスト"""

    def test_success(self):
        """成功結果"""
        r = SendResult(success=True, message_id="msg001")
        assert r.success is True
        assert r.message_id == "msg001"

    def test_failure(self):
        """失敗結果"""
        r = SendResult(success=False, error="API error")
        assert r.success is False
        assert r.error == "API error"


# =============================================================================
# ChatworkChannelAdapter.parse_webhook テスト
# =============================================================================


class TestParseWebhook:
    """Webhookパースのテスト"""

    def test_mention_event(self, adapter):
        """mention_to_meイベント"""
        data = make_webhook_data()
        msg = adapter.parse_webhook(data)
        assert msg is not None
        assert msg.platform == "chatwork"
        assert msg.room_id == "12345"
        assert msg.sender_id == "67890"
        assert msg.message_id == "msg001"
        assert msg.is_bot_addressed is True
        assert msg.event_type == "mention_to_me"
        assert "こんにちは" in msg.body

    def test_non_mention_event_with_to_tag(self, adapter):
        """mention_to_me以外でも[To:]タグがあればbot宛"""
        data = make_webhook_data(
            body="[To:10909425]ソウルくん 質問",
            event_type="message_created",
        )
        msg = adapter.parse_webhook(data)
        assert msg is not None
        assert msg.is_bot_addressed is True

    def test_non_mention_event_without_to_tag(self, adapter):
        """mention_to_me以外で[To:]タグもなければbot宛でない"""
        data = make_webhook_data(
            body="普通のメッセージ",
            event_type="message_created",
        )
        msg = adapter.parse_webhook(data)
        assert msg is not None
        assert msg.is_bot_addressed is False

    def test_toall_sets_broadcast(self, adapter):
        """[toall]のみ（直接メンションなし）はbroadcastフラグが立つ"""
        data = make_webhook_data(
            body="[toall]お知らせ",
            event_type="message_created",  # mention_to_meではない
        )
        msg = adapter.parse_webhook(data)
        assert msg.is_broadcast is True
        assert msg.should_process is False

    def test_own_message_sets_from_bot(self, adapter):
        """自分自身のメッセージはis_from_botフラグが立つ"""
        data = make_webhook_data(from_account_id=int(SOULKUN_ACCOUNT_ID))
        msg = adapter.parse_webhook(data)
        assert msg.is_from_bot is True
        assert msg.should_process is False

    def test_bot_reply_loop_sets_broadcast(self, adapter):
        """ボット返信ループパターンはbroadcastで処理スキップ"""
        data = make_webhook_data(body="了解ウル[rp aid=67890]")
        msg = adapter.parse_webhook(data)
        assert msg.is_broadcast is True

    def test_empty_request_returns_none(self, adapter):
        """空リクエストはNone"""
        assert adapter.parse_webhook(None) is None
        assert adapter.parse_webhook({}) is None

    def test_no_webhook_event_returns_none(self, adapter):
        """webhook_eventがないリクエストはNone"""
        assert adapter.parse_webhook({"other": "data"}) is None

    def test_empty_body_message(self, adapter):
        """空のメッセージ本文"""
        data = make_webhook_data(body="[To:10909425]")
        msg = adapter.parse_webhook(data)
        assert msg is not None
        # body is cleaned (may be empty after tag removal)
        assert msg.body == "" or msg.body.strip() == ""

    def test_toall_with_direct_mention_should_process(self, adapter):
        """[toall] + 直接メンションは処理すべき（CRITICAL-1修正）"""
        data = make_webhook_data(body="[toall][To:10909425]ソウルくん\n質問です")
        msg = adapter.parse_webhook(data)
        assert msg.is_broadcast is False  # toallだが直接メンションあり
        assert msg.is_bot_addressed is True
        assert msg.should_process is True

    def test_metadata_no_raw_body(self, adapter):
        """metadataに生のbodyが含まれないこと（CRITICAL-2修正）"""
        data = make_webhook_data()
        msg = adapter.parse_webhook(data)
        assert "webhook_event" not in msg.metadata
        assert "body" not in msg.metadata
        assert "room_id" in msg.metadata
        assert "message_id" in msg.metadata


# =============================================================================
# ChatworkChannelAdapter.send_message テスト
# =============================================================================


class TestSendMessage:
    """メッセージ送信のテスト"""

    def test_send_success(self, adapter, mock_client):
        """送信成功"""
        mock_client.send_message.return_value = "msg_id_123"
        result = adapter.send_message("12345", "こんにちは")
        assert result.success is True
        mock_client.send_message.assert_called_once_with(
            room_id=12345, message="こんにちは", reply_to=None,
        )

    def test_send_failure(self, adapter, mock_client):
        """送信失敗"""
        mock_client.send_message.side_effect = Exception("API error")
        result = adapter.send_message("12345", "こんにちは")
        assert result.success is False
        assert "API error" in result.error

    def test_send_with_reply_to(self, adapter, mock_client):
        """reply_toパラメータがChatworkClientに渡される"""
        mock_client.send_message.return_value = "msg_id"
        result = adapter.send_message("12345", "返答", reply_to="67890")
        assert result.success is True
        mock_client.send_message.assert_called_once_with(
            room_id=12345, message="返答", reply_to=67890,
        )

    def test_send_invalid_room_id(self, adapter, mock_client):
        """無効なroom_idは送信失敗（HIGH-3修正）"""
        result = adapter.send_message("abc", "こんにちは")
        assert result.success is False
        assert "Invalid room_id" in result.error
        mock_client.send_message.assert_not_called()


# =============================================================================
# ChatworkChannelAdapter.get_sender_name テスト
# =============================================================================


class TestGetSenderName:
    """送信者名取得のテスト"""

    def test_found(self, adapter, mock_client):
        """送信者が見つかった場合"""
        mock_client.get_room_members.return_value = [
            {"account_id": 67890, "name": "田中太郎"},
            {"account_id": 11111, "name": "山田花子"},
        ]
        name = adapter.get_sender_name("12345", "67890")
        assert name == "田中太郎"

    def test_not_found(self, adapter, mock_client):
        """送信者が見つからない場合"""
        mock_client.get_room_members.return_value = [
            {"account_id": 11111, "name": "山田花子"},
        ]
        name = adapter.get_sender_name("12345", "99999")
        assert name == "ゲスト"

    def test_api_error(self, adapter, mock_client):
        """APIエラー時はゲスト"""
        mock_client.get_room_members.side_effect = Exception("API error")
        name = adapter.get_sender_name("12345", "67890")
        assert name == "ゲスト"

    def test_invalid_room_id(self, adapter, mock_client):
        """無効なroom_idはゲスト（HIGH-3修正）"""
        name = adapter.get_sender_name("abc", "67890")
        assert name == "ゲスト"
        mock_client.get_room_members.assert_not_called()


# =============================================================================
# ChatworkChannelAdapter プロパティ テスト
# =============================================================================


class TestAdapterProperties:
    """アダプタープロパティのテスト"""

    def test_platform_name(self, adapter):
        """プラットフォーム名"""
        assert adapter.platform_name == "chatwork"

    def test_lazy_client_initialization(self):
        """クライアントの遅延初期化"""
        adapter = ChatworkChannelAdapter(chatwork_client=None)
        # _clientはNone
        assert adapter._client is None
        # _get_client()を呼ぶとインポートされる（テスト環境では依存があるのでモック化）
        with patch("lib.chatwork.ChatworkClient") as mock_cls:
            mock_cls.return_value = Mock()
            client = adapter._get_client()
            assert client is not None
            mock_cls.assert_called_once()
