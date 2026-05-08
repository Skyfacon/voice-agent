# MVP-0 实施 Backlog

本文档只覆盖 MVP-0：event-driven live loop skeleton、interrupt/truncate、trace/replay、module boundary、mock capability labeling。

事实来源 / Source contracts:

- `docs/architecture-book.md`
- `docs/adr-traceability-matrix.md`
- `docs/specs/event-registry.md`
- `docs/specs/state-reducers.md`
- `docs/specs/replay-spec.md`
- `docs/specs/model-adapter-capabilities.md`
- `docs/specs/mvp0-acceptance-scenarios.md`
- Frozen ADR Baseline v0.4
- `AGENTS.md`

## MVP-0 禁止范围

MVP-0 不得实现：

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
- complete semantic_close
- complete assistant-directedness

本 backlog 中所有 fixtures 都必须是 synthetic、redacted 或 minimal。raw audio、raw debug traces、local replay cache、secrets、unredacted real user input、large raw web content 不得提交。

## Slice 0: Repo Safety and Runtime Skeleton

**目标**

建立最小 implementation skeleton 和 repo safety guardrails，确保任何 MVP-0 runtime artifact 出现前，trace/audio/replay/cache 边界已经安全。

**非目标**

不做 runtime event processing、model calls、audio handling、frontend、SlowTask、tools。

**预计文件**

- Modify: `.gitignore` only if required exclusions are missing.
- Create later: `src/voice_agent/__init__.py`
- Create later: `src/voice_agent/config/runtime_config.py`
- Create later: `tests/conftest.py`
- Create later: `tests/fixtures/replay/mvp0/README.md`
- Create later: `tests/replay/test_fixture_safety.py`

**Events touched**

无 runtime events。本 slice 只准备 fixture 和 trace boundaries。

**State objects touched**

- `TracePrivacyState` contract only, as test expectation.

**Tests**

- `.gitignore` 或等价 repo exclusion mechanism 覆盖 `diagnostics/`, `traces/`, `replays/local/`, `audio/raw/`, `.env`, `.env.*`。
- committed fixture directory 是 `tests/fixtures/replay/mvp0/`，不是 `replays/local/`。
- fixture safety test 拒绝 raw audio refs、raw trace payloads、secret-like fields、unredacted real user text。

**Replay fixture**

- `tests/fixtures/replay/mvp0/000-empty-session.fixture.json`

**Privacy assertions**

- fixture 不包含 raw audio。
- fixture 不包含 raw trace。
- fixture 不包含 secrets 或 credential-like fields。
- fixture 不包含 unredacted real user input。

**Acceptance criteria**

- fresh checkout 在任何 runtime 写 trace/audio/replay-cache directories 之前，已经有安全的 local artifact exclusions。
- synthetic fixture location 与 local replay cache 分离。
- test harness 可以在不启动 service 的情况下执行 fixture-safety checks。

**Done when**

- Safety tests pass。
- 不存在 runtime code 写 local traces、raw audio、replay cache 到非 ignored paths。
- review 确认没有修改 ADR 或 Architecture Book 来解释实现。

## Slice 1: Event Envelope and Append-Only Journal

**目标**

实现 MVP-0 event envelope、per-session `event_seq`、append-only in-memory journal、MVP-0 required fields validation。

**非目标**

不做 reducers、replay runner、persistence backend beyond optional local debug export、global blocking event bus。

**预计文件**

- Create later: `src/voice_agent/events/envelope.py`
- Create later: `src/voice_agent/events/registry.py`
- Create later: `src/voice_agent/events/journal.py`
- Create later: `src/voice_agent/privacy/redaction.py`
- Create later: `tests/events/test_event_envelope.py`
- Create later: `tests/events/test_event_journal.py`

**Events touched**

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

**State objects touched**

无 reduced state；event envelope fields 为后续 reducers 做准备。

**Tests**

- Event creation requires `event_id`, `event_seq`, `event_schema_version`, `session_id`, `conversation_id`, `source_module`, `created_monotonic_ms`, `created_wall_clock_ms`, `caused_by_event_id` except root, `trace_redaction_level`。
- `event_seq` strictly increasing per session。
- Journal append-only，不按 wall clock reorder。
- Secret-like payloads 在 append 前 redacted or blocked。

**Replay fixture**

- `tests/fixtures/replay/mvp0/001-event-envelope-session-start.fixture.json`

**Privacy assertions**

- Event payload 不得存储 API keys、tokens、cookies、authorization headers、credentials、session secrets。
- Raw text/audio 必须用 refs 或 redacted fields 表达。

**Acceptance criteria**

