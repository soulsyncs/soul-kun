"""
Phase 2O: 創発（Emergence）テスト

Sync（ロジック）+ Async（DB操作）の両方をカバー。
"""

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch

from lib.brain.emergence import (
    # Main class
    BrainEmergence,
    create_emergence,
    is_emergence_enabled,
    # Components
    CapabilityOrchestrator,
    EmergenceEngine,
    StrategicAdvisor,
    # Enums
    PhaseID,
    IntegrationType,
    InsightType,
    EmergentBehaviorType,
    SnapshotStatus,
    EdgeStatus,
    # Models
    CapabilityEdge,
    EmergentBehavior,
    StrategicInsight,
    OrgSnapshot,
    EmergenceResult,
    # Constants
    EDGE_STRENGTH_DEFAULT,
    STRONG_EDGE_THRESHOLD,
    WEAK_EDGE_THRESHOLD,
    EMERGENCE_CONFIDENCE_THRESHOLD,
    FEATURE_FLAG_EMERGENCE_ENABLED,
    FEATURE_FLAG_STRATEGIC_ADVISOR_ENABLED,
)

ORG_ID = "org-test-emergence"


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_conn():
    """DB接続のモック"""
    conn = MagicMock()
    conn.execute = MagicMock()
    return conn


@pytest.fixture
def sample_edges():
    """テスト用の能力エッジ"""
    return [
        CapabilityEdge(
            organization_id=ORG_ID,
            source_phase="2E", target_phase="2G",
            integration_type=IntegrationType.SYNERGY.value,
            strength=0.85, evidence_count=10,
        ),
        CapabilityEdge(
            organization_id=ORG_ID,
            source_phase="2G", target_phase="2J",
            integration_type=IntegrationType.SYNERGY.value,
            strength=0.75, evidence_count=5,
        ),
        CapabilityEdge(
            organization_id=ORG_ID,
            source_phase="2E", target_phase="2J",
            integration_type=IntegrationType.AMPLIFICATION.value,
            strength=0.60, evidence_count=3,
        ),
        CapabilityEdge(
            organization_id=ORG_ID,
            source_phase="2H", target_phase="2N",
            integration_type=IntegrationType.SYNERGY.value,
            strength=0.70, evidence_count=4,
        ),
        CapabilityEdge(
            organization_id=ORG_ID,
            source_phase="2I", target_phase="2K",
            integration_type=IntegrationType.COMPLEMENT.value,
            strength=0.20, evidence_count=1,
        ),
    ]


@pytest.fixture
def sample_behaviors():
    """テスト用の創発行動"""
    return [
        EmergentBehavior(
            organization_id=ORG_ID,
            behavior_type=EmergentBehaviorType.NOVEL_COMBINATION.value,
            description="Test pattern 1",
            involved_phases=["2E", "2G", "2J"],
            confidence=0.8, impact_score=0.6,
        ),
        EmergentBehavior(
            organization_id=ORG_ID,
            behavior_type=EmergentBehaviorType.ADAPTIVE_RESPONSE.value,
            description="Test pattern 2",
            involved_phases=["2H", "2N"],
            confidence=0.7, impact_score=0.5,
        ),
        EmergentBehavior(
            organization_id=ORG_ID,
            behavior_type=EmergentBehaviorType.NOVEL_COMBINATION.value,
            description="Test pattern 3",
            involved_phases=["2I", "2J"],
            confidence=0.65, impact_score=0.4,
        ),
    ]


# =============================================================================
# Sync Tests: BrainEmergence Integration
# =============================================================================

