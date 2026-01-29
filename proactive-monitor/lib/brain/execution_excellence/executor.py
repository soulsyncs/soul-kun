# lib/brain/execution_excellence/executor.py
"""
Phase 2L: 実行力強化（Execution Excellence） - ワークフロー実行

ExecutionPlanに従ってサブタスクを順次/並列実行するコンポーネント。

設計書: docs/21_phase2l_execution_excellence.md
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from lib.brain.models import BrainContext, HandlerResult
from lib.brain.exceptions import ExecutionError
from lib.brain.execution_excellence.models import (
    SubTask,
    SubTaskStatus,
    ExecutionPlan,
    ExecutionExcellenceResult,
    ProgressReport,
    QualityReport,
    QualityCheckResult,
    EscalationRequest,
    EscalationLevel,
    RecoveryStrategy,
    RecoveryResult,
)

logger = logging.getLogger(__name__)


# =============================================================================
# ProgressTracker（進捗追跡）
# =============================================================================


class ProgressTracker:
    """
    進捗追跡

    実行中のワークフローの進捗を追跡し、ユーザーに報告する。
    """

    def __init__(
        self,
        notification_threshold: float = 0.25,  # 25%ごとに通知
        stale_threshold_seconds: int = 60,      # 60秒動きがなければ通知
    ):
        """
        進捗追跡を初期化

        Args:
            notification_threshold: 通知閾値（進捗率）
            stale_threshold_seconds: 停滞検出閾値（秒）
        """
        self.notification_threshold = notification_threshold
        self.stale_threshold_seconds = stale_threshold_seconds
        self._last_notified_progress: Dict[str, float] = {}
        self._last_activity_time: Dict[str, datetime] = {}

    async def update(self, plan: ExecutionPlan) -> Optional[ProgressReport]:
        """
        進捗を更新

        必要に応じてユーザーに進捗を通知する。

        Args:
            plan: 実行計画

        Returns:
            通知すべき場合はProgressReport、それ以外はNone
        """
        report = self._create_report(plan)

        # 通知が必要か判定
        should_notify = self._should_notify(plan.id, report)

        if should_notify:
            self._last_notified_progress[plan.id] = report.progress_percentage
            self._last_activity_time[plan.id] = datetime.now()
            return report

        return None

    def _create_report(self, plan: ExecutionPlan) -> ProgressReport:
        """進捗レポートを作成"""
        current_activity = "処理中..."
        in_progress_tasks = [
            st for st in plan.subtasks if st.status == SubTaskStatus.IN_PROGRESS
        ]
        if in_progress_tasks:
            current_activity = f"「{in_progress_tasks[0].name}」を実行中"

        issues = []
        failed_tasks = [
            st for st in plan.subtasks if st.status == SubTaskStatus.FAILED
        ]
        if failed_tasks:
            issues.append(f"{len(failed_tasks)}個のタスクが失敗")

        return ProgressReport(
            plan_id=plan.id,
            plan_name=plan.name,
            total_subtasks=len(plan.subtasks),
            completed_subtasks=plan.completed_count,
            failed_subtasks=plan.failed_count,
            in_progress_subtasks=plan.in_progress_count,
            pending_subtasks=plan.pending_count,
            progress_percentage=plan.progress * 100,
            current_activity=current_activity,
            issues=issues,
        )

    def _should_notify(self, plan_id: str, report: ProgressReport) -> bool:
        """通知すべきか判定"""
        # 初回は必ず通知
        if plan_id not in self._last_notified_progress:
            return True

        last_progress = self._last_notified_progress.get(plan_id, 0)
        progress_diff = report.progress_percentage - last_progress

        # 進捗が閾値を超えた
        if progress_diff >= self.notification_threshold * 100:
            return True

        # 長時間動きがない
        last_activity = self._last_activity_time.get(plan_id)
        if last_activity:
            elapsed = (datetime.now() - last_activity).total_seconds()
            if elapsed >= self.stale_threshold_seconds:
                return True

        # 完了または失敗
        if report.progress_percentage >= 100 or report.failed_subtasks > 0:
            return True

        return False

    def reset(self, plan_id: str) -> None:
        """追跡状態をリセット"""
        self._last_notified_progress.pop(plan_id, None)
        self._last_activity_time.pop(plan_id, None)


# =============================================================================
# QualityChecker（品質チェック）
# =============================================================================


class QualityChecker:
    """
    品質チェッカー

    実行結果の品質を検証する。
    """

    def __init__(
        self,
        min_completion_rate: float = 0.8,  # 最低完了率
        max_error_rate: float = 0.2,       # 最大エラー率
    ):
        """
        品質チェッカーを初期化

        Args:
            min_completion_rate: 最低完了率
            max_error_rate: 最大エラー率
        """
        self.min_completion_rate = min_completion_rate
        self.max_error_rate = max_error_rate

    async def check_plan(self, plan: ExecutionPlan) -> QualityReport:
        """
        実行計画全体の品質をチェック

        Args:
            plan: 実行計画

        Returns:
            品質レポート
        """
        check_results = []
        issues = []
        warnings = []

        # 1. 完了率チェック
        completion_result = self._check_completion_rate(plan)
        check_results.append(completion_result)
        if completion_result["result"] == "fail":
            issues.append(completion_result["message"])
        elif completion_result["result"] == "warning":
            warnings.append(completion_result["message"])

        # 2. エラー率チェック
        error_result = self._check_error_rate(plan)
        check_results.append(error_result)
        if error_result["result"] == "fail":
            issues.append(error_result["message"])
        elif error_result["result"] == "warning":
            warnings.append(error_result["message"])

        # 3. 実行時間チェック
        time_result = self._check_execution_time(plan)
        check_results.append(time_result)
        if time_result["result"] == "warning":
            warnings.append(time_result["message"])

        # 総合スコア計算
        total_score = sum(r["score"] for r in check_results) / len(check_results)

        # 総合結果判定
        if any(r["result"] == "fail" for r in check_results):
            overall_result = QualityCheckResult.FAIL
        elif any(r["result"] == "warning" for r in check_results):
            overall_result = QualityCheckResult.WARNING
        else:
            overall_result = QualityCheckResult.PASS

        return QualityReport(
            plan_id=plan.id,
            overall_result=overall_result,
            quality_score=total_score,
            checks=check_results,
            issues=issues,
            warnings=warnings,
        )

    def _check_completion_rate(self, plan: ExecutionPlan) -> Dict[str, Any]:
        """完了率チェック"""
        if not plan.subtasks:
            return {
                "name": "完了率",
                "result": "pass",
                "score": 1.0,
                "message": "タスクなし",
            }

        # オプショナルでないタスクの完了率
        required_tasks = [st for st in plan.subtasks if not st.is_optional]
        if not required_tasks:
            completion_rate = 1.0
        else:
            completed = sum(1 for st in required_tasks if st.status == SubTaskStatus.COMPLETED)
            completion_rate = completed / len(required_tasks)

        if completion_rate >= self.min_completion_rate:
            return {
                "name": "完了率",
                "result": "pass",
                "score": completion_rate,
                "message": f"{completion_rate * 100:.0f}%完了",
            }
        elif completion_rate >= self.min_completion_rate * 0.8:
            return {
                "name": "完了率",
                "result": "warning",
                "score": completion_rate,
                "message": f"完了率が低め: {completion_rate * 100:.0f}%",
            }
        else:
            return {
                "name": "完了率",
                "result": "fail",
                "score": completion_rate,
                "message": f"完了率が基準未満: {completion_rate * 100:.0f}% (基準: {self.min_completion_rate * 100:.0f}%)",
            }

    def _check_error_rate(self, plan: ExecutionPlan) -> Dict[str, Any]:
        """エラー率チェック"""
        if not plan.subtasks:
            return {
                "name": "エラー率",
                "result": "pass",
                "score": 1.0,
                "message": "タスクなし",
            }

        error_rate = plan.failed_count / len(plan.subtasks)

        if error_rate <= self.max_error_rate * 0.5:
            return {
                "name": "エラー率",
                "result": "pass",
                "score": 1.0 - error_rate,
                "message": f"エラー率: {error_rate * 100:.0f}%",
            }
        elif error_rate <= self.max_error_rate:
            return {
                "name": "エラー率",
                "result": "warning",
                "score": 1.0 - error_rate,
                "message": f"エラー率がやや高め: {error_rate * 100:.0f}%",
            }
        else:
            return {
                "name": "エラー率",
                "result": "fail",
                "score": 1.0 - error_rate,
                "message": f"エラー率が基準超過: {error_rate * 100:.0f}% (基準: {self.max_error_rate * 100:.0f}%)",
            }

    def _check_execution_time(self, plan: ExecutionPlan) -> Dict[str, Any]:
        """実行時間チェック"""
        if not plan.started_at:
            return {
                "name": "実行時間",
                "result": "pass",
                "score": 1.0,
                "message": "未開始",
            }

        total_time_ms = plan.total_execution_time_ms
        expected_time_ms = sum(st.timeout_seconds * 1000 for st in plan.subtasks)

        if expected_time_ms == 0:
            return {
                "name": "実行時間",
                "result": "pass",
                "score": 1.0,
                "message": "計測不要",
            }

        time_ratio = total_time_ms / expected_time_ms

        if time_ratio <= 1.0:
            return {
                "name": "実行時間",
                "result": "pass",
                "score": 1.0,
                "message": f"想定内: {total_time_ms / 1000:.1f}秒",
            }
        elif time_ratio <= 1.5:
            return {
                "name": "実行時間",
                "result": "warning",
                "score": 1.0 / time_ratio,
                "message": f"やや遅延: {total_time_ms / 1000:.1f}秒",
            }
        else:
            return {
                "name": "実行時間",
                "result": "warning",
                "score": 0.5,
                "message": f"大幅遅延: {total_time_ms / 1000:.1f}秒",
            }


# =============================================================================
# ExceptionHandler（例外処理）
# =============================================================================


# 一時的エラー（リトライ可能）
TRANSIENT_ERRORS = {
    "ConnectionError",
    "TimeoutError",
    "HTTPError",
    "APIError",
    "RateLimitError",
}

# 権限エラー
PERMISSION_ERRORS = {
    "PermissionError",
    "AuthenticationError",
    "AuthorizationError",
    "ForbiddenError",
}

# データエラー
DATA_ERRORS = {
    "ValidationError",
    "DataError",
    "NotFoundError",
    "ConflictError",
}


class ExceptionHandler:
    """
    例外処理

    実行中のエラーを処理し、適切なリカバリーを行う。
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay_seconds: float = 1.0,
    ):
        """
        例外処理を初期化

        Args:
            max_retries: 最大リトライ回数
            base_delay_seconds: リトライ基本遅延（秒）
        """
        self.max_retries = max_retries
        self.base_delay_seconds = base_delay_seconds

    async def handle(
        self,
        error: Exception,
        plan: ExecutionPlan,
        context: BrainContext,
        subtask: Optional[SubTask] = None,
    ) -> RecoveryResult:
        """
        エラーを処理

        Args:
            error: 発生したエラー
            plan: 実行計画
            context: 脳コンテキスト
            subtask: エラーが発生したサブタスク

        Returns:
            リカバリー結果
        """
        error_type = type(error).__name__
        logger.warning(f"Handling exception: {error_type}: {error}")

        # エラータイプに応じた処理
        if error_type in TRANSIENT_ERRORS:
            return await self._handle_transient_error(error, plan, subtask)

        elif error_type in PERMISSION_ERRORS:
            return await self._handle_permission_error(error, plan, context)

        elif error_type in DATA_ERRORS:
            return await self._handle_data_error(error, plan, context)

        else:
            return await self._handle_unknown_error(error, plan, context)

    async def _handle_transient_error(
        self,
        error: Exception,
        plan: ExecutionPlan,
        subtask: Optional[SubTask],
    ) -> RecoveryResult:
        """一時的エラーの処理（リトライ）"""
        if subtask and subtask.retry_count < self.max_retries:
            delay = self.base_delay_seconds * (2 ** subtask.retry_count)
            await asyncio.sleep(min(delay, 30))  # 最大30秒

            return RecoveryResult(
                strategy=RecoveryStrategy.RETRY,
                success=True,
                message="一時的なエラーのためリトライします",
            )

        return RecoveryResult(
            strategy=RecoveryStrategy.ESCALATE,
            success=False,
            message="リトライ上限に達しました",
        )

    async def _handle_permission_error(
        self,
        error: Exception,
        plan: ExecutionPlan,
        context: BrainContext,
    ) -> RecoveryResult:
        """権限エラーの処理"""
        return RecoveryResult(
            strategy=RecoveryStrategy.ESCALATE,
            success=False,
            message=f"権限エラーが発生しました: {error}",
        )

    async def _handle_data_error(
        self,
        error: Exception,
        plan: ExecutionPlan,
        context: BrainContext,
    ) -> RecoveryResult:
        """データエラーの処理"""
        # 代替案を探す（将来的にはより洗練された実装）
        return RecoveryResult(
            strategy=RecoveryStrategy.ESCALATE,
            success=False,
            message=f"データエラーが発生しました: {error}",
            alternatives=["入力データを確認してください", "別の方法を試してください"],
        )

    async def _handle_unknown_error(
        self,
        error: Exception,
        plan: ExecutionPlan,
        context: BrainContext,
    ) -> RecoveryResult:
        """未知のエラーの処理"""
        logger.error(f"Unknown error in execution: {error}", exc_info=True)

        return RecoveryResult(
            strategy=RecoveryStrategy.ESCALATE,
            success=False,
            message=f"予期しないエラーが発生しました: {error}",
        )


