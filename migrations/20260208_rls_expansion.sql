-- ============================================================================
-- RLS拡大マイグレーション: organization_idを持つ全テーブルにRLS有効化
--
-- 目的: CLAUDE.md 鉄則#2「RLSを段階的に実装」
-- 対象: 20260202_brain_tables_rls.sql で未対応のテーブル全て
--
-- 注意: 全テーブルに対し防御的に IF EXISTS チェックを行い、
--       テーブルやカラムが存在しない場合はスキップする。
--       既にRLSが有効なテーブルは DROP POLICY IF EXISTS で冪等に処理。
--
-- ロールバック: 20260208_rls_expansion_rollback.sql
--
-- 作成日: 2026-02-08
-- ============================================================================

BEGIN;

-- ============================================================================
-- ヘルパー: テーブルとorganization_idカラムが存在する場合のみRLSを有効化
--
-- Type Cast パターン（3種類）:
--   1. ::uuid  → organization_id が UUID 型のテーブル（47テーブル）
--                 daily_activity_logs: DB直接作成テーブル、UUID型と推定（要本番確認）
--   2. ::text  → organization_id が TEXT/VARCHAR 型のテーブル（12テーブル）
--                 chatwork_tasks: TEXT型 (docs/SECURITY_AUDIT_ORGANIZATION_ID.md)
--                 Phase 2I (4): organization_vocabulary等 - VARCHAR(255)
--                 Phase 2J (4): judgment_history等 - VARCHAR(255)
--                 Phase X  (3): scheduled_announcements等 - VARCHAR(100)
--   3. なし   → 該当なし（全59テーブルに明示キャストを付与済み）
--
-- current_setting() は常に text を返すため、カラム型に合わせたキャストが必須。
-- UUID カラムに対してキャストなしで比較すると暗黙キャストに依存し、
-- 型不一致エラーや予期しないアクセス許可のリスクがある。
-- ============================================================================

-- ============================================================================
-- Phase 2A: パターン検出
-- ============================================================================

-- question_patterns
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'question_patterns' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE question_patterns ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS question_patterns_org_isolation ON question_patterns;
        CREATE POLICY question_patterns_org_isolation ON question_patterns
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- personalization_risks
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'personalization_risks' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE personalization_risks ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS personalization_risks_org_isolation ON personalization_risks;
        CREATE POLICY personalization_risks_org_isolation ON personalization_risks
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- response_logs
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'response_logs' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE response_logs ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS response_logs_org_isolation ON response_logs;
        CREATE POLICY response_logs_org_isolation ON response_logs
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- bottleneck_alerts
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'bottleneck_alerts' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE bottleneck_alerts ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS bottleneck_alerts_org_isolation ON bottleneck_alerts;
        CREATE POLICY bottleneck_alerts_org_isolation ON bottleneck_alerts
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- emotion_scores
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'emotion_scores' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE emotion_scores ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS emotion_scores_org_isolation ON emotion_scores;
        CREATE POLICY emotion_scores_org_isolation ON emotion_scores
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- emotion_alerts
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'emotion_alerts' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE emotion_alerts ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS emotion_alerts_org_isolation ON emotion_alerts;
        CREATE POLICY emotion_alerts_org_isolation ON emotion_alerts
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- ============================================================================
-- Phase 2B: メモリフレームワーク
-- ============================================================================

-- conversation_summaries
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'conversation_summaries' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE conversation_summaries ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS conversation_summaries_org_isolation ON conversation_summaries;
        CREATE POLICY conversation_summaries_org_isolation ON conversation_summaries
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- user_preferences
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'user_preferences' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE user_preferences ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS user_preferences_org_isolation ON user_preferences;
        CREATE POLICY user_preferences_org_isolation ON user_preferences
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- organization_auto_knowledge
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'organization_auto_knowledge' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE organization_auto_knowledge ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS organization_auto_knowledge_org_isolation ON organization_auto_knowledge;
        CREATE POLICY organization_auto_knowledge_org_isolation ON organization_auto_knowledge
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- conversation_index
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'conversation_index' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE conversation_index ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS conversation_index_org_isolation ON conversation_index;
        CREATE POLICY conversation_index_org_isolation ON conversation_index
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- ============================================================================
-- Phase 2D: CEOラーニング
-- ============================================================================

