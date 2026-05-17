# MVP-2 Implementation Backlog

本文档是 MVP-2 的开工入口和实施 backlog。它不替代 ADR，不修改 ADR，也不授权扩大 MVP scope。实现时仍以 `AGENTS.md`、`stage_b_adr_register.md`、`docs/adr/*.md` 和 `docs/specs/*.md` 为准。

## 当前阶段一句话结论

MVP-0 / MVP-1 mock/replay spine 已完成；MVP-2 目标是实现 demo sandbox tools、progressive Tool Executor、`TOOL_UI_STATE_PATCHED`、工具前端反馈、Thinker-as-Composer、CommitmentCoverageCheck 和 ProgressTruthfulnessCheck，但当前 runtime 尚未实现这些能力。

当前实现观察：

- 已有 `MVP1Router`、`TaskFocusState`、`SlowTaskState`、`MockSlowTaskRuntime`、`UserPatchEvidencePackRuntime`、MVP-1 deterministic replay fixtures 和 acceptance runner。
- 未观察到 `ToolExecutionState` reducer、Tool Executor runtime、demo backend、工具前端界面、Thinker-as-Composer runtime、coverage/truthfulness checker runtime。
- `docs/specs/event-registry.md` 已列出 MVP-2 canonical events；registry 中存在事件名不代表 runtime 已实现。

## Source contracts

- `AGENTS.md`
- `stage_b_adr_register.md`
- `docs/adr/ADR-002 Event Journal, Timing Model, and Replay Foundation.md`
- `docs/adr/ADR-004 SlowTask Plan Versioning and Stale Result Policy.md`
- `docs/adr/ADR-005 Demo Tool Sandbox, Progressive Tool Invocation, and Side Effect Policy.md`
- `docs/adr/ADR-006 Router Task Focus and Single Active SlowTask MVP.md`
- `docs/adr/ADR-007 UserPatch Evidence Pack.md`
- `docs/adr/ADR-008 ASR Thinker Evidence Fusion and SlowTask-led Conflict Resolution.md`
- `docs/adr/ADR-009 SemanticCommitment and Thinker-as-Composer Contract.md`
- `docs/adr/ADR-010 Trace Replay Debug Policy for Web Demo.md`
- `docs/adr/ADR-012 MVP Vertical Slice and Development SLOs.md`
- `docs/adr/ADR-013 Truthful Progress Feedback.md`
- `docs/adr/ADR-014 webSearch Evidence Boundary for Demo Tools.md`
- `docs/adr/ADR-015 Repository Governance and AGENTS.md Rules.md`
- `docs/adr/ADR-016 SlowTask Lifecycle and Confirmation State Contract.md`
- `docs/project-overview.md`
- `docs/architecture-book.md`
- `docs/architecture-diagrams.md`
- `docs/implementation/mvp1-backlog.md`
- `docs/implementation/mvp1-to-mvp2-handoff.md`
- `docs/specs/event-registry.md`
- `docs/specs/state-reducers.md`
- `docs/specs/replay-spec.md`
- `docs/specs/mvp1-acceptance-scenarios.md`
- `tests/fixtures/replay/mvp1/manifest.index.json`

## MVP-2 scope

MVP-2 includes:

- Demo Tool Executor with progressive invocation events.
- Demo backend sandbox state for memo, alarm, flashlight, weather, and mock webSearch.
- Tool manifests and sandbox adapters that make adding later demo tools possible without changing core state machines.
- `ToolExecutionState` reducer and deterministic replay for tool lifecycle, UI patches, results, failures, retry/cancel metadata, blocked execution, and stale result behavior.
- `TOOL_UI_STATE_PATCHED` as the only frontend/demo UI state mutation path.
- Final demo requirement: a tool frontend interface must show tool progress, completion, failure, blocked state, and UI state changes caused by Tool Executor events.
- `DEMO_DESTRUCTIVE_ACTION` confirmation / authorization gate through ADR-016 current-plan confirmation state.
- Thinker-as-Composer role that emits `SPOKEN_PLAN_EMITTED` from SemanticCommitment or grounded progress.
- CommitmentCoverageCheck for SemanticCommitment-derived speech.
- ProgressTruthfulnessCheck for progress speech.
- webSearch as a Tool, but with `trust_level=UNTRUSTED_WEB_EVIDENCE` and evidence-only prompt placement.

## MVP-2 prohibited scope

MVP-2 must not implement:

- Real external write, external communication, payment, booking, real deletion, account mutation, identity mutation, credential mutation, or real device control.
- Real webSearch API by default. First pass uses mock / synthetic search result unless a human explicitly approves real read-only API work.
- Real ASR / Thinker / Slow LLM / TTS adapters as runtime integration.
- Multiple active SlowTasks.
- Pause/resume SlowTask.
- New RouterDecision beyond `FAST_ONLY`, `SPAWN_SLOW_TASK`, `PATCH_ACTIVE_SLOW_TASK`, `IGNORE`.
- New TaskFocus value beyond accepted ADR-006 values.
- New SlowTask state beyond ADR-016 MVP states.
- New MVP-relevant event names without updating ADR-002 and the canonical registry first.
- Frontend or demo backend state mutation from model text.
- Composer rewriting SlowTask facts.
- webSearch content entering instruction context or changing tool/confirmation/trace/repo policy.

## Core invariants inherited from MVP-1

- Event Journal is the source of truth for every critical state transition.
- Deterministic replay never reruns models, tools, network, clocks, random, or missing data-plane refs.
- Router is only a post-commit gate.
- UserPatch is evidence, not mutation.
- SlowTask owns complex-task facts, confirmation, resolved arguments, stale/adopted evidence, terminal outcome, and SemanticCommitment.
- Tool Executor owns tool execution, ToolExecutionState, manifest validation, argument/provenance validation, authorization, idempotency, sandbox calls, UI patches, failures, retries, cancellations, and normalized ToolResult.
- Tool Executor must not mutate SlowTask state directly.
- Old-plan ToolResult cannot advance current plan unless SlowTask emits `STALE_EVIDENCE_ADOPTED`.
- Composer cannot rewrite `immutable_facts`, `must_say_fields`, resolved arguments, tool status, risk warnings, confirmation state, or adopted stale evidence metadata.
- `DEMO_DESTRUCTIVE_ACTION` requires current-plan `CONFIRMATION_ACCEPTED` before `TOOL_EXECUTION_STARTED`.
- Shareable / GitHub fixtures must be synthetic, redacted, and minimal.

## Tool layer architecture

MVP-2 tool flow:

```text
SlowTask current-plan state
  -> resolved arguments / provenance / confirmation state
  -> Tool Executor
  -> tool manifest + side_effect_class gate
  -> sandbox adapter
  -> TOOL_PROGRESS_UPDATED / TOOL_UI_STATE_PATCHED / TOOL_RESULT_RECEIVED
  -> SlowTask evidence review and current-plan commitment
  -> Composer / checks / playback
```

Tool Executor responsibilities:

- Load and record tool manifests with `TOOL_MANIFEST_LOADED`.
- Accept partial or ready arguments through `TOOL_ARGUMENTS_PARTIAL` and `TOOL_ARGUMENTS_READY`.
- Emit `TOOL_PREVIEW_AVAILABLE` for previewable write/action tools.
- Enforce current `task_id`, `plan_version`, `task_event_seq`, resolved arguments, provenance, side-effect policy, idempotency, and confirmation requirements.
- Emit `TOOL_EXECUTION_AUTHORIZED` only after policy and confirmation gates pass.
- Emit `TOOL_EXECUTION_STARTED` only after authorization.
- Emit `TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS` when required arguments or provenance are missing.
- Emit `TOOL_UI_STATE_PATCHED` for demo backend/frontend-visible state changes.
- Emit `TOOL_RESULT_RECEIVED` with trust/source metadata.
- Emit failure, retry, and cancel events without faking unsupported cancellation success.

Initial tools:

| Tool | MVP behavior | Tool class | side_effect_class | Trust / result label | UI patch |
| --- | --- | --- | --- | --- | --- |
| `memo` | Create/list/update/delete demo notes. | demo backend state tool | create/list/update use `SANDBOX_WRITE` or `READ_ONLY`; delete/overwrite use `DEMO_DESTRUCTIVE_ACTION` | `TRUSTED_DEMO_TOOL_RESULT` | yes |
| `alarm` | Create/update/cancel demo alarms/timers. | demo schedule tool | create/update use `SANDBOX_WRITE`; cancel/overwrite use `DEMO_DESTRUCTIVE_ACTION` | `TRUSTED_DEMO_TOOL_RESULT` | yes |
| `flashlight` | Toggle simulated frontend flashlight. | demo device action | `SANDBOX_WRITE` or low-risk demo action | `TRUSTED_DEMO_TOOL_RESULT` | yes |
| `weather` | Return mock or structured read-only weather result. | read-only external/provider-style demo | `READ_ONLY` | `EXTERNAL_READ_PROVIDER_RESULT` for structured fields | optional display patch |
| `webSearch` | Return mock/synthetic search evidence. | external untrusted read | `READ_ONLY` with `EXTERNAL_READ_UNTRUSTED` tool category | `UNTRUSTED_WEB_EVIDENCE` | no direct action patch |

`webSearch` is a Tool, but it is not a trusted action source. It may produce search evidence and source refs. It must not directly patch memo/alarm/flashlight/weather state, change policy, or enter instruction context.

## Tool manifest / extensibility strategy

Tool additions should happen by adding manifest entries and sandbox adapters, not by changing Router, SlowTask lifecycle, event names, or core reducers.

Minimum manifest fields:

- `tool_name`
- `tool_adapter_id`
- `tool_manifest_version`
- `tool_category`
- `side_effect_class`
- `risk_class`
- `required_arguments`
- `optional_arguments`
- `argument_provenance_requirements`
- `result_type`
- `trust_level`
- `preview_required`
- `confirmation_required`
- `ui_patch_capable`
- `idempotency_required`
- `sandbox_state_namespace`

Extensibility rules:

- A new tool may add a new manifest and sandbox adapter.
- A new side-effect class requires ADR review if not already accepted.
- A new canonical event name requires ADR-002 and registry update before implementation.
- A tool cannot bypass Tool Executor even if its adapter is simple.
- A tool cannot call external systems unless its side-effect class and source trust model are allowed by accepted ADR.

## Frontend demo UI boundary

The final MVP-2 demo must include a tool frontend interface. The first implementation may start with backend state replay and add the frontend later in the MVP-2 slice sequence, but acceptance closeout must prove:

- Tool state is visible to the user through a frontend demo surface.
- Progress, blocked, failure, completion, and UI patch states are visible or inspectable.
- UI state changes are driven only by `TOOL_UI_STATE_PATCHED` and replayed state.
- Model text cannot directly toggle flashlight, create/delete memo, create/cancel alarm, overwrite weather display, or trigger webSearch UI action.
- `webSearch` results can be displayed as attributed evidence, but cannot directly mutate demo backend state.

## Recommended implementation slices

### Slice 0: MVP-2 fixture / replay safety skeleton

**Goal**
Create the MVP-2 fixture directory, manifest skeleton, acceptance scenario spec, and scope gates before runtime work.

**Non-goals**
No Tool Executor, demo backend, frontend, Composer, checkers, or real tools.

**Likely files**
- Create: `docs/specs/mvp2-acceptance-scenarios.md`
- Create: `tests/fixtures/replay/mvp2/manifest.index.json`
- Modify later: `tests/replay/test_fixture_safety.py`
- Modify later: `src/voice_agent/replay/scenario_assertions.py`
- Create later: `tests/acceptance/test_mvp2_acceptance_scenarios.py`

**Canonical events**
`SESSION_STARTED`, `ADAPTER_CAPABILITY_SNAPSHOT_RECORDED`, `REPLAY_STARTED`, `REPLAY_COMPLETED`.

**Replay / eval expectation**
An empty or manifest-only MVP-2 suite is deterministic, repo-safe, and synthetic. MVP-1 acceptance still rejects MVP-2-only events inside MVP-1 fixtures.

**Must-not-break MVP-1 invariants**
Do not alter MVP-1 fixture semantics or weaken MVP-1 forbidden-event gates.

### Slice 1: ToolExecutionState reducer

**Goal**
Add deterministic reducer support for progressive tool events and include `tool_execution_state_hash` in replay digest.

**Non-goals**
No execution, no demo backend calls, no UI patch application, no real API.

**Likely files**
- Create: `src/voice_agent/state/tool_execution_state.py`
- Modify: `src/voice_agent/replay/runner.py`
- Modify: `src/voice_agent/replay/state_digest.py`
- Modify: `docs/specs/state-reducers.md`
- Create: `tests/state/test_tool_execution_state.py`
- Create: `tests/replay/test_tool_execution_replay_mvp2.py`

**Canonical events**
`TOOL_CALL_STARTED`, `TOOL_MANIFEST_LOADED`, `TOOL_ARGUMENTS_PARTIAL`, `TOOL_ARGUMENTS_READY`, `TOOL_PREVIEW_AVAILABLE`, `TOOL_EXECUTION_AUTHORIZED`, `TOOL_EXECUTION_STARTED`, `TOOL_PROGRESS_UPDATED`, `TOOL_UI_STATE_PATCHED`, `TOOL_RESULT_RECEIVED`, `TOOL_EXECUTION_FAILED`, `TOOL_CALL_RETRYING`, `TOOL_EXECUTION_CANCEL_REQUESTED`, `TOOL_EXECUTION_CANCELLED`, `TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS`.

**Replay / eval expectation**
Replay reconstructs tool lifecycle state from recorded events only.

**Must-not-break MVP-1 invariants**
Old-plan `TOOL_RESULT_RECEIVED` still follows stale policy. `task_event_seq` remains monotonic and is not reused.

### Slice 2: demo Tool Executor skeleton

**Goal**
Implement the Tool Executor shell: manifest loading, argument/provenance validation, side-effect policy, authorization, idempotency, and controlled sandbox adapter dispatch.

**Non-goals**
No real external side effects, no frontend implementation yet, no real webSearch.

**Likely files**
- Create: `src/voice_agent/tools/`
- Create: `src/voice_agent/demo_backend/`
- Create: `tests/tools/test_demo_tool_executor_mvp2.py`
- Modify: `tests/fixtures/replay/mvp2/manifest.index.json`

**Canonical events**
`TOOL_MANIFEST_LOADED`, `TOOL_ARGUMENTS_PARTIAL`, `TOOL_ARGUMENTS_READY`, `TOOL_PREVIEW_AVAILABLE`, `TOOL_EXECUTION_AUTHORIZED`, `TOOL_EXECUTION_STARTED`, `TOOL_PROGRESS_UPDATED`, `TOOL_RESULT_RECEIVED`, `TOOL_EXECUTION_FAILED`, `TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS`.

**Replay / eval expectation**
At least one low-risk sandbox tool can emit progressive events, and blocked insufficient arguments emits blocked event without execution.

**Must-not-break MVP-1 invariants**
Tool Executor must not mutate SlowTask state directly and must not bypass current-plan binding.

### Slice 3: `TOOL_UI_STATE_PATCHED` and demo backend/frontend state replay

**Goal**
Make demo backend/frontend-visible state changes replayable through `TOOL_UI_STATE_PATCHED`.

**Non-goals**
No direct model-driven UI mutation, no real device control, no production frontend scope.

**Likely files**
- Modify: `src/voice_agent/state/tool_execution_state.py`
- Modify: `src/voice_agent/demo_backend/`
- Create: `tests/tools/test_tool_ui_state_patch_mvp2.py`
- Create: `tests/replay/test_tool_ui_state_replay_mvp2.py`
- Create later: minimal frontend demo files when product surface begins

**Canonical events**
`TOOL_EXECUTION_STARTED`, `TOOL_PROGRESS_UPDATED`, `TOOL_UI_STATE_PATCHED`, `TOOL_RESULT_RECEIVED`.

**Replay / eval expectation**
Replay reconstructs demo UI/backend state from recorded patch refs or synthetic patch substitutes.

**Must-not-break MVP-1 invariants**
UI patch remains Tool Executor-owned. SlowTask sees tool status/result only through journaled evidence.

### Slice 4: memo / alarm / flashlight / weather / webSearch demo tools

**Goal**
Implement the five first tools through manifests and sandbox adapters.

**Non-goals**
No real search API, no real weather API unless explicitly approved later, no external writes, no real device control.

**Likely files**
- Modify: `src/voice_agent/tools/`
- Modify: `src/voice_agent/demo_backend/`
- Create: `tests/tools/test_memo_tool_mvp2.py`
- Create: `tests/tools/test_alarm_tool_mvp2.py`
- Create: `tests/tools/test_flashlight_tool_mvp2.py`
- Create: `tests/tools/test_weather_tool_mvp2.py`
- Create: `tests/tools/test_websearch_tool_mvp2.py`
- Create: `tests/replay/test_demo_tools_replay_mvp2.py`

**Canonical events**
Tool manifest, argument, authorization, execution, progress, UI patch, result, failure, and blocked events from the canonical registry.

**Replay / eval expectation**
Each tool has at least one synthetic deterministic replay case. webSearch fixture uses synthetic search result with `trust_level=UNTRUSTED_WEB_EVIDENCE` and source refs.

**Must-not-break MVP-1 invariants**
Tool result plan binding remains current-plan unless explicitly stale. webSearch cannot become instruction.

### Slice 5: `DEMO_DESTRUCTIVE_ACTION` confirmation gate

**Goal**
Ensure delete/overwrite/cancel style demo actions require current-plan confirmation before execution.

**Non-goals**
No real deletion, no raw-text confirmation shortcut, no new confirmation scope, no pause/resume.

**Likely files**
- Modify: `src/voice_agent/tools/`
- Modify: `src/voice_agent/slowtask/` only if existing confirmation helpers need MVP-2 compatibility
- Create: `tests/tools/test_demo_destructive_confirmation_mvp2.py`
- Create: `tests/replay/test_demo_destructive_confirmation_replay_mvp2.py`

**Canonical events**
`CONFIRMATION_REQUIRED`, `WAITING_FOR_USER_CONFIRMATION`, `USER_CONFIRMATION_RECEIVED`, `CONFIRMATION_ACCEPTED`, `CONFIRMATION_REJECTED`, `TOOL_EXECUTION_AUTHORIZED`, `TOOL_EXECUTION_STARTED`, `TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS`, `TOOL_RESULT_RECEIVED`.

**Replay / eval expectation**
Missing confirmation blocks execution. Accepted current-plan confirmation authorizes execution. Superseded or rejected confirmation blocks execution.

**Must-not-break MVP-1 invariants**
Confirmation remains SlowTask-owned and invalidates on plan advance.

### Slice 6: Thinker-as-Composer / `SPOKEN_PLAN_EMITTED`

**Goal**
Add a Composer role contract that turns SemanticCommitment or grounded progress into a SpokenPlan.

**Non-goals**
No unchecked playback, no fact rewrite, no direct external model call outside adapter, no coverage/truthfulness pass bypass.

**Likely files**
- Create: `src/voice_agent/composer/`
- Modify or create: `src/voice_agent/adapters/` only for mock adapter role contract
- Create: `tests/composer/test_thinker_as_composer_mvp2.py`
- Create: `tests/replay/test_spoken_plan_replay_mvp2.py`

**Canonical events**
`SEMANTIC_COMMITMENT_EMITTED`, `SPOKEN_PLAN_EMITTED`, progress source events such as `PLANNING_STARTED`, `WAITING_FOR_SLOT`, `TOOL_PROGRESS_UPDATED`, `WAITING_FOR_USER_CONFIRMATION`, `FINALIZING`, `SLOWTASK_FAILED`.

**Replay / eval expectation**
Replay reconstructs source commitment/progress to SpokenPlan causal chain.

**Must-not-break MVP-1 invariants**
SemanticCommitment remains SlowTask-owned. Composer cannot rewrite facts or use unadopted stale evidence.

### Slice 7: CommitmentCoverageCheck / ProgressTruthfulnessCheck

**Goal**
Gate commitment speech and progress speech before playback.

**Non-goals**
No fact creation, no merged ambiguous check event, no playback after failed check.

**Likely files**
- Create: `src/voice_agent/checks/`
- Modify: `src/voice_agent/state/playback_state.py`
- Create: `tests/checks/test_commitment_coverage_mvp2.py`
- Create: `tests/checks/test_progress_truthfulness_mvp2.py`
- Create: `tests/replay/test_composer_checks_replay_mvp2.py`

**Canonical events**
`SPOKEN_PLAN_EMITTED`, `COMMITMENT_COVERAGE_CHECK_PASSED`, `COMMITMENT_COVERAGE_CHECK_FAILED`, `PROGRESS_TRUTHFULNESS_CHECK_PASSED`, `PROGRESS_TRUTHFULNESS_CHECK_FAILED`, `PLAYBACK_SPAN_STARTED`.

**Replay / eval expectation**
Failed check blocks playback. Passed check is traceable from `PLAYBACK_SPAN_STARTED.approved_check_event_id` or equivalent causal chain.

**Must-not-break MVP-1 invariants**
Progress is grounded in actual state events. Composer cannot turn dry-run/preview into executed action.

### Slice 8: MVP-2 acceptance runner

**Goal**
Create a single MVP-2 acceptance runner over synthetic scenarios.

**Non-goals**
No product service startup, no real model/tool success claim, no MVP-3 adapter integration.

**Likely files**
- Modify: `docs/specs/mvp2-acceptance-scenarios.md`
- Modify: `tests/fixtures/replay/mvp2/manifest.index.json`
- Create: `tests/acceptance/test_mvp2_acceptance_scenarios.py`
- Modify: `src/voice_agent/replay/scenario_assertions.py`

**Canonical events**
All MVP-2 tool, confirmation, Composer/check, stale policy, and replay events used by the suite.

**Replay / eval expectation**
Acceptance proves tool lifecycle replay, UI patch replay, sandbox-only behavior, webSearch evidence boundary, destructive confirmation, Composer fact boundary, truthful progress, and repo-safe fixtures.

**Must-not-break MVP-1 invariants**
MVP-1 acceptance remains green and continues to reject MVP-2-only behavior in MVP-1 fixtures.

## MVP-2 exit criteria

- `ToolExecutionState` replays progressive tool lifecycle without executing tools.
- memo, alarm, flashlight, weather, and webSearch have manifests and sandbox adapters.
- Tool Executor enforces current-plan binding, required arguments, provenance, side-effect policy, idempotency, and confirmation gates.
- `TOOL_UI_STATE_PATCHED` is the only frontend/demo UI mutation path.
- Final demo has a tool frontend interface with visible progress, completion, failure, blocked, and UI patch feedback.
- webSearch is a Tool but is always `UNTRUSTED_WEB_EVIDENCE`, evidence-only, and synthetic/mock in first pass.
- `DEMO_DESTRUCTIVE_ACTION` cannot start without current-plan `CONFIRMATION_ACCEPTED`.
- Old-plan progressive ToolResult follows stale policy and cannot advance current state without `STALE_EVIDENCE_ADOPTED`.
- Composer emits `SPOKEN_PLAN_EMITTED` without rewriting SemanticCommitment facts.
- Coverage/truthfulness checks gate playback.
- MVP-2 acceptance scenarios pass through `./scripts/test`.
- MVP-0 and MVP-1 acceptance remain passing.
- No ADR update is needed to explain implemented behavior.

## Stop-and-update-ADR conditions

Stop implementation and update accepted ADRs before proceeding if MVP-2 work needs any of the following:

- A new MVP-relevant event name.
- A new RouterDecision.
- A new TaskFocus value.
- A new SlowTask state.
- Multiple active SlowTasks.
- Pause/resume.
- Real external side-effect tools.
- Production privacy/auth policy.
- Real external write, external communication, booking/payment, real deletion, account/device/credential mutation.
- Direct frontend mutation by model text.
- webSearch content used as instruction.
- Composer allowed to rewrite SemanticCommitment facts.
- Tool Executor allowed to mutate SlowTaskState directly.
- Raw audio, raw trace, secrets, unredacted real user input, unredacted real ToolResult, or large raw web content in committed fixtures.
