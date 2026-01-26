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

# v10.30.1: Phase A 管理者設定のDB化
from .admin_config import (
    # データクラス
    AdminConfig,
    # メイン関数
    get_admin_config,
    # ショートカット関数
    is_admin_account,
    get_admin_room_id,
    get_admin_account_id,
    # キャッシュ操作
    clear_admin_config_cache,
    # 定数
    DEFAULT_ORG_ID,
    DEFAULT_ADMIN_ACCOUNT_ID,
    DEFAULT_ADMIN_ROOM_ID,
    DEFAULT_ADMIN_DM_ROOM_ID,
    DEFAULT_BOT_ACCOUNT_ID,
    # 後方互換性エイリアス
    ADMIN_ACCOUNT_ID,
    ADMIN_ROOM_ID,
    KAZU_CHATWORK_ACCOUNT_ID,
    KAZU_ACCOUNT_ID,
)

# v10.31.1: Phase D 接続設定集約
from .config import get_settings, Settings, settings
from .secrets import get_secret, get_secret_cached
from .db import (
    get_db_pool,
    get_db_connection,
    get_db_session,
    close_all_connections,
    health_check,
)
