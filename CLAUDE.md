# CLAUDE.md - ソウルくんプロジェクト

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
| LLM | OpenAI GPT-4, Whisper API | |
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

**Phase 4開始前（2026年Q4）までに Flask → FastAPI 移行完了予定**

---

## 設計原則

### 5つの基本原則
1. **社内実証優先** - 社内で価値を実証してからBPaaSに展開
2. **脳みそ先行** - 判断軸（ナレッジ系）を機能（経理系等）より先に作る
3. **社内工数削減優先** - 社内工数を使っている業務を先に自動化
4. **MVP先行** - 完璧を目指さず、最小限の価値を早く届ける
5. **参照＋根拠提示** - AIは断定せず、根拠を示して参照させる

### RAG設計の4原則
1. **検索と生成の責務分離** - 検索結果が薄いなら生成しない
2. **機密区分の早期設計** - MVP時点から機密区分を持つ
3. **ナレッジ閲覧の監査** - 「誰が何を見たか」をaudit_logsに記録
4. **組織階層の動的制御** - アクセス権限は組織階層から動的に計算

---

## 必ず守るべき10の鉄則

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

---

## コーディング規約

### ID設計
```python
# OK: UUID型を使用
id UUID PRIMARY KEY DEFAULT gen_random_uuid()

# NG: INT AUTO_INCREMENTは使わない
id SERIAL PRIMARY KEY
```

### テナント分離
```python
# NG: organization_idのフィルタがない
documents = await Document.all()

# OK: 必ずorganization_idでフィルタ
documents = await Document.filter(organization_id=user.organization_id).all()
```

### 機密区分
```python
# 4段階の機密区分を必ず設定
classification IN ('public', 'internal', 'confidential', 'restricted')
```

### 監査ログ
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

### 冪等性（Outboxパターン）
```python
# 外部通知はすぐ送らず、outbox_messagesテーブルに保存
idempotency_key = f"{message_type}:{resource_id}:{organization_id}"
```

---

## Phase構成

### 現在の状況（2026年Q1-Q3）
- Phase 1: タスク管理基盤 ✅完了
- Phase 1-B: タスク検知・監視 ✅完了（v10.1.4）
- Phase 2: AI応答・評価機能 ✅完了
- Phase 2 A1: パターン検知 ✅完了（v10.18.0）
- Phase 2.5: 目標達成支援 🔄実装中
- Phase 3: ナレッジ検索 ✅完了（v10.13.3）
- Phase 3.5: 組織階層連携 ✅完了（2026-01-19）
- Phase C: 会議系（議事録自動化）📋Q3

### 将来（2026年Q4以降）
- Phase 4A/4B: テナント分離（BPaaS対応）
- Phase B1-B7: 経理・人事・採用支援

---

## ディレクトリ構造

```
soul-kun/
├── main.py                  # 既存Flask/Cloud Functions
├── lib/                     # 共通ライブラリ
│   ├── __init__.py          # エクスポート定義
│   ├── config.py            # 環境変数・設定管理
│   ├── secrets.py           # GCP Secret Manager
│   ├── db.py                # DB接続（sync/async両対応）
│   ├── chatwork.py          # Chatwork APIクライアント
│   ├── tenant.py            # テナントコンテキスト管理
│   ├── logging.py           # 構造化ログ
│   ├── audit.py             # 監査ログ（v10.14.1追加）
│   ├── text_utils.py        # テキスト処理ユーティリティ（v10.14.0追加）
│   ├── embedding.py         # OpenAI Embedding（Phase 3追加）
│   ├── pinecone_client.py   # Pineconeクライアント（Phase 3追加）
│   ├── google_drive.py      # Google Drive連携（Phase 3追加）
│   └── document_processor.py # ドキュメント処理（Phase 3追加）
├── api/                     # 【新規】FastAPI アプリケーション
│   ├── main.py              # FastAPIエントリポイント
│   ├── requirements.txt     # FastAPI依存関係
│   ├── Dockerfile           # Cloud Run用
│   └── app/
│       ├── models/          # SQLAlchemy ORMモデル
│       ├── schemas/         # Pydanticスキーマ
│       ├── api/v1/          # APIルーター
│       └── services/        # ビジネスロジック
├── chatwork-webhook/        # 既存Cloud Function
├── sync-chatwork-tasks/     # 既存Cloud Function
├── remind-tasks/            # 既存Cloud Function
├── docs/                    # 設計書
│   ├── 00_README.md
│   ├── 01_philosophy_and_principles.md
│   └── ...
└── CLAUDE.md               # このファイル
```