-- ceo_teachings
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'ceo_teachings' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE ceo_teachings ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS ceo_teachings_org_isolation ON ceo_teachings;
        CREATE POLICY ceo_teachings_org_isolation ON ceo_teachings
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- ceo_teaching_conflicts
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'ceo_teaching_conflicts' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE ceo_teaching_conflicts ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS ceo_teaching_conflicts_org_isolation ON ceo_teaching_conflicts;
        CREATE POLICY ceo_teaching_conflicts_org_isolation ON ceo_teaching_conflicts
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- guardian_alerts
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'guardian_alerts' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE guardian_alerts ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS guardian_alerts_org_isolation ON guardian_alerts;
        CREATE POLICY guardian_alerts_org_isolation ON guardian_alerts
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- teaching_usage_logs
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'teaching_usage_logs' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE teaching_usage_logs ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS teaching_usage_logs_org_isolation ON teaching_usage_logs;
        CREATE POLICY teaching_usage_logs_org_isolation ON teaching_usage_logs
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- ============================================================================
-- Phase 2I: Deep Understanding
-- 注意: これらのテーブルはorganization_idがVARCHAR(255)型 → ::text キャスト使用
-- ============================================================================

-- organization_vocabulary (VARCHAR(255))
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'organization_vocabulary' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE organization_vocabulary ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS organization_vocabulary_org_isolation ON organization_vocabulary;
        CREATE POLICY organization_vocabulary_org_isolation ON organization_vocabulary
            USING (organization_id = current_setting('app.current_organization_id', true)::text)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::text);
    END IF;
END $$;

-- deep_understanding_logs (VARCHAR(255))
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'deep_understanding_logs' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE deep_understanding_logs ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS deep_understanding_logs_org_isolation ON deep_understanding_logs;
        CREATE POLICY deep_understanding_logs_org_isolation ON deep_understanding_logs
            USING (organization_id = current_setting('app.current_organization_id', true)::text)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::text);
    END IF;
END $$;

-- intent_resolution_feedback (VARCHAR(255))
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'intent_resolution_feedback' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE intent_resolution_feedback ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS intent_resolution_feedback_org_isolation ON intent_resolution_feedback;
        CREATE POLICY intent_resolution_feedback_org_isolation ON intent_resolution_feedback
            USING (organization_id = current_setting('app.current_organization_id', true)::text)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::text);
    END IF;
END $$;

-- emotion_patterns (VARCHAR(255))
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'emotion_patterns' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE emotion_patterns ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS emotion_patterns_org_isolation ON emotion_patterns;
        CREATE POLICY emotion_patterns_org_isolation ON emotion_patterns
            USING (organization_id = current_setting('app.current_organization_id', true)::text)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::text);
    END IF;
END $$;

-- ============================================================================
-- Phase 2J: Advanced Judgment
-- 注意: これらのテーブルはorganization_idがVARCHAR(255)型 → ::text キャスト使用
-- ============================================================================

-- judgment_history (VARCHAR(255))
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'judgment_history' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE judgment_history ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS judgment_history_org_isolation ON judgment_history;
        CREATE POLICY judgment_history_org_isolation ON judgment_history
            USING (organization_id = current_setting('app.current_organization_id', true)::text)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::text);
    END IF;
END $$;

-- evaluation_criteria_templates (VARCHAR(255))
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'evaluation_criteria_templates' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE evaluation_criteria_templates ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS evaluation_criteria_templates_org_isolation ON evaluation_criteria_templates;
        CREATE POLICY evaluation_criteria_templates_org_isolation ON evaluation_criteria_templates
            USING (organization_id = current_setting('app.current_organization_id', true)::text)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::text);
    END IF;
END $$;

