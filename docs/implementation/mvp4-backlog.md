# MVP-4 Implementation Backlog

This document starts MVP-4 planning only. Slice 0 creates the backlog and
acceptance scenarios; it does not implement runtime code, call real providers,
read secrets, add provider SDKs, modify canonical events, or change ADRs.

MVP-4 proves the smallest real voice-input end-to-end path through Router and
SlowTask control-plane routes:

```text
synthetic/local wav
-> audio turn commit
-> real Thinker audio-native evidence as primary semantic evidence
-> real ASR transcript evidence in parallel
-> Router consumes ASR + Thinker event refs
-> FAST_ONLY | SPAWN_SLOW_TASK | PATCH_ACTIVE_SLOW_TASK
-> deterministic replay / safety summary
```

## MVP-4 Goal

MVP-4 validates that a committed audio turn can carry safe audio evidence refs
through the real Thinker audio-native path and the real ASR transcript path,
then route into the existing Router and SlowTask control-plane paths.

The end state is not a product voice agent. The target is a replayable,
repo-safe proof that voice evidence can drive:

- `FAST_ONLY` with a minimal text/event response summary.
- `SPAWN_SLOW_TASK` through the existing mock/control-plane create and planning
  path.
- `PATCH_ACTIVE_SLOW_TASK` through `USER_PATCH_RECEIVED` evidence provenance
  into an existing active SlowTask.

## MVP-4 Non-goals

- No runtime implementation in Slice 0.
- No real provider calls in Slice 0.
- No direct external model calls outside adapters.
- No provider SDK additions.
- No env secret reads in docs/safety slices.
- No canonical event additions or ADR edits.
- No realtime microphone, live capture UI, AEC, full-duplex, or barge-in scope
  expansion.
- No real TTS or voice output.
- No real Slow LLM agent loop.
- No real external side-effect tools.
- No multiple active SlowTasks, pause/resume, or production privacy policy.
- No raw audio, raw transcript, provider body, prompt dump, diagnostics, trace,
  local replay cache, or secrets in repo artifacts.

## Architecture Boundary Summary

- Access Layer may load a synthetic or explicitly opted-in local wav, but it
  must emit only safe audio span metadata into the journal.
- Interaction Controller remains the only owner of audio turn commit. ASR and
  Thinker run only after `TURN_INGRESS_COMMITTED`.
- Thinker audio-native output is primary semantic evidence, but it is not the
  owner of `SEMANTIC_COMMITMENT_EMITTED`.
- ASR output is transcript/text projection evidence, not semantic truth.
- Router consumes only committed-turn metadata and ASR/Thinker event refs. It
  must not copy raw ASR or Thinker payloads and must not choose a final
  ASR-vs-Thinker winner.
- SlowTask owns task semantics, evidence review, `plan_version`, confirmation,
  cancellation, and `SEMANTIC_COMMITMENT_EMITTED`.
- UserPatch is evidence. For voice patches it must preserve ASR/Thinker
  provenance and bind `task_id`, `plan_version`, `observed_plan_version`, and
  `task_event_seq`.
- Replay uses recorded events and refs only. It must not rerun ASR, Thinker,
  Slow LLM, TTS, tools, network, clocks, or random.

## Current Baseline From MVP-0/1/2/3

- MVP-0 has per-session event journal, text/audio ingress events,
  `TURN_INGRESS_COMMITTED`, mock ASR/Thinker, Router FAST_ONLY/IGNORE, mock
  Talker playback metadata, and deterministic replay foundations.
- MVP-1 has `TaskFocusState`, single active SlowTask, mock SlowTask lifecycle,
  `UserPatchEvidencePackRuntime`, `plan_version`, `task_event_seq`, stale result
  policy, SlowTask-owned confirmation/cancel, and replay coverage.
- MVP-2 has demo Tool Executor, UI patch, confirmation gates, Composer and
  coverage/truthfulness replay behavior. MVP-4 does not need to exercise these
  except to avoid violating their boundaries.
