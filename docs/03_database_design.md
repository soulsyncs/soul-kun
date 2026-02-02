# 第5章：データベース設計

---

## Document Contract（SoT宣言）

| 項目 | 内容 |
|------|------|
| **この文書の役割** | データベース設計・スキーマ定義の詳細仕様 |
| **書くこと** | テーブル定義（DDL）、インデックス、制約、LTREE設計、ERD |
| **書かないこと** | 原則・概念（→CLAUDE.md）、API仕様（→04章）、脳の設計（→25章） |
| **SoT（この文書が正）** | 全テーブルのスキーマ定義、organization_idルール、LTREEパス設計 |
| **Owner** | カズさん（代表） |
| **関連リンク** | [CLAUDE.md](../CLAUDE.md)（原則）、[04章](04_api_and_security.md)（API実装）、[Design Coverage Matrix](DESIGN_COVERAGE_MATRIX.md) |

---

## 5.2.5 組織階層テーブル【Phase 3.5】【新設】

### ■ departments（部署マスタ）

**目的:** 組織の部署構造を管理する

**テーブル定義:**

```sql
CREATE TABLE departments (
    -- 基本情報
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    
    -- 部署情報
    name VARCHAR(255) NOT NULL,
    code VARCHAR(50),  -- 部署コード（例: "SALES-01"）
    parent_department_id UUID REFERENCES departments(id) ON DELETE CASCADE,
    
    -- 階層情報
    level INT NOT NULL DEFAULT 1,  -- 階層レベル（1=本社、2=部、3=課、4=係）
    path LTREE NOT NULL,  -- 階層パス（例: "soulsyncs.sales.tokyo"）
    
    -- 表示順
    display_order INT DEFAULT 0,
    
    -- 説明
    description TEXT,
    
    -- メタデータ
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_by UUID REFERENCES users(id),
    updated_by UUID REFERENCES users(id),
    
    -- インデックス
    CONSTRAINT unique_org_dept_code UNIQUE(organization_id, code),
    CONSTRAINT unique_org_dept_name UNIQUE(organization_id, name),
    CONSTRAINT check_level CHECK(level >= 1 AND level <= 10)
);

-- インデックス
CREATE INDEX idx_departments_org ON departments(organization_id);
CREATE INDEX idx_departments_parent ON departments(parent_department_id);
CREATE INDEX idx_departments_path ON departments USING GIST(path);  -- LTREEインデックス
CREATE INDEX idx_departments_active ON departments(is_active) WHERE is_active = TRUE;
```

**カラム説明:**

| カラム | 型 | 説明 | 例 |
|--------|---|------|-----|
| id | UUID | 部署ID | `dept_001` |
| organization_id | UUID | テナントID | `org_soulsyncs` |
| name | VARCHAR(255) | 部署名 | `東京営業課` |
| code | VARCHAR(50) | 部署コード | `SALES-01` |
| parent_department_id | UUID | 親部署ID | `dept_sales`（営業部） |
| level | INT | 階層レベル | 3（課レベル） |
| path | LTREE | 階層パス | `soulsyncs.sales.tokyo` |
| display_order | INT | 表示順 | 1 |
| description | TEXT | 説明 | `東京エリアの営業を担当` |
| is_active | BOOLEAN | 有効フラグ | TRUE |

**LTREEパスの構造:**

```
本社（level=1）: "soulsyncs"
  └─ 営業部（level=2）: "soulsyncs.sales"
      ├─ 東京営業課（level=3）: "soulsyncs.sales.tokyo"
      │   └─ 第一係（level=4）: "soulsyncs.sales.tokyo.team1"
      └─ 大阪営業課（level=3）: "soulsyncs.sales.osaka"
```

**LTREEのクエリ例:**

```sql
-- 営業部の配下すべて（子孫）
SELECT * FROM departments
WHERE path <@ 'soulsyncs.sales';

-- 東京営業課の親部署すべて（祖先）
SELECT * FROM departments
WHERE path @> 'soulsyncs.sales.tokyo';

-- 営業部の直下のみ（子のみ）
SELECT * FROM departments
WHERE parent_department_id = 'dept_sales';
```

---

### ■ user_departments（ユーザーの所属部署）

**目的:** ユーザーがどの部署に所属しているかを管理する

**テーブル定義:**

```sql
CREATE TABLE user_departments (
    -- 基本情報
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    department_id UUID NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    
    -- 所属情報
    is_primary BOOLEAN DEFAULT TRUE,  -- 主所属かどうか
    role_in_dept VARCHAR(100),  -- 部署内の役職（例: "課長", "マネージャー"）
    
    -- 期間
    started_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMPTZ,  -- 異動・退職時に設定
    
    -- メタデータ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_by UUID REFERENCES users(id),
    
    -- インデックス
    CONSTRAINT unique_user_primary_dept UNIQUE(user_id, is_primary) WHERE is_primary = TRUE AND ended_at IS NULL
);

-- インデックス
CREATE INDEX idx_user_depts_user ON user_departments(user_id);
CREATE INDEX idx_user_depts_dept ON user_departments(department_id);
CREATE INDEX idx_user_depts_active ON user_departments(user_id) WHERE ended_at IS NULL;
```

**カラム説明:**

| カラム | 型 | 説明 | 例 |
|--------|---|------|-----|
| user_id | UUID | ユーザーID | `user_yamada` |
| department_id | UUID | 部署ID | `dept_sales_tokyo` |
| is_primary | BOOLEAN | 主所属か | TRUE（兼務の場合はFALSE） |
| role_in_dept | VARCHAR(100) | 部署内の役職 | `課長` |
| started_at | TIMESTAMPTZ | 配属日 | `2024-04-01` |
| ended_at | TIMESTAMPTZ | 異動・退職日 | NULL（在籍中） |

**制約の意味:**

```sql
CONSTRAINT unique_user_primary_dept 
UNIQUE(user_id, is_primary) 
WHERE is_primary = TRUE AND ended_at IS NULL
```

→ **「ユーザーは1つだけ主所属を持つ」**を保証

**クエリ例:**

```sql
-- ユーザーの現在の所属部署を取得
SELECT d.* FROM departments d
JOIN user_departments ud ON ud.department_id = d.id
WHERE ud.user_id = 'user_yamada'
  AND ud.ended_at IS NULL;

-- 部署のメンバー一覧
SELECT u.* FROM users u
JOIN user_departments ud ON ud.user_id = u.id
WHERE ud.department_id = 'dept_sales_tokyo'
  AND ud.ended_at IS NULL;
```

