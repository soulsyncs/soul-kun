# lib/brain/handler_wrappers/brain_tool_handlers.py
"""
脳用ハンドラーラッパー関数

v10.28.0: BrainIntegrationから呼び出される
タスク検索・作成・完了、ナレッジ、記憶、目標、アナウンス、組織図等のハンドラー。
"""

import re
import logging
import os
from typing import Dict, Any, Callable

from lib.brain.models import HandlerResult
from .common import _extract_handler_result
from .memory_handlers import (
    _handle_save_long_term_memory,
    _handle_save_bot_persona,
    _handle_query_long_term_memory,
)

logger = logging.getLogger(__name__)


async def _brain_handle_task_search(params, room_id, account_id, sender_name, context):
    try:
        import sys
        main = sys.modules.get('main')
        if not main:
            return HandlerResult(success=False, message="システムエラーが発生したウル🐺")

        handle_chatwork_task_search = getattr(main, 'handle_chatwork_task_search')
        result = handle_chatwork_task_search(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=context.to_dict() if context else None)
        return HandlerResult(success=True, message=result if result else "タスクが見つからなかったウル🐺")
    except Exception as e:
        print(f"task_search error: {e}")
        import traceback
        traceback.print_exc()
        return HandlerResult(success=False, message=f"タスク検索でエラーが発生したウル🐺")


async def _brain_handle_task_create(params, room_id, account_id, sender_name, context):
    try:
        import sys
        main = sys.modules.get('main')
        if not main:
            return HandlerResult(success=False, message="システムエラーが発生したウル🐺")

        handle_chatwork_task_create = getattr(main, 'handle_chatwork_task_create')
        result = handle_chatwork_task_create(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=context.to_dict() if context else None)
        return HandlerResult(success=True, message=result if result else "タスクを作成したウル🐺")
    except Exception as e:
        return HandlerResult(success=False, message=f"タスク作成でエラーが発生したウル🐺")


async def _brain_handle_task_complete(params, room_id, account_id, sender_name, context):
    try:
        import sys
        main = sys.modules.get('main')
        if not main:
            return HandlerResult(success=False, message="システムエラーが発生したウル🐺")

        handle_chatwork_task_complete = getattr(main, 'handle_chatwork_task_complete')
        handler_context = {}
        if context and hasattr(context, 'recent_tasks') and context.recent_tasks:
            handler_context["recent_tasks_context"] = context.recent_tasks
        result = handle_chatwork_task_complete(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=handler_context)
        return HandlerResult(success=True, message=result if result else "タスクを完了にしたウル🐺")
    except Exception as e:
        return HandlerResult(success=False, message=f"タスク完了でエラーが発生したウル🐺")


async def _brain_handle_query_knowledge(params, room_id, account_id, sender_name, context):
    """
    ナレッジ検索ハンドラー

    Phase 3.5: ハンドラーはデータ取得のみ。回答生成はBrain層が担当。
    dict結果（needs_answer_synthesis=True）をHandlerResult.dataに格納し、
    core.py の _synthesize_knowledge_answer で Brain が回答を合成する。
    """
    try:
        import sys
        main = sys.modules.get('main')
        if not main:
            return HandlerResult(success=False, message="システムエラーが発生したウル🐺")

        handle_query_company_knowledge = getattr(main, 'handle_query_company_knowledge')
        result = handle_query_company_knowledge(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name)

        # Phase 3.5: dict結果はBrain合成用のデータとして渡す
        if isinstance(result, dict):
            return HandlerResult(
                success=True,
                message=result.get("message", "検索完了ウル🐺"),
                data=result,
            )
        return HandlerResult(success=True, message=result if result else "ナレッジが見つからなかったウル🐺")
    except Exception as e:
        return HandlerResult(success=False, message=f"ナレッジ検索でエラーが発生したウル🐺")


