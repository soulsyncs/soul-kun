"""
Admin Dashboard - Department CRUD Endpoints

部署ツリー取得、部署詳細、部署作成/更新/削除。
"""

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
    DepartmentTreeNode,
    DepartmentsTreeResponse,
    DepartmentResponse,
    DepartmentDetailResponse,
    DepartmentMember,
    CreateDepartmentRequest,
    UpdateDepartmentRequest,
    DepartmentMutationResponse,
    AdminErrorResponse,
)

router = APIRouter()


def _build_department_tree(
    departments: list, member_counts: dict
) -> list[DepartmentTreeNode]:
    """フラットな部署リストからツリー構造を構築する。"""
    nodes = {}
    for dept in departments:
        dept_id = str(dept[0])
        nodes[dept_id] = DepartmentTreeNode(
            id=dept_id,
            name=dept[1] or "",
            parent_department_id=str(dept[2]) if dept[2] else None,
            level=int(dept[3]) if dept[3] is not None else 0,
            display_order=int(dept[4]) if dept[4] is not None else 0,
            description=dept[5],
            is_active=bool(dept[6]) if dept[6] is not None else True,
            member_count=member_counts.get(dept_id, 0),
            children=[],
        )

    roots = []
    for dept_id, node in nodes.items():
        parent_id = node.parent_department_id
        if parent_id and parent_id in nodes:
            nodes[parent_id].children.append(node)
        elif not parent_id:
            # True root (no parent) → show at top level
            # Skip empty shell roots (0 members, 0 children) to avoid showing duplicate stale records
            roots.append(node)
        # else: orphaned (parent_id set but not found in this org) → skip to avoid duplicate display

    # Remove empty shell roots: roots with no members and no children are stale duplicates
    # (legitimate new departments will have either children or members soon after creation)
    roots = [r for r in roots if r.member_count > 0 or len(r.children) > 0]

    # Sort children by display_order at each level
    def sort_children(node: DepartmentTreeNode):
        node.children.sort(key=lambda n: n.display_order)
        for child in node.children:
            sort_children(child)

    roots.sort(key=lambda n: n.display_order)
    for root in roots:
        sort_children(root)

    return roots


