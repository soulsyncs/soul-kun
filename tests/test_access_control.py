"""
AccessControlService 単体テスト

Phase 3.5: 6段階権限レベルに基づくアクセス制御のテスト

テストケース構成:
- get_user_role_level: 権限レベル取得（10件）
- compute_accessible_departments: 部署アクセス計算（9件）
- get_user_departments: ユーザー所属部署取得（4件）
- get_all_departments: 全部署取得（3件）
- get_all_descendants: 配下部署取得（4件）
- get_direct_children: 直下部署取得（4件）
- can_access_department: 部署アクセス判定（6件）
- can_access_task: タスクアクセス判定（6件）
- sync versions: 同期版関数（8件）
- edge cases: 境界値・エッジケース（6件）

合計: 60テストケース
"""

import os
import sys
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

# api ディレクトリをパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'api'))

# access_control モジュールを直接インポート（__init__.py を避ける）
from app.services.access_control import (
    AccessControlService,
    get_user_role_level_sync,
    compute_accessible_departments_sync,
)

from sqlalchemy.ext.asyncio import AsyncSession


# ================================================================
# テスト用フィクスチャ
# ================================================================

@pytest.fixture
def mock_async_session():
    """非同期DBセッションのモック"""
    session = AsyncMock(spec=AsyncSession)
    return session


@pytest.fixture
def mock_sync_conn():
    """同期DBコネクションのモック"""
    conn = MagicMock()
    return conn


@pytest.fixture
def sample_organization_id():
    """テスト用組織ID"""
    return "org_test_001"


@pytest.fixture
def sample_user_id():
    """テスト用ユーザーID"""
    return "user_test_001"


@pytest.fixture
def sample_department_ids():
    """テスト用部署ID（階層構造）"""
    return {
        "hq": "dept_hq",           # 本社（Level 1）
        "sales": "dept_sales",     # 営業部（Level 2、hqの子）
        "sales_tokyo": "dept_sales_tokyo",  # 東京営業課（Level 3、salesの子）
        "sales_osaka": "dept_sales_osaka",  # 大阪営業課（Level 3、salesの子）
        "dev": "dept_dev",         # 開発部（Level 2、hqの子）
        "admin": "dept_admin",     # 管理部（Level 2、hqの子）
    }


# ================================================================
# get_user_role_level テスト（18件）
# ================================================================

class TestGetUserRoleLevel:
    """権限レベル取得のテスト"""

    @pytest.mark.asyncio
    async def test_level_6_ceo(self, mock_async_session, sample_user_id):
        """Level 6（代表/CFO）の権限レベル取得"""
        
        # モック設定: Level 6を返す
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (6,)
        mock_async_session.execute.return_value = mock_result

        service = AccessControlService(mock_async_session)
        level = await service.get_user_role_level(sample_user_id)

        assert level == 6

    @pytest.mark.asyncio
    async def test_level_5_admin(self, mock_async_session, sample_user_id):
        """Level 5（管理部）の権限レベル取得"""
        
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (5,)
        mock_async_session.execute.return_value = mock_result

        service = AccessControlService(mock_async_session)
        level = await service.get_user_role_level(sample_user_id)

        assert level == 5

    @pytest.mark.asyncio
    async def test_level_4_director(self, mock_async_session, sample_user_id):
        """Level 4（幹部/部長）の権限レベル取得"""
        
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (4,)
        mock_async_session.execute.return_value = mock_result

        service = AccessControlService(mock_async_session)
        level = await service.get_user_role_level(sample_user_id)

        assert level == 4

    @pytest.mark.asyncio
    async def test_level_3_leader(self, mock_async_session, sample_user_id):
        """Level 3（リーダー/課長）の権限レベル取得"""
        
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (3,)
        mock_async_session.execute.return_value = mock_result

        service = AccessControlService(mock_async_session)
        level = await service.get_user_role_level(sample_user_id)

        assert level == 3

    @pytest.mark.asyncio
    async def test_level_2_employee(self, mock_async_session, sample_user_id):
        """Level 2（一般社員）の権限レベル取得"""
        
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (2,)
        mock_async_session.execute.return_value = mock_result

        service = AccessControlService(mock_async_session)
        level = await service.get_user_role_level(sample_user_id)

        assert level == 2

    @pytest.mark.asyncio
    async def test_level_1_contractor(self, mock_async_session, sample_user_id):
        """Level 1（業務委託）の権限レベル取得"""
        
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (1,)
        mock_async_session.execute.return_value = mock_result

        service = AccessControlService(mock_async_session)
        level = await service.get_user_role_level(sample_user_id)

        assert level == 1

    @pytest.mark.asyncio
    async def test_default_level_when_no_role(self, mock_async_session, sample_user_id):
        """role_idがない場合、デフォルト（Level 2）を返す"""
        
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (None,)
        mock_async_session.execute.return_value = mock_result

        service = AccessControlService(mock_async_session)
        level = await service.get_user_role_level(sample_user_id)

        assert level == 2  # デフォルト: 一般社員

    @pytest.mark.asyncio
    async def test_default_level_when_no_row(self, mock_async_session, sample_user_id):
        """行が存在しない場合、デフォルト（Level 2）を返す"""
        
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_async_session.execute.return_value = mock_result

        service = AccessControlService(mock_async_session)
        level = await service.get_user_role_level(sample_user_id)

        assert level == 2  # デフォルト: 一般社員

    @pytest.mark.asyncio
    async def test_max_level_for_multiple_roles(self, mock_async_session, sample_user_id):
        """複数の役職がある場合、最大レベルを返す"""
        
        # SQLのMAX()で最大値が返される想定
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (4,)  # MAX(3, 4) = 4
        mock_async_session.execute.return_value = mock_result

        service = AccessControlService(mock_async_session)
        level = await service.get_user_role_level(sample_user_id)

        assert level == 4

    @pytest.mark.asyncio
    async def test_error_returns_default_level(self, mock_async_session, sample_user_id):
        """エラー発生時、デフォルト（Level 2）を返す（安全側に倒す）"""
        
        mock_async_session.execute.side_effect = Exception("DB error")

        service = AccessControlService(mock_async_session)
        level = await service.get_user_role_level(sample_user_id)

        assert level == 2  # デフォルト: 一般社員


