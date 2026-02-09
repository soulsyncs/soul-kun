# lib/brain/handler_wrappers.py
"""
脳用ハンドラーラッパー関数

v10.40: main.py から抽出
設計原則「全入力は脳を通る」に準拠

このモジュールは、Brainの意図理解・判断結果を
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

from typing import Dict, Any, Callable, Optional
import re
import logging

from lib.brain.models import HandlerResult

logger = logging.getLogger(__name__)


# =====================================================
# ユーティリティ関数
# =====================================================

def _extract_handler_result(result: Any, default_message: str) -> HandlerResult:
    """
    ハンドラーの戻り値からHandlerResultを生成する

    v10.54.5: 辞書型の戻り値を正しく処理

    Args:
        result: ハンドラーの戻り値（文字列、辞書、またはNone）
        default_message: resultがNone/空の場合のデフォルトメッセージ

    Returns:
        HandlerResult: 正しく構築されたハンドラー結果

    Examples:
        # 文字列が返された場合
        >>> _extract_handler_result("タスク一覧です", "デフォルト")
        HandlerResult(success=True, message="タスク一覧です")

        # 辞書が返された場合
        >>> _extract_handler_result({"success": True, "message": "目標一覧"}, "デフォルト")
        HandlerResult(success=True, message="目標一覧")

        # Noneが返された場合
        >>> _extract_handler_result(None, "デフォルトメッセージ")
        HandlerResult(success=True, message="デフォルトメッセージ")
    """
    if result is None:
        return HandlerResult(success=True, message=default_message)

    if isinstance(result, dict):
        # 辞書の場合はmessageフィールドを抽出
        message = result.get("message", default_message)
        success = result.get("success", True)

        # messageがNoneの場合はデフォルトメッセージを使用
        if message is None:
            message = default_message

        # 追加のフィールドをdataとして保持（fallback_to_general等）
        data = {k: v for k, v in result.items() if k not in ("success", "message")}

        return HandlerResult(success=success, message=message, data=data if data else None)

    # 文字列またはその他の場合
    return HandlerResult(success=True, message=str(result) if result else default_message)


# =====================================================
# グローバル変数: 中断されたセッションを一時保存
# =====================================================
_interrupted_goal_sessions: Dict[str, Dict[str, Any]] = {}


# =====================================================
# バイパスハンドラー
# =====================================================

def _bypass_handle_announcement(room_id, account_id, sender_name, message, context):
    """
    アナウンスのpending状態をバイパス処理

    v10.33.1: ハンドラー必須化により_get_announcement_handler()を使用
    """
    # 遅延インポート（循環参照回避）
    try:
        import sys
        main = sys.modules.get('main')
        if not main:
            print("⚠️ [バイパス] mainモジュールが見つかりません")
            return None

        _get_announcement_handler = getattr(main, '_get_announcement_handler', None)
        if not _get_announcement_handler:
            print("⚠️ [バイパス] _get_announcement_handler が見つかりません")
            return None

        handler = _get_announcement_handler()
        if not handler:
            return None

        # pending announcementを確認
        pending = handler._get_pending_announcement(room_id, account_id)
        if not pending:
            return None

        # フォローアップ処理
        response = handler.handle_announcement_request(
            params={"raw_message": message},
            room_id=room_id,
            account_id=account_id,
            sender_name=sender_name,
        )

        if response is None:
            return None

        return response

    except Exception as e:
        print(f"❌ [バイパス] announcement エラー: {e}")
        return None


def build_bypass_handlers() -> Dict[str, Callable]:
    """
    バイパスハンドラーのマッピングを構築

    v10.39.3: goal_sessionバイパスを削除
    - 脳の意図理解を通すため、バイパスを使わない
    - 脳のcore.py _continue_goal_setting() で意図を理解してから処理

    Returns:
        dict: バイパスタイプ -> ハンドラー関数のマッピング
    """
    return {
        # v10.39.3: goal_session バイパスを削除（脳が意図理解してからハンドラーを呼ぶ）
        # "goal_session": _bypass_handle_goal_session,
        "announcement_pending": _bypass_handle_announcement,
        # "task_pending" と "local_command" は既存の脳内処理で対応可能
    }


# =====================================================
# ヘルパー関数（長期記憶・ボットペルソナ）
# =====================================================

async def _handle_save_long_term_memory(message: str, room_id: str, account_id: str, sender_name: str) -> Dict[str, Any]:
    """
    長期記憶（人生軸・価値観）を保存

    v10.40.8: 新規追加
    """
    try:
        import sys
        import sqlalchemy
        main = sys.modules.get('main')
        if not main:
            return {"success": False, "message": "システムエラーが発生したウル🐺"}

        get_pool = getattr(main, 'get_pool')
        save_long_term_memory = getattr(main, 'save_long_term_memory')

        pool = get_pool()

        # ユーザー情報を取得
        with pool.connect() as conn:
            user_result = conn.execute(
                sqlalchemy.text("""
                    SELECT id, organization_id FROM users
                    WHERE chatwork_account_id = :account_id
                    LIMIT 1
                """),
                {"account_id": str(account_id)}
            ).fetchone()

            if not user_result:
                return {
                    "success": False,
                    "message": "ユーザー情報が見つからなかったウル...🐺"
                }

            # v10.40.15: users.id は UUID なので int 化しない
            user_id = str(user_result[0])
            org_id = str(user_result[1]) if user_result[1] else None

            if not org_id:
                return {
                    "success": False,
                    "message": "組織情報が見つからなかったウル...🐺"
                }

        # 長期記憶を保存
        result = save_long_term_memory(
            pool=pool,
            org_id=org_id,
            user_id=user_id,
            user_name=sender_name,
            message=message
        )

        # 型安全のため明示的にDict[str, Any]を返す
        if isinstance(result, dict):
            return result
        return {"success": False, "message": "予期しない戻り値ウル🐺"}

    except Exception as e:
        print(f"❌ 長期記憶保存エラー: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "message": "長期記憶の保存中にエラーが発生したウル...🐺\nもう一度試してほしいウル"
        }


async def _handle_save_bot_persona(
    message: str,
    room_id: str,
    account_id: str,
    sender_name: str
) -> Dict[str, Any]:
    """
    v10.40.9: ボットペルソナ設定を保存

    ソウルくんのキャラ設定（好物、口調など）を保存。
    管理者のみ設定可能。

    v10.40.11: ホワイトリスト拒否時のリダイレクト対応
    - user_idを渡して、拒否時はuser_long_term_memoryへリダイレクト
    - デバッグログ追加
    """
    from lib.bot_persona_memory import extract_persona_key_value, is_valid_bot_persona

    try:
        import sys
        import sqlalchemy
        main = sys.modules.get('main')
        if not main:
            return {"success": False, "message": "システムエラーが発生したウル🐺"}

        is_admin = getattr(main, 'is_admin')
        get_pool = getattr(main, 'get_pool')
        save_bot_persona = getattr(main, 'save_bot_persona')

        # 管理者チェック
        if not is_admin(account_id):
            return {
                "success": False,
                "message": "ソウルくんの設定は管理者のみ変更できるウル🐺\n菊地さんにお願いしてほしいウル！"
            }

        pool = get_pool()

        # v10.40.11: ユーザー情報を取得（user_idも含む）
        user_id = None
        org_id = None
        with pool.connect() as conn:
            user_result = conn.execute(
                sqlalchemy.text("""
                    SELECT id, organization_id FROM users
                    WHERE chatwork_account_id = :account_id
                    LIMIT 1
                """),
                {"account_id": str(account_id)}
            ).fetchone()

            if user_result:
                # v10.40.15: users.id は UUID なので int 化しない
                user_id = str(user_result[0])
                org_id = str(user_result[1]) if user_result[1] else None
            else:
                # 組織が見つからない場合はデフォルト組織を使用
                org_result = conn.execute(
                    sqlalchemy.text("""
                        SELECT id FROM organizations LIMIT 1
                    """)
                ).fetchone()
                if org_result:
                    org_id = str(org_result[0])

        if not org_id:
            return {
                "success": False,
                "message": "組織情報が見つからなかったウル...🐺"
            }

        # v10.40.11: デバッグログ - キー/値の抽出
        kv = extract_persona_key_value(message)
        print(f"🔍 [bot_persona DEBUG] extracted key={kv.get('key')}, value={kv.get('value')}")

        # v10.40.11: デバッグログ - ホワイトリスト判定
        is_valid, reason = is_valid_bot_persona(message, kv.get("key", ""), kv.get("value", ""))
        print(f"🔍 [bot_persona DEBUG] is_valid_bot_persona() = {is_valid}, reason={reason}")

        # ボットペルソナを保存（user_idを渡してリダイレクト機能を有効化）
        result = save_bot_persona(
            pool=pool,
            org_id=org_id,
            message=message,
            account_id=str(account_id),
            sender_name=sender_name,
            user_id=user_id  # v10.40.11: リダイレクト用にuser_idを追加
        )

        # v10.40.11: 保存先をログ出力
        # 型安全のため明示的にDict[str, Any]に変換
        if not isinstance(result, dict):
            return {"success": False, "message": "予期しない戻り値ウル🐺"}

        redirected_to = result.get("redirected_to", "")
        if redirected_to:
            print(f"🔍 [bot_persona DEBUG] 実際の保存先: {redirected_to}")
        elif result.get("success"):
            print(f"🔍 [bot_persona DEBUG] 実際の保存先: bot_persona_memory")
        else:
            print(f"🔍 [bot_persona DEBUG] 実際の保存先: none (保存失敗)")

        return result

    except Exception as e:
        print(f"❌ ボットペルソナ保存エラー: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "message": f"ボット設定の保存中にエラーが発生したウル...🐺"
        }


async def _handle_query_long_term_memory(
    account_id: str,
    sender_name: str,
    target_user_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    v10.40.9: 長期記憶（人生軸・価値観）を取得

    アクセス制御:
    - 本人の記憶: 全て取得可能
    - 他ユーザーの記憶: ORG_SHARED のみ取得可能
    - PRIVATEスコープの記憶は本人以外には絶対に返さない
    """
    try:
        import sys
        import sqlalchemy
        main = sys.modules.get('main')
        if not main:
            return {"success": False, "message": "システムエラーが発生したウル🐺"}

        get_pool = getattr(main, 'get_pool')
        LongTermMemoryManager = getattr(main, 'LongTermMemoryManager')

        pool = get_pool()

        # v10.40.16: users.id が正しいカラム名（user_id ではない）
        with pool.connect() as conn:
            requester_result = conn.execute(
                sqlalchemy.text("""
                    SELECT id, organization_id FROM users
                    WHERE chatwork_account_id = :account_id
                    LIMIT 1
                """),
                {"account_id": str(account_id)}
            ).fetchone()

            if not requester_result:
                return {
                    "success": False,
                    "message": "ユーザー情報が見つからなかったウル...🐺"
                }

            # v10.40.15: users.id は UUID なので int 化しない
            requester_user_id = str(requester_result[0])
            org_id = str(requester_result[1]) if requester_result[1] else None

            if not org_id:
                return {
                    "success": False,
                    "message": "組織情報が見つからなかったウル...🐺"
                }

        # ターゲットユーザーを決定（指定がなければリクエスター自身）
        target_id = target_user_id if target_user_id else requester_user_id
        is_self_query = (target_id == requester_user_id)

        # 長期記憶を取得（アクセス制御付き）
        manager = LongTermMemoryManager(pool, org_id, target_id, sender_name)

        if is_self_query:
            # 本人の記憶は全て取得
            memories = manager.get_all()
            if not memories:
                return {
                    "success": True,
                    "message": f"🐺 {sender_name}さんの人生の軸はまだ登録されていないウル！\n\n「人生の軸として覚えて」と言ってくれたら覚えるウル！"
                }
            display = manager.format_for_display(show_scope=False)
            return {
                "success": True,
                "message": display
            }
        else:
            # 他ユーザーの記憶はORG_SHAREDのみ
            memories = manager.get_all_for_requester(requester_user_id)
            if not memories:
                return {
                    "success": True,
                    "message": "共有されている情報は見つからなかったウル🐺"
                }
            # 注意: 他ユーザーの記憶を表示する際は個人情報を匿名化
            display = f"🐺 共有されている情報ウル！\n\n"
            for m in memories:
                type_label = m.get("memory_type", "記憶")
                display += f"【{type_label}】\n{m['content']}\n\n"
            return {
                "success": True,
                "message": display
            }

    except Exception as e:
        print(f"❌ 長期記憶取得エラー: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "message": f"長期記憶の取得中にエラーが発生したウル...🐺"
        }


