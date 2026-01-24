# Phase 2 進化版: B 覚える能力（Memory Framework）- 詳細設計書

**バージョン:** v1.0
**作成日:** 2026-01-24
**作成者:** Claude Code（経営参謀・SE・PM）
**ステータス:** 設計・実装中

---

## 1. エグゼクティブサマリー

### 1.1 この設計書の目的

**B. 覚える能力**は、Phase 2進化版「24機能」のグループBとして、**AIの記憶・学習能力を強化し、より文脈に沿った回答を提供する機能群**です。

### 1.2 3行で要約

1. **何をするか**: 会話履歴のサマリー化、ユーザー嗜好の学習、組織知識の自動蓄積
2. **なぜ必要か**: 長期記憶により「初めまして」を繰り返さない、一貫性のある対応を実現
3. **どう作るか**: PostgreSQLに記憶データを構造化保存 + LLMでサマリー/学習

### 1.3 グループA（気づく能力）との連携

| グループA機能 | グループB連携 |
|--------------|--------------|
| A1 パターン検出 | → B3で頻出Q&Aを自動ナレッジ化 |
| A2 属人化検出 | → B2でユーザー嗜好として記録 |
| A3 ボトルネック検出 | → B1でコンテキスト参照 |
| A4 感情変化検出 | → B2で感情傾向を学習 |

---

## 2. 全体設計

### 2.1 Phase 2進化版における位置づけ

```
Phase 2 進化版（24機能）
├─ A. 気づく能力（4機能）✅ 完了
│   ├─ A1. パターン検出 ✅
│   ├─ A2. 属人化検出 ✅
│   ├─ A3. ボトルネック検出 ✅
│   └─ A4. 感情変化検出 ✅
├─ ★ B. 覚える能力（4機能）← 本設計書のスコープ
│   ├─ B1. 会話サマリー記憶
│   ├─ B2. ユーザー嗜好学習
│   ├─ B3. 組織知識自動蓄積
│   └─ B4. 会話検索
├─ C. 先読みする能力（4機能）
├─ D. つなぐ能力（3機能）
├─ E. 育てる能力（3機能）
├─ F. 自動化能力（3機能）
├─ G. 進化する能力（3機能）
└─ H. 守る能力（2機能）
```

### 2.2 CLAUDE.md 10の鉄則への準拠

| # | 鉄則 | 本設計での対応 |
|---|------|---------------|
| 1 | 全テーブルにorganization_id | ✅ 全テーブルに含む |
| 2 | RLS実装 | ✅ Phase 4で有効化（設計済み） |
| 3 | 監査ログを記録 | ✅ confidential以上で記録 |
| 4 | API認証必須 | ✅ Bearer Token必須 |
| 5 | ページネーション | ✅ limit/offset実装 |
| 6 | キャッシュTTL | ✅ Redis対応設計 |
| 7 | APIバージョニング | ✅ /api/v1/ |
| 8 | エラーに機密情報含めない | ✅ サニタイズ実装 |
| 9 | SQLパラメータ化 | ✅ プレースホルダ使用 |
| 10 | トランザクション内API禁止 | ✅ 分離設計 |

---

## 3. B1: 会話サマリー記憶

### 3.1 機能概要

会話が一定量たまったら自動的にサマリー化し、長期記憶として保存。新しい会話時にサマリーを参照して文脈を維持。

```
【会話フロー】
ユーザー ← → ソウルくん
         ↓
    会話履歴（Firestore）
         ↓ 10件超過
    サマリー生成（LLM）
         ↓
    conversation_summaries（PostgreSQL）
         ↓
    次回会話時に参照
```

### 3.2 データベース設計

```sql
-- 会話サマリー【Phase 2 B1】
CREATE TABLE conversation_summaries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- サマリー内容
    summary_text TEXT NOT NULL,              -- サマリー本文
    key_topics TEXT[] DEFAULT '{}',          -- 主要トピック
    mentioned_persons TEXT[] DEFAULT '{}',   -- 言及された人物
    mentioned_tasks TEXT[] DEFAULT '{}',     -- 言及されたタスク

    -- 期間
    conversation_start TIMESTAMPTZ NOT NULL,
    conversation_end TIMESTAMPTZ NOT NULL,
    message_count INT NOT NULL,              -- 含まれるメッセージ数

    -- メタデータ
    room_id VARCHAR(50),                     -- ChatWorkルームID
    generated_by VARCHAR(50) DEFAULT 'llm',  -- llm / manual

    -- 機密区分
    classification VARCHAR(20) DEFAULT 'internal',

    -- 監査フィールド
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 制約
    CONSTRAINT check_classification CHECK (classification IN ('public', 'internal', 'confidential', 'restricted'))
);

-- インデックス
CREATE INDEX idx_conv_summaries_org_user ON conversation_summaries(organization_id, user_id);
CREATE INDEX idx_conv_summaries_created ON conversation_summaries(created_at DESC);
```

