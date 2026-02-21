# brain_decision_logs / ai_usage_logs 0件バグ修正 レビュー結果 (2026-02-21)

## 対象ファイル
- `lib/brain/learning.py` — log_decision() の None チェック追加
- `lib/brain/graph/nodes/responses.py` — text_response ノードに判断ログ追加
- `lib/brain/graph/nodes/llm_inference.py` — ai_usage_logs 記録追加

## 3コピー同期 (PASS)
- 全3ファイルの chatwork-webhook/lib/ と proactive-monitor/lib/ が IDENTICAL。

## learning.py の None チェック — WARNING 残存バグ

### 変更箇所 (line 418-421)
```python
_intent = understanding.intent if understanding is not None else "llm_brain"
_conf = understanding.intent_confidence if understanding is not None else (decision.confidence if decision else 0.0)
_entities = understanding.entities if understanding is not None else {}
```
これは正しい。

### REMAINING BUG (WARNING): line 449-453 デバッグログが None チェックを通らない
```python
logger.debug(
    f"Decision logged: intent={understanding.intent}, "  # ← understanding=None でAttributeError
    ...
)
```
- `understanding=None` のとき AttributeError が発生する
- ただし `except Exception as e` (line 458) が catch → `logger.warning(f"Error logging decision: {type(e).__name__}")` して return False
- バッファへの append (line 443) は既に完了しているため、ログエントリ自体は消失しない（次回フラッシュで記録される）
- したがって WARNING レベル（データ消失ではなく、エラーログが誤解を招く + return False が誤り）

### 型アノテーション不整合 (SUGGESTION)
- `log_decision_safely(understanding: UnderstandingResult, ...)` — Optional ではない
- 実際は None が渡されることがある。`Optional[UnderstandingResult]` に変更すべき
- `memory_manager.py:96` と `learning.py:388` の両方

## responses.py の text_response ログ追加 — PASS

### 検証した内容
- `_fire_and_forget` は `brain._fire_and_forget()` を使用 — `SoulkunBrain._fire_and_forget` (initialization.py:269) が参照保持+エラーコールバック実装済み。PASS (#19 fire-and-forget安全性)
- `_extract_confidence_value(llm_result.confidence, ...)` — `llm_result.confidence` は `ConfidenceScores` オブジェクト。`_extract_confidence_value` は `.overall` 属性を処理する。PASS
- `DecisionResult.confidence: float` — 既に float 型。`understanding_confidence` へ渡すキャストも問題なし
- `SAVE_DECISION_LOGS = True` (constants.py:572) — 定数確認済み
- `None` を understanding として渡す → learning.py が None チェックして処理 (WARNING の debug log bug を除けばバッファには入る)

### SUGGESTION: text_response でも build_response と同様に decision を state に保存しない
- `build_response` では `state.get("decision")` で取得しているが、text_response では新規で `DecisionResult` を生成している
- 一貫性のために state["decision"] に保存してから `log_decision_safely` を呼ぶ方が良い（SUGGESTION のみ）

## llm_inference.py の ai_usage_logs 追加 — PASS

### 検証した内容
- `UsageLogger.log_usage()` は同期関数で `self._pool.connect()` を使用 (usage_logger.py:189)
- `_sync()` 内でインスタンス化して呼び出し → `asyncio.to_thread(_sync)` でオフロード → PASS (#6 asyncブロッキング)
- `brain._fire_and_forget()` 使用 → 参照保持+エラーコールバック実装済み → PASS (#19)
- org_id は `brain.org_id` を直接渡す → `UsageLogger.__init__(organization_id=org_id)` → INSERT に `CAST(:org_id AS uuid)` あり → PASS (#5 org_idフィルタ)
- エラーは `type(e).__name__` のみログ → PASS (#8 PII漏洩なし)
- `Decimal("0")` を cost_jpy として渡す → usage_logger.py:197 `float(cost_jpy)` に変換 → PASS

### SUGGESTION: TODO コメントの実コスト計算
- `cost_jpy=Decimal("0")` — 常に0円で記録される
- TODO コメントはあるが、実コスト計算なしでは ai_usage_logs の cost_jpy が意味をなさない
- model_orchestrator 統合後に要修正

### 検証: llm_result.input_tokens / output_tokens の型
- `LLMBrainResult.input_tokens: int = 0` (llm_brain.py:213)
- `LLMBrainResult.output_tokens: int = 0` (llm_brain.py:214)
- ともに int 型。`UsageLogger.log_usage(input_tokens: int, output_tokens: int)` の引数型と一致。PASS

### latency_ms=0 の問題
- `latency_ms=0` で常に固定。LLM 推論の実レイテンシ（`time.time() - t0` が llm_inference.py:67 で計算済み）を渡していない
- SUGGESTION: `latency_ms=int((time.time() - t0) * 1000)` を渡すべき。ただし `t0` は現在のスコープでは `_log_llm_usage` に渡されていないため、リファクタリングが必要

## 重要発見: log_decision_safely の型アノテーション
- `memory_manager.py:96`: `understanding: UnderstandingResult` (Optional なし)
- `learning.py:388`: `understanding: UnderstandingResult` (Optional なし)
- 実際には None が渡される → mypy が --strict モードで型エラーを出す可能性
- 将来的に `Optional[UnderstandingResult]` に修正すべき

## 総合判定
- CRITICAL: なし（データ消失・セキュリティ・Brain architecture 違反なし）
- WARNING: learning.py:450 の debug log で understanding=None 時 AttributeError → return False（バッファ entry は保持されるが誤解を招く）
- SUGGESTION: latency_ms=0 固定、Optional 型アノテーション、cost_jpy=0 固定
