-- Rollback: meeting_room_keywords テーブル削除
-- Phase 4: ChatWorkグループ自動振り分け（Vision 12.2.3）
--
-- 対応マイグレーション: 20260213_meeting_room_keywords.sql
-- CLAUDE.md §3-2 #15: ロールバック安全性

BEGIN;

DROP POLICY IF EXISTS meeting_room_keywords_org_policy ON meeting_room_keywords;
DROP INDEX IF EXISTS idx_meeting_room_keywords_org;
DROP TABLE IF EXISTS meeting_room_keywords;

COMMIT;
