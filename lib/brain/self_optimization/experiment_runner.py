"""
Phase 2N: A/Bテスト実行エンジン

A/Bテストの作成、バリアント割当、結果分析、勝者判定を行う。

PII保護: ユーザー割当はuser_idのみ。バリアント名は戦略タイプ名のみ。
"""

import logging
import math
from typing import Any, Dict, List, Optional

from .constants import (
    AB_TEST_CONFIDENCE_LEVEL,
    AB_TEST_DEFAULT_TRAFFIC_SPLIT,
    AB_TEST_MIN_SAMPLE_SIZE,
    TABLE_BRAIN_AB_TESTS,
    MetricType,
    ABTestOutcome,
    ABTestStatus,
)
from .models import ABTest, OptimizationResult

logger = logging.getLogger(__name__)


class ExperimentRunner:
    """A/Bテストの作成・実行・結果分析

    主な機能:
    1. create_test: テスト作成
    2. get_active_tests: アクティブなテスト取得
    3. record_observation: テスト結果の記録
    4. analyze_results: 結果分析・勝者判定
    5. complete_test: テスト完了
    """

    def __init__(self, organization_id: str = ""):
        if not organization_id:
            raise ValueError("organization_id is required")
        self.organization_id = organization_id

    async def create_test(
        self,
        conn: Any,
        test_name: str,
        target_metric: MetricType,
        variant_a_desc: str = "control",
        variant_b_desc: str = "treatment",
        proposal_id: Optional[str] = None,
        traffic_split: float = AB_TEST_DEFAULT_TRAFFIC_SPLIT,
    ) -> OptimizationResult:
        """A/Bテストを作成"""
        try:
            from sqlalchemy import text
            conn.execute(
                text(f"""
                    INSERT INTO {TABLE_BRAIN_AB_TESTS}
                    (organization_id, test_name, target_metric,
                     variant_a_description, variant_b_description,
                     traffic_split, status, proposal_id, started_at)
                    VALUES (:org_id, :test_name, :target_metric,
                            :variant_a, :variant_b,
                            :split, :status, :proposal_id, NOW())
                    ON CONFLICT (organization_id, test_name) DO NOTHING
                """),
                {
                    "org_id": self.organization_id,
                    "test_name": test_name,
                    "target_metric": target_metric.value,
                    "variant_a": variant_a_desc,
                    "variant_b": variant_b_desc,
                    "split": traffic_split,
                    "status": ABTestStatus.RUNNING.value,
                    "proposal_id": proposal_id,
                },
            )
            return OptimizationResult(success=True, message=f"Test '{test_name}' created")
        except Exception as e:
            logger.error("Failed to create test '%s': %s", test_name, e)
            return OptimizationResult(success=False, message=type(e).__name__)

    async def get_active_tests(
        self,
        conn: Any,
    ) -> List[ABTest]:
        """アクティブなテスト一覧を取得"""
        try:
            from sqlalchemy import text
            result = conn.execute(
                text(f"""
                    SELECT id, organization_id, test_name, proposal_id, target_metric,
                           variant_a_description, variant_b_description, traffic_split,
                           status, variant_a_score, variant_b_score,
                           variant_a_samples, variant_b_samples,
                           outcome, confidence, started_at, completed_at, created_at
                    FROM {TABLE_BRAIN_AB_TESTS}
                    WHERE organization_id = :org_id
                      AND status IN ('running', 'created')
                    ORDER BY created_at DESC
                """),
                {"org_id": self.organization_id},
            )
            rows = result.fetchall()
            return [
                ABTest(
                    id=str(row[0]),
                    organization_id=str(row[1]),
                    test_name=row[2] or "",
                    proposal_id=str(row[3]) if row[3] else None,
                    target_metric=MetricType(row[4]) if row[4] else MetricType.RESPONSE_QUALITY,
                    variant_a_description=row[5] or "control",
                    variant_b_description=row[6] or "treatment",
                    traffic_split=float(row[7]) if row[7] else 0.5,
                    status=ABTestStatus(row[8]) if row[8] else ABTestStatus.CREATED,
                    variant_a_score=float(row[9]) if row[9] else None,
                    variant_b_score=float(row[10]) if row[10] else None,
                    variant_a_samples=row[11] or 0,
                    variant_b_samples=row[12] or 0,
                    outcome=ABTestOutcome(row[13]) if row[13] else None,
                    confidence=float(row[14]) if row[14] else None,
                    started_at=row[15],
                    completed_at=row[16],
                    created_at=row[17],
                )
                for row in rows
            ]
        except Exception as e:
            logger.warning("Failed to get active tests: %s", e)
            return []

    async def record_observation(
        self,
        conn: Any,
        test_id: str,
        is_variant_b: bool,
        score: float,
    ) -> OptimizationResult:
        """テストの観測結果を記録（running averageで更新）"""
        try:
            from sqlalchemy import text
            if is_variant_b:
                conn.execute(
                    text(f"""
                        UPDATE {TABLE_BRAIN_AB_TESTS}
                        SET variant_b_samples = variant_b_samples + 1,
                            variant_b_score = CASE
                                WHEN variant_b_samples = 0 THEN :score
                                ELSE (variant_b_score * variant_b_samples + :score) / (variant_b_samples + 1)
                            END
                        WHERE organization_id = :org_id AND id = :test_id::uuid
                    """),
                    {"org_id": self.organization_id, "test_id": test_id, "score": score},
                )
            else:
                conn.execute(
                    text(f"""
                        UPDATE {TABLE_BRAIN_AB_TESTS}
                        SET variant_a_samples = variant_a_samples + 1,
                            variant_a_score = CASE
                                WHEN variant_a_samples = 0 THEN :score
                                ELSE (variant_a_score * variant_a_samples + :score) / (variant_a_samples + 1)
                            END
                        WHERE organization_id = :org_id AND id = :test_id::uuid
                    """),
                    {"org_id": self.organization_id, "test_id": test_id, "score": score},
                )
            return OptimizationResult(success=True, message="Observation recorded")
        except Exception as e:
            logger.error("Failed to record observation for test %s: %s", test_id, e)
            return OptimizationResult(success=False, message=type(e).__name__)

    def analyze_results(
        self,
        test: ABTest,
    ) -> Dict[str, Any]:
        """テスト結果を分析し、勝者を判定

        Returns:
            {"outcome": str, "confidence": float, "ready": bool, "reason": str}
        """
        if test.variant_a_samples < AB_TEST_MIN_SAMPLE_SIZE or test.variant_b_samples < AB_TEST_MIN_SAMPLE_SIZE:
            return {
                "outcome": ABTestOutcome.INCONCLUSIVE.value,
                "confidence": 0.0,
                "ready": False,
                "reason": f"Insufficient samples (A={test.variant_a_samples}, B={test.variant_b_samples}, min={AB_TEST_MIN_SAMPLE_SIZE})",
            }

        score_a = test.variant_a_score or 0.0
        score_b = test.variant_b_score or 0.0
        diff = score_b - score_a

        # 簡易的な信頼度計算（標本数に基づく）
        total_samples = test.variant_a_samples + test.variant_b_samples
        confidence = min(0.99, 1.0 - 1.0 / math.sqrt(max(1, total_samples)))

        if abs(diff) < 0.02:
            outcome = ABTestOutcome.NO_DIFFERENCE
        elif diff > 0:
            outcome = ABTestOutcome.VARIANT_B_WINS
        else:
            outcome = ABTestOutcome.VARIANT_A_WINS

        ready = confidence >= AB_TEST_CONFIDENCE_LEVEL

        return {
            "outcome": outcome.value,
            "confidence": round(confidence, 4),
            "ready": ready,
            "reason": f"A={score_a:.4f}, B={score_b:.4f}, diff={diff:.4f}, confidence={confidence:.4f}",
            "score_a": score_a,
            "score_b": score_b,
            "diff": diff,
        }

    async def complete_test(
        self,
        conn: Any,
        test_id: str,
        outcome: ABTestOutcome,
        confidence: float,
    ) -> OptimizationResult:
        """テストを完了状態に更新"""
        try:
            from sqlalchemy import text
            conn.execute(
                text(f"""
                    UPDATE {TABLE_BRAIN_AB_TESTS}
                    SET status = :status, outcome = :outcome,
                        confidence = :confidence, completed_at = NOW()
                    WHERE organization_id = :org_id AND id = :test_id::uuid
                """),
                {
                    "org_id": self.organization_id,
                    "test_id": test_id,
                    "status": ABTestStatus.COMPLETED.value,
                    "outcome": outcome.value,
                    "confidence": confidence,
                },
            )
            return OptimizationResult(success=True, message=f"Test completed: {outcome.value}")
        except Exception as e:
            logger.error("Failed to complete test %s: %s", test_id, e)
            return OptimizationResult(success=False, message=type(e).__name__)

    async def pause_test(
        self,
        conn: Any,
        test_id: str,
    ) -> OptimizationResult:
        """テストを一時停止（障害時のセーフガード）"""
        try:
            from sqlalchemy import text
            conn.execute(
                text(f"""
                    UPDATE {TABLE_BRAIN_AB_TESTS}
                    SET status = :status
                    WHERE organization_id = :org_id AND id = :test_id::uuid
                """),
                {
                    "org_id": self.organization_id,
                    "test_id": test_id,
                    "status": ABTestStatus.PAUSED.value,
                },
            )
            logger.info("Test %s paused (safety measure)", test_id)
            return OptimizationResult(success=True, message="Test paused")
        except Exception as e:
            logger.error("Failed to pause test %s: %s", test_id, e)
            return OptimizationResult(success=False, message=type(e).__name__)


def create_experiment_runner(organization_id: str = "") -> ExperimentRunner:
    """ExperimentRunnerのファクトリ関数"""
    return ExperimentRunner(organization_id=organization_id)
