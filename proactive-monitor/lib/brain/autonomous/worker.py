# lib/brain/autonomous/worker.py
"""
Phase AA: ワーカーベースクラス

自律タスクを実行するワーカーの抽象基底クラス。
各タスクタイプ固有のワーカーはこのクラスを継承して実装する。

CLAUDE.md §1: 全機能はBrainを通る
CLAUDE.md §8 鉄則#8: エラーに機密情報を含めない
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from lib.brain.autonomous.task_queue import (
    AutonomousTask,
    TaskQueue,
    TaskStatus,
)

logger = logging.getLogger(__name__)


# =========================================================================
# ステップ結果
# =========================================================================


@dataclass
class StepResult:
    """ステップの実行結果"""
    success: bool
    output: Dict[str, Any]
    error: Optional[str] = None
    duration_ms: int = 0


# =========================================================================
# ベースワーカー
# =========================================================================


class BaseWorker(ABC):
    """
    自律タスクワーカーの基底クラス

    Usage:
        class ResearchWorker(BaseWorker):
            async def execute(self, task):
                # ステップ1: 情報収集
                await self.report_progress(task, 1, "情報収集中")
                data = await self._gather_info(task)

                # ステップ2: 分析
                await self.report_progress(task, 2, "分析中")
                analysis = await self._analyze(data)

                return {"analysis": analysis}
    """

    def __init__(self, task_queue: TaskQueue, pool=None):
        """
        Args:
            task_queue: タスクキュー
            pool: DB接続プール
        """
        self.task_queue = task_queue
        self.pool = pool

    async def run(self, task: AutonomousTask) -> Dict[str, Any]:
        """
        タスクを実行する（ライフサイクル管理付き）

        Args:
            task: 実行するタスク

        Returns:
            実行結果
        """
        # C.14 冪等性: 完了済み/キャンセル済みタスクの再実行防止
        if task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
            logger.info("Task already %s, skip: id=%s", task.status.value, task.id)
            return task.result or {}

        # アトミッククレーム: pending/failed → running（二重実行防止）
        claimed = await self.task_queue.claim(task.id)
        if not claimed:
            logger.info("Task claim failed (already running/completed): id=%s", task.id)
            return {"skipped": True, "reason": "already_processed"}

        try:
            # 実行
            result = await self.execute(task)

            # 完了
            await self.task_queue.update(
                task.id,
                status=TaskStatus.COMPLETED,
                progress_pct=100,
                result=result or {},
            )

            logger.info("Task completed: id=%s", task.id)
            return result or {}

        except Exception as e:
            # 失敗
            error_type = type(e).__name__
            await self.handle_error(task, e)
            logger.warning("Task failed: id=%s, error=%s", task.id, error_type)
            return {"error": error_type}

    @abstractmethod
    async def execute(self, task: AutonomousTask) -> Optional[Dict[str, Any]]:
        """
        タスクを実行する（サブクラスで実装）

        Args:
            task: 実行するタスク

        Returns:
            実行結果
        """
        ...

    async def report_progress(
        self,
        task: AutonomousTask,
        step: int,
        description: str = "",
    ) -> None:
        """
        進捗を報告する

        Args:
            task: タスク
            step: 現在のステップ番号
            description: ステップの説明
        """
        progress = (
            int(step / task.total_steps * 100) if task.total_steps > 0 else 0
        )
        await self.task_queue.update(
            task.id,
            current_step=step,
            progress_pct=min(progress, 99),  # 100%はcompletedのみ
        )
        logger.debug(
            "Task progress: id=%s, step=%d/%d, desc=%s",
            task.id, step, task.total_steps, description,
        )

    async def handle_error(
        self,
        task: AutonomousTask,
        error: Exception,
    ) -> None:
        """
        エラーを処理する

        Args:
            task: タスク
            error: 発生した例外
        """
        # PII漏洩防止: type名のみ記録
        error_type = type(error).__name__
        await self.task_queue.update(
            task.id,
            status=TaskStatus.FAILED,
            error_message=error_type,
        )
