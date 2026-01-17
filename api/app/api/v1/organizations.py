"""
Organizations API

組織階層連携API（Phase 3.5）
"""

from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import JSONResponse
from typing import Optional

from sqlalchemy import text

from lib.db import get_db_pool
from lib.logging import get_logger, log_audit_event
from lib.tenant import get_current_or_default_tenant
from lib.config import get_settings
from api.app.schemas.organization import (
    OrgChartSyncRequest,
    OrgChartSyncResponse,
    SyncErrorResponse,
    DepartmentListResponse,
    DepartmentResponse,
)
from api.app.services.organization_sync import (
    OrganizationSyncService,
    OrganizationSyncError,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])
logger = get_logger(__name__)


@router.post(
    "/{org_id}/sync-org-chart",
    response_model=OrgChartSyncResponse,
    responses={
        400: {"model": SyncErrorResponse, "description": "バリデーションエラー"},
        403: {"model": SyncErrorResponse, "description": "権限エラー"},
        500: {"model": SyncErrorResponse, "description": "サーバーエラー"},
    },
)
async def sync_org_chart(
    org_id: str,
    data: OrgChartSyncRequest,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    authorization: Optional[str] = Header(None),
):
    """
    組織図同期API

    組織図WebアプリからソウルくんDBに組織構造を同期します。

    - **sync_type**: full（全置換）または incremental（差分更新）
    - **departments**: 部署データの配列
    - **employees**: 社員データの配列
    - **roles**: 役職データの配列
    - **access_scopes**: アクセススコープデータの配列
    """
    logger.info(
        f"Sync org chart started",
        org_id=org_id,
        sync_type=data.sync_type,
        departments_count=len(data.departments),
        employees_count=len(data.employees),
    )

    # 組織IDの一致を確認
    if data.organization_id != org_id:
        raise HTTPException(
            status_code=400,
            detail={
                "status": "failed",
                "error_code": "ORG_ID_MISMATCH",
                "error_message": "リクエストボディの organization_id とパスの org_id が一致しません",
            },
        )

    pool = get_db_pool()
    settings = get_settings()

    try:
        with pool.connect() as conn:
            # 組織の存在確認（organization_idカラムで検索）
            result = conn.execute(
                text("SELECT id FROM organizations WHERE organization_id = :org_id"),
                {"org_id": org_id},
            )
            if not result.fetchone():
                # DEBUGモードではテスト用組織を自動作成
                if settings.DEBUG:
                    logger.warning(f"DEBUGモード: 組織 {org_id} を自動作成します")
                    conn.execute(
                        text("""
                            INSERT INTO organizations (id, organization_id, name, created_at, updated_at)
                            VALUES (:id, :organization_id, :name, NOW(), NOW())
                            ON CONFLICT (id) DO NOTHING
                        """),
                        {
                            "id": org_id,
                            "organization_id": f"test_{org_id[:8]}",
                            "name": f"テスト組織",
                        },
                    )
                    conn.commit()
                else:
                    raise HTTPException(
                        status_code=404,
                        detail={
                            "status": "failed",
                            "error_code": "ORG_NOT_FOUND",
                            "error_message": f"組織 {org_id} が見つかりません",
                        },
                    )

            # 同期サービスを実行
            service = OrganizationSyncService(conn)
            response = service.sync_org_chart(
                org_id=org_id,
                data=data,
                triggered_by=x_user_id,
            )

            conn.commit()

        # 監査ログ
        log_audit_event(
            logger=logger,
            action="sync_org_chart",
            resource_type="organization",
            resource_id=org_id,
            user_id=x_user_id,
            details={
                "sync_type": data.sync_type,
                "departments_added": response.summary.departments_added,
                "users_added": response.summary.users_added,
            },
        )

        logger.info(
            f"Sync org chart completed",
            org_id=org_id,
            sync_id=response.sync_id,
            duration_ms=response.duration_ms,
        )

        return response

    except OrganizationSyncError as e:
        logger.error(
            f"Sync org chart failed: {e.error_code}",
            org_id=org_id,
            error_code=e.error_code,
            error_message=e.message,
        )
        return JSONResponse(
            status_code=400,
            content={
                "status": "failed",
                "error_code": e.error_code,
                "error_message": e.message,
                "error_details": e.details,
            },
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(f"Sync org chart error", org_id=org_id)
        return JSONResponse(
            status_code=500,
            content={
                "status": "failed",
                "error_code": "INTERNAL_ERROR",
                "error_message": "内部エラーが発生しました",
            },
        )


@router.get(
    "/{org_id}/departments",
    response_model=DepartmentListResponse,
)
async def get_departments(
    org_id: str,
    parent_id: Optional[str] = None,
    level: Optional[int] = None,
    include_children: bool = False,
    is_active: bool = True,
):
    """
    部署一覧取得API

    組織の部署一覧を取得します。

    - **parent_id**: 親部署ID（指定すると子部署のみ）
    - **level**: 階層レベル
    - **include_children**: 配下すべてを含む
    - **is_active**: 有効な部署のみ
    """
    pool = get_db_pool()

    with pool.connect() as conn:
        # 基本クエリ
        query = """
            SELECT
                d.id,
                d.name,
                d.code,
                d.parent_id,
                d.level,
                d.path,
                d.display_order,
                d.description,
                d.is_active,
                (SELECT COUNT(*) FROM departments c
                 WHERE c.parent_id = d.id) as children_count,
                (SELECT COUNT(*) FROM user_departments ud
                 WHERE ud.department_id = d.id AND ud.ended_at IS NULL) as member_count
            FROM departments d
            WHERE d.organization_id = :org_id
        """
        params = {"org_id": org_id}

        if is_active:
            query += " AND d.is_active = TRUE"

        if parent_id:
            if include_children:
                # 配下すべてを含む（LTREE使用）
                query += " AND d.path <@ (SELECT path FROM departments WHERE id = :parent_id)"
            else:
                query += " AND d.parent_id = :parent_id"
            params["parent_id"] = parent_id

        if level:
            query += " AND d.level = :level"
            params["level"] = level

        query += " ORDER BY d.display_order, d.name"

        result = conn.execute(text(query), params)
        rows = result.fetchall()

        departments = [
            DepartmentResponse(
                id=str(row[0]),
                name=row[1],
                code=row[2],
                parent_id=str(row[3]) if row[3] else None,
                level=row[4],
                path=row[5],
                display_order=row[6],
                description=row[7],
                is_active=row[8],
                children_count=row[9],
                member_count=row[10],
            )
            for row in rows
        ]

        return DepartmentListResponse(
            departments=departments,
            total=len(departments),
        )


@router.get(
    "/{org_id}/departments/{dept_id}",
    response_model=DepartmentResponse,
)
async def get_department(
    org_id: str,
    dept_id: str,
):
    """
    部署詳細取得API

    特定の部署の詳細情報を取得します。
    """
    pool = get_db_pool()

    with pool.connect() as conn:
        result = conn.execute(
            text("""
                SELECT
                    d.id,
                    d.name,
                    d.code,
                    d.parent_id,
                    d.level,
                    d.path,
                    d.display_order,
                    d.description,
                    d.is_active,
                    (SELECT COUNT(*) FROM departments c
                     WHERE c.parent_id = d.id) as children_count,
                    (SELECT COUNT(*) FROM user_departments ud
                     WHERE ud.department_id = d.id AND ud.ended_at IS NULL) as member_count
                FROM departments d
                WHERE d.organization_id = :org_id AND d.id = :dept_id
            """),
            {"org_id": org_id, "dept_id": dept_id},
        )
        row = result.fetchone()

        if not row:
            raise HTTPException(
                status_code=404,
                detail={
                    "status": "failed",
                    "error_code": "DEPT_NOT_FOUND",
                    "error_message": f"部署 {dept_id} が見つかりません",
                },
            )

        return DepartmentResponse(
            id=str(row[0]),
            name=row[1],
            code=row[2],
            parent_id=str(row[3]) if row[3] else None,
            level=row[4],
            path=row[5],
            display_order=row[6],
            description=row[7],
            is_active=row[8],
            children_count=row[9],
            member_count=row[10],
        )
