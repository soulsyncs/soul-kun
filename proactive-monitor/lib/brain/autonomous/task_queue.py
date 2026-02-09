# lib/brain/autonomous/task_queue.py
"""
Phase AA: タスクキューサービス

自律タスクのCRUD操作とキュー管理を提供する。
DBバックエンド（autonomous_tasks テーブル）を使用。

CLAUDE.md §3 鉄則:
  #1: 全テーブルにorganization_id
  #5: 1000件超えはページネーション
  #9: SQLはパラメータ化
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# =========================================================================
# データモデル
# =========================================================================


class TaskStatus(str, Enum):
    """タスクのステータス"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskType(str, Enum):
    """タスクのタイプ"""
    RESEARCH = "research"
    REMINDER = "reminder"
    REPORT = "report"
    ANALYSIS = "analysis"
    NOTIFICATION = "notification"


@dataclass
class AutonomousTask:
    """自律タスク"""
    id: Optional[str] = None
    organization_id: str = ""
    title: str = ""
    description: str = ""
    task_type: str = "research"
    status: TaskStatus = TaskStatus.PENDING
    priority: int = 5
    execution_plan: Dict[str, Any] = field(default_factory=dict)
    progress_pct: int = 0
    current_step: int = 0
    total_steps: int = 0
    result: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    requested_by: Optional[str] = None
    room_id: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """辞書に変換"""
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "title": self.title,
            "description": self.description,
            "task_type": self.task_type,
            "status": self.status.value if isinstance(self.status, TaskStatus) else self.status,
            "priority": self.priority,
            "progress_pct": self.progress_pct,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "requested_by": self.requested_by,
            "room_id": self.room_id,
        }


# =========================================================================
# タスクキュー
# =========================================================================


