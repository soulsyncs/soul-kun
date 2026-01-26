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
├── chatwork-webhook/        # 既存Cloud Function（※下記「コード構造」参照）
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

### chatwork-webhook/main.py 構造（v10.24.7）

**現在の状況**: 9,627行（ハンドラー分割により3,737行を外部化、フォールバック実装を維持）

```
chatwork-webhook/main.py
│
├── [1-300] インポート・設定
│   ├── Flask/GCP imports
│   ├── lib/ imports（text_utils, goal_setting, memory, mvv_context）
│   ├── handlers/ imports（feature flags付き）
│   ├── モデル設定（Gemini 3 Flash）
│   └── Phase 3 ナレッジ検索設定
│
├── [300-1000] SYSTEM_CAPABILITIES（機能カタログ）
│   └── AI司令塔が参照する全機能定義
│
├── [1000-1700] DB・認証・基盤ユーティリティ
│   ├── get_pool(), get_db_connection()
│   ├── verify_chatwork_webhook_signature()
│   ├── get_or_create_person(), normalize_person_name()
│   └── get_org_chart_overview()（Phase 3.5）
│
├── [1700-2200] ハンドラー初期化関数
│   ├── _get_task_handler()
│   ├── _get_overdue_handler()
│   ├── _get_goal_handler()
│   ├── _get_knowledge_handler()
│   └── _get_proposal_handler()
│
├── [2200-4000] タスク管理（→ handlers/task_handler.py に委譲）
│   ├── create_chatwork_task() ← ラッパー
│   ├── complete_chatwork_task() ← ラッパー
│   ├── search_tasks_from_db() ← ラッパー
│   └── + フォールバック実装
│
├── [4000-4500] AIハンドラー関数（→ handlers/ に委譲）
│   ├── handle_learn_knowledge() ← ラッパー
│   ├── handle_forget_knowledge() ← ラッパー
│   ├── handle_list_knowledge() ← ラッパー
│   ├── handle_query_company_knowledge() ← ラッパー
│   └── + フォールバック実装
│
├── [4500-5000] Phase 2.5 目標達成支援（→ handlers/goal_handler.py に委譲）
│   ├── handle_goal_registration() ← ラッパー
│   ├── handle_goal_progress_report() ← ラッパー
│   └── handle_goal_status_check() ← ラッパー
│
├── [5000-5500] 会話履歴・Memory統合
│   ├── get_conversation_history(), save_conversation_history()
│   └── process_memory_after_conversation()（Phase 2 B）
│
├── [5500-6200] メインWebhookハンドラー
│   ├── chatwork_webhook()（エントリポイント）
│   ├── ai_commander()（AI司令塔）
│   ├── execute_action()
│   └── get_ai_response()（MVV統合済み）
│
├── [6200-7500] ナレッジ管理（→ handlers/knowledge_handler.py に委譲）
│   ├── ensure_knowledge_tables() ← ラッパー
│   ├── save_knowledge(), delete_knowledge() ← ラッパー
│   ├── search_phase3_knowledge() ← ラッパー
│   ├── integrated_knowledge_search() ← ラッパー
│   └── + フォールバック実装
│
├── [7500-8200] 遅延管理（→ handlers/overdue_handler.py に委譲）
│   ├── process_overdue_tasks() ← ラッパー
│   ├── send_overdue_reminder_to_dm() ← ラッパー
│   └── + フォールバック実装
│
├── [8200-9000] 他Cloud Function エンドポイント
│   ├── check_reply_messages()
│   ├── sync_chatwork_tasks()
│   └── remind_tasks()
│
└── [9000-9627] cleanup_old_data()
```

### chatwork-webhook/handlers/ 構造（v10.24.7）

**Phase 4前リファクタリング完了**: 6つのハンドラーモジュールを抽出（計3,737行）

```
chatwork-webhook/handlers/
├── __init__.py                 # エクスポート定義（8行）
├── memory_handler.py           # Memory管理（302行）v10.24.3
├── proposal_handler.py         # 提案管理（553行）v10.24.2
├── task_handler.py             # タスク管理（462行）v10.24.4
├── overdue_handler.py          # 遅延管理（817行）v10.24.5
├── goal_handler.py             # 目標達成支援（551行）v10.24.6
└── knowledge_handler.py        # ナレッジ管理（1,044行）v10.24.7
```

| ハンドラー | 行数 | 主要機能 | Feature Flag |
|-----------|------|----------|--------------|
| `MemoryHandler` | 302 | 会話Memory統合 | `USE_NEW_MEMORY_HANDLER` |
| `ProposalHandler` | 553 | 知識提案・承認 | `USE_NEW_PROPOSAL_HANDLER` |
| `TaskHandler` | 462 | タスク作成・検索・完了 | `USE_NEW_TASK_HANDLER` |
| `OverdueHandler` | 817 | 遅延検知・エスカレーション | `USE_NEW_OVERDUE_HANDLER` |
| `GoalHandler` | 551 | 目標設定対話 | `USE_NEW_GOAL_HANDLER` |
| `KnowledgeHandler` | 1,044 | ナレッジ管理・検索 | `USE_NEW_KNOWLEDGE_HANDLER` |

### リファクタリング計画（Phase 4前に実施）✅ 完了

**完了したフェーズ**:
1. ✅ **Phase 2-3**: `handlers/memory_handler.py`（302行）v10.24.3
2. ✅ **Phase 2-4**: `handlers/proposal_handler.py`（553行）v10.24.2
3. ✅ **Phase 2-5**: `handlers/task_handler.py`（462行）v10.24.4
4. ✅ **Phase 2-6**: `handlers/overdue_handler.py`（817行）v10.24.5
5. ✅ **Phase 2-7**: `handlers/goal_handler.py`（551行）v10.24.6
6. ✅ **Phase 2-8**: `handlers/knowledge_handler.py`（1,044行）v10.24.7

**設計パターン（全ハンドラー共通）**:
- 依存性注入（get_pool, get_secret等を外部から注入）
- Feature Flag（環境変数で旧実装にフォールバック可能）
- シングルトンパターン（`_get_*_handler()`で遅延初期化）
- ラッパー関数（main.pyの既存シグネチャを維持）

**テストカバレッジ**:
- memory_handler: 18件
- proposal_handler: 15件
- task_handler: 28件
- overdue_handler: 30件
- goal_handler: 59件
- knowledge_handler: 58件
- **合計**: 208件のユニットテスト

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

**lib/同期チェック対象（v10.23.3拡張）**:
| ファイル | コピー先 |
|---------|----------|
| `lib/text_utils.py` | remind-tasks, sync-chatwork-tasks, chatwork-webhook, check-reply-messages, cleanup-old-data, pattern-detection |
| `lib/goal_setting.py` | chatwork-webhook |
| `lib/mvv_context.py` | chatwork-webhook, report-generator |
| `lib/report_generator.py` | chatwork-webhook, report-generator |
| `lib/audit.py` | chatwork-webhook, sync-chatwork-tasks, pattern-detection |
| `lib/memory/*` | chatwork-webhook/lib/memory/ |
| `lib/detection/*` | pattern-detection/lib/detection/ |

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

## 📊 進捗記録の更新（必須）

**作業完了時、必ず CLAUDE.md の「直近の主な成果」セクションを更新すること。**

### 更新タイミング
- PRをマージした時
- 新機能を実装した時
- バグ修正を完了した時
- 本番デプロイを実行した時
- リファクタリングを完了した時

### 記録すべき内容
```markdown
- **YYYY-MM-DD HH:MM JST**: [作業タイトル] (バージョン) ✅ **完了/PR #XX**
  - **実施者**: Claude Code
  - **作業内容**:
    - 変更点1
    - 変更点2
    - ...
  - **変更ファイル**:
    - `path/to/file1.py`: 変更内容
    - `path/to/file2.py`: 変更内容
  - **テスト**: XX件のユニットテスト（全パス）
  - **10の鉄則準拠**: 確認項目
  - **Feature Flag**: （該当する場合）フラグ名
```

### 更新手順
1. 「直近の主な成果」セクションの**先頭**に新しいエントリを追加
2. 最終更新日時を更新
3. 関連するPhase一覧の状態を更新（該当する場合）
4. コミットしてPRに含める

**注意**: 進捗記録の更新を忘れないこと。ユーザーはこのセクションを見てプロジェクトの状況を把握する。

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
✅ Phase 2 A4: 感情変化検出（メンタルヘルス可視化）
✅ Phase 3: ナレッジ検索（Google Drive連携）
✅ Phase 3.5: 組織階層連携（役職ドロップダウン）

【進行中】
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

**最終更新: 2026-01-26 11:10 JST**

## Phase一覧と状態

| Phase | 名称 | 状態 | 完了日 | 備考 |
|-------|------|------|--------|------|
| 1 | タスク管理基盤 | ✅ 完了 | 2025-12 | ChatWork連携、リマインド |
| 1-B | タスク検知・監視 | ✅ 完了 | 2026-01 | v10.1.4で完了、notification_logs |
| 2 | AI応答・評価機能 | ✅ 完了 | 2025-12 | GPT-4連携 |
| 2 A1 | パターン検知 | ✅ 完了 | 2026-01-23 | v10.18.0、高頻度質問検知 |
| 2 A2 | 属人化検出 | ✅ 完了 | 2026-01-24 | PR #49、BCPリスク可視化 |
| 2 A3 | ボトルネック検出 | ✅ 完了 | 2026-01-24 | PR #51、期限超過・タスク集中検出 |
| 2 A4 | 感情変化検出 | ✅ 完了 | 2026-01-24 | v10.20.0、PR #59、**本番デプロイ完了**（emotion-detection-daily 10:00 JST）|
| 2 B | 覚える能力 | ✅ 完了 | 2026-01-24 | v10.21.0、PR #68、**通常会話統合完了**（B1サマリー・B4検索） |
| 2.5 | 目標達成支援 | ✅ 完了 | 2026-01-24 | v10.22.5、PR #77、**終了コマンド追加**（「やめる」等で終了可能） |
| **2C-1** | **MVV・組織論的行動指針** | **✅ 完了** | **2026-01-24** | **v10.22.3、PR #74、本番デプロイ完了（rev 00115-nul）** |
| **2C-2** | **日報・週報自動生成** | **✅ 完了** | **2026-01-24** | **v10.23.2、PR #84、Phase 2.5+MVV統合** |
| 3 | ナレッジ検索 | ✅ 完了 | 2026-01 | v10.13.3、ハイブリッド検索 |
| 3.5 | 組織階層連携 | ✅ 完了 | 2026-01-25 | 6段階権限、役職ドロップダウン、**96件テスト追加（PR #102）** |
| C | 会議系 | 📋 未着手 | - | 議事録自動化（Q3予定） |
| C+ | 会議前準備支援 | 📋 未着手 | - | Phase C完了後（v10.22.0追加） |
| **X** | **アナウンス機能** | **✅ 本番デプロイ完了** | **2026-01-25** | **v10.26.0、PR #127/PR #129/PR #130、revision 00141-sux** |
| 4A | テナント分離 | 📋 未着手 | - | RLS、マルチテナント |
| 4B | 外部連携API | 📋 未着手 | - | 公開API |

## 本番環境インフラ状態（2026-01-24 17:45 JST時点）

### Cloud Functions（18個）

| 関数名 | 状態 | 用途 | 最終更新 |
|--------|------|------|----------|
| chatwork-webhook | ACTIVE | メインWebhook（v10.25.5 助詞終了修正） | 2026-01-26 18:24 |
| chatwork-main | ACTIVE | Chatwork API | 2026-01-24 11:18 |
| remind-tasks | ACTIVE | タスクリマインド（土日祝スキップ） | 2026-01-25 11:10 |
| sync-chatwork-tasks | ACTIVE | タスク同期 | 2026-01-25 10:50 |
| check-reply-messages | ACTIVE | 返信チェック | 2026-01-24 11:23 |
| cleanup-old-data | ACTIVE | 古いデータ削除 | 2026-01-24 11:25 |
| **pattern-detection** | **ACTIVE** | **A1〜A4検知統合** | **2026-01-24 17:03** |
| personalization-detection | ACTIVE | A2属人化検出 | 2026-01-24 10:28 |
| bottleneck-detection | ACTIVE | A3ボトルネック検出 | 2026-01-24 11:28 |
| weekly-report | ACTIVE | 週次レポート | 2026-01-24 08:44 |
| goal-daily-check | ACTIVE | 目標デイリーチェック | 2026-01-24 11:58 |
| goal-daily-reminder | ACTIVE | 目標リマインド | 2026-01-24 11:59 |
| goal-morning-feedback | ACTIVE | 朝のフィードバック | 2026-01-24 12:00 |
| goal-consecutive-unanswered | ACTIVE | 連続未回答検出 | 2026-01-24 12:01 |
| watch_google_drive | ACTIVE | Google Drive監視 | 2026-01-21 17:16 |
| sync-room-members | ACTIVE | ルームメンバー同期 | 2026-01-18 13:52 |
| update-schema | ACTIVE | スキーマ更新 | 2025-12-25 11:51 |
| schema-patch | FAILED | （廃止予定） | 2025-12-25 12:01 |

### Cloud Scheduler（19個）

| ジョブ名 | スケジュール | 状態 | 用途 |
|----------|--------------|------|------|
| check-reply-messages-job | */5 * * * * | ENABLED | 5分毎返信チェック |
| sync-chatwork-tasks-job | 0 * * * * | ENABLED | 毎時タスク同期 |
| sync-done-tasks-job | 0 */4 * * * | ENABLED | 4時間毎完了タスク同期 |
| remind-tasks-job | 30 8 * * * | ENABLED | 毎日 08:30 リマインド |
| cleanup-old-data-job | 0 3 * * * | ENABLED | 毎日 03:00 クリーンアップ |
| **personalization-detection-daily** | **0 6 * * *** | **ENABLED** | **毎日 06:00 A2属人化検出** |
| **bottleneck-detection-daily** | **0 8 * * *** | **ENABLED** | **毎日 08:00 A3ボトルネック検出** |
| **emotion-detection-daily** | **0 10 * * *** | **ENABLED** | **毎日 10:00 A4感情変化検出** |
| **pattern-detection-hourly** | **15 * * * *** | **ENABLED** | **毎時15分 A1パターン検知** |
| weekly-report-monday | 0 9 * * 1 | ENABLED | 毎週月曜 09:00 週次レポート |
| goal-daily-check-job | 0 17 * * * | ENABLED | 毎日 17:00 目標チェック |
| goal-daily-reminder-job | 0 18 * * * | ENABLED | 毎日 18:00 目標リマインド |
| goal-morning-feedback-job | 0 8 * * * | ENABLED | 毎日 08:00 朝フィードバック |
| goal-consecutive-unanswered-job | 0 9 * * * | ENABLED | 毎日 09:00 連続未回答チェック |
| daily-reminder-job | 0 18 * * * | ENABLED | 毎日 18:00 デイリーリマインド |
| weekly-summary-job | 0 18 * * 5 | ENABLED | 毎週金曜 18:00 週次サマリー |
| weekly-summary-manager-job | 5 18 * * 5 | ENABLED | 毎週金曜 18:05 マネージャーサマリー |
| sync-room-members-job | 0 8 * * 1 | ENABLED | 毎週月曜 08:00 メンバー同期 |
| soulkun-task-polling | */5 * * * * | PAUSED | （一時停止中） |

### Phase 2関連DBテーブル（13テーブル）

| テーブル名 | カラム数 | インデックス数 | レコード数 | Phase |
|------------|----------|----------------|------------|-------|
| question_patterns | 21 | 7 | 0 | A1 |
| soulkun_insights | 26 | 8 | 89 | A1〜A4 |
| soulkun_weekly_reports | 20 | 4 | 0 | A1 |
| emotion_scores | 14 | 6 | 0 | A4 |
| emotion_alerts | 26 | 8 | 0 | A4 |
| conversation_summaries | 14 | 4 | 0 | B1 |
| user_preferences | 12 | 5 | 0 | B2 |
| organization_auto_knowledge | 20 | 6 | 0 | B3 |
| conversation_index | 13 | 6 | 0 | B4 |
| goal_setting_sessions | 16 | 6 | 1 | 2.5 |
| goal_setting_logs | 14 | 7 | 3 | 2.5 |
| goal_setting_patterns | 15 | 5 | 10 | 2.5 |
| goal_setting_user_patterns | 18 | 5 | 0 | 2.5+B |

---

## 直近の主な成果

- **2026-01-26 11:45 JST**: 脳アーキテクチャ Phase A 完了 (v10.28.0) 🔄 **PR作成中**
  - **実施者**: Claude Code
  - **概要**: ソウルくんの中央処理装置「脳」を新設。全てのユーザー入力が脳を通るようになる
  - **進捗**: 18%（Phase A バイパスルート排除完了）
  - **作成ファイル**:
    | ファイル | 行数 | 内容 |
    |---------|------|------|
    | `lib/brain/__init__.py` | 50 | エクスポート定義 |
    | `lib/brain/constants.py` | 120 | 定数定義（キャンセルキーワード、閾値等） |
    | `lib/brain/exceptions.py` | 120 | 例外クラス階層 |
    | `lib/brain/models.py` | 350 | データモデル（BrainContext, BrainResponse等） |
    | `lib/brain/core.py` | 960 | SoulkunBrainクラス（中央処理装置） |
    | `docs/13_brain_architecture.md` | 1606 | 設計書 |
    | `tests/test_brain_core.py` | 540 | 49件のユニットテスト |
  - **main.py変更**:
    - Feature Flag追加（`USE_BRAIN_ARCHITECTURE`）
    - `_get_brain()`シングルトン初期化関数
    - 19種の脳用ハンドラーラッパー追加
    - chatwork_webhook()に脳処理分岐追加
  - **効果**:
    - 全入力が脳を経由するため、一貫した判断が可能に
    - 確信度が低い場合は確認を求める
    - キャンセル処理が統一される
    - エラー時は従来フローにフォールバック
  - **テスト**: 49件の脳テスト + 1171件全パス
  - **10の鉄則準拠**: organization_id、フォールバック設計、Feature Flag
  - **Feature Flag**: `USE_BRAIN_ARCHITECTURE=false`（デフォルト無効）

- **2026-01-26 11:10 JST**: Phase X アナウンス機能 ルーム選択フロー修正 (v10.26.4〜v10.26.9b) 🔄 **テスト待ち**
  - **実施者**: Claude Code
  - **概要**: アナウンス確認フローで発生した複数のバグを連続修正
  - **修正内容**:
    | バージョン | PR | 修正内容 |
    |-----------|-----|---------|
    | v10.26.4 | #150 | 「伝えて」「言って」等の自然言語キーワードをmodification_keywordsに追加 |
    | v10.26.5 | #151 | 「自分のタスク教えて」等の非フォローアップメッセージをAI司令塔に委ねる |
    | v10.26.6 | #154 | パースプロンプト改善（メッセージ内容抽出強化） |
    | v10.26.7 | #155 | 新しいアナウンス依頼検出時に古いpendingを自動キャンセル |
    | v10.26.8 | #156 | ルーム選択待ち状態をDBに永続化（status='pending_room'） |
    | v10.26.9 | #157 | status名を'awaiting_room_selection'(22文字)→'pending_room'(12文字)に短縮（VARCHAR(20)制約対応） |
    | v10.26.9b | #158 | target_room_idのNOT NULL制約を削除（ルーム選択待ち時はnull） |
  - **DBマイグレーション実行済み**:
    - `scheduled_announcements.status` CHECK制約に`'pending_room'`追加
    - `scheduled_announcements.target_room_id` NOT NULL制約削除
  - **デプロイ**: chatwork-webhook revision 00173-xiv
  - **テスト**: 67件全パス
  - **次のステップ**: ユーザーによる実機テスト待ち

- **2026-01-26 10:30 JST**: CI/CD強化 - デバッグprint検出 (v10.27.3) ✅ **PR #152 マージ完了**
  - **実施者**: Claude Code
  - **目的**: デバッグprint文が本番コードに混入するのを自動で防止
  - **追加した禁止パターン**:
    - `🔍 DEBUG:` - 明らかなデバッグ用マーカー
    - `🔍 受信データ全体:` - 全リクエストデータのログ出力（セキュリティリスク）
    - `print(json.dumps(data...))` - 生データダンプ（セキュリティリスク）
  - **検出対象**: 全7つのmain.pyファイル
  - **変更ファイル**:
    - `.github/workflows/quality-checks.yml`: +70行（デバッグprint検出ステップ追加）
  - **効果**: 今後、うっかりデバッグコードをコミットしてもCIでブロックされる

- **2026-01-26 10:25 JST**: v10.27.2 本番デプロイ完了 ✅ **6つのCloud Functions**
  - **実施者**: Claude Code
  - **デプロイ内容**: デバッグprint文削除（PR #148）を本番環境に適用
  - **デプロイ結果**:
    | Cloud Function | 新リビジョン |
    |---------------|------------|
    | chatwork-webhook | 00168-pez |
    | sync-chatwork-tasks | 00053-coy |
    | remind-tasks | 00044-yoy |
    | check-reply-messages | 00013-sad |
    | cleanup-old-data | 00007-man |
    | chatwork-main | 00003-beb |
  - **効果**: セキュリティ向上（全リクエストデータのログ出力停止）、ログコスト削減

- **2026-01-26 10:15 JST**: デバッグprint文削除 (v10.27.2) ✅ **PR #148 マージ完了**
  - **実施者**: Claude Code
  - **問題**: 開発時のデバッグ用print文が本番環境に残っていた
  - **削除内容**:
    - `🔍 受信データ全体: json.dumps(data)` (6ファイル) - セキュリティリスク
    - `🔍 DEBUG: limit_time = {limit_time}, type = {type(limit_time)}` (6ファイル) - 不要なデバッグログ
  - **変更ファイル**:
    - `chatwork-webhook/main.py`: 2箇所削除
    - `sync-chatwork-tasks/main.py`: 2箇所削除
    - `remind-tasks/main.py`: 2箇所削除
    - `check-reply-messages/main.py`: 2箇所削除
    - `cleanup-old-data/main.py`: 2箇所削除
    - `main.py`: 2箇所削除
  - **効果**:
    - セキュリティ向上（全リクエストデータのログ出力停止）
    - ログコスト削減（不要なログ出力の削除）
  - **テスト**: 116件パス（タスク関連）、Quality Checks 4/4パス
  - **10の鉄則準拠**: ログ削除のみ、ロジック変更なし

- **2026-01-26 07:45 JST**: アナウンス タスク対象者指定バグ修正 (v10.26.3) ✅ **PR #144 本番デプロイ完了**
  - **実施者**: Claude Code
  - **問題**: 「麻美にタスクついか」と指定しても「対象: ルーム全員」になり、7人全員にタスクが作成された
  - **原因**:
    1. 解析プロンプトに「〇〇にタスク」のルールがなかった
    2. `task_include_names` → `task_include_account_ids` への変換処理がなかった
    3. LLMがデフォルトで `task_assign_all: true` を設定
  - **修正内容**:
    - 解析プロンプトに「〇〇にタスク」→ `task_include_names`, `task_assign_all: false` のルールを追加
    - `_resolve_names_to_account_ids()`: 名前からアカウントIDへの変換
    - `_match_name_to_member()`: 完全一致、部分一致、敬称（さん、様）対応
    - 名前解決時に `task_assign_all = False` を強制設定
  - **変更ファイル**:
    - `chatwork-webhook/handlers/announcement_handler.py`: +110行（名前解決機能）
    - `tests/test_announcement_handler.py`: +118行（6件の新規テスト）
  - **テスト**: 60件全パス
  - **デプロイ**: chatwork-webhook revision 00164-bid
  - **10の鉄則準拠**: 既存のorganization_idフィルタ維持、パラメータ化クエリ使用

- **2026-01-26 07:35 JST**: アナウンス確認フロー メッセージ修正機能 (v10.26.2) ✅ **PR #142 本番デプロイ完了**
  - **実施者**: Claude Code
  - **問題**: アナウンス確認フロー中に「これはテストだよっていうのを追記してもらってもいい？」と修正を依頼すると「応答を理解できませんでしたウル」となる
  - **原因**: `_handle_follow_up_response()`が「OK」「キャンセル」「タスク追加」のみ対応し、メッセージ修正に対応していなかった
  - **修正内容**:
    - 修正キーワード検出追加（追記、追加、変更、修正、書き換え、直して、変えて、入れて）
    - `_update_message_content()`: DBからpending announcementを取得しメッセージを更新
    - `_apply_message_modification()`: LLMでメッセージ修正
    - `_try_llm_modification()`: OpenRouter API経由でGeminiを使用
    - `_fallback_modification()`: APIエラー時の単純追記処理
  - **変更ファイル**:
    - `chatwork-webhook/handlers/announcement_handler.py`: +236行（メッセージ修正機能）
    - `tests/test_announcement_handler.py`: +142行（8件の新規テスト）
  - **テスト**: 54件全パス
  - **デプロイ**: chatwork-webhook revision 00162-kuq
  - **10の鉄則準拠**: organization_idフィルタ、パラメータ化クエリ、エラーメッセージに機密情報含まず

- **2026-01-26 07:22 JST**: アナウンス機能 MVVベースメッセージ変換 + BUG-003修正 (v10.26.1) ✅ **PR #140 本番デプロイ完了**
  - **実施者**: Claude Code
  - **問題1（BUG-003）**: アナウンス送信後のタスク作成が「送信に失敗しましたウル」エラー
    - **原因**: `send_chatwork_message()`がboolを返すが、`execute_announcement()`が`.get("message_id")`を呼び出し`AttributeError`
    - **修正**: `return_details`パラメータ追加（後方互換性維持）
  - **問題2**: メッセージが「おはよう」のまま送信され、ソウルくんらしい文章に変換されない
    - **原因**: MVVベースのメッセージ変換機能がなかった
    - **修正**: `_enhance_message_with_soulkun_style()`メソッド追加
  - **変更ファイル**:
    - `chatwork-webhook/main.py`: `send_chatwork_message()`に`return_details`パラメータ追加
    - `chatwork-webhook/handlers/announcement_handler.py`: MVVベースメッセージ変換追加
    - `tests/test_announcement_handler.py`: 6件の新規テスト追加
  - **テスト**: 46件全パス
  - **デプロイ**: chatwork-webhook revision 00160-law
  - **動作確認**: 「おはよう」→「おはようウル！🐺 今日も一日、みんなの可能性を信じて頑張っていこうウル✨」

- **2026-01-26 07:15 JST**: タスク要約 AI summary優先使用 (v10.27.0) ✅ **PR #139 本番デプロイ完了**
  - **実施者**: Claude Code
  - **問題**: タスク検索結果で「どなたに伺うのが最適なのかわからなかため...」のように元のタスク本文がそのまま表示され、AIが生成した要約（summaryカラム）が使われていなかった
  - **根本原因**: `handle_chatwork_task_search()`内のコメント「DBのsummaryは信頼できないため」に基づき、`summary`カラムを無視して`body`を直接切り詰めていた
  - **修正内容**:
    - `summary`カラムを`validate_summary()`で検証し、有効な場合は優先使用
    - 無効な場合（NULL、挨拶のみ、途切れ）のみ`body`からフォールバック生成
  - **変更ファイル**:
    - `chatwork-webhook/main.py`: `handle_chatwork_task_search()`の2箇所を修正
    - `tests/test_task_search.py`: `TestTaskSummaryDisplay`クラス追加（4件のテスト）
  - **テスト**: 1092件全パス
  - **デプロイ**: chatwork-webhook revision 00158-qey
  - **10の鉄則準拠**: 既存のSQLインジェクション対策維持、後方互換性確保

- **2026-01-26 06:28 JST**: アナウンス機能ルームマッチングバグ修正 (BUG-002) ✅ **PR #136 本番デプロイ完了**
  - **実施者**: Claude Code
  - **問題**: 「管理部のグループチャット」で「【SS】★管理部★」が見つからない
  - **根本原因**: `_normalize_for_matching()`の正規表現が最後のサフィックスのみ除去
    - 「管理部のグループチャット」→「管理部のグループ」(チャットのみ除去)
    - 「管理部のグループ」は「【ss】★管理部★」と一致しない→スコア0.0
  - **修正内容**:
    - サフィックス除去を正規表現から順序付きリストに変更（長いパターンから先に処理）
    - 特殊文字除去を追加（【】★☆◆◇■□●○「」『』〈〉《》）
  - **修正後**:
    - 「管理部のグループチャット」→「管理部」
    - 「【SS】★管理部★」→「ss管理部」
    - マッチスコア: 0.92（自動選択閾値0.8を超える）
  - **変更ファイル**:
    - `chatwork-webhook/handlers/announcement_handler.py`: `_normalize_for_matching()`修正
    - `tests/test_announcement_handler.py`: 4件のユニットテスト追加
  - **テスト**: 41件全パス
  - **デプロイ**: chatwork-webhook revision 00144-hiq

- **2026-01-25 21:00 JST**: Phase X DBマイグレーション実行完了 ✅ **本番環境適用**
  - **実施者**: Claude Code
  - **背景**: PR #127〜#133はマージ・デプロイ済みだったが、DBマイグレーションが未実行だったため本番でエラー発生
  - **エラー内容**: `relation "scheduled_announcements" does not exist`
  - **実行内容**:
    - Cloud SQL Proxy経由で本番DBに接続
    - `migrations/phase_x_announcement_feature.sql`を実行
  - **作成されたテーブル**:
    - `scheduled_announcements`: 35カラム、5インデックス（アナウンス予約・実行管理）
    - `announcement_logs`: 21カラム、3インデックス（実行ログ・監査証跡）
    - `announcement_patterns`: 22カラム、3インデックス（パターン検知・A1連携）
  - **作成されたオブジェクト**:
    - インデックス: 15個（PK含む）
    - トリガー: 2個（updated_at自動更新）
    - CHECK制約: 43個
    - 外部キー: 1個（announcement_logs → scheduled_announcements）
  - **検証**: INSERT/SELECT/DELETE動作確認済み
  - **10の鉄則準拠**: 全テーブルにorganization_id、監査ログ対応

- **2026-01-25 20:35 JST**: PR #131〜#133 マージ完了 ✅
  - **実施者**: Claude Code
  - **PR一覧**:
    - **PR #131**: CLAUDE.md Phase X本番デプロイ完了記録
    - **PR #132**: アナウンス確認フローにタスク作成プロンプト追加
    - **PR #133**: アナウンスフォローアップのコンテキスト永続化修正
  - **PR #133の修正内容**:
    - 問題: フォローアップメッセージが一般会話に流れる
    - 原因: HTTPリクエスト間でコンテキストが保持されない
    - 解決: `_get_pending_announcement()`でDBから30分以内のpendingを取得、ai_commander前にチェック
  - **テスト**: 38件のユニットテスト全パス
  - **デプロイ**: chatwork-webhook revision 00141-sux以降

- **2026-01-26 18:30 JST**: タスク要約 助詞終了バグ修正 (v10.25.5) ✅ **PR #125 本番デプロイ完了**
  - **実施者**: Claude Code
  - **問題**: タスク要約が「販路を」「決算書の」「資料に」のように助詞で終わり、意味が通じなかった
  - **根本原因**: `prepare_task_display_text()`が40文字で切り詰める際、助詞（を、に、で、と、が、は、の、へ、も）を見つけてそこで切っていた
  - **修正内容**:
    - 助詞での切り詰めロジックを**廃止**（601-606行目削除）
    - 代わりに、結果の末尾が助詞の場合は**助詞を削除**
    - 短いテキストでも助詞削除を適用（「決算書の」→「決算書」）
  - **修正例**:
    - `販路を` → `販路`
    - `決算書の` → `決算書`
    - `資料を` → `資料`
    - `お手隙でこちらのマスター内の総務のドライブに` → `お手隙でこちらのマスター内の総務のドライブ`
  - **変更ファイル**:
    - `lib/text_utils.py`: 助詞切り詰め廃止、末尾助詞削除ロジック追加
    - `chatwork-webhook/main.py`: デバッグログ削除
    - `tests/test_text_utils_lib.py`: テスト更新（助詞で終わらないことを確認）
    - 6つのCloud Functionsにlib/text_utils.py同期
  - **テスト**: 55件全パス
  - **デプロイ**: chatwork-webhook 2026-01-26 18:24 UTC

- **2026-01-25 20:10 JST**: Phase X アナウンス機能 本番デプロイ完了 (v10.26.0) ✅ **PR #127/PR #129/PR #130**
  - **実施者**: Claude Code
  - **概要**: 管理部またはカズさんがソウルくんにアナウンス業務を委任できる機能
  - **ユースケース**: 「合宿のチャットに持ち物確認してってアナウンスしといて。全員タスクで、来週金曜まで」
  - **10の鉄則完全準拠**: 全8箇所のWHEREクエリにorganization_idフィルタ追加、エラーメッセージから内部情報除去
  - **デプロイ実施内容**:
    1. **DBマイグレーション** ✅ Cloud SQLで実行完了
       - `scheduled_announcements`: アナウンス予約・実行管理
       - `announcement_logs`: 実行ログ（監査証跡）
       - `announcement_patterns`: パターン検知（A1連携、3回以上で定期化提案）
    2. **chatwork-webhook デプロイ** ✅ revision 00141-sux
       - `USE_ANNOUNCEMENT_FEATURE=true`
       - pytz依存関係追加（PR #130で修正）
    3. **認可ロジック修正** ✅ PR #129
       - カズさんはどのルームからでもアナウンス可能
       - スタッフは管理部チャットからのみ
    4. **動作確認** ✅
       - ログ: `✅ handlers/announcement_handler.py loaded for Announcement feature`
  - **実装内容**:
    - **AnnouncementHandler** (`handlers/announcement_handler.py`, ~1,371行)
      - 認可チェック（管理者はどこからでもOK、それ以外は管理部チャットのみ）
      - 曖昧ルームマッチング（「合宿のチャット」→「2026年度 社員合宿」）
      - 確認フロー生成（送信前に確認メッセージ表示）
      - 即時/予約/繰り返し（cron式）の3種スケジュール対応
      - タスク作成（全員 or 指定者、除外者指定可）
      - パターン記録（A1連携で定期化提案）
  - **変更ファイル**:
    - `migrations/phase_x_announcement_feature.sql`: 新規（421行）
    - `chatwork-webhook/handlers/announcement_handler.py`: 新規（~1,371行）
    - `chatwork-webhook/handlers/__init__.py`: エクスポート追加
    - `chatwork-webhook/main.py`: Feature Flag, CAPABILITIES, HANDLERS統合
    - `chatwork-webhook/requirements.txt`: pytz>=2024.1追加
    - `tests/test_announcement_handler.py`: 31件のユニットテスト
  - **テスト**: 31件全パス（認可テスト含む）
  - **10の鉄則準拠**:
    - organization_id: 全テーブル・全クエリに含む
    - SQLインジェクション対策: パラメータ化クエリ使用
    - 監査ログ: announcement_logsで記録
  - **使い方**:
    - カズさん: どのルームからでも「〇〇のチャットにアナウンスして」
    - スタッフ: 管理部チャットから「〇〇のチャットにアナウンスして」

- **2026-01-25 17:15 JST**: タスクsummaryバリデーション強化 (v10.25.1) ✅ **PR #118**
  - **実施者**: Claude Code
  - **問題**: タスク検索結果で「決算書の」「こちらの資料を」のように助詞で終わる不完全なsummaryが表示されていた
  - **作業内容**:
    - `MID_SENTENCE_ENDINGS`定数追加（の、を、に、で、が、は等17種の助詞）
    - `validate_summary()`に助詞末尾チェックを追加
    - `validate_and_get_reason()`にも同様のチェックを追加
    - 元本文が50文字以上かつ、summaryが助詞で終わり、元本文の一部である場合に「途切れ」と判定
  - **変更ファイル**:
    - lib/text_utils.py: MID_SENTENCE_ENDINGS追加、validate_summary改善
    - 6つのCloud Function: lib/text_utils.py同期
    - tests/test_text_utils_lib.py: 5件の新規テスト追加
  - **テスト**: 1038件全パス（5件新規追加）
  - **10の鉄則準拠**: DB操作なし、後方互換性維持
  - **デプロイ完了** (2026-01-25 17:15 JST):
    - sync-chatwork-tasks: 00048-coh → **00049-veg** ✅
    - chatwork-webhook: 00131-tod → **00132-cad** ✅
    - remind-tasks: 00041-neq → **00042-yub** ✅
    - check-reply-messages: 00010-xxx → **00011-vex** ✅
    - cleanup-old-data: 00004-xxx → **00005-daq** ✅
    - pattern-detection: 00010-xxx → **00011-yuj** ✅
  - **動作確認**: sync-chatwork-tasksのログで「📝 summaryが低品質のため再生成」を確認

