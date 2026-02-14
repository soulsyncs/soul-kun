# Cloud Build 自動デプロイ設定ガイド

## 概要

mainブランチへのマージ時に、自動でCloud Runサービスにデプロイする設定です。
変更されたファイルに応じて、該当サービスのみがビルド・デプロイされます。

## 対象Cloud Runサービス

| サービス | 構成ファイル | トリガー名 | 監視対象 |
|---------|-------------|-----------|---------|
| chatwork-webhook | cloudbuild.yaml | chatwork-webhook-auto-deploy | chatwork-webhook/**, lib/** |
| proactive-monitor | cloudbuild-proactive-monitor.yaml | proactive-monitor-auto-deploy | proactive-monitor/**, lib/** |
| soulkun-mcp-server | cloudbuild-mcp-server.yaml | mcp-server-auto-deploy | mcp-server/**, lib/**, chatwork-webhook/handlers/** |
| soulkun-mobile-api | cloudbuild-mobile-api.yaml | mobile-api-auto-deploy | mobile-api/**, lib/**, chatwork-webhook/handlers/** |

## 仕組み

```
mainにマージ
    ↓
Cloud Build トリガー発火（変更ファイルでフィルタ）
    ↓
cloudbuild-*.yaml 実行
    ↓
1. テスト・SQL検証（chatwork-webhookのみ）
    ↓
2. Docker build（Artifact Registry へ push）
    ↓
3. gcloud run deploy（Cloud Runサービス更新）
    ↓
4. トラフィックルーティング確認
    ↓
自動デプロイ完了
```

## Artifact Registry

| 項目 | 値 |
|------|-----|
| リポジトリ | `asia-northeast1-docker.pkg.dev/soulkun-production/cloud-run/` |
| イメージ | chatwork-webhook, proactive-monitor, soulkun-mcp-server, soulkun-mobile-api |

## 確認方法

```bash
# トリガー一覧
gcloud builds triggers list --region=asia-northeast1 --project=soulkun-production

# ビルド履歴
gcloud builds list --limit=10 --region=asia-northeast1

# 特定ビルドのログ
gcloud builds log <BUILD_ID> --region=asia-northeast1

# Cloud Runサービスの状態
gcloud run services list --region=asia-northeast1

# 最新リビジョン確認
gcloud run revisions list --service=chatwork-webhook --region=asia-northeast1 --limit=3
```

## トラブルシューティング

### ビルドが失敗する場合

Cloud Build サービスアカウントに以下の権限が必要：
- **Cloud Run 管理者** (`roles/run.admin`)
- **サービスアカウントユーザー** (`roles/iam.serviceAccountUser`)
- **Artifact Registry 書き込み** (`roles/artifactregistry.writer`)

```bash
# 権限付与
PROJECT_NUM=$(gcloud projects describe soulkun-production --format='value(projectNumber)')
SA="${PROJECT_NUM}@cloudbuild.gserviceaccount.com"

gcloud projects add-iam-policy-binding soulkun-production \
  --member="serviceAccount:${SA}" --role="roles/run.admin"

gcloud projects add-iam-policy-binding soulkun-production \
  --member="serviceAccount:${SA}" --role="roles/iam.serviceAccountUser"

gcloud projects add-iam-policy-binding soulkun-production \
  --member="serviceAccount:${SA}" --role="roles/artifactregistry.writer"
```

### Docker buildが失敗する場合

Apple Silicon (ARM) のMacではCloud Run用のamd64イメージをローカルビルドできません。
Cloud Buildが自動でGCP上（amd64）でビルドするため、通常は問題になりません。

手動でビルドが必要な場合：
```bash
gcloud builds submit --config=cloudbuild.yaml . --region=asia-northeast1
```

### トラフィックが切り替わらない場合

```bash
# 最新リビジョンに100%ルーティング
LATEST=$(gcloud run revisions list --service=chatwork-webhook --region=asia-northeast1 \
  --sort-by='~creationTimestamp' --limit=1 --format='value(name)')
gcloud run services update-traffic chatwork-webhook --region=asia-northeast1 \
  --to-revisions="${LATEST}=100"
```

## 注意事項

- 環境変数は `--update-env-vars` を使うこと（`--set-env-vars` は全変数を上書きするため禁止）
- Langfuse環境変数はCloud Runサービスに直接設定済み（cloudbuild.yamlには含めない）
