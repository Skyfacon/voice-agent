# MVP-4 Acceptance Scenarios

Source of truth: accepted ADR baseline, especially ADR-001, ADR-002, ADR-004,
ADR-006, ADR-007, ADR-008, ADR-010, ADR-011, ADR-012, ADR-016, plus
`docs/specs/event-registry.md`, `docs/specs/replay-spec.md`,
`docs/specs/state-reducers.md`, and `docs/implementation/mvp4-backlog.md`.

Scenario ids are acceptance labels, not journal event names. MVP-4 must not add
canonical events to satisfy these scenarios.

## MVP-4 Scope Statement

MVP-4 validates minimal real voice input E2E through Router and SlowTask
control-plane paths:

```text
synthetic/local wav
-> audio turn commit
-> Thinker audio-native semantic evidence
-> ASR transcript evidence in parallel
-> Router consumes ASR + Thinker refs
-> FAST_ONLY | SPAWN_SLOW_TASK | PATCH_ACTIVE_SLOW_TASK
-> deterministic replay / safety summary
```

MVP-4 does not validate realtime mic input, full-duplex, AEC, barge-in,
real TTS, voice output, real Slow LLM agent loop, real external side effects,
or production privacy.

## Required Scenarios

### MVP4-VOICE-E2E-PROVIDER-FREE-001

| Field | Spec |
| --- | --- |
| purpose | Validate the provider-free E2E voice control-plane path with fake ASR and fake Thinker over a synthetic audio turn. |
| initial state | Session started with mock/provider-free capability snapshot; no providers configured; synthetic audio metadata only. |
| event chain | `SESSION_STARTED` -> `ADAPTER_CAPABILITY_SNAPSHOT_RECORDED` -> audio ingress events -> `TURN_INGRESS_COMMITTED(input_modality=audio)` -> `MOCK_ASR_FRAME_EMITTED(output_mode=mock)` -> `MOCK_THINKER_FRAME_EMITTED(output_mode=mock)` -> `ROUTER_DECISION_EMITTED` -> outcome-specific events. |
| required assertions | No provider transport is imported or called; Router evidence ids point to same-turn fake ASR/Thinker events; output modes are mock; no raw audio bytes are in journal or fixture. |
| replay expectations | Deterministic replay passes using recorded events and refs only. |
| forbidden behavior | No `ASR_TRANSCRIPT_OUTPUT_EMITTED`, no real Thinker event, no env secret read, no provider SDK, no new canonical event. |
| fixture privacy requirements | GitHub-allowed fixture; synthetic refs only; all safety flags false. |

### MVP4-VOICE-E2E-THINKER-AUDIO-001

| Field | Spec |
| --- | --- |
| purpose | Validate the real Thinker audio-native path as primary semantic evidence while ASR is skipped or fake. |
| initial state | Committed synthetic/local audio turn; Thinker adapter path explicitly enabled through safe opt-in or fake transport test; ASR provider skipped or fake. |
| event chain | audio ingress events -> `TURN_INGRESS_COMMITTED(input_modality=audio)` -> `THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED(input_modality=audio, output_mode=real/fallback/degraded)` -> optional `MOCK_ASR_FRAME_EMITTED` -> `ROUTER_DECISION_EMITTED(thinker_frame_event_id=...)`. |
| required assertions | Thinker event is caused by the committed audio turn; refs are safe; optional semantic fields are available or explicitly degraded; Thinker is primary semantic evidence but does not emit `SEMANTIC_COMMITMENT_EMITTED`. |
| replay expectations | Replay consumes the recorded Thinker refs and does not call the Thinker provider. |
| forbidden behavior | No raw audio, provider body, provider schema, prompt dump, candidate text, secret, or Router conflict verdict. |
| fixture privacy requirements | Real smoke summaries are metadata-only; committed fixtures are synthetic/redacted/minimal. |

### MVP4-VOICE-E2E-ASR-PARALLEL-001

