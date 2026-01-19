-- ================================================================
-- Phase 3.5 完全版マイグレーション: Supabase（組織図システム）
-- ================================================================
-- 作成日: 2026-01-19
-- 作成者: Claude Code
-- バージョン: 2.0 (ダブルチェック済み)
--
-- このSQLはSupabaseの管理画面のSQLエディタで実行してください。
-- https://app.supabase.com/ にログイン → SQL Editor
--
-- 注意事項:
--   1. 既存のrolesテーブルがある場合はSTEP 1-1がスキップされます
--   2. 初期データはUPSERT（存在すれば更新、なければ挿入）
--   3. employeesテーブルが存在しない場合はSTEP 4がスキップされます
-- ================================================================

-- ================================================================
-- STEP 0: 事前確認（必須）
-- ================================================================

-- 0-1. 現在のテーブル一覧を確認
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;

-- 0-2. rolesテーブルの存在確認
SELECT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'roles'
) as roles_table_exists;

-- 0-3. employeesテーブルの存在確認
SELECT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'employees'
) as employees_table_exists;

-- 0-4. employeesテーブルのカラム確認（role_idが既にあるか）
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'employees'
ORDER BY ordinal_position;

-- ================================================================
-- STEP 1: rolesテーブルの作成
-- ================================================================

-- 1-1. テーブル作成（存在しない場合のみ）
CREATE TABLE IF NOT EXISTS roles (
    -- 主キー: 人間が読めるID（例: role_ceo）
    -- ※ Cloud SQL側ではexternal_idとしてこの値を保存
    id TEXT PRIMARY KEY,

    -- 役職名（例: 代表取締役）
    name TEXT NOT NULL,

    -- 権限レベル（1-6）
    -- 1=業務委託, 2=社員, 3=リーダー, 4=幹部/部長, 5=管理部, 6=代表/CFO
    level INTEGER NOT NULL DEFAULT 1 CHECK (level >= 1 AND level <= 6),

    -- 説明
    description TEXT,

    -- プルダウンでの表示順（小さいほど上）
    display_order INTEGER DEFAULT 0,

    -- 有効/無効フラグ
    is_active BOOLEAN DEFAULT TRUE,

    -- タイムスタンプ
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 1-2. コメント追加
COMMENT ON TABLE roles IS '役職マスタ - 6段階権限レベル管理用（Phase 3.5）';
COMMENT ON COLUMN roles.id IS '役職ID（例: role_ceo）- Cloud SQL側のroles.external_idに同期';
COMMENT ON COLUMN roles.name IS '役職名（例: 代表取締役）';
COMMENT ON COLUMN roles.level IS '権限レベル: 1=業務委託, 2=社員, 3=リーダー, 4=幹部/部長, 5=管理部, 6=代表/CFO';
COMMENT ON COLUMN roles.display_order IS 'プルダウンでの表示順（小さいほど上に表示）';
COMMENT ON COLUMN roles.is_active IS '有効フラグ - FALSEの役職は選択不可';

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

-- ================================================================
-- STEP 2: 初期データの投入（11件）
-- ================================================================

-- UPSERT: 存在すれば更新、なければ挿入
INSERT INTO roles (id, name, level, description, display_order) VALUES
    -- Level 6: 代表・CFO（最高権限）- 全組織の全情報にアクセス可能
    ('role_ceo', '代表取締役', 6, '最高経営責任者 - 全組織の全情報にアクセス可能', 1),
    ('role_cfo', 'CFO', 6, '最高財務責任者 - 全組織の全情報にアクセス可能', 2),
    ('role_coo', 'COO', 6, '最高執行責任者 - 全組織の全情報にアクセス可能', 3),

    -- Level 5: 管理部（全組織アクセス、最高機密除く）
    ('role_admin_mgr', '管理部マネージャー', 5, '管理部門責任者 - 全組織の情報にアクセス可能（財務機密除く）', 4),
    ('role_admin_staff', '管理部スタッフ', 5, '管理部門担当者 - 全組織の情報にアクセス可能（財務機密除く）', 5),

    -- Level 4: 幹部・部長（自部署＋配下全部署）
    ('role_director', '取締役', 4, '幹部 - 自部署と配下部署の情報にアクセス可能', 6),
    ('role_dept_head', '部長', 4, '部門責任者 - 自部署と配下部署の情報にアクセス可能', 7),

    -- Level 3: リーダー（自部署＋直下部署のみ）
    ('role_section_head', '課長', 3, '課責任者 - 自部署と直下部署の情報にアクセス可能', 8),
    ('role_leader', 'リーダー', 3, 'チームリーダー - 自部署と直下部署の情報にアクセス可能', 9),

    -- Level 2: 一般社員（自部署のみ）
    ('role_employee', '社員', 2, '一般社員 - 自部署の情報にアクセス可能', 10),

    -- Level 1: 業務委託（自部署のみ、制限あり）
    ('role_contractor', '業務委託', 1, '外部パートナー - 自部署の業務情報のみアクセス可能', 11)

ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    level = EXCLUDED.level,
    description = EXCLUDED.description,
    display_order = EXCLUDED.display_order,
    updated_at = NOW();

-- 2-1. 投入結果の確認
SELECT id, name, level, description, display_order, is_active
FROM roles
ORDER BY display_order;

-- ================================================================
-- STEP 3: Row Level Security（RLS）の設定
-- ================================================================

-- 3-1. RLSを有効化
ALTER TABLE roles ENABLE ROW LEVEL SECURITY;

-- 3-2. 読み取りは全員可能（認証なしでも可）
-- ※ app.jsから匿名キーでアクセスするため
DROP POLICY IF EXISTS "roles_select_policy" ON roles;
CREATE POLICY "roles_select_policy" ON roles
    FOR SELECT
    USING (true);

-- 3-3. 挿入・更新・削除も現状は許可（管理者専用UIから操作）
-- ※ 将来的には認証を追加予定（Phase 4A）
DROP POLICY IF EXISTS "roles_insert_policy" ON roles;
CREATE POLICY "roles_insert_policy" ON roles
    FOR INSERT
    WITH CHECK (true);

DROP POLICY IF EXISTS "roles_update_policy" ON roles;
CREATE POLICY "roles_update_policy" ON roles
    FOR UPDATE
    USING (true);

DROP POLICY IF EXISTS "roles_delete_policy" ON roles;
CREATE POLICY "roles_delete_policy" ON roles
    FOR DELETE
    USING (true);

-- ================================================================
-- STEP 4: employeesテーブルの修正
-- ================================================================

-- 4-1. role_idカラムを追加（外部キー）
-- ※ employeesテーブルが存在しない場合はスキップされます
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'employees'
    ) THEN
        -- role_idカラムが存在しない場合のみ追加
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'employees'
              AND column_name = 'role_id'
        ) THEN
            ALTER TABLE employees ADD COLUMN role_id TEXT REFERENCES roles(id);
            RAISE NOTICE 'role_id column added to employees table';
        ELSE
            RAISE NOTICE 'role_id column already exists in employees table';
        END IF;
    ELSE
        RAISE NOTICE 'employees table does not exist, skipping role_id addition';
    END IF;
