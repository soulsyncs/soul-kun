-- ============================================================================
-- RLS拡大ロールバック: 20260208_rls_expansion.sql の逆操作
--
-- 目的: 全48テーブルのRLSポリシー削除 + RLS無効化
-- 対象: 20260208_rls_expansion.sql で有効化した全テーブル
--
-- 注意: 全テーブルに対し防御的に IF EXISTS チェックを行い、
--       テーブルが存在しない場合はスキップする。
--       DROP POLICY IF EXISTS で冪等に処理。
--
-- 順方向: 20260208_rls_expansion.sql
--
-- 作成日: 2026-02-08
-- ============================================================================

BEGIN;

-- ============================================================================
-- Phase 2A: パターン検出
-- ============================================================================

-- question_patterns
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'question_patterns'
    ) THEN
        DROP POLICY IF EXISTS question_patterns_org_isolation ON question_patterns;
        ALTER TABLE question_patterns DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- personalization_risks
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'personalization_risks'
    ) THEN
        DROP POLICY IF EXISTS personalization_risks_org_isolation ON personalization_risks;
        ALTER TABLE personalization_risks DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- response_logs
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'response_logs'
    ) THEN
        DROP POLICY IF EXISTS response_logs_org_isolation ON response_logs;
        ALTER TABLE response_logs DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- bottleneck_alerts
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'bottleneck_alerts'
    ) THEN
        DROP POLICY IF EXISTS bottleneck_alerts_org_isolation ON bottleneck_alerts;
        ALTER TABLE bottleneck_alerts DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- emotion_scores
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'emotion_scores'
    ) THEN
        DROP POLICY IF EXISTS emotion_scores_org_isolation ON emotion_scores;
        ALTER TABLE emotion_scores DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- emotion_alerts
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'emotion_alerts'
    ) THEN
        DROP POLICY IF EXISTS emotion_alerts_org_isolation ON emotion_alerts;
        ALTER TABLE emotion_alerts DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- ============================================================================
-- Phase 2B: メモリフレームワーク
-- ============================================================================

-- conversation_summaries
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'conversation_summaries'
    ) THEN
        DROP POLICY IF EXISTS conversation_summaries_org_isolation ON conversation_summaries;
        ALTER TABLE conversation_summaries DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- user_preferences
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'user_preferences'
    ) THEN
        DROP POLICY IF EXISTS user_preferences_org_isolation ON user_preferences;
        ALTER TABLE user_preferences DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- organization_auto_knowledge
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'organization_auto_knowledge'
    ) THEN
        DROP POLICY IF EXISTS organization_auto_knowledge_org_isolation ON organization_auto_knowledge;
        ALTER TABLE organization_auto_knowledge DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- conversation_index
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'conversation_index'
    ) THEN
        DROP POLICY IF EXISTS conversation_index_org_isolation ON conversation_index;
        ALTER TABLE conversation_index DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- ============================================================================
-- Phase 2D: CEOラーニング
-- ============================================================================

-- ceo_teachings
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'ceo_teachings'
    ) THEN
        DROP POLICY IF EXISTS ceo_teachings_org_isolation ON ceo_teachings;
        ALTER TABLE ceo_teachings DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- ceo_teaching_conflicts
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'ceo_teaching_conflicts'
    ) THEN
        DROP POLICY IF EXISTS ceo_teaching_conflicts_org_isolation ON ceo_teaching_conflicts;
        ALTER TABLE ceo_teaching_conflicts DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- guardian_alerts
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'guardian_alerts'
    ) THEN
        DROP POLICY IF EXISTS guardian_alerts_org_isolation ON guardian_alerts;
        ALTER TABLE guardian_alerts DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- teaching_usage_logs
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'teaching_usage_logs'
    ) THEN
        DROP POLICY IF EXISTS teaching_usage_logs_org_isolation ON teaching_usage_logs;
        ALTER TABLE teaching_usage_logs DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- ============================================================================
-- Phase 2I: Deep Understanding
-- ============================================================================

-- organization_vocabulary
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'organization_vocabulary'
    ) THEN
        DROP POLICY IF EXISTS organization_vocabulary_org_isolation ON organization_vocabulary;
        ALTER TABLE organization_vocabulary DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- deep_understanding_logs
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'deep_understanding_logs'
    ) THEN
        DROP POLICY IF EXISTS deep_understanding_logs_org_isolation ON deep_understanding_logs;
        ALTER TABLE deep_understanding_logs DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- intent_resolution_feedback
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'intent_resolution_feedback'
    ) THEN
        DROP POLICY IF EXISTS intent_resolution_feedback_org_isolation ON intent_resolution_feedback;
        ALTER TABLE intent_resolution_feedback DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- emotion_patterns
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'emotion_patterns'
    ) THEN
        DROP POLICY IF EXISTS emotion_patterns_org_isolation ON emotion_patterns;
        ALTER TABLE emotion_patterns DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- ============================================================================