| Field | Spec |
| --- | --- |
| purpose | Validate real ASR transcript evidence in parallel to Thinker evidence for the same committed audio turn. |
| initial state | Committed audio turn; ASR adapter/session hook explicitly enabled through approved/fake transport test; Thinker evidence exists or is fake. |
| event chain | `TURN_INGRESS_COMMITTED(input_modality=audio)` -> `ASR_TRANSCRIPT_OUTPUT_EMITTED(input_modality=audio, transcript_finality=final)` plus required `ADAPTER_OUTPUT_DEGRADED` for missing timestamps/streaming -> Thinker evidence -> `ROUTER_DECISION_EMITTED(asr_frame_event_id=..., thinker_frame_event_id=...)`. |
| required assertions | ASR event matches `turn_id`, `utterance_id`, `audio_span_id`, and `input_modality`; ASR is transcript/text projection evidence only; Router stores event ids/metadata only. |
| replay expectations | Replay validates safe ASR refs and does not call ASR provider. |
| forbidden behavior | No raw transcript text, raw provider response, raw audio bytes, data URI, or ASR-as-semantic-truth behavior. |
| fixture privacy requirements | `asr_frame_ref`, `text_ref`, and optional timestamp refs are safe synthetic/redacted refs. |

### MVP4-VOICE-E2E-ROUTER-FAST-001

| Field | Spec |
| --- | --- |
| purpose | Validate Router consumes ASR + Thinker event refs and emits `FAST_ONLY`. |
| initial state | No active SlowTask, or active SlowTask with foreground/ambiguous input that must not patch. |
| event chain | common voice evidence chain -> `ROUTER_DECISION_EMITTED(router_decision=FAST_ONLY)` -> `TASK_FOCUS_STATE_UPDATED(foreground_mode=FAST_RESPONSE or SLOWTASK_ACTIVE)` -> minimal response summary. |
| required assertions | No `SLOWTASK_CREATED`; no `USER_PATCH_RECEIVED`; no `USER_PATCH_INTERPRETED`; no `PLAN_VERSION_ADVANCED`; minimal response does not claim real TTS or voice out. |
| replay expectations | Replay reconstructs `TaskFocusState` and unchanged `SlowTaskState` if an active task exists. |
| forbidden behavior | No task mutation, no new response event name, no real `TTS_SYNTHESIS_OUTPUT_EMITTED`. |
| fixture privacy requirements | Response summary uses `response_text_ref` or synthetic/redacted metadata only. |

### MVP4-VOICE-E2E-ROUTER-SPAWN-SLOWTASK-001

| Field | Spec |
| --- | --- |
| purpose | Validate Router emits `SPAWN_SLOW_TASK` and the existing SlowTask mock/control-plane create/planning path is recorded. |
| initial state | No active non-terminal SlowTask; voice evidence indicates a new complex task. |
| event chain | common voice evidence chain -> `ROUTER_DECISION_EMITTED(router_decision=SPAWN_SLOW_TASK, task_focus=NEW_TASK_CANDIDATE)` -> `SLOWTASK_CREATED` -> `SLOWTASK_STATE_CHANGED(to_state=CREATED)` -> `TASK_FOCUS_STATE_UPDATED(active_task_id=T)` -> `PLANNING_STARTED` -> `SLOWTASK_STATE_CHANGED(to_state=PLANNING)` -> `EVIDENCE_REVIEWED` -> optional `ARGUMENTS_RESOLVED` / `ARGUMENT_RESOLUTION_PROVENANCE` -> `FINALIZING` -> `SEMANTIC_COMMITMENT_EMITTED` -> `SLOWTASK_STATE_CHANGED(to_state=COMPLETED)` -> `TASK_FOCUS_STATE_UPDATED(active_task_id=null)`. |
| required assertions | `SLOWTASK_CREATED.source_evidence_refs` and `EVIDENCE_REVIEWED.evidence_refs` include ASR/Thinker refs; every SlowTask event binds `task_id`, `plan_version`, and `task_event_seq`; SemanticCommitment is SlowTask-owned and current-plan. |
| replay expectations | Replay reconstructs create/planning/completion without real Slow LLM or provider calls. |
| forbidden behavior | No real Slow LLM loop, no tool execution, no multiple active SlowTasks, no Router-owned commitment. |
| fixture privacy requirements | Goal, resolved arguments, provenance, and commitment refs are synthetic/redacted/minimal. |

### MVP4-VOICE-E2E-ROUTER-PATCH-SLOWTASK-001

| Field | Spec |
| --- | --- |
| purpose | Validate an existing active SlowTask receives voice UserPatch evidence bound to ASR + Thinker refs. |
| initial state | Active non-terminal SlowTask `T1` with current `plan_version=N`; voice evidence indicates active-task patch. |
| event chain | common voice evidence chain -> `ROUTER_DECISION_EMITTED(router_decision=PATCH_ACTIVE_SLOW_TASK, active_task_id=T1)` -> `TASK_FOCUS_STATE_UPDATED(active_task_id=T1)` -> `USER_PATCH_RECEIVED(patch_id=P1, task_id=T1, plan_version=N, observed_plan_version=N, task_event_seq=next, evidence_ref=E1)`. |
| required assertions | UserPatch authoritative evidence includes audio and ASR provenance; non-authoritative hypothesis includes Thinker provenance; patch receipt alone does not mutate goal, constraints, resolved arguments, confirmation state, lifecycle state, or current plan. |
| replay expectations | Replay reconstructs UserPatch evidence queue and source refs; SlowTask state remains unchanged by receipt alone. |
| forbidden behavior | No Router-owned `USER_PATCH_INTERPRETED`, no immediate `PLAN_VERSION_ADVANCED`, no raw text shortcut confirmation, no ASR/Thinker winner. |
| fixture privacy requirements | Evidence pack contains refs and redacted/synthetic summaries only. |

### MVP4-VOICE-E2E-TEXT-RESPONSE-001

| Field | Spec |
| --- | --- |
| purpose | Validate MVP-4 produces a minimal text/event response from fast or SlowTask control-plane path without real voice output. |
| initial state | Either `FAST_ONLY` route or SlowTask control-plane route completed/awaiting user. |
| event chain | For FAST_ONLY: Router fast chain -> response summary. For SlowTask: spawn or patch chain -> `SEMANTIC_COMMITMENT_EMITTED`, `CLARIFICATION_REQUESTED`, or other existing SlowTask control-plane event -> response summary. |
| required assertions | Response summary references source event ids and safe `response_text_ref`; it must be truthful about whether it comes from fast path, SlowTask mock, clarification, or degraded state. |
| replay expectations | Replay does not synthesize missing model output; response summary can be checked against recorded source events. |
| forbidden behavior | No real TTS, no playback claim, no `TTS_SYNTHESIS_OUTPUT_EMITTED`, no raw response text from provider. |
| fixture privacy requirements | Response text is synthetic/redacted or a safe ref; no prompt dump or provider body. |

### MVP4-VOICE-E2E-REPLAY-SAFETY-001

| Field | Spec |
| --- | --- |
| purpose | Validate replay uses recorded refs only and does not rerun providers or unsafe runtime components. |
| initial state | MVP-4 replay fixture with voice evidence, Router outcome, and optional SlowTask/UserPatch chain. |
| event chain | fixture manifest -> ordered events -> replay reducers -> `REPLAY_STARTED` / `REPLAY_COMPLETED` output or equivalent runner result. |
| required assertions | Replay does not import/call ASR live transport, Thinker live transport, Slow LLM, TTS, tools, network, clock, random, or env secret reads; state digest excludes raw/secret content. |
| replay expectations | Deterministic replay passes from recorded events and refs. |
| forbidden behavior | No provider rerun, no generated missing model output, no audio inference during replay. |
| fixture privacy requirements | `fixture_domain=GITHUB_ALLOWED`; all safety flags false. |

### MVP4-VOICE-E2E-RAW-ARTIFACT-BLOCK-001

| Field | Spec |
| --- | --- |
| purpose | Validate MVP-4 rejects raw audio, raw transcript, raw provider body, data URI, local traces/cache, and secrets. |
| initial state | Fixture/export candidate includes one unsafe field or unsafe ref at a time. |
| event chain | fixture/export validation -> rejection before replay pass. |
| required assertions | Validation fails for raw audio bytes/base64, `raw_transcript`, provider request/response/body/payload/schema, data URI, `file://`, `audio/raw/`, `diagnostics/`, `traces/`, `replays/local/`, absolute local user paths, API keys, tokens, cookies, authorization headers, and credential-like refs. |
| replay expectations | Unsafe fixture does not replay as passed. |
| forbidden behavior | No best-effort redaction that silently lets unsafe committed fixtures pass. |
| fixture privacy requirements | Safe fixtures use synthetic/redacted/minimal refs only. |

## Required Fixture / Replay Properties

- Every MVP-4 fixture must declare:
  - `manifest_schema_version`
  - `replay_id`
  - `source_trace_ref`
  - `replay_mode=deterministic`
  - `event_schema_version_range`
  - `fixture_domain=GITHUB_ALLOWED`
  - `generated_from=synthetic` or redacted/minimal
  - `contains_raw_audio=false`
  - `contains_raw_trace=false`
  - `contains_real_user_input=false`
  - `contains_secrets=false`
  - `contains_unredacted_tool_result=false`
  - `contains_large_raw_web_content=false`
  - `allowed_re_eval_components=[]`
