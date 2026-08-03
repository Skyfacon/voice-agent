# MVP6.2 Fast Foreground Interaction Design

## Status

Design document only. This document does not implement runtime code, call
providers, read secrets, add provider SDKs, create raw audio artifacts, or
change accepted ADRs.

MVP6.2 follows the same development style as MVP0 through MVP6.1: define the
boundary first, prove it with provider-free / fake paths, keep default tests
deterministic, and only then allow explicitly approved live provider work.

## Current Insight

The current audio path is already useful as a routing/debug spine:

```text
local wav / browser draft audio
-> local-only audio gate
-> TURN_INGRESS_COMMITTED
-> ASR Adapter
-> LALM Thinker Adapter
-> Router
-> metadata-only route summary
```

MVP5 proved this path for local wav input and real/fake ASR + Thinker evidence.
MVP6.1 wrapped the same path in a local debug console with browser draft audio,
provider-free default mode, local-only QA history, and safe metadata output.

The remaining user-visible gap is `FAST_ONLY`: it means "Router selected the
fast path", but it does not yet mean "the fast system produced a gated
foreground answer". The debug console therefore still displays a placeholder
such as "real fast answer is not implemented".

ADR-017 closes the architecture gap. It allows the fast model role to produce
route evidence, foreground act, and candidate reply in one adapter output, while
the runtime gate remains responsible for display, discard, template fallback, or
slow-system handoff.

## Source Contracts

MVP6.2 is governed by:

- `AGENTS.md`
- `stage_b_adr_register.md`
- ADR-001 Duplex / Interaction Controller
- ADR-002 Event Journal / canonical event registry
- ADR-006 Router Task Focus / single active SlowTask
- ADR-007 UserPatch Evidence Pack
- ADR-008 ASR / Thinker evidence fusion
- ADR-009 SemanticCommitment / Thinker-as-Composer
- ADR-010 Trace / Replay Debug Policy
- ADR-011 Model Adapter Capability Contract
- ADR-013 Truthful Progress Feedback
- ADR-015 Repository Governance
- ADR-016 SlowTask lifecycle / confirmation state
- ADR-017 Fast Interaction Adapter and Foreground Act Contract
- `docs/specs/event-registry.md`
- `docs/specs/replay-spec.md`
- `docs/specs/state-reducers.md`
- `docs/implementation/mvp5-backlog.md`
- `docs/implementation/mvp5-closeout.md`
- `docs/implementation/mvp6-local-debug-console.md`
- `docs/implementation/mvp6-streaming-fast-reply-design-note.md`

ADR-002 already contains the canonical ADR-017 event names. The derived
implementation registry in `docs/specs/event-registry.md` and the Python event
registry still need to be synchronized during implementation.

## MVP6.2 Goal

MVP6.2 turns `FAST_ONLY` from metadata-only routing into a replayable, gated
foreground text output path:

```text
committed audio turn
-> ASR evidence
-> Fast Interaction output
-> RouterDecision
-> Fast Foreground Gate
-> committed foreground text or template fallback / discard
-> MVP6 debug console display
```

The first implementation slice must be provider-free. It should prove the
canonical events, adapter schema, gate policy, route-specific discard behavior,
replay safety, and debug console display before any real fast-interaction
provider role is enabled.

## Allowed Scope

- Add ADR-017 foreground events to the derived event spec and Python registry.
- Add provider-free Fast Interaction adapter contract / fake adapter output.
- Record `FAST_INTERACTION_OUTPUT_EMITTED` and optional
  `FOREGROUND_REPLY_CANDIDATE_EMITTED` for committed turns.
- Implement deterministic Fast Foreground Gate policy.
- For `FAST_ONLY + ANSWER + LOW risk + sufficient confidence`, commit a
  foreground text output.
- For slow-task, patch, ignore, ambiguous, or unsafe paths, discard the
  candidate and optionally commit template ack / clarify / silence policy.
- Extend MVP5/MVP6 route metadata with foreground gate/output ids and safe refs.
- Extend MVP6 debug console answer display from route placeholder to gated
  foreground output or template fallback.
- Add deterministic provider-free tests and replay fixtures.
- Keep live provider work behind explicit opt-in and outside default tests.

## Prohibited Scope

- No extra model call after `FAST_ONLY`.
- No `FastReplyAdapter` chained after Router.
- No direct provider calls outside adapters.
- No real TTS, audio playback, or spoken delivery marker requirement.
- No streaming display before final route and gate pass.
- No tool calls, external side effects, payments, bookings, deletions, or
  external communication.
- No Router complex reasoning, tool authorization, confirmation acceptance, or
  SlowTask fact mutation.
- No fast reply rewriting SlowTask facts, resolved arguments, current-plan
  facts, tool status, or SemanticCommitment.
- No new RouterDecision values.
- No raw audio, raw prompt, provider body, local path, trace, replay cache,
  secret, or unredacted real user input in committed artifacts.
- No provider calls during deterministic replay.

## Architecture Boundary Summary

### Fast Interaction Adapter

Fast Interaction Adapter is an adapter role, not a new Router and not a
Composer. It can reuse the LALM / Thinker provider in a later live slice, but it
must expose a distinct role contract, prompt profile, output schema, capability
matrix, and event output.

Provider-free MVP6.2 starts with a fake adapter that emits safe refs and
synthetic candidate text. The fake adapter must still mark output mode honestly:
`mock`, `fallback`, or `degraded`; it must not claim to be a real model answer.

The output shape follows ADR-017:

- `route_hint`
- `route_prelude`
- `foreground_act`
- `reply_candidate` or future buffered `reply_delta`
- `final_fast_evidence_ref`
- `risk_tags`
- `confidence`
- `output_mode`
- `trace_redaction_level`

### Router

Router remains owner of `FAST_ONLY`, `SPAWN_SLOW_TASK`,
`PATCH_ACTIVE_SLOW_TASK`, and `IGNORE`. Fast Interaction output is evidence and
candidate foreground content; it is not final routing authority.

MVP6.2 should keep the current Router path intact. The provider-free slice may
run Fast Interaction output alongside existing ASR / Thinker evidence and pass
the resulting event ids to the gate after Router emits its decision.

### Fast Foreground Gate

Fast Foreground Gate is deterministic runtime policy. It consumes:

- Fast Interaction output event
- optional candidate event
- Router decision event
- TaskFocusState event
- active SlowTask summary state if present
- capability snapshot / output mode metadata
- configured confidence and risk thresholds

Only this combination may pass:

```text
router_decision=FAST_ONLY
foreground_act=ANSWER
risk_class=LOW
confidence >= configured_threshold
candidate schema valid
```

Everything else fails the candidate answer path and records why.

### Debug Console

MVP6 debug console should continue to be local-only and provider-free by
default. It can display:

- user-visible committed foreground text for gate-passed `FAST_ONLY`;
- template `ACK_SLOW` for `SPAWN_SLOW_TASK`;
- template `ACK_PATCH` for `PATCH_ACTIVE_SLOW_TASK`;
- template clarify or silence policy for ambiguous / ignore paths.

The API response may include local debug display text when safe, but committed
fixtures should rely on refs and synthetic/redacted examples. The console must
not expose raw provider body, prompt dump, local wav path, raw audio, secrets,
or unredacted real provider candidate text in shareable artifacts.

## Event Flow

### FAST_ONLY answer path

```text
TURN_INGRESS_COMMITTED
-> ASR_TRANSCRIPT_OUTPUT_EMITTED
-> THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED
-> FAST_INTERACTION_OUTPUT_EMITTED(foreground_act=ANSWER)
-> FOREGROUND_REPLY_CANDIDATE_EMITTED
-> ROUTER_DECISION_EMITTED(router_decision=FAST_ONLY)
-> TASK_FOCUS_STATE_UPDATED(foreground_mode=FAST_RESPONSE)
-> FOREGROUND_ACT_GATE_PASSED
-> FOREGROUND_OUTPUT_COMMITTED(output_basis=reply_candidate)
```