@router.get(
    "/departments",
    response_model=DepartmentsTreeResponse,
    responses={
        403: {"model": AdminErrorResponse, "description": "権限不足"},
        500: {"model": AdminErrorResponse, "description": "サーバーエラー"},
    },
    summary="部署ツリー取得",
    description="組織の全部署をツリー構造で返す。各部署に所属メンバー数を含む。",
)
async def get_departments_tree(
    user: UserContext = Depends(require_admin),
):
    """部署ツリーを取得"""

    organization_id = user.organization_id

    logger.info(
        "Get departments tree",
        organization_id=organization_id,
        user_id=user.user_id,
    )

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            # 全部署取得
            dept_result = conn.execute(
                text("""
                    SELECT
                        d.id, d.name, d.parent_id,
                        d.level, d.display_order, d.description,
                        d.is_active
                    FROM departments d
                    WHERE d.organization_id = :org_id
                    ORDER BY d.display_order ASC, d.name ASC
                """),
                {"org_id": organization_id},
            )
            departments = dept_result.fetchall()

            # 部署ごとのメンバー数
            count_result = conn.execute(
                text("""
                    SELECT
                        ud.department_id::text,
                        COUNT(DISTINCT ud.user_id) as cnt
                    FROM user_departments ud
                    JOIN departments d ON ud.department_id = d.id
                    WHERE d.organization_id = :org_id
                      AND ud.ended_at IS NULL
                    GROUP BY ud.department_id
                """),
                {"org_id": organization_id},
            )
            member_counts = {
                str(row[0]): int(row[1]) for row in count_result.fetchall()
            }

        tree = _build_department_tree(departments, member_counts)

        log_audit_event(
            logger=logger,
            action="get_departments_tree",
            resource_type="department",
            resource_id=organization_id,
            user_id=user.user_id,
            details={"total_departments": len(departments)},
        )

        return DepartmentsTreeResponse(
            status="success",
            departments=tree,
            total_count=len(departments),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Get departments tree error",
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
    "/departments/{dept_id}",
    response_model=DepartmentDetailResponse,
    responses={
        403: {"model": AdminErrorResponse, "description": "権限不足"},
        404: {"model": AdminErrorResponse, "description": "部署が見つからない"},
        500: {"model": AdminErrorResponse, "description": "サーバーエラー"},
    },
    summary="部署詳細取得",
    description="指定した部署の詳細情報と所属メンバーリストを返す。",
)
async def get_department_detail(
    dept_id: str = Path(
        ...,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        description="部署ID（UUID）",
    ),
    user: UserContext = Depends(require_admin),
):
    """部署詳細を取得"""

    organization_id = user.organization_id

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            # 部署情報
            dept_result = conn.execute(
                text("""
                    SELECT
                        d.id, d.name, d.parent_id,
                        d.level, d.display_order, d.description,
                        d.is_active, d.created_at, d.updated_at
                    FROM departments d
                    WHERE d.id = :dept_id
                      AND d.organization_id = :org_id
                    LIMIT 1
                """),
                {"dept_id": dept_id, "org_id": organization_id},
            )
            dept_row = dept_result.fetchone()

            if not dept_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "status": "failed",
                        "error_code": "DEPARTMENT_NOT_FOUND",
                        "error_message": "指定された部署が見つかりません",
                    },
                )

            # 所属メンバー取得
            members_result = conn.execute(
                text("""
                    SELECT
                        u.id, u.name,
                        r.name as role_name, r.level as role_level,
                        ud.is_primary
                    FROM user_departments ud
                    JOIN users u ON ud.user_id = u.id
                    LEFT JOIN roles r ON ud.role_id = r.id
                    WHERE ud.department_id = :dept_id
                      AND ud.ended_at IS NULL
                      AND u.organization_id = :org_id
                    ORDER BY r.level DESC NULLS LAST, u.name ASC
                """),
                {"dept_id": dept_id, "org_id": organization_id},
            )
            member_rows = members_result.fetchall()

        department = DepartmentResponse(
            id=str(dept_row[0]),
            name=dept_row[1] or "",
            parent_department_id=str(dept_row[2]) if dept_row[2] else None,
            level=int(dept_row[3]) if dept_row[3] is not None else 0,
            display_order=int(dept_row[4]) if dept_row[4] is not None else 0,
            description=dept_row[5],
            is_active=bool(dept_row[6]) if dept_row[6] is not None else True,
            member_count=len(member_rows),
            created_at=dept_row[7],
            updated_at=dept_row[8],
        )

        members = [
            DepartmentMember(
                user_id=str(row[0]),
                name=row[1],
                role=row[2],
                role_level=int(row[3]) if row[3] is not None else None,
                is_primary=bool(row[4]) if row[4] is not None else False,
            )
            for row in member_rows
        ]

        log_audit_event(
            logger=logger,
            action="get_department_detail",
            resource_type="department",
            resource_id=dept_id,
            user_id=user.user_id,
        )

        return DepartmentDetailResponse(
            status="success",
            department=department,
            members=members,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Get department detail error",
            organization_id=organization_id,
            dept_id=dept_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failed",
                "error_code": "INTERNAL_ERROR",
                "error_message": "内部エラーが発生しました",
            },
        )