- **2026-01-25 18:30 JST**: 人物情報の提案制 & タスク要約改善 (v10.25.0) ✅ **PR #115**
  - **実施者**: Claude Code
  - **作業内容**:
    - **タスク要約改善**: DBの`summary`カラム（AI生成）を優先使用
      - 検索結果、リマインド、遅延通知でsummaryを表示
      - フォールバック時は句点・読点の後ろで自然に切り詰め
    - **提案メッセージ改善**: 心理的安全性向上
      - 「菊地さんに確認をお願いした」→「ソウルくんが会社として問題ないか確認する」
      - `[To:管理者ID]`メンションも削除
    - **人物情報の提案制導入**: セキュリティ強化
      - スタッフ: 提案 → 管理者確認 → 承認で反映
      - 管理者: 従来通り即時保存
      - `knowledge_proposals`テーブルの`category='memory'`で管理
  - **変更ファイル**:
    - chatwork-webhook/main.py: handle_save_memory, approve_proposal等
    - chatwork-webhook/handlers/proposal_handler.py: 全面改修
    - chatwork-webhook/handlers/task_handler.py: summary対応
    - chatwork-webhook/handlers/overdue_handler.py: summary対応
    - remind-tasks/main.py: summary対応
    - sync-chatwork-tasks/main.py: summary対応
  - **テスト**: 1033件全パス
  - **10の鉄則準拠**: SQLインジェクション対策（パラメータ化）、後方互換性維持
  - **デプロイ完了** (2026-01-25 19:30 JST):
    - chatwork-webhook: 00130-daf → **00131-tod** ✅
    - remind-tasks: 00040-civ → **00041-neq** ✅
    - sync-chatwork-tasks: 00046-vow → **00048-coh** ✅

- **2026-01-25 16:00 JST**: テスト修正 1033件全パス達成 ✅ **PR #113**
  - **実施者**: Claude Code
  - **問題**: 14件のテストが壊れていた（インポートエラー、API変更への未追従）
  - **修正内容**:
    - **test_document_processor.py**: API変更に追従
      - `TxtExtractor` → `TextFileExtractor`
      - `HtmlExtractor` → `HTMLExtractor`
      - `chunk()` → `split()` メソッド名
      - `chunk_index` → `index` フィールド名
      - 存在しない`format`フィールドを削除
    - **test_knowledge_api.py**: DB接続エラー回避のためモック追加
    - **test_knowledge_search_service.py**: インポートパス修正（`api.app.*` → `app.*`）
    - **conftest.py**: `api/`ディレクトリをPythonパスに追加
  - **テスト結果**: 1033 passed, 4 warnings
  - **10の鉄則準拠**: テストコードのみ、本番コード変更なし

- **2026-01-25 15:30 JST**: タスク要約切り詰めバグ 完全修正 ✅ **PR #108, #111, #112**
  - **実施者**: Claude Code
  - **問題**: タスク要約が途中で切れる（`[:30]`等で雑に切り詰めていた）
  - **作業内容**:
    - **PR #108**: デイリーインサイト通知バグ修正
      - 送信者がカズさんになる問題: `CHATWORK_API_TOKEN` → `SOULKUN_CHATWORK_TOKEN`
      - `[qt][qtmeta...]`タグ表示問題: `clean_chatwork_tags()` + `prepare_task_display_text()`追加
    - **PR #111**: chatwork-webhook タスク要約修正（6箇所）
      - `_fallback_truncate_text()`ヘルパー関数追加
      - 句点・読点・助詞の後ろで自然に切れるように
    - **PR #112**: 追加修正（6箇所）
      - 督促メッセージ、エスカレーションDM、管理部報告、期限変更通知
  - **修正箇所合計**:
    - chatwork-webhook/main.py: 12箇所
    - remind-tasks/main.py: 11箇所（v10.17.2で対応済み）
    - sync-chatwork-tasks/main.py: 8箇所（v10.17.2で対応済み）
  - **デプロイ**:
    - chatwork-webhook: revision 00130-daf
    - pattern-detection: revision 00010-xxx
  - **10の鉄則準拠**: UI表示のみ、SQL変更なし

- **2026-01-25 14:45 JST**: org-chart 完璧プラン設計書 v2.0.0 ✅ **PR #109**
  - **実施者**: Claude Code
  - **作業内容**:
    - 設計書を「完璧プラン」で全面更新
    - 全体設計書（CLAUDE.md, Phase構成）との整合性チェック実施
    - 10の鉄則準拠、Phase 4マルチテナント対応を考慮
  - **追加したPhase**:
    - Phase 2: Supabase Auth + 編集者テーブル（複数人編集対応）
    - Phase 5: 監査ログ + ロールバック機能（10の鉄則準拠）
    - Phase 6: PDF/Excel出力 + モバイル対応
    - Phase 7: コードモジュール分割（保守性向上）
  - **コスト見積もり**:
    - ランニングコスト: ¥0/月（無料枠内）
    - BPaaS展開時: ¥3,800/月（Supabase Pro）
  - **所要時間見積もり**: 約30時間（1-2週間）
  - **次のステップ**: Phase 2（Supabase Auth）から実装開始

- **2026-01-25 13:20 JST**: org-chart ChatWork ID連携 ✅ **org-chart PR #3**
  - **実施者**: Claude Code
  - **作業内容**:
    - Supabase: `chatwork_account_id`カラム追加（SQL実行）
    - 同期APIのURL修正（誤ったCloud Run URLを修正）
    - 社員追加・編集フォームにChatWork ID入力欄追加
    - スキーマチェック機能追加（カラム未存在時のフォールバック）
    - マイグレーションファイル作成（`migrations/001_add_chatwork_account_id.sql`）
  - **変更ファイル（org-chart）**:
    - `index.html`: +28行（ChatWork ID入力欄）
    - `js/app.js`: +45行（スキーマチェック、条件付き送信）
    - `migrations/001_add_chatwork_account_id.sql`: 新規作成
  - **設計書**:
    - `docs/12_org_chart_frontend_design.md`: 新規作成（Phase 1完了）
  - **デプロイ**: X Server (sv10875.xserver.jp) に反映済み
  - **効果**: ソウルくんがChatWork IDでユーザーを特定し、正確なタスクリマインドが可能に

- **2026-01-25 14:30 JST**: Phase 3.5 バグ修正 + 96件テスト追加 ✅ **PR #102**
  - **実施者**: Claude Code
  - **作業内容**:
    - **UserDepartmentモデル修正**: `role_id`カラム欠落を修正（access_control.pyが依存）
    - **access_control.py修正**: `parent_id` → `parent_department_id`（2箇所）
    - **organization_sync.py修正**: バリデーション順序最適化（孤立→循環の順に変更）
  - **テスト追加**:
    - `test_access_control.py`: 60件（権限レベル、部署アクセス、エッジケース）
    - `test_organization_sync.py`: 36件（バリデーション、トポロジカルソート、循環/孤立検出）
  - **テスト結果**: 997件全パス
  - **10の鉄則準拠**:
    - organization_idフィルタ: 全クエリに含まれる
    - SQLインジェクション対策: パラメータ化クエリ使用
    - エラー時安全側: 空リスト/Falseを返す設計

- **2026-01-25 12:22 JST**: google-genai SDK移行 本番デプロイ完了 ✅ **PR #101**
  - **実施者**: Claude Code
  - **背景**: PR #99でマージされた新SDK移行を本番環境に適用
  - **作業内容**:
    - **watch-google-drive**: revision 00013-yiq（すでにデプロイ済み）
    - **soulkun-api**: revision 00039-z2q（新規デプロイ）
  - **修正内容**:
    - `api/requirements.txt`: 依存関係追加
      - google-api-python-client>=2.111.0（lib/google_drive.py依存）
      - google-auth>=2.25.0（lib/google_drive.py依存）
      - pytz>=2024.1（lib/goal_notification.py依存）
      - jpholiday>=0.1.9（lib/business_day.py依存）
    - `Dockerfile`: PYTHONPATH修正
      - `/app` → `/app:/app/api`
      - lib/とapi/app/の両方にアクセス可能に
  - **動作確認**:
    - soulkun-api: `{"name":"Soul-kun API","version":"3.5.0","status":"running"}`
    - watch-google-drive: `{"status":"completed","sync_id":"..."}`
  - **10の鉄則準拠**: 依存関係追加のみ、DB操作なし

- **2026-01-25 12:15 JST**: google-genai SDK移行 ✅ **PR #99**
  - **実施者**: Claude Code
  - **背景**: `google-generativeai`は2025年8月31日でサポート終了、新SDK`google-genai`への移行が必要
  - **作業内容**:
    - `lib/embedding.py`: 新SDK構造に対応
      - `import google.generativeai as genai` → `from google import genai`
      - `genai.configure()` → `genai.Client()`
      - `genai.embed_content()` → `client.models.embed_content()`
      - task_type: `retrieval_document` → `RETRIEVAL_DOCUMENT`
      - レスポンス: `['embedding']` → `.embeddings[0].values`
      - バッチ処理がネイティブでリスト対応
    - `api/requirements.txt`: `google-generativeai>=0.8.0` → `google-genai>=1.0.0`
    - `watch-google-drive/requirements.txt`: 同上
    - `tests/conftest.py`: モックを新SDK構造に対応
  - **後方互換**:
    - task_typeの旧形式（小文字）も`TASK_TYPE_MAP`で変換
    - 既存インターフェースを維持
  - **テスト**: 901件全パス（embedding関連15件含む）
  - **10の鉄則準拠**: DB操作なし、APIキーは環境変数/Secret Managerから取得
  - **参考**: https://ai.google.dev/gemini-api/docs/migrate
  - **デプロイ待ち**: watch-google-drive, api（Cloud Run）

