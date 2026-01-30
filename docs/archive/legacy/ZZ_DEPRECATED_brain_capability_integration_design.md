> ⚠️ **DEPRECATED - 参照禁止**
>
> このファイルは **`docs/25_llm_native_brain_architecture.md`** に統合されました。
>
> | 統合先 | 25章 第6章「各層の詳細設計」 |
> |--------|---------------------------|
> | 理由 | 脳-機能統合設計の統合 |
> | 日付 | 2026-01-30 |
>
> **👉 参照すべきファイル:** [25章 LLM常駐型脳アーキテクチャ](../25_llm_native_brain_architecture.md)

---

# 脳-機能統合設計書

## 1. 現状分析

### 1.1 脳アーキテクチャ（lib/brain/）

```
SoulkunBrain
├── process_message()          # メインエントリーポイント
├── _get_context()             # BrainContext取得
├── _understand()              # BrainUnderstanding
├── _decide()                  # BrainDecision
├── _execute()                 # BrainExecution
└── _update_memory_safely()    # BrainLearning

BrainContext (models.py)
├── current_state              # ConversationState
├── recent_conversation        # List[ConversationMessage]
├── conversation_summary       # SummaryData
├── user_preferences           # PreferenceData
├── person_info                # List[PersonInfo]
├── recent_tasks               # List[TaskInfo]
├── active_goals               # List[GoalInfo]
├── relevant_knowledge         # List[KnowledgeChunk]
├── insights                   # List[InsightInfo]
├── ceo_teachings              # CEOTeachingContext
└── ❌ multimodal_context      # 未実装
└── ❌ generation_context      # 未実装
```

### 1.2 機能モジュール（lib/capabilities/）

#### Multimodal（目・耳）
```
lib/capabilities/multimodal/
├── brain_integration.py       # ✅ 統合インターフェース実装済み
│   ├── MultimodalBrainContext # ✅ データモデル定義済み
│   ├── process_message_with_multimodal() # ✅ 処理関数定義済み
│   └── handle_chatwork_message_with_attachments() # ✅ 統合関数定義済み
├── coordinator.py             # ✅ 処理コーディネーター
├── image_processor.py         # ✅ 画像処理
├── pdf_processor.py           # ✅ PDF処理
├── url_processor.py           # ✅ URL処理
└── audio_processor.py         # ✅ 音声処理
```
**状態**: 実装済みだが脳から呼び出されていない

#### Generation（手）
```
lib/capabilities/generation/
├── document_generator.py      # ✅ 文書生成
├── image_generator.py         # ✅ 画像生成
├── video_generator.py         # ✅ 動画生成
├── google_docs_client.py      # ✅ Google Docs連携
├── google_sheets_client.py    # ✅ Google Sheets連携
├── google_slides_client.py    # ✅ Google Slides連携
└── ❌ brain_integration.py    # 未実装
```
**状態**: 生成処理は実装済みだが脳統合インターフェースがない

#### Feedback（内省）
```
lib/capabilities/feedback/
├── ceo_feedback_engine.py     # ✅ CEOフィードバックエンジン
├── fact_collector.py          # ✅ ファクト収集
├── analyzer.py                # ✅ 分析
├── delivery.py                # ✅ 配信
└── ❌ brain_integration.py    # 未実装
```
**状態**: proactive-monitorで独立使用、脳との統合なし

---

## 2. 統合設計

### 2.1 設計原則（7つの鉄則準拠）

1. **全ての入力は脳を通る** → 添付ファイルも脳のprocess_message()経由
2. **脳は全ての記憶にアクセスできる** → マルチモーダル結果もBrainContextに含める
3. **脳が判断、機能は実行のみ** → 生成実行は脳の判断後
4. **機能拡張しても脳の構造は変わらない** → コンテキスト拡張のみ
5. **確認は脳の責務** → 生成前に脳が確認判断
6. **状態管理は脳が統一管理** → 生成セッションも状態管理
7. **速度より正確性を優先** → 処理品質を優先

### 2.2 統合レイヤー図

