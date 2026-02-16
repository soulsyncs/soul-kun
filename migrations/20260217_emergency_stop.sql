-- =============================================================================
-- 緊急停止テーブル（Emergency Stop）
-- =============================================================================
-- 目的: ソウルくんのTool実行を即座に停止できる緊急停止スイッチ
-- 用途: 暴走防止、インシデント対応
--
-- セキュリティ:
--   - RLS有効（organization_id分離）
--   - Level 5+のみ操作可能（API側で制御）
--   - activated_by で操作者を記録（監査ログ）
--
-- CLAUDE.md準拠:
--   鉄則#1  organization_id必須
--   鉄則#2  RLS有効
--   鉄則#3  監査ログ（activated_by, activated_at, deactivated_at）
--   鉄則#9  パラメータ化SQL（アプリ側）
--   鉄則#15 ロールバックSQL完備
-- =============================================================================

-- テーブル作成
CREATE TABLE IF NOT EXISTS emergency_stop (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,

    -- 停止状態
    is_active BOOLEAN NOT NULL DEFAULT FALSE,

    -- 操作者情報
    activated_by VARCHAR(255),       -- 有効化した人のuser_id
    deactivated_by VARCHAR(255),     -- 無効化した人のuser_id
    reason TEXT,                      -- 停止理由

    -- タイムスタンプ
    activated_at TIMESTAMPTZ,
    deactivated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 制約: 1組織につき1レコード
    CONSTRAINT uq_emergency_stop_org UNIQUE (organization_id)
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_emergency_stop_org
    ON emergency_stop (organization_id);
CREATE INDEX IF NOT EXISTS idx_emergency_stop_active
    ON emergency_stop (is_active) WHERE is_active = TRUE;

-- RLS 有効化
ALTER TABLE emergency_stop ENABLE ROW LEVEL SECURITY;

-- RLS ポリシー（organization_id分離）
-- NOTE: organization_idはUUID型だが、current_settingはTEXTを返すので::textで比較
CREATE POLICY emergency_stop_org_isolation
    ON emergency_stop
    USING (organization_id::text = current_setting('app.current_organization_id', true));

-- 初期レコード挿入（ソウルシンクス組織）
INSERT INTO emergency_stop (organization_id, is_active)
VALUES ('5f98365f-e7c5-4f48-9918-7fe9aabae5df', FALSE)
ON CONFLICT (organization_id) DO NOTHING;

-- =============================================================================
-- Rollback SQL
-- =============================================================================
-- DROP POLICY IF EXISTS emergency_stop_org_isolation ON emergency_stop;
-- DROP TABLE IF EXISTS emergency_stop;
