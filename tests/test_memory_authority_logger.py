# tests/test_memory_authority_logger.py
"""
Memory Authority Observation Logger のテスト

v10.43.2: Cloud Logging対応版
"""

import asyncio
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

# =============================================================================
# SoftConflictLog テスト
# =============================================================================


class TestSoftConflictLog:
    """SoftConflictLogデータクラスのテスト"""

    def test_create_basic_log(self):
        """基本的なログ作成"""
        from lib.brain.memory_authority_logger import SoftConflictLog

        log = SoftConflictLog(
            timestamp="2025-01-28T10:00:00",
            action="chatwork_task_create",
            detected_memory_reference="家族との時間を大切に",
            conflict_reason="優先順位との矛盾",
        )
        assert log.action == "chatwork_task_create"
        assert log.detected_memory_reference == "家族との時間を大切に"
        assert log.conflict_reason == "優先順位との矛盾"
        assert log.user_response is None
        assert log.log_id.startswith("sc_")

    def test_log_id_auto_generated(self):
        """ログIDが自動生成される"""
        from lib.brain.memory_authority_logger import SoftConflictLog

        log1 = SoftConflictLog(
            timestamp="2025-01-28T10:00:00",
            action="action1",
            detected_memory_reference="ref1",
            conflict_reason="reason1",
        )
        log2 = SoftConflictLog(
            timestamp="2025-01-28T10:00:01",
            action="action2",
            detected_memory_reference="ref2",
            conflict_reason="reason2",
        )
        assert log1.log_id != log2.log_id

    def test_log_id_preserved_if_provided(self):
        """ログIDが指定された場合は保持される"""
        from lib.brain.memory_authority_logger import SoftConflictLog

        log = SoftConflictLog(
            timestamp="2025-01-28T10:00:00",
            action="action1",
            detected_memory_reference="ref1",
            conflict_reason="reason1",
            log_id="custom_id_123",
        )
        assert log.log_id == "custom_id_123"

    def test_to_dict(self):
        """辞書形式に変換"""
        from lib.brain.memory_authority_logger import SoftConflictLog

        log = SoftConflictLog(
            timestamp="2025-01-28T10:00:00",
            action="chatwork_task_create",
            detected_memory_reference="家族との時間を大切に",
            conflict_reason="優先順位との矛盾",
            room_id="123456",
            account_id="789",
            organization_id="org_test",
            confidence=0.6,
        )
        d = log.to_dict()
        assert d["action"] == "chatwork_task_create"
        assert d["room_id"] == "123456"
        assert d["confidence"] == 0.6
        assert "log_id" in d

    def test_conflict_details_default_empty(self):
        """conflict_detailsはデフォルトで空リスト"""
        from lib.brain.memory_authority_logger import SoftConflictLog

        log = SoftConflictLog(
            timestamp="2025-01-28T10:00:00",
            action="action1",
            detected_memory_reference="ref1",
            conflict_reason="reason1",
        )
        assert log.conflict_details == []


# =============================================================================
# MemoryAuthorityLogger テスト（Cloud Loggingモック）
# =============================================================================