-- Phase 2J: Advanced Judgment
-- ============================================================================

-- judgment_history
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'judgment_history'
    ) THEN
        DROP POLICY IF EXISTS judgment_history_org_isolation ON judgment_history;
        ALTER TABLE judgment_history DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- evaluation_criteria_templates
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'evaluation_criteria_templates'
    ) THEN
        DROP POLICY IF EXISTS evaluation_criteria_templates_org_isolation ON evaluation_criteria_templates;
        ALTER TABLE evaluation_criteria_templates DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- judgment_patterns
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'judgment_patterns'
    ) THEN
        DROP POLICY IF EXISTS judgment_patterns_org_isolation ON judgment_patterns;
        ALTER TABLE judgment_patterns DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- judgment_feedback
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'judgment_feedback'
    ) THEN
        DROP POLICY IF EXISTS judgment_feedback_org_isolation ON judgment_feedback;
        ALTER TABLE judgment_feedback DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- ============================================================================
-- Phase 2K: Proactive
-- ============================================================================

-- proactive_action_logs
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'proactive_action_logs'
    ) THEN
        DROP POLICY IF EXISTS proactive_action_logs_org_isolation ON proactive_action_logs;
        ALTER TABLE proactive_action_logs DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- proactive_cooldowns
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'proactive_cooldowns'
    ) THEN
        DROP POLICY IF EXISTS proactive_cooldowns_org_isolation ON proactive_cooldowns;
        ALTER TABLE proactive_cooldowns DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- proactive_settings
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'proactive_settings'
    ) THEN
        DROP POLICY IF EXISTS proactive_settings_org_isolation ON proactive_settings;
        ALTER TABLE proactive_settings DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- ============================================================================
-- Phase 2L: Execution Excellence
-- ============================================================================

-- execution_plans
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'execution_plans'
    ) THEN
        DROP POLICY IF EXISTS execution_plans_org_isolation ON execution_plans;
        ALTER TABLE execution_plans DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- execution_subtasks
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'execution_subtasks'
    ) THEN
        DROP POLICY IF EXISTS execution_subtasks_org_isolation ON execution_subtasks;
        ALTER TABLE execution_subtasks DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- execution_escalations
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'execution_escalations'
    ) THEN
        DROP POLICY IF EXISTS execution_escalations_org_isolation ON execution_escalations;
        ALTER TABLE execution_escalations DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- execution_quality_reports
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'execution_quality_reports'
    ) THEN
        DROP POLICY IF EXISTS execution_quality_reports_org_isolation ON execution_quality_reports;
        ALTER TABLE execution_quality_reports DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- ============================================================================
-- Phase 2-5: Goal Setting
-- ============================================================================

-- goal_setting_sessions
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'goal_setting_sessions'
    ) THEN
        DROP POLICY IF EXISTS goal_setting_sessions_org_isolation ON goal_setting_sessions;
        ALTER TABLE goal_setting_sessions DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- goal_setting_logs
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'goal_setting_logs'
    ) THEN
        DROP POLICY IF EXISTS goal_setting_logs_org_isolation ON goal_setting_logs;
        ALTER TABLE goal_setting_logs DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- goal_setting_user_patterns
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'goal_setting_user_patterns'
    ) THEN
        DROP POLICY IF EXISTS goal_setting_user_patterns_org_isolation ON goal_setting_user_patterns;
        ALTER TABLE goal_setting_user_patterns DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- ============================================================================
-- Phase 0: Model Orchestrator
-- ============================================================================

-- ai_usage_logs
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'ai_usage_logs'
    ) THEN
        DROP POLICY IF EXISTS ai_usage_logs_org_isolation ON ai_usage_logs;
        ALTER TABLE ai_usage_logs DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- ai_organization_settings
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'ai_organization_settings'
    ) THEN
        DROP POLICY IF EXISTS ai_organization_settings_org_isolation ON ai_organization_settings;
        ALTER TABLE ai_organization_settings DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- ai_monthly_cost_summary
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'ai_monthly_cost_summary'
    ) THEN
        DROP POLICY IF EXISTS ai_monthly_cost_summary_org_isolation ON ai_monthly_cost_summary;
        ALTER TABLE ai_monthly_cost_summary DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- ============================================================================
