-- Phase 2O: 創発（Emergence）マイグレーション
-- 作成日: 2026-02-09
-- 設計: 全Phase 2E-2Nの能力統合、創発パターン検出、戦略提案
--
-- PII保護: 能力メタデータ・集計スコアのみ。個人データは保存しない。

BEGIN;

-- ============================================================================
-- 1. brain_capability_graph - 能力間の関係グラフ
-- ============================================================================

CREATE TABLE IF NOT EXISTS brain_capability_graph (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,

    -- エッジ情報
    source_phase VARCHAR(10) NOT NULL,
    target_phase VARCHAR(10) NOT NULL,
    integration_type VARCHAR(30) NOT NULL DEFAULT 'synergy',
    strength DECIMAL(5,4) NOT NULL DEFAULT 0.5000,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    evidence_count INTEGER NOT NULL DEFAULT 0,

    -- タイムスタンプ
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- ユニーク制約（組織×フェーズペアで冪等）
    CONSTRAINT uq_capability_edge UNIQUE (organization_id, source_phase, target_phase),

    -- ステータスチェック
    CONSTRAINT chk_edge_status CHECK (status IN ('active', 'inactive', 'hypothesized')),

    -- 統合タイプチェック
    CONSTRAINT chk_integration_type CHECK (integration_type IN ('synergy', 'dependency', 'amplification', 'complement')),

    -- 強度範囲チェック
    CONSTRAINT chk_edge_strength CHECK (strength >= 0.0000 AND strength <= 1.0000)
);

CREATE INDEX IF NOT EXISTS idx_cap_graph_org ON brain_capability_graph(organization_id);
CREATE INDEX IF NOT EXISTS idx_cap_graph_status ON brain_capability_graph(status);

COMMENT ON TABLE brain_capability_graph IS '能力間の関係グラフ（PII含まず、フェーズID・強度のみ）';

-- Owner (RLS requires table owner)
ALTER TABLE brain_capability_graph OWNER TO soulkun_user;

-- RLS
ALTER TABLE brain_capability_graph ENABLE ROW LEVEL SECURITY;
CREATE POLICY rls_cap_graph_org ON brain_capability_graph
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);


-- ============================================================================
-- 2. brain_emergent_behaviors - 創発的行動パターン
-- ============================================================================

CREATE TABLE IF NOT EXISTS brain_emergent_behaviors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,

    -- パターン情報
    behavior_type VARCHAR(30) NOT NULL DEFAULT 'novel_combination',
    description VARCHAR(500) NOT NULL DEFAULT '',
    involved_phases JSONB NOT NULL DEFAULT '[]',
    confidence DECIMAL(5,4) NOT NULL DEFAULT 0.0000,
    impact_score DECIMAL(5,4) NOT NULL DEFAULT 0.0000,
    occurrence_count INTEGER NOT NULL DEFAULT 1,

    -- タイムスタンプ
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- 行動タイプチェック
    CONSTRAINT chk_behavior_type CHECK (behavior_type IN ('novel_combination', 'unexpected_pattern', 'adaptive_response', 'cross_domain')),

    -- スコア範囲チェック
    CONSTRAINT chk_behavior_confidence CHECK (confidence >= 0.0000 AND confidence <= 1.0000),
    CONSTRAINT chk_behavior_impact CHECK (impact_score >= 0.0000 AND impact_score <= 1.0000)
);

CREATE INDEX IF NOT EXISTS idx_emergent_org ON brain_emergent_behaviors(organization_id);
CREATE INDEX IF NOT EXISTS idx_emergent_type ON brain_emergent_behaviors(behavior_type);
CREATE INDEX IF NOT EXISTS idx_emergent_created ON brain_emergent_behaviors(created_at);

COMMENT ON TABLE brain_emergent_behaviors IS '創発的行動パターン（PII含まず、パターンタイプ・スコアのみ）';

-- Owner (RLS requires table owner)
ALTER TABLE brain_emergent_behaviors OWNER TO soulkun_user;

-- RLS
ALTER TABLE brain_emergent_behaviors ENABLE ROW LEVEL SECURITY;
CREATE POLICY rls_emergent_org ON brain_emergent_behaviors
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);


-- ============================================================================
-- 3. brain_strategic_insights - 戦略的インサイト
-- ============================================================================

CREATE TABLE IF NOT EXISTS brain_strategic_insights (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,

    -- インサイト情報
    insight_type VARCHAR(30) NOT NULL DEFAULT 'opportunity',
    title VARCHAR(200) NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    relevance_score DECIMAL(5,4) NOT NULL DEFAULT 0.0000,
    source_phases JSONB NOT NULL DEFAULT '[]',
    actionable BOOLEAN NOT NULL DEFAULT FALSE,

    -- タイムスタンプ
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- インサイトタイプチェック
    CONSTRAINT chk_insight_type CHECK (insight_type IN ('opportunity', 'risk', 'trend', 'recommendation', 'prediction')),

    -- スコア範囲チェック
    CONSTRAINT chk_insight_relevance CHECK (relevance_score >= 0.0000 AND relevance_score <= 1.0000)
);

CREATE INDEX IF NOT EXISTS idx_insights_org ON brain_strategic_insights(organization_id);
CREATE INDEX IF NOT EXISTS idx_insights_type ON brain_strategic_insights(insight_type);
CREATE INDEX IF NOT EXISTS idx_insights_created ON brain_strategic_insights(created_at);

COMMENT ON TABLE brain_strategic_insights IS '戦略的インサイト（PII含まず、カテゴリ・スコアのみ）';

-- Owner (RLS requires table owner)
ALTER TABLE brain_strategic_insights OWNER TO soulkun_user;

-- RLS
ALTER TABLE brain_strategic_insights ENABLE ROW LEVEL SECURITY;
CREATE POLICY rls_insights_org ON brain_strategic_insights
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);


-- ============================================================================
-- 4. brain_org_snapshots - 組織スナップショット
-- ============================================================================

CREATE TABLE IF NOT EXISTS brain_org_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,

    -- スナップショットデータ
    capability_scores JSONB NOT NULL DEFAULT '{}',
    overall_score DECIMAL(5,4) NOT NULL DEFAULT 0.0000,
    active_edges INTEGER NOT NULL DEFAULT 0,
    emergent_count INTEGER NOT NULL DEFAULT 0,
    insight_count INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'active',

    -- タイムスタンプ
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- ステータスチェック
    CONSTRAINT chk_snapshot_status CHECK (status IN ('active', 'archived')),

    -- スコア範囲チェック
    CONSTRAINT chk_snapshot_score CHECK (overall_score >= 0.0000 AND overall_score <= 1.0000)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_org ON brain_org_snapshots(organization_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_status ON brain_org_snapshots(status);
CREATE INDEX IF NOT EXISTS idx_snapshots_created ON brain_org_snapshots(created_at);

COMMENT ON TABLE brain_org_snapshots IS '組織状態スナップショット（PII含まず、集計メトリクスのみ）';

-- Owner (RLS requires table owner)
ALTER TABLE brain_org_snapshots OWNER TO soulkun_user;

-- RLS
ALTER TABLE brain_org_snapshots ENABLE ROW LEVEL SECURITY;
CREATE POLICY rls_snapshots_org ON brain_org_snapshots
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);

COMMIT;
