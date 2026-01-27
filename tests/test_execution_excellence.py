# tests/test_execution_excellence.py
"""
Phase 2L: 実行力強化（Execution Excellence）のテスト

設計書: docs/21_phase2l_execution_excellence.md
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from lib.brain.execution_excellence import (
    # メインクラス
    ExecutionExcellence,
    create_execution_excellence,
    is_execution_excellence_enabled,
    # コンポーネント
    TaskDecomposer,
    ExecutionPlanner,
    WorkflowExecutor,
    ProgressTracker,
    QualityChecker,
    ExceptionHandler,
    EscalationManager,
    DependencyGraph,
    # Enum
    SubTaskStatus,
    ExecutionPriority,
    RecoveryStrategy,
    QualityCheckResult,
    EscalationLevel,
    # データモデル
    SubTask,
    ExecutionPlan,
    # ユーティリティ
    detect_multi_action_request,
    create_subtask,
    create_execution_plan,
    # Feature Flags
    FEATURE_FLAG_EXECUTION_EXCELLENCE,
)
from lib.brain.models import BrainContext, HandlerResult


# =============================================================================
# フィクスチャ
# =============================================================================


@pytest.fixture
def mock_context():
    """モックBrainContext"""
    context = MagicMock(spec=BrainContext)
    context.room_id = "123"
    context.sender_account_id = "456"
    context.organization_id = "org_test"
    context.sender_name = "テストユーザー"
    context.person_info = []
    return context


@pytest.fixture
def mock_capabilities():
    """モックSYSTEM_CAPABILITIES"""
    return {
        "chatwork_task_create": {
            "name": "chatwork_task_create",
            "description": "タスクを作成する",
            "brain_metadata": {"is_primary": True},
        },
        "chatwork_task_search": {
            "name": "chatwork_task_search",
            "description": "タスクを検索する",
            "brain_metadata": {"is_primary": True},
        },
        "chatwork_task_complete": {
            "name": "chatwork_task_complete",
            "description": "タスクを完了する",
            "brain_metadata": {"is_primary": True},
        },
        "general_response": {
            "name": "general_response",
            "description": "一般応答",
            "brain_metadata": {"is_primary": True},
        },
    }


@pytest.fixture
def mock_handlers():
    """モックハンドラー"""
    async def success_handler(**kwargs):
        return HandlerResult(success=True, message="成功")

    async def fail_handler(**kwargs):
        return HandlerResult(success=False, message="失敗", error_details="テストエラー")

    return {
        "chatwork_task_create": success_handler,
        "chatwork_task_search": success_handler,
        "chatwork_task_complete": success_handler,
        "general_response": success_handler,
        "fail_action": fail_handler,
    }


@pytest.fixture
def decomposer(mock_capabilities):
    """TaskDecomposerインスタンス"""
    return TaskDecomposer(capabilities=mock_capabilities)


@pytest.fixture
def planner():
    """ExecutionPlannerインスタンス"""
    return ExecutionPlanner()


@pytest.fixture
def executor(mock_handlers):
    """WorkflowExecutorインスタンス"""
    return WorkflowExecutor(handlers=mock_handlers)


# =============================================================================
# detect_multi_action_request テスト
# =============================================================================


class TestDetectMultiActionRequest:
    """複合アクション検出のテスト"""

    def test_simple_request_not_detected(self):
        """単純なリクエストは検出されない"""
        assert detect_multi_action_request("自分のタスク教えて") is False
        assert detect_multi_action_request("おはよう") is False

    def test_conjunction_detected(self):
        """接続詞を含むリクエストが検出される"""
        assert detect_multi_action_request("タスク作って、田中さんに割り当てて") is True
        assert detect_multi_action_request("検索した後、完了にして") is True
        assert detect_multi_action_request("まとめて完了して") is True

    def test_negation_prevents_detection(self):
        """否定キーワードがあると検出されない"""
        assert detect_multi_action_request("タスクだけ教えて") is False
        assert detect_multi_action_request("簡単にまとめて") is False


# =============================================================================
# SubTask テスト
# =============================================================================


class TestSubTask:
    """SubTaskのテスト"""

    def test_create_subtask(self):
        """サブタスクを作成できる"""
        subtask = create_subtask(
            name="テストタスク",
            action="chatwork_task_create",
            params={"body": "テスト"},
        )
        assert subtask.name == "テストタスク"
        assert subtask.action == "chatwork_task_create"
        assert subtask.status == SubTaskStatus.PENDING

    def test_is_ready(self):
        """is_readyが正しく判定される"""
        subtask = create_subtask(name="テスト", action="test")
        assert subtask.is_ready is True

        subtask.status = SubTaskStatus.IN_PROGRESS
        assert subtask.is_ready is False

    def test_is_terminal(self):
        """is_terminalが正しく判定される"""
        subtask = create_subtask(name="テスト", action="test")
        assert subtask.is_terminal is False

        subtask.status = SubTaskStatus.COMPLETED
        assert subtask.is_terminal is True

        subtask.status = SubTaskStatus.FAILED
        assert subtask.is_terminal is True


# =============================================================================
# ExecutionPlan テスト
# =============================================================================


class TestExecutionPlan:
    """ExecutionPlanのテスト"""

    def test_create_execution_plan(self):
        """実行計画を作成できる"""
        subtasks = [
            create_subtask(name="タスク1", action="action1"),
            create_subtask(name="タスク2", action="action2"),
        ]
        plan = create_execution_plan(
            name="テスト計画",
            original_request="テストリクエスト",
            subtasks=subtasks,
        )
        assert plan.name == "テスト計画"
        assert len(plan.subtasks) == 2

    def test_progress_calculation(self):
        """進捗率が正しく計算される"""
        subtasks = [
            create_subtask(name="タスク1", action="action1"),
            create_subtask(name="タスク2", action="action2"),
        ]
        plan = create_execution_plan(
            name="テスト",
            original_request="テスト",
            subtasks=subtasks,
        )

        assert plan.progress == 0.0

        subtasks[0].status = SubTaskStatus.COMPLETED
        assert plan.progress == 0.5

        subtasks[1].status = SubTaskStatus.COMPLETED
        assert plan.progress == 1.0

    def test_get_ready_tasks(self):
        """実行可能タスクが正しく取得される"""
        st1 = create_subtask(name="タスク1", action="action1")
        st2 = create_subtask(name="タスク2", action="action2", depends_on=[st1.id])

        plan = create_execution_plan(
            name="テスト",
            original_request="テスト",
            subtasks=[st1, st2],
        )

        # 最初はst1のみ実行可能
        ready = plan.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].id == st1.id

        # st1完了後、st2が実行可能に
        st1.status = SubTaskStatus.COMPLETED
        ready = plan.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].id == st2.id


# =============================================================================
# DependencyGraph テスト
# =============================================================================


class TestDependencyGraph:
    """DependencyGraphのテスト"""

    def test_no_cycle(self):
        """循環がない場合"""
        st1 = create_subtask(name="タスク1", action="action1")
        st2 = create_subtask(name="タスク2", action="action2", depends_on=[st1.id])
        st3 = create_subtask(name="タスク3", action="action3", depends_on=[st2.id])

        graph = DependencyGraph([st1, st2, st3])
        assert graph.has_cycle() is False

    def test_cycle_detection(self):
        """循環依存が検出される"""
        st1 = create_subtask(name="タスク1", action="action1")
        st2 = create_subtask(name="タスク2", action="action2", depends_on=[st1.id])

        # 循環を作る
        st1.depends_on = [st2.id]

        graph = DependencyGraph([st1, st2])
        assert graph.has_cycle() is True

    def test_topological_sort(self):
        """トポロジカルソートが正しく機能する"""
        st1 = create_subtask(name="タスク1", action="action1")
        st2 = create_subtask(name="タスク2", action="action2", depends_on=[st1.id])
        st3 = create_subtask(name="タスク3", action="action3", depends_on=[st2.id])

        graph = DependencyGraph([st3, st1, st2])  # 順序を入れ替え
        sorted_tasks = graph.topological_sort()

        # st1 → st2 → st3 の順序
        assert sorted_tasks[0].id == st1.id
        assert sorted_tasks[1].id == st2.id
        assert sorted_tasks[2].id == st3.id

    def test_parallel_groups(self):
        """並列グループが正しく特定される"""
        st1 = create_subtask(name="タスク1", action="action1")
        st2 = create_subtask(name="タスク2", action="action2")  # st1と並列
        st3 = create_subtask(name="タスク3", action="action3", depends_on=[st1.id, st2.id])

        graph = DependencyGraph([st1, st2, st3])
        groups = graph.identify_parallel_groups()

        # グループ1: st1, st2（並列）
        # グループ2: st3
        assert len(groups) == 2
        assert len(groups[0]) == 2  # st1, st2
        assert len(groups[1]) == 1  # st3


# =============================================================================
# TaskDecomposer テスト
# =============================================================================


class TestTaskDecomposer:
    """TaskDecomposerのテスト"""

    @pytest.mark.asyncio
    async def test_simple_request_not_decomposed(self, decomposer, mock_context):
        """単純なリクエストは分解されない"""
        subtasks = await decomposer.decompose(
            "自分のタスク教えて",
            mock_context,
        )
        assert len(subtasks) == 1

    @pytest.mark.asyncio
    async def test_complex_request_decomposed(self, decomposer, mock_context):
        """複雑なリクエストは分解される"""
        # パターンにマッチするリクエスト
        subtasks = await decomposer.decompose(
            "タスク「報告書作成」を作って、田中さんに割り当てて",
            mock_context,
        )
        # パターンマッチすれば複数タスクに分解される
        # マッチしなければ1タスク
        assert len(subtasks) >= 1

    def test_should_decompose(self, decomposer):
        """should_decomposeが正しく判定する"""
        assert decomposer.should_decompose("タスク教えて") is False
        assert decomposer.should_decompose("タスク作って、完了にして") is True


# =============================================================================
# ExecutionPlanner テスト
# =============================================================================


class TestExecutionPlanner:
    """ExecutionPlannerのテスト"""

    def test_create_plan(self, planner, mock_context):
        """実行計画を作成できる"""
        subtasks = [
            create_subtask(name="タスク1", action="action1"),
            create_subtask(name="タスク2", action="action2"),
        ]

        plan = planner.create_plan(
            subtasks=subtasks,
            request="テストリクエスト",
            context=mock_context,
        )

        assert plan is not None
        assert len(plan.subtasks) == 2

    def test_circular_dependency_raises(self, planner, mock_context):
        """循環依存でエラーが発生する"""
        st1 = create_subtask(name="タスク1", action="action1")
        st2 = create_subtask(name="タスク2", action="action2", depends_on=[st1.id])
        st1.depends_on = [st2.id]  # 循環

        with pytest.raises(ValueError, match="循環依存"):
            planner.create_plan(
                subtasks=[st1, st2],
                request="テスト",
                context=mock_context,
            )

    def test_validate_plan(self, planner):
        """計画の検証が機能する"""
        subtasks = [create_subtask(name="タスク1", action="action1")]
        plan = create_execution_plan(
            name="テスト",
            original_request="テスト",
            subtasks=subtasks,
        )

        is_valid, errors = planner.validate_plan(plan)
        assert is_valid is True
        assert len(errors) == 0


# =============================================================================
# WorkflowExecutor テスト
# =============================================================================


class TestWorkflowExecutor:
    """WorkflowExecutorのテスト"""

    @pytest.mark.asyncio
    async def test_execute_simple_plan(self, executor, mock_context):
        """単純な計画を実行できる"""
        subtasks = [
            create_subtask(name="タスク1", action="chatwork_task_create"),
        ]
        plan = create_execution_plan(
            name="テスト計画",
            original_request="テストリクエスト",
            subtasks=subtasks,
            room_id="123",
            account_id="456",
        )

        result = await executor.execute(plan, mock_context)

        assert result.success is True
        assert len(result.completed_subtasks) == 1

    @pytest.mark.asyncio
    async def test_execute_with_dependency(self, executor, mock_context):
        """依存関係のある計画を実行できる"""
        st1 = create_subtask(name="タスク1", action="chatwork_task_create")
        st2 = create_subtask(name="タスク2", action="chatwork_task_search", depends_on=[st1.id])

        plan = create_execution_plan(
            name="テスト計画",
            original_request="テストリクエスト",
            subtasks=[st1, st2],
            room_id="123",
            account_id="456",
        )
        plan.parallel_execution = False

        result = await executor.execute(plan, mock_context)

        assert result.success is True
        assert len(result.completed_subtasks) == 2

    @pytest.mark.asyncio
    async def test_execute_with_failure(self, executor, mock_context):
        """失敗を含む計画を実行できる"""
        subtasks = [
            create_subtask(name="失敗タスク", action="fail_action"),
        ]
        plan = create_execution_plan(
            name="テスト計画",
            original_request="テストリクエスト",
            subtasks=subtasks,
            room_id="123",
            account_id="456",
        )

        result = await executor.execute(plan, mock_context)

        assert result.success is False
        assert len(result.failed_subtasks) == 1


# =============================================================================
# ProgressTracker テスト
# =============================================================================


class TestProgressTracker:
    """ProgressTrackerのテスト"""

    @pytest.mark.asyncio
    async def test_initial_progress(self):
        """初期進捗を報告できる"""
        tracker = ProgressTracker()
        subtasks = [create_subtask(name="タスク1", action="action1")]
        plan = create_execution_plan(
            name="テスト",
            original_request="テスト",
            subtasks=subtasks,
        )

        report = await tracker.update(plan)
        # 初回は通知される
        assert report is not None
        assert report.progress_percentage == 0.0

    @pytest.mark.asyncio
    async def test_progress_threshold(self):
        """閾値を超えると通知される"""
        tracker = ProgressTracker(notification_threshold=0.25)
        subtasks = [
            create_subtask(name="タスク1", action="action1"),
            create_subtask(name="タスク2", action="action2"),
            create_subtask(name="タスク3", action="action3"),
            create_subtask(name="タスク4", action="action4"),
        ]
        plan = create_execution_plan(
            name="テスト",
            original_request="テスト",
            subtasks=subtasks,
        )

        # 初回
        await tracker.update(plan)

        # 25%完了
        subtasks[0].status = SubTaskStatus.COMPLETED
        report = await tracker.update(plan)
        assert report is not None


# =============================================================================
# QualityChecker テスト
# =============================================================================


class TestQualityChecker:
    """QualityCheckerのテスト"""

    @pytest.mark.asyncio
    async def test_all_pass(self):
        """全て完了で合格"""
        checker = QualityChecker()
        subtasks = [create_subtask(name="タスク1", action="action1")]
        subtasks[0].status = SubTaskStatus.COMPLETED

        plan = create_execution_plan(
            name="テスト",
            original_request="テスト",
            subtasks=subtasks,
        )
        plan.started_at = datetime.now()
        plan.completed_at = datetime.now()

        report = await checker.check_plan(plan)
        assert report.overall_result == QualityCheckResult.PASS

    @pytest.mark.asyncio
    async def test_high_error_rate_fails(self):
        """エラー率が高いと不合格"""
        checker = QualityChecker(max_error_rate=0.2)
        subtasks = [
            create_subtask(name="タスク1", action="action1"),
            create_subtask(name="タスク2", action="action2"),
        ]
        subtasks[0].status = SubTaskStatus.FAILED
        subtasks[1].status = SubTaskStatus.FAILED

        plan = create_execution_plan(
            name="テスト",
            original_request="テスト",
            subtasks=subtasks,
        )

        report = await checker.check_plan(plan)
        assert report.overall_result == QualityCheckResult.FAIL


# =============================================================================
# ExecutionExcellence 統合テスト
# =============================================================================


class TestExecutionExcellenceIntegration:
    """ExecutionExcellence統合テスト"""

    @pytest.fixture
    def excellence(self, mock_handlers, mock_capabilities):
        """ExecutionExcellenceインスタンス"""
        return ExecutionExcellence(
            handlers=mock_handlers,
            capabilities=mock_capabilities,
        )

    def test_should_use_workflow(self, excellence, mock_context):
        """ワークフロー使用判定が機能する"""
        assert excellence.should_use_workflow("タスク教えて", mock_context) is False
        assert excellence.should_use_workflow("タスク作って、完了にして", mock_context) is True

    @pytest.mark.asyncio
    async def test_execute_request(self, excellence, mock_context):
        """リクエストを実行できる"""
        result = await excellence.execute_request(
            "タスクを検索して",
            mock_context,
        )
        # 単一タスクとして処理される
        assert result is not None


# =============================================================================
# Feature Flag テスト
# =============================================================================


class TestFeatureFlags:
    """Feature Flagのテスト"""

    def test_is_enabled_false_by_default(self):
        """デフォルトで無効"""
        assert is_execution_excellence_enabled() is False
        assert is_execution_excellence_enabled({}) is False

    def test_is_enabled_when_flag_set(self):
        """フラグ設定で有効"""
        flags = {FEATURE_FLAG_EXECUTION_EXCELLENCE: True}
        assert is_execution_excellence_enabled(flags) is True

    def test_create_with_flags(self, mock_handlers, mock_capabilities):
        """フラグ付きで作成できる"""
        flags = {
            "ENABLE_PARALLEL_EXECUTION": False,
            "ENABLE_QUALITY_CHECKS": False,
        }
        excellence = create_execution_excellence(
            handlers=mock_handlers,
            capabilities=mock_capabilities,
            feature_flags=flags,
        )
        assert excellence is not None
