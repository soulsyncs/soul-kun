-- Migration: Add 'pending_room' status to scheduled_announcements
-- Version: v10.26.9
-- Date: 2026-01-26
-- Purpose: Enable room selection workflow state persistence

-- Drop and recreate CHECK constraint to add 'pending_room' status
ALTER TABLE scheduled_announcements
DROP CONSTRAINT IF EXISTS scheduled_announcements_status_check;

ALTER TABLE scheduled_announcements
ADD CONSTRAINT scheduled_announcements_status_check
CHECK (status IN (
    'pending',       -- 依頼受付、確認待ち
    'pending_room',  -- ルーム選択待ち (v10.26.9)
    'confirmed',     -- ユーザー確認済み、実行/スケジュール待ち
    'scheduled',     -- スケジュール登録済み
    'executing',     -- 実行中
    'completed',     -- 完了（単発の場合）
    'failed',        -- 失敗
    'cancelled',     -- キャンセル
    'paused'         -- 一時停止（繰り返しの場合）
));

-- Verify
SELECT conname, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conrelid = 'scheduled_announcements'::regclass
  AND conname = 'scheduled_announcements_status_check';
