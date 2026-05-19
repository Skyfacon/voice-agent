# Model Spike Mainline Sync Addendum 2026-05-18

## 0. Status

- Status: `research_only_contract_sync_addendum`
- Date: 2026-05-18
- Lane: model spike research
- Scope: sync research interpretation from the 2026-05-17 baseline `main@ac1b43f` to the locally observed `main@f325483`.
- Non-goal: no runtime adapter implementation, no provider wiring, no real mic/playback, no protected production/spec/ADR edits.

This addendum is a research-only contract note. It does not approve MVP3 runtime integration. It updates the orientation baseline for later MVP3 planning, Tool Executor mapping, Composer/checker mapping, and Slow LLM metadata hardening.

## 1. 当前分支 / git 状态 / observed main snapshot

Observed local commands:

```text
git status --short --branch
## research/model-spikes...origin/research/model-spikes [ahead 18, behind 3]
 M docs/research/model-spike-integration-ledger.md
 ?? docs/research/model-spike-adapter-profile-hardening-checklist-2026-05-12.md
 ?? docs/research/model-spike-mainline-sync-2026-05-17.md
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
f325483
```

Observed `main` top commits:

```text
f325483 Merge pull request #21 from Skyfacon/mvp2/slice2-demo-tool-executor-skeleton
a52585b fix: harden MVP2 tool executor policy gates
2c7a567 feat: add MVP2 demo tool executor skeleton
5741ae3 Merge pull request #20 from Skyfacon/mvp2/slice1-tool-execution-state
de71948 feat: add MVP2 tool execution replay state
ac1b43f Merge pull request #19 from Skyfacon/mvp2/slice0-replay-safety
```

Interpretation:

- Current working branch is `research/model-spikes`.
- Local research branch is both ahead and behind origin; this addendum only observes local state and does not reconcile remote divergence.
- The current local main baseline for new model-spike planning should be recorded as `main@f325483`, unless a later thread observes a newer main.
- Existing modified/untracked research artifacts predate this addendum. This addendum only adds one new file under `docs/research/`.

## 2. 从 `main@ac1b43f` 到当前 main 的 contract delta

The 2026-05-17 sync used `main@ac1b43f` as its contract snapshot. That snapshot had MVP2 backlog, acceptance scenarios, replay safety skeleton, and event registry language, but it still treated Tool Executor runtime as not yet observed.

The locally observed `main@f325483` adds at least:

| Commit | Contract delta for research |
| --- | --- |
| `de71948` | Adds MVP2 ToolExecutionState replay state. Model spike evidence now needs to align not only to event names but also to replayable ToolExecutionState shape. |
| `5741ae3` | Merges MVP2 Slice 1. The sync baseline moves beyond "MVP2 replay safety skeleton only". |
| `2c7a567` | Adds MVP2 demo Tool Executor skeleton. Tool-like model outputs now need stricter mapping to Tool Executor-owned events and policy gates. |
| `a52585b` | Hardens MVP2 Tool Executor policy gates. Research cannot treat model-suggested actions as executable without current-plan authorization. |
| `f325483` | Merges MVP2 Slice 2. New planning baseline is ToolExecutionState plus Tool Executor skeleton, not just MVP2 docs skeleton. |

Important caveat:

- Some handoff/backlog prose on main still says MVP2 runtime is not observed. The commit log shows later MVP2 slices landed after that prose. For research planning, use `main@f325483` as the observed snapshot and treat status-language mismatch as a follow-up review item, not as permission to assume full MVP2 closeout.

## 3. MVP2 ToolExecutionState / Tool Executor skeleton 对 model spike research 的影响

The main change for model spike research is that tool-adjacent outputs must now be framed against Tool Executor ownership.

| Research output type | New interpretation at `main@f325483` |
| --- | --- |
| Slow LLM tool proposal | May be evidence for `ARGUMENTS_RESOLVED`, `TOOL_ARGUMENTS_PARTIAL`, `TOOL_ARGUMENTS_READY`, or `TOOL_PREVIEW_AVAILABLE`; it must not be treated as `TOOL_EXECUTION_AUTHORIZED`, `TOOL_EXECUTION_STARTED`, `TOOL_UI_STATE_PATCHED`, or `TOOL_RESULT_RECEIVED`. |
| Thinker intent / slots | May support routing, evidence review, ambiguity, and argument/provenance checks; it does not own Tool Executor lifecycle. |
| webSearch-like output | Must map to a ToolResult with `trust_level=UNTRUSTED_WEB_EVIDENCE` only after Tool Executor ownership; the content enters evidence, not instruction. |
| UI-action-like model text | Must not mutate frontend/demo state. Only `TOOL_UI_STATE_PATCHED` from Tool Executor can represent UI/backend demo state mutation. |
| Retry/cancel capability claims | Must separate adapter/provider behavior from Tool Executor event semantics; no fake cancel success. |

New minimum mapping fields for future profile hardening:

- `tool_call_id`
- `task_id`
- `plan_version`
- `task_event_seq`
- `idempotency_key`
- `resolved_arguments_ref`
- `provenance_ref`
- `authorization_event_id` when execution starts
- `ui_patch_id` and `patch_ref` when UI/demo state changes
- `result_status`, `result_ref`, `trust_level`, `source_type` for results

## 4. 哪些 2026-05-11/12 evidence 仍只是 historical `main@61e6afc`

The following evidence remains useful as model-behavior research, but it must be labeled historical relative to current main:

| Evidence family | Historical value | Why it is not enough for current main |
| --- | --- | --- |
| Slow LLM Qwen / DeepSeek JSON runs on 2026-05-11 | Observed structured JSON behavior and provider/degraded notes. | Captured before MVP1 closeout and before MVP2 ToolExecutionState / Tool Executor skeleton. Missing current `tool_call_id`, idempotency, authorization, stale replay mapping, and current-plan metadata proof. |
| Slow LLM retry dry run on 2026-05-12 | Synthetic eval for retry/stale/cancel taxonomy. | Needs upgrade from dry-run summary to current `main@f325483` progressive tool/stale event requirements. |
| ASR Qwen-ASR harness/dry run on 2026-05-12 | Useful synthetic frame/timestamp/cancellation harness shape. | No real realtime mic approval, no current ingress integration, and no current replay fixture proof against `f325483`. |
| TTS CosyVoice playback/truncate dry run on 2026-05-12 | Useful playback/truncate proof plan and synthetic truncate taxonomy. | Provider did not prove runtime truncation; no real playback approval; must map later speech through Composer/check gates where relevant. |
| Thinker Qwen-Omni run/harness on 2026-05-11/12 | Useful semantic-frame and modality research. | Needs current Router/UserPatch/SlowTask metadata binding and cannot bypass adapter or Interaction Controller. |
| Thinker-as-Composer boundary dry run on 2026-05-12 | Useful protected-field and coverage/truthfulness hints. | Must upgrade to current `SPOKEN_PLAN_EMITTED`, coverage/truthfulness check, and `PLAYBACK_SPAN_STARTED.approved_check_event_id` mapping. |
| Duplex/VAD WebRTC VAD runs on 2026-05-11/12 | Useful VAD timing and false-positive hints. | No real mic/playback/AEC approval; still only evidence for future Duplex candidate mapping. |

Rule: any report derived from those 2026-05-11/12 artifacts should carry `contract_snapshot=main@61e6afc` or `historical_main@61e6afc` unless re-run/re-mapped against `main@f325483`.

## 5. 哪些 2026-05-17 sync 结论仍有效，哪些需要升级到当前 main

Still valid:

- MVP3 is not approved to implement runtime adapters.
- Model spike outputs remain evidence/proposals unless routed through accepted adapter/Tool Executor boundaries.
- `main@61e6afc` evidence remains historical.
- `main@ac1b43f` is still a valid 2026-05-17 sync floor.
- SlowTask/UserPatch/ToolResult/SemanticCommitment must bind `task_id`, `plan_version`, and `task_event_seq`.
- Old-plan ToolResult cannot advance current plan without explicit stale evidence adoption/rebase.
- Composer cannot rewrite `SemanticCommitment` facts.
- webSearch remains untrusted evidence only.
- Repo-safe fixtures must be synthetic/redacted/minimal and contain no raw audio, raw trace, secrets, real user input, or large raw web content.

Needs upgrade:

| 2026-05-17 conclusion | Current upgrade at `main@f325483` |
| --- | --- |
| MVP2 is mostly planning/replay safety skeleton. | MVP2 now has observed ToolExecutionState replay state and demo Tool Executor skeleton/policy gates. |
| Tool-like output mapping can remain conceptual. | Future hardening must map to concrete Tool Executor events, state reducers, and policy gates. |
| Stale ToolResult proof can use MVP1 minimal marker shape. | Current planning must also cover MVP2 progressive executor variant. |
| Tool output needs task-bound metadata. | It also needs `tool_call_id`, `idempotency_key`, provenance refs, authorization refs, trust/source labels, and UI patch ids where applicable. |
| Composer/checker mapping can be a checklist item. | It now needs an explicit event mapping matrix against `SPOKEN_PLAN_EMITTED`, `COMMITMENT_COVERAGE_CHECK_*`, `PROGRESS_TRUTHFULNESS_CHECK_*`, and playback gating. |

## 6. 对 Slow LLM task-bound metadata 的新增复核要求

Future Slow LLM hardening must prove that model output can be transformed into replay-safe current-plan evidence without letting the model own state transitions.

Required review additions:

- Record the contract snapshot as `main@f325483` or newer.
- Separate provider output from SlowTask interpretation and Tool Executor lifecycle.
- For every action/tool-like proposal, capture whether it maps to:
  - `ARGUMENTS_RESOLVED`
  - `TOOL_ARGUMENTS_PARTIAL`
  - `TOOL_ARGUMENTS_READY`
  - `TOOL_PREVIEW_AVAILABLE`
  - `TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS`
  - stale evidence only
- Bind every accepted proposal to `task_id`, `plan_version`, `task_event_seq`, `observed_plan_version`, and `interpreted_against_plan_version` where relevant.
- Track `tool_call_id` and `idempotency_key` before any Tool Executor-owned execution path.
- Preserve `resolved_arguments_ref` and `provenance_ref`; do not inline raw sensitive content.
- Mark late results with original `result_plan_version` and current `current_plan_version`.
- Require `STALE_EVIDENCE_ADOPTED` before old-plan result evidence can enter current-plan commitment.
- Treat cancellation as capability-specific; unsupported cancellation must not become synthetic success.

No-Go condition:

- Any Slow LLM report that claims it can execute tools, patch UI, authorize side effects, or advance current-plan state by model text alone is not compatible with current main.

## 7. 对 Thinker-as-Composer / checker mapping 的新增复核要求

At `main@f325483`, Composer work must be reviewed against explicit event chains:

```text
SEMANTIC_COMMITMENT_EMITTED or progress source event
-> SPOKEN_PLAN_EMITTED
-> COMMITMENT_COVERAGE_CHECK_PASSED or PROGRESS_TRUTHFULNESS_CHECK_PASSED
-> PLAYBACK_SPAN_STARTED(approved_check_event_id=...)
```

Required mapping:

| Concern | Required event mapping |
| --- | --- |
| SemanticCommitment-derived speech | `SPOKEN_PLAN_EMITTED(source_commitment_id=..., coverage_check_required=true)` |
| Progress speech | `SPOKEN_PLAN_EMITTED(source_progress_event_ids=..., truthfulness_check_required=true)` |
| Coverage pass/fail | `COMMITMENT_COVERAGE_CHECK_PASSED` or `COMMITMENT_COVERAGE_CHECK_FAILED` |
| Progress truthfulness pass/fail | `PROGRESS_TRUTHFULNESS_CHECK_PASSED` or `PROGRESS_TRUTHFULNESS_CHECK_FAILED` |
| Playback gate | `PLAYBACK_SPAN_STARTED.approved_check_event_id` must point to the passed check event when required. |

Composer hardening must explicitly preserve:

- `immutable_facts`
- `must_say_fields`
- `resolved_arguments`
- tool status
- risk warnings
- confirmation state
- stale evidence restrictions
- demo/dry-run/real/degraded labels
- webSearch attribution and untrusted label

No-Go condition:

- Composer self-attestation cannot replace Coverage Checker or ProgressTruthfulnessCheck.

## 8. 对 Tool-like model output / webSearch / UI patch mapping 的新增复核要求

Tool-like model output:

- May propose structured arguments.
- May explain missing fields.
- May provide evidence for preview text.
- Must not authorize, start, retry, cancel, complete, or mutate tool execution.
- Must not create unregistered MVP event names.

webSearch:

- Must be represented as a Tool under Tool Executor ownership.
- Result must carry `source_type=EXTERNAL_READ_UNTRUSTED` and `trust_level=UNTRUSTED_WEB_EVIDENCE`.
- Result content enters evidence only.
- Fixture content must be mock/synthetic/redacted/minimal; no large raw web content.
- Webpage/search result instructions cannot change tool policy, confirmation policy, trace policy, ADR policy, or repo policy.

UI patch:

- Frontend/demo state mutation must be represented by `TOOL_UI_STATE_PATCHED`.
- Required fields include `tool_call_id`, `task_id`, `plan_version`, `task_event_seq`, `ui_patch_id`, `idempotency_key`, and `patch_ref`.
- Model text cannot directly drive UI state.
- Replay reconstructs UI/demo state from recorded patch refs, not from a frontend callback or tool rerun.

## 9. 对 ASR / TTS / Duplex/VAD 的影响，特别说明无 runtime integration approval

Current main changes do not approve any ASR/TTS/Duplex runtime integration.

| Domain | Impact of `main@f325483` | Boundary |
| --- | --- | --- |
| ASR | Future ASR evidence should still map through input/turn/adapter events and replay-safe refs. | No real mic, no real provider integration, no runtime adapter implementation in this lane. |
| TTS | TTS output eventually participates in playback and may depend on approved Composer/check output. | No real playback device, no raw audio, no provider truncate claim unless separately proven. |
| Duplex/VAD | VAD evidence still maps to `SPEECH_START_DETECTED`, `SPEECH_END_DETECTED`, `BARGE_IN_CANDIDATE`, directedness, semantic close, and interrupt/truncate chains. | No live mic scheduling, no AEC proof, no real playback reference capture in this lane. |

The new Tool Executor baseline mainly affects tool/action/progress speech surfaces. It does not weaken the existing audio safety boundary.

## 10. 新的 Go / No-Go gates

Go for research planning:

- Use `main@f325483` as the current contract snapshot for new model-spike addenda and mapping matrices.
- Keep `main@61e6afc` evidence as historical and useful only when labeled.
- Treat `main@ac1b43f` as the 2026-05-17 sync floor, not the newest baseline.
- Build mapping matrices for Tool Executor, Composer/checkers, and Slow LLM stale/current-plan metadata before MVP3 adapter planning.
- Continue using synthetic/redacted/minimal fixtures for any replay/eval artifacts.

Conditional Go:

- Profile hardening can proceed only if every candidate conclusion states its evidence label, contract snapshot, event mapping, and missing proof.
- Tool-like output can be promoted from research hint to planning input only after it maps cleanly to Tool Executor-owned events and policy gates.
- Composer output can be promoted only with independent coverage/truthfulness check mapping.

No-Go:

- Runtime adapter implementation.
- Real provider connection.
- Real mic or playback device run.
- Raw audio, raw trace, local replay cache, secrets, real user input, or large raw web content committed.
- Edits under `src/voice_agent/`, `tests/`, `docs/adr/`, or `docs/specs/` in this research-only thread.
- Model-owned tool execution, UI patching, confirmation, stale adoption, or Composer fact rewriting.
- Treating webSearch as instruction.

## 11. 后续线程顺序建议

Recommended order:

1. `smoke vs full_synthetic count reconciliation`
   - Reconcile dry-run summary smoke counts with the full synthetic counts already recorded in the integration ledger.
   - Output should be a research-only count table plus explanation of which counts are harness smoke, suite-level full synthetic, skipped, degraded, or unsupported.

2. `MVP2 Tool Executor event mapping matrix`
   - Map Slow LLM, Thinker, webSearch-like, and tool-like outputs to Tool Executor events at `main@f325483`.
   - Include required fields, evidence labels, No-Go states, and replay assertions.

3. `Composer/checker event mapping matrix`
   - Map Thinker-as-Composer findings to `SPOKEN_PLAN_EMITTED`, coverage checks, truthfulness checks, and playback gating.
   - Explicitly test protected-field preservation and failure branches.

4. `Slow LLM current-plan/stale metadata hardening`
   - Re-run or re-map Slow LLM dry-run evidence against current `task_id`, `plan_version`, `task_event_seq`, `tool_call_id`, idempotency, and stale/adopt rules.
   - Keep this spike-local and synthetic unless human approves a later runtime integration lane.

## 12. human approval gates

Human approval is required before:

- Syncing the research branch with origin or current main in a way that changes working tree contents.
- Editing `src/voice_agent/`, `tests/`, `docs/adr/`, or `docs/specs/`.
- Updating accepted ADRs or canonical specs.
- Implementing runtime adapters.
- Connecting any real provider endpoint.
- Running real microphone or playback-device experiments.
- Capturing, storing, or committing any raw audio, raw trace, local replay cache, secret, or real user input.
- Introducing real external side-effect tools.
- Treating webSearch as a real external fetch instead of mock/synthetic evidence.
- Promoting research hints into MVP3 planning gates without current-main event mapping and replay/eval proof.

## 13. Summary

This addendum upgrades the model spike research baseline from `main@ac1b43f` to the locally observed `main@f325483`.

The important contract delta is that MVP2 now has observed ToolExecutionState and demo Tool Executor skeleton/policy-gate commits. Therefore, tool-like model behavior, webSearch evidence, UI patches, stale ToolResult handling, and Composer speech all need concrete current-main event mapping before they can support MVP3 planning.

Runtime adapter integration remains No-Go.