class TestMemoryAuthorityLogger:
    """MemoryAuthorityLoggerのテスト"""

    @patch("google.cloud.logging.Client")
    def test_init_with_cloud_logging(self, mock_client_class):
        """Cloud Loggingクライアントが初期化される"""
        # モジュールをリロードしてクリーンな状態で
        import importlib
        import lib.brain.memory_authority_logger as mal
        mal._logger_instance = None

        mock_client = MagicMock()
        mock_logger = MagicMock()
        mock_client.logger.return_value = mock_logger
        mock_client_class.return_value = mock_client

        from lib.brain.memory_authority_logger import MemoryAuthorityLogger
        logger_instance = MemoryAuthorityLogger(enabled=True)

        mock_client_class.assert_called_once()
        mock_client.logger.assert_called_once_with("memory_authority_soft_conflicts")
        assert logger_instance._cloud_logger is mock_logger

    def test_init_disabled(self):
        """無効化された場合はCloud Loggingを初期化しない"""
        from lib.brain.memory_authority_logger import MemoryAuthorityLogger
        logger_instance = MemoryAuthorityLogger(enabled=False)
        assert logger_instance.enabled is False

    @patch("google.cloud.logging.Client")
    def test_log_soft_conflict_returns_log_id(self, mock_client_class):
        """ログ記録時にログIDを返す"""
        mock_client = MagicMock()
        mock_client.logger.return_value = MagicMock()
        mock_client_class.return_value = mock_client

        from lib.brain.memory_authority_logger import MemoryAuthorityLogger
        logger_instance = MemoryAuthorityLogger(enabled=True)
        log_id = logger_instance.log_soft_conflict(
            action="chatwork_task_create",
            detected_memory_reference="家族との時間を大切に",
            conflict_reason="優先順位との矛盾",
        )
        assert log_id.startswith("sc_")

    def test_log_soft_conflict_disabled_returns_empty(self):
        """無効時は空文字を返す"""
        from lib.brain.memory_authority_logger import MemoryAuthorityLogger
        logger_instance = MemoryAuthorityLogger(enabled=False)
        log_id = logger_instance.log_soft_conflict(
            action="chatwork_task_create",
            detected_memory_reference="ref",
            conflict_reason="reason",
        )
        assert log_id == ""

    @patch("google.cloud.logging.Client")
    def test_log_stored_in_pending(self, mock_client_class):
        """ログはまずペンディングに保存される"""
        mock_client = MagicMock()
        mock_client.logger.return_value = MagicMock()
        mock_client_class.return_value = mock_client

        from lib.brain.memory_authority_logger import MemoryAuthorityLogger
        logger_instance = MemoryAuthorityLogger(enabled=True)
        log_id = logger_instance.log_soft_conflict(
            action="action1",
            detected_memory_reference="ref1",
            conflict_reason="reason1",
        )
        assert log_id in logger_instance._pending_logs

    @patch("google.cloud.logging.Client")
    def test_update_user_response_calls_cloud_logging(self, mock_client_class):
        """ユーザー応答更新時にCloud Loggingに出力される"""
        mock_client = MagicMock()
        mock_logger = MagicMock()
        mock_client.logger.return_value = mock_logger
        mock_client_class.return_value = mock_client

        from lib.brain.memory_authority_logger import MemoryAuthorityLogger
        logger_instance = MemoryAuthorityLogger(enabled=True)
        log_id = logger_instance.log_soft_conflict(
            action="action1",
            detected_memory_reference="ref1",
            conflict_reason="reason1",
        )

        # 更新
        result = logger_instance.update_user_response(log_id, "ok")
        assert result is True

        # Cloud Loggingが呼ばれた
        mock_logger.log_struct.assert_called_once()
        call_args = mock_logger.log_struct.call_args
        log_dict = call_args[0][0]
        assert log_dict["user_response"] == "ok"
        assert log_dict["action"] == "action1"
        assert call_args[1]["severity"] == "INFO"

        # ペンディングから削除されている
        assert log_id not in logger_instance._pending_logs

    @patch("google.cloud.logging.Client")
    def test_update_user_response_not_found(self, mock_client_class):
        """存在しないログIDで更新失敗"""
        mock_client = MagicMock()
        mock_client.logger.return_value = MagicMock()
        mock_client_class.return_value = mock_client

        from lib.brain.memory_authority_logger import MemoryAuthorityLogger
        logger_instance = MemoryAuthorityLogger(enabled=True)
        result = logger_instance.update_user_response("nonexistent_id", "ok")
        assert result is False

    @patch("google.cloud.logging.Client")
    def test_flush_pending(self, mock_client_class):
        """ペンディングログを全てCloud Loggingに出力"""
        mock_client = MagicMock()
        mock_logger = MagicMock()
        mock_client.logger.return_value = mock_logger
        mock_client_class.return_value = mock_client

        from lib.brain.memory_authority_logger import MemoryAuthorityLogger
        logger_instance = MemoryAuthorityLogger(enabled=True)

        # 複数のログを記録
        logger_instance.log_soft_conflict("action1", "ref1", "reason1")
        logger_instance.log_soft_conflict("action2", "ref2", "reason2")
        logger_instance.log_soft_conflict("action3", "ref3", "reason3")

        assert len(logger_instance._pending_logs) == 3

        # フラッシュ
        count = logger_instance.flush_pending(default_response="timeout")
        assert count == 3
        assert len(logger_instance._pending_logs) == 0

        # Cloud Loggingが3回呼ばれた
        assert mock_logger.log_struct.call_count == 3

    @patch("google.cloud.logging.Client")
    def test_get_pending_count(self, mock_client_class):
        """ペンディング件数取得"""
        mock_client = MagicMock()
        mock_client.logger.return_value = MagicMock()
        mock_client_class.return_value = mock_client

        from lib.brain.memory_authority_logger import MemoryAuthorityLogger
        logger_instance = MemoryAuthorityLogger(enabled=True)
        assert logger_instance.get_pending_count() == 0

        logger_instance.log_soft_conflict("action1", "ref1", "reason1")
        logger_instance.log_soft_conflict("action2", "ref2", "reason2")
        assert logger_instance.get_pending_count() == 2


