"""
Phase 2 進化版 A1: パターン検出 - 定数定義

このモジュールは、検出基盤（Detection Framework）で使用する
定数を一元管理します。

設計書: docs/06_phase2_a1_pattern_detection.md

Author: Claude Code（経営参謀・SE・PM）
Created: 2026-01-23
Version: 1.0
"""

from enum import Enum
from typing import Final


# ================================================================
# 検出パラメータ
# ================================================================

class DetectionParameters:
    """
    検出処理で使用するパラメータの定数クラス

    これらの値は環境変数で上書き可能にする予定（Phase 2 A1 v1.1）
    """

    # ================================================================
    # A1パターン検出パラメータ
    # ================================================================

    # パターン検出の閾値
    # この回数以上出現したパターンをインサイトとして登録
    PATTERN_THRESHOLD: Final[int] = 5

    # パターン検出の対象期間（日数）
    # この期間内の質問を分析対象とする
    PATTERN_WINDOW_DAYS: Final[int] = 30

    # 保存するサンプル質問の最大数
    # パターンの具体例として管理者に表示
    MAX_SAMPLE_QUESTIONS: Final[int] = 5

    # occurrence_timestampsの最大保持件数
    # 高頻度質問での配列肥大化を防止（Codex LOW指摘対応）
    # 30日間ウィンドウで1日10件を想定し、余裕を持たせた値
    MAX_OCCURRENCE_TIMESTAMPS: Final[int] = 500

    # 類似度の閾値（0.0-1.0）
    # この値以上の類似度を持つ質問を同一パターンとして認識
    # 注意: 現在はハッシュベースなので未使用（将来Embedding導入時に使用）
    SIMILARITY_THRESHOLD: Final[float] = 0.85

    # 週次レポート送信曜日（0=月曜, 6=日曜）
    WEEKLY_REPORT_DAY: Final[int] = 0  # 月曜日

    # 週次レポート送信時刻（時:分）
    WEEKLY_REPORT_HOUR: Final[int] = 9
    WEEKLY_REPORT_MINUTE: Final[int] = 0

    # ================================================================
    # A2属人化検出パラメータ
    # ================================================================

    # 属人化判定の偏り閾値（80%以上の回答が1人に集中）
    PERSONALIZATION_THRESHOLD: Final[float] = 0.8

    # 属人化検出に必要な最小回答数
    MIN_RESPONSES_FOR_PERSONALIZATION: Final[int] = 5

    # 属人化検出の分析対象期間（日数）
    PERSONALIZATION_WINDOW_DAYS: Final[int] = 30

    # 高リスク判定の連続検出日数
    HIGH_RISK_EXCLUSIVE_DAYS: Final[int] = 14

    # 緊急リスク判定の連続検出日数
    CRITICAL_RISK_EXCLUSIVE_DAYS: Final[int] = 30

    # ================================================================
    # A3ボトルネック検出パラメータ
    # ================================================================

    # 緊急レベルの期限超過日数
    OVERDUE_CRITICAL_DAYS: Final[int] = 7

    # 高リスクレベルの期限超過日数
    OVERDUE_HIGH_DAYS: Final[int] = 3

    # 中リスクレベルの期限超過日数
    OVERDUE_MEDIUM_DAYS: Final[int] = 1

    # 長期未完了と判定する日数
    STALE_TASK_DAYS: Final[int] = 7

    # タスク集中アラートの閾値
    TASK_CONCENTRATION_THRESHOLD: Final[int] = 10

    # 平均の何倍で集中と判定
    CONCENTRATION_RATIO_THRESHOLD: Final[float] = 2.0


# ================================================================
# 質問カテゴリ
# ================================================================

class QuestionCategory(str, Enum):
    """
    質問のカテゴリ分類

    LLMまたはキーワードベースで分類される
    """

    # 業務手続き（週報、経費精算、申請等）
    BUSINESS_PROCESS = "business_process"

    # 社内ルール（有給、服装規定、就業規則等）
    COMPANY_RULE = "company_rule"

    # 技術質問（Slack、VPN、パスワード等）
    TECHNICAL = "technical"

    # 人事関連（評価、昇給、異動等）
    HR_RELATED = "hr_related"

    # プロジェクト関連（進捗、納期等）
    PROJECT = "project"

    # その他（分類不能）
    OTHER = "other"

    @classmethod
    def from_string(cls, value: str) -> "QuestionCategory":
        """
        文字列からカテゴリを取得

        Args:
            value: カテゴリ文字列

        Returns:
            QuestionCategory: 対応するカテゴリ

        Raises:
            ValueError: 不明なカテゴリの場合
        """
        try:
            return cls(value.lower())
        except ValueError:
            return cls.OTHER


# ================================================================
# カテゴリ分類用キーワード
# ================================================================

