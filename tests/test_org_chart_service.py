"""
Org Chart Service テスト

Phase B: Google Drive 自動権限管理機能
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import httpx

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
def mock_httpx_client():
    """モックHTTPクライアント"""
    with patch('lib.org_chart_service.httpx.AsyncClient') as mock_client:
        mock_instance = AsyncMock()
        mock_client.return_value = mock_instance
        yield mock_instance


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
        assert DEFAULT_ORGANIZATION_ID == "org_soulsyncs"


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

    def test_init_missing_key_raises(self):
        """キーなしでエラー"""
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