- MVP-3 has model adapter capability/profile contracts, adapter callback append
  boundary, real/fallback/degraded output labels, safe refs, ASR transcript
  output contract, Thinker semantic frame output contract, Slow LLM/TTS adapter
  contracts, and fallback/degraded replay gates.

## Real ASR / Thinker Baseline Now Available

Local `main` includes the LALM Thinker and ASR real provider work.

- ASR baseline:
  - `src/voice_agent/adapters/asr_runtime_adapter.py` provides an adapter-bound
    runtime wrapper that emits `ASR_TRANSCRIPT_OUTPUT_EMITTED` plus adapter
    degraded/retry/failure/validation events.
  - `src/voice_agent/runtime/asr_session_hook.py` provides a session-level
    opt-in ASR hook for committed audio turns.
  - ASR defaults to provider-free/no-call mode and requires explicit approved
    live-eval mode before transport use.
  - ASR summary metadata explicitly reports no raw audio, raw transcript,
    provider body, headers, or secrets.
- Thinker baseline:
  - `src/voice_agent/adapters/lalm_thinker_runtime_adapter.py` provides the
    real DashScope LALM Thinker text-turn runtime adapter.
  - `src/voice_agent/adapters/lalm_thinker_audio_native_smoke.py` proves a
    separate audio-native path over synthetic/local wav with metadata-only
    output summaries and `THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED`.
  - Current audio-native work is smoke-oriented. MVP-4 should first plan and
    test a provider-free fake path, then promote audio-native Thinker evidence
    into the E2E orchestrator without leaking raw audio or provider payloads.
- Router baseline:
  - `src/voice_agent/router/router.py` already accepts
    `ASR_TRANSCRIPT_OUTPUT_EMITTED` and
    `THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED` as understanding evidence.
- UserPatch baseline:
  - `src/voice_agent/user_patch/evidence_pack.py` already accepts real Thinker
    output, but ASR UserPatch construction currently validates only mock ASR.
    MVP-4 must plan this as a future implementation slice, not change it in
    Slice 0.

## Chosen MVP-4 Path

- Thinker audio-native is the primary semantic evidence.
- ASR runs in parallel and produces transcript/text projection evidence.
- Router consumes ASR and Thinker event refs:
  - `asr_frame_event_id` references `ASR_TRANSCRIPT_OUTPUT_EMITTED` or mock ASR.
  - `thinker_frame_event_id` references
    `THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED` or mock Thinker.
- Router outcome handling:
  - `FAST_ONLY` -> minimal response summary from fast path. This must not claim
    real TTS, mock playback, or voice out. Keep the response as acceptance
    runner metadata unless a later ADR-approved non-playback journal path
    exists.
  - `SPAWN_SLOW_TASK` -> existing SlowTask mock/control-plane create and
    planning path.
  - `PATCH_ACTIVE_SLOW_TASK` -> `USER_PATCH_RECEIVED` with ASR/Thinker evidence
    provenance into the active SlowTask.
- Input is synthetic/local wav only:
  - Synthetic wav can be generated by tests or smoke helpers.
  - Local user-provided wav is opt-in, local-only, and never committed.
  - Realtime microphone input is out of scope.

## Event Chain Targets For Each Router Outcome

### Common Voice Ingress And Evidence Chain

```text
SESSION_STARTED
-> ADAPTER_CAPABILITY_SNAPSHOT_RECORDED
-> AUDIO_SPAN_STARTED
-> SPEECH_START_DETECTED
-> TURN_OPENED
-> AUDIO_SPAN_ENDED
-> SPEECH_END_DETECTED
-> TURN_INGRESS_ACCEPTED
-> TURN_INGRESS_COMMITTED(input_modality=audio, audio_span_id=A)
-> THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED(input_modality=audio, audio_span_id=A)
-> ASR_TRANSCRIPT_OUTPUT_EMITTED(input_modality=audio, audio_span_id=A)
-> ROUTER_DECISION_EMITTED(asr_frame_event_id=..., thinker_frame_event_id=...)
-> TASK_FOCUS_STATE_UPDATED
```