# =====================================================
# セッション継続ハンドラー
# v10.39.1: 脳のcore.pyの_continue_*メソッドから呼び出される
# シグネチャ: (message, room_id, account_id, sender_name, state_data) -> dict or str or None
# =====================================================

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

    handle_pending_task_followupを使用して不足情報を補完します。
    """
    try:
        import sys
        main = sys.modules.get('main')
        if not main:
            return {"message": "システムエラーが発生したウル🐺", "success": False}

        handle_pending_task_followup = getattr(main, 'handle_pending_task_followup')

        # handle_pending_task_followupを呼び出し
        result = handle_pending_task_followup(message, room_id, account_id, sender_name)

        if result:
            # タスク作成成功
            return {
                "message": result,
                "success": True,
                "task_created": True,
                "new_state": "normal",
            }
        else:
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
                if any(kw in message for kw in ["削除", "消", "以外", "全部", "全削除"]) or any(ch.isdigit() for ch in message):
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


# =====================================================
# 脳用ハンドラーラッパー関数
# v10.28.0: BrainIntegrationから呼び出される
# =====================================================

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
    }


# =====================================================
# v10.40.3: ポーリング処理ヘルパー関数
# check_reply_messages から抽出
# =====================================================

def validate_polling_message(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    ポーリングメッセージのバリデーションとフィールド抽出

    v10.40.3: check_reply_messages から抽出

    Args:
        msg: ChatWork APIから取得したメッセージ辞書

    Returns:
        バリデーション済みデータ辞書、または無効な場合None
        {
            "message_id": str,
            "body": str,
            "account_id": str or None,
            "sender_name": str,
            "send_time": int or None,
        }
    """
    if not isinstance(msg, dict):
        print(f"⚠️ 不正なメッセージデータ型: {type(msg)}")
        return None

    message_id = msg.get("message_id")
    if message_id is None:
        print(f"⚠️ message_idがNone")
        return None

    body = msg.get("body")
    if body is None:
        body = ""
        logger.debug("[バリデーション] bodyがNone")
    if not isinstance(body, str):
        logger.debug(f"[バリデーション] bodyが文字列ではない: type={type(body)}")
        body = str(body) if body else ""

    account_data = msg.get("account")
    if account_data is None or not isinstance(account_data, dict):
        logger.debug("[バリデーション] accountデータが不正")
        account_id = None
        sender_name = "ゲスト"
    else:
        account_id = account_data.get("account_id")
        sender_name = account_data.get("name", "ゲスト")

    send_time = msg.get("send_time")

    # デバッグログ（PII除去）
    logger.debug(f"[バリデーション] メッセージチェック: body_len={len(body)}")

    return {
        "message_id": message_id,
        "body": body,
        "account_id": account_id,
        "sender_name": sender_name,
        "send_time": send_time,
    }


