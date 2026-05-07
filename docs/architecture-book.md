# Architecture Book

Source of truth: frozen ADR Baseline v0.4 from `AGENTS.md` and `docs/adr/*.md`.

This book compiles accepted architecture decisions into an implementation-facing specification. Statements marked with ADR IDs are decisions from the frozen baseline. Statements marked `spec detail, derived from ADR baseline` are implementation specifications that do not add new architecture capability.

## 1. Executive Summary

The voice-agent MVP is an event-driven live voice loop with strict module boundaries, replayable state, adapter-mediated model access, and sandbox-only demo tools. MVP-0 proves turn ingress, interrupt/truncate, event journal, trace/replay, and mock adapter boundaries. MVP-1 adds single active SlowTask, UserPatch evidence packs, plan versioning, and stale result handling. MVP-2 adds progressive demo tools, UI state patches, confirmations for demo destructive actions, Thinker-as-Composer, and coverage/truthfulness checks. MVP-3 replaces mocks with real adapters without adding new architecture capability. [ADR-001, ADR-002, ADR-003, ADR-004, ADR-005, ADR-009, ADR-011, ADR-012, ADR-016]

All critical state transitions must be recorded in a per-session append-only event journal. Replay reconstructs state from recorded events and does not re-run real models or tools by default. [ADR-002, ADR-010]

No business module may call external model endpoints directly. ASR, Thinker, Composer, Slow LLM, TTS, Duplex model, and Embedding/RAG access must go through adapters with declared capability matrices and output mode labels. [ADR-011, AGENTS.md]

## 2. System Goals and Non-Goals

### Goals

- Prove a live loop where audio/text ingress passes through canonical events and the Interaction Controller. [ADR-001, ADR-002, ADR-012]
- Support truncate-only barge-in with playback offsets and replayable causal links. [ADR-003]
- Maintain a per-session event journal as the basis for trace, replay, plan version consistency, and SLO measurement. [ADR-002]
- Keep Router as a post-commit gate, not a deep semantic interpreter. [ADR-006, ADR-008]
- Keep SlowTask as the owner of complex task state, confirmation state, resolved arguments, stale evidence, and SemanticCommitment. [ADR-004, ADR-007, ADR-008, ADR-016]
- Keep tools inside the demo sandbox during MVP and route all tool execution through Tool Executor. [ADR-005, ADR-016]
- Ensure Composer cannot rewrite SemanticCommitment facts and cannot invent progress. [ADR-009, ADR-013]
- Keep trace/replay useful locally while preventing raw audio, raw trace, secrets, PII, and unredacted real user input from entering shareable fixtures or GitHub. [ADR-010, ADR-015, AGENTS.md]

### Non-Goals

- MVP-0 does not require real ASR, real Thinker, real Slow LLM, real TTS, SlowTask, tools, true semantic_close, true assistant-directedness, or pause/resume. [ADR-012]
- MVP-1 does not require real Tool Executor, real external tools, real Slow LLM reasoning, multiple active SlowTasks, or advanced confirmation beyond ADR-016 MVP confirmation state. [ADR-012]
- MVP-2 does not allow real external writes, payment, booking, deletion, production privacy, or production auth. [ADR-005, ADR-012]
- MVP-3 must not add new architecture capability while integrating real adapters. [ADR-012]
- Multi active SlowTask, pause/resume, production privacy, and real side-effect tools are post-MVP and require later ADRs before implementation. [ADR-012, ADR-015, ADR-016]

## 3. Frozen ADR Baseline Summary

| ADR | Accepted decision summary |
| --- | --- |
| ADR-001 | Split Duplex realtime gate, deterministic Interaction Controller, and post-commit semantic routing. |
| ADR-002 | Establish per-session append-only event journal, timing model, canonical event registry, and replay foundation. |
| ADR-003 | Use truncate-only barge-in with playback reference, `BARGE_IN_CANDIDATE`, `TTS_TRUNCATE_REQUESTED`, and `TTS_TRUNCATED`. |
| ADR-004 | Bind SlowTask events to `task_id`, `plan_version`, and `task_event_seq`; stale ToolResult cannot advance current plan unless adopted/rebased. |
| ADR-005 | Run MVP tools through demo backend sandbox and progressive Tool Executor protocol; block real external side effects. |
| ADR-006 | Support single active SlowTask and Router-owned TaskFocusState for post-commit task focus classification. |
| ADR-007 | Define UserPatch as an evidence pack, not a semantic mutation or task patch conclusion. |
| ADR-008 | Treat ASR/Thinker differences as multi-source evidence; SlowTask owns ambiguity and conflict resolution. |
| ADR-009 | Define SemanticCommitment as complex-task fact source and Composer as spoken realization only, guarded by coverage checks. |
| ADR-010 | Define debug-first, repo-safe trace/replay policy and fixture boundaries. |
| ADR-011 | Require all model access through adapters with capability matrices, health events, and degradation/output-mode labels. |
| ADR-012 | Define MVP-0 through MVP-3 vertical slices and development SLOs. |
| ADR-013 | Require progress feedback to be grounded in actual state events and checked by ProgressTruthfulnessCheck. |
| ADR-014 | Mark webSearch as `UNTRUSTED_WEB_EVIDENCE`; keep it in evidence, not instruction context. |
| ADR-015 | Require repo-level governance via `AGENTS.md` and non-negotiable implementation rules. |
| ADR-016 | Define SlowTask lifecycle, confirmation ownership, tool authorization gate, cancellation, retry, and stale handling. |

## 4. Module Ownership

