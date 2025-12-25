import functions_framework
from flask import jsonify
from google.cloud import secretmanager, firestore
import httpx
import re
from datetime import datetime, timedelta, timezone
import pg8000
import sqlalchemy
from google.cloud.sql.connector import Connector
import json

PROJECT_ID = "soulkun-production"
db = firestore.Client(project=PROJECT_ID)

# Cloud SQL設定
INSTANCE_CONNECTION_NAME = "soulkun-production:asia-northeast1:soulkun-db"
DB_NAME = "soulkun_tasks"
DB_USER = "soulkun_user"

# 会話履歴の設定
MAX_HISTORY_COUNT = 10
HISTORY_EXPIRY_HOURS = 24

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
MY_ACCOUNT_ID = "8992493"

# Cloud SQL接続プール
_pool = None

def get_db_password():
    return get_secret("cloudsql-password")

def get_pool():
    global _pool
    if _pool is None:
        connector = Connector()
        def getconn():
            return connector.connect(
                INSTANCE_CONNECTION_NAME, "pg8000",
                user=DB_USER, password=get_db_password(), db=DB_NAME,
            )
        _pool = sqlalchemy.create_engine(
            "postgresql+pg8000://", creator=getconn,
            pool_size=5, max_overflow=2, pool_timeout=30, pool_recycle=1800,
        )
    return _pool

def get_secret(secret_id):
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")

def clean_chatwork_message(body):
    """ChatWorkメッセージをクリーニング"""
    clean_message = body
    clean_message = re.sub(r'\[To:\d+\]\s*[^\n\[]*(?:さん|くん|ちゃん|様|氏)?', '', clean_message)
    clean_message = re.sub(r'\[rp aid=\d+\]\[/rp\]', '', clean_message)
    clean_message = re.sub(r'\[/?[a-zA-Z]+\]', '', clean_message)
    clean_message = re.sub(r'\[.*?\]', '', clean_message)
    clean_message = clean_message.strip()
    clean_message = re.sub(r'\s+', ' ', clean_message)
    return clean_message

def is_reply_to_soulkun(body):
    """ソウルくんへの返信かどうかを判断（NEW）"""
    return f"[rp aid={MY_ACCOUNT_ID}]" in body

# ===== データベース操作関数 =====

def get_or_create_person(name):
    pool = get_pool()
    with pool.connect() as conn:
        result = conn.execute(
            sqlalchemy.text("SELECT id FROM persons WHERE name = :name"),
            {"name": name}
        ).fetchone()
        if result:
            return result[0]
        result = conn.execute(
            sqlalchemy.text("INSERT INTO persons (name) VALUES (:name) RETURNING id"),
            {"name": name}
        )
        conn.commit()
        return result.fetchone()[0]

def save_person_attribute(person_name, attribute_type, attribute_value, source="conversation"):
    person_id = get_or_create_person(person_name)
    pool = get_pool()
    with pool.connect() as conn:
        conn.execute(
            sqlalchemy.text("""
                INSERT INTO person_attributes (person_id, attribute_type, attribute_value, source, updated_at)
                VALUES (:person_id, :attr_type, :attr_value, :source, CURRENT_TIMESTAMP)
                ON CONFLICT (person_id, attribute_type) 
                DO UPDATE SET attribute_value = :attr_value, source = :source, updated_at = CURRENT_TIMESTAMP
            """),
            {"person_id": person_id, "attr_type": attribute_type, "attr_value": attribute_value, "source": source}
        )
        conn.commit()
    return True

def get_person_info(person_name):
    pool = get_pool()
    with pool.connect() as conn:
        person_result = conn.execute(
            sqlalchemy.text("SELECT id FROM persons WHERE name = :name"),
            {"name": person_name}
        ).fetchone()
        if not person_result:
            return None
        person_id = person_result[0]
        attributes = conn.execute(
            sqlalchemy.text("""
                SELECT attribute_type, attribute_value FROM person_attributes 
                WHERE person_id = :person_id ORDER BY updated_at DESC
            """),
            {"person_id": person_id}
        ).fetchall()
        return {
            "name": person_name,
            "attributes": [{"type": a[0], "value": a[1]} for a in attributes]
        }

def search_person_by_partial_name(partial_name):
    """部分一致で人物を検索"""
    pool = get_pool()
    with pool.connect() as conn:
        result = conn.execute(
            sqlalchemy.text("""
                SELECT name FROM persons 
                WHERE name ILIKE :pattern OR name ILIKE :pattern2
                ORDER BY 
                    CASE WHEN name = :exact THEN 0
                         WHEN name ILIKE :starts_with THEN 1
                         ELSE 2 END,
                    LENGTH(name)
                LIMIT 5
            """),
            {
                "pattern": f"%{partial_name}%",
                "pattern2": f"%{partial_name}%",
                "exact": partial_name,
                "starts_with": f"{partial_name}%"
            }
        ).fetchall()
        return [r[0] for r in result]

def delete_person(person_name):
    pool = get_pool()
    with pool.connect() as conn:
        trans = conn.begin()
        try:
            person_result = conn.execute(
                sqlalchemy.text("SELECT id FROM persons WHERE name = :name"),
                {"name": person_name}
            ).fetchone()
            if not person_result:
                trans.rollback()
                return False
            person_id = person_result[0]
            conn.execute(sqlalchemy.text("DELETE FROM person_attributes WHERE person_id = :person_id"), {"person_id": person_id})
            conn.execute(sqlalchemy.text("DELETE FROM person_events WHERE person_id = :person_id"), {"person_id": person_id})
            conn.execute(sqlalchemy.text("DELETE FROM persons WHERE id = :person_id"), {"person_id": person_id})
            trans.commit()
            return True
        except Exception as e:
            trans.rollback()
            print(f"削除エラー: {e}")
            return False

def get_all_persons_summary():
    pool = get_pool()
    with pool.connect() as conn:
        result = conn.execute(
            sqlalchemy.text("""
                SELECT p.name, STRING_AGG(pa.attribute_type || '=' || pa.attribute_value, ', ') as attributes
                FROM persons p
                LEFT JOIN person_attributes pa ON p.id = pa.person_id
                GROUP BY p.id, p.name ORDER BY p.name
            """)
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
            sqlalchemy.text("SELECT account_id, name FROM chatwork_users WHERE name ILIKE :pattern LIMIT 1"),
            {"pattern": f"%{name}%"}
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

# ===== 会話履歴管理 =====

def get_conversation_history(room_id, account_id):
    """会話履歴を取得（Firestore）"""
    history_ref = db.collection("conversation_history").document(f"{room_id}_{account_id}")
    doc = history_ref.get()
    if not doc.exists:
        return []
    data = doc.to_dict()
    messages = data.get("messages", [])
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=HISTORY_EXPIRY_HOURS)
    valid_messages = [m for m in messages if datetime.fromisoformat(m["timestamp"]) > cutoff_time]
    return valid_messages[-MAX_HISTORY_COUNT:]

def save_conversation_history(room_id, account_id, messages):
    """会話履歴を保存（Firestore）"""
    history_ref = db.collection("conversation_history").document(f"{room_id}_{account_id}")
    history_ref.set({"messages": messages, "updated_at": datetime.now(timezone.utc).isoformat()})

def add_message_to_history(room_id, account_id, role, content):
    """メッセージを履歴に追加"""
    history = get_conversation_history(room_id, account_id)
    history.append({"role": role, "content": content, "timestamp": datetime.now(timezone.utc).isoformat()})
    save_conversation_history(room_id, account_id, history[-MAX_HISTORY_COUNT:])

# ===== AI会話 =====

def call_openrouter_api(messages, model=None):
    """OpenRouter APIを呼び出し"""
    api_key = get_secret("OPENROUTER_API_KEY")
    if model is None:
        model = MODELS["default"]
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model,
        "messages": messages
    }
    
    try:
        response = httpx.post(OPENROUTER_API_URL, json=payload, headers=headers, timeout=30.0)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            print(f"OpenRouter API エラー: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"OpenRouter API 例外: {e}")
        return None

def generate_ai_response(user_message, room_id, account_id, context_info=None):
    """AI応答を生成"""
    history = get_conversation_history(room_id, account_id)
    
    system_prompt = """あなたは「ソウルくん」という名前のAIアシスタントです。
以下の機能を持っています：
- 人物情報の記録・検索・削除
- タスク管理
- ChatWorkタスク作成
- 一般的な会話

ユーザーの要求を理解し、適切に応答してください。
人物情報やタスクに関する操作が必要な場合は、明確に指示してください。"""
    
    if context_info:
        system_prompt += f"\n\n【現在の状況】\n{context_info}"
    
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend([{"role": m["role"], "content": m["content"]} for m in history])
    messages.append({"role": "user", "content": user_message})
    
    response = call_openrouter_api(messages)
    
    if response:
        add_message_to_history(room_id, account_id, "user", user_message)
        add_message_to_history(room_id, account_id, "assistant", response)
    
    return response

# ===== メイン処理 =====

@functions_framework.http
def chatwork_webhook(request):
    """ChatWork Webhook エンドポイント"""
    try:
        data = request.get_json()
        print(f"📨 受信データ: {json.dumps(data, ensure_ascii=False)}")
        
        webhook_event = data.get("webhook_event")
        if not webhook_event:
            return jsonify({"status": "error", "message": "webhook_event が見つかりません"}), 400
        
        # メッセージ作成イベントのみ処理
        if webhook_event.get("type") != "mention_to_me":
            print(f"⏭️ スキップ: イベントタイプ = {webhook_event.get('type')}")
            return jsonify({"status": "skipped", "message": "mention_to_me 以外のイベント"}), 200
        
        room_id = webhook_event.get("room_id")
        message_id = webhook_event.get("message_id")
        account_id = webhook_event.get("from_account_id")
        body = webhook_event.get("body", "")
        
        if not all([room_id, message_id, account_id]):
            return jsonify({"status": "error", "message": "必須パラメータが不足"}), 400
        
        # メッセージをクリーニング
        clean_body = clean_chatwork_message(body)
        print(f"🧹 クリーニング後: {clean_body}")
        
        # ソウルくんへの返信かチェック
        is_reply = is_reply_to_soulkun(body)
        print(f"💬 返信チェック: {is_reply}")
        
        # AI応答生成
        ai_response = generate_ai_response(clean_body, room_id, account_id)
        
        if not ai_response:
            ai_response = "申し訳ありません。現在応答できません。"
        
        # ChatWorkに返信
        api_token = get_secret("SOULKUN_CHATWORK_TOKEN")
        send_url = f"https://api.chatwork.com/v2/rooms/{room_id}/messages"
        
        send_data = {
            "body": f"[rp aid={account_id}][/rp]\n{ai_response}"
        }
        
        send_response = httpx.post(
            send_url,
            headers={"X-ChatWorkToken": api_token},
            data=send_data,
            timeout=10.0
        )
        
        print(f"📤 送信結果: status={send_response.status_code}, body={send_response.text}")
        
        return jsonify({"status": "success", "message": "処理完了"}), 200
        
    except Exception as e:
        print(f"❌ エラー: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@functions_framework.http
def check_reply_messages(request ):
    """返信メッセージをチェック（ポーリング用）"""
    try:
        # 実装予定
        return jsonify({"status": "success", "message": "ポーリング機能は未実装"}), 200
    except Exception as e:
        print(f"ポーリングエラー: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
