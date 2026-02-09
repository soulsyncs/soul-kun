-- ============================================================================
-- Phase 3.6: Organization Chart SaaS Tables
-- ============================================================================
-- 組織図SaaS化の基盤テーブル
--
-- テーブル:
--   1. org_chart_tenants - テナント管理
--   2. org_chart_users - テナント内ユーザー
--   3. org_chart_subscriptions - サブスクリプション管理
--   4. org_chart_audit_logs - 変更監査
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. org_chart_tenants テーブル
-- ============================================================================

CREATE TABLE IF NOT EXISTS org_chart_tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,

    -- テナント情報
    tenant_name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) NOT NULL UNIQUE,
    domain VARCHAR(255),

    -- 設定
    max_users INTEGER DEFAULT 50,
    features JSONB DEFAULT '{}',

    -- ステータス
    status VARCHAR(20) NOT NULL DEFAULT 'active',  -- active, suspended, cancelled

    -- タイムスタンプ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE org_chart_tenants OWNER TO soulkun_user;

CREATE INDEX IF NOT EXISTS idx_org_chart_tenants_org
    ON org_chart_tenants(organization_id);
CREATE INDEX IF NOT EXISTS idx_org_chart_tenants_slug
    ON org_chart_tenants(slug);

-- ============================================================================
-- 2. org_chart_users テーブル
-- ============================================================================

CREATE TABLE IF NOT EXISTS org_chart_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    tenant_id UUID NOT NULL REFERENCES org_chart_tenants(id),

    -- ユーザー情報
    firebase_uid VARCHAR(128) NOT NULL,
    email VARCHAR(255) NOT NULL,
    display_name VARCHAR(255),

    -- 権限
    role VARCHAR(50) NOT NULL DEFAULT 'viewer',  -- owner, admin, editor, viewer

    -- ステータス
    status VARCHAR(20) NOT NULL DEFAULT 'active',  -- active, invited, disabled
    last_login_at TIMESTAMPTZ,

    -- タイムスタンプ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- ユニーク制約
    UNIQUE (tenant_id, firebase_uid)
);

ALTER TABLE org_chart_users OWNER TO soulkun_user;

CREATE INDEX IF NOT EXISTS idx_org_chart_users_org
    ON org_chart_users(organization_id);
CREATE INDEX IF NOT EXISTS idx_org_chart_users_tenant
    ON org_chart_users(tenant_id);
CREATE INDEX IF NOT EXISTS idx_org_chart_users_firebase
    ON org_chart_users(firebase_uid);

-- ============================================================================
-- 3. org_chart_subscriptions テーブル
-- ============================================================================

CREATE TABLE IF NOT EXISTS org_chart_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    tenant_id UUID NOT NULL REFERENCES org_chart_tenants(id),

    -- プラン情報
    plan VARCHAR(50) NOT NULL DEFAULT 'free',  -- free, starter, business, enterprise
    billing_cycle VARCHAR(20) DEFAULT 'monthly',  -- monthly, yearly

    -- 期間
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ,

    -- Stripe連携
    stripe_customer_id VARCHAR(255),
    stripe_subscription_id VARCHAR(255),

    -- ステータス
    status VARCHAR(20) NOT NULL DEFAULT 'active',  -- active, past_due, cancelled, trialing

    -- タイムスタンプ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE org_chart_subscriptions OWNER TO soulkun_user;

CREATE INDEX IF NOT EXISTS idx_org_chart_subscriptions_org
    ON org_chart_subscriptions(organization_id);
CREATE INDEX IF NOT EXISTS idx_org_chart_subscriptions_tenant
    ON org_chart_subscriptions(tenant_id);

-- ============================================================================
-- 4. org_chart_audit_logs テーブル
-- ============================================================================

CREATE TABLE IF NOT EXISTS org_chart_audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    tenant_id UUID NOT NULL,

    -- アクション
    user_id UUID NOT NULL,
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50) NOT NULL,
    resource_id VARCHAR(255),

    -- 詳細（PII注意: 本文・名前等は含めない）
    changes JSONB DEFAULT '{}',
    ip_address VARCHAR(45),

    -- タイムスタンプ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE org_chart_audit_logs OWNER TO soulkun_user;

CREATE INDEX IF NOT EXISTS idx_org_chart_audit_org
    ON org_chart_audit_logs(organization_id);
CREATE INDEX IF NOT EXISTS idx_org_chart_audit_tenant
    ON org_chart_audit_logs(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_org_chart_audit_user
    ON org_chart_audit_logs(user_id, created_at DESC);

-- ============================================================================
-- 5. トリガー
-- ============================================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'update_updated_at_column') THEN
        IF NOT EXISTS (
            SELECT 1 FROM pg_trigger WHERE tgname = 'update_org_chart_tenants_updated_at'
        ) THEN
            CREATE TRIGGER update_org_chart_tenants_updated_at
                BEFORE UPDATE ON org_chart_tenants
                FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM pg_trigger WHERE tgname = 'update_org_chart_users_updated_at'
        ) THEN
            CREATE TRIGGER update_org_chart_users_updated_at
                BEFORE UPDATE ON org_chart_users
                FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM pg_trigger WHERE tgname = 'update_org_chart_subscriptions_updated_at'
        ) THEN
            CREATE TRIGGER update_org_chart_subscriptions_updated_at
                BEFORE UPDATE ON org_chart_subscriptions
                FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
        END IF;
    END IF;
END
$$;

-- ============================================================================
-- 6. RLS
-- ============================================================================

ALTER TABLE org_chart_tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE org_chart_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE org_chart_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE org_chart_audit_logs ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policy WHERE polname = 'org_chart_tenants_org_isolation') THEN
        CREATE POLICY org_chart_tenants_org_isolation ON org_chart_tenants
            FOR ALL USING (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policy WHERE polname = 'org_chart_users_org_isolation') THEN
        CREATE POLICY org_chart_users_org_isolation ON org_chart_users
            FOR ALL USING (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policy WHERE polname = 'org_chart_subscriptions_org_isolation') THEN
        CREATE POLICY org_chart_subscriptions_org_isolation ON org_chart_subscriptions
            FOR ALL USING (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policy WHERE polname = 'org_chart_audit_logs_org_isolation') THEN
        CREATE POLICY org_chart_audit_logs_org_isolation ON org_chart_audit_logs
            FOR ALL USING (organization_id = current_setting('app.current_organization_id', true)::uuid);
    END IF;
END
$$;

-- ============================================================================
-- 7. 確認
-- ============================================================================

SELECT table_name,
       (SELECT COUNT(*) FROM information_schema.columns c WHERE c.table_name = t.table_name) AS cols
FROM information_schema.tables t
WHERE table_name LIKE 'org_chart_%'
ORDER BY table_name;

COMMIT;
