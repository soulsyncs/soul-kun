-- ============================================================
-- Phase 2.5 + B Memory統合: ユーザー目標パターン分析
-- 作成日: 2026-01-24
-- 作成者: Claude Code
-- ============================================================

-- ============================================================
-- goal_setting_user_patterns（ユーザー目標パターン蓄積）
-- ============================================================

CREATE TABLE IF NOT EXISTS goal_setting_user_patterns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- パターン統計
    dominant_pattern VARCHAR(50),              -- 最も多く検出されたパターン
    pattern_history JSONB DEFAULT '{}',        -- {パターンコード: 出現回数}

    -- 対話統計
    total_sessions INT DEFAULT 0,              -- 総セッション数
    completed_sessions INT DEFAULT 0,          -- 完了セッション数
    avg_retry_count DECIMAL(4,2) DEFAULT 0.0,  -- 平均リトライ回数
    completion_rate DECIMAL(5,2) DEFAULT 0.0,  -- 完了率 (%)

    -- WHY/WHAT/HOWの傾向
    why_pattern_tendency JSONB DEFAULT '{}',   -- WHYステップのパターン傾向
    what_pattern_tendency JSONB DEFAULT '{}',  -- WHATステップのパターン傾向
    how_pattern_tendency JSONB DEFAULT '{}',   -- HOWステップのパターン傾向

    -- 具体性スコア傾向
    avg_specificity_score DECIMAL(4,3) DEFAULT 0.0,  -- 平均具体性スコア

    -- フィードバック効果
    preferred_feedback_style VARCHAR(50),      -- gentle / direct / supportive
    effective_retry_templates TEXT[] DEFAULT '{}',  -- 効果があったテンプレート

    -- 機密区分
    classification VARCHAR(20) DEFAULT 'internal',

    -- 監査フィールド
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 制約
    UNIQUE(organization_id, user_id),
    CONSTRAINT check_gsup_classification
        CHECK (classification IN ('public', 'internal', 'confidential', 'restricted')),
    CONSTRAINT check_gsup_completion_rate
        CHECK (completion_rate >= 0 AND completion_rate <= 100),
    CONSTRAINT check_gsup_avg_retry
        CHECK (avg_retry_count >= 0)
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_goal_user_patterns_org_user
    ON goal_setting_user_patterns(organization_id, user_id);
CREATE INDEX IF NOT EXISTS idx_goal_user_patterns_dominant
    ON goal_setting_user_patterns(dominant_pattern)
    WHERE dominant_pattern IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_goal_user_patterns_completion
    ON goal_setting_user_patterns(completion_rate DESC);

COMMENT ON TABLE goal_setting_user_patterns IS
    'Phase 2.5 + B統合: ユーザーごとの目標設定パターン傾向を蓄積';
COMMENT ON COLUMN goal_setting_user_patterns.dominant_pattern IS
    '最も多く検出されたパターン（ng_abstract, ng_career等）';
COMMENT ON COLUMN goal_setting_user_patterns.pattern_history IS
    'パターン履歴 JSON: {"ng_abstract": 5, "ng_other_blame": 2, "ok": 10}';
COMMENT ON COLUMN goal_setting_user_patterns.preferred_feedback_style IS
    'ユーザーが好むフィードバックスタイル: gentle / direct / supportive';

-- ============================================================
-- 完了メッセージ
-- ============================================================

DO $$
BEGIN
    RAISE NOTICE '✅ Phase 2.5 + B Memory統合 テーブル作成完了';
    RAISE NOTICE '  - goal_setting_user_patterns: ユーザー目標パターン蓄積';
END $$;
