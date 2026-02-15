# tests/test_brain_episodic_memory.py
"""
Ultimate Brain Phase 2: エピソード記憶（Episodic Memory）のテスト
"""

import pytest
from datetime import datetime, timedelta
from lib.brain.episodic_memory import (
    EpisodicMemory,
    create_episodic_memory,
    EpisodeType,
    RecallTrigger,
    Episode,
    RecallResult,
    RelatedEntity,
    DECAY_RATE_PER_DAY,
    MAX_RECALL_COUNT,
    BASE_IMPORTANCE,
    IMPORTANT_KEYWORDS,
)
from lib.brain.constants import JST


# ============================================================
# 定数テスト
# ============================================================

class TestConstants:
    """定数のテスト"""

    def test_decay_rate(self):
        """忘却率が正しく定義されている"""
        assert DECAY_RATE_PER_DAY == 0.02
        assert 0 < DECAY_RATE_PER_DAY < 1

    def test_max_recall_count(self):
        """最大想起結果数が正しく定義されている"""
        assert MAX_RECALL_COUNT == 5
        assert MAX_RECALL_COUNT > 0

    def test_base_importance(self):
        """エピソードタイプ別基本重要度が定義されている"""
        assert EpisodeType.ACHIEVEMENT in BASE_IMPORTANCE
        assert EpisodeType.FAILURE in BASE_IMPORTANCE
        assert BASE_IMPORTANCE[EpisodeType.LEARNING] == 0.9  # 最も重要

    def test_important_keywords(self):
        """重要キーワードが定義されている"""
        assert "目標" in IMPORTANT_KEYWORDS
        assert "達成" in IMPORTANT_KEYWORDS
        assert "失敗" in IMPORTANT_KEYWORDS


# ============================================================
# Enumテスト
# ============================================================

class TestEpisodeType:
    """EpisodeType Enumのテスト"""

    def test_values(self):
        """値が正しく定義されている"""
        assert EpisodeType.ACHIEVEMENT.value == "achievement"
        assert EpisodeType.FAILURE.value == "failure"
        assert EpisodeType.DECISION.value == "decision"
        assert EpisodeType.INTERACTION.value == "interaction"
        assert EpisodeType.LEARNING.value == "learning"
        assert EpisodeType.EMOTION.value == "emotion"

    def test_all_values(self):
        """全ての値が存在する"""
        assert len(EpisodeType) == 6


class TestRecallTrigger:
    """RecallTrigger Enumのテスト"""

    def test_values(self):
        """値が正しく定義されている"""
        assert RecallTrigger.KEYWORD.value == "keyword"
        assert RecallTrigger.SEMANTIC.value == "semantic"
        assert RecallTrigger.ENTITY.value == "entity"
        assert RecallTrigger.TEMPORAL.value == "temporal"
        assert RecallTrigger.EMOTIONAL.value == "emotional"

    def test_all_values(self):
        """全ての値が存在する"""
        assert len(RecallTrigger) == 5


# ============================================================
# データクラステスト
# ============================================================

class TestRelatedEntity:
    """RelatedEntityデータクラスのテスト"""

    def test_creation(self):
        """正しく作成できる"""
        entity = RelatedEntity(
            entity_type="person",
            entity_id="user_123",
            entity_name="菊地さん",
            relationship="involved",
        )
        assert entity.entity_type == "person"
        assert entity.entity_id == "user_123"
        assert entity.entity_name == "菊地さん"


class TestEpisode:
    """Episodeデータクラスのテスト"""

    def test_creation_default(self):
        """デフォルト値で作成できる"""
        episode = Episode()
        assert episode.episode_type == EpisodeType.INTERACTION
        assert episode.summary == ""
        assert episode.decay_factor == 1.0
        assert episode.recall_count == 0

    def test_creation_with_values(self):
        """値を指定して作成できる"""
        episode = Episode(
            id="ep_001",
            episode_type=EpisodeType.ACHIEVEMENT,
            summary="目標を達成した",
            importance_score=0.9,
            emotional_valence=0.8,
            user_id="user_123",
            organization_id="5f98365f-e7c5-4f48-9918-7fe9aabae5df",
        )
        assert episode.id == "ep_001"
        assert episode.episode_type == EpisodeType.ACHIEVEMENT
        assert episode.importance_score == 0.9

    def test_keywords_list(self):
        """キーワードリストが正しく設定できる"""
        episode = Episode(
            keywords=["目標", "達成", "読書"],
        )
        assert "目標" in episode.keywords
        assert len(episode.keywords) == 3


