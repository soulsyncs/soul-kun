# lib/brain/handler_wrappers/__init__.py
"""
脳用ハンドラーラッパー関数パッケージ

v10.40: main.py から抽出
設計原則「全入力は脳を通る」に準拠

このパッケージは、Brainの意図理解・判断結果を
実際のハンドラー関数に橋渡しするラッパー関数を提供します。

【設計思想】
- 各ラッパーはasync関数として定義（Brainのasync処理に対応）
- ハンドラー呼び出し時のエラーハンドリングを統一
- HandlerResultを返して、成功/失敗を明確に
- 循環参照を避けるため、main.py関数は遅延インポート

【使用方法】
from lib.brain.handler_wrappers import (
    build_brain_handlers,
    build_bypass_handlers,
    build_session_handlers,
)

# ハンドラー辞書を構築
handlers = build_brain_handlers(main_module_functions)
"""

# common
from .common import _extract_handler_result

# bypass handlers
from .bypass_handlers import (
    _bypass_handle_announcement,
    _bypass_handle_meeting_audio,
    _bypass_handle_task_pending,
    build_bypass_handlers,
)

# memory handlers
from .memory_handlers import (
    _handle_save_long_term_memory,
    _handle_save_bot_persona,
    _handle_query_long_term_memory,
)

# session handlers
from .session_handlers import (
    _interrupted_goal_sessions,
    _brain_continue_goal_setting,
    _brain_continue_announcement,
    _brain_continue_task_pending,
    _brain_continue_list_context,
    _brain_interrupt_goal_setting,
    _brain_get_interrupted_goal_setting,
    _brain_resume_goal_setting,
    build_session_handlers,
    get_session_management_functions,
)

# brain tool handlers
from .brain_tool_handlers import (
    _brain_handle_task_search,
    _brain_handle_task_create,
    _brain_handle_task_complete,
    _brain_handle_query_knowledge,
    _brain_handle_save_memory,
    _brain_handle_query_memory,
    _brain_handle_delete_memory,
    _brain_handle_learn_knowledge,
    _brain_handle_forget_knowledge,
    _brain_handle_list_knowledge,
    _brain_handle_goal_setting_start,
    _brain_handle_goal_progress_report,
    _brain_handle_goal_status_check,
    _brain_handle_goal_review,
    _brain_handle_goal_consult,
    _brain_handle_goal_delete,
    _brain_handle_goal_cleanup,
    _brain_handle_announcement_create,
    _brain_handle_query_org_chart,
    _brain_handle_daily_reflection,
    _brain_handle_proposal_decision,
    _brain_handle_api_limitation,
    _brain_handle_general_conversation,
    build_brain_handlers,
)

# external tool handlers
from .external_tool_handlers import (
    _brain_handle_web_search,
    _brain_handle_calendar_read,
    _brain_handle_drive_search,
    _brain_handle_data_aggregate,
    _brain_handle_data_search,
    _brain_handle_report_generate,
    _brain_handle_csv_export,
    _brain_handle_file_create,
)

# polling
from .polling import (
    validate_polling_message,
    should_skip_polling_message,
    process_polling_message,
    process_polling_room,
)


__all__ = [
    # ビルダー関数
    "build_bypass_handlers",
    "build_brain_handlers",
    "build_session_handlers",
    "get_session_management_functions",
    # 個別ハンドラー（直接アクセス用）
    "_brain_handle_task_search",
    "_brain_handle_task_create",
    "_brain_handle_task_complete",
    "_brain_handle_query_knowledge",
    "_brain_handle_save_memory",
    "_brain_handle_query_memory",
    "_brain_handle_delete_memory",
    "_brain_handle_learn_knowledge",
    "_brain_handle_forget_knowledge",
    "_brain_handle_list_knowledge",
    "_brain_handle_goal_setting_start",
    "_brain_handle_goal_progress_report",
    "_brain_handle_goal_status_check",
    "_brain_handle_goal_review",
    "_brain_handle_goal_consult",
    "_brain_handle_goal_delete",  # v10.56.2: 目標削除
    "_brain_handle_goal_cleanup",  # v10.56.2: 目標整理
    "_brain_handle_announcement_create",
    "_brain_handle_query_org_chart",
    "_brain_handle_daily_reflection",
    "_brain_handle_proposal_decision",
    "_brain_handle_api_limitation",
    "_brain_handle_general_conversation",
    # 外部ツールハンドラー
    "_brain_handle_web_search",
    "_brain_handle_calendar_read",
    "_brain_handle_drive_search",
    "_brain_handle_data_aggregate",
    "_brain_handle_data_search",
    "_brain_handle_report_generate",
    "_brain_handle_csv_export",
    "_brain_handle_file_create",
    # セッション継続ハンドラー
    "_brain_continue_goal_setting",
    "_brain_continue_announcement",
    "_brain_continue_task_pending",
    "_brain_continue_list_context",  # v10.56.2: 一覧表示後
    # セッション管理
    "_brain_interrupt_goal_setting",
    "_brain_get_interrupted_goal_setting",
    "_brain_resume_goal_setting",
    # ヘルパー
    "_handle_save_long_term_memory",
    "_handle_save_bot_persona",
    "_handle_query_long_term_memory",
    # v10.40.3: ポーリング処理
    "validate_polling_message",
    "should_skip_polling_message",
    "process_polling_message",
    "process_polling_room",
]
