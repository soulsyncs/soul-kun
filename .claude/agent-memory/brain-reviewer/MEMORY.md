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

## ChatWork file attachment detection patterns (confirmed in PR adding extract_chatwork_files)

- `extract_chatwork_files(body)` in `lib/channels/chatwork_adapter.py`: pure function, regex `r'\[download:(\d+)\]'`, returns `[{"file_id": "..."}]` list, no filename stored (PII-safe)
- `_FILE_LABEL = "ファイル"` constant defined at module level
- In `parse_webhook()`: files extracted from `raw_body` BEFORE `clean_message()` is called. Order matters because `clean_chatwork_message` removes `[download:XXX]` via the catch-all `\[.*?\]` regex at line 72
- Placeholder format: `"[ファイルを送信]"` (1 file) or `"[ファイル2件を送信]"` (N files)
- Placeholder is prepended to clean_body if text exists, or set as sole body if text-only-file message
- This prevents `should_process` returning False for file-only messages (body would be empty without placeholder)
- `ChatworkChannelAdapter` is NOT yet wired into main.py ChatWork route (only Telegram route uses adapter pattern). The new code is ready but not yet activated for ChatWork main flow.
- main.py already has its own `re.findall(r'\[download:(\d+)\]', body)` at line 1100 for audio file detection (separate, pre-existing logic). No conflict.
- 3-copy sync verified: lib/, chatwork-webhook/lib/, proactive-monitor/lib/ all identical after this PR
- 18/18 tests pass

## Telegram Vision AI patterns (confirmed in PR adding image recognition)

- `download_telegram_file(file_id, bot_token)`: synchronous httpx.Client, 30s timeout, 20MB limit, 2-step (getFile → binary download). Returns bytes or None.
- `is_image_media(media_info)`: photo type OR document with "image/" MIME prefix. Video/voice/PDF = False.
- `IMAGE_ANALYSIS = "image_analysis"` BypassType added to `lib/brain/integration.py`
- `has_image` key in bypass_context triggers IMAGE_ANALYSIS bypass
- `ENABLE_IMAGE_ANALYSIS` env var: guards download+bypass_context population in main.py only (not inside handler)
- `handler_wrappers/bypass_handlers.py` is chatwork-webhook ONLY — not in root lib/ or proactive-monitor/lib/ (confirmed again)
- All 3 copies of integration.py are in sync for IMAGE_ANALYSIS changes (verified)
- 17/17 new tests pass

### Pre-existing architectural issues (from Telegram Vision AI PR #581, not fixed in ChatWork PR)

1. **Recursive `process_message()` call**: `_bypass_handle_image_analysis()` calls `integration.process_message()` from within a bypass handler that was itself called by `process_message()`. Avoids infinite loop only because `bypass_context=None` on second call. Violates Guardian/Authorization Gate layering. Pattern to follow: `meeting_audio` handler calls `bridge._handle_meeting_transcription()` directly instead.
2. **Raw Vision output bypasses Guardian Layer**: Handler returns `vision_content` directly without Brain/Guardian filtering.
3. **Blocking HTTP in pre-processing**: Both `_download_meeting_audio` and `_detect_chatwork_image` make synchronous httpx HTTP calls from the Flask request handler. Pattern is consistent (and pre-existing) in this codebase.

### `VisionAPIClient` import path in bypass handler

- `chatwork-webhook/lib/brain/handler_wrappers/bypass_handlers.py` imports `from lib.capabilities.multimodal.base import VisionAPIClient`
- At runtime in chatwork-webhook/ context, Python resolves to `chatwork-webhook/lib/capabilities/multimodal/base.py` — correct
- NOT tested in test suite for any PR (no test exercises `_bypass_handle_image_analysis()` directly)

## ChatWork Vision AI patterns (confirmed feat/chatwork-vision-ai branch review)

- `_IMAGE_EXTENSIONS` = set `{"jpg","jpeg","png","gif","webp","bmp","tiff","tif"}` in main.py (line 1138)
- `_detect_chatwork_image(body, room_id, sender_account_id, bypass_context)`: sync function in Flask route
  - Parses `[download:ID]` tags, calls Files API (GET /rooms/{room_id}/files/{file_id}) per file_id to get filename
  - BUG: imports `from lib.secrets import get_secret` (non-cached!) at line 1172 inside loop, instead of using module-level `get_secret` (which is `infra.db.get_secret` -> `lib.secrets.get_secret_cached`). Hits Secret Manager on each image detection.
  - DEAD IMPORT at line 1164: `from infra.chatwork_api import download_chatwork_file` (imported but never used)
  - `sender_account_id` parameter is accepted but never used inside the function body
  - Guard: only runs if `not audio_data` AND `ENABLE_IMAGE_ANALYSIS == "true"`
  - Sets: `bypass_context["has_image"] = True`, `["image_file_id"]`, `["image_room_id"]`, `["image_source"] = "chatwork"`
