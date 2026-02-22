# lib/brain/handler_wrappers/session_handlers.py
"""
セッション継続ハンドラー

v10.39.1: 脳のcore.pyの_continue_*メソッドから呼び出される
シグネチャ: (message, room_id, account_id, sender_name, state_data) -> dict or str or None
"""

from typing import Dict, Any, Callable


# =====================================================
# グローバル変数: 中断されたセッションを一時保存
# =====================================================
_interrupted_goal_sessions: Dict[str, Dict[str, Any]] = {}


def _brain_continue_goal_setting(message, room_id, account_id, sender_name, state_data):
    """
    目標設定セッションを継続

    GoalSettingDialogueを使用してセッションを継続します。
    """
    try:
        import sys
        main = sys.modules.get('main')
        if not main:
            return {"message": "システムエラーが発生したウル🐺", "success": False}

        USE_GOAL_SETTING_LIB = getattr(main, 'USE_GOAL_SETTING_LIB', False)
        if USE_GOAL_SETTING_LIB:
            get_pool = getattr(main, 'get_pool')
            process_goal_setting_message = getattr(main, 'process_goal_setting_message')

            pool = get_pool()
            result = process_goal_setting_message(pool, room_id, account_id, message)
            if result:
                response_message = result.get("message", "")
                session_completed = result.get("session_completed", False)
                return {
                    "message": response_message,
                    "success": result.get("success", True),
                    "session_completed": session_completed,
                    "new_state": "normal" if session_completed else None,
                    "state_changed": session_completed,
                }
        # フォールバック
        return {
            "message": "目標設定を続けるウル🐺 もう少し詳しく教えてほしいウル！",
            "success": True,
        }
    except Exception as e:
        print(f"❌ _brain_continue_goal_setting error: {e}")
        return {
            "message": "目標設定の処理中にエラーが発生したウル🐺",
            "success": False,
            "session_completed": True,
            "new_state": "normal",
        }


def _brain_continue_announcement(message, room_id, account_id, sender_name, state_data):
    """
    アナウンス確認セッションを継続

    AnnouncementHandlerを使用してセッションを継続します。
    v10.33.1: ハンドラー必須化によりif handler:チェック削除
    """
    try:
        import sys
        main = sys.modules.get('main')
        if not main:
            return {"message": "システムエラーが発生したウル🐺", "success": False}

        _get_announcement_handler = getattr(main, '_get_announcement_handler')

        # state_dataからpending_announcement_idを取得
        pending_id = state_data.get("pending_announcement_id") if state_data else None
        context = {
            "awaiting_announcement_response": True,
            "pending_announcement_id": pending_id,
        }
        # パラメータを構築
        params = {
            "raw_message": message,
        }
        result = _get_announcement_handler().handle_announcement_request(
            params=params,
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
            context=context,
        )
        if result:
            # 結果を解析して完了状態を判定
            is_completed = any(kw in result for kw in ["送信完了", "キャンセル", "スケジュール完了"])
            return {
                "message": result,
                "success": True,
                "session_completed": is_completed,
                "new_state": "normal" if is_completed else None,
            }
        return {
            "message": "アナウンスの確認を続けるウル🐺",
            "success": True,
        }
    except Exception as e:
        print(f"❌ _brain_continue_announcement error: {e}")
        return {
            "message": "アナウンス処理中にエラーが発生したウル🐺",
            "success": False,
            "session_completed": True,
            "new_state": "normal",
        }