# =============================================================================
# 非同期テスト
# =============================================================================


class TestMemoryAuthorityLoggerAsync:
    """非同期メソッドのテスト"""

    @pytest.mark.asyncio
    @patch("google.cloud.logging.Client")
    async def test_log_soft_conflict_async(self, mock_client_class):
        """非同期ログ記録"""
        mock_client = MagicMock()
        mock_client.logger.return_value = MagicMock()
        mock_client_class.return_value = mock_client

        from lib.brain.memory_authority_logger import MemoryAuthorityLogger
        logger_instance = MemoryAuthorityLogger(enabled=True)
        log_id = await logger_instance.log_soft_conflict_async(
            action="async_action",
            detected_memory_reference="async_ref",
            conflict_reason="async_reason",
        )
        assert log_id.startswith("sc_")
        assert log_id in logger_instance._pending_logs

    @pytest.mark.asyncio
    @patch("google.cloud.logging.Client")
    async def test_update_user_response_async(self, mock_client_class):
        """非同期でユーザー応答を更新"""
        mock_client = MagicMock()
        mock_logger = MagicMock()
        mock_client.logger.return_value = mock_logger
        mock_client_class.return_value = mock_client

        from lib.brain.memory_authority_logger import MemoryAuthorityLogger
        logger_instance = MemoryAuthorityLogger(enabled=True)
        log_id = await logger_instance.log_soft_conflict_async(
            action="async_action",
            detected_memory_reference="async_ref",
            conflict_reason="async_reason",
        )

        result = await logger_instance.update_user_response_async(log_id, "ok")
        assert result is True
        assert log_id not in logger_instance._pending_logs

        # Cloud Loggingが呼ばれた
        mock_logger.log_struct.assert_called_once()


# =============================================================================
# シングルトン & ファクトリーテスト
# =============================================================================


class TestFactoryFunctions:
    """ファクトリー関数のテスト"""

    @patch("google.cloud.logging.Client")
    def test_get_memory_authority_logger_singleton(self, mock_client_class):
        """シングルトンインスタンスを取得"""
        mock_client = MagicMock()
        mock_client.logger.return_value = MagicMock()
        mock_client_class.return_value = mock_client

        # グローバル状態をリセット
        import lib.brain.memory_authority_logger as mal
        mal._logger_instance = None

        from lib.brain.memory_authority_logger import get_memory_authority_logger
        logger1 = get_memory_authority_logger(enabled=True)
        logger2 = get_memory_authority_logger()
        assert logger1 is logger2

    @patch("google.cloud.logging.Client")
    def test_create_memory_authority_logger_new_instance(self, mock_client_class):
        """新しいインスタンスを作成"""
        mock_client = MagicMock()
        mock_client.logger.return_value = MagicMock()
        mock_client_class.return_value = mock_client

        from lib.brain.memory_authority_logger import create_memory_authority_logger
        logger1 = create_memory_authority_logger(enabled=True)
        logger2 = create_memory_authority_logger(enabled=True)
        assert logger1 is not logger2


