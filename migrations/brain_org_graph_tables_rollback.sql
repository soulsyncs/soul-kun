-- ============================================================================
-- Brain Organization Graph Tables — ROLLBACK
-- ============================================================================
-- brain_org_graph_tables.sql の巻き戻し用
-- ============================================================================

BEGIN;

-- 依存関係の順序で削除（子テーブル→親テーブル）
DROP TABLE IF EXISTS brain_interactions CASCADE;
DROP TABLE IF EXISTS brain_relationships CASCADE;
DROP TABLE IF EXISTS brain_person_nodes CASCADE;

COMMIT;
