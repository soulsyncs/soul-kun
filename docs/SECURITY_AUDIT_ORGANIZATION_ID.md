# organization_id フィルタ監査レポート

**監査日:** 2026-01-30
**監査者:** Claude Code
**目的:** 全SQLクエリの organization_id フィルタ有無を検証し、データ漏洩リスクを特定

---

## Document Contract（SoT宣言）

| 項目 | 内容 |
|------|------|
| **この文書の役割** | organization_id フィルタの監査結果と是正計画 |
| **書くこと** | 監査結果、リスク評価、是正タスク |
| **書かないこと** | 実装の詳細（→ソースコード）、RLSポリシー（→別文書） |
| **SoT（この文書が正）** | organization_id監査の結果と是正進捗 |
| **Owner** | Tech Lead（連絡先: #dev チャンネル） |
| **更新トリガー** | 是正完了時、新たな問題発見時 |

---

## エグゼクティブサマリー

| 領域 | 状態 | リスク |
|------|------|--------|
| **API層（FastAPI）** | ✅ 完全実装 | 低 |
| **Insights機能** | ✅ 完全実装 | 低 |
| **Cloud Functions（Legacy）** | 🔴 **重大な不備** | **高** |

**根本的な問題:** Legacy Cloud Functions の `system_config`、`excluded_rooms`、`chatwork_tasks` テーブルへのクエリに organization_id フィルタがない。

**現在のリスク:** Phase 3.5（単一テナント）では実害なし。Phase 4（マルチテナント）移行時に**データ漏洩リスク**が発生。

---

## 1. 監査結果詳細

### 1.1 安全な領域（✅ OK）

