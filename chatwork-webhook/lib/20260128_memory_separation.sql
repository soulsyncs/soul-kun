-- =====================================================
-- v10.40.9: メモリ分離マイグレーション
--
-- 1. bot_persona_memory テーブル（ソウルくんのキャラ設定専用）
-- 2. user_long_term_memory に scope カラム追加
-- 3. soulkun_knowledge から bot_persona_memory へデータ移行
-- =====================================================

-- =====================================================
-- 1. bot_persona_memory テーブル作成
-- =====================================================
-- ソウルくんのキャラ設定・好み・性格などを保存
-- 全ユーザー共通で参照される

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

-- インデックス
CREATE INDEX IF NOT EXISTS idx_bot_persona_memory_org
    ON bot_persona_memory(organization_id);
CREATE INDEX IF NOT EXISTS idx_bot_persona_memory_category
    ON bot_persona_memory(organization_id, category);

-- コメント
COMMENT ON TABLE bot_persona_memory IS 'ソウルくんのキャラ設定・ペルソナ情報（全ユーザー共通）';
COMMENT ON COLUMN bot_persona_memory.key IS '設定キー（好物, モチーフ動物, 口調など）';
COMMENT ON COLUMN bot_persona_memory.value IS '設定値';
COMMENT ON COLUMN bot_persona_memory.category IS 'カテゴリ: character(キャラ設定), personality(性格), preference(好み)';


-- =====================================================
-- 2. user_long_term_memory に scope カラム追加
-- =====================================================
-- scope: PRIVATE（本人のみ）, ORG_SHARED（組織内共有）

DO $$
BEGIN
    -- scope カラムが存在しない場合のみ追加
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'user_long_term_memory'
        AND column_name = 'scope'
    ) THEN
        ALTER TABLE user_long_term_memory
        ADD COLUMN scope VARCHAR(20) NOT NULL DEFAULT 'PRIVATE';

        -- コメント追加
        COMMENT ON COLUMN user_long_term_memory.scope IS
            'アクセススコープ: PRIVATE(本人のみ), ORG_SHARED(組織内共有)';
    END IF;
END $$;

-- scopeのインデックス
CREATE INDEX IF NOT EXISTS idx_user_long_term_memory_scope
    ON user_long_term_memory(user_id, scope);


-- =====================================================
-- 3. soulkun_knowledge から bot_persona_memory へデータ移行
-- =====================================================
-- category='character' のデータを移行

-- 移行前にバックアップ的なログを残す（メタデータに移行元を記録）
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


-- =====================================================
-- 4. 移行完了後、soulkun_knowledge から character を削除
--    （安全のため、コメントアウト。手動実行推奨）
-- =====================================================
-- DELETE FROM soulkun_knowledge WHERE category = 'character';


-- =====================================================
-- 確認用クエリ
-- =====================================================
-- SELECT * FROM bot_persona_memory;
-- SELECT * FROM user_long_term_memory;
-- SELECT COUNT(*) FROM soulkun_knowledge WHERE category = 'character';
