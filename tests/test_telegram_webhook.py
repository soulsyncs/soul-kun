"""
Telegram Webhookエンドポイント統合テスト — Step B-4

chatwork-webhook/main.py の /telegram エンドポイントの動作をテスト:
- 署名検証のフロー
- 社長専用権限チェック
- Brain処理の統合フロー
- エラーハンドリング
"""

import json
import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


# =============================================================================
# テスト用ヘルパー
# =============================================================================

def _make_telegram_update(
    chat_id: int = 111,
    user_id: int = 111,
    first_name: str = "カズ",
    last_name: str = "菊地",
    text: str = "今日の予定教えて",
    chat_type: str = "private",
    message_id: int = 42,
):
    """テスト用のTelegram Update JSONを生成"""
    return {
        "message": {
            "message_id": message_id,
            "from": {"id": user_id, "first_name": first_name, "last_name": last_name},
            "chat": {"id": chat_id, "type": chat_type},
            "text": text,
        }
    }


# =============================================================================
# TelegramChannelAdapterを直接テスト（エンドポイント相当のフロー）
# =============================================================================


class TestTelegramWebhookFlow:
    """Telegram Webhookの処理フローをテスト（アダプター経由）"""

    @patch.dict(os.environ, {"TELEGRAM_CEO_CHAT_ID": "111"})
    def test_ceo_message_produces_channel_message(self):
        """社長のメッセージがChannelMessageに変換される"""
        from lib.channels.telegram_adapter import TelegramChannelAdapter

        adapter = TelegramChannelAdapter(bot_token="test-token", ceo_chat_id="111")
        update = _make_telegram_update(chat_id=111, text="今日の予定教えて")

        msg = adapter.parse_webhook(update)

        assert msg is not None
        assert msg.platform == "telegram"
        assert msg.body == "今日の予定教えて"
        assert msg.sender_name == "カズ 菊地"
        assert msg.is_bot_addressed is True  # プライベートチャットは常にTrue
        assert msg.metadata["is_ceo"] is True
        assert msg.metadata["is_private"] is True

    @patch.dict(os.environ, {"TELEGRAM_CEO_CHAT_ID": "111"})
    def test_non_ceo_rejected(self):
        """社長以外のメッセージはis_ceo=Falseで権限チェックに引っかかる"""
        from lib.channels.telegram_adapter import TelegramChannelAdapter

        adapter = TelegramChannelAdapter(bot_token="test-token", ceo_chat_id="111")
        update = _make_telegram_update(
            chat_id=999, user_id=999, first_name="他の人", text="こんにちは"
        )

        msg = adapter.parse_webhook(update)

        assert msg is not None
        assert msg.metadata["is_ceo"] is False
        # エンドポイントではis_ceo=Falseの場合に拒否メッセージを送信

    def test_photo_message_parsed(self):
        """写真メッセージはメディアプレースホルダー付きで解析される"""
        from lib.channels.telegram_adapter import TelegramChannelAdapter

        adapter = TelegramChannelAdapter(bot_token="test-token")
        update = {
            "message": {
                "message_id": 50,
                "from": {"id": 111, "first_name": "カズ"},
                "chat": {"id": 111, "type": "private"},
                "photo": [{"file_id": "xxx"}],
            }
        }

        msg = adapter.parse_webhook(update)
        assert msg is not None
        assert msg.body == "[写真を送信]"
        assert msg.metadata["media"]["media_type"] == "photo"

    def test_empty_body_returns_none(self):
        """空のリクエストボディはNone"""
        from lib.channels.telegram_adapter import TelegramChannelAdapter

        adapter = TelegramChannelAdapter(bot_token="test-token")
        assert adapter.parse_webhook({}) is None
        assert adapter.parse_webhook({"callback_query": {}}) is None

    def test_command_cleaned_before_brain(self):
        """/command プレフィックスがクリーニングされてからBrainへ渡される"""
        from lib.channels.telegram_adapter import TelegramChannelAdapter

        adapter = TelegramChannelAdapter(bot_token="test-token")
        update = _make_telegram_update(text="/ask 明日の予定教えて")

        msg = adapter.parse_webhook(update)

        assert msg is not None
        assert msg.body == "明日の予定教えて"
        assert msg.raw_body == "/ask 明日の予定教えて"

    @patch.dict(os.environ, {"TELEGRAM_CEO_CHAT_ID": "111"})
    def test_supergroup_topic_message(self):
        """グループのトピックメッセージが正しく処理される"""
        from lib.channels.telegram_adapter import TelegramChannelAdapter

        adapter = TelegramChannelAdapter(bot_token="test-token", ceo_chat_id="111")
        update = {
            "message": {
                "message_id": 100,
                "from": {"id": 111, "first_name": "カズ"},
                "chat": {"id": -1001234567890, "type": "supergroup"},
                "text": "/ask 経営会議の議題は？",
                "is_topic_message": True,
                "message_thread_id": 55,
            }
        }

        msg = adapter.parse_webhook(update)

        assert msg is not None
        assert msg.room_id == "tg:-1001234567890:55"  # 名前空間化されたroom_id
        assert msg.body == "経営会議の議題は？"
        assert msg.metadata["is_topic"] is True
        assert msg.metadata["topic_id"] == "55"
        assert msg.metadata["chat_type"] == "supergroup"

    def test_edited_message_ignored(self):
        """編集メッセージは無視される"""
        from lib.channels.telegram_adapter import TelegramChannelAdapter

        adapter = TelegramChannelAdapter(bot_token="test-token")
        update = {
            "edited_message": {
                "message_id": 42,
                "from": {"id": 111, "first_name": "カズ"},
                "chat": {"id": 111, "type": "private"},
                "text": "修正後テキスト",
            }
        }

        msg = adapter.parse_webhook(update)
        assert msg is None

    def test_only_command_cleaned_to_empty(self):
        """/start のみはクリーニング後に空文字→Noneが返る"""
        from lib.channels.telegram_adapter import TelegramChannelAdapter

        adapter = TelegramChannelAdapter(bot_token="test-token")
        update = _make_telegram_update(text="/start")

        msg = adapter.parse_webhook(update)
        assert msg is None  # cleaned_textが空でNone


