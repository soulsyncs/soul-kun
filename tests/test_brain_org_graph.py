# tests/test_brain_org_graph.py
"""
Ultimate Brain Phase 3: Organization Graph のユニットテスト

組織グラフ理解システムのテスト
- 人物ノード管理
- 関係管理
- インタラクション記録と学習
- 分析と洞察
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from lib.brain.org_graph import (
    # 定数
    INFLUENCE_SCORE_MIN,
    INFLUENCE_SCORE_MAX,
    INFLUENCE_SCORE_DEFAULT,
    TRUST_LEVEL_MIN,
    TRUST_LEVEL_MAX,
    TRUST_LEVEL_DEFAULT,
    RELATIONSHIP_STRENGTH_MIN,
    RELATIONSHIP_STRENGTH_MAX,
    RELATIONSHIP_STRENGTH_DEFAULT,
    INTERACTION_HISTORY_DAYS,
    STRENGTH_DECAY_RATE,
    TRUST_DECAY_RATE,
    MIN_INTERACTIONS_FOR_RELATIONSHIP,
    STRENGTH_INCREMENT,
    TRUST_INCREMENT,
    GRAPH_CACHE_TTL,
    # Enum
    RelationshipType,
    CommunicationStyle,
    InteractionType,
    ExpertiseArea,
    # データクラス
    PersonNode,
    PersonRelationship,
    Interaction,
    OrganizationGraphStats,
    RelationshipInsight,
    # メインクラス
    OrganizationGraph,
    create_organization_graph,
)


# =============================================================================
# 定数テスト
# =============================================================================

class TestConstants:
    """定数のテスト"""

    def test_influence_score_range(self):
        """影響力スコアの範囲"""
        assert INFLUENCE_SCORE_MIN == 0.0
        assert INFLUENCE_SCORE_MAX == 1.0
        assert INFLUENCE_SCORE_MIN <= INFLUENCE_SCORE_DEFAULT <= INFLUENCE_SCORE_MAX

    def test_trust_level_range(self):
        """信頼度の範囲"""
        assert TRUST_LEVEL_MIN == 0.0
        assert TRUST_LEVEL_MAX == 1.0
        assert TRUST_LEVEL_MIN <= TRUST_LEVEL_DEFAULT <= TRUST_LEVEL_MAX

    def test_relationship_strength_range(self):
        """関係強度の範囲"""
        assert RELATIONSHIP_STRENGTH_MIN == 0.0
        assert RELATIONSHIP_STRENGTH_MAX == 1.0
        assert RELATIONSHIP_STRENGTH_MIN <= RELATIONSHIP_STRENGTH_DEFAULT <= RELATIONSHIP_STRENGTH_MAX

    def test_decay_rates(self):
        """減衰率が妥当な値"""
        assert 0 < STRENGTH_DECAY_RATE < 0.1
        assert 0 < TRUST_DECAY_RATE < 0.1

    def test_increment_values(self):
        """増加量が妥当な値"""
        assert 0 < STRENGTH_INCREMENT < 0.2
        assert 0 < TRUST_INCREMENT < 0.1

    def test_history_days(self):
        """履歴保持期間"""
        assert INTERACTION_HISTORY_DAYS > 0

    def test_min_interactions(self):
        """最小インタラクション数"""
        assert MIN_INTERACTIONS_FOR_RELATIONSHIP >= 1


# =============================================================================
# Enum テスト
# =============================================================================

class TestRelationshipType:
    """RelationshipType のテスト"""

    def test_reports_to(self):
        """REPORTS_TO"""
        assert RelationshipType.REPORTS_TO.value == "reports_to"

    def test_mentors(self):
        """MENTORS"""
        assert RelationshipType.MENTORS.value == "mentors"

    def test_collaborates_with(self):
        """COLLABORATES_WITH"""
        assert RelationshipType.COLLABORATES_WITH.value == "collaborates_with"

    def test_conflicts_with(self):
        """CONFLICTS_WITH"""
        assert RelationshipType.CONFLICTS_WITH.value == "conflicts_with"

    def test_all_values_count(self):
        """全ての値の数"""
        assert len(RelationshipType) == 8


class TestCommunicationStyle:
    """CommunicationStyle のテスト"""

    def test_formal(self):
        """FORMAL"""
        assert CommunicationStyle.FORMAL.value == "formal"

    def test_casual(self):
        """CASUAL"""
        assert CommunicationStyle.CASUAL.value == "casual"

    def test_detailed(self):
        """DETAILED"""
        assert CommunicationStyle.DETAILED.value == "detailed"

    def test_brief(self):
        """BRIEF"""
        assert CommunicationStyle.BRIEF.value == "brief"

    def test_all_values_count(self):
        """全ての値の数"""
        assert len(CommunicationStyle) == 8


class TestInteractionType:
    """InteractionType のテスト"""

    def test_message(self):
        """MESSAGE"""
        assert InteractionType.MESSAGE.value == "message"

    def test_task_assignment(self):
        """TASK_ASSIGNMENT"""
        assert InteractionType.TASK_ASSIGNMENT.value == "task_assignment"

    def test_praise(self):
        """PRAISE"""
        assert InteractionType.PRAISE.value == "praise"

    def test_conflict(self):
        """CONFLICT"""
        assert InteractionType.CONFLICT.value == "conflict"

    def test_all_values_count(self):
        """全ての値の数"""
        assert len(InteractionType) == 10


class TestExpertiseArea:
    """ExpertiseArea のテスト"""

    def test_management(self):
        """MANAGEMENT"""
        assert ExpertiseArea.MANAGEMENT.value == "management"

    def test_technical(self):
        """TECHNICAL"""
        assert ExpertiseArea.TECHNICAL.value == "technical"

    def test_all_values_count(self):
        """全ての値の数"""
        assert len(ExpertiseArea) == 10


# =============================================================================
# データクラス テスト
# =============================================================================

class TestPersonNode:
    """PersonNode のテスト"""

    def test_creation_defaults(self):
        """デフォルト値での作成"""
        person = PersonNode()
        assert person.id is not None
        assert person.organization_id == ""
        assert person.person_id == ""
        assert person.name == ""
        assert person.influence_score == INFLUENCE_SCORE_DEFAULT
        assert person.expertise_areas == []
        assert person.communication_style == CommunicationStyle.CASUAL
        assert person.total_interactions == 0

    def test_creation_with_values(self):
        """値を指定して作成"""
        person = PersonNode(
            person_id="user123",
            name="田中太郎",
            influence_score=0.8,
            expertise_areas=["management", "sales"],
            communication_style=CommunicationStyle.FORMAL,
        )
        assert person.person_id == "user123"
        assert person.name == "田中太郎"
        assert person.influence_score == 0.8
        assert "management" in person.expertise_areas
        assert person.communication_style == CommunicationStyle.FORMAL

    def test_to_dict(self):
        """辞書への変換"""
        person = PersonNode(
            person_id="user123",
            name="田中太郎",
            influence_score=0.8,
        )
        d = person.to_dict()
        assert d["person_id"] == "user123"
        assert d["name"] == "田中太郎"
        assert d["influence_score"] == 0.8
        assert "created_at" in d


class TestPersonRelationship:
    """PersonRelationship のテスト"""

    def test_creation_defaults(self):
        """デフォルト値での作成"""
        rel = PersonRelationship()
        assert rel.id is not None
        assert rel.person_a_id == ""
        assert rel.person_b_id == ""
        assert rel.relationship_type == RelationshipType.COLLABORATES_WITH
        assert rel.strength == RELATIONSHIP_STRENGTH_DEFAULT
        assert rel.trust_level == TRUST_LEVEL_DEFAULT
        assert rel.bidirectional == False
        assert rel.observed_interactions == 0

    def test_creation_with_values(self):
        """値を指定して作成"""
        rel = PersonRelationship(
            person_a_id="user1",
            person_b_id="user2",
            relationship_type=RelationshipType.REPORTS_TO,
            strength=0.7,
            trust_level=0.8,
            bidirectional=False,
        )
        assert rel.person_a_id == "user1"
        assert rel.person_b_id == "user2"
        assert rel.relationship_type == RelationshipType.REPORTS_TO
        assert rel.strength == 0.7
        assert rel.trust_level == 0.8

    def test_to_dict(self):
        """辞書への変換"""
        rel = PersonRelationship(
            person_a_id="user1",
            person_b_id="user2",
            relationship_type=RelationshipType.MENTORS,
        )
        d = rel.to_dict()
        assert d["person_a_id"] == "user1"
        assert d["person_b_id"] == "user2"
        assert d["relationship_type"] == "mentors"


class TestInteraction:
    """Interaction のテスト"""

    def test_creation_defaults(self):
        """デフォルト値での作成"""
        interaction = Interaction()
        assert interaction.id is not None
        assert interaction.from_person_id == ""
        assert interaction.to_person_id == ""
        assert interaction.interaction_type == InteractionType.MESSAGE
        assert interaction.sentiment == 0.0

    def test_creation_with_values(self):
        """値を指定して作成"""
        interaction = Interaction(
            from_person_id="user1",
            to_person_id="user2",
            interaction_type=InteractionType.PRAISE,
            sentiment=0.8,
            context="素晴らしい仕事でした",
        )
        assert interaction.from_person_id == "user1"
        assert interaction.to_person_id == "user2"
        assert interaction.interaction_type == InteractionType.PRAISE
        assert interaction.sentiment == 0.8
        assert interaction.context == "素晴らしい仕事でした"

    def test_to_dict(self):
        """辞書への変換"""
        interaction = Interaction(
            from_person_id="user1",
            to_person_id="user2",
            interaction_type=InteractionType.HELP_PROVIDE,
        )
        d = interaction.to_dict()
        assert d["from_person_id"] == "user1"
        assert d["to_person_id"] == "user2"
        assert d["interaction_type"] == "help_provide"


class TestOrganizationGraphStats:
    """OrganizationGraphStats のテスト"""

    def test_creation_defaults(self):
        """デフォルト値での作成"""
        stats = OrganizationGraphStats()
        assert stats.total_persons == 0
        assert stats.total_relationships == 0
        assert stats.avg_influence_score == 0.0
        assert stats.graph_density == 0.0


class TestRelationshipInsight:
    """RelationshipInsight のテスト"""

    def test_creation_defaults(self):
        """デフォルト値での作成"""
        insight = RelationshipInsight()
        assert insight.person_a_id == ""
        assert insight.insight_type == ""
        assert insight.recommendations == []


# =============================================================================
# OrganizationGraph 初期化テスト
# =============================================================================

class TestOrganizationGraphInit:
    """OrganizationGraph 初期化のテスト"""

    def test_default_initialization(self):
        """デフォルト初期化"""
        graph = OrganizationGraph()
        assert graph.pool is None
        assert graph.organization_id == ""
        assert graph.enable_auto_learn == True
        assert len(graph._person_cache) == 0
        assert len(graph._relationship_cache) == 0

    def test_initialization_with_values(self):
        """値を指定して初期化"""
        mock_pool = MagicMock()
        graph = OrganizationGraph(
            pool=mock_pool,
            organization_id="org123",
            enable_auto_learn=False,
        )
        assert graph.pool == mock_pool
        assert graph.organization_id == "org123"
        assert graph.enable_auto_learn == False


# =============================================================================
# 人物ノード管理テスト
# =============================================================================

class TestOrganizationGraphPersonManagement:
    """人物ノード管理のテスト"""

    @pytest.mark.asyncio
    async def test_upsert_person(self):
        """人物の追加/更新"""
        graph = OrganizationGraph(organization_id="org123")
        person = PersonNode(
            person_id="user1",
            name="田中太郎",
        )

        result = await graph.upsert_person(person)

        assert result == True
        assert "user1" in graph._person_cache
        assert graph._person_cache["user1"].name == "田中太郎"
        assert graph._person_cache["user1"].organization_id == "org123"

    @pytest.mark.asyncio
    async def test_get_person_from_cache(self):
        """キャッシュから人物を取得"""
        graph = OrganizationGraph()
        person = PersonNode(person_id="user1", name="田中太郎")
        await graph.upsert_person(person)

        result = await graph.get_person("user1")

        assert result is not None
        assert result.name == "田中太郎"

    @pytest.mark.asyncio
    async def test_get_person_not_found(self):
        """存在しない人物"""
        graph = OrganizationGraph()

        result = await graph.get_person("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_update_person_influence(self):
        """影響力スコアの更新"""
        graph = OrganizationGraph()
        person = PersonNode(person_id="user1", influence_score=0.5)
        await graph.upsert_person(person)

        result = await graph.update_person_influence("user1", 0.2)

        assert result == True
        updated = await graph.get_person("user1")
        assert updated.influence_score == 0.7

    @pytest.mark.asyncio
    async def test_update_person_influence_clamp(self):
        """影響力スコアの範囲クランプ"""
        graph = OrganizationGraph()
        person = PersonNode(person_id="user1", influence_score=0.9)
        await graph.upsert_person(person)

        await graph.update_person_influence("user1", 0.5)

        updated = await graph.get_person("user1")
        assert updated.influence_score == INFLUENCE_SCORE_MAX

    @pytest.mark.asyncio
    async def test_update_person_expertise(self):
        """専門領域の更新"""
        graph = OrganizationGraph()
        person = PersonNode(person_id="user1", expertise_areas=["management"])
        await graph.upsert_person(person)

        result = await graph.update_person_expertise("user1", ["sales", "technical"])

        assert result == True
        updated = await graph.get_person("user1")
        assert "management" in updated.expertise_areas
        assert "sales" in updated.expertise_areas
        assert "technical" in updated.expertise_areas

    @pytest.mark.asyncio
    async def test_update_person_style(self):
        """コミュニケーションスタイルの更新"""
        graph = OrganizationGraph()
        person = PersonNode(person_id="user1")
        await graph.upsert_person(person)

        result = await graph.update_person_style("user1", CommunicationStyle.FORMAL)

        assert result == True
        updated = await graph.get_person("user1")
        assert updated.communication_style == CommunicationStyle.FORMAL

    @pytest.mark.asyncio
    async def test_get_all_persons(self):
        """全人物の取得"""
        graph = OrganizationGraph()
        await graph.upsert_person(PersonNode(person_id="user1", name="田中"))
        await graph.upsert_person(PersonNode(person_id="user2", name="山田"))

        result = await graph.get_all_persons()

        assert len(result) == 2


# =============================================================================
# 関係管理テスト
# =============================================================================

class TestOrganizationGraphRelationshipManagement:
    """関係管理のテスト"""

    @pytest.mark.asyncio
    async def test_upsert_relationship(self):
        """関係の追加/更新"""
        graph = OrganizationGraph(organization_id="org123")
        rel = PersonRelationship(
            person_a_id="user1",
            person_b_id="user2",
            relationship_type=RelationshipType.REPORTS_TO,
        )

        result = await graph.upsert_relationship(rel)

        assert result == True
        assert len(graph._relationship_cache) == 1

    @pytest.mark.asyncio
    async def test_get_relationship(self):
        """関係の取得"""
        graph = OrganizationGraph()
        rel = PersonRelationship(
            person_a_id="user1",
            person_b_id="user2",
        )
        await graph.upsert_relationship(rel)

        result = await graph.get_relationship("user1", "user2")

        assert result is not None
        assert result.person_a_id == "user1"
        assert result.person_b_id == "user2"

    @pytest.mark.asyncio
    async def test_get_relationship_bidirectional(self):
        """双方向関係の取得（逆方向）"""
        graph = OrganizationGraph()
        rel = PersonRelationship(
            person_a_id="user1",
            person_b_id="user2",
            bidirectional=True,
        )
        await graph.upsert_relationship(rel)

        result = await graph.get_relationship("user2", "user1")

        assert result is not None

    @pytest.mark.asyncio
    async def test_get_relationship_not_found(self):
        """存在しない関係"""
        graph = OrganizationGraph()

        result = await graph.get_relationship("user1", "user2")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_relationships_for_person(self):
        """特定人物の全関係を取得"""
        graph = OrganizationGraph()
        await graph.upsert_relationship(PersonRelationship(
            person_a_id="user1", person_b_id="user2",
        ))
        await graph.upsert_relationship(PersonRelationship(
            person_a_id="user1", person_b_id="user3",
        ))
        await graph.upsert_relationship(PersonRelationship(
            person_a_id="user2", person_b_id="user3",
        ))

        result = await graph.get_relationships_for_person("user1")

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_direct_reports(self):
        """直属の部下を取得"""
        graph = OrganizationGraph()
        await graph.upsert_relationship(PersonRelationship(
            person_a_id="user2",
            person_b_id="user1",
            relationship_type=RelationshipType.REPORTS_TO,
        ))
        await graph.upsert_relationship(PersonRelationship(
            person_a_id="user3",
            person_b_id="user1",
            relationship_type=RelationshipType.REPORTS_TO,
        ))

        result = await graph.get_direct_reports("user1")

        assert len(result) == 2
        assert "user2" in result
        assert "user3" in result

    @pytest.mark.asyncio
    async def test_get_manager(self):
        """マネージャーを取得"""
        graph = OrganizationGraph()
        await graph.upsert_relationship(PersonRelationship(
            person_a_id="user1",
            person_b_id="manager1",
            relationship_type=RelationshipType.REPORTS_TO,
        ))

        result = await graph.get_manager("user1")

        assert result == "manager1"

    @pytest.mark.asyncio
    async def test_get_collaborators(self):
        """協力者を取得"""
        graph = OrganizationGraph()
        await graph.upsert_relationship(PersonRelationship(
            person_a_id="user1",
            person_b_id="user2",
            relationship_type=RelationshipType.COLLABORATES_WITH,
        ))
        await graph.upsert_relationship(PersonRelationship(
            person_a_id="user1",
            person_b_id="user3",
            relationship_type=RelationshipType.COLLABORATES_WITH,
        ))

        result = await graph.get_collaborators("user1")

        assert len(result) == 2


# =============================================================================
# インタラクションテスト
# =============================================================================

class TestOrganizationGraphInteraction:
    """インタラクション記録のテスト"""

    @pytest.mark.asyncio
    async def test_record_interaction(self):
        """インタラクションの記録"""
        graph = OrganizationGraph(organization_id="org123")
        interaction = Interaction(
            from_person_id="user1",
            to_person_id="user2",
            interaction_type=InteractionType.MESSAGE,
        )

        result = await graph.record_interaction(interaction)

        assert result == True
        assert len(graph._interaction_buffer) == 1

    @pytest.mark.asyncio
    async def test_record_interaction_auto_learn(self):
        """インタラクションからの自動学習"""
        graph = OrganizationGraph(enable_auto_learn=True)
        interaction = Interaction(
            from_person_id="user1",
            to_person_id="user2",
            interaction_type=InteractionType.MESSAGE,
            sentiment=0.5,
        )

        await graph.record_interaction(interaction)

        # 関係が自動作成される
        rel = await graph.get_relationship("user1", "user2")
        assert rel is not None
        assert rel.observed_interactions == 1

    @pytest.mark.asyncio
    async def test_record_interaction_no_auto_learn(self):
        """自動学習無効時"""
        graph = OrganizationGraph(enable_auto_learn=False)
        interaction = Interaction(
            from_person_id="user1",
            to_person_id="user2",
        )

        await graph.record_interaction(interaction)

        # 関係は作成されない
        rel = await graph.get_relationship("user1", "user2")
        assert rel is None

    @pytest.mark.asyncio
    async def test_positive_interaction_increases_trust(self):
        """ポジティブなインタラクションで信頼度が上昇"""
        graph = OrganizationGraph()
        rel = PersonRelationship(
            person_a_id="user1",
            person_b_id="user2",
            trust_level=0.5,
        )
        await graph.upsert_relationship(rel)

        interaction = Interaction(
            from_person_id="user1",
            to_person_id="user2",
            sentiment=0.8,
        )
        await graph.record_interaction(interaction)

        updated_rel = await graph.get_relationship("user1", "user2")
        assert updated_rel.trust_level > 0.5

    @pytest.mark.asyncio
    async def test_negative_interaction_decreases_trust(self):
        """ネガティブなインタラクションで信頼度が低下"""
        graph = OrganizationGraph()
        rel = PersonRelationship(
            person_a_id="user1",
            person_b_id="user2",
            trust_level=0.5,
        )
        await graph.upsert_relationship(rel)

        interaction = Interaction(
            from_person_id="user1",
            to_person_id="user2",
            sentiment=-0.8,
        )
        await graph.record_interaction(interaction)

        updated_rel = await graph.get_relationship("user1", "user2")
        assert updated_rel.trust_level < 0.5


# =============================================================================
# 減衰処理テスト
# =============================================================================

class TestOrganizationGraphDecay:
    """減衰処理のテスト"""

    @pytest.mark.asyncio
    async def test_apply_decay(self):
        """減衰の適用"""
        graph = OrganizationGraph()
        rel = PersonRelationship(
            person_a_id="user1",
            person_b_id="user2",
            strength=0.8,
            trust_level=0.8,
            last_interaction_at=datetime.now() - timedelta(days=30),
        )
        await graph.upsert_relationship(rel)

        updated_count = await graph.apply_decay()

        assert updated_count == 1
        updated_rel = await graph.get_relationship("user1", "user2")
        assert updated_rel.strength < 0.8
        assert updated_rel.trust_level < 0.8


# =============================================================================
# 分析と洞察テスト
# =============================================================================

class TestOrganizationGraphAnalysis:
    """分析と洞察のテスト"""

    @pytest.mark.asyncio
    async def test_get_graph_stats_empty(self):
        """空のグラフの統計"""
        graph = OrganizationGraph()

        stats = await graph.get_graph_stats()

        assert stats.total_persons == 0
        assert stats.total_relationships == 0

    @pytest.mark.asyncio
    async def test_get_graph_stats_with_data(self):
        """データがあるグラフの統計"""
        graph = OrganizationGraph(organization_id="org123")
        await graph.upsert_person(PersonNode(person_id="user1", influence_score=0.8))
        await graph.upsert_person(PersonNode(person_id="user2", influence_score=0.6))
        await graph.upsert_relationship(PersonRelationship(
            person_a_id="user1",
            person_b_id="user2",
            bidirectional=True,
        ))

        stats = await graph.get_graph_stats()

        assert stats.total_persons == 2
        assert stats.total_relationships == 1
        assert stats.avg_influence_score == 0.7

    @pytest.mark.asyncio
    async def test_generate_relationship_insights_strong_bond(self):
        """強い絆の洞察"""
        graph = OrganizationGraph()
        await graph.upsert_relationship(PersonRelationship(
            person_a_id="user1",
            person_b_id="user2",
            strength=0.9,
            trust_level=0.9,
        ))

        insights = await graph.generate_relationship_insights()

        assert len(insights) > 0
        strong_bond_insights = [i for i in insights if i.insight_type == "strong_bond"]
        assert len(strong_bond_insights) == 1

    @pytest.mark.asyncio
    async def test_generate_relationship_insights_deteriorating(self):
        """悪化している関係の洞察"""
        graph = OrganizationGraph()
        await graph.upsert_relationship(PersonRelationship(
            person_a_id="user1",
            person_b_id="user2",
            positive_interactions=1,
            negative_interactions=5,
            observed_interactions=6,
        ))

        insights = await graph.generate_relationship_insights()

        deteriorating_insights = [i for i in insights if i.insight_type == "deteriorating"]
        assert len(deteriorating_insights) == 1

    @pytest.mark.asyncio
    async def test_generate_relationship_insights_conflict(self):
        """対立関係の洞察"""
        graph = OrganizationGraph()
        await graph.upsert_relationship(PersonRelationship(
            person_a_id="user1",
            person_b_id="user2",
            relationship_type=RelationshipType.CONFLICTS_WITH,
        ))

        insights = await graph.generate_relationship_insights()

        conflict_insights = [i for i in insights if i.insight_type == "potential_conflict"]
        assert len(conflict_insights) == 1


# =============================================================================
# パス検索テスト
# =============================================================================

class TestOrganizationGraphPathFinding:
    """パス検索のテスト"""

    @pytest.mark.asyncio
    async def test_find_communication_path_direct(self):
        """直接の接続"""
        graph = OrganizationGraph()
        await graph.upsert_relationship(PersonRelationship(
            person_a_id="user1",
            person_b_id="user2",
        ))

        path = await graph.find_communication_path("user1", "user2")

        assert path == ["user1", "user2"]

    @pytest.mark.asyncio
    async def test_find_communication_path_indirect(self):
        """間接的な接続"""
        graph = OrganizationGraph()
        await graph.upsert_relationship(PersonRelationship(
            person_a_id="user1",
            person_b_id="user2",
        ))
        await graph.upsert_relationship(PersonRelationship(
            person_a_id="user2",
            person_b_id="user3",
        ))

        path = await graph.find_communication_path("user1", "user3")

        assert path == ["user1", "user2", "user3"]

    @pytest.mark.asyncio
    async def test_find_communication_path_no_connection(self):
        """接続がない場合"""
        graph = OrganizationGraph()
        await graph.upsert_relationship(PersonRelationship(
            person_a_id="user1",
            person_b_id="user2",
        ))

        path = await graph.find_communication_path("user1", "user4")

        assert path == []

    @pytest.mark.asyncio
    async def test_find_communication_path_same_person(self):
        """同じ人物"""
        graph = OrganizationGraph()

        path = await graph.find_communication_path("user1", "user1")

        assert path == ["user1"]


# =============================================================================
# 紹介者提案テスト
# =============================================================================

class TestOrganizationGraphIntroducer:
    """紹介者提案のテスト"""

    @pytest.mark.asyncio
    async def test_suggest_introducer(self):
        """紹介者の提案"""
        graph = OrganizationGraph()
        await graph.upsert_person(PersonNode(person_id="user3", influence_score=0.8))
        await graph.upsert_relationship(PersonRelationship(
            person_a_id="user1",
            person_b_id="user3",
            bidirectional=True,
        ))
        await graph.upsert_relationship(PersonRelationship(
            person_a_id="user2",
            person_b_id="user3",
            bidirectional=True,
        ))

        introducer = await graph.suggest_introducer("user1", "user2")

        assert introducer == "user3"

    @pytest.mark.asyncio
    async def test_suggest_introducer_no_common(self):
        """共通の接続がない場合"""
        graph = OrganizationGraph()
        await graph.upsert_relationship(PersonRelationship(
            person_a_id="user1",
            person_b_id="user3",
        ))

        introducer = await graph.suggest_introducer("user1", "user2")

        assert introducer is None


# =============================================================================
# ユーティリティテスト
# =============================================================================

class TestOrganizationGraphUtilities:
    """ユーティリティのテスト"""

    def test_make_relationship_key(self):
        """関係キーの生成"""
        graph = OrganizationGraph()
        key = graph._make_relationship_key("user1", "user2")
        assert key == "user1:user2"

    @pytest.mark.asyncio
    async def test_clear_cache(self):
        """キャッシュのクリア"""
        graph = OrganizationGraph()
        await graph.upsert_person(PersonNode(person_id="user1"))
        await graph.upsert_relationship(PersonRelationship(
            person_a_id="user1",
            person_b_id="user2",
        ))

        await graph.clear_cache()

        assert len(graph._person_cache) == 0
        assert len(graph._relationship_cache) == 0


# =============================================================================
# ファクトリ関数テスト
# =============================================================================

class TestCreateOrganizationGraph:
    """create_organization_graph のテスト"""

    def test_create_with_defaults(self):
        """デフォルト値で作成"""
        graph = create_organization_graph()
        assert graph.pool is None
        assert graph.organization_id == ""
        assert graph.enable_auto_learn == True

    def test_create_with_values(self):
        """値を指定して作成"""
        mock_pool = MagicMock()
        graph = create_organization_graph(
            pool=mock_pool,
            organization_id="org123",
            enable_auto_learn=False,
        )
        assert graph.pool == mock_pool
        assert graph.organization_id == "org123"
        assert graph.enable_auto_learn == False


# =============================================================================
# 関係タイプ推論テスト
# =============================================================================

class TestRelationshipTypeInference:
    """関係タイプ推論のテスト"""

    def test_infer_task_assignment(self):
        """タスク割り当てから監督関係を推論"""
        graph = OrganizationGraph()
        interaction = Interaction(
            from_person_id="manager1",
            to_person_id="user1",
            interaction_type=InteractionType.TASK_ASSIGNMENT,
        )

        result = graph._infer_relationship_type(interaction)

        assert result == RelationshipType.SUPERVISES

    def test_infer_help_request(self):
        """助けを求めることから相談関係を推論"""
        graph = OrganizationGraph()
        interaction = Interaction(
            from_person_id="user1",
            to_person_id="expert1",
            interaction_type=InteractionType.HELP_REQUEST,
        )

        result = graph._infer_relationship_type(interaction)

        assert result == RelationshipType.CONSULTS

    def test_infer_conflict(self):
        """対立から対立関係を推論"""
        graph = OrganizationGraph()
        interaction = Interaction(
            from_person_id="user1",
            to_person_id="user2",
            interaction_type=InteractionType.CONFLICT,
        )

        result = graph._infer_relationship_type(interaction)

        assert result == RelationshipType.CONFLICTS_WITH


# =============================================================================
# 統合テスト
# =============================================================================

class TestOrganizationGraphIntegration:
    """統合テスト"""

    @pytest.mark.asyncio
    async def test_full_workflow(self):
        """完全なワークフロー"""
        graph = OrganizationGraph(organization_id="org123")

        # 人物を追加
        await graph.upsert_person(PersonNode(
            person_id="manager1",
            name="山田マネージャー",
            influence_score=0.9,
            expertise_areas=["management"],
        ))
        await graph.upsert_person(PersonNode(
            person_id="user1",
            name="田中太郎",
            influence_score=0.5,
            expertise_areas=["technical"],
        ))
        await graph.upsert_person(PersonNode(
            person_id="user2",
            name="鈴木花子",
            influence_score=0.5,
            expertise_areas=["sales"],
        ))

        # 関係を設定
        await graph.upsert_relationship(PersonRelationship(
            person_a_id="user1",
            person_b_id="manager1",
            relationship_type=RelationshipType.REPORTS_TO,
        ))
        await graph.upsert_relationship(PersonRelationship(
            person_a_id="user2",
            person_b_id="manager1",
            relationship_type=RelationshipType.REPORTS_TO,
        ))

        # インタラクションを記録
        await graph.record_interaction(Interaction(
            from_person_id="user1",
            to_person_id="user2",
            interaction_type=InteractionType.MESSAGE,
            sentiment=0.5,
        ))

        # 統計を取得
        stats = await graph.get_graph_stats()

        assert stats.total_persons == 3
        assert stats.total_relationships >= 2

        # 洞察を生成
        insights = await graph.generate_relationship_insights()

        # マネージャーの部下を取得
        reports = await graph.get_direct_reports("manager1")
        assert len(reports) == 2

    @pytest.mark.asyncio
    async def test_learning_from_multiple_interactions(self):
        """複数インタラクションからの学習"""
        graph = OrganizationGraph()

        # 複数のインタラクションを記録
        for i in range(5):
            await graph.record_interaction(Interaction(
                from_person_id="user1",
                to_person_id="user2",
                interaction_type=InteractionType.MESSAGE,
                sentiment=0.3,
            ))

        # 関係が強化されている
        rel = await graph.get_relationship("user1", "user2")
        assert rel is not None
        assert rel.observed_interactions == 5
        assert rel.strength > RELATIONSHIP_STRENGTH_DEFAULT


# =============================================================================
# W-2: 公開API メソッドのテスト（get_strong_relationships / get_person_by_id / is_cache_loaded）
# PR #672 で追加した3つの公開メソッドの単体テスト
# =============================================================================

class TestPublicCacheAPI:
    """W-2対応で追加した公開APIメソッドのテスト"""

    @pytest.mark.anyio
    async def test_is_cache_loaded_initially_false(self):
        """初期状態: キャッシュは空でロード未試行 → False を返す"""
        graph = OrganizationGraph(organization_id="org1")
        assert graph.is_cache_loaded() is False

    @pytest.mark.anyio
    async def test_is_cache_loaded_after_upsert(self):
        """人物を追加するとキャッシュに入る → True を返す"""
        graph = OrganizationGraph(organization_id="org1")
        await graph.upsert_person(PersonNode(person_id="p1", name="テスト太郎"))
        assert graph.is_cache_loaded() is True

    @pytest.mark.anyio
    async def test_get_person_by_id_returns_node(self):
        """登録済み人物IDでPersonNodeが返る"""
        graph = OrganizationGraph(organization_id="org1")
        person = PersonNode(person_id="p1", name="テスト太郎", influence_score=0.8)
        await graph.upsert_person(person)

        result = graph.get_person_by_id("p1")
        assert result is not None
        assert result.person_id == "p1"

    @pytest.mark.anyio
    async def test_get_person_by_id_returns_none_for_unknown(self):
        """未登録IDはNoneを返す"""
        graph = OrganizationGraph(organization_id="org1")
        assert graph.get_person_by_id("nonexistent") is None

    @pytest.mark.anyio
    async def test_get_strong_relationships_filters_by_strength(self):
        """min_strength以上の関係だけが返る"""
        graph = OrganizationGraph(organization_id="org1")
        # 強い関係（strength=0.9）
        strong = PersonRelationship(
            person_a_id="p1", person_b_id="p2",
            relationship_type=RelationshipType.COLLABORATES_WITH,
            strength=0.9,
        )
        # 弱い関係（strength=0.3）
        weak = PersonRelationship(
            person_a_id="p1", person_b_id="p3",
            relationship_type=RelationshipType.COLLABORATES_WITH,
            strength=0.3,
        )
        await graph.upsert_relationship(strong)
        await graph.upsert_relationship(weak)

        results = graph.get_strong_relationships(min_strength=0.7, limit=10)
        strengths = [r.strength for r in results]
        assert all(s >= 0.7 for s in strengths)
        assert 0.9 in strengths
        assert 0.3 not in strengths

    @pytest.mark.anyio
    async def test_get_strong_relationships_respects_limit(self):
        """limitパラメータで件数が制限される"""
        graph = OrganizationGraph(organization_id="org1")
        # 3件の強い関係を追加
        for i in range(3):
            rel = PersonRelationship(
                person_a_id=f"p{i}",
                person_b_id="hub",
                relationship_type=RelationshipType.COLLABORATES_WITH,
                strength=0.8,
            )
            await graph.upsert_relationship(rel)

        results = graph.get_strong_relationships(min_strength=0.5, limit=2)
        assert len(results) <= 2

    @pytest.mark.anyio
    async def test_get_strong_relationships_sorted_descending(self):
        """返り値は強度の降順にソートされる"""
        graph = OrganizationGraph(organization_id="org1")
        for strength in [0.7, 0.9, 0.8]:
            rel = PersonRelationship(
                person_a_id=f"p_s{int(strength*10)}",
                person_b_id="hub",
                relationship_type=RelationshipType.COLLABORATES_WITH,
                strength=strength,
            )
            await graph.upsert_relationship(rel)

        results = graph.get_strong_relationships(min_strength=0.5, limit=10)
        strengths = [r.strength for r in results]
        assert strengths == sorted(strengths, reverse=True)

    @pytest.mark.anyio
    async def test_get_strong_relationships_empty_when_none_qualify(self):
        """min_strengthを超える関係がゼロの場合は空リストを返す"""
        graph = OrganizationGraph(organization_id="org1")
        rel = PersonRelationship(
            person_a_id="p1", person_b_id="p2",
            relationship_type=RelationshipType.COLLABORATES_WITH,
            strength=0.3,
        )
        await graph.upsert_relationship(rel)

        results = graph.get_strong_relationships(min_strength=0.9, limit=10)
        assert results == []