- Events must use only canonical event names from ADR-002 / registry.
- Router evidence ids must reference prior same-turn ASR/Thinker evidence.
- Replay must reconstruct `InteractionState`, `TaskFocusState`, `SlowTaskState`,
  adapter health, and trace privacy state from recorded events only.
- State digest must exclude raw audio, raw text, provider bodies, prompts,
  secrets, and credential-like data.

## Required Safety Gates

- No direct external model calls outside adapters.
- No provider calls in default tests or replay.
- No env secret reads in provider-free tests, acceptance runner, or replay.
- No provider SDK additions.
- No canonical event additions.
- No ADR edits during MVP-4 implementation slices unless an ADR stop condition
  is reached and explicitly handled.
- No raw audio, raw transcript, provider body, prompt dump, diagnostics, trace,
  local replay cache, unredacted real user input, or secret in repo artifacts.
- `.gitignore` or equivalent repo exclusion must cover local-only artifact roots
  before any local artifact directory is created.
- Thinker audio-native is primary semantic evidence but not SemanticCommitment
  owner.
- ASR is transcript/text projection evidence but not semantic truth owner.
- UserPatch must preserve `task_id`, `plan_version`,
  `observed_plan_version`, `task_event_seq`, and ASR/Thinker provenance.

## Required Smoke Commands

Default MVP-4 verification commands must use the canonical test entrypoint:

```bash
./scripts/test tests/runtime/test_mvp4_voice_e2e_provider_free.py -q
./scripts/test tests/router/test_mvp4_voice_router_fusion.py -q
./scripts/test tests/runtime/test_mvp4_router_outcome_handling.py -q
./scripts/test tests/replay/test_mvp4_voice_evidence_replay.py -q
./scripts/test tests/replay/test_mvp4_fixture_safety.py -q
./scripts/test tests/acceptance/test_mvp4_acceptance_scenarios.py -q
```

Regression commands for existing boundaries:

```bash
./scripts/test tests/router/test_router_task_focus_mvp1.py -q
./scripts/test tests/user_patch/test_user_patch_evidence_pack.py -q
./scripts/test tests/slowtask/test_slowtask_lifecycle_mvp1.py -q
./scripts/test tests/runtime/test_asr_live_session_hook.py -q
./scripts/test tests/adapters/test_lalm_thinker_audio_native_smoke.py -q
```

Doc-only slices may run:

```bash
git diff --check
```

Live provider smoke commands are opt-in only and must not be part of default
replay/acceptance. They require explicit approval, approved packet/config, and
metadata-only output.

## Out-of-scope Rejection Cases

The MVP-4 suite must reject or flag:

- Realtime microphone capture.
- Full-duplex, AEC, live barge-in, or pause/resume scope.
- Real TTS or voice out as an MVP-4 completion requirement.
- Real Slow LLM agent loop.
- New canonical event names.
- New RouterDecision or task focus values.
- Router-owned cancel, confirmation, plan advance, semantic commitment, or
  ASR/Thinker conflict winner.
- Thinker-owned SemanticCommitment.
- ASR transcript treated as semantic truth.
- UserPatch without `task_id`, `plan_version`, `observed_plan_version`, or
  `task_event_seq`.
- Replay that reruns providers, tools, network, clocks, random, or env secret
  reads.
- Committed raw audio, raw transcript, raw provider body, prompt dump,
  diagnostics, traces, local replay cache, unredacted real input, or secrets.

## Closeout Criteria

MVP-4 can close only when:

- All required scenario ids above are covered by tests, fixtures, smoke
  summaries, or explicit documented non-live acceptance gates.
- Provider-free E2E passes for fake ASR + fake Thinker over synthetic audio turn.
- Thinker audio-native path produces safe primary semantic evidence through the
  adapter boundary.
- ASR emits safe parallel transcript evidence through the adapter/session hook
  boundary.
- Router consumes ASR + Thinker refs and covers FAST_ONLY, SPAWN_SLOW_TASK, and
  PATCH_ACTIVE_SLOW_TASK.
- SlowTask spawn path is recorded through existing mock/control-plane events.
- Voice UserPatch path preserves ASR/Thinker provenance and current-plan
  bindings.
- Deterministic replay passes from recorded refs only.
- Fixture/export safety gates reject unsafe raw artifacts and secrets.
- Closeout explicitly states remaining non-goals: no realtime mic, no
  full-duplex/AEC/barge-in expansion, no real TTS/voice out, no real Slow LLM
  loop, no production privacy claim.
