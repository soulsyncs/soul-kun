# 第10章：実装規約【v10.1.4新設】

---

## Document Contract（SoT宣言）

| 項目 | 内容 |
|------|------|
| **この文書の役割** | 実装規約・コーディング基準・テスト戦略の詳細仕様 |
| **書くこと** | コーディング規約、APIバージョニング、エラーハンドリング、テスト戦略 |
| **書かないこと** | 原則・概念（→CLAUDE.md）、API仕様（→04章）、DB設計（→03章） |
| **SoT（この文書が正）** | コーディング規約、テスト戦略（単体/統合/E2E/セキュリティ/パフォーマンス） |
| **Owner** | カズさん（代表） |
| **関連リンク** | [CLAUDE.md](../CLAUDE.md)（原則）、[04章](04_api_and_security.md)（API設計）、[Design Coverage Matrix](DESIGN_COVERAGE_MATRIX.md) |

---

## 10.1 実装規約の目的

この章では、ソウルくんの開発・運用において、全エンジニアが守るべき鉄則を定義します。

**規約の3つの柱:**
1. **一貫性**: すべてのコードが同じパターンに従う
2. **保守性**: 将来の機能拡張が容易
3. **安全性**: テナント分離、セキュリティの徹底

---

## 10.2 APIバージョニングポリシー【v10.1.4新設】

### ■ APIバージョニングの目的

**なぜバージョニングが必要か?**
- **破壊的変更への対応**: 既存クライアントを壊さずに新機能を追加
- **段階的移行**: 旧バージョンから新バージョンへスムーズに移行
- **後方互換性の保証**: 既存のBPaaS顧客への影響を最小化

---

### ■ バージョニング方式

**URL パスベースバージョニング（採用）**

```
/api/v1/tasks/overdue
/api/v2/tasks/overdue
```

**理由:**
- 明確で分かりやすい
- ドキュメント生成が容易
- APIゲートウェイでのルーティングが簡単

---

### ■ バージョンの命名規則

| バージョン | 用途 | 例 |
|-----------|------|---|
| **v1** | 初期リリース、社内実証（Phase 1〜3） | `/api/v1/tasks` |
| **v2** | BPaaS対応、マルチテナント完全対応（Phase 4） | `/api/v2/tasks` |
| **v3** | 将来の大規模リファクタリング | `/api/v3/tasks` |

**ルール:**
- メジャーバージョンのみ使用（v1.1 は使わない）
- 破壊的変更時にのみバージョンアップ
- 非破壊的変更（フィールド追加等）は既存バージョン内で実施

---

### ■ 破壊的変更と非破壊的変更

**破壊的変更（バージョンアップ必須）:**

| 変更内容 | 影響 | 対応 |
|---------|------|------|
| フィールド名の変更 | クライアントコードが壊れる | v2でリリース |
| 必須パラメータの追加 | 既存リクエストがエラー | v2でリリース |
| レスポンス構造の変更 | パースエラー | v2でリリース |
| エンドポイントの削除 | 404エラー | v2でリリース、v1は非推奨化 |
| 認証方式の変更 | 認証失敗 | v2でリリース |

**非破壊的変更（既存バージョンで対応可能）:**

| 変更内容 | 影響 | 対応 |
|---------|------|------|
| 新しいエンドポイント追加 | なし | v1に追加 |
| オプションパラメータの追加 | なし（デフォルト値あり） | v1に追加 |
| レスポンスフィールドの追加 | なし（無視される） | v1に追加 |
| エラーメッセージの改善 | なし | v1で修正 |

---

### ■ バージョン移行のプロセス

**Phase 1: 新バージョンのリリース**

```
時期: Phase 4A開始時（2026年Q4）

1. v2 APIをリリース（マルチテナント完全対応）
2. v1 APIは引き続き稼働（社内利用）
3. ドキュメントにv2への移行ガイドを公開
```

**Phase 2: 移行期間**

```
期間: 6ヶ月

1. 新規BPaaS顧客はv2のみ使用
2. 既存社内システムはv1のまま（任意でv2移行）
3. v1に「Deprecated」ヘッダーを追加
   例: Warning: "299 - API version v1 is deprecated. Please migrate to v2."
```

**Phase 3: v1非推奨化**

```
時期: Phase 4Bリリース後（2027年Q2）

1. v1 APIに非推奨警告を表示
2. ドキュメントでv1の新規利用を非推奨化
3. v1のサポート終了日を発表（6ヶ月後）
```

**Phase 4: v1終了**

```
時期: 2027年Q4

1. v1 APIを完全停止
2. v1へのリクエストは410 Goneを返す
3. v2への強制移行完了
```

---

### ■ バージョンごとのサポート期間

| バージョン | リリース時期 | サポート終了 | 最小サポート期間 |
|-----------|------------|------------|----------------|
| **v1** | Phase 1（2026年Q2） | 2027年Q4 | **18ヶ月** |
| **v2** | Phase 4A（2026年Q4） | 未定（2029年以降） | **24ヶ月以上** |

**ルール:**
- 新バージョンリリース後、旧バージョンは**最低18ヶ月サポート**
- 非推奨化から終了まで**最低6ヶ月の移行期間**を確保

---

### ■ バージョン間の違いの例（v1 vs v2）

**v1: 社内実証版**

```http
GET /api/v1/tasks/overdue?grace_days=0&limit=100&offset=0
Authorization: Bearer {API_KEY}
```

**レスポンス:**
```json
{
  "overdue_tasks": [...],
  "total_count": 2,
  "checked_at": "2026-01-17T09:00:00Z",
  "pagination": {...}
}
```

**v2: BPaaS対応版（Phase 4）**

```http
GET /api/v2/tasks/overdue?organization_id=org_soulsyncs&grace_days=0&limit=100&offset=0
Authorization: Bearer {API_KEY}
X-Tenant-ID: org_soulsyncs
```

**レスポンス:**
```json
{
  "data": {
    "overdue_tasks": [...],
    "total_count": 2
  },
  "meta": {
    "checked_at": "2026-01-17T09:00:00Z",
    "api_version": "v2",
    "tenant_id": "org_soulsyncs"
  },
  "pagination": {...}
}
```

