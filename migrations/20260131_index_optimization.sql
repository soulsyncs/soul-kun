-- =====================================================================
-- インデックス最適化マイグレーション
--
-- 目的: クエリパフォーマンスの向上
-- 作成日: 2026-01-31
-- 作成者: Claude Opus 4.5（データベースレビュー結果に基づく）
--
-- 参照: セキュリティ・品質レビュー 2026-01-31
-- =====================================================================

-- =====================================================================
-- 1. brain_conversation_states の複合インデックス
-- =====================================================================

-- メイン検索用（organization_id, room_id, user_idの組み合わせ）
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_brain_conv_states_lookup
ON brain_conversation_states (organization_id, room_id, user_id);

-- 期限切れ状態のクリーンアップ用（部分インデックス）
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_brain_conv_states_expired
ON brain_conversation_states (expires_at)
WHERE expires_at IS NOT NULL;

-- =====================================================================
-- 2. ceo_teachings の検索最適化
-- =====================================================================

-- アクティブな教えの検索用
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ceo_teachings_active_search
ON ceo_teachings (organization_id, is_active, validation_status)
WHERE is_active = true;

-- ソート用（priority, usage_count）
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ceo_teachings_sort
ON ceo_teachings (priority DESC, usage_count DESC)
WHERE is_active = true;

-- =====================================================================
-- 3. user_long_term_memory の検索最適化
-- =====================================================================

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_user_long_term_memory_lookup
ON user_long_term_memory (organization_id, user_id, memory_type);

-- =====================================================================
-- 4. brain_decision_logs の分析用インデックス
-- =====================================================================

-- 低確信度の判断を分析するためのインデックス
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_decision_logs_low_confidence
ON brain_decision_logs (organization_id, selected_action, understanding_confidence)
WHERE understanding_confidence < 0.5;

-- =====================================================================
-- 5. departments の LTREE インデックス
-- =====================================================================

-- GiSTインデックスでLTREE演算子を高速化
-- 注意: 既に存在する場合はスキップ
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE indexname = 'idx_departments_path_gist'
    ) THEN
        CREATE INDEX idx_departments_path_gist
        ON departments USING GIST (path);
    END IF;
END $$;

-- =====================================================================
-- 6. guardian_alerts の検索用インデックス
-- =====================================================================

-- ペンディングアラートの検索用
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_guardian_alerts_pending
ON guardian_alerts (organization_id, status, created_at)
WHERE status = 'pending';

-- =====================================================================
-- 7. goals テーブルの検索最適化
-- =====================================================================

-- ユーザーの目標検索用
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_goals_user_lookup
ON goals (organization_id, user_id, status);

-- =====================================================================
-- 確認用クエリ
-- =====================================================================

-- インデックスの確認（実行後に手動で確認）
-- SELECT indexname, indexdef
-- FROM pg_indexes
-- WHERE tablename IN (
--     'brain_conversation_states',
--     'ceo_teachings',
--     'user_long_term_memory',
--     'brain_decision_logs',
--     'departments',
--     'guardian_alerts',
--     'goals'
-- )
-- ORDER BY tablename, indexname;
