"""
OrganizationSyncService 単体テスト

Phase 3.5: 組織図同期サービスのテスト

テストケース構成:
- _validate_org_chart_data: バリデーション（8件）
- _topological_sort: トポロジカルソート（6件）
- _has_cycle: 循環参照検出（4件）
- _find_orphan_departments: 孤立部署検出（4件）
- _sync_roles: 役職同期（4件）
- sync_org_chart: メイン同期処理（6件）
- error handling: エラーハンドリング（4件）

合計: 36テストケース
"""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

# api ディレクトリをパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'api'))

# 直接モジュールをインポート
from app.services.organization_sync import (
    OrganizationSyncService,
    OrganizationSyncError,
)
from app.schemas.organization import (
    OrgChartSyncRequest,
    DepartmentInput,
    RoleInput,
    EmployeeInput,
    SyncOptions,
)


# ================================================================
# テスト用フィクスチャ
# ================================================================

@pytest.fixture
def mock_conn():
    """DBコネクションのモック"""
    conn = MagicMock()
    # executeの戻り値をモック
    mock_result = MagicMock()
    mock_result.fetchone.return_value = ("test-sync-id",)
    mock_result.rowcount = 0
    conn.execute.return_value = mock_result
    return conn


@pytest.fixture
def sample_organization_id():
    """テスト用組織ID"""
    return "org_test_001"


@pytest.fixture
def sample_departments():
    """テスト用部署データ（正常階層）"""
    return [
        DepartmentInput(
            id="dept_hq",
            name="本社",
            code="HQ",
            parentId=None,
            level=1,
            displayOrder=0,
            isActive=True,
        ),
        DepartmentInput(
            id="dept_sales",
            name="営業部",
            code="SALES",
            parentId="dept_hq",
            level=2,
            displayOrder=1,
            isActive=True,
        ),
        DepartmentInput(
            id="dept_sales_tokyo",
            name="東京営業課",
            code="SALES_TOKYO",
            parentId="dept_sales",
            level=3,
            displayOrder=0,
            isActive=True,
        ),
    ]


@pytest.fixture
def sample_roles():
    """テスト用役職データ"""
    return [
        RoleInput(id="role_ceo", name="代表取締役", level=6, description="CEO"),
        RoleInput(id="role_director", name="部長", level=4, description="部門責任者"),
        RoleInput(id="role_employee", name="社員", level=2, description="一般社員"),
    ]


@pytest.fixture
def sample_employees():
    """テスト用社員データ"""
    return [
        EmployeeInput(
            id="emp_001",
            name="田中太郎",
            email="tanaka@example.com",
            departmentId="dept_sales",
            roleId="role_director",
            isPrimary=True,
        ),
    ]


@pytest.fixture
def sample_sync_request(sample_departments, sample_roles, sample_employees):
    """テスト用同期リクエスト"""
    return OrgChartSyncRequest(
        organization_id="org_test_001",
        source="org_chart_system",
        sync_type="full",
        departments=sample_departments,
        roles=sample_roles,
        employees=sample_employees,
        options=SyncOptions(dry_run=False),
    )


# ================================================================
# _validate_org_chart_data テスト（8件）
# ================================================================

