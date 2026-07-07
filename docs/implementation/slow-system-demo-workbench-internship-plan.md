# 慢系统 Demo Workbench 六周实习任务书

## 状态

拟定版实习执行任务书，周期约 6 周。

本文档用于给实习生、mentor 和项目负责人对齐实习目标、阶段任务和交付标准。它不是 ADR，不替代 `AGENTS.md`、`stage_b_adr_register.md` 或 `docs/adr/` 下的 accepted ADR。任何实现都必须继续遵守当前仓库的架构边界。

## 一句话目标

构建一个 React 版 **慢系统 Demo Workbench**：对外能讲清楚慢系统如何可靠推进任务，对内能作为快慢系统耦合调试台；Codex 可以作为 LLM + 工具黑盒生成 proposal，但不能成为系统事实源。

## 最终产出形态

六周结束时，实习生应交付一个可运行的交互式原型，支持两种模式：

| 模式 | 面向对象 | 目的 |
| --- | --- | --- |
| Demo Mode | 外部观众、合作方、产品/技术负责人 | 用可视化故事讲清楚慢系统如何规划、查证、接收用户补充、等待确认、处理旧结果、生成最终承诺。 |
| Debug Mode | 内部研发 | 查看 Router、SlowTask、UserPatch、Event Journal snapshot、Codex proposal 之间的耦合状态。 |

这个 Workbench 应该先能在纯 mock/demo 场景下运行；随后通过可插拔 adapter 接入当前 `voice-agent` 的 replay / event / snapshot 数据。不要一开始就依赖真实 provider 或真实 Codex 可用性。

## 给实习生的项目定位

这不是让你重写慢系统，也不是让你单独实现一个新的 SlowTask runtime。你的任务是做慢系统的交互层、可视化层和 proposal 调试台。

正确理解：

```text
React Workbench
  -> 稳定 SlowSystemAdapter 协议
  -> Mock scenario adapter 或 Python snapshot adapter
  -> 可选 Codex proposal bridge
  -> 展示 validated proposal / accepted action
  -> 现有 SlowTask / Event Journal 仍然是事实源
```

错误理解：

```text
React Workbench
  -> 自己拥有 SlowTask 状态
  -> 直接推进 plan_version
  -> 直接授权工具执行
  -> 直接发出 SemanticCommitment
```

## 必须守住的边界

以下规则是 P0 级边界：

- React 不能成为第二套 SlowTask runtime。
- Codex 输出只能是 `proposal`，不能直接推进任务状态。
- Python control-plane 仍然拥有 Event Journal、SlowTask state、`plan_version`、`task_event_seq`、confirmation、stale evidence adoption 和 SemanticCommitment。
- 本项目不得新增 canonical event name；如果发现必须新增事件，停止实现，先走 ADR。
- 不允许真实外部副作用工具，比如支付、预订、删除、外部通信、真实设备控制。
- 不得提交 raw audio、raw provider body、prompt dump、本地路径、API key、cookie、token、credential。
- 前端不得收到 provider secret。任何 Codex 或模型调用必须经过后端 adapter。
- Demo 里的工具执行默认是 preview / proposal / sandbox，不是真实外部执行。

## 推荐范围

### 本次实习范围内

- React 交互式 Workbench。
- 面向外部展示的慢系统 Demo Mode。
- 面向内部研发的 Debug Mode。
- Mock scenarios。
- 稳定前端 adapter schema。
- Python snapshot adapter，用于把现有 replay/event 状态映射成前端可读 snapshot。
- Codex proposal bridge，作为可选后端能力。
- Proposal validation 和 accepted/rejected 状态展示。
- README、handoff、演示脚本。
- 基础测试：adapter mapping、proposal validation、关键 UI 状态。

### 本次实习不做

- 生产级前端。
- 实时麦克风流式输入。
- Full-duplex、AEC、live barge-in 扩展。
- 真实 TTS 或 voice output。
- 真实外部工具执行。
- 重写 `SlowTaskState`、`MockSlowTaskRuntime`、`DemoToolExecutor`、Event Journal。
- 多 active SlowTask。
- pause/resume。
- 生产隐私策略。
- 新 canonical event name。

## 推荐代码结构

最终结构可由 mentor 在实现前调整。推荐先按以下边界拆：

```text
apps/slow-system-workbench/
  package.json
  src/
    app/
      App.tsx
      routes.tsx
    adapters/
      SlowSystemAdapter.ts
      MockSlowSystemAdapter.ts
      HttpSlowSystemAdapter.ts
    components/
      ConversationPanel.tsx
      SlowTaskTimeline.tsx
      PlanVersionPanel.tsx
      EvidencePanel.tsx
      ConfirmationPanel.tsx
      CodexProposalPanel.tsx
      DebugInspector.tsx
    scenarios/
      demoScenarios.ts
    types/
      slowSystem.ts
    tests/
      adapterMapping.test.ts
      proposalValidation.test.ts
      demoScenarioState.test.ts

src/voice_agent/runtime/
  slow_system_workbench_api.py
  slow_system_workbench_snapshots.py
  slow_system_workbench_codex.py

tests/runtime/
  test_slow_system_workbench_snapshots.py
  test_slow_system_workbench_codex.py

docs/implementation/
  slow-system-demo-workbench-internship-plan.md
  slow-system-demo-workbench-handoff.md
```

如果 mentor 决定暂时不把 React app 放入当前 monorepo，也可以先放在独立 demo repo 或独立 worktree。但无论放在哪里，都必须遵守本文的协议、边界和交付要求。

## 前端稳定协议

React app 不应该直接依赖 Python 内部事件结构，而应依赖稳定的前端协议。下面是建议的 TypeScript 类型草案。

```ts
export type RouterDecision =
  | "FAST_ONLY"
  | "SPAWN_SLOW_TASK"
  | "PATCH_ACTIVE_SLOW_TASK"
  | "IGNORE";

export type TaskLifecycle =
  | "NONE"
  | "CREATED"
  | "PLANNING"
  | "WAITING_FOR_SLOT"
  | "WAITING_FOR_TOOL"
  | "WAITING_FOR_USER_CONFIRMATION"
  | "FINALIZING"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED";

export interface WorkbenchSnapshot {
  snapshot_id: string;
  mode: "demo" | "debug";
  scenario_id?: string;
  router?: RouterDecisionSnapshot;
  task?: TaskSnapshot;
  conversation: ConversationTurn[];
  codex_proposals: CodexProposal[];
  safety: WorkbenchSafetySummary;
}

export interface RouterDecisionSnapshot {
  router_decision: RouterDecision;
  task_focus:
    | "FOREGROUND_CHAT"
    | "NEW_TASK_CANDIDATE"
    | "ACTIVE_TASK_PATCH"
    | "AMBIGUOUS"
    | "NON_ASSISTANT";
  confidence: number;
  evidence_uncertainty: "low" | "medium" | "high";
  turn_id: string;
  asr_frame_event_id?: string;
  thinker_frame_event_id?: string;
}

export interface TaskSnapshot {
  task_id: string;
  lifecycle: TaskLifecycle;
  current_plan_version: number;
  latest_task_event_seq: number;
  goal_summary: string;
  plan_versions: PlanVersionSnapshot[];
  evidence: EvidenceItem[];
  stale_evidence: EvidenceItem[];
  pending_confirmation?: PendingConfirmation;
  semantic_commitment_preview?: SemanticCommitmentPreview;
}

export interface PlanVersionSnapshot {
  plan_version: number;
  status: "current" | "superseded" | "failed" | "completed";
  summary: string;
  created_by_event_id: string;
  reason: "initial_plan" | "user_patch" | "stale_evidence_adopted" | "manual_demo";
}

export interface EvidenceItem {
  evidence_id: string;
  source: "user" | "asr" | "thinker" | "tool" | "web" | "codex_proposal";
  trust_level: "authoritative" | "hypothesis" | "untrusted_web_evidence";
  plan_version: number;
  event_id?: string;
  label: string;
  summary: string;
  stale: boolean;
}

export interface PendingConfirmation {
  confirmation_id: string;
  scope: "TASK_CANCEL" | "SWITCH_TASK" | "DEMO_DESTRUCTIVE_ACTION" | "FINAL_ARGUMENT_CONFIRMATION";
  plan_version: number;
  prompt: string;
  risk_summary: string;
}

export interface CodexProposal {
  proposal_id: string;
  proposal_type:
    | "plan_update"
    | "evidence_review"
    | "tool_preview"
    | "clarification"
    | "commitment_draft";
  status: "draft" | "validated" | "accepted" | "rejected";
  summary: string;
  suggested_next_steps: string[];
  missing_fields: string[];
  requires_confirmation: boolean;
  risk_notes: string[];
  source_evidence_refs: string[];
}
```

## Codex Proposal Contract

Codex 应该被封装在后端 adapter 后面，返回 proposal JSON。前端只能展示 proposal；是否接受 proposal，必须由后端验证和慢系统规则决定。

允许 Codex 输出：

- plan update 建议。
- evidence review 摘要。
- missing field / clarification 建议。
- tool preview 草案。
- commitment wording 草案。

禁止 Codex 直接输出并执行：

- `PLAN_VERSION_ADVANCED`
- `SEMANTIC_COMMITMENT_EMITTED`
- `TOOL_EXECUTION_AUTHORIZED`
- `TOOL_UI_STATE_PATCHED`
- 直接 mutation `TaskSnapshot`
- 直接执行外部工具

建议后端响应格式：

```json
{
  "proposal_id": "proposal_demo_001",
  "proposal_type": "plan_update",
  "status": "validated",
  "summary": "Codex 建议更新计划，因为用户修改了时间约束。",
  "suggested_next_steps": [
    "保留原有地点约束",
    "将时间窗口改为明天上午",
    "最终确认前先向用户请求确认"
  ],
  "missing_fields": [],
  "requires_confirmation": true,
  "risk_notes": [
    "该 proposal 在被 SlowTask 接受前不是 SemanticCommitment。"
  ],
  "source_evidence_refs": [
    "evidence://demo/user-patch/change-time"
  ],
  "safety": {
    "codex_is_fact_owner": false,
    "advances_plan_version": false,
    "authorizes_tool": false,
    "contains_secret": false
  }
}
```

## 必做 Demo 场景

实习结束前，Demo Mode 至少要覆盖以下四条场景。

### 场景 1：创建新的复杂任务

故事线：

```text
用户：帮我规划一个两天的客户来访行程，地点尽量靠近公司。
系统：Router 判断为 SPAWN_SLOW_TASK。
慢系统：创建 plan_version=1，审查 evidence，发现缺少预算或时间偏好。
Codex：生成一个结构化 plan proposal。
后端：把 proposal 标为 draft/validated，不自动接受为事实。
```

必须展示：

- Conversation panel。
- Router decision：`SPAWN_SLOW_TASK`。
- SlowTask timeline。
- Plan version 1。
- Evidence list。
- Codex proposal。

验收标准：

- UI 明确展示 Codex 只是提出计划草案，不是事实源。
- `plan_version=1` 可见。
- Debug Mode 中可以看到 `task_event_seq`。

### 场景 2：用户补充约束导致计划变化

故事线：

```text
用户：改成明天上午，并且预算控制在 500 元以内。
系统：Router 判断为 PATCH_ACTIVE_SLOW_TASK。
慢系统：记录 UserPatch evidence。
Codex：建议这个 patch 是否属于 material change。
后端：只有 accepted interpretation 之后才展示 plan_version 推进。
```

必须展示：

- UserPatch evidence。
- plan version 前后对比。
- Codex proposal status。
- accepted / rejected action。

验收标准：

- UI 区分 `USER_PATCH_RECEIVED` 和真正的计划 mutation。
- material patch 从 `plan_version=1` 推进到 `plan_version=2`。
- non-material patch 场景不推进 plan version。

### 场景 3：旧工具结果变成 stale evidence

故事线：

```text
系统：为 plan_version=1 启动一个 demo tool lookup。
用户：在工具结果返回前修改任务。
工具结果：返回时仍绑定 old plan_version=1。
慢系统：将它放入 stale evidence，而不是应用到当前 plan_version=2。
Codex：可以建议 stale evidence 是否值得采用。
后端：除非显式 adopt，否则 stale evidence 不进入当前事实。
```

必须展示：

