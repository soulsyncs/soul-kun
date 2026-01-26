-- ============================================================
-- Phase 4準備: ユーザーテーブル設計修正
-- v10.30.0
-- ============================================================
--
-- 目的:
-- 1. chatwork_users テーブルのマルチテナント対応
-- 2. users テーブルにChatWork ID複合キー制約追加
-- 3. 10の鉄則準拠（organization_idフィルタ必須化）
--
-- 実行手順:
-- 1. 本番DBにCloud SQL Proxyで接続
-- 2. このSQLを実行
-- 3. chatwork-webhookをデプロイ
--
-- ロールバック:
-- 最後のセクションのロールバックSQLを実行
-- ============================================================

-- ============================================================
-- STEP 1: chatwork_users テーブルの修正
-- ============================================================

-- 1-0. room_id カラムを追加（存在しない場合）
-- 最後に見たルームIDを記録
ALTER TABLE chatwork_users
ADD COLUMN IF NOT EXISTS room_id VARCHAR(50);

COMMENT ON COLUMN chatwork_users.room_id IS
'最後に見つかったルームID（同期時に更新）';

-- 1-1. organization_id の型をUUIDに変更するため、まず一時カラムを作成
ALTER TABLE chatwork_users
ADD COLUMN IF NOT EXISTS organization_uuid UUID;

-- 1-2. 既存データをUUIDに変換
-- 'soul_syncs' → '5f98365f-e7c5-4f48-9918-7fe9aabae5df' (Soul Syncs)
UPDATE chatwork_users
SET organization_uuid = '5f98365f-e7c5-4f48-9918-7fe9aabae5df'::uuid
WHERE organization_id = 'soul_syncs' OR organization_id IS NULL;

-- 1-3. 旧カラムを削除し、新カラムをリネーム
ALTER TABLE chatwork_users DROP COLUMN IF EXISTS organization_id;
ALTER TABLE chatwork_users RENAME COLUMN organization_uuid TO organization_id;

-- 1-4. NOT NULL制約とデフォルト値を設定
ALTER TABLE chatwork_users
ALTER COLUMN organization_id SET NOT NULL;

ALTER TABLE chatwork_users
ALTER COLUMN organization_id SET DEFAULT '5f98365f-e7c5-4f48-9918-7fe9aabae5df'::uuid;

-- 1-5. organization_id にインデックスを追加
CREATE INDEX IF NOT EXISTS idx_chatwork_users_org
ON chatwork_users(organization_id);

-- 1-6. 複合ユニーク制約を追加（organization_id + account_id）
-- 既存のaccount_id単独のユニーク制約を削除
ALTER TABLE chatwork_users
DROP CONSTRAINT IF EXISTS chatwork_users_account_id_key;

-- 新しい複合ユニーク制約を追加
ALTER TABLE chatwork_users
ADD CONSTRAINT unique_org_account_id UNIQUE(organization_id, account_id);

-- コメント追加
COMMENT ON COLUMN chatwork_users.organization_id IS
'組織ID（マルチテナント対応）。10の鉄則 #1 準拠。
デフォルト: Soul Syncs (5f98365f-e7c5-4f48-9918-7fe9aabae5df)';

-- ============================================================
-- STEP 2: users テーブルの修正
-- ============================================================

-- 2-1. chatwork_account_id にインデックスを追加（まだない場合）
CREATE INDEX IF NOT EXISTS idx_users_chatwork_account
ON users(chatwork_account_id)
WHERE chatwork_account_id IS NOT NULL;

-- 2-2. 複合ユニーク制約を追加（organization_id + chatwork_account_id）
-- Phase 4マルチテナント対応: 同じChatWork IDが複数組織に存在可能にしつつ、
-- 同一組織内での重複を防止
ALTER TABLE users
ADD CONSTRAINT unique_org_chatwork_account_id
UNIQUE(organization_id, chatwork_account_id);

-- コメント追加
COMMENT ON CONSTRAINT unique_org_chatwork_account_id ON users IS
'Phase 4マルチテナント対応: 同一組織内でChatWork IDの重複を防止。
異なる組織では同じChatWork IDを持つユーザーが存在可能。';

-- ============================================================
-- STEP 3: 検証クエリ
-- ============================================================

-- chatwork_users の状態確認
SELECT
    organization_id,
    COUNT(*) as count,
    COUNT(DISTINCT account_id) as unique_accounts
FROM chatwork_users
GROUP BY organization_id;

-- users の状態確認
SELECT
    organization_id,
    COUNT(*) as total_users,
    COUNT(chatwork_account_id) as users_with_chatwork_id
FROM users
GROUP BY organization_id;

-- ============================================================
-- ロールバック（必要な場合のみ実行）
-- ============================================================
/*
-- chatwork_users のロールバック
ALTER TABLE chatwork_users DROP CONSTRAINT IF EXISTS unique_org_account_id;
ALTER TABLE chatwork_users ADD CONSTRAINT chatwork_users_account_id_key UNIQUE(account_id);
DROP INDEX IF EXISTS idx_chatwork_users_org;
ALTER TABLE chatwork_users ALTER COLUMN organization_id DROP NOT NULL;
ALTER TABLE chatwork_users ALTER COLUMN organization_id DROP DEFAULT;

-- users のロールバック
ALTER TABLE users DROP CONSTRAINT IF EXISTS unique_org_chatwork_account_id;
DROP INDEX IF EXISTS idx_users_chatwork_account;
*/
