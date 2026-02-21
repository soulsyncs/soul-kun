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

- `lib/brain/episodic_memory.py` `save_episode()`: **FIXED** in Task A implementation — now has set_config RLS context, 3-copy sync done, error handling with rollback+invalidate. See episodic_memory.py review below.
- `lib/brain/episodic_memory.py` `save_episode()`: **NEW WARNING** — `brain_episodes` table has `room_id` and `source` columns that are not inserted (INSERT omits them). Both are nullable, so no runtime error, but data is incomplete.
- `lib/brain/episodic_memory.py` `save_episode()`: **NEW WARNING** — `set_config(..., NULL, false)` may fail on some PostgreSQL versions (NULL not valid for set_config text parameter). state_manager.py uses the same pattern — treat as consistent but note risk. Actual behavior: PostgreSQL accepts NULL and sets to empty string.
- `lib/brain/episodic_memory.py` `save_episode()`: **NEW CRITICAL** — `self.pool.connect()` is synchronous blocking called directly (not via asyncio.to_thread()). create_episode() is sync, but callers in async chain (Brain nodes) will block the event loop. Must use asyncio.to_thread() or check _is_async_pool.
- `lib/brain/episodic_memory.py` line 443: `message[:50]` logged in recall() debug — message content (PII) in logs. DEBUG only, harmless in prod.
- `lib/brain/episodic_memory.py` `_generate_episode_id()`: uuid5(NAMESPACE_DNS, content) where content = f"{summary}_{occurred_at.isoformat()}". If two different episodes have the same summary+time, they will silently collide (ON CONFLICT DO UPDATE). This is a design choice, not a bug per se.
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

## memory_layer.py / context_builder.py RLS パターン (タスクE 2026-02-21, 最終確認)

- `BrainLearning._connect_with_org_context()`: `lib/brain/learning.py` line 266, 引数なし(@contextmanager), `self.org_id` を set_config する。finally でクリアあり（ただし try/except なし → finally 内で例外が発生する可能性あり）
- **タスクE修正済み**: memory_layer.py `_fetch_learnings()` が `self.pool.connect()` → `self.learning._connect_with_org_context()` に修正。3コピー同期PASS。
- **タスクE修正済み**: context_builder.py `_fetch_all_db_data()` に set_config org_id 設定追加。クリアは try/except（try/finally でない）。
- **残存RLS漏れ (WARNING)**: `lib/brain/context_builder.py` line 1106 `_get_phase2e_learnings()` の `_sync_fetch()` が `self.pool.connect()` のまま。ただし現在この関数は asyncio.gather から呼ばれておらず `_fetch_all_db_data` 統合後はデッドコード化している可能性あり（line 1055「DEPRECATED」コメント確認要）。
- **RLSクリアの安全性**: context_builder.py の RLS クリアは try/except（not try/finally）。最後のクエリ（query_9_ceo）が失敗して例外が catch されると `with pool.connect() as conn:` ブロックの外側 except に飛ぶため、クリア処理がスキップされる可能性あり。ただし中間 9クエリはそれぞれ個別 try/except でロールバックされ外側 except には飛ばない設計なので、実際のリスクは低い。
- `_connect_with_org_context()` の finally は try/except なし → finally 内の NULL set_config が失敗した場合 TypeError が伝播する（pre-existing）
- 詳細: `topics/memory_layer_rls_patterns.md`

## lib/meetings/ architecture patterns (confirmed 2026-02-21 proposal review)

- `vtt_parser.py`: `parse_vtt()` correctly extracts `speaker` field from "Name: text" VTT format. `VTTTranscript.speakers` returns unique speaker list. Speaker IS preserved in VTTSegment objects but discarded downstream.
- `transcript_sanitizer.py`: `TranscriptSanitizer` does NOT strip speaker names. Patterns are: credit card, Japanese address, employee ID, my number, phone, email etc. Speaker names are NOT in the PII pattern list. They are discarded because `speakers_json=None` and `raw_transcript=None` are passed to `save_transcript()` (hard-coded in zoom_brain_interface.py line 248-249, not via sanitizer setting).
- `zoom_brain_interface.py`: `_save_minutes_to_memory()` exists at line 459 (NOT 468 as proposal claimed). Saves: title, meeting_id, room_id, document_url, duration_seconds, task_count. Does NOT save: transcript text, speaker names.
- `google_meet_brain_interface.py`: `_save_minutes_to_memory()` exists at line 551 (NOT 621 as proposal claimed). Saves: title, meeting_id, room_id, drive_url, task_count. Confirmed working pattern.
- `BrainMemoryEnhancement` (__init__.py): exposes `find_episodes_by_keywords()` (line 217). Does NOT expose `find_episodes_by_time_range()` or `find_similar_episodes()` as public methods. These exist ONLY in `EpisodeRepository` (episode_repository.py lines 472, 537) as lower-level `find_by_time_range()` and `find_similar()`.
- Proposal's claim that "find_episodes_by_time_range(), find_similar_episodes() are existing and working" is MISLEADING. They exist in the repository layer but are NOT exposed in the public facade (BrainMemoryEnhancement). Any caller must go through EpisodeRepository directly, bypassing the organization_id safety wrapper.

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
- `chatwork-webhook/routes/zoom.py`: 185行（Phase 5で分割済み、Phase Z1で+9行）
- `chatwork-webhook/routes/scheduled.py`: 存在しない（実装すべきでない）
- main.pyに残存するルート: `/`(chatwork_webhook) のみ（2236行）
- Phase 4C: 4デッドルート削除完了（2907→2236行、-671行）
- 残存する軽微なTODO（SUGGESTION only、マージ非ブロック）:
  - `flush_dm_unavailable_notifications` が import 行（line 58）にのみ残存。削除されたルートでのみ使われていた。未使用 import だが実害なし。
  - `ensure_room_messages_table` が import 行（line 71）にのみ残存。同上。
  - `process_overdue_tasks()` の docstring line 2192: "remind_tasksから呼び出し" は stale（remind_tasksルート削除済み）。実際は独立CFから呼ばれる。

## Phase Z2 ④ Google Calendar ±60分ウィンドウ変更 (2026-02-20, APPROVED)

### 変更: lib/meetings/google_calendar_client.py
- `DEFAULT_TIME_WINDOW_MINUTES` 30 → 60（コメントに理由追記）
- `_select_best_match()` に `time_window_minutes: int = DEFAULT_TIME_WINDOW_MINUTES` 引数追加
- `find_matching_event()` が `_select_best_match` に `time_window_minutes` を渡すよう修正
- 3コピー同期済み（lib/, chatwork-webhook/lib/, proactive-monitor/lib/ 全てIDENTICAL確認済み）

### テスト: tests/test_google_calendar_client.py
- 新テスト4件追加（window boundary, score calc, custom window）
- **注意**: `test_30min_window_misses_event_at_50min` は関数内部のスコア値を直接assert **しておらず**、手計算の算術式をassertするのみ（設計意図の文書化テスト）。機能的には正しい（diff=50 > window=30なのでtime_score=0は正しい）が、回帰テストとしては弱い。