def _brain_continue_task_pending(message, room_id, account_id, sender_name, state_data):
    """
    タスク作成待ち状態を継続

    v10.56.15: PostgreSQLのstate_dataを使用してタスク作成を継続。
    state_dataがない場合はFirestoreにフォールバック。
    """
    try:
        import sys
        main = sys.modules.get('main')
        if not main:
            return {"message": "システムエラーが発生したウル🐺", "success": False}

        # v10.56.15: state_dataからpending_paramsを取得（PostgreSQL状態）
        pending_params = state_data.get("pending_params", {}) if state_data else {}
        pending_action = state_data.get("pending_action", "") if state_data else ""

        # タスク作成アクションの場合、メッセージを不足パラメータとして補完
        if pending_action == "chatwork_task_create" and pending_params:
            # メッセージをタスク本文として追加
            if "body" not in pending_params or not pending_params.get("body"):
                pending_params["body"] = message.strip()
                print(f"📋 [task_pending] body補完: {message[:50]}")

                # 他の必須パラメータがあるかチェック
                if pending_params.get("body"):
                    # assignee_idsとlimit_timeがあればタスク作成実行
                    handle_chatwork_task_create = getattr(main, 'handle_chatwork_task_create', None)
                    if handle_chatwork_task_create:
                        try:
                            result = handle_chatwork_task_create(
                                room_id=room_id,
                                account_id=account_id,
                                sender_name=sender_name,
                                params=pending_params,
                            )
                            if result and result.get("success"):
                                return {
                                    "message": result.get("message", "タスクを作成したウル🐺"),
                                    "success": True,
                                    "task_created": True,
                                    "new_state": "normal",
                                }
                        except Exception as e:
                            print(f"⚠️ タスク作成実行エラー: {e}")

        # フォールバック: Firestoreのpending_taskを使用（従来方式）
        handle_pending_task_followup = getattr(main, 'handle_pending_task_followup', None)
        if handle_pending_task_followup:
            result = handle_pending_task_followup(message, room_id, account_id, sender_name)

            if result:
                # タスク作成成功
                return {
                    "message": result,
                    "success": True,
                    "task_created": True,
                    "new_state": "normal",
                }

        # 補完できなかった場合
        return None
    except Exception as e:
        print(f"❌ _brain_continue_task_pending error: {e}")
        return {
            "message": "タスク作成中にエラーが発生したウル🐺",
            "success": False,
            "task_created": False,
            "new_state": "normal",
        }


# =====================================================
# v10.56.2: LIST_CONTEXT継続ハンドラー
# 一覧表示後の入力を処理（「X以外削除」「番号指定」等）
# =====================================================

