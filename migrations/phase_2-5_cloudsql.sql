-- ================================================================
-- Phase 2.5 目標達成支援: Cloud SQLマイグレーション
-- ================================================================
-- 作成日: 2026-01-23
-- 作成者: Claude Code
-- バージョン: 1.0
-- 設計書: docs/05_phase2-5_goal_achievement.md (v1.5)
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
  AND table_name IN ('organizations', 'users', 'departments', 'notification_logs')
ORDER BY table_name;

-- 1-3. goalsテーブルが既に存在するか確認（冪等性チェック）
SELECT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_name = 'goals' AND table_schema = 'public'
) as goals_exists;

-- 1-4. goal_progressテーブルが既に存在するか確認
SELECT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_name = 'goal_progress' AND table_schema = 'public'
) as goal_progress_exists;

-- 1-5. goal_remindersテーブルが既に存在するか確認
SELECT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_name = 'goal_reminders' AND table_schema = 'public'
) as goal_reminders_exists;

-- 1-6. notification_logsテーブルの構造確認（Phase 2.5で使用）
SELECT
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns
WHERE table_name = 'notification_logs'
  AND table_schema = 'public'
ORDER BY ordinal_position;

-- ================================================================
-- STEP 2: goalsテーブル作成（目標管理）
-- ================================================================

-- 2-1. goalsテーブル作成
CREATE TABLE IF NOT EXISTS goals (
    -- 主キー
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- テナント分離（鉄則: 全テーブルにorganization_id）
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- 目標の所有者
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    department_id UUID REFERENCES departments(id),  -- 部署目標の場合

    -- 目標の階層
    parent_goal_id UUID REFERENCES goals(id),  -- 親目標（部署目標など）
    goal_level VARCHAR(20) NOT NULL DEFAULT 'individual',  -- 'company', 'department', 'individual'

    -- 目標内容
    title VARCHAR(500) NOT NULL,  -- 「粗利300万円」
    description TEXT,  -- 詳細説明
    goal_type VARCHAR(50) NOT NULL,  -- 'numeric', 'deadline', 'action'

    -- 数値目標の場合
    target_value DECIMAL(15, 2),  -- 目標値（300万 → 3000000）
    current_value DECIMAL(15, 2) DEFAULT 0,  -- 現在値
    unit VARCHAR(50),  -- '円', '件', '人'

    -- 期限目標の場合
    deadline DATE,

    -- 期間
    period_type VARCHAR(20) NOT NULL DEFAULT 'monthly',  -- 'yearly', 'quarterly', 'monthly', 'weekly'
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,

    -- ステータス
    status VARCHAR(20) NOT NULL DEFAULT 'active',  -- 'active', 'completed', 'cancelled'

    -- 機密区分（4段階: public/internal/confidential/restricted）
    -- 目標は人事評価に関わるため、基本は internal 以上を使用
    classification VARCHAR(20) NOT NULL DEFAULT 'internal',
    CONSTRAINT check_goal_classification
        CHECK (classification IN ('public', 'internal', 'confidential', 'restricted')),

    -- 目標レベルの制約
    CONSTRAINT check_goal_level
        CHECK (goal_level IN ('company', 'department', 'individual')),

    -- 目標タイプの制約
    CONSTRAINT check_goal_type
        CHECK (goal_type IN ('numeric', 'deadline', 'action')),

    -- ステータスの制約
    CONSTRAINT check_goal_status
        CHECK (status IN ('active', 'completed', 'cancelled')),

    -- 期間タイプの制約
    CONSTRAINT check_period_type
        CHECK (period_type IN ('yearly', 'quarterly', 'monthly', 'weekly')),

    -- 期間の整合性チェック
    CONSTRAINT check_period_range
        CHECK (period_start <= period_end),

    -- メタデータ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_by UUID REFERENCES users(id),
    updated_by UUID REFERENCES users(id)
);

-- 2-2. インデックス作成
CREATE INDEX IF NOT EXISTS idx_goals_org ON goals(organization_id);
CREATE INDEX IF NOT EXISTS idx_goals_user ON goals(user_id);
CREATE INDEX IF NOT EXISTS idx_goals_dept ON goals(department_id);
CREATE INDEX IF NOT EXISTS idx_goals_parent ON goals(parent_goal_id);
CREATE INDEX IF NOT EXISTS idx_goals_period ON goals(period_start, period_end);
CREATE INDEX IF NOT EXISTS idx_goals_status ON goals(status) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_goals_level ON goals(goal_level);
CREATE INDEX IF NOT EXISTS idx_goals_type ON goals(goal_type);
CREATE INDEX IF NOT EXISTS idx_goals_classification ON goals(classification);

-- 2-3. コメント追加
COMMENT ON TABLE goals IS '目標管理テーブル（Phase 2.5）- 個人・部署・会社の目標を管理';
COMMENT ON COLUMN goals.organization_id IS 'テナントID（鉄則: 全テーブルにorganization_id）';
COMMENT ON COLUMN goals.user_id IS '目標の所有者（個人目標の場合は本人、部署目標の場合は責任者）';
COMMENT ON COLUMN goals.department_id IS '部署ID（部署目標の場合に設定）';
COMMENT ON COLUMN goals.parent_goal_id IS '親目標ID（個人目標→部署目標、部署目標→会社目標）';
COMMENT ON COLUMN goals.goal_level IS '目標レベル: company=会社, department=部署, individual=個人';
COMMENT ON COLUMN goals.goal_type IS '目標タイプ: numeric=数値, deadline=期限, action=行動';
COMMENT ON COLUMN goals.target_value IS '目標値（numeric目標の場合）: 例 300万円 → 3000000';
COMMENT ON COLUMN goals.current_value IS '現在値（自動更新される）';
COMMENT ON COLUMN goals.unit IS '単位: 円, 件, 人 など';
COMMENT ON COLUMN goals.period_type IS '期間タイプ: yearly=年次, quarterly=四半期, monthly=月次, weekly=週次';
COMMENT ON COLUMN goals.classification IS '機密区分（4段階）: public=公開, internal=社内限定, confidential=機密, restricted=極秘';

-- 2-4. 確認クエリ
SELECT 'goals table created' as status;

-- ================================================================
-- STEP 3: goal_progressテーブル作成（進捗記録）
-- ================================================================

-- 3-1. goal_progressテーブル作成
CREATE TABLE IF NOT EXISTS goal_progress (
    -- 主キー
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- リレーション
    goal_id UUID NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- 進捗データ
    progress_date DATE NOT NULL,  -- 記録日
    value DECIMAL(15, 2),  -- 数値目標の場合の実績値
    cumulative_value DECIMAL(15, 2),  -- 累計値

    -- 振り返り
    daily_note TEXT,  -- 「今日何やった？」の回答
    daily_choice TEXT,  -- 「今日何を選んだ？」の回答

    -- AIフィードバック
    ai_feedback TEXT,  -- ソウルくんからのフィードバック
    ai_feedback_sent_at TIMESTAMPTZ,  -- フィードバック送信日時

    -- 機密区分（4段階: public/internal/confidential/restricted）
    -- 基本は internal、AIフィードバック含む場合は confidential
    classification VARCHAR(20) NOT NULL DEFAULT 'internal',
    CONSTRAINT check_goal_progress_classification
        CHECK (classification IN ('public', 'internal', 'confidential', 'restricted')),

    -- メタデータ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_by UUID REFERENCES users(id),
    updated_by UUID REFERENCES users(id),

    -- 冪等性（1日1回のみ記録、訂正時は上書き）
    CONSTRAINT unique_goal_progress UNIQUE(goal_id, progress_date)
);

-- 3-2. インデックス作成
CREATE INDEX IF NOT EXISTS idx_goal_progress_goal ON goal_progress(goal_id);
CREATE INDEX IF NOT EXISTS idx_goal_progress_org ON goal_progress(organization_id);
CREATE INDEX IF NOT EXISTS idx_goal_progress_date ON goal_progress(progress_date);
CREATE INDEX IF NOT EXISTS idx_goal_progress_classification ON goal_progress(classification);

-- 3-3. コメント追加
COMMENT ON TABLE goal_progress IS '目標の日次進捗記録（Phase 2.5）- 毎日の振り返りを保存';
COMMENT ON COLUMN goal_progress.goal_id IS '対象目標ID';
COMMENT ON COLUMN goal_progress.organization_id IS 'テナントID（鉄則: 全テーブルにorganization_id）';
COMMENT ON COLUMN goal_progress.progress_date IS '進捗記録日（1日1レコード）';
COMMENT ON COLUMN goal_progress.value IS 'その日の実績値（numeric目標の場合）';
COMMENT ON COLUMN goal_progress.cumulative_value IS '累計値（その日までの合計）';
COMMENT ON COLUMN goal_progress.daily_note IS '17時の「今日何やった？」への回答';
COMMENT ON COLUMN goal_progress.daily_choice IS '「今日何を選んだ？」への回答（選択理論）';
COMMENT ON COLUMN goal_progress.ai_feedback IS 'ソウルくんからのフィードバック（翌朝8時に送信）';
COMMENT ON COLUMN goal_progress.ai_feedback_sent_at IS 'AIフィードバック送信日時';
COMMENT ON COLUMN goal_progress.classification IS '機密区分: AIフィードバック含む場合は confidential に昇格';
COMMENT ON CONSTRAINT unique_goal_progress ON goal_progress IS '冪等性保証: 同日に複数回返信があった場合は最新で上書き（UPSERT）';

