"""
Organization Schemas

組織階層連携用のPydanticスキーマ（Phase 3.5）
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


# =============================================================================
# リクエストスキーマ
# =============================================================================


class DepartmentInput(BaseModel):
    """部署入力データ"""

    id: str = Field(..., description="部署ID")
    name: str = Field(..., description="部署名")
    code: Optional[str] = Field(None, description="部署コード")
    parentId: Optional[str] = Field(None, description="親部署ID")
    level: int = Field(1, ge=1, le=10, description="階層レベル")
    displayOrder: int = Field(0, description="表示順序")
    isActive: bool = Field(True, description="有効フラグ")
    description: Optional[str] = Field(None, description="説明")


class RoleInput(BaseModel):
    """役職入力データ"""

    id: str = Field(..., description="役職ID")
    name: str = Field(..., description="役職名")
    level: int = Field(1, description="役職レベル")
    description: Optional[str] = Field(None, description="説明")


class EmployeeInput(BaseModel):
    """社員入力データ"""

    id: str = Field(..., description="ユーザーID")
    name: str = Field(..., description="社員名")
    email: Optional[str] = Field(None, description="メールアドレス")
    departmentId: str = Field(..., description="所属部署ID")
    roleId: Optional[str] = Field(None, description="役職ID")
    isPrimary: bool = Field(True, description="主所属フラグ")
    startDate: Optional[str] = Field(None, description="開始日（YYYY-MM-DD）")
    endDate: Optional[str] = Field(None, description="終了日（YYYY-MM-DD）")


class AccessScopeInput(BaseModel):
    """アクセススコープ入力データ"""

    departmentId: str = Field(..., description="部署ID")
    canViewChildDepartments: bool = Field(True, description="配下部署閲覧可")
    canViewSiblingDepartments: bool = Field(False, description="兄弟部署閲覧可")
    canViewParentDepartments: bool = Field(False, description="親部署閲覧可")
    maxDepth: int = Field(99, description="最大参照深度")


class SyncOptions(BaseModel):
    """同期オプション"""

    include_inactive_users: bool = Field(False, description="非アクティブユーザーを含む")
    include_archived_departments: bool = Field(
        False, description="アーカイブ済み部署を含む"
    )
    dry_run: bool = Field(False, description="ドライラン（実際には更新しない）")


class OrgChartSyncRequest(BaseModel):
    """組織図同期リクエスト"""

    organization_id: str = Field(..., description="組織ID")
    source: str = Field("org_chart_system", description="データソース")
    sync_type: str = Field(
        "full",
        pattern="^(full|incremental)$",
        description="同期タイプ（full: 全置換, incremental: 差分）",
    )

    departments: List[DepartmentInput] = Field(
        default_factory=list,
        description="部署データ",
    )
    roles: List[RoleInput] = Field(
        default_factory=list,
        description="役職データ",
    )
    employees: List[EmployeeInput] = Field(
        default_factory=list,
        description="社員データ",
    )
    access_scopes: List[AccessScopeInput] = Field(
        default_factory=list,
        description="アクセススコープデータ",
    )

    options: SyncOptions = Field(
        default_factory=SyncOptions,
        description="同期オプション",
    )


# =============================================================================
# レスポンススキーマ
# =============================================================================


class SyncSummary(BaseModel):
    """同期結果サマリー"""

    departments_added: int = Field(0, description="追加された部署数")
    departments_updated: int = Field(0, description="更新された部署数")
    departments_deleted: int = Field(0, description="削除された部署数")
    users_added: int = Field(0, description="追加されたユーザー数")
    users_updated: int = Field(0, description="更新されたユーザー数")
    users_deleted: int = Field(0, description="削除されたユーザー数")
    roles_added: int = Field(0, description="追加された役職数")


class OrgChartSyncResponse(BaseModel):
    """組織図同期レスポンス"""

    status: str = Field(..., description="ステータス（success/failed）")
    sync_id: str = Field(..., description="同期ログID")
    summary: SyncSummary = Field(..., description="同期結果サマリー")
    duration_ms: int = Field(..., description="処理時間（ミリ秒）")
    synced_at: datetime = Field(..., description="同期完了日時")


class SyncErrorResponse(BaseModel):
    """同期エラーレスポンス"""

    status: str = Field("failed", description="ステータス")
    error_code: str = Field(..., description="エラーコード")
    error_message: str = Field(..., description="エラーメッセージ")
    error_details: Optional[dict] = Field(None, description="エラー詳細")


# =============================================================================
# 部署照会レスポンス
# =============================================================================


class DepartmentResponse(BaseModel):
    """部署レスポンス"""

    id: str
    name: str
    code: Optional[str]
    parent_id: Optional[str]
    level: int
    path: str
    display_order: int
    description: Optional[str]
    is_active: bool
    children_count: int = 0
    member_count: int = 0


class DepartmentDetailResponse(DepartmentResponse):
    """部署詳細レスポンス"""

    parent: Optional[DepartmentResponse] = None
    children: List[DepartmentResponse] = Field(default_factory=list)
    members: List[dict] = Field(default_factory=list)
    access_scope: Optional[dict] = None


class DepartmentListResponse(BaseModel):
    """部署一覧レスポンス"""

    departments: List[DepartmentResponse]
    total: int
