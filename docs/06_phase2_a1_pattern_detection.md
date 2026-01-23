# Phase 2 進化版: A1 パターン検出 - 詳細設計書

**バージョン:** v1.0
**作成日:** 2026-01-23
**作成者:** Claude Code（経営参謀・SE・PM）
**ステータス:** 設計中

---

## 1. エグゼクティブサマリー

### 1.1 この設計書の目的

**A1 パターン検出**は、Phase 2進化版「24機能」の最初の実装として、**頻出質問を自動検出し、組織のナレッジ化を促進する機能**です。

### 1.2 3行で要約

1. **何をするか**: ソウルくんへの質問を分析し、同じ質問が繰り返されていたら管理者に報告
2. **なぜ必要か**: 繰り返される質問 = 全社周知すべき情報。ナレッジ化で工数削減
3. **どう作るか**: 既存会話ログを分析 → `soulkun_insights` に保存 → 週次レポートで通知

### 1.3 期待される効果

| 指標 | 現状 | 導入後 | 改善率 |
|------|------|--------|--------|
| 繰り返し質問への対応工数 | 月10時間（推定） | 月2時間 | **-80%** |
| ナレッジ化される情報 | 手動のみ | 自動提案 | **+∞** |
| 属人化リスクの可視化 | なし | 自動検出 | **新規** |

---

## 2. 全体設計との整合性

### 2.1 Phase 2進化版における位置づけ

```
Phase 2 進化版（24機能）
├─ A. 気づく能力（4機能）
│   ├─ ★ A1. パターン検出 ← 本設計書のスコープ
│   ├─ A2. 属人化検出（将来）
│   ├─ A3. ボトルネック検出（将来）
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
| Phase 1 | タスク管理 - パターン検出結果をタスク化可能 |
| Phase 1-B | notification_logs - 通知の冪等性を共有 |
| Phase 2.5 | 目標達成支援 - 目標関連の質問パターンも検出 |
| Phase 3 | ナレッジ検索 - 検出したパターンをナレッジ化 |
| Phase 3.5 | 組織階層 - 部署ごとのパターン分析 |

### 2.3 CLAUDE.md 10の鉄則への準拠

| # | 鉄則 | 本設計での対応 |
|---|------|---------------|
| 1 | 全テーブルにorganization_id | ✅ 全テーブルに含む |
| 2 | RLS実装 | ✅ Phase 4で有効化（設計済み） |
| 3 | 監査ログを記録 | ✅ confidential以上で記録 |
| 4 | API認証必須 | ✅ Bearer Token必須 |
| 5 | ページネーション | ✅ limit/offset実装 |
| 6 | キャッシュTTL | ⏳ Phase 4で導入 |
| 7 | APIバージョニング | ✅ /api/v1/ |
| 8 | エラーに機密情報含めない | ✅ サニタイズ実装 |
| 9 | SQLパラメータ化 | ✅ プレースホルダ使用 |
| 10 | トランザクション内API禁止 | ✅ 分離設計 |

---

## 3. 機能設計

### 3.1 機能概要

```
┌─────────────────────────────────────────────────────────────┐
│                   A1 パターン検出フロー                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  【入力】                                                   │
│  ソウルくんへの質問（ChatWork経由）                         │
│       ↓                                                     │
│  【処理1】質問の正規化                                      │
│  - 挨拶除去（「お疲れ様です」等）                           │
│  - 表記ゆれ統一（「週報」「しゅうほう」→「週報」）          │
│       ↓                                                     │
│  【処理2】カテゴリ分類（LLM）                               │
│  - 業務手続き / 社内ルール / 技術質問 / 人事 / その他      │
│       ↓                                                     │
│  【処理3】類似度ハッシュ生成                                │
│  - 同じ意味の質問を同一パターンとして認識                   │
│       ↓                                                     │
│  【処理4】パターンDB更新                                    │
│  - 既存パターンなら occurrence_count++                      │
│  - 新規パターンなら INSERT                                  │
│       ↓                                                     │
│  【処理5】閾値チェック                                      │
│  - occurrence_count >= 5 なら soulkun_insights に登録      │
│       ↓                                                     │
│  【出力】                                                   │
│  週次レポートで管理者に通知                                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 検出パラメータ

| パラメータ | デフォルト値 | 説明 | 変更可能 |
|-----------|------------|------|---------|
| PATTERN_THRESHOLD | 5 | 通知する最小発生回数 | ✅ |
| PATTERN_WINDOW_DAYS | 30 | パターン検出の対象期間（日） | ✅ |
| MAX_SAMPLE_QUESTIONS | 5 | 保存するサンプル質問の最大数 | ✅ |
| SIMILARITY_THRESHOLD | 0.85 | 類似度の閾値（0.0-1.0） | ✅ |
| WEEKLY_REPORT_DAY | 1 | 週次レポート送信曜日（1=月曜） | ✅ |

### 3.3 カテゴリ分類

| カテゴリ | 説明 | 例 |
|---------|------|-----|
| `business_process` | 業務手続き | 「週報の出し方」「経費精算の方法」 |
| `company_rule` | 社内ルール | 「有給の申請方法」「服装規定」 |
| `technical` | 技術質問 | 「Slackの使い方」「VPN接続方法」 |
| `hr_related` | 人事関連 | 「評価制度」「昇給の仕組み」 |
| `project` | プロジェクト | 「〇〇プロジェクトの進捗」 |
| `other` | その他 | 分類不能 |

---

## 4. データベース設計

### 4.1 テーブル一覧

| テーブル | 用途 | 新規/既存 |
|---------|------|----------|
| `question_patterns` | 質問パターンの記録 | 新規 |
| `soulkun_insights` | ソウルくんの気づき（統合） | 新規 |
| `soulkun_weekly_reports` | 週次レポート | 新規 |

### 4.2 question_patterns（質問パターン）

```sql
-- 質問パターンの記録【Phase 2進化版 A1】
CREATE TABLE question_patterns (
    -- 基本情報
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- 部署フィルタ（Phase 3.5準拠）
    department_id UUID REFERENCES departments(id) ON DELETE SET NULL,

    -- パターンデータ
    question_category VARCHAR(50) NOT NULL,      -- カテゴリ
    question_hash VARCHAR(64) NOT NULL,          -- 類似度判定用ハッシュ
    normalized_question TEXT NOT NULL,           -- 正規化された質問文

    -- 統計
    occurrence_count INT DEFAULT 1,
    first_asked_at TIMESTAMPTZ NOT NULL,
    last_asked_at TIMESTAMPTZ NOT NULL,
    asked_by_user_ids UUID[] DEFAULT '{}',       -- 質問した人のリスト
    sample_questions TEXT[] DEFAULT '{}',         -- サンプル質問（最大5件）

    -- ステータス
    status VARCHAR(20) DEFAULT 'active',          -- active, addressed, dismissed
    addressed_at TIMESTAMPTZ,
    addressed_action TEXT,                        -- 対応内容

    -- 機密区分
    classification VARCHAR(20) DEFAULT 'internal',

    -- 監査フィールド
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 制約
    UNIQUE(organization_id, question_hash)
);

-- インデックス
CREATE INDEX idx_question_patterns_org_count
    ON question_patterns(organization_id, occurrence_count DESC);
CREATE INDEX idx_question_patterns_category
    ON question_patterns(organization_id, question_category);
CREATE INDEX idx_question_patterns_department
    ON question_patterns(organization_id, department_id)
    WHERE department_id IS NOT NULL;
CREATE INDEX idx_question_patterns_status
    ON question_patterns(organization_id, status)
    WHERE status = 'active';

COMMENT ON TABLE question_patterns IS
'Phase 2進化版 A1: 質問パターンの記録
- 同じ質問が繰り返されていたら検出
- occurrence_count >= PATTERN_THRESHOLD で soulkun_insights に登録';
```

### 4.3 soulkun_insights（ソウルくんの気づき）

```sql
-- ソウルくんの気づき（全検出機能の統合テーブル）【Phase 2進化版】
CREATE TABLE soulkun_insights (
    -- 基本情報
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- 部署フィルタ（Phase 3.5準拠）
    department_id UUID REFERENCES departments(id) ON DELETE SET NULL,

    -- 気づきの種類
    insight_type VARCHAR(50) NOT NULL,           -- pattern_detected, personalization_risk, bottleneck, etc.
    source_type VARCHAR(50) NOT NULL,            -- a1_pattern, a2_personalization, a3_bottleneck, a4_emotion
    source_id UUID,                              -- 元データのID（question_patterns.id等）

    -- 内容
    importance VARCHAR(20) NOT NULL,             -- critical, high, medium, low
    title VARCHAR(200) NOT NULL,
    description TEXT NOT NULL,
    recommended_action TEXT,                     -- 推奨アクション
    evidence JSONB DEFAULT '{}',                 -- 根拠データ

    -- ステータス
    status VARCHAR(20) DEFAULT 'new',            -- new, acknowledged, addressed, dismissed
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by UUID REFERENCES users(id) ON DELETE SET NULL,
    addressed_at TIMESTAMPTZ,
    addressed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    addressed_action TEXT,

    -- 通知
    notified_at TIMESTAMPTZ,
    notified_to UUID[] DEFAULT '{}',             -- 通知先ユーザーID

    -- 機密区分
    classification VARCHAR(20) DEFAULT 'internal',

    -- 監査フィールド
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- インデックス
CREATE INDEX idx_soulkun_insights_org_type
    ON soulkun_insights(organization_id, insight_type);
CREATE INDEX idx_soulkun_insights_org_importance
    ON soulkun_insights(organization_id, importance);
CREATE INDEX idx_soulkun_insights_org_status
    ON soulkun_insights(organization_id, status)
    WHERE status IN ('new', 'acknowledged');
CREATE INDEX idx_soulkun_insights_department
    ON soulkun_insights(organization_id, department_id)
    WHERE department_id IS NOT NULL;

COMMENT ON TABLE soulkun_insights IS
'Phase 2進化版: ソウルくんの気づき（統合テーブル）
- A1パターン検出、A2属人化検出、A3ボトルネック検出等の結果を統合
- 週次レポートのソースデータ
- importance: critical/high は即時通知、medium/low は週次レポート';
```

### 4.4 soulkun_weekly_reports（週次レポート）

```sql
-- 週次レポート【Phase 2進化版】
CREATE TABLE soulkun_weekly_reports (
    -- 基本情報
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- 期間
    week_start DATE NOT NULL,
    week_end DATE NOT NULL,

    -- レポート内容
    report_content TEXT NOT NULL,                -- マークダウン形式のレポート本文
    insights_summary JSONB NOT NULL,             -- 気づきのサマリー（件数、重要度別等）
    included_insight_ids UUID[] DEFAULT '{}',    -- 含まれる気づきのID

    -- 送信情報
    sent_at TIMESTAMPTZ,
    sent_to UUID[] DEFAULT '{}',                 -- 送信先ユーザーID
    sent_via VARCHAR(50),                        -- chatwork, email, etc.

    -- ステータス
    status VARCHAR(20) DEFAULT 'draft',          -- draft, sent, failed
    error_message TEXT,

    -- 機密区分
    classification VARCHAR(20) DEFAULT 'internal',

    -- 監査フィールド
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 制約
    UNIQUE(organization_id, week_start)
);

-- インデックス
CREATE INDEX idx_soulkun_weekly_reports_org_week
    ON soulkun_weekly_reports(organization_id, week_start DESC);

COMMENT ON TABLE soulkun_weekly_reports IS
'Phase 2進化版: 週次レポート
- 毎週月曜日に自動生成
- soulkun_insights の内容をまとめて管理者に送信';
```

---

## 5. API設計

### 5.1 エンドポイント一覧

| メソッド | パス | 用途 | 権限 |
|---------|------|------|------|
| GET | `/api/v1/insights` | 気づき一覧取得 | 管理者 |
| GET | `/api/v1/insights/{id}` | 気づき詳細取得 | 管理者 |
| PATCH | `/api/v1/insights/{id}` | 気づきステータス更新 | 管理者 |
| GET | `/api/v1/weekly-reports` | 週次レポート一覧 | 管理者 |
| GET | `/api/v1/weekly-reports/{id}` | 週次レポート詳細 | 管理者 |
| POST | `/api/v1/weekly-reports/generate` | 週次レポート手動生成 | 管理者 |

### 5.2 GET /api/v1/insights

**目的:** ソウルくんの気づき一覧を取得

**認証:** Bearer Token（管理者権限）

**クエリパラメータ:**

