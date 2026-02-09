# tests/test_autonomous_workers.py
"""
Task AA: 自律タスクワーカーテスト

WorkerRegistry, ResearchWorker, ReminderWorker, ReportWorker のテスト。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from lib.brain.autonomous.task_queue import AutonomousTask, TaskQueue, TaskStatus
from lib.brain.autonomous.worker_registry import WorkerRegistry
from lib.brain.autonomous.research_worker import ResearchWorker
from lib.brain.autonomous.reminder_worker import ReminderWorker
from lib.brain.autonomous.report_worker import ReportWorker


# =============================================================================
# ヘルパー
# =============================================================================


def _make_task(**kwargs) -> AutonomousTask:
    """テスト用タスクを作成"""
    defaults = {
        "id": "task-001",
        "organization_id": "org-test",
        "title": "テストタスク",
        "description": "テスト用",
        "task_type": "research",
        "status": TaskStatus.PENDING,
        "room_id": "room-123",
    }
    defaults.update(kwargs)
    return AutonomousTask(**defaults)


def _make_queue() -> MagicMock:
    """モックTaskQueueを作成"""
    queue = MagicMock(spec=TaskQueue)
    queue.update = AsyncMock(return_value=True)
    return queue


# =============================================================================
# WorkerRegistry
# =============================================================================


class TestWorkerRegistry:
    """WorkerRegistryのテスト"""

    def test_register_and_get(self):
        """ワーカーを登録して取得できる"""
        queue = _make_queue()
        registry = WorkerRegistry(task_queue=queue)
        registry.register("research", ResearchWorker)

        worker = registry.get_worker("research")
        assert worker is not None
        assert isinstance(worker, ResearchWorker)

    def test_get_unknown_type(self):
        """未登録タイプはNoneを返す"""
        queue = _make_queue()
        registry = WorkerRegistry(task_queue=queue)

        worker = registry.get_worker("nonexistent")
        assert worker is None

    def test_instance_caching(self):
        """同じタイプは同じインスタンスを返す"""
        queue = _make_queue()
        registry = WorkerRegistry(task_queue=queue)
        registry.register("reminder", ReminderWorker)

        w1 = registry.get_worker("reminder")
        w2 = registry.get_worker("reminder")
        assert w1 is w2

    def test_list_types(self):
        """登録済みタスクタイプ一覧"""
        queue = _make_queue()
        registry = WorkerRegistry(task_queue=queue)
        registry.register("research", ResearchWorker)
        registry.register("reminder", ReminderWorker)
        registry.register("report", ReportWorker)

        types = registry.list_types()
        assert set(types) == {"research", "reminder", "report"}


# =============================================================================
# ResearchWorker
# =============================================================================


class TestResearchWorker:
    """ResearchWorkerのテスト"""

    @pytest.mark.asyncio
    async def test_execute_without_pool(self):
        """pool無しの場合、空のナレッジ結果"""
        queue = _make_queue()
        worker = ResearchWorker(task_queue=queue, pool=None)
        task = _make_task(
            execution_plan={"query": "テスト検索"},
        )

        result = await worker.execute(task)

        assert result is not None
        assert result["query"] == "テスト検索"
        assert result["results_count"] == 0
        assert "見つかりませんでした" in result["synthesis"]

    @pytest.mark.asyncio
    async def test_execute_reports_progress(self):
        """進捗が3ステップ報告される"""
        queue = _make_queue()
        worker = ResearchWorker(task_queue=queue, pool=None)
        task = _make_task(execution_plan={"query": "test"})

        await worker.execute(task)

        assert task.total_steps == 3
        # update is called for each step's progress report
        assert queue.update.call_count == 3

    @pytest.mark.asyncio
    async def test_synthesize_with_results(self):
        """検索結果がある場合の合成"""
        queue = _make_queue()
        worker = ResearchWorker(task_queue=queue, pool=None)

        results = [
            {"title": "ガイド1", "content": "テスト内容です"},
            {"title": "ガイド2", "content": "追加情報です"},
        ]
        synthesis = worker._synthesize("テスト", results)
        assert "ガイド1" in synthesis
        assert "ガイド2" in synthesis
        assert "テスト" in synthesis


# =============================================================================
# ReminderWorker
# =============================================================================


class TestReminderWorker:
    """ReminderWorkerのテスト"""

    @pytest.mark.asyncio
    async def test_unconfirmed_returns_awaiting(self):
        """未確認の場合はawaiting_confirmationを返す"""
        queue = _make_queue()
        worker = ReminderWorker(task_queue=queue, send_func=AsyncMock())
        task = _make_task(
            execution_plan={
                "message": "テストリマインダー",
                "confirmed": False,
            },
        )

        result = await worker.execute(task)

        assert result["status"] == "awaiting_confirmation"
        assert result["message_preview"] == "テストリマインダー"

    @pytest.mark.asyncio
    async def test_confirmed_sends_message(self):
        """確認済みの場合はメッセージを送信"""
        send_func = AsyncMock()
        queue = _make_queue()
        worker = ReminderWorker(task_queue=queue, send_func=send_func)
        task = _make_task(
            execution_plan={
                "message": "リマインダーメッセージ",
                "room_id": "room-456",
                "confirmed": True,
            },
        )

        result = await worker.execute(task)

        assert result["status"] == "sent"
        assert result["message_length"] == len("リマインダーメッセージ")
        send_func.assert_called_once_with(
            room_id="room-456",
            message="リマインダーメッセージ",
        )

    @pytest.mark.asyncio
    async def test_send_fails_gracefully(self):
        """送信失敗時はsend_failedを返す"""
        send_func = AsyncMock(side_effect=RuntimeError("send error"))
        queue = _make_queue()
        worker = ReminderWorker(task_queue=queue, send_func=send_func)
        task = _make_task(
            execution_plan={"message": "test", "confirmed": True},
        )

        result = await worker.execute(task)

        assert result["status"] == "send_failed"

    @pytest.mark.asyncio
    async def test_no_send_func(self):
        """send_funcが無い場合はsend_failed"""
        queue = _make_queue()
        worker = ReminderWorker(task_queue=queue, send_func=None)
        task = _make_task(
            execution_plan={"message": "test", "confirmed": True},
        )

        result = await worker.execute(task)

        assert result["status"] == "send_failed"


# =============================================================================
# ReportWorker
# =============================================================================


class TestReportWorker:
    """ReportWorkerのテスト"""

    @pytest.mark.asyncio
    async def test_execute_without_pool(self):
        """pool無しの場合、データなしレポート"""
        send_func = AsyncMock()
        queue = _make_queue()
        worker = ReportWorker(task_queue=queue, pool=None, send_func=send_func)
        task = _make_task(
            execution_plan={"report_type": "daily_summary"},
        )

        result = await worker.execute(task)

        assert result is not None
        assert result["report_type"] == "daily_summary"
        assert result["data_points"] == 0
        assert result["sent"] is True
        assert "データがありません" in result["report_preview"]

    @pytest.mark.asyncio
    async def test_generate_report_with_data(self):
        """データがある場合のレポート生成"""
        queue = _make_queue()
        worker = ReportWorker(task_queue=queue, pool=None)

        data = {
            "call_count": 100,
            "total_tokens": 50000,
            "total_cost": 1234.5,
            "error_count": 2,
            "total_decisions": 50,
        }

        report = worker._generate_report("daily_summary", data)
        assert "API呼出数: 100" in report
        assert "50,000" in report
        assert "1234円" in report
        assert "エラー率: 4.0%" in report

    @pytest.mark.asyncio
    async def test_execute_no_send_func(self):
        """send_funcが無い場合は送信失敗"""
        queue = _make_queue()
        worker = ReportWorker(task_queue=queue, pool=None, send_func=None)
        task = _make_task(
            execution_plan={"report_type": "daily_summary"},
        )

        result = await worker.execute(task)

        assert result["sent"] is False

    @pytest.mark.asyncio
    async def test_report_empty_data(self):
        """空データの場合のレポート"""
        queue = _make_queue()
        worker = ReportWorker(task_queue=queue, pool=None)

        report = worker._generate_report("weekly", {})
        assert "データがありません" in report