- **2026-01-25 11:45 JST**: Pinecone IDパースのバグ修正 ✅ **PR #97**
  - **実施者**: Claude Code
  - **問題**: `parse_pinecone_id()`がorganization_idにアンダースコアを含むIDを正しくパースできなかった
  - **原因**: `split("_", 1)`で最初の`_`で分割していたため、`org_soulsyncs`が`org`になっていた
  - **修正内容**:
    - `_doc`プレフィックスを探してorganization_idとdocument_idを分離
    - ValueError例外処理を追加
    - フォールバックロジックを維持
  - **テスト**: 2件のエッジケーステスト追加、19件全パス、901件の全体テストパス
  - **10の鉄則準拠**: パース処理のみ、DB操作なし

- **2026-01-25 11:10 JST**: 土日祝日リマインドスキップ機能 本番デプロイ完了 ✅ **PR #95**
  - **実施者**: Claude Code
  - **要望**: タスクリマインドと遅延タスク報告を土日祝日には送らないでほしい
  - **実装内容**:
    - `lib/business_day.py`: 営業日判定ユーティリティ新規作成
    - `is_business_day()`: 土日・祝日を除外した営業日判定
    - `jpholiday`ライブラリで日本の祝日を判定
    - `remind-tasks/main.py`: 営業日判定を追加
    - `overdue_handler.py`: 営業日判定を追加
  - **動作**:
    - 営業日（平日かつ祝日でない）: 通常通りリマインド送信
    - 土日: スキップ（理由: 「土曜日」「日曜日」）
    - 祝日: スキップ（理由: 祝日名。例「元日」「成人の日」）
  - **デプロイ**:
    - remind-tasks: revision 00040-civ
    - chatwork-webhook: revision 00127-miy
  - **テスト**: 20件のユニットテスト追加、882件の既存テストパス
  - **10の鉄則準拠**: 新規SQL追加なし、フォールバック設計あり

- **2026-01-25 10:50 JST**: タスク要約途切れバグ修正 本番デプロイ完了 ✅ **PR #93**
  - **実施者**: Claude Code
  - **問題**: タスク遅延リマインド等でタスク要約が途中で途切れる（「[:30]」や「[:40]」で直接切り詰めていた）
  - **根本原因**: 15箇所で`prepare_task_display_text()`を使わず直接切り詰めしていた
  - **修正内容**:
    - `overdue_handler.py`: `_format_body_short()`ヘルパー追加、6箇所修正
    - `task_handler.py`: `_fallback_truncate()`静的メソッド追加、3箇所修正
    - `main.py`: OverdueHandler初期化に依存性注入
    - `remind-tasks/main.py`: 5箇所を`lib_prepare_task_display_text()`に置換
    - `sync-chatwork-tasks/main.py`: 3箇所をインラインフォールバックに置換
  - **改善点**: 句点「。」、読点「、」、助詞「を」「に」「で」「が」「は」「の」の後ろで自然に切れる
  - **デプロイ**:
    - chatwork-webhook: revision 00126-rum
    - remind-tasks: revision 00039-nix
    - sync-chatwork-tasks: revision 00046-vow
  - **テスト**: 371件のユニットテスト全パス
  - **10の鉄則準拠**: 新規SQL追加なし、フォールバック設計維持

- **2026-01-25 10:25 JST**: Phase 4前リファクタリング 本番デプロイ完了 ✅ **v10.24.7**
  - **実施者**: Claude Code
  - **作業内容**:
    - 6ハンドラーの段階的有効化デプロイを実施
    - Phase A: 全ハンドラー無効でデプロイ（rev 00119）
    - Phase B: 1つずつ有効化（rev 00120→00125）
    - Phase C: 最終動作確認（エラーなし）
  - **有効化したハンドラー**（計3,729行）:
    | ハンドラー | 行数 | リビジョン |
    |-----------|------|-----------|
    | memory_handler.py | 302 | 00120 |
    | proposal_handler.py | 553 | 00121 |
    | task_handler.py | 462 | 00122 |
    | overdue_handler.py | 817 | 00123 |
    | goal_handler.py | 551 | 00124 |
    | knowledge_handler.py | 1,044 | 00125 |
  - **環境変数**:
    - USE_NEW_MEMORY_HANDLER=true
    - USE_NEW_PROPOSAL_HANDLER=true
    - USE_NEW_TASK_HANDLER=true
    - USE_NEW_OVERDUE_HANDLER=true
    - USE_NEW_GOAL_HANDLER=true
    - USE_NEW_KNOWLEDGE_HANDLER=true
  - **最終リビジョン**: chatwork-webhook-00125-niy
  - **ロールバック方法**: 該当ハンドラーの環境変数をfalseに設定
  - **10の鉄則準拠**: 全ハンドラーでorganization_id、SQLインジェクション対策確認済み
  - **テスト**: 208件のユニットテスト全パス

- **2026-01-25 09:50 JST**: セッション復旧・進捗記録更新 ✅ **PR #90**
  - **実施者**: Claude Code
  - **背景**: 作業中にセッションが落ち、中断した作業を復旧
  - **作業内容**:
    - 未コミットのCLAUDE.md変更（PR #89進捗エントリ）を検出
    - ブランチ保護ルールに従い、PRワークフローを完全実行
    - Quality Checks全パス（lib/同期、禁止パターン、ユニットテスト、Quality Gate）
    - Claude自身のダブルチェック実施（10の鉄則、セキュリティ、設計整合性）
    - PR #90をマージ、ブランチクリーンアップ完了
  - **変更ファイル**:
    - `CLAUDE.md`: +11行, -1行（PR #89進捗エントリ追加、タイムスタンプ更新）
  - **実行したワークフロー**:
    1. `git status` / `git diff` で状況把握
    2. `git add` / `git commit` でコミット作成
    3. `git checkout -b` でfeatureブランチ作成
    4. `git push -u origin` でリモートにプッシュ
    5. `gh pr create` でPR作成
    6. Quality Checks完了待ち（4チェック全パス）
    7. ダブルチェック実施（GO判定）
    8. `gh pr merge --merge --delete-branch` でマージ
    9. `git fetch --prune` / `git pull` でローカル同期
  - **教訓**: セッション落ち時の復旧手順を確立

- **2026-01-25 00:45 JST**: 進捗記録必須ルール追加 ✅ **PR #89**
  - **実施者**: Claude Code
  - **作業内容**:
    - CLAUDE.mdに「📊 進捗記録の更新（必須）」セクションを追加
    - 更新タイミング: PRマージ時、新機能実装時、バグ修正時、本番デプロイ時、リファクタリング時
    - 記録テンプレート: 日時、作業タイトル、実施者、作業内容、変更ファイル、テスト、10の鉄則準拠
    - 更新手順: 先頭追加、日時更新、Phase状態更新
  - **変更ファイル**:
    - `CLAUDE.md`: +35行（新規セクション追加）

- **2026-01-25 00:30 JST**: Phase 2-8 KnowledgeHandler抽出完了 (v10.24.7) ✅ **PR #88**
  - **実施者**: Claude Code
  - **作業内容**:
    - `handlers/knowledge_handler.py`（1,044行）を新規作成
    - `KnowledgeHandler`クラス:
      - 定数: `KNOWLEDGE_KEYWORDS`（キーワード辞書）、`QUERY_EXPANSION_MAP`（クエリ拡張）
      - 静的メソッド: `extract_keywords()`, `expand_query()`, `calculate_keyword_score()`
      - DB操作: `ensure_knowledge_tables()`, `save_knowledge()`, `delete_knowledge()`, `get_all_knowledge()`, `get_knowledge_for_prompt()`
      - 検索: `search_phase3_knowledge()`, `format_phase3_results()`, `integrated_knowledge_search()`, `search_legacy_knowledge()`
      - ハンドラー: `handle_learn_knowledge()`, `handle_forget_knowledge()`, `handle_list_knowledge()`, `handle_query_company_knowledge()`, `handle_local_learn_knowledge()`
    - main.pyにインポートブロック追加（`USE_NEW_KNOWLEDGE_HANDLER`フラグ）
    - `_get_knowledge_handler()`シングルトン初期化関数追加
    - 5つのラッパー関数更新（フォールバック付き）
  - **テスト**: 58件のユニットテスト追加（`tests/test_knowledge_handler.py`）
    - 定数テスト（6件）
    - 初期化テスト（4件）
    - キーワード抽出・クエリ拡張テスト（8件）
    - キーワードスコア計算テスト（5件）
    - DB操作テスト（11件）
    - 検索テスト（4件）
    - ハンドラーテスト（20件）
  - **全ハンドラーテスト**: 208件パス
  - **10の鉄則準拠**: organization_id, SQLインジェクション対策, フォールバック設計
  - **Quality Checks**: 全パス（禁止パターン, lib/同期, ユニットテスト）
  - **Feature Flag**: `USE_NEW_KNOWLEDGE_HANDLER=false`で旧実装に戻せる

