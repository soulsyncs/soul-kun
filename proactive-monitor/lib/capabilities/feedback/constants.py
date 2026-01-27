# lib/capabilities/feedback/constants.py
"""
Phase F1: CEOフィードバックシステム - 定数定義

このモジュールは、CEOフィードバックシステムで使用する定数を定義します。

設計書: docs/20_next_generation_capabilities.md セクション8

Author: Claude Opus 4.5
Created: 2026-01-27
"""

from enum import Enum
from typing import Final


# =============================================================================
# フィードバックタイプ
# =============================================================================


class FeedbackType(str, Enum):
    """
    フィードバックの種類

    設計書8.2に基づく分類
    """

    # 毎朝8:00配信 - 今日注目すべきこと
    DAILY_DIGEST = "daily_digest"

    # 毎週月曜9:00配信 - 先週の振り返り + 今週の注目点
    WEEKLY_REVIEW = "weekly_review"

    # 毎月1日9:00配信 - 月次分析 + トレンド + 提案
    MONTHLY_INSIGHT = "monthly_insight"

    # 随時 - 重要な変化を即座に通知
    REALTIME_ALERT = "realtime_alert"

    # 「最近どう？」で深掘り
    ON_DEMAND = "on_demand"


class FeedbackPriority(str, Enum):
    """
    フィードバックの優先度
    """

    # 即時対応推奨
    CRITICAL = "critical"

    # 早期対応推奨
    HIGH = "high"

    # 通常
    MEDIUM = "medium"

    # 情報共有
    LOW = "low"


class FeedbackStatus(str, Enum):
    """
    フィードバックのステータス
    """

    # 生成中
    GENERATING = "generating"

    # 生成完了（未送信）
    READY = "ready"

    # 送信済み
    SENT = "sent"

    # 既読
    READ = "read"

    # 対応済み
    ACTIONED = "actioned"

    # 生成失敗
    FAILED = "failed"


class InsightCategory(str, Enum):
    """
    インサイトのカテゴリ（CEOが知りたい情報の種類）
    """

    # タスク・進捗関連
    TASK_PROGRESS = "task_progress"

    # 目標達成関連
    GOAL_ACHIEVEMENT = "goal_achievement"

    # コミュニケーション関連
    COMMUNICATION = "communication"

    # チームの状態関連
    TEAM_HEALTH = "team_health"

    # リスク・異常検知
    RISK_ANOMALY = "risk_anomaly"

    # ポジティブな変化
    POSITIVE_CHANGE = "positive_change"

    # 提案・推奨
    RECOMMENDATION = "recommendation"


class TrendDirection(str, Enum):
    """
    トレンドの方向
    """

    # 上昇傾向
    INCREASING = "increasing"

    # 横ばい
    STABLE = "stable"

    # 下降傾向
    DECREASING = "decreasing"

    # 急上昇
    SPIKE = "spike"

    # 急下降
    DROP = "drop"


class ComparisonPeriod(str, Enum):
    """
    比較期間
    """

    # 前日比
    DAY_OVER_DAY = "day_over_day"

    # 前週比
    WEEK_OVER_WEEK = "week_over_week"

    # 前月比
    MONTH_OVER_MONTH = "month_over_month"

    # 前年比
    YEAR_OVER_YEAR = "year_over_year"


# =============================================================================
# 配信パラメータ
# =============================================================================


class DeliveryParameters:
    """
    配信に関するパラメータ
    """

    # ==========================================================================
    # デイリーダイジェスト
    # ==========================================================================

    # 配信時刻（時）
    DAILY_DIGEST_HOUR: Final[int] = 8

    # 配信時刻（分）
    DAILY_DIGEST_MINUTE: Final[int] = 0

    # 最大項目数
    DAILY_DIGEST_MAX_ITEMS: Final[int] = 5

    # ==========================================================================
    # ウィークリーレビュー
    # ==========================================================================

    # 配信曜日（0=月曜, 6=日曜）
    WEEKLY_REVIEW_DAY: Final[int] = 0

    # 配信時刻（時）
    WEEKLY_REVIEW_HOUR: Final[int] = 9

    # 配信時刻（分）
    WEEKLY_REVIEW_MINUTE: Final[int] = 0

    # ==========================================================================
    # マンスリーインサイト
    # ==========================================================================

    # 配信日
    MONTHLY_INSIGHT_DAY: Final[int] = 1

    # 配信時刻（時）
    MONTHLY_INSIGHT_HOUR: Final[int] = 9

    # 配信時刻（分）
    MONTHLY_INSIGHT_MINUTE: Final[int] = 0

    # ==========================================================================
    # リアルタイムアラート
    # ==========================================================================

    # アラート間隔（同じタイプのアラートを連続で送らない最小間隔、分）
    ALERT_COOLDOWN_MINUTES: Final[int] = 60

    # 1日あたりの最大アラート数
    MAX_DAILY_ALERTS: Final[int] = 10


