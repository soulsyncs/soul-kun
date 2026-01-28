# tests/test_memory_authority_logger.py
"""
Memory Authority Observation Logger のテスト

v10.43.1: P4 SOFT_CONFLICT観測用ログ保存機能のテスト
"""

import asyncio
import json
import os
import pytest
import tempfile
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock

from lib.brain.memory_authority_logger import (
    SoftConflictLog,
    MemoryAuthorityLogger,
    get_memory_authority_logger,
    create_memory_authority_logger,
)


# =============================================================================
# SoftConflictLog テスト
# =============================================================================


class TestSoftConflictLog:
    """SoftConflictLogデータクラスのテスト"""

    def test_create_basic_log(self):
        """基本的なログ作成"""
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
        log = SoftConflictLog(
            timestamp="2025-01-28T10:00:00",
            action="action1",
            detected_memory_reference="ref1",
            conflict_reason="reason1",
        )
        assert log.conflict_details == []


# =============================================================================
# MemoryAuthorityLogger テスト
# =============================================================================


class TestMemoryAuthorityLogger:
    """MemoryAuthorityLoggerのテスト"""

    def test_init_creates_directory(self):
        """初期化時にログディレクトリを作成"""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = os.path.join(tmpdir, "test_logs")
            logger = MemoryAuthorityLogger(log_dir=log_dir, enabled=True)
            assert Path(log_dir).exists()

    def test_init_disabled(self):
        """無効化された場合はディレクトリを作成しない"""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = os.path.join(tmpdir, "test_logs_disabled")
            logger = MemoryAuthorityLogger(log_dir=log_dir, enabled=False)
            assert not Path(log_dir).exists()

    def test_log_soft_conflict_returns_log_id(self):
        """ログ記録時にログIDを返す"""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = MemoryAuthorityLogger(log_dir=tmpdir, enabled=True)
            log_id = logger.log_soft_conflict(
                action="chatwork_task_create",
                detected_memory_reference="家族との時間を大切に",
                conflict_reason="優先順位との矛盾",
            )
            assert log_id.startswith("sc_")

    def test_log_soft_conflict_disabled_returns_empty(self):
        """無効時は空文字を返す"""
        logger = MemoryAuthorityLogger(enabled=False)
        log_id = logger.log_soft_conflict(
            action="chatwork_task_create",
            detected_memory_reference="ref",
            conflict_reason="reason",
        )
        assert log_id == ""

    def test_log_stored_in_pending(self):
        """ログはまずペンディングに保存される"""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = MemoryAuthorityLogger(log_dir=tmpdir, enabled=True)
            log_id = logger.log_soft_conflict(
                action="action1",
                detected_memory_reference="ref1",
                conflict_reason="reason1",
            )
            assert log_id in logger._pending_logs

    def test_update_user_response(self):
        """ユーザー応答を更新してログを確定保存"""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = MemoryAuthorityLogger(log_dir=tmpdir, enabled=True)
            log_id = logger.log_soft_conflict(
                action="action1",
                detected_memory_reference="ref1",
                conflict_reason="reason1",
            )

            # 更新
            result = logger.update_user_response(log_id, "ok")
            assert result is True

            # ペンディングから削除されている
            assert log_id not in logger._pending_logs

            # ファイルに保存されている
            assert logger.log_path.exists()
            with open(logger.log_path, "r") as f:
                line = f.readline()
                data = json.loads(line)
                assert data["user_response"] == "ok"

    def test_update_user_response_not_found(self):
        """存在しないログIDで更新失敗"""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = MemoryAuthorityLogger(log_dir=tmpdir, enabled=True)
            result = logger.update_user_response("nonexistent_id", "ok")
            assert result is False

    def test_flush_pending(self):
        """ペンディングログを全て確定保存"""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = MemoryAuthorityLogger(log_dir=tmpdir, enabled=True)

            # 複数のログを記録
            logger.log_soft_conflict("action1", "ref1", "reason1")
            logger.log_soft_conflict("action2", "ref2", "reason2")
            logger.log_soft_conflict("action3", "ref3", "reason3")

            assert len(logger._pending_logs) == 3

            # フラッシュ
            count = logger.flush_pending(default_response="timeout")
            assert count == 3
            assert len(logger._pending_logs) == 0

    def test_read_logs(self):
        """ログ読み込み"""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = MemoryAuthorityLogger(log_dir=tmpdir, enabled=True)

            # ログを記録して確定
            log_id = logger.log_soft_conflict(
                action="chatwork_task_create",
                detected_memory_reference="家族との時間を大切に",
                conflict_reason="優先順位との矛盾",
            )
            logger.update_user_response(log_id, "ok")

            # 読み込み
            logs = logger.read_logs()
            assert len(logs) == 1
            assert logs[0].action == "chatwork_task_create"
            assert logs[0].user_response == "ok"

    def test_read_logs_with_action_filter(self):
        """アクションでフィルタリング"""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = MemoryAuthorityLogger(log_dir=tmpdir, enabled=True)

            # 異なるアクションのログ
            for action in ["action1", "action2", "action1"]:
                log_id = logger.log_soft_conflict(action, "ref", "reason")
                logger.update_user_response(log_id, "ok")

            # フィルタリング
            logs = logger.read_logs(action_filter="action1")
            assert len(logs) == 2

    def test_read_logs_with_response_filter(self):
        """応答でフィルタリング"""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = MemoryAuthorityLogger(log_dir=tmpdir, enabled=True)

            # 異なる応答のログ
            for i, response in enumerate(["ok", "modify", "ok"]):
                log_id = logger.log_soft_conflict(f"action{i}", "ref", "reason")
                logger.update_user_response(log_id, response)

            # フィルタリング
            logs = logger.read_logs(response_filter="ok")
            assert len(logs) == 2

    def test_get_statistics(self):
        """統計情報取得"""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = MemoryAuthorityLogger(log_dir=tmpdir, enabled=True)

            # ログを記録
            for i in range(5):
                log_id = logger.log_soft_conflict(
                    action=f"action{i % 2}",
                    detected_memory_reference="ref",
                    conflict_reason="reason",
                    confidence=0.6 + (i * 0.05),
                )
                logger.update_user_response(log_id, "ok" if i % 2 == 0 else "modify")

            stats = logger.get_statistics()
            assert stats["total_count"] == 5
            assert "ok" in stats["response_distribution"]
            assert "modify" in stats["response_distribution"]
            assert stats["avg_confidence"] > 0

    def test_get_statistics_empty(self):
        """空の場合の統計"""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = MemoryAuthorityLogger(log_dir=tmpdir, enabled=True)
            stats = logger.get_statistics()
            assert stats["total_count"] == 0
            assert stats["avg_confidence"] == 0.0