class TestValidateOrgChartData:
    """バリデーションのテスト"""

    def test_valid_data_passes(self, mock_conn, sample_sync_request):
        """正常なデータはバリデーションを通過"""
        service = OrganizationSyncService(mock_conn)

        # エラーが発生しないことを確認
        service._validate_org_chart_data(sample_sync_request)

    def test_circular_reference_detected(self, mock_conn):
        """循環参照が検出される"""
        # A → B → C → A の循環
        departments = [
            DepartmentInput(id="A", name="A", parentId="C", level=1),
            DepartmentInput(id="B", name="B", parentId="A", level=2),
            DepartmentInput(id="C", name="C", parentId="B", level=3),
        ]
        request = OrgChartSyncRequest(
            organization_id="org_test",
            source="test",
            sync_type="full",
            departments=departments,
        )

        service = OrganizationSyncService(mock_conn)

        with pytest.raises(OrganizationSyncError) as exc_info:
            service._validate_org_chart_data(request)

        assert exc_info.value.error_code == "CIRCULAR_REFERENCE"

    def test_orphan_department_detected(self, mock_conn):
        """孤立部署が検出される"""
        departments = [
            DepartmentInput(id="dept_hq", name="本社", parentId=None, level=1),
            DepartmentInput(
                id="dept_orphan",
                name="孤立部署",
                parentId="dept_nonexistent",  # 存在しない親
                level=2,
            ),
        ]
        request = OrgChartSyncRequest(
            organization_id="org_test",
            source="test",
            sync_type="full",
            departments=departments,
        )

        service = OrganizationSyncService(mock_conn)

        with pytest.raises(OrganizationSyncError) as exc_info:
            service._validate_org_chart_data(request)

        assert exc_info.value.error_code == "ORPHAN_DEPARTMENT"
        assert "dept_orphan" in str(exc_info.value.details)

    def test_duplicate_code_detected(self, mock_conn):
        """部署コード重複が検出される"""
        departments = [
            DepartmentInput(id="dept_1", name="部署1", code="SAME_CODE", parentId=None, level=1),
            DepartmentInput(id="dept_2", name="部署2", code="SAME_CODE", parentId=None, level=1),
        ]
        request = OrgChartSyncRequest(
            organization_id="org_test",
            source="test",
            sync_type="full",
            departments=departments,
        )

        service = OrganizationSyncService(mock_conn)

        with pytest.raises(OrganizationSyncError) as exc_info:
            service._validate_org_chart_data(request)

        assert exc_info.value.error_code == "DUPLICATE_CODE"

    def test_too_many_departments_rejected(self, mock_conn):
        """部署数上限超過が検出される"""
        # 1001個の部署を作成
        departments = [
            DepartmentInput(id=f"dept_{i}", name=f"部署{i}", parentId=None, level=1)
            for i in range(1001)
        ]
        request = OrgChartSyncRequest(
            organization_id="org_test",
            source="test",
            sync_type="full",
            departments=departments,
        )

        service = OrganizationSyncService(mock_conn)

        with pytest.raises(OrganizationSyncError) as exc_info:
            service._validate_org_chart_data(request)

        assert exc_info.value.error_code == "TOO_MANY_DEPARTMENTS"

    def test_empty_departments_allowed(self, mock_conn):
        """空の部署リストは許可される"""
        request = OrgChartSyncRequest(
            organization_id="org_test",
            source="test",
            sync_type="full",
            departments=[],
        )

        service = OrganizationSyncService(mock_conn)

        # エラーが発生しないことを確認
        service._validate_org_chart_data(request)

    def test_self_reference_detected(self, mock_conn):
        """自己参照が検出される"""
        departments = [
            DepartmentInput(id="dept_self", name="自己参照", parentId="dept_self", level=1),
        ]
        request = OrgChartSyncRequest(
            organization_id="org_test",
            source="test",
            sync_type="full",
            departments=departments,
        )

        service = OrganizationSyncService(mock_conn)

        with pytest.raises(OrganizationSyncError) as exc_info:
            service._validate_org_chart_data(request)

        # 自己参照は循環参照として検出される（親は自分自身なので存在する＝孤立ではない）
        assert exc_info.value.error_code == "CIRCULAR_REFERENCE"

    def test_multiple_validation_errors(self, mock_conn):
        """複数のエラーがある場合、最初のエラーで停止"""
        # 循環参照 + 重複コード
        departments = [
            DepartmentInput(id="A", name="A", code="CODE", parentId="B", level=1),
            DepartmentInput(id="B", name="B", code="CODE", parentId="A", level=2),
        ]
        request = OrgChartSyncRequest(
            organization_id="org_test",
            source="test",
            sync_type="full",
            departments=departments,
        )

        service = OrganizationSyncService(mock_conn)

        with pytest.raises(OrganizationSyncError) as exc_info:
            service._validate_org_chart_data(request)

        # 循環参照が先に検出される
        assert exc_info.value.error_code == "CIRCULAR_REFERENCE"


