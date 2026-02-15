"""
Org Chart Service テスト

Phase B: Google Drive 自動権限管理機能
"""

import os
import pytest
from unittest.mock import Mock, AsyncMock, patch

from lib.org_chart_service import (
    OrgChartService,
    Employee,
    Department,
    Role,
    ROLE_LEVELS,
    DEFAULT_ORGANIZATION_ID,
)


# ================================================================
# Fixtures
# ================================================================

@pytest.fixture
def org_chart_service():
    """テスト用OrgChartService"""
    return OrgChartService(
        supabase_url="https://test.supabase.co",
        supabase_key="test-key",
        organization_id="org_test"
    )


# ================================================================
# Constants Tests
# ================================================================

class TestConstants:
    """定数テスト"""

    def test_role_levels(self):
        """役職レベル定義"""
        assert ROLE_LEVELS[1] == "一般スタッフ"
        assert ROLE_LEVELS[6] == "役員"
        assert len(ROLE_LEVELS) == 6

    def test_default_organization_id(self):
        """デフォルト組織ID"""
        assert DEFAULT_ORGANIZATION_ID == "5f98365f-e7c5-4f48-9918-7fe9aabae5df"


# ================================================================
# Employee Tests
# ================================================================

class TestEmployee:
    """Employeeデータクラスのテスト"""

    def test_has_google_account_true(self):
        """Googleアカウントあり"""
        emp = Employee(
            id="emp1",
            name="Test User",
            google_account_email="test@company.com"
        )
        assert emp.has_google_account is True

    def test_has_google_account_false(self):
        """Googleアカウントなし"""
        emp = Employee(
            id="emp1",
            name="Test User",
            google_account_email=None
        )
        assert emp.has_google_account is False

    def test_all_department_ids_single(self):
        """単一部署"""
        emp = Employee(
            id="emp1",
            name="Test User",
            department_id="dept1"
        )
        assert emp.all_department_ids == ["dept1"]

    def test_all_department_ids_with_additional(self):
        """兼務部署あり"""
        emp = Employee(
            id="emp1",
            name="Test User",
            department_id="dept1",
            additional_departments=[
                {"department_id": "dept2"},
                {"department_id": "dept3"}
            ]
        )
        assert set(emp.all_department_ids) == {"dept1", "dept2", "dept3"}


# ================================================================
# Department Tests
# ================================================================

class TestDepartment:
    """Departmentデータクラスのテスト"""

    def test_is_top_level_true(self):
        """トップレベル部署"""
        dept = Department(
            id="dept1",
            name="経営企画部",
            parent_id=None
        )
        assert dept.is_top_level is True

    def test_is_top_level_false(self):
        """子部署"""
        dept = Department(
            id="dept2",
            name="営業1課",
            parent_id="dept1"
        )
        assert dept.is_top_level is False


# ================================================================
# OrgChartService Initialization Tests
# ================================================================

class TestOrgChartServiceInit:
    """初期化テスト"""

    def test_init_with_params(self):
        """パラメータで初期化"""
        service = OrgChartService(
            supabase_url="https://test.supabase.co",
            supabase_key="test-key"
        )
        assert service.supabase_url == "https://test.supabase.co"
        assert service.supabase_key == "test-key"

    def test_init_missing_url_raises(self):
        """URLなしでエラー"""
        with pytest.raises(ValueError):
            OrgChartService(supabase_url=None, supabase_key="test-key")

    @patch("lib.org_chart_service.get_secret_cached", side_effect=Exception("Not available"))
    @patch.dict("os.environ", {"SUPABASE_ANON_KEY": ""}, clear=False)
    def test_init_missing_key_raises(self, mock_secret):
        """キーなしでエラー（Secret Manager・環境変数どちらも利用不可時）"""
        with pytest.raises(ValueError):
            OrgChartService(supabase_url="https://test.supabase.co", supabase_key=None)


# ================================================================
# OrgChartService API Tests
# ================================================================

