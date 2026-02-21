"""
lib/brain/context_builder.py — Phase 3.5 org_graph統合テスト

対象:
- ContextBuilder._fetch_org_graph_data()
- LLMContext.org_relationships フィールド
- LLMContext.to_prompt_string() に組織情報が含まれること
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from lib.brain.context_builder import ContextBuilder, LLMContext
from lib.brain.org_graph import (
    OrganizationGraph,
    PersonNode,
    PersonRelationship,
    RelationshipType,
    CommunicationStyle,
)


# =============================================================================
# ヘルパー
# =============================================================================

def _make_graph_with_data():
    """テスト用の OrganizationGraph（キャッシュ済み）"""
    graph = OrganizationGraph(pool=None, organization_id="org-1")

    persons = [
        PersonNode(
            id="id-1", organization_id="org-1", person_id="p1",
            name="田中 部長", role="部長",
            influence_score=0.9,
            expertise_areas=["management", "sales"],
            communication_style=CommunicationStyle.FORMAL,
        ),
        PersonNode(
            id="id-2", organization_id="org-1", person_id="p2",
            name="山田 課長", role="課長",
            influence_score=0.6,
            expertise_areas=["technical"],
            communication_style=CommunicationStyle.CASUAL,
        ),
    ]
    for p in persons:
        graph._person_cache[p.person_id] = p

    rel = PersonRelationship(
        id="r1", organization_id="org-1",
        person_a_id="p2", person_b_id="p1",
        relationship_type=RelationshipType.REPORTS_TO,
        strength=0.8,
    )
    graph._relationship_cache["p2:p1"] = rel

    return graph


# =============================================================================
# _fetch_org_graph_data() テスト
# =============================================================================

class TestFetchOrgGraphData:
    """ContextBuilder._fetch_org_graph_data() のテスト"""

    def _builder(self, org_graph=None):
        return ContextBuilder(pool=MagicMock(), org_graph=org_graph)

    def test_returns_empty_when_no_org_graph(self):
        """org_graph が None なら空文字"""
        builder = self._builder(org_graph=None)
        result = asyncio.get_event_loop().run_until_complete(
            builder._fetch_org_graph_data()
        )
        assert result == ""

    def test_returns_empty_when_cache_empty_and_load_fails(self):
        """キャッシュが空 & load_from_db も失敗したら空文字"""
        graph = OrganizationGraph(pool=None, organization_id="org-1")
        # pool=None なので load_from_db は即 return
        builder = self._builder(org_graph=graph)
        result = asyncio.get_event_loop().run_until_complete(
            builder._fetch_org_graph_data()
        )
        assert result == ""

    def test_returns_person_list_from_cache(self):
        """キャッシュに人物がいれば一覧が含まれる"""
        graph = _make_graph_with_data()
        builder = self._builder(org_graph=graph)
        result = asyncio.get_event_loop().run_until_complete(
            builder._fetch_org_graph_data()
        )
        assert "田中 部長" in result

    def test_includes_high_influence_label(self):
        """影響力0.7以上に '影響力: 高' が含まれる"""
        graph = _make_graph_with_data()
        builder = self._builder(org_graph=graph)
        result = asyncio.get_event_loop().run_until_complete(
            builder._fetch_org_graph_data()
        )
        assert "影響力: 高" in result

    def test_includes_strong_relationships(self):
        """強度0.7以上の関係が含まれる"""
        graph = _make_graph_with_data()
        builder = self._builder(org_graph=graph)
        result = asyncio.get_event_loop().run_until_complete(
            builder._fetch_org_graph_data()
        )
        assert "reports_to" in result

    def test_lazy_load_called_when_cache_empty_and_not_attempted(self):
        """キャッシュが空かつ未ロードなら load_from_db() が呼ばれる"""
        graph = MagicMock()
        graph._person_cache = {}  # 空キャッシュ
        graph._load_attempted = False  # 未ロード
        graph.load_from_db = AsyncMock()

        # load_from_db 後もキャッシュが空 → 空文字で返る
        async def fake_load():
            pass  # キャッシュに何も追加しない

        graph.load_from_db.side_effect = fake_load

        builder = self._builder(org_graph=graph)
        asyncio.get_event_loop().run_until_complete(
            builder._fetch_org_graph_data()
        )
        graph.load_from_db.assert_awaited_once()

    def test_lazy_load_not_called_when_already_attempted(self):
        """ロード済みの場合は load_from_db() を呼ばない（W-3 重複ロード防止）"""
        graph = MagicMock()
        graph._person_cache = {}  # キャッシュは空だが
        graph._load_attempted = True  # 既にロード試みた
        graph.load_from_db = AsyncMock()

        builder = self._builder(org_graph=graph)
        asyncio.get_event_loop().run_until_complete(
            builder._fetch_org_graph_data()
        )
        graph.load_from_db.assert_not_awaited()

    def test_no_load_when_cache_populated(self):
        """キャッシュが既にある場合は load_from_db() を呼ばない"""
        graph = MagicMock()
        graph._person_cache = {"p1": MagicMock()}  # 既にデータあり
        graph._load_attempted = False  # ロードはまだ試みていないが
        graph.load_from_db = AsyncMock()
        graph.get_top_persons_by_influence = MagicMock(return_value=[])
        graph._relationship_cache = {}

        builder = self._builder(org_graph=graph)
        asyncio.get_event_loop().run_until_complete(
            builder._fetch_org_graph_data()
        )
        graph.load_from_db.assert_not_awaited()


# =============================================================================
# LLMContext フィールド・to_prompt_string() テスト
# =============================================================================

class TestLLMContextOrgRelationships:
    """LLMContext.org_relationships / to_prompt_string() のテスト"""

    def test_org_relationships_default_empty(self):
        """デフォルトは空文字"""
        ctx = LLMContext()
        assert ctx.org_relationships == ""

    def test_org_relationships_in_prompt_string(self):
        """org_relationships がある場合、to_prompt_string() に含まれる"""
        ctx = LLMContext(org_relationships="主要人物（影響力順）:\n- 田中 部長（部長）")
        prompt = ctx.to_prompt_string()
        assert "組織関係情報" in prompt
        assert "田中 部長" in prompt

    def test_empty_org_relationships_not_in_prompt(self):
        """org_relationships が空なら to_prompt_string() にセクションなし"""
        ctx = LLMContext(org_relationships="")
        prompt = ctx.to_prompt_string()
        assert "組織関係情報" not in prompt