- Tool result preview。
- Current plan version。
- Stale evidence bucket。
- Optional adoption proposal。

验收标准：

- UI 清楚说明旧结果为什么不能推进当前任务。
- stale result 不得显示为 current evidence，除非有显式 adoption。

### 场景 4：确认门控

故事线：

```text
用户：那就取消这个任务吧。
系统：SlowTask 进入 WAITING_FOR_USER_CONFIRMATION。
Codex：可以起草确认提示语。
后端：只有用户确认才能 accept / reject。
```

必须展示：

- Pending confirmation。
- Risk summary。
- Demo Mode 中的 accept / reject 按钮。
- Debug Mode 中的事件或 snapshot 信息。

验收标准：

- Codex 不能代替用户确认。
- 用户 action 驱动 accepted / rejected 状态。

## 六周任务拆解

### 第 1 周：项目理解、架构阅读、Demo 骨架

目标：理解慢系统边界，产出可点击的 React skeleton 和第一条 mock 场景。

必读材料：

- `AGENTS.md`
- `stage_b_adr_register.md`
- `docs/adr/ADR-004 SlowTask Plan Versioning and Stale Result Policy.md`
- `docs/adr/ADR-006 Router Task Focus and Single Active SlowTask MVP.md`
- `docs/adr/ADR-007 UserPatch Evidence Pack.md`
- `docs/adr/ADR-008 ASR Thinker Evidence Fusion and SlowTask-led Conflict Resolution.md`
- `docs/adr/ADR-009 SemanticCommitment and Thinker-as-Composer Contract.md`
- `docs/adr/ADR-016 SlowTask Lifecycle and Confirmation State Contract.md`
- `docs/implementation/mvp5-closeout.md`
- `docs/implementation/mvp6-local-debug-console.md`

具体任务：

- 写一页架构理解笔记：React 拥有什么，SlowTask 拥有什么，Codex 拥有什么。
- 创建 React app skeleton 或独立 prototype workspace。
- 定义第一版 `slowSystem.ts` 前端类型。
- 加入场景 1 的静态 mock data。
- 搭建第一版页面布局：
  - conversation panel
  - SlowTask timeline
  - plan/evidence side panel
  - Codex proposal placeholder

第 1 周交付：

- 可运行 React skeleton。
- `slowSystem.ts` 类型草案。
- 一条可展示的 mock 场景。
- 一页中文架构理解笔记。

mentor 检查点：

- 实习生能解释为什么 Codex 只能做 proposal。
- UI 没有暗示 React 拥有 `plan_version`。
- demo 能在本地打开并点击。

### 第 2 周：慢系统可视化和 Demo 故事线

目标：让外部观众能看懂慢系统在做什么。

具体任务：

- 实现 `SlowTaskTimeline`，至少覆盖：
  - created
  - planning
  - waiting for slot
  - waiting for tool
  - waiting for user confirmation
  - finalizing
  - completed
- 实现 `PlanVersionPanel`，展示 current 和 superseded 版本。
- 实现 `EvidencePanel`，展示 evidence trust label：
  - authoritative
  - hypothesis
  - untrusted web evidence
- 实现 `ConfirmationPanel`，展示 pending confirmation。
- 加入场景 2 mock data。
- 加入场景 3 mock data。
- 写一个 demo script 文档，说明每个场景应该怎么讲。

第 2 周交付：

- Timeline 能展示核心慢系统状态。
- Plan version 对比可见。
- Evidence trust label 可见。
- UI 中至少可以选择三条 mock 场景。

mentor 检查点：

- 非工程背景的人能看懂 current evidence 和 stale evidence 的区别。
- UI 没有把 tool preview 表达成真实工具已执行。

### 第 3 周：交互流程和状态转换

目标：让 demo 从静态展示变成可交互流程。

具体任务：

- 加入场景控制按钮：
  - start new task
  - send user patch
  - receive late tool result
  - accept confirmation
  - reject confirmation
  - reset scenario
- 实现 frontend demo mode 的本地 mock scenario reducer。
- 增加 action log：
  - user action
  - router decision
  - user patch received
  - plan version advanced
  - stale evidence recorded
  - confirmation required
  - confirmation accepted/rejected
- 增加 Demo Mode / Debug Mode toggle。
- Debug Mode 展示稳定 snapshot 字段，不展示 Python 内部原始结构。

第 3 周交付：

- 覆盖场景 1-4 的可交互 mock demo。
- Action log panel。
- Demo Mode / Debug Mode toggle。
- 前端 reducer 或 adapter 的基础测试。

mentor 检查点：

- material patch 和 non-material patch 有可见区别。
- late tool result 不会偷偷改变 current plan。
- confirmation 必须由用户 action 驱动。

### 第 4 周：后端 Adapter 和现有系统 Snapshot 接入

目标：通过稳定 adapter 接入当前 `voice-agent` 的已有数据。

具体任务：

- 定义前端 `SlowSystemAdapter` interface：
  - `listScenarios()`
  - `loadSnapshot(scenarioId)`
  - `applyDemoAction(action)`
  - `requestCodexProposal(snapshot, intent)`
- 实现 `MockSlowSystemAdapter`。
- 实现 `HttpSlowSystemAdapter`，包含安全错误处理。
- 增加 Python snapshot endpoint 或 CLI-backed snapshot exporter。
- 将当前已有 replay/event 数据映射成 `WorkbenchSnapshot`。
- 增加 Python snapshot mapping tests。
- 确保后端响应不包含本地路径、secret、raw audio、raw provider body、prompt dump。

第 4 周交付：

- 前端可以在 mock adapter 和 HTTP adapter 之间切换。
- 至少一个当前系统 replay/demo case 可以映射为 Workbench snapshot。
- 后端安全测试。
- Handoff 文档中记录 adapter protocol。

mentor 检查点：

- 前端没有 import 或依赖 Python 内部 event 结构。
- Python adapter 返回稳定 workbench snapshot。
- unsafe fields 被拒绝或省略。

### 第 5 周：Codex Proposal Bridge

目标：让 Codex 作为 LLM + 工具黑盒生成 proposal，但不拥有任务事实。

具体任务：

- 实现后端 `CodexProposalBridge` 抽象。
- 先实现 deterministic fake proposal provider。
- 可选：在本地配置或显式 opt-in 后增加 Codex-backed provider。
- 校验 Codex 输出是否符合 proposal schema。
- 增加 proposal status：
  - draft
  - validated
  - accepted
  - rejected
- 前端增加：
  - request proposal
  - inspect proposal evidence refs
  - demo mode accept/reject proposal
  - 展示 backend 为什么拒绝 unsafe proposal
- 增加 invalid proposal tests：
  - 尝试推进 plan version
  - 尝试 authorize tool
  - 包含 unsafe local path
  - 包含 secret-like text
  - 缺少 source evidence refs

第 5 周交付：

- Codex proposal panel 可以使用 fake provider 跑通。
- 如果环境和 mentor 批准，支持可选 Codex-backed proposal path。
- Proposal validation tests。
- UI 中能看到安全解释。

mentor 检查点：

- Codex 可以 propose，但不能直接 mutate task state。
- invalid proposal fail closed。
- 没有 Codex credentials 或本地 Codex 不可用时，demo 仍然可用。

### 第 6 周：Demo 打磨、QA、文档和交接

目标：让项目能被其他工程师接手，也能对外演示。

具体任务：

- 打磨 Demo Mode 的视觉层级。
- 增加 5 分钟演示脚本。
- 增加内部 Debug Mode walkthrough。
- 增加 Workbench README。
- 增加 handoff doc：
  - architecture
  - adapter protocol
  - Codex proposal boundary
  - known limitations
  - next steps
- 跑相关测试。
- 录制短 demo video，或准备现场演示脚本。
- 列出 follow-up backlog。

第 6 周交付：

- Demo-ready React Workbench。
- 至少四条 working scenarios。
- Mock adapter 和 HTTP adapter。
- Fake proposal provider；可选 Codex proposal provider。
- 文档和 handoff。
- Test summary。
- Demo recording 或 presentation script。

mentor 检查点：

- 新工程师能按 README 跑起来。
- 外部观众能在 5 分钟内理解慢系统价值。
- mentor 能基于 handoff 列出下一阶段任务。