---

### ■ department_access_scopes（部署ごとの権限スコープ）

**目的:** 各部署がどの範囲の情報にアクセスできるかを定義する

**テーブル定義:**

```sql
CREATE TABLE department_access_scopes (
    -- 基本情報
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    department_id UUID NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    
    -- アクセススコープ
    can_view_child_departments BOOLEAN DEFAULT TRUE,  -- 配下の部署を見れるか
    can_view_sibling_departments BOOLEAN DEFAULT FALSE,  -- 兄弟部署を見れるか
    can_view_parent_departments BOOLEAN DEFAULT FALSE,  -- 親部署を見れるか
    max_depth INT DEFAULT 99,  -- 何階層下まで見れるか（1=直下のみ、99=無制限）
    
    -- 機密区分の上書き（部署ごとに設定可能）
    override_confidential_access BOOLEAN DEFAULT FALSE,  -- confidentialを強制的に見れる
    override_restricted_access BOOLEAN DEFAULT FALSE,  -- restrictedを強制的に見れる
    
    -- メタデータ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_by UUID REFERENCES users(id),
    
    -- インデックス
    CONSTRAINT unique_dept_scope UNIQUE(department_id)
);

-- インデックス
CREATE INDEX idx_dept_scopes_dept ON department_access_scopes(department_id);
```

**カラム説明:**

| カラム | 型 | 説明 | デフォルト値 | 例 |
|--------|---|------|------------|-----|
| can_view_child_departments | BOOLEAN | 配下の部署を見れるか | TRUE | 営業部長は東京課・大阪課を見れる |
| can_view_sibling_departments | BOOLEAN | 兄弟部署を見れるか | FALSE | 東京課長は大阪課を見れない |
| can_view_parent_departments | BOOLEAN | 親部署を見れるか | FALSE | 東京課長は営業部全体を見れない |
| max_depth | INT | 何階層下まで | 99 | 部長は配下すべて（99）、課長は直下のみ（1） |
| override_confidential_access | BOOLEAN | 機密情報を見れる | FALSE | 経営陣はすべての機密情報を見れる |
| override_restricted_access | BOOLEAN | 極秘情報を見れる | FALSE | CEOのみTRUE |

**設定例:**

| 部署 | can_view_child | can_view_sibling | max_depth | 意味 |
|------|---------------|-----------------|-----------|------|
| 本社 | TRUE | FALSE | 99 | 全部署を見れる |
| 営業部 | TRUE | FALSE | 99 | 営業部配下すべて |
| 東京営業課 | TRUE | FALSE | 1 | 東京課の直下のみ |
| 総務部 | TRUE | TRUE | 99 | 総務は全部署を横断的に見れる |

**クエリ例:**

```sql
-- 営業部長のアクセススコープを取得
SELECT * FROM department_access_scopes
WHERE department_id IN (
    SELECT department_id FROM user_departments
    WHERE user_id = 'user_bucho' AND ended_at IS NULL
);
```

---

### ■ department_hierarchies（部署階層の事前計算テーブル）

**目的:** 階層計算のパフォーマンスを改善するため、関係を事前計算

**テーブル定義:**

```sql
CREATE TABLE department_hierarchies (
    -- 基本情報
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    
    -- 階層関係
    ancestor_department_id UUID NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    descendant_department_id UUID NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    depth INT NOT NULL,  -- 何階層離れているか（0=自分自身）
    
    -- メタデータ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    
    -- インデックス
    CONSTRAINT unique_hierarchy UNIQUE(ancestor_department_id, descendant_department_id),
    CONSTRAINT check_depth CHECK(depth >= 0)
);

-- インデックス
CREATE INDEX idx_hierarchies_ancestor ON department_hierarchies(ancestor_department_id);
CREATE INDEX idx_hierarchies_descendant ON department_hierarchies(descendant_department_id);
CREATE INDEX idx_hierarchies_org ON department_hierarchies(organization_id);
```

**データ例:**

部署構造:
```
本社（A）
  └─ 営業部（B）
      └─ 東京営業課（C）
```

department_hierarchies テーブル:

| ancestor | descendant | depth | 意味 |
|----------|-----------|-------|------|
| A | A | 0 | 本社 → 本社（自分自身） |
| A | B | 1 | 本社 → 営業部（子） |
| A | C | 2 | 本社 → 東京営業課（孫） |
| B | B | 0 | 営業部 → 営業部（自分自身） |
| B | C | 1 | 営業部 → 東京営業課（子） |
| C | C | 0 | 東京営業課 → 東京営業課（自分自身） |

**クエリ例:**

```sql
-- 営業部の配下すべて（パフォーマンス最適化版）
SELECT d.* FROM departments d
JOIN department_hierarchies h ON h.descendant_department_id = d.id
WHERE h.ancestor_department_id = 'dept_sales'
  AND h.depth > 0;  -- 0は自分自身なので除外

-- 東京営業課の祖先すべて
SELECT d.* FROM departments d
JOIN department_hierarchies h ON h.ancestor_department_id = d.id
WHERE h.descendant_department_id = 'dept_sales_tokyo'
  AND h.depth > 0;
```

**パフォーマンス比較:**

| 方法 | 1000部署での応答時間 |
|------|-------------------|
| LTREEで毎回計算 | 50〜100ms |
| department_hierarchies使用 | 5〜10ms |

→ **10倍高速**

---

### ■ org_chart_sync_logs（組織図同期ログ）

**目的:** 組織図システムとの同期履歴を記録

**テーブル定義:**

