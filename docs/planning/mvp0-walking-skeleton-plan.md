# MVP-0 Walking Skeleton Plan

> Historical note: this document was originally a planning-only artifact. The MVP-0 plan described here has now been executed through Slice 9 on main. The document remains useful as the implementation trace and scope guard for the completed MVP-0 walking skeleton.

**Current status:** MVP-0 local walking skeleton is implemented in `src/voice_agent/`, covered by tests under `tests/`, and backed by synthetic replay fixtures under `tests/fixtures/replay/mvp0/`. `./scripts/test -q` currently passes with 124 tests. No real model adapters, SlowTask runtime, Tool Executor, Composer checks, frontend demo, or real external side effects are present.

**Goal:** Turn the accepted MVP-0 backlog into an implementation-ready walking skeleton plan for the event-driven live loop.

**Architecture:** MVP-0 proves the system spine with faithful mocks: Access Layer, Duplex mock/rule path, Interaction Controller, Event Journal, mock ASR/Thinker adapters, Router FAST_ONLY/IGNORE skeleton, mock Talker playback, truncate-only barge-in, deterministic replay, and repo-safe fixture gates. All critical state transitions must be represented by canonical events and replayable reducers.

**Tech Stack:** Python control plane, `pytest`, synthetic JSON replay fixtures, deterministic reducers, adapter capability snapshots, and per-session serialized event journal append.

---

## 1. Source of Truth

Implementation must use these documents as source contracts:

- `AGENTS.md`
- `stage_b_adr_register.md`
- `docs/project-overview.md`
- `docs/architecture-book.md`
- `docs/adr-traceability-matrix.md`
- `docs/planning/execution-roadmap.md`
- `docs/implementation/mvp0-backlog.md`
- `docs/specs/event-registry.md`
- `docs/specs/state-reducers.md`
- `docs/specs/replay-spec.md`
- `docs/specs/model-adapter-capabilities.md`
- `docs/specs/mvp0-acceptance-scenarios.md`
- `docs/development/python-runtime-policy.md`
- Accepted ADRs under `docs/adr/`, especially ADR-001, ADR-002, ADR-003, ADR-010, ADR-011, ADR-012, and ADR-015 for MVP-0.

Precedence:

1. `AGENTS.md`, accepted ADRs, and `stage_b_adr_register.md`.
2. Derived implementation specs in `docs/specs/*.md`.
3. Planning/backlog documents.
4. This plan.

If this plan conflicts with accepted ADRs or `AGENTS.md`, stop and fix the plan before implementation.

## 2. MVP-0 Scope

MVP-0 proves:

- Text ingress via `TEXT_INPUT_RECEIVED -> TURN_OPENED -> TURN_INGRESS_ACCEPTED -> TURN_INGRESS_COMMITTED`.
- Audio ingress via `AUDIO_SPAN_STARTED`, Duplex mock speech events, and Interaction Controller commit.
- Per-session append-only event journal with strictly increasing `event_seq`.
- Mock ASR and mock Thinker output only after `TURN_INGRESS_COMMITTED`.
- Startup adapter capability snapshot with explicit `output_mode=mock`.
- Router post-commit FAST_ONLY/IGNORE skeleton.
- Mock Talker playback span, progress, delivery markers, and truncate confirmation.
- Barge-in causal chain: `BARGE_IN_CANDIDATE -> INTERRUPT_CANDIDATE -> TTS_TRUNCATE_REQUESTED -> TTS_TRUNCATED`.
- Deterministic replay for `InteractionState`, `PlaybackState`, `AdapterHealthState`, `TracePrivacyState`, and minimal/inert `TaskFocusState` where Router replay needs it.
- Synthetic/redacted/minimal replay fixtures and local trace safety gates.
- Development SLO calculation from event timestamps, with results labeled `mock`, `degraded`, or `real`.

MVP-0 must not implement:

- Real ASR, real TTS, real Qwen3-Omni, real GLM, real Slow LLM, real Thinker, or provider endpoints.
- Direct external model calls outside adapters.
- SlowTask runtime, complete UserPatch plan version flow, stale ToolResult policy, SemanticCommitment, or Composer coverage checks.
- Demo tools, real external tools, real side-effect tools, frontend UI state patching, webSearch, payment, booking, deletion, or external communication.
- Pause/resume TTS, semantic-clause resume, multi-track recovery, full semantic_close, or full assistant-directedness.
- Raw audio fixtures, raw debug traces, local replay cache committed to Git, secrets, unredacted real user input, or large raw web content.

