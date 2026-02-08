"""services/task_ops.py - タスクDB操作・ChatWorkタスク管理

Phase 11-4a: main.pyから抽出されたタスク関連のDB操作・API連携。

依存: infra/db.py (get_pool, get_secret), infra/chatwork_api.py (call_chatwork_api_with_retry)
"""

import os
import re
import sqlalchemy

from infra.db import get_pool, get_secret
from infra.chatwork_api import call_chatwork_api_with_retry

from lib import (
    extract_task_subject,
    clean_chatwork_tags,
    prepare_task_display_text,
    validate_summary,
)

from lib import (
    get_user_primary_department as lib_get_user_primary_department,
)

from handlers.task_handler import TaskHandler as _NewTaskHandler


def _escape_ilike(value: str) -> str:
    """ILIKEメタキャラクタをエスケープ"""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# テナントID（CLAUDE.md 鉄則#1: 全クエリにorganization_idフィルター必須）
_ORGANIZATION_ID = os.getenv("PHASE3_ORGANIZATION_ID", "5f98365f-e7c5-4f48-9918-7fe9aabae5df")
MEMORY_DEFAULT_ORG_ID = _ORGANIZATION_ID
_task_handler = None



def _get_task_handler():
    """TaskHandlerのシングルトンインスタンスを取得"""
    global _task_handler
    if _task_handler is None:
        _task_handler = _NewTaskHandler(
            get_pool=get_pool,
            get_secret=get_secret,
            call_chatwork_api_with_retry=call_chatwork_api_with_retry,
            extract_task_subject=extract_task_subject,
            clean_chatwork_tags=clean_chatwork_tags,
            prepare_task_display_text=prepare_task_display_text,
            validate_summary=validate_summary,
            get_user_primary_department=lib_get_user_primary_department,
            use_text_utils=True,
            organization_id=_ORGANIZATION_ID
        )
    return _task_handler

def add_task(title, description=None, priority=0, due_date=None):
    pool = get_pool()
    with pool.begin() as conn:
        result = conn.execute(
            sqlalchemy.text("""
                INSERT INTO tasks (title, description, priority, due_date)
                VALUES (:title, :description, :priority, :due_date) RETURNING id
            """),
            {"title": title, "description": description, "priority": priority, "due_date": due_date}
        )
        return result.fetchone()[0]

def get_tasks(status=None):
    pool = get_pool()
    with pool.connect() as conn:
        if status:
            result = conn.execute(
                sqlalchemy.text("SELECT id, title, status, priority, due_date FROM tasks WHERE status = :status ORDER BY priority DESC, created_at DESC"),
                {"status": status}
            )
        else:
            result = conn.execute(
                sqlalchemy.text("SELECT id, title, status, priority, due_date FROM tasks ORDER BY priority DESC, created_at DESC")
            )
        return result.fetchall()

def update_task_status(task_id, status):
    pool = get_pool()
    with pool.begin() as conn:
        conn.execute(
            sqlalchemy.text("UPDATE tasks SET status = :status, updated_at = CURRENT_TIMESTAMP WHERE id = :id"),
            {"status": status, "id": task_id}
        )

def delete_task(task_id):
    pool = get_pool()
    with pool.begin() as conn:
        conn.execute(sqlalchemy.text("DELETE FROM tasks WHERE id = :id"), {"id": task_id})