async def _brain_handle_save_memory(params, room_id, account_id, sender_name, context):
    """
    記憶保存ハンドラー

    v10.40.9: メモリ分離対応
    - ボットペルソナ設定 → bot_persona_memoryに保存
    - 長期記憶パターン → user_long_term_memoryに保存
    - それ以外 → 従来の人物情報記憶（persons/person_attributes）

    v10.40.11: 保存結果に基づく返信修正
    - success=True の場合のみ「覚えた」と返す
    - 保存先を明確にログ出力
    """
    try:
        import sys
        main = sys.modules.get('main')
        if not main:
            return HandlerResult(success=False, message="システムエラーが発生したウル🐺")

        USE_BOT_PERSONA_MEMORY = getattr(main, 'USE_BOT_PERSONA_MEMORY', False)
        USE_LONG_TERM_MEMORY = getattr(main, 'USE_LONG_TERM_MEMORY', False)
        is_bot_persona_setting = getattr(main, 'is_bot_persona_setting', lambda x: False)
        is_long_term_memory_request = getattr(main, 'is_long_term_memory_request', lambda x: False)
        handle_save_memory = getattr(main, 'handle_save_memory')

        # オリジナルメッセージを取得
        # v10.48.7: params.message をフォールバックとして使用（確認フロー対応）
        original_message = ""
        if context:
            original_message = getattr(context, 'original_message', '') or ''
            if not original_message and hasattr(context, 'to_dict'):
                ctx_dict = context.to_dict()
                original_message = ctx_dict.get('original_message', '')
        # v10.48.7: paramsからのフォールバック（確認後はcontextに元メッセージがない）
        if not original_message:
            original_message = params.get("message", "")

        # v10.40.11: デバッグログ
        print(f"🔍 [save_memory DEBUG] message: {original_message[:80]}..." if len(original_message) > 80 else f"🔍 [save_memory DEBUG] message: {original_message}")

        # v10.40.11: is_bot_persona_setting() の判定結果をログ
        is_persona = is_bot_persona_setting(original_message) if USE_BOT_PERSONA_MEMORY and original_message else False
        print(f"🔍 [save_memory DEBUG] is_bot_persona_setting() = {is_persona}")

        # v10.40.9: ボットペルソナ設定を先に検出
        if is_persona:
            print(f"🐺 ボットペルソナ設定検出: {original_message[:50]}...")
            result = await _handle_save_bot_persona(
                original_message, room_id, account_id, sender_name
            )
            print(f"🔍 [save_memory DEBUG] 保存先: bot_persona_memory, success={result.get('success', False)}")
            return HandlerResult(success=result.get("success", False), message=result.get("message", ""))

        # v10.40.8: 長期記憶パターンを検出
        is_long_term = is_long_term_memory_request(original_message) if USE_LONG_TERM_MEMORY and original_message else False
        print(f"🔍 [save_memory DEBUG] is_long_term_memory_request() = {is_long_term}")

        if is_long_term:
            print(f"🔥 長期記憶パターン検出: {original_message[:50]}...")
            result = await _handle_save_long_term_memory(
                original_message, room_id, account_id, sender_name
            )
            print(f"🔍 [save_memory DEBUG] 保存先: user_long_term_memory, success={result.get('success', False)}")
            return HandlerResult(success=result.get("success", False), message=result.get("message", ""))

        # v10.40.11: ボットペルソナでも長期記憶でもない場合
        # 人物情報として適切かどうか確認
        attributes = params.get("attributes", [])
        print(f"🔍 [save_memory DEBUG] attributes: {attributes}")

        if not attributes:
            # 属性が抽出できなかった場合 → 保存しない
            print(f"🔍 [save_memory DEBUG] 保存先: none (属性なし)")
            return HandlerResult(
                success=False,
                message="🤔 何を覚えればいいかわからなかったウル...もう少し詳しく教えてほしいウル！"
            )

        # 通常の人物情報記憶
        result = handle_save_memory(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=context.to_dict() if context else None)

        # v10.40.11: 結果に基づいて返信（handle_save_memoryは文字列を返す）
        if result:
            print(f"🔍 [save_memory DEBUG] 保存先: person_attributes")
            # 保存成功（メッセージが返ってきた）
            return HandlerResult(success=True, message=str(result))
        else:
            print(f"🔍 [save_memory DEBUG] 保存先: none (保存失敗)")
            return HandlerResult(
                success=False,
                message="🤔 保存できなかったウル...もう一度試してほしいウル！"
            )
    except Exception as e:
        print(f"❌ 記憶保存エラー: {e}")
        import traceback
        traceback.print_exc()
        return HandlerResult(success=False, message=f"記憶保存でエラーが発生したウル🐺")


