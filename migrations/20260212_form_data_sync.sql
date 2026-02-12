-- =============================================================
-- フォーム回答データ同期用テーブル（Cloud SQL側）
-- Supabase → Cloud SQL 非金融データのみ同期
-- 3AI合議に基づく設計（2026-02-12）
-- =============================================================

-- =============================================================
-- 1. Supabase ↔ Cloud SQL 社員IDマッピング
-- =============================================================
CREATE TABLE IF NOT EXISTS supabase_employee_mapping (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id VARCHAR NOT NULL,
    supabase_employee_id UUID NOT NULL,
    cloudsql_employee_id UUID NOT NULL REFERENCES employees(id),
    employee_name VARCHAR NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_supabase_mapping UNIQUE (supabase_employee_id, organization_id)
);

CREATE INDEX IF NOT EXISTS idx_supabase_mapping_org
    ON supabase_employee_mapping(organization_id);
CREATE INDEX IF NOT EXISTS idx_supabase_mapping_cloudsql
    ON supabase_employee_mapping(cloudsql_employee_id);

-- =============================================================
-- 2. スキル自己評価（非金融）
-- =============================================================
CREATE TABLE IF NOT EXISTS form_employee_skills (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id VARCHAR NOT NULL,
    employee_id UUID NOT NULL REFERENCES employees(id),
    skill_levels JSONB DEFAULT '{}'::jsonb,
    top_skills JSONB DEFAULT '[]'::jsonb,
    weak_skills JSONB DEFAULT '[]'::jsonb,
    preferred_tasks JSONB DEFAULT '[]'::jsonb,
    avoided_tasks JSONB DEFAULT '[]'::jsonb,
    source VARCHAR DEFAULT 'supabase_sync',
    supabase_updated_at TIMESTAMPTZ,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_form_skills_employee
    ON form_employee_skills(employee_id, organization_id);
CREATE INDEX IF NOT EXISTS idx_form_skills_org
    ON form_employee_skills(organization_id);

-- =============================================================
-- 3. 稼働スタイル・キャパ（非金融）
-- =============================================================
CREATE TABLE IF NOT EXISTS form_employee_work_prefs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id VARCHAR NOT NULL,
    employee_id UUID NOT NULL REFERENCES employees(id),
    monthly_hours VARCHAR(50),
    work_hours JSONB DEFAULT '[]'::jsonb,
    work_style JSONB DEFAULT '[]'::jsonb,
    work_location VARCHAR(50),
    capacity VARCHAR(50),
    urgency_level VARCHAR(50),
    source VARCHAR DEFAULT 'supabase_sync',
    supabase_updated_at TIMESTAMPTZ,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_form_work_employee
    ON form_employee_work_prefs(employee_id, organization_id);
CREATE INDEX IF NOT EXISTS idx_form_work_org
    ON form_employee_work_prefs(organization_id);

-- =============================================================
-- 4. 連絡設定（非金融、PII除外: line_id除外）
-- =============================================================
CREATE TABLE IF NOT EXISTS form_employee_contact_prefs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id VARCHAR NOT NULL,
    employee_id UUID NOT NULL REFERENCES employees(id),
    contact_available_hours TEXT,
    preferred_channel VARCHAR(50),
    contact_ng JSONB DEFAULT '[]'::jsonb,
    communication_style VARCHAR(50),
    ai_disclosure_level VARCHAR(20) DEFAULT 'full',
    hobbies TEXT,
    source VARCHAR DEFAULT 'supabase_sync',
    supabase_updated_at TIMESTAMPTZ,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_form_contact_employee
    ON form_employee_contact_prefs(employee_id, organization_id);
CREATE INDEX IF NOT EXISTS idx_form_contact_org
    ON form_employee_contact_prefs(organization_id);

-- =============================================================
-- RLS有効化 + ポリシー（鉄則#2 / CRITICAL-4）
-- organization_id は VARCHAR なので ::text でキャスト
-- =============================================================
ALTER TABLE supabase_employee_mapping ENABLE ROW LEVEL SECURITY;
ALTER TABLE form_employee_skills ENABLE ROW LEVEL SECURITY;
ALTER TABLE form_employee_work_prefs ENABLE ROW LEVEL SECURITY;
ALTER TABLE form_employee_contact_prefs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS supabase_mapping_org_policy ON supabase_employee_mapping;
CREATE POLICY supabase_mapping_org_policy ON supabase_employee_mapping
    USING (organization_id = current_setting('app.current_organization_id', true)::text)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::text);

DROP POLICY IF EXISTS form_skills_org_policy ON form_employee_skills;
CREATE POLICY form_skills_org_policy ON form_employee_skills
    USING (organization_id = current_setting('app.current_organization_id', true)::text)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::text);

DROP POLICY IF EXISTS form_work_org_policy ON form_employee_work_prefs;
CREATE POLICY form_work_org_policy ON form_employee_work_prefs
    USING (organization_id = current_setting('app.current_organization_id', true)::text)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::text);

DROP POLICY IF EXISTS form_contact_org_policy ON form_employee_contact_prefs;
CREATE POLICY form_contact_org_policy ON form_employee_contact_prefs
    USING (organization_id = current_setting('app.current_organization_id', true)::text)
    WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::text);

-- =============================================================
-- コメント
-- =============================================================
COMMENT ON TABLE supabase_employee_mapping IS 'Supabase ↔ Cloud SQL 社員IDマッピング（UUID不一致のため名前ベースで解決）';
COMMENT ON TABLE form_employee_skills IS 'スキル自己評価（Supabase同期。非金融データのみ）';
COMMENT ON TABLE form_employee_work_prefs IS '稼働スタイル・キャパ（Supabase同期。非金融データのみ）';
COMMENT ON TABLE form_employee_contact_prefs IS '連絡設定（Supabase同期。line_id除外）';