class TestBrainEmergence:
    """統合クラスのテスト"""

    def test_initialization(self):
        e = BrainEmergence(organization_id=ORG_ID)
        assert e.organization_id == ORG_ID
        assert e.orchestrator is not None
        assert e.engine is not None
        assert e.advisor is not None

    def test_initialization_requires_org_id(self):
        with pytest.raises(ValueError, match="organization_id is required"):
            BrainEmergence(organization_id="")

    def test_initialization_with_disabled_advisor(self):
        e = BrainEmergence(organization_id=ORG_ID, enable_strategic_advisor=False)
        assert e.advisor is None

    def test_disabled_advisor_returns_safe_defaults(self):
        e = BrainEmergence(organization_id=ORG_ID, enable_strategic_advisor=False)
        # generate_insights returns empty list
        assert e.generate_insights([], []) == []

    def test_assess_emergence_level_delegates(self, sample_behaviors):
        e = BrainEmergence(organization_id=ORG_ID)
        result = e.assess_emergence_level(sample_behaviors)
        assert "level" in result
        assert "score" in result


# =============================================================================
# Sync Tests: Factory and Flags
# =============================================================================

class TestFactoryAndFlags:
    """ファクトリ関数とフィーチャーフラグ"""

    def test_create_emergence(self):
        e = create_emergence(organization_id=ORG_ID)
        assert isinstance(e, BrainEmergence)
        assert e.organization_id == ORG_ID

    def test_create_with_feature_flags(self):
        flags = {FEATURE_FLAG_STRATEGIC_ADVISOR_ENABLED: False}
        e = create_emergence(organization_id=ORG_ID, feature_flags=flags)
        assert e.advisor is None

    def test_is_enabled_true(self):
        assert is_emergence_enabled({FEATURE_FLAG_EMERGENCE_ENABLED: True}) is True

    def test_is_enabled_false(self):
        assert is_emergence_enabled({FEATURE_FLAG_EMERGENCE_ENABLED: False}) is False

    def test_is_enabled_none(self):
        assert is_emergence_enabled(None) is False


# =============================================================================
# Sync Tests: CapabilityOrchestrator
# =============================================================================

class TestCapabilityOrchestrator:
    """能力統合オーケストレーターのテスト"""

    def test_initialization(self):
        o = CapabilityOrchestrator(organization_id=ORG_ID)
        assert o.organization_id == ORG_ID

    def test_initialization_requires_org_id(self):
        with pytest.raises(ValueError):
            CapabilityOrchestrator(organization_id="")

    def test_find_synergies(self, sample_edges):
        o = CapabilityOrchestrator(organization_id=ORG_ID)
        synergies = o.find_synergies(sample_edges)
        # Only edges with type=synergy AND strength >= STRONG_EDGE_THRESHOLD
        assert len(synergies) >= 1
        for s in synergies:
            assert s["strength"] >= STRONG_EDGE_THRESHOLD

    def test_find_synergies_empty(self):
        o = CapabilityOrchestrator(organization_id=ORG_ID)
        assert o.find_synergies([]) == []

    def test_get_strongest_connections(self, sample_edges):
        o = CapabilityOrchestrator(organization_id=ORG_ID)
        strongest = o.get_strongest_connections(sample_edges, limit=3)
        assert len(strongest) == 3
        # Sorted by strength descending
        assert strongest[0]["strength"] >= strongest[1]["strength"]

    def test_get_weakest_connections(self, sample_edges):
        o = CapabilityOrchestrator(organization_id=ORG_ID)
        weakest = o.get_weakest_connections(sample_edges, limit=5)
        # Only edges with strength < WEAK_EDGE_THRESHOLD
        for w in weakest:
            assert w["strength"] < WEAK_EDGE_THRESHOLD

    def test_get_weakest_connections_empty(self):
        o = CapabilityOrchestrator(organization_id=ORG_ID)
        assert o.get_weakest_connections([]) == []


# =============================================================================
# Sync Tests: EmergenceEngine
# =============================================================================

