-- ============================================================================
-- room_messagesテーブルにorganization_idカラムを追加
--
-- 目的: テナント分離（CLAUDE.md 鉄則#1: 全テーブルにorganization_idを追加）
-- 背景: emotion_detector, personalization_detector がroom_messagesをorg_id無しで参照している
--
-- ロールバック: 20260208_room_messages_add_org_id_rollback.sql
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
        RAISE EXCEPTION 'Organization with slug "org_soulsyncs" not found. Aborting migration.';
    END IF;
END $$;

-- ============================================================================
-- 1. organization_idカラム追加
-- ============================================================================
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'room_messages' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE room_messages ADD COLUMN organization_id UUID;
    END IF;
END $$;

-- ============================================================================
-- 2. 既存データにデフォルトorganization_idを設定
-- ============================================================================
DO $$
DECLARE
    _org_uuid UUID;
BEGIN
    SELECT id INTO _org_uuid FROM organizations WHERE slug = 'org_soulsyncs' LIMIT 1;
    UPDATE room_messages SET organization_id = _org_uuid WHERE organization_id IS NULL;
END $$;

-- ============================================================================
-- 3. NOT NULL制約
-- ============================================================================
ALTER TABLE room_messages ALTER COLUMN organization_id SET NOT NULL;

-- ============================================================================
-- 4. インデックス追加
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_room_messages_org_id ON room_messages(organization_id);
CREATE INDEX IF NOT EXISTS idx_room_messages_org_send_time ON room_messages(organization_id, send_time DESC);

-- ============================================================================
-- 5. 外部キー制約
-- ============================================================================
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_schema = 'public'
          AND constraint_name = 'fk_room_messages_organization_id'
          AND table_name = 'room_messages'
    ) THEN
        ALTER TABLE room_messages
            ADD CONSTRAINT fk_room_messages_organization_id
            FOREIGN KEY (organization_id) REFERENCES organizations(id);
    END IF;
END $$;

-- ============================================================================
-- 6. RLS有効化
-- ============================================================================
ALTER TABLE room_messages ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS room_messages_org_isolation ON room_messages;
CREATE POLICY room_messages_org_isolation ON room_messages
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);

COMMIT;