# =============================================================================
# エッジケーステスト
# =============================================================================


class TestEdgeCases:
    """エッジケースのテスト"""

    @patch("google.cloud.logging.Client")
    def test_long_memory_reference_truncated(self, mock_client_class):
        """長い記憶参照は切り詰められる"""
        mock_client = MagicMock()
        mock_client.logger.return_value = MagicMock()
        mock_client_class.return_value = mock_client

        from lib.brain.memory_authority_logger import MemoryAuthorityLogger
        logger_instance = MemoryAuthorityLogger(enabled=True)
        long_ref = "あ" * 500
        log_id = logger_instance.log_soft_conflict(
            action="action",
            detected_memory_reference=long_ref,
            conflict_reason="reason",
        )
        log = logger_instance._pending_logs[log_id]
        assert len(log.detected_memory_reference) <= 200

    @patch("google.cloud.logging.Client")
    def test_long_message_excerpt_truncated(self, mock_client_class):
        """長いメッセージ抜粋は切り詰められる"""
        mock_client = MagicMock()
        mock_client.logger.return_value = MagicMock()
        mock_client_class.return_value = mock_client

        from lib.brain.memory_authority_logger import MemoryAuthorityLogger
        logger_instance = MemoryAuthorityLogger(enabled=True)
        long_msg = "あ" * 500
        log_id = logger_instance.log_soft_conflict(
            action="action",
            detected_memory_reference="ref",
            conflict_reason="reason",
            message_excerpt=long_msg,
        )
        log = logger_instance._pending_logs[log_id]
        assert len(log.message_excerpt) <= 100

    @patch("google.cloud.logging.Client")
    def test_conflict_details_preserved(self, mock_client_class):
        """詳細な矛盾情報が保存される"""
        mock_client = MagicMock()
        mock_logger = MagicMock()
        mock_client.logger.return_value = mock_logger
        mock_client_class.return_value = mock_client

        from lib.brain.memory_authority_logger import MemoryAuthorityLogger
        logger_instance = MemoryAuthorityLogger(enabled=True)
        details = [
            {"memory_type": "principles", "excerpt": "家族を大切に"},
            {"memory_type": "values", "excerpt": "健康第一"},
        ]
        log_id = logger_instance.log_soft_conflict(
            action="action",
            detected_memory_reference="ref",
            conflict_reason="reason",
            conflict_details=details,
        )
        logger_instance.update_user_response(log_id, "ok")

        # Cloud Loggingに詳細情報が含まれている
        call_args = mock_logger.log_struct.call_args
        log_dict = call_args[0][0]
        assert len(log_dict["conflict_details"]) == 2

    @patch("google.cloud.logging.Client")
    def test_cloud_logging_failure_fallback(self, mock_client_class):
        """Cloud Logging失敗時は標準ログにフォールバックして成功扱い"""
        mock_client = MagicMock()
        mock_logger = MagicMock()
        mock_logger.log_struct.side_effect = Exception("Cloud Logging error")
        mock_client.logger.return_value = mock_logger
        mock_client_class.return_value = mock_client

        from lib.brain.memory_authority_logger import MemoryAuthorityLogger
        logger_instance = MemoryAuthorityLogger(enabled=True)
        log_id = logger_instance.log_soft_conflict(
            action="action",
            detected_memory_reference="ref",
            conflict_reason="reason",
        )

        # Cloud Loggingが失敗しても標準ログにフォールバックして成功
        result = logger_instance.update_user_response(log_id, "ok")
        # フォールバックにより成功扱い
        assert result is True
        # ペンディングから削除される
        assert log_id not in logger_instance._pending_logs
        # Cloud Loggingは呼ばれた（失敗したが）
        mock_logger.log_struct.assert_called_once()


# =============================================================================
# 統合テスト
# =============================================================================


