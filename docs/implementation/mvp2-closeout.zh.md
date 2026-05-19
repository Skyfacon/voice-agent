# MVP-2 阶段 Closeout / Handoff 中文对照版

本文是 `docs/implementation/mvp2-closeout.md` 的中文对照版，用于阶段关闭、PR 总结和后续交接阅读。英文版继续保留；本文件只提供更易读的中文总结，不替代 ADR，不修改 ADR，也不授权扩大 MVP scope。后续开发仍必须以 `AGENTS.md`、`stage_b_adr_register.md`、`docs/adr/*.md` 和 `docs/specs/*.md` 为准。

## 1. 阶段快照

- 编写日期：2026-05-19
- 本次 closeout 范围：只新增文档总结。未修改 ADR，未修改代码，未启动服务，未接入真实模型、真实 TTS、真实工具、真实 frontend，也未产生真实外部副作用。
- 本地审阅基线：`mvp2/slice8-acceptance-runner`，提交 `9f47301`（`feat: add MVP2 acceptance runner`）。
- 远端 main 说明：2026-05-19 已刷新远端引用。`origin/main` 当前为 `671f7fc`（`Merge pull request #27 from Skyfacon/mvp2/slice8-acceptance-runner`），已包含 MVP-2 slice8 acceptance runner。
- 本次新增前工作区状态：已有英文版 `docs/implementation/mvp2-closeout.md` 为未跟踪文档文件。
- 英文原版：`docs/implementation/mvp2-closeout.md`。
- 中文对照版：`docs/implementation/mvp2-closeout.zh.md`。
- 统一测试入口：`./scripts/test -q`。
- 本文件测试状态：`./scripts/test -q` 已在本地通过，结果为 `665 passed`。

## 2. 已审阅资料

- 治理入口和 ADR 索引：`AGENTS.md`、`stage_b_adr_register.md`。
- MVP-2 规划和规格：`docs/implementation/mvp2-backlog.md`、`docs/specs/mvp2-acceptance-scenarios.md`、`docs/specs/event-registry.md`、`docs/specs/replay-spec.md`、`docs/specs/state-reducers.md`。
- MVP acceptance 测试：`tests/acceptance/test_mvp0_acceptance_scenarios.py`、`tests/acceptance/test_mvp1_acceptance_scenarios.py`、`tests/acceptance/test_mvp2_acceptance_scenarios.py`。
- MVP-2 replay manifest 和 fixtures：`tests/fixtures/replay/mvp2/manifest.index.json` 以及 manifest 中列出的 10 个 fixture。
- MVP-2 相关实现与测试：replay scenario assertions、replay runner、tool executor tests、demo tool tests、demo UI patch replay tests、destructive confirmation tests、Composer tests、coverage/truthfulness checker tests、fixture safety tests。

## 3. MVP-0 / MVP-1 / MVP-2 当前状态

MVP-0 已完成 mock live-loop 和 replay 主干。它覆盖 text/audio ingress、barge-in/truncate、mock adapter capability snapshot、本地 trace safety、deterministic replay 和 mock SLO label。MVP-0 acceptance suite 验证 5 个必需场景和 7 个 replay fixtures，并继续拒绝 MVP-1 / MVP-2 才允许出现的行为进入 MVP-0 fixtures。

MVP-1 已完成 SlowTask mock 层。它覆盖 Router/TaskFocus handoff、active task patch、`plan_version` 推进、foreground chat、ambiguous no-patch、waiting slot、stale evidence with/without adoption、cancel/switch confirmation、failed sticky terminal state、SemanticCommitment 和 deterministic replay。MVP-1 acceptance suite 验证 12 个必需场景和 13 个 replay fixtures，并拒绝 real output mode 以及 MVP-2-only Tool Executor 行为进入 MVP-1 fixtures。

MVP-2 已完成 deterministic demo/replay acceptance slice。它补齐 demo sandbox tools、progressive Tool Executor events、demo UI state patch replay、webSearch evidence boundary、demo destructive action confirmation gate、Thinker-as-Composer、coverage/truthfulness checks 和正式 MVP-2 acceptance runner。它不声称真实模型、真实 TTS、真实工具、真实 frontend 或真实外部副作用已经 ready。

## 4. MVP-2 已完成能力