| パラメータ | 型 | 必須 | 説明 |
|-----------|---|------|------|
| organization_id | UUID | ○ | 組織ID |
| insight_type | string | × | 種類フィルタ（pattern_detected等） |
| importance | string | × | 重要度フィルタ（high, medium, low） |
| status | string | × | ステータスフィルタ（new, acknowledged, addressed） |
| department_id | UUID | × | 部署フィルタ |
| limit | int | × | 取得件数（デフォルト: 50、最大: 1000） |
| offset | int | × | オフセット（デフォルト: 0） |

**レスポンス例:**

```json
{
  "insights": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440001",
      "insight_type": "pattern_detected",
      "source_type": "a1_pattern",
      "importance": "high",
      "title": "「週報の出し方」の質問が頻出しています",
      "description": "今月10回、5人の社員から同じ質問がありました。全社周知またはナレッジ化を検討してください。",
      "recommended_action": "1. 週報の出し方マニュアルを作成\n2. 全社メールで周知",
      "status": "new",
      "created_at": "2026-01-23T10:00:00Z",
      "evidence": {
        "occurrence_count": 10,
        "unique_users": 5,
        "sample_questions": [
          "週報ってどこから出すんですか？",
          "週報の提出方法を教えてください"
        ]
      }
    }
  ],
  "total": 15,
  "pagination": {
    "limit": 50,
    "offset": 0,
    "has_more": false
  }
}
```

### 5.3 PATCH /api/v1/insights/{id}

**目的:** 気づきのステータスを更新

**リクエスト例:**

```json
{
  "status": "addressed",
  "addressed_action": "週報マニュアルを作成し、全社メールで周知しました"
}
```

**レスポンス例:**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440001",
  "status": "addressed",
  "addressed_at": "2026-01-24T14:30:00Z",
  "addressed_by": "550e8400-e29b-41d4-a716-446655440099",
  "addressed_action": "週報マニュアルを作成し、全社メールで周知しました"
}
```

---

## 6. 実装設計

### 6.1 ファイル構成

```
lib/
├── detection/                      # 検出基盤（Detection Framework）
│   ├── __init__.py
│   ├── base.py                     # BaseDetector 抽象クラス
│   ├── pattern_detector.py         # A1 パターン検出
│   ├── personalization_detector.py # A2 属人化検出（将来）
│   ├── bottleneck_detector.py      # A3 ボトルネック検出（将来）
│   └── emotion_detector.py         # A4 感情変化検出（将来）
├── insights/                       # インサイト管理
│   ├── __init__.py
│   ├── insight_service.py          # インサイトCRUD
│   └── weekly_report_service.py    # 週次レポート生成
└── text_utils.py                   # 既存（挨拶除去等）

remind-tasks/
├── main.py                         # 既存（Cloud Functions）
└── functions/
    ├── pattern_detection.py        # パターン検出Cloud Function
    └── weekly_report.py            # 週次レポートCloud Function