| Module | Responsibilities | Non-responsibilities | Owned state |
| --- | --- | --- | --- |
| Access Layer | Receive user text/audio and emit input/audio span events. [ADR-001, ADR-002] | Does not commit turns, route semantics, or decide interrupts. [ADR-001] | Input span metadata; no turn ownership. |
| Duplex / Realtime Audio Controller | Pre-ASR realtime audio facts, directedness/semantic-close candidates, barge-in candidates. [ADR-001, ADR-003] | Does not commit turns, interpret tasks, or make final tool/SlowTask decisions. [ADR-001] | Realtime audio candidate state; playback reference for echo/barge-in. |
| Interaction Controller | Deterministic turn ingress and playback interruption policy applier. [ADR-001] | Not a semantic model; does not cancel SlowTasks or authorize tools. [ADR-001, ADR-016] | `InteractionState`. |
| Event Journal | Per-session append-only fact record, causal index, timing model, replay source. [ADR-002] | Not a global blocking message bus. [ADR-002] | Event sequence, envelope metadata, redaction level metadata. |
| ASR Adapter | Normalize ASR output or mock transcript/text projection. [ADR-011] | Does not own semantic truth or turn ingress. [ADR-001, ADR-008] | Adapter request/output metadata and capability status. |
| Thinker / Fast System | Foreground support, lightweight replies, SemanticFrame hints, emotion/audio caption/intent/slot hints. [ADR-008, ADR-009] | Does not arbitrate ASR/Thinker conflicts or own complex-task commitments. [ADR-008, ADR-009] | Adapter output metadata; no SlowTask state. |
| Router | Post-commit FAST_ONLY/SPAWN/PATCH/IGNORE decisions and TaskFocusState. [ADR-006] | Does not interpret final UserPatch semantics, cancel tasks, rewrite goals, authorize tools, or choose ASR/Thinker winner. [ADR-006, ADR-008, ADR-016] | `TaskFocusState`. |
| UserPatch Pipeline | Construct evidence packs for active SlowTask. [ADR-007] | Does not mutate task goals, slots, constraints, or plan version directly. [ADR-007] | Patch envelope and evidence refs. |
| SlowTask Runtime | Complex task state, plan version, task_event_seq, evidence review, confirmations, stale evidence, SemanticCommitment. [ADR-004, ADR-008, ADR-016] | Does not own turn ingress, Router focus, or direct tool execution. [ADR-001, ADR-006, ADR-016] | `SlowTaskState`, confirmation state, current plan, resolved arguments, stale evidence. |
| Tool Executor | Manifest validation, argument/provenance validation, authorization, idempotency, sandbox execution, UI patches, tool result normalization. [ADR-005, ADR-016] | Does not mutate SlowTask state directly or execute blocked real side-effect tools. [ADR-005, ADR-016] | `ToolExecutionState` and tool execution metadata. |
| Thinker-as-Composer | Convert SemanticCommitment/progress into SpokenPlan with style/persona. [ADR-009, ADR-013] | Cannot rewrite facts, authorize tools, infer confirmations, or invent progress. [ADR-009, ADR-013, ADR-016] | SpokenPlan draft metadata; no fact ownership. |
| Coverage / Truthfulness Checkers | Check Commitment coverage and progress truthfulness before playback. [ADR-009, ADR-013] | Do not create task facts or tool state. [ADR-009, ADR-013] | Check result metadata. |
| Talker / Playback | TTS or mock playback, playback progress, playback commitment, truncate execution. [ADR-003] | Does not synthesize facts, commit semantics, or decide barge-in policy. [ADR-001, ADR-003] | `PlaybackState`, playback offsets and span ids. |
| Trace / Replay Runtime | Local replay, shareable fixture export boundary, state digest, replay markers. [ADR-002, ADR-010] | Does not re-run real models/tools in default replay or store raw audio in shareable fixtures. [ADR-010] | Replay run state and fixture/export metadata. |
| Adapter Registry | Startup capability snapshot and adapter health/degradation events. [ADR-011] | Does not hide unsupported capabilities or provider-specific schema failures. [ADR-011] | `AdapterHealthState` and capability snapshot refs. |
| Privacy / Redaction | Redact/block secrets and enforce trace domain boundaries. [ADR-010, ADR-015] | Does not allow raw secrets in any trace domain. [ADR-010] | `TracePrivacyState`, redaction audit metadata. |

## 5. Control Plane vs Data Plane

Control plane events are state and policy decisions: session lifecycle, adapter capability snapshots, turn ingress events, Router decisions, TaskFocusState updates, SlowTask lifecycle events, plan version events, confirmation events, tool authorization events, coverage/truthfulness checks, trace/replay markers, and privacy/redaction events. [ADR-002, ADR-004, ADR-006, ADR-009, ADR-010, ADR-011, ADR-016]

Data plane artifacts are referenced payloads: audio chunks, audio refs, text refs, ASR/Thinker frame refs, evidence refs, result refs, UI patch refs, SpokenPlan text/audio refs, and replay fixture refs. Event payloads should prefer refs and redacted summaries over raw sensitive inline data. [ADR-002, ADR-007, ADR-010]

Spec detail, derived from ADR baseline: control plane events must be sufficient to replay state reducers without requiring raw data plane payloads. Data plane refs may be absent in shareable fixtures if redacted summaries preserve the state transition semantics.

## 6. Runtime Event Flow

Canonical high-level flow:

1. Session Runtime records `SESSION_STARTED` and `ADAPTER_CAPABILITY_SNAPSHOT_RECORDED`. [ADR-002, ADR-011]
2. Access Layer records text or audio ingress. [ADR-001, ADR-002]
3. Duplex analyzes audio ingress before ASR/Thinker and emits realtime facts/candidates. Text bypasses Duplex but not Interaction Controller. [ADR-001]
4. Interaction Controller opens, accepts/rejects/holds, and commits turns. Only `TURN_INGRESS_COMMITTED` enters ASR/Thinker/Router. [ADR-001]
5. ASR/Thinker adapters emit mock/real/fallback/degraded frames with output mode labels. [ADR-002, ADR-011]
6. Router emits post-commit decision and updates TaskFocusState when needed. [ADR-006]
7. Fast output may go to Composer/Talker if allowed; slow work enters SlowTask and UserPatch/plan-version lifecycle. [ADR-006, ADR-009, ADR-016]
8. Tool Executor handles progressive tool events and UI patches in MVP-2. [ADR-005, ADR-016]
9. SemanticCommitment or progress events become SpokenPlan through Composer, then pass coverage/truthfulness checks before Talker playback. [ADR-009, ADR-013]
10. Trace / Replay reconstructs state from recorded events and produces replay markers/state digest. [ADR-002, ADR-010]

## 7. Audio Input Path

Responsibilities: Access Layer creates `AUDIO_SPAN_STARTED`, optional `AUDIO_CHUNK_RECEIVED`, and `AUDIO_SPAN_ENDED`; Duplex emits speech and candidate events; Interaction Controller decides ingress. [ADR-001, ADR-002]

Non-responsibilities: Audio path does not let ASR/Thinker decide first ingress commit and does not allow Access Layer to route semantics. [ADR-001]

Owned state: Access Layer owns audio span metadata; Duplex owns realtime candidate state; Interaction Controller owns committed turn state. [ADR-001]

Input events: `AUDIO_SPAN_STARTED`, `AUDIO_CHUNK_RECEIVED`, `AUDIO_SPAN_ENDED`, `SPEECH_START_DETECTED`, `SPEECH_END_DETECTED`, `DIRECTEDNESS_CANDIDATE`, `SEMANTIC_CLOSE_CANDIDATE`, `NON_ASSISTANT_CANDIDATE`, `LOW_CONFIDENCE_INGRESS`. [ADR-002]

Output events: `TURN_OPENED`, `TURN_HELD`, `TURN_INGRESS_ACCEPTED`, `TURN_INGRESS_REJECTED`, `TURN_INGRESS_COMMITTED`; after commit, mock/real ASR and Thinker frame events. [ADR-001, ADR-002]

Invariants:

- No ASRFrame/SemanticFrame may be produced for an audio span without `TURN_INGRESS_COMMITTED`. [ADR-001, ADR-002]
- Audio spans use `audio_span_id`; raw audio is not stored by default. [ADR-007, ADR-010]
- Directedness and semantic_close can be mock/rule-based in MVP-0 but must be labeled honestly. [ADR-011, ADR-012]

Failure modes:

- Low confidence directedness or semantic close causes hold or reject instead of commit. [ADR-001]
- Missing raw audio in default replay means replay reconstructs event state, not audio inference. [ADR-010]
- Unsupported timestamps or semantic_close capability must degrade explicitly. [ADR-011]

Validation / replay scenarios:

- Audio start opens a turn and sets `turn_phase=COLLECTING_INPUT`. [ADR-001]
- Audio end with accepted policy emits `TURN_INGRESS_COMMITTED`. [ADR-001]
- Audio rejected or held never enters ASR/Thinker. [ADR-001, ADR-002]

## 8. Text Input Path

Responsibilities: Access Layer records `TEXT_INPUT_RECEIVED`; Interaction Controller opens, accepts, and commits the turn. [ADR-001, ADR-002]

Non-responsibilities: Text input does not pass through Duplex and must not create a synthetic `audio_span_id`. Access Layer must not bypass Interaction Controller into Router. [ADR-001, ADR-002]

Owned state: `input_span_id`, `text_span_id`, `input_modality=text`, and redacted text/text refs are input metadata; turn state is Interaction Controller-owned. [ADR-001, ADR-002]

Input events: `TEXT_INPUT_RECEIVED`; optional policy-triggered text-during-playback interrupt path. [ADR-002]

Output events: `TURN_OPENED`, `TURN_INGRESS_ACCEPTED`, `TURN_INGRESS_COMMITTED`; optional `INTERRUPT_CANDIDATE` and `TTS_TRUNCATE_REQUESTED` if policy interrupts playback. [ADR-001, ADR-002]

Invariants:

- `audio_span_id=null` for text ingress. [ADR-001, ADR-002]
- `directedness=ASSUMED_DIRECTED` and `semantic_close=ASSUMED_CLOSED` for text ingress. [ADR-001, ADR-002]
- Text ingress is replayable through canonical interaction events. [ADR-002]

Failure modes:

- If text arrives during playback, only Interaction Controller policy may decide whether it interrupts. [ADR-001]
- Raw text must be redacted or referenced according to trace domain. [ADR-007, ADR-010]

Validation / replay scenarios:

- Text path must emit `TEXT_INPUT_RECEIVED` -> `TURN_OPENED` -> `TURN_INGRESS_ACCEPTED` -> `TURN_INGRESS_COMMITTED`. [ADR-001, ADR-002, ADR-012]

## 9. Interaction Controller and Turn Ingress

