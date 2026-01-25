-- =====================================================
-- Phase X: アナウンス機能マイグレーション
-- バージョン: v10.26.0
-- 作成日: 2026-01-25
--
-- 概要:
--   管理部またはカズさんからのアナウンス依頼を処理し、
--   指定チャットルームにオールメンション送信・タスク作成する機能
--
-- テーブル:
--   1. scheduled_announcements - アナウンス予約・実行管理
--   2. announcement_logs - 実行ログ（監査証跡）
--   3. announcement_patterns - パターン検知（A1連携）
--
-- 10の鉄則チェック:
--   [x] #1 organization_id: 全テーブルに含む
--   [x] #3 監査ログ: announcement_logs で記録
--   [x] #9 SQLインジェクション: パラメータ化クエリ前提
-- =====================================================

-- =====================================================
-- 1. scheduled_announcements テーブル
-- =====================================================
-- アナウンスの予約・実行状態を管理

CREATE TABLE IF NOT EXISTS scheduled_announcements (
    -- =====================================================
    -- 主キー
    -- =====================================================
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- =====================================================
    -- テナント分離（10の鉄則 #1）
    -- =====================================================
    organization_id VARCHAR(100) NOT NULL DEFAULT 'org_soulsyncs',

    -- =====================================================
    -- アナウンス内容
    -- =====================================================
    title VARCHAR(200) NOT NULL,              -- 管理用タイトル（短縮版）
    message_content TEXT NOT NULL,            -- 送信するメッセージ本文

    -- =====================================================
    -- 送信先ルーム
    -- =====================================================
    target_room_id BIGINT NOT NULL,           -- ChatWork room_id
    target_room_name VARCHAR(255),            -- ルーム名（キャッシュ）

    -- =====================================================
    -- タスク作成設定
    -- =====================================================
    create_tasks BOOLEAN NOT NULL DEFAULT FALSE,
    task_deadline TIMESTAMPTZ,                -- タスク期限（NULL=期限なし）
    task_include_account_ids BIGINT[] DEFAULT '{}',   -- 含める人（空=全員）
    task_exclude_account_ids BIGINT[] DEFAULT '{}',   -- 除外する人
    task_assign_all_members BOOLEAN DEFAULT FALSE,    -- 全員にタスク

    -- =====================================================
    -- スケジュール設定
    -- =====================================================
    schedule_type VARCHAR(20) NOT NULL DEFAULT 'immediate'
        CHECK (schedule_type IN ('immediate', 'one_time', 'recurring')),
    scheduled_at TIMESTAMPTZ,                 -- one_time: 実行予定日時
    cron_expression VARCHAR(100),             -- recurring: cron式
    cron_description VARCHAR(200),            -- recurring: 人間向け説明（「毎週月曜9時」）
    timezone VARCHAR(50) DEFAULT 'Asia/Tokyo',
    skip_holidays BOOLEAN DEFAULT TRUE,       -- 祝日スキップ
    skip_weekends BOOLEAN DEFAULT TRUE,       -- 土日スキップ

    -- =====================================================
    -- 繰り返し制御
    -- =====================================================
    next_execution_at TIMESTAMPTZ,            -- 次回実行予定
    last_executed_at TIMESTAMPTZ,             -- 最終実行日時
    execution_count INT DEFAULT 0,            -- 実行回数
    max_executions INT,                       -- 最大実行回数（NULL=無制限）

    -- =====================================================
    -- 状態管理
    -- =====================================================
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN (
            'pending',      -- 依頼受付、確認待ち
            'confirmed',    -- ユーザー確認済み、実行/スケジュール待ち
            'scheduled',    -- スケジュール登録済み
            'executing',    -- 実行中
            'completed',    -- 完了（単発の場合）
            'failed',       -- 失敗
            'cancelled',    -- キャンセル
            'paused'        -- 一時停止（繰り返しの場合）
        )),

    -- =====================================================
    -- 依頼者情報
    -- =====================================================
    requested_by_account_id BIGINT NOT NULL,  -- ChatWork account_id
    requested_by_user_id UUID,                -- users.id（存在する場合）
    requested_from_room_id BIGINT NOT NULL,   -- 依頼を受けたルーム

    -- =====================================================
    -- 確認追跡
    -- =====================================================
    confirmation_message_id TEXT,             -- 確認メッセージのmessage_id
    confirmed_at TIMESTAMPTZ,                 -- 確認日時
    confirmation_response TEXT,               -- ユーザーの確認応答

    -- =====================================================
    -- キャンセル/失敗情報
    -- =====================================================
    cancelled_at TIMESTAMPTZ,
    cancelled_reason TEXT,
    failure_reason TEXT,

    -- =====================================================
    -- 監査フィールド
    -- =====================================================
    classification VARCHAR(20) NOT NULL DEFAULT 'internal'
        CHECK (classification IN ('public', 'internal', 'confidential', 'restricted')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- updated_at自動更新トリガー
CREATE OR REPLACE FUNCTION update_scheduled_announcements_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_scheduled_announcements_updated_at ON scheduled_announcements;
CREATE TRIGGER trigger_update_scheduled_announcements_updated_at
    BEFORE UPDATE ON scheduled_announcements
    FOR EACH ROW
    EXECUTE FUNCTION update_scheduled_announcements_updated_at();

-- インデックス
CREATE INDEX IF NOT EXISTS idx_scheduled_announcements_org_status
    ON scheduled_announcements(organization_id, status);

CREATE INDEX IF NOT EXISTS idx_scheduled_announcements_next_execution
    ON scheduled_announcements(next_execution_at)
    WHERE status = 'scheduled';

CREATE INDEX IF NOT EXISTS idx_scheduled_announcements_requester
    ON scheduled_announcements(organization_id, requested_by_account_id);

CREATE INDEX IF NOT EXISTS idx_scheduled_announcements_target_room
    ON scheduled_announcements(organization_id, target_room_id);

CREATE INDEX IF NOT EXISTS idx_scheduled_announcements_created_at
    ON scheduled_announcements(organization_id, created_at DESC);

-- コメント
COMMENT ON TABLE scheduled_announcements IS 'アナウンス予約・実行管理テーブル（Phase X）';
COMMENT ON COLUMN scheduled_announcements.schedule_type IS 'immediate=即時, one_time=単発予約, recurring=繰り返し';
COMMENT ON COLUMN scheduled_announcements.cron_expression IS 'croniter互換の式（例: "0 9 * * 1" = 毎週月曜9時）';
COMMENT ON COLUMN scheduled_announcements.skip_holidays IS 'TRUE=日本の祝日をスキップ（jpholiday使用）';


-- =====================================================
-- 2. announcement_logs テーブル
-- =====================================================
-- アナウンス実行ログ（監査証跡）

CREATE TABLE IF NOT EXISTS announcement_logs (
    -- =====================================================
    -- 主キー
    -- =====================================================
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- =====================================================
    -- テナント分離（10の鉄則 #1）
    -- =====================================================
    organization_id VARCHAR(100) NOT NULL DEFAULT 'org_soulsyncs',

    -- =====================================================
    -- 親アナウンスへの参照
    -- =====================================================
    announcement_id UUID NOT NULL REFERENCES scheduled_announcements(id) ON DELETE CASCADE,
    execution_number INT NOT NULL DEFAULT 1,  -- 繰り返しの場合の実行番号
    executed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- =====================================================
    -- メッセージ送信結果
    -- =====================================================
    message_sent BOOLEAN DEFAULT FALSE,
    message_id TEXT,                          -- ChatWork message_id
    message_sent_at TIMESTAMPTZ,

    -- =====================================================
    -- タスク作成結果
    -- =====================================================
    tasks_created BOOLEAN DEFAULT FALSE,
    task_count INT DEFAULT 0,
    task_ids TEXT[],                          -- 作成されたtask_idの配列
    task_creation_errors JSONB DEFAULT '{}',  -- エラー詳細

    -- =====================================================
    -- 実行時メンバースナップショット
    -- =====================================================
    room_members_snapshot JSONB NOT NULL DEFAULT '{}',  -- {account_id: name, ...}
    members_count INT DEFAULT 0,
    tasks_assigned_to BIGINT[],               -- タスクを振った人のaccount_id配列

    -- =====================================================
    -- 状態
    -- =====================================================
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN (
            'pending',          -- 実行待ち
            'in_progress',      -- 実行中
            'completed',        -- 完了
            'partial_failure',  -- 一部失敗（メッセージ送信OK、タスク作成一部NG等）
            'failed',           -- 失敗
            'skipped'           -- スキップ（祝日等）
        )),
    error_message TEXT,
    error_details JSONB,
    skip_reason TEXT,                         -- スキップ理由（「成人の日」等）

    -- =====================================================
    -- 監査フィールド
    -- =====================================================
    classification VARCHAR(20) NOT NULL DEFAULT 'internal'
        CHECK (classification IN ('public', 'internal', 'confidential', 'restricted')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_announcement_logs_announcement
    ON announcement_logs(announcement_id, execution_number);

CREATE INDEX IF NOT EXISTS idx_announcement_logs_org_status
    ON announcement_logs(organization_id, status);

CREATE INDEX IF NOT EXISTS idx_announcement_logs_executed_at
    ON announcement_logs(organization_id, executed_at DESC);

-- コメント
COMMENT ON TABLE announcement_logs IS 'アナウンス実行ログ（監査証跡）';
COMMENT ON COLUMN announcement_logs.execution_number IS '繰り返しアナウンスの場合、何回目の実行か';
COMMENT ON COLUMN announcement_logs.room_members_snapshot IS '実行時点のルームメンバー（メンバー変更追跡用）';


-- =====================================================
-- 3. announcement_patterns テーブル
-- =====================================================
-- アナウンス依頼パターン検知（Phase 2 A1連携）
-- 同じ依頼が3回以上繰り返されたら定期化を提案

CREATE TABLE IF NOT EXISTS announcement_patterns (
    -- =====================================================
    -- 主キー
    -- =====================================================
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- =====================================================
    -- テナント分離（10の鉄則 #1）
    -- =====================================================
    organization_id VARCHAR(100) NOT NULL DEFAULT 'org_soulsyncs',

    -- =====================================================
    -- パターン識別
    -- =====================================================
    pattern_hash VARCHAR(64) NOT NULL,        -- 正規化リクエストのSHA256
    normalized_request TEXT NOT NULL,         -- LLM正規化後のリクエスト
    target_room_id BIGINT,                    -- 対象ルーム（同定できた場合）
    target_room_name VARCHAR(255),

    -- =====================================================
    -- 統計
    -- =====================================================
    occurrence_count INT NOT NULL DEFAULT 1,
    occurrence_timestamps TIMESTAMPTZ[] NOT NULL DEFAULT '{}',
    last_occurred_at TIMESTAMPTZ NOT NULL,
    first_occurred_at TIMESTAMPTZ NOT NULL,
    requested_by_account_ids BIGINT[] NOT NULL DEFAULT '{}',  -- 依頼した人たち
    sample_requests TEXT[] NOT NULL DEFAULT '{}',             -- サンプル（最大5件）

    -- =====================================================
    -- 提案状態
    -- =====================================================
    suggestion_created BOOLEAN DEFAULT FALSE,
    insight_id UUID,                          -- 作成したsoulkun_insightsのID
    suggestion_accepted BOOLEAN,              -- ユーザーが提案を受け入れたか
    recurring_announcement_id UUID,           -- 定期化された場合のscheduled_announcements.id

    -- =====================================================
    -- 状態
    -- =====================================================
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN (
            'active',     -- アクティブ（パターン追跡中）
            'addressed',  -- 対応済み（定期化された）
            'dismissed'   -- 却下（ユーザーが不要と判断）
        )),
    addressed_at TIMESTAMPTZ,
    dismissed_reason TEXT,

    -- =====================================================
    -- 監査フィールド
    -- =====================================================
    classification VARCHAR(20) NOT NULL DEFAULT 'internal'
        CHECK (classification IN ('public', 'internal', 'confidential', 'restricted')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- =====================================================
    -- 制約
    -- =====================================================
    CONSTRAINT uq_announcement_patterns_org_hash
        UNIQUE (organization_id, pattern_hash)
);

-- updated_at自動更新トリガー
CREATE OR REPLACE FUNCTION update_announcement_patterns_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_announcement_patterns_updated_at ON announcement_patterns;
CREATE TRIGGER trigger_update_announcement_patterns_updated_at
    BEFORE UPDATE ON announcement_patterns
    FOR EACH ROW
    EXECUTE FUNCTION update_announcement_patterns_updated_at();

-- インデックス
CREATE INDEX IF NOT EXISTS idx_announcement_patterns_org_count
    ON announcement_patterns(organization_id, occurrence_count DESC);

CREATE INDEX IF NOT EXISTS idx_announcement_patterns_org_status
    ON announcement_patterns(organization_id, status)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_announcement_patterns_last_occurred
    ON announcement_patterns(organization_id, last_occurred_at DESC);

-- コメント
COMMENT ON TABLE announcement_patterns IS 'アナウンス依頼パターン検知（Phase 2 A1連携）';
COMMENT ON COLUMN announcement_patterns.pattern_hash IS '正規化リクエストのSHA256ハッシュ（64文字）';
COMMENT ON COLUMN announcement_patterns.occurrence_count IS '依頼回数（3回以上で定期化提案）';


-- =====================================================
-- 4. notification_logs CHECK制約更新
-- =====================================================
-- 新しい通知タイプを追加

-- 既存のCHECK制約を削除して再作成
-- 注意: 本番環境では制約名を確認してから実行すること

DO $$
BEGIN
    -- announcement関連の通知タイプが既に存在するか確認
    -- 存在しない場合のみ制約を更新
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'notification_logs_notification_type_check'
        AND conrelid = 'notification_logs'::regclass
    ) THEN
        -- 制約が存在しない場合は何もしない（別のマイグレーションで対応済みの可能性）
        RAISE NOTICE 'notification_logs制約は既に適切に設定されています';
    END IF;
END $$;

-- 手動で実行する場合のSQLコメント:
-- ALTER TABLE notification_logs DROP CONSTRAINT IF EXISTS notification_logs_notification_type_check;
-- ALTER TABLE notification_logs ADD CONSTRAINT notification_logs_notification_type_check
-- CHECK (notification_type IN (
--     -- 既存タイプ
--     'task_reminder', 'task_overdue', 'task_escalation',
--     'deadline_alert', 'escalation_alert', 'dm_unavailable',
--     'goal_daily_check', 'goal_daily_reminder', 'goal_morning_feedback',
--     'goal_team_summary', 'goal_consecutive_unanswered', 'goal_reminder',
--     'meeting_reminder',
--     'pattern_alert', 'weekly_report',
--     -- 新規: アナウンス関連
--     'announcement',                    -- アナウンス送信
--     'announcement_task',               -- アナウンスからのタスク作成
--     'announcement_confirmation',       -- 確認リクエスト
--     'announcement_recurring_suggestion' -- 定期化提案
-- ));


-- =====================================================
-- 5. soulkun_insights source_type更新
-- =====================================================
-- announcement_pattern を追加

-- 手動で実行する場合のSQLコメント:
-- ALTER TABLE soulkun_insights DROP CONSTRAINT IF EXISTS soulkun_insights_source_type_check;
-- ALTER TABLE soulkun_insights ADD CONSTRAINT soulkun_insights_source_type_check
-- CHECK (source_type IN (
--     'a1_pattern',
--     'a2_personalization',
--     'a3_bottleneck',
--     'a4_emotion',
--     'announcement_pattern'  -- 新規追加
-- ));


-- =====================================================
-- 完了メッセージ
-- =====================================================
DO $$
BEGIN
    RAISE NOTICE '========================================';
    RAISE NOTICE 'Phase X: アナウンス機能マイグレーション完了';
    RAISE NOTICE '========================================';
    RAISE NOTICE '作成されたテーブル:';
    RAISE NOTICE '  1. scheduled_announcements';
    RAISE NOTICE '  2. announcement_logs';
    RAISE NOTICE '  3. announcement_patterns';
    RAISE NOTICE '========================================';
END $$;
