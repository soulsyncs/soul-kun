"""
Phase 2G: 記憶の強化（Memory Enhancement）テスト

設計書: docs/17_brain_completion_roadmap.md セクション Phase 2G
"""

import pytest
from datetime import datetime, timedelta
from typing import List
from unittest.mock import MagicMock, patch
from uuid import uuid4

from lib.brain.memory_enhancement import (
    # 統合クラス
    BrainMemoryEnhancement,
    create_memory_enhancement,
    # リポジトリ
    EpisodeRepository,
    KnowledgeGraph,
    # モデル
    Episode,
    RecallResult,
    RelatedEntity,
    KnowledgeNode,
    KnowledgeEdge,
    KnowledgeSubgraph,
    ConsolidationResult,
    # Enums
    EpisodeType,
    RecallTrigger,
    EntityType,
    EntityRelationship,
    NodeType,
    EdgeType,
    KnowledgeSource,
    # 定数
    BASE_IMPORTANCE,
    DECAY_RATE_PER_DAY,
    FORGET_THRESHOLD,
    MAX_RECALL_COUNT,
    RECALL_RELEVANCE_THRESHOLD,
    KNOWLEDGE_CONFIDENCE_DEFAULT,
)


# ============================================================================
# Episode Model Tests
# ============================================================================

class TestEpisode:
    """Episodeモデルのテスト"""

    def test_create_episode(self):
        """エピソード作成"""
        episode = Episode(
            organization_id="org123",
            user_id="user456",
            episode_type=EpisodeType.ACHIEVEMENT,
            summary="目標達成",
        )
        assert episode.id is not None
        assert episode.organization_id == "org123"
        assert episode.user_id == "user456"
        assert episode.episode_type == EpisodeType.ACHIEVEMENT
        assert episode.summary == "目標達成"

    def test_episode_to_dict(self):
        """エピソードの辞書変換"""
        episode = Episode(
            organization_id="org123",
            episode_type=EpisodeType.DECISION,
            summary="重要な判断",
            keywords=["判断", "決定"],
        )
        d = episode.to_dict()
        assert d["organization_id"] == "org123"
        assert d["episode_type"] == "decision"
        assert d["summary"] == "重要な判断"
        assert "判断" in d["keywords"]

    def test_episode_from_dict(self):
        """辞書からエピソード生成"""
        data = {
            "id": str(uuid4()),
            "organization_id": "org123",
            "episode_type": "learning",
            "summary": "新しい学び",
            "keywords": ["学習"],
            "emotional_valence": 0.5,
            "importance_score": 0.8,
        }
        episode = Episode.from_dict(data)
        assert episode.organization_id == "org123"
        assert episode.episode_type == EpisodeType.LEARNING
        assert episode.summary == "新しい学び"
        assert episode.emotional_valence == 0.5
        assert episode.importance_score == 0.8

    def test_episode_effective_importance(self):
        """実効重要度の計算"""
        episode = Episode(
            importance_score=0.8,
            decay_factor=0.5,
        )
        assert episode.effective_importance == 0.4

    def test_episode_is_positive(self):
        """ポジティブなエピソードか"""
        positive = Episode(emotional_valence=0.5)
        neutral = Episode(emotional_valence=0.0)
        negative = Episode(emotional_valence=-0.5)

        assert positive.is_positive is True
        assert neutral.is_positive is False
        assert negative.is_positive is False

    def test_episode_is_negative(self):
        """ネガティブなエピソードか"""
        positive = Episode(emotional_valence=0.5)
        neutral = Episode(emotional_valence=0.0)
        negative = Episode(emotional_valence=-0.5)

        assert positive.is_negative is False
        assert neutral.is_negative is False
        assert negative.is_negative is True


class TestRelatedEntity:
    """RelatedEntityモデルのテスト"""

    def test_create_related_entity(self):
        """関連エンティティ作成"""
        entity = RelatedEntity(
            entity_type=EntityType.PERSON,
            entity_id="person123",
            entity_name="山田太郎",
            relationship=EntityRelationship.INVOLVED,
        )
        assert entity.entity_type == EntityType.PERSON
        assert entity.entity_id == "person123"
        assert entity.entity_name == "山田太郎"
        assert entity.relationship == EntityRelationship.INVOLVED

    def test_related_entity_to_dict(self):
        """関連エンティティの辞書変換"""
        entity = RelatedEntity(
            entity_type=EntityType.TASK,
            entity_id="task456",
            relationship=EntityRelationship.AFFECTED,
        )
        d = entity.to_dict()
        assert d["entity_type"] == "task"
        assert d["entity_id"] == "task456"
        assert d["relationship"] == "affected"

    def test_related_entity_from_dict(self):
        """辞書から関連エンティティ生成"""
        data = {
            "entity_type": "goal",
            "entity_id": "goal789",
            "entity_name": "売上目標",
            "relationship": "caused",
        }
        entity = RelatedEntity.from_dict(data)
        assert entity.entity_type == EntityType.GOAL
        assert entity.entity_id == "goal789"
        assert entity.entity_name == "売上目標"
        assert entity.relationship == EntityRelationship.CAUSED


# ============================================================================
# KnowledgeNode Model Tests
# ============================================================================

class TestKnowledgeNode:
    """KnowledgeNodeモデルのテスト"""

    def test_create_knowledge_node(self):
        """知識ノード作成"""
        node = KnowledgeNode(
            organization_id="org123",
            node_type=NodeType.PERSON,
            name="カズさん",
            description="CEO",
        )
        assert node.id is not None
        assert node.organization_id == "org123"
        assert node.node_type == NodeType.PERSON
        assert node.name == "カズさん"
        assert node.description == "CEO"

    def test_knowledge_node_with_aliases(self):
        """別名を持つ知識ノード"""
        node = KnowledgeNode(
            name="ソウルシンクス",
            node_type=NodeType.ORGANIZATION,
            aliases=["SoulSyncs", "SS"],
        )
        assert "SoulSyncs" in node.aliases
        assert "SS" in node.aliases

    def test_knowledge_node_matches_name(self):
        """名前マッチング"""
        node = KnowledgeNode(
            name="カズさん",
            aliases=["和田", "CEO"],
        )
        assert node.matches_name("カズさん") is True
        assert node.matches_name("和田") is True
        assert node.matches_name("CEO") is True
        assert node.matches_name("山田") is False


class TestKnowledgeEdge:
    """KnowledgeEdgeモデルのテスト"""

    def test_create_knowledge_edge(self):
        """知識エッジ作成"""
        edge = KnowledgeEdge(
            organization_id="org123",
            source_node_id=str(uuid4()),
            target_node_id=str(uuid4()),
            relation_type=EdgeType.BELONGS_TO,
        )
        assert edge.id is not None
        assert edge.relation_type == EdgeType.BELONGS_TO

    def test_knowledge_edge_with_weight(self):
        """重みを持つ知識エッジ"""
        edge = KnowledgeEdge(
            source_node_id=str(uuid4()),
            target_node_id=str(uuid4()),
            relation_type=EdgeType.REPORTS_TO,
            weight=0.9,
        )
        assert edge.weight == 0.9
        assert edge.relation_type == EdgeType.REPORTS_TO


# ============================================================================
# RecallResult Model Tests
# ============================================================================

class TestRecallResult:
    """RecallResultモデルのテスト"""

    def test_create_recall_result(self):
        """想起結果作成"""
        episode = Episode(
            importance_score=0.8,
            decay_factor=0.9,
        )
        result = RecallResult(
            episode=episode,
            relevance_score=0.7,
            trigger=RecallTrigger.KEYWORD,
            matched_keywords=["目標", "達成"],
        )
        assert result.relevance_score == 0.7
        assert result.trigger == RecallTrigger.KEYWORD
        assert "目標" in result.matched_keywords

    def test_recall_result_final_score(self):
        """最終スコアの計算"""
        episode = Episode(
            importance_score=0.8,
            decay_factor=0.5,
        )
        result = RecallResult(
            episode=episode,
            relevance_score=0.7,
            trigger=RecallTrigger.SEMANTIC,
        )
        # final_score = relevance * effective_importance
        # = 0.7 * (0.8 * 0.5) = 0.7 * 0.4 = 0.28
        assert result.final_score == pytest.approx(0.28)


# ============================================================================
# Constants Tests
# ============================================================================

class TestConstants:
    """定数のテスト"""

    def test_episode_type_values(self):
        """EpisodeTypeの値"""
        assert EpisodeType.ACHIEVEMENT.value == "achievement"
        assert EpisodeType.FAILURE.value == "failure"
        assert EpisodeType.DECISION.value == "decision"
        assert EpisodeType.LEARNING.value == "learning"

    def test_entity_type_values(self):
        """EntityTypeの値"""
        assert EntityType.PERSON.value == "person"
        assert EntityType.TASK.value == "task"
        assert EntityType.GOAL.value == "goal"

    def test_node_type_values(self):
        """NodeTypeの値"""
        assert NodeType.CONCEPT.value == "concept"
        assert NodeType.PERSON.value == "person"
        assert NodeType.ORGANIZATION.value == "organization"

    def test_edge_type_values(self):
        """EdgeTypeの値"""
        assert EdgeType.IS_A.value == "is_a"
        assert EdgeType.PART_OF.value == "part_of"
        assert EdgeType.BELONGS_TO.value == "belongs_to"

    def test_recall_trigger_values(self):
        """RecallTriggerの値"""
        assert RecallTrigger.KEYWORD.value == "keyword"
        assert RecallTrigger.SEMANTIC.value == "semantic"
        assert RecallTrigger.ENTITY.value == "entity"

    def test_thresholds(self):
        """閾値の存在確認"""
        # BASE_IMPORTANCE is a dict mapping EpisodeType to importance
        assert isinstance(BASE_IMPORTANCE, dict)
        assert len(BASE_IMPORTANCE) > 0
        assert DECAY_RATE_PER_DAY > 0
        assert FORGET_THRESHOLD >= 0
        assert MAX_RECALL_COUNT > 0
        assert RECALL_RELEVANCE_THRESHOLD >= 0
        assert 0 <= KNOWLEDGE_CONFIDENCE_DEFAULT <= 1


# ============================================================================
# BrainMemoryEnhancement Tests
# ============================================================================

class TestBrainMemoryEnhancement:
    """BrainMemoryEnhancementのテスト"""

    def test_create_memory_enhancement(self):
        """インスタンス生成"""
        memory = create_memory_enhancement("org123")
        assert memory.organization_id == "org123"

    def test_brain_memory_enhancement_init(self):
        """初期化"""
        memory = BrainMemoryEnhancement("org123")
        assert memory._episode_repo is not None
        assert memory._knowledge_graph is not None


class TestEpisodeRepository:
    """EpisodeRepositoryのテスト"""

    def test_repository_init(self):
        """リポジトリ初期化"""
        repo = EpisodeRepository("org123")
        assert repo.organization_id == "org123"


class TestKnowledgeGraph:
    """KnowledgeGraphのテスト"""

    def test_knowledge_graph_init(self):
        """知識グラフ初期化"""
        graph = KnowledgeGraph("org123")
        assert graph.organization_id == "org123"


# ============================================================================
# Integration Tests (with mocked DB)
# ============================================================================

