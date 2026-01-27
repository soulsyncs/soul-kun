-- Phase 2G: 記憶の強化（Memory Enhancement）
-- 設計書: docs/17_brain_completion_roadmap.md セクション Phase 2G
--
-- エピソード記憶、知識グラフ、時系列記憶のためのテーブル定義

-- ============================================================================
-- 1. エピソード記憶テーブル
-- ============================================================================

CREATE TABLE IF NOT EXISTS brain_episodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    user_id VARCHAR(50),  -- NULLなら組織全体の記憶

    -- エピソード内容
    episode_type VARCHAR(30) NOT NULL DEFAULT 'interaction',
    summary TEXT NOT NULL,
    details JSONB DEFAULT '{}',

    -- 感情・重要度
    emotional_valence DECIMAL(3,2) DEFAULT 0.0,  -- -1.0〜1.0
    importance_score DECIMAL(3,2) DEFAULT 0.5,   -- 0.0〜1.0

    -- 検索用
    keywords TEXT[] DEFAULT '{}',
    embedding_id VARCHAR(100),  -- Pinecone等のベクトルID

    -- 想起管理
    recall_count INT DEFAULT 0,
    last_recalled_at TIMESTAMPTZ,
    decay_factor DECIMAL(3,2) DEFAULT 1.0,  -- 忘却係数

    -- 場所情報
    room_id VARCHAR(50),

    -- メタデータ
    occurred_at TIMESTAMPTZ DEFAULT NOW(),
    source VARCHAR(50),  -- conversation, system, batch等
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_brain_episodes_org_user
    ON brain_episodes(organization_id, user_id);
CREATE INDEX IF NOT EXISTS idx_brain_episodes_type
    ON brain_episodes(organization_id, episode_type);
CREATE INDEX IF NOT EXISTS idx_brain_episodes_keywords
    ON brain_episodes USING GIN(keywords);