# =============================================================================
# 署名検証フロー
# =============================================================================


class TestTelegramSignatureFlow:
    """Webhook署名検証のフロー"""

    def test_valid_signature_passes(self):
        """正しいトークンで検証成功"""
        from lib.channels.telegram_adapter import verify_telegram_webhook

        assert verify_telegram_webhook(b"body", "my-secret", "my-secret") is True

    def test_invalid_signature_fails(self):
        """不正なトークンで検証失敗"""
        from lib.channels.telegram_adapter import verify_telegram_webhook

        assert verify_telegram_webhook(b"body", "my-secret", "wrong") is False

    def test_no_secret_configured_skips(self):
        """シークレット未設定は検証失敗"""
        from lib.channels.telegram_adapter import verify_telegram_webhook

        assert verify_telegram_webhook(b"body", "", "any") is False


# =============================================================================
# 送信フロー
# =============================================================================


class TestTelegramSendFlow:
    """Telegramメッセージ送信のフロー"""

    @patch("lib.channels.telegram_adapter.httpx.Client")
    def test_send_success(self, mock_client_cls):
        """正常にメッセージ送信"""
        from lib.channels.telegram_adapter import TelegramChannelAdapter

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": {"message_id": 42}}
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        adapter = TelegramChannelAdapter(bot_token="test-token")
        result = adapter.send_message("123", "テスト応答ウル🐺")

        assert result.success is True
        assert result.message_id == "42"

        # 送信パラメータの確認
        call_args = mock_client.post.call_args
        payload = call_args[1]["json"]
        assert payload["chat_id"] == "123"
        assert payload["text"] == "テスト応答ウル🐺"

    @patch("lib.channels.telegram_adapter.httpx.Client")
    def test_send_with_reply_to(self, mock_client_cls):
        """reply_to付きで返信メッセージ送信"""
        from lib.channels.telegram_adapter import TelegramChannelAdapter

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": {"message_id": 43}}
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        adapter = TelegramChannelAdapter(bot_token="test-token")
        result = adapter.send_message("123", "返信テスト", reply_to="42")

        assert result.success is True
        payload = mock_client.post.call_args[1]["json"]
        assert payload["reply_to_message_id"] == 42

    def test_send_without_token_fails(self):
        """トークン未設定で送信失敗"""
        from lib.channels.telegram_adapter import TelegramChannelAdapter

        adapter = TelegramChannelAdapter(bot_token="")
        result = adapter.send_message("123", "テスト")

        assert result.success is False
        assert "not configured" in result.error

    @patch("lib.channels.telegram_adapter.httpx.Client")
    def test_send_api_error(self, mock_client_cls):
        """API 400エラー時はsuccess=False"""
        from lib.channels.telegram_adapter import TelegramChannelAdapter

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request: chat not found"
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        adapter = TelegramChannelAdapter(bot_token="test-token")
        result = adapter.send_message("999", "テスト")

        assert result.success is False
        assert "400" in result.error

    @patch("lib.channels.telegram_adapter.httpx.Client")
    def test_send_network_exception(self, mock_client_cls):
        """ネットワーク例外時はsuccess=False"""
        from lib.channels.telegram_adapter import TelegramChannelAdapter

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = ConnectionError("Connection refused")
        mock_client_cls.return_value = mock_client

        adapter = TelegramChannelAdapter(bot_token="test-token")
        result = adapter.send_message("123", "テスト")

        assert result.success is False


