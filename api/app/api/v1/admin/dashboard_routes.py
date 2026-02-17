"""
Admin Dashboard - Dashboard KPI Endpoints

ダッシュボードKPIサマリー取得。
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text

from lib.db import get_db_pool
from lib.logging import log_audit_event

from .deps import (
    JST,
    logger,
    require_admin,
    UserContext,
)
from app.schemas.admin import (
    DashboardSummaryResponse,
    DashboardKPIs,
    AlertSummary,
    InsightSummary,
    AdminErrorResponse,
)

router = APIRouter()


@router.get(
    "/dashboard/summary",
    response_model=DashboardSummaryResponse,
    responses={
        403: {"model": AdminErrorResponse, "description": "権限不足"},
        500: {"model": AdminErrorResponse, "description": "サーバーエラー"},
    },
    summary="ダッシュボードKPIサマリー取得",
    description="""
全KPIを1リクエストで返すバッチエンドポイント。

## データソース
- ai_usage_logs: 会話数、応答時間、エラー率、コスト
- ai_monthly_cost_summary: 月間予算
- bottleneck_alerts: アクティブアラート数

## パラメータ
- period: 集計期間（today/7d/30d）
    """,
)
async def get_dashboard_summary(
    period: str = Query(
        "today",
        pattern="^(today|7d|30d)$",
        description="集計期間（today/7d/30d）",
    ),
    user: UserContext = Depends(require_admin),
):
    """ダッシュボードKPIサマリーを取得"""

    organization_id = user.organization_id
    now = datetime.now(JST)

    # 集計期間の計算
    if period == "today":
        start_date = now.date()
    elif period == "7d":
        start_date = (now - timedelta(days=7)).date()
    else:  # 30d
        start_date = (now - timedelta(days=30)).date()

    logger.info(
        "Get dashboard summary",
        organization_id=organization_id,
        period=period,
        user_id=user.user_id,
    )

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            # --- KPI: 会話数・平均応答時間・エラー率・コスト ---
            usage_result = conn.execute(
                text("""
                    SELECT
                        COUNT(*) as total_conversations,
                        COALESCE(AVG(response_time_ms), 0) as avg_response_time_ms,
                        CASE
                            WHEN COUNT(*) > 0
                            THEN COALESCE(SUM(CASE WHEN is_error = TRUE THEN 1 ELSE 0 END)::float / COUNT(*), 0)
                            ELSE 0
                        END as error_rate,
                        COALESCE(SUM(cost_usd), 0) as total_cost
                    FROM ai_usage_logs
                    WHERE organization_id = :org_id
                      AND created_at >= :start_date
                """),
                {"org_id": organization_id, "start_date": start_date},
            )
            usage_row = usage_result.fetchone()

            total_conversations = int(usage_row[0]) if usage_row else 0
            avg_response_time_ms = float(usage_row[1]) if usage_row else 0.0
            error_rate = float(usage_row[2]) if usage_row else 0.0
            total_cost = float(usage_row[3]) if usage_row else 0.0

            # --- 今日のコスト（period問わず常にtodayを返す） ---
            today_cost_result = conn.execute(
                text("""
                    SELECT COALESCE(SUM(cost_usd), 0) as cost_today
                    FROM ai_usage_logs
                    WHERE organization_id = :org_id
                      AND created_at >= :today
                """),
                {"org_id": organization_id, "today": now.date()},
            )
            today_cost_row = today_cost_result.fetchone()
            cost_today = float(today_cost_row[0]) if today_cost_row else 0.0

            # --- 月間予算残 ---
            current_month = now.strftime("%Y-%m")
            budget_result = conn.execute(
                text("""
                    SELECT
                        COALESCE(budget_usd, 0) as budget,
                        COALESCE(total_cost_usd, 0) as spent
                    FROM ai_monthly_cost_summary
                    WHERE organization_id = :org_id
                      AND year_month = :year_month
                    LIMIT 1
                """),
                {"org_id": organization_id, "year_month": current_month},
            )
            budget_row = budget_result.fetchone()
            if budget_row:
                monthly_budget_remaining = float(budget_row[0]) - float(budget_row[1])
            else:
                monthly_budget_remaining = 0.0

            # --- アクティブアラート数 ---
            alerts_count_result = conn.execute(
                text("""
                    SELECT COUNT(*) as active_count
                    FROM bottleneck_alerts
                    WHERE organization_id::text = :org_id
                      AND status = 'active'
                """),
                {"org_id": organization_id},
            )
            alerts_count_row = alerts_count_result.fetchone()
            active_alerts_count = int(alerts_count_row[0]) if alerts_count_row else 0

            # --- 最近のアラート（最大5件） ---
            recent_alerts_result = conn.execute(
                text("""
                    SELECT id, bottleneck_type, risk_level, target_name, created_at, status
                    FROM bottleneck_alerts
                    WHERE organization_id::text = :org_id
                    ORDER BY created_at DESC
                    LIMIT 5
                """),
                {"org_id": organization_id},
            )
            recent_alerts = []
            for row in recent_alerts_result.fetchall():
                recent_alerts.append(
                    AlertSummary(
                        id=str(row[0]),
                        alert_type=row[1] or "unknown",
                        severity=row[2] or "info",
                        message=row[3] or "",
                        created_at=row[4],
                        is_resolved=(row[5] != "active") if row[5] else False,
                    )
                )

            # --- 最近のインサイト（最大5件） ---
            recent_insights_result = conn.execute(
                text("""
                    SELECT id, insight_type, title, summary, created_at
                    FROM brain_insights
                    WHERE organization_id = :org_id
                    ORDER BY created_at DESC
                    LIMIT 5
                """),
                {"org_id": organization_id},
            )
            recent_insights = []
            for row in recent_insights_result.fetchall():
                recent_insights.append(
                    InsightSummary(
                        id=str(row[0]),
                        insight_type=row[1] or "general",
                        title=row[2] or "",
                        summary=row[3] or "",
                        created_at=row[4],
                    )
                )

        # 監査ログ
        log_audit_event(
            logger=logger,
            action="get_dashboard_summary",
            resource_type="dashboard",
            resource_id=organization_id,
            user_id=user.user_id,
            details={"period": period},
        )

        return DashboardSummaryResponse(
            status="success",
            period=period,
            kpis=DashboardKPIs(
                total_conversations=total_conversations,
                avg_response_time_ms=round(avg_response_time_ms, 2),
                error_rate=round(error_rate, 4),
                total_cost_today=round(cost_today, 4),
                monthly_budget_remaining=round(monthly_budget_remaining, 4),
                active_alerts_count=active_alerts_count,
            ),
            recent_alerts=recent_alerts,
            recent_insights=recent_insights,
            generated_at=now,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Get dashboard summary error",
            organization_id=organization_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failed",
                "error_code": "INTERNAL_ERROR",
                "error_message": "内部エラーが発生しました",
            },
        )