CREATE INDEX IF NOT EXISTS idx_brain_episodes_occurred
    ON brain_episodes(organization_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_brain_episodes_importance
    ON brain_episodes(organization_id, importance_score DESC);

-- ============================================================================
-- 2. エピソード-エンティティ関連テーブル
-- ============================================================================

CREATE TABLE IF NOT EXISTS brain_episode_entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    episode_id UUID NOT NULL REFERENCES brain_episodes(id) ON DELETE CASCADE,

    -- エンティティ情報
    entity_type VARCHAR(30) NOT NULL,  -- person, task, goal, room等
    entity_id VARCHAR(100) NOT NULL,
    entity_name VARCHAR(200),
    relationship VARCHAR(30) NOT NULL DEFAULT 'involved',  -- involved, caused, affected等

    -- メタデータ
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_brain_episode_entities_episode
    ON brain_episode_entities(episode_id);
CREATE INDEX IF NOT EXISTS idx_brain_episode_entities_entity
    ON brain_episode_entities(organization_id, entity_type, entity_id);

-- ============================================================================
-- 3. 知識ノードテーブル
-- ============================================================================

CREATE TABLE IF NOT EXISTS brain_knowledge_nodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,

    -- ノード情報
    node_type VARCHAR(30) NOT NULL,  -- concept, person, organization等
    name VARCHAR(200) NOT NULL,
    description TEXT,
    aliases TEXT[] DEFAULT '{}',  -- 別名リスト

    -- 属性
    properties JSONB DEFAULT '{}',

    -- 重要度・活性度
    importance_score DECIMAL(3,2) DEFAULT 0.5,
    activation_level DECIMAL(3,2) DEFAULT 0.5,

    -- メタデータ
    source VARCHAR(30) NOT NULL DEFAULT 'learned',  -- learned, system, imported
    confidence DECIMAL(3,2) DEFAULT 0.8,
    evidence_count INT DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_brain_knowledge_nodes_org
    ON brain_knowledge_nodes(organization_id);
CREATE INDEX IF NOT EXISTS idx_brain_knowledge_nodes_type
    ON brain_knowledge_nodes(organization_id, node_type);
CREATE INDEX IF NOT EXISTS idx_brain_knowledge_nodes_name
    ON brain_knowledge_nodes(organization_id, LOWER(name));
CREATE INDEX IF NOT EXISTS idx_brain_knowledge_nodes_aliases
    ON brain_knowledge_nodes USING GIN(aliases);

-- ============================================================================
-- 4. 知識エッジテーブル
-- ============================================================================

CREATE TABLE IF NOT EXISTS brain_knowledge_edges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,

    -- エッジ情報
    source_node_id UUID NOT NULL REFERENCES brain_knowledge_nodes(id) ON DELETE CASCADE,
    target_node_id UUID NOT NULL REFERENCES brain_knowledge_nodes(id) ON DELETE CASCADE,
    edge_type VARCHAR(30) NOT NULL,  -- is_a, part_of, related_to等

    -- 属性
    description TEXT,
    properties JSONB DEFAULT '{}',
    weight DECIMAL(3,2) DEFAULT 1.0,  -- 関係の強さ

    -- 根拠
    evidence TEXT[] DEFAULT '{}',
    evidence_count INT DEFAULT 1,

    -- メタデータ
    source VARCHAR(30) NOT NULL DEFAULT 'learned',
    confidence DECIMAL(3,2) DEFAULT 0.8,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- 重複防止
    UNIQUE(organization_id, source_node_id, target_node_id, edge_type)
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_brain_knowledge_edges_source
    ON brain_knowledge_edges(source_node_id);
CREATE INDEX IF NOT EXISTS idx_brain_knowledge_edges_target
    ON brain_knowledge_edges(target_node_id);
CREATE INDEX IF NOT EXISTS idx_brain_knowledge_edges_type
    ON brain_knowledge_edges(organization_id, edge_type);

-- ============================================================================
-- 5. 時系列イベントテーブル
-- ============================================================================

CREATE TABLE IF NOT EXISTS brain_temporal_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    user_id VARCHAR(50),  -- NULLなら組織全体

    -- イベント情報
    event_type VARCHAR(30) NOT NULL,  -- metric, milestone, state_change等
    event_name VARCHAR(200) NOT NULL,
    event_value DECIMAL,  -- 数値イベントの場合
    event_data JSONB DEFAULT '{}',

    -- 関連情報
    related_entity_type VARCHAR(30),
    related_entity_id VARCHAR(100),
    related_episode_id UUID REFERENCES brain_episodes(id) ON DELETE SET NULL,

    -- タイムスタンプ
    event_at TIMESTAMPTZ NOT NULL,
    period_start TIMESTAMPTZ,
    period_end TIMESTAMPTZ,

    -- メタデータ
    source VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_brain_temporal_events_org_user
    ON brain_temporal_events(organization_id, user_id);
CREATE INDEX IF NOT EXISTS idx_brain_temporal_events_type
    ON brain_temporal_events(organization_id, event_type);
CREATE INDEX IF NOT EXISTS idx_brain_temporal_events_entity
    ON brain_temporal_events(organization_id, related_entity_type, related_entity_id);
CREATE INDEX IF NOT EXISTS idx_brain_temporal_events_time
    ON brain_temporal_events(organization_id, event_at DESC);

-- ============================================================================
-- 6. 時系列比較テーブル
-- ============================================================================

CREATE TABLE IF NOT EXISTS brain_temporal_comparisons (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,

    -- 比較情報
    comparison_type VARCHAR(30) NOT NULL,  -- trend, improvement, regression等
    subject_type VARCHAR(30) NOT NULL,
    subject_id VARCHAR(100) NOT NULL,
    subject_name VARCHAR(200),

    -- 比較対象イベント
    baseline_event_id UUID REFERENCES brain_temporal_events(id) ON DELETE SET NULL,
    current_event_id UUID REFERENCES brain_temporal_events(id) ON DELETE SET NULL,

    -- 比較結果
    baseline_value DECIMAL,
    current_value DECIMAL,
    change_value DECIMAL,
    change_percent DECIMAL,
    trend VARCHAR(30),  -- improving, declining, stable

    -- 分析
    analysis_summary TEXT,
    analysis_details JSONB DEFAULT '{}',
    confidence DECIMAL(3,2) DEFAULT 0.8,

    -- メタデータ
    period_label VARCHAR(100),  -- 「先週と今週」「前月と今月」等
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_brain_temporal_comparisons_subject
    ON brain_temporal_comparisons(organization_id, subject_type, subject_id);
CREATE INDEX IF NOT EXISTS idx_brain_temporal_comparisons_trend
    ON brain_temporal_comparisons(organization_id, trend);

-- ============================================================================
-- 7. 記憶統合ログテーブル
-- ============================================================================

CREATE TABLE IF NOT EXISTS brain_memory_consolidations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,

    -- 統合情報
    consolidation_type VARCHAR(30) NOT NULL,  -- merge, summarize, forget, promote
    action VARCHAR(30) NOT NULL,  -- executed, skipped, deferred

    -- 対象
    source_type VARCHAR(30) NOT NULL,  -- episode, knowledge_node, pattern
    source_ids UUID[] NOT NULL,
    target_id UUID,

    -- 結果
    summary TEXT,
    details JSONB DEFAULT '{}',
    episodes_processed INT DEFAULT 0,
    episodes_merged INT DEFAULT 0,
    episodes_forgotten INT DEFAULT 0,

    -- メタデータ
    triggered_by VARCHAR(50),  -- batch, manual, auto
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_brain_memory_consolidations_org
    ON brain_memory_consolidations(organization_id);
CREATE INDEX IF NOT EXISTS idx_brain_memory_consolidations_type
    ON brain_memory_consolidations(organization_id, consolidation_type);
CREATE INDEX IF NOT EXISTS idx_brain_memory_consolidations_created
    ON brain_memory_consolidations(organization_id, created_at DESC);

-- ============================================================================
-- トリガー: updated_at自動更新
-- ============================================================================

CREATE OR REPLACE FUNCTION update_brain_memory_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- brain_episodes
DROP TRIGGER IF EXISTS trigger_brain_episodes_updated_at ON brain_episodes;
CREATE TRIGGER trigger_brain_episodes_updated_at
    BEFORE UPDATE ON brain_episodes
    FOR EACH ROW
    EXECUTE FUNCTION update_brain_memory_updated_at();

-- brain_knowledge_nodes
DROP TRIGGER IF EXISTS trigger_brain_knowledge_nodes_updated_at ON brain_knowledge_nodes;
CREATE TRIGGER trigger_brain_knowledge_nodes_updated_at
    BEFORE UPDATE ON brain_knowledge_nodes
    FOR EACH ROW
    EXECUTE FUNCTION update_brain_memory_updated_at();

-- brain_knowledge_edges
DROP TRIGGER IF EXISTS trigger_brain_knowledge_edges_updated_at ON brain_knowledge_edges;
CREATE TRIGGER trigger_brain_knowledge_edges_updated_at
    BEFORE UPDATE ON brain_knowledge_edges
    FOR EACH ROW
    EXECUTE FUNCTION update_brain_memory_updated_at();

-- ============================================================================
-- コメント
-- ============================================================================

COMMENT ON TABLE brain_episodes IS 'Phase 2G: エピソード記憶（出来事の記憶）';
COMMENT ON TABLE brain_episode_entities IS 'Phase 2G: エピソードと関連エンティティの関係';
COMMENT ON TABLE brain_knowledge_nodes IS 'Phase 2G: 知識グラフのノード（概念、エンティティ）';
COMMENT ON TABLE brain_knowledge_edges IS 'Phase 2G: 知識グラフのエッジ（関係）';
COMMENT ON TABLE brain_temporal_events IS 'Phase 2G: 時系列イベント';
COMMENT ON TABLE brain_temporal_comparisons IS 'Phase 2G: 時系列比較結果';
COMMENT ON TABLE brain_memory_consolidations IS 'Phase 2G: 記憶統合ログ';
