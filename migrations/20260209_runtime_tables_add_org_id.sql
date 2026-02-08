-- ============================================================================
-- Runtime管理テーブルにorganization_idカラムを追加
--
-- 目的: テナント分離（CLAUDE.md 鉄則#1: 全テーブルにorganization_idを追加）
-- 対象: sync-chatwork-tasks / remind-tasks で使用される5テーブル
--   1. processed_messages    - 二重処理防止
--   2. task_overdue_reminders - 督促履歴
--   3. task_limit_changes     - 期限変更履歴
--   4. dm_room_cache          - DMルームIDキャッシュ
--   5. task_escalations       - エスカレーション記録
--
-- 注意:
-- - 全テーブルのorganization_idはVARCHAR(100)（slugベース、UUIDではない）
-- - RLSポリシーは::textキャスト（VARCHARカラムに::uuidは本番エラーになる）
-- - 安全性: 本番環境は現在 org_soulsyncs のみの単一テナント
--
-- ロールバック: 20260209_runtime_tables_add_org_id_rollback.sql
--
-- 作成日: 2026-02-09
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. processed_messages
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'processed_messages'
          AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE processed_messages ADD COLUMN organization_id VARCHAR(100);
    END IF;
END $$;

UPDATE processed_messages
  SET organization_id = 'org_soulsyncs'
  WHERE organization_id IS NULL;

ALTER TABLE processed_messages ALTER COLUMN organization_id SET NOT NULL;
ALTER TABLE processed_messages ALTER COLUMN organization_id SET DEFAULT 'org_soulsyncs';

CREATE INDEX IF NOT EXISTS idx_processed_messages_org_id
  ON processed_messages(organization_id);

ALTER TABLE processed_messages ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS processed_messages_org_isolation ON processed_messages;
CREATE POLICY processed_messages_org_isolation ON processed_messages
  USING (organization_id::text = current_setting('app.current_organization_id', true)::text)
  WITH CHECK (organization_id::text = current_setting('app.current_organization_id', true)::text);

-- ============================================================================
-- 2. task_overdue_reminders
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'task_overdue_reminders'
          AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE task_overdue_reminders ADD COLUMN organization_id VARCHAR(100);
    END IF;
END $$;

UPDATE task_overdue_reminders
  SET organization_id = 'org_soulsyncs'
  WHERE organization_id IS NULL;

ALTER TABLE task_overdue_reminders ALTER COLUMN organization_id SET NOT NULL;
ALTER TABLE task_overdue_reminders ALTER COLUMN organization_id SET DEFAULT 'org_soulsyncs';

CREATE INDEX IF NOT EXISTS idx_overdue_reminders_org_id
  ON task_overdue_reminders(organization_id);

ALTER TABLE task_overdue_reminders ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS task_overdue_reminders_org_isolation ON task_overdue_reminders;
CREATE POLICY task_overdue_reminders_org_isolation ON task_overdue_reminders
  USING (organization_id::text = current_setting('app.current_organization_id', true)::text)
  WITH CHECK (organization_id::text = current_setting('app.current_organization_id', true)::text);

-- ============================================================================
-- 3. task_limit_changes
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'task_limit_changes'
          AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE task_limit_changes ADD COLUMN organization_id VARCHAR(100);
    END IF;
END $$;

UPDATE task_limit_changes
  SET organization_id = 'org_soulsyncs'
  WHERE organization_id IS NULL;

ALTER TABLE task_limit_changes ALTER COLUMN organization_id SET NOT NULL;
ALTER TABLE task_limit_changes ALTER COLUMN organization_id SET DEFAULT 'org_soulsyncs';

CREATE INDEX IF NOT EXISTS idx_limit_changes_org_id
  ON task_limit_changes(organization_id);

