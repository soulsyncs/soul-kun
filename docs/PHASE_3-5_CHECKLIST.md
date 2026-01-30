# Phase 3.5 実装チェックリスト

**プロジェクト:** ソウルくん組織図・権限管理システム
**作成日:** 2026年1月19日
**総工数:** 50時間（約6日）

---

## Document Contract（SoT宣言）

| 項目 | 内容 |
|------|------|
| **この文書の役割** | Phase 3.5 実装作業のチェックリスト・手順書 |
| **書くこと** | 各実装ステップの手順、確認コマンド、期待結果、トラブルシューティング |
| **書かないこと** | 設計の詳細・根拠（→PHASE_3-5_DETAILED_DESIGN.md参照） |
| **SoT（この文書が正）** | Phase 3.5の実装手順、各ステップの完了条件、デプロイ手順 |
| **Owner** | Tech Lead |
| **更新トリガー** | 実装手順の変更、新しいステップの追加、完了条件の変更 |

---

## 実装前の準備

### 環境確認

- [ ] Supabaseにログインできる
  - URL: https://app.supabase.com/
  - プロジェクト: adzxpeboaoiojepcxlyc

- [ ] Cloud SQLに接続できる
  - 接続方法: `gcloud sql connect soulkun-db --user=postgres`
  - または: Cloud SQL Auth Proxy経由

- [ ] 組織図システム（app.js）のコードがローカルにある
  - パス: `/Users/kikubookair/Desktop/org-chart/js/app.js`

- [ ] ソウルくんのコードがローカルにある
  - パス: `/Users/kikubookair/soul-kun/`

### バックアップ

- [ ] Supabaseのemployeesテーブルをバックアップ
  - `SELECT * FROM employees` → CSV出力

- [ ] Cloud SQLのrolesテーブルをバックアップ
  - `pg_dump -t roles > roles_backup.sql`

---

## Phase A: 基盤整備（14時間）

### A1. Supabaseにrolesテーブルを作成（3時間）

- [ ] Supabase SQLエディタを開く
- [ ] `migrations/phase_3-5_supabase.sql`の内容をコピー
- [ ] STEP 1〜3を順番に実行
- [ ] 確認: `SELECT * FROM roles` で11件表示
- [ ] 確認: RLSが有効（`SELECT relrowsecurity FROM pg_class WHERE relname = 'roles'`）

**期待結果:**
```
role_ceo | 代表取締役 | 6
role_cfo | CFO | 6
...（11件）
```

### A2. Supabaseのemployeesテーブル修正（1時間）

- [ ] STEP 4を実行
- [ ] 確認: `SELECT column_name FROM information_schema.columns WHERE table_name = 'employees' AND column_name = 'role_id'`
- [ ] 確認: 既存社員のrole_idは全てNULL

**期待結果:**
```
role_id カラムが存在し、全てNULL
```

### A3. Cloud SQLのrolesテーブル修正（2時間）

- [ ] Cloud SQLに接続
- [ ] 現状確認: `\d roles`
- [ ] external_idが存在しない場合、`migrations/phase_3-5_cloudsql.sql`のSTEP 2を実行
- [ ] 確認: `\d roles` でexternal_idカラムが表示

**期待結果:**
```
external_id | character varying(100) |
```

- [ ] `api/app/models/user.py`を開く
- [ ] Roleクラスに`external_id`を追加:
  ```python
  external_id = Column(String(100), unique=True, nullable=True)
  ```
- [ ] 変更をコミット

### A4. 組織図システム（app.js）の改修（8時間）

#### A4-1. loadData関数の修正

- [ ] app.jsを開く（/Users/kikubookair/Desktop/org-chart/js/app.js）
- [ ] 89行目付近のloadData関数を探す
- [ ] roles読み込みコードを追加:

```javascript
// 役職データの読み込み（追加）
const rolesResponse = await fetch(`${SUPABASE_REST_URL}/roles?is_active=eq.true&order=display_order`, {
    headers: {
        'Authorization': `Bearer ${SUPABASE_ANON_KEY}`,
        'apikey': SUPABASE_ANON_KEY,
        'Content-Type': 'application/json'
    }
});
roles = await rolesResponse.json() || [];
```

- [ ] 確認: ブラウザコンソールで `console.log(roles)` → 11件表示

#### A4-2. populateRoleSelect関数の作成

- [ ] 以下の関数を追加:

```javascript
// 役職プルダウンを生成
function populateRoleSelect(selectElementId, selectedRoleId = null) {
    const select = document.getElementById(selectElementId);
    if (!select) return;

    select.innerHTML = '<option value="">役職を選択...</option>';

    roles.forEach(role => {
        const option = document.createElement('option');
        option.value = role.id;
        option.textContent = `${role.name}（Level ${role.level}）`;
        if (selectedRoleId === role.id) {
            option.selected = true;
        }
        select.appendChild(option);
    });
}
```

#### A4-3. 社員追加フォームの修正

- [ ] addEmployeeForm関数を探す
- [ ] positionのinputをselectに変更:

```html
<select id="addEmpRoleId" class="form-select">
    <option value="">役職を選択...</option>
</select>
```

- [ ] フォーム表示時に`populateRoleSelect('addEmpRoleId')`を呼び出す

#### A4-4. 社員編集フォームの修正

- [ ] editEmployeeForm関数を探す
- [ ] positionのinputをselectに変更
- [ ] フォーム表示時に`populateRoleSelect('editEmpRoleId', employee.role_id)`を呼び出す

#### A4-5. 社員保存処理の修正

- [ ] saveEmployee関数を探す
- [ ] role_idを取得して保存に含める:

```javascript
const roleId = document.getElementById('addEmpRoleId').value || null;
// ...
const employeeData = {
    // ...
    role_id: roleId,
};
```

#### A4-6. 動作確認

- [ ] ローカルでindex.htmlを開く
- [ ] 社員追加で役職プルダウンが表示される
- [ ] 役職を選択して保存できる
- [ ] 編集画面で既存の役職が選択状態

#### A4-7. デプロイ

- [ ] 変更をGitHubにプッシュ
- [ ] 本番環境で動作確認

---

## Phase B: 同期機能強化（6時間）

### B1. 同期APIの改修（4時間）

#### B1-1. ハードコード削除

- [ ] app.jsの3466-3476行目を探す（rolelevelsハードコード）
- [ ] 以下のコードを削除:

```javascript
// 削除対象
const rolelevels = {
    'CEO': 1, '代表': 1, '社長': 1,
    // ...
};
```

#### B1-2. rolesテーブルから取得に変更

- [ ] 3458行目付近のmappedRoles生成を修正:

```javascript
// 修正後
const mappedRoles = roles
    .filter(r => r.is_active !== false)
    .map(r => ({
        id: r.id,
        name: r.name,
        level: r.level,
        description: r.description
    }));
```

#### B1-3. mappedEmployeesにrole_idを含める

- [ ] 3501行目付近のmappedEmployees生成を修正:

```javascript
const mappedEmployees = employees.map(e => ({
    id: String(e.id),
    name: e.name,
    email: e.email || `${String(e.id).replace(/-/g, '')}@example.com`,
    departmentId: String(e.department_id),
    roleId: e.role_id || null,  // ← 修正
    isPrimary: true,
    startDate: null,
    endDate: null
}));
```

#### B1-4. デプロイ

- [ ] 変更をGitHubにプッシュ
- [ ] 本番環境で動作確認

### B2. 同期ボタンの動作確認（2時間）

- [ ] 組織図で「ソウルくんに同期」ボタンを押下
- [ ] 成功メッセージが表示される
- [ ] ソウルくんのCloud SQLでrolesを確認:
  ```sql
  SELECT id, name, level, external_id FROM roles;
  ```
- [ ] external_idにSupabaseのroles.idが設定されている
- [ ] 同期ログを確認:
  ```sql
  SELECT * FROM org_chart_sync_logs ORDER BY created_at DESC LIMIT 1;
  ```

---

## Phase C: タスク管理連携（6時間）

### C1. chatwork_tasksにdepartment_id追加（2時間）

- [ ] Cloud SQLに接続
- [ ] `migrations/phase_3-5_cloudsql.sql`のSTEP 3を実行
- [ ] 確認: `\d chatwork_tasks` でdepartment_idカラムが表示

### C2. タスク作成時に部署を自動設定（4時間）

#### C2-1. タスク作成処理の確認

- [ ] main.pyを開く
- [ ] chatwork_tasksへのINSERT処理を探す（468行目付近）

#### C2-2. 担当者の部署取得ロジック追加

- [ ] 以下のヘルパー関数を追加:

```python
def get_user_primary_department(chatwork_account_id):
    """担当者のメイン部署IDを取得"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ud.department_id
            FROM user_departments ud
            JOIN users u ON ud.user_id = u.id
            WHERE u.chatwork_account_id = %s
              AND ud.is_primary = TRUE
              AND ud.ended_at IS NULL
            LIMIT 1
        """, (chatwork_account_id,))
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        conn.close()
```

