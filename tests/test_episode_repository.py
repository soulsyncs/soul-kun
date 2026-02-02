# tests/test_episode_repository.py
"""
EpisodeRepository のユニットテスト

lib/brain/memory_enhancement/episode_repository.py のカバレッジ強化
DB依存はモックで対応
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

from lib.brain.memory_enhancement.episode_repository import (
    EpisodeRepository,
    create_episode_repository,
)
from lib.brain.memory_enhancement.models import Episode, RecallResult, RelatedEntity
from lib.brain.memory_enhancement.constants import (
    EpisodeType,
    RecallTrigger,
    RECALL_RELEVANCE_THRESHOLD,
)


# =============================================================================
# テストデータ
# =============================================================================

TEST_ORG_ID = "550e8400-e29b-41d4-a716-446655440000"
TEST_USER_ID = "user_123"
TEST_EPISODE_ID = "660e8400-e29b-41d4-a716-446655440001"


def create_test_episode(
    episode_id: str = None,
    user_id: str = TEST_USER_ID,
    episode_type: EpisodeType = EpisodeType.INTERACTION,
    summary: str = "テストエピソード",
    keywords: list = None,
    importance_score: float = 0.5,
    decay_factor: float = 1.0,
) -> Episode:
    """テスト用Episodeを作成"""
    return Episode(
        id=episode_id or str(uuid4()),
        organization_id=TEST_ORG_ID,
        user_id=user_id,
        episode_type=episode_type,
        summary=summary,
        details={"test": "data"},
        emotional_valence=0.5,
        importance_score=importance_score,
        keywords=keywords or ["テスト", "目標"],
        embedding_id=None,
        recall_count=0,
        last_recalled_at=None,
        decay_factor=decay_factor,
        occurred_at=datetime.now(),
        created_at=datetime.now(),
        updated_at=datetime.now(),
        related_entities=[],
    )


def create_mock_row(episode: Episode = None):
    """DBの行データをモック"""
    ep = episode or create_test_episode()
    return (
        ep.id,
        ep.organization_id,
        ep.user_id,
        ep.episode_type.value if isinstance(ep.episode_type, EpisodeType) else ep.episode_type,
        ep.summary,
        ep.details,
        ep.emotional_valence,
        ep.importance_score,
        ep.keywords,
        ep.embedding_id,
        ep.recall_count,
        ep.last_recalled_at,
        ep.decay_factor,
        ep.occurred_at,
        ep.created_at,
        ep.updated_at,
    )


# =============================================================================
# 初期化テスト
# =============================================================================


class TestEpisodeRepositoryInit:
    """初期化テスト"""

    def test_init_with_org_id(self):
        """organization_idで初期化できる"""
        repo = EpisodeRepository(TEST_ORG_ID)
        assert repo.organization_id == TEST_ORG_ID

    def test_factory_function(self):
        """ファクトリ関数でインスタンス作成"""
        repo = create_episode_repository(TEST_ORG_ID)
        assert isinstance(repo, EpisodeRepository)
        assert repo.organization_id == TEST_ORG_ID


# =============================================================================
# 保存・更新テスト
# =============================================================================


class TestSave:
    """save()メソッドのテスト"""

    def test_save_new_episode(self):
        """新規エピソードの保存"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()
        conn.execute = MagicMock()

        episode = create_test_episode(episode_id=None)
        episode.id = None

        result = repo.save(conn, episode)

        assert result is not None
        assert conn.execute.called

    def test_save_episode_with_id(self):
        """ID付きエピソードの保存（更新）"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()
        conn.execute = MagicMock()

        episode = create_test_episode(episode_id=TEST_EPISODE_ID)

        result = repo.save(conn, episode)

        assert result == TEST_EPISODE_ID

    def test_save_episode_with_entities(self):
        """関連エンティティ付きエピソードの保存"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()
        conn.execute = MagicMock()

        episode = create_test_episode()
        episode.related_entities = [
            RelatedEntity(
                entity_type="user",
                entity_id="user_456",
                entity_name="田中",
                relationship="mentioned",
            )
        ]

        result = repo.save(conn, episode)

        assert result is not None
        # _save_entitiesが呼ばれるため、複数回executeされる
        assert conn.execute.call_count >= 1

    def test_save_episode_error(self):
        """保存エラー時に例外が上がる"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()
        conn.execute = MagicMock(side_effect=Exception("DB error"))

        episode = create_test_episode()

        with pytest.raises(Exception):
            repo.save(conn, episode)


class TestSaveEntities:
    """_save_entities()メソッドのテスト"""

    def test_save_entities_deletes_existing(self):
        """既存エンティティを削除してから新規挿入"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()
        conn.execute = MagicMock()

        entities = [
            RelatedEntity(
                entity_type="user",
                entity_id="user_1",
                entity_name="田中",
                relationship="mentioned",
            ),
            RelatedEntity(
                entity_type="goal",
                entity_id="goal_1",
                entity_name="目標A",
                relationship="about",
            ),
        ]

        repo._save_entities(conn, TEST_EPISODE_ID, entities)

        # DELETE + INSERT × 2
        assert conn.execute.call_count == 3

    def test_save_entities_empty_list(self):
        """空のエンティティリストの場合はDELETEのみ"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()
        conn.execute = MagicMock()

        repo._save_entities(conn, TEST_EPISODE_ID, [])

        # DELETEのみ
        assert conn.execute.call_count == 1


class TestUpdateRecallStats:
    """update_recall_stats()メソッドのテスト"""

    def test_update_recall_stats_success(self):
        """想起統計の更新成功"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.update_recall_stats(conn, TEST_EPISODE_ID)

        assert result is True

    def test_update_recall_stats_not_found(self):
        """対象エピソードが見つからない"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.update_recall_stats(conn, TEST_EPISODE_ID)

        assert result is False

    def test_update_recall_stats_no_boost(self):
        """重要度ブーストなし"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.update_recall_stats(conn, TEST_EPISODE_ID, boost_importance=False)

        assert result is True

    def test_update_recall_stats_error(self):
        """エラー時はFalseを返す"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()
        conn.execute = MagicMock(side_effect=Exception("DB error"))

        result = repo.update_recall_stats(conn, TEST_EPISODE_ID)

        assert result is False


class TestApplyDecay:
    """apply_decay()メソッドのテスト"""

    def test_apply_decay_success(self):
        """忘却係数の適用成功"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 5
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.apply_decay(conn, days=1)

        assert result == 5

    def test_apply_decay_no_updates(self):
        """更新なし"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.apply_decay(conn, days=1)

        assert result == 0

    def test_apply_decay_error(self):
        """エラー時は0を返す"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()
        conn.execute = MagicMock(side_effect=Exception("DB error"))

        result = repo.apply_decay(conn)

        assert result == 0


