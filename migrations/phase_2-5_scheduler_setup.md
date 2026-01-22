# Phase 2.5 Cloud Scheduler 設定ガイド

**作成日:** 2026-01-23
**作成者:** Claude Code
**設計書:** docs/05_phase2-5_goal_achievement.md (v1.5)

---

## 1. 概要

Phase 2.5「目標達成支援」の定期通知を実行するCloud Schedulerジョブの設定ガイドです。

### スケジュール一覧

| ジョブ名 | 時刻 (JST) | 説明 |
|---------|-----------|------|
| `goal-daily-check` | 17:00 | 進捗確認（全スタッフへのDM） |
| `goal-daily-reminder` | 18:00 | 未回答リマインド（17時未回答者へのDM） |
| `goal-morning-feedback` | 08:00 | 朝フィードバック + チームサマリー |
| `goal-consecutive-unanswered` | 09:00 | 3日連続未回答アラート |

---

## 2. 事前準備

### 2.1 Cloud Functions のデプロイ

```bash
# remind-tasks ディレクトリに移動
cd remind-tasks

# Cloud Functions をデプロイ
gcloud functions deploy goal_daily_check \
  --runtime python311 \
  --trigger-http \
  --allow-unauthenticated \
  --region asia-northeast1 \
  --entry-point goal_daily_check \
  --timeout 540s \
  --memory 512MB

gcloud functions deploy goal_daily_reminder \
  --runtime python311 \
  --trigger-http \
  --allow-unauthenticated \
  --region asia-northeast1 \
  --entry-point goal_daily_reminder \
  --timeout 540s \
  --memory 512MB

gcloud functions deploy goal_morning_feedback \
  --runtime python311 \
  --trigger-http \
  --allow-unauthenticated \
  --region asia-northeast1 \
  --entry-point goal_morning_feedback \
  --timeout 540s \
  --memory 512MB

gcloud functions deploy goal_consecutive_unanswered_check \
  --runtime python311 \
  --trigger-http \
  --allow-unauthenticated \
  --region asia-northeast1 \
  --entry-point goal_consecutive_unanswered_check \
  --timeout 540s \
  --memory 512MB
```

### 2.2 サービスアカウントの確認

```bash
# デフォルトのサービスアカウントを確認
gcloud iam service-accounts list

# Cloud Scheduler が Cloud Functions を呼び出す権限を確認
gcloud projects get-iam-policy soulkun-production \
  --flatten="bindings[].members" \
  --format='table(bindings.role)' \
  --filter="bindings.members:serviceAccount"
```

---

## 3. Cloud Scheduler ジョブの作成

### 3.1 17:00 進捗確認 (goal-daily-check)

```bash
gcloud scheduler jobs create http goal-daily-check \
  --location=asia-northeast1 \
  --schedule="0 17 * * *" \
  --time-zone="Asia/Tokyo" \
  --uri="https://asia-northeast1-soulkun-production.cloudfunctions.net/goal_daily_check" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{"org_id": "org_soulsyncs"}' \
  --description="Phase 2.5: 17時進捗確認"
```

### 3.2 18:00 未回答リマインド (goal-daily-reminder)

```bash
gcloud scheduler jobs create http goal-daily-reminder \
  --location=asia-northeast1 \
  --schedule="0 18 * * *" \
  --time-zone="Asia/Tokyo" \
  --uri="https://asia-northeast1-soulkun-production.cloudfunctions.net/goal_daily_reminder" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{"org_id": "org_soulsyncs"}' \
  --description="Phase 2.5: 18時未回答リマインド"
```

### 3.3 08:00 朝フィードバック (goal-morning-feedback)

```bash
gcloud scheduler jobs create http goal-morning-feedback \
  --location=asia-northeast1 \
  --schedule="0 8 * * *" \
  --time-zone="Asia/Tokyo" \
  --uri="https://asia-northeast1-soulkun-production.cloudfunctions.net/goal_morning_feedback" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{"org_id": "org_soulsyncs"}' \
  --description="Phase 2.5: 8時朝フィードバック・チームサマリー"
```

### 3.4 09:00 連続未回答チェック (goal-consecutive-unanswered)

```bash
gcloud scheduler jobs create http goal-consecutive-unanswered \
  --location=asia-northeast1 \
  --schedule="0 9 * * *" \
  --time-zone="Asia/Tokyo" \
  --uri="https://asia-northeast1-soulkun-production.cloudfunctions.net/goal_consecutive_unanswered_check" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{"org_id": "org_soulsyncs", "consecutive_days": 3}' \
  --description="Phase 2.5: 3日連続未回答アラート"
```

---

## 4. ジョブの確認・管理

### 4.1 ジョブ一覧の確認

```bash
gcloud scheduler jobs list --location=asia-northeast1
```

### 4.2 ジョブの詳細確認

```bash
gcloud scheduler jobs describe goal-daily-check --location=asia-northeast1
```

### 4.3 手動実行（テスト）

