"""
Phase 2H: 自己認識（Self-Awareness）- データモデル

設計書: docs/17_brain_completion_roadmap.md セクション Phase 2H

能力スコア、限界情報、改善ログ、自己診断のデータモデル定義。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .constants import (
    ABILITY_SCORE_DEFAULT,
    AbilityCategory,
    AbilityLevel,
    ConfidenceLevel,
    DiagnosisType,
    EscalationReason,
    ImprovementType,
    LimitationType,
    ABILITY_LEVEL_THRESHOLDS,
    CONFIDENCE_LEVEL_THRESHOLDS,
)


# ============================================================================
# 能力モデル
# ============================================================================

@dataclass
class Ability:
    """能力定義

    ソウルくんが持つ特定の能力を定義する。
    """
    # 識別情報
    id: Optional[str] = None
    organization_id: Optional[str] = None

    # 能力情報
    category: AbilityCategory = AbilityCategory.GENERAL
    name: str = ""
    description: Optional[str] = None

    # メタデータ
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def __post_init__(self):
        if self.id is None:
            self.id = str(uuid4())
        if self.created_at is None:
            self.created_at = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "category": self.category.value if isinstance(self.category, AbilityCategory) else self.category,
            "name": self.name,
            "description": self.description,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


@dataclass
class AbilityScore:
    """能力スコア

    特定の能力に対するスコアを記録する。
    """
    # 識別情報
    id: Optional[str] = None
    organization_id: Optional[str] = None
    ability_id: Optional[str] = None
    user_id: Optional[str] = None  # NULLなら組織全体のスコア

    # スコア情報
    category: AbilityCategory = AbilityCategory.GENERAL
    score: float = ABILITY_SCORE_DEFAULT
    sample_count: int = 0
    success_count: int = 0
    failure_count: int = 0

    # 履歴
    previous_score: Optional[float] = None
    score_change: float = 0.0

    # メタデータ
    last_evaluated_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def __post_init__(self):
        if self.id is None:
            self.id = str(uuid4())
        if self.created_at is None:
            self.created_at = datetime.now()

    @property
    def level(self) -> AbilityLevel:
        """スコアから能力レベルを判定"""
        for level, (low, high) in ABILITY_LEVEL_THRESHOLDS.items():
            if low <= self.score < high:
                return level
        return AbilityLevel.UNKNOWN

    @property
    def is_strong(self) -> bool:
        """得意分野か"""
        return self.score >= 0.7

    @property
    def is_weak(self) -> bool:
        """苦手分野か"""
        return self.score < 0.4

    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.sample_count == 0:
            return 0.0
        return self.success_count / self.sample_count

    def update_score(self, success: bool, weight: float = 0.1) -> float:
        """スコアを更新

        Args:
            success: 成功したか
            weight: 更新の重み

        Returns:
            更新後のスコア
        """
        self.previous_score = self.score
        self.sample_count += 1

        if success:
            self.success_count += 1
            # 成功時: スコアを上げる（1.0に近づける）
            self.score = self.score + (1.0 - self.score) * weight
        else:
            self.failure_count += 1
            # 失敗時: スコアを下げる（0に近づける）
            self.score = self.score * (1.0 - weight)

        self.score_change = self.score - self.previous_score
        self.last_evaluated_at = datetime.now()
        return self.score

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "ability_id": self.ability_id,
            "user_id": self.user_id,
            "category": self.category.value if isinstance(self.category, AbilityCategory) else self.category,
            "score": self.score,
            "level": self.level.value,
            "sample_count": self.sample_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": self.success_rate,
            "previous_score": self.previous_score,
            "score_change": self.score_change,
            "last_evaluated_at": self.last_evaluated_at.isoformat() if self.last_evaluated_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AbilityScore":
        category = data.get("category", "general")
        if isinstance(category, str):
            try:
                category = AbilityCategory(category)
            except ValueError:
                category = AbilityCategory.GENERAL

        def parse_datetime(val):
            if val is None:
                return None
            if isinstance(val, datetime):
                return val
            return datetime.fromisoformat(val.replace("Z", "+00:00"))

        return cls(
            id=data.get("id"),
            organization_id=data.get("organization_id"),
            ability_id=data.get("ability_id"),
            user_id=data.get("user_id"),
            category=category,
            score=data.get("score", ABILITY_SCORE_DEFAULT),
            sample_count=data.get("sample_count", 0),
            success_count=data.get("success_count", 0),
            failure_count=data.get("failure_count", 0),
            previous_score=data.get("previous_score"),
            score_change=data.get("score_change", 0.0),
            last_evaluated_at=parse_datetime(data.get("last_evaluated_at")),
            created_at=parse_datetime(data.get("created_at")),
            updated_at=parse_datetime(data.get("updated_at")),
        )


# ============================================================================
# 限界モデル
# ============================================================================

@dataclass
class Limitation:
    """限界情報

    ソウルくんの限界を記録する。
    """
    # 識別情報
    id: Optional[str] = None
    organization_id: Optional[str] = None

    # 限界情報
    limitation_type: LimitationType = LimitationType.UNCERTAINTY
    description: str = ""
    category: Optional[AbilityCategory] = None
    keywords: List[str] = field(default_factory=list)

    # 発生状況
    occurrence_count: int = 1
    last_occurred_at: Optional[datetime] = None
    context: Dict[str, Any] = field(default_factory=dict)

    # 対応策
    escalation_target: Optional[str] = None
    mitigation_strategy: Optional[str] = None
    is_resolvable: bool = False
    resolution_notes: Optional[str] = None

    # メタデータ
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def __post_init__(self):
        if self.id is None:
            self.id = str(uuid4())
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.last_occurred_at is None:
            self.last_occurred_at = self.created_at

    def increment_occurrence(self):
        """発生回数をインクリメント"""
        self.occurrence_count += 1
        self.last_occurred_at = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "limitation_type": self.limitation_type.value if isinstance(self.limitation_type, LimitationType) else self.limitation_type,
            "description": self.description,
            "category": self.category.value if isinstance(self.category, AbilityCategory) else self.category,
            "keywords": self.keywords,
            "occurrence_count": self.occurrence_count,
            "last_occurred_at": self.last_occurred_at.isoformat() if self.last_occurred_at else None,
            "context": self.context,
            "escalation_target": self.escalation_target,
            "mitigation_strategy": self.mitigation_strategy,
            "is_resolvable": self.is_resolvable,
            "resolution_notes": self.resolution_notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ============================================================================
# 改善ログモデル
# ============================================================================

@dataclass
class ImprovementLog:
    """改善ログ

    能力の改善・悪化を記録する。
    """
    # 識別情報
    id: Optional[str] = None
    organization_id: Optional[str] = None
    ability_score_id: Optional[str] = None

    # 改善情報
    improvement_type: ImprovementType = ImprovementType.ACCURACY
    category: AbilityCategory = AbilityCategory.GENERAL
    previous_score: float = 0.0
    current_score: float = 0.0
    change_amount: float = 0.0
    change_percent: float = 0.0

    # 分析
    is_improvement: bool = True
    analysis: Optional[str] = None
    contributing_factors: List[str] = field(default_factory=list)

    # メタデータ
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    created_at: Optional[datetime] = None

    def __post_init__(self):
        if self.id is None:
            self.id = str(uuid4())
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.period_end is None:
            self.period_end = self.created_at

        # 変化量を計算
        self.change_amount = self.current_score - self.previous_score
        if self.previous_score > 0:
            self.change_percent = (self.change_amount / self.previous_score) * 100
        self.is_improvement = self.change_amount > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "ability_score_id": self.ability_score_id,
            "improvement_type": self.improvement_type.value if isinstance(self.improvement_type, ImprovementType) else self.improvement_type,
            "category": self.category.value if isinstance(self.category, AbilityCategory) else self.category,
            "previous_score": self.previous_score,
            "current_score": self.current_score,
            "change_amount": self.change_amount,
            "change_percent": self.change_percent,
            "is_improvement": self.is_improvement,
            "analysis": self.analysis,
            "contributing_factors": self.contributing_factors,
            "period_start": self.period_start.isoformat() if self.period_start else None,
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================================
# 自己診断モデル
# ============================================================================

@dataclass
class SelfDiagnosis:
    """自己診断

    定期的な自己診断の結果を記録する。
    """
    # 識別情報
    id: Optional[str] = None
    organization_id: Optional[str] = None

    # 診断情報
    diagnosis_type: DiagnosisType = DiagnosisType.DAILY
    diagnosis_date: Optional[datetime] = None

    # 集計結果
    total_interactions: int = 0
    successful_interactions: int = 0
    failed_interactions: int = 0
    escalated_interactions: int = 0

    # 能力サマリー
    overall_score: float = 0.0
    strong_abilities: List[str] = field(default_factory=list)
    weak_abilities: List[str] = field(default_factory=list)
    improved_abilities: List[str] = field(default_factory=list)
    declined_abilities: List[str] = field(default_factory=list)

    # 限界サマリー
    frequent_limitations: List[Dict[str, Any]] = field(default_factory=list)
    new_limitations: List[str] = field(default_factory=list)

    # 推奨事項
    recommendations: List[str] = field(default_factory=list)
    focus_areas: List[str] = field(default_factory=list)

    # メタデータ
    created_at: Optional[datetime] = None

    def __post_init__(self):
        if self.id is None:
            self.id = str(uuid4())
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.diagnosis_date is None:
            self.diagnosis_date = self.created_at

    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.total_interactions == 0:
            return 0.0
        return self.successful_interactions / self.total_interactions

    @property
    def escalation_rate(self) -> float:
        """エスカレーション率"""
        if self.total_interactions == 0:
            return 0.0
        return self.escalated_interactions / self.total_interactions

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "diagnosis_type": self.diagnosis_type.value if isinstance(self.diagnosis_type, DiagnosisType) else self.diagnosis_type,
            "diagnosis_date": self.diagnosis_date.isoformat() if self.diagnosis_date else None,
            "total_interactions": self.total_interactions,
            "successful_interactions": self.successful_interactions,
            "failed_interactions": self.failed_interactions,
            "escalated_interactions": self.escalated_interactions,
            "success_rate": self.success_rate,
            "escalation_rate": self.escalation_rate,
            "overall_score": self.overall_score,
            "strong_abilities": self.strong_abilities,
            "weak_abilities": self.weak_abilities,
            "improved_abilities": self.improved_abilities,
            "declined_abilities": self.declined_abilities,
            "frequent_limitations": self.frequent_limitations,
            "new_limitations": self.new_limitations,
            "recommendations": self.recommendations,
            "focus_areas": self.focus_areas,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================================
# 確信度評価モデル
# ============================================================================

@dataclass
class ConfidenceAssessment:
    """確信度評価

    特定の回答に対する確信度を評価する。
    """
    # 確信度
    confidence_score: float = 0.5
    confidence_level: ConfidenceLevel = ConfidenceLevel.MEDIUM

    # 評価要素
    knowledge_confidence: float = 0.5      # 知識の確信度
    context_confidence: float = 0.5        # 文脈理解の確信度
    historical_accuracy: float = 0.5       # 過去の正確性

    # フラグ
    needs_confirmation: bool = False
    needs_escalation: bool = False
    escalation_reason: Optional[EscalationReason] = None
    escalation_target: Optional[str] = None

    # メッセージ
    confidence_message: str = ""
    uncertainty_factors: List[str] = field(default_factory=list)

    def __post_init__(self):
        # 総合確信度を計算
        self.confidence_score = (
            self.knowledge_confidence * 0.4 +
            self.context_confidence * 0.3 +
            self.historical_accuracy * 0.3
        )

        # 確信度レベルを判定
        for level, (low, high) in CONFIDENCE_LEVEL_THRESHOLDS.items():
            if low <= self.confidence_score < high:
                self.confidence_level = level
                break

        # フラグを設定
        self.needs_confirmation = self.confidence_level in [
            ConfidenceLevel.MEDIUM, ConfidenceLevel.LOW
        ]
        self.needs_escalation = self.confidence_level == ConfidenceLevel.VERY_LOW

    def to_dict(self) -> Dict[str, Any]:
        return {
            "confidence_score": self.confidence_score,
            "confidence_level": self.confidence_level.value,
            "knowledge_confidence": self.knowledge_confidence,
            "context_confidence": self.context_confidence,
            "historical_accuracy": self.historical_accuracy,
            "needs_confirmation": self.needs_confirmation,
            "needs_escalation": self.needs_escalation,
            "escalation_reason": self.escalation_reason.value if self.escalation_reason else None,
            "escalation_target": self.escalation_target,
            "confidence_message": self.confidence_message,
            "uncertainty_factors": self.uncertainty_factors,
        }


# ============================================================================
# 能力サマリーモデル
# ============================================================================

@dataclass
class AbilitySummary:
    """能力サマリー

    組織またはユーザーの能力の概要。
    """
    organization_id: str = ""
    user_id: Optional[str] = None

    # 全体スコア
    overall_score: float = 0.0
    overall_level: AbilityLevel = AbilityLevel.DEVELOPING

    # カテゴリ別スコア
    category_scores: Dict[str, float] = field(default_factory=dict)

    # 強み・弱み
    strengths: List[Dict[str, Any]] = field(default_factory=list)
    weaknesses: List[Dict[str, Any]] = field(default_factory=list)

    # トレンド
    improving_categories: List[str] = field(default_factory=list)
    declining_categories: List[str] = field(default_factory=list)

    # 統計
    total_abilities: int = 0
    evaluated_at: Optional[datetime] = None

    def __post_init__(self):
        if self.evaluated_at is None:
            self.evaluated_at = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "organization_id": self.organization_id,
            "user_id": self.user_id,
            "overall_score": self.overall_score,
            "overall_level": self.overall_level.value,
            "category_scores": self.category_scores,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "improving_categories": self.improving_categories,
            "declining_categories": self.declining_categories,
            "total_abilities": self.total_abilities,
            "evaluated_at": self.evaluated_at.isoformat() if self.evaluated_at else None,
        }
