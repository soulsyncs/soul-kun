-- ============================================================================
-- インデックス最適化マイグレーション
-- マイグレーション: 20260131_index_optimization.sql
-- 作成日: 2026-01-31
-- 作成者: Claude Opus 4.5
--
-- 目的:
-- - クエリパフォーマンスの改善
-- - N+1問題の軽減
-- - 日次集計・分析クエリの高速化
--
-- 参照:
-- - Database Query Optimization Review (2026-01-31)
-- - docs/25_llm_native_brain_architecture.md セクション15
-- ============================================================================

-- NOTE: CONCURRENTLY を使用しているため、トランザクション外で実行してください
-- 本番適用時は各CREATEを個別に実行することを推奨

-- ============================================================================
-- 1. brain_conversation_states の複合インデックス
-- 目的: セッション状態取得クエリの高速化
-- ============================================================================

-- 状態取得用の複合インデックス
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_brain_conv_states_lookup
ON brain_conversation_states (organization_id, room_id, user_id);

-- 期限切れ状態のクリーンアップ用（部分インデックス）
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_brain_conv_states_expired
ON brain_conversation_states (expires_at)
WHERE expires_at IS NOT NULL;


-- ============================================================================
-- 2. ceo_teachings の検索最適化
-- 目的: アクティブなCEO教え検索の高速化
-- ============================================================================

-- アクティブな教えの検索用（部分インデックス）
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ceo_teachings_active_search
ON ceo_teachings (organization_id, is_active, validation_status)
WHERE is_active = true;

-- カテゴリ検索用
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ceo_teachings_category
ON ceo_teachings (organization_id, category)
WHERE is_active = true;


-- ============================================================================
-- 3. user_long_term_memory の検索最適化
-- 目的: メモリ検索クエリの高速化
-- ============================================================================

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_user_long_term_memory_lookup
ON user_long_term_memory (organization_id, user_id, memory_type);

-- 作成日時でのソート用
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_user_long_term_memory_created
ON user_long_term_memory (organization_id, user_id, created_at DESC);


-- ============================================================================
-- 4. brain_decision_logs の分析用インデックス
-- 目的: 低確信度判断の分析高速化
-- ============================================================================

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_decision_logs_analysis
ON brain_decision_logs (organization_id, selected_action, understanding_confidence)
WHERE understanding_confidence < 0.5;

-- 日付範囲での集計用
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_decision_logs_daily
ON brain_decision_logs (organization_id, created_at);


-- ============================================================================
-- 5. departments の LTREE インデックス
-- 目的: 階層クエリ（祖先/子孫検索）の高速化
-- ============================================================================

-- GiSTインデックスでLTREE演算子を高速化
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_departments_path_gist
ON departments USING GIST (path);


-- ============================================================================
-- 6. brain_observability_logs の追加インデックス
-- 目的: 新しく追加されたObservabilityテーブルの検索高速化
-- ============================================================================

-- 日次メトリクス集計用
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_brain_obs_logs_daily_metrics
ON brain_observability_logs (organization_id, DATE(created_at));

-- エラー分析用
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_brain_obs_logs_errors
ON brain_observability_logs (organization_id, execution_error_code)
WHERE execution_success = false;


-- ============================================================================
-- 完了メッセージ
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Index optimization migration completed';
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Added indexes:';
    RAISE NOTICE '  brain_conversation_states: 2';
    RAISE NOTICE '  ceo_teachings: 2';
    RAISE NOTICE '  user_long_term_memory: 2';
    RAISE NOTICE '  brain_decision_logs: 2';
    RAISE NOTICE '  departments: 1 (GiST)';
    RAISE NOTICE '  brain_observability_logs: 2';
    RAISE NOTICE '============================================================';
END $$;