### 3.3 サマリー生成パラメータ

| パラメータ | デフォルト | 説明 |
|-----------|-----------|------|
| SUMMARY_TRIGGER_COUNT | 10 | サマリー生成のトリガーメッセージ数 |
| SUMMARY_MAX_LENGTH | 500 | サマリーの最大文字数 |
| SUMMARY_RETENTION_DAYS | 90 | サマリー保持期間（日） |

### 3.4 サマリー生成プロンプト

```python
CONVERSATION_SUMMARY_PROMPT = """
以下の会話履歴を要約してください。

【要約のポイント】
1. 主要なトピック（何について話したか）
2. 重要な決定事項や合意
3. 言及された人物名
4. 言及されたタスク
5. ユーザーの関心事や課題

【出力形式】JSON
{
  "summary": "200-500文字の要約",
  "key_topics": ["トピック1", "トピック2"],
  "mentioned_persons": ["人物1", "人物2"],
  "mentioned_tasks": ["タスク1"],
  "user_concerns": ["課題1"]
}

【会話履歴】
{conversation_history}
"""
```

---

## 4. B2: ユーザー嗜好学習

### 4.1 機能概要

ユーザーごとの好み（回答スタイル、よく使う機能、コミュニケーション傾向）を自動学習し、パーソナライズされた対応を行う。

### 4.2 データベース設計

```sql
-- ユーザー嗜好【Phase 2 B2】
CREATE TABLE user_preferences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- 嗜好データ
    preference_type VARCHAR(50) NOT NULL,    -- response_style, feature_usage, communication, schedule
    preference_key VARCHAR(100) NOT NULL,    -- 具体的な嗜好項目
    preference_value JSONB NOT NULL,         -- 値（複雑なデータ対応）

    -- 学習情報
    learned_from VARCHAR(50) DEFAULT 'auto', -- auto / explicit / a4_emotion
    confidence DECIMAL(4,3) DEFAULT 0.5,     -- 信頼度（0.0-1.0）
    sample_count INT DEFAULT 1,              -- 学習に使用したサンプル数

    -- 機密区分
    classification VARCHAR(20) DEFAULT 'internal',

    -- 監査フィールド
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- 制約
    UNIQUE(organization_id, user_id, preference_type, preference_key)
);

-- インデックス
CREATE INDEX idx_user_prefs_org_user ON user_preferences(organization_id, user_id);
CREATE INDEX idx_user_prefs_type ON user_preferences(preference_type);
```

### 4.3 嗜好タイプ

| タイプ | 説明 | 例 |
|--------|------|-----|
| `response_style` | 回答スタイル | 簡潔 / 詳細、カジュアル / フォーマル |
| `feature_usage` | よく使う機能 | タスク検索、ナレッジ検索 |
| `communication` | コミュニケーション傾向 | 朝型 / 夜型、絵文字使用 |
| `schedule` | スケジュール傾向 | 忙しい曜日、会議が多い時間帯 |
| `emotion_trend` | 感情傾向（A4連携） | ベースラインスコア、変動パターン |

---

## 5. B3: 組織知識自動蓄積

### 5.1 機能概要

A1パターン検出で検出された頻出質問を自動的にナレッジ化。管理者の承認後、Phase 3のナレッジ検索に統合。

### 5.2 A1パターン検出との連携フロー

```
A1 パターン検出
    ↓
頻出質問を検出（occurrence_count >= 5）
    ↓
soulkun_insights に登録（insight_type='pattern_detected'）
    ↓
B3 組織知識自動蓄積
    ↓
回答パターンをLLMで生成
    ↓
organization_auto_knowledge に下書き保存
    ↓
管理者が承認
    ↓
Phase 3 ナレッジ検索に統合
```

### 5.3 データベース設計