- 为 `memo`、`alarm`、`flashlight`、`weather`、`webSearch` 建立 tool manifest 和 scope 声明，包括 tool category、side-effect class、trust label 和 UI patch capability。
- 覆盖 progressive Tool Executor lifecycle：manifest load、partial args、ready args、insufficient-argument blocked、preview、authorization、start、progress、UI patch、result、failure、retry、cancel request、cancel metadata。
- 建立 sandbox-only demo backend state。memo/alarm/flashlight 等 demo action 只通过 Tool Executor 产生 replayable UI patch。
- `DemoUIState` 只能从已记录的 `TOOL_UI_STATE_PATCHED` / synthetic `patch_ref` 重建。单独的 `TOOL_RESULT_RECEIVED` 不会被 replay 推断为 frontend/demo state mutation。
- 为 sandbox memo delete 和 alarm cancel 覆盖 `DEMO_DESTRUCTIVE_ACTION` confirmation gate：必须是 current-plan confirmation，并且 causal authorization 正确，才允许 `TOOL_EXECUTION_STARTED`。
- 覆盖 progressive stale ToolResult policy：old-plan ToolResult 必须进入 stale evidence；没有显式 adoption，不得推进 current task。
- 明确 webSearch 只能作为 evidence：`UNTRUSTED_WEB_EVIDENCE`、`EXTERNAL_READ_UNTRUSTED`、无 UI patch、无 backend action、不能进入 instruction/policy mutation。
- 建立 Thinker-as-Composer mock role：从 current-plan SemanticCommitment 或 grounded progress 产生 `SPOKEN_PLAN_EMITTED`，但不直接 playback，也不得改写 SlowTask facts。
- 建立 CommitmentCoverageCheck 和 ProgressTruthfulnessCheck mock gates。通过的 check 可以授权匹配的 playback；失败或 stale check 不能授权 playback。
- 建立 MVP-2 acceptance runner：验证 spec-derived scenario list、fixture safety、deterministic replay digest、no-runtime-execution summary、ADR update summary 和 hidden future-scope detection summary。

## 5. Acceptance Coverage

MVP-2 acceptance spec 声明 15 个场景，runner 会校验 manifest 与 spec-derived scenario list 完全一致：

- Tool surface：`MVP2-TOOL-MANIFEST-001`、`MVP2-TOOL-ARGS-PARTIAL-001`、`MVP2-TOOL-BLOCKED-INSUFFICIENT-ARGS-001`。
- Demo tools：`MVP2-MEMO-SANDBOX-WRITE-001`、`MVP2-ALARM-SANDBOX-SCHEDULE-001`、`MVP2-FLASHLIGHT-DEMO-DEVICE-ACTION-001`、`MVP2-WEATHER-READ-ONLY-001`、`MVP2-WEBSEARCH-UNTRUSTED-EVIDENCE-001`。
- UI/replay boundary：`MVP2-UI-STATE-PATCHED-001`。
- Confirmation 和 stale policy：`MVP2-DEMO-DESTRUCTIVE-CONFIRMATION-001`、`MVP2-STALE-TOOL-RESULT-PROGRESSIVE-001`。
- Composer 和 spoken output gates：`MVP2-COMPOSER-SPOKEN-PLAN-001`、`MVP2-COMMITMENT-COVERAGE-001`、`MVP2-PROGRESS-TRUTHFULNESS-001`。
- Suite safety：`MVP2-ACCEPTANCE-SCOPE-SAFETY-001`。

Acceptance runner 还覆盖负向门禁：缺失必需 scenario、跳过 fixture check、不安全 side-effect class、削弱 replay property、不安全 source module、repo-unsafe fixture content、raw artifact marker、real/unlabeled output mode、以及 real adapter runtime claim 都会被拒绝。

## 6. Replay Fixture 覆盖

MVP-2 manifest 是 `MVP2-ACCEPTANCE`、`GITHUB_ALLOWED`、deterministic，并且 fixture 材料限定为 synthetic/redacted/minimal。当前检查 10 个 fixtures：

| Fixture | 主要覆盖 |
| --- | --- |
| `000-empty-mvp2-session.fixture.json` | 空 MVP-2 replay safety skeleton。 |
| `001-tool-execution-state.fixture.json` | ToolExecutionState reducer surface，包括 lifecycle、args、authorization、progress、UI refs、result/failure/retry/cancel metadata。 |
| `002-tool-executor-skeleton.fixture.json` | Tool Executor success path 和 insufficient-provenance blocked path，replay 不执行 backend。 |
| `003-tool-ui-state-patch.fixture.json` | demo UI/backend 只从 `TOOL_UI_STATE_PATCHED` 重建。 |
| `004-demo-tools.fixture.json` | memo、alarm、flashlight、weather、webSearch demo tool replay。 |
| `005-demo-destructive-confirmation.fixture.json` | memo delete 和 alarm cancel 的 current-plan destructive confirmation gate。 |
| `006-thinker-as-composer.fixture.json` | Composer 从 current-plan commitment 和 grounded progress 产生 unchecked spoken plans。 |
| `007-composer-checks.fixture.json` | coverage/truthfulness pass events gate playback，且不执行 TTS/audio/frontend。 |
| `008-tool-manifest-only.fixture.json` | 加载所有 MVP-2 tool manifest，不执行工具。 |
| `009-progressive-stale-tool-result.fixture.json` | old-plan progressive ToolResult 进入 stale evidence，不推进 current task。 |

