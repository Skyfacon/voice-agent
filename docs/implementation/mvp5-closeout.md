# MVP-5 Closeout

## MVP-5 Summary

MVP-5 closes the explicitly approved local wav verification slice:

```text
local wav opt-in
-> local-only wav gate
-> real ASR adapter boundary
-> real Thinker audio adapter boundary
-> Router
-> metadata-only route summary
```

The default acceptance path is provider-free. Real provider execution remains
manual opt-in only and is not part of deterministic replay or default tests.

## Goal 5 Evidence Ledger

| Track | Status | Evidence |
| --- | --- | --- |
| provider-free tests evidence | Passed | `./scripts/test tests/acceptance/test_mvp5_acceptance_scenarios.py -q`, Goal 1-4 runtime tests, replay test |
| fake transport evidence | Covered by tests | `tests/runtime/test_mvp5_live_voice_evidence.py`, `tests/runtime/test_mvp5_live_router_runner.py`, `tests/runtime/test_mvp5_live_route_results.py`, `tests/runtime/test_mvp5_real_voice_e2e_smoke.py` |
| replay safety evidence | Passed | `tests/replay/test_mvp5_live_route_replay.py` validates recorded metadata refs only |
| stdout/fixture safety evidence | Passed | acceptance manifest checks and smoke metadata checks require safety flags false |
| optional live smoke evidence status | Preflight passed; real wav smoke not run | DashScope env var presence was confirmed, but no approved local wav or pack was available for a real provider call |
| remaining non-goals | Stated below | No runtime scope expansion in Goal 5 |

## Scenario Coverage

| Scenario id | Coverage |
| --- | --- |
| MVP5-LIVE-WAV-INPUT-GATE-001 | Local wav input fails closed without explicit opt-in; opt-in metadata omits path and file name and keeps bytes in a local handle. |
| MVP5-LIVE-APPROVAL-GATE-001 | Approval gate requires live opt-in, local wav opt-in, adapter ids, request budget, timeout, metadata-only output, and credential env var presence. |
| MVP5-LIVE-ASR-THINKER-EVIDENCE-001 | Fake transport tests cover ASR and Thinker adapter-owned evidence for the same committed audio turn with safe refs and output modes. |
| MVP5-LIVE-ROUTER-AUTO-001 | Router consumes same-turn ASR and Thinker event ids and reports actual decision or mismatch without forcing a route. |
| MVP5-LIVE-ROUTE-DIRECT-001 | FAST_ONLY route returns direct-answer metadata, safe response ref, no SlowTask/UserPatch mutation, `real_tts_used=false`, and `voice_output=none`. |
| MVP5-LIVE-ROUTE-SLOWTASK-001 | SPAWN_SLOW_TASK route records ASR and Thinker refs in SlowTask create/planning evidence with task binding fields. |
| MVP5-LIVE-ROUTE-USERPATCH-001 | PATCH_ACTIVE_SLOW_TASK route emits current-plan `USER_PATCH_RECEIVED` with ASR authoritative evidence and Thinker hypothesis provenance only. |
| MVP5-LIVE-THREE-ROUTE-PACK-001 | Provider-free fake pack mode covers direct answer, SlowTask spawn, and UserPatch summaries, and reports mismatches without overriding Router. |
| MVP5-LIVE-SUMMARY-SAFETY-001 | Smoke JSON exposes safe ids, route status, output modes, refs, and safety booleans only. |
| MVP5-LIVE-REPLAY-SAFETY-001 | Deterministic replay uses recorded events and refs only and does not rerun providers, tools, clocks, random, env secret reads, or wav reads. |
| MVP5-LIVE-RAW-ARTIFACT-BLOCK-001 | Acceptance and runtime safety gates reject path-like refs, data refs, raw bytes, credential-like strings, and unsafe summary keys. |

## Safe Metadata Policy

Goal 5 closeout and committed fixtures are metadata-only. Safe live or fake
summaries may include:

- `status`
- `mode`
- `route_result_kind`
- `actual_route`
- `router_decision`
- `expected_route_matched`
- event ids and safe refs
- `provider_call_used`
- `fake_transport_used`
- `raw_audio_included=false`
- `raw_transcript_included=false`
- `raw_provider_body_included=false`
- `prompt_dump_included=false`
- `secret_included=false`
- `local_wav_path_included=false`
- `replay_reruns_provider=false`
- `real_tts_used=false`
- `voice_output=none`

## Optional Live Smoke Evidence Status

Current status: preflight passed; real wav smoke not run because no approved
local wav or pack was available.

Required approval shape for this closeout uses credential env var name
`DASHSCOPE_API_KEY`, provider adapter ids `mvp5_asr_adapter` and
`mvp5_thinker_adapter`, `max_provider_calls=6`, `timeout_ms=30000`, and
`safe_output_ref=summary://mvp5/goal5/live-evidence`.

Safe live evidence recorded in this closeout:

- preflight output: `DASHSCOPE_API_KEY present`
- provider_call_used=false
- fake_transport_used=false
- raw_audio_included=false
- raw_transcript_included=false
- raw_provider_body_included=false
- prompt_dump_included=false
- secret_included=false
- local_wav_path_included=false
- replay_reruns_provider=false
- real_tts_used=false
- voice_output=none

No live smoke stdout, local wav path, approval packet path, provider payload, or
model text is committed.

## Verification Commands

| Command | Result |
| --- | --- |
| `./scripts/test tests/acceptance/test_mvp5_acceptance_scenarios.py -q` | 6 passed |
| `./scripts/test tests/runtime/test_mvp5_live_audio_input.py -q` | 4 passed |
| `./scripts/test tests/runtime/test_mvp5_live_approval.py -q` | 7 passed |
| `./scripts/test tests/runtime/test_mvp5_live_voice_evidence.py -q` | 4 passed |
| `./scripts/test tests/runtime/test_mvp5_live_router_runner.py -q` | 2 passed |
| `./scripts/test tests/runtime/test_mvp5_live_route_results.py -q` | 3 passed |
| `./scripts/test tests/runtime/test_mvp5_real_voice_e2e_smoke.py -q` | 6 passed |
| `./scripts/test tests/replay/test_mvp5_live_route_replay.py -q` | 2 passed |
| `scripts/mvp5-real-voice-e2e --help` | passed |
| DashScope credential preflight | `DASHSCOPE_API_KEY present` |
| Approved live wav smoke | not run: no approved local wav or pack available |
| `git diff --check` | clean |
| `./scripts/test` | 1226 passed |

## Remaining Non-goals

- no realtime mic
- no full-duplex/AEC/barge-in
- no real TTS/voice out
- no real Slow LLM loop
- no production privacy claim
- no real external side effects
- no real tool execution
- no new canonical event
- no RouterDecision expansion

## ADR Stop Conditions

None encountered in Goal 5.
