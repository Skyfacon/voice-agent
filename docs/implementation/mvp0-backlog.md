# MVP-0 Implementation Backlog

Source contracts:

- `docs/architecture-book.md`
- `docs/adr-traceability-matrix.md`
- `docs/specs/event-registry.md`
- `docs/specs/state-reducers.md`
- `docs/specs/replay-spec.md`
- `docs/specs/model-adapter-capabilities.md`
- `docs/specs/mvp0-acceptance-scenarios.md`
- Frozen ADR Baseline v0.4 and `AGENTS.md`

This backlog is scoped only to MVP-0: event-driven live loop skeleton, interrupt/truncate, trace/replay, module boundary, and mock capability labeling.

## MVP-0 Forbidden Scope

Do not implement in MVP-0:

- real ASR
- real TTS
- real Qwen3-Omni
- real GLM
- real external tools
- real side-effect tools
- complete SlowTask
- complete UserPatch plan_version flow
- Composer coverage check
- pause/resume TTS
- complete semantic_close or assistant-directedness

All fixtures in this backlog must be synthetic, redacted, or minimal. Raw audio, raw debug traces, local replay cache, secrets, unredacted real user input, and large raw web content must not be committed.

## Slice 0: Repo Safety and Runtime Skeleton

**Goal:** Establish the minimal implementation skeleton and repository safety guardrails required before any MVP-0 runtime artifacts can be created.

**Non-goal:** No runtime event processing, no model calls, no audio handling, no frontend, no SlowTask, no tools.

**Expected files:**

- Modify: `.gitignore` only if required exclusions are missing.
- Create: `src/voice_agent/__init__.py`
- Create: `src/voice_agent/config/runtime_config.py`
- Create: `tests/conftest.py`
- Create: `tests/fixtures/replay/mvp0/README.md`
- Create: `tests/replay/test_fixture_safety.py`

**Events touched:** None emitted by runtime yet. This slice only prepares fixture and trace boundaries.

**State objects touched:** `TracePrivacyState` contract only, as test expectation.

**Tests:**

- Verify `.gitignore` or equivalent repo exclusion covers `diagnostics/`, `traces/`, `replays/local/`, `audio/raw/`, `.env`, and `.env.*`.
- Verify committed fixture directory is `tests/fixtures/replay/mvp0/`, not `replays/local/`.
- Verify fixture safety test rejects raw audio refs, raw trace payloads, secret-like fields, and unredacted real user text.

**Replay fixture:** `tests/fixtures/replay/mvp0/000-empty-session.fixture.json`

**Privacy assertions:**

- Fixture contains no raw audio.
- Fixture contains no raw trace.
- Fixture contains no secrets or credential-like fields.
- Fixture contains no unredacted real user input.

**Acceptance criteria:**

- A fresh checkout has safe local artifact exclusions before any runtime writes trace/audio/replay-cache directories.
- Synthetic fixture location is separate from local replay cache.
- Test harness can run fixture-safety checks without starting a service.

**Done when:**

- Safety tests pass.
- No runtime code writes local traces, raw audio, or replay cache outside ignored paths.
- Review confirms no ADR or Architecture Book files were modified.

## Slice 1: Event Envelope and Append-Only Journal

**Goal:** Implement the MVP-0 event envelope, per-session `event_seq`, append-only in-memory journal, and event validation for required MVP-0 fields.

**Non-goal:** No reducers, no replay runner, no persistence backend beyond optional local debug export, no global blocking event bus.

**Expected files:**

- Create: `src/voice_agent/events/envelope.py`
- Create: `src/voice_agent/events/registry.py`
- Create: `src/voice_agent/events/journal.py`
- Create: `src/voice_agent/privacy/redaction.py`
- Create: `tests/events/test_event_envelope.py`
- Create: `tests/events/test_event_journal.py`

**Events touched:**

- `SESSION_STARTED`
- `ADAPTER_CAPABILITY_SNAPSHOT_RECORDED`
- `TEXT_INPUT_RECEIVED`
- `AUDIO_SPAN_STARTED`
- `AUDIO_SPAN_ENDED`
- `SPEECH_START_DETECTED`
- `SPEECH_END_DETECTED`
- `TURN_OPENED`
- `TURN_INGRESS_ACCEPTED`
- `TURN_INGRESS_COMMITTED`
- `ROUTER_DECISION_EMITTED`
- `PLAYBACK_SPAN_STARTED`
- `PLAYBACK_PROGRESS`
- `PLAYBACK_COMMITTED`
- `BARGE_IN_CANDIDATE`
- `INTERRUPT_CANDIDATE`
- `TTS_TRUNCATE_REQUESTED`
- `TTS_TRUNCATED`
- `REPLAY_STARTED`
- `REPLAY_COMPLETED`
- `TRACE_WRITE_DEGRADED`
- `TRACE_SECRET_REDACTION_APPLIED`
- `TRACE_WRITE_BLOCKED_SECRET_DETECTED`

**State objects touched:** None reduced yet; event envelope fields prepare later reducers.

**Tests:**

- Event creation requires `event_id`, `event_seq`, `event_schema_version`, `session_id`, `conversation_id`, `source_module`, `created_monotonic_ms`, `created_wall_clock_ms`, `caused_by_event_id` except root, and `trace_redaction_level`.
- `event_seq` is strictly increasing per session.
- Journal append is append-only and does not reorder by wall clock.
- Secret-like payloads are redacted or blocked before append.

**Replay fixture:** `tests/fixtures/replay/mvp0/001-event-envelope-session-start.fixture.json`

**Privacy assertions:**

- No event payload may store API keys, tokens, cookies, authorization headers, credentials, or session secrets.
- Raw text/audio must be represented by refs or redacted fields.

**Acceptance criteria:**

- MVP-0 event names are accepted only if registered in `docs/specs/event-registry.md`.
- Unknown MVP-relevant event names fail validation.
- Root and non-root causal-link rules are enforced.

**Done when:**

- Event envelope and journal tests pass.
- Fixture validates through the event validator.
- No external model/tool/network call exists in this slice.

## Slice 2: Capability Snapshot and Mock Adapter Contracts

**Goal:** Add startup capability snapshot support and honest mock adapter capability declarations for MVP-0.

**Non-goal:** No provider endpoint integration, no real ASR/TTS/Thinker, no HTTP/WebSocket healthchecks beyond mock status, no real model output validation.

**Expected files:**

- Create: `src/voice_agent/adapters/capabilities.py`
- Create: `src/voice_agent/adapters/mock_adapters.py`
- Create: `src/voice_agent/runtime/session.py`
- Create: `tests/adapters/test_mock_capability_snapshot.py`
- Create: `tests/runtime/test_session_startup.py`

**Events touched:**

- `SESSION_STARTED`
- `ADAPTER_CAPABILITY_SNAPSHOT_RECORDED`
- `MOCK_ASR_FRAME_EMITTED`
- `MOCK_THINKER_FRAME_EMITTED`
- `ADAPTER_OUTPUT_DEGRADED` only for explicit degraded mock scenarios.

**State objects touched:**

- `AdapterHealthState`
- `TracePrivacyState` for credential-safe endpoint/config refs.

**Tests:**

- Session startup emits `SESSION_STARTED` followed by `ADAPTER_CAPABILITY_SNAPSHOT_RECORDED`.
- Mock ASR, mock Thinker, and mock TTS/Talker matrices declare all required capability fields.
- Mock outputs are labeled `output_mode=mock`.
- Unsupported capabilities are explicit and not silently assumed.
- Endpoint/config refs do not contain credentials.

**Replay fixture:** `tests/fixtures/replay/mvp0/002-mock-capability-snapshot.fixture.json`

**Privacy assertions:**

- Capability snapshot contains no provider credentials.
- Mock profiles use synthetic refs only.

**Acceptance criteria:**

- `MVP0-MOCK-ADAPTER-CAPABILITY-001` can be executed against the runtime.
- Replay can reconstruct adapter modes from snapshot without probing adapters.

**Done when:**

