"""
Admin Dashboard - Members List/Detail Endpoints

メンバー一覧取得、メンバー詳細取得、キーマン発見。
"""

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import text

from lib.db import get_db_pool
from lib.logging import log_audit_event

from .deps import (
    _escape_like,
    logger,
    require_admin,
    UserContext,
)
from app.schemas.admin import (
    MembersListResponse,
    MemberResponse,
    AdminErrorResponse,
)

router = APIRouter()


@router.get(
    "/members",
    response_model=MembersListResponse,
    responses={
        403: {"model": AdminErrorResponse, "description": "権限不足"},
        500: {"model": AdminErrorResponse, "description": "サーバーエラー"},
    },
    summary="メンバー一覧取得",
    description="""
組織内のメンバー一覧を返す（検索・フィルタ・ページネーション対応）。

## パラメータ
- search: 名前またはメールで部分一致検索
- dept_id: 部署IDでフィルタ
- limit: 取得件数（デフォルト50、最大200）
- offset: オフセット
    """,
)
async def get_members(
    search: Optional[str] = Query(
        None,
        max_length=100,
        description="名前/メール部分一致検索",
    ),
    dept_id: Optional[str] = Query(
        None,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        description="部署IDでフィルタ（UUID形式）",
    ),
    limit: int = Query(
        50,
        ge=1,
        le=200,
        description="取得件数（最大200）",
    ),
    offset: int = Query(
        0,
        ge=0,
        description="オフセット",
    ),
    user: UserContext = Depends(require_admin),
):
    """メンバー一覧を取得"""

    organization_id = user.organization_id

    logger.info(
        "Get members",
        organization_id=organization_id,
        has_search=bool(search),
        dept_id=dept_id,
        limit=limit,
        offset=offset,
        user_id=user.user_id,
    )

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            # ベースクエリ（DISTINCT ON で各ユーザー1行に制限、主所属を優先）
            query = """
                SELECT DISTINCT ON (u.id)
                    u.id as user_id,
                    u.name,
                    u.email,
                    r.name as role_name,
                    r.level as role_level,
                    d.name as department_name,
                    ud.department_id,
                    u.created_at
                FROM users u
                LEFT JOIN user_departments ud
                    ON u.id = ud.user_id AND ud.ended_at IS NULL
                LEFT JOIN roles r
                    ON ud.role_id = r.id
                LEFT JOIN departments d
                    ON ud.department_id = d.id
                WHERE u.organization_id = :org_id
            """
            params = {"org_id": organization_id}

            # 検索フィルタ
            if search:
                query += """
                    AND (
                        u.name ILIKE :search_pattern
                        OR u.email ILIKE :search_pattern
                    )
                """
                params["search_pattern"] = f"%{_escape_like(search)}%"

            # 部署フィルタ
            if dept_id:
                query += " AND ud.department_id = :dept_id"
                params["dept_id"] = dept_id

            # DISTINCT ON (u.id) + ソート（主所属を優先）
            # サブクエリでDISTINCT ON処理し、外側でcreated_at DESCソート + ページネーション
            query = f"""
                SELECT * FROM (
                    {query}
                    ORDER BY u.id, ud.is_primary DESC NULLS LAST, ud.created_at ASC
                ) sub
                ORDER BY sub.created_at DESC
                LIMIT :limit OFFSET :offset
            """
            params["limit"] = limit
            params["offset"] = offset

            result = conn.execute(text(query), params)
            rows = result.fetchall()

            # 総件数カウント
            count_query = """
                SELECT COUNT(DISTINCT u.id) as total
                FROM users u
                LEFT JOIN user_departments ud
                    ON u.id = ud.user_id AND ud.ended_at IS NULL
                WHERE u.organization_id = :org_id
            """
            count_params = {"org_id": organization_id}

            if search:
                count_query += """
                    AND (
                        u.name ILIKE :search_pattern
                        OR u.email ILIKE :search_pattern
                    )
                """
                count_params["search_pattern"] = f"%{_escape_like(search)}%"

            if dept_id:
                count_query += " AND ud.department_id = :dept_id"
                count_params["dept_id"] = dept_id

            count_result = conn.execute(text(count_query), count_params)
            total_count = int(count_result.fetchone()[0])

        members = []
        for row in rows:
            members.append(
                MemberResponse(
                    user_id=str(row[0]),
                    name=row[1],
                    email=row[2],
                    role=row[3],
                    role_level=int(row[4]) if row[4] is not None else None,
                    department=row[5],
                    department_id=str(row[6]) if row[6] else None,
                    created_at=row[7],
                )
            )

        log_audit_event(
            logger=logger,
            action="get_members",
            resource_type="member",
            resource_id=organization_id,
            user_id=user.user_id,
            details={
                "has_search": bool(search),
                "dept_id": dept_id,
                "returned_count": len(members),
                "total_count": total_count,
            },
        )

        return MembersListResponse(
            status="success",
            members=members,
            total_count=total_count,
            offset=offset,
            limit=limit,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Get members error",
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


@router.get(
    "/members/{user_id}",
    response_model=MemberResponse,
    responses={
        403: {"model": AdminErrorResponse, "description": "権限不足"},
        404: {"model": AdminErrorResponse, "description": "メンバーが見つからない"},
        500: {"model": AdminErrorResponse, "description": "サーバーエラー"},
    },
    summary="メンバー詳細取得",
    description="指定したユーザーIDのメンバー詳細情報を返す。",
)
async def get_member_detail(
    user_id: str = Path(
        ...,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        description="UUID形式のユーザーID",
    ),
    user: UserContext = Depends(require_admin),
):
    """メンバー詳細を取得"""

    organization_id = user.organization_id

    logger.info(
        "Get member detail",
        organization_id=organization_id,
        target_user_id=user_id,
        user_id=user.user_id,
    )

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT
                        u.id as user_id,
                        u.name,
                        u.email,
                        r.name as role_name,
                        r.level as role_level,
                        d.name as department_name,
                        ud.department_id,
                        u.created_at
                    FROM users u
                    LEFT JOIN user_departments ud
                        ON u.id = ud.user_id AND ud.ended_at IS NULL
                    LEFT JOIN roles r
                        ON ud.role_id = r.id
                    LEFT JOIN departments d
                        ON ud.department_id = d.id
                    WHERE u.id = :target_user_id
                      AND u.organization_id = :org_id
                    LIMIT 1
                """),
                {"target_user_id": user_id, "org_id": organization_id},
            )
            row = result.fetchone()

        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failed",
                    "error_code": "MEMBER_NOT_FOUND",
                    "error_message": "指定されたメンバーが見つかりません",
                },
            )

        log_audit_event(
            logger=logger,
            action="get_member_detail",
            resource_type="member",
            resource_id=user_id,
            user_id=user.user_id,
            details={},
        )

        return MemberResponse(
            user_id=str(row[0]),
            name=row[1],
            email=row[2],
            role=row[3],
            role_level=int(row[4]) if row[4] is not None else None,
            department=row[5],
            department_id=str(row[6]) if row[6] else None,
            created_at=row[7],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Get member detail error",
            organization_id=organization_id,
            target_user_id=user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failed",
                "error_code": "INTERNAL_ERROR",
                "error_message": "内部エラーが発生しました",
            },
        )


@router.get(
    "/members/keymen",
    summary="隠れたキーマン発見",
    description="AI利用ログから組織の鍵となる人物をスコアリング（Level 5+）",
)
async def get_keymen(
    period_days: int = Query(90, ge=7, le=365, description="集計期間（デフォルト90日）"),
    user: UserContext = Depends(require_admin),
):
    organization_id = user.organization_id
    since = date.today() - timedelta(days=period_days)

    logger.info("Get keymen", organization_id=organization_id, period_days=period_days)

    try:
        pool = get_db_pool()
        with pool.connect() as conn:
            # ユーザー別のAI活用統計
            usage_result = conn.execute(
                text("""
                    SELECT
                        al.user_id,
                        COUNT(*) AS total_requests,
                        COUNT(DISTINCT DATE(al.created_at)) AS active_days,
                        COUNT(DISTINCT al.tier) AS tiers_used
                    FROM ai_usage_logs al
                    WHERE al.organization_id = :org_id
                      AND al.user_id IS NOT NULL
                      AND al.created_at >= :since
                    GROUP BY al.user_id
                    ORDER BY total_requests DESC
                    LIMIT 50
                """),
                {"org_id": organization_id, "since": since},
            )
            usage_rows = usage_result.fetchall()

            if not usage_rows:
                from app.schemas.admin import KeymenResponse
                return KeymenResponse(status="success", period_days=period_days, top_keymen=[])

            # ユーザー情報を取得
            user_ids = [str(r[0]) for r in usage_rows]
            placeholders = ", ".join(f":uid_{i}" for i in range(len(user_ids)))
            uid_params = {f"uid_{i}": uid for i, uid in enumerate(user_ids)}
            uid_params["org_id"] = organization_id

            user_result = conn.execute(
                text(f"""
                    SELECT DISTINCT ON (u.id)
                        u.id, u.name, d.name AS dept_name
                    FROM users u
                    LEFT JOIN user_departments ud
                        ON u.id = ud.user_id AND ud.ended_at IS NULL AND ud.is_primary = TRUE
                    LEFT JOIN departments d ON ud.department_id = d.id
                    WHERE u.organization_id = :org_id
                      AND u.id::text IN ({placeholders})
                    ORDER BY u.id
                """),
                uid_params,
            )
            user_map = {str(r[0]): (r[1], r[2]) for r in user_result.fetchall()}

            # 直近30日 vs 前30日でトレンド計算
            mid = date.today() - timedelta(days=30)
            trend_result = conn.execute(
                text("""
                    SELECT user_id,
                           COUNT(*) FILTER (WHERE created_at >= :mid) AS recent,
                           COUNT(*) FILTER (WHERE created_at < :mid) AS older
                    FROM ai_usage_logs
                    WHERE organization_id = :org_id
                      AND user_id IS NOT NULL
                      AND created_at >= :since
                    GROUP BY user_id
                """),
                {"org_id": organization_id, "since": since, "mid": mid},
            )
            trend_map = {str(r[0]): (int(r[1]), int(r[2])) for r in trend_result.fetchall()}

        # スコア正規化
        max_requests = max(int(r[1]) for r in usage_rows)
        max_days = max(int(r[2]) for r in usage_rows)
        max_tiers = max(int(r[3]) for r in usage_rows)

        def _trend(uid: str) -> str:
            rec, old = trend_map.get(uid, (0, 0))
            if old == 0:
                return "rising" if rec > 0 else "stable"
            ratio = rec / old
            if ratio >= 1.3:
                return "rising"
            if ratio <= 0.7:
                return "declining"
            return "stable"

        from app.schemas.admin import KeyPersonScore, KeymenResponse

        top_keymen = []
        for rank, row in enumerate(usage_rows[:10], start=1):
            uid = str(row[0])
            req = int(row[1])
            days_used = int(row[2])
            tiers = int(row[3])
            norm_req = req / max_requests if max_requests > 0 else 0
            norm_days = days_used / max_days if max_days > 0 else 0
            norm_tiers = tiers / max_tiers if max_tiers > 0 else 0
            score = round((norm_req * 0.4 + norm_days * 0.4 + norm_tiers * 0.2) * 100, 1)

            name, dept = user_map.get(uid, (None, None))
            top_keymen.append(
                KeyPersonScore(
                    user_id=uid, name=name, department_name=dept,
                    total_requests=req, active_days=days_used,
                    tiers_used=tiers, score=score, rank=rank,
                    recent_trend=_trend(uid),
                )
            )

        log_audit_event(
            logger=logger, action="get_keymen",
            resource_type="members", resource_id="keymen",
            user_id=user.user_id,
            details={"period_days": period_days, "count": len(top_keymen)},
        )
        return KeymenResponse(
            status="success",
            period_days=period_days,
            top_keymen=top_keymen,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get keymen error", organization_id=organization_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failed", "error_code": "INTERNAL_ERROR", "error_message": "内部エラーが発生しました"},
        )
