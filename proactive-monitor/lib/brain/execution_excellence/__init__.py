# lib/brain/execution_excellence/__init__.py
"""
Phase 2L: 実行力強化（Execution Excellence）

複雑なタスクの分解・計画・実行を行う脳の拡張モジュール。

主要コンポーネント:
- TaskDecomposer: リクエストをサブタスクに分解
- ExecutionPlanner: 実行計画を立案
- WorkflowExecutor: ワークフローを実行
- ProgressTracker: 進捗を追跡
- QualityChecker: 品質をチェック
- ExceptionHandler: 例外を処理
- EscalationManager: エスカレーションを管理

設計書: docs/21_phase2l_execution_excellence.md

使用例:
    from lib.brain.execution_excellence import ExecutionExcellence

    excellence = ExecutionExcellence(
        handlers=handlers,
        capabilities=SYSTEM_CAPABILITIES,
    )

    # ワークフロー実行が必要か判定
    if excellence.should_use_workflow(request, context):
        result = await excellence.execute_request(request, context)
    else:
        # 通常の単一アクション実行
        ...
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from lib.brain.models import BrainContext, HandlerResult
from lib.brain.execution_excellence.models import (
    # Enum
    SubTaskStatus,
    ExecutionPriority,
    RecoveryStrategy,
    QualityCheckResult,
    EscalationLevel,
    # データクラス
    SubTask,
    ExecutionPlan,
    ProgressReport,
    QualityReport,
    EscalationRequest,
    RecoveryResult,
    ExecutionExcellenceResult,
    SubTaskTemplate,
    DecompositionPattern,
    # ファクトリ
    create_subtask,
    create_execution_plan,
)
from lib.brain.execution_excellence.decomposer import (
    TaskDecomposer,
    create_task_decomposer,
    detect_multi_action_request,
    ALL_DECOMPOSITION_PATTERNS,
)
from lib.brain.execution_excellence.planner import (
    ExecutionPlanner,
    create_execution_planner,
    DependencyGraph,
)
from lib.brain.execution_excellence.executor import (
    WorkflowExecutor,
    ProgressTracker,
    QualityChecker,
    ExceptionHandler,
    EscalationManager,
    create_workflow_executor,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Feature Flag
# =============================================================================


FEATURE_FLAG_EXECUTION_EXCELLENCE = "ENABLE_EXECUTION_EXCELLENCE"
FEATURE_FLAG_TASK_DECOMPOSITION = "ENABLE_TASK_DECOMPOSITION"
FEATURE_FLAG_PARALLEL_EXECUTION = "ENABLE_PARALLEL_EXECUTION"
FEATURE_FLAG_QUALITY_CHECKS = "ENABLE_QUALITY_CHECKS"
FEATURE_FLAG_AUTO_ESCALATION = "ENABLE_AUTO_ESCALATION"
FEATURE_FLAG_LLM_DECOMPOSITION = "ENABLE_LLM_DECOMPOSITION"


# =============================================================================
# ExecutionExcellence 統合クラス
# =============================================================================


class ExecutionExcellence:
    """
    実行力強化の統合クラス

    TaskDecomposer、ExecutionPlanner、WorkflowExecutor、
    およびサポートコンポーネントを統合する。
    """

    def __init__(
        self,
        handlers: Dict[str, Callable],
        capabilities: Dict[str, Dict],
        pool: Optional[Any] = None,
        org_id: str = "",
        llm_client: Optional[Any] = None,
        enable_parallel_execution: bool = True,
        enable_quality_checks: bool = True,
        enable_llm_decomposition: bool = False,
    ):
        """
        ExecutionExcellenceを初期化

        Args:
            handlers: アクション名 → ハンドラー関数
            capabilities: SYSTEM_CAPABILITIES
            pool: DBプール（オプション）
            org_id: 組織ID
            llm_client: LLMクライアント（オプション）
            enable_parallel_execution: 並列実行を有効化
            enable_quality_checks: 品質チェックを有効化
            enable_llm_decomposition: LLMベース分解を有効化
        """
        self.handlers = handlers
        self.capabilities = capabilities
        self.pool = pool
        self.org_id = org_id

        # コンポーネント初期化
        self.decomposer = TaskDecomposer(
            capabilities=capabilities,
            llm_client=llm_client,
            enable_llm_decomposition=enable_llm_decomposition,
        )

        self.planner = ExecutionPlanner(
            default_parallel_execution=enable_parallel_execution,
            default_quality_checks_enabled=enable_quality_checks,
        )

        self.progress_tracker = ProgressTracker()
        self.quality_checker = QualityChecker()
        self.exception_handler = ExceptionHandler()
        self.escalation_manager = EscalationManager()

        self.executor = WorkflowExecutor(
            handlers=handlers,
            progress_tracker=self.progress_tracker,
            quality_checker=self.quality_checker,
            exception_handler=self.exception_handler,
            escalation_manager=self.escalation_manager,
        )

        logger.info(
            f"ExecutionExcellence initialized: "
            f"handlers={len(handlers)}, "
            f"parallel={enable_parallel_execution}, "
            f"quality_checks={enable_quality_checks}"
        )

    async def execute_request(
        self,
        request: str,
        context: BrainContext,
    ) -> ExecutionExcellenceResult:
        """
        リクエストを実行

        Args:
            request: ユーザーリクエスト
            context: 脳コンテキスト

        Returns:
            実行結果
        """
        logger.info(f"Executing request: {request[:50]}...")

        # 1. タスク分解
        subtasks = await self.decomposer.decompose(request, context)

        if len(subtasks) == 1 and subtasks[0].action == "general_response":
            # 分解不要な単一タスク → 従来の処理に委譲
            return self._create_single_task_result(subtasks[0], request)

        # 2. 実行計画立案
        plan = self.planner.create_plan(subtasks, request, context)

        # 3. ワークフロー実行
        result = await self.executor.execute(plan, context)

        # 4. 実行結果を記録（将来的にDBに保存）
        await self._log_execution(plan, result)

        return result

    def should_use_workflow(self, request: str, context: BrainContext) -> bool:
        """
        ワークフロー実行を使うべきか判定

        複雑なリクエストの場合はTrue

        Args:
            request: ユーザーリクエスト
            context: 脳コンテキスト

        Returns:
            ワークフロー実行を使うべきならTrue
        """
        return detect_multi_action_request(request)

    async def get_progress(self, plan_id: str) -> Optional[ProgressReport]:
        """
        進捗を取得

        Args:
            plan_id: 実行計画ID

        Returns:
            進捗レポート（見つからない場合はNone）
        """
        # 将来的にはDBから取得
        return None

    async def handle_escalation_response(
        self,
        escalation_id: str,
        response: str,
        reasoning: Optional[str] = None,
    ) -> bool:
        """
        エスカレーションへの応答を処理

        Args:
            escalation_id: エスカレーションID
            response: 応答（"retry", "skip", "abort"等）
            reasoning: 応答の理由

        Returns:
            処理成功ならTrue
        """
        return await self.escalation_manager.process_response(
            escalation_id, response, reasoning
        )

    def _create_single_task_result(
        self,
        subtask: SubTask,
        request: str,
    ) -> ExecutionExcellenceResult:
        """単一タスクの結果を作成"""
        return ExecutionExcellenceResult(
            plan_id="single_task",
            plan_name="単一タスク",
            original_request=request,
            success=True,
            message="",  # 従来の処理に委譲するため空
            completed_subtasks=[],
            failed_subtasks=[],
            skipped_subtasks=[],
        )

    async def _log_execution(
        self,
        plan: ExecutionPlan,
        result: ExecutionExcellenceResult,
    ) -> None:
        """実行結果をログ"""
        logger.info(
            f"Execution completed: "
            f"plan={plan.name}, "
            f"success={result.success}, "
            f"completed={len(result.completed_subtasks)}, "
            f"failed={len(result.failed_subtasks)}, "
            f"time={result.total_execution_time_ms}ms"
        )

        # 将来的にはDBに保存


# =============================================================================
# ファクトリ関数
# =============================================================================


def create_execution_excellence(
    handlers: Dict[str, Callable],
    capabilities: Dict[str, Dict],
    pool: Optional[Any] = None,
    org_id: str = "",
    llm_client: Optional[Any] = None,
    feature_flags: Optional[Dict[str, bool]] = None,
) -> ExecutionExcellence:
    """
    ExecutionExcellenceを作成

    Args:
        handlers: アクションハンドラー
        capabilities: SYSTEM_CAPABILITIES
        pool: DBプール
        org_id: 組織ID
        llm_client: LLMクライアント
        feature_flags: Feature Flag設定

    Returns:
        ExecutionExcellence
    """
    flags = feature_flags or {}

    return ExecutionExcellence(
        handlers=handlers,
        capabilities=capabilities,
        pool=pool,
        org_id=org_id,
        llm_client=llm_client,
        enable_parallel_execution=flags.get(FEATURE_FLAG_PARALLEL_EXECUTION, True),
        enable_quality_checks=flags.get(FEATURE_FLAG_QUALITY_CHECKS, True),
        enable_llm_decomposition=flags.get(FEATURE_FLAG_LLM_DECOMPOSITION, False),
    )


def is_execution_excellence_enabled(feature_flags: Optional[Dict[str, bool]] = None) -> bool:
    """
    ExecutionExcellenceが有効かどうかを判定

    Args:
        feature_flags: Feature Flag設定

    Returns:
        有効ならTrue
    """
    if feature_flags is None:
        return False
    return feature_flags.get(FEATURE_FLAG_EXECUTION_EXCELLENCE, False)


# =============================================================================
# エクスポート
# =============================================================================


__all__ = [
    # メインクラス
    "ExecutionExcellence",
    "create_execution_excellence",
    "is_execution_excellence_enabled",
    # コンポーネント
    "TaskDecomposer",
    "create_task_decomposer",
    "ExecutionPlanner",
    "create_execution_planner",
    "WorkflowExecutor",
    "create_workflow_executor",
    "ProgressTracker",
    "QualityChecker",
    "ExceptionHandler",
    "EscalationManager",
    "DependencyGraph",
    # Enum
    "SubTaskStatus",
    "ExecutionPriority",
    "RecoveryStrategy",
    "QualityCheckResult",
    "EscalationLevel",
    # データモデル
    "SubTask",
    "ExecutionPlan",
    "ProgressReport",
    "QualityReport",
    "EscalationRequest",
    "RecoveryResult",
    "ExecutionExcellenceResult",
    "SubTaskTemplate",
    "DecompositionPattern",
    # ファクトリ
    "create_subtask",
    "create_execution_plan",
    # ユーティリティ
    "detect_multi_action_request",
    "ALL_DECOMPOSITION_PATTERNS",
    # Feature Flags
    "FEATURE_FLAG_EXECUTION_EXCELLENCE",
    "FEATURE_FLAG_TASK_DECOMPOSITION",
    "FEATURE_FLAG_PARALLEL_EXECUTION",
    "FEATURE_FLAG_QUALITY_CHECKS",
    "FEATURE_FLAG_AUTO_ESCALATION",
    "FEATURE_FLAG_LLM_DECOMPOSITION",
]

__version__ = "1.0.0"
