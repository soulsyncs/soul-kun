-- ============================================================================
-- persons系テーブルにorganization_idカラムを追加
--
-- 目的: テナント分離（CLAUDE.md 鉄則#1: 全テーブルにorganization_idを追加）
-- ブロッカー: このマイグレーション完了がperson_service.pyのorg_idフィルター追加の前提条件
--
-- 注意: personsテーブルのCREATE TABLEはmigrations/配下に存在しない（初期セットアップで作成）。
-- 実行前に本番DBスキーマを確認すること: \d persons
--
-- ロールバック: 20260208_persons_add_org_id_rollback.sql
--
-- 作成日: 2026-02-08
-- ============================================================================

BEGIN;

-- ============================================================================
-- 0. 前提チェック: バックフィル用組織の存在確認
-- ============================================================================
DO $$
DECLARE
    _org_uuid UUID;
BEGIN
    SELECT id INTO _org_uuid FROM organizations WHERE slug = 'org_soulsyncs' LIMIT 1;
    IF _org_uuid IS NULL THEN
        RAISE EXCEPTION 'Organization with slug "org_soulsyncs" not found. '
            'Verify the slug with: SELECT id, slug FROM organizations; '
            'Aborting migration to prevent NULL backfill.';
    END IF;
END $$;

-- ============================================================================
-- 1. personsテーブルにorganization_id追加
-- ============================================================================

-- カラムが存在しない場合のみ追加
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'persons' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE persons ADD COLUMN organization_id UUID;
    END IF;
END $$;

-- ============================================================================
-- 2. person_attributesテーブルにorganization_id追加
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'person_attributes' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE person_attributes ADD COLUMN organization_id UUID;
    END IF;
END $$;

-- ============================================================================
-- 3. person_eventsテーブルにorganization_id追加
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'person_events' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE person_events ADD COLUMN organization_id UUID;
    END IF;
END $$;

-- ============================================================================
-- 4. 既存データにデフォルトorganization_idを設定
-- ============================================================================
-- 注意: organizations.slugの値を本番DBで確認してからUPDATEすること
-- SELECT id, slug FROM organizations; で確認

DO $$
DECLARE
    _org_uuid UUID;
BEGIN
    SELECT id INTO _org_uuid FROM organizations WHERE slug = 'org_soulsyncs' LIMIT 1;
    -- 前提チェック（セクション0）で既に検証済みだが安全のため再確認
    IF _org_uuid IS NULL THEN
        RAISE EXCEPTION 'Organization with slug "org_soulsyncs" not found. Aborting.';
    END IF;

    UPDATE persons SET organization_id = _org_uuid WHERE organization_id IS NULL;
    UPDATE person_attributes SET organization_id = _org_uuid WHERE organization_id IS NULL;
    UPDATE person_events SET organization_id = _org_uuid WHERE organization_id IS NULL;
END $$;

-- ============================================================================
-- 5. NOT NULL制約を追加
-- ============================================================================

ALTER TABLE persons ALTER COLUMN organization_id SET NOT NULL;
ALTER TABLE person_attributes ALTER COLUMN organization_id SET NOT NULL;
ALTER TABLE person_events ALTER COLUMN organization_id SET NOT NULL;

-- ============================================================================
-- 6. 外部キー制約を追加
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_schema = 'public'
          AND constraint_name = 'fk_persons_organization_id' AND table_name = 'persons'
    ) THEN
        ALTER TABLE persons
            ADD CONSTRAINT fk_persons_organization_id
            FOREIGN KEY (organization_id) REFERENCES organizations(id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_schema = 'public'
          AND constraint_name = 'fk_person_attributes_organization_id' AND table_name = 'person_attributes'
    ) THEN
        ALTER TABLE person_attributes
            ADD CONSTRAINT fk_person_attributes_organization_id
            FOREIGN KEY (organization_id) REFERENCES organizations(id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_schema = 'public'
          AND constraint_name = 'fk_person_events_organization_id' AND table_name = 'person_events'
    ) THEN
        ALTER TABLE person_events
            ADD CONSTRAINT fk_person_events_organization_id
            FOREIGN KEY (organization_id) REFERENCES organizations(id);
    END IF;
END $$;

-- ============================================================================
-- 7. インデックス追加（org_idフィルター高速化）
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_persons_org_id ON persons(organization_id);
CREATE INDEX IF NOT EXISTS idx_person_attributes_org_id ON person_attributes(organization_id);
CREATE INDEX IF NOT EXISTS idx_person_events_org_id ON person_events(organization_id);

-- persons名前検索のインデックス（org_id + name）
CREATE INDEX IF NOT EXISTS idx_persons_org_id_name ON persons(organization_id, name);

-- person_attributes/eventsの複合インデックス（org_id + person_id）
CREATE INDEX IF NOT EXISTS idx_person_attributes_org_person
    ON person_attributes(organization_id, person_id);
CREATE INDEX IF NOT EXISTS idx_person_events_org_person
    ON person_events(organization_id, person_id);

-- ============================================================================
-- 8. RLS有効化（Tier 1-D）
-- ============================================================================

ALTER TABLE persons ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS persons_org_isolation ON persons;
CREATE POLICY persons_org_isolation ON persons
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);

ALTER TABLE person_attributes ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS person_attributes_org_isolation ON person_attributes;
CREATE POLICY person_attributes_org_isolation ON person_attributes
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);

ALTER TABLE person_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS person_events_org_isolation ON person_events;
CREATE POLICY person_events_org_isolation ON person_events
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);

COMMIT;

-- ============================================================================
-- 検証クエリ（実行後の確認用）
-- ============================================================================
--
-- 1. カラム確認:
--    SELECT table_name, column_name, data_type, is_nullable
--    FROM information_schema.columns
--    WHERE table_name IN ('persons', 'person_attributes', 'person_events')
--      AND column_name = 'organization_id';
--
-- 2. RLS確認:
--    SELECT tablename, rowsecurity FROM pg_tables
--    WHERE tablename IN ('persons', 'person_attributes', 'person_events');
--
-- 3. ポリシー確認:
--    SELECT tablename, policyname FROM pg_policies
--    WHERE tablename IN ('persons', 'person_attributes', 'person_events');
--
-- ============================================================================
