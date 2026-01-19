# Phase 3.5 動作確認テスト計画書

## 目次
1. [テスト概要](#テスト概要)
2. [テスト環境](#テスト環境)
3. [テストカテゴリ](#テストカテゴリ)
4. [テストケース詳細](#テストケース詳細)
5. [テスト実行手順](#テスト実行手順)
6. [テスト結果記録シート](#テスト結果記録シート)

---

## テスト概要

### 目的
Phase 3.5で実装した以下の機能が正しく動作することを確認する：

1. **rolesテーブル**: Supabaseでの役職マスタ管理
2. **external_id同期**: Supabase ↔ Cloud SQL間の役職データ同期
3. **user_departments.role_id**: ユーザーの権限レベル計算
4. **chatwork_tasks.department_id**: タスクのアクセス制御
5. **access_control.py**: 6段階権限レベルによるアクセス制御

### テスト範囲
| カテゴリ | 対象 | 重要度 |
|---------|------|--------|
| DB構造 | rolesテーブル | 高 |
| DB構造 | user_departments.role_id | 高 |
| DB構造 | chatwork_tasks.department_id | 中 |
| 同期 | 組織図 → Cloud SQL | 高 |
| UI | 役職ドロップダウン | 中 |
| API | アクセス制御 | 高 |

---

## テスト環境

### Supabase（組織図システム）
- **URL**: https://app.supabase.com/
- **プロジェクト**: org-chart
- **テスト方法**: SQL Editor / app.js

### Cloud SQL（ソウルくん）
- **接続**: `gcloud sql connect soulkun-db --user=postgres`
- **テスト方法**: psql / SQLクエリ

### 組織図フロントエンド
- **URL**: /Users/kikubookair/Desktop/org-chart/index.html
- **テスト方法**: ブラウザ / DevTools Console

---

## テストカテゴリ

### カテゴリA: データベース構造テスト
- A-1: rolesテーブル構造（Supabase）
- A-2: rolesテーブル構造（Cloud SQL）
- A-3: user_departments.role_idカラム
- A-4: chatwork_tasks.department_idカラム
- A-5: 外部キー制約
- A-6: インデックス

### カテゴリB: 初期データテスト
- B-1: roles初期データ（11件）
- B-2: 権限レベルの分布確認

### カテゴリC: 同期テスト
- C-1: 組織図同期ボタン
- C-2: roles同期（Supabase → Cloud SQL）
- C-3: employees同期
- C-4: departments同期

### カテゴリD: UIテスト
- D-1: 役職ドロップダウン表示
- D-2: 役職選択・保存
- D-3: 既存社員の役職表示

### カテゴリE: アクセス制御テスト
- E-1: get_user_role_level()
- E-2: compute_accessible_departments()
- E-3: タスク検索フィルタリング

### カテゴリF: エラーハンドリングテスト
- F-1: DB接続エラー時の挙動
- F-2: 不正データ時の挙動

---

## テストケース詳細

### A-1: rolesテーブル構造（Supabase）

**目的**: rolesテーブルが正しい構造で作成されていることを確認

**テスト手順**:
```sql
-- Supabase SQL Editor で実行
SELECT
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'roles'
ORDER BY ordinal_position;
```

**期待結果**:
| column_name | data_type | is_nullable |
|-------------|-----------|-------------|
| id | text | NO |
| name | text | NO |
| level | integer | NO |
| description | text | YES |
| display_order | integer | YES |
| is_active | boolean | YES |
| created_at | timestamp with time zone | YES |
| updated_at | timestamp with time zone | YES |

**判定基準**: 全カラムが期待通りの型で存在する → PASS

---

### A-2: rolesテーブル構造（Cloud SQL）

**目的**: Cloud SQLのrolesテーブルにexternal_idカラムが追加されていることを確認

**テスト手順**:
```sql
-- Cloud SQL で実行
SELECT
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns
WHERE table_name = 'roles'
  AND table_schema = 'public'
ORDER BY ordinal_position;
```

**期待結果**:
- `external_id` カラムが存在する
- 型は `character varying(100)` または `text`
- UNIQUE制約がある

**追加確認**:
```sql
-- UNIQUE制約の確認
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'roles' AND indexname LIKE '%external_id%';
```

**判定基準**: external_idカラムとUNIQUE制約が存在する → PASS

---

### A-3: user_departments.role_idカラム

**目的**: user_departmentsテーブルにrole_idカラムが追加されていることを確認

**テスト手順**:
```sql
-- Cloud SQL で実行
SELECT
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns
WHERE table_name = 'user_departments'
  AND column_name = 'role_id';
```

**期待結果**:
- `role_id` カラムが存在する
- 型は `uuid`
- rolesテーブルへの外部キー制約がある

**追加確認**:
```sql
-- 外部キー制約の確認
SELECT
    tc.constraint_name,
    kcu.column_name,
    ccu.table_name AS foreign_table_name
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
    ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage ccu
    ON ccu.constraint_name = tc.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND tc.table_name = 'user_departments'
  AND kcu.column_name = 'role_id';
```

**判定基準**: role_idカラムと外部キー制約が存在する → PASS

---

### A-4: chatwork_tasks.department_idカラム

**目的**: chatwork_tasksテーブルにdepartment_idカラムが追加されていることを確認

**テスト手順**:
```sql
-- Cloud SQL で実行
SELECT
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns
WHERE table_name = 'chatwork_tasks'
  AND column_name = 'department_id';
```

**期待結果**:
- `department_id` カラムが存在する
- 型は `uuid`
- departmentsテーブルへの外部キー制約がある

**判定基準**: department_idカラムと外部キー制約が存在する → PASS

---

### B-1: roles初期データ（11件）

**目的**: Supabaseに11件の役職データが正しく投入されていることを確認

**テスト手順**:
```sql
-- Supabase SQL Editor で実行
SELECT id, name, level, display_order
FROM roles
WHERE is_active = TRUE
ORDER BY display_order;
```

**期待結果**:
| id | name | level | display_order |
|----|------|-------|---------------|
| role_ceo | 代表取締役 | 6 | 1 |
| role_cfo | CFO | 6 | 2 |
| role_coo | COO | 6 | 3 |
| role_admin_mgr | 管理部マネージャー | 5 | 4 |
| role_admin_staff | 管理部スタッフ | 5 | 5 |
| role_director | 取締役 | 4 | 6 |
| role_dept_head | 部長 | 4 | 7 |
| role_section_head | 課長 | 3 | 8 |
| role_leader | リーダー | 3 | 9 |
| role_employee | 社員 | 2 | 10 |
| role_contractor | 業務委託 | 1 | 11 |

**判定基準**: 11件が正しいlevelとdisplay_orderで存在する → PASS

---

### B-2: 権限レベルの分布確認

**目的**: 各権限レベルに適切な数の役職が存在することを確認

**テスト手順**:
```sql
-- Supabase SQL Editor で実行
SELECT
    level,
    COUNT(*) as count,
    STRING_AGG(name, ', ') as roles
FROM roles
WHERE is_active = TRUE
GROUP BY level
ORDER BY level DESC;
```

**期待結果**:
| level | count | roles |
|-------|-------|-------|
| 6 | 3 | 代表取締役, CFO, COO |
| 5 | 2 | 管理部マネージャー, 管理部スタッフ |
| 4 | 2 | 取締役, 部長 |
| 3 | 2 | 課長, リーダー |
| 2 | 1 | 社員 |
| 1 | 1 | 業務委託 |

**判定基準**: 各レベルに正しい数の役職が存在する → PASS

---

### C-1: 組織図同期ボタン

**目的**: 組織図システムの同期ボタンが正しく動作することを確認

**テスト手順**:
1. `/Users/kikubookair/Desktop/org-chart/index.html` を開く
2. DevTools Console を開く（F12）
3. 「Cloud SQL同期」ボタンをクリック
4. Console出力とUIを確認

**期待結果**:
- Console: `Using roles from Supabase table: 11 roles`
- Console: `Sync successful!` または類似メッセージ
- UI: 「同期成功」通知が表示

**エラー時の確認**:
- Console: エラーメッセージを確認
- Network: APIリクエストの応答を確認

**判定基準**: 同期が成功し、エラーが発生しない → PASS

---

### C-2: roles同期（Supabase → Cloud SQL）

**目的**: Supabaseのrolesデータが正しくCloud SQLに同期されることを確認

**テスト手順**:
```sql
-- 同期後、Cloud SQL で実行
SELECT
    id,
    name,
    level,
    external_id,
    is_active
FROM roles
WHERE external_id IS NOT NULL
ORDER BY level DESC, name;
```

**期待結果**:
- `external_id` に Supabase の `roles.id` が設定されている
  - 例: `external_id = 'role_ceo'`
- `name`, `level` が Supabase と一致

**判定基準**: external_idが正しく設定され、データが一致する → PASS

---

### D-1: 役職ドロップダウン表示

**目的**: 組織図UIの役職ドロップダウンに全11件が表示されることを確認

**テスト手順**:
1. 組織図システムを開く
2. 「社員追加」フォームを開く
3. 役職ドロップダウンを確認

**期待結果**:
- 11件の役職が表示される
- 表示順がdisplay_order順（代表取締役が最上位）
- 「役職を選択...」のプレースホルダーがある

**判定基準**: 全11件が正しい順序で表示される → PASS

---

### D-2: 役職選択・保存

**目的**: 社員に役職を設定し、保存できることを確認

**テスト手順**:
1. 既存社員の編集フォームを開く
2. 役職ドロップダウンから「課長」を選択
3. 保存
4. 再度開いて確認

**期待結果**:
- 保存成功の通知が表示
- 再度開くと「課長」が選択されている
- Supabase: `employees.role_id = 'role_section_head'`

**確認クエリ**:
```sql
-- Supabase SQL Editor で実行
SELECT id, name, role_id FROM employees WHERE name = 'テスト社員名';
```

**判定基準**: role_idが正しく保存・表示される → PASS

---

### E-1: get_user_role_level()

**目的**: ユーザーの権限レベルが正しく取得されることを確認

**テスト手順**:
```sql
-- Cloud SQL で実行
-- テストユーザーにrole_idを設定
UPDATE user_departments
SET role_id = (SELECT id FROM roles WHERE external_id = 'role_section_head' LIMIT 1)
WHERE user_id = 'テストユーザーID'
  AND ended_at IS NULL;

-- 権限レベルを取得（access_control.py:83-89 相当）
SELECT COALESCE(MAX(r.level), 2) as max_level
FROM user_departments ud
JOIN roles r ON ud.role_id = r.id
WHERE ud.user_id = 'テストユーザーID'
  AND ud.ended_at IS NULL;
```

**期待結果**:
- `max_level = 3`（課長はLevel 3）

**判定基準**: 正しい権限レベルが返される → PASS

---

### E-2: compute_accessible_departments()

**目的**: ユーザーがアクセス可能な部署が正しく計算されることを確認

**テスト手順**:
```sql
-- Cloud SQL で実行
-- Level 3（課長）の場合: 自部署＋直下部署

-- 1. ユーザーの所属部署を取得
SELECT department_id FROM user_departments
WHERE user_id = 'テストユーザーID' AND ended_at IS NULL;

-- 2. 直下部署を取得（access_control.py:182-188 相当）
SELECT id FROM departments
WHERE parent_id = '所属部署ID'
  AND organization_id = 'org_soulsyncs'
  AND is_active = TRUE;
```

**期待結果**:
- 自部署が含まれる
- 直下部署が含まれる
- 他部署は含まれない

**判定基準**: アクセス可能な部署が正しく計算される → PASS

---

### F-1: DB接続エラー時の挙動

**目的**: DB接続エラー時にデフォルト値が返されることを確認

**テスト手順**:
1. access_control.pyのログ出力を確認
2. 意図的にエラーを発生させる（不正なuser_id等）

**期待結果**:
- エラーログが出力される
- get_user_role_level(): `2` が返される
- compute_accessible_departments(): `[]` が返される

**判定基準**: デフォルト値が返され、クラッシュしない → PASS

---

## テスト実行手順

### 実行順序

1. **事前準備**
   - [ ] Cloud SQLバックアップを取得
   - [ ] Supabaseのデータをエクスポート

2. **マイグレーション実行**
   - [ ] Supabaseマイグレーション実行（phase_3-5_supabase_complete.sql）
   - [ ] Cloud SQLマイグレーション実行（phase_3-5_cloudsql_complete.sql）

3. **カテゴリA: DB構造テスト**
   - [ ] A-1: rolesテーブル構造（Supabase）
   - [ ] A-2: rolesテーブル構造（Cloud SQL）
   - [ ] A-3: user_departments.role_idカラム
   - [ ] A-4: chatwork_tasks.department_idカラム

4. **カテゴリB: 初期データテスト**
   - [ ] B-1: roles初期データ（11件）
   - [ ] B-2: 権限レベルの分布確認

5. **カテゴリC: 同期テスト**
   - [ ] C-1: 組織図同期ボタン
   - [ ] C-2: roles同期確認

6. **カテゴリD: UIテスト**
   - [ ] D-1: 役職ドロップダウン表示
   - [ ] D-2: 役職選択・保存

7. **カテゴリE: アクセス制御テスト**
   - [ ] E-1: get_user_role_level()
   - [ ] E-2: compute_accessible_departments()

8. **カテゴリF: エラーハンドリングテスト**
   - [ ] F-1: DB接続エラー時の挙動

---

## テスト結果記録シート

| テストID | テスト名 | 結果 | 備考 | 実行日 | 実行者 |
|----------|----------|------|------|--------|--------|
| A-1 | rolesテーブル構造（Supabase） | [ ]PASS / [ ]FAIL | | | |
| A-2 | rolesテーブル構造（Cloud SQL） | [ ]PASS / [ ]FAIL | | | |
| A-3 | user_departments.role_idカラム | [ ]PASS / [ ]FAIL | | | |
| A-4 | chatwork_tasks.department_idカラム | [ ]PASS / [ ]FAIL | | | |
| B-1 | roles初期データ（11件） | [ ]PASS / [ ]FAIL | | | |
| B-2 | 権限レベルの分布確認 | [ ]PASS / [ ]FAIL | | | |
| C-1 | 組織図同期ボタン | [ ]PASS / [ ]FAIL | | | |
| C-2 | roles同期確認 | [ ]PASS / [ ]FAIL | | | |
| D-1 | 役職ドロップダウン表示 | [ ]PASS / [ ]FAIL | | | |
| D-2 | 役職選択・保存 | [ ]PASS / [ ]FAIL | | | |
| E-1 | get_user_role_level() | [ ]PASS / [ ]FAIL | | | |
| E-2 | compute_accessible_departments() | [ ]PASS / [ ]FAIL | | | |
| F-1 | DB接続エラー時の挙動 | [ ]PASS / [ ]FAIL | | | |

---

## 問題発生時の対応

### ロールバック手順

1. **Cloud SQL**:
   ```sql
   -- phase_3-5_cloudsql_complete.sql の最後のロールバックSQLを実行
   ```

2. **Supabase**:
   ```sql
   -- phase_3-5_supabase_complete.sql の最後のロールバックSQLを実行
   ```

### エスカレーション先

- 技術的問題: Claude Code
- ビジネス判断: カズさん

---

## 将来の拡張に向けた確認事項

### Phase 4A（テナント分離）への準備
- [ ] organization_idフィルタが全クエリに含まれている
- [ ] RLS準備が完了（lib/tenant.py）

### Phase 3（ナレッジ系）への準備
- [ ] classificationカラムの追加余地がある
- [ ] アクセス制御がclassificationを考慮できる設計

---

以上