### callers 確認
- `handlers/zoom_webhook_handler.py` line 191: `client.find_matching_event(zoom_start, zoom_topic=topic)` — time_window_minutesを渡さない（デフォルト60分が使われる）
- root `handlers/` と `chatwork-webhook/handlers/` 両方IDENTICAL確認済み
- 本番で明示的なtime_window変更呼び出しはなし（デフォルト値変更のみが実効的な変更）

### ローカルテスト実行結果
- テスト自体は正しく動作（直接import検証済み）
- `python3 -m pytest tests/test_google_calendar_client.py` は langfuse/pydantic.v1/Python3.14 問題でCOLLECTION ERRORになる（pre-existing、PRに関係なし）

## Google Calendar Events API (サービスアカウント方式) — 2026-02-20

### calendar_routes.py の /events エンドポイント（今回追加）

- **CRITICAL: `_get_calendar_service()` が `subprocess.run(["gcloud", ...])` を使用している**
  - Cloud Run環境ではgcloudコマンドが存在しない可能性が高い。本番でHTTP 503になるリスク。
  - 正しい実装: `google.cloud.secretmanager.SecretManagerServiceClient()` で取得すべき（lib/brain/capabilities/generation.py lines 22-32 が正しい実装例）
  - `result.returncode` チェックなし: gcloudコマンドが失敗しても空文字が `sa_key_str` に入り、後段でJSONパースエラーになる（503でなくUnhandled exceptionになる）
  - 一時ファイル（`tempfile.NamedTemporaryFile`）にSAキーを書き出している。`delete=False` + `finally: os.unlink()` で削除は行われるが、例外発生時にファイルが残る可能性あり（finally内でのunlinkが失敗した場合）

- **WARNING: `/events` エンドポイントは `get_current_user` のみで Level 未チェック**
  - 他のエンドポイント（status/connect/disconnect）も同様に `get_current_user` のみ（require_adminなし）
  - 管理画面APIでLevel 5+チェックなしは pre-existing pattern（今回新規追加の問題ではなく、既存の設計選択）
  - admin dashboard は §1-1 例外（読み取り専用）に該当するため SUGGESTION 扱い

- **WARNING: `/events` エンドポイントに audit ログなし**
  - /status, /connect, /disconnect, /callback には `log_audit_event()` があるが `/events` にはない
  - カレンダーの「閲覧」は confidential 操作に当たる可能性あり（鉄則#3）

- **`_SA_KEY_SECRET = "google-docs-sa-key"` はハードコード**（鉄則#16相当）
  - ただし lib/brain/capabilities/generation.py line 25 でも `"soulkun-production"` と `"google-docs-sa-key"` がハードコードされており、PRE-EXISTING パターン
  - 環境変数 `GOOGLE_SA_KEY_SECRET` で上書き可能な設計にすべき

- **既存の `create_calendar_client_from_db()` との重複**
  - `lib/meetings/google_calendar_client.py` の `create_calendar_client_from_db()` が OAuth方式でカレンダーを取得する正規ルート
  - `calendar_tool.py` の `list_calendar_events()` も同クライアントを使う
  - 今回の `/events` エンドポイントはサービスアカウント方式で別実装。2つのアクセス方式が並存している
  - 設計として意図的かどうか確認が必要（管理画面は会社カレンダー全体を見る、Brain toolはOAuth接続カレンダーを見る、という分離かもしれない）

- **`CalendarEvent` dataclass名の衝突**
  - `lib/meetings/google_calendar_client.py` にも `CalendarEvent` クラスが定義されている
  - `api/app/schemas/admin.py` の `CalendarEvent` (Pydantic) は同名だが別クラス。import時に混乱する可能性あり（型ヒント的には問題ないが混乱招く）

### use-integrations.ts (今回追加)

- `staleTime: 5 * 60 * 1000` (5分): CLAUDE.md 鉄則#6 (キャッシュTTL 5分) 準拠

## Phase Z1 Zoom transcript_completed 対応 (2026-02-20)

### 変更概要
- `recording.transcript_completed` イベント対応（VTT生成完了時に発火）
- 3.5分待ちリトライ（30s→60s→120s）を削除 → VTT未存在時は `retry=False` で即リターン
- `webhook_event` ハードコード `"recording.completed"` → `event_type` に修正

### 重要発見: handlers/ ディレクトリが2箇所に存在
- `handlers/zoom_webhook_handler.py` (rootレベル) — **未更新のまま**
- `chatwork-webhook/handlers/zoom_webhook_handler.py` — 今回更新済み
- rootの`handlers/`はchatwork-webhook固有（lib/のような3コピー同期対象ではない）
- **テストは `sys.path.insert(0, 'chatwork-webhook')` で chatwork-webhook 側を読む** → テスト自体は正しい
- rootの`handlers/`を実際に使う場所: lib/brain/capabilities/meeting.py が `from handlers.meeting_handler import` で lazy import
- **根本問題**: rootの `handlers/` はchatwork-webhookのランタイムPYTHONPATH上には「ない」はず（Dockerfileで `/app/chatwork-webhook` がCOPY先）。rootの`handlers/`は開発/テスト環境のartifact。本番は chatwork-webhook/handlers/ のみ使われる。

### WARNING: 残存するハードコード
- `chatwork-webhook/handlers/zoom_webhook_handler.py` line 81: ログ文字列 `"Zoom webhook: recording.completed meeting_id=%s"` — `recording.transcript_completed` の場合でも同じ文字列でログされる。機能には影響なし（ログの誤解招き）。

### 3コピー同期状態
- `lib/meetings/zoom_brain_interface.py`: 3コピー全て同一 (PASS)
- `handlers/zoom_webhook_handler.py`: rootは**意図的に未更新**（chatwork-webhookのみが対象）

## Phase D-1 dead-comment cleanup (feat/org-chart-drilldown, 2026-02-19)

- `chatwork-webhook/main.py`: 3箇所のコメント削除のみ (-42行、2156→2114行)
  1. GoalHandler/KnowledgeHandler 空ヘッダーコメント（行833付近）— 実装は handlers/ に移転済み
  2. ハンドラーマッピング使い方コメントを1行に集約（行1371付近）
  3. v10.40 ai_commander tombstone コメント（行1476付近）— 「(NEW)」ラベルも同時削除
- **ロジック変更ゼロ** — コメント行のみ。SQLなし・API呼び出しなし・org_idなし
- テスト影響なし（AST解析テストは telegram.py のみ存在、main.py コメント内容は非参照）
- 22項目チェック全項目 PASS（コメント削除はロジックチェック対象外）
- 残存 SUGGESTION (pre-existing, NOT introduced by D-1): stale `flush_dm_unavailable_notifications` unused import, `process_overdue_tasks` stale docstring

## 7バグ修正レビュー (2026-02-19, 全機能テスト発見分)

### 修正ファイル・評価結果
- `lib/brain/execution.py`: REQUIRED_PARAMETERS/PARAMETER_TYPES/display_names を registry.py と整合（task_id→task_identifier, content→key/value）。PASS。後方互換エントリ（body, task_id, content）が display_names に残存 — SUGGESTION only
- `lib/brain/agents/knowledge_expert.py`: `_handle_delete_memory` の返却形式を `query` フォーマットから `persons[]` フォーマットへ修正。正しい根本原因修正。
- `lib/brain/llm_brain.py`: System Promptに `goal_progress_report` の説明を追加。問題なし。
- `lib/brain/capabilities/generation.py`: `handle_image_generation` エラー時に `error_code` を追加してリトライ停止。WARNING: `error_details=str(e)` が `lib/brain/learning.py:424` 経由で DB（execution_error カラム）に記録される。ユーザーには公開されないが内部パス・APIメッセージが記録されうる。SUGGESTION: `type(e).__name__` のみにする。`str(e)` を分類して `user_msg` は適切。
- `lib/capabilities/generation/dalle_client.py`: タイムアウト時の `continue` 追加。ロジック検証済み。`DALLETimeoutError` catch 順序は正しい（line175がhttpx.TimeoutException、line183がDALLETimeoutError == _handle_error_responseが投げる場合）。
- `lib/brain/graph/nodes/responses.py`: `handle_confirm` にて `approval_result.confirmation_message` + `capability_bridge.CAPABILITIES` の `confirmation_template` フォールバック追加。NULL安全。`format_map` はキー不足時でも `（key未指定）` で埋めるため例外なし。
- `lib/brain/guardian_layer.py`: `_check_api_limitation` 新チェック追加。`from handlers.registry import SYSTEM_CAPABILITIES` が ImportError 時は ALLOW にフォールバック（安全方向）。chatwork-webhook runtime では `handlers/` が PYTHONPATH にある。priority_level=3 はドキュメント（class docstring）に記載なし — SUGGESTION only。

### 3コピー同期確認
- 全6修正ファイルの3コピー（lib/ / chatwork-webhook/lib/ / proactive-monitor/lib/）が同一 — PASS

### 共通パターン確認
- `handlers.registry.SYSTEM_CAPABILITIES` は `/Users/kikubookair/soul-kun/handlers/registry.py` に存在（line49）。root registry: 38エントリ、chatwork-webhook registry: 37エントリ。api_limitation エントリ: chatwork_task_edit, chatwork_task_delete の2種。
- `confirmation_template` は `lib/brain/capability_bridge.py` の `CAPABILITIES` dict に格納。generate_document/generate_image/generate_video/deep_research等に存在。`responses.py` は `CAPABILITIES` を参照（`SYSTEM_CAPABILITIES` でなく）。

## Bug③ person_events.organization_id missing (2026-02-19, fix/all-function-test-bugs)

### 確定した事実
- 本番DB `person_events` に `organization_id` 列が存在しない (Cloud Logging実証)
- `db_schema.json` には `person_events.organization_id: uuid` と記録されているが**本番実態と乖離**
  - `20260216_create_persons_tables.sql` の `CREATE TABLE IF NOT EXISTS` が既存テーブルをスキップした
  - `db_schema.json` はマイグレーション後の「想定スキーマ」を記録しており、本番の実状とは異なる場合がある
- 同じバグ `DELETE FROM person_events WHERE ... AND organization_id = :org_id` が**8箇所**に存在:
  - `lib/person_service.py` L121
  - `chatwork-webhook/lib/person_service.py` L121
  - `proactive-monitor/lib/person_service.py` L121
  - `main.py` L376
  - `cleanup-old-data/main.py` L275
  - `check-reply-messages/main.py` L620
  - `remind-tasks/main.py` L1259
  - `sync-chatwork-tasks/main.py` L2482

### Option B (CASCADE依存) の評価（2回目レビュー 2026-02-19）
- `person_events` の CASCADE: 本番DB確認済み（ユーザー提供）→ CRITICAL 解消
- **残課題 W-1**: `person_attributes` の CASCADE が本番DBで有効か未確認（同様に `CREATE TABLE IF NOT EXISTS` でスキップされた可能性）
  - 確認SQL: `SELECT conname, pg_get_constraintdef(c.oid) FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid WHERE t.relname IN ('person_attributes', 'person_events') AND c.contype = 'f';`
- **残課題 W-2**: 修正が `chatwork-webhook/lib/person_service.py` の1ファイルのみで、残り7箇所が未修正
  - 3コピー同期（鉄則#17）が壊れる: `lib/` と `proactive-monitor/lib/` が未修正
  - `main.py` + 4CF main.py も同一バグが継続
- マイグレーション `20260214_persons_org_id_uuid.sql` line 10: `-- person_events: organization_id column does NOT exist (skip)` → 本番でテーブルが既存だったと確定
- `person_attributes` は同じ `CREATE TABLE IF NOT EXISTS` ブロックのため、同様にスキップされた可能性が高い

### 修正完了条件
1. `person_attributes` の CASCADE を本番DBで確認
2. 全8箇所（lib/, chatwork-webhook/lib/, proactive-monitor/lib/, main.py, 4CF main.py）を同一PR で修正（横展開完了）

## Phase Z1 ⑤ task_extractor.py parse_deadline_hint (2026-02-20)

- `lib/meetings/task_extractor.py`: `parse_deadline_hint()` 新規追加。3コピー同期PASS。
- **LOGIC BUG (WARNING)**: 今週 on Friday: `(4 - now.weekday()) % 7 == 0` → forced to 7. 金曜当日に「今週中」→ 翌週金曜になる。今週当日 = 今日 (end_of_day(now)) が正しい。
- **TEST GAP (WARNING)**: `parse_deadline_hint` が `test_task_extractor.py` にimportされておらず、直接ユニットテストなし。`test_full_flow_with_chatwork_creation` が `call_args[0][3]` (deadline引数) を検証しない。
- **SUGGESTION**: `import re as _re` と `import calendar` が関数本体内にある（モジュールトップへ移動推奨）。
- **PASS**: None/空文字/なし/未設定/不明 → default 7d。UTCタイムゾーン使用正しい。PIIログなし。90日キャップ正常動作。
- **PASS**: 3コピー同期（lib/ / chatwork-webhook/lib/ / proactive-monitor/lib/ 全て同一）。

## Phase Z2 ⑥ zoom_brain_interface.py Step 12 Memory Save (2026-02-20)

### 変更概要
- `lib/meetings/zoom_brain_interface.py`: `process_zoom_minutes()` に Step 12「議事録をエピソード記憶に保存」追加
- 新メソッド `_save_minutes_to_memory()` を追加（非クリティカル、try/exceptで保護）
- `tests/test_zoom_brain_interface.py`: `TestSaveMinutesToMemory` クラス（6テスト）追加