class TestEmergenceEngine:
    """創発エンジンのテスト"""

    def test_initialization(self):
        e = EmergenceEngine(organization_id=ORG_ID)
        assert e.organization_id == ORG_ID

    def test_detect_emergent_patterns_with_strong_edges(self, sample_edges):
        e = EmergenceEngine(organization_id=ORG_ID)
        patterns = e.detect_emergent_patterns(sample_edges)
        # Should detect "learning_memory_judgment" (2E, 2G, 2J all connected strongly)
        assert len(patterns) >= 1
        for p in patterns:
            assert p.confidence >= EMERGENCE_CONFIDENCE_THRESHOLD

    def test_detect_emergent_patterns_empty(self):
        e = EmergenceEngine(organization_id=ORG_ID)
        patterns = e.detect_emergent_patterns([])
        assert patterns == []

    def test_detect_emergent_patterns_weak_edges(self):
        """弱いエッジからは創発パターンを検出しない"""
        e = EmergenceEngine(organization_id=ORG_ID)
        weak_edges = [
            CapabilityEdge(
                organization_id=ORG_ID,
                source_phase="2E", target_phase="2G",
                strength=0.2,
            ),
        ]
        patterns = e.detect_emergent_patterns(weak_edges)
        assert patterns == []

    def test_assess_emergence_level_none(self):
        e = EmergenceEngine(organization_id=ORG_ID)
        result = e.assess_emergence_level([])
        assert result["level"] == "none"
        assert result["score"] == 0.0

    def test_assess_emergence_level_basic(self):
        e = EmergenceEngine(organization_id=ORG_ID)
        behaviors = [
            EmergentBehavior(organization_id=ORG_ID, confidence=0.5),
        ]
        result = e.assess_emergence_level(behaviors)
        assert result["level"] == "basic"

    def test_assess_emergence_level_intermediate(self):
        e = EmergenceEngine(organization_id=ORG_ID)
        behaviors = [
            EmergentBehavior(organization_id=ORG_ID, confidence=0.7),
            EmergentBehavior(organization_id=ORG_ID, confidence=0.65),
            EmergentBehavior(organization_id=ORG_ID, confidence=0.6),
        ]
        result = e.assess_emergence_level(behaviors)
        assert result["level"] == "intermediate"

    def test_assess_emergence_level_advanced(self):
        e = EmergenceEngine(organization_id=ORG_ID)
        behaviors = [
            EmergentBehavior(organization_id=ORG_ID, confidence=0.9)
            for _ in range(5)
        ]
        result = e.assess_emergence_level(behaviors)
        assert result["level"] == "advanced"


# =============================================================================
# Sync Tests: StrategicAdvisor
# =============================================================================

class TestStrategicAdvisor:
    """戦略アドバイザーのテスト"""

    def test_initialization(self):
        a = StrategicAdvisor(organization_id=ORG_ID)
        assert a.organization_id == ORG_ID

    def test_generate_insights_weak_edges(self, sample_edges, sample_behaviors):
        a = StrategicAdvisor(organization_id=ORG_ID)
        insights = a.generate_insights(sample_edges, sample_behaviors)
        # Should generate at least one insight (weak edge at 0.20)
        assert len(insights) >= 1
        types = [i.insight_type for i in insights]
        assert InsightType.OPPORTUNITY.value in types

    def test_generate_insights_with_scores(self, sample_edges, sample_behaviors):
        a = StrategicAdvisor(organization_id=ORG_ID)
        scores = {"2E": 0.9, "2G": 0.2, "2K": 0.85}
        insights = a.generate_insights(sample_edges, sample_behaviors, scores)
        types = [i.insight_type for i in insights]
        # Risk for low-score phase 2G
        assert InsightType.RISK.value in types
        # Recommendation for strong phases
        assert InsightType.RECOMMENDATION.value in types

    def test_generate_insights_empty(self):
        a = StrategicAdvisor(organization_id=ORG_ID)
        insights = a.generate_insights([], [])
        assert insights == []

    def test_generate_insights_trend(self):
        a = StrategicAdvisor(organization_id=ORG_ID)
        behaviors = [
            EmergentBehavior(
                organization_id=ORG_ID,
                behavior_type=EmergentBehaviorType.NOVEL_COMBINATION.value,
                involved_phases=["2E", "2G"],
            )
            for _ in range(3)
        ]
        insights = a.generate_insights([], behaviors)
        types = [i.insight_type for i in insights]
        assert InsightType.TREND.value in types

    def test_generate_insights_max_limit(self, sample_edges):
        a = StrategicAdvisor(organization_id=ORG_ID)
        # Many low-score phases to generate many risk insights
        scores = {f"2{chr(65+i)}": 0.1 for i in range(15)}
        behaviors = [
            EmergentBehavior(
                organization_id=ORG_ID,
                behavior_type=EmergentBehaviorType.NOVEL_COMBINATION.value,
                involved_phases=["2E"],
            )
            for _ in range(5)
        ]
        insights = a.generate_insights(sample_edges, behaviors, scores)
        from lib.brain.emergence.constants import MAX_INSIGHTS_PER_ANALYSIS
        assert len(insights) <= MAX_INSIGHTS_PER_ANALYSIS