**変更点:**
1. `X-Tenant-ID` ヘッダーが必須（マルチテナント対応）
2. レスポンス構造の変更（`data` と `meta` に分離）
3. `api_version` フィールドの追加

---

### ■ バージョン管理の実装例

**FastAPIでのバージョン管理:**

```python
from fastapi import APIRouter

# v1 APIルーター
router_v1 = APIRouter(prefix="/api/v1", tags=["v1"])

@router_v1.get("/tasks/overdue")
async def get_overdue_tasks_v1(
    grace_days: int = 0,
    limit: int = 100,
    offset: int = 0
):
    # v1の実装
    return {
        "overdue_tasks": [...],
        "total_count": 2,
        "checked_at": datetime.utcnow().isoformat()
    }

# v2 APIルーター
router_v2 = APIRouter(prefix="/api/v2", tags=["v2"])

@router_v2.get("/tasks/overdue")
async def get_overdue_tasks_v2(
    organization_id: str,
    grace_days: int = 0,
    limit: int = 100,
    offset: int = 0,
    tenant_id: str = Header(..., alias="X-Tenant-ID")
):
    # テナントIDの検証
    if organization_id != tenant_id:
        raise HTTPException(status_code=403, detail="Tenant mismatch")
    
    # v2の実装（マルチテナント対応）
    return {
        "data": {
            "overdue_tasks": [...],
            "total_count": 2
        },
        "meta": {
            "checked_at": datetime.utcnow().isoformat(),
            "api_version": "v2",
            "tenant_id": tenant_id
        }
    }

# アプリケーションに登録
app.include_router(router_v1)
app.include_router(router_v2)
```

---

### ■ クライアントへの移行ガイド

**v1 → v2 移行チェックリスト:**

| # | 項目 | 変更内容 |
|---|------|---------|
| 1 | **URL変更** | `/api/v1/` → `/api/v2/` |
| 2 | **ヘッダー追加** | `X-Tenant-ID` を全リクエストに追加 |
| 3 | **レスポンス解析** | `data`, `meta` 構造に対応 |
| 4 | **エラーハンドリング** | 新しいエラーコード（403: Tenant mismatch）に対応 |
| 5 | **認証トークン** | 新しいAPI Key（テナントごと）を取得 |

**移行例（Python）:**

```python
# v1（旧）
response = requests.get(
    "https://api.soulsyncs.jp/api/v1/tasks/overdue",
    headers={"Authorization": f"Bearer {API_KEY}"},
    params={"grace_days": 0}
)
tasks = response.json()["overdue_tasks"]

# v2（新）
response = requests.get(
    "https://api.soulsyncs.jp/api/v2/tasks/overdue",
    headers={
        "Authorization": f"Bearer {API_KEY}",
        "X-Tenant-ID": "org_soulsyncs"  # 追加
    },
    params={
        "organization_id": "org_soulsyncs",  # 追加
        "grace_days": 0
    }
)
tasks = response.json()["data"]["overdue_tasks"]  # 変更
```

---

### ■ バージョニングのベストプラクティス

**DO（推奨）:**
- ✅ 破壊的変更時は必ず新バージョンをリリース
- ✅ 非推奨化から終了まで最低6ヶ月の猶予期間を設ける
- ✅ ドキュメントに移行ガイドを明記
- ✅ v1終了後も、v1へのリクエストには適切なエラーメッセージを返す
- ✅ レスポンスヘッダーに `API-Version: v2` を含める

**DON'T（禁止）:**
- ❌ 予告なしにバージョンを終了
- ❌ 同じバージョン内で破壊的変更を実施
- ❌ v1とv2で同じエンドポイントが異なる動作をする（混乱を招く）
- ❌ バージョンを細かく刻む（v1.1, v1.2 等）
- ❌ 非推奨警告なしに突然終了

---

### ■ APIバージョニングまとめ

**v10.1.4で明確にしたこと:**

| 項目 | 内容 |
|------|------|
| バージョニング方式 | URL パスベース（`/api/v1/`, `/api/v2/`） |
| v1 → v2 移行時期 | Phase 4A（2026年Q4）|
| v1サポート終了 | 2027年Q4（18ヶ月サポート） |
| 移行期間 | 最低6ヶ月 |
| 破壊的変更の定義 | フィールド名変更、必須パラメータ追加、レスポンス構造変更 |

**v10.1.4の価値:**
- Phase 4での破壊的変更に明確な指針を提供
- BPaaS顧客への影響を最小化する移行プロセスを定義
- エンジニアがバージョニング判断に迷わない

---

## 10.3 実装規約サマリー

### ■ 必ず守るべき10の鉄則

| # | 鉄則 | Phase |
|---|------|-------|
| 1 | **全テーブルにorganization_idを追加** | Phase 3.5〜 |
| 2 | **Row Level Security（RLS）を実装** | Phase 4A |
| 3 | **監査ログを全confidential以上の操作で記録** | Phase 3.5 |
| 4 | **APIは必ず認証必須** | Phase 1〜 |
| 5 | **ページネーションを1000件超えAPIに実装** | Phase 1-B〜 |
| 6 | **キャッシュにTTLを設定（デフォルト5分）** | Phase 3.5 |
| 7 | **破壊的変更時はAPIバージョンアップ** | Phase 4A〜 |
| 8 | **エラーメッセージに機密情報を含めない** | Phase 1〜 |
| 9 | **SQLインジェクション対策（パラメータ化）** | Phase 1〜 |
| 10 | **トランザクション内でAPI呼び出しをしない** | Phase 1〜 |

---

# 第11章：テスト設計【新設】

## 11.1 テスト戦略

### ■ テストの種類とカバレッジ