class TaskQueue:
    """
    自律タスクのキュー管理

    autonomous_tasks テーブルをバックエンドとしたCRUD操作を提供。
    """

    def __init__(self, pool, org_id: str):
        """
        Args:
            pool: SQLAlchemy接続プール
            org_id: 組織ID
        """
        if not org_id:
            raise ValueError("org_id must not be empty")
        self.pool = pool
        self.org_id = org_id

    async def create(self, task: AutonomousTask) -> Optional[AutonomousTask]:
        """
        タスクを作成

        Args:
            task: 作成するタスク

        Returns:
            作成されたタスク（IDが付与される）
        """
        if not self.pool:
            return None

        task.organization_id = self.org_id

        try:
            from sqlalchemy import text
            import json

            def _sync_create():
                with self.pool.connect() as conn:
                    conn.execute(
                        text("SELECT set_config('app.current_organization_id', :org_id, false)"),
                        {"org_id": self.org_id},
                    )
                    result = conn.execute(
                        text("""
                            INSERT INTO autonomous_tasks
                                (organization_id, title, description, task_type,
                                 status, priority, execution_plan,
                                 total_steps, requested_by, room_id,
                                 scheduled_at)
                            VALUES
                                (:org_id::uuid, :title, :desc, :type,
                                 :status, :priority, :plan::jsonb,
                                 :total_steps, :requested_by, :room_id,
                                 :scheduled_at)
                            RETURNING id, created_at
                        """),
                        {
                            "org_id": self.org_id,
                            "title": task.title,
                            "desc": task.description,
                            "type": task.task_type,
                            "status": task.status.value,
                            "priority": task.priority,
                            "plan": json.dumps(task.execution_plan),
                            "total_steps": task.total_steps,
                            "requested_by": task.requested_by,
                            "room_id": task.room_id,
                            "scheduled_at": task.scheduled_at,
                        },
                    )
                    row = result.mappings().first()
                    conn.commit()
                    return row

            row = await asyncio.to_thread(_sync_create)
            if row:
                task.id = str(row["id"])
                task.created_at = row["created_at"]
                logger.info("Task created: id=%s, title=%s", task.id, task.title)
                return task

        except Exception as e:
            logger.warning("Failed to create task: %s", type(e).__name__)

        return None

    async def get(self, task_id: str) -> Optional[AutonomousTask]:
        """
        タスクを取得

        Args:
            task_id: タスクID

        Returns:
            タスク（見つからない場合はNone）
        """
        if not self.pool:
            return None

        try:
            from sqlalchemy import text

            def _sync_get():
                with self.pool.connect() as conn:
                    conn.execute(
                        text("SELECT set_config('app.current_organization_id', :org_id, false)"),
                        {"org_id": self.org_id},
                    )
                    row = conn.execute(
                        text("""
                            SELECT * FROM autonomous_tasks
                            WHERE id = :id AND organization_id = :org_id::uuid
                        """),
                        {"id": task_id, "org_id": self.org_id},
                    ).mappings().first()
                    return row

            row = await asyncio.to_thread(_sync_get)
            if row:
                return self._row_to_task(row)

        except Exception as e:
            logger.warning("Failed to get task: %s", type(e).__name__)

        return None

    async def update(
        self,
        task_id: str,
        status: Optional[TaskStatus] = None,
        progress_pct: Optional[int] = None,
        current_step: Optional[int] = None,
        result: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> bool:
        """
        タスクを更新

        Args:
            task_id: タスクID
            status: 新しいステータス
            progress_pct: 進捗率
            current_step: 現在のステップ
            result: 結果
            error_message: エラーメッセージ

        Returns:
            更新に成功したか
        """
        if not self.pool:
            return False

        updates = []
        params: Dict[str, Any] = {
            "id": task_id,
            "org_id": self.org_id,
        }

        if status is not None:
            updates.append("status = :status")
            params["status"] = status.value
            if status == TaskStatus.RUNNING:
                updates.append("started_at = NOW()")
            elif status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                updates.append("completed_at = NOW()")

        if progress_pct is not None:
            updates.append("progress_pct = :progress")
            params["progress"] = progress_pct

        if current_step is not None:
            updates.append("current_step = :step")
            params["step"] = current_step

        if result is not None:
            import json
            updates.append("result = :result::jsonb")
            params["result"] = json.dumps(result)

        if error_message is not None:
            updates.append("error_message = :error")
            params["error"] = error_message

        if not updates:
            return True

        try:
            from sqlalchemy import text

            set_clause = ", ".join(updates)
            sql = f"""
                UPDATE autonomous_tasks
                SET {set_clause}
                WHERE id = :id AND organization_id = :org_id::uuid
            """

            def _sync_update():
                with self.pool.connect() as conn:
                    conn.execute(
                        text("SELECT set_config('app.current_organization_id', :org_id, false)"),
                        {"org_id": self.org_id},
                    )
                    conn.execute(text(sql), params)
                    conn.commit()

            await asyncio.to_thread(_sync_update)
            return True

        except Exception as e:
            logger.warning("Failed to update task: %s", type(e).__name__)
            return False

    async def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[AutonomousTask]:
        """
        タスク一覧を取得

        Args:
            status: ステータスフィルタ
            limit: 取得件数（最大1000）
            offset: オフセット

        Returns:
            タスクのリスト
        """
        if not self.pool:
            return []

        limit = min(limit, 1000)  # 鉄則#5: ページネーション

        try:
            from sqlalchemy import text

            where_clauses = ["organization_id = :org_id::uuid"]
            params: Dict[str, Any] = {
                "org_id": self.org_id,
                "limit": limit,
                "offset": offset,
            }

            if status is not None:
                where_clauses.append("status = :status")
                params["status"] = status.value

            where = " AND ".join(where_clauses)
            sql = f"""
                SELECT * FROM autonomous_tasks
                WHERE {where}
                ORDER BY priority ASC, created_at DESC
                LIMIT :limit OFFSET :offset
            """

            def _sync_list():
                with self.pool.connect() as conn:
                    conn.execute(
                        text("SELECT set_config('app.current_organization_id', :org_id, false)"),
                        {"org_id": self.org_id},
                    )
                    rows = conn.execute(text(sql), params).mappings().all()
                    return rows

            rows = await asyncio.to_thread(_sync_list)
            return [self._row_to_task(row) for row in rows]

        except Exception as e:
            logger.warning("Failed to list tasks: %s", type(e).__name__)
            return []

    def _row_to_task(self, row) -> AutonomousTask:
        """DBの行をAutonomousTaskに変換"""
        return AutonomousTask(
            id=str(row["id"]),
            organization_id=str(row["organization_id"]),
            title=row["title"],
            description=row.get("description", ""),
            task_type=row["task_type"],
            status=TaskStatus(row["status"]),
            priority=row.get("priority", 5),
            execution_plan=row.get("execution_plan") or {},
            progress_pct=row.get("progress_pct", 0),
            current_step=row.get("current_step", 0),
            total_steps=row.get("total_steps", 0),
            result=row.get("result") or {},
            error_message=row.get("error_message"),
            requested_by=row.get("requested_by"),
            room_id=row.get("room_id"),
            scheduled_at=row.get("scheduled_at"),
            started_at=row.get("started_at"),
            completed_at=row.get("completed_at"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )
