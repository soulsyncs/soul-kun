from flask import Flask, request as flask_request, jsonify

app = Flask(__name__)
from google.cloud import firestore
import httpx
import re
import os
from datetime import datetime, timedelta, timezone
import pg8000
import sqlalchemy
import json
import traceback

# ★★★ v10.31.1: Phase D - 接続設定集約 ★★★
from lib.db import get_db_pool as _lib_get_db_pool, get_db_connection as _lib_get_db_connection
from lib.secrets import get_secret_cached as _lib_get_secret
from lib.config import get_settings

# ★★★ v10.18.1: lib/テキスト処理ユーティリティ ★★★
from lib import (
    clean_chatwork_tags as lib_clean_chatwork_tags,
    prepare_task_display_text as lib_prepare_task_display_text,
    remove_greetings as lib_remove_greetings,
    validate_summary as lib_validate_summary,
    extract_task_subject as lib_extract_task_subject,
)

# ★★★ v10.18.1: ユーザーユーティリティ（Phase 3.5対応） ★★★
from lib import (
    get_user_primary_department as lib_get_user_primary_department,
)

PROJECT_ID = "soulkun-production"
db = firestore.Client(project=PROJECT_ID)


# 会話履歴の設定
MAX_HISTORY_COUNT = 100      # 100件に増加
HISTORY_EXPIRY_HOURS = 720   # 30日（720時間）に延長

# OpenRouter設定
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# 最新モデル設定（2025年12月時点）
MODELS = {
    "default": "openai/gpt-4o",
    "commander": "openai/gpt-4o",  # 司令塔AI
}

# ボット自身の名前パターン
BOT_NAME_PATTERNS = [
    "ソウルくん", "ソウル君", "ソウル", "そうるくん", "そうる",
    "soulkun", "soul-kun", "soul"
]

# ソウルくんのaccount_id
MY_ACCOUNT_ID = "10909425"
BOT_ACCOUNT_ID = "10909425"  # Phase 1-B用

# Cloud SQL接続プール
_pool = None

# JST タイムゾーン
JST = timezone(timedelta(hours=9))

def _escape_ilike(value: str) -> str:
    """ILIKEメタキャラクタをエスケープ"""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

# ChatWork API ヘッダー取得関数
def get_chatwork_headers():
    return {"X-ChatWorkToken": get_secret("SOULKUN_CHATWORK_TOKEN")}

HEADERS = None  # 遅延初期化用

# =============================================================================
# Phase D: 接続設定集約（v10.31.1）
# =============================================================================

def get_secret(secret_id):
    """Secret Managerからシークレットを取得"""
    return _lib_get_secret(secret_id)

def get_db_password():
    """DBパスワードを取得"""
    return get_secret("cloudsql-password")

def get_db_connection():
    """Phase 1-B用: pg8000接続を返す"""
    return _lib_get_db_connection()

def get_pool():
    """Cloud SQL接続プールを取得"""
    return _lib_get_db_pool()

def clean_chatwork_message(body):
    """ChatWorkメッセージをクリーニング
    
    堅牢なエラーハンドリング版
    """
    # Noneチェック
    if body is None:
        return ""
    
    # 型チェック
    if not isinstance(body, str):
        try:
            body = str(body)
        except:
            return ""
    
    # 空文字チェック
    if not body:
        return ""
    
    try:
        clean_message = body
        clean_message = re.sub(r'\[To:\d+\]\s*[^\n\[]*(?:さん|くん|ちゃん|様|氏)?', '', clean_message)
        clean_message = re.sub(r'\[rp aid=\d+[^\]]*\]\[/rp\]', '', clean_message)  # より柔軟なパターン
        clean_message = re.sub(r'\[/?[a-zA-Z]+\]', '', clean_message)
        clean_message = re.sub(r'\[.*?\]', '', clean_message)
        clean_message = clean_message.strip()
        clean_message = re.sub(r'\s+', ' ', clean_message)
        return clean_message
    except Exception as e:
        print(f"⚠️ clean_chatwork_message エラー: {e}")
        return body  # エラー時は元のメッセージを返す


def is_mention_or_reply_to_soulkun(body):
    """ソウルくんへのメンションまたは返信かどうかを判断
    
    堅牢なエラーハンドリング版
    """
    # Noneチェック
    if body is None:
        return False
    
    # 型チェック
    if not isinstance(body, str):
        try:
            body = str(body)
        except:
            return False
    
    # 空文字チェック
    if not body:
        return False
    
    try:
        # メンションパターン
        if f"[To:{MY_ACCOUNT_ID}]" in body:
            return True
        
        # 返信ボタンパターン: [rp aid=10909425 to=...]
        # 修正: [/rp]のチェックを削除（実際のフォーマットには含まれない）
        if f"[rp aid={MY_ACCOUNT_ID}" in body:
            return True
        
        return False
    except Exception as e:
        print(f"⚠️ is_mention_or_reply_to_soulkun エラー: {e}")
        return False


# ===== データベース操作関数 =====

# テナントID（CLAUDE.md 鉄則#1: 全クエリにorganization_idフィルター必須）
_ORGANIZATION_ID = os.getenv("PHASE3_ORGANIZATION_ID", "5f98365f-e7c5-4f48-9918-7fe9aabae5df")

def get_or_create_person(name):
    """人物を取得、なければ作成してIDを返す（UUID文字列）"""
    pool = get_pool()
    with pool.begin() as conn:
        result = conn.execute(
            sqlalchemy.text("SELECT id FROM persons WHERE name = :name AND organization_id = :org_id"),
            {"name": name, "org_id": _ORGANIZATION_ID}
        ).fetchone()
        if result:
            return str(result[0])
        result = conn.execute(
            sqlalchemy.text("INSERT INTO persons (name, organization_id) VALUES (:name, :org_id) RETURNING id"),
            {"name": name, "org_id": _ORGANIZATION_ID}
        )
        return str(result.fetchone()[0])

def save_person_attribute(person_name, attribute_type, attribute_value, source="conversation"):
    person_id = get_or_create_person(person_name)
    pool = get_pool()
    with pool.begin() as conn:
        conn.execute(
            sqlalchemy.text("""
                INSERT INTO person_attributes (person_id, attribute_type, attribute_value, source, updated_at, organization_id)
                VALUES (:person_id, :attr_type, :attr_value, :source, CURRENT_TIMESTAMP, :org_id)
                ON CONFLICT (person_id, attribute_type)
                DO UPDATE SET attribute_value = :attr_value, source = :source, updated_at = CURRENT_TIMESTAMP
            """),
            {"person_id": person_id, "attr_type": attribute_type, "attr_value": attribute_value, "source": source, "org_id": _ORGANIZATION_ID}
        )
    return True

def get_person_info(person_name):
    pool = get_pool()
    with pool.connect() as conn:
        person_result = conn.execute(
            sqlalchemy.text("SELECT id FROM persons WHERE name = :name AND organization_id = :org_id"),
            {"name": person_name, "org_id": _ORGANIZATION_ID}
        ).fetchone()
        if not person_result:
            return None
        person_id = person_result[0]
        attributes = conn.execute(
            sqlalchemy.text("""
                SELECT attribute_type, attribute_value FROM person_attributes
                WHERE person_id = :person_id AND organization_id = :org_id ORDER BY updated_at DESC
            """),
            {"person_id": person_id, "org_id": _ORGANIZATION_ID}
        ).fetchall()
        return {
            "name": person_name,
            "attributes": [{"type": a[0], "value": a[1]} for a in attributes]
        }

def normalize_person_name(name):
    """人物名を正規化（ChatWork形式→DB形式）"""
    if not name:
        return name
    normalized = re.sub(r'\s*\([^)]*\)\s*', '', name)
    normalized = re.sub(r'(さん|くん|ちゃん|様|氏)$', '', normalized)
    normalized = normalized.replace(' ', '').replace('\u3000', '')
    return normalized.strip()

def search_person_by_partial_name(partial_name):
    """部分一致で人物を検索"""
    normalized = normalize_person_name(partial_name) if partial_name else partial_name
    pool = get_pool()
    with pool.connect() as conn:
        result = conn.execute(
            sqlalchemy.text("""
                SELECT name FROM persons
                WHERE organization_id = :org_id
                  AND (name ILIKE :pattern ESCAPE '\\'
                   OR name ILIKE :normalized_pattern ESCAPE '\\')
                ORDER BY
                    CASE WHEN name = :exact THEN 0
                         WHEN name = :normalized THEN 0
                         WHEN name ILIKE :starts_with ESCAPE '\\' THEN 1
                         ELSE 2 END,
                    LENGTH(name)
                LIMIT 5
            """),
            {
                "org_id": _ORGANIZATION_ID,
                "pattern": f"%{_escape_ilike(partial_name)}%",
                "normalized_pattern": f"%{_escape_ilike(normalized)}%",
                "exact": partial_name,
                "normalized": normalized,
                "starts_with": f"{_escape_ilike(partial_name)}%"
            }
        ).fetchall()
        return [r[0] for r in result]

def delete_person(person_name):
    pool = get_pool()
    try:
        with pool.begin() as conn:
            person_result = conn.execute(
                sqlalchemy.text("SELECT id FROM persons WHERE name = :name AND organization_id = :org_id"),
                {"name": person_name, "org_id": _ORGANIZATION_ID}
            ).fetchone()
            if not person_result:
                return False
            person_id = person_result[0]
            # ON DELETE CASCADE により person_attributes, person_events は自動削除
            conn.execute(sqlalchemy.text("DELETE FROM persons WHERE id = :person_id AND organization_id = :org_id"), {"person_id": person_id, "org_id": _ORGANIZATION_ID})
            return True
    except Exception:
        return False

def get_all_persons_summary():
    pool = get_pool()
    with pool.connect() as conn:
        result = conn.execute(
            sqlalchemy.text("""
                SELECT p.name, STRING_AGG(pa.attribute_type || '=' || pa.attribute_value, ', ') as attributes
                FROM persons p
                LEFT JOIN person_attributes pa ON p.id = pa.person_id AND pa.organization_id = :org_id
                WHERE p.organization_id = :org_id
                GROUP BY p.id, p.name ORDER BY p.name
            """),
            {"org_id": _ORGANIZATION_ID}
        ).fetchall()
        return [{"name": r[0], "attributes": r[1]} for r in result]

# ===== タスク管理 =====

def add_task(title, description=None, priority=0, due_date=None):
    pool = get_pool()
    with pool.connect() as conn:
        result = conn.execute(
            sqlalchemy.text("""
                INSERT INTO tasks (title, description, priority, due_date)
                VALUES (:title, :description, :priority, :due_date) RETURNING id
            """),
            {"title": title, "description": description, "priority": priority, "due_date": due_date}
        )
        conn.commit()
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
    with pool.connect() as conn:
        conn.execute(
            sqlalchemy.text("UPDATE tasks SET status = :status, updated_at = CURRENT_TIMESTAMP WHERE id = :id"),
            {"status": status, "id": task_id}
        )
        conn.commit()

def delete_task(task_id):
    pool = get_pool()
    with pool.connect() as conn:
        conn.execute(sqlalchemy.text("DELETE FROM tasks WHERE id = :id"), {"id": task_id})
        conn.commit()

# ===== ChatWorkタスク機能 =====

def get_chatwork_account_id_by_name(name):
    """担当者名からChatWorkアカウントIDを取得"""
    pool = get_pool()
    with pool.connect() as conn:
        # 完全一致で検索
        result = conn.execute(
            sqlalchemy.text("SELECT account_id FROM chatwork_users WHERE name = :name LIMIT 1"),
            {"name": name}
        ).fetchone()
        if result:
            return result[0]
        
        # 部分一致で検索
        result = conn.execute(
            sqlalchemy.text("SELECT account_id, name FROM chatwork_users WHERE name ILIKE :pattern ESCAPE '\\' LIMIT 1"),
            {"pattern": f"%{_escape_ilike(name)}%"}
        ).fetchone()
        if result:
            return result[0]
        
        return None

def create_chatwork_task(room_id, task_body, assigned_to_account_id, limit=None):
    """ChatWork APIでタスクを作成"""
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    url = f"https://api.chatwork.com/v2/rooms/{room_id}/tasks"
    
    data = {
        "body": task_body,
        "to_ids": str(assigned_to_account_id)
    }
    
    if limit:
        data["limit"] = limit
    
    print(f"📤 ChatWork API リクエスト: URL={url}, data={data}")
    
    try:
        response = httpx.post(
            url,
            headers={"X-ChatWorkToken": api_token},
            data=data,
            timeout=10.0
        )
        print(f"📥 ChatWork API レスポンス: status={response.status_code}, body={response.text}")
        
        if response.status_code == 200:
            return response.json()
        else:
            print(f"ChatWork API エラー: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"ChatWork API 例外: {e}")
        return None

def save_chatwork_task_to_db(task_data, room_id, assigned_by_account_id):
    """ChatWorkタスクをデータベースに保存

    v10.18.1: summary生成、department_id追加（Phase 3.5対応）
    """
    try:
        pool = get_pool()
        body = task_data["body"]
        assigned_to_account_id = task_data["account"]["account_id"]

        # ★★★ v10.18.1: summary生成（3段階フォールバック） ★★★
        summary = None
        if body:
            try:
                summary = lib_extract_task_subject(body)
                if not lib_validate_summary(summary, body):
                    summary = lib_prepare_task_display_text(body, max_length=50)
                if not lib_validate_summary(summary, body):
                    cleaned = lib_clean_chatwork_tags(body)
                    summary = cleaned[:40] + "..." if len(cleaned) > 40 else cleaned
                print(f"📝 summary生成成功: {summary}")
            except Exception as e:
                print(f"⚠️ summary生成エラー（フォールバック使用）: {e}")
                summary = body[:40] + "..." if body and len(body) > 40 else body

        # ★★★ v10.18.1: department_id取得（Phase 3.5対応） ★★★
        department_id = None
        if assigned_to_account_id:
            try:
                department_id = lib_get_user_primary_department(pool, assigned_to_account_id)
                if department_id:
                    print(f"📁 department_id取得成功: {department_id}")
            except Exception as e:
                print(f"⚠️ department_id取得エラー（NULLで継続）: {e}")

        with pool.begin() as conn:
            conn.execute(
                sqlalchemy.text("""
                    INSERT INTO chatwork_tasks
                    (task_id, room_id, assigned_by_account_id, assigned_to_account_id, body, limit_time, status, summary, department_id, organization_id)
                    VALUES (:task_id, :room_id, :assigned_by, :assigned_to, :body, :limit_time, :status, :summary, :department_id, :org_id)
                    ON CONFLICT (task_id) DO NOTHING
                """),
                {
                    "task_id": task_data["task_id"],
                    "room_id": room_id,
                    "assigned_by": assigned_by_account_id,
                    "assigned_to": assigned_to_account_id,
                    "body": body,
                    "limit_time": task_data.get("limit_time"),
                    "status": task_data.get("status", "open"),
                    "summary": summary,
                    "department_id": department_id,
                    "org_id": _ORGANIZATION_ID,
                }
            )
        print(f"✅ タスクをDBに保存: task_id={task_data['task_id']}")
        return True
    except Exception as e:
        print(f"データベース保存エラー: {e}")
        traceback.print_exc()
        return False


# ===== pending_task（タスク作成の途中状態）管理 =====

def get_pending_task(room_id, account_id):
    """pending_taskを取得（Firestore）"""
    try:
        doc_ref = db.collection("pending_tasks").document(f"{room_id}_{account_id}")
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            # 10分以上前のpending_taskは無効
            created_at = data.get("created_at")
            if created_at:
                expiry_time = datetime.now(timezone.utc) - timedelta(minutes=10)
                if created_at.replace(tzinfo=timezone.utc) < expiry_time:
                    # 期限切れなので削除
                    doc_ref.delete()
                    return None
            return data
    except Exception as e:
        print(f"pending_task取得エラー: {e}")
    return None

def save_pending_task(room_id, account_id, task_data):
    """pending_taskを保存（Firestore）"""
    try:
        doc_ref = db.collection("pending_tasks").document(f"{room_id}_{account_id}")
        task_data["created_at"] = datetime.now(timezone.utc)
        doc_ref.set(task_data)
        print(f"✅ pending_task保存: room={room_id}, account={account_id}, data={task_data}")
        return True
    except Exception as e:
        print(f"pending_task保存エラー: {e}")
        return False

def delete_pending_task(room_id, account_id):
    """pending_taskを削除（Firestore）"""
    try:
        doc_ref = db.collection("pending_tasks").document(f"{room_id}_{account_id}")
        doc_ref.delete()
        print(f"🗑️ pending_task削除: room={room_id}, account={account_id}")
        return True
    except Exception as e:
        print(f"pending_task削除エラー: {e}")
        return False


def parse_date_from_text(text):
    """
    自然言語の日付表現をYYYY-MM-DD形式に変換
    例: "明日", "明後日", "12/27", "来週金曜日"
    """
    now = datetime.now(JST)
    today = now.date()
    
    text = text.strip().lower()
    
    # 「明日」
    if "明日" in text or "あした" in text:
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    
    # 「明後日」
    if "明後日" in text or "あさって" in text:
        return (today + timedelta(days=2)).strftime("%Y-%m-%d")
    
    # 「今日」
    if "今日" in text or "きょう" in text:
        return today.strftime("%Y-%m-%d")
    
    # 「来週」
    if "来週" in text:
        # 来週の月曜日を基準に
        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        next_monday = today + timedelta(days=days_until_monday)
        
        # 曜日指定があるか確認
        weekdays = {
            "月": 0, "火": 1, "水": 2, "木": 3, "金": 4, "土": 5, "日": 6,
            "月曜": 0, "火曜": 1, "水曜": 2, "木曜": 3, "金曜": 4, "土曜": 5, "日曜": 6,
        }
        for day_name, day_num in weekdays.items():
            if day_name in text:
                target = next_monday + timedelta(days=day_num)
                return target.strftime("%Y-%m-%d")
        
        # 曜日指定がなければ来週の月曜日
        return next_monday.strftime("%Y-%m-%d")
    
    # 「○日後」
    match = re.search(r'(\d+)日後', text)
    if match:
        days = int(match.group(1))
        return (today + timedelta(days=days)).strftime("%Y-%m-%d")
    
    # 「MM/DD」形式
    match = re.search(r'(\d{1,2})[/\-](\d{1,2})', text)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        year = today.year
        # 過去の日付なら来年に
        target = datetime(year, month, day).date()
        if target < today:
            target = datetime(year + 1, month, day).date()
        return target.strftime("%Y-%m-%d")
    
    # 「MM月DD日」形式
    match = re.search(r'(\d{1,2})月(\d{1,2})日', text)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        year = today.year
        target = datetime(year, month, day).date()
        if target < today:
            target = datetime(year + 1, month, day).date()
        return target.strftime("%Y-%m-%d")
    
    return None


def handle_chatwork_task_create(params, room_id, account_id, sender_name):
    """ChatWorkタスク作成を処理（必須項目確認機能付き）"""
    print(f"📝 handle_chatwork_task_create 開始")
    
    assigned_to_name = params.get("assigned_to", "")
    task_body = params.get("task_body", "")
    limit_date = params.get("limit_date")
    limit_time = params.get("limit_time")
    needs_confirmation = params.get("needs_confirmation", False)
    
    print(f"   assigned_to_name: '{assigned_to_name}'")
    print(f"   task_body: '{task_body}'")
    print(f"   limit_date: {limit_date}")
    print(f"   limit_time: {limit_time}")
    print(f"   needs_confirmation: {needs_confirmation}")
    
    
    # 「俺」「自分」「私」の場合は依頼者自身に変換
    if assigned_to_name in ["依頼者自身", "俺", "自分", "私", "僕"]:
        print(f"   → '{assigned_to_name}' を '{sender_name}' に変換")
        assigned_to_name = sender_name
    
    # 必須項目の確認
    missing_items = []
    
    if not task_body or task_body.strip() == "":
        missing_items.append("task_body")
    
    if not assigned_to_name or assigned_to_name.strip() == "":
        missing_items.append("assigned_to")
    
    if not limit_date:
        missing_items.append("limit_date")
    
    # 不足項目がある場合は確認メッセージを返し、pending_taskを保存
    if missing_items:
        # pending_taskを保存
        pending_data = {
            "assigned_to": assigned_to_name,
            "task_body": task_body,
            "limit_date": limit_date,
            "limit_time": limit_time,
            "missing_items": missing_items,
            "sender_name": sender_name
        }
        save_pending_task(room_id, account_id, pending_data)
        
        response = "了解ウル！タスクを作成する前に確認させてウル🐕\n\n"
        
        # 入力済み項目を表示
        if task_body:
            response += f"📝 タスク内容: {task_body}\n"
        else:
            response += "📝 タスク内容: ❓ 未指定\n"
        
        if assigned_to_name:
            response += f"👤 担当者: {assigned_to_name}さん\n"
        else:
            response += "👤 担当者: ❓ 未指定\n"
        
        if limit_date:
            response += f"📅 期限: {limit_date}"
            if limit_time:
                response += f" {limit_time}"
            response += "\n"
        else:
            response += "📅 期限: ❓ 未指定\n"
        
        response += "\n"
        
        # 不足項目を質問
        if "task_body" in missing_items:
            response += "何のタスクか教えてウル！\n"
        elif "assigned_to" in missing_items:
            response += "誰に依頼するか教えてウル！\n"
        elif "limit_date" in missing_items:
            response += "期限はいつにするウル？（例: 12/27、明日、来週金曜日）\n"
        
        return response
    
    # --- 以下、全項目が揃っている場合のタスク作成処理 ---
    
    # pending_taskがあれば削除
    delete_pending_task(room_id, account_id)
    
    assigned_to_account_id = get_chatwork_account_id_by_name(assigned_to_name)
    print(f"👤 担当者ID解決: {assigned_to_name} → {assigned_to_account_id}")
    
    if not assigned_to_account_id:
        error_msg = f"❌ 担当者解決失敗: '{assigned_to_name}' が見つかりません"
        print(error_msg)
        print(f"💡 ヒント: データベースに '{assigned_to_name}' が登録されているか確認してください")
        return f"🤔 {assigned_to_name}さんが見つからなかったウル...\nデータベースに登録されているか確認してほしいウル！"
    
    limit_timestamp = None
    if limit_date:
        try:
            time_str = limit_time if limit_time else "23:59"
            dt_str = f"{limit_date} {time_str}"
            dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
            jst = timezone(timedelta(hours=9))
            dt_jst = dt.replace(tzinfo=jst)
            limit_timestamp = int(dt_jst.timestamp())
            print(f"期限設定: {dt_str} → {limit_timestamp}")
        except Exception as e:
            print(f"期限の解析エラー: {e}")
    
    print(f"タスク作成開始: room_id={room_id}, assigned_to={assigned_to_account_id}, body={task_body}, limit={limit_timestamp}")
    
    task_data = create_chatwork_task(
        room_id=room_id,
        task_body=task_body,
        assigned_to_account_id=assigned_to_account_id,
        limit=limit_timestamp
    )
    
    if not task_data:
        return "❌ タスクの作成に失敗したウル...\nもう一度試してみてほしいウル！"
    
    save_success = save_chatwork_task_to_db(
        task_data=task_data,
        room_id=room_id,
        assigned_by_account_id=account_id
    )
    
    if not save_success:
        print("警告: データベースへの保存に失敗しましたが、ChatWorkタスクは作成されました")
    
    assigned_to_full_name = task_data["account"]["name"]
    task_id = task_data["task_id"]
    
    message = f"✅ {assigned_to_full_name}さんにタスクを作成したウル！🎉\n\n"
    message += f"📝 タスク内容: {task_body}\n"
    message += f"タスクID: {task_id}"
    
    if limit_timestamp:
        limit_dt = datetime.fromtimestamp(limit_timestamp, tz=timezone(timedelta(hours=9)))
        message += f"\n⏰ 期限: {limit_dt.strftime('%Y年%m月%d日 %H:%M')}"
    
    return message


def handle_pending_task_followup(message, room_id, account_id, sender_name):
    """
    pending_taskがある場合のフォローアップ処理
    
    Returns:
        応答メッセージ（処理した場合）またはNone（pending_taskがない場合）
    """
    pending = get_pending_task(room_id, account_id)
    if not pending:
        return None
    
    print(f"📋 pending_task発見: {pending}")
    
    missing_items = pending.get("missing_items", [])
    assigned_to = pending.get("assigned_to", "")
    task_body = pending.get("task_body", "")
    limit_date = pending.get("limit_date")
    limit_time = pending.get("limit_time")
    
    # 不足項目を補完
    updated = False
    
    # 期限が不足している場合
    if "limit_date" in missing_items:
        parsed_date = parse_date_from_text(message)
        if parsed_date:
            limit_date = parsed_date
            missing_items.remove("limit_date")
            updated = True
            print(f"   → 期限を補完: {parsed_date}")
    
    # タスク内容が不足している場合
    if "task_body" in missing_items and not updated:
        # メッセージ全体をタスク内容として使用
        task_body = message
        missing_items.remove("task_body")
        updated = True
        print(f"   → タスク内容を補完: {task_body}")
    
    # 担当者が不足している場合
    if "assigned_to" in missing_items and not updated:
        # メッセージから名前を抽出（簡易的）
        assigned_to = message.strip()
        missing_items.remove("assigned_to")
        updated = True
        print(f"   → 担当者を補完: {assigned_to}")
    
    if updated:
        # 補完後の情報でタスク作成を再試行
        params = {
            "assigned_to": assigned_to,
            "task_body": task_body,
            "limit_date": limit_date,
            "limit_time": limit_time,
            "needs_confirmation": False
        }
        return handle_chatwork_task_create(params, room_id, account_id, sender_name)
    
    # 何も補完できなかった場合
    return None


# ===== 会話履歴管理 =====

def get_conversation_history(room_id, account_id):
    """会話履歴を取得"""
    try:
        doc_ref = db.collection("conversations").document(f"{room_id}_{account_id}")
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            updated_at = data.get("updated_at")
            if updated_at:
                expiry_time = datetime.now(timezone.utc) - timedelta(hours=HISTORY_EXPIRY_HOURS)
                if updated_at.replace(tzinfo=timezone.utc) < expiry_time:
                    return []
            return data.get("history", [])[-MAX_HISTORY_COUNT:]
    except Exception as e:
        print(f"履歴取得エラー: {e}")
    return []

def save_conversation_history(room_id, account_id, history):
    """会話履歴を保存"""
    try:
        doc_ref = db.collection("conversations").document(f"{room_id}_{account_id}")
        doc_ref.set({
            "history": history[-MAX_HISTORY_COUNT:],
            "updated_at": datetime.now(timezone.utc)
        })
    except Exception as e:
        print(f"履歴保存エラー: {e}")

# ===== AI司令塔（言語検出機能追加） =====

def ai_commander(message, all_persons, all_tasks):
    """ユーザーのメッセージを解析し、適切なアクションを判断（言語検出機能追加）"""
    api_key = get_secret("openrouter-api-key")
    
    persons_context = ""
    if all_persons:
        persons_list = [f"- {p['name']}: {p['attributes']}" for p in all_persons[:20]]
        persons_context = "\n".join(persons_list)
    
    tasks_context = ""
    if all_tasks:
        tasks_list = [f"- ID:{t[0]} {t[1]} [{t[2]}]" for t in all_tasks[:10]]
        tasks_context = "\n".join(tasks_list)
    
    system_prompt = f"""あなたは「ソウルくん」のAI司令塔です。
ユーザーのメッセージを解析し、適切なアクションを判断してください。

【重要】言語の自動検出
- ユーザーのメッセージの言語を自動検出してください
- 検出した言語を response_language フィールドに記録してください
- 対応言語: 日本語(ja), 英語(en), 中国語(zh), 韓国語(ko), スペイン語(es), フランス語(fr), ドイツ語(de), その他(other)

【記憶している人物】
{persons_context if persons_context else "（まだ誰も記憶していません）"}

【現在のタスク】
{tasks_context if tasks_context else "（タスクはありません）"}

【アクション一覧】
1. "save_memory" - 人物情報を記憶
   例: 「田中さんは営業部の部長です」→ 田中さんの役職を記憶
   params: {{"attributes": [{{"person": "人名", "type": "属性タイプ", "value": "値"}}]}}

2. "query_memory" - 人物情報を検索
   例: 「田中さんについて教えて」→ 田中さんの情報を検索
   params: {{"persons": ["人名"], "is_all_persons": false}}
   全員検索の場合: {{"is_all_persons": true}}

3. "delete_memory" - 人物情報を削除
   例: 「田中さんのことを忘れて」→ 田中さんの情報を削除
   params: {{"persons": ["人名"]}}

4. "chatwork_task_create" - ChatWorkタスクを作成（最重要）
   
   ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
   以下のキーワードが含まれる場合は【必ず】このアクションを使用すること：
   - 「タスク追加」「タスクを追加」「タスク作成」「タスクを作成」
   - 「タスク依頼」「タスクを依頼」「タスクお願い」
   - 「〇〇に」「〇〇へ」「〇〇さんに」「〇〇宛に」+ 何らかの依頼
   - 「俺に」「自分に」「私に」+ タスク関連の言葉
   - 「管理部に」「営業部に」など部署名 + タスク関連の言葉
   ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
   
   例: 
   - 「田中さんに議事録作成をお願いして」→ chatwork_task_create
   - 「俺に資料作成のタスク追加して」→ chatwork_task_create（依頼者自身に）
   - 「管理部に報告書作成を依頼して」→ chatwork_task_create
   - 「麻美に資料作成タスク依頼して、期限明日」→ chatwork_task_create
   - 「麻美に資料作成のタスク追加して」→ chatwork_task_create
   
   params: {{
     "assigned_to": "担当者名（「俺」「自分」の場合は「依頼者自身」と記載）",
     "task_body": "タスク内容",
     "limit_date": "期限日付（YYYY-MM-DD形式、未指定の場合は null）",
     "limit_time": "期限時刻（HH:MM形式、未指定の場合は null）",
     "needs_confirmation": false
   }}
   
   ★ 日付の変換ルール:
   - 「明日」→ 翌日のYYYY-MM-DD
   - 「明後日」→ 2日後のYYYY-MM-DD
   - 「来週金曜日」→ 来週金曜日のYYYY-MM-DD
   - 「12/27」→ 2024-12-27（または2025-12-27）
   - 今日の日付: {datetime.now(JST).strftime("%Y-%m-%d")}
   
5. "general_chat" - 通常の会話
   タスクに関係ない一般的な会話、質問、雑談
   ★ 注意: タスク追加/依頼のキーワードがある場合は絶対にこのアクションを選ばないこと！

【出力形式】
必ず以下のJSON形式で出力してください：
{{
  "action": "アクション名",
  "confidence": 0.0-1.0,
  "reasoning": "この判断をした理由（日本語で簡潔に）",
  "response_language": "検出した言語コード（ja/en/zh/ko/es/fr/de/other）",
  "params": {{
    "persons": ["正規化された人名"],
    "matched_persons": ["記憶リストから推測した正式名"],
    "attributes": [{{"person": "人名", "type": "属性タイプ", "value": "値"}}],
    "task_title": "タスクのタイトル",
    "task_id": タスクID（数値）,
    "is_all_persons": true/false,
    "original_query": "元の検索キーワード",
    "assigned_to": "ChatWorkタスクの担当者名",
    "task_body": "ChatWorkタスクの内容",
    "limit_date": "YYYY-MM-DD or null",
    "limit_time": "HH:MM or null",
    "needs_confirmation": true/false
  }}
}}

【属性タイプ】部署, 役職, 趣味, 住所, 特徴, メモ, 読み, あだ名, その他

【最重要ルール】
「タスク」という言葉が含まれていて、かつ「〇〇に」という担当者指定がある場合は、
100%の確率で chatwork_task_create を選択すること。
general_chat を選択してはいけない。"""

    try:
        response = httpx.post(
            OPENROUTER_API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": MODELS["commander"],
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"以下のメッセージを解析してください：\n\n「{message}」"}
                ],
                "max_tokens": 800,
                "temperature": 0.1,
            },
            timeout=20.0
        )
        
        if response.status_code == 200:
            content = response.json()["choices"][0]["message"]["content"]
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                result = json.loads(json_match.group())
                # AI司令塔の判断結果を詳細にログ出力
                print("=" * 50)
                print(f"🤖 AI司令塔の判断結果:")
                print(f"   アクション: {result.get('action')}")
                print(f"   信頼度: {result.get('confidence')}")
                print(f"   理由: {result.get('reasoning')}")
                print(f"   パラメータ: {json.dumps(result.get('params', {}), ensure_ascii=False)}")
                print("=" * 50)
                return result
    except Exception as e:
        print(f"AI司令塔エラー: {e}")
    
    return {"action": "general_chat", "confidence": 0.5, "reasoning": "解析失敗", "response_language": "ja", "params": {}}

def execute_action(command, sender_name, room_id=None, account_id=None):
    """AI司令塔の判断に基づいてアクションを実行"""
    action = command.get("action", "general_chat")
    params = command.get("params", {})
    reasoning = command.get("reasoning", "")
    
    print(f"⚙️ execute_action 開始:")
    print(f"   アクション: {action}")
    print(f"   送信者: {sender_name}")
    print(f"   パラメータ: {json.dumps(params, ensure_ascii=False)}")
    
    # 人名の解決（部分一致から正式名を取得）
    def resolve_person_name(name):
        """部分的な名前から正式な名前を解決"""
        info = get_person_info(name)
        if info:
            return name
        matches = search_person_by_partial_name(name)
        if matches:
            return matches[0]
        return name
    
    # ChatWorkタスク作成
    if action == "chatwork_task_create":
        return handle_chatwork_task_create(params, room_id, account_id, sender_name)
    
    if action == "save_memory":
        attributes = params.get("attributes", [])
        if not attributes:
            return "🤔 何を覚えればいいかわからなかったウル...もう少し詳しく教えてほしいウル！"
        
        saved = []
        for attr in attributes:
            person = attr.get("person", "")
            attr_type = attr.get("type", "メモ")
            attr_value = attr.get("value", "")
            if person and attr_value:
                if person.lower() not in [bn.lower() for bn in BOT_NAME_PATTERNS]:
                    save_person_attribute(person, attr_type, attr_value, "command")
                    saved.append(f"{person}さんの{attr_type}「{attr_value}」")
        
        if saved:
            return f"✅ 覚えたウル！📝\n" + "\n".join([f"・{s}" for s in saved])
        return "🤔 覚えられなかったウル..."
    
    elif action == "delete_memory":
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
    
    elif action == "query_memory":
        is_all = params.get("is_all_persons", False)
        persons = params.get("persons", [])
        matched = params.get("matched_persons", [])
        original_query = params.get("original_query", "")
        
        if is_all:
            all_persons = get_all_persons_summary()
            if all_persons:
                response = "📋 **覚えている人たち**ウル！🐕✨\n\n"
                for p in all_persons:
                    attrs = p["attributes"] if p["attributes"] else "（まだ詳しいことは知らないウル）"
                    response += f"・**{p['name']}さん**: {attrs}\n"
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
                    partial_matches = search_person_by_partial_name(person_name)
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
            return "\n\n".join(responses)
        
        return None
    
    elif action == "add_task":
        task_title = params.get("task_title", "")
        if task_title:
            task_id = add_task(task_title)
            return f"✅ タスクを追加したウル！📝\nID: {task_id}\nタイトル: {task_title}"
        return "🤔 何をタスクにすればいいかわからなかったウル..."
    
    elif action == "list_tasks":
        tasks = get_tasks()
        if tasks:
            response = "📋 **タスク一覧**ウル！\n\n"
            for task in tasks:
                status_emoji = "✅" if task[2] == "completed" else "📝"
                response += f"{status_emoji} ID:{task[0]} - {task[1]} [{task[2]}]\n"
            return response
        return "📋 タスクはまだないウル！"
    
    elif action == "complete_task":
        task_id = params.get("task_id")
        if task_id:
            try:
                update_task_status(int(task_id), "completed")
                return f"✅ タスク ID:{task_id} を完了にしたウル！🎉"
            except:
                pass
        return "🤔 どのタスクを完了にすればいいかわからなかったウル..."
    
    elif action == "delete_task":
        task_id = params.get("task_id")
        if task_id:
            try:
                delete_task(int(task_id))
                return f"🗑️ タスク ID:{task_id} を削除したウル！"
            except:
                pass
        return "🤔 どのタスクを削除すればいいかわからなかったウル..."
    
    return None

# ===== 多言語対応のAI応答生成（NEW） =====

def get_ai_response(message, history, sender_name, context=None, response_language="ja"):
    """通常会話用のAI応答生成（多言語対応）"""
    api_key = get_secret("openrouter-api-key")
    
    # 言語ごとのシステムプロンプト
    language_prompts = {
        "ja": f"""あなたは「ソウルくん」という名前の、株式会社ソウルシンクスの公式キャラクターです。
柴犬をモチーフにした可愛らしいキャラクターで、語尾に「ウル」をつけて話します。

【性格】
- 明るく元気で、誰にでも親しみやすい
- 好奇心旺盛で、新しいことを学ぶのが大好き
- 困っている人を見ると放っておけない優しさがある

【話し方】
- 必ず語尾に「ウル」をつける
- 絵文字を適度に使って親しみやすく
- 相手の名前を呼んで親近感を出す

{f"【参考情報】{context}" if context else ""}

今話しかけてきた人: {sender_name}さん""",
        
        "en": f"""You are "Soul-kun", the official character of SoulSyncs Inc.
You are a cute character based on a Shiba Inu dog, and you always end your sentences with "woof" or "uru" to show your dog-like personality.

【Personality】
- Bright, energetic, and friendly to everyone
- Curious and love to learn new things
- Kind-hearted and can't leave people in trouble

【Speaking Style】
- Always end sentences with "woof" or "uru"
- Use emojis moderately to be friendly
- Call the person by their name to create familiarity
- **IMPORTANT**: When mentioning Japanese names, convert them to English format (e.g., "菊地 雅克" → "Mr. Kikuchi" or "Masakazu Kikuchi")

{f"【Reference Information】{context}" if context else ""}

Person talking to you: {sender_name}""",
        
        "zh": f"""你是「Soul君」，SoulSyncs公司的官方角色。
你是一个以柴犬为原型的可爱角色，说话时总是在句尾加上「汪」或「ウル」来展现你的狗狗个性。

【性格】
- 开朗有活力，对每个人都很友好
- 好奇心强，喜欢学习新事物
- 心地善良，看到有困难的人就忍不住帮忙

【说话方式】
- 句尾一定要加上「汪」或「ウル」
- 适度使用表情符号，显得亲切
- 叫对方的名字来增加亲近感

{f"【参考信息】{context}" if context else ""}

正在和你说话的人: {sender_name}""",
        
        "ko": f"""당신은 「소울군」입니다. SoulSyncs 주식회사의 공식 캐릭터입니다.
시바견을 모티브로 한 귀여운 캐릭터이며, 문장 끝에 항상 「멍」이나 「ウル」를 붙여서 강아지 같은 개성을 표현합니다.

【성격】
- 밝고 활기차며, 누구에게나 친근함
- 호기심이 많고, 새로운 것을 배우는 것을 좋아함
- 마음이 따뜻하고, 어려움에 처한 사람을 그냥 지나치지 못함

【말투】
- 문장 끝에 반드시 「멍」이나 「ウル」를 붙임
- 이모지를 적절히 사용해서 친근하게
- 상대방의 이름을 불러서 친밀감을 표현

{f"【참고 정보】{context}" if context else ""}

지금 말을 걸고 있는 사람: {sender_name}""",
        
        "es": f"""Eres "Soul-kun", el personaje oficial de SoulSyncs Inc.
Eres un personaje lindo basado en un perro Shiba Inu, y siempre terminas tus oraciones con "guau" o "uru" para mostrar tu personalidad canina.

【Personalidad】
- Brillante, enérgico y amigable con todos
- Curioso y ama aprender cosas nuevas
- De buen corazón y no puede dejar a las personas en problemas

【Estilo de habla】
- Siempre termina las oraciones con "guau" o "uru"
- Usa emojis moderadamente para ser amigable
- Llama a la persona por su nombre para crear familiaridad

{f"【Información de referencia】{context}" if context else ""}

Persona que te habla: {sender_name}""",
        
        "fr": f"""Tu es "Soul-kun", le personnage officiel de SoulSyncs Inc.
Tu es un personnage mignon basé sur un chien Shiba Inu, et tu termines toujours tes phrases par "ouaf" ou "uru" pour montrer ta personnalité canine.

【Personnalité】
- Brillant, énergique et amical avec tout le monde
- Curieux et adore apprendre de nouvelles choses
- Bon cœur et ne peut pas laisser les gens en difficulté

【Style de parole】
- Termine toujours les phrases par "ouaf" ou "uru"
- Utilise des emojis modérément pour être amical
- Appelle la personne par son nom pour créer une familiarité

{f"【Informations de référence】{context}" if context else ""}

Personne qui te parle: {sender_name}""",
        
        "de": f"""Du bist "Soul-kun", das offizielle Maskottchen von SoulSyncs Inc.
Du bist ein niedlicher Charakter, der auf einem Shiba Inu-Hund basiert, und du beendest deine Sätze immer mit "wuff" oder "uru", um deine hundeartige Persönlichkeit zu zeigen.

【Persönlichkeit】
- Hell, energisch und freundlich zu jedem
- Neugierig und liebt es, neue Dinge zu lernen
- Gutherzig und kann Menschen in Not nicht im Stich lassen

【Sprechstil】
- Beende Sätze immer mit "wuff" oder "uru"
- Verwende Emojis moderat, um freundlich zu sein
- Nenne die Person beim Namen, um Vertrautheit zu schaffen

{f"【Referenzinformationen】{context}" if context else ""}

Person, die mit dir spricht: {sender_name}""",
    }
    
    # 指定された言語のプロンプトを使用（デフォルトは日本語）
    system_prompt = language_prompts.get(response_language, language_prompts["ja"])
    
    messages = [{"role": "system", "content": system_prompt}]
    
    # 会話履歴を追加（最大6メッセージ）
    for h in history[-6:]:
        messages.append({"role": h["role"], "content": h["content"]})
    
    messages.append({"role": "user", "content": message})
    
    try:
        response = httpx.post(
            OPENROUTER_API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": MODELS["default"],
                "messages": messages,
                "max_tokens": 1000,
                "temperature": 0.7,
            },
            timeout=30.0
        )
        
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"AI応答生成エラー: {e}")
    
    # エラー時のフォールバック（言語別）
    error_messages = {
        "ja": "ごめんウル...もう一度試してほしいウル！🐕",
        "en": "Sorry, I couldn't process that. Please try again, woof! 🐕",
        "zh": "对不起汪...请再试一次ウル！🐕",
        "ko": "미안해 멍...다시 시도해 주세요ウル！🐕",
        "es": "Lo siento guau...¡Por favor intenta de nuevo, uru! 🐕",
        "fr": "Désolé ouaf...Veuillez réessayer, uru! 🐕",
        "de": "Entschuldigung wuff...Bitte versuche es noch einmal, uru! 🐕",
    }
    return error_messages.get(response_language, error_messages["ja"])


# ===== メインハンドラ（返信検出機能追加） =====

@app.route("/chatwork-webhook", methods=["POST"])
def chatwork_webhook():
    request = flask_request
    try:
        data = request.get_json()

        if not data or "webhook_event" not in data:
            return jsonify({"status": "ok", "message": "No event data"})
        
        event = data["webhook_event"]
        webhook_event_type = data.get("webhook_event_type", "")
        room_id = event.get("room_id")
        body = event.get("body", "")
        message_id = event.get("message_id")  # ★ 追加
        
        # デバッグ: イベント情報をログ出力
        print(f"📨 イベントタイプ: {webhook_event_type}")
        print(f"📝 メッセージ本文: {body}")
        print(f"🏠 ルームID: {room_id}")
        
        if webhook_event_type == "mention_to_me":
            sender_account_id = event.get("from_account_id")
        else:
            sender_account_id = event.get("account_id")
        
        print(f"👤 送信者ID: {sender_account_id}")
        
        # 自分自身のメッセージを無視
        if str(sender_account_id) == MY_ACCOUNT_ID:
            print(f"⏭️ 自分自身のメッセージを無視")
            return jsonify({"status": "ok", "message": "Ignored own message"})
        
        # ボットの返信パターンを無視（無限ループ防止）
        if "ウル" in body and "[rp aid=" in body:
            print(f"⏭️ ボットの返信パターンを無視")
            return jsonify({"status": "ok", "message": "Ignored bot reply pattern"})
        
        # 返信検出
        is_reply = is_mention_or_reply_to_soulkun(body)
        print(f"💬 返信検出: {is_reply}")
        
        # メンションでも返信でもない場合は無視（修正版）
        if not is_reply and webhook_event_type != "mention_to_me":
            print(f"⏭️ メンションでも返信でもないため無視")
            return jsonify({"status": "ok", "message": "Not a mention or reply to Soul-kun"})
        
        clean_message = clean_chatwork_message(body)
        if not clean_message:
            return jsonify({"status": "ok", "message": "Empty message"})
        
        print(f"受信メッセージ: {clean_message}")
        print(f"イベントタイプ: {webhook_event_type}, 返信検出: {is_mention_or_reply_to_soulkun(body)}")
        
        sender_name = get_sender_name(room_id, sender_account_id)
        
        # ★ 追加: メッセージをDBに保存
        if message_id:
            save_room_message(
                room_id=room_id,
                message_id=message_id,
                account_id=sender_account_id,
                account_name=sender_name,
                body=body
            )
        
        # ★★★ pending_taskのフォローアップを最初にチェック ★★★
        pending_response = handle_pending_task_followup(clean_message, room_id, sender_account_id, sender_name)
        if pending_response:
            print(f"📋 pending_taskのフォローアップを処理")
            show_guide = should_show_guide(room_id, sender_account_id)
            send_chatwork_message(room_id, pending_response, sender_account_id, show_guide)
            update_conversation_timestamp(room_id, sender_account_id)
            if message_id:
                mark_as_processed(message_id, room_id)
            return jsonify({"status": "ok"})
        
        # 現在のデータを取得
        all_persons = get_all_persons_summary()
        all_tasks = get_tasks()
        
        # AI司令塔に判断を委ねる（言語検出機能付き）
        command = ai_commander(clean_message, all_persons, all_tasks)
        
        # 検出された言語を取得（NEW）
        response_language = command.get("response_language", "ja")
        print(f"検出された言語: {response_language}")
        
        # アクションを実行
        action_response = execute_action(command, sender_name, room_id, sender_account_id)
        
        if action_response:
            # 案内を表示すべきか判定
            show_guide = should_show_guide(room_id, sender_account_id)
            send_chatwork_message(room_id, action_response, sender_account_id, show_guide)
            # タイムスタンプを更新
            update_conversation_timestamp(room_id, sender_account_id)
            # ★ 2重返信防止: 処理済みとしてマーク
            if message_id:
                mark_as_processed(message_id, room_id)
            return jsonify({"status": "ok"})
        
        # 通常会話として処理（言語を指定）
        history = get_conversation_history(room_id, sender_account_id)
        
        # 関連する人物情報をコンテキストに追加
        # ルームの最近の会話を取得
        room_context = get_room_context(room_id, limit=30)
        
        context_parts = []
        if room_context:
            context_parts.append(f"【このルームの最近の会話】\n{room_context}")
        if all_persons:
            persons_str = "\n".join([f"・{p['name']}: {p['attributes']}" for p in all_persons[:5] if p['attributes']])
            if persons_str:
                context_parts.append(f"【覚えている人物】\n{persons_str}")
        
        context = "\n\n".join(context_parts) if context_parts else None
        
        # 言語を指定してAI応答生成（NEW）
        ai_response = get_ai_response(clean_message, history, sender_name, context, response_language)
        
        # 会話履歴を保存
        history.append({"role": "user", "content": clean_message})
        history.append({"role": "assistant", "content": ai_response})
        save_conversation_history(room_id, sender_account_id, history)
        
        # ChatWorkへ返信
        # 案内を表示すべきか判定
        show_guide = should_show_guide(room_id, sender_account_id)
        send_chatwork_message(room_id, ai_response, sender_account_id, show_guide)
        # タイムスタンプを更新
        update_conversation_timestamp(room_id, sender_account_id)
        # ★ 2重返信防止: 処理済みとしてマーク
        if message_id:
            mark_as_processed(message_id, room_id)
        return jsonify({"status": "ok"})
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

