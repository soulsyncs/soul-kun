-- ============================================================================
-- Rollback: persons/person_attributes organization_id UUID -> VARCHAR
--
-- Reverses 20260214_persons_org_id_uuid.sql
-- Risk: 2/10 (same tiny tables: 7 + 23 rows, no app code changes)
-- ============================================================================

BEGIN;

-- Phase 1: Drop dependent objects (RLS policies, indexes, FK constraints)
DROP POLICY IF EXISTS persons_org_isolation ON persons;
DROP POLICY IF EXISTS person_attributes_org_isolation ON person_attributes;

DROP INDEX IF EXISTS idx_persons_org_id;
DROP INDEX IF EXISTS idx_persons_org_id_name;
DROP INDEX IF EXISTS idx_person_attributes_org_id;
DROP INDEX IF EXISTS idx_person_attributes_org_person;

ALTER TABLE persons DROP CONSTRAINT IF EXISTS fk_persons_organization_id;
ALTER TABLE person_attributes DROP CONSTRAINT IF EXISTS fk_person_attributes_organization_id;

-- Phase 2: Revert column types (UUID -> VARCHAR)
ALTER TABLE persons
    ALTER COLUMN organization_id TYPE varchar USING organization_id::text;

ALTER TABLE person_attributes
    ALTER COLUMN organization_id TYPE varchar USING organization_id::text;

-- Phase 3: Re-create indexes (same as before migration)
CREATE INDEX idx_persons_org_id ON persons(organization_id);
CREATE INDEX idx_persons_org_id_name ON persons(organization_id, name);
CREATE INDEX idx_person_attributes_org_id ON person_attributes(organization_id);
CREATE INDEX idx_person_attributes_org_person ON person_attributes(organization_id, person_id);

-- Phase 4: Re-create RLS policies (varchar version with ::text cast)
CREATE POLICY persons_org_isolation ON persons
    USING (organization_id = current_setting('app.current_organization_id', true)::text)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::text);

CREATE POLICY person_attributes_org_isolation ON person_attributes
    USING (organization_id = current_setting('app.current_organization_id', true)::text)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::text);

-- Note: FK constraints are NOT recreated in rollback because
-- organizations.id is UUID type, and varchar cannot reference UUID.
-- The original schema did not have these FK constraints.

COMMIT;