## 最终交付清单

实习完成时必须交付：

- 可运行 React Workbench。
- Demo Mode，至少四条场景。
- Debug Mode，能展示 Router、SlowTask、plan version、task event sequence、evidence、stale evidence、confirmation。
- 稳定前端 adapter protocol。
- Mock adapter。
- Python snapshot 或 HTTP adapter。
- Codex proposal bridge，至少包含 fake provider。
- 如获批准且环境可用，可包含 Codex-backed provider。
- Proposal validation tests。
- Frontend reducer 或 adapter tests。
- Backend snapshot / proposal tests。
- Workbench README。
- Handoff document。
- Demo script 或录屏。

## 验收标准

### 产品验收

- Demo Mode 能讲清楚可靠任务推进的故事。
- UI 能让快系统和慢系统的差异可见。
- UI 能让 plan change、stale evidence、confirmation 易于理解。
- demo 不依赖 live provider credentials。

### 工程验收

- React 只拥有 display state。
- 后端拥有事实状态和 proposal validation。
- Codex proposal path 可关闭，关闭后 demo 仍可运行。
- Adapter schema 有文档，足够后续接入。
- 保留现有 `voice-agent` 安全规则。
- 不提交 raw audio、raw trace、provider body、本地路径或 secret。

### 内部调试验收

- Debug Mode 能展示某个 turn 为什么变成 `SPAWN_SLOW_TASK` 或 `PATCH_ACTIVE_SLOW_TASK`。
- Debug Mode 能展示当前 `plan_version`。
- Debug Mode 能把 stale evidence 和 current evidence 分开。
- Debug Mode 能展示 pending confirmation 及其 accepted / rejected 状态。

## Mentor 节奏

建议每周固定节奏：

- 周一：30 分钟计划 checkpoint。
- 周三：30 分钟架构或代码 review。
- 周五：具体 artifact demo checkpoint。

每周五必须回答：

- 这周有什么可以点击或运行？
- 对慢系统边界有什么新理解？
- 当前 blocker 是什么？
- 下周 scope 是否需要调整？

## 风险清单

| 风险 | 可能性 | 影响 | 缓解 |
| --- | --- | --- | --- |
| scope 漂移成重写 SlowTask | 中 | 高 | React 只做 adapter 和展示；任何 backend state change 需要 mentor 批准。 |
| Codex 被误认为事实源 | 中 | 高 | 所有 Codex 输出标记为 proposal；后端校验；UI 展示 accepted/rejected 状态。 |
| 前端过早打磨视觉，协议没跑通 | 中 | 中 | 第 4 周 adapter checkpoint 强制验收。 |
| 后端接入耗时过长 | 中 | 中 | Mock adapter 是一等路径；Python snapshot 可以先只读。 |
| 前端存储不安全原始数据 | 低 | 高 | 增加 safety validation 和 forbidden field tests。 |
| Demo 依赖不可用 Codex 凭证 | 中 | 中 | fake proposal provider 必做；Codex-backed provider 可选。 |

## Stretch Goals

只有必做项全部完成后，才考虑以下扩展：

- Event timeline 可视化 replay scrubber。
- 导入 committed replay fixture 并渲染为 Workbench scenario。
- Qwen proposal 与 Codex proposal side-by-side 对比。
- 导出 redacted demo snapshot JSON。
- 为四条 demo 场景增加 Playwright smoke tests。

## 最终展示建议

最终展示建议控制在 10 分钟：

1. 1 分钟：为什么需要慢系统。
2. 2 分钟：新复杂任务场景。
3. 2 分钟：用户补充约束和 plan version 变化。
4. 2 分钟：stale evidence 场景。
5. 1 分钟：confirmation gate。
6. 1 分钟：Codex proposal 边界。
7. 1 分钟：如何接入当前 `voice-agent`。

## 成功定义

这次实习成功的标志是：慢系统从抽象架构变成可点击、可讲述、可调试的交互体验。

- 外部观众能理解为什么它比简单 `ASR -> LLM -> TTS` 级联更可靠。
- 内部开发者能用它观察快慢系统耦合。
- 实习生留下可运行 artifact、清楚的协议文档、测试和后续集成路径。
