"""
Phase 2F: 結果からの学習 - 定数定義

設計書: docs/17_brain_completion_roadmap.md セクション Phase 2F
"""

from enum import Enum
from typing import Dict, Set


# ============================================================================
# イベントタイプ
# ============================================================================

class EventType(str, Enum):
    """追跡対象イベントのタイプ"""
    NOTIFICATION_SENT = "notification_sent"       # 通知送信
    TASK_REMINDER = "task_reminder"               # タスクリマインド
    GOAL_REMINDER = "goal_reminder"               # 目標リマインド
    SUGGESTION_MADE = "suggestion_made"           # 提案
    PROACTIVE_MESSAGE = "proactive_message"       # 能動的メッセージ
    ANNOUNCEMENT = "announcement"                 # アナウンス
    DAILY_CHECK = "daily_check"                   # 日次チェック
    FOLLOW_UP = "follow_up"                       # フォローアップ


# イベントタイプと対応するアクション名のマッピング
EVENT_TYPE_ACTION_MAP: Dict[str, EventType] = {
    "send_notification": EventType.NOTIFICATION_SENT,
    "send_reminder": EventType.TASK_REMINDER,
    "send_announcement": EventType.ANNOUNCEMENT,
    "suggest_task": EventType.SUGGESTION_MADE,
    "suggest_goal": EventType.SUGGESTION_MADE,
    "goal_reminder_sent": EventType.GOAL_REMINDER,
    "goal_progress_prompt": EventType.DAILY_CHECK,
    "task_reminder_sent": EventType.TASK_REMINDER,
    "proactive_check_in": EventType.PROACTIVE_MESSAGE,
    "proactive_follow_up": EventType.FOLLOW_UP,
}


# ============================================================================
# 結果タイプ
# ============================================================================

class OutcomeType(str, Enum):
    """検出された結果のタイプ"""
    ADOPTED = "adopted"       # 提案が採用された
    IGNORED = "ignored"       # 無視された（反応なし）
    REJECTED = "rejected"     # 明確に拒否された
    DELAYED = "delayed"       # 遅れて対応された
    PARTIAL = "partial"       # 部分的に採用された
    PENDING = "pending"       # まだ結果未確定


# ============================================================================
# フィードバック信号
# ============================================================================

class FeedbackSignal(str, Enum):
    """暗黙のフィードバック信号"""
    # ポジティブ信号
    TASK_COMPLETED = "task_completed"           # タスクが完了した
    GOAL_PROGRESS_MADE = "goal_progress_made"   # 目標進捗が記録された
    REPLY_RECEIVED = "reply_received"           # 返信があった
    ACTION_TAKEN = "action_taken"               # アクションが実行された

    # ネガティブ信号
    NO_RESPONSE = "no_response"                 # 反応なし
    TASK_OVERDUE = "task_overdue"               # タスク期限切れ
    GOAL_STALLED = "goal_stalled"               # 目標停滞
    MESSAGE_DELETED = "message_deleted"         # メッセージ削除（将来実装）

    # 中立信号
    READ_BUT_NO_ACTION = "read_but_no_action"   # 既読だがアクションなし


# ============================================================================
# パターンタイプ
# ============================================================================

class PatternType(str, Enum):
    """抽出されるパターンのタイプ"""
    TIMING = "timing"                           # 効果的な時間帯
    COMMUNICATION_STYLE = "communication_style" # 効果的な言い回し
    TASK_TYPE = "task_type"                     # タスクタイプ別傾向
    USER_PREFERENCE = "user_preference"         # ユーザー固有の好み
    SEASONAL = "seasonal"                       # 季節・周期的パターン
    DAY_OF_WEEK = "day_of_week"                 # 曜日別パターン
    RESPONSE_TIME = "response_time"             # 反応時間パターン


# ============================================================================
# パターンスコープ
# ============================================================================

