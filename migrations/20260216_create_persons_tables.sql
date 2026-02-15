-- ============================================================================
-- Migration: Create persons, person_attributes, person_events tables
--
-- 本番DBにこれらのテーブルが存在しなかったため、UUID型で新規作成する。
-- 全テーブルにRLS（行レベルセキュリティ）を適用。
--
-- 2026-02-16
-- ============================================================================

BEGIN;

-- ============================================================
-- 1. persons テーブル（人物情報）
-- ============================================================
CREATE TABLE IF NOT EXISTS persons (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    organization_id UUID NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_persons_org_id ON persons(organization_id);
CREATE INDEX IF NOT EXISTS idx_persons_org_id_name ON persons(organization_id, name);

ALTER TABLE persons ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'persons' AND policyname = 'persons_org_isolation') THEN
        CREATE POLICY persons_org_isolation ON persons
            USING (organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::uuid)
            WITH CHECK (organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::uuid);
    END IF;
END $$;

-- ============================================================
-- 2. person_attributes テーブル（人物の属性）
-- ============================================================
CREATE TABLE IF NOT EXISTS person_attributes (
    id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    person_id UUID NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    attribute_type VARCHAR(100) NOT NULL,
    attribute_value TEXT,
    source VARCHAR(50) DEFAULT 'conversation',
    organization_id UUID NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_person_attribute UNIQUE (person_id, attribute_type)
);

CREATE INDEX IF NOT EXISTS idx_person_attributes_person_id ON person_attributes(person_id);
CREATE INDEX IF NOT EXISTS idx_person_attributes_org_id ON person_attributes(organization_id);

ALTER TABLE person_attributes ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'person_attributes' AND policyname = 'person_attributes_org_isolation') THEN
        CREATE POLICY person_attributes_org_isolation ON person_attributes
            USING (organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::uuid)
            WITH CHECK (organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::uuid);
    END IF;
END $$;

-- ============================================================
-- 3. person_events テーブル（人物のイベント）
-- ============================================================
CREATE TABLE IF NOT EXISTS person_events (
    id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    person_id UUID NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    event_description TEXT,
    event_date DATE,
    organization_id UUID NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_person_events_person_id ON person_events(person_id);
CREATE INDEX IF NOT EXISTS idx_person_events_org_id ON person_events(organization_id);

ALTER TABLE person_events ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'person_events' AND policyname = 'person_events_org_isolation') THEN
        CREATE POLICY person_events_org_isolation ON person_events
            USING (organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::uuid)
            WITH CHECK (organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::uuid);
    END IF;
END $$;

-- ============================================================
-- 4. 検証
-- ============================================================
DO $$
DECLARE
    _persons_exists BOOLEAN;
    _pa_exists BOOLEAN;
    _pe_exists BOOLEAN;
BEGIN
    SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'persons') INTO _persons_exists;
    SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'person_attributes') INTO _pa_exists;
    SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'person_events') INTO _pe_exists;

    IF NOT _persons_exists THEN RAISE EXCEPTION 'persons table was not created'; END IF;
    IF NOT _pa_exists THEN RAISE EXCEPTION 'person_attributes table was not created'; END IF;
    IF NOT _pe_exists THEN RAISE EXCEPTION 'person_events table was not created'; END IF;

    RAISE NOTICE 'All 3 tables created successfully: persons, person_attributes, person_events';
END $$;

COMMIT;