# ================================================================
# _topological_sort テスト（6件）
# ================================================================

class TestTopologicalSort:
    """トポロジカルソートのテスト"""

    def test_sorts_in_parent_child_order(self, mock_conn, sample_departments):
        """親→子の順でソートされる"""
        service = OrganizationSyncService(mock_conn)

        # 逆順で入力
        reversed_depts = list(reversed(sample_departments))
        sorted_depts = service._topological_sort(reversed_depts)

        # 親が先に来ることを確認
        ids = [d.id for d in sorted_depts]
        assert ids.index("dept_hq") < ids.index("dept_sales")
        assert ids.index("dept_sales") < ids.index("dept_sales_tokyo")

    def test_handles_single_department(self, mock_conn):
        """単一部署を処理できる"""
        departments = [
            DepartmentInput(id="dept_only", name="唯一の部署", parentId=None, level=1),
        ]

        service = OrganizationSyncService(mock_conn)
        sorted_depts = service._topological_sort(departments)

        assert len(sorted_depts) == 1
        assert sorted_depts[0].id == "dept_only"

    def test_handles_flat_structure(self, mock_conn):
        """フラットな構造（全て同レベル）を処理できる"""
        departments = [
            DepartmentInput(id="dept_1", name="部署1", parentId=None, level=1),
            DepartmentInput(id="dept_2", name="部署2", parentId=None, level=1),
            DepartmentInput(id="dept_3", name="部署3", parentId=None, level=1),
        ]

        service = OrganizationSyncService(mock_conn)
        sorted_depts = service._topological_sort(departments)

        assert len(sorted_depts) == 3

    def test_handles_deep_hierarchy(self, mock_conn):
        """深い階層（5レベル）を処理できる"""
        departments = [
            DepartmentInput(id="level_1", name="L1", parentId=None, level=1),
            DepartmentInput(id="level_2", name="L2", parentId="level_1", level=2),
            DepartmentInput(id="level_3", name="L3", parentId="level_2", level=3),
            DepartmentInput(id="level_4", name="L4", parentId="level_3", level=4),
            DepartmentInput(id="level_5", name="L5", parentId="level_4", level=5),
        ]

        service = OrganizationSyncService(mock_conn)
        sorted_depts = service._topological_sort(departments)

        ids = [d.id for d in sorted_depts]
        assert ids == ["level_1", "level_2", "level_3", "level_4", "level_5"]

    def test_raises_on_cycle(self, mock_conn):
        """循環参照でエラーを発生"""
        departments = [
            DepartmentInput(id="A", name="A", parentId="B", level=1),
            DepartmentInput(id="B", name="B", parentId="A", level=1),
        ]

        service = OrganizationSyncService(mock_conn)

        with pytest.raises(OrganizationSyncError) as exc_info:
            service._topological_sort(departments)

        assert exc_info.value.error_code == "CIRCULAR_REFERENCE"

    def test_handles_multiple_roots(self, mock_conn):
        """複数のルート部署を処理できる"""
        departments = [
            DepartmentInput(id="root_1", name="Root1", parentId=None, level=1),
            DepartmentInput(id="root_2", name="Root2", parentId=None, level=1),
            DepartmentInput(id="child_1", name="Child1", parentId="root_1", level=2),
            DepartmentInput(id="child_2", name="Child2", parentId="root_2", level=2),
        ]

        service = OrganizationSyncService(mock_conn)
        sorted_depts = service._topological_sort(departments)

        ids = [d.id for d in sorted_depts]
        # 両方のルートが子より前に来る
        assert ids.index("root_1") < ids.index("child_1")
        assert ids.index("root_2") < ids.index("child_2")


