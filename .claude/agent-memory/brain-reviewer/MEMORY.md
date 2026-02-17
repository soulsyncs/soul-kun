# brain-reviewer Agent Memory

## Project key facts (verified)

- Python 3.11+ project, run tests with `python3 -m pytest` (not `python`)
- Working directory: `/Users/kikubookair/soul-kun`
- Logger names follow Python's `__name__` convention (e.g. `lib.audit` for `/Users/kikubookair/soul-kun/lib/audit.py`)
- PR review via `gh pr diff <number>` and `gh pr view <number> --json ...`

## Known pre-existing test failures (NOT regressions)

- `TestLogAuditAsync`, `TestLogDrivePermissionChange`, `TestLogDriveSyncSummary` (11 tests in `tests/test_audit.py`) fail locally due to missing/misconfigured pytest-asyncio plugin. pyproject.toml has `asyncio_mode` config that pytest warns is unknown. These failures pre-date any reviewed PR and should not be flagged as regressions.

## lib/audit.py patterns (confirmed in PR #571 / #574)

- Logger: `logger = logging.getLogger(__name__)` -> name is `"lib.audit"`
- Fallback path (no table): logs at INFO level: `"Audit (no table): ..."`
- Exception path: logs at WARNING: `"Audit log failed (non-blocking): ..."`, then INFO: `"Audit (fallback): ..."`
- Details line: `"   Details: ..."` (with 3 leading spaces) logged at INFO
- DB path: logs at INFO: `"Audit logged: ..."`
- PR #571 changed print() -> logging in lib/audit.py; PR #574 fixed tests accordingly

## caplog usage pattern for lib/audit.py tests

```python
with caplog.at_level(logging.INFO, logger="lib.audit"):
    result = log_audit(...)
assert "Audit (no table)" in caplog.text
```

- `caplog.at_level(logging.INFO, ...)` also captures WARNING and above (correct for catching both INFO and WARNING messages in same test)

## chatwork-webhook/main.py deployment config (confirmed PR #575)

- Dockerfile: `gunicorn main:app --workers 1 --threads 8 --timeout 540`
- 1 worker, 8 threads: in-memory dicts are shared within the process but NOT across restarts
- In-memory rate limiting dict is vulnerable to thread-safety (TOCTOU) with 8 threads
- `time` module is imported at top of file (line 6); safe to use `time.time()` in the webhook section
- `import collections as _collections` added in PR #575 at line 2962 is UNUSED (dead code)
- Telegram webhook security order: signature -> group restriction -> CEO check -> rate limit
  - WARNING: rate limit check is AFTER CEO check, so non-CEO accounts are rejected before rate limit;
    this is correct since non-CEO hits "not_ceo" branch first, not rate limit

## Review checklist quick notes

- For test-only PRs: verify only the changed file, run the modified tests, check for scope creep
- Tests-only changes don't require Brain architecture or org_id checks (22-item checklist items A-F largely N/A for pure test files)
- Always check if async test failures are pre-existing before flagging
- `e` in `logger.error("...: %s: %s", type(e).__name__, e, ...)` CAN contain PII from exception messages;
  prefer logging only `type(e).__name__` in production paths; acceptable tradeoff when exc_info=True already captures full traceback in logs

## Telegram channel adapter patterns (confirmed PR #576)

- room_id format: `tg:{chat_id}` (private) or `tg:{chat_id}:{topic_id}` (supergroup topic)
- metadata always carries `chat_id`, `topic_id` separately for use in send_message routing
- send_message is called with `room_id=chat_id` (NOT the namespaced room_id) so Telegram API gets the raw chat_id
- `BRAIN_ALLOWED_ROOMS` env var: if set to numeric ChatWork IDs only, Telegram `tg:` prefixed room_ids will NOT match and Brain falls back to error path (fallback_func=None → IntegrationResult(success=False)); safe but degraded behavior
- **kwargs in abstract ChannelAdapter.send_message: ChatworkChannelAdapter does NOT declare **kwargs; calling it with extra kwargs (e.g., message_thread_id=55) would raise TypeError. Currently safe because Telegram webhook always uses TelegramChannelAdapter, never ChatworkChannelAdapter. But is a type-safety gap.
- lib/ 3-copy sync verified: lib/, chatwork-webhook/lib/, proactive-monitor/lib/ all identical after this PR
