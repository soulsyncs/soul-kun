"""
Admin Dashboard - System Health Endpoints

システムヘルスサマリー、メトリクス推移、自己診断一覧。
"""

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
    "/system/health",
    summary="システムヘルスサマリー",
    description="最新日のシステムヘルスサマリー（Level 5+）",
)
async def get_system_health(
    user: UserContext = Depends(require_admin),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT metric_date, total_conversations, unique_users,
                           avg_response_time_ms, p95_response_time_ms,
                           success_count, error_count, avg_confidence
                    FROM brain_daily_metrics
                    WHERE organization_id = :org_id
                    ORDER BY metric_date DESC
                    LIMIT 1
                """),
                {"org_id": organization_id},
            )
            row = result.fetchone()

        from app.schemas.admin import SystemHealthSummary

        if not row:
            return SystemHealthSummary()

        total = (int(row[5] or 0) + int(row[6] or 0))
        success_rate = round(int(row[5] or 0) / total * 100, 1) if total > 0 else 0.0

        log_audit_event(
            logger=logger, action="get_system_health",
            resource_type="system", resource_id="health",
            user_id=user.user_id, details={},
        )
        return SystemHealthSummary(
            latest_date=str(row[0]),
            total_conversations=int(row[1] or 0),
            unique_users=int(row[2] or 0),
            avg_response_time_ms=row[3],
            p95_response_time_ms=row[4],
            success_rate=success_rate,
            error_count=int(row[6] or 0),
            avg_confidence=round(float(row[7]), 3) if row[7] else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get system health error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )


@router.get(
    "/system/metrics",
    summary="システムメトリクス推移",
    description="日次メトリクスの推移（Level 5+）",
)
async def get_system_metrics(
    user: UserContext = Depends(require_admin),
    days: int = Query(30, ge=7, le=90, description="取得期間"),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT metric_date, total_conversations, unique_users,
                           avg_response_time_ms, success_count, error_count,
                           avg_confidence
                    FROM brain_daily_metrics
                    WHERE organization_id = :org_id
                      AND metric_date >= CURRENT_DATE - (INTERVAL '1 day' * :days)
                    ORDER BY metric_date
                """),
                {"org_id": organization_id, "days": days},
            )
            rows = result.fetchall()

        from app.schemas.admin import DailyMetricEntry, SystemMetricsResponse

        metrics = [
            DailyMetricEntry(
                metric_date=str(r[0]),
                total_conversations=int(r[1] or 0),
                unique_users=int(r[2] or 0),
                avg_response_time_ms=r[3],
                success_count=int(r[4] or 0),
                error_count=int(r[5] or 0),
                avg_confidence=round(float(r[6]), 3) if r[6] else None,
            )
            for r in rows
        ]

        log_audit_event(
            logger=logger, action="get_system_metrics",
            resource_type="system", resource_id="metrics",
            user_id=user.user_id, details={"days": days},
        )
        return SystemMetricsResponse(metrics=metrics)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get system metrics error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )


@router.get(
    "/system/diagnoses",
    summary="自己診断一覧",
    description="Brain自己診断の一覧（Level 5+）",
)
async def get_self_diagnoses(
    user: UserContext = Depends(require_admin),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        rows = []
        total = 0
        with pool.connect() as conn:
            try:
                result = conn.execute(
                    text("""
                        SELECT id, diagnosis_type, period_start, period_end,
                               overall_score, total_interactions,
                               successful_interactions, identified_weaknesses
                        FROM brain_self_diagnoses
                        WHERE organization_id = :org_id
                        ORDER BY period_end DESC
                        LIMIT :limit OFFSET :offset
                    """),
                    {"org_id": organization_id, "limit": limit, "offset": offset},
                )
                rows = result.fetchall()

                count_result = conn.execute(
                    text("SELECT COUNT(*) FROM brain_self_diagnoses WHERE organization_id = :org_id"),
                    {"org_id": organization_id},
                )
                total = int(count_result.fetchone()[0])
            except Exception:
                conn.rollback()

        from app.schemas.admin import SelfDiagnosisSummary, SelfDiagnosesResponse

        diagnoses = [
            SelfDiagnosisSummary(
                id=str(r[0]), diagnosis_type=r[1],
                period_start=str(r[2]) if r[2] else None,
                period_end=str(r[3]) if r[3] else None,
                overall_score=round(float(r[4]), 1),
                total_interactions=int(r[5]),
                successful_interactions=int(r[6]),
                identified_weaknesses=list(r[7]) if r[7] else None,
            )
            for r in rows
        ]

        log_audit_event(
            logger=logger, action="get_self_diagnoses",
            resource_type="system", resource_id="diagnoses",
            user_id=user.user_id, details={"count": len(diagnoses)},
        )
        return SelfDiagnosesResponse(diagnoses=diagnoses, total_count=total)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get self diagnoses error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )
