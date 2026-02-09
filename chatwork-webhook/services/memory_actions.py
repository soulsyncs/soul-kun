"""services/memory_actions.py - メモリ・知識アクションハンドラー

Phase 11-5a: main.pyから抽出された記憶・知識管理のアクションハンドラー。

依存: services/person_org.py, services/proposal_actions.py, infra/db.py
"""

import json
import sqlalchemy
import traceback

from infra.db import get_pool
from infra.helpers import is_admin
from services.person_org import (
    save_person_attribute,
    get_person_info,
    normalize_person_name,
    search_person_by_partial_name,
    get_all_persons_summary,
    delete_person,
    resolve_person_name,
    parse_attribute_string,
)
from services.proposal_actions import create_proposal, report_proposal_to_admin
from services.knowledge_ops import _get_knowledge_handler
from services.task_ops import log_analytics_event

# 長期記憶
try:
    from lib.long_term_memory import (
        is_long_term_memory_request,
        save_long_term_memory,
        LongTermMemoryManager,
    )
    USE_LONG_TERM_MEMORY = True
except ImportError:
    USE_LONG_TERM_MEMORY = False

# ボットペルソナ記憶（v10.40.9: handle_list_knowledge統合により
# BotPersonaMemoryManagerはknowledge_handler.pyに移動）

# BOT名パターン
BOT_NAME_PATTERNS = [
    "ソウルくん", "ソウル君", "ソウル", "そうるくん", "そうる",
    "soulkun", "soul-kun", "soul"
]



