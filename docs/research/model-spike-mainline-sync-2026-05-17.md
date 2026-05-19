# Model Spike Mainline Sync Addendum

## Status

research_contract_sync_after_mvp1_closeout_and_mvp2_start

本文是 model-spike research lane 对主线程最新 contract 的同步校准。它不是 runtime implementation plan，不授权接入真实 provider，不修改 ADR / specs，不扩大 MVP scope。

## Date

2026-05-17

## Scope

In scope:

- 记录 model-spike lane 从 MVP-0 contract snapshot 更新到当前 mainline contract 的校准点。
- 明确 MVP-1 closeout 对 Slow LLM、Thinker、ASR、Composer 和 tool-proposal research 的影响。
- 明确 MVP-2 已开工后，Tool Executor、UI patch、webSearch、Composer/checker 边界对 model-spike profile hardening 的影响。
- 给下一轮 spike-local tooling 或 profile hardening 提供 Go / No-Go 判断。

Out of scope:

- No changes to `src/voice_agent/`, `tests/`, `docs/adr/`, or `docs/specs/`.
- No runtime adapter implementation.
- No real provider call.
- No real tool execution, real webSearch API, real frontend/device mutation, or real external side effect.
- No raw audio, raw trace, local replay cache, real user input, generated audio artifact, provider body, secret, token, credential, cookie, or authorization header.

## Mainline Snapshot

Observed from local git refs on 2026-05-17:

| item | commit / source | model-spike interpretation |
| --- | --- | --- |
| Previous model-spike default snapshot | `main@61e6afc` | Historical MVP-0 contract baseline remains valid for older run reports. |
| MVP-1 closeout doc commit | `4dea276 Document MVP-1 closeout architecture status` | MVP-1 mock/replay control-plane contract is no longer pending. |
| MVP-1 merged mainline point | `2f3b359 Merge pull request #17 from Skyfacon/mvp1/slice10-acceptance-closeout` | Use as MVP-1 closeout merge reference when a merge commit is preferred. |
| MVP-2 docs skeleton | `a88a086 docs: add MVP2 backlog and acceptance skeleton` | MVP-2 target scenarios are now explicit contract input for research hardening. |
| MVP-2 replay safety skeleton | `0cdb7c8 test: add MVP2 replay safety skeleton` | MVP-2 fixture safety shape exists on mainline. |
| Current observed main | `ac1b43f Merge pull request #19 from Skyfacon/mvp2/slice0-replay-safety` | New model-spike reports should reference this or a newer mainline snapshot. |

Current `research/model-spikes` is behind current `main` and still contains research-only changes. This addendum does not merge main into the research branch; it updates research coordination guidance.

## Source Evidence

Mainline docs and fixtures used for this sync:

- `main:docs/implementation/mvp1-backlog.md`
- `main:docs/implementation/mvp1-to-mvp2-handoff.md`
- `main:docs/implementation/mvp2-backlog.md`
- `main:docs/specs/mvp1-acceptance-scenarios.md`
- `main:docs/specs/mvp2-acceptance-scenarios.md`
- `main:tests/fixtures/replay/mvp2/manifest.index.json`
- `main:tests/fixtures/replay/mvp2/000-empty-mvp2-session.fixture.json`
- `main:docs/specs/event-registry.md`
- `main:docs/specs/replay-spec.md`

## Contract Delta Summary

### MVP-1 Is Now Implemented Contract

Model-spike docs that previously said "wait for MVP-1 contract" should now say "verify against MVP-1 closeout contract".

MVP-1 closeout confirms:

- `MVP1Router`, `TaskFocusState`, `SlowTaskState`, `MockSlowTaskRuntime`, and `UserPatchEvidencePackRuntime` exist in mainline.
- Single active SlowTask, UserPatch evidence pack, `plan_version`, `task_event_seq`, stale evidence, confirmation, cancel/switch, and mock SemanticCommitment are replay-validated.
- Router remains post-commit and does not interpret final UserPatch semantics.
- UserPatch remains evidence, not mutation.
- SlowTask owns `SlowTaskState`, confirmation state, resolved arguments, stale/adopted evidence, SemanticCommitment, and terminal outcome.
- Terminal states are sticky; late UserPatch, ToolResult, or confirmation cannot advance a terminal task.

MVP-1 also tightened required event bindings:

| area | current requirement for research-shaped metadata |
| --- | --- |
| `USER_PATCH_INTERPRETED` | Must include `patch_id`, `task_id`, `plan_version`, `task_event_seq`, `observed_plan_version`, `interpreted_against_plan_version`, `interpretation_type`, and `materially_changes_task`. |
| `PLAN_VERSION_ADVANCED` | Must include `task_id`, `plan_version`, `task_event_seq`, `from_plan_version`, `to_plan_version`, and `planning_reason`; event `plan_version` must equal `to_plan_version`. |
| stale result chain | `TOOL_RESULT_MARKED_STALE` and `STALE_EVIDENCE_RECORDED` now require current-plan `plan_version` and `task_event_seq`. |
| stale adoption | Old-plan evidence can affect current-plan reasoning only after `STALE_EVIDENCE_ADOPTED`, with bounded adoption metadata. |
| replay stale variants | MVP-1 uses a minimal marker variant; MVP-2 may use progressive Tool Executor events after Tool Executor gates exist. |

### MVP-2 Has Started, But Runtime Is Still In Progress

At `main@ac1b43f`, MVP-2 has backlog, acceptance scenarios, and an empty replay safety skeleton. It does not yet prove real Tool Executor runtime, demo backend, frontend UI patching, Composer runtime, or coverage/truthfulness checker runtime.

MVP-2 target scope now gives model-spike research concrete owner boundaries:

- Tool Executor owns tool execution, manifest validation, argument/provenance validation, authorization, idempotency, sandbox calls, UI patches, failures, retries, cancellations, and normalized ToolResult.
- `TOOL_UI_STATE_PATCHED` is the only frontend/demo UI mutation path.
- webSearch is a Tool, but first pass is mock/synthetic and always `UNTRUSTED_WEB_EVIDENCE`.
- `DEMO_DESTRUCTIVE_ACTION` requires current-plan `CONFIRMATION_ACCEPTED` before `TOOL_EXECUTION_STARTED`.
- Thinker-as-Composer emits `SPOKEN_PLAN_EMITTED` from SemanticCommitment or grounded progress, but cannot rewrite facts.
- CommitmentCoverageCheck and ProgressTruthfulnessCheck gate playback.

## Impact On Model-Spike Work

| domain | sync result | required calibration |
| --- | --- | --- |
| Slow LLM | Continue, but retarget from "MVP-1 pending" to implemented MVP-1 bindings. | Update future planning/stale/tool-proposal observations to include exact `task_id`, `plan_version`, `task_event_seq`, `observed_plan_version`, stale/adoption chain, and terminal late-result policy. |
| Thinker / ASR | Continue as evidence providers. | Preserve provenance and conflict; do not turn ASR/Thinker output into Router winner, SemanticCommitment, confirmation, or tool authorization. |
| Thinker-as-Composer | Priority increases because MVP-2 has explicit Composer/check scenarios. | Treat model output as SpokenPlan draft only; require source commitment/progress refs and independent coverage/truthfulness checks. |
| TTS / Talker | Continue synthesis and truncate proof work. | For SpokenPlan playback, distinguish provider synthesis from `PLAYBACK_SPAN_STARTED` that must reference an approved check event when check gating is required. |
| Duplex / VAD | Existing realtime ingress proof plan remains valid. | MVP-1 changes are mostly not applicable; MVP-2 only reinforces playback/barge-in ownership around spoken output. |
| Tool-like model output | Must stay proposal evidence. | Model proposals may inform `TOOL_ARGUMENTS_*` or planning evidence, but Tool Executor owns execution, authorization, UI patch, and result normalization. |
| webSearch / RAG evidence | Continue as evidence boundary only. | Use `UNTRUSTED_WEB_EVIDENCE`; no web content may enter instruction context or mutate tool/confirmation/repo policy. |

## Updated Gate Interpretation

| gate | synced status | implication |
| --- | --- | --- |
| Gate 0: research-only boundary | unchanged | Keep work under `docs/research/` and approved `tools/model_spikes/`; protected dirs stay untouched. |
| Gate 1: spike-local eval readiness | still pass for existing synthetic harnesses, with calibration needed | Existing 2026-05-12 harnesses remain useful, but future task-bound cases must use MVP-1 closeout required fields. |
| Gate 2: adapter profile hardening | partial/pass by domain | Hardened profiles should cite `main@ac1b43f` or newer and state whether old evidence was generated against `main@61e6afc`. |
| Gate 3: MVP-3 integration consideration | still not ready | MVP-2 is in progress; real adapter implementation, runtime owner-boundary tests, provider health/error policy, and replay/eval fixtures are not approved for MVP-3. |

## Calibration Checklist For New Reports

Every new model-spike run report or profile hardening addendum should now include:

- `contract_snapshot`: `main@ac1b43f` or newer, unless intentionally preserving historical evidence.
- `historical_contract_snapshot`: original snapshot if reusing 2026-05-11/12 observations from `main@61e6afc`.
- Explicit `output_mode`: `real`, `mock`, `fallback`, `degraded`, or synthetic equivalent.
- For task-bound model evidence: `task_id`, `plan_version`, `task_event_seq`, causal source refs, adapter request id, and late/stale policy.
- For UserPatch-like evidence: `observed_plan_version` and clear split between authoritative evidence and non-authoritative hypothesis.
- For stale result cases: old-plan result binding plus current-plan stale marking and optional adoption metadata.
- For tool-like output: proposal-only label, no execution/authorization claim, and no UI mutation claim.
- For Composer-like output: source commitment or progress refs, check-required flags, and no self-attested coverage/truthfulness pass.
- For webSearch/RAG: `UNTRUSTED_WEB_EVIDENCE`, source refs, redaction status, and no instruction-context placement.
- Privacy flags proving no raw audio, raw trace, local replay cache, real user input, provider body, secret, or generated audio artifact is committed.

## Recommended Next Research Sequence

1. Treat this addendum as the sync point for all new model-spike research after 2026-05-17.
2. Update Slow LLM retry/stale synthetic eval next, because it most directly depends on MVP-1 `plan_version` and stale-result refinements.
3. Update Thinker-as-Composer boundary eval next, because MVP-2 now has explicit SpokenPlan, coverage, progress-truthfulness, and playback gating scenarios.
4. Continue Duplex/VAD realtime ingress proof without changing its owner-chain: Duplex evidence, Interaction interrupt/truncate request, Talker truncate confirmation.
5. Defer runtime adapter implementation until a separate MVP-3 integration branch explicitly approves it.

## Recommendation

Do not restart model-spike work. Continue the existing research lane after this sync, but require new outputs to reference the current mainline snapshot and MVP-1 closeout bindings. The research direction remains correct; the contract snapshot and task-bound metadata expectations have become stricter.
