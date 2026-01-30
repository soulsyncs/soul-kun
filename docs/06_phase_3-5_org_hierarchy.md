# Phase 3.5: 組織階層設計書

---

## Document Contract（SoT宣言）

| 項目 | 内容 |
|------|------|
| **この文書の役割** | Phase 3.5（組織階層機能）の実装手順書 |
| **書くこと** | 組織階層のデータモデル、マイグレーション手順、週次スケジュール |
| **書かないこと** | 組織理論の詳細（→11章）、フロントエンド設計（→12章） |
| **SoT（この文書が正）** | departmentsテーブル定義、LTREE設計、マイグレーション手順 |
| **Owner** | Tech Lead |
| **更新トリガー** | 組織階層機能の仕様変更時 |

---

## 12.1 Phase 3.5の実装手順

### ■ Week 7: データモデル構築（20時間）

**Day 1-2: テーブル作成（10時間）**

```bash
# 1. マイグレーションファイル作成
$ python manage.py makemigration create_organization_tables

# 2. マイグレーション実装
# migrations/v10_0_001_create_organization_tables.py
```

```python
async def upgrade():
    """組織階層テーブルを作成"""
    
    # 1. LTREEエクステンションを有効化
    await conn.execute("CREATE EXTENSION IF NOT EXISTS ltree;")
    
    # 2. departments テーブル作成
    await conn.execute("""
        CREATE TABLE departments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id),
            name VARCHAR(255) NOT NULL,
            code VARCHAR(50),
            parent_department_id UUID REFERENCES departments(id),
            level INT NOT NULL DEFAULT 1,
            path LTREE NOT NULL,
            display_order INT DEFAULT 0,
            description TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            created_by UUID REFERENCES users(id),
            updated_by UUID REFERENCES users(id),
            CONSTRAINT unique_org_dept_code UNIQUE(organization_id, code),
            CONSTRAINT check_level CHECK(level >= 1 AND level <= 10)
        );
    """)
    
    # 3. インデックス作成
    await conn.execute("""
        CREATE INDEX idx_departments_org ON departments(organization_id);
        CREATE INDEX idx_departments_parent ON departments(parent_department_id);
        CREATE INDEX idx_departments_path ON departments USING GIST(path);
    """)
    
    # 4. user_departments テーブル作成
    await conn.execute("""
        CREATE TABLE user_departments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            department_id UUID NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
            is_primary BOOLEAN DEFAULT TRUE,
            role_in_dept VARCHAR(100),
            started_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            ended_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT unique_user_primary_dept 
                UNIQUE(user_id, is_primary) 
                WHERE is_primary = TRUE AND ended_at IS NULL
        );
    """)
    
    # 5. department_access_scopes テーブル作成
    await conn.execute("""
        CREATE TABLE department_access_scopes (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            department_id UUID NOT NULL REFERENCES departments(id),
            can_view_child_departments BOOLEAN DEFAULT TRUE,
            can_view_sibling_departments BOOLEAN DEFAULT FALSE,
            can_view_parent_departments BOOLEAN DEFAULT FALSE,
            max_depth INT DEFAULT 99,
            override_confidential_access BOOLEAN DEFAULT FALSE,
            override_restricted_access BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT unique_dept_scope UNIQUE(department_id)
        );
    """)
    
    # 6. department_hierarchies テーブル作成
    await conn.execute("""
        CREATE TABLE department_hierarchies (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id),
            ancestor_department_id UUID NOT NULL REFERENCES departments(id),
            descendant_department_id UUID NOT NULL REFERENCES departments(id),
            depth INT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT unique_hierarchy 
                UNIQUE(ancestor_department_id, descendant_department_id),
            CONSTRAINT check_depth CHECK(depth >= 0)
        );
    """)
    
    # 7. org_chart_sync_logs テーブル作成
    await conn.execute("""
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
    """)
```

```bash
# 3. マイグレーション実行
$ python manage.py migrate

# 4. 動作確認
$ python manage.py shell
>>> from app.models import Department
>>> await Department.all().count()
0  # テーブルが作成された
```

**Day 3-4: モデル実装（6時間）**