# ================================================================
# _has_cycle テスト（4件）
# ================================================================

class TestHasCycle:
    """循環参照検出のテスト"""

    def test_no_cycle_returns_false(self, mock_conn, sample_departments):
        """循環がない場合はFalse"""
        service = OrganizationSyncService(mock_conn)

        result = service._has_cycle(sample_departments)

        assert result is False

    def test_direct_cycle_returns_true(self, mock_conn):
        """直接循環（A→B→A）を検出"""
        departments = [
            DepartmentInput(id="A", name="A", parentId="B", level=1),
            DepartmentInput(id="B", name="B", parentId="A", level=2),
        ]

        service = OrganizationSyncService(mock_conn)

        result = service._has_cycle(departments)

        assert result is True

    def test_indirect_cycle_returns_true(self, mock_conn):
        """間接循環（A→B→C→A）を検出"""
        departments = [
            DepartmentInput(id="A", name="A", parentId="C", level=1),
            DepartmentInput(id="B", name="B", parentId="A", level=2),
            DepartmentInput(id="C", name="C", parentId="B", level=3),
        ]

        service = OrganizationSyncService(mock_conn)

        result = service._has_cycle(departments)

        assert result is True

    def test_empty_list_returns_false(self, mock_conn):
        """空リストは循環なし"""
        service = OrganizationSyncService(mock_conn)

        result = service._has_cycle([])

        assert result is False


# ================================================================
# _find_orphan_departments テスト（4件）
# ================================================================

class TestFindOrphanDepartments:
    """孤立部署検出のテスト"""

    def test_no_orphans_returns_empty(self, mock_conn, sample_departments):
        """孤立がない場合は空リスト"""
        service = OrganizationSyncService(mock_conn)

        result = service._find_orphan_departments(sample_departments)

        assert result == []

    def test_detects_orphan(self, mock_conn):
        """孤立部署を検出"""
        departments = [
            DepartmentInput(id="dept_hq", name="本社", parentId=None, level=1),
            DepartmentInput(id="dept_orphan", name="孤立", parentId="nonexistent", level=2),
        ]

        service = OrganizationSyncService(mock_conn)

        result = service._find_orphan_departments(departments)

        assert "dept_orphan" in result

    def test_detects_multiple_orphans(self, mock_conn):
        """複数の孤立部署を検出"""
        departments = [
            DepartmentInput(id="dept_hq", name="本社", parentId=None, level=1),
            DepartmentInput(id="orphan_1", name="孤立1", parentId="ghost_1", level=2),
            DepartmentInput(id="orphan_2", name="孤立2", parentId="ghost_2", level=2),
        ]

        service = OrganizationSyncService(mock_conn)

        result = service._find_orphan_departments(departments)

        assert len(result) == 2
        assert "orphan_1" in result
        assert "orphan_2" in result

    def test_root_is_not_orphan(self, mock_conn):
        """ルート部署（parentId=None）は孤立ではない"""
        departments = [
            DepartmentInput(id="root", name="Root", parentId=None, level=1),
        ]

        service = OrganizationSyncService(mock_conn)

        result = service._find_orphan_departments(departments)

        assert result == []


# ================================================================
# _sync_roles テスト（4件）
# ================================================================