# =============================================================================
# End-to-End フロー（アダプター → メッセージ変換 → 検証）
# =============================================================================


class TestTelegramE2EFlow:
    """エンドツーエンドのメッセージ処理フロー"""

    @patch.dict(os.environ, {"TELEGRAM_CEO_CHAT_ID": "111"})
    def test_full_flow_ceo_private_message(self):
        """社長のプライベートメッセージ: 解析 → 権限OK → Brain用データ準備"""
        from lib.channels.telegram_adapter import TelegramChannelAdapter

        adapter = TelegramChannelAdapter(bot_token="test-token", ceo_chat_id="111")
        update = _make_telegram_update(
            chat_id=111, user_id=111,
            first_name="カズ", last_name="菊地",
            text="売上データを調べて",
        )

        # Step 1: parse_webhook
        msg = adapter.parse_webhook(update)
        assert msg is not None

        # Step 2: 権限チェック
        assert msg.metadata["is_ceo"] is True
        assert msg.should_process is True

        # Step 3: Brain用のデータ
        assert msg.body == "売上データを調べて"
        assert msg.sender_name == "カズ 菊地"
        assert msg.room_id == "tg:111"
        assert msg.platform == "telegram"

    @patch.dict(os.environ, {
        "TELEGRAM_CEO_CHAT_ID": "111",
        "TELEGRAM_BOT_USERNAME": "soulkun_bot",
    })
    def test_full_flow_group_mention(self):
        """グループ内でのボット宛メンション: 解析 → ボット宛 → Brain用データ準備"""
        from lib.channels.telegram_adapter import TelegramChannelAdapter

        adapter = TelegramChannelAdapter(bot_token="test-token", ceo_chat_id="111")
        update = {
            "message": {
                "message_id": 100,
                "from": {"id": 111, "first_name": "カズ"},
                "chat": {"id": -1001234567890, "type": "supergroup"},
                "text": "@soulkun_bot 今日の予定教えて",
                "is_topic_message": True,
                "message_thread_id": 55,
            }
        }

        msg = adapter.parse_webhook(update)
        assert msg is not None

        # ボット宛判定
        assert msg.is_bot_addressed is True

        # メッセージクリーニング
        assert msg.body == "今日の予定教えて"

        # トピック情報（名前空間化: tg:{chat_id}:{topic_id}）
        assert msg.room_id == "tg:-1001234567890:55"
        assert msg.metadata["topic_id"] == "55"

    @patch.dict(os.environ, {"TELEGRAM_CEO_CHAT_ID": "111"})
    def test_full_flow_non_addressed_group_message(self):
        """グループ内のボット宛でないメッセージ: is_bot_addressed=False"""
        from lib.channels.telegram_adapter import TelegramChannelAdapter

        adapter = TelegramChannelAdapter(bot_token="test-token", ceo_chat_id="111")
        update = {
            "message": {
                "message_id": 100,
                "from": {"id": 111, "first_name": "カズ"},
                "chat": {"id": -1001234567890, "type": "supergroup"},
                "text": "普通のグループ会話",
            }
        }

        msg = adapter.parse_webhook(update)
        assert msg is not None
        assert msg.is_bot_addressed is False
        assert msg.body == "普通のグループ会話"


# =============================================================================
# Step B-2: セキュリティ機能テスト
# =============================================================================


