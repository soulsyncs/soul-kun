-- ============================================================================
-- soulkun_knowledge org_id追加のロールバック
--
-- 注意: RLSポリシー削除 → UNIQUE制約復元 → カラム削除の順
-- ============================================================================

BEGIN;

-- 1. RLSポリシーと有効化を取り消し
DROP POLICY IF EXISTS soulkun_knowledge_org_isolation ON soulkun_knowledge;
ALTER TABLE soulkun_knowledge DISABLE ROW LEVEL SECURITY;

-- 2. インデックス削除
DROP INDEX IF EXISTS idx_soulkun_knowledge_org_id;
DROP INDEX IF EXISTS idx_soulkun_knowledge_org_category;

-- 3. UNIQUE制約を元に戻す
ALTER TABLE soulkun_knowledge DROP CONSTRAINT IF EXISTS uq_soulkun_knowledge_org_cat_key;

-- 重複がある場合のみ旧UNIQUE制約を追加（安全策）
DO $$
BEGIN
    ALTER TABLE soulkun_knowledge ADD CONSTRAINT soulkun_knowledge_category_key_key UNIQUE (category, key);
EXCEPTION WHEN unique_violation THEN
    RAISE WARNING 'Cannot restore UNIQUE(category, key) - duplicate data exists';
END $$;

-- 4. organization_idカラムを削除
ALTER TABLE soulkun_knowledge DROP COLUMN IF EXISTS organization_id;

COMMIT;
