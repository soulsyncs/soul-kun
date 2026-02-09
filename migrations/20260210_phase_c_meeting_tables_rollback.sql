-- ============================================================================
-- Phase C MVP0: ロールバック
--
-- 20260210_phase_c_meeting_tables.sql の逆操作
-- 依存関係の逆順で削除（子テーブル → 親テーブル）
--
-- 作成日: 2026-02-10
-- ============================================================================

BEGIN;

-- RLSポリシー削除
DROP POLICY IF EXISTS meeting_consent_logs_org_isolation ON meeting_consent_logs;
DROP POLICY IF EXISTS meeting_transcripts_org_isolation ON meeting_transcripts;
DROP POLICY IF EXISTS meeting_recordings_org_isolation ON meeting_recordings;
DROP POLICY IF EXISTS meetings_org_isolation ON meetings;

-- テーブル削除（子 → 親の順）
DROP TABLE IF EXISTS meeting_consent_logs;
DROP TABLE IF EXISTS meeting_transcripts;
DROP TABLE IF EXISTS meeting_recordings;
DROP TABLE IF EXISTS meetings;

COMMIT;