```sql
-- 組織図同期ログテーブル
CREATE TABLE org_chart_sync_logs (
    -- 主キー
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sync_id VARCHAR(100) UNIQUE NOT NULL,  -- 'sync_20260115_140000_abc123'

    -- リレーション
    organization_id UUID NOT NULL REFERENCES organizations(id),

    -- 同期タイプ
    sync_type VARCHAR(50) NOT NULL,        -- 'full' | 'incremental'
    source_system VARCHAR(100) NOT NULL,   -- 'org_chart_system'

    -- ステータス
    status VARCHAR(50) NOT NULL DEFAULT 'in_progress',
    -- 'in_progress' | 'success' | 'failed' | 'rolled_back'

    -- 部署の統計
    departments_added INT DEFAULT 0,
    departments_updated INT DEFAULT 0,
    departments_deleted INT DEFAULT 0,

    -- 役職の統計（★v10.1.2追加）
    roles_added INT DEFAULT 0,
    roles_updated INT DEFAULT 0,
    roles_deleted INT DEFAULT 0,

    -- ユーザーの統計
    users_added INT DEFAULT 0,
    users_updated INT DEFAULT 0,
    users_deleted INT DEFAULT 0,

    -- 所属の統計
    user_departments_added INT DEFAULT 0,
    user_departments_updated INT DEFAULT 0,
    user_departments_deleted INT DEFAULT 0,

    -- エラー情報
    error_code VARCHAR(100),
    error_message TEXT,
    error_details JSONB,

    -- タイミング
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    failed_at TIMESTAMPTZ,
    duration_ms INT,

    -- 実行者
    triggered_by UUID REFERENCES users(id),
    trigger_source VARCHAR(50),  -- 'manual' | 'scheduled' | 'webhook'

    -- リクエストデータ（デバッグ用）
    request_payload JSONB,

    -- メタデータ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- インデックス
CREATE INDEX idx_sync_logs_org ON org_chart_sync_logs(organization_id);
CREATE INDEX idx_sync_logs_status ON org_chart_sync_logs(status);
CREATE INDEX idx_sync_logs_started ON org_chart_sync_logs(started_at DESC);
CREATE INDEX idx_sync_logs_sync_id ON org_chart_sync_logs(sync_id);

-- コメント
COMMENT ON TABLE org_chart_sync_logs IS '組織図同期の実行ログ';
COMMENT ON COLUMN org_chart_sync_logs.sync_id IS '一意の同期ID（冪等性キー）';
COMMENT ON COLUMN org_chart_sync_logs.status IS 'in_progress=実行中, success=成功, failed=失敗, rolled_back=ロールバック済み';
COMMENT ON COLUMN org_chart_sync_logs.duration_ms IS '同期処理にかかった時間（ミリ秒）';
```

**ログ例:**

```json
{
    "id": "log_001",
    "organization_id": "org_soulsyncs",
    "sync_type": "full",
    "status": "success",
    "departments_added": 5,
    "departments_updated": 2,
    "departments_deleted": 0,
    "users_added": 10,
    "users_updated": 3,
    "users_deleted": 1,
    "started_at": "2025-01-13T10:00:00Z",
    "completed_at": "2025-01-13T10:00:05Z",
    "duration_ms": 5000,
    "triggered_by": "user_admin",
    "source_system": "org-chart-web"
}
```

**Tortoise ORMモデル:**

```python
from tortoise import Model, fields
import uuid

class OrgChartSyncLog(Model):
    """組織図同期ログ"""
    id = fields.UUIDField(pk=True, default=uuid.uuid4)
    sync_id = fields.CharField(max_length=100, unique=True)
    organization = fields.ForeignKeyField('models.Organization', related_name='sync_logs')

    sync_type = fields.CharField(max_length=50)  # 'full' | 'incremental'
    source_system = fields.CharField(max_length=100)
    status = fields.CharField(max_length=50, default='in_progress')

    # 統計
    departments_added = fields.IntField(default=0)
    departments_updated = fields.IntField(default=0)
    departments_deleted = fields.IntField(default=0)
    roles_added = fields.IntField(default=0)
    roles_updated = fields.IntField(default=0)
    roles_deleted = fields.IntField(default=0)
    users_added = fields.IntField(default=0)
    users_updated = fields.IntField(default=0)
    users_deleted = fields.IntField(default=0)
    user_departments_added = fields.IntField(default=0)
    user_departments_updated = fields.IntField(default=0)
    user_departments_deleted = fields.IntField(default=0)

    # エラー情報
    error_code = fields.CharField(max_length=100, null=True)
    error_message = fields.TextField(null=True)
    error_details = fields.JSONField(null=True)

    # タイミング
    started_at = fields.DatetimeField()
    completed_at = fields.DatetimeField(null=True)
    failed_at = fields.DatetimeField(null=True)
    duration_ms = fields.IntField(null=True)

    # 実行者
    triggered_by = fields.ForeignKeyField('models.User', related_name='triggered_syncs', null=True)
    trigger_source = fields.CharField(max_length=50, null=True)

    # リクエストデータ
    request_payload = fields.JSONField(null=True)

    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "org_chart_sync_logs"
```

### ■ roles同期処理の実装【v10.1.2追加】

**同期結果クラス:**

```python
from typing import Dict, Any, List
from uuid import UUID
from datetime import datetime

class SyncResult:
    """同期結果"""
    def __init__(self):
        self.added = 0
        self.updated = 0
        self.deleted = 0
        self.errors = []

async def sync_roles(
    organization_id: UUID,
    roles_data: List[RoleInput]
) -> SyncResult:
    """
    役職データの同期

    Args:
        organization_id: 組織ID
        roles_data: 組織図システムからの役職データ

    Returns:
        SyncResult: 同期結果
    """
    result = SyncResult()

    # 既存の役職IDを取得
    existing_roles = await Role.filter(
        organization_id=organization_id
    ).all()
    existing_role_ids = {str(r.id) for r in existing_roles}
    incoming_role_ids = {r.id for r in roles_data}

    for role_data in roles_data:
        try:
            existing_role = await Role.get_or_none(
                id=role_data.id,
                organization_id=organization_id
            )

            if existing_role:
                # 更新
                existing_role.name = role_data.name
                existing_role.description = role_data.description
                existing_role.metadata = {'level': role_data.level}
                existing_role.updated_at = datetime.utcnow()
                await existing_role.save()
                result.updated += 1
            else:
                # 新規作成
                await Role.create(
                    id=role_data.id,
                    organization_id=organization_id,
                    name=role_data.name,
                    description=role_data.description,
                    permissions={},  # デフォルトは空
                    metadata={'level': role_data.level}
                )
                result.added += 1

        except Exception as e:
            result.errors.append({
                'role_id': role_data.id,
                'error': str(e)
            })

    # 削除処理（組織図システムに存在しなくなった役職）
    # 注意：関連データがある場合は削除しない
    for role_id in existing_role_ids - incoming_role_ids:
        try:
            role = await Role.get(id=role_id)
            # 関連チェック
            has_users = await UserRole.filter(role_id=role_id).exists()
            has_scopes = await DepartmentAccessScope.filter(role_id=role_id).exists()

            if not has_users and not has_scopes:
                await role.delete()
                result.deleted += 1
            else:
                # 関連データがある場合は is_active = False にするだけ
                role.is_active = False
                await role.save()

        except Exception as e:
            result.errors.append({
                'role_id': role_id,
                'error': f'削除失敗: {str(e)}'
            })

    return result
```

