-- ============================================================
-- Phase C: 脳アーキテクチャ - 状態管理統一
-- 作成日: 2026-01-26
-- 作成者: Claude Code
-- 設計書: docs/13_brain_architecture.md
-- ============================================================

-- ============================================================
-- brain_conversation_states（会話状態管理テーブル）
-- ============================================================

CREATE TABLE IF NOT EXISTS brain_conversation_states (
    -- 識別
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    room_id VARCHAR(50) NOT NULL,
    user_id VARCHAR(50) NOT NULL,  -- ChatWork account_id

    -- 状態
    state_type VARCHAR(50) NOT NULL,  -- 'normal', 'goal_setting', 'announcement', 'confirmation', 'task_pending', 'multi_action'
    state_step VARCHAR(50),            -- 'intro', 'why', 'what', 'how', 'confirm', 'pending_room' etc.
    state_data JSONB DEFAULT '{}',     -- 状態固有のデータ

    -- 元の機能への参照
    reference_type VARCHAR(50),        -- 'goal_session', 'announcement', 'task', 'knowledge'
    reference_id UUID,                 -- 参照先のID

    -- タイムアウト
    expires_at TIMESTAMPTZ NOT NULL,   -- この時刻を過ぎたら自動クリア
    timeout_minutes INT DEFAULT 30,

    -- 監査
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- ユニーク制約（1ユーザー1ルームに1状態）
    CONSTRAINT unique_user_room_state UNIQUE(organization_id, room_id, user_id),

    -- 状態タイプの制約
    CONSTRAINT check_brain_state_type CHECK (state_type IN (
        'normal',           -- 通常状態（状態なし）
        'goal_setting',     -- 目標設定対話中
        'announcement',     -- アナウンス確認中
        'confirmation',     -- 確認待ち
        'task_pending',     -- タスク作成待ち
        'multi_action'      -- 複数アクション実行中
    )),

    -- 参照タイプの制約
    CONSTRAINT check_brain_reference_type CHECK (
        reference_type IS NULL OR reference_type IN (
            'goal_session',     -- goal_setting_sessionsへの参照
            'announcement',     -- scheduled_announcementsへの参照
            'task',             -- タスク作成待ち
            'knowledge',        -- ナレッジ確認
            'memory'            -- 人物記憶確認
        )
    ),

    -- タイムアウトの制約
    CONSTRAINT check_brain_timeout CHECK (timeout_minutes > 0 AND timeout_minutes <= 1440)
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_brain_states_user ON brain_conversation_states(organization_id, room_id, user_id);
CREATE INDEX IF NOT EXISTS idx_brain_states_expires ON brain_conversation_states(expires_at) WHERE state_type != 'normal';
CREATE INDEX IF NOT EXISTS idx_brain_states_ref ON brain_conversation_states(reference_type, reference_id) WHERE reference_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_brain_states_type ON brain_conversation_states(state_type) WHERE state_type != 'normal';

-- コメント
COMMENT ON TABLE brain_conversation_states IS 'Phase C: 脳アーキテクチャの会話状態管理。マルチステップ対話を統一管理';
COMMENT ON COLUMN brain_conversation_states.state_type IS '状態タイプ: normal（通常）, goal_setting（目標設定中）, announcement（アナウンス確認中）, confirmation（確認待ち）, task_pending（タスク作成待ち）, multi_action（複数アクション中）';
COMMENT ON COLUMN brain_conversation_states.state_step IS '状態内のステップ。goal_setting: intro/why/what/how, announcement: pending/pending_room/confirmed等';
COMMENT ON COLUMN brain_conversation_states.state_data IS '状態固有データ（JSON）: pending_action, pending_params, confirmation_options等';
COMMENT ON COLUMN brain_conversation_states.reference_type IS '参照先タイプ: goal_session, announcement, task等';
COMMENT ON COLUMN brain_conversation_states.reference_id IS '参照先ID（外部テーブルのUUID）';
COMMENT ON COLUMN brain_conversation_states.expires_at IS 'タイムアウト時刻。これを過ぎると自動クリア';
COMMENT ON COLUMN brain_conversation_states.timeout_minutes IS 'タイムアウト時間（分）。デフォルト30分';

-- updated_at自動更新トリガー
CREATE OR REPLACE FUNCTION update_brain_states_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_brain_states_updated_at ON brain_conversation_states;
CREATE TRIGGER trigger_brain_states_updated_at
    BEFORE UPDATE ON brain_conversation_states
    FOR EACH ROW
    EXECUTE FUNCTION update_brain_states_updated_at();

-- ============================================================
-- brain_decision_logs（脳の判断ログ - 監査・分析用）
-- ============================================================

CREATE TABLE IF NOT EXISTS brain_decision_logs (
    -- 識別
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- 入力情報
    room_id VARCHAR(50) NOT NULL,
    user_id VARCHAR(50) NOT NULL,
    user_message TEXT NOT NULL,

    -- 理解層の結果
    understanding_result JSONB NOT NULL,  -- 推論した意図、エンティティ等
    understanding_confidence DECIMAL(4,3),

    -- 判断層の結果
    selected_action VARCHAR(100) NOT NULL,
    action_params JSONB,
    decision_confidence DECIMAL(4,3),
    decision_reasoning TEXT,

    -- 確認モード
    required_confirmation BOOLEAN DEFAULT FALSE,
    confirmation_question TEXT,

    -- 実行結果
    execution_success BOOLEAN,
    execution_error TEXT,

    -- パフォーマンス
    understanding_time_ms INT,
    decision_time_ms INT,
    execution_time_ms INT,
    total_time_ms INT,

    -- 監査
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 機密区分
    classification VARCHAR(20) DEFAULT 'internal',

    -- 制約
    CONSTRAINT check_brain_log_classification CHECK (classification IN ('public', 'internal', 'confidential', 'restricted')),
    CONSTRAINT check_brain_log_confidence CHECK (
        (understanding_confidence IS NULL OR (understanding_confidence >= 0 AND understanding_confidence <= 1)) AND
        (decision_confidence IS NULL OR (decision_confidence >= 0 AND decision_confidence <= 1))
    )
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_brain_decision_org ON brain_decision_logs(organization_id);
CREATE INDEX IF NOT EXISTS idx_brain_decision_user ON brain_decision_logs(organization_id, user_id);
CREATE INDEX IF NOT EXISTS idx_brain_decision_action ON brain_decision_logs(selected_action);
CREATE INDEX IF NOT EXISTS idx_brain_decision_created ON brain_decision_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_brain_decision_low_confidence ON brain_decision_logs(decision_confidence)
    WHERE decision_confidence < 0.7;
CREATE INDEX IF NOT EXISTS idx_brain_decision_errors ON brain_decision_logs(created_at DESC)
    WHERE execution_success = FALSE;

-- コメント
COMMENT ON TABLE brain_decision_logs IS 'Phase C: 脳の判断ログ。監査・分析・学習に使用';
COMMENT ON COLUMN brain_decision_logs.understanding_result IS '理解層の出力（JSON）: intent, entities, resolved_ambiguities等';
COMMENT ON COLUMN brain_decision_logs.understanding_confidence IS '意図推論の確信度 0.0-1.0';
COMMENT ON COLUMN brain_decision_logs.decision_confidence IS '判断の確信度 0.0-1.0';
COMMENT ON COLUMN brain_decision_logs.decision_reasoning IS '判断理由（デバッグ用）';
COMMENT ON COLUMN brain_decision_logs.required_confirmation IS '確認モードを発動したか';
COMMENT ON COLUMN brain_decision_logs.total_time_ms IS '処理全体の時間（ミリ秒）';

-- ============================================================
-- brain_state_history（状態遷移履歴 - 分析用）
-- ============================================================

CREATE TABLE IF NOT EXISTS brain_state_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    room_id VARCHAR(50) NOT NULL,
    user_id VARCHAR(50) NOT NULL,

    -- 遷移情報
    from_state_type VARCHAR(50),
    from_state_step VARCHAR(50),
    to_state_type VARCHAR(50) NOT NULL,
    to_state_step VARCHAR(50),

    -- 遷移理由
    transition_reason VARCHAR(50) NOT NULL,  -- 'user_action', 'user_cancel', 'timeout', 'completed', 'error'

    -- 参照
    state_id UUID REFERENCES brain_conversation_states(id) ON DELETE SET NULL,

    -- 監査
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 制約
    CONSTRAINT check_transition_reason CHECK (transition_reason IN (
        'user_action',      -- ユーザーのアクションによる遷移
        'user_cancel',      -- ユーザーによるキャンセル
        'timeout',          -- タイムアウトによる自動クリア
        'completed',        -- 正常完了
        'error',            -- エラーによるクリア
        'superseded'        -- 新しいセッションに置換
    ))
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_brain_history_org_user ON brain_state_history(organization_id, room_id, user_id);
CREATE INDEX IF NOT EXISTS idx_brain_history_created ON brain_state_history(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_brain_history_state_id ON brain_state_history(state_id) WHERE state_id IS NOT NULL;

-- コメント
COMMENT ON TABLE brain_state_history IS 'Phase C: 状態遷移履歴。分析・デバッグに使用';
COMMENT ON COLUMN brain_state_history.transition_reason IS '遷移理由: user_action, user_cancel, timeout, completed, error, superseded';

-- ============================================================
-- 期限切れ状態のクリーンアップ関数
-- ============================================================

CREATE OR REPLACE FUNCTION cleanup_expired_brain_states()
RETURNS INT AS $$
DECLARE
    deleted_count INT;
BEGIN
    -- 期限切れの状態を履歴に記録してから削除
    INSERT INTO brain_state_history (
        organization_id, room_id, user_id,
        from_state_type, from_state_step,
        to_state_type, to_state_step,
        transition_reason, state_id
    )
    SELECT
        organization_id, room_id, user_id,
        state_type, state_step,
        'normal', NULL,
        'timeout', id
    FROM brain_conversation_states
    WHERE expires_at < CURRENT_TIMESTAMP
      AND state_type != 'normal';

    -- 削除
    DELETE FROM brain_conversation_states
    WHERE expires_at < CURRENT_TIMESTAMP
      AND state_type != 'normal';

    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION cleanup_expired_brain_states IS '期限切れの脳状態をクリーンアップ。履歴に記録してから削除';

-- ============================================================
-- 完了メッセージ
-- ============================================================

DO $$
BEGIN
    RAISE NOTICE '✅ Phase C 脳アーキテクチャ - 状態管理テーブル作成完了';
    RAISE NOTICE '  - brain_conversation_states: 会話状態管理';
    RAISE NOTICE '  - brain_decision_logs: 判断ログ';
    RAISE NOTICE '  - brain_state_history: 状態遷移履歴';
    RAISE NOTICE '  - cleanup_expired_brain_states(): クリーンアップ関数';
END $$;
