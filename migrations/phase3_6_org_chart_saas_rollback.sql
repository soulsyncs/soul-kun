-- ============================================================================
-- Phase 3.6: Organization Chart SaaS Tables — ROLLBACK
-- ============================================================================

BEGIN;

DROP TABLE IF EXISTS org_chart_audit_logs CASCADE;
DROP TABLE IF EXISTS org_chart_subscriptions CASCADE;
DROP TABLE IF EXISTS org_chart_users CASCADE;
DROP TABLE IF EXISTS org_chart_tenants CASCADE;

COMMIT;