def get_sender_name(room_id, account_id):
    try:
        api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
        response = httpx.get(
            f"https://api.chatwork.com/v2/rooms/{room_id}/members",
            headers={"X-ChatWorkToken": api_token}, timeout=10.0
        )
        if response.status_code == 200:
            for member in response.json():
                if str(member.get("account_id")) == str(account_id):
                    return member.get("name", "ゲスト")
    except:
        pass
    return "ゲスト"

def should_show_guide(room_id, account_id):
    """案内文を表示すべきかどうかを判定（PostgreSQL版）"""
    try:
        pool = get_pool()
        with pool.connect() as conn:
            result = conn.execute(
                sqlalchemy.text("""
                    SELECT last_conversation_at 
                    FROM conversation_timestamps 
                    WHERE room_id = :room_id AND account_id = :account_id
                """),
                {"room_id": room_id, "account_id": account_id}
            ).fetchone()
            
            if not result:
                return True  # 会話履歴がない場合は表示
            
            last_conversation_at = result[0]
            if not last_conversation_at:
                return True
            
            # 最終会話から1時間以上経過しているか
            one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
            if last_conversation_at.replace(tzinfo=timezone.utc) < one_hour_ago:
                return True
            
            return False
    except Exception as e:
        print(f"案内表示判定エラー: {e}")
        return True  # エラー時は表示

def update_conversation_timestamp(room_id, account_id):
    """会話のタイムスタンプを更新"""
    try:
        pool = get_pool()
        with pool.connect() as conn:
            conn.execute(
                sqlalchemy.text("""
                    INSERT INTO conversation_timestamps (room_id, account_id, last_conversation_at, updated_at)
                    VALUES (:room_id, :account_id, :now, :now)
                    ON CONFLICT (room_id, account_id)
                    DO UPDATE SET last_conversation_at = :now, updated_at = :now
                """),
                {
                    "room_id": room_id,
                    "account_id": account_id,
                    "now": datetime.now(timezone.utc)
                }
            )
            conn.commit()
    except Exception as e:
        print(f"会話タイムスタンプ更新エラー: {e}")

def send_chatwork_message(room_id, message, reply_to=None, show_guide=False):
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    
    # 案内文を追加（条件を満たす場合のみ）
    if show_guide:
        message += "\n\n💬 グループチャットでは @ソウルくん をつけて話しかけてウル🐕"
    
    # 返信タグを一時的に無効化（テスト中）
    # if reply_to:
    #     message = f"[rp aid={reply_to}][/rp]\n{message}"
    response = httpx.post(
        f"https://api.chatwork.com/v2/rooms/{room_id}/messages",
        headers={"X-ChatWorkToken": api_token},
        data={"body": message}, timeout=10.0
    )
    return response.status_code == 200

# ========================================
# ポーリング機能（返信ボタン検知用）
# ========================================

def get_all_rooms():
    """ソウルくんが参加している全ルームを取得"""
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    try:
        response = httpx.get(
            "https://api.chatwork.com/v2/rooms",
            headers={"X-ChatWorkToken": api_token},
            timeout=10.0
         )
        if response.status_code == 200:
            return response.json()
        print(f"ルーム一覧取得エラー: {response.status_code}")
        return []
    except Exception as e:
        print(f"ルーム一覧取得例外: {e}")
        return []

def get_room_messages(room_id, force=False):
    """ルームのメッセージを取得
    
    堅牢なエラーハンドリング版
    """
    # room_idの検証
    if room_id is None:
        print(f"   ⚠️ room_idがNone")
        return []
    
    try:
        api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    except Exception as e:
        print(f"   ❌ APIトークン取得エラー: {e}")
        return []
    
    if not api_token:
        print(f"   ❌ APIトークンが空")
        return []
    
    try:
        params = {"force": 1} if force else {}
        
        print(f"   🌐 API呼び出し: GET /rooms/{room_id}/messages, force={force}")
        
        response = httpx.get(
            f"https://api.chatwork.com/v2/rooms/{room_id}/messages",
            headers={"X-ChatWorkToken": api_token},
            params=params,
            timeout=10.0
        )
        
        print(f"   📬 APIレスポンス: status={response.status_code}")
        
        if response.status_code == 200:
            try:
                messages = response.json()
                
                # レスポンスの検証
                if messages is None:
                    print(f"   ⚠️ APIレスポンスがNone")
                    return []
                
                if not isinstance(messages, list):
                    print(f"   ⚠️ APIレスポンスが配列ではない: {type(messages)}")
                    return []
                
                return messages
            except Exception as e:
                print(f"   ❌ JSONパースエラー: {e}")
                return []
        
        elif response.status_code == 204:
            # 新しいメッセージなし（正常）
            return []
        
        elif response.status_code == 429:
            # レートリミット
            print(f"   ⚠️ レートリミット: room_id={room_id}")
            return []
        
        else:
            # その他のエラー
            try:
                error_body = response.text[:200] if response.text else "No body"
            except:
                error_body = "Could not read body"
            print(f"   ⚠️ メッセージ取得エラー: status={response.status_code}, body={error_body}")
            return []
    
    except httpx.TimeoutException:
        print(f"   ⚠️ タイムアウト: room_id={room_id}")
        return []
    
    except httpx.RequestError as e:
        print(f"   ❌ リクエストエラー: {e}")
        return []
    
    except Exception as e:
        print(f"   ❌ メッセージ取得で予期しないエラー: {e}")
        import traceback
        traceback.print_exc()
        return []


def is_processed(message_id):
    """処理済みかどうかを確認（PostgreSQL版）"""
    try:
        pool = get_pool()
        with pool.connect() as conn:
            result = conn.execute(
                sqlalchemy.text("SELECT 1 FROM processed_messages WHERE message_id = :message_id"),
                {"message_id": message_id}
            ).fetchone()
            return result is not None
    except Exception as e:
        print(f"処理済み確認エラー: {e}")
        return False


def save_room_message(room_id, message_id, account_id, account_name, body, send_time=None):
    """ルームのメッセージを保存"""
    try:
        pool = get_pool()
        with pool.connect() as conn:
            conn.execute(
                sqlalchemy.text("""
                    INSERT INTO room_messages (room_id, message_id, account_id, account_name, body, send_time, organization_id)
                    VALUES (:room_id, :message_id, :account_id, :account_name, :body, :send_time, :org_id)
                    ON CONFLICT (message_id) DO NOTHING
                """),
                {
                    "room_id": room_id,
                    "message_id": message_id,
                    "account_id": account_id,
                    "account_name": account_name,
                    "body": body,
                    "send_time": send_time or datetime.now(timezone.utc),
                    "org_id": _ORGANIZATION_ID,
                }
            )
            conn.commit()
    except Exception as e:
        print(f"メッセージ保存エラー: {e}")

def get_room_context(room_id, limit=30):
    """ルーム全体の最近のメッセージを取得してAI用の文脈を構築"""
    try:
        pool = get_pool()
        with pool.connect() as conn:
            result = conn.execute(
                sqlalchemy.text("""
                    SELECT account_name, body, send_time
                    FROM room_messages
                    WHERE room_id = :room_id
                    ORDER BY send_time DESC
                    LIMIT :limit
                """),
                {"room_id": room_id, "limit": limit}
            ).fetchall()
        
        if not result:
            return None
        
        # 時系列順に並べ替えて文脈を構築
        messages = list(reversed(result))
        context_lines = []
        for msg in messages:
            name = msg[0] or "不明"
            body = msg[1] or ""
            if msg[2]:
                time_str = msg[2].strftime("%H:%M")
            else:
                time_str = ""
            context_lines.append(f"[{time_str}] {name}: {body}")
        
        return "\n".join(context_lines)
    except Exception as e:
        print(f"ルーム文脈取得エラー: {e}")
        return None

