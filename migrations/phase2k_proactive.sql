-- ============================================================
-- Phase 2K: 能動性（Proactivity）マイグレーション
-- 作成日: 2026-01-27
-- 設計書: docs/17_brain_completion_roadmap.md Phase 2K
-- ============================================================

-- ============================================================
-- 1. proactive_action_logs（能動的アクションログ）
-- ============================================================

CREATE TABLE IF NOT EXISTS proactive_action_logs (
    -- 主キー
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- テナント分離（鉄則: 全テーブルにorganization_id）
    organization_id UUID NOT NULL,

    -- 対象ユーザー
    user_id UUID NOT NULL,

    -- トリガー情報
    trigger_type VARCHAR(50) NOT NULL,  -- goal_abandoned, task_overload, emotion_decline, etc.
    trigger_details JSONB NOT NULL DEFAULT '{}',
    priority VARCHAR(20) NOT NULL DEFAULT 'medium',  -- critical, high, medium, low

    -- メッセージ情報
    message_type VARCHAR(50) NOT NULL,  -- follow_up, encouragement, reminder, celebration, check_in
    message_text TEXT NOT NULL,

    -- 配信情報
    channel VARCHAR(50) NOT NULL DEFAULT 'chatwork',
    channel_target VARCHAR(100),  -- room_id等
    chatwork_message_id VARCHAR(100),

    -- 結果
    success BOOLEAN NOT NULL DEFAULT false,
    error_message TEXT,

    -- ユーザー反応
    user_responded BOOLEAN DEFAULT false,
    user_response_at TIMESTAMPTZ,
    user_response_positive BOOLEAN,  -- ポジティブな反応だったか

    -- メタデータ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 制約
    CONSTRAINT check_trigger_type CHECK (
        trigger_type IN (
            'goal_abandoned', 'task_overload', 'emotion_decline',
            'question_unanswered', 'goal_achieved', 'task_completed_streak',
            'long_absence'
        )
    ),
    CONSTRAINT check_priority CHECK (
        priority IN ('critical', 'high', 'medium', 'low')
    ),
    CONSTRAINT check_message_type CHECK (
        message_type IN ('follow_up', 'encouragement', 'reminder', 'celebration', 'check_in')
    )
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_proactive_logs_org
    ON proactive_action_logs(organization_id);
CREATE INDEX IF NOT EXISTS idx_proactive_logs_user
    ON proactive_action_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_proactive_logs_trigger
    ON proactive_action_logs(trigger_type);
CREATE INDEX IF NOT EXISTS idx_proactive_logs_created
    ON proactive_action_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_proactive_logs_success
    ON proactive_action_logs(success);

-- 重複防止用（同じユーザーに同じトリガーで短時間に複数送信しない）
CREATE INDEX IF NOT EXISTS idx_proactive_logs_cooldown
    ON proactive_action_logs(organization_id, user_id, trigger_type, created_at DESC);

-- コメント
COMMENT ON TABLE proactive_action_logs IS 'Phase 2K: 能動的アクション（ソウルくんから声かけ）のログ';
COMMENT ON COLUMN proactive_action_logs.trigger_type IS 'トリガータイプ: goal_abandoned, task_overload, emotion_decline, question_unanswered, goal_achieved, task_completed_streak, long_absence';
COMMENT ON COLUMN proactive_action_logs.message_type IS 'メッセージタイプ: follow_up, encouragement, reminder, celebration, check_in';


-- ============================================================
-- 2. proactive_cooldowns（クールダウン管理）
-- ============================================================

CREATE TABLE IF NOT EXISTS proactive_cooldowns (
    -- 主キー
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- テナント分離
    organization_id UUID NOT NULL,

    -- 対象
    user_id UUID NOT NULL,
    trigger_type VARCHAR(50) NOT NULL,

    -- クールダウン情報
    last_sent_at TIMESTAMPTZ NOT NULL,
    cooldown_until TIMESTAMPTZ NOT NULL,

    -- メタデータ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- ユニーク制約（1ユーザー1トリガータイプにつき1レコード）
    CONSTRAINT unique_user_trigger UNIQUE (organization_id, user_id, trigger_type)
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_proactive_cooldowns_lookup
    ON proactive_cooldowns(organization_id, user_id, trigger_type);
CREATE INDEX IF NOT EXISTS idx_proactive_cooldowns_until
    ON proactive_cooldowns(cooldown_until);

-- コメント
COMMENT ON TABLE proactive_cooldowns IS 'Phase 2K: 能動的メッセージのクールダウン管理';


-- ============================================================
-- 3. proactive_settings（能動性設定）
-- ============================================================

CREATE TABLE IF NOT EXISTS proactive_settings (
    -- 主キー
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- テナント分離
    organization_id UUID NOT NULL,

    -- 対象（NULLなら組織全体のデフォルト）
    user_id UUID,

    -- 設定
    enabled BOOLEAN NOT NULL DEFAULT true,

    -- 各トリガーの有効/無効
    goal_abandoned_enabled BOOLEAN DEFAULT true,
    task_overload_enabled BOOLEAN DEFAULT true,
    emotion_decline_enabled BOOLEAN DEFAULT true,
    question_unanswered_enabled BOOLEAN DEFAULT true,
    goal_achieved_enabled BOOLEAN DEFAULT true,
    task_completed_streak_enabled BOOLEAN DEFAULT true,
    long_absence_enabled BOOLEAN DEFAULT true,

    -- カスタム閾値（NULLならデフォルト値を使用）
    goal_abandoned_days INT,  -- デフォルト: 7
    task_overload_count INT,  -- デフォルト: 5
    emotion_decline_days INT, -- デフォルト: 3
    long_absence_days INT,    -- デフォルト: 14

    -- 時間帯制限（この時間帯のみメッセージ送信）
    quiet_hours_start TIME,  -- 例: 22:00
    quiet_hours_end TIME,    -- 例: 08:00

    -- メタデータ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- ユニーク制約
    CONSTRAINT unique_org_user_settings UNIQUE (organization_id, user_id)
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_proactive_settings_org
    ON proactive_settings(organization_id);
CREATE INDEX IF NOT EXISTS idx_proactive_settings_user
    ON proactive_settings(organization_id, user_id);

-- コメント
COMMENT ON TABLE proactive_settings IS 'Phase 2K: 能動性機能の設定（組織/ユーザー単位）';


-- ============================================================
-- 4. proactive_stats（統計ビュー）
-- ============================================================

CREATE OR REPLACE VIEW v_proactive_stats AS
SELECT
    organization_id,
    DATE(created_at AT TIME ZONE 'Asia/Tokyo') as date_jst,
    trigger_type,
    COUNT(*) as total_actions,
    SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful_actions,
    SUM(CASE WHEN user_responded THEN 1 ELSE 0 END) as user_responded,
    SUM(CASE WHEN user_response_positive THEN 1 ELSE 0 END) as positive_responses,
    ROUND(
        SUM(CASE WHEN success THEN 1 ELSE 0 END)::NUMERIC / NULLIF(COUNT(*), 0) * 100,
        2
    ) as success_rate,
    ROUND(
        SUM(CASE WHEN user_responded THEN 1 ELSE 0 END)::NUMERIC / NULLIF(SUM(CASE WHEN success THEN 1 ELSE 0 END), 0) * 100,
        2
    ) as response_rate
FROM proactive_action_logs
GROUP BY organization_id, DATE(created_at AT TIME ZONE 'Asia/Tokyo'), trigger_type;

COMMENT ON VIEW v_proactive_stats IS 'Phase 2K: 能動的アクションの日別統計';


-- ============================================================
-- 5. Feature Flagの追加
-- ============================================================

INSERT INTO feature_flags (name, enabled, description, created_at)
VALUES
    ('USE_PROACTIVE_MONITOR', false, 'Phase 2K: 能動的モニタリング機能', CURRENT_TIMESTAMP),
    ('PROACTIVE_DRY_RUN', true, 'Phase 2K: ドライラン（メッセージ送信せずログのみ）', CURRENT_TIMESTAMP)
ON CONFLICT (name) DO UPDATE SET
    description = EXCLUDED.description,
    updated_at = CURRENT_TIMESTAMP;


-- ============================================================
-- 6. トリガー（updated_at自動更新）
-- ============================================================

CREATE OR REPLACE FUNCTION update_proactive_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_proactive_cooldowns_updated_at ON proactive_cooldowns;
CREATE TRIGGER trigger_proactive_cooldowns_updated_at
    BEFORE UPDATE ON proactive_cooldowns
    FOR EACH ROW
    EXECUTE FUNCTION update_proactive_updated_at();

DROP TRIGGER IF EXISTS trigger_proactive_settings_updated_at ON proactive_settings;
CREATE TRIGGER trigger_proactive_settings_updated_at
    BEFORE UPDATE ON proactive_settings
    FOR EACH ROW
    EXECUTE FUNCTION update_proactive_updated_at();


-- ============================================================
-- 完了メッセージ
-- ============================================================

DO $$
BEGIN
    RAISE NOTICE '✅ Phase 2K 能動性（Proactivity）テーブル作成完了';
    RAISE NOTICE '   - proactive_action_logs: 能動的アクションログ';
    RAISE NOTICE '   - proactive_cooldowns: クールダウン管理';
    RAISE NOTICE '   - proactive_settings: 設定';
    RAISE NOTICE '   - v_proactive_stats: 統計ビュー';
    RAISE NOTICE '   - Feature Flags: USE_PROACTIVE_MONITOR, PROACTIVE_DRY_RUN';
END $$;
