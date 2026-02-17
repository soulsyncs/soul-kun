"""
Admin Dashboard - Proactive Actions Endpoints

プロアクティブアクション一覧、プロアクティブ統計。
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
    "/proactive/actions",
    summary="プロアクティブアクション一覧",
    description="プロアクティブアクションの一覧（Level 5+）",
)
async def get_proactive_actions(
    user: UserContext = Depends(require_admin),
    trigger_type: Optional[str] = Query(None, description="トリガータイプフィルタ"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            where_clauses = ["pa.organization_id = :org_id"]
            params: dict = {"org_id": organization_id, "limit": limit, "offset": offset}

            if trigger_type:
                where_clauses.append("pa.trigger_type = :trigger_type")
                params["trigger_type"] = trigger_type

            where_sql = " AND ".join(where_clauses)

            result = conn.execute(
                text(f"""
                    SELECT pa.id, pa.user_id, pa.trigger_type, pa.priority,
                           pa.message_type, pa.user_response_positive, pa.created_at
                    FROM proactive_action_logs pa
                    WHERE {where_sql}
                    ORDER BY pa.created_at DESC
                    LIMIT :limit OFFSET :offset
                """),
                params,
            )
            rows = result.fetchall()

            count_result = conn.execute(
                text(f"SELECT COUNT(*) FROM proactive_action_logs pa WHERE {where_sql}"),
                params,
            )
            total = int(count_result.fetchone()[0])

        from app.schemas.admin import ProactiveActionSummary, ProactiveActionsResponse

        actions = [
            ProactiveActionSummary(
                id=str(r[0]), user_id=str(r[1]),
                trigger_type=r[2], priority=r[3],
                message_type=r[4],
                user_response_positive=r[5],
                created_at=str(r[6]) if r[6] else None,
            )
            for r in rows
        ]

        log_audit_event(
            logger=logger, action="get_proactive_actions",
            resource_type="proactive_actions", resource_id="list",
            user_id=user.user_id, details={"count": len(actions)},
        )
        return ProactiveActionsResponse(actions=actions, total_count=total)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get proactive actions error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )


@router.get(
    "/proactive/stats",
    summary="プロアクティブ統計",
    description="プロアクティブアクションの統計（Level 5+）",
)
async def get_proactive_stats(
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
                        COUNT(*) FILTER (WHERE user_response_positive = TRUE) AS positive,
                        COUNT(*) FILTER (WHERE user_response_positive IS NOT NULL) AS responded
                    FROM proactive_action_logs
                    WHERE organization_id = :org_id
                """),
                {"org_id": organization_id},
            )
            stats = result.fetchone()
            total = int(stats[0])
            positive = int(stats[1])
            responded = int(stats[2])

            by_type_result = conn.execute(
                text("""
                    SELECT trigger_type,
                           COUNT(*) AS total,
                           COUNT(*) FILTER (WHERE user_response_positive = TRUE) AS positive
                    FROM proactive_action_logs
                    WHERE organization_id = :org_id
                    GROUP BY trigger_type
                    ORDER BY total DESC
                """),
                {"org_id": organization_id},
            )
            by_type = [
                {"trigger_type": r[0], "total": int(r[1]), "positive": int(r[2])}
                for r in by_type_result.fetchall()
            ]

        from app.schemas.admin import ProactiveStatsResponse

        log_audit_event(
            logger=logger, action="get_proactive_stats",
            resource_type="proactive_actions", resource_id="stats",
            user_id=user.user_id, details={},
        )
        return ProactiveStatsResponse(
            total_actions=total,
            positive_responses=positive,
            response_rate=round(positive / responded * 100, 1) if responded > 0 else 0.0,
            by_trigger_type=by_type,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get proactive stats error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )
