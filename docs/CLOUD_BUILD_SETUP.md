# Cloud Build 自動デプロイ設定ガイド

## 概要

mainブランチへのマージ時に、自動でCloud Functionsにデプロイする設定です。

## 設定手順

### Step 1: GitHub接続の設定（GCPコンソール）

1. [Cloud Build トリガー](https://console.cloud.google.com/cloud-build/triggers?project=soulkun-production) を開く

2. 「リポジトリを接続」をクリック

3. 「GitHub (Cloud Build GitHub アプリ)」を選択

4. GitHubにログインし、`soulsyncs/soul-kun` リポジトリへのアクセスを許可

### Step 2: トリガーの作成（GCPコンソール）

1. 「トリガーを作成」をクリック

2. 以下の設定を入力：

| 項目 | 値 |
|------|-----|
| **名前** | `chatwork-webhook-auto-deploy` |
| **リージョン** | `グローバル（非リージョン）` |
| **イベント** | `ブランチにpush` |
| **ソース** | `soulsyncs/soul-kun` |
| **ブランチ** | `^main$` |
| **構成** | `Cloud Build 構成ファイル` |
| **ファイルの場所** | `cloudbuild.yaml` |

3. 「含まれるファイル」フィルタを追加：
   ```
   chatwork-webhook/**
   lib/brain/**
   lib/feature_flags.py
   ```

4. 「作成」をクリック

### Step 3: テスト

1. ブランチを作成してPRを出す
2. mainにマージする
3. Cloud Buildが自動実行されることを確認

## 仕組み

```
mainにマージ
    ↓
Cloud Build トリガー発火
    ↓
cloudbuild.yaml 実行
    ↓
1. lib/同期チェック
    ↓
2. gcloud functions deploy
    ↓
自動デプロイ完了
```

## 確認方法

```bash
# トリガー一覧
gcloud builds triggers list --region=global

# ビルド履歴
gcloud builds list --limit=10

# 特定ビルドのログ
gcloud builds log <BUILD_ID>
```

## トラブルシューティング

### ビルドが失敗する場合

1. Cloud Build サービスアカウントに権限が必要：
   - Cloud Functions 管理者
   - サービスアカウントユーザー

```bash
# 権限付与
gcloud projects add-iam-policy-binding soulkun-production \
  --member="serviceAccount:898513057014@cloudbuild.gserviceaccount.com" \
  --role="roles/cloudfunctions.admin"

gcloud projects add-iam-policy-binding soulkun-production \
  --member="serviceAccount:898513057014@cloudbuild.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"
```

### lib/同期エラーの場合

```bash
# ローカルで同期
make sync

# コミット＆プッシュ
git add .
git commit -m "fix: lib/ 同期"
git push
```
