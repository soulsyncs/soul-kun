"""
Phase 2O: 戦略アドバイザー

組織全体の能力分析から戦略的インサイトを生成し、
長期的な改善提案を行う。

PII保護: 集計メトリクス・カテゴリのみ。個人データは含まない。
"""

import json
import logging
from typing import Any, Dict, List, Optional

from .constants import (
    INSIGHT_RELEVANCE_THRESHOLD,
    MAX_INSIGHTS_PER_ANALYSIS,
    PREDICTION_HORIZON_DAYS,
    SNAPSHOT_RETENTION_DAYS,
    TABLE_BRAIN_ORG_SNAPSHOTS,
    TABLE_BRAIN_STRATEGIC_INSIGHTS,
    InsightType,
    SnapshotStatus,
)
from .models import (
    CapabilityEdge,
    EmergentBehavior,
    EmergenceResult,
    OrgSnapshot,
    StrategicInsight,
)

logger = logging.getLogger(__name__)


class StrategicAdvisor:
    """組織最適化・長期戦略の提案

    主な機能:
    1. generate_insights: 能力・創発データからインサイト生成
    2. save_insight: インサイトを保存
    3. get_recent_insights: 最近のインサイト取得
    4. create_snapshot: 組織状態のスナップショット作成
    5. get_snapshot_history: スナップショット履歴取得
    """

    def __init__(self, organization_id: str = ""):
        if not organization_id:
            raise ValueError("organization_id is required")
        self.organization_id = organization_id

    def generate_insights(
        self,
        edges: List[CapabilityEdge],
        behaviors: List[EmergentBehavior],
        capability_scores: Optional[Dict[str, float]] = None,
    ) -> List[StrategicInsight]:
        """能力グラフ・創発行動からインサイトを生成"""
        insights: List[StrategicInsight] = []
        scores = capability_scores or {}

        # 1. 弱い結合からの改善機会
        weak_edges = [e for e in edges if e.strength < 0.3]
        if weak_edges:
            weak_phases = set()
            for e in weak_edges:
                weak_phases.add(e.source_phase)
                weak_phases.add(e.target_phase)
            insights.append(StrategicInsight(
                organization_id=self.organization_id,
                insight_type=InsightType.OPPORTUNITY.value,
                title="Strengthen weak capability connections",
                description=f"Phases {sorted(weak_phases)} have weak interconnections that could benefit from focused integration",
                relevance_score=0.7,
                source_phases=sorted(weak_phases),
                actionable=True,
            ))

        # 2. 創発パターンからのトレンド
        if len(behaviors) >= 3:
            most_common_type = max(
                set(b.behavior_type for b in behaviors),
                key=lambda t: sum(1 for b in behaviors if b.behavior_type == t),
            )
            insights.append(StrategicInsight(
                organization_id=self.organization_id,
                insight_type=InsightType.TREND.value,
                title=f"Dominant emergent pattern: {most_common_type}",
                description=f"The organization shows a recurring {most_common_type} pattern across {len(behaviors)} detected behaviors",
                relevance_score=0.8,
                source_phases=sorted(set(
                    p for b in behaviors for p in b.involved_phases
                )),
                actionable=False,
            ))

        # 3. 低スコアのフェーズからリスク検知
        for phase, score in scores.items():
            if score < 0.3:
                insights.append(StrategicInsight(
                    organization_id=self.organization_id,
                    insight_type=InsightType.RISK.value,
                    title=f"Low capability score: Phase {phase}",
                    description=f"Phase {phase} has a score of {score:.2f}, which may limit overall brain effectiveness",
                    relevance_score=0.9,
                    source_phases=[phase],
                    actionable=True,
                ))

        # 4. 高パフォーマンスフェーズからの推薦
        strong_phases = [p for p, s in scores.items() if s >= 0.8]
        if strong_phases:
            insights.append(StrategicInsight(
                organization_id=self.organization_id,
                insight_type=InsightType.RECOMMENDATION.value,
                title="Leverage strong capabilities",
                description=f"Phases {strong_phases} are performing well. Consider using them as anchors for weaker capabilities.",
                relevance_score=0.6,
                source_phases=strong_phases,
                actionable=True,
            ))

        return insights[:MAX_INSIGHTS_PER_ANALYSIS]

    async def save_insight(
        self,
        conn: Any,
        insight: StrategicInsight,
    ) -> EmergenceResult:
        """インサイトを保存"""
        try:
            from sqlalchemy import text
            conn.execute(
                text(f"""
                    INSERT INTO {TABLE_BRAIN_STRATEGIC_INSIGHTS}
                    (organization_id, insight_type, title, description,
                     relevance_score, source_phases, actionable)
                    VALUES (:org_id, :itype, :title, :desc,
                            :relevance, :phases, :actionable)
                """),
                {
                    "org_id": self.organization_id,
                    "itype": insight.insight_type,
                    "title": insight.title,
                    "desc": insight.description,
                    "relevance": insight.relevance_score,
                    "phases": json.dumps(insight.source_phases),
                    "actionable": insight.actionable,
                },
            )
            logger.info("Insight saved: type=%s, title=%s", insight.insight_type, insight.title)
            return EmergenceResult(success=True, message="Insight saved")
        except Exception as e:
            logger.error("Failed to save insight: %s", e)
            return EmergenceResult(success=False, message=str(e))

    async def get_recent_insights(
        self,
        conn: Any,
        limit: int = 20,
    ) -> List[StrategicInsight]:
        """最近のインサイトを取得"""
        try:
            from sqlalchemy import text
            result = conn.execute(
                text(f"""
                    SELECT id, organization_id, insight_type, title, description,
                           relevance_score, source_phases, actionable, created_at
                    FROM {TABLE_BRAIN_STRATEGIC_INSIGHTS}
                    WHERE organization_id = :org_id
                    ORDER BY relevance_score DESC, created_at DESC
                    LIMIT :limit
                """),
                {"org_id": self.organization_id, "limit": limit},
            )
            rows = result.fetchall()
            insights = []
            for row in rows:
                phases_raw = row[6]
                if isinstance(phases_raw, str):
                    phases = json.loads(phases_raw)
                elif isinstance(phases_raw, list):
                    phases = phases_raw
                else:
                    phases = []

                insights.append(StrategicInsight(
                    id=str(row[0]),
                    organization_id=str(row[1]),
                    insight_type=row[2],
                    title=row[3] or "",
                    description=row[4] or "",
                    relevance_score=float(row[5]) if row[5] else 0.0,
                    source_phases=phases,
                    actionable=bool(row[7]) if row[7] is not None else False,
                    created_at=row[8],
                ))
            return insights
        except Exception as e:
            logger.warning("Failed to get recent insights: %s", e)
            return []

    async def create_snapshot(
        self,
        conn: Any,
        capability_scores: Dict[str, float],
        active_edges: int = 0,
        emergent_count: int = 0,
        insight_count: int = 0,
    ) -> EmergenceResult:
        """組織状態のスナップショットを作成"""
        try:
            overall = (
                sum(capability_scores.values()) / len(capability_scores)
                if capability_scores else 0.0
            )

            from sqlalchemy import text
            conn.execute(
                text(f"""
                    INSERT INTO {TABLE_BRAIN_ORG_SNAPSHOTS}
                    (organization_id, capability_scores, overall_score,
                     active_edges, emergent_count, insight_count)
                    VALUES (:org_id, :scores, :overall,
                            :edges, :emergent, :insights)
                """),
                {
                    "org_id": self.organization_id,
                    "scores": json.dumps(capability_scores),
                    "overall": round(overall, 4),
                    "edges": active_edges,
                    "emergent": emergent_count,
                    "insights": insight_count,
                },
            )
            logger.info("Snapshot created: overall=%.4f, edges=%d", overall, active_edges)
            return EmergenceResult(success=True, message="Snapshot created")
        except Exception as e:
            logger.error("Failed to create snapshot: %s", e)
            return EmergenceResult(success=False, message=str(e))

    async def get_snapshot_history(
        self,
        conn: Any,
        limit: int = 10,
    ) -> List[OrgSnapshot]:
        """スナップショット履歴を取得"""
        try:
            from sqlalchemy import text
            result = conn.execute(
                text(f"""
                    SELECT id, organization_id, capability_scores, overall_score,
                           active_edges, emergent_count, insight_count,
                           status, created_at
                    FROM {TABLE_BRAIN_ORG_SNAPSHOTS}
                    WHERE organization_id = :org_id
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {"org_id": self.organization_id, "limit": limit},
            )
            rows = result.fetchall()
            snapshots = []
            for row in rows:
                scores_raw = row[2]
                if isinstance(scores_raw, str):
                    scores = json.loads(scores_raw)
                elif isinstance(scores_raw, dict):
                    scores = scores_raw
                else:
                    scores = {}

                snapshots.append(OrgSnapshot(
                    id=str(row[0]),
                    organization_id=str(row[1]),
                    capability_scores=scores,
                    overall_score=float(row[3]) if row[3] else 0.0,
                    active_edges=int(row[4]) if row[4] else 0,
                    emergent_count=int(row[5]) if row[5] else 0,
                    insight_count=int(row[6]) if row[6] else 0,
                    status=row[7] or SnapshotStatus.ACTIVE.value,
                    created_at=row[8],
                ))
            return snapshots
        except Exception as e:
            logger.warning("Failed to get snapshot history: %s", e)
            return []


def create_strategic_advisor(organization_id: str = "") -> StrategicAdvisor:
    """StrategicAdvisorのファクトリ関数"""
    return StrategicAdvisor(organization_id=organization_id)