```sql
-- 組織知識自動蓄積【Phase 2 B3】
CREATE TABLE organization_auto_knowledge (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- 元データ（A1パターン検出連携）
    source_insight_id UUID REFERENCES soulkun_insights(id) ON DELETE SET NULL,
    source_pattern_id UUID REFERENCES question_patterns(id) ON DELETE SET NULL,

    -- 知識データ
    question TEXT NOT NULL,                  -- 質問（正規化後）
    answer TEXT NOT NULL,                    -- 自動生成された回答
    category VARCHAR(50),                    -- カテゴリ
    keywords TEXT[] DEFAULT '{}',            -- 検索用キーワード

    -- ステータス
    status VARCHAR(20) DEFAULT 'draft',      -- draft, approved, rejected, archived
    approved_at TIMESTAMPTZ,
    approved_by UUID REFERENCES users(id) ON DELETE SET NULL,
    rejection_reason TEXT,

    -- Phase 3連携
    synced_to_phase3 BOOLEAN DEFAULT FALSE,
    phase3_document_id UUID,

    -- 品質スコア
    usage_count INT DEFAULT 0,               -- 使用回数
    helpful_count INT DEFAULT 0,             -- 役に立った回数
    quality_score DECIMAL(4,3),              -- 品質スコア

    -- 機密区分
    classification VARCHAR(20) DEFAULT 'internal',

    -- 監査フィールド
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- インデックス
CREATE INDEX idx_auto_knowledge_org ON organization_auto_knowledge(organization_id);
CREATE INDEX idx_auto_knowledge_status ON organization_auto_knowledge(status);
CREATE INDEX idx_auto_knowledge_source ON organization_auto_knowledge(source_insight_id);
```

---

## 6. B4: 会話検索

### 6.1 機能概要

過去の会話を検索・参照する機能。ユーザーが「前に話した〇〇について」と言ったときに、関連する過去の会話を取得。

### 6.2 データベース設計

```sql
-- 会話インデックス【Phase 2 B4】
CREATE TABLE conversation_index (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- 会話データ
    message_id VARCHAR(100),                 -- ChatWorkメッセージID
    room_id VARCHAR(50),                     -- ChatWorkルームID
    message_text TEXT NOT NULL,              -- メッセージ本文
    message_type VARCHAR(20) NOT NULL,       -- user / assistant

    -- 検索用データ
    keywords TEXT[] DEFAULT '{}',            -- 抽出されたキーワード
    entities JSONB DEFAULT '{}',             -- 抽出されたエンティティ
    embedding_id VARCHAR(100),               -- Pineconeベクトル参照（将来用）

    -- タイムスタンプ
    message_time TIMESTAMPTZ NOT NULL,

    -- 機密区分
    classification VARCHAR(20) DEFAULT 'internal',

    -- 監査フィールド
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- インデックス
CREATE INDEX idx_conv_index_org_user ON conversation_index(organization_id, user_id);
CREATE INDEX idx_conv_index_time ON conversation_index(message_time DESC);
CREATE INDEX idx_conv_index_keywords ON conversation_index USING GIN(keywords);
CREATE INDEX idx_conv_index_room ON conversation_index(room_id, message_time DESC);

-- 全文検索インデックス（日本語対応）
CREATE INDEX idx_conv_index_text ON conversation_index
    USING GIN(to_tsvector('simple', message_text));
```

### 6.3 検索API

```
POST /api/v1/conversations/search

Request:
{
  "query": "週報の出し方",
  "user_id": "uuid",        // オプション
  "from_date": "2026-01-01",
  "to_date": "2026-01-24",
  "limit": 10
}

Response:
{
  "conversations": [
    {
      "message_id": "xxx",
      "message_text": "週報の出し方を教えて",
      "message_time": "2026-01-20T10:30:00Z",
      "context": [
        // 前後の会話
      ]
    }
  ],
  "total": 5
}
```

---

## 7. 実装設計

### 7.1 ファイル構成

```
lib/
├── memory/                         # Bグループ 覚える能力
│   ├── __init__.py
│   ├── base.py                     # BaseMemory 基底クラス
│   ├── constants.py                # 定数定義
│   ├── exceptions.py               # 例外クラス
│   ├── conversation_summary.py     # B1 会話サマリー記憶
│   ├── user_preference.py          # B2 ユーザー嗜好学習
│   ├── auto_knowledge.py           # B3 組織知識自動蓄積
│   └── conversation_search.py      # B4 会話検索
└── detection/                      # Aグループ（既存）
    └── ...

pattern-detection/                  # Cloud Functions
├── main.py                         # 検出エンドポイント
└── lib/memory/                     # lib/からコピー
```

### 7.2 BaseMemory（記憶基盤）

