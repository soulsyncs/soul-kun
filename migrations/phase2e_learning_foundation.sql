-- Phase 2E: 学習基盤（Learning Foundation）- DBマイグレーション
-- 設計書: docs/18_phase2e_learning_foundation.md v1.1.0
-- 作成日: 2026-01-27
--
-- 目的: ソウルくんが明示的なフィードバックから学習する基盤を構築
--
-- テーブル:
--   1. brain_learnings - 学習内容の保存
--   2. brain_learning_logs - 学習適用のログ
--
-- 依存:
--   - update_updated_at_column() 関数（既存）
--   - Phase 2D ceo_teachings テーブル（関連参照用）

BEGIN;

-- ============================================================================
-- 1. brain_learnings テーブル
-- ============================================================================
--
-- ソウルくんが学習した内容を保存するテーブル
--
-- 学習カテゴリ（8種）:
--   - alias: 別名・略称（「麻美」=「渡部麻美」）
--   - preference: 好み・やり方（「報告は箇条書きで」）
--   - fact: 事実・情報（「Aプロジェクトの担当は田中」）
--   - rule: ルール・決まり（「金曜は定例会議がある」）
--   - correction: 間違いの修正（「タスクの期限は翌営業日」）
--   - context: 文脈・背景（「今月は繁忙期」）
--   - relationship: 人間関係（「佐藤と鈴木は同期」）
--   - procedure: 手順・やり方（「請求書は経理に回す」）
--
-- スコープ（4種）:
--   - global: 全員に適用
--   - user: 特定ユーザーのみ
--   - room: 特定ルームのみ
--   - temporary: 期間限定
--
-- 権限レベル（4段階、Phase 2D連携）:
--   - ceo: CEOからの教え（最高優先度）
--   - manager: 管理職からの教え
--   - user: 一般ユーザーからの教え
--   - system: システム自動学習（Phase 2F）

