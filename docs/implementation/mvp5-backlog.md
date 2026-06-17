# MVP-5 Implementation Backlog

This document starts MVP-5 planning only. Slice 0 creates the backlog and
acceptance boundary docs; it does not implement runtime code, call providers,
read secrets, add provider SDKs, modify canonical events, or change ADRs.

MVP-5 promotes MVP-4's provider-free/local metadata proof into an explicitly
opted-in live verification runner over real local wav input:

```text
explicit local wav input
-> local-only raw audio read
-> audio turn commit metadata
-> real ASR adapter call
-> real Thinker audio-native adapter call
-> Router consumes ASR + Thinker event refs
-> FAST_ONLY | SPAWN_SLOW_TASK | PATCH_ACTIVE_SLOW_TASK
-> metadata-only live summary + local-only evidence pack
```

## MVP-5 Goal

MVP-5 validates that a human can provide real local wav audio, explicitly opt in
to live provider calls, run real ASR plus real Thinker through existing adapter
boundaries, pass recorded evidence refs through Router, and inspect safe
metadata-only results for the three existing Router/SlowTask paths:

- **Direct answer / FAST_ONLY**: Router emits `FAST_ONLY` and the runner returns
  a safe response summary. MVP-5 does not add voice output or TTS playback.
- **SlowTask spawn**: Router emits `SPAWN_SLOW_TASK` and the existing
  SlowTask mock/control-plane create/planning path is recorded.
- **UserPatch**: Router emits `PATCH_ACTIVE_SLOW_TASK` and
  `USER_PATCH_RECEIVED` preserves ASR authoritative evidence plus Thinker
  hypothesis provenance for the active task.

For a single wav input, the runner reports the one Router outcome produced by
the current Router. To prove all three paths, MVP-5 acceptance uses a local
three-case wav pack or equivalent local-only route verification manifest, with
one approved wav case per expected outcome.

## Relationship To MVP-4 And Main Branch State

MVP-5 depends on the MVP-4 voice E2E control-plane work being present before
runtime slices begin:

- provider-free voice E2E orchestrator;
- synthetic/local wav metadata loader;
- real Thinker audio-native fake transport path;
- real ASR fake transport/session hook path;
- Router outcome handling for FAST/SPAWN/PATCH;
- replay fixture safety gates and acceptance closeout.

This Slice 0 branch is intentionally based on current `origin/main`. If MVP-4
implementation commits are not merged into `main` yet, MVP-5 runtime slices must
first rebase onto, merge, or recreate the relevant MVP-4 artifacts. This docs
slice does not silently reimplement MVP-4.

## Source Contracts

- `AGENTS.md`
- `stage_b_adr_register.md`
- accepted ADRs, especially ADR-001, ADR-002, ADR-004, ADR-006, ADR-007,
  ADR-008, ADR-010, ADR-011, ADR-012, ADR-015, ADR-016
- `docs/specs/event-registry.md`
- `docs/specs/replay-spec.md`
- `docs/specs/state-reducers.md`
- `docs/specs/mvp4-acceptance-scenarios.md`
- `docs/implementation/mvp4-backlog.md`
- existing ASR and LALM Thinker live-eval approval and closeout docs under
  `docs/implementation/`

## MVP-5 Allowed Scope

- Local wav file metadata and bytes may be read only after explicit CLI opt-in.
- Live ASR and live Thinker calls may occur only through adapters and only after
  explicit approval packet/config and credential checks.
- Default automated tests remain provider-free, fake-transport, or guard-based.
- Live run output is JSON metadata only.
- Local live summaries may be written only under ignored local artifact roots.
- Router decisions remain the existing canonical values:
  `FAST_ONLY`, `SPAWN_SLOW_TASK`, `PATCH_ACTIVE_SLOW_TASK`, `IGNORE`.
- SlowTask/UserPatch behavior stays within existing MVP-1/MVP-4 control-plane
  semantics.

## MVP-5 Prohibited Scope

- No direct provider calls outside adapters.
- No provider calls in deterministic replay.
- No real provider calls in default CI/acceptance tests.
- No raw wav bytes, raw transcript, raw provider body, prompt dump, local trace,
  local replay cache, or secrets in committed artifacts.
- No env secret reads in provider-free tests or replay.
- No provider SDK additions unless already present and adapter-owned.
- No new canonical event names without ADR.
- No RouterDecision or task focus expansion without ADR.
- No realtime microphone, streaming capture UI, AEC, full-duplex, live
  barge-in, pause/resume, or multi active SlowTask.
- No real TTS, voice output, or playback as an MVP-5 acceptance requirement.
- No real Slow LLM agent loop.
- No real external tool side effects.
- No production privacy claim.

## Architecture Boundary Summary

- **Access / local input** reads local wav bytes only for the current live run.
  Journal events and summaries store safe refs and metadata, not file paths or
  bytes.
- **Interaction Controller** remains owner of turn commit. ASR and Thinker run
  only after `TURN_INGRESS_COMMITTED`.
- **ASR Adapter** emits `ASR_TRANSCRIPT_OUTPUT_EMITTED` with safe transcript
  refs and explicit `output_mode=real|fallback|degraded`.
- **Thinker Adapter** emits `THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED` with safe
  semantic refs and explicit `output_mode=real|fallback|degraded`.
- **Evidence joiner** may wait for both adapter outputs or surface a degraded
  missing-evidence result, but it must not invent model output.
- **Router** consumes only event ids and safe metadata. Router does not copy raw
  transcript, provider payload, semantic frame body, or prompt content.
- **SlowTask/UserPatch** remain the only owners of task mutation and patch
  interpretation.
- **Replay** consumes recorded metadata refs only and never reruns providers.

## Live Provider / Approval Policy

Every real-provider MVP-5 command must require:

- explicit flag such as `--live-provider`;
- explicit local wav opt-in such as `--allow-local-wav`;
- approval packet path or validated approval config;
- credential env var name, not credential value, with secret value never printed
  or written into trace;
- max request count and timeout budget;
- metadata-only output mode;
- local-only output root under an ignored path such as `outputs/`,
  `diagnostics/`, or `replays/local/`.

The runner must fail closed before provider calls if approval, credential, wav
validation, or safety checks fail.

## Input And Output Contract

Future smoke command shape:

```bash
scripts/mvp5-real-voice-e2e \
  --live-provider \
  --allow-local-wav \
  --local-wav <local-wav> \
  --expected-route auto \
  --approval-packet docs/implementation/<approved-packet>.md
```

Future three-route acceptance pack shape:

```bash
scripts/mvp5-real-voice-e2e \
  --live-provider \
  --allow-local-wav-pack <local-pack.json> \
  --approval-packet docs/implementation/<approved-packet>.md
```

Safe JSON summary fields should include:

- `run_id`
- `input_source=local_wav_opt_in`
- `local_wav_path_included=false`
- `raw_audio_included=false`
- `raw_transcript_included=false`
- `raw_provider_body_included=false`
- `secret_included=false`
- `provider_call_used=true`
- `asr_output_mode`
- `thinker_output_mode`
- `router_decision`
- `route_result_kind=direct_answer|slowtask_spawn|user_patch|ignore|degraded`
- `asr_event_id`
- `thinker_event_id`
- `router_event_id`
- `slowtask_event_ids`
- `user_patch_event_ids`
- `response_text_ref` or `result_summary_ref`
- `warnings`

The summary must not include the local absolute wav path or file name.

## Route Result Semantics

### Direct Answer / FAST_ONLY

MVP-5 direct answer means the live ASR+Thinker evidence caused Router to emit
`FAST_ONLY` and the runner can produce a metadata-only response summary. It is
not a claim that real TTS, playback, or a production answer generator exists.

### SlowTask Spawn

MVP-5 SlowTask spawn means Router emitted `SPAWN_SLOW_TASK`, and existing
SlowTask mock/control-plane events show `SLOWTASK_CREATED`, planning, evidence
review, and a safe commitment or result summary. It is not a real Slow LLM agent
loop.

### UserPatch

MVP-5 UserPatch means an active task existed before the wav turn, Router emitted
`PATCH_ACTIVE_SLOW_TASK`, and `USER_PATCH_RECEIVED` preserved:

- `task_id`
- `plan_version`
- `observed_plan_version`
- `task_event_seq`
- authoritative audio/ASR refs
- non-authoritative Thinker hypothesis refs

Patch receipt alone must not advance plan version or mutate task facts.

## Route Coverage Strategy

One arbitrary wav cannot be assumed to exercise all three paths. MVP-5 therefore
uses two acceptance modes:

- **Single-run mode**: one wav -> real ASR + real Thinker -> Router -> one
  metadata-only route result.
- **Three-route local pack mode**: three local wav cases with declared expected
  outcomes. Each case still runs real ASR + real Thinker and must naturally pass
  through Router to the expected outcome. The runner must report mismatches
  instead of forcing Router decisions.

## Replay And Fixture Policy

- Live runs are local-only by default.
- GitHub fixtures may contain only synthetic/redacted/minimal metadata derived
  from live summaries after review.
- Replay fixtures must not contain raw wav path, file name, bytes, transcript
  text, provider body, prompt dump, secret, or local output path.
