# Phase 2 進化版: A3 ボトルネック検出 - 詳細設計書

**バージョン:** v1.0
**作成日:** 2026-01-24
**作成者:** Claude Code（経営参謀・SE・PM）
**ステータス:** 設計中

---

## Document Contract（SoT宣言）

| 項目 | 内容 |
|------|------|
| **この文書の役割** | Phase 2進化版 A3ボトルネック検出機能の詳細設計書 |
| **書くこと** | ボトルネック検出のアルゴリズム（期限超過/長期未完了/担当者集中）、bottleneck_alertsテーブル設計、BottleneckDetector実装設計、Cloud Function/Scheduler設計 |
| **書かないこと** | A1パターン検出（→06_phase2_a1_pattern_detection.md）、A2属人化検出（→07_phase2_a2_personalization_detection.md）、soulkun_insightsテーブルの詳細（→06_phase2_a1_pattern_detection.md） |
| **SoT（この文書が正）** | A3ボトルネック検出のパラメータ（OVERDUE_CRITICAL_DAYS等）、bottleneck_alertsテーブル設計、ボトルネックタイプ定義（overdue_task/stale_task/task_concentration/no_assignee）、リスクレベル判定条件 |
| **Owner** | Tech Lead |
| **更新トリガー** | 検出パラメータの変更、DBスキーマの変更、ボトルネックタイプの追加・変更 |

---

## 1. エグゼクティブサマリー

### 1.1 この設計書の目的

**A3 ボトルネック検出**は、Phase 2進化版「24機能」のA群（気づく能力）の第3弾として、**業務の滞留・遅延を自動検出し、組織のボトルネックを可視化する機能**です。

### 1.2 3行で要約

1. **何をするか**: タスクの滞留状況を分析し、期限超過・長期未完了・担当者集中を検出
2. **なぜ必要か**: 滞留タスク = 業務の遅延・リスク。早期発見で工数削減・トラブル防止
3. **どう作るか**: chatwork_tasks分析 → `bottleneck_alerts` に保存 → 日次レポートで通知

### 1.3 期待される効果

| 指標 | 現状 | 導入後 | 改善率 |
|------|------|--------|--------|
| 期限超過タスクの見落とし | 月5件（推定） | 0件 | **-100%** |
| 滞留タスクへの対応時間 | 発覚から3日 | 発覚から1日 | **-67%** |
| タスク集中の可視化 | なし | 自動検出 | **新規** |

---

## 2. 全体設計との整合性

### 2.1 Phase 2進化版における位置づけ

```
Phase 2 進化版（24機能）
├─ A. 気づく能力（4機能）
│   ├─ A1. パターン検出 ✅ 完了
│   ├─ A2. 属人化検出 ✅ 完了
│   ├─ ★ A3. ボトルネック検出 ← 本設計書のスコープ
│   └─ A4. 感情変化検出（将来）
├─ B. 覚える能力（4機能）
├─ C. 先読みする能力（4機能）
├─ D. つなぐ能力（3機能）
├─ E. 育てる能力（3機能）
├─ F. 自動化能力（3機能）
├─ G. 進化する能力（3機能）
└─ H. 守る能力（2機能）
```

### 2.2 既存Phaseとの連携

| Phase | 連携内容 |
|-------|---------|
| Phase 1 | chatwork_tasks - タスクデータの分析対象 |
| Phase 1-B | notification_logs - 通知の冪等性を共有 |
| Phase 2.5 | 目標達成支援 - 目標関連タスクのボトルネック検出 |
| Phase 3.5 | 組織階層 - 部署ごとのボトルネック分析 |

---

## 3. 機能設計

### 3.1 機能概要

```
┌─────────────────────────────────────────────────────────────┐
│                   A3 ボトルネック検出フロー                  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  【入力】                                                   │
│  chatwork_tasks テーブル（status = 'open'）                 │
│       ↓                                                     │
│  【処理1】期限超過タスクの検出                              │
│  - limit_time < NOW() かつ status = 'open'                  │
│  - 超過日数でリスクレベルを判定                             │
│       ↓                                                     │
│  【処理2】長期未完了タスクの検出                            │
│  - 作成から7日以上経過かつ status = 'open'                  │
│  - 期限なしでも長期滞留は検出                               │
│       ↓                                                     │
│  【処理3】担当者集中の検出                                  │
│  - 特定担当者に未完了タスクが10件以上集中                   │
│  - 組織平均の2倍以上の場合はアラート                        │
│       ↓                                                     │
│  【処理4】ボトルネックDB更新                                │
│  - bottleneck_alerts テーブルに記録                         │
│  - soulkun_insights に登録（critical/high）                 │
│       ↓                                                     │
│  【出力】                                                   │
│  日次レポートで管理者に通知                                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 検出パラメータ

| パラメータ | デフォルト値 | 説明 | 変更可能 |
|-----------|------------|------|---------|
| OVERDUE_CRITICAL_DAYS | 7 | 緊急レベルの期限超過日数 | ✅ |
| OVERDUE_HIGH_DAYS | 3 | 高リスクレベルの期限超過日数 | ✅ |
| OVERDUE_MEDIUM_DAYS | 1 | 中リスクレベルの期限超過日数 | ✅ |
| STALE_TASK_DAYS | 7 | 長期未完了と判定する日数 | ✅ |
| TASK_CONCENTRATION_THRESHOLD | 10 | タスク集中アラートの閾値 | ✅ |
| CONCENTRATION_RATIO_THRESHOLD | 2.0 | 平均の何倍で集中と判定 | ✅ |

### 3.3 ボトルネックタイプ

| タイプ | 説明 | 検出条件 |
|--------|------|----------|
| `overdue_task` | 期限超過タスク | limit_time < NOW() |
| `stale_task` | 長期未完了タスク | 作成から7日以上経過 |
| `task_concentration` | タスク集中 | 担当者に10件以上集中 |
| `no_assignee` | 担当者未設定 | assigned_to_account_id IS NULL |

### 3.4 リスクレベル判定

| リスクレベル | 条件 | 通知タイミング |
|-------------|------|---------------|
| `critical` | 期限7日超過 / タスク20件以上集中 | 即時通知 |
| `high` | 期限3日超過 / タスク15件以上集中 | 即時通知 |
| `medium` | 期限1日超過 / タスク10件以上集中 | 日次レポート |
| `low` | 長期未完了（7日以上） | 週次レポート |

---

## 4. データベース設計

### 4.1 テーブル一覧

| テーブル | 用途 | 新規/既存 |
|---------|------|----------|
| `bottleneck_alerts` | ボトルネック検出結果 | 新規 |
| `soulkun_insights` | ソウルくんの気づき（統合） | 既存（A1で作成済み） |
| `chatwork_tasks` | タスクデータ | 既存 |

### 4.2 bottleneck_alerts（ボトルネック検出結果）

```sql
-- ボトルネック検出結果【Phase 2進化版 A3】
CREATE TABLE bottleneck_alerts (
    -- 基本情報
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- 部署フィルタ（Phase 3.5準拠）
    department_id UUID REFERENCES departments(id) ON DELETE SET NULL,

    -- ボトルネックタイプ
    bottleneck_type VARCHAR(50) NOT NULL,  -- overdue_task, stale_task, task_concentration, no_assignee
    risk_level VARCHAR(20) NOT NULL,       -- critical, high, medium, low

    -- 対象情報
    target_type VARCHAR(50) NOT NULL,      -- task, user
    target_id VARCHAR(100) NOT NULL,       -- task_id または user_id
    target_name VARCHAR(255),              -- タスク名または担当者名

    -- 統計
    overdue_days INT,                      -- 期限超過日数（overdue_task用）
    task_count INT,                        -- タスク数（task_concentration用）
    stale_days INT,                        -- 滞留日数（stale_task用）

    -- 関連タスク
    related_task_ids TEXT[] DEFAULT '{}',  -- 関連するタスクIDリスト
    sample_tasks JSONB DEFAULT '[]',       -- サンプルタスク情報

    -- ステータス
    status VARCHAR(20) DEFAULT 'active',   -- active, resolved, dismissed
    first_detected_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_detected_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMPTZ,
    resolved_action TEXT,

    -- 機密区分
    classification VARCHAR(20) DEFAULT 'internal',

    -- 監査フィールド
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 制約
    UNIQUE(organization_id, bottleneck_type, target_type, target_id),
    CONSTRAINT check_bottleneck_type CHECK (
        bottleneck_type IN ('overdue_task', 'stale_task', 'task_concentration', 'no_assignee')
    ),
    CONSTRAINT check_risk_level CHECK (
        risk_level IN ('critical', 'high', 'medium', 'low')
    ),
    CONSTRAINT check_status CHECK (
        status IN ('active', 'resolved', 'dismissed')
    )
);

