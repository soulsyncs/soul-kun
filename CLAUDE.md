# CLAUDE.md - ソウルくんプロジェクト

## 開発方針

### プラグインをメインとした開発

**このプロジェクトでは、everything-claude-codeプラグインを開発の基本フレームワークとして採用しています。**

```
開発のやり方（HOW） → プラグインに従う
├── コーディング規約      → プラグインのcoding-standards
├── テスト設計           → プラグインのtdd-guide
├── コードレビュー        → プラグインのcode-reviewer
├── セキュリティチェック   → プラグインのsecurity-reviewer
├── DB設計レビュー       → プラグインのdatabase-reviewer
└── リファクタリング      → プラグインのrefactor-cleaner

何を作るか（WHAT） → ソウルくん設計書に従う
├── 機能の仕様          → docs/配下の設計書
├── ビジネスルール       → 本ファイルの「ソウルくん固有ルール」
└── 10の鉄則            → 本ファイルの「必ず守るべき10の鉄則」
```

**プラグインとソウルくんルールが矛盾した場合：**
- 汎用的なコーディングルール → プラグイン優先
- ソウルくん固有のビジネスルール → 本ファイル優先

---

## プロジェクト概要

**ソウルくん**は、株式会社ソウルシンクスが開発するAIバックオフィスシステム。

### ミッション
> 「人でなくてもできることは全部テクノロジーに任せ、人にしかできないことに人が集中できる状態を作る」

### コア機能
- 組織構造を理解したアクセス制御
- RAGベースのナレッジ検索
- タスク自動検知・リマインド
- 議事録自動生成

---

## 技術スタック

| 要素 | 技術 | 備考 |
|------|------|------|
| 言語 | Python 3.11+ | |
| **既存API** | Flask + Cloud Functions | Chatwork連携、タスク管理 |
| **新規API** | FastAPI + Cloud Run | Phase 3.5以降の組織図・ナレッジ系 |
| DB | PostgreSQL (Cloud SQL) + LTREE拡張 | |
| ベクトルDB | Pinecone | |
| キャッシュ | Redis | Phase 4で本格導入 |
| LLM | OpenAI GPT-4, Gemini | |
| 外部連携 | ChatWork API, Zoom API, Google Meet API | |
| インフラ | Google Cloud Platform | |

### ハイブリッドアーキテクチャ

```
┌─────────────────────────────────────────────────────────────┐
│                      GCP環境                                 │
│                                                              │
│  ┌─────────────────────┐   ┌─────────────────────────────┐  │
│  │ 既存: Cloud Functions│   │ 新規: Cloud Run             │  │
│  │ (Flask)              │   │ (FastAPI)                   │  │
│  │                      │   │                             │  │
│  │ ├─ chatwork_webhook  │   │ ├─ /api/v1/organizations/   │  │
│  │ ├─ check_reply_msgs  │   │ ├─ /api/v1/departments/     │  │
│  │ ├─ sync_cw_tasks     │   │ ├─ /api/v1/knowledge/       │  │
│  │ └─ remind_tasks      │   │ └─ /api/v1/access/          │  │
│  └───────────┬──────────┘   └──────────────┬──────────────┘  │
│              │                             │                 │
│              └─────────┬───────────────────┘                 │
│                        │                                     │
│                   ┌────▼────┐                                │
│                   │  lib/   │ ← 共通ライブラリ               │
│                   └────┬────┘                                │
│                        │                                     │
│                   ┌────▼────┐                                │
│                   │Cloud SQL│                                │
│                   └─────────┘                                │
└─────────────────────────────────────────────────────────────┘
```

---

## ソウルくん固有ルール

### 必ず守るべき10の鉄則

| # | 鉄則 | 補足 |
|---|------|------|
| 1 | **全テーブルにorganization_idを追加** | テナント分離の前提 |
| 2 | **Row Level Security（RLS）を実装** | Phase 4Aで必須 |
| 3 | **監査ログを全confidential以上の操作で記録** | audit_logsテーブルに記録 |
| 4 | **APIは必ず認証必須** | 例外なし |
| 5 | **ページネーションを1000件超えAPIに実装** | limit/offsetを使用 |
| 6 | **キャッシュにTTLを設定（デフォルト5分）** | Redis使用時 |
| 7 | **破壊的変更時はAPIバージョンアップ** | /api/v1/, /api/v2/ |
| 8 | **エラーメッセージに機密情報を含めない** | ユーザーID、内部パス等 |
| 9 | **SQLインジェクション対策（パラメータ化）** | 直接文字列連結禁止 |
| 10 | **トランザクション内でAPI呼び出しをしない** | デッドロック防止 |

### 設計原則

**5つの基本原則**
1. **社内実証優先** - 社内で価値を実証してからBPaaSに展開
2. **脳みそ先行** - 判断軸（ナレッジ系）を機能（経理系等）より先に作る
3. **社内工数削減優先** - 社内工数を使っている業務を先に自動化
4. **MVP先行** - 完璧を目指さず、最小限の価値を早く届ける
5. **参照＋根拠提示** - AIは断定せず、根拠を示して参照させる

**RAG設計の4原則**
1. **検索と生成の責務分離** - 検索結果が薄いなら生成しない
2. **機密区分の早期設計** - MVP時点から機密区分を持つ
3. **ナレッジ閲覧の監査** - 「誰が何を見たか」をaudit_logsに記録
4. **組織階層の動的制御** - アクセス権限は組織階層から動的に計算

### コーディング規約（ソウルくん固有）

**ID設計**
```python
# OK: UUID型を使用
id UUID PRIMARY KEY DEFAULT gen_random_uuid()

# NG: INT AUTO_INCREMENTは使わない
id SERIAL PRIMARY KEY
```