# =============================================================================
# Sync Tests: Models
# =============================================================================

class TestModels:
    """データモデルのテスト"""

    def test_capability_edge_defaults(self):
        e = CapabilityEdge()
        assert e.id  # UUID generated
        assert e.strength == 0.5
        assert e.status == "active"
        assert e.created_at is not None

    def test_capability_edge_to_dict(self):
        e = CapabilityEdge(
            organization_id=ORG_ID,
            source_phase="2E", target_phase="2G",
        )
        d = e.to_dict()
        assert d["organization_id"] == ORG_ID
        assert d["source_phase"] == "2E"

    def test_emergent_behavior_defaults(self):
        b = EmergentBehavior()
        assert b.id
        assert b.involved_phases == []
        assert b.confidence == 0.0

    def test_emergent_behavior_to_dict(self):
        b = EmergentBehavior(
            organization_id=ORG_ID,
            involved_phases=["2E", "2G"],
        )
        d = b.to_dict()
        assert d["involved_phases"] == ["2E", "2G"]

    def test_strategic_insight_defaults(self):
        i = StrategicInsight()
        assert i.id
        assert i.actionable is False

    def test_org_snapshot_defaults(self):
        s = OrgSnapshot()
        assert s.id
        assert s.capability_scores == {}
        assert s.overall_score == 0.0

    def test_org_snapshot_to_dict(self):
        s = OrgSnapshot(
            organization_id=ORG_ID,
            capability_scores={"2E": 0.8},
            overall_score=0.8,
        )
        d = s.to_dict()
        assert d["capability_scores"] == {"2E": 0.8}

    def test_emergence_result(self):
        r = EmergenceResult(success=True, message="ok")
        assert r.success is True
        assert r.data is None

    def test_all_enum_values(self):
        assert len(PhaseID) == 10
        assert len(IntegrationType) == 4
        assert len(InsightType) == 5
        assert len(EmergentBehaviorType) == 4
        assert len(SnapshotStatus) == 2
        assert len(EdgeStatus) == 3


# =============================================================================
# Async Tests: CapabilityOrchestrator DB
# =============================================================================

