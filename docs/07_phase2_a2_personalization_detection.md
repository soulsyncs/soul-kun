# Phase 2 進化版: A2 属人化検出 - 詳細設計書

**バージョン:** v1.0
**作成日:** 2026-01-24
**作成者:** Claude Code（経営参謀・SE・PM）
**ステータス:** 実装中

---

## 1. エグゼクティブサマリー

### 1.1 この設計書の目的

**A2 属人化検出**は、Phase 2進化版「24機能」の2番目の実装として、**特定の人にしか回答できない質問・業務を検出し、BCP（事業継続）リスクを可視化する機能**です。

### 1.2 3行で要約

1. **何をするか**: 「〇〇さんにしか聞けない」状態を自動検出し、管理者に報告
2. **なぜ必要か**: 属人化は会社のリスク。誰かがいなくても止まらない仕組みが必要
3. **どう作るか**: 会話ログを分析 → 回答者の偏りを検出 → `soulkun_insights` に登録

### 1.3 期待される効果

| 指標 | 現状 | 導入後 | 改善率 |
|------|------|--------|--------|
| 属人化リスクの把握 | 感覚的 | 定量的 | **可視化** |
| ナレッジ移転の優先度 | 不明 | 自動提案 | **+∞** |
| BCP対策の実行 | 後手 | 先手 | **新規** |

---

## 2. 全体設計との整合性

### 2.1 Phase 2進化版における位置づけ

```
Phase 2 進化版（24機能）
├─ A. 気づく能力（4機能）
│   ├─ ✅ A1. パターン検出（完了）
│   ├─ ★ A2. 属人化検出 ← 本設計書のスコープ
│   ├─ A3. ボトルネック検出（将来）
│   └─ A4. 感情変化検出（将来）
├─ B. 覚える能力（4機能）
...
```

### 2.2 A1パターン検出との違い

| 項目 | A1 パターン検出 | A2 属人化検出 |
|------|----------------|---------------|
| 検出対象 | 同じ質問の繰り返し | 回答者の偏り |
| 分析軸 | 質問内容 | 回答者（人） |
| リスク | 情報周知不足 | BCP（事業継続）リスク |
| 推奨アクション | ナレッジ化・全社周知 | ナレッジ移転・文書化 |

---

## 3. 機能設計

### 3.1 機能概要

```
┌─────────────────────────────────────────────────────────────┐
│                   A2 属人化検出フロー                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  【入力】                                                   │
│  ソウルくんの会話ログ（質問と回答）                         │
│       ↓                                                     │
│  【処理1】回答者の分析                                      │
│  - 「誰が」「何に」回答しているか集計                       │
│  - カテゴリ別・トピック別に分類                             │
│       ↓                                                     │
│  【処理2】偏り検出                                          │
│  - 特定カテゴリで1人が80%以上回答 → 属人化リスク            │
│  - 特定トピックで1人だけが回答 → 高リスク                   │
│       ↓                                                     │
│  【処理3】リスク評価                                        │
│  - 回答回数、期間、代替者の有無でスコアリング               │
│       ↓                                                     │
│  【処理4】soulkun_insights登録                              │
│  - insight_type: 'personalization_risk'                     │
│       ↓                                                     │
│  【出力】                                                   │
│  週次レポートで管理者に通知                                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 検出パラメータ

| パラメータ | デフォルト値 | 説明 | 変更可能 |
|-----------|------------|------|---------|
| PERSONALIZATION_THRESHOLD | 0.8 | 属人化判定の偏り閾値（80%） | ✅ |
| MIN_RESPONSES_FOR_DETECTION | 5 | 検出に必要な最小回答数 | ✅ |
| ANALYSIS_WINDOW_DAYS | 30 | 分析対象期間（日） | ✅ |
| HIGH_RISK_EXCLUSIVE_DAYS | 14 | 独占回答が続いた日数（高リスク判定） | ✅ |

### 3.3 属人化リスクレベル

| リスクレベル | 条件 | アクション |
|-------------|------|-----------|
| `critical` | 1人だけが回答 + 代替者なし + 30日以上継続 | 即時通知・緊急対応 |
| `high` | 1人が80%以上回答 + 14日以上継続 | 週次レポートで強調 |
| `medium` | 1人が60%以上回答 + 7日以上継続 | 週次レポートに記載 |
| `low` | 偏りの傾向あり | 監視継続 |

---

## 4. データベース設計

### 4.1 新規テーブル: personalization_risks

```sql
-- 属人化リスクの記録【Phase 2進化版 A2】
CREATE TABLE personalization_risks (
    -- 基本情報
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- 部署フィルタ（Phase 3.5準拠）
    department_id UUID REFERENCES departments(id) ON DELETE SET NULL,

    -- 属人化対象
    expert_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    topic_category VARCHAR(50) NOT NULL,        -- 属人化しているトピックカテゴリ
    topic_keywords TEXT[] DEFAULT '{}',         -- 関連キーワード

    -- 統計
    total_responses INT DEFAULT 0,              -- 全回答数
    expert_responses INT DEFAULT 0,             -- エキスパートの回答数
    personalization_ratio DECIMAL(5,4),         -- 属人化率（0.0000-1.0000）
    first_detected_at TIMESTAMPTZ NOT NULL,
    last_detected_at TIMESTAMPTZ NOT NULL,
    consecutive_days INT DEFAULT 0,             -- 連続検出日数

    -- 代替者情報
    alternative_responders UUID[] DEFAULT '{}', -- 代替回答者のユーザーID
    has_alternative BOOLEAN DEFAULT false,      -- 代替者がいるか

    -- サンプルデータ
    sample_questions TEXT[] DEFAULT '{}',       -- サンプル質問（最大5件）
    sample_responses TEXT[] DEFAULT '{}',       -- サンプル回答（最大5件）

    -- ステータス
    risk_level VARCHAR(20) DEFAULT 'low',       -- critical, high, medium, low
    status VARCHAR(20) DEFAULT 'active',        -- active, mitigated, dismissed
    mitigated_at TIMESTAMPTZ,
    mitigation_action TEXT,                     -- 対応内容

    -- 機密区分
    classification VARCHAR(20) DEFAULT 'internal',

    -- 監査フィールド
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 制約
    UNIQUE(organization_id, expert_user_id, topic_category)
);

