"""
Admin Dashboard - Meetings Endpoints

ミーティング一覧、ミーティング詳細。
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
    "/meetings",
    summary="ミーティング一覧",
    description="ミーティングの一覧（Level 5+）",
)
async def get_meetings_list(
    user: UserContext = Depends(require_admin),
    meeting_status: Optional[str] = Query(None, alias="status", description="ステータスフィルタ"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            where_clauses = ["m.organization_id = :org_id"]
            params: dict = {"org_id": organization_id, "limit": limit, "offset": offset}

            if meeting_status:
                where_clauses.append("m.status = :meeting_status")
                params["meeting_status"] = meeting_status

            where_sql = " AND ".join(where_clauses)

            result = conn.execute(
                text(f"""
                    SELECT m.id, m.title, m.meeting_type, m.meeting_date,
                           m.duration_seconds, m.status, m.source,
                           EXISTS(SELECT 1 FROM meeting_transcripts mt
                                  WHERE mt.meeting_id = m.id
                                    AND mt.organization_id = :org_id
                                    AND mt.deleted_at IS NULL) AS has_transcript,
                           EXISTS(SELECT 1 FROM meeting_recordings mr
                                  WHERE mr.meeting_id = m.id
                                    AND mr.organization_id = :org_id
                                    AND mr.deleted_at IS NULL) AS has_recording
                    FROM meetings m
                    WHERE {where_sql}
                    ORDER BY m.meeting_date DESC NULLS LAST
                    LIMIT :limit OFFSET :offset
                """),
                params,
            )
            rows = result.fetchall()

            count_result = conn.execute(
                text(f"SELECT COUNT(*) FROM meetings m WHERE {where_sql}"),
                params,
            )
            total = int(count_result.fetchone()[0])

        from app.schemas.admin import MeetingSummary, MeetingsListResponse

        meetings = [
            MeetingSummary(
                id=str(r[0]), title=r[1], meeting_type=r[2],
                meeting_date=str(r[3]) if r[3] else None,
                duration_seconds=float(r[4]) if r[4] else None,
                status=r[5], source=r[6],
                has_transcript=bool(r[7]), has_recording=bool(r[8]),
            )
            for r in rows
        ]

        log_audit_event(
            logger=logger, action="get_meetings_list",
            resource_type="meetings", resource_id="list",
            user_id=user.user_id, details={"count": len(meetings)},
        )
        return MeetingsListResponse(meetings=meetings, total_count=total)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get meetings list error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )


@router.get(
    "/meetings/{meeting_id}",
    summary="ミーティング詳細",
    description="ミーティングの詳細（議事録・録音含む）（Level 5+）",
)
async def get_meeting_detail(
    meeting_id: str = Path(..., pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", description="ミーティングID (UUID)"),
    user: UserContext = Depends(require_admin),
):
    organization_id = user.organization_id or DEFAULT_ORG_ID
    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            # ミーティング基本情報
            m_result = conn.execute(
                text("""
                    SELECT m.id, m.title, m.meeting_type, m.meeting_date,
                           m.duration_seconds, m.status, m.source
                    FROM meetings m
                    WHERE m.id = :meeting_id AND m.organization_id = :org_id
                """),
                {"meeting_id": meeting_id, "org_id": organization_id},
            )
            m_row = m_result.fetchone()
            if not m_row:
                raise HTTPException(status_code=404, detail={"status": "failed", "error_message": "ミーティングが見つかりません"})

            # 議事録
            transcript_text = None
            try:
                t_result = conn.execute(
                    text("""
                        SELECT COALESCE(mt.sanitized_transcript, mt.raw_transcript) as transcript_text
                        FROM meeting_transcripts mt
                        WHERE mt.meeting_id = :meeting_id
                          AND mt.organization_id = :org_id
                          AND mt.deleted_at IS NULL
                        ORDER BY mt.created_at DESC LIMIT 1
                    """),
                    {"meeting_id": meeting_id, "org_id": organization_id},
                )
                t_row = t_result.fetchone()
                if t_row:
                    transcript_text = t_row[0]
            except Exception as e:
                logger.warning("Failed to fetch transcript", meeting_id=meeting_id, error=str(e))

            log_audit_event(
                logger=logger, action="get_meeting_detail",
                resource_type="meetings", resource_id=meeting_id,
                user_id=user.user_id, details={},
            )
            return {
                "status": "success",
                "meeting": {
                    "id": str(m_row[0]),
                    "title": m_row[1],
                    "meeting_type": m_row[2],
                    "meeting_date": str(m_row[3]) if m_row[3] else None,
                    "duration_seconds": float(m_row[4]) if m_row[4] else None,
                    "status": m_row[5],
                    "source": m_row[6],
                },
                "transcript": transcript_text,
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get meeting detail error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )
