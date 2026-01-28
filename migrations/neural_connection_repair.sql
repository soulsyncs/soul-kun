-- ============================================================
-- 神経接続修理（Neural Connection Repair）
-- 作成日: 2026-01-28
-- 作成者: Claude Code
-- 目的: 状態管理をbrain_conversation_statesに一本化
-- ============================================================
--
-- トランザクション構成:
--   BEGIN〜COMMIT で全操作を包む
--   - CREATE TABLE IF NOT EXISTS: 冪等（既存なら何もしない）
--   - CREATE INDEX IF NOT EXISTS: 冪等（既存なら何もしない）
--   - INSERT ... WHERE NOT EXISTS: 冪等（移行済みならスキップ）
--   途中失敗時は全てロールバックされ、中途半端な状態にならない
--
-- 注意: CREATE INDEX CONCURRENTLY は使用していないためTX内で安全
-- ============================================================

BEGIN;

-- ============================================================
-- Phase 1: brain_dialogue_logs テーブル作成
-- goal_setting_logsの移行先。全対話フローのログを統一管理
-- ============================================================

CREATE TABLE IF NOT EXISTS brain_dialogue_logs (
    -- 識別
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- ユーザー識別（ChatWork account_id を正とする）
    chatwork_account_id VARCHAR(50) NOT NULL,
    room_id VARCHAR(50) NOT NULL,

    -- 状態情報
    state_type VARCHAR(50) NOT NULL,   -- 'goal_setting', 'task_create', 'announcement_confirm' など
    state_step VARCHAR(50) NOT NULL,   -- 'why', 'what', 'how', 'confirm' など
    step_attempt INTEGER NOT NULL DEFAULT 1,

    -- 対話内容
    user_message TEXT,
    ai_response TEXT,

    -- 分析結果
    detected_pattern VARCHAR(100),
    evaluation_result JSONB,
    feedback_given BOOLEAN DEFAULT FALSE,
    result VARCHAR(50),   -- 'accepted', 'retry', 'timeout', 'cancelled' など

    -- 分類
    classification VARCHAR(20) NOT NULL DEFAULT 'internal',

    -- 監査
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 制約
    CONSTRAINT check_dialogue_state_type CHECK (state_type IN (
        'goal_setting',           -- 目標設定対話
        'task_create',            -- タスク作成対話
        'announcement_confirm',   -- アナウンス確認対話
        'memory_confirm',         -- 記憶確認対話
        'feedback',               -- フィードバック対話
        'other'                   -- その他
    )),
    CONSTRAINT check_dialogue_classification CHECK (classification IN (
        'public', 'internal', 'confidential', 'restricted'
    ))
);

-- インデックス（IF NOT EXISTSで冪等）
CREATE INDEX IF NOT EXISTS idx_brain_dialogue_logs_lookup
    ON brain_dialogue_logs(organization_id, chatwork_account_id, state_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_brain_dialogue_logs_room
    ON brain_dialogue_logs(room_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_brain_dialogue_logs_pattern
    ON brain_dialogue_logs(detected_pattern) WHERE detected_pattern IS NOT NULL;

-- コメント
COMMENT ON TABLE brain_dialogue_logs IS '神経接続修理: 全対話フローのログを統一管理。goal_setting_logsから移行';
COMMENT ON COLUMN brain_dialogue_logs.chatwork_account_id IS 'ChatWork account_id（user_idの正）';
COMMENT ON COLUMN brain_dialogue_logs.state_type IS '対話タイプ: goal_setting, task_create, announcement_confirm など';
COMMENT ON COLUMN brain_dialogue_logs.state_step IS '対話ステップ: why, what, how, confirm など';
COMMENT ON COLUMN brain_dialogue_logs.step_attempt IS 'ステップ内の試行回数（リトライ回数）';
COMMENT ON COLUMN brain_dialogue_logs.detected_pattern IS '検出されたパターン（曖昧、質問、困惑など）';
COMMENT ON COLUMN brain_dialogue_logs.evaluation_result IS '評価結果（JSON）';
COMMENT ON COLUMN brain_dialogue_logs.result IS '結果: accepted, retry, timeout, cancelled';

-- ============================================================
-- Phase 2: goal_setting_logs → brain_dialogue_logs データ移行
-- 既存データを保全しながら新テーブルに移行
-- ============================================================

-- 移行前のカウント確認（実行時に確認用）
-- SELECT COUNT(*) FROM goal_setting_logs;  -- 期待値: 30件

INSERT INTO brain_dialogue_logs (
    id,
    organization_id,
    chatwork_account_id,
    room_id,
    state_type,
    state_step,
    step_attempt,
    user_message,
    ai_response,
    detected_pattern,
    evaluation_result,
    feedback_given,
    result,
    classification,
    created_at
)
SELECT
    gsl.id,
    gsl.organization_id,
    u.chatwork_account_id,
    gss.chatwork_room_id,
    'goal_setting',
    gsl.step,
    gsl.step_attempt,
    gsl.user_message,
    gsl.ai_response,
    gsl.detected_pattern,
    gsl.evaluation_result,
    gsl.feedback_given,
    gsl.result,
    gsl.classification,
    gsl.created_at
FROM goal_setting_logs gsl
JOIN goal_setting_sessions gss ON gsl.session_id = gss.id
JOIN users u ON gss.user_id = u.id
WHERE NOT EXISTS (
    -- 冪等性: 既に移行済みのデータはスキップ
    SELECT 1 FROM brain_dialogue_logs bdl WHERE bdl.id = gsl.id
);

-- 移行後のカウント確認
-- SELECT COUNT(*) FROM brain_dialogue_logs WHERE state_type = 'goal_setting';

COMMIT;

-- ============================================================
-- Phase 3: goal_setting_sessions との互換性維持（移行期間中）
-- reference_type='goal_session' で既存セッションを参照可能にする
-- ============================================================

-- 注意: goal_setting_sessionsはまだDROPしない
-- goal_setting.pyの書き換え完了後、安定稼働を確認してからDROPする

-- ============================================================
-- ロールバック用SQL（必要時のみ実行）
-- ============================================================

-- DROP TABLE IF EXISTS brain_dialogue_logs;
-- 注意: goal_setting_logsは残っているため、データは失われない

-- ============================================================
-- 検証クエリ
-- ============================================================

-- 1. 移行件数確認
-- SELECT
--     (SELECT COUNT(*) FROM goal_setting_logs) as original_count,
--     (SELECT COUNT(*) FROM brain_dialogue_logs WHERE state_type = 'goal_setting') as migrated_count;

-- 2. データ整合性確認
-- SELECT gsl.id, gsl.step, bdl.state_step
-- FROM goal_setting_logs gsl
-- LEFT JOIN brain_dialogue_logs bdl ON gsl.id = bdl.id
-- WHERE bdl.id IS NULL;  -- 移行漏れがあればここに出る
