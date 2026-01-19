# 環境変数リファレンス

Soul-kun で使用する環境変数の完全なリファレンスです。

## 目次

1. [概要](#概要)
2. [GCP プロジェクト設定](#gcp-プロジェクト設定)
3. [データベース設定](#データベース設定)
4. [シークレット管理](#シークレット管理)
5. [AI/LLM 設定](#aillm-設定)
6. [Chatwork 設定](#chatwork-設定)
7. [Phase 3: ナレッジ検索](#phase-3-ナレッジ検索)
8. [Phase 3.5: 組織階層連携](#phase-35-組織階層連携)
9. [コンポーネント別設定](#コンポーネント別設定)

---

## 概要

### 環境の種類

| 環境 | 設定方法 | シークレット管理 |
|------|----------|------------------|
| ローカル開発 | `.env` ファイル | 環境変数 |
| Cloud Functions | `env-vars.yaml` | GCP Secret Manager |
| Cloud Run | Cloud Run 設定画面 | GCP Secret Manager |

### 設定の優先順位

1. 環境変数（直接設定）
2. GCP Secret Manager（本番環境）
3. デフォルト値（`lib/config.py` で定義）

---

## GCP プロジェクト設定

### PROJECT_ID

| 項目 | 値 |
|------|-----|
| 説明 | GCP プロジェクト ID |
| デフォルト | `soulkun-production` |
| 必須 | はい |

```bash
PROJECT_ID=soulkun-production
```

### INSTANCE_CONNECTION_NAME

| 項目 | 値 |
|------|-----|
| 説明 | Cloud SQL インスタンスの接続名 |
| デフォルト | `soulkun-production:asia-northeast1:soulkun-db` |
| 形式 | `{project}:{region}:{instance}` |

```bash
INSTANCE_CONNECTION_NAME=soulkun-production:asia-northeast1:soulkun-db
```

### ENVIRONMENT

| 項目 | 値 |
|------|-----|
| 説明 | 実行環境の識別子 |
| 選択肢 | `development`, `staging`, `production` |
| デフォルト | `development` |

```bash
ENVIRONMENT=production
```

### DEBUG

| 項目 | 値 |
|------|-----|
| 説明 | デバッグモードの有効化 |
| デフォルト | `true` |

```bash
DEBUG=false
```

---

## データベース設定

### 基本設定

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `DB_NAME` | データベース名 | `soulkun_tasks` |
| `DB_USER` | 接続ユーザー名 | `soulkun_user` |
| `DB_HOST` | ホスト（ローカル開発時のみ） | `null` |
| `DB_PORT` | ポート番号 | `5432` |

### コネクションプール設定

Cloud Run 100 インスタンス対応の設計。

| 変数 | 説明 | デフォルト | 推奨値 |
|------|------|-----------|--------|
| `DB_POOL_SIZE` | プールサイズ | `5` | 3-5 |
| `DB_MAX_OVERFLOW` | 最大オーバーフロー | `2` | 2 |
| `DB_POOL_TIMEOUT` | タイムアウト（秒） | `30` | 30 |
| `DB_POOL_RECYCLE` | リサイクル間隔（秒） | `1800` | 1800 |

```bash
# 推奨設定（100インスタンス × 5接続 = 500接続）
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=2
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=1800
```

---

## シークレット管理

### ローカル開発

環境変数として設定（`.env` ファイル）:

```bash
# ★ v10.12.0: OpenAI不要、Gemini APIに統一
GOOGLE_AI_API_KEY=your-google-ai-key-here
PINECONE_API_KEY=your-pinecone-key
CHATWORK_API_KEY=your-chatwork-key
SOULKUN_DB_PASSWORD=your-db-password
```

### 本番環境（GCP Secret Manager）

シークレット名と環境変数名の対応:

| Secret Manager 名 | ローカル環境変数名 |
|-------------------|-------------------|
| `GOOGLE_AI_API_KEY` | `GOOGLE_AI_API_KEY` |
| `PINECONE_API_KEY` | `PINECONE_API_KEY` |
| `chatwork-api-key` | `CHATWORK_API_KEY` |
| `soulkun-db-password` | `SOULKUN_DB_PASSWORD` |
| `openrouter-api-key` | `OPENROUTER_API_KEY` |

シークレットの登録:

```bash
# Gemini API キー（LLM応答 + Embedding）
echo -n "AIza..." | gcloud secrets create GOOGLE_AI_API_KEY --data-file=-

# Pinecone API キー
echo -n "your-pinecone-key" | gcloud secrets create PINECONE_API_KEY --data-file=-

# DBパスワード
echo -n "your-password" | gcloud secrets create soulkun-db-password --data-file=-
```

---

## AI/LLM 設定

### OpenRouter（AI応答機能）

★ v10.12.0: Gemini 3 Flashに統一

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `OPENROUTER_API_URL` | API エンドポイント | `https://openrouter.ai/api/v1/chat/completions` |
| `DEFAULT_AI_MODEL` | 標準モデル | `google/gemini-3-flash-preview` |
| `COMMANDER_AI_MODEL` | 高度な判断用モデル | `google/gemini-3-flash-preview` |

### Gemini Embedding

★ v10.12.0: OpenAI → Gemini Embeddingに変更

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `GOOGLE_AI_API_KEY` | Google AI API キー | - |

使用モデル: `models/text-embedding-004`（768次元）

コスト: **無料**（Free Tier）

---

## Chatwork 設定

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `CHATWORK_API_KEY` | API キー（Secret Manager） | - |
| `CHATWORK_API_RATE_LIMIT` | レート制限（5分あたり） | `100` |
| `MY_ACCOUNT_ID` | ソウルくんのアカウント ID | `7399137` |
| `BOT_ACCOUNT_ID` | ボットアカウント ID | `7399137` |

### 会話履歴

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `MAX_HISTORY_COUNT` | 最大履歴件数 | `100` |
| `HISTORY_EXPIRY_HOURS` | 履歴保持時間 | `720`（30日） |

---

## Phase 3: ナレッジ検索

### Pinecone 設定

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `PINECONE_API_KEY` | Pinecone API キー | - |
| `PINECONE_INDEX_NAME` | インデックス名 | `soulkun-knowledge` |

### 検索設定

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `KNOWLEDGE_SEARCH_TOP_K` | 返す結果の最大数 | `5` |
| `KNOWLEDGE_SEARCH_SCORE_THRESHOLD` | スコア閾値（0.0-1.0） | `0.7` |
| `KNOWLEDGE_REFUSE_ON_LOW_SCORE` | 低スコア時に回答を拒否 | `true` |

```bash
# 推奨設定
KNOWLEDGE_SEARCH_TOP_K=5
KNOWLEDGE_SEARCH_SCORE_THRESHOLD=0.7
KNOWLEDGE_REFUSE_ON_LOW_SCORE=true
```

### Googleドライブ監視

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `ROOT_FOLDER_ID` | 監視対象のフォルダ ID | - |
| `ORGANIZATION_ID` | 組織 ID | `org_soulsyncs` |
| `CHUNK_SIZE` | チャンクサイズ（文字数） | `1000` |
| `CHUNK_OVERLAP` | オーバーラップ（文字数） | `200` |

```bash
# 社内マニュアルフォルダを監視
ROOT_FOLDER_ID=1ABC...xyz
ORGANIZATION_ID=org_soulsyncs
CHUNK_SIZE=1000
CHUNK_OVERLAP=200
```

---

## Phase 3.5: 組織階層連携

### ENABLE_DEPARTMENT_ACCESS_CONTROL

| 項目 | 値 |
|------|-----|
| 説明 | 部署ベースのアクセス制御を有効化 |
| デフォルト | `false` |

**設定値の意味:**

| 値 | 動作 |
|----|------|
| `false` | 機密区分（classification）のみでアクセス制御。Phase 3 単独運用時に使用。 |
| `true` | 部署ベースのアクセス制御を追加。Phase 3.5 デプロイ後に有効化。 |

```bash
# Phase 3 単独運用時
ENABLE_DEPARTMENT_ACCESS_CONTROL=false

# Phase 3.5 デプロイ後
ENABLE_DEPARTMENT_ACCESS_CONTROL=true
```

---

## コンポーネント別設定

### Cloud Functions: chatwork-webhook

```yaml
# env-vars.yaml
PROJECT_ID: soulkun-production
INSTANCE_CONNECTION_NAME: soulkun-production:asia-northeast1:soulkun-db
DB_NAME: soulkun_tasks
DB_USER: soulkun_user
MY_ACCOUNT_ID: "7399137"
BOT_ACCOUNT_ID: "7399137"
ENVIRONMENT: production
DEBUG: "false"
```

### Cloud Functions: watch-google-drive

```yaml
# env-vars.yaml
PROJECT_ID: soulkun-production
INSTANCE_CONNECTION_NAME: soulkun-production:asia-northeast1:soulkun-db
DB_NAME: soulkun_tasks
DB_USER: soulkun_user
ORGANIZATION_ID: org_soulsyncs
ROOT_FOLDER_ID: "YOUR_FOLDER_ID"
CHUNK_SIZE: "1000"
CHUNK_OVERLAP: "200"
PINECONE_INDEX_NAME: soulkun-knowledge
ENVIRONMENT: production
DEBUG: "false"
```

### Cloud Run: FastAPI (api/)

```yaml
# Cloud Run 環境変数設定
PROJECT_ID: soulkun-production
INSTANCE_CONNECTION_NAME: soulkun-production:asia-northeast1:soulkun-db
DB_NAME: soulkun_tasks
DB_USER: soulkun_user
PINECONE_INDEX_NAME: soulkun-knowledge
KNOWLEDGE_SEARCH_TOP_K: "5"
KNOWLEDGE_SEARCH_SCORE_THRESHOLD: "0.7"
KNOWLEDGE_REFUSE_ON_LOW_SCORE: "true"
ENABLE_DEPARTMENT_ACCESS_CONTROL: "false"
ENVIRONMENT: production
DEBUG: "false"
CORS_ORIGINS: "https://app.soulsyncs.co.jp"
```

---

## Cloud Scheduler 設定

### watch-google-drive トリガー

```bash
# Cloud Scheduler ジョブの作成
gcloud scheduler jobs create http watch-google-drive-job \
  --location=asia-northeast1 \
  --schedule="*/5 * * * *" \
  --uri="https://asia-northeast1-soulkun-production.cloudfunctions.net/watch_google_drive" \
  --http-method=POST \
  --oidc-service-account-email=scheduler-sa@soulkun-production.iam.gserviceaccount.com \
  --message-body='{"organization_id":"org_soulsyncs","root_folder_id":"YOUR_FOLDER_ID"}'
```

---

## セキュリティに関する注意事項

1. **絶対にコミットしないファイル:**
   - `.env`
   - `env-vars.yaml`
   - サービスアカウントキー（`*.json`）

2. **`.gitignore` に追加:**
   ```
   .env
   env-vars.yaml
   *.json
   !package.json
   ```

3. **シークレットのローテーション:**
   - API キーは定期的にローテーション
   - Secret Manager でバージョン管理

4. **最小権限の原則:**
   - 各サービスアカウントには必要最小限の権限のみ付与