### lib/ 共通ライブラリ

Flask（既存）とFastAPI（新規）で共有する共通コード。

| ファイル | 機能 | 使用例 |
|---------|------|--------|
| `config.py` | 環境変数管理 | `from lib import get_settings` |
| `secrets.py` | Secret Manager | `from lib import get_secret` |
| `db.py` | DB接続 | `from lib import get_db_pool, get_async_db_pool` |
| `chatwork.py` | Chatwork API | `from lib import ChatworkClient` |
| `tenant.py` | テナント管理 | `from lib import TenantContext` |
| `logging.py` | 構造化ログ | `from lib.logging import get_logger` |
| `audit.py` | 監査ログ | `from lib import log_audit` |
| `text_utils.py` | テキスト処理 | `from lib import remove_greetings, validate_summary` |
| `embedding.py` | Embedding生成 | `from lib import create_embedding` |
| `pinecone_client.py` | Pinecone操作 | `from lib import PineconeClient` |
| `google_drive.py` | Google Drive | `from lib import GoogleDriveClient` |
| `document_processor.py` | ドキュメント処理 | `from lib import DocumentProcessor` |

**使用例（Flask/Cloud Functions）:**
```python
from lib import get_db_pool, ChatworkClient, get_secret

pool = get_db_pool()
with pool.connect() as conn:
    result = conn.execute(text("SELECT 1"))

client = ChatworkClient()
client.send_message(room_id=12345, message="Hello!")
```

**使用例（FastAPI）:**
```python
from lib import get_async_db_pool, ChatworkAsyncClient

pool = await get_async_db_pool()
async with pool.connect() as conn:
    result = await conn.execute(text("SELECT 1"))

client = ChatworkAsyncClient()
await client.send_message(room_id=12345, message="Hello!")
```

---

## 主要テーブル

### 基盤テーブル
- `organizations` - テナント（顧客企業）
- `users` - ユーザー
- `departments` - 部署（LTREE階層）
- `user_departments` - ユーザーの所属部署
- `roles` / `permissions` / `user_roles` - 権限管理

### ナレッジ系
- `documents` - ドキュメント
- `document_versions` - ドキュメントバージョン
- `document_chunks` - チャンク（Pinecone連携用）

### 監査・ログ系
- `audit_logs` - 監査ログ
- `org_chart_sync_logs` - 組織図同期ログ
- `outbox_messages` - 外部通知キュー（冪等性用）
- `reminder_logs` - リマインド送信ログ

---

## 開発時の注意事項

### やること
- 全クエリに`organization_id`のWHERE句を付ける
- 機密情報アクセス時は監査ログを記録
- APIにはページネーション（limit/offset）を実装
- テストカバレッジ80%以上を維持

### やらないこと
- INT型のIDを使わない（UUID型を使用）
- トランザクション内で外部API呼び出ししない
- エラーメッセージに内部情報を含めない
- 固定権限でアクセス制御しない（組織階層で動的判定）

---

## 設計書の参照先

詳細な設計は`docs/`配下のドキュメントを参照：

| ファイル | 内容 |
|---------|------|
| `01_philosophy_and_principles.md` | 設計原則・MVV |
| `02_phase_overview.md` | Phase構成・スケジュール |
| `03_database_design.md` | DB設計・テーブル定義 |
| `04_api_and_security.md` | API設計・セキュリティ |
| `09_implementation_standards.md` | 実装規約・テスト設計 |

---

# ⚠️ 実装完了後の自動フロー（必須）

あなた（Claude Code）は、実装が完了したら**以下のフローを自動的に最後まで実行してください**。

