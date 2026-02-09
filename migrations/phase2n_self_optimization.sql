-- Phase 2N: 自己最適化（Self-Optimization）マイグレーション
-- 作成日: 2026-02-09
-- 設計書: docs/17_brain_completion_roadmap.md セクション Phase 2N
--
-- パフォーマンス分析、改善立案、A/Bテスト、自動デプロイのためのテーブル
-- PII保護: 集計メトリクスのみ。個人のメッセージ本文・名前は保存しない。

BEGIN;

-- ============================================================================
-- 1. brain_performance_metrics - パフォーマンス指標
-- ============================================================================

CREATE TABLE IF NOT EXISTS brain_performance_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,

    -- メトリクス情報
    metric_type VARCHAR(50) NOT NULL DEFAULT 'response_quality',
    score DECIMAL(5,4) NOT NULL DEFAULT 0.5000,
    sample_count INTEGER NOT NULL DEFAULT 0,

    -- タイムスタンプ
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- スコア範囲チェック
    CONSTRAINT chk_perf_score_range CHECK (score >= 0.0000 AND score <= 1.0000)
);

CREATE INDEX IF NOT EXISTS idx_perf_metrics_org ON brain_performance_metrics(organization_id);
CREATE INDEX IF NOT EXISTS idx_perf_metrics_type ON brain_performance_metrics(metric_type);
CREATE INDEX IF NOT EXISTS idx_perf_metrics_created ON brain_performance_metrics(created_at);

COMMENT ON TABLE brain_performance_metrics IS '能力別パフォーマンス指標（PII含まず、集計値のみ）';

-- Owner (RLS requires table owner)
ALTER TABLE brain_performance_metrics OWNER TO soulkun_user;

-- RLS
ALTER TABLE brain_performance_metrics ENABLE ROW LEVEL SECURITY;
CREATE POLICY rls_perf_metrics_org ON brain_performance_metrics
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);


-- ============================================================================
-- 2. brain_improvement_proposals - 改善提案
-- ============================================================================

CREATE TABLE IF NOT EXISTS brain_improvement_proposals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,

    -- 提案内容
    title VARCHAR(200) NOT NULL DEFAULT '',
    target_metric VARCHAR(50) NOT NULL DEFAULT 'response_quality',
    hypothesis TEXT NOT NULL DEFAULT '',
    expected_improvement DECIMAL(5,4) NOT NULL DEFAULT 0.0000,

    -- ステータス
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    priority INTEGER NOT NULL DEFAULT 0,

    -- 結果
    actual_improvement DECIMAL(5,4),
    ab_test_id UUID,

    -- タイムスタンプ
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- ステータスチェック
    CONSTRAINT chk_proposal_status CHECK (status IN ('draft', 'proposed', 'approved', 'testing', 'deployed', 'rejected', 'rolled_back'))
);

CREATE INDEX IF NOT EXISTS idx_proposals_org ON brain_improvement_proposals(organization_id);
CREATE INDEX IF NOT EXISTS idx_proposals_status ON brain_improvement_proposals(status);

COMMENT ON TABLE brain_improvement_proposals IS '改善施策の提案・管理（PII含まず、カテゴリのみ）';

-- Owner (RLS requires table owner)
ALTER TABLE brain_improvement_proposals OWNER TO soulkun_user;

-- RLS
ALTER TABLE brain_improvement_proposals ENABLE ROW LEVEL SECURITY;
CREATE POLICY rls_proposals_org ON brain_improvement_proposals
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);


-- ============================================================================
-- 3. brain_ab_tests - A/Bテスト
-- ============================================================================

CREATE TABLE IF NOT EXISTS brain_ab_tests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,

    -- テスト定義
    test_name VARCHAR(200) NOT NULL,
    proposal_id UUID,
    target_metric VARCHAR(50) NOT NULL DEFAULT 'response_quality',

    -- バリアント
    variant_a_description VARCHAR(200) NOT NULL DEFAULT 'control',
    variant_b_description VARCHAR(200) NOT NULL DEFAULT 'treatment',
    traffic_split DECIMAL(3,2) NOT NULL DEFAULT 0.50,

    -- ステータス
    status VARCHAR(20) NOT NULL DEFAULT 'created',

    -- 結果
    variant_a_score DECIMAL(5,4),
    variant_b_score DECIMAL(5,4),
    variant_a_samples INTEGER NOT NULL DEFAULT 0,
    variant_b_samples INTEGER NOT NULL DEFAULT 0,
    outcome VARCHAR(30),
    confidence DECIMAL(5,4),

    -- タイムスタンプ
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- ユニーク制約（組織×テスト名で冪等）
    CONSTRAINT uq_ab_tests_org_name UNIQUE (organization_id, test_name),

    -- ステータスチェック
    CONSTRAINT chk_test_status CHECK (status IN ('created', 'running', 'paused', 'completed', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS idx_ab_tests_org ON brain_ab_tests(organization_id);
CREATE INDEX IF NOT EXISTS idx_ab_tests_status ON brain_ab_tests(status);

COMMENT ON TABLE brain_ab_tests IS 'A/Bテスト定義・結果（PII含まず、戦略タイプ名のみ）';

-- Owner (RLS requires table owner)
ALTER TABLE brain_ab_tests OWNER TO soulkun_user;

-- RLS
ALTER TABLE brain_ab_tests ENABLE ROW LEVEL SECURITY;
CREATE POLICY rls_ab_tests_org ON brain_ab_tests
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);


-- ============================================================================
-- 4. brain_deployment_logs - デプロイログ
-- ============================================================================

CREATE TABLE IF NOT EXISTS brain_deployment_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,

    -- デプロイ情報
    proposal_id UUID,
    ab_test_id UUID,
    status VARCHAR(20) NOT NULL DEFAULT 'canary',

    -- メトリクス
    pre_deploy_score DECIMAL(5,4),
    post_deploy_score DECIMAL(5,4),
    improvement_delta DECIMAL(5,4),
    rollback_reason TEXT,

    -- タイムスタンプ
    deployed_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- ステータスチェック
    CONSTRAINT chk_deploy_status CHECK (status IN ('canary', 'rolling', 'full', 'rolled_back', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_deploy_logs_org ON brain_deployment_logs(organization_id);
CREATE INDEX IF NOT EXISTS idx_deploy_logs_status ON brain_deployment_logs(status);
CREATE INDEX IF NOT EXISTS idx_deploy_logs_created ON brain_deployment_logs(created_at);

COMMENT ON TABLE brain_deployment_logs IS '改善施策の展開ログ（PII含まず、メトリクス集計値のみ）';

-- Owner (RLS requires table owner)
ALTER TABLE brain_deployment_logs OWNER TO soulkun_user;

-- RLS
ALTER TABLE brain_deployment_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY rls_deploy_logs_org ON brain_deployment_logs
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);

COMMIT;
