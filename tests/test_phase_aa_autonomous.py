# tests/test_phase_aa_autonomous.py
"""Phase AA 自律エージェント基盤のテスト"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from lib.brain.autonomous.task_queue import (
    AutonomousTask,
    TaskQueue,
    TaskStatus,
    TaskType,
)
from lib.brain.autonomous.worker import BaseWorker, StepResult
from lib.brain.autonomous.tool_registry import (
    AvailableTool,
    ToolRegistry,
    create_default_registry,
)


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def mock_pool():
    """モックDBプール"""
    pool = MagicMock()
    conn = MagicMock()
    conn.execute.return_value.mappings.return_value.first.return_value = {
        "id": "task-uuid-123",
        "created_at": datetime.now(),
    }
    conn.execute.return_value.mappings.return_value.all.return_value = []
    pool.connect.return_value.__enter__ = MagicMock(return_value=conn)
    pool.connect.return_value.__exit__ = MagicMock(return_value=False)
    return pool


@pytest.fixture
def task_queue(mock_pool):
    """TaskQueueインスタンス"""
    return TaskQueue(pool=mock_pool, org_id="test-org-uuid")


@pytest.fixture
def sample_task():
    """サンプルタスク"""
    return AutonomousTask(
        title="テストタスク",
        description="テスト用の自律タスク",
        task_type="research",
        priority=3,
        total_steps=3,
        requested_by="user123",
        room_id="room456",
    )


# =========================================================================
# TaskStatus テスト
# =========================================================================


class TestTaskStatus:
    """TaskStatusのテスト"""

    def test_status_values(self):
        """ステータスの値が正しい"""
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.RUNNING == "running"
        assert TaskStatus.COMPLETED == "completed"
        assert TaskStatus.FAILED == "failed"
        assert TaskStatus.CANCELLED == "cancelled"


class TestTaskType:
    """TaskTypeのテスト"""

    def test_type_values(self):
        """タイプの値が正しい"""
        assert TaskType.RESEARCH == "research"
        assert TaskType.REMINDER == "reminder"
        assert TaskType.REPORT == "report"


# =========================================================================
# AutonomousTask テスト
# =========================================================================


class TestAutonomousTask:
    """AutonomousTaskのテスト"""

    def test_default_values(self):
        """デフォルト値が正しい"""
        task = AutonomousTask()
        assert task.id is None
        assert task.status == TaskStatus.PENDING
        assert task.priority == 5
        assert task.progress_pct == 0

    def test_to_dict(self, sample_task):
        """辞書変換"""
        d = sample_task.to_dict()
        assert d["title"] == "テストタスク"
        assert d["task_type"] == "research"
        assert d["priority"] == 3
        assert d["status"] == "pending"


# =========================================================================
# TaskQueue テスト
# =========================================================================


class TestTaskQueue:
    """TaskQueueのテスト"""

    def test_init_requires_org_id(self, mock_pool):
        """org_idは必須"""
        with pytest.raises(ValueError):
            TaskQueue(pool=mock_pool, org_id="")

    def test_init_valid(self, task_queue):
        """正常な初期化"""
        assert task_queue.org_id == "test-org-uuid"

    @pytest.mark.asyncio
    async def test_create_task(self, task_queue, sample_task):
        """タスク作成"""
        result = await task_queue.create(sample_task)
        assert result is not None
        assert result.id == "task-uuid-123"
        assert result.organization_id == "test-org-uuid"

    @pytest.mark.asyncio
    async def test_create_without_pool(self, sample_task):
        """プールなしではNoneを返す"""
        queue = TaskQueue.__new__(TaskQueue)
        queue.pool = None
        queue.org_id = "test"
        result = await queue.create(sample_task)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_task(self, task_queue):
        """タスク取得"""
        conn = task_queue.pool.connect().__enter__()
        conn.execute.return_value.mappings.return_value.first.return_value = {
            "id": "task-uuid-123",
            "organization_id": "test-org-uuid",
            "title": "テスト",
            "task_type": "research",
            "status": "running",
            "priority": 5,
            "progress_pct": 50,
            "current_step": 1,
            "total_steps": 2,
        }

        result = await task_queue.get("task-uuid-123")
        assert result is not None
        assert result.status == TaskStatus.RUNNING

    @pytest.mark.asyncio
    async def test_get_task_not_found(self, task_queue):
        """タスクが見つからない"""
        conn = task_queue.pool.connect().__enter__()
        conn.execute.return_value.mappings.return_value.first.return_value = None

        result = await task_queue.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_status(self, task_queue):
        """ステータス更新"""
        result = await task_queue.update(
            "task-uuid-123",
            status=TaskStatus.RUNNING,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_update_progress(self, task_queue):
        """進捗更新"""
        result = await task_queue.update(
            "task-uuid-123",
            progress_pct=50,
            current_step=2,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_update_no_changes(self, task_queue):
        """変更なしは成功を返す"""
        result = await task_queue.update("task-uuid-123")
        assert result is True

    @pytest.mark.asyncio
    async def test_list_tasks_empty(self, task_queue):
        """空のリスト"""
        result = await task_queue.list_tasks()
        assert result == []

    @pytest.mark.asyncio
    async def test_list_tasks_with_status_filter(self, task_queue):
        """ステータスフィルタ付きリスト"""
        result = await task_queue.list_tasks(status=TaskStatus.PENDING)
        assert isinstance(result, list)


# =========================================================================
# BaseWorker テスト
# =========================================================================


class ConcreteWorker(BaseWorker):
    """テスト用の具象ワーカー"""
    async def execute(self, task):
        await self.report_progress(task, 1, "Step 1")
        return {"result": "done"}


class FailingWorker(BaseWorker):
    """テスト用の失敗ワーカー"""
    async def execute(self, task):
        raise ValueError("Test error")


class TestBaseWorker:
    """BaseWorkerのテスト"""

    @pytest.mark.asyncio
    async def test_run_success(self, task_queue, sample_task):
        """正常実行"""
        sample_task.id = "task-uuid-123"
        worker = ConcreteWorker(task_queue=task_queue)
        result = await worker.run(sample_task)
        assert result == {"result": "done"}

    @pytest.mark.asyncio
    async def test_run_failure(self, task_queue, sample_task):
        """失敗実行"""
        sample_task.id = "task-uuid-123"
        worker = FailingWorker(task_queue=task_queue)
        result = await worker.run(sample_task)
        assert result == {"error": "ValueError"}

    @pytest.mark.asyncio
    async def test_report_progress(self, task_queue, sample_task):
        """進捗報告"""
        sample_task.id = "task-uuid-123"
        sample_task.total_steps = 4
        worker = ConcreteWorker(task_queue=task_queue)
        await worker.report_progress(sample_task, 2, "halfway")
        # update が呼ばれたことの確認（例外なし）

    @pytest.mark.asyncio
    async def test_handle_error(self, task_queue, sample_task):
        """エラーハンドリング"""
        sample_task.id = "task-uuid-123"
        worker = ConcreteWorker(task_queue=task_queue)
        await worker.handle_error(sample_task, RuntimeError("test"))
        # update が呼ばれたことの確認（例外なし）


class TestStepResult:
    """StepResultのテスト"""

    def test_success(self):
        """成功結果"""
        result = StepResult(success=True, output={"data": 1})
        assert result.success is True
        assert result.error is None

    def test_failure(self):
        """失敗結果"""
        result = StepResult(success=False, output={}, error="Something wrong")
        assert result.success is False
        assert result.error == "Something wrong"


# =========================================================================
# ToolRegistry テスト
# =========================================================================


class TestToolRegistry:
    """ToolRegistryのテスト"""

    def test_register_and_get(self):
        """登録と取得"""
        registry = ToolRegistry()
        tool = AvailableTool(
            name="test_tool",
            description="テストツール",
            category="test",
        )
        registry.register(tool)
        assert registry.get("test_tool") is tool
        assert registry.count == 1

    def test_get_nonexistent(self):
        """存在しないツール"""
        registry = ToolRegistry()
        assert registry.get("nonexistent") is None

    def test_list_all(self):
        """全ツールリスト"""
        registry = ToolRegistry()
        registry.register(AvailableTool(name="a", description="A", category="x"))
        registry.register(AvailableTool(name="b", description="B", category="y"))
        assert len(registry.list_tools()) == 2

    def test_list_by_category(self):
        """カテゴリフィルタ"""
        registry = ToolRegistry()
        registry.register(AvailableTool(name="a", description="A", category="x"))
        registry.register(AvailableTool(name="b", description="B", category="y"))
        registry.register(AvailableTool(name="c", description="C", category="x"))
        assert len(registry.list_tools(category="x")) == 2
        assert len(registry.list_tools(category="y")) == 1

    def test_list_for_llm(self):
        """LLM用リスト"""
        registry = ToolRegistry()
        registry.register(AvailableTool(
            name="test",
            description="Test tool",
            required_params=["query"],
        ))
        llm_list = registry.list_for_llm()
        assert len(llm_list) == 1
        assert llm_list[0]["name"] == "test"
        assert "handler" not in llm_list[0]


class TestAvailableTool:
    """AvailableToolのテスト"""

    def test_default_values(self):
        """デフォルト値"""
        tool = AvailableTool(name="t", description="d")
        assert tool.category == "general"
        assert tool.requires_confirmation is False
        assert tool.max_execution_time_sec == 60

    def test_to_dict(self):
        """辞書変換"""
        tool = AvailableTool(
            name="search",
            description="検索",
            category="research",
            required_params=["query"],
            requires_confirmation=True,
        )
        d = tool.to_dict()
        assert d["name"] == "search"
        assert d["requires_confirmation"] is True
        assert "handler" not in d
        assert "max_execution_time_sec" not in d


class TestCreateDefaultRegistry:
    """create_default_registryのテスト"""

    def test_creates_registry(self):
        """デフォルトレジストリが作成される"""
        registry = create_default_registry()
        assert registry.count >= 7

    def test_has_knowledge_search(self):
        """knowledge_searchが登録されている"""
        registry = create_default_registry()
        tool = registry.get("knowledge_search")
        assert tool is not None
        assert tool.category == "research"
        assert "query" in tool.required_params

    def test_send_message_requires_confirmation(self):
        """send_messageは確認が必要"""
        registry = create_default_registry()
        tool = registry.get("send_message")
        assert tool is not None
        assert tool.requires_confirmation is True

    def test_all_categories(self):
        """全カテゴリが存在する"""
        registry = create_default_registry()
        categories = {t.category for t in registry.list_tools()}
        assert "research" in categories
        assert "communication" in categories
        assert "analysis" in categories
        assert "management" in categories
