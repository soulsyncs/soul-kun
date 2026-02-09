"""
Phase 2N: 自己最適化（Self-Optimization）のテスト

設計書: docs/17_brain_completion_roadmap.md セクション Phase 2N
"""

import pytest
from unittest.mock import MagicMock
from datetime import datetime

from lib.brain.self_optimization import (
    # Main class
    BrainSelfOptimization,
    create_self_optimization,
    is_self_optimization_enabled,
    # Components
    PerformanceAnalyzer,
    ImprovementPlanner,
    ExperimentRunner,
    AutoDeployer,
    # Models
    PerformanceMetric,
    ImprovementProposal,
    ABTest,
    DeploymentLog,
    OptimizationResult,
    # Enums
    MetricType,
    ProposalStatus,
    ABTestStatus,
    ABTestOutcome,
    DeploymentStatus,
    # Constants
    METRIC_SCORE_DEFAULT,
    WEAK_POINT_THRESHOLD,
    STRONG_POINT_THRESHOLD,
    AB_TEST_MIN_SAMPLE_SIZE,
    AB_TEST_CONFIDENCE_LEVEL,
    IMPROVEMENT_SIGNIFICANCE_THRESHOLD,
    REGRESSION_THRESHOLD,
    FEATURE_FLAG_SELF_OPTIMIZATION_ENABLED,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_conn():
    """Mock DB connection"""
    conn = MagicMock()
    conn.execute = MagicMock()
    return conn


@pytest.fixture
def optimizer():
    """BrainSelfOptimization instance"""
    return BrainSelfOptimization(organization_id="org_test_123")


@pytest.fixture
def analyzer():
    return PerformanceAnalyzer(organization_id="org_test_123")


@pytest.fixture
def planner():
    return ImprovementPlanner(organization_id="org_test_123")


@pytest.fixture
def runner():
    return ExperimentRunner(organization_id="org_test_123")


@pytest.fixture
def deployer():
    return AutoDeployer(organization_id="org_test_123")


@pytest.fixture
def sample_metrics():
    """Sample metrics list"""
    return [
        PerformanceMetric(metric_type=MetricType.RESPONSE_QUALITY, score=0.85, sample_count=100),
        PerformanceMetric(metric_type=MetricType.RESPONSE_TIME, score=0.3, sample_count=100),
        PerformanceMetric(metric_type=MetricType.USER_SATISFACTION, score=0.75, sample_count=50),
        PerformanceMetric(metric_type=MetricType.ERROR_RATE, score=0.2, sample_count=100),
    ]


@pytest.fixture
def sample_ab_test():
    """Sample A/B test with enough data"""
    return ABTest(
        organization_id="org_test_123",
        test_name="test_quality_v2",
        target_metric=MetricType.RESPONSE_QUALITY,
        variant_a_score=0.75,
        variant_b_score=0.82,
        variant_a_samples=100,
        variant_b_samples=100,
        status=ABTestStatus.RUNNING,
    )


# =============================================================================
# Test: BrainSelfOptimization (統合クラス)
# =============================================================================

class TestBrainSelfOptimization:

    def test_initialization(self, optimizer):
        assert optimizer.organization_id == "org_test_123"
        assert optimizer.analyzer is not None
        assert optimizer.planner is not None
        assert optimizer.experiment_runner is not None
        assert optimizer.deployer is not None

    def test_initialization_requires_org_id(self):
        with pytest.raises(ValueError, match="organization_id is required"):
            BrainSelfOptimization(organization_id="")

    def test_initialization_with_disabled_components(self):
        inst = BrainSelfOptimization(
            organization_id="org_test",
            enable_ab_testing=False,
            enable_auto_deploy=False,
        )
        assert inst.analyzer is not None  # always enabled
        assert inst.planner is not None  # always enabled
        assert inst.experiment_runner is None
        assert inst.deployer is None

    def test_disabled_ab_testing_returns_safe_defaults(self):
        inst = BrainSelfOptimization(
            organization_id="org_test",
            enable_ab_testing=False,
        )
        result = inst.analyze_test_results(ABTest())
        assert result["outcome"] == "disabled"

    def test_disabled_deployer_returns_safe_defaults(self):
        inst = BrainSelfOptimization(
            organization_id="org_test",
            enable_auto_deploy=False,
        )
        result = inst.check_regression(0.5, 0.3)
        assert result["action"] == "disabled"


# =============================================================================
# Test: Factory & Feature Flag
# =============================================================================

class TestFactoryAndFlags:

    def test_create_self_optimization(self):
        inst = create_self_optimization(organization_id="org_test")
        assert isinstance(inst, BrainSelfOptimization)

    def test_create_with_feature_flags(self):
        inst = create_self_optimization(
            organization_id="org_test",
            feature_flags={"ENABLE_AB_TESTING": False},
        )
        assert inst.experiment_runner is None

    def test_is_enabled_true(self):
        assert is_self_optimization_enabled({FEATURE_FLAG_SELF_OPTIMIZATION_ENABLED: True}) is True

    def test_is_enabled_false(self):
        assert is_self_optimization_enabled({FEATURE_FLAG_SELF_OPTIMIZATION_ENABLED: False}) is False

    def test_is_enabled_none(self):
        assert is_self_optimization_enabled(None) is False


# =============================================================================
# Test: PerformanceAnalyzer (sync logic)
# =============================================================================

class TestPerformanceAnalyzer:

    def test_initialization(self, analyzer):
        assert analyzer.organization_id == "org_test_123"

    def test_initialization_requires_org_id(self):
        with pytest.raises(ValueError):
            PerformanceAnalyzer(organization_id="")

    def test_identify_weak_points(self, analyzer, sample_metrics):
        weak = analyzer.identify_weak_points(sample_metrics)
        assert len(weak) == 2  # response_time (0.3) and error_rate (0.2)
        assert weak[0]["metric_type"] == "error_rate"  # largest gap first
        assert weak[0]["score"] == 0.2

    def test_identify_weak_points_empty(self, analyzer):
        weak = analyzer.identify_weak_points([])
        assert weak == []

    def test_identify_strong_points(self, analyzer, sample_metrics):
        strong = analyzer.identify_strong_points(sample_metrics)
        assert len(strong) == 2  # response_quality (0.85) and user_satisfaction (0.75)
        assert strong[0]["score"] == 0.85

    def test_calculate_overall_score(self, analyzer, sample_metrics):
        score = analyzer.calculate_overall_score(sample_metrics)
        assert 0.0 <= score <= 1.0
        # Weighted average should be reasonable
        assert score > 0.3  # not all weak
        assert score < 0.9  # not all strong

    def test_calculate_overall_score_empty(self, analyzer):
        score = analyzer.calculate_overall_score([])
        assert score == METRIC_SCORE_DEFAULT


# =============================================================================
# Test: ImprovementPlanner (sync logic)
# =============================================================================

class TestImprovementPlanner:

    def test_initialization(self, planner):
        assert planner.organization_id == "org_test_123"

    def test_generate_proposal(self, planner):
        weak_point = {"metric_type": "error_rate", "score": 0.2, "gap": 0.2, "priority": 0}
        proposal = planner.generate_proposal(weak_point)
        assert proposal.target_metric == MetricType.ERROR_RATE
        assert proposal.expected_improvement > 0
        assert proposal.status == ProposalStatus.DRAFT

    def test_generate_proposal_unknown_type(self, planner):
        weak_point = {"metric_type": "unknown_metric", "score": 0.1, "gap": 0.3, "priority": 1}
        proposal = planner.generate_proposal(weak_point)
        assert proposal.target_metric == MetricType.RESPONSE_QUALITY  # fallback

    def test_prioritize_proposals(self, planner):
        proposals = [
            ImprovementProposal(priority=2, expected_improvement=0.1),
            ImprovementProposal(priority=0, expected_improvement=0.2),
            ImprovementProposal(priority=0, expected_improvement=0.15),
        ]
        sorted_proposals = planner.prioritize_proposals(proposals)
        assert sorted_proposals[0].expected_improvement == 0.2  # highest improvement in priority 0
        assert sorted_proposals[2].priority == 2  # lowest priority last

    def test_is_significant_improvement(self, planner):
        assert planner.is_significant_improvement(0.5, 0.56) is True
        assert planner.is_significant_improvement(0.5, 0.52) is False


# =============================================================================
# Test: ExperimentRunner (sync logic)
# =============================================================================

class TestExperimentRunner:

    def test_initialization(self, runner):
        assert runner.organization_id == "org_test_123"

    def test_analyze_results_insufficient_data(self, runner):
        test = ABTest(variant_a_samples=10, variant_b_samples=5)
        result = runner.analyze_results(test)
        assert result["outcome"] == ABTestOutcome.INCONCLUSIVE.value
        assert result["ready"] is False

    def test_analyze_results_variant_b_wins(self, runner, sample_ab_test):
        result = runner.analyze_results(sample_ab_test)
        assert result["outcome"] == ABTestOutcome.VARIANT_B_WINS.value
        assert result["confidence"] > 0

    def test_analyze_results_no_difference(self, runner):
        test = ABTest(
            variant_a_score=0.75, variant_b_score=0.76,
            variant_a_samples=100, variant_b_samples=100,
        )
        result = runner.analyze_results(test)
        assert result["outcome"] == ABTestOutcome.NO_DIFFERENCE.value

    def test_analyze_results_variant_a_wins(self, runner):
        test = ABTest(
            variant_a_score=0.85, variant_b_score=0.70,
            variant_a_samples=100, variant_b_samples=100,
        )
        result = runner.analyze_results(test)
        assert result["outcome"] == ABTestOutcome.VARIANT_A_WINS.value


# =============================================================================
# Test: AutoDeployer (sync logic)
# =============================================================================

class TestAutoDeployer:

    def test_initialization(self, deployer):
        assert deployer.organization_id == "org_test_123"

    def test_check_regression_none(self, deployer):
        result = deployer.check_regression(0.7, 0.72)
        assert result["is_regression"] is False
        assert result["action"] == "continue"

    def test_check_regression_detected(self, deployer):
        result = deployer.check_regression(0.7, 0.6)
        assert result["is_regression"] is True
        assert result["action"] == "rollback"

    def test_check_regression_boundary(self, deployer):
        # Exactly at threshold (delta == -REGRESSION_THRESHOLD should trigger)
        result = deployer.check_regression(0.75, 0.75 - REGRESSION_THRESHOLD)
        assert result["is_regression"] is True
        assert result["action"] == "rollback"

    def test_check_regression_just_above_threshold(self, deployer):
        # Just above threshold (not a regression)
        result = deployer.check_regression(0.75, 0.75 - REGRESSION_THRESHOLD + 0.001)
        assert result["is_regression"] is False


# =============================================================================
# Test: Models
# =============================================================================

class TestModels:

    def test_performance_metric_defaults(self):
        m = PerformanceMetric()
        assert m.id is not None
        assert m.score == METRIC_SCORE_DEFAULT
        assert m.metric_type == MetricType.RESPONSE_QUALITY

    def test_performance_metric_to_dict(self):
        m = PerformanceMetric(organization_id="org1", score=0.9)
        d = m.to_dict()
        assert d["organization_id"] == "org1"
        assert d["score"] == 0.9

    def test_improvement_proposal_defaults(self):
        p = ImprovementProposal()
        assert p.status == ProposalStatus.DRAFT
        assert p.priority == 0

    def test_ab_test_defaults(self):
        t = ABTest()
        assert t.status == ABTestStatus.CREATED
        assert t.traffic_split == 0.5

    def test_ab_test_to_dict(self):
        t = ABTest(test_name="test1", organization_id="org1")
        d = t.to_dict()
        assert d["test_name"] == "test1"
        assert d["status"] == "created"

    def test_deployment_log_defaults(self):
        d = DeploymentLog()
        assert d.status == DeploymentStatus.CANARY

    def test_optimization_result(self):
        r = OptimizationResult(success=True, message="OK")
        assert r.success is True

    def test_all_enum_values(self):
        assert len(MetricType) == 6
        assert len(ProposalStatus) == 7
        assert len(ABTestStatus) == 5
        assert len(ABTestOutcome) == 4
        assert len(DeploymentStatus) == 5


# =============================================================================
# Test: Async DB操作 — PerformanceAnalyzer
# =============================================================================

class TestPerformanceAnalyzerDB:

    @pytest.mark.asyncio
    async def test_record_metric_success(self, analyzer, mock_conn):
        result = await analyzer.record_metric(mock_conn, MetricType.RESPONSE_QUALITY, 0.85, 10)
        assert result.success is True
        params = mock_conn.execute.call_args[0][1]
        assert params["org_id"] == "org_test_123"
        assert params["metric_type"] == "response_quality"
        assert params["score"] == 0.85

    @pytest.mark.asyncio
    async def test_record_metric_clamps_score(self, analyzer, mock_conn):
        result = await analyzer.record_metric(mock_conn, MetricType.ERROR_RATE, 1.5)
        assert result.success is True
        params = mock_conn.execute.call_args[0][1]
        assert params["score"] == 1.0  # clamped

    @pytest.mark.asyncio
    async def test_record_metric_db_error(self, analyzer, mock_conn):
        mock_conn.execute.side_effect = Exception("insert error")
        result = await analyzer.record_metric(mock_conn, MetricType.RESPONSE_QUALITY, 0.5)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_get_latest_metrics_found(self, analyzer, mock_conn):
        mock_conn.execute.return_value.fetchall.return_value = [
            ("uuid-1", "org_test_123", "response_quality", 0.85, 100, datetime(2026, 1, 1)),
            ("uuid-2", "org_test_123", "error_rate", 0.1, 50, datetime(2026, 1, 1)),
        ]
        metrics = await analyzer.get_latest_metrics(mock_conn)
        assert len(metrics) == 2
        assert metrics[0].score == 0.85

    @pytest.mark.asyncio
    async def test_get_latest_metrics_empty(self, analyzer, mock_conn):
        mock_conn.execute.return_value.fetchall.return_value = []
        metrics = await analyzer.get_latest_metrics(mock_conn)
        assert metrics == []

    @pytest.mark.asyncio
    async def test_get_latest_metrics_db_error(self, analyzer, mock_conn):
        mock_conn.execute.side_effect = Exception("read error")
        metrics = await analyzer.get_latest_metrics(mock_conn)
        assert metrics == []

    @pytest.mark.asyncio
    async def test_analyze_trend_insufficient(self, analyzer, mock_conn):
        mock_conn.execute.return_value.fetchall.return_value = [(0.5, datetime(2026, 1, 1))]
        result = await analyzer.analyze_trend(mock_conn, MetricType.RESPONSE_QUALITY)
        assert result["direction"] == "insufficient_data"

    @pytest.mark.asyncio
    async def test_analyze_trend_improving(self, analyzer, mock_conn):
        """トレンドが改善傾向の場合"""
        # 5+ data points with second half higher than first half
        data_points = [
            (0.50, datetime(2026, 1, 1)),
            (0.52, datetime(2026, 1, 2)),
            (0.55, datetime(2026, 1, 3)),
            (0.70, datetime(2026, 1, 4)),
            (0.75, datetime(2026, 1, 5)),
            (0.80, datetime(2026, 1, 6)),
        ]
        mock_conn.execute.return_value.fetchall.return_value = data_points
        result = await analyzer.analyze_trend(mock_conn, MetricType.RESPONSE_QUALITY)
        assert result["direction"] == "improving"
        assert result["change"] > 0
        assert result["data_points"] == 6

    @pytest.mark.asyncio
    async def test_analyze_trend_declining(self, analyzer, mock_conn):
        """トレンドが低下傾向の場合"""
        data_points = [
            (0.80, datetime(2026, 1, 1)),
            (0.75, datetime(2026, 1, 2)),
            (0.70, datetime(2026, 1, 3)),
            (0.55, datetime(2026, 1, 4)),
            (0.50, datetime(2026, 1, 5)),
        ]
        mock_conn.execute.return_value.fetchall.return_value = data_points
        result = await analyzer.analyze_trend(mock_conn, MetricType.RESPONSE_QUALITY)
        assert result["direction"] == "declining"
        assert result["change"] < 0

    @pytest.mark.asyncio
    async def test_analyze_trend_stable(self, analyzer, mock_conn):
        """トレンドが安定している場合"""
        data_points = [
            (0.60, datetime(2026, 1, 1)),
            (0.61, datetime(2026, 1, 2)),
            (0.59, datetime(2026, 1, 3)),
            (0.60, datetime(2026, 1, 4)),
            (0.61, datetime(2026, 1, 5)),
        ]
        mock_conn.execute.return_value.fetchall.return_value = data_points
        result = await analyzer.analyze_trend(mock_conn, MetricType.RESPONSE_QUALITY)
        assert result["direction"] == "stable"

    @pytest.mark.asyncio
    async def test_analyze_trend_db_error(self, analyzer, mock_conn):
        mock_conn.execute.side_effect = Exception("query error")
        result = await analyzer.analyze_trend(mock_conn, MetricType.RESPONSE_QUALITY)
        assert result["direction"] == "error"


# =============================================================================
# Test: Async DB操作 — ImprovementPlanner
# =============================================================================

class TestImprovementPlannerDB:

    @pytest.mark.asyncio
    async def test_save_proposal_success(self, planner, mock_conn):
        proposal = ImprovementProposal(
            organization_id="org_test_123",
            title="Improve response time",
            target_metric=MetricType.RESPONSE_TIME,
        )
        result = await planner.save_proposal(mock_conn, proposal)
        assert result.success is True
        params = mock_conn.execute.call_args[0][1]
        assert params["org_id"] == "org_test_123"

    @pytest.mark.asyncio
    async def test_save_proposal_db_error(self, planner, mock_conn):
        mock_conn.execute.side_effect = Exception("insert error")
        result = await planner.save_proposal(mock_conn, ImprovementProposal())
        assert result.success is False

    @pytest.mark.asyncio
    async def test_get_active_proposals_found(self, planner, mock_conn):
        mock_conn.execute.return_value.fetchall.return_value = [
            ("uuid-1", "org_test_123", "Improve X", "response_quality", "hypo",
             0.1, "draft", 0, None, None, datetime(2026, 1, 1), None),
        ]
        proposals = await planner.get_active_proposals(mock_conn)
        assert len(proposals) == 1
        assert proposals[0].title == "Improve X"

    @pytest.mark.asyncio
    async def test_get_active_proposals_empty(self, planner, mock_conn):
        mock_conn.execute.return_value.fetchall.return_value = []
        proposals = await planner.get_active_proposals(mock_conn)
        assert proposals == []

    @pytest.mark.asyncio
    async def test_update_proposal_status_success(self, planner, mock_conn):
        result = await planner.update_proposal_status(
            mock_conn, "uuid-1", ProposalStatus.APPROVED,
        )
        assert result.success is True
        assert "approved" in result.message

    @pytest.mark.asyncio
    async def test_update_proposal_status_db_error(self, planner, mock_conn):
        mock_conn.execute.side_effect = Exception("update error")
        result = await planner.update_proposal_status(mock_conn, "uuid-1", ProposalStatus.REJECTED)
        assert result.success is False


# =============================================================================
# Test: Async DB操作 — ExperimentRunner
# =============================================================================

class TestExperimentRunnerDB:

    @pytest.mark.asyncio
    async def test_create_test_success(self, runner, mock_conn):
        result = await runner.create_test(
            mock_conn, "test_v2", MetricType.RESPONSE_QUALITY,
        )
        assert result.success is True
        params = mock_conn.execute.call_args[0][1]
        assert params["org_id"] == "org_test_123"
        assert params["test_name"] == "test_v2"

    @pytest.mark.asyncio
    async def test_create_test_db_error(self, runner, mock_conn):
        mock_conn.execute.side_effect = Exception("insert error")
        result = await runner.create_test(mock_conn, "test", MetricType.ERROR_RATE)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_get_active_tests_found(self, runner, mock_conn):
        mock_conn.execute.return_value.fetchall.return_value = [
            ("uuid-1", "org_test_123", "test_v2", None, "response_quality",
             "control", "treatment", 0.5, "running",
             0.75, 0.80, 50, 50, None, None,
             datetime(2026, 1, 1), None, datetime(2026, 1, 1)),
        ]
        tests = await runner.get_active_tests(mock_conn)
        assert len(tests) == 1
        assert tests[0].test_name == "test_v2"

    @pytest.mark.asyncio
    async def test_get_active_tests_empty(self, runner, mock_conn):
        mock_conn.execute.return_value.fetchall.return_value = []
        tests = await runner.get_active_tests(mock_conn)
        assert tests == []

    @pytest.mark.asyncio
    async def test_record_observation_variant_a(self, runner, mock_conn):
        result = await runner.record_observation(mock_conn, "uuid-1", False, 0.8)
        assert result.success is True
        sql_str = str(mock_conn.execute.call_args[0][0])
        assert "variant_a_samples" in sql_str

    @pytest.mark.asyncio
    async def test_record_observation_variant_b(self, runner, mock_conn):
        result = await runner.record_observation(mock_conn, "uuid-1", True, 0.9)
        assert result.success is True
        sql_str = str(mock_conn.execute.call_args[0][0])
        assert "variant_b_samples" in sql_str

    @pytest.mark.asyncio
    async def test_record_observation_db_error(self, runner, mock_conn):
        mock_conn.execute.side_effect = Exception("update error")
        result = await runner.record_observation(mock_conn, "uuid-1", True, 0.5)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_complete_test_success(self, runner, mock_conn):
        result = await runner.complete_test(
            mock_conn, "uuid-1", ABTestOutcome.VARIANT_B_WINS, 0.95,
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_pause_test_success(self, runner, mock_conn):
        result = await runner.pause_test(mock_conn, "uuid-1")
        assert result.success is True
        params = mock_conn.execute.call_args[0][1]
        assert params["status"] == "paused"

    @pytest.mark.asyncio
    async def test_pause_test_db_error(self, runner, mock_conn):
        mock_conn.execute.side_effect = Exception("update error")
        result = await runner.pause_test(mock_conn, "uuid-1")
        assert result.success is False


# =============================================================================
# Test: Async DB操作 — AutoDeployer
# =============================================================================

class TestAutoDeployerDB:

    @pytest.mark.asyncio
    async def test_start_canary_success(self, deployer, mock_conn):
        result = await deployer.start_canary(mock_conn, "proposal-1", pre_deploy_score=0.7)
        assert result.success is True
        params = mock_conn.execute.call_args[0][1]
        assert params["org_id"] == "org_test_123"
        assert params["proposal_id"] == "proposal-1"

    @pytest.mark.asyncio
    async def test_start_canary_db_error(self, deployer, mock_conn):
        mock_conn.execute.side_effect = Exception("insert error")
        result = await deployer.start_canary(mock_conn, "proposal-1")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_promote_to_full_success(self, deployer, mock_conn):
        result = await deployer.promote_to_full(mock_conn, "deploy-1", post_deploy_score=0.8)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_promote_to_full_not_found(self, deployer, mock_conn):
        mock_conn.execute.return_value.rowcount = 0
        result = await deployer.promote_to_full(mock_conn, "nonexistent-id")
        assert result.success is False
        assert "not found" in result.message.lower()

    @pytest.mark.asyncio
    async def test_promote_to_full_db_error(self, deployer, mock_conn):
        mock_conn.execute.side_effect = Exception("update error")
        result = await deployer.promote_to_full(mock_conn, "deploy-1")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_rollback_success(self, deployer, mock_conn):
        result = await deployer.rollback(mock_conn, "deploy-1", "regression detected")
        assert result.success is True
        params = mock_conn.execute.call_args[0][1]
        assert params["status"] == "rolled_back"
        assert params["reason"] == "regression detected"

    @pytest.mark.asyncio
    async def test_rollback_db_error(self, deployer, mock_conn):
        mock_conn.execute.side_effect = Exception("update error")
        result = await deployer.rollback(mock_conn, "deploy-1", "reason")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_get_deployment_history_found(self, deployer, mock_conn):
        mock_conn.execute.return_value.fetchall.return_value = [
            ("uuid-d1", "org_test_123", "prop-1", None, "full",
             0.7, 0.8, 0.1, None,
             datetime(2026, 1, 1), datetime(2026, 1, 2), datetime(2026, 1, 1)),
        ]
        history = await deployer.get_deployment_history(mock_conn)
        assert len(history) == 1
        assert history[0].status == DeploymentStatus.FULL

    @pytest.mark.asyncio
    async def test_get_deployment_history_empty(self, deployer, mock_conn):
        mock_conn.execute.return_value.fetchall.return_value = []
        history = await deployer.get_deployment_history(mock_conn)
        assert history == []

    @pytest.mark.asyncio
    async def test_get_deployment_history_db_error(self, deployer, mock_conn):
        mock_conn.execute.side_effect = Exception("read error")
        history = await deployer.get_deployment_history(mock_conn)
        assert history == []


# =============================================================================
# Test: 統合クラスDB委譲
# =============================================================================

class TestBrainSelfOptimizationDB:

    @pytest.mark.asyncio
    async def test_record_metric_delegates(self, optimizer, mock_conn):
        result = await optimizer.record_metric(mock_conn, MetricType.ERROR_RATE, 0.1)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_get_latest_metrics_delegates(self, optimizer, mock_conn):
        mock_conn.execute.return_value.fetchall.return_value = []
        metrics = await optimizer.get_latest_metrics(mock_conn)
        assert metrics == []

    @pytest.mark.asyncio
    async def test_create_ab_test_delegates(self, optimizer, mock_conn):
        result = await optimizer.create_ab_test(mock_conn, "test1", MetricType.RESPONSE_QUALITY)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_start_canary_delegates(self, optimizer, mock_conn):
        result = await optimizer.start_canary_deploy(mock_conn, "prop-1")
        assert result.success is True

    @pytest.mark.asyncio
    async def test_get_deployment_history_delegates(self, optimizer, mock_conn):
        mock_conn.execute.return_value.fetchall.return_value = []
        history = await optimizer.get_deployment_history(mock_conn)
        assert history == []
