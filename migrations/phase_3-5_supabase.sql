-- ================================================================
-- Phase 3.5 マイグレーション: Supabase（組織図システム）
-- ================================================================
-- 実行日: 2026-01-XX
-- 作成者: Claude Code
--
-- このSQLはSupabaseの管理画面のSQLエディタで実行してください。
-- https://app.supabase.com/ にログイン → SQL Editor
-- ================================================================

-- ----------------------------------------------------------------
-- STEP 1: rolesテーブルの作成
-- ----------------------------------------------------------------

-- 1-1. テーブル作成
CREATE TABLE IF NOT EXISTS roles (
    -- 主キー: 人間が読めるID（例: role_ceo）
    id TEXT PRIMARY KEY,

    -- 役職名（例: 代表取締役）
    name TEXT NOT NULL,

    -- 権限レベル（1-6）
    -- 1=業務委託, 2=社員, 3=リーダー, 4=幹部/部長, 5=管理部, 6=代表/CFO
    level INTEGER NOT NULL DEFAULT 1 CHECK (level >= 1 AND level <= 6),

    -- 説明
    description TEXT,

    -- プルダウンでの表示順
    display_order INTEGER DEFAULT 0,

    -- 有効/無効フラグ
    is_active BOOLEAN DEFAULT TRUE,

    -- タイムスタンプ
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 1-2. コメント追加（テーブルの説明）
COMMENT ON TABLE roles IS '役職マスタ - 権限レベル管理用';
COMMENT ON COLUMN roles.id IS '役職ID（例: role_ceo）';
COMMENT ON COLUMN roles.name IS '役職名（例: 代表取締役）';
COMMENT ON COLUMN roles.level IS '権限レベル: 1=業務委託, 2=社員, 3=リーダー, 4=幹部/部長, 5=管理部, 6=代表/CFO';
COMMENT ON COLUMN roles.display_order IS 'プルダウンでの表示順（小さいほど上）';

-- 1-3. インデックス作成
CREATE INDEX IF NOT EXISTS idx_roles_level ON roles(level);
CREATE INDEX IF NOT EXISTS idx_roles_active ON roles(is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_roles_display_order ON roles(display_order);

-- 1-4. 更新時のタイムスタンプ自動更新トリガー
CREATE OR REPLACE FUNCTION update_roles_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS roles_updated_at_trigger ON roles;
CREATE TRIGGER roles_updated_at_trigger
    BEFORE UPDATE ON roles
    FOR EACH ROW
    EXECUTE FUNCTION update_roles_updated_at();

-- ----------------------------------------------------------------
-- STEP 2: 初期データの投入（11件）
-- ----------------------------------------------------------------

INSERT INTO roles (id, name, level, description, display_order) VALUES
    -- Level 6: 代表・CFO（最高権限）
    ('role_ceo', '代表取締役', 6, '最高経営責任者 - 全組織の全情報にアクセス可能', 1),
    ('role_cfo', 'CFO', 6, '最高財務責任者 - 全組織の全情報にアクセス可能', 2),
    ('role_coo', 'COO', 6, '最高執行責任者 - 全組織の全情報にアクセス可能', 3),

    -- Level 5: 管理部（全組織アクセス、最高機密除く）
    ('role_admin_mgr', '管理部マネージャー', 5, '管理部門責任者 - 全組織の情報にアクセス可能（財務機密除く）', 4),
    ('role_admin_staff', '管理部スタッフ', 5, '管理部門担当者 - 全組織の情報にアクセス可能（財務機密除く）', 5),

    -- Level 4: 幹部・部長（自部署＋配下）
    ('role_director', '取締役', 4, '幹部 - 自部署と配下部署の情報にアクセス可能', 6),
    ('role_dept_head', '部長', 4, '部門責任者 - 自部署と配下部署の情報にアクセス可能', 7),

    -- Level 3: リーダー（自部署＋直下）
    ('role_section_head', '課長', 3, '課責任者 - 自部署と直下部署の情報にアクセス可能', 8),
    ('role_leader', 'リーダー', 3, 'チームリーダー - 自部署と直下部署の情報にアクセス可能', 9),

    -- Level 2: 一般社員（自部署のみ）
    ('role_employee', '社員', 2, '一般社員 - 自部署の情報にアクセス可能', 10),

    -- Level 1: 業務委託（自部署のみ、制限あり）
    ('role_contractor', '業務委託', 1, '外部パートナー - 自部署の業務情報のみアクセス可能', 11)

-- 既存データがある場合は更新
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    level = EXCLUDED.level,
    description = EXCLUDED.description,
    display_order = EXCLUDED.display_order,
    updated_at = NOW();

-- ----------------------------------------------------------------
-- STEP 3: Row Level Security（RLS）の設定
-- ----------------------------------------------------------------

-- RLSを有効化
ALTER TABLE roles ENABLE ROW LEVEL SECURITY;

-- 読み取りは全員可能（認証なしでも可）
DROP POLICY IF EXISTS "roles_select_policy" ON roles;
CREATE POLICY "roles_select_policy" ON roles
    FOR SELECT
    USING (true);

-- 挿入・更新・削除は認証済みユーザーのみ
-- ※現状は認証機能がないため、コメントアウト
-- DROP POLICY IF EXISTS "roles_insert_policy" ON roles;
-- CREATE POLICY "roles_insert_policy" ON roles
--     FOR INSERT
--     WITH CHECK (auth.role() = 'authenticated');

-- DROP POLICY IF EXISTS "roles_update_policy" ON roles;
-- CREATE POLICY "roles_update_policy" ON roles
--     FOR UPDATE
--     USING (auth.role() = 'authenticated');

-- DROP POLICY IF EXISTS "roles_delete_policy" ON roles;
-- CREATE POLICY "roles_delete_policy" ON roles
--     FOR DELETE
--     USING (auth.role() = 'authenticated');

-- ----------------------------------------------------------------
-- STEP 4: employeesテーブルの修正
-- ----------------------------------------------------------------

-- 4-1. role_idカラムを追加（外部キー）
ALTER TABLE employees
ADD COLUMN IF NOT EXISTS role_id TEXT REFERENCES roles(id);

-- 4-2. インデックス作成
CREATE INDEX IF NOT EXISTS idx_employees_role_id ON employees(role_id);

-- 4-3. positionカラムにコメント追加（非推奨を明示）
COMMENT ON COLUMN employees.position IS '【非推奨】今後はrole_idを使用してください。後方互換性のために残しています。';
COMMENT ON COLUMN employees.role_id IS '役職ID（rolesテーブルへの外部キー）';

-- ----------------------------------------------------------------
-- 確認クエリ
-- ----------------------------------------------------------------

-- rolesテーブルの確認
-- SELECT id, name, level, description FROM roles ORDER BY display_order;

-- employeesテーブルのrole_idカラム確認
-- SELECT id, name, position, role_id FROM employees LIMIT 5;

-- ================================================================
-- 完了！
-- ================================================================
-- 次のステップ:
-- 1. Cloud SQLマイグレーションを実行
-- 2. app.jsを改修してデプロイ
-- 3. 既存社員に役職を手動で設定
-- ================================================================
