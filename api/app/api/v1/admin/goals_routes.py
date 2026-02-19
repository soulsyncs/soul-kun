"""
Admin Dashboard - Goals Endpoints

目標一覧取得、目標達成率サマリー、目標詳細取得、未来予測。
"""

from datetime import date, timedelta
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


def _linear_regression(x_vals: list, y_vals: list):
    """単純線形回帰 (slope, intercept) を返す。データ不足の場合は (None, None)"""
    n = len(x_vals)
    if n < 2:
        return None, None
    sum_x = sum(x_vals)
    sum_y = sum(y_vals)
    sum_xy = sum(x * y for x, y in zip(x_vals, y_vals))
    sum_x2 = sum(x * x for x in x_vals)
    denom = n * sum_x2 - sum_x * sum_x
    if denom == 0:
        return None, None
    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n
    return slope, intercept


@router.get(
    "/goals/forecast",
    summary="目標の未来予測",
    description="進捗履歴から線形回帰で各目標の達成予測日を算出（Level 5+）",
)
async def get_goals_forecast(
    user: UserContext = Depends(require_admin),
):
    organization_id = user.organization_id
    today = date.today()

    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            # 進行中の目標を取得
            goals_result = conn.execute(
                text("""
                    SELECT g.id, g.title, u.name AS user_name,
                           d.name AS department_name,
                           g.target_value, g.current_value, g.unit,
                           g.deadline, g.period_start
                    FROM goals g
                    LEFT JOIN users u ON g.user_id = u.id
                    LEFT JOIN departments d ON g.department_id = d.id
                    WHERE g.organization_id = :org_id
                      AND g.status = 'active'
                    ORDER BY g.deadline ASC NULLS LAST
                """),
                {"org_id": organization_id},
            )
            goals_rows = goals_result.fetchall()

            # 進捗履歴を取得（直近60日分）
            progress_result = conn.execute(
                text("""
                    SELECT goal_id, progress_date,
                           COALESCE(cumulative_value, value) AS val
                    FROM goal_progress
                    WHERE organization_id = :org_id
                      AND progress_date >= :since
                      AND (cumulative_value IS NOT NULL OR value IS NOT NULL)
                    ORDER BY goal_id, progress_date ASC
                """),
                {"org_id": organization_id, "since": today - timedelta(days=60)},
            )
            progress_map: dict = {}
            for p in progress_result.fetchall():
                gid = str(p[0])
                if gid not in progress_map:
                    progress_map[gid] = []
                progress_map[gid].append((p[1], float(p[2]) if p[2] is not None else None))

        from app.schemas.admin import GoalForecastItem, GoalForecastResponse

        forecasts = []
        ahead = on_track = at_risk = stalled_n = 0

        for row in goals_rows:
            gid = str(row[0])
            title = str(row[1])
            user_name = row[2]
            dept_name = row[3]
            target = float(row[4]) if row[4] is not None else None
            current = float(row[5]) if row[5] is not None else None
            unit = row[6]
            deadline = row[7]  # date object or None
            period_start = row[8]  # date object or None

            # 進捗なし or 目標値なし
            if target is None or target <= 0:
                forecasts.append(GoalForecastItem(
                    id=gid, title=title, user_name=user_name,
                    department_name=dept_name, forecast_status="no_data",
                    current_value=current, target_value=target, unit=unit,
                    deadline=str(deadline) if deadline else None,
                ))
                continue

            progress_pct = round(current / target * 100, 1) if current is not None else 0.0

            # 線形回帰の基準点（period_start or 最初の進捗日から）
            entries = [(e[0], e[1]) for e in (progress_map.get(gid) or []) if e[1] is not None]
            if len(entries) < 2:
                # 進捗データが不足 → 直近の値を使って推定
                if current is not None and current >= target:
                    forecast_status = "ahead"
                    ahead += 1
                else:
                    forecast_status = "no_data"
                forecasts.append(GoalForecastItem(
                    id=gid, title=title, user_name=user_name,
                    department_name=dept_name, forecast_status=forecast_status,
                    progress_pct=progress_pct, current_value=current,
                    target_value=target, unit=unit,
                    deadline=str(deadline) if deadline else None,
                ))
                continue

            # 線形回帰：x = days since first entry, y = cumulative_value
            base_date = entries[0][0]
            x_vals = [(e[0] - base_date).days for e in entries]
            y_vals = [e[1] for e in entries]
            slope, intercept = _linear_regression(x_vals, y_vals)

            if slope is None or slope <= 0:
                forecast_status = "stalled"
                stalled_n += 1
                forecasts.append(GoalForecastItem(
                    id=gid, title=title, user_name=user_name,
                    department_name=dept_name, forecast_status=forecast_status,
                    progress_pct=progress_pct, current_value=current,
                    target_value=target, unit=unit, slope_per_day=slope,
                    deadline=str(deadline) if deadline else None,
                ))
                continue

            # 予測達成日を計算
            days_to_target = (target - intercept) / slope
            projected_date = base_date + timedelta(days=int(days_to_target))

            days_to_deadline = (deadline - today).days if deadline else None
            days_ahead_or_behind = None
            if deadline:
                days_ahead_or_behind = (projected_date - deadline).days

            # ステータス判定
            if current is not None and current >= target:
                forecast_status = "ahead"
                ahead += 1
            elif days_ahead_or_behind is None:
                forecast_status = "on_track"
                on_track += 1
            elif days_ahead_or_behind <= -15:
                forecast_status = "ahead"
                ahead += 1
            elif days_ahead_or_behind <= 0:
                forecast_status = "on_track"
                on_track += 1
            else:
                forecast_status = "at_risk"
                at_risk += 1

            forecasts.append(GoalForecastItem(
                id=gid, title=title, user_name=user_name,
                department_name=dept_name, forecast_status=forecast_status,
                progress_pct=progress_pct, current_value=current,
                target_value=target, unit=unit, slope_per_day=round(slope, 4),
                deadline=str(deadline) if deadline else None,
                projected_completion_date=str(projected_date),
                days_to_deadline=days_to_deadline,
                days_ahead_or_behind=days_ahead_or_behind,
            ))

        log_audit_event(
            logger=logger, action="get_goals_forecast",
            resource_type="goals", resource_id="forecast",
            user_id=user.user_id,
            details={"total": len(forecasts), "at_risk": at_risk},
        )
        return GoalForecastResponse(
            status="success",
            total_active=len(goals_rows),
            ahead_count=ahead,
            on_track_count=on_track,
            at_risk_count=at_risk,
            stalled_count=stalled_n,
            forecasts=forecasts,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get goals forecast error", organization_id=organization_id)
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