**テナント分離**
```python
# NG: organization_idのフィルタがない
documents = await Document.all()

# OK: 必ずorganization_idでフィルタ
documents = await Document.filter(organization_id=user.organization_id).all()
```

**機密区分**
```python
# 4段階の機密区分を必ず設定
classification IN ('public', 'internal', 'confidential', 'restricted')
```

**監査ログ**
```python
# confidential以上の操作では必ず記録
await log_audit(
    user=user,
    action='view',
    resource_type='document',
    resource_id=doc_id,
    classification='confidential'
)
```

---

## ディレクトリ構造

```
soul-kun/
├── main.py                  # 既存Flask/Cloud Functions
├── lib/                     # 共通ライブラリ
│   ├── config.py            # 環境変数・設定管理
│   ├── secrets.py           # GCP Secret Manager
│   ├── db.py                # DB接続（sync/async両対応）
│   ├── chatwork.py          # Chatwork APIクライアント
│   ├── audit.py             # 監査ログ
│   ├── feature_flags.py     # Feature Flag集約管理
│   ├── brain/               # 脳アーキテクチャ
│   └── memory/              # Memory Framework
├── api/                     # FastAPI アプリケーション
│   └── app/
│       ├── models/          # SQLAlchemy ORMモデル
│       ├── schemas/         # Pydanticスキーマ
│       ├── api/v1/          # APIルーター
│       └── services/        # ビジネスロジック
├── chatwork-webhook/        # メインCloud Function
│   ├── main.py
│   ├── lib/                 # lib/のコピー
│   └── handlers/            # 機能別ハンドラー
├── docs/                    # 設計書
├── tests/                   # テスト
├── CLAUDE.md                # このファイル
└── PROGRESS.md              # 進捗記録
```

### lib/ 共通ライブラリ

| ファイル | 機能 |
|---------|------|
| `config.py` | 環境変数管理 |
| `secrets.py` | Secret Manager |
| `db.py` | DB接続 |
| `chatwork.py` | Chatwork API |
| `audit.py` | 監査ログ |
| `feature_flags.py` | Feature Flag管理 |
| `admin_config.py` | 管理者設定（DB化済み） |
| `brain/` | 脳アーキテクチャ（v10.29.0） |
| `memory/` | Memory Framework（Phase 2 B） |

---

## 主要テーブル

**基盤テーブル**
- `organizations` - テナント（顧客企業）
- `users` - ユーザー
- `departments` - 部署（LTREE階層）
- `chatwork_users` - ChatWorkユーザー

**ナレッジ系**
- `documents` - ドキュメント
- `document_chunks` - チャンク（Pinecone連携用）
- `soulkun_knowledge` - ソウルくんの知識

**監査・ログ系**
- `audit_logs` - 監査ログ
- `notification_logs` - 通知ログ

詳細は `docs/03_database_design.md` を参照。

---

## 設計書参照先

| ファイル | 内容 |
|---------|------|
| `docs/01_philosophy_and_principles.md` | 設計原則・MVV |
| `docs/02_phase_overview.md` | Phase構成・スケジュール |
| `docs/03_database_design.md` | DB設計・テーブル定義 |
| `docs/04_api_and_security.md` | API設計・セキュリティ |
| `docs/09_implementation_standards.md` | 実装規約・テスト設計 |
| `docs/13_brain_architecture.md` | 脳アーキテクチャ |

---

## 実装フロー

### 実装完了後の必須フロー

```
1. コード実装完了
    ↓
2. git commit（Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>）
    ↓
3. feature ブランチ作成 & push
    ↓
4. PR作成
    ↓
5. Quality Checks 完了を待つ（自動）
    ↓
6. ダブルチェック（10の鉄則、セキュリティ、設計整合性）
    ↓
7. 「マージしていいですか？」とユーザーに確認
    ↓
8. 承認後、マージ実行
```

### ダブルチェック観点

```
[ ] 10の鉄則を守っているか
    - organization_id フィルタがあるか
    - SQLインジェクション対策（パラメータ化）されているか
    - エラーメッセージに機密情報がないか
[ ] セキュリティ（プラグインのsecurity-reviewerも活用）
[ ] 設計整合性（docs/と一致しているか）
```

### コミットしないファイル

- `env-vars.yaml`（機密情報）
- `.env`ファイル
- 認証情報を含むファイル

---

## ペルソナ

このプロジェクトでは、以下の3つの役割を兼ね備えた存在として判断してください：

| 役割 | 視点 | 主な責務 |
|------|------|---------|
| **世界最高のソウルシンクス経営者** | ビジネス・戦略 | ミッションとの整合性、ROI、優先順位判断 |
| **世界最高のエンジニア** | 技術・品質 | 設計の正しさ、コード品質、セキュリティ |
| **世界最高のプロジェクトマネージャー** | 進捗・リスク | スケジュール管理、リスク特定、依存関係整理 |

---

## 優先度の判断基準

次のタスクを選ぶ際は、以下の優先順位で判断してください：

1. **バグ修正・障害対応** - 本番環境に影響があるもの
2. **カズさんからの明示的な依頼** - ユーザーリクエスト最優先
3. **進行中フェーズの完了** - 中途半端にしない
4. **依存関係の解消** - 他タスクのブロッカーになっているもの
5. **クイックウィン** - 短時間で成果が出せるもの

---

## セッション開始時

セッション開始時は、以下を実行してください：

```bash
# 直近のコミット履歴を確認
git log --oneline -10

# 未コミットの変更を確認
git status
```

進捗状況の詳細は `PROGRESS.md` を参照してください。

---

## 進捗記録

**作業履歴は `PROGRESS.md` に記録してください。**

作業完了時：
1. `PROGRESS.md` の「直近の主な成果」に追記
2. 関連するPhase一覧の状態を更新（該当する場合）