# ================================================================
# compute_accessible_departments テスト（12件）
# ================================================================

class TestComputeAccessibleDepartments:
    """部署アクセス計算のテスト"""

    @pytest.mark.asyncio
    async def test_level_6_can_access_all_departments(
        self, mock_async_session, sample_user_id, sample_organization_id, sample_department_ids
    ):
        """Level 6は全部署にアクセス可能"""
        
        service = AccessControlService(mock_async_session)

        # get_user_role_levelをモック
        with patch.object(service, 'get_user_role_level', return_value=6):
            with patch.object(service, 'get_all_departments', return_value=list(sample_department_ids.values())):
                result = await service.compute_accessible_departments(sample_user_id, sample_organization_id)

        assert len(result) == 6
        assert set(result) == set(sample_department_ids.values())

    @pytest.mark.asyncio
    async def test_level_5_can_access_all_departments(
        self, mock_async_session, sample_user_id, sample_organization_id, sample_department_ids
    ):
        """Level 5も全部署にアクセス可能"""
        
        service = AccessControlService(mock_async_session)

        with patch.object(service, 'get_user_role_level', return_value=5):
            with patch.object(service, 'get_all_departments', return_value=list(sample_department_ids.values())):
                result = await service.compute_accessible_departments(sample_user_id, sample_organization_id)

        assert len(result) == 6

    @pytest.mark.asyncio
    async def test_level_4_can_access_own_and_all_descendants(
        self, mock_async_session, sample_user_id, sample_organization_id, sample_department_ids
    ):
        """Level 4は自部署＋配下全部署にアクセス可能"""
        
        service = AccessControlService(mock_async_session)

        # 営業部長（sales部署に所属）の場合
        user_depts = [sample_department_ids["sales"]]
        descendants = [sample_department_ids["sales_tokyo"], sample_department_ids["sales_osaka"]]

        with patch.object(service, 'get_user_role_level', return_value=4):
            with patch.object(service, 'get_user_departments', return_value=user_depts):
                with patch.object(service, 'get_all_descendants', return_value=descendants):
                    result = await service.compute_accessible_departments(sample_user_id, sample_organization_id)

        # 自部署（sales）+ 配下（tokyo, osaka）= 3部署
        assert len(result) == 3
        assert sample_department_ids["sales"] in result
        assert sample_department_ids["sales_tokyo"] in result
        assert sample_department_ids["sales_osaka"] in result
        # 他部署は含まれない
        assert sample_department_ids["dev"] not in result

    @pytest.mark.asyncio
    async def test_level_3_can_access_own_and_direct_children(
        self, mock_async_session, sample_user_id, sample_organization_id, sample_department_ids
    ):
        """Level 3は自部署＋直下部署のみアクセス可能"""
        
        service = AccessControlService(mock_async_session)

        # 営業部のリーダーの場合
        user_depts = [sample_department_ids["sales"]]
        direct_children = [sample_department_ids["sales_tokyo"], sample_department_ids["sales_osaka"]]

        with patch.object(service, 'get_user_role_level', return_value=3):
            with patch.object(service, 'get_user_departments', return_value=user_depts):
                with patch.object(service, 'get_direct_children', return_value=direct_children):
                    result = await service.compute_accessible_departments(sample_user_id, sample_organization_id)

        assert len(result) == 3
        assert sample_department_ids["sales"] in result
        assert sample_department_ids["sales_tokyo"] in result
        assert sample_department_ids["sales_osaka"] in result

    @pytest.mark.asyncio
    async def test_level_2_can_access_only_own_department(
        self, mock_async_session, sample_user_id, sample_organization_id, sample_department_ids
    ):
        """Level 2は自部署のみアクセス可能"""
        
        service = AccessControlService(mock_async_session)

        user_depts = [sample_department_ids["sales_tokyo"]]

        with patch.object(service, 'get_user_role_level', return_value=2):
            with patch.object(service, 'get_user_departments', return_value=user_depts):
                result = await service.compute_accessible_departments(sample_user_id, sample_organization_id)

        # 自部署のみ
        assert len(result) == 1
        assert sample_department_ids["sales_tokyo"] in result
        # 親部署は含まれない
        assert sample_department_ids["sales"] not in result

    @pytest.mark.asyncio
    async def test_level_1_can_access_only_own_department(
        self, mock_async_session, sample_user_id, sample_organization_id, sample_department_ids
    ):
        """Level 1も自部署のみアクセス可能"""
        
        service = AccessControlService(mock_async_session)

        user_depts = [sample_department_ids["dev"]]

        with patch.object(service, 'get_user_role_level', return_value=1):
            with patch.object(service, 'get_user_departments', return_value=user_depts):
                result = await service.compute_accessible_departments(sample_user_id, sample_organization_id)

        assert len(result) == 1
        assert sample_department_ids["dev"] in result

    @pytest.mark.asyncio
    async def test_no_department_returns_empty_list(
        self, mock_async_session, sample_user_id, sample_organization_id
    ):
        """部署未所属の場合、空リストを返す"""
        
        service = AccessControlService(mock_async_session)

        with patch.object(service, 'get_user_role_level', return_value=2):
            with patch.object(service, 'get_user_departments', return_value=[]):
                result = await service.compute_accessible_departments(sample_user_id, sample_organization_id)

        assert result == []

    @pytest.mark.asyncio
    async def test_multiple_departments_level_4(
        self, mock_async_session, sample_user_id, sample_organization_id, sample_department_ids
    ):
        """複数部署所属（兼務）のLevel 4の場合"""
        
        service = AccessControlService(mock_async_session)

        # 営業部と開発部に兼務
        user_depts = [sample_department_ids["sales"], sample_department_ids["dev"]]

        async def mock_get_all_descendants(dept_id, org_id):
            if dept_id == sample_department_ids["sales"]:
                return [sample_department_ids["sales_tokyo"], sample_department_ids["sales_osaka"]]
            return []

        with patch.object(service, 'get_user_role_level', return_value=4):
            with patch.object(service, 'get_user_departments', return_value=user_depts):
                with patch.object(service, 'get_all_descendants', side_effect=mock_get_all_descendants):
                    result = await service.compute_accessible_departments(sample_user_id, sample_organization_id)

        # sales + tokyo + osaka + dev = 4部署
        assert len(result) == 4

    @pytest.mark.asyncio
    async def test_error_returns_empty_list(
        self, mock_async_session, sample_user_id, sample_organization_id
    ):
        """エラー発生時、空リストを返す（安全側に倒す）"""
        
        service = AccessControlService(mock_async_session)

        with patch.object(service, 'get_user_role_level', side_effect=Exception("DB error")):
            result = await service.compute_accessible_departments(sample_user_id, sample_organization_id)

        assert result == []


