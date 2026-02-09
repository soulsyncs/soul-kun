"""services/org_knowledge_actions.py - 組織図・知識・日次振り返りハンドラー

Phase 11-5d: main.pyから抽出された組織図クエリ・知識管理・日次振り返り。

依存: services/person_org.py, infra/db.py
"""

import os
from datetime import datetime
import traceback

from infra.db import get_pool, get_secret, get_db_connection
from services.person_org import (
    get_org_chart_overview,
    search_department_by_name,
    get_department_members,
)
from services.knowledge_ops import _get_knowledge_handler

from handlers.registry import SYSTEM_CAPABILITIES

# モデル設定
MODELS = {
    "default": "google/gemini-3-flash-preview",
    "commander": "google/gemini-3-flash-preview",
}

# Phase 3 ナレッジ設定
PHASE3_KNOWLEDGE_CONFIG = {
    "api_url": os.getenv(
        "KNOWLEDGE_SEARCH_API_URL",
        "https://soulkun-api-898513057014.asia-northeast1.run.app/api/v1/knowledge/search"
    ),
    "enabled": os.getenv("ENABLE_PHASE3_KNOWLEDGE", "true").lower() == "true",
    "timeout": float(os.getenv("PHASE3_TIMEOUT", "30")),
    "similarity_threshold": float(os.getenv("PHASE3_SIMILARITY_THRESHOLD", "0.5")),
    "organization_id": os.getenv("PHASE3_ORGANIZATION_ID", "5f98365f-e7c5-4f48-9918-7fe9aabae5df"),
    "keyword_weight": float(os.getenv("PHASE3_KEYWORD_WEIGHT", "0.4")),
    "vector_weight": float(os.getenv("PHASE3_VECTOR_WEIGHT", "0.6")),
}

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"



def handle_query_org_chart(params, room_id, account_id, sender_name, context=None):
    """組織図クエリのハンドラー（Phase 3.5）"""
    query_type = params.get("query_type", "overview")
    department = params.get("department", "")

    if query_type == "overview":
        # 組織図の全体構造を表示
        departments = get_org_chart_overview()
        if not departments:
            return "🤔 組織図データがまだ登録されていないウル..."

        # 階層構造で表示
        response = "🏢 **組織図**ウル！\n\n"

        for dept in departments:
            level = dept["level"]
            indent = "　" * (level - 1)
            member_info = f"（{dept['member_count']}名）" if dept["member_count"] > 0 else ""
            response += f"{indent}📁 {dept['name']}{member_info}\n"

        response += f"\n合計: {len(departments)}部署"
        return response

    elif query_type == "members":
        # 部署のメンバー一覧
        if not department:
            return "🤔 どの部署のメンバーを知りたいウル？部署名を教えてほしいウル！"

        dept_name, members = get_department_members(department)
        if dept_name is None:
            return f"🤔 「{department}」という部署が見つからなかったウル..."

        if not members:
            return f"📁 **{dept_name}** には現在メンバーがいないウル"

        response = f"👥 **{dept_name}のメンバー**ウル！\n\n"
        for m in members:
            concurrent_mark = "【兼】" if m.get("is_concurrent") else ""
            position_str = f"（{m['position']}）" if m.get("position") else ""
            emp_type_str = f" [{m['employment_type']}]" if m.get("employment_type") else ""
            response += f"・{concurrent_mark}{m['name']}{position_str}{emp_type_str}\n"

        response += f"\n合計: {len(members)}名"
        return response

    elif query_type == "detail":
        # 部署の詳細情報
        if not department:
            return "🤔 どの部署の詳細を知りたいウル？部署名を教えてほしいウル！"

        depts = search_department_by_name(department)
        if not depts:
            return f"🤔 「{department}」という部署が見つからなかったウル..."

        dept = depts[0]
        dept_name, members = get_department_members(dept["name"])

        response = f"📁 **{dept['name']}** の詳細ウル！\n\n"
        response += f"・階層レベル: {dept['level']}\n"
        response += f"・所属人数: {dept['member_count']}名\n"

        if members:
            response += f"\n👥 **メンバー**:\n"
            for m in members[:10]:  # 最大10名まで表示
                concurrent_mark = "【兼】" if m.get("is_concurrent") else ""
                position_str = f"（{m['position']}）" if m.get("position") else ""
                response += f"　・{concurrent_mark}{m['name']}{position_str}\n"
            if len(members) > 10:
                response += f"　...他{len(members) - 10}名"

        return response

    return "🤔 組織図の検索方法がわからなかったウル..."

