"""
Phase 2E: 学習基盤 - データモデル

設計書: docs/18_phase2e_learning_foundation.md v1.1.0
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from .constants import (
    AuthorityLevel,
    ConflictResolutionStrategy,
    ConflictType,
    DecisionImpact,
    LearningCategory,
    LearningScope,
    RelationshipType,
    TriggerType,
    DEFAULT_CONFIDENCE_DECAY_RATE,
    DEFAULT_LEARNED_CONTENT_VERSION,
    DEFAULT_CLASSIFICATION,
)


# ============================================================================
# 学習データモデル
# ============================================================================

@dataclass
class Learning:
    """学習データモデル

    ソウルくんが学習した1つの知識を表す。
    brain_learningsテーブルの1レコードに対応。
    """

    # 識別情報
    id: Optional[str] = None
    organization_id: Optional[str] = None

    # 学習カテゴリ
    category: str = LearningCategory.FACT.value

    # トリガー（いつ適用するか）
    trigger_type: str = TriggerType.KEYWORD.value
    trigger_value: str = ""

    # 学習内容
    learned_content: Dict[str, Any] = field(default_factory=dict)
    learned_content_version: int = DEFAULT_LEARNED_CONTENT_VERSION

    # スコープ
    scope: str = LearningScope.GLOBAL.value
    scope_target_id: Optional[str] = None

    # 権限レベル（Phase 2D連携）
    authority_level: str = AuthorityLevel.USER.value
    related_ceo_teaching_id: Optional[str] = None

    # 有効期間
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None

    # 教えた人
    taught_by_account_id: str = ""
    taught_by_name: Optional[str] = None
    taught_in_room_id: Optional[str] = None

    # 元のメッセージ
    source_message: Optional[str] = None
    source_context: Optional[Dict[str, Any]] = None

    # 検出情報
    detection_pattern: Optional[str] = None
    detection_confidence: Optional[float] = None

    # 適用状況
    is_active: bool = True
    applied_count: int = 0
    last_applied_at: Optional[datetime] = None
    success_count: int = 0
    failure_count: int = 0

    # 上書き情報
    supersedes_id: Optional[str] = None
    superseded_by_id: Optional[str] = None

    # Phase 2G準備: 知識グラフ
    related_learning_ids: Optional[List[str]] = None
    relationship_type: Optional[str] = None
    confidence_decay_rate: float = DEFAULT_CONFIDENCE_DECAY_RATE

    # Phase 2H準備: 自己認識
    unknown_pattern: Optional[str] = None
    clarification_count: int = 0

    # Phase 2N準備: 自己最適化
    effectiveness_score: Optional[float] = None
    last_effectiveness_check: Optional[datetime] = None
    decision_impact: Optional[str] = None

    # 監査
    classification: str = DEFAULT_CLASSIFICATION
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "category": self.category,
            "trigger_type": self.trigger_type,
            "trigger_value": self.trigger_value,
            "learned_content": self.learned_content,
            "learned_content_version": self.learned_content_version,
            "scope": self.scope,
            "scope_target_id": self.scope_target_id,
            "authority_level": self.authority_level,
            "related_ceo_teaching_id": self.related_ceo_teaching_id,
            "valid_from": self.valid_from.isoformat() if self.valid_from else None,
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
            "taught_by_account_id": self.taught_by_account_id,
            "taught_by_name": self.taught_by_name,
            "taught_in_room_id": self.taught_in_room_id,
            "source_message": self.source_message,
            "source_context": self.source_context,
            "detection_pattern": self.detection_pattern,
            "detection_confidence": self.detection_confidence,
            "is_active": self.is_active,
            "applied_count": self.applied_count,
            "last_applied_at": self.last_applied_at.isoformat() if self.last_applied_at else None,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "supersedes_id": self.supersedes_id,
            "superseded_by_id": self.superseded_by_id,
            "related_learning_ids": self.related_learning_ids,
            "relationship_type": self.relationship_type,
            "confidence_decay_rate": self.confidence_decay_rate,
            "unknown_pattern": self.unknown_pattern,
            "clarification_count": self.clarification_count,
            "effectiveness_score": self.effectiveness_score,
            "last_effectiveness_check": (
                self.last_effectiveness_check.isoformat()
                if self.last_effectiveness_check else None
            ),
            "decision_impact": self.decision_impact,
            "classification": self.classification,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Learning":
        """辞書形式から生成"""
        # datetime変換
        for dt_field in ["valid_from", "valid_until", "last_applied_at",
                         "last_effectiveness_check", "created_at", "updated_at"]:
            if data.get(dt_field) and isinstance(data[dt_field], str):
                data[dt_field] = datetime.fromisoformat(data[dt_field])

        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> "Learning":
        """DBレコードから生成"""
        return cls.from_dict(row)

    def get_description(self) -> str:
        """学習内容の説明を取得"""
        content = self.learned_content

        if self.category == LearningCategory.ALIAS.value:
            return f"「{content.get('from', '')}」→「{content.get('to', '')}」"

        elif self.category == LearningCategory.PREFERENCE.value:
            return f"{content.get('subject', '')}: {content.get('preference', '')}"

        elif self.category == LearningCategory.FACT.value:
            return content.get('description', str(content))

        elif self.category == LearningCategory.RULE.value:
            condition = content.get('condition', '')
            action = content.get('action', '')
            return f"{condition}の時は{action}"

        elif self.category == LearningCategory.CORRECTION.value:
            wrong = content.get('wrong_pattern', '')
            correct = content.get('correct_pattern', '')
            return f"「{wrong}」→「{correct}」"

        elif self.category == LearningCategory.CONTEXT.value:
            return content.get('description', str(content))

        elif self.category == LearningCategory.RELATIONSHIP.value:
            p1 = content.get('person1', '')
            p2 = content.get('person2', '')
            rel = content.get('relationship', '')
            return f"{p1}と{p2}は{rel}"

        elif self.category == LearningCategory.PROCEDURE.value:
            return content.get('description', str(content))

        return str(content)

    @property
    def authority_level_priority(self) -> int:
        """権限レベルの優先度を取得（数値が小さいほど高優先）"""
        from .constants import AUTHORITY_PRIORITY
        return AUTHORITY_PRIORITY.get(self.authority_level, 5)


# ============================================================================
# 学習ログデータモデル
# ============================================================================

@dataclass
class LearningLog:
    """学習ログデータモデル

    学習が適用された履歴を表す。
    brain_learning_logsテーブルの1レコードに対応。
    """

    # 識別情報
    id: Optional[str] = None
    organization_id: Optional[str] = None
    learning_id: str = ""
    learning_version: int = 1

    # 適用状況
    applied_at: Optional[datetime] = None
    applied_in_room_id: Optional[str] = None
    applied_for_account_id: Optional[str] = None

    # トリガー情報
    trigger_message: Optional[str] = None
    trigger_context: Optional[Dict[str, Any]] = None
    context_hash: Optional[str] = None

    # 結果
    was_successful: Optional[bool] = None
    result_description: Optional[str] = None
    response_latency_ms: Optional[int] = None

    # フィードバック
    feedback_received: bool = False
    feedback_positive: Optional[bool] = None
    feedback_message: Optional[str] = None
    user_feedback_at: Optional[datetime] = None

    # 監査
    created_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "learning_id": self.learning_id,
            "learning_version": self.learning_version,
            "applied_at": self.applied_at.isoformat() if self.applied_at else None,
            "applied_in_room_id": self.applied_in_room_id,
            "applied_for_account_id": self.applied_for_account_id,
            "trigger_message": self.trigger_message,
            "trigger_context": self.trigger_context,
            "context_hash": self.context_hash,
            "was_successful": self.was_successful,
            "result_description": self.result_description,
            "response_latency_ms": self.response_latency_ms,
            "feedback_received": self.feedback_received,
            "feedback_positive": self.feedback_positive,
            "feedback_message": self.feedback_message,
            "user_feedback_at": (
                self.user_feedback_at.isoformat() if self.user_feedback_at else None
            ),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> "LearningLog":
        """DBレコードから生成"""
        return cls(**{k: v for k, v in row.items() if k in cls.__dataclass_fields__})


# ============================================================================
# フィードバック検出結果
# ============================================================================

@dataclass
class PatternMatch:
    """パターンマッチ結果"""
    groups: Dict[str, str] = field(default_factory=dict)
    start: int = 0
    end: int = 0
    matched_text: str = ""


@dataclass
class FeedbackDetectionResult:
    """フィードバック検出結果

    ユーザーのメッセージから「教えている」ことを検出した結果。
    """

    # 検出したパターン
    pattern_name: str = ""
    pattern_category: str = ""

    # マッチ情報
    match: Optional[PatternMatch] = None

    # 抽出した情報
    extracted: Dict[str, Any] = field(default_factory=dict)

    # 確信度（0.0-1.0）
    confidence: float = 0.0

    # 文脈からの補足情報
    context_support: bool = False
    recent_error_support: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "pattern_name": self.pattern_name,
            "pattern_category": self.pattern_category,
            "match": {
                "groups": self.match.groups if self.match else {},
                "matched_text": self.match.matched_text if self.match else "",
            },
            "extracted": self.extracted,
            "confidence": self.confidence,
            "context_support": self.context_support,
            "recent_error_support": self.recent_error_support,
        }


# ============================================================================
# 会話コンテキスト
# ============================================================================

@dataclass
class ConversationContext:
    """会話コンテキスト

    学習検出・適用時に参照する文脈情報。
    """

    # 直前のメッセージ
    previous_messages: List[Dict[str, Any]] = field(default_factory=list)

    # ソウルくんの最後のアクション
    soulkun_last_action: Optional[str] = None
    soulkun_last_response: Optional[str] = None

    # エラー情報
    has_recent_error: bool = False
    error_type: Optional[str] = None
    error_message: Optional[str] = None

    # ルーム情報
    room_id: Optional[str] = None
    room_name: Optional[str] = None

    # ユーザー情報
    user_id: Optional[str] = None
    user_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "previous_messages": self.previous_messages,
            "soulkun_last_action": self.soulkun_last_action,
            "soulkun_last_response": self.soulkun_last_response,
            "has_recent_error": self.has_recent_error,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "room_id": self.room_id,
            "room_name": self.room_name,
            "user_id": self.user_id,
            "user_name": self.user_name,
        }


# ============================================================================
# 矛盾情報
# ============================================================================

@dataclass
class ConflictInfo:
    """矛盾情報

    2つの学習間の矛盾を表す。
    """

    # 矛盾する学習
    new_learning: Learning
    existing_learning: Learning

    # 矛盾タイプ
    conflict_type: str = ConflictType.CONTENT_MISMATCH.value

    # 解決提案（conflict_detector.pyとの互換性のため両方サポート）
    resolution_suggestion: str = ""
    suggested_resolution: str = ""

    # 矛盾の説明（conflict_detector.pyで使用）
    description: str = ""

    # CEO教え（矛盾相手がCEO教えの場合）
    ceo_teaching_statement: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "new_learning": self.new_learning.to_dict(),
            "existing_learning": self.existing_learning.to_dict(),
            "conflict_type": self.conflict_type,
            "resolution_suggestion": self.resolution_suggestion,
            "suggested_resolution": self.suggested_resolution,
            "description": self.description,
            "ceo_teaching_statement": self.ceo_teaching_statement,
        }


# ============================================================================
# 解決結果
# ============================================================================

@dataclass
class Resolution:
    """矛盾解決結果"""

    # アクション
    action: str = ""  # 'superseded', 'rejected', 'needs_confirmation'

    # 結果
    kept_learning: Optional[Learning] = None
    removed_learning: Optional[Learning] = None

    # メッセージ
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "action": self.action,
            "kept_learning": self.kept_learning.to_dict() if self.kept_learning else None,
            "removed_learning": (
                self.removed_learning.to_dict() if self.removed_learning else None
            ),
            "message": self.message,
        }


# ============================================================================
# 適用済み学習
# ============================================================================

@dataclass
class AppliedLearning:
    """適用済み学習

    学習が適用された結果を表す。
    """

    # 適用した学習
    learning: Learning

    # 適用方法
    application_type: str = ""  # 'alias_resolved', 'rule_applied', etc.

    # 適用結果
    before_value: Optional[str] = None
    after_value: Optional[str] = None

    # 処理時間
    latency_ms: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "learning_id": self.learning.id,
            "learning_category": self.learning.category,
            "application_type": self.application_type,
            "before_value": self.before_value,
            "after_value": self.after_value,
            "latency_ms": self.latency_ms,
        }


# ============================================================================
# 効果測定結果（Phase 2N準備）
# ============================================================================

@dataclass
class EffectivenessResult:
    """学習効果測定結果"""

    learning_id: str = ""

    # 統計
    total_applications: int = 0
    successful_applications: int = 0
    failed_applications: int = 0
    positive_feedbacks: int = 0
    negative_feedbacks: int = 0

    # スコア
    effectiveness_score: float = 0.0

    # 推奨アクション
    recommendation: Optional[str] = None  # 'keep', 'review', 'deactivate'

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "learning_id": self.learning_id,
            "total_applications": self.total_applications,
            "successful_applications": self.successful_applications,
            "failed_applications": self.failed_applications,
            "positive_feedbacks": self.positive_feedbacks,
            "negative_feedbacks": self.negative_feedbacks,
            "effectiveness_score": self.effectiveness_score,
            "recommendation": self.recommendation,
        }


# ============================================================================
# 改善提案（Phase 2N準備）
# ============================================================================

@dataclass
class ImprovementSuggestion:
    """学習の改善提案"""

    learning_id: str = ""

    # 提案タイプ
    suggestion_type: str = ""  # 'refine_trigger', 'adjust_scope', 'deactivate'

    # 詳細
    description: str = ""
    reason: str = ""

    # 提案内容
    suggested_changes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "learning_id": self.learning_id,
            "suggestion_type": self.suggestion_type,
            "description": self.description,
            "reason": self.reason,
            "suggested_changes": self.suggested_changes,
        }
