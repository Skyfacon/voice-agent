# MVP-1 Implementation Backlog

本文档只覆盖 MVP-1：SlowTask mock、single active SlowTask、TaskFocusState、UserPatch evidence pack、`plan_version`、`task_event_seq`、stale ToolResult policy mock、SemanticCommitment mock、ASR/Thinker evidence fusion mock、SlowTask replay。

本文档最初是设计和实施 backlog；当前也作为 MVP-1 closeout 记录。它记录 MVP-1 已落地的 mock/replay scope、slice 边界、验证证据和仍禁止误读为 MVP-2/MVP-3 的范围。

## Source Contracts

- `AGENTS.md`
- `stage_b_adr_register.md`
- `docs/adr/ADR-002 Event Journal, Timing Model, and Replay Foundation.md`
- `docs/adr/ADR-004 SlowTask Plan Versioning and Stale Result Policy.md`
- `docs/adr/ADR-006 Router Task Focus and Single Active SlowTask MVP.md`
- `docs/adr/ADR-007 UserPatch Evidence Pack.md`
- `docs/adr/ADR-008 ASR Thinker Evidence Fusion and SlowTask-led Conflict Resolution.md`
- `docs/adr/ADR-010 Trace Replay Debug Policy for Web Demo.md`
- `docs/adr/ADR-012 MVP Vertical Slice and Development SLOs.md`
- `docs/adr/ADR-015 Repository Governance and AGENTS.md Rules.md`
- `docs/adr/ADR-016 SlowTask Lifecycle and Confirmation State Contract.md`
- `docs/project-overview.md`
- `docs/architecture-book.md`
- `docs/specs/event-registry.md`
- `docs/specs/state-reducers.md`
- `docs/specs/replay-spec.md`
- `docs/planning/execution-roadmap.md`
- `docs/implementation/mvp0-backlog.md`
- `docs/specs/mvp1-acceptance-scenarios.md`

## Current Starting Point

Verified on 2026-05-14:

- MVP-0 Slice 0-9 are implemented and closeout hardening found no blocking readiness issue.
- MVP-1 mock/replay spine is implemented in the current checkout.
- `src/voice_agent/router/router.py` includes `MVP1Router`, ADR-006 TaskFocus values, and MVP-1 RouterDecision handling.
- `src/voice_agent/state/task_focus_state.py` and `src/voice_agent/state/slowtask_state.py` replay TaskFocus and SlowTask state.
- `src/voice_agent/slowtask/mock_runtime.py` and `src/voice_agent/user_patch/evidence_pack.py` implement the MVP-1 mock runtime and UserPatch evidence pack flow.
- `tests/fixtures/replay/mvp1/manifest.index.json` declares `MVP1-ACCEPTANCE` over deterministic, synthetic, GitHub-allowed fixtures.
- `tests/acceptance/test_mvp1_acceptance_scenarios.py` covers the required MVP-1 scenarios and rejects hidden MVP-2 behavior.
- MVP-2 Tool Executor, Composer, frontend UI patching, demo tools, real Slow LLM, real model adapters, multi active SlowTask, and pause/resume remain out of runtime scope.

This backlog should now be read as the MVP-1 implementation record and closeout checklist, not as evidence that MVP-1 is still unstarted.

## MVP-1 Closeout Status

Current closeout summary:

| Slice | Area | Current status | Evidence |
| --- | --- | --- | --- |
| 0 | Fixture/replay safety skeleton | Complete | `tests/fixtures/replay/mvp1/000-empty-mvp1-session.fixture.json`, `manifest.index.json`, fixture safety tests |
| 1 | Event registry validation | Complete | `tests/events/test_mvp1_event_registry.py`, canonical registry validation |
| 2 | TaskFocusState and Router MVP-1 decisions | Complete | `MVP1Router`, `TaskFocusState`, `tests/router/test_router_task_focus_mvp1.py`, `tests/replay/test_task_focus_state_mvp1.py` |
| 3 | SlowTaskState reducer and replay skeleton | Complete | `src/voice_agent/state/slowtask_state.py`, `tests/state/test_slowtask_state.py`, `tests/replay/test_slowtask_replay_mvp1.py` |
| 4 | SlowTask create/planning/completed happy path | Complete | `src/voice_agent/slowtask/mock_runtime.py`, `tests/slowtask/test_slowtask_lifecycle_mvp1.py`, `004-spawn-planning-completed.fixture.json` |
| 5 | UserPatch evidence pack construction | Complete | `src/voice_agent/user_patch/evidence_pack.py`, `tests/user_patch/test_user_patch_evidence_pack.py`, `005-active-patch-evidence.fixture.json` |
| 6 | UserPatch interpretation and plan advance | Complete | `tests/slowtask/test_user_patch_interpretation.py`, `tests/slowtask/test_plan_version_advance.py`, `006-plan-advance-replanning.fixture.json` |
| 7 | Evidence review, ambiguity, waiting slot | Complete | `tests/slowtask/test_evidence_review_mvp1.py`, `tests/slowtask/test_waiting_slot_mvp1.py`, `007-evidence-review-waiting-slot.fixture.json` |
| 8 | Stale ToolResult with/without adoption | Complete | `tests/slowtask/test_stale_tool_result_policy.py`, `tests/replay/test_stale_tool_result_replay.py`, `008-stale-result-*.fixture.json` |
| 9 | Cancel / switch-task confirmation | Complete | `tests/slowtask/test_confirmation_cancel_switch_mvp1.py`, `tests/replay/test_cancel_switch_confirmation_replay.py`, `009-cancel/switch-*.fixture.json` |
| 10 | MVP-1 acceptance runner and closeout | Complete | `tests/acceptance/test_mvp1_acceptance_scenarios.py`, `MVP1-ACCEPTANCE` manifest |

Closeout interpretation:

- MVP-1 completion means the mock/replay control-plane behavior is implemented and replay-validated.
- It does not mean a product service, frontend demo, real Tool Executor, real Slow LLM, real adapters, or MVP-2 Composer/checker path exists.
- Slice sections below are kept as implementation record. Their non-goals and acceptance criteria remain useful scope guards; file lists have been updated from original planning intent to current observed paths where applicable.

## MVP-1 Scope

- Single active non-terminal SlowTask.
- Router-owned `TaskFocusState` for active task focus classification.
- UserPatch evidence pack construction for active-task input.
- SlowTask-owned patch interpretation.
- SlowTask mock lifecycle per ADR-016.
- `plan_version` advance for material task changes.
- `task_event_seq` sequencing inside each SlowTask.
- ASR/Thinker evidence fusion mock with provenance.
- Evidence review, ambiguity detection/resolution, waiting-slot, and resolved-arguments mock paths.
- Stale ToolResult policy mock with and without explicit adoption.
- Minimal ADR-016 cancel and switch-task confirmation paths.
- Mock SemanticCommitment emitted only from current-plan SlowTask state.
- Deterministic replay for `TaskFocusState` and `SlowTaskState`.
- MVP-1 acceptance runner over synthetic/redacted/minimal fixtures.

## MVP-1 Prohibited Scope

MVP-1 must not implement:

- real Tool Executor
- real external tools
- real external write, payment, booking, deletion, or external communication
- real Slow LLM reasoning
- real ASR / Thinker / TTS adapter integration beyond existing mock output modes
- multiple active SlowTasks
- pause/resume SlowTask
- MVP-2 progressive tool invocation
- `TOOL_UI_STATE_PATCHED` replay or frontend UI patching
- demo tools
- Thinker-as-Composer
- CommitmentCoverageCheck or ProgressTruthfulnessCheck
- production privacy policy
- new MVP-relevant event names not registered in ADR-002 and `docs/specs/event-registry.md`

MVP-1 may use canonical `TOOL_CALL_STARTED` and `TOOL_RESULT_RECEIVED` only as synthetic fixture events or through a fixture/mock tool event emitter required to validate stale result policy. That emitter is not a partial Tool Executor: it owns no manifest loading, authorization, adapter call, retry, cancellation, UI patch, or side-effect behavior. MVP-1 must not emit `TOOL_EXECUTION_STARTED`.

## Core Invariants

- Every critical state transition is recorded in the per-session append-only event journal.
- MVP-relevant event names must come from ADR-002 and `docs/specs/event-registry.md`.
- Router owns `TaskFocusState` and post-commit routing decisions only.
- Router must not interpret final UserPatch semantics, cancel tasks, authorize tools, advance `plan_version`, or choose ASR/Thinker winners.
- UserPatch is evidence, not task mutation.
- SlowTask Runtime owns `SlowTaskState`, `confirmation_state`, current `plan_version`, `task_event_seq`, stale evidence, adopted/rebased evidence metadata, resolved arguments, and SemanticCommitment.
- SlowTask-relevant event schemas must require the ADR binding fields in the registry/validator, including `task_id`, current-plan binding, and `task_event_seq` for UserPatch interpretation, plan advance, stale marking, stale evidence recording, and SemanticCommitment.
- `USER_PATCH_RECEIVED.plan_version` is the pre-advance current plan version.
- `USER_PATCH_INTERPRETED` is required before any UserPatch can advance plan version, affect confirmation, cancel, or resolve arguments.
- Not every UserPatch advances `plan_version`.
- `plan_version` advances only through `PLAN_VERSION_ADVANCED`.
- Old-plan `TOOL_RESULT_RECEIVED` defaults to `TOOL_RESULT_MARKED_STALE` and `STALE_EVIDENCE_RECORDED`.
- Stale evidence must not advance current state unless `STALE_EVIDENCE_ADOPTED` exists.
- SemanticCommitment must use current `plan_version`; if it uses adopted stale evidence, source metadata must include the adoption event.
- Terminal SlowTask states are sticky. Late UserPatch, ToolResult, or confirmation events after `COMPLETED`, `CANCELLED`, or `FAILED` must not advance the task.
- Shareable/GitHub fixtures must be synthetic, redacted, and minimal.

## State Objects

### TaskFocusState

Owned by Router.

Required fields:

- `active_task_id`
- `foreground_mode`
- `side_conversation_allowed`
- `default_patch_policy`
- `ambiguous_input_policy`
- `last_focus_decision`
- `last_focus_confidence`
- `last_focus_event_id`

MVP-1 behavior:

- Replayed from `ROUTER_DECISION_EMITTED` and `TASK_FOCUS_STATE_UPDATED`.
- Tracks at most one active non-terminal SlowTask.
- Keeps foreground chat separate from active-task patching.
- Treats `AMBIGUOUS` as no-patch by default.
- Does not infer task terminal cleanup from SlowTask events; active task cleanup must be represented by Router-owned `TASK_FOCUS_STATE_UPDATED`.

### SlowTaskState

Owned by SlowTask Runtime.

Required fields:

- `task_id`
- current state in `CREATED`, `WAITING_FOR_SLOT`, `PLANNING`, `EXECUTING`, `WAITING_FOR_USER_CONFIRMATION`, `COMPLETED`, `CANCELLED`, `FAILED`
- current `plan_version`
- current `task_event_seq`
- initial goal / current goal refs
- current constraints refs
- resolved arguments refs
- argument provenance refs
- evidence refs
- confirmation state
- stale evidence refs
- adopted/rebased evidence metadata
- terminal outcome
- latest SemanticCommitment ref if completed

MVP-1 behavior:

- Created by `SLOWTASK_CREATED`.
- Every state transition requires `SLOWTASK_STATE_CHANGED`.
- `PLAN_VERSION_ADVANCED` is the only event that updates current `plan_version`.
- `USER_PATCH_RECEIVED` appends evidence only.
- `USER_PATCH_INTERPRETED` records SlowTask interpretation against an observed plan.
- `COMPLETED`, `CANCELLED`, and `FAILED` are sticky.
- Late events after terminal state are replay diagnostics or stale/debug evidence only.

### UserPatch Evidence Pack

Owned by UserPatch Pipeline as input evidence; interpreted by SlowTask Runtime.

Envelope and binding fields:

- `patch_id`
- `event_id`
- `session_id`
- `conversation_id`
- `task_id`
- `plan_version`
- `observed_plan_version`
- `task_event_seq`
- `turn_id`
- `utterance_id`
- `caused_by_event_id`
- `created_monotonic_ms`
- `created_wall_clock_ms`
- `evidence_ref`