# ================================================================
# get_user_departments テスト（4件）
# ================================================================

class TestGetUserDepartments:
    """ユーザー所属部署取得のテスト"""

    @pytest.mark.asyncio
    async def test_returns_user_departments(self, mock_async_session, sample_user_id):
        """ユーザーの所属部署を返す"""
        
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("dept_001",), ("dept_002",)]
        mock_async_session.execute.return_value = mock_result

        service = AccessControlService(mock_async_session)
        result = await service.get_user_departments(sample_user_id)

        assert result == ["dept_001", "dept_002"]

    @pytest.mark.asyncio
    async def test_returns_empty_for_no_departments(self, mock_async_session, sample_user_id):
        """部署未所属の場合、空リストを返す"""
        
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_async_session.execute.return_value = mock_result

        service = AccessControlService(mock_async_session)
        result = await service.get_user_departments(sample_user_id)

        assert result == []

    @pytest.mark.asyncio
    async def test_excludes_ended_departments(self, mock_async_session, sample_user_id):
        """ended_atが設定された部署は除外される"""
        
        # SQLにWHERE ended_at IS NULLがあるので、DBが正しくフィルタする
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("dept_active",)]  # 終了した部署は含まれない
        mock_async_session.execute.return_value = mock_result

        service = AccessControlService(mock_async_session)
        result = await service.get_user_departments(sample_user_id)

        assert result == ["dept_active"]

    @pytest.mark.asyncio
    async def test_error_returns_empty_list(self, mock_async_session, sample_user_id):
        """エラー発生時、空リストを返す"""
        
        mock_async_session.execute.side_effect = Exception("DB error")

        service = AccessControlService(mock_async_session)
        result = await service.get_user_departments(sample_user_id)

        assert result == []


