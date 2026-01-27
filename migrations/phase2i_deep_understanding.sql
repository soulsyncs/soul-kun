-- Phase 2I: 理解力強化（Deep Understanding）DBマイグレーション
-- 設計書: docs/17_brain_completion_roadmap.md セクション17.3 Phase 2I
-- Author: Claude Opus 4.5
-- Created: 2026-01-27

-- =============================================================================
-- 組織固有語彙テーブル
-- =============================================================================

-- 組織固有の語彙・用語を管理するテーブル
CREATE TABLE IF NOT EXISTS organization_vocabulary (
    -- 主キー
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- 組織ID（テナント分離）
    organization_id VARCHAR(255) NOT NULL,

    -- 語彙
    term VARCHAR(255) NOT NULL,

    -- カテゴリ
    category VARCHAR(50) NOT NULL DEFAULT 'idiom',
    -- project_name, product_name, abbreviation, team_name,
    -- role_name, event_name, system_name, idiom

    -- 意味・説明
    meaning TEXT NOT NULL DEFAULT '',

    -- エイリアス（別の呼び方）
    aliases JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- 関連語彙
    related_terms JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- 使用例
    usage_examples JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- 出現回数（学習用）
    occurrence_count INTEGER NOT NULL DEFAULT 0,

    -- 最終使用日時
    last_used_at TIMESTAMPTZ,

    -- メタデータ
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- アクティブフラグ
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    -- タイムスタンプ
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- 制約
    CONSTRAINT organization_vocabulary_unique_term UNIQUE (organization_id, term)
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_organization_vocabulary_org_id
    ON organization_vocabulary(organization_id);
CREATE INDEX IF NOT EXISTS idx_organization_vocabulary_category
    ON organization_vocabulary(category);
CREATE INDEX IF NOT EXISTS idx_organization_vocabulary_term
    ON organization_vocabulary(term);
CREATE INDEX IF NOT EXISTS idx_organization_vocabulary_active
    ON organization_vocabulary(organization_id, is_active)
    WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_organization_vocabulary_occurrence
    ON organization_vocabulary(organization_id, occurrence_count DESC);

-- GINインデックス（エイリアス検索用）
CREATE INDEX IF NOT EXISTS idx_organization_vocabulary_aliases
    ON organization_vocabulary USING gin(aliases jsonb_path_ops);


-- =============================================================================
-- 深い理解ログテーブル
-- =============================================================================

-- 深い理解の処理ログを記録するテーブル（分析・改善用）
CREATE TABLE IF NOT EXISTS deep_understanding_logs (
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

    -- 元のメッセージ
    original_message TEXT NOT NULL,

    -- 強化されたメッセージ
    enhanced_message TEXT,

    -- 意図推測結果（JSON）
    intent_inference JSONB DEFAULT '{}'::jsonb,

    -- 組織文脈結果（JSON）
    organization_context JSONB DEFAULT '{}'::jsonb,

    -- 感情読み取り結果（JSON）
    emotion_reading JSONB DEFAULT '{}'::jsonb,

    -- 復元された文脈（JSON）
    recovered_context JSONB DEFAULT '{}'::jsonb,

    -- 全体の信頼度
    overall_confidence DECIMAL(3, 2) NOT NULL DEFAULT 0.00,

    -- 確認が必要だったか
    needs_confirmation BOOLEAN NOT NULL DEFAULT FALSE,

    -- 確認理由
    confirmation_reason TEXT,

    -- 処理時間（ミリ秒）
    processing_time_ms INTEGER NOT NULL DEFAULT 0,

    -- エラー情報
    errors JSONB DEFAULT '[]'::jsonb,

    -- 警告情報
    warnings JSONB DEFAULT '[]'::jsonb,

    -- タイムスタンプ
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_deep_understanding_logs_org_id
    ON deep_understanding_logs(organization_id);
CREATE INDEX IF NOT EXISTS idx_deep_understanding_logs_user_id
    ON deep_understanding_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_deep_understanding_logs_created_at
    ON deep_understanding_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_deep_understanding_logs_confidence
    ON deep_understanding_logs(organization_id, overall_confidence);

-- パーティション用（将来的に必要な場合）
CREATE INDEX IF NOT EXISTS idx_deep_understanding_logs_created_month
    ON deep_understanding_logs(organization_id, DATE_TRUNC('month', created_at));


-- =============================================================================
-- 意図解決フィードバックテーブル
-- =============================================================================

-- ユーザーが意図解決を承認/修正した際のフィードバックを記録
CREATE TABLE IF NOT EXISTS intent_resolution_feedback (
    -- 主キー
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- 組織ID（テナント分離）
    organization_id VARCHAR(255) NOT NULL,

    -- 元のログID
    understanding_log_id UUID REFERENCES deep_understanding_logs(id),

    -- 元の表現
    original_expression VARCHAR(500) NOT NULL,

    -- システムが推測した解決
    system_resolution VARCHAR(500),

    -- ユーザーが選択/修正した解決
    user_resolution VARCHAR(500) NOT NULL,

    -- フィードバックタイプ
    feedback_type VARCHAR(50) NOT NULL,
    -- approved: 承認, corrected: 修正, rejected: 拒否

    -- 解決タイプ
    resolution_type VARCHAR(50) NOT NULL,
    -- pronoun_reference, ellipsis_reference, context_dependent, organization_idiom

    -- タイムスタンプ
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_intent_resolution_feedback_org_id
    ON intent_resolution_feedback(organization_id);
CREATE INDEX IF NOT EXISTS idx_intent_resolution_feedback_log_id
    ON intent_resolution_feedback(understanding_log_id);
CREATE INDEX IF NOT EXISTS idx_intent_resolution_feedback_type
    ON intent_resolution_feedback(organization_id, resolution_type);


-- =============================================================================
-- 感情パターンテーブル
-- =============================================================================

-- ユーザーごとの感情パターンを学習するテーブル
CREATE TABLE IF NOT EXISTS emotion_patterns (
    -- 主キー
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- 組織ID（テナント分離）
    organization_id VARCHAR(255) NOT NULL,

    -- ChatWorkアカウントID（ユーザー識別）
    chatwork_account_id VARCHAR(255) NOT NULL,

    -- 感情カテゴリ
    emotion_category VARCHAR(50) NOT NULL,
    -- happy, excited, grateful, frustrated, anxious, angry, stressed, etc.

    -- キーワード（このユーザーがこの感情時に使う表現）
    keywords JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- 出現回数
    occurrence_count INTEGER NOT NULL DEFAULT 1,

    -- 最終検出日時
    last_detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- タイムスタンプ
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- 制約
    CONSTRAINT emotion_patterns_unique UNIQUE (organization_id, chatwork_account_id, emotion_category)
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_emotion_patterns_org_user
    ON emotion_patterns(organization_id, chatwork_account_id);


-- =============================================================================
-- Feature Flagの追加
-- =============================================================================

-- Feature Flagテーブルに新しいフラグを追加
INSERT INTO feature_flags (name, description, is_enabled, organization_id)
SELECT 'deep_understanding_enabled', 'Phase 2I: 深い理解層機能を有効化', FALSE, 'global'
WHERE NOT EXISTS (
    SELECT 1 FROM feature_flags WHERE name = 'deep_understanding_enabled' AND organization_id = 'global'
);

INSERT INTO feature_flags (name, description, is_enabled, organization_id)
SELECT 'implicit_intent_enabled', 'Phase 2I: 暗黙の意図推測機能を有効化', FALSE, 'global'
WHERE NOT EXISTS (
    SELECT 1 FROM feature_flags WHERE name = 'implicit_intent_enabled' AND organization_id = 'global'
);

INSERT INTO feature_flags (name, description, is_enabled, organization_id)
SELECT 'organization_context_enabled', 'Phase 2I: 組織文脈理解機能を有効化', FALSE, 'global'
WHERE NOT EXISTS (
    SELECT 1 FROM feature_flags WHERE name = 'organization_context_enabled' AND organization_id = 'global'
);

INSERT INTO feature_flags (name, description, is_enabled, organization_id)
SELECT 'emotion_reading_enabled', 'Phase 2I: 感情読み取り機能を有効化', FALSE, 'global'
WHERE NOT EXISTS (
    SELECT 1 FROM feature_flags WHERE name = 'emotion_reading_enabled' AND organization_id = 'global'
);

INSERT INTO feature_flags (name, description, is_enabled, organization_id)
SELECT 'vocabulary_learning_enabled', 'Phase 2I: 語彙学習機能を有効化', FALSE, 'global'
WHERE NOT EXISTS (
    SELECT 1 FROM feature_flags WHERE name = 'vocabulary_learning_enabled' AND organization_id = 'global'
);


-- =============================================================================
-- RLS（Row Level Security）ポリシー
-- =============================================================================

-- organization_vocabulary
ALTER TABLE organization_vocabulary ENABLE ROW LEVEL SECURITY;

CREATE POLICY organization_vocabulary_isolation ON organization_vocabulary
    USING (organization_id = current_setting('app.current_organization_id', true))
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true));

-- deep_understanding_logs
ALTER TABLE deep_understanding_logs ENABLE ROW LEVEL SECURITY;

CREATE POLICY deep_understanding_logs_isolation ON deep_understanding_logs
    USING (organization_id = current_setting('app.current_organization_id', true))
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true));