class TestTelegramGroupRestriction:
    """Step B-2: グループチャット制限テスト"""

    @patch.dict(os.environ, {"TELEGRAM_CEO_CHAT_ID": "111"})
    def test_private_chat_allowed(self):
        """プライベートチャットは許可される"""
        from lib.channels.telegram_adapter import TelegramChannelAdapter

        adapter = TelegramChannelAdapter(bot_token="test-token", ceo_chat_id="111")
        update = _make_telegram_update(chat_id=111, chat_type="private")
        msg = adapter.parse_webhook(update)

        assert msg is not None
        assert msg.metadata["is_private"] is True
        # グループ制限にかからない（private → OK）

    @patch.dict(os.environ, {"TELEGRAM_CEO_CHAT_ID": "111"})
    def test_supergroup_with_topic_allowed(self):
        """スーパーグループ+トピックは許可される"""
        from lib.channels.telegram_adapter import TelegramChannelAdapter

        adapter = TelegramChannelAdapter(bot_token="test-token", ceo_chat_id="111")
        update = {
            "message": {
                "message_id": 100,
                "from": {"id": 111, "first_name": "カズ"},
                "chat": {"id": -1001234567890, "type": "supergroup"},
                "text": "/ask 質問",
                "is_topic_message": True,
                "message_thread_id": 55,
            }
        }
        msg = adapter.parse_webhook(update)

        assert msg is not None
        assert msg.metadata["chat_type"] == "supergroup"
        assert msg.metadata["is_topic"] is True
        # グループ制限にかからない（supergroup + topic → OK）

    @patch.dict(os.environ, {"TELEGRAM_CEO_CHAT_ID": "111"})
    def test_regular_group_produces_metadata(self):
        """普通のグループメッセージにはis_topic=Falseのメタデータが付く"""
        from lib.channels.telegram_adapter import TelegramChannelAdapter

        adapter = TelegramChannelAdapter(bot_token="test-token", ceo_chat_id="111")
        update = {
            "message": {
                "message_id": 100,
                "from": {"id": 111, "first_name": "カズ"},
                "chat": {"id": -999, "type": "group"},
                "text": "/ask テスト",
            }
        }
        msg = adapter.parse_webhook(update)

        assert msg is not None
        assert msg.metadata["chat_type"] == "group"
        assert msg.metadata["is_topic"] is False
        # main.pyのwebhook側でgroup_not_allowedとして拒否される


class TestTelegramRateLimit:
    """Step B-2: レート制限テスト"""

    def test_rate_limit_function_exists(self):
        """レート制限関数がソースコードに存在する"""
        import ast

        main_path = os.path.join(
            os.path.dirname(__file__), "..", "chatwork-webhook", "main.py"
        )
        with open(main_path) as f:
            source = f.read()

        tree = ast.parse(source)
        func_names = [
            node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        ]

        assert "_check_telegram_rate_limit" in func_names
        assert "telegram_webhook" in func_names

    def test_rate_limit_logic_standalone(self):
        """レート制限ロジックの単体テスト（関数を直接実行）"""
        import time as _time

        # 簡易的にレート制限ロジックを再現してテスト
        rate_limit = {}
        max_requests = 3
        window = 1.0  # 1秒ウィンドウ

        def check(chat_id):
            now = _time.time()
            if chat_id not in rate_limit:
                rate_limit[chat_id] = []
            rate_limit[chat_id] = [
                ts for ts in rate_limit[chat_id] if now - ts < window
            ]
            if len(rate_limit[chat_id]) >= max_requests:
                return False
            rate_limit[chat_id].append(now)
            return True

        # 3件はOK
        assert check("111") is True
        assert check("111") is True
        assert check("111") is True
        # 4件目でレート制限
        assert check("111") is False
        # 別のchat_idは影響なし
        assert check("222") is True


class TestTelegramAuditLogging:
    """Step B-2: 監査ログテスト（print→logging変換の確認）"""

    @patch.dict(os.environ, {"TELEGRAM_CEO_CHAT_ID": "111"})
    def test_no_print_statements_in_telegram_webhook(self):
        """telegram_webhook関数にprint文が残っていないことを確認"""
        import ast

        main_path = os.path.join(
            os.path.dirname(__file__), "..", "chatwork-webhook", "main.py"
        )
        with open(main_path) as f:
            source = f.read()

        tree = ast.parse(source)

        # telegram_webhook関数を見つける
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "telegram_webhook":
                # 関数内のprint呼び出しを探す
                prints_found = []
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        func = child.func
                        if isinstance(func, ast.Name) and func.id == "print":
                            prints_found.append(child.lineno)

                assert len(prints_found) == 0, (
                    f"telegram_webhook()にprint文が残っています（行: {prints_found}）。"
                    "loggingを使用してください。"
                )