| テストレベル | 目的 | カバレッジ目標 | 実施時期 |
|------------|------|--------------|---------|
| 単体テスト | 関数・メソッドの正常動作 | 80%以上 | 開発中 |
| 統合テスト | API・DB連携の動作 | 主要シナリオ100% | Phase完了時 |
| E2Eテスト | ユーザー操作の再現 | 主要フロー100% | リリース前 |
| セキュリティテスト | 権限・認証の検証 | 全権限パターン | リリース前 |
| パフォーマンステスト | 負荷・応答時間 | 目標値達成 | リリース前 |

---

## 11.2 単体テスト

### ■ compute_accessible_departments() のテスト

```python
import pytest
from app.services.organization import compute_accessible_departments

@pytest.mark.asyncio
async def test_compute_accessible_departments_manager():
    """部長は配下すべてにアクセスできる"""
    
    # セットアップ
    org = await Organization.create(name="テスト会社")
    dept_sales = await Department.create(
        organization_id=org.id,
        name="営業部",
        path="sales"
    )
    dept_tokyo = await Department.create(
        organization_id=org.id,
        name="東京営業課",
        parent_department_id=dept_sales.id,
        path="sales.tokyo"
    )
    user = await User.create(
        organization_id=org.id,
        name="部長",
        role="manager"
    )
    user_dept = await UserDepartment.create(
        user_id=user.id,
        department_id=dept_sales.id
    )
    await DepartmentAccessScope.create(
        department_id=dept_sales.id,
        can_view_child_departments=True,
        max_depth=99
    )
    await rebuild_department_hierarchies(org.id)
    
    # 実行
    accessible = await compute_accessible_departments(user, [user_dept])
    
    # 検証
    assert dept_sales.id in accessible  # 自部署
    assert dept_tokyo.id in accessible  # 配下


@pytest.mark.asyncio
async def test_compute_accessible_departments_member():
    """一般社員は自部署のみ"""
    
    # セットアップ
    org = await Organization.create(name="テスト会社")
    dept_sales = await Department.create(
        organization_id=org.id,
        name="営業部",
        path="sales"
    )
    dept_tokyo = await Department.create(
        organization_id=org.id,
        name="東京営業課",
        parent_department_id=dept_sales.id,
        path="sales.tokyo"
    )
    user = await User.create(
        organization_id=org.id,
        name="一般社員",
        role="member"
    )
    user_dept = await UserDepartment.create(
        user_id=user.id,
        department_id=dept_tokyo.id
    )
    # スコープなし = デフォルト（自部署のみ）
    
    # 実行
    accessible = await compute_accessible_departments(user, [user_dept])
    
    # 検証
    assert dept_tokyo.id in accessible  # 自部署
    assert dept_sales.id not in accessible  # 親部署は見れない
```

---

## 11.3 統合テスト

### ■ 組織図同期APIのテスト

```python
@pytest.mark.asyncio
async def test_sync_org_chart_full():
    """組織図同期API（フルシンク）のテスト"""
    
    # セットアップ
    org = await Organization.create(name="テスト会社")
    admin_user = await User.create(
        organization_id=org.id,
        name="管理者",
        role="admin"
    )
    
    # リクエストデータ
    data = {
        "sync_type": "full",
        "departments": [
            {
                "id": "dept_sales",
                "name": "営業部",
                "code": "SALES",
                "parent_id": None,
                "level": 1
            },
            {
                "id": "dept_tokyo",
                "name": "東京営業課",
                "code": "SALES-01",
                "parent_id": "dept_sales",
                "level": 2
            }
        ],
        "user_departments": [
            {
                "user_id": admin_user.id,
                "department_id": "dept_sales",
                "is_primary": True
            }
        ]
    }
    
    # APIコール
    response = await client.post(
        f"/api/v1/organizations/{org.id}/sync-org-chart",
        json=data,
        headers={"Authorization": f"Bearer {admin_user.token}"}
    )
    
    # 検証
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "success"
    assert result["summary"]["departments_added"] == 2
    
    # DBに保存されているか確認
    depts = await Department.filter(organization_id=org.id).all()
    assert len(depts) == 2
    
    # 階層テーブルが作成されているか確認
    hierarchies = await DepartmentHierarchy.filter(
        organization_id=org.id
    ).all()
    assert len(hierarchies) >= 3  # (sales, sales), (sales, tokyo), (tokyo, tokyo)
```

---

## 11.4 E2Eテスト

### ■ シナリオ: 部長がドキュメントを閲覧

```python
@pytest.mark.e2e
async def test_manager_views_document():
    """E2E: 部長がドキュメントを閲覧できる"""
    
    # 1. セットアップ
    org, manager_user, dept_sales, document = await setup_test_scenario()
    
    # 2. ログイン
    await login_as(manager_user)
    
    # 3. ドキュメント検索
    response = await search_knowledge("営業マニュアル")
    assert response.status_code == 200
    assert len(response.json()["sources"]) > 0
    
    # 4. ドキュメント閲覧
    doc_id = response.json()["sources"][0]["document_id"]
    response = await view_document(doc_id)
    assert response.status_code == 200
    
    # 5. 監査ログ確認
    logs = await AuditLog.filter(
        user_id=manager_user.id,
        resource_id=doc_id
    ).all()
    assert len(logs) == 1
```

---

## 11.5 セキュリティテスト

### ■ テストケース一覧

| # | テストケース | 期待結果 |
|---|------------|---------|
| 1 | 一般社員が他部署の機密情報を閲覧 | ❌ 403 Forbidden |
| 2 | 部長が配下の部署の機密情報を閲覧 | ✅ 200 OK |
| 3 | 部長が兄弟部署の機密情報を閲覧 | ❌ 403 Forbidden |
| 4 | 管理者がすべての機密情報を閲覧 | ✅ 200 OK |
| 5 | 退職社員がドキュメントを閲覧 | ❌ 401 Unauthorized |
| 6 | 組織が異なるドキュメントを閲覧 | ❌ 404 Not Found |

**テスト実装例:**

```python
@pytest.mark.security
async def test_member_cannot_view_other_dept_confidential():
    """一般社員は他部署の機密情報を見れない"""
    
    # セットアップ
    org = await Organization.create(name="テスト会社")
    dept_sales = await Department.create(
        organization_id=org.id,
        name="営業部"
    )
    dept_hr = await Department.create(
        organization_id=org.id,
        name="人事部"
    )
    user = await User.create(
        organization_id=org.id,
        name="営業社員",
        role="member"
    )
    await UserDepartment.create(
        user_id=user.id,
        department_id=dept_sales.id
    )
    
    # 人事部の機密ドキュメント
    hr_document = await Document.create(
        organization_id=org.id,
        department_id=dept_hr.id,
        classification="confidential",
        title="人事評価基準"
    )
    
    # テスト
    response = await client.get(
        f"/api/v1/documents/{hr_document.id}",
        headers={"Authorization": f"Bearer {user.token}"}
    )
    
    # 検証
    assert response.status_code == 403
    assert "department_mismatch" in response.json()["error_code"]
```

## 11.6 パフォーマンステスト【v10.1.2追加】

### Phase 3.5 パフォーマンステスト基準

#### compute_accessible_departments()

| テストケース | 条件 | 目標応答時間 |
|-------------|------|-------------|
| 小規模 | 100部署 | < 50ms |
| 中規模 | 1,000部署 | < 100ms |
| 大規模 | 10,000部署 | < 500ms |

#### 同期API（POST /api/v1/org-chart/sync）

| テストケース | 条件 | 目標処理時間 |
|-------------|------|-------------|
| 小規模 | 100部署 + 500ユーザー | < 5秒 |
| 中規模 | 1,000部署 + 5,000ユーザー | < 30秒 |
| 大規模 | 10,000部署 + 50,000ユーザー | < 5分 |

#### 同時実行テスト

| テストケース | 条件 | 期待動作 |
|-------------|------|---------|
| 同時同期 | 2つの同期リクエストが同時に来た場合 | 2つ目はSYNC_CONFLICTで拒否 |
| リトライ | 接続エラー後の自動リトライ | 5分後に自動実行 |

#### RAG検索（組織フィルタ適用後）

| テストケース | 条件 | 目標応答時間 |
|-------------|------|-------------|
| フィルタ適用 | 1,000部署からのフィルタリング | < 10ms |
| 検索実行 | 1,000チャンクからの検索 | < 200ms |
| 合計 | フィルタ + 検索 | < 250ms |

### テストスクリプト例

```python
import pytest
import asyncio
from datetime import datetime

@pytest.mark.asyncio
async def test_compute_accessible_departments_performance():
    """
    compute_accessible_departments のパフォーマンステスト
    """
    # テストデータ準備（1000部署）
    organization_id = await create_test_organization_with_departments(1000)
    user_id = await create_test_user(organization_id)

    # 計測
    start = datetime.utcnow()
    result = await compute_accessible_departments(user_id, organization_id)
    duration = (datetime.utcnow() - start).total_seconds() * 1000

    # アサーション
    assert duration < 100, f"応答時間が目標を超過: {duration}ms"
    assert len(result) > 0, "結果が空です"

@pytest.mark.asyncio
async def test_sync_api_performance():
    """
    同期APIのパフォーマンステスト
    """
    # テストデータ準備
    request = OrgChartSyncRequest(
        organization_id="org_test",
        sync_type="full",
        departments=[
            DepartmentInput(id=f"dept_{i}", name=f"部署{i}", code=f"D{i}", parentId=None, level=1, displayOrder=i, isActive=True)
            for i in range(100)
        ],
        roles=[
            RoleInput(id=f"role_{i}", name=f"役職{i}", level=i, description=f"説明{i}")
            for i in range(10)
        ],
        employees=[
            EmployeeInput(id=f"user_{i}", name=f"社員{i}", email=f"user{i}@test.com", departmentId=f"dept_{i % 100}", roleId=f"role_{i % 10}", isPrimary=True)
            for i in range(500)
        ]
    )

    # 計測
    start = datetime.utcnow()
    result = await sync_org_chart(request)
    duration = (datetime.utcnow() - start).total_seconds()

    # アサーション
    assert duration < 5, f"処理時間が目標を超過: {duration}秒"
    assert result['status'] == 'success'

@pytest.mark.asyncio
async def test_sync_conflict():
    """
    同期競合テスト
    """
    organization_id = "org_conflict_test"

    # 同期1を開始（完了しない）
    task1 = asyncio.create_task(slow_sync(organization_id))
    await asyncio.sleep(0.1)  # 少し待つ

    # 同期2を開始（競合するはず）
    with pytest.raises(HTTPException) as exc_info:
        await sync_org_chart(OrgChartSyncRequest(organization_id=organization_id, ...))

    assert exc_info.value.detail['error']['code'] == 'SYNC_CONFLICT'
```

---

# 第14章：実装前チェックリスト【Phase 3 MVP】【v10.1新設】

## 14.1 Phase 3 MVPの実装順序

Phase 3 MVPは「一気に全機能」ではなく、**「土台→機能」の順**で実装します。

### ■ なぜ順序が重要か？

**悪い例：機能から先に作る**

```
Day 1: ドキュメント取り込み機能を実装
Day 2: RAG検索機能を実装
Day 3: 「あ、機密区分がない！」→ 全テーブルを修正
Day 4: 「あ、監査ログがない！」→ 全APIを修正
Day 5: 「あ、chunk_idがない！」→ Pineconeのデータを再登録
```

→ **手戻りが多発し、工数が2倍になる**

**良い例：土台から先に固める**

```
Week 1: 不可逆の土台10項目を実装（機能は動かない）
Week 2: 土台の上に機能を実装（スムーズに進む）
Week 3-6: 機能を拡張（手戻りなし）
```

→ **手戻りゼロ、工数が半分**

---

## 14.2 Step 1: 不可逆の土台を固める（Week 1-2, 40時間）

### ■ 不可逆の土台10項目

