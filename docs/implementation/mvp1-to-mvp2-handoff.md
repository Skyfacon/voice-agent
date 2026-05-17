#  MVP-1 to MVP-2 Handoff

本文面向准备实现 MVP-2 的 human developer / coding agent。它不替代 ADR，不修改 ADR，也不授权扩大 MVP scope。实现 MVP-2 前仍需以 `AGENTS.md`、`stage_b_adr_register.md`、`docs/adr/*.md` 和 `docs/specs/*.md` 为准。

## 1. 当前阶段一句话结论

MVP-0 / MVP-1 mock/replay spine 已完成，覆盖 live-loop skeleton、SlowTask mock、UserPatch、plan_version、stale evidence、confirmation 和 deterministic replay；MVP-2 runtime 尚未实现。

当前实现观察：

- 已观察到 `MVP1Router`、`TaskFocusState`、`SlowTaskState`、`MockSlowTaskRuntime`、`UserPatchEvidencePackRuntime`、MVP-1 replay fixtures 和 acceptance runner。
- 未观察到 real Tool Executor、demo tool backend、frontend UI patching、Thinker-as-Composer runtime、CommitmentCoverageCheck、ProgressTruthfulnessCheck、real ASR/Thinker/Slow LLM/TTS adapter integration。
- `docs/specs/event-registry.md` 已列出 MVP-2 canonical events；事件名在 registry 中存在不等于 runtime 已实现。

## 2. MVP-1 已完成能力清单

- `MVP1Router` / `TaskFocusState`
  - Router 仍是 post-commit gate，只在 `TURN_INGRESS_COMMITTED` 和 mock ASR/Thinker frame 之后发出 `ROUTER_DECISION_EMITTED`。
  - RouterDecision 仅为 `FAST_ONLY`、`SPAWN_SLOW_TASK`、`PATCH_ACTIVE_SLOW_TASK`、`IGNORE`。
  - TaskFocus values 覆盖 `ACTIVE_TASK_PATCH`、`FOREGROUND_CHAT`、`NEW_TASK_CANDIDATE`、`CANCEL_OR_PAUSE_CANDIDATE`、`NON_ASSISTANT`、`AMBIGUOUS`。
  - active SlowTask 场景下，new-task / cancel-pause candidate 只进入 UserPatch control evidence，不由 Router 直接切换或取消。

- `SlowTaskState` / `MockSlowTaskRuntime`
  - 支持 `CREATED`、`WAITING_FOR_SLOT`、`PLANNING`、`EXECUTING`、`WAITING_FOR_USER_CONFIRMATION`、`COMPLETED`、`CANCELLED`、`FAILED`。
  - terminal states sticky：`COMPLETED`、`CANCELLED`、`FAILED` 后 late UserPatch / ToolResult / confirmation 不得推进任务。
  - mock runtime 覆盖 create、planning、completed、failed、cancelled、waiting-slot、confirmation 和 current-plan SemanticCommitment paths。

- `UserPatchEvidencePackRuntime`
  - `USER_PATCH_RECEIVED` 是 evidence pack，不是 mutation。
  - evidence pack 分 authoritative evidence 和 non-authoritative hypothesis。
  - 保留 ASR n-best、Thinker summary、Router focus metadata 和 source refs/provenance。
  - `USER_PATCH_RECEIVED` 绑定 pre-advance `plan_version`、`observed_plan_version`、`task_event_seq`、`turn_id`、`utterance_id`。

- `plan_version` advance
  - 只有 SlowTask 解释过 material UserPatch 后才 emit `PLAN_VERSION_ADVANCED`。
  - `PLAN_VERSION_ADVANCED.plan_version` 必须等于 `to_plan_version`。
  - non-material patch、foreground chat、ambiguous no-patch 不推进 plan。

- stale evidence with / without adoption
  - MVP-1 用 synthetic `TOOL_CALL_STARTED` / `TOOL_RESULT_RECEIVED` marker 验证 stale policy。
  - old-plan `TOOL_RESULT_RECEIVED` 默认必须进入 `TOOL_RESULT_MARKED_STALE` -> `STALE_EVIDENCE_RECORDED`。
  - 只有 `STALE_EVIDENCE_ADOPTED` 之后，旧 plan evidence 才能进入 current-plan evidence review / resolved arguments / SemanticCommitment。

- waiting slot / ambiguity / resolved arguments mock
  - SlowTask mock 可 emit `EVIDENCE_REVIEWED`、`AMBIGUITY_DETECTED`、`AMBIGUITY_RESOLVED`、`INSUFFICIENT_EVIDENCE_FOR_ACTION`、`CLARIFICATION_REQUESTED`、`WAITING_FOR_SLOT`、`ARGUMENTS_RESOLVED`、`ARGUMENT_RESOLUTION_PROVENANCE`。
  - Router 不选择 ASR/Thinker winner；SlowTask 拥有 ambiguity/conflict resolution。

- cancel / switch-task confirmation
  - cancel 和 switch-task 先通过 `USER_PATCH_RECEIVED` / `USER_PATCH_INTERPRETED`。
  - SlowTask owns `CONFIRMATION_REQUIRED`、`WAITING_FOR_USER_CONFIRMATION`、`USER_CONFIRMATION_RECEIVED`、`CONFIRMATION_ACCEPTED` / `CONFIRMATION_REJECTED`。
  - switch-task accepted path 是 cancel-then-spawn；rejected path 不改变当前 task goal / arguments / plan_version。

- mock SemanticCommitment
  - `SEMANTIC_COMMITMENT_EMITTED` 由 SlowTask Runtime 产生，绑定 current `task_id`、`plan_version`、`task_event_seq`。
  - 若使用 adopted stale evidence，commitment source events 必须包含 adoption source。
  - 这只是 structured commitment mock，不是 spoken realization。

- deterministic replay and MVP-1 acceptance runner
  - Replay reducer 覆盖 `InteractionState`、`TaskFocusState`、`SlowTaskState`、`PlaybackState`、`AdapterHealthState`、`TracePrivacyState`。
  - `tests/fixtures/replay/mvp1/manifest.index.json` 声明 `MVP1-ACCEPTANCE`、`GITHUB_ALLOWED`、deterministic、synthetic fixtures。
  - acceptance runner 覆盖 spawn、active patch、plan advance、foreground chat、ambiguous no patch、waiting slot、stale result、stale adoption、cancel、switch、failed、SemanticCommitment。

## 3. MVP-2 必须继承的 invariants

- Event Journal 是 source of truth。关键状态迁移未进入 per-session append-only journal，就不算通过 slice。
- deterministic replay 不重跑模型、工具、网络、时钟、随机数，也不 fetch 缺失 data-plane refs。
- Router only post-commit gate。Router 不解释最终 UserPatch semantics，不 cancel task，不 authorize tool，不 advance `plan_version`。
- UserPatch is evidence, not mutation。`USER_PATCH_RECEIVED` 不直接改 goal、constraint、slot、confirmation、cancel 或 task state。
- SlowTask owns complex-task facts，包括 resolved arguments、confirmation state、stale/adopted evidence、SemanticCommitment 和 terminal outcome。
- old-plan `TOOL_RESULT_RECEIVED` cannot advance current plan unless `STALE_EVIDENCE_ADOPTED` exists and is referenced by current-plan reasoning.
- Composer cannot rewrite SemanticCommitment facts。不得修改 `immutable_facts`、`must_say_fields`、resolved arguments、tool status、risk warnings 或 confirmation state。
- Tool Executor is the only owner of tool execution and `TOOL_UI_STATE_PATCHED`。前端/demo backend 状态不得由模型文本直接驱动。
- demo tools must stay in sandbox。MVP-2 不允许真实 external write、external communication、payment、booking、real deletion 或 credential/account mutation。
- `DEMO_DESTRUCTIVE_ACTION` 必须走 ADR-016 current-plan confirmation / authorization gate。
- webSearch 是 `UNTRUSTED_WEB_EVIDENCE`，只能进入 evidence 区，不得进入 instruction 区或修改工具/确认/trace/repo policy。
- 所有 ToolCall / ToolResult / UserPatch / SemanticCommitment 必须绑定 `task_id`、`plan_version`、`task_event_seq`。
- 每个 MVP-2 slice 必须先有 replay scenario 或 eval case；mock / degraded / real output 必须可区分。

## 4. 容易误读的 MVP-1 产物

- MVP-1 的 `TOOL_CALL_STARTED` / `TOOL_RESULT_RECEIVED` 只是 synthetic fixture / mock marker，用于 stale policy；不是 progressive Tool Executor。
- MVP-1 acceptance runner 明确拒绝 `TOOL_EXECUTION_STARTED`、`TOOL_PROGRESS_UPDATED`、`TOOL_UI_STATE_PATCHED`、tool manifest、authorization、retry/cancel execution events。
- mock `SEMANTIC_COMMITMENT_EMITTED` 不是 Thinker-as-Composer，也不会产生 `SPOKEN_PLAN_EMITTED`。
- `MockSlowTaskRuntime` 不是 real Slow LLM；它是 deterministic event emitter。
- replay success 不是 real model/tool success；它只证明 recorded control-plane events 可重建 state。
- MVP-1 没有 frontend demo、real adapters、demo tool backend。
- `TaskFocusSnapshot.current_plan_version` 只是 Router 可见的 public summary，不允许 Router 读取 SlowTask internal goal/constraints/stale evidence/authorization details。
- 当前 registry 中存在 MVP-2 event names，不代表这些事件已经有 reducer/runtime/acceptance coverage。

## 5. MVP-2 推荐切片顺序

### Slice 0: MVP-2 fixture / replay safety skeleton

- Goal: 先建立 MVP-2 fixture 目录、manifest、scope gate、repo safety gate 和空 replay case。
- Non-goals: 不实现 Tool Executor、demo backend、Composer、checkers、frontend 或真实工具。
- Likely files:
  - `docs/implementation/mvp2-backlog.md`
  - `docs/specs/mvp2-acceptance-scenarios.md`
  - `tests/fixtures/replay/mvp2/README.md`
  - `tests/fixtures/replay/mvp2/000-empty-mvp2-session.fixture.json`
  - `tests/fixtures/replay/mvp2/manifest.index.json`
  - `tests/replay/test_fixture_safety.py`
  - `tests/acceptance/test_mvp2_acceptance_scenarios.py`
  - `src/voice_agent/replay/scenario_assertions.py`
- Canonical events involved: `SESSION_STARTED`, `ADAPTER_CAPABILITY_SNAPSHOT_RECORDED`, `REPLAY_STARTED`, `REPLAY_COMPLETED`.
- Replay/eval expectation: deterministic, GitHub-allowed, synthetic/minimal fixture；MVP-0/MVP-1 suites keep passing and MVP-1 fixtures still reject MVP-2-only behavior.
- Must-not-break MVP-1 invariants: 不改变 MVP-1 manifest forbidden-event gates；不把 MVP-2 events 放进 `tests/fixtures/replay/mvp1/`。

### Slice 1: `ToolExecutionState` reducer

- Goal: 添加 deterministic reducer / state digest support for progressive tool events before any execution code.
- Non-goals: 不调用 demo backend，不执行工具，不 patch UI，不实现 webSearch，不处理真实外部系统。
- Likely files:
  - `src/voice_agent/state/tool_execution_state.py`
  - `src/voice_agent/replay/runner.py`
  - `src/voice_agent/replay/state_digest.py`
  - `docs/specs/state-reducers.md`
  - `tests/state/test_tool_execution_state.py`
  - `tests/replay/test_tool_execution_replay_mvp2.py`
