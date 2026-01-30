# 第5章 Phase 3 詳細設計書：ナレッジ系（ソウルくんの脳みそ）

**バージョン:** v1.1.0
**作成日:** 2026-01-19
**最終更新:** 2026-01-19
**ステータス:** 設計完了・実装準備完了

> **📄 補遺ドキュメント:** Googleドライブ連携の詳細設計は [06_phase3_google_drive_integration.md](./06_phase3_google_drive_integration.md) を参照

---

## Document Contract（SoT宣言）

| 項目 | 内容 |
|------|------|
| **この文書の役割** | Phase 3ナレッジ検索機能（ソウルくんの脳みそ）の詳細設計書 |
| **書くこと** | MVP完了定義、documents/document_versions/document_chunks/knowledge_feedback/knowledge_search_logsテーブル設計、Pinecone統合設計、検索・フィードバックAPI設計、RAG検索フロー、Phase 3.5連携設計 |
| **書かないこと** | Googleドライブ連携の詳細（→06_phase3_google_drive_integration.md）、試験運用手順（→PHASE3_TRIAL_OPERATION_GUIDE.md） |
| **SoT（この文書が正）** | Phase 3 MVP完了定義（9項目）、documents/document_chunks等のDBスキーマ、Pineconeインデックス・メタデータ設計、ナレッジ検索API仕様、機密区分（classification）とカテゴリ（category）の定義 |
| **Owner** | Tech Lead |
| **更新トリガー** | MVP要件の変更、DBスキーマの変更、Pinecone設計の変更、API仕様の変更 |

---

## 目次

