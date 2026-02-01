"""
Person Service テスト

lib/person_service.py のユニットテスト
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from lib.person_service import (
    PersonService,
    OrgChartService,
    normalize_person_name,
)


# ================================================================
# Fixtures
# ================================================================

@pytest.fixture
def mock_pool():
    """モックDBプール"""
    pool = MagicMock()
    return pool


@pytest.fixture
def mock_get_pool(mock_pool):
    """get_poolコールバック"""
    return lambda: mock_pool


@pytest.fixture
def person_service(mock_get_pool):
    """テスト用PersonService"""
    return PersonService(get_pool=mock_get_pool)


@pytest.fixture
def org_chart_service(mock_get_pool):
    """テスト用OrgChartService"""
    return OrgChartService(get_pool=mock_get_pool)


# ================================================================
# normalize_person_name Tests
# ================================================================

class TestNormalizePersonName:
    """normalize_person_name関数のテスト"""

    def test_normalize_with_reading(self):
        """読み仮名を除去"""
        result = normalize_person_name("高野　義浩 (タカノ ヨシヒロ)")
        assert result == "高野義浩"

    def test_normalize_with_honorific_san(self):
        """敬称「さん」を除去"""
        result = normalize_person_name("田中さん")
        assert result == "田中"

    def test_normalize_with_honorific_kun(self):
        """敬称「くん」を除去"""
        result = normalize_person_name("山田くん")
        assert result == "山田"

    def test_normalize_with_honorific_chan(self):
        """敬称「ちゃん」を除去"""
        result = normalize_person_name("花子ちゃん")
        assert result == "花子"

    def test_normalize_with_honorific_sama(self):
        """敬称「様」を除去"""
        result = normalize_person_name("佐藤様")
        assert result == "佐藤"

    def test_normalize_with_honorific_shi(self):
        """敬称「氏」を除去"""
        result = normalize_person_name("鈴木氏")
        assert result == "鈴木"

    def test_normalize_removes_spaces(self):
        """スペースを除去"""
        result = normalize_person_name("田中 太郎")
        assert result == "田中太郎"

    def test_normalize_removes_fullwidth_spaces(self):
        """全角スペースを除去"""
        result = normalize_person_name("田中　太郎")
        assert result == "田中太郎"

    def test_normalize_none_input(self):
        """None入力"""
        result = normalize_person_name(None)
        assert result is None

    def test_normalize_empty_string(self):
        """空文字入力"""
        result = normalize_person_name("")
        assert result == ""

    def test_normalize_complex_name(self):
        """複合的なケース"""
        result = normalize_person_name("高野　義浩さん (タカノ ヨシヒロ)")
        # 読み仮名除去 → スペース除去 → 敬称除去
        assert result == "高野義浩"


# ================================================================
# PersonService Tests
# ================================================================

class TestPersonServiceGetOrCreatePerson:
    """get_or_create_personのテスト"""

    def test_get_existing_person(self, person_service, mock_pool):
        """既存の人物を取得"""
        # Setup mock
        mock_conn = MagicMock()
        mock_pool.begin.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.begin.return_value.__exit__ = Mock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = (123,)

        result = person_service.get_or_create_person("田中太郎")

        assert result == 123
        mock_conn.execute.assert_called_once()

    def test_create_new_person(self, person_service, mock_pool):
        """新規人物を作成"""
        mock_conn = MagicMock()
        mock_pool.begin.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.begin.return_value.__exit__ = Mock(return_value=False)
        # 最初のSELECTでNone、次のINSERTで新ID
        mock_conn.execute.return_value.fetchone.side_effect = [None, (456,)]

        result = person_service.get_or_create_person("新規太郎")

        assert result == 456
        assert mock_conn.execute.call_count == 2


class TestPersonServiceSavePersonAttribute:
    """save_person_attributeのテスト"""

    def test_save_attribute(self, person_service, mock_pool):
        """属性を保存"""
        mock_conn = MagicMock()
        mock_pool.begin.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.begin.return_value.__exit__ = Mock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = (1,)

        result = person_service.save_person_attribute(
            person_name="田中太郎",
            attribute_type="好きな食べ物",
            attribute_value="ラーメン",
            source="conversation"
        )

        assert result is True


class TestPersonServiceGetPersonInfo:
    """get_person_infoのテスト"""

    def test_get_existing_person_info(self, person_service, mock_pool):
        """既存の人物情報を取得"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = Mock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = (1,)
        mock_conn.execute.return_value.fetchall.return_value = [
            ("好きな食べ物", "ラーメン"),
            ("趣味", "読書"),
        ]

        result = person_service.get_person_info("田中太郎")

        assert result["name"] == "田中太郎"
        assert len(result["attributes"]) == 2
        assert result["attributes"][0]["type"] == "好きな食べ物"

    def test_get_nonexistent_person_info(self, person_service, mock_pool):
        """存在しない人物情報を取得"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = Mock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = None

        result = person_service.get_person_info("存在しない人")

        assert result is None


class TestPersonServiceDeletePerson:
    """delete_personのテスト"""

    def test_delete_existing_person(self, person_service, mock_pool):
        """既存の人物を削除"""
        mock_conn = MagicMock()
        mock_trans = MagicMock()
        mock_pool.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = Mock(return_value=False)
        mock_conn.begin.return_value = mock_trans
        mock_conn.execute.return_value.fetchone.return_value = (1,)

        result = person_service.delete_person("田中太郎")

        assert result is True
        mock_trans.commit.assert_called_once()

    def test_delete_nonexistent_person(self, person_service, mock_pool):
        """存在しない人物を削除"""
        mock_conn = MagicMock()
        mock_trans = MagicMock()
        mock_pool.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = Mock(return_value=False)
        mock_conn.begin.return_value = mock_trans
        mock_conn.execute.return_value.fetchone.return_value = None

        result = person_service.delete_person("存在しない人")

        assert result is False
        mock_trans.rollback.assert_called_once()

    def test_delete_person_with_exception(self, person_service, mock_pool):
        """削除中に例外発生"""
        mock_conn = MagicMock()
        mock_trans = MagicMock()
        mock_pool.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = Mock(return_value=False)
        mock_conn.begin.return_value = mock_trans
        mock_conn.execute.return_value.fetchone.return_value = (1,)
        mock_conn.execute.side_effect = [
            MagicMock(fetchone=Mock(return_value=(1,))),
            Exception("DB Error")
        ]

        result = person_service.delete_person("田中太郎")

        assert result is False
        mock_trans.rollback.assert_called_once()


class TestPersonServiceGetAllPersonsSummary:
    """get_all_persons_summaryのテスト"""

    def test_get_all_persons_summary(self, person_service, mock_pool):
        """全人物のサマリーを取得"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = Mock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = [
            ("田中太郎", "好きな食べ物=ラーメン, 趣味=読書"),
            ("山田花子", "好きな色=青"),
        ]

        result = person_service.get_all_persons_summary()

        assert len(result) == 2
        assert result[0]["name"] == "田中太郎"
        assert "ラーメン" in result[0]["attributes"]


