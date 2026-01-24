-- ============================================================
-- Phase 2 B: 覚える能力（Memory Framework）
-- 作成日: 2026-01-24
-- 作成者: Claude Code
-- ============================================================

-- ============================================================
-- B1: conversation_summaries（会話サマリー記憶）
-- ============================================================

CREATE TABLE IF NOT EXISTS conversation_summaries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- サマリー内容
    summary_text TEXT NOT NULL,
    key_topics TEXT[] DEFAULT '{}',
    mentioned_persons TEXT[] DEFAULT '{}',
    mentioned_tasks TEXT[] DEFAULT '{}',

    -- 期間
    conversation_start TIMESTAMPTZ NOT NULL,
    conversation_end TIMESTAMPTZ NOT NULL,
    message_count INT NOT NULL,

    -- メタデータ
    room_id VARCHAR(50),
    generated_by VARCHAR(50) DEFAULT 'llm',

    -- 機密区分
    classification VARCHAR(20) DEFAULT 'internal',

    -- 監査フィールド
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 制約
    CONSTRAINT check_cs_classification CHECK (classification IN ('public', 'internal', 'confidential', 'restricted'))
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_conv_summaries_org_user ON conversation_summaries(organization_id, user_id);
CREATE INDEX IF NOT EXISTS idx_conv_summaries_created ON conversation_summaries(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_conv_summaries_user_time ON conversation_summaries(user_id, conversation_end DESC);

COMMENT ON TABLE conversation_summaries IS 'Phase 2 B1: 会話サマリー記憶。長い会話をサマリー化して保存';
COMMENT ON COLUMN conversation_summaries.key_topics IS '主要トピック（配列）';
COMMENT ON COLUMN conversation_summaries.generated_by IS '生成方法: llm / manual';

-- ============================================================
-- B2: user_preferences（ユーザー嗜好学習）
-- ============================================================

CREATE TABLE IF NOT EXISTS user_preferences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- 嗜好データ
    preference_type VARCHAR(50) NOT NULL,
    preference_key VARCHAR(100) NOT NULL,
    preference_value JSONB NOT NULL,

    -- 学習情報
    learned_from VARCHAR(50) DEFAULT 'auto',
    confidence DECIMAL(4,3) DEFAULT 0.5,
    sample_count INT DEFAULT 1,

    -- 機密区分
    classification VARCHAR(20) DEFAULT 'internal',

    -- 監査フィールド
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 制約
    UNIQUE(organization_id, user_id, preference_type, preference_key),
    CONSTRAINT check_up_classification CHECK (classification IN ('public', 'internal', 'confidential', 'restricted')),
    CONSTRAINT check_up_confidence CHECK (confidence >= 0 AND confidence <= 1),
    CONSTRAINT check_up_pref_type CHECK (preference_type IN ('response_style', 'feature_usage', 'communication', 'schedule', 'emotion_trend'))
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_user_prefs_org_user ON user_preferences(organization_id, user_id);
CREATE INDEX IF NOT EXISTS idx_user_prefs_type ON user_preferences(preference_type);
CREATE INDEX IF NOT EXISTS idx_user_prefs_confidence ON user_preferences(confidence DESC) WHERE confidence >= 0.7;

COMMENT ON TABLE user_preferences IS 'Phase 2 B2: ユーザー嗜好学習。ユーザーごとの好みを自動学習';
COMMENT ON COLUMN user_preferences.preference_type IS '嗜好タイプ: response_style, feature_usage, communication, schedule, emotion_trend';
COMMENT ON COLUMN user_preferences.learned_from IS '学習元: auto（自動）, explicit（明示）, a4_emotion（A4連携）';
COMMENT ON COLUMN user_preferences.confidence IS '信頼度 0.0-1.0';

-- ============================================================
-- B3: organization_auto_knowledge（組織知識自動蓄積）
-- ============================================================

CREATE TABLE IF NOT EXISTS organization_auto_knowledge (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- 元データ（A1パターン検出連携）
    source_insight_id UUID REFERENCES soulkun_insights(id) ON DELETE SET NULL,
    source_pattern_id UUID REFERENCES question_patterns(id) ON DELETE SET NULL,

    -- 知識データ
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    category VARCHAR(50),
    keywords TEXT[] DEFAULT '{}',

    -- ステータス
    status VARCHAR(20) DEFAULT 'draft',
    approved_at TIMESTAMPTZ,
    approved_by UUID REFERENCES users(id) ON DELETE SET NULL,
    rejection_reason TEXT,

    -- Phase 3連携
    synced_to_phase3 BOOLEAN DEFAULT FALSE,
    phase3_document_id UUID,

    -- 品質スコア
    usage_count INT DEFAULT 0,
    helpful_count INT DEFAULT 0,
    quality_score DECIMAL(4,3),

    -- 機密区分
    classification VARCHAR(20) DEFAULT 'internal',

    -- 監査フィールド
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 制約
    CONSTRAINT check_oak_status CHECK (status IN ('draft', 'approved', 'rejected', 'archived')),
    CONSTRAINT check_oak_classification CHECK (classification IN ('public', 'internal', 'confidential', 'restricted'))
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_auto_knowledge_org ON organization_auto_knowledge(organization_id);
CREATE INDEX IF NOT EXISTS idx_auto_knowledge_status ON organization_auto_knowledge(status) WHERE status IN ('draft', 'approved');
CREATE INDEX IF NOT EXISTS idx_auto_knowledge_source_insight ON organization_auto_knowledge(source_insight_id) WHERE source_insight_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_auto_knowledge_source_pattern ON organization_auto_knowledge(source_pattern_id) WHERE source_pattern_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_auto_knowledge_keywords ON organization_auto_knowledge USING GIN(keywords);

COMMENT ON TABLE organization_auto_knowledge IS 'Phase 2 B3: 組織知識自動蓄積。A1パターン検出と連携してFAQを自動生成';
COMMENT ON COLUMN organization_auto_knowledge.status IS 'ステータス: draft（下書き）, approved（承認済み）, rejected（却下）, archived（アーカイブ）';
COMMENT ON COLUMN organization_auto_knowledge.quality_score IS '品質スコア: usage_count と helpful_count から算出';

-- ============================================================
-- B4: conversation_index（会話検索インデックス）
-- ============================================================

CREATE TABLE IF NOT EXISTS conversation_index (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- 会話データ
    message_id VARCHAR(100),
    room_id VARCHAR(50),
    message_text TEXT NOT NULL,
    message_type VARCHAR(20) NOT NULL,

    -- 検索用データ
    keywords TEXT[] DEFAULT '{}',
    entities JSONB DEFAULT '{}',
    embedding_id VARCHAR(100),

    -- タイムスタンプ
    message_time TIMESTAMPTZ NOT NULL,

    -- 機密区分
    classification VARCHAR(20) DEFAULT 'internal',

    -- 監査フィールド
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 制約
    CONSTRAINT check_ci_message_type CHECK (message_type IN ('user', 'assistant')),
    CONSTRAINT check_ci_classification CHECK (classification IN ('public', 'internal', 'confidential', 'restricted'))
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_conv_index_org_user ON conversation_index(organization_id, user_id);
CREATE INDEX IF NOT EXISTS idx_conv_index_time ON conversation_index(message_time DESC);
CREATE INDEX IF NOT EXISTS idx_conv_index_keywords ON conversation_index USING GIN(keywords);
CREATE INDEX IF NOT EXISTS idx_conv_index_room ON conversation_index(room_id, message_time DESC);
CREATE INDEX IF NOT EXISTS idx_conv_index_message_id ON conversation_index(message_id) WHERE message_id IS NOT NULL;

COMMENT ON TABLE conversation_index IS 'Phase 2 B4: 会話検索インデックス。過去の会話を検索可能に';
COMMENT ON COLUMN conversation_index.message_type IS 'メッセージタイプ: user（ユーザー発言）, assistant（ソウルくん発言）';
COMMENT ON COLUMN conversation_index.embedding_id IS 'Pineconeベクトル参照（将来用）';

-- ============================================================
-- 完了メッセージ
-- ============================================================

DO $$
BEGIN
    RAISE NOTICE '✅ Phase 2 B 覚える能力 テーブル作成完了';
    RAISE NOTICE '  - conversation_summaries: B1 会話サマリー記憶';
    RAISE NOTICE '  - user_preferences: B2 ユーザー嗜好学習';
    RAISE NOTICE '  - organization_auto_knowledge: B3 組織知識自動蓄積';
    RAISE NOTICE '  - conversation_index: B4 会話検索';
END $$;
