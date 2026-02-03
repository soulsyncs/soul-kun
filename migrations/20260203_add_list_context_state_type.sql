-- ============================================================================
-- Migration: list_context 状態タイプの追加
-- 作成日: 2026-02-03
-- 作成者: Claude Code
-- 目的: brain_conversation_states テーブルに list_context 状態タイプを追加
--
-- 背景:
--   PR #395 で LIST_CONTEXT 状態タイプをコードに追加したが、
--   DBのCHECK制約に追加されていなかったため、状態保存が失敗していた。
--   これにより「目標全部削除して」→「全削除でOK」の文脈が切れていた。
--
-- 変更内容:
--   1. 既存のCHECK制約を削除
--   2. list_context を含む新しいCHECK制約を追加
--
-- ロールバック:
--   ALTER TABLE brain_conversation_states
--     DROP CONSTRAINT IF EXISTS check_brain_state_type;
--   ALTER TABLE brain_conversation_states
--     ADD CONSTRAINT check_brain_state_type CHECK (state_type IN (
--       'normal','goal_setting','announcement','confirmation',
--       'task_pending','multi_action'
--     ));
-- ============================================================================

-- トランザクション開始
BEGIN;

-- ============================================================================
-- Step 1: 既存の制約を削除（両方の名前を試す）
-- ============================================================================

-- 旧名（neural_connection_repair.sql由来の可能性）
ALTER TABLE brain_conversation_states
  DROP CONSTRAINT IF EXISTS check_state_type;

-- 現名（phase_c_brain_state_management.sql由来）
ALTER TABLE brain_conversation_states
  DROP CONSTRAINT IF EXISTS check_brain_state_type;

-- ============================================================================
-- Step 2: 新しい制約を追加（list_context を含む）
-- ============================================================================

ALTER TABLE brain_conversation_states
  ADD CONSTRAINT check_brain_state_type CHECK (state_type IN (
    'normal',           -- 通常状態（状態なし）
    'goal_setting',     -- 目標設定対話中
    'announcement',     -- アナウンス確認中
    'confirmation',     -- 確認待ち
    'task_pending',     -- タスク作成待ち
    'multi_action',     -- 複数アクション実行中
    'list_context'      -- v10.56.5: 一覧表示後の文脈保持
  ));

-- ============================================================================
-- Step 3: コメント更新
-- ============================================================================

COMMENT ON COLUMN brain_conversation_states.state_type IS
  '状態タイプ: normal（通常）, goal_setting（目標設定中）, announcement（アナウンス確認中）, confirmation（確認待ち）, task_pending（タスク作成待ち）, multi_action（複数アクション中）, list_context（一覧表示後の文脈保持）';

-- ============================================================================
-- 完了通知
-- ============================================================================

DO $$
BEGIN
  RAISE NOTICE '✅ Migration: list_context 状態タイプ追加完了';
  RAISE NOTICE '  - check_brain_state_type 制約を更新';
  RAISE NOTICE '  - list_context を許可リストに追加';
END $$;

COMMIT;
