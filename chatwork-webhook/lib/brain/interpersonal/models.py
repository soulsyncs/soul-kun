"""
Phase 2M: 対人力強化（Interpersonal Skills）- データモデル

設計書: docs/17_brain_completion_roadmap.md セクション Phase 2M

コミュニケーションプロファイル、モチベーションプロファイル、
フィードバック機会、対立ログのデータモデル定義。

PII保護: メッセージ本文・個人名は保存しない。
行動メタデータ（スタイル嗜好、検知タイムスタンプ、匿名化シグナル）のみ。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .constants import (
    ConflictSeverity,
    ConflictStatus,
    DiscouragementSignal,
    FeedbackType,
    InterpersonalStyleType,
    MotivationType,
    PreferredTiming,
    ReceptivenessLevel,
)


# ============================================================================
# コミュニケーションプロファイル
# ============================================================================

@dataclass
class CommunicationProfile:
    """ユーザーごとのコミュニケーションスタイルプロファイル

    PII保護: ユーザー名やメッセージ本文は含まない。
    """
    id: Optional[str] = None
    organization_id: Optional[str] = None
    user_id: Optional[str] = None

    # スタイル嗜好
    preferred_length: InterpersonalStyleType = InterpersonalStyleType.BALANCED
    formality_level: InterpersonalStyleType = InterpersonalStyleType.ADAPTIVE
    preferred_timing: PreferredTiming = PreferredTiming.ANYTIME

    # レスポンススタイル（JSONB互換）
    response_preferences: Dict[str, Any] = field(default_factory=dict)

    # 統計
    interaction_count: int = 0
    confidence_score: float = 0.5

    # タイムスタンプ
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
            "user_id": self.user_id,
            "preferred_length": self.preferred_length.value if isinstance(self.preferred_length, InterpersonalStyleType) else self.preferred_length,
            "formality_level": self.formality_level.value if isinstance(self.formality_level, InterpersonalStyleType) else self.formality_level,
            "preferred_timing": self.preferred_timing.value if isinstance(self.preferred_timing, PreferredTiming) else self.preferred_timing,
            "response_preferences": self.response_preferences,
            "interaction_count": self.interaction_count,
            "confidence_score": self.confidence_score,
        }


# ============================================================================
# モチベーションプロファイル
# ============================================================================

@dataclass
class MotivationProfile:
    """ユーザーのモチベーションタイプ・価値観プロファイル

    PII保護: 具体的な成功事例のテキストは保存しない。
    カテゴリ分類とスコアのみ。
    """
    id: Optional[str] = None
    organization_id: Optional[str] = None
    user_id: Optional[str] = None

    # モチベーションタイプ
    primary_type: MotivationType = MotivationType.ACHIEVEMENT
    secondary_type: Optional[MotivationType] = None

    # 価値観（カテゴリ名のみ、具体的テキストは含まない）
    key_values: List[str] = field(default_factory=list)

    # 落ち込みトリガー（シグナルタイプのみ）
    discouragement_triggers: List[str] = field(default_factory=list)

    # 統計
    sample_count: int = 0
    confidence_score: float = 0.5

    # タイムスタンプ
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
            "user_id": self.user_id,
            "primary_type": self.primary_type.value if isinstance(self.primary_type, MotivationType) else self.primary_type,
            "secondary_type": self.secondary_type.value if isinstance(self.secondary_type, MotivationType) else self.secondary_type,
            "key_values": self.key_values,
            "discouragement_triggers": self.discouragement_triggers,
            "sample_count": self.sample_count,
            "confidence_score": self.confidence_score,
        }


# ============================================================================
# フィードバック機会
# ============================================================================

@dataclass
class FeedbackOpportunity:
    """フィードバック（助言）の機会を記録するモデル

    PII保護: context はカテゴリ・タグのみ（メッセージ本文を含まない）。
    """
    id: Optional[str] = None
    organization_id: Optional[str] = None
    user_id: Optional[str] = None

    # フィードバック内容
    feedback_type: FeedbackType = FeedbackType.CONSTRUCTIVE
    context_category: str = ""  # カテゴリタグのみ（例: "task_delay", "goal_progress"）
    receptiveness_score: float = 0.5

    # 配信状態
    delivered: bool = False
    delivered_at: Optional[datetime] = None

    # タイムスタンプ
    created_at: Optional[datetime] = None

    def __post_init__(self):
        if self.id is None:
            self.id = str(uuid4())
        if self.created_at is None:
            self.created_at = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "user_id": self.user_id,
            "feedback_type": self.feedback_type.value if isinstance(self.feedback_type, FeedbackType) else self.feedback_type,
            "context_category": self.context_category,
            "receptiveness_score": self.receptiveness_score,
            "delivered": self.delivered,
        }


# ============================================================================
# 対立ログ
# ============================================================================

@dataclass
class ConflictLog:
    """対立の検知・調停記録モデル

    PII保護: party_a_user_id / party_b_user_id のみ（名前は含まない）。
    context_category はカテゴリタグのみ。
    """
    id: Optional[str] = None
    organization_id: Optional[str] = None

    # 関係者（IDのみ、名前は含まない）
    party_a_user_id: Optional[str] = None
    party_b_user_id: Optional[str] = None

    # 対立情報
    context_category: str = ""  # "project_disagreement", "schedule_conflict" 等
    severity: ConflictSeverity = ConflictSeverity.LOW
    status: ConflictStatus = ConflictStatus.DETECTED

    # 調停
    mediation_strategy_type: Optional[str] = None  # "common_ground", "compromise" 等
    evidence_count: int = 0

    # タイムスタンプ
    detected_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None

    def __post_init__(self):
        if self.id is None:
            self.id = str(uuid4())
        if self.detected_at is None:
            self.detected_at = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "party_a_user_id": self.party_a_user_id,
            "party_b_user_id": self.party_b_user_id,
            "context_category": self.context_category,
            "severity": self.severity.value if isinstance(self.severity, ConflictSeverity) else self.severity,
            "status": self.status.value if isinstance(self.status, ConflictStatus) else self.status,
            "evidence_count": self.evidence_count,
        }


# ============================================================================
# 結果モデル
# ============================================================================

@dataclass
class InterpersonalResult:
    """対人力機能の結果を返すモデル"""
    success: bool = True
    message: str = ""
    data: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
