# soul-kun

ソウルくんチャットボット - Cloud Functions, DB, ChatWork連携

## 概要

ソウルくんは、ChatWork上で動作するAIチャットボットです。以下の機能を提供します：

- **人物情報管理**: 人物情報の記録・検索・削除
- **タスク管理**: タスクの作成・更新・削除
- **ChatWorkタスク作成**: ChatWork APIを使用したタスク作成
- **AI会話**: OpenRouter APIを使用した自然な会話

## 技術スタック

- **Runtime**: Python 3.11
- **Framework**: Functions Framework (Google Cloud Functions)
- **Database**: Cloud SQL (PostgreSQL) + Firestore
- **AI**: OpenRouter API (GPT-4o)
- **Integration**: ChatWork API

## ファイル構成

```
soul-kun/
├── main.py              # メインコード
├── requirements.txt     # 依存パッケージ
├── README.md           # このファイル
└── .gitignore          # Git除外設定
```

## セットアップ

### 1. 依存パッケージのインストール

```bash
pip install -r requirements.txt
```

### 2. 環境変数の設定

Google Cloud Secret Manager に以下のシークレットを設定してください：

- `cloudsql-password`: Cloud SQL のパスワード
- `SOULKUN_CHATWORK_TOKEN`: ChatWork API トークン
- `OPENROUTER_API_KEY`: OpenRouter API キー

### 3. Cloud SQL の設定

以下の情報を `main.py` で設定してください：

```python
INSTANCE_CONNECTION_NAME = "soulkun-production:asia-northeast1:soulkun-db"
DB_NAME = "soulkun_tasks"
DB_USER = "soulkun_user"
```

## デプロイ

Google Cloud Functions にデプロイ：

```bash
gcloud functions deploy chatwork-webhook \
  --runtime python311 \
  --trigger-http \
  --allow-unauthenticated \
  --entry-point chatwork_webhook \
  --region asia-northeast1
```

## 使い方

ChatWork でソウルくんにメンションすると、AI が応答します。

### コマンド例

- **人物情報の記録**: 「田中さんの誕生日は1月1日です」
- **人物情報の検索**: 「田中さんの情報を教えて」
- **タスクの作成**: 「タスクを作成して：〇〇を実施」
- **一般的な会話**: 「こんにちは」

## ライセンス

このプロジェクトは社内利用のため、ライセンスは設定されていません。

## 開発者

Soul Syncs (ソウルシンクス)
