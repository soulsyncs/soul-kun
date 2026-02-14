-- ============================================================================
-- Migration: persons/person_attributes organization_id VARCHAR -> UUID
--
-- 3AI Consensus (2026-02-14): Option A+ (minimal conversion, zero code changes)
-- Risk: 2-3/10 (tiny tables: 7 + 23 rows, no app code changes)
--
-- Pre-flight verified:
--   - persons: 7 rows, 0 bad UUIDs
--   - person_attributes: 23 rows, 0 bad UUIDs
--   - person_events: organization_id column does NOT exist (skip)
-- ============================================================================

BEGIN;

-- Phase 0: Validate all existing data is valid UUID (safety guard)
DO $$
DECLARE
    _bad_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO _bad_count FROM persons
    WHERE organization_id IS NOT NULL
      AND organization_id !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';
    IF _bad_count > 0 THEN
        RAISE EXCEPTION 'Found % rows in persons with non-UUID organization_id', _bad_count;
    END IF;

    SELECT COUNT(*) INTO _bad_count FROM person_attributes
    WHERE organization_id IS NOT NULL
      AND organization_id !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';
    IF _bad_count > 0 THEN
        RAISE EXCEPTION 'Found % rows in person_attributes with non-UUID organization_id', _bad_count;
    END IF;
END $$;

-- Phase 1: Drop dependent objects (RLS policies, indexes, FK constraints)
DROP POLICY IF EXISTS persons_org_isolation ON persons;
DROP POLICY IF EXISTS person_attributes_org_isolation ON person_attributes;

DROP INDEX IF EXISTS idx_persons_org_id;
DROP INDEX IF EXISTS idx_persons_org_id_name;
DROP INDEX IF EXISTS idx_person_attributes_org_id;
DROP INDEX IF EXISTS idx_person_attributes_org_person;

ALTER TABLE persons DROP CONSTRAINT IF EXISTS fk_persons_organization_id;
ALTER TABLE person_attributes DROP CONSTRAINT IF EXISTS fk_person_attributes_organization_id;

-- Phase 2: Drop non-UUID defaults, then convert column types (VARCHAR -> UUID)
-- Both tables had DEFAULT 'soul_syncs'::character varying which cannot cast to UUID.
ALTER TABLE persons
    ALTER COLUMN organization_id DROP DEFAULT;
ALTER TABLE person_attributes
    ALTER COLUMN organization_id DROP DEFAULT;

ALTER TABLE persons
    ALTER COLUMN organization_id TYPE uuid USING organization_id::uuid;

ALTER TABLE person_attributes
    ALTER COLUMN organization_id TYPE uuid USING organization_id::uuid;

-- Phase 3: Re-create FK constraints (now type-safe: uuid -> uuid)
ALTER TABLE persons
    ADD CONSTRAINT fk_persons_organization_id
    FOREIGN KEY (organization_id) REFERENCES organizations(id);

ALTER TABLE person_attributes
    ADD CONSTRAINT fk_person_attributes_organization_id
    FOREIGN KEY (organization_id) REFERENCES organizations(id);

-- Phase 4: Re-create indexes
CREATE INDEX idx_persons_org_id ON persons(organization_id);
CREATE INDEX idx_persons_org_id_name ON persons(organization_id, name);
CREATE INDEX idx_person_attributes_org_id ON person_attributes(organization_id);
CREATE INDEX idx_person_attributes_org_person ON person_attributes(organization_id, person_id);

-- Phase 5: Re-create RLS policies (now correct: uuid = uuid, no implicit cast)
CREATE POLICY persons_org_isolation ON persons
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);

CREATE POLICY person_attributes_org_isolation ON person_attributes
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);

COMMIT;
