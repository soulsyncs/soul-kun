-- =====================================================
-- v10.40.9: メモリ分離マイグレーション
--
-- 構成:
--   Phase 1: スキーマ変更（短時間DDL）
--   Phase 2: データ移行（トランザクション分離）
--   Phase 3: インデックス作成（CONCURRENTLY でロック回避）
--
-- 実行方法:
--   cat migrations/20260128_memory_separation.sql | gcloud sql connect soulkun-db --user=postgres --database=soulkun
--
-- 冪等性: IF NOT EXISTS / ON CONFLICT で再実行可能
-- ロック: Phase 3 は CONCURRENTLY で通常クエリをブロックしない
-- =====================================================


-- =====================================================
-- Phase 1: スキーマ変更（短時間DDL）
-- =====================================================
-- DDLは自動コミットされる。テーブル作成とカラム追加は高速。

-- 1-1. bot_persona_memory テーブル作成
CREATE TABLE IF NOT EXISTS bot_persona_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,

    -- キー（例: 好物, モチーフ動物, 口調）
    key VARCHAR(100) NOT NULL,

    -- 値（例: 10円パン, 狼, ウル）
    value TEXT NOT NULL,

    -- カテゴリ（character, personality, preference）
    category VARCHAR(50) NOT NULL DEFAULT 'character',

    -- 誰が設定したか（管理者のみ設定可能）
    created_by_account_id TEXT,
    created_by_name TEXT,

    -- メタデータ
    metadata JSONB DEFAULT '{}',

    -- タイムスタンプ
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    -- 外部キー制約
    CONSTRAINT fk_bot_persona_memory_org FOREIGN KEY (organization_id)
        REFERENCES organizations(id) ON DELETE CASCADE,

    -- organization_id + key でユニーク
    CONSTRAINT uq_bot_persona_org_key UNIQUE (organization_id, key)
);

-- コメント
COMMENT ON TABLE bot_persona_memory IS 'ソウルくんのキャラ設定・ペルソナ情報（全ユーザー共通）';
COMMENT ON COLUMN bot_persona_memory.key IS '設定キー（好物, モチーフ動物, 口調など）';
COMMENT ON COLUMN bot_persona_memory.value IS '設定値';
COMMENT ON COLUMN bot_persona_memory.category IS 'カテゴリ: character(キャラ設定), personality(性格), preference(好み)';

-- 1-2. user_long_term_memory に scope カラム追加（安全版）
-- 3ステップ方式: テーブルリライトを回避し、長時間ロックを防ぐ

-- Step 1: NULL許可でカラム追加（高速DDL、テーブルリライトなし）
ALTER TABLE user_long_term_memory
ADD COLUMN IF NOT EXISTS scope VARCHAR(20);

-- Step 2: 既存データに値を埋める（バッチ更新で負荷制御）
-- 1回の実行で全件終わらなくてもOK。NULLが残る場合は同じSQLを繰り返す運用。
WITH target AS (
    SELECT id
    FROM user_long_term_memory
    WHERE scope IS NULL
    ORDER BY id
    LIMIT 10000
)
UPDATE user_long_term_memory u
SET scope = 'PRIVATE'
FROM target
WHERE u.id = target.id;

-- （任意）進捗確認
-- SELECT COUNT(*) FROM user_long_term_memory WHERE scope IS NULL;

-- ★重要: Step 3 を実行する前に NULL = 0 を確認すること
-- 巨大テーブルの場合、上記バッチUPDATEを NULL が 0 になるまで繰り返す

-- Step 3: デフォルト値とNOT NULL制約を追加
ALTER TABLE user_long_term_memory
ALTER COLUMN scope SET DEFAULT 'PRIVATE';

ALTER TABLE user_long_term_memory
ALTER COLUMN scope SET NOT NULL;

COMMENT ON COLUMN user_long_term_memory.scope IS
    'アクセススコープ: PRIVATE(本人のみ), ORG_SHARED(組織内共有)';


-- =====================================================
-- Phase 2: データ移行（トランザクション分離）
-- =====================================================
-- データ移行のみトランザクションでラップ。失敗時はロールバック。

BEGIN;

INSERT INTO bot_persona_memory (
    organization_id,
    key,
    value,
    category,
    created_by_account_id,
    metadata,
    created_at,
    updated_at
)
SELECT
    -- organization_idがない場合はデフォルトのソウルシンクスIDを使用
    COALESCE(
        (SELECT id FROM organizations WHERE name ILIKE '%ソウルシンクス%' LIMIT 1),
        (SELECT id FROM organizations LIMIT 1)
    ) as organization_id,
    sk.key,
    sk.value,
    'character' as category,
    sk.created_by as created_by_account_id,
    jsonb_build_object(
        'migrated_from', 'soulkun_knowledge',
        'original_category', sk.category,
        'migrated_at', CURRENT_TIMESTAMP
    ) as metadata,
    sk.created_at,
    sk.updated_at
FROM soulkun_knowledge sk
WHERE sk.category = 'character'
ON CONFLICT (organization_id, key) DO UPDATE SET
    value = EXCLUDED.value,
    metadata = bot_persona_memory.metadata || jsonb_build_object('updated_via_migration', CURRENT_TIMESTAMP),
    updated_at = CURRENT_TIMESTAMP;

COMMIT;


-- =====================================================
-- Phase 3: インデックス作成（CONCURRENTLY でロック回避）
-- =====================================================
-- CONCURRENTLY: テーブルロックを取得せず、通常クエリと並行して作成
-- 注意: トランザクション内では実行不可

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_bot_persona_memory_org
    ON bot_persona_memory(organization_id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_bot_persona_memory_category
    ON bot_persona_memory(organization_id, category);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_user_long_term_memory_scope
    ON user_long_term_memory(user_id, scope);


-- =====================================================
-- 移行完了後の手動作業（オプション）
-- =====================================================
-- soulkun_knowledge から character を削除する場合:
-- DELETE FROM soulkun_knowledge WHERE category = 'character';


-- =====================================================
-- 設計メモ
-- =====================================================
-- bot_persona_memory.organization_id:
--   NOT NULL制約あり（組織単位ペルソナが前提）
--   各組織が独自のボットペルソナを持てる設計（マルチテナント対応）
--   グローバル共通ペルソナは想定していない