def get_chatwork_account_id_by_name(name, organization_id: str = None):
    """担当者名からChatWorkアカウントIDを取得（敬称除去・スペース正規化対応）

    v10.30.0: 10の鉄則準拠 - organization_idフィルタ必須化
    """
    if organization_id is None:
        organization_id = MEMORY_DEFAULT_ORG_ID

    pool = get_pool()

    # ★ 敬称を除去（さん、くん、ちゃん、様、氏）
    clean_name = re.sub(r'(さん|くん|ちゃん|様|氏)$', '', name.strip())
    # ★ スペースを除去して正規化（半角・全角両方）
    normalized_name = clean_name.replace(' ', '').replace('　', '')
    print(f"👤 担当者検索: 入力='{name}' → クリーニング後='{clean_name}' → 正規化='{normalized_name}'")
    
    with pool.connect() as conn:
        # 完全一致で検索（クリーニング後の名前）
        result = conn.execute(
            sqlalchemy.text("""
                SELECT account_id FROM chatwork_users
                WHERE organization_id = :org_id AND name = :name
                LIMIT 1
            """),
            {"org_id": organization_id, "name": clean_name}
        ).fetchone()
        if result:
            print(f"✅ 完全一致で発見: {clean_name} → {result[0]}")
            return result[0]

        # 部分一致で検索（クリーニング後の名前）
        result = conn.execute(
            sqlalchemy.text("""
                SELECT account_id, name FROM chatwork_users
                WHERE organization_id = :org_id AND name ILIKE :pattern ESCAPE '\\'
                LIMIT 1
            """),
            {"org_id": organization_id, "pattern": f"%{_escape_ilike(clean_name)}%"}
        ).fetchone()
        if result:
            print(f"✅ 部分一致で発見: {clean_name} → {result[0]} ({result[1]})")
            return result[0]

        # ★ スペース除去して正規化した名前で検索（NEW）
        # DBの名前からもスペースを除去して比較
        result = conn.execute(
            sqlalchemy.text("""
                SELECT account_id, name FROM chatwork_users
                WHERE organization_id = :org_id
                  AND REPLACE(REPLACE(name, ' ', ''), '　', '') ILIKE :pattern ESCAPE '\\'
                LIMIT 1
            """),
            {"org_id": organization_id, "pattern": f"%{_escape_ilike(normalized_name)}%"}
        ).fetchone()
        if result:
            print(f"✅ 正規化検索で発見: {normalized_name} → {result[0]} ({result[1]})")
            return result[0]

        # 元の名前でも検索（念のため）
        if clean_name != name:
            result = conn.execute(
                sqlalchemy.text("""
                    SELECT account_id, name FROM chatwork_users
                    WHERE organization_id = :org_id AND name ILIKE :pattern ESCAPE '\\'
                    LIMIT 1
                """),
                {"org_id": organization_id, "pattern": f"%{_escape_ilike(name)}%"}
            ).fetchone()
            if result:
                print(f"✅ 元の名前で部分一致: {name} → {result[0]} ({result[1]})")
                return result[0]

        print(f"❌ 担当者が見つかりません: {name} (クリーニング後: {clean_name}, 正規化: {normalized_name})")
        return None

def create_chatwork_task(room_id, task_body, assigned_to_account_id, limit=None):
    """
    ChatWork APIでタスクを作成（リトライ機構付き）

    v10.24.4: handlers/task_handler.py に移動済み
    """
    return _get_task_handler().create_chatwork_task(room_id, task_body, assigned_to_account_id, limit)

def complete_chatwork_task(room_id, task_id):
    """
    ChatWork APIでタスクを完了にする（リトライ機構付き）

    v10.24.4: handlers/task_handler.py に移動済み
    """
    return _get_task_handler().complete_chatwork_task(room_id, task_id)

def search_tasks_from_db(room_id, assigned_to_account_id=None, assigned_by_account_id=None, status="open",
                          enable_dept_filter=False, organization_id=None, search_all_rooms=False):
    """DBからタスクを検索

    v10.24.4: handlers/task_handler.py に移動済み
    v10.54.2: 未定義関数参照を修正（get_user_id_func/get_accessible_departments_funcはオプション）
    """
    return _get_task_handler().search_tasks_from_db(
        room_id, assigned_to_account_id, assigned_by_account_id, status,
        enable_dept_filter, organization_id, search_all_rooms,
        get_user_id_func=None, get_accessible_departments_func=None
    )

def update_task_status_in_db(task_id, status):
    """
    DBのタスクステータスを更新

    v10.24.4: handlers/task_handler.py に移動済み
    """
    return _get_task_handler().update_task_status_in_db(task_id, status)

def save_chatwork_task_to_db(task_id, room_id, assigned_by_account_id, assigned_to_account_id, body, limit_time):
    """
    ChatWorkタスクをデータベースに保存

    v10.24.4: handlers/task_handler.py に移動済み
    """
    return _get_task_handler().save_chatwork_task_to_db(
        task_id, room_id, assigned_by_account_id, assigned_to_account_id, body, limit_time
    )

def log_analytics_event(event_type, actor_account_id, actor_name, room_id, event_data, success=True, error_message=None, event_subtype=None):
    """
    分析用イベントログを記録

    v10.24.4: handlers/task_handler.py に移動済み
    """
    _get_task_handler().log_analytics_event(
        event_type=event_type,
        actor_account_id=actor_account_id,
        actor_name=actor_name,
        room_id=room_id,
        event_data=event_data,
        success=success,
        error_message=error_message,
        event_subtype=event_subtype
    )
