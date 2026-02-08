-- ============================================================================
-- soulkun_knowledgeテーブルにorganization_idカラムを追加
--
-- 目的: テナント分離（CLAUDE.md 鉄則#1: 全テーブルにorganization_idを追加）
-- 背景: soulkun_knowledgeは唯一org_idカラムがないナレッジテーブル。
--        これまではキー接頭辞 [org_id:key_name] でorg分離していたが、
--        Phase 4ではRLS対応のため明示的なカラムが必要。
--
-- 注意:
-- - soulkun_knowledge.organization_idはVARCHAR(255)（slugベース、UUIDではない）
-- - RLSポリシーは::textキャスト（VARCHARカラムに::uuidは本番エラーになる）
-- - UNIQUE制約を(category, key)から(organization_id, category, key)に変更
--
-- ロールバック: 20260208_soulkun_knowledge_add_org_id_rollback.sql
--
-- 作成日: 2026-02-08
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. organization_idカラムを追加（nullable → 後でNOT NULL化）
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'soulkun_knowledge'
          AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE soulkun_knowledge ADD COLUMN organization_id VARCHAR(255);
    END IF;
END $$;

-- ============================================================================
-- 2. 既存データのバックフィル（キー接頭辞パターンから抽出）
-- ============================================================================
-- 安全性: 本番環境は現在 org_soulsyncs のみの単一テナント。
-- キー形式が [org_soulsyncs:xxx] パターンの場合は正規表現で org_id を抽出し、
-- それ以外（プレフィクスなし）はデフォルト組織 'org_soulsyncs' を設定する。
-- 将来マルチテナント化する際は、テナント固有のバックフィルスクリプトを別途作成すること。
-- キー形式: [org_soulsyncs:actual_key] → organization_id = 'org_soulsyncs'

UPDATE soulkun_knowledge
  SET organization_id = substring(key FROM '^\[([^:]+):')
  WHERE organization_id IS NULL
  AND key LIKE '[%:%';

-- 接頭辞パターンに一致しない行はデフォルト組織を設定
UPDATE soulkun_knowledge
  SET organization_id = 'org_soulsyncs'
  WHERE organization_id IS NULL;

-- ============================================================================
-- 2.5. キーからプレフィクスを除去
-- ============================================================================
-- パターン1: "[org:category] subject" → "subject"（memory_flushが書くフォーマット）
UPDATE soulkun_knowledge
  SET key = substring(key FROM '^\[[^\]]+\] (.+)$')
  WHERE key ~ '^\[[^\]]+\] .+';

-- パターン2: "[org:key_name]" → "key_name"（単純ブラケットフォーマット）
UPDATE soulkun_knowledge
  SET key = substring(key FROM '^\[[^:]+:(.+)\]$')
  WHERE key ~ '^\[[^:]+:.+\]$';

-- ============================================================================
-- 3. NOT NULL制約を追加
-- ============================================================================

ALTER TABLE soulkun_knowledge ALTER COLUMN organization_id SET NOT NULL;

-- ============================================================================
-- 4. UNIQUE制約を更新（org_id込みに変更）
-- ============================================================================
-- 旧: UNIQUE(category, key) → 新: UNIQUE(organization_id, category, key)

-- 旧制約を安全に削除
DO $$
DECLARE
    _constraint_name TEXT;
BEGIN
    SELECT constraint_name INTO _constraint_name
    FROM information_schema.table_constraints
    WHERE table_schema = 'public'
      AND table_name = 'soulkun_knowledge'
      AND constraint_type = 'UNIQUE';

    IF _constraint_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE soulkun_knowledge DROP CONSTRAINT %I', _constraint_name);
    END IF;
END $$;

-- 新しいUNIQUE制約を追加
ALTER TABLE soulkun_knowledge
  ADD CONSTRAINT uq_soulkun_knowledge_org_cat_key
  UNIQUE (organization_id, category, key);

-- ============================================================================
-- 5. インデックス追加（org_idフィルター高速化）
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_soulkun_knowledge_org_id
  ON soulkun_knowledge(organization_id);

-- org_id + category の複合インデックス
CREATE INDEX IF NOT EXISTS idx_soulkun_knowledge_org_category
  ON soulkun_knowledge(organization_id, category);

-- ============================================================================
-- 6. RLS有効化（VARCHARカラム → ::textキャスト）
-- ============================================================================

ALTER TABLE soulkun_knowledge ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS soulkun_knowledge_org_isolation ON soulkun_knowledge;
CREATE POLICY soulkun_knowledge_org_isolation ON soulkun_knowledge
  USING (organization_id::text = current_setting('app.current_organization_id', true)::text)
  WITH CHECK (organization_id::text = current_setting('app.current_organization_id', true)::text);

COMMIT;

-- ============================================================================
-- 検証クエリ（実行後の確認用）
-- ============================================================================
--
-- 1. カラム確認:
--    SELECT column_name, data_type, is_nullable
--    FROM information_schema.columns
--    WHERE table_name = 'soulkun_knowledge' AND column_name = 'organization_id';
--
-- 2. バックフィル確認:
--    SELECT organization_id, COUNT(*) FROM soulkun_knowledge GROUP BY organization_id;
--
-- 3. RLS確認:
--    SELECT tablename, rowsecurity FROM pg_tables
--    WHERE tablename = 'soulkun_knowledge';
--
-- 4. ポリシー確認:
--    SELECT tablename, policyname FROM pg_policies
--    WHERE tablename = 'soulkun_knowledge';
--
-- ============================================================================