## 3. Directory and File Plan

This section originally described future implementation paths. These MVP-0 paths now exist in the repository and remain listed here as the implemented walking skeleton layout.

### Implemented Source Layout

| Path | Responsibility |
| --- | --- |
| `src/voice_agent/__init__.py` | Python package marker only. |
| `src/voice_agent/config/runtime_config.py` | Local runtime config, trace defaults, and artifact path policy. |
| `src/voice_agent/events/envelope.py` | Common event envelope schema and validation. |
| `src/voice_agent/events/registry.py` | MVP-0 canonical event-name and required-field validator derived from `docs/specs/event-registry.md`. |
| `src/voice_agent/events/journal.py` | Per-session append-only in-memory journal and serialized `event_seq` allocation. |
| `src/voice_agent/privacy/redaction.py` | Secret detection, redaction, and write blocking before journal append. |
| `src/voice_agent/adapters/capabilities.py` | Capability matrix types and validation. |
| `src/voice_agent/adapters/mock_adapters.py` | Mock ASR, Thinker, and TTS/Talker capability declarations. |
| `src/voice_agent/runtime/session.py` | Session startup flow and capability snapshot emission. |
| `src/voice_agent/state/interaction_state.py` | Deterministic `InteractionState` reducer. |
| `src/voice_agent/state/playback_state.py` | Deterministic `PlaybackState` reducer. |
| `src/voice_agent/state/adapter_health_state.py` | Deterministic `AdapterHealthState` reducer. |
| `src/voice_agent/state/trace_privacy_state.py` | Deterministic `TracePrivacyState` reducer. |
| `src/voice_agent/state/task_focus_state.py` | Minimal/inert MVP-0 Router state reducer. |
| `src/voice_agent/replay/manifest.py` | Replay manifest schema and fixture-domain checks. |
| `src/voice_agent/replay/runner.py` | Deterministic replay runner. |
| `src/voice_agent/replay/state_digest.py` | Stable digest excluding raw/sensitive payloads. |
| `src/voice_agent/replay/scenario_assertions.py` | MVP-0 scenario assertion helpers. |
| `src/voice_agent/access/text_ingress.py` | Text ingress event creation. |
| `src/voice_agent/access/audio_ingress.py` | Audio span metadata event creation, with no raw audio storage. |
| `src/voice_agent/duplex/mock_duplex.py` | Mock/rule speech start/end and barge-in candidates. |
| `src/voice_agent/interaction/controller.py` | Deterministic turn ingress and interrupt policy applier. |
| `src/voice_agent/interaction/policy.py` | MVP-0 assumed-directed/assumed-closed and truncate policy constants. |
| `src/voice_agent/understanding/mock_asr.py` | Mock ASR frame emission after commit only. |
| `src/voice_agent/understanding/mock_thinker.py` | Mock semantic frame emission after commit only. |
| `src/voice_agent/router/router.py` | Post-commit FAST_ONLY/IGNORE MVP-0 Router skeleton. |
| `src/voice_agent/talker/mock_talker.py` | Mock playback span lifecycle, progress, commit marker, finish, and truncate. |

### Implemented Test and Fixture Layout

| Path | Responsibility |
| --- | --- |
| `tests/conftest.py` | Test helpers for synthetic ids, timestamps, and fixture loading. |
| `tests/events/` | Event envelope, registry, journal, append-only, and redaction tests. |
| `tests/adapters/` | Capability matrix and mock adapter output-mode tests. |
| `tests/runtime/` | Session startup and capability snapshot tests. |
| `tests/state/` | Reducer and state digest tests. |
| `tests/replay/` | Deterministic replay, fixture safety, and per-scenario replay tests. |
| `tests/interaction/` | Text ingress, controller, and barge-in/truncate tests. |
| `tests/duplex/` | Mock audio accept and barge-in candidate tests. |
| `tests/understanding/` | Mock ASR/Thinker ordering tests. |
| `tests/router/` | FAST_ONLY/IGNORE and post-commit ordering tests. |
| `tests/talker/` | Mock playback lifecycle tests. |
| `tests/slo/` | MVP-0 synthetic latency metric tests. |
| `tests/acceptance/` | Five MVP-0 acceptance scenario tests. |
| `tests/fixtures/replay/mvp0/` | GitHub-allowed synthetic/redacted/minimal fixtures. |