### 3コピー同期確認済み
- lib/ / chatwork-webhook/lib/ / proactive-monitor/lib/ 全て IDENTICAL (PASS)

### memory_enhancement モジュール署名確認 (確定)
- `BrainMemoryEnhancement.__init__(organization_id: str)` — poolは取らない。Correct: pool は _save_sync() 内でのみ使用
- `record_episode(conn, episode_type, summary, details, user_id, room_id, keywords, entities, importance, emotional_valence)` — 署名MATCH
- `RelatedEntity(entity_type: EntityType, entity_id: str, entity_name, relationship: EntityRelationship)` — 正しくobjectアクセス（dict不使用）
- `EntityType.MEETING = "meeting"`, `EntityType.ROOM = "room"` — 両方定義済み (constants.py L86,82)
- `EpisodeType.INTERACTION = "interaction"` — 定義済み (constants.py L51)

### 確認した問題点

**WARNING-1: BrainMemoryEnhancement.__init__ で organization_id を生ログ記録**
- `__init__.py` line 137: `logger.info(f"BrainMemoryEnhancement initialized for org: {organization_id}")`
- organization_id（UUID）が INFO レベルでログに出力される。P15で指摘済みのパターン。PRE-EXISTING
- zoom_brain_interface.py の新コードは毎回 `BrainMemoryEnhancement(self.organization_id)` を _save_minutes_to_memory() 内でインスタンス化 → 毎回ログ出力
- 既存コードの問題（PRE-EXISTING）。今回の変更で露出頻度は増加するが、新規導入ではない

**WARNING-2: details dict に `title` が含まれる（PII軽微リスク）**
- `details={"title": title, "room_id": room_id, ...}` で会議タイトルがDBのJSONBに保存される
- 会議タイトルには人名が含まれうる（例: 「田中部長との面談」）
- CLAUDE.md §9-2: 「チャット本文そのまま」は禁止だが会議タイトルは明示的に禁止されていない
- summary にも title が含まれる（「Zoom会議「田中部長との面談」の議事録を作成」）
- SUGGESTION: title を details から除外するか、タイトルをハッシュ化する（ただし設計意図として検索性が必要なため現状維持も合理的）

**WARNING-3: _save_entities の DELETE に organization_id フィルタなし (PRE-EXISTING)**
- `episode_repository.py` _save_entities(): `DELETE FROM brain_episode_entities WHERE episode_id = CAST(:episode_id AS uuid)` — organization_id フィルタなし
- episode_id は UUID（ランダム）なので実質的なリスクは低いが、設計上の漏れ。PRE-EXISTING

**INFO (PASS): asyncio.to_thread 使用正しい**
- _save_sync() は同期関数 → asyncio.to_thread(_save_sync) で正しくオフロード。ブロッキングなし。

**INFO (PASS): 接続管理正しい**
- `with self.pool.connect() as conn:` でwith文使用 → リークなし

**INFO (PASS): org_id isolation 正しい**
- `BrainMemoryEnhancement(self.organization_id)` → _episode_repo.save() → INSERT時 organization_id=self.organization_id でフィルタ

**INFO (PASS): 非クリティカル失敗隔離**
- try/except Exception でラップ、type(mem_err).__name__ のみログ記録（PII漏洩なし）

**INFO (PASS): 3コピー同期**
- lib/ / chatwork-webhook/lib/ / proactive-monitor/lib/ 全て IDENTICAL

**SUGGESTION: BrainMemoryEnhancement を _save_minutes_to_memory() 内でインスタンス化している**
- 毎回 Step 12 が実行されるたびに新しいインスタンスを生成。軽量だが無駄
- クラス属性として初期化（`__init__` で `self._memory = BrainMemoryEnhancement(organization_id)` など）が望ましい

**SUGGESTION: test_memory_failure_does_not_block_result の mock が async でない**
- `side_effect=RuntimeError(...)` で同期的に例外を投げるが、`_save_minutes_to_memory` は `async def` なので、`patch.object` がそのまま `side_effect` を設定した MagicMock（非async）になる
- Python の unittest.mock では、async メソッドに side_effect を設定した場合、AsyncMock が必要。ただし Python 3.8+ では `patch.object` が async 関数を自動でAsyncMockに変換するため、実際には動作する。テストは機能的に正しい。

## PR #654 supabase-sync/main.py /sync-org レビュー結果 (2026-02-20)

### スキーマ確認結果（db_schema.json）
- `user_departments` テーブル: `organization_id` カラムが存在しない（tables section / soulkun section 両方で確認済み）
- `user_departments.user_id`: `tables` section では `uuid` 型、`soulkun.*` section では `integer` 型 → スキーマ不一致（どちらかが古い。Phase 3-5 マイグレーションで uuid に変更された可能性）
- `roles.organization_id`: `character varying` 型。`WHERE organization_id = :org_id` は正しく動作（PostgreSQL auto-cast）
- `departments.organization_id`: `uuid` 型
- `users.id`: `uuid` 型（存在する）、`users.organization_id`: `character varying` 型

### Critical Issues in PR #654
- **C-1 (型不整合)**: `user_departments.user_id` が `integer` 型（soulkun section）なのに `CAST(:user_id AS uuid)` している。本番でエラーになる可能性。ただし `tables` section では `uuid` → どちらが最新か要確認。
- **C-2 (N+1クエリ)**: `sync_org_assignments()` でループ内に `conn.execute(SELECT)` + `conn.execute(UPDATE/INSERT)` がある。従業員×部署数分のクエリが発生。
- **C-3 (APIコールをトランザクション外で行い、同一接続でDB書き込み)**: Supabase API fetch は pool.connect() の外（正しい）。問題なし。

### WARNING Issues in PR #654
- **W-1 (str(e)をHTTPレスポンスに返す)**: line 1135 `"message": str(e)` → DB接続文字列・内部パスが漏洩しうる。鉄則#8違反。
- **W-2 (user_departments に organization_id フィルタなし)**: SELECT/UPDATE/INSERT すべてに org_id フィルタがない。ただしテーブル自体にカラムがない（PRE-EXISTING設計）。
- **W-3 (/sync-org に認証なし)**: `X-CloudScheduler` ヘッダーチェックなし。ただし deploy.sh で `--no-allow-unauthenticated` 設定。Cloud Run IAM で保護されている。
- **W-4 (Supabase全件取得にページネーションなし)**: `fetch_table()` にページネーション実装なし。1000件超えで全件取得。鉄則#5。PRE-EXISTING（既存エンドポイントと共通）。
- **W-5 (logger.warning の %s に e が入る)**: line 414 `logger.warning("Failed to parse departments_json: %s", e)` — departments_json の内容が漏れる可能性（PII含む場合）。

### supabase-sync のアーキテクチャ（確定）
- Cloud Run、`--no-allow-unauthenticated` = IAM認証必須（`allUsers` ではない）
- Cloud Scheduler が `X-CloudScheduler` ヘッダー付きで呼ぶ（/sync-org にはそのチェックがない — pre-existing gap）
- `CLOUDSQL_ORG_ID` はハードコードデフォルト値 `'5f98365f-e7c5-4f48-9918-7fe9aabae5df'` あり（pre-existing）
- 既存 `/` エンドポイント（form data sync）は同様の構造