- MVP-0 event names only accepted if registered in `docs/specs/event-registry.md`。
- Unknown MVP-relevant event names fail validation。
- Root 和 non-root causal-link rules 被 enforcement。

**Done when**

- Event envelope / journal tests pass。
- fixture validates through event validator。
- 本 slice 不存在 external model/tool/network call。

## Slice 2: Capability Snapshot and Mock Adapter Contracts

**目标**

增加 startup capability snapshot support 和 MVP-0 mock adapter capability declarations。

**非目标**

不做 provider endpoint integration、real ASR/TTS/Thinker、HTTP/WebSocket healthchecks beyond mock status、real model output validation。

**预计文件**

- Create later: `src/voice_agent/adapters/capabilities.py`
- Create later: `src/voice_agent/adapters/mock_adapters.py`
- Create later: `src/voice_agent/runtime/session.py`
- Create later: `tests/adapters/test_mock_capability_snapshot.py`
- Create later: `tests/runtime/test_session_startup.py`

**Events touched**

- `SESSION_STARTED`
- `ADAPTER_CAPABILITY_SNAPSHOT_RECORDED`
- `MOCK_ASR_FRAME_EMITTED`
- `MOCK_THINKER_FRAME_EMITTED`
- `ADAPTER_OUTPUT_DEGRADED` only for explicit degraded mock scenarios.

**State objects touched**

- `AdapterHealthState`
- `TracePrivacyState` for credential-safe endpoint/config refs.

**Tests**

- Session startup emits `SESSION_STARTED` followed by `ADAPTER_CAPABILITY_SNAPSHOT_RECORDED`。
- Mock ASR、mock Thinker、mock TTS/Talker matrices declare all required capability fields。
- Mock outputs 标记 `output_mode=mock`。
- Unsupported capabilities are explicit and not silently assumed。
- endpoint/config refs 不包含 credentials。

**Replay fixture**

- `tests/fixtures/replay/mvp0/002-mock-capability-snapshot.fixture.json`

**Privacy assertions**

- Capability snapshot 不包含 provider credentials。
- Mock profiles 只使用 synthetic refs。

**Acceptance criteria**

- `MVP0-MOCK-ADAPTER-CAPABILITY-001` can be executed against runtime。
- Replay 可以从 snapshot reconstruct adapter modes，不 probing adapters。

**Done when**

- Capability snapshot tests pass。
- Fixture validates and replays into expected `AdapterHealthState`。
- 不存在 real adapter/provider code。

## Slice 3: Deterministic State Reducers and Replay Core

**目标**

实现 MVP-0 deterministic replay over recorded events。

**非目标**

不做 re-eval replay、audio-level replay、model/tool reruns、SlowTask reducer beyond inert/empty state placeholder if needed by digest。

**预计文件**

- Create later: `src/voice_agent/state/interaction_state.py`
- Create later: `src/voice_agent/state/playback_state.py`
- Create later: `src/voice_agent/state/adapter_health_state.py`
- Create later: `src/voice_agent/state/trace_privacy_state.py`
- Create later: `src/voice_agent/replay/manifest.py`
- Create later: `src/voice_agent/replay/runner.py`
- Create later: `src/voice_agent/replay/state_digest.py`
- Create later: `tests/replay/test_deterministic_replay.py`
- Create later: `tests/state/test_state_digest.py`

**Events touched**

- `REPLAY_STARTED`
- `REPLAY_COMPLETED`
- all MVP-0 events already accepted by journal validator.

**State objects touched**

- `InteractionState`
- `PlaybackState`
- `AdapterHealthState`
- `TracePrivacyState`

**Tests**

- Replay sorts by `event_seq`, not wall clock。
- Replay never calls models、tools、network、clocks、randomness。
- Missing data-plane refs preserved as unavailable，不 fetch。
- State digest excludes raw audio、raw text、secrets、raw web content、raw tool credential payloads。

**Replay fixture**

- `tests/fixtures/replay/mvp0/003-replay-empty-and-startup.fixture.json`

**Privacy assertions**

- ReplayManifest for shareable fixtures sets `contains_raw_audio=false`, `contains_raw_trace=false`, `contains_secrets=false`。
- Digest 不包含 raw sensitive payloads。

**Acceptance criteria**

- Deterministic replay 可以加载 synthetic fixture、validate events、reduce states、emit stable state digest。
- Replay output labels mode and fixture domain。

**Done when**

- Reducer/replay tests pass。
- No default replay path can re-run a model or tool。

## Slice 4: Text Ingress Through Interaction Controller

**目标**

实现 text ingress 从 Access Layer 经 Interaction Controller 到 committed turn。

**非目标**

