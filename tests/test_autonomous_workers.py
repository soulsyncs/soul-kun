# tests/test_autonomous_workers.py
"""
Task AA: 自律タスクワーカーテスト

WorkerRegistry, ResearchWorker, ReminderWorker, ReportWorker のテスト。
DB経路モックテスト + 冪等性テスト + TaskQueue.claimテスト含む。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from lib.brain.autonomous.task_queue import AutonomousTask, TaskQueue, TaskStatus
from lib.brain.autonomous.worker import BaseWorker
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
    queue.claim = AsyncMock(return_value=True)
    return queue


def _make_mock_pool(rows=None, mappings_result=None):
    """DB接続プールのモックを作成"""
    mock_result = MagicMock()
    if mappings_result is not None:
        mock_result.mappings.return_value.all.return_value = mappings_result
        mock_result.mappings.return_value.first.return_value = (
            mappings_result[0] if mappings_result else None
        )
    elif rows is not None:
        mock_result.mappings.return_value.all.return_value = rows
        mock_result.mappings.return_value.first.return_value = (
            rows[0] if rows else None
        )
    else:
        mock_result.mappings.return_value.all.return_value = []
        mock_result.mappings.return_value.first.return_value = None

    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_result

    mock_pool = MagicMock()
    mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)

    return mock_pool, mock_conn


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
        assert result["synthesis_length"] > 0

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

    @pytest.mark.asyncio
    async def test_missing_organization_id(self):
        """organization_idが空の場合はエラーを返す"""
        queue = _make_queue()
        worker = ResearchWorker(task_queue=queue, pool=None)
        task = _make_task(organization_id="")

        result = await worker.execute(task)

        assert result["error"] == "missing_organization_id"


# =============================================================================
# ReminderWorker
# =============================================================================


class TestReminderWorker:
    """ReminderWorkerのテスト"""

    @pytest.mark.asyncio
    async def test_unconfirmed_returns_awaiting(self):
        """未確認の場合はawaiting_confirmationを返す"""
        queue = _make_queue()
        worker = ReminderWorker(task_queue=queue)
        task = _make_task(
            execution_plan={
                "message": "テストリマインダー",
                "confirmed": False,
            },
        )

        result = await worker.execute(task)

        assert result["status"] == "awaiting_confirmation"
        assert result["message_length"] == len("テストリマインダー")

    @pytest.mark.asyncio
    async def test_confirmed_returns_ready(self):
        """確認済みの場合はreadyステータスを返す（送信はBrain責務）"""
        queue = _make_queue()
        worker = ReminderWorker(task_queue=queue)
        task = _make_task(
            execution_plan={
                "message": "リマインダーメッセージ",
                "room_id": "room-456",
                "confirmed": True,
            },
        )

        result = await worker.execute(task)

        assert result["status"] == "ready"
        assert result["message_length"] == len("リマインダーメッセージ")
        assert result["room_id"] == "room-456"

    @pytest.mark.asyncio
    async def test_none_message_fallback(self):
        """messageがNoneの場合、descriptionにフォールバック"""
        queue = _make_queue()
        worker = ReminderWorker(task_queue=queue)
        task = _make_task(
            description="フォールバックメッセージ",
            execution_plan={"confirmed": True},
        )

        result = await worker.execute(task)

        assert result["status"] == "ready"
        assert result["message_length"] == len("フォールバックメッセージ")

    @pytest.mark.asyncio
    async def test_none_message_and_description(self):
        """message/descriptionが両方Noneの場合、空文字で安全"""
        queue = _make_queue()
        worker = ReminderWorker(task_queue=queue)
        task = _make_task(
            description=None,
            execution_plan={"confirmed": True},
        )

        result = await worker.execute(task)

        assert result["status"] == "ready"
        assert result["message_length"] == 0

    @pytest.mark.asyncio
    async def test_missing_organization_id(self):
        """organization_idが空の場合はエラーを返す"""
        queue = _make_queue()
        worker = ReminderWorker(task_queue=queue)
        task = _make_task(organization_id="")

        result = await worker.execute(task)

        assert result["error"] == "missing_organization_id"


# =============================================================================
# ReportWorker
# =============================================================================


class TestReportWorker:
    """ReportWorkerのテスト"""

    @pytest.mark.asyncio
    async def test_execute_without_pool(self):
        """pool無しの場合、データなしレポート"""
        queue = _make_queue()
        worker = ReportWorker(task_queue=queue, pool=None)
        task = _make_task(
            execution_plan={"report_type": "daily_summary"},
        )

        result = await worker.execute(task)

        assert result is not None
        assert result["report_type"] == "daily_summary"
        assert result["data_points"] == 0
        assert result["status"] == "ready"
        assert result["report_length"] > 0

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
        assert "日次レポート" in report

    @pytest.mark.asyncio
    async def test_generate_report_weekly(self):
        """週次レポートのタイトルが正しい"""
        queue = _make_queue()
        worker = ReportWorker(task_queue=queue, pool=None)

        data = {"call_count": 10, "total_tokens": 1000, "total_cost": 100,
                "error_count": 0, "total_decisions": 5}
        report = worker._generate_report("weekly_summary", data)
        assert "週次レポート" in report

    @pytest.mark.asyncio
    async def test_report_empty_data(self):
        """空データの場合のレポート"""
        queue = _make_queue()
        worker = ReportWorker(task_queue=queue, pool=None)

        report = worker._generate_report("weekly", {})
        assert "データがありません" in report

    @pytest.mark.asyncio
    async def test_missing_organization_id(self):
        """organization_idが空の場合はエラーを返す"""
        queue = _make_queue()
        worker = ReportWorker(task_queue=queue, pool=None)
        task = _make_task(organization_id="")

        result = await worker.execute(task)

        assert result["error"] == "missing_organization_id"


# =============================================================================
# ResearchWorker DB経路テスト (A.4)
# =============================================================================


class TestResearchWorkerDB:
    """ResearchWorker DB経路テスト"""

    @pytest.mark.asyncio
    async def test_search_knowledge_with_pool(self):
        """DB経由でナレッジ検索が実行される"""
        db_rows = [
            {"title": "ナレッジ1", "content": "テスト内容1"},
            {"title": "ナレッジ2", "content": "テスト内容2"},
        ]
        mock_pool, mock_conn = _make_mock_pool(mappings_result=db_rows)
        queue = _make_queue()
        worker = ResearchWorker(task_queue=queue, pool=mock_pool)

        results = await worker._search_knowledge(
            query="テスト",
            organization_id="org-test",
            max_results=5,
        )

        assert len(results) == 2
        assert results[0]["title"] == "ナレッジ1"
        assert results[1]["title"] == "ナレッジ2"
        # set_config が呼ばれていることを確認
        assert mock_conn.execute.call_count >= 2

    @pytest.mark.asyncio
    async def test_search_knowledge_empty_result(self):
        """DB検索結果が空の場合"""
        mock_pool, _ = _make_mock_pool(mappings_result=[])
        queue = _make_queue()
        worker = ResearchWorker(task_queue=queue, pool=mock_pool)

        results = await worker._search_knowledge(
            query="存在しないクエリ",
            organization_id="org-test",
        )

        assert results == []

    @pytest.mark.asyncio
    async def test_search_knowledge_db_error(self):
        """DB例外時は空リストを返す"""
        mock_pool = MagicMock()
        mock_pool.connect.side_effect = RuntimeError("connection error")
        queue = _make_queue()
        worker = ResearchWorker(task_queue=queue, pool=mock_pool)

        results = await worker._search_knowledge(
            query="test",
            organization_id="org-test",
        )

        assert results == []

    @pytest.mark.asyncio
    async def test_execute_with_pool_returns_results(self):
        """pool有りでexecute: ナレッジ結果を含む"""
        db_rows = [
            {"title": "手順書", "content": "手順の内容"},
        ]
        mock_pool, _ = _make_mock_pool(mappings_result=db_rows)
        queue = _make_queue()
        worker = ResearchWorker(task_queue=queue, pool=mock_pool)
        task = _make_task(execution_plan={"query": "手順"})

        result = await worker.execute(task)

        assert result["results_count"] == 1
        assert result["synthesis_length"] > 0


# =============================================================================
# ReportWorker DB経路テスト (A.4)
# =============================================================================


class TestReportWorkerDB:
    """ReportWorker DB経路テスト"""

    @pytest.mark.asyncio
    async def test_collect_data_with_pool(self):
        """DB経由でレポートデータを収集"""
        usage_row = {
            "call_count": 42,
            "total_tokens": 10000,
            "total_cost": 500.0,
        }
        error_row = {
            "errors": 3,
            "total": 100,
        }

        mock_conn = MagicMock()
        call_count = {"n": 0}

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            result = MagicMock()
            if call_count["n"] == 1:
                return result
            elif call_count["n"] == 2:
                result.mappings.return_value.first.return_value = usage_row
                return result
            else:
                result.mappings.return_value.first.return_value = error_row
                return result

        mock_conn.execute.side_effect = side_effect

        mock_pool = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)

        queue = _make_queue()
        worker = ReportWorker(task_queue=queue, pool=mock_pool)

        data = await worker._collect_data(
            organization_id="org-test",
            report_type="daily_summary",
        )

        assert data["call_count"] == 42
        assert data["total_tokens"] == 10000
        assert data["total_cost"] == 500.0
        assert data["error_count"] == 3
        assert data["total_decisions"] == 100

    @pytest.mark.asyncio
    async def test_collect_data_db_error(self):
        """DB例外時は空辞書を返す"""
        mock_pool = MagicMock()
        mock_pool.connect.side_effect = RuntimeError("connection error")
        queue = _make_queue()
        worker = ReportWorker(task_queue=queue, pool=mock_pool)

        data = await worker._collect_data(
            organization_id="org-test",
            report_type="daily_summary",
        )

        assert data == {}

    @pytest.mark.asyncio
    async def test_execute_with_pool_returns_ready(self):
        """pool有りでフルパイプライン実行（送信なし）"""
        usage_row = {
            "call_count": 10,
            "total_tokens": 5000,
            "total_cost": 250.0,
        }
        error_row = {"errors": 1, "total": 20}

        mock_conn = MagicMock()
        call_count = {"n": 0}

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            result = MagicMock()
            if call_count["n"] == 1:
                return result
            elif call_count["n"] == 2:
                result.mappings.return_value.first.return_value = usage_row
                return result
            else:
                result.mappings.return_value.first.return_value = error_row
                return result

        mock_conn.execute.side_effect = side_effect

        mock_pool = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)

        queue = _make_queue()
        worker = ReportWorker(task_queue=queue, pool=mock_pool)
        task = _make_task(execution_plan={"report_type": "daily_summary"})

        result = await worker.execute(task)

        assert result["status"] == "ready"
        assert result["data_points"] == 5
        assert result["report_length"] > 0


# =============================================================================
# 冪等性テスト (C.14)
# =============================================================================


class TestIdempotency:
    """BaseWorker.run() の冪等性テスト"""

    @pytest.mark.asyncio
    async def test_completed_task_skipped(self):
        """COMPLETED状態のタスクはスキップされる"""
        queue = _make_queue()
        worker = ResearchWorker(task_queue=queue, pool=None)
        task = _make_task(
            status=TaskStatus.COMPLETED,
            result={"already": "done"},
        )

        result = await worker.run(task)

        assert result == {"already": "done"}
        queue.claim.assert_not_called()

    @pytest.mark.asyncio
    async def test_cancelled_task_skipped(self):
        """CANCELLED状態のタスクはスキップされる"""
        queue = _make_queue()
        worker = ResearchWorker(task_queue=queue, pool=None)
        task = _make_task(status=TaskStatus.CANCELLED)

        result = await worker.run(task)

        assert result == {}
        queue.claim.assert_not_called()

    @pytest.mark.asyncio
    async def test_claim_failure_returns_skipped(self):
        """claimに失敗した場合はskippedを返す"""
        queue = _make_queue()
        queue.claim = AsyncMock(return_value=False)
        worker = ResearchWorker(task_queue=queue, pool=None)
        task = _make_task(status=TaskStatus.PENDING)

        result = await worker.run(task)

        assert result["skipped"] is True
        assert result["reason"] == "already_processed"

    @pytest.mark.asyncio
    async def test_claim_success_executes(self):
        """claimに成功した場合は正常に実行される"""
        queue = _make_queue()
        queue.claim = AsyncMock(return_value=True)
        worker = ResearchWorker(task_queue=queue, pool=None)
        task = _make_task(
            status=TaskStatus.PENDING,
            execution_plan={"query": "テスト"},
        )

        result = await worker.run(task)

        assert result["query"] == "テスト"
        queue.claim.assert_called_once_with("task-001")
        # COMPLETED update が呼ばれる
        update_calls = [
            c for c in queue.update.call_args_list
            if c.kwargs.get("status") == TaskStatus.COMPLETED
            or (len(c.args) > 1 and c.args[1] == TaskStatus.COMPLETED)
        ]
        assert len(update_calls) >= 1


# =============================================================================
# TaskQueue.claim 直接テスト (C.14)
# =============================================================================


class TestTaskQueueClaim:
    """TaskQueue.claim() の直接テスト"""

    @pytest.mark.asyncio
    async def test_claim_success_pending(self):
        """pending状態のタスクをclaimできる"""
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = {"id": "task-001"}
        mock_conn.execute.return_value = mock_result

        mock_pool = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)

        tq = TaskQueue(pool=mock_pool, org_id="org-test")
        result = await tq.claim("task-001")

        assert result is True
        mock_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_claim_fail_already_running(self):
        """既にrunning/completedの場合はclaimに失敗"""
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = None  # 0 rows
        mock_conn.execute.return_value = mock_result

        mock_pool = MagicMock()
        mock_pool.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = MagicMock(return_value=False)

        tq = TaskQueue(pool=mock_pool, org_id="org-test")
        result = await tq.claim("task-001")

        assert result is False

    @pytest.mark.asyncio
    async def test_claim_db_error(self):
        """DB例外時はFalseを返す"""
        mock_pool = MagicMock()
        mock_pool.connect.side_effect = RuntimeError("connection error")

        tq = TaskQueue(pool=mock_pool, org_id="org-test")
        result = await tq.claim("task-001")

        assert result is False

    @pytest.mark.asyncio
    async def test_claim_no_pool(self):
        """pool無しの場合はFalseを返す"""
        tq = TaskQueue(pool=None, org_id="org-test")
        result = await tq.claim("task-001")

        assert result is False
