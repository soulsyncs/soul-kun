"""
Phase 2N: 自己最適化（Self-Optimization）モジュール

設計書: docs/17_brain_completion_roadmap.md セクション Phase 2N

自分の性能を分析して自動的に改善する。
A/Bテストで何が効果的か実験し、成功施策を自動展開する。

使用例:
    from lib.brain.self_optimization import BrainSelfOptimization, create_self_optimization

    # 統合クラスを使用
    optimizer = create_self_optimization(organization_id="org_xxx")

    # パフォーマンス記録
    await optimizer.record_metric(conn, MetricType.RESPONSE_QUALITY, 0.85)

    # 弱点分析
    metrics = await optimizer.get_latest_metrics(conn)
    weak_points = optimizer.identify_weak_points(metrics)

    # A/Bテスト実行
    await optimizer.create_ab_test(conn, "test_name", MetricType.RESPONSE_QUALITY)
"""

import logging
from typing import Any, Dict, List, Optional

from .constants import (
    # Feature flags
    FEATURE_FLAG_AB_TESTING_ENABLED,
    FEATURE_FLAG_AUTO_DEPLOY_ENABLED,
    FEATURE_FLAG_SELF_OPTIMIZATION_ENABLED,
    # Enums
    DeploymentStatus,
    MetricType,
    ProposalStatus,
    ABTestOutcome,
    ABTestStatus,
    # Thresholds
    AB_TEST_CONFIDENCE_LEVEL,
    AB_TEST_MIN_SAMPLE_SIZE,
    CANARY_PERCENTAGE,
    IMPROVEMENT_SIGNIFICANCE_THRESHOLD,
    MAX_ACTIVE_PROPOSALS,
    METRIC_SCORE_DEFAULT,
    REGRESSION_THRESHOLD,
    STRONG_POINT_THRESHOLD,
    WEAK_POINT_THRESHOLD,
    # Tables
    TABLE_BRAIN_AB_TESTS,
    TABLE_BRAIN_DEPLOYMENT_LOGS,
    TABLE_BRAIN_IMPROVEMENT_PROPOSALS,
    TABLE_BRAIN_PERFORMANCE_METRICS,
)
from .models import (
    ABTest,
    DeploymentLog,
    ImprovementProposal,
    OptimizationResult,
    PerformanceMetric,
)
from .performance_analyzer import PerformanceAnalyzer, create_performance_analyzer
from .improvement_planner import ImprovementPlanner, create_improvement_planner
from .experiment_runner import ExperimentRunner, create_experiment_runner
from .auto_deployer import AutoDeployer, create_auto_deployer

logger = logging.getLogger(__name__)


# =============================================================================
# 統合クラス
# =============================================================================

class BrainSelfOptimization:
    """Phase 2N: 自己最適化の統合クラス

    4つのコンポーネントを統合して提供する:
    1. PerformanceAnalyzer（パフォーマンス分析）
    2. ImprovementPlanner（改善立案）
    3. ExperimentRunner（A/Bテスト実行）
    4. AutoDeployer（自動デプロイ）
    """

    def __init__(
        self,
        organization_id: str = "",
        enable_ab_testing: bool = True,
        enable_auto_deploy: bool = True,
    ):
        if not organization_id:
            raise ValueError("organization_id is required")
        self.organization_id = organization_id

        # コンポーネント初期化
        self.analyzer = PerformanceAnalyzer(organization_id=organization_id)
        self.planner = ImprovementPlanner(organization_id=organization_id)
        self.experiment_runner = ExperimentRunner(organization_id=organization_id) if enable_ab_testing else None
        self.deployer = AutoDeployer(organization_id=organization_id) if enable_auto_deploy else None

        logger.info(
            "BrainSelfOptimization initialized: org=%s, ab_testing=%s, auto_deploy=%s",
            organization_id,
            enable_ab_testing,
            enable_auto_deploy,
        )

    # =========================================================================
    # パフォーマンス分析
    # =========================================================================

    async def record_metric(
        self,
        conn: Any,
        metric_type: MetricType,
        score: float,
        sample_count: int = 1,
    ) -> OptimizationResult:
        """メトリクスを記録"""
        return await self.analyzer.record_metric(conn, metric_type, score, sample_count)

    async def get_latest_metrics(
        self,
        conn: Any,
    ) -> List[PerformanceMetric]:
        """最新メトリクスを取得"""
        return await self.analyzer.get_latest_metrics(conn)

    def identify_weak_points(
        self,
        metrics: List[PerformanceMetric],
    ) -> List[Dict[str, Any]]:
        """弱点を特定"""
        return self.analyzer.identify_weak_points(metrics)

    def identify_strong_points(
        self,
        metrics: List[PerformanceMetric],
    ) -> List[Dict[str, Any]]:
        """強みを特定"""
        return self.analyzer.identify_strong_points(metrics)

    def calculate_overall_score(
        self,
        metrics: List[PerformanceMetric],
    ) -> float:
        """総合スコアを計算"""
        return self.analyzer.calculate_overall_score(metrics)

    async def analyze_trend(
        self,
        conn: Any,
        metric_type: MetricType,
    ) -> Dict[str, Any]:
        """トレンド分析"""
        return await self.analyzer.analyze_trend(conn, metric_type)

    # =========================================================================
    # 改善立案
    # =========================================================================

    def generate_proposal(
        self,
        weak_point: Dict[str, Any],
    ) -> ImprovementProposal:
        """弱点から改善提案を生成"""
        return self.planner.generate_proposal(weak_point)

    async def save_proposal(
        self,
        conn: Any,
        proposal: ImprovementProposal,
    ) -> OptimizationResult:
        """提案を保存"""
        return await self.planner.save_proposal(conn, proposal)

    async def get_active_proposals(
        self,
        conn: Any,
    ) -> List[ImprovementProposal]:
        """アクティブな提案を取得"""
        return await self.planner.get_active_proposals(conn)

    # =========================================================================
    # A/Bテスト
    # =========================================================================

    async def create_ab_test(
        self,
        conn: Any,
        test_name: str,
        target_metric: MetricType,
        variant_a_desc: str = "control",
        variant_b_desc: str = "treatment",
        proposal_id: Optional[str] = None,
    ) -> OptimizationResult:
        """A/Bテストを作成"""
        if self.experiment_runner is None:
            return OptimizationResult(success=False, message="A/B testing disabled")
        return await self.experiment_runner.create_test(
            conn, test_name, target_metric, variant_a_desc, variant_b_desc, proposal_id,
        )

    async def get_active_tests(
        self,
        conn: Any,
    ) -> List[ABTest]:
        """アクティブなテスト取得"""
        if self.experiment_runner is None:
            return []
        return await self.experiment_runner.get_active_tests(conn)

    def analyze_test_results(
        self,
        test: ABTest,
    ) -> Dict[str, Any]:
        """テスト結果を分析"""
        if self.experiment_runner is None:
            return {"outcome": "disabled", "confidence": 0.0, "ready": False, "reason": "A/B testing disabled"}
        return self.experiment_runner.analyze_results(test)

    # =========================================================================
    # デプロイ
    # =========================================================================

    async def start_canary_deploy(
        self,
        conn: Any,
        proposal_id: str,
        ab_test_id: Optional[str] = None,
        pre_deploy_score: Optional[float] = None,
    ) -> OptimizationResult:
        """カナリアデプロイを開始"""
        if self.deployer is None:
            return OptimizationResult(success=False, message="Auto-deploy disabled")
        return await self.deployer.start_canary(conn, proposal_id, ab_test_id, pre_deploy_score)

    def check_regression(
        self,
        pre_score: float,
        current_score: float,
    ) -> Dict[str, Any]:
        """回帰検知"""
        if self.deployer is None:
            return {"is_regression": False, "delta": 0.0, "action": "disabled", "reason": "Auto-deploy disabled"}
        return self.deployer.check_regression(pre_score, current_score)

    async def get_deployment_history(
        self,
        conn: Any,
    ) -> List[DeploymentLog]:
        """デプロイ履歴取得"""
        if self.deployer is None:
            return []
        return await self.deployer.get_deployment_history(conn)


