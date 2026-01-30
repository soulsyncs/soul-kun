# Row Level Security（RLS）ポリシー設計書

**作成日:** 2026-01-30
**目的:** Phase 4（マルチテナント）移行に向けたRLSポリシーの設計
**前提:** PostgreSQLのRow Level Security機能を使用

---

## Document Contract（SoT宣言）

| 項目 | 内容 |
|------|------|
| **この文書の役割** | RLSポリシーの設計仕様と実装ガイド |
| **書くこと** | ポリシー定義、設定方法、移行手順、検証方法 |
| **書かないこと** | 実装コード（→マイグレーションファイル）、監査結果（→SECURITY_AUDIT_ORGANIZATION_ID.md） |
| **SoT（この文書が正）** | RLSポリシー設計の全仕様 |
| **Owner** | Tech Lead（連絡先: #dev チャンネル） |
| **更新トリガー** | ポリシー変更時、テーブル追加時 |

---

## 1. RLSの目的と効果

### 1.1 なぜRLSが必要か

```
【アプリケーション層のみの防御（現状）】
  ユーザー → API → WHERE organization_id = ? → DB
                    ↑
              ここを忘れるとデータ漏洩

【RLSによる二重防御（目標）】
  ユーザー → API → WHERE organization_id = ? → DB
                                               ↓
                                         RLSポリシーで再検証
                                         （アプリが忘れても安全）
```

### 1.2 RLSの効果

| 効果 | 説明 |
|------|------|
| **データ漏洩防止** | クエリにWHERE句を忘れても、RLSがフィルタ |
| **SQLインジェクション耐性** | 攻撃者がSQLを注入しても、テナント外データにアクセス不可 |
| **開発者の負担軽減** | 毎回organization_idを意識しなくてよい |
| **監査対応** | 「DBレベルでテナント分離している」と説明可能 |

---

## 2. テナントコンテキストの設定

### 2.1 設計方針

PostgreSQLのセッション変数（`current_setting`）を使用してテナントIDを設定。

```sql
-- テナントコンテキストを設定（各リクエストの最初に実行）
SET app.current_tenant = 'org_soulsyncs';

-- 後続のクエリは自動的にこのテナントでフィルタされる
SELECT * FROM chatwork_tasks;  -- RLSにより自動フィルタ
```

### 2.2 Pythonでの設定方法

```python
async def set_tenant_context(conn, organization_id: str):
    """
    テナントコンテキストを設定

    全てのDB接続取得時に呼び出す
    """
    await conn.execute(
        "SET app.current_tenant = $1",
        organization_id
    )

# 使用例
async with get_db_connection() as conn:
    await set_tenant_context(conn, user.organization_id)
    # 以降のクエリは自動的にフィルタされる
    result = await conn.fetch("SELECT * FROM chatwork_tasks")
```

### 2.3 FastAPIでの統合

```python
from fastapi import Depends, Request

async def get_db_with_tenant(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    テナントコンテキストを設定したDB接続を取得
    """
    # X-Tenant-ID ヘッダーから取得（Phase 4）
    tenant_id = request.headers.get("X-Tenant-ID", "org_soulsyncs")

    await db.execute(text(f"SET app.current_tenant = '{tenant_id}'"))

    return db
```

---

## 3. テーブル別RLSポリシー

### 3.1 対象テーブル一覧

| テーブル | RLS | ポリシー名 | 対象操作 |
|---------|-----|-----------|---------|
| chatwork_tasks | 必須 | tenant_isolation_tasks | ALL |
| system_config | 必須 | tenant_isolation_config | ALL |
| excluded_rooms | 必須 | tenant_isolation_rooms | ALL |
| soulkun_insights | 必須 | tenant_isolation_insights | ALL |
| soulkun_weekly_reports | 必須 | tenant_isolation_reports | ALL |
| audit_logs | 必須 | tenant_isolation_audit | ALL |
| departments | 必須 | tenant_isolation_depts | ALL |
| users | 必須 | tenant_isolation_users | ALL |
| user_departments | 不要 | - | - |

### 3.2 ポリシー定義

#### chatwork_tasks

