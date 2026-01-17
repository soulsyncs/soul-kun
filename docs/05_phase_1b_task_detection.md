# 第12章：実装手順書【新設】

## 12.0 Phase 1-Bの実装手順【v10.1.3追加】【v10.1.4更新】

### ■ Phase 1-B実装の全体スケジュール

| Week | Day | 作業内容 | 時間 | 担当 |
|------|-----|---------|------|------|
| 任意 | 1 | tasksテーブル拡張＋notification_logsテーブル作成【v10.1.4更新】 | 2h | 吉澤 |
| 任意 | 1-2 | GET /tasks/overdue API実装（ページネーション対応）【v10.1.4更新】 | 3h | 吉澤 |
| 任意 | 2 | daily_overdue_reminder.py実装 | 4h | 吉澤 |
| 任意 | 2-3 | Cloud Scheduler設定＋テスト | 2h | 吉澤 |
| 任意 | 3 | 本番デプロイ＋監視設定 | 1h | 吉澤 |

**合計工数:** 12時間

---

### ■ Step 1: データベースマイグレーション（2時間）

**【v10.1.4更新】2つのマイグレーション方法**

| 方法 | 対象テーブル | メリット | デメリット |
|------|------------|---------|----------|
| **A. v10.1.3版**（最小限） | reminder_logs | Phase 1-Bだけなら十分 | Phase 2.5で再マイグレーション必要 |
| **B. v10.1.4版**（推奨） | notification_logs | Phase 2.5時の手戻りなし | 初期実装が若干複雑 |

**推奨: 方法B（v10.1.4版）を採用**

理由:
- Phase 2.5時の手戻り8時間を削減
- 将来の機能拡張に完全対応
- v10.1.4の戦略的意義に合致

---

**1-1. マイグレーションファイル作成**

```bash
# v10.1.4版マイグレーションファイル生成
$ alembic revision -m "add_notification_system_v10_1_4"
```

**1-2. マイグレーション実装（v10.1.4版）**

```python
# migrations/versions/xxx_add_notification_system_v10_1_4.py

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'xxx_add_notification_system_v10_1_4'
down_revision = 'previous_revision_id'

def upgrade():
    # 1. tasksテーブルにnotification_room_idカラム追加
    op.add_column('tasks', 
        sa.Column('notification_room_id', sa.String(20), nullable=True,
                  comment='ChatWork通知先ルームID。NULLの場合は管理部ルーム'))
    
    # 2. notification_logsテーブル作成（v10.1.4拡張版）
    op.create_table('notification_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, 
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), 
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False,
                  comment='組織ID（マルチテナント対応）'),
        
        # 通知タイプと対象
        sa.Column('notification_type', sa.String(50), nullable=False,
                  comment='task_reminder, goal_reminder, meeting_reminder, system_notification'),
        sa.Column('target_type', sa.String(50), nullable=False,
                  comment='task, goal, meeting, system'),
        sa.Column('target_id', postgresql.UUID(as_uuid=True), nullable=True,
                  comment='対象ID（systemの場合はNULL）'),
        
        # 通知日時
        sa.Column('notification_date', sa.Date(), nullable=False,
                  comment='通知日（YYYY-MM-DD）'),
        sa.Column('sent_at', sa.TIMESTAMP(timezone=True), nullable=False, 
                  server_default=sa.text('NOW()')),
        
        # ステータス
        sa.Column('status', sa.String(20), nullable=False,
                  comment='success, failed, skipped'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), server_default='0',
                  comment='リトライ回数'),
        
        # 通知先
        sa.Column('channel', sa.String(20), nullable=True,
                  comment='chatwork, email, slack'),
        sa.Column('channel_target', sa.String(255), nullable=True,
                  comment='room_id, email address, channel_id'),
        
        # メタデータ
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), 
                  server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), 
                  server_default=sa.text('NOW()')),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), 
                  sa.ForeignKey('users.id'), nullable=True),
        
        # 冪等性確保のUNIQUE制約
        sa.UniqueConstraint('organization_id', 'target_type', 'target_id', 
                           'notification_date', 'notification_type',
                           name='unique_notification'),
        
        comment='汎用通知送信履歴。v10.1.4で拡張: タスク、目標、会議など、あらゆる通知に対応'
    )
    
    # 3. インデックス作成
    op.create_index('idx_notification_logs_org', 'notification_logs', ['organization_id'])
    op.create_index('idx_notification_logs_target', 'notification_logs', ['target_type', 'target_id'])
    op.create_index('idx_notification_logs_date', 'notification_logs', ['notification_date'])
    op.create_index('idx_notification_logs_status', 'notification_logs', ['status'],
                    postgresql_where=sa.text("status = 'failed'"))
    
    # 4. tasksテーブルのパフォーマンス最適化インデックス
    op.create_index('idx_tasks_org_due_status', 'tasks', 
                    ['organization_id', 'due_date', 'status'])

def downgrade():
    op.drop_index('idx_tasks_org_due_status', 'tasks')
    op.drop_index('idx_notification_logs_status', 'notification_logs')
    op.drop_index('idx_notification_logs_date', 'notification_logs')
    op.drop_index('idx_notification_logs_target', 'notification_logs')
    op.drop_index('idx_notification_logs_org', 'notification_logs')
    op.drop_table('notification_logs')
    op.drop_column('tasks', 'notification_room_id')
```