COMMENT ON TABLE bottleneck_alerts IS
'Phase 2進化版 A3: ボトルネック検出結果
- 期限超過、長期未完了、担当者集中を検出
- soulkun_insights と連携して通知';

-- インデックス
CREATE INDEX idx_bottleneck_alerts_org_type
    ON bottleneck_alerts(organization_id, bottleneck_type);

CREATE INDEX idx_bottleneck_alerts_org_level
    ON bottleneck_alerts(organization_id, risk_level);

CREATE INDEX idx_bottleneck_alerts_status
    ON bottleneck_alerts(organization_id, status)
    WHERE status = 'active';

CREATE INDEX idx_bottleneck_alerts_target
    ON bottleneck_alerts(organization_id, target_type, target_id);

CREATE INDEX idx_bottleneck_alerts_department
    ON bottleneck_alerts(organization_id, department_id)
    WHERE department_id IS NOT NULL;

-- updated_at 自動更新トリガー
CREATE TRIGGER trg_bottleneck_alerts_updated_at
    BEFORE UPDATE ON bottleneck_alerts
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

---

## 5. 実装設計

### 5.1 BottleneckDetector クラス

```python
class BottleneckDetector(BaseDetector):
    """
    ボトルネック検出器

    タスクの滞留・遅延・集中を検出し、業務のボトルネックを可視化

    検出項目:
    1. 期限超過タスク（overdue_task）
    2. 長期未完了タスク（stale_task）
    3. 担当者へのタスク集中（task_concentration）
    4. 担当者未設定タスク（no_assignee）
    """

    def __init__(
        self,
        conn: Connection,
        org_id: UUID,
        overdue_critical_days: int = 7,
        overdue_high_days: int = 3,
        overdue_medium_days: int = 1,
        stale_task_days: int = 7,
        task_concentration_threshold: int = 10,
    ):
        super().__init__(
            conn=conn,
            org_id=org_id,
            detector_type=SourceType.A3_BOTTLENECK,
            insight_type=InsightType.BOTTLENECK,
        )
        # パラメータ設定...

    async def detect(self) -> DetectionResult:
        """
        ボトルネックを検出

        Returns:
            DetectionResult: 検出結果
        """
        # 1. 期限超過タスクの検出
        overdue_alerts = await self._detect_overdue_tasks()

        # 2. 長期未完了タスクの検出
        stale_alerts = await self._detect_stale_tasks()

        # 3. 担当者集中の検出
        concentration_alerts = await self._detect_task_concentration()

        # 4. アラートをDBに保存
        saved_alerts = []
        for alert in overdue_alerts + stale_alerts + concentration_alerts:
            saved = await self._save_alert(alert)
            if saved:
                saved_alerts.append(saved)

        # 5. critical/high はInsightに登録
        insights_created = 0
        for alert in saved_alerts:
            if alert['risk_level'] in ('critical', 'high'):
                if not await self.insight_exists_for_source(alert['id']):
                    insight_data = self._create_insight_data(alert)
                    await self.save_insight(insight_data)
                    insights_created += 1

        return DetectionResult(
            success=True,
            detected_count=len(saved_alerts),
            insight_created=insights_created > 0,
            details={
                "overdue_tasks": len(overdue_alerts),
                "stale_tasks": len(stale_alerts),
                "concentration_alerts": len(concentration_alerts),
                "insights_created": insights_created,
            },
        )
```

### 5.2 期限超過タスク検出SQL

```sql
-- 期限超過タスクを検出
SELECT
    task_id,
    body,
    summary,
    limit_time,
    assigned_to_account_id,
    assigned_to_name,
    room_id,
    room_name,
    EXTRACT(DAY FROM (NOW() - limit_time)) as overdue_days
FROM chatwork_tasks
WHERE status = 'open'
  AND limit_time IS NOT NULL
  AND limit_time < NOW()
ORDER BY limit_time ASC;
```

