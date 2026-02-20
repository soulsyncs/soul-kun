-- ============================================================
-- 雇用形態（employment_type）カラム追加
-- 作成日: 2026-02-20
-- 作成者: Claude Code
-- 対応フェーズ: org-chart-migration Phase S-1
-- 目的: 旧Supabase employees.employment_type を新システムに復元
-- ============================================================

-- users テーブルに employment_type カラムを追加
ALTER TABLE users
ADD COLUMN IF NOT EXISTS employment_type VARCHAR(50) NULL;

-- コメント
COMMENT ON COLUMN users.employment_type IS
'雇用形態。例: 正社員, 業務委託, パート, インターン, 顧問
旧Supabase employees.employment_type を Cloud SQL に移行したフィールド。';

-- インデックス（雇用形態別フィルタリング用）
CREATE INDEX IF NOT EXISTS idx_users_employment_type
ON users(organization_id, employment_type)
WHERE employment_type IS NOT NULL;
