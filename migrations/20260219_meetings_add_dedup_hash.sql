-- ============================================================================
-- Zoom議事録 重複登録防止: dedup_hashカラム追加
--
-- 目的:
--   source_meeting_id がNullの場合でも重複チェックを可能にする。
--   source + topic + start_time のSHA256ハッシュを冪等キーとして使用。
--
-- 背景:
--   Zoomのwebhookでmeeting_idが取れない場合、従来は重複チェックをスキップ
--   していた（zoom_brain_interface.py line 208）。その結果、同じ会議が
--   複数回トリガーされると議事録が重複して生成される問題があった。
--
-- ロールバック: 20260219_meetings_add_dedup_hash_rollback.sql
--
-- 作成日: 2026-02-19
-- ============================================================================

BEGIN;

-- dedup_hashカラム追加（既存テーブルへのALTER）
ALTER TABLE meetings
  ADD COLUMN IF NOT EXISTS dedup_hash VARCHAR(64);

-- 重複防止のためUNIQUEインデックス（同org内で同じhashの二重登録を防ぐ）
CREATE UNIQUE INDEX IF NOT EXISTS idx_meetings_dedup_hash
  ON meetings(organization_id, dedup_hash)
  WHERE dedup_hash IS NOT NULL;

COMMIT;
