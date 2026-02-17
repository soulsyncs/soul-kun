# lib/brain/handler_wrappers/memory_handlers.py
"""
メモリ・ペルソナ関連ハンドラー

長期記憶（人生軸・価値観）の保存・取得、ボットペルソナ設定を処理する。
"""

from typing import Dict, Any, Optional


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