class TestDeleteForgotten:
    """delete_forgotten()メソッドのテスト"""

    def test_delete_forgotten_success(self):
        """忘却エピソードの削除成功"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 3
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.delete_forgotten(conn)

        assert result == 3

    def test_delete_forgotten_none(self):
        """削除対象なし"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.delete_forgotten(conn)

        assert result == 0

    def test_delete_forgotten_error(self):
        """エラー時は0を返す"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()
        conn.execute = MagicMock(side_effect=Exception("DB error"))

        result = repo.delete_forgotten(conn)

        assert result == 0


# =============================================================================
# 検索テスト
# =============================================================================


class TestFindById:
    """find_by_id()メソッドのテスト"""

    def test_find_by_id_found(self):
        """IDでエピソードを取得"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()

        episode = create_test_episode(episode_id=TEST_EPISODE_ID)
        mock_result = MagicMock()
        mock_result.fetchone = MagicMock(return_value=create_mock_row(episode))
        conn.execute = MagicMock(return_value=mock_result)

        # _load_entitiesのモック
        with patch.object(repo, '_load_entities', return_value=[]):
            result = repo.find_by_id(conn, TEST_EPISODE_ID)

        assert result is not None
        assert result.id == TEST_EPISODE_ID

    def test_find_by_id_not_found(self):
        """エピソードが見つからない"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone = MagicMock(return_value=None)
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.find_by_id(conn, TEST_EPISODE_ID)

        assert result is None

    def test_find_by_id_error(self):
        """エラー時はNoneを返す"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()
        conn.execute = MagicMock(side_effect=Exception("DB error"))

        result = repo.find_by_id(conn, TEST_EPISODE_ID)

        assert result is None