- bypass_handler: `result[0] if result else None` — `(None, None)` is truthy! `if result else None` returns `(None, None)`, then `result[0]` is `None`. Safe: `if not image_data:` downstream catches it.
- `download_chatwork_file` in infra/chatwork_api.py returns `(bytes, filename)` or `(None, None)`. SUCCESS = status_code < 400.
- Telegram path got `image_source = "telegram"` added explicitly (was previously missing, handler defaulted correctly)
- Tests: 19/19 pass. Source-level tests only (regex on .py file contents). No functional integration test for actual download/Vision path.
- Test dead code: `TestDetectChatworkImage._call_detect()` method (line 50) never called; `@patch("chatwork-webhook.main._detect_chatwork_image")` has invalid hyphen in module name. Harmless.
- Comment typo at line 2051: `bypas_context` (missing 's' in 'bypass')
- infra.db.get_secret = lib.secrets.get_secret_cached (cached, lru_cache(maxsize=32))
- lib.secrets.get_secret = non-cached version (hits Secret Manager or env var every call)

## Diagnostic log patterns (confirmed in branch diag/llm-brain-routing-check)

- Brain feature flag env var: `USE_BRAIN_ARCHITECTURE` (NOT `ENABLE_LLM_BRAIN` — deprecated)
  - `is_llm_brain_enabled()` defined in `lib/feature_flags.py` line 638
  - `ENV_BRAIN_ENABLED = "USE_BRAIN_ARCHITECTURE"` in `lib/brain/env_config.py`
  - Docstring in `initialization.py._init_llm_brain()` still says `ENABLE_LLM_BRAIN` (stale doc, not code bug)
- `LLMBrain` attributes: `self.model` (str), `self.api_provider` (APIProvider enum) — always set in constructor
  - `api_provider.value` is safe to call (enum, never None after __init__)
- `get_tools_for_llm()` returns list of dicts from `SYSTEM_CAPABILITIES` via `ToolConverter.convert_all()`
  - Each dict has `"name"` key (capability_key string), NOT PII
  - `t.get("name", "?")` access pattern is correct
  - SYSTEM_CAPABILITIES has ~254 entries in registry.py — tools list log line could be very long
- `ToolCall.tool_name`: str attribute, tool system name (e.g. "chatwork_task_create") — NOT PII, safe to log
- `_extract_confidence_value()` helper properly handles `.overall` pattern for confidence — used correctly in llm_inference.py
- `print()` vs `logger`: main.py fallback path uses `print()` (consistent with surrounding code; Flask context, no structured logger setup)
- Diagnostic log in `message_processing.py` uses `"SET"/"NONE"` instead of actual object reference — PII-safe
- 3-copy sync (lib/, chatwork-webhook/lib/, proactive-monitor/lib/) confirmed identical for all 4 lib files in this PR

## Telegram media support patterns (confirmed in PR adding photo/video/document/voice)

- `_extract_media_info(msg)` in `lib/channels/telegram_adapter.py`: pure function, priority order is photo > video > document > voice, returns {} for no media
- `extract_telegram_update()`: sets text = `msg.get("text","") or msg.get("caption","")`, then prepends `[{label}を送信]` placeholder if media present
- `raw_body` in ChannelMessage for media messages = the placeholder-prepended text (NOT the original empty string). There is no "original empty caption" distinction preserved at adapter level. Intentional design.
- `file_name` from document metadata is NOT logged (stays in metadata only). PII-safe.
- `media_type` IS logged in main.py line 3088: `media_type=%s`. This is safe (it's a type label like "photo", not user content).
- `clean_telegram_message()` is called on the placeholder text `[写真を送信]` — this is safe because the regex `^/\w+` does not match `[` prefix.
- media metadata structure in `ChannelMessage.metadata["media"]`: dict with keys `{media_type, file_id, file_unique_id, file_size, ...type-specific keys}`. Empty dict `{}` for text-only messages.
- Brain bypass check: media still goes through Brain via `integration.process_message()` at line 3108. No bypass.
- Thread safety: `_extract_media_info` and `_MEDIA_TYPE_LABELS` are pure/immutable. No shared mutable state added. Safe for 8-thread gunicorn.
- 77 tests pass (all new + pre-existing) after this PR.
