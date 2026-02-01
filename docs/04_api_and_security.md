# 第5.5章：API設計【新設】

---

## Document Contract（SoT宣言）

| 項目 | 内容 |
|------|------|
| **この文書の役割** | API設計・セキュリティ実装の詳細仕様 |
| **書くこと** | APIエンドポイント仕様、認証・認可実装、セキュリティ対策、監査ログ実装 |
| **書かないこと** | 原則・概念（→CLAUDE.md）、テーブル定義（→03章）、脳の設計（→25章） |
| **SoT（この文書が正）** | API仕様、Authorization Gate実装、監査ログ実装、権限レベル実装、RLS実装 |
| **Owner** | カズさん（代表） |
| **関連リンク** | [CLAUDE.md](../CLAUDE.md)（原則）、[03章](03_database_design.md)（DB設計）、[Design Coverage Matrix](DESIGN_COVERAGE_MATRIX.md) |

---

## 5.5.1 組織図同期API

### ■ POST /api/v1/organizations/{org_id}/sync-org-chart

**目的:** 組織図Webアプリからソウル君DBに組織構造を同期する

**認証:** Bearer Token（管理者権限必須）

**リクエスト:**

```json
{
  "organization_id": "org_soulsyncs",
  "source": "org_chart_system",
  "sync_type": "full",

  "departments": [
    {
      "id": "dept_honsha",
      "name": "本社",
      "code": "HQ",
      "parentId": null,
      "level": 1,
      "displayOrder": 1,
      "isActive": true
    },
    {
      "id": "dept_eigyo",
      "name": "営業部",
      "code": "SALES",
      "parentId": "dept_honsha",
      "level": 2,
      "displayOrder": 1,
      "isActive": true
    },
    {
      "id": "dept_eigyo_1ka",
      "name": "営業1課",
      "code": "SALES1",
      "parentId": "dept_eigyo",
      "level": 3,
      "displayOrder": 1,
      "isActive": true
    }
  ],

  "roles": [
    {
      "id": "role_ceo",
      "name": "CEO",
      "level": 1,
      "description": "最高経営責任者"
    },
    {
      "id": "role_bucho",
      "name": "部長",
      "level": 2,
      "description": "部門責任者"
    },
    {
      "id": "role_kacho",
      "name": "課長",
      "level": 3,
      "description": "課責任者"
    },
    {
      "id": "role_member",
      "name": "社員",
      "level": 4,
      "description": "一般社員"
    }
  ],

  "employees": [
    {
      "id": "user_kazu",
      "name": "菊地雅克",
      "email": "kazu@soulsyncs.jp",
      "departmentId": "dept_honsha",
      "roleId": "role_ceo",
      "isPrimary": true,
      "startDate": "2018-01-01",
      "endDate": null
    },
    {
      "id": "user_tanaka",
      "name": "田中太郎",
      "email": "tanaka@soulsyncs.jp",
      "departmentId": "dept_eigyo",
      "roleId": "role_bucho",
      "isPrimary": true,
      "startDate": "2020-04-01",
      "endDate": null
    }
  ],

  "options": {
    "include_inactive_users": false,
    "include_archived_departments": false,
    "dry_run": false
  }
}
```

**レスポンス（成功時）:**

```json
{
  "status": "success",
  "sync_id": "sync_log_001",
  "summary": {
    "departments_added": 5,
    "departments_updated": 2,
    "departments_deleted": 0,
    "users_added": 10,
    "users_updated": 3,
    "users_deleted": 1
  },
  "duration_ms": 5000,
  "synced_at": "2025-01-13T10:00:05Z"
}
```

**レスポンス（エラー時）:**

```json
{
  "status": "failed",
  "error_code": "CIRCULAR_REFERENCE",
  "error_message": "部署 'dept_sales' が循環参照を引き起こします",
  "error_details": {
    "department_id": "dept_sales",
    "circular_path": ["dept_sales", "dept_tokyo", "dept_sales"]
  }
}
```

**エラーコード一覧:**

| エラーコード | 説明 | HTTPステータス |
|------------|------|---------------|
| CIRCULAR_REFERENCE | 循環参照が検出された | 400 |
| ORPHAN_DEPARTMENT | 親部署が存在しない | 400 |
| DUPLICATE_CODE | 部署コードが重複 | 400 |
| INVALID_USER | ユーザーIDが存在しない | 404 |
| UNAUTHORIZED | 管理者権限がない | 403 |
| TOO_MANY_DEPARTMENTS | 部署数が上限を超過 | 400 |

**処理フロー:**

```python
@app.post("/api/v1/organizations/{org_id}/sync-org-chart")
async def sync_org_chart(
    org_id: str,
    data: OrgChartSyncRequest,
    user: User = Depends(get_current_user)
):
    """組織図同期API"""
    
    # 1. 権限チェック
    await authorize(user, "organization", "manage")
    
    # 2. 同期ログ作成
    sync_log = await OrgChartSyncLog.create(
        organization_id=org_id,
        sync_type=data.sync_type,
        status="in_progress",
        started_at=datetime.now(),
        triggered_by=user.id
    )
    
    try:
        # 3. トランザクション開始
        async with db.transaction():
            
            # 4. バリデーション
            await validate_org_chart_data(data)
            
            # 5. フルシンクの場合、既存データを削除
            if data.sync_type == "full":
                await Department.filter(organization_id=org_id).delete()
                await UserDepartment.filter(
                    user_id__organization_id=org_id
                ).delete()
            
            # 6. 部署データを挿入（階層順）
            dept_map = {}
            sorted_depts = topological_sort(data.departments)
            
            for dept_data in sorted_depts:
                # 親部署のパスを取得
                if dept_data.parent_id:
                    parent = dept_map[dept_data.parent_id]
                    path = f"{parent.path}.{dept_data.code.lower()}"
                else:
                    path = dept_data.code.lower()
                
                dept = await Department.create(
                    id=dept_data.id,
                    organization_id=org_id,
                    name=dept_data.name,
                    code=dept_data.code,
                    parent_department_id=dept_data.parent_id,
                    level=dept_data.level,
                    path=path,
                    display_order=dept_data.display_order,
                    description=dept_data.description
                )
                dept_map[dept.id] = dept
            
            # 7. 階層テーブルを再構築
            await rebuild_department_hierarchies(org_id)
            
            # 8. ユーザー所属を更新
            for ud_data in data.user_departments:
                await UserDepartment.create(
                    user_id=ud_data.user_id,
                    department_id=ud_data.department_id,
                    is_primary=ud_data.is_primary,
                    role_in_dept=ud_data.role_in_dept,
                    started_at=ud_data.started_at
                )
            
            # 9. アクセススコープを更新
            for scope_data in data.access_scopes:
                await DepartmentAccessScope.update_or_create(
                    department_id=scope_data.department_id,
                    defaults={
                        "can_view_child_departments": scope_data.can_view_child_departments,
                        "can_view_sibling_departments": scope_data.can_view_sibling_departments,
                        "max_depth": scope_data.max_depth
                    }
                )
        
        # 10. 同期ログ更新（成功）
        await sync_log.update(
            status="success",
            completed_at=datetime.now(),
            departments_added=len(data.departments),
            users_added=len(data.user_departments)
        )
        
        # 11. キャッシュクリア
        await clear_org_hierarchy_cache(org_id)
        
        return {
            "status": "success",
            "sync_id": sync_log.id,
            "summary": {
                "departments_added": len(data.departments),
                "users_added": len(data.user_departments)
            }
        }
        
    except Exception as e:
        # エラー時のロールバック
        await sync_log.update(
            status="failed",
            error_message=str(e),
            completed_at=datetime.now()
        )
        raise
```

**バリデーション:**

```python
async def validate_org_chart_data(data: OrgChartSyncRequest):
    """組織図データのバリデーション"""
    
    # 1. 循環参照チェック
    graph = build_department_graph(data.departments)
    if has_cycle(graph):
        raise ValueError("循環参照が検出されました")
    
    # 2. 孤立部署チェック
    orphans = find_orphan_departments(data.departments)
    if orphans:
        raise ValueError(f"親部署が存在しない部署: {orphans}")
    
    # 3. 部署コード重複チェック
    codes = [d.code for d in data.departments]
    if len(codes) != len(set(codes)):
        raise ValueError("部署コードが重複しています")
    
    # 4. ユーザー存在チェック
    user_ids = [ud.user_id for ud in data.user_departments]
    existing_users = await User.filter(id__in=user_ids).count()
    if existing_users != len(set(user_ids)):
        raise ValueError("存在しないユーザーIDが含まれています")
```

**トポロジカルソート（階層順に並び替え）:**

```python
def topological_sort(departments: list[DepartmentData]) -> list[DepartmentData]:
    """
    部署を階層順にソート（親 → 子の順）
    """
    # 依存グラフを構築
    graph = defaultdict(list)
    in_degree = defaultdict(int)
    dept_map = {d.id: d for d in departments}
    
    for dept in departments:
        if dept.parent_id:
            graph[dept.parent_id].append(dept.id)
            in_degree[dept.id] += 1
        else:
            in_degree[dept.id] = 0
    
    # トポロジカルソート（Kahn's algorithm）
    queue = [d.id for d in departments if in_degree[d.id] == 0]
    sorted_ids = []
    
    while queue:
        dept_id = queue.pop(0)
        sorted_ids.append(dept_id)
        
        for child_id in graph[dept_id]:
            in_degree[child_id] -= 1
            if in_degree[child_id] == 0:
                queue.append(child_id)
    
    # 循環参照チェック
    if len(sorted_ids) != len(departments):
        raise ValueError("循環参照が検出されました")
    
    return [dept_map[dept_id] for dept_id in sorted_ids]
```

### ■ リカバリ設計（Staged Commit方式）【v10.55追加】

> **背景**: `sync_type=full` で全削除→再作成を行う場合、途中でエラーが発生するとデータが消失するリスクがある。
> このリスクを軽減するため、Staged Commit方式を採用する。

#### Staged Commit方式の概要

```
従来（危険）:
  1. 既存データを削除 ← ここで失敗するとデータ消失
  2. 新データを挿入
  3. 完了

Staged Commit方式（安全）:
  1. 新データをステージングテーブルに作成
  2. ステージングデータを検証
  3. 検証OKなら、アトミックに切り替え ← 失敗しても旧データは残る
  4. 旧データをバックアップとして保持（24時間）
```

#### 実装例

```python
async def sync_org_chart_staged(
    org_id: str,
    data: OrgChartSyncRequest
) -> dict:
    """
    Staged Commit方式での組織図同期

    1. 新データを別テーブルに準備
    2. 検証が全てパスしたら、アトミックに切り替え
    3. 失敗時は旧データがそのまま残る
    """
    staging_suffix = f"_staging_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    backup_suffix = f"_backup_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    try:
        # === Phase 1: ステージングテーブルに新データ作成 ===
        await create_staging_tables(org_id, staging_suffix)
        await populate_staging_data(org_id, staging_suffix, data)

        # === Phase 2: ステージングデータの検証 ===
        validation_result = await validate_staging_data(org_id, staging_suffix)
        if not validation_result.is_valid:
            raise ValueError(f"検証失敗: {validation_result.errors}")

        # === Phase 3: 依存関係の検証（タスク、権限等） ===
        dependency_result = await validate_dependencies(org_id, staging_suffix)
        if not dependency_result.is_valid:
            raise ValueError(f"依存関係エラー: {dependency_result.errors}")

        # === Phase 4: アトミックに切り替え ===
        async with db.transaction():
            # 4-1. 現行テーブルをバックアップにリネーム
            await rename_tables(org_id, "", backup_suffix)

            # 4-2. ステージングテーブルを本番にリネーム
            await rename_tables(org_id, staging_suffix, "")

        # === Phase 5: クリーンアップ（非同期） ===
        # バックアップは24時間後に削除（即時削除しない）
        await schedule_backup_cleanup(org_id, backup_suffix, hours=24)

        return {
            "status": "success",
            "backup_id": backup_suffix,
            "message": "24時間以内であればバックアップから復元可能"
        }

    except Exception as e:
        # 失敗時: ステージングテーブルを削除、旧データは維持
        await drop_staging_tables(org_id, staging_suffix)
        raise


async def restore_from_backup(org_id: str, backup_suffix: str) -> dict:
    """
    バックアップからの復元

    バックアップテーブルが存在する場合（24時間以内）、
    現行データをバックアップに戻す。
    """
    # バックアップの存在確認
    if not await backup_tables_exist(org_id, backup_suffix):
        raise ValueError(f"バックアップが見つかりません: {backup_suffix}")

    async with db.transaction():
        # 現行テーブルを削除
        await drop_tables(org_id, "")

        # バックアップを本番にリネーム
        await rename_tables(org_id, backup_suffix, "")

    return {
        "status": "restored",
        "message": f"バックアップ {backup_suffix} から復元完了"
    }
```

