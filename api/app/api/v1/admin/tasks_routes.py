"""
Admin Dashboard - Tasks Endpoints

タスク全体サマリー、タスク一覧取得。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text

from lib.db import get_db_pool
from lib.logging import log_audit_event

from .deps import (
    DEFAULT_ORG_ID,
    logger,
    require_admin,
    UserContext,
)

router = APIRouter()


@router.get(
    "/tasks/overview",
    summary="タスク全体サマリー",
    description="ChatWork/自律/検出タスクの全体サマリー（Level 5+）",
)
async def get_tasks_overview(
    user: UserContext = Depends(require_admin),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            # ChatWork tasks
            cw_result = conn.execute(
                text("""
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (WHERE status = 'open') AS open,
                        COUNT(*) FILTER (WHERE status = 'done') AS done,
                        COUNT(*) FILTER (WHERE status = 'open' AND limit_time IS NOT NULL
                                         AND to_timestamp(limit_time) < NOW()) AS overdue
                    FROM chatwork_tasks
                    WHERE organization_id = :org_id
                """),
                {"org_id": organization_id},
            )
            cw = cw_result.fetchone()

            # Autonomous tasks (table may not exist yet)
            try:
                at_result = conn.execute(
                    text("""
                        SELECT
                            COUNT(*) AS total,
                            COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                            COUNT(*) FILTER (WHERE status = 'running') AS running,
                            COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                            COUNT(*) FILTER (WHERE status = 'failed') AS failed
                        FROM autonomous_tasks
                        WHERE organization_id = :org_id
                    """),
                    {"org_id": organization_id},
                )
                at = at_result.fetchone()
            except Exception:
                conn.rollback()
                at = (0, 0, 0, 0, 0)

            # Detected tasks
            dt_result = conn.execute(
                text("""
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (WHERE status = 'processed') AS processed,
                        COUNT(*) FILTER (WHERE status != 'processed' OR status IS NULL) AS unprocessed
                    FROM detected_tasks
                    WHERE organization_id = :org_id
                """),
                {"org_id": organization_id},
            )
            dt = dt_result.fetchone()

        from app.schemas.admin import TaskOverviewStats

        log_audit_event(
            logger=logger, action="get_tasks_overview",
            resource_type="tasks", resource_id="overview",
            user_id=user.user_id, details={},
        )
        return TaskOverviewStats(
            chatwork_tasks={"total": int(cw[0]), "open": int(cw[1]), "done": int(cw[2]), "overdue": int(cw[3])},
            autonomous_tasks={"total": int(at[0]), "pending": int(at[1]), "running": int(at[2]),
                              "completed": int(at[3]), "failed": int(at[4])},
            detected_tasks={"total": int(dt[0]), "processed": int(dt[1]), "unprocessed": int(dt[2])},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get tasks overview error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )


@router.get(
    "/tasks/list",
    summary="タスク一覧取得",
    description="全タスクソースを統合した一覧（Level 5+）",
)
async def get_tasks_list(
    user: UserContext = Depends(require_admin),
    source: Optional[str] = Query(None, description="ソースフィルタ（chatwork/autonomous/detected）"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            tasks = []

            if source is None or source == "chatwork":
                cw_result = conn.execute(
                    text("""
                        SELECT task_id::text, summary, body, status,
                               assigned_to_name, limit_time, created_at
                        FROM chatwork_tasks
                        WHERE organization_id = :org_id
                        ORDER BY created_at DESC
                        LIMIT :limit OFFSET :offset
                    """),
                    {"org_id": organization_id, "limit": limit, "offset": offset},
                )
                for r in cw_result.fetchall():
                    title = r[1] or (r[2][:80] + "..." if r[2] and len(r[2]) > 80 else r[2] or "")
                    deadline = None
                    if r[5]:
                        from datetime import datetime as dt_mod
                        deadline = dt_mod.utcfromtimestamp(int(r[5])).strftime("%Y-%m-%d")
                    tasks.append({"id": r[0], "source": "chatwork", "title": title,
                                  "status": r[3] or "unknown", "assignee_name": r[4],
                                  "deadline": deadline,
                                  "created_at": str(r[6]) if r[6] else None})

            if source is None or source == "autonomous":
                try:
                    at_result = conn.execute(
                        text("""
                            SELECT id::text, title, status, requested_by, scheduled_at, created_at
                            FROM autonomous_tasks
                            WHERE organization_id = :org_id
                            ORDER BY created_at DESC
                            LIMIT :limit OFFSET :offset
                        """),
                        {"org_id": organization_id, "limit": limit, "offset": offset},
                    )
                    for r in at_result.fetchall():
                        tasks.append({"id": r[0], "source": "autonomous", "title": r[1],
                                      "status": r[2], "assignee_name": r[3],
                                      "deadline": str(r[4]) if r[4] else None,
                                      "created_at": str(r[5]) if r[5] else None})
                except Exception:
                    conn.rollback()

            if source is None or source == "detected":
                dt_result = conn.execute(
                    text("""
                        SELECT id::text, task_content, status, account_id, NULL, detected_at
                        FROM detected_tasks
                        WHERE organization_id = :org_id
                        ORDER BY detected_at DESC
                        LIMIT :limit OFFSET :offset
                    """),
                    {"org_id": organization_id, "limit": limit, "offset": offset},
                )
                for r in dt_result.fetchall():
                    tasks.append({"id": r[0], "source": "detected", "title": r[1] or "",
                                  "status": r[2] or "detected", "assignee_name": r[3],
                                  "deadline": r[4],
                                  "created_at": str(r[5]) if r[5] else None})

        # Sort by created_at descending
        tasks.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        tasks = tasks[:limit]

        from app.schemas.admin import TaskItem, TaskListResponse

        task_items = [TaskItem(**t) for t in tasks]

        log_audit_event(
            logger=logger, action="get_tasks_list",
            resource_type="tasks", resource_id="list",
            user_id=user.user_id, details={"count": len(task_items), "source": source},
        )
        return TaskListResponse(tasks=task_items, total_count=len(task_items))

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get tasks list error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )
