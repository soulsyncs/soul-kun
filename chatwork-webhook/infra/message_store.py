"""infra/message_store.py - ルームメッセージ保存・処理済み管理

Phase 11-1c: main.pyから抽出されたメッセージ保存・処理済みチェック機能。

依存: infra/db.py (get_pool)
"""

from datetime import datetime, timezone
import os
import sqlalchemy
import traceback

from infra.db import get_pool

_ORGANIZATION_ID = os.getenv("PHASE3_ORGANIZATION_ID", "5f98365f-e7c5-4f48-9918-7fe9aabae5df")



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
        with pool.begin() as conn:
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
    except Exception as e:
        print(f"メッセージ保存エラー: {e}")
        traceback.print_exc()

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
                      AND organization_id = :org_id
                    ORDER BY send_time DESC
                    LIMIT :limit
                """),
                {"room_id": room_id, "limit": limit, "org_id": _ORGANIZATION_ID}
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
        with pool.begin() as conn:
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
            print("✅ room_messagesテーブルの確認/作成完了")
    except Exception as e:
        print(f"⚠️ room_messagesテーブル作成エラー: {e}")
        traceback.print_exc()

def ensure_processed_messages_table():
    """processed_messagesテーブルが存在しない場合は作成（二重処理防止の要）"""
    try:
        pool = get_pool()
        with pool.begin() as conn:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS processed_messages (
                    message_id VARCHAR(50) PRIMARY KEY,
                    room_id BIGINT NOT NULL,
                    organization_id VARCHAR(100) NOT NULL DEFAULT '5f98365f-e7c5-4f48-9918-7fe9aabae5df',
                    processed_at TIMESTAMP WITH TIME ZONE NOT NULL
                );
            """))
            conn.execute(sqlalchemy.text("""
                CREATE INDEX IF NOT EXISTS idx_processed_messages_room_id 
                ON processed_messages(room_id);
            """))
            conn.execute(sqlalchemy.text("""
                CREATE INDEX IF NOT EXISTS idx_processed_messages_processed_at 
                ON processed_messages(processed_at);
            """))
            print("✅ processed_messagesテーブルの確認/作成完了")
    except Exception as e:
        print(f"⚠️ processed_messagesテーブル作成エラー: {e}")
        traceback.print_exc()

def mark_as_processed(message_id, room_id):
    """処理済みとしてマーク（PostgreSQL版）"""
    try:
        pool = get_pool()
        with pool.begin() as conn:
            conn.execute(
                sqlalchemy.text("""
                    INSERT INTO processed_messages (message_id, room_id, organization_id, processed_at)
                    VALUES (:message_id, :room_id, '5f98365f-e7c5-4f48-9918-7fe9aabae5df', :processed_at)
                    ON CONFLICT (message_id) DO NOTHING
                """),
                {
                    "message_id": message_id,
                    "room_id": room_id,
                    "processed_at": datetime.now(timezone.utc)
                }
            )
    except Exception as e:
        print(f"処理済みマークエラー: {e}")
        traceback.print_exc()