# =============================================================================
# 分析パラメータ
# =============================================================================


class AnalysisParameters:
    """
    分析に関するパラメータ
    """

    # ==========================================================================
    # 異常検知
    # ==========================================================================

    # 急激な変化の閾値（標準偏差の何倍）
    ANOMALY_THRESHOLD_SIGMA: Final[float] = 2.0

    # トレンド判定に必要な最小データポイント数
    MIN_DATA_POINTS_FOR_TREND: Final[int] = 5

    # ==========================================================================
    # タスク分析
    # ==========================================================================

    # 滞留と判定する日数
    TASK_STALE_DAYS: Final[int] = 3

    # タスク集中の閾値（平均の何倍）
    TASK_CONCENTRATION_RATIO: Final[float] = 2.0

    # ==========================================================================
    # コミュニケーション分析
    # ==========================================================================

    # メッセージトーン変化の検出期間（日）
    MESSAGE_TONE_WINDOW_DAYS: Final[int] = 7

    # トーン変化の閾値
    TONE_CHANGE_THRESHOLD: Final[float] = 0.3

    # ==========================================================================
    # 目標分析
    # ==========================================================================

    # 目標達成率の警告閾値
    GOAL_PROGRESS_WARNING_THRESHOLD: Final[float] = 0.5

    # 目標達成率の危険閾値
    GOAL_PROGRESS_DANGER_THRESHOLD: Final[float] = 0.3


# =============================================================================
# テンプレート定数
# =============================================================================


class FeedbackTemplates:
    """
    フィードバックメッセージのテンプレート
    """

    # デイリーダイジェストのヘッダー
    DAILY_DIGEST_HEADER: Final[str] = """━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 {date}（{weekday}）{name}さんへのフィードバック
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

    # ウィークリーレビューのヘッダー
    WEEKLY_REVIEW_HEADER: Final[str] = """━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📈 {week_start}〜{week_end} 週次レビュー
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

    # リアルタイムアラートのヘッダー
    ALERT_HEADER: Final[str] = """━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🚨 {name}さん、ちょっと気になることがあるウル
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

    # セクションの区切り
    SECTION_DIVIDER: Final[str] = "\n"

    # フッター
    FOOTER: Final[str] = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"


# =============================================================================
# Feature Flags
# =============================================================================


# フィードバック機能全体のフラグ
FEATURE_FLAG_NAME: Final[str] = "ENABLE_CEO_FEEDBACK"

# デイリーダイジェスト
FEATURE_FLAG_DAILY_DIGEST: Final[str] = "ENABLE_DAILY_DIGEST"

# ウィークリーレビュー
FEATURE_FLAG_WEEKLY_REVIEW: Final[str] = "ENABLE_WEEKLY_REVIEW"

# マンスリーインサイト
FEATURE_FLAG_MONTHLY_INSIGHT: Final[str] = "ENABLE_MONTHLY_INSIGHT"

# リアルタイムアラート
FEATURE_FLAG_REALTIME_ALERT: Final[str] = "ENABLE_REALTIME_ALERT"

# オンデマンド分析
FEATURE_FLAG_ON_DEMAND: Final[str] = "ENABLE_ON_DEMAND_ANALYSIS"


# =============================================================================
# アイコン定数
# =============================================================================


class FeedbackIcons:
    """
    フィードバックで使用するアイコン
    """

    # 優先度アイコン
    PRIORITY_CRITICAL: Final[str] = "🔴"
    PRIORITY_HIGH: Final[str] = "🟠"
    PRIORITY_MEDIUM: Final[str] = "🟡"
    PRIORITY_LOW: Final[str] = "🟢"

    # カテゴリアイコン
    TASK: Final[str] = "📋"
    GOAL: Final[str] = "🎯"
    COMMUNICATION: Final[str] = "💬"
    TEAM: Final[str] = "👥"
    RISK: Final[str] = "⚠️"
    POSITIVE: Final[str] = "✨"
    RECOMMENDATION: Final[str] = "💡"

    # トレンドアイコン
    TREND_UP: Final[str] = "📈"
    TREND_DOWN: Final[str] = "📉"
    TREND_STABLE: Final[str] = "➡️"

    # その他
    ALERT: Final[str] = "🚨"
    INFO: Final[str] = "ℹ️"
    SUCCESS: Final[str] = "✅"
    WARNING: Final[str] = "⚠️"
    TIME: Final[str] = "⏰"
    CALENDAR: Final[str] = "📅"
