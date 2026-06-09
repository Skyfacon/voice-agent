# MVP-3 Implementation Backlog

本文档是 MVP-3 的 slice-driven backlog。它延续 MVP-0 / MVP-1 / MVP-2 的工作模式：先建立 fixture、replay、scope safety 和 acceptance skeleton，再逐步接入 adapter contract、runtime harness、单个 adapter 行为、fallback/degraded replay，最后做 acceptance runner 和 closeout。

MVP-3 must not start with direct provider integration. 真实 provider 只能在 profile、assembly gate、callback serialization、failure/degraded replay 和 secret-safety gate 都存在后，作为某一个 adapter slice 的内部实现替换进入。

## Source Contracts

- `AGENTS.md`
- `stage_b_adr_register.md`
- `docs/adr/ADR-001 Duplex Boundary and Interaction Controller.md`
- `docs/adr/ADR-002 Event Journal, Timing Model, and Replay Foundation.md`
- `docs/adr/ADR-003 Barge-in and TTS Truncate Contract.md`
- `docs/adr/ADR-004 SlowTask Plan Versioning and Stale Result Policy.md`
- `docs/adr/ADR-009 SemanticCommitment and Thinker-as-Composer Contract.md`
- `docs/adr/ADR-010 Trace Replay Debug Policy for Web Demo.md`
- `docs/adr/ADR-011 Model Adapter Capability Contract.md`
- `docs/adr/ADR-012 MVP Vertical Slice and Development SLOs.md`
- `docs/adr/ADR-015 Repository Governance and AGENTS.md Rules.md`
- `docs/specs/model-adapter-capabilities.md`
- `docs/specs/replay-spec.md`
- `docs/specs/state-reducers.md`
- `docs/implementation/mvp0-backlog.md`
- `docs/implementation/mvp1-backlog.md`
- `docs/implementation/mvp2-backlog.md`
- `docs/implementation/mvp2-closeout.md`

## Current Starting Point

- MVP-0 / MVP-1 / MVP-2 are complete for their documented mock/demo/replay scopes.
- MVP-3 readiness gates now exist for adapter profile validation, runtime assembly, adapter event registration, and adapter callback append serialization.
- Existing branch work has a design and plan for adapter profile spec; this becomes MVP-3 Slice 1, not the whole MVP-3 plan.
- No real ASR, Thinker, Slow LLM, or TTS adapter implementation is currently present.
- No provider SDK dependency, provider endpoint probe, API key, real frontend, or real external side-effect tool is in MVP-3 scope.

## MVP-3 Scope

MVP-3 replaces selected mock model adapters with real/fallback/degraded adapter behavior behind existing architecture boundaries. It must not add new architecture capability.

Allowed scope:

- Adapter capability profiles for ASR, Thinker, Slow LLM, and TTS.
- Runtime assembly from validated profile sets.
- Adapter health/error/degraded event harness.
- Single append boundary for adapter callbacks entering Event Journal.
- Per-adapter contract slices for ASR, Thinker, Slow LLM, and TTS.
- Deterministic replay fixtures for real/fallback/degraded adapter outputs and failures.
- MVP-3 acceptance runner and closeout.

## MVP-3 Prohibited Scope

MVP-3 must not implement:

- direct external model calls outside adapters;
- provider calls during replay;
- provider SDK use before profile/assembly/failure/degraded gates exist;
- real external write tools, payment, booking, deletion, account mutation, external communication, or device control;
- multi active SlowTask;
- pause/resume SlowTask;
- new RouterDecision, TaskFocus value, or SlowTask state;
- Composer fact rewriting;
- raw audio, raw trace, secrets, unredacted real user input, or large raw web content in committed fixtures;
- frontend product demo unless separately planned and scoped.

## Core Invariants

- Every critical state transition must be represented by Event Journal events.
- Adapter outputs must be labeled `real`, `mock`, `fallback`, or `degraded`.
- Mock/fallback/degraded profiles do not count as required MVP-3 real readiness.
- Replay is deterministic and must not rerun providers, tools, network, clocks, or random.
- Adapter callbacks must enter the Event Journal through one append boundary.
- Old-plan adapter/tool results must not advance current state without explicit adopt/rebase.
- Secrets and credential-like refs must be rejected or redacted before trace exposure.
- MVP-3 does not introduce new architecture capability without ADR update.

## Slice 0: MVP-3 fixture / replay safety skeleton

**Goal**

Create the MVP-3 fixture directory, empty fixture, acceptance scenario skeleton, manifest index, and initial safety tests before any adapter implementation. MVP-3 Slice 0 is a safety skeleton only; it proves the suite boundary before adapter profile or provider work begins.

**Non-goals**

No adapter profile examples, real provider calls, fake-real runtime harness, provider SDK dependency, event producer, or acceptance runner over real adapter behavior.

**Likely files**

- Create: `docs/specs/mvp3-acceptance-scenarios.md`
- Create: `tests/fixtures/replay/mvp3/README.md`
- Create: `tests/fixtures/replay/mvp3/manifest.index.json`
- Create: `tests/fixtures/replay/mvp3/000-empty-mvp3-session.fixture.json`
- Create: `tests/acceptance/test_mvp3_acceptance_scenarios.py`
- Modify: `tests/conftest.py`

**Replay / eval expectation**

The empty MVP-3 fixture replays deterministically, is GitHub-safe, and contains no provider execution or secret-bearing metadata.

**Done when**

- MVP-3 backlog declares Slice 0-9.
- MVP-3 acceptance spec declares all planned scenario ids.
- MVP-3 manifest and empty fixture pass Slice 0 safety tests.
- Existing MVP0/MVP1/MVP2 tests remain passing.

## Slice 1: Adapter profile spec

**Goal**

Define provider-agnostic ASR, Thinker, Slow LLM, and TTS adapter profiles.

**Non-goals**

No provider selection, SDK dependency, healthcheck, network call, or runtime adapter implementation.

**Likely files**

- Create: `docs/specs/adapter-capability-profiles.md`
- Create: `tests/adapters/test_mvp3_adapter_capability_profiles_spec.py`

**Done when**

- Synthetic profile examples pass `validate_capability_matrix`.
- Required real profile set passes `validate_mvp3_adapter_profile_set`.
- Runtime assembly snapshot can be built without probing providers.
- Mock-only and credential-like profile cases fail closed.

## Slice 2: Adapter health/error/degraded event harness

**Goal**

Create a fake-real adapter harness that emits canonical adapter health, retry, failed, validation failed, and degraded events without network calls.

**Non-goals**

No real provider SDK, no real model output, no production retry scheduler.

**Done when**

- Harness events validate through the canonical registry.
- Events enter the journal through `AdapterCallbackAppendBoundary`.
- Secret-like adapter metadata is rejected or redacted.

## Slice 3: Runtime assembly and startup

**Goal**

Start a session from an MVP-3 profile set and record a capability snapshot with explicit real/fallback/degraded modes.

**Non-goals**

No provider health probe during startup.

**Done when**

- `SESSION_STARTED` and `ADAPTER_CAPABILITY_SNAPSHOT_RECORDED` replay deterministically.
- Unsupported or incomplete MVP-3 profile sets fail closed.

## Slice 4: ASR adapter contract

**Goal**

Define and validate ASR final transcript or equivalent text projection behind an adapter boundary.

**Non-goals**

No streaming requirement, no raw audio fixture, no direct ASR provider call outside adapter.

**Done when**

- ASR output events/ref metadata are labeled real/fallback/degraded.
- Missing timestamps or streaming support degrade explicitly.
- Replay does not require raw audio.

## Slice 5: Thinker adapter contract

**Goal**

Define and validate Thinker SemanticFrame-compatible structured output behind an adapter boundary.

**Non-goals**

No Composer fact rewriting, no provider-specific schema leakage into Router or SlowTask.

**Done when**

- Thinker output is normalized before downstream use.
- Missing semantic close, directedness, emotion, or audio caption degrades explicitly.

## Slice 6: Slow LLM structured output

**Goal**

Validate structured SlowTask output from a Slow LLM adapter, including schema validation failure handling.

**Non-goals**

No new SlowTask states, no multi SlowTask, no direct provider call from SlowTask.

**Done when**

- Invalid structured output emits `ADAPTER_OUTPUT_VALIDATION_FAILED`.
- Retry/failure/degraded paths are replay-visible.
- SlowTask consumes only validated normalized output.

## Slice 7: TTS adapter contract

**Goal**

Define and validate TTS basic audio synthesis refs and truncate capability handling.

**Non-goals**

No pause/resume, no raw audio fixture, no production audio storage policy.

**Done when**

- TTS output uses safe audio refs or metadata refs.
- Missing truncate capability blocks or degrades barge-in target validation explicitly.

## Slice 8: Fallback/degraded replay

**Goal**

Add deterministic fixtures for real/fallback/degraded adapter outcomes and failure paths.

**Non-goals**

No provider calls during replay or fixture generation from raw traces.

**Done when**

- Replay distinguishes real/fallback/degraded modes from recorded events.
- Failure/degraded scenarios do not silently advance current task state.

## Slice 9: MVP-3 acceptance runner and closeout

**Goal**

Create a single MVP-3 acceptance runner over all required MVP-3 scenarios and perform closeout review.

**Non-goals**

No new architecture capability, frontend product demo, or real external side-effect tools.

**Done when**

- All MVP-3 scenario ids are covered.
- Acceptance runner rejects direct provider calls, missing mode labels, unsafe fixtures, weakened replay properties, and scope broadening.
- MVP0/MVP1/MVP2 acceptance remains passing.
