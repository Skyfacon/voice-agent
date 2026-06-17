# MVP-4 Closeout

## MVP-4 Summary

MVP-4 closes the minimal voice-input E2E control-plane slice:

```text
synthetic/local wav metadata
-> audio turn commit
-> Thinker audio-native evidence and ASR transcript evidence
-> Router fusion
-> FAST_ONLY, SPAWN_SLOW_TASK, or PATCH_ACTIVE_SLOW_TASK
-> deterministic replay and metadata-only smoke summary
```

The default acceptance path is provider-free. Real adapter boundaries are covered
by fake transport tests and metadata-only refs. Replay consumes recorded events
and refs only; it never reruns providers.

## Goal / Slice Completion Map

| Slice | Status | Evidence |
| --- | --- | --- |
| Slice 0 docs/backlog | Complete | `docs/implementation/mvp4-backlog.md`, `docs/specs/mvp4-acceptance-scenarios.md` |
| Slice 1 provider-free voice spine | Complete | `tests/runtime/test_mvp4_voice_e2e_provider_free.py`, `tests/fixtures/replay/mvp4/000-provider-free-voice-e2e.fixture.json` |
| Slice 2 synthetic/local wav input loader | Complete | synthetic metadata loader and opt-in local wav metadata loader in `src/voice_agent/runtime/mvp4_voice_e2e_orchestrator.py` |
| Slice 3 real Thinker audio-native path | Complete | fake transport path in `tests/runtime/test_mvp4_voice_e2e_real_evidence_paths.py` |
| Slice 4 real ASR parallel evidence | Complete | fake ASR transport path in `tests/runtime/test_mvp4_voice_e2e_real_evidence_paths.py` |
| Slice 5 Router fusion | Complete | `tests/router/test_mvp4_voice_router_fusion.py` |
| Slice 6 Router outcome handling | Complete | `tests/runtime/test_mvp4_router_outcome_handling.py` |
| Slice 7 SlowTask/UserPatch provenance replay | Complete | `tests/replay/test_mvp4_voice_evidence_replay.py` |
| Slice 8 replay fixture + safety gates | Complete | `tests/replay/test_mvp4_fixture_safety.py`, `tests/fixtures/replay/mvp4/008-replay-safety.fixture.json` |
| Slice 9 acceptance runner + closeout | Complete | `tests/acceptance/test_mvp4_acceptance_scenarios.py`, `scripts/mvp4-voice-e2e-smoke`, this closeout |

## Scenario Coverage

| Scenario id | Coverage |
| --- | --- |
| MVP4-VOICE-E2E-PROVIDER-FREE-001 | Provider-free fixture and acceptance test replay fake ASR and fake Thinker over synthetic audio metadata, without real provider events or env secret reads. |
| MVP4-VOICE-E2E-THINKER-AUDIO-001 | Fake transport covers the real Thinker audio-native adapter boundary and emits `THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED` without `SEMANTIC_COMMITMENT_EMITTED`. |
| MVP4-VOICE-E2E-ASR-PARALLEL-001 | Fake transport ASR path emits `ASR_TRANSCRIPT_OUTPUT_EMITTED` bound to the same turn and audio span as Thinker evidence; replay uses recorded refs. |
| MVP4-VOICE-E2E-ROUTER-FAST-001 | `run_mvp4_router_fast_only_voice_e2e()` and smoke `--route fast` verify `FAST_ONLY`, no SlowTask, no UserPatch, no TTS/playback. |
| MVP4-VOICE-E2E-ROUTER-SPAWN-SLOWTASK-001 | `run_mvp4_router_spawn_slowtask_voice_e2e()` and replay verify `SPAWN_SLOW_TASK`, SlowTask create/planning, and ASR/Thinker refs in `SLOWTASK_CREATED` and `EVIDENCE_REVIEWED`. |
| MVP4-VOICE-E2E-ROUTER-PATCH-SLOWTASK-001 | `run_mvp4_router_patch_active_slowtask_voice_e2e()` and replay verify `USER_PATCH_RECEIVED` task binding and ASR authoritative plus Thinker hypothesis provenance, without interpretation or plan advance. |
| MVP4-VOICE-E2E-TEXT-RESPONSE-001 | FAST, spawn, and patch runtime summaries expose safe `response_text_ref`, `real_tts_used=false`, and `voice_output=none`; no new response canonical event is added. |
| MVP4-VOICE-E2E-REPLAY-SAFETY-001 | Committed fixtures replay under provider, network, clock, random, and env guards. |
| MVP4-VOICE-E2E-RAW-ARTIFACT-BLOCK-001 | `validate_mvp4_fixture_safety` rejects raw audio, raw transcript, provider bodies, local paths, local trace/cache refs, and secrets. |

