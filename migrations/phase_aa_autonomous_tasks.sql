-- ============================================================================
-- Phase AA: Autonomous Task Tables
-- ============================================================================
-- 自律エージェントのタスク管理テーブル
--
-- テーブル:
--   1. autonomous_tasks - タスク管理
--   2. autonomous_task_steps - ステップ管理
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. autonomous_tasks テーブル
-- ============================================================================

CREATE TABLE IF NOT EXISTS autonomous_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,

    -- タスク情報
    title VARCHAR(255) NOT NULL,
    description TEXT,
    task_type VARCHAR(50) NOT NULL,  -- research, reminder, report, analysis, notification

    -- 実行情報
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending, running, completed, failed, cancelled
    priority INTEGER DEFAULT 5,  -- 1=highest, 10=lowest
    execution_plan JSONB DEFAULT '{}',

    -- 進捗
    progress_pct INTEGER DEFAULT 0,
    current_step INTEGER DEFAULT 0,
    total_steps INTEGER DEFAULT 0,

    -- 結果
    result JSONB DEFAULT '{}',
    error_message TEXT,

    -- リクエスト元
    requested_by VARCHAR(100),  -- user_id or "system"
    room_id VARCHAR(100),

    -- スケジュール
    scheduled_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,

    -- タイムスタンプ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE autonomous_tasks OWNER TO soulkun_user;

CREATE INDEX IF NOT EXISTS idx_autonomous_tasks_org
    ON autonomous_tasks(organization_id);
CREATE INDEX IF NOT EXISTS idx_autonomous_tasks_status
    ON autonomous_tasks(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_autonomous_tasks_scheduled
    ON autonomous_tasks(scheduled_at)
    WHERE status = 'pending' AND scheduled_at IS NOT NULL;

-- ============================================================================
-- 2. autonomous_task_steps テーブル
-- ============================================================================

CREATE TABLE IF NOT EXISTS autonomous_task_steps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    task_id UUID NOT NULL REFERENCES autonomous_tasks(id) ON DELETE CASCADE,

    -- ステップ情報
    step_number INTEGER NOT NULL,
    tool_name VARCHAR(100) NOT NULL,
    description TEXT,

    -- 入出力
    input_params JSONB DEFAULT '{}',
    output_result JSONB DEFAULT '{}',

    -- 実行情報
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending, running, completed, failed, skipped
    error_message TEXT,

    -- タイミング
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    duration_ms INTEGER,

    -- タイムスタンプ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE autonomous_task_steps OWNER TO soulkun_user;

CREATE INDEX IF NOT EXISTS idx_autonomous_steps_org
    ON autonomous_task_steps(organization_id);
CREATE INDEX IF NOT EXISTS idx_autonomous_steps_task
    ON autonomous_task_steps(task_id, step_number);

-- ============================================================================
-- 3. トリガー
-- ============================================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'update_updated_at_column') THEN
        IF NOT EXISTS (
            SELECT 1 FROM pg_trigger WHERE tgname = 'update_autonomous_tasks_updated_at'
        ) THEN
            CREATE TRIGGER update_autonomous_tasks_updated_at
                BEFORE UPDATE ON autonomous_tasks
                FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
        END IF;
    END IF;
END
$$;

-- ============================================================================
-- 4. RLS
-- ============================================================================

ALTER TABLE autonomous_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE autonomous_task_steps ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policy WHERE polname = 'autonomous_tasks_org_isolation') THEN
        CREATE POLICY autonomous_tasks_org_isolation ON autonomous_tasks
            FOR ALL USING (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policy WHERE polname = 'autonomous_task_steps_org_isolation') THEN
        CREATE POLICY autonomous_task_steps_org_isolation ON autonomous_task_steps
            FOR ALL USING (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END
$$;

-- ============================================================================
-- 5. 確認
-- ============================================================================

SELECT table_name,
       (SELECT COUNT(*) FROM information_schema.columns c WHERE c.table_name = t.table_name) AS cols
FROM information_schema.tables t
WHERE table_name LIKE 'autonomous_%'
ORDER BY table_name;

COMMIT;