```bash
# 17時進捗確認のテスト実行
gcloud scheduler jobs run goal-daily-check --location=asia-northeast1

# ドライランモードでテスト実行（実際には送信しない）
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{"org_id": "org_soulsyncs", "dry_run": true}' \
  https://asia-northeast1-soulkun-production.cloudfunctions.net/goal_daily_check
```

### 4.4 ジョブの一時停止・再開

```bash
# 一時停止
gcloud scheduler jobs pause goal-daily-check --location=asia-northeast1

# 再開
gcloud scheduler jobs resume goal-daily-check --location=asia-northeast1
```

### 4.5 ジョブの削除

```bash
gcloud scheduler jobs delete goal-daily-check --location=asia-northeast1
```

---

## 5. 環境変数設定

### 5.1 テストモード

本番環境でテストする際は、以下の環境変数を設定してください。

```bash
# Cloud Functions の環境変数を更新
gcloud functions deploy goal_daily_check \
  --update-env-vars DRY_RUN=true

# テスト完了後、本番モードに戻す
gcloud functions deploy goal_daily_check \
  --update-env-vars DRY_RUN=false
```

### 5.2 環境変数一覧

| 変数名 | 説明 | デフォルト |
|--------|------|-----------|
| `DRY_RUN` | ドライランモード（true=送信しない） | false |
| `TEST_ACCOUNT_ID` | テスト用アカウントID | - |
| `TEST_ROOM_ID` | テスト用ルームID | - |

---

## 6. 監視・アラート設定

### 6.1 Cloud Monitoring アラートの設定

```bash
# Cloud Functions のエラー率アラート
gcloud alpha monitoring policies create \
  --notification-channels=<CHANNEL_ID> \
  --display-name="Goal Notification Error Rate" \
  --condition-filter='resource.type="cloud_function" AND metric.type="cloudfunctions.googleapis.com/function/execution_count" AND metric.labels.status!="ok"' \
  --condition-threshold-value=5 \
  --condition-comparison=COMPARISON_GT \
  --condition-duration=300s
```

### 6.2 ログの確認

```bash
# 最新のログを確認
gcloud functions logs read goal_daily_check --limit=50

# エラーログのみ確認
gcloud functions logs read goal_daily_check --filter="severity>=ERROR"

# 特定の日付のログを確認
gcloud logging read 'resource.type="cloud_function" AND resource.labels.function_name="goal_daily_check" AND timestamp>="2026-01-23T00:00:00Z"' --limit=100
```

---

## 7. トラブルシューティング

### 7.1 「既に送信済み」でスキップされる

**原因:** `notification_logs` テーブルに当日の送信済みレコードがある

**対処:**
```sql
-- 今日の送信ログを確認
SELECT * FROM notification_logs
WHERE notification_date = CURRENT_DATE
  AND notification_type LIKE 'goal_%'
ORDER BY created_at DESC;

-- 必要に応じて削除（再送信したい場合のみ）
DELETE FROM notification_logs
WHERE notification_date = CURRENT_DATE
  AND notification_type = 'goal_daily_check'
  AND target_id = '<user_id>';
```

### 7.2 ChatWork レート制限エラー

**原因:** ChatWork API のレート制限（5分間で100リクエスト）に達した

**対処:**
- 指数バックオフで自動リトライされる
- `notification_logs.status='failed'` のレコードを確認し、手動で再実行

```sql
-- 失敗した通知を確認
SELECT * FROM notification_logs
WHERE status = 'failed'
  AND notification_type LIKE 'goal_%'
ORDER BY created_at DESC;
```

### 7.3 ユーザーに通知が届かない

**確認ポイント:**
1. ユーザーの `chatwork_room_id` が設定されているか
2. ユーザーがアクティブな目標を持っているか
3. `notification_logs` にレコードがあるか

```sql
-- ユーザーの ChatWork 設定を確認
SELECT id, display_name, chatwork_room_id
FROM users
WHERE organization_id = 'org_soulsyncs';

-- ユーザーのアクティブな目標を確認
SELECT u.display_name, g.title, g.status
FROM users u
JOIN goals g ON g.user_id = u.id
WHERE g.organization_id = 'org_soulsyncs'
  AND g.status = 'active';
```

---

## 8. チェックリスト

### 8.1 初期設定

- [ ] Cloud Functions がデプロイされた
- [ ] Cloud Scheduler ジョブが作成された
- [ ] DRY_RUN=true でテスト実行した
- [ ] 実際の通知が届くことを確認した
- [ ] DRY_RUN=false に戻した

### 8.2 本番運用開始

- [ ] 全ジョブが ENABLED 状態であることを確認
- [ ] Cloud Monitoring アラートを設定した
- [ ] カズさんに本番運用開始を報告した
- [ ] 初回の各通知が正常に送信されたことを確認

### 8.3 定期確認（週次）

- [ ] `notification_logs` の failed レコードを確認
- [ ] Cloud Functions のエラーログを確認
- [ ] ChatWork API のレート制限状況を確認

---

**作成者:** Claude Code
**Co-Authored-By:** Claude Opus 4.5 <noreply@anthropic.com>
