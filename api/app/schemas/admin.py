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
    total_cost_today: float = Field(0.0, description="本日のコスト（USD）")
    monthly_budget_remaining: float = Field(0.0, description="月間予算残（USD）")
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
    cost: float = Field(0.0, description="コスト（USD）")


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
    total_cost: float = Field(0.0, description="合計コスト（USD）")
    requests: int = Field(0, description="リクエスト数")
    budget: Optional[float] = Field(None, description="月間予算（USD）")
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
    cost: float = Field(0.0, description="コスト（USD）")
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
    cost: float = Field(0.0, description="コスト（USD）")
    requests: int = Field(0, description="リクエスト数")
    pct: float = Field(0.0, description="割合（0.0-100.0）")


class CostTierBreakdown(BaseModel):
    """ティア別コスト内訳"""

    tier: str = Field(..., description="ティア名")
    cost: float = Field(0.0, description="コスト（USD）")
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