- Canonical events involved: `TOOL_CALL_STARTED`, `TOOL_MANIFEST_LOADED`, `TOOL_ARGUMENTS_PARTIAL`, `TOOL_ARGUMENTS_READY`, `TOOL_PREVIEW_AVAILABLE`, `TOOL_EXECUTION_AUTHORIZED`, `TOOL_EXECUTION_STARTED`, `TOOL_PROGRESS_UPDATED`, `TOOL_UI_STATE_PATCHED`, `TOOL_RESULT_RECEIVED`, `TOOL_EXECUTION_FAILED`, `TOOL_CALL_RETRYING`, `TOOL_EXECUTION_CANCEL_REQUESTED`, `TOOL_EXECUTION_CANCELLED`, `TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS`.
- Replay/eval expectation: replay reconstructs tool call status, manifest/version, arguments readiness, authorization, progress, UI patch refs, result/failure/retry/cancel metadata without executing a tool.
- Must-not-break MVP-1 invariants: old-plan `TOOL_RESULT_RECEIVED` still goes through stale policy；`task_event_seq` remains monotonic and is never reused from tool start.

### Slice 2: demo Tool Executor skeleton

- Goal: 实现 sandbox-only Tool Executor shell：manifest load、argument/provenance validation、side-effect class gate、authorization event emission、controlled in-memory demo tool execution.
- Non-goals: 不做 frontend UI patch replay，不做 real external write / communication / booking / deletion，不做 real webSearch，先不做 destructive action confirmation。
- Likely files:
  - `src/voice_agent/tools/`
  - `src/voice_agent/demo_backend/`
  - `tests/tools/test_demo_tool_executor_mvp2.py`
  - `tests/replay/test_tool_execution_replay_mvp2.py`
- Canonical events involved: `TOOL_MANIFEST_LOADED`, `TOOL_ARGUMENTS_PARTIAL`, `TOOL_ARGUMENTS_READY`, `TOOL_PREVIEW_AVAILABLE`, `TOOL_EXECUTION_AUTHORIZED`, `TOOL_EXECUTION_STARTED`, `TOOL_PROGRESS_UPDATED`, `TOOL_RESULT_RECEIVED`, `TOOL_EXECUTION_FAILED`, `TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS`.
- Replay/eval expectation: at least one read-only or low-risk sandbox action can emit progressive events and replay without real execution; missing arguments/provenance emits blocked event and no execution start.
- Must-not-break MVP-1 invariants: Tool Executor must not mutate `SlowTaskState` directly；SlowTask remains owner of resolved arguments and confirmation.

### Slice 3: `TOOL_UI_STATE_PATCHED` and demo UI/backend state replay

- Goal: 让 demo backend/frontend-visible state changes 只能通过 `TOOL_UI_STATE_PATCHED` 记录并可 replay。
- Non-goals: 不让模型文本直接驱动 UI；不要求完整前端产品；不接真实设备。
- Likely files:
  - `src/voice_agent/state/tool_execution_state.py`
  - `src/voice_agent/demo_backend/`
  - `src/voice_agent/tools/`
  - `tests/tools/test_tool_ui_state_patch_mvp2.py`
  - `tests/replay/test_tool_ui_state_replay_mvp2.py`
  - optional later frontend path, if a minimal demo surface is introduced
- Canonical events involved: `TOOL_EXECUTION_STARTED`, `TOOL_PROGRESS_UPDATED`, `TOOL_UI_STATE_PATCHED`, `TOOL_RESULT_RECEIVED`.
- Replay/eval expectation: replay reconstructs demo state from recorded `patch_ref` / synthetic patch substitute; patch ids and idempotency keys are stable.
- Must-not-break MVP-1 invariants: UI state patch is Tool Executor-owned only；SlowTask consumes result/status as evidence later, not as direct state mutation.

### Slice 4: demo destructive action confirmation gate

- Goal: Enforce ADR-016 authorization for `DEMO_DESTRUCTIVE_ACTION` before execution starts.
- Non-goals: 不实现真实 deletion；不新增 confirmation scope；不接受 raw text shortcut as confirmation；不实现 pause/resume。
- Likely files:
  - `src/voice_agent/tools/`
  - `src/voice_agent/demo_backend/`
  - `src/voice_agent/slowtask/`
  - `tests/tools/test_demo_destructive_confirmation_mvp2.py`
  - `tests/slowtask/test_confirmation_cancel_switch_mvp1.py` only if existing helpers need compatibility coverage
  - `tests/replay/test_demo_destructive_confirmation_replay_mvp2.py`
- Canonical events involved: `CONFIRMATION_REQUIRED`, `WAITING_FOR_USER_CONFIRMATION`, `USER_CONFIRMATION_RECEIVED`, `CONFIRMATION_ACCEPTED`, `CONFIRMATION_REJECTED`, `TOOL_EXECUTION_AUTHORIZED`, `TOOL_EXECUTION_STARTED`, `TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS`, `TOOL_RESULT_RECEIVED`.
- Replay/eval expectation: no current-plan `CONFIRMATION_ACCEPTED` means no `TOOL_EXECUTION_STARTED`; accepted confirmation authorizes execution; rejected or superseded confirmation blocks execution.
- Must-not-break MVP-1 invariants: confirmation remains SlowTask-owned；pending confirmation becomes invalid if `plan_version` advances。

### Slice 5: Thinker-as-Composer / `SPOKEN_PLAN_EMITTED`

- Goal: Add Composer role contract that converts current-plan SemanticCommitment or grounded progress into a `SPOKEN_PLAN_EMITTED` draft.
- Non-goals: 不直接播放 unchecked output；不让 Composer call provider endpoint outside adapter；不让 Composer rewrite facts；不实现 coverage/truthfulness pass yet unless bundled with Slice 6.
- Likely files:
  - `src/voice_agent/composer/`
  - `src/voice_agent/adapters/` if a mock composer adapter contract is added
  - `tests/composer/test_thinker_as_composer_mvp2.py`
  - `tests/replay/test_spoken_plan_replay_mvp2.py`
- Canonical events involved: `SEMANTIC_COMMITMENT_EMITTED`, `SPOKEN_PLAN_EMITTED`, plus progress source events such as `PLANNING_STARTED`, `WAITING_FOR_SLOT`, `TOOL_PROGRESS_UPDATED`, `WAITING_FOR_USER_CONFIRMATION`, `FINALIZING`, `SLOWTASK_FAILED`.
- Replay/eval expectation: replay reconstructs source commitment/progress -> spoken plan causal chain; generated text is synthetic/redacted in fixtures.
- Must-not-break MVP-1 invariants: Composer cannot alter `task_id`, `plan_version`, `resolved_arguments`, tool status, risk warning, confirmation state, or adopted stale evidence metadata.

### Slice 6: CommitmentCoverageCheck / ProgressTruthfulnessCheck

- Goal: Add rule-based or adapter-backed mock checks that gate playback for commitment-derived speech and progress speech.
- Non-goals: 不创造新 facts；不合并 coverage failure 和 progress truthfulness failure into one ambiguous event；不播放 failed checks。
- Likely files:
  - `src/voice_agent/checks/`
  - `src/voice_agent/composer/`
  - `src/voice_agent/state/playback_state.py`
  - `tests/checks/test_commitment_coverage_mvp2.py`
  - `tests/checks/test_progress_truthfulness_mvp2.py`
  - `tests/replay/test_composer_checks_replay_mvp2.py`
- Canonical events involved: `SPOKEN_PLAN_EMITTED`, `COMMITMENT_COVERAGE_CHECK_PASSED`, `COMMITMENT_COVERAGE_CHECK_FAILED`, `PROGRESS_TRUTHFULNESS_CHECK_PASSED`, `PROGRESS_TRUTHFULNESS_CHECK_FAILED`, `PLAYBACK_SPAN_STARTED`.
- Replay/eval expectation: failed coverage/truthfulness blocks playback; passed check is referenced by `PLAYBACK_SPAN_STARTED.approved_check_event_id` or equivalent causal chain.
- Must-not-break MVP-1 invariants: SemanticCommitment remains SlowTask-owned；progress must be grounded in actual state events；stale evidence without adoption cannot be spoken as current fact.

### Slice 7: MVP-2 acceptance runner

- Goal: Build a single MVP-2 acceptance suite over required synthetic scenarios for tools, UI patch, destructive confirmation, Composer, checks, webSearch boundary, and replay safety.
- Non-goals: 不启动产品服务，不要求 real model/tool success，不引入 MVP-3 real adapters，不实现 production privacy/auth。
- Likely files:
  - `docs/specs/mvp2-acceptance-scenarios.md`
  - `tests/acceptance/test_mvp2_acceptance_scenarios.py`
  - `tests/fixtures/replay/mvp2/manifest.index.json`
  - `src/voice_agent/replay/scenario_assertions.py`
  - relevant `tests/tools/`, `tests/composer/`, `tests/checks/`, `tests/replay/`
- Canonical events involved: all MVP-2 tool, commitment/composer/check, replay, confirmation, stale-policy events used by prior slices.
- Replay/eval expectation: suite proves deterministic replay, fixture safety, sandbox-only tools, UI patch replay, destructive-action gate, no direct UI mutation, no Composer fact rewrite, no unsupported progress, and webSearch untrusted evidence boundary.
- Must-not-break MVP-1 invariants: MVP-1 acceptance remains green and continues to reject MVP-2-only behavior in MVP-1 fixtures.

## 6. MVP-2 开工前 checklist

- 首批 demo tools 选哪几个？建议先固定 3 个，例如 flashlight、memo、alarm；weather / webSearch 可排在后续 slice。
- webSearch 用 mock 还是真 read-only API？建议 MVP-2 先用 mock/synthetic result，除非明确批准联网/read-only API 方案。
- 是否先做无前端的 demo backend state replay，还是同步做极简前端？建议先做 backend state replay，再接极简前端。
- Tool Executor manifest schema 是否先文档化？建议先文档化最小 manifest：`tool_name`、`tool_adapter_id`、`tool_manifest_version`、`side_effect_class`、required args、preview policy、confirmation requirement。
- Composer/checker 先 rule-based 还是 adapter-backed mock？建议先 rule-based / deterministic mock，后续再 adapter-backed mock；真实 adapter 属 MVP-3。
- MVP-2 acceptance scenarios 是否先写再实现？建议先写 `docs/specs/mvp2-acceptance-scenarios.md` 和 empty manifest gate，再开始 runtime。
- `TOOL_CALL_STARTED` 是否继续作为 summary marker？如果和 `TOOL_EXECUTION_STARTED` 同时 emit，必须共享 `tool_call_id`，且不能表示二次执行。
- `DEMO_DESTRUCTIVE_ACTION` 的首个示例选什么？建议选可逆/resettable 的 demo note delete 或 demo alarm cancel。
- 是否需要更新 docs before code？若只是实现 ADR-002 已注册事件和 ADR-005/009/013/014/016 范围内行为，不需要改 ADR；若要新增 event name、RouterDecision、TaskFocus value、SlowTask state 或 scope，必须先停下更新 ADR。

## 7. 建议的下一步

建议先创建并审阅以下三个文件，再动 runtime：

- `docs/implementation/mvp2-backlog.md`
- `docs/specs/mvp2-acceptance-scenarios.md`
- `tests/fixtures/replay/mvp2/manifest.index.json`

推荐顺序：

1. 先写 MVP-2 acceptance scenarios 和 fixture safety gate。
2. 再加 `ToolExecutionState` reducer，不执行任何工具。
3. 再实现 sandbox-only Tool Executor skeleton。
4. 最后接 Composer/checkers 和 acceptance closeout。

任何发现文档与代码状态不一致的地方，先在 implementation docs 中写“当前实现观察”；不要用 handoff 或 backlog 悄悄改变 ADR 边界。
