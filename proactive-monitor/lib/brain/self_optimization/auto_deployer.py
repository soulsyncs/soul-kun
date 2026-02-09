"""
Phase 2N: 自動デプロイエンジン

成功施策のカナリアデプロイ、メトリクス監視、回帰検知、ロールバックを行う。

PII保護: デプロイログにはメトリクス集計値のみ。個人データは含まない。
"""

import logging
from typing import Any, Dict, List, Optional

from .constants import (
    CANARY_MONITORING_HOURS,
    CANARY_PERCENTAGE,
    REGRESSION_THRESHOLD,
    TABLE_BRAIN_DEPLOYMENT_LOGS,
    DeploymentStatus,
)
from .models import DeploymentLog, OptimizationResult

logger = logging.getLogger(__name__)


class AutoDeployer:
    """成功施策の展開・監視・ロールバック

    主な機能:
    1. start_canary: カナリアデプロイ開始
    2. check_regression: 回帰検知
    3. promote_to_full: 全展開に昇格
    4. rollback: ロールバック実行
    5. get_deployment_history: デプロイ履歴取得
    """

    def __init__(self, organization_id: str = ""):
        if not organization_id:
            raise ValueError("organization_id is required")
        self.organization_id = organization_id

    async def start_canary(
        self,
        conn: Any,
        proposal_id: str,
        ab_test_id: Optional[str] = None,
        pre_deploy_score: Optional[float] = None,
    ) -> OptimizationResult:
        """カナリアデプロイを開始"""
        try:
            from sqlalchemy import text
            conn.execute(
                text(f"""
                    INSERT INTO {TABLE_BRAIN_DEPLOYMENT_LOGS}
                    (organization_id, proposal_id, ab_test_id, status,
                     pre_deploy_score, deployed_at)
                    VALUES (:org_id, :proposal_id, :ab_test_id, :status,
                            :pre_score, NOW())
                """),
                {
                    "org_id": self.organization_id,
                    "proposal_id": proposal_id,
                    "ab_test_id": ab_test_id,
                    "status": DeploymentStatus.CANARY.value,
                    "pre_score": pre_deploy_score,
                },
            )
            logger.info(
                "Canary deploy started for proposal %s (%.0f%% traffic)",
                proposal_id, CANARY_PERCENTAGE * 100,
            )
            return OptimizationResult(success=True, message="Canary deployment started")
        except Exception as e:
            logger.error("Failed to start canary for proposal %s: %s", proposal_id, e)
            return OptimizationResult(success=False, message=str(e))

    def check_regression(
        self,
        pre_score: float,
        current_score: float,
    ) -> Dict[str, Any]:
        """回帰を検知

        Returns:
            {"is_regression": bool, "delta": float, "action": str}
        """
        delta = current_score - pre_score

        if delta <= -REGRESSION_THRESHOLD:
            return {
                "is_regression": True,
                "delta": round(delta, 4),
                "action": "rollback",
                "reason": f"Score dropped by {abs(delta):.4f} (threshold: {REGRESSION_THRESHOLD})",
            }

        return {
            "is_regression": False,
            "delta": round(delta, 4),
            "action": "continue",
            "reason": "No regression detected",
        }

    async def promote_to_full(
        self,
        conn: Any,
        deployment_id: str,
        post_deploy_score: Optional[float] = None,
    ) -> OptimizationResult:
        """カナリアから全展開に昇格"""
        try:
            from sqlalchemy import text
            params: Dict[str, Any] = {
                "org_id": self.organization_id,
                "deployment_id": deployment_id,
                "status": DeploymentStatus.FULL.value,
            }
            set_clauses = ["status = :status", "completed_at = NOW()"]

            if post_deploy_score is not None:
                set_clauses.append("post_deploy_score = :post_score")
                set_clauses.append("improvement_delta = :post_score - pre_deploy_score")
                params["post_score"] = post_deploy_score

            result = conn.execute(
                text(f"""
                    UPDATE {TABLE_BRAIN_DEPLOYMENT_LOGS}
                    SET {', '.join(set_clauses)}
                    WHERE organization_id = :org_id AND id = :deployment_id::uuid
                """),
                params,
            )
            if result.rowcount == 0:
                logger.warning("No deployment found for id=%s org=%s", deployment_id, self.organization_id)
                return OptimizationResult(success=False, message="Deployment not found")
            return OptimizationResult(success=True, message="Promoted to full deployment")
        except Exception as e:
            logger.error("Failed to promote deployment %s: %s", deployment_id, e)
            return OptimizationResult(success=False, message=str(e))

    async def rollback(
        self,
        conn: Any,
        deployment_id: str,
        reason: str,
    ) -> OptimizationResult:
        """デプロイをロールバック"""
        try:
            from sqlalchemy import text
            conn.execute(
                text(f"""
                    UPDATE {TABLE_BRAIN_DEPLOYMENT_LOGS}
                    SET status = :status, rollback_reason = :reason, completed_at = NOW()
                    WHERE organization_id = :org_id AND id = :deployment_id::uuid
                """),
                {
                    "org_id": self.organization_id,
                    "deployment_id": deployment_id,
                    "status": DeploymentStatus.ROLLED_BACK.value,
                    "reason": reason,
                },
            )
            logger.warning("Deployment %s rolled back: %s", deployment_id, reason)
            return OptimizationResult(success=True, message=f"Rolled back: {reason}")
        except Exception as e:
            logger.error("Failed to rollback deployment %s: %s", deployment_id, e)
            return OptimizationResult(success=False, message=str(e))

    async def get_deployment_history(
        self,
        conn: Any,
        limit: int = 20,
    ) -> List[DeploymentLog]:
        """デプロイ履歴を取得"""
        try:
            from sqlalchemy import text
            result = conn.execute(
                text(f"""
                    SELECT id, organization_id, proposal_id, ab_test_id, status,
                           pre_deploy_score, post_deploy_score, improvement_delta,
                           rollback_reason, deployed_at, completed_at, created_at
                    FROM {TABLE_BRAIN_DEPLOYMENT_LOGS}
                    WHERE organization_id = :org_id
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {"org_id": self.organization_id, "limit": limit},
            )
            rows = result.fetchall()
            return [
                DeploymentLog(
                    id=str(row[0]),
                    organization_id=str(row[1]),
                    proposal_id=str(row[2]) if row[2] else None,
                    ab_test_id=str(row[3]) if row[3] else None,
                    status=DeploymentStatus(row[4]) if row[4] else DeploymentStatus.CANARY,
                    pre_deploy_score=float(row[5]) if row[5] else None,
                    post_deploy_score=float(row[6]) if row[6] else None,
                    improvement_delta=float(row[7]) if row[7] else None,
                    rollback_reason=row[8],
                    deployed_at=row[9],
                    completed_at=row[10],
                    created_at=row[11],
                )
                for row in rows
            ]
        except Exception as e:
            logger.warning("Failed to get deployment history: %s", e)
            return []


def create_auto_deployer(organization_id: str = "") -> AutoDeployer:
    """AutoDeployerのファクトリ関数"""
    return AutoDeployer(organization_id=organization_id)