CREATE TABLE IF NOT EXISTS brain_learnings (
    -- ============================================
    -- 識別情報
    -- ============================================
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,

    -- ============================================
    -- 学習カテゴリ
    -- ============================================
    category VARCHAR(50) NOT NULL,
    -- 'alias', 'preference', 'fact', 'rule', 'correction',
    -- 'context', 'relationship', 'procedure'

    -- ============================================
    -- トリガー（いつ適用するか）
    -- ============================================
    trigger_type VARCHAR(50) NOT NULL,
    -- 'keyword': キーワード一致
    -- 'pattern': 正規表現パターン
    -- 'context': 文脈条件
    -- 'always': 常に適用

    trigger_value TEXT NOT NULL,
    -- trigger_type='keyword': 「麻美」
    -- trigger_type='pattern': 「タスク.*期限」
    -- trigger_type='context': JSON形式の条件
    -- trigger_type='always': '*'

    -- ============================================
    -- 学習内容の詳細
    -- ============================================
    learned_content JSONB NOT NULL,
    -- カテゴリごとに異なる構造（設計書4.2参照）
    -- 例（alias）: {"type": "alias", "from": "麻美", "to": "渡部麻美"}
    -- 例（rule）: {"type": "rule", "condition": "急ぎの時", "action": "先にDMで連絡"}

    learned_content_version INTEGER NOT NULL DEFAULT 1,
    -- スキーマバージョン（将来のJSONB構造変更に備える）

    -- ============================================
    -- スコープ
    -- ============================================
    scope VARCHAR(50) NOT NULL DEFAULT 'global',
    -- 'global', 'user', 'room', 'temporary'

    scope_target_id VARCHAR(100),
    -- user scope: account_id
    -- room scope: room_id
    -- global/temporary: NULL

    -- ============================================
    -- 権限レベル（Phase 2D連携）
    -- ============================================
    authority_level VARCHAR(20) NOT NULL DEFAULT 'user',
    -- 'ceo', 'manager', 'user', 'system'
    -- 優先度: ceo > manager > user > system

    related_ceo_teaching_id UUID,
    -- Phase 2D ceo_teachings との関連
    -- CEO教えから派生した学習の場合に設定

    -- ============================================
    -- 有効期間（temporary scopeの場合）
    -- ============================================
    valid_from TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    valid_until TIMESTAMP WITH TIME ZONE,
    -- NULLの場合は無期限

    -- ============================================
    -- 教えた人
    -- ============================================
    taught_by_account_id VARCHAR(50) NOT NULL,
    taught_by_name VARCHAR(100),
    taught_in_room_id VARCHAR(50),

    -- ============================================
    -- 元のメッセージ
    -- ============================================
    source_message TEXT,
    -- 教えてくれた時のメッセージ全文

    source_context JSONB,
    -- 直前の会話など、文脈情報
    -- {
    --   "previous_messages": [...],
    --   "soulkun_last_action": "...",
    --   "error_occurred": true/false
    -- }

    -- ============================================
    -- 検出情報
    -- ============================================
    detection_pattern VARCHAR(100),
    -- 使用した検出パターン名
    -- 例: 'alias_definition', 'rule_definition', 'correction'

    detection_confidence DECIMAL(3,2),
    -- 検出の確信度（0.00-1.00）

    -- ============================================
    -- 適用状況
    -- ============================================
    is_active BOOLEAN DEFAULT true,
    -- falseの場合は適用されない（削除・上書きされた学習）

    applied_count INTEGER DEFAULT 0,
    -- この学習が適用された回数

    last_applied_at TIMESTAMP WITH TIME ZONE,
    -- 最後に適用された日時

    success_count INTEGER DEFAULT 0,
    -- 適用が成功した回数（ユーザーからの肯定的フィードバック）

    failure_count INTEGER DEFAULT 0,
    -- 適用が失敗した回数（ユーザーからの否定的フィードバック）

    -- ============================================
    -- 上書き情報（学習の修正・更新用）
    -- ============================================
    supersedes_id UUID REFERENCES brain_learnings(id),
    -- この学習が上書きした学習のID

    superseded_by_id UUID REFERENCES brain_learnings(id),
    -- この学習を上書きした学習のID

    -- ============================================
    -- Phase 2G準備: 知識グラフ
    -- ============================================
    related_learning_ids UUID[],
    -- 関連する学習のID配列
    -- 例: 「麻美」→「渡部麻美」と「渡部麻美」→「経理担当」を関連付け

    relationship_type VARCHAR(50),
    -- 関連の種類
    -- 'implies': 含意（A→B）
    -- 'contradicts': 矛盾（A⇔B）
    -- 'extends': 拡張（AはBの詳細）
    -- 'specializes': 特殊化（AはBの特殊ケース）

    confidence_decay_rate DECIMAL(5,4) DEFAULT 0.0001,
    -- 時間経過による確信度低下率（1日あたり）
    -- 0.0001 = 1日で0.01%低下

    -- ============================================
    -- Phase 2H準備: 自己認識
    -- ============================================
    unknown_pattern TEXT,
    -- 「分からなかった」パターンを記録
    -- Phase 2Hで「〇〇については詳しくない」と自己認識するため

    clarification_count INTEGER DEFAULT 0,
    -- この学習に関して確認を求めた回数
    -- 多い場合は曖昧な知識として認識

    -- ============================================
    -- Phase 2N準備: 自己最適化
    -- ============================================
    effectiveness_score DECIMAL(3,2)
        CHECK (effectiveness_score IS NULL OR
               (effectiveness_score >= 0.00 AND effectiveness_score <= 1.00)),
    -- 学習の効果スコア（0.00-1.00）
    -- success_count / (success_count + failure_count) を基に計算

    last_effectiveness_check TIMESTAMP WITH TIME ZONE,
    -- 最終効果測定日時

    decision_impact VARCHAR(20),
    -- 判断への影響度
    -- 'positive': 良い判断につながった
    -- 'negative': 悪い判断につながった
    -- 'neutral': 影響なし

    -- ============================================
    -- 監査
    -- ============================================
    classification VARCHAR(20) DEFAULT 'internal'
        CHECK (classification IN ('public', 'internal', 'confidential', 'restricted')),
    -- 機密区分
    -- 個人情報を含む学習は'confidential'

    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- brain_learnings インデックス
-- ============================================================================

-- 組織単位での検索（必須：10の鉄則#1）
CREATE INDEX IF NOT EXISTS idx_learnings_org
    ON brain_learnings(organization_id);

-- カテゴリ別検索
CREATE INDEX IF NOT EXISTS idx_learnings_category
    ON brain_learnings(organization_id, category);

-- トリガー検索（学習適用時の高速化）
CREATE INDEX IF NOT EXISTS idx_learnings_trigger
    ON brain_learnings(trigger_type, trigger_value);

-- スコープ別検索
CREATE INDEX IF NOT EXISTS idx_learnings_scope
    ON brain_learnings(organization_id, scope, scope_target_id);

-- アクティブな学習のみ検索（部分インデックス）
CREATE INDEX IF NOT EXISTS idx_learnings_active
    ON brain_learnings(organization_id, is_active)
    WHERE is_active = true;

-- 教えた人での検索
CREATE INDEX IF NOT EXISTS idx_learnings_taught_by
    ON brain_learnings(taught_by_account_id);

-- 更新日時順（最新の学習優先）
CREATE INDEX IF NOT EXISTS idx_learnings_updated
    ON brain_learnings(updated_at DESC);

-- 権限レベル別検索
CREATE INDEX IF NOT EXISTS idx_learnings_authority
    ON brain_learnings(authority_level);

-- CEO教えとの関連検索
CREATE INDEX IF NOT EXISTS idx_learnings_ceo_teaching
    ON brain_learnings(related_ceo_teaching_id)
    WHERE related_ceo_teaching_id IS NOT NULL;

-- Phase 2F準備: 暗黙フィードバック検出用
CREATE INDEX IF NOT EXISTS idx_learnings_implicit
    ON brain_learnings(detection_pattern)
    WHERE detection_pattern LIKE 'implicit_%';

-- Phase 2N準備: 効果測定用
CREATE INDEX IF NOT EXISTS idx_learnings_effectiveness
    ON brain_learnings(effectiveness_score DESC)
    WHERE effectiveness_score IS NOT NULL;

-- 矛盾検出用（同じtrigger_valueを持つアクティブな学習を高速検索）
CREATE INDEX IF NOT EXISTS idx_learnings_trigger_active
    ON brain_learnings(trigger_value, is_active)
    WHERE is_active = true;

-- JSONB全文検索用（GINインデックス）
CREATE INDEX IF NOT EXISTS idx_learnings_content
    ON brain_learnings USING GIN(learned_content jsonb_path_ops);

-- ============================================================================
-- brain_learnings CHECK制約
-- ============================================================================

-- カテゴリ制約
ALTER TABLE brain_learnings DROP CONSTRAINT IF EXISTS chk_learnings_category;
ALTER TABLE brain_learnings ADD CONSTRAINT chk_learnings_category
    CHECK (category IN (
        'alias',        -- 別名・略称
        'preference',   -- 好み・やり方
        'fact',         -- 事実・情報
        'rule',         -- ルール・決まり
        'correction',   -- 間違いの修正
        'context',      -- 文脈・背景
        'relationship', -- 人間関係
        'procedure'     -- 手順・やり方
    ));

-- スコープ制約
ALTER TABLE brain_learnings DROP CONSTRAINT IF EXISTS chk_learnings_scope;
ALTER TABLE brain_learnings ADD CONSTRAINT chk_learnings_scope
    CHECK (scope IN (
        'global',    -- 全員に適用
        'user',      -- 特定ユーザーのみ
        'room',      -- 特定ルームのみ
        'temporary'  -- 期間限定
    ));

-- トリガータイプ制約
ALTER TABLE brain_learnings DROP CONSTRAINT IF EXISTS chk_learnings_trigger_type;
ALTER TABLE brain_learnings ADD CONSTRAINT chk_learnings_trigger_type
    CHECK (trigger_type IN (
        'keyword',  -- キーワード一致
        'pattern',  -- 正規表現パターン
        'context',  -- 文脈条件
        'always'    -- 常に適用
    ));

-- 権限レベル制約
ALTER TABLE brain_learnings DROP CONSTRAINT IF EXISTS chk_learnings_authority_level;
ALTER TABLE brain_learnings ADD CONSTRAINT chk_learnings_authority_level
    CHECK (authority_level IN (
        'ceo',      -- CEO（最高優先度）
        'manager',  -- 管理職
        'user',     -- 一般ユーザー
        'system'    -- システム自動学習
    ));

-- 関係タイプ制約（Phase 2G準備）
ALTER TABLE brain_learnings DROP CONSTRAINT IF EXISTS chk_learnings_relationship_type;
ALTER TABLE brain_learnings ADD CONSTRAINT chk_learnings_relationship_type
    CHECK (relationship_type IS NULL OR relationship_type IN (
        'implies',      -- 含意
        'contradicts',  -- 矛盾
        'extends',      -- 拡張
        'specializes'   -- 特殊化
    ));

-- 判断影響度制約（Phase 2N準備）
ALTER TABLE brain_learnings DROP CONSTRAINT IF EXISTS chk_learnings_decision_impact;
ALTER TABLE brain_learnings ADD CONSTRAINT chk_learnings_decision_impact
    CHECK (decision_impact IS NULL OR decision_impact IN (
        'positive',  -- 良い判断につながった
        'negative',  -- 悪い判断につながった
        'neutral'    -- 影響なし
    ));

-- コメント
COMMENT ON TABLE brain_learnings IS 'ソウルくんの学習内容（Phase 2E）';
COMMENT ON COLUMN brain_learnings.category IS '学習カテゴリ（alias/preference/fact/rule/correction/context/relationship/procedure）';
COMMENT ON COLUMN brain_learnings.trigger_type IS '適用トリガーの種類（keyword/pattern/context/always）';
COMMENT ON COLUMN brain_learnings.authority_level IS '教えた人の権限レベル（ceo > manager > user > system）';
COMMENT ON COLUMN brain_learnings.related_ceo_teaching_id IS 'Phase 2D ceo_teachingsへの関連（CEO教えから派生した場合）';
COMMENT ON COLUMN brain_learnings.learned_content_version IS 'JSONBスキーマバージョン（将来の互換性用）';
COMMENT ON COLUMN brain_learnings.related_learning_ids IS 'Phase 2G準備: 関連する学習のID配列';
COMMENT ON COLUMN brain_learnings.effectiveness_score IS 'Phase 2N準備: 学習の効果スコア（0.00-1.00）';


-- ============================================================================
-- 2. brain_learning_logs テーブル
-- ============================================================================
--
-- 学習が適用された履歴を記録するテーブル
--
-- 目的:
--   - 学習の効果測定（成功/失敗の追跡）
--   - デバッグ・監査
--   - Phase 2Nでの自己最適化の基礎データ

CREATE TABLE IF NOT EXISTS brain_learning_logs (
    -- ============================================
    -- 識別情報
    -- ============================================
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    learning_id UUID NOT NULL REFERENCES brain_learnings(id) ON DELETE CASCADE,
    learning_version INTEGER NOT NULL DEFAULT 1,
    -- 適用時の学習バージョン（追跡用）

    -- ============================================
    -- 適用状況
    -- ============================================
    applied_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    applied_in_room_id VARCHAR(50),
    applied_for_account_id VARCHAR(50),
    -- 誰のメッセージに対して適用したか

    -- ============================================
    -- トリガー情報
    -- ============================================
    trigger_message TEXT,
    -- 適用のトリガーとなったメッセージ

    trigger_context JSONB,
    -- トリガー時の文脈情報

    context_hash VARCHAR(64),
    -- 文脈の一意識別子（SHA-256）
    -- 同じ文脈での重複適用を検出するため

    -- ============================================
    -- 結果
    -- ============================================
    was_successful BOOLEAN,
    -- 適用が成功したか（後続処理の結果）

    result_description TEXT,
    -- 適用結果の説明

    response_latency_ms INTEGER,
    -- 応答時間（ミリ秒）
    -- 性能分析用

    -- ============================================
    -- フィードバック（ユーザーからの反応）
    -- ============================================
    feedback_received BOOLEAN DEFAULT false,
    -- フィードバックを受け取ったか

    feedback_positive BOOLEAN,
    -- 肯定的フィードバックか（true=良い、false=悪い、NULL=未評価）

    feedback_message TEXT,
    -- フィードバックのメッセージ内容

    user_feedback_at TIMESTAMP WITH TIME ZONE,
    -- フィードバックを受け取った日時

    -- ============================================
    -- 監査
    -- ============================================
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- brain_learning_logs インデックス
-- ============================================================================

-- 学習単位での検索
CREATE INDEX IF NOT EXISTS idx_learning_logs_learning
    ON brain_learning_logs(learning_id);

-- 組織単位での検索
CREATE INDEX IF NOT EXISTS idx_learning_logs_org
    ON brain_learning_logs(organization_id);

-- 適用日時順
CREATE INDEX IF NOT EXISTS idx_learning_logs_applied
    ON brain_learning_logs(applied_at DESC);

-- フィードバックがあるログ検索
CREATE INDEX IF NOT EXISTS idx_learning_logs_feedback
    ON brain_learning_logs(learning_id, feedback_received)
    WHERE feedback_received = true;

-- 文脈ハッシュ検索（重複検出用）
CREATE INDEX IF NOT EXISTS idx_learning_logs_context_hash
    ON brain_learning_logs(context_hash);

-- アカウント別検索
CREATE INDEX IF NOT EXISTS idx_learning_logs_account
    ON brain_learning_logs(applied_for_account_id);

-- ルーム別検索
CREATE INDEX IF NOT EXISTS idx_learning_logs_room
    ON brain_learning_logs(applied_in_room_id);

-- コメント
COMMENT ON TABLE brain_learning_logs IS '学習適用ログ（Phase 2E）';
COMMENT ON COLUMN brain_learning_logs.context_hash IS '文脈の一意識別子（重複適用検出用）';
COMMENT ON COLUMN brain_learning_logs.response_latency_ms IS '応答時間（ミリ秒）- 性能分析用';
COMMENT ON COLUMN brain_learning_logs.feedback_positive IS 'フィードバックの評価（true=良い、false=悪い、NULL=未評価）';


-- ============================================================================
-- 3. トリガー
-- ============================================================================

-- brain_learnings の updated_at 自動更新
DROP TRIGGER IF EXISTS update_brain_learnings_updated_at ON brain_learnings;
CREATE TRIGGER update_brain_learnings_updated_at
    BEFORE UPDATE ON brain_learnings
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();


-- ============================================================================
-- 4. 初期データ（オプション）
-- ============================================================================

-- 現時点では初期データなし
-- 学習はユーザーとの対話を通じて蓄積される


COMMIT;

-- ============================================================================
-- マイグレーション情報
-- ============================================================================
--
-- 実行方法:
--   psql -h [host] -U [user] -d [database] -f migrations/phase2e_learning_foundation.sql
--
-- ロールバック方法:
--   DROP TABLE IF EXISTS brain_learning_logs CASCADE;
--   DROP TABLE IF EXISTS brain_learnings CASCADE;
--
-- 依存関係:
--   - update_updated_at_column() 関数が存在すること
--   - Phase 2D ceo_teachings テーブルが存在すること（related_ceo_teaching_id参照用）
--
-- 推定データ量（1年後）:
--   - brain_learnings: 約1,000件（1組織あたり）
--   - brain_learning_logs: 約10,000件（1組織あたり）
--   - 推定ストレージ: 約50MB（1組織あたり）
