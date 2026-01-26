"""
check-reply-messages/lib - Cloud Functions用ローカルライブラリ

このディレクトリにはデプロイ時にsoul-kun/lib/からコピーされた
モジュールが配置されます。

v10.18.1: text_utils、user_utils追加
v10.31.1: Phase D - db, config, secrets追加（接続設定集約）
"""

# =============================================================================
# Phase D: 接続設定集約（v10.31.1）
# =============================================================================
from .config import get_settings, Settings, settings
from .secrets import get_secret, get_secret_cached
from .db import (
    get_db_pool,
    get_db_connection,
    get_db_session,
    close_all_connections,
    health_check,
)

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

from .user_utils import (
    get_user_primary_department,
)
