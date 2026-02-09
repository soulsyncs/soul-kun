"""
Phase 2N: 改善立案エンジン

改善機会の検出、仮説生成、優先順位付けを行う。

PII保護: 改善提案はカテゴリレベルのみ。個人のメッセージ本文は含まない。
"""

import logging
from typing import Any, Dict, List, Optional

from .constants import (
    IMPROVEMENT_SIGNIFICANCE_THRESHOLD,
    MAX_ACTIVE_PROPOSALS,
    TABLE_BRAIN_IMPROVEMENT_PROPOSALS,
    MetricType,
    ProposalStatus,
)
from .models import ImprovementProposal, OptimizationResult

logger = logging.getLogger(__name__)


class ImprovementPlanner:
    """改善機会の検出・仮説生成・優先順位付け

    主な機能:
    1. generate_proposal: 弱点から改善提案を生成
    2. get_active_proposals: アクティブな提案を取得
    3. update_proposal_status: 提案ステータスを更新
    4. prioritize_proposals: 提案の優先順位付け
    """

    def __init__(self, organization_id: str = ""):
        if not organization_id:
            raise ValueError("organization_id is required")
        self.organization_id = organization_id

    def generate_proposal(
        self,
        weak_point: Dict[str, Any],
    ) -> ImprovementProposal:
        """弱点から改善提案を生成

        Args:
            weak_point: {"metric_type": str, "score": float, "gap": float, "priority": int}

        Returns:
            ImprovementProposal
        """
        metric_type_str = weak_point.get("metric_type", "response_quality")
        gap = weak_point.get("gap", 0.1)
        priority = weak_point.get("priority", 1)

        # メトリクスタイプごとの改善仮説テンプレート
        hypothesis_map = {
            MetricType.RESPONSE_QUALITY.value: "Improve response accuracy by refining context retrieval",
            MetricType.RESPONSE_TIME.value: "Reduce latency by optimizing query patterns",
            MetricType.USER_SATISFACTION.value: "Enhance user experience by adapting communication style",
            MetricType.TASK_COMPLETION.value: "Improve task success rate by better understanding intent",
            MetricType.ERROR_RATE.value: "Reduce errors by strengthening input validation",
            MetricType.ESCALATION_RATE.value: "Reduce escalations by improving confidence calibration",
        }

        try:
            mt = MetricType(metric_type_str)
        except ValueError:
            mt = MetricType.RESPONSE_QUALITY

        return ImprovementProposal(
            organization_id=self.organization_id,
            title=f"Improve {metric_type_str} (gap: {gap:.2f})",
            target_metric=mt,
            hypothesis=hypothesis_map.get(metric_type_str, "General improvement needed"),
            expected_improvement=min(gap, 0.2),
            status=ProposalStatus.DRAFT,
            priority=priority,
        )

    async def save_proposal(
        self,
        conn: Any,
        proposal: ImprovementProposal,
    ) -> OptimizationResult:
        """提案をDBに保存"""
        try:
            from sqlalchemy import text
            conn.execute(
                text(f"""
                    INSERT INTO {TABLE_BRAIN_IMPROVEMENT_PROPOSALS}
                    (organization_id, title, target_metric, hypothesis,
                     expected_improvement, status, priority)
                    VALUES (:org_id, :title, :target_metric, :hypothesis,
                            :expected_improvement, :status, :priority)
                """),
                {
                    "org_id": self.organization_id,
                    "title": proposal.title,
                    "target_metric": proposal.target_metric.value,
                    "hypothesis": proposal.hypothesis,
                    "expected_improvement": proposal.expected_improvement,
                    "status": proposal.status.value,
                    "priority": proposal.priority,
                },
            )
            return OptimizationResult(success=True, message="Proposal saved")
        except Exception as e:
            logger.error("Failed to save proposal: %s", e)
            return OptimizationResult(success=False, message=str(e))

    async def get_active_proposals(
        self,
        conn: Any,
    ) -> List[ImprovementProposal]:
        """アクティブな提案を取得"""
        try:
            from sqlalchemy import text
            result = conn.execute(
                text(f"""
                    SELECT id, organization_id, title, target_metric, hypothesis,
                           expected_improvement, status, priority, actual_improvement,
                           ab_test_id, created_at, updated_at
                    FROM {TABLE_BRAIN_IMPROVEMENT_PROPOSALS}
                    WHERE organization_id = :org_id
                      AND status NOT IN ('rejected', 'rolled_back')
                    ORDER BY priority ASC, created_at DESC
                    LIMIT :limit
                """),
                {"org_id": self.organization_id, "limit": MAX_ACTIVE_PROPOSALS},
            )
            rows = result.fetchall()
            return [
                ImprovementProposal(
                    id=str(row[0]),
                    organization_id=str(row[1]),
                    title=row[2] or "",
                    target_metric=MetricType(row[3]) if row[3] else MetricType.RESPONSE_QUALITY,
                    hypothesis=row[4] or "",
                    expected_improvement=float(row[5]) if row[5] else 0.0,
                    status=ProposalStatus(row[6]) if row[6] else ProposalStatus.DRAFT,
                    priority=row[7] or 0,
                    actual_improvement=float(row[8]) if row[8] else None,
                    ab_test_id=str(row[9]) if row[9] else None,
                    created_at=row[10],
                    updated_at=row[11],
                )
                for row in rows
            ]
        except Exception as e:
            logger.warning("Failed to get active proposals: %s", e)
            return []

    async def update_proposal_status(
        self,
        conn: Any,
        proposal_id: str,
        new_status: ProposalStatus,
        actual_improvement: Optional[float] = None,
        ab_test_id: Optional[str] = None,
    ) -> OptimizationResult:
        """提案のステータスを更新"""
        try:
            from sqlalchemy import text
            params: Dict[str, Any] = {
                "org_id": self.organization_id,
                "proposal_id": proposal_id,
                "status": new_status.value,
            }

            set_clauses = ["status = :status", "updated_at = NOW()"]
            if actual_improvement is not None:
                set_clauses.append("actual_improvement = :actual")
                params["actual"] = actual_improvement
            if ab_test_id is not None:
                set_clauses.append("ab_test_id = :ab_test_id")
                params["ab_test_id"] = ab_test_id

            conn.execute(
                text(f"""
                    UPDATE {TABLE_BRAIN_IMPROVEMENT_PROPOSALS}
                    SET {', '.join(set_clauses)}
                    WHERE organization_id = :org_id AND id = :proposal_id::uuid
                """),
                params,
            )
            return OptimizationResult(success=True, message=f"Proposal status updated to {new_status.value}")
        except Exception as e:
            logger.error("Failed to update proposal %s: %s", proposal_id, e)
            return OptimizationResult(success=False, message=str(e))

    def prioritize_proposals(
        self,
        proposals: List[ImprovementProposal],
    ) -> List[ImprovementProposal]:
        """提案の優先順位付け（期待改善効果が高い順）"""
        return sorted(
            proposals,
            key=lambda p: (p.priority, -p.expected_improvement),
        )

    def is_significant_improvement(
        self,
        before: float,
        after: float,
    ) -> bool:
        """改善が統計的に有意かを判定"""
        return (after - before) >= IMPROVEMENT_SIGNIFICANCE_THRESHOLD


def create_improvement_planner(organization_id: str = "") -> ImprovementPlanner:
    """ImprovementPlannerのファクトリ関数"""
    return ImprovementPlanner(organization_id=organization_id)