Responsibilities: Deterministically reduce Duplex/text/access events plus current InteractionState, TaskFocusState summary, SlowTask summary, playback state, and policy into finalized interaction events. [ADR-001]

Non-responsibilities: It is not a semantic model, does not use ASRFrame/SemanticFrame for first ingress commit, and does not own SlowTask cancel/confirmation/tool authorization. [ADR-001, ADR-016]

Owned state: `InteractionState` with `turn_phase`, `playback_phase`, `directedness`, `semantic_close`, current turn/input/audio/text/playback span ids, last ingress outcome, and last interaction event id. [ADR-001]

Input events: access/audio/text events, Duplex candidate/verdict events, `BARGE_IN_CANDIDATE`, `TTS_TRUNCATED`, playback status, and policy state. [ADR-001, ADR-002]

Output events: `TURN_OPENED`, `TURN_INGRESS_ACCEPTED`, `TURN_INGRESS_REJECTED`, `TURN_HELD`, `TURN_INGRESS_COMMITTED`, `INTERRUPT_CANDIDATE`, `TTS_TRUNCATE_REQUESTED`, `WAITING_USER`, `WAITING_CONFIRMATION`. [ADR-001, ADR-002]

Invariants:

- Interaction Controller is the unique owner of turn ingress commit. [ADR-001]
- All finalized interaction events must include causal links sufficient for replay. [ADR-001, ADR-002]
- `PLAYBACK_COMMITTED` is a delivery marker, not semantic acknowledgement. [ADR-001, ADR-002]

Failure modes:

- Low-confidence ingress becomes hold/reject rather than speculative semantic routing. [ADR-001]
- Missing playback state prevents target barge-in validation. [ADR-003]

Validation / replay scenarios:

- Replay reconstructs `InteractionState` from interaction and playback events. [ADR-002]
- Text and audio paths both go through Interaction Controller before Router. [ADR-001, ADR-002]

## 10. Duplex / Realtime Audio Controller

Responsibilities: Pre-ASR speech start/end, VAD, playback overlap, echo likelihood, barge-in confidence, assistant-directedness candidate, semantic_close candidate, reject/hold/accept candidates. [ADR-001, ADR-003]

Non-responsibilities: Does not commit turns, decide task semantics, route tools, own SlowTask, or produce final answers. [ADR-001]

Owned state: Realtime audio analysis state, playback reference association, candidate confidence state. [ADR-001, ADR-003]

Input events: `AUDIO_SPAN_STARTED`, `AUDIO_CHUNK_RECEIVED`, `AUDIO_SPAN_ENDED`, playback reference/progress events. [ADR-002, ADR-003]

Output events: `SPEECH_START_DETECTED`, `SPEECH_END_DETECTED`, `BARGE_IN_CANDIDATE`, `DIRECTEDNESS_CANDIDATE`, `SEMANTIC_CLOSE_CANDIDATE`, `NON_ASSISTANT_CANDIDATE`. [ADR-002]

Invariants:

- Barge-in judgment must retain playback reference interface; no-playback-reference barge-in is demo mock only. [ADR-003]
- Duplex semantic capability serves realtime ingress only, not task semantic authority. [ADR-001]

Failure modes:

- Echo mistaken for user speech creates false barge-in; replay/eval must measure it. [ADR-003, ADR-012]
- Unsupported semantic_close or directedness must be mocked/rule-based/degraded explicitly. [ADR-011]

Validation / replay scenarios:

- Speech start/end and barge-in candidate chain must be replayable to Interaction decisions. [ADR-001, ADR-003]

## 11. Barge-in and TTS Truncate Flow

Responsibilities: Detect overlap, convert it to interrupt policy, request truncate, and record actual truncation. [ADR-003]

Non-responsibilities: MVP does not support pause/resume, semantic-clause resume, multi-track recovery, or model-side cancellation guarantees. [ADR-003, ADR-012]

Owned state: Duplex owns candidate facts; Interaction Controller owns interrupt decision and truncate request; Talker owns playback/truncate execution. [ADR-001, ADR-003]

Input events: `PLAYBACK_SPAN_STARTED`, `PLAYBACK_PROGRESS`, `PLAYBACK_COMMITTED`, `BARGE_IN_CANDIDATE`. [ADR-002, ADR-003]

Output events: `INTERRUPT_CANDIDATE`, `TTS_TRUNCATE_REQUESTED`, `TTS_TRUNCATED`, final playback offset events. [ADR-002, ADR-003]

Invariants:

- Keep three offsets distinct: candidate-time `BARGE_IN_CANDIDATE.playback_offset_ms`, request-time `TTS_TRUNCATE_REQUESTED.cutoff_playback_offset_ms`, and Talker-confirmed `TTS_TRUNCATED.actual_stop_offset_ms`. [ADR-003]
- `TTS_TRUNCATE_REQUESTED` must carry `playback_span_id`, cutoff offset, and causal link. [ADR-003]
- Talker must expose playback progress and unique `playback_span_id`. [ADR-003]

Failure modes:

- Missing playback reference makes target architecture validation fail. [ADR-003, ADR-011]
- TTS adapter without truncate capability cannot pass barge-in target validation and must record degradation. [ADR-011]

Validation / replay scenarios:

- Barge-in to truncate command latency target is <= 250ms and measurable from journal events. [ADR-003, ADR-012]
- Replay reconstructs causal chain from candidate to truncate. [ADR-003]

## 12. Thinker / ASR / Understanding Bundle

Responsibilities: ASR provides text projection; Thinker/Fast System provides SemanticFrame, audio/utterance summaries, emotion/audio caption/intent/slot hints, foreground replies, and task-like/complexity hints. [ADR-008, ADR-009, ADR-011]

