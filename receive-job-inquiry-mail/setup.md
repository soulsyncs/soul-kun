# receive-job-inquiry-mail セットアップ手順

このサービスは「求人媒体からの応募通知メールを自動でChatWorkに集約する」仕組みです。

---

## 仕組みの概要

```
Indeed/Wantedly等 → メール送信 → Gmail受信
    → Gmail Pub/Sub → このCloud Runサービス → ChatWorkグループに投稿
```

---

## セットアップ手順（初回のみ）

### 手順1: Secret Managerにシークレットを追加

```bash
# 1-a. ChatWork APIトークン（既存の場合はスキップ）
gcloud secrets create chatwork-api-token \
  --replication-policy="automatic"
echo -n "YOUR_CHATWORK_API_TOKEN" | \
  gcloud secrets versions add chatwork-api-token --data-file=-

# 1-b. Gmail サービスアカウントのJSONキー
gcloud secrets create gmail-service-account-json \
  --replication-policy="automatic"
gcloud secrets versions add gmail-service-account-json \
  --data-file=path/to/service-account-key.json
```

### 手順2: Gmailサービスアカウントの設定

1. Google Cloud Console → IAMとサービスアカウント → 新規作成
2. ロール: 「なし」（Gmail APIはDomain-wide delegationで制御）
3. JSON鍵を作成してダウンロード → 手順1-bでSecret Managerに保存
4. Google Workspace管理画面 → セキュリティ → API制御 → 全権限
   - クライアントID: サービスアカウントのクライアントID
   - スコープ: `https://www.googleapis.com/auth/gmail.readonly`

### 手順3: Cloud Pub/Subトピックを作成

```bash
# トピック作成
gcloud pubsub topics create gmail-job-inquiry-notifications

# Gmail APIにPub/Subへの発行権限を付与
gcloud pubsub topics add-iam-policy-binding \
  gmail-job-inquiry-notifications \
  --member="serviceAccount:gmail-api-push@system.gserviceaccount.com" \
  --role="roles/pubsub.publisher"
```

### 手順4: Cloud RunサービスをPub/Subのpushサブスクリプションに登録

```bash
# まずCloud Runにデプロイ（後述）してURLを取得してから実行
CLOUD_RUN_URL="https://receive-job-inquiry-mail-xxxxx-an.a.run.app"

gcloud pubsub subscriptions create gmail-job-inquiry-sub \
  --topic=gmail-job-inquiry-notifications \
  --push-endpoint="${CLOUD_RUN_URL}/receive" \
  --ack-deadline=60
```

### 手順5: Gmail watchを設定（Pythonで実行）

```python
# 初回1回だけ実行（7日ごとに再実行が必要 → Cloud Schedulerで自動化）
from gmail_client import GmailClient
client = GmailClient("recruit@soulsyncs.jp")
client.setup_watch("projects/YOUR_PROJECT_ID/topics/gmail-job-inquiry-notifications")
```

### 手順6: Cloud Runにデプロイ

```bash
# soul-kunリポジトリのルートから実行
gcloud builds submit \
  --config=receive-job-inquiry-mail/cloudbuild.yaml \
  --project=YOUR_PROJECT_ID
```

または手動ビルド＆デプロイ:

```bash
# Dockerビルド
docker build -f receive-job-inquiry-mail/Dockerfile -t gcr.io/PROJECT_ID/receive-job-inquiry-mail .

# Cloud Runデプロイ
gcloud run deploy receive-job-inquiry-mail \
  --image=gcr.io/PROJECT_ID/receive-job-inquiry-mail \
  --region=asia-northeast1 \
  --platform=managed \
  --no-allow-unauthenticated \
  --set-env-vars="RECRUIT_CHATWORK_ROOM_ID=YOUR_ROOM_ID,RECRUIT_GMAIL_ADDRESS=recruit@soulsyncs.jp,GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID" \
  --service-account=YOUR_SERVICE_ACCOUNT@PROJECT.iam.gserviceaccount.com
```

---

## 環境変数

| 変数名 | 説明 | 例 |
|--------|------|-----|
| `RECRUIT_CHATWORK_ROOM_ID` | 通知先のChatWorkグループID | `123456789` |
| `RECRUIT_GMAIL_ADDRESS` | 監視するGmailアドレス | `recruit@soulsyncs.jp` |
| `GOOGLE_CLOUD_PROJECT` | GCPプロジェクトID | `soulsyncs-prod` |

---

## 動作テスト

```bash
# ローカルでdry-runテスト
curl -X POST http://localhost:8080/test \
  -H "Content-Type: application/json" \
  -d '{
    "raw_email": "From: noreply@indeed.com\nSubject: 山田太郎さんがあなたの求人【スタッフコーディネーター】に応募しました\n\nメッセージ本文",
    "dry_run": true
  }'
```

---

## Gmail watch の7日ごと更新（Cloud Scheduler設定）

Gmail watch() は7日で期限切れになるため、6日ごとに再設定が必要です。

```bash
# Cloud Schedulerジョブを作成（6日ごとに /setup-watch エンドポイントを叩く）
gcloud scheduler jobs create http gmail-watch-renewal \
  --schedule="0 9 */6 * *" \
  --uri="${CLOUD_RUN_URL}/setup-watch" \
  --http-method=POST \
  --time-zone="Asia/Tokyo"
```

対応するエンドポイントは `main.py` に `/setup-watch` を追加してください。
