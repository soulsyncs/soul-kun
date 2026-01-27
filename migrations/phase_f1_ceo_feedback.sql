-- ============================================================
-- Phase F1: CEOフィードバックシステム マイグレーション
-- 作成日: 2026-01-27
-- 設計書: docs/20_next_generation_capabilities.md セクション8
-- ============================================================

-- ============================================================
-- 1. feedback_deliveries（フィードバック配信ログ）
-- ============================================================

CREATE TABLE IF NOT EXISTS feedback_deliveries (
    -- 主キー
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- テナント分離（鉄則: 全テーブルにorganization_id）
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- フィードバック情報
    feedback_id VARCHAR(100) NOT NULL,  -- UUIDまたは生成されたID
    feedback_type VARCHAR(50) NOT NULL,  -- 'daily_digest', 'weekly_review', 'monthly_insight', 'realtime_alert', 'on_demand'

    -- 受信者情報
    recipient_user_id UUID REFERENCES users(id),

    -- 配信情報
    channel VARCHAR(50) NOT NULL DEFAULT 'chatwork',  -- 配信チャネル
    channel_target VARCHAR(100),  -- チャネル固有の宛先（room_id等）
    message_id VARCHAR(100),  -- 配信されたメッセージのID

    -- タイミング
    delivered_at TIMESTAMPTZ,
    read_at TIMESTAMPTZ,
    actioned_at TIMESTAMPTZ,

    -- エラー情報
    error_message TEXT,
    retry_count INT DEFAULT 0,

    -- 機密区分（フィードバックは internal 以上）
    classification VARCHAR(20) NOT NULL DEFAULT 'internal',

    -- メタデータ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 制約
    CONSTRAINT check_feedback_type CHECK (
        feedback_type IN ('daily_digest', 'weekly_review', 'monthly_insight', 'realtime_alert', 'on_demand')
    ),
    CONSTRAINT check_channel CHECK (
        channel IN ('chatwork', 'email', 'slack', 'push')
    ),
    CONSTRAINT check_classification CHECK (
        classification IN ('public', 'internal', 'confidential', 'restricted')
    )
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_feedback_deliveries_org
    ON feedback_deliveries(organization_id);
CREATE INDEX IF NOT EXISTS idx_feedback_deliveries_type
    ON feedback_deliveries(feedback_type);
CREATE INDEX IF NOT EXISTS idx_feedback_deliveries_recipient
    ON feedback_deliveries(recipient_user_id);
CREATE INDEX IF NOT EXISTS idx_feedback_deliveries_delivered
    ON feedback_deliveries(delivered_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_deliveries_feedback_id
    ON feedback_deliveries(feedback_id);

-- 冪等性用のユニーク制約（同じフィードバックを二重配信しない）
CREATE UNIQUE INDEX IF NOT EXISTS idx_feedback_deliveries_unique
    ON feedback_deliveries(organization_id, feedback_id, channel);

-- コメント
COMMENT ON TABLE feedback_deliveries IS 'CEOフィードバックの配信ログ（Phase F1）';
COMMENT ON COLUMN feedback_deliveries.feedback_type IS 'フィードバックの種類: daily_digest, weekly_review, monthly_insight, realtime_alert, on_demand';
COMMENT ON COLUMN feedback_deliveries.channel IS '配信チャネル: chatwork, email, slack, push';


-- ============================================================
-- 2. feedback_settings（フィードバック設定）
-- ============================================================

CREATE TABLE IF NOT EXISTS feedback_settings (
    -- 主キー
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- テナント分離
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- 対象ユーザー（CEO等）
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- 配信先
    chatwork_room_id INT,  -- DMルームID

    -- 機能の有効/無効
    enable_daily_digest BOOLEAN DEFAULT TRUE,
    enable_weekly_review BOOLEAN DEFAULT TRUE,
    enable_monthly_insight BOOLEAN DEFAULT TRUE,
    enable_realtime_alert BOOLEAN DEFAULT TRUE,
    enable_on_demand BOOLEAN DEFAULT TRUE,

    -- 配信タイミング
    daily_digest_hour INT DEFAULT 8,  -- 8:00
    daily_digest_minute INT DEFAULT 0,
    weekly_review_day INT DEFAULT 0,  -- 0=月曜日
    weekly_review_hour INT DEFAULT 9,  -- 9:00

    -- アラート設定
    alert_cooldown_minutes INT DEFAULT 60,  -- アラート間隔
    max_daily_alerts INT DEFAULT 10,  -- 1日の最大アラート数

    -- 優先度閾値（この優先度以上のみ通知）
    min_alert_priority VARCHAR(20) DEFAULT 'high',  -- 'critical', 'high', 'medium', 'low'

    -- メタデータ
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_by UUID REFERENCES users(id),
    updated_by UUID REFERENCES users(id),

    -- ユニーク制約（組織内で1ユーザー1設定）
    CONSTRAINT unique_feedback_settings UNIQUE(organization_id, user_id),

    -- 制約
    CONSTRAINT check_daily_hour CHECK (daily_digest_hour >= 0 AND daily_digest_hour <= 23),
    CONSTRAINT check_daily_minute CHECK (daily_digest_minute >= 0 AND daily_digest_minute <= 59),
    CONSTRAINT check_weekly_day CHECK (weekly_review_day >= 0 AND weekly_review_day <= 6),
    CONSTRAINT check_weekly_hour CHECK (weekly_review_hour >= 0 AND weekly_review_hour <= 23),
    CONSTRAINT check_min_priority CHECK (
        min_alert_priority IN ('critical', 'high', 'medium', 'low')
    )
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_feedback_settings_org
    ON feedback_settings(organization_id);
CREATE INDEX IF NOT EXISTS idx_feedback_settings_user
    ON feedback_settings(user_id);
CREATE INDEX IF NOT EXISTS idx_feedback_settings_active
    ON feedback_settings(is_active)
    WHERE is_active = TRUE;

-- コメント
COMMENT ON TABLE feedback_settings IS 'CEOフィードバックの設定（Phase F1）';
COMMENT ON COLUMN feedback_settings.min_alert_priority IS 'この優先度以上のアラートのみ通知';


-- ============================================================
-- 3. feedback_alert_cooldowns（アラートクールダウン管理）
-- ============================================================

CREATE TABLE IF NOT EXISTS feedback_alert_cooldowns (
    -- 主キー
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- テナント分離
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- アラートタイプ（同じタイプのアラートは間隔を空ける）
    alert_type VARCHAR(100) NOT NULL,

    -- 対象（ユーザーIDやメトリック名）
    alert_subject VARCHAR(255),

    -- 最終アラート日時
    last_alerted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 次回アラート可能日時
    next_alert_allowed_at TIMESTAMPTZ NOT NULL,

    -- メタデータ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- ユニーク制約
    CONSTRAINT unique_alert_cooldown UNIQUE(organization_id, alert_type, alert_subject)
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_alert_cooldowns_org
    ON feedback_alert_cooldowns(organization_id);
CREATE INDEX IF NOT EXISTS idx_alert_cooldowns_next_allowed
    ON feedback_alert_cooldowns(next_alert_allowed_at);

-- コメント
COMMENT ON TABLE feedback_alert_cooldowns IS 'リアルタイムアラートのクールダウン管理（Phase F1）';
COMMENT ON COLUMN feedback_alert_cooldowns.next_alert_allowed_at IS 'この時刻以降にアラート可能';


-- ============================================================
-- 4. 分析用ビュー
-- ============================================================

-- フィードバック配信統計ビュー
CREATE OR REPLACE VIEW feedback_delivery_stats AS
SELECT
    organization_id,
    feedback_type,
    channel,
    DATE(delivered_at) as delivery_date,
    COUNT(*) as delivery_count,
    COUNT(CASE WHEN read_at IS NOT NULL THEN 1 END) as read_count,
    COUNT(CASE WHEN actioned_at IS NOT NULL THEN 1 END) as actioned_count,
    ROUND(
        COUNT(CASE WHEN read_at IS NOT NULL THEN 1 END)::DECIMAL /
        NULLIF(COUNT(*)::DECIMAL, 0) * 100,
        1
    ) as read_rate_percent
FROM feedback_deliveries
WHERE delivered_at IS NOT NULL
GROUP BY organization_id, feedback_type, channel, DATE(delivered_at);

COMMENT ON VIEW feedback_delivery_stats IS 'フィードバック配信の日次統計';


-- ============================================================
-- 5. 更新トリガー
-- ============================================================

-- feedback_settingsのupdated_at自動更新
CREATE OR REPLACE FUNCTION update_feedback_settings_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_feedback_settings_updated_at ON feedback_settings;
CREATE TRIGGER trigger_feedback_settings_updated_at
    BEFORE UPDATE ON feedback_settings
    FOR EACH ROW
    EXECUTE FUNCTION update_feedback_settings_updated_at();


-- ============================================================
-- 完了メッセージ
-- ============================================================

DO $$
BEGIN
    RAISE NOTICE '✅ Phase F1 CEOフィードバックシステム テーブル作成完了';
    RAISE NOTICE '  - feedback_deliveries: フィードバック配信ログ';
    RAISE NOTICE '  - feedback_settings: フィードバック設定';
    RAISE NOTICE '  - feedback_alert_cooldowns: アラートクールダウン管理';
    RAISE NOTICE '  - feedback_delivery_stats: 配信統計ビュー';
END $$;
