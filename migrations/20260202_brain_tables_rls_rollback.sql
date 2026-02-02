-- ============================================================================
-- brain_* テーブル RLS ロールバック
--
-- 用途: 本番適用後に問題が発生した場合のロールバック用
-- 実行方法: psql -d $DATABASE -f migrations/20260202_brain_tables_rls_rollback.sql
--
-- 注意: このファイルは20260202_brain_tables_rls.sqlの逆操作
-- ============================================================================

BEGIN;

-- ============================================================================
-- Phase 2E: 学習基盤
-- ============================================================================

-- brain_learnings
DROP POLICY IF EXISTS brain_learnings_org_isolation ON brain_learnings;
ALTER TABLE brain_learnings DISABLE ROW LEVEL SECURITY;

-- brain_learning_logs
DROP POLICY IF EXISTS brain_learning_logs_org_isolation ON brain_learning_logs;
ALTER TABLE brain_learning_logs DISABLE ROW LEVEL SECURITY;

-- ============================================================================
-- Phase 2F: 結果学習
-- ============================================================================

-- brain_outcome_events
DROP POLICY IF EXISTS brain_outcome_events_org_isolation ON brain_outcome_events;
ALTER TABLE brain_outcome_events DISABLE ROW LEVEL SECURITY;

-- brain_outcome_patterns
DROP POLICY IF EXISTS brain_outcome_patterns_org_isolation ON brain_outcome_patterns;
ALTER TABLE brain_outcome_patterns DISABLE ROW LEVEL SECURITY;

-- ============================================================================
-- Phase 2G: 記憶強化
-- ============================================================================

-- brain_episodes
DROP POLICY IF EXISTS brain_episodes_org_isolation ON brain_episodes;
ALTER TABLE brain_episodes DISABLE ROW LEVEL SECURITY;

-- brain_episode_entities
DROP POLICY IF EXISTS brain_episode_entities_org_isolation ON brain_episode_entities;
ALTER TABLE brain_episode_entities DISABLE ROW LEVEL SECURITY;

-- brain_knowledge_nodes
DROP POLICY IF EXISTS brain_knowledge_nodes_org_isolation ON brain_knowledge_nodes;
ALTER TABLE brain_knowledge_nodes DISABLE ROW LEVEL SECURITY;

-- brain_knowledge_edges
DROP POLICY IF EXISTS brain_knowledge_edges_org_isolation ON brain_knowledge_edges;
ALTER TABLE brain_knowledge_edges DISABLE ROW LEVEL SECURITY;

-- brain_temporal_events
DROP POLICY IF EXISTS brain_temporal_events_org_isolation ON brain_temporal_events;
ALTER TABLE brain_temporal_events DISABLE ROW LEVEL SECURITY;

-- brain_temporal_comparisons
DROP POLICY IF EXISTS brain_temporal_comparisons_org_isolation ON brain_temporal_comparisons;
ALTER TABLE brain_temporal_comparisons DISABLE ROW LEVEL SECURITY;

-- brain_memory_consolidations
DROP POLICY IF EXISTS brain_memory_consolidations_org_isolation ON brain_memory_consolidations;
ALTER TABLE brain_memory_consolidations DISABLE ROW LEVEL SECURITY;

-- ============================================================================
-- Phase 2H: 自己認識
-- ============================================================================

-- brain_ability_scores
DROP POLICY IF EXISTS brain_ability_scores_org_isolation ON brain_ability_scores;
ALTER TABLE brain_ability_scores DISABLE ROW LEVEL SECURITY;

-- brain_limitations
DROP POLICY IF EXISTS brain_limitations_org_isolation ON brain_limitations;
ALTER TABLE brain_limitations DISABLE ROW LEVEL SECURITY;

-- brain_improvement_logs
DROP POLICY IF EXISTS brain_improvement_logs_org_isolation ON brain_improvement_logs;
ALTER TABLE brain_improvement_logs DISABLE ROW LEVEL SECURITY;

-- brain_self_diagnoses
DROP POLICY IF EXISTS brain_self_diagnoses_org_isolation ON brain_self_diagnoses;
ALTER TABLE brain_self_diagnoses DISABLE ROW LEVEL SECURITY;

-- brain_confidence_logs
DROP POLICY IF EXISTS brain_confidence_logs_org_isolation ON brain_confidence_logs;
ALTER TABLE brain_confidence_logs DISABLE ROW LEVEL SECURITY;

-- ============================================================================
-- Phase C: 脳状態管理
-- ============================================================================

-- brain_conversation_states
DROP POLICY IF EXISTS brain_conversation_states_org_isolation ON brain_conversation_states;
ALTER TABLE brain_conversation_states DISABLE ROW LEVEL SECURITY;

-- brain_decision_logs
DROP POLICY IF EXISTS brain_decision_logs_org_isolation ON brain_decision_logs;
ALTER TABLE brain_decision_logs DISABLE ROW LEVEL SECURITY;

-- brain_state_history
DROP POLICY IF EXISTS brain_state_history_org_isolation ON brain_state_history;
ALTER TABLE brain_state_history DISABLE ROW LEVEL SECURITY;

-- ============================================================================
-- Neural Connection Repair
-- ============================================================================

-- brain_dialogue_logs
DROP POLICY IF EXISTS brain_dialogue_logs_org_isolation ON brain_dialogue_logs;
ALTER TABLE brain_dialogue_logs DISABLE ROW LEVEL SECURITY;

COMMIT;

-- ============================================================================
-- 確認用クエリ
-- ============================================================================
-- SELECT tablename, rowsecurity FROM pg_tables
-- WHERE tablename LIKE 'brain_%' AND schemaname = 'public';