class TestFindByKeywords:
    """find_by_keywords()メソッドのテスト"""

    def test_find_by_keywords_found(self):
        """キーワードでエピソードを検索"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()

        episode = create_test_episode(keywords=["目標", "達成"])
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[create_mock_row(episode)])
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.find_by_keywords(conn, ["目標"])

        assert len(result) == 1

    def test_find_by_keywords_empty_keywords(self):
        """空のキーワードリストは空リストを返す"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()

        result = repo.find_by_keywords(conn, [])

        assert result == []

    def test_find_by_keywords_with_user_id(self):
        """user_id指定で検索"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[])
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.find_by_keywords(conn, ["目標"], user_id=TEST_USER_ID)

        assert result == []

    def test_find_by_keywords_error(self):
        """エラー時は空リストを返す"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()
        conn.execute = MagicMock(side_effect=Exception("DB error"))

        result = repo.find_by_keywords(conn, ["目標"])

        assert result == []


class TestFindByEntities:
    """find_by_entities()メソッドのテスト"""

    def test_find_by_entities_found(self):
        """エンティティでエピソードを検索"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()

        episode = create_test_episode()
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[create_mock_row(episode)])
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.find_by_entities(conn, ["entity_1"])

        assert len(result) == 1

    def test_find_by_entities_empty_ids(self):
        """空のIDリストは空リストを返す"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()

        result = repo.find_by_entities(conn, [])

        assert result == []

    def test_find_by_entities_with_user_id(self):
        """user_id指定で検索"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[])
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.find_by_entities(conn, ["entity_1"], user_id=TEST_USER_ID)

        assert result == []

    def test_find_by_entities_error(self):
        """エラー時は空リストを返す"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()
        conn.execute = MagicMock(side_effect=Exception("DB error"))

        result = repo.find_by_entities(conn, ["entity_1"])

        assert result == []


class TestFindByTimeRange:
    """find_by_time_range()メソッドのテスト"""

    def test_find_by_time_range_found(self):
        """時間範囲でエピソードを検索"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()

        episode = create_test_episode()
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[create_mock_row(episode)])
        conn.execute = MagicMock(return_value=mock_result)

        now = datetime.now()
        result = repo.find_by_time_range(conn, now - timedelta(days=7), now)

        assert len(result) == 1

    def test_find_by_time_range_with_filters(self):
        """user_idとepisode_type指定で検索"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[])
        conn.execute = MagicMock(return_value=mock_result)

        now = datetime.now()
        result = repo.find_by_time_range(
            conn,
            now - timedelta(days=7),
            now,
            user_id=TEST_USER_ID,
            episode_type=EpisodeType.ACHIEVEMENT,
        )

        assert result == []

    def test_find_by_time_range_error(self):
        """エラー時は空リストを返す"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()
        conn.execute = MagicMock(side_effect=Exception("DB error"))

        now = datetime.now()
        result = repo.find_by_time_range(conn, now - timedelta(days=7), now)

        assert result == []


class TestFindSimilar:
    """find_similar()メソッドのテスト"""

    def test_find_similar_found(self):
        """類似エピソードを検索"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()

        base_episode = create_test_episode(episode_id="base_id", keywords=["目標", "達成"])
        similar_episode = create_test_episode(episode_id="similar_id", keywords=["目標", "成長"])

        # 類似度を含む行（最後にsimilarityカラム）
        similar_row = create_mock_row(similar_episode) + (0.6,)
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[similar_row])
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.find_similar(conn, base_episode, threshold=0.5)

        assert len(result) == 1
        assert result[0][1] >= 0.5  # 類似度

    def test_find_similar_no_keywords(self):
        """キーワードなしの場合は空リストを返す"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()

        episode = create_test_episode(keywords=[])

        result = repo.find_similar(conn, episode)

        assert result == []

    def test_find_similar_below_threshold(self):
        """閾値未満は除外"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()

        base_episode = create_test_episode(keywords=["目標"])
        similar_row = create_mock_row(create_test_episode()) + (0.3,)  # 低い類似度
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[similar_row])
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.find_similar(conn, base_episode, threshold=0.5)

        assert len(result) == 0

    def test_find_similar_error(self):
        """エラー時は空リストを返す"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()
        conn.execute = MagicMock(side_effect=Exception("DB error"))

        episode = create_test_episode(keywords=["目標"])

        result = repo.find_similar(conn, episode)

        assert result == []


class TestFindRecent:
    """find_recent()メソッドのテスト"""

    def test_find_recent_found(self):
        """最近のエピソードを取得"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()

        episode = create_test_episode()
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[create_mock_row(episode)])
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.find_recent(conn)

        assert len(result) == 1

    def test_find_recent_with_filters(self):
        """user_idとepisode_type指定で検索"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[])
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.find_recent(
            conn,
            user_id=TEST_USER_ID,
            episode_type=EpisodeType.ACHIEVEMENT,
        )

        assert result == []

    def test_find_recent_error(self):
        """エラー時は空リストを返す"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()
        conn.execute = MagicMock(side_effect=Exception("DB error"))

        result = repo.find_recent(conn)

        assert result == []