-- judgment_patterns (VARCHAR(255))
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'judgment_patterns' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE judgment_patterns ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS judgment_patterns_org_isolation ON judgment_patterns;
        CREATE POLICY judgment_patterns_org_isolation ON judgment_patterns
            USING (organization_id = current_setting('app.current_organization_id', true)::text)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::text);
    END IF;
END $$;

-- judgment_feedback (VARCHAR(255))
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'judgment_feedback' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE judgment_feedback ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS judgment_feedback_org_isolation ON judgment_feedback;
        CREATE POLICY judgment_feedback_org_isolation ON judgment_feedback
            USING (organization_id = current_setting('app.current_organization_id', true)::text)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::text);
    END IF;
END $$;

-- ============================================================================
-- Phase 2K: Proactive
-- ============================================================================

-- proactive_action_logs
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'proactive_action_logs' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE proactive_action_logs ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS proactive_action_logs_org_isolation ON proactive_action_logs;
        CREATE POLICY proactive_action_logs_org_isolation ON proactive_action_logs
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- proactive_cooldowns
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'proactive_cooldowns' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE proactive_cooldowns ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS proactive_cooldowns_org_isolation ON proactive_cooldowns;
        CREATE POLICY proactive_cooldowns_org_isolation ON proactive_cooldowns
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- proactive_settings
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'proactive_settings' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE proactive_settings ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS proactive_settings_org_isolation ON proactive_settings;
        CREATE POLICY proactive_settings_org_isolation ON proactive_settings
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- ============================================================================
-- Phase 2L: Execution Excellence
-- ============================================================================

-- execution_plans
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'execution_plans' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE execution_plans ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS execution_plans_org_isolation ON execution_plans;
        CREATE POLICY execution_plans_org_isolation ON execution_plans
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- execution_subtasks
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'execution_subtasks' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE execution_subtasks ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS execution_subtasks_org_isolation ON execution_subtasks;
        CREATE POLICY execution_subtasks_org_isolation ON execution_subtasks
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- execution_escalations
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'execution_escalations' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE execution_escalations ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS execution_escalations_org_isolation ON execution_escalations;
        CREATE POLICY execution_escalations_org_isolation ON execution_escalations
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- execution_quality_reports
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'execution_quality_reports' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE execution_quality_reports ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS execution_quality_reports_org_isolation ON execution_quality_reports;
        CREATE POLICY execution_quality_reports_org_isolation ON execution_quality_reports
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- ============================================================================
-- Phase 2-5: Goal Setting
-- ============================================================================

-- goal_setting_sessions
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'goal_setting_sessions' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE goal_setting_sessions ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS goal_setting_sessions_org_isolation ON goal_setting_sessions;
        CREATE POLICY goal_setting_sessions_org_isolation ON goal_setting_sessions
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- goal_setting_logs
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'goal_setting_logs' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE goal_setting_logs ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS goal_setting_logs_org_isolation ON goal_setting_logs;
        CREATE POLICY goal_setting_logs_org_isolation ON goal_setting_logs
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- goal_setting_user_patterns
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'goal_setting_user_patterns' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE goal_setting_user_patterns ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS goal_setting_user_patterns_org_isolation ON goal_setting_user_patterns;
        CREATE POLICY goal_setting_user_patterns_org_isolation ON goal_setting_user_patterns
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- ============================================================================
-- Phase 0: Model Orchestrator
-- ============================================================================

-- ai_usage_logs
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'ai_usage_logs' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE ai_usage_logs ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS ai_usage_logs_org_isolation ON ai_usage_logs;
        CREATE POLICY ai_usage_logs_org_isolation ON ai_usage_logs
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- ai_organization_settings
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'ai_organization_settings' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE ai_organization_settings ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS ai_organization_settings_org_isolation ON ai_organization_settings;
        CREATE POLICY ai_organization_settings_org_isolation ON ai_organization_settings
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- ai_monthly_cost_summary
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'ai_monthly_cost_summary' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE ai_monthly_cost_summary ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS ai_monthly_cost_summary_org_isolation ON ai_monthly_cost_summary;
        CREATE POLICY ai_monthly_cost_summary_org_isolation ON ai_monthly_cost_summary
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- ============================================================================
-- Phase 3: Knowledge Management
-- ============================================================================

-- documents
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'documents' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS documents_org_isolation ON documents;
        CREATE POLICY documents_org_isolation ON documents
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- document_chunks
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'document_chunks' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS document_chunks_org_isolation ON document_chunks;
        CREATE POLICY document_chunks_org_isolation ON document_chunks
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- knowledge_search_logs
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'knowledge_search_logs' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE knowledge_search_logs ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS knowledge_search_logs_org_isolation ON knowledge_search_logs;
        CREATE POLICY knowledge_search_logs_org_isolation ON knowledge_search_logs
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- knowledge_feedback
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'knowledge_feedback' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE knowledge_feedback ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS knowledge_feedback_org_isolation ON knowledge_feedback;
        CREATE POLICY knowledge_feedback_org_isolation ON knowledge_feedback
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- google_drive_sync_logs
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'google_drive_sync_logs' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE google_drive_sync_logs ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS google_drive_sync_logs_org_isolation ON google_drive_sync_logs;
        CREATE POLICY google_drive_sync_logs_org_isolation ON google_drive_sync_logs
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- google_drive_sync_state
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'google_drive_sync_state' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE google_drive_sync_state ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS google_drive_sync_state_org_isolation ON google_drive_sync_state;
        CREATE POLICY google_drive_sync_state_org_isolation ON google_drive_sync_state
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- ============================================================================
-- Phase 3.5: Organization Hierarchy
-- ============================================================================

-- departments
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'departments' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE departments ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS departments_org_isolation ON departments;
        CREATE POLICY departments_org_isolation ON departments
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- users
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE users ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS users_org_isolation ON users;
        CREATE POLICY users_org_isolation ON users
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- ============================================================================
-- Phase X: Announcements
-- 注意: これらのテーブルはorganization_idがVARCHAR(100)型
--       DEFAULT 'org_soulsyncs' のため ::uuid キャストは不可 → ::text 使用
-- ============================================================================

-- scheduled_announcements (VARCHAR(100))
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'scheduled_announcements' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE scheduled_announcements ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS scheduled_announcements_org_isolation ON scheduled_announcements;
        CREATE POLICY scheduled_announcements_org_isolation ON scheduled_announcements
            USING (organization_id = current_setting('app.current_organization_id', true)::text)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::text);
    END IF;
END $$;

-- announcement_logs (VARCHAR(100))
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'announcement_logs' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE announcement_logs ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS announcement_logs_org_isolation ON announcement_logs;
        CREATE POLICY announcement_logs_org_isolation ON announcement_logs
            USING (organization_id = current_setting('app.current_organization_id', true)::text)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::text);
    END IF;
END $$;

-- announcement_patterns (VARCHAR(100))
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'announcement_patterns' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE announcement_patterns ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS announcement_patterns_org_isolation ON announcement_patterns;
        CREATE POLICY announcement_patterns_org_isolation ON announcement_patterns
            USING (organization_id = current_setting('app.current_organization_id', true)::text)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::text);
    END IF;
END $$;

-- ============================================================================
-- Phase F1: CEO Feedback
-- ============================================================================

-- feedback_deliveries
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'feedback_deliveries' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE feedback_deliveries ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS feedback_deliveries_org_isolation ON feedback_deliveries;
        CREATE POLICY feedback_deliveries_org_isolation ON feedback_deliveries
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- feedback_settings
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'feedback_settings' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE feedback_settings ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS feedback_settings_org_isolation ON feedback_settings;
        CREATE POLICY feedback_settings_org_isolation ON feedback_settings
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- feedback_alert_cooldowns
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'feedback_alert_cooldowns' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE feedback_alert_cooldowns ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS feedback_alert_cooldowns_org_isolation ON feedback_alert_cooldowns;
        CREATE POLICY feedback_alert_cooldowns_org_isolation ON feedback_alert_cooldowns
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- ============================================================================
-- Phase A: Admin Config
-- ============================================================================

