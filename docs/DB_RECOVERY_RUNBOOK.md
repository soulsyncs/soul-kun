# DB Recovery Runbook

Cloud SQL (PostgreSQL) の障害復旧手順書。

## 1. 前提情報

| 項目 | 値 |
|------|-----|
| プロジェクト | `soulkun-production` |
| インスタンス | `soulkun-db` |
| リージョン | `asia-northeast1` |
| ユーザー | `soulkun_user` |
| 自動バックアップ | Cloud SQL 自動（日次、7日保持） |
| PITR | Cloud SQL トランザクションログ |

## 2. バックアップ確認

### 自動バックアップ一覧

```bash
gcloud sql backups list --instance=soulkun-db --project=soulkun-production
```

### 最新バックアップの確認

```bash
gcloud sql backups list --instance=soulkun-db --project=soulkun-production \
  --sort-by=~startTime --limit=1
```

## 3. 全体復旧（インスタンスレベル）

### 3-1. バックアップからの復旧

```bash
# バックアップIDを取得
gcloud sql backups list --instance=soulkun-db --project=soulkun-production

# 復旧実行（新インスタンスへ）
gcloud sql instances restore-backup soulkun-db \
  --backup-id=BACKUP_ID \
  --project=soulkun-production
```

**注意**: 既存インスタンスへの復旧は全データが上書きされる。可能なら新インスタンスで検証後に切り替え。

### 3-2. Point-in-Time Recovery (PITR)

特定時刻への復旧（データ投入ミス等）。

```bash
# 新インスタンスとしてクローン（特定時刻）
gcloud sql instances clone soulkun-db soulkun-db-recovery \
  --point-in-time="2026-02-09T10:00:00Z" \
  --project=soulkun-production
```

復旧後、新インスタンスでデータ確認→問題なければ本番切り替え。

## 4. 部分復旧（テーブルレベル）

特定テーブルのみ復旧する場合。

### 4-1. 手順

1. PITRで一時インスタンスを作成
2. 一時インスタンスからテーブルをダンプ
3. 本番インスタンスにリストア

```bash
# 1. 一時インスタンス作成
gcloud sql instances clone soulkun-db soulkun-db-temp \
  --point-in-time="2026-02-09T10:00:00Z" \
  --project=soulkun-production

# 2. Cloud SQL Proxy で一時インスタンスに接続
cloud-sql-proxy soulkun-production:asia-northeast1:soulkun-db-temp \
  --port=5433

# 3. 対象テーブルをダンプ
pg_dump -h 127.0.0.1 -p 5433 -U soulkun_user -d soulkun \
  -t TARGET_TABLE --data-only > /tmp/table_recovery.sql

# 4. 本番にリストア（Cloud SQL Proxy 5432で接続中）
psql -h 127.0.0.1 -p 5432 -U soulkun_user -d soulkun < /tmp/table_recovery.sql

# 5. 一時インスタンス削除
gcloud sql instances delete soulkun-db-temp --project=soulkun-production
```

## 5. 復旧後チェックリスト

復旧後、必ず以下を確認する。

### 5-1. テーブル整合性

```sql
-- テーブル数確認（期待: 60+テーブル）
SELECT COUNT(*) FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE';
```

### 5-2. RLS確認

```sql
-- RLS有効テーブル一覧
SELECT tablename, rowsecurity
FROM pg_tables
WHERE schemaname = 'public' AND rowsecurity = true
ORDER BY tablename;
```

### 5-3. org_id分離テスト

```sql
-- RLSセッション変数を設定してクエリ
SELECT set_config('app.current_organization_id', 'test-org-id', false);

-- データが見えないことを確認
SELECT COUNT(*) FROM brain_decision_logs;  -- 0であるべき
```

### 5-4. テーブル所有者確認

```sql
-- soulkun_user が所有していること
SELECT tablename, tableowner
FROM pg_tables
WHERE schemaname = 'public' AND tableowner != 'soulkun_user'
ORDER BY tablename;
```

### 5-5. アプリケーション動作確認

1. ChatWork でソウルくんにメッセージ送信 → 応答確認
2. Cloud Logging で `brain_decision_logs` への書き込みログ確認
3. proactive-monitor の Cloud Run ログ確認

## 6. 緊急連絡先

| 役割 | 連絡方法 |
|------|---------|
| 管理者（菊池） | ChatWork DM (account_id: 1728974) |
| GCP サポート | Cloud Console > Support |

## 7. マイグレーション失敗時

マイグレーションSQL実行で障害が発生した場合。

1. **ロールバックスクリプト実行**: `migrations/` に `*_rollback.sql` が存在する場合はそれを実行
2. **手動ロールバック**: ロールバックスクリプトがない場合、`BEGIN/ROLLBACK` で手動巻き戻し
3. **Cloud SQL Proxy接続**: `cloud-sql-proxy soulkun-production:asia-northeast1:soulkun-db --port=5432`
4. **DB接続**: `psql -h 127.0.0.1 -p 5432 -U soulkun_user -d soulkun`
