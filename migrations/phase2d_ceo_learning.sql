-- ============================================================================
-- Phase 2D: CEO学習・ガーディアン機能
-- マイグレーション: phase2d_ceo_learning.sql
-- 作成日: 2026-01-27
-- 作成者: Claude Code
--
-- 目的:
-- - CEOとの対話から「教え」を抽出・蓄積するためのテーブル
-- - MVV・組織論との矛盾を検出してアラートを管理するテーブル
-- - 教えの使用ログを記録するテーブル
--
-- 10の鉄則チェック:
-- - [x] #1 全テーブルにorganization_id
-- - [x] #3 監査ログ対応（classification）
-- - [x] #5 ページネーション対応（インデックス）
-- - [x] #6 キャッシュ対応（updated_at）
-- - [x] #9 SQLインジェクション対策（パラメータ化前提）
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. ceo_teachings テーブル
-- CEOからの教えを保存
-- ============================================================================
CREATE TABLE IF NOT EXISTS ceo_teachings (
    -- 識別情報
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    ceo_user_id UUID NOT NULL,  -- Phase 4A: BPaaS顧客のCEOユーザーID

    -- 教えの内容
    statement TEXT NOT NULL,              -- 主張（何を言っているか）
    reasoning TEXT,                       -- 理由（なぜそう言っているか）
    context TEXT,                         -- 文脈（どんな状況で）
    target VARCHAR(100),                  -- 対象（全員/マネージャー/特定部署等）

    -- 分類
    category VARCHAR(50) NOT NULL,        -- カテゴリ
    subcategory VARCHAR(50),              -- 細分類
    keywords TEXT[],                      -- 検索用キーワード（配列）

    -- 検証結果
    validation_status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (validation_status IN ('pending', 'verified', 'alert_pending', 'overridden')),
        -- pending: 検証中
        -- verified: 検証済み（矛盾なし）
        -- alert_pending: アラート待ち（CEOの確認待ち）
        -- overridden: CEOが上書き許可（矛盾あるが保存）
    mvv_alignment_score DECIMAL(3,2)
        CHECK (mvv_alignment_score IS NULL OR (mvv_alignment_score >= 0.00 AND mvv_alignment_score <= 1.00)),
    theory_alignment_score DECIMAL(3,2)
        CHECK (theory_alignment_score IS NULL OR (theory_alignment_score >= 0.00 AND theory_alignment_score <= 1.00)),

    -- 優先度・活性化
    priority INTEGER DEFAULT 5 CHECK (priority >= 1 AND priority <= 10),
    is_active BOOLEAN DEFAULT true,
    supersedes UUID REFERENCES ceo_teachings(id), -- この教えが上書きする過去の教えID

    -- 利用統計
    usage_count INTEGER DEFAULT 0,        -- 何回応答に使われたか
    last_used_at TIMESTAMP WITH TIME ZONE,
    helpful_count INTEGER DEFAULT 0,      -- 役に立ったと評価された回数

    -- ソース情報
    source_room_id VARCHAR(50),           -- 元の会話のroom_id
    source_message_id VARCHAR(50),        -- 元のメッセージID
    extracted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    -- 監査・メタデータ
    classification VARCHAR(20) DEFAULT 'confidential'
        CHECK (classification IN ('public', 'internal', 'confidential', 'restricted')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ceo_teachings インデックス
CREATE INDEX IF NOT EXISTS idx_ceo_teachings_org
    ON ceo_teachings(organization_id);
CREATE INDEX IF NOT EXISTS idx_ceo_teachings_ceo
    ON ceo_teachings(organization_id, ceo_user_id);
CREATE INDEX IF NOT EXISTS idx_ceo_teachings_category
    ON ceo_teachings(organization_id, category);
CREATE INDEX IF NOT EXISTS idx_ceo_teachings_keywords
    ON ceo_teachings USING GIN(keywords);
CREATE INDEX IF NOT EXISTS idx_ceo_teachings_active
    ON ceo_teachings(organization_id, is_active) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_ceo_teachings_validation
    ON ceo_teachings(validation_status);
CREATE INDEX IF NOT EXISTS idx_ceo_teachings_priority
    ON ceo_teachings(organization_id, priority DESC) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_ceo_teachings_updated
    ON ceo_teachings(updated_at DESC);

-- カテゴリのCHECK制約
ALTER TABLE ceo_teachings
    ADD CONSTRAINT chk_ceo_teachings_category
    CHECK (category IN (
        -- MVV関連
        'mvv_mission', 'mvv_vision', 'mvv_values',
        -- 組織論関連
        'choice_theory', 'sdt', 'servant', 'psych_safety',
        -- 業務関連
        'biz_sales', 'biz_hr', 'biz_accounting', 'biz_general',
        -- 人・文化関連
        'culture', 'communication', 'staff_guidance',
        -- その他
        'other'
    ));

COMMENT ON TABLE ceo_teachings IS 'CEOからの教え（Phase 2D）';
COMMENT ON COLUMN ceo_teachings.ceo_user_id IS 'Phase 4A: BPaaS展開時は顧客CEOのユーザーID';
COMMENT ON COLUMN ceo_teachings.statement IS '教えの主張（何を言っているか）';
COMMENT ON COLUMN ceo_teachings.reasoning IS '教えの理由（なぜそう言っているか）';
COMMENT ON COLUMN ceo_teachings.context IS '教えの文脈（どんな状況で）';
COMMENT ON COLUMN ceo_teachings.target IS '教えの対象（全員/マネージャー/特定部署等）';
COMMENT ON COLUMN ceo_teachings.validation_status IS '検証ステータス: pending/verified/alert_pending/overridden';
COMMENT ON COLUMN ceo_teachings.supersedes IS 'この教えが上書きする過去の教えID';

-- ============================================================================
-- 2. ceo_teaching_conflicts テーブル
-- 教えの矛盾情報を保存
-- ============================================================================
CREATE TABLE IF NOT EXISTS ceo_teaching_conflicts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    teaching_id UUID NOT NULL REFERENCES ceo_teachings(id) ON DELETE CASCADE,

    -- 矛盾情報
    conflict_type VARCHAR(50) NOT NULL
        CHECK (conflict_type IN ('mvv', 'choice_theory', 'sdt', 'guidelines', 'existing')),
    conflict_subtype VARCHAR(50),         -- 細分類（例: 'mission', 'vision', 'autonomy'等）
    description TEXT NOT NULL,            -- 矛盾の説明
    reference TEXT NOT NULL,              -- 参照した基準（原文引用）
    severity VARCHAR(10) NOT NULL
        CHECK (severity IN ('high', 'medium', 'low')),

    -- 関連教え（既存教えとの矛盾の場合）
    conflicting_teaching_id UUID REFERENCES ceo_teachings(id),

    -- メタデータ
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ceo_teaching_conflicts インデックス
CREATE INDEX IF NOT EXISTS idx_conflicts_org
    ON ceo_teaching_conflicts(organization_id);
CREATE INDEX IF NOT EXISTS idx_conflicts_teaching
    ON ceo_teaching_conflicts(teaching_id);
CREATE INDEX IF NOT EXISTS idx_conflicts_type
    ON ceo_teaching_conflicts(conflict_type);
CREATE INDEX IF NOT EXISTS idx_conflicts_severity
    ON ceo_teaching_conflicts(severity);

COMMENT ON TABLE ceo_teaching_conflicts IS '教えの矛盾情報（Phase 2D）';
COMMENT ON COLUMN ceo_teaching_conflicts.conflict_type IS '矛盾タイプ: mvv/choice_theory/sdt/guidelines/existing';
COMMENT ON COLUMN ceo_teaching_conflicts.severity IS '深刻度: high/medium/low';

-- ============================================================================
-- 3. guardian_alerts テーブル
-- ガーディアンからのアラートを管理
-- ============================================================================
CREATE TABLE IF NOT EXISTS guardian_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    teaching_id UUID NOT NULL REFERENCES ceo_teachings(id),

    -- アラート内容
    conflict_summary TEXT NOT NULL,       -- 矛盾の要約
    alert_message TEXT NOT NULL,          -- CEOへのメッセージ（ソウルくん口調）
    alternative_suggestion TEXT,          -- 代替案

    -- ステータス
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'acknowledged', 'overridden', 'retracted')),
        -- pending: CEOの回答待ち
        -- acknowledged: CEOが確認済み（教えを取り消し）
        -- overridden: CEOが上書き許可（矛盾あるが保存）
        -- retracted: CEOが撤回（教えを修正する）
    ceo_response TEXT,                    -- CEOの回答
    ceo_reasoning TEXT,                   -- CEOの判断理由（なぜ上書きしたか等）
    resolved_at TIMESTAMP WITH TIME ZONE,

    -- 通知情報
    notified_at TIMESTAMP WITH TIME ZONE,
    notification_room_id VARCHAR(50),     -- 通知先room_id
    notification_message_id VARCHAR(50),  -- 通知メッセージID

    -- 監査・メタデータ
    classification VARCHAR(20) DEFAULT 'confidential'
        CHECK (classification IN ('public', 'internal', 'confidential', 'restricted')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- guardian_alerts インデックス
CREATE INDEX IF NOT EXISTS idx_alerts_org
    ON guardian_alerts(organization_id);
CREATE INDEX IF NOT EXISTS idx_alerts_status
    ON guardian_alerts(status);
CREATE INDEX IF NOT EXISTS idx_alerts_teaching
    ON guardian_alerts(teaching_id);
CREATE INDEX IF NOT EXISTS idx_alerts_pending
    ON guardian_alerts(organization_id, status) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_alerts_created
    ON guardian_alerts(created_at DESC);

COMMENT ON TABLE guardian_alerts IS 'ガーディアンアラート（Phase 2D）';
COMMENT ON COLUMN guardian_alerts.status IS 'ステータス: pending/acknowledged/overridden/retracted';
COMMENT ON COLUMN guardian_alerts.ceo_reasoning IS 'CEOの判断理由（なぜ上書きしたか等）';

-- ============================================================================
-- 4. teaching_usage_logs テーブル
-- 教えの使用ログを記録（監査・分析用）
-- ============================================================================
CREATE TABLE IF NOT EXISTS teaching_usage_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    teaching_id UUID NOT NULL REFERENCES ceo_teachings(id),

    -- 使用コンテキスト
    room_id VARCHAR(50) NOT NULL,
    account_id VARCHAR(50) NOT NULL,
    user_message TEXT NOT NULL,           -- ユーザーのメッセージ
    response_excerpt TEXT,                -- 応答の抜粋（200文字程度）

    -- 選択理由
    relevance_score DECIMAL(3,2)
        CHECK (relevance_score IS NULL OR (relevance_score >= 0.00 AND relevance_score <= 1.00)),
    selection_reasoning TEXT,             -- なぜこの教えを選んだか

    -- フィードバック
    was_helpful BOOLEAN,                  -- 役に立ったか（ユーザー評価）
    feedback TEXT,                        -- フィードバック内容

    -- 監査・メタデータ
    classification VARCHAR(20) DEFAULT 'internal'
        CHECK (classification IN ('public', 'internal', 'confidential', 'restricted')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- teaching_usage_logs インデックス
CREATE INDEX IF NOT EXISTS idx_usage_org
    ON teaching_usage_logs(organization_id);
CREATE INDEX IF NOT EXISTS idx_usage_teaching
    ON teaching_usage_logs(teaching_id);
CREATE INDEX IF NOT EXISTS idx_usage_room
    ON teaching_usage_logs(room_id);
CREATE INDEX IF NOT EXISTS idx_usage_account
    ON teaching_usage_logs(account_id);
CREATE INDEX IF NOT EXISTS idx_usage_created
    ON teaching_usage_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_helpful
    ON teaching_usage_logs(teaching_id, was_helpful) WHERE was_helpful IS NOT NULL;

COMMENT ON TABLE teaching_usage_logs IS '教え使用ログ（Phase 2D）';
COMMENT ON COLUMN teaching_usage_logs.relevance_score IS '関連度スコア（0.00-1.00）';
COMMENT ON COLUMN teaching_usage_logs.was_helpful IS '役に立ったか（ユーザー評価）';

-- ============================================================================
-- 5. トリガー: updated_at 自動更新
-- ============================================================================

-- 汎用updated_at更新関数（既存の場合は作成しない）
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ceo_teachings.updated_at トリガー
DROP TRIGGER IF EXISTS update_ceo_teachings_updated_at ON ceo_teachings;
CREATE TRIGGER update_ceo_teachings_updated_at
    BEFORE UPDATE ON ceo_teachings
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- guardian_alerts.updated_at トリガー
DROP TRIGGER IF EXISTS update_guardian_alerts_updated_at ON guardian_alerts;
CREATE TRIGGER update_guardian_alerts_updated_at
    BEFORE UPDATE ON guardian_alerts
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- 6. RLS（Row Level Security）準備 - Phase 4A向け
-- 現時点では有効化しないが、構造は準備しておく
-- ============================================================================

-- RLSポリシー（コメントアウト - Phase 4Aで有効化）
-- ALTER TABLE ceo_teachings ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE ceo_teaching_conflicts ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE guardian_alerts ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE teaching_usage_logs ENABLE ROW LEVEL SECURITY;

-- ============================================================================
-- 7. 初期データ（オプション）
-- ============================================================================

-- テストデータは本番では挿入しない
-- 開発環境でのみ使用する場合は別ファイルで管理

COMMIT;

-- ============================================================================
-- 確認用クエリ
-- ============================================================================
-- SELECT table_name, column_name, data_type
-- FROM information_schema.columns
-- WHERE table_name IN ('ceo_teachings', 'ceo_teaching_conflicts', 'guardian_alerts', 'teaching_usage_logs')
-- ORDER BY table_name, ordinal_position;