#### リカバリ手順

| シナリオ | 検出方法 | 復旧手順 | RTO |
|---------|---------|---------|-----|
| 同期中にエラー | トランザクションロールバック | 自動復旧（旧データ維持） | 0分 |
| 同期完了後に問題発覚 | 手動検出 | `restore_from_backup()` 実行 | 5分 |
| バックアップ期限切れ | 24時間経過 | 日次バックアップから復元 | 1時間 |

#### バックアップ保持期間

| データ | 保持期間 | 自動削除 | 理由 |
|--------|---------|---------|------|
| 同期前バックアップ | 24時間 | ✅ | 当日中の問題検出用 |
| 日次DBバックアップ | 7日 | ✅ | 週単位での問題検出用 |
| 月次アーカイブ | 1年 | ❌ | 長期保存用 |

#### API拡張（バックアップ操作）

```
# バックアップ一覧
GET /api/v1/organizations/{org_id}/sync-backups

# バックアップから復元
POST /api/v1/organizations/{org_id}/sync-backups/{backup_id}/restore
```

---

## 5.5.2 組織階層照会API

### ■ GET /api/v1/organizations/{org_id}/departments

**目的:** 組織の部署一覧を取得

**認証:** Bearer Token

**クエリパラメータ:**

| パラメータ | 型 | 必須 | 説明 | 例 |
|----------|---|------|------|-----|
| parent_id | UUID | × | 親部署ID（指定すると子部署のみ） | `dept_sales` |
| level | INT | × | 階層レベル | `2`（部レベル） |
| include_children | BOOL | × | 配下すべて含む | `true` |
| is_active | BOOL | × | 有効な部署のみ | `true` |

**レスポンス:**

```json
{
  "departments": [
    {
      "id": "dept_sales",
      "name": "営業部",
      "code": "SALES",
      "parent_id": null,
      "level": 1,
      "path": "soulsyncs.sales",
      "children_count": 2,
      "member_count": 15
    },
    {
      "id": "dept_sales_tokyo",
      "name": "東京営業課",
      "code": "SALES-01",
      "parent_id": "dept_sales",
      "level": 2,
      "path": "soulsyncs.sales.tokyo",
      "children_count": 0,
      "member_count": 8
    }
  ],
  "total": 2
}
```

---

### ■ GET /api/v1/organizations/{org_id}/departments/{dept_id}

**目的:** 特定の部署の詳細情報を取得

**レスポンス:**

```json
{
  "id": "dept_sales_tokyo",
  "name": "東京営業課",
  "code": "SALES-01",
  "parent_id": "dept_sales",
  "level": 2,
  "path": "soulsyncs.sales.tokyo",
  "description": "東京エリアの営業を担当",
  "parent": {
    "id": "dept_sales",
    "name": "営業部"
  },
  "children": [],
  "members": [
    {
      "user_id": "user_yamada",
      "name": "山田太郎",
      "role_in_dept": "課長",
      "is_primary": true
    }
  ],
  "access_scope": {
    "can_view_child_departments": true,
    "can_view_sibling_departments": false,
    "max_depth": 1
  }
}
```

---

### ■ GET /api/v1/users/{user_id}/accessible-departments

**目的:** ユーザーがアクセス可能な部署一覧を取得

**認証:** Bearer Token（本人または管理者のみ）

**レスポンス:**

```json
{
  "user_id": "user_yamada",
  "primary_department": {
    "id": "dept_sales_tokyo",
    "name": "東京営業課",
    "role_in_dept": "課長"
  },
  "accessible_departments": [
    {
      "id": "dept_sales_tokyo",
      "name": "東京営業課",
      "access_reason": "primary"
    },
    {
      "id": "dept_sales_tokyo_team1",
      "name": "第一係",
      "access_reason": "child"
    }
  ],
  "total": 2
}
```

**実装:**

```python
@app.get("/api/v1/users/{user_id}/accessible-departments")
async def get_accessible_departments(
    user_id: str,
    current_user: User = Depends(get_current_user)
):
    """ユーザーのアクセス可能部署を取得"""
    
    # 権限チェック（本人または管理者）
    if current_user.id != user_id:
        await authorize(current_user, "user", "view")
    
    # ユーザーの所属部署を取得
    user_depts = await UserDepartment.filter(
        user_id=user_id,
        ended_at=None
    ).prefetch_related("department").all()
    
    # アクセス可能部署を計算
    accessible = await compute_accessible_departments(current_user, user_depts)
    
    return {
        "user_id": user_id,
        "accessible_departments": accessible
    }
```

---

## 5.5.3 アクセス権限判定API

### ■ POST /api/v1/users/{user_id}/check-access

**目的:** ユーザーが特定のリソースにアクセス可能かを判定

**リクエスト:**

```json
{
  "resource_type": "document",
  "resource_id": "doc_001",
  "action": "view"
}
```

**レスポンス:**

```json
{
  "user_id": "user_yamada",
  "resource_type": "document",
  "resource_id": "doc_001",
  "action": "view",
  "allowed": true,
  "reason": "user_department_match",
  "details": {
    "user_department": "dept_sales_tokyo",
    "document_department": "dept_sales_tokyo",
    "document_classification": "confidential"
  }
}
```

**実装:**

```python
@app.post("/api/v1/users/{user_id}/check-access")
async def check_access(
    user_id: str,
    request: AccessCheckRequest,
    current_user: User = Depends(get_current_user)
):
    """アクセス権限を判定"""
    
    user = await User.get(user_id)
    
    if request.resource_type == "document":
        document = await Document.get(request.resource_id)
        allowed = await can_access_document(user, document)
        reason = get_access_reason(user, document)
        
        return {
            "user_id": user_id,
            "resource_type": "document",
            "resource_id": document.id,
            "action": request.action,
            "allowed": allowed,
            "reason": reason
        }
```

**権限判定ロジック:**

```python
async def can_access_document(user: User, document: Document) -> bool:
    """ドキュメントへのアクセス権限を判定"""
    
    # 1. 機密区分チェック
    if document.classification == "public":
        return True  # 全員OK
    
    if document.classification == "internal":
        return user.organization_id == document.organization_id  # 社員ならOK
    
    if document.classification == "restricted":
        return user.role == "admin"  # 経営陣のみ
    
    # 2. confidential（部門限定）の判定
    if document.classification == "confidential":
        # ユーザーのアクセス可能部署を取得
        accessible_depts = await get_user_accessible_departments(user)
        
        # ドキュメントの所属部署がアクセス可能部署に含まれるか
        if document.department_id in accessible_depts:
            return True
        
        # 特別権限（override）を確認
        scope = await DepartmentAccessScope.get_or_none(
            department_id__in=accessible_depts
        )
        if scope and scope.override_confidential_access:
            return True
    
    return False
```

---

## 5.5.4 RAG検索API（組織フィルタ統合版）

### ■ POST /api/v1/knowledge/search

**目的:** ナレッジ検索（組織階層を考慮）

**リクエスト:**

```json
{
  "query": "経費精算のやり方を教えて",
  "filters": {
    "category": ["B"],  // マニュアル
    "classification": ["internal", "confidential"]
  },
  "top_k": 10
}
```

**レスポンス:**

```json
{
  "query": "経費精算のやり方を教えて",
  "answer": "経費精算は以下の手順で行います...",
  "sources": [
    {
      "chunk_id": "chunk_001",
      "document_id": "doc_manual_001",
      "document_title": "経費精算マニュアル",
      "page": 5,
      "section": "2.3 経費精算の手順",
      "score": 0.92,
      "text": "経費精算は、まず領収書を撮影し..."
    }
  ],
  "answer_refused": false,
  "refused_reason": null,
  "search_time_ms": 150
}
```

**実装（組織フィルタ統合版）:**

```python
@app.post("/api/v1/knowledge/search")
async def search_knowledge(
    request: KnowledgeSearchRequest,
    user: User = Depends(get_current_user)
):
    """ナレッジ検索（組織階層を考慮）"""
    
    start_time = time.time()
    
    # 1. ユーザーのアクセス可能部署を取得（キャッシュ活用）
    accessible_depts = await get_user_accessible_departments_cached(user)
    
    # 2. Pinecone検索フィルタを構築
    filters = {
        "organization_id": user.organization_id,
        "$or": [
            {"classification": "public"},
            {"classification": "internal"},
            {
                "classification": "confidential",
                "department_id": {"$in": accessible_depts}  # ★組織フィルタ
            }
        ]
    }
    
    # カテゴリフィルタがあれば追加
    if request.filters and request.filters.category:
        filters["category"] = {"$in": request.filters.category}
    
    # 3. Embedding生成
    query_embedding = await compute_embedding(request.query)
    
    # 4. Pinecone検索
    search_results = await pinecone_index.query(
        vector=query_embedding,
        filter=filters,
        top_k=request.top_k or 10,
        include_metadata=True
    )
    
    # 5. 回答生成判定
    should_generate, reason = should_generate_answer(search_results)
    
    if not should_generate:
        # 検索ログに記録
        await KnowledgeSearchLog.create(
            user_id=user.id,
            query=request.query,
            answer_refused=True,
            refused_reason=reason
        )
        
        return {
            "query": request.query,
            "answer": None,
            "sources": [],
            "answer_refused": True,
            "refused_reason": reason
        }
    
    # 6. 回答生成
    answer = await generate_answer_with_sources(
        query=request.query,
        sources=search_results
    )
    
    # 7. 検索ログに記録
    await KnowledgeSearchLog.create(
        user_id=user.id,
        query=request.query,
        answer=answer,
        sources=[r.id for r in search_results],
        answer_refused=False,
        search_time_ms=int((time.time() - start_time) * 1000)
    )
    
    # 8. 監査ログに記録（機密情報の場合）
    if any(r.metadata.get("classification") == "confidential" for r in search_results):
        await AuditLog.create(
            user_id=user.id,
            action="view_confidential_knowledge",
            resource_type="knowledge",
            resource_ids=[r.metadata.get("document_id") for r in search_results],
            details={"query": request.query}
        )
    
    return {
        "query": request.query,
        "answer": answer,
        "sources": [format_source(r) for r in search_results],
        "answer_refused": False,
        "search_time_ms": int((time.time() - start_time) * 1000)
    }
```

**キャッシュの活用:**

```python
async def get_user_accessible_departments_cached(user: User) -> list[str]:
    """
    ユーザーのアクセス可能部署をキャッシュ付きで取得
    TTL: 5分（組織変更は即座に反映されなくてもOK）
    """
    cache_key = f"accessible_depts:{user.id}"
    
    # キャッシュから取得
    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached)
    
    # キャッシュミス → 計算
    user_depts = await UserDepartment.filter(
        user_id=user.id,
        ended_at=None
    ).all()
    
    accessible = await compute_accessible_departments(user, user_depts)
    
    # キャッシュに保存（TTL: 5分）
    await redis.setex(cache_key, 300, json.dumps(accessible))
    
    return accessible
```

---

## 5.5.6 組織図システムとの連携仕様【v10.1.2追加】

### 5.5.6.1 概要

組織図システム（カズさんが管理）とソウルくんは、以下の方法でデータ連携を行う。

```
┌─────────────────────┐         ┌─────────────────────┐
│   組織図システム      │         │     ソウルくん       │
│  （LocalStorage）    │         │    （Cloud SQL）     │
│                     │         │                     │
│  ・部署マスタ        │ ──────→ │  ・departments      │
│  ・役職マスタ        │   API   │  ・roles           │
│  ・社員マスタ        │         │  ・users           │
│                     │         │  ・user_departments │
└─────────────────────┘         └─────────────────────┘
```