Non-responsibilities: ASR is not the sole semantic truth; Thinker does not own SlowTask facts; Router must not choose ASR/Thinker winner. [ADR-008]

Owned state: Adapter output refs, confidence/provenance metadata, output mode labels. [ADR-008, ADR-011]

Input events: `TURN_INGRESS_COMMITTED` and committed span refs. [ADR-001, ADR-002]

Output events: `MOCK_ASR_FRAME_EMITTED`, `MOCK_THINKER_FRAME_EMITTED`, real/fallback/degraded adapter output events, and evidence refs. [ADR-002, ADR-011]

Invariants:

- All model access goes through adapters. [ADR-011, AGENTS.md]
- Outputs must be real/mock/fallback/degraded distinguishable. [ADR-011, ADR-012]
- Key fields carry provenance when entering SlowTask evidence. [ADR-008]

Failure modes:

- Schema validation failure becomes `ADAPTER_OUTPUT_VALIDATION_FAILED`; unsupported capability becomes degradation/fail-fast event. [ADR-011]
- FAST_ONLY replies must avoid committing uncertain critical fields. [ADR-008]

Validation / replay scenarios:

- MVP-0 uses mock ASR/Thinker after commit only. [ADR-002, ADR-012]
- Evidence fusion scenarios preserve ASR n-best and Thinker summary conflicts for SlowTask review. [ADR-007, ADR-008]

## 13. Router and TaskFocus Policy

Responsibilities: Post-commit gate to `FAST_ONLY`, `SPAWN_SLOW_TASK`, `PATCH_ACTIVE_SLOW_TASK`, or `IGNORE`; classify task focus when an active SlowTask exists. [ADR-006]

Non-responsibilities: Does not interpret final UserPatch semantics, cancel/pause tasks, authorize tools, rewrite goals, or arbitrate ASR/Thinker conflicts. [ADR-006, ADR-008, ADR-016]

Owned state: `TaskFocusState` with active task id, foreground mode, side conversation policy, default patch policy, ambiguous input policy, last focus decision/confidence/event id. [ADR-006]

Input events: `TURN_INGRESS_COMMITTED`, ASR/Thinker evidence if available, current TaskFocusState, active SlowTask summary. [ADR-006]

Output events: `ROUTER_DECISION_EMITTED`, `TASK_FOCUS_STATE_UPDATED`, UserPatch construction trigger when patching active task. [ADR-002, ADR-006]

Invariants:

- MVP supports only one active non-terminal SlowTask. [ADR-006]
- Ambiguous input must not patch active task by default; obvious foreground chat stays FAST_ONLY. [ADR-006]
- New task candidate while active task exists goes through UserPatch control evidence and SlowTask confirmation, not automatic replacement. [ADR-006, ADR-016]

Failure modes:

- Misrouting contaminates active SlowTask; patch misrouting rate must be measurable. [ADR-006, ADR-012]
- `NON_ASSISTANT` post-commit input must not enter SlowTask. [ADR-006]

Validation / replay scenarios:

- Replay reconstructs TaskFocusState from `ROUTER_DECISION_EMITTED` and `TASK_FOCUS_STATE_UPDATED`. [ADR-002, ADR-006]

## 14. SlowTask Lifecycle

Responsibilities: Own SlowTaskState, current plan version, task_event_seq, goal/constraints/resolved arguments, confirmation state, stale/adopted evidence, terminal outcome, evidence review, ambiguity resolution, and SemanticCommitment. [ADR-004, ADR-008, ADR-016]

Non-responsibilities: Does not own ingress, Router focus, direct tool execution, or spoken realization. [ADR-001, ADR-006, ADR-016]

Owned state: `SlowTaskState`, current `plan_version`, `task_event_seq`, task goal/constraints, resolved arguments, confirmation state, stale evidence, adopted/rebased evidence metadata, terminal outcome. [ADR-016]

Input events: `ROUTER_DECISION_EMITTED(SPAWN_SLOW_TASK)`, `USER_PATCH_RECEIVED`, `TOOL_RESULT_RECEIVED`, tool failure/cancel events, adapter failures, stale evidence events, confirmation-related UserPatch interpretations. [ADR-002, ADR-004, ADR-016]

Output events: `SLOWTASK_CREATED`, `SLOWTASK_STATE_CHANGED`, `EVIDENCE_REVIEWED`, `AMBIGUITY_DETECTED`, `AMBIGUITY_RESOLVED`, `CLARIFICATION_REQUESTED`, `ARGUMENTS_RESOLVED`, `PLAN_VERSION_ADVANCED`, `TASK_REPLANNED`, `CONFIRMATION_REQUIRED`, `SLOWTASK_CANCEL_REQUESTED`, `SLOWTASK_CANCELLED`, `FINALIZING`, `SEMANTIC_COMMITMENT_EMITTED`, `SLOWTASK_DEGRADED`, `SLOWTASK_FAILED`. [ADR-002, ADR-008, ADR-016]

Invariants:

- Every SlowTask state transition emits `SLOWTASK_STATE_CHANGED`. [ADR-016]
- Terminal states are `COMPLETED`, `CANCELLED`, `FAILED`; terminal tasks cannot be advanced by late UserPatch/ToolResult/confirmation. [ADR-016]
- SemanticCommitment must use current `plan_version` and record adopted stale evidence sources if used. [ADR-004]

Failure modes:

- Old plan ToolResult becomes stale evidence and cannot advance state unless explicitly adopted/rebased. [ADR-004, ADR-016]
- Pending confirmation becomes invalid if plan_version advances and must be rejected or superseded. [ADR-016]
- Missing critical evidence causes clarification or insufficient-evidence events. [ADR-008, ADR-016]

Validation / replay scenarios:

- MVP-1 must replay create, planning, waiting-slot, replanning, completed, cancelled, failed, stale-result paths. [ADR-012, ADR-016]

## 15. UserPatch and Plan Versioning

Responsibilities: UserPatch pipeline captures authoritative evidence and non-authoritative hypotheses for active SlowTask; SlowTask interprets it against observed plan version. [ADR-004, ADR-007]

Non-responsibilities: UserPatch itself is not a plan, state mutation, goal rewrite, slot patch, confirmation, or cancel. [ADR-007]

Owned state: Patch id/envelope, source event refs, authoritative evidence refs, non-authoritative hypothesis fields, redaction metadata. [ADR-007]

Input events: Router patch decision, committed turn evidence, ASR/Thinker/Duplex/TaskFocus evidence. [ADR-006, ADR-007, ADR-008]

Output events: `USER_PATCH_RECEIVED`, `USER_PATCH_INTERPRETED`, optional `PLAN_VERSION_ADVANCED`, optional `TASK_REPLANNED` / `PLANNING_RESTARTED`. [ADR-002, ADR-004, ADR-007]

Invariants:

- `USER_PATCH_RECEIVED.plan_version` is the pre-advance current plan version. [ADR-004, ADR-007]
- Not every UserPatch advances plan_version. [ADR-004, ADR-007]
- Secret-like content must be redacted or blocked before journal write. [ADR-007, ADR-010]

Failure modes:

- Router misclassification becomes non-authoritative evidence and must not mutate SlowTask without interpretation. [ADR-006, ADR-007]
- Shareable replay cannot contain unredacted real user input. [ADR-007, ADR-010]

Validation / replay scenarios:

- Replay reconstructs UserPatch to interpretation to optional plan advance causal chain. [ADR-004, ADR-007]

## 16. Tool Risk and Side Effect Policy

Responsibilities: Tool Executor runs all tools through adapters/manifests, validates current plan, arguments, provenance, side-effect class, confirmation, idempotency, and emits progressive tool events. [ADR-005, ADR-016]

Non-responsibilities: Slow Agent may propose tool calls but cannot directly call external services; Tool Executor cannot mutate SlowTask state directly. [ADR-005, ADR-016]

Owned state: ToolExecutionState, manifest version, authorization event refs, idempotency keys, retry/cancel state, UI patch refs. [ADR-005, ADR-016]

Input events: `ARGUMENTS_RESOLVED`, `CONFIRMATION_ACCEPTED`, `TOOL_MANIFEST_LOADED`, SlowTask current plan metadata, tool adapter responses. [ADR-005, ADR-016]

Output events: `TOOL_ARGUMENTS_PARTIAL`, `TOOL_ARGUMENTS_READY`, `TOOL_PREVIEW_AVAILABLE`, `TOOL_EXECUTION_AUTHORIZED`, `TOOL_EXECUTION_STARTED`, `TOOL_PROGRESS_UPDATED`, `TOOL_UI_STATE_PATCHED`, `TOOL_RESULT_RECEIVED`, `TOOL_EXECUTION_FAILED`, `TOOL_CALL_RETRYING`, `TOOL_EXECUTION_CANCELLED`, `TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS`. [ADR-002, ADR-005, ADR-016]

Invariants:

- MVP allows `READ_ONLY`, `DRY_RUN`, `SANDBOX_WRITE`, and confirmed `DEMO_DESTRUCTIVE_ACTION`; blocks `EXTERNAL_WRITE`, `EXTERNAL_COMMUNICATION`, `BOOKING_OR_PAYMENT`, and real `DELETION`. [ADR-005, ADR-016]
- `DEMO_DESTRUCTIVE_ACTION` requires current-plan `CONFIRMATION_ACCEPTED`. [ADR-005, ADR-016]
- Frontend UI state changes only through `TOOL_UI_STATE_PATCHED`. [ADR-005, AGENTS.md]
- webSearch is evidence, not instruction. [ADR-014]

Failure modes:

- Missing resolved arguments/provenance emits `TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS`; no execution starts. [ADR-008, ADR-016]
- Tool failure/retry/cancel must be journaled and interpreted by SlowTask. [ADR-016]
- Old plan result is stale and cannot advance current state. [ADR-004, ADR-016]

Validation / replay scenarios:

- MVP-2 replays progressive tool call, UI patch, demo destructive confirmation, blocked real side-effect, and stale result cases. [ADR-005, ADR-012, ADR-016]

## 17. SemanticCommitment and Composer Contract

Responsibilities: SlowTask emits SemanticCommitment; Thinker-as-Composer converts approved facts/progress into SpokenPlan; checkers verify coverage/truthfulness. [ADR-009, ADR-013]

Non-responsibilities: Composer cannot modify immutable facts, delete must-say fields, authorize tools, infer confirmation, treat dry-run as execution, or use unadopted stale evidence as current fact. [ADR-009, ADR-013, ADR-016]

Owned state: SlowTask owns SemanticCommitment; Composer owns SpokenPlan drafts; Coverage/Truthfulness checkers own check result metadata. [ADR-009, ADR-013]

Input events: `SEMANTIC_COMMITMENT_EMITTED`, SlowTask progress events, tool status, confirmation state, InteractionState summary, TaskFocusState summary, persona/style config. [ADR-009, ADR-013]

