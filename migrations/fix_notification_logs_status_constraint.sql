-- ================================================================
-- notification_logs.status CHECK制約修正
-- ================================================================
-- 作成日: 2026-01-23
-- 作成者: Claude Code
--
-- 問題:
--   notification_logs.status の CHECK制約に 'pending' が含まれておらず、
--   3フェーズパターン（Phase1: pending挿入 → Phase2: API呼出 → Phase3: success/failed更新）
--   の初期INSERT時にエラーが発生
--
-- 修正内容:
--   CHECK制約を更新して 'pending' を許可
-- ================================================================

-- 現在の制約を確認
SELECT conname, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conrelid = 'notification_logs'::regclass
  AND contype = 'c';

-- 既存のCHECK制約を削除
ALTER TABLE notification_logs DROP CONSTRAINT IF EXISTS check_status;

-- 新しいCHECK制約を追加（'pending' を含む）
ALTER TABLE notification_logs
ADD CONSTRAINT check_status
CHECK (status IN ('pending', 'success', 'failed', 'skipped'));

-- 確認
SELECT conname, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conrelid = 'notification_logs'::regclass
  AND contype = 'c';

-- コメント更新
COMMENT ON COLUMN notification_logs.status IS
'ステータス:
- pending: 送信処理中（3フェーズパターンの初期状態）
- success: 送信成功
- failed: 送信失敗
- skipped: スキップ（既に回答済み等）';
