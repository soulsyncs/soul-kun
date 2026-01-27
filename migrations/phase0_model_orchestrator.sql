-- Phase 0: Model Orchestrator - DBマイグレーション
-- 設計書: docs/20_next_generation_capabilities.md セクション10
-- 作成日: 2026-01-27
--
-- 目的: 全AI呼び出しを統括するModel Orchestratorの基盤を構築
--
-- テーブル:
--   1. ai_model_registry - モデル情報マスタ
--   2. ai_usage_logs - 利用ログ
--   3. ai_organization_settings - 組織別設定
--   4. ai_monthly_cost_summary - 月次コストサマリー
--
-- 依存:
--   - organizations テーブル（既存）
--   - update_updated_at_column() 関数（既存）

BEGIN;

-- ============================================================================
-- 1. ai_model_registry テーブル
-- ============================================================================
--
-- AIモデルの情報マスタ
--
-- ティア（3種）:
--   - economy: 軽量タスク向け（Gemini Flash, GPT-4o-mini）
--   - standard: 標準タスク向け（GPT-4o, Claude Sonnet）
--   - premium: 重要タスク向け（Claude Opus, o1）
--
-- プロバイダー:
--   - anthropic: Claude系
--   - openai: GPT系
--   - google: Gemini系
--   - openrouter: OpenRouter経由

