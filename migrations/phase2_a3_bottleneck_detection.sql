-- =====================================================
-- Phase 2 A3: ボトルネック検出 マイグレーション
-- =====================================================
--
-- 実行方法:
--   cloud-sql-proxy で接続後、psqlで実行
--
-- 作成日: 2026-01-24
-- 作成者: Claude Code
-- =====================================================

-- トランザクション開始
BEGIN;

-- =====================================================
-- 1. bottleneck_alerts テーブル作成
-- =====================================================

CREATE TABLE IF NOT EXISTS bottleneck_alerts (
    -- 基本情報
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,

    -- 部署フィルタ（Phase 3.5準拠）
    department_id UUID,

    -- ボトルネックタイプ
    bottleneck_type VARCHAR(50) NOT NULL,
    risk_level VARCHAR(20) NOT NULL,

    -- 対象情報
    target_type VARCHAR(50) NOT NULL,
    target_id VARCHAR(100) NOT NULL,
    target_name VARCHAR(255),

    -- 統計
    overdue_days INT,
    task_count INT,
    stale_days INT,

    -- 関連タスク
    related_task_ids TEXT[] DEFAULT '{}',
    sample_tasks JSONB DEFAULT '[]',

    -- ステータス
    status VARCHAR(20) DEFAULT 'active',
    first_detected_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_detected_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMPTZ,
    resolved_action TEXT,

    -- 機密区分
    classification VARCHAR(20) DEFAULT 'internal',

    -- 監査フィールド
    created_by UUID,
    updated_by UUID,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 制約
    UNIQUE(organization_id, bottleneck_type, target_type, target_id),
    CONSTRAINT check_bottleneck_type CHECK (
        bottleneck_type IN ('overdue_task', 'stale_task', 'task_concentration', 'no_assignee')
    ),
    CONSTRAINT check_bottleneck_risk_level CHECK (
        risk_level IN ('critical', 'high', 'medium', 'low')
    ),
    CONSTRAINT check_bottleneck_status CHECK (
        status IN ('active', 'resolved', 'dismissed')
    )
);

COMMENT ON TABLE bottleneck_alerts IS
'Phase 2進化版 A3: ボトルネック検出結果
- 期限超過、長期未完了、担当者集中を検出
- soulkun_insights と連携して通知';

-- =====================================================
-- 2. インデックス作成
-- =====================================================

CREATE INDEX IF NOT EXISTS idx_bottleneck_alerts_org_type
    ON bottleneck_alerts(organization_id, bottleneck_type);

CREATE INDEX IF NOT EXISTS idx_bottleneck_alerts_org_level
    ON bottleneck_alerts(organization_id, risk_level);

CREATE INDEX IF NOT EXISTS idx_bottleneck_alerts_status
    ON bottleneck_alerts(organization_id, status)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_bottleneck_alerts_target
    ON bottleneck_alerts(organization_id, target_type, target_id);

CREATE INDEX IF NOT EXISTS idx_bottleneck_alerts_department
    ON bottleneck_alerts(organization_id, department_id)
    WHERE department_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_bottleneck_alerts_detected_at
    ON bottleneck_alerts(organization_id, last_detected_at DESC);

-- =====================================================
-- 3. updated_at 自動更新トリガー
-- =====================================================

-- トリガー関数が存在しない場合は作成
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS trg_bottleneck_alerts_updated_at ON bottleneck_alerts;
CREATE TRIGGER trg_bottleneck_alerts_updated_at
    BEFORE UPDATE ON bottleneck_alerts
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- =====================================================
-- 4. 確認クエリ
-- =====================================================

DO $$
DECLARE
    table_count INT;
    index_count INT;
BEGIN
    -- テーブル数確認
    SELECT COUNT(*) INTO table_count
    FROM information_schema.tables
    WHERE table_schema = 'public'
    AND table_name = 'bottleneck_alerts';

    -- インデックス数確認
    SELECT COUNT(*) INTO index_count
    FROM pg_indexes
    WHERE schemaname = 'public'
    AND indexname LIKE '%bottleneck%';

    RAISE NOTICE '================================';
    RAISE NOTICE 'Phase 2 A3 マイグレーション完了';
    RAISE NOTICE '================================';
    RAISE NOTICE '作成テーブル数: %', table_count;
    RAISE NOTICE '作成インデックス数: %', index_count;
END $$;

-- コミット
COMMIT;
