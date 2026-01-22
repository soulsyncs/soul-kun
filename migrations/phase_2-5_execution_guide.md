# Phase 2.5 マイグレーション実行ガイド

**作成日:** 2026-01-23
**作成者:** Claude Code
**設計書:** docs/05_phase2-5_goal_achievement.md (v1.5)

---

## 1. 概要

Phase 2.5「目標達成支援」のデータベーステーブルを作成するマイグレーションです。

### 作成されるテーブル

| テーブル | 説明 |
|---------|------|
| `goals` | 目標管理（個人・部署・会社目標） |
| `goal_progress` | 日次進捗記録（17時の振り返り） |
| `goal_reminders` | リマインド設定（通知タイミング） |
| `audit_logs` | 監査ログ（confidential以上の操作記録） |

---

## 2. 事前準備

### 2.1 バックアップの取得

```bash
# Cloud SQL のバックアップを取得
gcloud sql backups create --instance=soulkun-db --description="Before Phase 2.5 migration"

# バックアップの確認
gcloud sql backups list --instance=soulkun-db
```

### 2.2 接続確認

```bash
# Cloud SQL に接続
gcloud sql connect soulkun-db --user=postgres

# 接続後、データベースを確認
\c soulkun
\dt
```

---

## 3. マイグレーション実行

### 3.1 Cloud SQL への接続

```bash
gcloud sql connect soulkun-db --user=postgres
```

パスワードを入力してログインします。

### 3.2 マイグレーションの実行

```sql
-- データベースを選択
\c soulkun

-- マイグレーションファイルを実行
\i /path/to/phase_2-5_cloudsql.sql
```

または、ローカルからファイルを読み込んで実行:

```bash
# ローカルからCloud SQLにマイグレーションを実行
cat migrations/phase_2-5_cloudsql.sql | gcloud sql connect soulkun-db --user=postgres --database=soulkun
```

### 3.3 実行結果の確認

各STEPで確認クエリが実行されます。以下の項目を確認してください:

1. **STEP 1:** 事前確認 - 依存テーブル（organizations, users, departments, notification_logs）が存在すること
2. **STEP 2-5:** テーブル作成 - 各テーブルが作成されたこと
3. **STEP 6:** 最終確認 - 全テーブルの構造、外部キー制約、インデックスが正しいこと

---

## 4. 確認クエリ

### 4.1 テーブル存在確認

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('goals', 'goal_progress', 'goal_reminders', 'audit_logs')
ORDER BY table_name;
```

期待結果: 4件のテーブルが表示される

### 4.2 goalsテーブルの構造確認

```sql
SELECT
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'goals'
  AND table_schema = 'public'
ORDER BY ordinal_position;
```

期待結果: 22カラムが表示される

### 4.3 CHECK制約の確認

```sql
SELECT
    tc.constraint_name,
    tc.table_name,
    cc.check_clause
FROM information_schema.table_constraints tc
JOIN information_schema.check_constraints cc
    ON tc.constraint_name = cc.constraint_name
WHERE tc.table_name IN ('goals', 'goal_progress', 'goal_reminders', 'audit_logs')
  AND tc.constraint_type = 'CHECK'
ORDER BY tc.table_name, tc.constraint_name;
```

期待結果: 以下のCHECK制約が表示される
- `check_goal_level`
- `check_goal_type`
- `check_goal_status`
- `check_period_type`
- `check_goal_classification`
- `check_period_range`
- `check_goal_progress_classification`
- `check_reminder_type`
- `check_audit_log_classification`

### 4.4 外部キー制約の確認

```sql
SELECT
    tc.table_name,
    kcu.column_name,
    ccu.table_name AS foreign_table_name,
    ccu.column_name AS foreign_column_name
FROM information_schema.table_constraints AS tc
JOIN information_schema.key_column_usage AS kcu
    ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage AS ccu
    ON ccu.constraint_name = tc.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND tc.table_name IN ('goals', 'goal_progress', 'goal_reminders', 'audit_logs')
ORDER BY tc.table_name, kcu.column_name;
```

期待結果: 各テーブルの外部キー参照が正しく設定されていること

---

## 5. ロールバック手順

問題が発生した場合は、以下の手順でロールバックします。

### 5.1 トランザクション中の場合

```sql
ROLLBACK;
```

### 5.2 コミット後の場合

```sql
-- 注意: データが存在する場合は削除されます
-- 本番環境では慎重に実行してください

-- 1. audit_logsテーブルを削除
DROP TABLE IF EXISTS audit_logs CASCADE;

-- 2. goal_remindersテーブルを削除
DROP TABLE IF EXISTS goal_reminders CASCADE;

-- 3. goal_progressテーブルを削除
DROP TABLE IF EXISTS goal_progress CASCADE;

-- 4. goalsテーブルを削除
DROP TABLE IF EXISTS goals CASCADE;

-- 確認
SELECT table_name FROM information_schema.tables
WHERE table_name IN ('goals', 'goal_progress', 'goal_reminders', 'audit_logs')
  AND table_schema = 'public';
-- 結果が0件なら成功
```

---

## 6. 次のステップ

マイグレーション完了後、以下の作業を進めます:

1. **lib/goal.py** - 目標管理サービスの作成
2. **lib/goal_notification.py** - 通知サービスの作成
3. **chatwork-webhook/main.py** - 目標登録対話の追加
4. **remind-tasks/main.py** - 17時/8時/18時の定期実行処理追加
5. **Cloud Scheduler設定** - 定期実行ジョブの設定

---

## 7. トラブルシューティング

### 7.1 「relation "organizations" does not exist」エラー

organizations テーブルが存在しない場合に発生します。
Phase 3以降のマイグレーションが完了しているか確認してください。

```sql
SELECT COUNT(*) FROM organizations;
```

### 7.2 「duplicate key value violates unique constraint」エラー

既にテーブルが存在する場合に発生する可能性があります。
`IF NOT EXISTS` を使用しているため、通常は発生しませんが、
既存のテーブルを確認してください。

```sql
SELECT table_name FROM information_schema.tables
WHERE table_name IN ('goals', 'goal_progress', 'goal_reminders', 'audit_logs');
```

### 7.3 接続エラー

Cloud SQL への接続に問題がある場合:

```bash
# Cloud SQL Admin API が有効か確認
gcloud services list --enabled | grep sqladmin

# 接続IPがホワイトリストに登録されているか確認
gcloud sql instances describe soulkun-db --format="value(settings.ipConfiguration.authorizedNetworks)"
```

---

## 8. チェックリスト

- [ ] バックアップを取得した
- [ ] Cloud SQL に接続できた
- [ ] マイグレーションを実行した
- [ ] 4つのテーブルが作成された（goals, goal_progress, goal_reminders, audit_logs）
- [ ] CHECK制約が正しく設定された
- [ ] 外部キー制約が正しく設定された
- [ ] インデックスが正しく設定された
- [ ] SQLAlchemy ORMモデルを確認した（api/app/models/goal.py）

---

**作成者:** Claude Code
**Co-Authored-By:** Claude Opus 4.5 <noreply@anthropic.com>
