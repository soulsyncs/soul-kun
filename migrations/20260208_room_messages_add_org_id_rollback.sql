-- ============================================================================
-- room_messages organization_id追加のロールバック
--
-- 用途: 本番適用後に問題が発生した場合のロールバック用
-- 実行方法: psql -d $DATABASE -f migrations/20260208_room_messages_add_org_id_rollback.sql
--
-- 注意: このファイルは20260208_room_messages_add_org_id.sqlの逆操作
-- ============================================================================

BEGIN;

-- RLS
DROP POLICY IF EXISTS room_messages_org_isolation ON room_messages;
ALTER TABLE room_messages DISABLE ROW LEVEL SECURITY;

-- FK
ALTER TABLE room_messages DROP CONSTRAINT IF EXISTS fk_room_messages_organization_id;

-- Indexes
DROP INDEX IF EXISTS idx_room_messages_org_id;
DROP INDEX IF EXISTS idx_room_messages_org_send_time;

-- NOT NULL
ALTER TABLE room_messages ALTER COLUMN organization_id DROP NOT NULL;

-- Column
ALTER TABLE room_messages DROP COLUMN IF EXISTS organization_id;

COMMIT;