# =============================================================================
# EscalationManager（エスカレーション管理）
# =============================================================================


class EscalationManager:
    """
    エスカレーション管理

    自動処理できない問題を人間にエスカレーションする。
    """

    def __init__(
        self,
        default_timeout_minutes: int = 30,
    ):
        """
        エスカレーション管理を初期化

        Args:
            default_timeout_minutes: デフォルトタイムアウト（分）
        """
        self.default_timeout_minutes = default_timeout_minutes
        self._pending_escalations: Dict[str, EscalationRequest] = {}

    async def create_task_escalation(
        self,
        subtask: SubTask,
        plan: ExecutionPlan,
        error: Exception,
    ) -> EscalationRequest:
        """タスク失敗のエスカレーションを作成"""
        escalation = EscalationRequest(
            id=str(uuid.uuid4()),
            plan_id=plan.id,
            subtask_id=subtask.id,
            level=EscalationLevel.DECISION,
            title=f"「{subtask.name}」の実行に失敗しました",
            description=f"エラー内容: {str(error)}",
            context=f"「{plan.original_request[:50]}...」の一部として実行中でした",
            options=[
                {"id": "retry", "label": "リトライ", "description": "もう一度試します"},
                {"id": "skip", "label": "スキップ", "description": "このタスクを飛ばして続行"},
                {"id": "abort", "label": "中止", "description": "全体の処理を中止"},
            ],
            recommendation="retry" if subtask.retry_count < 2 else "skip",
            recommendation_reasoning="一時的なエラーの可能性があります" if subtask.retry_count < 2 else "複数回失敗しているためスキップを推奨",
        )

        self._pending_escalations[escalation.id] = escalation
        return escalation

    async def create_quality_escalation(
        self,
        plan: ExecutionPlan,
        quality_report: QualityReport,
    ) -> EscalationRequest:
        """品質問題のエスカレーションを作成"""
        escalation = EscalationRequest(
            id=str(uuid.uuid4()),
            plan_id=plan.id,
            level=EscalationLevel.CONFIRMATION,
            title="品質チェックで問題が見つかりました",
            description=f"問題点: {', '.join(quality_report.issues)}",
            context=f"「{plan.original_request[:50]}...」の実行結果です",
            options=[
                {"id": "accept", "label": "そのまま完了", "description": "問題を許容して完了"},
                {"id": "retry", "label": "やり直し", "description": "最初からやり直し"},
                {"id": "manual", "label": "手動対応", "description": "自分で対応する"},
            ],
            recommendation="accept" if quality_report.quality_score > 0.7 else "manual",
        )

        self._pending_escalations[escalation.id] = escalation
        return escalation

    async def process_response(
        self,
        escalation_id: str,
        response: str,
        reasoning: Optional[str] = None,
    ) -> bool:
        """エスカレーションへの応答を処理"""
        escalation = self._pending_escalations.get(escalation_id)
        if not escalation:
            return False

        escalation.status = "responded"
        escalation.response = response
        escalation.response_reasoning = reasoning
        escalation.responded_at = datetime.now()

        return True

    def get_pending_escalations(self, plan_id: str) -> List[EscalationRequest]:
        """特定プランの未解決エスカレーションを取得"""
        return [
            e for e in self._pending_escalations.values()
            if e.plan_id == plan_id and e.is_pending
        ]


