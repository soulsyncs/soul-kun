# 設計と実装の差分レポート

**調査日:** 2026-01-31（v10.53.2更新）
**目的:** 25章（LLM常駐型脳アーキテクチャ）と実際のコードの差分を明確化し、対応優先度を決定する

---

## Document Contract（SoT宣言）

| 項目 | 内容 |
|------|------|
| **この文書の役割** | 設計書と実装コードの差分を一覧化し、対応を追跡 |
| **書くこと** | 各層の差分、対応優先度、実装タスク |
| **書かないこと** | 設計の詳細（→25章）、コードの詳細（→ソースコード） |
| **SoT（この文書が正）** | 設計vs実装の差分状況、対応優先度 |
| **Owner** | Tech Lead（連絡先: #dev チャンネル） |
| **更新トリガー** | 差分解消時、新たな差分発見時 |

---

## エグゼクティブサマリー

| 層 | 実装度 | 深刻度 | 状態 |
|---|--------|--------|------|
| Context Builder | **100%** | ✅ 完了 | LLMContext実装済み |
| **LLM Brain** | **100%** | ✅ 完了 | **設計の核心が実装完了** |
| Guardian Layer | **100%** | ✅ 完了 | LLM連携実装済み |
| Authorization Gate | **100%** | ✅ 完了 | 完成 |
| Observability | 60% | 🟡 中 | DB永続化未実装 |
| Tool Executor | 70% | 🟡 中 | 一部手動のまま |

**現状:** 設計の核心「LLM常駐型」アーキテクチャは**実装完了**。USE_BRAIN_ARCHITECTURE=true で本番稼働中。

---

## 1. Context Builder層（実装度: 100% ✅）

### 設計書の定義（25章 5.1）

```
役割: LLM Brainに渡すコンテキストを構築
入力: ユーザーメッセージ、セッション状態
出力: 構造化されたLLMContext
```

### 実装の現状

| 項目 | 設計 | 実装 | 状態 |
|------|------|------|------|
| ContextBuilderクラス | 必須 | ✅ 実装済み | `context_builder.py` |
| LLMContext構造体 | 定義済み | ✅ 実装済み | Message, UserPreferences等 |
| Truth順位の厳密適用 | 必須 | ✅ 実装済み | 並列取得で実装 |
| 並列データ取得 | 推奨 | ✅ 実装済み | asyncio.gather使用 |

### 実装場所

```
lib/brain/
├── context_builder.py   ← LLMContextBuilder（686行）
└── models.py            ← LLMContext, Message等のデータクラス
```

### 対応タスク

なし（完了）

---

## 2. LLM Brain層（実装度: 100% ✅）

### 設計書の定義（25章 5.2）

```
役割: OpenRouter 経由の `openai/gpt-5.2` が常駐し、全ての判断を行う
入力: System Prompt、Context、メッセージ、Tool定義
出力: tool_calls、text_response、reasoning、confidence
```

### 実装の現状

| 項目 | 設計 | 実装 | 状態 |
|------|------|------|------|
| LLMBrainクラス | 必須 | ✅ 実装済み | `llm_brain.py`（1,249行） |
| Claude API連携 | 必須 | ✅ 実装済み | OpenRouter/Anthropic両対応 |
| Function Calling | 必須 | ✅ 実装済み | `tool_converter.py` |
| Chain-of-Thought | 必須 | ✅ 実装済み | System Promptで強制 |
| Confidence抽出 | 必須 | ✅ 実装済み | ConfidenceScores管理 |

### 現在のアーキテクチャ（設計通り）

```
ユーザー入力
    ↓
Context Builder（LLMContext構築）
    ↓
LLM Brain（GPT-5.2 / Claude）← 常時LLMが判断
    ↓
Function Calling（LLMがTool選択）
    ↓
Guardian Layer（リスク検査）
    ↓
Tool実行
```

### 実装場所

```
lib/brain/
├── llm_brain.py         ← LLMBrain（1,249行）
├── context_builder.py   ← LLMContextBuilder（686行）
├── tool_converter.py    ← Tool定義変換
└── core.py              ← _process_with_llm_brain()統合
```

### 対応タスク

なし（完了）

---

## 3. Guardian Layer（実装度: 100% ✅）

### 設計書の定義（25章 5.3）

```
役割: LLM判断後のリスク検査
出力: ALLOW / CONFIRM / BLOCK / MODIFY
```

### 実装の現状

| 項目 | 設計 | 実装 | 状態 |
|------|------|------|------|
| GuardianLayerクラス | 必須 | ✅ 実装済み | `guardian_layer.py`（522行） |
| 危険操作検出 | 必須 | ✅ 実装済み | DANGEROUS_OPERATIONS |
| 確信度チェック | 必須 | ✅ 実装済み | 0.3中止、0.7確認 |
| CEO教え検証 | 必須 | ✅ 実装済み | 基本チェック実装 |
| LLM出力との連携 | 必須 | ✅ 実装済み | async check()メソッド |

### 実装場所

```
lib/brain/
├── guardian_layer.py    ← GuardianLayer（522行）
└── guardian.py          ← GuardianService（レガシー）
```

### 対応タスク

| # | タスク | 優先度 |
|---|--------|--------|
| G-1 | CEO教え違反検出の詳細化（TODO注記あり） | 低 |

---

## 4. Authorization Gate（実装度: 100% ✅）

### 設計書の定義（25章 5.4）