Output events: `SPOKEN_PLAN_EMITTED`, `COMMITMENT_COVERAGE_CHECK_PASSED`, `COMMITMENT_COVERAGE_CHECK_FAILED`, `PROGRESS_TRUTHFULNESS_CHECK_PASSED`, `PROGRESS_TRUTHFULNESS_CHECK_FAILED`. [ADR-002, ADR-009, ADR-013]

Invariants:

- Talker can play SemanticCommitment-derived speech only after coverage check passes. [ADR-009]
- Talker can play progress speech only after progress truthfulness check passes. [ADR-013]
- Progress must be grounded in actual state events. [ADR-013]

Failure modes:

- Coverage/truthfulness failure blocks playback and requires retry, template fallback, or degraded response. [ADR-009, ADR-013]
- Unsupported progress language is blocked. [ADR-013]

Validation / replay scenarios:

- Replay reconstructs SemanticCommitment/progress -> SpokenPlan -> check -> playback causal chain. [ADR-009, ADR-013]

## 18. Talker / Playback Control

Responsibilities: Start playback only for approved SpokenPlan/output, report progress and committed offsets, execute truncate, and emit playback events. [ADR-003, ADR-009, ADR-013]

Non-responsibilities: Talker does not create SemanticCommitment, perform coverage checks, or decide barge-in policy. [ADR-003, ADR-009]

Owned state: `PlaybackState`, current `playback_span_id`, offsets, approval check ref, truncate state. [ADR-003]

Input events: approved SpokenPlan/check pass events, `TTS_TRUNCATE_REQUESTED`, TTS adapter output. [ADR-003, ADR-009, ADR-013]

Output events: `PLAYBACK_SPAN_STARTED`, `PLAYBACK_PROGRESS`, `PLAYBACK_COMMITTED`, `PLAYBACK_FINISHED`, `TTS_TRUNCATED`. [ADR-002, ADR-003]

Invariants:

- `PLAYBACK_COMMITTED` is only a playback delivery marker, not proof of user comprehension or semantic acknowledgement. [ADR-001, ADR-002]
- Playback started for checked content must reference the approved check event or check result. [ADR-009, ADR-013]
- Truncate support is required for target barge-in validation. [ADR-003, ADR-011]

Failure modes:

- Missing truncate capability causes degraded/fail validation event. [ADR-011]
- Playback progress too sparse may reduce replay/SLO fidelity; progress frequency remains an ADR open question. [ADR-003]

Validation / replay scenarios:

- Replay verifies playback offset chain and truncate offsets. [ADR-003]

## 19. Trace / Replay / Privacy

Responsibilities: Record local debug traces, enforce export boundaries, replay events into state reducers, produce replay markers and state digest, redact/block secrets. [ADR-002, ADR-010]

Non-responsibilities: Default replay does not re-run real models/tools and shareable fixtures do not contain raw audio, raw trace, secrets, PII, unredacted tool results, or large raw web content. [ADR-010]

Owned state: Replay run state, trace domain metadata, redaction/export status, state digest metadata. [ADR-010]

Input events: full event journal, redaction/export requests, replay requests. [ADR-002, ADR-010]

Output events: `REPLAY_STARTED`, `REPLAY_COMPLETED`, `TRACE_WRITE_DEGRADED`, `TRACE_SECRET_REDACTION_APPLIED`, `TRACE_WRITE_BLOCKED_SECRET_DETECTED`. [ADR-002, ADR-010]

Invariants:

- Secrets never enter trace in raw form. [ADR-010, AGENTS.md]
- Raw audio is local debug opt-in only and never GitHub/shareable. [ADR-010, ADR-015]
- Shareable fixtures must be synthetic, redacted, or minimal. [ADR-010, ADR-015]

Failure modes:

- Redaction failure blocks write/export and records blocked event. [ADR-010]
- Async persistence failure records degraded trace state. [ADR-002]

Validation / replay scenarios:

- MVP-0 local trace safety case verifies defaults, redaction, and replay of InteractionState. [ADR-010, ADR-012]

## 20. Model Adapter Capability Contract

Responsibilities: Adapter Registry records startup capability snapshot; adapters normalize provider output, report health, timeouts, retries, validation failures, degradations, and output mode. [ADR-011]

Non-responsibilities: Business modules cannot depend on provider-specific APIs or hidden capabilities. [ADR-011]

Owned state: Capability matrix, adapter health, error/retry policy, deployment mode, output mode refs. [ADR-011]

Input events: session startup, healthcheck requests, adapter requests, provider responses/errors/timeouts. [ADR-011]

Output events: `ADAPTER_CAPABILITY_SNAPSHOT_RECORDED`, `ADAPTER_HEALTHCHECK_FAILED`, `ADAPTER_REQUEST_RETRYING`, `ADAPTER_REQUEST_FAILED`, `ADAPTER_OUTPUT_VALIDATION_FAILED`, `ADAPTER_OUTPUT_DEGRADED`, adapter frame/output events. [ADR-002, ADR-011]

Invariants:

- Unsupported capabilities must be explicit, never silently assumed. [ADR-011]
- Mock outputs must be labeled mock and cannot count as real target validation. [ADR-011, ADR-012]
- Adapter must not log secrets. [ADR-011]

Failure modes:

- No TTS truncate capability blocks target barge-in validation. [ADR-011]
- No structured JSON in Slow LLM triggers parser/validator retry then failure or fallback. [ADR-011]
- No emotion means unavailable, not neutral. [ADR-011]