- **2026-01-25 00:00 JST**: Phase 2-3〜2-8 リファクタリング完了 ✅ **main.py分割完了**
  - **実施者**: Claude Code
  - **概要**: chatwork-webhook/main.pyから6つのハンドラーモジュールを抽出
  - **抽出結果**:
    | Phase | ハンドラー | 行数 | バージョン | テスト数 |
    |-------|-----------|------|-----------|---------|
    | 2-3 | memory_handler.py | 302 | v10.24.3 | 18 |
    | 2-4 | proposal_handler.py | 553 | v10.24.2 | 15 |
    | 2-5 | task_handler.py | 462 | v10.24.4 | 28 |
    | 2-6 | overdue_handler.py | 817 | v10.24.5 | 30 |
    | 2-7 | goal_handler.py | 551 | v10.24.6 | 59 |
    | 2-8 | knowledge_handler.py | 1,044 | v10.24.7 | 58 |
    | **合計** | - | **3,737** | - | **208** |
  - **設計パターン**:
    - 依存性注入（外部依存をコンストラクタで注入）
    - Feature Flag（環境変数で旧実装にフォールバック可能）
    - シングルトンパターン（遅延初期化）
    - ラッパー関数（既存シグネチャ維持）
  - **main.py状態**: 9,627行（フォールバック実装維持のため減少は限定的）
  - **次のステップ**: 本番デプロイ後、フォールバック実装を段階的に削除予定

