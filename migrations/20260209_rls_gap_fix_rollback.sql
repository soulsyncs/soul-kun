-- ============================================================================
-- ロールバック: 旧マイグレーションテーブルのRLSギャップ修正
-- 対象: 20260209_rls_gap_fix.sql の逆操作
-- 作成日: 2026-02-09
-- ============================================================================

BEGIN;

-- 1. goal_setting_patterns
DROP POLICY IF EXISTS goal_setting_patterns_org_isolation ON goal_setting_patterns;
ALTER TABLE goal_setting_patterns DISABLE ROW LEVEL SECURITY;
DROP INDEX IF EXISTS idx_goal_setting_patterns_org_id;
ALTER TABLE goal_setting_patterns DROP COLUMN IF EXISTS organization_id;

-- 2. goals
DROP POLICY IF EXISTS goals_org_isolation ON goals;
ALTER TABLE goals DISABLE ROW LEVEL SECURITY;

-- 3. goal_progress
DROP POLICY IF EXISTS goal_progress_org_isolation ON goal_progress;
ALTER TABLE goal_progress DISABLE ROW LEVEL SECURITY;

-- 4. goal_reminders
DROP POLICY IF EXISTS goal_reminders_org_isolation ON goal_reminders;
ALTER TABLE goal_reminders DISABLE ROW LEVEL SECURITY;

-- 5. audit_logs
DROP POLICY IF EXISTS audit_logs_org_isolation ON audit_logs;
ALTER TABLE audit_logs DISABLE ROW LEVEL SECURITY;

-- 6. document_versions
DROP POLICY IF EXISTS document_versions_org_isolation ON document_versions;
ALTER TABLE document_versions DISABLE ROW LEVEL SECURITY;

COMMIT;