Authoritative evidence may include:

- redacted user text or `text_ref`
- `audio_span_id`
- `asr_nbest`
- `transcript_hint`
- `source_event_ids`
- `turn_id`
- `utterance_id`
- `input_modality`
- `language_hint`
- audio timing metadata
- field-level provenance

Non-authoritative hypothesis may include:

- `semantic_summary`
- `audio_summary`
- `patch_hint`
- `candidate_patch_types`
- `emotion`
- `confidence`
- `task_focus`
- `task_focus_confidence`
- `router_reason`
- `evidence_uncertainty`

MVP-1 behavior:

- It does not rewrite goal, slot, constraint, confirmation state, or cancellation state.
- It can carry `cancel_candidate` or `switch_task_candidate` as non-authoritative control evidence.
- It must preserve ASR/Thinker disagreement for SlowTask review.
- Shareable fixtures must use synthetic/redacted text and refs.

## `task_event_seq` / `plan_version` Sequencing Rules

- `event_seq` is session-level and assigned by the Event Journal.
- `task_event_seq` is task-level and owned by SlowTask Runtime for SlowTask-relevant events.
- MVP-1 must allocate `task_event_seq` monotonically per `task_id` whenever a SlowTask-relevant event is emitted or accepted into SlowTask state.
- There must be one SlowTask append/sequence boundary per session task. Runtime helpers such as UserPatch Pipeline and fixture/mock tool event emitter must obtain the next `task_event_seq` from that boundary before journal append; they must not allocate task sequence numbers independently.
- Event Journal assigns session-level `event_seq`; the SlowTask append/sequence boundary assigns task-level `task_event_seq`. Implementations may combine these in one serialized append call, but they must not rely on async scheduling order or independent threads to advance task sequence.
- A new SlowTask starts with an initial `plan_version`; MVP-1 fixtures must use a consistent convention, for example `plan_version=1`.
- A material patch uses this event order:
  1. `USER_PATCH_RECEIVED(plan_version=N, observed_plan_version=N)`
  2. `USER_PATCH_INTERPRETED(interpreted_against_plan_version=N, materially_changes_task=true)`
  3. `PLAN_VERSION_ADVANCED(from_plan_version=N, to_plan_version=N+1)`
  4. `PLANNING_RESTARTED(plan_version=N+1)`
  5. `TASK_REPLANNED(plan_version=N+1, superseded_plan_version=N)`
- A non-material, irrelevant, foreground, or ambiguous no-patch path must not emit `PLAN_VERSION_ADVANCED`.
- Tool call/result mock events bind to the plan that created them.
- `TOOL_RESULT_RECEIVED(plan_version=N)` when current plan is `N+1` must be followed by `TOOL_RESULT_MARKED_STALE` and `STALE_EVIDENCE_RECORDED`.
- `STALE_EVIDENCE_ADOPTED(plan_version=N+1, adopted_from_plan_version=N)` is the only path by which old-plan evidence may enter current-plan reasoning.
- Pending confirmation created under plan `N` is invalid if current plan advances to `N+1`; it must be rejected or superseded before it can authorize anything.
- Terminal SlowTask states reject advancement from late UserPatch, ToolResult, or confirmation events even if those events carry matching ids.

## Slice 0: MVP-1 Fixture/Replay Safety Skeleton

**Goal**

Define the MVP-1 fixture directory, manifest shape, safety checks, and replay boundaries before adding any SlowTask runtime behavior.

**Non-goals**

At this slice boundary: no SlowTask runtime, Router behavior change, UserPatch interpretation, tool execution, or new event names.

**Implemented files or file areas**

- Existing: `tests/fixtures/replay/mvp1/README.md`
- Existing: `tests/fixtures/replay/mvp1/000-empty-mvp1-session.fixture.json`
- Existing: `tests/fixtures/replay/mvp1/manifest.index.json`
- Existing: `tests/replay/test_fixture_safety.py`
- Existing: replay manifest validation supports MVP-1 expected states

**Events touched**

- `SESSION_STARTED`
- `ADAPTER_CAPABILITY_SNAPSHOT_RECORDED`
- `REPLAY_STARTED`
- `REPLAY_COMPLETED`
- trace safety events when redaction/block paths are intentionally exercised

**State objects touched**

- `TracePrivacyState`
- empty `TaskFocusState`
- empty `SlowTaskState` expectation in state digest

**Tests**

- Fixture safety rejects raw audio, raw debug trace, local replay cache refs, secrets, unredacted real user input, unredacted sensitive tool results, and large raw web content.
- Manifest declares `fixture_domain=GITHUB_ALLOWED`, `replay_mode=deterministic`, `contains_raw_audio=false`, `contains_raw_trace=false`, `contains_real_user_input=false`, and `contains_secrets=false`.
- Replay does not call models, tools, network, clock, or random.

**Replay fixture**

- `tests/fixtures/replay/mvp1/000-empty-mvp1-session.fixture.json`

**Privacy assertions**

- Fixture is synthetic/redacted/minimal.
- No raw audio, raw trace, secret, credential, authorization header, session secret, or real user input appears.

**Acceptance criteria**

- MVP-1 fixture suite can be introduced without changing `.gitignore`.
- Empty MVP-1 replay produces deterministic state digest fields for `TaskFocusState` and `SlowTaskState`.
- MVP-0 fixture suite remains forbidden from emitting MVP-1 events.

**Done when**

- Fixture safety tests pass.
- Empty MVP-1 fixture replays.
- Review confirms this slice does not implement SlowTask behavior.

## Slice 1: MVP-1 Event Registry Validation

**Goal**

Reconcile ADR-002 / ADR-004 / ADR-016 binding requirements with `docs/specs/event-registry.md`, then ensure implementation validators accept all canonical MVP-1 events and reject non-canonical labels such as `SEMANTIC_COMMITMENT_CREATED` or `STALE_TOOL_RESULT_RECORDED` as journal event names.

**Non-goals**

No new event names, ADR changes, state reducer logic, runtime state machine, or tool execution.