-- インデックス
CREATE INDEX idx_personalization_risks_org_level
    ON personalization_risks(organization_id, risk_level);
CREATE INDEX idx_personalization_risks_expert
    ON personalization_risks(organization_id, expert_user_id);
CREATE INDEX idx_personalization_risks_status
    ON personalization_risks(organization_id, status)
    WHERE status = 'active';
CREATE INDEX idx_personalization_risks_department
    ON personalization_risks(organization_id, department_id)
    WHERE department_id IS NOT NULL;

COMMENT ON TABLE personalization_risks IS
'Phase 2進化版 A2: 属人化リスクの記録
- 特定の人にしか回答できない状態を検出
- BCPリスクとして管理者に通知';
```

### 4.2 response_logs テーブル（回答ログ用・オプション）

```sql
-- 回答ログ（属人化検出用）【Phase 2進化版 A2】
-- 注: room_messages から派生データとして集計可能な場合は不要
CREATE TABLE response_logs (
    -- 基本情報
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- 回答情報
    question_message_id BIGINT NOT NULL,        -- 質問のmessage_id
    response_message_id BIGINT NOT NULL,        -- 回答のmessage_id
    responder_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- 分類
    topic_category VARCHAR(50),                 -- カテゴリ分類

    -- タイムスタンプ
    question_time TIMESTAMPTZ NOT NULL,
    response_time TIMESTAMPTZ NOT NULL,
    response_delay_seconds INT,                 -- 回答までの時間

    -- 監査フィールド
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 制約
    UNIQUE(organization_id, question_message_id, response_message_id)
);

-- インデックス
CREATE INDEX idx_response_logs_org_responder
    ON response_logs(organization_id, responder_user_id, topic_category);
CREATE INDEX idx_response_logs_org_time
    ON response_logs(organization_id, response_time DESC);

COMMENT ON TABLE response_logs IS
'Phase 2進化版 A2: 回答ログ
- 誰がどのカテゴリの質問に回答したかを記録
- 属人化検出の分析に使用';
```

---

## 5. 実装設計

### 5.1 PersonalizationDetector クラス

```python
# lib/detection/personalization_detector.py
"""
A2 属人化検出
特定の人にしか回答できない状態を検出し、BCPリスクを可視化
"""
from typing import Dict, List, Optional
from uuid import UUID
from datetime import datetime, timedelta
from decimal import Decimal

from lib.detection.base import BaseDetector

