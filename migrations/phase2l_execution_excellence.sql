-- ============================================================
-- Phase 2L: 実行力強化（Execution Excellence）マイグレーション
-- 作成日: 2026-01-28
-- 設計書: docs/21_phase2l_execution_excellence.md
-- ============================================================

-- ============================================================
-- 1. execution_plans（実行計画テーブル）
-- ============================================================

CREATE TABLE IF NOT EXISTS execution_plans (
    -- 主キー
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- テナント分離（鉄則: 全テーブルにorganization_id）
    organization_id UUID NOT NULL,

    -- コンテキスト
    room_id VARCHAR(50) NOT NULL,
    account_id VARCHAR(50) NOT NULL,

    -- 計画情報
    name VARCHAR(200) NOT NULL,
    description TEXT,
    original_request TEXT NOT NULL,

    -- ステータス
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    progress DECIMAL(5, 2) DEFAULT 0.00,

    -- 実行設定
    parallel_execution BOOLEAN DEFAULT TRUE,
    continue_on_failure BOOLEAN DEFAULT FALSE,
    quality_checks_enabled BOOLEAN DEFAULT TRUE,
    required_quality_level DECIMAL(3, 2) DEFAULT 0.80,

    -- タイムスタンプ
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 制約
    CONSTRAINT check_status CHECK (
        status IN ('pending', 'in_progress', 'completed', 'failed', 'blocked', 'skipped', 'escalated')
    ),
    CONSTRAINT check_progress CHECK (
        progress >= 0.00 AND progress <= 100.00
    ),
    CONSTRAINT check_quality_level CHECK (
        required_quality_level >= 0.00 AND required_quality_level <= 1.00
    )
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_execution_plans_org
    ON execution_plans(organization_id);
CREATE INDEX IF NOT EXISTS idx_execution_plans_org_status
    ON execution_plans(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_execution_plans_room
    ON execution_plans(room_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_execution_plans_account
    ON execution_plans(account_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_execution_plans_status
    ON execution_plans(status);
CREATE INDEX IF NOT EXISTS idx_execution_plans_created
    ON execution_plans(created_at DESC);

-- コメント
COMMENT ON TABLE execution_plans IS 'Phase 2L: 実行計画（複合タスクの分解・計画）';
COMMENT ON COLUMN execution_plans.status IS 'ステータス: pending, in_progress, completed, failed, blocked, skipped, escalated';
COMMENT ON COLUMN execution_plans.progress IS '進捗率（0.00-100.00）';
COMMENT ON COLUMN execution_plans.parallel_execution IS '並列実行を許可するか';
COMMENT ON COLUMN execution_plans.continue_on_failure IS '失敗時も続行するか';


-- ============================================================
-- 2. execution_subtasks（サブタスクテーブル）
-- ============================================================

CREATE TABLE IF NOT EXISTS execution_subtasks (
    -- 主キー
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- 外部キー
    plan_id UUID NOT NULL REFERENCES execution_plans(id) ON DELETE CASCADE,

    -- テナント分離
    organization_id UUID NOT NULL,

    -- サブタスク情報
    name VARCHAR(200) NOT NULL,
    description TEXT,
    action VARCHAR(100) NOT NULL,
    params JSONB DEFAULT '{}',

    -- 依存関係
    depends_on TEXT[] DEFAULT '{}',

    -- ステータス
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    priority VARCHAR(20) DEFAULT 'normal',

    -- 実行設定
    is_optional BOOLEAN DEFAULT FALSE,
    max_retries INTEGER DEFAULT 3,
    timeout_seconds INTEGER DEFAULT 60,
    recovery_strategy VARCHAR(20) DEFAULT 'retry',

    -- 実行結果
    result JSONB,
    error TEXT,
    retry_count INTEGER DEFAULT 0,

    -- タイムスタンプ
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 制約
    CONSTRAINT check_subtask_status CHECK (
        status IN ('pending', 'in_progress', 'completed', 'failed', 'blocked', 'skipped', 'escalated')
    ),
    CONSTRAINT check_priority CHECK (
        priority IN ('critical', 'high', 'normal', 'low')
    ),
    CONSTRAINT check_recovery_strategy CHECK (
        recovery_strategy IN ('retry', 'alternative', 'skip', 'escalate', 'abort')
    ),
    CONSTRAINT check_retry_count CHECK (
        retry_count >= 0
    )
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_execution_subtasks_plan
    ON execution_subtasks(plan_id);
CREATE INDEX IF NOT EXISTS idx_execution_subtasks_org
    ON execution_subtasks(organization_id);
CREATE INDEX IF NOT EXISTS idx_execution_subtasks_status
    ON execution_subtasks(status);
CREATE INDEX IF NOT EXISTS idx_execution_subtasks_action
    ON execution_subtasks(action);

-- コメント
COMMENT ON TABLE execution_subtasks IS 'Phase 2L: サブタスク（分解された個別タスク）';
COMMENT ON COLUMN execution_subtasks.status IS 'ステータス: pending, in_progress, completed, failed, blocked, skipped, escalated';
COMMENT ON COLUMN execution_subtasks.priority IS '優先度: critical, high, normal, low';
COMMENT ON COLUMN execution_subtasks.recovery_strategy IS 'リカバリー戦略: retry, alternative, skip, escalate, abort';
COMMENT ON COLUMN execution_subtasks.depends_on IS '依存するサブタスクIDの配列';


-- ============================================================
-- 3. execution_escalations（エスカレーションテーブル）
-- ============================================================

CREATE TABLE IF NOT EXISTS execution_escalations (
    -- 主キー
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- 外部キー
    plan_id UUID NOT NULL REFERENCES execution_plans(id) ON DELETE CASCADE,
    subtask_id UUID REFERENCES execution_subtasks(id) ON DELETE SET NULL,

    -- テナント分離
    organization_id UUID NOT NULL,

    -- エスカレーション内容
    level VARCHAR(20) NOT NULL DEFAULT 'confirmation',
    title VARCHAR(300) NOT NULL,
    description TEXT,
    context TEXT,

    -- 選択肢
    options JSONB DEFAULT '[]',
    default_option VARCHAR(50),
    recommendation VARCHAR(50),
    recommendation_reasoning TEXT,

    -- ステータス
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    response VARCHAR(50),
    response_reasoning TEXT,

    -- タイムスタンプ
    expires_at TIMESTAMPTZ,
    responded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 通知情報
    notification_sent BOOLEAN DEFAULT FALSE,
    notification_room_id VARCHAR(50),
    notification_message_id VARCHAR(50),

    -- 制約
    CONSTRAINT check_escalation_level CHECK (
        level IN ('info', 'confirmation', 'decision', 'urgent')
    ),
    CONSTRAINT check_escalation_status CHECK (
        status IN ('pending', 'responded', 'expired')
    )
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_execution_escalations_plan
    ON execution_escalations(plan_id);
CREATE INDEX IF NOT EXISTS idx_execution_escalations_org
    ON execution_escalations(organization_id);
CREATE INDEX IF NOT EXISTS idx_execution_escalations_status
    ON execution_escalations(status);
CREATE INDEX IF NOT EXISTS idx_execution_escalations_level
    ON execution_escalations(level);
CREATE INDEX IF NOT EXISTS idx_execution_escalations_expires
    ON execution_escalations(expires_at)
    WHERE status = 'pending';

-- コメント
COMMENT ON TABLE execution_escalations IS 'Phase 2L: エスカレーション（自動処理できない問題の人間への確認）';
COMMENT ON COLUMN execution_escalations.level IS 'エスカレーションレベル: info, confirmation, decision, urgent';
COMMENT ON COLUMN execution_escalations.status IS 'ステータス: pending, responded, expired';


-- ============================================================
-- 4. execution_quality_reports（品質レポートテーブル）
-- ============================================================

CREATE TABLE IF NOT EXISTS execution_quality_reports (
    -- 主キー
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- 外部キー
    plan_id UUID NOT NULL REFERENCES execution_plans(id) ON DELETE CASCADE,
    subtask_id UUID REFERENCES execution_subtasks(id) ON DELETE SET NULL,

    -- テナント分離
    organization_id UUID NOT NULL,

    -- チェック結果
    overall_result VARCHAR(20) NOT NULL DEFAULT 'pass',
    quality_score DECIMAL(3, 2) DEFAULT 1.00,

    -- 詳細チェック
    checks JSONB DEFAULT '[]',

    -- 問題点
    issues TEXT[] DEFAULT '{}',
    warnings TEXT[] DEFAULT '{}',

    -- 推奨アクション
    recommended_actions TEXT[] DEFAULT '{}',

    -- タイムスタンプ
    checked_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 制約
    CONSTRAINT check_quality_result CHECK (
        overall_result IN ('pass', 'warning', 'fail', 'skipped')
    ),
    CONSTRAINT check_quality_score CHECK (
        quality_score >= 0.00 AND quality_score <= 1.00
    )
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_execution_quality_plan
    ON execution_quality_reports(plan_id);
CREATE INDEX IF NOT EXISTS idx_execution_quality_org
    ON execution_quality_reports(organization_id);
CREATE INDEX IF NOT EXISTS idx_execution_quality_result
    ON execution_quality_reports(overall_result);

-- コメント
COMMENT ON TABLE execution_quality_reports IS 'Phase 2L: 品質レポート（実行結果の品質検証）';
COMMENT ON COLUMN execution_quality_reports.overall_result IS '全体結果: pass, warning, fail, skipped';
COMMENT ON COLUMN execution_quality_reports.quality_score IS '品質スコア（0.00-1.00）';


-- ============================================================
-- 5. Feature Flags（lib/feature_flags.pyで管理、参照用）
-- ============================================================

-- Feature Flags:
-- - ENABLE_EXECUTION_EXCELLENCE: メイン機能フラグ（デフォルト: false）
-- - ENABLE_TASK_DECOMPOSITION: タスク自動分解（depends_on: ENABLE_EXECUTION_EXCELLENCE）
-- - ENABLE_PARALLEL_EXECUTION: 並列実行（depends_on: ENABLE_EXECUTION_EXCELLENCE）
-- - ENABLE_QUALITY_CHECKS: 品質チェック（depends_on: ENABLE_EXECUTION_EXCELLENCE）
-- - ENABLE_AUTO_ESCALATION: 自動エスカレーション（depends_on: ENABLE_EXECUTION_EXCELLENCE）
-- - ENABLE_LLM_DECOMPOSITION: LLMベースのタスク分解（depends_on: ENABLE_TASK_DECOMPOSITION）


-- ============================================================
-- 6. トリガー: updated_at自動更新
-- ============================================================

-- execution_plans
CREATE OR REPLACE FUNCTION update_execution_plans_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_execution_plans_updated_at ON execution_plans;
CREATE TRIGGER trigger_execution_plans_updated_at
    BEFORE UPDATE ON execution_plans
    FOR EACH ROW
    EXECUTE FUNCTION update_execution_plans_updated_at();

-- execution_escalations
CREATE OR REPLACE FUNCTION update_execution_escalations_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_execution_escalations_updated_at ON execution_escalations;
CREATE TRIGGER trigger_execution_escalations_updated_at
    BEFORE UPDATE ON execution_escalations
    FOR EACH ROW
    EXECUTE FUNCTION update_execution_escalations_updated_at();


-- ============================================================
-- 完了メッセージ
-- ============================================================

DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Phase 2L: Execution Excellence マイグレーション完了';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '';
    RAISE NOTICE '作成されたテーブル:';
    RAISE NOTICE '  - execution_plans: 実行計画';
    RAISE NOTICE '  - execution_subtasks: サブタスク';
    RAISE NOTICE '  - execution_escalations: エスカレーション';
    RAISE NOTICE '  - execution_quality_reports: 品質レポート';
    RAISE NOTICE '';
    RAISE NOTICE '次のステップ:';
    RAISE NOTICE '  1. Feature Flag ENABLE_EXECUTION_EXCELLENCE を true に設定';
    RAISE NOTICE '  2. chatwork-webhook を更新';
    RAISE NOTICE '  3. テスト実行';
    RAISE NOTICE '';
END $$;
