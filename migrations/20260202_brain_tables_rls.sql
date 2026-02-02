-- ============================================================================
-- brain_* テーブル RLS (Row Level Security) 追加
--
-- 目的: organization_id によるテナント分離
-- CLAUDE.md 鉄則#2: RLS（Row Level Security）を実装
--
-- 対象テーブル:
--   Phase 2E: brain_learnings, brain_learning_logs
--   Phase 2F: brain_outcome_events, brain_outcome_patterns
--   Phase 2G: brain_episodes, brain_episode_entities, brain_knowledge_nodes,
--             brain_knowledge_edges, brain_temporal_events,
--             brain_temporal_comparisons, brain_memory_consolidations
--   Phase 2H: brain_ability_scores, brain_limitations, brain_improvement_logs,
--             brain_self_diagnoses, brain_confidence_logs
--   Phase C:  brain_conversation_states, brain_decision_logs, brain_state_history
--   Neural:   brain_dialogue_logs
--
-- 作成日: 2026-02-02
-- ============================================================================

-- ============================================================================
-- Phase 2E: 学習基盤
-- ============================================================================

-- brain_learnings
ALTER TABLE brain_learnings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS brain_learnings_org_isolation ON brain_learnings;
CREATE POLICY brain_learnings_org_isolation ON brain_learnings
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);

-- brain_learning_logs
ALTER TABLE brain_learning_logs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS brain_learning_logs_org_isolation ON brain_learning_logs;
CREATE POLICY brain_learning_logs_org_isolation ON brain_learning_logs
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);

-- ============================================================================
-- Phase 2F: 結果学習
-- ============================================================================

-- brain_outcome_events (organization_idがある場合のみ)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'brain_outcome_events' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE brain_outcome_events ENABLE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS brain_outcome_events_org_isolation ON brain_outcome_events;
        CREATE POLICY brain_outcome_events_org_isolation ON brain_outcome_events
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- brain_outcome_patterns (organization_idがある場合のみ)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'brain_outcome_patterns' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE brain_outcome_patterns ENABLE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS brain_outcome_patterns_org_isolation ON brain_outcome_patterns;
        CREATE POLICY brain_outcome_patterns_org_isolation ON brain_outcome_patterns
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- ============================================================================
-- Phase 2G: 記憶強化
-- ============================================================================

-- brain_episodes
ALTER TABLE brain_episodes ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS brain_episodes_org_isolation ON brain_episodes;
CREATE POLICY brain_episodes_org_isolation ON brain_episodes
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);

-- brain_episode_entities
ALTER TABLE brain_episode_entities ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS brain_episode_entities_org_isolation ON brain_episode_entities;
CREATE POLICY brain_episode_entities_org_isolation ON brain_episode_entities
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);

-- brain_knowledge_nodes
ALTER TABLE brain_knowledge_nodes ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS brain_knowledge_nodes_org_isolation ON brain_knowledge_nodes;
CREATE POLICY brain_knowledge_nodes_org_isolation ON brain_knowledge_nodes
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);

-- brain_knowledge_edges
ALTER TABLE brain_knowledge_edges ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS brain_knowledge_edges_org_isolation ON brain_knowledge_edges;
CREATE POLICY brain_knowledge_edges_org_isolation ON brain_knowledge_edges
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);

-- brain_temporal_events
ALTER TABLE brain_temporal_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS brain_temporal_events_org_isolation ON brain_temporal_events;
CREATE POLICY brain_temporal_events_org_isolation ON brain_temporal_events
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);

-- brain_temporal_comparisons
ALTER TABLE brain_temporal_comparisons ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS brain_temporal_comparisons_org_isolation ON brain_temporal_comparisons;
CREATE POLICY brain_temporal_comparisons_org_isolation ON brain_temporal_comparisons
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);

-- brain_memory_consolidations
ALTER TABLE brain_memory_consolidations ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS brain_memory_consolidations_org_isolation ON brain_memory_consolidations;
CREATE POLICY brain_memory_consolidations_org_isolation ON brain_memory_consolidations
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);

-- ============================================================================
-- Phase 2H: 自己認識
-- 注意: これらのテーブルはorganization_idがVARCHAR(255)型
-- ============================================================================

