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

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
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

## Step 7: Claude Code + プラグイン（推奨）

開発にはClaude Codeの利用を推奨します。プラグインにより、コードレビュー・セキュリティチェック・TDDなどが自動化されます。

### 7-1. Claude Code のインストール

```bash
npm install -g @anthropic-ai/claude-code
```

### 7-2. Claude Code の起動と認証

```bash
cd soul-kun
claude
```

初回起動時にAnthropicアカウントでの認証が求められます。

### 7-3. プラグインのインストール

Claude Code 内で以下のコマンドを実行：

```
/plugin marketplace add affaan-m/everything-claude-code
/plugin install everything-claude-code@everything-claude-code
```

または、`~/.claude/settings.json` に以下を追加：

```json
{
  "extraKnownMarketplaces": {
    "everything-claude-code": {
      "source": {
        "source": "github",
        "repo": "affaan-m/everything-claude-code"
      }
    }
  },
  "enabledPlugins": {
    "everything-claude-code@everything-claude-code": true
  }
}
```

### 7-4. プラグインで使える機能

| コマンド | 説明 |
|---------|------|
| `/plan` | 実装計画を立てる |
| `/tdd` | テスト駆動開発 |
| `/code-review` | コードレビュー |
| `/security-review` | セキュリティチェック |
| `/e2e` | E2Eテスト生成 |

**専門エージェント（自動で呼び出される）:**
- `code-reviewer`: コード品質チェック
- `security-reviewer`: 脆弱性検出
- `database-reviewer`: DB設計レビュー
- `architect`: アーキテクチャ設計
- `tdd-guide`: TDDガイド

---

## Step 8: Git Hooks + Codexレビュー

git push 時に自動でCodex（OpenAI）がコードレビューを実行します。

### 8-1. Git Hooks のインストール（重要）

**Git hooksはcloneでは引き継がれないため、手動でセットアップが必要です：**

```bash
# セットアップスクリプトを実行
./scripts/setup_hooks.sh
```

これにより以下のhooksがインストールされます：
- **pre-commit**: コミット前にlib/の同期をチェック
- **pre-push**: プッシュ前にCodexレビューを実行

### 8-2. Codex CLI のインストール

```bash
npm install -g @openai/codex
```

初回実行時にOpenAIアカウントでの認証が求められます。

### 8-3. 動作の流れ

```
git push
    ↓
pre-pushフック発動（.git/hooks/pre-push）
    ↓
codex_review_loop スクリプト実行（リポジトリ内に含まれている）
    ↓
Codex が CLAUDE.md + 設計書を参照してレビュー
    ↓
PASS → push成功
FAIL → pushブロック（修正が必要）
```

### 8-4. レビュー観点

Codexは以下の観点でレビューします：

1. **重大バグ**: ロジックエラー、クラッシュの可能性
2. **セキュリティ**: 脆弱性、情報漏洩リスク
3. **設計書との矛盾**: CLAUDE.mdの原則違反
4. **テストカバレッジ**: テスト対象の全パスをカバーしているか

### 8-5. レビューをスキップする場合（緊急時のみ）

```bash
SKIP_CODEX_REVIEW=1 git push
```

> **注意**: スキップした場合は、後で必ず手動レビューを実行してください。

---

## 開発フロー（まとめ）

```
1. ブランチ作成
   git checkout -b feature/xxx

2. コード実装
   claude  # Claude Codeで開発

3. テスト実行
   pytest tests/ -v

4. lib/ 同期（lib/を変更した場合）
   ./scripts/sync_lib.sh

5. コミット
   git add .
   git commit -m "feat: 説明"

6. プッシュ（Codexレビュー自動実行）
   git push -u origin feature/xxx

7. PR作成
   gh pr create
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
| `claude` | Claude Code起動 |
| `/plan` | 実装計画（Claude Code内） |
| `/tdd` | TDD開発（Claude Code内） |

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

### Q: Codexレビューでエラー

**A:** codex CLIがインストールされているか確認：
```bash
which codex
codex --version
```

### Q: プラグインが動かない

**A:** Claude Codeを再起動して、プラグインを再インストール：
```
/plugin install everything-claude-code@everything-claude-code
```

---

## 問い合わせ

セットアップで問題があれば、カズさんに連絡してください。