```
┌─────────────────────────────────────────────────────────────────┐
│                        ChatWork Webhook                         │
│  (chatwork-webhook/handlers/message_handler.py)                │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│               Capability Preprocessor Layer                     │
│  (NEW: lib/brain/capability_bridge.py)                         │
│                                                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │  Multimodal │  │  Generation │  │  Feedback   │            │
│  │ Preprocessor│  │  Handler    │  │  Handler    │            │
│  └─────────────┘  └─────────────┘  └─────────────┘            │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                      SoulkunBrain                               │
│                                                                 │
│  BrainContext (Extended)                                        │
│  ├── ... (既存フィールド)                                       │
│  ├── multimodal_context: MultimodalBrainContext                │
│  └── generation_request: GenerationRequest                     │
│                                                                 │
│  process_message()                                              │
│  ├── _get_context() + マルチモーダル情報追加                    │
│  ├── _understand()  + マルチモーダル考慮                        │
│  ├── _decide()      + 生成アクション判断                        │
│  └── _execute()     + 生成ハンドラー呼び出し                    │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│              Capability Execution Layer                         │
│  (lib/capabilities/*)                                          │
│                                                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │  Multimodal │  │  Generation │  │  Feedback   │            │
│  │  Processors │  │  Generators │  │  Engine     │            │
│  └─────────────┘  └─────────────┘  └─────────────┘            │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 データフロー

```
1. 入力フロー（Multimodal）
   ChatWork → 添付ファイル検出 → Multimodal処理 → BrainContext拡張 → 脳処理

2. 出力フロー（Generation）
   脳判断 → 生成アクション選択 → Generationハンドラー実行 → 結果返却

3. 分析フロー（Feedback）
   脳判断 → フィードバック要求検出 → Feedbackエンジン実行 → 結果返却
```

---

## 3. 実装計画

### Phase 1: BrainContext拡張（優先度: 高）

**目的**: BrainContextにマルチモーダル/生成コンテキストを追加

**変更ファイル**:
- `lib/brain/models.py`

**追加フィールド**:
```python
@dataclass
class BrainContext:
    # ... 既存フィールド ...

    # Phase M: マルチモーダルコンテキスト
    multimodal_context: Optional["MultimodalBrainContext"] = None

    # Phase G: 生成リクエスト
    generation_request: Optional["GenerationRequest"] = None

    def has_multimodal_content(self) -> bool:
        """マルチモーダルコンテンツがあるか"""
        return (
            self.multimodal_context is not None
            and self.multimodal_context.has_multimodal_content
        )

    def has_generation_request(self) -> bool:
        """生成リクエストがあるか"""
        return self.generation_request is not None
```

### Phase 2: Capability Bridge作成（優先度: 高）

**目的**: 脳と機能モジュールの橋渡し層を作成

**新規ファイル**:
- `lib/brain/capability_bridge.py`

**主要クラス**:
```python
class CapabilityBridge:
    """
    脳と機能モジュールの橋渡し層

    - 入力前処理（Multimodal）
    - 出力ハンドラー登録（Generation）
    - フィードバック統合（Feedback）
    """

    def __init__(self, pool, org_id: str):
        self.pool = pool
        self.org_id = org_id

        # Multimodal
        self.multimodal_coordinator = MultimodalCoordinator(pool, org_id)

        # Generation
        self.document_generator = DocumentGenerator(...)
        self.image_generator = ImageGenerator(...)

        # Feedback
        self.feedback_engine = CEOFeedbackEngine(...)

    async def preprocess_message(
        self,
        message: str,
        attachments: List[Dict],
        room_id: str,
        user_id: str,
    ) -> Tuple[str, Optional[MultimodalBrainContext]]:
        """メッセージの前処理（マルチモーダル）"""
        ...

    def get_capability_handlers(self) -> Dict[str, Callable]:
        """生成ハンドラーを取得"""
        return {
            "generate_document": self._handle_document_generation,
            "generate_image": self._handle_image_generation,
            "generate_video": self._handle_video_generation,
            "generate_feedback": self._handle_feedback_generation,
        }
