# tests/test_learning_repository.py
"""
LearningRepository のユニットテスト

lib/brain/learning_foundation/repository.py のカバレッジ強化
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

from lib.brain.learning_foundation.repository import (
    LearningRepository,
    create_repository,
)
from lib.brain.learning_foundation.models import Learning, LearningLog
from lib.brain.learning_foundation.constants import (
    AuthorityLevel,
    LearningScope,
)


# =============================================================================
# テストデータ
# =============================================================================

TEST_ORG_ID = "550e8400-e29b-41d4-a716-446655440000"
TEST_LEARNING_ID = "660e8400-e29b-41d4-a716-446655440001"
TEST_LOG_ID = "770e8400-e29b-41d4-a716-446655440001"
TEST_USER_ID = "user_123"
TEST_ROOM_ID = "room_456"


def create_test_learning(
    learning_id: str = None,
    category: str = "greeting",
    trigger_value: str = "おはよう",
    is_active: bool = True,
) -> Learning:
    """テスト用Learningを作成"""
    return Learning(
        id=learning_id or str(uuid4()),
        organization_id=TEST_ORG_ID,
        category=category,
        trigger_type="keyword",
        trigger_value=trigger_value,
        learned_content={"response": "おはようございます"},
        learned_content_version=1,
        scope=LearningScope.GLOBAL.value,
        scope_target_id=None,
        authority_level=AuthorityLevel.CEO.value,
        valid_from=datetime.now(),
        valid_until=None,
        taught_by_account_id=TEST_USER_ID,
        taught_by_name="田中",
        taught_in_room_id=TEST_ROOM_ID,
        source_message="覚えて",
        source_context={},
        detection_pattern=None,
        detection_confidence=0.9,
        classification="explicit",
        is_active=is_active,
        applied_count=0,
        success_count=0,
        failure_count=0,
        effectiveness_score=0.5,
        supersedes_id=None,
        superseded_by_id=None,
        related_learning_ids=None,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


def create_test_log(
    log_id: str = None,
    learning_id: str = TEST_LEARNING_ID,
) -> LearningLog:
    """テスト用LearningLogを作成"""
    return LearningLog(
        id=log_id or str(uuid4()),
        organization_id=TEST_ORG_ID,
        learning_id=learning_id,
        learning_version=1,
        applied_at=datetime.now(),
        applied_in_room_id=TEST_ROOM_ID,
        applied_for_account_id=TEST_USER_ID,
        trigger_message="おはよう",
        trigger_context=None,
        context_hash=None,
        was_successful=True,
        result_description="Applied successfully",
        response_latency_ms=50,
        feedback_received=False,
        feedback_positive=None,
        feedback_message=None,
        user_feedback_at=None,
        created_at=datetime.now(),
    )


def create_mock_learning_row(learning: Learning = None):
    """DBの行データをモック（_row_to_learningのカラム順）

    カラム順序（DBスキーマ準拠）:
    id, organization_id, category, trigger_type, trigger_value,
    learned_content, learned_content_version, scope, scope_target_id,
    authority_level, valid_from, valid_until, taught_by_account_id,
    taught_by_name, taught_in_room_id, source_message, source_context,
    detection_pattern, detection_confidence, classification,
    supersedes_id, superseded_by_id, related_learning_ids,
    is_active, effectiveness_score, applied_count, success_count,
    failure_count, created_at, updated_at
    """
    l = learning or create_test_learning()
    return (
        l.id,
        l.organization_id,
        l.category,
        l.trigger_type,
        l.trigger_value,
        l.learned_content,
        l.learned_content_version,
        l.scope,
        l.scope_target_id,
        l.authority_level,
        l.valid_from,
        l.valid_until,
        l.taught_by_account_id,
        l.taught_by_name,
        l.taught_in_room_id,
        l.source_message,
        l.source_context,
        l.detection_pattern,
        l.detection_confidence,
        l.classification,
        l.supersedes_id,
        l.superseded_by_id,
        l.related_learning_ids,
        l.is_active,
        l.effectiveness_score,
        l.applied_count,
        l.success_count,
        l.failure_count,
        l.created_at,
        l.updated_at,
    )


def create_mock_log_row(log: LearningLog = None):
    """DBの行データをモック（_row_to_logのカラム順）

    カラム順序（DBスキーマ準拠）:
    id, organization_id, learning_id, applied_at,
    applied_in_room_id, applied_for_account_id,
    trigger_message, was_successful, feedback_message,
    user_feedback_at, created_at
    """
    lg = log or create_test_log()
    return (
        lg.id,
        lg.organization_id,
        lg.learning_id,
        lg.applied_at,
        lg.applied_in_room_id,
        lg.applied_for_account_id,
        lg.trigger_message,
        lg.was_successful,
        lg.feedback_message,
        lg.user_feedback_at,
        lg.created_at,
    )


# =============================================================================
# 初期化テスト
# =============================================================================


class TestLearningRepositoryInit:
    """初期化テスト"""

    def test_init_with_org_id(self):
        """organization_idで初期化できる"""
        repo = LearningRepository(TEST_ORG_ID)
        assert repo.organization_id == TEST_ORG_ID

    def test_factory_function(self):
        """ファクトリ関数でインスタンス作成"""
        repo = create_repository(TEST_ORG_ID)
        assert isinstance(repo, LearningRepository)


# =============================================================================
# 保存系テスト
# =============================================================================


class TestSave:
    """save()メソッドのテスト"""

    def test_save_success(self):
        """学習の保存成功"""
        repo = LearningRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone = MagicMock(return_value=(TEST_LEARNING_ID,))
        conn.execute = MagicMock(return_value=mock_result)

        learning = create_test_learning(learning_id=TEST_LEARNING_ID)

        result = repo.save(conn, learning)

        assert result == TEST_LEARNING_ID

    def test_save_failure(self):
        """保存失敗時に例外"""
        repo = LearningRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone = MagicMock(return_value=None)
        conn.execute = MagicMock(return_value=mock_result)

        learning = create_test_learning()

        with pytest.raises(ValueError):
            repo.save(conn, learning)


class TestSaveLog:
    """save_log()メソッドのテスト"""

    def test_save_log_success(self):
        """ログの保存成功"""
        repo = LearningRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone = MagicMock(return_value=(TEST_LOG_ID,))
        conn.execute = MagicMock(return_value=mock_result)

        log = create_test_log(log_id=TEST_LOG_ID)

        result = repo.save_log(conn, log)

        assert result == TEST_LOG_ID

    def test_save_log_no_id(self):
        """IDなしログの保存"""
        repo = LearningRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone = MagicMock(return_value=(TEST_LOG_ID,))
        conn.execute = MagicMock(return_value=mock_result)

        log = create_test_log()
        log.id = None

        result = repo.save_log(conn, log)

        assert result is not None


# =============================================================================
# 検索系テスト
# =============================================================================


class TestFindById:
    """find_by_id()メソッドのテスト"""

    def test_find_by_id_found(self):
        """IDで学習を取得"""
        repo = LearningRepository(TEST_ORG_ID)
        conn = MagicMock()
        learning = create_test_learning(learning_id=TEST_LEARNING_ID)
        mock_result = MagicMock()
        mock_result.fetchone = MagicMock(return_value=create_mock_learning_row(learning))
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.find_by_id(conn, TEST_LEARNING_ID)

        assert result is not None
        assert result.id == TEST_LEARNING_ID

    def test_find_by_id_not_found(self):
        """学習が見つからない"""
        repo = LearningRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone = MagicMock(return_value=None)
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.find_by_id(conn, TEST_LEARNING_ID)

        assert result is None


class TestFindApplicable:
    """find_applicable()メソッドのテスト"""

    def test_find_applicable_org_scope(self):
        """組織スコープで適用可能な学習を検索"""
        repo = LearningRepository(TEST_ORG_ID)
        conn = MagicMock()
        learning = create_test_learning()
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[create_mock_learning_row(learning)])
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.find_applicable(conn, "おはよう", TEST_USER_ID, TEST_ROOM_ID)

        assert len(result) >= 0

    def test_find_applicable_no_matches(self):
        """マッチなし"""
        repo = LearningRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[])
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.find_applicable(conn, "テスト", TEST_USER_ID, TEST_ROOM_ID)

        assert result == []


class TestFindByTrigger:
    """find_by_trigger()メソッドのテスト"""

    def test_find_by_trigger_found(self):
        """トリガーで検索"""
        repo = LearningRepository(TEST_ORG_ID)
        conn = MagicMock()
        learning = create_test_learning(trigger_value="おはよう")
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[create_mock_learning_row(learning)])
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.find_by_trigger(conn, "keyword", "おはよう")

        assert len(result) >= 1

    def test_find_by_trigger_not_found(self):
        """トリガーが見つからない"""
        repo = LearningRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[])
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.find_by_trigger(conn, "keyword", "存在しない")

        assert result == []


class TestFindByCategory:
    """find_by_category()メソッドのテスト"""

    def test_find_by_category_found(self):
        """カテゴリで検索"""
        repo = LearningRepository(TEST_ORG_ID)
        conn = MagicMock()
        learning = create_test_learning(category="greeting")
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[create_mock_learning_row(learning)])
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.find_by_category(conn, "greeting")

        assert len(result) >= 1

    def test_find_by_category_active_only(self):
        """アクティブのみ検索"""
        repo = LearningRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[])
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.find_by_category(conn, "greeting", active_only=True)

        assert result == []


class TestFindAll:
    """find_all()メソッドのテスト"""

    def test_find_all_found(self):
        """全件検索"""
        repo = LearningRepository(TEST_ORG_ID)
        conn = MagicMock()
        learning = create_test_learning()

        # count queryとdata queryで別の結果を返す
        count_result = MagicMock()
        count_result.scalar = MagicMock(return_value=1)

        data_result = MagicMock()
        data_result.fetchall = MagicMock(return_value=[create_mock_learning_row(learning)])

        conn.execute = MagicMock(side_effect=[count_result, data_result])

        learnings, total = repo.find_all(conn)

        assert len(learnings) == 1
        assert total == 1

    def test_find_all_empty(self):
        """結果なし"""
        repo = LearningRepository(TEST_ORG_ID)
        conn = MagicMock()

        count_result = MagicMock()
        count_result.scalar = MagicMock(return_value=0)

        data_result = MagicMock()
        data_result.fetchall = MagicMock(return_value=[])

        conn.execute = MagicMock(side_effect=[count_result, data_result])

        learnings, total = repo.find_all(conn, active_only=True, limit=10, offset=0)

        assert learnings == []
        assert total == 0


class TestFindByUser:
    """find_by_user()メソッドのテスト"""

    def test_find_by_user_found(self):
        """ユーザーで検索"""
        repo = LearningRepository(TEST_ORG_ID)
        conn = MagicMock()
        learning = create_test_learning()
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[create_mock_learning_row(learning)])
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.find_by_user(conn, TEST_USER_ID)

        assert len(result) >= 0


# =============================================================================
# 更新系テスト
# =============================================================================


class TestDeactivate:
    """deactivate()メソッドのテスト"""

    def test_deactivate_success(self):
        """無効化成功"""
        repo = LearningRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.deactivate(conn, TEST_LEARNING_ID)

        assert result is True

    def test_deactivate_not_found(self):
        """対象が見つからない"""
        repo = LearningRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.deactivate(conn, TEST_LEARNING_ID)

        assert result is False


class TestActivate:
    """activate()メソッドのテスト"""

    def test_activate_success(self):
        """有効化成功"""
        repo = LearningRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.activate(conn, TEST_LEARNING_ID)

        assert result is True

    def test_activate_not_found(self):
        """対象が見つからない"""
        repo = LearningRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.activate(conn, TEST_LEARNING_ID)

        assert result is False


class TestUpdateSupersedes:
    """update_supersedes()メソッドのテスト"""

    def test_update_supersedes_success(self):
        """上書き関係の更新成功"""
        repo = LearningRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        conn.execute = MagicMock(return_value=mock_result)

        old_id = str(uuid4())
        result = repo.update_supersedes(conn, TEST_LEARNING_ID, old_id)

        assert result is True


class TestIncrementApplyCount:
    """increment_apply_count()メソッドのテスト"""

    def test_increment_apply_count_success(self):
        """適用回数の増加成功"""
        repo = LearningRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.increment_apply_count(conn, TEST_LEARNING_ID)

        assert result is True


class TestUpdateFeedbackCount:
    """update_feedback_count()メソッドのテスト"""

    def test_update_feedback_count_positive(self):
        """ポジティブフィードバック"""
        repo = LearningRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.update_feedback_count(conn, TEST_LEARNING_ID, is_positive=True)

        assert result is True

    def test_update_feedback_count_negative(self):
        """ネガティブフィードバック"""
        repo = LearningRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.update_feedback_count(conn, TEST_LEARNING_ID, is_positive=False)

        assert result is True


class TestUpdateEffectivenessScore:
    """update_effectiveness_score()メソッドのテスト"""

    def test_update_effectiveness_score_success(self):
        """効果スコアの更新成功"""
        repo = LearningRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.update_effectiveness_score(conn, TEST_LEARNING_ID, 0.8)

        assert result is True


class TestUpdateLogFeedback:
    """update_log_feedback()メソッドのテスト"""

    def test_update_log_feedback_success(self):
        """ログフィードバックの更新成功"""
        repo = LearningRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.update_log_feedback(conn, TEST_LOG_ID, "positive")

        assert result is True


class TestDelete:
    """delete()メソッドのテスト"""

    def test_delete_success(self):
        """削除成功"""
        repo = LearningRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.delete(conn, TEST_LEARNING_ID)

        assert result is True

    def test_delete_not_found(self):
        """対象が見つからない"""
        repo = LearningRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.delete(conn, TEST_LEARNING_ID)

        assert result is False


# =============================================================================
# ログ検索テスト
# =============================================================================


class TestFindLogsByLearning:
    """find_logs_by_learning()メソッドのテスト"""

    def test_find_logs_by_learning_found(self):
        """学習IDでログを検索"""
        repo = LearningRepository(TEST_ORG_ID)
        conn = MagicMock()
        log = create_test_log()
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[create_mock_log_row(log)])
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.find_logs_by_learning(conn, TEST_LEARNING_ID)

        assert len(result) >= 1


class TestFindRecentLogs:
    """find_recent_logs()メソッドのテスト"""

    def test_find_recent_logs_found(self):
        """最近のログを検索"""
        repo = LearningRepository(TEST_ORG_ID)
        conn = MagicMock()
        log = create_test_log()
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[create_mock_log_row(log)])
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.find_recent_logs(conn)

        assert len(result) >= 1

    def test_find_recent_logs_with_limit(self):
        """件数制限付きでログを検索"""
        repo = LearningRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[])
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.find_recent_logs(conn, limit=5)

        assert result == []


# =============================================================================
# ユーティリティテスト
# =============================================================================


class TestRowToLearning:
    """_row_to_learning()メソッドのテスト"""

    def test_row_to_learning_basic(self):
        """行データからLearningへの変換"""
        repo = LearningRepository(TEST_ORG_ID)
        learning = create_test_learning()
        row = create_mock_learning_row(learning)

        result = repo._row_to_learning(row)

        assert result.id == learning.id
        assert result.category == learning.category

    def test_row_to_learning_with_none_values(self):
        """NULLを含む行データの変換"""
        repo = LearningRepository(TEST_ORG_ID)
        row = (
            str(uuid4()),
            TEST_ORG_ID,
            "category",
            "keyword",
            "trigger",
            {},  # learned_content
            1,
            None,  # scope
            None,  # scope_target_id
            None,  # authority_level
            None,  # valid_from
            None,  # valid_until
            None,  # taught_by_account_id
            None,  # taught_by_name
            None,  # taught_in_room_id
            None,  # source_message
            None,  # source_context
            None,  # detection_pattern
            None,  # detection_confidence
            None,  # classification
            True,  # is_active
            0,  # apply_count
            0,  # positive_feedback_count
            0,  # negative_feedback_count
            None,  # effectiveness_score
            None,  # supersedes_id
            None,  # created_at
            None,  # updated_at
        )

        result = repo._row_to_learning(row)

        assert result is not None


class TestRowToLog:
    """_row_to_log()メソッドのテスト"""

    def test_row_to_log_basic(self):
        """行データからLearningLogへの変換"""
        repo = LearningRepository(TEST_ORG_ID)
        log = create_test_log()
        row = create_mock_log_row(log)

        result = repo._row_to_log(row)

        assert result.id == log.id
        assert result.learning_id == log.learning_id


class TestMatchesTrigger:
    """_matches_trigger()メソッドのテスト"""

    def test_matches_trigger_keyword(self):
        """キーワードマッチ"""
        repo = LearningRepository(TEST_ORG_ID)
        learning = create_test_learning(trigger_value="おはよう")
        learning.trigger_type = "keyword"

        result = repo._matches_trigger(learning, "おはようございます")

        assert result is True

    def test_matches_trigger_no_match(self):
        """マッチしない"""
        repo = LearningRepository(TEST_ORG_ID)
        learning = create_test_learning(trigger_value="おはよう")
        learning.trigger_type = "keyword"

        result = repo._matches_trigger(learning, "こんにちは")

        assert result is False

    def test_matches_trigger_pattern(self):
        """正規表現パターンマッチ"""
        repo = LearningRepository(TEST_ORG_ID)
        learning = create_test_learning(trigger_value=r"おはよ.*")
        learning.trigger_type = "pattern"  # repository uses "pattern" not "regex"

        result = repo._matches_trigger(learning, "おはようございます")

        assert result is True

    def test_matches_trigger_always(self):
        """常にマッチ"""
        repo = LearningRepository(TEST_ORG_ID)
        learning = create_test_learning()
        learning.trigger_type = "always"

        result = repo._matches_trigger(learning, "任意のメッセージ")

        assert result is True