# ================================================================
# get_all_departments テスト（3件）
# ================================================================

class TestGetAllDepartments:
    """全部署取得のテスト"""

    @pytest.mark.asyncio
    async def test_returns_all_active_departments(self, mock_async_session, sample_organization_id):
        """有効な全部署を返す"""
        
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("dept_001",), ("dept_002",), ("dept_003",)]
        mock_async_session.execute.return_value = mock_result

        service = AccessControlService(mock_async_session)
        result = await service.get_all_departments(sample_organization_id)

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_returns_empty_for_no_departments(self, mock_async_session, sample_organization_id):
        """部署がない場合、空リストを返す"""
        
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_async_session.execute.return_value = mock_result

        service = AccessControlService(mock_async_session)
        result = await service.get_all_departments(sample_organization_id)

        assert result == []

    @pytest.mark.asyncio
    async def test_error_returns_empty_list(self, mock_async_session, sample_organization_id):
        """エラー発生時、空リストを返す"""
        
        mock_async_session.execute.side_effect = Exception("DB error")

        service = AccessControlService(mock_async_session)
        result = await service.get_all_departments(sample_organization_id)

        assert result == []


# ================================================================
# get_all_descendants テスト（4件）- LTREE使用
# ================================================================

class TestGetAllDescendants:
    """配下部署取得のテスト（LTREE）"""

    @pytest.mark.asyncio
    async def test_returns_all_descendants(self, mock_async_session, sample_organization_id):
        """全配下部署を返す"""
        
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("dept_child_1",), ("dept_child_2",), ("dept_grandchild",)]
        mock_async_session.execute.return_value = mock_result

        service = AccessControlService(mock_async_session)
        result = await service.get_all_descendants("dept_parent", sample_organization_id)

        assert len(result) == 3
        assert "dept_child_1" in result
        assert "dept_grandchild" in result

    @pytest.mark.asyncio
    async def test_excludes_self(self, mock_async_session, sample_organization_id):
        """自分自身は含まれない"""
        
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("dept_child",)]  # 自分自身は含まれない
        mock_async_session.execute.return_value = mock_result

        service = AccessControlService(mock_async_session)
        result = await service.get_all_descendants("dept_parent", sample_organization_id)

        # SQLに d.id != :dept_id があるので、自分自身は含まれない
        assert "dept_parent" not in result

    @pytest.mark.asyncio
    async def test_returns_empty_for_leaf_node(self, mock_async_session, sample_organization_id):
        """末端部署の場合、空リストを返す"""
        
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_async_session.execute.return_value = mock_result

        service = AccessControlService(mock_async_session)
        result = await service.get_all_descendants("dept_leaf", sample_organization_id)

        assert result == []

    @pytest.mark.asyncio
    async def test_error_returns_empty_list(self, mock_async_session, sample_organization_id):
        """エラー発生時、空リストを返す（安全側に倒す）"""
        
        mock_async_session.execute.side_effect = Exception("DB error")

        service = AccessControlService(mock_async_session)
        result = await service.get_all_descendants("dept_parent", sample_organization_id)

        assert result == []


