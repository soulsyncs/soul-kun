# Phase 3.5: 組織階層設計書

---

## Document Contract（SoT宣言）

| 項目 | 内容 |
|------|------|
| **この文書の役割** | Phase 3.5（組織階層機能）の実装手順書 |
| **書くこと** | マイグレーション手順、週次スケジュール、LTREE設計の使い方 |
| **書かないこと** | 組織理論の詳細（→11章）、フロントエンド設計（→12章）、**テーブル定義（→03章）** |
| **SoT（この文書が正）** | マイグレーション手順、実装スケジュール |
| **参照のみ（SoTは別）** | departments/user_departments等のテーブル定義 → [03_database_design.md](03_database_design.md) セクション5.2.5 |
| **Owner** | Tech Lead |
| **更新トリガー** | 組織階層機能の仕様変更時 |

> **⚠️ 重要（v10.55追加）**: テーブル定義は **03_database_design.md がSoT（唯一の正）** です。
> 本文書ではテーブル定義の詳細を記載せず、03章への参照のみとします。
> テーブル定義を変更する場合は、必ず03章を更新してください。

---

## 12.1 Phase 3.5の実装手順

### ■ Week 7: データモデル構築（20時間）

**Day 1-2: テーブル作成（10時間）**

> **テーブル定義のSoT:** [03_database_design.md](03_database_design.md) セクション5.2.5
>
> 以下のテーブルを作成します。定義の詳細は03章を参照してください。
>
> | テーブル | 目的 | 定義の場所 |
> |---------|------|-----------|
> | departments | 部署マスタ | 03章 5.2.5 |
> | user_departments | ユーザーの所属部署 | 03章 5.2.5 |
> | department_access_scopes | 部署ごとの権限スコープ | 03章 5.2.5 |
> | department_hierarchies | 部署階層の事前計算 | 03章 5.2.5 |
> | org_chart_sync_logs | 組織図同期ログ | 03章 5.2.5 |

```bash
# 1. マイグレーションファイル作成
$ python manage.py makemigration create_organization_tables

# 2. マイグレーション実装
# migrations/v10_0_001_create_organization_tables.py
#
# ※ CREATE TABLE文は 03_database_design.md セクション5.2.5 を参照
# ※ 以下はマイグレーション実行の流れのみ記載
```

```python
async def upgrade():
    """組織階層テーブルを作成

    テーブル定義のSoT: docs/03_database_design.md セクション5.2.5
    ※ CREATE TABLE文は上記設計書からコピーすること
    """

    # 1. LTREEエクステンションを有効化
    await conn.execute("CREATE EXTENSION IF NOT EXISTS ltree;")

    # 2. 以下のテーブルを03章の定義に従って作成:
    #    - departments
    #    - user_departments
    #    - department_access_scopes
    #    - department_hierarchies
    #    - org_chart_sync_logs
    #
    # ※ 詳細なCREATE TABLE文は 03_database_design.md を参照

    # 実装時は03章のDDLをそのままコピーして使用すること
    pass
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

## 13.5 ファイル誤配置検知システム【v10.55追加】

### ■ 概要

機密ファイルが誤って公開フォルダに配置された場合を自動検知し、管理者にアラートを送信するシステムです。

**検知対象:**
- Google Driveの共有設定が不適切なファイル
- 機密区分と配置場所の不整合
- 権限設定の変更によるセキュリティ低下

### ■ 誤配置パターンと検知ルール

| # | パターン | 説明 | 重大度 | 対応 |
|---|---------|------|-------|------|
| 1 | **機密 → 公開フォルダ** | confidential/restrictedファイルが「全員に公開」設定 | Critical | 即時アラート + 自動権限復旧 |
| 2 | **部門限定 → 全社公開** | 部門限定ファイルが全社フォルダに配置 | High | 即時アラート |
| 3 | **社内 → 外部共有** | internalファイルに外部メールアドレスが追加 | Critical | 即時アラート + 共有解除 |
| 4 | **権限拡大** | ファイル権限が拡大された | Medium | 日次レポート |
| 5 | **未分類ファイル** | 機密区分が設定されていないファイル | Low | 週次レポート |

### ■ 検知ジョブ設計

```python
# lib/knowledge/misplacement_detector.py

from datetime import datetime, timedelta
from typing import List, Optional
from dataclasses import dataclass
from enum import Enum

