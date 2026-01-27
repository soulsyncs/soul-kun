-- Phase 2H: 自己認識（Self-Awareness）マイグレーション
-- 設計書: docs/17_brain_completion_roadmap.md セクション Phase 2H
--
-- 能力の自己評価、限界の認識、確信度判定、改善追跡のためのテーブル

-- ============================================================================
-- 1. brain_ability_scores - 能力スコア
-- ============================================================================

CREATE TABLE IF NOT EXISTS brain_ability_scores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id VARCHAR(255) NOT NULL,

    -- 能力情報
    category VARCHAR(50) NOT NULL,  -- ability category (task_management, knowledge_search, etc.)
    score DECIMAL(3,2) NOT NULL DEFAULT 0.50,  -- 0.00-1.00

    -- 統計情報
    sample_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,

    -- 時系列
    last_success_at TIMESTAMP WITH TIME ZONE,
    last_failure_at TIMESTAMP WITH TIME ZONE,
    last_updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- メタデータ
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- ユニーク制約（組織×カテゴリで1レコード）
    CONSTRAINT uq_ability_scores_org_category UNIQUE (organization_id, category),

    -- スコア範囲チェック
    CONSTRAINT chk_ability_score_range CHECK (score >= 0.00 AND score <= 1.00)
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_ability_scores_org ON brain_ability_scores(organization_id);
CREATE INDEX IF NOT EXISTS idx_ability_scores_category ON brain_ability_scores(category);
CREATE INDEX IF NOT EXISTS idx_ability_scores_score ON brain_ability_scores(score);

-- コメント
COMMENT ON TABLE brain_ability_scores IS '能力スコア - 各カテゴリの能力値を追跡';
COMMENT ON COLUMN brain_ability_scores.category IS '能力カテゴリ: task_management, knowledge_search, goal_support, communication, pattern_detection, emotion_analysis, bottleneck_detection, learning_from_feedback, outcome_learning, ceo_teaching, personalization, context_understanding, tone_adaptation, general';
COMMENT ON COLUMN brain_ability_scores.score IS '能力スコア: 0.0-0.2=unknown, 0.2-0.4=novice, 0.4-0.6=developing, 0.6-0.8=proficient, 0.8-1.0=expert';


-- ============================================================================
-- 2. brain_limitations - 限界情報
-- ============================================================================

CREATE TABLE IF NOT EXISTS brain_limitations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id VARCHAR(255) NOT NULL,

    -- 限界情報
    limitation_type VARCHAR(50) NOT NULL,  -- knowledge_gap, outdated_info, domain_specific, etc.
    description TEXT NOT NULL,
    keywords TEXT[],  -- 関連キーワード配列

    -- 発生状況
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    first_occurred_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_occurred_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- 解決状況
    is_resolved BOOLEAN NOT NULL DEFAULT FALSE,
    resolved_at TIMESTAMP WITH TIME ZONE,
    resolution_note TEXT,

    -- メタデータ
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_limitations_org ON brain_limitations(organization_id);
CREATE INDEX IF NOT EXISTS idx_limitations_type ON brain_limitations(limitation_type);
CREATE INDEX IF NOT EXISTS idx_limitations_resolved ON brain_limitations(is_resolved);
CREATE INDEX IF NOT EXISTS idx_limitations_occurrence ON brain_limitations(occurrence_count DESC);

-- コメント
COMMENT ON TABLE brain_limitations IS '限界情報 - ソウルくんが苦手/できないことを記録';
COMMENT ON COLUMN brain_limitations.limitation_type IS '限界タイプ: knowledge_gap, outdated_info, domain_specific, capability_limit, permission_limit, resource_limit, uncertainty, ambiguity, ethical_concern, missing_context, conflicting_info';


-- ============================================================================
-- 3. brain_improvement_logs - 改善ログ
-- ============================================================================

CREATE TABLE IF NOT EXISTS brain_improvement_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id VARCHAR(255) NOT NULL,

    -- 改善情報
    improvement_type VARCHAR(50) NOT NULL,  -- accuracy, speed, coverage, consistency, personalization
    category VARCHAR(50),  -- 対象の能力カテゴリ（NULL可）

    -- スコア変化
    previous_score DECIMAL(3,2) NOT NULL,
    current_score DECIMAL(3,2) NOT NULL,

    -- 要因分析
    trigger_event TEXT,  -- 改善のきっかけ
    contributing_factors TEXT[],  -- 改善に寄与した要因

    -- 関連情報
    related_interaction_ids UUID[],  -- 関連するインタラクションID

    -- メタデータ
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_improvement_logs_org ON brain_improvement_logs(organization_id);
CREATE INDEX IF NOT EXISTS idx_improvement_logs_type ON brain_improvement_logs(improvement_type);
CREATE INDEX IF NOT EXISTS idx_improvement_logs_category ON brain_improvement_logs(category);
CREATE INDEX IF NOT EXISTS idx_improvement_logs_recorded_at ON brain_improvement_logs(recorded_at DESC);

-- コメント
COMMENT ON TABLE brain_improvement_logs IS '改善ログ - 能力向上/悪化の履歴を追跡';
COMMENT ON COLUMN brain_improvement_logs.improvement_type IS '改善タイプ: accuracy, speed, coverage, consistency, personalization';


-- ============================================================================
-- 4. brain_self_diagnoses - 自己診断結果
-- ============================================================================

