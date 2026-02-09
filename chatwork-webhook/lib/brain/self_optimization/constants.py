"""
Phase 2N: 自己最適化（Self-Optimization）- 定数定義

設計書: docs/17_brain_completion_roadmap.md セクション Phase 2N

パフォーマンス分析、改善立案、A/Bテスト、自動展開に関する定数。
"""

from enum import Enum
from typing import Dict


# ============================================================================
# テーブル名
# ============================================================================

TABLE_BRAIN_PERFORMANCE_METRICS = "brain_performance_metrics"
TABLE_BRAIN_IMPROVEMENT_PROPOSALS = "brain_improvement_proposals"
TABLE_BRAIN_AB_TESTS = "brain_ab_tests"
TABLE_BRAIN_DEPLOYMENT_LOGS = "brain_deployment_logs"


# ============================================================================
# Feature Flags
# ============================================================================

FEATURE_FLAG_SELF_OPTIMIZATION_ENABLED = "ENABLE_SELF_OPTIMIZATION"
FEATURE_FLAG_AB_TESTING_ENABLED = "ENABLE_AB_TESTING"
FEATURE_FLAG_AUTO_DEPLOY_ENABLED = "ENABLE_AUTO_DEPLOY"


# ============================================================================
# Enums
# ============================================================================

class MetricType(str, Enum):
    """パフォーマンス指標タイプ"""
    RESPONSE_QUALITY = "response_quality"
    RESPONSE_TIME = "response_time"
    USER_SATISFACTION = "user_satisfaction"
    TASK_COMPLETION = "task_completion"
    ERROR_RATE = "error_rate"
    ESCALATION_RATE = "escalation_rate"


class ProposalStatus(str, Enum):
    """改善提案のステータス"""
    DRAFT = "draft"
    PROPOSED = "proposed"
    APPROVED = "approved"
    TESTING = "testing"
    DEPLOYED = "deployed"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"


class TestStatus(str, Enum):
    """A/Bテストのステータス"""
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TestOutcome(str, Enum):
    """A/Bテストの結果"""
    VARIANT_A_WINS = "variant_a_wins"
    VARIANT_B_WINS = "variant_b_wins"
    NO_DIFFERENCE = "no_difference"
    INCONCLUSIVE = "inconclusive"


class DeploymentStatus(str, Enum):
    """デプロイのステータス"""
    CANARY = "canary"
    ROLLING = "rolling"
    FULL = "full"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


# ============================================================================
# 閾値・パラメータ
# ============================================================================

# パフォーマンス分析
TREND_LOOKBACK_DAYS: int = 30
WEAK_POINT_THRESHOLD: float = 0.4
STRONG_POINT_THRESHOLD: float = 0.7
METRIC_SCORE_DEFAULT: float = 0.5
MIN_SAMPLES_FOR_TREND: int = 5

# 改善提案
MAX_ACTIVE_PROPOSALS: int = 10
IMPROVEMENT_SIGNIFICANCE_THRESHOLD: float = 0.05  # 5%改善で有意

# A/Bテスト
AB_TEST_MIN_SAMPLE_SIZE: int = 50
AB_TEST_CONFIDENCE_LEVEL: float = 0.95
AB_TEST_MAX_DURATION_DAYS: int = 14
AB_TEST_DEFAULT_TRAFFIC_SPLIT: float = 0.5

# 自動デプロイ
CANARY_PERCENTAGE: float = 0.1  # カナリア段階で10%に展開
CANARY_MONITORING_HOURS: int = 24
REGRESSION_THRESHOLD: float = 0.05  # 5%回帰で自動ロールバック

# メトリクス重み
METRIC_WEIGHTS: Dict[str, float] = {
    MetricType.RESPONSE_QUALITY.value: 0.25,
    MetricType.RESPONSE_TIME.value: 0.15,
    MetricType.USER_SATISFACTION.value: 0.25,
    MetricType.TASK_COMPLETION.value: 0.20,
    MetricType.ERROR_RATE.value: 0.10,
    MetricType.ESCALATION_RATE.value: 0.05,
}