- Capability snapshot tests pass.
- Fixture validates and replays into expected `AdapterHealthState`.
- No real adapter/provider code exists.

## Slice 3: Deterministic State Reducers and Replay Core

**Goal:** Implement deterministic replay over recorded events for MVP-0 state objects.

**Non-goal:** No re-eval replay, no audio-level replay, no model/tool reruns, no SlowTask reducer beyond inert/empty state placeholder if needed by digest.

**Expected files:**

- Create: `src/voice_agent/state/interaction_state.py`
- Create: `src/voice_agent/state/playback_state.py`
- Create: `src/voice_agent/state/adapter_health_state.py`
- Create: `src/voice_agent/state/trace_privacy_state.py`
- Create: `src/voice_agent/replay/manifest.py`
- Create: `src/voice_agent/replay/runner.py`
- Create: `src/voice_agent/replay/state_digest.py`
- Create: `tests/replay/test_deterministic_replay.py`
- Create: `tests/state/test_state_digest.py`

**Events touched:**

- `REPLAY_STARTED`
- `REPLAY_COMPLETED`
- All MVP-0 events already accepted by the journal validator.

**State objects touched:**

- `InteractionState`
- `PlaybackState`
- `AdapterHealthState`
- `TracePrivacyState`

**Tests:**

- Replay sorts by `event_seq`, not wall clock.
- Replay never calls models, tools, network, clocks, or randomness.
- Missing data-plane refs are preserved as unavailable, not fetched.
- State digest excludes raw audio, raw text, secrets, raw web content, and raw tool credential payloads.

**Replay fixture:** `tests/fixtures/replay/mvp0/003-replay-empty-and-startup.fixture.json`

**Privacy assertions:**

- ReplayManifest for shareable fixtures sets `contains_raw_audio=false`, `contains_raw_trace=false`, `contains_secrets=false`.
- Digest does not include raw sensitive payloads.

**Acceptance criteria:**

- Deterministic replay can load a synthetic fixture, validate events, reduce states, and emit a stable state digest.
- Replay output labels mode and fixture domain.

**Done when:**

- Reducer and replay tests pass.
- No default replay path can re-run a model or tool.

## Slice 4: Text Ingress Through Interaction Controller

**Goal:** Implement text ingress from Access Layer through Interaction Controller into a committed turn.

**Non-goal:** No Duplex path, no synthetic audio span, no real model, no SlowTask, no tools.

**Expected files:**

- Create: `src/voice_agent/access/text_ingress.py`
- Create: `src/voice_agent/interaction/controller.py`
- Create: `src/voice_agent/interaction/policy.py`
- Create: `tests/interaction/test_text_ingress.py`
- Create: `tests/replay/test_text_ingress_replay.py`

**Events touched:**

- `TEXT_INPUT_RECEIVED`
- `TURN_OPENED`
- `TURN_INGRESS_ACCEPTED`
- `TURN_INGRESS_COMMITTED`
- `ROUTER_DECISION_EMITTED` if Slice 6 router stub is already present; otherwise deferred to Slice 6.

**State objects touched:**

- `InteractionState`

**Tests:**

- Text ingress emits `TEXT_INPUT_RECEIVED` before any turn event.
- Interaction Controller emits `TURN_OPENED`, `TURN_INGRESS_ACCEPTED`, and `TURN_INGRESS_COMMITTED`.
- Text ingress has `audio_span_id=null`.
- Text ingress uses `directedness=ASSUMED_DIRECTED` and `semantic_close=ASSUMED_CLOSED`.
- Access Layer cannot route directly to Router.

**Replay fixture:** `tests/fixtures/replay/mvp0/004-text-ingress.fixture.json`

**Privacy assertions:**

- Fixture uses `redacted_text` or `text_ref`, not unredacted real user input.
- No raw audio field appears in text fixture.

**Acceptance criteria:**

- `MVP0-TEXT-INGRESS-001` passes through runtime tests and deterministic replay.
- `InteractionState` final state has `turn_phase=TURN_COMMITTED`, `last_ingress_outcome=COMMITTED`, and `current_audio_span_id=null`.

