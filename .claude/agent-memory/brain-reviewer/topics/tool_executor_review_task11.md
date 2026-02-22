# TASK-11: ToolExecutor分離レビュー (2026-02-22)

## 変更概要
- 新規: `lib/brain/tool_executor.py` (ToolExecutor + ToolExecutionOutcome)
- 変更: `lib/brain/graph/nodes/execute_tool.py` (ToolExecutor呼び出しに切替)
- 3コピー同期: PASS (lib/ chatwork-webhook/lib/ proactive-monitor/lib/ 全一致)

## 重要な型不整合（WARNING）

`ToolExecutionOutcome.result` の型アノテーションが `ExecutionResult` (lib/brain/execution.py のデータクラス) だが、
実際に `brain._execute()` が返すのは `HandlerResult` (lib/brain/models.py のデータクラス)。

- `core/pipeline.py` line 96: `async def _execute(...) -> HandlerResult:`
- `state.py` line 49: `execution_result: Any  # HandlerResult` (コメントでもHandlerResultと明記)
- `tool_executor.py` line 41: `result: ExecutionResult` (Wrong — should be HandlerResult or Any)

ただし、Python は dataclass フィールドの型を実行時には強制しないため、実動作は正常。
テストも `brain._execute` を `HandlerResult` を返す AsyncMock でモックしており、テストはPASS。

## 未使用インポート（SUGGESTION）

`tool_executor.py` line 20-21 に不要なインポート:
- `field` (from dataclasses) — ToolExecutionOutcome は field() を使っていない
- `Dict` (from typing) — 使用箇所なし
- `Optional` (from typing) — 使用箇所なし

## テストカバレッジ

`ToolExecutor` クラス自体の直接テストはゼロ。
- 既存の `TestExecuteTool` は `make_execute_tool(brain)` 経由でノードをテストしており、
  ToolExecutor は間接的にしか通らない。
- `brain._execute` をモックしているため ToolExecutor の変換ロジックは実質テストされている。
- ToolExecutor 単体テストがあれば理想的だが、SUGGESTION レベル。

## 設計の正当性

- Brain Architecture 準拠: Brain の `_execute()` に委譲するのみ、判断ロジックなし ✓
- fire-and-forget: 監査ログは execute_tool.py 側の `brain._fire_and_forget()` を使用 ✓
- ToolExecutor は毎回 `ToolExecutor(brain).execute(...)` でインスタンス化 — ステートレスなので問題なし ✓
- `needs_confirmation=False` (line 100): Guardian/ApprovalGate 通過済みの前提 ✓

## 判定: PASS（未使用インポートと型アノテーション修正を推奨）
