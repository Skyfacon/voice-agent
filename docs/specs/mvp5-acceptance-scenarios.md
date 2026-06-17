# MVP-5 Acceptance Scenarios

Source of truth: accepted ADR baseline, especially ADR-001, ADR-002, ADR-004,
ADR-006, ADR-007, ADR-008, ADR-010, ADR-011, ADR-012, ADR-015, ADR-016, plus
`docs/specs/event-registry.md`, `docs/specs/replay-spec.md`,
`docs/specs/state-reducers.md`, `docs/specs/mvp4-acceptance-scenarios.md`, and
`docs/implementation/mvp5-backlog.md`.

Scenario ids are acceptance labels, not journal event names. MVP-5 must not add
canonical events to satisfy these scenarios.

## MVP-5 Scope Statement

MVP-5 validates an explicitly opted-in live local wav verification path:

```text
local wav
-> local-only audio bytes
-> audio turn commit metadata
-> real ASR adapter evidence
-> real Thinker audio-native adapter evidence
-> Router consumes ASR + Thinker event refs
-> direct answer / FAST_ONLY
   or SlowTask / SPAWN_SLOW_TASK
   or UserPatch / PATCH_ACTIVE_SLOW_TASK
-> metadata-only JSON summary
```

MVP-5 does not validate realtime microphone input, full-duplex, AEC,
live barge-in, real TTS, voice output, real Slow LLM agent loop, real external
side effects, provider calls during replay, or production privacy.

## Required Scenarios

### MVP5-LIVE-WAV-INPUT-GATE-001

| Field | Spec |
| --- | --- |
| purpose | Validate local wav input is explicit, local-only, and safe before any provider call. |
| initial state | CLI receives a local wav path and no live approval yet. |
| event chain | local input validation -> audio metadata extraction -> subsequent `AUDIO_SPAN_STARTED` / `TURN_INGRESS_COMMITTED` metadata. |
| required assertions | Without `--allow-local-wav`, loading fails closed; with opt-in, raw bytes stay in memory only; summary and journal include no local absolute path, file name, raw bytes, data URI, or `file://` ref. |
| replay expectations | Replay fixtures contain only safe refs and cannot require local wav bytes. |
| forbidden behavior | No realtime mic, no data URI, no committed local path, no raw audio fixture. |
| artifact privacy requirements | Local wav is `LOCAL_RAW_AUDIO`; committed artifacts use synthetic/redacted/minimal refs only. |

### MVP5-LIVE-APPROVAL-GATE-001

| Field | Spec |
| --- | --- |
| purpose | Validate live provider execution requires explicit approval, bounded request budget, and safe credential handling. |
| initial state | MVP-5 live command requested with ASR + Thinker providers. |
| event chain | approval packet/config validation -> credential env var presence check -> capability snapshot metadata -> provider call allowed. |
| required assertions | Missing approval, missing credential, unsafe refs, or request budget overflow fails before provider calls; output mentions credential env var name only, never secret value. |
| replay expectations | Replay never reads approval files or env secrets. |
| forbidden behavior | No implicit env secret reads in default tests; no provider call without `--live-provider`; no secret in trace or summary. |
| artifact privacy requirements | Approval docs/templates must not contain real credentials. |

### MVP5-LIVE-ASR-THINKER-EVIDENCE-001

| Field | Spec |
| --- | --- |
| purpose | Validate real ASR and real Thinker audio-native adapter evidence are produced for the same committed wav turn. |
| initial state | Approved local wav live run with adapter configs and request budget. |
| event chain | `TURN_INGRESS_COMMITTED(input_modality=audio)` -> `ASR_TRANSCRIPT_OUTPUT_EMITTED(input_modality=audio)` and `THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED(input_modality=audio)` -> optional degraded/failure events. |
| required assertions | ASR and Thinker events match `turn_id`, `utterance_id`, `audio_span_id`, and `input_modality`; each output has explicit `output_mode`; refs are safe; missing optional fields degrade explicitly. |
| replay expectations | Replay consumes recorded refs and does not call ASR or Thinker providers. |
| forbidden behavior | No raw transcript text, provider body, provider schema, prompt dump, candidate text, raw wav bytes, or credential material. |
| artifact privacy requirements | Live summaries are metadata-only; committed fixtures are synthetic/redacted/minimal. |