-- Phase 3: Knowledge Management
-- ============================================================================

-- documents
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'documents'
    ) THEN
        DROP POLICY IF EXISTS documents_org_isolation ON documents;
        ALTER TABLE documents DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- document_chunks
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'document_chunks'
    ) THEN
        DROP POLICY IF EXISTS document_chunks_org_isolation ON document_chunks;
        ALTER TABLE document_chunks DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- knowledge_search_logs
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'knowledge_search_logs'
    ) THEN
        DROP POLICY IF EXISTS knowledge_search_logs_org_isolation ON knowledge_search_logs;
        ALTER TABLE knowledge_search_logs DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- knowledge_feedback
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'knowledge_feedback'
    ) THEN
        DROP POLICY IF EXISTS knowledge_feedback_org_isolation ON knowledge_feedback;
        ALTER TABLE knowledge_feedback DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- google_drive_sync_logs
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'google_drive_sync_logs'
    ) THEN
        DROP POLICY IF EXISTS google_drive_sync_logs_org_isolation ON google_drive_sync_logs;
        ALTER TABLE google_drive_sync_logs DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- google_drive_sync_state
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'google_drive_sync_state'
    ) THEN
        DROP POLICY IF EXISTS google_drive_sync_state_org_isolation ON google_drive_sync_state;
        ALTER TABLE google_drive_sync_state DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- ============================================================================
-- Phase 3.5: Organization Hierarchy
-- ============================================================================

-- departments
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'departments'
    ) THEN
        DROP POLICY IF EXISTS departments_org_isolation ON departments;
        ALTER TABLE departments DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- users
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'users'
    ) THEN
        DROP POLICY IF EXISTS users_org_isolation ON users;
        ALTER TABLE users DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- ============================================================================
-- Phase X: Announcements
-- ============================================================================

-- scheduled_announcements
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'scheduled_announcements'
    ) THEN
        DROP POLICY IF EXISTS scheduled_announcements_org_isolation ON scheduled_announcements;
        ALTER TABLE scheduled_announcements DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- announcement_logs
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'announcement_logs'
    ) THEN
        DROP POLICY IF EXISTS announcement_logs_org_isolation ON announcement_logs;
        ALTER TABLE announcement_logs DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- announcement_patterns
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'announcement_patterns'
    ) THEN
        DROP POLICY IF EXISTS announcement_patterns_org_isolation ON announcement_patterns;
        ALTER TABLE announcement_patterns DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- ============================================================================
-- Phase F1: CEO Feedback
-- ============================================================================

-- feedback_deliveries
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'feedback_deliveries'
    ) THEN
        DROP POLICY IF EXISTS feedback_deliveries_org_isolation ON feedback_deliveries;
        ALTER TABLE feedback_deliveries DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- feedback_settings
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'feedback_settings'
    ) THEN
        DROP POLICY IF EXISTS feedback_settings_org_isolation ON feedback_settings;
        ALTER TABLE feedback_settings DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- feedback_alert_cooldowns
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'feedback_alert_cooldowns'
    ) THEN
        DROP POLICY IF EXISTS feedback_alert_cooldowns_org_isolation ON feedback_alert_cooldowns;
        ALTER TABLE feedback_alert_cooldowns DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- ============================================================================
-- Phase A: Admin Config
-- ============================================================================

-- organization_admin_configs
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'organization_admin_configs'
    ) THEN
        DROP POLICY IF EXISTS organization_admin_configs_org_isolation ON organization_admin_configs;
        ALTER TABLE organization_admin_configs DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- ============================================================================
-- Memory: Bot Persona / User Long Term Memory
-- ============================================================================

-- bot_persona_memory
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'bot_persona_memory'
    ) THEN
        DROP POLICY IF EXISTS bot_persona_memory_org_isolation ON bot_persona_memory;
        ALTER TABLE bot_persona_memory DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- user_long_term_memory
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'user_long_term_memory'
    ) THEN
        DROP POLICY IF EXISTS user_long_term_memory_org_isolation ON user_long_term_memory;
        ALTER TABLE user_long_term_memory DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- ============================================================================
-- Phase M1: Multimodal
-- ============================================================================

