-- ============================================================================
-- Brain Organization Graph Tables
-- ============================================================================
-- org_graph.py の DB永続化用テーブル
--
-- テーブル:
--   1. brain_person_nodes - 人物ノード
--   2. brain_relationships - 関係性
--   3. brain_interactions - インタラクション記録
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. brain_person_nodes テーブル
-- ============================================================================

CREATE TABLE IF NOT EXISTS brain_person_nodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    person_id VARCHAR(100) NOT NULL,

    -- 基本情報
    name VARCHAR(255) NOT NULL DEFAULT '',
    department_id VARCHAR(100),
    role VARCHAR(255),

    -- 属性
    influence_score DECIMAL(3,2) DEFAULT 0.50,
    expertise_areas JSONB DEFAULT '[]',
    communication_style VARCHAR(50) DEFAULT 'casual',

    -- 統計
    total_interactions INTEGER DEFAULT 0,
    avg_response_time_hours DECIMAL(6,2),
    activity_level DECIMAL(3,2) DEFAULT 0.50,

    -- タイムスタンプ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- ユニーク制約: 組織内で同一person_idは1つ
    UNIQUE (organization_id, person_id)
);

CREATE INDEX IF NOT EXISTS idx_brain_person_nodes_org
    ON brain_person_nodes(organization_id);
CREATE INDEX IF NOT EXISTS idx_brain_person_nodes_person
    ON brain_person_nodes(organization_id, person_id);

-- ============================================================================
-- 2. brain_relationships テーブル
-- ============================================================================

CREATE TABLE IF NOT EXISTS brain_relationships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,

    person_a_id VARCHAR(100) NOT NULL,
    person_b_id VARCHAR(100) NOT NULL,
    relationship_type VARCHAR(50) NOT NULL,

    -- 関係属性
    strength DECIMAL(3,2) DEFAULT 0.30,
    trust_level DECIMAL(3,2) DEFAULT 0.50,
    bidirectional BOOLEAN DEFAULT false,
    interaction_count INTEGER DEFAULT 0,

    -- コンテキスト
    context JSONB DEFAULT '{}',

    -- タイムスタンプ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- ユニーク制約
    UNIQUE (organization_id, person_a_id, person_b_id, relationship_type)
);

CREATE INDEX IF NOT EXISTS idx_brain_relationships_org
    ON brain_relationships(organization_id);
CREATE INDEX IF NOT EXISTS idx_brain_relationships_person_a
    ON brain_relationships(organization_id, person_a_id);
CREATE INDEX IF NOT EXISTS idx_brain_relationships_person_b
    ON brain_relationships(organization_id, person_b_id);

-- ============================================================================
-- 3. brain_interactions テーブル
-- ============================================================================

CREATE TABLE IF NOT EXISTS brain_interactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,

    from_person_id VARCHAR(100) NOT NULL,
    to_person_id VARCHAR(100) NOT NULL,
    interaction_type VARCHAR(50) NOT NULL,

    -- 詳細
    sentiment DECIMAL(3,2) DEFAULT 0.00,
    room_id VARCHAR(100),

    -- タイムスタンプ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_brain_interactions_org
    ON brain_interactions(organization_id);
CREATE INDEX IF NOT EXISTS idx_brain_interactions_from
    ON brain_interactions(organization_id, from_person_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_brain_interactions_created
    ON brain_interactions(created_at DESC);

-- ============================================================================
-- 4. トリガー
-- ============================================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'update_updated_at_column') THEN
        IF NOT EXISTS (
            SELECT 1 FROM pg_trigger WHERE tgname = 'update_brain_person_nodes_updated_at'
        ) THEN
            CREATE TRIGGER update_brain_person_nodes_updated_at
                BEFORE UPDATE ON brain_person_nodes
                FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM pg_trigger WHERE tgname = 'update_brain_relationships_updated_at'
        ) THEN
            CREATE TRIGGER update_brain_relationships_updated_at
                BEFORE UPDATE ON brain_relationships
                FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
        END IF;
    END IF;
END
$$;

-- ============================================================================
-- 5. RLS
-- ============================================================================

ALTER TABLE brain_person_nodes ENABLE ROW LEVEL SECURITY;
ALTER TABLE brain_relationships ENABLE ROW LEVEL SECURITY;
ALTER TABLE brain_interactions ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policy WHERE polname = 'brain_person_nodes_org_isolation') THEN
        CREATE POLICY brain_person_nodes_org_isolation ON brain_person_nodes
            FOR ALL USING (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policy WHERE polname = 'brain_relationships_org_isolation') THEN
        CREATE POLICY brain_relationships_org_isolation ON brain_relationships
            FOR ALL USING (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policy WHERE polname = 'brain_interactions_org_isolation') THEN
        CREATE POLICY brain_interactions_org_isolation ON brain_interactions
            FOR ALL USING (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END
$$;

-- ============================================================================
-- 6. 確認
-- ============================================================================

SELECT table_name,
       (SELECT COUNT(*) FROM information_schema.columns c WHERE c.table_name = t.table_name) AS cols
FROM information_schema.tables t
WHERE table_name IN ('brain_person_nodes', 'brain_relationships', 'brain_interactions')
ORDER BY table_name;

COMMIT;