ALTER TABLE task_limit_changes ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS task_limit_changes_org_isolation ON task_limit_changes;
CREATE POLICY task_limit_changes_org_isolation ON task_limit_changes
  USING (organization_id::text = current_setting('app.current_organization_id', true)::text)
  WITH CHECK (organization_id::text = current_setting('app.current_organization_id', true)::text);

-- ============================================================================
-- 4. dm_room_cache
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'dm_room_cache'
          AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE dm_room_cache ADD COLUMN organization_id VARCHAR(100);
    END IF;
END $$;

UPDATE dm_room_cache
  SET organization_id = 'org_soulsyncs'
  WHERE organization_id IS NULL;

ALTER TABLE dm_room_cache ALTER COLUMN organization_id SET NOT NULL;
ALTER TABLE dm_room_cache ALTER COLUMN organization_id SET DEFAULT 'org_soulsyncs';

CREATE INDEX IF NOT EXISTS idx_dm_room_cache_org_id
  ON dm_room_cache(organization_id);

ALTER TABLE dm_room_cache ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS dm_room_cache_org_isolation ON dm_room_cache;
CREATE POLICY dm_room_cache_org_isolation ON dm_room_cache
  USING (organization_id::text = current_setting('app.current_organization_id', true)::text)
  WITH CHECK (organization_id::text = current_setting('app.current_organization_id', true)::text);

-- ============================================================================
-- 5. task_escalations
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'task_escalations'
          AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE task_escalations ADD COLUMN organization_id VARCHAR(100);
    END IF;
END $$;

UPDATE task_escalations
  SET organization_id = 'org_soulsyncs'
  WHERE organization_id IS NULL;

ALTER TABLE task_escalations ALTER COLUMN organization_id SET NOT NULL;
ALTER TABLE task_escalations ALTER COLUMN organization_id SET DEFAULT 'org_soulsyncs';

CREATE INDEX IF NOT EXISTS idx_task_escalations_org_id
  ON task_escalations(organization_id);

ALTER TABLE task_escalations ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS task_escalations_org_isolation ON task_escalations;
CREATE POLICY task_escalations_org_isolation ON task_escalations
  USING (organization_id::text = current_setting('app.current_organization_id', true)::text)
  WITH CHECK (organization_id::text = current_setting('app.current_organization_id', true)::text);

COMMIT;

-- ============================================================================
-- 検証クエリ（実行後の確認用）
-- ============================================================================
--
-- 1. カラム確認:
--    SELECT table_name, column_name, data_type, is_nullable
--    FROM information_schema.columns
--    WHERE column_name = 'organization_id'
--      AND table_name IN ('processed_messages', 'task_overdue_reminders',
--                         'task_limit_changes', 'dm_room_cache', 'task_escalations')
--    ORDER BY table_name;
--
-- 2. バックフィル確認:
--    SELECT 'processed_messages' AS tbl, organization_id, COUNT(*) FROM processed_messages GROUP BY organization_id
--    UNION ALL
--    SELECT 'task_overdue_reminders', organization_id, COUNT(*) FROM task_overdue_reminders GROUP BY organization_id
--    UNION ALL
--    SELECT 'task_limit_changes', organization_id, COUNT(*) FROM task_limit_changes GROUP BY organization_id
--    UNION ALL
--    SELECT 'dm_room_cache', organization_id, COUNT(*) FROM dm_room_cache GROUP BY organization_id
--    UNION ALL
--    SELECT 'task_escalations', organization_id, COUNT(*) FROM task_escalations GROUP BY organization_id;
--
-- 3. RLS確認:
--    SELECT tablename, rowsecurity FROM pg_tables
--    WHERE tablename IN ('processed_messages', 'task_overdue_reminders',
--                        'task_limit_changes', 'dm_room_cache', 'task_escalations');
--
-- 4. ポリシー確認:
--    SELECT tablename, policyname FROM pg_policies
--    WHERE tablename IN ('processed_messages', 'task_overdue_reminders',
--                        'task_limit_changes', 'dm_room_cache', 'task_escalations');
--
-- ============================================================================
