-- Phase 2N: 自己最適化（Self-Optimization）ロールバック
-- 作成日: 2026-02-09
-- 注意: このスクリプトはPhase 2Nのテーブルを完全に削除します

BEGIN;

-- RLSポリシー削除
DROP POLICY IF EXISTS rls_deploy_logs_org ON brain_deployment_logs;
DROP POLICY IF EXISTS rls_ab_tests_org ON brain_ab_tests;
DROP POLICY IF EXISTS rls_proposals_org ON brain_improvement_proposals;
DROP POLICY IF EXISTS rls_perf_metrics_org ON brain_performance_metrics;

-- テーブル削除（依存関係の逆順）
DROP TABLE IF EXISTS brain_deployment_logs;
DROP TABLE IF EXISTS brain_ab_tests;
DROP TABLE IF EXISTS brain_improvement_proposals;
DROP TABLE IF EXISTS brain_performance_metrics;

COMMIT;