def should_skip_polling_message(
    data: Dict[str, Any],
    five_minutes_ago: int,
    my_account_id: str,
) -> bool:
    """
    ポーリングメッセージをスキップすべきかチェック

    v10.40.3: check_reply_messages から抽出

    Args:
        data: validate_polling_messageの戻り値
        five_minutes_ago: 5分前のタイムスタンプ
        my_account_id: 自分のアカウントID

    Returns:
        スキップすべき場合True
    """
    import sys
    main = sys.modules.get('main')
    if not main:
        print("⚠️ [ポーリング] mainモジュールが見つかりません")
        return True

    is_mention_or_reply_to_soulkun = getattr(main, 'is_mention_or_reply_to_soulkun', None)
    should_ignore_toall = getattr(main, 'should_ignore_toall', None)
    is_processed = getattr(main, 'is_processed', None)

    message_id = data["message_id"]
    body = data["body"]
    account_id = data["account_id"]
    send_time = data["send_time"]

    # メンション/返信チェック
    try:
        is_mention_or_reply = is_mention_or_reply_to_soulkun(body) if body and is_mention_or_reply_to_soulkun else False
        print(f"   is_mention_or_reply: {is_mention_or_reply}")
    except Exception as e:
        print(f"   ❌ is_mention_or_reply_to_soulkun エラー: {e}")
        is_mention_or_reply = False

    # 5分以内のメッセージのみ処理
    if send_time is not None:
        try:
            if int(send_time) < five_minutes_ago:
                return True
        except (ValueError, TypeError) as e:
            print(f"⚠️ send_time変換エラー: {send_time}, error={e}")

    # 自分自身のメッセージを無視
    if account_id is not None and str(account_id) == my_account_id:
        return True

    # オールメンション（toall）の判定
    if should_ignore_toall and should_ignore_toall(body):
        print(f"   ⏭️ オールメンション（toall）のみのため無視")
        return True

    # メンションまたは返信を検出
    if not is_mention_or_reply:
        return True

    # 処理済みならスキップ
    try:
        if is_processed and is_processed(message_id):
            logger.debug("[スキップ判定] すでに処理済み")
            return True
    except Exception as e:
        logger.debug(f"[スキップ判定] 処理済みチェックエラー（続行）: {e}")

    return False