```sql
-- RLSを有効化
ALTER TABLE chatwork_tasks ENABLE ROW LEVEL SECURITY;

-- デフォルト拒否（ポリシーにマッチしなければアクセス不可）
ALTER TABLE chatwork_tasks FORCE ROW LEVEL SECURITY;

-- テナント分離ポリシー
CREATE POLICY tenant_isolation_tasks ON chatwork_tasks
    USING (organization_id = current_setting('app.current_tenant', true))
    WITH CHECK (organization_id = current_setting('app.current_tenant', true));

-- 説明:
-- USING: SELECT/UPDATE/DELETE時のフィルタ条件
-- WITH CHECK: INSERT/UPDATE時の値検証
```

#### system_config

```sql
ALTER TABLE system_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE system_config FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_config ON system_config
    USING (organization_id = current_setting('app.current_tenant', true))
    WITH CHECK (organization_id = current_setting('app.current_tenant', true));
```

#### excluded_rooms

```sql
ALTER TABLE excluded_rooms ENABLE ROW LEVEL SECURITY;
ALTER TABLE excluded_rooms FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_rooms ON excluded_rooms
    USING (organization_id = current_setting('app.current_tenant', true))
    WITH CHECK (organization_id = current_setting('app.current_tenant', true));
```

#### soulkun_insights

```sql
ALTER TABLE soulkun_insights ENABLE ROW LEVEL SECURITY;
ALTER TABLE soulkun_insights FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_insights ON soulkun_insights
    USING (organization_id = current_setting('app.current_tenant', true))
    WITH CHECK (organization_id = current_setting('app.current_tenant', true));
```

#### soulkun_weekly_reports

```sql
ALTER TABLE soulkun_weekly_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE soulkun_weekly_reports FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_reports ON soulkun_weekly_reports
    USING (organization_id = current_setting('app.current_tenant', true))
    WITH CHECK (organization_id = current_setting('app.current_tenant', true));
```

#### audit_logs

```sql
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_audit ON audit_logs
    USING (organization_id = current_setting('app.current_tenant', true))
    WITH CHECK (organization_id = current_setting('app.current_tenant', true));
```

#### departments

```sql
ALTER TABLE departments ENABLE ROW LEVEL SECURITY;
ALTER TABLE departments FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_depts ON departments
    USING (organization_id = current_setting('app.current_tenant', true))
    WITH CHECK (organization_id = current_setting('app.current_tenant', true));
```

#### users

```sql
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_users ON users
    USING (organization_id = current_setting('app.current_tenant', true))
    WITH CHECK (organization_id = current_setting('app.current_tenant', true));
```

---

## 4. スーパーユーザーとバイパス

### 4.1 RLSをバイパスするユーザー

| ユーザー | バイパス | 用途 |
|---------|---------|------|
| postgres（スーパーユーザー） | 自動バイパス | 管理作業 |
| migration_user | バイパス許可 | マイグレーション実行 |
| app_user | バイパス不可 | アプリケーション接続 |

### 4.2 バイパス設定

```sql
-- マイグレーション用ユーザーにバイパス権限を付与
ALTER USER migration_user BYPASSRLS;

-- アプリケーション用ユーザーはバイパス不可（デフォルト）
-- ALTER USER app_user NOBYPASSRLS;  -- 明示的に設定する場合
```

### 4.3 管理者アクセス（全テナント参照）

```sql
-- 管理者用ポリシー（必要な場合のみ追加）
CREATE POLICY admin_access ON chatwork_tasks
    FOR ALL
    TO admin_role
    USING (true)
    WITH CHECK (true);
```

---

## 5. 移行手順

### Phase 1: 準備（現在〜Phase 4A開始前）

1. **organization_idカラムの追加**（SECURITY_AUDIT_ORGANIZATION_ID.md参照）
2. **既存データへのデフォルト値設定**
3. **テスト環境でRLSポリシーを検証**

```sql
-- 1. カラム追加（例: system_config）
ALTER TABLE system_config
ADD COLUMN organization_id TEXT NOT NULL DEFAULT 'org_soulsyncs';

-- 2. 既存データのorganization_id設定
UPDATE system_config
SET organization_id = 'org_soulsyncs'
WHERE organization_id IS NULL OR organization_id = '';
```

### Phase 2: RLS有効化（Phase 4A）

1. **本番環境でのRLSポリシー作成**
2. **アプリケーションコードでのテナントコンテキスト設定**
3. **段階的なRLS有効化（テーブルごと）**

```sql
-- 1つのテーブルずつ有効化して検証
ALTER TABLE chatwork_tasks ENABLE ROW LEVEL SECURITY;
-- 動作確認後、次のテーブルへ
```

### Phase 3: 検証（Phase 4A完了後）