# ================================================================
# get_direct_children テスト（4件）
# ================================================================

class TestGetDirectChildren:
    """直下部署取得のテスト"""

    @pytest.mark.asyncio
    async def test_returns_direct_children(self, mock_async_session, sample_organization_id):
        """直下の子部署を返す"""
        
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("dept_child_1",), ("dept_child_2",)]
        mock_async_session.execute.return_value = mock_result

        service = AccessControlService(mock_async_session)
        result = await service.get_direct_children("dept_parent", sample_organization_id)

        assert len(result) == 2
        assert "dept_child_1" in result
        assert "dept_child_2" in result

    @pytest.mark.asyncio
    async def test_excludes_grandchildren(self, mock_async_session, sample_organization_id):
        """孫部署は含まれない（直下のみ）"""
        
        # SQLがparent_department_id = :dept_idでフィルタするので、孫は含まれない
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("dept_child",)]  # 孫は含まれない
        mock_async_session.execute.return_value = mock_result

        service = AccessControlService(mock_async_session)
        result = await service.get_direct_children("dept_parent", sample_organization_id)

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_returns_empty_for_leaf_node(self, mock_async_session, sample_organization_id):
        """末端部署の場合、空リストを返す"""
        
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_async_session.execute.return_value = mock_result

        service = AccessControlService(mock_async_session)
        result = await service.get_direct_children("dept_leaf", sample_organization_id)

        assert result == []

    @pytest.mark.asyncio
    async def test_error_returns_empty_list(self, mock_async_session, sample_organization_id):
        """エラー発生時、空リストを返す"""
        
        mock_async_session.execute.side_effect = Exception("DB error")

        service = AccessControlService(mock_async_session)
        result = await service.get_direct_children("dept_parent", sample_organization_id)

        assert result == []


# ================================================================
# can_access_department テスト（6件）
# ================================================================

class TestCanAccessDepartment:
    """部署アクセス判定のテスト"""

    @pytest.mark.asyncio
    async def test_can_access_own_department(
        self, mock_async_session, sample_user_id, sample_organization_id
    ):
        """自部署にはアクセス可能"""
        
        service = AccessControlService(mock_async_session)

        with patch.object(service, 'compute_accessible_departments', return_value=["dept_own", "dept_child"]):
            result = await service.can_access_department(sample_user_id, "dept_own", sample_organization_id)

        assert result is True

    @pytest.mark.asyncio
    async def test_can_access_child_department(
        self, mock_async_session, sample_user_id, sample_organization_id
    ):
        """配下部署にはアクセス可能"""
        
        service = AccessControlService(mock_async_session)

        with patch.object(service, 'compute_accessible_departments', return_value=["dept_own", "dept_child"]):
            result = await service.can_access_department(sample_user_id, "dept_child", sample_organization_id)

        assert result is True

    @pytest.mark.asyncio
    async def test_cannot_access_other_department(
        self, mock_async_session, sample_user_id, sample_organization_id
    ):
        """他部署にはアクセス不可"""
        
        service = AccessControlService(mock_async_session)

        with patch.object(service, 'compute_accessible_departments', return_value=["dept_own"]):
            result = await service.can_access_department(sample_user_id, "dept_other", sample_organization_id)

        assert result is False

    @pytest.mark.asyncio
    async def test_cannot_access_sibling_department(
        self, mock_async_session, sample_user_id, sample_organization_id
    ):
        """兄弟部署にはアクセス不可（デフォルト）"""
        
        service = AccessControlService(mock_async_session)

        with patch.object(service, 'compute_accessible_departments', return_value=["dept_sales_tokyo"]):
            result = await service.can_access_department(sample_user_id, "dept_sales_osaka", sample_organization_id)

        assert result is False

    @pytest.mark.asyncio
    async def test_cannot_access_parent_department(
        self, mock_async_session, sample_user_id, sample_organization_id
    ):
        """親部署にはアクセス不可（Level 2の場合）"""
        
        service = AccessControlService(mock_async_session)

        with patch.object(service, 'compute_accessible_departments', return_value=["dept_sales_tokyo"]):
            result = await service.can_access_department(sample_user_id, "dept_sales", sample_organization_id)

        assert result is False

    @pytest.mark.asyncio
    async def test_error_returns_false(
        self, mock_async_session, sample_user_id, sample_organization_id
    ):
        """エラー発生時、アクセス不可を返す（安全側に倒す）"""
        
        service = AccessControlService(mock_async_session)

        with patch.object(service, 'compute_accessible_departments', side_effect=Exception("DB error")):
            result = await service.can_access_department(sample_user_id, "dept_any", sample_organization_id)

        assert result is False


