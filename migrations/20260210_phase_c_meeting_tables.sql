-- ============================================================================
-- Phase C MVP0: 会議文字起こし用テーブル作成
--
-- 目的: 会議録音の文字起こし・議事録自動生成の永続化層
-- 対象: 4テーブル新規作成
--   1. meetings              - 会議メタデータ
--   2. meeting_recordings    - 録音ファイル参照（GCS）
--   3. meeting_transcripts   - 文字起こし結果（PII除去版 + 原文TTL90日）
--   4. meeting_consent_logs  - 録音同意ログ（PDPA準拠）
--
-- 注意:
-- - 全テーブルのorganization_idはVARCHAR(100)（slugベース、UUIDではない）
-- - RLSポリシーは::textキャスト（VARCHARカラムに::uuidは本番エラーになる）
-- - DELETE CASCADEで同意撤回時の即時データ削除を保証（Codex Fix #3）
-- - brain_approvedフラグでBrain承認なしのChatWork投稿を防止（Codex Fix #1）
--
-- ロールバック: 20260210_phase_c_meeting_tables_rollback.sql
--
-- 作成日: 2026-02-10
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. meetings - 会議メタデータ
-- ============================================================================

CREATE TABLE IF NOT EXISTS meetings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id VARCHAR(100) NOT NULL DEFAULT 'org_soulsyncs',
    title VARCHAR(500),
    meeting_type VARCHAR(50) NOT NULL DEFAULT 'unknown',
    meeting_date TIMESTAMPTZ,
    duration_seconds FLOAT DEFAULT 0,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    source VARCHAR(50) NOT NULL DEFAULT 'manual_upload',
    source_meeting_id VARCHAR(255),
    room_id VARCHAR(100),
    created_by VARCHAR(100),
    brain_approved BOOLEAN NOT NULL DEFAULT FALSE,
    transcript_sanitized BOOLEAN NOT NULL DEFAULT FALSE,
    attendees_count INTEGER DEFAULT 0,
    speakers_detected INTEGER DEFAULT 0,
    document_url VARCHAR(1000),
    document_id VARCHAR(255),
    total_tokens_used INTEGER DEFAULT 0,
    estimated_cost_jpy FLOAT DEFAULT 0,
    error_message TEXT,
    error_code VARCHAR(50),
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_meetings_org_id
  ON meetings(organization_id);
CREATE INDEX IF NOT EXISTS idx_meetings_status
  ON meetings(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_meetings_created_by
  ON meetings(organization_id, created_by);
CREATE INDEX IF NOT EXISTS idx_meetings_created_at
  ON meetings(created_at);

ALTER TABLE meetings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS meetings_org_isolation ON meetings;
CREATE POLICY meetings_org_isolation ON meetings
  USING (organization_id::text = current_setting('app.current_organization_id', true)::text)
  WITH CHECK (organization_id::text = current_setting('app.current_organization_id', true)::text);

-- ============================================================================
-- 2. meeting_recordings - 録音ファイル参照
-- ============================================================================

CREATE TABLE IF NOT EXISTS meeting_recordings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id VARCHAR(100) NOT NULL DEFAULT 'org_soulsyncs',
    meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    gcs_path VARCHAR(1000) NOT NULL,
    file_size_bytes BIGINT DEFAULT 0,
    duration_seconds FLOAT DEFAULT 0,
    format VARCHAR(20),
    sample_rate INTEGER,
    channels INTEGER DEFAULT 1,
    retention_expires_at TIMESTAMPTZ NOT NULL,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_meeting_recordings_org
  ON meeting_recordings(organization_id);
CREATE INDEX IF NOT EXISTS idx_meeting_recordings_meeting
  ON meeting_recordings(meeting_id);
CREATE INDEX IF NOT EXISTS idx_meeting_recordings_retention
  ON meeting_recordings(retention_expires_at) WHERE NOT is_deleted;

ALTER TABLE meeting_recordings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS meeting_recordings_org_isolation ON meeting_recordings;
CREATE POLICY meeting_recordings_org_isolation ON meeting_recordings
  USING (organization_id::text = current_setting('app.current_organization_id', true)::text)
  WITH CHECK (organization_id::text = current_setting('app.current_organization_id', true)::text);

-- ============================================================================
-- 3. meeting_transcripts - 文字起こし結果
-- ============================================================================

CREATE TABLE IF NOT EXISTS meeting_transcripts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id VARCHAR(100) NOT NULL DEFAULT 'org_soulsyncs',
    meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    raw_transcript TEXT,
    sanitized_transcript TEXT,
    segments_json JSONB,
    speakers_json JSONB,
    detected_language VARCHAR(10) DEFAULT 'ja',
    word_count INTEGER DEFAULT 0,
    confidence FLOAT DEFAULT 0,
    retention_expires_at TIMESTAMPTZ NOT NULL,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_meeting_transcripts_org
  ON meeting_transcripts(organization_id);
CREATE INDEX IF NOT EXISTS idx_meeting_transcripts_meeting
  ON meeting_transcripts(meeting_id);

ALTER TABLE meeting_transcripts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS meeting_transcripts_org_isolation ON meeting_transcripts;
CREATE POLICY meeting_transcripts_org_isolation ON meeting_transcripts
  USING (organization_id::text = current_setting('app.current_organization_id', true)::text)
  WITH CHECK (organization_id::text = current_setting('app.current_organization_id', true)::text);

-- ============================================================================
-- 4. meeting_consent_logs - 録音同意ログ
-- ============================================================================

CREATE TABLE IF NOT EXISTS meeting_consent_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id VARCHAR(100) NOT NULL DEFAULT 'org_soulsyncs',
    meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    user_id VARCHAR(100) NOT NULL,
    consent_type VARCHAR(30) NOT NULL,
    consent_method VARCHAR(50) NOT NULL DEFAULT 'chatwork_message',
    ip_address VARCHAR(45),
    user_agent VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_meeting_consent_org
  ON meeting_consent_logs(organization_id);
CREATE INDEX IF NOT EXISTS idx_meeting_consent_meeting
  ON meeting_consent_logs(meeting_id);
CREATE INDEX IF NOT EXISTS idx_meeting_consent_user
  ON meeting_consent_logs(organization_id, user_id);

ALTER TABLE meeting_consent_logs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS meeting_consent_logs_org_isolation ON meeting_consent_logs;
CREATE POLICY meeting_consent_logs_org_isolation ON meeting_consent_logs
  USING (organization_id::text = current_setting('app.current_organization_id', true)::text)
  WITH CHECK (organization_id::text = current_setting('app.current_organization_id', true)::text);

COMMIT;
