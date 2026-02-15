"""
remind-tasks/lib - Cloud Functions用ローカルライブラリ

このディレクトリにはデプロイ時にsoul-kun/lib/からコピーされた
モジュールが配置されます。

注意: ルートlib/__init__.pyとは異なる最小限のインポート。
chatwork.py, tenant.py等はこのCloud Functionでは不要。
"""

# text_utils（remind-tasks/main.pyが from lib import で使用）
from lib.text_utils import (
    clean_chatwork_tags,
    prepare_task_display_text,
    remove_greetings,
    validate_summary,
    extract_task_subject,
)

# user_utils
from lib.user_utils import (
    get_user_primary_department,
)
