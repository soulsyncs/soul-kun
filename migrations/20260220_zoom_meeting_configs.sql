-- Migration: zoom_meeting_configs テーブル作成
-- Phase Z1 ②: 管理ダッシュボードZoom連携設定
--
-- 「この会議名のパターンはこのChatWorkルームへ」という設定を一元管理。
-- カレンダーの備考欄に毎回書く手間をなくす。
--
-- CLAUDE.md準拠:
--   鉄則#1: organization_id必須
--   鉄則#2: RLS有効化
--   鉄則#9: パラメータ化SQL（アプリ側）
--   §3-2 #15: ロールバック安全性（別ファイル）

BEGIN;

CREATE TABLE IF NOT EXISTS zoom_meeting_configs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     VARCHAR(255) NOT NULL,
    meeting_name_pattern TEXT NOT NULL,       -- 会議名のキーワード（例: "朝会", "週次MTG"）
    chatwork_room_id    VARCHAR(50) NOT NULL, -- 送信先ChatWorkルームID
    room_name           VARCHAR(255),         -- 管理用ラベル（例: "営業チームルーム"）
    is_active           BOOLEAN DEFAULT true,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(organization_id, meeting_name_pattern)
);

-- RLS有効化（CLAUDE.md鉄則#2）
ALTER TABLE zoom_meeting_configs ENABLE ROW LEVEL SECURITY;

-- RLSポリシー: organization_idでテナント分離
CREATE POLICY zoom_meeting_configs_org_policy
    ON zoom_meeting_configs
    FOR ALL
    USING (organization_id = current_setting('app.current_organization_id', true)::text)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::text);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_zoom_meeting_configs_org
    ON zoom_meeting_configs (organization_id);

CREATE INDEX IF NOT EXISTS idx_zoom_meeting_configs_active
    ON zoom_meeting_configs (organization_id, is_active);

COMMIT;