def handle_save_memory(params, room_id, account_id, sender_name, context=None):
    """
    人物情報を記憶するハンドラー（文字列形式と辞書形式の両方に対応）

    v10.25.0: 提案制を追加
    - 管理者（カズさん）からは即時保存
    - 他のスタッフからは提案として記録し、確認後に保存

    v10.40.13: brain無効時も長期記憶判定を実行
    - is_long_term_memory_request() でパターン検出
    - 人生軸・価値観 → user_long_term_memory へ保存
    - それ以外 → 従来の person_attributes へ保存
    """
    print(f"📝 handle_save_memory 開始")
    print(f"   params: {json.dumps(params, ensure_ascii=False)}")

    # =====================================================
    # v10.40.13: 長期記憶判定（brain無効時対応）
    # =====================================================
    original_message = ""
    if context:
        if isinstance(context, dict):
            original_message = context.get("original_message", "")
        elif hasattr(context, "original_message"):
            original_message = getattr(context, "original_message", "")

    print(f"🔍 [save_memory DEBUG] msg={original_message[:60]}..." if len(original_message) > 60 else f"🔍 [save_memory DEBUG] msg={original_message}")

    # 長期記憶パターンを検出
    is_long_term = False
    if USE_LONG_TERM_MEMORY and original_message:
        is_long_term = is_long_term_memory_request(original_message)
    print(f"🔍 [save_memory DEBUG] is_long_term={is_long_term}")

    if is_long_term:
        # 長期記憶として保存
        print(f"🔍 [save_memory DEBUG] save_to=user_long_term_memory")
        try:
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
                    print(f"🔍 [save_memory DEBUG] user not found")
                    return "🤔 ユーザー情報が見つからなかったウル...登録状況を確認してほしいウル🐺"

                # v10.40.15: users.id は UUID なので int 化しない
                user_id = str(user_result[0])
                org_id = str(user_result[1]) if user_result[1] else None

                if not org_id:
                    print(f"🔍 [save_memory DEBUG] org not found")
                    return "🤔 組織情報が見つからなかったウル...🐺"

            # 長期記憶を保存
            result = save_long_term_memory(
                pool=pool,
                org_id=org_id,
                user_id=user_id,
                user_name=sender_name,
                message=original_message
            )

            print(f"🔍 [save_memory DEBUG] long_term_result success={result.get('success', False)}")

            if result.get("success"):
                return result.get("message", "大事な軸、ちゃんと覚えたウル！🐺✨")
            else:
                return result.get("message", "🤔 保存できなかったウル...もう一度試してほしいウル！")

        except Exception as e:
            print(f"❌ 長期記憶保存エラー: {e}")
            import traceback
            traceback.print_exc()
            return f"🤔 長期記憶の保存中にエラーが発生したウル...🐺"

    # =====================================================
    # 従来の人物情報記憶処理（長期記憶ではない場合）
    # =====================================================
    print(f"🔍 [save_memory DEBUG] save_to=person_attributes")

    attributes = params.get("attributes", [])
    print(f"   attributes: {attributes}")

    if not attributes:
        return "🤔 何を覚えればいいかわからなかったウル...もう少し詳しく教えてほしいウル！"

    # v10.25.0: 管理者判定
    is_admin_user = is_admin(account_id)

    saved = []
    proposed = []

    def process_attribute(person, attr_type, attr_value):
        """属性を処理（管理者なら即時保存、それ以外は提案）"""
        if not person or not attr_value:
            return False
        if person.lower() in [bn.lower() for bn in BOT_NAME_PATTERNS]:
            print(f"   → スキップ: ボット名パターンに一致")
            return False

        if is_admin_user:
            # 管理者は即時保存
            save_person_attribute(person, attr_type, attr_value, "command")
            saved.append(f"{person}さんの{attr_type}「{attr_value}」")
            print(f"   → 管理者: 即時保存成功: {person}さんの{attr_type}")
        else:
            # スタッフは提案として記録
            # valueにJSON形式で{type, value}を保存
            proposal_value = json.dumps({"type": attr_type, "value": attr_value}, ensure_ascii=False)
            proposal_id = create_proposal(
                proposed_by_account_id=account_id,
                proposed_by_name=sender_name,
                proposed_in_room_id=room_id,
                category="memory",  # 人物情報用のカテゴリ
                key=person,         # 人物名
                value=proposal_value
            )
            if proposal_id:
                # 管理者に通知（裏で）
                try:
                    # v10.25.0: category='memory'を渡して人物情報用メッセージに
                    report_proposal_to_admin(proposal_id, sender_name, person, proposal_value, category="memory")
                except Exception as e:
                    print(f"⚠️ 管理部への報告エラー: {e}")
                proposed.append(f"{person}さんの{attr_type}「{attr_value}」")
                print(f"   → スタッフ: 提案として記録: {person}さんの{attr_type}, ID={proposal_id}")
        return True

    for attr in attributes:
        print(f"   処理中のattr: {attr} (型: {type(attr).__name__})")

        # ★ 文字列形式の場合はパースする
        if isinstance(attr, str):
            print(f"   → 文字列形式を検出、パース開始")
            parsed_attrs = parse_attribute_string(attr)
            print(f"   → パース結果: {parsed_attrs}")

            for parsed in parsed_attrs:
                person = parsed.get("person", "")
                attr_type = parsed.get("type", "メモ")
                attr_value = parsed.get("value", "")
                print(f"   person='{person}', type='{attr_type}', value='{attr_value}'")
                process_attribute(person, attr_type, attr_value)
            continue

        # ★ 辞書形式の場合は従来通り処理
        if isinstance(attr, dict):
            person = attr.get("person", "")
            attr_type = attr.get("type", "メモ")
            attr_value = attr.get("value", "")
            print(f"   person='{person}', type='{attr_type}', value='{attr_value}'")
            process_attribute(person, attr_type, attr_value)
        else:
            print(f"   ⚠️ 未対応の型: {type(attr).__name__}")

    # 分析ログ記録
    if saved or proposed:
        log_analytics_event(
            event_type="memory_saved" if saved else "memory_proposed",
            actor_account_id=account_id,
            actor_name=sender_name,
            room_id=room_id,
            event_data={
                "saved_items": saved,
                "proposed_items": proposed,
                "original_params": params
            }
        )

    # レスポンス
    if saved:
        return f"✅ 覚えたウル！📝\n" + "\n".join([f"・{s}" for s in saved])
    elif proposed:
        # v10.25.0: スタッフ向けメッセージ（ソウルくんが確認）
        return f"教えてくれてありがとウル！🐺\n\nソウルくんが会社として問題ないか確認するウル！\n確認できたら覚えるウル！✨\n\n" + "\n".join([f"・{s}" for s in proposed])
    return "🤔 覚えられなかったウル..."

