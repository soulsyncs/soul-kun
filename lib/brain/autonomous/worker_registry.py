# lib/brain/autonomous/worker_registry.py
"""
Phase AA: ワーカーレジストリ

TaskType → Worker のマッピングを管理する。
新しいワーカーはここに登録するだけで利用可能になる。

CLAUDE.md S1: Brain経由で機能を実行
"""

import logging
from typing import Dict, Optional, Type

from lib.brain.autonomous.task_queue import TaskQueue
from lib.brain.autonomous.worker import BaseWorker

logger = logging.getLogger(__name__)


class WorkerRegistry:
    """
    TaskType→Workerのマッピングを管理するレジストリ

    Usage:
        registry = WorkerRegistry(task_queue=queue, pool=pool)
        registry.register("research", ResearchWorker)
        worker = registry.get_worker("research")
    """

    def __init__(self, task_queue: TaskQueue, pool=None):
        self.task_queue = task_queue
        self.pool = pool
        self._workers: Dict[str, Type[BaseWorker]] = {}
        self._instances: Dict[str, BaseWorker] = {}

    def register(self, task_type: str, worker_class: Type[BaseWorker]) -> None:
        """ワーカークラスを登録"""
        self._workers[task_type] = worker_class
        logger.debug("Worker registered: %s -> %s", task_type, worker_class.__name__)

    def get_worker(self, task_type: str) -> Optional[BaseWorker]:
        """タスクタイプに対応するワーカーインスタンスを取得（キャッシュ付き）"""
        if task_type in self._instances:
            return self._instances[task_type]

        worker_class = self._workers.get(task_type)
        if not worker_class:
            logger.warning("No worker for task_type: %s", task_type)
            return None

        instance = worker_class(task_queue=self.task_queue, pool=self.pool)
        self._instances[task_type] = instance
        return instance

    def list_types(self) -> list:
        """登録済みタスクタイプ一覧"""
        return list(self._workers.keys())