Replay 侧的关键结论是：deterministic replay 不重跑模型、工具、网络、时钟或随机数；demo UI state 只能来自 `TOOL_UI_STATE_PATCHED`；webSearch 只能作为 untrusted evidence replay；demo destructive action 需要 current-plan confirmation；Composer output 需要 coverage/truthfulness gate 才能 playback；old-plan ToolResult 要进入 current-plan 使用，必须先有 stale-evidence/adoption chain。

## 7. Non-goals / 明确没有做的事情

MVP-2 明确不包含：

- 真实 ASR、Thinker、Slow LLM、TTS、duplex model、embedding/RAG 或 provider-backed Composer call。
- adapter 外的直接外部模型调用。
- 真实 Tool Executor integrations、真实 external write、external communication、booking、payment、real deletion、account/identity mutation、credential mutation 或真实 device control。
- 默认真实 webSearch 或真实 weather API。MVP-2 接受的是 mock/synthetic/read-only evidence replay。
- 真实 frontend 启动或 browser/product UI 验证。MVP-2 验证的是 replayed `DemoUIState`，不是正在运行的产品 UI。
- production privacy/auth、production persistence、production tool credentials 或 unredacted real user input fixture。
- multi active SlowTask、pause/resume、新 RouterDecision、新 TaskFocus value、新 SlowTask state 或新 canonical event name。
- 任何超出已接受 MVP-2 ADR/spec surface 的新架构能力。

本次 closeout 审阅没有发现 MVP-2 scope 外行为进入已审阅的 source/spec/test surface。Acceptance gates 也明确拒绝主要 out-of-scope behaviors 和 future-scope source modules。

## 8. 最近 Review 暴露的问题与 Gate 补强

最近 review 暴露出几个“happy path 通过还不够”的风险点：

- Destructive confirmation 不能只看是否有 accepted confirmation event。现在会验证 current `task_id` / `plan_version`、tool trigger、preview argument fingerprint、router/turn causality、confirmation scope 和 causal authorization，之后才允许 `TOOL_EXECUTION_STARTED`。
- Tool UI state 必须有严格事件边界。Replay 只从 Tool Executor-owned `TOOL_UI_STATE_PATCHED` 重建 demo state，并拒绝 direct frontend/model text mutation，也不会从 ToolResult 反推 UI mutation。
- webSearch 需要强 evidence boundary。Manifest 和 acceptance runner 要求 `UNTRUSTED_WEB_EVIDENCE`、`EXTERNAL_READ_UNTRUSTED`、read-only side effects、无 UI patch，并且只能进入 evidence review。
- Composer 需要 provenance 和 fact-preservation gates。Runtime/replay tests 会拒绝 stale source、错误 task/plan binding、noncanonical source module、缺失 source id、unsupported progress source，以及 symbolic metadata 被 drop/rewrite/add。
- Coverage/truthfulness checks 需要 replayable failure paths。Failed checks 会被保留为 check events，但不能 authorize playback；通过的 playback 必须引用匹配的 passed check 和 spoken plan。
- Progressive ToolResult 需要 acceptance-level stale protection。old-plan ToolResult fixture 会验证 `TOOL_RESULT_MARKED_STALE` 和 `STALE_EVIDENCE_RECORDED`，且没有 explicit adoption 时不允许产生 SemanticCommitment 或推进 current plan。
- Acceptance runner 现在会拒绝 real output mode、不安全 side-effect class、被削弱的 replay properties、缺失 fixture checks、不安全 fixtures 和 forbidden future-scope source modules。

## 9. ADR 与 Scope 判断

当前 MVP-2 closeout 不需要 ADR 更新。原因是：

- MVP-2 用到的 canonical events 已经在 event registry/specs 中存在。
- 本阶段没有新增 architecture role、event family、state owner 或 MVP scope。
- 本阶段没有引入真实 model/tool/frontend/external side-effect 行为。

