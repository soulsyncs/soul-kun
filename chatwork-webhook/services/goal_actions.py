"""services/goal_actions.py - 目標管理アクションハンドラー

Phase 11-5c: main.pyから抽出された目標設定・進捗・レビューのアクションハンドラー。

依存: infra/db.py (get_pool)
"""

from infra.db import get_pool

from handlers.goal_handler import GoalHandler as _NewGoalHandler

try:
    from lib import (
        has_active_goal_session,
        process_goal_setting_message,
    )
    USE_GOAL_SETTING_LIB = True
except ImportError:
    USE_GOAL_SETTING_LIB = False
    process_goal_setting_message = None

_goal_handler = None



def _get_goal_handler():
    """GoalHandlerのシングルトンインスタンスを取得"""
    global _goal_handler
    if _goal_handler is None:
        _goal_handler = _NewGoalHandler(
            get_pool=get_pool,
            process_goal_setting_message_func=process_goal_setting_message if USE_GOAL_SETTING_LIB else None,
            use_goal_setting_lib=USE_GOAL_SETTING_LIB
        )
    return _goal_handler

def handle_goal_registration(params, room_id, account_id, sender_name, context=None):
    """
    目標登録ハンドラー（WHY→WHAT→HOWの対話形式）

    v10.24.6: handlers/goal_handler.py に移動済み
    """
    return _get_goal_handler().handle_goal_registration(params, room_id, account_id, sender_name, context)

def handle_goal_progress_report(params, room_id, account_id, sender_name, context=None):
    """
    目標進捗報告ハンドラー

    v10.24.6: handlers/goal_handler.py に移動済み
    """
    return _get_goal_handler().handle_goal_progress_report(params, room_id, account_id, sender_name, context)

def handle_goal_status_check(params, room_id, account_id, sender_name, context=None):
    """
    目標確認ハンドラー

    v10.24.6: handlers/goal_handler.py に移動済み
    """
    return _get_goal_handler().handle_goal_status_check(params, room_id, account_id, sender_name, context)

def handle_goal_review(params, room_id, account_id, sender_name, context=None):
    """
    目標一覧・整理ハンドラー

    v10.44.0: handlers/goal_handler.py に移動済み
    """
    return _get_goal_handler().handle_goal_review(params, room_id, account_id, sender_name, context)

def handle_goal_consult(params, room_id, account_id, sender_name, context=None):
    """
    目標相談ハンドラー

    v10.44.0: handlers/goal_handler.py に移動済み
    """
    return _get_goal_handler().handle_goal_consult(params, room_id, account_id, sender_name, context)

def handle_goal_delete(params, room_id, account_id, sender_name, context=None):
    """
    目標削除ハンドラー

    v10.56.2: handlers/goal_handler.py に移動済み
    設計書: docs/05_phase2-5_goal_achievement.md セクション5.6.1
    """
    return _get_goal_handler().handle_goal_delete(params, room_id, account_id, sender_name, context)

def handle_goal_cleanup(params, room_id, account_id, sender_name, context=None):
    """
    目標整理ハンドラー

    v10.56.2: handlers/goal_handler.py に移動済み
    設計書: docs/05_phase2-5_goal_achievement.md セクション5.6.2
    """
    return _get_goal_handler().handle_goal_cleanup(params, room_id, account_id, sender_name, context)