**Implemented files or file areas**

- Existing: `src/voice_agent/events/registry.py`
- Existing: `tests/events/test_event_envelope.py`
- Existing: `tests/events/test_mvp1_event_registry.py`

**Events touched**

- `SLOWTASK_CREATED`
- `SLOWTASK_STATE_CHANGED`
- `USER_PATCH_RECEIVED`
- `USER_PATCH_INTERPRETED`
- `PLAN_VERSION_ADVANCED`
- `TASK_REPLANNED`
- `EVIDENCE_REVIEWED`
- `AMBIGUITY_DETECTED`
- `AMBIGUITY_RESOLVED`
- `CLARIFICATION_REQUESTED`
- `ARGUMENTS_RESOLVED`
- `ARGUMENT_RESOLUTION_PROVENANCE`
- `INSUFFICIENT_EVIDENCE_FOR_ACTION`
- `PLANNING_STARTED`
- `PLANNING_RESTARTED`
- `WAITING_FOR_SLOT`
- `FINALIZING`
- `CONFIRMATION_REQUIRED`
- `USER_CONFIRMATION_RECEIVED`
- `CONFIRMATION_ACCEPTED`
- `CONFIRMATION_REJECTED`
- `SLOWTASK_CANCEL_REQUESTED`
- `SLOWTASK_CANCELLED`
- `TOOL_CALL_STARTED`
- `TOOL_RESULT_RECEIVED`
- `TOOL_RESULT_MARKED_STALE`
- `STALE_EVIDENCE_RECORDED`
- `STALE_EVIDENCE_ADOPTED`
- `SEMANTIC_COMMITMENT_EMITTED`

**State objects touched**

None beyond validation metadata.

**Tests**

- Schema reconciliation check compares ADR binding requirements, event registry required fields, and MVP-1 acceptance scenario event chains before runtime work begins.
- Required fields from `docs/specs/event-registry.md` are enforced.
- SlowTask-relevant events require `task_id`, current-plan binding, and `task_event_seq` where ADR requires them; this includes `USER_PATCH_INTERPRETED`, `PLAN_VERSION_ADVANCED`, `TOOL_RESULT_MARKED_STALE`, and `STALE_EVIDENCE_RECORDED`.
- Non-canonical relationship labels fail validation as event names.
- MVP-2-only event names are not required by MVP-1 acceptance fixtures.

**Replay fixture**

- `tests/fixtures/replay/mvp1/001-event-registry-minimal.fixture.json`

**Privacy assertions**

- Required-field examples use refs and metadata only.
- No inline raw user text, raw tool payload, or secret-like field is needed.

**Acceptance criteria**

- Every MVP-1 event used by later slices is registered before fixture/runtime use.
- No acceptance scenario depends on an unregistered MVP-relevant event name.
- Registry required fields are strong enough for validators to reject missing `task_event_seq` or missing current-plan binding on critical SlowTask events.

**Done when**

- Event validation tests pass.
- Review confirms no ADR-002 update is required.
- Any remaining registry/ADR mismatch is documented as a stop-and-update-ADR condition rather than papered over in implementation.

## Slice 2: TaskFocusState Reducer and Router MVP-1 Decisions

**Goal**

Expand Router and `TaskFocusState` from MVP-0 FAST_ONLY/IGNORE skeleton into MVP-1 post-commit task focus behavior while preserving Router non-ownership of final UserPatch semantics.

Define a `RouterContext` / `TaskFocusSnapshot` contract at the same time. Router may receive a read-only summary with active task id, lifecycle phase, current plan version, pending confirmation scope, and terminal/non-terminal status. Router must not read SlowTask internal goal rewrites, resolved arguments, stale evidence contents, or confirmation authorization details, and must not infer final UserPatch semantics from the snapshot.

**Non-goals**

No UserPatch interpretation, no SlowTask cancellation, no plan advance, no ASR/Thinker conflict arbitration, no multi active SlowTask.

**Implemented files or file areas**

- Existing: `src/voice_agent/router/router.py`
- Existing: `src/voice_agent/state/task_focus_state.py`
- Existing: Router context / task focus snapshot definitions near the Router boundary
- Existing: `src/voice_agent/replay/runner.py`
- Existing: `src/voice_agent/replay/state_digest.py`
- Existing: `tests/router/test_router_task_focus_mvp1.py`
- Existing: `tests/replay/test_task_focus_state_mvp1.py`

**Events touched**

- `ROUTER_DECISION_EMITTED`
- `TASK_FOCUS_STATE_UPDATED`

**State objects touched**

- `TaskFocusState`

**Tests**

- Router consumes only the public `RouterContext` / `TaskFocusSnapshot`, not SlowTask internals.
- No active SlowTask plus complex input emits `SPAWN_SLOW_TASK`.
- Active SlowTask plus obvious patch emits `PATCH_ACTIVE_SLOW_TASK` with `task_focus=ACTIVE_TASK_PATCH`.
- Active SlowTask plus foreground chat emits `FAST_ONLY` with `task_focus=FOREGROUND_CHAT` and no UserPatch trigger.
- Active SlowTask plus ambiguous input emits no patch.
- New-task candidate while active emits `PATCH_ACTIVE_SLOW_TASK` with `task_focus=NEW_TASK_CANDIDATE`, not automatic spawn.
- Cancel/pause candidate while active emits `PATCH_ACTIVE_SLOW_TASK` with `task_focus=CANCEL_OR_PAUSE_CANDIDATE`, not cancellation.
- `NON_ASSISTANT` input emits `IGNORE` and does not enter SlowTask.

**Replay fixture**

- `tests/fixtures/replay/mvp1/002-task-focus-router.fixture.json`

**Privacy assertions**

- Router decisions contain metadata and evidence refs only.
- ASR/Thinker evidence refs remain synthetic/redacted.

**Acceptance criteria**

- `TaskFocusState` replays active task id, foreground mode, side conversation policy, ambiguity policy, and last focus decision.
- Router still emits only `FAST_ONLY`, `SPAWN_SLOW_TASK`, `PATCH_ACTIVE_SLOW_TASK`, or `IGNORE`.
- Router never emits SlowTask lifecycle, confirmation, cancel, or plan version events.
- Router can tell whether an active non-terminal task exists without interpreting that task's goal, constraints, resolved arguments, stale evidence, or confirmation result.

**Done when**

- Router focus tests pass.
- Replay reconstructs the same `TaskFocusState` from recorded events.
- Review confirms Router did not become a semantic task interpreter.

## Slice 3: SlowTaskState Reducer and Deterministic Replay Skeleton

**Goal**

Add deterministic replay support for SlowTaskState before adding live runtime behavior.

**Non-goals**

No live SlowTask runtime, no UserPatch construction, no mock tool generation, no Composer or spoken output.

**Implemented files or file areas**

- Existing: `src/voice_agent/state/slowtask_state.py`
- Existing: `src/voice_agent/replay/runner.py`
- Existing: `src/voice_agent/replay/state_digest.py`
- Existing: `tests/state/test_slowtask_state.py`
- Existing: `tests/replay/test_slowtask_replay_mvp1.py`

**Events touched**

- All SlowTask lifecycle, evidence, plan-version, stale-result, confirmation, cancel, and SemanticCommitment events listed in Slice 1.

**State objects touched**

- `SlowTaskState`
- state digest

**Tests**

- `SLOWTASK_CREATED` initializes state without completing the task.
- Every `SLOWTASK_STATE_CHANGED` updates state only when the transition is legal.
- `PLAN_VERSION_ADVANCED` is the only event that updates current `plan_version`.
- `USER_PATCH_RECEIVED` appends evidence and does not mutate goal or constraints.
- `SLOWTASK_FAILED` followed by `SLOWTASK_STATE_CHANGED(to_state=FAILED)` produces terminal failed state.
- Terminal states are sticky.
- Late post-terminal UserPatch, ToolResult, and confirmation events do not advance state.
- State digest excludes raw text/audio/secret/tool credential payloads.

**Replay fixture**

- `tests/fixtures/replay/mvp1/003-slowtask-reducer-skeleton.fixture.json`
- `tests/fixtures/replay/mvp1/003-slowtask-failed-sticky.fixture.json`

**Privacy assertions**

- Goal, evidence, resolved arguments, stale evidence, and commitment data use refs.
- Digest does not include raw user text or sensitive tool payloads.

**Acceptance criteria**

- Replay can reconstruct `SlowTaskState` from events alone.
- Replay covers `COMPLETED`, `CANCELLED`, and `FAILED` terminal stickiness before runtime happy paths depend on it.
- Reducer does not call models, tools, network, clock, or random.

**Done when**

- SlowTask reducer tests pass.
- State digest includes stable `slowtask_state_hash`.
- Review confirms no runtime behavior was smuggled into reducer tests.

## Slice 4: SlowTask Runtime Create/Planning/Completed Happy Path

**Goal**

Implement the minimal mock SlowTask happy path from Router spawn to current-plan SemanticCommitment without tools.

**Non-goals**

No real Slow LLM, no real Tool Executor, no progressive tool events, no Composer, no coverage/truthfulness checks.

**Implemented files or file areas**

- Existing: `src/voice_agent/slowtask/`
- Existing: `src/voice_agent/runtime/slowtask_orchestrator.py`
- Existing: `tests/slowtask/test_slowtask_lifecycle_mvp1.py`
- Existing: `tests/replay/test_slowtask_happy_path_replay.py`

**Events touched**

- `ROUTER_DECISION_EMITTED`
- `TASK_FOCUS_STATE_UPDATED`
- `SLOWTASK_CREATED`
- `SLOWTASK_STATE_CHANGED`
- `PLANNING_STARTED`
- `EVIDENCE_REVIEWED`
- `ARGUMENTS_RESOLVED`
- `ARGUMENT_RESOLUTION_PROVENANCE`
- `FINALIZING`
- `SEMANTIC_COMMITMENT_EMITTED`

**State objects touched**

- `TaskFocusState`
- `SlowTaskState`

**Tests**

- Spawn order is `ROUTER_DECISION_EMITTED(router_decision=SPAWN_SLOW_TASK)` -> `SLOWTASK_CREATED` -> `SLOWTASK_STATE_CHANGED(to_state=CREATED)` -> Router-owned `TASK_FOCUS_STATE_UPDATED(active_task_id=T1)` -> `PLANNING_STARTED` -> `SLOWTASK_STATE_CHANGED(to_state=PLANNING)`.
- Replay must never expose an `active_task_id` that points to a task id before its `SLOWTASK_CREATED` event exists.
- Happy path emits `EVIDENCE_REVIEWED`, resolved arguments when applicable, `FINALIZING`, `SEMANTIC_COMMITMENT_EMITTED`, and `SLOWTASK_STATE_CHANGED(to_state=COMPLETED)`.
- SemanticCommitment binds current `task_id`, `plan_version`, and `task_event_seq`.
- Completion clears active focus only through `TASK_FOCUS_STATE_UPDATED`.

**Replay fixture**

- `tests/fixtures/replay/mvp1/004-spawn-planning-completed.fixture.json`

**Privacy assertions**

- Initial goal and commitment are refs or synthetic/redacted summaries.
- No raw model prompt/output is required.

**Acceptance criteria**

- A single SlowTask can be created, planned, finalized, committed, completed, and replayed.
- No tool or Composer events appear.

**Done when**

- Happy-path lifecycle tests pass.
- Replay state matches runtime state.
- Review confirms this is mock lifecycle only.

## Slice 5: UserPatch Evidence Pack Construction

**Goal**

Construct UserPatch evidence packs for active-task patch decisions without interpreting them as task mutations.

**Non-goals**

No SlowTask interpretation, no plan advance, no direct slot/constraint/goal mutation, no confirmation acceptance.

**Implemented files or file areas**

- Existing: `src/voice_agent/user_patch/`
- Existing: Router/UserPatch handoff where patch decisions hand off evidence refs
- Existing: `tests/user_patch/test_user_patch_evidence_pack.py`
- Existing: `tests/replay/test_user_patch_received_replay.py`

**Events touched**

