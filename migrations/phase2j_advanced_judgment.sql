-- Phase 2J: 判断力強化（Advanced Judgment）DBマイグレーション
-- 設計書: docs/17_brain_completion_roadmap.md セクション17.3 Phase 2J
-- Author: Claude Opus 4.5
-- Created: 2026-01-27

-- =============================================================================
-- 判断履歴テーブル
-- =============================================================================

-- 判断の履歴を記録するテーブル（過去判断との整合性チェック用）
CREATE TABLE IF NOT EXISTS judgment_history (
    -- 主キー
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- 組織ID（テナント分離）
    organization_id VARCHAR(255) NOT NULL,

    -- ユーザーID
    user_id VARCHAR(255),

    -- ChatWorkアカウントID
    chatwork_account_id VARCHAR(255),

    -- ルームID
    room_id VARCHAR(255),

    -- 判断タイプ
    judgment_type VARCHAR(50) NOT NULL DEFAULT 'comparison',
    -- comparison, ranking, best_choice, risk_assessment, go_no_go,
    -- candidate_evaluation, investment_decision, etc.

    -- 判断の質問・課題
    question TEXT NOT NULL,

    -- 選択肢（JSON配列）
    options_json JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- 評価基準（JSON配列）
    criteria_json JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- 選択肢評価結果（JSON配列）
    evaluations_json JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- トレードオフ分析結果（JSON）
    tradeoffs_json JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- リスク評価結果（JSON）
    risk_assessment_json JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- リターン評価結果（JSON）
    return_assessment_json JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- 整合性チェック結果（JSON）
    consistency_check_json JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- 推奨結果（JSON）
    recommendation_json JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- 推奨された選択肢
    recommended_option VARCHAR(255),

    -- 実際に選択された選択肢（ユーザーの最終判断）
    actual_choice VARCHAR(255),

    -- 判断理由
    reasoning TEXT,

    -- 判断結果（後から記録：成功/失敗等）
    outcome TEXT,

    -- 結果評価スコア（後から記録：0-1）
    outcome_score DECIMAL(3, 2),

    -- 全体の信頼度
    overall_confidence DECIMAL(3, 2) NOT NULL DEFAULT 0.50,

    -- 処理時間（ミリ秒）
    processing_time_ms INTEGER NOT NULL DEFAULT 0,

    -- メタデータ
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- タグ（検索用）
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- タイムスタンプ
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_judgment_history_org_id
    ON judgment_history(organization_id);
CREATE INDEX IF NOT EXISTS idx_judgment_history_user_id
    ON judgment_history(user_id);
CREATE INDEX IF NOT EXISTS idx_judgment_history_type
    ON judgment_history(organization_id, judgment_type);
CREATE INDEX IF NOT EXISTS idx_judgment_history_created_at
    ON judgment_history(organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_judgment_history_question
    ON judgment_history USING gin(to_tsvector('japanese', question));

-- GINインデックス（タグ検索用）
CREATE INDEX IF NOT EXISTS idx_judgment_history_tags
    ON judgment_history USING gin(tags jsonb_path_ops);


-- =============================================================================
-- 評価基準テンプレートテーブル
-- =============================================================================

-- 組織ごとの評価基準テンプレートを管理するテーブル
CREATE TABLE IF NOT EXISTS evaluation_criteria_templates (
    -- 主キー
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- 組織ID（テナント分離）
    organization_id VARCHAR(255) NOT NULL,

    -- 基準名
    name VARCHAR(255) NOT NULL,

    -- カテゴリ
    category VARCHAR(50) NOT NULL DEFAULT 'other',
    -- financial, revenue, technical, quality, time, cost, risk,
    -- skill_fit, culture_fit, growth_potential, etc.

    -- 重要度
    importance VARCHAR(50) NOT NULL DEFAULT 'medium',
    -- critical, high, medium, low, optional

    -- 重み（0-1）
    weight DECIMAL(3, 2) NOT NULL DEFAULT 0.60,

    -- 説明
    description TEXT NOT NULL DEFAULT '',

    -- 適用される判断タイプ（NULLの場合は全タイプに適用）
    judgment_type VARCHAR(50),

    -- スコアリングガイドライン（JSON）
    score_guidelines_json JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- 使用回数（人気度の指標）
    usage_count INTEGER NOT NULL DEFAULT 0,

    -- 最終使用日時
    last_used_at TIMESTAMPTZ,

    -- メタデータ
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- 有効フラグ
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    -- タイムスタンプ
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- 制約
    CONSTRAINT evaluation_criteria_unique_name UNIQUE (organization_id, name, judgment_type)
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_evaluation_criteria_org_id
    ON evaluation_criteria_templates(organization_id);
CREATE INDEX IF NOT EXISTS idx_evaluation_criteria_category
    ON evaluation_criteria_templates(organization_id, category);
CREATE INDEX IF NOT EXISTS idx_evaluation_criteria_type
    ON evaluation_criteria_templates(organization_id, judgment_type);
CREATE INDEX IF NOT EXISTS idx_evaluation_criteria_active
    ON evaluation_criteria_templates(organization_id, is_active)
    WHERE is_active = TRUE;


-- =============================================================================
-- 判断パターンテーブル
-- =============================================================================

-- よく使われる判断パターン（テンプレート）を管理するテーブル
CREATE TABLE IF NOT EXISTS judgment_patterns (
    -- 主キー
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- 組織ID（テナント分離）
    organization_id VARCHAR(255) NOT NULL,

    -- パターン名
    name VARCHAR(255) NOT NULL,

    -- 説明
    description TEXT NOT NULL DEFAULT '',

    -- 判断タイプ
    judgment_type VARCHAR(50) NOT NULL,

    -- デフォルトの選択肢（JSON配列）
    default_options_json JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- デフォルトの評価基準（JSON配列）
    default_criteria_json JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- デフォルトの組織価値観設定（JSON）
    default_values_json JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- 使用回数
    usage_count INTEGER NOT NULL DEFAULT 0,

    -- 最終使用日時
    last_used_at TIMESTAMPTZ,

    -- 有効フラグ
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    -- タイムスタンプ
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- 制約
    CONSTRAINT judgment_patterns_unique_name UNIQUE (organization_id, name)
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_judgment_patterns_org_id
    ON judgment_patterns(organization_id);
CREATE INDEX IF NOT EXISTS idx_judgment_patterns_type
    ON judgment_patterns(organization_id, judgment_type);


-- =============================================================================
-- 判断フィードバックテーブル
-- =============================================================================

-- ユーザーからの判断フィードバックを記録するテーブル（学習用）
CREATE TABLE IF NOT EXISTS judgment_feedback (
    -- 主キー
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- 組織ID（テナント分離）
    organization_id VARCHAR(255) NOT NULL,

    -- 元の判断履歴ID
    judgment_history_id UUID REFERENCES judgment_history(id),

    -- フィードバックタイプ
    feedback_type VARCHAR(50) NOT NULL,
    -- accepted: 推奨を受け入れた
    -- rejected: 推奨を拒否した
    -- modified: 別の選択肢を選んだ
    -- outcome_positive: 結果が良かった
    -- outcome_negative: 結果が悪かった

    -- システムの推奨
    system_recommendation VARCHAR(255),

    -- ユーザーの最終選択
    user_choice VARCHAR(255),

    -- フィードバックコメント
    comment TEXT,

    -- 評価スコア（1-5）
    rating INTEGER,

    -- タイムスタンプ
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_judgment_feedback_org_id
    ON judgment_feedback(organization_id);
CREATE INDEX IF NOT EXISTS idx_judgment_feedback_history_id
    ON judgment_feedback(judgment_history_id);
CREATE INDEX IF NOT EXISTS idx_judgment_feedback_type
    ON judgment_feedback(organization_id, feedback_type);


-- =============================================================================
-- Feature Flagの追加
-- =============================================================================

-- Feature Flagテーブルに新しいフラグを追加
INSERT INTO feature_flags (name, description, is_enabled, organization_id)
SELECT 'advanced_judgment_enabled', 'Phase 2J: 高度な判断層機能を有効化', FALSE, 'global'
WHERE NOT EXISTS (
    SELECT 1 FROM feature_flags WHERE name = 'advanced_judgment_enabled' AND organization_id = 'global'
);

INSERT INTO feature_flags (name, description, is_enabled, organization_id)
SELECT 'option_evaluation_enabled', 'Phase 2J: 選択肢評価機能を有効化', FALSE, 'global'
WHERE NOT EXISTS (
    SELECT 1 FROM feature_flags WHERE name = 'option_evaluation_enabled' AND organization_id = 'global'
);

INSERT INTO feature_flags (name, description, is_enabled, organization_id)
SELECT 'tradeoff_analysis_enabled', 'Phase 2J: トレードオフ分析機能を有効化', FALSE, 'global'
WHERE NOT EXISTS (
    SELECT 1 FROM feature_flags WHERE name = 'tradeoff_analysis_enabled' AND organization_id = 'global'
);

INSERT INTO feature_flags (name, description, is_enabled, organization_id)
SELECT 'risk_assessment_enabled', 'Phase 2J: リスク評価機能を有効化', FALSE, 'global'
WHERE NOT EXISTS (
    SELECT 1 FROM feature_flags WHERE name = 'risk_assessment_enabled' AND organization_id = 'global'
);

INSERT INTO feature_flags (name, description, is_enabled, organization_id)
SELECT 'consistency_check_enabled', 'Phase 2J: 整合性チェック機能を有効化', FALSE, 'global'
WHERE NOT EXISTS (
    SELECT 1 FROM feature_flags WHERE name = 'consistency_check_enabled' AND organization_id = 'global'
);


-- =============================================================================
-- RLS（Row Level Security）ポリシー
-- =============================================================================

-- judgment_history
ALTER TABLE judgment_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY judgment_history_isolation ON judgment_history
    USING (organization_id = current_setting('app.current_organization_id', true))
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true));

-- evaluation_criteria_templates
ALTER TABLE evaluation_criteria_templates ENABLE ROW LEVEL SECURITY;

CREATE POLICY evaluation_criteria_isolation ON evaluation_criteria_templates
    USING (organization_id = current_setting('app.current_organization_id', true))
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true));

-- judgment_patterns
ALTER TABLE judgment_patterns ENABLE ROW LEVEL SECURITY;

CREATE POLICY judgment_patterns_isolation ON judgment_patterns
    USING (organization_id = current_setting('app.current_organization_id', true))
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true));

-- judgment_feedback
ALTER TABLE judgment_feedback ENABLE ROW LEVEL SECURITY;

CREATE POLICY judgment_feedback_isolation ON judgment_feedback
    USING (organization_id = current_setting('app.current_organization_id', true))
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true));


-- =============================================================================
-- トリガー: updated_atの自動更新
-- =============================================================================

-- judgment_history
CREATE OR REPLACE TRIGGER update_judgment_history_updated_at
    BEFORE UPDATE ON judgment_history
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- evaluation_criteria_templates
CREATE OR REPLACE TRIGGER update_evaluation_criteria_updated_at
    BEFORE UPDATE ON evaluation_criteria_templates
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- judgment_patterns
CREATE OR REPLACE TRIGGER update_judgment_patterns_updated_at
    BEFORE UPDATE ON judgment_patterns
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();


-- =============================================================================
-- コメント
-- =============================================================================

COMMENT ON TABLE judgment_history IS 'Phase 2J: 判断履歴（整合性チェック用）';
COMMENT ON TABLE evaluation_criteria_templates IS 'Phase 2J: 評価基準テンプレート';
COMMENT ON TABLE judgment_patterns IS 'Phase 2J: 判断パターン（テンプレート）';
COMMENT ON TABLE judgment_feedback IS 'Phase 2J: 判断フィードバック（学習用）';

