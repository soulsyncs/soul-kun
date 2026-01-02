# ============================================
# P2-010: 週次サマリー（個人向け）
# 独立したCloud Function
# ============================================
# ファイル名: main.py
# エントリポイント: weekly_summary
# ============================================

import functions_framework
import sqlalchemy
from google.cloud.sql.connector import Connector
from google.cloud import secretmanager
import httpx
from datetime import datetime, timedelta
import time
import json

# ============================================
# 設定
# ============================================
PROJECT_ID = "soulkun-production"
INSTANCE_CONNECTION_NAME = "soulkun-production:asia-northeast1:soulkun-db"
DB_NAME = "soulkun_tasks"
DB_USER = "soulkun_user"

# グローバル変数（コネクションプール用）
connector = None
pool = None


# ============================================
# データベース接続
# ============================================

def get_secret(secret_id):
    """Secret Managerからシークレットを取得"""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")


def get_pool():
    """データベース接続プールを取得"""
    global connector, pool
    
    if pool is not None:
        return pool
    
    connector = Connector()
    
    def getconn():
        password = get_secret("cloudsql-password")
        conn = connector.connect(
            INSTANCE_CONNECTION_NAME,
            "pg8000",
            user=DB_USER,
            password=password,
            db=DB_NAME
        )
        return conn
    
    pool = sqlalchemy.create_engine(
        "postgresql+pg8000://",
        creator=getconn,
    )
    
    return pool


# ============================================
# ChatWork API
# ============================================

def get_chatwork_token():
    """ChatWorkトークンを取得"""
    return get_secret("SOULKUN_CHATWORK_TOKEN")


def send_chatwork_message(room_id, message):
    """ChatWorkにメッセージを送信"""
    api_token = get_chatwork_token()
    
    try:
        response = httpx.post(
            f"https://api.chatwork.com/v2/rooms/{room_id}/messages",
            headers={"X-ChatWorkToken": api_token},
            data={"body": message},
            timeout=10.0
        )
        return response.status_code == 200
    except Exception as e:
        print(f"[ChatWork API] エラー: {str(e)}")
        return False


# ============================================
# 週次タスク集計
# ============================================

def get_weekly_task_summary(account_id, start_date, end_date):
    """
    指定期間のタスク集計を取得（chatwork_tasksテーブル使用）
    
    Args:
        account_id: ChatWorkのaccount_id
        start_date: 集計開始日（YYYY-MM-DD形式）
        end_date: 集計終了日（YYYY-MM-DD形式）
    
    Returns:
        dict: 集計結果
    """
    db_pool = get_pool()
    
    # 日付をUNIXタイムスタンプに変換
    start_dt = datetime.strptime(start_date, '%Y-%m-%d')
    end_dt = datetime.strptime(end_date, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())
    
    with db_pool.connect() as conn:
        query = sqlalchemy.text("""
            SELECT 
                COUNT(*) as total_tasks,
                COUNT(CASE WHEN status = 'done' THEN 1 END) as completed_tasks,
                COUNT(CASE WHEN status = 'done' AND 
                    (limit_time IS NULL OR 
                     completed_at IS NULL OR 
                     EXTRACT(EPOCH FROM completed_at) <= limit_time) 
                    THEN 1 END) as on_time_completed
            FROM chatwork_tasks
            WHERE assigned_to_account_id = :account_id
            AND (
                (limit_time >= :start_ts AND limit_time <= :end_ts)
                OR 
                (status = 'done' 
                 AND completed_at >= to_timestamp(:start_ts) 
                 AND completed_at <= to_timestamp(:end_ts))
            )
        """)
        
        result = conn.execute(query, {
            'account_id': account_id,
            'start_ts': start_ts,
            'end_ts': end_ts
        }).fetchone()
        
        if result:
            total = result.total_tasks or 0
            completed = result.completed_tasks or 0
            on_time = result.on_time_completed or 0
            completion_rate = (on_time / completed * 100) if completed > 0 else 0
            
            return {
                'total_tasks': total,
                'completed_tasks': completed,
                'on_time_completed': on_time,
                'completion_rate': round(completion_rate, 1)
            }
        
        return {
            'total_tasks': 0,
            'completed_tasks': 0,
            'on_time_completed': 0,
            'completion_rate': 0
        }


# ============================================
# メッセージ生成
# ============================================

def get_encouragement_message(completion_rate):
    """
    完了率に応じた労いメッセージを返す
    
    設計書v7.2.1準拠
    """
    if completion_rate >= 100:
        return "全部期限内に完了したウル！素晴らしいウル！✨"
    elif completion_rate >= 80:
        return "ほとんど期限内に完了したウル！頑張ってるウル！💪"
    elif completion_rate >= 50:
        return "半分以上完了したウル！来週も一緒に頑張るウル！"
    else:
        return "お疲れ様ウル！困ってることがあれば相談してウル🐺"