-- multimodal_processing_logs
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'multimodal_processing_logs'
    ) THEN
        DROP POLICY IF EXISTS multimodal_processing_logs_org_isolation ON multimodal_processing_logs;
        ALTER TABLE multimodal_processing_logs DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- multimodal_extracted_entities
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'multimodal_extracted_entities'
    ) THEN
        DROP POLICY IF EXISTS multimodal_extracted_entities_org_isolation ON multimodal_extracted_entities;
        ALTER TABLE multimodal_extracted_entities DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- ============================================================================
-- Other: Notification / Insights / Chatwork Tasks / Daily Activity
-- ============================================================================

-- notification_logs
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'notification_logs'
    ) THEN
        DROP POLICY IF EXISTS notification_logs_org_isolation ON notification_logs;
        ALTER TABLE notification_logs DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- soulkun_insights
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'soulkun_insights'
    ) THEN
        DROP POLICY IF EXISTS soulkun_insights_org_isolation ON soulkun_insights;
        ALTER TABLE soulkun_insights DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- soulkun_weekly_reports
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'soulkun_weekly_reports'
    ) THEN
        DROP POLICY IF EXISTS soulkun_weekly_reports_org_isolation ON soulkun_weekly_reports;
        ALTER TABLE soulkun_weekly_reports DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- chatwork_tasks
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'chatwork_tasks'
    ) THEN
        DROP POLICY IF EXISTS chatwork_tasks_org_isolation ON chatwork_tasks;
        ALTER TABLE chatwork_tasks DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- daily_activity_logs
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'daily_activity_logs'
    ) THEN
        DROP POLICY IF EXISTS daily_activity_logs_org_isolation ON daily_activity_logs;
        ALTER TABLE daily_activity_logs DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

COMMIT;

-- ============================================================================
-- 検証クエリ（ロールバック後の確認用）
-- ============================================================================
--
-- 1. RLSが無効になったことを確認（このマイグレーション対象テーブル）:
--    SELECT schemaname, tablename, rowsecurity
--    FROM pg_tables
--    WHERE schemaname = 'public' AND rowsecurity = true
--    ORDER BY tablename;
--    -- 結果: 20260202_brain_tables_rls.sql の対象テーブルのみが残るはず
--
-- 2. ポリシーが削除されたことを確認:
--    SELECT tablename, policyname
--    FROM pg_policies
--    WHERE schemaname = 'public' AND policyname LIKE '%_org_isolation'
--    ORDER BY tablename;
--    -- 結果: 20260202_brain_tables_rls.sql の対象ポリシーのみが残るはず
--
-- 3. 全48テーブルのRLS状態を個別確認:
--    SELECT t.tablename, t.rowsecurity
--    FROM pg_tables t
--    WHERE t.schemaname = 'public'
--      AND t.tablename IN (
--          'question_patterns', 'personalization_risks', 'response_logs',
--          'bottleneck_alerts', 'emotion_scores', 'emotion_alerts',
--          'conversation_summaries', 'user_preferences', 'organization_auto_knowledge',
--          'conversation_index', 'ceo_teachings', 'ceo_teaching_conflicts',
--          'guardian_alerts', 'teaching_usage_logs', 'organization_vocabulary',
--          'deep_understanding_logs', 'intent_resolution_feedback', 'emotion_patterns',
--          'judgment_history', 'evaluation_criteria_templates', 'judgment_patterns',
--          'judgment_feedback', 'proactive_action_logs', 'proactive_cooldowns',
--          'proactive_settings', 'execution_plans', 'execution_subtasks',
--          'execution_escalations', 'execution_quality_reports',
--          'goal_setting_sessions', 'goal_setting_logs', 'goal_setting_user_patterns',
--          'ai_usage_logs', 'ai_organization_settings', 'ai_monthly_cost_summary',
--          'documents', 'document_chunks', 'knowledge_search_logs',
--          'knowledge_feedback', 'google_drive_sync_logs', 'google_drive_sync_state',
--          'departments', 'users', 'scheduled_announcements',
--          'announcement_logs', 'announcement_patterns',
--          'feedback_deliveries', 'feedback_settings', 'feedback_alert_cooldowns',
--          'organization_admin_configs',
--          'bot_persona_memory', 'user_long_term_memory',
--          'multimodal_processing_logs', 'multimodal_extracted_entities',
--          'notification_logs', 'soulkun_insights', 'soulkun_weekly_reports',
--          'chatwork_tasks', 'daily_activity_logs'
--      )
--    ORDER BY t.tablename;
--    -- 結果: 全て rowsecurity = false であること
--
-- ============================================================================