COMMENT ON COLUMN judgment_history.judgment_type IS '判断タイプ: comparison, ranking, best_choice, risk_assessment, go_no_go, candidate_evaluation, investment_decision';
COMMENT ON COLUMN judgment_history.outcome IS '判断結果: 後からユーザーが記録（成功/失敗等）';
COMMENT ON COLUMN judgment_history.outcome_score IS '結果評価スコア: 0-1、後から記録';

COMMENT ON COLUMN evaluation_criteria_templates.category IS '評価基準カテゴリ: financial, revenue, technical, quality, time, cost, risk, skill_fit, culture_fit, growth_potential';
COMMENT ON COLUMN evaluation_criteria_templates.importance IS '重要度: critical, high, medium, low, optional';

COMMENT ON COLUMN judgment_feedback.feedback_type IS 'フィードバックタイプ: accepted, rejected, modified, outcome_positive, outcome_negative';


-- =============================================================================
-- デフォルトデータの投入（ソウルシンクス用）
-- =============================================================================

-- プロジェクト評価用のデフォルト基準（ソウルシンクス用）
INSERT INTO evaluation_criteria_templates (
    organization_id, name, category, importance, weight, description, judgment_type
)
SELECT
    'org_soulsyncs',
    '収益性',
    'revenue',
    'high',
    0.80,
    '期待される収益・利益率',
    'go_no_go'