def handle_api_limitation(params, room_id, account_id, sender_name, context=None):
    """
    API制約により実装不可能な機能を要求された時のハンドラー
    
    ChatWork APIの制約により、タスクの編集・削除は実装できない。
    ユーザーに適切な説明を返す。
    """
    # contextからどの機能が呼ばれたか特定
    action = context.get("action", "") if context else ""
    
    # 機能カタログからメッセージを取得
    capability = SYSTEM_CAPABILITIES.get(action, {})
    limitation_message = capability.get("limitation_message", "この機能")
    
    # ソウルくんキャラクターで説明
    response = f"""ごめんウル！🐺

{limitation_message}は、ChatWorkの仕様でソウルくんからはできないウル…

【ソウルくんができること】
✅ タスクの作成（「〇〇さんに△△をお願いして」）
✅ タスクの完了（「〇〇のタスク完了にして」）
✅ タスクの検索（「自分のタスク教えて」）
✅ リマインド（期限前に自動でお知らせ）
✅ 遅延管理（期限超過タスクを管理部に報告）

【{limitation_message}が必要な場合】
ChatWorkアプリで直接操作してほしいウル！
タスクを開いて、編集や削除ができるウル🐺

もし「このタスクのリマインドだけ止めて」ならソウルくんでできるウル！"""
    
    return response

def handle_query_company_knowledge(params, room_id, account_id, sender_name):
    """
    会社知識の参照ハンドラー（Phase 3統合版）

    統合ナレッジ検索を使用して、就業規則・マニュアル等から回答を生成する。
    旧システム（soulkun_knowledge）とPhase 3（Pinecone）を自動的に切り替え。

    Args:
        params: {"query": "検索したい内容"}
        room_id: ChatWorkルームID
        account_id: ユーザーのアカウントID
        sender_name: 送信者名

    Returns:
        回答テキスト

    v10.24.7: handlers/knowledge_handler.py に分割
    v10.32.0: フォールバック削除（ハンドラー必須化）
    """
    return _get_knowledge_handler().handle_query_company_knowledge(params, room_id, account_id, sender_name)

def handle_daily_reflection(params, room_id, account_id, sender_name, context=None):
    """daily_reflection_logs"""
    print(f"handle_daily_reflection : room_id={room_id}, account_id={account_id}")
    
    try:
        reflection_text = params.get("reflection_text", "")
        if not reflection_text:
            return {"success": False, "message": "..."}
        
        from datetime import datetime
        from sqlalchemy import text
        
        conn = get_db_connection()
        if not conn:
            return {"success": False, "message": "..."}
        
        try:
            insert_query = text("""
                INSERT INTO daily_reflection_logs 
                (account_id, recorded_at, reflection_text, room_id, message_id, created_at)
                VALUES (:account_id, :recorded_at, :reflection_text, :room_id, :message_id, NOW())
            """)
            
            conn.execute(insert_query, {
                "account_id": str(account_id),
                "recorded_at": datetime.now().date(),
                "reflection_text": reflection_text,
                "room_id": str(room_id),
                "message_id": context.get("message_id", "") if context else ""
            })
            conn.commit()
            
            print(f": account_id={account_id}")
            return {"success": True, "message": "\n"}
            
        finally:
            conn.close()
            
    except Exception as e:
        print(f"handle_daily_reflection : {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "message": "..."}