### 5.5.6.2 組織図システムのデータ構造（LocalStorage）

**ストレージキー：** `soulsyncs_org_chart_v2`

```javascript
// LocalStorageのデータ構造
interface OrgChartData {
  version: string;           // 'v2.0'
  lastUpdated: string;       // ISO8601形式
  lastSynced: string | null; // 最後に同期した日時

  organization: {
    id: string;              // 'org_soulsyncs'
    name: string;            // 'ソウルシンクス'
  };

  // 部署データ
  departments: Array<{
    id: string;              // 'dept_honsha'
    name: string;            // '本社'
    code: string;            // 'HQ'
    parentId: string | null; // 親部署ID（ルートはnull）
    level: number;           // 階層レベル
    displayOrder: number;    // 表示順
    isActive: boolean;       // 有効フラグ
  }>;

  // 役職データ（★v10.1.2で追加）
  roles: Array<{
    id: string;              // 'role_ceo'
    name: string;            // 'CEO'
    level: number;           // 役職レベル（1が最上位）
    description: string;     // '最高経営責任者'
  }>;

  // 社員データ
  employees: Array<{
    id: string;              // 'user_kazu'
    name: string;            // '菊地雅克'
    email: string;           // 'kazu@soulsyncs.jp'
    departmentId: string;    // 'dept_honsha'
    roleId: string;          // 'role_ceo'（★v10.1.2で追加）
    isPrimary: boolean;      // true
    startDate: string;       // '2018-01-01'
    endDate: string | null;  // null（現職）
  }>;
}
```

### 5.5.6.3 カズさんが実装すべき内容

**1. 役職マスタ管理UI**

```html
<!-- 組織図システムに追加するUI -->
<div class="role-management">
  <h3>役職マスタ</h3>
  <button onclick="addRole()">役職を追加</button>

  <table>
    <thead>
      <tr>
        <th>役職名</th>
        <th>レベル</th>
        <th>説明</th>
        <th>操作</th>
      </tr>
    </thead>
    <tbody id="rolesList">
      <!-- 動的に生成 -->
    </tbody>
  </table>
</div>
```

**2. 社員への役職紐付けUI**

```html
<!-- 社員編集画面に役職選択を追加 -->
<div class="form-group">
  <label for="roleId">役職</label>
  <select name="roleId" id="roleId" required>
    <option value="">-- 選択してください --</option>
    <option value="role_ceo">CEO</option>
    <option value="role_bucho">部長</option>
    <option value="role_kacho">課長</option>
    <option value="role_member">社員</option>
  </select>
</div>
```

**3. 同期ボタンの実装**

```javascript
// 組織図システムに追加するJavaScript

const ORG_CHART_STORAGE_KEY = 'soulsyncs_org_chart_v2';
const SOULKUN_API_BASE = 'https://api.soulsyncs.jp/v1';

/**
 * ソウルくんへの同期を実行
 */
async function syncToSoulKun() {
  // LocalStorageからデータ取得
  const orgChartData = JSON.parse(
    localStorage.getItem(ORG_CHART_STORAGE_KEY)
  );

  if (!orgChartData) {
    showError('組織図データがありません');
    return;
  }

  // APIトークンを取得
  const apiToken = localStorage.getItem('soulsyncs_api_token');
  if (!apiToken) {
    showError('APIトークンが設定されていません');
    return;
  }

  try {
    showLoading('同期中...');

    // 同期API呼び出し
    const response = await fetch(`${SOULKUN_API_BASE}/org-chart/sync`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${apiToken}`
      },
      body: JSON.stringify({
        organization_id: orgChartData.organization.id,
        source: 'org_chart_system',
        sync_type: 'full',
        departments: orgChartData.departments,
        roles: orgChartData.roles,
        employees: orgChartData.employees,
        options: {
          include_inactive_users: false,
          include_archived_departments: false,
          dry_run: false
        }
      })
    });

    const result = await response.json();

    if (result.status === 'success') {
      // 成功
      const summary = result.summary;
      showSuccess(
        `同期完了！\n` +
        `部署: 追加${summary.departments.added} / 更新${summary.departments.updated}\n` +
        `役職: 追加${summary.roles.added} / 更新${summary.roles.updated}\n` +
        `社員: 追加${summary.users.added} / 更新${summary.users.updated}`
      );

      // 最終同期日時を更新
      orgChartData.lastSynced = new Date().toISOString();
      localStorage.setItem(ORG_CHART_STORAGE_KEY, JSON.stringify(orgChartData));

    } else {
      // 失敗
      showError(`同期失敗: ${result.error.message}`);

      // 詳細ログへのリンクを表示
      if (result.sync_log_url) {
        console.log('詳細ログ:', result.sync_log_url);
      }
    }

  } catch (error) {
    showError(`通信エラー: ${error.message}`);
  } finally {
    hideLoading();
  }
}

// UIヘルパー関数
function showLoading(message) {
  document.getElementById('loadingOverlay').style.display = 'flex';
  document.getElementById('loadingMessage').textContent = message;
}

function hideLoading() {
  document.getElementById('loadingOverlay').style.display = 'none';
}

function showSuccess(message) {
  alert(message); // 本番ではトーストなどに置き換え
}

function showError(message) {
  alert('エラー: ' + message); // 本番ではトーストなどに置き換え
}
```

**4. 同期ボタンHTML**

```html
<!-- 組織図システムのヘッダーに追加 -->
<div class="sync-section">
  <button onclick="syncToSoulKun()" class="sync-button">
    <span class="icon">🔄</span>
    ソウルくんに同期
  </button>
  <span id="lastSyncedText" class="sync-status">
    <!-- 最終同期日時を表示 -->
  </span>
</div>

<!-- ローディングオーバーレイ -->
<div id="loadingOverlay" class="loading-overlay" style="display: none;">
  <div class="loading-content">
    <div class="spinner"></div>
    <p id="loadingMessage">同期中...</p>
  </div>
</div>
```

### 5.5.6.4 APIトークンの設定

組織図システムからソウルくんAPIを呼び出すには、APIトークンが必要。

**トークン取得手順：**

1. ソウルくん管理画面にログイン
2. 設定 → API設定 → トークン生成
3. スコープ：`org-chart:sync` を選択
4. トークンをコピー

**トークン設定（組織図システム側）：**

```javascript
// 初回のみ実行
localStorage.setItem('soulsyncs_api_token', 'sk-xxxxx...');
```

または設定画面を用意：

```html
<div class="api-settings">
  <h3>ソウルくんAPI設定</h3>
  <div class="form-group">
    <label>APIトークン</label>
    <input type="password" id="apiToken" placeholder="sk-xxxxx...">
    <button onclick="saveApiToken()">保存</button>
  </div>
</div>

<script>
function saveApiToken() {
  const token = document.getElementById('apiToken').value;
  localStorage.setItem('soulsyncs_api_token', token);
  showSuccess('APIトークンを保存しました');
}
</script>
```

---

## 5.5.7 タスク期限超過API【v10.1.3追加】【v10.1.4ページネーション追加】

### ■ GET /tasks/overdue

**目的:** 期限超過したタスク一覧を取得（リマインド送信用）

**認証:** API Key（Cloud Scheduler用）

**リクエスト:**

```http
GET /api/v1/tasks/overdue?organization_id=org_soulsyncs&grace_days=0&limit=100&offset=0
Authorization: Bearer {API_KEY}
```

**クエリパラメータ:**

| パラメータ | 型 | 必須 | 説明 | デフォルト値 | 最大値 |
|-----------|---|------|------|-------------|--------|
| organization_id | string | ✅ | 組織ID | - | - |
| grace_days | integer | ❌ | 猶予日数（期限からN日以内は除外） | 0 | - |
| **limit** | **integer** | ❌ | **取得件数【v10.1.4追加】** | **100** | **1000** |
| **offset** | **integer** | ❌ | **オフセット【v10.1.4追加】** | **0** | - |

**ページネーションの仕様【v10.1.4追加】:**

- **limit**: 1回のリクエストで取得する件数（デフォルト: 100、最大: 1000）
- **offset**: スキップする件数（デフォルト: 0）
- **次のページ**: `offset = current_offset + limit`
- **1000件超えの対応**: offsetを使って複数回リクエスト

**レスポンス（成功時）:**

```json
{
  "overdue_tasks": [
    {
      "task_id": "task_12345",
      "title": "Re:nk新規案件ヒアリング資料作成",
      "description": "新規クライアントへの提案資料を作成",
      "due_date": "2026-01-15",
      "days_overdue": 2,
      "priority": "high",
      "status": "in_progress",
      "assigned_to": {
        "user_id": "user_tanaka",
        "name": "田中太郎",
        "email": "tanaka@soulsyncs.jp"
      },
      "notification_room_id": "123456789",
      "created_by": {
        "user_id": "user_kazu",
        "name": "菊地雅克"
      },
      "created_at": "2026-01-10T09:00:00Z"
    },
    {
      "task_id": "task_67890",
      "title": "月次報告書作成",
      "description": null,
      "due_date": "2026-01-16",
      "days_overdue": 1,
      "priority": "medium",
      "status": "pending",
      "assigned_to": {
        "user_id": "user_suzuki",
        "name": "鈴木花子",
        "email": "suzuki@soulsyncs.jp"
      },
      "notification_room_id": null,
      "created_by": {
        "user_id": "user_kazu",
        "name": "菊地雅克"
      },
      "created_at": "2026-01-12T14:30:00Z"
    }
  ],
  "total_count": 2,
  "checked_at": "2026-01-17T09:00:00Z",
  "pagination": {
    "current_limit": 100,
    "current_offset": 0,
    "has_more": false,
    "next_offset": null
  }
}
```

**レスポンスフィールド（ページネーション）【v10.1.4追加】:**

| フィールド | 型 | 説明 |
|-----------|---|------|
| pagination.current_limit | integer | 今回のリクエストのlimit値 |
| pagination.current_offset | integer | 今回のリクエストのoffset値 |
| pagination.has_more | boolean | 次のページがあるか（true = ある、false = ない） |
| pagination.next_offset | integer\|null | 次のoffset値（has_more = false の場合は null） |

**ページネーション使用例:**

```python
# ページ1: 最初の100件
response = requests.get('/api/v1/tasks/overdue', params={
    'organization_id': 'org_soulsyncs',
    'grace_days': 0,
    'limit': 100,
    'offset': 0
})
# total_count = 250, has_more = true, next_offset = 100

# ページ2: 次の100件
response = requests.get('/api/v1/tasks/overdue', params={
    'organization_id': 'org_soulsyncs',
    'grace_days': 0,
    'limit': 100,
    'offset': 100
})
# has_more = true, next_offset = 200

# ページ3: 最後の50件
response = requests.get('/api/v1/tasks/overdue', params={
    'organization_id': 'org_soulsyncs',
    'grace_days': 0,
    'limit': 100,
    'offset': 200
})
# has_more = false, next_offset = null
```

**レスポンス（エラー時）:**

```json
{
  "error": {
    "code": "INVALID_ORGANIZATION",
    "message": "指定された組織IDが見つかりません"
  }
}
```

**SQL実装例（ページネーション対応）【v10.1.4更新】【v10.1.5修正】:**

```sql
-- ページネーション対応版
-- v10.1.5修正: INTERVAL構文エラーを修正（アプリ側でcutoff_date計算）
WITH overdue_tasks_cte AS (
    SELECT 
        t.task_id,
        t.title,
        t.description,
        t.due_date,
        CURRENT_DATE - t.due_date AS days_overdue,
        t.priority,
        t.status,
        t.notification_room_id,
        u.user_id AS assigned_user_id,
        u.name AS assigned_user_name,
        u.email AS assigned_user_email,
        c.user_id AS created_by_user_id,
        c.name AS created_by_name,
        t.created_at,
        COUNT(*) OVER() AS total_count  -- 総件数を計算
    FROM tasks t
    INNER JOIN users u ON t.assigned_to = u.user_id
    INNER JOIN users c ON t.created_by = c.user_id
    WHERE 
        t.organization_id = $1
        AND t.due_date < $2  -- v10.1.5: cutoff_date（アプリ側で計算）
        AND t.status NOT IN ('completed', 'cancelled')
    ORDER BY t.due_date ASC, t.priority DESC
)
SELECT * FROM overdue_tasks_cte
LIMIT $3 OFFSET $4;  -- limit, offset
```

**Python実装例:**

```python
@router.get("/overdue")
async def get_overdue_tasks(
    organization_id: str,
    grace_days: int = 0,
    limit: int = 100,
    offset: int = 0,
    api_key: str = Depends(verify_api_key)
):
    # バリデーション
    if limit > 1000:
        raise HTTPException(status_code=400, detail="limit must be <= 1000")
    if limit < 1:
        raise HTTPException(status_code=400, detail="limit must be >= 1")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")
    
    # v10.1.5修正: cutoff_dateをアプリ側で計算
    from datetime import date, timedelta
    cutoff_date = date.today() - timedelta(days=grace_days)
    
    # クエリ実行
    results = await db.fetch_all(query, 
        organization_id,  # $1
        cutoff_date,      # $2（v10.1.5: アプリ側で計算）
        limit,            # $3
        offset            # $4
    )
    
    # total_countを取得
    total_count = results[0]["total_count"] if results else 0
    
    # ページネーション情報を計算
    has_more = (offset + limit) < total_count
    next_offset = (offset + limit) if has_more else None
    
    return {
        "overdue_tasks": [format_task(r) for r in results],
        "total_count": total_count,
        "checked_at": datetime.utcnow().isoformat(),
        "pagination": {
            "current_limit": limit,
            "current_offset": offset,
            "has_more": has_more,
            "next_offset": next_offset
        }
    }
