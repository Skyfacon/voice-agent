# Model Spike Tool Executor Event Mapping 2026-05-18

## 0. Status

- Status: `research_only_tool_executor_event_mapping`
- Date: 2026-05-18
- Lane: model spike research
- Contract snapshot: observed `main@ced2077`
- Historical evidence snapshot: 2026-05-11/12 model spike artifacts remain historical `main@61e6afc` unless explicitly re-mapped.

本文只做 research-only mapping。它不实现 runtime adapter，不连接真实 provider，不运行真实麦克风或播放设备，不采集真实用户录音，不修改 `src/voice_agent/`、`tests/`、`docs/adr/`、`docs/specs/`，也不承诺任何 MVP3 runtime behavior。

## 1. 当前分支 / git 状态 / observed main snapshot

只读观察到的本地状态：

```text
git status --short --branch
## research/model-spikes...origin/research/model-spikes [ahead 18, behind 3]
 M docs/research/model-spike-integration-ledger.md
 ?? docs/research/model-spike-adapter-profile-hardening-checklist-2026-05-12.md
 ?? docs/research/model-spike-count-reconciliation-2026-05-18.md
 ?? docs/research/model-spike-mainline-sync-2026-05-17.md
 ?? docs/research/model-spike-mainline-sync-2026-05-18.md
 ?? docs/research/model-spike-mvp3-readiness-review-2026-05-18.md
 ?? docs/research/model-spike-phase-summary-2026-05-11.md
 ?? docs/research/model-spike-phase-summary-2026-05-12.md
 ?? docs/research/profiles/
 ?? docs/research/spikes/...
 ?? tools/
```

Observed main:

```text
git rev-parse --short main
ced2077
```

Observed `main` top commits:

```text
ced2077 Merge pull request #22 from Skyfacon/mvp2/slice3-tool-ui-state-patch
0d2870f fix: harden MVP2 UI patch replay validation
6f6e549 feat: add MVP2 tool UI state replay
f325483 Merge pull request #21 from Skyfacon/mvp2/slice2-demo-tool-executor-skeleton
a52585b fix: harden MVP2 tool executor policy gates
2c7a567 feat: add MVP2 demo tool executor skeleton
5741ae3 Merge pull request #20 from Skyfacon/mvp2/slice1-tool-execution-state
de71948 feat: add MVP2 tool execution replay state
ac1b43f Merge pull request #19 from Skyfacon/mvp2/slice0-replay-safety
0cdb7c8 test: add MVP2 replay safety skeleton
49897e8 docs: add MVP2 backlog and acceptance skeleton
a88a086 docs: add MVP2 backlog and acceptance skeleton
```

Interpretation:

- 当前分支符合预期：`research/model-spikes`。
- 工作区已有既存 research lane 改动，本文件只新增本线程文档。
- 本线程观察到的 main 是 `main@ced2077`，不是旧 addendum 中的 `main@f325483`。
- `ced2077` 已包含 Slice 3 Tool UI State Patch / UI patch replay validation，因此本 mapping 必须覆盖 `TOOL_UI_STATE_PATCHED` 和 replay from `patch_ref`。

## 2. 当前 main contract delta

相对 2026-05-18 mainline sync addendum 记录的 `main@f325483`，本线程只读观察到的实际 main 为 `main@ced2077`。

| Delta | 只读观察 | Mapping 影响 |
| --- | --- | --- |
| `de71948` / `5741ae3` | `ToolExecutionState` reducer and replay state 已进入 main。 | Tool-like model evidence 不能只写 conceptual proposal，必须映射到 replayable tool lifecycle fields。 |
| `2c7a567` / `a52585b` / `f325483` | `DemoToolExecutor` skeleton、manifest validation、current-plan policy gate、idempotency gate、blocked insufficient argument path 已进入 main。 | `TOOL_EXECUTION_STARTED` 只能来自 Tool Executor policy gate，不来自 model/provider output。 |
| `6f6e549` / `0d2870f` / `ced2077` | `TOOL_UI_STATE_PATCHED` replay and validation 已进入 main；`DemoUIState` 从 `patch_ref` 重建 demo UI/backend state。 | UI mutation mapping 必须绑定 `ui_patch_id`、`idempotency_key`、`patch_ref`，并说明 replay 不执行 backend/tool/frontend。 |

Important caveat:

- `main:docs/implementation/mvp2-backlog.md` 的开头仍有 “runtime 尚未实现这些能力” 的历史状态语言。
- 但只读 grep / `git show main:src/voice_agent/state/tool_execution_state.py` / `git show main:src/voice_agent/tools/executor.py` / MVP2 fixtures and tests 显示当前 `main@ced2077` 已有 `ToolExecutionState`、`DemoToolExecutor`、`DemoUIState`、UI patch replay fixture/test。
- 本文按 observed implementation + current canonical specs 解释，不修改 backlog/spec/ADR。

结论：本 mapping 不需要把 `ced2077` 当成 “超过预期但未同步” 的 blocker。它需要记录 `f325483 -> ced2077` delta，并建议后续如要更新旧 sync 文档，另开 research-only sync thread。

## 3. 本 mapping 的范围和非目标

In scope:

- 将 model spike research evidence 映射到当前 observed main 的 MVP2 Tool Executor events、`ToolExecutionState`、UI patch replay contract。
- 明确哪些 evidence 可作为 Tool Executor upstream input，哪些只能作为 planning hint，哪些是 No-Go mapping。
- 形成后续 Composer/checker mapping 和 Slow LLM current-plan/stale metadata hardening 的输入。

Out of scope:

- 不实现 runtime adapter。
- 不接真实 provider。
- 不运行真实麦克风、播放设备、真实 webSearch 或真实外部工具。
- 不把 synthetic/dry-run evidence 升级为 real provider readiness。
- 不新增 canonical event name。
- 不修改 `src/voice_agent/`、`tests/`、`docs/adr/`、`docs/specs/`。

## 4. MVP2 Tool Executor canonical event inventory

| Event | Observed owner / reducer | Required mapping notes |
| --- | --- | --- |
| `TOOL_MANIFEST_LOADED` | Tool Executor; `ToolExecutionState.tool_manifests` | Records manifest identity and policy metadata. Model output cannot invent manifest or side-effect class. |
| `TOOL_CALL_STARTED` | Tool Executor; optional MVP1 marker / MVP2 call marker | Summary marker only. If emitted with progressive events, must share `tool_call_id`; it is not execution. |
| `TOOL_ARGUMENTS_PARTIAL` | Tool Executor | Allowed mapping from incomplete SlowTask/tool proposal evidence; requires missing fields and `partial_arguments_ref`. |
| `TOOL_ARGUMENTS_READY` | Tool Executor | Requires current-plan resolved arguments and provenance. Model/provider output alone is not enough. |
| `TOOL_PREVIEW_AVAILABLE` | Tool Executor | Previewable action metadata only; may require confirmation. Model text preview is not authorization. |
| `TOOL_EXECUTION_AUTHORIZED` | Tool Executor | Requires current-plan policy allow or current-plan `CONFIRMATION_ACCEPTED`; may carry `confirmation_id`. |
| `TOOL_EXECUTION_STARTED` | Tool Executor | Actual sandbox execution start. Requires authorization, current plan, idempotency, allowed side-effect class. |
| `TOOL_PROGRESS_UPDATED` | Tool Executor | In-flight or completed progress metadata. It must be grounded in Tool Executor/backend state, not model prose. |
| `TOOL_UI_STATE_PATCHED` | Tool Executor; `ToolExecutionState` and `DemoUIState` | Sole frontend/demo state mutation path. Requires `ui_patch_id`, `idempotency_key`, `patch_ref`. |
| `TOOL_RESULT_RECEIVED` | Tool Executor; also consumed by SlowTask evidence state | Normalized ToolResult with `result_status`, `result_ref`, optional `trust_level`, `source_type`. |
| `TOOL_EXECUTION_FAILED` | Tool Executor | Tool execution failure metadata. No `TOOL_RESULT_RECEIVED` success should be synthesized after failure. |
| `TOOL_CALL_RETRYING` | Tool Executor | Retry metadata after retryable tool failure; not model retry self-report. |
| `TOOL_EXECUTION_CANCEL_REQUESTED` | SlowTask Runtime source; also observed by `ToolExecutionState` | Request to cancel started tool after plan advance/task cancel. Unsupported cancellation must not become fake success. |
| `TOOL_EXECUTION_CANCELLED` | Tool Executor | Cancellation result metadata with `cancel_status`; must bind to prior cancel request and started call. |
| `TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS` | Tool Executor | Hard block when arguments/provenance missing. It is not a retryable execution failure. |
| `TOOL_RESULT_MARKED_STALE` | SlowTask Runtime | Marks old-plan ToolResult stale; event `plan_version` is current plan, `result_plan_version` is original result plan. |
| `STALE_EVIDENCE_RECORDED` | SlowTask Runtime | Stores stale evidence ref after stale mark. Does not advance current plan. |
| `STALE_EVIDENCE_ADOPTED` | SlowTask Runtime | Only explicit adopt/rebase can reuse old-plan evidence; must record source and scope. |

Current observed implementation notes:

- `ToolExecutionState` accepts the canonical progressive event names above and enforces monotonic `task_event_seq` per `task_id` / `tool_call_id`.
- `DemoToolExecutor` emits manifest, argument, authorization, started, progress, UI patch, result, failed, and blocked events in journal.
- UI patch replay reconstructs `DemoUIState` from `TOOL_UI_STATE_PATCHED`, not from backend execution or ToolResult alone.

## 5. Required field matrix

| Field | Required / owner meaning | Mapping rule for model spike evidence |
| --- | --- | --- |
| `tool_call_id` | Stable id for one tool call; required by tool lifecycle and stale events. | Model proposal may suggest an intended action, but Tool Executor / owner must allocate or bind the actual `tool_call_id`. |
| `task_id` | Current SlowTask id. | Required before any Tool Executor event. ASR/Thinker/Slow LLM evidence without `task_id` remains upstream evidence only. |
| `plan_version` | Plan version for event ownership. | Tool execution must match current plan. Old result keeps original result plan and is stale until adopted. |
| `task_event_seq` | Per-task append/accept sequence. | Must be assigned at journal boundary. Model/provider output must not provide authoritative sequence. |
| `idempotency_key` | Required for write/action execution and UI patch. | Generated by Tool Executor/request owner. Model text cannot choose a replay authority key. |
| `resolved_arguments_ref` | Current-plan resolved argument data-plane ref. | Must come from SlowTask `ARGUMENTS_RESOLVED` or validated owner chain, not direct model text. |
| `provenance_ref` | Provenance for resolved arguments. | ASR/Thinker/Slow LLM may contribute evidence refs; SlowTask/Tool Executor validate provenance before ready/execution. |
| `authorization_event_id` | Link from start to authorization. | Required or inferred from caused-by for `TOOL_EXECUTION_STARTED`; model output cannot authorize itself. |
| `confirmation_id` | Current-plan confirmation id for risky/destructive/final argument gate. | Must originate from SlowTask confirmation chain. Provider “sure” / model “confirmed” text is not confirmation. |
| `ui_patch_id` | Stable id for replayed UI patch. | Generated by demo backend/Tool Executor path; must not expose raw content. |
| `patch_ref` | Structured ref used to reconstruct demo UI/backend state. | Must be synthetic/minimal/redacted; replay parses namespace/operation from `patch://synthetic/...`. |
| `result_ref` | Normalized result ref. | Tool Executor owns result normalization. Provider/model payload refs remain redacted evidence until normalized. |
| `trust_level` | Result trust class, such as `TRUSTED_DEMO_TOOL_RESULT` or `UNTRUSTED_WEB_EVIDENCE`. | Mandatory for webSearch/RAG boundary. Model cannot upgrade untrusted evidence to trusted. |
| `source_type` | Source class, such as `DEMO_SANDBOX`, `READ_ONLY_EXTERNAL`, `EXTERNAL_READ_UNTRUSTED`. | Must be manifest/tool policy output. webSearch/RAG uses `EXTERNAL_READ_UNTRUSTED`. |

## 6. Model spike evidence to Tool Executor event mapping

| Evidence family | Evidence label | May map to Tool Executor events | Upstream evidence only | Forbidden / No-Go mapping |
| --- | --- | --- | --- | --- |
| Slow LLM tool proposal | `observed_real` for proposal shape; `synthetic_eval` for dry-run boundaries | `TOOL_ARGUMENTS_PARTIAL`, `TOOL_ARGUMENTS_READY` only after SlowTask resolves/proves arguments; possible `TOOL_PREVIEW_AVAILABLE` after Tool Executor review | Missing slots, confirmation-needed flag, proposed tool name/arguments, schema validation result | No `TOOL_EXECUTION_AUTHORIZED`, no `TOOL_EXECUTION_STARTED`, no UI patch, no ToolResult, no confirmation acceptance from model output. |
| Slow LLM stale / late result | `synthetic_eval`; some timeout is `observed_degraded` | `TOOL_RESULT_MARKED_STALE`, `STALE_EVIDENCE_RECORDED`, optionally `STALE_EVIDENCE_ADOPTED` only by SlowTask | Late validated output, retry/timeout/cancel metadata, original request refs | No current-plan advance before adopt/rebase; no fake provider cancellation success. |
| Slow LLM web evidence proposal | `observed_real` for untrusted boundary shape; `synthetic_eval` for retry cases | If represented as webSearch Tool: `TOOL_RESULT_RECEIVED(source_type=EXTERNAL_READ_UNTRUSTED, trust_level=UNTRUSTED_WEB_EVIDENCE)` after Tool Executor ownership | Query intent, source refs, untrusted snippets/summaries | No web instruction to policy mutation; no raw large web content; no trusted result upgrade. |
| Thinker tool proposal evidence | `observed_real` for proposal-only deltas; `synthetic_eval` for boundary cases | Same as Slow LLM proposal: at most argument partial/ready input after owner validation | Intent hints, slot hints, uncertainty, provenance refs | No provider-native tool delta as Tool Executor event; no model-owned authorization/execution/UI patch. |
| Thinker / ASR transcript or slot evidence that later affects tools | ASR: `observed_real`, `observed_degraded`, `synthetic_eval`; Thinker: `observed_real`, `unknown`, `synthetic_eval` | None directly. After SlowTask review, may support `ARGUMENTS_RESOLVED`, then Tool Executor can emit `TOOL_ARGUMENTS_READY` | Transcript text projection, slot hints, conflict/missing-slot evidence, non-speech risk | ASR/Thinker cannot emit Tool Executor events or choose field winners. |
| TTS playback / truncate evidence | `observed_real` for synthesis/stream chunks; `synthetic_eval` for playback/truncate shape; `observed_degraded` for client close | Mostly none. Tool progress speech may later be Composer/check input, not Tool Executor-owned TTS evidence | Playback progress, truncate proof, audio synthesis metadata | TTS provider close is not `TOOL_EXECUTION_CANCELLED`, not `TOOL_UI_STATE_PATCHED`, not tool result, not user acknowledgement. |
| Duplex / VAD barge-in evidence | local `observed_real` / `observed_degraded`; WebRTC harness `synthetic_eval` | None | `BARGE_IN_CANDIDATE`, interrupt/truncate chain evidence owned by Duplex/Interaction/Talker | No Tool Executor mapping; no semantic close/directedness authority; no UI patch/tool cancel inference. |
| webSearch / RAG untrusted evidence | standalone count `unknown`; embedded boundary evidence `observed_real` / `synthetic_eval` | webSearch Tool path: manifest, args ready, authorized/read-only started, progress, `TOOL_RESULT_RECEIVED` with untrusted labels | Query, source refs, redacted summary/snippet, injection-risk metadata | No instruction placement, no policy mutation, no direct backend/UI action, no large raw web content. |

## 7. Domain-specific mapping boundaries

### Slow LLM

- 可映射：tool proposal after validation may support `TOOL_ARGUMENTS_PARTIAL`; after SlowTask current-plan `ARGUMENTS_RESOLVED`, Tool Executor may emit `TOOL_ARGUMENTS_READY`.
- Upstream only：schema validation, bounded repair, timeout, context degradation, missing/conflicting evidence, stale/late result metadata.
- Forbidden：model-owned tool execution, authorization, confirmation, UI mutation, terminal task outcome, direct SlowTask state mutation.
- Evidence labels：validated JSON / bounded repair / tool proposal shape are historical `observed_real`; timeout is `observed_degraded`; stale/adoption and retry matrices are `synthetic_eval`; provider-confirmed cancellation remains `unknown`.

### Thinker

- 可映射：Thinker tool proposal evidence can become Tool Executor input only after SlowTask/Tool Executor validation.
- Upstream only：SemanticFrame, intent hints, slot hints, uncertainty, ASR/Thinker conflict, web evidence separation.
- Forbidden：SemanticCommitment, resolved arguments, Router field winner, confirmation, tool authorization, ToolResult, UI patch.
- Evidence labels：SemanticFrame and proposal-only shape are historical `observed_real`; semantic close and assistant directedness are `unknown` as evidence and `unsupported` as authority; boundary cases are `synthetic_eval`.

### ASR

- 可映射：none directly to Tool Executor.
- Upstream only：transcript/timestamp evidence may support SlowTask evidence review and later `ARGUMENTS_RESOLVED`.
- Forbidden：ASR transcript as resolved argument fact, confirmation, tool authorization, ToolResult, UI patch.
- Evidence labels：final transcript / response streaming / filetrans timestamps are historical `observed_real`; non-speech and timeout are `observed_degraded`; realtime mic input remains `unknown`.

### TTS / Talker

- 可映射：none directly to Tool Executor lifecycle.
- Upstream only：Tool progress or result may later be spoken by Composer/checker/Talker, but TTS provider evidence is not Tool Executor ownership.
- Forbidden：provider stream close as cancellation success, playback committed as user acknowledgement, provider output as `TOOL_UI_STATE_PATCHED`.
- Evidence labels：basic synthesis and streaming audio are historical `observed_real`; client close is `observed_degraded`; playback/truncate event shape is `synthetic_eval`; provider-confirmed cancellation is `unknown`.

### Duplex / VAD

- 可映射：none to Tool Executor.
- Upstream only：barge-in and interrupt/truncate chains belong to Duplex, Interaction Controller, and Talker.
- Forbidden：VAD result as tool cancel request, UI patch, or semantic/directness final authority.
- Evidence labels：WebRTC local frame decisions have local `observed_real` for frame decisions and `observed_degraded` for limits; harness counts are `synthetic_eval`; semantic close/directedness are `unknown` or `unsupported` as authority.

### webSearch / RAG

- 可映射：as Tool only, with `TOOL_RESULT_RECEIVED(source_type=EXTERNAL_READ_UNTRUSTED, trust_level=UNTRUSTED_WEB_EVIDENCE)`.
- Upstream only：search query, source refs, short redacted/synthetic summary, redaction status.
- Forbidden：web content as instruction, policy mutation, confirmation policy mutation, trace/repo/ADR rule mutation, direct UI/backend action.
- Evidence labels：no standalone real suite count; embedded boundary observations are `observed_real` or `synthetic_eval`; real external fetch in MVP2 remains `unsupported` without human approval.

## 8. Current-plan / stale-result mapping

### MVP1 minimal marker variant

MVP1 replay may use only a minimal marker shape:

```text
TOOL_CALL_STARTED(plan_version=N)
USER_PATCH_RECEIVED(observed_plan_version=N)
USER_PATCH_INTERPRETED(interpreted_against_plan_version=N, materially_changes_task=true)
PLAN_VERSION_ADVANCED(to_plan_version=N+1)
TOOL_RESULT_RECEIVED(plan_version=N)
TOOL_RESULT_MARKED_STALE(result_plan_version=N, current_plan_version=N+1)
STALE_EVIDENCE_RECORDED
optional STALE_EVIDENCE_ADOPTED
```

Mapping rule:

- `TOOL_CALL_STARTED` is not execution.
- Old-plan result keeps `result_plan_version=N`.
- Stale marker event uses `plan_version=N+1` and `current_plan_version=N+1`.
- No current-plan SemanticCommitment or tool-based progress is valid before `STALE_EVIDENCE_ADOPTED`.

### MVP2 progressive executor variant

MVP2 may include:

```text
TOOL_EXECUTION_STARTED(plan_version=N)
USER_PATCH_RECEIVED(observed_plan_version=N)
USER_PATCH_INTERPRETED(interpreted_against_plan_version=N, materially_changes_task=true)
PLAN_VERSION_ADVANCED(to_plan_version=N+1)
optional TOOL_EXECUTION_CANCEL_REQUESTED(plan_version=N+1)
TOOL_RESULT_RECEIVED(plan_version=N)
TOOL_RESULT_MARKED_STALE(result_plan_version=N, current_plan_version=N+1)
STALE_EVIDENCE_RECORDED
optional STALE_EVIDENCE_ADOPTED
```

Mapping rule:

- `tool_call_id` links old execution/result/stale evidence.
- `task_event_seq` remains monotonic and must not be reused from the original execution.
- Unsupported cancellation must be recorded as unsupported/degraded metadata, not as `TOOL_EXECUTION_CANCELLED(cancel_status=success)`.
- Adoption/rebase is SlowTask-owned. Tool Executor and model output cannot adopt stale evidence into current plan.

## 9. UI patch replay mapping

Owner:

- `TOOL_UI_STATE_PATCHED` is Tool Executor-owned.
- `DemoUIState` reconstructs demo UI/backend state from recorded patch events.
- Replay must not execute demo backend, frontend callbacks, tools, models, clocks, random sources, or network.

Required fields:

- `tool_call_id`
- `task_id`
- `plan_version`
- `task_event_seq`
- `ui_patch_id`
- `idempotency_key`
- `patch_ref`

Observed current-main replay behavior:

- Patch refs use structured synthetic refs such as `patch://synthetic/demo_backend/memo/create/<ui_patch_id>`.
- Replay parses namespace and operation from `patch_ref`.
- Duplicate `ui_patch_id` is accepted only if the entire patch metadata and task binding match.
- A `TOOL_RESULT_RECEIVED` without `TOOL_UI_STATE_PATCHED` does not reconstruct demo UI state.
- `TOOL_UI_STATE_PATCHED` requires prior `TOOL_EXECUTION_STARTED` and a UI-capable manifest.

Why model text / provider output cannot directly patch UI:

- Model text lacks Tool Executor policy gates, idempotency, manifest validation, current-plan binding, and replayable patch refs.
- Direct frontend mutation would bypass Event Journal and deterministic replay.
- A provider payload may be evidence or a normalized tool result source, but not a UI state mutation event.

## 10. webSearch as Tool mapping

Required mapping:

- `tool_name=webSearch`
- `tool_category=EXTERNAL_READ_UNTRUSTED`
- `side_effect_class=READ_ONLY`
- `source_type=EXTERNAL_READ_UNTRUSTED`
- `trust_level=UNTRUSTED_WEB_EVIDENCE`
- first pass mode: mock or synthetic unless human explicitly approves real read-only API work.

Prompt placement:

- webSearch/RAG content goes into evidence area only.
- It must not enter instruction area.
- It must carry source refs, redaction status, and untrusted label.

Fixture policy:

- No raw large web content.
- No unredacted real user input.
- No secrets, cookies, auth headers, or credential-bearing URL/body.
- Synthetic or redacted summaries/snippets only.

No policy mutation:

- Webpage/search result instructions cannot alter tool policy, confirmation policy, trace/replay policy, repo policy, ADR policy, or AGENTS rules.
- webSearch cannot directly trigger memo/alarm/flashlight/weather UI/backend action.

## 11. Inputs for later Composer/checker mapping matrix

This Tool Executor mapping hands off the following constraints:

- Composer may speak tool progress only from grounded source events such as `TOOL_PROGRESS_UPDATED`, `TOOL_UI_STATE_PATCHED`, `TOOL_RESULT_RECEIVED`, `WAITING_FOR_TOOL`, or `SLOWTASK_FAILED`.
- Composer must not say a tool executed before `TOOL_EXECUTION_STARTED`.
- Composer must not say UI state changed before `TOOL_UI_STATE_PATCHED`.
- Composer must not express old-plan ToolResult as current fact unless `STALE_EVIDENCE_ADOPTED` exists.
- webSearch evidence must be attributed or degraded in speech and must remain `UNTRUSTED_WEB_EVIDENCE`.
- Playback still needs `SPOKEN_PLAN_EMITTED` -> coverage/truthfulness check -> `PLAYBACK_SPAN_STARTED(approved_check_event_id=...)` where required.

## 12. Inputs for Slow LLM current-plan/stale metadata hardening

Next Slow LLM hardening should require each tool-adjacent observation to record:

- `contract_snapshot=main@ced2077` or newer.
- historical source snapshot for reused 2026-05-11/12 evidence.
- `task_id`, `plan_version`, `task_event_seq`, `tool_call_id` where tool-related.
- `result_plan_version` and `current_plan_version` for late ToolResult-like output.
- whether output is proposal, resolved argument evidence, stale evidence, retry metadata, failure metadata, or unsupported.
- `idempotency_key` only after Tool Executor/request owner allocates it.
- `resolved_arguments_ref` and `provenance_ref` only after SlowTask owner validation.
- `trust_level` and `source_type` for any external/web evidence.
- explicit `may_advance_current_task=false` unless SlowTask current-plan owner emits the relevant event.

No-Go hardening claims:

- “Slow LLM can execute tool” from provider-native output.
- “Slow LLM can patch UI” from generated text.
- “Late old-plan result can be reused” without `STALE_EVIDENCE_ADOPTED`.
- “Client abort proves provider cancellation.”
- “webSearch evidence can update policy.”

## 13. Go / No-Go checklist

| Decision | Status | Reason |
| --- | --- | --- |
| Use `main@ced2077` as current Tool Executor mapping snapshot | Go | Observed main is `ced2077`; Slice 3 UI patch replay is present. |
| Reuse 2026-05-11/12 model spike evidence as historical inputs | Go with label | Must preserve historical `main@61e6afc` and evidence labels. |
| Treat Slow LLM / Thinker tool proposal as Tool Executor input | Conditional Go | Only after SlowTask/Tool Executor validation and current-plan binding. |
| Treat ASR transcript/Thinker slots as direct tool arguments | No-Go | They are evidence, not resolved arguments. |
| Treat model/provider output as `TOOL_EXECUTION_AUTHORIZED` | No-Go | Authorization is Tool Executor + SlowTask confirmation/policy owned. |
| Treat model/provider output as `TOOL_EXECUTION_STARTED` | No-Go | Execution starts only after Tool Executor gates. |
| Treat model/provider output as `TOOL_UI_STATE_PATCHED` | No-Go | UI patch is Tool Executor-owned and replayed from `patch_ref`. |
| Treat TTS provider close as tool cancellation | No-Go | TTS playback/truncate is Talker/Interaction-owned, not Tool Executor cancellation. |
| Treat VAD barge-in as tool cancel request | No-Go | Duplex/Interaction/Talker chain is separate from Tool Executor. |
| Map webSearch/RAG as untrusted Tool evidence | Conditional Go | Must be `EXTERNAL_READ_UNTRUSTED` / `UNTRUSTED_WEB_EVIDENCE`, synthetic/mock first pass. |
| Runtime adapter implementation from this document | No-Go | Research-only mapping does not authorize runtime integration. |

## 14. Human approval gates

Human approval is required before:

- Editing `src/voice_agent/`, `tests/`, `docs/adr/`, or `docs/specs/`.
- Updating accepted ADRs or canonical event registry/specs.
- Implementing runtime adapters or connecting real providers.
- Running real microphone, playback-device, real webSearch, or external tool experiments.
- Capturing, storing, or committing raw audio, generated audio, raw trace, local replay cache, secrets, cookies, credentials, auth headers, real user input, or large raw web content.
- Turning research evidence into MVP3 planning claims without current-main event mapping and replay/eval proof.
- Promoting webSearch/RAG from untrusted evidence to trusted instruction or policy input.

## 15. Summary

At observed `main@ced2077`, MVP2 Tool Executor mapping must be concrete:

- Tool Executor owns manifest, arguments, authorization, execution, progress, UI patch, result, failure, retry, and cancellation result events.
- SlowTask owns current-plan facts, confirmation, stale marking, stale recording, and adoption/rebase.
- `TOOL_UI_STATE_PATCHED` is the only demo UI/backend mutation path and replays from `patch_ref`.
- Model spike evidence can support planning and upstream evidence review, but cannot itself become Tool Executor-owned runtime events.
- webSearch/RAG remains `UNTRUSTED_WEB_EVIDENCE`, evidence-only, synthetic/mock by default, and unable to mutate policy or UI.

Recommended next threads:

1. Composer/checker mapping matrix against `SPOKEN_PLAN_EMITTED`, coverage/truthfulness checks, and playback gates.
2. Slow LLM current-plan/stale metadata hardening against `main@ced2077`.
3. Optional research-only sync addendum that updates old `f325483` wording to observed `ced2077` if the project wants a standalone mainline sync record.