class TestCapabilityOrchestratorDB:
    """能力オーケストレーターのDB操作テスト"""

    @pytest.mark.asyncio
    async def test_record_edge_success(self, mock_conn):
        o = CapabilityOrchestrator(organization_id=ORG_ID)
        result = await o.record_edge(mock_conn, "2E", "2G", IntegrationType.SYNERGY, 0.8)
        assert result.success is True
        mock_conn.execute.assert_called_once()
        params = mock_conn.execute.call_args[0][1]
        assert params["org_id"] == ORG_ID
        assert params["src"] == "2E"
        assert params["tgt"] == "2G"

    @pytest.mark.asyncio
    async def test_record_edge_clamps_strength(self, mock_conn):
        o = CapabilityOrchestrator(organization_id=ORG_ID)
        result = await o.record_edge(mock_conn, "2E", "2G", strength=1.5)
        assert result.success is True
        params = mock_conn.execute.call_args[0][1]
        assert params["strength"] == 1.0  # Clamped

    @pytest.mark.asyncio
    async def test_record_edge_db_error(self, mock_conn):
        mock_conn.execute.side_effect = Exception("DB error")
        o = CapabilityOrchestrator(organization_id=ORG_ID)
        result = await o.record_edge(mock_conn, "2E", "2G")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_get_capability_graph_found(self, mock_conn):
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("id1", ORG_ID, "2E", "2G", "synergy", 0.85, "active", 10,
             datetime.now(timezone.utc), datetime.now(timezone.utc)),
        ]
        mock_conn.execute.return_value = mock_result
        o = CapabilityOrchestrator(organization_id=ORG_ID)
        edges = await o.get_capability_graph(mock_conn)
        assert len(edges) == 1
        assert edges[0].source_phase == "2E"
        params = mock_conn.execute.call_args[0][1]
        assert params["org_id"] == ORG_ID

    @pytest.mark.asyncio
    async def test_get_capability_graph_empty(self, mock_conn):
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result
        o = CapabilityOrchestrator(organization_id=ORG_ID)
        edges = await o.get_capability_graph(mock_conn)
        assert edges == []

    @pytest.mark.asyncio
    async def test_get_capability_graph_db_error(self, mock_conn):
        mock_conn.execute.side_effect = Exception("DB error")
        o = CapabilityOrchestrator(organization_id=ORG_ID)
        edges = await o.get_capability_graph(mock_conn)
        assert edges == []

    @pytest.mark.asyncio
    async def test_update_edge_status_success(self, mock_conn):
        o = CapabilityOrchestrator(organization_id=ORG_ID)
        result = await o.update_edge_status(mock_conn, "edge-id", EdgeStatus.INACTIVE)
        assert result.success is True
        params = mock_conn.execute.call_args[0][1]
        assert params["org_id"] == ORG_ID
        assert params["edge_id"] == "edge-id"

    @pytest.mark.asyncio
    async def test_update_edge_status_db_error(self, mock_conn):
        mock_conn.execute.side_effect = Exception("DB error")
        o = CapabilityOrchestrator(organization_id=ORG_ID)
        result = await o.update_edge_status(mock_conn, "edge-id", EdgeStatus.INACTIVE)
        assert result.success is False


# =============================================================================
# Async Tests: EmergenceEngine DB
# =============================================================================