```python
# lib/memory/base.py
"""
記憶基盤の抽象クラス
全ての記憶機能（B1, B2, B3, B4）はこのクラスを継承する
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from uuid import UUID
from datetime import datetime

class BaseMemory(ABC):
    """
    記憶機能の基底クラス

    継承クラスは以下を実装する:
    - save(): データを保存
    - retrieve(): データを取得
    - update(): データを更新（オプション）
    """

    def __init__(self, conn, org_id: UUID):
        self.conn = conn
        self.org_id = org_id
        self.memory_type: str = ""

    @abstractmethod
    async def save(self, **kwargs) -> UUID:
        """データを保存"""
        pass

    @abstractmethod
    async def retrieve(self, **kwargs) -> List[Dict]:
        """データを取得"""
        pass
```

---

## 8. Cloud Function設計

### 8.1 新規エンドポイント

| 関数名 | トリガー | 説明 |
|--------|---------|------|
| `conversation_summary` | HTTP POST | 会話サマリー生成 |
| `user_preference_update` | HTTP POST | ユーザー嗜好更新 |
| `auto_knowledge_generate` | Cloud Scheduler (毎日) | 自動知識生成 |

### 8.2 実装例

```python
@functions_framework.http
def conversation_summary(request):
    """
    POST /conversation-summary

    会話サマリーを生成して保存
    """
    from lib.memory import ConversationSummary

    data = request.get_json()
    user_id = data.get('user_id')
    org_id = data.get('organization_id')

    with get_db_pool().connect() as conn:
        summary = ConversationSummary(conn, org_id)
        result = await summary.generate_and_save(user_id)

    return jsonify({
        'status': 'success',
        'summary_id': str(result.id)
    })
```

---

## 9. マイグレーションSQL

```sql
-- ============================================================
-- Phase 2 B: 覚える能力（Memory Framework）
-- 作成日: 2026-01-24
-- ============================================================

-- B1: conversation_summaries
CREATE TABLE IF NOT EXISTS conversation_summaries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    summary_text TEXT NOT NULL,
    key_topics TEXT[] DEFAULT '{}',
    mentioned_persons TEXT[] DEFAULT '{}',
    mentioned_tasks TEXT[] DEFAULT '{}',
    conversation_start TIMESTAMPTZ NOT NULL,
    conversation_end TIMESTAMPTZ NOT NULL,
    message_count INT NOT NULL,
    room_id VARCHAR(50),
    generated_by VARCHAR(50) DEFAULT 'llm',
    classification VARCHAR(20) DEFAULT 'internal',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT check_cs_classification CHECK (classification IN ('public', 'internal', 'confidential', 'restricted'))
);

CREATE INDEX IF NOT EXISTS idx_conv_summaries_org_user ON conversation_summaries(organization_id, user_id);
CREATE INDEX IF NOT EXISTS idx_conv_summaries_created ON conversation_summaries(created_at DESC);

-- B2: user_preferences
CREATE TABLE IF NOT EXISTS user_preferences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    preference_type VARCHAR(50) NOT NULL,
    preference_key VARCHAR(100) NOT NULL,
    preference_value JSONB NOT NULL,
    learned_from VARCHAR(50) DEFAULT 'auto',
    confidence DECIMAL(4,3) DEFAULT 0.5,
    sample_count INT DEFAULT 1,
    classification VARCHAR(20) DEFAULT 'internal',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(organization_id, user_id, preference_type, preference_key),
    CONSTRAINT check_up_classification CHECK (classification IN ('public', 'internal', 'confidential', 'restricted'))
);

CREATE INDEX IF NOT EXISTS idx_user_prefs_org_user ON user_preferences(organization_id, user_id);
CREATE INDEX IF NOT EXISTS idx_user_prefs_type ON user_preferences(preference_type);

-- B3: organization_auto_knowledge
CREATE TABLE IF NOT EXISTS organization_auto_knowledge (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    source_insight_id UUID REFERENCES soulkun_insights(id) ON DELETE SET NULL,
    source_pattern_id UUID REFERENCES question_patterns(id) ON DELETE SET NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    category VARCHAR(50),
    keywords TEXT[] DEFAULT '{}',
    status VARCHAR(20) DEFAULT 'draft',
    approved_at TIMESTAMPTZ,
    approved_by UUID REFERENCES users(id) ON DELETE SET NULL,
    rejection_reason TEXT,
    synced_to_phase3 BOOLEAN DEFAULT FALSE,
    phase3_document_id UUID,
    usage_count INT DEFAULT 0,
    helpful_count INT DEFAULT 0,
    quality_score DECIMAL(4,3),
    classification VARCHAR(20) DEFAULT 'internal',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT check_oak_status CHECK (status IN ('draft', 'approved', 'rejected', 'archived')),
    CONSTRAINT check_oak_classification CHECK (classification IN ('public', 'internal', 'confidential', 'restricted'))
);

CREATE INDEX IF NOT EXISTS idx_auto_knowledge_org ON organization_auto_knowledge(organization_id);
CREATE INDEX IF NOT EXISTS idx_auto_knowledge_status ON organization_auto_knowledge(status);
CREATE INDEX IF NOT EXISTS idx_auto_knowledge_source ON organization_auto_knowledge(source_insight_id);

-- B4: conversation_index
CREATE TABLE IF NOT EXISTS conversation_index (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message_id VARCHAR(100),
    room_id VARCHAR(50),
    message_text TEXT NOT NULL,
    message_type VARCHAR(20) NOT NULL,
    keywords TEXT[] DEFAULT '{}',
    entities JSONB DEFAULT '{}',
    embedding_id VARCHAR(100),
    message_time TIMESTAMPTZ NOT NULL,
    classification VARCHAR(20) DEFAULT 'internal',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT check_ci_message_type CHECK (message_type IN ('user', 'assistant')),
    CONSTRAINT check_ci_classification CHECK (classification IN ('public', 'internal', 'confidential', 'restricted'))
);

CREATE INDEX IF NOT EXISTS idx_conv_index_org_user ON conversation_index(organization_id, user_id);
CREATE INDEX IF NOT EXISTS idx_conv_index_time ON conversation_index(message_time DESC);
CREATE INDEX IF NOT EXISTS idx_conv_index_keywords ON conversation_index USING GIN(keywords);
CREATE INDEX IF NOT EXISTS idx_conv_index_room ON conversation_index(room_id, message_time DESC);

-- 完了メッセージ
DO $$
BEGIN
    RAISE NOTICE '✅ Phase 2 B 覚える能力 テーブル作成完了';
    RAISE NOTICE '  - conversation_summaries: B1 会話サマリー記憶';
    RAISE NOTICE '  - user_preferences: B2 ユーザー嗜好学習';
    RAISE NOTICE '  - organization_auto_knowledge: B3 組織知識自動蓄積';
    RAISE NOTICE '  - conversation_index: B4 会話検索';
END $$;
```

