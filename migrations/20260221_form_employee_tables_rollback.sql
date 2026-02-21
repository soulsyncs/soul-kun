-- =============================================================================
-- Phase 2-A ロールバック: form_employee テーブル削除
-- =============================================================================
-- 注意: データが入った状態でのロールバックは不可逆です。
--       実行前に必ずバックアップを確認してください。
-- =============================================================================

DROP TABLE IF EXISTS form_employee_contact_prefs CASCADE;
DROP TABLE IF EXISTS form_employee_work_prefs CASCADE;
DROP TABLE IF EXISTS form_employee_skills CASCADE;
DROP TABLE IF EXISTS supabase_employee_mapping CASCADE;