class TestEmergenceEngineDB:
    """創発エンジンのDB操作テスト"""

    @pytest.mark.asyncio
    async def test_record_behavior_success(self, mock_conn):
        e = EmergenceEngine(organization_id=ORG_ID)
        behavior = EmergentBehavior(
            organization_id=ORG_ID,
            behavior_type="novel_combination",
            involved_phases=["2E", "2G"],
            confidence=0.8,
        )
        result = await e.record_behavior(mock_conn, behavior)
        assert result.success is True
        params = mock_conn.execute.call_args[0][1]
        assert params["org_id"] == ORG_ID
        assert params["btype"] == "novel_combination"
        assert json.loads(params["phases"]) == ["2E", "2G"]

    @pytest.mark.asyncio
    async def test_record_behavior_db_error(self, mock_conn):
        mock_conn.execute.side_effect = Exception("DB error")
        e = EmergenceEngine(organization_id=ORG_ID)
        behavior = EmergentBehavior(organization_id=ORG_ID)
        result = await e.record_behavior(mock_conn, behavior)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_get_emergent_behaviors_found(self, mock_conn):
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("id1", ORG_ID, "novel_combination", "desc1",
             json.dumps(["2E", "2G"]), 0.8, 0.6, 3, datetime.now(timezone.utc)),
        ]
        mock_conn.execute.return_value = mock_result
        e = EmergenceEngine(organization_id=ORG_ID)
        behaviors = await e.get_emergent_behaviors(mock_conn)
        assert len(behaviors) == 1
        assert behaviors[0].involved_phases == ["2E", "2G"]
        params = mock_conn.execute.call_args[0][1]
        assert params["org_id"] == ORG_ID

    @pytest.mark.asyncio
    async def test_get_emergent_behaviors_json_list(self, mock_conn):
        """involved_phases が既にlistの場合"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("id1", ORG_ID, "adaptive_response", "desc",
             ["2H", "2N"], 0.7, 0.5, 1, datetime.now(timezone.utc)),
        ]
        mock_conn.execute.return_value = mock_result
        e = EmergenceEngine(organization_id=ORG_ID)
        behaviors = await e.get_emergent_behaviors(mock_conn)
        assert behaviors[0].involved_phases == ["2H", "2N"]

    @pytest.mark.asyncio
    async def test_get_emergent_behaviors_empty(self, mock_conn):
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result
        e = EmergenceEngine(organization_id=ORG_ID)
        behaviors = await e.get_emergent_behaviors(mock_conn)
        assert behaviors == []

    @pytest.mark.asyncio
    async def test_get_emergent_behaviors_db_error(self, mock_conn):
        mock_conn.execute.side_effect = Exception("DB error")
        e = EmergenceEngine(organization_id=ORG_ID)
        behaviors = await e.get_emergent_behaviors(mock_conn)
        assert behaviors == []


# =============================================================================
# Async Tests: StrategicAdvisor DB
# =============================================================================

class TestStrategicAdvisorDB:
    """戦略アドバイザーのDB操作テスト"""

    @pytest.mark.asyncio
    async def test_save_insight_success(self, mock_conn):
        a = StrategicAdvisor(organization_id=ORG_ID)
        insight = StrategicInsight(
            organization_id=ORG_ID,
            insight_type="opportunity",
            title="Test insight",
            source_phases=["2E", "2G"],
        )
        result = await a.save_insight(mock_conn, insight)
        assert result.success is True
        params = mock_conn.execute.call_args[0][1]
        assert params["org_id"] == ORG_ID
        assert json.loads(params["phases"]) == ["2E", "2G"]

    @pytest.mark.asyncio
    async def test_save_insight_db_error(self, mock_conn):
        mock_conn.execute.side_effect = Exception("DB error")
        a = StrategicAdvisor(organization_id=ORG_ID)
        insight = StrategicInsight(organization_id=ORG_ID)
        result = await a.save_insight(mock_conn, insight)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_get_recent_insights_found(self, mock_conn):
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("id1", ORG_ID, "opportunity", "title1", "desc1",
             0.8, json.dumps(["2E"]), True, datetime.now(timezone.utc)),
        ]
        mock_conn.execute.return_value = mock_result
        a = StrategicAdvisor(organization_id=ORG_ID)
        insights = await a.get_recent_insights(mock_conn)
        assert len(insights) == 1
        assert insights[0].insight_type == "opportunity"
        assert insights[0].actionable is True
        params = mock_conn.execute.call_args[0][1]
        assert params["org_id"] == ORG_ID

    @pytest.mark.asyncio
    async def test_get_recent_insights_empty(self, mock_conn):
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result
        a = StrategicAdvisor(organization_id=ORG_ID)
        insights = await a.get_recent_insights(mock_conn)
        assert insights == []

    @pytest.mark.asyncio
    async def test_get_recent_insights_db_error(self, mock_conn):
        mock_conn.execute.side_effect = Exception("DB error")
        a = StrategicAdvisor(organization_id=ORG_ID)
        insights = await a.get_recent_insights(mock_conn)
        assert insights == []

    @pytest.mark.asyncio
    async def test_create_snapshot_success(self, mock_conn):
        a = StrategicAdvisor(organization_id=ORG_ID)
        scores = {"2E": 0.8, "2G": 0.6}
        result = await a.create_snapshot(mock_conn, scores, active_edges=5)
        assert result.success is True
        params = mock_conn.execute.call_args[0][1]
        assert params["org_id"] == ORG_ID
        assert json.loads(params["scores"]) == {"2E": 0.8, "2G": 0.6}
        assert params["overall"] == 0.7  # (0.8 + 0.6) / 2

    @pytest.mark.asyncio
    async def test_create_snapshot_empty_scores(self, mock_conn):
        a = StrategicAdvisor(organization_id=ORG_ID)
        result = await a.create_snapshot(mock_conn, {})
        assert result.success is True
        params = mock_conn.execute.call_args[0][1]
        assert params["overall"] == 0.0

    @pytest.mark.asyncio
    async def test_create_snapshot_db_error(self, mock_conn):
        mock_conn.execute.side_effect = Exception("DB error")
        a = StrategicAdvisor(organization_id=ORG_ID)
        result = await a.create_snapshot(mock_conn, {"2E": 0.5})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_get_snapshot_history_found(self, mock_conn):
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("id1", ORG_ID, json.dumps({"2E": 0.8}), 0.8,
             5, 3, 2, "active", datetime.now(timezone.utc)),
        ]
        mock_conn.execute.return_value = mock_result
        a = StrategicAdvisor(organization_id=ORG_ID)
        snapshots = await a.get_snapshot_history(mock_conn)
        assert len(snapshots) == 1
        assert snapshots[0].capability_scores == {"2E": 0.8}
        params = mock_conn.execute.call_args[0][1]
        assert params["org_id"] == ORG_ID

    @pytest.mark.asyncio
    async def test_get_snapshot_history_dict_scores(self, mock_conn):
        """capability_scores が既にdictの場合"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("id1", ORG_ID, {"2E": 0.9}, 0.9,
             3, 1, 1, "active", datetime.now(timezone.utc)),
        ]
        mock_conn.execute.return_value = mock_result
        a = StrategicAdvisor(organization_id=ORG_ID)
        snapshots = await a.get_snapshot_history(mock_conn)
        assert snapshots[0].capability_scores == {"2E": 0.9}

    @pytest.mark.asyncio
    async def test_get_snapshot_history_empty(self, mock_conn):
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result
        a = StrategicAdvisor(organization_id=ORG_ID)
        snapshots = await a.get_snapshot_history(mock_conn)
        assert snapshots == []

    @pytest.mark.asyncio
    async def test_get_snapshot_history_db_error(self, mock_conn):
        mock_conn.execute.side_effect = Exception("DB error")
        a = StrategicAdvisor(organization_id=ORG_ID)
        snapshots = await a.get_snapshot_history(mock_conn)
        assert snapshots == []