-- organization_admin_configs
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'organization_admin_configs' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE organization_admin_configs ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS organization_admin_configs_org_isolation ON organization_admin_configs;
        CREATE POLICY organization_admin_configs_org_isolation ON organization_admin_configs
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- ============================================================================
-- Memory: Bot Persona / User Long Term Memory
-- ============================================================================

-- bot_persona_memory
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'bot_persona_memory' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE bot_persona_memory ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS bot_persona_memory_org_isolation ON bot_persona_memory;
        CREATE POLICY bot_persona_memory_org_isolation ON bot_persona_memory
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- user_long_term_memory
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'user_long_term_memory' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE user_long_term_memory ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS user_long_term_memory_org_isolation ON user_long_term_memory;
        CREATE POLICY user_long_term_memory_org_isolation ON user_long_term_memory
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- ============================================================================
-- Phase M1: Multimodal
-- ============================================================================

-- multimodal_processing_logs
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'multimodal_processing_logs' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE multimodal_processing_logs ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS multimodal_processing_logs_org_isolation ON multimodal_processing_logs;
        CREATE POLICY multimodal_processing_logs_org_isolation ON multimodal_processing_logs
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- multimodal_extracted_entities
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'multimodal_extracted_entities' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE multimodal_extracted_entities ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS multimodal_extracted_entities_org_isolation ON multimodal_extracted_entities;
        CREATE POLICY multimodal_extracted_entities_org_isolation ON multimodal_extracted_entities
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- ============================================================================
-- Other: Notification / Insights / Chatwork Tasks
-- ============================================================================

-- notification_logs
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'notification_logs' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE notification_logs ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS notification_logs_org_isolation ON notification_logs;
        CREATE POLICY notification_logs_org_isolation ON notification_logs
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- soulkun_insights
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'soulkun_insights' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE soulkun_insights ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS soulkun_insights_org_isolation ON soulkun_insights;
        CREATE POLICY soulkun_insights_org_isolation ON soulkun_insights
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- soulkun_weekly_reports
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'soulkun_weekly_reports' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE soulkun_weekly_reports ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS soulkun_weekly_reports_org_isolation ON soulkun_weekly_reports;
        CREATE POLICY soulkun_weekly_reports_org_isolation ON soulkun_weekly_reports
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

-- chatwork_tasks (organization_id は TEXT 型 — docs/SECURITY_AUDIT_ORGANIZATION_ID.md 参照)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'chatwork_tasks' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE chatwork_tasks ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS chatwork_tasks_org_isolation ON chatwork_tasks;
        CREATE POLICY chatwork_tasks_org_isolation ON chatwork_tasks
            USING (organization_id = current_setting('app.current_organization_id', true)::text)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::text);
    END IF;
END $$;

-- daily_activity_logs (organization_id は UUID 型と推定 — DB直接作成テーブル)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'daily_activity_logs' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE daily_activity_logs ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS daily_activity_logs_org_isolation ON daily_activity_logs;
        CREATE POLICY daily_activity_logs_org_isolation ON daily_activity_logs
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END $$;

COMMIT;

-- ============================================================================
-- 検証クエリ（実行後の確認用）
-- ============================================================================
--
-- 1. RLSが有効なテーブル一覧:
--    SELECT schemaname, tablename, rowsecurity
--    FROM pg_tables
--    WHERE schemaname = 'public' AND rowsecurity = true
--    ORDER BY tablename;
--
-- 2. ポリシー一覧:
--    SELECT tablename, policyname
--    FROM pg_policies
--    WHERE schemaname = 'public'
--    ORDER BY tablename;
--
-- 3. RLS未設定のテナントテーブル検出:
--    SELECT t.tablename
--    FROM pg_tables t
--    JOIN information_schema.columns c
--      ON c.table_name = t.tablename AND c.column_name = 'organization_id'
--    WHERE t.schemaname = 'public' AND t.rowsecurity = false;
--
-- ============================================================================