| # | 項目 | なぜ最初？ | 実装工数 | 担当 |
|---|------|-----------|---------|------|
| 1 | ID設計 | 全テーブルの前提 | 5h | エンジニア |
| 2 | 機密区分 | 後から付け直すのが地獄 | 3h | エンジニア |
| 3 | 監査ログ | 後から追加すると全APIを修正 | 4h | エンジニア |
| 4 | 引用粒度 | チャンク分割の前提 | 3h | エンジニア |
| 5 | 権限制御の形式 | 動的権限への拡張路線 | 5h | エンジニア |
| 6 | 組織階層モデル | セキュリティの根 | 8h | エンジニア |
| 7 | 回答拒否の仕様 | 事故防止のブレーキ | 3h | エンジニア |
| 8 | 同期ログ | 組織図同期の証跡 | 3h | エンジニア |
| 9 | テナント化の鍵 | Phase 4Aの前提 | 3h | エンジニア |
| 10 | メッセージ送信の冪等性 | 二重送信防止 | 3h | エンジニア |
| **合計** | | | **40h** | |

---

### ■ 土台1: ID設計（5時間）

**目的:** 全テーブルで一貫したID体系を確立

**実装内容:**

```sql
-- 1. UUID v4 をデフォルトに
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 2. 全テーブルのID型を統一
-- ✅ OK: UUID
id UUID PRIMARY KEY DEFAULT gen_random_uuid()

-- ❌ NG: INT AUTO_INCREMENT
id SERIAL PRIMARY KEY  -- これは使わない

-- 3. 外部キーも全てUUID
organization_id UUID NOT NULL REFERENCES organizations(id)
user_id UUID NOT NULL REFERENCES users(id)
document_id UUID NOT NULL REFERENCES documents(id)
chunk_id UUID NOT NULL  -- Pineconeのベクターキー
```

**チェックリスト:**

- [ ] 全テーブルのIDがUUID型か？
- [ ] 外部キーもUUID型か？
- [ ] `gen_random_uuid()` がデフォルト値か？
- [ ] INT型のIDは一切使っていないか？

**テストケース:**

```python
@pytest.mark.asyncio
async def test_all_tables_use_uuid():
    """全テーブルのIDがUUID型であることを確認"""
    
    # テーブル一覧を取得
    result = await db.execute("""
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE column_name = 'id'
          AND table_schema = 'public'
    """)
    
    for row in result:
        table_name, column_name, data_type = row
        assert data_type == "uuid", f"{table_name}.{column_name} はUUID型である必要があります"
```

---

### ■ 土台2: 機密区分（3時間）

**目的:** ドキュメントの機密レベルを最初から持つ

**実装内容:**

```sql
-- documents テーブルに classification カラムを追加
ALTER TABLE documents
ADD COLUMN classification VARCHAR(50) NOT NULL DEFAULT 'internal'
CHECK (classification IN ('public', 'internal', 'confidential', 'restricted'));

-- ドキュメントバージョンにも
ALTER TABLE document_versions
ADD COLUMN classification VARCHAR(50) NOT NULL DEFAULT 'internal'
CHECK (classification IN ('public', 'internal', 'confidential', 'restricted'));

-- Pinecone Metadata にも
-- （コード例は後述）
```

**機密区分の定義（再掲）:**

| 区分 | 説明 | アクセス権 |
|------|------|-----------|
| public | 社外にも公開可能 | 全員 |
| internal | 社員なら誰でも閲覧可 | 全社員 |
| confidential | 部門/役職で閲覧制限 | 組織階層で判定 |
| restricted | 経営陣のみ | 経営陣のみ |

**チェックリスト:**

- [ ] documents テーブルに classification カラムがあるか？
- [ ] document_versions テーブルにも classification カラムがあるか？
- [ ] CHECK制約で値を制限しているか？
- [ ] デフォルト値が 'internal' か？

---

### ■ 土台3: 監査ログ（4時間）

**目的:** 「誰が何を見たか」を記録する

**実装内容:**

```sql
CREATE TABLE audit_logs (
    -- 基本情報
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    
    -- アクション
    user_id UUID NOT NULL REFERENCES users(id),
    action VARCHAR(100) NOT NULL,  -- 'view', 'create', 'update', 'delete', 'export'
    
    -- リソース
    resource_type VARCHAR(50) NOT NULL,  -- 'document', 'knowledge', 'user', 'department'
    resource_id UUID,
    resource_name VARCHAR(255),
    
    -- 組織情報
    department_id UUID REFERENCES departments(id),
    classification VARCHAR(50),
    
    -- 詳細
    details JSONB,
    
    -- コンテキスト
    ip_address INET,
    user_agent TEXT,
    
    -- メタデータ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- インデックス
CREATE INDEX idx_audit_user ON audit_logs(user_id);
CREATE INDEX idx_audit_resource ON audit_logs(resource_type, resource_id);
CREATE INDEX idx_audit_action ON audit_logs(action);
CREATE INDEX idx_audit_classification ON audit_logs(classification);
CREATE INDEX idx_audit_created ON audit_logs(created_at DESC);
```

**監査ログを記録するヘルパー関数:**

```python
async def log_audit(
    user: User,
    action: str,
    resource_type: str,
    resource_id: str = None,
    resource_name: str = None,
    department_id: str = None,
    classification: str = None,
    details: dict = None
):
    """監査ログを記録"""
    
    await AuditLog.create(
        organization_id=user.organization_id,
        user_id=user.id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_name=resource_name,
        department_id=department_id,
        classification=classification,
        details=details,
        ip_address=get_client_ip(),
        user_agent=get_user_agent()
    )
```

**チェックリスト:**

- [ ] audit_logs テーブルが作成されているか？
- [ ] classification カラムがあるか？
- [ ] department_id カラムがあるか？
- [ ] log_audit() 関数が実装されているか？

---

### ■ 土台4: 引用粒度（3時間）

**目的:** チャンクIDでドキュメントの特定箇所を引用できる

**実装内容:**

```sql
-- document_chunks テーブル
CREATE TABLE document_chunks (
    -- 基本情報
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),  -- chunk_id
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    document_version_id UUID NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id),
    
    -- チャンク内容
    chunk_index INT NOT NULL,  -- 0から始まる連番
    text TEXT NOT NULL,
    
    -- 位置情報
    page_number INT,
    section_title VARCHAR(500),
    start_char INT,
    end_char INT,
    
    -- メタデータ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    
    -- インデックス
    CONSTRAINT unique_chunk_index UNIQUE(document_version_id, chunk_index)
);

CREATE INDEX idx_chunks_doc ON document_chunks(document_id);
CREATE INDEX idx_chunks_version ON document_chunks(document_version_id);
CREATE INDEX idx_chunks_org ON document_chunks(organization_id);
```