- `TURN_INGRESS_COMMITTED`
- `MOCK_ASR_FRAME_EMITTED`
- `MOCK_THINKER_FRAME_EMITTED`
- `ROUTER_DECISION_EMITTED`
- `TASK_FOCUS_STATE_UPDATED`
- `USER_PATCH_RECEIVED`

**State objects touched**

- UserPatch evidence pack
- `TaskFocusState`
- `SlowTaskState` evidence queue

**Tests**

- `USER_PATCH_RECEIVED` binds `patch_id`, `task_id`, pre-advance `plan_version`, `observed_plan_version`, `task_event_seq`, `turn_id`, `utterance_id`, and `evidence_ref`.
- Evidence pack contains authoritative evidence and non-authoritative hypothesis.
- ASR n-best and Thinker summary can disagree and both retain provenance.
- `candidate_patch_types` are hints only.
- `USER_PATCH_RECEIVED` alone never changes plan version, resolved arguments, confirmation state, task goal, or constraints.

**Replay fixture**

- `tests/fixtures/replay/mvp1/005-active-patch-evidence.fixture.json`

**Privacy assertions**

- User text is synthetic/redacted or referenced through `text_ref`.
- Audio is represented by `audio_span_id`, never raw audio.
- Evidence refs do not contain secrets or credentials.

**Acceptance criteria**

- Active patch input becomes a replayable evidence pack.
- Router metadata is preserved but non-authoritative.

**Done when**

- UserPatch evidence tests pass.
- Replay reconstructs the evidence queue without mutating task state.

## Slice 6: UserPatch Interpretation and Plan Version Advance/Replanning

**Goal**

Let SlowTask interpret UserPatch evidence against the observed plan and advance `plan_version` only for material changes.

**Non-goals**

No Router semantic interpretation, no direct UserPatch mutation, no stale result adoption, no real Slow LLM.

**Implemented files or file areas**

- Existing: `src/voice_agent/slowtask/`
- Existing: `tests/slowtask/test_user_patch_interpretation.py`
- Existing: `tests/slowtask/test_plan_version_advance.py`
- Existing: `tests/replay/test_plan_version_replay.py`

**Events touched**

- `USER_PATCH_RECEIVED`
- `USER_PATCH_INTERPRETED`
- `PLAN_VERSION_ADVANCED`
- `PLANNING_RESTARTED`
- `TASK_REPLANNED`
- `SLOWTASK_STATE_CHANGED`

**State objects touched**

- `SlowTaskState`
- plan metadata
- patch interpretation metadata

**Tests**

- `USER_PATCH_INTERPRETED` records `interpreted_against_plan_version`, `interpretation_type`, `materially_changes_task`, reason, and evidence refs.
- Material patch emits `PLAN_VERSION_ADVANCED(plan_version=N+1, from_plan_version=N, to_plan_version=N+1, task_event_seq=...)`.
- Plan advance records `caused_by_user_patch_event_id`.
- Replanning emits `PLANNING_RESTARTED` and `TASK_REPLANNED`.
- Irrelevant, foreground, or non-task patch does not advance plan version.
- Pending confirmation under old plan is rejected or superseded if plan advances.

**Replay fixture**

- `tests/fixtures/replay/mvp1/006-plan-advance-replanning.fixture.json`

**Privacy assertions**

- Interpretation reason uses metadata or synthetic/redacted refs.
- No raw user input is needed in fixture.

**Acceptance criteria**

- Plan version changes are replayable and causally tied to interpreted patches.
- Non-material patches do not create hidden task mutations.

**Done when**

- Plan-version tests pass.
- Replay reconstructs final plan version and superseded plan metadata.

## Slice 7: Evidence Review, Ambiguity, Waiting Slot, and Resolved Arguments Mock

**Goal**

Model SlowTask-led ASR/Thinker evidence review, ambiguity handling, waiting-slot behavior, and resolved arguments with provenance.

**Non-goals**

No real Slow LLM reasoning, no tool execution, no Router conflict verdict, no automatic ASR/Thinker winner selection.

**Implemented files or file areas**

- Existing: `src/voice_agent/slowtask/`
- Existing: `tests/slowtask/test_evidence_review_mvp1.py`
- Existing: `tests/slowtask/test_waiting_slot_mvp1.py`
- Existing: `tests/replay/test_evidence_review_replay.py`

**Events touched**

- `EVIDENCE_REVIEWED`
- `AMBIGUITY_DETECTED`
- `AMBIGUITY_RESOLVED`
- `CLARIFICATION_REQUESTED`
- `ARGUMENTS_RESOLVED`
- `ARGUMENT_RESOLUTION_PROVENANCE`
- `INSUFFICIENT_EVIDENCE_FOR_ACTION`
- `WAITING_FOR_SLOT`
- `SLOWTASK_STATE_CHANGED`

**State objects touched**

- `SlowTaskState`
- resolved arguments refs
- provenance refs
- missing/ambiguous field metadata

**Tests**

- Evidence review records source evidence refs from ASR, Thinker, Router, and UserPatch where applicable.
- Obvious ambiguity emits `AMBIGUITY_DETECTED`.
- Context-resolvable ambiguity emits `AMBIGUITY_RESOLVED` with provenance.
- Missing critical slot emits `INSUFFICIENT_EVIDENCE_FOR_ACTION`, `CLARIFICATION_REQUESTED`, `WAITING_FOR_SLOT`, and `SLOWTASK_STATE_CHANGED(to_state=WAITING_FOR_SLOT)`.
- Resolved arguments require `ARGUMENTS_RESOLVED` and `ARGUMENT_RESOLUTION_PROVENANCE`.
- No tool call or SemanticCommitment is emitted when critical evidence is unresolved.

**Replay fixture**

- `tests/fixtures/replay/mvp1/007-evidence-review-waiting-slot.fixture.json`

**Privacy assertions**

- Ambiguous field values are synthetic/redacted.
- Provenance is stored as refs or minimized metadata.

**Acceptance criteria**

- Replay can explain evidence review to ambiguity/waiting/resolved-arguments paths.
- Tool execution remains absent from MVP-1 evidence review.

**Done when**

- Evidence review and waiting-slot tests pass.
- Replay diagnostics distinguish missing evidence from model/tool failure.