## Phase D 予算アラート機能 (feature/admin-dashboard-phase2, 2026-02-21)

### 変更ファイル
- `api/app/schemas/admin.py`: BudgetUpdateRequest/BudgetUpdateResponse 追加
- `api/app/api/v1/admin/costs_routes.py`: PUT /costs/budget 追加
- `admin-dashboard/src/lib/api.ts`: updateBudget 追加
- `admin-dashboard/src/types/api.ts`: BudgetUpdateRequest/Response 型追加
- `admin-dashboard/src/pages/costs.tsx`: 予算設定フォームUI追加
- `proactive-monitor/main.py`: _try_cost_budget_alert() 追加

### ai_monthly_cost_summary スキーマ（確認済み）
- UNIQUE(organization_id, year_month) → ON CONFLICT 句は正しい
- budget_status CHECK: `('normal', 'warning', 'caution', 'limit')`
- budget_remaining_jpy = budget_jpy - total_cost_jpy（コメントに記載）
- organization_id 型: UUID

### CRITICAL issues found
- **C-1: `budget_remaining_jpy` の計算式が逆** (costs_routes.py line 571, 575)
  - INSERT: `budget_remaining_jpy = -:budget_jpy` → 新規行（cost=0）では正しくは `budget_jpy`（残予算=予算全額）
  - UPDATE: `COALESCE(ai_monthly_cost_summary.total_cost_jpy, 0) - :budget_jpy` → 「コスト - 予算」= 負値になる
  - 正しくは `budget_jpy - COALESCE(total_cost_jpy, 0)`（予算 - コスト = 残予算）
- **C-2: `budget_status` が UPDATE 句で更新されない**
  - ON CONFLICT DO UPDATE に budget_status の更新がない
  - `check_budget_status` CHECK制約: 'normal'/'warning'/'caution'/'limit'（4段階）
  - だが costs_routes.py の GET monthly では CASE式で 'exceeded'/'warning'/'normal' の3値を計算している（budget_statusカラムを使っていない）
  - つまり budget_status カラムはGETクエリでは使われていないため、機能的影響は軽微（WARNINGレベル）

### WARNING issues found
- **W-1: require_admin (Level 5+) でなく require_editor (Level 6+) が正しいかもしれない**
  - 予算設定は「書き込み操作」。他の書き込み操作（部署作成/更新/メンバー更新）は `require_editor` (Level 6+)
  - 現在は `require_admin` (Level 5+) で保護されている
  - CLAUDE.md §8: Level 5=管理部/取締役、Level 6=代表/CFO
  - 予算設定は CFO 相当の権限が適切とも考えられる → require_editor への変更を検討すべき
- **W-2: year_month バリデーションなし**
  - `BudgetUpdateRequest.year_month: str` に `pattern=r"^\d{4}-\d{2}$"` がない
  - "2026-13", "invalid" などの不正値がDBに挿入される可能性
- **W-3: logger.info に budget_jpy 金額を記録** (costs_routes.py line 549-555)
  - `budget_jpy=body.budget_jpy` が INFO レベルでログに出力される
  - CLAUDE.md §9-3: 監査ログに金額を記録しない（漏洩リスク）。プロダクション向けログには不適切
  - log_audit_event の details にも `"budget_jpy": body.budget_jpy` が記録されている（同様）

### SUGGESTION issues found
- **S-1: proactive-monitor/main.py line 279**
  - `logger.warning(f"[CostAlert] Failed (non-critical): {e}")` → `{e}` が DB接続文字列を含む可能性
  - `type(e).__name__` 推奨（既存パターンと一致）
- **S-2: costs.tsx の budgetMutation エラーハンドリング**
  - `budgetMutation.isError` のエラーメッセージが "保存に失敗しました" のみ（API error detailを表示しない）
  - ユーザーが何を修正すればよいか不明。SUGGESTION レベル

### 3コピー同期
- proactive-monitor/main.py は lib/ のコピーではなく独自ファイル。同期不要。PASS。

## Task B: _update_user_preference (lib/brain/learning.py, 2026-02-21)

### DB schema key facts (verified from db_schema.json)
- `user_preferences` exists in BOTH soulkun (root section) and soulkun_tasks schema
  - Root section (`"user_preferences"`): organization_id=uuid, user_id=uuid, preference_type=varchar, preference_key=varchar, preference_value=jsonb, learned_from=varchar, confidence=numeric, sample_count=integer, classification=varchar. NO `id` column listed in flat section.
  - soulkun_tasks section (`"soulkun_tasks.user_preferences"`): same columns, id=uuid NOT NULL
- `soulkun_tasks.users`: organization_id = **character varying** (NOT uuid). `id` = uuid. `chatwork_account_id` = character varying (nullable=true)
- The pool in BrainLearning is passed from core/initialization.py (same pool used for brain_decision_logs). Likely soulkun_tasks DB.

### CRITICAL issue found
- **C-1 (CRITICAL)**: `WHERE u.organization_id = :org_id` in both INSERTs — `soulkun_tasks.users.organization_id` is **character varying**, NOT uuid. `CAST(:org_id AS uuid)` casts org_id to uuid for the INSERT value (correct), but the WHERE clause `u.organization_id = :org_id` passes org_id as text compared to varchar column — this is correct. NO PROBLEM here.
- **C-2 (CRITICAL)**: `learned_from = 'behavior'` in INSERT — `LearnedFrom` enum in `lib/memory/constants.py` has values: `AUTO="auto"`, `EXPLICIT="explicit"`, `A4_EMOTION="a4_emotion"`. `'behavior'` is NOT a valid LearnedFrom value. The column is varchar so no DB constraint prevents insert, but the value is semantically wrong and inconsistent with the enum.
- **C-3 (CRITICAL — async blocking)**: `_update_user_preference` is `async def` but calls `self._begin_with_org_context()` which calls `self.pool.begin()` synchronously. Same pattern as pre-existing bug in episodic_memory.py. Blocks the event loop.

