-- =============================================================================
-- Google OAuth Tokens テーブル
-- =============================================================================
-- 目的: 管理画面から接続したGoogleアカウントのOAuthトークンを保管
-- 用途: GoogleカレンダーAPI（Zoom議事録のルーム振り分け等）
--
-- セキュリティ:
--   - RLS有効（organization_id分離）
--   - access_token / refresh_token はアプリレベルで暗号化して保存
--   - 暗号化キーはGCP Secret Manager管理
--   - connected_by で操作者を記録（監査ログ）
--
-- CLAUDE.md準拠:
--   鉄則#1  organization_id必須
--   鉄則#2  RLS有効
--   鉄則#3  監査ログ（connected_by, connected_at, updated_at）
--   鉄則#9  パラメータ化SQL（アプリ側）
-- =============================================================================

-- テーブル作成
CREATE TABLE IF NOT EXISTS google_oauth_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,

    -- サービス識別（将来: google_drive, google_docs 等にも拡張可能）
    service_name VARCHAR(50) NOT NULL DEFAULT 'google_calendar',

    -- Google アカウント情報
    google_email VARCHAR(255),

    -- OAuth トークン（アプリレベルで暗号化済みの値を保存）
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    token_expiry TIMESTAMPTZ NOT NULL,
    scopes TEXT,

    -- 監査
    connected_by UUID,
    connected_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 状態管理
    is_active BOOLEAN DEFAULT TRUE,

    -- 制約: 1組織につき1サービス1接続
    CONSTRAINT uq_google_oauth_org_service UNIQUE (organization_id, service_name)
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_google_oauth_tokens_org
    ON google_oauth_tokens (organization_id);
CREATE INDEX IF NOT EXISTS idx_google_oauth_tokens_active
    ON google_oauth_tokens (is_active) WHERE is_active = TRUE;

-- RLS 有効化
ALTER TABLE google_oauth_tokens ENABLE ROW LEVEL SECURITY;

-- RLS ポリシー（organization_id分離）
-- NOTE: organization_idはUUID型だが、current_settingはTEXTを返すので::textで比較
CREATE POLICY google_oauth_tokens_org_isolation
    ON google_oauth_tokens
    USING (organization_id::text = current_setting('app.current_organization_id', true));

-- =============================================================================
-- Rollback SQL
-- =============================================================================
-- DROP POLICY IF EXISTS google_oauth_tokens_org_isolation ON google_oauth_tokens;
-- DROP TABLE IF EXISTS google_oauth_tokens;