不做 Duplex path、synthetic audio span、real model、SlowTask、tools。

**预计文件**

- Create later: `src/voice_agent/access/text_ingress.py`
- Create later: `src/voice_agent/interaction/controller.py`
- Create later: `src/voice_agent/interaction/policy.py`
- Create later: `tests/interaction/test_text_ingress.py`
- Create later: `tests/replay/test_text_ingress_replay.py`

**Events touched**

- `TEXT_INPUT_RECEIVED`
- `TURN_OPENED`
- `TURN_INGRESS_ACCEPTED`
- `TURN_INGRESS_COMMITTED`
- `ROUTER_DECISION_EMITTED` if Slice 6 router stub is already present; otherwise deferred to Slice 6.

**State objects touched**

- `InteractionState`

**Tests**

- Text ingress emits `TEXT_INPUT_RECEIVED` before any turn event。
- Interaction Controller emits `TURN_OPENED`, `TURN_INGRESS_ACCEPTED`, `TURN_INGRESS_COMMITTED`。
- Text ingress has `audio_span_id=null`。
- Text ingress uses `directedness=ASSUMED_DIRECTED` and `semantic_close=ASSUMED_CLOSED`。
- Access Layer cannot route directly to Router。

**Replay fixture**

- `tests/fixtures/replay/mvp0/004-text-ingress.fixture.json`

**Privacy assertions**

- Fixture uses `redacted_text` or `text_ref`，不使用 unredacted real user input。
- Text fixture 不出现 raw audio field。

**Acceptance criteria**

- `MVP0-TEXT-INGRESS-001` passes through runtime tests and deterministic replay。
- `InteractionState` final state has `turn_phase=TURN_COMMITTED`, `last_ingress_outcome=COMMITTED`, `current_audio_span_id=null`。

**Done when**

- Text ingress tests pass。
- Text replay fixture produces expected digest。
- Text ingress 不依赖 Duplex 或 model path。

## Slice 5: Audio Span and Duplex Mock Accept Path

**目标**

实现 minimal audio ingress path：audio span、mock/rule Duplex speech start/end、Interaction Controller commit。

**非目标**

不处理 raw audio、不做 real VAD、real semantic_close、real assistant-directedness、real ASR/Thinker。

**预计文件**

- Create later: `src/voice_agent/access/audio_ingress.py`
- Create later: `src/voice_agent/duplex/mock_duplex.py`
- Modify later: `src/voice_agent/interaction/controller.py`
- Create later: `tests/duplex/test_mock_audio_accept.py`
- Create later: `tests/replay/test_audio_ingress_replay.py`

**Events touched**

- `AUDIO_SPAN_STARTED`
- `AUDIO_SPAN_ENDED`
- `SPEECH_START_DETECTED`
- `SPEECH_END_DETECTED`
- `TURN_OPENED`
- `TURN_INGRESS_ACCEPTED`
- `TURN_INGRESS_COMMITTED`

**State objects touched**

- `InteractionState`

**Tests**

- audio span start + speech start sets `turn_phase=COLLECTING_INPUT`。
- speech end with mock accepted policy emits accepted and committed turn events。
- audio payloads include offsets and no raw audio。
- no ASR/Thinker frame before `TURN_INGRESS_COMMITTED`。

**Replay fixture**

- `tests/fixtures/replay/mvp0/005-audio-ingress-accepted.fixture.json`

**Privacy assertions**

- Fixture 只包含 audio metadata and refs。
- Raw audio absent and not required for deterministic replay。

**Acceptance criteria**

- `MVP0-AUDIO-INGRESS-001` passes through runtime tests and deterministic replay。
- Audio path causally traceable from audio span events to `TURN_INGRESS_COMMITTED`。

**Done when**

- Audio ingress tests pass。
- Replay reconstructs expected `InteractionState`。
- Mock Duplex clearly labeled or configured as mock/rule behavior。

## Slice 6: Mock Understanding and Router FAST_ONLY Skeleton

**目标**

在 committed turn 后发出 mock ASR/Thinker frame，并产生最小 Router decision。

**非目标**

不做 real ASR、real Thinker、SlowTask spawn、UserPatch、plan_version、evidence fusion、tool routing。

**预计文件**

- Create later: `src/voice_agent/understanding/mock_asr.py`
- Create later: `src/voice_agent/understanding/mock_thinker.py`
- Create later: `src/voice_agent/router/router.py`
- Create later: `src/voice_agent/state/task_focus_state.py`
- Create later: `tests/understanding/test_mock_understanding_after_commit.py`
- Create later: `tests/router/test_router_fast_only_mvp0.py`
- Create later: `tests/replay/test_router_decision_replay.py`