def generate_weekly_summary_message(name, summary):
    """週次サマリーメッセージを生成"""
    encouragement = get_encouragement_message(summary['completion_rate'])
    
    message = f"""🐺 {name}さん、今週もお疲れ様ウル！

■ 今週の結果
・完了したタスク: {summary['completed_tasks']}件
・期限内完了率: {summary['completion_rate']}%

{encouragement}

困ったことや相談したいことがあれば、いつでも言ってウルね！🐺💪"""
    
    return message


# ============================================
# DMルーム取得
# ============================================

def get_dm_room_id(account_id):
    """dm_room_cacheからDMルームIDを取得"""
    db_pool = get_pool()
    
    with db_pool.connect() as conn:
        result = conn.execute(
            sqlalchemy.text("SELECT dm_room_id FROM dm_room_cache WHERE account_id = :account_id"),
            {'account_id': account_id}
        ).fetchone()
        
        return result.dm_room_id if result else None


# ============================================
# メイン処理
# ============================================

def send_weekly_summaries():
    """
    全スタッフに週次サマリーを送信
    
    設計書v7.2.1準拠:
    - 毎週金曜18:00に実行
    - その週にタスクが1件以上あった人のみ対象
    - 各スタッフの個人チャット（DM）に送信
    - ChatWork APIレート制限対策: 1秒に1通ペース
    """
    # 今週の月曜日と金曜日を計算
    today = datetime.now()
    days_since_monday = today.weekday()
    monday = (today - timedelta(days=days_since_monday)).replace(hour=0, minute=0, second=0, microsecond=0)
    friday = monday + timedelta(days=4)
    
    start_date = monday.strftime('%Y-%m-%d')
    end_date = friday.strftime('%Y-%m-%d')
    
    print(f"[週次サマリー] 集計期間: {start_date} ~ {end_date}")
    
    # 全スタッフを取得
    db_pool = get_pool()
    with db_pool.connect() as conn:
        users = conn.execute(
            sqlalchemy.text("SELECT account_id, name FROM chatwork_users")
        ).fetchall()
    
    sent_count = 0
    skip_count = 0
    error_count = 0
    no_dm_room_users = []
    
    for user in users:
        account_id = user.account_id
        name = user.name or f"ID:{account_id}"
        
        # 週次サマリーを取得
        summary = get_weekly_task_summary(account_id, start_date, end_date)
        
        # タスクが0件の人はスキップ
        if summary['total_tasks'] == 0:
            print(f"[週次サマリー] {name}: タスク0件のためスキップ")
            skip_count += 1
            continue
        
        # DMルームIDを取得
        dm_room_id = get_dm_room_id(account_id)
        
        if not dm_room_id:
            print(f"[週次サマリー] {name}: DMルームIDが見つからないためスキップ")
            no_dm_room_users.append({'account_id': account_id, 'name': name})
            skip_count += 1
            continue
        
        # メッセージを生成
        message = generate_weekly_summary_message(name, summary)
        
        # DMを送信
        try:
            success = send_chatwork_message(dm_room_id, message)
            if success:
                print(f"[週次サマリー] {name}: 送信成功（完了率: {summary['completion_rate']}%）")
                sent_count += 1
            else:
                print(f"[週次サマリー] {name}: 送信失敗")
                error_count += 1
        except Exception as e:
            print(f"[週次サマリー] {name}: エラー - {str(e)}")
            error_count += 1
        
        # レート制限対策: 1秒待機
        time.sleep(1)
    
    result = {
        'sent': sent_count,
        'skipped': skip_count,
        'errors': error_count,
        'period': f"{start_date} ~ {end_date}",
        'no_dm_room_users': no_dm_room_users
    }
    
    print(f"[週次サマリー] 完了: 送信={sent_count}, スキップ={skip_count}, エラー={error_count}")
    
    if no_dm_room_users:
        print(f"[週次サマリー] DMルームIDがないユーザー: {len(no_dm_room_users)}人")
        for u in no_dm_room_users:
            print(f"  - {u['name']} (account_id: {u['account_id']})")
    
    return result


# ============================================
# HTTPエンドポイント
# ============================================

@functions_framework.http
def weekly_summary(request):
    """
    週次サマリーを送信するHTTPエンドポイント
    
    Cloud Schedulerから毎週金曜18:00に呼び出される
    """
    print("[週次サマリー] 開始")
    
    try:
        result = send_weekly_summaries()
        
        response = {
            'status': 'success',
            'message': '週次サマリー送信完了',
            'details': result
        }
        
        print(f"[週次サマリー] 結果: {json.dumps(result, ensure_ascii=False)}")
        
        return json.dumps(response, ensure_ascii=False), 200, {'Content-Type': 'application/json'}
        
    except Exception as e:
        print(f"[週次サマリー] エラー: {str(e)}")
        import traceback
        traceback.print_exc()
        
        response = {
            'status': 'error',
            'message': str(e)
        }
        
        return json.dumps(response, ensure_ascii=False), 500, {'Content-Type': 'application/json'}
