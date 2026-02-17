"""
目標設定対話フロー管理モジュール（Phase 2.5 v1.8 - 神経接続修理版）

アチーブメント社・選択理論に基づく目標設定対話を管理。
WHY → WHAT → HOW の順で一問一答形式で目標を設定する。

使用例:
    from lib.goal_setting import GoalSettingDialogue

    dialogue = GoalSettingDialogue(pool, room_id, account_id)
    response = dialogue.process_message(user_message)
"""

# Constants - re-export for backward compatibility
from .constants import (
    OPENROUTER_API_KEY,
    LLM_MODEL,
    LLM_TIMEOUT,
    LONG_RESPONSE_THRESHOLD,
    FRUSTRATION_PATTERNS,
    CONFIRMATION_PATTERNS,
    BUT_CONNECTOR_PATTERNS,
    FEEDBACK_REQUEST_PATTERNS,
    DOUBT_ANXIETY_PATTERNS,
    RESTART_PATTERNS,
    WHY_FULFILLED_PATTERNS,
    WHAT_FULFILLED_PATTERNS,
    HOW_FULFILLED_PATTERNS,
    STEPS,
    STEP_ORDER,
    MAX_RETRY_COUNT,
    TEMPLATES,
    PATTERN_KEYWORDS,
    LENGTH_THRESHOLDS,
    STEP_EXPECTED_KEYWORDS,
)

# Detectors - re-export for backward compatibility
from .detectors import (
    _wants_restart,
    _has_but_connector,
    _has_feedback_request,
    _has_doubt_or_anxiety,
    _is_pure_confirmation,
    _infer_fulfilled_phases,
    _get_next_unfulfilled_step,
)

# Dialogue - re-export for backward compatibility
from .dialogue import (
    GoalSettingDialogue,
    has_active_goal_session,
    process_goal_setting_message,
)

# Analysis - re-export for backward compatibility
from .analysis import (
    GoalSettingUserPatternAnalyzer,
    GoalHistoryProvider,
)

__all__ = [
    # Constants
    "OPENROUTER_API_KEY",
    "LLM_MODEL",
    "LLM_TIMEOUT",
    "LONG_RESPONSE_THRESHOLD",
    "FRUSTRATION_PATTERNS",
    "CONFIRMATION_PATTERNS",
    "BUT_CONNECTOR_PATTERNS",
    "FEEDBACK_REQUEST_PATTERNS",
    "DOUBT_ANXIETY_PATTERNS",
    "RESTART_PATTERNS",
    "WHY_FULFILLED_PATTERNS",
    "WHAT_FULFILLED_PATTERNS",
    "HOW_FULFILLED_PATTERNS",
    "STEPS",
    "STEP_ORDER",
    "MAX_RETRY_COUNT",
    "TEMPLATES",
    "PATTERN_KEYWORDS",
    "LENGTH_THRESHOLDS",
    "STEP_EXPECTED_KEYWORDS",
    # Detectors
    "_wants_restart",
    "_has_but_connector",
    "_has_feedback_request",
    "_has_doubt_or_anxiety",
    "_is_pure_confirmation",
    "_infer_fulfilled_phases",
    "_get_next_unfulfilled_step",
    # Dialogue
    "GoalSettingDialogue",
    "has_active_goal_session",
    "process_goal_setting_message",
    # Analysis
    "GoalSettingUserPatternAnalyzer",
    "GoalHistoryProvider",
]