**Events touched**

- `TURN_INGRESS_COMMITTED`
- `MOCK_ASR_FRAME_EMITTED`
- `MOCK_THINKER_FRAME_EMITTED`
- `ROUTER_DECISION_EMITTED`

**State objects touched**

- `AdapterHealthState`
- `TaskFocusState` minimal/inert MVP-0 state
- `InteractionState` as causal source only

**Tests**

- Mock ASR/Thinker frames emit only after `TURN_INGRESS_COMMITTED`。
- Mock frame events carry `output_mode=mock`。
- Router emits only MVP router decisions and defaults to `FAST_ONLY` or `IGNORE` for MVP-0 synthetic inputs。
- Router does not spawn SlowTask, create UserPatch, or use plan_version in MVP-0。

**Replay fixture**

- `tests/fixtures/replay/mvp0/006-mock-understanding-router.fixture.json`

**Privacy assertions**

- Mock transcript and semantic frame refs use synthetic content。
- No model prompt, provider response, or secret-like adapter metadata is stored。

**Acceptance criteria**

- Text and audio committed turns produce mock understanding events and a Router decision。
- Replay can verify no Router decision appears before turn commit。

**Done when**

- Understanding and Router tests pass。
- Replay fixture validates expected event ordering。
- No SlowTask/UserPatch/tool code is introduced。

## Slice 7: Mock Talker Playback Progress and Delivery Markers

**目标**

实现 mock Talker playback span lifecycle with progress and playback commitment markers。

**非目标**

不做 real TTS、audio synthesis requirement、Composer coverage check、progress truthfulness check。

**预计文件**

- Create later: `src/voice_agent/talker/mock_talker.py`
- Modify later: `src/voice_agent/state/playback_state.py`
- Create later: `tests/talker/test_mock_playback.py`
- Create later: `tests/replay/test_playback_replay.py`

**Events touched**

- `PLAYBACK_SPAN_STARTED`
- `PLAYBACK_PROGRESS`
- `PLAYBACK_COMMITTED`
- `PLAYBACK_FINISHED`

**State objects touched**

- `PlaybackState`
- `InteractionState` playback phase only if controller observes playback events.

**Tests**

- Playback has unique `playback_span_id`。
- Playback progress reports `playback_offset_ms`。
- `PLAYBACK_COMMITTED` is recorded as a delivery marker only。
- Replay reconstructs latest progress and committed offsets。

**Replay fixture**

- `tests/fixtures/replay/mvp0/007-playback-progress.fixture.json`

**Privacy assertions**

- Mock audio uses `audio_ref` or `tts_stream_ref`, not raw audio。
- Fixture contains no real TTS output。

**Acceptance criteria**

- Mock Talker can start playback and produce progress/commit events。
- Replay preserves playback offsets and does not treat commitment as user confirmation。

**Done when**

- Playback tests pass。
- Playback fixture produces expected `PlaybackState`。
- No real TTS adapter/provider is added。

## Slice 8: Barge-in Candidate to Truncate Flow

**目标**

实现 truncate-only barge-in path：Duplex candidate -> Interaction interrupt policy -> Talker truncate confirmation。

**非目标**

不做 pause/resume、semantic-clause resume、multi-track recovery、model-side TTS cancellation guarantee、full duplex semantic model。

**预计文件**

- Modify later: `src/voice_agent/duplex/mock_duplex.py`
- Modify later: `src/voice_agent/interaction/controller.py`
- Modify later: `src/voice_agent/talker/mock_talker.py`
- Modify later: `src/voice_agent/state/playback_state.py`
- Create later: `tests/interaction/test_barge_in_truncate.py`
- Create later: `tests/replay/test_barge_in_truncate_replay.py`
- Create later: `tests/slo/test_mvp0_latency_metrics.py`

**Events touched**

- `PLAYBACK_PROGRESS`
- `PLAYBACK_COMMITTED`
- `AUDIO_SPAN_STARTED`
- `SPEECH_START_DETECTED`
- `BARGE_IN_CANDIDATE`
- `INTERRUPT_CANDIDATE`
- `TTS_TRUNCATE_REQUESTED`
- `TTS_TRUNCATED`

**State objects touched**

- `InteractionState`
- `PlaybackState`

**Tests**

- Duplex emits `BARGE_IN_CANDIDATE` only with `playback_span_id`, `playback_offset_ms`, `echo_likelihood`, `vad_confidence`, `barge_in_confidence`。
- Interaction Controller emits `INTERRUPT_CANDIDATE` and `TTS_TRUNCATE_REQUESTED`。
- `TTS_TRUNCATE_REQUESTED` includes `cutoff_playback_offset_ms` and references interrupt candidate。
- Talker emits `TTS_TRUNCATED` with `actual_stop_offset_ms`。
- Barge-in to truncate command latency is computable and <= 250ms in synthetic passing fixture。

