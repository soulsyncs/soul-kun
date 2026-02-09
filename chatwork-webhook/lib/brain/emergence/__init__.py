"""
Phase 2O: 創発（Emergence）モジュール

全Phase 2E-2Nの能力を統合し、個別では不可能だった
高度な問題解決・戦略提案を実現する。

使用例:
    from lib.brain.emergence import BrainEmergence, create_emergence

    optimizer = create_emergence(organization_id="org_xxx")

    # 能力グラフ記録
    await optimizer.record_edge(conn, "2E", "2G", IntegrationType.SYNERGY, 0.8)

    # 創発パターン検出
    edges = await optimizer.get_capability_graph(conn)
    patterns = optimizer.detect_emergent_patterns(edges)

    # 戦略インサイト生成
    insights = optimizer.generate_insights(edges, patterns)
"""

import logging
from typing import Any, Dict, List, Optional

from .constants import (
    # Feature flags
    FEATURE_FLAG_EMERGENCE_ENABLED,
    FEATURE_FLAG_STRATEGIC_ADVISOR_ENABLED,
    # Enums
    EdgeStatus,
    EmergentBehaviorType,
    InsightType,
    IntegrationType,
    PhaseID,
    SnapshotStatus,
    # Thresholds
    EDGE_STRENGTH_DEFAULT,
    EDGE_STRENGTH_MAX,
    EDGE_STRENGTH_MIN,
    EMERGENCE_CONFIDENCE_THRESHOLD,
    INSIGHT_RELEVANCE_THRESHOLD,
    MAX_EMERGENT_BEHAVIORS_PER_ORG,
    MAX_INSIGHTS_PER_ANALYSIS,
    PREDICTION_HORIZON_DAYS,
    SNAPSHOT_RETENTION_DAYS,
    STRONG_EDGE_THRESHOLD,
    WEAK_EDGE_THRESHOLD,
    # Tables
    TABLE_BRAIN_CAPABILITY_GRAPH,
    TABLE_BRAIN_EMERGENT_BEHAVIORS,
    TABLE_BRAIN_ORG_SNAPSHOTS,
    TABLE_BRAIN_STRATEGIC_INSIGHTS,
)
from .models import (
    CapabilityEdge,
    EmergentBehavior,
    EmergenceResult,
    OrgSnapshot,
    StrategicInsight,
)
from .capability_orchestrator import CapabilityOrchestrator, create_capability_orchestrator
from .emergence_engine import EmergenceEngine, create_emergence_engine
from .strategic_advisor import StrategicAdvisor, create_strategic_advisor

logger = logging.getLogger(__name__)


# =============================================================================
# 統合クラス
# =============================================================================