1. [概要と目的](#1-概要と目的)
2. [Phase 3 MVP完了定義（9項目）](#2-phase-3-mvp完了定義9項目)
3. [データベース設計](#3-データベース設計)
   - 3.1 [documents テーブル](#31-documents-テーブル)
   - 3.2 [document_versions テーブル](#32-document_versions-テーブル)
   - 3.3 [document_chunks テーブル](#33-document_chunks-テーブル)
   - 3.4 [knowledge_feedback テーブル](#34-knowledge_feedback-テーブル)
   - 3.5 [knowledge_search_logs テーブル](#35-knowledge_search_logs-テーブル)
   - 3.6 [ER図](#36-er図)
4. [Pinecone統合設計](#4-pinecone統合設計)
   - 4.1 [Pineconeインデックス設計](#41-pineconeインデックス設計)
   - 4.2 [Metadata設計](#42-metadata設計)
   - 4.3 [Namespace設計](#43-namespace設計)
5. [API設計](#5-api設計)
   - 5.1 [ドキュメント管理API](#51-ドキュメント管理api)
   - 5.2 [ドキュメント取り込みAPI](#52-ドキュメント取り込みapi)
   - 5.3 [ナレッジ検索API](#53-ナレッジ検索api)
   - 5.4 [フィードバックAPI](#54-フィードバックapi)
   - 5.5 [検索品質評価API](#55-検索品質評価api)
6. [処理フロー設計](#6-処理フロー設計)
   - 6.1 [ドキュメント取り込みフロー](#61-ドキュメント取り込みフロー)
   - 6.2 [RAG検索フロー](#62-rag検索フロー)
   - 6.3 [フィードバック処理フロー](#63-フィードバック処理フロー)
7. [Phase 3.5連携設計（組織階層）](#7-phase-35連携設計組織階層)
8. [エラーハンドリング設計](#8-エラーハンドリング設計)
9. [テスト設計](#9-テスト設計)
10. [マイグレーション計画](#10-マイグレーション計画)
11. [実装チェックリスト](#11-実装チェックリスト)

---

## 1. 概要と目的

### 1.1 Phase 3の位置づけ

```
Phase 1: タスク管理基盤 ✅完了
Phase 1-B: タスク検知・監視 ✅完了
Phase 2: AI応答・評価機能 ✅完了
Phase 2.5: 目標達成支援 🔄実装中
    ↓
【★ Phase 3: ナレッジ系（ソウルくんの脳みそ）】← 今ここの設計
    ↓
Phase 3.5: 組織階層連携
Phase 3.6: 組織図システム製品化
Phase C: 会議系（議事録自動化）
Phase 4: テナント分離（BPaaS対応）
```

### 1.2 Phase 3の目的

**「ソウルくんが会社のナレッジを理解し、根拠に基づいた回答ができるようになる」**

### 1.3 Phase 3で解決する課題

| # | 現状の課題 | Phase 3で解決 |
|---|----------|-------------|
| 1 | 「就業規則どこにある？」→ 毎回管理部に聞く | ソウルくんがナレッジを検索して回答 |
| 2 | 回答の根拠がわからない | 引用元（ドキュメント名、ページ、セクション）を提示 |
| 3 | 古い情報を参照してしまう | 最終更新日を表示、注意書きを付与 |
| 4 | 機密情報の漏洩リスク | アクセス制御（最低2段階）を実装 |
| 5 | 回答精度が不明 | フィードバック収集、検索品質の可視化 |

### 1.4 設計原則（RAG設計の4原則に準拠）

| # | 原則 | Phase 3での適用 |
|---|------|----------------|
| 1 | **検索と生成の責務分離** | 検索結果が薄いなら生成しない |
| 2 | **機密区分の早期設計** | MVP時点から4段階の機密区分を持つ |
| 3 | **ナレッジ閲覧の監査** | 「誰が何を見たか」をaudit_logsに記録 |
| 4 | **組織階層の動的制御** | Phase 3.5でアクセス権限を組織階層から動的計算 |

### 1.5 10の鉄則の適用

| # | 鉄則 | Phase 3での適用 |
|---|------|----------------|
| 1 | 全テーブルにorganization_id | documents, document_chunks等すべてに適用 |
| 2 | RLS実装 | Phase 4Aで完全実装、Phase 3ではアプリレベルで制御 |
| 3 | 監査ログ | confidential以上の検索をaudit_logsに記録 |
| 4 | API認証必須 | Bearer Token必須 |
| 5 | ページネーション | 1000件超えAPIに実装 |
| 6 | キャッシュTTL | Redisキャッシュ5分 |
| 7 | APIバージョニング | /api/v1/knowledge/ |
| 8 | エラーメッセージ制限 | 機密情報を含めない |
| 9 | SQLインジェクション対策 | パラメータ化クエリ |
| 10 | トランザクション内API禁止 | 外部API呼び出しはトランザクション外 |

---

## 2. Phase 3 MVP完了定義（9項目）

| # | 要件 | 詳細 | テスト方法 | 優先度 |
|---|------|------|-----------|--------|
| 1 | **ドキュメント取り込み** | A（理念）、B（マニュアル）、F（サービス情報）をPineconeに登録 | 3カテゴリのドキュメントが検索可能 | 必須 |
| 2 | **参照検索** | 質問に対して関連箇所を返す | 「経費精算」で関連チャンクがヒット | 必須 |
| 3 | **根拠提示** | 回答に引用/出典を付ける | 回答に「出典: マニュアルp.5」が含まれる | 必須 |
| 4 | **注意書き** | 「最終更新日」「最新版は管理部に確認」を付ける | 全回答に注意書きが含まれる | 必須 |
| 5 | **フィードバック** | 「役に立った/違う」を記録する | knowledge_feedbackにデータが記録される | 必須 |
| 6 | **アクセス制御** | 最低でも「全員OK/管理部のみ」の2段階 | public/internalの2段階が動作 | 必須 |
| 7 | **引用粒度** | ページ/見出し/段落（chunk_id）まで特定できる | chunk_idがレスポンスに含まれる | 必須 |
| 8 | **回答拒否条件** | 根拠が取れない場合は「回答できません」を返す | 無関係な質問で拒否メッセージが返る | 必須 |
| 9 | **検索品質評価** | 週次で「ヒットしない質問」「誤ヒット」を可視化 | 管理画面で品質メトリクスが表示される | 必須 |

---

## 3. データベース設計

### 3.1 documents テーブル

**目的:** ナレッジとして管理するドキュメントのメタデータを保存

**テーブル定義:**

```sql
-- ドキュメントマスタテーブル
CREATE TABLE documents (
    -- === 主キー ===
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- === テナント分離（10の鉄則 #1） ===
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- === 基本情報 ===
    title VARCHAR(500) NOT NULL,                    -- ドキュメントタイトル
    description TEXT,                               -- 概要説明
    file_name VARCHAR(255) NOT NULL,                -- 元ファイル名
    file_path VARCHAR(1000),                        -- GCSパス（gs://bucket/path）
    file_type VARCHAR(50) NOT NULL,                 -- 'pdf', 'docx', 'txt', 'md', 'html'
    file_size_bytes BIGINT,                         -- ファイルサイズ
    file_hash VARCHAR(64),                          -- SHA-256ハッシュ（重複検知用）

    -- === カテゴリと機密区分 ===
    category VARCHAR(1) NOT NULL,                   -- 'A', 'B', 'C', 'D', 'E', 'F'
    -- A: 理念・哲学（MVV、3軸、行動指針）
    -- B: 業務マニュアル
    -- C: 就業規則（Q3以降）
    -- D: テンプレート（Q3以降）
    -- E: 顧客情報（Q3以降）
    -- F: サービス情報

    classification VARCHAR(20) NOT NULL DEFAULT 'internal',
    -- 'public': 社外にも公開可能
    -- 'internal': 社員なら誰でも閲覧可
    -- 'confidential': 部門/役職で閲覧制限（Phase 3.5で組織階層連携）
    -- 'restricted': 経営陣のみ

    -- === 組織階層連携（Phase 3.5対応準備） ===
    department_id UUID REFERENCES departments(id),  -- 所属部署（confidentialの場合に使用）
    owner_user_id UUID REFERENCES users(id),        -- ドキュメントオーナー

    -- === バージョン管理 ===
    current_version INT NOT NULL DEFAULT 1,         -- 現在のバージョン番号
    is_latest BOOLEAN DEFAULT TRUE,                 -- 最新バージョンかどうか

    -- === 処理状態 ===
    processing_status VARCHAR(50) NOT NULL DEFAULT 'pending',
    -- 'pending': 取り込み待ち
    -- 'processing': 取り込み中
    -- 'chunking': チャンク分割中
    -- 'embedding': エンベディング生成中
    -- 'indexing': Pineconeインデックス中
    -- 'completed': 完了
    -- 'failed': 失敗
    -- 'archived': アーカイブ済み

    processing_error TEXT,                          -- エラーメッセージ
    processed_at TIMESTAMPTZ,                       -- 処理完了日時

    -- === チャンク統計 ===
    total_chunks INT DEFAULT 0,                     -- 総チャンク数
    total_pages INT DEFAULT 0,                      -- 総ページ数（PDF等の場合）
    total_tokens INT DEFAULT 0,                     -- 総トークン数（参考値）

    -- === 検索統計 ===
    search_count INT DEFAULT 0,                     -- 検索ヒット回数
    feedback_positive_count INT DEFAULT 0,          -- ポジティブフィードバック数
    feedback_negative_count INT DEFAULT 0,          -- ネガティブフィードバック数
    last_searched_at TIMESTAMPTZ,                   -- 最後に検索された日時

    -- === 表示設定 ===
    is_active BOOLEAN DEFAULT TRUE,                 -- 有効フラグ（非表示化用）
    is_searchable BOOLEAN DEFAULT TRUE,             -- 検索対象かどうか
    display_order INT DEFAULT 0,                    -- 表示順

    -- === 注意書き設定 ===
    disclaimer_text TEXT,                           -- カスタム注意書き
    requires_human_verification BOOLEAN DEFAULT FALSE, -- 「管理部に確認」を表示

    -- === タグ・メタデータ ===
    tags TEXT[],                                    -- タグ配列
    metadata JSONB DEFAULT '{}',                    -- 拡張メタデータ

    -- === 監査情報 ===
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_by UUID REFERENCES users(id),
    updated_by UUID REFERENCES users(id),
    deleted_at TIMESTAMPTZ,                         -- 論理削除日時
    deleted_by UUID REFERENCES users(id),

    -- === 制約 ===
    CONSTRAINT valid_category CHECK (category IN ('A', 'B', 'C', 'D', 'E', 'F')),
    CONSTRAINT valid_classification CHECK (classification IN ('public', 'internal', 'confidential', 'restricted')),
    CONSTRAINT valid_file_type CHECK (file_type IN ('pdf', 'docx', 'doc', 'txt', 'md', 'html', 'xlsx', 'xls', 'pptx', 'ppt')),
    CONSTRAINT valid_processing_status CHECK (processing_status IN ('pending', 'processing', 'chunking', 'embedding', 'indexing', 'completed', 'failed', 'archived')),
    CONSTRAINT positive_version CHECK (current_version >= 1),
    CONSTRAINT unique_org_file_hash UNIQUE (organization_id, file_hash) -- 同一組織内で重複ファイル禁止
);

-- インデックス
CREATE INDEX idx_documents_org ON documents(organization_id);
CREATE INDEX idx_documents_category ON documents(organization_id, category);
CREATE INDEX idx_documents_classification ON documents(organization_id, classification);
CREATE INDEX idx_documents_department ON documents(department_id) WHERE department_id IS NOT NULL;
CREATE INDEX idx_documents_status ON documents(processing_status);
CREATE INDEX idx_documents_active ON documents(organization_id, is_active) WHERE is_active = TRUE;
CREATE INDEX idx_documents_searchable ON documents(organization_id, is_searchable) WHERE is_searchable = TRUE;
CREATE INDEX idx_documents_created ON documents(created_at DESC);
CREATE INDEX idx_documents_tags ON documents USING GIN(tags);
CREATE INDEX idx_documents_metadata ON documents USING GIN(metadata);

-- コメント
COMMENT ON TABLE documents IS 'ナレッジドキュメントのメタデータ管理テーブル';
COMMENT ON COLUMN documents.category IS 'A:理念, B:マニュアル, C:就業規則, D:テンプレート, E:顧客情報, F:サービス情報';
COMMENT ON COLUMN documents.classification IS 'public:公開, internal:社内, confidential:部門限定, restricted:経営陣のみ';
COMMENT ON COLUMN documents.file_hash IS 'SHA-256ハッシュ。同一ファイルの重複登録を防止';
COMMENT ON COLUMN documents.processing_status IS 'pending→processing→chunking→embedding→indexing→completed の順で遷移';
```

**カラム説明（重要なもの）:**

| カラム | 説明 | 例 |
|--------|------|-----|
| category | ドキュメントカテゴリ | 'B'（マニュアル） |
| classification | 機密区分 | 'internal'（社員全員OK） |
| department_id | 所属部署（confidentialで使用） | dept_sales（営業部） |
| processing_status | 処理状態 | 'completed' |
| file_hash | SHA-256ハッシュ | 重複検知に使用 |
| requires_human_verification | 「管理部に確認」表示 | true |

---

### 3.2 document_versions テーブル

**目的:** ドキュメントのバージョン履歴を管理

**テーブル定義:**

```sql
-- ドキュメントバージョン管理テーブル
CREATE TABLE document_versions (
    -- === 主キー ===
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- === テナント分離 ===
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- === リレーション ===
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,

    -- === バージョン情報 ===
    version_number INT NOT NULL,                    -- バージョン番号（1, 2, 3...）

    -- === ファイル情報（このバージョンの） ===
    file_name VARCHAR(255) NOT NULL,
    file_path VARCHAR(1000),                        -- GCSパス
    file_size_bytes BIGINT,
    file_hash VARCHAR(64),

    -- === 変更内容 ===
    change_summary TEXT,                            -- 変更概要
    change_type VARCHAR(50),                        -- 'major', 'minor', 'patch'

    -- === チャンク情報（このバージョンの） ===
    total_chunks INT DEFAULT 0,
    total_pages INT DEFAULT 0,

    -- === 処理状態 ===
    processing_status VARCHAR(50) NOT NULL DEFAULT 'pending',
    processing_error TEXT,
    processed_at TIMESTAMPTZ,

    -- === Pinecone情報 ===
    pinecone_vectors_count INT DEFAULT 0,           -- Pineconeに登録したベクター数
    pinecone_namespace VARCHAR(255),                -- Pinecone namespace

    -- === フラグ ===
    is_latest BOOLEAN DEFAULT FALSE,                -- 最新バージョンか
    is_active BOOLEAN DEFAULT TRUE,                 -- アクティブか

    -- === 監査情報 ===
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_by UUID REFERENCES users(id),

    -- === 制約 ===
    CONSTRAINT unique_doc_version UNIQUE (document_id, version_number),
    CONSTRAINT positive_version CHECK (version_number >= 1)
);

-- インデックス
CREATE INDEX idx_doc_versions_org ON document_versions(organization_id);
CREATE INDEX idx_doc_versions_doc ON document_versions(document_id);
CREATE INDEX idx_doc_versions_latest ON document_versions(document_id, is_latest) WHERE is_latest = TRUE;
CREATE INDEX idx_doc_versions_status ON document_versions(processing_status);

-- コメント
COMMENT ON TABLE document_versions IS 'ドキュメントのバージョン履歴。更新時に前バージョンを保持';
COMMENT ON COLUMN document_versions.is_latest IS '最新バージョンフラグ。1ドキュメントにつき1つだけTRUE';
```

**バージョン管理フロー:**

```
[ドキュメント更新時]

1. 現在のバージョンのis_latestをFALSEに変更
2. 新しいバージョンレコードを作成（is_latest = TRUE）
3. documentsテーブルのcurrent_versionをインクリメント
4. 新バージョンの処理を開始（チャンク化、エンベディング、インデックス）
5. 処理完了後、旧バージョンのPineconeベクターを削除（オプション）
```

---

### 3.3 document_chunks テーブル

**目的:** ドキュメントを分割したチャンクを管理し、Pineconeとの対応を保持

**テーブル定義:**

```sql
-- ドキュメントチャンクテーブル
CREATE TABLE document_chunks (
    -- === 主キー ===
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- === テナント分離 ===
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- === リレーション ===
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    document_version_id UUID NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,

    -- === チャンク識別 ===
    chunk_index INT NOT NULL,                       -- チャンク番号（0始まり）

    -- === Pinecone連携 ===
    pinecone_id VARCHAR(255) NOT NULL,              -- Pineconeのベクター ID
    -- フォーマット: {org_id}_{doc_id}_{version}_{chunk_index}
    -- 例: org123_doc456_v1_chunk0

    pinecone_namespace VARCHAR(255) NOT NULL,       -- Pinecone namespace
    -- フォーマット: org_{organization_id}
    -- 例: org_soulsyncs

    -- === チャンクコンテンツ ===
    content TEXT NOT NULL,                          -- チャンクのテキスト内容
    content_hash VARCHAR(64),                       -- SHA-256（変更検知用）
    token_count INT,                                -- トークン数（参考値）
    char_count INT,                                 -- 文字数

    -- === 位置情報（引用粒度のため重要） ===
    page_number INT,                                -- ページ番号（PDF等）
    section_title VARCHAR(500),                     -- セクションタイトル
    section_hierarchy TEXT[],                       -- セクション階層 ['第1章', '1.1 概要', '1.1.1 目的']
    start_position INT,                             -- 元文書での開始位置（文字数）
    end_position INT,                               -- 元文書での終了位置（文字数）

    -- === 追加メタデータ ===
    chunk_type VARCHAR(50) DEFAULT 'text',          -- 'text', 'table', 'list', 'code', 'header'
    has_table BOOLEAN DEFAULT FALSE,                -- テーブルを含むか
    has_code BOOLEAN DEFAULT FALSE,                 -- コードを含むか
    has_list BOOLEAN DEFAULT FALSE,                 -- リストを含むか
    language VARCHAR(10) DEFAULT 'ja',              -- 言語コード

    -- === 機密区分（ドキュメントから継承、またはチャンク固有） ===
    classification VARCHAR(20),                     -- チャンク固有の機密区分（NULL=ドキュメントから継承）
    department_id UUID REFERENCES departments(id),  -- チャンク固有の部署（NULL=ドキュメントから継承）

    -- === エンベディング情報 ===
    embedding_model VARCHAR(100),                   -- 'text-embedding-3-small', 'text-embedding-ada-002'
    embedding_dimension INT,                        -- 1536, 3072 など
    embedding_generated_at TIMESTAMPTZ,             -- エンベディング生成日時

    -- === 処理状態 ===
    is_indexed BOOLEAN DEFAULT FALSE,               -- Pineconeにインデックス済みか
    indexed_at TIMESTAMPTZ,                         -- インデックス日時
    index_error TEXT,                               -- インデックスエラー

    -- === 検索統計 ===
    search_hit_count INT DEFAULT 0,                 -- 検索でヒットした回数
    last_hit_at TIMESTAMPTZ,                        -- 最後にヒットした日時
    average_score FLOAT,                            -- 平均スコア（検索品質評価用）

    -- === フラグ ===
    is_active BOOLEAN DEFAULT TRUE,                 -- 有効フラグ

    -- === 監査情報 ===
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- === 制約 ===
    CONSTRAINT unique_pinecone_id UNIQUE (pinecone_id),
    CONSTRAINT unique_doc_chunk UNIQUE (document_id, document_version_id, chunk_index),
    CONSTRAINT valid_chunk_type CHECK (chunk_type IN ('text', 'table', 'list', 'code', 'header', 'mixed'))
);

-- インデックス
CREATE INDEX idx_chunks_org ON document_chunks(organization_id);
CREATE INDEX idx_chunks_doc ON document_chunks(document_id);
CREATE INDEX idx_chunks_version ON document_chunks(document_version_id);
CREATE INDEX idx_chunks_pinecone ON document_chunks(pinecone_id);
CREATE INDEX idx_chunks_page ON document_chunks(document_id, page_number);
CREATE INDEX idx_chunks_indexed ON document_chunks(is_indexed) WHERE is_indexed = TRUE;
CREATE INDEX idx_chunks_active ON document_chunks(is_active) WHERE is_active = TRUE;
CREATE INDEX idx_chunks_search_stats ON document_chunks(search_hit_count DESC);

-- コメント
COMMENT ON TABLE document_chunks IS 'ドキュメントを分割したチャンク。Pineconeベクターと1対1で対応';
COMMENT ON COLUMN document_chunks.pinecone_id IS 'Pineconeベクター ID。フォーマット: {org}_{doc}_{ver}_{idx}';
COMMENT ON COLUMN document_chunks.section_hierarchy IS 'セクション階層。例: ["第1章", "1.1 概要"]';
COMMENT ON COLUMN document_chunks.classification IS 'チャンク固有の機密区分。NULLの場合はドキュメントから継承';
```

**Pinecone IDフォーマット:**

```
{organization_id}_{document_id}_{version_number}_{chunk_index}

例:
org_soulsyncs_doc_manual001_v1_chunk0
org_soulsyncs_doc_manual001_v1_chunk1
org_soulsyncs_doc_manual001_v2_chunk0  ← バージョン2
```

**位置情報の重要性（MVP要件#7: 引用粒度）:**

```python
# 検索結果の引用表示例
{
    "chunk_id": "org_soulsyncs_doc_manual001_v1_chunk5",
    "document_title": "経費精算マニュアル",
    "page_number": 5,
    "section_title": "2.3 経費精算の手順",
    "section_hierarchy": ["第2章 経費", "2.3 経費精算の手順"],
    "citation": "経費精算マニュアル p.5 「2.3 経費精算の手順」"
}
```

---

### 3.4 knowledge_feedback テーブル

**目的:** ナレッジ検索に対するユーザーフィードバックを記録

**テーブル定義:**

```sql
-- ナレッジフィードバックテーブル
CREATE TABLE knowledge_feedback (
    -- === 主キー ===
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- === テナント分離 ===
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- === リレーション ===
    search_log_id UUID NOT NULL REFERENCES knowledge_search_logs(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id),

    -- === フィードバック内容 ===
    feedback_type VARCHAR(20) NOT NULL,             -- 'helpful', 'not_helpful', 'wrong', 'incomplete', 'outdated'
    -- 'helpful': 役に立った
    -- 'not_helpful': 役に立たなかった
    -- 'wrong': 間違っている
    -- 'incomplete': 情報が不完全
    -- 'outdated': 情報が古い

    rating INT,                                     -- 1-5のスコア（オプション）
    comment TEXT,                                   -- 自由記述コメント

    -- === 対象チャンク（どのチャンクに対するフィードバックか） ===
    target_chunk_ids UUID[],                        -- フィードバック対象のchunk_id配列

    -- === 改善提案 ===
    suggested_answer TEXT,                          -- ユーザーが提案する正しい回答
    suggested_source TEXT,                          -- ユーザーが提案する正しい情報源

    -- === 処理状態 ===
    status VARCHAR(50) DEFAULT 'pending',           -- 'pending', 'reviewed', 'resolved', 'ignored'
    reviewed_at TIMESTAMPTZ,
    reviewed_by UUID REFERENCES users(id),
    resolution_note TEXT,                           -- 対応内容のメモ

    -- === 監査情報 ===
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- === 制約 ===
    CONSTRAINT valid_feedback_type CHECK (feedback_type IN ('helpful', 'not_helpful', 'wrong', 'incomplete', 'outdated')),
    CONSTRAINT valid_rating CHECK (rating IS NULL OR (rating >= 1 AND rating <= 5)),
    CONSTRAINT valid_status CHECK (status IN ('pending', 'reviewed', 'resolved', 'ignored'))
);

-- インデックス
CREATE INDEX idx_feedback_org ON knowledge_feedback(organization_id);
CREATE INDEX idx_feedback_search ON knowledge_feedback(search_log_id);
CREATE INDEX idx_feedback_user ON knowledge_feedback(user_id);
CREATE INDEX idx_feedback_type ON knowledge_feedback(feedback_type);
CREATE INDEX idx_feedback_status ON knowledge_feedback(status) WHERE status = 'pending';
CREATE INDEX idx_feedback_created ON knowledge_feedback(created_at DESC);

-- コメント
COMMENT ON TABLE knowledge_feedback IS 'ナレッジ検索に対するユーザーフィードバック';
COMMENT ON COLUMN knowledge_feedback.feedback_type IS 'helpful:役立った, not_helpful:役立たず, wrong:間違い, incomplete:不完全, outdated:古い';
COMMENT ON COLUMN knowledge_feedback.target_chunk_ids IS 'フィードバック対象のchunk_id配列。特定のチャンクへのフィードバックに使用';
```

**フィードバックの種類と対応:**

| フィードバック | 意味 | システムの対応 |
|--------------|------|--------------|
| helpful | 役に立った | チャンクのスコアを上げる |
| not_helpful | 役に立たなかった | レビュー対象としてマーク |
| wrong | 間違っている | 管理者に即通知、ドキュメント確認 |
| incomplete | 情報が不完全 | ドキュメント更新を検討 |
| outdated | 情報が古い | ドキュメント更新を検討 |

---

### 3.5 knowledge_search_logs テーブル

**目的:** ナレッジ検索のログを記録し、検索品質の評価に使用

**テーブル定義:**

```sql
-- ナレッジ検索ログテーブル
CREATE TABLE knowledge_search_logs (
    -- === 主キー ===
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- === テナント分離 ===
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- === ユーザー情報 ===
    user_id UUID NOT NULL REFERENCES users(id),
    user_department_id UUID REFERENCES departments(id),  -- 検索時のユーザー所属部署

    -- === 検索クエリ ===
    query TEXT NOT NULL,                            -- 検索クエリ
    query_embedding_model VARCHAR(100),             -- 使用したエンベディングモデル

    -- === フィルタ条件 ===
    filters JSONB,                                  -- 適用したフィルタ
    -- 例: {"category": ["A", "B"], "classification": ["internal"]}

    -- === 検索結果 ===
    result_count INT DEFAULT 0,                     -- ヒット件数
    result_chunk_ids UUID[],                        -- ヒットしたchunk_id配列
    result_scores FLOAT[],                          -- 各結果のスコア配列
    top_score FLOAT,                                -- 最高スコア
    average_score FLOAT,                            -- 平均スコア

    -- === 回答生成 ===
    answer_generated BOOLEAN DEFAULT FALSE,         -- 回答を生成したか
    answer TEXT,                                    -- 生成した回答
    answer_model VARCHAR(100),                      -- 使用したLLMモデル
    answer_tokens INT,                              -- 回答生成に使用したトークン数

    -- === 回答拒否（MVP要件#8） ===
    answer_refused BOOLEAN DEFAULT FALSE,           -- 回答を拒否したか
    refused_reason VARCHAR(100),                    -- 拒否理由
    -- 'no_results': 検索結果なし
    -- 'low_confidence': 信頼度が低い
    -- 'out_of_scope': スコープ外
    -- 'restricted_content': 機密情報

    -- === アクセス制御 ===
    accessible_classifications TEXT[],              -- ユーザーがアクセス可能な機密区分
    accessible_department_ids UUID[],               -- ユーザーがアクセス可能な部署
    filtered_by_access_control INT DEFAULT 0,       -- アクセス制御でフィルタされた件数

    -- === パフォーマンス ===
    search_time_ms INT,                             -- 検索処理時間（ミリ秒）
    embedding_time_ms INT,                          -- エンベディング生成時間
    answer_generation_time_ms INT,                  -- 回答生成時間
    total_time_ms INT,                              -- 総処理時間

    -- === 検索品質評価用 ===
    has_feedback BOOLEAN DEFAULT FALSE,             -- フィードバックがあるか
    feedback_type VARCHAR(20),                      -- 最新のフィードバックタイプ

    -- === 検索元 ===
    source VARCHAR(50) DEFAULT 'chatwork',          -- 'chatwork', 'web', 'api', 'admin'
    source_room_id VARCHAR(50),                     -- ChatWorkルームID等

    -- === 監査情報 ===
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- === 制約 ===
    CONSTRAINT valid_refused_reason CHECK (
        refused_reason IS NULL OR
        refused_reason IN ('no_results', 'low_confidence', 'out_of_scope', 'restricted_content')
    )
);

-- インデックス
CREATE INDEX idx_search_logs_org ON knowledge_search_logs(organization_id);
CREATE INDEX idx_search_logs_user ON knowledge_search_logs(user_id);
CREATE INDEX idx_search_logs_created ON knowledge_search_logs(created_at DESC);
CREATE INDEX idx_search_logs_refused ON knowledge_search_logs(answer_refused) WHERE answer_refused = TRUE;
CREATE INDEX idx_search_logs_no_feedback ON knowledge_search_logs(has_feedback) WHERE has_feedback = FALSE;
CREATE INDEX idx_search_logs_quality ON knowledge_search_logs(organization_id, created_at DESC, top_score);

-- 週次レポート用インデックス
CREATE INDEX idx_search_logs_weekly ON knowledge_search_logs(organization_id, DATE(created_at));

-- コメント
COMMENT ON TABLE knowledge_search_logs IS 'ナレッジ検索のログ。検索品質評価とフィードバック紐付けに使用';
COMMENT ON COLUMN knowledge_search_logs.filtered_by_access_control IS 'アクセス制御によりフィルタされた結果数。多い場合は権限設定の見直しが必要';
COMMENT ON COLUMN knowledge_search_logs.refused_reason IS '回答拒否理由。品質改善の分析に使用';
```

**検索品質メトリクス（MVP要件#9）:**

```sql
-- 週次検索品質レポートの例
WITH weekly_stats AS (
    SELECT
        DATE_TRUNC('week', created_at) AS week,
        COUNT(*) AS total_searches,
        COUNT(*) FILTER (WHERE answer_refused = TRUE) AS refused_count,
        COUNT(*) FILTER (WHERE result_count = 0) AS no_results_count,
        COUNT(*) FILTER (WHERE has_feedback = TRUE AND feedback_type = 'helpful') AS helpful_count,
        COUNT(*) FILTER (WHERE has_feedback = TRUE AND feedback_type IN ('wrong', 'not_helpful')) AS negative_count,
        AVG(top_score) AS avg_top_score,
        AVG(search_time_ms) AS avg_search_time_ms
    FROM knowledge_search_logs
    WHERE organization_id = $1
      AND created_at >= NOW() - INTERVAL '4 weeks'
    GROUP BY DATE_TRUNC('week', created_at)
)
SELECT
    week,
    total_searches,
    refused_count,
    ROUND(refused_count * 100.0 / NULLIF(total_searches, 0), 1) AS refused_rate,
    no_results_count,
    helpful_count,
    negative_count,
    ROUND(helpful_count * 100.0 / NULLIF(helpful_count + negative_count, 0), 1) AS satisfaction_rate,
    ROUND(avg_top_score, 3) AS avg_top_score,
    ROUND(avg_search_time_ms) AS avg_search_time_ms
FROM weekly_stats
ORDER BY week DESC;
```

---

### 3.6 ER図

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              Phase 3 ナレッジ系 ER図                                      │
└─────────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────┐
│    organizations    │◀──────────────────────────────────────────────────────────────────┐
│   (テナント管理)     │                                                                   │
├─────────────────────┤                                                                   │
│ id (PK)             │                                                                   │
│ name                │                                                                   │
│ ...                 │                                                                   │
└─────────────────────┘                                                                   │
         │                                                                                │
         │ 1:N                                                                            │
         ▼                                                                                │
┌─────────────────────┐          ┌─────────────────────┐          ┌─────────────────────┐ │
│     documents       │ 1:N      │  document_versions  │ 1:N      │   document_chunks   │ │
│   (ドキュメント)     │─────────▶│   (バージョン)       │─────────▶│    (チャンク)        │ │
├─────────────────────┤          ├─────────────────────┤          ├─────────────────────┤ │
│ id (PK)             │          │ id (PK)             │          │ id (PK)             │ │
│ organization_id(FK) │          │ organization_id(FK) │──────────│ organization_id(FK) │─┘
│ department_id (FK)──│───────┐  │ document_id (FK)    │          │ document_id (FK)    │
│ owner_user_id (FK)  │       │  │ version_number      │          │ document_version_id │
│ title               │       │  │ file_path           │          │ pinecone_id         │◀─── Pinecone連携
│ category            │       │  │ is_latest           │          │ pinecone_namespace  │
│ classification      │       │  │ ...                 │          │ content             │
│ processing_status   │       │  └─────────────────────┘          │ page_number         │
│ current_version     │       │                                   │ section_title       │
│ ...                 │       │                                   │ section_hierarchy   │
└─────────────────────┘       │                                   │ classification      │
         │                    │                                   │ is_indexed          │
         │                    │                                   │ ...                 │
         │                    │                                   └─────────────────────┘
         │                    │                                            │
         │                    │                                            │ N:1
         │                    ▼                                            │
         │          ┌─────────────────────┐                                │
         │          │    departments      │                                │
         │          │     (部署)           │◀───────────────────────────────┘
         │          ├─────────────────────┤        (Phase 3.5連携)
         │          │ id (PK)             │
         │          │ organization_id(FK) │
         │          │ name                │
         │          │ path (LTREE)        │
         │          │ ...                 │
         │          └─────────────────────┘
         │
         │
         ▼
┌─────────────────────┐          ┌─────────────────────┐
│knowledge_search_logs│ 1:N      │  knowledge_feedback │
│   (検索ログ)         │─────────▶│   (フィードバック)    │
├─────────────────────┤          ├─────────────────────┤
│ id (PK)             │          │ id (PK)             │
│ organization_id(FK) │          │ organization_id(FK) │
│ user_id (FK)        │          │ search_log_id (FK)  │
│ query               │          │ user_id (FK)        │
│ result_chunk_ids    │──────────│ feedback_type       │
│ answer              │          │ rating              │
│ answer_refused      │          │ comment             │
│ refused_reason      │          │ target_chunk_ids    │──────── document_chunksを参照
│ search_time_ms      │          │ status              │
│ has_feedback        │◀─────────│ ...                 │
│ ...                 │          └─────────────────────┘
└─────────────────────┘
         │
         │ N:1
         ▼
┌─────────────────────┐
│       users         │
│     (ユーザー)       │
├─────────────────────┤
│ id (PK)             │
│ organization_id(FK) │
│ name                │
│ ...                 │
└─────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              Pinecone連携イメージ                                        │
└─────────────────────────────────────────────────────────────────────────────────────────┘

PostgreSQL (document_chunks)                    Pinecone (ベクターDB)
┌─────────────────────────────┐                ┌─────────────────────────────┐
│ id: chunk_uuid_001          │                │ Namespace: org_soulsyncs    │
│ pinecone_id: org_ss_doc1_v1 │───────────────▶│ ┌─────────────────────────┐ │
│ content: "経費精算は..."     │                │ │ ID: org_ss_doc1_v1_c0   │ │
│ page_number: 5              │                │ │ Vector: [0.1, 0.3, ...]  │ │
│ section_title: "2.3 手順"   │                │ │ Metadata:               │ │
│ ...                         │                │ │   document_id: doc1     │ │
└─────────────────────────────┘                │ │   category: "B"         │ │
                                               │ │   classification: "int" │ │
                                               │ │   department_id: null   │ │
                                               │ │   page: 5               │ │
                                               │ └─────────────────────────┘ │
                                               └─────────────────────────────┘
```

---

## 4. Pinecone統合設計

### 4.1 Pineconeインデックス設計

**インデックス設定:**

```yaml
# Pinecone Index Configuration
index_name: soulkun-knowledge
metric: cosine
dimension: 1536  # text-embedding-3-small
pods: 1  # MVP時点
replicas: 1  # 本番は2以上推奨
pod_type: p1.x1  # または s1.x1（コスト重視）
```

**MVP時点の構成:**

| 項目 | 設定値 | 備考 |
|------|--------|------|
| インデックス名 | soulkun-knowledge | 全テナント共通 |
| メトリクス | cosine | 類似度計算 |
| 次元数 | 1536 | text-embedding-3-small |
| Namespace | org_{organization_id} | テナント分離 |

### 4.2 Metadata設計

**Pineconeに保存するMetadata:**

```python
# Pinecone Vector Metadata Schema
{
    # === 必須フィールド ===
    "organization_id": str,          # テナントID（フィルタ必須）
    "document_id": str,              # ドキュメントID
    "document_version": int,         # バージョン番号
    "chunk_index": int,              # チャンクインデックス

    # === 機密区分・アクセス制御 ===
    "category": str,                 # 'A', 'B', 'C', 'D', 'E', 'F'
    "classification": str,           # 'public', 'internal', 'confidential', 'restricted'
    "department_id": str | None,     # 部署ID（confidentialの場合）

    # === 引用情報（MVP要件#7） ===
    "document_title": str,           # ドキュメントタイトル
    "page_number": int | None,       # ページ番号
    "section_title": str | None,     # セクションタイトル

    # === 検索補助 ===
    "file_type": str,                # 'pdf', 'docx', etc.
    "chunk_type": str,               # 'text', 'table', 'list', 'code'
    "language": str,                 # 'ja', 'en'

    # === 時間情報 ===
    "created_at": str,               # ISO8601形式
    "updated_at": str,               # ISO8601形式

    # === フラグ ===
    "is_active": bool,               # 有効フラグ
    "requires_verification": bool    # 「管理部に確認」フラグ
}
```

**Metadataサイズ制限:**
- Pineconeの制限: 40KB/ベクター
- 推奨サイズ: 10KB以下（安全マージン）

### 4.3 Namespace設計

**Namespace戦略:**

```
┌─────────────────────────────────────────────────────────────────┐
│                      Pinecone Index                              │
│                    (soulkun-knowledge)                           │
│                                                                  │
│  ┌─────────────────────┐  ┌─────────────────────┐              │
│  │ Namespace:           │  │ Namespace:           │              │
│  │ org_soulsyncs        │  │ org_customer_a       │              │
│  │                      │  │                      │              │
│  │ ├─ doc1_v1_chunk0   │  │ ├─ doc10_v1_chunk0  │              │
│  │ ├─ doc1_v1_chunk1   │  │ ├─ doc10_v1_chunk1  │              │
│  │ ├─ doc2_v1_chunk0   │  │ └─ doc11_v1_chunk0  │              │
│  │ └─ doc3_v2_chunk0   │  │                      │              │
│  │                      │  │                      │              │
│  └─────────────────────┘  └─────────────────────┘              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Namespaceの命名規則:**

```python
def get_pinecone_namespace(organization_id: str) -> str:
    """Pinecone namespaceを生成"""
    return f"org_{organization_id}"

# 例:
# organization_id = "soulsyncs" → namespace = "org_soulsyncs"
# organization_id = "customer_abc123" → namespace = "org_customer_abc123"
```

**Namespaceの利点:**

| # | 利点 | 説明 |
|---|------|------|
| 1 | テナント分離 | 組織ごとにデータが完全分離 |
| 2 | クエリ高速化 | Namespace指定で検索対象を絞り込み |
| 3 | 管理容易性 | 組織ごとに削除・更新が可能 |
| 4 | コスト最適化 | 不要な組織のデータを効率的に削除 |

---

## 5. API設計

### 5.1 ドキュメント管理API

#### POST /api/v1/documents

**目的:** 新規ドキュメントの登録

**リクエスト:**

```http
POST /api/v1/documents
Authorization: Bearer {token}
Content-Type: multipart/form-data

--boundary
Content-Disposition: form-data; name="file"; filename="manual.pdf"
Content-Type: application/pdf

{binary file data}
--boundary
Content-Disposition: form-data; name="metadata"
Content-Type: application/json

{
  "title": "経費精算マニュアル",
  "description": "経費精算の手順を説明するマニュアル",
  "category": "B",
  "classification": "internal",
  "department_id": null,
  "tags": ["経費", "マニュアル", "総務"],
  "requires_human_verification": true,
  "disclaimer_text": "最新版は総務部に確認してください"
}
--boundary--
```

**レスポンス（成功時）:**

```json
{
  "status": "success",
  "document": {
    "id": "doc_abc123",
    "title": "経費精算マニュアル",
    "category": "B",
    "classification": "internal",
    "processing_status": "pending",
    "file_name": "manual.pdf",
    "file_size_bytes": 1048576,
    "created_at": "2026-01-19T10:00:00Z"
  },
  "message": "ドキュメントが登録されました。処理が完了するまでお待ちください。",
  "estimated_processing_time_seconds": 60
}
```

**レスポンス（エラー時）:**

```json
{
  "status": "error",
  "error": {
    "code": "DUPLICATE_FILE",
    "message": "同一のファイルがすでに登録されています",
    "details": {
      "existing_document_id": "doc_xyz789",
      "existing_document_title": "経費精算マニュアル（旧）"
    }
  }
}
```

---

#### GET /api/v1/documents

**目的:** ドキュメント一覧の取得

**リクエスト:**

```http
GET /api/v1/documents?category=B&classification=internal&status=completed&limit=20&offset=0
Authorization: Bearer {token}
```

**クエリパラメータ:**

| パラメータ | 型 | 必須 | 説明 | デフォルト |
|-----------|---|------|------|-----------|
| category | string | × | カテゴリフィルタ | なし |
| classification | string | × | 機密区分フィルタ | なし |
| status | string | × | 処理状態フィルタ | なし |
| is_active | boolean | × | 有効フラグ | true |
| search | string | × | タイトル検索 | なし |
| limit | integer | × | 取得件数 | 20 |
| offset | integer | × | オフセット | 0 |
| sort_by | string | × | ソート項目 | created_at |
| sort_order | string | × | ソート順 | desc |

**レスポンス:**

```json
{
  "documents": [
    {
      "id": "doc_abc123",
      "title": "経費精算マニュアル",
      "category": "B",
      "classification": "internal",
      "processing_status": "completed",
      "current_version": 2,
      "total_chunks": 45,
      "total_pages": 20,
      "search_count": 150,
      "feedback_positive_count": 42,
      "feedback_negative_count": 3,
      "created_at": "2026-01-10T10:00:00Z",
      "updated_at": "2026-01-15T14:30:00Z"
    }
  ],
  "pagination": {
    "total": 50,
    "limit": 20,
    "offset": 0,
    "has_more": true
  }
}
```

---

#### GET /api/v1/documents/{document_id}

**目的:** ドキュメント詳細の取得

**レスポンス:**

```json
{
  "document": {
    "id": "doc_abc123",
    "title": "経費精算マニュアル",
    "description": "経費精算の手順を説明するマニュアル",
    "category": "B",
    "classification": "internal",
    "department_id": null,
    "owner": {
      "user_id": "user_admin",
      "name": "管理者"
    },
    "file": {
      "name": "manual.pdf",
      "type": "pdf",
      "size_bytes": 1048576,
      "path": "gs://soulkun-docs/org_soulsyncs/manual.pdf"
    },
    "processing": {
      "status": "completed",
      "processed_at": "2026-01-10T10:05:00Z",
      "total_chunks": 45,
      "total_pages": 20,
      "total_tokens": 15000
    },
    "versions": [
      {
        "version_number": 2,
        "is_latest": true,
        "created_at": "2026-01-15T14:30:00Z",
        "change_summary": "2026年度の改定を反映"
      },
      {
        "version_number": 1,
        "is_latest": false,
        "created_at": "2026-01-10T10:00:00Z",
        "change_summary": "初版"
      }
    ],
    "statistics": {
      "search_count": 150,
      "feedback_positive_count": 42,
      "feedback_negative_count": 3,
      "satisfaction_rate": 93.3
    },
    "settings": {
      "is_active": true,
      "is_searchable": true,
      "requires_human_verification": true,
      "disclaimer_text": "最新版は総務部に確認してください"
    },
    "tags": ["経費", "マニュアル", "総務"],
    "created_at": "2026-01-10T10:00:00Z",
    "updated_at": "2026-01-15T14:30:00Z"
  }
}
```

---

#### PUT /api/v1/documents/{document_id}

**目的:** ドキュメントメタデータの更新

**リクエスト:**

```json
{
  "title": "経費精算マニュアル（2026年度版）",
  "classification": "internal",
  "tags": ["経費", "マニュアル", "総務", "2026"],
  "requires_human_verification": true
}
```

---

#### POST /api/v1/documents/{document_id}/versions

**目的:** 新しいバージョンのアップロード

**リクエスト:**

```http
POST /api/v1/documents/doc_abc123/versions
Authorization: Bearer {token}
Content-Type: multipart/form-data

--boundary
Content-Disposition: form-data; name="file"; filename="manual_v2.pdf"
Content-Type: application/pdf

{binary file data}
--boundary
Content-Disposition: form-data; name="metadata"
Content-Type: application/json

{
  "change_summary": "2026年度の改定を反映",
  "change_type": "major"
}
--boundary--
```

---

#### DELETE /api/v1/documents/{document_id}

**目的:** ドキュメントの論理削除（アーカイブ）

**レスポンス:**

```json
{
  "status": "success",
  "message": "ドキュメントがアーカイブされました",
  "document_id": "doc_abc123",
  "archived_at": "2026-01-19T15:00:00Z"
}
```

---

### 5.2 ドキュメント取り込みAPI

#### POST /api/v1/documents/{document_id}/process

**目的:** ドキュメントの処理（チャンク化、エンベディング、インデックス）を開始

**リクエスト:**

```json
{
  "options": {
    "force_reprocess": false,
    "chunk_size": 1000,
    "chunk_overlap": 200,
    "embedding_model": "text-embedding-3-small"
  }
}
```

**レスポンス:**

```json
{
  "status": "success",
  "job_id": "job_xyz789",
  "document_id": "doc_abc123",
  "processing_status": "processing",
  "estimated_completion_time": "2026-01-19T10:05:00Z",
  "webhook_url": "/api/v1/documents/doc_abc123/processing-status"
}
```

---

#### GET /api/v1/documents/{document_id}/processing-status

**目的:** 処理状態の確認

**レスポンス:**

```json
{
  "document_id": "doc_abc123",
  "processing_status": "embedding",
  "progress": {
    "current_step": "embedding",
    "total_steps": 4,
    "current_step_number": 3,
    "steps": [
      {"name": "upload", "status": "completed", "duration_ms": 1000},
      {"name": "chunking", "status": "completed", "duration_ms": 5000, "chunks_created": 45},
      {"name": "embedding", "status": "in_progress", "progress_percent": 60},
      {"name": "indexing", "status": "pending"}
    ]
  },
  "started_at": "2026-01-19T10:00:00Z",
  "estimated_completion": "2026-01-19T10:05:00Z"
}
```

---

### 5.3 ナレッジ検索API

#### POST /api/v1/knowledge/search

**目的:** ナレッジ検索（RAG検索）

**リクエスト:**

```json
{
  "query": "経費精算のやり方を教えて",
  "filters": {
    "category": ["A", "B", "F"],
    "classification": ["public", "internal"]
  },
  "options": {
    "top_k": 5,
    "min_score": 0.7,
    "include_answer": true,
    "include_sources": true
  }
}
```

**レスポンス（回答生成成功時）:**

```json
{
  "search_id": "search_abc123",
  "query": "経費精算のやり方を教えて",

  "answer": {
    "text": "経費精算は以下の手順で行います：\n\n1. 領収書を撮影してシステムにアップロード\n2. 経費区分を選択（交通費、交際費など）\n3. 金額と日付を入力\n4. 上長に承認申請\n5. 承認後、経理部で処理\n\n詳細は経費精算マニュアルをご確認ください。",
    "generated": true,
    "model": "gpt-4-turbo",
    "confidence": 0.92
  },

  "sources": [
    {
      "chunk_id": "org_ss_doc1_v1_c5",
      "document_id": "doc_abc123",
      "document_title": "経費精算マニュアル",
      "version": 2,
      "page_number": 5,
      "section_title": "2.3 経費精算の手順",
      "section_hierarchy": ["第2章 経費", "2.3 経費精算の手順"],
      "score": 0.92,
      "text": "経費精算は、まず領収書を撮影し..."
    },
    {
      "chunk_id": "org_ss_doc1_v1_c6",
      "document_id": "doc_abc123",
      "document_title": "経費精算マニュアル",
      "version": 2,
      "page_number": 6,
      "section_title": "2.4 承認フロー",
      "section_hierarchy": ["第2章 経費", "2.4 承認フロー"],
      "score": 0.85,
      "text": "経費の承認は上長が行います..."
    }
  ],

  "citation": "出典: 経費精算マニュアル p.5-6「2.3 経費精算の手順」「2.4 承認フロー」",

  "disclaimer": {
    "text": "この情報は2026年1月15日に更新されました。最新の情報は総務部にご確認ください。",
    "last_updated": "2026-01-15T14:30:00Z",
    "requires_verification": true
  },

  "answer_refused": false,

  "metadata": {
    "search_time_ms": 150,
    "embedding_time_ms": 50,
    "answer_time_ms": 1500,
    "total_time_ms": 1700,
    "results_before_filter": 12,
    "results_after_filter": 5,
    "filtered_by_access_control": 3
  }
}
```

**レスポンス（回答拒否時：MVP要件#8）:**

```json
{
  "search_id": "search_def456",
  "query": "来週の天気を教えて",

  "answer": null,

  "sources": [],

  "answer_refused": true,
  "refused_reason": "out_of_scope",
  "refused_message": "申し訳ありません。ご質問の内容はソウルくんのナレッジベースの範囲外のため、お答えできません。業務に関するご質問でしたら、もう少し具体的に教えていただけますか？",

  "suggestions": [
    "「経費精算の方法を教えて」のような業務に関する質問をお試しください",
    "「有給休暇の申請方法は？」のような社内手続きの質問もお答えできます"
  ],

  "metadata": {
    "search_time_ms": 100,
    "total_time_ms": 150,
    "results_before_filter": 0
  }
}
```

**回答拒否条件（MVP要件#8の詳細）:**

| 条件 | refused_reason | メッセージ例 |
|------|---------------|-------------|
| 検索結果が0件 | no_results | 関連する情報が見つかりませんでした |
| 最高スコアが0.5未満 | low_confidence | 確信を持ってお答えできる情報がありません |
| 質問がスコープ外 | out_of_scope | ナレッジベースの範囲外です |
| 機密情報のみヒット | restricted_content | アクセス権限がありません |

---

#### GET /api/v1/knowledge/search/{search_id}

**目的:** 検索結果の再取得

---

### 5.4 フィードバックAPI

#### POST /api/v1/knowledge/feedback

**目的:** 検索結果へのフィードバック送信

**リクエスト:**

```json
{
  "search_id": "search_abc123",
  "feedback_type": "helpful",
  "rating": 5,
  "comment": "わかりやすかったです",
  "target_chunk_ids": ["org_ss_doc1_v1_c5"]
}
```

**レスポンス:**

```json
{
  "status": "success",
  "feedback_id": "fb_xyz789",
  "message": "フィードバックありがとうございます！"
}
```

---

#### POST /api/v1/knowledge/feedback/wrong

**目的:** 「間違っている」フィードバック（詳細入力用）

**リクエスト:**

```json
{
  "search_id": "search_abc123",
  "feedback_type": "wrong",
  "target_chunk_ids": ["org_ss_doc1_v1_c5"],
  "comment": "経費精算の承認フローが変更されています",
  "suggested_answer": "2026年からは、10,000円未満の経費は上長承認不要になりました",
  "suggested_source": "2026年1月の社内通達"
}
```

---

#### GET /api/v1/knowledge/feedback/pending

**目的:** 未対応フィードバック一覧（管理者用）

**レスポンス:**

```json
{
  "feedback_items": [
    {
      "id": "fb_xyz789",
      "feedback_type": "wrong",
      "search_query": "経費精算のやり方",
      "user": {
        "id": "user_tanaka",
        "name": "田中太郎"
      },
      "comment": "経費精算の承認フローが変更されています",
      "target_document": {
        "id": "doc_abc123",
        "title": "経費精算マニュアル"
      },
      "created_at": "2026-01-19T10:00:00Z"
    }
  ],
  "pagination": {
    "total": 5,
    "pending_count": 3,
    "reviewed_count": 2
  }
}
```

---

### 5.5 検索品質評価API

#### GET /api/v1/knowledge/quality/report

**目的:** 検索品質レポートの取得（MVP要件#9）

**リクエスト:**

```http
GET /api/v1/knowledge/quality/report?period=weekly&start_date=2026-01-13&end_date=2026-01-19
Authorization: Bearer {token}
```

**レスポンス:**

```json
{
  "period": {
    "type": "weekly",
    "start_date": "2026-01-13",
    "end_date": "2026-01-19"
  },

  "summary": {
    "total_searches": 500,
    "unique_users": 45,
    "average_searches_per_user": 11.1
  },

  "quality_metrics": {
    "answer_rate": {
      "value": 85.0,
      "description": "回答を生成できた割合",
      "trend": "+2.5%"
    },
    "refusal_rate": {
      "value": 15.0,
      "breakdown": {
        "no_results": 8.0,
        "low_confidence": 4.0,
        "out_of_scope": 2.5,
        "restricted_content": 0.5
      }
    },
    "satisfaction_rate": {
      "value": 92.0,
      "description": "ポジティブフィードバック率",
      "trend": "+1.2%"
    },
    "average_score": {
      "value": 0.82,
      "description": "検索結果の平均スコア"
    },
    "average_response_time_ms": {
      "value": 1500,
      "breakdown": {
        "embedding": 50,
        "search": 100,
        "answer_generation": 1350
      }
    }
  },

  "problem_areas": {
    "no_results_queries": [
      {
        "query": "社用車の予約方法",
        "count": 12,
        "recommendation": "社用車予約に関するドキュメントの登録を検討"
      },
      {
        "query": "名刺の発注",
        "count": 8,
        "recommendation": "名刺発注マニュアルの登録を検討"
      }
    ],
    "low_score_queries": [
      {
        "query": "経費の立替",
        "average_score": 0.45,
        "count": 15,
        "recommendation": "経費マニュアルのチャンク分割を見直し"
      }
    ],
    "negative_feedback_documents": [
      {
        "document_id": "doc_xyz123",
        "document_title": "就業規則",
        "negative_feedback_count": 5,
        "issues": ["情報が古い", "わかりにくい"]
      }
    ]
  },

  "top_queries": [
    {"query": "経費精算", "count": 45, "satisfaction_rate": 95.0},
    {"query": "有給休暇", "count": 38, "satisfaction_rate": 88.0},
    {"query": "出張申請", "count": 25, "satisfaction_rate": 92.0}
  ],

  "recommendations": [
    {
      "priority": "high",
      "type": "add_document",
      "description": "社用車予約マニュアルの登録を推奨",
      "reason": "「社用車」に関する検索が12件あり、すべてヒットなし"
    },
    {
      "priority": "medium",
      "type": "update_document",
      "description": "就業規則の更新を推奨",
      "reason": "ネガティブフィードバックが5件あり、「情報が古い」という指摘"
    }
  ]
}
```

---

#### GET /api/v1/knowledge/quality/unanswered

**目的:** ヒットしなかった質問一覧

**レスポンス:**

```json
{
  "unanswered_queries": [
    {
      "query": "社用車の予約方法",
      "count": 12,
      "users": ["user_a", "user_b", "user_c"],
      "first_searched_at": "2026-01-14T09:00:00Z",
      "last_searched_at": "2026-01-19T14:30:00Z"
    }
  ],
  "total": 15,
  "period": "last_7_days"
}
```

---

## 6. 処理フロー設計

### 6.1 ドキュメント取り込みフロー

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                         ドキュメント取り込みフロー                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘

[ユーザー] ─────▶ [API Gateway] ─────▶ [Document Service] ─────▶ [Cloud Storage]
                      │                      │
                      │                      ▼
                      │              ┌───────────────────┐
                      │              │ 1. バリデーション   │
                      │              │ - ファイル形式     │
                      │              │ - サイズ制限       │
                      │              │ - 重複チェック     │
                      │              └─────────┬─────────┘
                      │                        │
                      │                        ▼
                      │              ┌───────────────────┐
                      │              │ 2. DBレコード作成  │
                      │              │ - documents       │
                      │              │ - document_versions│
                      │              │ status: pending   │
                      │              └─────────┬─────────┘
                      │                        │
                      ▼                        ▼
              [Response to User]     [Cloud Tasks Queue]
              "処理を開始しました"            │
                                              │
                      ┌───────────────────────┘
                      │
                      ▼
         ┌────────────────────────┐
         │ 3. テキスト抽出        │
         │ (Background Worker)    │
         │                        │
         │ PDF → PyMuPDF         │
         │ DOCX → python-docx    │
         │ TXT/MD → そのまま     │
         └───────────┬────────────┘
                     │
                     ▼
         ┌────────────────────────┐
         │ 4. チャンク分割        │
         │                        │
         │ - セマンティック分割   │
         │ - 見出しベース         │
         │ - サイズ: 1000文字     │
         │ - オーバーラップ: 200  │
         │                        │
         │ status: chunking       │
         └───────────┬────────────┘
                     │
                     ▼
         ┌────────────────────────┐
         │ 5. DBにチャンク保存    │
         │                        │
         │ document_chunks        │
         │ - content              │
         │ - page_number          │
         │ - section_title        │
         │ - section_hierarchy    │
         └───────────┬────────────┘
                     │
                     ▼
         ┌────────────────────────┐
         │ 6. エンベディング生成  │
         │                        │
         │ OpenAI API             │
         │ text-embedding-3-small │
         │ バッチ処理（100件ずつ）│
         │                        │
         │ status: embedding      │
         └───────────┬────────────┘
                     │
                     ▼
         ┌────────────────────────┐
         │ 7. Pineconeにアップ    │
         │                        │
         │ - namespace設定        │
         │ - metadata付与         │
         │ - バッチupsert         │
         │                        │
         │ status: indexing       │
         └───────────┬────────────┘
                     │
                     ▼
         ┌────────────────────────┐
         │ 8. 完了処理            │
         │                        │
         │ - status: completed    │
         │ - 統計情報更新         │
         │ - Webhook通知（任意）  │
         └────────────────────────┘
```

**チャンク分割戦略:**

```python
from langchain.text_splitter import RecursiveCharacterTextSplitter

def create_chunks(
    text: str,
    metadata: dict,
    chunk_size: int = 1000,
    chunk_overlap: int = 200
) -> list[dict]:
    """
    ドキュメントをチャンクに分割

    戦略:
    1. 見出しを検出して構造を把握
    2. 見出しを跨がないように分割
    3. 文の途中で切らない
    4. オーバーラップで文脈を保持
    """

    # セマンティックな区切りを優先
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=[
            "\n## ",      # Markdown H2
            "\n### ",     # Markdown H3
            "\n#### ",    # Markdown H4
            "\n\n",       # 段落
            "\n",         # 改行
            "。",         # 日本語文末
            ".",          # 英語文末
            " ",          # スペース
            ""            # 最後の手段
        ]
    )

    chunks = splitter.split_text(text)

    return [
        {
            "content": chunk,
            "chunk_index": i,
            "char_count": len(chunk),
            "metadata": metadata
        }
        for i, chunk in enumerate(chunks)
    ]
```

---

### 6.2 RAG検索フロー

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              RAG検索フロー                                               │
└─────────────────────────────────────────────────────────────────────────────────────────┘

[ユーザー: 「経費精算のやり方を教えて」]
                │
                ▼
┌───────────────────────────────────────┐
│ 1. リクエスト受信                      │
│    - ユーザー認証                      │
│    - リクエストバリデーション           │
└─────────────────┬─────────────────────┘
                  │
                  ▼
┌───────────────────────────────────────┐
│ 2. ユーザーのアクセス権限を計算        │
│                                        │
│ accessible_depts = await              │
│   get_user_accessible_departments(user)│
│                                        │
│ accessible_classifications = [         │
│   'public', 'internal'                 │
│   + ('confidential' if dept_match)     │
│ ]                                      │
│                                        │
│ ★ Phase 3.5連携ポイント               │
└─────────────────┬─────────────────────┘
                  │
                  ▼
┌───────────────────────────────────────┐
│ 3. クエリのエンベディング生成          │
│                                        │
│ query_embedding = await openai.embed(  │
│   text=query,                          │
│   model="text-embedding-3-small"       │
│ )                                      │
│                                        │
│ ⏱️ ~50ms                               │
└─────────────────┬─────────────────────┘
                  │
                  ▼
┌───────────────────────────────────────┐
│ 4. Pinecone検索フィルタ構築           │
│                                        │
│ filter = {                             │
│   "$and": [                            │
│     {"category": {"$in": ["A","B","F"]}}│
│     {"$or": [                          │
│       {"classification": "public"},    │
│       {"classification": "internal"},  │
│       {"classification":"confidential",│
│        "department_id":{"$in":depts}}  │
│     ]}                                 │
│   ]                                    │
│ }                                      │
└─────────────────┬─────────────────────┘
                  │
                  ▼
┌───────────────────────────────────────┐
│ 5. Pinecone検索実行                    │
│                                        │
│ results = await pinecone.query(        │
│   namespace=f"org_{org_id}",           │
│   vector=query_embedding,              │
│   filter=filter,                       │
│   top_k=10,                            │
│   include_metadata=True                │
│ )                                      │
│                                        │
│ ⏱️ ~100ms                              │
└─────────────────┬─────────────────────┘
                  │
                  ▼
┌───────────────────────────────────────┐
│ 6. 回答生成判定                        │
│                                        │
│ if len(results) == 0:                  │
│   return refuse("no_results")          │
│                                        │
│ if max_score < 0.5:                    │
│   return refuse("low_confidence")      │
│                                        │
│ ★ MVP要件#8: 回答拒否条件              │
└─────────────────┬─────────────────────┘
                  │
                  ▼
┌───────────────────────────────────────┐
│ 7. コンテキスト構築                    │
│                                        │
│ context = build_context(               │
│   chunks=results,                      │
│   include_citations=True               │
│ )                                      │
│                                        │
│ 例:                                    │
│ """                                    │
│ [出典: 経費精算マニュアル p.5]         │
│ 経費精算は、まず領収書を撮影し...     │
│                                        │
│ [出典: 経費精算マニュアル p.6]         │
│ 承認は上長が行います...               │
│ """                                    │
└─────────────────┬─────────────────────┘
                  │
                  ▼
┌───────────────────────────────────────┐
│ 8. 回答生成                            │
│                                        │
│ prompt = f"""                          │
│ 以下の情報源を参考に質問に回答してくだ│
│ さい。情報源にない内容は回答しないで  │
│ ください。                             │
│                                        │
│ 情報源:                                │
│ {context}                              │
│                                        │
│ 質問: {query}                          │
│ """                                    │
│                                        │
│ answer = await openai.chat(            │
│   model="gpt-4-turbo",                 │
│   messages=[{"role":"user","content":  │
│     prompt}]                           │
│ )                                      │
│                                        │
│ ⏱️ ~1500ms                             │
└─────────────────┬─────────────────────┘
                  │
                  ▼
┌───────────────────────────────────────┐
│ 9. 注意書き付与                        │
│                                        │
│ disclaimer = build_disclaimer(         │
│   documents=source_documents,          │
│   requires_verification=True           │
│ )                                      │
│                                        │
│ 例:                                    │
│ "この情報は2026-01-15に更新されました。│
│  最新の情報は総務部にご確認ください。" │
│                                        │
│ ★ MVP要件#4: 注意書き                  │
└─────────────────┬─────────────────────┘
                  │
                  ▼
┌───────────────────────────────────────┐
│ 10. 検索ログ記録                       │
│                                        │
│ await KnowledgeSearchLog.create(       │
│   query=query,                         │
│   result_chunk_ids=[...],              │
│   answer=answer,                       │
│   answer_refused=False,                │
│   search_time_ms=150,                  │
│   ...                                  │
│ )                                      │
│                                        │
│ ★ MVP要件#9: 検索品質評価用            │
└─────────────────┬─────────────────────┘
                  │
                  ▼
┌───────────────────────────────────────┐
│ 11. 監査ログ記録（必要時）             │
│                                        │
│ if any confidential in results:        │
│   await AuditLog.create(               │
│     action="view_confidential",        │
│     resource_type="knowledge",         │
│     ...                                │
│   )                                    │
│                                        │
│ ★ RAG設計原則#3: 監査ログ              │
└─────────────────┬─────────────────────┘
                  │
                  ▼
           [レスポンス返却]
```

**回答生成プロンプト:**

```python
ANSWER_GENERATION_PROMPT = """
あなたはソウルシンクスの社内AIアシスタント「ソウルくん」です。
以下の情報源を参考に、ユーザーの質問に回答してください。

## 回答ルール
1. 情報源にある内容のみを使って回答する
2. 情報源にない内容は「わかりません」と正直に伝える
3. 推測や一般論は使わない
4. 回答の最後に出典を明記する
5. 親しみやすく、でも正確に

## 情報源
{context}

## 質問
{query}

## 回答形式
- 簡潔に要点をまとめる
- 必要に応じて箇条書きを使う
- 出典は「（出典: ドキュメント名 p.X）」の形式で記載

---
回答:
"""
```

---

### 6.3 フィードバック処理フロー

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                           フィードバック処理フロー                                        │
└─────────────────────────────────────────────────────────────────────────────────────────┘

[ユーザー: フィードバック送信]
         │
         ▼
┌────────────────────────────────────┐
│ 1. フィードバック受信               │
│                                     │
│ - search_id の検証                  │
│ - feedback_type の検証              │
│ - rating/comment の検証             │
└───────────────┬─────────────────────┘
                │
                ▼
┌────────────────────────────────────┐
│ 2. knowledge_feedback に保存       │
│                                     │
│ INSERT INTO knowledge_feedback...   │
│ status: 'pending'                   │
└───────────────┬─────────────────────┘
                │
                ▼
┌────────────────────────────────────┐
│ 3. 関連レコードの更新               │
│                                     │
│ - knowledge_search_logs.has_feedback│
│   = TRUE                            │
│ - knowledge_search_logs.feedback_type│
│   = '{type}'                        │
└───────────────┬─────────────────────┘
                │
                ▼
┌────────────────────────────────────┐
│ 4. 統計情報の更新                   │
│                                     │
│ documents.feedback_positive_count   │
│ または                              │
│ documents.feedback_negative_count   │
│ をインクリメント                    │
└───────────────┬─────────────────────┘
                │
                ├──────────────────────────────┐
                │                              │
    [feedback_type == 'helpful']    [feedback_type in ('wrong', 'not_helpful')]
                │                              │
                ▼                              ▼
┌────────────────────────────┐  ┌────────────────────────────┐
│ 5a. ポジティブ処理          │  │ 5b. ネガティブ処理          │
│                             │  │                             │
│ - チャンクのスコア加算      │  │ - 管理者に通知              │
│   (search_hit_count++)      │  │ - レビュー対象としてマーク   │
│                             │  │                             │
│ [自動完了]                  │  │ [管理者レビューへ]          │
└────────────────────────────┘  └───────────────┬─────────────┘
                                                │
                                                ▼
                                ┌────────────────────────────┐
                                │ 6. 管理者レビュー           │
                                │                             │
                                │ - フィードバック内容確認    │
                                │ - ドキュメント更新検討      │
                                │ - status: 'reviewed'        │
                                │ - resolution_note: 対応内容 │
                                └───────────────┬─────────────┘
                                                │
                                                ▼
                                ┌────────────────────────────┐
                                │ 7. 対応完了                 │
                                │                             │
                                │ - status: 'resolved'        │
                                │ - 必要に応じてドキュメント  │
                                │   更新                      │
                                └────────────────────────────┘
```

---

## 7. Phase 3.5連携設計（組織階層）

### 7.1 Phase 3.5との依存関係

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        Phase 3 と Phase 3.5 の連携                                      │
└────────────────────────────────────────────────────────────────────────────────────────┘

Phase 3 (ナレッジ系)                         Phase 3.5 (組織階層)
┌─────────────────────────┐                 ┌─────────────────────────┐
│                         │                 │                         │
│ documents               │                 │ departments             │
│ ├─ department_id ───────┼────────────────▶│ ├─ id                   │
│ └─ classification       │                 │ ├─ path (LTREE)         │
│                         │                 │ └─ ...                  │
│ document_chunks         │                 │                         │
│ ├─ department_id ───────┼────────────────▶│ user_departments        │
│ └─ classification       │                 │ ├─ user_id              │
│                         │                 │ └─ department_id        │
│ Pinecone Metadata       │                 │                         │
│ └─ department_id ───────┼────────────────▶│ department_access_scopes│
│                         │                 │ └─ can_view_child_...   │
│                         │                 │                         │
│ RAG検索処理             │    呼び出し     │ compute_accessible_     │
│ └─ accessible_depts ◀───┼─────────────────│ departments()           │
│                         │                 │                         │
└─────────────────────────┘                 └─────────────────────────┘

【Phase 3だけで動作する最小構成】
- classification = 'public' または 'internal' のみ使用
- department_id = NULL
- アクセス制御は organization_id のみ

【Phase 3.5連携後の拡張】
- classification = 'confidential' が使用可能に
- department_id を設定して部署別アクセス制御
- compute_accessible_departments() による動的権限計算
```

### 7.2 Phase 3単独動作モード（MVP）

Phase 3.5が完成する前でも、Phase 3は単独で動作できるように設計。

```python
async def get_accessible_classifications(
    user: User,
    organization_id: UUID
) -> list[str]:
    """
    ユーザーがアクセス可能な機密区分を取得

    Phase 3単独モード（MVP）:
    - public, internal のみ
    - confidential, restricted は使用しない

    Phase 3.5連携後:
    - 組織階層に基づいてconfidentialも判定
    """

    # 基本: public と internal は全員アクセス可能
    classifications = ['public', 'internal']

    # Phase 3.5連携チェック（フラグで制御）
    if settings.ENABLE_DEPARTMENT_ACCESS_CONTROL:
        # Phase 3.5のcompute_accessible_departments()を使用
        accessible_depts = await compute_accessible_departments(
            user_id=user.id,
            organization_id=organization_id
        )

        if accessible_depts:
            classifications.append('confidential')

    # 管理者は restricted も可能
    if user.role == 'admin':
        classifications.append('restricted')

    return classifications
```

### 7.3 Pineconeフィルタの動的構築

```python
async def build_pinecone_filter(
    user: User,
    organization_id: UUID,
    request_filters: dict
) -> dict:
    """
    Pinecone検索フィルタを動的に構築

    Phase 3単独モード:
    - classification: public, internal のみ
    - department_id フィルタなし

    Phase 3.5連携後:
    - classification: confidential も含む
    - department_id でフィルタ
    """

    # カテゴリフィルタ
    category_filter = request_filters.get('category', ['A', 'B', 'F'])

    # アクセス可能な機密区分
    accessible_classifications = await get_accessible_classifications(
        user, organization_id
    )

    # 基本フィルタ
    filter_conditions = [
        {"category": {"$in": category_filter}},
    ]

    # 機密区分フィルタ
    classification_conditions = []

    for classification in accessible_classifications:
        if classification in ['public', 'internal']:
            # public/internal は department_id 不要
            classification_conditions.append({
                "classification": classification
            })

        elif classification == 'confidential':
            # confidential は department_id でフィルタ
            if settings.ENABLE_DEPARTMENT_ACCESS_CONTROL:
                accessible_depts = await compute_accessible_departments(
                    user_id=user.id,
                    organization_id=organization_id
                )
                classification_conditions.append({
                    "$and": [
                        {"classification": "confidential"},
                        {"department_id": {"$in": [str(d) for d in accessible_depts]}}
                    ]
                })

        elif classification == 'restricted':
            # restricted は管理者のみ
            classification_conditions.append({
                "classification": "restricted"
            })

    filter_conditions.append({"$or": classification_conditions})

    return {"$and": filter_conditions}
```

---

## 8. エラーハンドリング設計

### 8.1 エラーコード一覧

| コード | HTTPステータス | 説明 | 対処法 |
|--------|---------------|------|--------|
| DOC_001 | 400 | 無効なファイル形式 | サポート形式を確認 |
| DOC_002 | 400 | ファイルサイズ超過 | 50MB以下に圧縮 |
| DOC_003 | 409 | 重複ファイル | 既存ドキュメントを更新 |
| DOC_004 | 404 | ドキュメント未発見 | IDを確認 |
| DOC_005 | 422 | 処理失敗 | ファイル内容を確認 |
| SEARCH_001 | 400 | クエリが空 | クエリを入力 |
| SEARCH_002 | 400 | クエリが長すぎる | 500文字以内 |
| SEARCH_003 | 503 | Pinecone接続エラー | リトライ |
| SEARCH_004 | 503 | OpenAI接続エラー | リトライ |
| SEARCH_005 | 500 | 回答生成エラー | サポートに連絡 |
| FB_001 | 400 | 無効なフィードバック | タイプを確認 |
| FB_002 | 404 | 検索ログ未発見 | search_idを確認 |
| AUTH_001 | 401 | 認証エラー | トークンを確認 |
| AUTH_002 | 403 | 権限不足 | 管理者に連絡 |

### 8.2 エラーレスポンス形式

```json
{
  "status": "error",
  "error": {
    "code": "DOC_003",
    "message": "同一のファイルがすでに登録されています",
    "details": {
      "existing_document_id": "doc_xyz789",
      "existing_document_title": "経費精算マニュアル（旧）",
      "file_hash": "abc123..."
    },
    "help_url": "https://docs.soulsyncs.jp/errors/DOC_003"
  },
  "request_id": "req_abc123",
  "timestamp": "2026-01-19T10:00:00Z"
}
```

### 8.3 リトライ戦略

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10)
)
async def call_openai_embedding(text: str) -> list[float]:
    """
    OpenAI Embedding API呼び出し（リトライ付き）

    リトライ戦略:
    - 最大3回リトライ
    - 指数バックオフ（1秒, 2秒, 4秒...）
    - 最大10秒待機
    """
    response = await openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return response.data[0].embedding


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10)
)
async def pinecone_query(
    namespace: str,
    vector: list[float],
    filter: dict,
    top_k: int
) -> list:
    """
    Pinecone検索（リトライ付き）
    """
    return await pinecone_index.query(
        namespace=namespace,
        vector=vector,
        filter=filter,
        top_k=top_k,
        include_metadata=True
    )
```

---

## 9. テスト設計

### 9.1 テストカテゴリ

| カテゴリ | 対象 | カバレッジ目標 |
|---------|------|--------------|
| ユニットテスト | ビジネスロジック | 80%以上 |
| 統合テスト | API + DB | 70%以上 |
| E2Eテスト | 全体フロー | 主要シナリオ |

### 9.2 テストケース一覧

**ドキュメント管理:**

| # | テストケース | 期待結果 |
|---|-------------|---------|
| 1 | PDF登録（正常） | processing_status = pending |
| 2 | 重複ファイル登録 | エラー DOC_003 |
| 3 | 無効な形式（exe） | エラー DOC_001 |
| 4 | 50MB超過 | エラー DOC_002 |
| 5 | バージョン更新 | current_version インクリメント |

**ナレッジ検索:**

| # | テストケース | 期待結果 |
|---|-------------|---------|
| 1 | 通常検索 | 回答 + 出典 |
| 2 | 検索結果0件 | 回答拒否（no_results） |
| 3 | 低スコア | 回答拒否（low_confidence） |
| 4 | アクセス制御（internal） | 社員はアクセス可 |
| 5 | アクセス制御（confidential） | 該当部署のみアクセス可 |
| 6 | 注意書き付与 | disclaimer が含まれる |

**フィードバック:**

| # | テストケース | 期待結果 |
|---|-------------|---------|
| 1 | helpful送信 | 統計カウントアップ |
| 2 | wrong送信 | 管理者通知 |
| 3 | 無効なsearch_id | エラー FB_002 |

### 9.3 テストデータ

```python
# テスト用ドキュメント
TEST_DOCUMENTS = [
    {
        "title": "経費精算マニュアル",
        "category": "B",
        "classification": "internal",
        "content": "経費精算は以下の手順で行います..."
    },
    {
        "title": "MVV（ミッション・ビジョン・バリュー）",
        "category": "A",
        "classification": "public",
        "content": "私たちのミッションは..."
    },
    {
        "title": "営業部内部資料",
        "category": "B",
        "classification": "confidential",
        "department_id": "dept_sales",
        "content": "営業部の内部情報..."
    }
]

# テスト用検索クエリ
TEST_QUERIES = [
    {"query": "経費精算のやり方", "expected_hits": True},
    {"query": "会社のミッション", "expected_hits": True},
    {"query": "明日の天気", "expected_hits": False, "expected_refuse": "out_of_scope"},
]
```

---

## 10. マイグレーション計画

### 10.1 マイグレーションファイル

```sql
-- Migration: 001_create_phase3_knowledge_tables.sql
-- Date: 2026-01-19
-- Description: Phase 3 ナレッジ系テーブルの作成

BEGIN;

-- 1. documents テーブル
CREATE TABLE documents (
    -- (上記の定義)
);

-- 2. document_versions テーブル
CREATE TABLE document_versions (
    -- (上記の定義)
);

-- 3. document_chunks テーブル
CREATE TABLE document_chunks (
    -- (上記の定義)
);

-- 4. knowledge_search_logs テーブル
CREATE TABLE knowledge_search_logs (
    -- (上記の定義)
);

-- 5. knowledge_feedback テーブル
CREATE TABLE knowledge_feedback (
    -- (上記の定義)
);

-- インデックス作成
-- (上記の各テーブルのインデックス)

COMMIT;
```

### 10.2 Pineconeセットアップ

```python
# scripts/setup_pinecone.py

import pinecone

def setup_pinecone_index():
    """Pineconeインデックスのセットアップ"""

    # 接続
    pinecone.init(
        api_key=settings.PINECONE_API_KEY,
        environment=settings.PINECONE_ENVIRONMENT
    )

    # インデックス作成（存在しない場合）
    if "soulkun-knowledge" not in pinecone.list_indexes():
        pinecone.create_index(
            name="soulkun-knowledge",
            dimension=1536,
            metric="cosine",
            pod_type="p1.x1"
        )
        print("インデックス 'soulkun-knowledge' を作成しました")
    else:
        print("インデックス 'soulkun-knowledge' は既に存在します")

    # インデックス情報
    index = pinecone.Index("soulkun-knowledge")
    stats = index.describe_index_stats()
    print(f"インデックス統計: {stats}")

if __name__ == "__main__":
    setup_pinecone_index()
```

### 10.3 実行順序

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                           マイグレーション実行順序                                       │
└────────────────────────────────────────────────────────────────────────────────────────┘

[Step 1] データベースマイグレーション
         └─ 001_create_phase3_knowledge_tables.sql

[Step 2] Pineconeセットアップ
         └─ scripts/setup_pinecone.py

[Step 3] 環境変数設定
         └─ PINECONE_API_KEY, PINECONE_ENVIRONMENT, OPENAI_API_KEY

[Step 4] API デプロイ（Cloud Run）
         └─ api/app/api/v1/knowledge/

[Step 5] 動作確認
         └─ テストドキュメントの登録・検索

[Step 6] 初期データ投入
         └─ A（理念）、B（マニュアル）、F（サービス情報）のドキュメント
```

---

## 11. 実装チェックリスト

### 11.1 データベース

- [ ] documents テーブル作成
- [ ] document_versions テーブル作成
- [ ] document_chunks テーブル作成
- [ ] knowledge_search_logs テーブル作成
- [ ] knowledge_feedback テーブル作成
- [ ] インデックス作成
- [ ] マイグレーション実行

### 11.2 Pinecone

- [ ] インデックス作成（soulkun-knowledge）
- [ ] Namespace設計確認
- [ ] Metadata設計確認
- [ ] 接続テスト

### 11.3 API

- [ ] POST /api/v1/documents（ドキュメント登録）
- [ ] GET /api/v1/documents（一覧取得）
- [ ] GET /api/v1/documents/{id}（詳細取得）
- [ ] PUT /api/v1/documents/{id}（更新）
- [ ] DELETE /api/v1/documents/{id}（削除）
- [ ] POST /api/v1/documents/{id}/versions（バージョン追加）
- [ ] POST /api/v1/documents/{id}/process（処理開始）
- [ ] GET /api/v1/documents/{id}/processing-status（処理状態）
- [ ] POST /api/v1/knowledge/search（検索）
- [ ] POST /api/v1/knowledge/feedback（フィードバック）
- [ ] GET /api/v1/knowledge/quality/report（品質レポート）

### 11.4 処理ロジック

- [ ] テキスト抽出（PDF, DOCX, TXT, MD）
- [ ] チャンク分割
- [ ] エンベディング生成
- [ ] Pineconeインデックス
- [ ] RAG検索
- [ ] 回答生成
- [ ] 回答拒否判定
- [ ] 注意書き付与
- [ ] フィードバック処理

### 11.5 テスト

- [ ] ユニットテスト
- [ ] 統合テスト
- [ ] E2Eテスト
- [ ] 負荷テスト

### 11.6 MVP要件確認

- [ ] #1: ドキュメント取り込み（A, B, F）
- [ ] #2: 参照検索
- [ ] #3: 根拠提示
- [ ] #4: 注意書き
- [ ] #5: フィードバック
- [ ] #6: アクセス制御（2段階）
- [ ] #7: 引用粒度（chunk_id）
- [ ] #8: 回答拒否条件
- [ ] #9: 検索品質評価

---

**[📁 目次に戻る](00_README.md)**
