"""
lib/brain/learning_foundation/manager.py のテスト

対象:
- LearningManager（コマンド検出、一覧、削除、修正、統計）
- create_manager
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

from lib.brain.learning_foundation.manager import (
    LearningManager,
    create_manager,
)
from lib.brain.learning_foundation.models import Learning
from lib.brain.learning_foundation.constants import (
    AuthorityLevel,
    LearningCategory,
    LearningScope,
)


# =============================================================================
# テストデータ
# =============================================================================

TEST_ORG_ID = "org-test-123"
TEST_USER_ID = "user-123"
TEST_LEARNING_ID = str(uuid4())


def create_test_learning(
    learning_id: str = None,
    category: str = LearningCategory.FACT.value,
    taught_by: str = TEST_USER_ID,
    authority: str = AuthorityLevel.USER.value,
    description: str = "テスト学習",
) -> Learning:
    """テスト用Learning作成"""
    return Learning(
        id=learning_id or str(uuid4()),
        organization_id=TEST_ORG_ID,
        category=category,
        trigger_type="keyword",
        trigger_value="テスト",
        learned_content={"description": description, "type": category},
        learned_content_version=1,
        scope=LearningScope.GLOBAL.value,
        authority_level=authority,
        taught_by_account_id=taught_by,
        taught_by_name="テストユーザー",
        is_active=True,
        applied_count=5,
        success_count=3,
        failure_count=1,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


# =============================================================================
# LearningManager 初期化テスト
# =============================================================================


class TestLearningManagerInit:
    """初期化テスト"""

    def test_init_with_org_id(self):
        """組織IDで初期化"""
        manager = LearningManager(TEST_ORG_ID)
        assert manager.organization_id == TEST_ORG_ID
        assert manager.repository is not None

    def test_init_with_repository(self):
        """リポジトリ指定で初期化"""
        mock_repo = MagicMock()
        manager = LearningManager(TEST_ORG_ID, repository=mock_repo)
        assert manager.repository == mock_repo


# =============================================================================
# コマンド検出テスト
# =============================================================================


class TestIsListCommand:
    """is_list_command()のテスト"""

    @pytest.fixture
    def manager(self):
        return LearningManager(TEST_ORG_ID)

    @pytest.mark.parametrize("message", [
        "何覚えてる？",
        "覚えてることを教えて",
        "学習一覧を見せて",
        "覚えたことは何？",
        "学習内容を確認",
    ])
    def test_list_command_detected(self, manager, message):
        """一覧コマンドを検出"""
        assert manager.is_list_command(message) is True

    @pytest.mark.parametrize("message", [
        "おはよう",
        "タスクを追加して",
        "今日の予定は？",
    ])
    def test_non_list_command(self, manager, message):
        """一覧コマンドではない"""
        assert manager.is_list_command(message) is False


class TestIsDeleteCommand:
    """is_delete_command()のテスト"""

    @pytest.fixture
    def manager(self):
        return LearningManager(TEST_ORG_ID)

    @pytest.mark.parametrize("message", [
        "それを忘れて",
        "〇〇を忘れて",
        "学習を削除して",
        "覚えたことを消して",
    ])
    def test_delete_command_detected(self, manager, message):
        """削除コマンドを検出"""
        assert manager.is_delete_command(message) is True

    @pytest.mark.parametrize("message", [
        "おはよう",
        "タスクを追加して",
        "覚えてることを教えて",
    ])
    def test_non_delete_command(self, manager, message):
        """削除コマンドではない"""
        assert manager.is_delete_command(message) is False


# =============================================================================
# 一覧表示テスト
# =============================================================================


class TestListAll:
    """list_all()のテスト"""

    def test_list_all_returns_dict(self):
        """辞書を返す"""
        mock_repo = MagicMock()
        mock_repo.find_by_category = MagicMock(return_value=[])
        manager = LearningManager(TEST_ORG_ID, repository=mock_repo)
        conn = MagicMock()

        result = manager.list_all(conn)

        assert isinstance(result, dict)

    def test_list_all_with_learnings(self):
        """学習がある場合"""
        learning = create_test_learning(category=LearningCategory.FACT.value)
        mock_repo = MagicMock()
        mock_repo.find_by_category = MagicMock(
            side_effect=lambda conn, category, **kwargs:
                [learning] if category == LearningCategory.FACT.value else []
        )
        manager = LearningManager(TEST_ORG_ID, repository=mock_repo)
        conn = MagicMock()

        result = manager.list_all(conn)

        assert LearningCategory.FACT.value in result
        assert len(result[LearningCategory.FACT.value]) == 1

    def test_list_all_with_user_filter(self):
        """ユーザーフィルタ"""
        learning1 = create_test_learning(taught_by=TEST_USER_ID)
        learning2 = create_test_learning(taught_by="other-user")
        mock_repo = MagicMock()
        mock_repo.find_by_category = MagicMock(
            side_effect=lambda conn, category, **kwargs:
                [learning1, learning2] if category == LearningCategory.FACT.value else []
        )
        manager = LearningManager(TEST_ORG_ID, repository=mock_repo)
        conn = MagicMock()

        result = manager.list_all(conn, user_id=TEST_USER_ID)

        assert LearningCategory.FACT.value in result
        assert len(result[LearningCategory.FACT.value]) == 1
        assert result[LearningCategory.FACT.value][0].taught_by_account_id == TEST_USER_ID


class TestListByCategory:
    """list_by_category()のテスト"""

    def test_list_by_category(self):
        """カテゴリ別一覧"""
        learning = create_test_learning()
        mock_repo = MagicMock()
        mock_repo.find_by_category = MagicMock(return_value=[learning])
        manager = LearningManager(TEST_ORG_ID, repository=mock_repo)
        conn = MagicMock()

        result = manager.list_by_category(conn, LearningCategory.FACT.value)

        assert len(result) == 1

    def test_list_by_category_with_user_filter(self):
        """ユーザーフィルタ付き"""
        learning1 = create_test_learning(taught_by=TEST_USER_ID)
        learning2 = create_test_learning(taught_by="other-user")
        mock_repo = MagicMock()
        mock_repo.find_by_category = MagicMock(return_value=[learning1, learning2])
        manager = LearningManager(TEST_ORG_ID, repository=mock_repo)
        conn = MagicMock()

        result = manager.list_by_category(conn, LearningCategory.FACT.value, user_id=TEST_USER_ID)

        assert len(result) == 1


class TestListByUser:
    """list_by_user()のテスト"""

    def test_list_by_user(self):
        """ユーザー別一覧"""
        learning = create_test_learning(taught_by=TEST_USER_ID)
        mock_repo = MagicMock()
        mock_repo.find_by_user = MagicMock(return_value=[learning])
        manager = LearningManager(TEST_ORG_ID, repository=mock_repo)
        conn = MagicMock()

        result = manager.list_by_user(conn, TEST_USER_ID)

        assert len(result) == 1
        mock_repo.find_by_user.assert_called_once()


class TestFormatListResponse:
    """format_list_response()のテスト"""

    def test_empty_list(self):
        """空の場合"""
        manager = LearningManager(TEST_ORG_ID)
        result = manager.format_list_response({})
        assert "まだ何も覚えていない" in result

    def test_with_learnings(self):
        """学習がある場合"""
        manager = LearningManager(TEST_ORG_ID)
        learning = create_test_learning(description="テスト説明")
        learnings_by_category = {
            LearningCategory.FACT.value: [learning]
        }

        result = manager.format_list_response(learnings_by_category)

        assert "覚えていることの一覧" in result
        assert "テスト説明" in result
        assert "【事実・情報】" in result

    def test_ceo_authority_mark(self):
        """CEO権限マーク"""
        manager = LearningManager(TEST_ORG_ID)
        learning = create_test_learning(authority=AuthorityLevel.CEO.value)
        learnings_by_category = {
            LearningCategory.FACT.value: [learning]
        }

        result = manager.format_list_response(learnings_by_category)

        assert "（CEO）" in result

    def test_manager_authority_mark(self):
        """管理者権限マーク"""
        manager = LearningManager(TEST_ORG_ID)
        learning = create_test_learning(authority=AuthorityLevel.MANAGER.value)
        learnings_by_category = {
            LearningCategory.FACT.value: [learning]
        }

        result = manager.format_list_response(learnings_by_category)

        assert "（管理者）" in result


# =============================================================================
# 削除テスト
# =============================================================================


class TestDelete:
    """delete()のテスト"""

    def test_delete_not_found(self):
        """学習が見つからない"""
        mock_repo = MagicMock()
        mock_repo.find_by_id = MagicMock(return_value=None)
        manager = LearningManager(TEST_ORG_ID, repository=mock_repo)
        conn = MagicMock()

        success, message = manager.delete(conn, TEST_LEARNING_ID, TEST_USER_ID)

        assert success is False
        assert "覚えていない" in message

    def test_delete_no_permission(self):
        """権限なし"""
        learning = create_test_learning(
            taught_by="other-user",
            authority=AuthorityLevel.CEO.value
        )
        mock_repo = MagicMock()
        mock_repo.find_by_id = MagicMock(return_value=learning)
        manager = LearningManager(TEST_ORG_ID, repository=mock_repo)
        conn = MagicMock()

        success, message = manager.delete(
            conn, TEST_LEARNING_ID, TEST_USER_ID,
            requester_authority=AuthorityLevel.USER.value
        )

        assert success is False
        assert "権限" in message

    def test_delete_ceo_teaching_forbidden(self):
        """CEO教えは削除不可"""
        learning = create_test_learning(
            taught_by=TEST_USER_ID,
            authority=AuthorityLevel.CEO.value
        )
        mock_repo = MagicMock()
        mock_repo.find_by_id = MagicMock(return_value=learning)
        manager = LearningManager(TEST_ORG_ID, repository=mock_repo)
        conn = MagicMock()

        success, message = manager.delete(conn, TEST_LEARNING_ID, TEST_USER_ID)

        assert success is False
        assert "CEO教え" in message

    def test_delete_success(self):
        """削除成功"""
        learning = create_test_learning(taught_by=TEST_USER_ID)
        mock_repo = MagicMock()
        mock_repo.find_by_id = MagicMock(return_value=learning)
        mock_repo.delete = MagicMock(return_value=True)
        manager = LearningManager(TEST_ORG_ID, repository=mock_repo)
        conn = MagicMock()

        success, message = manager.delete(conn, TEST_LEARNING_ID, TEST_USER_ID)

        assert success is True
        assert "忘れた" in message or "削除" in message

    def test_delete_failed(self):
        """削除失敗"""
        learning = create_test_learning(taught_by=TEST_USER_ID)
        mock_repo = MagicMock()
        mock_repo.find_by_id = MagicMock(return_value=learning)
        mock_repo.delete = MagicMock(return_value=False)
        manager = LearningManager(TEST_ORG_ID, repository=mock_repo)
        conn = MagicMock()

        success, message = manager.delete(conn, TEST_LEARNING_ID, TEST_USER_ID)

        assert success is False


class TestDeleteByDescription:
    """delete_by_description()のテスト"""

    def test_not_found(self):
        """見つからない"""
        mock_repo = MagicMock()
        mock_repo.find_all = MagicMock(return_value=([], 0))
        manager = LearningManager(TEST_ORG_ID, repository=mock_repo)
        conn = MagicMock()

        success, message, learning = manager.delete_by_description(
            conn, "存在しない説明", TEST_USER_ID
        )

        assert success is False
        assert learning is None

    def test_multiple_matches(self):
        """複数マッチ"""
        learning1 = create_test_learning(description="テスト学習A")
        learning2 = create_test_learning(description="テスト学習B")
        mock_repo = MagicMock()
        mock_repo.find_all = MagicMock(return_value=([learning1, learning2], 2))
        manager = LearningManager(TEST_ORG_ID, repository=mock_repo)
        conn = MagicMock()

        success, message, learning = manager.delete_by_description(
            conn, "テスト", TEST_USER_ID
        )

        assert success is False
        assert "複数" in message
        assert learning is None

    def test_single_match_success(self):
        """1件マッチで削除成功"""
        learning = create_test_learning(taught_by=TEST_USER_ID, description="特定の学習")
        mock_repo = MagicMock()
        mock_repo.find_all = MagicMock(return_value=([learning], 1))
        mock_repo.find_by_id = MagicMock(return_value=learning)
        mock_repo.delete = MagicMock(return_value=True)
        manager = LearningManager(TEST_ORG_ID, repository=mock_repo)
        conn = MagicMock()

        success, message, deleted = manager.delete_by_description(
            conn, "特定", TEST_USER_ID
        )

        assert success is True
        assert deleted is not None


class TestCanDelete:
    """_can_delete()のテスト"""

    def test_can_delete_own_learning(self):
        """自分の学習は削除可能"""
        learning = create_test_learning(taught_by=TEST_USER_ID)
        manager = LearningManager(TEST_ORG_ID)

        result = manager._can_delete(learning, TEST_USER_ID, AuthorityLevel.USER.value)

        assert result is True

    def test_can_delete_with_higher_authority(self):
        """高い権限なら削除可能"""
        learning = create_test_learning(
            taught_by="other-user",
            authority=AuthorityLevel.USER.value
        )
        manager = LearningManager(TEST_ORG_ID)

        result = manager._can_delete(learning, TEST_USER_ID, AuthorityLevel.CEO.value)

        assert result is True

    def test_cannot_delete_higher_authority_learning(self):
        """低い権限では削除不可"""
        learning = create_test_learning(
            taught_by="other-user",
            authority=AuthorityLevel.CEO.value
        )
        manager = LearningManager(TEST_ORG_ID)

        result = manager._can_delete(learning, TEST_USER_ID, AuthorityLevel.USER.value)

        assert result is False


# =============================================================================
# 修正テスト
# =============================================================================


class TestUpdateContent:
    """update_content()のテスト"""

    def test_update_not_found(self):
        """学習が見つからない"""
        mock_repo = MagicMock()
        mock_repo.find_by_id = MagicMock(return_value=None)
        manager = LearningManager(TEST_ORG_ID, repository=mock_repo)
        conn = MagicMock()

        success, message = manager.update_content(
            conn, TEST_LEARNING_ID, {"description": "新しい説明"}, TEST_USER_ID
        )

        assert success is False
        assert "覚えていない" in message

    def test_update_no_permission(self):
        """権限なし"""
        learning = create_test_learning(
            taught_by="other-user",
            authority=AuthorityLevel.CEO.value
        )
        mock_repo = MagicMock()
        mock_repo.find_by_id = MagicMock(return_value=learning)
        manager = LearningManager(TEST_ORG_ID, repository=mock_repo)
        conn = MagicMock()

        success, message = manager.update_content(
            conn, TEST_LEARNING_ID, {"description": "新しい説明"}, TEST_USER_ID
        )

        assert success is False
        assert "権限" in message

    def test_update_ceo_teaching_requires_manager(self):
        """CEO教えの修正は管理者権限が必要"""
        learning = create_test_learning(
            taught_by=TEST_USER_ID,
            authority=AuthorityLevel.CEO.value
        )
        mock_repo = MagicMock()
        mock_repo.find_by_id = MagicMock(return_value=learning)
        manager = LearningManager(TEST_ORG_ID, repository=mock_repo)
        conn = MagicMock()

        success, message = manager.update_content(
            conn, TEST_LEARNING_ID, {"description": "新しい説明"},
            TEST_USER_ID, AuthorityLevel.USER.value
        )

        assert success is False
        assert "管理者権限" in message

    def test_update_success(self):
        """修正成功"""
        learning = create_test_learning(taught_by=TEST_USER_ID)
        mock_repo = MagicMock()
        mock_repo.find_by_id = MagicMock(return_value=learning)
        mock_repo.save = MagicMock(return_value="new-id")
        mock_repo.update_supersedes = MagicMock()
        manager = LearningManager(TEST_ORG_ID, repository=mock_repo)
        conn = MagicMock()

        success, message = manager.update_content(
            conn, TEST_LEARNING_ID, {"description": "新しい説明"}, TEST_USER_ID
        )

        assert success is True
        mock_repo.save.assert_called_once()
        mock_repo.update_supersedes.assert_called_once()


class TestCanModify:
    """_can_modify()のテスト"""

    def test_can_modify_own_learning(self):
        """自分の学習は修正可能"""
        learning = create_test_learning(taught_by=TEST_USER_ID)
        manager = LearningManager(TEST_ORG_ID)

        result = manager._can_modify(learning, TEST_USER_ID, AuthorityLevel.USER.value)

        assert result is True

    def test_can_modify_with_higher_authority(self):
        """高い権限なら修正可能"""
        learning = create_test_learning(
            taught_by="other-user",
            authority=AuthorityLevel.USER.value
        )
        manager = LearningManager(TEST_ORG_ID)

        result = manager._can_modify(learning, TEST_USER_ID, AuthorityLevel.CEO.value)

        assert result is True

    def test_cannot_modify_higher_authority_learning(self):
        """低い権限では修正不可"""
        learning = create_test_learning(
            taught_by="other-user",
            authority=AuthorityLevel.CEO.value
        )
        manager = LearningManager(TEST_ORG_ID)

        result = manager._can_modify(learning, TEST_USER_ID, AuthorityLevel.USER.value)

        assert result is False


# =============================================================================
# 統計テスト
# =============================================================================


class TestGetStatistics:
    """get_statistics()のテスト"""

    def test_empty_statistics(self):
        """空の統計"""
        mock_repo = MagicMock()
        mock_repo.find_all = MagicMock(return_value=([], 0))
        manager = LearningManager(TEST_ORG_ID, repository=mock_repo)
        conn = MagicMock()

        result = manager.get_statistics(conn)

        assert result["total_count"] == 0
        assert result["total_applies"] == 0
        assert result["avg_applies"] == 0

    def test_statistics_with_learnings(self):
        """学習がある場合の統計"""
        learning1 = create_test_learning(category=LearningCategory.FACT.value)
        learning2 = create_test_learning(category=LearningCategory.RULE.value)
        # applied_count属性を設定
        learning1.applied_count = 10
        learning2.applied_count = 5
        learning1.success_count = 8
        learning2.success_count = 4
        learning1.failure_count = 2
        learning2.failure_count = 1

        mock_repo = MagicMock()
        mock_repo.find_all = MagicMock(return_value=([learning1, learning2], 2))
        manager = LearningManager(TEST_ORG_ID, repository=mock_repo)
        conn = MagicMock()

        result = manager.get_statistics(conn)

        assert result["total_count"] == 2
        assert result["by_category"][LearningCategory.FACT.value] == 1
        assert result["by_category"][LearningCategory.RULE.value] == 1


class TestFormatStatisticsResponse:
    """format_statistics_response()のテスト"""

    def test_format_statistics(self):
        """統計のフォーマット"""
        manager = LearningManager(TEST_ORG_ID)
        statistics = {
            "total_count": 10,
            "total_applies": 100,
            "avg_applies": 10.0,
            "positive_feedback": 80,
            "negative_feedback": 20,
            "feedback_ratio": 0.8,
            "by_category": {
                LearningCategory.FACT.value: 5,
                LearningCategory.RULE.value: 3,
                LearningCategory.ALIAS.value: 2,
            },
            "by_authority": {
                AuthorityLevel.CEO.value: 2,
                AuthorityLevel.USER.value: 8,
            },
        }

        result = manager.format_statistics_response(statistics)

        assert "統計" in result
        assert "10件" in result
        assert "100回" in result
        assert "カテゴリ別" in result
        assert "権限レベル別" in result


# =============================================================================
# ファクトリ関数テスト
# =============================================================================


class TestCreateManager:
    """create_manager()のテスト"""

    def test_create_manager(self):
        """マネージャー作成"""
        manager = create_manager(TEST_ORG_ID)
        assert isinstance(manager, LearningManager)
        assert manager.organization_id == TEST_ORG_ID

    def test_create_manager_with_repository(self):
        """リポジトリ指定で作成"""
        mock_repo = MagicMock()
        manager = create_manager(TEST_ORG_ID, repository=mock_repo)
        assert manager.repository == mock_repo
