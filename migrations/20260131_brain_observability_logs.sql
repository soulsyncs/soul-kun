-- ============================================================================
-- Brain Observability Logs テーブル
-- マイグレーション: 20260131_brain_observability_logs.sql
-- 作成日: 2026-01-31
-- 作成者: Claude Opus 4.5
--
-- 目的:
-- - LLM Brain の全判断過程を記録する
-- - 設計書 docs/25_llm_native_brain_architecture.md セクション15に基づく
-- - 本番モニタリング・パフォーマンス最適化に使用
--
-- 記録する情報（設計書15章より）:
-- - 入力メッセージ
-- - LLMの思考過程（Chain-of-Thought）
-- - 選択されたTool・パラメータ
-- - Guardian/AuthGateの判定結果
-- - 実行結果
-- - コスト情報
--
-- 10の鉄則チェック:
-- - [x] #1 全テーブルにorganization_id
-- - [x] #3 監査ログ対応（classification = confidential）
-- - [x] #5 ページネーション対応（インデックス）
-- - [x] #6 キャッシュ対応（updated_at、TTL考慮）
-- - [x] #9 SQLインジェクション対策（パラメータ化前提）
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. brain_observability_logs テーブル
-- LLM Brain の全判断を記録するメインテーブル
-- ============================================================================
CREATE TABLE IF NOT EXISTS brain_observability_logs (
    -- ========================================
    -- 識別情報
    -- ========================================
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    user_id VARCHAR(100) NOT NULL,       -- ChatWork account_id
    room_id VARCHAR(100),                 -- ChatWorkルームID
    session_id VARCHAR(100),              -- セッションID（確認フロー追跡用）

    -- ========================================
    -- リクエスト情報
    -- ========================================
    message_preview VARCHAR(200),         -- 入力メッセージ（先頭200文字、プライバシー保護）
    message_hash VARCHAR(64),             -- メッセージのSHA256ハッシュ（重複検出用）

    -- ========================================
    -- LLM Brain 判断情報
    -- ========================================
    -- 意図判定
    detected_intent VARCHAR(100),         -- 判定された意図
    output_type VARCHAR(50) NOT NULL      -- "tool_call" / "text_response" / "clarification_needed"
        CHECK (output_type IN ('tool_call', 'text_response', 'clarification_needed', 'error')),

    -- 思考過程（Chain-of-Thought）
    reasoning TEXT,                       -- LLMの思考過程

    -- Tool呼び出し情報
    tool_name VARCHAR(100),               -- 選択されたTool名
    tool_parameters JSONB,                -- Toolに渡されたパラメータ
    tool_count INTEGER DEFAULT 0,         -- 呼び出されたTool数

    -- 確信度スコア
    confidence_overall DECIMAL(3,2)       -- 総合確信度（0.00〜1.00）
        CHECK (confidence_overall IS NULL OR (confidence_overall >= 0.00 AND confidence_overall <= 1.00)),
    confidence_intent DECIMAL(3,2)        -- 意図理解の確信度
        CHECK (confidence_intent IS NULL OR (confidence_intent >= 0.00 AND confidence_intent <= 1.00)),
    confidence_parameters DECIMAL(3,2)    -- パラメータ抽出の確信度
        CHECK (confidence_parameters IS NULL OR (confidence_parameters >= 0.00 AND confidence_parameters <= 1.00)),

    -- ========================================
    -- Guardian Layer 判定情報
    -- ========================================
    guardian_action VARCHAR(20)           -- "allow" / "confirm" / "block" / "modify"
        CHECK (guardian_action IS NULL OR guardian_action IN ('allow', 'confirm', 'block', 'modify')),
    guardian_reason TEXT,                 -- 判定理由
    guardian_risk_level VARCHAR(20)       -- "low" / "medium" / "high" / "critical"
        CHECK (guardian_risk_level IS NULL OR guardian_risk_level IN ('low', 'medium', 'high', 'critical')),
    guardian_check_type VARCHAR(50),      -- どのチェックで判定されたか

    -- ========================================
    -- Authorization Gate 判定情報
    -- ========================================
    auth_gate_action VARCHAR(20)          -- "allow" / "deny"
        CHECK (auth_gate_action IS NULL OR auth_gate_action IN ('allow', 'deny')),
    auth_gate_reason TEXT,                -- 判定理由

    -- ========================================
    -- 実行結果
    -- ========================================
    execution_success BOOLEAN,            -- 実行成功/失敗
    execution_error_code VARCHAR(100),    -- エラーコード
    execution_error_message TEXT,         -- エラーメッセージ
    execution_result_summary VARCHAR(500), -- 結果概要

    -- ========================================
    -- パフォーマンス・コスト情報
    -- ========================================
    -- LLM API
    model_used VARCHAR(100),              -- 使用したモデル（例: "openai/gpt-5.2"）
    api_provider VARCHAR(50),             -- API提供元（"openrouter" / "anthropic"）
    input_tokens INTEGER DEFAULT 0,       -- 入力トークン数
    output_tokens INTEGER DEFAULT 0,      -- 出力トークン数

    -- 時間
    llm_response_time_ms INTEGER,         -- LLM応答時間（ミリ秒）
    guardian_check_time_ms INTEGER,       -- Guardian判定時間（ミリ秒）
    total_response_time_ms INTEGER,       -- 総応答時間（ミリ秒）

    -- コスト（円）
    estimated_cost_yen DECIMAL(10,4),     -- 推定コスト（円）

    -- ========================================
    -- 確認フロー情報
    -- ========================================
    needs_confirmation BOOLEAN DEFAULT FALSE,
    confirmation_question TEXT,           -- 確認質問文
    confirmation_status VARCHAR(20)       -- "pending" / "approved" / "denied" / "timeout"
        CHECK (confirmation_status IS NULL OR confirmation_status IN ('pending', 'approved', 'denied', 'timeout')),
    confirmation_response_at TIMESTAMPTZ,

    -- ========================================
    -- メタデータ
    -- ========================================
    classification VARCHAR(20) DEFAULT 'confidential'
        CHECK (classification IN ('public', 'internal', 'confidential', 'restricted')),
    environment VARCHAR(20) DEFAULT 'production'
        CHECK (environment IN ('development', 'staging', 'production')),
    version VARCHAR(20),                  -- ソウルくんのバージョン

    -- ========================================
    -- タイムスタンプ
    -- ========================================
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- 2. インデックス
-- クエリパターンに基づいて最適化
-- ============================================================================

-- 基本検索用（organization_id + 時間範囲）
CREATE INDEX IF NOT EXISTS idx_brain_obs_org_created
    ON brain_observability_logs(organization_id, created_at DESC);

-- ユーザー別検索
CREATE INDEX IF NOT EXISTS idx_brain_obs_user
    ON brain_observability_logs(organization_id, user_id, created_at DESC);

-- 日別集計用（パーティションキー候補）
CREATE INDEX IF NOT EXISTS idx_brain_obs_date
    ON brain_observability_logs(DATE(created_at));

-- Tool使用分析
CREATE INDEX IF NOT EXISTS idx_brain_obs_tool
    ON brain_observability_logs(tool_name)
    WHERE tool_name IS NOT NULL;

-- Guardian判定分析
CREATE INDEX IF NOT EXISTS idx_brain_obs_guardian
    ON brain_observability_logs(guardian_action)
    WHERE guardian_action IS NOT NULL;

-- エラー分析
CREATE INDEX IF NOT EXISTS idx_brain_obs_errors
    ON brain_observability_logs(execution_success)
    WHERE execution_success = FALSE;

-- 確認フロー分析
CREATE INDEX IF NOT EXISTS idx_brain_obs_confirmation
    ON brain_observability_logs(confirmation_status)
    WHERE needs_confirmation = TRUE;

-- コスト分析用
CREATE INDEX IF NOT EXISTS idx_brain_obs_cost
    ON brain_observability_logs(organization_id, DATE(created_at), estimated_cost_yen)
    WHERE estimated_cost_yen IS NOT NULL;

-- パフォーマンス分析用（遅いリクエスト検出）
CREATE INDEX IF NOT EXISTS idx_brain_obs_slow
    ON brain_observability_logs(total_response_time_ms DESC)
    WHERE total_response_time_ms > 10000;  -- 10秒超

-- ========================================
-- 部分インデックス（よく使うパターン）
-- ========================================

-- 本番環境のみ
CREATE INDEX IF NOT EXISTS idx_brain_obs_prod
    ON brain_observability_logs(organization_id, created_at DESC)
    WHERE environment = 'production';

-- ブロックされたリクエスト
CREATE INDEX IF NOT EXISTS idx_brain_obs_blocked
    ON brain_observability_logs(organization_id, created_at DESC)
    WHERE guardian_action = 'block';


-- ============================================================================
-- 3. brain_daily_metrics テーブル
-- 日次集計メトリクス（設計書15.2のダッシュボード用）
-- ============================================================================
CREATE TABLE IF NOT EXISTS brain_daily_metrics (
    -- 識別情報
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    metric_date DATE NOT NULL,

    -- 会話統計
    total_conversations INTEGER DEFAULT 0,
    unique_users INTEGER DEFAULT 0,

    -- 応答時間
    avg_response_time_ms INTEGER,
    p50_response_time_ms INTEGER,
    p95_response_time_ms INTEGER,
    p99_response_time_ms INTEGER,
    max_response_time_ms INTEGER,

    -- 確信度
    avg_confidence DECIMAL(3,2),
    min_confidence DECIMAL(3,2),

    -- Tool使用
    tool_call_count INTEGER DEFAULT 0,
    text_response_count INTEGER DEFAULT 0,
    clarification_count INTEGER DEFAULT 0,

    -- Guardian判定
    allow_count INTEGER DEFAULT 0,
    confirm_count INTEGER DEFAULT 0,
    block_count INTEGER DEFAULT 0,

    -- 実行結果
    success_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    error_rate DECIMAL(5,2),              -- エラー率（%）

    -- コスト
    total_input_tokens BIGINT DEFAULT 0,
    total_output_tokens BIGINT DEFAULT 0,
    total_cost_yen DECIMAL(12,2) DEFAULT 0,

    -- アラート
    slow_request_count INTEGER DEFAULT 0, -- 10秒超のリクエスト数
    high_error_alert BOOLEAN DEFAULT FALSE,
    high_block_alert BOOLEAN DEFAULT FALSE,
    high_cost_alert BOOLEAN DEFAULT FALSE,

    -- メタデータ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- ユニーク制約
    CONSTRAINT unique_org_date UNIQUE(organization_id, metric_date)
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_daily_metrics_org
    ON brain_daily_metrics(organization_id, metric_date DESC);

CREATE INDEX IF NOT EXISTS idx_daily_metrics_alerts
    ON brain_daily_metrics(metric_date DESC)
    WHERE high_error_alert = TRUE OR high_block_alert = TRUE OR high_cost_alert = TRUE;


-- ============================================================================
-- 4. brain_user_feedback テーブル
-- ユーザーフィードバック（応答品質計測用）
-- ============================================================================
CREATE TABLE IF NOT EXISTS brain_user_feedback (
    -- 識別情報
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    log_id UUID REFERENCES brain_observability_logs(id) ON DELETE SET NULL,
    user_id VARCHAR(100) NOT NULL,

    -- フィードバック
    rating INTEGER CHECK (rating >= 1 AND rating <= 5),  -- 1-5星
    is_helpful BOOLEAN,                   -- 役に立ったか
    feedback_type VARCHAR(50)             -- "helpful" / "not_helpful" / "wrong" / "slow" / "other"
        CHECK (feedback_type IN ('helpful', 'not_helpful', 'wrong', 'slow', 'other')),
    comment TEXT,                         -- 自由記述

    -- メタデータ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_feedback_org
    ON brain_user_feedback(organization_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_feedback_log
    ON brain_user_feedback(log_id)
    WHERE log_id IS NOT NULL;


-- ============================================================================
-- 5. 日次集計バッチ用関数
-- ============================================================================
CREATE OR REPLACE FUNCTION aggregate_brain_daily_metrics(
    p_organization_id UUID,
    p_date DATE
)
RETURNS void AS $$
BEGIN
    INSERT INTO brain_daily_metrics (
        organization_id,
        metric_date,
        total_conversations,
        unique_users,
        avg_response_time_ms,
        p50_response_time_ms,
        p95_response_time_ms,
        p99_response_time_ms,
        max_response_time_ms,
        avg_confidence,
        min_confidence,
        tool_call_count,
        text_response_count,
        clarification_count,
        allow_count,
        confirm_count,
        block_count,
        success_count,
        error_count,
        error_rate,
        total_input_tokens,
        total_output_tokens,
        total_cost_yen,
        slow_request_count,
        high_error_alert,
        high_block_alert,
        high_cost_alert
    )
    SELECT
        p_organization_id,
        p_date,
        -- 会話統計
        COUNT(*),
        COUNT(DISTINCT user_id),
        -- 応答時間
        AVG(total_response_time_ms)::INTEGER,
        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY total_response_time_ms)::INTEGER,
        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_response_time_ms)::INTEGER,
        PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY total_response_time_ms)::INTEGER,
        MAX(total_response_time_ms),
        -- 確信度
        AVG(confidence_overall),
        MIN(confidence_overall),
        -- Tool使用
        COUNT(*) FILTER (WHERE output_type = 'tool_call'),
        COUNT(*) FILTER (WHERE output_type = 'text_response'),
        COUNT(*) FILTER (WHERE output_type = 'clarification_needed'),
        -- Guardian判定
        COUNT(*) FILTER (WHERE guardian_action = 'allow'),
        COUNT(*) FILTER (WHERE guardian_action = 'confirm'),
        COUNT(*) FILTER (WHERE guardian_action = 'block'),
        -- 実行結果
        COUNT(*) FILTER (WHERE execution_success = TRUE),
        COUNT(*) FILTER (WHERE execution_success = FALSE),
        CASE WHEN COUNT(*) > 0
            THEN (COUNT(*) FILTER (WHERE execution_success = FALSE)::DECIMAL / COUNT(*) * 100)
            ELSE 0
        END,
        -- コスト
        COALESCE(SUM(input_tokens), 0),
        COALESCE(SUM(output_tokens), 0),
        COALESCE(SUM(estimated_cost_yen), 0),
        -- アラート用
        COUNT(*) FILTER (WHERE total_response_time_ms > 10000),
        -- エラー率 > 5%
        CASE WHEN COUNT(*) > 0
            THEN (COUNT(*) FILTER (WHERE execution_success = FALSE)::DECIMAL / COUNT(*) * 100) > 5
            ELSE FALSE
        END,
        -- ブロック率 > 10%
        CASE WHEN COUNT(*) > 0
            THEN (COUNT(*) FILTER (WHERE guardian_action = 'block')::DECIMAL / COUNT(*) * 100) > 10
            ELSE FALSE
        END,
        -- コスト > 5000円/日
        COALESCE(SUM(estimated_cost_yen), 0) > 5000
    FROM brain_observability_logs
    WHERE organization_id = p_organization_id
      AND DATE(created_at) = p_date
      AND environment = 'production'
    ON CONFLICT (organization_id, metric_date) DO UPDATE SET
        total_conversations = EXCLUDED.total_conversations,
        unique_users = EXCLUDED.unique_users,
        avg_response_time_ms = EXCLUDED.avg_response_time_ms,
        p50_response_time_ms = EXCLUDED.p50_response_time_ms,
        p95_response_time_ms = EXCLUDED.p95_response_time_ms,
        p99_response_time_ms = EXCLUDED.p99_response_time_ms,
        max_response_time_ms = EXCLUDED.max_response_time_ms,
        avg_confidence = EXCLUDED.avg_confidence,
        min_confidence = EXCLUDED.min_confidence,
        tool_call_count = EXCLUDED.tool_call_count,
        text_response_count = EXCLUDED.text_response_count,
        clarification_count = EXCLUDED.clarification_count,
        allow_count = EXCLUDED.allow_count,
        confirm_count = EXCLUDED.confirm_count,
        block_count = EXCLUDED.block_count,
        success_count = EXCLUDED.success_count,
        error_count = EXCLUDED.error_count,
        error_rate = EXCLUDED.error_rate,
        total_input_tokens = EXCLUDED.total_input_tokens,
        total_output_tokens = EXCLUDED.total_output_tokens,
        total_cost_yen = EXCLUDED.total_cost_yen,
        slow_request_count = EXCLUDED.slow_request_count,
        high_error_alert = EXCLUDED.high_error_alert,
        high_block_alert = EXCLUDED.high_block_alert,
        high_cost_alert = EXCLUDED.high_cost_alert,
        updated_at = CURRENT_TIMESTAMP;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 6. データ保持ポリシー（90日）
-- 古いログを自動削除するための関数
-- ============================================================================
CREATE OR REPLACE FUNCTION cleanup_old_brain_logs(
    p_retention_days INTEGER DEFAULT 90
)
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM brain_observability_logs
    WHERE created_at < CURRENT_TIMESTAMP - (p_retention_days || ' days')::INTERVAL;

    GET DIAGNOSTICS deleted_count = ROW_COUNT;

    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;


-- ============================================================================
-- 7. アラート用ビュー
-- 設計書15.1の監視項目を簡単に確認できるビュー
-- ============================================================================
CREATE OR REPLACE VIEW v_brain_alerts AS
SELECT
    organization_id,
    metric_date,
    -- 設計書15.1の閾値に基づくアラート
    CASE
        WHEN avg_response_time_ms > 10000 THEN '警告: LLM応答時間 > 10秒'
        ELSE NULL
    END AS response_time_alert,
    CASE
        WHEN error_rate > 5 THEN '警告: エラー率 > 5%'
        ELSE NULL
    END AS error_rate_alert,
    CASE
        WHEN confirm_count::DECIMAL / NULLIF(total_conversations, 0) * 100 > 30
        THEN '情報: 確認モード発生率 > 30%'
        ELSE NULL
    END AS confirm_rate_alert,
    CASE
        WHEN block_count::DECIMAL / NULLIF(total_conversations, 0) * 100 > 10
        THEN '警告: ブロック発生率 > 10%'
        ELSE NULL
    END AS block_rate_alert,
    CASE
        WHEN total_cost_yen > 5000 THEN '警告: 日次コスト > 5,000円'
        ELSE NULL
    END AS cost_alert,
    -- サマリー
    total_conversations,
    avg_response_time_ms,
    error_rate,
    total_cost_yen
FROM brain_daily_metrics
WHERE metric_date >= CURRENT_DATE - INTERVAL '7 days'
ORDER BY metric_date DESC, organization_id;


-- ============================================================================
-- 8. ダッシュボード用ビュー
-- 設計書15.2のダッシュボード形式
-- ============================================================================
CREATE OR REPLACE VIEW v_brain_dashboard AS
SELECT
    organization_id,
    metric_date,
    -- 今日の統計
    total_conversations AS "総会話数",
    ROUND(avg_response_time_ms / 1000.0, 1) AS "平均応答時間（秒）",
    avg_confidence AS "確信度平均",
    confirm_count AS "確認モード回数",
    ROUND(confirm_count::DECIMAL / NULLIF(total_conversations, 0) * 100, 1) AS "確認モード率（%）",
    block_count AS "ブロック回数",
    ROUND(block_count::DECIMAL / NULLIF(total_conversations, 0) * 100, 1) AS "ブロック率（%）",
    -- コスト
    total_cost_yen AS "本日コスト（円）"
FROM brain_daily_metrics
ORDER BY metric_date DESC, organization_id;


-- ============================================================================
-- 9. 設計書への追記用コメント
-- ============================================================================
COMMENT ON TABLE brain_observability_logs IS
'LLM Brain の全判断過程を記録するテーブル。
設計書: docs/25_llm_native_brain_architecture.md セクション15
保持期間: 90日（cleanup_old_brain_logs関数で削除）';

COMMENT ON TABLE brain_daily_metrics IS
'日次集計メトリクス。設計書15.2のダッシュボード用。
aggregate_brain_daily_metrics関数で毎日集計';

COMMENT ON TABLE brain_user_feedback IS
'ユーザーフィードバック。LLM Brainの応答品質を計測';


COMMIT;

-- ============================================================================
-- 使用例
-- ============================================================================
--
-- -- 日次集計の実行
-- SELECT aggregate_brain_daily_metrics('org-uuid-here', CURRENT_DATE);
--
-- -- アラートの確認
-- SELECT * FROM v_brain_alerts WHERE metric_date = CURRENT_DATE;
--
-- -- ダッシュボードの表示
-- SELECT * FROM v_brain_dashboard WHERE metric_date >= CURRENT_DATE - 7;
--
-- -- 古いログの削除（90日以上前）
-- SELECT cleanup_old_brain_logs(90);
