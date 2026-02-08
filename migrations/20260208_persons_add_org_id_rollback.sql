-- ============================================================================
-- persons系テーブル organization_id追加のロールバック
--
-- 用途: 本番適用後に問題が発生した場合のロールバック用
-- 実行方法: psql -d $DATABASE -f migrations/20260208_persons_add_org_id_rollback.sql
--
-- 注意: このファイルは20260208_persons_add_org_id.sqlの逆操作
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. RLSポリシーの削除
-- ============================================================================

DROP POLICY IF EXISTS persons_org_isolation ON persons;
ALTER TABLE persons DISABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS person_attributes_org_isolation ON person_attributes;
ALTER TABLE person_attributes DISABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS person_events_org_isolation ON person_events;
ALTER TABLE person_events DISABLE ROW LEVEL SECURITY;

-- ============================================================================
-- 2. インデックスの削除
-- ============================================================================

DROP INDEX IF EXISTS idx_persons_org_id_name;
DROP INDEX IF EXISTS idx_persons_org_id;
DROP INDEX IF EXISTS idx_person_attributes_org_id;
DROP INDEX IF EXISTS idx_person_events_org_id;
DROP INDEX IF EXISTS idx_person_attributes_org_person;
DROP INDEX IF EXISTS idx_person_events_org_person;

-- ============================================================================
-- 3. 外部キー制約の削除
-- ============================================================================

ALTER TABLE persons DROP CONSTRAINT IF EXISTS fk_persons_organization_id;
ALTER TABLE person_attributes DROP CONSTRAINT IF EXISTS fk_person_attributes_organization_id;
ALTER TABLE person_events DROP CONSTRAINT IF EXISTS fk_person_events_organization_id;

-- ============================================================================
-- 4. NOT NULL制約の削除
-- ============================================================================

ALTER TABLE persons ALTER COLUMN organization_id DROP NOT NULL;
ALTER TABLE person_attributes ALTER COLUMN organization_id DROP NOT NULL;
ALTER TABLE person_events ALTER COLUMN organization_id DROP NOT NULL;

-- ============================================================================
-- 5. カラムの削除
-- ============================================================================

ALTER TABLE persons DROP COLUMN IF EXISTS organization_id;
ALTER TABLE person_attributes DROP COLUMN IF EXISTS organization_id;
ALTER TABLE person_events DROP COLUMN IF EXISTS organization_id;

COMMIT;

-- ============================================================================
-- 検証クエリ（ロールバック後の確認用）
-- ============================================================================
--
-- 1. カラムが削除されたことを確認:
--    SELECT column_name FROM information_schema.columns
--    WHERE table_name IN ('persons', 'person_attributes', 'person_events')
--      AND column_name = 'organization_id';
--    -- 結果が0行であること
--
-- 2. RLSが無効であることを確認:
--    SELECT tablename, rowsecurity FROM pg_tables
--    WHERE tablename IN ('persons', 'person_attributes', 'person_events');
--    -- rowsecurity = false であること
--
-- ============================================================================
