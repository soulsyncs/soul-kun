-- =============================================================================
-- Phase M1: Multimodal入力能力 - DBマイグレーション
--
-- このマイグレーションは、Multimodal入力処理に必要なテーブルを作成します。
--
-- テーブル:
-- 1. multimodal_processing_logs - 処理ログ（監査・分析用）
-- 2. multimodal_extracted_entities - 抽出エンティティ（検索用）
--
-- 設計書: docs/20_next_generation_capabilities.md
-- Author: Claude Opus 4.5
-- Created: 2026-01-27
-- =============================================================================

-- トランザクション開始
BEGIN;

-- =============================================================================
-- 1. multimodal_processing_logs テーブル
-- =============================================================================
-- 全てのMultimodal処理のログを記録
-- 監査・分析・デバッグに使用

CREATE TABLE IF NOT EXISTS multimodal_processing_logs (
    -- 主キー
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- 組織ID（10の鉄則: テナント分離）
    organization_id UUID NOT NULL,

    -- 処理情報
    processing_id VARCHAR(50) NOT NULL,  -- 一意の処理ID
    input_type VARCHAR(20) NOT NULL,     -- image, pdf, url, audio, video
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending, processing, completed, failed

    -- タイミング
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    processing_time_ms INTEGER,

    -- コンテキスト
    room_id VARCHAR(50),                 -- ChatWorkルームID
    user_id VARCHAR(50),                 -- ユーザーID
    instruction TEXT,                    -- ユーザーからの指示

    -- 入力情報（機密情報は含めない）
    input_hash VARCHAR(64),              -- 入力データのSHA-256ハッシュ
    input_size_bytes INTEGER,
    input_format VARCHAR(20),            -- jpg, png, pdf, etc.

    -- モデル情報
    model_used VARCHAR(100),             -- 使用したVisionモデル
    model_provider VARCHAR(50),          -- google, openai, anthropic
    api_calls_count INTEGER DEFAULT 0,

    -- コスト情報
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    estimated_cost_jpy DECIMAL(10, 4) DEFAULT 0,

    -- 結果サマリー（詳細は含めない）
    success BOOLEAN NOT NULL DEFAULT FALSE,
    confidence_score DECIMAL(3, 2),      -- 0.00 - 1.00
    entities_count INTEGER DEFAULT 0,
    summary_preview VARCHAR(200),        -- 要約の先頭200文字

    -- エラー情報
    error_code VARCHAR(50),
    error_message TEXT,

    -- メタデータ
    metadata JSONB DEFAULT '{}',

    -- タイムスタンプ
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_multimodal_logs_org_id
    ON multimodal_processing_logs(organization_id);

CREATE INDEX IF NOT EXISTS idx_multimodal_logs_processing_id
    ON multimodal_processing_logs(processing_id);

CREATE INDEX IF NOT EXISTS idx_multimodal_logs_input_type
    ON multimodal_processing_logs(input_type);

CREATE INDEX IF NOT EXISTS idx_multimodal_logs_status
    ON multimodal_processing_logs(status);

CREATE INDEX IF NOT EXISTS idx_multimodal_logs_created_at
    ON multimodal_processing_logs(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_multimodal_logs_org_type_created
    ON multimodal_processing_logs(organization_id, input_type, created_at DESC);

-- 複合インデックス（分析用）
CREATE INDEX IF NOT EXISTS idx_multimodal_logs_org_success_created
    ON multimodal_processing_logs(organization_id, success, created_at DESC);

-- コメント
COMMENT ON TABLE multimodal_processing_logs IS 'Phase M1: Multimodal処理ログ（監査・分析用）';
COMMENT ON COLUMN multimodal_processing_logs.organization_id IS '組織ID（テナント分離用）';
COMMENT ON COLUMN multimodal_processing_logs.processing_id IS '一意の処理ID';
COMMENT ON COLUMN multimodal_processing_logs.input_type IS '入力タイプ: image, pdf, url, audio, video';
COMMENT ON COLUMN multimodal_processing_logs.input_hash IS '入力データのSHA-256ハッシュ（重複検出用）';
COMMENT ON COLUMN multimodal_processing_logs.model_used IS '使用したVision/LLMモデルID';
COMMENT ON COLUMN multimodal_processing_logs.estimated_cost_jpy IS '推定コスト（円）';


-- =============================================================================
-- 2. multimodal_extracted_entities テーブル
-- =============================================================================
-- 抽出されたエンティティを保存（検索・分析用）

CREATE TABLE IF NOT EXISTS multimodal_extracted_entities (
    -- 主キー
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- 組織ID（10の鉄則: テナント分離）
    organization_id UUID NOT NULL,

    -- 処理ログへの参照
    processing_log_id UUID NOT NULL REFERENCES multimodal_processing_logs(id) ON DELETE CASCADE,

    -- エンティティ情報
    entity_type VARCHAR(50) NOT NULL,    -- person, organization, date, amount, location, email, phone, url, etc.
    entity_value TEXT NOT NULL,          -- 抽出された値
    confidence DECIMAL(3, 2) NOT NULL DEFAULT 0.50,  -- 0.00 - 1.00

    -- コンテキスト
    context TEXT,                        -- エンティティ周辺のコンテキスト
    start_position INTEGER,              -- テキスト内の開始位置
    end_position INTEGER,                -- テキスト内の終了位置

    -- 正規化
    normalized_value TEXT,               -- 正規化された値（日付: ISO形式、金額: 数値）
    canonical_id VARCHAR(100),           -- 正規化されたID（人物DBへの参照等）

    -- メタデータ
    metadata JSONB DEFAULT '{}',

    -- タイムスタンプ
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_multimodal_entities_org_id
    ON multimodal_extracted_entities(organization_id);

CREATE INDEX IF NOT EXISTS idx_multimodal_entities_log_id
    ON multimodal_extracted_entities(processing_log_id);

CREATE INDEX IF NOT EXISTS idx_multimodal_entities_type
    ON multimodal_extracted_entities(entity_type);

CREATE INDEX IF NOT EXISTS idx_multimodal_entities_value
    ON multimodal_extracted_entities(entity_value);

-- 全文検索用インデックス（日本語）
CREATE INDEX IF NOT EXISTS idx_multimodal_entities_value_gin
    ON multimodal_extracted_entities USING gin(to_tsvector('simple', entity_value));

-- 複合インデックス（検索用）
CREATE INDEX IF NOT EXISTS idx_multimodal_entities_org_type_value
    ON multimodal_extracted_entities(organization_id, entity_type, entity_value);

-- コメント
COMMENT ON TABLE multimodal_extracted_entities IS 'Phase M1: 抽出エンティティ（検索・分析用）';
COMMENT ON COLUMN multimodal_extracted_entities.entity_type IS 'エンティティタイプ: person, organization, date, amount, location, email, phone, url等';
COMMENT ON COLUMN multimodal_extracted_entities.confidence IS '抽出の確信度（0.00-1.00）';
COMMENT ON COLUMN multimodal_extracted_entities.normalized_value IS '正規化された値（検索用）';


-- =============================================================================
-- 3. 更新トリガー
-- =============================================================================

-- multimodal_processing_logsのupdated_at自動更新
CREATE OR REPLACE FUNCTION update_multimodal_logs_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_multimodal_logs_updated_at ON multimodal_processing_logs;
CREATE TRIGGER trg_multimodal_logs_updated_at
    BEFORE UPDATE ON multimodal_processing_logs
    FOR EACH ROW
    EXECUTE FUNCTION update_multimodal_logs_updated_at();


-- =============================================================================
-- 4. Row Level Security（Phase 4A準備）
-- =============================================================================

-- RLSを有効化
ALTER TABLE multimodal_processing_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE multimodal_extracted_entities ENABLE ROW LEVEL SECURITY;

-- 既存のポリシーを削除（再実行時のため）
DROP POLICY IF EXISTS multimodal_logs_org_isolation ON multimodal_processing_logs;
DROP POLICY IF EXISTS multimodal_entities_org_isolation ON multimodal_extracted_entities;

-- 組織IDによるアクセス制限ポリシー
-- 注: 実際のRLS適用はPhase 4Aで行う（現時点ではポリシー定義のみ）
CREATE POLICY multimodal_logs_org_isolation ON multimodal_processing_logs
    FOR ALL
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid);

CREATE POLICY multimodal_entities_org_isolation ON multimodal_extracted_entities
    FOR ALL
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid);


-- =============================================================================
-- 5. 統計情報取得用ビュー
-- =============================================================================

-- 組織別の処理統計ビュー
CREATE OR REPLACE VIEW v_multimodal_stats AS
SELECT
    organization_id,
    input_type,
    DATE_TRUNC('day', created_at) AS date,
    COUNT(*) AS total_count,
    SUM(CASE WHEN success THEN 1 ELSE 0 END) AS success_count,
    SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) AS failure_count,
    AVG(processing_time_ms) AS avg_processing_time_ms,
    SUM(estimated_cost_jpy) AS total_cost_jpy,
    AVG(confidence_score) AS avg_confidence
FROM multimodal_processing_logs
GROUP BY organization_id, input_type, DATE_TRUNC('day', created_at);

COMMENT ON VIEW v_multimodal_stats IS 'Phase M1: 組織別・タイプ別の日次処理統計';


-- =============================================================================
-- 6. 古いログのクリーンアップ関数
-- =============================================================================

CREATE OR REPLACE FUNCTION cleanup_old_multimodal_logs(retention_days INTEGER DEFAULT 90)
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    -- 古いエンティティを削除（カスケードで自動削除されるが明示的に）
    DELETE FROM multimodal_extracted_entities
    WHERE processing_log_id IN (
        SELECT id FROM multimodal_processing_logs
        WHERE created_at < NOW() - (retention_days || ' days')::INTERVAL
    );

    -- 古いログを削除
    DELETE FROM multimodal_processing_logs
    WHERE created_at < NOW() - (retention_days || ' days')::INTERVAL;

    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION cleanup_old_multimodal_logs IS '指定日数より古いMultimodal処理ログを削除';


-- コミット
COMMIT;

-- =============================================================================
-- 実行確認
-- =============================================================================
-- 以下のクエリで作成されたオブジェクトを確認:
--
-- SELECT table_name FROM information_schema.tables
-- WHERE table_name LIKE 'multimodal%';
--
-- SELECT indexname FROM pg_indexes
-- WHERE tablename LIKE 'multimodal%';
-- =============================================================================