-- 3-4. 確認クエリ
SELECT 'goal_progress table created' as status;

-- ================================================================
-- STEP 4: goal_remindersテーブル作成（リマインド設定）
-- ================================================================

-- 4-1. goal_remindersテーブル作成
CREATE TABLE IF NOT EXISTS goal_reminders (
    -- 主キー
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- テナント分離（鉄則: 全テーブルにorganization_id）
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- リレーション
    goal_id UUID NOT NULL REFERENCES goals(id) ON DELETE CASCADE,

    -- リマインド設定
    reminder_type VARCHAR(50) NOT NULL,  -- 'daily_check', 'morning_feedback', 'team_summary', 'daily_reminder'
    reminder_time TIME NOT NULL,  -- 17:00, 08:00, 18:00
    is_enabled BOOLEAN DEFAULT TRUE,

    -- ChatWork設定
    chatwork_room_id VARCHAR(20),  -- 通知先ルームID（NULLの場合はDM）

    -- リマインドタイプの制約
    CONSTRAINT check_reminder_type
        CHECK (reminder_type IN ('daily_check', 'morning_feedback', 'team_summary', 'daily_reminder')),

    -- メタデータ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_by UUID REFERENCES users(id),
    updated_by UUID REFERENCES users(id)
);

-- 4-2. インデックス作成
CREATE INDEX IF NOT EXISTS idx_goal_reminders_org ON goal_reminders(organization_id);
CREATE INDEX IF NOT EXISTS idx_goal_reminders_goal ON goal_reminders(goal_id);
CREATE INDEX IF NOT EXISTS idx_goal_reminders_enabled ON goal_reminders(is_enabled) WHERE is_enabled = TRUE;
CREATE INDEX IF NOT EXISTS idx_goal_reminders_type ON goal_reminders(reminder_type);
CREATE INDEX IF NOT EXISTS idx_goal_reminders_time ON goal_reminders(reminder_time);

-- 4-3. コメント追加
COMMENT ON TABLE goal_reminders IS '目標リマインド設定（Phase 2.5）- 通知タイミングを個別に設定';
COMMENT ON COLUMN goal_reminders.organization_id IS 'テナントID（鉄則: 全テーブルにorganization_id）';
COMMENT ON COLUMN goal_reminders.goal_id IS '対象目標ID';
COMMENT ON COLUMN goal_reminders.reminder_type IS 'リマインドタイプ: daily_check=17時進捗確認, morning_feedback=8時フィードバック, team_summary=8時チームサマリー, daily_reminder=18時未回答リマインド';
COMMENT ON COLUMN goal_reminders.reminder_time IS 'リマインド時刻（TIME型）';
COMMENT ON COLUMN goal_reminders.is_enabled IS 'リマインド有効フラグ';
COMMENT ON COLUMN goal_reminders.chatwork_room_id IS 'ChatWork通知先ルームID（NULLの場合はDMで送信）';

-- 4-4. 確認クエリ
SELECT 'goal_reminders table created' as status;

-- ================================================================
-- STEP 5: audit_logsテーブル作成（監査ログ）
-- ================================================================