Required assertions:

- No `SLOWTASK_CREATED`.
- No `USER_PATCH_RECEIVED`.
- No `PLAN_VERSION_ADVANCED`.
- Gate pass references both Router decision and candidate event.
- Committed output references the gate pass event.

### SlowTask spawn path

```text
FAST_INTERACTION_OUTPUT_EMITTED(foreground_act=ACK_SLOW or ANSWER)
-> optional FOREGROUND_REPLY_CANDIDATE_EMITTED
-> ROUTER_DECISION_EMITTED(router_decision=SPAWN_SLOW_TASK)
-> FOREGROUND_ACT_GATE_FAILED
-> FOREGROUND_OUTPUT_DISCARDED
-> optional FOREGROUND_OUTPUT_COMMITTED(output_basis=template_ack)
-> SLOWTASK_CREATED / existing SlowTask control-plane events
```

Required assertions:

- Candidate answer is never shown.
- Template ack does not invent SlowTask progress.
- Complex task facts remain SlowTask / SemanticCommitment owned.

### Active SlowTask patch path

```text
FAST_INTERACTION_OUTPUT_EMITTED(foreground_act=ACK_PATCH or ANSWER)
-> optional FOREGROUND_REPLY_CANDIDATE_EMITTED
-> ROUTER_DECISION_EMITTED(router_decision=PATCH_ACTIVE_SLOW_TASK)
-> FOREGROUND_ACT_GATE_FAILED
-> FOREGROUND_OUTPUT_DISCARDED
-> optional FOREGROUND_OUTPUT_COMMITTED(output_basis=template_ack)
-> USER_PATCH_RECEIVED
```

Required assertions:

- Candidate answer is never shown.
- Patch enters UserPatch evidence.
- Fast output does not mutate goal, constraints, resolved arguments,
  confirmation state, plan version, or task lifecycle.

### Ambiguous / ignore path

Ambiguous or ignore paths must not show candidate answers. MVP6.2 may choose
between:

- `FOREGROUND_OUTPUT_COMMITTED(output_basis=template_clarify)` for short
  clarifications; or
- `FOREGROUND_OUTPUT_COMMITTED(output_basis=silence_policy)` / no visible output
  for ignore, depending on product policy.

The selected behavior must be explicit in event fields and replay fixtures.

## Safe Metadata Contract

MVP6.2 run metadata may include:

- `foreground_output_status=committed|discarded|template|silence|not_run`
- `foreground_act`
- `foreground_gate_decision=passed|failed|not_run`
- `foreground_gate_event_id`
- `foreground_candidate_event_id`
- `foreground_output_event_id`
- `foreground_discard_event_id`
- `foreground_output_ref`
- `foreground_output_basis`
- `foreground_fallback_reason`
- `fast_interaction_output_event_id`
- `fast_interaction_output_mode`
- existing MVP5/MVP6 route, adapter, safety, and latency fields

Local debug response may include display text only after output safety
validation. Shareable fixtures should prefer refs and synthetic display text.

Metadata must continue to assert:

- `raw_audio_included=false`
- `raw_transcript_included=false`
- `raw_provider_body_included=false`
- `prompt_dump_included=false`
- `secret_included=false`
- `local_wav_path_included=false`
- `replay_reruns_provider=false`
- `real_tts_used=false`
- `voice_output=none`

## Acceptance Scenarios

### MVP6.2-REGISTRY-SYNC-001

ADR-017 foreground events exist in `docs/specs/event-registry.md`,
`src/voice_agent/events/registry.py`, and event registry tests with required
fields aligned to ADR-002.

### MVP6.2-FAKE-FAST-ANSWER-PASS-001

A provider-free fake `FAST_ONLY` run emits Fast Interaction output, candidate,
Router decision, gate pass, and committed foreground output. The debug console
shows the committed answer instead of the MVP6.1 placeholder.

### MVP6.2-SLOW-DISCARD-TEMPLATE-001

