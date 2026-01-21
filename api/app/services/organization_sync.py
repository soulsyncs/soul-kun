"""
Organization Sync Service

組織図同期のビジネスロジック（Phase 3.5）
"""

from datetime import datetime, timezone
from collections import defaultdict
from typing import Dict, List, Optional
import time

from sqlalchemy import text
from sqlalchemy.engine import Connection

from lib.logging import get_logger
from app.schemas.organization import (
    OrgChartSyncRequest,
    OrgChartSyncResponse,
    SyncSummary,
    DepartmentInput,
)

logger = get_logger(__name__)


class OrganizationSyncError(Exception):
    """組織同期エラー"""

    def __init__(self, error_code: str, message: str, details: Optional[dict] = None):
        self.error_code = error_code
        self.message = message
        self.details = details or {}
        super().__init__(message)


class OrganizationSyncService:
    """組織図同期サービス"""

    def __init__(self, conn: Connection):
        self.conn = conn

    def sync_org_chart(
        self,
        org_id: str,
        data: OrgChartSyncRequest,
        triggered_by: Optional[str] = None,
    ) -> OrgChartSyncResponse:
        """
        組織図を同期

        Args:
            org_id: 組織ID
            data: 同期リクエストデータ
            triggered_by: 実行ユーザーID

        Returns:
            同期結果レスポンス
        """
        start_time = time.time()

        # 同期ログを作成
        sync_log_id = self._create_sync_log(
            org_id=org_id,
            sync_type=data.sync_type,
            source_system=data.source,
            triggered_by=triggered_by,
        )

        try:
            # ドライランの場合はバリデーションのみ
            if data.options.dry_run:
                self._validate_org_chart_data(data)
                summary = SyncSummary(
                    departments_added=len(data.departments),
                    users_added=len(data.employees),
                    roles_added=len(data.roles),
                )
            else:
                # 実際の同期処理
                summary = self._execute_sync(org_id, data)

            # 処理時間を計算
            duration_ms = int((time.time() - start_time) * 1000)

            # 同期ログを更新（成功）
            self._update_sync_log(
                sync_log_id=sync_log_id,
                status="success",
                summary=summary,
                duration_ms=duration_ms,
            )

            return OrgChartSyncResponse(
                status="success",
                sync_id=sync_log_id,
                summary=summary,
                duration_ms=duration_ms,
                synced_at=datetime.now(timezone.utc),
            )

        except OrganizationSyncError as e:
            # 同期ログを更新（失敗）
            duration_ms = int((time.time() - start_time) * 1000)
            self._update_sync_log(
                sync_log_id=sync_log_id,
                status="failed",
                error_message=e.message,
                error_details={"error_code": e.error_code, **e.details},
                duration_ms=duration_ms,
            )
            raise

        except Exception as e:
            # 同期ログを更新（失敗）
            duration_ms = int((time.time() - start_time) * 1000)
            self._update_sync_log(
                sync_log_id=sync_log_id,
                status="failed",
                error_message=str(e),
                duration_ms=duration_ms,
            )
            raise

    def _execute_sync(
        self,
        org_id: str,
        data: OrgChartSyncRequest,
    ) -> SyncSummary:
        """同期処理を実行"""

        # バリデーション
        self._validate_org_chart_data(data)

        summary = SyncSummary()

        # フル同期の場合は既存データを削除
        if data.sync_type == "full":
            deleted = self._delete_existing_departments(org_id)
            summary.departments_deleted = deleted

        # 役職を同期
        if data.roles:
            roles_added = self._sync_roles(org_id, data.roles)
            summary.roles_added = roles_added

        # 部署をトポロジカルソートして同期
        sorted_depts = self._topological_sort(data.departments)
        dept_map = self._sync_departments(org_id, sorted_depts)
        summary.departments_added = len(dept_map)

        # 階層テーブルを再構築
        self._rebuild_department_hierarchies(org_id, dept_map)

        # ユーザー所属を同期
        if data.employees:
            users_added = self._sync_employees(org_id, data.employees, dept_map)
            summary.users_added = users_added

        # アクセススコープを同期
        if data.access_scopes:
            self._sync_access_scopes(data.access_scopes, dept_map)

        return summary

    def _validate_org_chart_data(self, data: OrgChartSyncRequest) -> None:
        """組織図データのバリデーション"""

        # 循環参照チェック
        if self._has_cycle(data.departments):
            raise OrganizationSyncError(
                error_code="CIRCULAR_REFERENCE",
                message="部署に循環参照が検出されました",
            )

        # 孤立部署チェック
        orphans = self._find_orphan_departments(data.departments)
        if orphans:
            raise OrganizationSyncError(
                error_code="ORPHAN_DEPARTMENT",
                message=f"親部署が存在しない部署: {orphans}",
                details={"orphan_departments": orphans},
            )

        # 部署コード重複チェック
        codes = [d.code for d in data.departments if d.code]
        if len(codes) != len(set(codes)):
            duplicates = [c for c in codes if codes.count(c) > 1]
            raise OrganizationSyncError(
                error_code="DUPLICATE_CODE",
                message=f"部署コードが重複しています: {set(duplicates)}",
                details={"duplicate_codes": list(set(duplicates))},
            )

        # 部署数上限チェック
        if len(data.departments) > 1000:
            raise OrganizationSyncError(
                error_code="TOO_MANY_DEPARTMENTS",
                message="部署数が上限（1000）を超えています",
                details={"department_count": len(data.departments)},
            )

    def _topological_sort(
        self,
        departments: List[DepartmentInput],
    ) -> List[DepartmentInput]:
        """
        部署を階層順にソート（親 → 子の順）

        Kahn's algorithmを使用
        """
        graph = defaultdict(list)
        in_degree = defaultdict(int)
        dept_map = {d.id: d for d in departments}

        for dept in departments:
            if dept.parentId:
                graph[dept.parentId].append(dept.id)
                in_degree[dept.id] += 1
            else:
                in_degree[dept.id] = 0

        # ルート部署（親がない）から開始
        queue = [d.id for d in departments if in_degree[d.id] == 0]
        sorted_ids = []

        while queue:
            dept_id = queue.pop(0)
            sorted_ids.append(dept_id)

            for child_id in graph[dept_id]:
                in_degree[child_id] -= 1
                if in_degree[child_id] == 0:
                    queue.append(child_id)

        # 循環参照があれば全てソートできない
        if len(sorted_ids) != len(departments):
            raise OrganizationSyncError(
                error_code="CIRCULAR_REFERENCE",
                message="循環参照が検出されました",
            )

        return [dept_map[dept_id] for dept_id in sorted_ids]

    def _has_cycle(self, departments: List[DepartmentInput]) -> bool:
        """循環参照をチェック"""
        try:
            self._topological_sort(departments)
            return False
        except OrganizationSyncError:
            return True

    def _find_orphan_departments(
        self,
        departments: List[DepartmentInput],
    ) -> List[str]:
        """親部署が存在しない部署を検出"""
        dept_ids = {d.id for d in departments}
        orphans = []

        for dept in departments:
            if dept.parentId and dept.parentId not in dept_ids:
                orphans.append(dept.id)

        return orphans

    def _create_sync_log(
        self,
        org_id: str,
        sync_type: str,
        source_system: str,
        triggered_by: Optional[str],
    ) -> str:
        """同期ログを作成"""
        import uuid
        from datetime import datetime

        # sync_id を生成（例: SYNC-20260117-abc123）
        sync_id = f"SYNC-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

        result = self.conn.execute(
            text("""
                INSERT INTO org_chart_sync_logs
                (sync_id, organization_id, sync_type, status, source_system,
                 triggered_by, started_at, created_at)
                VALUES (:sync_id, :org_id, :sync_type, 'in_progress', :source_system,
                        :triggered_by, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                RETURNING id
            """),
            {
                "sync_id": sync_id,
                "org_id": org_id,
                "sync_type": sync_type,
                "source_system": source_system,
                "triggered_by": triggered_by,
            },
        )
        row = result.fetchone()
        return str(row[0])

    def _update_sync_log(
        self,
        sync_log_id: str,
        status: str,
        summary: Optional[SyncSummary] = None,
        error_message: Optional[str] = None,
        error_details: Optional[dict] = None,
        duration_ms: Optional[int] = None,
    ) -> None:
        """同期ログを更新"""
        params = {
            "id": sync_log_id,
            "status": status,
            "completed_at": datetime.now(timezone.utc),
            "duration_ms": duration_ms,
            "error_message": error_message,
        }

        if summary:
            params.update(
                {
                    "departments_added": summary.departments_added,
                    "departments_updated": summary.departments_updated,
                    "departments_deleted": summary.departments_deleted,
                    "employees_added": summary.users_added,
                    "employees_updated": summary.users_updated,
                    "employees_deleted": summary.users_deleted,
                }
            )

        self.conn.execute(
            text("""
                UPDATE org_chart_sync_logs
                SET status = :status,
                    completed_at = :completed_at,
                    duration_ms = :duration_ms,
                    error_message = :error_message,
                    departments_added = COALESCE(:departments_added, departments_added),
                    departments_updated = COALESCE(:departments_updated, departments_updated),
                    departments_deleted = COALESCE(:departments_deleted, departments_deleted),
                    employees_added = COALESCE(:employees_added, employees_added),
                    employees_updated = COALESCE(:employees_updated, employees_updated),
                    employees_deleted = COALESCE(:employees_deleted, employees_deleted)
                WHERE id = :id
            """),
            {
                **params,
                "departments_added": summary.departments_added if summary else None,
                "departments_updated": summary.departments_updated if summary else None,
                "departments_deleted": summary.departments_deleted if summary else None,
                "employees_added": summary.users_added if summary else None,
                "employees_updated": summary.users_updated if summary else None,
                "employees_deleted": summary.users_deleted if summary else None,
            },
        )

    def _delete_existing_departments(self, org_id: str) -> int:
        """既存の部署を削除"""
        result = self.conn.execute(
            text("""
                DELETE FROM departments
                WHERE organization_id = :org_id
            """),
            {"org_id": org_id},
        )
        return result.rowcount

    def _sync_roles(self, org_id: str, roles: list) -> int:
        """役職を同期（external_idで識別）"""
        count = 0
        for role in roles:
            # 既存チェック
            result = self.conn.execute(
                text("SELECT id FROM roles WHERE external_id = :external_id"),
                {"external_id": role.id},
            )
            existing = result.fetchone()

            if existing:
                # UPDATE
                self.conn.execute(
                    text("""
                        UPDATE roles SET name = :name, level = :level,
                        description = :description, updated_at = CURRENT_TIMESTAMP
                        WHERE external_id = :external_id
                    """),
                    {
                        "external_id": role.id,
                        "name": role.name,
                        "level": role.level,
                        "description": role.description,
                    },
                )
            else:
                # INSERT
                self.conn.execute(
                    text("""
                        INSERT INTO roles (organization_id, external_id, name, level, description)
                        VALUES (:org_id, :external_id, :name, :level, :description)
                    """),
                    {
                        "external_id": role.id,
                        "org_id": org_id,
                        "name": role.name,
                        "level": role.level,
                        "description": role.description,
                    },
                )
            count += 1
        return count

    def _sync_departments(
        self,
        org_id: str,
        sorted_depts: List[DepartmentInput],
    ) -> Dict[str, str]:
        """部署を同期し、external_id→パスのマップを返す"""
        dept_map: Dict[str, str] = {}  # external_id -> path

        for dept in sorted_depts:
            # 親部署のパスを取得
            if dept.parentId and dept.parentId in dept_map:
                parent_path = dept_map[dept.parentId]
                code = (dept.code or dept.id).lower().replace("-", "_")
                path = f"{parent_path}.{code}"
            else:
                path = (dept.code or dept.id).lower().replace("-", "_")

            # 親部署のUUIDを取得
            parent_uuid = None
            if dept.parentId:
                parent_result = self.conn.execute(
                    text("SELECT id FROM departments WHERE external_id = :ext_id AND organization_id = :org_id"),
                    {"ext_id": dept.parentId, "org_id": org_id},
                )
                parent_row = parent_result.fetchone()
                if parent_row:
                    parent_uuid = parent_row[0]

            # 既存チェック
            existing_result = self.conn.execute(
                text("SELECT id FROM departments WHERE external_id = :external_id"),
                {"external_id": dept.id},
            )
            existing = existing_result.fetchone()

            if existing:
                # UPDATE
                self.conn.execute(
                    text("""
                        UPDATE departments SET name = :name, code = :code,
                        parent_id = :parent_id, level = :level, path = :path,
                        display_order = :display_order, description = :description,
                        is_active = :is_active, updated_at = CURRENT_TIMESTAMP
                        WHERE external_id = :external_id
                    """),
                    {
                        "external_id": dept.id,
                        "name": dept.name,
                        "code": dept.code or dept.id,
                        "parent_id": parent_uuid,
                        "level": dept.level,
                        "path": path,
                        "display_order": dept.displayOrder,
                        "description": dept.description,
                        "is_active": dept.isActive,
                    },
                )
            else:
                # INSERT
                self.conn.execute(
                    text("""
                        INSERT INTO departments
                        (organization_id, external_id, name, code, parent_id,
                         level, path, display_order, description, is_active)
                        VALUES (:org_id, :external_id, :name, :code, :parent_id,
                                :level, :path, :display_order, :description, :is_active)
                    """),
                    {
                        "external_id": dept.id,
                        "org_id": org_id,
                        "name": dept.name,
                        "code": dept.code or dept.id,
                        "parent_id": parent_uuid,
                        "level": dept.level,
                        "path": path,
                        "display_order": dept.displayOrder,
                        "description": dept.description,
                        "is_active": dept.isActive,
                    },
                )
            dept_map[dept.id] = path

        return dept_map

    def _rebuild_department_hierarchies(
        self,
        org_id: str,
        dept_map: Dict[str, str],
    ) -> None:
        """部署階層テーブルを再構築（external_id→UUID変換）"""

        # external_id → UUID マップを作成
        ext_to_uuid: Dict[str, str] = {}
        for ext_id in dept_map.keys():
            result = self.conn.execute(
                text("SELECT id FROM departments WHERE external_id = :ext_id AND organization_id = :org_id"),
                {"ext_id": ext_id, "org_id": org_id},
            )
            row = result.fetchone()
            if row:
                ext_to_uuid[ext_id] = str(row[0])

        # 既存の階層データを削除
        self.conn.execute(
            text("""
                DELETE FROM department_hierarchies
                WHERE organization_id = :org_id
            """),
            {"org_id": org_id},
        )

        # 各部署について、祖先→子孫の関係を挿入
        for ext_id, path in dept_map.items():
            descendant_uuid = ext_to_uuid.get(ext_id)
            if not descendant_uuid:
                continue

            # パスから祖先を計算
            path_parts = path.split(".")
            for depth, _ in enumerate(path_parts):
                ancestor_path = ".".join(path_parts[: len(path_parts) - depth])
                ancestor_ext_id = self._find_dept_id_by_path(dept_map, ancestor_path)

                if ancestor_ext_id:
                    ancestor_uuid = ext_to_uuid.get(ancestor_ext_id)
                    if ancestor_uuid:
                        self.conn.execute(
                            text("""
                                INSERT INTO department_hierarchies
                                (organization_id, ancestor_department_id,
                                 descendant_department_id, depth)
                                VALUES (:org_id, :ancestor_id, :descendant_id, :depth)
                                ON CONFLICT DO NOTHING
                            """),
                            {
                                "org_id": org_id,
                                "ancestor_id": ancestor_uuid,
                                "descendant_id": descendant_uuid,
                                "depth": depth,
                            },
                        )

    def _find_dept_id_by_path(
        self,
        dept_map: Dict[str, str],
        target_path: str,
    ) -> Optional[str]:
        """パスから部署IDを検索"""
        for dept_id, path in dept_map.items():
            if path == target_path:
                return dept_id
        return None

    def _sync_employees(
        self,
        org_id: str,
        employees: list,
        dept_map: Dict[str, str],
    ) -> int:
        """社員の所属を同期（external_idで識別）"""
        count = 0

        for emp in employees:
            if emp.departmentId not in dept_map:
                logger.warning(
                    f"Department not found for employee: {emp.id}",
                    department_id=emp.departmentId,
                )
                continue

            # ユーザー既存チェック
            user_check = self.conn.execute(
                text("SELECT id FROM users WHERE external_id = :external_id"),
                {"external_id": emp.id},
            )
            existing_user = user_check.fetchone()

            if existing_user:
                # UPDATE
                self.conn.execute(
                    text("""
                        UPDATE users SET name = :name, email = :email,
                        updated_at = CURRENT_TIMESTAMP
                        WHERE external_id = :external_id
                    """),
                    {
                        "external_id": emp.id,
                        "email": emp.email or f"{emp.id}@example.com",
                        "name": emp.name,
                    },
                )
            else:
                # INSERT
                self.conn.execute(
                    text("""
                        INSERT INTO users (organization_id, external_id, email, name)
                        VALUES (:org_id, :external_id, :email, :name)
                    """),
                    {
                        "external_id": emp.id,
                        "org_id": org_id,
                        "email": emp.email or f"{emp.id}@example.com",
                        "name": emp.name,
                    },
                )

            # ユーザーのUUIDを取得
            result = self.conn.execute(
                text("SELECT id FROM users WHERE external_id = :external_id AND organization_id = :org_id"),
                {"external_id": emp.id, "org_id": org_id},
            )
            user_row = result.fetchone()
            if not user_row:
                logger.error(f"Failed to get user UUID for {emp.id}")
                continue
            user_uuid = user_row[0]

            # 部署のUUIDを取得
            dept_result = self.conn.execute(
                text("SELECT id FROM departments WHERE external_id = :external_id AND organization_id = :org_id"),
                {"external_id": emp.departmentId, "org_id": org_id},
            )
            dept_row = dept_result.fetchone()
            if not dept_row:
                logger.error(f"Failed to get department UUID for {emp.departmentId}")
                continue
            dept_uuid = dept_row[0]

            # 既存の所属を終了
            self.conn.execute(
                text("""
                    UPDATE user_departments
                    SET ended_at = CURRENT_TIMESTAMP
                    WHERE user_id = :user_id AND ended_at IS NULL
                """),
                {"user_id": user_uuid},
            )

            # 新しい所属を追加
            self.conn.execute(
                text("""
                    INSERT INTO user_departments
                    (user_id, department_id, is_primary, role_in_dept, started_at)
                    VALUES (:user_id, :dept_id, :is_primary, :role_in_dept,
                            COALESCE(CAST(:start_date AS date), CURRENT_DATE))
                """),
                {
                    "user_id": user_uuid,
                    "dept_id": dept_uuid,
                    "is_primary": emp.isPrimary,
                    "role_in_dept": emp.roleId,
                    "start_date": emp.startDate,
                },
            )
            count += 1

        return count

    def _sync_access_scopes(
        self,
        access_scopes: list,
        dept_map: Dict[str, str],
    ) -> None:
        """アクセススコープを同期"""
        for scope in access_scopes:
            if scope.departmentId not in dept_map:
                continue

            self.conn.execute(
                text("""
                    INSERT INTO department_access_scopes
                    (department_id, can_view_child_departments,
                     can_view_sibling_departments, can_view_parent_departments,
                     max_depth)
                    VALUES (:dept_id, :can_child, :can_sibling, :can_parent, :max_depth)
                    ON CONFLICT (department_id) DO UPDATE
                    SET can_view_child_departments = :can_child,
                        can_view_sibling_departments = :can_sibling,
                        can_view_parent_departments = :can_parent,
                        max_depth = :max_depth,
                        updated_at = CURRENT_TIMESTAMP
                """),
                {
                    "dept_id": scope.departmentId,
                    "can_child": scope.canViewChildDepartments,
                    "can_sibling": scope.canViewSiblingDepartments,
                    "can_parent": scope.canViewParentDepartments,
                    "max_depth": scope.maxDepth,
                },
            )
