> ⚠️ **DEPRECATED - 参照禁止**
>
> このファイルは **`docs/25_llm_native_brain_architecture.md`** に統合されました。
>
> | 統合先 | 25章 第12章「既存コードからの移行計画」 |
> |--------|--------------------------------------|
> | 理由 | LLM常駐型脳アーキテクチャへの統合 |
> | 日付 | 2026-01-30 |
>
> **👉 参照すべきファイル:** [25章 LLM常駐型脳アーキテクチャ](../25_llm_native_brain_architecture.md)

---

# 統合リファクタリング計画（v10.30.0）

**作成日:** 2026-01-26
**作成者:** Claude Code（経営参謀・SE・PM）
**背景:** v10.29.9で発見した設計乖離 + コードベース全体の重複問題解決

---

## エグゼクティブサマリー

### 素人向け説明

**現状の問題：**
同じ情報（電話番号）が10冊のノートに書いてある状態。
1冊書き忘れると「その番号知らない」とバグる。

**解決策：**
1冊のマスターノートに統一。全員がそれを見る。

**工数：** 2-3日

---

## 1. 発見した問題一覧

### 1.1 最重要（Phase 4マルチテナント対応に必須）

| # | 問題 | 影響箇所 | 現状 |
|---|------|---------|------|
| 1 | 管理者アカウントID | 10+ファイル | `1728974` ハードコード |
| 2 | 管理部ルームID | 10+ファイル | `405315911` ハードコード |
| 3 | 組織ID | 4ファイル | `org_soulsyncs` ハードコード |

### 1.2 重要（保守性に影響）

| # | 問題 | 影響箇所 | 現状 |
|---|------|---------|------|
| 4 | Cloud SQL接続設定 | 7ファイル | 同じ文字列をコピペ |
| 5 | CAPABILITY_KEYWORDS | 2ファイル | decision.py と understanding.py |
| 6 | 検出パラメータ | 2ファイル | lib/ と pattern-detection/ |
| 7 | Feature Flag | 各main.py | 15個が散在、命名不統一 |
| 8 | APIエンドポイント | 3ファイル | URLハードコード |
| 9 | エラーメッセージ | 多数 | 「カズさん」直接埋込 |
| 10 | ソウルくんID | 2ファイル | MY_ACCOUNT_ID / BOT_ACCOUNT_ID |

---

## 2. 解決策

### 2.1 Phase A: 管理者設定のDB化（最優先）

**Before:**
```python
# 10ファイルにこれがある
ADMIN_ACCOUNT_ID = "1728974"
ADMIN_ROOM_ID = "405315911"
```

**After:**
```python
# lib/admin_config.py（新規）
from lib.db import get_pool

_admin_config_cache = {}

def get_admin_config(org_id: str) -> dict:
    """管理者設定をDBから取得（キャッシュ付き）"""
    if org_id in _admin_config_cache:
        return _admin_config_cache[org_id]

    pool = get_pool()
    with pool.connect() as conn:
        result = conn.execute(text("""
            SELECT admin_account_id, admin_room_id, admin_dm_room_id
            FROM organization_admin_configs
            WHERE organization_id = :org_id
        """), {"org_id": org_id}).fetchone()

    config = {
        "admin_account_id": result[0] if result else "1728974",  # フォールバック
        "admin_room_id": result[1] if result else "405315911",
        "admin_dm_room_id": result[2] if result else None,
    }
    _admin_config_cache[org_id] = config
    return config
```

**DBテーブル:**
```sql
CREATE TABLE organization_admin_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    admin_account_id VARCHAR(50) NOT NULL,
    admin_room_id VARCHAR(50) NOT NULL,
    admin_dm_room_id VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(organization_id)
);

-- ソウルシンクス用初期データ
INSERT INTO organization_admin_configs (organization_id, admin_account_id, admin_room_id, admin_dm_room_id)
VALUES ('5f98365f-e7c5-4f48-9918-7fe9aabae5df', '1728974', '405315911', '217825794');
```

### 2.2 Phase B: SYSTEM_CAPABILITIESの拡張（脳アーキテクチャ）