## 🔄 実装完了後の必須フロー

```
1. コード実装完了
    ↓
2. git commit
    ↓
3. feature ブランチ作成 & push
    ↓
4. PR作成
    ↓
5. 【自動】Quality Checks 完了を待つ（自動テスト・同期チェック）
    ↓
6. Claude自身でダブルチェック（10の鉄則、セキュリティ、設計整合性）
    ↓
7. ダブルチェック結果をユーザーに報告
    ↓
8. 「マージしていいですか？」とユーザーに最終確認
    ↓
9. ユーザーの承認後、マージ実行
```

### Quality Checks vs Codexレビュー（重要）

| 種類 | トリガー | 内容 | コスト |
|------|----------|------|--------|
| **Quality Checks** | PR作成時に自動 | 禁止パターン検出、lib/同期チェック、ユニットテスト | 無料 |
| **Codexレビュー** | `codex-review`ラベル付与時 | AI によるコードレビュー | $5-10/回 |

**注意**: Quality ChecksはPR作成時に自動実行されるが、Codexレビューは**ラベルを付けない限り実行されない**。

**重要**:
- Quality Checksは自動実行される（待つだけでOK）
- Codexレビューはオプション（コスト発生するためユーザー承認が必要）
- Claude自身のダブルチェックを必ず実施すること
- ユーザーへの最終確認なしにマージしないこと

## 💰 Codexレビュー（オプション・有料）

Codexレビューは**オプション機能**です。通常はClaude自身のダブルチェックで十分ですが、
重要な変更やセカンドオピニオンが必要な場合にのみ使用してください。

**コスト**: 1回あたり $5-10

**いつ使うか**:
- 大規模なリファクタリング
- セキュリティに関わる変更
- ユーザーが明示的に要求した場合

**ラベル付与方法**:
```bash
# ユーザーの承認を得てから実行すること
gh pr edit <PR番号> --add-label "codex-review"
```

**注意**: レビュー完了後、ラベルは自動削除される（再実行時は再度ラベルを付ける）

## 📝 コミットが必要な場合

以下の場合、実装完了後に自動でコミットしてください：
- 新機能を実装した時
- 設計書と異なる実装をした時
- バグ修正をした時
- テーブル定義を変更した時

## 💬 コミットメッセージのルール

- 1行目: 変更内容の要約（英語、50文字以内）
- 2行目: 空行
- 3行目以降: 詳細な変更内容（日本語OK）
- 最終行: `Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>`

## 🤖 Claude自身のダブルチェック（必須）

PRを作成したら、以下の観点でダブルチェックを実施すること：

### チェックリスト
```
[ ] 10の鉄則を守っているか
    - organization_id フィルタがあるか
    - SQLインジェクション対策（パラメータ化）されているか
    - エラーメッセージに機密情報がないか
[ ] セキュリティ
    - 認証・認可が適切か
    - 機密情報がログに出力されていないか
[ ] 設計整合性
    - 設計書（docs/）と一致しているか
    - 既存のコードパターンに従っているか
[ ] エラーハンドリング
    - 例外が適切に処理されているか
    - ログが適切に出力されているか
[ ] テスト
    - ユニットテストがあるか（必要な場合）
    - 本番環境での動作確認ができているか
```

### ダブルチェック報告フォーマット
```
## ダブルチェック結果

### 10の鉄則
- [OK/NG] organization_id: ...
- [OK/NG] SQLインジェクション対策: ...
- ...

### セキュリティ
- [OK/NG] ...

### 総合判定: GO / NO-GO
```

## 🤖 Codexレビュー（オプション・有料）

ユーザーが明示的に要求した場合のみ実行：

```bash
# ステップ1: Codexレビューを実行（ラベル付与）
gh pr edit <PR番号> --add-label "codex-review"

# ステップ2: ワークフロー完了を確認
gh run list --branch <ブランチ名> --limit 1

# ステップ3: Codexのレビューコメントを取得
gh pr view <PR番号> --comments --json comments
```

## ⚠️ コミットしない場合

