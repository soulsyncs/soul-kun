"""
sync-chatwork-tasks/lib - Cloud Functions用ローカルライブラリ

このディレクトリにはデプロイ時にsoul-kun/lib/からコピーされた
モジュールが配置されます。

注意: ルートlib/__init__.pyとは異なる最小限のインポート。
chatwork.py, tenant.py等はこのCloud Functionでは不要。
"""

# text_utils
from lib.text_utils import (
    GREETING_PATTERNS,
    CLOSING_PATTERNS,
    remove_greetings,
    extract_task_subject,
    is_greeting_only,
    validate_summary,
    validate_and_get_reason,
    prepare_task_display_text,
    clean_chatwork_tags,
)

# audit
from lib.audit import (
    log_audit,
    log_audit_batch,
)

# user_utils
from lib.user_utils import (
    get_user_primary_department,
)
