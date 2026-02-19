-- ============================================================================
-- ロールバック: dedup_hashカラム削除
--
-- 対応マイグレーション: 20260219_meetings_add_dedup_hash.sql
-- ============================================================================

BEGIN;

DROP INDEX IF EXISTS idx_meetings_dedup_hash;

ALTER TABLE meetings
  DROP COLUMN IF EXISTS dedup_hash;

COMMIT;