ASR and Thinker order may differ in runtime, but Router must reference only
prior recorded evidence events for the same committed turn.

### FAST_ONLY Target

```text
common chain
-> ROUTER_DECISION_EMITTED(router_decision=FAST_ONLY, task_focus=FOREGROUND_CHAT or AMBIGUOUS)
-> TASK_FOCUS_STATE_UPDATED(foreground_mode=FAST_RESPONSE or SLOWTASK_ACTIVE)
-> minimal response summary
```

The minimal response summary may be acceptance-runner metadata such as
`response_text_ref`, `source_router_event_id`, and safety flags. It must not add
a canonical event. If an implementation slice requires a journaled fast text
response and no accepted non-playback event exists, that is an ADR stop
condition rather than a reason to invent a new event.

### SPAWN_SLOW_TASK Target

```text
common chain
-> ROUTER_DECISION_EMITTED(router_decision=SPAWN_SLOW_TASK, task_focus=NEW_TASK_CANDIDATE)
-> SLOWTASK_CREATED(source_evidence_refs include ASR + Thinker refs)
-> SLOWTASK_STATE_CHANGED(to_state=CREATED)
-> TASK_FOCUS_STATE_UPDATED(active_task_id=T)
-> PLANNING_STARTED
-> SLOWTASK_STATE_CHANGED(to_state=PLANNING)
-> EVIDENCE_REVIEWED(evidence_refs include ASR + Thinker refs)
-> optional ARGUMENTS_RESOLVED / ARGUMENT_RESOLUTION_PROVENANCE
-> FINALIZING
-> SEMANTIC_COMMITMENT_EMITTED
-> SLOWTASK_STATE_CHANGED(to_state=COMPLETED)
-> TASK_FOCUS_STATE_UPDATED(active_task_id=null)
```

This uses the current mock/control-plane SlowTask path. It must not introduce a
real Slow LLM loop.

### PATCH_ACTIVE_SLOW_TASK Target

```text
active SlowTask exists with current plan_version=N
common chain
-> ROUTER_DECISION_EMITTED(router_decision=PATCH_ACTIVE_SLOW_TASK, active_task_id=T)
-> TASK_FOCUS_STATE_UPDATED(active_task_id=T)
-> USER_PATCH_RECEIVED(
     task_id=T,
     plan_version=N,
     observed_plan_version=N,
     task_event_seq=next,
     evidence_ref=...,
     authoritative_evidence_refs include audio/asr refs,
     non_authoritative_hypothesis_refs include Thinker refs
   )
-> optional later USER_PATCH_INTERPRETED / PLAN_VERSION_ADVANCED in SlowTask slice
```

`USER_PATCH_RECEIVED` must not mutate task goal, constraints, resolved
arguments, confirmation state, or current plan by itself.

## SlowTask / UserPatch Evidence Provenance Policy

- `source_evidence_refs` and `evidence_refs` must include refs for both ASR and
  Thinker when both were available.
- Thinker refs may include `semantic_frame_ref`, `semantic_summary_ref`, and
  optional evidence refs with available/unavailable/degraded status.
- ASR refs may include `asr_frame_ref`, `text_ref`, and optional
  `audio_timestamps_ref`.
- UserPatch authoritative evidence should retain `audio_span_id`,
  `asr_frame_ref`, ASR n-best/text refs when available, and source event ids.
- UserPatch non-authoritative hypothesis should retain `semantic_frame_ref`,
  `semantic_summary_ref`, `task_focus`, `candidate_patch_types`, and provenance
  from Router/Thinker.
- Router metadata is non-authoritative. It may provide `task_focus_hint`,
  confidence, and uncertainty, but SlowTask must interpret final patch meaning.
- SlowTask evidence review and resolved arguments must reference source events
  or refs and remain current-plan bound.

## Data-plane And Safe-ref Policy

