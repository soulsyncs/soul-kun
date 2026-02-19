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

## Topic files index

- `topics/proactive_py_history.md`: Full Codex/Gemini cross-validation findings pre-PR #614