### Local-Only Paths

These paths are local-only and must remain ignored before any runtime writes to them:

- `diagnostics/`
- `traces/`
- `replays/local/`
- `audio/raw/`
- `.env`
- `.env.*`

## 4. Execution Rules for Every Slice

- Start each slice by reading the relevant accepted ADR and spec sections again.
- Write tests and fixtures before or alongside implementation.
- Use canonical event names from `docs/specs/event-registry.md`.
- Bind all events to the common envelope and causal links required for replay.
- Keep journal append serialized per session; one path allocates `event_seq`.
- Do not let reducers, replay, Interaction Controller, or journal validation call networks, models, tools, clocks, randomness, or missing-ref fetchers.
- Keep all fixtures synthetic/redacted/minimal and under `tests/fixtures/replay/mvp0/`.
- Mark every mock output and SLO result as `mock`.
- Run slice-local tests plus fixture safety before committing.
- Use the commit messages suggested below only after implementation and verification; this planning task does not stage or commit.

## 5. Slice 0: Repo Safety and Runtime Skeleton

**Goal**

Prepare the minimal Python package/test skeleton and repo safety guardrails before any runtime artifact can be produced.

**Expected Files**

- Modify: `.gitignore` only if required local-only exclusions are missing.
- Create: `src/voice_agent/__init__.py`
- Create: `src/voice_agent/config/runtime_config.py`
- Create: `tests/conftest.py`
- Create: `tests/fixtures/replay/mvp0/README.md`
- Create: `tests/fixtures/replay/mvp0/000-empty-session.fixture.json`
- Create: `tests/replay/test_fixture_safety.py`

**Tests**

- `pytest tests/replay/test_fixture_safety.py -q`
- Validate `.gitignore` or equivalent exclusion covers local debug, trace, replay cache, raw audio, and env secret paths.
- Fixture safety scan rejects raw audio refs, raw trace payloads, secret-like fields, unredacted real user text, and large raw web content.

**Fixture**

- `tests/fixtures/replay/mvp0/000-empty-session.fixture.json`
- Domain: `GITHUB_ALLOWED`
- Generated from: `hand_written_minimal` or `synthetic`

**Acceptance Criteria**

- Local artifact exclusions exist before runtime writes traces, raw audio, or local replay cache.
- Committed fixture directory is separate from `replays/local/`.
- Test harness can run without service startup, real models, real tools, `src/` side effects, or local debug artifacts.

**Suggested Commit Message**

- `chore: add mvp0 repo safety skeleton`

## 6. Slice 1: Event Envelope and Append-Only Journal

**Goal**

Implement MVP-0 event envelope validation, canonical event-name validation, per-session `event_seq`, append-only in-memory journal, and pre-write redaction/blocking.

**Expected Files**

- Create: `src/voice_agent/events/envelope.py`
- Create: `src/voice_agent/events/registry.py`
- Create: `src/voice_agent/events/journal.py`
- Create: `src/voice_agent/privacy/redaction.py`
- Create: `tests/events/test_event_envelope.py`
- Create: `tests/events/test_event_journal.py`
- Create: `tests/fixtures/replay/mvp0/001-event-envelope-session-start.fixture.json`

**Tests**

- `pytest tests/events/test_event_envelope.py tests/events/test_event_journal.py -q`
- Event creation requires common envelope fields from `docs/specs/event-registry.md`.
- `event_seq` is strictly increasing per session and never sorted by wall clock.
- Unknown MVP-relevant event names fail validation.
- Root events and non-root causal-link rules are enforced.
- Secret-like payloads are redacted or blocked before append.

**Fixture**

- `tests/fixtures/replay/mvp0/001-event-envelope-session-start.fixture.json`
- Includes `SESSION_STARTED` and a minimal valid envelope chain.

**Acceptance Criteria**

- Journal is append-only and deterministic.
- MVP-0 event names are accepted only when registered.
- Event payloads do not store API keys, tokens, cookies, credentials, authorization headers, session secrets, raw text, or raw audio.

**Suggested Commit Message**

- `feat: add event journal envelope`

## 7. Slice 2: Capability Snapshot and Mock Adapter Contracts

**Goal**

Record startup capability snapshots and define honest MVP-0 mock adapter capability matrices.

**Expected Files**

- Create: `src/voice_agent/adapters/capabilities.py`
- Create: `src/voice_agent/adapters/mock_adapters.py`
- Create: `src/voice_agent/runtime/session.py`
- Create: `tests/adapters/test_mock_capability_snapshot.py`
- Create: `tests/runtime/test_session_startup.py`
- Create: `tests/fixtures/replay/mvp0/002-mock-capability-snapshot.fixture.json`

**Tests**

- `pytest tests/adapters/test_mock_capability_snapshot.py tests/runtime/test_session_startup.py -q`
- Session startup emits `SESSION_STARTED` followed by `ADAPTER_CAPABILITY_SNAPSHOT_RECORDED`.
- Mock ASR, mock Thinker, and mock TTS/Talker matrices declare all required capability fields.
- Mock outputs and capability snapshots expose `output_mode=mock`.
- Unsupported capabilities are explicit and never silently assumed.
- Endpoint/config refs do not contain credentials.

**Fixture**

- `tests/fixtures/replay/mvp0/002-mock-capability-snapshot.fixture.json`
- Replay reconstructs `AdapterHealthState` from snapshot without probing adapters.

**Acceptance Criteria**

- `MVP0-MOCK-ADAPTER-CAPABILITY-001` can pass against runtime and replay.
- Mock capability is not counted as real target validation.
- No provider endpoint or real adapter code exists.

**Suggested Commit Message**

- `feat: record mock adapter capabilities`

## 8. Slice 3: Deterministic State Reducers and Replay Core

**Goal**

Implement deterministic replay over recorded events and MVP-0 reducer targets.

**Expected Files**

- Create: `src/voice_agent/state/interaction_state.py`
- Create: `src/voice_agent/state/playback_state.py`
- Create: `src/voice_agent/state/adapter_health_state.py`
- Create: `src/voice_agent/state/trace_privacy_state.py`
- Create: `src/voice_agent/replay/manifest.py`
- Create: `src/voice_agent/replay/runner.py`
- Create: `src/voice_agent/replay/state_digest.py`
- Create: `tests/replay/test_deterministic_replay.py`
- Create: `tests/state/test_state_digest.py`
- Create: `tests/fixtures/replay/mvp0/003-replay-empty-and-startup.fixture.json`

**Tests**

- `pytest tests/replay/test_deterministic_replay.py tests/state/test_state_digest.py -q`
- Replay consumes events by `event_seq`, not wall clock.
- Replay validates envelope and event-specific required fields.
- Replay never calls models, tools, network, clocks, randomness, or missing-ref fetchers.
- Missing data-plane refs become unavailable diagnostics.
- State digest excludes raw audio, raw text, secrets, raw web content, and tool credentials.

**Fixture**

- `tests/fixtures/replay/mvp0/003-replay-empty-and-startup.fixture.json`
- Includes replay manifest with `contains_raw_audio=false`, `contains_raw_trace=false`, and `contains_secrets=false`.

**Acceptance Criteria**

- Deterministic replay loads synthetic fixtures, reduces state, and emits stable digest.
- Replay output labels fixture domain and replay mode.
- No default replay path can re-run a model or tool.

**Suggested Commit Message**

- `feat: add deterministic replay core`

## 9. Slice 4: Text Ingress Through Interaction Controller

**Goal**

Implement text ingress from Access Layer through Interaction Controller to committed turn.

**Expected Files**

- Create: `src/voice_agent/access/text_ingress.py`
- Create: `src/voice_agent/interaction/controller.py`
- Create: `src/voice_agent/interaction/policy.py`
- Create: `tests/interaction/test_text_ingress.py`
- Create: `tests/replay/test_text_ingress_replay.py`
- Create: `tests/fixtures/replay/mvp0/004-text-ingress.fixture.json`

**Tests**

- `pytest tests/interaction/test_text_ingress.py tests/replay/test_text_ingress_replay.py -q`
- Text ingress emits `TEXT_INPUT_RECEIVED` before turn events.
- Controller emits `TURN_OPENED`, `TURN_INGRESS_ACCEPTED`, and `TURN_INGRESS_COMMITTED`.
- Text events have `audio_span_id=null`.
- Text ingress uses `directedness=ASSUMED_DIRECTED` and `semantic_close=ASSUMED_CLOSED`.
- Access Layer cannot route directly to Router.

**Fixture**

- `tests/fixtures/replay/mvp0/004-text-ingress.fixture.json`
- Uses synthetic or redacted text, never unredacted real user input.

**Acceptance Criteria**

- `MVP0-TEXT-INGRESS-001` passes through runtime tests and deterministic replay.
- Final `InteractionState` has `turn_phase=TURN_COMMITTED`, `last_ingress_outcome=COMMITTED`, `current_text_span_id` set, and `current_audio_span_id=null`.
- No Duplex or model path is required for text ingress.

**Suggested Commit Message**

- `feat: route text ingress through controller`

## 10. Slice 5: Audio Span and Duplex Mock Accept Path

**Goal**

Implement minimal audio ingress with audio span metadata, mock/rule Duplex speech start/end, and Interaction Controller commit.

**Expected Files**

- Create: `src/voice_agent/access/audio_ingress.py`
- Create: `src/voice_agent/duplex/mock_duplex.py`
- Modify: `src/voice_agent/interaction/controller.py`
- Create: `tests/duplex/test_mock_audio_accept.py`
- Create: `tests/replay/test_audio_ingress_replay.py`
- Create: `tests/fixtures/replay/mvp0/005-audio-ingress-accepted.fixture.json`

**Tests**

- `pytest tests/duplex/test_mock_audio_accept.py tests/replay/test_audio_ingress_replay.py -q`
- Audio span start and speech start set `turn_phase=COLLECTING_INPUT`.
- Speech end with mock accepted policy emits accepted and committed turn events.
- Audio payloads include offsets and no raw audio.
- No ASR/Thinker frame can appear before `TURN_INGRESS_COMMITTED`.
- Mock directedness/semantic_close behavior is labeled as mock/rule-based or assumed.

**Fixture**

- `tests/fixtures/replay/mvp0/005-audio-ingress-accepted.fixture.json`
- Contains only audio metadata, offsets, ids, refs, and synthetic confidence values.

**Acceptance Criteria**

- `MVP0-AUDIO-INGRESS-001` passes through runtime tests and deterministic replay.
- Audio path causally traces from span events to `TURN_INGRESS_COMMITTED`.
- Deterministic replay does not need raw audio or audio-level inference.

**Suggested Commit Message**

- `feat: add mock audio ingress path`

## 11. Slice 6: Mock Understanding and Router FAST_ONLY Skeleton

**Goal**

Emit mock ASR/Thinker frames after committed turns and produce minimal post-commit Router decisions.

**Expected Files**

- Create: `src/voice_agent/understanding/mock_asr.py`
- Create: `src/voice_agent/understanding/mock_thinker.py`
- Create: `src/voice_agent/router/router.py`
- Create: `src/voice_agent/state/task_focus_state.py`
- Create: `tests/understanding/test_mock_understanding_after_commit.py`
- Create: `tests/router/test_router_fast_only_mvp0.py`
- Create: `tests/replay/test_router_decision_replay.py`
- Create: `tests/fixtures/replay/mvp0/006-mock-understanding-router.fixture.json`

**Tests**

- `pytest tests/understanding/test_mock_understanding_after_commit.py tests/router/test_router_fast_only_mvp0.py tests/replay/test_router_decision_replay.py -q`
- Mock ASR and Thinker frames emit only after `TURN_INGRESS_COMMITTED`.
- Mock frame events carry `output_mode=mock`.
- Router emits only MVP-0 `FAST_ONLY` or `IGNORE` decisions.
- Router does not spawn SlowTask, create UserPatch, advance plan version, authorize tools, or interpret final task semantics.
- Replay verifies no Router decision appears before turn commit.