class TestRecallResult:
    """RecallResultデータクラスのテスト"""

    def test_creation(self):
        """正しく作成できる"""
        episode = Episode(
            id="ep_001",
            summary="目標を達成した",
            importance_score=0.9,
        )
        result = RecallResult(
            episode=episode,
            relevance_score=0.85,
            trigger=RecallTrigger.KEYWORD,
            matched_keywords=["目標", "達成"],
            reasoning="キーワード一致",
        )
        assert result.relevance_score == 0.85
        assert result.trigger == RecallTrigger.KEYWORD
        assert len(result.matched_keywords) == 2


# ============================================================
# EpisodicMemoryテスト
# ============================================================

class TestEpisodicMemoryInit:
    """EpisodicMemory初期化のテスト"""

    def test_create_default(self):
        """デフォルト設定で作成できる"""
        memory = create_episodic_memory()
        assert memory is not None

    def test_create_with_pool(self):
        """poolを指定して作成できる"""
        memory = create_episodic_memory(pool=None)
        assert memory is not None

    def test_create_with_organization_id(self):
        """organization_idを指定して作成できる"""
        memory = create_episodic_memory(organization_id="5f98365f-e7c5-4f48-9918-7fe9aabae5df")
        assert memory.organization_id == "5f98365f-e7c5-4f48-9918-7fe9aabae5df"


class TestEpisodicMemoryCreateEpisode:
    """EpisodicMemory.create_episode()のテスト"""

    def test_create_achievement(self):
        """達成エピソードを作成できる"""
        memory = create_episodic_memory()
        episode = memory.create_episode(
            episode_type=EpisodeType.ACHIEVEMENT,
            summary="目標を達成した",
            user_id="user_001",
        )
        assert episode is not None
        assert episode.episode_type == EpisodeType.ACHIEVEMENT
        assert episode.summary == "目標を達成した"

    def test_create_failure(self):
        """失敗エピソードを作成できる"""
        memory = create_episodic_memory()
        episode = memory.create_episode(
            episode_type=EpisodeType.FAILURE,
            summary="締め切りに間に合わなかった",
            user_id="user_001",
        )
        assert episode.episode_type == EpisodeType.FAILURE

    def test_create_with_details(self):
        """詳細付きでエピソードを作成できる"""
        memory = create_episodic_memory()
        episode = memory.create_episode(
            episode_type=EpisodeType.LEARNING,
            summary="Pythonの非同期処理について学んだ",
            details={"source": "ドキュメント", "topic": "asyncio"},
            user_id="user_001",
        )
        assert episode.details["source"] == "ドキュメント"

    def test_auto_keyword_extraction(self):
        """キーワードが自動抽出される"""
        memory = create_episodic_memory()
        episode = memory.create_episode(
            episode_type=EpisodeType.LEARNING,
            summary="目標を達成して成功した",
            user_id="user_001",
        )
        # 重要キーワードが抽出される
        assert len(episode.keywords) > 0

    def test_importance_score_calculation(self):
        """重要度スコアが計算される"""
        memory = create_episodic_memory()
        episode = memory.create_episode(
            episode_type=EpisodeType.ACHIEVEMENT,
            summary="大きな目標を達成",
            user_id="user_001",
        )
        assert 0 <= episode.importance_score <= 1.0

    def test_episode_id_generated(self):
        """エピソードIDが自動生成される"""
        memory = create_episodic_memory()
        episode = memory.create_episode(
            episode_type=EpisodeType.INTERACTION,
            summary="会話をした",
            user_id="user_001",
        )
        assert episode.id is not None
        assert len(episode.id) > 0


