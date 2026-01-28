-- =====================================================
-- v10.40.9: メモリ分離マイグレーション チェックリスト
--
-- 実行方法:
--   cat migrations/20260128_memory_separation_checklist.sql | gcloud sql connect soulkun-db --user=postgres --database=soulkun
--
-- 用途:
--   - PRE: マイグレーション実行前の状態確認
--   - POST: マイグレーション実行後の検証
--
-- ロック回避設計:
--   - インデックスは CONCURRENTLY で作成
--   - 実行中も通常クエリはブロックされない
--   - Phase分離: DDL → データ移行 → インデックス
-- =====================================================

\echo '============================================='
\echo 'v10.40.9 Memory Separation Checklist'
\echo '============================================='

-- =====================================================
-- PRE-MIGRATION: 実行前確認
-- =====================================================

\echo ''
\echo '===== PRE-1: 移行対象データ確認（soulkun_knowledge.category=character） ====='
SELECT
    COUNT(*) as character_count,
    'これらが bot_persona_memory へ移行される' as note
FROM soulkun_knowledge
WHERE category = 'character';

\echo ''
\echo '===== PRE-2: soulkun_knowledge 現在の状態 ====='
SELECT
    category,
    COUNT(*) as count
FROM soulkun_knowledge
GROUP BY category
ORDER BY category;

\echo ''
\echo '===== PRE-3: user_long_term_memory scope カラム存在確認 ====='
SELECT
    column_name,
    data_type,
    column_default
FROM information_schema.columns
WHERE table_name = 'user_long_term_memory'
AND column_name = 'scope';

\echo ''
\echo '===== PRE-4: bot_persona_memory テーブル存在確認 ====='
SELECT
    table_name,
    'EXISTS' as status
FROM information_schema.tables
WHERE table_name = 'bot_persona_memory'
UNION ALL
SELECT
    'bot_persona_memory',
    'NOT EXISTS'
WHERE NOT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_name = 'bot_persona_memory'
);


-- =====================================================
-- POST-MIGRATION: 実行後検証
-- =====================================================

\echo ''
\echo '===== POST-1: bot_persona_memory テーブル確認 ====='
SELECT
    table_name,
    (SELECT COUNT(*) FROM bot_persona_memory) as row_count
FROM information_schema.tables
WHERE table_name = 'bot_persona_memory';

\echo ''
\echo '===== POST-2: bot_persona_memory 移行データ確認 ====='
SELECT
    key,
    value,
    category,
    metadata->>'migrated_from' as migrated_from,
    created_at
FROM bot_persona_memory
ORDER BY key
LIMIT 20;

\echo ''
\echo '===== POST-3: user_long_term_memory scope カラム確認 ====='
SELECT
    column_name,
    data_type,
    column_default,
    is_nullable
FROM information_schema.columns
WHERE table_name = 'user_long_term_memory'
AND column_name = 'scope';

\echo ''
\echo '===== POST-4: user_long_term_memory scope 分布確認 ====='
SELECT
    scope,
    COUNT(*) as count
FROM user_long_term_memory
GROUP BY scope
ORDER BY scope;

\echo ''
\echo '===== POST-5: インデックス確認 ====='
-- 注意: CONCURRENTLY で作成されるため、通常クエリはブロックされない
-- インデックス作成中でも読み書き可能
SELECT
    indexname,
    tablename
FROM pg_indexes
WHERE tablename IN ('bot_persona_memory', 'user_long_term_memory')
AND indexname LIKE 'idx_%'
ORDER BY tablename, indexname;

\echo ''
\echo '===== POST-6: 整合性チェック（FK） ====='
-- bot_persona_memory の organization_id が有効か
SELECT
    'bot_persona_memory FK check' as check_name,
    CASE
        WHEN COUNT(*) = 0 THEN 'OK: No orphan records'
        ELSE 'WARNING: ' || COUNT(*) || ' orphan records'
    END as result
FROM bot_persona_memory b
WHERE NOT EXISTS (
    SELECT 1 FROM organizations o WHERE o.id = b.organization_id
);

\echo ''
\echo '===== POST-7: organization_id NULL チェック ====='
-- 設計方針: 組織単位ペルソナが前提（NOT NULL制約）
-- 期待値: 0件（NULLは許容しない）
SELECT
    'bot_persona_memory org_id NULL check' as check_name,
    CASE
        WHEN COUNT(*) = 0 THEN 'OK: No NULL org_id (design compliant)'
        ELSE 'ERROR: ' || COUNT(*) || ' records with NULL org_id'
    END as result
FROM bot_persona_memory
WHERE organization_id IS NULL;

\echo ''
\echo '============================================='
\echo 'Checklist Complete'
\echo '============================================='
\echo ''
\echo '設計メモ:'
\echo '  bot_persona_memory.organization_id: NOT NULL（組織単位ペルソナ）'
\echo '  グローバル共通ペルソナは想定していない'
\echo '============================================='
