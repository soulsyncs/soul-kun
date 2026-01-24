"""
chatwork-webhook/lib - Cloud Functions用ローカルライブラリ

このディレクトリにはデプロイ時にsoul-kun/lib/からコピーされた
モジュールが配置されます。

v10.18.1: 新規追加（summary生成対応）
"""
from .text_utils import (
    # パターン定義
    GREETING_PATTERNS,
    CLOSING_PATTERNS,
    GREETING_STARTS,
    TRUNCATION_INDICATORS,
    # 関数
    clean_chatwork_tags,
    prepare_task_display_text,
    remove_greetings,
    extract_task_subject,
    is_greeting_only,
    validate_summary,
    validate_and_get_reason,
)

from .audit import (
    AuditAction,
    AuditResourceType,
    log_audit,
    log_audit_batch,
)

# v10.18.1: user_utils追加（Phase 3.5対応）
from .user_utils import (
    get_user_primary_department,
)

# v10.19.0: goal_setting追加（Phase 2.5目標設定対話フロー）
from .goal_setting import (
    # 定数
    STEPS as GOAL_SETTING_STEPS,
    STEP_ORDER as GOAL_SETTING_STEP_ORDER,
    MAX_RETRY_COUNT as GOAL_SETTING_MAX_RETRY,
    TEMPLATES as GOAL_SETTING_TEMPLATES,
    PATTERN_KEYWORDS as GOAL_SETTING_PATTERN_KEYWORDS,
    # クラス
    GoalSettingDialogue,
    # ヘルパー関数
    has_active_goal_session,
    process_goal_setting_message,
)