def process_polling_message(
    room_id: str,
    data: Dict[str, Any],
) -> int:
    """
    検出されたポーリングメッセージを処理

    v10.40.3: check_reply_messages から抽出
    Brain統合でメッセージを処理し、応答を送信

    Args:
        room_id: ルームID
        data: validate_polling_messageの戻り値

    Returns:
        処理した場合1、スキップした場合0
    """
    import sys
    from datetime import datetime

    main = sys.modules.get('main')
    if not main:
        print("⚠️ [ポーリング] mainモジュールが見つかりません")
        return 0

    # main.py関数の取得
    mark_as_processed = getattr(main, 'mark_as_processed', None)
    save_room_message = getattr(main, 'save_room_message', None)
    clean_chatwork_message = getattr(main, 'clean_chatwork_message', None)
    handle_pending_task_followup = getattr(main, 'handle_pending_task_followup', None)
    match_local_command = getattr(main, 'match_local_command', None)
    execute_local_command = getattr(main, 'execute_local_command', None)
    _get_brain_integration = getattr(main, '_get_brain_integration', None)
    _build_bypass_context = getattr(main, '_build_bypass_context', None)
    build_bypass_handlers_fn = getattr(main, 'build_bypass_handlers', None)
    send_chatwork_message = getattr(main, 'send_chatwork_message', None)
    USE_BRAIN_ARCHITECTURE = getattr(main, 'USE_BRAIN_ARCHITECTURE', False)
    JST = getattr(main, 'JST', None)

    message_id = data["message_id"]
    body = data["body"]
    account_id = data["account_id"]
    sender_name = data["sender_name"]
    send_time = data["send_time"]

    logger.debug("[ポーリング] メッセージ検出、処理開始")

    # ★★★ 2重処理防止: 即座にマーク ★★★
    if mark_as_processed:
        mark_as_processed(message_id, room_id)
        logger.debug("[ポーリング] 処理開始マーク完了")

    # メッセージをDBに保存
    try:
        if save_room_message and JST:
            save_room_message(
                room_id=room_id,
                message_id=message_id,
                account_id=account_id,
                account_name=sender_name,
                body=body,
                send_time=datetime.fromtimestamp(send_time, tz=JST) if send_time else None
            )
    except Exception as e:
        print(f"⚠️ メッセージ保存エラー（続行）: {e}")

    # メッセージをクリーニング
    try:
        clean_message = clean_chatwork_message(body) if body and clean_chatwork_message else ""
    except Exception as e:
        print(f"⚠️ メッセージクリーニングエラー: {e}")
        clean_message = body

    if not clean_message:
        return 1

    try:
        # ★★★ pending_taskのフォローアップを最初にチェック ★★★
        if handle_pending_task_followup:
            pending_response = handle_pending_task_followup(clean_message, room_id, account_id, sender_name)
            if pending_response:
                print(f"📋 pending_taskのフォローアップを処理")
                if send_chatwork_message:
                    send_chatwork_message(room_id, pending_response, None, False)
                return 1

        # =====================================================
        # v6.9.1: ローカルコマンド判定（API制限対策）
        # =====================================================
        if match_local_command and execute_local_command:
            local_action, local_groups = match_local_command(clean_message)
            if local_action:
                print(f"🏠 ローカルコマンド検出: {local_action}")
                local_response = execute_local_command(
                    local_action, local_groups,
                    account_id, sender_name, room_id
                )
                if local_response and send_chatwork_message:
                    send_chatwork_message(room_id, local_response, None, False)
                    return 1

        # =====================================================
        # v10.40: Brain統合（ai_commander + execute_action削除）
        # 設計原則「全入力は脳を通る」に準拠
        # =====================================================
        if USE_BRAIN_ARCHITECTURE and _get_brain_integration:
            try:
                integration = _get_brain_integration()
                if integration and integration.is_brain_enabled():
                    bypass_context = _build_bypass_context(room_id, account_id) if _build_bypass_context else {}
                    bypass_handlers = build_bypass_handlers_fn() if build_bypass_handlers_fn else {}

                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        result = loop.run_until_complete(
                            integration.process_message(
                                message=clean_message,
                                room_id=room_id,
                                account_id=account_id,
                                sender_name=sender_name,
                                fallback_func=None,
                                bypass_context=bypass_context,
                                bypass_handlers=bypass_handlers,
                            )
                        )
                    finally:
                        loop.close()

                    if result and result.success and result.message:
                        logger.debug(f"[ポーリング] Brain応答成功: brain={result.used_brain}, time={result.processing_time_ms}ms")
                        if send_chatwork_message:
                            send_chatwork_message(room_id, result.message, None, False)
                    else:
                        logger.debug("[ポーリング] Brain処理が応答なし")
                else:
                    logger.debug("[ポーリング] Brain統合が無効")
            except Exception as brain_e:
                logger.error(f"[ポーリング] Brain処理エラー: {brain_e}")
                import traceback
                traceback.print_exc()
        else:
            logger.debug("[ポーリング] USE_BRAIN_ARCHITECTURE=false, スキップ")

        return 1

    except Exception as e:
        logger.error(f"[ポーリング] メッセージ処理エラー: {e}")
        import traceback
        traceback.print_exc()
        return 0