@router.post(
    "/departments",
    response_model=DepartmentMutationResponse,
    status_code=201,
    responses={
        403: {"model": AdminErrorResponse, "description": "権限不足（Level 6必要）"},
        500: {"model": AdminErrorResponse, "description": "サーバーエラー"},
    },
    summary="部署作成（Level 6+）",
    description="新しい部署を作成する。編集権限（Level 6以上）が必要。",
)
async def create_department(
    request: CreateDepartmentRequest,
    user: UserContext = Depends(require_editor),
):
    """部署を作成する"""

    organization_id = user.organization_id

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            # 親部署の存在確認（指定時）
            parent_level = 0
            if request.parent_department_id:
                parent_result = conn.execute(
                    text("""
                        SELECT id, level, path
                        FROM departments
                        WHERE id = :parent_id
                          AND organization_id = :org_id
                        LIMIT 1
                    """),
                    {
                        "parent_id": request.parent_department_id,
                        "org_id": organization_id,
                    },
                )
                parent_row = parent_result.fetchone()
                if not parent_row:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={
                            "status": "failed",
                            "error_code": "PARENT_NOT_FOUND",
                            "error_message": "指定された親部署が見つかりません",
                        },
                    )
                parent_level = int(parent_row[1]) if parent_row[1] is not None else 0

            new_level = parent_level + 1

            # 部署作成
            result = conn.execute(
                text("""
                    INSERT INTO departments (
                        organization_id, name, parent_id,
                        level, display_order, description,
                        is_active, created_by
                    ) VALUES (
                        :org_id, :name, :parent_id,
                        :level, :display_order, :description,
                        TRUE, :created_by
                    )
                    RETURNING id
                """),
                {
                    "org_id": organization_id,
                    "name": request.name,
                    "parent_id": request.parent_department_id,
                    "level": new_level,
                    "display_order": request.display_order,
                    "description": request.description,
                    "created_by": user.user_id,
                },
            )
            new_id = str(result.fetchone()[0])
            conn.commit()

        log_audit_event(
            logger=logger,
            action="create_department",
            resource_type="department",
            resource_id=new_id,
            user_id=user.user_id,
            details={
                "name": request.name,
                "parent_id": request.parent_department_id,
            },
        )

        return DepartmentMutationResponse(
            status="success",
            department_id=new_id,
            message=f"部署「{request.name}」を作成しました",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Create department error",
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


@router.put(
    "/departments/{dept_id}",
    response_model=DepartmentMutationResponse,
    responses={
        403: {"model": AdminErrorResponse, "description": "権限不足（Level 6必要）"},
        404: {"model": AdminErrorResponse, "description": "部署が見つからない"},
        500: {"model": AdminErrorResponse, "description": "サーバーエラー"},
    },
    summary="部署更新（Level 6+）",
    description="部署情報を更新する。編集権限（Level 6以上）が必要。",
)
async def update_department(
    request: UpdateDepartmentRequest,
    dept_id: str = Path(
        ...,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        description="部署ID（UUID）",
    ),
    user: UserContext = Depends(require_editor),
):
    """部署情報を更新する"""

    organization_id = user.organization_id

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            # 対象部署の存在確認
            exists_result = conn.execute(
                text("""
                    SELECT id FROM departments
                    WHERE id = :dept_id AND organization_id = :org_id
                    LIMIT 1
                """),
                {"dept_id": dept_id, "org_id": organization_id},
            )
            if not exists_result.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "status": "failed",
                        "error_code": "DEPARTMENT_NOT_FOUND",
                        "error_message": "指定された部署が見つかりません",
                    },
                )

            # 動的にSETクエリを組み立て
            set_clauses = []
            params = {"dept_id": dept_id, "org_id": organization_id}

            if request.name is not None:
                set_clauses.append("name = :name")
                params["name"] = request.name
            if request.parent_department_id is not None:
                # 循環参照チェック: 自分自身を親に設定できない
                if request.parent_department_id == dept_id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={
                            "status": "failed",
                            "error_code": "CIRCULAR_REFERENCE",
                            "error_message": "部署を自身の子にすることはできません",
                        },
                    )
                # 循環参照チェック: 子孫を親に設定できない
                ancestor_check = conn.execute(
                    text("""
                        WITH RECURSIVE ancestors AS (
                            SELECT id, parent_id FROM departments
                            WHERE id = :proposed_parent AND organization_id = :org_id
                            UNION ALL
                            SELECT d.id, d.parent_id FROM departments d
                            JOIN ancestors a ON d.id = a.parent_id
                        )
                        SELECT 1 FROM ancestors WHERE id = :dept_id LIMIT 1
                    """),
                    {
                        "proposed_parent": request.parent_department_id,
                        "org_id": organization_id,
                        "dept_id": dept_id,
                    },
                )
                if ancestor_check.fetchone():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={
                            "status": "failed",
                            "error_code": "CIRCULAR_REFERENCE",
                            "error_message": "子孫の部署を親に設定することはできません（循環参照）",
                        },
                    )
                set_clauses.append("parent_id = :parent_id")
                params["parent_id"] = request.parent_department_id
            if request.description is not None:
                set_clauses.append("description = :description")
                params["description"] = request.description
            if request.display_order is not None:
                set_clauses.append("display_order = :display_order")
                params["display_order"] = request.display_order

            if not set_clauses:
                return DepartmentMutationResponse(
                    status="success",
                    department_id=dept_id,
                    message="更新項目がありません",
                )

            set_clauses.append("updated_by = :updated_by")
            params["updated_by"] = user.user_id
            set_clauses.append("updated_at = NOW()")

            query = f"""
                UPDATE departments
                SET {', '.join(set_clauses)}
                WHERE id = :dept_id AND organization_id = :org_id
            """
            conn.execute(text(query), params)
            conn.commit()

        log_audit_event(
            logger=logger,
            action="update_department",
            resource_type="department",
            resource_id=dept_id,
            user_id=user.user_id,
            details={"updated_fields": [c.split(" = ")[0] for c in set_clauses[:-2]]},
        )

        return DepartmentMutationResponse(
            status="success",
            department_id=dept_id,
            message="部署情報を更新しました",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Update department error",
            organization_id=organization_id,
            dept_id=dept_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failed",
                "error_code": "INTERNAL_ERROR",
                "error_message": "内部エラーが発生しました",
            },
        )