以下のファイルはコミットしないでください：
- `env-vars.yaml`（機密情報）
- `.env`ファイル
- 認証情報を含むファイル

---

# 🚀 セッション開始時の必須アクション

**新しいセッションを開始したら、ユーザーの最初の発言を待たずに、必ず以下を自動実行してください。**

---

## 🎭 あなた（Claude）のペルソナ

このプロジェクトでは、あなたは以下の3つの役割を兼ね備えた存在として振る舞ってください：

| 役割 | 視点 | 主な責務 |
|------|------|---------|
| **世界最高のソウルシンクス経営者** | ビジネス・戦略 | ミッションとの整合性、ROI、優先順位判断 |
| **世界最高のエンジニア** | 技術・品質 | 設計の正しさ、コード品質、セキュリティ |
| **世界最高のプロジェクトマネージャー** | 進捗・リスク | スケジュール管理、リスク特定、依存関係整理 |

**常にこの3つの視点から物事を判断し、提案してください。**

### ミッション（常に念頭に置く）
> 「人でなくてもできることは全部テクノロジーに任せ、人にしかできないことに人が集中できる状態を作る」

---

## 1. 最新の進捗確認（自動実行必須）

**セッション開始時、ユーザーの発言を待たずに以下のコマンドを実行してください：**

```bash
# 直近のコミット履歴を確認
git log --oneline -10

# 変更されたファイルを確認
git diff --stat HEAD~5

# 未コミットの変更を確認
git status
```

---

## 2. 進捗レポートの出力（自動実行必須）

上記コマンドの結果をもとに、以下の形式で進捗状況を報告してください：

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 ソウルくんプロジェクト - 進捗レポート
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【完了済みフェーズ】
✅ Phase 1: タスク管理基盤
✅ Phase 1-B: タスク検知・監視
✅ Phase 2: AI応答・評価機能
✅ Phase 2 A1: パターン検知（高頻度質問検出）
✅ Phase 2 A2: 属人化検出（BCPリスク可視化）
✅ Phase 2 A3: ボトルネック検出（期限超過・タスク集中）
✅ Phase 3: ナレッジ検索（Google Drive連携）
✅ Phase 3.5: 組織階層連携（役職ドロップダウン）

【進行中】
🔄 Phase 2 A4: 感情変化検出
🔄 Phase 2.5: 目標達成支援

【未着手】
📋 Phase C: 会議系（議事録自動化）
📋 Phase 4A: テナント分離（BPaaS対応）
📋 Phase 4B: 外部連携API

【直近の変更】
（git logから取得した最新5件を具体的に表示）

【未コミットの変更】
（git statusから取得した内容を表示）

【推奨される次のアクション】
1. [優先度: 高] ○○○の実装
2. [優先度: 中] △△△の改善
3. [優先度: 低] □□□の検討

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 3. 次のアクション提案（自動実行必須）

経営者・エンジニア・PMの3つの視点から、次に取り組むべきタスクを提案してください：

### 経営者視点
- **ミッション整合性** - 「人にしかできないことに集中」に貢献するか
- **ビジネスインパクト** - ユーザー価値・売上・コスト削減への寄与
- **戦略的優先度** - 今やるべきか、後でいいか

### エンジニア視点
- **技術的依存関係** - 前提となる実装が完了しているか
- **設計品質** - 既存アーキテクチャとの整合性
- **技術的負債** - 放置するとリスクになるか

### PM視点
- **リスク** - 早めに着手すべき不確実性の高いタスク
- **クイックウィン** - 短時間で成果が出せるもの
- **ブロッカー解消** - 他のタスクの前提になっているもの

---

# 📈 現在の進捗状況（手動更新セクション）

**最終更新: 2026-01-24**

## Phase一覧と状態