async def _brain_handle_query_memory(params, room_id, account_id, sender_name, context):
    """
    記憶検索ハンドラー

    v10.40.9: 長期記憶（人生軸）クエリを検出して分岐
    """
    try:
        import sys
        main = sys.modules.get('main')
        if not main:
            return HandlerResult(success=False, message="システムエラーが発生したウル🐺")

        USE_LONG_TERM_MEMORY = getattr(main, 'USE_LONG_TERM_MEMORY', False)
        handle_query_memory = getattr(main, 'handle_query_memory')

        # v10.40.9: 長期記憶クエリパターンを検出
        # v10.48.7: params.message をフォールバックとして使用（確認フロー対応）
        original_message = ""
        if context:
            original_message = getattr(context, 'original_message', '') or ''
            if not original_message and hasattr(context, 'to_dict'):
                ctx_dict = context.to_dict()
                original_message = ctx_dict.get('original_message', '')
        if not original_message:
            original_message = params.get("message", "")

        long_term_query_patterns = [
            r"軸を(確認|教えて|見せて)",
            r"(俺|私|自分)の軸",
            r"人生の軸",
            r"価値観を(確認|教えて)",
        ]

        is_long_term_query = False
        for pattern in long_term_query_patterns:
            if re.search(pattern, original_message, re.IGNORECASE):
                is_long_term_query = True
                break

        if is_long_term_query and USE_LONG_TERM_MEMORY:
            print(f"🔍 [query_memory] long_term_query detected, redirecting to long_term_memory")
            result = await _handle_query_long_term_memory(
                account_id=account_id,
                sender_name=sender_name
            )
            if result.get("success"):
                return HandlerResult(success=True, message=str(result.get("message", "")))
            # 長期記憶がなければ従来処理にフォールバック

        # 従来の記憶検索
        result = handle_query_memory(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=context.to_dict() if context else None)
        return HandlerResult(success=True, message=str(result) if result else "記憶が見つからなかったウル🐺")
    except Exception as e:
        return HandlerResult(success=False, message=f"記憶検索でエラーが発生したウル🐺")


async def _brain_handle_delete_memory(params, room_id, account_id, sender_name, context):
    try:
        import sys
        main = sys.modules.get('main')
        if not main:
            return HandlerResult(success=False, message="システムエラーが発生したウル🐺")

        handle_delete_memory = getattr(main, 'handle_delete_memory')
        result = handle_delete_memory(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=context.to_dict() if context else None)
        return HandlerResult(success=True, message=result if result else "記憶を削除したウル🐺")
    except Exception as e:
        return HandlerResult(success=False, message=f"記憶削除でエラーが発生したウル🐺")


async def _brain_handle_learn_knowledge(params, room_id, account_id, sender_name, context):
    try:
        import sys
        main = sys.modules.get('main')
        if not main:
            return HandlerResult(success=False, message="システムエラーが発生したウル🐺")

        handle_learn_knowledge = getattr(main, 'handle_learn_knowledge')
        result = handle_learn_knowledge(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name)
        return HandlerResult(success=True, message=result if result else "知識を学習したウル🐺")
    except Exception as e:
        return HandlerResult(success=False, message=f"知識学習でエラーが発生したウル🐺")