### MVP5-LIVE-ROUTER-AUTO-001

| Field | Spec |
| --- | --- |
| purpose | Validate a single real wav run passes ASR + Thinker refs through Router and reports the actual Router decision. |
| initial state | One committed wav turn has ASR and Thinker evidence events. |
| event chain | live evidence chain -> `ROUTER_DECISION_EMITTED(asr_frame_event_id=..., thinker_frame_event_id=...)` -> `TASK_FOCUS_STATE_UPDATED` -> metadata-only route result. |
| required assertions | Router references prior same-turn evidence events; Router does not copy raw ASR/Thinker payloads; expected-route mismatches are reported, not forced. |
| replay expectations | Replay validates Router evidence refs from recorded events only. |
| forbidden behavior | No route forcing, no new RouterDecision, no ASR/Thinker winner, no Router-owned task mutation. |
| artifact privacy requirements | Route result stores ids/refs/status only. |

### MVP5-LIVE-ROUTE-DIRECT-001

| Field | Spec |
| --- | --- |
| purpose | Validate the direct answer route result when live evidence causes `FAST_ONLY`. |
| initial state | Approved wav case expected to route to foreground/direct answer. |
| event chain | live evidence chain -> `ROUTER_DECISION_EMITTED(router_decision=FAST_ONLY)` -> `TASK_FOCUS_STATE_UPDATED` -> direct-answer metadata summary. |
| required assertions | No `SLOWTASK_CREATED`; no `USER_PATCH_RECEIVED`; no `USER_PATCH_INTERPRETED`; no `PLAN_VERSION_ADVANCED`; summary has safe `response_text_ref` or `result_summary_ref`; `real_tts_used=false`; `voice_output=none`. |
| replay expectations | Replay reconstructs TaskFocusState and no SlowTask mutation. |
| forbidden behavior | No new response canonical event, no real TTS, no playback, no provider raw answer text. |
| artifact privacy requirements | Direct answer summary is synthetic/redacted metadata or safe ref only. |

### MVP5-LIVE-ROUTE-SLOWTASK-001

| Field | Spec |
| --- | --- |
| purpose | Validate live evidence can spawn the existing SlowTask control-plane path. |
| initial state | Approved wav case expected to indicate a new complex task; no active non-terminal SlowTask. |
| event chain | live evidence chain -> `ROUTER_DECISION_EMITTED(router_decision=SPAWN_SLOW_TASK)` -> `SLOWTASK_CREATED` -> `SLOWTASK_STATE_CHANGED` -> `PLANNING_STARTED` -> `EVIDENCE_REVIEWED` -> optional safe commitment/result summary. |
| required assertions | `SLOWTASK_CREATED.source_evidence_refs` and `EVIDENCE_REVIEWED.evidence_refs` include ASR and Thinker refs; every SlowTask event binds `task_id`, `plan_version`, and `task_event_seq`; SemanticCommitment, if emitted, is SlowTask-owned and current-plan. |
| replay expectations | Replay reconstructs the control-plane path without real Slow LLM provider calls. |
| forbidden behavior | No real Slow LLM loop, no tool execution, no multiple active SlowTasks, no Router-owned commitment. |
| artifact privacy requirements | Goal, arguments, provenance, and commitment refs are synthetic/redacted/minimal. |

### MVP5-LIVE-ROUTE-USERPATCH-001