## Slice 8: Stale ToolResult Policy With and Without Adoption

**Goal**

Validate old-plan ToolResult handling with default stale recording and explicit adoption/rebase, using only synthetic fixture events or a fixture/mock tool event emitter.

**Non-goals**

No real Tool Executor, no partial Tool Executor, no manifest loading, no authorization gate, no adapter invocation, no progressive tool execution, no `TOOL_EXECUTION_STARTED`, no UI patch, no demo tools, no external side effects.

**Implemented files or file areas**

- Existing: `src/voice_agent/slowtask/`
- Existing: `tests/slowtask/test_stale_tool_result_policy.py`
- Existing: `tests/replay/test_stale_tool_result_replay.py`

**Events touched**

- `TOOL_CALL_STARTED`
- `USER_PATCH_RECEIVED`
- `USER_PATCH_INTERPRETED`
- `PLAN_VERSION_ADVANCED`
- `PLANNING_RESTARTED`
- `TASK_REPLANNED`
- `TOOL_RESULT_RECEIVED`
- `TOOL_RESULT_MARKED_STALE`
- `STALE_EVIDENCE_RECORDED`
- `STALE_EVIDENCE_ADOPTED`
- `EVIDENCE_REVIEWED`
- `ARGUMENTS_RESOLVED`
- `SEMANTIC_COMMITMENT_EMITTED` only in adopted/current-plan path

**State objects touched**

- `SlowTaskState`
- stale evidence refs
- adopted/rebased evidence metadata

**Tests**

- Only `TOOL_CALL_STARTED` and synthetic `TOOL_RESULT_RECEIVED` are allowed as MVP-1 tool markers.
- `TOOL_EXECUTION_STARTED`, `TOOL_PROGRESS_UPDATED`, `TOOL_UI_STATE_PATCHED`, manifest, authorization, retry, and cancellation execution events are rejected from MVP-1 stale fixtures.
- Tool call/result mock events bind `task_id`, `plan_version`, and `task_event_seq`.
- Old-plan result emits `TOOL_RESULT_MARKED_STALE(plan_version=current_plan_version, task_event_seq=...)` and `STALE_EVIDENCE_RECORDED(plan_version=current_plan_version, task_event_seq=...)`.
- Without `STALE_EVIDENCE_ADOPTED`, stale result does not change current plan, resolved arguments, or SemanticCommitment.
- With `STALE_EVIDENCE_ADOPTED`, adopted scope, reason, source event, and adopted-from plan are recorded.
- Commitment that uses adopted evidence includes adoption source metadata.

**Replay fixture**

- `tests/fixtures/replay/mvp1/008-stale-result-no-adoption.fixture.json`
- `tests/fixtures/replay/mvp1/008-stale-result-adopted.fixture.json`

**Privacy assertions**

- ToolResult refs are synthetic/minimized.
- No real external result, credential, authorization header, or side-effect payload appears.

**Acceptance criteria**

- Replay reproduces stale evidence state exactly.
- Old-plan result never advances current plan without adoption.

**Done when**

- Stale policy tests pass for both adopted and non-adopted cases.
- Review confirms no MVP-2 Tool Executor behavior was introduced.

## Slice 9: Cancel / Switch-Task Minimal Confirmation Path per ADR-016

**Goal**

Implement minimal SlowTask-owned confirmation paths for cancel and switch-task candidates without Router directly cancelling or replacing tasks.

**Non-goals**

No pause/resume, no multiple active SlowTasks, no real external action, no direct raw-text confirmation shortcut.

**Implemented files or file areas**

- Existing: `src/voice_agent/slowtask/`
- Existing: `src/voice_agent/user_patch/`
- Existing: `tests/slowtask/test_confirmation_cancel_switch_mvp1.py`
- Existing: `tests/replay/test_cancel_switch_confirmation_replay.py`

**Events touched**

- `ROUTER_DECISION_EMITTED`
- `TASK_FOCUS_STATE_UPDATED`
- `USER_PATCH_RECEIVED`
- `USER_PATCH_INTERPRETED`
- `CONFIRMATION_REQUIRED`
- `WAITING_FOR_USER_CONFIRMATION`
- `SLOWTASK_STATE_CHANGED`
- `USER_CONFIRMATION_RECEIVED`
- `CONFIRMATION_ACCEPTED`
- `CONFIRMATION_REJECTED`
- `SLOWTASK_CANCEL_REQUESTED`
- `SLOWTASK_CANCELLED`

**State objects touched**

- `TaskFocusState`
- `SlowTaskState`
- `confirmation_state`
- terminal outcome

**Tests**

- Cancel candidate enters UserPatch evidence first.
- SlowTask interpretation emits `CONFIRMATION_REQUIRED(confirmation_scope=TASK_CANCEL)` or a safe rejection/clarification path.
- User confirmation goes through `USER_PATCH_RECEIVED` and `USER_PATCH_INTERPRETED` before `USER_CONFIRMATION_RECEIVED`.
- Accepted cancel emits `SLOWTASK_CANCEL_REQUESTED`, `SLOWTASK_CANCELLED`, and `SLOWTASK_STATE_CHANGED(to_state=CANCELLED)`.
- Switch-task candidate uses `CONFIRMATION_REQUIRED(confirmation_scope=SWITCH_TASK)` and cancel-then-spawn only after active task is terminal.
- Rejected switch/cancel leaves current task goal and constraints unchanged.
- Accepted switch path cancels the active task first, clears active focus, and only then permits a later `ROUTER_DECISION_EMITTED(router_decision=SPAWN_SLOW_TASK)` for the preserved new-task candidate.

**Replay fixture**

- `tests/fixtures/replay/mvp1/009-cancel-confirmation.fixture.json`
- `tests/fixtures/replay/mvp1/009-switch-task-confirmation-accepted.fixture.json`
- `tests/fixtures/replay/mvp1/009-switch-task-confirmation-rejected.fixture.json`

**Privacy assertions**

- Confirmation prompt is a `prompt_ref`.
- User confirmation text is synthetic/redacted or referenced.
- No raw text shortcut or secret-bearing authorization ref appears.

**Acceptance criteria**