class TestPersonServiceSearchPersonByPartialName:
    """search_person_by_partial_nameのテスト"""

    def test_search_with_results(self, person_service, mock_pool):
        """検索結果あり"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = Mock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = [
            ("田中太郎",),
            ("田中花子",),
        ]

        result = person_service.search_person_by_partial_name("田中")

        assert len(result) == 2
        assert "田中太郎" in result
        assert "田中花子" in result

    def test_search_with_no_results(self, person_service, mock_pool):
        """検索結果なし"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = Mock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = []

        result = person_service.search_person_by_partial_name("存在しない")

        assert len(result) == 0


# ================================================================
# OrgChartService Tests
# ================================================================

class TestOrgChartServiceGetOrgChartOverview:
    """get_org_chart_overviewのテスト"""

    def test_get_overview(self, org_chart_service, mock_pool):
        """組織図概要を取得"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = Mock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = [
            ("uuid-1", "営業部", 1, None, 5),
            ("uuid-2", "開発部", 1, None, 10),
            ("uuid-3", "営業1課", 2, "uuid-1", 3),
        ]

        result = org_chart_service.get_org_chart_overview()

        assert len(result) == 3
        assert result[0]["name"] == "営業部"
        assert result[0]["member_count"] == 5
        assert result[2]["parent_id"] == "uuid-1"


class TestOrgChartServiceSearchDepartmentByName:
    """search_department_by_nameのテスト"""

    def test_search_department(self, org_chart_service, mock_pool):
        """部署検索"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = Mock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = [
            ("uuid-1", "営業部", 1, 5),
            ("uuid-3", "営業1課", 2, 3),
        ]

        result = org_chart_service.search_department_by_name("営業")

        assert len(result) == 2
        assert result[0]["name"] == "営業部"


class TestOrgChartServiceGetDepartmentMembers:
    """get_department_membersのテスト"""

    def test_get_members_existing_department(self, org_chart_service, mock_pool):
        """既存部署のメンバー取得"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = Mock(return_value=False)
        # 部署検索結果
        mock_conn.execute.return_value.fetchone.return_value = ("uuid-1", "営業部", "ext-1")
        # メンバー一覧
        mock_conn.execute.return_value.fetchall.return_value = [
            ("田中太郎", "部長", "正社員", 0, 2),
            ("山田花子", "メンバー", "正社員", 0, 10),
            ("佐藤一郎", "兼務", "正社員", 1, 10),
        ]

        dept_name, members = org_chart_service.get_department_members("営業")

        assert dept_name == "営業部"
        assert len(members) == 3
        assert members[0]["name"] == "田中太郎"
        assert members[2].get("is_concurrent") is True

    def test_get_members_nonexistent_department(self, org_chart_service, mock_pool):
        """存在しない部署"""
        mock_conn = MagicMock()
        mock_pool.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_pool.connect.return_value.__exit__ = Mock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = None

        dept_name, members = org_chart_service.get_department_members("存在しない部署")

        assert dept_name is None
        assert members == []