- Deterministic replay must validate recorded events and refs only; it must not
  call ASR, Thinker, Router runtime, Slow LLM, TTS, tools, network, clock,
  random, or env secret reads.

## ADR Stop Conditions

Stop and update/create an ADR before implementation if any MVP-5 slice requires:

- new canonical event names for live run result, answer text, or route summary;
- direct provider calls from Router, SlowTask, tests, replay, or business logic;
- Router forcing route outcomes instead of reporting decisions;
- Router selecting ASR-vs-Thinker truth winner;
- Thinker owning `SEMANTIC_COMMITMENT_EMITTED`;
- ASR transcript becoming semantic truth;
- real Slow LLM loop;
- real TTS/voice output/playback;
- realtime mic, streaming capture, AEC, full-duplex, live barge-in, pause/resume,
  or multi active SlowTask;
- committed raw/local artifacts or secrets.

## Slice Plan

### Slice 0: MVP-5 backlog + acceptance boundary docs only

**Objective**

Create `docs/implementation/mvp5-backlog.md` and
`docs/specs/mvp5-acceptance-scenarios.md`.

**Non-goals**

No runtime code, tests, provider calls, secret reads, SDK additions, canonical
event changes, ADR changes, or fixture generation.

**Likely files**

- Create: `docs/implementation/mvp5-backlog.md`
- Create: `docs/specs/mvp5-acceptance-scenarios.md`

**Tests / checks**

- `git diff --check`

**Definition of done**

- Both docs define goals, non-goals, live approval boundary, data safety,
  route coverage, slice plan, acceptance scenario ids, smoke commands, and ADR
  stop conditions.

### Slice 1: prerequisite and safety baseline

**Objective**

Confirm the branch contains required MVP-4 artifacts or add a documented
prerequisite failure that blocks runtime slices.

**Non-goals**

No live provider calls and no attempt to recreate all MVP-4 slices silently.

**Likely files**

- Create: `tests/acceptance/test_mvp5_acceptance_scenarios.py`
- Possibly modify: `tests/conftest.py`
- Possibly create: `tests/fixtures/replay/mvp5/README.md`
- Possibly create: `tests/fixtures/replay/mvp5/manifest.index.json`

**Tests / checks**

- `./scripts/test tests/acceptance/test_mvp5_acceptance_scenarios.py -q`
- `git diff --check`

**Definition of done**

- MVP-5 acceptance tests fail closed if MVP-4 voice E2E prerequisites are
  absent.
- Fixture directory declares live-derived fixtures local-only unless redacted.

### Slice 2: local wav live input gate

**Objective**

Create a local wav input gate that reads wav bytes only after explicit opt-in and
returns safe metadata plus an opaque local-only audio handle for adapter calls.

**Non-goals**

No provider call, no realtime mic, no committed raw audio, no data URI support.

**Likely files**

- Create: `src/voice_agent/runtime/mvp5_live_audio_input.py`
- Create: `tests/runtime/test_mvp5_live_audio_input.py`

**Tests / checks**

- `./scripts/test tests/runtime/test_mvp5_live_audio_input.py -q`

**Definition of done**

- Without `--allow-local-wav`, local input fails closed.
- Output metadata redacts path and file name.
- Raw bytes are available only through an in-memory local handle and never enter
  journal/smoke JSON.

### Slice 3: live approval packet and credential gate

**Objective**

Define and validate a shared MVP-5 live approval gate for the combined ASR +
Thinker run.

**Non-goals**

No live provider request in default tests.

**Likely files**

- Create: `docs/implementation/mvp5-live-eval-approval-template.md`
- Create: `src/voice_agent/runtime/mvp5_live_approval.py`
- Create: `tests/runtime/test_mvp5_live_approval.py`

**Tests / checks**

- `./scripts/test tests/runtime/test_mvp5_live_approval.py -q`

**Definition of done**

- Missing approval, missing credential env var, over-budget request count, and
  unsafe refs fail closed before provider calls.

### Slice 4: real ASR + real Thinker live evidence runner

**Objective**

Run real ASR and real Thinker over the same local wav through adapter boundaries
and append normalized events for the same committed turn.

**Non-goals**

No Router outcome handling, no response generation, no TTS.

**Likely files**

- Create: `src/voice_agent/runtime/mvp5_live_voice_evidence.py`
- Create: `tests/runtime/test_mvp5_live_voice_evidence.py`
- Modify existing ASR/Thinker adapter smoke modules only if needed to expose
  adapter-owned functions without changing safety policy.

**Tests / checks**

- `./scripts/test tests/runtime/test_mvp5_live_voice_evidence.py -q`
- Optional approved manual live command only with explicit user approval.