```

**パフォーマンス要件:**

- **1000タスク検索**: < 1秒
- **10000タスク検索（ページネーション使用）**: < 3秒（1000件×10ページ）
- インデックス: `idx_tasks_org_due_status` を使用
- **メモリ使用量**: limit=100の場合、約10KB/リクエスト（1000件でも100KB以下）

**セキュリティ:**

- API Keyによる認証必須
- organizationIdの権限チェック
- Rate Limit: 100req/hour
- **limit最大値チェック**（1000件超えを防止）

**互換性:**

- **後方互換性**: limit/offsetを指定しない場合、デフォルト値（limit=100, offset=0）が適用される
- **既存コードへの影響**: ゼロ（既存のクライアントはそのまま動作）

---

# 第5.6章：セキュリティ設計【新設】

## 5.6.1 階層ベースのアクセス制御

### ■ アクセス制御の原則

| # | 原則 | 説明 |
|---|------|------|
| 1 | **動的権限計算** | 固定権限ではなく、組織階層から動的に計算 |
| 2 | **最小権限の原則** | デフォルトは「自部署のみ」 |
| 3 | **階層継承** | 上位部署は下位部署を見れる（デフォルト） |
| 4 | **横展開禁止** | 兄弟部署は見れない（デフォルト） |
| 5 | **監査ログ必須** | confidential以上は必ずログに記録 |

### ■ アクセスパターン

**パターン1: 部長 → 配下すべて**

```
営業部長（dept_sales）
  ├─ 東京営業課（dept_sales_tokyo） ✅ 見れる
  │   └─ 第一係（dept_sales_tokyo_team1） ✅ 見れる
  └─ 大阪営業課（dept_sales_osaka） ✅ 見れる
```

**パターン2: 課長 → 自課のみ**

```
東京営業課長（dept_sales_tokyo）
  ├─ 第一係（dept_sales_tokyo_team1） ✅ 見れる
  └─ 第二係（dept_sales_tokyo_team2） ✅ 見れる

大阪営業課（dept_sales_osaka） ❌ 見れない（兄弟部署）
```

**パターン3: 一般社員 → 自部署のみ**

```
東京営業課の一般社員
  └─ 東京営業課（dept_sales_tokyo） ✅ 見れる

営業部（dept_sales） ❌ 見れない（親部署）
第一係（dept_sales_tokyo_team1） ❌ 見れない（子部署）
大阪営業課（dept_sales_osaka） ❌ 見れない（兄弟部署）
```

**パターン4: 総務部 → 全部署横断**

```
総務部（can_view_sibling_departments = TRUE）
  ├─ 営業部 ✅ 見れる
  ├─ 開発部 ✅ 見れる
  └─ 管理部 ✅ 見れる
```

### ■ 実装コード

```python
async def compute_accessible_departments(
    user_id: UUID,
    organization_id: UUID,
    resource_type: str = 'document'
) -> List[UUID]:
    """
    ユーザーがアクセス可能な部署IDのリストを計算

    v10.1.2: UserDepartmentとUserRoleを別々に取得するよう修正

    Args:
        user_id: ユーザーID
        organization_id: 組織ID
        resource_type: リソースタイプ（document, knowledge, meeting など）

    Returns:
        アクセス可能な部署IDのリスト
    """

    # Step 1: ユーザーの所属部署を取得
    # ★修正：roleのselect_relatedを削除
    user_departments = await UserDepartment.filter(
        user_id=user_id,
        is_primary=True,
        valid_until__isnull=True  # 現在有効な所属のみ
    ).select_related('department').all()

    if not user_departments:
        return []

    # Step 2: ユーザーのロールを取得（★追加）
    user_roles = await UserRole.filter(
        user_id=user_id
    ).select_related('role').all()

    if not user_roles:
        # ロールがない場合はデフォルトで自部署のみ
        return [ud.department.id for ud in user_departments]

    accessible_dept_ids: Set[UUID] = set()

    # Step 3: 所属部署 × ロール の組み合わせでスコープを計算
    for ud in user_departments:
        for ur in user_roles:
            department = ud.department
            role = ur.role

            # Step 4: ロール×部署のスコープを取得
            scope = await DepartmentAccessScope.get_or_none(
                role_id=role.id,
                department_id=department.id,
                resource_type=resource_type
            )

            if not scope:
                # スコープ未定義の場合はデフォルト（self）
                scope_value = 'self'
            else:
                scope_value = scope.scope

            # Step 5: スコープに基づいてアクセス可能部署を計算
            if scope_value == 'all':
                # 全部署アクセス可能
                all_depts = await Department.filter(
                    organization_id=organization_id
                ).values_list('id', flat=True)
                accessible_dept_ids.update(all_depts)
                # 全部署なのでこれ以上計算不要
                return list(accessible_dept_ids)

            elif scope_value == 'descendants':
                # 自部署 + 全子孫（LTREE演算子使用）
                # ★修正：正しいLTREE演算子を使用
                descendants = await Department.filter(
                    organization_id=organization_id,
                    path__descendant_or_equal=department.path
                ).values_list('id', flat=True)
                accessible_dept_ids.update(descendants)

            elif scope_value == 'children':
                # 自部署 + 直下の子部署のみ
                accessible_dept_ids.add(department.id)
                children = await Department.filter(
                    parent_id=department.id
                ).values_list('id', flat=True)
                accessible_dept_ids.update(children)

            else:  # 'self'
                # 自部署のみ
                accessible_dept_ids.add(department.id)

    return list(accessible_dept_ids)