**1-3. マイグレーション実行**

```bash
# 本番環境で実行
$ alembic upgrade head

# ロールバック方法（万が一）
$ alembic downgrade -1
```

---

### ■ 【参考】v10.1.3版マイグレーション（最小限実装）

v10.1.4版を採用する場合は不要ですが、参考までに記載します。

```python
# v10.1.3版（reminder_logsテーブル）
def upgrade():
    # tasksテーブル拡張
    op.add_column('tasks', 
        sa.Column('notification_room_id', sa.String(20), nullable=True))
    
    # reminder_logsテーブル作成（タスク専用）
    op.create_table('reminder_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, 
                  server_default=sa.text('uuid_generate_v4()')),
        sa.Column('task_id', postgresql.UUID(as_uuid=True), 
                  sa.ForeignKey('tasks.task_id', ondelete='CASCADE'), nullable=False),
        sa.Column('remind_date', sa.Date(), nullable=False),
        sa.Column('sent_at', sa.TIMESTAMP(timezone=True), nullable=False, 
                  server_default=sa.text('NOW()')),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), 
                  server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), 
                  server_default=sa.text('NOW()')),
        sa.UniqueConstraint('task_id', 'remind_date', 
                           name='unique_task_remind_date')
    )
    
    # インデックス
    op.create_index('idx_reminder_logs_task', 'reminder_logs', ['task_id'])
    op.create_index('idx_reminder_logs_date', 'reminder_logs', ['remind_date'])
    op.create_index('idx_tasks_org_due_status', 'tasks', 
                    ['organization_id', 'due_date', 'status'])
```

---

### ■ Step 2: API実装（3時間）

**2-1. エンドポイント追加**

```python
# app/routers/tasks.py

from fastapi import APIRouter, Depends, HTTPException
from datetime import date, datetime
from typing import List

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])

@router.get("/overdue")
async def get_overdue_tasks(
    organization_id: str,
    grace_days: int = 0,
    api_key: str = Depends(verify_api_key)
):
    """
    期限超過タスク一覧を取得
    
    Args:
        organization_id: 組織ID
        grace_days: 猶予日数（0=当日から、1=翌日から）
    
    Returns:
        期限超過タスクのリスト
    """
    
    # 1. 組織存在チェック
    org = await Organization.get_or_none(id=organization_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    
    # 2. 期限超過タスクを取得
    cutoff_date = date.today() - timedelta(days=grace_days)
    
    overdue_tasks = await db.fetch_all("""
        SELECT 
            t.task_id,
            t.title,
            t.description,
            t.due_date,
            CURRENT_DATE - t.due_date AS days_overdue,
            t.priority,
            t.status,
            t.notification_room_id,
            u.user_id AS assigned_user_id,
            u.name AS assigned_user_name,
            u.email AS assigned_user_email,
            c.user_id AS created_by_user_id,
            c.name AS created_by_name,
            t.created_at
        FROM tasks t
        INNER JOIN users u ON t.assigned_to = u.user_id
        INNER JOIN users c ON t.created_by = c.user_id
        WHERE 
            t.organization_id = :org_id
            AND t.due_date < :cutoff_date
            AND t.status NOT IN ('completed', 'cancelled')
        ORDER BY t.due_date ASC, t.priority DESC
    """, {"org_id": organization_id, "cutoff_date": cutoff_date})
    
    # 3. レスポンス整形
    return {
        "overdue_tasks": [
            {
                "task_id": task["task_id"],
                "title": task["title"],
                "description": task["description"],
                "due_date": task["due_date"].isoformat(),
                "days_overdue": task["days_overdue"],
                "priority": task["priority"],
                "status": task["status"],
                "assigned_to": {
                    "user_id": task["assigned_user_id"],
                    "name": task["assigned_user_name"],
                    "email": task["assigned_user_email"]
                },
                "notification_room_id": task["notification_room_id"],
                "created_by": {
                    "user_id": task["created_by_user_id"],
                    "name": task["created_by_name"]
                },
                "created_at": task["created_at"].isoformat()
            }
            for task in overdue_tasks
        ],
        "total_count": len(overdue_tasks),
        "checked_at": datetime.utcnow().isoformat()
    }
```

