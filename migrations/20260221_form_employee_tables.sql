-- =============================================================================
-- Phase 2-A: Googleフォームスタッフパーソナルデータ用テーブル追加
-- =============================================================================
-- 目的: supabase-sync が参照する 4 テーブルを Cloud SQL に作成する
--       フォームの回答 → Supabase → Cloud SQL の同期パイプラインを完成させる
-- 関連: supabase-sync/main.py の sync_skills / sync_work_preferences /
--       sync_contact_preferences / _build_employee_mapping
-- ロールバック: 20260221_form_employee_tables_rollback.sql
-- 作成者: Claude Sonnet 4.6 / 2026-02-21
-- =============================================================================

-- organization_id は employees テーブルと同じ character varying（VARCHAR）型で統一
-- employee_id は employees.id と同じ UUID 型

-- ============================================================
-- 1. Supabase→CloudSQL 従業員IDマッピングキャッシュ
-- ============================================================
CREATE TABLE IF NOT EXISTS supabase_employee_mapping (
    id                   BIGSERIAL PRIMARY KEY,
    organization_id      CHARACTER VARYING(255) NOT NULL,
    supabase_employee_id UUID                   NOT NULL,
    cloudsql_employee_id UUID                   NOT NULL,
    employee_name        TEXT                   NOT NULL,
    created_at           TIMESTAMPTZ            NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ            NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_supabase_employee_mapping
        UNIQUE (supabase_employee_id, organization_id)
);

CREATE INDEX IF NOT EXISTS idx_supabase_employee_mapping_org
    ON supabase_employee_mapping (organization_id);

CREATE INDEX IF NOT EXISTS idx_supabase_employee_mapping_cloudsql
    ON supabase_employee_mapping (cloudsql_employee_id);

-- RLS有効化（鉄則#2）
ALTER TABLE supabase_employee_mapping ENABLE ROW LEVEL SECURITY;

CREATE POLICY supabase_employee_mapping_org_isolation
    ON supabase_employee_mapping
    USING (organization_id::text = current_setting('app.current_organization_id', true))
    WITH CHECK (organization_id::text = current_setting('app.current_organization_id', true));

-- ============================================================
-- 2. スキル自己評価テーブル
-- ============================================================
CREATE TABLE IF NOT EXISTS form_employee_skills (
    id                   BIGSERIAL PRIMARY KEY,
    organization_id      CHARACTER VARYING(255) NOT NULL,
    employee_id          UUID                   NOT NULL,

    -- スキル評価（Googleフォームの多段階評価をJSONBで保持）
    skill_levels         JSONB                  NOT NULL DEFAULT '{}',
    -- 例: {"Python": "得意", "Excel": "実務経験あり", "Java": "触った程度"}

    top_skills           JSONB                  NOT NULL DEFAULT '[]',
    -- 例: ["Python", "データ分析", "プロジェクト管理"]

    weak_skills          JSONB                  NOT NULL DEFAULT '[]',
    -- 例: ["デザイン", "財務"]

    preferred_tasks      JSONB                  NOT NULL DEFAULT '[]',
    -- 例: ["資料作成", "顧客折衝"]

    avoided_tasks        JSONB                  NOT NULL DEFAULT '[]',
    -- 例: ["冷凍食品の配送"]

    supabase_updated_at  TIMESTAMPTZ,
    synced_at            TIMESTAMPTZ            NOT NULL DEFAULT NOW(),
    created_at           TIMESTAMPTZ            NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ            NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_form_employee_skills
        UNIQUE (employee_id, organization_id)
);

CREATE INDEX IF NOT EXISTS idx_form_employee_skills_org
    ON form_employee_skills (organization_id);

CREATE INDEX IF NOT EXISTS idx_form_employee_skills_employee
    ON form_employee_skills (employee_id);

-- RLS
ALTER TABLE form_employee_skills ENABLE ROW LEVEL SECURITY;

CREATE POLICY form_employee_skills_org_isolation
    ON form_employee_skills
    USING (organization_id::text = current_setting('app.current_organization_id', true))
    WITH CHECK (organization_id::text = current_setting('app.current_organization_id', true));