**Fixture**

- `tests/fixtures/replay/mvp0/006-mock-understanding-router.fixture.json`
- Contains synthetic mock transcript and semantic frame refs.

**Acceptance Criteria**

- Text and audio committed turns produce mock understanding events and a Router decision.
- Minimal/inert `TaskFocusState` can be replayed without introducing MVP-1 active task behavior.
- No SlowTask, UserPatch, tool, or real model code is introduced.

**Suggested Commit Message**

- `feat: add mock understanding router path`

## 12. Slice 7: Mock Talker Playback Progress and Delivery Markers

**Goal**

Implement mock Talker playback span lifecycle with progress, delivery marker, and finish event support.

**Expected Files**

- Create: `src/voice_agent/talker/mock_talker.py`
- Modify: `src/voice_agent/state/playback_state.py`
- Create: `tests/talker/test_mock_playback.py`
- Create: `tests/replay/test_playback_replay.py`
- Create: `tests/fixtures/replay/mvp0/007-playback-progress.fixture.json`

**Tests**

- `pytest tests/talker/test_mock_playback.py tests/replay/test_playback_replay.py -q`
- Playback has a unique `playback_span_id`.
- Playback progress reports `playback_offset_ms`.
- `PLAYBACK_COMMITTED` is recorded as a delivery marker only.
- Replay reconstructs latest progress, committed offsets, and final playback phase.
- Mock audio uses `audio_ref` or `tts_stream_ref`, never raw audio.

**Fixture**

- `tests/fixtures/replay/mvp0/007-playback-progress.fixture.json`
- Contains synthetic playback refs and offset metadata only.

**Acceptance Criteria**

- Mock Talker can start playback and produce progress/commit events.
- Replay preserves playback offsets.
- No real TTS adapter, provider client, or Composer coverage check is added.

**Suggested Commit Message**

- `feat: add mock playback lifecycle`

## 13. Slice 8: Barge-in Candidate to Truncate Flow

**Goal**

Implement truncate-only barge-in path from Duplex candidate to Interaction interrupt policy to Talker truncate confirmation.

**Expected Files**

- Modify: `src/voice_agent/duplex/mock_duplex.py`
- Modify: `src/voice_agent/interaction/controller.py`
- Modify: `src/voice_agent/talker/mock_talker.py`
- Modify: `src/voice_agent/state/playback_state.py`
- Create: `tests/interaction/test_barge_in_truncate.py`
- Create: `tests/replay/test_barge_in_truncate_replay.py`
- Create: `tests/slo/test_mvp0_latency_metrics.py`
- Create: `tests/fixtures/replay/mvp0/008-barge-in-truncate.fixture.json`

**Tests**

- `pytest tests/interaction/test_barge_in_truncate.py tests/replay/test_barge_in_truncate_replay.py tests/slo/test_mvp0_latency_metrics.py -q`
- Duplex emits `BARGE_IN_CANDIDATE` only with `playback_span_id`, `playback_offset_ms`, `echo_likelihood`, `vad_confidence`, and `barge_in_confidence`.
- Interaction Controller emits `INTERRUPT_CANDIDATE` and `TTS_TRUNCATE_REQUESTED`.
- `TTS_TRUNCATE_REQUESTED` carries `cutoff_playback_offset_ms` and references the interrupt candidate.
- Talker emits `TTS_TRUNCATED` with `actual_stop_offset_ms`.
- Barge-in to truncate command latency is computable from event timestamps and is `<=250ms` in the synthetic passing fixture.

**Fixture**

- `tests/fixtures/replay/mvp0/008-barge-in-truncate.fixture.json`
- Contains no raw mic audio or playback audio.

**Acceptance Criteria**

- `MVP0-BARGE-IN-TRUNCATE-001` passes through runtime tests and deterministic replay.
- Candidate-time offset, request cutoff offset, and actual stop offset remain distinct.
- Replay reconstructs `PlaybackState=TRUNCATED`.
- No pause/resume, semantic-clause resume, multi-track recovery, or model-side TTS cancellation guarantee is introduced.

**Suggested Commit Message**

- `feat: add barge in truncate flow`

