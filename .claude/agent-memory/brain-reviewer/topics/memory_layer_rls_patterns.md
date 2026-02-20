# memory_layer.py / context_builder.py RLS パターンメモ

## タスクE レビュー (2026-02-21) — 最終レビュー完了

### 変更1: memory_layer.py
- `lib/brain/core/memory_layer.py` line 187: `self.pool.connect()` → `self.learning._connect_with_org_context()`
- 修正理由: `brain_learnings` テーブルはRLS有効。`self.pool.connect()` では `app.current_organization_id` が設定されない → RLSが全行を隠す → `find_applicable()` が常に空返却
- **RLSクリアは `_connect_with_org_context()` の `finally` ブロックで保証（learning.py line 287-288）**

### 変更2: context_builder.py `_fetch_all_db_data()`
- line 537-539: `pool.connect()` の直後に `set_config(org_id)` を追加
- line 850-856: 9クエリ完了後、`with` ブロック内の最後で `set_config(NULL)` でクリア
- **WARNING: クリアが `try/except pass` の中 かつ `with` ブロックの通常終了パスにのみある**
  - クエリ途中で例外 → `except Exception as e: logger.warning(...)` (line 858) → クリア到達しない → 接続プールにRLSコンテキスト付きで返却
  - `with pool.connect() as conn:` 自体の例外 → 同様
  - **推奨: `with` ブロックの `finally` パターンへ変更、または `try/finally` でクリアを保証**

### BrainLearning._connect_with_org_context() シグネチャ
- `lib/brain/learning.py` line 266 に定義
- 引数なし（`self.org_id` を使う）
- `@contextmanager` デコレータ（同期）
- 内部で `set_config('app.current_organization_id', :org_id, false)` を実行
- finally で `set_config(..., NULL, false)` をクリア（safety保証あり）
- `self.org_id` は `__init__` で `org_id: str = ""` → デフォルト空文字列（None にはならない）

### 残存RLS漏れ（タスクEスコープ外）
- `lib/brain/context_builder.py` line 1106: `_get_phase2e_learnings()` メソッド内の `_sync_fetch()` が `self.pool.connect()` を使用している（RLS設定なし）
  - ただし現在 `build()` から呼ばれていない（gather に含まれていない）— 未使用メソッド
  - 将来有効化されたときに問題になる。WARNING レベル

### 3コピー同期状況 (確認済み)
- lib/, chatwork-webhook/lib/, proactive-monitor/lib/ の両ファイル、diff 空（同期済み）

### テストカバレッジ
- `MemoryLayerMixin._get_context()` のユニットテストは存在しない（tests/test_memory_layer.py なし）
- SUGGESTION レベル（既存テスト不在は pre-existing）
