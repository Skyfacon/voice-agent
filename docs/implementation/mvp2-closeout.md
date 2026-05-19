# MVP-2 Closeout / Handoff

本文面向准备关闭 MVP-2、整理 PR/阶段总结、并进入 MVP-3 planning 的 human developer / coding agent。它不替代 ADR，不修改 ADR，也不授权扩大 MVP scope。后续工作仍以 `AGENTS.md`、`stage_b_adr_register.md`、`docs/adr/*.md` 和 `docs/specs/*.md` 为准。

## 1. Closeout Snapshot

- Prepared on: 2026-05-19
- Scope of this closeout: documentation-only review and handoff. No ADR, code, runtime service, real model, real TTS, real tool, real frontend, or real external side effect was introduced by this closeout.
- Local review base: `mvp2/slice8-acceptance-runner` at `9f47301` (`feat: add MVP2 acceptance runner`).
- Remote-main note: remote refs were refreshed on 2026-05-19. `origin/main` is `671f7fc` (`Merge pull request #27 from Skyfacon/mvp2/slice8-acceptance-runner`) and includes the MVP-2 slice8 acceptance runner.
- Initial local worktree status: clean before this document was added.
- Recent feature diff versus local `main`: `src/voice_agent/replay/scenario_assertions.py`, `tests/acceptance/test_mvp2_acceptance_scenarios.py`, `tests/fixtures/replay/mvp2/008-tool-manifest-only.fixture.json`, `tests/fixtures/replay/mvp2/009-progressive-stale-tool-result.fixture.json`, `tests/fixtures/replay/mvp2/manifest.index.json`, and `tests/replay/test_fixture_safety.py`.
- Canonical test entrypoint: `./scripts/test -q`.
- Closeout test status: `./scripts/test -q` passed locally with `665 passed`.

## 2. Sources Reviewed

- Governance and ADR index: `AGENTS.md`, `stage_b_adr_register.md`.
- MVP-2 planning and specs: `docs/implementation/mvp2-backlog.md`, `docs/specs/mvp2-acceptance-scenarios.md`, `docs/specs/event-registry.md`, `docs/specs/replay-spec.md`, `docs/specs/state-reducers.md`.
- MVP acceptance suites: `tests/acceptance/test_mvp0_acceptance_scenarios.py`, `tests/acceptance/test_mvp1_acceptance_scenarios.py`, `tests/acceptance/test_mvp2_acceptance_scenarios.py`.
- MVP-2 replay manifest and fixtures: `tests/fixtures/replay/mvp2/manifest.index.json` and the ten MVP-2 fixture files listed there.
- MVP-2 implementation and tests: replay scenario assertions, replay runner behavior, tool executor tests, demo tool tests, demo UI patch replay tests, destructive confirmation tests, Composer tests, coverage/truthfulness checker tests, and fixture safety tests.

## 3. Phase Status Summary

MVP-0 is complete for the mock live-loop and replay spine. It covers text/audio ingress, barge-in/truncate, mock adapter capability snapshots, local trace safety, deterministic replay, and mock SLO labels. The acceptance suite validates 5 required scenarios over 7 replay fixtures and still rejects MVP-1/MVP-2-only scope in MVP-0 fixtures.

MVP-1 is complete for SlowTask mock behavior. It covers Router/TaskFocus handoff, active task patching, `plan_version` advancement, foreground chat, ambiguity without mutation, waiting-slot behavior, stale evidence with and without adoption, cancel/switch confirmation, failed sticky terminal state, SemanticCommitment, and deterministic replay. The acceptance suite validates 12 required scenarios over 13 replay fixtures and rejects real output modes and MVP-2-only Tool Executor behavior in MVP-1 fixtures.

MVP-2 is complete as a deterministic demo/replay acceptance slice. It adds demo sandbox tools, progressive Tool Executor events, demo UI state patch replay, webSearch evidence boundaries, demo destructive action confirmation gates, Thinker-as-Composer, coverage/truthfulness checks, and a formal MVP-2 acceptance runner. It does not claim real model, real TTS, real tool, real frontend, or real external side-effect readiness.

## 4. MVP-2 Completed Capability Surface

- Tool manifest and scope declarations for `memo`, `alarm`, `flashlight`, `weather`, and `webSearch`, including tool category, side-effect class, trust label, and UI patch capability.
- Progressive Tool Executor lifecycle coverage: manifest load, partial arguments, ready arguments, insufficient-argument blocking, preview, authorization, start, progress, UI patch, result, failure, retry, cancel request, and cancellation metadata.
- Sandbox-only demo backend state for memo/alarm/flashlight style actions, with replayable UI state patches emitted only through `TOOL_UI_STATE_PATCHED`.
- `DemoUIState` replay reconstruction from recorded patch refs only. Successful `TOOL_RESULT_RECEIVED` is not enough to infer frontend/demo state mutation.
- `DEMO_DESTRUCTIVE_ACTION` confirmation gate for sandbox memo delete and alarm cancel, requiring current-plan confirmation and correct causal authorization before execution can start.
- Progressive stale ToolResult handling, where old-plan results are recorded as stale evidence and cannot advance the current task without explicit adoption.
- webSearch as evidence only: `UNTRUSTED_WEB_EVIDENCE`, `EXTERNAL_READ_UNTRUSTED`, no UI patch, no backend action, no instruction/policy mutation.
- Thinker-as-Composer mock role: emits `SPOKEN_PLAN_EMITTED` from current-plan SemanticCommitment or grounded progress without playback and without rewriting SlowTask facts.
- CommitmentCoverageCheck and ProgressTruthfulnessCheck mock gates. Passed checks can authorize matching playback; failed or stale checks cannot.
- MVP-2 acceptance runner with scenario-derived coverage, fixture safety gates, deterministic replay digest comparison, no-runtime-execution summary, ADR-update summary, and hidden future-scope detection summary.

## 5. Acceptance Coverage

The MVP-2 acceptance spec declares 15 scenarios and the runner verifies the manifest exactly matches the spec-derived scenario list:

- Tool surface: `MVP2-TOOL-MANIFEST-001`, `MVP2-TOOL-ARGS-PARTIAL-001`, `MVP2-TOOL-BLOCKED-INSUFFICIENT-ARGS-001`.
- Demo tools: `MVP2-MEMO-SANDBOX-WRITE-001`, `MVP2-ALARM-SANDBOX-SCHEDULE-001`, `MVP2-FLASHLIGHT-DEMO-DEVICE-ACTION-001`, `MVP2-WEATHER-READ-ONLY-001`, `MVP2-WEBSEARCH-UNTRUSTED-EVIDENCE-001`.
- UI/replay boundary: `MVP2-UI-STATE-PATCHED-001`.
- Confirmation and stale policy: `MVP2-DEMO-DESTRUCTIVE-CONFIRMATION-001`, `MVP2-STALE-TOOL-RESULT-PROGRESSIVE-001`.
- Composer and speech gates: `MVP2-COMPOSER-SPOKEN-PLAN-001`, `MVP2-COMMITMENT-COVERAGE-001`, `MVP2-PROGRESS-TRUTHFULNESS-001`.
- Suite safety: `MVP2-ACCEPTANCE-SCOPE-SAFETY-001`.

The acceptance runner also rejects weakened manifests: missing required scenarios, skipped fixture checks, unsafe side-effect classes, weakened replay properties, unsafe source modules, repo-unsafe fixture content, raw artifact markers, real/unlabeled output modes, and real adapter runtime claims.

## 6. Replay Fixture Coverage

The MVP-2 manifest is `MVP2-ACCEPTANCE`, `GITHUB_ALLOWED`, deterministic, and limited to synthetic/redacted/minimal fixture material. It checks ten fixtures:

| Fixture | Primary coverage |
| --- | --- |
| `000-empty-mvp2-session.fixture.json` | Empty MVP-2 replay safety skeleton. |
| `001-tool-execution-state.fixture.json` | ToolExecutionState reducer surface, including lifecycle, args, authorization, progress, UI refs, result/failure/retry/cancel metadata. |
| `002-tool-executor-skeleton.fixture.json` | Tool Executor success and blocked insufficient-provenance paths without backend replay. |
| `003-tool-ui-state-patch.fixture.json` | Demo UI/backend reconstruction only from `TOOL_UI_STATE_PATCHED`. |
| `004-demo-tools.fixture.json` | memo, alarm, flashlight, weather, and webSearch demo tool replay. |
| `005-demo-destructive-confirmation.fixture.json` | Current-plan destructive confirmation gate for memo delete and alarm cancel. |
| `006-thinker-as-composer.fixture.json` | Composer emits unchecked spoken plans from current-plan commitment and grounded progress. |
| `007-composer-checks.fixture.json` | Coverage/truthfulness pass events gate playback without TTS/audio/frontend execution. |
| `008-tool-manifest-only.fixture.json` | Manifest loading for all MVP-2 tools without execution. |
| `009-progressive-stale-tool-result.fixture.json` | Old-plan progressive ToolResult becomes stale evidence and does not advance current task. |

Replay coverage explicitly requires deterministic replay to not rerun models, tools, network, clock, or random; demo UI state must come from `TOOL_UI_STATE_PATCHED`; webSearch must remain untrusted evidence only; destructive demo actions require current-plan confirmation; Composer output requires coverage/truthfulness gates before playback; and old-plan ToolResult reuse requires a stale-evidence/adoption chain.

## 7. Non-goals and Out-of-scope Behavior

MVP-2 intentionally does not include:

- Real ASR, Thinker, Slow LLM, TTS, duplex model, embedding/RAG, or provider-backed Composer calls.
- Direct external model calls outside adapters.
- Real Tool Executor integrations, real external writes, external communication, booking, payment, real deletion, account or identity mutation, credential mutation, or real device control.
- Real webSearch or real weather API calls by default. The accepted MVP-2 path is mock/synthetic/read-only evidence replay.
- Real frontend launch or browser/product UI verification. MVP-2 verifies frontend-visible demo state as replayed `DemoUIState`, not a running UI surface.
- Production privacy/auth, production persistence, production tool credentials, or unredacted real user input fixtures.
- Multi active SlowTask, pause/resume, new RouterDecision values, new TaskFocus values, new SlowTask states, or new canonical event names.
- Any new architecture capability beyond the accepted MVP-2 ADR/spec surface.

The closeout review did not find MVP-2 scope-out behavior in the reviewed source/spec/test surface. The acceptance gates also explicitly reject the main out-of-scope behaviors and source modules.

## 8. Review Findings and Gate Hardening

Recent review work exposed several places where a passing happy path would not have been enough:

- Destructive confirmation needed more than an accepted confirmation event. The gate now verifies current `task_id` / `plan_version`, correct tool trigger, preview argument fingerprint, router/turn causality, confirmation scope, and causal authorization before `TOOL_EXECUTION_STARTED`.
- Tool UI state needed a strict event boundary. Replay now reconstructs demo state only from Tool Executor-owned `TOOL_UI_STATE_PATCHED`; it rejects direct frontend/model text mutation and does not infer state mutation from a ToolResult alone.
- webSearch needed a stronger evidence boundary. The manifest and acceptance runner require `UNTRUSTED_WEB_EVIDENCE`, `EXTERNAL_READ_UNTRUSTED`, read-only side effects, no UI patch, and evidence review rather than instruction/backend action.
- Composer needed provenance and fact-preservation gates. The runtime/replay tests reject stale sources, wrong task/plan bindings, noncanonical source modules, missing source ids, unsupported progress sources, and symbolic metadata drops/rewrites/additions.
- Coverage and truthfulness checks needed replayable failure paths. Failed checks are preserved as check events but cannot authorize playback; passed playback must reference the matching passed check and spoken plan.
- Progressive ToolResult handling needed acceptance-level stale protection. The old-plan ToolResult fixture verifies `TOOL_RESULT_MARKED_STALE` and `STALE_EVIDENCE_RECORDED`, with no SemanticCommitment or current-plan advancement unless adoption is explicit.
- The acceptance runner now guards against silent scope broadening by rejecting real output modes, unsafe side-effect classes, weakened replay properties, missing fixture checks, unsafe fixtures, and forbidden future-scope source modules.

## 9. ADR and Scope Assessment

No ADR update is required for the current MVP-2 closeout. The implemented and tested behavior stays within the accepted ADR/spec surface:

- Canonical events are already represented in the event registry/specs used by MVP-2.
- No new architecture role, event family, state owner, or MVP scope was introduced by this closeout.
- No real model/tool/frontend/external side-effect behavior was introduced.

An ADR update remains required before any future change that adds canonical event names, changes owner boundaries, adds new RouterDecision/TaskFocus/SlowTask states, enables real external side effects, introduces production privacy/auth policy, or expands MVP-3 beyond adapter replacement.

## 10. Current Test Status

- Required command: `./scripts/test -q`.
- Status for this closeout document: passed locally with `665 passed`.
- CI/remote status: remote `main` was refreshed locally and confirmed at `671f7fc`; GitHub CI status should still be checked on the docs-only PR.

## 11. MVP-3 Readiness

The project is ready to start MVP-3 planning after the closeout document is reviewed and the canonical test command passes. The readiness basis is:

- Adapter capability contracts already distinguish `real`, `mock`, `fallback`, and `degraded` output modes.
- MVP-0 through MVP-2 replay suites establish deterministic replay, trace privacy, event ownership, and fixture safety expectations.
- MVP-2 acceptance explicitly forbids real adapter runtime integration, which gives MVP-3 a clear boundary to change deliberately rather than accidentally.
- State reducers and replay specs already require replay not to rerun models, tools, network, clock, or random.

MVP-3 should be treated as adapter integration planning, not architecture expansion. It should replace selected mock adapter behavior behind existing adapter boundaries and keep deterministic replay based on recorded events/refs.

## 12. Remaining Risks and Technical Debt

- Remote refs were refreshed during this closeout; `origin/main` was confirmed at `671f7fc`. CI should still be treated as the merge authority for the final docs-only PR.
- `docs/implementation/mvp2-backlog.md` still contains historical language saying the MVP-2 runtime is not yet implemented. That backlog was accurate before slice completion, but it may confuse future readers unless a small documentation cleanup links to this closeout.
- `tests/fixtures/replay/mvp2/manifest.index.json` still contains a historical `planned_fixture_checks` section in addition to the current `fixture_checks`. It is harmless but can confuse readers.
- `src/voice_agent/replay/scenario_assertions.py` now carries a large amount of MVP-0/MVP-1/MVP-2 acceptance logic. A future non-scope-changing cleanup could split runner helpers by MVP phase.
- MVP-2 validates replayed demo UI state, not a live product frontend. If a real frontend demo is needed before product demos, it should be planned explicitly and not backfilled into MVP-2.
- MVP-3 real adapters will need credential-safe config refs, output-mode labeling, failure/degraded/fallback events, and replay fixtures before any provider endpoint is exercised.
- The MVP-2 tests are intentionally synthetic. They are strong for control-plane invariants but do not evaluate real provider quality, latency, acoustic quality, TTS quality, or production tool behavior.

## 13. Recommended MVP-3 Entry Order

Keep MVP-3 narrow: real adapter capability matrix, adapter mock/real/fallback/degraded labeling, deterministic replay that never reruns models/tools/network/clock/random, and no new architecture capability.

1. Refresh local `main`, confirm the slice8 merge SHA, land this docs-only closeout, and verify `./scripts/test -q` plus CI.
2. Re-read ADR-011 and existing adapter capability code, then write the MVP-3 adapter capability matrix for ASR, Thinker, Slow LLM, and TTS.
3. Add tests that enforce adapter output-mode labeling: `mock`, `real`, `fallback`, and `degraded` must be explicit and credential-safe.
4. Add deterministic replay fixtures for adapter output/failure/degraded events using recorded refs only. Replay must not call providers, tools, network, clock, or random.
5. Add fallback/degraded acceptance cases before enabling any real provider path.
6. Wire one real adapter behind the existing adapter interface only after the capability matrix and replay gates exist.
7. Keep Tool Executor, frontend, multi SlowTask, pause/resume, and real external side-effect tools out of MVP-3 unless a new ADR explicitly expands scope.

## 14. Merge / Handoff Recommendation

- Commit this closeout as a standalone docs-only change against refreshed remote `main`.
- A separate PR is recommended because the code feature branch has already been merged and this document is a stage closeout artifact rather than a runtime fix.
- After this closeout lands and tests pass, the next work item should be MVP-3 planning, not more MVP-2 feature work.
