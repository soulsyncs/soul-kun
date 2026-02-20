"""
Admin Dashboard - Member Detail/Update Endpoints

メンバー詳細取得（全属性）、メンバー情報更新、所属部署更新。
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import text

from lib.db import get_db_pool
from lib.logging import log_audit_event

from .deps import (
    logger,
    require_admin,
    require_editor,
    UserContext,
)
from app.schemas.admin import (
    MemberDetailResponse,
    MemberDepartmentInfo,
    UpdateMemberRequest,
    UpdateMemberDepartmentsRequest,
    DepartmentMutationResponse,
    AdminErrorResponse,
)

router = APIRouter()


@router.get(
    "/members/{user_id}/detail",
    response_model=MemberDetailResponse,
    responses={
        403: {"model": AdminErrorResponse, "description": "権限不足"},
        404: {"model": AdminErrorResponse, "description": "メンバーが見つからない"},
        500: {"model": AdminErrorResponse, "description": "サーバーエラー"},
    },
    summary="メンバー詳細取得（全属性）",
    description="メンバーの全属性（所属部署リスト、ChatWorkアカウント等）を返す。",
)
async def get_member_full_detail(
    user_id: str = Path(
        ...,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        description="UUID形式のユーザーID",
    ),
    user: UserContext = Depends(require_admin),
):
    """メンバーの全詳細情報を取得"""

    organization_id = user.organization_id

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            # ユーザー基本情報
            user_result = conn.execute(
                text("""
                    SELECT
                        u.id, u.name, u.email,
                        u.chatwork_account_id, u.is_active,
                        u.created_at, u.updated_at,
                        u.employment_type, u.avatar_url
                    FROM users u
                    WHERE u.id = :user_id
                      AND u.organization_id = :org_id
                    LIMIT 1
                """),
                {"user_id": user_id, "org_id": organization_id},
            )
            user_row = user_result.fetchone()

            if not user_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "status": "failed",
                        "error_code": "MEMBER_NOT_FOUND",
                        "error_message": "指定されたメンバーが見つかりません",
                    },
                )

            # 所属部署リスト
            dept_result = conn.execute(
                text("""
                    SELECT
                        ud.department_id, d.name as dept_name,
                        r.name as role_name, r.level as role_level,
                        ud.is_primary, ud.started_at
                    FROM user_departments ud
                    JOIN departments d ON ud.department_id = d.id
                    LEFT JOIN roles r ON ud.role_id = r.id
                    WHERE ud.user_id = :user_id
                      AND ud.ended_at IS NULL
                      AND d.organization_id = :org_id
                    ORDER BY ud.is_primary DESC, d.name ASC
                """),
                {"user_id": user_id, "org_id": organization_id},
            )
            dept_rows = dept_result.fetchall()

        departments = [
            MemberDepartmentInfo(
                department_id=str(row[0]),
                department_name=row[1] or "",
                role=row[2],
                role_level=int(row[3]) if row[3] is not None else None,
                is_primary=bool(row[4]) if row[4] is not None else False,
            )
            for row in dept_rows
        ]

        # 主所属の開始日を入社日として取得
        hire_date = next(
            (row[5] for row in dept_rows if row[4]),  # is_primary = True
            dept_rows[0][5] if dept_rows else None,   # フォールバック: 最初の部署
        )

        # 最高ロールレベルを取得
        max_role_level = max(
            (d.role_level for d in departments if d.role_level is not None),
            default=None,
        )
        primary_role = next(
            (d.role for d in departments if d.is_primary and d.role),
            departments[0].role if departments else None,
        )

        log_audit_event(
            logger=logger,
            action="get_member_full_detail",
            resource_type="member",
            resource_id=user_id,
            user_id=user.user_id,
        )

        return MemberDetailResponse(
            status="success",
            user_id=str(user_row[0]),
            name=user_row[1],
            email=user_row[2],
            role=primary_role,
            role_level=max_role_level,
            departments=departments,
            chatwork_account_id=user_row[3],
            is_active=bool(user_row[4]) if user_row[4] is not None else True,
            avatar_url=user_row[8],
            employment_type=user_row[7],
            hire_date=hire_date,
            created_at=user_row[5],
            updated_at=user_row[6],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Get member full detail error",
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


@router.put(
    "/members/{user_id}",
    response_model=DepartmentMutationResponse,
    responses={
        403: {"model": AdminErrorResponse, "description": "権限不足（Level 6必要）"},
        404: {"model": AdminErrorResponse, "description": "メンバーが見つからない"},
        500: {"model": AdminErrorResponse, "description": "サーバーエラー"},
    },
    summary="メンバー情報更新（Level 6+）",
    description="メンバーの基本情報（名前、メール、ChatWorkアカウント）を更新する。",
)
async def update_member(
    request: UpdateMemberRequest,
    user_id: str = Path(
        ...,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        description="UUID形式のユーザーID",
    ),
    user: UserContext = Depends(require_editor),
):
    """メンバー情報を更新する"""

    organization_id = user.organization_id

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            # 存在確認
            exists_result = conn.execute(
                text("""
                    SELECT id FROM users
                    WHERE id = :user_id AND organization_id = :org_id
                    LIMIT 1
                """),
                {"user_id": user_id, "org_id": organization_id},
            )
            if not exists_result.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "status": "failed",
                        "error_code": "MEMBER_NOT_FOUND",
                        "error_message": "指定されたメンバーが見つかりません",
                    },
                )

            set_clauses = []
            params = {"user_id": user_id, "org_id": organization_id}

            if request.name is not None:
                set_clauses.append("name = :name")
                params["name"] = request.name
            if request.email is not None:
                set_clauses.append("email = :email")
                params["email"] = request.email
            if request.chatwork_account_id is not None:
                set_clauses.append("chatwork_account_id = :cw_id")
                params["cw_id"] = request.chatwork_account_id
            if request.employment_type is not None:
                set_clauses.append("employment_type = :employment_type")
                params["employment_type"] = request.employment_type or None
            if request.avatar_url is not None:
                set_clauses.append("avatar_url = :avatar_url")
                params["avatar_url"] = request.avatar_url or None

            if not set_clauses:
                return DepartmentMutationResponse(
                    status="success",
                    department_id=user_id,
                    message="更新項目がありません",
                )

            set_clauses.append("updated_at = NOW()")

            query = f"""
                UPDATE users
                SET {', '.join(set_clauses)}
                WHERE id = :user_id AND organization_id = :org_id
            """
            conn.execute(text(query), params)
            conn.commit()

        log_audit_event(
            logger=logger,
            action="update_member",
            resource_type="member",
            resource_id=user_id,
            user_id=user.user_id,
            details={"updated_fields": [c.split(" = ")[0] for c in set_clauses[:-1]]},
        )

        return DepartmentMutationResponse(
            status="success",
            department_id=user_id,
            message="メンバー情報を更新しました",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Update member error",
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


@router.put(
    "/members/{user_id}/departments",
    response_model=DepartmentMutationResponse,
    responses={
        403: {"model": AdminErrorResponse, "description": "権限不足（Level 6必要）"},
        404: {"model": AdminErrorResponse, "description": "メンバーが見つからない"},
        500: {"model": AdminErrorResponse, "description": "サーバーエラー"},
    },
    summary="メンバー所属部署更新（Level 6+）",
    description="メンバーの所属部署を一括更新する。既存の所属は終了日を設定して新しい所属に置き換える。",
)
async def update_member_departments(
    request: UpdateMemberDepartmentsRequest,
    user_id: str = Path(
        ...,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        description="UUID形式のユーザーID",
    ),
    user: UserContext = Depends(require_editor),
):
    """メンバーの所属部署を更新する"""

    organization_id = user.organization_id
    now = datetime.now(timezone.utc)

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            # ユーザー存在確認
            exists_result = conn.execute(
                text("""
                    SELECT id FROM users
                    WHERE id = :user_id AND organization_id = :org_id
                    LIMIT 1
                """),
                {"user_id": user_id, "org_id": organization_id},
            )
            if not exists_result.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "status": "failed",
                        "error_code": "MEMBER_NOT_FOUND",
                        "error_message": "指定されたメンバーが見つかりません",
                    },
                )

            # 指定された部署が全て存在するか確認（バッチ検証でN+1回避）
            dept_ids = [d.department_id for d in request.departments]
            valid_result = conn.execute(
                text("""
                    SELECT id::text FROM departments
                    WHERE id = ANY(:dept_ids::uuid[])
                      AND organization_id = :org_id
                      AND is_active = TRUE
                """),
                {"dept_ids": dept_ids, "org_id": organization_id},
            )
            valid_ids = {str(row[0]) for row in valid_result.fetchall()}
            missing = set(dept_ids) - valid_ids
            if missing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "status": "failed",
                        "error_code": "DEPARTMENT_NOT_FOUND",
                        "error_message": f"部署 {', '.join(missing)} が見つかりません",
                    },
                )

            # 既存の所属を終了（org_id防御）
            conn.execute(
                text("""
                    UPDATE user_departments ud
                    SET ended_at = :now, updated_at = :now
                    FROM departments d
                    WHERE ud.user_id = :user_id
                      AND ud.ended_at IS NULL
                      AND ud.department_id = d.id
                      AND d.organization_id = :org_id
                """),
                {"user_id": user_id, "now": now, "org_id": organization_id},
            )

            # 新しい所属を作成
            for assignment in request.departments:
                conn.execute(
                    text("""
                        INSERT INTO user_departments (
                            user_id, department_id, role_id,
                            is_primary, started_at, created_at
                        ) VALUES (
                            :user_id, :dept_id, :role_id,
                            :is_primary, :now, :now
                        )
                    """),
                    {
                        "user_id": user_id,
                        "dept_id": assignment.department_id,
                        "role_id": assignment.role_id,
                        "is_primary": assignment.is_primary,
                        "now": now,
                    },
                )

            conn.commit()

        log_audit_event(
            logger=logger,
            action="update_member_departments",
            resource_type="member",
            resource_id=user_id,
            user_id=user.user_id,
            details={
                "new_departments": [d.department_id for d in request.departments],
            },
        )

        return DepartmentMutationResponse(
            status="success",
            department_id=user_id,
            message=f"所属部署を{len(request.departments)}件に更新しました",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Update member departments error",
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
