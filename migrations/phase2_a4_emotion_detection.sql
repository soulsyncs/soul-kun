-- =====================================================
-- Phase 2 A4: 感情変化検出 マイグレーション
-- =====================================================
--
-- 実行方法:
--   cloud-sql-proxy で接続後、psqlで実行
--
-- 作成日: 2026-01-24
-- 作成者: Claude Code
--
-- プライバシー注意:
--   - emotion_scores, emotion_alerts は全て CONFIDENTIAL 分類
--   - メッセージ本文は保存しない（統計データのみ）
--   - 従業員のメンタルヘルス情報のため厳重管理
-- =====================================================

-- トランザクション開始
BEGIN;

-- =====================================================
-- 1. emotion_scores テーブル作成
--    （メッセージごとの感情分析結果）
-- =====================================================

CREATE TABLE IF NOT EXISTS emotion_scores (
    -- 基本情報
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,

    -- メッセージ参照（room_messages.message_id）
    message_id BIGINT NOT NULL,
    room_id BIGINT NOT NULL,
    user_id UUID NOT NULL,

    -- 感情分析結果
    sentiment_score DECIMAL(4,3) NOT NULL,
    sentiment_label VARCHAR(20) NOT NULL,
    confidence DECIMAL(4,3),
    detected_emotions TEXT[] DEFAULT '{}',

    -- LLM分析メタ情報
    analysis_model VARCHAR(100),

    -- タイムスタンプ
    message_time TIMESTAMPTZ NOT NULL,
    analyzed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 機密区分（常にCONFIDENTIAL - DBレベルで強制）
    classification VARCHAR(20) DEFAULT 'confidential'
        CONSTRAINT check_emotion_scores_classification
        CHECK (classification = 'confidential'),

    -- 監査フィールド
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 制約
    UNIQUE(organization_id, message_id),
    CONSTRAINT check_sentiment_score_range
        CHECK (sentiment_score >= -1.0 AND sentiment_score <= 1.0),
    CONSTRAINT check_confidence_range
        CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)),
    CONSTRAINT check_sentiment_label
        CHECK (sentiment_label IN ('very_negative', 'negative', 'neutral', 'positive', 'very_positive'))
);

COMMENT ON TABLE emotion_scores IS
'Phase 2進化版 A4: 感情スコア（メッセージ単位）
- メッセージごとの感情分析結果を保存
- CONFIDENTIAL分類（従業員メンタル情報）
- メッセージ本文は保存しない（プライバシー保護）';

-- =====================================================
-- 2. emotion_alerts テーブル作成
--    （感情変化検出アラート）
-- =====================================================

CREATE TABLE IF NOT EXISTS emotion_alerts (
    -- 基本情報
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,

    -- 対象ユーザー
    user_id UUID NOT NULL,
    user_name VARCHAR(255),
    department_id UUID,

    -- アラート詳細
    alert_type VARCHAR(50) NOT NULL,
    risk_level VARCHAR(20) NOT NULL,

    -- 感情データ（統計のみ、本文なし）
    baseline_score DECIMAL(4,3),
    current_score DECIMAL(4,3),
    score_change DECIMAL(4,3),
    consecutive_negative_days INT DEFAULT 0,

    -- 分析期間
    analysis_start_date DATE NOT NULL,
    analysis_end_date DATE NOT NULL,

    -- エビデンス（統計のみ、メッセージ本文は含めない）
    message_count INT DEFAULT 0,
    negative_message_count INT DEFAULT 0,
    evidence JSONB DEFAULT '{}',

    -- ステータス
    status VARCHAR(20) DEFAULT 'active',
    first_detected_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_detected_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMPTZ,
    resolution_notes TEXT,

    -- 機密区分（常にCONFIDENTIAL - DBレベルで強制）
    classification VARCHAR(20) DEFAULT 'confidential'
        CONSTRAINT check_emotion_alerts_classification
        CHECK (classification = 'confidential'),

    -- 監査フィールド
    created_by UUID,
    updated_by UUID,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 制約
    UNIQUE(organization_id, user_id, alert_type, analysis_start_date),
    CONSTRAINT check_emotion_alert_type CHECK (
        alert_type IN ('sudden_drop', 'sustained_negative', 'high_volatility', 'recovery')
    ),
    CONSTRAINT check_emotion_risk_level CHECK (
        risk_level IN ('critical', 'high', 'medium', 'low')
    ),
    CONSTRAINT check_emotion_alert_status CHECK (
        status IN ('active', 'resolved', 'dismissed')
    ),
    CONSTRAINT check_baseline_score_range
        CHECK (baseline_score IS NULL OR (baseline_score >= -1.0 AND baseline_score <= 1.0)),
    CONSTRAINT check_current_score_range
        CHECK (current_score IS NULL OR (current_score >= -1.0 AND current_score <= 1.0))
);

COMMENT ON TABLE emotion_alerts IS
'Phase 2進化版 A4: 感情変化アラート
- 感情変化を検出してアラートを生成
- sudden_drop: 急激な感情悪化
- sustained_negative: 継続的なネガティブ
- high_volatility: 感情の不安定さ
- recovery: 回復（ポジティブ変化）
- CONFIDENTIAL分類（従業員メンタル情報）
- soulkun_insights と連携して管理者に通知';

-- =====================================================
-- 3. インデックス作成
-- =====================================================