## 14. Slice 9: MVP-0 Replay Fixtures and Acceptance Runner

**Goal**

Add a single acceptance runner over all MVP-0 synthetic replay fixtures and scenario assertions.

**Expected Files**

- Create: `src/voice_agent/replay/scenario_assertions.py`
- Create: `tests/acceptance/test_mvp0_acceptance_scenarios.py`
- Create: `tests/fixtures/replay/mvp0/009-local-trace-safety.fixture.json`
- Create: `tests/fixtures/replay/mvp0/manifest.index.json`
- Reuse and validate fixtures `004` through `008`.

**Tests**

- `pytest tests/acceptance/test_mvp0_acceptance_scenarios.py -q`
- Execute `MVP0-TEXT-INGRESS-001`.
- Execute `MVP0-AUDIO-INGRESS-001`.
- Execute `MVP0-BARGE-IN-TRUNCATE-001`.
- Execute `MVP0-MOCK-ADAPTER-CAPABILITY-001`.
- Execute `MVP0-LOCAL-TRACE-SAFETY-001`.
- Verify SLO labels are present and distinguish `mock`, `degraded`, and `real`.
- Fail if forbidden MVP-0 scope events or modules appear in the fixture event stream.

**Fixture**

- `tests/fixtures/replay/mvp0/manifest.index.json`
- `tests/fixtures/replay/mvp0/009-local-trace-safety.fixture.json`
- All fixtures declare replay manifest fields and safe fixture domains.

**Acceptance Criteria**

- One MVP-0 acceptance command validates fixtures, replays event streams, checks final state digests, and enforces scenario assertions.
- All five MVP-0 acceptance scenarios pass.
- Fixture safety checks pass across the full MVP-0 fixture set.
- Review confirms no MVP-1, MVP-2, or MVP-3 behavior slipped into MVP-0.

**Suggested Commit Message**

- `test: add mvp0 acceptance runner`

## 15. Replay, Fixture, and Privacy Gate

Every committed replay fixture must satisfy:

- `fixture_domain=GITHUB_ALLOWED` or another shareable-safe domain allowed by `docs/specs/replay-spec.md`.
- `generated_from=synthetic`, `redacted`, or `hand_written_minimal`.
- `contains_raw_audio=false`.
- `contains_raw_trace=false`.
- `contains_real_user_input=false`.
- `contains_secrets=false`.
- `contains_unredacted_tool_result=false`.
- `contains_large_raw_web_content=false`.
- Mock outputs use `output_mode=mock`.
- Event ids, timestamps, text, transcript refs, semantic frame refs, and audio/playback refs are invented or synthetic.
- State digest excludes raw audio, raw text, secrets, raw web content, tool credentials, request bodies, headers, cookies, and authorization data.

Replay must:

- Run in deterministic mode by default.
- Sort by `event_seq`.
- Validate envelope and event-specific required fields.
- Reconstruct reducer state without calling models, tools, networks, clocks, randomness, or missing-ref fetchers.
- Emit `REPLAY_STARTED` and `REPLAY_COMPLETED` for replay runs.
- Label replay mode, fixture domain, and SLO output mode.

Privacy gate fails the slice if:

- A fixture includes raw audio, raw debug trace, secret-like content, unredacted real user input, unredacted sensitive tool output, or large raw web content.
- A local debug path is not ignored before runtime writes to it.
- Adapter events expose provider credentials, request bodies, headers, cookies, or authorization values.
- `PLAYBACK_COMMITTED` is treated as user acknowledgement or confirmation.

## 16. Commit Message Suggestions

These suggested commits are kept as historical slice markers. Current main has already merged MVP-0 work through Slice 9; use future commit messages for MVP-1+ work instead.

| Slice | Suggested commit |
| --- | --- |
| Slice 0 | `chore: add mvp0 repo safety skeleton` |
| Slice 1 | `feat: add event journal envelope` |
| Slice 2 | `feat: record mock adapter capabilities` |
| Slice 3 | `feat: add deterministic replay core` |
| Slice 4 | `feat: route text ingress through controller` |
| Slice 5 | `feat: add mock audio ingress path` |
| Slice 6 | `feat: add mock understanding router path` |
| Slice 7 | `feat: add mock playback lifecycle` |
| Slice 8 | `feat: add barge in truncate flow` |
| Slice 9 | `test: add mvp0 acceptance runner` |