# カテゴリごとのキーワードリスト
# LLM分類が利用できない場合のフォールバック
CATEGORY_KEYWORDS: Final[dict[QuestionCategory, list[str]]] = {
    QuestionCategory.BUSINESS_PROCESS: [
        "週報", "経費", "精算", "申請", "承認", "ワークフロー",
        "報告", "提出", "書き方", "フォーマット", "テンプレート",
    ],
    QuestionCategory.COMPANY_RULE: [
        "有給", "休暇", "服装", "ルール", "規定", "就業",
        "勤怠", "出勤", "退勤", "残業", "福利厚生",
    ],
    QuestionCategory.TECHNICAL: [
        "slack", "vpn", "パスワード", "ログイン", "システム",
        "接続", "エラー", "設定", "インストール", "アプリ",
    ],
    QuestionCategory.HR_RELATED: [
        "評価", "昇給", "人事", "異動", "面談",
        "昇進", "給与", "ボーナス", "賞与", "査定",
    ],
    QuestionCategory.PROJECT: [
        "プロジェクト", "案件", "進捗", "納期", "スケジュール",
        "マイルストーン", "リリース", "クライアント",
    ],
}


# ================================================================
# パターンステータス
# ================================================================

class PatternStatus(str, Enum):
    """
    質問パターンのステータス
    """

    # 検出中（デフォルト）
    ACTIVE = "active"

    # 対応済み（ナレッジ化等）
    ADDRESSED = "addressed"

    # 無視（重要でないと判断）
    DISMISSED = "dismissed"


# ================================================================
# インサイトタイプ
# ================================================================

class InsightType(str, Enum):
    """
    ソウルくんの気づきの種類
    """

    # 頻出パターンを検出
    PATTERN_DETECTED = "pattern_detected"

    # 属人化リスクを検出（A2で使用予定）
    PERSONALIZATION_RISK = "personalization_risk"

    # ボトルネックを検出（A3で使用予定）
    BOTTLENECK = "bottleneck"

    # 感情変化を検出（A4で使用予定）
    EMOTION_CHANGE = "emotion_change"


# ================================================================
# ソースタイプ
# ================================================================

class SourceType(str, Enum):
    """
    インサイトのソース（検出元）
    """

    # A1パターン検出
    A1_PATTERN = "a1_pattern"

    # A2属人化検出（将来）
    A2_PERSONALIZATION = "a2_personalization"

    # A3ボトルネック検出（将来）
    A3_BOTTLENECK = "a3_bottleneck"

    # A4感情変化検出（将来）
    A4_EMOTION = "a4_emotion"


# ================================================================
# 重要度
# ================================================================

class Importance(str, Enum):
    """
    インサイトの重要度

    通知タイミング:
    - critical/high: 即時通知（検出から1時間以内）
    - medium/low: 週次レポート
    """

    # 即時対応必要（経営に影響）
    CRITICAL = "critical"

    # 早急に対応（業務に支障）
    HIGH = "high"

    # 計画的に対応
    MEDIUM = "medium"

    # 時間があれば対応
    LOW = "low"

    @classmethod
    def from_occurrence_count(
        cls,
        occurrence_count: int,
        unique_users: int
    ) -> "Importance":
        """
        発生回数とユニークユーザー数から重要度を判定

        Args:
            occurrence_count: 発生回数
            unique_users: ユニークユーザー数

        Returns:
            Importance: 判定された重要度
        """
        if occurrence_count >= 20 or unique_users >= 10:
            return cls.CRITICAL
        elif occurrence_count >= 10 or unique_users >= 5:
            return cls.HIGH
        elif occurrence_count >= 5:
            return cls.MEDIUM
        else:
            return cls.LOW


# ================================================================
# インサイトステータス
# ================================================================

class InsightStatus(str, Enum):
    """
    インサイトのステータス
    """

    # 新規（未確認）
    NEW = "new"

    # 確認済み（対応検討中）
    ACKNOWLEDGED = "acknowledged"

    # 対応完了
    ADDRESSED = "addressed"

    # 無視（対応不要と判断）
    DISMISSED = "dismissed"


# ================================================================
# 週次レポートステータス
# ================================================================

class WeeklyReportStatus(str, Enum):
    """
    週次レポートのステータス
    """

    # 下書き（生成済み、未送信）
    DRAFT = "draft"

    # 送信完了
    SENT = "sent"

    # 送信失敗
    FAILED = "failed"


# ================================================================
# 機密区分
# ================================================================

class Classification(str, Enum):
    """
    機密区分（4段階）

    CLAUDE.mdの鉄則: 4段階の機密区分を必ず設定
    """

    # 公開情報
    PUBLIC = "public"

    # 社内限定（デフォルト）
    INTERNAL = "internal"

    # 機密
    CONFIDENTIAL = "confidential"

    # 極秘
    RESTRICTED = "restricted"


# ================================================================
# 通知タイプ（notification_logs用）
# ================================================================

class NotificationType(str, Enum):
    """
    通知タイプ（notification_logsのnotification_type）
    """

    # A1パターン検出: 頻出パターン検出アラート
    PATTERN_ALERT = "pattern_alert"

    # A1パターン検出: 週次レポート
    WEEKLY_REPORT = "weekly_report"

    # A2属人化検出: 属人化アラート
    PERSONALIZATION_ALERT = "personalization_alert"

    # A3ボトルネック検出: ボトルネックアラート
    BOTTLENECK_ALERT = "bottleneck_alert"