# =============================================================================
# WorkflowExecutor（ワークフロー実行）
# =============================================================================


class WorkflowExecutor:
    """
    ワークフロー実行

    ExecutionPlanに従ってサブタスクを実行する。
    """

    def __init__(
        self,
        handlers: Dict[str, Callable],
        progress_tracker: Optional[ProgressTracker] = None,
        quality_checker: Optional[QualityChecker] = None,
        exception_handler: Optional[ExceptionHandler] = None,
        escalation_manager: Optional[EscalationManager] = None,
    ):
        """
        ワークフロー実行を初期化

        Args:
            handlers: アクション名 → ハンドラー関数
            progress_tracker: 進捗追跡
            quality_checker: 品質チェッカー
            exception_handler: 例外処理
            escalation_manager: エスカレーション管理
        """
        self.handlers = handlers
        self.progress_tracker = progress_tracker or ProgressTracker()
        self.quality_checker = quality_checker or QualityChecker()
        self.exception_handler = exception_handler or ExceptionHandler()
        self.escalation_manager = escalation_manager or EscalationManager()

        logger.debug(f"WorkflowExecutor initialized with {len(handlers)} handlers")

    async def execute(
        self,
        plan: ExecutionPlan,
        context: BrainContext,
    ) -> ExecutionExcellenceResult:
        """
        実行計画を実行

        Args:
            plan: 実行計画
            context: 脳コンテキスト

        Returns:
            実行結果
        """
        logger.info(f"Executing plan: {plan.name} ({len(plan.subtasks)} subtasks)")

        plan.status = SubTaskStatus.IN_PROGRESS
        plan.started_at = datetime.now()
        escalations = []

        try:
            # 1. 実行可能なタスクを順次/並列実行
            while not plan.is_complete():
                ready_tasks = plan.get_ready_tasks()

                if not ready_tasks:
                    # 実行可能なタスクがない = デッドロックまたは全て完了
                    if not plan.is_complete():
                        logger.warning("No ready tasks but plan not complete")
                        break
                    break

                # 並列実行
                if plan.parallel_execution and len(ready_tasks) > 1:
                    results = await asyncio.gather(
                        *[
                            self._execute_subtask(st, plan, context)
                            for st in ready_tasks
                        ],
                        return_exceptions=True,
                    )

                    # 例外をチェック
                    for i, result in enumerate(results):
                        if isinstance(result, Exception):
                            subtask = ready_tasks[i]
                            recovery = await self.exception_handler.handle(
                                result, plan, context, subtask
                            )
                            if recovery.strategy == RecoveryStrategy.ESCALATE:
                                esc = await self.escalation_manager.create_task_escalation(
                                    subtask, plan, result
                                )
                                escalations.append(esc)
                else:
                    # 順次実行
                    for task in ready_tasks:
                        success = await self._execute_subtask(task, plan, context)

                        # 失敗時の処理
                        if not success and not plan.continue_on_failure:
                            if task.status == SubTaskStatus.ESCALATED:
                                break  # エスカレーション待ち

                # 進捗更新
                progress_report = await self.progress_tracker.update(plan)
                if progress_report:
                    logger.debug(
                        f"Progress: {progress_report.progress_percentage:.0f}%"
                    )

            # 2. 品質チェック
            quality_report = None
            if plan.quality_checks_enabled:
                quality_report = await self.quality_checker.check_plan(plan)

                if quality_report.overall_result == QualityCheckResult.FAIL:
                    escalation = await self.escalation_manager.create_quality_escalation(
                        plan, quality_report
                    )
                    escalations.append(escalation)

            # 3. 完了
            plan.status = SubTaskStatus.COMPLETED if not plan.has_failures() else SubTaskStatus.FAILED
            plan.completed_at = datetime.now()

            return self._create_result(plan, quality_report, escalations)

        except Exception as e:
            logger.error(f"Workflow execution failed: {e}", exc_info=True)
            plan.status = SubTaskStatus.FAILED
            plan.completed_at = datetime.now()

            return ExecutionExcellenceResult(
                plan_id=plan.id,
                plan_name=plan.name,
                original_request=plan.original_request,
                success=False,
                message=f"ワークフローの実行中にエラーが発生しました: {e}",
                escalations=escalations,
                total_execution_time_ms=plan.total_execution_time_ms,
            )

    async def _execute_subtask(
        self,
        subtask: SubTask,
        plan: ExecutionPlan,
        context: BrainContext,
    ) -> bool:
        """サブタスクを実行"""
        logger.debug(f"Executing subtask: {subtask.name} ({subtask.action})")

        subtask.status = SubTaskStatus.IN_PROGRESS
        subtask.started_at = datetime.now()

        try:
            # ハンドラーを取得
            handler = self.handlers.get(subtask.action)
            if not handler:
                # ハンドラーがない場合はスキップまたはエスカレーション
                if subtask.is_optional:
                    subtask.status = SubTaskStatus.SKIPPED
                    subtask.error = f"ハンドラーが見つかりません: {subtask.action}"
                    return True
                else:
                    subtask.status = SubTaskStatus.FAILED
                    subtask.error = f"ハンドラーが見つかりません: {subtask.action}"
                    return False

            # 実行（タイムアウト付き）
            result = await asyncio.wait_for(
                self._call_handler(handler, subtask, plan, context),
                timeout=subtask.timeout_seconds,
            )

            if result.success:
                subtask.status = SubTaskStatus.COMPLETED
                subtask.result = result.data
                subtask.completed_at = datetime.now()
                logger.debug(f"Subtask completed: {subtask.name}")
                return True
            else:
                subtask.status = SubTaskStatus.FAILED
                subtask.error = result.error_details or result.message
                subtask.completed_at = datetime.now()
                logger.warning(f"Subtask failed: {subtask.name} - {subtask.error}")
                return False

        except asyncio.TimeoutError:
            subtask.status = SubTaskStatus.FAILED
            subtask.error = f"タイムアウト（{subtask.timeout_seconds}秒）"
            subtask.completed_at = datetime.now()
            logger.warning(f"Subtask timeout: {subtask.name}")
            return False

        except Exception as e:
            subtask.status = SubTaskStatus.FAILED
            subtask.error = str(e)
            subtask.completed_at = datetime.now()
            logger.error(f"Subtask error: {subtask.name} - {e}")

            # リカバリー戦略を適用
            if subtask.recovery_strategy == RecoveryStrategy.SKIP and subtask.is_optional:
                subtask.status = SubTaskStatus.SKIPPED
                return True

            return False

    async def _call_handler(
        self,
        handler: Callable,
        subtask: SubTask,
        plan: ExecutionPlan,
        context: BrainContext,
    ) -> HandlerResult:
        """ハンドラーを呼び出す"""
        # ハンドラーが非同期関数かどうかを判定
        if asyncio.iscoroutinefunction(handler):
            result = await handler(
                params=subtask.params,
                room_id=plan.room_id,
                account_id=plan.account_id,
                sender_name=context.sender_name,
                context=context,
            )
        else:
            # 同期関数の場合はスレッドプールで実行
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: handler(
                    params=subtask.params,
                    room_id=plan.room_id,
                    account_id=plan.account_id,
                    sender_name=context.sender_name,
                    context=context,
                ),
            )

        return self._normalize_result(result)

    def _normalize_result(self, result: Any) -> HandlerResult:
        """結果をHandlerResultに正規化"""
        if isinstance(result, HandlerResult):
            return result

        if isinstance(result, str):
            return HandlerResult(success=True, message=result)

        if isinstance(result, dict):
            return HandlerResult(
                success=result.get("success", True),
                message=result.get("message", "完了"),
                data=result,
                error_details=result.get("error_details"),
            )

        if result is None:
            return HandlerResult(success=True, message="完了")

        return HandlerResult(success=True, message=str(result))

    def _create_result(
        self,
        plan: ExecutionPlan,
        quality_report: Optional[QualityReport],
        escalations: List[EscalationRequest],
    ) -> ExecutionExcellenceResult:
        """実行結果を作成"""
        completed_names = [
            st.name for st in plan.subtasks
            if st.status == SubTaskStatus.COMPLETED
        ]
        failed_names = [
            st.name for st in plan.subtasks
            if st.status == SubTaskStatus.FAILED
        ]
        skipped_names = [
            st.name for st in plan.subtasks
            if st.status == SubTaskStatus.SKIPPED
        ]

        # メッセージ生成
        if not failed_names:
            message = f"「{plan.original_request[:30]}...」を完了したウル🐺"
            if completed_names:
                message += f"\n\n完了したタスク:\n" + "\n".join(f"✅ {n}" for n in completed_names)
        else:
            message = f"「{plan.original_request[:30]}...」の一部が失敗したウル..."
            if completed_names:
                message += f"\n\n完了: " + ", ".join(completed_names)
            message += f"\n失敗: " + ", ".join(failed_names)

        # 提案生成
        suggestions = []
        if failed_names:
            suggestions.append("失敗したタスクをリトライする？")
        if completed_names:
            suggestions.append("他にやることはある？")

        return ExecutionExcellenceResult(
            plan_id=plan.id,
            plan_name=plan.name,
            original_request=plan.original_request,
            success=not plan.has_failures(),
            message=message,
            completed_subtasks=completed_names,
            failed_subtasks=failed_names,
            skipped_subtasks=skipped_names,
            quality_score=quality_report.quality_score if quality_report else 1.0,
            quality_report=quality_report,
            escalations=escalations,
            total_execution_time_ms=plan.total_execution_time_ms,
            retry_count=sum(st.retry_count for st in plan.subtasks),
            suggestions=suggestions,
            started_at=plan.started_at,
        )


# =============================================================================
# ファクトリ関数
# =============================================================================


def create_workflow_executor(
    handlers: Dict[str, Callable],
) -> WorkflowExecutor:
    """
    WorkflowExecutorを作成

    Args:
        handlers: アクションハンドラー

    Returns:
        WorkflowExecutor
    """
    return WorkflowExecutor(
        handlers=handlers,
        progress_tracker=ProgressTracker(),
        quality_checker=QualityChecker(),
        exception_handler=ExceptionHandler(),
        escalation_manager=EscalationManager(),
    )