class PersonalizationDetector(BaseDetector):
    """
    属人化検出器

    検出ロジック:
    1. カテゴリ別の回答者を集計
    2. 特定の人の回答比率を計算
    3. 閾値を超えたら属人化リスクとして検出
    4. リスクレベルを評価
    5. soulkun_insightsに登録
    """

    def __init__(self, conn, org_id: UUID):
        super().__init__(conn, org_id)
        self.detector_type = "a2_personalization"
        self.insight_type = "personalization_risk"

        # 検出パラメータ
        self.personalization_threshold = 0.8
        self.min_responses = 5
        self.analysis_window_days = 30
        self.high_risk_exclusive_days = 14

    async def detect(self) -> List[Dict]:
        """
        属人化リスクを検出

        Returns:
            検出されたリスクのリスト
        """
        # 1. カテゴリ別の回答統計を取得
        stats = await self._get_response_statistics()

        # 2. 属人化リスクを評価
        risks = []
        for category, category_stats in stats.items():
            risk = self._evaluate_personalization(category, category_stats)
            if risk:
                risks.append(risk)

        # 3. リスクをDBに保存
        for risk in risks:
            await self._save_risk(risk)

        # 4. 閾値を超えたリスクはInsightに登録
        insights = []
        for risk in risks:
            if risk['risk_level'] in ('critical', 'high', 'medium'):
                insight = await self._create_and_save_insight(risk)
                insights.append(insight)

        return insights

    async def _get_response_statistics(self) -> Dict:
        """
        カテゴリ別の回答統計を取得
        """
        # room_messages から回答パターンを分析
        # ソウルくんへの質問 → 誰かの回答 のペアを抽出
        # （実装は実際のデータ構造に依存）
        pass

    def _evaluate_personalization(
        self,
        category: str,
        stats: Dict
    ) -> Optional[Dict]:
        """
        属人化リスクを評価
        """
        total = stats.get('total_responses', 0)
        if total < self.min_responses:
            return None

        # 最も多く回答している人を特定
        top_responder = max(
            stats['responders'].items(),
            key=lambda x: x[1],
            default=(None, 0)
        )

        if not top_responder[0]:
            return None

        ratio = top_responder[1] / total

        if ratio < 0.6:  # 60%未満は検出対象外
            return None

        # リスクレベルを判定
        risk_level = self._determine_risk_level(
            ratio=ratio,
            total=total,
            exclusive=(len(stats['responders']) == 1),
            consecutive_days=stats.get('consecutive_days', 0)
        )

        return {
            'expert_user_id': top_responder[0],
            'topic_category': category,
            'total_responses': total,
            'expert_responses': top_responder[1],
            'personalization_ratio': ratio,
            'risk_level': risk_level,
            'alternative_responders': [
                uid for uid in stats['responders'].keys()
                if uid != top_responder[0]
            ],
            'has_alternative': len(stats['responders']) > 1,
            'sample_questions': stats.get('sample_questions', [])[:5],
        }

    def _determine_risk_level(
        self,
        ratio: float,
        total: int,
        exclusive: bool,
        consecutive_days: int
    ) -> str:
        """
        リスクレベルを判定
        """
        if exclusive and consecutive_days >= 30:
            return 'critical'
        elif ratio >= 0.8 and consecutive_days >= 14:
            return 'high'
        elif ratio >= 0.6 and consecutive_days >= 7:
            return 'medium'
        else:
            return 'low'

    def _create_insight(self, risk: Dict) -> Dict:
        """
        リスクからInsightオブジェクトを生成
        """
        ratio_pct = int(risk['personalization_ratio'] * 100)

        return {
            'organization_id': self.org_id,
            'insight_type': self.insight_type,
            'source_type': self.detector_type,
            'source_id': risk.get('id'),
            'importance': risk['risk_level'],
            'title': f"「{risk['topic_category']}」の回答が{ratio_pct}%属人化しています",
            'description': (
                f"過去30日間で「{risk['topic_category']}」カテゴリの質問に対する回答の"
                f"{ratio_pct}%が特定の1人に集中しています。"
                f"この状態はBCP（事業継続）リスクです。"
            ),
            'recommended_action': (
                "1. この分野のナレッジを文書化\n"
                "2. 代替回答者の育成\n"
                "3. 定期的な知識共有セッションの実施"
            ),
            'evidence': {
                'expert_user_id': str(risk['expert_user_id']),
                'topic_category': risk['topic_category'],
                'personalization_ratio': ratio_pct,
                'total_responses': risk['total_responses'],
                'has_alternative': risk['has_alternative'],
                'sample_questions': risk.get('sample_questions', [])
            },
            'classification': 'internal'
        }
```

---

## 6. 実装計画

### 6.1 実装ステップ

| ステップ | 内容 | 完了条件 |
|---------|------|---------|
| 1 | DBマイグレーション実行 | テーブル作成完了 |
| 2 | PersonalizationDetector実装 | ユニットテスト通過 |
| 3 | Cloud Function追加 | デプロイ成功 |
| 4 | Cloud Scheduler設定 | 定期実行確認 |
| 5 | 週次レポート統合 | A2の結果が含まれる |

---

## 7. チェックリスト

### 7.1 設計完了チェック

- [x] CLAUDE.md 10の鉄則準拠
- [x] A1パターン検出との整合性
- [x] BaseDetector継承設計
- [x] soulkun_insights統合
- [x] 週次レポート統合

---

**設計書 終了**