A provider-free `SPAWN_SLOW_TASK` run records candidate discard and template
`ACK_SLOW` commit while preserving existing SlowTask create/planning events.

### MVP6.2-PATCH-DISCARD-TEMPLATE-001

A provider-free `PATCH_ACTIVE_SLOW_TASK` run records candidate discard and
template `ACK_PATCH` commit while still creating only `USER_PATCH_RECEIVED` for
task mutation evidence.

### MVP6.2-ACTIVE-SIDECHAT-PASS-001

With an active non-terminal SlowTask, foreground side chat may pass only when
Router emits `FAST_ONLY` and task focus is `FOREGROUND_CHAT`. Active task patch,
new-task candidate, cancel/pause candidate, and ambiguous focus must fail the
candidate answer path.

### MVP6.2-AMBIGUOUS-NO-ANSWER-001

Ambiguous or low-confidence output never shows candidate answer text. The
runtime records either template clarification or silence policy with explicit
fallback reason.

### MVP6.2-REPLAY-SAFETY-001

Replay reconstructs candidate generation, gate pass/fail, committed output,
discard, and template fallback from recorded events only. It does not call ASR,
Thinker, Fast Interaction, Slow LLM, TTS, tools, network, clock, random, or env
secret reads.

### MVP6.2-NO-SECOND-MODEL-CALL-001

Provider-free and future live tests must prove that `FAST_ONLY` answer display
does not trigger a second model request after Router. A live Fast Interaction
role may reuse the same underlying LALM provider call that produced route
evidence, but it must be a distinct adapter role/schema and a single adapter
request for the turn.

### MVP6.2-SAFETY-EXPORT-001

Committed fixtures and PR artifacts contain no raw audio, raw prompt, provider
body, local wav path, local output path, secret, raw trace, replay cache, or
unredacted real user input.

## Slice Plan

### Slice 0: Design document only

Create this design document.

Checks:

- `git diff --check -- docs/implementation/mvp6.2-fast-foreground-design.md`

Definition of done:

- The document states goals, non-goals, source contracts, event flow,
  acceptance scenarios, slice plan, and ADR stop conditions.

### Slice 1: Registry sync

Synchronize ADR-017 foreground event names into the derived event spec and
Python event registry.

Likely files:

- `docs/specs/event-registry.md`
- `src/voice_agent/events/registry.py`
- `tests/events/test_mvp1_event_registry.py` or a new foreground registry test

Checks:

- `./scripts/test tests/events -q`
- `rg -n "FAST_INTERACTION_OUTPUT_EMITTED|FOREGROUND_OUTPUT_COMMITTED" docs/specs src tests`

### Slice 2: Provider-free Fast Interaction adapter contract

Add a fake Fast Interaction adapter that emits normalized safe refs, foreground
act, candidate metadata, confidence, risk tags, schema name, and output mode.

Likely files:

- `src/voice_agent/adapters/fast_interaction_contract.py`
- `src/voice_agent/adapters/fast_interaction_fake.py`
- `tests/adapters/test_fast_interaction_fake.py`

Checks:

- `./scripts/test tests/adapters/test_fast_interaction_fake.py -q`

### Slice 3: Fast Foreground Gate

Implement deterministic gate policy and foreground output / discard event
emission.

Likely files:

- `src/voice_agent/runtime/fast_foreground_gate.py`
- `tests/runtime/test_fast_foreground_gate.py`

Checks:

- `./scripts/test tests/runtime/test_fast_foreground_gate.py -q`

### Slice 4: MVP5/MVP6 route runner integration

Extend the existing route runner metadata with Fast Interaction and foreground
events while preserving current SlowTask/UserPatch behavior.

Likely files:

- `src/voice_agent/runtime/mvp5_live_router_runner.py`
- `src/voice_agent/runtime/mvp5_real_voice_e2e_smoke.py`
- `tests/runtime/test_mvp5_live_route_results.py`
- `tests/replay/test_mvp5_live_route_replay.py`

Checks:

- `./scripts/test tests/runtime/test_mvp5_live_route_results.py -q`
- `./scripts/test tests/replay/test_mvp5_live_route_replay.py -q`

### Slice 5: MVP6 debug console display

Replace the MVP6.1 placeholder with gated foreground output or template
fallback. The console remains local-only and provider-free by default.

Likely files:

- `src/voice_agent/runtime/mvp6_debug_console_api.py`
- `src/voice_agent/runtime/mvp6_debug_console_static.py`
- `tests/runtime/test_mvp6_debug_console_runs.py`
- `tests/runtime/test_mvp6_debug_console_static.py`

Checks:

- `./scripts/test tests/runtime/test_mvp6_debug_console_runs.py -q`
- `./scripts/test tests/runtime/test_mvp6_debug_console_static.py -q`

### Slice 6: Replay fixture and acceptance closeout

Add minimal synthetic replay coverage and acceptance tests for fast answer pass,
slow discard/template, patch discard/template, ambiguous no-answer, and safety
export.

Likely files:

- `tests/fixtures/replay/mvp6/`
- `tests/acceptance/test_mvp6_acceptance_scenarios.py`
- `docs/implementation/mvp6.2-closeout.md`

Checks:

- `./scripts/test tests/acceptance/test_mvp6_acceptance_scenarios.py -q`
- `./scripts/test tests/replay -q`
- `git diff --check`

### Slice 7: Future live Fast Interaction role

Only after provider-free slices pass, introduce a real Fast Interaction role
profile. The live adapter may reuse the underlying LALM / Thinker provider but
must not add a second post-Router answer request.

Likely files:

- `src/voice_agent/adapters/lalm_fast_interaction_profile.py`
- `src/voice_agent/adapters/lalm_fast_interaction_runtime_adapter.py`
- live eval gate docs / tests similar to existing LALM Thinker gates

Checks:

- provider-free tests remain default;
- live provider execution remains explicit opt-in;
- adapter capability snapshot distinguishes real / mock / fallback / degraded.

## Verification Strategy

Default verification should stay provider-free:

- targeted unit tests for event registry, fake adapter, gate, route runner, and
  debug console;
- deterministic replay tests using recorded refs only;
- acceptance tests that prove pass, discard, template fallback, side chat, and
  ambiguous paths;
- fixture safety checks for raw audio, local paths, provider bodies, prompts,
  secrets, and unredacted real input;
- `git diff --check`.

Full project `./scripts/test` remains a closeout-level check, not required after
every small slice if targeted tests already cover the changed surface.

## ADR Stop Conditions

Stop and update/create an ADR before implementation if any slice requires:

- a second model request after Router for fast answer generation;
- displaying streaming deltas before final route and gate pass;
- real TTS / audio playback as part of fast foreground output;
- a new RouterDecision or task focus enum beyond accepted ADRs;
- Router-owned complex reasoning, tool authorization, confirmation acceptance,
  task cancellation, or SlowTask fact mutation;
- Fast Interaction output becoming SemanticCommitment or SlowTask fact source;
- direct provider calls outside adapter boundaries;
- provider calls during deterministic replay;
- raw audio, raw prompt, provider body, secret, raw trace, replay cache, local
  path, or unredacted real input in committed artifacts;
- production privacy, external side effects, real tool execution, payment,
  booking, deletion, or external communication.

## Open Questions

- Should `IGNORE` produce an explicit `FOREGROUND_OUTPUT_COMMITTED` with
  `output_basis=silence_policy`, or only a discard event with no committed
  output?
- Should text UI consume `FOREGROUND_OUTPUT_COMMITTED` directly, or should
  future voice playback wrap it as `SPOKEN_PLAN_EMITTED(source=fast_foreground)`?
- What should the first configured confidence threshold be for provider-free
  tests and live opt-in runs?
- In the future live role, should one provider response emit both
  `THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED` and `FAST_INTERACTION_OUTPUT_EMITTED`,
  or should Fast Interaction replace the Thinker event for routing paths that
  opt into ADR-017?