**Done when:**

- Text ingress tests pass.
- Text replay fixture produces expected digest.
- No Duplex or model path is required for text ingress.

## Slice 5: Audio Span and Duplex Mock Accept Path

**Goal:** Implement the minimal audio ingress path with mock/rule Duplex speech start/end and Interaction Controller commit.

**Non-goal:** No raw audio processing, no real VAD, no real semantic_close, no real assistant-directedness, no real ASR/Thinker.

**Expected files:**

- Create: `src/voice_agent/access/audio_ingress.py`
- Create: `src/voice_agent/duplex/mock_duplex.py`
- Modify: `src/voice_agent/interaction/controller.py`
- Create: `tests/duplex/test_mock_audio_accept.py`
- Create: `tests/replay/test_audio_ingress_replay.py`

**Events touched:**

- `AUDIO_SPAN_STARTED`
- `AUDIO_SPAN_ENDED`
- `SPEECH_START_DETECTED`
- `SPEECH_END_DETECTED`
- `TURN_OPENED`
- `TURN_INGRESS_ACCEPTED`
- `TURN_INGRESS_COMMITTED`

**State objects touched:**

- `InteractionState`

**Tests:**

- Audio span start plus speech start sets `turn_phase=COLLECTING_INPUT`.
- Speech end with mock accepted policy emits accepted and committed turn events.
- Audio event payloads include offsets and no raw audio.
- No ASR/Thinker frame is emitted before `TURN_INGRESS_COMMITTED`.

**Replay fixture:** `tests/fixtures/replay/mvp0/005-audio-ingress-accepted.fixture.json`

**Privacy assertions:**

- Fixture contains only audio metadata and refs.
- Raw audio is absent and not required for deterministic replay.

**Acceptance criteria:**

- `MVP0-AUDIO-INGRESS-001` passes through runtime tests and deterministic replay.
- Audio path is causally traceable from audio span events to `TURN_INGRESS_COMMITTED`.

**Done when:**

- Audio ingress tests pass.
- Replay reconstructs expected InteractionState.
- Mock Duplex is clearly labeled or configured as mock/rule behavior.

## Slice 6: Mock Understanding and Router FAST_ONLY Skeleton

**Goal:** Add post-commit mock ASR/Thinker frame emission and a minimal Router decision after committed turns.

**Non-goal:** No real ASR, real Thinker, SlowTask spawn, UserPatch, plan_version, evidence fusion, or tool routing.

**Expected files:**

- Create: `src/voice_agent/understanding/mock_asr.py`
- Create: `src/voice_agent/understanding/mock_thinker.py`
- Create: `src/voice_agent/router/router.py`
- Create: `src/voice_agent/state/task_focus_state.py`
- Create: `tests/understanding/test_mock_understanding_after_commit.py`
- Create: `tests/router/test_router_fast_only_mvp0.py`
- Create: `tests/replay/test_router_decision_replay.py`

**Events touched:**

- `TURN_INGRESS_COMMITTED`
- `MOCK_ASR_FRAME_EMITTED`
- `MOCK_THINKER_FRAME_EMITTED`
- `ROUTER_DECISION_EMITTED`

**State objects touched:**

- `AdapterHealthState`
- `TaskFocusState` minimal/inert MVP-0 state
- `InteractionState` as causal source only

**Tests:**

- Mock ASR/Thinker frames emit only after `TURN_INGRESS_COMMITTED`.
- Mock frame events carry `output_mode=mock`.
- Router emits only MVP router decisions and defaults to `FAST_ONLY` or `IGNORE` for MVP-0 synthetic inputs.
- Router does not spawn SlowTask, create UserPatch, or use plan_version in MVP-0.

**Replay fixture:** `tests/fixtures/replay/mvp0/006-mock-understanding-router.fixture.json`

**Privacy assertions:**

- Mock transcript and semantic frame refs use synthetic content.
- No model prompt, provider response, or secret-like adapter metadata is stored.

**Acceptance criteria:**