### ■ エラーハンドリング実装【v10.1.2追加】

**エラークラス定義:**

```python
from enum import Enum

class SyncErrorCode(str, Enum):
    """同期エラーコード"""
    ORG_CHART_CONNECTION_FAILED = "ORG_CHART_CONNECTION_FAILED"
    ORG_CHART_AUTH_FAILED = "ORG_CHART_AUTH_FAILED"
    SYNC_CONFLICT = "SYNC_CONFLICT"
    DATA_VALIDATION_FAILED = "DATA_VALIDATION_FAILED"
    SYNC_PROCESSING_FAILED = "SYNC_PROCESSING_FAILED"
    ROLLBACK_FAILED = "ROLLBACK_FAILED"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"

# リトライ可能なエラー
RECOVERABLE_ERRORS = {
    SyncErrorCode.ORG_CHART_CONNECTION_FAILED,
    SyncErrorCode.SYNC_CONFLICT,
}

class OrgChartSyncError(Exception):
    """組織図同期エラー"""

    def __init__(
        self,
        code: SyncErrorCode,
        message: str,
        details: dict = None,
        recoverable: bool = None
    ):
        self.code = code
        self.message = message
        self.details = details or {}
        self.recoverable = recoverable if recoverable is not None else (code in RECOVERABLE_ERRORS)
        super().__init__(message)

    def to_dict(self) -> dict:
        return {
            'code': self.code.value,
            'message': self.message,
            'details': self.details,
            'recoverable': self.recoverable
        }
```

**APIエンドポイントでのエラーハンドリング:**

```python
from fastapi import APIRouter, HTTPException
from datetime import datetime, timedelta
import traceback

router = APIRouter(prefix="/api/v1/org-chart", tags=["org-chart"])

@router.post("/sync")
async def sync_org_chart(request: OrgChartSyncRequest):
    """
    組織図同期API
    """
    sync_log = None
    started_at = datetime.utcnow()

    try:
        # Step 1: 同期ログ作成
        sync_id = f"sync_{started_at.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        sync_log = await OrgChartSyncLog.create(
            sync_id=sync_id,
            organization_id=request.organization_id,
            sync_type=request.sync_type,
            source_system=request.source,
            status='in_progress',
            started_at=started_at,
            request_payload=request.dict()
        )

        # Step 2: 同期競合チェック
        existing_sync = await OrgChartSyncLog.filter(
            organization_id=request.organization_id,
            status='in_progress'
        ).exclude(id=sync_log.id).first()

        if existing_sync:
            raise OrgChartSyncError(
                code=SyncErrorCode.SYNC_CONFLICT,
                message='別の同期処理が実行中です',
                details={
                    'existing_sync_id': existing_sync.sync_id,
                    'existing_started_at': existing_sync.started_at.isoformat()
                }
            )

        # Step 3: 同期処理実行
        result = await perform_sync(request, sync_log)

        # Step 4: 成功レスポンス
        return {
            'status': 'success',
            'sync_id': sync_id,
            'sync_log_url': f'/api/v1/org-chart/sync-logs/{sync_id}',
            'started_at': started_at.isoformat(),
            'completed_at': result['completed_at'].isoformat(),
            'summary': result['summary'],
            'next_sync_recommended': (datetime.utcnow() + timedelta(hours=1)).isoformat()
        }

    except OrgChartSyncError as e:
        # 既知のエラー
        if sync_log:
            await sync_log.update(
                status='failed',
                failed_at=datetime.utcnow(),
                error_code=e.code.value,
                error_message=e.message,
                error_details=e.details,
                duration_ms=int((datetime.utcnow() - started_at).total_seconds() * 1000)
            )

        # リトライ可能なエラーの場合、自動リトライをスケジュール
        if e.recoverable:
            await schedule_retry(
                sync_log_id=sync_log.id if sync_log else None,
                delay_seconds=300  # 5分後
            )

        raise HTTPException(
            status_code=500,
            detail={
                'status': 'failed',
                'sync_id': sync_log.sync_id if sync_log else None,
                'error': e.to_dict(),
                'rollback_status': 'completed' if sync_log else 'not_required',
                'next_action': '5分後に自動リトライします' if e.recoverable else '手動で修正してください'
            }
        )

    except Exception as e:
        # 予期しないエラー
        if sync_log:
            await sync_log.update(
                status='failed',
                failed_at=datetime.utcnow(),
                error_code=SyncErrorCode.UNKNOWN_ERROR.value,
                error_message=str(e),
                error_details={'traceback': traceback.format_exc()},
                duration_ms=int((datetime.utcnow() - started_at).total_seconds() * 1000)
            )

        raise HTTPException(
            status_code=500,
            detail={
                'status': 'failed',
                'sync_id': sync_log.sync_id if sync_log else None,
                'error': {
                    'code': 'UNKNOWN_ERROR',
                    'message': '予期しないエラーが発生しました',
                    'details': str(e),
                    'recoverable': False
                }
            }
        )

async def schedule_retry(sync_log_id: UUID, delay_seconds: int = 300):
    """
    リトライをスケジュール

    実装方法：
    - Celeryタスク
    - Cloud Tasks
    - Redis + ジョブキュー
    """
    # 例：Celeryの場合
    # retry_sync_task.apply_async(args=[sync_log_id], countdown=delay_seconds)
    pass
```

### ■ トランザクション管理【v10.1.2追加】

**同期処理のトランザクション実装:**

