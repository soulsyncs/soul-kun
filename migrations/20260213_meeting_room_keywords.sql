-- Migration: meeting_room_keywords テーブル作成
-- Phase 4: ChatWorkグループ自動振り分け（Vision 12.2.3）
--
-- キーワード→ChatWorkルームIDのマッピングテーブル。
-- 会議タイトルに含まれるキーワードで投稿先を自動判定。
--
-- CLAUDE.md準拠:
--   鉄則#1: organization_id必須
--   鉄則#2: RLS有効化
--   鉄則#9: パラメータ化SQL（アプリ側）
--   §3-2 #15: ロールバック安全性（別ファイル）

BEGIN;

CREATE TABLE IF NOT EXISTS meeting_room_keywords (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id VARCHAR(255) NOT NULL,
    keyword VARCHAR(255) NOT NULL,
    chatwork_room_id VARCHAR(50) NOT NULL,
    room_name VARCHAR(255),
    priority INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(organization_id, keyword)
);

-- RLS有効化（CLAUDE.md鉄則#2）
ALTER TABLE meeting_room_keywords ENABLE ROW LEVEL SECURITY;

-- RLSポリシー: organization_idでテナント分離（WITH CHECK追加）
CREATE POLICY meeting_room_keywords_org_policy
    ON meeting_room_keywords
    FOR ALL
    USING (organization_id = current_setting('app.current_organization_id', true)::text)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::text);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_meeting_room_keywords_org
    ON meeting_room_keywords (organization_id);

COMMIT;