def _brain_continue_list_context(message, room_id, account_id, sender_name, state_data):
    """
    一覧表示後の入力を処理

    state_dataに保存されたlist_typeとactionに基づいて処理を継続。
    - list_type: "goals" or "tasks"
    - action: "goal_delete", "goal_cleanup", etc.

    設計書: docs/05_phase2-5_goal_achievement.md セクション5.6
    """
    try:
        import sys
        from datetime import datetime

        list_type = state_data.get("list_type", "goals")
        action = state_data.get("action", "goal_delete")
        pending_data = state_data.get("pending_data", {})
        step = state_data.get("step", "")

        # 有効期限チェック（main不要）
        expires_at_str = state_data.get("expires_at")
        if expires_at_str:
            expires_at = datetime.fromisoformat(expires_at_str)
            if datetime.utcnow() > expires_at:
                return {
                    "message": "⏰ 一覧が古くなったウル。もう一度「目標一覧」と言ってほしいウル🐺",
                    "success": True,
                    "session_completed": True,
                    "new_state": "normal",
                }

        # キャンセルキーワードチェック（main不要）
        cancel_keywords = ["やめ", "キャンセル", "取り消", "中止", "やっぱり"]
        if any(kw in message for kw in cancel_keywords):
            return {
                "message": "✅ わかったウル！操作をキャンセルしたウル🐺",
                "success": True,
                "session_completed": True,
                "new_state": "normal",
            }

        # 以降の処理にはmainモジュールが必要
        main = sys.modules.get('main')
        if not main:
            return {"message": "システムエラーが発生したウル🐺", "success": False}

        # 目標一覧の場合
        if list_type == "goals":
            # 一覧直後の文脈（goal_list）
            if step == "goal_list":
                handle_goal_delete = getattr(main, 'handle_goal_delete')
                handle_goal_cleanup = getattr(main, 'handle_goal_cleanup')

                # 削除系の入力（番号 / 以外削除 / 全削除）
                # B-1修正: 進捗報告キーワードが含まれる場合は削除判定から除外
                is_delete_request = any(kw in message for kw in ["削除", "消して", "消す", "以外", "全部消", "全削除"])
                is_progress_report = any(kw in message for kw in [
                    "売り上げ", "売上", "実績", "報告", "達成", "稼いだ", "万円", "受注", "成約",
                    "今日は", "今日の", "今月は", "今月の", "今週は", "今週の",
                ])
                if is_delete_request or (any(ch.isdigit() for ch in message) and not is_progress_report):
                    context = {"original_message": message, "pending_data": pending_data}
                    result = handle_goal_delete(
                        params={},
                        room_id=room_id,
                        account_id=account_id,
                        sender_name=sender_name,
                        context=context
                    )

                    # v10.56.3: awaiting_confirmation または awaiting_input を処理
                    if isinstance(result, dict) and (result.get("awaiting_confirmation") or result.get("awaiting_input")):
                        return {
                            "message": result.get("message", ""),
                            "success": result.get("success", True),
                            "session_completed": False,
                            "new_state_data": {
                                "list_type": "goals",
                                "action": "goal_delete",
                                "step": result.get("awaiting_confirmation") or result.get("awaiting_input"),
                                "pending_data": result.get("pending_data", {}),
                                "expires_at": state_data.get("expires_at"),
                            },
                        }

                    return {
                        "message": result.get("message", "処理を実行したウル🐺"),
                        "success": result.get("success", True),
                        "session_completed": True,
                        "new_state": "normal",
                    }

                # 整理系の入力
                if any(kw in message for kw in ["整理", "重複", "期限", "未定", "相談中", "新規"]):
                    cleanup_type = None
                    if any(kw in message for kw in ["重複"]):
                        cleanup_type = "A"
                    elif any(kw in message for kw in ["期限", "期限切れ"]):
                        cleanup_type = "B"
                    elif any(kw in message for kw in ["未定", "相談中", "新規"]):
                        cleanup_type = "C"

                    context = {"original_message": message, "pending_data": pending_data}
                    params = {"cleanup_type": cleanup_type} if cleanup_type else {}
                    result = handle_goal_cleanup(
                        params=params,
                        room_id=room_id,
                        account_id=account_id,
                        sender_name=sender_name,
                        context=context
                    )

                    if isinstance(result, dict) and (result.get("awaiting_confirmation") or result.get("awaiting_input")):
                        return {
                            "message": result.get("message", ""),
                            "success": result.get("success", True),
                            "session_completed": False,
                            "new_state_data": {
                                "list_type": "goals",
                                "action": "goal_cleanup",
                                "step": result.get("awaiting_confirmation") or result.get("awaiting_input"),
                                "pending_data": result.get("pending_data", {}),
                                "expires_at": state_data.get("expires_at"),
                            },
                        }

                    return {
                        "message": result.get("message", "処理を実行したウル🐺"),
                        "success": result.get("success", True),
                        "session_completed": True,
                        "new_state": "normal",
                    }

                # それ以外は文脈を解除して通常処理へ
                return None

            # 確認待ち状態からの応答（「OK」「削除する」等）
            if step in ["goal_delete", "goal_delete_duplicates", "goal_cleanup_duplicates", "goal_cleanup_expired"]:
                msg_lc = message.lower()
                approval_keywords = [
                    "ok", "はい", "削除", "実行", "うん", "いいよ", "お願い",
                    "そうだよ", "全部ok", "全削除", "全消し", "全部消す", "全部消して", "消して",
                    "全件削除", "全件ok", "全件削除でok", "全部削除でok",
                    "お願いいたします", "お願いします",
                ]
                if any(kw in msg_lc for kw in approval_keywords):
                    context = {
                        "pending_data": pending_data,
                        "original_message": message,
                    }

                    # v10.56.2: delete系とcleanup系で適切なハンドラーを呼び分け
                    if step in ["goal_delete", "goal_delete_duplicates"]:
                        handle_goal_delete = getattr(main, 'handle_goal_delete')
                        result = handle_goal_delete(
                            params={"confirmed": True, **pending_data},
                            room_id=room_id,
                            account_id=account_id,
                            sender_name=sender_name,
                            context=context
                        )
                    else:
                        # goal_cleanup_duplicates, goal_cleanup_expired
                        handle_goal_cleanup = getattr(main, 'handle_goal_cleanup')
                        result = handle_goal_cleanup(
                            params={"confirmed": True, **pending_data},
                            room_id=room_id,
                            account_id=account_id,
                            sender_name=sender_name,
                            context=context
                        )

                    return {
                        "message": result.get("message", "処理を実行したウル🐺"),
                        "success": result.get("success", True),
                        "session_completed": True,
                        "new_state": "normal",
                    }
                # 承認語句が不足している場合は確認を継続（文脈を維持）
                return {
                    "message": "✅ 了解ウル！全削除で進めていい？\n「はい」「全削除でOK」「お願いします」などで返してほしいウル🐺",
                    "success": True,
                    "session_completed": False,
                    "new_state_data": {
                        "list_type": "goals",
                        "action": "goal_delete",
                        "step": step,
                        "pending_data": pending_data,
                        "expires_at": state_data.get("expires_at"),
                    },
                }

            # 番号入力待ち状態からの応答
            if step == "goal_delete_numbers":
                # 入力をそのままgoal_deleteに渡す
                handle_goal_delete = getattr(main, 'handle_goal_delete')

                context = {
                    "original_message": message,
                    "pending_data": pending_data,
                }
                result = handle_goal_delete(
                    params={},
                    room_id=room_id,
                    account_id=account_id,
                    sender_name=sender_name,
                    context=context
                )

                # awaiting_confirmationが返ってきた場合は続ける
                if isinstance(result, dict):
                    if result.get("awaiting_confirmation"):
                        return {
                            "message": result.get("message", ""),
                            "success": result.get("success", True),
                            "session_completed": False,  # セッション継続
                            "new_state_data": {
                                "list_type": "goals",
                                "action": "goal_delete",
                                "step": result.get("awaiting_confirmation"),
                                "pending_data": result.get("pending_data", {}),
                                "expires_at": state_data.get("expires_at"),
                            },
                        }
                    return {
                        "message": result.get("message", "処理を実行したウル🐺"),
                        "success": result.get("success", True),
                        "session_completed": True,
                        "new_state": "normal",
                    }

        # フォールバック
        return {
            "message": "🤔 よくわからなかったウル。もう一度教えてほしいウル🐺",
            "success": True,
            "session_completed": False,
        }

    except Exception as e:
        print(f"❌ _brain_continue_list_context error: {e}")
        import traceback
        traceback.print_exc()
        return {
            "message": "処理中にエラーが発生したウル🐺 もう一度試してほしいウル",
            "success": False,
            "session_completed": True,
            "new_state": "normal",
        }


