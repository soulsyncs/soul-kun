"""
Phase 2N: パフォーマンス分析エンジン

能力別メトリクスの計算、弱点特定、トレンド分析を行う。

PII保護: 集計値のみ扱う。個人のメッセージ本文・名前は保存しない。
"""

import logging
from typing import Any, Dict, List, Optional

from .constants import (
    METRIC_SCORE_DEFAULT,
    METRIC_WEIGHTS,
    MIN_SAMPLES_FOR_TREND,
    STRONG_POINT_THRESHOLD,
    TABLE_BRAIN_PERFORMANCE_METRICS,
    TREND_LOOKBACK_DAYS,
    WEAK_POINT_THRESHOLD,
    MetricType,
)
from .models import OptimizationResult, PerformanceMetric

logger = logging.getLogger(__name__)


class PerformanceAnalyzer:
    """能力別パフォーマンスの分析・弱点特定・トレンド分析

    主な機能:
    1. record_metric: メトリクスの記録
    2. get_latest_metrics: 最新メトリクスの取得
    3. identify_weak_points: 弱点の特定
    4. calculate_overall_score: 総合スコアの計算
    5. analyze_trend: トレンド分析
    """

    def __init__(self, organization_id: str = ""):
        if not organization_id:
            raise ValueError("organization_id is required")
        self.organization_id = organization_id

    async def record_metric(
        self,
        conn: Any,
        metric_type: MetricType,
        score: float,
        sample_count: int = 1,
    ) -> OptimizationResult:
        """メトリクスを記録"""
        try:
            from sqlalchemy import text
            conn.execute(
                text(f"""
                    INSERT INTO {TABLE_BRAIN_PERFORMANCE_METRICS}
                    (organization_id, metric_type, score, sample_count)
                    VALUES (:org_id, :metric_type, :score, :sample_count)
                """),
                {
                    "org_id": self.organization_id,
                    "metric_type": metric_type.value,
                    "score": max(0.0, min(1.0, score)),
                    "sample_count": sample_count,
                },
            )
            return OptimizationResult(success=True, message="Metric recorded")
        except Exception as e:
            logger.error("Failed to record metric %s: %s", metric_type.value, e)
            return OptimizationResult(success=False, message=str(e))

    async def get_latest_metrics(
        self,
        conn: Any,
    ) -> List[PerformanceMetric]:
        """各メトリクスタイプの最新値を取得"""
        try:
            from sqlalchemy import text
            result = conn.execute(
                text(f"""
                    SELECT DISTINCT ON (metric_type)
                           id, organization_id, metric_type, score, sample_count,
                           created_at
                    FROM {TABLE_BRAIN_PERFORMANCE_METRICS}
                    WHERE organization_id = :org_id
                    ORDER BY metric_type, created_at DESC
                """),
                {"org_id": self.organization_id},
            )
            rows = result.fetchall()
            return [
                PerformanceMetric(
                    id=str(row[0]),
                    organization_id=str(row[1]),
                    metric_type=MetricType(row[2]) if row[2] else MetricType.RESPONSE_QUALITY,
                    score=float(row[3]) if row[3] else METRIC_SCORE_DEFAULT,
                    sample_count=row[4] or 0,
                    created_at=row[5],
                )
                for row in rows
            ]
        except Exception as e:
            logger.warning("Failed to get latest metrics: %s", e)
            return []

    def identify_weak_points(
        self,
        metrics: List[PerformanceMetric],
    ) -> List[Dict[str, Any]]:
        """メトリクスから弱点を特定

        Args:
            metrics: 最新メトリクスリスト

        Returns:
            弱点リスト [{"metric_type": str, "score": float, "priority": int}]
        """
        weak_points = []
        for m in metrics:
            if m.score < WEAK_POINT_THRESHOLD:
                weak_points.append({
                    "metric_type": m.metric_type.value if isinstance(m.metric_type, MetricType) else m.metric_type,
                    "score": m.score,
                    "gap": WEAK_POINT_THRESHOLD - m.score,
                    "priority": 0 if m.score < 0.2 else 1,
                })

        # gapが大きい順にソート
        weak_points.sort(key=lambda x: x["gap"], reverse=True)
        return weak_points

    def identify_strong_points(
        self,
        metrics: List[PerformanceMetric],
    ) -> List[Dict[str, Any]]:
        """メトリクスから強みを特定"""
        strong_points = []
        for m in metrics:
            if m.score >= STRONG_POINT_THRESHOLD:
                strong_points.append({
                    "metric_type": m.metric_type.value if isinstance(m.metric_type, MetricType) else m.metric_type,
                    "score": m.score,
                })
        strong_points.sort(key=lambda x: x["score"], reverse=True)
        return strong_points

    def calculate_overall_score(
        self,
        metrics: List[PerformanceMetric],
    ) -> float:
        """メトリクスから加重平均の総合スコアを計算"""
        if not metrics:
            return METRIC_SCORE_DEFAULT

        total_weight = 0.0
        weighted_sum = 0.0
        for m in metrics:
            mt = m.metric_type.value if isinstance(m.metric_type, MetricType) else m.metric_type
            weight = METRIC_WEIGHTS.get(mt, 0.1)
            weighted_sum += m.score * weight
            total_weight += weight

        if total_weight == 0:
            return METRIC_SCORE_DEFAULT
        return round(weighted_sum / total_weight, 4)

    async def analyze_trend(
        self,
        conn: Any,
        metric_type: MetricType,
        lookback_days: int = TREND_LOOKBACK_DAYS,
    ) -> Dict[str, Any]:
        """指定メトリクスのトレンドを分析

        Returns:
            {"direction": str, "change": float, "samples": int, "data_points": int}
        """
        try:
            from sqlalchemy import text
            result = conn.execute(
                text(f"""
                    SELECT score, created_at
                    FROM {TABLE_BRAIN_PERFORMANCE_METRICS}
                    WHERE organization_id = :org_id
                      AND metric_type = :metric_type
                      AND created_at >= NOW() - make_interval(days => :lookback_days)
                    ORDER BY created_at ASC
                """),
                {
                    "org_id": self.organization_id,
                    "metric_type": metric_type.value,
                    "lookback_days": int(lookback_days),
                },
            )
            rows = result.fetchall()

            if len(rows) < MIN_SAMPLES_FOR_TREND:
                return {
                    "direction": "insufficient_data",
                    "change": 0.0,
                    "samples": len(rows),
                    "data_points": len(rows),
                }

            scores = [float(r[0]) for r in rows]
            first_half = sum(scores[:len(scores)//2]) / (len(scores)//2)
            second_half = sum(scores[len(scores)//2:]) / (len(scores) - len(scores)//2)
            change = second_half - first_half

            if change > 0.05:
                direction = "improving"
            elif change < -0.05:
                direction = "declining"
            else:
                direction = "stable"

            return {
                "direction": direction,
                "change": round(change, 4),
                "samples": len(rows),
                "data_points": len(rows),
            }
        except Exception as e:
            logger.warning("Failed to analyze trend for %s: %s", metric_type.value, e)
            return {"direction": "error", "change": 0.0, "samples": 0, "data_points": 0}


def create_performance_analyzer(organization_id: str = "") -> PerformanceAnalyzer:
    """PerformanceAnalyzerのファクトリ関数"""
    return PerformanceAnalyzer(organization_id=organization_id)
