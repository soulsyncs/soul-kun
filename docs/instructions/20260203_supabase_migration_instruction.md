# Supabase DBマイグレーション指示書

## 目的

ソウルくんの「目標全部削除して」→「全削除でOK」の会話が途切れるバグを修正する。

## 背景

- ソウルくんのコードに `list_context` という新しい状態タイプを追加した
- しかしデータベースの許可リストに `list_context` が含まれていない
- そのため状態を保存しようとするとDBが拒否し、会話の文脈が失われる
- 結果：「全削除でOK」と言っても「タスク？目標？」と聞き返してしまう

## やってほしいこと

### Step 1: Supabaseにログイン

1. https://supabase.com にアクセス
2. ソウルくんのプロジェクトを開く

### Step 2: SQL Editorを開く

1. 左メニューから「SQL Editor」をクリック
2. 「New query」をクリック

### Step 3: SQLを実行

以下のSQLをコピーして貼り付け、「Run」ボタンをクリック：

```sql
BEGIN;

-- 既存の制約を削除
ALTER TABLE brain_conversation_states
  DROP CONSTRAINT IF EXISTS check_state_type;

ALTER TABLE brain_conversation_states
  DROP CONSTRAINT IF EXISTS check_brain_state_type;

-- 新しい制約を追加（list_contextを含む）
ALTER TABLE brain_conversation_states
  ADD CONSTRAINT check_brain_state_type CHECK (state_type IN (
    'normal',
    'goal_setting',
    'announcement',
    'confirmation',
    'task_pending',
    'multi_action',
    'list_context'
  ));

COMMIT;
```

### Step 4: 結果確認

- 「Success」と表示されればOK
- エラーが出た場合はエラーメッセージを教えてください

## 完了後

この指示書を渡してくれた人（Claude Code）に「完了した」と伝えてください。
その後、コードのデプロイを行い、動作確認をします。

## 所要時間

約2分

## 注意事項

- このSQLはデータを削除しません（制約の変更のみ）
- 失敗しても既存データに影響はありません
- 本番環境で実行してください