# ================================================================
# A2属人化検出: リスクレベル
# ================================================================

class PersonalizationRiskLevel(str, Enum):
    """
    属人化リスクのレベル

    設計書: docs/07_phase2_a2_personalization_detection.md
    """

    # 緊急: 完全独占 + 30日以上継続
    CRITICAL = "critical"

    # 高リスク: 80%以上 + 14日以上継続
    HIGH = "high"

    # 中リスク: 60%以上 + 7日以上継続
    MEDIUM = "medium"

    # 低リスク: 監視継続
    LOW = "low"


# ================================================================
# A2属人化検出: ステータス
# ================================================================

class PersonalizationStatus(str, Enum):
    """
    属人化リスクの対応ステータス
    """

    # アクティブ（検出中）
    ACTIVE = "active"

    # 対応済み（ナレッジ化等）
    MITIGATED = "mitigated"

    # 無視（対応不要と判断）
    DISMISSED = "dismissed"


# ================================================================
# A3ボトルネック検出: ボトルネックタイプ
# ================================================================

class BottleneckType(str, Enum):
    """
    ボトルネックの種類

    設計書: docs/08_phase2_a3_bottleneck_detection.md
    """

    # 期限超過タスク
    OVERDUE_TASK = "overdue_task"

    # 長期未完了タスク
    STALE_TASK = "stale_task"

    # タスク集中
    TASK_CONCENTRATION = "task_concentration"

    # 担当者未設定
    NO_ASSIGNEE = "no_assignee"


# ================================================================
# A3ボトルネック検出: リスクレベル
# ================================================================

class BottleneckRiskLevel(str, Enum):
    """
    ボトルネックのリスクレベル

    設計書: docs/08_phase2_a3_bottleneck_detection.md
    """

    # 緊急: 期限7日超過 / タスク20件以上集中
    CRITICAL = "critical"

    # 高リスク: 期限3日超過 / タスク15件以上集中
    HIGH = "high"

    # 中リスク: 期限1日超過 / タスク10件以上集中
    MEDIUM = "medium"

    # 低リスク: 長期未完了
    LOW = "low"


# ================================================================
# A3ボトルネック検出: ステータス
# ================================================================

class BottleneckStatus(str, Enum):
    """
    ボトルネックアラートの対応ステータス
    """

    # アクティブ（検出中）
    ACTIVE = "active"

    # 解決済み
    RESOLVED = "resolved"

    # 無視（対応不要と判断）
    DISMISSED = "dismissed"


# ================================================================
# 冪等性キーのプレフィックス
# ================================================================

class IdempotencyKeyPrefix(str, Enum):
    """
    冪等性キーのプレフィックス

    notification_logsのtarget_idに使用
    形式: {prefix}:{id}:{organization_id}
    """

    # パターンアラート
    PATTERN_ALERT = "pattern_alert"

    # 週次レポート
    WEEKLY_REPORT = "weekly_report"


# ================================================================
# エラーコード
# ================================================================

class ErrorCode(str, Enum):
    """
    検出処理のエラーコード
    """

    # 検出処理エラー
    DETECTION_ERROR = "DETECTION_ERROR"

    # パターン保存エラー
    PATTERN_SAVE_ERROR = "PATTERN_SAVE_ERROR"

    # インサイト作成エラー
    INSIGHT_CREATE_ERROR = "INSIGHT_CREATE_ERROR"

    # 通知送信エラー
    NOTIFICATION_ERROR = "NOTIFICATION_ERROR"

    # データベースエラー
    DATABASE_ERROR = "DATABASE_ERROR"

    # バリデーションエラー
    VALIDATION_ERROR = "VALIDATION_ERROR"

    # 認証エラー
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"

    # 認可エラー
    AUTHORIZATION_ERROR = "AUTHORIZATION_ERROR"


# ================================================================
# ログメッセージテンプレート
# ================================================================

class LogMessages:
    """
    構造化ログのメッセージテンプレート
    """

    # 検出処理
    DETECTION_STARTED = "Pattern detection started"
    DETECTION_COMPLETED = "Pattern detection completed"
    DETECTION_FAILED = "Pattern detection failed"

    # パターン操作
    PATTERN_CREATED = "New question pattern created"
    PATTERN_UPDATED = "Question pattern updated"
    PATTERN_THRESHOLD_REACHED = "Pattern threshold reached, creating insight"

    # インサイト操作
    INSIGHT_CREATED = "New insight created"
    INSIGHT_UPDATED = "Insight updated"
    INSIGHT_NOTIFIED = "Insight notification sent"

    # 週次レポート
    WEEKLY_REPORT_GENERATED = "Weekly report generated"
    WEEKLY_REPORT_SENT = "Weekly report sent"
    WEEKLY_REPORT_FAILED = "Weekly report send failed"