| Field | Spec |
| --- | --- |
| purpose | Validate live evidence can patch an existing active SlowTask through `USER_PATCH_RECEIVED`. |
| initial state | Active non-terminal SlowTask `T1` with current `plan_version=N`; approved wav case expected to be an active-task patch. |
| event chain | live evidence chain -> `ROUTER_DECISION_EMITTED(router_decision=PATCH_ACTIVE_SLOW_TASK, active_task_id=T1)` -> `TASK_FOCUS_STATE_UPDATED(active_task_id=T1)` -> `USER_PATCH_RECEIVED(task_id=T1, plan_version=N, observed_plan_version=N, task_event_seq=next)`. |
| required assertions | Authoritative evidence includes audio and ASR provenance; non-authoritative hypothesis includes Thinker provenance; patch receipt alone does not mutate goal, constraints, resolved arguments, confirmation state, lifecycle state, or current plan. |
| replay expectations | Replay reconstructs UserPatch evidence queue and source refs; SlowTask state remains unchanged by receipt alone. |
| forbidden behavior | No Router-owned `USER_PATCH_INTERPRETED`, no immediate `PLAN_VERSION_ADVANCED`, no raw text shortcut confirmation, no forced ASR/Thinker winner. |
| artifact privacy requirements | Evidence pack contains refs and redacted/synthetic summaries only. |

### MVP5-LIVE-THREE-ROUTE-PACK-001

| Field | Spec |
| --- | --- |
| purpose | Validate a local three-case wav pack covers direct answer, SlowTask spawn, and UserPatch routes through real ASR + real Thinker + Router. |
| initial state | Local-only manifest lists three wav cases with expected outcomes `FAST_ONLY`, `SPAWN_SLOW_TASK`, and `PATCH_ACTIVE_SLOW_TASK`. |
| event chain | For each case: local wav gate -> live ASR/Thinker evidence -> Router -> route-specific control-plane events -> metadata-only summary. |
| required assertions | Each case naturally reaches its expected Router outcome; mismatches fail the pack without forcing Router; aggregate output reports one result per route kind. |
| replay expectations | Only redacted/minimal metadata may be exported; replay never reruns provider calls. |
| forbidden behavior | No committed wav pack, no local path in JSON, no route override, no raw transcript/provider body. |
| artifact privacy requirements | Local pack and raw wavs stay outside GitHub under ignored roots. |

### MVP5-LIVE-SUMMARY-SAFETY-001

| Field | Spec |
| --- | --- |
| purpose | Validate live command output is safe, metadata-only JSON. |
| initial state | Any MVP-5 single-run or three-route live result. |
| event chain | route result -> summary renderer -> stdout/local output. |
| required assertions | Summary includes `provider_call_used=true`, output modes, event ids, safe refs, route result kind, and safety booleans; summary explicitly has `raw_audio_included=false`, `raw_transcript_included=false`, `raw_provider_body_included=false`, `secret_included=false`, and `local_wav_path_included=false`. |
| replay expectations | Redacted summary can be checked by acceptance runner without provider rerun. |
| forbidden behavior | No raw wav path, file name, raw transcript, provider request/response/body/payload/schema, prompt dump, headers, authorization, cookie, token, API key, or credential. |
| artifact privacy requirements | Local summaries with any real-input metadata remain local-only unless redacted into synthetic/minimal fixtures. |

### MVP5-LIVE-REPLAY-SAFETY-001

| Field | Spec |
| --- | --- |
| purpose | Validate replay and acceptance never rerun providers or unsafe runtime components. |
| initial state | MVP-5 redacted/minimal replay fixture or metadata summary. |
| event chain | fixture/summary manifest -> recorded events -> replay reducers -> result. |
| required assertions | Replay does not import/call ASR live transport, Thinker live transport, Slow LLM, TTS, tools, network, clock, random, env secret reads, or local wav reads. |
| replay expectations | Deterministic replay passes from recorded events and refs only. |
| forbidden behavior | No provider rerun, no generated missing model output, no audio inference during replay. |
| artifact privacy requirements | `fixture_domain=GITHUB_ALLOWED`; all safety flags false. |

### MVP5-LIVE-RAW-ARTIFACT-BLOCK-001

