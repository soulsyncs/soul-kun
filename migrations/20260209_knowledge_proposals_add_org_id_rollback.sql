-- ============================================================================
-- knowledge_proposals org_id追加のロールバック
-- ============================================================================

BEGIN;

-- 1. RLSポリシーと有効化を取り消し
DROP POLICY IF EXISTS knowledge_proposals_org_isolation ON knowledge_proposals;
ALTER TABLE knowledge_proposals DISABLE ROW LEVEL SECURITY;

-- 2. インデックス削除
DROP INDEX IF EXISTS idx_knowledge_proposals_org_id;
DROP INDEX IF EXISTS idx_knowledge_proposals_org_status;

-- 3. organization_idカラムを削除
ALTER TABLE knowledge_proposals DROP COLUMN IF EXISTS organization_id;

COMMIT;