# =============================================================================
# 非同期テスト
# =============================================================================


class TestMemoryAuthorityLoggerAsync:
    """非同期メソッドのテスト"""

    @pytest.mark.asyncio
    async def test_log_soft_conflict_async(self):
        """非同期ログ記録"""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = MemoryAuthorityLogger(log_dir=tmpdir, enabled=True)
            log_id = await logger.log_soft_conflict_async(
                action="async_action",
                detected_memory_reference="async_ref",
                conflict_reason="async_reason",
            )
            assert log_id.startswith("sc_")
            assert log_id in logger._pending_logs

    @pytest.mark.asyncio
    async def test_update_user_response_async(self):
        """非同期でユーザー応答を更新"""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = MemoryAuthorityLogger(log_dir=tmpdir, enabled=True)
            log_id = await logger.log_soft_conflict_async(
                action="async_action",
                detected_memory_reference="async_ref",
                conflict_reason="async_reason",
            )

            result = await logger.update_user_response_async(log_id, "ok")
            assert result is True
            assert log_id not in logger._pending_logs


# =============================================================================
# シングルトン & ファクトリーテスト
# =============================================================================


class TestFactoryFunctions:
    """ファクトリー関数のテスト"""

    def test_get_memory_authority_logger_singleton(self):
        """シングルトンインスタンスを取得"""
        # グローバル状態をリセット
        import lib.brain.memory_authority_logger as mal
        mal._logger_instance = None

        logger1 = get_memory_authority_logger(enabled=True)
        logger2 = get_memory_authority_logger()
        assert logger1 is logger2

    def test_create_memory_authority_logger_new_instance(self):
        """新しいインスタンスを作成"""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger1 = create_memory_authority_logger(log_dir=tmpdir, enabled=True)
            logger2 = create_memory_authority_logger(log_dir=tmpdir, enabled=True)
            assert logger1 is not logger2