@router.delete(
    "/departments/{dept_id}",
    response_model=DepartmentMutationResponse,
    responses={
        403: {"model": AdminErrorResponse, "description": "権限不足（Level 6必要）"},
        404: {"model": AdminErrorResponse, "description": "部署が見つからない"},
        409: {"model": AdminErrorResponse, "description": "子部署またはメンバーが存在"},
        500: {"model": AdminErrorResponse, "description": "サーバーエラー"},
    },
    summary="部署削除（ソフト削除, Level 6+）",
    description="部署をソフト削除（is_active=false）する。子部署またはメンバーがいる場合は拒否。",
)
async def delete_department(
    dept_id: str = Path(
        ...,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        description="部署ID（UUID）",
    ),
    user: UserContext = Depends(require_editor),
):
    """部署をソフト削除する"""

    organization_id = user.organization_id

    pool = get_db_pool()

    try:
        with pool.connect() as conn:
            # 対象部署の存在確認
            exists_result = conn.execute(
                text("""
                    SELECT id, name FROM departments
                    WHERE id = :dept_id
                      AND organization_id = :org_id
                      AND is_active = TRUE
                    LIMIT 1
                """),
                {"dept_id": dept_id, "org_id": organization_id},
            )
            dept_row = exists_result.fetchone()
            if not dept_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "status": "failed",
                        "error_code": "DEPARTMENT_NOT_FOUND",
                        "error_message": "指定された部署が見つかりません",
                    },
                )

            # 子部署の存在チェック
            children_result = conn.execute(
                text("""
                    SELECT COUNT(*) FROM departments
                    WHERE parent_id = :dept_id
                      AND organization_id = :org_id
                      AND is_active = TRUE
                """),
                {"dept_id": dept_id, "org_id": organization_id},
            )
            if int(children_result.fetchone()[0]) > 0:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "status": "failed",
                        "error_code": "HAS_CHILDREN",
                        "error_message": "子部署が存在するため削除できません。先に子部署を移動または削除してください",
                    },
                )

            # 所属メンバーの存在チェック（org_id防御）
            members_result = conn.execute(
                text("""
                    SELECT COUNT(*) FROM user_departments ud
                    JOIN users u ON ud.user_id = u.id
                    WHERE ud.department_id = :dept_id
                      AND ud.ended_at IS NULL
                      AND u.organization_id = :org_id
                """),
                {"dept_id": dept_id, "org_id": organization_id},
            )
            if int(members_result.fetchone()[0]) > 0:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "status": "failed",
                        "error_code": "HAS_MEMBERS",
                        "error_message": "所属メンバーが存在するため削除できません。先にメンバーを異動させてください",
                    },
                )

            # ソフト削除
            conn.execute(
                text("""
                    UPDATE departments
                    SET is_active = FALSE, updated_by = :updated_by, updated_at = NOW()
                    WHERE id = :dept_id AND organization_id = :org_id
                """),
                {
                    "dept_id": dept_id,
                    "org_id": organization_id,
                    "updated_by": user.user_id,
                },
            )
            conn.commit()

        dept_name = dept_row[1] or dept_id

        log_audit_event(
            logger=logger,
            action="delete_department",
            resource_type="department",
            resource_id=dept_id,
            user_id=user.user_id,
            details={"department_name": dept_name},
        )

        return DepartmentMutationResponse(
            status="success",
            department_id=dept_id,
            message=f"部署「{dept_name}」を削除しました",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Delete department error",
            organization_id=organization_id,
            dept_id=dept_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failed",
                "error_code": "INTERNAL_ERROR",
                "error_message": "内部エラーが発生しました",
            },
        )