```
役割: LLMと完全に独立した権限検証
チェック: Tool実行権限、データアクセス権限、6段階権限レベル
```

### 実装の現状

| 項目 | 設計 | 実装 | 状態 |
|------|------|------|------|
| AuthorizationGate | 必須 | ✅ 実装済み | `authorization_gate.py` |
| AccessControlService | 必須 | ✅ 実装済み | `api/app/services/access_control.py` |
| 6段階権限レベル | 必須 | ✅ 実装済み | |
| LLMとの独立性 | 必須 | ✅ 確保済み | |
| Tool別権限定義 | 推奨 | ⚠️ 不完全 | TOOL_REQUIRED_LEVELSが未定義 |

### 対応タスク

| # | タスク | 優先度 |
|---|--------|--------|
| A-1 | TOOL_REQUIRED_LEVELSを定義 | 低 |

---

## 5. Observability Layer（実装度: 60%）

### 設計書の定義（25章 5.5）

```
役割: 全判断を記録し追跡可能に
記録: 入力、Context、思考過程、Guardian判定、実行結果
```

### 実装の現状

| 項目 | 設計 | 実装 | 状態 |
|------|------|------|------|
| BrainObservability | 必須 | ✅ 実装済み | `observability.py` |
| Cloud Logging | 必須 | ✅ 実装済み | |
| 判断ログ記録 | 必須 | ✅ 実装済み | Guardian/AuthGate判定含む |
| Self-Critique | 推奨 | ✅ 実装済み | `self_critique.py` |
| DB永続化 | 必須 | ❌ 未実装 | Cloud Loggingのみ |

### 対応タスク

| # | タスク | 優先度 |
|---|--------|--------|
| O-1 | brain_decision_logsテーブルを設計 | 低 |
| O-2 | DB永続化を実装 | 低 |

---

## 6. Tool Execution層（実装度: 70%）

### 設計書の定義（25章 5.6）

```
役割: Function Callingで選択されたToolを実行
入力: ToolCall（name, parameters）
出力: ToolExecutionResult
```

### 実装の現状

| 項目 | 設計 | 実装 | 状態 |
|------|------|------|------|
| ToolExecutorクラス | 推奨 | ⚠️ 部分的 | BrainExecutionで代用 |
| ハンドラー実行 | 必須 | ✅ 実装済み | `execution.py` |
| パラメータ変換 | 必須 | ✅ 実装済み | `tool_converter.py` |
| Tool定義 | 必須 | ✅ 実装済み | Anthropic形式対応 |

### 対応タスク

| # | タスク | 優先度 |
|---|--------|--------|
| T-1 | ToolExecutorクラスの分離（推奨） | 低 |

---

## 残存タスク一覧

### 高優先度（本番品質向上）

| # | タスク | 見積 | 状態 |
|---|--------|------|------|
| **TEST-1** | **Advanced Judgmentテスト追加** | 4h | 🔄 進行中（2026-02-22マスタープランに計上） |
| **TEST-2** | **Agentsテスト追加** | 4h | 🔄 進行中（2026-02-22マスタープランに計上） |
| **TEST-3** | **CEO Learningテスト追加** | 2h | 🔄 進行中（2026-02-22マスタープランに計上） |
| **TEST-4** | **プロンプト回帰テスト（Promptfoo拡充）** | 6h | 🔄 進行中（Promptfoo CI稼働中・テストケース拡充中） |

### 低優先度（便宜的改善）

| # | タスク | 見積 | 状態 |
|---|--------|------|------|
| O-1/O-2 | Observability DB永続化 | 4h | ❌ 未着手 |
| T-1 | Tool Executorクラス分離 | 2h | ❌ 未着手 |
| A-1 | TOOL_REQUIRED_LEVELS定義 | 1h | ❌ 未着手 |
| G-1 | CEO教え検出詳細化 | 3h | ❌ 未着手 |

---

## 差分チェックリスト（PRレビュー用）

```
✅ LLMBrainクラスが実装されているか？ → 完了
✅ Function Calling形式でToolが呼び出されているか？ → 完了
✅ キーワードマッチがフォールバックに降格されているか？ → 完了
✅ LLMContextが使用されているか？ → 完了
✅ Observabilityログに全判断が記録されているか？ → 完了（DB永続化除く）
```

---

## 関連ドキュメント

| ドキュメント | 参照セクション |
|-------------|---------------|
| 25章（設計詳細） | 第5章（アーキテクチャ全体像） |
| CLAUDE.md | セクション2（脳の鉄則） |
| 04章 | セクション5.6（権限実装） |
| Design Coverage Matrix | Authorization Gate行 |

---

## 更新履歴

| 日付 | 変更内容 |
|------|---------|
| 2026-01-30 | 初版作成（全層の差分調査完了） |
| **2026-01-31** | **v10.53.2: LLM Brain実装完了に伴い全面更新** |
| **2026-02-08** | **コード監査: セキュリティ課題（org_id 114箇所、RLS 52テーブル不足、API認証0件、ILIKE脆弱性）を別途ロードマップ計画で対応。本レポートの脳アーキテクチャ差分は変更なし。** |
| **2026-02-22** | **3AI合議による総点検: LangGraph 12ノード完了（11→12に修正）、Langfuse本番稼働確認、LangGraphノードテスト71→88件完了、Promptfoo CI稼働中（週次+PR時）、Terraform CI稼働中（PR時差分表示）。TEST-1〜4を進行中ステータスに更新。** |

---

**このファイルについての質問は、Tech Leadに連絡してください。**