class PatternScope(str, Enum):
    """パターンの適用スコープ"""
    GLOBAL = "global"       # 全ユーザーに適用
    USER = "user"           # 特定ユーザーのみ
    ROOM = "room"           # 特定ルームのみ
    DEPARTMENT = "department"  # 特定部署のみ


# ============================================================================
# 検出閾値（時間）
# ============================================================================

# 採用判定の閾値（時間）
ADOPTED_THRESHOLD_HOURS: int = 4

# 遅延対応判定の閾値（時間）
DELAYED_THRESHOLD_HOURS: int = 24

# 無視判定の閾値（時間）
IGNORED_THRESHOLD_HOURS: int = 48

# 結果検出のチェック対象期間（時間）
OUTCOME_CHECK_MAX_AGE_HOURS: int = 72

# 目標リマインド後の反応期待日数
GOAL_RESPONSE_EXPECTED_DAYS: int = 1

# 連続無反応で無視判定とする日数
NO_RESPONSE_THRESHOLD_DAYS: int = 3


# ============================================================================
# パターン抽出閾値
# ============================================================================

# パターン抽出に必要な最小サンプル数
MIN_SAMPLE_COUNT: int = 10

# パターン有効とみなす最小成功率
MIN_SUCCESS_RATE: float = 0.6

# パターンの最小確信度
MIN_CONFIDENCE_SCORE: float = 0.5

# 学習への昇格に必要な確信度
PROMOTION_CONFIDENCE_THRESHOLD: float = 0.7

# 学習への昇格に必要な最小サンプル数
PROMOTION_MIN_SAMPLE_COUNT: int = 20


# ============================================================================
# 時間帯定義
# ============================================================================

# 時間帯の区分
TIME_SLOTS: Dict[str, Dict[str, int]] = {
    "early_morning": {"start": 6, "end": 9},
    "morning": {"start": 9, "end": 12},
    "afternoon": {"start": 12, "end": 15},
    "late_afternoon": {"start": 15, "end": 18},
    "evening": {"start": 18, "end": 21},
    "night": {"start": 21, "end": 24},
}

# 曜日名
DAY_OF_WEEK_NAMES: Dict[int, str] = {
    0: "monday",
    1: "tuesday",
    2: "wednesday",
    3: "thursday",
    4: "friday",
    5: "saturday",
    6: "sunday",
}


# ============================================================================
# データ保持期間
# ============================================================================

# イベントデータの保持期間（日）
OUTCOME_EVENT_RETENTION_DAYS: int = 365

# パターンの有効期間（日）- 更新がなければ非アクティブに
PATTERN_STALENESS_DAYS: int = 90


# ============================================================================
# DB関連定数
# ============================================================================

# テーブル名
TABLE_BRAIN_OUTCOME_EVENTS = "brain_outcome_events"
TABLE_BRAIN_OUTCOME_PATTERNS = "brain_outcome_patterns"

# 最大取得件数
MAX_EVENTS_PER_QUERY: int = 500
MAX_PATTERNS_PER_QUERY: int = 100


# ============================================================================
# 追跡対象アクション
# ============================================================================

TRACKABLE_ACTIONS: Set[str] = {
    # 通知系
    "send_notification",
    "send_reminder",
    "send_announcement",

    # 提案系
    "suggest_task",
    "suggest_goal",

    # 目標系
    "goal_reminder_sent",
    "goal_progress_prompt",

    # タスク系
    "task_reminder_sent",

    # プロアクティブ系
    "proactive_check_in",
    "proactive_follow_up",
}


# ============================================================================
# ログメッセージ
# ============================================================================

LOG_MESSAGES = {
    "event_recorded": "Outcome event recorded: {event_type} for {account_id}",
    "outcome_detected": "Outcome detected: {outcome_type} for event {event_id}",
    "pattern_extracted": "Pattern extracted: {pattern_type} with confidence {confidence}",
    "pattern_promoted": "Pattern promoted to learning: {pattern_id} -> {learning_id}",
}
