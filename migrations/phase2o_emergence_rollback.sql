-- Phase 2O: 創発（Emergence）ロールバック
-- 作成日: 2026-02-09
-- 注意: このスクリプトはPhase 2Oのテーブルを完全に削除します

BEGIN;

-- RLSポリシー削除
DROP POLICY IF EXISTS rls_snapshots_org ON brain_org_snapshots;
DROP POLICY IF EXISTS rls_insights_org ON brain_strategic_insights;
DROP POLICY IF EXISTS rls_emergent_org ON brain_emergent_behaviors;
DROP POLICY IF EXISTS rls_cap_graph_org ON brain_capability_graph;

-- テーブル削除（依存関係の逆順）
DROP TABLE IF EXISTS brain_org_snapshots;
DROP TABLE IF EXISTS brain_strategic_insights;
DROP TABLE IF EXISTS brain_emergent_behaviors;
DROP TABLE IF EXISTS brain_capability_graph;

COMMIT;