class BrainEmergence:
    """Phase 2O: 創発の統合クラス

    3つのコンポーネントを統合して提供する:
    1. CapabilityOrchestrator（能力統合調整）
    2. EmergenceEngine（創発パターン検出）
    3. StrategicAdvisor（戦略提案）
    """

    def __init__(
        self,
        organization_id: str = "",
        enable_strategic_advisor: bool = True,
    ):
        if not organization_id:
            raise ValueError("organization_id is required")
        self.organization_id = organization_id

        # コンポーネント初期化
        self.orchestrator = CapabilityOrchestrator(organization_id=organization_id)
        self.engine = EmergenceEngine(organization_id=organization_id)
        self.advisor = StrategicAdvisor(organization_id=organization_id) if enable_strategic_advisor else None

        logger.info(
            "BrainEmergence initialized: org=%s, strategic_advisor=%s",
            organization_id, enable_strategic_advisor,
        )

    # =========================================================================
    # 能力統合（Orchestrator）
    # =========================================================================

    async def record_edge(
        self,
        conn: Any,
        source_phase: str,
        target_phase: str,
        integration_type: IntegrationType = IntegrationType.SYNERGY,
        strength: float = EDGE_STRENGTH_DEFAULT,
    ) -> EmergenceResult:
        """能力間の関係を記録"""
        return await self.orchestrator.record_edge(
            conn, source_phase, target_phase, integration_type, strength,
        )

    async def get_capability_graph(
        self,
        conn: Any,
    ) -> List[CapabilityEdge]:
        """全エッジを一括取得"""
        return await self.orchestrator.get_capability_graph(conn)

    def find_synergies(
        self,
        edges: List[CapabilityEdge],
    ) -> List[Dict[str, Any]]:
        """相乗効果の検出"""
        return self.orchestrator.find_synergies(edges)

    def get_strongest_connections(
        self,
        edges: List[CapabilityEdge],
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """最も強い結合を取得"""
        return self.orchestrator.get_strongest_connections(edges, limit)

    # =========================================================================
    # 創発エンジン
    # =========================================================================

    def detect_emergent_patterns(
        self,
        edges: List[CapabilityEdge],
    ) -> List[EmergentBehavior]:
        """創発パターンを検出"""
        return self.engine.detect_emergent_patterns(edges)

    async def record_behavior(
        self,
        conn: Any,
        behavior: EmergentBehavior,
    ) -> EmergenceResult:
        """創発行動を記録"""
        return await self.engine.record_behavior(conn, behavior)

    async def get_emergent_behaviors(
        self,
        conn: Any,
    ) -> List[EmergentBehavior]:
        """記録済み創発行動を取得"""
        return await self.engine.get_emergent_behaviors(conn)

    def assess_emergence_level(
        self,
        behaviors: List[EmergentBehavior],
    ) -> Dict[str, Any]:
        """創発レベルを評価"""
        return self.engine.assess_emergence_level(behaviors)

    # =========================================================================
    # 戦略アドバイザー
    # =========================================================================

    def generate_insights(
        self,
        edges: List[CapabilityEdge],
        behaviors: List[EmergentBehavior],
        capability_scores: Optional[Dict[str, float]] = None,
    ) -> List[StrategicInsight]:
        """戦略的インサイトを生成"""
        if self.advisor is None:
            return []
        return self.advisor.generate_insights(edges, behaviors, capability_scores)

    async def save_insight(
        self,
        conn: Any,
        insight: StrategicInsight,
    ) -> EmergenceResult:
        """インサイトを保存"""
        if self.advisor is None:
            return EmergenceResult(success=False, message="Strategic advisor disabled")
        return await self.advisor.save_insight(conn, insight)

    async def get_recent_insights(
        self,
        conn: Any,
    ) -> List[StrategicInsight]:
        """最近のインサイトを取得"""
        if self.advisor is None:
            return []
        return await self.advisor.get_recent_insights(conn)

    async def create_snapshot(
        self,
        conn: Any,
        capability_scores: Dict[str, float],
        active_edges: int = 0,
        emergent_count: int = 0,
        insight_count: int = 0,
    ) -> EmergenceResult:
        """組織スナップショットを作成"""
        if self.advisor is None:
            return EmergenceResult(success=False, message="Strategic advisor disabled")
        return await self.advisor.create_snapshot(
            conn, capability_scores, active_edges, emergent_count, insight_count,
        )

    async def get_snapshot_history(
        self,
        conn: Any,
    ) -> List[OrgSnapshot]:
        """スナップショット履歴を取得"""
        if self.advisor is None:
            return []
        return await self.advisor.get_snapshot_history(conn)


# =============================================================================
# ファクトリ関数
# =============================================================================

def create_emergence(
    organization_id: str = "",
    feature_flags: Optional[Dict[str, bool]] = None,
) -> BrainEmergence:
    """BrainEmergenceのファクトリ関数"""
    flags = feature_flags or {}
    return BrainEmergence(
        organization_id=organization_id,
        enable_strategic_advisor=flags.get(FEATURE_FLAG_STRATEGIC_ADVISOR_ENABLED, True),
    )


def is_emergence_enabled(feature_flags: Optional[Dict[str, bool]] = None) -> bool:
    """Phase 2Oが有効かチェック"""
    if feature_flags is None:
        return False
    return feature_flags.get(FEATURE_FLAG_EMERGENCE_ENABLED, False)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Main class
    "BrainEmergence",
    "create_emergence",
    "is_emergence_enabled",
    # Components
    "CapabilityOrchestrator",
    "create_capability_orchestrator",
    "EmergenceEngine",
    "create_emergence_engine",
    "StrategicAdvisor",
    "create_strategic_advisor",
    # Enums
    "PhaseID",
    "IntegrationType",
    "InsightType",
    "EmergentBehaviorType",
    "SnapshotStatus",
    "EdgeStatus",
    # Models
    "CapabilityEdge",
    "EmergentBehavior",
    "StrategicInsight",
    "OrgSnapshot",
    "EmergenceResult",
    # Constants
    "EDGE_STRENGTH_DEFAULT",
    "EDGE_STRENGTH_MAX",
    "EDGE_STRENGTH_MIN",
    "STRONG_EDGE_THRESHOLD",
    "WEAK_EDGE_THRESHOLD",
    "EMERGENCE_CONFIDENCE_THRESHOLD",
    "MAX_EMERGENT_BEHAVIORS_PER_ORG",
    "INSIGHT_RELEVANCE_THRESHOLD",
    "MAX_INSIGHTS_PER_ANALYSIS",
    "PREDICTION_HORIZON_DAYS",
    "SNAPSHOT_RETENTION_DAYS",
    # Tables
    "TABLE_BRAIN_CAPABILITY_GRAPH",
    "TABLE_BRAIN_EMERGENT_BEHAVIORS",
    "TABLE_BRAIN_STRATEGIC_INSIGHTS",
    "TABLE_BRAIN_ORG_SNAPSHOTS",
    # Feature flags
    "FEATURE_FLAG_EMERGENCE_ENABLED",
    "FEATURE_FLAG_STRATEGIC_ADVISOR_ENABLED",
]

__version__ = "1.0.0"
