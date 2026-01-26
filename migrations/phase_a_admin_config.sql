-- =====================================================
-- Phase A: 管理者設定のDB化 マイグレーション
-- バージョン: v10.30.1
-- 作成日: 2026-01-26
--
-- 概要:
--   ハードコードされた管理者設定（ADMIN_ACCOUNT_ID, ADMIN_ROOM_ID等）を
--   データベースで管理し、マルチテナント対応の基盤を構築する。
--
-- テーブル:
--   1. organization_admin_configs - 組織ごとの管理者設定
--
-- 背景:
--   - 10+ファイルに ADMIN_ACCOUNT_ID = "1728974" がハードコード
--   - 10+ファイルに ADMIN_ROOM_ID = 405315911 がハードコード
--   - Phase 4（マルチテナント）対応の前提条件
--
-- 10の鉄則チェック:
--   [x] #1 organization_id: 外部キーでorganizationsテーブルと連携
--   [x] #3 監査ログ: created_at, updated_at で記録
--   [x] #9 SQLインジェクション: パラメータ化クエリ前提
-- =====================================================

-- =====================================================
-- 1. organization_admin_configs テーブル
-- =====================================================
-- 組織ごとの管理者設定を一元管理

CREATE TABLE IF NOT EXISTS organization_admin_configs (
    -- =====================================================
    -- 主キー
    -- =====================================================
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- =====================================================
    -- 組織への参照（10の鉄則 #1）
    -- =====================================================
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- =====================================================
    -- 管理者アカウント設定
    -- =====================================================
    -- 管理者のChatWork account_id
    -- この人が承認権限を持ち、重要な通知を受け取る
    admin_account_id VARCHAR(50) NOT NULL,

    -- 管理者の名前（表示用、キャッシュ）
    admin_name VARCHAR(100),

    -- =====================================================
    -- 管理部ルーム設定
    -- =====================================================
    -- 管理部のグループチャットroom_id
    -- 組織全体の通知、レポート、エスカレーションの送信先
    admin_room_id VARCHAR(50) NOT NULL,

    -- 管理部ルームの名前（表示用、キャッシュ）
    admin_room_name VARCHAR(255),

    -- =====================================================
    -- 管理者DMルーム設定（オプション）
    -- =====================================================
    -- 管理者への1対1DMルームID
    -- 緊急通知、個別リマインドに使用
    admin_dm_room_id VARCHAR(50),

    -- =====================================================
    -- 追加の認可ルーム（オプション）
    -- =====================================================
    -- アナウンス機能等で認可されたルームID配列
    -- 管理部ルーム以外からも特定操作を許可する場合に使用
    authorized_room_ids BIGINT[] DEFAULT '{}',

    -- =====================================================
    -- ボットアカウント設定（オプション）
    -- =====================================================
    -- ソウルくん自身のChatWork account_id
    -- 自分自身へのメンション除外等に使用
    bot_account_id VARCHAR(50) DEFAULT '7399137',

    -- =====================================================
    -- 有効フラグ
    -- =====================================================
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    -- =====================================================
    -- 監査フィールド
    -- =====================================================
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),  -- 作成者（account_idまたはシステム）
    updated_by VARCHAR(100),  -- 更新者

    -- =====================================================
    -- 制約
    -- =====================================================
    -- 1組織につき1設定のみ
    CONSTRAINT uq_organization_admin_configs_org
        UNIQUE (organization_id)
);

-- updated_at自動更新トリガー
CREATE OR REPLACE FUNCTION update_organization_admin_configs_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_organization_admin_configs_updated_at ON organization_admin_configs;
CREATE TRIGGER trigger_update_organization_admin_configs_updated_at
    BEFORE UPDATE ON organization_admin_configs
    FOR EACH ROW
    EXECUTE FUNCTION update_organization_admin_configs_updated_at();

-- =====================================================
-- 2. インデックス
-- =====================================================

-- 組織IDでの検索（主要なアクセスパターン）
CREATE INDEX IF NOT EXISTS idx_organization_admin_configs_org
    ON organization_admin_configs(organization_id)
    WHERE is_active = TRUE;

-- 管理者account_idでの検索（権限チェック用）
CREATE INDEX IF NOT EXISTS idx_organization_admin_configs_admin_account
    ON organization_admin_configs(admin_account_id)
    WHERE is_active = TRUE;