| モジュール | ファイル | 状態 |
|-----------|---------|------|
| Insights | proactive-monitor/lib/insights/*.py | 全クエリに organization_id あり |
| API | api/app/services/access_control.py | 全クエリに organization_id あり |
| API | api/app/api/v1/*.py | 全クエリに organization_id あり |
| Goal通知 | proactive-monitor/lib/goal_notification.py | organization_id あり |

### 1.2 危険な領域（🔴 CRITICAL）

| テーブル | 影響ファイル数 | 影響クエリ数 | リスク |
|---------|--------------|-------------|--------|
| **system_config** | 6 | 6 | 組織間設定混在 |
| **excluded_rooms** | 6 | 6 | 組織間ルーム混在 |
| **chatwork_tasks** | 6 | 11 | タスクデータ漏洩 |

---

## 2. 影響を受けるファイル一覧

### system_config / excluded_rooms（全6ファイル）

| # | ファイル | 行番号 |
|---|---------|--------|
| 1 | chatwork-webhook/main.py | 4995, 5001 |
| 2 | sync-chatwork-tasks/main.py | 7714, 7720 |
| 3 | remind-tasks/main.py | 5453, 5459 |
| 4 | check-reply-messages/main.py | 2779, 2785 |
| 5 | cleanup-old-data/main.py | 2284, 2290 |
| 6 | main.py（ルート） | 2539, 2545 |

### chatwork_tasks（主要な問題箇所）

| # | ファイル | 操作 | 行番号 |
|---|---------|------|--------|
| 1 | chatwork-webhook/main.py | SELECT/UPDATE | 5066, 5088 |
| 2 | sync-chatwork-tasks/main.py | SELECT/COUNT/UPDATE | 1255, 1324, 1331, 7787, 7863 |
| 3 | remind-tasks/main.py | SELECT | 5524 |
| 4 | check-reply-messages/main.py | SELECT | 2850 |
| 5 | cleanup-old-data/main.py | SELECT | 2355 |
| 6 | main.py（ルート） | SELECT | 2610 |

---

## 3. リスク評価

### 3.1 CLAUDE.md 違反

| 鉄則 | 内容 | 現状 |
|------|------|------|
| **#1** | 全テーブルにorganization_idを追加 | **違反**（3テーブルで未対応） |
| **#2** | RLSを実装 | 未実装（Phase 4で対応予定） |

### 3.2 リスクシナリオ

| ID | シナリオ | 発生条件 | 影響 |
|----|---------|---------|------|
| **DATA-001** | 他組織のタスクが見える | Phase 4移行後、task_id重複時 | 機密情報漏洩 |
| **DATA-002** | 他組織の設定が適用される | Phase 4移行後 | 誤動作 |
| **DATA-003** | タスク更新で他組織データを書き換え | Phase 4移行後 | データ破壊 |

---

## 4. 是正計画

### Phase 1: テーブルスキーマ修正（必須・Phase 4移行前）

```sql
-- system_config
ALTER TABLE system_config ADD COLUMN organization_id TEXT NOT NULL DEFAULT 'org_soulsyncs';
ALTER TABLE system_config DROP CONSTRAINT system_config_pkey;
ALTER TABLE system_config ADD PRIMARY KEY (organization_id, key);

-- excluded_rooms
ALTER TABLE excluded_rooms ADD COLUMN organization_id TEXT NOT NULL DEFAULT 'org_soulsyncs';
ALTER TABLE excluded_rooms DROP CONSTRAINT excluded_rooms_pkey;
ALTER TABLE excluded_rooms ADD PRIMARY KEY (organization_id, room_id);

-- chatwork_tasks（既にorganization_idがある可能性、要確認）
-- なければ追加
ALTER TABLE chatwork_tasks ADD COLUMN organization_id TEXT NOT NULL DEFAULT 'org_soulsyncs';
CREATE INDEX idx_chatwork_tasks_org ON chatwork_tasks(organization_id);
```

### Phase 2: クエリ修正（23箇所）

**対象:** 上記「影響を受けるファイル一覧」の全箇所

**修正パターン:**

```python
# Before
cursor.execute("SELECT value FROM system_config WHERE key = %s", (key,))

# After
cursor.execute("""
    SELECT value FROM system_config
    WHERE key = %s AND organization_id = %s
""", (key, ORGANIZATION_ID))
```

### Phase 3: テスト追加

```python
def test_organization_isolation():
    """異なる組織のデータが混在しないことを確認"""
    # 組織Aのデータを作成
    create_task(org_id="org_a", task_id="task_1")
    # 組織Bのコンテキストで取得を試みる
    result = get_task(org_id="org_b", task_id="task_1")
    # 取得できないことを確認
    assert result is None
```

---

## 5. 是正タスク一覧

| # | タスク | 優先度 | 状態 | 担当 |
|---|--------|--------|------|------|
| ORG-001 | system_configにorganization_idカラム追加 | 🔴 高 | 未着手 | - |
| ORG-002 | excluded_roomsにorganization_idカラム追加 | 🔴 高 | 未着手 | - |
| ORG-003 | chatwork_tasksのorganization_id有無確認 | 🔴 高 | 未着手 | - |
| ORG-004 | Cloud Functions全6ファイルのクエリ修正 | 🔴 高 | 未着手 | - |
| ORG-005 | マイグレーションスクリプト作成 | 🟡 中 | 未着手 | - |
| ORG-006 | 組織分離テストケース追加 | 🟡 中 | 未着手 | - |
| ORG-007 | RLSポリシー設計（別文書） | 🟡 中 | 進行中 | - |

---

## 6. 暫定対策（Phase 3.5）

現在は単一テナント（`org_soulsyncs`）のため、即時の修正は不要。ただし：

1. **新規クエリ追加時は必ず organization_id フィルタを含める**
2. **PRレビューでorganization_idチェックを必須化**
3. **Phase 4移行計画に本文書の是正タスクを含める**

---

## 7. 関連ドキュメント

| ドキュメント | 参照内容 |
|-------------|---------|
| CLAUDE.md セクション5 | 10の鉄則（#1: organization_id必須） |
| OPERATIONS_RUNBOOK.md セクション11 | organization_id管理 |
| Design Coverage Matrix | organization_id行 |

---

## 更新履歴

| 日付 | 変更内容 |
|------|---------|
| 2026-01-30 | 初版作成（全SQLクエリ監査完了） |

---

**このファイルについての質問は、Tech Leadに連絡してください。**