**Definition of done**

- Fake transport tests prove event shape.
- Opt-in live run emits safe `ASR_TRANSCRIPT_OUTPUT_EMITTED` and
  `THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED`.
- No raw audio, raw transcript, provider body, prompt dump, or secret appears in
  journal or summary.

### Slice 5: Router live evidence fusion

**Objective**

Route live ASR + Thinker evidence refs and report one route result for a single
wav.

**Non-goals**

No forced route decisions, no new RouterDecision, no ASR/Thinker winner.

**Likely files**

- Create: `src/voice_agent/runtime/mvp5_live_router_runner.py`
- Create: `tests/runtime/test_mvp5_live_router_runner.py`

**Tests / checks**

- `./scripts/test tests/runtime/test_mvp5_live_router_runner.py -q`

**Definition of done**

- Single-run fake transport tests cover `FAST_ONLY`, `SPAWN_SLOW_TASK`, and
  `PATCH_ACTIVE_SLOW_TASK` using controlled safe evidence.
- Live mode reports the actual Router result and mismatches expected-route
  assertions without overriding Router.

### Slice 6: direct answer / FAST_ONLY result summary

**Objective**

Return a metadata-only direct answer route result when Router emits `FAST_ONLY`.

**Non-goals**

No real TTS, no playback, no new canonical answer event.

**Likely files**

- Modify: `src/voice_agent/runtime/mvp5_live_router_runner.py`
- Create/modify: `tests/runtime/test_mvp5_live_route_results.py`

**Tests / checks**

- `./scripts/test tests/runtime/test_mvp5_live_route_results.py -q`

**Definition of done**

- Summary includes safe `response_text_ref` or `result_summary_ref`,
  `real_tts_used=false`, and `voice_output=none`.

### Slice 7: SlowTask spawn and UserPatch route summaries

**Objective**

Record existing SlowTask spawn and UserPatch control-plane results from live
evidence.

**Non-goals**

No real Slow LLM loop, no tool execution, no plan advance from patch receipt
alone.

**Likely files**

- Modify: `src/voice_agent/runtime/mvp5_live_router_runner.py`
- Create/modify: `tests/runtime/test_mvp5_live_route_results.py`
- Create: `tests/replay/test_mvp5_live_route_replay.py`

**Tests / checks**

- `./scripts/test tests/runtime/test_mvp5_live_route_results.py -q`
- `./scripts/test tests/replay/test_mvp5_live_route_replay.py -q`

**Definition of done**

- Spawn path stores ASR/Thinker refs in `SLOWTASK_CREATED` and
  `EVIDENCE_REVIEWED`.
- Patch path stores ASR authoritative evidence and Thinker hypothesis refs in
  `USER_PATCH_RECEIVED`.

### Slice 8: three-route local pack smoke command

**Objective**

Create a manual smoke command that accepts a local three-case wav pack and
outputs metadata-only results for direct answer, SlowTask spawn, and UserPatch.

**Non-goals**

No committed raw wav pack, no automatic provider run in tests, no route forcing.

**Likely files**

- Create: `scripts/mvp5-real-voice-e2e`
- Create: `src/voice_agent/runtime/mvp5_real_voice_e2e_smoke.py`
- Create: `tests/runtime/test_mvp5_real_voice_e2e_smoke.py`

**Tests / checks**

- `./scripts/test tests/runtime/test_mvp5_real_voice_e2e_smoke.py -q`
- Manual approved live smoke command after user approval.

**Definition of done**

- Provider-free tests verify CLI redaction and expected JSON shape.
- Manual live smoke can run all three local wav cases and report route matches
  or mismatches without printing local paths or raw outputs.

### Slice 9: acceptance runner + closeout

**Objective**

Add an MVP-5 acceptance runner and closeout showing default provider-free tests,
fixture safety, and at least one explicitly approved local live eval summary
when available.

**Non-goals**

No production voice agent claim, no real TTS, no real Slow LLM loop.

**Likely files**

- Create: `tests/acceptance/test_mvp5_acceptance_scenarios.py`
- Create: `docs/implementation/mvp5-closeout.md`
- Modify: `tests/fixtures/replay/mvp5/manifest.index.json`

**Tests / checks**

- `./scripts/test tests/acceptance/test_mvp5_acceptance_scenarios.py -q`
- `./scripts/test tests/runtime/test_mvp5_* -q`
- `./scripts/test tests/replay/test_mvp5_* -q`
- `git diff --check`
- Optional approved live smoke command.

**Definition of done**

- Required scenario ids pass.
- Closeout distinguishes provider-free tests, fake transport tests, optional
  approved live provider evidence, and remaining non-goals.
