-- ============================================================
-- ロールバック: 雇用形態（employment_type）カラム削除
-- ============================================================

DROP INDEX IF EXISTS idx_users_employment_type;

ALTER TABLE users
DROP COLUMN IF EXISTS employment_type;
