"""
Admin Dashboard - Wellness/Emotion Endpoints

感情アラート一覧、感情トレンド取得。
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
    "/wellness/alerts",
    summary="感情アラート一覧",
    description="アクティブな感情アラートを取得（Level 5+）",
)
async def get_emotion_alerts(
    user: UserContext = Depends(require_admin),
    risk_level: Optional[str] = Query(None, description="リスクレベルフィルタ"),
    alert_status: Optional[str] = Query(None, alias="status", description="ステータスフィルタ"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            where_clauses = ["ea.organization_id = :org_id"]
            params: dict = {"org_id": organization_id, "limit": limit, "offset": offset}

            if risk_level:
                where_clauses.append("ea.risk_level = :risk_level")
                params["risk_level"] = risk_level
            if alert_status:
                where_clauses.append("ea.status = :alert_status")
                params["alert_status"] = alert_status

            where_sql = " AND ".join(where_clauses)

            result = conn.execute(
                text(f"""
                    SELECT ea.id, ea.user_id, ea.user_name,
                           d.name AS department_name,
                           ea.alert_type, ea.risk_level,
                           ea.baseline_score, ea.current_score, ea.score_change,
                           ea.consecutive_negative_days, ea.status,
                           ea.first_detected_at, ea.last_detected_at
                    FROM emotion_alerts ea
                    LEFT JOIN departments d ON ea.department_id = d.id
                    WHERE {where_sql}
                    ORDER BY ea.last_detected_at DESC
                    LIMIT :limit OFFSET :offset
                """),
                params,
            )
            rows = result.fetchall()

            count_result = conn.execute(
                text(f"SELECT COUNT(*) FROM emotion_alerts ea WHERE {where_sql}"),
                params,
            )
            total = int(count_result.fetchone()[0])

        from app.schemas.admin import EmotionAlertSummary, EmotionAlertsResponse

        alerts = [
            EmotionAlertSummary(
                id=str(r[0]), user_id=str(r[1]),
                user_name=r[2], department_name=r[3],
                alert_type=r[4], risk_level=r[5],
                baseline_score=float(r[6]) if r[6] is not None else None,
                current_score=float(r[7]) if r[7] is not None else None,
                score_change=float(r[8]) if r[8] is not None else None,
                consecutive_negative_days=r[9],
                status=r[10],
                first_detected_at=str(r[11]) if r[11] else None,
                last_detected_at=str(r[12]) if r[12] else None,
            )
            for r in rows
        ]

        log_audit_event(
            logger=logger, action="get_emotion_alerts",
            resource_type="emotion_alerts", resource_id="list",
            user_id=user.user_id, details={"count": len(alerts)},
        )
        return EmotionAlertsResponse(alerts=alerts, total_count=total)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get emotion alerts error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )


@router.get(
    "/wellness/trends",
    summary="感情トレンド取得",
    description="組織全体の感情スコア推移を取得（Level 5+）",
)
async def get_emotion_trends(
    user: UserContext = Depends(require_admin),
    days: int = Query(30, ge=7, le=90, description="取得期間（日数）"),
    department_id: Optional[str] = Query(None, description="部署IDフィルタ"),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            extra_join = ""
            extra_where = ""
            params: dict = {"org_id": organization_id, "days": days}

            if department_id:
                extra_join = """
                    JOIN user_departments ud ON es.user_id = ud.user_id AND ud.ended_at IS NULL
                """
                extra_where = "AND ud.department_id = :dept_id"
                params["dept_id"] = department_id

            result = conn.execute(
                text(f"""
                    SELECT
                        DATE(es.message_time) AS date,
                        AVG(es.sentiment_score) AS avg_score,
                        COUNT(*) AS message_count,
                        COUNT(*) FILTER (WHERE es.sentiment_label IN ('negative', 'very_negative')) AS negative_count,
                        COUNT(*) FILTER (WHERE es.sentiment_label IN ('positive', 'very_positive')) AS positive_count
                    FROM emotion_scores es
                    {extra_join}
                    WHERE es.organization_id = :org_id
                      AND es.message_time >= CURRENT_DATE - (INTERVAL '1 day' * :days)
                      {extra_where}
                    GROUP BY DATE(es.message_time)
                    ORDER BY date
                """),
                params,
            )
            rows = result.fetchall()

        from app.schemas.admin import EmotionTrendEntry, EmotionTrendsResponse

        trends = [
            EmotionTrendEntry(
                date=str(r[0]), avg_score=round(float(r[1]), 3),
                message_count=int(r[2]), negative_count=int(r[3]), positive_count=int(r[4]),
            )
            for r in rows
        ]

        log_audit_event(
            logger=logger, action="get_emotion_trends",
            resource_type="emotion_scores", resource_id="trends",
            user_id=user.user_id, details={"days": days},
        )
        return EmotionTrendsResponse(
            trends=trends,
            period_start=str(rows[0][0]) if rows else None,
            period_end=str(rows[-1][0]) if rows else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get emotion trends error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )
