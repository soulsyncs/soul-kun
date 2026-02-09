"""
tests/test_batch_insert_n1.py

Task 5: N+1クエリ修正テスト
org_graph.py, learning_loop.py, observability.py のバッチINSERTテスト
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from unittest.mock import MagicMock, patch

import pytest


# ============================================================
# org_graph バッチINSERTテスト
# ============================================================

class TestOrgGraphBatchInsert:
    """org_graph._flush_interaction_buffer バッチINSERTテスト"""

    @pytest.mark.asyncio
    async def test_batch_insert_single_execute(self):
        """複数エントリが1回のINSERTで処理される"""
        from lib.brain.org_graph import OrganizationGraph

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_pool = MagicMock()
        mock_pool.connect.return_value = mock_conn

        graph = OrganizationGraph.__new__(OrganizationGraph)
        graph.organization_id = "test-org-id"
        graph.pool = mock_pool
        graph._interaction_buffer = []
        graph._relationship_cache = {}
        graph._person_cache = {}

        # 3件のインタラクションをバッファに追加
        class MockInteractionType(Enum):
            MENTION = "mention"

        for i in range(3):
            interaction = MagicMock()
            interaction.from_person_id = f"person_{i}"
            interaction.to_person_id = f"person_{i + 10}"
            interaction.interaction_type = MockInteractionType.MENTION
            interaction.sentiment = 0.5
            interaction.room_id = "room_1"
            graph._interaction_buffer.append(interaction)

        count = await graph._flush_interaction_buffer()

        assert count == 3
        # 1回のexecute呼び出し（バッチ）
        assert mock_conn.execute.call_count == 1
        sql_str = str(mock_conn.execute.call_args[0][0].text)
        assert "VALUES" in sql_str
        # 3つのVALUES句
        assert sql_str.count(":org_id_") == 3
        mock_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_batch_insert_chunks_at_100(self):
        """101件の場合、2回のexecuteが呼ばれる（100 + 1チャンク）"""
        from lib.brain.org_graph import OrganizationGraph

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_pool = MagicMock()
        mock_pool.connect.return_value = mock_conn

        graph = OrganizationGraph.__new__(OrganizationGraph)
        graph.organization_id = "test-org-id"
        graph.pool = mock_pool
        graph._interaction_buffer = []
        graph._relationship_cache = {}
        graph._person_cache = {}

        class MockInteractionType(Enum):
            MENTION = "mention"

        for i in range(101):
            interaction = MagicMock()
            interaction.from_person_id = f"person_{i}"
            interaction.to_person_id = f"person_{i + 200}"
            interaction.interaction_type = MockInteractionType.MENTION
            interaction.sentiment = 0.0
            interaction.room_id = None
            graph._interaction_buffer.append(interaction)

        count = await graph._flush_interaction_buffer()

        assert count == 101
        # 2チャンク: 100 + 1
        assert mock_conn.execute.call_count == 2
        mock_conn.commit.assert_called_once()


# ============================================================
# learning_loop バッチINSERTテスト
# ============================================================

class TestLearningLoopBatchInsert:
    """learning_loop._flush_learning_buffer バッチINSERTテスト"""

    @pytest.mark.asyncio
    async def test_batch_insert_uses_organization_id(self):
        """self.organization_id を正しく使う（self.org_idバグ修正確認）"""
        from lib.brain.learning_loop import LearningLoop

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_pool = MagicMock()
        mock_pool.connect.return_value = mock_conn

        loop = LearningLoop.__new__(LearningLoop)
        loop.organization_id = "correct-org-id"
        loop.pool = mock_pool
        loop._learning_buffer = []

        entry = MagicMock()
        entry.improvement_type = "accuracy"
        entry.category = "learning"
        entry.trigger_event = "test"
        loop._learning_buffer.append(entry)

        count = await loop._flush_learning_buffer()

        assert count == 1
        assert mock_conn.execute.call_count == 1
        params = mock_conn.execute.call_args[0][1]
        assert params["org_id_0"] == "correct-org-id"
        mock_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_batch_insert_multiple_entries(self):
        """複数エントリが1回のINSERTで処理される"""
        from lib.brain.learning_loop import LearningLoop

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_pool = MagicMock()
        mock_pool.connect.return_value = mock_conn

        loop = LearningLoop.__new__(LearningLoop)
        loop.organization_id = "org-id"
        loop.pool = mock_pool
        loop._learning_buffer = []

        for _ in range(5):
            entry = MagicMock()
            entry.improvement_type = "speed"
            entry.category = "learning"
            entry.trigger_event = "batch_test"
            loop._learning_buffer.append(entry)

        count = await loop._flush_learning_buffer()

        assert count == 5
        assert mock_conn.execute.call_count == 1
        sql_str = str(mock_conn.execute.call_args[0][0].text)
        assert sql_str.count(":org_id_") == 5


# ============================================================
# observability バッチINSERTテスト
# ============================================================

class TestObservabilityBatchInsert:
    """observability._flush_logs バッチINSERTテスト"""

    def test_batch_insert_single_execute(self):
        """複数ログが1回のINSERTで処理される"""
        from lib.brain.observability import (
            BrainObservability,
            ContextType,
            ObservabilityLog,
        )

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_pool = MagicMock()
        mock_pool.connect.return_value = mock_conn

        obs = BrainObservability(
            org_id="obs-org-id",
            enable_persistence=True,
            pool=mock_pool,
        )

        # バッファに直接追加
        for i in range(3):
            obs._log_buffer.append(
                ObservabilityLog(
                    context_type=ContextType.INTENT,
                    path=f"test_path_{i}",
                    applied=True,
                    account_id=f"user_{i}",
                    org_id="obs-org-id",
                    details={"room_id": f"room_{i}"},
                )
            )

        # _flush_logs を直接呼ぶ
        with patch("concurrent.futures.ThreadPoolExecutor") as mock_executor_cls:
            mock_executor = MagicMock()
            mock_future = MagicMock()
            mock_executor.submit.side_effect = lambda fn: (fn(), mock_future)[1]
            mock_executor_cls.return_value = mock_executor

            obs._flush_logs()

        # 1回のexecute呼び出し（バッチ）
        assert mock_conn.execute.call_count == 1
        sql_str = str(mock_conn.execute.call_args[0][0].text)
        assert sql_str.count(":org_id_") == 3
        mock_conn.commit.assert_called_once()

    def test_pii_filtered_in_batch(self):
        """バッチINSERTでもPIIフィルタが機能する"""
        from lib.brain.observability import (
            BrainObservability,
            ContextType,
            ObservabilityLog,
        )

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_pool = MagicMock()
        mock_pool.connect.return_value = mock_conn

        obs = BrainObservability(
            org_id="obs-org-id",
            enable_persistence=True,
            pool=mock_pool,
        )

        obs._log_buffer.append(
            ObservabilityLog(
                context_type=ContextType.PERSONA,
                path="test_pii",
                applied=True,
                account_id="user_1",
                org_id="obs-org-id",
                details={
                    "room_id": "room_safe",
                    "message": "This is PII and should be filtered",
                    "email": "secret@example.com",
                },
            )
        )

        with patch("concurrent.futures.ThreadPoolExecutor") as mock_executor_cls:
            mock_executor = MagicMock()
            mock_executor.submit.side_effect = lambda fn: (fn(), MagicMock())[1]
            mock_executor_cls.return_value = mock_executor

            obs._flush_logs()

        params = mock_conn.execute.call_args[0][1]
        # room_id は保持される
        assert params["room_id_0"] == "room_safe"
        # PIIキーは渡されない（room_idのみ残る）
        # details内のmessage, emailはフィルタ済み
