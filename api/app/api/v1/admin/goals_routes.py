"""
Admin Dashboard - Goals Endpoints

目標一覧取得、目標達成率サマリー、目標詳細取得。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
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
    "/goals",
    summary="目標一覧取得",
    description="全目標をフィルタ付きで取得（Level 5+）",
)
async def get_goals_list(
    user: UserContext = Depends(require_admin),
    status_filter: Optional[str] = Query(None, alias="status", description="ステータスフィルタ"),
    department_id: Optional[str] = Query(None, description="部署IDフィルタ"),
    period_type: Optional[str] = Query(None, description="期間種別フィルタ"),
    limit: int = Query(50, ge=1, le=200, description="取得件数"),
    offset: int = Query(0, ge=0, description="オフセット"),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            where_clauses = ["g.organization_id = :org_id"]
            params: dict = {"org_id": organization_id, "limit": limit, "offset": offset}

            if status_filter:
                where_clauses.append("g.status = :status")
                params["status"] = status_filter
            if department_id:
                where_clauses.append("g.department_id = :dept_id")
                params["dept_id"] = department_id
            if period_type:
                where_clauses.append("g.period_type = :period_type")
                params["period_type"] = period_type

            where_sql = " AND ".join(where_clauses)

            result = conn.execute(
                text(f"""
                    SELECT g.id, g.user_id, u.name AS user_name,
                           d.name AS department_name,
                           g.title, g.goal_type, g.goal_level, g.status,
                           g.period_type, g.period_start, g.period_end,
                           g.deadline, g.target_value, g.current_value, g.unit
                    FROM goals g
                    LEFT JOIN users u ON g.user_id = u.id
                    LEFT JOIN departments d ON g.department_id = d.id
                    WHERE {where_sql}
                    ORDER BY g.created_at DESC
                    LIMIT :limit OFFSET :offset
                """),
                params,
            )
            rows = result.fetchall()

            count_result = conn.execute(
                text(f"SELECT COUNT(*) FROM goals g WHERE {where_sql}"),
                params,
            )
            total = int(count_result.fetchone()[0])

        from app.schemas.admin import GoalSummary, GoalsListResponse

        goals = []
        for row in rows:
            target = float(row[12]) if row[12] is not None else None
            current = float(row[13]) if row[13] is not None else None
            progress = (current / target * 100) if target and current is not None and target > 0 else None
            goals.append(GoalSummary(
                id=str(row[0]), user_id=str(row[1]),
                user_name=row[2], department_name=row[3],
                title=row[4], goal_type=row[5], goal_level=row[6],
                status=row[7], period_type=row[8],
                period_start=str(row[9]) if row[9] else None,
                period_end=str(row[10]) if row[10] else None,
                deadline=str(row[11]) if row[11] else None,
                target_value=target, current_value=current,
                unit=row[14], progress_pct=round(progress, 1) if progress is not None else None,
            ))

        log_audit_event(
            logger=logger, action="get_goals_list",
            resource_type="goals", resource_id="list",
            user_id=user.user_id, details={"count": len(goals)},
        )
        return GoalsListResponse(goals=goals, total_count=total)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get goals list error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )


@router.get(
    "/goals/stats",
    summary="目標達成率サマリー",
    description="全社/部署別の目標達成率を取得（Level 5+）",
)
async def get_goals_stats(
    user: UserContext = Depends(require_admin),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (WHERE status = 'active') AS active,
                        COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                        COUNT(*) FILTER (WHERE status = 'active' AND deadline < CURRENT_DATE) AS overdue
                    FROM goals
                    WHERE organization_id = :org_id
                """),
                {"org_id": organization_id},
            )
            stats = result.fetchone()
            total = int(stats[0])
            completed = int(stats[2])
            rate = (completed / total * 100) if total > 0 else 0.0

            dept_result = conn.execute(
                text("""
                    SELECT d.name,
                           COUNT(*) AS total,
                           COUNT(*) FILTER (WHERE g.status = 'completed') AS completed
                    FROM goals g
                    JOIN departments d ON g.department_id = d.id
                    WHERE g.organization_id = :org_id
                    GROUP BY d.name
                    ORDER BY total DESC
                """),
                {"org_id": organization_id},
            )
            by_dept = [
                {"department": r[0], "total": int(r[1]), "completed": int(r[2]),
                 "rate": round(int(r[2]) / int(r[1]) * 100, 1) if int(r[1]) > 0 else 0.0}
                for r in dept_result.fetchall()
            ]

        from app.schemas.admin import GoalStatsResponse

        log_audit_event(
            logger=logger, action="get_goals_stats",
            resource_type="goals", resource_id="stats",
            user_id=user.user_id, details={},
        )
        return GoalStatsResponse(
            total_goals=total, active_goals=int(stats[1]),
            completed_goals=completed, overdue_goals=int(stats[3]),
            completion_rate=round(rate, 1), by_department=by_dept,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get goals stats error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )


@router.get(
    "/goals/{goal_id}",
    summary="目標詳細取得",
    description="目標の詳細と進捗履歴を取得（Level 5+）",
)
async def get_goal_detail(
    goal_id: str = Path(..., pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
    user: UserContext = Depends(require_admin),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT g.id, g.user_id, u.name AS user_name,
                           d.name AS department_name,
                           g.title, g.goal_type, g.goal_level, g.status,
                           g.period_type, g.period_start, g.period_end,
                           g.deadline, g.target_value, g.current_value, g.unit
                    FROM goals g
                    LEFT JOIN users u ON g.user_id = u.id
                    LEFT JOIN departments d ON g.department_id = d.id
                    WHERE g.id = :goal_id AND g.organization_id = :org_id
                """),
                {"goal_id": goal_id, "org_id": organization_id},
            )
            row = result.fetchone()
            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"status": "failed", "error_code": "GOAL_NOT_FOUND", "error_message": "目標が見つかりません"},
                )

            target = float(row[12]) if row[12] is not None else None
            current = float(row[13]) if row[13] is not None else None
            progress = (current / target * 100) if target and current is not None and target > 0 else None

            from app.schemas.admin import GoalSummary, GoalProgressEntry, GoalDetailResponse

            goal = GoalSummary(
                id=str(row[0]), user_id=str(row[1]),
                user_name=row[2], department_name=row[3],
                title=row[4], goal_type=row[5], goal_level=row[6],
                status=row[7], period_type=row[8],
                period_start=str(row[9]) if row[9] else None,
                period_end=str(row[10]) if row[10] else None,
                deadline=str(row[11]) if row[11] else None,
                target_value=target, current_value=current,
                unit=row[14], progress_pct=round(progress, 1) if progress is not None else None,
            )

            progress_result = conn.execute(
                text("""
                    SELECT id, progress_date, value, cumulative_value, daily_note
                    FROM goal_progress
                    WHERE goal_id = :goal_id AND organization_id = :org_id
                    ORDER BY progress_date DESC
                    LIMIT 90
                """),
                {"goal_id": goal_id, "org_id": organization_id},
            )
            progress_entries = [
                GoalProgressEntry(
                    id=str(p[0]), progress_date=str(p[1]),
                    value=float(p[2]) if p[2] is not None else None,
                    cumulative_value=float(p[3]) if p[3] is not None else None,
                    daily_note=p[4],
                )
                for p in progress_result.fetchall()
            ]

        log_audit_event(
            logger=logger, action="get_goal_detail",
            resource_type="goal", resource_id=goal_id,
            user_id=user.user_id, details={},
        )
        return GoalDetailResponse(goal=goal, progress=progress_entries)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get goal detail error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )
