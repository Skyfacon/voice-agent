# MVP-3 Acceptance Scenarios

Source of truth: accepted ADR baseline, especially ADR-002, ADR-010, ADR-011, ADR-012, ADR-015, and the derived specs in `docs/specs/model-adapter-capabilities.md`, `docs/specs/replay-spec.md`, and `docs/implementation/mvp3-backlog.md`.

MVP-3 validates real/fallback/degraded adapter integration behind existing adapter boundaries. It does not validate new architecture capability, real external side-effect tools, frontend product demo, multi active SlowTask, pause/resume, or provider calls during replay.

Scenario ids are acceptance labels, not journal event names. Event chains below are causal sketches; committed fixtures must still include common envelope fields and required fields from the canonical registry.

All MVP-3 fixtures must be synthetic, redacted, and minimal.

## Scenario MVP3-FIXTURE-SAFETY-001

| Field | Spec |
| --- | --- |
| purpose | Validate the MVP-3 fixture/replay safety skeleton before adapter implementation begins. |
| initial state | Empty MVP-3 fixture with GitHub-safe replay manifest. |
| event chain | none for Slice 0. |
| required assertions | Fixture domain is `GITHUB_ALLOWED`; replay mode is deterministic; safety flags are false; no provider execution is claimed. |
| replay expectations | Deterministic replay completes without events and without provider/tool/network/clock/random execution. |
| forbidden behavior | No provider SDK, no provider network probe, no direct external model call, no raw audio, no raw trace, no secrets, no unredacted real user input. |

## Scenario MVP3-ADAPTER-PROFILE-001

| Field | Spec |
| --- | --- |
| purpose | Validate ASR, Thinker, Slow LLM, and TTS adapter capability profiles. |
| initial state | Provider-agnostic profile examples exist. |
| event chain | none required; profile validation is metadata-only. |
| required assertions | Required real profile set passes readiness gate; mock-only and credential-like profiles fail closed. |
| replay expectations | No replay provider probe. |
| forbidden behavior | No provider SDK or endpoint credential in profile examples. |

## Scenario MVP3-ADAPTER-EVENT-HARNESS-001

| Field | Spec |
| --- | --- |
| purpose | Validate fake-real adapter health/error/degraded event production. |
| initial state | Session started with MVP-3 capability snapshot. |
| event chain | `ADAPTER_HEALTHCHECK_FAILED` / `ADAPTER_REQUEST_RETRYING` / `ADAPTER_REQUEST_FAILED` / `ADAPTER_OUTPUT_VALIDATION_FAILED` / `ADAPTER_OUTPUT_DEGRADED`. |
| required assertions | Events validate through canonical registry and enter journal through `AdapterCallbackAppendBoundary`; fake-real harness does not call provider SDKs, endpoint healthchecks, sockets, HTTP clients, or other network probes; secret-like adapter metadata is rejected or redacted before trace exposure; output modes remain explicit as `real`, `fallback`, or `degraded`. |
| replay expectations | Replay reconstructs adapter health state from recorded events only. |
| forbidden behavior | No live provider request. |

## Scenario MVP3-RUNTIME-ASSEMBLY-001

| Field | Spec |
| --- | --- |
| purpose | Validate MVP-3 runtime session startup from validated profiles. |
| initial state | Valid MVP-3 profile set. |
| event chain | `SESSION_STARTED` -> `ADAPTER_CAPABILITY_SNAPSHOT_RECORDED`. |
| required assertions | Snapshot records `capability_snapshot_ref`, `adapter_ids`, `adapter_types`, `deployment_modes`, `output_modes`, and `capability_version`; valid profile sets can include explicit `real`, `fallback`, and `degraded` modes; unsupported, incomplete, or credential-like endpoint/config/profile refs fail closed before startup. |
| replay expectations | Replay does not probe providers. |
| forbidden behavior | No startup network healthcheck. |

## Scenario MVP3-ASR-CONTRACT-001

| Field | Spec |
| --- | --- |
| purpose | Validate ASR adapter final transcript or text projection contract. |
| initial state | Committed audio turn metadata exists. |
| event chain | `ASR_TRANSCRIPT_OUTPUT_EMITTED` plus `ADAPTER_OUTPUT_DEGRADED` when timestamps or streaming support are unavailable. |
| required assertions | Output mode is explicit; no raw audio is committed; missing timestamps degrade explicitly. |
| replay expectations | Replay uses recorded refs only. |
| forbidden behavior | No direct ASR provider call outside adapter. |

## Scenario MVP3-THINKER-CONTRACT-001

| Field | Spec |
| --- | --- |
| purpose | Validate Thinker structured SemanticFrame-compatible output contract. |
| initial state | Committed turn and ASR/text evidence exist. |
| event chain | `THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED` plus `ADAPTER_OUTPUT_DEGRADED` when semantic close, assistant-directedness, emotion, or audio caption are unavailable. |
| required assertions | Output is normalized before Router/SlowTask use; missing optional semantic fields degrade explicitly; output mode is explicit as real/fallback/degraded. |
| replay expectations | Replay uses recorded refs only. |
| forbidden behavior | No provider-specific schema leakage into Router or SlowTask. |

## Scenario MVP3-SLOW-LLM-STRUCTURED-001

| Field | Spec |
| --- | --- |
| purpose | Validate Slow LLM structured output and validation failure handling. |
| initial state | SlowTask current plan needs model output. |
| event chain | adapter request -> structured output validation pass or `ADAPTER_OUTPUT_VALIDATION_FAILED`. |
| required assertions | Invalid output does not silently pass downstream; retry/failure/degraded path is event-visible. |
| replay expectations | Replay does not call Slow LLM provider. |
| forbidden behavior | No direct provider call from SlowTask. |

## Scenario MVP3-TTS-CONTRACT-001

| Field | Spec |
| --- | --- |
| purpose | Validate TTS basic synthesis refs and truncate capability handling. |
| initial state | SpokenPlan approved for playback. |
| event chain | TTS adapter output or degraded/fallback event; playback events if output is safe. |
| required assertions | Audio refs are safe; missing truncate capability blocks or degrades barge-in target validation. |
| replay expectations | Replay does not require raw audio. |
| forbidden behavior | No raw audio fixture or pause/resume scope. |

## Scenario MVP3-FALLBACK-DEGRADED-REPLAY-001

| Field | Spec |
| --- | --- |
| purpose | Validate real/fallback/degraded adapter outcomes are replay-visible. |
| initial state | Adapter profile set includes explicit modes. |
| event chain | real output, fallback output, and degraded event variants. |
| required assertions | Output modes are explicit and old-plan results do not advance current task without adoption. |
| replay expectations | Deterministic replay distinguishes modes from recorded events. |
| forbidden behavior | No hidden provider rerun during replay. |

## Scenario MVP3-ACCEPTANCE-SCOPE-SAFETY-001

| Field | Spec |
| --- | --- |
| purpose | Validate suite-level MVP-3 scope safety. |
| initial state | MVP-3 acceptance manifest loaded. |
| event chain | acceptance runner validates fixtures and scenarios. |
| required assertions | Required scenarios are present; fixtures are deterministic, GitHub-safe, synthetic/redacted/minimal, and mode labels are explicit. |
| replay expectations | Acceptance runner reports pass/fail without provider/tool/network execution. |
| forbidden behavior | No direct provider calls, unsafe fixtures, secret leakage, real external side effects, or silent architecture expansion. |