- Raw audio bytes stay in memory or local-only opt-in storage.
- Journal events carry `audio_span_id`, `audio_format_ref`, `audio_sample_offset`,
  duration, and safe refs only.
- Safe refs must not contain data URIs, local absolute paths, `file://`, provider
  URLs, diagnostics paths, traces paths, replay local cache paths, credential
  markers, or encoded raw payloads.
- Synthetic wav fixtures can be generated from code but committed fixtures must
  store only metadata and refs.
- Local user-provided wavs are allowed only by explicit opt-in and must be
  treated as `LOCAL_RAW_AUDIO`; they must not be copied into GitHub-safe
  fixtures.
- Provider response bodies, raw transcripts, prompt dumps, and raw semantic
  frames are not safe refs and must not enter committed artifacts.

## Provider / Live Eval Policy

- Slice 0 is docs only and provider-free.
- Slices 1, 2, 5, 6, 7, 8, and replay acceptance must be provider-free by
  default.
- Real Thinker and real ASR slices must require explicit opt-in mode, approved
  packet/config where applicable, fake transport tests, and no secret reads in
  default tests.
- No provider SDK may be added for MVP-4. Existing adapter transports may be
  reused only behind adapter boundaries.
- Live eval output must be metadata-only and must report:
  - `raw_audio_included=false`
  - `raw_transcript_included=false`
  - `raw_provider_body_included=false`
  - `secret_included=false`
  - explicit `output_mode`
- Replay and acceptance runners must never call providers.

## Replay And Fixture Safety Policy

- MVP-4 committed fixtures must use `fixture_domain=GITHUB_ALLOWED`,
  `replay_mode=deterministic`, `generated_from=synthetic` or redacted/minimal,
  and all safety flags false.
- Provider-free fixtures may contain fake ASR/Thinker events with synthetic refs.
- Real-provider smoke summaries may be local-only unless reduced to safe
  metadata-only synthetic/redacted fixtures.
- Replay must reject raw audio, raw transcript, raw provider body, prompt dumps,
  diagnostics, traces, local replay cache refs, data URIs, secrets, credential
  markers, and unredacted real user input.
- Replay must validate that Router evidence refs point to prior same-turn ASR and
  Thinker events.
- Replay must validate that SlowTask/UserPatch refs preserve provenance and do
  not use stale old-plan evidence as current-plan fact.

## Risks And ADR Stop Conditions

Stop and write/update an ADR before implementation if any slice requires:

- A new MVP-relevant canonical event name.
- A RouterDecision beyond `FAST_ONLY`, `SPAWN_SLOW_TASK`,
  `PATCH_ACTIVE_SLOW_TASK`, or `IGNORE`.
- Router selecting ASR vs Thinker winner or interpreting final UserPatch
  semantics.
- Thinker becoming owner of `SEMANTIC_COMMITMENT_EMITTED`.
- ASR transcript becoming semantic truth owner.
- Realtime microphone input, AEC, full-duplex semantic model, or barge-in scope
  expansion.
- Real TTS, voice out, or TTS playback as MVP-4 proof.
- Real Slow LLM agent loop.
- Multiple active SlowTasks or pause/resume.
- Direct provider calls from Router, SlowTask, replay, tests, or business
  modules.
- Raw artifacts or secrets in trace, fixture, or committed docs/examples.

## Slice Plan

### Slice 0: MVP-4 backlog + acceptance scenarios only

**Objective**

Create `docs/implementation/mvp4-backlog.md` and
`docs/specs/mvp4-acceptance-scenarios.md` from accepted ADRs and current MVP
baseline.

**Non-goals**

No runtime code, tests, provider calls, secret reads, SDK additions, canonical
event changes, ADR changes, or fixture generation.

**Likely files**

- Create: `docs/implementation/mvp4-backlog.md`
- Create: `docs/specs/mvp4-acceptance-scenarios.md`

**Contract constraints**

- Use only accepted canonical events.
- Mark all future implementation needs as future slices.
- Document ADR stop conditions instead of solving them.

**Tests / replay fixtures / smoke command**

- `git diff --check`
- No `./scripts/test` required for Slice 0 because it is docs-only.

**Definition of done**

- Both docs exist and cover goals, non-goals, event chains, safety gates, slices,
  scenarios, smoke commands, and closeout criteria.
- Git diff has no whitespace errors.

**Review checklist**

- No new event names are proposed.
- No provider call or secret-read instruction is embedded in Slice 0.
- No runtime implementation language sneaks into this slice as completed work.

**Suggested goal prompt**

`Start MVP-4 Slice 0: create the MVP-4 backlog and acceptance scenarios docs only. Do not implement runtime or call providers.`

### Slice 1: provider-free minimal voice E2E orchestrator with fake ASR + fake Thinker

**Objective**

Build a provider-free orchestrator over synthetic audio-turn events that emits
fake ASR and fake Thinker evidence, then routes through Router outcomes.

**Non-goals**

No real ASR, real Thinker, local wav loader, provider config, secrets, TTS, or
Slow LLM loop.

**Likely files**

- Create: `src/voice_agent/runtime/mvp4_voice_e2e_orchestrator.py`
- Create: `tests/runtime/test_mvp4_voice_e2e_provider_free.py`
- Create: `tests/fixtures/replay/mvp4/000-provider-free-voice-e2e.fixture.json`
- Modify: `tests/fixtures/replay/mvp4/manifest.index.json`

**Contract constraints**

- Emit only existing audio/interaction/mock understanding/Router/SlowTask events.
- Router consumes event ids and refs, not raw fake payloads.
- Orchestrator must not import live provider transports.

**Tests / replay fixtures / smoke command**

- `./scripts/test tests/runtime/test_mvp4_voice_e2e_provider_free.py -q`
- `./scripts/test tests/replay/test_mvp4_acceptance_scenarios.py -q`

**Definition of done**

- Provider-free fixture covers `FAST_ONLY`, `SPAWN_SLOW_TASK`, and
  `PATCH_ACTIVE_SLOW_TASK`.
- Replay passes without provider/tool/network/clock/random calls.

**Review checklist**

- Fake evidence uses `output_mode=mock`.
- No raw audio in fixture.
- No direct SlowTask mutation on patch path.

**Suggested goal prompt**

`Implement MVP-4 Slice 1 provider-free voice E2E with fake ASR and fake Thinker over synthetic audio events, plus deterministic replay.`

### Slice 2: synthetic/local wav input loader with safe artifact policy

**Objective**

Add a loader boundary for generated synthetic wav and explicit local wav opt-in,
mapping audio bytes to safe audio span metadata.

**Non-goals**

No realtime mic, no provider call, no audio-level replay by default, no raw audio
fixture.

**Likely files**

- Create: `src/voice_agent/runtime/mvp4_audio_input.py`
- Create: `tests/runtime/test_mvp4_audio_input.py`
- Modify: `docs/specs/mvp4-acceptance-scenarios.md`

**Contract constraints**

- Committed fixtures store safe refs/metadata only.
- Local user-provided wav must be local-only and blocked from GitHub fixtures.
- Loader must reject data URIs, unsafe absolute paths, and ignored trace/cache
  locations as committed refs.

**Tests / replay fixtures / smoke command**

- `./scripts/test tests/runtime/test_mvp4_audio_input.py -q`
- `git diff --check`

**Definition of done**

- Synthetic wav can create an audio turn without committing bytes.
- Local wav opt-in is metadata-only and blocked from replay export.

**Review checklist**

- `.gitignore` remains sufficient for local artifacts.
- No fixture contains bytes, base64, data URI, or raw path.

**Suggested goal prompt**

`Implement MVP-4 Slice 2 synthetic/local wav input loader with safe refs and no committed raw audio.`

### Slice 3: real Thinker audio-native path as primary semantic evidence

**Objective**

