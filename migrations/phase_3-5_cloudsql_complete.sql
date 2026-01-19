-- ================================================================
-- Phase 3.5 完全版マイグレーション: Cloud SQL（ソウルくん）
-- ================================================================
-- 作成日: 2026-01-19
-- 作成者: Claude Code
-- バージョン: 2.0 (ダブルチェック済み)
--
-- このSQLはCloud SQLに接続して実行してください。
--
-- 接続方法:
--   gcloud sql connect soulkun-db --user=postgres
--
-- 注意事項:
--   1. 必ずバックアップを取ってから実行
--   2. STEP 1の事前確認を必ず実行
--   3. エラーが発生したらSTEP 7のロールバックを実行
-- ================================================================

-- ================================================================
-- STEP 0: トランザクション開始
-- ================================================================
BEGIN;

-- ================================================================
-- STEP 1: 事前確認（必須）
-- ================================================================

-- 1-1. 現在のデータベースとユーザーを確認
SELECT current_database() as database, current_user as user, now() as executed_at;

-- 1-2. 必要なテーブルの存在確認
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('roles', 'user_departments', 'chatwork_tasks', 'departments', 'users')
ORDER BY table_name;

-- 1-3. rolesテーブルの現状確認
SELECT
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'roles'
  AND table_schema = 'public'
ORDER BY ordinal_position;

-- 1-4. user_departmentsテーブルの現状確認
SELECT
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'user_departments'
  AND table_schema = 'public'
ORDER BY ordinal_position;

-- 1-5. chatwork_tasksテーブルの現状確認
SELECT
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'chatwork_tasks'
  AND table_schema = 'public'
ORDER BY ordinal_position;

-- 1-6. 既存データ件数の確認
SELECT
    'roles' as table_name, COUNT(*) as row_count FROM roles
UNION ALL
SELECT 'users', COUNT(*) FROM users
UNION ALL
SELECT 'departments', COUNT(*) FROM departments
UNION ALL
SELECT 'user_departments', COUNT(*) FROM user_departments
UNION ALL
SELECT 'chatwork_tasks', COUNT(*) FROM chatwork_tasks;

-- 1-7. external_idカラムの存在確認（既に実行済みかどうか）
SELECT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'roles'
      AND column_name = 'external_id'
) as external_id_exists;

-- 1-8. user_departments.role_idカラムの存在確認
SELECT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'user_departments'
      AND column_name = 'role_id'
) as role_id_exists;

-- ================================================================
-- STEP 2: rolesテーブルの修正
-- ================================================================

-- 2-1. external_idカラムを追加（存在しない場合）
-- このカラムはSupabaseのroles.id（TEXT型、例: role_ceo）を保存
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'roles' AND column_name = 'external_id'
    ) THEN
        ALTER TABLE roles ADD COLUMN external_id VARCHAR(100);
        RAISE NOTICE 'external_id column added to roles table';
    ELSE
        RAISE NOTICE 'external_id column already exists in roles table';
    END IF;
END $$;

-- 2-2. external_idにUNIQUE制約を追加（存在しない場合）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE tablename = 'roles' AND indexname = 'roles_external_id_key'
    ) THEN
        ALTER TABLE roles ADD CONSTRAINT roles_external_id_key UNIQUE (external_id);
        RAISE NOTICE 'UNIQUE constraint added to external_id';
    ELSE
        RAISE NOTICE 'UNIQUE constraint already exists on external_id';
    END IF;
EXCEPTION
    WHEN duplicate_table THEN
        RAISE NOTICE 'UNIQUE constraint already exists on external_id';
END $$;

-- 2-3. インデックス作成
CREATE INDEX IF NOT EXISTS idx_roles_external_id ON roles(external_id);

-- 2-4. コメント追加
COMMENT ON COLUMN roles.external_id IS 'Supabase側のroles.id（同期用）- 例: role_ceo, role_employee';
COMMENT ON COLUMN roles.level IS '権限レベル: 1=業務委託, 2=社員, 3=リーダー, 4=幹部/部長, 5=管理部, 6=代表/CFO';

-- 2-5. 確認クエリ
SELECT id, name, level, external_id, is_active
FROM roles
ORDER BY level DESC, name;

-- ================================================================
-- STEP 3: user_departmentsテーブルの修正【重要】
-- ================================================================

-- 3-1. role_idカラムを追加（権限レベル計算に必須）
-- このカラムはユーザーの権限レベル（1-6）を取得するためにrolesテーブルとJOINする
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'user_departments' AND column_name = 'role_id'
    ) THEN
        ALTER TABLE user_departments ADD COLUMN role_id UUID REFERENCES roles(id);
        RAISE NOTICE 'role_id column added to user_departments table';
    ELSE
        RAISE NOTICE 'role_id column already exists in user_departments table';
    END IF;
END $$;

-- 3-2. インデックス作成
CREATE INDEX IF NOT EXISTS idx_user_departments_role ON user_departments(role_id);

-- 3-3. コメント追加
COMMENT ON COLUMN user_departments.role_id IS '役職ID（rolesテーブルへの外部キー）- 権限レベル計算に使用。access_control.pyがこのカラムを参照';

-- 3-4. 確認クエリ
SELECT
    ud.id,
    u.name as user_name,
    d.name as department_name,
    ud.role_in_dept,
    ud.role_id,
    r.name as role_name,
    r.level as role_level
FROM user_departments ud
LEFT JOIN users u ON ud.user_id = u.id
LEFT JOIN departments d ON ud.department_id = d.id
LEFT JOIN roles r ON ud.role_id = r.id
WHERE ud.ended_at IS NULL
LIMIT 10;

