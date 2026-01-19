-- ================================================================
-- Phase 3 完全版マイグレーション: Cloud SQL（ソウルくん ナレッジ系）
-- ================================================================
-- 作成日: 2026-01-19
-- 作成者: Claude Code
-- バージョン: 1.0.0
--
-- このSQLはCloud SQLに接続して実行してください。
--
-- 接続方法:
--   gcloud sql connect soulkun-db --user=postgres
--
-- 注意事項:
--   1. 必ずバックアップを取ってから実行
--   2. STEP 1の事前確認を必ず実行
--   3. エラーが発生したらSTEP 9のロールバックを実行
--
-- 前提条件:
--   - organizations テーブルが存在すること
--   - users テーブルが存在すること
--   - departments テーブルは任意（Phase 3.5で作成。FK制約は後から追加可能）
--
-- Phase 3.5連携について:
--   - department_id カラムは FK 制約なしで作成（Phase 3.5が未デプロイでも動作）
--   - Phase 3.5 デプロイ後に ALTER TABLE で FK 制約を追加する（STEP 8A 参照）
--   - ENABLE_DEPARTMENT_ACCESS_CONTROL フラグで動作を切り替え
-- ================================================================

-- ================================================================
-- STEP 0: トランザクション開始
-- ================================================================
BEGIN;

-- ================================================================
-- STEP 1: 事前確認（必須）
-- ================================================================

-- 1-1. 現在のデータベースとユーザーを確認
SELECT current_database() as database, current_user as user, now() as executed_at;

-- 1-2. 必要なテーブルの存在確認
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('organizations', 'users', 'departments')
ORDER BY table_name;

-- 1-3. Phase 3テーブルが既に存在するか確認
SELECT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_name = 'documents'
      AND table_schema = 'public'
) as documents_exists;

-- ================================================================
-- STEP 2: documents テーブル作成
-- ================================================================

CREATE TABLE IF NOT EXISTS documents (
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
    -- 注意: department_id の FK 制約は Phase 3.5 デプロイ後に追加する（STEP 8A 参照）
    department_id UUID,                             -- 所属部署（confidentialの場合に使用）
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

    -- === Googleドライブ連携（06_phase3_google_drive_integration.md） ===
    google_drive_file_id VARCHAR(255),              -- GoogleドライブのファイルID
    google_drive_folder_path TEXT[],                -- フォルダパス配列
    google_drive_web_view_link TEXT,                -- Googleドライブでのファイル閲覧URL
    google_drive_last_modified TIMESTAMPTZ,         -- Googleドライブでの最終更新日時

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
    CONSTRAINT positive_version CHECK (current_version >= 1)
);