WHERE NOT EXISTS (
    SELECT 1 FROM evaluation_criteria_templates
    WHERE organization_id = 'org_soulsyncs' AND name = '収益性' AND judgment_type = 'go_no_go'
);

INSERT INTO evaluation_criteria_templates (
    organization_id, name, category, importance, weight, description, judgment_type
)
SELECT
    'org_soulsyncs',
    '戦略的適合性',
    'strategic',
    'high',
    0.80,
    '自社の戦略・方向性との適合',
    'go_no_go'
WHERE NOT EXISTS (
    SELECT 1 FROM evaluation_criteria_templates
    WHERE organization_id = 'org_soulsyncs' AND name = '戦略的適合性' AND judgment_type = 'go_no_go'
);

INSERT INTO evaluation_criteria_templates (
    organization_id, name, category, importance, weight, description, judgment_type
)
SELECT
    'org_soulsyncs',
    '技術的実現可能性',
    'technical',
    'critical',
    1.00,
    '自社の技術力で実現可能か',
    'go_no_go'
WHERE NOT EXISTS (
    SELECT 1 FROM evaluation_criteria_templates
    WHERE organization_id = 'org_soulsyncs' AND name = '技術的実現可能性' AND judgment_type = 'go_no_go'
);

INSERT INTO evaluation_criteria_templates (
    organization_id, name, category, importance, weight, description, judgment_type
)
SELECT
    'org_soulsyncs',
    'リスク',
    'risk',
    'high',
    0.80,
    'プロジェクトに伴うリスク（低いほど良い）',
    'go_no_go'
WHERE NOT EXISTS (
    SELECT 1 FROM evaluation_criteria_templates
    WHERE organization_id = 'org_soulsyncs' AND name = 'リスク' AND judgment_type = 'go_no_go'
);

-- 採用評価用のデフォルト基準（ソウルシンクス用）
INSERT INTO evaluation_criteria_templates (
    organization_id, name, category, importance, weight, description, judgment_type
)
SELECT
    'org_soulsyncs',
    'スキル適合',
    'skill_fit',
    'critical',
    1.00,
    '必要なスキル・経験を持っているか',
    'candidate_evaluation'
WHERE NOT EXISTS (
    SELECT 1 FROM evaluation_criteria_templates
    WHERE organization_id = 'org_soulsyncs' AND name = 'スキル適合' AND judgment_type = 'candidate_evaluation'
);

INSERT INTO evaluation_criteria_templates (
    organization_id, name, category, importance, weight, description, judgment_type
)
SELECT
    'org_soulsyncs',
    'カルチャーフィット',
    'culture_fit',
    'high',
    0.80,
    '組織のカルチャーに合うか',
    'candidate_evaluation'
WHERE NOT EXISTS (
    SELECT 1 FROM evaluation_criteria_templates
    WHERE organization_id = 'org_soulsyncs' AND name = 'カルチャーフィット' AND judgment_type = 'candidate_evaluation'
);

INSERT INTO evaluation_criteria_templates (
    organization_id, name, category, importance, weight, description, judgment_type
)
SELECT
    'org_soulsyncs',
    '成長可能性',
    'growth_potential',
    'high',
    0.80,
    '今後の成長が期待できるか',
    'candidate_evaluation'
WHERE NOT EXISTS (
    SELECT 1 FROM evaluation_criteria_templates
    WHERE organization_id = 'org_soulsyncs' AND name = '成長可能性' AND judgment_type = 'candidate_evaluation'
);
