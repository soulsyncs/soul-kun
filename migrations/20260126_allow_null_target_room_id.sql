-- Migration: Allow NULL target_room_id for pending_room status
-- Version: v10.26.9b
-- Date: 2026-01-26
-- Purpose: Enable room selection workflow where target_room_id is unknown initially

-- Allow NULL for target_room_id (needed for pending_room status)
ALTER TABLE scheduled_announcements
ALTER COLUMN target_room_id DROP NOT NULL;

-- Verify
SELECT column_name, is_nullable
FROM information_schema.columns
WHERE table_name = 'scheduled_announcements'
  AND column_name = 'target_room_id';