-- documents インデックス
CREATE INDEX IF NOT EXISTS idx_documents_org ON documents(organization_id);
CREATE INDEX IF NOT EXISTS idx_documents_category ON documents(organization_id, category);
CREATE INDEX IF NOT EXISTS idx_documents_classification ON documents(organization_id, classification);
CREATE INDEX IF NOT EXISTS idx_documents_department ON documents(department_id) WHERE department_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(processing_status);
CREATE INDEX IF NOT EXISTS idx_documents_active ON documents(organization_id, is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_documents_searchable ON documents(organization_id, is_searchable) WHERE is_searchable = TRUE;
CREATE INDEX IF NOT EXISTS idx_documents_created ON documents(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_tags ON documents USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_documents_metadata ON documents USING GIN(metadata);
CREATE INDEX IF NOT EXISTS idx_documents_file_hash ON documents(organization_id, file_hash) WHERE file_hash IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_drive_file_id ON documents(organization_id, google_drive_file_id) WHERE google_drive_file_id IS NOT NULL;

-- documents コメント
COMMENT ON TABLE documents IS 'ナレッジドキュメントのメタデータ管理テーブル';
COMMENT ON COLUMN documents.category IS 'A:理念, B:マニュアル, C:就業規則, D:テンプレート, E:顧客情報, F:サービス情報';
COMMENT ON COLUMN documents.classification IS 'public:公開, internal:社内, confidential:部門限定, restricted:経営陣のみ';
COMMENT ON COLUMN documents.file_hash IS 'SHA-256ハッシュ。同一ファイルの重複登録を防止';
COMMENT ON COLUMN documents.processing_status IS 'pending→processing→chunking→embedding→indexing→completed の順で遷移';
COMMENT ON COLUMN documents.google_drive_file_id IS 'GoogleドライブのファイルID。Googleドライブ連携時に使用';
COMMENT ON COLUMN documents.google_drive_folder_path IS 'Googleドライブのフォルダパス配列。権限決定に使用';

-- ================================================================
-- STEP 3: document_versions テーブル作成
-- ================================================================

CREATE TABLE IF NOT EXISTS document_versions (
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
    CONSTRAINT positive_version_num CHECK (version_number >= 1)
);

-- document_versions インデックス
CREATE INDEX IF NOT EXISTS idx_doc_versions_org ON document_versions(organization_id);
CREATE INDEX IF NOT EXISTS idx_doc_versions_doc ON document_versions(document_id);
CREATE INDEX IF NOT EXISTS idx_doc_versions_latest ON document_versions(document_id, is_latest) WHERE is_latest = TRUE;
CREATE INDEX IF NOT EXISTS idx_doc_versions_status ON document_versions(processing_status);

-- document_versions コメント
COMMENT ON TABLE document_versions IS 'ドキュメントのバージョン履歴。更新時に前バージョンを保持';
COMMENT ON COLUMN document_versions.is_latest IS '最新バージョンフラグ。1ドキュメントにつき1つだけTRUE';

-- ================================================================
-- STEP 4: document_chunks テーブル作成
-- ================================================================

CREATE TABLE IF NOT EXISTS document_chunks (
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
    -- 注意: department_id の FK 制約は Phase 3.5 デプロイ後に追加する（STEP 8A 参照）
    department_id UUID,                             -- チャンク固有の部署（NULL=ドキュメントから継承）

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

-- document_chunks インデックス
CREATE INDEX IF NOT EXISTS idx_chunks_org ON document_chunks(organization_id);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON document_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_version ON document_chunks(document_version_id);
CREATE INDEX IF NOT EXISTS idx_chunks_pinecone ON document_chunks(pinecone_id);
CREATE INDEX IF NOT EXISTS idx_chunks_page ON document_chunks(document_id, page_number);
CREATE INDEX IF NOT EXISTS idx_chunks_indexed ON document_chunks(is_indexed) WHERE is_indexed = TRUE;
CREATE INDEX IF NOT EXISTS idx_chunks_active ON document_chunks(is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_chunks_search_stats ON document_chunks(search_hit_count DESC);

-- document_chunks コメント
COMMENT ON TABLE document_chunks IS 'ドキュメントを分割したチャンク。Pineconeベクターと1対1で対応';
COMMENT ON COLUMN document_chunks.pinecone_id IS 'Pineconeベクター ID。フォーマット: {org}_{doc}_{ver}_{idx}';
COMMENT ON COLUMN document_chunks.section_hierarchy IS 'セクション階層。例: ["第1章", "1.1 概要"]';
COMMENT ON COLUMN document_chunks.classification IS 'チャンク固有の機密区分。NULLの場合はドキュメントから継承';

-- ================================================================
-- STEP 5: knowledge_search_logs テーブル作成
-- ================================================================

CREATE TABLE IF NOT EXISTS knowledge_search_logs (
    -- === 主キー ===
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- === テナント分離 ===
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- === ユーザー情報 ===
    user_id UUID NOT NULL REFERENCES users(id),
    -- 注意: user_department_id の FK 制約は Phase 3.5 デプロイ後に追加する（STEP 8A 参照）
    user_department_id UUID,                        -- 検索時のユーザー所属部署

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

-- knowledge_search_logs インデックス
CREATE INDEX IF NOT EXISTS idx_search_logs_org ON knowledge_search_logs(organization_id);
CREATE INDEX IF NOT EXISTS idx_search_logs_user ON knowledge_search_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_search_logs_created ON knowledge_search_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_search_logs_refused ON knowledge_search_logs(answer_refused) WHERE answer_refused = TRUE;
CREATE INDEX IF NOT EXISTS idx_search_logs_no_feedback ON knowledge_search_logs(has_feedback) WHERE has_feedback = FALSE;
CREATE INDEX IF NOT EXISTS idx_search_logs_quality ON knowledge_search_logs(organization_id, created_at DESC, top_score);
CREATE INDEX IF NOT EXISTS idx_search_logs_weekly ON knowledge_search_logs(organization_id, DATE(created_at));

-- knowledge_search_logs コメント
COMMENT ON TABLE knowledge_search_logs IS 'ナレッジ検索のログ。検索品質評価とフィードバック紐付けに使用';
COMMENT ON COLUMN knowledge_search_logs.filtered_by_access_control IS 'アクセス制御によりフィルタされた結果数。多い場合は権限設定の見直しが必要';
COMMENT ON COLUMN knowledge_search_logs.refused_reason IS '回答拒否理由。品質改善の分析に使用';

-- ================================================================
-- STEP 6: knowledge_feedback テーブル作成
-- ================================================================

CREATE TABLE IF NOT EXISTS knowledge_feedback (
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
    CONSTRAINT valid_feedback_status CHECK (status IN ('pending', 'reviewed', 'resolved', 'ignored'))
);

-- knowledge_feedback インデックス
CREATE INDEX IF NOT EXISTS idx_feedback_org ON knowledge_feedback(organization_id);
CREATE INDEX IF NOT EXISTS idx_feedback_search ON knowledge_feedback(search_log_id);
CREATE INDEX IF NOT EXISTS idx_feedback_user ON knowledge_feedback(user_id);
CREATE INDEX IF NOT EXISTS idx_feedback_type ON knowledge_feedback(feedback_type);
CREATE INDEX IF NOT EXISTS idx_feedback_status ON knowledge_feedback(status) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_feedback_created ON knowledge_feedback(created_at DESC);

-- knowledge_feedback コメント
COMMENT ON TABLE knowledge_feedback IS 'ナレッジ検索に対するユーザーフィードバック';
COMMENT ON COLUMN knowledge_feedback.feedback_type IS 'helpful:役立った, not_helpful:役立たず, wrong:間違い, incomplete:不完全, outdated:古い';
COMMENT ON COLUMN knowledge_feedback.target_chunk_ids IS 'フィードバック対象のchunk_id配列。特定のチャンクへのフィードバックに使用';

-- ================================================================
-- STEP 7: google_drive_sync_logs テーブル作成（Googleドライブ連携）
-- ================================================================

CREATE TABLE IF NOT EXISTS google_drive_sync_logs (
    -- === 主キー ===
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- === テナント分離 ===
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- === 同期情報 ===
    sync_id VARCHAR(100) UNIQUE NOT NULL,           -- sync_20260119_100000_abc123
    sync_type VARCHAR(50) NOT NULL,                 -- 'scheduled', 'manual', 'initial'

    -- === 処理統計 ===
    files_checked INT DEFAULT 0,                    -- チェックしたファイル数
    files_added INT DEFAULT 0,                      -- 追加したファイル数
    files_updated INT DEFAULT 0,                    -- 更新したファイル数
    files_deleted INT DEFAULT 0,                    -- 削除したファイル数
    files_skipped INT DEFAULT 0,                    -- スキップしたファイル数
    files_failed INT DEFAULT 0,                     -- 失敗したファイル数

    -- === ステータス ===
    status VARCHAR(50) NOT NULL DEFAULT 'in_progress',
    -- 'in_progress': 実行中
    -- 'completed': 完了
    -- 'completed_with_errors': エラーありで完了
    -- 'failed': 失敗

    -- === エラー情報 ===
    error_code VARCHAR(100),
    error_message TEXT,
    error_details JSONB,
    failed_files JSONB,                             -- 失敗したファイルのリスト

    -- === タイミング ===
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    duration_ms INT,

    -- === Google Drive API情報 ===
    start_page_token VARCHAR(255),                  -- 同期開始時のページトークン
    new_page_token VARCHAR(255),                    -- 同期完了後のページトークン
    root_folder_id VARCHAR(255),                    -- 監視対象のルートフォルダID

    -- === メタデータ ===
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- === 制約 ===
    CONSTRAINT valid_sync_status CHECK (
        status IN ('in_progress', 'completed', 'completed_with_errors', 'failed')
    )
);

-- google_drive_sync_logs インデックス
CREATE INDEX IF NOT EXISTS idx_drive_sync_logs_org ON google_drive_sync_logs(organization_id);
CREATE INDEX IF NOT EXISTS idx_drive_sync_logs_status ON google_drive_sync_logs(status);
CREATE INDEX IF NOT EXISTS idx_drive_sync_logs_started ON google_drive_sync_logs(started_at DESC);

-- google_drive_sync_logs コメント
COMMENT ON TABLE google_drive_sync_logs IS 'Googleドライブ同期ジョブの実行ログ。5分ごとの定期実行の記録と、エラー追跡に使用';
COMMENT ON COLUMN google_drive_sync_logs.start_page_token IS 'Google Drive API Changes のページトークン。前回の同期以降の変更を取得するために使用';

-- ================================================================
-- STEP 8: google_drive_sync_state テーブル作成（Googleドライブ連携）
-- ================================================================

CREATE TABLE IF NOT EXISTS google_drive_sync_state (
    -- === 主キー ===
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- === テナント分離 ===
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- === 同期状態 ===
    root_folder_id VARCHAR(255) NOT NULL,           -- 監視対象のルートフォルダID
    page_token VARCHAR(255) NOT NULL,               -- 次回同期開始時のページトークン
    last_sync_at TIMESTAMPTZ,                       -- 最後に同期した日時
    last_sync_id UUID REFERENCES google_drive_sync_logs(id),

    -- === メタデータ ===
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- === 制約 ===
    CONSTRAINT unique_org_folder UNIQUE (organization_id, root_folder_id)
);

-- google_drive_sync_state コメント
COMMENT ON TABLE google_drive_sync_state IS 'Googleドライブ同期の状態管理テーブル。組織×フォルダごとにページトークンを保持し、差分同期を実現';
COMMENT ON COLUMN google_drive_sync_state.page_token IS 'Google Drive API Changes のページトークン。このトークン以降の変更を次回同期で取得する';

-- ================================================================
-- STEP 8A: Phase 3.5連携用 FK制約追加（オプション）
-- ================================================================
-- 注意: このステップは Phase 3.5 デプロイ後に別途実行してください
-- departments テーブルが存在する状態で実行する必要があります
--
-- 実行方法:
--   1. Phase 3.5 のマイグレーションを先に実行
--   2. departments テーブルの存在を確認
--   3. 以下のコメントを外して実行
-- ================================================================

/*
-- Phase 3.5 連携用 FK 制約を追加（departments テーブル存在確認後に実行）
DO $$
BEGIN
    -- departments テーブルが存在するか確認
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'departments' AND table_schema = 'public'
    ) THEN
        -- documents.department_id に FK 制約を追加
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.table_constraints
            WHERE constraint_name = 'fk_documents_department' AND table_name = 'documents'
        ) THEN
            ALTER TABLE documents
            ADD CONSTRAINT fk_documents_department
            FOREIGN KEY (department_id) REFERENCES departments(id);
            RAISE NOTICE 'Added FK constraint: documents.department_id -> departments.id';
        END IF;

        -- document_chunks.department_id に FK 制約を追加
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.table_constraints
            WHERE constraint_name = 'fk_document_chunks_department' AND table_name = 'document_chunks'
        ) THEN
            ALTER TABLE document_chunks
            ADD CONSTRAINT fk_document_chunks_department
            FOREIGN KEY (department_id) REFERENCES departments(id);
            RAISE NOTICE 'Added FK constraint: document_chunks.department_id -> departments.id';
        END IF;

        -- knowledge_search_logs.user_department_id に FK 制約を追加
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.table_constraints
            WHERE constraint_name = 'fk_search_logs_user_department' AND table_name = 'knowledge_search_logs'
        ) THEN
            ALTER TABLE knowledge_search_logs
            ADD CONSTRAINT fk_search_logs_user_department
            FOREIGN KEY (user_department_id) REFERENCES departments(id);
            RAISE NOTICE 'Added FK constraint: knowledge_search_logs.user_department_id -> departments.id';
        END IF;
    ELSE
        RAISE NOTICE 'departments table not found. FK constraints not added. Run Phase 3.5 migration first.';
    END IF;
END $$;
*/

-- ================================================================
-- STEP 9: 確認クエリ
-- ================================================================

-- 作成されたテーブルの確認
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
    'documents',
    'document_versions',
    'document_chunks',
    'knowledge_search_logs',
    'knowledge_feedback',
    'google_drive_sync_logs',
    'google_drive_sync_state'
  )
ORDER BY table_name;

-- 各テーブルのカラム数確認
SELECT
    table_name,
    COUNT(*) as column_count
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN (
    'documents',
    'document_versions',
    'document_chunks',
    'knowledge_search_logs',
    'knowledge_feedback',
    'google_drive_sync_logs',
    'google_drive_sync_state'
  )
GROUP BY table_name
ORDER BY table_name;

-- ================================================================
-- STEP 10: コミット
-- ================================================================
COMMIT;

-- ================================================================
-- 成功メッセージ
-- ================================================================
--
-- Phase 3 マイグレーションが完了しました！
--
-- 作成されたテーブル:
-- 1. documents           - ナレッジドキュメントのメタデータ
-- 2. document_versions   - ドキュメントのバージョン履歴
-- 3. document_chunks     - ドキュメントのチャンク（Pinecone連携）
-- 4. knowledge_search_logs - 検索ログ
-- 5. knowledge_feedback  - ユーザーフィードバック
-- 6. google_drive_sync_logs - Googleドライブ同期ログ
-- 7. google_drive_sync_state - Googleドライブ同期状態
--
-- 次のステップ:
-- 1. Pineconeインデックスの作成
-- 2. lib/google_drive.py の実装
-- 3. Cloud Functions watch_google_drive のデプロイ
-- ================================================================

-- ================================================================
-- ロールバック用（エラー時のみ実行）
-- ================================================================
/*
-- ロールバック（全テーブル削除）
BEGIN;

DROP TABLE IF EXISTS knowledge_feedback CASCADE;
DROP TABLE IF EXISTS knowledge_search_logs CASCADE;
DROP TABLE IF EXISTS document_chunks CASCADE;
DROP TABLE IF EXISTS document_versions CASCADE;
DROP TABLE IF EXISTS google_drive_sync_state CASCADE;
DROP TABLE IF EXISTS google_drive_sync_logs CASCADE;
DROP TABLE IF EXISTS documents CASCADE;

COMMIT;
*/