- **2026-01-24 22:00 JST**: v10.23.3 lib/同期チェック拡張 + report-generator再デプロイ ✅ **完了**
  - **実施者**: Claude Code
  - **PR #87**: Quality Checksワークフロー拡張
    - lib/同期チェック対象を1モジュール→7モジュール（20+ファイル）に拡大
    - text_utils.py, goal_setting.py, mvv_context.py, report_generator.py, audit.py
    - lib/memory/*, lib/detection/* ディレクトリ対応
  - **report-generator再デプロイ**: revision 00006-quy
    - v10.23.2変更（目標進捗+MVV連動）を本番適用
    - entry-point: report_generator
  - **変更ファイル**:
    - `.github/workflows/quality-checks.yml`: 221行→314行

- **2026-01-24 21:30 JST**: Phase 2C-2 日報・週報自動生成 + Phase 2.5連動 + MVV統合 (v10.23.2) ✅ **完了**
  - **実施者**: Claude Code
  - **PR #84**: Phase 2.5目標設定とMVV統合
  - **作業内容**:
    - `GoalProgressFetcher`クラス: goalsテーブルから現在の目標を取得
    - `EncouragementGenerator`クラス: MVV・組織論ベースの励ましメッセージ生成
    - 日報・週報に目標進捗セクション追加（進捗バー、WHY、HOW、期限表示）
    - 選択理論の5つの基本欲求を意識した言葉かけ
    - 行動指針10箇条と成果のマッチング
  - **コミュニケーションスタイル統一完了**:
    - 通常会話 → MVV・組織論ベース ✅
    - 目標設定 → WHY/WHAT/HOW対話 ✅
    - 日報・週報 → MVV連動 + 目標進捗 ✅ ← 今回追加
  - **変更ファイル**:
    - `lib/report_generator.py`: +535行
    - `chatwork-webhook/lib/report_generator.py`: 同期
    - `report-generator/lib/report_generator.py`: 同期
    - `report-generator/lib/mvv_context.py`: 新規追加
    - `tests/test_report_generator.py`: +200行（37テストケース全パス）
  - **フォールバック設計**: MVVモジュール利用不可でも動作

- **2026-01-24 20:29 JST**: Phase 2C-1 MVV・組織論的行動指針 本番有効化 ✅ **本番デプロイ完了**
  - **実施者**: Claude Code
  - **作業内容**:
    - PR #74: lib/mvv_context.py（743行）実装・マージ
    - PR #75: 環境変数フラグ `DISABLE_MVV_CONTEXT` 追加
    - PR #76: `import os` 追加修正
    - PR #77: 目標設定終了コマンド追加（v10.22.5）
    - 段階的デプロイ完了（無効→有効）
  - **有効化された機能**:
    - MVV要約（ミッション・ビジョン・バリュー）
    - 組織論的行動指針（選択理論・自己決定理論・心理的安全性・サーバントリーダーシップ）
    - NGパターン検出（帰属意識リスク・人事権関連・メンタルヘルス等）
    - 5つの基本欲求分析（生存・愛/所属・力・自由・楽しみ）
  - **デプロイ**: chatwork-webhook revision 00115-nul
  - **テスト確認**: 「やる気出ない」「成長したい」等のメッセージで組織論的対応を確認
  - **緊急時無効化**: `DISABLE_MVV_CONTEXT=true` で即座に無効化可能
  - **テスト**: 46件（mvv_context）+ 113件（goal_setting）= 159件パス

- **2026-01-24 18:10 JST**: BUG-001修正 v10.22.0（PR #71）✅ **本番デプロイ完了**
  - **実施者**: Claude Code
  - **問題**: 「自分のタスクを教えて」と聞くと、質問したチャットルームのタスクしか検索されず、他のルームにあるタスクが見つからない
  - **原因**: `search_tasks_from_db()`が常に`WHERE room_id = :room_id`でフィルタしていた
  - **修正内容**:
    - `search_tasks_from_db()`に`search_all_rooms`パラメータを追加
    - 自分のタスク検索時（`is_self_search=True`）は全ルームから検索
    - 検索結果をルーム別にグループ化して表示
    - `room_id`, `room_name`を検索結果に追加
  - **変更ファイル**:
    - `chatwork-webhook/main.py`: search_tasks_from_db(), handle_chatwork_task_search()
    - `tests/test_task_search.py`: 9件のテスト追加
  - **後方互換性**: `search_all_rooms=False`がデフォルト（既存動作に影響なし）
  - **10の鉄則準拠**:
    - ✅ SQLインジェクション対策: パラメータ化クエリ使用
    - ✅ 後方互換性: キーワード引数で追加
  - **デプロイ完了**: chatwork-webhook revision 00109-dek (2026-01-24 18:10 JST)

- **2026-01-24 17:41 JST**: Memory Framework通常会話統合完了（PR #68）✅
  - **実施者**: Claude Code
  - **作業内容**: chatwork-webhookにPhase 2 B Memory Frameworkを統合
    - `asyncio`インポート追加（Python 3.10+ 推奨方式）
    - `lib/memory`からクラスインポート
      - ConversationSummary (B1)
      - UserPreference (B2)
      - ConversationSearch (B4)
      - MemoryParameters
    - `process_memory_after_conversation()`関数追加（~150行）
      - 会話完了後に非同期でMemory処理を実行
      - B1: 会話サマリー生成（10件以上で自動トリガー）
      - B4: 会話検索インデックス（ユーザー・AI両方）
    - 会話数閾値による負荷軽減
    - エラーハンドリング（会話処理に影響を与えない設計）
  - **デプロイ**: chatwork-webhook revision 00107-zum
  - **動作確認**: Memory Framework正常ロード確認済み
  - **10の鉄則準拠**:
    - ✅ organization_id: usersテーブルから取得してMemory Frameworkに渡す
    - ✅ SQLインジェクション対策: パラメータ化クエリ使用
    - ✅ フォールバック設計: USE_MEMORY_FRAMEWORK=Falseで無効化可能
  - **Phase 2「覚える能力」通常会話に統合**:
    - B1 会話サマリー: 10件以上の会話で自動生成
    - B4 会話検索: 全会話をインデックス化

- **2026-01-24 17:04 JST**: Phase 2 A4 + Phase 2.5 本番デプロイ完了（PR #66）✅
  - **実施者**: Claude Code
  - **作業内容**:
    1. **DBマイグレーション - Phase 2 A4 感情変化検出**
       - `emotion_scores`テーブル作成（14カラム、6インデックス）
         - id, organization_id, message_id, room_id, user_id
         - sentiment_score (-1.0〜1.0), sentiment_label, confidence
         - detected_emotions (TEXT[]), analysis_model
         - message_time, analyzed_at, classification, created_at
         - UNIQUE(organization_id, message_id)
         - CHECK: classification = 'confidential' (プライバシー保護)
       - `emotion_alerts`テーブル作成（26カラム、8インデックス）
         - 4種のalert_type: sudden_drop, sustained_negative, high_volatility, recovery
         - 4段階risk_level: critical, high, medium, low
         - CHECK: classification = 'confidential' (プライバシー保護)
       - `notification_logs` CHECK制約更新（emotion_alert追加）
    2. **DBマイグレーション - Phase 2.5 Memory統合**
       - `goal_setting_user_patterns`テーブル作成（18カラム、5インデックス）
         - dominant_pattern, pattern_history (JSONB)
         - total_sessions, completed_sessions, avg_retry_count, completion_rate
         - why/what/how_pattern_tendency (JSONB)
         - avg_specificity_score, preferred_feedback_style
         - effective_retry_templates (TEXT[])
         - UNIQUE(organization_id, user_id)
    3. **Cloud Function再デプロイ**
       - pattern-detection: revision 00005-koz
       - /emotion-detectionエンドポイント追加
       - memory=512MB, timeout=300s, max-instances=5
    4. **Cloud Scheduler作成**
       - emotion-detection-daily: 毎日 10:00 JST
       - URI: https://asia-northeast1-soulkun-production.cloudfunctions.net/pattern-detection/emotion-detection
       - body: {"dry_run": false}
    5. **動作確認テスト**
       - エンドポイント疎通確認: ✅成功
       - レスポンス: {"success": true, "message": "分析対象の質問がありませんでした"}
  - **10の鉄則準拠確認**:
    - ✅ organization_idフィルタ: 全クエリに含まれる
    - ✅ SQLインジェクション対策: パラメータ化クエリ使用
    - ✅ 機密区分: emotion_*テーブルはCONFIDENTIAL強制
    - ✅ 監査ログ対応: audit_logs連携済み
  - **Phase 2「気づく能力」完全稼働**:
    - A1 パターン検知: 毎時15分実行
    - A2 属人化検出: 毎日06:00実行
    - A3 ボトルネック検出: 毎日08:00実行
    - A4 感情変化検出: 毎日10:00実行 ← NEW

- **2026-01-24**: Phase 2.5 + B Memory統合（PR #64）✅完了
  - **GoalSettingContextEnricher**（lib/memory/goal_integration.py 396行）
    - B1(会話サマリー) + B2(ユーザー嗜好) + 目標パターンを統合
    - パーソナライズ推奨事項を自動生成（フィードバックスタイル、注力エリア、回避パターン）
    - get_personalization_summary()でソウルくんが参照する簡潔な情報を出力
  - **GoalSettingUserPatternAnalyzer**（lib/goal_setting.py +313行）
    - ユーザーの目標設定パターンを分析・蓄積
    - dominant_pattern（最頻出パターン）、completion_rate（完了率）、avg_retry_count（平均リトライ回数）
    - WHY/WHAT/HOW各ステップの傾向分析
  - **GoalHistoryProvider**（lib/goal_setting.py +199行）
    - 過去の目標・達成状況を取得
    - 類似目標の成功パターンを分析
    - フィードバック改善に活用
  - **パーソナライズドフィードバック**
    - _personalize_feedback(): 過去パターンに基づくフィードバック調整
    - _learn_from_interaction(): セッション完了時に嗜好を学習
    - _update_preference_on_complete(): B2ユーザー嗜好にgoal_setting使用状況を記録
  - **DBマイグレーション**
    - `goal_setting_user_patterns`テーブル（13カラム、3インデックス、3 CHECK制約）
    - UNIQUE(organization_id, user_id)
  - **テスト**: 184件のユニットテスト（全パス）
  - **10の鉄則準拠**: organization_idフィルタ、SQLインジェクション対策、フォールバック設計

- **2026-01-24**: Phase 2 B 覚える能力（PR #62）✅完了
  - **Memory Framework**（8ファイル、8,303行）
    - `base.py`: BaseMemoryクラス（LLM連携、OpenRouter API）
    - `constants.py`: MemoryParameters、Enum、プロンプト定義
    - `exceptions.py`: 10種のカスタム例外クラス
    - `conversation_summary.py`: B1 会話サマリー記憶
    - `user_preference.py`: B2 ユーザー嗜好学習
    - `auto_knowledge.py`: B3 組織知識自動蓄積（A1パターン検出連携）
    - `conversation_search.py`: B4 会話検索インデックス
  - **DBマイグレーション完了**
    - `conversation_summaries`: 会話サマリー（key_topics, mentioned_persons, mentioned_tasks）
    - `user_preferences`: ユーザー嗜好（response_style, feature_usage等5タイプ）
    - `organization_auto_knowledge`: 自動蓄積FAQ（draft→approved→rejected→archived）
    - `conversation_index`: 会話検索（キーワード、エンティティ、embedding_id）
    - 21インデックス、31 CHECK制約、4外部キー
  - **テスト**: 82件のユニットテスト（全パス）
  - **10の鉄則準拠**: organization_idフィルタ、機密区分、パラメータ化SQL

- **2026-01-24**: v10.19.4 目標設定セッション検出修正（PR #61）✅完了
  - **バグ修正**: 既存セッション検出時に'intro'→'why'ステップで開始するよう修正
  - **変更ファイル**: lib/goal_setting.py、chatwork-webhook/lib/goal_setting.py、chatwork-webhook/main.py
  - **テスト**: 102件のユニットテスト（全パス）

- **2026-01-24**: v10.20.0 Phase 2 A4 感情変化検出（PR #59）✅完了
  - **Phase 2「気づく能力」完成**（A1〜A4全て完了）
  - **EmotionDetectorクラス**（~900行）
    - BaseDetectorを継承した感情変化検出器
    - LLM（Gemini 3 Flash）による感情スコアリング（-1.0〜1.0）
    - 4種のアラートタイプ: sudden_drop, sustained_negative, high_volatility, recovery
    - 4段階リスクレベル: CRITICAL, HIGH, MEDIUM, LOW
    - soulkun_insightsへの自動登録（CRITICAL/HIGH）
  - **DBスキーマ**
    - emotion_scores: メッセージごとの感情スコア
    - emotion_alerts: 検出されたアラート
    - CHECK制約でCONFIDENTIAL分類を強制
  - **プライバシー配慮**
    - 全データはCONFIDENTIAL分類（DB制約で強制）
    - 管理者のみ通知（本人には直接通知しない）
    - メッセージ本文は保存しない（統計のみ）
  - **Cloud Function**
    - エンドポイント: POST /emotion-detection
    - 実行タイミング: 毎日 10:00 JST（Cloud Scheduler）
  - **テスト**
    - 64件のユニットテスト（全てパス）
    - パラメータ、Enum、リスクレベル判定、InsightData生成、プライバシー検証
  - **10の鉄則準拠**
    - organization_idフィルタ必須
    - SQLインジェクション対策（パラメータ化）
    - 監査ログ対応
  - **デプロイ完了** (2026-01-24 17:04 JST)
    - ✅ DBマイグレーション実行（emotion_scores, emotion_alerts）
    - ✅ Cloud Functionデプロイ（pattern-detection rev00005-koz）
    - ✅ Cloud Scheduler設定（emotion-detection-daily 10:00 JST）
    - ✅ Phase 2.5 DBマイグレーション（goal_setting_user_patterns）

- **2026-01-24**: v10.19.3 臨機応変な対応（Adaptive Response Enhancement）（PR #58）✅完了
  - **新機能**
    - 質問検出: 「？」で終わる、「どうしたらいい」「どうすれば」等のヘルプ要求
    - 困惑検出: 「わからない」「難しい」「迷う」等、全ステップ共通
    - 極端に短い回答検出: <5文字（極短）、5-10文字（非常に短い）
    - 具体性スコアリング強化: 文字数、数値表現、期限表現、行動動詞
    - リトライ回数に応じたトーン変更: 2回目=優しい、3回目=受け入れ
  - **新規テンプレート12種**
    - `help_question_why/what/how`: ステップ別の質問への回答
    - `help_confused_why/what/how`: ステップ別の困惑への対応（前回答参照）
    - `too_short`: 極端に短い回答への対応
    - `retry_gentle`: 2回目リトライ用（優しいトーン）
    - `retry_accepting`: 3回目リトライ用（受け入れ準備）
  - **新規定数**
    - `LENGTH_THRESHOLDS`: 長さ閾値（5/10/20/30文字）
    - `STEP_EXPECTED_KEYWORDS`: ステップ別期待キーワード
  - **テスト**
    - 102件のユニットテスト追加（tests/test_goal_setting.py）
    - パターン検出優先度テスト
    - フィードバック生成テスト
    - エッジケーステスト
  - **設計書更新**
    - `docs/05_phase2-5_goal_achievement.md` v1.8

- **2026-01-24**: v10.19.0 Phase 2.5 目標設定対話フロー（PR #53, #55, #56）✅完了
  - **目標設定対話機能**
    - WHY（なぜ）→ WHAT（何を）→ HOW（どうやって）の3ステップ対話
    - 選択理論/Achievement社メソッドに基づく設計
    - 9種のNGパターン検出（ng_career, ng_abstract, ng_other_blame, ng_no_goal, ng_mental_health, ng_private_only, ng_too_high, ng_not_connected, unknown）
    - MAX_RETRY_COUNT=3（3回NGで強制的に次ステップへ）
    - 24時間セッションタイムアウト
  - **新規ファイル**
    - `lib/goal_setting.py`（909行）: 対話管理クラス・パターン検出
    - `chatwork-webhook/lib/goal_setting.py`: Cloud Functions用コピー
    - `migrations/20260124_goal_setting_tables.sql`: DBテーブル定義
  - **DBテーブル**
    - `goal_setting_sessions`: セッション管理（24時間TTL）
    - `goal_setting_logs`: 対話ログ（パターン検出結果含む）
    - `goal_setting_patterns`: パターンマスタ（10パターン初期登録）
    - `goal_setting_pattern_stats`: 分析用ビュー
  - **設計書更新**
    - `docs/05_phase2-5_goal_achievement.md` v1.7
    - chatwork_room_id VARCHAR(50)に拡張
    - MAX_RETRY_COUNT=3 セクション追加
  - **デプロイ**
    - chatwork-webhook: revision 00098-yik
    - max-instances=20, memory=512MB
  - **テスト**
    - 統合テスト: 全ステップの対話フロー確認
    - パターン検出テスト: 11/11件パス

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
