-- =============================================================================
-- Phase 2-A RLSポリシー修正（brain-reviewer W1+W2対応）
-- =============================================================================
-- W1: organization_id::text キャスト追加（VARCHAR列はtext cast必須 §3-2 #7）
-- W2: WITH CHECK 句を追加（INSERT/UPDATE のテナント強制）
-- =============================================================================

-- supabase_employee_mapping
DROP POLICY IF EXISTS supabase_employee_mapping_org_isolation ON supabase_employee_mapping;
CREATE POLICY supabase_employee_mapping_org_isolation
    ON supabase_employee_mapping
    USING (organization_id::text = current_setting('app.current_organization_id', true))
    WITH CHECK (organization_id::text = current_setting('app.current_organization_id', true));

-- form_employee_skills
DROP POLICY IF EXISTS form_employee_skills_org_isolation ON form_employee_skills;
CREATE POLICY form_employee_skills_org_isolation
    ON form_employee_skills
    USING (organization_id::text = current_setting('app.current_organization_id', true))
    WITH CHECK (organization_id::text = current_setting('app.current_organization_id', true));

-- form_employee_work_prefs
DROP POLICY IF EXISTS form_employee_work_prefs_org_isolation ON form_employee_work_prefs;
CREATE POLICY form_employee_work_prefs_org_isolation
    ON form_employee_work_prefs
    USING (organization_id::text = current_setting('app.current_organization_id', true))
    WITH CHECK (organization_id::text = current_setting('app.current_organization_id', true));

-- form_employee_contact_prefs
DROP POLICY IF EXISTS form_employee_contact_prefs_org_isolation ON form_employee_contact_prefs;
CREATE POLICY form_employee_contact_prefs_org_isolation
    ON form_employee_contact_prefs
    USING (organization_id::text = current_setting('app.current_organization_id', true))
    WITH CHECK (organization_id::text = current_setting('app.current_organization_id', true));