-- ================================================================
-- STEP 4: chatwork_tasksテーブルの修正
-- ================================================================

-- 4-1. department_idカラムを追加
-- このカラムはタスクがどの部署に属するかを記録（アクセス制御に使用）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'chatwork_tasks' AND column_name = 'department_id'
    ) THEN
        ALTER TABLE chatwork_tasks ADD COLUMN department_id UUID REFERENCES departments(id);
        RAISE NOTICE 'department_id column added to chatwork_tasks table';
    ELSE
        RAISE NOTICE 'department_id column already exists in chatwork_tasks table';
    END IF;
END $$;

-- 4-2. インデックス作成
CREATE INDEX IF NOT EXISTS idx_chatwork_tasks_department ON chatwork_tasks(department_id);

-- 4-3. コメント追加
COMMENT ON COLUMN chatwork_tasks.department_id IS 'タスクの所属部署ID（担当者のメイン部署）- アクセス制御に使用';

-- 4-4. 確認クエリ
SELECT
    task_id,
    body,
    assigned_to_account_id,
    department_id,
    status
FROM chatwork_tasks
LIMIT 5;

-- ================================================================
-- STEP 5: 既存タスクへの部署設定（オプション）
-- ================================================================

-- 既存タスクに部署を自動設定する場合は以下のコメントを外して実行
-- ※担当者のメイン部署を自動設定

/*
UPDATE chatwork_tasks ct
SET department_id = (
    SELECT ud.department_id
    FROM user_departments ud
    JOIN users u ON ud.user_id = u.id
    WHERE u.chatwork_account_id = ct.assigned_to_account_id
      AND ud.is_primary = TRUE
      AND ud.ended_at IS NULL
    LIMIT 1
)
WHERE ct.department_id IS NULL
  AND ct.assigned_to_account_id IS NOT NULL;

-- 設定結果の確認
SELECT
    COUNT(*) as total,
    COUNT(department_id) as with_dept,
    COUNT(*) - COUNT(department_id) as without_dept
FROM chatwork_tasks;
*/

-- ================================================================
-- STEP 6: 最終確認（必須）
-- ================================================================

-- 6-1. rolesテーブルの構造確認
SELECT
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'roles'
  AND table_schema = 'public'
ORDER BY ordinal_position;

-- 6-2. user_departmentsテーブルの構造確認
SELECT
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'user_departments'
  AND table_schema = 'public'
ORDER BY ordinal_position;

-- 6-3. chatwork_tasksテーブルの構造確認
SELECT
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'chatwork_tasks'
  AND table_schema = 'public'
ORDER BY ordinal_position;

-- 6-4. 外部キー制約の確認
SELECT
    tc.constraint_name,
    tc.table_name,
    kcu.column_name,
    ccu.table_name AS foreign_table_name,
    ccu.column_name AS foreign_column_name
FROM information_schema.table_constraints AS tc
JOIN information_schema.key_column_usage AS kcu
    ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage AS ccu
    ON ccu.constraint_name = tc.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND tc.table_name IN ('user_departments', 'chatwork_tasks')
ORDER BY tc.table_name, tc.constraint_name;

-- 6-5. インデックスの確認
SELECT
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE tablename IN ('roles', 'user_departments', 'chatwork_tasks')
  AND schemaname = 'public'
ORDER BY tablename, indexname;

-- 6-6. access_control.pyで使用するクエリのテスト
-- ユーザーの権限レベルを取得するクエリ（access_control.py:83-89相当）
/*
SELECT COALESCE(MAX(r.level), 2) as max_level
FROM user_departments ud
JOIN roles r ON ud.role_id = r.id
WHERE ud.user_id = 'テスト用ユーザーIDをここに入力'
  AND ud.ended_at IS NULL;
*/

-- ================================================================
-- STEP 7: コミット or ロールバック
-- ================================================================

-- 全て正常に完了した場合
COMMIT;

-- エラーが発生した場合は以下を実行
-- ROLLBACK;

-- ================================================================
-- 完了サマリー
-- ================================================================
SELECT
    'Phase 3.5 Migration Completed!' as status,
    now() as completed_at;

-- ================================================================
-- ロールバック用SQL（問題発生時）
-- ================================================================
/*
-- 注意: 本番環境では慎重に実行してください

-- 1. chatwork_tasks.department_id を削除
ALTER TABLE chatwork_tasks DROP COLUMN IF EXISTS department_id;
DROP INDEX IF EXISTS idx_chatwork_tasks_department;

-- 2. user_departments.role_id を削除
ALTER TABLE user_departments DROP COLUMN IF EXISTS role_id;
DROP INDEX IF EXISTS idx_user_departments_role;

-- 3. roles.external_id を削除
ALTER TABLE roles DROP CONSTRAINT IF EXISTS roles_external_id_key;
ALTER TABLE roles DROP COLUMN IF EXISTS external_id;
DROP INDEX IF EXISTS idx_roles_external_id;

-- 確認
SELECT column_name FROM information_schema.columns
WHERE table_name IN ('roles', 'user_departments', 'chatwork_tasks')
  AND column_name IN ('external_id', 'role_id', 'department_id');
-- 結果が0件なら成功
*/

-- ================================================================
-- 次のステップ
-- ================================================================
-- 1. Supabaseマイグレーションを実行（phase_3-5_supabase_complete.sql）
-- 2. 組織図システムで同期ボタンをテスト
-- 3. 役職選択ドロップダウンの動作確認
-- 4. タスク検索のアクセス制御テスト
-- ================================================================