def handle_query_memory(params, room_id, account_id, sender_name, context=None):
    """人物情報を検索するハンドラー"""
    print(f"🔍 handle_query_memory 開始")
    print(f"   params: {params}")
    
    is_all = params.get("is_all_persons", False)
    persons = params.get("persons", [])
    matched = params.get("matched_persons", [])
    original_query = params.get("original_query", "")
    
    print(f"   is_all: {is_all}")
    print(f"   persons: {persons}")
    print(f"   matched: {matched}")
    print(f"   original_query: {original_query}")
    
    if is_all:
        all_persons = get_all_persons_summary()
        if all_persons:
            response = "📋 **覚えている人たち**ウル！🐕✨\n\n"
            for p in all_persons:
                attrs = p["attributes"] if p["attributes"] else "（まだ詳しいことは知らないウル）"
                response += f"・**{p['name']}さん**: {attrs}\n"
            # 分析ログ記録
            log_analytics_event(
                event_type="memory_queried",
                event_subtype="all_persons",
                actor_account_id=account_id,
                actor_name=sender_name,
                room_id=room_id,
                event_data={
                    "query_type": "all",
                    "result_count": len(all_persons)
                }
            )
            return response
        return "🤔 まだ誰のことも覚えていないウル..."
    
    target_persons = matched if matched else persons
    if not target_persons and original_query:
        matches = search_person_by_partial_name(original_query)
        if matches:
            target_persons = matches
    
    if target_persons:
        responses = []
        for person_name in target_persons:
            resolved_name = resolve_person_name(person_name)
            info = get_person_info(resolved_name)
            if info:
                response = f"📋 **{resolved_name}さん**について覚えていることウル！\n\n"
                if info["attributes"]:
                    for attr in info["attributes"]:
                        response += f"・{attr['type']}: {attr['value']}\n"
                else:
                    response += "（まだ詳しいことは知らないウル）"
                responses.append(response)
            else:
                # ★★★ v6.8.6: 正規化した名前でも検索 ★★★
                normalized_name = normalize_person_name(person_name)
                partial_matches = search_person_by_partial_name(normalized_name)
                if partial_matches:
                    for match in partial_matches[:1]:
                        match_info = get_person_info(match)
                        if match_info:
                            response = f"📋 **{match}さん**について覚えていることウル！\n"
                            response += f"（「{person_name}」で検索したウル）\n\n"
                            for attr in match_info["attributes"]:
                                response += f"・{attr['type']}: {attr['value']}\n"
                            responses.append(response)
                            break
                else:
                    responses.append(f"🤔 {person_name}さんについてはまだ何も覚えていないウル...")
        # 分析ログ記録
        log_analytics_event(
            event_type="memory_queried",
            event_subtype="specific_persons",
            actor_account_id=account_id,
            actor_name=sender_name,
            room_id=room_id,
            event_data={
                "query_type": "specific",
                "queried_persons": target_persons,
                "result_count": len(responses)
            }
        )
        return "\n\n".join(responses)
    
    return None

def handle_delete_memory(params, room_id, account_id, sender_name, context=None):
    """人物情報を削除するハンドラー"""
    persons = params.get("persons", [])
    matched = params.get("matched_persons", persons)
    
    if not persons and not matched:
        return "🤔 誰の記憶を削除すればいいかわからなかったウル..."
    
    target_persons = matched if matched else persons
    resolved_persons = [resolve_person_name(p) for p in target_persons]
    
    deleted = []
    not_found = []
    for person_name in resolved_persons:
        if delete_person(person_name):
            deleted.append(person_name)
        else:
            not_found.append(person_name)
    
    response_parts = []
    if deleted:
        names = "、".join([f"{n}さん" for n in deleted])
        response_parts.append(f"✅ {names}の記憶をすべて削除したウル！🗑️")
    if not_found:
        names = "、".join([f"{n}さん" for n in not_found])
        response_parts.append(f"🤔 {names}の記憶は見つからなかったウル...")
    
    return "\n".join(response_parts) if response_parts else "🤔 削除できなかったウル..."

def handle_learn_knowledge(params, room_id, account_id, sender_name):
    """
    知識を学習するハンドラー
    - 管理者（カズさん）からは即時反映
    - 他のスタッフからは提案として受け付け、管理部に報告

    v10.24.7: handlers/knowledge_handler.py に移動済み
    """
    return _get_knowledge_handler().handle_learn_knowledge(params, room_id, account_id, sender_name)

def handle_forget_knowledge(params, room_id, account_id, sender_name):
    """
    知識を削除するハンドラー（管理者のみ）

    v10.24.7: handlers/knowledge_handler.py に移動済み
    """
    return _get_knowledge_handler().handle_forget_knowledge(params, room_id, account_id, sender_name)

def handle_list_knowledge(params, room_id, account_id, sender_name):
    """
    学習した知識の一覧を表示するハンドラー

    v10.24.7: handlers/knowledge_handler.py に分割
    v10.32.0: フォールバック削除（ハンドラー必須化）
    v10.40.9: メモリ分離対応（ハンドラーに統合）
    """
    return _get_knowledge_handler().handle_list_knowledge(params, room_id, account_id, sender_name)