后续如果要新增 canonical event name、改变 owner boundary、新增 RouterDecision/TaskFocus/SlowTask state、启用真实外部副作用、引入 production privacy/auth policy，或让 MVP-3 超出 adapter replacement 范围，必须先更新或新增 ADR。

## 10. 当前测试状态

- 必需命令：`./scripts/test -q`。
- 本中文对照文档测试状态：本地已通过，结果为 `665 passed`。
- CI/remote 状态：本地已刷新 remote `main` 并确认其为 `671f7fc`；最终 GitHub CI 状态仍应在 docs-only PR 上确认。

## 11. MVP-3 Readiness

Closeout 文档审阅并通过统一测试入口后，项目可以进入 MVP-3 planning。Readiness 基础是：

- adapter capability contract 已经能区分 `real`、`mock`、`fallback`、`degraded` output modes。
- MVP-0 到 MVP-2 的 replay suites 已经建立 deterministic replay、trace privacy、event ownership 和 fixture safety 的基本门禁。
- MVP-2 acceptance 明确禁止 real adapter runtime integration，这给 MVP-3 留出了清晰边界：真实 adapter 要被有意接入，而不是意外混入。
- state reducers 和 replay specs 已经要求 replay 不重跑模型、工具、网络、时钟或随机数。

MVP-3 应该被视为 adapter integration planning，而不是架构扩张。它应当在现有 adapter boundary 后替换 selected mock behavior，并继续保持 deterministic replay 基于 recorded events/refs。

## 12. 剩余风险和技术债

- 当前沙箱中已刷新 remote refs，并确认 `origin/main` 为 `671f7fc`。最终 docs-only PR 是否可合入仍以 CI / GitHub merge gate 为准。
- `docs/implementation/mvp2-backlog.md` 仍保留“当前 MVP-2 runtime 尚未实现”的历史语境。它在当时是准确的，但现在可能让后续读者困惑；后续可做一个小的文档清理，链接到 closeout。
- `tests/fixtures/replay/mvp2/manifest.index.json` 仍同时包含当前 `fixture_checks` 和历史 `planned_fixture_checks`。这不影响测试，但阅读上容易造成歧义。
- `src/voice_agent/replay/scenario_assertions.py` 目前承载了 MVP-0/MVP-1/MVP-2 大量 acceptance logic。后续可以做不改变 scope 的小重构，按 MVP phase 拆分 helper。
- MVP-2 验证的是 replayed demo UI state，不是 live product frontend。如果产品 demo 前需要真实 frontend surface，应明确作为后续工作规划，不能回填到 MVP-2 scope。
- MVP-3 接入真实 adapters 前，需要 credential-safe config refs、output-mode labeling、failure/degraded/fallback events 和 replay fixtures。
- MVP-2 测试是 synthetic control-plane 测试。它对控制面 invariant 很强，但不评估真实 provider quality、latency、acoustic quality、TTS quality 或 production tool behavior。

## 13. MVP-3 建议切入顺序

MVP-3 要保持窄范围：真实 adapter capability matrix、adapter mock/real/fallback/degraded 标注、deterministic replay 不重跑模型/工具/network/clock/random，并且不新增新架构能力。

1. 刷新 local `main`，确认 slice8 merge SHA，合入 docs-only closeout，并运行 `./scripts/test -q` 与 CI。
2. 重读 ADR-011 和现有 adapter capability code，为 ASR、Thinker、Slow LLM、TTS 编写 MVP-3 adapter capability matrix。
3. 增加测试，强制 adapter output mode 显式标注：`mock`、`real`、`fallback`、`degraded` 都必须可区分且不泄露 credential。
4. 为 adapter output/failure/degraded events 增加 deterministic replay fixtures，只使用 recorded refs。Replay 不得调用 provider、tool、network、clock 或 random。
5. 在启用任何真实 provider path 前，先补 fallback/degraded acceptance cases。
6. 只在 capability matrix 和 replay gates 到位后，才把第一个 real adapter 接到既有 adapter interface 后面。
7. Tool Executor、frontend、multi SlowTask、pause/resume、真实 external side-effect tools 继续排除在 MVP-3 外，除非先有新 ADR 明确扩大 scope。

## 14. Merge / Handoff 建议

- 保留英文版 closeout，同时提交这份中文对照版，作为 docs-only change。
- 如果代码特性分支已经合入 main，建议单独开一个 closeout 文档 PR。
- closeout 合入并测试通过后，下一步建议进入 MVP-3 planning，而不是继续扩大 MVP-2 feature scope。