**Pineconeへの登録:**

```python
async def register_chunk_to_pinecone(chunk: DocumentChunk):
    """チャンクをPineconeに登録"""
    
    # Embedding生成
    embedding = await compute_embedding(chunk.text)
    
    # Metadata
    metadata = {
        "chunk_id": str(chunk.id),
        "document_id": str(chunk.document_id),
        "document_version_id": str(chunk.document_version_id),
        "organization_id": str(chunk.organization_id),
        "classification": chunk.document.classification,
        "department_id": str(chunk.document.department_id) if chunk.document.department_id else None,
        "page_number": chunk.page_number,
        "section_title": chunk.section_title,
        "chunk_index": chunk.chunk_index,
        "text": chunk.text[:500]  # 先頭500文字のみ（プレビュー用）
    }
    
    # Pineconeに登録
    await pinecone_index.upsert(
        vectors=[(str(chunk.id), embedding, metadata)],
        namespace=str(chunk.organization_id)
    )
```

**チェックリスト:**

- [ ] document_chunks テーブルが作成されているか？
- [ ] chunk_id, document_id, document_version_id があるか？
- [ ] page_number, section_title があるか？
- [ ] Pinecone Metadataに chunk_id が含まれているか？

---

### ■ 土台5: 権限制御の形式（5時間）

**目的:** 固定権限→動的権限への拡張路線を確保

**実装内容:**

```sql
-- roles テーブル（既存）
CREATE TABLE roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    name VARCHAR(100) NOT NULL,
    permissions JSONB NOT NULL,  -- {"documents": ["view", "create"], ...}
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- permissions テーブル（Phase 3 MVPでは最小限）
CREATE TABLE permissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    role_id UUID NOT NULL REFERENCES roles(id),
    resource_type VARCHAR(50) NOT NULL,  -- 'document', 'knowledge', etc.
    action VARCHAR(50) NOT NULL,  -- 'view', 'create', 'update', 'delete'
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT unique_permission UNIQUE(role_id, resource_type, action)
);

-- user_roles テーブル
CREATE TABLE user_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    role_id UUID NOT NULL REFERENCES roles(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT unique_user_role UNIQUE(user_id, role_id)
);
```

**権限チェック関数（MVP版）:**

```python
async def authorize(user: User, resource_type: str, action: str):
    """権限チェック（MVP版）"""
    
    # 1. 管理者は全てOK
    if user.role == "admin":
        return True
    
    # 2. ユーザーのロールを取得
    user_roles = await UserRole.filter(user_id=user.id).prefetch_related("role").all()
    
    # 3. 権限をチェック
    for user_role in user_roles:
        permissions = await Permission.filter(
            role_id=user_role.role_id,
            resource_type=resource_type,
            action=action
        ).exists()
        
        if permissions:
            return True
    
    # 4. 権限なし
    raise HTTPException(status_code=403, detail="権限がありません")
```

**チェックリスト:**

- [ ] roles, permissions, user_roles テーブルが作成されているか？
- [ ] authorize() 関数が実装されているか？
- [ ] 全APIで authorize() を呼び出しているか？

---

### ■ 土台6: 組織階層モデル（8時間）

**目的:** セキュリティの根となる組織構造を定義

**実装内容:**

（第5章 5.2.5の内容を参照。departments, user_departments, department_access_scopes, department_hierarchies を作成）

```sql
-- departments テーブル
CREATE TABLE departments (...);  -- 詳細は5.2.5参照

-- user_departments テーブル
CREATE TABLE user_departments (...);

-- department_access_scopes テーブル
CREATE TABLE department_access_scopes (...);

-- department_hierarchies テーブル
CREATE TABLE department_hierarchies (...);
```

**チェックリスト:**

- [ ] departments テーブルに LTREE型の path カラムがあるか？
- [ ] user_departments テーブルに is_primary カラムがあるか？
- [ ] department_access_scopes テーブルがあるか？
- [ ] department_hierarchies テーブルがあるか？
- [ ] LTREE拡張機能が有効化されているか？

---

### ■ 土台7: 回答拒否の仕様（3時間）

**目的:** 根拠が薄い場合は回答しない

**実装内容:**

```python
def should_generate_answer(results: list[SearchResult]) -> tuple[bool, str]:
    """
    動的閾値による回答生成判定
    
    Returns:
        (許可/拒否, 理由)
    """
    if not results:
        return False, "no_results"
    
    top_1 = results[0].score
    
    # 絶対閾値
    if top_1 < 0.5:
        return False, "low_confidence"
    
    # 高信頼度
    if top_1 >= 0.8:
        return True, "high_confidence"
    
    # 1位が突出
    if len(results) >= 3:
        if top_1 - results[2].score > 0.2:
            return True, "top_hit_dominant"
    
    # 複数ヒットの平均
    top_3_avg = sum(r.score for r in results[:3]) / min(3, len(results))
    if top_3_avg >= 0.6:
        return True, "multi_hit"
    
    return False, "low_average"
```

**チェックリスト:**

- [ ] should_generate_answer() 関数が実装されているか？
- [ ] 閾値が動的に調整されるか？
- [ ] 拒否理由がログに記録されるか？

---

### ■ 土台8: 同期ログ（3時間）

**目的:** 組織図同期の証跡を残す

**実装内容:**

```sql
CREATE TABLE org_chart_sync_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    sync_type VARCHAR(50) NOT NULL,
    status VARCHAR(50) NOT NULL,
    departments_added INT DEFAULT 0,
    departments_updated INT DEFAULT 0,
    departments_deleted INT DEFAULT 0,
    users_added INT DEFAULT 0,
    users_updated INT DEFAULT 0,
    users_deleted INT DEFAULT 0,
    error_message TEXT,
    error_details JSONB,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    duration_ms INT,
    triggered_by UUID REFERENCES users(id),
    source_system VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
```