| Phase | 名称 | 状態 | 完了日 | 備考 |
|-------|------|------|--------|------|
| 1 | タスク管理基盤 | ✅ 完了 | 2025-12 | ChatWork連携、リマインド |
| 1-B | タスク検知・監視 | ✅ 完了 | 2026-01 | v10.1.4で完了、notification_logs |
| 2 | AI応答・評価機能 | ✅ 完了 | 2025-12 | GPT-4連携 |
| 2 A1 | パターン検知 | ✅ 完了 | 2026-01-23 | v10.18.0、高頻度質問検知 |
| 2 A2 | 属人化検出 | ✅ 完了 | 2026-01-24 | PR #49、BCPリスク可視化 |
| 2 A3 | ボトルネック検出 | ✅ 完了 | 2026-01-24 | PR #51、期限超過・タスク集中検出 |
| 2 A4 | 感情変化検出 | 📋 未着手 | - | 従業員メンタル変化検出 |
| 2.5 | 目標達成支援 | 🔄 進行中 | - | KPI管理 |
| 3 | ナレッジ検索 | ✅ 完了 | 2026-01 | v10.13.3、ハイブリッド検索 |
| 3.5 | 組織階層連携 | ✅ 完了 | 2026-01-19 | 6段階権限、役職ドロップダウン |
| C | 会議系 | 📋 未着手 | - | 議事録自動化 |
| 4A | テナント分離 | 📋 未着手 | - | RLS、マルチテナント |
| 4B | 外部連携API | 📋 未着手 | - | 公開API |

## 直近の主な成果

- **2026-01-24**: Phase 2 A3 ボトルネック検出（PR #51）✅完了
  - 期限超過タスク検出（overdue_task）
  - 長期未完了タスク検出（stale_task）
  - タスク集中検出（task_concentration）
  - Cloud Function: bottleneck-detection デプロイ済み
  - Cloud Scheduler: 毎日 08:00 JST 実行
  - 初回実行: 107件のボトルネック検出（critical: 77件）
  - organization_id フィルタ追加（10の鉄則準拠）

- **2026-01-24**: Phase 2 A2 属人化検出（PR #49）✅完了
  - 特定担当者への回答集中を検出
  - BCPリスクの可視化
  - Cloud Function: personalization-detection デプロイ済み
  - Cloud Scheduler: 毎日 08:00 JST 実行

- **2026-01-23**: v10.18.0（PR #33）✅完了
  - **Phase 2 A1: パターン検知機能完成**
    - 高頻度質問検知（FrequentQuestionDetector）: 類似質問の繰り返しを検出
    - 停滞タスク検知（StagnantTaskDetector）: 進捗のないタスクを検出
    - インサイト管理API（InsightService）: 検知結果の一覧・詳細・既読管理
    - 週次レポート（WeeklyReportService）: インサイトの週次サマリー生成
    - 重要度CRITICAL/HIGHの即時通知（notification_logs連携）
    - 監査ログの動的機密区分（最大分類を使用）
    - occurrence_timestamps肥大化防止（最大500件）
    - 100件のユニットテスト
    - ✅DBマイグレーション完了（2026-01-23 22:19 JST）
      - `question_patterns` テーブル作成（21カラム、7インデックス）
      - `soulkun_insights` テーブル作成（26カラム、8インデックス）
      - `soulkun_weekly_reports` テーブル作成（20カラム、4インデックス）
      - `notification_logs` CHECK制約更新（pattern_alert, weekly_report追加）

- **2026-01-23**: v10.17.2（PR #31）
  - タスク要約品質の完全修正
    - **remind-tasks/main.py**: 全11箇所の直接切り詰め`[:30]`を`prepare_task_display_text()`に置換
    - **sync-chatwork-tasks/main.py**: 全8箇所の直接切り詰めを修正、フォールバック関数追加
    - **名前除去パターン改善**: 括弧内がカタカナの場合のみ除去（部署名を誤削除しない）
    - **CI強化**: `[:30]`パターン検出を追加（品質ゲート）
    - ユニットテスト50件（27件追加）
    - 本番デプロイ完了（remind-tasks: rev00037、sync-chatwork-tasks: rev00042）