# =============================================================================
# Async Tests: BrainEmergence Integration DB
# =============================================================================

class TestBrainEmergenceDB:
    """統合クラスのDB委譲テスト"""

    @pytest.mark.asyncio
    async def test_record_edge_delegates(self, mock_conn):
        e = BrainEmergence(organization_id=ORG_ID)
        result = await e.record_edge(mock_conn, "2E", "2G")
        assert result.success is True
        params = mock_conn.execute.call_args[0][1]
        assert params["org_id"] == ORG_ID

    @pytest.mark.asyncio
    async def test_get_capability_graph_delegates(self, mock_conn):
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result
        e = BrainEmergence(organization_id=ORG_ID)
        edges = await e.get_capability_graph(mock_conn)
        assert edges == []

    @pytest.mark.asyncio
    async def test_record_behavior_delegates(self, mock_conn):
        e = BrainEmergence(organization_id=ORG_ID)
        b = EmergentBehavior(organization_id=ORG_ID)
        result = await e.record_behavior(mock_conn, b)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_save_insight_delegates(self, mock_conn):
        e = BrainEmergence(organization_id=ORG_ID)
        i = StrategicInsight(organization_id=ORG_ID)
        result = await e.save_insight(mock_conn, i)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_save_insight_disabled_advisor(self, mock_conn):
        e = BrainEmergence(organization_id=ORG_ID, enable_strategic_advisor=False)
        i = StrategicInsight(organization_id=ORG_ID)
        result = await e.save_insight(mock_conn, i)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_create_snapshot_delegates(self, mock_conn):
        e = BrainEmergence(organization_id=ORG_ID)
        result = await e.create_snapshot(mock_conn, {"2E": 0.8})
        assert result.success is True

    @pytest.mark.asyncio
    async def test_get_snapshot_history_delegates(self, mock_conn):
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result
        e = BrainEmergence(organization_id=ORG_ID)
        snapshots = await e.get_snapshot_history(mock_conn)
        assert snapshots == []

    @pytest.mark.asyncio
    async def test_get_snapshot_history_disabled_advisor(self, mock_conn):
        e = BrainEmergence(organization_id=ORG_ID, enable_strategic_advisor=False)
        snapshots = await e.get_snapshot_history(mock_conn)
        assert snapshots == []
