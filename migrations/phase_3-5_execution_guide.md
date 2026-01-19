# Phase 3.5 マイグレーション実行ガイド

## 概要

このガイドはPhase 3.5（組織階層連携）のSQLマイグレーションと動作確認テストの実行手順を説明します。

### 作成ファイル一覧

| ファイル名 | 用途 |
|-----------|------|
| `phase_3-5_cloudsql_complete.sql` | Cloud SQLマイグレーション（完全版） |
| `phase_3-5_supabase_complete.sql` | Supabaseマイグレーション（完全版） |
| `phase_3-5_test_plan.md` | 動作確認テスト計画書 |
| `phase_3-5_execution_guide.md` | 本ガイド |

---

## 実行前チェックリスト

### 必須確認事項

- [ ] Cloud SQLへの接続権限がある
- [ ] Supabase管理画面へのアクセス権限がある
- [ ] バックアップを取得した（推奨）
- [ ] 実行時間を確保した（約30-60分）

### バックアップコマンド

```bash
# Cloud SQL バックアップ
gcloud sql backups create --instance=soulkun-db

# Supabase: 管理画面 → Database → Backups で取得
```

---

## 実行手順

### Phase 1: Supabaseマイグレーション（先に実行）

**理由**: rolesテーブルの初期データはSupabaseで作成し、Cloud SQLに同期するため

#### 手順

1. **Supabase管理画面にアクセス**
   - https://app.supabase.com/
   - プロジェクト選択

2. **SQL Editorを開く**
   - 左メニュー → SQL Editor

3. **マイグレーションSQLを実行**
   - `phase_3-5_supabase_complete.sql` の内容をコピー
   - SQL Editorに貼り付け
   - 「Run」ボタンをクリック

4. **結果を確認**
   ```sql
   -- 実行後に確認
   SELECT id, name, level FROM roles ORDER BY display_order;
   -- 11件が表示されればOK
   ```

#### 期待される出力

```
id              | name           | level
----------------|----------------|-------
role_ceo        | 代表取締役      | 6
role_cfo        | CFO            | 6
role_coo        | COO            | 6
role_admin_mgr  | 管理部マネージャー | 5
role_admin_staff| 管理部スタッフ   | 5
role_director   | 取締役          | 4
role_dept_head  | 部長           | 4
role_section_head| 課長          | 3
role_leader     | リーダー        | 3
role_employee   | 社員           | 2
role_contractor | 業務委託        | 1
```

---

### Phase 2: Cloud SQLマイグレーション

#### 手順

1. **Cloud SQLに接続**
   ```bash
   gcloud sql connect soulkun-db --user=postgres
   ```

2. **マイグレーションSQLを実行**
   ```bash
   # ファイルから実行
   \i /Users/kikubookair/soul-kun/migrations/phase_3-5_cloudsql_complete.sql

   # または、ファイル内容をコピーして直接実行
   ```

3. **結果を確認**
   ```sql
   -- rolesテーブルの構造確認
   \d roles

   -- user_departmentsテーブルの構造確認
   \d user_departments

   -- chatwork_tasksテーブルの構造確認
   \d chatwork_tasks
   ```

#### 期待される出力

```
-- rolesテーブルにexternal_idカラムが追加されている
Column     | Type         | Nullable
-----------|--------------|----------
id         | uuid         | not null
...
external_id| varchar(100) |

-- user_departmentsテーブルにrole_idカラムが追加されている
Column     | Type         | Nullable
-----------|--------------|----------
...
role_id    | uuid         |

-- chatwork_tasksテーブルにdepartment_idカラムが追加されている
Column       | Type | Nullable
-------------|------|----------
...
department_id| uuid |
```

---

### Phase 3: 動作確認テスト

#### テスト1: 組織図同期

1. **組織図システムを開く**
   ```bash
   open /Users/kikubookair/Desktop/org-chart/index.html
   ```

2. **DevTools Consoleを開く**
   - F12 または Command+Option+I

3. **ページをリロード**
   - Console出力を確認: `Loaded roles: 11 items`

4. **Cloud SQL同期ボタンをクリック**
   - Console出力を確認: `Using roles from Supabase table: 11 roles`
   - 同期成功メッセージを確認

#### テスト2: 役職ドロップダウン

1. **社員追加フォームを開く**
   - 「社員追加」ボタンをクリック

2. **役職ドロップダウンを確認**
   - 11件の役職が表示されている
   - 「代表取締役」が最上位

3. **既存社員の編集**
   - 既存社員を選択して編集フォームを開く
   - 役職を選択して保存
   - 再度開いて保存されていることを確認

#### テスト3: 同期確認

1. **Cloud SQLで同期結果を確認**
   ```sql
   -- rolesのexternal_idを確認
   SELECT id, name, level, external_id
   FROM roles
   WHERE external_id IS NOT NULL;
   ```

2. **期待結果**
   - external_idに `role_ceo`, `role_employee` などが設定されている

---

## トラブルシューティング

### 問題1: Supabaseでテーブル作成エラー

**症状**: `relation "roles" already exists`

**対処**:
- エラーを無視してOK（IF NOT EXISTSで対応済み）
- または、既存テーブルを確認: `SELECT * FROM roles;`

### 問題2: Cloud SQLで外部キーエラー

**症状**: `insert or update on table "user_departments" violates foreign key constraint`

**対処**:
- rolesテーブルにデータがあることを確認
- 同期を再実行

### 問題3: 同期ボタンでエラー

**症状**: Console にエラーが表示される

**対処**:
1. Network タブで API レスポンスを確認
2. Supabase の RLS ポリシーを確認
3. Cloud SQL の接続設定を確認

### 問題4: 役職ドロップダウンが空

**症状**: 役職が表示されない

**対処**:
1. Console で `roles` 変数を確認: `console.log(roles)`
2. Supabase の roles テーブルを確認
3. RLS ポリシーが SELECT を許可しているか確認

---

## ロールバック手順

### Supabaseロールバック

```sql
-- 注意: データも削除されます
ALTER TABLE employees DROP COLUMN IF EXISTS role_id;
DROP INDEX IF EXISTS idx_employees_role_id;

DROP POLICY IF EXISTS "roles_select_policy" ON roles;
DROP POLICY IF EXISTS "roles_insert_policy" ON roles;
DROP POLICY IF EXISTS "roles_update_policy" ON roles;
DROP POLICY IF EXISTS "roles_delete_policy" ON roles;
ALTER TABLE roles DISABLE ROW LEVEL SECURITY;

DROP TABLE IF EXISTS roles CASCADE;
```

### Cloud SQLロールバック

```sql
-- 注意: データも削除されます
ALTER TABLE chatwork_tasks DROP COLUMN IF EXISTS department_id;
DROP INDEX IF EXISTS idx_chatwork_tasks_department;

ALTER TABLE user_departments DROP COLUMN IF EXISTS role_id;
DROP INDEX IF EXISTS idx_user_departments_role;

ALTER TABLE roles DROP CONSTRAINT IF EXISTS roles_external_id_key;
ALTER TABLE roles DROP COLUMN IF EXISTS external_id;
DROP INDEX IF EXISTS idx_roles_external_id;
```

---

## 完了後のチェックリスト

### 必須確認

- [ ] Supabase: rolesテーブルに11件のデータがある
- [ ] Cloud SQL: roles.external_idカラムが存在する
- [ ] Cloud SQL: user_departments.role_idカラムが存在する
- [ ] Cloud SQL: chatwork_tasks.department_idカラムが存在する
- [ ] 組織図: 役職ドロップダウンに11件表示される
- [ ] 同期: Cloud SQL同期が成功する

### 推奨確認

- [ ] 既存社員に役職を設定できる
- [ ] 設定した役職が保存・表示される
- [ ] access_control.py のクエリが正常に動作する

---

## 次のステップ

1. **既存社員への役職設定**
   - 組織図UIから各社員に役職を設定
   - 特に代表、管理部、課長などの権限が必要なメンバー

2. **タスクへの部署設定（オプション）**
   - 既存タスクに部署を設定する場合は、マイグレーションSQLのSTEP 5を実行

3. **アクセス制御の本番テスト**
   - ChatWorkのタスク検索で権限フィルタが効いているか確認

---

## 設計との整合性確認結果

### 確認済み項目

| 項目 | 設計書 | 実装 | 整合性 |
|------|--------|------|--------|
| roles.level | 1-6の6段階 | CHECK制約あり | OK |
| roles.external_id | Supabase連携用 | VARCHAR(100) UNIQUE | OK |
| user_departments.role_id | 権限計算用FK | UUID REFERENCES roles | OK |
| chatwork_tasks.department_id | アクセス制御用 | UUID REFERENCES departments | OK |
| LTREE使用 | departments.path | <@ 演算子使用 | OK |
| organization_idフィルタ | テナント分離 | 全クエリに追加済み | OK |

### 将来拡張への準備

| Phase | 必要な準備 | 状態 |
|-------|-----------|------|
| Phase 3 (ナレッジ) | classification対応 | 設計済み |
| Phase 4A (テナント分離) | RLS準備 | lib/tenant.py作成済み |
| Phase 4B (外部連携API) | external_id | 実装済み |

---

## 問合せ先

技術的な問題が発生した場合は、このドキュメントとテスト計画書を参照の上、
Claude Code にエラーメッセージと実行環境を共有してください。

---

以上