```

### Phase 3: Decision Layer拡張（優先度: 中）

**目的**: 判断層に生成アクションを追加

**変更ファイル**:
- `lib/brain/decision.py`
- `chatwork-webhook/handlers/__init__.py` (SYSTEM_CAPABILITIES)

**追加アクション**:
```python
SYSTEM_CAPABILITIES = {
    # ... 既存アクション ...

    # Phase G: Generation capabilities
    "generate_document": {
        "name": "generate_document",
        "description": "文書を生成する",
        "keywords": ["資料作成", "ドキュメント", "レポート作成"],
        "parameters": {
            "document_type": "文書タイプ (report/summary/proposal)",
            "topic": "トピック",
            "outline": "アウトライン（オプション）",
        },
        "requires_confirmation": True,
    },
    "generate_image": {
        "name": "generate_image",
        "description": "画像を生成する",
        "keywords": ["画像作成", "イラスト", "図"],
        "parameters": {
            "prompt": "画像の説明",
            "style": "スタイル（オプション）",
        },
        "requires_confirmation": True,
    },
    # ... その他 ...
}
```

### Phase 4: Execution Layer拡張（優先度: 中）

**目的**: 実行層に生成ハンドラーを統合

**変更ファイル**:
- `lib/brain/execution.py`
- `chatwork-webhook/main.py`

**統合方法**:
```python
# chatwork-webhook/main.py

from lib.brain.capability_bridge import CapabilityBridge

# CapabilityBridgeを初期化
capability_bridge = CapabilityBridge(pool=pool, org_id=org_id)

# ハンドラーを統合
handlers = {
    **existing_handlers,
    **capability_bridge.get_capability_handlers(),
}

# 脳を初期化
brain = SoulkunBrain(
    pool=pool,
    org_id=org_id,
    handlers=handlers,
    capabilities=SYSTEM_CAPABILITIES,
)
```

### Phase 5: ChatWork Handler統合（優先度: 高）

**目的**: ChatWork Webhookでマルチモーダル前処理を呼び出す

**変更ファイル**:
- `chatwork-webhook/main.py`
- `chatwork-webhook/handlers/message_handler.py`（必要に応じて）

**実装**:
```python
async def handle_mention(event, pool, org_id, brain, capability_bridge):
    """メンション付きメッセージの処理"""

    # 1. マルチモーダル前処理
    enriched_message, multimodal_context = await capability_bridge.preprocess_message(
        message=event.body,
        attachments=event.attachments or [],
        room_id=str(event.room_id),
        user_id=str(event.account_id),
    )

    # 2. 脳に渡す（コンテキスト付き）
    response = await brain.process_message(
        message=enriched_message,
        room_id=str(event.room_id),
        account_id=str(event.account_id),
        sender_name=event.account.name,
        multimodal_context=multimodal_context,  # 新パラメータ
    )

    return response.message
```

---

## 4. 実装順序

| 順序 | タスク | 優先度 | 依存関係 | 想定工数 |
|------|--------|--------|----------|----------|
| 1 | BrainContext拡張 | 高 | なし | 小 |
| 2 | CapabilityBridge作成 | 高 | 1 | 中 |
| 3 | ChatWork Handler統合 | 高 | 2 | 中 |
| 4 | 生成ハンドラー追加 | 中 | 2 | 中 |
| 5 | SYSTEM_CAPABILITIES更新 | 中 | 4 | 小 |
| 6 | Feedbackエンジン統合 | 低 | 2 | 中 |
| 7 | テスト追加 | 高 | 全て | 中 |

---

## 5. 検証項目

### 機能テスト
- [ ] 画像添付メッセージが正しく処理される
- [ ] PDF添付メッセージが正しく処理される
- [ ] URL含むメッセージが正しく処理される
- [ ] 「資料作成して」で文書生成ハンドラーが呼ばれる
- [ ] 「画像作成して」で画像生成ハンドラーが呼ばれる
- [ ] 生成アクションで確認が求められる

### 統合テスト
- [ ] 添付ファイル付きメッセージ → マルチモーダル処理 → 脳 → 応答
- [ ] 生成リクエスト → 確認 → 生成実行 → 結果返却

### 非機能テスト
- [ ] エラー時のフォールバック動作
- [ ] タイムアウト処理
- [ ] 大容量ファイル処理

---

## 6. 注意事項

1. **後方互換性**: 既存のメッセージ処理フローを壊さない
2. **フィーチャーフラグ**: 各機能は個別にON/OFF可能にする
3. **エラーハンドリング**: 機能モジュールのエラーは脳が適切にハンドリング
4. **ログ**: 処理フローのログを適切に出力
5. **コスト管理**: 生成機能はコストがかかるため確認必須

---

## 7. 参考ドキュメント

- `docs/13_brain_architecture.md` - 脳アーキテクチャ設計書
- `docs/20_next_generation_capabilities.md` - 次世代能力設計書
- `lib/capabilities/multimodal/brain_integration.py` - 既存のマルチモーダル統合コード
