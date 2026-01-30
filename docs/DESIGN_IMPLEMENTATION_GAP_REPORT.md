# 設計と実装の差分レポート

**調査日:** 2026-01-30
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
| Context Builder | 30% | 🔴 高 | LLMContext未実装 |
| **LLM Brain** | **15%** | **🔴 最高** | **設計の核心が未実装** |
| Guardian Layer | 70% | 🟡 中 | LLM連携が不完全 |
| Authorization Gate | 80% | 🟢 低 | ほぼ完成 |
| Observability | 60% | 🟡 中 | DB永続化未実装 |
| Tool Executor | 50% | 🟡 中 | Function Calling未対応 |

**根本的な問題:** 設計は「LLM常駐型」だが、実装は「キーワードマッチ + LLMフォールバック型」のまま。

---

## 1. Context Builder層（実装度: 30%）

### 設計書の定義（25章 5.1）

```
役割: LLM Brainに渡すコンテキストを構築
入力: ユーザーメッセージ、セッション状態
出力: 構造化されたLLMContext
```

### 実装の現状

| 項目 | 設計 | 実装 | 差分 |
|------|------|------|------|
| ContextBuilderクラス | 必須 | ❌ 未実装 | `_get_context()`で代用 |
| LLMContext構造体 | 定義済み | ❌ 未実装 | BrainContextで代用 |
| Truth順位の厳密適用 | 必須 | ⚠️ コメントのみ | 実装されていない |
| 並列データ取得 | 推奨 | ❌ 未実装 | 順次取得 |

### 実装場所

```
proactive-monitor/lib/brain/
├── memory_access.py   ← BrainMemoryAccess（部分実装）
├── state_manager.py   ← BrainStateManager（部分実装）
└── core.py            ← _get_context()（部分実装）
```

### 対応タスク

| # | タスク | 優先度 |
|---|--------|--------|
| C-1 | LLMContext データ構造を定義 | 高 |
| C-2 | ContextBuilder クラスを実装 | 高 |
| C-3 | Truth順位を厳密に実装 | 中 |

---

## 2. LLM Brain層（実装度: 15%）🔴 最重要

### 設計書の定義（25章 5.2）

```
役割: Claude Opus 4.5が常駐し、全ての判断を行う
入力: System Prompt、Context、メッセージ、Tool定義
出力: tool_calls、text_response、reasoning、confidence
```

### 実装の現状

| 項目 | 設計 | 実装 | 差分 |
|------|------|------|------|
| LLMBrainクラス | 必須 | ❌ 未実装 | BrainUnderstanding + BrainDecision |
| Claude API連携 | 必須 | ❌ 未実装 | キーワードマッチが主 |
| Function Calling | 必須 | ❌ 未実装 | 手動でTool選択 |
| Chain-of-Thought | 必須 | ⚠️ 条件付き | 常時ではない |
| Confidence抽出 | 必須 | ⚠️ 不正確 | キーワード確信度で代用 |

### 現在のアーキテクチャ（問題点）

```
現在の実装:
ユーザー入力
    ↓
キーワードマッチ（INTENT_KEYWORDS）
    ↓
確信度 < 0.7 の場合のみ → LLM呼び出し（フォールバック）
    ↓
手動でTool選択

設計（目標）:
ユーザー入力
    ↓
LLM Brain（Claude Opus 4.5）← 常時LLMが判断
    ↓
Function Calling（LLMがTool選択）
    ↓
Tool実行
```

### 実装場所

```
proactive-monitor/lib/brain/
├── understanding.py   ← キーワードマッチ（設計と不一致）
├── decision.py        ← 判断ロジック（LLM非依存）
└── core.py            ← メイン処理
```

### 対応タスク

| # | タスク | 優先度 |
|---|--------|--------|
| **B-1** | **LLMBrainクラスを実装** | **最高** |
| B-2 | Claude API連携（Function Calling形式） | 最高 |
| B-3 | Tool定義をAnthropic形式に変換 | 高 |
| B-4 | System Prompt構築ロジック | 高 |
| B-5 | Chain-of-Thought必須化 | 中 |

---

## 3. Guardian Layer（実装度: 70%）

### 設計書の定義（25章 5.3）

```
役割: LLM判断後のリスク検査
出力: ALLOW / CONFIRM / BLOCK / MODIFY
```

### 実装の現状

| 項目 | 設計 | 実装 | 差分 |
|------|------|------|------|
| GuardianService | 必須 | ✅ 実装済み | `guardian.py` |
| 危険操作検出 | 必須 | ✅ 実装済み | |
| 確信度チェック | 必須 | ✅ 実装済み | |
| CEO教え検証 | 必須 | ✅ 実装済み | |
| LLM出力との連携 | 必須 | ❌ 未実装 | LLMが常駐していないため |

### 実装場所

```
proactive-monitor/lib/brain/
└── guardian.py   ← GuardianService（実装済み、LLM連携待ち）
```

### 対応タスク

| # | タスク | 優先度 |
|---|--------|--------|
| G-1 | LLMBrain実装後にGuardian連携を追加 | 中（B-1完了後） |

---

## 4. Authorization Gate（実装度: 80%）

### 設計書の定義（25章 5.4）

```
役割: LLMと完全に独立した権限検証
チェック: Tool実行権限、データアクセス権限、6段階権限レベル
```

### 実装の現状

| 項目 | 設計 | 実装 | 差分 |
|------|------|------|------|
| AuthorizationGate | 必須 | ✅ 実装済み | `authorization_gate.py` |
| AccessControlService | 必須 | ✅ 実装済み | `api/app/services/access_control.py` |
| 6段階権限レベル | 必須 | ✅ 実装済み | |
| LLMとの独立性 | 必須 | ✅ 確保済み | |
| Tool別権限定義 | 推奨 | ⚠️ 不完全 | TOOL_REQUIRED_LEVELSが未定義 |

### 実装場所

```
proactive-monitor/lib/brain/
└── authorization_gate.py   ← AuthorizationGate（ほぼ完成）

api/app/services/
└── access_control.py       ← AccessControlService（完成）
```

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

| 項目 | 設計 | 実装 | 差分 |
|------|------|------|------|
| BrainObservability | 必須 | ✅ 実装済み | `observability.py` |
| Cloud Logging | 必須 | ✅ 実装済み | |
| 判断ログ記録 | 必須 | ⚠️ 部分的 | Guardian/AuthGate判定が不足 |
| Self-Critique | 推奨 | ✅ 実装済み | `self_critique.py` |
| DB永続化 | 必須 | ❌ 未実装 | Cloud Loggingのみ |

### 実装場所

```
proactive-monitor/lib/brain/
├── observability.py    ← BrainObservability（部分実装）
└── self_critique.py    ← SelfCritique（実装済み）
```

### 対応タスク

| # | タスク | 優先度 |
|---|--------|--------|
| O-1 | brain_decision_logsテーブルを設計 | 中 |
| O-2 | DB永続化を実装 | 中 |
| O-3 | Guardian/AuthGate判定の記録を追加 | 低 |

---

## 6. Tool Execution層（実装度: 50%）

### 設計書の定義（25章 5.6）

```
役割: Function Callingで選択されたToolを実行
入力: ToolCall（name, parameters）
出力: ToolExecutionResult
```

### 実装の現状

| 項目 | 設計 | 実装 | 差分 |
|------|------|------|------|
| ToolExecutorクラス | 推奨 | ❌ 未実装 | BrainExecutionで代用 |
| ハンドラー実行 | 必須 | ✅ 実装済み | `execution.py` |
| パラメータ変換 | 必須 | ⚠️ 分散 | 統一レイヤーなし |
| Tool定義 | 必須 | ❌ 未実装 | SYSTEM_CAPABILITIESで代用 |

### 対応タスク

| # | タスク | 優先度 |
|---|--------|--------|
| T-1 | Tool定義をAnthropic形式に変換 | 高（B-3と同時） |
| T-2 | パラメータ変換を一元化 | 低 |

---

## 優先実装ロードマップ

### Phase 1: LLM常駐化（最優先）

```
Week 1-2:
├── B-1: LLMBrainクラス実装
├── B-2: Claude API連携（Function Calling）
├── C-1: LLMContext定義
└── C-2: ContextBuilder実装

成果物: LLMが全ての判断を行う状態
```

### Phase 2: 統合・検証

```
Week 3-4:
├── B-3/T-1: Tool定義のAnthropic形式化
├── B-4: System Prompt構築
├── G-1: Guardian層のLLM連携
└── O-1/O-2: Observability永続化

成果物: 設計通りの6層アーキテクチャ
```

### Phase 3: 最適化

```
Week 5-6:
├── C-3: Truth順位の厳密実装
├── B-5: Chain-of-Thought必須化
├── A-1: Tool別権限定義
└── テスト・ドキュメント整備

成果物: 本番運用可能な状態
```

---

## 差分チェックリスト

PRレビュー時に以下を確認：

```
□ LLMBrainクラスが実装されているか？
□ Function Calling形式でToolが呼び出されているか？
□ キーワードマッチがフォールバックに降格されているか？
□ LLMContextが使用されているか？
□ Observabilityログに全判断が記録されているか？
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

---

**このファイルについての質問は、Tech Leadに連絡してください。**
