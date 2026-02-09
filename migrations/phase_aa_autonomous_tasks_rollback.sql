-- ============================================================================
-- Phase AA: Autonomous Task Tables — ROLLBACK
-- ============================================================================

BEGIN;

DROP TABLE IF EXISTS autonomous_task_steps CASCADE;
DROP TABLE IF EXISTS autonomous_tasks CASCADE;

COMMIT;