class TestSyncRoles:
    """役職同期のテスト"""

    def test_inserts_new_role(self, mock_conn, sample_roles, sample_organization_id):
        """新規役職を挿入"""
        # 既存なし（fetchone=None）
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result

        service = OrganizationSyncService(mock_conn)
        count = service._sync_roles(sample_organization_id, sample_roles)

        assert count == 3
        # INSERTが呼ばれたことを確認（SELECTの後）
        assert mock_conn.execute.call_count >= 3

    def test_updates_existing_role(self, mock_conn, sample_organization_id):
        """既存役職を更新"""
        roles = [RoleInput(id="role_ceo", name="CEO", level=6)]

        # 既存あり
        mock_result = MagicMock()
        mock_result.fetchone.return_value = ("existing-uuid",)
        mock_conn.execute.return_value = mock_result

        service = OrganizationSyncService(mock_conn)
        count = service._sync_roles(sample_organization_id, roles)

        assert count == 1

    def test_handles_empty_roles(self, mock_conn, sample_organization_id):
        """空の役職リストを処理"""
        service = OrganizationSyncService(mock_conn)
        count = service._sync_roles(sample_organization_id, [])

        assert count == 0

    def test_uses_external_id(self, mock_conn, sample_organization_id):
        """external_idを使って識別"""
        roles = [RoleInput(id="role_test", name="Test", level=2)]

        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result

        service = OrganizationSyncService(mock_conn)
        service._sync_roles(sample_organization_id, roles)

        # external_idがSQLで使われていることを確認
        calls = mock_conn.execute.call_args_list
        assert any("external_id" in str(call) for call in calls)


# ================================================================
# sync_org_chart テスト（6件）
# ================================================================

class TestSyncOrgChart:
    """メイン同期処理のテスト"""

    def test_dry_run_does_not_modify(self, mock_conn, sample_sync_request, sample_organization_id):
        """ドライランは変更を行わない"""
        sample_sync_request.options.dry_run = True

        service = OrganizationSyncService(mock_conn)

        with patch.object(service, '_validate_org_chart_data'):
            with patch.object(service, '_execute_sync') as mock_execute:
                result = service.sync_org_chart(sample_organization_id, sample_sync_request)

                # _execute_syncは呼ばれない
                mock_execute.assert_not_called()

        assert result.status == "success"

    def test_returns_success_response(self, mock_conn, sample_sync_request, sample_organization_id):
        """成功時に正しいレスポンスを返す"""
        service = OrganizationSyncService(mock_conn)

        with patch.object(service, '_validate_org_chart_data'):
            with patch.object(service, '_execute_sync') as mock_execute:
                from app.schemas.organization import SyncSummary
                mock_execute.return_value = SyncSummary(
                    departments_added=3,
                    roles_added=2,
                    users_added=1,
                )
                result = service.sync_org_chart(sample_organization_id, sample_sync_request)

        assert result.status == "success"
        assert result.summary.departments_added == 3
        assert result.summary.roles_added == 2
        assert result.summary.users_added == 1

    def test_logs_sync_start_and_end(self, mock_conn, sample_sync_request, sample_organization_id):
        """同期開始と終了がログされる"""
        from app.schemas.organization import SyncSummary

        service = OrganizationSyncService(mock_conn)

        with patch.object(service, '_create_sync_log', return_value="sync-123") as mock_create:
            with patch.object(service, '_update_sync_log') as mock_update:
                with patch.object(service, '_execute_sync', return_value=SyncSummary()):
                    service.sync_org_chart(sample_organization_id, sample_sync_request)

        mock_create.assert_called_once()
        mock_update.assert_called_once()

    def test_handles_validation_error(self, mock_conn, sample_organization_id):
        """バリデーションエラーを処理"""
        # 循環参照のあるリクエスト
        departments = [
            DepartmentInput(id="A", name="A", parentId="B", level=1),
            DepartmentInput(id="B", name="B", parentId="A", level=2),
        ]
        request = OrgChartSyncRequest(
            organization_id=sample_organization_id,
            source="test",
            sync_type="full",
            departments=departments,
        )

        service = OrganizationSyncService(mock_conn)

        with pytest.raises(OrganizationSyncError) as exc_info:
            service.sync_org_chart(sample_organization_id, request)

        assert exc_info.value.error_code == "CIRCULAR_REFERENCE"

    def test_includes_duration_in_response(self, mock_conn, sample_sync_request, sample_organization_id):
        """レスポンスに処理時間が含まれる"""
        from app.schemas.organization import SyncSummary

        service = OrganizationSyncService(mock_conn)

        with patch.object(service, '_validate_org_chart_data'):
            with patch.object(service, '_execute_sync', return_value=SyncSummary()):
                result = service.sync_org_chart(sample_organization_id, sample_sync_request)

        assert result.duration_ms is not None
        assert result.duration_ms >= 0

    def test_includes_synced_at_in_response(self, mock_conn, sample_sync_request, sample_organization_id):
        """レスポンスに同期時刻が含まれる"""
        from app.schemas.organization import SyncSummary

        service = OrganizationSyncService(mock_conn)

        with patch.object(service, '_validate_org_chart_data'):
            with patch.object(service, '_execute_sync', return_value=SyncSummary()):
                result = service.sync_org_chart(sample_organization_id, sample_sync_request)

        assert result.synced_at is not None