```python
# app/models/organization.py

from tortoise import fields
from tortoise.models import Model

class Department(Model):
    """部署マスタ"""
    
    id = fields.UUIDField(pk=True)
    organization = fields.ForeignKeyField("models.Organization", related_name="departments")
    name = fields.CharField(max_length=255)
    code = fields.CharField(max_length=50, null=True)
    parent_department = fields.ForeignKeyField("models.Department", related_name="children", null=True)
    level = fields.IntField(default=1)
    path = fields.CharField(max_length=1000)  # LTREE型として扱う
    display_order = fields.IntField(default=0)
    description = fields.TextField(null=True)
    is_active = fields.BooleanField(default=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    
    class Meta:
        table = "departments"
    
    async def get_children(self, max_depth: int = 99) -> list["Department"]:
        """配下の部署を取得"""
        return await Department.filter(
            id__in=Subquery(
                DepartmentHierarchy.filter(
                    ancestor_department_id=self.id,
                    depth__gt=0,
                    depth__lte=max_depth
                ).values_list("descendant_department_id", flat=True)
            )
        ).all()
    
    async def get_parents(self) -> list["Department"]:
        """親部署を取得"""
        return await Department.filter(
            id__in=Subquery(
                DepartmentHierarchy.filter(
                    descendant_department_id=self.id,
                    depth__gt=0
                ).values_list("ancestor_department_id", flat=True)
            )
        ).all()
```

**Day 5: テストデータ作成（4時間）**

```python
# scripts/create_test_org_chart.py

async def create_test_org_chart():
    """テスト用の組織図を作成"""
    
    # 1. 組織作成
    org = await Organization.create(name="ソウルシンクス")
    
    # 2. 本社
    head_office = await Department.create(
        organization_id=org.id,
        name="本社",
        code="HQ",
        level=1,
        path="soulsyncs"
    )
    
    # 3. 営業部
    sales_dept = await Department.create(
        organization_id=org.id,
        name="営業部",
        code="SALES",
        parent_department_id=head_office.id,
        level=2,
        path="soulsyncs.sales"
    )
    
    # 4. 東京営業課
    tokyo_sales = await Department.create(
        organization_id=org.id,
        name="東京営業課",
        code="SALES-01",
        parent_department_id=sales_dept.id,
        level=3,
        path="soulsyncs.sales.tokyo"
    )
    
    # 5. 階層テーブルを構築
    await rebuild_department_hierarchies(org.id)
    
    print("テスト組織図を作成しました")
```

```bash
# 実行
$ python scripts/create_test_org_chart.py
```

---

### ■ Week 8: API実装（30時間）

**Day 1-2: 組織図同期API（10時間）**

```python
# app/api/v1/organization.py

from fastapi import APIRouter, Depends, HTTPException
from app.models import Organization, Department, UserDepartment
from app.schemas import OrgChartSyncRequest, OrgChartSyncResponse
from app.services.organization import sync_org_chart_data
from app.dependencies import get_current_user, authorize

router = APIRouter(prefix="/organizations", tags=["organization"])

@router.post("/{org_id}/sync-org-chart", response_model=OrgChartSyncResponse)
async def sync_org_chart(
    org_id: str,
    data: OrgChartSyncRequest,
    user: User = Depends(get_current_user)
):
    """組織図同期API"""
    
    # 権限チェック
    await authorize(user, "organization", "manage")
    
    # 同期処理
    result = await sync_org_chart_data(org_id, data, user)
    
    return result
```

**Day 3-4: 階層計算ロジック（10時間）**

```python
# app/services/organization.py

async def compute_accessible_departments(
    user: User,
    user_depts: list[UserDepartment]
) -> list[str]:
    """ユーザーのアクセス可能部署を計算"""
    
    accessible = set()
    
    for user_dept in user_depts:
        dept = await Department.get(user_dept.department_id)
        scope = await DepartmentAccessScope.get_or_none(department_id=dept.id)
        
        # 自部署
        accessible.add(dept.id)
        
        # 配下
        if scope and scope.can_view_child_departments:
            children = await dept.get_children(max_depth=scope.max_depth)
            accessible.update([c.id for c in children])
        
        # 兄弟
        if scope and scope.can_view_sibling_departments:
            siblings = await Department.filter(
                parent_department_id=dept.parent_department_id,
                id__ne=dept.id
            ).all()
            accessible.update([s.id for s in siblings])
        
        # 親
        if scope and scope.can_view_parent_departments:
            parents = await dept.get_parents()
            accessible.update([p.id for p in parents])
    
    return list(accessible)
```

**Day 5: RAG検索統合（10時間）**

```python
# app/services/knowledge.py

async def search_knowledge_with_org_filter(
    query: str,
    user: User
) -> KnowledgeSearchResponse:
    """ナレッジ検索（組織フィルタ付き）"""
    
    # アクセス可能部署を取得
    accessible_depts = await get_user_accessible_departments_cached(user)
    
    # Pinecone検索
    results = await pinecone_index.query(
        vector=await compute_embedding(query),
        filter={
            "organization_id": user.organization_id,
            "$or": [
                {"classification": "public"},
                {"classification": "internal"},
                {
                    "classification": "confidential",
                    "department_id": {"$in": accessible_depts}
                }
            ]
        },
        top_k=10
    )
    
    return results
```