async def get_child_departments(
    dept: Department,
    max_depth: int = 99
) -> list[Department]:
    """
    指定した部署の配下すべてを取得（max_depthまで）
    """
    # department_hierarchies テーブルを使用（高速）
    children = await Department.filter(
        id__in=Subquery(
            DepartmentHierarchy.filter(
                ancestor_department_id=dept.id,
                depth__gt=0,  # 自分自身は除く
                depth__lte=max_depth
            ).values_list("descendant_department_id", flat=True)
        )
    ).all()
    
    return children


async def get_parent_departments(dept: Department) -> list[Department]:
    """指定した部署の親部署すべてを取得"""
    parents = await Department.filter(
        id__in=Subquery(
            DepartmentHierarchy.filter(
                descendant_department_id=dept.id,
                depth__gt=0  # 自分自身は除く
            ).values_list("ancestor_department_id", flat=True)
        )
    ).all()
    
    return parents
```

---

## 5.6.2 権限判定ロジック

### ■ can_access_document()

**完全版実装:**

```python
async def can_access_document(user: User, document: Document) -> tuple[bool, str]:
    """
    ドキュメントへのアクセス権限を判定
    
    Returns:
        (許可/拒否, 理由)
    """
    
    # 1. 組織が異なる場合は即拒否
    if user.organization_id != document.organization_id:
        return False, "different_organization"
    
    # 2. 機密区分による判定
    classification = document.classification
    
    # 2-1. public: 全員OK
    if classification == "public":
        return True, "public_document"
    
    # 2-2. internal: 社員ならOK
    if classification == "internal":
        return True, "internal_document"
    
    # 2-3. restricted: 経営陣のみ
    if classification == "restricted":
        if user.role == "admin":
            return True, "admin_user"
        else:
            return False, "insufficient_role"
    
    # 2-4. confidential: 部署ベースの判定
    if classification == "confidential":
        # ユーザーのアクセス可能部署を取得
        accessible_depts = await get_user_accessible_departments_cached(user)
        
        # ドキュメントに部署が設定されていない場合
        if not document.department_id:
            # 管理者のみOK
            if user.role == "admin":
                return True, "admin_user"
            else:
                return False, "no_department_set"
        
        # 部署が一致する場合
        if document.department_id in accessible_depts:
            return True, "department_match"
        
        # 特別権限（override）を確認
        user_dept_ids = await get_user_department_ids(user)
        scopes = await DepartmentAccessScope.filter(
            department_id__in=user_dept_ids
        ).all()
        
        for scope in scopes:
            if scope.override_confidential_access:
                return True, "override_confidential"
        
        # 上記すべてに該当しない場合は拒否
        return False, "department_mismatch"
    
    # 想定外の機密区分
    return False, "unknown_classification"
```

---

## 5.6.3 監査ログ設計

### ■ audit_logs テーブル（拡張版）

**v10.0での拡張:**

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
    
    -- 組織情報【v10.0追加】
    department_id UUID REFERENCES departments(id),  -- アクセスした部署
    classification VARCHAR(50),  -- 機密区分
    
    -- 詳細
    details JSONB,
    
    -- コンテキスト
    ip_address INET,
    user_agent TEXT,
    
    -- メタデータ
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    
    -- インデックス
    INDEX idx_audit_user ON audit_logs(user_id),
    INDEX idx_audit_resource ON audit_logs(resource_type, resource_id),
    INDEX idx_audit_action ON audit_logs(action),
    INDEX idx_audit_classification ON audit_logs(classification),  -- 【v10.0追加】
    INDEX idx_audit_created ON audit_logs(created_at DESC)
);
```

### ■ 監査ログの記録

```python
async def log_document_access(
    user: User,
    document: Document,
    action: str = "view"
):
    """ドキュメントアクセスを監査ログに記録"""
    
    # confidential以上のみログに記録
    if document.classification in ["confidential", "restricted"]:
        await AuditLog.create(
            organization_id=user.organization_id,
            user_id=user.id,
            action=action,
            resource_type="document",
            resource_id=document.id,
            resource_name=document.title,
            department_id=document.department_id,  # ★組織情報
            classification=document.classification,  # ★機密区分
            details={
                "document_title": document.title,
                "category": document.category,
                "accessed_at": datetime.now().isoformat()
            },
            ip_address=get_client_ip(),
            user_agent=get_user_agent()
        )
```

### ■ 監査レポート

```python
@app.get("/api/v1/admin/audit-report")
async def get_audit_report(
    start_date: date,
    end_date: date,
    classification: str = None,
    user: User = Depends(get_current_user)
):
    """監査レポート取得（管理者のみ）"""
    
    await authorize(user, "organization", "manage")
    
    query = AuditLog.filter(
        organization_id=user.organization_id,
        created_at__gte=start_date,
        created_at__lte=end_date
    )
    
    if classification:
        query = query.filter(classification=classification)
    
    logs = await query.all()
    
    # 集計
    summary = {
        "total_accesses": len(logs),
        "by_user": count_by_field(logs, "user_id"),
        "by_classification": count_by_field(logs, "classification"),
        "by_department": count_by_field(logs, "department_id")
    }
    
    return {
        "period": {"start": start_date, "end": end_date},
        "summary": summary,
        "logs": [format_audit_log(log) for log in logs]
    }
```

---


---

**[📁 目次に戻る](00_README.md)**