# =============================================================================
# ファクトリ関数
# =============================================================================

def create_self_optimization(
    organization_id: str = "",
    feature_flags: Optional[Dict[str, bool]] = None,
) -> BrainSelfOptimization:
    """BrainSelfOptimizationのファクトリ関数"""
    flags = feature_flags or {}
    return BrainSelfOptimization(
        organization_id=organization_id,
        enable_ab_testing=flags.get(FEATURE_FLAG_AB_TESTING_ENABLED, True),
        enable_auto_deploy=flags.get(FEATURE_FLAG_AUTO_DEPLOY_ENABLED, True),
    )


def is_self_optimization_enabled(feature_flags: Optional[Dict[str, bool]] = None) -> bool:
    """Phase 2Nが有効かチェック"""
    if feature_flags is None:
        return False
    return feature_flags.get(FEATURE_FLAG_SELF_OPTIMIZATION_ENABLED, False)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Main class
    "BrainSelfOptimization",
    "create_self_optimization",
    "is_self_optimization_enabled",
    # Components
    "PerformanceAnalyzer",
    "create_performance_analyzer",
    "ImprovementPlanner",
    "create_improvement_planner",
    "ExperimentRunner",
    "create_experiment_runner",
    "AutoDeployer",
    "create_auto_deployer",
    # Enums
    "MetricType",
    "ProposalStatus",
    "ABTestStatus",
    "ABTestOutcome",
    "DeploymentStatus",
    # Models
    "PerformanceMetric",
    "ImprovementProposal",
    "ABTest",
    "DeploymentLog",
    "OptimizationResult",
    # Constants
    "METRIC_SCORE_DEFAULT",
    "WEAK_POINT_THRESHOLD",
    "STRONG_POINT_THRESHOLD",
    "AB_TEST_MIN_SAMPLE_SIZE",
    "AB_TEST_CONFIDENCE_LEVEL",
    "IMPROVEMENT_SIGNIFICANCE_THRESHOLD",
    "CANARY_PERCENTAGE",
    "REGRESSION_THRESHOLD",
    "MAX_ACTIVE_PROPOSALS",
    # Tables
    "TABLE_BRAIN_PERFORMANCE_METRICS",
    "TABLE_BRAIN_IMPROVEMENT_PROPOSALS",
    "TABLE_BRAIN_AB_TESTS",
    "TABLE_BRAIN_DEPLOYMENT_LOGS",
    # Feature flags
    "FEATURE_FLAG_SELF_OPTIMIZATION_ENABLED",
    "FEATURE_FLAG_AB_TESTING_ENABLED",
    "FEATURE_FLAG_AUTO_DEPLOY_ENABLED",
]

__version__ = "1.0.0"