**チェックリスト:**

- [ ] org_chart_sync_logs テーブルが作成されているか？
- [ ] sync_type, status カラムがあるか？
- [ ] departments_added 等の集計カラムがあるか？

---

### ■ 土台9: テナント化の鍵（3時間）

**目的:** 全テーブルに organization_id を持たせる

**実装内容:**

```sql
-- 全テーブルに organization_id を追加
ALTER TABLE documents
ADD COLUMN organization_id UUID NOT NULL REFERENCES organizations(id);

ALTER TABLE document_versions
ADD COLUMN organization_id UUID NOT NULL REFERENCES organizations(id);

ALTER TABLE document_chunks
ADD COLUMN organization_id UUID NOT NULL REFERENCES organizations(id);

-- インデックス
CREATE INDEX idx_docs_org ON documents(organization_id);
CREATE INDEX idx_versions_org ON document_versions(organization_id);
CREATE INDEX idx_chunks_org ON document_chunks(organization_id);
```

**WHERE句の強制:**

```python
# ❌ NG: organization_id のフィルタがない
documents = await Document.all()

# ✅ OK: 必ず organization_id でフィルタ
documents = await Document.filter(organization_id=user.organization_id).all()
```

**チェックリスト:**

- [ ] 全テーブルに organization_id カラムがあるか？
- [ ] 全クエリに organization_id のWHERE句があるか？

---

### ■ 土台10: メッセージ送信の冪等性（3時間）

**目的:** 二重送信・再試行を防ぐ

**実装内容:**

（第15章の内容を参照）

```sql
CREATE TABLE outbox_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    message_type VARCHAR(50) NOT NULL,
    destination VARCHAR(100) NOT NULL,
    recipient_id VARCHAR(255) NOT NULL,
    content JSONB NOT NULL,
    idempotency_key VARCHAR(255) NOT NULL UNIQUE,
    status VARCHAR(50) DEFAULT 'pending',
    retry_count INT DEFAULT 0,
    max_retries INT DEFAULT 3,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMPTZ,
    failed_at TIMESTAMPTZ,
    error_message TEXT
);
```

**チェックリスト:**

- [ ] outbox_messages テーブルが作成されているか？
- [ ] idempotency_key カラムに UNIQUE制約があるか？
- [ ] retry_count, max_retries カラムがあるか？

---

## 14.3 Step 2: MVPの機能実装（Week 3-6, 80時間）

土台が固まった後、MVPの9項目を実装します。

### ■ 実装スケジュール

| Week | 実装内容 | 工数 |
|------|---------|------|
| Week 3 | ドキュメント取り込み、参照検索 | 30h |
| Week 4 | 根拠提示、注意書き | 20h |
| Week 5 | フィードバック、アクセス制御 | 15h |
| Week 6 | 引用粒度、回答拒否条件、検索品質評価 | 15h |
| **合計** | | **80h** |

---

## 14.4 実装完了の確認チェックリスト

### ■ 土台チェックリスト

- [ ] 1. ID設計：全テーブルのIDがUUID型
- [ ] 2. 機密区分：documents, document_versions に classification カラム
- [ ] 3. 監査ログ：audit_logs テーブル + log_audit() 関数
- [ ] 4. 引用粒度：document_chunks テーブル + chunk_id
- [ ] 5. 権限制御：roles, permissions, user_roles テーブル
- [ ] 6. 組織階層：departments, user_departments, etc.
- [ ] 7. 回答拒否：should_generate_answer() 関数
- [ ] 8. 同期ログ：org_chart_sync_logs テーブル
- [ ] 9. テナント化：全テーブルに organization_id
- [ ] 10. 冪等性：outbox_messages テーブル

### ■ MVPチェックリスト

- [ ] 1. ドキュメント取り込み：A, B, F のドキュメントが登録できる
- [ ] 2. 参照検索：質問に対して関連箇所が返る
- [ ] 3. 根拠提示：回答に引用/出典が付く
- [ ] 4. 注意書き：「最終更新日」「最新版は管理部に確認」が付く
- [ ] 5. フィードバック：「役に立った/違う」が記録される
- [ ] 6. アクセス制御：「全員OK/管理部のみ」の2段階
- [ ] 7. 引用粒度：ページ/見出し/段落まで特定できる
- [ ] 8. 回答拒否条件：根拠が薄い場合は「回答できません」
- [ ] 9. 検索品質評価：週次で「ヒットしない質問」を可視化

---

# 第15章：メッセージ送信の冪等性設計【v10.1新設】

## 15.1 なぜ冪等性が必要か？

### ■ 外部通知の3大問題

ChatWork/Slack/メール等の外部通知は、必ず以下の問題が発生します。

| 問題 | 例 | 結果 |
|------|-----|------|
| **二重送信** | タスク完了を2回通知 | 「なぜ2回通知が来るの?」とユーザー混乱 |
| **再試行** | ネットワークエラーで3回リトライ | 同じ通知が3回届く |
| **順序崩れ** | 後の通知が先に届く | 「タスク完了」が「タスク開始」より先に届く |

**結果:**
- 同じ通知が3回届く
- 古い通知が新しい通知を上書き
- ユーザーが混乱

---

## 15.2 Outboxパターンの実装

### ■ Outboxパターンとは？

**通知をすぐに送らず、一旦DBに保存してから送る**パターンです。

```
[通常のパターン（NG）]
タスク完了 → すぐにChatWorkに送信 → ネットワークエラー → リトライ → 二重送信

[Outboxパターン（OK）]
タスク完了 → outbox_messagesテーブルに保存 → 別プロセスが送信 → 送信済みフラグ → 二重送信防止
```

### ■ outbox_messages テーブル