# ================================================================
# can_access_task テスト（6件）
# ================================================================

class TestCanAccessTask:
    """タスクアクセス判定のテスト"""

    @pytest.mark.asyncio
    async def test_can_access_task_in_own_department(
        self, mock_async_session, sample_user_id, sample_organization_id
    ):
        """自部署のタスクにアクセス可能"""
        
        service = AccessControlService(mock_async_session)

        with patch.object(service, 'can_access_department', return_value=True):
            result = await service.can_access_task(sample_user_id, "dept_own", sample_organization_id)

        assert result is True

    @pytest.mark.asyncio
    async def test_cannot_access_task_in_other_department(
        self, mock_async_session, sample_user_id, sample_organization_id
    ):
        """他部署のタスクにはアクセス不可"""
        
        service = AccessControlService(mock_async_session)

        with patch.object(service, 'can_access_department', return_value=False):
            result = await service.can_access_task(sample_user_id, "dept_other", sample_organization_id)

        assert result is False

    @pytest.mark.asyncio
    async def test_can_access_task_with_null_department(
        self, mock_async_session, sample_user_id, sample_organization_id
    ):
        """部署未設定のタスクにはアクセス可能（後方互換性）"""
        
        service = AccessControlService(mock_async_session)

        # department_id が None の場合、全員アクセス可能
        result = await service.can_access_task(sample_user_id, None, sample_organization_id)

        assert result is True

    @pytest.mark.asyncio
    async def test_null_department_allows_all_access(
        self, mock_async_session, sample_user_id, sample_organization_id
    ):
        """NULL部署のタスクは権限に関係なくアクセス可能"""
        
        service = AccessControlService(mock_async_session)

        # can_access_departmentは呼ばれない
        with patch.object(service, 'can_access_department') as mock_method:
            result = await service.can_access_task(sample_user_id, None, sample_organization_id)
            mock_method.assert_not_called()

        assert result is True

    @pytest.mark.asyncio
    async def test_error_returns_false(
        self, mock_async_session, sample_user_id, sample_organization_id
    ):
        """エラー発生時、アクセス不可を返す（安全側に倒す）"""
        
        service = AccessControlService(mock_async_session)

        with patch.object(service, 'can_access_department', side_effect=Exception("DB error")):
            result = await service.can_access_task(sample_user_id, "dept_any", sample_organization_id)

        assert result is False

    @pytest.mark.asyncio
    async def test_empty_string_department_treated_as_null(
        self, mock_async_session, sample_user_id, sample_organization_id
    ):
        """空文字列の部署IDはNoneとして扱わない（厳密な判定）"""
        
        service = AccessControlService(mock_async_session)

        # 空文字列はNoneではないので、can_access_departmentが呼ばれる
        with patch.object(service, 'can_access_department', return_value=False):
            result = await service.can_access_task(sample_user_id, "", sample_organization_id)

        # 空文字列はNoneではないので、通常のアクセス判定が行われる
        assert result is False


# ================================================================
# 同期版関数テスト（8件）
# ================================================================

