-- ================================================================
-- Phase 3.5 マイグレーション: Cloud SQL（ソウルくん）
-- ================================================================
-- 実行日: 2026-01-XX
-- 作成者: Claude Code
--
-- このSQLはCloud SQLに接続して実行してください。
--
-- ローカル開発環境:
--   psql -h localhost -U postgres -d soulkun
--
-- Cloud SQL（本番）:
--   gcloud sql connect soulkun-db --user=postgres
-- ================================================================

-- ----------------------------------------------------------------
-- STEP 1: 事前確認
-- ----------------------------------------------------------------

-- 1-1. rolesテーブルの現状確認
-- \d roles

-- 1-2. 既存データの確認
-- SELECT id, name, level, external_id FROM roles LIMIT 10;

-- ----------------------------------------------------------------
-- STEP 2: rolesテーブルの修正
-- ----------------------------------------------------------------

-- 2-1. external_idカラムを追加（存在しない場合）
-- このカラムはSupabaseのroles.idを保存するために使用
ALTER TABLE roles
ADD COLUMN IF NOT EXISTS external_id VARCHAR(100) UNIQUE;

-- 2-2. インデックス作成
CREATE INDEX IF NOT EXISTS idx_roles_external_id ON roles(external_id);

-- 2-3. コメント追加
COMMENT ON COLUMN roles.external_id IS 'Supabase側のroles.id（同期用）';
COMMENT ON COLUMN roles.level IS '権限レベル: 1=業務委託, 2=社員, 3=リーダー, 4=幹部/部長, 5=管理部, 6=代表/CFO';

-- ----------------------------------------------------------------
-- STEP 3: chatwork_tasksテーブルの修正
-- ----------------------------------------------------------------

-- 3-1. department_idカラムを追加
-- このカラムはタスクがどの部署に属するかを記録
ALTER TABLE chatwork_tasks
ADD COLUMN IF NOT EXISTS department_id UUID REFERENCES departments(id);

-- 3-2. インデックス作成
CREATE INDEX IF NOT EXISTS idx_chatwork_tasks_department ON chatwork_tasks(department_id);

-- 3-3. コメント追加
COMMENT ON COLUMN chatwork_tasks.department_id IS 'タスクの所属部署ID（担当者のメイン部署）';

-- ----------------------------------------------------------------
-- STEP 4: 既存タスクへの部署設定（オプション）
-- ----------------------------------------------------------------

-- 既存タスクに部署を設定する場合、以下のSQLを実行
-- ※担当者のメイン部署を自動設定

-- UPDATE chatwork_tasks ct
-- SET department_id = (
--     SELECT ud.department_id
--     FROM user_departments ud
--     JOIN users u ON ud.user_id = u.id
--     WHERE u.chatwork_account_id = ct.assigned_to_account_id
--       AND ud.is_primary = TRUE
--       AND ud.ended_at IS NULL
--     LIMIT 1
-- )
-- WHERE ct.department_id IS NULL;

-- 設定結果の確認
-- SELECT
--     COUNT(*) as total,
--     COUNT(department_id) as with_dept,
--     COUNT(*) - COUNT(department_id) as without_dept
-- FROM chatwork_tasks;

-- ----------------------------------------------------------------
-- STEP 5: Roleモデルの確認用コメント
-- ----------------------------------------------------------------

-- 以下の変更をapi/app/models/user.pyに適用してください:
--
-- class Role(Base, TimestampMixin):
--     """役職マスタ"""
--     __tablename__ = "roles"
--
--     id = Column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
--     organization_id = Column(UUID(as_uuid=False), ForeignKey("organizations.id"), nullable=False)
--     external_id = Column(String(100), unique=True, nullable=True)  # 🆕 追加
--     name = Column(String(100), nullable=False)
--     level = Column(Integer, default=1)
--     description = Column(Text, nullable=True)
--     is_active = Column(Boolean, default=True)

-- ----------------------------------------------------------------
-- 確認クエリ
-- ----------------------------------------------------------------

-- rolesテーブルの構造確認
-- \d roles

-- chatwork_tasksテーブルの構造確認
-- \d chatwork_tasks

-- rolesのデータ確認
-- SELECT id, name, level, external_id FROM roles;

-- chatwork_tasksのdepartment_id確認
-- SELECT task_id, department_id FROM chatwork_tasks LIMIT 5;

-- ================================================================
-- 完了！
-- ================================================================
-- 次のステップ:
-- 1. api/app/models/user.pyにexternal_idを追加
-- 2. app.jsを改修してデプロイ
-- 3. 同期テスト実行
-- ================================================================