| Field | Spec |
| --- | --- |
| purpose | Validate MVP-5 rejects raw audio, raw transcript, provider body, local paths, local traces/cache, and secrets from committed artifacts and stdout. |
| initial state | Fixture/export/stdout candidate includes one unsafe field or unsafe ref at a time. |
| event chain | safety validation -> rejection before replay/acceptance pass. |
| required assertions | Validation rejects wav bytes/base64, raw transcript, provider request/response/body/payload/schema, prompt dump, data URI, `file://`, absolute local paths, local wav file names, `audio/raw/`, `diagnostics/`, `traces/`, `replays/local/`, API keys, tokens, cookies, authorization headers, and credential-like refs. |
| replay expectations | Unsafe fixture does not replay as passed. |
| forbidden behavior | No best-effort redaction that silently lets unsafe committed artifacts pass. |
| artifact privacy requirements | Safe fixtures use synthetic/redacted/minimal refs only. |

## Required Default Verification Commands

Default commands must be provider-free and use the canonical test entrypoint:

```bash
./scripts/test tests/acceptance/test_mvp5_acceptance_scenarios.py -q
./scripts/test tests/runtime/test_mvp5_live_audio_input.py -q
./scripts/test tests/runtime/test_mvp5_live_approval.py -q
./scripts/test tests/runtime/test_mvp5_live_voice_evidence.py -q
./scripts/test tests/runtime/test_mvp5_live_router_runner.py -q
./scripts/test tests/replay/test_mvp5_live_route_replay.py -q
```

Doc-only slices may run:

```bash
git diff --check
```

## Optional Approved Live Smoke Commands

Live provider smoke is opt-in only and must not be part of default CI/replay:

```bash
scripts/mvp5-real-voice-e2e \
  --live-provider \
  --allow-local-wav \
  --local-wav <local-wav> \
  --expected-route auto \
  --approval-packet docs/implementation/<approved-packet>.md

scripts/mvp5-real-voice-e2e \
  --live-provider \
  --allow-local-wav-pack <local-pack.json> \
  --approval-packet docs/implementation/<approved-packet>.md
```

## Out-of-scope Rejection Cases

The MVP-5 suite must reject or flag:

- realtime microphone capture;
- full-duplex, AEC, live barge-in, pause/resume, or multi active SlowTask;
- real TTS or voice out as an acceptance requirement;
- real Slow LLM agent loop;
- new canonical event names;
- new RouterDecision or task focus values;
- route forcing instead of Router-produced outcomes;
- Router-owned cancel, confirmation, plan advance, semantic commitment, or
  ASR/Thinker winner;
- Thinker-owned SemanticCommitment;
- ASR transcript treated as semantic truth;
- UserPatch without `task_id`, `plan_version`, `observed_plan_version`, or
  `task_event_seq`;
- replay that reruns providers, tools, network, clocks, random, env secret reads,
  or local wav reads;
- committed raw audio, raw transcript, raw provider body, prompt dump,
  diagnostics, traces, local replay cache, unredacted real input, or secrets.

## Closeout Criteria

MVP-5 can close only when:

- all required scenario ids above are covered by default tests, fake transport
  tests, redacted/minimal fixtures, and optional approved live smoke evidence;
- local wav input is explicit opt-in and path-redacted;
- live provider calls require approval and fail closed before unsafe execution;
- real ASR and real Thinker events bind to the same committed audio turn;
- Router reports actual FAST_ONLY, SPAWN_SLOW_TASK, and PATCH_ACTIVE_SLOW_TASK
  outcomes across a three-case local pack without forcing decisions;
- route summaries are metadata-only and truthful about non-goals;
- deterministic replay passes from recorded refs only;
- fixture/export/stdout safety gates reject unsafe raw artifacts and secrets;
- closeout explicitly states remaining non-goals: no realtime mic, no
  full-duplex/AEC/barge-in expansion, no real TTS/voice out, no real Slow LLM
  loop, no production privacy claim, and no real external side effects.