class TestIntegration:
    """統合テスト"""

    @patch("google.cloud.logging.Client")
    def test_full_workflow(self, mock_client_class):
        """完全なワークフロー: ログ → 応答更新 → Cloud Logging出力"""
        mock_client = MagicMock()
        mock_logger = MagicMock()
        mock_client.logger.return_value = mock_logger
        mock_client_class.return_value = mock_client

        from lib.brain.memory_authority_logger import MemoryAuthorityLogger
        logger_instance = MemoryAuthorityLogger(enabled=True)

        # 1. 複数のSOFT_CONFLICTをログ
        log_ids = []
        for i in range(10):
            log_id = logger_instance.log_soft_conflict(
                action=f"action_{i % 3}",
                detected_memory_reference=f"記憶参照{i}",
                conflict_reason=f"矛盾理由{i}",
                room_id=f"room_{i}",
                account_id=f"account_{i}",
                organization_id="org_test",
                confidence=0.5 + (i * 0.05),
            )
            log_ids.append(log_id)

        # 2. ユーザー応答を更新（一部のみ）
        responses = ["ok", "modify", "cancel", "ok", "modify"]
        for i, response in enumerate(responses):
            logger_instance.update_user_response(log_ids[i], response)

        # 3. 残りをフラッシュ
        flushed = logger_instance.flush_pending(default_response="timeout")
        assert flushed == 5

        # 4. Cloud Loggingが10回呼ばれた
        assert mock_logger.log_struct.call_count == 10

        # 5. ペンディングが空
        assert logger_instance.get_pending_count() == 0

    @pytest.mark.asyncio
    @patch("google.cloud.logging.Client")
    async def test_async_non_blocking(self, mock_client_class):
        """非同期ログがメイン処理をブロックしないことを確認"""
        mock_client = MagicMock()
        mock_client.logger.return_value = MagicMock()
        mock_client_class.return_value = mock_client

        from lib.brain.memory_authority_logger import MemoryAuthorityLogger
        logger_instance = MemoryAuthorityLogger(enabled=True)

        # 非同期でログ記録
        start = datetime.now()
        tasks = []
        for i in range(100):
            task = logger_instance.log_soft_conflict_async(
                action=f"action_{i}",
                detected_memory_reference=f"ref_{i}",
                conflict_reason=f"reason_{i}",
            )
            tasks.append(task)

        # 全タスクを並列実行
        results = await asyncio.gather(*tasks)
        elapsed = (datetime.now() - start).total_seconds()

        # 全て成功
        assert all(r.startswith("sc_") for r in results)

        # 処理時間が妥当（並列なので短いはず）
        # 注: CIでは遅いかもしれないので緩めの閾値
        assert elapsed < 5.0


# =============================================================================
# Cloud Logging利用不可時のテスト
# =============================================================================


class TestWithoutCloudLogging:
    """Cloud Logging利用不可時のテスト"""

    def test_fallback_to_standard_logging_when_disabled(self):
        """無効時は標準ログにフォールバック"""
        from lib.brain.memory_authority_logger import MemoryAuthorityLogger
        logger_instance = MemoryAuthorityLogger(enabled=False)

        # ログ記録は動作しない（空文字を返す）
        log_id = logger_instance.log_soft_conflict(
            action="action",
            detected_memory_reference="ref",
            conflict_reason="reason",
        )
        assert log_id == ""

    @patch("google.cloud.logging.Client")
    def test_cloud_logger_none_fallback(self, mock_client_class):
        """Cloud Loggerがnoneの場合は標準ログにフォールバック"""
        mock_client_class.side_effect = Exception("Cannot create client")

        from lib.brain.memory_authority_logger import MemoryAuthorityLogger
        logger_instance = MemoryAuthorityLogger(enabled=True)

        # Cloud Loggerはnone
        assert logger_instance._cloud_logger is None

        # ログ記録は動作する
        log_id = logger_instance.log_soft_conflict(
            action="action",
            detected_memory_reference="ref",
            conflict_reason="reason",
        )
        assert log_id.startswith("sc_")

        # 応答更新も動作する（標準ログに出力）
        result = logger_instance.update_user_response(log_id, "ok")
        assert result is True