async def _brain_handle_forget_knowledge(params, room_id, account_id, sender_name, context):
    try:
        import sys
        main = sys.modules.get('main')
        if not main:
            return HandlerResult(success=False, message="システムエラーが発生したウル🐺")

        handle_forget_knowledge = getattr(main, 'handle_forget_knowledge')
        result = handle_forget_knowledge(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name)
        return HandlerResult(success=True, message=result if result else "知識を削除したウル🐺")
    except Exception as e:
        return HandlerResult(success=False, message=f"知識削除でエラーが発生したウル🐺")


async def _brain_handle_list_knowledge(params, room_id, account_id, sender_name, context):
    """
    知識一覧ハンドラー

    v10.40.17: 「軸を確認」等の長期記憶クエリは long_term_memory から取得
    """
    try:
        import sys
        main = sys.modules.get('main')
        if not main:
            return HandlerResult(success=False, message="システムエラーが発生したウル🐺")

        handle_list_knowledge = getattr(main, 'handle_list_knowledge')

        # v10.40.17: 長期記憶クエリパターンを検出
        # v10.48.7: params.message をフォールバックとして使用（確認フロー対応）
        original_message = ""
        if context:
            original_message = getattr(context, 'original_message', '') or ''
            if not original_message and hasattr(context, 'to_dict'):
                ctx_dict = context.to_dict()
                original_message = ctx_dict.get('original_message', '')
        if not original_message:
            original_message = params.get("message", "")

        long_term_query_patterns = [
            r"軸を(確認|教えて|見せて)",
            r"(俺|私|自分)の軸",
            r"人生の軸",
            r"価値観を(確認|教えて)",
        ]

        is_long_term_query = False
        for pattern in long_term_query_patterns:
            if re.search(pattern, original_message, re.IGNORECASE):
                is_long_term_query = True
                break

        if is_long_term_query:
            print(f"🔍 [list_knowledge] long_term_query detected, redirecting to long_term_memory")
            result = await _handle_query_long_term_memory(
                account_id=account_id,
                sender_name=sender_name
            )
            if result.get("success"):
                return HandlerResult(success=True, message=str(result.get("message", "")))
            # 長期記憶がなければ従来処理にフォールバック

        result = handle_list_knowledge(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name)
        return HandlerResult(success=True, message=str(result) if result else "知識一覧を取得したウル🐺")
    except Exception as e:
        print(f"❌ list_knowledge error: {e}")
        return HandlerResult(success=False, message=f"知識一覧でエラーが発生したウル🐺")


async def _brain_handle_goal_setting_start(params, room_id, account_id, sender_name, context):
    """目標設定開始ハンドラー（v10.29.8）"""
    try:
        import sys
        main = sys.modules.get('main')
        if not main:
            return HandlerResult(success=False, message="システムエラーが発生したウル🐺")

        USE_GOAL_SETTING_LIB = getattr(main, 'USE_GOAL_SETTING_LIB', False)
        if USE_GOAL_SETTING_LIB:
            get_pool = getattr(main, 'get_pool')
            process_goal_setting_message = getattr(main, 'process_goal_setting_message')

            pool = get_pool()
            result = process_goal_setting_message(pool, room_id, account_id, "目標を設定したい")
            if result:
                message = result.get("message", "")
                if message:
                    return HandlerResult(success=result.get("success", False), message=message)
        return HandlerResult(success=True, message="目標設定を始めるウル🐺")
    except Exception as e:
        return HandlerResult(success=False, message="目標設定でエラーが発生したウル🐺")


async def _brain_handle_goal_progress_report(params, room_id, account_id, sender_name, context):
    try:
        import sys
        main = sys.modules.get('main')
        if not main:
            return HandlerResult(success=False, message="システムエラーが発生したウル🐺")

        handle_goal_progress_report = getattr(main, 'handle_goal_progress_report')
        result = handle_goal_progress_report(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=context.to_dict() if context else None)
        # v10.54.5: 辞書型の戻り値を正しく処理
        return _extract_handler_result(result, "進捗を報告したウル🐺")
    except Exception as e:
        return HandlerResult(success=False, message=f"進捗報告でエラーが発生したウル🐺")


