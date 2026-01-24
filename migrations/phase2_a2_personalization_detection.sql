-- =====================================================
-- Phase 2 A2: 属人化検出 マイグレーション
-- =====================================================
--
-- 実行方法:
--   cloud-sql-proxy で接続後、psqlで実行
--
-- 作成日: 2026-01-24
-- 作成者: Claude Code
-- =====================================================

-- トランザクション開始
BEGIN;

-- =====================================================
-- 1. personalization_risks テーブル作成
-- =====================================================

CREATE TABLE IF NOT EXISTS personalization_risks (
    -- 基本情報
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- 部署フィルタ（Phase 3.5準拠）
    department_id UUID REFERENCES departments(id) ON DELETE SET NULL,

    -- 属人化対象
    expert_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    topic_category VARCHAR(50) NOT NULL,
    topic_keywords TEXT[] DEFAULT '{}',

    -- 統計
    total_responses INT DEFAULT 0,
    expert_responses INT DEFAULT 0,
    personalization_ratio DECIMAL(5,4),
    first_detected_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_detected_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    consecutive_days INT DEFAULT 0,

    -- 代替者情報
    alternative_responders UUID[] DEFAULT '{}',
    has_alternative BOOLEAN DEFAULT false,

    -- サンプルデータ
    sample_questions TEXT[] DEFAULT '{}',
    sample_responses TEXT[] DEFAULT '{}',

    -- ステータス
    risk_level VARCHAR(20) DEFAULT 'low',
    status VARCHAR(20) DEFAULT 'active',
    mitigated_at TIMESTAMPTZ,
    mitigation_action TEXT,

    -- 機密区分
    classification VARCHAR(20) DEFAULT 'internal',

    -- 監査フィールド
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 制約
    UNIQUE(organization_id, expert_user_id, topic_category),
    CONSTRAINT check_risk_level CHECK (risk_level IN ('critical', 'high', 'medium', 'low')),
    CONSTRAINT check_status CHECK (status IN ('active', 'mitigated', 'dismissed'))
);

COMMENT ON TABLE personalization_risks IS
'Phase 2進化版 A2: 属人化リスクの記録
- 特定の人にしか回答できない状態を検出
- BCPリスクとして管理者に通知';

-- =====================================================
-- 2. インデックス作成
-- =====================================================

CREATE INDEX IF NOT EXISTS idx_personalization_risks_org_level
    ON personalization_risks(organization_id, risk_level);

CREATE INDEX IF NOT EXISTS idx_personalization_risks_expert
    ON personalization_risks(organization_id, expert_user_id);

CREATE INDEX IF NOT EXISTS idx_personalization_risks_status
    ON personalization_risks(organization_id, status)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_personalization_risks_department
    ON personalization_risks(organization_id, department_id)
    WHERE department_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_personalization_risks_category
    ON personalization_risks(organization_id, topic_category);

-- =====================================================
-- 3. response_logs テーブル作成（回答追跡用）
-- =====================================================

CREATE TABLE IF NOT EXISTS response_logs (
    -- 基本情報
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- 回答情報
    question_message_id BIGINT NOT NULL,
    response_message_id BIGINT NOT NULL,
    responder_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    room_id BIGINT NOT NULL,

    -- 分類
    topic_category VARCHAR(50),
    question_text TEXT,
    response_text TEXT,

    -- タイムスタンプ
    question_time TIMESTAMPTZ NOT NULL,
    response_time TIMESTAMPTZ NOT NULL,
    response_delay_seconds INT,

    -- 監査フィールド
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 制約
    UNIQUE(organization_id, question_message_id, response_message_id)
);

COMMENT ON TABLE response_logs IS
'Phase 2進化版 A2: 回答ログ
- 誰がどのカテゴリの質問に回答したかを記録
- 属人化検出の分析に使用';

-- =====================================================
-- 4. response_logs インデックス作成
-- =====================================================

CREATE INDEX IF NOT EXISTS idx_response_logs_org_responder
    ON response_logs(organization_id, responder_user_id, topic_category);

CREATE INDEX IF NOT EXISTS idx_response_logs_org_time
    ON response_logs(organization_id, response_time DESC);

CREATE INDEX IF NOT EXISTS idx_response_logs_org_category
    ON response_logs(organization_id, topic_category, response_time DESC);

-- =====================================================
-- 5. notification_logs の CHECK 制約更新
-- =====================================================

-- 既存の制約を削除（存在する場合）
ALTER TABLE notification_logs DROP CONSTRAINT IF EXISTS check_notification_type;

-- 新しい制約を追加（A2用の通知タイプを含む）
ALTER TABLE notification_logs ADD CONSTRAINT check_notification_type
CHECK (notification_type IN (
    -- 既存
    'task_reminder', 'task_overdue', 'task_escalation',
    'deadline_alert', 'escalation_alert', 'dm_unavailable',
    'goal_daily_check', 'goal_daily_reminder', 'goal_morning_feedback',
    'goal_team_summary', 'goal_consecutive_unanswered',
    -- A1パターン検出
    'pattern_alert', 'weekly_report',
    -- A2属人化検出（新規）
    'personalization_alert'
));

-- =====================================================
-- 6. updated_at 自動更新トリガー
-- =====================================================

-- personalization_risks用
DROP TRIGGER IF EXISTS trg_personalization_risks_updated_at ON personalization_risks;
CREATE TRIGGER trg_personalization_risks_updated_at
    BEFORE UPDATE ON personalization_risks
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- =====================================================
-- 7. soulkun_insights に A2 用の source_type を許可
-- =====================================================
-- (既存のテーブルはTEXT型なので制約更新不要)

-- =====================================================
-- 確認クエリ
-- =====================================================

DO $$
DECLARE
    table_count INT;
    index_count INT;
BEGIN
    -- テーブル数確認
    SELECT COUNT(*) INTO table_count
    FROM information_schema.tables
    WHERE table_schema = 'public'
    AND table_name IN ('personalization_risks', 'response_logs');

    -- インデックス数確認
    SELECT COUNT(*) INTO index_count
    FROM pg_indexes
    WHERE schemaname = 'public'
    AND indexname LIKE '%personalization%' OR indexname LIKE '%response_logs%';

    RAISE NOTICE '================================';
    RAISE NOTICE 'Phase 2 A2 マイグレーション完了';
    RAISE NOTICE '================================';
    RAISE NOTICE '作成テーブル数: %', table_count;
    RAISE NOTICE '作成インデックス数: %', index_count;
END $$;

-- コミット
COMMIT;
