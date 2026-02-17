"""
Admin Dashboard - Members List/Detail Endpoints

メンバー一覧取得、メンバー詳細取得。
"""

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