-- emotion_scores インデックス
CREATE INDEX IF NOT EXISTS idx_emotion_scores_user_time
    ON emotion_scores(organization_id, user_id, message_time DESC);

CREATE INDEX IF NOT EXISTS idx_emotion_scores_org_time
    ON emotion_scores(organization_id, message_time DESC);

CREATE INDEX IF NOT EXISTS idx_emotion_scores_negative
    ON emotion_scores(organization_id, sentiment_label)
    WHERE sentiment_label IN ('negative', 'very_negative');

CREATE INDEX IF NOT EXISTS idx_emotion_scores_analyzed_at
    ON emotion_scores(organization_id, analyzed_at DESC);

-- emotion_alerts インデックス
CREATE INDEX IF NOT EXISTS idx_emotion_alerts_org_type
    ON emotion_alerts(organization_id, alert_type);

CREATE INDEX IF NOT EXISTS idx_emotion_alerts_org_level
    ON emotion_alerts(organization_id, risk_level);

CREATE INDEX IF NOT EXISTS idx_emotion_alerts_user
    ON emotion_alerts(organization_id, user_id);

CREATE INDEX IF NOT EXISTS idx_emotion_alerts_status
    ON emotion_alerts(organization_id, status)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_emotion_alerts_department
    ON emotion_alerts(organization_id, department_id)
    WHERE department_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_emotion_alerts_detected_at
    ON emotion_alerts(organization_id, last_detected_at DESC);

-- =====================================================
-- 4. updated_at 自動更新トリガー
-- =====================================================

-- トリガー関数が存在しない場合は作成
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- emotion_alerts用トリガー
DROP TRIGGER IF EXISTS trg_emotion_alerts_updated_at ON emotion_alerts;
CREATE TRIGGER trg_emotion_alerts_updated_at
    BEFORE UPDATE ON emotion_alerts
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- =====================================================
-- 5. notification_logs の CHECK 制約更新
--    （emotion_alert を追加）
-- =====================================================

-- 既存の制約を削除（存在する場合）
ALTER TABLE notification_logs DROP CONSTRAINT IF EXISTS check_notification_type;

-- 新しい制約を追加（A4用の通知タイプを含む）
ALTER TABLE notification_logs ADD CONSTRAINT check_notification_type
CHECK (notification_type IN (
    -- タスク管理系
    'task_reminder', 'task_overdue', 'task_escalation',
    'deadline_alert', 'escalation_alert', 'dm_unavailable',
    -- 目標設定系
    'goal_daily_check', 'goal_daily_reminder', 'goal_morning_feedback',
    'goal_team_summary', 'goal_consecutive_unanswered', 'goal_reminder',
    -- 会議系
    'meeting_reminder',
    -- A1パターン検出
    'pattern_alert', 'weekly_report',
    -- A2属人化検出
    'personalization_alert',
    -- A3ボトルネック検出
    'bottleneck_alert',
    -- A4感情変化検出（新規）
    'emotion_alert'
));

COMMENT ON CONSTRAINT check_notification_type ON notification_logs IS
'notification_type の許可値:
- task_*: タスク管理系
- goal_*: 目標設定系
- meeting_*: 会議系
- pattern_alert, weekly_report: A1パターン検出
- personalization_alert: A2属人化検出
- bottleneck_alert: A3ボトルネック検出
- emotion_alert: A4感情変化検出（v10.20.0追加）';

-- =====================================================
-- 6. 確認クエリ
-- =====================================================

DO $$
DECLARE
    emotion_scores_count INT;
    emotion_alerts_count INT;
    es_index_count INT;
    ea_index_count INT;
BEGIN
    -- テーブル数確認
    SELECT COUNT(*) INTO emotion_scores_count
    FROM information_schema.tables
    WHERE table_schema = 'public'
    AND table_name = 'emotion_scores';

    SELECT COUNT(*) INTO emotion_alerts_count
    FROM information_schema.tables
    WHERE table_schema = 'public'
    AND table_name = 'emotion_alerts';

    -- インデックス数確認
    SELECT COUNT(*) INTO es_index_count
    FROM pg_indexes
    WHERE schemaname = 'public'
    AND indexname LIKE '%emotion_scores%';

    SELECT COUNT(*) INTO ea_index_count
    FROM pg_indexes
    WHERE schemaname = 'public'
    AND indexname LIKE '%emotion_alerts%';

    RAISE NOTICE '========================================';
    RAISE NOTICE 'Phase 2 A4 マイグレーション完了';
    RAISE NOTICE '========================================';
    RAISE NOTICE 'emotion_scores テーブル: %', CASE WHEN emotion_scores_count = 1 THEN 'OK' ELSE 'ERROR' END;
    RAISE NOTICE 'emotion_alerts テーブル: %', CASE WHEN emotion_alerts_count = 1 THEN 'OK' ELSE 'ERROR' END;
    RAISE NOTICE 'emotion_scores インデックス数: %', es_index_count;
    RAISE NOTICE 'emotion_alerts インデックス数: %', ea_index_count;
    RAISE NOTICE '';
    RAISE NOTICE '注意: このデータはCONFIDENTIAL分類です';
    RAISE NOTICE '従業員のメンタルヘルス情報として厳重に管理してください';
END $$;

-- コミット
COMMIT;
