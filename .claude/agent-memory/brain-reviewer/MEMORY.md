# brain-reviewer Agent Memory

## Project key facts (verified)

- Python 3.11+ project, run tests with `python3 -m pytest` (not `python`)
- Working directory: `/Users/kikubookair/soul-kun`
- Logger names follow Python's `__name__` convention (e.g. `lib.audit` for `/Users/kikubookair/soul-kun/lib/audit.py`)
- PR review via `gh pr diff <number>` and `gh pr view <number> --json ...`

## Known pre-existing test failures (NOT regressions)

- `TestLogAuditAsync`, `TestLogDrivePermissionChange`, `TestLogDriveSyncSummary` (11 tests in `tests/test_audit.py`) fail locally due to missing/misconfigured pytest-asyncio plugin.
- ALL tests in `tests/test_proactive.py`, `tests/test_proactive_monitor.py` etc. fail locally due to langfuse/pydantic.v1 incompatibility with Python 3.14. Pre-existing.

## Review checklist quick notes

- For test-only PRs: verify only the changed file, run the modified tests, check for scope creep
- Tests-only changes don't require Brain architecture or org_id checks (22-item checklist largely N/A for pure test files)
- Always check if async test failures are pre-existing before flagging
- `e` in `logger.error("...: %s: %s", type(e).__name__, e, ...)` CAN contain PII; prefer logging only `type(e).__name__` in production paths
- 3-copy sync: always diff all 3 copies: lib/, chatwork-webhook/lib/, proactive-monitor/lib/

## lib/audit.py patterns (confirmed in PR #571 / #574)

- Logger name: `"lib.audit"`. Fallback: INFO `"Audit (no table): ..."`. Exception: WARNING then INFO.
- caplog: `with caplog.at_level(logging.INFO, logger="lib.audit"):` captures INFO and above

## proactive.py patterns (confirmed in PR #614)

- **P8 Silent Fail (v11.2.0)**: `_take_action()` no longer calls `_generate_message()` as fallback.
  - When `message` is None (Brain=None or Brain exception): returns `ProactiveAction(success=True, error_message="Brain unavailable: send skipped")`. Does NOT call `_send_message_func`.
  - `_generate_message()` is now dead code — no callers remain in main code. Test `test_generate_message_template_fallback` also orphaned.
  - **Design convention**: `success=True` + non-None `error_message` = "intentionally skipped". Brain's `should_send=False` uses the same pattern (line 905-915). Consistent but semantically awkward.
  - `create_proactive_monitor()` now logs at ERROR (was WARNING) when brain=None
