"""
Phase 2N: 自己最適化（Self-Optimization）- データモデル

設計書: docs/17_brain_completion_roadmap.md セクション Phase 2N

パフォーマンス指標、改善提案、A/Bテスト、デプロイログのデータモデル定義。

PII保護: メトリクスは集計値のみ。個人のメッセージ本文・名前は保存しない。
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .constants import (
    DeploymentStatus,
    MetricType,
    METRIC_SCORE_DEFAULT,
    ProposalStatus,
    ABTestOutcome,
    ABTestStatus,
)


# ============================================================================
# パフォーマンス指標
# ============================================================================

@dataclass
class PerformanceMetric:
    """能力別パフォーマンス指標

    PII保護: 集計値のみ保存。個人のメッセージ本文は含まない。
    """
    id: Optional[str] = None
    organization_id: Optional[str] = None

    # メトリクス情報
    metric_type: MetricType = MetricType.RESPONSE_QUALITY
    score: float = METRIC_SCORE_DEFAULT
    sample_count: int = 0

    # トレンド
    previous_score: Optional[float] = None
    trend_direction: str = "stable"  # "improving", "declining", "stable"

    # メタデータ
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    created_at: Optional[datetime] = None

    def __post_init__(self):
        if self.id is None:
            self.id = str(uuid4())
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "metric_type": self.metric_type.value if isinstance(self.metric_type, MetricType) else self.metric_type,
            "score": self.score,
            "sample_count": self.sample_count,
            "previous_score": self.previous_score,
            "trend_direction": self.trend_direction,
            "period_start": self.period_start.isoformat() if self.period_start else None,
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================================
# 改善提案
# ============================================================================

@dataclass
class ImprovementProposal:
    """改善施策の提案・管理

    PII保護: 対象は能力カテゴリのみ。個人情報は含まない。
    """
    id: Optional[str] = None
    organization_id: Optional[str] = None

    # 提案内容
    title: str = ""
    target_metric: MetricType = MetricType.RESPONSE_QUALITY
    hypothesis: str = ""  # 改善仮説（カテゴリレベル）
    expected_improvement: float = 0.0

    # ステータス
    status: ProposalStatus = ProposalStatus.DRAFT
    priority: int = 0  # 0=最高, 数値が大きいほど低い

    # 結果
    actual_improvement: Optional[float] = None
    ab_test_id: Optional[str] = None

    # タイムスタンプ
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def __post_init__(self):
        if self.id is None:
            self.id = str(uuid4())
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "title": self.title,
            "target_metric": self.target_metric.value if isinstance(self.target_metric, MetricType) else self.target_metric,
            "hypothesis": self.hypothesis,
            "expected_improvement": self.expected_improvement,
            "status": self.status.value if isinstance(self.status, ProposalStatus) else self.status,
            "priority": self.priority,
            "actual_improvement": self.actual_improvement,
            "ab_test_id": self.ab_test_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ============================================================================
# A/Bテスト
# ============================================================================

@dataclass
class ABTest:
    """A/Bテスト定義・結果

    PII保護: ユーザー割当はuser_idのみ。バリアントは戦略タイプ名のみ。
    """
    id: Optional[str] = None
    organization_id: Optional[str] = None

    # テスト定義
    test_name: str = ""
    proposal_id: Optional[str] = None
    target_metric: MetricType = MetricType.RESPONSE_QUALITY

    # バリアント（戦略タイプ名のみ、PII含まず）
    variant_a_description: str = "control"
    variant_b_description: str = "treatment"
    traffic_split: float = 0.5  # variant_bの割合

    # ステータス
    status: ABTestStatus = ABTestStatus.CREATED

    # 結果
    variant_a_score: Optional[float] = None
    variant_b_score: Optional[float] = None
    variant_a_samples: int = 0
    variant_b_samples: int = 0
    outcome: Optional[ABTestOutcome] = None
    confidence: Optional[float] = None

    # タイムスタンプ
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    def __post_init__(self):
        if self.id is None:
            self.id = str(uuid4())
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "test_name": self.test_name,
            "proposal_id": self.proposal_id,
            "target_metric": self.target_metric.value if isinstance(self.target_metric, MetricType) else self.target_metric,
            "variant_a_description": self.variant_a_description,
            "variant_b_description": self.variant_b_description,
            "traffic_split": self.traffic_split,
            "status": self.status.value if isinstance(self.status, ABTestStatus) else self.status,
            "variant_a_score": self.variant_a_score,
            "variant_b_score": self.variant_b_score,
            "variant_a_samples": self.variant_a_samples,
            "variant_b_samples": self.variant_b_samples,
            "outcome": self.outcome.value if isinstance(self.outcome, ABTestOutcome) else self.outcome,
            "confidence": self.confidence,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================================
# デプロイログ
# ============================================================================

@dataclass
class DeploymentLog:
    """改善施策の展開ログ

    PII保護: 施策IDとメトリクスのみ。個人情報は含まない。
    """
    id: Optional[str] = None
    organization_id: Optional[str] = None

    # デプロイ情報
    proposal_id: Optional[str] = None
    ab_test_id: Optional[str] = None
    status: DeploymentStatus = DeploymentStatus.CANARY

    # メトリクス
    pre_deploy_score: Optional[float] = None
    post_deploy_score: Optional[float] = None
    improvement_delta: Optional[float] = None
    rollback_reason: Optional[str] = None

    # タイムスタンプ
    deployed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    def __post_init__(self):
        if self.id is None:
            self.id = str(uuid4())
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "proposal_id": self.proposal_id,
            "ab_test_id": self.ab_test_id,
            "status": self.status.value if isinstance(self.status, DeploymentStatus) else self.status,
            "pre_deploy_score": self.pre_deploy_score,
            "post_deploy_score": self.post_deploy_score,
            "improvement_delta": self.improvement_delta,
            "rollback_reason": self.rollback_reason,
            "deployed_at": self.deployed_at.isoformat() if self.deployed_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================================
# 結果モデル
# ============================================================================

@dataclass
class OptimizationResult:
    """自己最適化機能の結果を返すモデル"""
    success: bool = True
    message: str = ""
    data: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