**Before:**
```python
# main.py - SYSTEM_CAPABILITIES
"query_knowledge": {
    "name": "会社知識の参照",
    ...
}

# decision.py - 別途定義（重複！）
CAPABILITY_KEYWORDS = {
    "query_knowledge": {
        "primary": ["ナレッジ検索"],
        ...
    }
}

# understanding.py - さらに別途定義（重複！）
INTENT_KEYWORDS = {
    "query_knowledge": {
        "primary": ["教えて"],
        ...
    }
}
```

**After:**
```python
# main.py - SYSTEM_CAPABILITIES（唯一の定義場所）
"query_knowledge": {
    "name": "会社知識の参照",
    "description": "...",
    "category": "knowledge",
    "enabled": True,
    # ★ 脳用メタデータを統合
    "brain_metadata": {
        "decision_keywords": {
            "primary": ["ナレッジ検索", "知識を教えて"],
            "secondary": ["どうやって", "方法"],
            "negative": ["追加", "忘れて"],
        },
        "intent_keywords": {
            "primary": ["教えて", "知りたい"],
            "secondary": ["就業規則", "ルール"],
            "modifiers": [],
            "confidence_boost": 0.8,
        },
        "risk_level": "low",
        "priority": 5,
    },
    ...
}

# decision.py - 動的に取得
class BrainDecision:
    def __init__(self, capabilities: dict, ...):
        # SYSTEM_CAPABILITIESから動的に構築
        self.capability_keywords = {
            key: cap.get("brain_metadata", {}).get("decision_keywords", {})
            for key, cap in capabilities.items()
            if cap.get("enabled", True)
        }
```

### 2.3 Phase C: Feature Flagの集約

**Before:**
```python
# chatwork-webhook/main.py（15個が散在）
_USE_NEW_MEMORY_HANDLER_ENV = os.environ.get("USE_NEW_MEMORY_HANDLER", "true").lower() == "true"
_USE_NEW_TASK_HANDLER_ENV = os.environ.get("USE_NEW_TASK_HANDLER", "true").lower() == "true"
...
```

**After:**
```python
# lib/feature_flags.py（新規）
from dataclasses import dataclass
import os

@dataclass
class FeatureFlags:
    """Feature Flagを一元管理"""

    # ハンドラー系
    use_memory_handler: bool = True
    use_task_handler: bool = True
    use_overdue_handler: bool = True
    use_goal_handler: bool = True
    use_knowledge_handler: bool = True
    use_proposal_handler: bool = True
    use_announcement_handler: bool = True

    # 脳アーキテクチャ
    use_brain_architecture: bool = True
    brain_fallback_enabled: bool = True

    # 検出機能
    use_pattern_detection: bool = True
    use_emotion_detection: bool = True

    @classmethod
    def from_env(cls) -> "FeatureFlags":
        """環境変数から読み込み"""
        return cls(
            use_memory_handler=os.getenv("USE_MEMORY_HANDLER", "true").lower() == "true",
            use_task_handler=os.getenv("USE_TASK_HANDLER", "true").lower() == "true",
            # ...
        )

# 使用例
flags = FeatureFlags.from_env()
if flags.use_brain_architecture:
    ...
```

### 2.4 Phase D: 接続設定の集約

**Before:**
```python
# 7ファイルに同じ文字列
INSTANCE_CONNECTION_NAME = "soulkun-production:asia-northeast1:soulkun-db"
```

**After:**
```python
# lib/config.py（既存）を活用
from lib.config import get_settings

settings = get_settings()
pool = create_engine(
    f"postgresql+pg8000://{settings.DB_USER}:{settings.DB_PASSWORD}@/{settings.DB_NAME}",
    connect_args={"unix_sock": f"/cloudsql/{settings.INSTANCE_CONNECTION_NAME}/.s.PGSQL.5432"}
)
```

---

## 3. 実装計画

### 3.1 タイムライン

| Phase | 内容 | 工数 | 優先度 |
|-------|------|------|--------|
| A | 管理者設定のDB化 | 2時間 | ★★★ |
| B | SYSTEM_CAPABILITIES拡張 | 3時間 | ★★★ |
| C | Feature Flag集約 | 1時間 | ★★☆ |
| D | 接続設定集約 | 1時間 | ★★☆ |
| E | バリデーション追加 | 1時間 | ★★☆ |
| F | テスト・検証 | 2時間 | ★★★ |
| **合計** | - | **10時間** | - |

### 3.2 Phase A: 管理者設定のDB化（詳細）

