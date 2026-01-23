-- ================================================================
-- Phase 2 進化版 A1: パターン検出 - Cloud SQLマイグレーション
-- ================================================================
-- 作成日: 2026-01-23
-- 作成者: Claude Code（経営参謀・SE・PM）
-- バージョン: 1.0
-- 設計書: docs/06_phase2_a1_pattern_detection.md (v1.0)
--
-- このSQLはCloud SQLに接続して実行してください。
--
-- 接続方法:
--   gcloud sql connect soulkun-db --user=postgres
--
-- 注意事項:
--   1. 必ずバックアップを取ってから実行
--   2. STEP 1の事前確認を必ず実行
--   3. エラーが発生したらSTEP 10のロールバックを実行
--   4. Phase 2.5のマイグレーションが完了していることを確認
--
-- 依存関係:
--   - organizations テーブル（Phase 1）
--   - users テーブル（Phase 1）
--   - departments テーブル（Phase 3.5）
--   - notification_logs テーブル（Phase 1-B）
--
-- 変更内容:
--   - question_patterns テーブル新規作成
--   - soulkun_insights テーブル新規作成
--   - soulkun_weekly_reports テーブル新規作成
--   - notification_logs CHECK制約更新（notification_type追加）
-- ================================================================


-- ================================================================
-- STEP 0: トランザクション開始
-- ================================================================
-- 注意: Cloud SQLではBEGINでトランザクションを開始します
-- エラーが発生した場合はROLLBACKで全ての変更を取り消せます
BEGIN;


-- ================================================================
-- STEP 1: 事前確認（必須 - これらのクエリを先に実行して確認）
-- ================================================================

-- 1-1. 現在のデータベースとユーザーを確認
-- 期待値: database=soulkun_tasks, user=soulkun_user または postgres
SELECT
    current_database() as database,
    current_user as user,
    now() as executed_at,
    version() as postgres_version;

-- 1-2. 必要な依存テーブルの存在確認
-- 期待値: organizations, users, departments, notification_logs が全て存在
SELECT table_name,
       (SELECT COUNT(*) FROM information_schema.columns WHERE table_name = t.table_name) as column_count
FROM information_schema.tables t
WHERE table_schema = 'public'
  AND table_name IN ('organizations', 'users', 'departments', 'notification_logs')
ORDER BY table_name;

-- 1-3. question_patternsテーブルが既に存在するか確認（冪等性チェック）
-- 期待値: false（新規作成の場合）
SELECT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_name = 'question_patterns' AND table_schema = 'public'
) as question_patterns_exists;

-- 1-4. soulkun_insightsテーブルが既に存在するか確認
-- 期待値: false（新規作成の場合）
SELECT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_name = 'soulkun_insights' AND table_schema = 'public'
) as soulkun_insights_exists;

-- 1-5. soulkun_weekly_reportsテーブルが既に存在するか確認
-- 期待値: false（新規作成の場合）
SELECT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_name = 'soulkun_weekly_reports' AND table_schema = 'public'
) as soulkun_weekly_reports_exists;

-- 1-6. notification_logsテーブルの現在のCHECK制約を確認
-- 期待値: check_notification_type 制約が存在
SELECT
    conname as constraint_name,
    pg_get_constraintdef(oid) as constraint_definition
FROM pg_constraint
WHERE conrelid = 'notification_logs'::regclass
  AND contype = 'c';

-- 1-7. departmentsテーブルの構造確認（Phase 3.5との連携確認）
SELECT
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns
WHERE table_name = 'departments'
  AND table_schema = 'public'
ORDER BY ordinal_position;


-- ================================================================
-- STEP 2: question_patternsテーブル作成（質問パターン記録）
-- ================================================================
-- 目的: ソウルくんへの質問を分析し、頻出パターンを検出
-- 用途: 同じ質問が繰り返されていたら管理者に報告→ナレッジ化促進

-- 2-1. question_patternsテーブル作成
CREATE TABLE IF NOT EXISTS question_patterns (
    -- ================================================================
    -- 主キー
    -- ================================================================
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- ================================================================
    -- テナント分離（鉄則1: 全テーブルにorganization_id）
    -- ================================================================
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- ================================================================
    -- 部署フィルタ（Phase 3.5準拠）
    -- 部署ごとのパターン分析を可能にする
    -- NULLの場合は組織全体のパターン
    -- ================================================================
    department_id UUID REFERENCES departments(id) ON DELETE SET NULL,

    -- ================================================================
    -- パターンデータ
    -- ================================================================
    -- カテゴリ: 質問の分類
    -- - business_process: 業務手続き（週報、経費精算等）
    -- - company_rule: 社内ルール（有給、服装規定等）
    -- - technical: 技術質問（Slack、VPN等）
    -- - hr_related: 人事関連（評価、昇給等）
    -- - project: プロジェクト関連
    -- - other: その他
    question_category VARCHAR(50) NOT NULL,

    -- 類似度判定用ハッシュ（SHA256の先頭64文字）
    -- 同じ意味の質問を同一パターンとして認識するために使用
    question_hash VARCHAR(64) NOT NULL,

    -- 正規化された質問文（挨拶除去、表記ゆれ統一後）
    normalized_question TEXT NOT NULL,

    -- ================================================================
    -- 統計データ
    -- ================================================================
    -- 発生回数（この質問パターンが何回出現したか - 全期間）
    occurrence_count INT NOT NULL DEFAULT 1 CHECK (occurrence_count >= 1),

    -- 各発生日時のタイムスタンプ配列（Codex MEDIUM2指摘対応）
    -- ウィンドウ期間（デフォルト30日）内の発生のみを保持
    -- 閾値チェックはこの配列の要素数で行う
    occurrence_timestamps TIMESTAMPTZ[] NOT NULL DEFAULT '{}',

    -- 最初に質問された日時
    first_asked_at TIMESTAMPTZ NOT NULL,

    -- 最後に質問された日時
    last_asked_at TIMESTAMPTZ NOT NULL,

    -- 質問した人のリスト（UUID配列）
    -- 同じ人が何度も質問している場合は1回だけカウント
    asked_by_user_ids UUID[] NOT NULL DEFAULT '{}',

    -- サンプル質問（元の質問文を最大5件保存）
    -- パターンの具体例として管理者に表示
    sample_questions TEXT[] NOT NULL DEFAULT '{}',

    -- ================================================================
    -- ステータス管理
    -- ================================================================
    -- ステータス:
    -- - active: 検出中（デフォルト）
    -- - addressed: 対応済み（ナレッジ化等）
    -- - dismissed: 無視（重要でないと判断）
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'addressed', 'dismissed')),

    -- 対応日時（statusがaddressed/dismissedに変更された日時）
    addressed_at TIMESTAMPTZ,

    -- 対応内容（どのように対応したかの記録）
    -- 例: 「週報マニュアルを作成し、全社メールで周知」
    addressed_action TEXT,

    -- 無視理由（statusがdismissedの場合）
    -- 例: 「季節限定の質問のため」
    dismissed_reason TEXT,

    -- ================================================================
    -- 機密区分（鉄則: 4段階の機密区分を必ず設定）
    -- ================================================================
    -- - public: 公開情報
    -- - internal: 社内限定（デフォルト）
    -- - confidential: 機密
    -- - restricted: 極秘
    classification VARCHAR(20) NOT NULL DEFAULT 'internal'
        CHECK (classification IN ('public', 'internal', 'confidential', 'restricted')),

    -- ================================================================
    -- 監査フィールド（v1.2準拠）
    -- ================================================================
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- ================================================================
    -- 制約
    -- ================================================================
    -- 注意: 部署別のユニーク制約はCREATE UNIQUE INDEXで作成（NULLの扱いのため）
    -- 下記のインデックス作成セクションを参照
    CONSTRAINT chk_occurrence_count CHECK (occurrence_count >= 1)
);

-- 2-2. question_patternsテーブルのインデックス作成

-- ================================================================
-- 部署別パターンのユニーク制約（Codex HIGH1指摘対応）
-- ================================================================
-- 同一組織・同一部署内で同じハッシュのパターンは1つだけ
-- NULLの部署IDも含めてユニーク性を保証するため、COALESCEを使用
-- '00000000-0000-0000-0000-000000000000' は「部署未指定」を表すセンチネル値
CREATE UNIQUE INDEX IF NOT EXISTS uq_question_patterns_org_dept_hash
    ON question_patterns(
        organization_id,
        COALESCE(department_id, '00000000-0000-0000-0000-000000000000'::uuid),
        question_hash
    );

-- 組織IDと発生回数でのソート（頻出パターンの取得用）
CREATE INDEX IF NOT EXISTS idx_question_patterns_org_count
    ON question_patterns(organization_id, occurrence_count DESC);

-- 組織IDとカテゴリでの検索
CREATE INDEX IF NOT EXISTS idx_question_patterns_org_category
    ON question_patterns(organization_id, question_category);

-- 組織IDと部署IDでの検索（Phase 3.5連携）
CREATE INDEX IF NOT EXISTS idx_question_patterns_org_department
    ON question_patterns(organization_id, department_id)
    WHERE department_id IS NOT NULL;

-- アクティブなパターンのみの部分インデックス
CREATE INDEX IF NOT EXISTS idx_question_patterns_org_status_active
    ON question_patterns(organization_id, status)
    WHERE status = 'active';

-- 最終質問日時での検索（期間フィルタ用）
CREATE INDEX IF NOT EXISTS idx_question_patterns_last_asked
    ON question_patterns(organization_id, last_asked_at DESC);

-- 2-3. question_patternsテーブルのコメント追加
COMMENT ON TABLE question_patterns IS
'Phase 2進化版 A1: 質問パターンの記録
- ソウルくんへの質問を分析し、頻出パターンを検出
- occurrence_count >= PATTERN_THRESHOLD（デフォルト5）でsoulkun_insightsに登録
- 設計書: docs/06_phase2_a1_pattern_detection.md';

COMMENT ON COLUMN question_patterns.question_category IS
'質問のカテゴリ: business_process, company_rule, technical, hr_related, project, other';

COMMENT ON COLUMN question_patterns.question_hash IS
'類似度判定用ハッシュ（SHA256の先頭64文字）- 同じ意味の質問を同一パターンとして認識';

COMMENT ON COLUMN question_patterns.occurrence_count IS
'発生回数 - この値がPATTERN_THRESHOLD以上になるとインサイトとして登録';

COMMENT ON COLUMN question_patterns.asked_by_user_ids IS
'質問した人のUUIDリスト - ユニークユーザー数の計算に使用';

COMMENT ON COLUMN question_patterns.sample_questions IS
'元の質問文のサンプル（最大5件）- パターンの具体例として表示';


-- ================================================================
-- STEP 3: soulkun_insightsテーブル作成（ソウルくんの気づき）
-- ================================================================
-- 目的: 全ての検出機能（A1, A2, A3, A4）の結果を統合管理
-- 用途: 週次レポートのソースデータ、管理者への通知

-- 3-1. soulkun_insightsテーブル作成
CREATE TABLE IF NOT EXISTS soulkun_insights (
    -- ================================================================
    -- 主キー
    -- ================================================================
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- ================================================================
    -- テナント分離（鉄則1: 全テーブルにorganization_id）
    -- ================================================================
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- ================================================================
    -- 部署フィルタ（Phase 3.5準拠）
    -- ================================================================
    department_id UUID REFERENCES departments(id) ON DELETE SET NULL,

    -- ================================================================
    -- 気づきの種類とソース
    -- ================================================================
    -- 気づきの種類（表示用）
    -- - pattern_detected: 頻出パターンを検出
    -- - personalization_risk: 属人化リスクを検出
    -- - bottleneck: ボトルネックを検出
    -- - emotion_change: 感情変化を検出
    insight_type VARCHAR(50) NOT NULL,

    -- ソースの種類（システム内部用）
    -- - a1_pattern: A1パターン検出
    -- - a2_personalization: A2属人化検出（将来）
    -- - a3_bottleneck: A3ボトルネック検出（将来）
    -- - a4_emotion: A4感情変化検出（将来）
    source_type VARCHAR(50) NOT NULL,

    -- ソースデータのID（元データへの参照）
    -- 例: question_patterns.id
    source_id UUID,

    -- ================================================================
    -- 重要度と内容
    -- ================================================================
    -- 重要度:
    -- - critical: 即時対応必要（経営に影響）
    -- - high: 早急に対応（業務に支障）
    -- - medium: 計画的に対応
    -- - low: 時間があれば対応
    importance VARCHAR(20) NOT NULL
        CHECK (importance IN ('critical', 'high', 'medium', 'low')),

    -- タイトル（一覧表示用、200文字以内）
    title VARCHAR(200) NOT NULL,

    -- 詳細説明（マークダウン可）
    description TEXT NOT NULL,

    -- 推奨アクション（マークダウン可）
    recommended_action TEXT,

    -- 根拠データ（JSON形式）
    -- 例: {"occurrence_count": 10, "unique_users": 5, "sample_questions": [...]}
    evidence JSONB NOT NULL DEFAULT '{}',

    -- ================================================================
    -- ステータス管理
    -- ================================================================
    -- ステータス:
    -- - new: 新規（未確認）
    -- - acknowledged: 確認済み（対応検討中）
    -- - addressed: 対応完了
    -- - dismissed: 無視（対応不要と判断）
    status VARCHAR(20) NOT NULL DEFAULT 'new'
        CHECK (status IN ('new', 'acknowledged', 'addressed', 'dismissed')),

    -- 確認日時と確認者
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by UUID REFERENCES users(id) ON DELETE SET NULL,

    -- 対応日時と対応者
    addressed_at TIMESTAMPTZ,
    addressed_by UUID REFERENCES users(id) ON DELETE SET NULL,

    -- 対応内容
    addressed_action TEXT,

    -- 無視理由（statusがdismissedの場合）
    dismissed_reason TEXT,

    -- ================================================================
    -- 通知管理
    -- ================================================================
    -- 通知日時
    notified_at TIMESTAMPTZ,

    -- 通知先ユーザーIDリスト
    notified_to UUID[] NOT NULL DEFAULT '{}',

    -- 通知方法: chatwork, email, etc.
    notified_via VARCHAR(50),

    -- ================================================================
    -- 機密区分（鉄則: 4段階の機密区分を必ず設定）
    -- ================================================================
    classification VARCHAR(20) NOT NULL DEFAULT 'internal'
        CHECK (classification IN ('public', 'internal', 'confidential', 'restricted')),

    -- ================================================================
    -- 監査フィールド（v1.2準拠）
    -- ================================================================
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 3-2. soulkun_insightsテーブルのインデックス作成
-- 組織IDと気づきの種類での検索
CREATE INDEX IF NOT EXISTS idx_soulkun_insights_org_type
    ON soulkun_insights(organization_id, insight_type);

-- 組織IDと重要度での検索（重要な気づきを優先表示）
CREATE INDEX IF NOT EXISTS idx_soulkun_insights_org_importance
    ON soulkun_insights(organization_id, importance);

-- 未対応の気づきのみの部分インデックス
CREATE INDEX IF NOT EXISTS idx_soulkun_insights_org_status_pending
    ON soulkun_insights(organization_id, status)
    WHERE status IN ('new', 'acknowledged');

-- 組織IDと部署IDでの検索
CREATE INDEX IF NOT EXISTS idx_soulkun_insights_org_department
    ON soulkun_insights(organization_id, department_id)
    WHERE department_id IS NOT NULL;

-- ================================================================
-- 重複インサイト防止のユニーク制約（Codex HIGH2指摘対応）
-- ================================================================
-- 同一ソースから重複してインサイトが作成されることを防止
-- レース条件（並行実行）による重複作成をDB側で防ぐ
-- source_id が NULL の場合は制約の対象外（部分ユニークインデックス）
CREATE UNIQUE INDEX IF NOT EXISTS uq_soulkun_insights_source
    ON soulkun_insights(organization_id, source_type, source_id)
    WHERE source_id IS NOT NULL;

-- ソースタイプとソースIDでの検索（重複チェック用）
-- 注意: 上記のユニークインデックスが検索にも使用されるため、
--       別途通常のインデックスは不要だが、明示性のため残す
CREATE INDEX IF NOT EXISTS idx_soulkun_insights_source_search
    ON soulkun_insights(organization_id, source_type, source_id)
    WHERE source_id IS NOT NULL;

-- 作成日時での検索（期間フィルタ用）
CREATE INDEX IF NOT EXISTS idx_soulkun_insights_created_at
    ON soulkun_insights(organization_id, created_at DESC);

-- 3-3. soulkun_insightsテーブルのコメント追加
COMMENT ON TABLE soulkun_insights IS
'Phase 2進化版: ソウルくんの気づき（統合テーブル）
- A1パターン検出、A2属人化検出、A3ボトルネック検出等の結果を統合
- 週次レポートのソースデータ
- importance: critical/high は即時通知、medium/low は週次レポート
- 設計書: docs/06_phase2_a1_pattern_detection.md';

COMMENT ON COLUMN soulkun_insights.source_type IS
'ソースの種類: a1_pattern, a2_personalization, a3_bottleneck, a4_emotion';

COMMENT ON COLUMN soulkun_insights.importance IS
'重要度: critical（即時対応）, high（早急対応）, medium（計画対応）, low（時間があれば）';

COMMENT ON COLUMN soulkun_insights.evidence IS
'根拠データ（JSON形式）- 検出の具体的な証拠を格納';


-- ================================================================
-- STEP 4: soulkun_weekly_reportsテーブル作成（週次レポート）
-- ================================================================
-- 目的: 週次でインサイトをまとめて管理者に報告
-- 用途: 毎週月曜日に自動生成、ChatWorkで送信

-- 4-1. soulkun_weekly_reportsテーブル作成
CREATE TABLE IF NOT EXISTS soulkun_weekly_reports (
    -- ================================================================
    -- 主キー
    -- ================================================================
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- ================================================================
    -- テナント分離（鉄則1: 全テーブルにorganization_id）
    -- ================================================================
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- ================================================================
    -- レポート期間
    -- ================================================================
    -- 週の開始日（月曜日）
    week_start DATE NOT NULL,

    -- 週の終了日（日曜日）
    week_end DATE NOT NULL,

    -- 期間の整合性チェック
    CONSTRAINT chk_week_period CHECK (week_end > week_start AND week_end - week_start <= 7),

    -- ================================================================
    -- レポート内容
    -- ================================================================
    -- レポート本文（マークダウン形式）
    report_content TEXT NOT NULL,

    -- インサイトのサマリー（JSON形式）
    -- 例: {"total": 5, "by_importance": {"high": 1, "medium": 2, "low": 2}, "by_type": {...}}
    insights_summary JSONB NOT NULL DEFAULT '{}',

    -- 含まれるインサイトのIDリスト
    included_insight_ids UUID[] NOT NULL DEFAULT '{}',

    -- ================================================================
    -- 送信情報
    -- ================================================================
    -- 送信日時
    sent_at TIMESTAMPTZ,

    -- 送信先ユーザーIDリスト
    sent_to UUID[] NOT NULL DEFAULT '{}',

    -- 送信方法: chatwork, email, etc.
    sent_via VARCHAR(50),

    -- ChatWork room_id（送信先ルーム）
    chatwork_room_id BIGINT,

    -- ChatWork message_id（送信済みメッセージID）
    chatwork_message_id TEXT,

    -- ================================================================
    -- ステータス管理
    -- ================================================================
    -- ステータス:
    -- - draft: 下書き（生成済み、未送信）
    -- - sent: 送信完了
    -- - failed: 送信失敗
    status VARCHAR(20) NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'sent', 'failed')),

    -- エラーメッセージ（送信失敗時）
    error_message TEXT,

    -- リトライ回数
    retry_count INT NOT NULL DEFAULT 0,

    -- ================================================================
    -- 機密区分（鉄則: 4段階の機密区分を必ず設定）
    -- ================================================================
    classification VARCHAR(20) NOT NULL DEFAULT 'internal'
        CHECK (classification IN ('public', 'internal', 'confidential', 'restricted')),

    -- ================================================================
    -- 監査フィールド（v1.2準拠）
    -- ================================================================
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- ================================================================
    -- 制約
    -- ================================================================
    -- 同一組織で同じ週のレポートは1つだけ
    CONSTRAINT uq_soulkun_weekly_reports_org_week
        UNIQUE(organization_id, week_start)
);

-- 4-2. soulkun_weekly_reportsテーブルのインデックス作成
-- 組織IDと週開始日での検索
CREATE INDEX IF NOT EXISTS idx_soulkun_weekly_reports_org_week
    ON soulkun_weekly_reports(organization_id, week_start DESC);

-- ステータスでの検索（送信待ちレポートの取得用）
CREATE INDEX IF NOT EXISTS idx_soulkun_weekly_reports_status
    ON soulkun_weekly_reports(status)
    WHERE status IN ('draft', 'failed');

-- 4-3. soulkun_weekly_reportsテーブルのコメント追加
COMMENT ON TABLE soulkun_weekly_reports IS
'Phase 2進化版: 週次レポート
- 毎週月曜日に自動生成
- soulkun_insights の内容をまとめて管理者に送信
- 設計書: docs/06_phase2_a1_pattern_detection.md';

COMMENT ON COLUMN soulkun_weekly_reports.insights_summary IS
'インサイトのサマリー（JSON形式）- 件数、重要度別、タイプ別の集計';


-- ================================================================
-- STEP 5: notification_logs CHECK制約の更新
-- ================================================================
-- 目的: A1パターン検出で使用する新しいnotification_typeを追加
-- 追加値: pattern_alert, weekly_report

-- 5-1. 既存のCHECK制約を削除
ALTER TABLE notification_logs
    DROP CONSTRAINT IF EXISTS check_notification_type;

-- 5-2. 新しいCHECK制約を追加（既存の値 + 新規の値）
ALTER TABLE notification_logs
    ADD CONSTRAINT check_notification_type
    CHECK (notification_type IN (
        -- Phase 1-B: タスク管理
        'task_reminder',
        'task_overdue',
        'task_escalation',
        'deadline_alert',
        'escalation_alert',
        'dm_unavailable',
        -- Phase 2.5: 目標達成支援
        'goal_daily_check',
        'goal_daily_reminder',
        'goal_morning_feedback',
        'goal_team_summary',
        'goal_consecutive_unanswered',
        -- Phase 2 A1: パターン検出（新規追加）
        'pattern_alert',      -- 頻出パターン検出アラート（critical/high）
        'weekly_report'       -- 週次レポート
    ));

-- 5-3. コメント追加
COMMENT ON CONSTRAINT check_notification_type ON notification_logs IS
'通知タイプの制約 - Phase 2 A1でpattern_alert, weekly_reportを追加';


-- ================================================================
-- STEP 6: RLS（Row Level Security）ポリシー準備
-- ================================================================
-- 注意: Phase 4でRLSを有効化する際に使用
-- 現時点ではポリシーの定義のみ（有効化はしない）

-- 6-1. question_patternsのRLSポリシー（Phase 4で有効化）
-- DROP POLICY IF EXISTS policy_question_patterns_org ON question_patterns;
-- CREATE POLICY policy_question_patterns_org ON question_patterns
--     USING (organization_id = current_setting('app.current_organization_id')::UUID);

-- 6-2. soulkun_insightsのRLSポリシー（Phase 4で有効化）
-- DROP POLICY IF EXISTS policy_soulkun_insights_org ON soulkun_insights;
-- CREATE POLICY policy_soulkun_insights_org ON soulkun_insights
--     USING (organization_id = current_setting('app.current_organization_id')::UUID);

-- 6-3. soulkun_weekly_reportsのRLSポリシー（Phase 4で有効化）
-- DROP POLICY IF EXISTS policy_soulkun_weekly_reports_org ON soulkun_weekly_reports;
-- CREATE POLICY policy_soulkun_weekly_reports_org ON soulkun_weekly_reports
--     USING (organization_id = current_setting('app.current_organization_id')::UUID);


-- ================================================================
-- STEP 7: updated_at自動更新トリガー
-- ================================================================
-- 目的: レコード更新時にupdated_atを自動更新

-- 7-1. トリガー関数の作成（既存の場合はスキップ）
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- 7-2. question_patternsテーブルにトリガー追加
DROP TRIGGER IF EXISTS trigger_question_patterns_updated_at ON question_patterns;
CREATE TRIGGER trigger_question_patterns_updated_at
    BEFORE UPDATE ON question_patterns
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- 7-3. soulkun_insightsテーブルにトリガー追加
DROP TRIGGER IF EXISTS trigger_soulkun_insights_updated_at ON soulkun_insights;
CREATE TRIGGER trigger_soulkun_insights_updated_at
    BEFORE UPDATE ON soulkun_insights
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- 7-4. soulkun_weekly_reportsテーブルにトリガー追加
DROP TRIGGER IF EXISTS trigger_soulkun_weekly_reports_updated_at ON soulkun_weekly_reports;
CREATE TRIGGER trigger_soulkun_weekly_reports_updated_at
    BEFORE UPDATE ON soulkun_weekly_reports
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();


-- ================================================================
-- STEP 8: 確認クエリ（マイグレーション成功の確認）
-- ================================================================

-- 8-1. 作成されたテーブルの確認
SELECT
    table_name,
    (SELECT COUNT(*) FROM information_schema.columns c WHERE c.table_name = t.table_name) as columns
FROM information_schema.tables t
WHERE table_schema = 'public'
  AND table_name IN ('question_patterns', 'soulkun_insights', 'soulkun_weekly_reports')
ORDER BY table_name;

-- 8-2. question_patternsテーブルの構造確認
SELECT
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'question_patterns'
  AND table_schema = 'public'
ORDER BY ordinal_position;

-- 8-3. soulkun_insightsテーブルの構造確認
SELECT
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'soulkun_insights'
  AND table_schema = 'public'
ORDER BY ordinal_position;

-- 8-4. soulkun_weekly_reportsテーブルの構造確認
SELECT
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'soulkun_weekly_reports'
  AND table_schema = 'public'
ORDER BY ordinal_position;

-- 8-5. インデックスの確認
SELECT
    indexname,
    tablename
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename IN ('question_patterns', 'soulkun_insights', 'soulkun_weekly_reports')
ORDER BY tablename, indexname;

-- 8-6. 制約の確認
SELECT
    conname as constraint_name,
    conrelid::regclass as table_name,
    pg_get_constraintdef(oid) as definition
FROM pg_constraint
WHERE conrelid IN (
    'question_patterns'::regclass,
    'soulkun_insights'::regclass,
    'soulkun_weekly_reports'::regclass
)
ORDER BY conrelid, conname;

-- 8-7. トリガーの確認
SELECT
    trigger_name,
    event_object_table as table_name,
    action_timing,
    event_manipulation
FROM information_schema.triggers
WHERE event_object_table IN ('question_patterns', 'soulkun_insights', 'soulkun_weekly_reports')
ORDER BY event_object_table, trigger_name;

-- 8-8. notification_logsの制約確認（更新後）
SELECT
    conname as constraint_name,
    pg_get_constraintdef(oid) as constraint_definition
FROM pg_constraint
WHERE conrelid = 'notification_logs'::regclass
  AND conname = 'check_notification_type';


-- ================================================================
-- STEP 9: コミット（全ての変更を確定）
-- ================================================================
-- 全ての確認が完了したらコミット
COMMIT;

-- マイグレーション完了メッセージ
SELECT
    'Phase 2 A1 Pattern Detection migration completed successfully!' as message,
    now() as completed_at;


-- ================================================================
-- STEP 10: ロールバック手順（エラー発生時のみ実行）
-- ================================================================
-- 注意: 以下はエラー発生時にのみ実行してください
-- 通常のマイグレーションでは実行しないでください