async def _brain_handle_goal_status_check(params, room_id, account_id, sender_name, context):
    try:
        import sys
        main = sys.modules.get('main')
        if not main:
            return HandlerResult(success=False, message="システムエラーが発生したウル🐺")

        handle_goal_status_check = getattr(main, 'handle_goal_status_check')
        result = handle_goal_status_check(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=context.to_dict() if context else None)
        # v10.54.5: 辞書型の戻り値を正しく処理
        return _extract_handler_result(result, "目標状況を確認したウル🐺")
    except Exception as e:
        return HandlerResult(success=False, message=f"目標状況確認でエラーが発生したウル🐺")


# v10.45.0: goal_review ハンドラー（既存目標の一覧・整理・削除・修正）
async def _brain_handle_goal_review(params, room_id, account_id, sender_name, context):
    try:
        import sys
        from datetime import datetime, timedelta
        main = sys.modules.get('main')
        if not main:
            return HandlerResult(success=False, message="システムエラーが発生したウル🐺")

        handle_goal_review = getattr(main, 'handle_goal_review')
        result = handle_goal_review(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=context.to_dict() if context else None)

        # v10.56.3: LIST_CONTEXT状態を保存（目標一覧表示後の文脈保持）
        if isinstance(result, dict) and result.get("success", True):
            try:
                from lib.brain.state_manager import BrainStateManager
                from lib.brain.models import StateType
                from sqlalchemy import text

                get_pool = getattr(main, 'get_pool')
                pool = get_pool()

                # v10.56.6: ユーザーのorganization_idを取得（マルチテナント対応）
                with pool.connect() as conn:
                    user_result = conn.execute(
                        text("SELECT organization_id FROM users WHERE chatwork_account_id = :account_id LIMIT 1"),
                        {"account_id": str(account_id)}
                    ).fetchone()

                if user_result and user_result[0]:
                    org_id = str(user_result[0])
                    logger.debug("[LIST_CONTEXT保存/goal_review] org_id取得成功")

                    state_manager = BrainStateManager(pool=pool, org_id=org_id)
                    expires_at = datetime.utcnow() + timedelta(minutes=5)

                    await state_manager.transition_to(
                        room_id=room_id,
                        user_id=str(account_id),
                        state_type=StateType.LIST_CONTEXT,
                        step="goal_list",
                        data={
                            "list_type": "goals",
                            "action": "goal_list",
                            "pending_data": {},
                            "expires_at": expires_at.isoformat(),
                        },
                        timeout_minutes=5,
                    )
                    logger.debug("[LIST_CONTEXT保存/goal_review] 状態保存完了")
                else:
                    logger.debug("[LIST_CONTEXT保存/goal_review] ユーザーのorg_id取得失敗")
            except Exception as state_err:
                print(f"❌ LIST_CONTEXT状態保存エラー（goal_review）: {state_err}")

        # v10.54.5: 辞書型の戻り値を正しく処理
        return _extract_handler_result(result, "目標一覧を表示したウル🐺")
    except Exception as e:
        print(f"goal_review error: {e}")
        return HandlerResult(success=False, message=f"目標一覧でエラーが発生したウル🐺")


# v10.45.0: goal_consult ハンドラー（目標の決め方・優先順位の相談）
async def _brain_handle_goal_consult(params, room_id, account_id, sender_name, context):
    try:
        import sys
        main = sys.modules.get('main')
        if not main:
            return HandlerResult(success=False, message="システムエラーが発生したウル🐺")

        handle_goal_consult = getattr(main, 'handle_goal_consult')
        result = handle_goal_consult(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=context.to_dict() if context else None)
        # v10.54.5: 辞書型の戻り値を正しく処理
        return _extract_handler_result(result, "目標について相談を受けたウル🐺")
    except Exception as e:
        print(f"goal_consult error: {e}")
        return HandlerResult(success=False, message=f"目標相談でエラーが発生したウル🐺")