END $$;

-- 4-2. インデックス作成
CREATE INDEX IF NOT EXISTS idx_employees_role_id ON employees(role_id);

-- 4-3. コメント追加
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'employees'
          AND column_name = 'position'
    ) THEN
        COMMENT ON COLUMN employees.position IS '【非推奨】今後はrole_idを使用してください。後方互換性のために残しています。';
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'employees'
          AND column_name = 'role_id'
    ) THEN
        COMMENT ON COLUMN employees.role_id IS '役職ID（rolesテーブルへの外部キー）- Cloud SQLに同期';
    END IF;
END $$;

-- ================================================================
-- STEP 5: 最終確認（必須）
-- ================================================================

-- 5-1. rolesテーブルの構造確認
SELECT
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'roles'
ORDER BY ordinal_position;

-- 5-2. rolesテーブルのデータ確認
SELECT id, name, level, description, display_order, is_active
FROM roles
ORDER BY display_order;

-- 5-3. employeesテーブルの構造確認（存在する場合）
SELECT
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'employees'
ORDER BY ordinal_position;

-- 5-4. employeesテーブルのrole_id設定状況確認（存在する場合）
SELECT
    e.id,
    e.name,
    e.position,
    e.role_id,
    r.name as role_name,
    r.level as role_level
FROM employees e
LEFT JOIN roles r ON e.role_id = r.id
LIMIT 10;

-- 5-5. RLSポリシーの確認
SELECT
    schemaname,
    tablename,
    policyname,
    permissive,
    roles,
    cmd,
    qual
FROM pg_policies
WHERE tablename = 'roles';

-- 5-6. インデックスの確認
SELECT
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE tablename IN ('roles', 'employees')
  AND schemaname = 'public'
ORDER BY tablename, indexname;

-- ================================================================
-- 完了サマリー
-- ================================================================
SELECT
    'Phase 3.5 Supabase Migration Completed!' as status,
    (SELECT COUNT(*) FROM roles) as total_roles,
    (SELECT COUNT(*) FROM roles WHERE is_active = TRUE) as active_roles,
    NOW() as completed_at;

-- ================================================================
-- ロールバック用SQL（問題発生時）
-- ================================================================
/*
-- 注意: 本番環境では慎重に実行してください

-- 1. employees.role_id を削除
ALTER TABLE employees DROP COLUMN IF EXISTS role_id;
DROP INDEX IF EXISTS idx_employees_role_id;

-- 2. RLSポリシーを削除
DROP POLICY IF EXISTS "roles_select_policy" ON roles;
DROP POLICY IF EXISTS "roles_insert_policy" ON roles;
DROP POLICY IF EXISTS "roles_update_policy" ON roles;
DROP POLICY IF EXISTS "roles_delete_policy" ON roles;
ALTER TABLE roles DISABLE ROW LEVEL SECURITY;

-- 3. rolesテーブルを削除（データも削除されます！）
DROP TABLE IF EXISTS roles CASCADE;

-- 確認
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public' AND table_name = 'roles';
-- 結果が0件なら成功
*/

-- ================================================================
-- 次のステップ
-- ================================================================
-- 1. Cloud SQLマイグレーションを実行（phase_3-5_cloudsql_complete.sql）
-- 2. app.jsをデプロイ（ローカルで動作確認済みの場合はスキップ）
-- 3. 組織図システムで同期ボタンをテスト
-- 4. 既存社員に役職を手動で設定
-- ================================================================