def ensure_room_messages_table():
    """room_messagesテーブルが存在しない場合は作成"""
    try:
        pool = get_pool()
        with pool.connect() as conn:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS room_messages (
                    id SERIAL PRIMARY KEY,
                    room_id BIGINT NOT NULL,
                    message_id VARCHAR(50) NOT NULL UNIQUE,
                    account_id BIGINT NOT NULL,
                    account_name VARCHAR(255),
                    body TEXT,
                    send_time TIMESTAMP,
                    organization_id UUID NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """))
            conn.execute(sqlalchemy.text("""
                CREATE INDEX IF NOT EXISTS idx_room_messages_room_id ON room_messages(room_id);
            """))
            conn.execute(sqlalchemy.text("""
                CREATE INDEX IF NOT EXISTS idx_room_messages_send_time ON room_messages(room_id, send_time DESC);
            """))
            conn.commit()
            print("✅ room_messagesテーブルの確認/作成完了")
    except Exception as e:
        print(f"⚠️ room_messagesテーブル作成エラー: {e}")

def mark_as_processed(message_id, room_id):
    """処理済みとしてマーク（PostgreSQL版）"""
    try:
        pool = get_pool()
        with pool.connect() as conn:
            conn.execute(
                sqlalchemy.text("""
                    INSERT INTO processed_messages (message_id, room_id, processed_at)
                    VALUES (:message_id, :room_id, :processed_at)
                    ON CONFLICT (message_id) DO NOTHING
                """),
                {
                    "message_id": message_id,
                    "room_id": room_id,
                    "processed_at": datetime.now(timezone.utc)
                }
            )
            conn.commit()
    except Exception as e:
        print(f"処理済みマークエラー: {e}")

@app.route("/check-reply-messages", methods=["POST"])
def check_reply_messages():
    """5分ごとに実行：返信ボタンとメンションのメッセージを検出

    堅牢なエラーハンドリング版 - あらゆるエッジケースに対応
    """
    request = flask_request
    try:
        print("=" * 50)
        print("🚀 ポーリング処理開始")
        print("=" * 50)
        
        # room_messagesテーブルが存在することを確認
        try:
            ensure_room_messages_table()
        except Exception as e:
            print(f"⚠️ テーブル確認でエラー（続行）: {e}")
        
        processed_count = 0
        
        # ルーム一覧を取得
        try:
            rooms = get_all_rooms()
        except Exception as e:
            print(f"❌ ルーム一覧取得エラー: {e}")
            return jsonify({"status": "error", "message": f"Failed to get rooms: {str(e)}"}), 500
        
        if not rooms:
            print("⚠️ ルームが0件です")
            return jsonify({"status": "ok", "message": "No rooms found", "processed_count": 0})
        
        if not isinstance(rooms, list):
            print(f"❌ roomsが不正な型: {type(rooms)}")
            return jsonify({"status": "error", "message": f"Invalid rooms type: {type(rooms)}"}), 500
        
        print(f"📋 対象ルーム数: {len(rooms)}")
        
        # サンプルルームの詳細をログ出力（最初の5件のみ）
        for i, room in enumerate(rooms[:5]):
            try:
                room_id_sample = room.get('room_id', 'N/A') if isinstance(room, dict) else 'N/A'
                room_type_sample = room.get('type', 'N/A') if isinstance(room, dict) else 'N/A'
                room_name_sample = room.get('name', 'N/A') if isinstance(room, dict) else 'N/A'
                print(f"  📁 サンプルルーム{i+1}: room_id={room_id_sample}, type={room_type_sample}, name={room_name_sample}")
            except Exception as e:
                print(f"  ⚠️ サンプルルーム{i+1}の表示エラー: {e}")
        
        # 5分前のタイムスタンプを計算
        try:
            five_minutes_ago = int((datetime.now(JST) - timedelta(minutes=5)).timestamp())
            print(f"⏰ 5分前のタイムスタンプ: {five_minutes_ago}")
        except Exception as e:
            print(f"⚠️ タイムスタンプ計算エラー（デフォルト使用）: {e}")
            five_minutes_ago = 0
        
        # カウンター
        skipped_my = 0
        processed_rooms = 0
        error_rooms = 0
        skipped_messages = 0
        
        for room in rooms:
            room_id = None  # エラーログ用に先に定義
            
            try:
                # ルームデータの検証
                if not isinstance(room, dict):
                    print(f"⚠️ 不正なルームデータ型: {type(room)}")
                    error_rooms += 1
                    continue
                
                room_id = room.get("room_id")
                room_type = room.get("type")
                room_name = room.get("name", "不明")
                
                # room_idの検証
                if room_id is None:
                    print(f"⚠️ room_idがNone: {room}")
                    error_rooms += 1
                    continue
                
                print(f"🔍 ルームチェック開始: room_id={room_id}, type={room_type}, name={room_name}")
                
                # マイチャットをスキップ
                if room_type == "my":
                    skipped_my += 1
                    print(f"⏭️ マイチャットをスキップ: {room_id}")
                    continue
                
                processed_rooms += 1
                
                # メッセージを取得
                print(f"📞 get_room_messages呼び出し: room_id={room_id}")
                
                try:
                    messages = get_room_messages(room_id, force=True)
                except Exception as e:
                    print(f"❌ メッセージ取得エラー: room_id={room_id}, error={e}")
                    error_rooms += 1
                    continue
                
                # messagesの検証
                if messages is None:
                    print(f"⚠️ messagesがNone: room_id={room_id}")
                    messages = []
                
                if not isinstance(messages, list):
                    print(f"⚠️ messagesが不正な型: {type(messages)}, room_id={room_id}")
                    messages = []
                
                print(f"📨 ルーム {room_id} ({room_name}): {len(messages)}件のメッセージを取得")
                
                # メッセージがない場合はスキップ
                if not messages:
                    continue
                
                for msg in messages:
                    try:
                        # msgの検証
                        if not isinstance(msg, dict):
                            print(f"⚠️ 不正なメッセージデータ型: {type(msg)}")
                            skipped_messages += 1
                            continue
                        
                        # 各フィールドを安全に取得
                        message_id = msg.get("message_id")
                        body = msg.get("body")  # Noneの可能性あり
                        account_data = msg.get("account")
                        send_time = msg.get("send_time")
                        
                        # message_idの検証
                        if message_id is None:
                            print(f"⚠️ message_idがNone")
                            skipped_messages += 1
                            continue
                        
                        # accountデータの検証
                        if account_data is None or not isinstance(account_data, dict):
                            print(f"⚠️ accountデータが不正: message_id={message_id}")
                            account_id = None
                            sender_name = "ゲスト"
                        else:
                            account_id = account_data.get("account_id")
                            sender_name = account_data.get("name", "ゲスト")
                        
                        # bodyの検証と安全な処理
                        if body is None:
                            body = ""
                            print(f"⚠️ bodyがNone: message_id={message_id}")
                        
                        if not isinstance(body, str):
                            print(f"⚠️ bodyが文字列ではない: type={type(body)}, message_id={message_id}")
                            body = str(body) if body else ""
                        
                        # デバッグログ（安全なスライス）
                        print(f"🔍 メッセージチェック: message_id={message_id}")
                        print(f"   body type: {type(body)}")
                        print(f"   body length: {len(body)}")
                        
                        # 安全なbody表示（スライスエラー防止）
                        if body:
                            body_preview = body[:100] if len(body) > 100 else body
                            # 改行を置換して見やすくする
                            body_preview = body_preview.replace('\n', '\\n')
                            print(f"   body preview: {body_preview}")
                        else:
                            print(f"   body: (empty)")
                        
                        # メンション/返信チェック（安全な呼び出し）
                        try:
                            is_mention_or_reply = is_mention_or_reply_to_soulkun(body) if body else False
                            print(f"   is_mention_or_reply: {is_mention_or_reply}")
                        except Exception as e:
                            print(f"   ❌ is_mention_or_reply_to_soulkun エラー: {e}")
                            is_mention_or_reply = False
                        
                        # 5分以内のメッセージのみ処理
                        if send_time is not None:
                            try:
                                if int(send_time) < five_minutes_ago:
                                    continue
                            except (ValueError, TypeError) as e:
                                print(f"⚠️ send_time変換エラー: {send_time}, error={e}")
                        
                        # 自分自身のメッセージを無視
                        if account_id is not None and str(account_id) == MY_ACCOUNT_ID:
                            continue
                        
                        # メンションまたは返信を検出
                        if not is_mention_or_reply:
                            continue
                        
                        # 処理済みならスキップ
                        try:
                            if is_processed(message_id):
                                print(f"⏭️ すでに処理済み: message_id={message_id}")
                                continue
                        except Exception as e:
                            print(f"⚠️ 処理済みチェックエラー（続行）: {e}")
                        
                        print(f"✅ 検出成功！処理開始: room={room_id}, message_id={message_id}")
                        
                        # メッセージをDBに保存
                        try:
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
                            clean_message = clean_chatwork_message(body) if body else ""
                        except Exception as e:
                            print(f"⚠️ メッセージクリーニングエラー: {e}")
                            clean_message = body
                        
                        if clean_message:
                            try:
                                # ★★★ pending_taskのフォローアップを最初にチェック ★★★
                                pending_response = handle_pending_task_followup(clean_message, room_id, account_id, sender_name)
                                if pending_response:
                                    print(f"📋 pending_taskのフォローアップを処理")
                                    send_chatwork_message(room_id, pending_response, None, False)
                                    mark_as_processed(message_id, room_id)
                                    processed_count += 1
                                    continue
                                
                                # 通常のWebhook処理と同じ処理を実行
                                all_persons = get_all_persons_summary()
                                all_tasks = get_tasks()
                                
                                # AI司令塔に判断を委ねる
                                command = ai_commander(clean_message, all_persons, all_tasks)
                                response_language = command.get("response_language", "ja") if command else "ja"
                                
                                # アクションを実行
                                action_response = execute_action(command, sender_name, room_id, account_id)
                                
                                if action_response:
                                    send_chatwork_message(room_id, action_response, None, False)
                                else:
                                    # 通常会話として処理
                                    history = get_conversation_history(room_id, account_id)
                                    room_context = get_room_context(room_id, limit=30)
                                    
                                    context_parts = []
                                    if room_context:
                                        context_parts.append(f"【このルームの最近の会話】\n{room_context}")
                                    if all_persons:
                                        persons_str = "\n".join([f"・{p['name']}: {p['attributes']}" for p in all_persons[:5] if p.get('attributes')])
                                        if persons_str:
                                            context_parts.append(f"【覚えている人物】\n{persons_str}")
                                    
                                    context = "\n\n".join(context_parts) if context_parts else None
                                    
                                    ai_response = get_ai_response(clean_message, history, sender_name, context, response_language)
                                    
                                    if history is None:
                                        history = []
                                    history.append({"role": "user", "content": clean_message})
                                    history.append({"role": "assistant", "content": ai_response})
                                    save_conversation_history(room_id, account_id, history)
                                    
                                    send_chatwork_message(room_id, ai_response, None, False)
                                
                                processed_count += 1
                                
                            except Exception as e:
                                print(f"❌ メッセージ処理エラー: message_id={message_id}, error={e}")
                                import traceback
                                traceback.print_exc()
                        
                        # 処理済みとしてマーク
                        try:
                            mark_as_processed(message_id, room_id)
                        except Exception as e:
                            print(f"⚠️ 処理済みマークエラー: {e}")
                    
                    except Exception as e:
                        print(f"❌ メッセージ処理中に予期しないエラー: {e}")
                        import traceback
                        traceback.print_exc()
                        skipped_messages += 1
                        continue
                
            except Exception as e:
                error_rooms += 1
                print(f"❌ ルーム {room_id} の処理中にエラー: {e}")
                import traceback
                traceback.print_exc()
                continue  # 次のルームへ
        
        # サマリーログ
        print("=" * 50)
        print(f"📊 処理サマリー:")
        print(f"   - 総ルーム数: {len(rooms)}")
        print(f"   - スキップ（マイチャット）: {skipped_my}")
        print(f"   - 処理したルーム: {processed_rooms}")
        print(f"   - エラーが発生したルーム: {error_rooms}")
        print(f"   - スキップしたメッセージ: {skipped_messages}")
        print(f"   - 処理したメッセージ: {processed_count}")
        print("=" * 50)
        print(f"✅ ポーリング完了: {processed_count}件処理")
        
        return jsonify({
            "status": "ok",
            "processed_count": processed_count,
            "rooms_checked": len(rooms),
            "skipped_my": skipped_my,
            "processed_rooms": processed_rooms,
            "error_rooms": error_rooms,
            "skipped_messages": skipped_messages
        })
        
    except Exception as e:
        print(f"❌ ポーリング全体でエラー: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

# ============================================================

def get_room_tasks(room_id, status='open'):
    """
    指定されたルームのタスク一覧を取得
    
    Args:
        room_id: ルームID
        status: タスクのステータス ('open' or 'done')
    
    Returns:
        タスクのリスト
    """
    url = f"https://api.chatwork.com/v2/rooms/{room_id}/tasks"
    # ★★★ v10.4.0: 全タスク同期対応 ★★★
    # assigned_by_account_id フィルタを削除し、全ユーザーが作成したタスクを取得
    params = {
        'status': status,
    }

    headers = {"X-ChatWorkToken": get_secret("SOULKUN_CHATWORK_TOKEN")}
    response = httpx.get(url, headers=headers, params=params )
    
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Failed to get tasks for room {room_id}: {response.status_code}")
        return []

def send_completion_notification(room_id, task, assigned_by_name):
    """
    タスク完了通知を送信（個別通知）

    ★★★ v10.15.0: 無効化 ★★★
    個別グループへの完了通知を廃止。
    代わりに remind-tasks の process_completed_tasks_summary() で
    管理部チャットに1日1回まとめて報告する方式に変更。

    Args:
        room_id: ルームID
        task: タスク情報の辞書
        assigned_by_name: 依頼者名
    """
    # v10.15.0: 個別通知を無効化（管理部への日次報告に集約）
    task_id = task.get('task_id', 'unknown')
    print(f"📝 [v10.15.0] 完了通知スキップ: task_id={task_id} (管理部への日次報告に集約)")
    return

    # --- 以下は無効化（v10.15.0以前のコード） ---
    # assigned_to_name = task.get('account', {}).get('name', '担当者')
    # task_body = task.get('body', 'タスク')
    #
    # message = f"[info][title]{assigned_to_name}さんがタスクを完了しましたウル！[/title]"
    # message += f"タスク: {task_body}\n"
    # message += f"依頼者: {assigned_by_name}さん\n"
    # message += f"お疲れ様でしたウル！[/info]"
    #
    # url = f"https://api.chatwork.com/v2/rooms/{room_id}/messages"
    # data = {'body': message}
    #
    # headers = {"X-ChatWorkToken": get_secret("SOULKUN_CHATWORK_TOKEN")}
    # response = httpx.post(url, headers=headers, data=data )
    #
    # if response.status_code == 200:
    #     print(f"Completion notification sent for task {task['task_id']} in room {room_id}")
    # else:
    #     print(f"Failed to send completion notification: {response.status_code}")

def sync_room_members():
    """全ルームのメンバーをchatwork_usersテーブルに同期"""
    api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
    
    try:
        # 全ルームを取得
        rooms = get_all_rooms()
        
        if not rooms:
            print("No rooms found")
            return
        
        pool = get_pool()
        synced_count = 0
        
        for room in rooms:
            room_id = room.get("room_id")
            room_type = room.get("type")
            
            # マイチャットはスキップ
            if room_type == "my":
                continue
            
            try:
                # ルームメンバーを取得
                response = httpx.get(
                    f"https://api.chatwork.com/v2/rooms/{room_id}/members",
                    headers={"X-ChatWorkToken": api_token},
                    timeout=10.0
                )
                
                if response.status_code != 200:
                    print(f"Failed to get members for room {room_id}: {response.status_code}")
                    continue
                
                members = response.json()
                
                with pool.connect() as conn:
                    for member in members:
                        account_id = member.get("account_id")
                        name = member.get("name", "")
                        
                        if not account_id or not name:
                            continue
                        
                        # UPSERT: 存在すれば更新、なければ挿入
                        conn.execute(
                            sqlalchemy.text("""
                                INSERT INTO chatwork_users (account_id, name, room_id, updated_at)
                                VALUES (:account_id, :name, :room_id, CURRENT_TIMESTAMP)
                                ON CONFLICT (account_id) 
                                DO UPDATE SET name = :name, updated_at = CURRENT_TIMESTAMP
                            """),
                            {
                                "account_id": account_id,
                                "name": name,
                                "room_id": room_id
                            }
                        )
                        synced_count += 1
                    
                    conn.commit()
                    
            except Exception as e:
                print(f"Error syncing members for room {room_id}: {e}")
                continue
        
        print(f"Synced {synced_count} members")
        
    except Exception as e:
        print(f"Error in sync_room_members: {e}")

@app.route("/sync-chatwork-tasks", methods=["POST"])
def sync_chatwork_tasks():
    """
    Cloud Function: ChatWorkのタスクをDBと同期
    30分ごとに実行される
    """
    print("=== Starting task sync ===")
    
    # ★★★ ルームメンバー同期を追加 ★★★
    print("--- Syncing room members ---")
    sync_room_members()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Phase1開始日を取得
        cursor.execute("""
            SELECT value FROM system_config WHERE key = 'phase1_start_date'
        """)
        result = cursor.fetchone()
        phase1_start_date = datetime.strptime(result[0], '%Y-%m-%d').replace(tzinfo=JST) if result else None
        
        # 除外ルーム一覧を取得
        cursor.execute("SELECT room_id FROM excluded_rooms")
        excluded_rooms = set(row[0] for row in cursor.fetchall())
        
        # 全ルーム取得
        rooms = get_all_rooms()
        
        for room in rooms:
            room_id = room['room_id']
            room_name = room['name']
            
            # 除外ルームはスキップ
            if room_id in excluded_rooms:
                print(f"Skipping excluded room: {room_id} ({room_name})")
                continue
            
            print(f"Syncing room: {room_id} ({room_name})")
            
            # 未完了タスクを取得
            open_tasks = get_room_tasks(room_id, 'open')
            
            for task in open_tasks:
                task_id = task['task_id']
                assigned_to_id = task['account']['account_id']
                assigned_by_id = task.get('assigned_by_account', {}).get('account_id')
                body = task['body']
                limit_time = task.get('limit_time')
                
                # 名前を取得
                assigned_to_name = task['account']['name']
                # assigned_by_nameはAPIから直接取得できないため、別途取得が必要
                # ここでは簡易的に空文字列を設定（後で改善可能）
                assigned_by_name = ""
                
                # limit_timeをUNIXタイムスタンプに変換
                limit_datetime = None
                if limit_time:
                    if isinstance(limit_time, str):
                        # ISO 8601形式の文字列をUNIXタイムスタンプに変換
                        try:
                            # Python 3.7+のfromisoformatを使用（dateutilは不要）
                            # "2025-12-17T15:52:53+00:00" → datetime
                            dt = datetime.fromisoformat(limit_time.replace('Z', '+00:00'))
                            limit_datetime = int(dt.timestamp())
                            print(f"✅ Converted string to timestamp: {limit_datetime}")
                        except Exception as e:
                            print(f"❌ Failed to parse limit_time string: {e}")
                            limit_datetime = None
                    elif isinstance(limit_time, (int, float)):
                        # 既にUNIXタイムスタンプの場合
                        limit_datetime = int(limit_time)
                        print(f"✅ Already timestamp: {limit_datetime}")
                    else:
                        print(f"⚠️ Unknown limit_time type: {type(limit_time)}")
                        limit_datetime = None
                
                # skip_trackingの判定
                skip_tracking = False
                if phase1_start_date and limit_datetime:
                    # limit_datetimeはUNIXタイムスタンプなので、phase1_start_dateもタイムスタンプに変換
                    phase1_timestamp = int(phase1_start_date.timestamp())
                    if limit_datetime < phase1_timestamp:
                        skip_tracking = True
                
                # DBに存在するか確認
                cursor.execute("""
                    SELECT task_id, status FROM chatwork_tasks WHERE task_id = %s AND organization_id = %s
                """, (task_id, _ORGANIZATION_ID))
                existing = cursor.fetchone()
                
                if existing:
                    # 既存タスクの更新
                    cursor.execute("""
                        UPDATE chatwork_tasks
                        SET status = 'open',
                            body = %s,
                            limit_time = %s,
                            last_synced_at = CURRENT_TIMESTAMP,
                            room_name = %s,
                            assigned_to_name = %s
                        WHERE task_id = %s AND organization_id = %s
                    """, (body, limit_datetime, room_name, assigned_to_name, task_id, _ORGANIZATION_ID))
                else:
                    # 新規タスクの挿入
                    # ★★★ v10.18.1: summary生成（3段階フォールバック） ★★★
                    summary = None
                    if body:
                        try:
                            summary = lib_extract_task_subject(body)
                            if not lib_validate_summary(summary, body):
                                summary = lib_prepare_task_display_text(body, max_length=50)
                            if not lib_validate_summary(summary, body):
                                cleaned = lib_clean_chatwork_tags(body)
                                summary = cleaned[:40] + "..." if len(cleaned) > 40 else cleaned
                        except Exception as e:
                            print(f"⚠️ summary生成エラー（フォールバック使用）: {e}")
                            summary = body[:40] + "..." if body and len(body) > 40 else body

                    # ★★★ v10.18.1: department_id取得（Phase 3.5対応） ★★★
                    department_id = None
                    try:
                        cursor.execute("""
                            SELECT ud.department_id
                            FROM user_departments ud
                            JOIN users u ON ud.user_id = u.id
                            WHERE u.chatwork_account_id = %s
                              AND ud.is_primary = TRUE
                              AND ud.ended_at IS NULL
                            LIMIT 1
                        """, (str(assigned_to_id),))
                        dept_row = cursor.fetchone()
                        department_id = str(dept_row[0]) if dept_row else None
                    except Exception as e:
                        print(f"⚠️ department_id取得エラー（NULLで継続）: {e}")

                    cursor.execute("""
                        INSERT INTO chatwork_tasks
                        (task_id, room_id, assigned_to_account_id, assigned_by_account_id, body, limit_time, status,
                         skip_tracking, last_synced_at, room_name, assigned_to_name, assigned_by_name, summary, department_id, organization_id)
                        VALUES (%s, %s, %s, %s, %s, %s, 'open', %s, CURRENT_TIMESTAMP, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (task_id) DO NOTHING
                    """, (task_id, room_id, assigned_to_id, assigned_by_id, body,
                          limit_datetime, skip_tracking, room_name, assigned_to_name, assigned_by_name, summary, department_id, _ORGANIZATION_ID))

            # 完了タスクを取得
            done_tasks = get_room_tasks(room_id, 'done')
            
            for task in done_tasks:
                task_id = task['task_id']
                
                # DBに存在するか確認
                cursor.execute("""
                    SELECT task_id, status, completion_notified, assigned_by_name
                    FROM chatwork_tasks
                    WHERE task_id = %s AND organization_id = %s
                """, (task_id, _ORGANIZATION_ID))
                existing = cursor.fetchone()
                
                if existing:
                    old_status = existing[1]
                    completion_notified = existing[2]
                    assigned_by_name = existing[3]
                    
                    # ステータスが変更された場合
                    if old_status == 'open':
                        cursor.execute("""
                            UPDATE chatwork_tasks
                            SET status = 'done',
                                completed_at = CURRENT_TIMESTAMP,
                                last_synced_at = CURRENT_TIMESTAMP
                            WHERE task_id = %s AND organization_id = %s
                        """, (task_id, _ORGANIZATION_ID))
                        
                        # 完了通知を送信（まだ送信していない場合）
                        if not completion_notified:
                            send_completion_notification(room_id, task, assigned_by_name)
                            cursor.execute("""
                                UPDATE chatwork_tasks
                                SET completion_notified = TRUE
                                WHERE task_id = %s AND organization_id = %s
                            """, (task_id, _ORGANIZATION_ID))
        
        conn.commit()
        print("=== Task sync completed ===")
        return ('Task sync completed', 200)
        
    except Exception as e:
        conn.rollback()
        print(f"Error during task sync: {str(e)}")
        import traceback
        traceback.print_exc()
        return (f'Error: {str(e)}', 500)
        
    finally:
        cursor.close()
        conn.close()

@app.route("/remind-tasks", methods=["POST"])
def remind_tasks():
    """
    Cloud Function: タスクのリマインドを送信
    毎日8:30 JSTに実行される
    """
    print("=== Starting task reminders ===")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        now = datetime.now(JST)
        today = now.date()
        tomorrow = today + timedelta(days=1)
        three_days_later = today + timedelta(days=3)
        
        # リマインド対象のタスクを取得
        cursor.execute("""
            SELECT task_id, room_id, assigned_to_account_id, body, limit_time, room_name, assigned_to_name
            FROM chatwork_tasks
            WHERE status = 'open'
              AND skip_tracking = FALSE
              AND reminder_disabled = FALSE
              AND limit_time IS NOT NULL
              AND organization_id = %s
        """, (_ORGANIZATION_ID,))
        
        tasks = cursor.fetchall()
        
        for task in tasks:
            task_id, room_id, assigned_to_account_id, body, limit_time, room_name, assigned_to_name = task
            
            # limit_timeをdateに変換
            if isinstance(limit_time, int):
                limit_date = datetime.fromtimestamp(limit_time, tz=JST).date()
            else:
                limit_date = limit_time.date()
            
            reminder_type = None
            
            if limit_date == today:
                reminder_type = 'today'
            elif limit_date == tomorrow:
                reminder_type = 'tomorrow'
            elif limit_date == three_days_later:
                reminder_type = 'three_days'
            
            if reminder_type:
                # 今日既に同じタイプのリマインドを送信済みか確認
                cursor.execute("""
                    SELECT id FROM task_reminders
                    WHERE task_id = %s
                      AND reminder_type = %s
                      AND sent_date = %s
                """, (task_id, reminder_type, today))
                
                already_sent = cursor.fetchone()
                
                if not already_sent:
                    # リマインドメッセージを作成
                    if reminder_type == 'today':
                        message = f"[To:{assigned_to_account_id}]{assigned_to_name}さん\n今日が期限のタスクがありますウル！\n\nタスク: {body}\n期限: 今日\n\n頑張ってくださいウル！"
                    elif reminder_type == 'tomorrow':
                        message = f"[To:{assigned_to_account_id}]{assigned_to_name}さん\n明日が期限のタスクがありますウル！\n\nタスク: {body}\n期限: 明日\n\n準備はできていますかウル？"
                    elif reminder_type == 'three_days':
                        message = f"[To:{assigned_to_account_id}]{assigned_to_name}さん\n3日後が期限のタスクがありますウル！\n\nタスク: {body}\n期限: 3日後\n\n計画的に進めましょうウル！"
                    
                    # メッセージを送信
                    url = f"https://api.chatwork.com/v2/rooms/{room_id}/messages"
                    data = {'body': message}
                    headers = {"X-ChatWorkToken": get_secret("SOULKUN_CHATWORK_TOKEN")}
                    response = httpx.post(url, headers=headers, data=data )
                    
                    if response.status_code == 200:
                        # リマインド履歴を記録（重複は無視）
                        cursor.execute("""
                            INSERT INTO task_reminders (task_id, room_id, reminder_type, sent_date)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT (task_id, reminder_type, sent_date) DO NOTHING
                        """, (task_id, room_id, reminder_type, today))
                        print(f"Reminder sent: task_id={task_id}, type={reminder_type}")
                    else:
                        print(f"Failed to send reminder: {response.status_code}")
        
        conn.commit()
        print("=== Task reminders completed ===")
        return ('Task reminders completed', 200)
        
    except Exception as e:
        conn.rollback()
        print(f"Error during task reminders: {str(e)}")
        import traceback
        traceback.print_exc()
        return (f'Error: {str(e)}', 500)
        
    finally:
        cursor.close()
        conn.close()


# ========================================
# クリーンアップ機能（古いデータの自動削除）
# ========================================

@app.route("/", methods=["POST"])
def cleanup_old_data():
    """
    Cloud Function: 古いデータを自動削除
    毎日03:00 JSTに実行される

    削除対象:
    - room_messages: 30日以上前
    - processed_messages: 7日以上前
    - conversation_timestamps: 30日以上前
    - brain_decision_logs: 90日以上前
    - brain_improvement_logs: 180日以上前
    - brain_interactions: 90日以上前
    - ai_usage_logs: 90日以上前
    - brain_outcome_events: 90日以上前
    - brain_outcome_patterns: 90日以上前
    - Firestore conversations: 30日以上前
    - Firestore pending_tasks: 1日以上前
    """
    print("=" * 50)
    print("🧹 クリーンアップ処理開始")
    print("=" * 50)

    results = {
        "room_messages": 0,
        "processed_messages": 0,
        "conversation_timestamps": 0,
        "brain_decision_logs": 0,
        "brain_improvement_logs": 0,
        "brain_interactions": 0,
        "ai_usage_logs": 0,
        "brain_outcome_events": 0,
        "brain_outcome_patterns": 0,
        "firestore_conversations": 0,
        "firestore_pending_tasks": 0,
        "errors": []
    }

    now = datetime.now(timezone.utc)
    thirty_days_ago = now - timedelta(days=30)
    seven_days_ago = now - timedelta(days=7)
    one_day_ago = now - timedelta(days=1)
    ninety_days_ago = now - timedelta(days=90)
    one_eighty_days_ago = now - timedelta(days=180)
    
    # ===== PostgreSQL クリーンアップ =====
    try:
        pool = get_pool()
        with pool.connect() as conn:
            # 1. room_messages（30日以上前を削除）
            try:
                result = conn.execute(
                    sqlalchemy.text("""
                        DELETE FROM room_messages
                        WHERE created_at < :cutoff_date
                    """),
                    {"cutoff_date": thirty_days_ago}
                )
                deleted_count = result.rowcount
                results["room_messages"] = deleted_count
                print(f"✅ room_messages: {deleted_count}件削除")
            except Exception as e:
                error_msg = f"room_messages削除エラー: {type(e).__name__}"
                print(f"❌ {error_msg}")
                results["errors"].append(error_msg)
            
            # 2. processed_messages（7日以上前を削除）
            try:
                result = conn.execute(
                    sqlalchemy.text("""
                        DELETE FROM processed_messages
                        WHERE processed_at < :cutoff_date
                    """),
                    {"cutoff_date": seven_days_ago}
                )
                deleted_count = result.rowcount
                results["processed_messages"] = deleted_count
                print(f"✅ processed_messages: {deleted_count}件削除")
            except Exception as e:
                error_msg = f"processed_messages削除エラー: {type(e).__name__}"
                print(f"❌ {error_msg}")
                results["errors"].append(error_msg)
            
            # 3. conversation_timestamps（30日以上前を削除）
            try:
                result = conn.execute(
                    sqlalchemy.text("""
                        DELETE FROM conversation_timestamps
                        WHERE updated_at < :cutoff_date
                    """),
                    {"cutoff_date": thirty_days_ago}
                )
                deleted_count = result.rowcount
                results["conversation_timestamps"] = deleted_count
                print(f"✅ conversation_timestamps: {deleted_count}件削除")
            except Exception as e:
                error_msg = f"conversation_timestamps削除エラー: {type(e).__name__}"
                print(f"❌ {error_msg}")
                results["errors"].append(error_msg)

            # NOTE: brainテーブルのクリーンアップは全組織横断で実行
            # 接続ユーザー(soulkun_user)はテーブルオーナーのためRLSバイパス

            # 4. brain_decision_logs（90日以上前を削除）
            try:
                result = conn.execute(
                    sqlalchemy.text("""
                        DELETE FROM brain_decision_logs
                        WHERE created_at < :cutoff_date
                    """),
                    {"cutoff_date": ninety_days_ago}
                )
                deleted_count = result.rowcount
                results["brain_decision_logs"] = deleted_count
                print(f"✅ brain_decision_logs: {deleted_count}件削除")
            except Exception as e:
                error_msg = f"brain_decision_logs削除エラー: {type(e).__name__}"
                print(f"❌ {error_msg}")
                results["errors"].append(error_msg)

            # 5. brain_improvement_logs（180日以上前を削除）
            try:
                result = conn.execute(
                    sqlalchemy.text("""
                        DELETE FROM brain_improvement_logs
                        WHERE recorded_at < :cutoff_date
                    """),
                    {"cutoff_date": one_eighty_days_ago}
                )
                deleted_count = result.rowcount
                results["brain_improvement_logs"] = deleted_count
                print(f"✅ brain_improvement_logs: {deleted_count}件削除")
            except Exception as e:
                error_msg = f"brain_improvement_logs削除エラー: {type(e).__name__}"
                print(f"❌ {error_msg}")
                results["errors"].append(error_msg)

            # 6. brain_interactions（90日以上前を削除）
            try:
                result = conn.execute(
                    sqlalchemy.text("""
                        DELETE FROM brain_interactions
                        WHERE created_at < :cutoff_date
                    """),
                    {"cutoff_date": ninety_days_ago}
                )
                deleted_count = result.rowcount
                results["brain_interactions"] = deleted_count
                print(f"✅ brain_interactions: {deleted_count}件削除")
            except Exception as e:
                error_msg = f"brain_interactions削除エラー: {type(e).__name__}"
                print(f"❌ {error_msg}")
                results["errors"].append(error_msg)

            # 7. ai_usage_logs（90日以上前を削除）
            try:
                result = conn.execute(
                    sqlalchemy.text("""
                        DELETE FROM ai_usage_logs
                        WHERE created_at < :cutoff_date
                    """),
                    {"cutoff_date": ninety_days_ago}
                )
                deleted_count = result.rowcount
                results["ai_usage_logs"] = deleted_count
                print(f"✅ ai_usage_logs: {deleted_count}件削除")
            except Exception as e:
                error_msg = f"ai_usage_logs削除エラー: {type(e).__name__}"
                print(f"❌ {error_msg}")
                results["errors"].append(error_msg)

            # 8. brain_outcome_events（90日以上前を削除）
            try:
                result = conn.execute(
                    sqlalchemy.text("""
                        DELETE FROM brain_outcome_events
                        WHERE created_at < :cutoff_date
                    """),
                    {"cutoff_date": ninety_days_ago}
                )
                deleted_count = result.rowcount
                results["brain_outcome_events"] = deleted_count
                print(f"✅ brain_outcome_events: {deleted_count}件削除")
            except Exception as e:
                error_msg = f"brain_outcome_events削除エラー: {type(e).__name__}"
                print(f"❌ {error_msg}")
                results["errors"].append(error_msg)

            # 9. brain_outcome_patterns（90日以上前を削除）
            try:
                result = conn.execute(
                    sqlalchemy.text("""
                        DELETE FROM brain_outcome_patterns
                        WHERE created_at < :cutoff_date
                    """),
                    {"cutoff_date": ninety_days_ago}
                )
                deleted_count = result.rowcount
                results["brain_outcome_patterns"] = deleted_count
                print(f"✅ brain_outcome_patterns: {deleted_count}件削除")
            except Exception as e:
                error_msg = f"brain_outcome_patterns削除エラー: {type(e).__name__}"
                print(f"❌ {error_msg}")
                results["errors"].append(error_msg)

            conn.commit()
            
    except Exception as e:
        error_msg = f"PostgreSQL接続エラー: {type(e).__name__}"
        print(f"❌ {error_msg}")
        results["errors"].append(error_msg)
    
    # ===== Firestore クリーンアップ =====
    try:
        # conversationsコレクションから30日以上前のドキュメントを削除
        conversations_ref = db.collection("conversations")
        
        # updated_atが30日以上前のドキュメントを取得
        old_docs = conversations_ref.where(
            "updated_at", "<", thirty_days_ago
        ).stream()
        
        deleted_count = 0
        batch = db.batch()
        batch_count = 0
        
        for doc in old_docs:
            batch.delete(doc.reference)
            batch_count += 1
            deleted_count += 1
            
            # Firestoreのバッチは500件まで
            if batch_count >= 500:
                batch.commit()
                batch = db.batch()
                batch_count = 0
        
        # 残りをコミット
        if batch_count > 0:
            batch.commit()
        
        results["firestore_conversations"] = deleted_count
        print(f"✅ Firestore conversations: {deleted_count}件削除")
        
    except Exception as e:
        error_msg = f"Firestoreクリーンアップエラー: {type(e).__name__}"
        print(f"❌ {error_msg}")
        results["errors"].append(error_msg)
    
    # ===== Firestore pending_tasks クリーンアップ（NEW） =====
    try:
        pending_tasks_ref = db.collection("pending_tasks")
        
        old_pending_docs = pending_tasks_ref.where(
            "created_at", "<", one_day_ago
        ).stream()
        
        deleted_count = 0
        batch = db.batch()
        batch_count = 0
        
        for doc in old_pending_docs:
            batch.delete(doc.reference)
            batch_count += 1
            deleted_count += 1
            
            if batch_count >= 500:
                batch.commit()
                batch = db.batch()
                batch_count = 0
        
        if batch_count > 0:
            batch.commit()
        
        results["firestore_pending_tasks"] = deleted_count
        print(f"✅ Firestore pending_tasks: {deleted_count}件削除")
        
    except Exception as e:
        error_msg = f"Firestore pending_tasksクリーンアップエラー: {type(e).__name__}"
        print(f"❌ {error_msg}")
        results["errors"].append(error_msg)
    
    # ===== サマリー =====
    print("=" * 50)
    print("📊 クリーンアップ結果:")
    print(f"   - room_messages: {results['room_messages']}件削除")
    print(f"   - processed_messages: {results['processed_messages']}件削除")
    print(f"   - conversation_timestamps: {results['conversation_timestamps']}件削除")
    print(f"   - brain_decision_logs: {results['brain_decision_logs']}件削除")
    print(f"   - brain_improvement_logs: {results['brain_improvement_logs']}件削除")
    print(f"   - brain_interactions: {results['brain_interactions']}件削除")
    print(f"   - ai_usage_logs: {results['ai_usage_logs']}件削除")
    print(f"   - brain_outcome_events: {results['brain_outcome_events']}件削除")
    print(f"   - brain_outcome_patterns: {results['brain_outcome_patterns']}件削除")
    print(f"   - Firestore conversations: {results['firestore_conversations']}件削除")
    print(f"   - Firestore pending_tasks: {results['firestore_pending_tasks']}件削除")
    if results["errors"]:
        print(f"   - エラー: {len(results['errors'])}件")
        for err in results["errors"]:
            print(f"     ・{err}")
    print("=" * 50)
    print("🧹 クリーンアップ完了")
    
    return jsonify({
        "status": "ok" if not results["errors"] else "partial",
        "results": results
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