- Router never cancels or authorizes directly.
- Confirmation state is SlowTask-owned and replayable.
- Terminal cancellation is sticky.
- Switch-task confirmation is mandatory MVP-1 coverage, not optional follow-up coverage.

**Done when**

- Cancel/switch confirmation tests pass.
- Replay reconstructs confirmation and terminal cancellation state.

## Slice 10: MVP-1 Acceptance Runner and Closeout Review

**Goal**

Create a single MVP-1 acceptance runner over the required synthetic scenarios and perform closeout review for scope, replay, privacy, and ADR compliance.

**Non-goals**

No product service startup, no browser/frontend, no real models, no real tools, no MVP-2 demo tool path.

**Implemented files or file areas**

- Existing: `docs/specs/mvp1-acceptance-scenarios.md`
- Existing: `tests/acceptance/test_mvp1_acceptance_scenarios.py`
- Existing: `src/voice_agent/replay/scenario_assertions.py`
- Existing: `tests/fixtures/replay/mvp1/manifest.index.json`

**Events touched**

- All canonical MVP-1 events required by the acceptance scenarios.
- `REPLAY_STARTED`
- `REPLAY_COMPLETED`

**State objects touched**

- `TaskFocusState`
- `SlowTaskState`
- `TracePrivacyState`
- state digest

**Tests**

- Execute all scenarios in `docs/specs/mvp1-acceptance-scenarios.md`.
- Acceptance runner rejects MVP-2-only behavior such as `TOOL_UI_STATE_PATCHED`, `SPOKEN_PLAN_EMITTED`, coverage/truthfulness checks, or demo tools.
- Acceptance runner rejects raw audio/raw trace/secrets/unredacted real input.
- Acceptance runner verifies mock/degraded/real labeling where SLO or capability output is measured.
- Acceptance runner includes a lightweight synthetic eval table derived from fixture outcomes, with at least patch focus, ambiguity handling, and UserPatch interpretation rows. The table is measurement metadata only; it does not require real model evaluation.

**Replay fixture**

- `tests/fixtures/replay/mvp1/manifest.index.json`

Required scenario coverage:

- `MVP1-SPAWN-SLOWTASK-001`
- `MVP1-ACTIVE-PATCH-001`
- `MVP1-PLAN-ADVANCE-001`
- `MVP1-FOREGROUND-CHAT-001`
- `MVP1-AMBIGUOUS-NO-PATCH-001`
- `MVP1-WAITING-SLOT-001`
- `MVP1-STALE-RESULT-001`
- `MVP1-STALE-ADOPTED-001`
- `MVP1-CANCEL-001`
- `MVP1-SWITCH-TASK-001`
- `MVP1-FAILED-001`
- `MVP1-SEMANTIC-COMMITMENT-001`

**Privacy assertions**

- Every committed fixture is synthetic/redacted/minimal.
- No raw audio, raw trace, local replay cache, secret, unredacted real user input, sensitive tool result, or large raw web content appears.

**Acceptance criteria**

- Required MVP-1 scenarios pass.
- Existing MVP-0 acceptance remains passing.
- Synthetic eval table can report patch focus correctness, ambiguity no-patch behavior, and interpretation materiality coverage from fixture metadata.
- Review finds no hidden MVP-2/MVP-3 scope.
- No ADR update is needed to explain implemented behavior.

**Done when**

- `git diff --check` passes.
- `./scripts/test -q` passes.
- Closeout review reports no blocking readiness finding.

## MVP-1 Exit Criteria

MVP-1 closeout is complete when:

- Single active SlowTask can be spawned, patched, replanned, finalized, completed, cancelled, and replayed.
- Failed SlowTask terminal replay is covered.
- `TaskFocusState` prevents obvious foreground chat and ambiguous input from patching active SlowTask.
- UserPatch evidence packs bind `task_id`, `plan_version`, `task_event_seq`, turn ids, evidence refs, and provenance.
- UserPatch never directly mutates task state.
- Material patch advances `plan_version`; non-material patch does not.
- SlowTask replay reconstructs lifecycle state, current plan, stale evidence, adopted evidence, confirmation state, resolved arguments, and SemanticCommitment metadata.
- Old-plan ToolResult defaults to stale evidence and cannot advance current plan without `STALE_EVIDENCE_ADOPTED`.
- SemanticCommitment is current-plan only and records adopted stale evidence sources when used.
- Cancel/switch confirmation flows go through UserPatch interpretation and SlowTask-owned confirmation state.
- Switch-task accepted and rejected paths are mandatory acceptance coverage.
- Terminal SlowTask rejects advancement from late UserPatch, ToolResult, or confirmation.
- Acceptance fixtures are synthetic/redacted/minimal and repo-safe.
- No real Tool Executor, real tool, frontend UI patch, Composer coverage, demo tool, real model adapter, multi active SlowTask, or pause/resume behavior is introduced.

## Stop-and-Update-ADR Conditions

Stop implementation and update accepted ADRs before proceeding if MVP-1 work needs any of the following:

- A new MVP-relevant journal event name not registered in ADR-002 and `docs/specs/event-registry.md`.
- A required binding mismatch between ADR-004 / ADR-016 and `docs/specs/event-registry.md` that cannot be resolved as a derived-spec correction.
- A new RouterDecision beyond `FAST_ONLY`, `SPAWN_SLOW_TASK`, `PATCH_ACTIVE_SLOW_TASK`, and `IGNORE`.
- Router directly interpreting final UserPatch semantics, cancelling tasks, authorizing tools, advancing `plan_version`, or choosing ASR/Thinker winners.
- UserPatch represented as a task mutation rather than evidence.
- Multiple active SlowTasks.
- Pause/resume SlowTask.
- Real Tool Executor, progressive tool execution, or `TOOL_UI_STATE_PATCHED`.
- Real external side-effect tool, external write, payment, booking, deletion, or communication.
- MVP-2 Composer coverage/truthfulness checks or frontend UI patching.
- Production privacy policy.
- Raw audio, raw debug trace, secrets, unredacted real user input, or large raw web content in committed fixtures.
- Any design that allows stale ToolResult to advance current state without `STALE_EVIDENCE_ADOPTED`.