-- intent_resolution_feedback
ALTER TABLE intent_resolution_feedback ENABLE ROW LEVEL SECURITY;

CREATE POLICY intent_resolution_feedback_isolation ON intent_resolution_feedback
    USING (organization_id = current_setting('app.current_organization_id', true))
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true));

-- emotion_patterns
ALTER TABLE emotion_patterns ENABLE ROW LEVEL SECURITY;

CREATE POLICY emotion_patterns_isolation ON emotion_patterns
    USING (organization_id = current_setting('app.current_organization_id', true))
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true));


-- =============================================================================
-- コメント
-- =============================================================================

COMMENT ON TABLE organization_vocabulary IS 'Phase 2I: 組織固有の語彙・用語を管理するテーブル';
COMMENT ON TABLE deep_understanding_logs IS 'Phase 2I: 深い理解層の処理ログ（分析・改善用）';
COMMENT ON TABLE intent_resolution_feedback IS 'Phase 2I: 意図解決に対するユーザーフィードバック（学習用）';
COMMENT ON TABLE emotion_patterns IS 'Phase 2I: ユーザーごとの感情パターン（学習用）';

COMMENT ON COLUMN organization_vocabulary.category IS '語彙カテゴリ: project_name, product_name, abbreviation, team_name, role_name, event_name, system_name, idiom';
COMMENT ON COLUMN intent_resolution_feedback.feedback_type IS 'フィードバックタイプ: approved(承認), corrected(修正), rejected(拒否)';
COMMENT ON COLUMN emotion_patterns.emotion_category IS '感情カテゴリ: happy, excited, grateful, frustrated, anxious, angry, stressed, confused, etc.';