Before each future commit:

- Run slice-local tests.
- Run fixture safety tests.
- Run the relevant replay or acceptance check.
- Run `git diff --check`.
- Review changed files for raw/local artifacts and accidental scope expansion.

## 17. Stop and Add or Update an ADR When

Stop implementation and update accepted ADRs before proceeding if a change would:

- Introduce any MVP-relevant event name not registered by ADR-002 and `docs/specs/event-registry.md`.
- Treat non-canonical names such as `SEMANTIC_COMMITMENT_CREATED`, `SPOKEN_PLAN_CREATED`, or `STALE_TOOL_RESULT_RECORDED` as journal event names instead of canonical mapped events.
- Change ownership of turn ingress, Interaction Controller, Router, SlowTask, Tool Executor, Composer, Event Journal, Replay, or Adapter boundaries.
- Let Access Layer route directly to Router, or let ASR/Thinker decide first ingress commit.
- Add SlowTask, UserPatch, plan_version, stale ToolResult policy, SemanticCommitment, Composer coverage, tools, frontend UI patching, webSearch, or real model integration to MVP-0.
- Add real external side effects, production privacy, production auth, booking, payment, deletion, external communication, or real tool execution.
- Add multi active SlowTask, pause/resume SlowTask, pause/resume TTS, semantic-clause resume, or multi-track playback recovery.
- Depend on provider-specific APIs outside adapters.
- Add native/sidecar components that bypass adapters, Tool Executor, Event Journal, Interaction Controller, or canonical event names.
- Depend on Python threads or async scheduling order to advance critical state.
- Require raw audio, raw traces, secrets, or unredacted real input in committed fixtures.

## 18. MVP-0 Exit Criteria

MVP-0 is accepted only when:

- `MVP0-TEXT-INGRESS-001` passes.
- `MVP0-AUDIO-INGRESS-001` passes.
- `MVP0-BARGE-IN-TRUNCATE-001` passes.
- `MVP0-MOCK-ADAPTER-CAPABILITY-001` passes.
- `MVP0-LOCAL-TRACE-SAFETY-001` passes.
- Deterministic replay reconstructs MVP-0 states without model/tool/network reruns.
- Capability snapshot and mock outputs are labeled `mock`.
- Barge-in to truncate latency is computable from events and passing synthetic fixture is `<=250ms`.
- Local trace safety assertions pass.
- No ADR, Architecture Book, or frozen spec changes are needed to explain the implementation.

## 19. Non-Blocking Plan Decisions

- MVP-0 implementation should prioritize CLI/local replay and acceptance tests over a frontend demo, because frontend requirement is an ADR-012 open question and not required for the walking skeleton.
- Initial event journal can be in-memory for runtime tests. Persistence/export should remain optional and local-only until trace storage format is explicitly chosen.
- Playback progress frequency can use a deterministic test-friendly interval first; do not claim product-level latency or audio fidelity from mock timing.
- Directedness and semantic_close should use assumed or mock/rule labels in MVP-0; do not present them as real model capability.

## 20. Self-Check

| Check | Result |
| --- | --- |
| Does this plan broaden MVP-0 scope? | No. SlowTask, tools, Composer checks, real adapters, frontend UI patching, pause/resume, and real side effects are explicitly forbidden. |
| Does this plan bypass adapters? | No. All model-like outputs are mock adapter outputs with capability snapshots and `output_mode=mock`; no direct provider calls are allowed. |
| Does this plan omit replay/eval gates? | No. Every slice names at least one replay fixture or fixture/acceptance gate, and Slice 9 runs all MVP-0 scenarios. |
| Does this plan risk raw artifacts? | Controlled. The plan requires `.gitignore` coverage, fixture safety tests, synthetic/redacted/minimal fixtures, and no raw audio/trace/secrets/unredacted input in GitHub-allowed content. |
| Does this plan change ADRs or Architecture Book? | No. It only maps accepted ADR/spec requirements into future implementation order. |
| Does this plan create runtime code now? | Historical answer: no. Current repository state: MVP-0 runtime code now exists because the plan has been executed. |