/*
-- ロールバック開始
ROLLBACK;

-- または、手動でテーブルを削除する場合:
DROP TABLE IF EXISTS soulkun_weekly_reports CASCADE;
DROP TABLE IF EXISTS soulkun_insights CASCADE;
DROP TABLE IF EXISTS question_patterns CASCADE;

-- notification_logsの制約を元に戻す場合:
ALTER TABLE notification_logs DROP CONSTRAINT IF EXISTS check_notification_type;
ALTER TABLE notification_logs ADD CONSTRAINT check_notification_type
CHECK (notification_type IN (
    'task_reminder', 'task_overdue', 'task_escalation',
    'deadline_alert', 'escalation_alert', 'dm_unavailable',
    'goal_daily_check', 'goal_daily_reminder', 'goal_morning_feedback',
    'goal_team_summary', 'goal_consecutive_unanswered'
));
*/


-- ================================================================
-- 付録A: テストデータ挿入（開発環境のみ）
-- ================================================================
-- 注意: 本番環境では実行しないでください

/*
-- テスト用の組織ID（実際の値に置き換え）
-- SET @test_org_id = '5f98365f-e7c5-4f48-9918-7fe9aabae5df';

-- テスト用のパターンデータ
INSERT INTO question_patterns (
    organization_id,
    question_category,
    question_hash,
    normalized_question,
    occurrence_count,
    first_asked_at,
    last_asked_at,
    asked_by_user_ids,
    sample_questions,
    status
) VALUES (
    '5f98365f-e7c5-4f48-9918-7fe9aabae5df',
    'business_process',
    'abc123def456',
    '週報の出し方を教えてください',
    10,
    CURRENT_TIMESTAMP - INTERVAL '30 days',
    CURRENT_TIMESTAMP,
    ARRAY['user-id-1'::UUID, 'user-id-2'::UUID],
    ARRAY['週報ってどこから出すんですか？', '週報の提出方法を教えてください'],
    'active'
);

-- テスト用のインサイトデータ
INSERT INTO soulkun_insights (
    organization_id,
    insight_type,
    source_type,
    importance,
    title,
    description,
    recommended_action,
    evidence,
    status
) VALUES (
    '5f98365f-e7c5-4f48-9918-7fe9aabae5df',
    'pattern_detected',
    'a1_pattern',
    'high',
    '「週報の出し方」の質問が頻出しています',
    '過去30日間で10回、5人の社員から同じ質問がありました。',
    '1. 週報マニュアルを作成\n2. 全社メールで周知',
    '{"occurrence_count": 10, "unique_users": 5}',
    'new'
);
*/


-- ================================================================
-- 付録B: 運用クエリ集
-- ================================================================

/*
-- B-1. 頻出パターンのTop 10を取得
SELECT
    qp.id,
    qp.question_category,
    qp.normalized_question,
    qp.occurrence_count,
    array_length(qp.asked_by_user_ids, 1) as unique_users,
    qp.last_asked_at
FROM question_patterns qp
WHERE qp.organization_id = :org_id
  AND qp.status = 'active'
ORDER BY qp.occurrence_count DESC
LIMIT 10;

-- B-2. 未対応のインサイト一覧
SELECT
    si.id,
    si.insight_type,
    si.importance,
    si.title,
    si.status,
    si.created_at
FROM soulkun_insights si
WHERE si.organization_id = :org_id
  AND si.status IN ('new', 'acknowledged')
ORDER BY
    CASE si.importance
        WHEN 'critical' THEN 1
        WHEN 'high' THEN 2
        WHEN 'medium' THEN 3
        ELSE 4
    END,
    si.created_at DESC;

-- B-3. 今週の週次レポートを取得
SELECT
    swr.id,
    swr.week_start,
    swr.week_end,
    swr.report_content,
    swr.status,
    swr.sent_at
FROM soulkun_weekly_reports swr
WHERE swr.organization_id = :org_id
  AND swr.week_start = date_trunc('week', CURRENT_DATE)::DATE;

-- B-4. カテゴリ別のパターン件数
SELECT
    question_category,
    COUNT(*) as pattern_count,
    SUM(occurrence_count) as total_occurrences
FROM question_patterns
WHERE organization_id = :org_id
  AND status = 'active'
GROUP BY question_category
ORDER BY total_occurrences DESC;
*/

-- ================================================================
-- マイグレーションファイル終了
-- ================================================================
