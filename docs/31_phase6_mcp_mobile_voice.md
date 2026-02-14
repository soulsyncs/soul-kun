# Phase 6: MCP / Mobile API / Voice Pipeline 設計書

> **作成日**: 2026-02-14
> **Phase**: 戦略的改善計画 Phase 6（最終フェーズ）
> **PR**: feature/phase6-mcp-mobile

---

## 概要

Phase 6 は「ソウルくんへの入口を増やす」フェーズ。
現在は ChatWork Webhook が唯一の入口だが、以下の3つを追加する。

| コンポーネント | 役割 | ユースケース |
|---------------|------|-------------|
| **MCP Server** | Claude Desktop / Cursor 等からソウルくんのツールを使用 | 開発者・管理者が IDE から直接操作 |
| **Mobile API** | iPhoneアプリ / Web UI 用 REST API | 外出先・移動中のアクセス |
| **Voice Pipeline** | 音声対話（STT + TTS） | ハンズフリー操作、運転中 |

---

## アーキテクチャ

```
                    ┌─────────────────┐
                    │   ソウルくん Brain   │
                    │  (lib/brain/)    │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
    ┌─────────┴──────┐ ┌────┴─────┐ ┌──────┴───────┐
    │ ChatWork       │ │ MCP      │ │ Mobile API   │
    │ Webhook        │ │ Server   │ │ (FastAPI)    │
    │ (既存)         │ │ (新規)   │ │ (新規)       │
    └────────────────┘ └──────────┘ └──────┬───────┘
                                           │
                                    ┌──────┴───────┐
                                    │ Voice        │
                                    │ Pipeline     │
                                    │ (Whisper+TTS)│
                                    └──────────────┘
```

**重要**: 全ての入口は **Brain 経由** で処理される（CLAUDE.md 鉄則1: bypass禁止）。

---

## 1. MCP Server

### 設計思想

SYSTEM_CAPABILITIES（既存の機能カタログ）をMCPプロトコルで自動公開する。
二重定義を避けるため、`handlers/registry.py` がSoT（Single Source of Truth）。

### ファイル構成

| ファイル | 役割 |
|---------|------|
| `mcp-server/server.py` | MCP Server メイン（Tools / Resources / Prompts） |
| `mcp-server/requirements.txt` | 依存パッケージ |
| `mcp-server/Dockerfile` | Cloud Run デプロイ用 |
| `mcp-server/claude_desktop_config.json` | Claude Desktop 設定例 |

### MCP Tools

SYSTEM_CAPABILITIES から自動生成。現在 20+ ツールが公開される:

- タスク管理: `chatwork_task_create`, `chatwork_task_complete`, etc.
- 目標管理: `goal_create`, `goal_update`, etc.
- 文書生成: `generate_document`, `generate_report`
- リサーチ: `deep_research`
- 会議: `zoom_meeting_minutes`

### MCP Resources

| URI | 内容 |
|-----|------|
| `soulkun://tasks/active` | アクティブタスク一覧 |
| `soulkun://goals/active` | 目標一覧 |
| `soulkun://persons` | メンバー一覧（PII除外） |
| `soulkun://departments` | 部署構造 |

### MCP Prompts

| 名前 | 用途 |
|------|------|
| `ceo_feedback` | CEO視点フィードバック生成 |
| `weekly_summary` | 週次サマリー |
| `deep_research` | ディープリサーチ |

### 起動方法

```bash
# stdio モード（Claude Desktop）
python3 mcp-server/server.py

# SSE モード（HTTP経由）
python3 mcp-server/server.py --transport sse --port 8080
```

### Claude Desktop 設定

`~/Library/Application Support/Claude/claude_desktop_config.json` に追記:

```json
{
  "mcpServers": {
    "soulkun": {
      "command": "python3",
      "args": ["/path/to/soul-kun/mcp-server/server.py"]
    }
  }
}
```

---

## 2. Mobile API

### 設計思想

ChatWork 以外のクライアント（iPhoneアプリ、Web UI）向けの REST API。
JWT認証 + WebSocket リアルタイムチャット。

### エンドポイント

| Method | Path | 認証 | 説明 |
|--------|------|------|------|
| POST | `/api/v1/auth/login` | No | ログイン（JWT発行） |
| POST | `/api/v1/auth/refresh` | Yes | トークンリフレッシュ |
| POST | `/api/v1/chat` | Yes | メッセージ送信（Brain経由） |
| GET | `/api/v1/tasks` | Yes | タスク一覧 |
| GET | `/api/v1/goals` | Yes | 目標一覧 |
| GET | `/api/v1/persons` | Yes | メンバー一覧（PII除外） |
| WS | `/api/v1/ws` | Yes | WebSocket リアルタイムチャット |
| POST | `/api/v1/voice/stt` | Yes | 音声→テキスト |
| POST | `/api/v1/voice/tts` | Yes | テキスト→音声 |
| POST | `/api/v1/voice/chat` | Yes | 音声チャット（一括） |
| POST | `/api/v1/notifications/register` | Yes | プッシュ通知登録 |
| GET | `/health` | No | ヘルスチェック |

### 認証フロー

```
1. POST /api/v1/auth/login { email, password }
   → JWT token 返却（24h有効）

2. 以降のリクエストは Authorization: Bearer <token>

3. WebSocket: 接続後最初のメッセージで { "token": "<JWT>" } を送信
```

### ファイル構成

| ファイル | 役割 |
|---------|------|
| `mobile-api/main.py` | FastAPI アプリ（REST + WebSocket） |
| `mobile-api/voice.py` | 音声パイプライン（STT + TTS） |
| `mobile-api/requirements.txt` | 依存パッケージ |
| `mobile-api/Dockerfile` | Cloud Run デプロイ用 |
| `mobile-api/deploy.sh` | デプロイスクリプト |

---

## 3. Voice Pipeline

### フロー

```
ユーザー（声）
    ↓ 音声ファイル（WAV/MP3/M4A）
Whisper API（OpenAI）
    ↓ テキスト
Brain 処理
    ↓ レスポンステキスト
Google Cloud TTS
    ↓ MP3音声
ユーザー（スピーカー）
```

### STT（Speech-to-Text）

| 項目 | 値 |
|------|---|
| エンジン | OpenAI Whisper API |
| 言語 | 日本語（ja） |
| 最大ファイルサイズ | 25MB |
| 対応形式 | WAV, MP3, M4A, OGG, WebM, FLAC |
| コスト | ~$0.006/分 |

### TTS（Text-to-Speech）

| 項目 | 値 |
|------|---|
| エンジン | Google Cloud Text-to-Speech |
| 声 | ja-JP-Neural2-B（男性、ソウルくんの声） |
| 出力形式 | MP3 |
| 速度調整 | 0.5x〜2.0x |
| コスト | ~$0.000004/文字 |

### PII保護

- 音声ファイルは処理後即削除（`tempfile` + `os.unlink`）
- 音声内容はログに記録しない
- テキスト変換後は通常のBrainフロー（PIIマスキング適用）

---

## セキュリティ

| 対策 | 実装 |
|------|------|
| 認証 | JWT（HS256、24h有効） |
| 認可 | organization_id フィルタ（鉄則#1） |
| CORS | 設定可能なオリジン制限 |
| Rate Limiting | Cloud Run の max-instances で制御 |
| PII保護 | persons エンドポイントでメール・電話除外 |
| SQL | パラメータ化クエリ（鉄則#9） |
| 音声データ | 処理後即削除 |
| Secret管理 | Google Secret Manager |

---

## デプロイ

```bash
# 全サービスデプロイ
bash mobile-api/deploy.sh all

# 個別デプロイ
bash mobile-api/deploy.sh mobile-api
bash mobile-api/deploy.sh mcp-server
```

### 必要な Secret Manager エントリ

| シークレット | 用途 |
|-------------|------|
| `jwt-secret` | **新規作成必要** — JWT署名用シークレット |
| `cloudsql-password` | 既存 — DB接続 |
| `openrouter-api-key` | 既存 — Whisper API / LLM |

---

## iPhoneアプリ（次ステップ）

Mobile API が稼働した後、React Native でiPhoneアプリを構築:

1. React Native プロジェクト初期化
2. Mobile API への接続
3. チャット画面（WebSocket）
4. タスク/目標ダッシュボード
5. 音声入力（マイクボタン）
6. プッシュ通知
7. App Store 申請

---

## コスト見積もり

| 項目 | 月額見積もり |
|------|-------------|
| Cloud Run（MCP Server） | ~$5（min-instances=0） |
| Cloud Run（Mobile API） | ~$10（min-instances=0） |
| Whisper API | ~$1（月100分想定） |
| Google Cloud TTS | ~$0.50（月10万文字想定） |
| **合計** | **~$16.50/月** |
