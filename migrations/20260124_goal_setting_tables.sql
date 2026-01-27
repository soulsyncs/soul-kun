-- ============================================================
-- Phase 2.5 v1.6: 目標設定対話機能のテーブル作成
-- 作成日: 2026-01-24
-- ============================================================

-- ============================================================
-- 1. goal_setting_sessions（目標設定セッション管理）
-- ============================================================

CREATE TABLE IF NOT EXISTS goal_setting_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id),

    -- セッション状態
    status VARCHAR(20) NOT NULL DEFAULT 'in_progress',
    -- 'in_progress' | 'completed' | 'abandoned'
    current_step VARCHAR(20) NOT NULL DEFAULT 'intro',
    -- 'intro' | 'why' | 'what' | 'how' | 'complete'

    -- 回答の一時保存
    why_answer TEXT,      -- Step 1の回答
    what_answer TEXT,     -- Step 2の回答
    how_answer TEXT,      -- Step 3の回答

    -- 完了時に作成されたgoal_id
    goal_id UUID REFERENCES goals(id),

    -- ChatWorkルーム（対話が行われているルーム）
    chatwork_room_id VARCHAR(50),

    -- タイミング
    started_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    last_activity_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- セッションタイムアウト（24時間で期限切れ）
    expires_at TIMESTAMPTZ DEFAULT (CURRENT_TIMESTAMP + INTERVAL '24 hours'),

    -- メタデータ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 制約
    CONSTRAINT check_session_status CHECK (status IN ('in_progress', 'completed', 'abandoned')),
    CONSTRAINT check_session_step CHECK (current_step IN ('intro', 'why', 'what', 'how', 'complete'))
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_goal_sessions_org ON goal_setting_sessions(organization_id);
CREATE INDEX IF NOT EXISTS idx_goal_sessions_user ON goal_setting_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_goal_sessions_status ON goal_setting_sessions(status)
    WHERE status = 'in_progress';
CREATE INDEX IF NOT EXISTS idx_goal_sessions_room ON goal_setting_sessions(chatwork_room_id, user_id)
    WHERE status = 'in_progress';
CREATE INDEX IF NOT EXISTS idx_goal_sessions_expires ON goal_setting_sessions(expires_at)
    WHERE status = 'in_progress';

-- コメント
COMMENT ON TABLE goal_setting_sessions IS '目標設定セッション管理（Phase 2.5 v1.6）。一問一答の途中状態を保持';
COMMENT ON COLUMN goal_setting_sessions.expires_at IS '24時間でタイムアウト。期限切れセッションは abandoned に更新';
COMMENT ON COLUMN goal_setting_sessions.current_step IS '現在のステップ: intro=導入, why=WHY, what=WHAT, how=HOW, complete=完了';


-- ============================================================
-- 2. goal_setting_patterns（パターンマスタ）
-- ※ goal_setting_logs より先に作成（外部キー参照のため）
-- ============================================================

CREATE TABLE IF NOT EXISTS goal_setting_patterns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- パターン定義
    pattern_code VARCHAR(50) UNIQUE NOT NULL,
    -- 'ok', 'ng_career', 'ng_abstract', 'ng_other_blame', ...
    pattern_name VARCHAR(100) NOT NULL,
    pattern_category VARCHAR(20) NOT NULL,
    -- 'ok' | 'ng' | 'warning'

    -- 対象ステップ
    applicable_steps TEXT[],
    -- ['why', 'what', 'how'] など

    -- 検出条件（AI評価用のヒント）
    detection_keywords TEXT[],
    -- ['転職', '副業', '市場価値'] など
    detection_description TEXT,
    -- 「転職や副業に関する発言」など

    -- 推奨対応
    recommended_response TEXT,
    -- 推奨の回答テンプレート
    response_strategy VARCHAR(50),
    -- 'proceed' | 'redirect_to_company' | 'ask_for_specificity' | 'empathize_then_self_focus' ...

    -- 統計（定期更新）
    occurrence_count INT DEFAULT 0,
    success_rate DECIMAL(5, 2),
    -- このパターン後の目標設定完了率
    last_occurred_at TIMESTAMPTZ,

    -- メタデータ
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 制約
    CONSTRAINT check_pattern_category CHECK (pattern_category IN ('ok', 'ng', 'warning'))
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_patterns_code ON goal_setting_patterns(pattern_code);
CREATE INDEX IF NOT EXISTS idx_patterns_category ON goal_setting_patterns(pattern_category);
CREATE INDEX IF NOT EXISTS idx_patterns_active ON goal_setting_patterns(is_active) WHERE is_active = TRUE;

-- コメント
COMMENT ON TABLE goal_setting_patterns IS '目標設定パターンマスタ（Phase 2.5 v1.6）。検出パターンと推奨対応を管理';
COMMENT ON COLUMN goal_setting_patterns.response_strategy IS '対応戦略コード。実装側でこのコードに応じた対応を行う';


-- ============================================================
-- 3. 初期パターンデータ投入
-- ============================================================

INSERT INTO goal_setting_patterns (pattern_code, pattern_name, pattern_category, applicable_steps, detection_keywords, detection_description, response_strategy)
VALUES
    ('ok', 'OK（適切）', 'ok', ARRAY['why', 'what', 'how'], NULL, '適切な回答', 'proceed'),
    ('exit', '終了・キャンセル', 'ok', ARRAY['why', 'what', 'how'], ARRAY['やめる', 'やめたい', 'キャンセル', '終了', '中止', 'やめて', 'やめます', 'やっぱりいいや'], 'ユーザーが目標設定セッションの終了を希望', 'accept'),
    ('ng_abstract', '抽象的すぎる', 'ng', ARRAY['why', 'what', 'how'], ARRAY['成長', '頑張る', '良くなりたい', '向上', 'スキルアップ'], '具体性に欠ける発言', 'ask_for_specificity'),
    ('ng_career', '転職・副業志向', 'ng', ARRAY['why'], ARRAY['転職', '副業', '市場価値', 'どこでも通用', '独立', 'フリーランス', '起業'], '会社外でのキャリアを示唆', 'redirect_to_company'),
    ('ng_other_blame', '他責思考', 'ng', ARRAY['why', 'what'], ARRAY['上司が', '会社が', '環境が', 'せいで', 'のせい', '評価してくれない', 'わかってくれない'], '他者や環境のせいにする発言', 'empathize_then_self_focus'),
    ('ng_no_goal', '目標がない', 'ng', ARRAY['why'], ARRAY['特にない', '今のまま', '考えてない', 'わからない', 'ない'], '目標を持っていない', 'inspire_possibility'),
    ('ng_too_high', '目標が高すぎる', 'warning', ARRAY['what'], NULL, '達成不可能な目標設定', 'suggest_milestone'),
    ('ng_not_connected', '結果目標と繋がらない', 'ng', ARRAY['how'], NULL, '行動が結果目標と繋がっていない', 'connect_to_result'),
    ('ng_mental_health', 'メンタルヘルス懸念', 'warning', ARRAY['why', 'what', 'how'], ARRAY['疲れた', 'しんどい', '辛い', 'やる気が出ない', '限界', '無理', '死にたい', '辞めたい'], '精神的な不調を示唆', 'empathize_and_suggest_human'),
    ('ng_private_only', 'プライベート目標のみ', 'warning', ARRAY['why', 'what'], ARRAY['ダイエット', '趣味', '旅行', '痩せたい', '筋トレ', '資格'], '仕事と関係ない目標のみ', 'add_work_goal'),
    ('unknown', '未分類', 'warning', ARRAY['why', 'what', 'how'], NULL, '既存パターンに該当しない', 'ask_for_clarification')
ON CONFLICT (pattern_code) DO NOTHING;


-- ============================================================
-- 4. goal_setting_logs（目標設定対話ログ）
-- ============================================================

CREATE TABLE IF NOT EXISTS goal_setting_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- セッション管理
    session_id UUID NOT NULL REFERENCES goal_setting_sessions(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id),

    -- ステップ管理
    step VARCHAR(20) NOT NULL,
    -- 'intro' | 'why' | 'what' | 'how' | 'complete'
    step_attempt INT NOT NULL DEFAULT 1,
    -- リトライ回数（1=初回、2=1回目の再質問後...）

    -- 対話内容
    user_message TEXT,          -- ユーザーの発言（原文）
    ai_response TEXT,           -- ソウルくんの回答

    -- AI評価
    detected_pattern VARCHAR(50) REFERENCES goal_setting_patterns(pattern_code),
    -- 'ok' | 'ng_career' | 'ng_abstract' | ...
    evaluation_result JSONB,
    -- {
    --   "specificity_score": 0.8,
    --   "direction_score": 0.9,
    --   "connection_score": 0.7,
    --   "issues": ["abstract", "no_deadline"],
    --   "recommendation": "ask_for_deadline"
    -- }
    feedback_given BOOLEAN DEFAULT FALSE,
    -- フィードバック（再質問）を行ったか

    -- 結果
    result VARCHAR(20),
    -- 'accepted' | 'retry' | 'abandoned'

    -- 機密区分（目標設定の対話は internal 以上）
    classification VARCHAR(20) NOT NULL DEFAULT 'internal',

    -- メタデータ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 制約
    CONSTRAINT check_log_step CHECK (step IN ('intro', 'why', 'what', 'how', 'complete')),
    CONSTRAINT check_log_result CHECK (result IS NULL OR result IN ('accepted', 'retry', 'abandoned')),
    CONSTRAINT check_log_classification CHECK (classification IN ('public', 'internal', 'confidential', 'restricted'))
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_goal_logs_org ON goal_setting_logs(organization_id);
CREATE INDEX IF NOT EXISTS idx_goal_logs_session ON goal_setting_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_goal_logs_user ON goal_setting_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_goal_logs_pattern ON goal_setting_logs(detected_pattern);
CREATE INDEX IF NOT EXISTS idx_goal_logs_created ON goal_setting_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_goal_logs_result ON goal_setting_logs(result);

-- コメント
COMMENT ON TABLE goal_setting_logs IS '目標設定対話ログ（Phase 2.5 v1.6）。継続改善のためのデータ蓄積用';
COMMENT ON COLUMN goal_setting_logs.detected_pattern IS '検出されたパターンコード（goal_setting_patternsを参照）';
COMMENT ON COLUMN goal_setting_logs.evaluation_result IS 'AI評価の詳細（JSONBで拡張可能）';
COMMENT ON COLUMN goal_setting_logs.step_attempt IS 'このステップの試行回数。1=初回、2=1回目の再質問後';


-- ============================================================
-- 5. 分析用ビュー
-- ============================================================

-- パターン別の発生件数と完了率ビュー
CREATE OR REPLACE VIEW goal_setting_pattern_stats AS
SELECT
    gsl.detected_pattern,
    gsp.pattern_name,
    gsp.pattern_category,
    COUNT(*) as occurrence_count,
    COUNT(CASE WHEN gss.status = 'completed' THEN 1 END) as completed_count,
    ROUND(
        CASE
            WHEN COUNT(*) > 0 THEN
                COUNT(CASE WHEN gss.status = 'completed' THEN 1 END)::DECIMAL / COUNT(*)::DECIMAL * 100
            ELSE 0
        END,
        1
    ) as completion_rate_percent
FROM goal_setting_logs gsl
JOIN goal_setting_sessions gss ON gsl.session_id = gss.id
LEFT JOIN goal_setting_patterns gsp ON gsl.detected_pattern = gsp.pattern_code
GROUP BY gsl.detected_pattern, gsp.pattern_name, gsp.pattern_category;

COMMENT ON VIEW goal_setting_pattern_stats IS 'パターン別の発生件数と目標設定完了率の集計ビュー';


-- ============================================================
-- 6. パターン統計の自動更新関数
-- ============================================================

CREATE OR REPLACE FUNCTION update_pattern_statistics()
RETURNS TRIGGER AS $$
BEGIN
    -- パターンの発生回数と最終発生日を更新
    UPDATE goal_setting_patterns
    SET
        occurrence_count = occurrence_count + 1,
        last_occurred_at = CURRENT_TIMESTAMP,
        updated_at = CURRENT_TIMESTAMP
    WHERE pattern_code = NEW.detected_pattern;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- トリガー作成
DROP TRIGGER IF EXISTS trigger_update_pattern_stats ON goal_setting_logs;
CREATE TRIGGER trigger_update_pattern_stats
    AFTER INSERT ON goal_setting_logs
    FOR EACH ROW
    WHEN (NEW.detected_pattern IS NOT NULL)
    EXECUTE FUNCTION update_pattern_statistics();


-- ============================================================
-- 7. 期限切れセッションの自動更新関数
-- ============================================================

CREATE OR REPLACE FUNCTION expire_old_sessions()
RETURNS INTEGER AS $$
DECLARE
    updated_count INTEGER;
BEGIN
    UPDATE goal_setting_sessions
    SET
        status = 'abandoned',
        updated_at = CURRENT_TIMESTAMP
    WHERE status = 'in_progress'
      AND expires_at < CURRENT_TIMESTAMP;

    GET DIAGNOSTICS updated_count = ROW_COUNT;
    RETURN updated_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION expire_old_sessions() IS '期限切れの目標設定セッションを abandoned に更新。定期的に実行する';


-- ============================================================
-- 完了メッセージ
-- ============================================================

DO $$
BEGIN
    RAISE NOTICE '✅ Phase 2.5 v1.6 テーブル作成完了';
    RAISE NOTICE '  - goal_setting_sessions: 目標設定セッション管理';
    RAISE NOTICE '  - goal_setting_patterns: パターンマスタ（初期データ投入済み）';
    RAISE NOTICE '  - goal_setting_logs: 対話ログ';
    RAISE NOTICE '  - goal_setting_pattern_stats: 分析用ビュー';
END $$;
