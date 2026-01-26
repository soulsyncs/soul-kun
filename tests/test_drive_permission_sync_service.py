"""
Drive Permission Sync Service テスト

Phase C: Google Drive 自動権限管理機能
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime

from lib.drive_permission_sync_service import (
    DrivePermissionSyncService,
    FolderPermissionSpec,
    SyncPlan,
    SyncReport,
    FolderType,
    FOLDER_TYPE_MAP,
    FOLDER_MIN_ROLE_LEVEL,
    FOLDER_DEFAULT_ROLE,
)
from lib.drive_permission_manager import PermissionRole, PermissionSyncResult
from lib.org_chart_service import Employee, Department


# ================================================================
# Constants Tests
# ================================================================

class TestConstants:
    """定数テスト"""

    def test_folder_type_values(self):
        """フォルダタイプの値"""
        assert FolderType.PUBLIC.value == "public"
        assert FolderType.INTERNAL.value == "internal"
        assert FolderType.RESTRICTED.value == "restricted"
        assert FolderType.DEPARTMENT.value == "department"

    def test_folder_type_map(self):
        """フォルダ名→タイプマッピング"""
        assert FOLDER_TYPE_MAP["全社共有"] == FolderType.PUBLIC
        assert FOLDER_TYPE_MAP["社員限定"] == FolderType.INTERNAL
        assert FOLDER_TYPE_MAP["役員限定"] == FolderType.RESTRICTED
        assert FOLDER_TYPE_MAP["部署別"] == FolderType.DEPARTMENT

    def test_folder_min_role_level(self):
        """フォルダタイプ→最小役職レベル"""
        assert FOLDER_MIN_ROLE_LEVEL[FolderType.PUBLIC] == 1
        assert FOLDER_MIN_ROLE_LEVEL[FolderType.INTERNAL] == 1
        assert FOLDER_MIN_ROLE_LEVEL[FolderType.RESTRICTED] == 6
        assert FOLDER_MIN_ROLE_LEVEL[FolderType.DEPARTMENT] == 1

    def test_folder_default_role(self):
        """フォルダタイプ→デフォルト権限"""
        assert FOLDER_DEFAULT_ROLE[FolderType.PUBLIC] == PermissionRole.READER
        assert FOLDER_DEFAULT_ROLE[FolderType.RESTRICTED] == PermissionRole.READER


# ================================================================
# FolderPermissionSpec Tests
# ================================================================

class TestFolderPermissionSpec:
    """FolderPermissionSpecデータクラスのテスト"""

    def test_is_department_folder_true(self):
        """部署フォルダ判定（true）"""
        spec = FolderPermissionSpec(
            folder_id="folder1",
            folder_name="営業部",
            folder_type=FolderType.DEPARTMENT,
            folder_path=["部署別", "営業部"],
            department_name="営業部"
        )
        assert spec.is_department_folder is True

    def test_is_department_folder_false_no_name(self):
        """部署フォルダ判定（false - 名前なし）"""
        spec = FolderPermissionSpec(
            folder_id="folder1",
            folder_name="営業部",
            folder_type=FolderType.DEPARTMENT,
            folder_path=["部署別", "営業部"],
            department_name=None
        )
        assert spec.is_department_folder is False

    def test_is_department_folder_false_wrong_type(self):
        """部署フォルダ判定（false - タイプ違い）"""
        spec = FolderPermissionSpec(
            folder_id="folder1",
            folder_name="全社共有",
            folder_type=FolderType.PUBLIC,
            folder_path=["全社共有"],
            department_name="営業部"
        )
        assert spec.is_department_folder is False


# ================================================================
# SyncPlan Tests
# ================================================================

class TestSyncPlan:
    """SyncPlanデータクラスのテスト"""

    def test_created_at_auto_set(self):
        """作成日時が自動設定される"""
        plan = SyncPlan()
        assert plan.created_at is not None
        assert isinstance(plan.created_at, datetime)

    def test_folder_specs_default(self):
        """folder_specsのデフォルト値"""
        plan = SyncPlan()
        assert plan.folder_specs == []


# ================================================================
# SyncReport Tests
# ================================================================

class TestSyncReport:
    """SyncReportデータクラスのテスト"""

    def test_total_changes(self):
        """合計変更数"""
        report = SyncReport(
            permissions_added=5,
            permissions_removed=3,
            permissions_updated=2
        )
        assert report.total_changes == 10

    def test_duration_seconds(self):
        """処理時間"""
        report = SyncReport()
        report.started_at = datetime(2026, 1, 1, 12, 0, 0)
        report.completed_at = datetime(2026, 1, 1, 12, 0, 30)
        assert report.duration_seconds == 30.0

    def test_duration_seconds_not_completed(self):
        """未完了時の処理時間"""
        report = SyncReport()
        assert report.duration_seconds == 0

    def test_to_summary_dry_run(self):
        """サマリー出力（dry run）"""
        report = SyncReport(
            dry_run=True,
            folders_processed=5,
            permissions_added=10,
            permissions_removed=2,
            permissions_updated=3,
            permissions_unchanged=50,
            errors=1
        )
        report.completed_at = datetime.now()

        summary = report.to_summary()
        assert "[DRY RUN]" in summary
        assert "処理フォルダ数: 5" in summary
        assert "追加: 10" in summary
        assert "エラー: 1" in summary

    def test_to_summary_executed(self):
        """サマリー出力（実行）"""
        report = SyncReport(dry_run=False)
        report.completed_at = datetime.now()

        summary = report.to_summary()
        assert "[EXECUTED]" in summary


# ================================================================
# DrivePermissionSyncService Tests
# ================================================================

class TestDrivePermissionSyncService:
    """DrivePermissionSyncServiceのテスト"""

    @pytest.fixture
    def mock_services(self):
        """モックサービス"""
        with patch('lib.drive_permission_sync_service.OrgChartService') as mock_org, \
             patch('lib.drive_permission_sync_service.DrivePermissionManager') as mock_perm, \
             patch('lib.drive_permission_sync_service.GoogleDriveClient') as mock_drive:

            mock_org_instance = AsyncMock()
            mock_perm_instance = AsyncMock()
            mock_drive_instance = MagicMock()

            mock_org.return_value = mock_org_instance
            mock_perm.return_value = mock_perm_instance
            mock_drive.return_value = mock_drive_instance

            yield {
                'org': mock_org_instance,
                'perm': mock_perm_instance,
                'drive': mock_drive_instance
            }

    @pytest.fixture
    def sync_service(self, mock_services):
        """テスト用サービス"""
        service = DrivePermissionSyncService(
            supabase_url="https://test.supabase.co",
            supabase_key="test-key",
            service_account_info={'type': 'service_account'},
            root_folder_id="root123"
        )
        return service

    def test_determine_folder_type(self, sync_service):
        """フォルダタイプ判定"""
        assert sync_service._determine_folder_type("全社共有") == FolderType.PUBLIC
        assert sync_service._determine_folder_type("社員限定") == FolderType.INTERNAL
        assert sync_service._determine_folder_type("役員限定") == FolderType.RESTRICTED
        assert sync_service._determine_folder_type("部署別") == FolderType.DEPARTMENT
        assert sync_service._determine_folder_type("その他") == FolderType.UNKNOWN

    def test_calculate_expected_permissions_public(self, sync_service):
        """全社共有フォルダの期待権限"""
        # 社員キャッシュをセット
        sync_service._employees_cache = [
            Employee(id="emp1", name="User1", google_account_email="user1@test.com", role_level=1),
            Employee(id="emp2", name="User2", google_account_email="user2@test.com", role_level=4),
            Employee(id="emp3", name="User3", google_account_email=None, role_level=1),  # メールなし
        ]

        spec = FolderPermissionSpec(
            folder_id="folder1",
            folder_name="全社共有",
            folder_type=FolderType.PUBLIC,
            folder_path=["全社共有"]
        )

        permissions = sync_service._calculate_expected_permissions(spec)

        # メールがある社員のみ
        assert len(permissions) == 2
        assert "user1@test.com" in permissions
        assert "user2@test.com" in permissions
        # 役職レベルに応じた権限
        assert permissions["user1@test.com"] == PermissionRole.READER
        assert permissions["user2@test.com"] == PermissionRole.WRITER

    def test_calculate_expected_permissions_restricted(self, sync_service):
        """役員限定フォルダの期待権限"""
        sync_service._employees_cache = [
            Employee(id="emp1", name="Staff", google_account_email="staff@test.com", role_level=1),
            Employee(id="emp2", name="Manager", google_account_email="manager@test.com", role_level=4),
            Employee(id="emp3", name="Director", google_account_email="director@test.com", role_level=6),
        ]

        spec = FolderPermissionSpec(
            folder_id="folder1",
            folder_name="役員限定",
            folder_type=FolderType.RESTRICTED,
            folder_path=["役員限定"]
        )

        permissions = sync_service._calculate_expected_permissions(spec)

        # 役員（レベル6）のみ
        assert len(permissions) == 1
        assert "director@test.com" in permissions
        assert "staff@test.com" not in permissions
        assert "manager@test.com" not in permissions

    def test_calculate_expected_permissions_department(self, sync_service):
        """部署別フォルダの期待権限"""
        sync_service._employees_cache = [
            Employee(
                id="emp1", name="Sales1", google_account_email="sales1@test.com",
                role_level=1, department_id="dept_sales"
            ),
            Employee(
                id="emp2", name="Sales2", google_account_email="sales2@test.com",
                role_level=4, department_id="dept_sales"
            ),
            Employee(
                id="emp3", name="Dev1", google_account_email="dev1@test.com",
                role_level=1, department_id="dept_dev"
            ),
        ]

        spec = FolderPermissionSpec(
            folder_id="folder1",
            folder_name="営業部",
            folder_type=FolderType.DEPARTMENT,
            folder_path=["部署別", "営業部"],
            department_id="dept_sales",
            department_name="営業部"
        )

        permissions = sync_service._calculate_expected_permissions(spec)

        # 営業部のみ
        assert len(permissions) == 2
        assert "sales1@test.com" in permissions
        assert "sales2@test.com" in permissions
        assert "dev1@test.com" not in permissions
        # 役職レベルに応じた権限
        assert permissions["sales1@test.com"] == PermissionRole.READER
        assert permissions["sales2@test.com"] == PermissionRole.WRITER

    def test_calculate_expected_permissions_unknown(self, sync_service):
        """不明タイプフォルダは空"""
        sync_service._employees_cache = [
            Employee(id="emp1", name="User1", google_account_email="user1@test.com", role_level=1),
        ]

        spec = FolderPermissionSpec(
            folder_id="folder1",
            folder_name="不明",
            folder_type=FolderType.UNKNOWN,
            folder_path=["不明"]
        )

        permissions = sync_service._calculate_expected_permissions(spec)
        assert permissions == {}

    @pytest.mark.asyncio
    async def test_sync_all_folders_dry_run(self, sync_service, mock_services):
        """全フォルダ同期（dry run）"""
        # モックのセットアップ
        mock_services['org'].get_all_employees.return_value = [
            Employee(id="emp1", name="User1", google_account_email="user1@test.com", role_level=1)
        ]
        mock_services['org'].get_all_departments.return_value = []

        mock_services['drive'].service.files.return_value.list.return_value.execute.return_value = {
            'files': [
                {'id': 'folder1', 'name': '全社共有'}
            ]
        }

        mock_services['perm'].sync_folder_permissions.return_value = PermissionSyncResult(
            folder_id="folder1",
            permissions_added=1,
            permissions_removed=0,
            permissions_updated=0,
            permissions_unchanged=0
        )

        report = await sync_service.sync_all_folders(dry_run=True)

        assert report.dry_run is True
        assert report.completed_at is not None

    def test_clear_caches(self, sync_service, mock_services):
        """キャッシュクリア"""
        sync_service._employees_cache = [Employee(id="emp1", name="Test", role_level=1)]
        sync_service._departments_cache = [Department(id="dept1", name="Test")]

        sync_service.clear_caches()

        assert sync_service._employees_cache is None
        assert sync_service._departments_cache is None
        assert sync_service._dept_name_to_id == {}


# ================================================================
# Integration Tests
# ================================================================

class TestPermissionCalculation:
    """権限計算の統合テスト"""

    def test_role_level_mapping(self):
        """役職レベルと権限のマッピング"""
        from lib.drive_permission_manager import ROLE_LEVEL_TO_PERMISSION

        # レベル1-2: reader
        assert ROLE_LEVEL_TO_PERMISSION[1] == PermissionRole.READER
        assert ROLE_LEVEL_TO_PERMISSION[2] == PermissionRole.READER

        # レベル3: commenter
        assert ROLE_LEVEL_TO_PERMISSION[3] == PermissionRole.COMMENTER

        # レベル4-6: writer
        assert ROLE_LEVEL_TO_PERMISSION[4] == PermissionRole.WRITER
        assert ROLE_LEVEL_TO_PERMISSION[5] == PermissionRole.WRITER
        assert ROLE_LEVEL_TO_PERMISSION[6] == PermissionRole.WRITER

    def test_department_employee_all_department_ids(self):
        """兼務社員の全部署ID取得"""
        emp = Employee(
            id="emp1",
            name="兼務社員",
            department_id="dept_main",
            additional_departments=[
                {"department_id": "dept_sub1"},
                {"department_id": "dept_sub2"}
            ],
            role_level=1
        )

        all_ids = emp.all_department_ids
        assert "dept_main" in all_ids
        assert "dept_sub1" in all_ids
        assert "dept_sub2" in all_ids
        assert len(all_ids) == 3