Promote the existing LALM Thinker audio-native smoke shape into the MVP-4
orchestrator as the primary semantic evidence path.

**Non-goals**

No ASR integration, no Router fusion changes beyond accepting Thinker refs, no
provider call in default tests, no SDK addition, no raw provider payload.

**Likely files**

- Modify: `src/voice_agent/adapters/lalm_thinker_audio_native_smoke.py`
- Possibly create: `src/voice_agent/adapters/lalm_thinker_audio_native_runtime.py`
- Modify: `src/voice_agent/runtime/mvp4_voice_e2e_orchestrator.py`
- Create: `tests/runtime/test_mvp4_thinker_audio_native_path.py`
- Modify: `tests/adapters/test_lalm_thinker_audio_native_smoke.py`

**Contract constraints**

- Real path stays behind the Thinker adapter boundary.
- `THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED` is caused by
  `TURN_INGRESS_COMMITTED`.
- Success uses safe refs and `output_mode=real|fallback|degraded`.
- Missing optional semantic fields must be explicit degraded metadata, not
  silent defaults.

**Tests / replay fixtures / smoke command**

- `./scripts/test tests/runtime/test_mvp4_thinker_audio_native_path.py -q`
- `./scripts/test tests/adapters/test_lalm_thinker_audio_native_smoke.py -q`
- Optional live smoke only after approval: existing audio-native smoke command.

**Definition of done**

- Provider-free fake transport proves audio-native Thinker event emission.
- Metadata confirms no raw audio, provider body, candidate text, prompt dump, or
  secret in output.

**Review checklist**

- Replay imports no live transport.
- Thinker evidence is primary semantic evidence but not SemanticCommitment.

**Suggested goal prompt**

`Implement MVP-4 Slice 3 real Thinker audio-native evidence path using fake transport tests first, preserving safe refs and replay provider-free behavior.`

### Slice 4: real ASR parallel transcript evidence

**Objective**

Run ASR in parallel to Thinker for the same committed audio turn and emit
`ASR_TRANSCRIPT_OUTPUT_EMITTED` as transcript/text projection evidence.

**Non-goals**

No ASR as semantic truth, no streaming ASR requirement, no raw transcript, no
Router winner selection.

**Likely files**

- Modify: `src/voice_agent/runtime/asr_session_hook.py`
- Modify: `src/voice_agent/runtime/mvp4_voice_e2e_orchestrator.py`
- Create: `tests/runtime/test_mvp4_asr_parallel_evidence.py`
- Possibly modify: `tests/runtime/test_asr_live_session_hook.py`

**Contract constraints**

- ASR output is caused by the committed audio turn.
- ASR safe refs must pass replay validation.
- Missing timestamps/streaming must produce degraded mode plus existing adapter
  degraded events.

**Tests / replay fixtures / smoke command**

- `./scripts/test tests/runtime/test_mvp4_asr_parallel_evidence.py -q`
- `./scripts/test tests/runtime/test_asr_live_session_hook.py -q`

**Definition of done**

- Fake transport tests prove ASR event emission in parallel with Thinker refs.
- Default mode remains provider-free/no-call.

**Review checklist**

- No ASR provider transport import outside adapter/runtime hook.
- No raw transcript or provider body in fixture or metadata.

**Suggested goal prompt**

`Implement MVP-4 Slice 4 ASR parallel transcript evidence for committed audio turns using existing ASR adapter/session hook boundaries.`

### Slice 5: Router fusion over ASR + Thinker refs

**Objective**

Validate Router consumes same-turn ASR and Thinker event refs and emits only
existing Router decisions.

**Non-goals**

No conflict arbitration, no field winner, no new task focus, no SlowTask
interpretation.

**Likely files**

- Modify: `src/voice_agent/router/router.py`
- Create: `tests/router/test_mvp4_voice_router_fusion.py`
- Modify: `src/voice_agent/replay/runner.py` only if existing validation needs
  MVP-4 fixture indexing, not new event semantics.