## Evidence Commands Run

Goal 5 verification run on 2026-06-16:

| Command | Result |
| --- | --- |
| `./scripts/test tests/acceptance/test_mvp4_acceptance_scenarios.py -q` | 11 passed |
| `./scripts/test tests/runtime/test_mvp4_voice_e2e_provider_free.py -q` | 10 passed |
| `./scripts/test tests/runtime/test_mvp4_voice_e2e_real_evidence_paths.py -q` | 2 passed |
| `./scripts/test tests/runtime/test_mvp4_router_outcome_handling.py -q` | 3 passed |
| `./scripts/test tests/router/test_mvp4_voice_router_fusion.py -q` | 4 passed |
| `./scripts/test tests/replay/test_mvp4_acceptance_scenarios.py -q` | 9 passed |
| `./scripts/test tests/replay/test_mvp4_voice_evidence_replay.py -q` | 14 passed |
| `./scripts/test tests/replay/test_mvp4_fixture_safety.py -q` | 34 passed |
| `scripts/mvp4-voice-e2e-smoke --route fast` | JSON `status=passed`, `provider_call_used=false`, `voice_output=none` |
| `scripts/mvp4-voice-e2e-smoke --route spawn` | JSON `status=passed`, `provider_call_used=false`, `voice_output=none` |
| `scripts/mvp4-voice-e2e-smoke --route patch` | JSON `status=passed`, `provider_call_used=false`, `voice_output=none` |
| `scripts/mvp4-voice-e2e-smoke --route provider-free` | JSON `status=passed`, `provider_call_used=false`, `voice_output=none` |
| `git diff --check` | clean |
| `./scripts/test` | 1192 passed |

## Fixture / Replay Safety Summary

- MVP-4 committed fixtures are GitHub-allowed, synthetic/redacted/minimal, and metadata-only.
- Fixture manifest safety flags remain false for raw audio, raw trace, real user input, secrets, unredacted tool results, and large raw web content.
- `allowed_re_eval_components=[]`; replay validates recorded events and refs only.
- Local wav metadata has `replay_export_allowed=false` and is never exported to a committed fixture by the smoke command.
- Smoke output includes safe ids, refs, and summaries only. It does not include raw audio bytes, raw transcript text, provider body, prompt dump, secrets, or local absolute wav path.

## Provider / Live Eval Policy

- Default MVP-4 acceptance is provider-free.
- Live provider smoke is opt-in only, outside default acceptance, and must stay metadata-only.
- Replay never reruns ASR, Thinker, Slow LLM, TTS, tools, network, clock, random, or env secret reads.
- Fake transport tests cover real adapter boundaries without adding provider SDKs or reading real env secrets.

## Manual Smoke Usage

```bash
scripts/mvp4-voice-e2e-smoke --route fast
scripts/mvp4-voice-e2e-smoke --route spawn
scripts/mvp4-voice-e2e-smoke --route patch
scripts/mvp4-voice-e2e-smoke --route provider-free
scripts/mvp4-voice-e2e-smoke --route fast --local-wav /tmp/example.wav --allow-local-wav
```

Local wav mode is explicit opt-in. The command reads wav metadata only and does
not print the local path or file name.

## Explicit Limitations / Non-goals

- no realtime mic
- no full-duplex/AEC/barge-in expansion
- no real TTS / voice out
- no real Slow LLM loop
- no production privacy claim
- no real external side effects
- no real tool execution
- no production voice agent claim

## ADR Stop Conditions

none encountered.

MVP-4 used runtime summaries for fast text response. If a future fast text
response needs a canonical event, that future event design would require ADR
work before implementation.