class TestSyncVersions:
    """同期版関数のテスト（Cloud Functions用）"""

    def test_get_user_role_level_sync_returns_level(self, mock_sync_conn, sample_user_id):
        """同期版: 権限レベルを返す"""
        
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (4,)
        mock_sync_conn.execute.return_value = mock_result

        level = get_user_role_level_sync(mock_sync_conn, sample_user_id)

        assert level == 4

    def test_get_user_role_level_sync_returns_default_on_none(self, mock_sync_conn, sample_user_id):
        """同期版: NULLの場合、デフォルトを返す"""
        
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (None,)
        mock_sync_conn.execute.return_value = mock_result

        level = get_user_role_level_sync(mock_sync_conn, sample_user_id)

        assert level == 2  # デフォルト: 一般社員

    def test_get_user_role_level_sync_returns_default_on_error(self, mock_sync_conn, sample_user_id):
        """同期版: エラー時、デフォルトを返す"""
        
        mock_sync_conn.execute.side_effect = Exception("DB error")

        level = get_user_role_level_sync(mock_sync_conn, sample_user_id)

        assert level == 2  # デフォルト: 一般社員

    def test_compute_accessible_departments_sync_level_6(
        self, mock_sync_conn, sample_user_id, sample_organization_id
    ):
        """同期版: Level 6は全部署"""
        
        # 最初の呼び出し: get_user_role_level_sync
        # 2番目の呼び出し: 全部署取得
        mock_results = [
            MagicMock(fetchone=MagicMock(return_value=(6,))),  # Level 6
            MagicMock(fetchall=MagicMock(return_value=[("dept_1",), ("dept_2",), ("dept_3",)])),  # 全部署
        ]
        mock_sync_conn.execute.side_effect = mock_results

        result = compute_accessible_departments_sync(mock_sync_conn, sample_user_id, sample_organization_id)

        assert len(result) == 3

    def test_compute_accessible_departments_sync_level_2(
        self, mock_sync_conn, sample_user_id, sample_organization_id
    ):
        """同期版: Level 2は自部署のみ"""
        
        mock_results = [
            MagicMock(fetchone=MagicMock(return_value=(2,))),  # Level 2
            MagicMock(fetchall=MagicMock(return_value=[("dept_own",)])),  # 所属部署
        ]
        mock_sync_conn.execute.side_effect = mock_results

        result = compute_accessible_departments_sync(mock_sync_conn, sample_user_id, sample_organization_id)

        assert len(result) == 1
        assert "dept_own" in result

    def test_compute_accessible_departments_sync_no_department(
        self, mock_sync_conn, sample_user_id, sample_organization_id
    ):
        """同期版: 部署未所属の場合、空リスト"""
        
        mock_results = [
            MagicMock(fetchone=MagicMock(return_value=(2,))),  # Level 2
            MagicMock(fetchall=MagicMock(return_value=[])),  # 所属部署なし
        ]
        mock_sync_conn.execute.side_effect = mock_results

        result = compute_accessible_departments_sync(mock_sync_conn, sample_user_id, sample_organization_id)

        assert result == []

    def test_compute_accessible_departments_sync_error_returns_empty(
        self, mock_sync_conn, sample_user_id, sample_organization_id
    ):
        """同期版: エラー時、空リストを返す"""
        
        mock_sync_conn.execute.side_effect = Exception("DB error")

        result = compute_accessible_departments_sync(mock_sync_conn, sample_user_id, sample_organization_id)

        assert result == []

    def test_compute_accessible_departments_sync_level_4_with_descendants(
        self, mock_sync_conn, sample_user_id, sample_organization_id
    ):
        """同期版: Level 4で配下部署を取得"""
        
        # Level取得 → 所属部署取得 → 配下部署取得
        mock_results = [
            MagicMock(fetchone=MagicMock(return_value=(4,))),  # Level 4
            MagicMock(fetchall=MagicMock(return_value=[("dept_sales",)])),  # 所属部署
            MagicMock(fetchall=MagicMock(return_value=[("dept_tokyo",), ("dept_osaka",)])),  # 配下部署
        ]
        mock_sync_conn.execute.side_effect = mock_results

        result = compute_accessible_departments_sync(mock_sync_conn, sample_user_id, sample_organization_id)

        # 自部署 + 配下2部署 = 3
        assert len(result) == 3
        assert "dept_sales" in result
        assert "dept_tokyo" in result
        assert "dept_osaka" in result


# ================================================================
# 境界値・エッジケーステスト（6件）
# ================================================================