# v10.56.2: goal_delete ハンドラー（目標削除）
async def _brain_handle_goal_delete(params, room_id, account_id, sender_name, context):
    """
    目標削除ハンドラー

    設計書: docs/05_phase2-5_goal_achievement.md セクション5.6.1

    v10.56.2: LIST_CONTEXT状態保存対応
    - awaiting_inputが返された場合、LIST_CONTEXT状態を保存
    - 次の入力は自動的にgoal_deleteとして処理される
    """
    try:
        import sys
        from datetime import datetime, timedelta

        main = sys.modules.get('main')
        if not main:
            return HandlerResult(success=False, message="システムエラーが発生したウル🐺")

        handle_goal_delete = getattr(main, 'handle_goal_delete')
        result = handle_goal_delete(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=context.to_dict() if context else None)

        # awaiting_inputまたはawaiting_confirmationの場合は状態を保存
        if isinstance(result, dict):
            awaiting_input = result.get("awaiting_input")
            awaiting_confirmation = result.get("awaiting_confirmation")
            pending_data = result.get("pending_data", {})

            # LIST_CONTEXT状態を保存（5分有効）
            if awaiting_input or awaiting_confirmation:
                try:
                    from lib.brain.state_manager import BrainStateManager
                    from lib.brain.models import StateType
                    from sqlalchemy import text

                    get_pool = getattr(main, 'get_pool')
                    pool = get_pool()

                    # v10.56.6: ユーザーのorganization_idを取得（マルチテナント対応）
                    with pool.connect() as conn:
                        user_result = conn.execute(
                            text("SELECT organization_id FROM users WHERE chatwork_account_id = :account_id LIMIT 1"),
                            {"account_id": str(account_id)}
                        ).fetchone()

                    if user_result and user_result[0]:
                        org_id = str(user_result[0])
                        logger.debug("[LIST_CONTEXT保存] org_id取得成功")

                        state_manager = BrainStateManager(pool=pool, org_id=org_id)

                        # 有効期限を計算（5分）
                        expires_at = datetime.utcnow() + timedelta(minutes=5)

                        await state_manager.transition_to(
                            room_id=room_id,
                            user_id=str(account_id),
                            state_type=StateType.LIST_CONTEXT,
                            step=awaiting_input or awaiting_confirmation,
                            data={
                                "list_type": "goals",
                                "action": "goal_delete",
                                "pending_data": pending_data,
                                "expires_at": expires_at.isoformat(),
                            },
                            timeout_minutes=5,
                        )
                        logger.debug("[LIST_CONTEXT保存] 状態保存完了")
                    else:
                        logger.debug("[LIST_CONTEXT保存] ユーザーのorg_id取得失敗")

                except Exception as state_err:
                    print(f"❌ LIST_CONTEXT状態保存エラー: {state_err}")

            return HandlerResult(
                success=result.get("success", True),
                message=result.get("message", ""),
                metadata={
                    "awaiting_input": awaiting_input,
                    "awaiting_confirmation": awaiting_confirmation,
                    "pending_data": pending_data,
                }
            )
        return _extract_handler_result(result, "目標削除を処理したウル🐺")
    except Exception as e:
        print(f"goal_delete error: {e}")
        return HandlerResult(success=False, message=f"目標削除でエラーが発生したウル🐺")


# v10.56.2: goal_cleanup ハンドラー（目標整理）
async def _brain_handle_goal_cleanup(params, room_id, account_id, sender_name, context):
    """
    目標整理ハンドラー

    設計書: docs/05_phase2-5_goal_achievement.md セクション5.6.2
    """
    try:
        import sys
        main = sys.modules.get('main')
        if not main:
            return HandlerResult(success=False, message="システムエラーが発生したウル🐺")

        handle_goal_cleanup = getattr(main, 'handle_goal_cleanup')
        result = handle_goal_cleanup(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=context.to_dict() if context else None)

        # awaiting_inputまたはawaiting_confirmationの場合はそのまま返す
        if isinstance(result, dict):
            return HandlerResult(
                success=result.get("success", True),
                message=result.get("message", ""),
                metadata={
                    "awaiting_input": result.get("awaiting_input"),
                    "awaiting_confirmation": result.get("awaiting_confirmation"),
                    "pending_data": result.get("pending_data"),
                }
            )
        return _extract_handler_result(result, "目標整理を処理したウル🐺")
    except Exception as e:
        print(f"goal_cleanup error: {e}")
        return HandlerResult(success=False, message=f"目標整理でエラーが発生したウル🐺")