CREATE TABLE IF NOT EXISTS brain_self_diagnoses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id VARCHAR(255) NOT NULL,

    -- 診断タイプ
    diagnosis_type VARCHAR(20) NOT NULL,  -- daily, weekly, monthly, on_demand

    -- 診断期間
    period_start TIMESTAMP WITH TIME ZONE NOT NULL,
    period_end TIMESTAMP WITH TIME ZONE NOT NULL,

    -- 統計情報
    total_interactions INTEGER NOT NULL DEFAULT 0,
    successful_interactions INTEGER NOT NULL DEFAULT 0,
    failed_interactions INTEGER NOT NULL DEFAULT 0,
    escalated_interactions INTEGER NOT NULL DEFAULT 0,

    -- スコア
    overall_score DECIMAL(3,2) NOT NULL DEFAULT 0.50,

    -- 能力別スコア（JSONB）
    ability_scores JSONB,  -- {"task_management": 0.7, "knowledge_search": 0.6, ...}

    -- 改善点
    identified_weaknesses TEXT[],
    recommended_improvements TEXT[],

    -- 限界認識
    newly_identified_limitations UUID[],  -- brain_limitationsへの参照

    -- メタデータ
    diagnosed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_self_diagnoses_org ON brain_self_diagnoses(organization_id);
CREATE INDEX IF NOT EXISTS idx_self_diagnoses_type ON brain_self_diagnoses(diagnosis_type);
CREATE INDEX IF NOT EXISTS idx_self_diagnoses_diagnosed_at ON brain_self_diagnoses(diagnosed_at DESC);

-- コメント
COMMENT ON TABLE brain_self_diagnoses IS '自己診断結果 - 定期的な自己診断の結果を保存';
COMMENT ON COLUMN brain_self_diagnoses.diagnosis_type IS '診断タイプ: daily, weekly, monthly, on_demand';
COMMENT ON COLUMN brain_self_diagnoses.ability_scores IS '能力別スコア（JSON形式）';


-- ============================================================================
-- 5. brain_confidence_logs - 確信度ログ（任意、分析用）
-- ============================================================================

CREATE TABLE IF NOT EXISTS brain_confidence_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id VARCHAR(255) NOT NULL,

    -- コンテキスト
    interaction_id UUID,  -- 関連するインタラクションID
    category VARCHAR(50) NOT NULL,  -- 能力カテゴリ

    -- 確信度スコア
    knowledge_confidence DECIMAL(3,2) NOT NULL,
    context_confidence DECIMAL(3,2) NOT NULL,
    historical_accuracy DECIMAL(3,2) NOT NULL,
    overall_confidence DECIMAL(3,2) NOT NULL,

    -- 判定結果
    confidence_level VARCHAR(20) NOT NULL,  -- high, medium, low, very_low
    needs_confirmation BOOLEAN NOT NULL DEFAULT FALSE,
    needs_escalation BOOLEAN NOT NULL DEFAULT FALSE,

    -- 不確実性要因
    uncertainty_factors TEXT[],

    -- メタデータ
    assessed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_confidence_logs_org ON brain_confidence_logs(organization_id);
CREATE INDEX IF NOT EXISTS idx_confidence_logs_category ON brain_confidence_logs(category);
CREATE INDEX IF NOT EXISTS idx_confidence_logs_level ON brain_confidence_logs(confidence_level);
CREATE INDEX IF NOT EXISTS idx_confidence_logs_escalation ON brain_confidence_logs(needs_escalation);
CREATE INDEX IF NOT EXISTS idx_confidence_logs_assessed_at ON brain_confidence_logs(assessed_at DESC);

-- コメント
COMMENT ON TABLE brain_confidence_logs IS '確信度ログ - 各応答時の確信度評価を記録（分析用）';
COMMENT ON COLUMN brain_confidence_logs.confidence_level IS '確信度レベル: high (0.8-1.0), medium (0.5-0.8), low (0.3-0.5), very_low (0-0.3)';


-- ============================================================================
-- 更新トリガー
-- ============================================================================

-- brain_ability_scores の updated_at 自動更新
DROP TRIGGER IF EXISTS trigger_ability_scores_updated_at ON brain_ability_scores;
CREATE TRIGGER trigger_ability_scores_updated_at
    BEFORE UPDATE ON brain_ability_scores
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- brain_limitations の updated_at 自動更新
DROP TRIGGER IF EXISTS trigger_limitations_updated_at ON brain_limitations;
CREATE TRIGGER trigger_limitations_updated_at
    BEFORE UPDATE ON brain_limitations
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();


-- ============================================================================
-- 初期データ投入（ソウルシンクス組織用のデフォルト能力スコア）
-- ============================================================================

-- 注意: organization_id はソウルシンクスの実際のIDに変更が必要
-- INSERT INTO brain_ability_scores (organization_id, category, score)
-- VALUES
--     ('soulsyncs', 'task_management', 0.70),
--     ('soulsyncs', 'knowledge_search', 0.60),
--     ('soulsyncs', 'goal_support', 0.65),
--     ('soulsyncs', 'communication', 0.70),
--     ('soulsyncs', 'pattern_detection', 0.50),
--     ('soulsyncs', 'emotion_analysis', 0.50),
--     ('soulsyncs', 'bottleneck_detection', 0.50),
--     ('soulsyncs', 'learning_from_feedback', 0.60),
--     ('soulsyncs', 'outcome_learning', 0.50),
--     ('soulsyncs', 'ceo_teaching', 0.60),
--     ('soulsyncs', 'personalization', 0.50),
--     ('soulsyncs', 'context_understanding', 0.55),
--     ('soulsyncs', 'tone_adaptation', 0.60),
--     ('soulsyncs', 'general', 0.50)
-- ON CONFLICT (organization_id, category) DO NOTHING;