class Severity(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

@dataclass
class MisplacementAlert:
    file_id: str
    file_name: str
    owner_id: str
    organization_id: str
    pattern: str
    severity: Severity
    current_location: str
    expected_location: str
    detected_at: datetime
    auto_remediated: bool = False

async def detect_misplacements(organization_id: str) -> List[MisplacementAlert]:
    """ファイル誤配置を検知する（5分ごとに実行）"""

    alerts = []

    # 1. Google Drive APIで変更されたファイルを取得
    modified_files = await get_recently_modified_files(
        organization_id=organization_id,
        since=datetime.now() - timedelta(minutes=5)
    )

    for file in modified_files:
        # 2. 機密区分を取得
        classification = await get_file_classification(file.id)

        # 3. 現在の共有設定を取得
        sharing_settings = await get_sharing_settings(file.id)

        # 4. 誤配置パターンをチェック
        alert = check_misplacement_patterns(
            file=file,
            classification=classification,
            sharing=sharing_settings
        )

        if alert:
            alerts.append(alert)

            # 5. Critical/Highは即時対応
            if alert.severity in [Severity.CRITICAL, Severity.HIGH]:
                await send_immediate_alert(alert)

                # 6. 自動修復（Criticalのみ）
                if alert.severity == Severity.CRITICAL:
                    await auto_remediate(alert)

    return alerts


def check_misplacement_patterns(
    file: DriveFile,
    classification: str,
    sharing: SharingSettings
) -> Optional[MisplacementAlert]:
    """誤配置パターンをチェック"""

    # パターン1: 機密ファイルが公開設定
    if classification in ["confidential", "restricted"]:
        if sharing.anyone_can_access:
            return MisplacementAlert(
                file_id=file.id,
                file_name=file.name,
                owner_id=file.owner_id,
                organization_id=file.organization_id,
                pattern="confidential_in_public",
                severity=Severity.CRITICAL,
                current_location=sharing.folder_path,
                expected_location="機密フォルダ",
                detected_at=datetime.now()
            )

    # パターン2: 部門限定が全社公開
    if classification == "confidential" and file.department_id:
        if sharing.is_organization_wide:
            return MisplacementAlert(
                file_id=file.id,
                file_name=file.name,
                owner_id=file.owner_id,
                organization_id=file.organization_id,
                pattern="department_in_company_wide",
                severity=Severity.HIGH,
                current_location=sharing.folder_path,
                expected_location=f"部門フォルダ: {file.department_id}",
                detected_at=datetime.now()
            )

    # パターン3: 社内ファイルに外部共有
    if classification == "internal":
        external_emails = [
            email for email in sharing.shared_emails
            if not email.endswith(f"@{file.organization_domain}")
        ]
        if external_emails:
            return MisplacementAlert(
                file_id=file.id,
                file_name=file.name,
                owner_id=file.owner_id,
                organization_id=file.organization_id,
                pattern="internal_shared_externally",
                severity=Severity.CRITICAL,
                current_location=f"外部共有先: {external_emails}",
                expected_location="社内のみ",
                detected_at=datetime.now()
            )

    return None
```

### ■ 自動修復（Auto-Remediation）

```python
# lib/knowledge/auto_remediation.py

async def auto_remediate(alert: MisplacementAlert) -> bool:
    """重大な誤配置を自動修復する"""

    try:
        if alert.pattern == "confidential_in_public":
            # 公開設定を解除
            await revoke_public_access(alert.file_id)

            # 所有者に通知
            await notify_owner(
                owner_id=alert.owner_id,
                message=f"機密ファイル「{alert.file_name}」の公開設定を自動で解除しました。"
            )

        elif alert.pattern == "internal_shared_externally":
            # 外部共有を解除
            await revoke_external_shares(alert.file_id)

            await notify_owner(
                owner_id=alert.owner_id,
                message=f"社内ファイル「{alert.file_name}」の外部共有を自動で解除しました。"
            )

        # 監査ログに記録
        await audit_log(
            action="auto_remediation",
            resource_type="file",
            resource_id=alert.file_id,
            details={
                "pattern": alert.pattern,
                "severity": alert.severity.value,
                "remediation": "access_revoked"
            }
        )

        return True

    except Exception as e:
        # 修復失敗時は管理者にエスカレーション
        await escalate_to_admin(alert, error=str(e))
        return False
```

### ■ アラート通知設計

| 重大度 | 通知先 | 通知方法 | タイミング |
|-------|--------|---------|----------|
| **Critical** | 管理者 + ファイル所有者 | ChatWork即時通知 + メール | 検知から1分以内 |
| **High** | 管理者 + ファイル所有者 | ChatWork即時通知 | 検知から5分以内 |
| **Medium** | 管理者 | 日次サマリーレポート | 毎日9:00 |
| **Low** | 管理者 | 週次レポート | 毎週月曜9:00 |

```python
# lib/knowledge/alert_notifier.py

ALERT_TEMPLATES = {
    "confidential_in_public": """
🚨 【緊急】機密ファイルが公開設定になっています

■ ファイル名: {file_name}
■ 所有者: {owner_name}
■ 検知日時: {detected_at}
■ 対応状況: {remediation_status}

自動で公開設定を解除しました。
詳細を確認し、意図的な場合は管理者に連絡してください。
""",

    "internal_shared_externally": """
🚨 【緊急】社内ファイルが外部共有されています

■ ファイル名: {file_name}
■ 共有先: {external_emails}
■ 検知日時: {detected_at}
■ 対応状況: {remediation_status}

自動で外部共有を解除しました。
意図的な共有の場合は、適切な承認プロセスを経てください。
""",

    "department_in_company_wide": """
⚠️ 【警告】部門限定ファイルが全社公開になっています

■ ファイル名: {file_name}
■ 本来の部門: {expected_department}
■ 現在の設定: 全社公開
■ 検知日時: {detected_at}

確認の上、適切な権限設定に変更してください。
"""
}

async def send_immediate_alert(alert: MisplacementAlert):
    """即時アラートを送信"""

    template = ALERT_TEMPLATES.get(alert.pattern)
    if not template:
        template = "ファイル誤配置を検知しました: {file_name}"

    message = template.format(
        file_name=alert.file_name,
        owner_name=await get_user_name(alert.owner_id),
        detected_at=alert.detected_at.strftime("%Y-%m-%d %H:%M"),
        remediation_status="自動修復済み" if alert.auto_remediated else "要対応",
        external_emails=getattr(alert, 'external_emails', 'N/A'),
        expected_department=alert.expected_location
    )

    # ChatWorkに送信
    await send_chatwork_message(
        room_id=await get_admin_room_id(alert.organization_id),
        message=message
    )

    # メールも送信（Criticalのみ）
    if alert.severity == Severity.CRITICAL:
        await send_email(
            to=await get_admin_email(alert.organization_id),
            subject=f"【緊急】ファイル誤配置検知: {alert.file_name}",
            body=message
        )
```

### ■ 検知ジョブのスケジュール

| ジョブ | 実行間隔 | 処理内容 |
|-------|---------|---------|
| `detect_misplacements` | 5分ごと | 直近5分の変更をチェック |
| `generate_daily_report` | 毎日9:00 | Medium以下のサマリー |
| `generate_weekly_report` | 毎週月曜9:00 | 全体統計とトレンド |
| `cleanup_old_alerts` | 毎日3:00 | 90日超過のアラートを削除 |

```python
# Cloud Scheduler設定（cloudbuild.yaml参照）

MISPLACEMENT_JOBS = [
    {
        "name": "detect-misplacements",
        "schedule": "*/5 * * * *",  # 5分ごと
        "handler": "detect_misplacements",
        "timeout": "120s"
    },
    {
        "name": "daily-misplacement-report",
        "schedule": "0 9 * * *",  # 毎日9:00
        "handler": "generate_daily_report",
        "timeout": "300s"
    },
    {
        "name": "weekly-misplacement-report",
        "schedule": "0 9 * * 1",  # 毎週月曜9:00
        "handler": "generate_weekly_report",
        "timeout": "600s"
    }
]
```

### ■ 監査ログ設計

| イベント | 記録内容 | 保持期間 |
|---------|---------|---------|
| 誤配置検知 | file_id, pattern, severity, detected_at | 1年 |
| 自動修復実行 | file_id, action, result, executed_at | 1年 |
| アラート送信 | alert_id, recipients, channel, sent_at | 1年 |
| 手動対応完了 | alert_id, resolved_by, resolution, resolved_at | 1年 |

> **注意**: 監査ログにはファイル名やメールアドレスなどのPIIを含めず、IDのみを記録します。

---


---

**[📁 目次に戻る](00_README.md)**
