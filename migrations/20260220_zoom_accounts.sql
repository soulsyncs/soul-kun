-- migrations/20260220_zoom_accounts.sql
-- Zoom 複数アカウント対応（Phase Z2 ③）
-- 各Zoomアカウントの account_id と webhook_secret_token を管理するテーブル。
-- 複数アカウントの議事録を一つのソウルくんで受け取るために使用。
--
-- ロールバック: 20260220_zoom_accounts_rollback.sql
-- Author: Claude Sonnet 4.6 (3AI合意: 2026-02-20)

CREATE TABLE IF NOT EXISTS zoom_accounts (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id       VARCHAR(255) NOT NULL,
    account_name          VARCHAR(255) NOT NULL,           -- 管理用ラベル（例: "営業部Zoom"）
    zoom_account_id       VARCHAR(255) NOT NULL,           -- Zoomの account_id（Zoom Appのダッシュボードで確認可能）
    webhook_secret_token  TEXT NOT NULL,                   -- Webhook Secret Token（Zoom App毎に異なる）
    default_room_id       VARCHAR(50),                     -- このアカウントのデフォルト送信先ChatWorkルームID
                                                           -- NULL の場合は zoom_meeting_configs のパターンマッチを優先
    is_active             BOOLEAN DEFAULT true,
    created_at            TIMESTAMPTZ DEFAULT NOW(),
    updated_at            TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(organization_id, zoom_account_id)
);

-- Row Level Security: 自組織のデータのみ参照・更新可能
ALTER TABLE zoom_accounts ENABLE ROW LEVEL SECURITY;

CREATE POLICY zoom_accounts_org_policy ON zoom_accounts
    FOR ALL
    USING (organization_id = current_setting('app.current_organization_id', true)::text)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::text);

-- インデックス: Webhook受信時の account_id 検索を高速化
CREATE INDEX IF NOT EXISTS idx_zoom_accounts_account_id
    ON zoom_accounts(zoom_account_id)
    WHERE is_active = true;
