# 開発環境セットアップガイド

このドキュメントでは、ソウルくんの開発環境をゼロから構築する手順を説明します。

---

## 前提条件

以下がインストールされていることを確認してください。

| ツール | バージョン | インストール方法 |
|--------|-----------|-----------------|
| **Python** | 3.11以上 | `brew install python@3.11` |
| **Git** | 最新版 | `brew install git` |
| **Google Cloud SDK** | 最新版 | [公式サイト](https://cloud.google.com/sdk/docs/install) |

---

## Step 1: リポジトリのクローン

```bash
git clone git@github.com:soulsyncs/soul-kun.git
cd soul-kun
```

> **SSH鍵の設定が必要な場合**: [GitHub SSH設定ガイド](https://docs.github.com/ja/authentication/connecting-to-github-with-ssh)

---

## Step 2: Python仮想環境のセットアップ

```bash
# 仮想環境を作成
python3.11 -m venv venv

# 仮想環境を有効化
source venv/bin/activate

# 依存パッケージをインストール
pip install --upgrade pip
pip install -r requirements.txt
pip install -r tests/requirements-test.txt
```

---

## Step 3: 環境変数の設定

### 3-1. テンプレートをコピー

```bash
cp .env.example .env
```

### 3-2. シークレットを設定

`.env` ファイルを編集し、以下の値を設定してください。

**カズさんから共有されるシークレット:**

| 環境変数 | 説明 | 取得元 |
|---------|------|--------|
| `SOULKUN_DB_PASSWORD` | Cloud SQL パスワード | カズさんから共有 |
| `GOOGLE_AI_API_KEY` | Gemini API キー（Embedding用、無料） | [Google AI Studio](https://aistudio.google.com/apikey) で発行可能 |
| `PINECONE_API_KEY` | Pinecone API キー | カズさんから共有 |
| `CHATWORK_API_KEY` | ChatWork API トークン | カズさんから共有 |
| `OPENROUTER_API_KEY` | OpenRouter API キー（LLM用） | カズさんから共有 |

> **Gemini API キー**: 個人で発行しても可。無料枠で十分です。

---

## Step 4: GCPアクセス権限の設定

### 4-1. カズさん側の作業（1回だけ）

```bash
# GCPプロジェクトにメンバー追加
gcloud projects add-iam-policy-binding soulkun-production \
  --member="user:スタッフのメール@example.com" \
  --role="roles/editor"

# Cloud SQL接続権限
gcloud projects add-iam-policy-binding soulkun-production \
  --member="user:スタッフのメール@example.com" \
  --role="roles/cloudsql.client"

# Secret Manager読み取り権限
gcloud projects add-iam-policy-binding soulkun-production \
  --member="user:スタッフのメール@example.com" \
  --role="roles/secretmanager.secretAccessor"
```

### 4-2. スタッフ側の作業

```bash
# GCPにログイン
gcloud auth login

# アプリケーションデフォルト認証
gcloud auth application-default login

# プロジェクトを設定
gcloud config set project soulkun-production
```

---

## Step 5: ローカルDB接続（Cloud SQL Auth Proxy）

ローカルからCloud SQLに接続するには、Auth Proxyが必要です。

### 5-1. Cloud SQL Auth Proxy のインストール

**macOS (Apple Silicon):**
```bash
curl -o cloud-sql-proxy https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.8.0/cloud-sql-proxy.darwin.arm64
chmod +x cloud-sql-proxy
sudo mv cloud-sql-proxy /usr/local/bin/
```

**macOS (Intel):**
```bash
curl -o cloud-sql-proxy https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.8.0/cloud-sql-proxy.darwin.amd64
chmod +x cloud-sql-proxy
sudo mv cloud-sql-proxy /usr/local/bin/
```

### 5-2. Auth Proxy の起動

**別のターミナルで実行（開発中は常時起動）:**
```bash
cloud-sql-proxy soulkun-production:asia-northeast1:soulkun-db
```

成功すると以下のように表示されます:
```
Listening on 127.0.0.1:5432 for soulkun-production:asia-northeast1:soulkun-db
```

---

## Step 6: 動作確認

### 6-1. テストを実行

```bash
# 仮想環境が有効化されていることを確認
source venv/bin/activate

# テスト実行
pytest tests/ -v --tb=short

# 特定のテストだけ実行
pytest tests/test_brain/ -v
```

### 6-2. lib/ 同期チェック

```bash
./scripts/sync_lib.sh --check
```

### 6-3. DBに接続できるか確認

```bash
# Cloud SQL Auth Proxy が起動していることを前提
python -c "
from lib.db import get_db_connection
conn = get_db_connection()
print('DB接続成功!')
conn.close()
"
```

---

## 開発フロー

### ブランチ戦略

```
main（本番）
  └── feature/xxx（機能開発）
  └── fix/xxx（バグ修正）
```

### コミット前の確認

```bash
# lib/ が同期されているか確認
./scripts/sync_lib.sh --check

# テスト実行
pytest tests/ -v
```

### コミットメッセージ

```bash
git commit -m "feat: 機能の説明

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## よくあるトラブル

### Q: `ModuleNotFoundError: No module named 'lib'`

**A:** 仮想環境が有効化されていない可能性があります。
```bash
source venv/bin/activate
```

### Q: DB接続エラー

**A:** Cloud SQL Auth Proxy が起動しているか確認してください。
```bash
cloud-sql-proxy soulkun-production:asia-northeast1:soulkun-db
```

### Q: `Permission denied` でGCPリソースにアクセスできない

**A:** GCP認証を再実行してください。
```bash
gcloud auth login
gcloud auth application-default login
```

---

## 便利なコマンド

| コマンド | 説明 |
|---------|------|
| `pytest tests/ -v` | 全テスト実行 |
| `pytest tests/ -k "test_brain"` | 特定のテストだけ実行 |
| `./scripts/sync_lib.sh` | lib/ を各サービスに同期 |
| `./scripts/sync_lib.sh --check` | 同期状態をチェック |
| `make sync` | lib/ 同期（Makefile経由） |

---

## Claude Code（推奨）

開発にはClaude Codeの利用を推奨します。

### インストール

```bash
npm install -g @anthropic-ai/claude-code
```

### 使い方

```bash
cd soul-kun
claude
```

プロジェクトの `CLAUDE.md` が自動で読み込まれ、設計書に沿った開発ができます。

---

## 問い合わせ

セットアップで問題があれば、カズさんに連絡してください。