async def _brain_handle_announcement_create(params, room_id, account_id, sender_name, context):
    """v10.33.0: USE_ANNOUNCEMENT_FEATUREフラグチェック削除, v10.33.1: ハンドラー必須化"""
    try:
        import sys
        main = sys.modules.get('main')
        if not main:
            return HandlerResult(success=False, message="システムエラーが発生したウル🐺")

        _get_announcement_handler = getattr(main, '_get_announcement_handler')
        result = _get_announcement_handler().handle_announcement_request(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=context.to_dict() if context else None)
        if result:
            return HandlerResult(success=True, message=result)
        return HandlerResult(success=True, message="アナウンス機能は現在準備中ウル🐺")
    except Exception as e:
        logger.error("announcement_create error: %s", e, exc_info=True)
        return HandlerResult(success=False, message=f"アナウンスでエラーが発生したウル🐺")


async def _brain_handle_query_org_chart(params, room_id, account_id, sender_name, context):
    try:
        import sys
        main = sys.modules.get('main')
        if not main:
            return HandlerResult(success=False, message="システムエラーが発生したウル🐺")

        handle_query_org_chart = getattr(main, 'handle_query_org_chart')
        result = handle_query_org_chart(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=context.to_dict() if context else None)
        return HandlerResult(success=True, message=result if result else "組織情報を取得したウル🐺")
    except Exception as e:
        logger.error("query_org_chart error: %s", e, exc_info=True)
        return HandlerResult(success=False, message=f"組織図クエリでエラーが発生したウル🐺")


async def _brain_handle_daily_reflection(params, room_id, account_id, sender_name, context):
    try:
        import sys
        main = sys.modules.get('main')
        if not main:
            return HandlerResult(success=False, message="システムエラーが発生したウル🐺")

        handle_daily_reflection = getattr(main, 'handle_daily_reflection')
        result = handle_daily_reflection(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=context.to_dict() if context else None)
        return HandlerResult(success=True, message=result if result else "振り返りを記録したウル🐺")
    except Exception as e:
        return HandlerResult(success=False, message=f"振り返りでエラーが発生したウル🐺")


async def _brain_handle_proposal_decision(params, room_id, account_id, sender_name, context):
    try:
        import sys
        main = sys.modules.get('main')
        if not main:
            return HandlerResult(success=False, message="システムエラーが発生したウル🐺")

        handle_proposal_decision = getattr(main, 'handle_proposal_decision')
        result = handle_proposal_decision(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=context.to_dict() if context else None)
        return HandlerResult(success=True, message=result if result else "提案を処理したウル🐺")
    except Exception as e:
        return HandlerResult(success=False, message=f"提案処理でエラーが発生したウル🐺")


async def _brain_handle_api_limitation(params, room_id, account_id, sender_name, context):
    try:
        import sys
        main = sys.modules.get('main')
        if not main:
            return HandlerResult(success=False, message="システムエラーが発生したウル🐺")

        handle_api_limitation = getattr(main, 'handle_api_limitation')
        result = handle_api_limitation(params=params, room_id=room_id, account_id=account_id, sender_name=sender_name, context=context.to_dict() if context else None)
        return HandlerResult(success=True, message=result if result else "API制限の説明ウル🐺")
    except Exception as e:
        return HandlerResult(success=False, message=f"API制限説明でエラーが発生したウル🐺")