```python
from tortoise.transactions import in_transaction
from datetime import datetime

async def perform_sync(
    request: OrgChartSyncRequest,
    sync_log: OrgChartSyncLog
) -> dict:
    """
    同期処理の実行（トランザクション管理）

    全ての変更はトランザクション内で実行され、
    エラー発生時は自動的にロールバックされる。
    """
    started_at = datetime.utcnow()

    async with in_transaction() as connection:
        try:
            # Step 1: データ検証
            await validate_sync_data(request)

            # Step 2: 部署データの同期
            dept_result = await sync_departments(
                organization_id=request.organization_id,
                departments_data=request.departments,
                connection=connection
            )

            # Step 3: 役職データの同期
            role_result = await sync_roles(
                organization_id=request.organization_id,
                roles_data=request.roles,
                connection=connection
            )

            # Step 4: ユーザーデータの同期
            user_result = await sync_users(
                organization_id=request.organization_id,
                employees_data=request.employees,
                connection=connection
            )

            # Step 5: 所属情報の同期
            user_dept_result = await sync_user_departments(
                organization_id=request.organization_id,
                employees_data=request.employees,
                connection=connection
            )

            # Step 6: 階層関係の再計算
            await rebuild_department_hierarchies(
                organization_id=request.organization_id,
                connection=connection
            )

            # Step 7: キャッシュの無効化
            await invalidate_cache(request.organization_id)

            completed_at = datetime.utcnow()
            duration_ms = int((completed_at - started_at).total_seconds() * 1000)

            # Step 8: 同期ログを更新
            await sync_log.update(
                status='success',
                completed_at=completed_at,
                duration_ms=duration_ms,
                departments_added=dept_result.added,
                departments_updated=dept_result.updated,
                departments_deleted=dept_result.deleted,
                roles_added=role_result.added,
                roles_updated=role_result.updated,
                roles_deleted=role_result.deleted,
                users_added=user_result.added,
                users_updated=user_result.updated,
                users_deleted=user_result.deleted,
                user_departments_added=user_dept_result.added,
                user_departments_updated=user_dept_result.updated,
                user_departments_deleted=user_dept_result.deleted
            )

            return {
                'completed_at': completed_at,
                'summary': {
                    'departments': {
                        'added': dept_result.added,
                        'updated': dept_result.updated,
                        'deleted': dept_result.deleted
                    },
                    'roles': {
                        'added': role_result.added,
                        'updated': role_result.updated,
                        'deleted': role_result.deleted
                    },
                    'users': {
                        'added': user_result.added,
                        'updated': user_result.updated,
                        'deleted': user_result.deleted
                    },
                    'user_departments': {
                        'added': user_dept_result.added,
                        'updated': user_dept_result.updated,
                        'deleted': user_dept_result.deleted
                    }
                }
            }

        except Exception as e:
            # トランザクションは自動的にロールバックされる
            raise OrgChartSyncError(
                code=SyncErrorCode.SYNC_PROCESSING_FAILED,
                message='同期処理中にエラーが発生しました',
                details={
                    'error': str(e),
                    'step': 'unknown'  # 実際には各ステップでtry-exceptして特定
                }
            )

async def validate_sync_data(request: OrgChartSyncRequest):
    """
    同期データの検証
    """
    errors = []

    # 部署の親子関係チェック
    dept_ids = {d.id for d in request.departments}
    for dept in request.departments:
        if dept.parentId and dept.parentId not in dept_ids:
            errors.append(f"部署 {dept.id} の親 {dept.parentId} が存在しません")

    # 社員の部署・役職チェック
    role_ids = {r.id for r in request.roles}
    for emp in request.employees:
        if emp.departmentId not in dept_ids:
            errors.append(f"社員 {emp.id} の部署 {emp.departmentId} が存在しません")
        if emp.roleId not in role_ids:
            errors.append(f"社員 {emp.id} の役職 {emp.roleId} が存在しません")

    if errors:
        raise OrgChartSyncError(
            code=SyncErrorCode.DATA_VALIDATION_FAILED,
            message='データ検証に失敗しました',
            details={'errors': errors}
        )

async def rebuild_department_hierarchies(organization_id: UUID, connection=None):
    """
    department_hierarchiesテーブルを再構築

    LTREE pathに基づいて先祖・子孫関係を事前計算
    """
    # 既存データをクリア
    await DepartmentHierarchy.filter(
        organization_id=organization_id
    ).delete()

    # 全部署を取得
    departments = await Department.filter(
        organization_id=organization_id
    ).all()

    # 階層関係を挿入
    for dept in departments:
        # pathを解析して先祖を取得
        path_parts = dept.path.split('.')
        for i, ancestor_code in enumerate(path_parts[:-1]):
            ancestor = await Department.get_or_none(
                organization_id=organization_id,
                code=ancestor_code
            )
            if ancestor:
                await DepartmentHierarchy.create(
                    organization_id=organization_id,
                    ancestor_id=ancestor.id,
                    descendant_id=dept.id,
                    depth=len(path_parts) - i - 1
                )

async def invalidate_cache(organization_id: UUID):
    """
    キャッシュの無効化
    """
    # Redis使用時
    # await redis.delete(f"org:{organization_id}:departments")
    # await redis.delete(f"org:{organization_id}:accessible_depts:*")
    pass
```

---

## 5.2.6 タスク管理テーブル【Phase 1-B】【v10.1.3追加】

### ■ tasksテーブル

**目的:** タスクの期限管理と自動リマインド

**v10.1.3での変更:**
- `notification_room_id` カラム追加（ChatWork通知先ルームID）

**テーブル定義:**

```sql
CREATE TABLE tasks (
    task_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    
    -- タスク情報
    title VARCHAR(500) NOT NULL,
    description TEXT,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',  -- 'pending', 'in_progress', 'completed', 'cancelled'
    priority VARCHAR(50) DEFAULT 'medium',  -- 'low', 'medium', 'high', 'urgent'
    
    -- 期限管理
    due_date DATE,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    
    -- 担当者
    assigned_to UUID REFERENCES users(id),
    created_by UUID NOT NULL REFERENCES users(id),
    
    -- リマインド設定（v10.1.3追加）
    notification_room_id VARCHAR(20),  -- ChatWork通知先ルームID
    
    -- メタデータ
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- インデックス
CREATE INDEX idx_tasks_org ON tasks(organization_id);
CREATE INDEX idx_tasks_assigned ON tasks(assigned_to);
CREATE INDEX idx_tasks_status ON tasks(status);

-- v10.1.3追加: 期限超過タスク検索の高速化
CREATE INDEX idx_tasks_org_due_status 
ON tasks(organization_id, due_date, status);

COMMENT ON COLUMN tasks.notification_room_id IS 
'ChatWork通知先ルームID。タスク作成時に記録。
NULLの場合は管理部ルーム（CHATWORK_MANAGEMENT_ROOM_ID）に通知';

COMMENT ON INDEX idx_tasks_org_due_status IS 
'期限超過タスク検索の最適化。
WHERE organization_id = ? AND due_date < ? AND status != ''completed''
のクエリで使用';
```