def process_polling_room(
    room: Dict[str, Any],
    five_minutes_ago: int,
    my_account_id: str,
) -> Dict[str, int]:
    """
    ポーリングで1つのルームを処理

    v10.40.3: check_reply_messages から抽出

    Args:
        room: ルーム情報辞書
        five_minutes_ago: 5分前のタイムスタンプ
        my_account_id: 自分のアカウントID

    Returns:
        カウント辞書 {
            "processed_count": int,
            "skipped_my": int,
            "processed_rooms": int,
            "error_rooms": int,
            "skipped_messages": int,
        }
    """
    import sys

    main = sys.modules.get('main')
    if not main:
        print("⚠️ [ポーリング] mainモジュールが見つかりません")
        return {"processed_count": 0, "skipped_my": 0, "processed_rooms": 0, "error_rooms": 1, "skipped_messages": 0}

    get_room_messages = getattr(main, 'get_room_messages', None)

    counts = {
        "processed_count": 0,
        "skipped_my": 0,
        "processed_rooms": 0,
        "error_rooms": 0,
        "skipped_messages": 0,
    }

    room_id = None

    try:
        # ルームデータの検証
        if not isinstance(room, dict):
            print(f"⚠️ 不正なルームデータ型: {type(room)}")
            counts["error_rooms"] += 1
            return counts

        room_id = room.get("room_id")
        room_type = room.get("type")
        room_name = room.get("name", "不明")

        # room_idの検証
        if room_id is None:
            logger.debug("[ポーリング] room_idがNone")
            counts["error_rooms"] += 1
            return counts

        logger.debug(f"[ポーリング] ルームチェック開始: type={room_type}")

        # マイチャットをスキップ
        if room_type == "my":
            counts["skipped_my"] += 1
            logger.debug("[ポーリング] マイチャットをスキップ")
            return counts

        counts["processed_rooms"] += 1

        # メッセージを取得
        logger.debug("[ポーリング] get_room_messages呼び出し")

        try:
            messages = get_room_messages(room_id, force=True) if get_room_messages else []
        except Exception as e:
            logger.error(f"[ポーリング] メッセージ取得エラー: {e}")
            counts["error_rooms"] += 1
            return counts

        # messagesの検証
        if messages is None:
            logger.debug("[ポーリング] messagesがNone")
            messages = []

        if not isinstance(messages, list):
            logger.debug(f"[ポーリング] messagesが不正な型: {type(messages)}")
            messages = []

        logger.debug(f"[ポーリング] {len(messages)}件のメッセージを取得")

        # メッセージがない場合はスキップ
        if not messages:
            return counts

        for msg in messages:
            try:
                # バリデーション
                data = validate_polling_message(msg)
                if data is None:
                    counts["skipped_messages"] += 1
                    continue

                # スキップ判定
                if should_skip_polling_message(data, five_minutes_ago, my_account_id):
                    continue

                # 処理実行
                result = process_polling_message(room_id, data)
                counts["processed_count"] += result

            except Exception as e:
                logger.error(f"[ポーリング] メッセージ処理中に予期しないエラー: {e}")
                import traceback
                traceback.print_exc()
                counts["skipped_messages"] += 1
                continue

    except Exception as e:
        counts["error_rooms"] += 1
        logger.error(f"[ポーリング] ルーム処理中にエラー: {e}")
        import traceback
        traceback.print_exc()

    return counts


# =====================================================
# エクスポート
# =====================================================

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