-- 管理部ルームIDでの検索（ルーム特定用）
CREATE INDEX IF NOT EXISTS idx_organization_admin_configs_admin_room
    ON organization_admin_configs(admin_room_id)
    WHERE is_active = TRUE;

-- =====================================================
-- 3. コメント
-- =====================================================

COMMENT ON TABLE organization_admin_configs IS
    '組織ごとの管理者設定（Phase A: マルチテナント対応基盤）';

COMMENT ON COLUMN organization_admin_configs.admin_account_id IS
    '管理者のChatWork account_id。承認権限を持ち、重要通知を受け取る。例: 1728974';

COMMENT ON COLUMN organization_admin_configs.admin_room_id IS
    '管理部グループチャットのroom_id。組織全体の通知先。例: 405315911';

COMMENT ON COLUMN organization_admin_configs.admin_dm_room_id IS
    '管理者への1対1DMルームID。緊急通知用。例: 217825794';

COMMENT ON COLUMN organization_admin_configs.authorized_room_ids IS
    'アナウンス等で追加認可されたルームID配列。管理部以外からの操作許可用。';

COMMENT ON COLUMN organization_admin_configs.bot_account_id IS
    'ソウルくん自身のaccount_id。自己メンション除外用。デフォルト: 7399137';

-- =====================================================
-- 4. ソウルシンクス用初期データ
-- =====================================================
-- 既存のハードコード値をデータベースに移行

INSERT INTO organization_admin_configs (
    organization_id,
    admin_account_id,
    admin_name,
    admin_room_id,
    admin_room_name,
    admin_dm_room_id,
    authorized_room_ids,
    bot_account_id,
    is_active,
    created_by
)
VALUES (
    '5f98365f-e7c5-4f48-9918-7fe9aabae5df',  -- ソウルシンクスのorganization_id
    '1728974',                                -- カズさんのChatWork account_id
    '菊地雅克',                               -- カズさんの名前
    '405315911',                              -- 管理部グループチャット
    '管理部',                                 -- ルーム名
    '217825794',                              -- カズさんへのDMルーム
    ARRAY[405315911]::BIGINT[],              -- 認可ルーム（管理部）
    '7399137',                                -- ソウルくんのaccount_id
    TRUE,
    'migration_phase_a'
)
ON CONFLICT (organization_id)
DO UPDATE SET
    admin_account_id = EXCLUDED.admin_account_id,
    admin_name = EXCLUDED.admin_name,
    admin_room_id = EXCLUDED.admin_room_id,
    admin_room_name = EXCLUDED.admin_room_name,
    admin_dm_room_id = EXCLUDED.admin_dm_room_id,
    authorized_room_ids = EXCLUDED.authorized_room_ids,
    bot_account_id = EXCLUDED.bot_account_id,
    updated_by = 'migration_phase_a';

-- =====================================================
-- 5. 確認クエリ（実行後に確認用）
-- =====================================================

-- テーブル構造確認
-- \d organization_admin_configs

-- データ確認
-- SELECT
--     o.name as org_name,
--     c.admin_account_id,
--     c.admin_name,
--     c.admin_room_id,
--     c.admin_dm_room_id,
--     c.is_active
-- FROM organization_admin_configs c
-- JOIN organizations o ON c.organization_id = o.id;

-- =====================================================
-- 完了メッセージ
-- =====================================================
DO $$
BEGIN
    RAISE NOTICE '========================================';
    RAISE NOTICE 'Phase A: 管理者設定のDB化 マイグレーション完了';
    RAISE NOTICE '========================================';
    RAISE NOTICE '作成されたテーブル:';
    RAISE NOTICE '  1. organization_admin_configs';
    RAISE NOTICE '';
    RAISE NOTICE '初期データ:';
    RAISE NOTICE '  - ソウルシンクス (org_id: 5f98365f-e7c5-4f48-9918-7fe9aabae5df)';
    RAISE NOTICE '  - 管理者: 菊地雅克 (account_id: 1728974)';
    RAISE NOTICE '  - 管理部ルーム: 405315911';
    RAISE NOTICE '';
    RAISE NOTICE '次のステップ:';
    RAISE NOTICE '  1. lib/admin_config.py を作成';
    RAISE NOTICE '  2. 各ファイルのハードコードを置換';
    RAISE NOTICE '========================================';
END $$;