# =====================================================
# v10.39.2: 目標設定中断・再開ハンドラー
# 脳が意図を汲み取り、別の話題に対応するための仕組み
# =====================================================

def _brain_interrupt_goal_setting(room_id, account_id, interrupted_session):
    """
    目標設定セッションを中断状態で保存

    脳が「別の意図」を検出した場合に呼ばれる。
    途中経過を記憶し、後で再開できるようにする。
    """
    try:
        key = f"{room_id}:{account_id}"
        _interrupted_goal_sessions[key] = interrupted_session
        print(f"📝 目標設定セッションを中断保存: {key}, step={interrupted_session.get('current_step')}")
        return True
    except Exception as e:
        print(f"❌ _brain_interrupt_goal_setting error: {e}")
        return False


def _brain_get_interrupted_goal_setting(room_id, account_id):
    """中断されたセッションを取得"""
    key = f"{room_id}:{account_id}"
    return _interrupted_goal_sessions.get(key)


def _brain_resume_goal_setting(message, room_id, account_id, sender_name, state_data):
    """
    中断されたセッションを再開

    「目標設定の続き」などのキーワードで呼ばれる。
    """
    try:
        import sys
        main = sys.modules.get('main')
        if not main:
            return {"message": "システムエラーが発生したウル🐺", "success": False}

        key = f"{room_id}:{account_id}"
        interrupted = _interrupted_goal_sessions.get(key)

        if not interrupted:
            return {
                "message": "中断された目標設定は見つからなかったウル🐺\n新しく目標設定を始める？「目標設定したい」と言ってくれればスタートするウル！",
                "success": True,
                "session_completed": False,
            }

        # 中断されたセッションの情報を取得
        current_step = interrupted.get("current_step", "why")
        why_answer = interrupted.get("why_answer", "")
        what_answer = interrupted.get("what_answer", "")
        how_answer = interrupted.get("how_answer", "")

        USE_GOAL_SETTING_LIB = getattr(main, 'USE_GOAL_SETTING_LIB', False)
        # セッションを再開
        if USE_GOAL_SETTING_LIB:
            get_pool = getattr(main, 'get_pool')
            process_goal_setting_message = getattr(main, 'process_goal_setting_message')

            pool = get_pool()
            # 既存のセッションを再開するか、新しいセッションを開始
            result = process_goal_setting_message(pool, room_id, account_id, "目標設定を再開したい")
            if result:
                # 中断されたセッションをクリア
                del _interrupted_goal_sessions[key]

                # 進捗を表示
                progress_summary = "📝 前回の進捗:\n"
                if why_answer:
                    progress_summary += f"・WHY: {why_answer[:50]}...\n" if len(why_answer) > 50 else f"・WHY: {why_answer}\n"
                if what_answer:
                    progress_summary += f"・WHAT: {what_answer[:50]}...\n" if len(what_answer) > 50 else f"・WHAT: {what_answer}\n"
                if how_answer:
                    progress_summary += f"・HOW: {how_answer[:50]}...\n" if len(how_answer) > 50 else f"・HOW: {how_answer}\n"

                response = result.get("message", "")
                if progress_summary != "📝 前回の進捗:\n":
                    response = f"{progress_summary}\n{response}"

                return {
                    "message": response,
                    "success": True,
                    "session_completed": result.get("session_completed", False),
                }

        return {
            "message": "目標設定を再開するウル🐺",
            "success": True,
        }
    except Exception as e:
        print(f"❌ _brain_resume_goal_setting error: {e}")
        return {
            "message": "目標設定の再開中にエラーが発生したウル🐺",
            "success": False,
        }


def build_session_handlers() -> Dict[str, Callable]:
    """
    セッション継続ハンドラーのマッピングを構築

    Returns:
        dict: セッションタイプ -> ハンドラー関数のマッピング
    """
    return {
        "goal_setting": _brain_continue_goal_setting,
        "announcement": _brain_continue_announcement,
        "task_pending": _brain_continue_task_pending,
        "goal_resume": _brain_resume_goal_setting,
        "list_context": _brain_continue_list_context,  # v10.56.2: 一覧表示後の文脈保持
    }


def get_session_management_functions() -> Dict[str, Callable]:
    """
    セッション管理関数を取得

    Returns:
        dict: 管理関数名 -> 関数のマッピング
    """
    return {
        "interrupt_goal_setting": _brain_interrupt_goal_setting,
        "get_interrupted_goal_setting": _brain_get_interrupted_goal_setting,
        "resume_goal_setting": _brain_resume_goal_setting,
    }