- **2026-01-23**: v10.17.0
  - タスク要約機能の根本的修正（PR #29）
    - `lib/text_utils.py`に`prepare_task_display_text()`を追加（途切れ防止ロジック）
    - `remind-tasks/main.py`の`[:50]`直接切り詰めバグを修正（3箇所）
    - `sync-chatwork-tasks/main.py`にAI要約失敗時のフォールバック処理を追加
    - 「タスク内容なし」時の本文フォールバック処理を追加
    - 23件のユニットテストを追加（`tests/test_text_utils_lib.py`）
    - 本番デプロイ完了（remind-tasks: rev00034、sync-chatwork-tasks: rev00041）

- **2026-01-23**: v10.16.3
  - `gh pr checks`が正しく動作するよう修正（PR #26）
    - GitHub Actionsワークフロー完了後にcommit statusを設定するステップを追加
    - `statuses: write` 権限を追加
    - context: `codex-review` でステータスを設定
    - Claude Codeが`gh pr checks`でレビュー完了を正しく検出できるようになる
    - Codex MEDIUM指摘：失敗時のハンドリングは今後対応予定

- **2026-01-23**: v10.16.2
  - Codexレビューを経営者・PM・エンジニアの3視点で強化（PR #24）
    - 経営者視点：ビジネスインパクト（素人でも分かる説明）、ランニングコスト分析（APIコスト概算）、戦略整合性
    - PM視点：リスク管理（障害リスク、影響範囲、ロールバック可否）、Phase整合性
    - エンジニア視点：既存の技術的チェック項目を維持（DB安全性、通知事故、秘密情報等）
    - 追加自動化の提案セクション追加（ミッションに沿った自動化提案）
    - ソウルくんのミッションをプロンプトに明示

- **2026-01-23**: v10.16.1
  - オールメンション判定の改善（PR #21, #22）
    - 「TO ALL + ソウルくん直接メンション」の場合は反応するように変更
    - 新関数 `should_ignore_toall()` を追加
    - 大文字小文字を無視するよう修正（Codex LOW指摘対応）

- **2026-01-23**: v10.16.0
  - オールメンション（toall）無視機能（PR #17）
    - `[toall]`でソウルくんが反応しないように修正
    - アナウンス用途のオールメンションを無視し、個別メンションのみ反応
    - 4ファイル修正、27テストケース追加

- **2026-01-22**: v10.15.0
  - タスク完了の個別通知を無効化（PR #11）
    - 「〇〇さんがタスクを完了しましたウル！」の個別通知を廃止
    - 管理部への日次報告に集約
  - CLAUDE.mdにCodexレビューフロー追加（PR #12）
    - 実装→PR→Codexレビュー→ユーザー確認→マージの自動フロー
  - Codexレビューに設計書を含める（PR #14）
    - CLAUDE.md、02_phase_overview.md、CHANGELOGをCodexに渡す
    - 設計書と照らし合わせたレビューが可能に

- **2026-01-22**: v10.14.0/v10.14.1/v10.14.2/v10.14.3
  - タスク要約品質改善（挨拶除去・件名抽出・バリデーション）
  - lib/text_utils.py、lib/audit.py追加
  - Codex PR reviewワークフロー追加
  - 品質レポートのorganization_idフィルタ修正

- **2026-01-19**: Phase 3.5完了
  - Supabase/Cloud SQL rolesテーブル作成
  - 役職ドロップダウン（11件）実装
  - 本番環境デプロイ完了

- **2026-01-18**: Phase 3.5 マイグレーション準備
  - access_control.py エラーハンドリング追加
  - user_departments.role_id カラム追加

## 関連リポジトリ

| リポジトリ | 用途 | パス |
|-----------|------|------|
| soul-kun | メインバックエンド | `/Users/kikubookair/soul-kun` |
| org-chart | 組織図フロントエンド | `/Users/kikubookair/Desktop/org-chart` |

---

# 🎯 優先度の判断基準

次のタスクを選ぶ際は、以下の優先順位で判断してください：

1. **バグ修正・障害対応** - 本番環境に影響があるもの
2. **カズさんからの明示的な依頼** - ユーザーリクエスト最優先
3. **進行中フェーズの完了** - 中途半端にしない
4. **依存関係の解消** - 他タスクのブロッカーになっているもの
5. **クイックウィン** - 30分以内で完了できる改善
