-- ============================================================================
-- ロールバック: Runtime管理テーブルのorganization_idカラムを削除
--
-- 対象: 20260209_runtime_tables_add_org_id.sql の逆操作
--
-- 作成日: 2026-02-09
-- ============================================================================

BEGIN;

-- 1. processed_messages
DROP POLICY IF EXISTS processed_messages_org_isolation ON processed_messages;
ALTER TABLE processed_messages DISABLE ROW LEVEL SECURITY;
DROP INDEX IF EXISTS idx_processed_messages_org_id;
ALTER TABLE processed_messages DROP COLUMN IF EXISTS organization_id;

-- 2. task_overdue_reminders
DROP POLICY IF EXISTS task_overdue_reminders_org_isolation ON task_overdue_reminders;
ALTER TABLE task_overdue_reminders DISABLE ROW LEVEL SECURITY;
DROP INDEX IF EXISTS idx_overdue_reminders_org_id;
ALTER TABLE task_overdue_reminders DROP COLUMN IF EXISTS organization_id;

-- 3. task_limit_changes
DROP POLICY IF EXISTS task_limit_changes_org_isolation ON task_limit_changes;
ALTER TABLE task_limit_changes DISABLE ROW LEVEL SECURITY;
DROP INDEX IF EXISTS idx_limit_changes_org_id;
ALTER TABLE task_limit_changes DROP COLUMN IF EXISTS organization_id;

-- 4. dm_room_cache
DROP POLICY IF EXISTS dm_room_cache_org_isolation ON dm_room_cache;
ALTER TABLE dm_room_cache DISABLE ROW LEVEL SECURITY;
DROP INDEX IF EXISTS idx_dm_room_cache_org_id;
ALTER TABLE dm_room_cache DROP COLUMN IF EXISTS organization_id;

-- 5. task_escalations
DROP POLICY IF EXISTS task_escalations_org_isolation ON task_escalations;
ALTER TABLE task_escalations DISABLE ROW LEVEL SECURITY;
DROP INDEX IF EXISTS idx_task_escalations_org_id;
ALTER TABLE task_escalations DROP COLUMN IF EXISTS organization_id;

COMMIT;