-- 5-1. audit_logsテーブル作成（lib/audit.py で参照）
CREATE TABLE IF NOT EXISTS audit_logs (
    -- 主キー
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- テナント分離
    organization_id VARCHAR(100),  -- 既存の形式に合わせてVARCHAR（将来UUID化予定）

    -- 実行者情報
    user_id UUID REFERENCES users(id),
    user_email VARCHAR(255),  -- 冗長だがログ検索用

    -- アクション情報
    action VARCHAR(50) NOT NULL,  -- 'create', 'read', 'update', 'delete', 'view', 'sync', 'regenerate'
    resource_type VARCHAR(100) NOT NULL,  -- 'goal', 'goal_progress', 'goal_summary', 'document', etc.
    resource_id VARCHAR(255),  -- UUIDまたはその他のID
    resource_name VARCHAR(500),  -- リソース名（検索用）

    -- 関連情報
    department_id UUID REFERENCES departments(id),

    -- 機密区分
    classification VARCHAR(20),
    CONSTRAINT check_audit_log_classification
        CHECK (classification IS NULL OR classification IN ('public', 'internal', 'confidential', 'restricted')),

    -- 詳細データ
    details JSONB,  -- 追加のコンテキスト情報

    -- アクセス元情報
    ip_address VARCHAR(45),  -- IPv6対応
    user_agent TEXT,

    -- タイムスタンプ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 5-2. インデックス作成
CREATE INDEX IF NOT EXISTS idx_audit_logs_org ON audit_logs(organization_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_user ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_logs_resource_type ON audit_logs(resource_type);
CREATE INDEX IF NOT EXISTS idx_audit_logs_resource_id ON audit_logs(resource_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_classification ON audit_logs(classification);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_logs_dept ON audit_logs(department_id);

-- 5-3. コメント追加
COMMENT ON TABLE audit_logs IS '監査ログテーブル（Phase 2.5/4A）- confidential以上の操作を記録';
COMMENT ON COLUMN audit_logs.action IS 'アクション: create, read, update, delete, view, sync, regenerate';
COMMENT ON COLUMN audit_logs.resource_type IS 'リソースタイプ: goal, goal_progress, goal_summary, document, task, user, department';
COMMENT ON COLUMN audit_logs.classification IS '対象リソースの機密区分';
COMMENT ON COLUMN audit_logs.details IS '追加情報（変更前後の値、メタデータなど）';

-- 5-4. 確認クエリ
SELECT 'audit_logs table created' as status;

-- ================================================================
-- STEP 6: 最終確認（必須）
-- ================================================================

-- 6-1. 作成したテーブルの確認
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('goals', 'goal_progress', 'goal_reminders', 'audit_logs')
ORDER BY table_name;

-- 6-2. goalsテーブルの構造確認
SELECT
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'goals'
  AND table_schema = 'public'
ORDER BY ordinal_position;

-- 6-3. goal_progressテーブルの構造確認
SELECT
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'goal_progress'
  AND table_schema = 'public'
ORDER BY ordinal_position;

-- 6-4. goal_remindersテーブルの構造確認
SELECT
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'goal_reminders'
  AND table_schema = 'public'
ORDER BY ordinal_position;

-- 6-5. audit_logsテーブルの構造確認
SELECT
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'audit_logs'
  AND table_schema = 'public'
ORDER BY ordinal_position;

-- 6-6. 外部キー制約の確認
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
  AND tc.table_name IN ('goals', 'goal_progress', 'goal_reminders', 'audit_logs')
ORDER BY tc.table_name, tc.constraint_name;

-- 6-7. CHECK制約の確認
SELECT
    tc.constraint_name,
    tc.table_name,
    cc.check_clause
FROM information_schema.table_constraints tc
JOIN information_schema.check_constraints cc
    ON tc.constraint_name = cc.constraint_name
WHERE tc.table_name IN ('goals', 'goal_progress', 'goal_reminders', 'audit_logs')
  AND tc.constraint_type = 'CHECK'
ORDER BY tc.table_name, tc.constraint_name;

-- 6-8. インデックスの確認
SELECT
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE tablename IN ('goals', 'goal_progress', 'goal_reminders', 'audit_logs')
  AND schemaname = 'public'
ORDER BY tablename, indexname;

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
    'Phase 2.5 Migration Completed!' as status,
    now() as completed_at;

-- 作成されたテーブルのサマリー
SELECT
    table_name,
    (SELECT COUNT(*) FROM information_schema.columns c WHERE c.table_name = t.table_name AND c.table_schema = 'public') as column_count
FROM information_schema.tables t
WHERE table_schema = 'public'
  AND table_name IN ('goals', 'goal_progress', 'goal_reminders', 'audit_logs')
ORDER BY table_name;

-- ================================================================
-- ロールバック用SQL（問題発生時）
-- ================================================================
/*
-- 注意: 本番環境では慎重に実行してください
-- データが存在する場合は削除されます

-- 1. audit_logsテーブルを削除
DROP TABLE IF EXISTS audit_logs CASCADE;

-- 2. goal_remindersテーブルを削除
DROP TABLE IF EXISTS goal_reminders CASCADE;

-- 3. goal_progressテーブルを削除
DROP TABLE IF EXISTS goal_progress CASCADE;

-- 4. goalsテーブルを削除
DROP TABLE IF EXISTS goals CASCADE;

-- 確認
SELECT table_name FROM information_schema.tables
WHERE table_name IN ('goals', 'goal_progress', 'goal_reminders', 'audit_logs')
  AND table_schema = 'public';
-- 結果が0件なら成功
*/

-- ================================================================
-- 次のステップ
-- ================================================================
-- 1. api/app/models/ にSQLAlchemy ORMモデルを作成
-- 2. lib/goal.py に目標管理サービスを作成
-- 3. chatwork-webhook/main.py に目標登録対話を追加
-- 4. Cloud Schedulerで17時/8時/18時のジョブを設定
-- ================================================================
