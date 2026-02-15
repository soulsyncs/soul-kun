-- ============================================================================
-- Migration: persons.id INTEGER -> UUID (primary key migration)
--
-- 3AI Consensus (2026-02-15): Full UUID migration for person ID
-- Risk: 3/10 (tiny tables: 7 persons + 23 person_attributes + person_events)
--
-- Strategy: Single-transaction atomic swap
--   1. Add UUID column
--   2. Populate with generated UUIDs
--   3. Update FK references
--   4. Swap primary key
--   5. Rename columns
--   6. Recreate constraints, indexes, RLS
-- ============================================================================

BEGIN;

-- ============================================================
-- Phase 0: Pre-flight validation
-- ============================================================
DO $$
DECLARE
    _persons_count INTEGER;
    _pa_count INTEGER;
    _pe_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO _persons_count FROM persons;
    SELECT COUNT(*) INTO _pa_count FROM person_attributes;
    SELECT COUNT(*) INTO _pe_count FROM person_events;

    RAISE NOTICE 'Pre-flight: persons=%, person_attributes=%, person_events=%',
        _persons_count, _pa_count, _pe_count;

    -- Safety: abort if unexpectedly large
    IF _persons_count > 100 THEN
        RAISE EXCEPTION 'persons table has % rows (expected ~7). Aborting for safety.', _persons_count;
    END IF;
END $$;

-- ============================================================
-- Phase 1: Add UUID columns
-- ============================================================

-- persons: new UUID primary key column
ALTER TABLE persons ADD COLUMN uuid_id UUID DEFAULT gen_random_uuid() NOT NULL;

-- person_attributes: new UUID FK column
ALTER TABLE person_attributes ADD COLUMN person_uuid UUID;

-- person_events: new UUID FK column
ALTER TABLE person_events ADD COLUMN person_uuid UUID;

-- ============================================================
-- Phase 2: Populate UUID columns (backfill)
-- ============================================================

-- Generate UUIDs for existing persons
UPDATE persons SET uuid_id = gen_random_uuid() WHERE uuid_id IS NULL;

-- Map person_attributes.person_id (int) -> person_uuid (uuid)
UPDATE person_attributes pa
SET person_uuid = p.uuid_id
FROM persons p
WHERE pa.person_id = p.id;

-- Map person_events.person_id (int) -> person_uuid (uuid)
UPDATE person_events pe
SET person_uuid = p.uuid_id
FROM persons p
WHERE pe.person_id = p.id;

-- ============================================================
-- Phase 3: Validate backfill (zero NULLs allowed)
-- ============================================================
DO $$
DECLARE
    _null_pa INTEGER;
    _null_pe INTEGER;
BEGIN
    SELECT COUNT(*) INTO _null_pa FROM person_attributes WHERE person_uuid IS NULL;
    SELECT COUNT(*) INTO _null_pe FROM person_events WHERE person_uuid IS NULL;

    IF _null_pa > 0 THEN
        RAISE EXCEPTION 'person_attributes has % rows with NULL person_uuid after backfill', _null_pa;
    END IF;
    IF _null_pe > 0 THEN
        RAISE EXCEPTION 'person_events has % rows with NULL person_uuid after backfill', _null_pe;
    END IF;
END $$;

-- ============================================================
-- Phase 4: Drop old constraints and indexes
-- ============================================================

-- Drop FK constraints on person_id (integer)
ALTER TABLE person_attributes DROP CONSTRAINT IF EXISTS person_attributes_person_id_fkey;
ALTER TABLE person_attributes DROP CONSTRAINT IF EXISTS fk_person_attributes_person_id;
ALTER TABLE person_events DROP CONSTRAINT IF EXISTS person_events_person_id_fkey;
ALTER TABLE person_events DROP CONSTRAINT IF EXISTS fk_person_events_person_id;

-- Drop unique constraints that reference old columns
ALTER TABLE person_attributes DROP CONSTRAINT IF EXISTS person_attributes_person_id_attribute_type_key;
ALTER TABLE person_attributes DROP CONSTRAINT IF EXISTS uq_person_attribute;

-- Drop old indexes
DROP INDEX IF EXISTS idx_person_attributes_person_id;
DROP INDEX IF EXISTS idx_person_events_person_id;

-- Drop old primary key
ALTER TABLE persons DROP CONSTRAINT IF EXISTS persons_pkey;

-- ============================================================
-- Phase 5: Rename columns (atomic swap)
-- ============================================================

-- persons: id (int) -> old_int_id, uuid_id -> id
ALTER TABLE persons RENAME COLUMN id TO old_int_id;
ALTER TABLE persons RENAME COLUMN uuid_id TO id;

-- person_attributes: person_id (int) -> old_person_int_id, person_uuid -> person_id
ALTER TABLE person_attributes RENAME COLUMN person_id TO old_person_int_id;
ALTER TABLE person_attributes RENAME COLUMN person_uuid TO person_id;

-- person_events: person_id (int) -> old_person_int_id, person_uuid -> person_id
ALTER TABLE person_events RENAME COLUMN person_id TO old_person_int_id;
ALTER TABLE person_events RENAME COLUMN person_uuid TO person_id;

-- ============================================================
-- Phase 6: Recreate constraints
-- ============================================================

-- New primary key on UUID
ALTER TABLE persons ADD PRIMARY KEY (id);

-- NOT NULL on FK columns
ALTER TABLE person_attributes ALTER COLUMN person_id SET NOT NULL;
ALTER TABLE person_events ALTER COLUMN person_id SET NOT NULL;

-- FK constraints (UUID -> UUID)
ALTER TABLE person_attributes
    ADD CONSTRAINT fk_person_attributes_person_id
    FOREIGN KEY (person_id) REFERENCES persons(id);

ALTER TABLE person_events
    ADD CONSTRAINT fk_person_events_person_id
    FOREIGN KEY (person_id) REFERENCES persons(id);

-- Unique constraint: one attribute type per person
ALTER TABLE person_attributes
    ADD CONSTRAINT uq_person_attribute
    UNIQUE (person_id, attribute_type);

-- ============================================================
-- Phase 7: Recreate indexes
-- ============================================================
CREATE INDEX idx_persons_id ON persons(id);
CREATE INDEX idx_person_attributes_person_id ON person_attributes(person_id);
CREATE INDEX idx_person_events_person_id ON person_events(person_id);

-- ============================================================
-- Phase 8: Recreate RLS policies (UUID casting)
-- ============================================================
-- persons
DROP POLICY IF EXISTS persons_org_isolation ON persons;
CREATE POLICY persons_org_isolation ON persons
    USING (organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::uuid);

-- person_attributes
DROP POLICY IF EXISTS person_attributes_org_isolation ON person_attributes;
CREATE POLICY person_attributes_org_isolation ON person_attributes
    USING (organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::uuid);

-- ============================================================
-- Phase 9: Drop old integer columns (cleanup)
-- ============================================================
ALTER TABLE persons DROP COLUMN old_int_id;
ALTER TABLE person_attributes DROP COLUMN old_person_int_id;
ALTER TABLE person_events DROP COLUMN old_person_int_id;

-- Drop old sequence (if exists)
DROP SEQUENCE IF EXISTS persons_id_seq;

-- ============================================================
-- Phase 10: Set default for new rows
-- ============================================================
ALTER TABLE persons ALTER COLUMN id SET DEFAULT gen_random_uuid();

COMMIT;

-- Post-migration verification queries (run manually):
-- SELECT id, name, organization_id FROM persons;
-- SELECT person_id, attribute_type FROM person_attributes LIMIT 5;
-- SELECT person_id FROM person_events LIMIT 5;