---

### ■ Step 3: スケジューラー実装（4時間）

**3-1. daily_overdue_reminder.py作成**

```python
# schedulers/daily_overdue_reminder.py

import os
import asyncio
from datetime import date
import httpx
import asyncpg
from typing import List, Dict

# 環境変数（必須チェック）
REQUIRED_ENV_VARS = [
    'DATABASE_URL',
    'CHATWORK_API_TOKEN',
    'CHATWORK_MANAGEMENT_ROOM_ID',
    'API_BASE_URL',
    'API_KEY',
    'ORGANIZATION_ID'  # v10.1.4追加: notification_logsのために必須
]

def check_env_vars():
    """必須環境変数チェック"""
    missing = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
    if missing:
        raise EnvironmentError(f"Missing required environment variables: {missing}")

# 環境変数
DATABASE_URL = os.getenv('DATABASE_URL')
CHATWORK_API_TOKEN = os.getenv('CHATWORK_API_TOKEN')
CHATWORK_MANAGEMENT_ROOM_ID = os.getenv('CHATWORK_MANAGEMENT_ROOM_ID')
API_BASE_URL = os.getenv('API_BASE_URL', 'https://api.soulsyncs.jp')
API_KEY = os.getenv('API_KEY')
ORGANIZATION_ID = os.getenv('ORGANIZATION_ID', 'org_soulsyncs')
GRACE_DAYS = int(os.getenv('GRACE_DAYS', '0'))
SEND_EMPTY_REPORTS = os.getenv('SEND_EMPTY_REPORTS', 'false').lower() == 'true'

async def fetch_overdue_tasks() -> List[Dict]:
    """期限超過タスクをAPIから取得"""
    url = f"{API_BASE_URL}/api/v1/tasks/overdue"
    params = {
        'organization_id': ORGANIZATION_ID,
        'grace_days': GRACE_DAYS
    }
    headers = {'Authorization': f'Bearer {API_KEY}'}
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()
        return data['overdue_tasks']

async def send_chatwork_message(room_id: str, message: str) -> bool:
    """ChatWorkメッセージ送信"""
    url = f"https://api.chatwork.com/v2/rooms/{room_id}/messages"
    headers = {'X-ChatWorkToken': CHATWORK_API_TOKEN}
    data = {'body': message}
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, data=data)
        return response.status_code == 200

async def log_notification(
    conn: asyncpg.Connection, 
    organization_id: str,
    notification_type: str,
    target_type: str,
    target_id: str, 
    notification_date: date, 
    status: str,
    channel: str = 'chatwork',
    channel_target: str = None,
    error_msg: str = None
):
    """
    通知ログ記録（UPSERT）
    
    v10.1.4: reminder_logs → notification_logs に拡張
    Phase 2.5（目標達成支援）、Phase C（会議リマインド）にも対応
    """
    await conn.execute("""
        INSERT INTO notification_logs (
            organization_id, 
            notification_type, 
            target_type, 
            target_id, 
            notification_date, 
            status, 
            sent_at, 
            error_message,
            retry_count,
            channel,
            channel_target
        )
        VALUES ($1, $2, $3, $4, $5, $6, NOW(), $7, 0, $8, $9)
        ON CONFLICT (organization_id, target_type, target_id, notification_date, notification_type) 
        DO UPDATE SET 
            status = EXCLUDED.status,
            sent_at = NOW(),
            error_message = EXCLUDED.error_message,
            retry_count = notification_logs.retry_count + 1,
            updated_at = NOW()
    """, 
        organization_id,
        notification_type,
        target_type,
        target_id,
        notification_date,
        status,
        error_msg,
        channel,
        channel_target
    )

async def main():
    """メイン処理"""
    check_env_vars()  # 環境変数チェック
    
    conn = await asyncpg.connect(DATABASE_URL)
    today = date.today()
    
    try:
        # 1. 期限超過タスク取得
        tasks = await fetch_overdue_tasks()
        
        if not tasks and not SEND_EMPTY_REPORTS:
            print("No overdue tasks. Skipping notification.")
            return
        
        # 2. タスクごとにリマインド送信
        for task in tasks:
            task_id = task['task_id']
            title = task['title']
            due_date = task['due_date']
            days_overdue = task['days_overdue']
            priority = task['priority']
            room_id = task['notification_room_id'] or CHATWORK_MANAGEMENT_ROOM_ID
            
            # メッセージ作成
            message = f"""[info][title]【期限超過タスクのリマインド】[/title]
以下のタスクの期限が過ぎています：

📌 {title}
   期限: {due_date}（{days_overdue}日超過）
   優先度: {priority}

タスクの完了または期限の延長をお願いします。
{API_BASE_URL}/tasks/{task_id}[/info]"""
            
            # ChatWork送信
            try:
                success = await send_chatwork_message(room_id, message)
                if success:
                    # v10.1.4: notification_logsに記録
                    await log_notification(
                        conn, 
                        ORGANIZATION_ID,  # organization_id
                        'task_reminder',  # notification_type
                        'task',           # target_type
                        task_id,          # target_id
                        today,            # notification_date
                        'success',        # status
                        'chatwork',       # channel
                        room_id           # channel_target
                    )
                    print(f"✅ Sent reminder for task {task_id}")
                else:
                    await log_notification(
                        conn, 
                        ORGANIZATION_ID, 
                        'task_reminder', 
                        'task', 
                        task_id, 
                        today, 
                        'failed', 
                        'chatwork', 
                        room_id,
                        'ChatWork API error'
                    )
                    print(f"❌ Failed to send reminder for task {task_id}")
            except Exception as e:
                await log_notification(
                    conn, 
                    ORGANIZATION_ID, 
                    'task_reminder', 
                    'task', 
                    task_id, 
                    today, 
                    'failed', 
                    'chatwork', 
                    room_id,
                    str(e)
                )
                print(f"❌ Error sending reminder for task {task_id}: {e}")
        
        # 3. サマリー送信（オプション）
        if tasks and SEND_EMPTY_REPORTS:
            summary = f"【本日のリマインド送信完了】\n送信件数: {len(tasks)}件"
            await send_chatwork_message(CHATWORK_MANAGEMENT_ROOM_ID, summary)
    
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
```

