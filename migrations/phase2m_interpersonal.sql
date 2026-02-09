-- Phase 2M: 対人力強化（Interpersonal Skills）マイグレーション
-- 作成日: 2026-02-09
-- 設計書: docs/17_brain_completion_roadmap.md セクション Phase 2M
--
-- コミュニケーションスタイル適応、動機付け、助言、対立調停のためのテーブル
-- PII保護: メッセージ本文・個人名は保存しない。行動メタデータのみ。

BEGIN;

-- ============================================================================
-- 1. brain_communication_profiles - コミュニケーションプロファイル
-- ============================================================================

CREATE TABLE IF NOT EXISTS brain_communication_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,

    -- ユーザー情報
    user_id UUID NOT NULL,

    -- スタイル嗜好
    preferred_length VARCHAR(20) NOT NULL DEFAULT 'balanced',
    formality_level VARCHAR(20) NOT NULL DEFAULT 'adaptive',
    preferred_timing VARCHAR(20) NOT NULL DEFAULT 'anytime',

    -- レスポンス嗜好（JSONB）
    response_preferences JSONB DEFAULT '{}',

    -- 統計
    interaction_count INTEGER NOT NULL DEFAULT 0,
    confidence_score DECIMAL(3,2) NOT NULL DEFAULT 0.50,

    -- タイムスタンプ
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- ユニーク制約（組織×ユーザーで1レコード）
    CONSTRAINT uq_comm_profiles_org_user UNIQUE (organization_id, user_id),

    -- スコア範囲チェック
    CONSTRAINT chk_comm_confidence_range CHECK (confidence_score >= 0.00 AND confidence_score <= 1.00)
);

CREATE INDEX IF NOT EXISTS idx_comm_profiles_org ON brain_communication_profiles(organization_id);
CREATE INDEX IF NOT EXISTS idx_comm_profiles_user ON brain_communication_profiles(user_id);

COMMENT ON TABLE brain_communication_profiles IS 'ユーザーごとのコミュニケーションスタイルプロファイル（PII含まず）';

-- Owner (RLS requires table owner)
ALTER TABLE brain_communication_profiles OWNER TO soulkun_user;

-- RLS
ALTER TABLE brain_communication_profiles ENABLE ROW LEVEL SECURITY;
CREATE POLICY rls_comm_profiles_org ON brain_communication_profiles
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);


-- ============================================================================
-- 2. brain_motivation_profiles - モチベーションプロファイル
-- ============================================================================

CREATE TABLE IF NOT EXISTS brain_motivation_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,

    -- ユーザー情報
    user_id UUID NOT NULL,

    -- モチベーションタイプ
    primary_type VARCHAR(30) NOT NULL DEFAULT 'achievement',
    secondary_type VARCHAR(30),

    -- 価値観（カテゴリ名配列、具体的テキストは含まない）
    key_values JSONB DEFAULT '[]',

    -- 落ち込みトリガー（シグナルタイプ配列）
    discouragement_triggers JSONB DEFAULT '[]',

    -- 統計
    sample_count INTEGER NOT NULL DEFAULT 0,
    confidence_score DECIMAL(3,2) NOT NULL DEFAULT 0.50,

    -- タイムスタンプ
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- ユニーク制約
    CONSTRAINT uq_motivation_profiles_org_user UNIQUE (organization_id, user_id),

    -- スコア範囲チェック
    CONSTRAINT chk_motivation_confidence_range CHECK (confidence_score >= 0.00 AND confidence_score <= 1.00)
);

CREATE INDEX IF NOT EXISTS idx_motivation_profiles_org ON brain_motivation_profiles(organization_id);
CREATE INDEX IF NOT EXISTS idx_motivation_profiles_user ON brain_motivation_profiles(user_id);

COMMENT ON TABLE brain_motivation_profiles IS 'ユーザーのモチベーションタイプ・価値観プロファイル（PII含まず）';

-- Owner (RLS requires table owner)
ALTER TABLE brain_motivation_profiles OWNER TO soulkun_user;