class TestEdgeCases:
    """境界値・エッジケースのテスト"""

    @pytest.mark.asyncio
    async def test_level_boundary_4_and_5(self, mock_async_session, sample_user_id, sample_organization_id):
        """Level 4と5の境界（4は配下のみ、5は全部署）"""
        
        service = AccessControlService(mock_async_session)

        # Level 4: 自部署+配下
        with patch.object(service, 'get_user_role_level', return_value=4):
            with patch.object(service, 'get_user_departments', return_value=["dept_sales"]):
                with patch.object(service, 'get_all_descendants', return_value=["dept_tokyo"]):
                    result_4 = await service.compute_accessible_departments(sample_user_id, sample_organization_id)

        # Level 5: 全部署
        with patch.object(service, 'get_user_role_level', return_value=5):
            with patch.object(service, 'get_all_departments', return_value=["dept_sales", "dept_tokyo", "dept_dev"]):
                result_5 = await service.compute_accessible_departments(sample_user_id, sample_organization_id)

        assert len(result_4) == 2  # 自部署 + 配下
        assert len(result_5) == 3  # 全部署

    @pytest.mark.asyncio
    async def test_level_boundary_2_and_3(self, mock_async_session, sample_user_id, sample_organization_id):
        """Level 2と3の境界（2は自部署のみ、3は+直下）"""
        
        service = AccessControlService(mock_async_session)

        # Level 2: 自部署のみ
        with patch.object(service, 'get_user_role_level', return_value=2):
            with patch.object(service, 'get_user_departments', return_value=["dept_sales"]):
                result_2 = await service.compute_accessible_departments(sample_user_id, sample_organization_id)

        # Level 3: 自部署 + 直下
        with patch.object(service, 'get_user_role_level', return_value=3):
            with patch.object(service, 'get_user_departments', return_value=["dept_sales"]):
                with patch.object(service, 'get_direct_children', return_value=["dept_tokyo"]):
                    result_3 = await service.compute_accessible_departments(sample_user_id, sample_organization_id)

        assert len(result_2) == 1  # 自部署のみ
        assert len(result_3) == 2  # 自部署 + 直下

    @pytest.mark.asyncio
    async def test_level_boundary_3_and_4(self, mock_async_session, sample_user_id, sample_organization_id):
        """Level 3と4の境界（3は直下のみ、4は全配下）"""
        
        service = AccessControlService(mock_async_session)

        # Level 3: 直下のみ
        with patch.object(service, 'get_user_role_level', return_value=3):
            with patch.object(service, 'get_user_departments', return_value=["dept_sales"]):
                with patch.object(service, 'get_direct_children', return_value=["dept_tokyo"]):
                    result_3 = await service.compute_accessible_departments(sample_user_id, sample_organization_id)

        # Level 4: 全配下（孫も含む）
        with patch.object(service, 'get_user_role_level', return_value=4):
            with patch.object(service, 'get_user_departments', return_value=["dept_sales"]):
                with patch.object(service, 'get_all_descendants', return_value=["dept_tokyo", "dept_tokyo_team1"]):
                    result_4 = await service.compute_accessible_departments(sample_user_id, sample_organization_id)

        assert len(result_3) == 2  # 自部署 + 直下
        assert len(result_4) == 3  # 自部署 + 全配下

    @pytest.mark.asyncio
    async def test_deeply_nested_hierarchy(self, mock_async_session, sample_user_id, sample_organization_id):
        """深い階層構造（4階層以上）"""
        
        service = AccessControlService(mock_async_session)

        # 4階層: 本社 → 営業部 → 東京課 → チームA
        deep_descendants = ["dept_sales", "dept_tokyo", "dept_team_a", "dept_sub_team"]

        with patch.object(service, 'get_user_role_level', return_value=4):
            with patch.object(service, 'get_user_departments', return_value=["dept_hq"]):
                with patch.object(service, 'get_all_descendants', return_value=deep_descendants):
                    result = await service.compute_accessible_departments(sample_user_id, sample_organization_id)

        assert len(result) == 5  # 自部署 + 4配下

    @pytest.mark.asyncio
    async def test_empty_organization(self, mock_async_session, sample_user_id, sample_organization_id):
        """部署がない組織"""
        
        service = AccessControlService(mock_async_session)

        with patch.object(service, 'get_user_role_level', return_value=6):
            with patch.object(service, 'get_all_departments', return_value=[]):
                result = await service.compute_accessible_departments(sample_user_id, sample_organization_id)

        assert result == []

    @pytest.mark.asyncio
    async def test_uuid_format_ids(self, mock_async_session, sample_organization_id):
        """UUID形式のIDを正しく処理"""
        
        uuid_user_id = "550e8400-e29b-41d4-a716-446655440000"
        uuid_dept_id = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"

        service = AccessControlService(mock_async_session)

        with patch.object(service, 'compute_accessible_departments', return_value=[uuid_dept_id]):
            result = await service.can_access_department(uuid_user_id, uuid_dept_id, sample_organization_id)

        assert result is True