---

## 12.2 Phase 3.6の実装手順

### ■ Week 9-12: 組織図システム製品化（80時間）

**Week 9: マルチテナント化（30時間）**

1. 組織図WebアプリのコードをCloud Run対応に改修
2. LocalStorageをCloud SQLに切り替え
3. 認証機能の実装（Firebase Authentication）
4. テナント分離の実装

**Week 10: UI改修（40時間）**

1. Webアプリのデザイン改修
2. レスポンシブ対応
3. 管理画面の実装
4. エクスポート機能の強化

**Week 11-12: 外販準備（10時間）**

1. API仕様書の作成
2. マニュアルの作成
3. 料金ページの作成
4. 契約書の作成

---

# 第13章：組織図システム仕様書【新設】

## 13.1 組織図システムの機能一覧

### ■ コア機能

| # | 機能 | 説明 | 優先度 |
|---|------|------|--------|
| 1 | 部署管理 | 部署の追加・編集・削除 | 必須 |
| 2 | 社員管理 | 社員の追加・編集・削除 | 必須 |
| 3 | 組織図表示 | ツリー/カード/リスト表示 | 必須 |
| 4 | 所属管理 | 社員の部署配属・異動 | 必須 |
| 5 | 権限管理 | 誰が編集できるか | 必須 |
| 6 | データエクスポート | PDF/Excel出力 | 必須 |
| 7 | 履歴管理 | 組織変更履歴の記録 | 必須 |
| 8 | 検索機能 | 部署・社員の検索 | 推奨 |
| 9 | フィルタ機能 | 雇用形態・スキル等でフィルタ | 推奨 |
| 10 | テンプレート | 業種別のテンプレート | オプション |

---

## 13.2 組織図システムのUI設計

### ■ 画面一覧

| # | 画面名 | URL | 機能 |
|---|--------|-----|------|
| 1 | ログイン | `/login` | ユーザー認証 |
| 2 | ダッシュボード | `/` | 組織図の概要表示 |
| 3 | 組織図表示 | `/org-chart` | ツリー/カード/リスト表示 |
| 4 | 部署編集 | `/departments/{id}` | 部署の詳細・編集 |
| 5 | 社員編集 | `/employees/{id}` | 社員の詳細・編集 |
| 6 | 履歴表示 | `/history` | 組織変更履歴 |
| 7 | エクスポート | `/export` | PDF/Excel出力 |
| 8 | 設定 | `/settings` | 権限・同期設定 |

---

## 13.3 組織図システムのデータ同期

### ■ 同期方式

| 方式 | タイミング | 実装 |
|------|----------|------|
| **Push型（推奨）** | 組織図Webアプリから変更を通知 | 「保存」ボタン押下時にAPI呼び出し |
| Pull型 | ソウル君が定期的に取得 | 5分ごとにポーリング（非推奨） |

**Push型の実装:**

```javascript
// 組織図Webアプリ (JavaScript)

async function syncToSoulkun() {
    const orgChartData = {
        sync_type: "full",
        departments: getAllDepartments(),
        user_departments: getAllUserDepartments(),
        access_scopes: getAllAccessScopes()
    };
    
    const response = await fetch(
        `https://soulkun.api/v1/organizations/${orgId}/sync-org-chart`,
        {
            method: "POST",
            headers: {
                "Authorization": `Bearer ${apiToken}`,
                "Content-Type": "application/json"
            },
            body: JSON.stringify(orgChartData)
        }
    );
    
    if (response.ok) {
        const result = await response.json();
        showNotification(`同期完了: ${result.summary.departments_added}部署を追加`);
    } else {
        showError("同期に失敗しました");
    }
}

// 「保存」ボタンのイベントハンドラ
document.getElementById("save-button").addEventListener("click", async () => {
    await saveToLocalDB();  // ローカルDBに保存
    await syncToSoulkun();  // ソウル君に同期
});
```

---

## 13.4 組織図システムの外販仕様

### ■ 提供形態

| 項目 | 内容 |
|------|------|
| **デプロイ先** | Cloud Run（GCP） |
| **データベース** | Cloud SQL（PostgreSQL） |
| **認証** | Firebase Authentication |
| **ストレージ** | Cloud Storage（画像保存用） |
| **監視** | Cloud Monitoring |

### ■ SLA（Service Level Agreement）

| 項目 | 目標値 |
|------|--------|
| **稼働率** | 99.9%（月間ダウンタイム < 43分） |
| **応答時間** | P95 < 200ms |
| **データバックアップ** | 毎日自動バックアップ |
| **障害復旧時間** | 4時間以内 |

---


---

**[📁 目次に戻る](00_README.md)**