# =============================================================================
# エッジケーステスト
# =============================================================================


class TestEdgeCases:
    """エッジケースのテスト"""

    def test_long_memory_reference_truncated(self):
        """長い記憶参照は切り詰められる"""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = MemoryAuthorityLogger(log_dir=tmpdir, enabled=True)
            long_ref = "あ" * 500
            log_id = logger.log_soft_conflict(
                action="action",
                detected_memory_reference=long_ref,
                conflict_reason="reason",
            )
            log = logger._pending_logs[log_id]
            assert len(log.detected_memory_reference) <= 200

    def test_long_message_excerpt_truncated(self):
        """長いメッセージ抜粋は切り詰められる"""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = MemoryAuthorityLogger(log_dir=tmpdir, enabled=True)
            long_msg = "あ" * 500
            log_id = logger.log_soft_conflict(
                action="action",
                detected_memory_reference="ref",
                conflict_reason="reason",
                message_excerpt=long_msg,
            )
            log = logger._pending_logs[log_id]
            assert len(log.message_excerpt) <= 100

    def test_read_logs_nonexistent_file(self):
        """存在しないファイルの読み込み"""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = MemoryAuthorityLogger(log_dir=tmpdir, enabled=True)
            logs = logger.read_logs()
            assert logs == []

    def test_read_logs_corrupted_line(self):
        """破損した行をスキップ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = MemoryAuthorityLogger(log_dir=tmpdir, enabled=True)

            # 正常なログを書き込み
            log_id = logger.log_soft_conflict("action", "ref", "reason")
            logger.update_user_response(log_id, "ok")

            # 破損した行を追加
            with open(logger.log_path, "a") as f:
                f.write("not valid json\n")
                f.write('{"incomplete": true\n')

            # 読み込み（破損行はスキップ）
            logs = logger.read_logs()
            assert len(logs) == 1

    def test_conflict_details_preserved(self):
        """詳細な矛盾情報が保存される"""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = MemoryAuthorityLogger(log_dir=tmpdir, enabled=True)
            details = [
                {"memory_type": "principles", "excerpt": "家族を大切に"},
                {"memory_type": "values", "excerpt": "健康第一"},
            ]
            log_id = logger.log_soft_conflict(
                action="action",
                detected_memory_reference="ref",
                conflict_reason="reason",
                conflict_details=details,
            )
            logger.update_user_response(log_id, "ok")

            logs = logger.read_logs()
            assert len(logs[0].conflict_details) == 2


# =============================================================================
# 統合テスト
# =============================================================================


class TestIntegration:
    """統合テスト"""

    def test_full_workflow(self):
        """完全なワークフロー: ログ → 応答更新 → 読み込み → 統計"""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = MemoryAuthorityLogger(log_dir=tmpdir, enabled=True)

            # 1. 複数のSOFT_CONFLICTをログ
            log_ids = []
            for i in range(10):
                log_id = logger.log_soft_conflict(
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
                logger.update_user_response(log_ids[i], response)

            # 3. 残りをフラッシュ
            flushed = logger.flush_pending(default_response="timeout")
            assert flushed == 5

            # 4. ログ読み込み
            all_logs = logger.read_logs()
            assert len(all_logs) == 10

            # 5. フィルタリング
            ok_logs = logger.read_logs(response_filter="ok")
            assert len(ok_logs) == 2

            action_0_logs = logger.read_logs(action_filter="action_0")
            assert len(action_0_logs) == 4  # 0, 3, 6, 9

            # 6. 統計
            stats = logger.get_statistics()
            assert stats["total_count"] == 10
            assert stats["response_distribution"]["ok"] == 2
            assert stats["response_distribution"]["timeout"] == 5
            assert stats["pending_count"] == 0

    @pytest.mark.asyncio
    async def test_async_non_blocking(self):
        """非同期ログがメイン処理をブロックしないことを確認"""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = MemoryAuthorityLogger(log_dir=tmpdir, enabled=True)

            # 非同期でログ記録
            start = datetime.now()
            tasks = []
            for i in range(100):
                task = logger.log_soft_conflict_async(
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