# ================================================================
# エラーハンドリングテスト（4件）
# ================================================================

class TestErrorHandling:
    """エラーハンドリングのテスト"""

    def test_sync_error_updates_log(self, mock_conn, sample_organization_id):
        """同期エラー時にログが更新される"""
        # 循環参照エラー
        departments = [
            DepartmentInput(id="A", name="A", parentId="B", level=1),
            DepartmentInput(id="B", name="B", parentId="A", level=2),
        ]
        request = OrgChartSyncRequest(
            organization_id=sample_organization_id,
            source="test",
            sync_type="full",
            departments=departments,
        )

        service = OrganizationSyncService(mock_conn)

        with patch.object(service, '_update_sync_log') as mock_update:
            with pytest.raises(OrganizationSyncError):
                service.sync_org_chart(sample_organization_id, request)

            # 失敗ステータスでログ更新
            mock_update.assert_called()
            call_args = mock_update.call_args
            assert call_args[1]["status"] == "failed"

    def test_unexpected_error_updates_log(self, mock_conn, sample_sync_request, sample_organization_id):
        """予期しないエラー時にログが更新される"""
        service = OrganizationSyncService(mock_conn)

        with patch.object(service, '_validate_org_chart_data', side_effect=RuntimeError("Unexpected")):
            with patch.object(service, '_update_sync_log') as mock_update:
                with pytest.raises(RuntimeError):
                    service.sync_org_chart(sample_organization_id, sample_sync_request)

                # 失敗ステータスでログ更新
                mock_update.assert_called()

    def test_error_includes_error_code(self, mock_conn, sample_organization_id):
        """エラーにエラーコードが含まれる"""
        departments = [
            DepartmentInput(id="orphan", name="孤立", parentId="nonexistent", level=2),
        ]
        request = OrgChartSyncRequest(
            organization_id=sample_organization_id,
            source="test",
            sync_type="full",
            departments=departments,
        )

        service = OrganizationSyncService(mock_conn)

        with pytest.raises(OrganizationSyncError) as exc_info:
            service.sync_org_chart(sample_organization_id, request)

        assert exc_info.value.error_code is not None
        assert exc_info.value.message is not None

    def test_error_includes_details(self, mock_conn, sample_organization_id):
        """エラーに詳細情報が含まれる"""
        departments = [
            DepartmentInput(id="dept_1", name="部署1", code="DUPLICATE", parentId=None, level=1),
            DepartmentInput(id="dept_2", name="部署2", code="DUPLICATE", parentId=None, level=1),
        ]
        request = OrgChartSyncRequest(
            organization_id=sample_organization_id,
            source="test",
            sync_type="full",
            departments=departments,
        )

        service = OrganizationSyncService(mock_conn)

        with pytest.raises(OrganizationSyncError) as exc_info:
            service.sync_org_chart(sample_organization_id, request)

        assert exc_info.value.details is not None
        assert "duplicate_codes" in exc_info.value.details
