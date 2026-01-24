"""
check-reply-messages/lib - Cloud Functions用ローカルライブラリ

このディレクトリにはデプロイ時にsoul-kun/lib/からコピーされた
モジュールが配置されます。

v10.18.1: 新規追加（summary生成、department_id対応）
"""

# text_utils（summary生成用）
from .text_utils import (
    clean_chatwork_tags,
    prepare_task_display_text,
    remove_greetings,
    validate_summary,
    extract_task_subject,
)

# user_utils（Phase 3.5対応）
from .user_utils import (
    get_user_primary_department,
    get_user_by_chatwork_id,
)

# audit（監査ログ）
from .audit import (
    AuditAction,
    AuditResourceType,
    log_audit,
    log_audit_batch,
)
