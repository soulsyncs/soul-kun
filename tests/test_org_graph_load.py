"""
lib/brain/org_graph.py — load_from_db() / get_top_persons_by_influence() /
get_relationships_for_person() のテスト（Phase 3.5）
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from lib.brain.org_graph import (
    OrganizationGraph,
    PersonNode,
    PersonRelationship,
    RelationshipType,
    CommunicationStyle,
    INFLUENCE_SCORE_DEFAULT,
    RELATIONSHIP_STRENGTH_DEFAULT,
    TRUST_LEVEL_DEFAULT,
)


# =============================================================================
# ヘルパー
# =============================================================================

def _make_person_row(**kwargs):
    """DB行のモック（dict-like）"""
    defaults = {
        "id": "aaaa-1111",
        "person_id": "p1",
        "name": "田中 太郎",
        "department_id": "dept-001",
        "role": "部長",
        "influence_score": 0.8,
        "expertise_areas": ["management", "sales"],
        "communication_style": "formal",
        "total_interactions": 50,
        "avg_response_time_hours": 2.5,
        "activity_level": 0.9,
        "created_at": None,
        "updated_at": None,
    }
    defaults.update(kwargs)
    return defaults


def _make_rel_row(**kwargs):
    """DB関係行のモック"""
    defaults = {
        "id": "bbbb-2222",
        "person_a_id": "p1",
        "person_b_id": "p2",
        "relationship_type": "reports_to",
        "strength": 0.8,
        "trust_level": 0.7,
        "bidirectional": False,
        "interaction_count": 30,
        "created_at": None,
        "updated_at": None,
    }
    defaults.update(kwargs)
    return defaults


# =============================================================================
# load_from_db() テスト
# =============================================================================

class TestLoadFromDb:
    """load_from_db() のテスト"""

    def test_no_pool_is_noop(self):
        """pool が None なら何もしない"""
        graph = OrganizationGraph(pool=None, organization_id="org-1")
        asyncio.get_event_loop().run_until_complete(graph.load_from_db())
        assert graph._person_cache == {}
        assert graph._relationship_cache == {}

    def test_loads_persons_into_cache(self):
        """DB行が人物キャッシュに格納される"""
        person_row = _make_person_row()
        rel_row = _make_rel_row()

        pool = MagicMock()

        with patch("asyncio.to_thread", new=AsyncMock(return_value=([person_row], [rel_row]))):
            graph = OrganizationGraph(pool=pool, organization_id="org-1")
            asyncio.get_event_loop().run_until_complete(graph.load_from_db())

        assert "p1" in graph._person_cache
        person = graph._person_cache["p1"]
        assert person.name == "田中 太郎"
        assert person.influence_score == 0.8
        assert person.communication_style == CommunicationStyle.FORMAL

    def test_loads_relationships_into_cache(self):
        """DB行が関係キャッシュに格納される"""
        rel_row = _make_rel_row()

        pool = MagicMock()

        with patch("asyncio.to_thread", new=AsyncMock(return_value=([], [rel_row]))):
            graph = OrganizationGraph(pool=pool, organization_id="org-1")
            asyncio.get_event_loop().run_until_complete(graph.load_from_db())

        key = "p1:p2"
        assert key in graph._relationship_cache
        rel = graph._relationship_cache[key]
        assert rel.relationship_type == RelationshipType.REPORTS_TO
        assert rel.strength == 0.8

    def test_unknown_comm_style_falls_back_to_casual(self):
        """未知のコミュニケーションスタイルはCASUALにフォールバック"""
        row = _make_person_row(communication_style="unknown_style")

        pool = MagicMock()

        with patch("asyncio.to_thread", new=AsyncMock(return_value=([row], []))):
            graph = OrganizationGraph(pool=pool, organization_id="org-1")
            asyncio.get_event_loop().run_until_complete(graph.load_from_db())

        assert graph._person_cache["p1"].communication_style == CommunicationStyle.CASUAL

    def test_unknown_rel_type_falls_back_to_collaborates(self):
        """未知の関係タイプはCOLLABORATES_WITHにフォールバック"""
        row = _make_rel_row(relationship_type="unknown_type")

        pool = MagicMock()

        with patch("asyncio.to_thread", new=AsyncMock(return_value=([], [row]))):
            graph = OrganizationGraph(pool=pool, organization_id="org-1")
            asyncio.get_event_loop().run_until_complete(graph.load_from_db())

        key = "p1:p2"
        assert graph._relationship_cache[key].relationship_type == RelationshipType.COLLABORATES_WITH

    def test_db_error_is_graceful(self):
        """DB例外が発生してもキャッシュは空のまま（graceful degradation）"""
        pool = MagicMock()

        with patch("asyncio.to_thread", new=AsyncMock(side_effect=Exception("DB down"))):
            graph = OrganizationGraph(pool=pool, organization_id="org-1")
            # 例外が外に出ないことを確認
            asyncio.get_event_loop().run_until_complete(graph.load_from_db())

        assert graph._person_cache == {}
        assert graph._relationship_cache == {}

    def test_cache_timestamp_set_after_load(self):
        """正常ロード後はキャッシュタイムスタンプが設定される"""
        pool = MagicMock()

        with patch("asyncio.to_thread", new=AsyncMock(return_value=([], []))):
            graph = OrganizationGraph(pool=pool, organization_id="org-1")
            asyncio.get_event_loop().run_until_complete(graph.load_from_db())

        assert graph._cache_timestamp is not None


# =============================================================================
# get_top_persons_by_influence() テスト
# =============================================================================

class TestGetTopPersonsByInfluence:
    """get_top_persons_by_influence() のテスト"""

    def _make_graph_with_persons(self, scores):
        graph = OrganizationGraph(pool=None, organization_id="org-1")
        for i, score in enumerate(scores):
            p = PersonNode(
                id=f"id-{i}",
                organization_id="org-1",
                person_id=f"p{i}",
                name=f"Person{i}",
                influence_score=score,
            )
            graph._person_cache[f"p{i}"] = p
        return graph

    def test_returns_sorted_by_influence(self):
        """影響力順（降順）で返す"""
        graph = self._make_graph_with_persons([0.3, 0.9, 0.6])
        top = graph.get_top_persons_by_influence(limit=3)
        scores = [p.influence_score for p in top]
        assert scores == sorted(scores, reverse=True)

    def test_respects_limit(self):
        """limit件数を超えない"""
        graph = self._make_graph_with_persons([0.9, 0.8, 0.7, 0.6, 0.5, 0.4])
        top = graph.get_top_persons_by_influence(limit=3)
        assert len(top) == 3

    def test_empty_cache_returns_empty(self):
        """キャッシュが空なら空リスト"""
        graph = OrganizationGraph(pool=None, organization_id="org-1")
        assert graph.get_top_persons_by_influence() == []


# =============================================================================
# get_relationships_for_person() テスト
# =============================================================================

class TestGetRelationshipsForPerson:
    """get_relationships_for_person() のテスト"""

    def _make_graph_with_rels(self):
        graph = OrganizationGraph(pool=None, organization_id="org-1")
        rel1 = PersonRelationship(
            id="r1", organization_id="org-1",
            person_a_id="p1", person_b_id="p2",
            relationship_type=RelationshipType.REPORTS_TO,
        )
        rel2 = PersonRelationship(
            id="r2", organization_id="org-1",
            person_a_id="p3", person_b_id="p1",
            relationship_type=RelationshipType.MENTORS,
        )
        rel3 = PersonRelationship(
            id="r3", organization_id="org-1",
            person_a_id="p2", person_b_id="p3",
            relationship_type=RelationshipType.COLLABORATES_WITH,
        )
        graph._relationship_cache["p1:p2"] = rel1
        graph._relationship_cache["p3:p1"] = rel2
        graph._relationship_cache["p2:p3"] = rel3
        return graph

    def test_returns_all_rels_for_person(self):
        """指定人物が a または b のどちらにいても返す"""
        graph = self._make_graph_with_rels()
        rels = graph.get_cached_relationships_for_person("p1")
        # p1 は rel1(a側) と rel2(b側) に出現
        assert len(rels) == 2

    def test_no_match_returns_empty(self):
        """関係のない人物には空リスト"""
        graph = self._make_graph_with_rels()
        rels = graph.get_cached_relationships_for_person("p_unknown")
        assert rels == []