-- ============================================================
-- 3. 稼働スタイルテーブル
-- ============================================================
CREATE TABLE IF NOT EXISTS form_employee_work_prefs (
    id                   BIGSERIAL PRIMARY KEY,
    organization_id      CHARACTER VARYING(255) NOT NULL,
    employee_id          UUID                   NOT NULL,

    -- 月間稼働時間（例: "120h", "フルタイム"）
    monthly_hours        TEXT,

    -- 稼働可能時間帯（例: ["平日9〜18時", "土曜午前"]）
    work_hours           JSONB                  NOT NULL DEFAULT '[]',

    -- 勤務形態（例: ["リモート可", "出社可"]）
    work_style           JSONB                  NOT NULL DEFAULT '[]',

    -- 稼働場所（例: "完全リモート", "ハイブリッド", "出社のみ"）
    work_location        TEXT,

    -- キャパシティ（例: "余裕あり", "普通", "限界"）
    capacity             TEXT,

    -- 緊急対応可否（例: "対応可", "事前相談必要", "不可"）
    urgency_level        TEXT,

    supabase_updated_at  TIMESTAMPTZ,
    synced_at            TIMESTAMPTZ            NOT NULL DEFAULT NOW(),
    created_at           TIMESTAMPTZ            NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ            NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_form_employee_work_prefs
        UNIQUE (employee_id, organization_id)
);

CREATE INDEX IF NOT EXISTS idx_form_employee_work_prefs_org
    ON form_employee_work_prefs (organization_id);

CREATE INDEX IF NOT EXISTS idx_form_employee_work_prefs_employee
    ON form_employee_work_prefs (employee_id);

-- RLS
ALTER TABLE form_employee_work_prefs ENABLE ROW LEVEL SECURITY;

CREATE POLICY form_employee_work_prefs_org_isolation
    ON form_employee_work_prefs
    USING (organization_id::text = current_setting('app.current_organization_id', true))
    WITH CHECK (organization_id::text = current_setting('app.current_organization_id', true));

-- ============================================================
-- 4. 連絡設定テーブル
-- ============================================================
CREATE TABLE IF NOT EXISTS form_employee_contact_prefs (
    id                   BIGSERIAL PRIMARY KEY,
    organization_id      CHARACTER VARYING(255) NOT NULL,
    employee_id          UUID                   NOT NULL,

    -- 連絡可能時間帯（例: "平日10〜19時"）
    contact_available_hours TEXT,

    -- 優先連絡手段（例: "ChatWork", "Slack", "メール"）
    preferred_channel    TEXT,

    -- 連絡NGな内容（例: ["深夜連絡", "週末の急ぎでない相談"]）
    contact_ng           JSONB                  NOT NULL DEFAULT '[]',

    -- コミュニケーションスタイル（例: "要点のみ", "詳しく説明してほしい"）
    communication_style  TEXT,

    -- AIへの情報開示レベル（'full', 'partial', 'minimal'）
    ai_disclosure_level  TEXT                   NOT NULL DEFAULT 'full',

    -- 趣味・雑談のネタ（PII低リスク）
    hobbies              TEXT,

    supabase_updated_at  TIMESTAMPTZ,
    synced_at            TIMESTAMPTZ            NOT NULL DEFAULT NOW(),
    created_at           TIMESTAMPTZ            NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ            NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_form_employee_contact_prefs
        UNIQUE (employee_id, organization_id)
);

CREATE INDEX IF NOT EXISTS idx_form_employee_contact_prefs_org
    ON form_employee_contact_prefs (organization_id);

CREATE INDEX IF NOT EXISTS idx_form_employee_contact_prefs_employee
    ON form_employee_contact_prefs (employee_id);

-- RLS
ALTER TABLE form_employee_contact_prefs ENABLE ROW LEVEL SECURITY;

CREATE POLICY form_employee_contact_prefs_org_isolation
    ON form_employee_contact_prefs
    USING (organization_id::text = current_setting('app.current_organization_id', true))
    WITH CHECK (organization_id::text = current_setting('app.current_organization_id', true));

-- =============================================================================
-- 完了メッセージ
-- =============================================================================
-- 実行後確認コマンド:
--   SELECT table_name FROM information_schema.tables
--   WHERE table_name LIKE 'form_employee%' OR table_name = 'supabase_employee_mapping';
-- =============================================================================