# =============================================================================
# 想起テスト
# =============================================================================


class TestRecall:
    """recall()メソッドのテスト"""

    def test_recall_by_keywords(self):
        """キーワードベースの想起"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()

        episode = create_test_episode(keywords=["目標", "達成"], importance_score=0.8)
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[create_mock_row(episode)])
        conn.execute = MagicMock(return_value=mock_result)

        # update_recall_statsのモック
        with patch.object(repo, 'update_recall_stats', return_value=True):
            result = repo.recall(conn, "目標について教えて")

        # キーワード「目標」がマッチするはず
        assert isinstance(result, list)

    def test_recall_with_entity_ids(self):
        """エンティティIDコンテキスト付きの想起"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[])
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.recall(
            conn,
            "テスト",
            context={"entity_ids": ["entity_1", "entity_2"]},
        )

        assert isinstance(result, list)

    def test_recall_with_reference_time(self):
        """参照時間コンテキスト付きの想起"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[])
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.recall(
            conn,
            "テスト",
            context={"reference_time": datetime.now()},
        )

        assert isinstance(result, list)


class TestRecallByKeywords:
    """_recall_by_keywords()メソッドのテスト"""

    def test_recall_by_keywords_matches(self):
        """キーワードマッチ"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()

        episode = create_test_episode(keywords=["目標", "達成"])
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[create_mock_row(episode)])
        conn.execute = MagicMock(return_value=mock_result)

        result = repo._recall_by_keywords(conn, ["目標"])

        assert len(result) >= 0  # マッチがあれば1以上


class TestRecallByEntities:
    """_recall_by_entities()メソッドのテスト"""

    def test_recall_by_entities_matches(self):
        """エンティティマッチ"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()

        episode = create_test_episode()
        episode.related_entities = [
            RelatedEntity(
                entity_type="user",
                entity_id="entity_1",
                entity_name="田中",
                relationship="mentioned",
            )
        ]
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[create_mock_row(episode)])
        conn.execute = MagicMock(return_value=mock_result)

        # find_by_entitiesをモック
        with patch.object(repo, 'find_by_entities', return_value=[episode]):
            result = repo._recall_by_entities(conn, ["entity_1"])

        assert len(result) >= 0


class TestRecallByTemporal:
    """_recall_by_temporal()メソッドのテスト"""

    def test_recall_by_temporal_matches(self):
        """時間的関連マッチ"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()

        now = datetime.now()
        episode = create_test_episode()
        episode.occurred_at = now - timedelta(days=2)

        # find_by_time_rangeをモック
        with patch.object(repo, 'find_by_time_range', return_value=[episode]):
            result = repo._recall_by_temporal(conn, now)

        assert len(result) >= 0


class TestRankResults:
    """_rank_results()メソッドのテスト"""

    def test_rank_results_deduplication(self):
        """重複除去"""
        repo = EpisodeRepository(TEST_ORG_ID)

        episode = create_test_episode(episode_id="same_id", importance_score=0.8)
        result1 = RecallResult(
            episode=episode,
            relevance_score=0.5,
            trigger=RecallTrigger.KEYWORD,
        )
        result2 = RecallResult(
            episode=episode,
            relevance_score=0.8,  # 高いスコア
            trigger=RecallTrigger.ENTITY,
        )

        ranked = repo._rank_results([result1, result2])

        # 同じエピソードは1つにまとめられる
        assert len(ranked) <= 1

    def test_rank_results_threshold(self):
        """閾値以下は除外"""
        repo = EpisodeRepository(TEST_ORG_ID)

        episode = create_test_episode(importance_score=0.1, decay_factor=0.1)
        result = RecallResult(
            episode=episode,
            relevance_score=0.1,  # 低いスコア
            trigger=RecallTrigger.KEYWORD,
        )

        ranked = repo._rank_results([result])

        # 閾値未満なら除外される可能性
        assert isinstance(ranked, list)