---

### ■ notification_logsテーブル【v10.1.4拡張】

**目的:** 汎用通知送信履歴の記録（冪等性確保）

**v10.1.3からの変更点:**
- reminder_logs（タスク専用）→ notification_logs（汎用）
- Phase 2.5（目標達成支援）、Phase C（会議リマインド）にも対応
- マルチテナント対応（organization_id追加）

**特徴:**
- UNIQUE制約で二重送信を防止
- UPSERT仕様（失敗→成功のリトライ時に上書き）
- タスク、目標、会議など、あらゆる通知に対応

**テーブル定義:**

```sql
-- 汎用通知送信履歴テーブル（冪等性確保＋復旧可能）
CREATE TABLE notification_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    
    -- 通知タイプと対象
    notification_type VARCHAR(50) NOT NULL,  -- 'task_reminder', 'goal_reminder', 'meeting_reminder', 'system_notification'
    target_type VARCHAR(50) NOT NULL,        -- 'task', 'goal', 'meeting', 'system'
    target_id UUID,                          -- task_id, goal_id, meeting_id, etc. (NULLable for system notifications)
    
    -- 通知日時
    notification_date DATE NOT NULL,         -- いつの通知か（YYYY-MM-DD）
    sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- ステータス
    status VARCHAR(20) NOT NULL,             -- 'success', 'failed', 'skipped'
    error_message TEXT,
    retry_count INT DEFAULT 0,               -- リトライ回数
    
    -- 通知先
    channel VARCHAR(20),                     -- 'chatwork', 'email', 'slack'
    channel_target VARCHAR(255),             -- room_id, email address, channel_id
    
    -- メタデータ
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID REFERENCES users(id),
    
    -- 冪等性確保のUNIQUE制約
    CONSTRAINT unique_notification UNIQUE(organization_id, target_type, target_id, notification_date, notification_type)
);

-- インデックス
CREATE INDEX idx_notification_logs_org ON notification_logs(organization_id);
CREATE INDEX idx_notification_logs_target ON notification_logs(target_type, target_id);
CREATE INDEX idx_notification_logs_date ON notification_logs(notification_date);
CREATE INDEX idx_notification_logs_status ON notification_logs(status) WHERE status = 'failed';

-- UNIQUE制約のコメント（v10.1.5追加）
COMMENT ON CONSTRAINT unique_notification ON notification_logs IS 
'冪等性保証: 同じ組織・対象・日付・通知タイプで1回のみ送信可能。
1日に同じ対象への複数回送信が必要な場合は、notification_typeを変更する
（例: task_reminder → task_reminder_urgent）。
Scheduler再実行時の二重送信を防止。';

COMMENT ON TABLE notification_logs IS 
'汎用通知送信履歴。
v10.1.4で拡張: タスク、目標、会議など、あらゆる通知に対応。
UNIQUE制約により、同じ対象・同じ日付・同じ通知タイプで複数回送信することを防止。
失敗→成功のリトライ時はUPSERTで上書き。
Scheduler再実行時の冪等性を保証。';

COMMENT ON COLUMN notification_logs.notification_type IS 
'通知タイプ:
- task_reminder: タスク期限超過リマインド
- goal_reminder: 目標達成状況リマインド（Phase 2.5）
- meeting_reminder: 会議リマインド（Phase C）
- system_notification: システム通知';

COMMENT ON COLUMN notification_logs.target_type IS 
'対象タイプ:
- task: タスク
- goal: 目標（Phase 2.5）
- meeting: 会議（Phase C）
- system: システム全体（target_id = NULL）';
```

**UPSERT時の使用例:**

```python
# 失敗→成功のリトライでログを更新
await conn.execute("""
    INSERT INTO notification_logs (
        organization_id, 
        notification_type, 
        target_type, 
        target_id, 
        notification_date, 
        status, 
        sent_at, 
        error_message,
        retry_count,
        channel,
        channel_target
    )
    VALUES ($1, $2, $3, $4, $5, $6, NOW(), $7, $8, $9, $10)
    ON CONFLICT (organization_id, target_type, target_id, notification_date, notification_type) 
    DO UPDATE SET 
        status = EXCLUDED.status,
        sent_at = NOW(),
        error_message = EXCLUDED.error_message,
        retry_count = notification_logs.retry_count + 1,
        updated_at = NOW()
""", 
    organization_id, 
    'task_reminder',  # notification_type
    'task',           # target_type
    task_id,          # target_id
    remind_date,      # notification_date
    status, 
    error_message,
    retry_count,
    'chatwork',       # channel
    room_id           # channel_target
)
```

**v10.1.3からのマイグレーション:**

```sql
-- Step 1: notification_logsテーブル作成（上記SQL）

-- Step 2: reminder_logsのデータをnotification_logsに移行
INSERT INTO notification_logs (
    organization_id,
    notification_type,
    target_type,
    target_id,
    notification_date,
    sent_at,
    status,
    error_message,
    retry_count,
    channel,
    channel_target,
    created_at,
    updated_at
)
SELECT 
    t.organization_id,        -- tasksテーブルからorganization_idを取得
    'task_reminder',          -- notification_type
    'task',                   -- target_type
    rl.task_id,               -- target_id
    rl.remind_date,           -- notification_date
    rl.sent_at,
    rl.status,
    rl.error_message,
    0,                        -- retry_count（デフォルト）
    'chatwork',               -- channel（デフォルト）
    t.notification_room_id,   -- channel_target
    rl.created_at,
    rl.updated_at
FROM reminder_logs rl
INNER JOIN tasks t ON rl.task_id = t.task_id;

-- Step 3: reminder_logsテーブルを削除（オプション）
-- DROP TABLE reminder_logs;
```

**将来の拡張例（Phase 2.5: 目標達成支援）:**

```python
# 目標達成リマインド
await conn.execute("""
    INSERT INTO notification_logs (
        organization_id, notification_type, target_type, target_id, 
        notification_date, status, channel, channel_target
    )
    VALUES ($1, 'goal_reminder', 'goal', $2, $3, 'success', 'chatwork', $4)
    ON CONFLICT (organization_id, target_type, target_id, notification_date, notification_type) 
    DO UPDATE SET status = EXCLUDED.status, sent_at = NOW()
""", organization_id, goal_id, today, room_id)
```

