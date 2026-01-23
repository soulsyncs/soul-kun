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