#### C2-3. INSERT文にdepartment_idを追加

- [ ] chatwork_tasksへのINSERT文を修正:

```python
department_id = get_user_primary_department(assigned_to_account_id)

cursor.execute("""
    INSERT INTO chatwork_tasks
    (task_id, room_id, assigned_to_account_id, ..., department_id)
    VALUES (%s, %s, %s, ..., %s)
""", (task_id, room_id, assigned_to_account_id, ..., department_id))
```

#### C2-4. デプロイ

- [ ] 変更をGitHubにプッシュ
- [ ] Cloud Functionsにデプロイ
- [ ] テストタスクを作成して確認

---

## Phase D: アクセス制御（12時間）

### D1. compute_accessible_departments実装（6時間）

- [ ] `api/app/services/access_control.py`を新規作成
- [ ] 以下の関数を実装:

```python
async def compute_accessible_departments(user_id: str) -> List[str]:
    """ユーザーがアクセス可能な部署IDのリストを返す"""
    # 実装は詳細設計書の第6章を参照
    pass

async def get_user_role_level(user_id: str) -> int:
    """ユーザーの権限レベルを取得"""
    pass

async def get_all_descendants(dept_id: str) -> List[str]:
    """部署の全配下を取得"""
    pass

async def get_direct_children(dept_id: str) -> List[str]:
    """部署の直下の子を取得"""
    pass
```

- [ ] 単体テスト作成・実行

### D2. タスク検索への統合（6時間）

- [ ] `chatwork-webhook/main.py`を開く
- [ ] `search_tasks_from_db`関数を探す（1516行目付近）
- [ ] compute_accessible_departmentsを呼び出し
- [ ] WHERE句にdepartment_idフィルタを追加:

```python
accessible_depts = compute_accessible_departments(user_id)

query = """
    SELECT * FROM chatwork_tasks
    WHERE (
        department_id IN (:dept_ids)
        OR department_id IS NULL  -- 部署未設定のタスクも表示
    )
    AND status = 'open'
"""
```

- [ ] デプロイ
- [ ] テスト: 各権限レベルでタスク検索を実行

---

## テストフェーズ（12時間）

### 単体テスト（4時間）

- [ ] 権限計算テスト（18ケース）
- [ ] 同期APIテスト（6ケース）
- [ ] UIテスト（6ケース）

### 結合テスト（4時間）

- [ ] 同期フローテスト
  - [ ] 組織図で役職を変更
  - [ ] 同期ボタンを押下
  - [ ] ソウルくんに反映を確認

- [ ] 権限フィルタテスト
  - [ ] Level 6でタスク検索 → 全タスク表示
  - [ ] Level 4でタスク検索 → 自部署＋配下
  - [ ] Level 2でタスク検索 → 自部署のみ

### E2Eテスト（2時間）

- [ ] シナリオ1: 新規社員登録→同期→タスク検索
- [ ] シナリオ2: 役職変更→同期→権限反映確認

### バグ修正・調整（2時間）

- [ ] 発見したバグの修正
- [ ] パフォーマンス調整
- [ ] ドキュメント更新

---

## 完了確認

### 最終チェックリスト

- [ ] rolesテーブルに11件の役職がある（Supabase & Cloud SQL）
- [ ] 組織図で役職プルダウンが表示される
- [ ] 役職を選択して社員を保存できる
- [ ] 同期ボタンでソウルくんに役職が同期される
- [ ] タスクにdepartment_idが設定される
- [ ] 「自分のタスクを教えて」で権限に応じたタスクが表示される

### 手動移行

- [ ] カズさん（CEO）→ role_ceo を設定
- [ ] その他の社員 → 適切なrole_idを設定

---

## トラブルシューティング

### Q: rolesテーブルが作成されない

**A:** Supabaseの権限を確認してください。SQLエディタで以下を実行:
```sql
SELECT current_user;
-- postgresまたはservice_roleであることを確認
```

### Q: 同期ボタンでエラーが出る

**A:** ブラウザのコンソールでエラーを確認してください。よくある原因:
- CORS設定
- APIエンドポイントのURL間違い
- 認証トークンの期限切れ

### Q: department_idがNULLのまま

**A:** 以下を確認してください:
1. 担当者のchatwork_account_idがusersテーブルに存在するか
2. user_departmentsに所属情報があるか
3. is_primary = TRUE で ended_at IS NULL の条件を満たすか

---

**このチェックリストを使って、Phase 3.5の実装を進めてください。**