**将来の拡張例（Phase C: 会議リマインド）:**

```python
# 会議リマインド
await conn.execute("""
    INSERT INTO notification_logs (
        organization_id, notification_type, target_type, target_id, 
        notification_date, status, channel, channel_target
    )
    VALUES ($1, 'meeting_reminder', 'meeting', $2, $3, 'success', 'chatwork', $4)
    ON CONFLICT (organization_id, target_type, target_id, notification_date, notification_type) 
    DO UPDATE SET status = EXCLUDED.status, sent_at = NOW()
""", organization_id, meeting_id, today, room_id)
```

---

## 5.2.7 脳の学習・記憶テーブル【Phase 2E/2G】【新設】

**目的:** 脳の学習（Phase 2E）と記憶強化（Phase 2G）をDBレベルで一貫して管理する  
**実装参照:** migrations/phase2e_learning_foundation.sql / migrations/phase2g_memory_enhancement.sql

### ■ brain_learnings（学習内容）

```sql
CREATE TABLE IF NOT EXISTS brain_learnings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    category VARCHAR(50) NOT NULL,
    learned_content JSONB NOT NULL,
    learned_content_version INT DEFAULT 1,
    scope VARCHAR(50) NOT NULL,
    scope_target_id VARCHAR(100),
    trigger_type VARCHAR(50) NOT NULL,
    trigger_value TEXT,
    trigger_pattern TEXT,
    authority_level VARCHAR(30) NOT NULL,
    decision_impact VARCHAR(30) NOT NULL,
    relationship_type VARCHAR(30),
    taught_by_account_id VARCHAR(50),
    taught_by_user_name VARCHAR(200),
    taught_at TIMESTAMPTZ DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE,
    supersedes_id UUID REFERENCES brain_learnings(id),
    superseded_by_id UUID REFERENCES brain_learnings(id),
    related_ceo_teaching_id UUID,
    related_learning_ids UUID[] DEFAULT '{}',
    applied_count INT DEFAULT 0,
    success_count INT DEFAULT 0,
    failure_count INT DEFAULT 0,
    effectiveness_score DECIMAL(3,2) DEFAULT 0.5,
    last_applied_at TIMESTAMPTZ,
    detection_pattern VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_brain_learnings_org
    ON brain_learnings(organization_id);
CREATE INDEX IF NOT EXISTS idx_brain_learnings_category
    ON brain_learnings(organization_id, category);
CREATE INDEX IF NOT EXISTS idx_brain_learnings_trigger
    ON brain_learnings(trigger_type, trigger_value);
CREATE INDEX IF NOT EXISTS idx_brain_learnings_scope
    ON brain_learnings(organization_id, scope, scope_target_id);
CREATE INDEX IF NOT EXISTS idx_brain_learnings_active
    ON brain_learnings(organization_id, is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_brain_learnings_authority
    ON brain_learnings(authority_level);
CREATE INDEX IF NOT EXISTS idx_brain_learnings_effectiveness
    ON brain_learnings(effectiveness_score DESC);
CREATE INDEX IF NOT EXISTS idx_brain_learnings_learned_content
    ON brain_learnings USING GIN(learned_content jsonb_path_ops);
```

### ■ brain_learning_logs（学習適用ログ）

```sql
CREATE TABLE IF NOT EXISTS brain_learning_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    learning_id UUID NOT NULL REFERENCES brain_learnings(id) ON DELETE CASCADE,
    applied_at TIMESTAMPTZ DEFAULT NOW(),
    applied_for_account_id VARCHAR(50),
    applied_for_user_name VARCHAR(200),
    applied_in_room_id VARCHAR(50),
    applied_result JSONB DEFAULT '{}',
    was_successful BOOLEAN,
    context_hash VARCHAR(64),
    context_summary TEXT,
    feedback_received BOOLEAN DEFAULT FALSE,
    feedback_message TEXT,
    user_feedback_at TIMESTAMPTZ,
    feedback_positive BOOLEAN,
    response_latency_ms INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_brain_learning_logs_learning
    ON brain_learning_logs(learning_id);
CREATE INDEX IF NOT EXISTS idx_brain_learning_logs_org
    ON brain_learning_logs(organization_id);
CREATE INDEX IF NOT EXISTS idx_brain_learning_logs_applied_at
    ON brain_learning_logs(applied_at DESC);
CREATE INDEX IF NOT EXISTS idx_brain_learning_logs_feedback
    ON brain_learning_logs(learning_id, feedback_received) WHERE feedback_received = TRUE;
```

### ■ brain_episodes（エピソード記憶）

```sql
CREATE TABLE IF NOT EXISTS brain_episodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    user_id VARCHAR(50),
    episode_type VARCHAR(30) NOT NULL DEFAULT 'interaction',
    summary TEXT NOT NULL,
    details JSONB DEFAULT '{}',
    emotional_valence DECIMAL(3,2) DEFAULT 0.0,
    importance_score DECIMAL(3,2) DEFAULT 0.5,
    keywords TEXT[] DEFAULT '{}',
    embedding_id VARCHAR(100),
    recall_count INT DEFAULT 0,
    last_recalled_at TIMESTAMPTZ,
    decay_factor DECIMAL(3,2) DEFAULT 1.0,
    room_id VARCHAR(50),
    occurred_at TIMESTAMPTZ DEFAULT NOW(),
    source VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_brain_episodes_org_user
    ON brain_episodes(organization_id, user_id);
CREATE INDEX IF NOT EXISTS idx_brain_episodes_type
    ON brain_episodes(organization_id, episode_type);
CREATE INDEX IF NOT EXISTS idx_brain_episodes_keywords
    ON brain_episodes USING GIN(keywords);
CREATE INDEX IF NOT EXISTS idx_brain_episodes_occurred
    ON brain_episodes(organization_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_brain_episodes_importance
    ON brain_episodes(organization_id, importance_score DESC);
```

### ■ brain_episode_entities（エピソード-エンティティ関連）