class TestEpisodicMemoryRecall:
    """EpisodicMemory.recall()のテスト"""

    def test_recall_by_keyword(self):
        """キーワードで想起できる"""
        memory = create_episodic_memory()

        # エピソードを作成
        memory.create_episode(
            episode_type=EpisodeType.ACHIEVEMENT,
            summary="プロジェクトAを完了した",
            user_id="user_123",
        )

        results = memory.recall(
            message="プロジェクトの進捗を教えて",
            user_id="user_123",
        )
        assert isinstance(results, list)

    def test_recall_returns_list(self):
        """想起結果がリストで返される"""
        memory = create_episodic_memory()
        results = memory.recall(message="何かあった？")
        assert isinstance(results, list)

    def test_recall_limit(self):
        """最大結果数を超えない"""
        memory = create_episodic_memory()

        # 複数エピソードを作成
        for i in range(10):
            memory.create_episode(
                episode_type=EpisodeType.INTERACTION,
                summary=f"目標{i}についての会話",
                user_id="user_123",
            )

        results = memory.recall(
            message="目標について",
            user_id="user_123",
            max_results=3,
        )
        assert len(results) <= 3

    def test_recall_sorted_by_score(self):
        """スコア順にソートされる"""
        memory = create_episodic_memory()

        # 異なる重要度のエピソードを作成
        memory.create_episode(
            episode_type=EpisodeType.ACHIEVEMENT,
            summary="目標を達成して成功した",  # 重要キーワード多い
            user_id="user_123",
        )
        memory.create_episode(
            episode_type=EpisodeType.INTERACTION,
            summary="話をした",  # 重要キーワード少ない
            user_id="user_123",
        )

        results = memory.recall(
            message="目標の話",
            user_id="user_123",
        )

        if len(results) >= 2:
            # スコア降順
            for i in range(len(results) - 1):
                assert results[i].relevance_score >= results[i + 1].relevance_score


class TestEpisodicMemoryDecay:
    """忘却のテスト"""

    def test_apply_decay(self):
        """忘却が適用される"""
        memory = create_episodic_memory()
        episode = memory.create_episode(
            episode_type=EpisodeType.INTERACTION,
            summary="会話をした",
            user_id="user_001",
        )
        original_decay = episode.decay_factor

        memory.apply_decay(days_since_creation=10)

        # decay_factorが減少している
        assert episode.decay_factor < original_decay

    def test_decay_minimum(self):
        """忘却しても最小値を下回らない"""
        memory = create_episodic_memory()
        episode = memory.create_episode(
            episode_type=EpisodeType.INTERACTION,
            summary="会話をした",
            user_id="user_001",
        )

        # 非常に長い期間経過
        memory.apply_decay(days_since_creation=365)

        assert episode.decay_factor >= 0.1  # 最低10%は残る


class TestEpisodicMemoryConvenienceMethods:
    """便利メソッドのテスト"""

    def test_record_achievement(self):
        """達成を記録できる"""
        memory = create_episodic_memory()
        episode = memory.record_achievement(
            summary="資格試験に合格した",
            user_id="user_001",
        )
        assert episode.episode_type == EpisodeType.ACHIEVEMENT
        assert episode.emotional_valence > 0  # ポジティブ

    def test_record_failure(self):
        """失敗を記録できる"""
        memory = create_episodic_memory()
        episode = memory.record_failure(
            summary="プレゼンでミスをした",
            user_id="user_001",
        )
        assert episode.episode_type == EpisodeType.FAILURE
        assert episode.emotional_valence < 0  # ネガティブ

    def test_record_learning(self):
        """学習を記録できる"""
        memory = create_episodic_memory()
        episode = memory.record_learning(
            summary="新しいフレームワークを学んだ",
            user_id="user_001",
        )
        assert episode.episode_type == EpisodeType.LEARNING

    def test_get_recent_episodes(self):
        """最近のエピソードを取得できる"""
        memory = create_episodic_memory()

        # エピソードを作成
        for i in range(5):
            memory.create_episode(
                episode_type=EpisodeType.INTERACTION,
                summary=f"会話{i}",
                user_id="user_001",
            )

        episodes = memory.get_recent_episodes(user_id="user_001", limit=3)
        assert len(episodes) <= 3

    def test_get_stats(self):
        """統計情報を取得できる"""
        memory = create_episodic_memory()

        # エピソードを作成
        memory.record_achievement("達成1", user_id="user_001")
        memory.record_failure("失敗1", user_id="user_001")

        stats = memory.get_stats()
        assert "total_episodes" in stats
        assert "by_type" in stats
        assert stats["total_episodes"] == 2


# ============================================================
# ファクトリ関数テスト
# ============================================================

class TestFactory:
    """ファクトリ関数のテスト"""

    def test_create_episodic_memory(self):
        """create_episodic_memoryが正しく動作する"""
        memory = create_episodic_memory()
        assert isinstance(memory, EpisodicMemory)

    def test_create_with_options(self):
        """オプション付きで作成できる"""
        memory = create_episodic_memory(
            pool=None,
            organization_id="5f98365f-e7c5-4f48-9918-7fe9aabae5df",
        )
        assert isinstance(memory, EpisodicMemory)
        assert memory.organization_id == "5f98365f-e7c5-4f48-9918-7fe9aabae5df"