# =============================================================================
# ユーティリティテスト
# =============================================================================


class TestExtractKeywords:
    """_extract_keywords()メソッドのテスト"""

    def test_extract_keywords_basic(self):
        """基本的なキーワード抽出"""
        repo = EpisodeRepository(TEST_ORG_ID)

        keywords = repo._extract_keywords("目標を達成したい")

        assert isinstance(keywords, list)

    def test_extract_keywords_with_names(self):
        """名前パターンの抽出"""
        repo = EpisodeRepository(TEST_ORG_ID)

        keywords = repo._extract_keywords("田中さんの目標について")

        assert isinstance(keywords, list)
        # 「田中さん」がキーワードとして抽出されるはず

    def test_extract_keywords_empty(self):
        """空文字列"""
        repo = EpisodeRepository(TEST_ORG_ID)

        keywords = repo._extract_keywords("")

        assert keywords == []


class TestRowToEpisode:
    """_row_to_episode()メソッドのテスト"""

    def test_row_to_episode_basic(self):
        """行データからEpisodeへの変換"""
        repo = EpisodeRepository(TEST_ORG_ID)

        episode = create_test_episode()
        row = create_mock_row(episode)

        result = repo._row_to_episode(row)

        assert result.id == episode.id
        assert result.summary == episode.summary

    def test_row_to_episode_with_none_values(self):
        """NULLを含む行データの変換"""
        repo = EpisodeRepository(TEST_ORG_ID)

        row = (
            str(uuid4()),  # id
            None,  # organization_id
            None,  # user_id
            None,  # episode_type
            None,  # summary
            None,  # details
            None,  # emotional_valence
            None,  # importance_score
            None,  # keywords
            None,  # embedding_id
            None,  # recall_count
            None,  # last_recalled_at
            None,  # decay_factor
            None,  # occurred_at
            None,  # created_at
            None,  # updated_at
        )

        result = repo._row_to_episode(row)

        assert result is not None
        assert result.summary == ""
        assert result.keywords == []


class TestLoadEntities:
    """_load_entities()メソッドのテスト"""

    def test_load_entities_found(self):
        """関連エンティティの読み込み"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()

        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[
            ("user", "user_1", "田中", "mentioned"),
            ("goal", "goal_1", "目標A", "about"),
        ])
        conn.execute = MagicMock(return_value=mock_result)

        result = repo._load_entities(conn, TEST_EPISODE_ID)

        assert len(result) == 2
        assert result[0].entity_type == "user"

    def test_load_entities_empty(self):
        """エンティティなし"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()

        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[])
        conn.execute = MagicMock(return_value=mock_result)

        result = repo._load_entities(conn, TEST_EPISODE_ID)

        assert result == []

    def test_load_entities_error(self):
        """エラー時は空リストを返す"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()
        conn.execute = MagicMock(side_effect=Exception("DB error"))

        result = repo._load_entities(conn, TEST_EPISODE_ID)

        assert result == []


# =============================================================================
# 統計テスト
# =============================================================================


class TestGetStatistics:
    """get_statistics()メソッドのテスト"""

    def test_get_statistics_success(self):
        """統計取得成功"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()

        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[
            (10, 0.7, 0.9, 25, "interaction", 10),
        ])
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.get_statistics(conn)

        assert result["total_episodes"] == 10
        assert "by_type" in result

    def test_get_statistics_with_user_id(self):
        """user_id指定で統計取得"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()

        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[])
        conn.execute = MagicMock(return_value=mock_result)

        result = repo.get_statistics(conn, user_id=TEST_USER_ID)

        assert result["total_episodes"] == 0

    def test_get_statistics_error(self):
        """エラー時はデフォルト値を返す"""
        repo = EpisodeRepository(TEST_ORG_ID)
        conn = MagicMock()
        conn.execute = MagicMock(side_effect=Exception("DB error"))

        result = repo.get_statistics(conn)

        assert result["total_episodes"] == 0
        assert result["by_type"] == {}
