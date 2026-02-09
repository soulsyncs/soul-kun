-- Phase 2M: 対人力強化（Interpersonal Skills）ロールバック
-- 作成日: 2026-02-09
-- 注意: このスクリプトはPhase 2Mのテーブルを完全に削除します

BEGIN;

-- RLSポリシー削除
DROP POLICY IF EXISTS rls_conflict_logs_org ON brain_conflict_logs;
DROP POLICY IF EXISTS rls_feedback_opp_org ON brain_feedback_opportunities;
DROP POLICY IF EXISTS rls_motivation_profiles_org ON brain_motivation_profiles;
DROP POLICY IF EXISTS rls_comm_profiles_org ON brain_communication_profiles;

-- テーブル削除（依存関係の逆順）
DROP TABLE IF EXISTS brain_conflict_logs;
DROP TABLE IF EXISTS brain_feedback_opportunities;
DROP TABLE IF EXISTS brain_motivation_profiles;
DROP TABLE IF EXISTS brain_communication_profiles;

COMMIT;