**Contract constraints**

- Router references evidence event ids only.
- Thinker focus hints may guide task focus, but Router does not own final
  semantic interpretation.
- Router decisions remain `FAST_ONLY`, `SPAWN_SLOW_TASK`,
  `PATCH_ACTIVE_SLOW_TASK`, or `IGNORE`.

**Tests / replay fixtures / smoke command**

- `./scripts/test tests/router/test_mvp4_voice_router_fusion.py -q`
- `./scripts/test tests/router/test_router_task_focus_mvp1.py -q`

**Definition of done**

- Router accepts real ASR plus real Thinker refs over audio turns.
- Conflicting evidence is preserved as uncertainty/provenance, not resolved by
  Router.

**Review checklist**

- No copied raw ASR/Thinker payload in Router event.
- No `task_id`/`plan_version` in Router spawn decision unless already accepted
  by existing contracts.

**Suggested goal prompt**

`Implement MVP-4 Slice 5 Router fusion over ASR and Thinker event refs without new decisions or conflict arbitration.`

### Slice 6: Router outcome handling

**Objective**

Connect Router outcomes to the minimal control-plane responses:
`FAST_ONLY`, `SPAWN_SLOW_TASK`, and `PATCH_ACTIVE_SLOW_TASK`.

**Non-goals**

No real TTS, no voice out, no real Slow LLM loop, no tool execution.

**Likely files**

- Modify: `src/voice_agent/runtime/mvp4_voice_e2e_orchestrator.py`
- Modify: `src/voice_agent/runtime/slowtask_orchestrator.py`
- Modify: `src/voice_agent/user_patch/evidence_pack.py`
- Create: `tests/runtime/test_mvp4_router_outcome_handling.py`

**Contract constraints**

- FAST_ONLY does not create or patch SlowTask.
- SPAWN uses existing mock/control-plane `SLOWTASK_CREATED` and planning events.
- PATCH creates `USER_PATCH_RECEIVED` with pre-advance plan bindings and
  ASR/Thinker provenance.
- SlowTask mock remains the only task semantic owner.

**Tests / replay fixtures / smoke command**

- `./scripts/test tests/runtime/test_mvp4_router_outcome_handling.py -q`
- `./scripts/test tests/user_patch/test_user_patch_evidence_pack.py -q`
- `./scripts/test tests/slowtask/test_slowtask_lifecycle_mvp1.py -q`

**Definition of done**

- One test each proves FAST_ONLY, spawn, and patch outcomes from voice evidence.
- Patch route preserves both ASR and Thinker refs.

**Review checklist**

- No `USER_PATCH_INTERPRETED` emitted by Router.
- No plan advance on `USER_PATCH_RECEIVED`.
- No real TTS/TTS synthesis event.

**Suggested goal prompt**

`Implement MVP-4 Slice 6 Router outcome handling for FAST_ONLY, SPAWN_SLOW_TASK, and PATCH_ACTIVE_SLOW_TASK over voice evidence.`

### Slice 7: SlowTask/UserPatch voice evidence provenance replay coverage

**Objective**

Add replay coverage that proves voice UserPatch and spawned SlowTask evidence
preserve ASR/Thinker provenance without raw payloads.

**Non-goals**

No new SlowTask states, no Slow LLM, no final conflict winner.

**Likely files**

- Create: `tests/replay/test_mvp4_voice_evidence_replay.py`
- Create/modify: `tests/fixtures/replay/mvp4/*.fixture.json`
- Modify: `src/voice_agent/user_patch/evidence_pack.py` if needed to accept real
  ASR events in UserPatch authoritative evidence.
- Modify: `src/voice_agent/replay/runner.py` only for existing-policy validation
  of MVP-4 fixtures.

**Contract constraints**

- `USER_PATCH_RECEIVED` binds `task_id`, `plan_version`,
  `observed_plan_version`, and `task_event_seq`.
- ASR/Thinker event refs in UserPatch must match Router refs.
- SlowTask evidence review must use refs only.

