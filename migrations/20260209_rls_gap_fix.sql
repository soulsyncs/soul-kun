-- ============================================================================
-- 旧マイグレーションテーブルのRLSギャップ修正
--
-- 目的: Codex監査AUDIT-3で検出されたRLS未設定テーブルにポリシーを追加
-- 対象: 6テーブル（ai_model_registryは本番未作成のためスキップ）
--
-- テーブル別のorg_id型:
--   UUID型:    goals, goal_progress, goal_reminders, document_versions
--   VARCHAR型: audit_logs
--   未設定:    goal_setting_patterns（本マイグレーションでVARCHAR(255)追加）
--
-- ロールバック: 20260209_rls_gap_fix_rollback.sql
-- 作成日: 2026-02-09
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. goal_setting_patterns: organization_id カラム追加 + RLS
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'goal_setting_patterns'
          AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE goal_setting_patterns ADD COLUMN organization_id VARCHAR(255);
    END IF;
END $$;

UPDATE goal_setting_patterns
  SET organization_id = 'org_soulsyncs'
  WHERE organization_id IS NULL;

ALTER TABLE goal_setting_patterns ALTER COLUMN organization_id SET NOT NULL;
ALTER TABLE goal_setting_patterns ALTER COLUMN organization_id SET DEFAULT 'org_soulsyncs';

CREATE INDEX IF NOT EXISTS idx_goal_setting_patterns_org_id
  ON goal_setting_patterns(organization_id);

ALTER TABLE goal_setting_patterns ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS goal_setting_patterns_org_isolation ON goal_setting_patterns;
CREATE POLICY goal_setting_patterns_org_isolation ON goal_setting_patterns
  USING (organization_id::text = current_setting('app.current_organization_id', true)::text)
  WITH CHECK (organization_id::text = current_setting('app.current_organization_id', true)::text);

-- ============================================================================
-- 2. goals: RLS有効化（org_id UUID既存）
-- ============================================================================

ALTER TABLE goals ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS goals_org_isolation ON goals;
CREATE POLICY goals_org_isolation ON goals
  USING (organization_id::uuid = current_setting('app.current_organization_id', true)::uuid)
  WITH CHECK (organization_id::uuid = current_setting('app.current_organization_id', true)::uuid);

-- ============================================================================
-- 3. goal_progress: RLS有効化（org_id UUID既存）
-- ============================================================================

ALTER TABLE goal_progress ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS goal_progress_org_isolation ON goal_progress;
CREATE POLICY goal_progress_org_isolation ON goal_progress
  USING (organization_id::uuid = current_setting('app.current_organization_id', true)::uuid)
  WITH CHECK (organization_id::uuid = current_setting('app.current_organization_id', true)::uuid);

-- ============================================================================
-- 4. goal_reminders: RLS有効化（org_id UUID既存）
-- ============================================================================

ALTER TABLE goal_reminders ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS goal_reminders_org_isolation ON goal_reminders;
CREATE POLICY goal_reminders_org_isolation ON goal_reminders
  USING (organization_id::uuid = current_setting('app.current_organization_id', true)::uuid)
  WITH CHECK (organization_id::uuid = current_setting('app.current_organization_id', true)::uuid);

-- ============================================================================
-- 5. audit_logs: RLS有効化（org_id VARCHAR既存）
-- ============================================================================

ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS audit_logs_org_isolation ON audit_logs;
CREATE POLICY audit_logs_org_isolation ON audit_logs
  USING (organization_id::text = current_setting('app.current_organization_id', true)::text)
  WITH CHECK (organization_id::text = current_setting('app.current_organization_id', true)::text);

-- ============================================================================
-- 6. document_versions: RLS有効化（org_id UUID既存）
-- ============================================================================

ALTER TABLE document_versions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS document_versions_org_isolation ON document_versions;
CREATE POLICY document_versions_org_isolation ON document_versions
  USING (organization_id::uuid = current_setting('app.current_organization_id', true)::uuid)
  WITH CHECK (organization_id::uuid = current_setting('app.current_organization_id', true)::uuid);

COMMIT;

-- ============================================================================
-- 検証クエリ
-- ============================================================================
--
-- SELECT tablename, rowsecurity FROM pg_tables
-- WHERE tablename IN ('goal_setting_patterns', 'goals', 'goal_progress',
--                     'goal_reminders', 'audit_logs', 'document_versions');
--
-- SELECT tablename, policyname FROM pg_policies
-- WHERE tablename IN ('goal_setting_patterns', 'goals', 'goal_progress',
--                     'goal_reminders', 'audit_logs', 'document_versions');
--
-- ============================================================================
