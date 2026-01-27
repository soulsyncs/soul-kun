# lib/capabilities/feedback/models.py
"""
Phase F1: CEOフィードバックシステム - データモデル

このモジュールは、CEOフィードバックシステムで使用するデータモデルを定義します。

設計書: docs/20_next_generation_capabilities.md セクション8

Author: Claude Opus 4.5
Created: 2026-01-27
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from .constants import (
    FeedbackType,
    FeedbackPriority,
    FeedbackStatus,
    InsightCategory,
    TrendDirection,
    ComparisonPeriod,
    FeedbackIcons,
)


# =============================================================================
# ファクト（事実）モデル
# =============================================================================


@dataclass
class TaskFact:
    """
    タスクに関する事実

    Attributes:
        user_id: ユーザーID
        user_name: ユーザー名
        total_tasks: 総タスク数
        completed_tasks: 完了タスク数
        overdue_tasks: 期限超過タスク数
        stale_tasks: 滞留タスク数（N日以上未更新）
        tasks_created_today: 今日作成されたタスク数
        tasks_completed_today: 今日完了したタスク数
        oldest_overdue_days: 最も古い期限超過の日数
        task_details: 個別タスクの詳細（オプション）
    """

    user_id: str
    user_name: str
    total_tasks: int = 0
    completed_tasks: int = 0
    overdue_tasks: int = 0
    stale_tasks: int = 0
    tasks_created_today: int = 0
    tasks_completed_today: int = 0
    oldest_overdue_days: int = 0
    task_details: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def completion_rate(self) -> float:
        """完了率"""
        if self.total_tasks == 0:
            return 0.0
        return self.completed_tasks / self.total_tasks

    @property
    def has_issues(self) -> bool:
        """問題があるか"""
        return self.overdue_tasks > 0 or self.stale_tasks > 0

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "user_id": self.user_id,
            "user_name": self.user_name,
            "total_tasks": self.total_tasks,
            "completed_tasks": self.completed_tasks,
            "overdue_tasks": self.overdue_tasks,
            "stale_tasks": self.stale_tasks,
            "completion_rate": round(self.completion_rate, 2),
            "has_issues": self.has_issues,
        }


@dataclass
class GoalFact:
    """
    目標に関する事実

    Attributes:
        user_id: ユーザーID
        user_name: ユーザー名
        goal_id: 目標ID
        goal_title: 目標タイトル
        target_value: 目標値
        current_value: 現在値
        progress_rate: 進捗率
        days_remaining: 残り日数
        trend: 進捗トレンド
        last_updated: 最終更新日時
    """

    user_id: str
    user_name: str
    goal_id: str
    goal_title: str
    target_value: float
    current_value: float
    progress_rate: float
    days_remaining: int
    trend: TrendDirection = TrendDirection.STABLE
    last_updated: Optional[datetime] = None

    @property
    def is_on_track(self) -> bool:
        """目標に向けて順調か"""
        if self.days_remaining <= 0:
            return self.progress_rate >= 1.0
        # 残り日数に対して適切な進捗率かどうか
        expected_progress = 1.0 - (self.days_remaining / 30)  # 30日想定
        return self.progress_rate >= expected_progress * 0.8

    @property
    def is_at_risk(self) -> bool:
        """リスクがあるか"""
        return not self.is_on_track and self.progress_rate < 0.5

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "user_id": self.user_id,
            "user_name": self.user_name,
            "goal_id": self.goal_id,
            "goal_title": self.goal_title,
            "progress_rate": round(self.progress_rate, 2),
            "days_remaining": self.days_remaining,
            "trend": self.trend.value,
            "is_on_track": self.is_on_track,
            "is_at_risk": self.is_at_risk,
        }


@dataclass
class CommunicationFact:
    """
    コミュニケーションに関する事実

    Attributes:
        user_id: ユーザーID
        user_name: ユーザー名
        message_count_today: 今日のメッセージ数
        message_count_week: 今週のメッセージ数
        avg_response_time_hours: 平均返信時間（時間）
        sentiment_score: 感情スコア（-1.0〜1.0）
        sentiment_trend: 感情トレンド
        question_count: 質問数
        mention_count: メンション数
    """

    user_id: str
    user_name: str
    message_count_today: int = 0
    message_count_week: int = 0
    avg_response_time_hours: float = 0.0
    sentiment_score: float = 0.0
    sentiment_trend: TrendDirection = TrendDirection.STABLE
    question_count: int = 0
    mention_count: int = 0

    @property
    def is_sentiment_concerning(self) -> bool:
        """感情面で気になる状態か"""
        return self.sentiment_score < -0.3 or self.sentiment_trend == TrendDirection.DROP

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "user_id": self.user_id,
            "user_name": self.user_name,
            "message_count_today": self.message_count_today,
            "message_count_week": self.message_count_week,
            "sentiment_score": round(self.sentiment_score, 2),
            "sentiment_trend": self.sentiment_trend.value,
            "is_sentiment_concerning": self.is_sentiment_concerning,
        }


@dataclass
class TeamFact:
    """
    チーム全体に関する事実

    Attributes:
        organization_id: 組織ID
        total_members: メンバー総数
        active_members: アクティブメンバー数（今日活動あり）
        avg_task_completion_rate: 平均タスク完了率
        total_overdue_tasks: 組織全体の期限超過タスク
        total_goals_at_risk: リスクのある目標数
        top_performers: トップパフォーマー（ユーザー名リスト）
        members_needing_attention: 注意が必要なメンバー（ユーザー名リスト）
    """

    organization_id: str
    total_members: int = 0
    active_members: int = 0
    avg_task_completion_rate: float = 0.0
    total_overdue_tasks: int = 0
    total_goals_at_risk: int = 0
    top_performers: List[str] = field(default_factory=list)
    members_needing_attention: List[str] = field(default_factory=list)

    @property
    def activity_rate(self) -> float:
        """活動率"""
        if self.total_members == 0:
            return 0.0
        return self.active_members / self.total_members

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "organization_id": self.organization_id,
            "total_members": self.total_members,
            "active_members": self.active_members,
            "activity_rate": round(self.activity_rate, 2),
            "avg_task_completion_rate": round(self.avg_task_completion_rate, 2),
            "total_overdue_tasks": self.total_overdue_tasks,
            "total_goals_at_risk": self.total_goals_at_risk,
            "top_performers": self.top_performers[:3],
            "members_needing_attention": self.members_needing_attention[:3],
        }


@dataclass
class DailyFacts:
    """
    日次ファクトの集合

    ファクト収集エンジンが収集する全ての事実を保持する。
    """

    # 収集日
    date: date = field(default_factory=date.today)

    # 組織ID
    organization_id: str = ""

    # タスク関連
    task_facts: List[TaskFact] = field(default_factory=list)

    # 目標関連
    goal_facts: List[GoalFact] = field(default_factory=list)

    # コミュニケーション関連
    communication_facts: List[CommunicationFact] = field(default_factory=list)

    # チーム全体
    team_fact: Optional[TeamFact] = None

    # 既存のインサイト（A1-A4で検出されたもの）
    existing_insights: List[Dict[str, Any]] = field(default_factory=list)

    # 収集時刻
    collected_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "date": self.date.isoformat(),
            "organization_id": self.organization_id,
            "task_facts": [t.to_dict() for t in self.task_facts],
            "goal_facts": [g.to_dict() for g in self.goal_facts],
            "communication_facts": [c.to_dict() for c in self.communication_facts],
            "team_fact": self.team_fact.to_dict() if self.team_fact else None,
            "existing_insights_count": len(self.existing_insights),
            "collected_at": self.collected_at.isoformat(),
        }


# =============================================================================
# 分析結果モデル
# =============================================================================


@dataclass
class Anomaly:
    """
    検出された異常

    Attributes:
        anomaly_type: 異常のタイプ
        subject: 対象（ユーザー名、タスク名など）
        description: 説明
        current_value: 現在値
        expected_value: 期待値
        deviation: 偏差（標準偏差の何倍か）
        severity: 深刻度
        detected_at: 検出日時
    """

    anomaly_type: str
    subject: str
    description: str
    current_value: float
    expected_value: float
    deviation: float
    severity: FeedbackPriority = FeedbackPriority.MEDIUM
    detected_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "anomaly_type": self.anomaly_type,
            "subject": self.subject,
            "description": self.description,
            "current_value": self.current_value,
            "expected_value": self.expected_value,
            "deviation": round(self.deviation, 2),
            "severity": self.severity.value,
        }


@dataclass
class Trend:
    """
    検出されたトレンド

    Attributes:
        metric_name: 指標名
        direction: 方向
        change_rate: 変化率（%）
        comparison_period: 比較期間
        data_points: データポイント数
        confidence: 確信度
    """

    metric_name: str
    direction: TrendDirection
    change_rate: float
    comparison_period: ComparisonPeriod
    data_points: int = 0
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "metric_name": self.metric_name,
            "direction": self.direction.value,
            "change_rate": round(self.change_rate, 2),
            "comparison_period": self.comparison_period.value,
            "confidence": round(self.confidence, 2),
        }


@dataclass
class AnalysisResult:
    """
    分析結果

    分析エンジンの出力を保持する。
    """

    # 検出された異常
    anomalies: List[Anomaly] = field(default_factory=list)

    # 検出されたトレンド
    trends: List[Trend] = field(default_factory=list)

    # 注目すべき変化
    notable_changes: List[Dict[str, Any]] = field(default_factory=list)

    # ポジティブな発見
    positive_findings: List[Dict[str, Any]] = field(default_factory=list)

    # 分析時刻
    analyzed_at: datetime = field(default_factory=datetime.now)

    @property
    def has_critical_items(self) -> bool:
        """クリティカルな項目があるか"""
        return any(a.severity == FeedbackPriority.CRITICAL for a in self.anomalies)

    @property
    def has_high_priority_items(self) -> bool:
        """高優先度の項目があるか"""
        return any(
            a.severity in (FeedbackPriority.CRITICAL, FeedbackPriority.HIGH)
            for a in self.anomalies
        )

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "anomalies": [a.to_dict() for a in self.anomalies],
            "trends": [t.to_dict() for t in self.trends],
            "notable_changes": self.notable_changes,
            "positive_findings": self.positive_findings,
            "has_critical_items": self.has_critical_items,
            "analyzed_at": self.analyzed_at.isoformat(),
        }


# =============================================================================
# フィードバックアイテムモデル
# =============================================================================


@dataclass
class FeedbackItem:
    """
    フィードバックの個別項目

    CEOに伝える1つの情報単位。
    """

    # 基本情報
    category: InsightCategory
    priority: FeedbackPriority
    title: str
    description: str

    # 詳細情報
    evidence: List[str] = field(default_factory=list)  # 事実のリスト
    hypothesis: Optional[str] = None  # 仮説（「〜かもしれません」）
    recommendation: Optional[str] = None  # 推奨アクション

    # メタデータ
    related_users: List[str] = field(default_factory=list)
    related_metrics: Dict[str, Any] = field(default_factory=dict)

    def get_icon(self) -> str:
        """カテゴリに応じたアイコンを取得"""
        icon_map = {
            InsightCategory.TASK_PROGRESS: FeedbackIcons.TASK,
            InsightCategory.GOAL_ACHIEVEMENT: FeedbackIcons.GOAL,
            InsightCategory.COMMUNICATION: FeedbackIcons.COMMUNICATION,
            InsightCategory.TEAM_HEALTH: FeedbackIcons.TEAM,
            InsightCategory.RISK_ANOMALY: FeedbackIcons.RISK,
            InsightCategory.POSITIVE_CHANGE: FeedbackIcons.POSITIVE,
            InsightCategory.RECOMMENDATION: FeedbackIcons.RECOMMENDATION,
        }
        return icon_map.get(self.category, FeedbackIcons.INFO)

    def get_priority_icon(self) -> str:
        """優先度に応じたアイコンを取得"""
        icon_map = {
            FeedbackPriority.CRITICAL: FeedbackIcons.PRIORITY_CRITICAL,
            FeedbackPriority.HIGH: FeedbackIcons.PRIORITY_HIGH,
            FeedbackPriority.MEDIUM: FeedbackIcons.PRIORITY_MEDIUM,
            FeedbackPriority.LOW: FeedbackIcons.PRIORITY_LOW,
        }
        return icon_map.get(self.priority, "")

    def to_text(self, include_evidence: bool = True) -> str:
        """テキスト形式に変換"""
        parts = [f"{self.get_icon()} {self.title}"]

        if self.description:
            parts.append(f"   {self.description}")

        if include_evidence and self.evidence:
            for ev in self.evidence[:3]:  # 最大3つ
                parts.append(f"   ・{ev}")

        if self.hypothesis:
            parts.append(f"   → {self.hypothesis}")

        if self.recommendation:
            parts.append(f"   💡 {self.recommendation}")

        return "\n".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "category": self.category.value,
            "priority": self.priority.value,
            "title": self.title,
            "description": self.description,
            "evidence": self.evidence,
            "hypothesis": self.hypothesis,
            "recommendation": self.recommendation,
            "related_users": self.related_users,
        }


# =============================================================================
# フィードバックモデル
# =============================================================================


@dataclass
class CEOFeedback:
    """
    CEOへのフィードバック

    配信される1つのフィードバックメッセージ全体。
    """

    # 基本情報
    feedback_id: str
    feedback_type: FeedbackType
    organization_id: str
    recipient_user_id: str
    recipient_name: str

    # 内容
    items: List[FeedbackItem] = field(default_factory=list)
    summary: str = ""  # エグゼクティブサマリー

    # ステータス
    status: FeedbackStatus = FeedbackStatus.GENERATING
    generated_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None  # sent_atのエイリアス
    read_at: Optional[datetime] = None

    # 配信情報
    delivery_channel: str = "chatwork"
    chatwork_room_id: Optional[str] = None
    chatwork_message_id: Optional[str] = None

    # メタデータ
    source_facts: Optional[DailyFacts] = None
    source_analysis: Optional[AnalysisResult] = None

    @property
    def highest_priority(self) -> FeedbackPriority:
        """最も高い優先度を取得"""
        if not self.items:
            return FeedbackPriority.LOW

        priority_order = [
            FeedbackPriority.CRITICAL,
            FeedbackPriority.HIGH,
            FeedbackPriority.MEDIUM,
            FeedbackPriority.LOW,
        ]

        for priority in priority_order:
            if any(item.priority == priority for item in self.items):
                return priority

        return FeedbackPriority.LOW

    @property
    def item_count(self) -> int:
        """項目数"""
        return len(self.items)

    def get_items_by_priority(self, priority: FeedbackPriority) -> List[FeedbackItem]:
        """優先度で項目をフィルタ"""
        return [item for item in self.items if item.priority == priority]

    def get_items_by_category(self, category: InsightCategory) -> List[FeedbackItem]:
        """カテゴリで項目をフィルタ"""
        return [item for item in self.items if item.category == category]

    def to_text(self) -> str:
        """テキスト形式に変換（ChatWork送信用）"""
        from .constants import FeedbackTemplates

        parts = []

        # ヘッダー
        if self.feedback_type == FeedbackType.DAILY_DIGEST:
            header = FeedbackTemplates.DAILY_DIGEST_HEADER.format(
                date=self.generated_at.strftime("%m/%d") if self.generated_at else "",
                weekday=["月", "火", "水", "木", "金", "土", "日"][
                    self.generated_at.weekday()
                ] if self.generated_at else "",
                name=self.recipient_name,
            )
        elif self.feedback_type == FeedbackType.REALTIME_ALERT:
            header = FeedbackTemplates.ALERT_HEADER.format(name=self.recipient_name)
        else:
            header = f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n📊 {self.recipient_name}さんへのフィードバック\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

        parts.append(header)

        # サマリー
        if self.summary:
            parts.append(f"\n{self.summary}")

        # 項目
        if self.items:
            parts.append("\n【注目ポイント】\n")
            for item in self.items:
                parts.append(item.to_text())
                parts.append("")

        # フッター
        parts.append(FeedbackTemplates.FOOTER)

        return "\n".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "feedback_id": self.feedback_id,
            "feedback_type": self.feedback_type.value,
            "organization_id": self.organization_id,
            "recipient_user_id": self.recipient_user_id,
            "recipient_name": self.recipient_name,
            "items": [item.to_dict() for item in self.items],
            "summary": self.summary,
            "status": self.status.value,
            "highest_priority": self.highest_priority.value,
            "item_count": self.item_count,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
        }


# =============================================================================
# 配信結果モデル
# =============================================================================


@dataclass
class DeliveryResult:
    """
    配信結果

    Attributes:
        success: 成功したか
        feedback_id: フィードバックID
        channel: 配信チャネル
        channel_target: 配信先（ルームIDなど）
        message_id: 送信されたメッセージID
        delivered_at: 配信日時
        error_message: エラーメッセージ（失敗時）
    """

    feedback_id: str
    success: bool
    channel: str = "chatwork"
    channel_target: Optional[str] = None
    message_id: Optional[str] = None
    delivered_at: Optional[datetime] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "success": self.success,
            "feedback_id": self.feedback_id,
            "channel": self.channel,
            "channel_target": self.channel_target,
            "message_id": self.message_id,
            "delivered_at": self.delivered_at.isoformat() if self.delivered_at else None,
            "error": self.error_message,
        }
