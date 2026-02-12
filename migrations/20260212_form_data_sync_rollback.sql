-- =============================================================
-- ロールバック: フォーム回答データ同期用テーブル
-- 20260212_form_data_sync.sql の逆操作
-- =============================================================

DROP TABLE IF EXISTS form_employee_contact_prefs CASCADE;
DROP TABLE IF EXISTS form_employee_work_prefs CASCADE;
DROP TABLE IF EXISTS form_employee_skills CASCADE;
DROP TABLE IF EXISTS supabase_employee_mapping CASCADE;