class TestOrgChartServiceAPI:
    """API呼び出しテスト"""

    @pytest.mark.asyncio
    async def test_get_all_employees(self, org_chart_service):
        """全社員取得"""
        mock_response = Mock()
        mock_response.json.return_value = [
            {
                'id': 'emp1',
                'name': 'User One',
                'department_id': 'dept1',
                'role_id': 'role1',
                'google_account_email': 'user1@company.com',
                'is_active': True,
                'departments': {'name': 'Sales'},
                'roles': {'name': 'Staff', 'level': 1}
            },
            {
                'id': 'emp2',
                'name': 'User Two',
                'department_id': 'dept2',
                'google_account_email': None,
                'is_active': True,
                'departments': {'name': 'Dev'},
                'roles': {'name': 'Lead', 'level': 3}
            }
        ]
        mock_response.raise_for_status = Mock()

        with patch.object(org_chart_service, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_get_client.return_value = mock_client

            employees = await org_chart_service.get_all_employees()

            assert len(employees) == 2
            assert employees[0].name == 'User One'
            assert employees[0].google_account_email == 'user1@company.com'
            assert employees[1].role_level == 3

    @pytest.mark.asyncio
    async def test_get_all_employees_with_google_only(self, org_chart_service):
        """Googleアカウント設定済みのみ"""
        mock_response = Mock()
        mock_response.json.return_value = [
            {
                'id': 'emp1',
                'name': 'User One',
                'google_account_email': 'user1@company.com',
                'is_active': True,
                'departments': {},
                'roles': {'level': 1}
            }
        ]
        mock_response.raise_for_status = Mock()

        with patch.object(org_chart_service, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_get_client.return_value = mock_client

            employees = await org_chart_service.get_all_employees(
                with_google_account_only=True
            )

            # パラメータにフィルタが含まれていることを確認
            call_args = mock_client.get.call_args
            assert 'google_account_email' in call_args[1]['params']

    @pytest.mark.asyncio
    async def test_get_all_departments(self, org_chart_service):
        """全部署取得"""
        mock_response = Mock()
        mock_response.json.return_value = [
            {'id': 'dept1', 'name': '営業部', 'parent_id': None},
            {'id': 'dept2', 'name': '営業1課', 'parent_id': 'dept1'},
        ]
        mock_response.raise_for_status = Mock()

        with patch.object(org_chart_service, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_get_client.return_value = mock_client

            departments = await org_chart_service.get_all_departments()

            assert len(departments) == 2
            assert departments[0].name == '営業部'
            assert departments[0].is_top_level is True
            assert departments[1].parent_id == 'dept1'

    @pytest.mark.asyncio
    async def test_get_all_google_accounts(self, org_chart_service):
        """Googleアカウントマップ取得"""
        mock_response = Mock()
        mock_response.json.return_value = [
            {
                'id': 'emp1',
                'name': 'User One',
                'google_account_email': 'User1@Company.com',
                'is_active': True,
                'departments': {},
                'roles': {'level': 1}
            },
            {
                'id': 'emp2',
                'name': 'User Two',
                'google_account_email': 'user2@company.com',
                'is_active': True,
                'departments': {},
                'roles': {'level': 2}
            }
        ]
        mock_response.raise_for_status = Mock()

        with patch.object(org_chart_service, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_get_client.return_value = mock_client

            accounts = await org_chart_service.get_all_google_accounts()

            # キーは小文字に正規化
            assert 'user1@company.com' in accounts
            assert 'user2@company.com' in accounts
            assert accounts['user1@company.com'].name == 'User One'


# ================================================================
# Helper Method Tests
# ================================================================

class TestHelperMethods:
    """ヘルパーメソッドのテスト"""

    def test_parse_employee_full(self, org_chart_service):
        """完全な社員データのパース"""
        data = {
            'id': 'emp1',
            'name': 'Test User',
            'department_id': 'dept1',
            'role_id': 'role1',
            'google_account_email': 'test@company.com',
            'chatwork_account_id': '12345',
            'email_work': 'test@work.com',
            'is_active': True,
            'departments': {'name': 'Sales Dept'},
            'roles': {'name': 'Manager', 'level': 4}
        }

        emp = org_chart_service._parse_employee(data)

        assert emp.id == 'emp1'
        assert emp.name == 'Test User'
        assert emp.department_name == 'Sales Dept'
        assert emp.role_name == 'Manager'
        assert emp.role_level == 4
        assert emp.google_account_email == 'test@company.com'

    def test_parse_employee_minimal(self, org_chart_service):
        """最小限の社員データのパース"""
        data = {
            'id': 'emp1',
            'name': 'Test User',
            'departments': None,
            'roles': None
        }

        emp = org_chart_service._parse_employee(data)

        assert emp.id == 'emp1'
        assert emp.name == 'Test User'
        assert emp.department_id is None
        assert emp.role_level == 1  # デフォルト

    def test_get_child_department_ids(self, org_chart_service):
        """子部署ID取得"""
        departments = [
            Department(id='parent', name='親部署', parent_id=None),
            Department(id='child1', name='子部署1', parent_id='parent'),
            Department(id='child2', name='子部署2', parent_id='parent'),
            Department(id='grandchild', name='孫部署', parent_id='child1'),
            Department(id='other', name='他部署', parent_id=None),
        ]

        child_ids = org_chart_service._get_child_department_ids(
            departments, 'parent'
        )

        assert child_ids == {'child1', 'child2', 'grandchild'}
        assert 'other' not in child_ids

    def test_get_child_department_ids_no_children(self, org_chart_service):
        """子部署なし"""
        departments = [
            Department(id='leaf', name='末端部署', parent_id='parent'),
        ]

        child_ids = org_chart_service._get_child_department_ids(
            departments, 'leaf'
        )

        assert child_ids == set()


# ================================================================
# Role Level Filter Tests
# ================================================================

class TestRoleLevelFilter:
    """役職レベルフィルタのテスト"""

    @pytest.mark.asyncio
    async def test_get_employees_by_role_level(self, org_chart_service):
        """役職レベルでフィルタ"""
        mock_response = Mock()
        mock_response.json.return_value = [
            {'id': 'emp1', 'name': 'Staff', 'departments': {}, 'roles': {'level': 1}},
            {'id': 'emp2', 'name': 'Lead', 'departments': {}, 'roles': {'level': 3}},
            {'id': 'emp3', 'name': 'Manager', 'departments': {}, 'roles': {'level': 4}},
            {'id': 'emp4', 'name': 'Director', 'departments': {}, 'roles': {'level': 5}},
        ]
        mock_response.raise_for_status = Mock()

        with patch.object(org_chart_service, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_get_client.return_value = mock_client

            # レベル3以上
            employees = await org_chart_service.get_employees_by_role_level(
                min_level=3
            )

            assert len(employees) == 3
            assert all(e.role_level >= 3 for e in employees)

    @pytest.mark.asyncio
    async def test_get_accounts_by_role_level(self, org_chart_service):
        """役職レベル以上のGoogleアカウント取得"""
        mock_response = Mock()
        mock_response.json.return_value = [
            {'id': 'emp1', 'name': 'Staff', 'google_account_email': 'staff@c.com', 'departments': {}, 'roles': {'level': 1}},
            {'id': 'emp2', 'name': 'Manager', 'google_account_email': 'manager@c.com', 'departments': {}, 'roles': {'level': 4}},
        ]
        mock_response.raise_for_status = Mock()

        with patch.object(org_chart_service, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_get_client.return_value = mock_client

            accounts = await org_chart_service.get_accounts_by_role_level(min_level=4)

            assert len(accounts) == 1
            assert accounts[0] == 'manager@c.com'


# ================================================================
# Additional Tests for Coverage Improvement
# ================================================================


class TestEmployeeAdditional:
    """Employee データクラスの追加テスト"""

    def test_has_google_account_empty_string(self):
        """Googleアカウントが空文字の場合"""
        emp = Employee(
            id="emp1",
            name="Test User",
            google_account_email=""
        )
        assert emp.has_google_account is False

    def test_all_department_ids_no_department(self):
        """部署なしの場合"""
        emp = Employee(id="emp1", name="Test User")
        assert emp.all_department_ids == []

    def test_all_department_ids_additional_only(self):
        """兼務部署のみ（主部署なし）"""
        emp = Employee(
            id="emp1",
            name="Test User",
            department_id=None,
            additional_departments=[{"department_id": "dept2"}]
        )
        assert emp.all_department_ids == ["dept2"]

    def test_all_department_ids_additional_without_key(self):
        """兼務部署にdepartment_idがない場合"""
        emp = Employee(
            id="emp1",
            name="Test User",
            department_id="dept1",
            additional_departments=[
                {"department_id": "dept2"},
                {"other_field": "value"},  # department_idなし
            ]
        )
        assert emp.all_department_ids == ["dept1", "dept2"]

    def test_create_with_all_fields(self):
        """全フィールドで作成"""
        emp = Employee(
            id="emp1",
            name="田中太郎",
            department_id="dept1",
            department_name="営業部",
            role_id="role1",
            role_name="マネージャー",
            role_level=4,
            google_account_email="tanaka@example.com",
            chatwork_account_id="12345",
            email_work="tanaka@work.com",
            is_active=False,
            additional_departments=[{"department_id": "dept2"}]
        )
        assert emp.id == "emp1"
        assert emp.name == "田中太郎"
        assert emp.department_id == "dept1"
        assert emp.department_name == "営業部"
        assert emp.role_id == "role1"
        assert emp.role_name == "マネージャー"
        assert emp.role_level == 4
        assert emp.google_account_email == "tanaka@example.com"
        assert emp.chatwork_account_id == "12345"
        assert emp.email_work == "tanaka@work.com"
        assert emp.is_active is False


class TestDepartmentAdditional:
    """Department データクラスの追加テスト"""

    def test_create_with_all_fields(self):
        """全フィールドで作成"""
        dept = Department(
            id="dept1",
            name="営業部",
            parent_id="parent1",
            organization_id="org_custom",
            path="company.sales"
        )
        assert dept.id == "dept1"
        assert dept.name == "営業部"
        assert dept.parent_id == "parent1"
        assert dept.organization_id == "org_custom"
        assert dept.path == "company.sales"

    def test_default_organization_id(self):
        """デフォルト組織ID"""
        dept = Department(id="dept1", name="営業部")
        assert dept.organization_id == DEFAULT_ORGANIZATION_ID


class TestRoleAdditional:
    """Role データクラスの追加テスト"""

    def test_create_with_required_fields(self):
        """必須フィールドのみで作成"""
        role = Role(id="role1", name="マネージャー", level=4)
        assert role.id == "role1"
        assert role.name == "マネージャー"
        assert role.level == 4
        assert role.organization_id == DEFAULT_ORGANIZATION_ID

    def test_create_with_all_fields(self):
        """全フィールドで作成"""
        role = Role(
            id="role1",
            name="部長",
            level=5,
            organization_id="org_custom"
        )
        assert role.organization_id == "org_custom"


class TestOrgChartServiceClient:
    """クライアント管理のテスト"""

    @pytest.mark.asyncio
    async def test_get_client_creates_client(self):
        """クライアント生成"""
        service = OrgChartService(
            supabase_url="https://test.supabase.co",
            supabase_key="test-key"
        )
        assert service._client is None

        client = await service._get_client()
        assert client is not None
        assert service._client is client

        # 2回目は同じクライアントを返す
        client2 = await service._get_client()
        assert client2 is client

        await service.close()

    @pytest.mark.asyncio
    async def test_close_client(self):
        """クライアントを閉じる"""
        service = OrgChartService(
            supabase_url="https://test.supabase.co",
            supabase_key="test-key"
        )
        await service._get_client()
        assert service._client is not None

        await service.close()
        assert service._client is None

    @pytest.mark.asyncio
    async def test_close_when_no_client(self):
        """クライアントがない場合のclose"""
        service = OrgChartService(
            supabase_url="https://test.supabase.co",
            supabase_key="test-key"
        )
        # エラーが発生しないことを確認
        await service.close()
        assert service._client is None


class TestOrgChartServiceInitAdditional:
    """初期化の追加テスト"""

    @patch.dict("os.environ", {"SUPABASE_URL": "https://env.supabase.co", "SUPABASE_ANON_KEY": "env_key"})
    @patch("lib.org_chart_service.get_secret_cached", side_effect=Exception("Secret Manager unavailable"))
    @patch("lib.org_chart_service.logger")
    def test_init_from_environment(self, mock_logger, mock_secret):
        """環境変数からフォールバック初期化（Secret Manager不可時）"""
        service = OrgChartService()
        assert service.supabase_url == "https://env.supabase.co"
        assert service.supabase_key == "env_key"
        mock_logger.warning.assert_called_once()

    @patch("lib.org_chart_service.get_secret_cached", return_value="secret_manager_key")
    def test_init_from_secret_manager(self, mock_secret):
        """Secret Managerからキーを取得"""
        service = OrgChartService(supabase_url="https://test.supabase.co")
        assert service.supabase_key == "secret_manager_key"
        mock_secret.assert_called_once_with('SUPABASE_ANON_KEY')

    def test_init_with_custom_organization_id(self):
        """カスタム組織ID"""
        service = OrgChartService(
            supabase_url="https://test.supabase.co",
            supabase_key="test-key",
            organization_id="org_custom"
        )
        assert service.organization_id == "org_custom"

    def test_init_with_organization_filter(self):
        """組織フィルタ有効"""
        service = OrgChartService(
            supabase_url="https://test.supabase.co",
            supabase_key="test-key",
            skip_organization_filter=False
        )
        assert service.skip_organization_filter is False

    def test_rest_url_construction(self):
        """REST URL構築"""
        service = OrgChartService(
            supabase_url="https://test.supabase.co",
            supabase_key="test-key"
        )
        assert service.rest_url == "https://test.supabase.co/rest/v1"


class TestOrgChartServiceEmployeeById:
    """get_employee_by_id のテスト"""

    @pytest.mark.asyncio
    async def test_get_employee_by_id_found(self, org_chart_service):
        """社員が見つかる場合"""
        mock_response = Mock()
        mock_response.json.return_value = [
            {
                'id': 'emp1',
                'name': '田中太郎',
                'department_id': 'dept1',
                'is_active': True,
                'departments': {'name': '営業部'},
                'roles': {'name': 'マネージャー', 'level': 4}
            }
        ]
        mock_response.raise_for_status = Mock()

        with patch.object(org_chart_service, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_get_client.return_value = mock_client

            employee = await org_chart_service.get_employee_by_id('emp1')

            assert employee is not None
            assert employee.id == 'emp1'
            assert employee.name == '田中太郎'

    @pytest.mark.asyncio
    async def test_get_employee_by_id_not_found(self, org_chart_service):
        """社員が見つからない場合"""
        mock_response = Mock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = Mock()

        with patch.object(org_chart_service, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_get_client.return_value = mock_client

            employee = await org_chart_service.get_employee_by_id('nonexistent')

            assert employee is None

    @pytest.mark.asyncio
    async def test_get_employee_by_id_with_organization_filter(self):
        """組織フィルタ有効時のID検索"""
        service = OrgChartService(
            supabase_url="https://test.supabase.co",
            supabase_key="test-key",
            skip_organization_filter=False
        )

        mock_response = Mock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = Mock()

        with patch.object(service, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_get_client.return_value = mock_client

            await service.get_employee_by_id('emp1')

            call_args = mock_client.get.call_args
            params = call_args[1]['params']
            assert 'organization_id' in params


class TestOrgChartServiceDepartmentById:
    """get_department_by_id のテスト"""

    @pytest.mark.asyncio
    async def test_get_department_by_id_found(self, org_chart_service):
        """部署が見つかる場合"""
        mock_response = Mock()
        mock_response.json.return_value = [
            {'id': 'dept1', 'name': '営業部', 'parent_id': None, 'path': 'company.sales'}
        ]
        mock_response.raise_for_status = Mock()

        with patch.object(org_chart_service, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_get_client.return_value = mock_client

            department = await org_chart_service.get_department_by_id('dept1')

            assert department is not None
            assert department.id == 'dept1'
            assert department.name == '営業部'

    @pytest.mark.asyncio
    async def test_get_department_by_id_not_found(self, org_chart_service):
        """部署が見つからない場合"""
        mock_response = Mock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = Mock()

        with patch.object(org_chart_service, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_get_client.return_value = mock_client

            department = await org_chart_service.get_department_by_id('nonexistent')

            assert department is None

    @pytest.mark.asyncio
    async def test_get_department_by_id_with_organization_filter(self):
        """組織フィルタ有効時"""
        service = OrgChartService(
            supabase_url="https://test.supabase.co",
            supabase_key="test-key",
            skip_organization_filter=False
        )

        mock_response = Mock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = Mock()

        with patch.object(service, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_get_client.return_value = mock_client

            await service.get_department_by_id('dept1')

            call_args = mock_client.get.call_args
            params = call_args[1]['params']
            assert 'organization_id' in params


class TestOrgChartServiceDepartmentByName:
    """get_department_by_name のテスト"""

    @pytest.mark.asyncio
    async def test_get_department_by_name_found(self, org_chart_service):
        """部署が見つかる場合"""
        mock_response = Mock()
        mock_response.json.return_value = [
            {'id': 'dept1', 'name': '営業部', 'parent_id': None}
        ]
        mock_response.raise_for_status = Mock()

        with patch.object(org_chart_service, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_get_client.return_value = mock_client

            department = await org_chart_service.get_department_by_name('営業部')

            assert department is not None
            assert department.name == '営業部'

    @pytest.mark.asyncio
    async def test_get_department_by_name_not_found(self, org_chart_service):
        """部署が見つからない場合"""
        mock_response = Mock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = Mock()

        with patch.object(org_chart_service, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_get_client.return_value = mock_client

            department = await org_chart_service.get_department_by_name('存在しない部署')

            assert department is None

    @pytest.mark.asyncio
    async def test_get_department_by_name_with_organization_filter(self):
        """組織フィルタ有効時"""
        service = OrgChartService(
            supabase_url="https://test.supabase.co",
            supabase_key="test-key",
            skip_organization_filter=False
        )

        mock_response = Mock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = Mock()

        with patch.object(service, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_get_client.return_value = mock_client

            await service.get_department_by_name('営業部')

            call_args = mock_client.get.call_args
            params = call_args[1]['params']
            assert 'organization_id' in params


class TestOrgChartServiceRoles:
    """get_all_roles のテスト"""

    @pytest.mark.asyncio
    async def test_get_all_roles(self, org_chart_service):
        """全役職取得"""
        mock_response = Mock()
        mock_response.json.return_value = [
            {'id': 'role1', 'name': '一般スタッフ', 'level': 1},
            {'id': 'role2', 'name': 'マネージャー', 'level': 4},
            {'id': 'role3', 'name': '部長', 'level': 5},
        ]
        mock_response.raise_for_status = Mock()

        with patch.object(org_chart_service, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_get_client.return_value = mock_client

            roles = await org_chart_service.get_all_roles()

            assert len(roles) == 3
            assert roles[0].name == '一般スタッフ'
            assert roles[0].level == 1
            assert roles[1].level == 4

    @pytest.mark.asyncio
    async def test_get_all_roles_without_level(self, org_chart_service):
        """levelがない場合のデフォルト値"""
        mock_response = Mock()
        mock_response.json.return_value = [
            {'id': 'role1', 'name': '不明な役職'},  # levelなし
        ]
        mock_response.raise_for_status = Mock()

        with patch.object(org_chart_service, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_get_client.return_value = mock_client

            roles = await org_chart_service.get_all_roles()

            assert roles[0].level == 1  # デフォルト値

    @pytest.mark.asyncio
    async def test_get_all_roles_with_organization_filter(self):
        """組織フィルタ有効時"""
        service = OrgChartService(
            supabase_url="https://test.supabase.co",
            supabase_key="test-key",
            skip_organization_filter=False
        )

        mock_response = Mock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = Mock()

        with patch.object(service, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_get_client.return_value = mock_client

            await service.get_all_roles()

            call_args = mock_client.get.call_args
            params = call_args[1]['params']
            assert 'organization_id' in params


class TestOrgChartServiceEmployeesByDepartment:
    """get_employees_by_department のテスト"""

    @pytest.mark.asyncio
    async def test_get_employees_by_department(self, org_chart_service):
        """部署で社員取得"""
        mock_response = Mock()
        mock_response.json.return_value = [
            {
                'id': 'emp1',
                'name': '田中',
                'department_id': 'dept1',
                'is_active': True,
                'departments': {'name': '営業部'},
                'roles': {'level': 1}
            }
        ]
        mock_response.raise_for_status = Mock()

        with patch.object(org_chart_service, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_get_client.return_value = mock_client

            employees = await org_chart_service.get_employees_by_department('dept1')

            assert len(employees) == 1
            assert employees[0].department_id == 'dept1'

    @pytest.mark.asyncio
    async def test_get_employees_by_department_include_sub(self, org_chart_service):
        """子部署の社員も含める"""
        emp_data = [
            {
                'id': 'emp1',
                'name': '田中',
                'department_id': 'dept1',  # 親部署
                'is_active': True,
                'departments': {'name': '営業部'},
                'roles': {'level': 1}
            },
            {
                'id': 'emp2',
                'name': '山田',
                'department_id': 'dept2',  # 子部署
                'is_active': True,
                'departments': {'name': '営業一課'},
                'roles': {'level': 1}
            },
        ]

        dept_data = [
            {'id': 'dept1', 'name': '営業部', 'parent_id': None},
            {'id': 'dept2', 'name': '営業一課', 'parent_id': 'dept1'},
        ]

        mock_response_emp = Mock()
        mock_response_emp.json.return_value = emp_data
        mock_response_emp.raise_for_status = Mock()

        mock_response_dept = Mock()
        mock_response_dept.json.return_value = dept_data
        mock_response_dept.raise_for_status = Mock()

        with patch.object(org_chart_service, '_get_client') as mock_get_client:
            mock_client = AsyncMock()

            def get_side_effect(url, params=None):
                if 'employees' in url:
                    return mock_response_emp
                else:
                    return mock_response_dept

            mock_client.get.side_effect = get_side_effect
            mock_get_client.return_value = mock_client

            employees = await org_chart_service.get_employees_by_department(
                'dept1', include_sub_departments=True
            )

            # 親部署と子部署の両方の社員が取得される
            assert len(employees) == 2


class TestOrgChartServiceDepartmentGoogleAccounts:
    """get_department_google_accounts のテスト"""

    @pytest.mark.asyncio
    async def test_get_department_google_accounts(self, org_chart_service):
        """部署のGoogleアカウント取得"""
        mock_response = Mock()
        mock_response.json.return_value = [
            {
                'id': 'emp1',
                'name': '田中',
                'department_id': 'dept1',
                'google_account_email': 'tanaka@example.com',
                'is_active': True,
                'departments': {'name': '営業部'},
                'roles': {'level': 1}
            },
            {
                'id': 'emp2',
                'name': '山田',
                'department_id': 'dept1',
                'google_account_email': None,  # Googleアカウントなし
                'is_active': True,
                'departments': {'name': '営業部'},
                'roles': {'level': 1}
            },
        ]
        mock_response.raise_for_status = Mock()

        with patch.object(org_chart_service, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_get_client.return_value = mock_client

            accounts = await org_chart_service.get_department_google_accounts('dept1')

            assert len(accounts) == 1
            assert 'tanaka@example.com' in accounts

    @pytest.mark.asyncio
    async def test_get_department_google_accounts_include_sub(self, org_chart_service):
        """子部署含めてGoogleアカウント取得"""
        emp_data = [
            {
                'id': 'emp1',
                'name': '田中',
                'department_id': 'dept1',
                'google_account_email': 'tanaka@example.com',
                'is_active': True,
                'departments': {},
                'roles': {'level': 1}
            },
            {
                'id': 'emp2',
                'name': '山田',
                'department_id': 'dept2',  # 子部署
                'google_account_email': 'yamada@example.com',
                'is_active': True,
                'departments': {},
                'roles': {'level': 1}
            },
        ]

        dept_data = [
            {'id': 'dept1', 'name': '営業部', 'parent_id': None},
            {'id': 'dept2', 'name': '営業一課', 'parent_id': 'dept1'},
        ]

        mock_response_emp = Mock()
        mock_response_emp.json.return_value = emp_data
        mock_response_emp.raise_for_status = Mock()

        mock_response_dept = Mock()
        mock_response_dept.json.return_value = dept_data
        mock_response_dept.raise_for_status = Mock()

        with patch.object(org_chart_service, '_get_client') as mock_get_client:
            mock_client = AsyncMock()

            def get_side_effect(url, params=None):
                if 'employees' in url:
                    return mock_response_emp
                else:
                    return mock_response_dept

            mock_client.get.side_effect = get_side_effect
            mock_get_client.return_value = mock_client

            accounts = await org_chart_service.get_department_google_accounts(
                'dept1', include_sub_departments=True
            )

            assert len(accounts) == 2


class TestParseEmployeeAdditional:
    """_parse_employee の追加テスト"""

    def test_parse_employee_with_departments_json(self, org_chart_service):
        """departments_jsonのパース"""
        import json
        data = {
            'id': 'emp1',
            'name': '田中',
            'departments_json': json.dumps([
                {'department_id': 'dept2', 'department_name': '企画部'},
            ])
        }

        emp = org_chart_service._parse_employee(data)

        assert len(emp.additional_departments) == 1
        assert emp.additional_departments[0]['department_id'] == 'dept2'

    def test_parse_employee_with_invalid_departments_json(self, org_chart_service):
        """無効なJSON"""
        data = {
            'id': 'emp1',
            'name': '田中',
            'departments_json': 'invalid json'
        }

        emp = org_chart_service._parse_employee(data)

        # 無効なJSONの場合は空リスト
        assert emp.additional_departments == []

    def test_parse_employee_with_list_departments(self, org_chart_service):
        """departmentsがリストの場合（不正なデータ）"""
        data = {
            'id': 'emp1',
            'name': '田中',
            'departments': ['invalid'],  # 辞書ではなくリスト
            'roles': ['invalid']
        }

        emp = org_chart_service._parse_employee(data)

        # isinstance(dept_data, dict)がFalseなのでNoneになる
        assert emp.department_name is None
        assert emp.role_name is None

    def test_parse_employee_missing_name(self, org_chart_service):
        """nameがない場合"""
        data = {
            'id': 'emp1'
        }

        emp = org_chart_service._parse_employee(data)

        assert emp.name == ''  # デフォルト値

    def test_parse_employee_missing_is_active(self, org_chart_service):
        """is_activeがない場合"""
        data = {
            'id': 'emp1',
            'name': '田中'
        }

        emp = org_chart_service._parse_employee(data)

        assert emp.is_active is True  # デフォルト値


class TestOrgChartServiceWithOrgFilter:
    """組織フィルタ有効時のテスト"""

    @pytest.mark.asyncio
    async def test_get_all_employees_with_org_filter(self):
        """組織フィルタ有効時の全社員取得"""
        service = OrgChartService(
            supabase_url="https://test.supabase.co",
            supabase_key="test-key",
            organization_id="org_custom",
            skip_organization_filter=False
        )

        mock_response = Mock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = Mock()

        with patch.object(service, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_get_client.return_value = mock_client

            await service.get_all_employees()

            call_args = mock_client.get.call_args
            params = call_args[1]['params']
            assert params.get('organization_id') == 'eq.org_custom'

    @pytest.mark.asyncio
    async def test_get_all_departments_with_org_filter(self):
        """組織フィルタ有効時の全部署取得"""
        service = OrgChartService(
            supabase_url="https://test.supabase.co",
            supabase_key="test-key",
            skip_organization_filter=False
        )

        mock_response = Mock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = Mock()

        with patch.object(service, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_get_client.return_value = mock_client

            await service.get_all_departments()

            call_args = mock_client.get.call_args
            params = call_args[1]['params']
            assert 'organization_id' in params


class TestEmployeeByDepartmentWithConcurrent:
    """兼務部署を持つ社員のフィルタリングテスト"""

    @pytest.mark.asyncio
    async def test_employee_found_by_concurrent_department(self, org_chart_service):
        """兼務部署で検索して見つかる"""
        import json
        emp_data = [
            {
                'id': 'emp1',
                'name': '田中',
                'department_id': 'dept1',  # 主部署: 営業部
                'is_active': True,
                'departments': {'name': '営業部'},
                'roles': {'level': 1},
                'departments_json': json.dumps([
                    {'department_id': 'dept2'},  # 兼務: 企画部
                ])
            },
        ]

        mock_response = Mock()
        mock_response.json.return_value = emp_data
        mock_response.raise_for_status = Mock()

        with patch.object(org_chart_service, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_get_client.return_value = mock_client

            # 企画部で検索しても兼務社員が見つかる
            employees = await org_chart_service.get_employees_by_department('dept2')

            assert len(employees) == 1
            assert employees[0].name == '田中'


class TestGetAccountsByRoleLevelWithNoAccount:
    """Googleアカウントなし社員の役職レベル検索"""

    @pytest.mark.asyncio
    async def test_excludes_employees_without_google_account(self, org_chart_service):
        """Googleアカウントなしの社員は除外"""
        mock_response = Mock()
        mock_response.json.return_value = [
            {
                'id': 'emp1',
                'name': '田中',
                'google_account_email': 'tanaka@example.com',
                'is_active': True,
                'departments': {},
                'roles': {'level': 4}
            },
            {
                'id': 'emp2',
                'name': '山田',
                'google_account_email': None,  # Googleアカウントなし
                'is_active': True,
                'departments': {},
                'roles': {'level': 5}
            },
        ]
        mock_response.raise_for_status = Mock()

        with patch.object(org_chart_service, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_get_client.return_value = mock_client

            accounts = await org_chart_service.get_accounts_by_role_level(min_level=4)

            # レベル4以上でGoogleアカウントあり
            assert len(accounts) == 1
            assert 'tanaka@example.com' in accounts