---

## 10. テスト設計

### 10.1 テストケース数目標

| 機能 | テストケース数 |
|------|---------------|
| B1 会話サマリー記憶 | 20件 |
| B2 ユーザー嗜好学習 | 20件 |
| B3 組織知識自動蓄積 | 20件 |
| B4 会話検索 | 20件 |
| **合計** | **80件以上** |

### 10.2 主要テストケース

**B1 会話サマリー記憶:**
- サマリー生成トリガー（10件で発火）
- サマリーテキスト生成
- key_topics抽出
- organization_idフィルタ

**B2 ユーザー嗜好学習:**
- 嗜好タイプ別保存
- 信頼度更新
- UPSERT動作
- A4感情検出連携

**B3 組織知識自動蓄積:**
- A1パターン検出連携
- 回答自動生成
- 承認フロー
- Phase 3連携

**B4 会話検索:**
- キーワード検索
- 日付範囲検索
- ユーザーフィルタ
- ページネーション

---

## 11. デプロイ計画

### 11.1 フェーズ分け

| フェーズ | 内容 | 工数 |
|---------|------|------|
| B1 | 会話サマリー記憶 | 4h |
| B2 | ユーザー嗜好学習 | 4h |
| B3 | 組織知識自動蓄積 | 6h |
| B4 | 会話検索 | 4h |
| テスト | 80件以上 | 6h |
| デプロイ | Cloud Functions | 2h |
| **合計** | | **26h** |

### 11.2 デプロイ順序

1. DBマイグレーション実行
2. lib/memory/ 実装
3. pattern-detection/lib/memory/ 同期
4. Cloud Functionデプロイ
5. chatwork-webhook統合

---

## 12. チェックリスト

### 12.1 設計完了チェック

- [x] CLAUDE.md 10の鉄則準拠
- [x] Aグループとの連携設計
- [x] テーブル設計（organization_id, classification）
- [x] API設計
- [x] テスト設計

### 12.2 実装チェック

- [ ] マイグレーション実行
- [ ] B1 実装・テスト
- [ ] B2 実装・テスト
- [ ] B3 実装・テスト
- [ ] B4 実装・テスト
- [ ] Cloud Functionデプロイ
- [ ] chatwork-webhook統合

---

**設計書 終了**