---

### ■ Step 4: Cloud Scheduler設定（2時間）

**4-1. Cloud Runジョブ作成**

```bash
# Dockerfileビルド
$ docker build -t gcr.io/soulsyncs-project/daily-overdue-reminder:latest .

# Cloud Runジョブデプロイ
$ gcloud run jobs create daily-overdue-reminder \
    --image gcr.io/soulsyncs-project/daily-overdue-reminder:latest \
    --region asia-northeast1 \
    --set-env-vars DATABASE_URL=xxx,CHATWORK_API_TOKEN=xxx,API_KEY=xxx \
    --max-retries 3 \
    --task-timeout 10m
```

**4-2. Cloud Scheduler設定**

```bash
# 毎日朝9時（JST）実行
$ gcloud scheduler jobs create http daily-overdue-reminder-trigger \
    --schedule="0 9 * * *" \
    --time-zone="Asia/Tokyo" \
    --uri="https://asia-northeast1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/soulsyncs-project/jobs/daily-overdue-reminder:run" \
    --http-method=POST \
    --oidc-service-account-email=scheduler@soulsyncs-project.iam.gserviceaccount.com
```

---

### ■ Step 5: テスト＋監視（1時間）

**5-1. 手動テスト**

```bash
# Cloud Runジョブ手動実行
$ gcloud run jobs execute daily-overdue-reminder --region asia-northeast1

# ログ確認
$ gcloud logs read --filter="resource.labels.job_name=daily-overdue-reminder" --limit=50
```

**5-2. 監視アラート設定**

```yaml
# Cloud Monitoring Alert Policy
displayName: "Daily Overdue Reminder - Execution Failure"
conditions:
  - displayName: "Job Failed"
    conditionThreshold:
      filter: |
        resource.type="cloud_run_job"
        resource.labels.job_name="daily-overdue-reminder"
        metric.type="run.googleapis.com/job/completed_execution_count"
        metric.labels.result="failed"
      comparison: COMPARISON_GT
      thresholdValue: 0
      duration: 60s
notificationChannels:
  - "projects/soulsyncs-project/notificationChannels/email-admin"
```

---


---

**[📁 目次に戻る](00_README.md)**
