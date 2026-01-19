# Phase 3 試験運用ガイド

ナレッジ検索機能の試験運用手順書です。

## 目次

1. [概要](#概要)
2. [デプロイ前準備](#デプロイ前準備)
3. [デプロイ手順](#デプロイ手順)
4. [検索APIの使い方](#検索apiの使い方)
5. [試験運用の手順](#試験運用の手順)
6. [トラブルシューティング](#トラブルシューティング)

---

## 概要

### システム構成

```
┌─────────────────────────────────────────────────────────────────┐
│                     Phase 3 ナレッジ検索                         │
│                                                                  │
│  ┌─────────────────┐     ┌──────────────┐     ┌──────────────┐  │
│  │ Google Drive    │────▶│ Cloud        │────▶│ PostgreSQL   │  │
│  │ (マニュアル)     │     │ Functions    │     │ (Cloud SQL)  │  │
│  └─────────────────┘     │watch_google  │     └──────────────┘  │
│          │               │_drive        │            │          │
│          │               └──────────────┘            │          │
│          │                      │                    │          │
│          ▼                      ▼                    ▼          │
│  ┌─────────────────┐     ┌──────────────┐     ┌──────────────┐  │
│  │ OpenAI          │◀────│ Pinecone     │◀────│ FastAPI      │  │
│  │ (Embedding)     │     │ (Vector DB)  │     │ (検索API)    │  │
│  └─────────────────┘     └──────────────┘     └──────────────┘  │
│                                                       ▲          │
│                                                       │          │
│                                               ┌──────────────┐   │
│                                               │ ユーザー      │   │
│                                               │ (API経由)    │   │
│                                               └──────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 機能一覧

| 機能 | 説明 | エンドポイント |
|------|------|---------------|
| ナレッジ検索 | 自然言語でドキュメントを検索 | POST `/api/v1/knowledge/search` |
| フィードバック | 検索結果への評価を登録 | POST `/api/v1/knowledge/feedback` |
| ドキュメント一覧 | 登録ドキュメントの確認 | GET `/api/v1/knowledge/documents` |
| ドキュメント詳細 | 特定ドキュメントの詳細 | GET `/api/v1/knowledge/documents/{id}` |

---

## デプロイ前準備

### 1. GCP Secret Manager にシークレットを登録

```bash
# OpenAI API キー
echo -n "sk-your-openai-key" | gcloud secrets create OPENAI_API_KEY --data-file=-

# Pinecone API キー
echo -n "your-pinecone-key" | gcloud secrets create PINECONE_API_KEY --data-file=-

# (必要な場合) DB パスワード
echo -n "your-db-password" | gcloud secrets create cloudsql-password --data-file=-
```

### 2. Pinecone インデックスの作成

Pinecone Console (https://app.pinecone.io) で新規インデックスを作成:

| 設定項目 | 値 |
|---------|-----|
| Index Name | `soulkun-knowledge` |
| Dimensions | `1536` |
| Metric | `cosine` |
| Cloud | `AWS` |
| Region | `us-east-1` |

### 3. Google Drive フォルダの準備

1. **監視対象フォルダの作成**
   - Google Drive で「ソウルシンクス/ナレッジ」等のフォルダを作成
   - フォルダ構造でカテゴリと機密区分を決定

2. **フォルダIDの取得**
   - フォルダを開いたときのURL: `https://drive.google.com/drive/folders/XXXXX`
   - `XXXXX` 部分がフォルダID

3. **推奨フォルダ構造**
   ```
   ナレッジ/
   ├── 01_理念・哲学/          → カテゴリ: A, 機密区分: internal
   ├── 02_業務マニュアル/       → カテゴリ: B, 機密区分: internal
   ├── 03_就業規則/            → カテゴリ: C, 機密区分: internal
   ├── 04_テンプレート/        → カテゴリ: D, 機密区分: internal
   └── 06_サービス情報/        → カテゴリ: F, 機密区分: public
   ```

### 4. サービスアカウントの設定

```bash
# サービスアカウントにドライブへの読み取り権限を付与
# Google Admin Console で共有ドライブへのアクセス権限を設定
```

### 5. データベースマイグレーション

```bash
# Cloud SQL に接続
gcloud sql connect soulkun-db --user=postgres

# マイグレーション実行
\i migrations/phase_3_knowledge_cloudsql.sql
```

---

## デプロイ手順

### 1. Cloud Functions (watch_google_drive) のデプロイ

```bash
cd watch-google-drive

# env-vars.yaml を設定
cp env-vars.yaml.example env-vars.yaml
# エディタで ROOT_FOLDER_ID 等を設定

# デプロイ
gcloud functions deploy watch_google_drive \
    --runtime python311 \
    --trigger-http \
    --allow-unauthenticated=false \
    --timeout=540 \
    --memory=512MB \
    --region=asia-northeast1 \
    --env-vars-file=env-vars.yaml
```

### 2. Cloud Scheduler の設定

```bash
# 5分ごとに実行するジョブを作成
gcloud scheduler jobs create http watch-google-drive-job \
    --location=asia-northeast1 \
    --schedule="*/5 * * * *" \
    --uri="https://asia-northeast1-soulkun-production.cloudfunctions.net/watch_google_drive" \
    --http-method=POST \
    --oidc-service-account-email=scheduler-sa@soulkun-production.iam.gserviceaccount.com \
    --message-body='{"organization_id":"org_soulsyncs","root_folder_id":"YOUR_FOLDER_ID"}'
```

### 3. FastAPI (Cloud Run) のデプロイ

```bash
cd api

# デプロイ
gcloud run deploy soulkun-api \
    --source=. \
    --region=asia-northeast1 \
    --allow-unauthenticated=false \
    --set-env-vars="PROJECT_ID=soulkun-production,PINECONE_INDEX_NAME=soulkun-knowledge,ENVIRONMENT=production" \
    --set-secrets="OPENAI_API_KEY=OPENAI_API_KEY:latest,PINECONE_API_KEY=PINECONE_API_KEY:latest"
```

### 4. 初回フルシンクの実行

```bash
# 初回は全ファイルを取り込み
curl -X POST \
    -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
    -H "Content-Type: application/json" \
    -d '{"organization_id":"org_soulsyncs","root_folder_id":"YOUR_FOLDER_ID","full_sync":true}' \
    https://asia-northeast1-soulkun-production.cloudfunctions.net/watch_google_drive
```

---

## 検索APIの使い方

### エンドポイント

**URL:** `POST /api/v1/knowledge/search`

**必須ヘッダー:**
```
X-User-ID: ユーザーID
X-Tenant-ID: org_soulsyncs
Content-Type: application/json
```

### 基本的な検索

```bash
curl -X POST "https://soulkun-api-xxxxx.run.app/api/v1/knowledge/search" \
    -H "X-User-ID: user_kazu" \
    -H "X-Tenant-ID: org_soulsyncs" \
    -H "Content-Type: application/json" \
    -d '{
        "query": "経費精算の手順を教えてください",
        "top_k": 5
    }'
```

### レスポンス例

```json
{
    "query": "経費精算の手順を教えてください",
    "results": [
        {
            "chunk_id": "550e8400-e29b-41d4-a716-446655440000",
            "pinecone_id": "org_soulsyncs_doc123_v1_chunk0",
            "score": 0.92,
            "content": "経費精算の手順は以下の通りです。\n1. 経費精算システムにログイン\n2. 「新規申請」をクリック\n3. 必要事項を入力...",
            "page_number": 1,
            "section_title": "1. 経費精算の基本",
            "document": {
                "document_id": "doc123",
                "title": "経費精算マニュアル",
                "file_name": "経費精算マニュアル.pdf",
                "category": "B",
                "classification": "internal",
                "google_drive_web_view_link": "https://drive.google.com/file/d/xxx/view"
            }
        }
    ],
    "total_results": 1,
    "search_log_id": "log_abc123",
    "top_score": 0.92,
    "average_score": 0.92,
    "answer_refused": false,
    "search_time_ms": 150,
    "total_time_ms": 200
}
```

### カテゴリフィルタ付き検索

```bash
curl -X POST "https://soulkun-api-xxxxx.run.app/api/v1/knowledge/search" \
    -H "X-User-ID: user_kazu" \
    -H "X-Tenant-ID: org_soulsyncs" \
    -H "Content-Type: application/json" \
    -d '{
        "query": "MVVとは何ですか",
        "categories": ["A"],
        "top_k": 3
    }'
```

### カテゴリ一覧

| カテゴリ | 内容 |
|---------|------|
| A | 理念・哲学（MVV、3軸、行動指針） |
| B | 業務マニュアル |
| C | 就業規則 |
| D | テンプレート |
| E | 顧客情報 |
| F | サービス情報 |

### フィードバック登録

検索結果が役に立った/立たなかった場合:

```bash
curl -X POST "https://soulkun-api-xxxxx.run.app/api/v1/knowledge/feedback" \
    -H "X-User-ID: user_kazu" \
    -H "X-Tenant-ID: org_soulsyncs" \
    -H "Content-Type: application/json" \
    -d '{
        "search_log_id": "log_abc123",
        "feedback_type": "helpful",
        "rating": 5,
        "comment": "とても分かりやすかったです"
    }'
```

**フィードバックタイプ:**
- `helpful`: 役に立った
- `not_helpful`: 役に立たなかった
- `wrong`: 間違っている
- `incomplete`: 情報が不完全
- `outdated`: 情報が古い

### ドキュメント一覧の確認

```bash
curl -X GET "https://soulkun-api-xxxxx.run.app/api/v1/knowledge/documents?page=1&page_size=10" \
    -H "X-User-ID: user_kazu" \
    -H "X-Tenant-ID: org_soulsyncs"
```

---

## 試験運用の手順

### フェーズ 1: カズさんによる動作確認（1-2日）

**確認項目:**

- [ ] Google Drive からのファイル取り込み
  - 同期ログの確認: `google_drive_sync_logs` テーブル
  - ドキュメント登録の確認: `documents` テーブル

- [ ] 検索機能の動作確認
  - 基本検索のテスト
  - カテゴリフィルタのテスト
  - スコア閾値の確認

- [ ] フィードバック機能の確認

**確認SQL:**

```sql
-- 同期ログの確認
SELECT sync_id, status, files_added, files_updated, files_failed, completed_at
FROM google_drive_sync_logs
ORDER BY created_at DESC
LIMIT 10;

-- ドキュメント一覧
SELECT title, category, classification, total_chunks, processing_status
FROM documents
WHERE organization_id = 'org_soulsyncs'
ORDER BY created_at DESC;

-- 検索ログの確認
SELECT query, result_count, top_score, answer_refused, created_at
FROM knowledge_search_logs
ORDER BY created_at DESC
LIMIT 20;
```

### フェーズ 2: 幹部数名での試験運用（1-2週間）

**対象ユーザー:**
- カズさん
- 選定した幹部 3-5名

**使用シナリオ:**
1. 日常業務で疑問が生じたときに検索
2. 新入社員への説明時に参照
3. ルール確認時に使用

**評価ポイント:**
- 検索精度（top_score の分布）
- 回答拒否率（answer_refused の割合）
- ユーザーフィードバックの傾向

**週次レビュー項目:**

```sql
-- 検索統計（週次）
SELECT
    DATE(created_at) as date,
    COUNT(*) as search_count,
    AVG(top_score) as avg_top_score,
    SUM(CASE WHEN answer_refused THEN 1 ELSE 0 END) as refused_count,
    SUM(CASE WHEN has_feedback THEN 1 ELSE 0 END) as feedback_count
FROM knowledge_search_logs
WHERE created_at >= NOW() - INTERVAL '7 days'
GROUP BY DATE(created_at)
ORDER BY date;

-- フィードバック集計
SELECT
    feedback_type,
    COUNT(*) as count,
    AVG(rating) as avg_rating
FROM knowledge_feedback
WHERE created_at >= NOW() - INTERVAL '7 days'
GROUP BY feedback_type;

-- よく検索されるクエリ
SELECT query, COUNT(*) as count
FROM knowledge_search_logs
WHERE created_at >= NOW() - INTERVAL '7 days'
GROUP BY query
ORDER BY count DESC
LIMIT 20;
```

### フェーズ 3: 全社展開の判断

**展開基準:**
- 平均 top_score >= 0.7
- 回答拒否率 <= 30%
- フィードバック positive_rate >= 70%

---

## トラブルシューティング

### 検索結果が出ない

**考えられる原因:**
1. ドキュメントが未インデックス
2. Pinecone 接続エラー
3. エンベディング生成エラー

**確認手順:**
```sql
-- ドキュメントの処理状態確認
SELECT processing_status, COUNT(*)
FROM documents
WHERE organization_id = 'org_soulsyncs'
GROUP BY processing_status;

-- インデックス状態確認
SELECT is_indexed, COUNT(*)
FROM document_chunks
WHERE organization_id = 'org_soulsyncs'
GROUP BY is_indexed;
```

### 同期が失敗する

**ログ確認:**
```sql
SELECT sync_id, status, error_message, failed_files
FROM google_drive_sync_logs
WHERE status = 'failed'
ORDER BY created_at DESC
LIMIT 5;
```

**よくある原因:**
- Google Drive API のレート制限
- サービスアカウントの権限不足
- ファイルサイズが大きすぎる

### スコアが低い

**改善策:**
1. チャンクサイズの調整（`CHUNK_SIZE` 環境変数）
2. オーバーラップの調整（`CHUNK_OVERLAP` 環境変数）
3. ドキュメントの品質向上（見出し、構造の整理）

---

## 設定項目一覧

### 環境変数

| 変数名 | 説明 | デフォルト |
|--------|------|-----------|
| `ROOT_FOLDER_ID` | 監視対象の Google Drive フォルダID | （必須） |
| `ORGANIZATION_ID` | 組織ID | `org_soulsyncs` |
| `CHUNK_SIZE` | チャンクサイズ（文字数） | `1000` |
| `CHUNK_OVERLAP` | オーバーラップ（文字数） | `200` |
| `KNOWLEDGE_SEARCH_TOP_K` | デフォルト検索結果数 | `5` |
| `KNOWLEDGE_SEARCH_SCORE_THRESHOLD` | スコア閾値 | `0.7` |
| `KNOWLEDGE_REFUSE_ON_LOW_SCORE` | 低スコア時に回答拒否 | `true` |
| `ENABLE_DEPARTMENT_ACCESS_CONTROL` | 部署アクセス制御（Phase 3.5） | `false` |

### 推奨チューニング値

| 項目 | 推奨値 | 説明 |
|------|--------|------|
| チャンクサイズ | 800-1200 | 小さすぎると文脈が失われる |
| オーバーラップ | 15-25% | チャンクサイズの15-25%程度 |
| スコア閾値 | 0.65-0.75 | 厳しすぎると検索結果が少なくなる |

---

## サポート連絡先

- 技術的な問題: Slack #soul-kun-dev
- ドキュメント追加依頼: Slack #knowledge-management