```

### 6.2 BaseDetector（検出基盤）

```python
# lib/detection/base.py
"""
検出基盤の抽象クラス
全ての検出機能（A1, A2, A3, A4）はこのクラスを継承する
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from uuid import UUID
from datetime import datetime

class BaseDetector(ABC):
    """
    検出機能の基底クラス

    継承クラスは以下を実装する:
    - detect(): 検出処理を実行
    - _create_insight(): 検出結果からInsightを生成
    """

    def __init__(self, conn, org_id: UUID):
        self.conn = conn
        self.org_id = org_id
        self.detector_type: str = ""  # 例: "a1_pattern"
        self.insight_type: str = ""   # 例: "pattern_detected"

    @abstractmethod
    async def detect(self, **kwargs) -> List[Dict]:
        """
        検出処理を実行
        Returns: 検出されたパターンのリスト
        """
        pass

    @abstractmethod
    def _create_insight(self, detection: Dict) -> Dict:
        """
        検出結果からInsightオブジェクトを生成
        """
        pass

    async def save_insights(self, detections: List[Dict]) -> List[UUID]:
        """
        検出結果をsoulkun_insightsに保存
        """
        insight_ids = []
        for detection in detections:
            insight = self._create_insight(detection)
            insight_id = await self._insert_insight(insight)
            insight_ids.append(insight_id)
        return insight_ids

    async def _insert_insight(self, insight: Dict) -> UUID:
        """
        soulkun_insightsにINSERT
        """
        # 実装は insight_service.py に委譲
        from lib.insights.insight_service import InsightService
        service = InsightService(self.conn)
        return await service.create(insight)
```

### 6.3 PatternDetector（A1パターン検出）

```python
# lib/detection/pattern_detector.py
"""
A1 パターン検出
頻出質問を検出し、ナレッジ化を促進する
"""
import hashlib
from typing import Dict, List, Optional
from uuid import UUID
from datetime import datetime, timedelta
import sqlalchemy
from sqlalchemy import text

from lib.detection.base import BaseDetector
from lib.text_utils import remove_greetings, normalize_text

class PatternDetector(BaseDetector):
    """
    パターン検出器

    検出ロジック:
    1. 会話ログから質問を抽出
    2. 質問を正規化（挨拶除去、表記ゆれ統一）
    3. カテゴリを分類（LLM使用）
    4. 類似度ハッシュを生成
    5. question_patternsテーブルを更新
    6. 閾値を超えたらsoulkun_insightsに登録
    """

    def __init__(self, conn, org_id: UUID):
        super().__init__(conn, org_id)
        self.detector_type = "a1_pattern"
        self.insight_type = "pattern_detected"

        # 検出パラメータ
        self.pattern_threshold = 5
        self.pattern_window_days = 30
        self.max_sample_questions = 5
        self.similarity_threshold = 0.85

    async def detect(self, question: str, user_id: UUID, department_id: Optional[UUID] = None) -> Optional[Dict]:
        """
        質問を分析し、パターンを検出

        Args:
            question: ユーザーからの質問
            user_id: 質問したユーザーのID
            department_id: ユーザーの所属部署ID（オプション）

        Returns:
            検出されたパターン情報、または None
        """
        # 1. 質問を正規化
        normalized = self._normalize_question(question)
        if not normalized:
            return None

        # 2. カテゴリを分類
        category = await self._classify_category(normalized)

        # 3. 類似度ハッシュを生成
        question_hash = self._generate_hash(normalized)

        # 4. 既存パターンを検索
        existing = await self._find_existing_pattern(question_hash)

        if existing:
            # 5a. 既存パターンを更新
            updated = await self._update_pattern(
                pattern_id=existing['id'],
                user_id=user_id,
                sample_question=question
            )

            # 6. 閾値チェック
            if updated['occurrence_count'] >= self.pattern_threshold:
                # まだInsightになっていなければ作成
                if not await self._insight_exists(existing['id']):
                    return await self._create_and_save_insight(updated)
        else:
            # 5b. 新規パターンを作成
            await self._create_pattern(
                category=category,
                question_hash=question_hash,
                normalized_question=normalized,
                user_id=user_id,
                department_id=department_id,
                sample_question=question
            )

        return None

    def _normalize_question(self, question: str) -> str:
        """
        質問を正規化
        - 挨拶除去
        - 表記ゆれ統一
        - 空白正規化
        """
        # 既存のtext_utilsを活用
        text = remove_greetings(question)
        text = normalize_text(text)
        return text.strip()

    async def _classify_category(self, question: str) -> str:
        """
        質問のカテゴリを分類（LLM使用）
        """
        # TODO: LLM APIを呼び出してカテゴリ分類
        # 暫定実装: キーワードベースで分類
        keywords = {
            'business_process': ['週報', '経費', '精算', '申請', '承認', 'ワークフロー'],
            'company_rule': ['有給', '休暇', '服装', 'ルール', '規定', '就業'],
            'technical': ['slack', 'vpn', 'パスワード', 'ログイン', 'システム'],
            'hr_related': ['評価', '昇給', '人事', '異動', '面談'],
            'project': ['プロジェクト', '案件', '進捗', '納期'],
        }

        question_lower = question.lower()
        for category, words in keywords.items():
            for word in words:
                if word.lower() in question_lower:
                    return category
        return 'other'

    def _generate_hash(self, normalized_question: str) -> str:
        """
        類似度判定用のハッシュを生成
        """
        # 簡易実装: SHA256ハッシュ
        # TODO: より高度な類似度判定（Embedding等）
        return hashlib.sha256(normalized_question.encode()).hexdigest()[:64]

    async def _find_existing_pattern(self, question_hash: str) -> Optional[Dict]:
        """
        既存パターンを検索
        """
        result = self.conn.execute(text("""
            SELECT id, occurrence_count, sample_questions
            FROM question_patterns
            WHERE organization_id = :org_id
              AND question_hash = :hash
              AND status = 'active'
        """), {'org_id': str(self.org_id), 'hash': question_hash})

        row = result.fetchone()
        if row:
            return {
                'id': row[0],
                'occurrence_count': row[1],
                'sample_questions': row[2]
            }
        return None

    async def _update_pattern(self, pattern_id: UUID, user_id: UUID, sample_question: str) -> Dict:
        """
        既存パターンを更新
        """
        result = self.conn.execute(text("""
            UPDATE question_patterns
            SET occurrence_count = occurrence_count + 1,
                last_asked_at = CURRENT_TIMESTAMP,
                asked_by_user_ids = array_append(
                    CASE
                        WHEN :user_id = ANY(asked_by_user_ids) THEN asked_by_user_ids
                        ELSE asked_by_user_ids
                    END,
                    CASE
                        WHEN :user_id = ANY(asked_by_user_ids) THEN NULL
                        ELSE :user_id::uuid
                    END
                ),
                sample_questions = CASE
                    WHEN array_length(sample_questions, 1) < :max_samples
                    THEN array_append(sample_questions, :sample)
                    ELSE sample_questions
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :pattern_id
            RETURNING id, occurrence_count, question_category, normalized_question,
                      asked_by_user_ids, sample_questions
        """), {
            'pattern_id': str(pattern_id),
            'user_id': str(user_id),
            'sample': sample_question,
            'max_samples': self.max_sample_questions
        })

        row = result.fetchone()
        self.conn.commit()

        return {
            'id': row[0],
            'occurrence_count': row[1],
            'question_category': row[2],
            'normalized_question': row[3],
            'asked_by_user_ids': row[4],
            'sample_questions': row[5]
        }

    async def _create_pattern(
        self,
        category: str,
        question_hash: str,
        normalized_question: str,
        user_id: UUID,
        department_id: Optional[UUID],
        sample_question: str
    ) -> UUID:
        """
        新規パターンを作成
        """
        result = self.conn.execute(text("""
            INSERT INTO question_patterns (
                organization_id, department_id, question_category, question_hash,
                normalized_question, first_asked_at, last_asked_at,
                asked_by_user_ids, sample_questions, created_by
            ) VALUES (
                :org_id, :dept_id, :category, :hash,
                :normalized, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                ARRAY[:user_id::uuid], ARRAY[:sample], :user_id
            )
            RETURNING id
        """), {
            'org_id': str(self.org_id),
            'dept_id': str(department_id) if department_id else None,
            'category': category,
            'hash': question_hash,
            'normalized': normalized_question,
            'user_id': str(user_id),
            'sample': sample_question
        })

        pattern_id = result.fetchone()[0]
        self.conn.commit()
        return pattern_id

    async def _insight_exists(self, source_id: UUID) -> bool:
        """
        このパターンに対するInsightが既に存在するか確認
        """
        result = self.conn.execute(text("""
            SELECT 1 FROM soulkun_insights
            WHERE organization_id = :org_id
              AND source_type = 'a1_pattern'
              AND source_id = :source_id
        """), {'org_id': str(self.org_id), 'source_id': str(source_id)})

        return result.fetchone() is not None

    def _create_insight(self, detection: Dict) -> Dict:
        """
        検出結果からInsightオブジェクトを生成
        """
        unique_users = len(set(detection.get('asked_by_user_ids', [])))
        occurrence_count = detection.get('occurrence_count', 0)

        # 重要度を判定
        if occurrence_count >= 20 or unique_users >= 10:
            importance = 'critical'
        elif occurrence_count >= 10 or unique_users >= 5:
            importance = 'high'
        elif occurrence_count >= 5:
            importance = 'medium'
        else:
            importance = 'low'

        return {
            'organization_id': self.org_id,
            'insight_type': self.insight_type,
            'source_type': self.detector_type,
            'source_id': detection['id'],
            'importance': importance,
            'title': f"「{detection['normalized_question'][:30]}...」の質問が頻出しています",
            'description': f"過去30日間で{occurrence_count}回、{unique_users}人の社員から同じ質問がありました。全社周知またはナレッジ化を検討してください。",
            'recommended_action': "1. この質問に対するマニュアルを作成\n2. 全社メールまたはSlackで周知\n3. ナレッジベースに登録（Phase 3）",
            'evidence': {
                'occurrence_count': occurrence_count,
                'unique_users': unique_users,
                'sample_questions': detection.get('sample_questions', []),
                'category': detection.get('question_category', 'other')
            },
            'classification': 'internal'
        }

    async def _create_and_save_insight(self, detection: Dict) -> Dict:
        """
        Insightを作成して保存
        """
        insight = self._create_insight(detection)
        insight_id = await self._insert_insight(insight)
        insight['id'] = insight_id
        return insight
```

---

## 7. 通知設計

### 7.1 通知タイミング

| 重要度 | 通知タイミング | 通知先 |
|--------|---------------|--------|
| critical | 即時（検出から1時間以内） | 管理者（菊地さん） |
| high | 即時（検出から1時間以内） | 管理者 |
| medium | 週次レポート | 管理者 |
| low | 週次レポート | 管理者 |

### 7.2 週次レポートテンプレート

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 ソウルくん週次レポート
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【期間】2026年1月20日〜1月26日

【今週の気づき】

🔴 重要度: HIGH（1件）
┌─────────────────────────────────────────┐
│ 「週報の出し方」の質問が頻出           │
│ - 発生回数: 10回                        │
│ - 質問者数: 5人                         │
│ - 推奨: 全社周知またはナレッジ化        │
└─────────────────────────────────────────┘

🟡 重要度: MEDIUM（2件）
1. 「VPN接続方法」の質問（6回、3人）
2. 「有給申請」の質問（5回、4人）

【推奨アクション】
1. 週報マニュアルの作成・周知
2. VPN接続ガイドの更新
3. 有給申請フローの全社案内

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
※ このレポートは自動生成されました
※ 詳細はソウルくん管理画面で確認できます
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 7.3 notification_logsとの統合

```sql
-- notification_logsに新しいnotification_typeを追加
-- 既存の制約を更新する必要がある場合はマイグレーションで対応

-- 冪等性キーの形式
-- pattern_alert:{insight_id}:{organization_id}
-- weekly_report:{week_start}:{organization_id}
```

---

## 7.4 notification_logs制約の更新

A1パターン検出の通知を `notification_logs` で管理するため、CHECK制約を更新する必要があります。

```sql
-- マイグレーション: notification_type制約の更新
ALTER TABLE notification_logs DROP CONSTRAINT IF EXISTS check_notification_type;
ALTER TABLE notification_logs ADD CONSTRAINT check_notification_type
CHECK (notification_type IN (
    -- 既存
    'task_reminder', 'task_overdue', 'task_escalation',
    'deadline_alert', 'escalation_alert', 'dm_unavailable',
    'goal_daily_check', 'goal_daily_reminder', 'goal_morning_feedback',
    'goal_team_summary', 'goal_consecutive_unanswered',
    -- A1パターン検出で追加
    'pattern_alert',      -- 頻出パターン検出アラート
    'weekly_report'       -- 週次レポート
));
```

**冪等性キーの形式:**

| notification_type | 冪等性キー形式 | 例 |
|-------------------|--------------|-----|
| pattern_alert | `{insight_id}:{org_id}` | `550e8400-...:123e4567-...` |
| weekly_report | `{week_start}:{org_id}` | `2026-01-20:123e4567-...` |

---

## 8. Cloud Functions設計

### 8.1 デプロイ対象

| 関数名 | トリガー | 実行タイミング |
|--------|---------|---------------|
| `pattern-detection-hourly` | Cloud Scheduler | 毎時 |
| `weekly-report-monday` | Cloud Scheduler | 毎週月曜 09:00 |
| `insight-notification` | Pub/Sub | Insight作成時 |

### 8.2 実行フロー

```
【hourly: パターン検出】
Cloud Scheduler (毎時)
    ↓
pattern-detection-hourly
    ↓
過去1時間の会話ログを分析
    ↓
question_patterns を更新
    ↓
閾値超えがあれば soulkun_insights に登録
    ↓
critical/high は Pub/Sub に発行

【monday: 週次レポート】
Cloud Scheduler (月曜09:00)
    ↓
weekly-report-monday
    ↓
先週の soulkun_insights を集計
    ↓
レポートを生成
    ↓
ChatWorkで管理者に送信
    ↓
soulkun_weekly_reports に保存
```

---

## 9. テスト設計

### 9.1 ユニットテスト

| テスト対象 | テスト内容 |
|-----------|-----------|
| `_normalize_question` | 挨拶除去、表記ゆれ統一 |
| `_classify_category` | カテゴリ分類の正確性 |
| `_generate_hash` | ハッシュ生成の一貫性 |
| `_create_insight` | Insight生成の正確性 |

### 9.2 統合テスト

| テスト対象 | テスト内容 |
|-----------|-----------|
| パターン検出フロー | 質問→検出→Insight生成 |
| 週次レポート生成 | Insight集計→レポート生成 |
| 通知送信 | ChatWork送信の成功確認 |

### 9.3 テストデータ

```python
TEST_QUESTIONS = [
    # 同じパターン（週報）
    "週報ってどこから出すんですか？",
    "週報の出し方を教えてください",
    "週報の提出方法が分かりません",
    "週報はどうやって書くの？",
    "週報の書き方教えて",

    # 別のパターン（VPN）
    "VPNに繋がらないんですが",
    "VPN接続方法を教えてください",

    # ユニークな質問
    "来週の会議室の予約状況は？"
]
```

---

## 10. 実装計画

### 10.1 フェーズ分け

| フェーズ | 内容 | 工数目安 |
|---------|------|---------|
| Phase A | DB設計・テーブル作成 | 2h |
| Phase B | BaseDetector実装 | 2h |
| Phase C | PatternDetector実装 | 4h |
| Phase D | InsightService実装 | 2h |
| Phase E | WeeklyReportService実装 | 3h |
| Phase F | Cloud Functions実装 | 3h |
| Phase G | テスト作成・実行 | 4h |
| Phase H | 本番デプロイ・検証 | 2h |
| **合計** | | **22h** |

### 10.2 優先順位

```
【MVP（最小限の価値提供）】
1. question_patterns テーブル作成
2. PatternDetector の detect() 実装
3. soulkun_insights テーブル作成
4. 週次レポート手動生成（Cloud Functions後回し）

【本番リリース】
5. Cloud Functions（hourly, weekly）
6. 自動通知（Pub/Sub）
7. 管理画面連携（将来）
```

---

## 11. リスクと対策

| リスク | 影響 | 対策 |
|--------|------|------|
| 誤検出（無関係な質問を同一パターンと判定） | ノイズ増加 | 類似度閾値を調整可能に |
| 過検出（大量のInsight生成） | 管理者の負担 | 週次レポートでまとめて通知 |
| LLMコスト増加 | 運用コスト | キーワードベース分類を併用 |
| 会話ログの機密性 | プライバシー | 個人情報マスキング |

---

## 12. 将来の拡張

### 12.1 A2, A3, A4への展開

本設計の「検出基盤（Detection Framework）」を活用して、以下の機能を追加可能：

| 機能 | 継承クラス | 追加テーブル |
|------|-----------|-------------|
| A2 属人化検出 | `PersonalizationDetector(BaseDetector)` | `personalization_risks` |
| A3 ボトルネック検出 | `BottleneckDetector(BaseDetector)` | `bottleneck_detections` |
| A4 感情変化検出 | `EmotionDetector(BaseDetector)` | `emotion_change_detections` |

### 12.2 Phase 3（ナレッジ検索）連携

検出されたパターンを自動的にナレッジ候補として登録：

```
頻出質問を検出
    ↓
ナレッジ化を提案
    ↓
管理者が承認
    ↓
Phase 3のドキュメントとして登録
    ↓
次回から自動回答
```

---

## 13. チェックリスト

### 13.1 設計完了チェック

- [x] CLAUDE.md 10の鉄則準拠
- [x] 既存Phase（1, 1-B, 2.5, 3, 3.5）との整合性
- [x] Phase 2進化版の全体設計との整合性
- [x] API設計（/api/v1/）
- [x] テーブル設計（organization_id, created_by/updated_by, TIMESTAMPTZ）
- [x] 拡張性（BaseDetectorによる共通基盤）
- [x] 通知設計（notification_logs統合）
- [x] テスト設計

### 13.2 実装前確認

- [ ] Phase 2.5との競合なし確認
- [ ] DBマイグレーション手順確定
- [ ] 本番環境の会話ログ形式確認
- [ ] ChatWork通知のroom_id確認

---

**設計書 終了**