### 5.3 担当者集中検出SQL

```sql
-- 担当者別の未完了タスク数を集計
SELECT
    assigned_to_account_id,
    assigned_to_name,
    COUNT(*) as task_count,
    ARRAY_AGG(task_id ORDER BY limit_time NULLS LAST) as task_ids
FROM chatwork_tasks
WHERE status = 'open'
  AND assigned_to_account_id IS NOT NULL
GROUP BY assigned_to_account_id, assigned_to_name
HAVING COUNT(*) >= :threshold
ORDER BY task_count DESC;
```

---

## 6. Cloud Function設計

### 6.1 エンドポイント

| 関数名 | URL | 説明 |
|--------|-----|------|
| `bottleneck-detection` | `/bottleneck-detection` | ボトルネック検出メイン |

### 6.2 リクエスト/レスポンス

**リクエスト:**
```json
{
    "dry_run": false,
    "org_id": "uuid"
}
```

**レスポンス:**
```json
{
    "success": true,
    "message": "5件のボトルネックを検出しました",
    "results": {
        "detected_count": 5,
        "insight_created": true,
        "details": {
            "overdue_tasks": 3,
            "stale_tasks": 1,
            "concentration_alerts": 1,
            "risk_levels": {
                "critical": 1,
                "high": 2,
                "medium": 2,
                "low": 0
            }
        }
    },
    "timestamp": "2026-01-24T10:00:00Z"
}
```

### 6.3 Cloud Scheduler設定

```yaml
# 日次実行（毎朝8:00 JST）
name: bottleneck-detection-daily
schedule: "0 8 * * *"
time_zone: "Asia/Tokyo"
http_target:
  uri: https://asia-northeast1-soulkun-production.cloudfunctions.net/bottleneck-detection
  http_method: POST
  body: '{"dry_run": false}'
```

---

## 7. 通知設計

### 7.1 通知タイプ

| notification_type | 説明 | 送信先 |
|-------------------|------|--------|
| `bottleneck_alert` | ボトルネック検出アラート | 管理者 / 担当者 |

### 7.2 通知メッセージ例

**期限超過タスク（critical）:**
```
[toall]

:warning: ボトルネック検出アラート

以下のタスクが期限を7日以上超過しています：

:x: [タスク名] - 担当: 山田さん
   期限: 2026-01-17 → 7日超過
   ルーム: 営業チーム

早急にご確認ください。

ソウルくん
```

**担当者集中（high）:**
```
:warning: タスク集中アラート

山田さんに未完了タスクが15件集中しています。

:point_right: 負荷分散をご検討ください
:point_right: 優先度の見直しをご検討ください

ソウルくん
```

---

## 8. 実装スケジュール

| ステップ | 内容 | 完了基準 |
|---------|------|---------|
| 1 | DBマイグレーション実行 | bottleneck_alerts テーブル作成 |
| 2 | BottleneckDetector 実装 | lib/detection/bottleneck_detector.py |
| 3 | Cloud Function 追加 | pattern-detection/main.py |
| 4 | デプロイ・テスト | curl テスト成功 |
| 5 | Cloud Scheduler 設定 | 日次実行設定 |

---

## 9. テスト計画

### 9.1 ユニットテスト

- [ ] 期限超過タスク検出ロジック
- [ ] 長期未完了タスク検出ロジック
- [ ] 担当者集中検出ロジック
- [ ] リスクレベル判定ロジック

### 9.2 結合テスト

- [ ] Cloud Function デプロイ成功
- [ ] dry_run モードテスト
- [ ] 実検出テスト（本番データ）
- [ ] Cloud Scheduler 連携テスト

---

## 付録: 参照ドキュメント

- [06_phase2_a1_pattern_detection.md](./06_phase2_a1_pattern_detection.md) - A1パターン検出
- [07_phase2_a2_personalization_detection.md](./07_phase2_a2_personalization_detection.md) - A2属人化検出
- [CLAUDE.md](../CLAUDE.md) - プロジェクト規約