# Note: connection_queryのハンドラーはCapabilityBridge経由で登録される
# （設計原則「機能拡張しても脳の構造は変わらない。カタログへの追加のみ」に準拠）


async def _brain_handle_general_conversation(params, room_id, account_id, sender_name, context):
    try:
        import sys
        main = sys.modules.get('main')
        if not main:
            return HandlerResult(success=False, message="システムエラーが発生したウル🐺")

        get_conversation_history = getattr(main, 'get_conversation_history')
        get_room_context = getattr(main, 'get_room_context')
        get_all_persons_summary = getattr(main, 'get_all_persons_summary')
        get_ai_response = getattr(main, 'get_ai_response')

        history = get_conversation_history(room_id, account_id)
        room_context = get_room_context(room_id, limit=30)
        all_persons = get_all_persons_summary()
        context_parts = []
        if room_context:
            context_parts.append(f"【このルームの最近の会話】\n{room_context}")
        if all_persons:
            persons_str = "\n".join([f"・{p['name']}: {p['attributes']}" for p in all_persons[:5] if p['attributes']])
            if persons_str:
                context_parts.append(f"【覚えている人物】\n{persons_str}")
        context_str = "\n\n".join(context_parts) if context_parts else None
        ai_response = get_ai_response(params.get("message", ""), history, sender_name, context_str, "ja", account_id)
        return HandlerResult(success=True, message=ai_response)
    except Exception as e:
        return HandlerResult(success=False, message=f"ごめんウル...もう一度試してほしいウル🐺")


def build_brain_handlers() -> Dict[str, Callable]:
    """
    脳用ハンドラーのマッピングを構築

    v10.40.2: main.pyのSYSTEM_CAPABILITIESと一致するキー名に修正
    - query_company_knowledge → query_knowledge
    - goal_setting_start → goal_registration

    Returns:
        dict: アクション名 -> ハンドラー関数のマッピング
    """
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

    return {
        "chatwork_task_search": _brain_handle_task_search,
        "chatwork_task_create": _brain_handle_task_create,
        "chatwork_task_complete": _brain_handle_task_complete,
        "query_knowledge": _brain_handle_query_knowledge,  # v10.40.2: SYSTEM_CAPABILITIESと一致
        "save_memory": _brain_handle_save_memory,
        "query_memory": _brain_handle_query_memory,
        "delete_memory": _brain_handle_delete_memory,
        "learn_knowledge": _brain_handle_learn_knowledge,
        "forget_knowledge": _brain_handle_forget_knowledge,
        "list_knowledge": _brain_handle_list_knowledge,
        "goal_registration": _brain_handle_goal_setting_start,  # v10.40.2: SYSTEM_CAPABILITIESと一致
        "goal_progress_report": _brain_handle_goal_progress_report,
        "goal_status_check": _brain_handle_goal_status_check,
        "goal_review": _brain_handle_goal_review,
        "goal_consult": _brain_handle_goal_consult,
        "goal_delete": _brain_handle_goal_delete,  # v10.56.2: 目標削除
        "goal_cleanup": _brain_handle_goal_cleanup,  # v10.56.2: 目標整理
        "announcement_create": _brain_handle_announcement_create,
        "query_org_chart": _brain_handle_query_org_chart,
        "daily_reflection": _brain_handle_daily_reflection,
        "proposal_decision": _brain_handle_proposal_decision,
        "api_limitation": _brain_handle_api_limitation,
        "general_conversation": _brain_handle_general_conversation,
        "web_search": _brain_handle_web_search,  # Step A-1
        "calendar_read": _brain_handle_calendar_read,  # Step A-3
        "drive_search": _brain_handle_drive_search,  # Step A-5
        "data_aggregate": _brain_handle_data_aggregate,  # Step C-1
        "data_search": _brain_handle_data_search,  # Step C-1
        "report_generate": _brain_handle_report_generate,  # Step C-5
        "csv_export": _brain_handle_csv_export,  # Step C-5
        "file_create": _brain_handle_file_create,  # Step C-5
    }