```sql
CREATE TABLE outbox_messages (
    -- 基本情報
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    
    -- メッセージ内容
    message_type VARCHAR(50) NOT NULL,  -- 'task_completed', 'org_sync', etc.
    destination VARCHAR(100) NOT NULL,  -- 'chatwork', 'slack', 'email'
    recipient_id VARCHAR(255) NOT NULL,  -- room_id or user_email
    content JSONB NOT NULL,
    
    -- 冪等性キー（重複防止）
    idempotency_key VARCHAR(255) NOT NULL UNIQUE,
    
    -- ステータス
    status VARCHAR(50) DEFAULT 'pending',  -- pending, sent, failed
    retry_count INT DEFAULT 0,
    max_retries INT DEFAULT 3,
    
    -- タイムスタンプ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMPTZ,
    failed_at TIMESTAMPTZ,
    
    -- エラー情報
    error_message TEXT
);

CREATE INDEX idx_outbox_status ON outbox_messages(status) WHERE status = 'pending';
CREATE INDEX idx_outbox_idempotency ON outbox_messages(idempotency_key);
```

---

## 15.3 冪等性キーの設計

### ■ 冪等性キーとは？

**「このメッセージは既に送信済みか？」を判定するための一意キー**です。

**生成ルール:**

```
{message_type}:{resource_id}:{organization_id}
```

**例:**

| メッセージタイプ | リソースID | 冪等性キー |
|---------------|-----------|-----------|
| タスク完了 | task_123 | `task_completed:task_123:org_soulsyncs` |
| 組織図同期 | sync_456 | `org_sync:sync_456:org_soulsyncs` |
| ドキュメント更新 | doc_789 | `doc_updated:doc_789:org_soulsyncs` |

### ■ 実装コード

```python
def generate_idempotency_key(
    message_type: str,
    resource_id: str,
    organization_id: str
) -> str:
    """冪等性キーを生成"""
    return f"{message_type}:{resource_id}:{organization_id}"


async def enqueue_message(
    message_type: str,
    resource_id: str,
    organization_id: str,
    destination: str,
    recipient_id: str,
    content: dict
) -> OutboxMessage:
    """
    メッセージをキューに追加（冪等性保証）
    
    Returns:
        OutboxMessage: 追加されたメッセージ（既に送信済みの場合は既存のメッセージ）
    """
    
    idempotency_key = generate_idempotency_key(
        message_type,
        resource_id,
        organization_id
    )
    
    # 既に送信済みかチェック
    existing = await OutboxMessage.get_or_none(
        idempotency_key=idempotency_key,
        status="sent"
    )
    
    if existing:
        # 既に送信済み（冪等性により、2回目の送信をスキップ）
        return existing
    
    # キューに追加
    message = await OutboxMessage.create(
        organization_id=organization_id,
        message_type=message_type,
        destination=destination,
        recipient_id=recipient_id,
        content=content,
        idempotency_key=idempotency_key
    )
    
    return message
```

---

## 15.4 リトライ戦略

### ■ リトライの設定

| 項目 | 値 | 理由 |
|------|-----|------|
| 最大リトライ回数 | 3回 | 無限リトライを防ぐ |
| リトライ間隔 | 1分, 5分, 10分 | Exponential Backoff |
| タイムアウト | 30秒 | 長時間待たない |

### ■ メッセージ送信ワーカー

```python
async def process_outbox():
    """
    Outboxメッセージを処理（定期実行）
    Cloud Schedulerで5分ごとに実行
    """
    
    # pending状態のメッセージを取得
    messages = await OutboxMessage.filter(
        status="pending",
        retry_count__lt=F("max_retries")
    ).order_by("created_at").limit(100).all()
    
    for message in messages:
        try:
            # 送信処理
            if message.destination == "chatwork":
                await send_to_chatwork(message)
            elif message.destination == "slack":
                await send_to_slack(message)
            elif message.destination == "email":
                await send_email(message)
            
            # 成功
            await message.update(
                status="sent",
                sent_at=datetime.now()
            )
            
            logger.info(f"Message sent: {message.id}")
            
        except Exception as e:
            # 失敗（リトライ）
            await message.update(
                retry_count=message.retry_count + 1,
                error_message=str(e)
            )
            
            # リトライ上限に達したら failed
            if message.retry_count >= message.max_retries:
                await message.update(
                    status="failed",
                    failed_at=datetime.now()
                )
                
                logger.error(f"Message failed: {message.id}, error: {e}")
            else:
                logger.warning(f"Message retry: {message.id}, retry: {message.retry_count}")


async def send_to_chatwork(message: OutboxMessage):
    """ChatWorkに送信"""
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://api.chatwork.com/v2/rooms/{message.recipient_id}/messages",
            headers={"X-ChatWorkToken": settings.CHATWORK_API_TOKEN},
            data={"body": message.content["body"]},
            timeout=30.0
        )
        
        if response.status_code != 200:
            raise Exception(f"ChatWork API error: {response.status_code}")
```

---

## 15.5 監視とアラート

### ■ 監視すべき指標

| 指標 | 閾値 | アラート |
|------|------|---------|
| pending状態のメッセージ数 | > 100 | 送信処理が遅延している |
| failed状態のメッセージ数 | > 10 | 送信エラーが多発 |
| 平均送信時間 | > 10秒 | 送信処理が遅い |
| リトライ率 | > 30% | 外部APIが不安定 |

### ■ ダッシュボード

```sql
-- pending状態のメッセージ数
SELECT COUNT(*) FROM outbox_messages WHERE status = 'pending';

-- failed状態のメッセージ数
SELECT COUNT(*) FROM outbox_messages WHERE status = 'failed';

-- 平均送信時間
SELECT AVG(EXTRACT(EPOCH FROM (sent_at - created_at))) AS avg_send_time_seconds
FROM outbox_messages
WHERE status = 'sent'
  AND sent_at >= NOW() - INTERVAL '1 hour';

-- リトライ率
SELECT 
    COUNT(CASE WHEN retry_count > 0 THEN 1 END) * 100.0 / COUNT(*) AS retry_rate
FROM outbox_messages
WHERE created_at >= NOW() - INTERVAL '1 hour';
```

---

（ファイルサイズの都合上、ここで一旦区切ります）


---

**[📁 目次に戻る](00_README.md)**
