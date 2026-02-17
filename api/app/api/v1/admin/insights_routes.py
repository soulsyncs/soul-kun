"""
Admin Dashboard - Insights Endpoints

インサイト一覧取得、質問パターン一覧、週次レポート一覧。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text

from lib.db import get_db_pool
from lib.logging import log_audit_event
from lib.text_utils import clean_chatwork_tags

from .deps import (
    DEFAULT_ORG_ID,
    logger,
    require_admin,
    UserContext,
)

router = APIRouter()


@router.get(
    "/insights",
    summary="インサイト一覧取得",
    description="AI生成インサイトの一覧（Level 5+）",
)
async def get_insights_list(
    user: UserContext = Depends(require_admin),
    importance: Optional[str] = Query(None, description="重要度フィルタ"),
    insight_status: Optional[str] = Query(None, alias="status", description="ステータスフィルタ"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            where_clauses = ["si.organization_id = :org_id"]
            params: dict = {"org_id": organization_id, "limit": limit, "offset": offset}

            if importance:
                where_clauses.append("si.importance = :importance")
                params["importance"] = importance
            if insight_status:
                where_clauses.append("si.status = :insight_status")
                params["insight_status"] = insight_status

            where_sql = " AND ".join(where_clauses)

            result = conn.execute(
                text(f"""
                    SELECT si.id, si.insight_type, si.source_type, si.importance,
                           si.title, si.description, si.recommended_action,
                           si.status, d.name AS department_name, si.created_at
                    FROM soulkun_insights si
                    LEFT JOIN departments d ON si.department_id = d.id
                    WHERE {where_sql}
                    ORDER BY si.created_at DESC
                    LIMIT :limit OFFSET :offset
                """),
                params,
            )
            rows = result.fetchall()

            count_result = conn.execute(
                text(f"SELECT COUNT(*) FROM soulkun_insights si WHERE {where_sql}"),
                params,
            )
            total = int(count_result.fetchone()[0])

        from app.schemas.admin import InsightSummary, InsightsListResponse

        insights = [
            InsightSummary(
                id=str(r[0]), insight_type=r[1], source_type=r[2],
                importance=r[3],
                title=clean_chatwork_tags(r[4]) if r[4] else "",
                description=clean_chatwork_tags(r[5]) if r[5] else "",
                recommended_action=clean_chatwork_tags(r[6]) if r[6] else None,
                status=r[7],
                department_name=r[8],
                created_at=str(r[9]) if r[9] else None,
            )
            for r in rows
        ]

        log_audit_event(
            logger=logger, action="get_insights_list",
            resource_type="insights", resource_id="list",
            user_id=user.user_id, details={"count": len(insights)},
        )
        return InsightsListResponse(insights=insights, total_count=total)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get insights list error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )


@router.get(
    "/insights/patterns",
    summary="質問パターン一覧",
    description="よくある質問パターンの一覧（Level 5+）",
)
async def get_question_patterns(
    user: UserContext = Depends(require_admin),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT id, question_category, normalized_question,
                           occurrence_count, last_asked_at, status
                    FROM question_patterns
                    WHERE organization_id = :org_id
                    ORDER BY occurrence_count DESC
                    LIMIT :limit OFFSET :offset
                """),
                {"org_id": organization_id, "limit": limit, "offset": offset},
            )
            rows = result.fetchall()

            count_result = conn.execute(
                text("SELECT COUNT(*) FROM question_patterns WHERE organization_id = :org_id"),
                {"org_id": organization_id},
            )
            total = int(count_result.fetchone()[0])

        from app.schemas.admin import QuestionPatternSummary, QuestionPatternsResponse

        patterns = [
            QuestionPatternSummary(
                id=str(r[0]), question_category=r[1],
                normalized_question=r[2], occurrence_count=int(r[3]),
                last_asked_at=str(r[4]) if r[4] else None, status=r[5],
            )
            for r in rows
        ]

        log_audit_event(
            logger=logger, action="get_question_patterns",
            resource_type="question_patterns", resource_id="list",
            user_id=user.user_id, details={"count": len(patterns)},
        )
        return QuestionPatternsResponse(patterns=patterns, total_count=total)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get question patterns error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )


@router.get(
    "/insights/weekly-reports",
    summary="週次レポート一覧",
    description="週次レポートの一覧（Level 5+）",
)
async def get_weekly_reports(
    user: UserContext = Depends(require_admin),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT id, week_start, week_end, status, sent_at, sent_via
                    FROM soulkun_weekly_reports
                    WHERE organization_id = :org_id
                    ORDER BY week_start DESC
                    LIMIT :limit OFFSET :offset
                """),
                {"org_id": organization_id, "limit": limit, "offset": offset},
            )
            rows = result.fetchall()

            count_result = conn.execute(
                text("SELECT COUNT(*) FROM soulkun_weekly_reports WHERE organization_id = :org_id"),
                {"org_id": organization_id},
            )
            total = int(count_result.fetchone()[0])

        from app.schemas.admin import WeeklyReportSummary, WeeklyReportsResponse

        reports = [
            WeeklyReportSummary(
                id=str(r[0]), week_start=str(r[1]), week_end=str(r[2]),
                status=r[3], sent_at=str(r[4]) if r[4] else None, sent_via=r[5],
            )
            for r in rows
        ]

        log_audit_event(
            logger=logger, action="get_weekly_reports",
            resource_type="weekly_reports", resource_id="list",
            user_id=user.user_id, details={"count": len(reports)},
        )
        return WeeklyReportsResponse(reports=reports, total_count=total)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get weekly reports error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )
