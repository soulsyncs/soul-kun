"""
Admin Dashboard Schemas

管理ダッシュボードAPI用のPydanticスキーマ定義。
KPIサマリー、Brain分析、コスト管理、メンバー管理のレスポンスモデル。

PII保護:
    - user_message等の個人情報を含むフィールドは定義しない
    - 統計値・集計値のみを返す
"""

from __future__ import annotations

import datetime as dt
from typing import List, Optional

from pydantic import BaseModel, Field


# =============================================================================
# 共通
# =============================================================================


class AdminErrorResponse(BaseModel):
    """管理API エラーレスポンス"""

    status: str = Field("failed", description="ステータス")
    error_code: str = Field(..., description="エラーコード")
    error_message: str = Field(..., description="エラーメッセージ")


# =============================================================================
# 認証
# =============================================================================


class GoogleAuthRequest(BaseModel):
    """Google認証リクエスト"""

    id_token: str = Field(..., description="Google ID Token")


class TokenLoginRequest(BaseModel):
    """トークンログインリクエスト（暫定認証用）"""

    token: str = Field(..., description="JWT access token")


class AuthTokenResponse(BaseModel):
    """認証トークンレスポンス（トークンはhttpOnly cookieで配信）"""

    status: str = Field("success", description="ステータス")
    token_type: str = Field("bearer", description="トークンタイプ")
    expires_in: int = Field(..., description="有効期限（秒）")


class AuthMeResponse(BaseModel):
    """現在のユーザー情報レスポンス"""

    user_id: str = Field(..., description="ユーザーID")
    organization_id: str = Field(..., description="組織ID")
    name: Optional[str] = Field(None, description="ユーザー名")
    email: Optional[str] = Field(None, description="メールアドレス")
    role: Optional[str] = Field(None, description="ロール")
    role_level: int = Field(..., description="権限レベル（1-6）")
    department_id: Optional[str] = Field(None, description="所属部署ID")


# =============================================================================
# ダッシュボード
# =============================================================================


class AlertSummary(BaseModel):
    """アラート概要"""

    id: str = Field(..., description="アラートID")
    alert_type: str = Field(..., description="アラート種別")
    severity: str = Field(..., description="重要度（critical/warning/info）")
    message: str = Field(..., description="アラートメッセージ")
    created_at: dt.datetime = Field(..., description="作成日時")
    is_resolved: bool = Field(False, description="解決済みか")


class InsightSummary(BaseModel):
    """インサイト概要"""

    id: str = Field(..., description="インサイトID")
    insight_type: str = Field(..., description="インサイト種別")
    title: str = Field(..., description="タイトル")
    summary: str = Field(..., description="概要")
    created_at: dt.datetime = Field(..., description="作成日時")


class DashboardKPIs(BaseModel):
    """ダッシュボードKPI"""

    total_conversations: int = Field(0, description="会話総数")
    avg_response_time_ms: float = Field(0.0, description="平均応答時間（ミリ秒）")
    error_rate: float = Field(0.0, description="エラー率（0.0-1.0）")
    total_cost_today: float = Field(0.0, description="本日のコスト（円）")
    monthly_budget_remaining: float = Field(0.0, description="月間予算残（円）")
    active_alerts_count: int = Field(0, description="アクティブアラート数")


class DashboardSummaryResponse(BaseModel):
    """ダッシュボードサマリーレスポンス"""

    status: str = Field("success", description="ステータス")
    period: str = Field(..., description="集計期間（today/7d/30d）")
    kpis: DashboardKPIs = Field(..., description="KPI")
    recent_alerts: List[AlertSummary] = Field(
        default_factory=list, description="最近のアラート（最大5件）"
    )
    recent_insights: List[InsightSummary] = Field(
        default_factory=list, description="最近のインサイト（最大5件）"
    )
    generated_at: dt.datetime = Field(..., description="生成日時")


# =============================================================================
# Brain分析
# =============================================================================


class BrainDailyMetric(BaseModel):
    """Brain日次メトリクス"""

    date: dt.date = Field(..., description="日付")
    conversations: int = Field(0, description="会話数")
    avg_latency_ms: float = Field(0.0, description="平均レイテンシ（ミリ秒）")
    error_rate: float = Field(0.0, description="エラー率（0.0-1.0）")
    cost: float = Field(0.0, description="コスト（円）")


class BrainMetricsResponse(BaseModel):
    """Brain メトリクスレスポンス"""

    status: str = Field("success", description="ステータス")
    days: int = Field(..., description="集計日数")
    metrics: List[BrainDailyMetric] = Field(
        default_factory=list, description="日次メトリクスリスト"
    )


class BrainLogEntry(BaseModel):
    """Brain決定ログエントリ

    PII保護: user_messageフィールドは含めない。
    brain_decision_logsのid, created_at, selected_action, confidence, timeのみ。
    """

    id: str = Field(..., description="ログID")
    created_at: dt.datetime = Field(..., description="作成日時")
    selected_action: str = Field(..., description="選択されたアクション")
    decision_confidence: Optional[float] = Field(
        None, description="判断確信度（0.0-1.0）"
    )
    total_time_ms: Optional[float] = Field(
        None, description="判断にかかった時間（ミリ秒）"
    )


class BrainLogsResponse(BaseModel):
    """Brain決定ログレスポンス"""

    status: str = Field("success", description="ステータス")
    logs: List[BrainLogEntry] = Field(
        default_factory=list, description="決定ログリスト"
    )
    total_count: int = Field(0, description="総件数")
    offset: int = Field(0, description="オフセット")
    limit: int = Field(50, description="リミット")


# =============================================================================
# コスト管理
# =============================================================================


class CostMonthlyEntry(BaseModel):
    """月次コストエントリ"""

    year_month: str = Field(..., description="年月（YYYY-MM）")
    total_cost: float = Field(0.0, description="合計コスト（円）")
    requests: int = Field(0, description="リクエスト数")
    budget: Optional[float] = Field(None, description="月間予算（円）")
    status: str = Field("normal", description="ステータス（normal/warning/exceeded）")


class CostMonthlyResponse(BaseModel):
    """月次コストレスポンス"""

    status: str = Field("success", description="ステータス")
    months: List[CostMonthlyEntry] = Field(
        default_factory=list, description="月次コストリスト"
    )


class CostDailyEntry(BaseModel):
    """日次コストエントリ"""

    date: dt.date = Field(..., description="日付")
    cost: float = Field(0.0, description="コスト（円）")
    requests: int = Field(0, description="リクエスト数")


class CostDailyResponse(BaseModel):
    """日次コストレスポンス"""

    status: str = Field("success", description="ステータス")
    days: int = Field(..., description="集計日数")
    daily: List[CostDailyEntry] = Field(
        default_factory=list, description="日次コストリスト"
    )


class CostModelBreakdown(BaseModel):
    """モデル別コスト内訳"""

    model: str = Field(..., description="モデル名")
    cost: float = Field(0.0, description="コスト（円）")
    requests: int = Field(0, description="リクエスト数")
    pct: float = Field(0.0, description="割合（0.0-100.0）")


class CostTierBreakdown(BaseModel):
    """ティア別コスト内訳"""

    tier: str = Field(..., description="ティア名")
    cost: float = Field(0.0, description="コスト（円）")
    requests: int = Field(0, description="リクエスト数")
    pct: float = Field(0.0, description="割合（0.0-100.0）")


class CostBreakdownResponse(BaseModel):
    """コスト内訳レスポンス"""

    status: str = Field("success", description="ステータス")
    days: int = Field(..., description="集計日数")
    by_model: List[CostModelBreakdown] = Field(
        default_factory=list, description="モデル別内訳"
    )
    by_tier: List[CostTierBreakdown] = Field(
        default_factory=list, description="ティア別内訳"
    )


# =============================================================================
# メンバー管理
# =============================================================================


class MemberResponse(BaseModel):
    """メンバーレスポンス"""

    user_id: str = Field(..., description="ユーザーID")
    name: Optional[str] = Field(None, description="ユーザー名")
    email: Optional[str] = Field(None, description="メールアドレス")
    role: Optional[str] = Field(None, description="ロール名")
    role_level: Optional[int] = Field(None, description="権限レベル（1-6）")
    department: Optional[str] = Field(None, description="所属部署名")
    department_id: Optional[str] = Field(None, description="所属部署ID")
    created_at: Optional[dt.datetime] = Field(None, description="作成日時")


class MembersListResponse(BaseModel):
    """メンバー一覧レスポンス"""

    status: str = Field("success", description="ステータス")
    members: List[MemberResponse] = Field(
        default_factory=list, description="メンバーリスト"
    )
    total_count: int = Field(0, description="総件数")
    offset: int = Field(0, description="オフセット")
    limit: int = Field(50, description="リミット")


# =============================================================================
# 組織図・部署管理
# =============================================================================


class DepartmentMember(BaseModel):
    """部署所属メンバー"""

    user_id: str = Field(..., description="ユーザーID")
    name: Optional[str] = Field(None, description="ユーザー名")
    role: Optional[str] = Field(None, description="ロール名")
    role_level: Optional[int] = Field(None, description="権限レベル")
    is_primary: bool = Field(False, description="主所属か")


class DepartmentResponse(BaseModel):
    """部署レスポンス"""

    id: str = Field(..., description="部署ID")
    name: str = Field(..., description="部署名")
    parent_department_id: Optional[str] = Field(None, description="親部署ID")
    level: int = Field(0, description="階層レベル")
    display_order: int = Field(0, description="表示順")
    description: Optional[str] = Field(None, description="説明")
    is_active: bool = Field(True, description="有効か")
    member_count: int = Field(0, description="所属メンバー数")
    created_at: Optional[dt.datetime] = Field(None, description="作成日時")
    updated_at: Optional[dt.datetime] = Field(None, description="更新日時")


class DepartmentTreeNode(BaseModel):
    """部署ツリーノード（子部署を含む再帰構造）"""

    id: str = Field(..., description="部署ID")
    name: str = Field(..., description="部署名")
    parent_department_id: Optional[str] = Field(None, description="親部署ID")
    level: int = Field(0, description="階層レベル")
    display_order: int = Field(0, description="表示順")
    description: Optional[str] = Field(None, description="説明")
    is_active: bool = Field(True, description="有効か")
    member_count: int = Field(0, description="所属メンバー数")
    children: List["DepartmentTreeNode"] = Field(
        default_factory=list, description="子部署"
    )


class DepartmentsTreeResponse(BaseModel):
    """部署ツリーレスポンス"""

    status: str = Field("success", description="ステータス")
    departments: List[DepartmentTreeNode] = Field(
        default_factory=list, description="部署ツリー（ルートノード群）"
    )
    total_count: int = Field(0, description="全部署数")


class DepartmentDetailResponse(BaseModel):
    """部署詳細レスポンス（メンバーリスト込み）"""

    status: str = Field("success", description="ステータス")
    department: DepartmentResponse = Field(..., description="部署情報")
    members: List[DepartmentMember] = Field(
        default_factory=list, description="所属メンバー"
    )


class CreateDepartmentRequest(BaseModel):
    """部署作成リクエスト"""

    name: str = Field(..., min_length=1, max_length=100, description="部署名")
    parent_department_id: Optional[str] = Field(
        None,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        description="親部署ID（UUID）",
    )
    description: Optional[str] = Field(None, max_length=500, description="説明")
    display_order: int = Field(0, ge=0, description="表示順")


class UpdateDepartmentRequest(BaseModel):
    """部署更新リクエスト"""

    name: Optional[str] = Field(None, min_length=1, max_length=100, description="部署名")
    parent_department_id: Optional[str] = Field(
        None,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        description="親部署ID（UUID）",
    )
    description: Optional[str] = Field(None, max_length=500, description="説明")
    display_order: Optional[int] = Field(None, ge=0, description="表示順")


class DepartmentMutationResponse(BaseModel):
    """部署変更レスポンス"""

    status: str = Field("success", description="ステータス")
    department_id: str = Field(..., description="部署ID")
    message: str = Field(..., description="メッセージ")


class MemberDepartmentInfo(BaseModel):
    """メンバーの所属部署情報"""

    department_id: str = Field(..., description="部署ID")
    department_name: str = Field(..., description="部署名")
    role: Optional[str] = Field(None, description="部署内ロール")
    role_level: Optional[int] = Field(None, description="権限レベル")
    is_primary: bool = Field(False, description="主所属か")


class MemberDetailResponse(BaseModel):
    """メンバー詳細レスポンス（全属性）"""

    status: str = Field("success", description="ステータス")
    user_id: str = Field(..., description="ユーザーID")
    name: Optional[str] = Field(None, description="ユーザー名")
    email: Optional[str] = Field(None, description="メールアドレス")
    role: Optional[str] = Field(None, description="ロール名")
    role_level: Optional[int] = Field(None, description="権限レベル")
    departments: List[MemberDepartmentInfo] = Field(
        default_factory=list, description="所属部署リスト"
    )
    chatwork_account_id: Optional[str] = Field(None, description="ChatWorkアカウントID")
    is_active: bool = Field(True, description="有効か")
    avatar_url: Optional[str] = Field(None, description="顔写真URL")
    employment_type: Optional[str] = Field(None, description="雇用形態（正社員/業務委託/パート等）")
    evaluation: Optional[str] = Field(None, description="評価ランク（S/A/B/C/D）")
    goal_achievement: Optional[int] = Field(None, description="目標達成率（0〜100）", ge=0, le=100)
    skills: List[str] = Field(default_factory=list, description="スキルリスト（例: [\"営業\", \"Excel\"]）")
    notes: Optional[str] = Field(None, description="備考・メモ（自由記述）")
    phone: Optional[str] = Field(None, description="電話番号")
    birthday: Optional[dt.date] = Field(None, description="誕生日（YYYY-MM-DD）")
    hire_date: Optional[dt.datetime] = Field(None, description="入社日（主所属部署の開始日）")
    created_at: Optional[dt.datetime] = Field(None, description="作成日時")
    updated_at: Optional[dt.datetime] = Field(None, description="更新日時")


class UpdateMemberRequest(BaseModel):
    """メンバー更新リクエスト"""

    name: Optional[str] = Field(None, min_length=1, max_length=100, description="名前")
    email: Optional[str] = Field(None, max_length=200, description="メールアドレス")
    chatwork_account_id: Optional[str] = Field(
        None, max_length=50, description="ChatWorkアカウントID"
    )
    employment_type: Optional[str] = Field(
        None, max_length=50, description="雇用形態（正社員/業務委託/パート/インターン/顧問）"
    )
    avatar_url: Optional[str] = Field(None, max_length=500, description="顔写真URL")
    evaluation: Optional[str] = Field(None, max_length=10, description="評価ランク（S/A/B/C/D）")
    goal_achievement: Optional[int] = Field(None, description="目標達成率（0〜100）", ge=0, le=100)
    skills: Optional[List[str]] = Field(None, description="スキルリスト（例: [\"営業\", \"Excel\"]）")
    notes: Optional[str] = Field(None, description="備考・メモ（自由記述）")
    phone: Optional[str] = Field(None, max_length=50, description="電話番号")
    birthday: Optional[dt.date] = Field(None, description="誕生日（YYYY-MM-DD）")


class MemberDepartmentAssignment(BaseModel):
    """メンバー部署割り当て"""

    department_id: str = Field(
        ...,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        description="部署ID（UUID）",
    )
    role_id: str = Field(
        ...,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        description="ロールID（UUID）",
    )
    is_primary: bool = Field(False, description="主所属か")


class UpdateMemberDepartmentsRequest(BaseModel):
    """メンバー所属部署更新リクエスト"""

    departments: List[MemberDepartmentAssignment] = Field(
        ..., min_length=1, description="所属部署リスト（最低1つ）"
    )


# =============================================
# Phase 2: Goals / Wellness / Tasks schemas
# =============================================


class GoalSummary(BaseModel):
    """目標サマリー（一覧表示用）"""

    id: str
    user_id: str
    user_name: Optional[str] = None
    department_name: Optional[str] = None
    title: str
    goal_type: str
    goal_level: str
    status: str
    period_type: str
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    deadline: Optional[str] = None
    target_value: Optional[float] = None
    current_value: Optional[float] = None
    unit: Optional[str] = None
    progress_pct: Optional[float] = None


class GoalsListResponse(BaseModel):
    """目標一覧レスポンス"""

    status: str = "success"
    goals: List[GoalSummary] = Field(default_factory=list)
    total_count: int = 0


class GoalProgressEntry(BaseModel):
    """目標進捗エントリ"""

    id: str
    progress_date: str
    value: Optional[float] = None
    cumulative_value: Optional[float] = None
    daily_note: Optional[str] = None


class GoalDetailResponse(BaseModel):
    """目標詳細レスポンス"""

    status: str = "success"
    goal: GoalSummary
    progress: List[GoalProgressEntry] = Field(default_factory=list)


class GoalStatsResponse(BaseModel):
    """目標達成率サマリー"""

    status: str = "success"
    total_goals: int = 0
    active_goals: int = 0
    completed_goals: int = 0
    overdue_goals: int = 0
    completion_rate: float = 0.0
    by_department: List[dict] = Field(default_factory=list)


class EmotionAlertSummary(BaseModel):
    """感情アラートサマリー"""

    id: str
    user_id: str
    user_name: Optional[str] = None
    department_name: Optional[str] = None
    alert_type: str
    risk_level: str
    baseline_score: Optional[float] = None
    current_score: Optional[float] = None
    score_change: Optional[float] = None
    consecutive_negative_days: Optional[int] = None
    status: str
    first_detected_at: Optional[str] = None
    last_detected_at: Optional[str] = None


class EmotionAlertsResponse(BaseModel):
    """感情アラート一覧レスポンス"""

    status: str = "success"
    alerts: List[EmotionAlertSummary] = Field(default_factory=list)
    total_count: int = 0


class EmotionTrendEntry(BaseModel):
    """感情トレンドエントリ"""

    date: str
    avg_score: float
    message_count: int
    negative_count: int
    positive_count: int


class EmotionTrendsResponse(BaseModel):
    """感情トレンドレスポンス"""

    status: str = "success"
    trends: List[EmotionTrendEntry] = Field(default_factory=list)
    period_start: Optional[str] = None
    period_end: Optional[str] = None


class TaskOverviewStats(BaseModel):
    """タスク全体サマリー"""

    status: str = "success"
    chatwork_tasks: dict = Field(default_factory=dict)
    autonomous_tasks: dict = Field(default_factory=dict)
    detected_tasks: dict = Field(default_factory=dict)


class TaskItem(BaseModel):
    """タスクアイテム"""

    id: str
    source: str  # chatwork / autonomous / detected
    title: str
    status: str
    assignee_name: Optional[str] = None
    deadline: Optional[str] = None
    created_at: Optional[str] = None


class TaskListResponse(BaseModel):
    """タスク一覧レスポンス"""

    status: str = "success"
    tasks: List[TaskItem] = Field(default_factory=list)
    total_count: int = 0


# =============================================
# Phase 3: Insights / Meetings / Proactive schemas
# =============================================


class InsightSummary(BaseModel):
    """インサイトサマリー"""

    id: str
    insight_type: str
    source_type: str
    importance: str
    title: str
    description: str
    recommended_action: Optional[str] = None
    status: str
    department_name: Optional[str] = None
    created_at: Optional[str] = None


class InsightsListResponse(BaseModel):
    """インサイト一覧レスポンス"""

    status: str = "success"
    insights: List[InsightSummary] = Field(default_factory=list)
    total_count: int = 0


class QuestionPatternSummary(BaseModel):
    """質問パターンサマリー"""

    id: str
    question_category: str
    normalized_question: str
    occurrence_count: int
    last_asked_at: Optional[str] = None
    status: str


class QuestionPatternsResponse(BaseModel):
    """質問パターン一覧"""

    status: str = "success"
    patterns: List[QuestionPatternSummary] = Field(default_factory=list)
    total_count: int = 0


class WeeklyReportSummary(BaseModel):
    """週次レポートサマリー"""

    id: str
    week_start: str
    week_end: str
    status: str
    sent_at: Optional[str] = None
    sent_via: Optional[str] = None


class WeeklyReportsResponse(BaseModel):
    """週次レポート一覧"""

    status: str = "success"
    reports: List[WeeklyReportSummary] = Field(default_factory=list)
    total_count: int = 0


class WeeklyReportDetailResponse(BaseModel):
    """週次レポート詳細"""

    status: str = "success"
    report: WeeklyReportSummary
    report_content: str
    insights_summary: Optional[dict] = None


class MeetingSummary(BaseModel):
    """ミーティングサマリー"""

    id: str
    title: Optional[str] = None
    meeting_type: str
    meeting_date: Optional[str] = None
    duration_seconds: Optional[float] = None
    status: str
    source: str
    has_transcript: bool = False
    has_recording: bool = False


class MeetingsListResponse(BaseModel):
    """ミーティング一覧"""

    status: str = "success"
    meetings: List[MeetingSummary] = Field(default_factory=list)
    total_count: int = 0


class ProactiveActionSummary(BaseModel):
    """プロアクティブアクションサマリー"""

    id: str
    user_id: str
    trigger_type: str
    priority: str
    message_type: str
    user_response_positive: Optional[bool] = None
    created_at: Optional[str] = None


class ProactiveActionsResponse(BaseModel):
    """プロアクティブアクション一覧"""

    status: str = "success"
    actions: List[ProactiveActionSummary] = Field(default_factory=list)
    total_count: int = 0


class ProactiveStatsResponse(BaseModel):
    """プロアクティブ統計"""

    status: str = "success"
    total_actions: int = 0
    positive_responses: int = 0
    response_rate: float = 0.0
    by_trigger_type: List[dict] = Field(default_factory=list)


# =============================================
# Phase 4: Teachings / System Health schemas
# =============================================


class TeachingSummary(BaseModel):
    """CEO教えサマリー"""

    id: str
    category: str
    subcategory: Optional[str] = None
    statement: str
    validation_status: str
    priority: Optional[int] = None
    is_active: Optional[bool] = None
    usage_count: Optional[int] = None
    helpful_count: Optional[int] = None
    last_used_at: Optional[str] = None


class TeachingsListResponse(BaseModel):
    """CEO教え一覧"""

    status: str = "success"
    teachings: List[TeachingSummary] = Field(default_factory=list)
    total_count: int = 0


class TeachingConflictSummary(BaseModel):
    """教え矛盾サマリー"""

    id: str
    teaching_id: str
    conflict_type: str
    severity: str
    description: str
    conflicting_teaching_id: Optional[str] = None
    created_at: Optional[str] = None


class TeachingConflictsResponse(BaseModel):
    """教え矛盾一覧"""

    status: str = "success"
    conflicts: List[TeachingConflictSummary] = Field(default_factory=list)
    total_count: int = 0


class TeachingUsageStatsResponse(BaseModel):
    """教え利用統計"""

    status: str = "success"
    total_usages: int = 0
    helpful_rate: float = 0.0
    by_category: List[dict] = Field(default_factory=list)


class SystemHealthSummary(BaseModel):
    """システムヘルスサマリー"""

    status: str = "success"
    latest_date: Optional[str] = None
    total_conversations: int = 0
    unique_users: int = 0
    avg_response_time_ms: Optional[int] = None
    p95_response_time_ms: Optional[int] = None
    success_rate: float = 0.0
    error_count: int = 0
    avg_confidence: Optional[float] = None


class DailyMetricEntry(BaseModel):
    """日次メトリクスエントリ"""

    metric_date: str
    total_conversations: int = 0
    unique_users: int = 0
    avg_response_time_ms: Optional[int] = None
    success_count: int = 0
    error_count: int = 0
    avg_confidence: Optional[float] = None


class SystemMetricsResponse(BaseModel):
    """システムメトリクス推移"""

    status: str = "success"
    metrics: List[DailyMetricEntry] = Field(default_factory=list)


class SelfDiagnosisSummary(BaseModel):
    """自己診断サマリー"""

    id: str
    diagnosis_type: str
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    overall_score: float
    total_interactions: int = 0
    successful_interactions: int = 0
    identified_weaknesses: Optional[List[str]] = None


class SelfDiagnosesResponse(BaseModel):
    """自己診断一覧"""

    status: str = "success"
    diagnoses: List[SelfDiagnosisSummary] = Field(default_factory=list)
    total_count: int = 0


# =============================================================================
# Google Calendar 連携
# =============================================================================


class GoogleCalendarStatusResponse(BaseModel):
    """Googleカレンダー接続状態"""

    status: str = "success"
    is_connected: bool = False
    google_email: Optional[str] = None
    connected_at: Optional[str] = None
    token_valid: bool = False


class GoogleCalendarConnectResponse(BaseModel):
    """OAuth認可URL"""

    status: str = "success"
    auth_url: str = Field(..., description="GoogleのOAuth認可画面URL")


class GoogleCalendarDisconnectResponse(BaseModel):
    """接続解除結果"""

    status: str = "success"
    message: str = "Googleカレンダー連携を解除しました"


# =============================================================================
# 緊急停止（Emergency Stop）— Step 0-3
# =============================================================================


class EmergencyStopStatusResponse(BaseModel):
    """緊急停止の状態"""

    status: str = "success"
    is_active: bool = False
    activated_by: Optional[str] = None
    deactivated_by: Optional[str] = None
    reason: Optional[str] = None
    activated_at: Optional[str] = None
    deactivated_at: Optional[str] = None


class EmergencyStopActivateRequest(BaseModel):
    """緊急停止の有効化リクエスト"""

    reason: str = Field("", description="停止理由")


class EmergencyStopActionResponse(BaseModel):
    """緊急停止の操作結果"""

    status: str = "success"
    message: str = Field(..., description="操作結果メッセージ")
    is_active: bool = Field(..., description="操作後の停止状態")


# =============================================================================
# Phase 2 新機能: AI ROI / Teaching Penetration
# =============================================================================


class AiRoiTierBreakdown(BaseModel):
    """AIティア別ROI内訳"""

    tier: str = Field(..., description="ティア名（brain/assistant/generation等）")
    requests: int = Field(0, description="リクエスト数")
    cost_jpy: float = Field(0.0, description="コスト（円）")
    time_saved_hours: float = Field(0.0, description="削減工数（時間）")
    labor_saved_jpy: float = Field(0.0, description="削減人件費（円）")


class AiRoiResponse(BaseModel):
    """AI費用対効果レスポンス"""

    status: str = "success"
    days: int = Field(30, description="集計日数")
    total_cost_jpy: float = Field(0.0, description="AI費用合計（円）")
    total_requests: int = Field(0, description="総リクエスト数")
    time_saved_hours: float = Field(0.0, description="総削減工数（時間）")
    labor_saved_jpy: float = Field(0.0, description="総削減人件費（円）")
    roi_multiplier: float = Field(0.0, description="ROI倍率（削減人件費 / AI費用）")
    by_tier: List[AiRoiTierBreakdown] = Field(
        default_factory=list, description="ティア別内訳"
    )


class TeachingPenetrationItem(BaseModel):
    """教え別浸透度"""

    id: str = Field(..., description="教えID")
    statement: str = Field(..., description="教えの内容（先頭60文字）")
    category: str = Field(..., description="カテゴリ")
    usage_count: int = Field(0, description="利用回数")
    penetration_pct: float = Field(0.0, description="浸透度（%）")


class TeachingPenetrationCategory(BaseModel):
    """カテゴリ別浸透度"""

    category: str = Field(..., description="カテゴリ名")
    total_teachings: int = Field(0, description="教えの総数")
    used_teachings: int = Field(0, description="1回以上使われた教えの数")
    total_usages: int = Field(0, description="カテゴリ内総利用回数")
    penetration_pct: float = Field(0.0, description="使用率（used/total * 100）")


class TeachingPenetrationResponse(BaseModel):
    """理念浸透度レスポンス"""

    status: str = "success"
    total_teachings: int = Field(0, description="教えの総数")
    used_teachings: int = Field(0, description="1回以上使われた教えの数")
    total_usages: int = Field(0, description="総利用回数")
    overall_penetration_pct: float = Field(0.0, description="全体浸透度（%）")
    by_category: List[TeachingPenetrationCategory] = Field(
        default_factory=list, description="カテゴリ別浸透度"
    )
    top_teachings: List[TeachingPenetrationItem] = Field(
        default_factory=list, description="利用回数TOP5の教え"
    )
    unused_teachings: List[TeachingPenetrationItem] = Field(
        default_factory=list, description="未使用の教え（改善機会）"
    )


# =============================================================================
# Phase 3 新機能: Goal Forecast / Key Person Discovery
# =============================================================================


class GoalForecastItem(BaseModel):
    """目標別の未来予測"""

    id: str = Field(..., description="目標ID")
    title: str = Field(..., description="目標タイトル")
    user_name: Optional[str] = Field(None, description="担当者名")
    department_name: Optional[str] = Field(None, description="部署名")
    forecast_status: str = Field(
        ...,
        description="予測ステータス（ahead/on_track/at_risk/stalled/no_data）",
    )
    progress_pct: Optional[float] = Field(None, description="現在の進捗（%）")
    deadline: Optional[str] = Field(None, description="締切日")
    projected_completion_date: Optional[str] = Field(
        None, description="予測達成日（このペースで進んだ場合）"
    )
    days_to_deadline: Optional[int] = Field(
        None, description="締切まで残り日数（負値 = 超過）"
    )
    days_ahead_or_behind: Optional[int] = Field(
        None,
        description="締切と予測達成日の差（負値 = 余裕あり、正値 = 遅れ）",
    )
    current_value: Optional[float] = Field(None, description="現在値")
    target_value: Optional[float] = Field(None, description="目標値")
    unit: Optional[str] = Field(None, description="単位")
    slope_per_day: Optional[float] = Field(None, description="1日あたりの進捗速度")


class GoalForecastResponse(BaseModel):
    """目標未来予測レスポンス"""

    status: str = "success"
    total_active: int = Field(0, description="進行中の目標数")
    ahead_count: int = Field(0, description="順調に前倒しの目標数")
    on_track_count: int = Field(0, description="予定通りの目標数")
    at_risk_count: int = Field(0, description="達成が遅れそうな目標数")
    stalled_count: int = Field(0, description="進捗が止まっている目標数")
    forecasts: List[GoalForecastItem] = Field(
        default_factory=list, description="目標別予測リスト"
    )


class KeyPersonScore(BaseModel):
    """キーマンスコア"""

    user_id: str = Field(..., description="ユーザーID")
    name: Optional[str] = Field(None, description="名前")
    department_name: Optional[str] = Field(None, description="部署名")
    total_requests: int = Field(0, description="総AIリクエスト数（90日間）")
    active_days: int = Field(0, description="AI活用日数（ユニーク日数）")
    tiers_used: int = Field(0, description="使用AIティア数（多様性）")
    score: float = Field(0.0, description="キーマンスコア（0-100）")
    rank: int = Field(1, description="ランク（1位が最もキーマン）")
    recent_trend: str = Field(
        "stable", description="直近トレンド（rising/stable/declining）"
    )


class KeymenResponse(BaseModel):
    """隠れたキーマン発見レスポンス"""

    status: str = "success"
    period_days: int = Field(90, description="集計期間（日）")
    top_keymen: List[KeyPersonScore] = Field(
        default_factory=list, description="キーマンランキング（上位10名）"
    )