- Text and audio committed turns produce mock understanding events and a Router decision.
- Replay can verify no Router decision appears before turn commit.

**Done when:**

- Understanding and Router tests pass.
- Replay fixture validates expected event ordering.
- No SlowTask/UserPatch/tool code is introduced.

## Slice 7: Mock Talker Playback Progress and Delivery Markers

**Goal:** Implement mock Talker playback span lifecycle with progress and playback commitment markers.

**Non-goal:** No real TTS, no audio synthesis requirement, no Composer coverage check, no progress truthfulness check.

**Expected files:**

- Create: `src/voice_agent/talker/mock_talker.py`
- Modify: `src/voice_agent/state/playback_state.py`
- Create: `tests/talker/test_mock_playback.py`
- Create: `tests/replay/test_playback_replay.py`

**Events touched:**

- `PLAYBACK_SPAN_STARTED`
- `PLAYBACK_PROGRESS`
- `PLAYBACK_COMMITTED`
- `PLAYBACK_FINISHED`

**State objects touched:**

- `PlaybackState`
- `InteractionState` playback phase only if controller observes playback events.

**Tests:**

- Playback has unique `playback_span_id`.
- Playback progress reports `playback_offset_ms`.
- `PLAYBACK_COMMITTED` is recorded as a delivery marker only.
- Replay reconstructs latest progress and committed offsets.

**Replay fixture:** `tests/fixtures/replay/mvp0/007-playback-progress.fixture.json`

**Privacy assertions:**

- Mock audio uses `audio_ref` or `tts_stream_ref`, not raw audio.
- Fixture contains no real TTS output.

**Acceptance criteria:**

- Mock Talker can start playback and produce progress/commit events.
- Replay preserves playback offsets and does not treat commitment as user confirmation.

**Done when:**

- Playback tests pass.
- Playback fixture produces expected `PlaybackState`.
- No real TTS adapter/provider is added.

## Slice 8: Barge-in Candidate to Truncate Flow

**Goal:** Implement truncate-only barge-in path from Duplex candidate through Interaction interrupt policy to Talker truncate confirmation.

**Non-goal:** No pause/resume, no semantic-clause resume, no multi-track recovery, no model-side TTS cancellation guarantee, no full duplex semantic model.

**Expected files:**

- Modify: `src/voice_agent/duplex/mock_duplex.py`
- Modify: `src/voice_agent/interaction/controller.py`
- Modify: `src/voice_agent/talker/mock_talker.py`
- Modify: `src/voice_agent/state/playback_state.py`
- Create: `tests/interaction/test_barge_in_truncate.py`
- Create: `tests/replay/test_barge_in_truncate_replay.py`
- Create: `tests/slo/test_mvp0_latency_metrics.py`

**Events touched:**

- `PLAYBACK_PROGRESS`
- `PLAYBACK_COMMITTED`
- `AUDIO_SPAN_STARTED`
- `SPEECH_START_DETECTED`
- `BARGE_IN_CANDIDATE`
- `INTERRUPT_CANDIDATE`
- `TTS_TRUNCATE_REQUESTED`
- `TTS_TRUNCATED`

**State objects touched:**

- `InteractionState`
- `PlaybackState`

**Tests:**

- Duplex emits `BARGE_IN_CANDIDATE` only with `playback_span_id`, `playback_offset_ms`, `echo_likelihood`, `vad_confidence`, and `barge_in_confidence`.
- Interaction Controller emits `INTERRUPT_CANDIDATE` and `TTS_TRUNCATE_REQUESTED`.
- `TTS_TRUNCATE_REQUESTED` includes `cutoff_playback_offset_ms` and references interrupt candidate.
- Talker emits `TTS_TRUNCATED` with `actual_stop_offset_ms`.
- Barge-in to truncate command latency is computable and <= 250ms in synthetic passing fixture.

**Replay fixture:** `tests/fixtures/replay/mvp0/008-barge-in-truncate.fixture.json`

**Privacy assertions:**

- No raw mic audio or playback audio in fixture.
- Echo and confidence values are metadata only.

**Acceptance criteria:**