**Tests / replay fixtures / smoke command**

- `./scripts/test tests/replay/test_mvp4_voice_evidence_replay.py -q`
- `./scripts/test tests/replay/test_user_patch_received_replay.py -q`
- `./scripts/test tests/replay/test_slowtask_replay_mvp1.py -q`

**Definition of done**

- Replay reconstructs spawn and patch provenance.
- Replay rejects mismatched Router/UserPatch source refs.

**Review checklist**

- No raw audio/transcript/provider fields in evidence packs.
- No stale old-plan evidence advances current task.

**Suggested goal prompt**

`Implement MVP-4 Slice 7 replay coverage for SlowTask and UserPatch voice evidence provenance.`

### Slice 8: deterministic replay fixture + safety gates

**Objective**

Add MVP-4 fixture manifest, deterministic replay fixture(s), and safety gates
that reject unsafe artifacts and provider reruns.

**Non-goals**

No live provider eval runner as default acceptance, no generated raw trace
fixture.

**Likely files**

- Create: `tests/fixtures/replay/mvp4/README.md`
- Create: `tests/fixtures/replay/mvp4/manifest.index.json`
- Create: `tests/fixtures/replay/mvp4/008-replay-safety.fixture.json`
- Create: `tests/replay/test_mvp4_fixture_safety.py`
- Modify: `tests/replay/test_fixture_safety.py` if suite-level manifest support
  is centralized.

**Contract constraints**

- Fixture manifest safety flags must all be false for GitHub-allowed fixtures.
- Replay must not import live transports or read env secrets.
- Unsafe refs include data URI, raw/local trace/cache/audio paths, provider
  bodies, prompt dumps, and credential markers.

**Tests / replay fixtures / smoke command**

- `./scripts/test tests/replay/test_mvp4_fixture_safety.py -q`
- `./scripts/test tests/replay -q`

**Definition of done**

- Safety tests fail closed on unsafe audio/transcript/provider/secret fields.
- Deterministic replay passes from recorded refs only.

**Review checklist**

- Manifest lists every MVP-4 scenario id.
- No committed fixture is generated from raw local trace without redaction.

**Suggested goal prompt**

`Implement MVP-4 Slice 8 deterministic replay fixture and safety gates for voice E2E artifacts.`

### Slice 9: MVP-4 acceptance runner + closeout

**Objective**

Create an MVP-4 acceptance runner and closeout document showing all required
voice E2E scenarios pass under provider-free replay and gated live smoke
policies.

**Non-goals**

No PR claim that full-duplex, real TTS, realtime mic, or real Slow LLM is
complete.

**Likely files**

- Create: `tests/acceptance/test_mvp4_acceptance_scenarios.py`
- Create: `docs/implementation/mvp4-closeout.md`
- Modify: `tests/fixtures/replay/mvp4/manifest.index.json`
- Possibly create: `scripts/mvp4-voice-e2e-smoke`

**Contract constraints**

- Acceptance runner must be provider-free by default.
- Live provider smoke must be opt-in and metadata-only.
- Closeout must distinguish mock, real, fallback, and degraded outputs.

**Tests / replay fixtures / smoke command**

- `./scripts/test tests/acceptance/test_mvp4_acceptance_scenarios.py -q`
- `./scripts/test tests/runtime/test_mvp4_* -q`
- `./scripts/test tests/replay/test_mvp4_* -q`
- Optional approved live smoke command only when explicitly authorized.

**Definition of done**

- All required MVP-4 scenario ids pass.
- Closeout documents provider-free replay evidence, live smoke status, safety
  gates, limitations, and follow-up ADR stop items.

**Review checklist**

- No hidden provider/network call in acceptance runner.
- Closeout does not claim production voice agent, full-duplex, voice out, or
  real Slow LLM loop.

**Suggested goal prompt**

`Implement MVP-4 Slice 9 acceptance runner and closeout for minimal real voice input E2E through Router and SlowTask control-plane paths.`
