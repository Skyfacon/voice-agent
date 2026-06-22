# MVP6 Local Developer Debug Console Design

## Goal

MVP6 adds a local-only developer debug console for the existing MVP5 single-audio
routing path. The console lets a developer open a local page, record one audio
draft with the browser microphone, explicitly run that draft through the
provider-free or live-provider MVP5 path, and inspect Router/debug metadata in a
clear page.

The feature is a debug surface, not the production voice assistant UI. It should
reduce manual wav-file friction while preserving the same architecture and
safety boundaries established by MVP0-MVP5.

## User Outcomes

- Start a local debug console with one script.
- Record, stop, clear, and run a single browser microphone draft.
- Default to provider-free mode for fast UI and routing debugging.
- Explicitly switch to DashScope live provider mode when server-side approval
  and credential checks are ready.
- See route decisions, provider/fake flags, pipeline stage status, safe refs,
  and safety booleans in one page.
- Save a local-only QA/debug history record with ASR question text and a
  debug-friendly route answer, without saving raw audio.

## Non-Goals

- No realtime microphone streaming.
- No full-duplex, AEC, or live barge-in expansion.
- No real TTS or voice output.
- No real Slow LLM or Composer-generated assistant answer.
- No production demo UI claim.
- No real external side-effect tool execution.
- No new canonical event.
- No new RouterDecision value.
- No direct provider call outside adapters.
- No replay that reruns provider calls, reads local wavs, or reads env secrets.

## Recommended Approach

Use a single local Python debug server with plain HTML and JavaScript.

```text
Browser plain HTML/JS
  -> local Python debug server
  -> ignored local audio temp file
  -> existing MVP5 single-audio runtime
  -> ASR / Thinker / Router metadata result
  -> local-only QA history
  -> Browser debug display
```

The browser owns recording and display. The Python server owns approval checks,
provider mode gating, temporary local audio handling, MVP5 runtime invocation,
and QA history writes.

## File Boundaries

The implementation should keep the feature in small, testable units:

- `scripts/mvp6-debug-console`: executable entrypoint.
- `src/voice_agent/runtime/mvp6_debug_console_server.py`: local HTTP server and
  request dispatch.
- `src/voice_agent/runtime/mvp6_debug_console_api.py`: request/response schema,
  provider mode validation, and run orchestration boundary.
- `src/voice_agent/runtime/mvp6_debug_console_history.py`: local-only QA history
  writer/reader and redaction checks.
- `src/voice_agent/runtime/mvp6_debug_console_static.py`: embedded plain HTML,
  CSS, and JS assets.
- `tests/runtime/test_mvp6_debug_console_status.py`: status endpoint and startup
  safety.
- `tests/runtime/test_mvp6_debug_console_runs.py`: run endpoint behavior.
- `tests/runtime/test_mvp6_debug_console_history.py`: QA history behavior and
  redaction.
- `tests/acceptance/test_mvp6_acceptance_scenarios.py`: MVP6 acceptance matrix.
- `docs/implementation/mvp6-local-debug-console.md`: implementation closeout or
  operating notes.

## Page Design

MVP6 uses a Run-First Console plus Pipeline Inspector layout.

```text
Top status bar
- Provider: Fake / DashScope Live
- Approval: loaded / missing
- Credential: present / missing
- Last run status

Main run panel
- Record
- Stop
- Clear Recording
- Run
- recording duration
- draft audio status

Run controls
- Provider mode: Fake / DashScope Live
- Expected route: auto / FAST_ONLY / SPAWN_SLOW_TASK / PATCH_ACTIVE_SLOW_TASK
- Active task context fields for PATCH
- Save QA history: on by default

Latest result
- actual route / router decision
- route result kind
- expected route matched
- debug answer display
- provider_call_used / fake_transport_used

Pipeline inspector
- Local audio gate
- ASR
- Thinker
- Router
- QA history write
```

The UI state machine is intentionally simple:

```text
Idle
-> Recording
-> RecordedDraft
-> Running
-> Completed / Failed
```

Behavior rules:

- `Record` requests browser microphone permission and starts one recording.
- `Stop` creates a browser-memory audio draft.
- `Clear Recording` discards the draft and does not upload to the server.
- `Run` is enabled only when a draft exists.
- Starting a new recording discards the old unsubmitted draft.
- The server never returns local temp file paths or file names to the browser.
- The next run replaces the latest-result panel.

## Provider Modes

Default mode is provider-free fake mode.

Fake mode:

- Does not call real providers.
- Does not read real provider env secrets.
- Uses existing MVP5 provider-free fake transport behavior.
- Still runs through normalized evidence and Router decision code paths.

DashScope live mode:

- Is visible in the page as an explicit provider mode.
- Requires the server to be started with a valid approval packet.
- Requires credential presence to be checked server-side by env var name.
- Uses existing MVP5 ASR and Thinker adapter transports.
- Returns safe failure categories such as `approval_missing`,
  `credential_missing`, `provider_timeout`, `provider_request_failed`,
  `provider_response_parse_failed`, `provider_output_validation_failed`, and
  `unsupported_audio`.

The browser may select provider mode, but the server remains the authority for
whether live provider execution is allowed.

## Server Startup

The server starts with an explicit approval packet path when live provider mode
is needed:

```bash
scripts/mvp6-debug-console \
  --approval-packet outputs/mvp6-debug-console/approval.json
```

The page must not upload, edit, or display the approval packet path. It may
display safe approval metadata:

- `approval_loaded`
- `metadata_only_output`
- `credential_env_var_name`
- `credential_present`
- `max_provider_calls`
- `timeout_ms`

The credential value must never be returned, written to history, or logged.

## Local HTTP API

The server exposes a minimal local API:

```text
GET  /
GET  /api/status
POST /api/runs
GET  /api/history
POST /api/history/clear
```

### `GET /api/status`

Returns safe startup and readiness metadata:

```json
{
  "status": "ready",
  "provider_modes": ["fake", "dashscope_live"],
  "default_provider_mode": "fake",
  "approval_loaded": true,
  "credential_env_var_name": "DASHSCOPE_API_KEY",
  "credential_present": true,
  "metadata_only_output": true,
  "qa_history_enabled_default": true
}
```

It must not return the approval packet path, credential value, local output
directory, temp file path, or any provider payload.

### `POST /api/runs`

Accepts one browser audio blob and run controls:

```text
audio=<browser recording blob>
provider_mode=fake|dashscope_live
expected_route=auto|FAST_ONLY|SPAWN_SLOW_TASK|PATCH_ACTIVE_SLOW_TASK
active_task_id=...
active_plan_version=...
active_task_event_seq=...
active_lifecycle_phase=PLANNING
save_qa_history=true|false
```

The endpoint must reject client-supplied local paths. It writes received audio to
an ignored local temp/output path and calls existing MVP5 runtime code. It
returns metadata-only debug data, not the temp path or raw audio.

Representative response shape:

```json
{
  "status": "completed",
  "run_id": "mvp6_run_...",
  "provider_mode": "fake",
  "actual_route": "FAST_ONLY",
  "router_decision": "FAST_ONLY",
  "route_result_kind": "direct_answer",
  "expected_route_matched": true,
  "question_text": "local-only ASR text when available",
  "answer_display": "Router chose FAST_ONLY from FOREGROUND_CHAT evidence.",
  "pipeline": [
    {"stage": "local_audio_gate", "status": "passed"},
    {"stage": "asr", "status": "completed", "output_mode": "mock"},
    {"stage": "thinker", "status": "completed", "output_mode": "mock"},
    {"stage": "router", "status": "completed"}
  ],
  "safety": {
    "raw_audio_returned": false,
    "raw_audio_saved_to_history": false,
    "provider_body_returned": false,
    "secret_returned": false,
    "local_path_returned": false,
    "replay_reruns_provider": false
  }
}
```

`question_text` is allowed only for the local debug console response and local
QA history. It remains outside shareable replay fixtures and existing MVP5
metadata-only summaries.

### `GET /api/history`

Returns recent local-only QA history entries. The server should cap the default
response to a small number, such as the latest 20 entries, to keep the page
lightweight.

### `POST /api/history/clear`

Clears local-only QA history. It must not remove committed fixtures, replay
fixtures, traces, or any file outside the configured MVP6 output root.

## QA History

The default local history path should live under an ignored output root:

```text
outputs/mvp6-debug-console/qa-history.jsonl
```

Each record may include:

- `run_id`
- `created_at`
- `provider_mode`
- `question_source=asr_transcript`
- `question_text`
- `answer_kind=debug_route_answer`
- `answer_display`
- `actual_route`
- `router_decision`
- `route_result_kind`
- `asr_output_mode`
- `thinker_output_mode`
- `provider_call_used`
- `fake_transport_used`
- safe event ids and refs
- safety flags

QA history must not include:

- raw audio bytes or base64
- temp wav path or file name
- approval packet path
- provider request body
- provider response body
- provider schema
- prompt dump
- headers, cookies, tokens, API keys, or credential values
- replay cache paths

The page should label this clearly:

```text
QA history is local-only and may contain ASR user text.
```

## Debug Answer Semantics

MVP6 does not produce a final assistant answer. It produces a debug-friendly
answer display:

```text
Router chose SPAWN_SLOW_TASK from NEW_TASK_CANDIDATE evidence.
```

This keeps the slice within MVP5 routing boundaries. A future slice may add a
real text answer through Slow LLM, Composer, coverage checks, and approved output
flow.

## Security and Privacy Rules

- Bind to localhost by default.
- Do not accept browser-supplied local filesystem paths.
- Do not return local temp paths or file names.
- Do not return raw audio bytes or base64.
- Do not save raw audio to QA history.
- Do not return or save provider bodies.
- Do not return or save prompt dumps.
- Do not return or save credential values.
- Do not include approval packet paths in API responses.
- Do not write local debug artifacts outside ignored local-only roots.
- Do not commit local QA history, temp audio, traces, diagnostics, or replay
  cache.

## Test and Acceptance Plan

### Acceptance Scenarios

1. `MVP6-LOCAL-CONSOLE-STARTUP-001`: server binds locally and `GET
   /api/status` returns safe provider/approval/credential metadata.
2. `MVP6-MIC-DRAFT-RUN-001`: browser draft state requires explicit `Run`;
   `Clear Recording` does not upload or call runtime.
3. `MVP6-PROVIDER-FREE-RUN-001`: default fake mode completes one run without
   provider calls or real env secret reads.
4. `MVP6-LIVE-PROVIDER-GATE-001`: DashScope live mode is selectable but blocked
   without server-side approval and credential readiness.
5. `MVP6-PIPELINE-INSPECTOR-001`: run response includes local audio gate, ASR,
   Thinker, Router, and QA history stage statuses.
6. `MVP6-QA-HISTORY-001`: QA history saves ASR question text and debug answer by
   default, without raw audio.
7. `MVP6-SAFETY-REDACTION-001`: API responses and history reject raw audio,
   local paths, provider bodies, prompt dumps, and secrets.
8. `MVP6-NO-ARCHITECTURE-EXPANSION-001`: no new canonical event, no new
   RouterDecision, no adapter bypass, no realtime/full-duplex/TTS/Slow LLM.

### Test Files

- `tests/runtime/test_mvp6_debug_console_status.py`
- `tests/runtime/test_mvp6_debug_console_runs.py`
- `tests/runtime/test_mvp6_debug_console_history.py`
- `tests/acceptance/test_mvp6_acceptance_scenarios.py`

### Verification Commands

Use the repository test entrypoint:

```bash
./scripts/test tests/runtime/test_mvp6_debug_console_status.py -q
./scripts/test tests/runtime/test_mvp6_debug_console_runs.py -q
./scripts/test tests/runtime/test_mvp6_debug_console_history.py -q
./scripts/test tests/acceptance/test_mvp6_acceptance_scenarios.py -q
./scripts/test
```

## ADR Stop Conditions

Stop and update or create an ADR before implementation continues if MVP6 needs:

- a new MVP-relevant canonical event;
- a new RouterDecision value;
- direct provider calls outside adapters;
- Thinker-owned SlowTask, UserPatch, SemanticCommitment, ToolCall, ToolResult,
  confirmation, playback, or UI state mutation;
- replay that reruns providers, reads env secrets, or reads local audio;
- committed raw audio, raw ASR text from real users, provider body, prompt dump,
  local temp path, diagnostics, trace, replay cache, or secret;
- real TTS, real Slow LLM answer generation, realtime mic streaming,
  full-duplex, AEC, or barge-in expansion.

## Implementation Decisions

- Use Python standard-library HTTP serving, backed by focused request/response
  helpers, instead of adding a web framework dependency.
- Have the browser produce a wav-compatible `audio/wav` blob before upload. Use
  Web Audio APIs to collect microphone samples and encode a mono PCM WAV draft
  in browser memory. The server still validates the uploaded bytes as local audio
  input before calling MVP5.
- Store QA history as append-only jsonl under
  `outputs/mvp6-debug-console/qa-history.jsonl`.
- Return only the latest 20 QA history entries from `GET /api/history` by
  default.
- Implement `POST /api/history/clear` by clearing only the configured MVP6
  history file, never by deleting directories or using client-supplied paths.