### WARNING issues found
- **W-1**: `json.dumps(interaction_outcome)` where `interaction_outcome = "success"` or `"failure"` → produces `'"success"'` (JSON string with quotes). This is valid JSONB but storing a JSON-encoded string as the value of a JSONB column is unusual. `CAST('"success"' AS jsonb)` is valid in PostgreSQL. Functionally correct but semantically odd — direct string `"success"` without json.dumps would be stored as JSONB text type too via `CAST('success' AS jsonb)` (without quotes this would FAIL since 'success' is not valid JSON). So json.dumps is actually REQUIRED here. PASS.
- **W-2**: `communication` PreferenceType value — `PreferenceType.COMMUNICATION = "communication"` is valid (line 55 of constants.py). `feature_usage` = `PreferenceType.FEATURE_USAGE = "feature_usage"` is also valid (line 54). Both preference_type values MATCH the enum. PASS.
- **W-3 (WARNING)**: `_begin_with_org_context` is used for WRITE operations (INSERT) — correct choice over `_connect_with_org_context`. Provides transaction semantics. PASS.
- **W-4 (WARNING)**: No audit log for user preference writes. Not required (not confidential+ operation per CLAUDE.md §3 鉄則#3), PASS.
- **W-5 (SUGGESTION)**: `import sqlalchemy` is inside the function body (line 731). Should be at module top. Pre-existing pattern in this file (same in `_save_decision_log`).

### org_id filter check (C-5)
- INSERT uses subquery: `WHERE u.organization_id = :org_id AND u.chatwork_account_id = :account_id` — correct org isolation. If account_id not found for this org, zero rows inserted (safe failure). PASS.
- `CAST(:org_id AS uuid)` for the INSERT value is correct (organization_id column is uuid type). PASS.

### PII check
- `account_id` NOT in logs (line 801 explicitly notes CLAUDE.md §9-3). PASS.
- `response_style` and `interaction_outcome` are enum-like strings, not PII. PASS.

## Task D: episodic_memory recall → Brain context pipeline (feature/admin-dashboard-phase2, 2026-02-21)

### 変更概要（3ファイル）
- `lib/brain/core/initialization.py`: `from lib.brain.episodic_memory import create_episodic_memory` 追加。`self.episodic_memory = create_episodic_memory(pool=pool, organization_id=org_id)` を `BrainMemoryAccess` 初期化直後に追加。
- `lib/brain/models.py` line 719: `recent_episodes: List[Any] = field(default_factory=list)` を `BrainContext` に追加。
- `lib/brain/core/memory_layer.py` lines 200-211: Phase 2E ブロック直後に episodic recall ブロックを追加。

### 3コピー同期確認（PASS）
- 3コピー全て同一: lib/ / chatwork-webhook/lib/ / proactive-monitor/lib/ — `recent_episodes` (models.py), recall ブロック (memory_layer.py), `create_episodic_memory` import (initialization.py) 全て IDENTICAL。

### recall() の特性（重要）
- `recall()` は `self._memory_cache: Dict[str, Episode]` のみ参照（DB呼び出しなし、I/Oなし）
- `_recall_by_keywords`, `_recall_by_entities`, `_recall_by_temporal`, `_score_and_rank`, `_update_recall_stats` — 全てin-memoryのみ
- `asyncio.to_thread()` の使用は技術的に正しい（GILリリース、CPU仕事のオフロード）が実質不要（I/Oなし）。正確性は保たれているが誤解を招くコメント。

### CRITICAL issues
- **なし**（セキュリティ・データ整合性・Brain architecture 上の blocking issue は見つからなかった）

### WARNING issues
- **W-1 (型の弱さ)**: `recent_episodes: List[Any]` は型情報を失っている。正確には `List[RecallResult]` であるべき。ただし `RecallResult` は `episodic_memory.py` で定義されており models.py が直接 import するのが適切か要検討（循環 import リスクはない、episodic_memory.py は models.py を import しないため）。
- **W-2 (PII in logs)**: `episodic_memory.py` line 463 `f"... {message[:50]}..."` — recall() 内で message 先頭50文字をDEBUGログに出力。PRE-EXISTING（Task Dで新規導入ではない）。DEBUG levelなのでprodで問題なし。
- **W-3 (ダミー想起)**: `_memory_cache` はインスタンス生成時に空（`{}`）。Task Aで save_episode() 実装済みだが、キャッシュへの populate が async 経由（DB→キャッシュへの初回ロードは未実装）。つまり実行時に recall() は常に空リストを返す可能性が高い。`recent_episodes` は常に空で LLM に渡されない。機能的デッドコードの可能性。

### SUGGESTION issues
- **S-1 (asyncio.to_thread 不要)**: recall() は純粋にin-memory（I/Oなし）。`asyncio.to_thread()` は技術的に害はないが unnecessary overhead。コメント「キャッシュ参照のみ、高速」と矛盾している（to_threadはスレッドプール経由でむしろ遅い）。将来的にDB呼び出しが追加された場合に備えた防衛的コードとも解釈できる。
- **S-2 (hasattr ガード)**: `hasattr(self, 'episodic_memory')` は防衛的だが、`initialization.py` で `self.episodic_memory` が必ず設定されるため通常不要。ただしテスト時などで Brain が部分初期化された場合の安全ガードとして妥当。
- **S-3 (recent_episodes の消費先がない)**: `recent_episodes` は `BrainContext` に格納されるが、`build_context.py`（LangGraph）も `context_builder.py`（LLM Brain）も `recent_episodes` を参照していない。LLM プロンプトに挿入されない。格納するだけで LLM に渡らない — Task D は「パイプラインに接続」と銘打っているが実際には未接続。

### org_id filter (PASS)
- `EpisodicMemory.recall()` はin-memory cacheのみ参照。cacheは `self.organization_id` をキーとして org 分離されたインスタンス（`create_episodic_memory(organization_id=org_id)`）が保持。org_id leakなし。

## Task C: _update_conversation_summary (lib/brain/learning.py, 2026-02-21)

### 変更概要
- `BrainLearning.__init__` に `get_ai_response_func` 追加 + `_summary_update_times` dict追加
- `update_memory()` に `_should_update_summary(room_id)` 条件追加
- 新規: `_update_conversation_summary()`, `_build_summary_prompt()`, `_call_ai_for_summary()`, `_parse_summary_response()`, `_save_summary_sync()`, `_should_update_summary()`

### DB schema 確認（conversation_summaries）
- `conversation_summaries` は db_schema.json の root section には **ない**（tables セクションに存在）
- `tables.conversation_summaries`: id=uuid, organization_id=uuid, user_id=uuid, summary_text=text, key_topics=ARRAY, mentioned_persons=ARRAY, mentioned_tasks=ARRAY, conv_start/end=timestamptz, message_count=int, room_id=varchar, generated_by=varchar, classification=varchar
- **UNIQUE 制約なし** (organization_id, user_id, ...) → ON CONFLICT なし INSERT は重複行を生成しうる
- マイグレーション: `migrations/phase2_b_memory_framework.sql` で CREATE TABLE 定義確認済み

### CRITICAL issues
- なし（セキュリティ・テナント分離上のブロッカーなし）

### WARNING issues
- **W-1 (テストカバレッジ不足)**: `test_brain_learning.py` の `brain_learning` fixture に `get_ai_response_func` がない。`test_update_memory_generates_summary_when_threshold` でサマリー生成テストは通るが、実際は `get_ai_response` が None → LLM スキップ → `_update_conversation_summary` は return False。つまりテストは「サマリー生成パスを通らずに PASS」している。LLM あり時のサマリー実際生成パス（`_build_summary_prompt`, `_call_ai_for_summary`, `_parse_summary_response`, `_save_summary_sync`）に対するテストが存在しない。
- **W-2 (重複行の可能性)**: `conversation_summaries` に UNIQUE 制約なし。同じ room_id + user_id で SUMMARY_THRESHOLD を何度も超えた場合、ON CONFLICT なし INSERT により重複行が蓄積する。`_should_update_summary()` の 30分間隔制御はメモリ上のみ（プロセス再起動でリセット）。
- **W-3 (mentioned_persons が PII)**: `_build_summary_prompt` で LLM に人名抽出を依頼 → `mentioned_persons` 列に人名がDBに保存される。CLAUDE.md §9-2「業務に必要な事実は覚える」に合致するが、§9-3「名前は監査ログに入れない」との境界が曖昧。ここは会話記憶であり監査ログではないため設計上は許容範囲。
- **W-4 (create_learning factory に get_ai_response_func なし)**: line 1587 の `create_learning()` ファクトリ関数に `get_ai_response_func` パラメータが追加されていない。直接 `BrainLearning(...)` を使う initialization.py は問題ないが、他の呼び出し元（テスト等）が `create_learning()` を使う場合にサマリー機能を有効化できない。

### SUGGESTION issues
- **S-1**: `_parse_summary_response` の `re.search(r'\{[\s\S]*\}', response)` — 貪欲マッチ。通常のLLMレスポンス（数百文字）ではReDoSリスクなし。
- **S-2**: `_build_summary_prompt` の各メッセージを `msg.content[:200]` でカット。最大20件×200文字 = 4000文字がプロンプトに含まれる。許容範囲。

### PASS
- 3コピー同期: lib/ / chatwork-webhook/lib/ / proactive-monitor/lib/ 全て IDENTICAL
- asyncio.to_thread 使用正しい（`_save_summary_sync` は同期関数→to_thread経由）
- pool は QueuePool（同期）。to_thread 内で _begin_with_org_context → pool.begin() は正しい
- org_id フィルタ: INSERT の SELECT サブクエリで `WHERE u.organization_id = :org_id AND u.chatwork_account_id = :account_id` — 正しいテナント分離
- `CAST(:org_id AS uuid)` for INSERT value — conversation_summaries.organization_id は uuid 型 → 正しい
- `u.organization_id = :org_id` (users テーブル) — users.organization_id は character varying → text パラメータの比較は正しい
- PII ログなし: account_id はログに出ない（line 849-853で明示的に除外）
- LLM 不使用時 return False — ゴミデータをDBに入れない設計は正しい
- `_should_update_summary` の成功時のみ `_summary_update_times` 更新（失敗時は次回再試行できる設計）

## drive_tool.py パターン (lib/brain/drive_tool.py, feat/google-drive-full-setup, 2026-02-21)

### search_drive_files() 設計確認済み
- `accessible_classifications` ホワイトリスト検証: `{"public","internal","restricted","confidential"}` のみ許可。
- f-string SQL は `cls_placeholders`（`:cls0, :cls1` プレースホルダー名のみ）のみ。値は `cls_params` として parameterized → SQLインジェクションなし。
- RLS: `set_config('app.current_organization_id', :org_id, true)` で設定。`documents` テーブルに `documents_org_isolation` RLS ポリシーあり（`::uuid` キャスト、organization_id は uuid 型）。
- `organization_id` フィルタ: WHERE 句で `organization_id = :org_id` (EXPLICIT) + RLS の2重ガード。
- エラーログ: `type(e).__name__` のみ（PII漏洩なし）。エラーレスポンス: `type(e).__name__` のみ → 鉄則#8準拠。
- `with pool.connect() as conn:` で接続管理正しい（リークなし）。
- 3コピー同期: lib/ / chatwork-webhook/lib/ / proactive-monitor/lib/ 全て IDENTICAL (PASS)。

### accessible_classifications ハンドラー連携: PR #0221 で修正済み
- `_brain_handle_drive_search()` が `get_accessible_classifications_for_account()` を `asyncio.to_thread()` 経由で呼び出す実装に更新（2回連続 to_thread = 直列実行、正しい）。
- `account_id` が None のとき `str(account_id) if account_id else ""` で空文字→先頭ガードで最小権限フォールバック。安全側。
- `handler_wrappers/external_tool_handlers.py` は chatwork-webhook 固有（proactive-monitor/lib/ にはディレクトリ自体が存在しない）。3コピー同期対象外、bypass_handlers.py と同じパターン。

### WARNING (残存): get_accessible_classifications_for_account() の pool/スキーマ整合
- SQL: `FROM user_departments ud JOIN users u ON ud.user_id = u.id` で `u.id` を使う。
- `databases.soulkun.users` に `id` カラムは **存在しない**（`user_id: integer` のみ）。
- `databases.soulkun_tasks.users` には `id: uuid` が存在 → pool が soulkun_tasks DB を指す場合のみ動作。
- `search_drive_files()` は soulkun DB の documents テーブルを参照。2つの関数が異なる DB を参照している可能性があり、呼び出し元 `main.get_pool()` がどちらを返すか要確認。
- エラー時フォールバックは `["public", "internal"]`（安全側）なので CRITICAL でなく WARNING。

### WARNING: format_drive_files() がエラーメッセージをそのまま返す
- `format_drive_files()` line 196: `result.get('error', ...)` を返す。
- drive_tool.py の `error` フィールドには `type(e).__name__` のみ含まれる（安全）。
- ただしハンドラーが error_msg をメッセージに含める (external_tool_handlers.py line 240-241)。エラー内容がユーザーに届く。現状は `type(e).__name__` のみなので許容範囲。

### テストカバレッジ (test_drive_tool.py)
- 基本パス（正常/空/エラー/max_results/updated_at_none）はカバー済み。
- **TEST GAP**: `accessible_classifications` の新パラメータに対するテストが0件。
  - ホワイトリスト拒否テスト（無効な値が除外されるか）なし
  - デフォルト値適用テスト（None渡し→["public","internal"]になるか）なし
  - INスコープ絞り込みテスト（["confidential"]渡し→restrictedが返らないか）なし

### documents テーブル確認済みカラム（db_schema.json）
- organization_id: uuid, classification: character varying, is_searchable: boolean, deleted_at: timestamptz
- google_drive_web_view_link: text, file_name: character varying, title: character varying, updated_at: timestamptz

## Phase 2 form_employee tables migration (2026-02-21, reviewed)

### Migration: migrations/20260221_form_employee_tables.sql
- 4 new tables: supabase_employee_mapping, form_employee_skills, form_employee_work_prefs, form_employee_contact_prefs
- organization_id type: CHARACTER VARYING(255) — matching employees table pattern
- **WARNING (RLS型キャスト)**: All 4 RLS policies use bare `organization_id = current_setting(...)` WITHOUT `::text` cast.
  - Project's established pattern for VARCHAR org_id tables: `organization_id::text = current_setting(...)` (see migrations/20260209_runtime_tables_add_org_id.sql, 20260210_phase_c_meeting_tables.sql, 20260217_emergency_stop.sql, 20260216_google_oauth_tokens.sql)
  - PostgreSQL allows VARCHAR = TEXT comparison natively (no runtime error), but inconsistent with project convention and documented RLS safety rule (CLAUDE.md §3-2 #7)
  - FIX: Add `::text` cast: `organization_id::text = current_setting('app.current_organization_id', true)`
- **WARNING (WITH CHECK 句なし)**: All 4 RLS policies use `USING` only, no `WITH CHECK`. Without WITH CHECK, INSERT/UPDATE operations are not filtered by RLS. The USING clause alone only applies to SELECT/DELETE.
  - For INSERT/UPDATE tenant isolation, must add: `WITH CHECK (organization_id::text = current_setting('app.current_organization_id', true))`
- **PASS**: Rollback script exists (20260221_form_employee_tables_rollback.sql). 3-copy sync N/A (migration file).
- **PASS**: Indexes on organization_id and employee_id for all 4 tables.
- **PASS**: UNIQUE constraints on (employee_id, organization_id) for all 4 tables.

### PersonInfo.to_string() extension (models.py)
- _ATTR_LABELS tuple format: (lookup_key, display_label) e.g. ("スキル（得意）", "得意")
- supabase-sync writes person_attributes with full-label keys: "スキル（得意）", "稼働スタイル", "キャパシティ", "月間稼働", "連絡可能時間"
- `for key, label in _ATTR_LABELS` correctly maps tuple[0]→key and tuple[1]→abbreviated display label. FUNCTIONAL PASS.
- **WARNING (PII)**: attributes dict may contain personal preference data (skills, work style, hobbies). to_string() feeds LLM context — this is by design, but note attributes can include 'hobbies' TEXT which isn't included in _ATTR_LABELS filter. Only 5 safe operational keys are shown. OK.
- **SUGGESTION**: _ATTR_LABELS defined inside method body on every call. Should be module-level constant.
- 3-copy sync: lib/, chatwork-webhook/lib/, proactive-monitor/lib/ all IDENTICAL (PASS verified).

## Phase 3-B create_teaching (feat/admin-google-drive, 未コミット 2026-02-21)

### 変更ファイル (未コミット)
- `api/app/schemas/admin.py`: TEACHING_CATEGORY_VALUES, CreateTeachingRequest, TeachingMutationResponse 追加
- `api/app/api/v1/admin/teachings_routes.py`: POST /teachings (create_teaching) 追加, W-1修正
- `admin-dashboard/src/types/api.ts`: TEACHING_CATEGORIES 定数 + TeachingCategoryValue 型追加
- `admin-dashboard/src/pages/teachings.tsx`: 「教えを追加」ダイアログ (select dropdown)

### C-1 (PASS): TeachingMutationResponse 正しく使用
- `TeachingMutationResponse(status, teaching_id, message)` — フィールド正しい
- DepartmentMutationResponse は teachings_routes.py で一切参照されていない

### W-1 (PASS): organization_id フォールバック修正済み
- `get_teaching_penetration` (line 250): `user.organization_id or DEFAULT_ORG_ID` — PASS
- `create_teaching` (line 367): `user.organization_id or DEFAULT_ORG_ID` — PASS
- **REGRESSION (SUGGESTION)**: 既存3関数 (get_teachings_list/conflicts/usage_stats) が `or DEFAULT_ORG_ID or DEFAULT_ORG_ID` に変化 (二重 or は論理的に同一、バグではない)

### W-2 (PASS): category バリデーション
- `model_post_init` で ValueError → Pydantic v2 ValidationError に変換 — 動作確認済み
- `TEACHING_CATEGORY_VALUES` (15値) が DB CHECK constraint と完全一致 — 確認済み
- フロントエンドは `<select>` プルダウン (自由テキスト入力不可) — PASS
- `__get_validators__` メソッドは Pydantic v2 では完全無視 (IGNORED) — 副作用なし (SUGGESTION: 削除)

### その他確認項目
- SQL インジェクション: where_sql は静的な条件キーワードのみ。値は `:category` 等でパラメータ化 — PASS
- 監査ログ: 全5エンドポイントに `log_audit_event` あり — PASS
- エラーレスポンス: "内部エラーが発生しました" のみ — PASS (鉄則#8)
- CAST: `CAST(:org_id AS uuid)`, `CAST(:id AS uuid)`, `CAST(:ceo_uid AS uuid)` — ceo_teachings の各列は UUID 型、正しい
- conn.commit(): create_teaching の INSERT 後にあり — PASS
- org_id フィルタ: 全 SELECT に `organization_id = :org_id` あり — PASS
- ページネーション: limit le=200, 件数上限あり — PASS
- テストカバレッジ: CreateTeachingRequest/TeachingMutationResponse の直接ユニットテストなし — SUGGESTION
- ceo_teachings.category に DB CHECK 制約あり (phase2d_ceo_learning.sql) — バックエンドバリデーションとの二重防御でよい

## Topic files index

- `topics/proactive_py_history.md`: Full Codex/Gemini cross-validation findings pre-PR #614
- `topics/admin_dashboard_frontend.md`: admin-dashboard フロントエンドレビューパターン (Phase A-1 通貨表示バグ修正等)
- `topics/phase_b2_audit_db_write.md`: Phase B-2 監査ログDB永続保存 詳細レビュー結果
- `topics/drive_routes_review.md`: Google Drive Admin API (drive_routes.py) レビュー結果 (2026-02-21) — C-1: drive.readonly スコープでアップロード不可、C-2: mime_type カラム不存在

## fix/currency-display-jpy ブランチ フェーズ別サマリー

### Phase A-1 admin-dashboard 通貨表示修正
- CRITICAL: `kpi-card.test.tsx` line 22 `'$42.50'` → `'¥43'` 要修正
- 変更4ファイル 13箇所 $ → ¥ 変更済み。WARNING: `予算残高` ツールチップに通貨単位なし

### Phase A-2 document_generator.py タイムアウト有効化
- WARNING: `asyncio.TimeoutError` が専用クラスでなく汎用 `*GenerationError` にラップされる
- WARNING: `import time` が関数本体内にある (line 506)
- 詳細: `lib/capabilities/generation/document_generator.py`

### Phase B-1 mask_email PIIマスキング
- WARNING: `lib/drive_permission_manager.py` lines 542, 568 に `{email}` 生ログ残存 (3コピー全て)
- SUGGESTION: `mask_email()` 専用ユニットテストなし

### Phase B-2 監査ログDB永続保存
- WARNING: `lib/audit.py` line 367 `logger.warning("... %s", db_err)` — db_err に接続情報含む可能性 → `type(db_err).__name__` 推奨
- WARNING: `batch_N_folders` / `batch_N_items` の resource_id が DB で NULL 化 (非UUID のため)
- 詳細: `topics/phase_b2_audit_db_write.md`