CREATE TABLE IF NOT EXISTS ai_model_registry (
    -- ============================================
    -- 識別情報
    -- ============================================
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- ============================================
    -- モデル情報
    -- ============================================
    model_id VARCHAR(100) NOT NULL UNIQUE,
    -- e.g., "anthropic/claude-opus-4-5-20251101", "openai/gpt-4o-2024-11-20"

    provider VARCHAR(50) NOT NULL,
    -- 'anthropic', 'openai', 'google', 'openrouter'

    display_name VARCHAR(200) NOT NULL,
    -- e.g., "Claude Opus 4.5", "GPT-4o"

    -- ============================================
    -- ティア・カテゴリ
    -- ============================================
    tier VARCHAR(20) NOT NULL,
    -- 'economy', 'standard', 'premium'

    capabilities JSONB NOT NULL DEFAULT '["text"]',
    -- e.g., ["text", "vision", "code"]

    -- ============================================
    -- コスト情報（USD/1M tokens → 円換算は計算時に実施）
    -- ============================================
    input_cost_per_1m_usd DECIMAL(10,6) NOT NULL,
    -- 入力トークン100万あたりのコスト（USD）

    output_cost_per_1m_usd DECIMAL(10,6) NOT NULL,
    -- 出力トークン100万あたりのコスト（USD）

    -- ============================================
    -- 性能パラメータ
    -- ============================================
    max_context_tokens INTEGER DEFAULT 128000,
    max_output_tokens INTEGER DEFAULT 4096,

    -- ============================================
    -- フォールバック順序
    -- ============================================
    fallback_priority INTEGER DEFAULT 100,
    -- 数字が小さいほど優先度が高い

    -- ============================================
    -- 状態
    -- ============================================
    is_active BOOLEAN DEFAULT TRUE,
    is_default_for_tier BOOLEAN DEFAULT FALSE,
    -- 各ティアのデフォルトモデルかどうか

    -- ============================================
    -- 監査
    -- ============================================
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- ============================================
    -- 制約
    -- ============================================
    CONSTRAINT check_tier CHECK (tier IN ('economy', 'standard', 'premium')),
    CONSTRAINT check_provider CHECK (provider IN ('anthropic', 'openai', 'google', 'openrouter'))
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_ai_model_registry_tier ON ai_model_registry(tier);
CREATE INDEX IF NOT EXISTS idx_ai_model_registry_active ON ai_model_registry(is_active);
CREATE INDEX IF NOT EXISTS idx_ai_model_registry_fallback ON ai_model_registry(tier, fallback_priority);

-- updated_at自動更新トリガー
DROP TRIGGER IF EXISTS update_ai_model_registry_updated_at ON ai_model_registry;
CREATE TRIGGER update_ai_model_registry_updated_at
    BEFORE UPDATE ON ai_model_registry
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- 2. ai_usage_logs テーブル
-- ============================================================================
--
-- AI呼び出しの利用ログ
--
-- ソウルくんの鉄則: organization_id必須（テナント分離）

CREATE TABLE IF NOT EXISTS ai_usage_logs (
    -- ============================================
    -- 識別情報
    -- ============================================
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    -- テナント分離（必須）

    -- ============================================
    -- リクエスト情報
    -- ============================================
    model_id VARCHAR(100) NOT NULL,
    -- ai_model_registry.model_id への参照（外部キーではなくVARCHAR）

    task_type VARCHAR(50) NOT NULL,
    -- 'conversation', 'emotion_detection', 'ceo_learning', etc.

    tier VARCHAR(20) NOT NULL,
    -- 実際に使用されたティア

    -- ============================================
    -- トークン使用量
    -- ============================================
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,

    -- ============================================
    -- コスト（円換算）
    -- ============================================
    cost_jpy DECIMAL(10,4) NOT NULL,
    -- 実際のコスト（円）

    -- ============================================
    -- リクエストコンテキスト
    -- ============================================
    room_id VARCHAR(50),
    user_id VARCHAR(50),
    request_hash VARCHAR(64),
    -- 重複検出用（SHA256ハッシュ）

    -- ============================================
    -- パフォーマンス
    -- ============================================
    latency_ms INTEGER,
    -- レスポンス時間（ミリ秒）

    -- ============================================
    -- フォールバック情報
    -- ============================================
    was_fallback BOOLEAN DEFAULT FALSE,
    original_model_id VARCHAR(100),
    -- フォールバック前の元モデル

    fallback_reason TEXT,
    -- フォールバック理由（エラーメッセージ等）

    fallback_attempt INTEGER DEFAULT 0,
    -- フォールバック回数

    -- ============================================
    -- 状態
    -- ============================================
    success BOOLEAN NOT NULL,
    error_message TEXT,

    -- ============================================
    -- 監査
    -- ============================================
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_ai_usage_logs_org_date
    ON ai_usage_logs(organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_usage_logs_task_type
    ON ai_usage_logs(task_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_usage_logs_model
    ON ai_usage_logs(model_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_usage_logs_success
    ON ai_usage_logs(organization_id, success, created_at DESC);

-- ============================================================================
-- 3. ai_organization_settings テーブル
-- ============================================================================
--
-- 組織ごとのModel Orchestrator設定
--
-- コスト閾値（4段階）:
--   - normal: < cost_threshold_warning
--   - warning: cost_threshold_warning <= cost < cost_threshold_caution
--   - caution: cost_threshold_caution <= cost < cost_threshold_limit
--   - limit: cost >= cost_threshold_limit

CREATE TABLE IF NOT EXISTS ai_organization_settings (
    -- ============================================
    -- 識別情報
    -- ============================================
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL UNIQUE,
    -- 1組織1レコード

    -- ============================================
    -- 月間予算（円）
    -- ============================================
    monthly_budget_jpy DECIMAL(12,2) DEFAULT 30000,
    -- デフォルト: 3万円/月

    -- ============================================
    -- 日次コスト閾値（円）
    -- ============================================
    cost_threshold_warning DECIMAL(10,2) DEFAULT 100,
    -- 100円/日で警告

    cost_threshold_caution DECIMAL(10,2) DEFAULT 500,
    -- 500円/日で自動ダウングレード

    cost_threshold_limit DECIMAL(10,2) DEFAULT 2000,
    -- 2000円/日でAI停止

    -- ============================================
    -- デフォルトティア
    -- ============================================
    default_tier VARCHAR(20) DEFAULT 'standard',
    -- 'economy', 'standard', 'premium'

    -- ============================================
    -- 機能フラグ
    -- ============================================
    enable_premium_tier BOOLEAN DEFAULT TRUE,
    -- premiumティアを使用可能か

    enable_auto_downgrade BOOLEAN DEFAULT TRUE,
    -- コスト超過時に自動ダウングレードするか

    enable_fallback BOOLEAN DEFAULT TRUE,
    -- フォールバックを有効化するか

    max_fallback_attempts INTEGER DEFAULT 3,
    -- 最大フォールバック回数

    -- ============================================
    -- 為替レート
    -- ============================================
    usd_to_jpy_rate DECIMAL(6,2) DEFAULT 150.00,
    -- USD→JPY換算レート（定期更新推奨）

    -- ============================================
    -- 監査
    -- ============================================
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_ai_organization_settings_org
    ON ai_organization_settings(organization_id);

-- updated_at自動更新トリガー
DROP TRIGGER IF EXISTS update_ai_organization_settings_updated_at ON ai_organization_settings;
CREATE TRIGGER update_ai_organization_settings_updated_at
    BEFORE UPDATE ON ai_organization_settings
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- 4. ai_monthly_cost_summary テーブル
-- ============================================================================
--
-- 月次コストサマリー（集計テーブル）
--
-- budget_status（4段階）:
--   - normal: 通常（残予算充分）
--   - warning: 警告（残予算50%以下）
--   - caution: 注意（残予算20%以下）
--   - limit: 制限（残予算0またはマイナス）

CREATE TABLE IF NOT EXISTS ai_monthly_cost_summary (
    -- ============================================
    -- 識別情報
    -- ============================================
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,

    -- ============================================
    -- 月
    -- ============================================
    year_month VARCHAR(7) NOT NULL,
    -- e.g., "2026-01"

    -- ============================================
    -- コスト集計
    -- ============================================
    total_cost_jpy DECIMAL(12,4) NOT NULL DEFAULT 0,
    total_requests INTEGER NOT NULL DEFAULT 0,
    total_input_tokens BIGINT NOT NULL DEFAULT 0,
    total_output_tokens BIGINT NOT NULL DEFAULT 0,

    -- ============================================
    -- ティア別集計
    -- ============================================
    economy_cost_jpy DECIMAL(12,4) DEFAULT 0,
    economy_requests INTEGER DEFAULT 0,

    standard_cost_jpy DECIMAL(12,4) DEFAULT 0,
    standard_requests INTEGER DEFAULT 0,

    premium_cost_jpy DECIMAL(12,4) DEFAULT 0,
    premium_requests INTEGER DEFAULT 0,

    -- ============================================
    -- 予算状態
    -- ============================================
    budget_jpy DECIMAL(12,2),
    -- 月初に設定される予算

    budget_remaining_jpy DECIMAL(12,2),
    -- 残予算（budget_jpy - total_cost_jpy）

    budget_status VARCHAR(20) DEFAULT 'normal',
    -- 'normal', 'warning', 'caution', 'limit'

    -- ============================================
    -- フォールバック統計
    -- ============================================
    fallback_count INTEGER DEFAULT 0,
    fallback_success_count INTEGER DEFAULT 0,

    -- ============================================
    -- エラー統計
    -- ============================================
    error_count INTEGER DEFAULT 0,

    -- ============================================
    -- 監査
    -- ============================================
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- ============================================
    -- 制約
    -- ============================================
    CONSTRAINT unique_org_month UNIQUE(organization_id, year_month),
    CONSTRAINT check_budget_status CHECK (budget_status IN ('normal', 'warning', 'caution', 'limit'))
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_ai_monthly_cost_summary_org_month
    ON ai_monthly_cost_summary(organization_id, year_month DESC);
CREATE INDEX IF NOT EXISTS idx_ai_monthly_cost_summary_status
    ON ai_monthly_cost_summary(budget_status, year_month DESC);

-- updated_at自動更新トリガー
DROP TRIGGER IF EXISTS update_ai_monthly_cost_summary_updated_at ON ai_monthly_cost_summary;
CREATE TRIGGER update_ai_monthly_cost_summary_updated_at
    BEFORE UPDATE ON ai_monthly_cost_summary
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- 5. 初期データ投入: モデルレジストリ
-- ============================================================================

-- 既存データクリア（冪等性のため）
DELETE FROM ai_model_registry WHERE model_id LIKE '%/%';

-- Economy Tier Models
INSERT INTO ai_model_registry (
    model_id, provider, display_name, tier, capabilities,
    input_cost_per_1m_usd, output_cost_per_1m_usd,
    max_context_tokens, max_output_tokens,
    fallback_priority, is_default_for_tier
) VALUES
-- Google Gemini Flash Lite (Economy)
(
    'google/gemini-2.0-flash-lite',
    'google',
    'Gemini 2.0 Flash Lite',
    'economy',
    '["text"]',
    0.075,
    0.30,
    1000000,
    8192,
    10,
    TRUE
),
-- OpenAI GPT-4o Mini (Economy)
(
    'openai/gpt-4o-mini',
    'openai',
    'GPT-4o Mini',
    'economy',
    '["text", "vision"]',
    0.15,
    0.60,
    128000,
    16384,
    20,
    FALSE
);

-- Standard Tier Models
INSERT INTO ai_model_registry (
    model_id, provider, display_name, tier, capabilities,
    input_cost_per_1m_usd, output_cost_per_1m_usd,
    max_context_tokens, max_output_tokens,
    fallback_priority, is_default_for_tier
) VALUES
-- Google Gemini 2.5 Pro (Standard - Default)
(
    'google/gemini-2.5-pro-preview',
    'google',
    'Gemini 2.5 Pro',
    'standard',
    '["text", "vision", "code"]',
    1.25,
    5.00,
    1000000,
    8192,
    10,
    TRUE
),
-- OpenAI GPT-4o (Standard)
(
    'openai/gpt-4o',
    'openai',
    'GPT-4o',
    'standard',
    '["text", "vision", "code"]',
    2.50,
    10.00,
    128000,
    16384,
    20,
    FALSE
),
-- Anthropic Claude 3.5 Sonnet (Standard)
(
    'anthropic/claude-3-5-sonnet-latest',
    'anthropic',
    'Claude 3.5 Sonnet',
    'standard',
    '["text", "vision", "code"]',
    3.00,
    15.00,
    200000,
    8192,
    30,
    FALSE
);

-- Premium Tier Models
INSERT INTO ai_model_registry (
    model_id, provider, display_name, tier, capabilities,
    input_cost_per_1m_usd, output_cost_per_1m_usd,
    max_context_tokens, max_output_tokens,
    fallback_priority, is_default_for_tier
) VALUES
-- Anthropic Claude Opus 4.5 (Premium - Default)
(
    'anthropic/claude-opus-4-5-20251101',
    'anthropic',
    'Claude Opus 4.5',
    'premium',
    '["text", "vision", "code"]',
    15.00,
    75.00,
    200000,
    32000,
    10,
    TRUE
),
-- OpenAI o1 (Premium)
(
    'openai/o1',
    'openai',
    'OpenAI o1',
    'premium',
    '["text", "code"]',
    15.00,
    60.00,
    200000,
    100000,
    20,
    FALSE
),
-- Google Gemini Ultra (Premium)
(
    'google/gemini-2.0-ultra',
    'google',
    'Gemini 2.0 Ultra',
    'premium',
    '["text", "vision", "code"]',
    10.00,
    40.00,
    1000000,
    8192,
    30,
    FALSE
);

COMMIT;

-- ============================================================================
-- マイグレーション確認用クエリ
-- ============================================================================
-- SELECT 'ai_model_registry' as table_name, COUNT(*) as count FROM ai_model_registry
-- UNION ALL
-- SELECT 'ai_usage_logs', COUNT(*) FROM ai_usage_logs
-- UNION ALL
-- SELECT 'ai_organization_settings', COUNT(*) FROM ai_organization_settings
-- UNION ALL
-- SELECT 'ai_monthly_cost_summary', COUNT(*) FROM ai_monthly_cost_summary;