1. **全テーブルでのRLS有効確認**
2. **テナント分離テストの実行**
3. **パフォーマンス影響の測定**

---

## 6. 検証方法

### 6.1 RLS有効確認クエリ

```sql
-- RLSが有効なテーブル一覧
SELECT
    schemaname,
    tablename,
    rowsecurity
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;

-- 期待結果: rowsecurity = true（RLS有効）
```

### 6.2 テナント分離テスト

```python
import pytest

@pytest.mark.asyncio
async def test_rls_tenant_isolation():
    """RLSによるテナント分離を検証"""

    async with get_db_connection() as conn:
        # テナントAのコンテキストでデータ作成
        await conn.execute("SET app.current_tenant = 'org_a'")
        await conn.execute("""
            INSERT INTO chatwork_tasks (task_id, organization_id, body)
            VALUES ('task_1', 'org_a', 'テナントAのタスク')
        """)

        # テナントBのコンテキストで取得を試みる
        await conn.execute("SET app.current_tenant = 'org_b'")
        result = await conn.fetch("""
            SELECT * FROM chatwork_tasks WHERE task_id = 'task_1'
        """)

        # RLSにより取得できないことを確認
        assert len(result) == 0, "テナントBからテナントAのデータが見えてしまっている"

@pytest.mark.asyncio
async def test_rls_insert_validation():
    """RLSのINSERT検証（WITH CHECK）を確認"""

    async with get_db_connection() as conn:
        # テナントAのコンテキスト
        await conn.execute("SET app.current_tenant = 'org_a'")

        # テナントBのデータを挿入しようとする
        with pytest.raises(Exception) as exc_info:
            await conn.execute("""
                INSERT INTO chatwork_tasks (task_id, organization_id, body)
                VALUES ('task_2', 'org_b', '不正なデータ')
            """)

        # RLSのWITH CHECKにより拒否されることを確認
        assert "violates row-level security policy" in str(exc_info.value)
```

### 6.3 パフォーマンステスト

```sql
-- RLS有効化前後のクエリプラン比較
EXPLAIN ANALYZE
SELECT * FROM chatwork_tasks WHERE status = 'open';

-- 期待: Index Scanが使用され、大幅な性能劣化がないこと
```

---

## 7. トラブルシューティング

### 7.1 よくある問題

| 問題 | 原因 | 解決策 |
|------|------|--------|
| 全データが見えない | テナントコンテキスト未設定 | `SET app.current_tenant`を確認 |
| INSERT失敗 | organization_idの不一致 | WITH CHECKポリシーを確認 |
| マイグレーション失敗 | RLSでブロック | BYPASSRLSユーザーで実行 |
| パフォーマンス劣化 | インデックス不足 | organization_idのインデックス追加 |

### 7.2 デバッグ方法

```sql
-- 現在のテナントコンテキストを確認
SELECT current_setting('app.current_tenant', true);

-- RLSポリシーを確認
SELECT * FROM pg_policies WHERE tablename = 'chatwork_tasks';

-- RLSを一時的に無効化（デバッグ用、本番では禁止）
SET row_security = off;  -- スーパーユーザーのみ
```

---

## 8. 実装チェックリスト

### 移行前チェック

- [ ] 全テーブルにorganization_idカラムがある
- [ ] 既存データにorganization_idが設定されている
- [ ] テスト環境でRLSポリシーが動作確認済み
- [ ] アプリケーションコードでテナントコンテキスト設定が実装済み

### 移行時チェック

- [ ] RLSポリシーが全テーブルに作成されている
- [ ] FORCEオプションが設定されている
- [ ] バイパスユーザーが適切に設定されている

### 移行後チェック

- [ ] テナント分離テストが全てパス
- [ ] パフォーマンス影響が許容範囲内
- [ ] 監査ログが正常に記録されている

---

## 9. 関連ドキュメント

| ドキュメント | 参照内容 |
|-------------|---------|
| SECURITY_AUDIT_ORGANIZATION_ID.md | organization_idフィルタ監査結果 |
| CLAUDE.md セクション5 | 10の鉄則（#2: RLS実装） |
| OPERATIONS_RUNBOOK.md セクション11 | organization_id管理 |
| 04_api_and_security.md | セキュリティ設計 |

---

## 更新履歴

| 日付 | 変更内容 |
|------|---------|
| 2026-01-30 | 初版作成 |

---

**このファイルについての質問は、Tech Leadに連絡してください。**