Validation / replay scenarios:

- MVP-0 records mock capability snapshot; MVP-3 records real adapter capability and failures without adding architecture capability. [ADR-011, ADR-012]

## 21. MVP-0 / MVP-1 / MVP-2 / MVP-3 Scope

### MVP-0

Proves event-driven live loop skeleton: mock audio/text ingress, Duplex events, Interaction Controller, event journal, Router, mock Thinker, mock TTS/Talker, playback offsets, interrupt/truncate, local replay, and optional basic frontend loop. [ADR-012]

### MVP-1

Adds single active SlowTask, TaskFocusState, UserPatch, mock SlowTask lifecycle, plan_version, task_event_seq, stale ToolResult mock, SemanticCommitment mock, ASR/Thinker evidence fusion mock, and SlowTask replay. [ADR-012]

### MVP-2

Adds demo backend sandbox tools, progressive invocation, at least three demo tools, `TOOL_UI_STATE_PATCHED`, demo destructive light confirmation, ADR-016 tool authorization gate, Thinker-as-Composer, CommitmentCoverageCheck, ProgressTruthfulnessCheck, truthful progress, and replay of tool/frontend state. [ADR-005, ADR-009, ADR-012, ADR-013, ADR-016]

### MVP-3

Integrates real adapters for ASR, Thinker, Slow LLM, and TTS via capability contract and health/error events, without adding new architecture capability. [ADR-011, ADR-012]

## 22. Validation and Replay Strategy

- Each MVP slice must have replay or eval scenarios before it is considered complete. [ADR-012, AGENTS.md]
- MVP-0 scenarios are specified in `docs/specs/mvp0-acceptance-scenarios.md`. [ADR-012]
- Event schemas are specified in `docs/specs/event-registry.md`; reducers are specified in `docs/specs/state-reducers.md`. These are spec details derived from ADR-002. [ADR-002]
- Replay modes and fixture boundaries are specified in `docs/specs/replay-spec.md`. These are spec details derived from ADR-002 and ADR-010. [ADR-002, ADR-010]
- Adapter capability and degradation mapping is specified in `docs/specs/model-adapter-capabilities.md`. This is a spec detail derived from ADR-011. [ADR-011]
- Development SLOs must be calculated from event timestamps and labeled mock/degraded/real. [ADR-012]

## 23. New ADR Required

No P0 / P1-A contradiction was found inside the frozen ADR baseline during this compilation pass.

New ADR or ADR update is required before implementing any of these as facts:

- Treating non-canonical prompt labels such as `SEMANTIC_COMMITMENT_CREATED`, `SPOKEN_PLAN_CREATED`, or `STALE_TOOL_RESULT_RECORDED` as new journal event names instead of mapping them to ADR-002 canonical events. [ADR-002]
- Multi active SlowTask, pause/resume SlowTask, pause/resume TTS, real external side-effect tools, production privacy policy, or production auth. [ADR-012, ADR-015, ADR-016]
- Any MVP-relevant event name not registered in ADR-002. [ADR-002, ADR-015]

## 24. Open Questions

These are frozen ADR open questions carried forward as non-blocking questions. They are not implementation backlog items in this document.

- MVP-0 directedness/semantic_close default: mock, rule-based, or unknown. [ADR-001]
- `TURN_INGRESS_REJECTED` trace retention level. [ADR-001]
- Candidate vs verdict naming for Duplex outputs beyond current registry. [ADR-001]
- Low-confidence directedness default policy. [ADR-001]
- Event journal file format, flush policy, and session/conversation sequence scope. [ADR-002]
- Playback progress frequency, truncate actual-stop offset reporting, Composer awareness of already-played text/token span, and echo_likelihood mock defaults. [ADR-003]
- `task_event_seq` allocator, stale_evidence TTL, and cross-version stale evidence propagation. [ADR-004]
- Demo backend source-of-truth boundaries, tool preview requirement, webSearch mock vs real API, manifest load timing, and UI patch granularity. [ADR-005]
- `foreground_mode` enum, progress vs foreground priority, switch-task prompt ownership, and ambiguity clarification wording. [ADR-006]
- UserPatch raw_text use in audio input, ASR n-best limit, multiple candidate patch types, and structured interpretation reason requirement. [ADR-007]
- SlowTask ambiguity resolver implementation mode, FAST_ONLY uncertainty guardrail, normalized provenance values, and wrong-resolution eval labeling. [ADR-008]
- CoverageCheck implementation method, Composer prompt/profile separation, immutable fact representation, FAST_ONLY SpokenPlan bypass, degraded response template, and multi-part must-say coverage. [ADR-009]
- Trace storage format, raw audio opt-in scope, shareable export timing, secret detection method, local cleanup, and gitignore coverage verification. [ADR-010]
- Capability static vs probed source, frontend capability display, structured JSON retry count, Fast/Composer adapter profile sharing, latency representation, and adapter compatibility suite. [ADR-011]
- MVP-0 frontend requirement, MVP-2 first demo tools, webSearch mode, SLO hard gate, MVP-3 model endpoint choices, and slice demo/replay fixture split. [ADR-012]
- Progress filler classification, frontend progress display, and repeated waiting cadence. [ADR-013]
- webSearch mock vs real API, snippet length, source URL requirement, synthetic prompt-injection eval count, and attribution template. [ADR-014]
- Trace/audio/replay directory configurability, ADR register content scope, and AGENTS.md language style. [ADR-015]
- Confirmation timeout product policy and future pause/resume ADR. [ADR-016]