```sql
CREATE TABLE IF NOT EXISTS brain_episode_entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    episode_id UUID NOT NULL REFERENCES brain_episodes(id) ON DELETE CASCADE,
    entity_type VARCHAR(30) NOT NULL,
    entity_id VARCHAR(100) NOT NULL,
    entity_name VARCHAR(200),
    relationship VARCHAR(30) NOT NULL DEFAULT 'involved',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_brain_episode_entities_episode
    ON brain_episode_entities(episode_id);
CREATE INDEX IF NOT EXISTS idx_brain_episode_entities_entity
    ON brain_episode_entities(organization_id, entity_type, entity_id);
```

### ■ brain_knowledge_nodes（知識ノード）

```sql
CREATE TABLE IF NOT EXISTS brain_knowledge_nodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    node_type VARCHAR(30) NOT NULL,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    aliases TEXT[] DEFAULT '{}',
    properties JSONB DEFAULT '{}',
    importance_score DECIMAL(3,2) DEFAULT 0.5,
    activation_level DECIMAL(3,2) DEFAULT 0.5,
    source VARCHAR(30) NOT NULL DEFAULT 'learned',
    confidence DECIMAL(3,2) DEFAULT 0.8,
    evidence_count INT DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_brain_knowledge_nodes_org
    ON brain_knowledge_nodes(organization_id);
CREATE INDEX IF NOT EXISTS idx_brain_knowledge_nodes_type
    ON brain_knowledge_nodes(organization_id, node_type);
CREATE INDEX IF NOT EXISTS idx_brain_knowledge_nodes_name
    ON brain_knowledge_nodes(organization_id, LOWER(name));
CREATE INDEX IF NOT EXISTS idx_brain_knowledge_nodes_aliases
    ON brain_knowledge_nodes USING GIN(aliases);
```

### ■ brain_knowledge_edges（知識エッジ）

```sql
CREATE TABLE IF NOT EXISTS brain_knowledge_edges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    source_node_id UUID NOT NULL REFERENCES brain_knowledge_nodes(id) ON DELETE CASCADE,
    target_node_id UUID NOT NULL REFERENCES brain_knowledge_nodes(id) ON DELETE CASCADE,
    edge_type VARCHAR(30) NOT NULL,
    description TEXT,
    properties JSONB DEFAULT '{}',
    weight DECIMAL(3,2) DEFAULT 1.0,
    evidence TEXT[] DEFAULT '{}',
    evidence_count INT DEFAULT 1,
    source VARCHAR(30) NOT NULL DEFAULT 'learned',
    confidence DECIMAL(3,2) DEFAULT 0.8,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(organization_id, source_node_id, target_node_id, edge_type)
);

CREATE INDEX IF NOT EXISTS idx_brain_knowledge_edges_source
    ON brain_knowledge_edges(source_node_id);
CREATE INDEX IF NOT EXISTS idx_brain_knowledge_edges_target
    ON brain_knowledge_edges(target_node_id);
CREATE INDEX IF NOT EXISTS idx_brain_knowledge_edges_type
    ON brain_knowledge_edges(organization_id, edge_type);
```

### ■ brain_temporal_events（時系列イベント）

```sql
CREATE TABLE IF NOT EXISTS brain_temporal_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    user_id VARCHAR(50),
    event_type VARCHAR(30) NOT NULL,
    event_name VARCHAR(200) NOT NULL,
    event_value DECIMAL,
    event_data JSONB DEFAULT '{}',
    related_entity_type VARCHAR(30),
    related_entity_id VARCHAR(100),
    related_episode_id UUID REFERENCES brain_episodes(id) ON DELETE SET NULL,
    event_at TIMESTAMPTZ NOT NULL,
    period_start TIMESTAMPTZ,
    period_end TIMESTAMPTZ,
    source VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_brain_temporal_events_org_user
    ON brain_temporal_events(organization_id, user_id);
CREATE INDEX IF NOT EXISTS idx_brain_temporal_events_type
    ON brain_temporal_events(organization_id, event_type);
CREATE INDEX IF NOT EXISTS idx_brain_temporal_events_entity
    ON brain_temporal_events(organization_id, related_entity_type, related_entity_id);
CREATE INDEX IF NOT EXISTS idx_brain_temporal_events_time
    ON brain_temporal_events(organization_id, event_at DESC);
```

### ■ brain_temporal_comparisons（時系列比較）

```sql
CREATE TABLE IF NOT EXISTS brain_temporal_comparisons (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    comparison_type VARCHAR(30) NOT NULL,
    subject_type VARCHAR(30) NOT NULL,
    subject_id VARCHAR(100) NOT NULL,
    subject_name VARCHAR(200),
    baseline_event_id UUID REFERENCES brain_temporal_events(id) ON DELETE SET NULL,
    current_event_id UUID REFERENCES brain_temporal_events(id) ON DELETE SET NULL,
    baseline_value DECIMAL,
    current_value DECIMAL,
    change_value DECIMAL,
    change_percent DECIMAL,
    trend VARCHAR(30),
    analysis_summary TEXT,
    analysis_details JSONB DEFAULT '{}',
    confidence DECIMAL(3,2) DEFAULT 0.8,
    period_label VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_brain_temporal_comparisons_subject
    ON brain_temporal_comparisons(organization_id, subject_type, subject_id);
CREATE INDEX IF NOT EXISTS idx_brain_temporal_comparisons_trend
    ON brain_temporal_comparisons(organization_id, trend);
```

### ■ brain_memory_consolidations（記憶統合ログ）

```sql
CREATE TABLE IF NOT EXISTS brain_memory_consolidations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    consolidation_type VARCHAR(30) NOT NULL,
    action VARCHAR(30) NOT NULL,
    source_type VARCHAR(30) NOT NULL,
    source_ids UUID[] NOT NULL,
    target_id UUID,
    summary TEXT,
    details JSONB DEFAULT '{}',
    episodes_processed INT DEFAULT 0,
    episodes_merged INT DEFAULT 0,
    episodes_forgotten INT DEFAULT 0,
    triggered_by VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_brain_memory_consolidations_org
    ON brain_memory_consolidations(organization_id);
CREATE INDEX IF NOT EXISTS idx_brain_memory_consolidations_type
    ON brain_memory_consolidations(organization_id, consolidation_type);
CREATE INDEX IF NOT EXISTS idx_brain_memory_consolidations_created
    ON brain_memory_consolidations(organization_id, created_at DESC);
```


---

**[📁 目次に戻る](00_README.md)**
