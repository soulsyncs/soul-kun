# Phase B-2: 監査ログDB永続保存実装 (fix/currency-display-jpy, reviewed 2026-02-19)

## 変更概要
- `lib/audit.py`: `log_audit_async()` に SQLAlchemy AsyncEngine 経由の DB 書き込みを実装
- `lib/audit.py`: `log_drive_permission_change()` の email を `mask_email()` でマスキング
- `lib/audit.py`: `from lib.logging import mask_email` を module-level import に追加
- 4コピー同期済み: lib/, chatwork-webhook/lib/, proactive-monitor/lib/, sync-chatwork-tasks/lib/

## 判定サマリー: WARNING 2件 + SUGGESTION 3件 (CRITICALなし)

## WARNING-1: db_err ログに内部情報リーク (Rule #8)
- `lib/audit.py` line 367: `logger.warning("... %s", db_err)`
- `str(db_err)` には asyncpg 接続エラーメッセージ (ホスト名, ポート, スタックトレース等) が含まれる可能性
- 推奨: `logger.warning("... %s", type(db_err).__name__)` に変更
- 同パターンが line 372 にも存在: `f"⚠️ Audit log failed (non-blocking): {e}"` — pre-existing

## WARNING-2: "batch_N_folders" resource_id がサイレント NULL 化
- `log_drive_sync_summary()` が `resource_id=f"batch_{folders_processed}_folders"` を渡す
- `_to_uuid_or_none()` が UUID でないためこれを None に変換 → DB に NULL で保存
- batch 処理の resource_id 情報が DB から失われる (Cloud Logging には残る)
- 同様に `log_audit_batch()` の `resource_id=f"batch_{len(items)}_items"` も NULL 化される
- 設計的にはサイレント失敗 (フォールバック設計) だが、DB の resource_id が常に NULL になる点は意図的か要確認

## SUGGESTION-1: _to_uuid_or_none() ヘルパーを関数内に定義
- `log_audit_async()` 内に `def _to_uuid_or_none()` を定義 (ローカル関数)
- 呼び出しのたびに関数オブジェクトが再生成される (性能への影響は軽微)
- より明確にするなら module-level に定義すべきだが、機能的には問題なし

## SUGGESTION-2: DB 書き込みパスのテストカバレッジなし
- `tests/test_audit_async.py` と `tests/test_audit.py` の `TestLogAuditAsync` は `get_async_db_pool` をモックしていない
- テスト実行時は DB 接続失敗 → Cloud Logging フォールバックで `return True` となる
- DB INSERT のパス (成功・失敗・CAST エラー) が実際にテストされていない
- 追加すべきテストケース:
  - `patch("lib.audit.get_async_db_pool")` でモック → DB 書き込み成功を assert
  - DB 書き込み失敗時に `True` を返しつつ WARNING ログを出すことを assert

## SUGGESTION-3: 成功ログに絵文字
- line 363: `logger.info("✅ Audit DB logged: ...")` — 絵文字使用
- CLAUDE.md §5: "Only use emojis if the user explicitly requests it"
- 機能には影響なし、スタイルの問題

## 検証済み OK 項目

### CAST(NULL AS UUID) の挙動 — OK
- PostgreSQL: `CAST(NULL AS UUID)` は NULL を返す。エラーにならない
- asyncpg: Python `None` を SQL NULL として渡す。正常動作
- `_to_uuid_or_none()` が `None` を返す場合、`CAST(:user_id AS UUID)` with None = `CAST(NULL AS UUID)` = NULL

### SQLAlchemy 2.x AsyncEngine.connect() + conn.commit() パターン — OK
- SQLAlchemy 2.0 の AsyncEngine は autobegin モード (DML後に明示的 commit が必要)
- `async with pool.connect() as conn:` + `await conn.commit()` は正しいパターン
- `api/app/api/v1/knowledge.py` line 57-59 で同じパターンを使用 (確認済み)

### 型整合性 (audit_logs カラム vs INSERT) — OK
- `organization_id`: DB = character varying, INSERT = :org_id (str) → 正常
- `user_id`: DB = uuid, INSERT = CAST(:user_id AS UUID) with _to_uuid_or_none → 正常
- `resource_id`: DB schema.json = uuid (本番型), INSERT = CAST(:resource_id AS UUID) with _to_uuid_or_none → 正常
  - 注: 元の DDL (phase_2-5_cloudsql.sql) は VARCHAR(255) だが、db_schema.json (2026-02-10生成、本番反映) は uuid
- `details`: DB = jsonb, INSERT = CAST(:details AS JSONB) → 正常
- `id`: DEFAULT gen_random_uuid() → INSERT に含めていないが auto-generated — 正常
- `department_id`, `ip_address`, `user_agent`: INSERT に含めていない → NULL で保存 (nullable) — 正常

### 循環インポート — なし
- `lib/audit.py` → `lib/logging.py` → `lib/config.py` + `lib/tenant.py`
- `lib/tenant.py` は外部ライブラリのみ import (循環なし)
- `lib/config.py` は外部ライブラリのみ import (循環なし)

### 3-copy sync — OK
- lib/ = chatwork-webhook/lib/ = proactive-monitor/lib/ = sync-chatwork-tasks/lib/ 全一致
- `sync-chatwork-tasks` は Dockerfile で `sync-chatwork-tasks/lib/` を削除してルート `lib/` を使う

### 非同期テスト失敗 — pre-existing (NOT regression)
- `test_audit.py::TestLogAuditAsync` および `test_audit_async.py::TestLogAuditAsync` の async テストは
  pytest-asyncio 未設定 (Python 3.14 互換性問題) で既に失敗。Phase B-2 で新たに導入した失敗ではない。

### Check Rule #6 (async blocking) — OK
- `pool = await get_async_db_pool()` — async pool 取得
- `async with pool.connect() as conn:` — asyncpg AsyncEngine の非同期コネクション
- 同期 I/O のブロッキングなし

### Check Rule #9 (pg8000 互換) — N/A for this code
- `log_audit_async` は asyncpg (AsyncEngine) を使用。pg8000 ではない
- `lib/audit.py` の同期版 `log_audit()` は pg8000 を使用するが、今回の変更なし

### Check Rule #10 (トランザクション内 API 呼び出し) — OK
- DB 接続は DB 書き込みのみ。外部 API 呼び出しなし
