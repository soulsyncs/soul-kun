"""
Phase 2F: 結果からの学習 - データモデル

設計書: docs/17_brain_completion_roadmap.md セクション Phase 2F
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from .constants import (
    EventType,
    FeedbackSignal,
    OutcomeType,
    PatternScope,
    PatternType,
)


# ============================================================================
# イベントデータモデル
# ============================================================================

@dataclass
class OutcomeEvent:
    """行動結果イベントデータモデル

    ソウルくんの通知・提案などのアクションとその結果を表す。
    brain_outcome_eventsテーブルの1レコードに対応。
    """

    # 識別情報
    id: Optional[str] = None
    organization_id: Optional[str] = None

    # イベント情報
    event_type: str = EventType.NOTIFICATION_SENT.value
    event_subtype: Optional[str] = None
    event_timestamp: Optional[datetime] = None

    # ターゲット情報
    target_account_id: str = ""
    target_room_id: Optional[str] = None

    # イベント詳細
    event_details: Dict[str, Any] = field(default_factory=dict)
    # 例: {
    #   "action": "send_reminder",
    #   "message_preview": "...",
    #   "sent_hour": 10,
    #   "day_of_week": "monday"
    # }

    # 関連リソース
    related_resource_type: Optional[str] = None  # 'task', 'goal', 'notification'
    related_resource_id: Optional[str] = None

    # 結果追跡
    outcome_detected: bool = False
    outcome_type: Optional[str] = None  # OutcomeType値
    outcome_detected_at: Optional[datetime] = None
    outcome_details: Optional[Dict[str, Any]] = None
    # 例: {
    #   "response_time_hours": 2.5,
    #   "user_action": "completed_task",
    #   "feedback_signal": "task_completed"
    # }

    # 学習連携
    learning_extracted: bool = False
    learning_id: Optional[str] = None
    pattern_id: Optional[str] = None

    # コンテキストスナップショット
    context_snapshot: Optional[Dict[str, Any]] = None

    # 監査
    created_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "event_type": self.event_type,
            "event_subtype": self.event_subtype,
            "event_timestamp": (
                self.event_timestamp.isoformat() if self.event_timestamp else None
            ),
            "target_account_id": self.target_account_id,
            "target_room_id": self.target_room_id,
            "event_details": self.event_details,
            "related_resource_type": self.related_resource_type,
            "related_resource_id": self.related_resource_id,
            "outcome_detected": self.outcome_detected,
            "outcome_type": self.outcome_type,
            "outcome_detected_at": (
                self.outcome_detected_at.isoformat()
                if self.outcome_detected_at else None
            ),
            "outcome_details": self.outcome_details,
            "learning_extracted": self.learning_extracted,
            "learning_id": self.learning_id,
            "pattern_id": self.pattern_id,
            "context_snapshot": self.context_snapshot,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OutcomeEvent":
        """辞書形式から生成"""
        # datetime変換
        for dt_field in ["event_timestamp", "outcome_detected_at", "created_at"]:
            if data.get(dt_field) and isinstance(data[dt_field], str):
                data[dt_field] = datetime.fromisoformat(data[dt_field])

        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> "OutcomeEvent":
        """DBレコードから生成"""
        return cls.from_dict(dict(row))

    @property
    def is_positive_outcome(self) -> bool:
        """ポジティブな結果かどうか"""
        return self.outcome_type in [
            OutcomeType.ADOPTED.value,
            OutcomeType.PARTIAL.value,
        ]

    @property
    def is_negative_outcome(self) -> bool:
        """ネガティブな結果かどうか"""
        return self.outcome_type in [
            OutcomeType.IGNORED.value,
            OutcomeType.REJECTED.value,
        ]


# ============================================================================
# 暗黙フィードバックデータモデル
# ============================================================================

@dataclass
class ImplicitFeedback:
    """暗黙フィードバックデータモデル

    ユーザーの行動から検出された間接的なフィードバック。
    """

    # 関連イベント
    event_id: str = ""

    # フィードバック内容
    feedback_signal: str = FeedbackSignal.NO_RESPONSE.value
    outcome_type: str = OutcomeType.PENDING.value

    # 確信度（0.0-1.0）
    confidence: float = 0.0

    # 検出根拠
    evidence: Dict[str, Any] = field(default_factory=dict)
    # 例: {
    #   "detection_method": "time_based",
    #   "elapsed_hours": 2.5,
    #   "threshold_hours": 4,
    #   "supporting_data": {...}
    # }

    # 検出日時
    detected_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "event_id": self.event_id,
            "feedback_signal": self.feedback_signal,
            "outcome_type": self.outcome_type,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "detected_at": self.detected_at.isoformat() if self.detected_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ImplicitFeedback":
        """辞書形式から生成"""
        if data.get("detected_at") and isinstance(data["detected_at"], str):
            data["detected_at"] = datetime.fromisoformat(data["detected_at"])

        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ============================================================================
# パターンデータモデル
# ============================================================================

@dataclass
class OutcomePattern:
    """結果パターンデータモデル

    抽出された成功/失敗パターン。
    brain_outcome_patternsテーブルの1レコードに対応。
    """

    # 識別情報
    id: Optional[str] = None
    organization_id: Optional[str] = None

    # パターン識別
    pattern_type: str = PatternType.TIMING.value
    pattern_category: Optional[str] = None

    # 適用対象
    scope: str = PatternScope.USER.value
    scope_target_id: Optional[str] = None

    # パターン内容
    pattern_content: Dict[str, Any] = field(default_factory=dict)
    # 例（時間帯パターン）: {
    #   "type": "timing",
    #   "condition": {"hour_range": [9, 12], "day_of_week": ["monday", "tuesday"]},
    #   "effect": "high_response_rate",
    #   "description": "午前中の連絡に対して反応が良い"
    # }

    # 統計情報
    sample_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    success_rate: Optional[float] = None
    confidence_score: Optional[float] = None

    # 効果測定
    effectiveness_score: Optional[float] = None
    last_effectiveness_check: Optional[datetime] = None

    # 状態
    is_active: bool = True
    is_validated: bool = False
    validated_at: Optional[datetime] = None

    # 学習連携（brain_learningsに昇格した場合）
    promoted_to_learning_id: Optional[str] = None
    promoted_at: Optional[datetime] = None

    # 監査
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "pattern_type": self.pattern_type,
            "pattern_category": self.pattern_category,
            "scope": self.scope,
            "scope_target_id": self.scope_target_id,
            "pattern_content": self.pattern_content,
            "sample_count": self.sample_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": self.success_rate,
            "confidence_score": self.confidence_score,
            "effectiveness_score": self.effectiveness_score,
            "last_effectiveness_check": (
                self.last_effectiveness_check.isoformat()
                if self.last_effectiveness_check else None
            ),
            "is_active": self.is_active,
            "is_validated": self.is_validated,
            "validated_at": (
                self.validated_at.isoformat() if self.validated_at else None
            ),
            "promoted_to_learning_id": self.promoted_to_learning_id,
            "promoted_at": (
                self.promoted_at.isoformat() if self.promoted_at else None
            ),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OutcomePattern":
        """辞書形式から生成"""
        # datetime変換
        for dt_field in [
            "last_effectiveness_check",
            "validated_at",
            "promoted_at",
            "created_at",
            "updated_at",
        ]:
            if data.get(dt_field) and isinstance(data[dt_field], str):
                data[dt_field] = datetime.fromisoformat(data[dt_field])

        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> "OutcomePattern":
        """DBレコードから生成"""
        return cls.from_dict(dict(row))

    def get_description(self) -> str:
        """パターンの説明を取得"""
        content = self.pattern_content

        if self.pattern_type == PatternType.TIMING.value:
            condition = content.get("condition", {})
            hour_range = condition.get("hour_range", [])
            if hour_range:
                return f"{hour_range[0]}時〜{hour_range[1]}時の連絡が効果的"

        elif self.pattern_type == PatternType.COMMUNICATION_STYLE.value:
            return content.get("description", "コミュニケーションスタイルパターン")

        elif self.pattern_type == PatternType.TASK_TYPE.value:
            return content.get("description", "タスクタイプパターン")

        elif self.pattern_type == PatternType.USER_PREFERENCE.value:
            return content.get("description", "ユーザー好みパターン")

        elif self.pattern_type == PatternType.DAY_OF_WEEK.value:
            days = content.get("condition", {}).get("days", [])
            if days:
                return f"{', '.join(days)}の連絡が効果的"

        return content.get("description", str(content))

    @property
    def is_promotable(self) -> bool:
        """学習に昇格可能かどうか"""
        from .constants import (
            PROMOTION_CONFIDENCE_THRESHOLD,
            PROMOTION_MIN_SAMPLE_COUNT,
        )
        return (
            self.confidence_score is not None
            and self.confidence_score >= PROMOTION_CONFIDENCE_THRESHOLD
            and self.sample_count >= PROMOTION_MIN_SAMPLE_COUNT
            and self.promoted_to_learning_id is None
        )


# ============================================================================
# インサイトデータモデル
# ============================================================================

@dataclass
class OutcomeInsight:
    """分析から得られたインサイト"""

    # インサイト情報
    insight_type: str = ""  # 'user_responsiveness', 'timing_effectiveness', etc.
    target_account_id: Optional[str] = None

    # 内容
    title: str = ""
    description: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)

    # 推奨アクション
    recommendation: Optional[str] = None
    recommendation_details: Optional[Dict[str, Any]] = None

    # 確信度
    confidence: float = 0.0

    # 生成日時
    generated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "insight_type": self.insight_type,
            "target_account_id": self.target_account_id,
            "title": self.title,
            "description": self.description,
            "evidence": self.evidence,
            "recommendation": self.recommendation,
            "recommendation_details": self.recommendation_details,
            "confidence": self.confidence,
            "generated_at": (
                self.generated_at.isoformat() if self.generated_at else None
            ),
        }


# ============================================================================
# 集計結果データモデル
# ============================================================================

@dataclass
class OutcomeStatistics:
    """結果の集計統計"""

    # 集計対象
    target_account_id: Optional[str] = None
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None

    # イベント統計
    total_events: int = 0
    adopted_count: int = 0
    ignored_count: int = 0
    delayed_count: int = 0
    rejected_count: int = 0
    pending_count: int = 0

    # 計算済み指標
    adoption_rate: float = 0.0
    ignore_rate: float = 0.0
    average_response_time_hours: Optional[float] = None

    # 時間帯別統計
    by_hour: Optional[Dict[int, Dict[str, int]]] = None
    # 例: {9: {"total": 10, "adopted": 8, "ignored": 2}, ...}

    # 曜日別統計
    by_day_of_week: Optional[Dict[str, Dict[str, int]]] = None
    # 例: {"monday": {"total": 15, "adopted": 12, ...}, ...}

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "target_account_id": self.target_account_id,
            "period_start": (
                self.period_start.isoformat() if self.period_start else None
            ),
            "period_end": (
                self.period_end.isoformat() if self.period_end else None
            ),
            "total_events": self.total_events,
            "adopted_count": self.adopted_count,
            "ignored_count": self.ignored_count,
            "delayed_count": self.delayed_count,
            "rejected_count": self.rejected_count,
            "pending_count": self.pending_count,
            "adoption_rate": self.adoption_rate,
            "ignore_rate": self.ignore_rate,
            "average_response_time_hours": self.average_response_time_hours,
            "by_hour": self.by_hour,
            "by_day_of_week": self.by_day_of_week,
        }


# ============================================================================
# 検出コンテキスト
# ============================================================================

@dataclass
class DetectionContext:
    """結果検出時のコンテキスト"""

    # イベント情報
    event: OutcomeEvent = field(default_factory=OutcomeEvent)

    # 関連データ
    notification_log: Optional[Dict[str, Any]] = None
    goal_progress: Optional[Dict[str, Any]] = None
    task_info: Optional[Dict[str, Any]] = None
    proactive_action: Optional[Dict[str, Any]] = None

    # 時間情報
    elapsed_hours: float = 0.0
    check_timestamp: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "event": self.event.to_dict(),
            "notification_log": self.notification_log,
            "goal_progress": self.goal_progress,
            "task_info": self.task_info,
            "proactive_action": self.proactive_action,
            "elapsed_hours": self.elapsed_hours,
            "check_timestamp": (
                self.check_timestamp.isoformat() if self.check_timestamp else None
            ),
        }