- `MVP0-BARGE-IN-TRUNCATE-001` passes through runtime tests and deterministic replay.
- Candidate-time offset, request cutoff offset, and actual stop offset remain distinct.

**Done when:**

- Barge-in/truncate tests pass.
- Replay fixture reconstructs `PlaybackState=TRUNCATED`.
- No pause/resume behavior is introduced.

## Slice 9: MVP-0 Replay Fixtures and Acceptance Runner

**Goal:** Add a single acceptance runner over all MVP-0 synthetic replay fixtures and scenario assertions.

**Non-goal:** No real service startup requirement, no browser/frontend requirement, no real audio fixture, no eval of model quality.

**Expected files:**

- Create: `src/voice_agent/replay/scenario_assertions.py`
- Create: `tests/acceptance/test_mvp0_acceptance_scenarios.py`
- Create: `tests/fixtures/replay/mvp0/004-text-ingress.fixture.json`
- Create: `tests/fixtures/replay/mvp0/005-audio-ingress-accepted.fixture.json`
- Create: `tests/fixtures/replay/mvp0/006-mock-understanding-router.fixture.json`
- Create: `tests/fixtures/replay/mvp0/007-playback-progress.fixture.json`
- Create: `tests/fixtures/replay/mvp0/008-barge-in-truncate.fixture.json`
- Create: `tests/fixtures/replay/mvp0/009-local-trace-safety.fixture.json`

**Events touched:**

- All MVP-0 required events exercised by the five acceptance scenarios.
- `REPLAY_STARTED`
- `REPLAY_COMPLETED`
- Optional trace safety events when privacy fixture exercises redaction/blocking.

**State objects touched:**

- `InteractionState`
- `PlaybackState`
- `AdapterHealthState`
- `TracePrivacyState`
- Minimal/inert `TaskFocusState` only where Router replay needs it.

**Tests:**

- Execute `MVP0-TEXT-INGRESS-001`.
- Execute `MVP0-AUDIO-INGRESS-001`.
- Execute `MVP0-BARGE-IN-TRUNCATE-001`.
- Execute `MVP0-MOCK-ADAPTER-CAPABILITY-001`.
- Execute `MVP0-LOCAL-TRACE-SAFETY-001`.
- Verify SLO labels are mock/degraded/real where calculated.

**Replay fixture:** `tests/fixtures/replay/mvp0/manifest.index.json`

**Privacy assertions:**

- All committed fixtures are synthetic/redacted/minimal.
- No fixture contains raw audio, raw debug trace, secrets, unredacted real user input, unredacted sensitive tool results, or large raw web content.
- Local debug paths remain ignored and separate from committed fixtures.

**Acceptance criteria:**

- A single MVP-0 acceptance command validates fixtures, replays event streams, and checks final state digests/assertions.
- Acceptance runner fails if forbidden MVP-0 scope events or modules appear in the event stream.

**Done when:**

- All five MVP-0 acceptance scenarios pass.
- Fixture safety checks pass.
- Review confirms no MVP-1/MVP-2/MVP-3 scope slipped into MVP-0.

## MVP-0 Exit Criteria

MVP-0 is complete only when:

- Text ingress emits `TEXT_INPUT_RECEIVED` -> `TURN_OPENED` -> `TURN_INGRESS_ACCEPTED` -> `TURN_INGRESS_COMMITTED`.
- Audio ingress emits audio span and mock Duplex events before turn commit.
- Mock ASR/Thinker emit only after `TURN_INGRESS_COMMITTED`.
- Router emits post-commit decision only.
- Mock Talker emits playback progress and delivery markers.
- Barge-in path emits `BARGE_IN_CANDIDATE` -> `INTERRUPT_CANDIDATE` -> `TTS_TRUNCATE_REQUESTED` -> `TTS_TRUNCATED`.
- Deterministic replay reconstructs MVP-0 states without re-running models or tools.
- Capability snapshot and all mock outputs are labeled mock.
- Local trace safety assertions pass.
- No ADR, Architecture Book, or frozen spec changes are required to explain the implementation.