- **P15 org_id masking**: `state_manager.py:109` and `self_awareness/__init__.py:114` now use `org_id[:8]...`
  - **REMAINING LEAKS in proactive.py** (NOT fixed in PR #614):
    - line 516: `logger.debug(f"... invalid UUID for user {user_ctx.user_id}: {user_ctx.organization_id}")`
    - line 627: same pattern for emotion_decline check
    - line 687: same pattern for goal_achieved check
    - These are DEBUG level only — harmless in prod, but scope miss for P15
- **dry_run path** (line 956): `brain_info` variable can show `"(fallback)"` but that branch is now unreachable (message=None exits earlier). Stale code, not a bug.
- **Docstring stale** (line 1181-1183): Note in `create_proactive_monitor()` still says "テンプレートが使用される" but behavior is now Silent Fail.
- `_log_action` is guarded by `if success:` AFTER the send attempt — the new early return path correctly skips `_log_action`.
- Still open architectural issues: See `topics/proactive_py_history.md`

## ProactiveAction dataclass conventions

- `success=True` + `error_message=None` = sent successfully
- `success=True` + `error_message="Skipped by brain: ..."` = Brain decided not to send (should_send=False)
- `success=True` + `error_message="Brain unavailable: send skipped"` = NEW: Silent Fail (PR #614)
- `success=False` + `error_message=type(e).__name__` = actual send failure

## state_manager.py BrainStateManager patterns (confirmed PR #614)

- `__init__`: org_id masking at line 109: `org_id[:8] if org_id else ''`
- `_org_id_is_uuid`: detected via `UUID(org_id)` try/except, used to skip queries on non-UUID org_ids
- `_is_async_pool`: detected via `hasattr(pool, 'begin') and asyncio.iscoroutinefunction(pool.begin)`

## Telegram/ChatWork channel adapter topics

- See individual topics in memory notes (compact summary kept here):
  - Telegram room_id: `tg:{chat_id}` or `tg:{chat_id}:{topic_id}`
  - ChatWork file detection: `extract_chatwork_files()` in chatwork_adapter.py, regex `\[download:(\d+)\]`
  - Vision AI bypass type: `IMAGE_ANALYSIS = "image_analysis"` in integration.py
  - bypass_handlers.py is chatwork-webhook ONLY (not root lib/)

## Known open issues (pre-existing, not introduced by any reviewed PR)

- `lib/brain/episodic_memory.py` line 251: keywords logged at INFO (PII leak risk)
- `lib/brain/alert_sender.py` line 78: hardcoded ChatWork room ID `"417892193"` as default
- `lib/brain/integration.py` lines 624, 630: bare `asyncio.create_task()` (not _fire_and_forget)
- `lib/brain/authorization_gate.py` line 378, `memory_access.py` line 348, `agents/base.py` line 669: same pattern
- Proactive messages bypass Guardian/Authorization Gate (generate_proactive_message skips process_message)
- confirmation loop: confirmed operations NOT audit-logged via normal path (execute_tool node bypassed)
- `ORGANIZATION_UUID_TO_SLUG` hardcoded mapping in proactive.py (tech debt, Phase 4B TODO)

## capability_bridge.py refactor patterns (P10, branch refactor/capability-bridge-split)

- `lib/brain/capabilities/` subpackage: generation.py, google_workspace.py, feedback.py, meeting.py, connection.py
- `_parse_org_uuid` / `_safe_parse_uuid`: duplicated in generation.py AND feedback.py (module-level, not a shared util). No shared `_utils.py`.
- `_get_google_docs_credentials()`: moved to generation.py, hardcoded project `"soulkun-production"` — PRE-EXISTING bug (also in old bridge).
- google_workspace.py handlers accept `org_id` param but NEVER use it internally (no tenant check). Pre-existing behavior (old bridge same).
- **CRITICAL BUG**: `tests/test_capability_bridge.py` tests 10 methods removed from CapabilityBridge:
  - `test_lazy_initialized_attributes_are_none` (line 129): refs `bridge._multimodal_coordinator` etc. — attrs deleted
  - `TestSafeParseUuid` (line 143): calls `CapabilityBridge._safe_parse_uuid` — static method deleted
  - `TestParseOrgUuid` (line 175): calls `bridge._parse_org_uuid()` — instance method deleted
  - Tests not updated in this PR. Would fail at runtime (but can't run locally due to Python 3.14 + langfuse)
- meeting.py handlers import `from handlers.meeting_handler import ...` (lazy, inside function body). Resolves correctly in chatwork-webhook context (PYTHONPATH includes /app/chatwork-webhook). Pre-existing pattern.
- `result.error_message` propagated to user message in generation.py lines 165, 279, 378. Pre-existing (same in old bridge).
- 3-copy sync: lib/, chatwork-webhook/lib/, proactive-monitor/lib/ all identical (verified).
- audit logging: NO audit calls in any capabilities/ handler. Pre-existing gap (old bridge same).

## validate_sql_columns.sh coverage gap (confirmed Phase 3 review)

- `--all` flag only scans `lib/`, `chatwork-webhook/lib/`, `proactive-monitor/lib/` — NOT `api/` or `cost-report/`
- Bugs in `api/app/api/v1/admin/brain_routes.py` and `cost-report/main.py` pass `--all` silently
- To detect API layer SQL bugs, must manually grep `api/` and `cost-report/` for old column names

## Phase 3 (AI cost visibility) — FIXED in feat/phase3-ai-cost-visibility (reviewed 2026-02-19)

### All previously flagged issues now RESOLVED:
- C-1: `brain_routes.py` `SUM(cost_usd)` → `0 as cost` (brain_decision_logs has no cost column)
- C-2: `cost-report/main.py` `model_name` → `model_id`, `GROUP BY model_name` → `GROUP BY model_id`
- W-1: `dashboard_routes.py` `AVG(response_time_ms)` → `AVG(latency_ms)`
- W-2: `dashboard_routes.py` `is_error = TRUE` → `success = FALSE`
- W-3: `dashboard_routes.py` `FROM brain_insights / summary` → `FROM brain_strategic_insights / description`
- costs_routes.py: `cost_usd`→`cost_jpy`, `budget_usd`→`budget_jpy`, `model_name`→`model_id`, `usage_tier`→`tier`

### Remaining open items (SUGGESTION level, not blocking):
- `api/app/schemas/admin.py`: All cost `Field(description=...)` still say "（USD）" but actual values are JPY
  - Lines 102,103,134,186,188,205,223,232: `description="コスト（USD）"` should be `（円）`
  - Non-breaking (description is documentation only), SUGGESTION to fix for clarity
- `bottleneck_alerts` queries in `dashboard_routes.py`: `organization_id::text` cast is inconsistent
  with other tables (no cast). Pre-existing, correct behavior, minor inconsistency only.
- `cost-report/main.py` line 27: `ALERT_ROOM_ID` default `"417892193"` hardcoded — same as alert_sender.py pre-existing

## Phase 3 admin API patterns (confirmed 2026-02-19)

- `api/app/api/v1/admin/deps.py`: `require_admin` = Level 5+, `require_editor` = Level 6+
- Auth: `get_current_user` (JWT) + `get_user_role_level_sync` DB check — fully authenticated
- All 4 routes have `organization_id` filter on every SELECT — org isolation OK
- Audit logging via `log_audit_event()` present on all endpoints
- `async def` + synchronous `pool.connect()` pattern — pre-existing, admin dashboard is §1-1 exception
- `brain_strategic_insights` is in `soulkun_tasks` DB (NOT soulkun DB)
- `bottleneck_alerts.organization_id` is UUID type (both soulkun and soulkun_tasks DBs)
- `ai_usage_logs.organization_id` is UUID type — no cast needed (PostgreSQL auto-casts text literals)

## Phase 4 main.py split (feat/phase4-main-split, reviewed 2026-02-19)

- `chatwork-webhook/routes/telegram.py`: Blueprint-based split of Telegram webhook from main.py
- `from main import _get_brain_integration` at line 172 is INSIDE the function body (deferred/lazy import) — NOT at module level. No circular import at load time. `sys.modules['main']` is already populated when gunicorn starts.
- `app.register_blueprint(telegram_bp)` is at module-level in main.py (line 3042-3044) — no `url_prefix`, so `/telegram` route is unchanged.
- Rate limit state (`_telegram_rate_limit` dict) moved from main.py to routes/telegram.py module scope. Gunicorn `--workers 1` means single process, so per-module dict is equivalent to original. Behavior unchanged.
- **CRITICAL test failure**: `tests/test_telegram_webhook.py::TestTelegramRateLimit::test_rate_limit_function_exists` fails because it AST-parses `main.py` and asserts `_check_telegram_rate_limit` and `telegram_webhook` exist there. Both are now in `routes/telegram.py`. Test must be updated to scan `routes/telegram.py` instead (or both files).
- `test_no_print_statements_in_telegram_webhook` PASSES (it checks main.py, which no longer has the function — no prints = vacuous pass). This is a false-positive — the test now tests nothing.

## Phase 5 main.py split (feat/phase4-main-split, Zoom, reviewed 2026-02-19)

- `chatwork-webhook/routes/zoom.py`: Blueprint split of Zoom webhook (176 lines)
- `from main import get_ai_response_raw, _ORGANIZATION_ID` at line 111 is INSIDE the function body (deferred/lazy import). No circular import at load time.
- `from routes.zoom import zoom_bp` is at module-level in main.py (line 2900). Safe because zoom.py has NO module-level `from main import`.
- Blueprint registered with `app.register_blueprint(zoom_bp)` — no `url_prefix`, so `/zoom-webhook` route is unchanged.
- `GET` method on `/zoom-webhook` is PRE-EXISTING (original main.py line 2889 also had `methods=["POST", "GET"]`).
- `threading.Thread(daemon=True)` + `asyncio.new_event_loop()` + `loop.close()` in finally — PRE-EXISTING pattern. `loop.close()` is in finally block (line 164). Correct.
- `traceback.print_exc()` and `{bg_err}` in print — PRE-EXISTING pattern (main.py has 9 instances). Not a regression.
- `result.message` at line 158 (`print(f"Zoom議事録生成失敗: {result.message}")`) — only reached when `result.success=False` or `result.message=None`. Meeting content NOT exposed here (success=True+message=body goes to ChatWork, not print).
- `_ORGANIZATION_ID` default hardcoded value `"5f98365f..."` is PRE-EXISTING (from original main.py).
- No AST-based tests exist for zoom_webhook (unlike Telegram). No test regressions introduced.
- WARNING: `print(f"... {type(e).__name__}: {e}")` at line 173 (outer except) — `{e}` expansion could expose internal paths/connection strings. Same pattern as Telegram (pre-existing, WARNING level).

## Phase 6 main.py split (feat/phase4-main-split, Scheduled routes, reviewed 2026-02-19)

- `chatwork-webhook/routes/scheduled.py`: Blueprint split of 4 scheduled routes (710 lines)
- **CRITICAL ARCHITECTURAL ISSUE**: Cloud Scheduler does NOT call chatwork-webhook Cloud Run for these routes.
  - Scheduler targets standalone Cloud Functions in `check-reply-messages/`, `sync-chatwork-tasks/`, `remind-tasks/`, `cleanup-old-data/` directories.
  - The 4 new Blueprint routes in scheduled.py are effectively unreachable in production (no caller).
  - `chatwork-webhook` Cloud Run is publicly accessible (`allUsers`) — so these routes are publicly exposed but unauthenticated.
- **ARCHITECTURE CLARIFICATION**: chatwork-webhook = Cloud Run (Docker), scheduled jobs = separate Cloud Functions (Gen2). These are completely separate deployments.
- All `from main import` calls are inside function bodies (lazy) — no circular import at load time.
- `from routes.scheduled import scheduled_bp` is at module level in main.py line 2238. Safe because scheduled.py has NO module-level `from main import`.
- **PRE-EXISTING**: `httpx.post()` inside open transaction in `remind_tasks` (line 484). DB connection open while calling external API. Rule #10 violation, but pre-existing.
- **PRE-EXISTING**: `str(e)` exposed in HTTP responses (lines 65, 141, 379, 514). Same in original main.py.
- **PRE-EXISTING**: `cleanup_old_data` DELETE queries on `room_messages`, `processed_messages`, `conversation_timestamps` have NO `organization_id` filter, despite these tables having org_id columns. Pre-existing in original main.py.
- **PRE-EXISTING**: `system_config`, `excluded_rooms` queries without org_id. These tables have no org_id column (intentional single-tenant design for chatwork-webhook).
- **PRE-EXISTING**: `task_reminders` INSERT has no org_id (table has no org_id column).
- `flask_request` is imported but not used (import is kept, `request = flask_request` dead code lines were removed in split).
- `user_departments` query has no org_id filter — table has no org_id column (pre-existing).
- No new tests added for scheduled.py routes (pre-existing gap, CFs have their own separate tests).

## Phase 4C next-phase evaluation (2026-02-19)

- **B (requirements固定)**: Phase 4C で完了。`google-cloud-storage==2.19.0` に固定（2.19.0 = 2.x系最新、PyPI確認済み）
- **A-1 (Scheduled Blueprint分割)**: 実施不推奨。Cloud Schedulerはchatwork-webhook Cloud Runを呼ばない。追加してもunreachable+unauthenticated endpoint増加になる
- **A-2 (chatwork_webhook分割)**: 本番主要エンドポイント。依存関数群1054行(行822-1875)がセット。`get_ai_response`単独312行。TelegramやZoomの3-5倍の規模。高リスク
- **C (Google Meet)**: lib/meetings/に`google_calendar_client.py`のみ。録画取得実装ゼロ。Drive API経由+Webhook設定複雑。前提条件(Google Workspace録画機能の有効化)確認が必要
- **推奨順**: B(1行修正) → A-2(段階的) → C(前提確認後)。A-1は非推奨

## chatwork-webhook/main.py の4スケジュールルートの状態 (確定調査結果 2026-02-19)

### デプロイアーキテクチャ（確定）
- chatwork-webhook = Cloud Run (Docker)。`allUsers` invoker権限（公開アクセス）
- 4つのスケジュールジョブ = 独立したCloud Functions Gen2（`cloud_functions.tf`に定義）
- Cloud Schedulerは `google_cloudfunctions2_function.functions["check-reply-messages"]` 等のURIを直接呼ぶ。chatwork-webhook Cloud RunのURIは一切指定していない

### main.py内4ルートの性質（確定）
- `/check-reply-messages`（行2214）、`/sync-chatwork-tasks`（行2327）、`/remind-tasks`（行2573）、`/cleanup-old-data`（行2698）
- Cloud Schedulerから呼ばれることはない（スケジューラーは独立CF直接呼び出し）
- 認証なし（HMACはWebhook `/` のみ）。かつ chatwork-webhook は `allUsers` 公開 → **誰でも呼べるエンドポイント**
- 判断：**デッドコード（A）。Blueprint分割は不要かつ有害（セキュリティリスク増大なし変化なし）**
- 推奨アクション：Blueprint分割より**削除**が正しい。ただし削除前に「本番で手動呼び出しに使っていないか」確認が必要

### 独立CF main.py の構造
- `check-reply-messages/main.py`：Flask `@app.route("/")` が `check_reply_messages()` のエントリ。Dockerでgunicorn起動。cloud_functions.tfの `entry_point = "check_reply_messages"` で `@` デコレータなし関数を直接呼ぶ（Gen2はFlaskアプリ or functions-framework両対応）
- 4つのCFディレクトリそれぞれに独立したmain.pyあり（互いのコードを共有せず）

## routes/ ファイル現状 (2026-02-19確認、Phase 4C完了後)

- `chatwork-webhook/routes/telegram.py`: 226行（Phase 4で分割済み）
- `chatwork-webhook/routes/zoom.py`: 176行（Phase 5で分割済み）
- `chatwork-webhook/routes/scheduled.py`: 存在しない（実装すべきでない）
- main.pyに残存するルート: `/`(chatwork_webhook) のみ（2236行）
- Phase 4C: 4デッドルート削除完了（2907→2236行、-671行）
- 残存する軽微なTODO（SUGGESTION only、マージ非ブロック）:
  - `flush_dm_unavailable_notifications` が import 行（line 58）にのみ残存。削除されたルートでのみ使われていた。未使用 import だが実害なし。
  - `ensure_room_messages_table` が import 行（line 71）にのみ残存。同上。
  - `process_overdue_tasks()` の docstring line 2192: "remind_tasksから呼び出し" は stale（remind_tasksルート削除済み）。実際は独立CFから呼ばれる。

## Phase B-1 mask_email PIIマスキング (fix/currency-display-jpy, reviewed 2026-02-19)

- `lib/logging.py` に `mask_email(email: str) -> str` を追加（行328-347）
- `lib/drive_permission_manager.py` の10箇所を `{email}` → `{mask_email(email)}` に変更
- **WARNING: 修正漏れ2箇所** — `update_permission()` の lines 542, 568 に `{email}` 生ログが残存
  - line 542: `f"[DRY RUN] Would update permission: {email} {permission.role.value}..."` (masked なし)
  - line 568: `f"Updated permission: {email} {permission.role.value}..."` (masked なし)
  - 3コピー全てに同じ漏れあり（lib/, chatwork-webhook/lib/, proactive-monitor/lib/）
- **SUGGESTION: `@nodomain` エッジケース** — `"@nodomain".split("@",1)` → `local=""`, `len("")<=1` → `*@nodomain` を返す。意図は不明だが実害なし（空localは無効メール）
- **SUGGESTION: `mask_email()` 専用ユニットテストなし** — `test_memory_sanitizer.py:64` の `test_mask_email` は `mask_pii()` のテスト。`lib.logging.mask_email` 直接テストは存在しない
- **SUGGESTION: `google_docs_client.py` line 360** — `logger.info(f"Shared document {document_id} with {len(email_addresses)} users")` はカウントのみで生メール非ログ。対象外（スコープ外として正しい）
- `PermissionChange.email` フィールドへの生メール保存は設計上正当（ビジネスロジック構造体）
- 3-copy sync: lib/ = chatwork-webhook/lib/ = proactive-monitor/lib/ 全一致（確認済み）— ただし漏れも3コピー全て同じ

## Phase A-2 document_generator.py タイムアウト有効化 (fix/currency-display-jpy, reviewed 2026-02-19)

- 対象: `lib/capabilities/generation/document_generator.py`
- `_call_llm` / `_call_llm_json` は pure async (httpx.AsyncClient を直接 await) — asyncio.to_thread は使っていない
- `asyncio.wait_for + asyncio.to_thread` の禁止パターン (#20) に該当しない
- タイムアウト定数は constants.py で正しく定義 (OUTLINE=60, SECTION=120)
- **WARNING: `asyncio.TimeoutError` が `OutlineGenerationError` に変換されるが `OutlineTimeoutError` にならない**
  - `_generate_outline` の `except Exception as e` が `asyncio.TimeoutError` を `OutlineGenerationError` にラップ
  - `_generate_section` の `asyncio.TimeoutError` は呼び出し元 `_generate_full_document` の `except Exception` で `SectionGenerationError` にラップ
  - 専用クラス `OutlineTimeoutError`/`SectionTimeoutError` が存在するが使われない
- **WARNING: `import time` が関数本体内にある (line 506)** — 通常は module-level に置くべき
- **WARNING: `str(e)` をユーザー向けエラー応答に含める箇所あり (lines 164, 175, 186)** — 既存の pre-existing 問題
- **SUGGESTION: タイムアウトテストなし** — `test_generation.py` にタイムアウト時の `_generate_outline`/`_generate_section` 動作テストがない (例外クラスのユニットテストのみ)
- 3-copy sync: lib/ = chatwork-webhook/lib/ = proactive-monitor/lib/ 全一致（確認済み）

## Topic files index

- `topics/proactive_py_history.md`: Full Codex/Gemini cross-validation findings pre-PR #614
- `topics/admin_dashboard_frontend.md`: admin-dashboard フロントエンドレビューパターン (Phase A-1 通貨表示バグ修正等)

## Phase A-1 admin-dashboard 通貨表示修正 (fix/currency-display-jpy, reviewed 2026-02-19)

- **CRITICAL**: `kpi-card.test.tsx` line 22 の `'$42.50'` → `'¥43'`（またはテスト入力を整数に変更）
- 変更4ファイル: kpi-card.tsx, costs.tsx, dashboard.tsx, brain.tsx — 13箇所の $ を ¥ に変更
- 残存 $ 表示: 0件（網羅性確認済み）
- `api/app/schemas/admin.py` の "（USD）" 記述: 既に存在しない（前回記録の残存事項は解消済み）
- WARNING: dashboard.tsx `予算残高` カードのツールチップに通貨単位記述なし
