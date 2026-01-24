"""
メモリ管理ハンドラーのテスト

chatwork-webhook/handlers/memory_handler.py のテスト
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
import sys
import os

# chatwork-webhookのパスを追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'chatwork-webhook'))

from handlers.memory_handler import MemoryHandler


class TestMemoryHandlerInit:
    """MemoryHandlerの初期化テスト"""

    def test_init(self):
        """正常に初期化できること"""
        handler = MemoryHandler(
            firestore_db=MagicMock(),
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            max_history_count=100,
            history_expiry_hours=720
        )
        assert handler.max_history_count == 100
        assert handler.history_expiry_hours == 720


class TestGetConversationHistory:
    """get_conversation_history関数のテスト"""

    def test_get_history_success(self):
        """会話履歴が正常に取得できること"""
        mock_db = MagicMock()
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {
            "history": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi!"}
            ],
            "updated_at": datetime.now(timezone.utc)
        }
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        handler = MemoryHandler(
            firestore_db=mock_db,
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            max_history_count=100,
            history_expiry_hours=720
        )

        result = handler.get_conversation_history("room123", "account456")

        assert len(result) == 2
        assert result[0]["role"] == "user"

    def test_get_history_not_exists(self):
        """履歴が存在しない場合は空リストを返すこと"""
        mock_db = MagicMock()
        mock_doc = MagicMock()
        mock_doc.exists = False
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        handler = MemoryHandler(
            firestore_db=mock_db,
            get_pool=MagicMock(),
            get_secret=MagicMock()
        )

        result = handler.get_conversation_history("room123", "account456")

        assert result == []

    def test_get_history_expired(self):
        """期限切れの履歴は空リストを返すこと"""
        mock_db = MagicMock()
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {
            "history": [{"role": "user", "content": "Hello"}],
            "updated_at": datetime.now(timezone.utc) - timedelta(hours=800)  # 期限切れ
        }
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        handler = MemoryHandler(
            firestore_db=mock_db,
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            history_expiry_hours=720
        )

        result = handler.get_conversation_history("room123", "account456")

        assert result == []

    def test_get_history_truncated(self):
        """履歴がmax_history_countを超える場合は切り詰めること"""
        mock_db = MagicMock()
        mock_doc = MagicMock()
        mock_doc.exists = True
        # 150件の履歴
        large_history = [{"role": "user", "content": f"Message {i}"} for i in range(150)]
        mock_doc.to_dict.return_value = {
            "history": large_history,
            "updated_at": datetime.now(timezone.utc)
        }
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        handler = MemoryHandler(
            firestore_db=mock_db,
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            max_history_count=100
        )

        result = handler.get_conversation_history("room123", "account456")

        assert len(result) == 100

    def test_get_history_error(self):
        """エラー時は空リストを返すこと"""
        mock_db = MagicMock()
        mock_db.collection.side_effect = Exception("Firestore error")

        handler = MemoryHandler(
            firestore_db=mock_db,
            get_pool=MagicMock(),
            get_secret=MagicMock()
        )

        result = handler.get_conversation_history("room123", "account456")

        assert result == []


class TestSaveConversationHistory:
    """save_conversation_history関数のテスト"""

    def test_save_history_success(self):
        """会話履歴が正常に保存できること"""
        mock_db = MagicMock()

        handler = MemoryHandler(
            firestore_db=mock_db,
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            max_history_count=100
        )

        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"}
        ]
        handler.save_conversation_history("room123", "account456", history)

        # setが呼ばれたことを確認
        mock_db.collection.return_value.document.return_value.set.assert_called_once()

    def test_save_history_truncated(self):
        """履歴がmax_history_countを超える場合は切り詰めて保存すること"""
        mock_db = MagicMock()

        handler = MemoryHandler(
            firestore_db=mock_db,
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            max_history_count=10
        )

        # 20件の履歴
        history = [{"role": "user", "content": f"Message {i}"} for i in range(20)]
        handler.save_conversation_history("room123", "account456", history)

        # setに渡された履歴が10件に切り詰められていることを確認
        call_args = mock_db.collection.return_value.document.return_value.set.call_args
        saved_history = call_args[0][0]["history"]
        assert len(saved_history) == 10


class TestClearConversationHistory:
    """clear_conversation_history関数のテスト"""

    def test_clear_history_success(self):
        """会話履歴が正常にクリアできること"""
        mock_db = MagicMock()

        handler = MemoryHandler(
            firestore_db=mock_db,
            get_pool=MagicMock(),
            get_secret=MagicMock()
        )

        result = handler.clear_conversation_history("room123", "account456")

        assert result is True
        mock_db.collection.return_value.document.return_value.delete.assert_called_once()

    def test_clear_history_error(self):
        """エラー時はFalseを返すこと"""
        mock_db = MagicMock()
        mock_db.collection.return_value.document.return_value.delete.side_effect = Exception("Error")

        handler = MemoryHandler(
            firestore_db=mock_db,
            get_pool=MagicMock(),
            get_secret=MagicMock()
        )

        result = handler.clear_conversation_history("room123", "account456")

        assert result is False


class TestProcessMemoryAfterConversation:
    """process_memory_after_conversation関数のテスト"""

    def test_process_disabled(self):
        """Memory Frameworkが無効の場合は何もしないこと"""
        handler = MemoryHandler(
            firestore_db=MagicMock(),
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            use_memory_framework=False  # 無効
        )

        # エラーが発生しないことを確認
        handler.process_memory_after_conversation(
            room_id="room123",
            account_id="account456",
            sender_name="Test User",
            user_message="Hello",
            ai_response="Hi!",
            history=[]
        )

    def test_process_no_classes(self):
        """Memory Frameworkクラスが未設定の場合は何もしないこと"""
        handler = MemoryHandler(
            firestore_db=MagicMock(),
            get_pool=MagicMock(),
            get_secret=MagicMock(),
            use_memory_framework=True,
            conversation_summary_class=None,
            conversation_search_class=None
        )

        # エラーが発生しないことを確認
        handler.process_memory_after_conversation(
            room_id="room123",
            account_id="account456",
            sender_name="Test User",
            user_message="Hello",
            ai_response="Hi!",
            history=[]
        )

    def test_process_below_threshold(self):
        """閾値未満の場合はスキップすること"""
        mock_pool = MagicMock()

        handler = MemoryHandler(
            firestore_db=MagicMock(),
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            use_memory_framework=True,
            memory_summary_trigger_count=10,
            conversation_summary_class=MagicMock,
            conversation_search_class=MagicMock
        )

        # 5件の履歴（閾値10未満）
        history = [{"role": "user", "content": f"Message {i}"} for i in range(5)]

        handler.process_memory_after_conversation(
            room_id="room123",
            account_id="account456",
            sender_name="Test User",
            user_message="Hello",
            ai_response="Hi!",
            history=history
        )

        # get_poolが呼ばれないことを確認（閾値未満でスキップ）
        handler.get_pool.assert_not_called()

    def test_process_user_not_found(self):
        """ユーザーが見つからない場合はスキップすること"""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = None  # ユーザーなし

        handler = MemoryHandler(
            firestore_db=MagicMock(),
            get_pool=MagicMock(return_value=mock_pool),
            get_secret=MagicMock(),
            use_memory_framework=True,
            memory_summary_trigger_count=5,
            conversation_summary_class=MagicMock,
            conversation_search_class=MagicMock
        )

        # 10件の履歴（閾値以上）
        history = [{"role": "user", "content": f"Message {i}"} for i in range(10)]

        # エラーが発生しないことを確認
        handler.process_memory_after_conversation(
            room_id="room123",
            account_id="account456",
            sender_name="Test User",
            user_message="Hello",
            ai_response="Hi!",
            history=history
        )


class TestDocumentPath:
    """Firestoreドキュメントパスのテスト"""

    def test_document_path_format(self):
        """ドキュメントパスが正しい形式であること"""
        mock_db = MagicMock()
        mock_doc = MagicMock()
        mock_doc.exists = False
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        handler = MemoryHandler(
            firestore_db=mock_db,
            get_pool=MagicMock(),
            get_secret=MagicMock()
        )

        handler.get_conversation_history("room123", "account456")

        # ドキュメントパスの確認
        mock_db.collection.assert_called_with("conversations")
        mock_db.collection.return_value.document.assert_called_with("room123_account456")