1. **DBマイグレーション作成**
   - `organization_admin_configs` テーブル作成
   - 初期データ投入

2. **lib/admin_config.py 新規作成**
   - `get_admin_config(org_id)` 関数
   - キャッシュ機構（TTL=1時間）

3. **既存コード置換**（10+ファイル）
   - `ADMIN_ACCOUNT_ID` → `get_admin_config(org_id)["admin_account_id"]`
   - `ADMIN_ROOM_ID` → `get_admin_config(org_id)["admin_room_id"]`

4. **テスト追加**
   - DB接続モック
   - フォールバック動作確認

### 3.3 Phase B: SYSTEM_CAPABILITIES拡張（詳細）

1. **SYSTEM_CAPABILITIES拡張**
   - 全19アクションに `brain_metadata` 追加
   - 既存の CAPABILITY_KEYWORDS / INTENT_KEYWORDS の内容をコピー

2. **decision.py 修正**
   - `_build_capability_keywords()` メソッド追加
   - `CAPABILITY_KEYWORDS` 定数を削除

3. **understanding.py 修正**
   - `_build_intent_keywords()` メソッド追加
   - `INTENT_KEYWORDS` 定数を削除

4. **バリデーション追加**
   - `validate_capabilities_handlers()` 関数
   - 起動時に整合性チェック

---

## 4. リファクタリング後の機能追加フロー

### Before（5箇所更新が必要）

```
新機能追加時:
1. SYSTEM_CAPABILITIES にアクション定義追加
2. handlers 辞書にハンドラー関数追加
3. CAPABILITY_KEYWORDS にキーワード追加
4. INTENT_KEYWORDS にキーワード追加
5. (場合により) 管理者IDハードコード
```

### After（2箇所のみ）

```
新機能追加時:
1. SYSTEM_CAPABILITIES にアクション定義追加（brain_metadata含む）
2. handlers 辞書にハンドラー関数追加

以上！
```

---

## 5. 検証チェックリスト

### Phase A（未実施）
- [ ] organization_admin_configs テーブル作成
- [ ] lib/admin_config.py 実装
- [ ] 10+ファイルの ADMIN_* 置換

### Phase B（v10.30.0 完了 ✅）
- [x] SYSTEM_CAPABILITIES に brain_metadata 追加（18アクション）
- [x] decision.py の CAPABILITY_KEYWORDS 動的化
- [x] understanding.py の INTENT_KEYWORDS 動的化
- [x] validate_capabilities_handlers() 実装
- [x] lib/brain/validation.py 新規作成（25件テスト）
- [x] 後方互換性維持（capabilities未指定時はフォールバック）
- [x] 全1822件テストパス

### Phase C（v10.31.0 完了 ✅）
- [x] lib/feature_flags.py 実装（525行）
- [x] FeatureFlagsクラス（22フラグ対応）
- [x] 5カテゴリ分類（handler, library, feature, detection, infra）
- [x] 環境変数読み込み（from_env）
- [x] インポート結果設定（set_import_result）
- [x] ヘルパー関数（is_handler_enabled等）
- [x] シングルトンパターン（get_flags）
- [x] 92件のユニットテスト（全パス）
- [x] 6つのCloud Functionsにコピー

### Phase D（未実施）
- [ ] 接続設定集約
- [ ] 本番環境動作確認

---

## 6. 将来の拡張性

このリファクタリング後：

| 観点 | Before | After |
|------|--------|-------|
| 新機能追加 | 5箇所更新 | 2箇所のみ |
| 管理者変更 | 10+ファイル修正 | DB1行更新 |
| マルチテナント | 対応不可 | 対応可能 |
| Feature Flag | 散在 | 一元管理 |
| 設計書準拠 | 60% | 95% |

---

## 7. リスクと対策

| リスク | 対策 |
|--------|------|
| 大規模変更による不具合 | Feature Flagで段階的有効化 |
| DB接続エラー | フォールバック値を維持 |
| テスト漏れ | CI/CDで整合性チェック自動化 |

---

## 8. 推奨

**今すぐ実施することを強く推奨します。**

理由：
1. 設計書の思想「カタログ追加のみ」に忠実になる
2. Phase 4マルチテナント対応の前提条件
3. 同種の不整合が二度と発生しなくなる
4. 保守性が大幅に向上

v10.29.9は応急処置。この技術的負債は早めに返済すべき。