**Replay fixture**

- `tests/fixtures/replay/mvp0/008-barge-in-truncate.fixture.json`

**Privacy assertions**

- No raw mic audio or playback audio in fixture。
- Echo and confidence values are metadata only。

**Acceptance criteria**

- `MVP0-BARGE-IN-TRUNCATE-001` passes through runtime tests and deterministic replay。
- Candidate-time offset、request cutoff offset、actual stop offset 保持区分。

**Done when**

- Barge-in/truncate tests pass。
- Replay fixture reconstructs `PlaybackState=TRUNCATED`。
- No pause/resume behavior is introduced。

## Slice 9: MVP-0 Replay Fixtures and Acceptance Runner

**目标**

增加 single acceptance runner over all MVP-0 synthetic replay fixtures and scenario assertions。

**非目标**

不要求 real service startup、browser/frontend、real audio fixture、model quality eval。

**预计文件**

- Create later: `src/voice_agent/replay/scenario_assertions.py`
- Create later: `tests/acceptance/test_mvp0_acceptance_scenarios.py`
- Create later: `tests/fixtures/replay/mvp0/004-text-ingress.fixture.json`
- Create later: `tests/fixtures/replay/mvp0/005-audio-ingress-accepted.fixture.json`
- Create later: `tests/fixtures/replay/mvp0/006-mock-understanding-router.fixture.json`
- Create later: `tests/fixtures/replay/mvp0/007-playback-progress.fixture.json`
- Create later: `tests/fixtures/replay/mvp0/008-barge-in-truncate.fixture.json`
- Create later: `tests/fixtures/replay/mvp0/009-local-trace-safety.fixture.json`
- Create later: `tests/fixtures/replay/mvp0/manifest.index.json`

**Events touched**

- All MVP-0 required events exercised by five acceptance scenarios。
- `REPLAY_STARTED`
- `REPLAY_COMPLETED`
- Optional trace safety events when privacy fixture exercises redaction/blocking。

**State objects touched**

- `InteractionState`
- `PlaybackState`
- `AdapterHealthState`
- `TracePrivacyState`
- Minimal/inert `TaskFocusState` only where Router replay needs it。

**Tests**

- Execute `MVP0-TEXT-INGRESS-001`。
- Execute `MVP0-AUDIO-INGRESS-001`。
- Execute `MVP0-BARGE-IN-TRUNCATE-001`。
- Execute `MVP0-MOCK-ADAPTER-CAPABILITY-001`。
- Execute `MVP0-LOCAL-TRACE-SAFETY-001`。
- Verify SLO labels are mock/degraded/real where calculated。

**Replay fixture**

- `tests/fixtures/replay/mvp0/manifest.index.json`

**Privacy assertions**

- All committed fixtures are synthetic/redacted/minimal。
- No fixture contains raw audio、raw debug trace、secrets、unredacted real user input、unredacted sensitive tool results、large raw web content。
- Local debug paths remain ignored and separate from committed fixtures。

**Acceptance criteria**

- Single MVP-0 acceptance command validates fixtures、replays event streams、checks final state digests/assertions。
- Acceptance runner fails if forbidden MVP-0 scope events or modules appear in event stream。

**Done when**

- All five MVP-0 acceptance scenarios pass。
- Fixture safety checks pass。
- Review confirms no MVP-1/MVP-2/MVP-3 scope slipped into MVP-0。

## MVP-0 Exit Criteria

MVP-0 完成条件：

- Text ingress emits `TEXT_INPUT_RECEIVED` -> `TURN_OPENED` -> `TURN_INGRESS_ACCEPTED` -> `TURN_INGRESS_COMMITTED`。
- Audio ingress emits audio span and mock Duplex events before turn commit。
- Mock ASR/Thinker emit only after `TURN_INGRESS_COMMITTED`。
- Router emits post-commit decision only。
- Mock Talker emits playback progress and delivery markers。
- Barge-in path emits `BARGE_IN_CANDIDATE` -> `INTERRUPT_CANDIDATE` -> `TTS_TRUNCATE_REQUESTED` -> `TTS_TRUNCATED`。
- Deterministic replay reconstructs MVP-0 states without re-running models or tools。
- Capability snapshot and all mock outputs are labeled mock。
- Local trace safety assertions pass。
- No ADR、Architecture Book、or frozen spec changes are required to explain implementation。
