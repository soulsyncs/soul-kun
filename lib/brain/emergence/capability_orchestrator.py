"""
Phase 2O: 能力統合オーケストレーター

全Phase 2E-2Nの能力間の関係をグラフとして管理し、
相乗効果・依存関係・増幅関係を追跡する。

PII保護: 能力タイプ・強度のみ。個人データは含まない。
"""

import logging
from typing import Any, Dict, List

from .constants import (
    EDGE_STRENGTH_DEFAULT,
    EDGE_STRENGTH_MAX,
    EDGE_STRENGTH_MIN,
    STRONG_EDGE_THRESHOLD,
    TABLE_BRAIN_CAPABILITY_GRAPH,
    WEAK_EDGE_THRESHOLD,
    EdgeStatus,
    IntegrationType,
    PhaseID,
)
from .models import CapabilityEdge, EmergenceResult

logger = logging.getLogger(__name__)


class CapabilityOrchestrator:
    """全Phase 2E-2N能力の統合調整

    主な機能:
    1. record_edge: 能力間の関係を記録
    2. get_capability_graph: 全エッジを一括取得（N+1対策）
    3. find_synergies: 相乗効果の検出
    4. get_strongest_connections: 最も強い結合の取得
    5. get_weakest_connections: 最も弱い結合の取得
    """

    def __init__(self, organization_id: str = ""):
        if not organization_id:
            raise ValueError("organization_id is required")
        self.organization_id = organization_id

    async def record_edge(
        self,
        conn: Any,
        source_phase: str,
        target_phase: str,
        integration_type: IntegrationType = IntegrationType.SYNERGY,
        strength: float = EDGE_STRENGTH_DEFAULT,
    ) -> EmergenceResult:
        """能力間の関係を記録（ON CONFLICT で冪等）"""
        try:
            clamped = max(EDGE_STRENGTH_MIN, min(EDGE_STRENGTH_MAX, strength))
            from sqlalchemy import text
            conn.execute(
                text(f"""
                    INSERT INTO {TABLE_BRAIN_CAPABILITY_GRAPH}
                    (organization_id, source_phase, target_phase,
                     integration_type, strength, evidence_count)
                    VALUES (:org_id, :src, :tgt, :itype, :strength, 1)
                    ON CONFLICT (organization_id, source_phase, target_phase)
                    DO UPDATE SET
                        strength = (:strength + {TABLE_BRAIN_CAPABILITY_GRAPH}.strength) / 2,
                        evidence_count = {TABLE_BRAIN_CAPABILITY_GRAPH}.evidence_count + 1,
                        updated_at = NOW()
                """),
                {
                    "org_id": self.organization_id,
                    "src": source_phase,
                    "tgt": target_phase,
                    "itype": integration_type.value if isinstance(integration_type, IntegrationType) else integration_type,
                    "strength": clamped,
                },
            )
            logger.info(
                "Edge recorded: %s -> %s (strength=%.2f) for org %s",
                source_phase, target_phase, clamped, self.organization_id,
            )
            return EmergenceResult(success=True, message="Edge recorded")
        except Exception as e:
            logger.error("Failed to record edge %s->%s: %s", source_phase, target_phase, e)
            return EmergenceResult(success=False, message=type(e).__name__)

    async def get_capability_graph(
        self,
        conn: Any,
        limit: int = 200,
    ) -> List[CapabilityEdge]:
        """全エッジを一括取得（N+1対策: 単一クエリ）"""
        try:
            from sqlalchemy import text
            result = conn.execute(
                text(f"""
                    SELECT id, organization_id, source_phase, target_phase,
                           integration_type, strength, status, evidence_count,
                           created_at, updated_at
                    FROM {TABLE_BRAIN_CAPABILITY_GRAPH}
                    WHERE organization_id = :org_id AND status = :status
                    ORDER BY strength DESC
                    LIMIT :limit
                """),
                {"org_id": self.organization_id, "status": EdgeStatus.ACTIVE.value, "limit": limit},
            )
            rows = result.fetchall()
            return [
                CapabilityEdge(
                    id=str(row[0]),
                    organization_id=str(row[1]),
                    source_phase=row[2],
                    target_phase=row[3],
                    integration_type=row[4],
                    strength=float(row[5]) if row[5] else EDGE_STRENGTH_DEFAULT,
                    status=row[6] or EdgeStatus.ACTIVE.value,
                    evidence_count=int(row[7]) if row[7] else 0,
                    created_at=row[8],
                    updated_at=row[9],
                )
                for row in rows
            ]
        except Exception as e:
            logger.warning("Failed to get capability graph: %s", e)
            return []

    def find_synergies(
        self,
        edges: List[CapabilityEdge],
    ) -> List[Dict[str, Any]]:
        """相乗効果のあるペアを検出"""
        synergies = []
        for edge in edges:
            if (
                edge.integration_type == IntegrationType.SYNERGY.value
                and edge.strength >= STRONG_EDGE_THRESHOLD
            ):
                synergies.append({
                    "source": edge.source_phase,
                    "target": edge.target_phase,
                    "strength": edge.strength,
                    "evidence_count": edge.evidence_count,
                    "type": "strong_synergy",
                })
        return synergies

    def get_strongest_connections(
        self,
        edges: List[CapabilityEdge],
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """最も強い結合を取得"""
        sorted_edges = sorted(edges, key=lambda e: e.strength, reverse=True)
        return [
            {
                "source": e.source_phase,
                "target": e.target_phase,
                "strength": e.strength,
                "type": e.integration_type,
            }
            for e in sorted_edges[:limit]
        ]

    def get_weakest_connections(
        self,
        edges: List[CapabilityEdge],
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """最も弱い結合を取得（改善対象の特定用）"""
        sorted_edges = sorted(edges, key=lambda e: e.strength)
        return [
            {
                "source": e.source_phase,
                "target": e.target_phase,
                "strength": e.strength,
                "type": e.integration_type,
            }
            for e in sorted_edges[:limit]
            if e.strength < WEAK_EDGE_THRESHOLD
        ]

    async def update_edge_status(
        self,
        conn: Any,
        edge_id: str,
        status: EdgeStatus,
    ) -> EmergenceResult:
        """エッジのステータスを更新"""
        try:
            from sqlalchemy import text
            conn.execute(
                text(f"""
                    UPDATE {TABLE_BRAIN_CAPABILITY_GRAPH}
                    SET status = :status, updated_at = NOW()
                    WHERE organization_id = :org_id AND id = :edge_id::uuid
                """),
                {
                    "org_id": self.organization_id,
                    "edge_id": edge_id,
                    "status": status.value,
                },
            )
            return EmergenceResult(success=True, message=f"Edge status updated to {status.value}")
        except Exception as e:
            logger.error("Failed to update edge %s: %s", edge_id, e)
            return EmergenceResult(success=False, message=type(e).__name__)


def create_capability_orchestrator(organization_id: str = "") -> CapabilityOrchestrator:
    """CapabilityOrchestratorのファクトリ関数"""
    return CapabilityOrchestrator(organization_id=organization_id)
