-- ============================================================================
-- knowledge_proposalsテーブルにorganization_idカラムを追加
--
-- 目的: テナント分離（CLAUDE.md 鉄則#1: 全テーブルにorganization_idを追加）
-- 背景: knowledge_proposalsにorg_idカラムがなく、鉄則#1違反だった。
--
-- 注意:
-- - organization_idはVARCHAR(255)（slugベース、UUIDではない）
-- - RLSポリシーは::textキャスト
--
-- ロールバック: 20260209_knowledge_proposals_add_org_id_rollback.sql
--
-- 作成日: 2026-02-09
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. organization_idカラムを追加
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'knowledge_proposals'
          AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE knowledge_proposals ADD COLUMN organization_id VARCHAR(255);
    END IF;
END $$;

-- ============================================================================
-- 2. 既存データのバックフィル（全てデフォルト組織）
-- ============================================================================

UPDATE knowledge_proposals
  SET organization_id = 'org_soulsyncs'
  WHERE organization_id IS NULL;

-- ============================================================================
-- 3. NOT NULL制約を追加
-- ============================================================================

ALTER TABLE knowledge_proposals ALTER COLUMN organization_id SET NOT NULL;

-- ============================================================================
-- 4. インデックス追加
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_knowledge_proposals_org_id
  ON knowledge_proposals(organization_id);

CREATE INDEX IF NOT EXISTS idx_knowledge_proposals_org_status
  ON knowledge_proposals(organization_id, status);

-- ============================================================================
-- 5. RLS有効化（VARCHARカラム → ::textキャスト）
-- ============================================================================

ALTER TABLE knowledge_proposals ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS knowledge_proposals_org_isolation ON knowledge_proposals;
CREATE POLICY knowledge_proposals_org_isolation ON knowledge_proposals
  USING (organization_id::text = current_setting('app.current_organization_id', true)::text)
  WITH CHECK (organization_id::text = current_setting('app.current_organization_id', true)::text);

COMMIT;