class TestIntegration:
    """統合テスト"""

    @pytest.fixture
    def mock_conn(self):
        """モックDB接続"""
        return MagicMock()

    @pytest.fixture
    def memory(self):
        """BrainMemoryEnhancementインスタンス"""
        return create_memory_enhancement("org123")

    def test_record_achievement_creates_episode(self, memory, mock_conn):
        """達成エピソードの記録"""
        with patch.object(memory._episode_repo, 'save', return_value="episode123") as mock_save:
            episode_id = memory.record_achievement(
                conn=mock_conn,
                user_id="user456",
                summary="営業目標達成",
                details={"description": "Q1の営業目標を達成した"},
                keywords=["営業", "目標", "達成"],
            )

            assert episode_id == "episode123"
            mock_save.assert_called_once()

            # 保存されたエピソードを確認
            saved_episode = mock_save.call_args[0][1]
            assert saved_episode.episode_type == EpisodeType.ACHIEVEMENT
            assert saved_episode.importance_score == pytest.approx(0.8, rel=0.1)

    def test_record_failure_creates_episode(self, memory, mock_conn):
        """失敗エピソードの記録"""
        with patch.object(memory._episode_repo, 'save', return_value="episode456") as mock_save:
            episode_id = memory.record_failure(
                conn=mock_conn,
                user_id="user456",
                summary="期限超過",
                details={"description": "タスクの期限を超過した"},
            )

            assert episode_id == "episode456"
            mock_save.assert_called_once()

            saved_episode = mock_save.call_args[0][1]
            assert saved_episode.episode_type == EpisodeType.FAILURE

    def test_record_decision_creates_episode(self, memory, mock_conn):
        """判断エピソードの記録"""
        with patch.object(memory._episode_repo, 'save', return_value="episode789") as mock_save:
            episode_id = memory.record_decision(
                conn=mock_conn,
                user_id="user456",
                summary="新規案件を受注",
                details={"description": "B社の案件を受注することを決定した"},
            )

            assert episode_id == "episode789"
            mock_save.assert_called_once()

            saved_episode = mock_save.call_args[0][1]
            assert saved_episode.episode_type == EpisodeType.DECISION

    def test_record_learning_creates_episode(self, memory, mock_conn):
        """学習エピソードの記録"""
        with patch.object(memory._episode_repo, 'save', return_value="episode000") as mock_save:
            episode_id = memory.record_learning(
                conn=mock_conn,
                summary="報連相の重要性",
                details={"description": "カズさんから報連相の重要性を学んだ"},
            )

            assert episode_id == "episode000"
            mock_save.assert_called_once()

            saved_episode = mock_save.call_args[0][1]
            assert saved_episode.episode_type == EpisodeType.LEARNING

    def test_recall_episodes(self, memory, mock_conn):
        """エピソード想起"""
        mock_results = [
            RecallResult(
                episode=Episode(summary="目標達成"),
                relevance_score=0.9,
                trigger=RecallTrigger.KEYWORD,
                matched_keywords=["目標"],
            )
        ]
        with patch.object(memory._episode_repo, 'recall', return_value=mock_results) as mock_recall:
            results = memory.recall_episodes(
                conn=mock_conn,
                message="目標について教えて",
                user_id="user456",
            )

            assert len(results) == 1
            assert results[0].relevance_score == 0.9
            mock_recall.assert_called_once()

    def test_add_knowledge_node(self, memory, mock_conn):
        """知識ノード追加"""
        with patch.object(memory._knowledge_graph, 'add_node', return_value="node123") as mock_add:
            node_id = memory.add_knowledge_node(
                conn=mock_conn,
                name="カズさん",
                node_type=NodeType.PERSON,
                description="CEO",
            )

            assert node_id == "node123"
            mock_add.assert_called_once()

            added_node = mock_add.call_args[0][1]
            assert added_node.name == "カズさん"
            assert added_node.node_type == NodeType.PERSON

    def test_add_knowledge_edge(self, memory, mock_conn):
        """知識エッジ追加"""
        source_id = str(uuid4())
        target_id = str(uuid4())

        with patch.object(memory._knowledge_graph, 'add_edge', return_value="edge123") as mock_add:
            edge_id = memory.add_knowledge_edge(
                conn=mock_conn,
                source_node_id=source_id,
                target_node_id=target_id,
                relation_type=EdgeType.BELONGS_TO,
            )

            assert edge_id == "edge123"
            mock_add.assert_called_once()

            added_edge = mock_add.call_args[0][1]
            assert added_edge.source_node_id == source_id
            assert added_edge.target_node_id == target_id
            assert added_edge.relation_type == EdgeType.BELONGS_TO


# ============================================================================
# Edge Cases Tests
# ============================================================================

class TestEdgeCases:
    """エッジケーステスト"""

    def test_episode_with_empty_keywords(self):
        """空のキーワードリスト"""
        episode = Episode(
            organization_id="org123",
            summary="テスト",
            keywords=[],
        )
        assert episode.keywords == []

    def test_episode_with_none_user_id(self):
        """組織全体の記憶（user_id=None）"""
        episode = Episode(
            organization_id="org123",
            user_id=None,
            summary="組織全体の学び",
        )
        assert episode.user_id is None

    def test_knowledge_node_with_empty_aliases(self):
        """空の別名リスト"""
        node = KnowledgeNode(
            name="テスト",
            aliases=[],
        )
        assert node.aliases == []

    def test_episode_from_dict_with_unknown_type(self):
        """未知のエピソードタイプ"""
        data = {
            "episode_type": "unknown_type",
            "summary": "テスト",
        }
        episode = Episode.from_dict(data)
        # フォールバックでINTERACTIONになる
        assert episode.episode_type == EpisodeType.INTERACTION

    def test_related_entity_from_dict_with_unknown_type(self):
        """未知のエンティティタイプ"""
        data = {
            "entity_type": "unknown_type",
            "entity_id": "123",
        }
        entity = RelatedEntity.from_dict(data)
        # フォールバックでPERSONになる
        assert entity.entity_type == EntityType.PERSON