-- brain_ability_scores (organization_idがある場合のみ)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'brain_ability_scores' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE brain_ability_scores ENABLE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS brain_ability_scores_org_isolation ON brain_ability_scores;
        CREATE POLICY brain_ability_scores_org_isolation ON brain_ability_scores
            USING (organization_id = current_setting('app.current_organization_id', true))
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true));
    END IF;
END $$;

-- brain_limitations (organization_idがある場合のみ)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'brain_limitations' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE brain_limitations ENABLE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS brain_limitations_org_isolation ON brain_limitations;
        CREATE POLICY brain_limitations_org_isolation ON brain_limitations
            USING (organization_id = current_setting('app.current_organization_id', true))
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true));
    END IF;
END $$;

-- brain_improvement_logs (organization_idがある場合のみ)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'brain_improvement_logs' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE brain_improvement_logs ENABLE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS brain_improvement_logs_org_isolation ON brain_improvement_logs;
        CREATE POLICY brain_improvement_logs_org_isolation ON brain_improvement_logs
            USING (organization_id = current_setting('app.current_organization_id', true))
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true));
    END IF;
END $$;

-- brain_self_diagnoses (organization_idがある場合のみ)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'brain_self_diagnoses' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE brain_self_diagnoses ENABLE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS brain_self_diagnoses_org_isolation ON brain_self_diagnoses;
        CREATE POLICY brain_self_diagnoses_org_isolation ON brain_self_diagnoses
            USING (organization_id = current_setting('app.current_organization_id', true))
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true));
    END IF;
END $$;

-- brain_confidence_logs (organization_idがある場合のみ)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'brain_confidence_logs' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE brain_confidence_logs ENABLE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS brain_confidence_logs_org_isolation ON brain_confidence_logs;
        CREATE POLICY brain_confidence_logs_org_isolation ON brain_confidence_logs
            USING (organization_id = current_setting('app.current_organization_id', true))
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true));
    END IF;
END $$;

-- ============================================================================
-- Phase C: 脳状態管理
-- ============================================================================

-- brain_conversation_states
ALTER TABLE brain_conversation_states ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS brain_conversation_states_org_isolation ON brain_conversation_states;
CREATE POLICY brain_conversation_states_org_isolation ON brain_conversation_states
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);

-- brain_decision_logs
ALTER TABLE brain_decision_logs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS brain_decision_logs_org_isolation ON brain_decision_logs;
CREATE POLICY brain_decision_logs_org_isolation ON brain_decision_logs
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);

-- brain_state_history
ALTER TABLE brain_state_history ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS brain_state_history_org_isolation ON brain_state_history;
CREATE POLICY brain_state_history_org_isolation ON brain_state_history
    USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);

-- ============================================================================
-- Neural Connection Repair
-- ============================================================================

-- brain_dialogue_logs (organization_idがある場合のみ)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'brain_dialogue_logs' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE brain_dialogue_logs ENABLE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS brain_dialogue_logs_org_isolation ON brain_dialogue_logs;
        CREATE POLICY brain_dialogue_logs_org_isolation ON brain_dialogue_logs
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- ============================================================================
-- 検証クエリ（実行後の確認用）
-- ============================================================================

-- RLSが有効になったテーブル一覧を確認
-- SELECT schemaname, tablename, rowsecurity
-- FROM pg_tables
-- WHERE tablename LIKE 'brain_%' AND rowsecurity = true;

-- ポリシー一覧を確認
-- SELECT schemaname, tablename, policyname
-- FROM pg_policies
-- WHERE tablename LIKE 'brain_%';

-- ============================================================================
-- 注意事項
-- ============================================================================
--
-- 1. アプリケーションからDBに接続する際、以下を実行してorganization_idを設定する必要がある:
--    SET app.current_organization_id = 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx';
--
-- 2. superuserまたはテーブルオーナーはRLSをバイパスする
--    バイパスを防ぐには FORCE ROW LEVEL SECURITY を使用
--
-- 3. RLS無効化（緊急時のみ）:
--    ALTER TABLE brain_learnings DISABLE ROW LEVEL SECURITY;
-- ============================================================================
