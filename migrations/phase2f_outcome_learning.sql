-- ============================================================================
-- Phase 2F: 結果からの学習 - DBマイグレーション
-- ============================================================================
-- 設計書: docs/17_brain_completion_roadmap.md セクション Phase 2F
--
-- テーブル:
--   1. brain_outcome_events - 行動結果イベント
--   2. brain_outcome_patterns - 成功/失敗パターン
--
-- 実行方法:
--   psql -h <host> -U <user> -d <database> -f phase2f_outcome_learning.sql
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. brain_outcome_events テーブル
-- ============================================================================

-- 行動結果イベントテーブル
-- ソウルくんの通知・提案などのアクションとその結果を記録する
CREATE TABLE IF NOT EXISTS brain_outcome_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,

    -- イベント情報
    event_type VARCHAR(50) NOT NULL,  -- 'notification_sent', 'task_reminder', 'goal_reminder', etc.
    event_subtype VARCHAR(50),        -- 詳細分類
    event_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- ターゲット情報
    target_account_id VARCHAR(50) NOT NULL,  -- 対象ユーザー
    target_room_id VARCHAR(50),              -- 対象ルーム

    -- イベント詳細
    event_details JSONB NOT NULL DEFAULT '{}',
    -- 例: {
    --   "action": "send_reminder",
    --   "message_preview": "...",
    --   "sent_hour": 10,
    --   "day_of_week": "monday"
    -- }

    -- 関連リソース
    related_resource_type VARCHAR(50),  -- 'task', 'goal', 'notification'
    related_resource_id UUID,

    -- 結果追跡
    outcome_detected BOOLEAN DEFAULT false,
    outcome_type VARCHAR(50),  -- 'adopted', 'ignored', 'rejected', 'delayed', 'partial', 'pending'
    outcome_detected_at TIMESTAMPTZ,
    outcome_details JSONB,
    -- 例: {
    --   "response_time_hours": 2.5,
    --   "user_action": "completed_task",
    --   "feedback_signal": "task_completed"
    -- }

    -- 学習連携
    learning_extracted BOOLEAN DEFAULT false,
    learning_id UUID,  -- brain_learningsへの参照（昇格時）
    pattern_id UUID,   -- brain_outcome_patternsへの参照

    -- コンテキストスナップショット
    context_snapshot JSONB,

    -- 監査
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_brain_outcome_events_org
    ON brain_outcome_events(organization_id);

CREATE INDEX IF NOT EXISTS idx_brain_outcome_events_target
    ON brain_outcome_events(target_account_id);

CREATE INDEX IF NOT EXISTS idx_brain_outcome_events_type
    ON brain_outcome_events(event_type, outcome_type);

CREATE INDEX IF NOT EXISTS idx_brain_outcome_events_timestamp
    ON brain_outcome_events(event_timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_brain_outcome_events_pending
    ON brain_outcome_events(outcome_detected)
    WHERE outcome_detected = false;

CREATE INDEX IF NOT EXISTS idx_brain_outcome_events_org_target
    ON brain_outcome_events(organization_id, target_account_id, event_timestamp DESC);

COMMENT ON TABLE brain_outcome_events IS '行動結果イベント（Phase 2F）- ソウルくんのアクションとその結果を追跡';
COMMENT ON COLUMN brain_outcome_events.event_type IS 'イベントタイプ: notification_sent, task_reminder, goal_reminder, suggestion_made, proactive_message, announcement, daily_check, follow_up';
COMMENT ON COLUMN brain_outcome_events.outcome_type IS '結果タイプ: adopted, ignored, rejected, delayed, partial, pending';


-- ============================================================================
-- 2. brain_outcome_patterns テーブル
-- ============================================================================

-- 成功/失敗パターンテーブル
-- 抽出された結果のパターンを保存する
CREATE TABLE IF NOT EXISTS brain_outcome_patterns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,

    -- パターン識別
    pattern_type VARCHAR(50) NOT NULL,  -- 'timing', 'communication_style', 'task_type', 'user_preference', 'seasonal', 'day_of_week', 'response_time'
    pattern_category VARCHAR(50),        -- サブカテゴリ

    -- 適用対象
    scope VARCHAR(50) NOT NULL DEFAULT 'user',  -- 'global', 'user', 'room', 'department'
    scope_target_id VARCHAR(100),

    -- パターン内容
    pattern_content JSONB NOT NULL,
    -- 例（時間帯パターン）: {
    --   "type": "timing",
    --   "condition": {"hour_range": [9, 12], "day_of_week": ["monday", "tuesday"]},
    --   "effect": "high_response_rate",
    --   "description": "午前中の連絡に対して反応が良い"
    -- }

    -- 統計情報
    sample_count INTEGER DEFAULT 0,          -- サンプル数
    success_count INTEGER DEFAULT 0,         -- 成功回数
    failure_count INTEGER DEFAULT 0,         -- 失敗回数
    success_rate DECIMAL(5,4),               -- 成功率（0.0000〜1.0000）
    confidence_score DECIMAL(5,4),           -- 確信度（サンプル数と成功率から計算）

    -- 効果測定
    effectiveness_score DECIMAL(3,2),        -- 効果スコア（0.00〜1.00）
    last_effectiveness_check TIMESTAMPTZ,

    -- 状態
    is_active BOOLEAN DEFAULT true,
    is_validated BOOLEAN DEFAULT false,      -- 検証済みか
    validated_at TIMESTAMPTZ,

    -- 学習連携（brain_learningsに昇格した場合）
    promoted_to_learning_id UUID,            -- brain_learnings.idへの参照
    promoted_at TIMESTAMPTZ,

    -- 監査
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_brain_outcome_patterns_org
    ON brain_outcome_patterns(organization_id);

CREATE INDEX IF NOT EXISTS idx_brain_outcome_patterns_type
    ON brain_outcome_patterns(pattern_type);

CREATE INDEX IF NOT EXISTS idx_brain_outcome_patterns_scope
    ON brain_outcome_patterns(scope, scope_target_id);

CREATE INDEX IF NOT EXISTS idx_brain_outcome_patterns_active
    ON brain_outcome_patterns(is_active)
    WHERE is_active = true;

CREATE INDEX IF NOT EXISTS idx_brain_outcome_patterns_confidence
    ON brain_outcome_patterns(confidence_score DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_brain_outcome_patterns_promotable
    ON brain_outcome_patterns(confidence_score, sample_count)
    WHERE is_active = true AND promoted_to_learning_id IS NULL;

COMMENT ON TABLE brain_outcome_patterns IS '成功/失敗パターン（Phase 2F）- 抽出された結果のパターン';
COMMENT ON COLUMN brain_outcome_patterns.pattern_type IS 'パターンタイプ: timing, communication_style, task_type, user_preference, seasonal, day_of_week, response_time';
COMMENT ON COLUMN brain_outcome_patterns.scope IS 'スコープ: global, user, room, department';


-- ============================================================================
-- 3. トリガー
-- ============================================================================

-- updated_atの自動更新トリガー（update_updated_at_column関数が存在する場合）
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'update_updated_at_column') THEN
        -- brain_outcome_patterns
        IF NOT EXISTS (
            SELECT 1 FROM pg_trigger
            WHERE tgname = 'update_brain_outcome_patterns_updated_at'
        ) THEN
            CREATE TRIGGER update_brain_outcome_patterns_updated_at
                BEFORE UPDATE ON brain_outcome_patterns
                FOR EACH ROW
                EXECUTE FUNCTION update_updated_at_column();
        END IF;
    END IF;
END
$$;


-- ============================================================================
-- 4. 外部キー制約（オプション）
-- ============================================================================

-- brain_learningsテーブルが存在する場合のみ外部キーを追加
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'brain_learnings') THEN
        -- brain_outcome_events.learning_id -> brain_learnings.id
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.table_constraints
            WHERE constraint_name = 'fk_outcome_events_learning'
        ) THEN
            ALTER TABLE brain_outcome_events
            ADD CONSTRAINT fk_outcome_events_learning
            FOREIGN KEY (learning_id) REFERENCES brain_learnings(id)
            ON DELETE SET NULL;
        END IF;

        -- brain_outcome_patterns.promoted_to_learning_id -> brain_learnings.id
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.table_constraints
            WHERE constraint_name = 'fk_outcome_patterns_promoted_learning'
        ) THEN
            ALTER TABLE brain_outcome_patterns
            ADD CONSTRAINT fk_outcome_patterns_promoted_learning
            FOREIGN KEY (promoted_to_learning_id) REFERENCES brain_learnings(id)
            ON DELETE SET NULL;
        END IF;
    END IF;
END
$$;

-- brain_outcome_events.pattern_id -> brain_outcome_patterns.id
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'fk_outcome_events_pattern'
    ) THEN
        ALTER TABLE brain_outcome_events
        ADD CONSTRAINT fk_outcome_events_pattern
        FOREIGN KEY (pattern_id) REFERENCES brain_outcome_patterns(id)
        ON DELETE SET NULL;
    END IF;
END
$$;


-- ============================================================================
-- 5. organizationsテーブルへの外部キー（テナント分離）
-- ============================================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'organizations') THEN
        -- brain_outcome_events.organization_id -> organizations.id
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.table_constraints
            WHERE constraint_name = 'fk_outcome_events_org'
        ) THEN
            ALTER TABLE brain_outcome_events
            ADD CONSTRAINT fk_outcome_events_org
            FOREIGN KEY (organization_id) REFERENCES organizations(id)
            ON DELETE CASCADE;
        END IF;

        -- brain_outcome_patterns.organization_id -> organizations.id
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.table_constraints
            WHERE constraint_name = 'fk_outcome_patterns_org'
        ) THEN
            ALTER TABLE brain_outcome_patterns
            ADD CONSTRAINT fk_outcome_patterns_org
            FOREIGN KEY (organization_id) REFERENCES organizations(id)
            ON DELETE CASCADE;
        END IF;
    END IF;
END
$$;


-- ============================================================================
-- 6. 確認クエリ
-- ============================================================================

-- テーブル確認
SELECT
    table_name,
    (SELECT COUNT(*) FROM information_schema.columns WHERE table_name = t.table_name) as column_count
FROM information_schema.tables t
WHERE table_name IN ('brain_outcome_events', 'brain_outcome_patterns')
ORDER BY table_name;

-- インデックス確認
SELECT
    indexname,
    tablename
FROM pg_indexes
WHERE tablename IN ('brain_outcome_events', 'brain_outcome_patterns')
ORDER BY tablename, indexname;


COMMIT;

-- ============================================================================
-- 実行結果の確認
-- ============================================================================
-- Phase 2F マイグレーション完了
-- テーブル: brain_outcome_events, brain_outcome_patterns
-- インデックス: 13個
-- ============================================================================