-- RLS
ALTER TABLE brain_motivation_profiles ENABLE ROW LEVEL SECURITY;
CREATE POLICY rls_motivation_profiles_org ON brain_motivation_profiles
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);


-- ============================================================================
-- 3. brain_feedback_opportunities - フィードバック機会
-- ============================================================================

CREATE TABLE IF NOT EXISTS brain_feedback_opportunities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,

    -- ユーザー情報
    user_id UUID NOT NULL,

    -- フィードバック内容
    feedback_type VARCHAR(30) NOT NULL DEFAULT 'constructive',
    context_category VARCHAR(100) NOT NULL DEFAULT '',
    receptiveness_score DECIMAL(3,2) NOT NULL DEFAULT 0.50,

    -- 配信状態
    delivered BOOLEAN NOT NULL DEFAULT FALSE,
    delivered_at TIMESTAMPTZ,

    -- タイムスタンプ
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- スコア範囲チェック
    CONSTRAINT chk_feedback_receptiveness_range CHECK (receptiveness_score >= 0.00 AND receptiveness_score <= 1.00)
);

CREATE INDEX IF NOT EXISTS idx_feedback_opp_org ON brain_feedback_opportunities(organization_id);
CREATE INDEX IF NOT EXISTS idx_feedback_opp_user ON brain_feedback_opportunities(user_id);
CREATE INDEX IF NOT EXISTS idx_feedback_opp_delivered ON brain_feedback_opportunities(delivered);
CREATE INDEX IF NOT EXISTS idx_feedback_opp_created ON brain_feedback_opportunities(created_at);

COMMENT ON TABLE brain_feedback_opportunities IS 'フィードバック機会の記録（PII含まず、カテゴリタグのみ）';

-- Owner (RLS requires table owner)
ALTER TABLE brain_feedback_opportunities OWNER TO soulkun_user;

-- RLS
ALTER TABLE brain_feedback_opportunities ENABLE ROW LEVEL SECURITY;
CREATE POLICY rls_feedback_opp_org ON brain_feedback_opportunities
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);


-- ============================================================================
-- 4. brain_conflict_logs - 対立ログ
-- ============================================================================

CREATE TABLE IF NOT EXISTS brain_conflict_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,

    -- 関係者（IDのみ、名前は含まない）
    party_a_user_id UUID NOT NULL,
    party_b_user_id UUID NOT NULL,

    -- 対立情報
    context_category VARCHAR(100) NOT NULL DEFAULT '',
    severity VARCHAR(20) NOT NULL DEFAULT 'low',
    status VARCHAR(20) NOT NULL DEFAULT 'detected',

    -- 調停
    mediation_strategy_type VARCHAR(50),
    evidence_count INTEGER NOT NULL DEFAULT 0,

    -- タイムスタンプ
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,

    -- ステータスチェック
    CONSTRAINT chk_conflict_severity CHECK (severity IN ('low', 'medium', 'high')),
    CONSTRAINT chk_conflict_status CHECK (status IN ('detected', 'monitoring', 'mediating', 'resolved', 'escalated'))
);

CREATE INDEX IF NOT EXISTS idx_conflict_logs_org ON brain_conflict_logs(organization_id);
CREATE INDEX IF NOT EXISTS idx_conflict_logs_status ON brain_conflict_logs(status);
CREATE INDEX IF NOT EXISTS idx_conflict_logs_parties ON brain_conflict_logs(party_a_user_id, party_b_user_id);
CREATE INDEX IF NOT EXISTS idx_conflict_logs_detected ON brain_conflict_logs(detected_at);

COMMENT ON TABLE brain_conflict_logs IS '対立の検知・調停記録（PII含まず、IDとカテゴリのみ）';

-- Owner (RLS requires table owner)
ALTER TABLE brain_conflict_logs OWNER TO soulkun_user;

-- RLS
ALTER TABLE brain_conflict_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY rls_conflict_logs_org ON brain_conflict_logs
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);

COMMIT;
