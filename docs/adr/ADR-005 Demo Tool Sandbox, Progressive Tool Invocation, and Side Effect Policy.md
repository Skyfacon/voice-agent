# ADR-005 Demo Tool Sandbox, Progressive Tool Invocation, and Side Effect Policy

## Status

accepted

## Context

当前 live 语音 Agent 仍处于 demo 架构阶段。工具调用的目标不是直接操作真实世界系统，而是配合前端页面和 demo backend 展示 Agent “边说边做”的能力。

Demo 工具包括但不限于：

- 手电筒
- 备忘录
- 天气查询
- 闹钟
- webSearch

这些工具可以抽象为统一 Tool，但它们在 MVP 阶段应运行在 demo sandbox 中：可以改变 demo 页面状态、mock 后端状态或读取受控外部信息，但不应执行真实世界不可逆操作。

同时，工具调用需要支持渐进式加载和渐进式执行，而不是只有一次性 ToolCall / ToolResult。语音场景里，用户可能边说边补充参数，SlowTask 也可能需要先展示工具准备、参数预览、执行中状态和 UI patch。

## Decision

MVP 工具体系采用 demo backend sandbox + progressive tool invocation protocol。

所有工具都必须通过 Tool Adapter / Tool Executor 调用，不允许 Slow Agent 直接调用外部服务。

MVP 允许以下工具类别：

- `READ_ONLY_DEMO`
  读取 demo backend 状态，例如读取当前备忘录列表。

- `READ_ONLY_EXTERNAL`
  读取外部但低风险信息，例如天气 API。

- `EXTERNAL_READ_UNTRUSTED`
  外部不可信内容读取，例如 webSearch、RAG、网页摘要。

- `DEMO_STATE_WRITE`
  写入 demo backend 状态，例如新增备忘录。

- `DEMO_DEVICE_ACTION`
  改变前端模拟设备状态，例如打开/关闭手电筒。

- `DEMO_SCHEDULE_ACTION`
  创建或修改 demo 闹钟 / 计时器。

Tool `side_effect_class` taxonomy:

- `READ_ONLY`
- `DRY_RUN`
- `SANDBOX_WRITE`
- `DEMO_DESTRUCTIVE_ACTION`
- `EXTERNAL_WRITE`
- `EXTERNAL_COMMUNICATION`
- `BOOKING_OR_PAYMENT`
- `DELETION`

MVP 允许以下 `side_effect_class`：

- `READ_ONLY`
- `DRY_RUN`
- `SANDBOX_WRITE`
- `DEMO_DESTRUCTIVE_ACTION`

MVP 禁止以下真实外部副作用类别：

- `EXTERNAL_WRITE`
- `EXTERNAL_COMMUNICATION`
- `BOOKING_OR_PAYMENT`
- `DELETION`
- account / identity / credential modification

这些类别保留为目标架构 future class，在 demo 阶段默认 blocked。

`DEMO_DESTRUCTIVE_ACTION` 与真实 `DELETION` 是不同的 `side_effect_class`。

`DEMO_DESTRUCTIVE_ACTION` 必须满足：

- sandbox-only
- no real user data
- no external system mutation
- reversible or resettable
- traceable
- light confirmation required if user-visible

例如：删除 demo 备忘录、覆盖 demo 闹钟、取消 demo 闹钟可以是 `DEMO_DESTRUCTIVE_ACTION`；删除真实文件、真实账号数据、真实联系人、真实订单或真实云端资源属于 `DELETION`，MVP 禁止。

每个 ToolCall 必须包含：

- `tool_call_id`
- `task_id`
- `plan_version`
- `task_event_seq`
- `caused_by_event_id`
- `tool_name`
- `tool_adapter_id`
- `tool_manifest_version`
- `risk_class`
- `side_effect_class`
- `idempotency_key`
- `authorization_event_id` optional
- `input_arguments`
- `input_provenance`
- `progressive_mode`
- `expected_result_type`

渐进式工具调用协议至少支持以下事件：

- `TOOL_MANIFEST_LOADED`
- `TOOL_ARGUMENTS_PARTIAL`
- `TOOL_ARGUMENTS_READY`
- `TOOL_PREVIEW_AVAILABLE`
- `TOOL_EXECUTION_AUTHORIZED`
- `TOOL_EXECUTION_STARTED`
- `TOOL_PROGRESS_UPDATED`
- `TOOL_UI_STATE_PATCHED`
- `TOOL_RESULT_RECEIVED`
- `TOOL_EXECUTION_FAILED`
- `TOOL_CALL_RETRYING`
- `TOOL_EXECUTION_CANCEL_REQUESTED`
- `TOOL_EXECUTION_CANCELLED`
- `TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS`

其中：

- `TOOL_ARGUMENTS_PARTIAL` 表示参数还不完整，可以继续从用户输入或上下文补齐。
- `TOOL_ARGUMENTS_READY` 表示参数足够执行。
- `TOOL_PREVIEW_AVAILABLE` 用于展示执行预览，例如“将添加一条备忘录：买牛奶”。
- `TOOL_EXECUTION_AUTHORIZED` 表示 Tool Executor 已确认 current `plan_version`、side-effect policy、参数 provenance 和必要确认均满足。
- `TOOL_EXECUTION_STARTED` 是实际执行开始事件；不得在 blocked / stale / missing confirmation 情况下产生。
- `TOOL_UI_STATE_PATCHED` 用于前端 demo 状态同步，例如手电筒 UI 变为 on。
- `TOOL_PROGRESS_UPDATED` 用于长工具，例如 webSearch 的搜索中、读取中、总结中。
- `TOOL_RESULT_RECEIVED` 是最终工具结果。
- `TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS` 表示缺少 SlowTask resolved arguments 或关键参数 provenance，工具不得执行。

确认策略：

- 低风险 demo action 默认不强制确认。
- 参数不完整时必须澄清，不能猜测关键参数。
- `DEMO_DESTRUCTIVE_ACTION` 需要轻确认，例如删除 demo 备忘录、覆盖 demo 闹钟、取消 demo 闹钟。
- 轻确认由 SlowTask `confirmation_state` 拥有，并通过 ADR-016 的 `CONFIRMATION_REQUIRED` -> `USER_CONFIRMATION_RECEIVED` -> `CONFIRMATION_ACCEPTED` / `CONFIRMATION_REJECTED` 完成。
- `DEMO_DESTRUCTIVE_ACTION` 执行前，Tool Executor 必须看到 current-plan `CONFIRMATION_ACCEPTED` 并把它写入 `authorization_event_id`。
- 任何真实外部副作用类别默认 blocked，即使 Slow Agent 请求也不得执行。
- 如果未来开启真实外部副作用工具，必须另行 ADR 定义确认、回滚、补偿和权限策略。

webSearch 作为工具接入，但其结果属于 `EXTERNAL_READ_UNTRUSTED`：

- 可被 Slow Agent 作为 evidence 使用。
- 不得作为系统指令、工具策略、隐私策略或确认策略。
- 不得覆盖 architecture rules。
- 需要在后续 ADR-014 中纳入 untrusted external content boundary。

Tool execution policy：

1. Router 只决定是否进入慢任务或 patch active task，不直接授权工具。
2. Slow Agent 可以提出 ToolCall 和 partial arguments。
3. SlowTask 必须先产出 current-plan resolved arguments 或明确的 insufficient-evidence / clarification event。
4. Tool Executor 负责加载 tool manifest、校验参数、校验 current `plan_version`、校验 confirmation / authorization、执行 demo backend 调用、产出 progressive events。
5. Frontend 通过 `TOOL_UI_STATE_PATCHED` / progress events 展示工具状态。
6. 所有 ToolCall、progressive event、ToolResult 都必须写入 event journal，并使用 ADR-002 canonical event names。
7. 所有 ToolCall / ToolResult 必须遵守 ADR-004 plan_version 和 stale result policy。
8. Tool lifecycle、confirmation ownership、cancel/retry/failure transition 以 ADR-016 为准。

## Alternatives Considered

1. 继续沿用真实工具风控 ADR。
   安全但过重，不符合当前 demo 目标，会让手电筒、备忘录、闹钟等 demo action 过度确认。

2. Demo 工具完全自由调用，不做 side effect class。
   实现快，但后续很难迁移到真实工具体系，也无法评估误触发和 replay。

3. 工具只做一次性 ToolCall / ToolResult。
   简单，但无法展示渐进式加载、参数补全、执行中状态和 UI patch，不符合 live 语音 demo 体验。

4. 前端直接根据模型文本改变 UI。
   看起来快，但绕过 Tool Executor 和 event journal，会破坏 trace/replay 和安全边界。

## Consequences

正向结果：

- Demo 可以展示真实“边说边做”的交互感。
- 手电筒、备忘录、天气、闹钟、webSearch 都能统一抽象为工具。
- 前端页面能订阅渐进式工具状态，而不是等待最终结果。
- demo side effect 被限制在 sandbox，不会触发真实外部风险。
- ToolCall schema 仍保留未来迁移到真实工具的关键字段。
- webSearch 从一开始被建模为不可信外部证据。

代价：

- Tool protocol 比一次性调用更复杂。
- 前端和 demo backend 需要支持工具状态 patch。
- 需要维护 tool manifest version。
- Tool Executor 要区分 demo side effect 和真实 external side effect。
- 某些 demo action 的确认边界需要单独设计，例如删除、覆盖、取消。

## Impacted Modules

- Slow Agent
- Tool Executor
- Tool Adapter
- Demo Backend
- Frontend Tool UI
- Router
- SlowTask
- Event Journal
- Trace / Replay
- SemanticCommitment
- Composer
- Privacy / Redaction Policy
- Untrusted External Content Boundary

## Validation Method

MVP-2 必须验证：

1. 手电筒工具可以通过 `DEMO_DEVICE_ACTION` 改变前端 demo 状态。
2. 备忘录工具可以通过 `DEMO_STATE_WRITE` 新增 demo note。
3. 闹钟工具可以通过 `DEMO_SCHEDULE_ACTION` 创建 demo alarm。
4. 天气工具可以通过 `READ_ONLY_EXTERNAL` 或 mock API 返回结果。
5. webSearch 工具结果被标记为 `EXTERNAL_READ_UNTRUSTED`。
6. Tool manifest 可以被加载并记录 `TOOL_MANIFEST_LOADED`。
7. 参数不完整时产生 `TOOL_ARGUMENTS_PARTIAL`，不会直接执行。
8. 参数完整时产生 `TOOL_ARGUMENTS_READY`。
9. 工具执行中可以产生 `TOOL_PROGRESS_UPDATED`。
10. 前端状态变化必须通过 `TOOL_UI_STATE_PATCHED` 记录。
11. ToolResult 必须绑定 `task_id`、`plan_version`、`task_event_seq`。
12. plan_version 变化后，旧 ToolResult 按 ADR-004 stale policy 处理。
13. 真实 `EXTERNAL_WRITE` 类工具在 MVP 中被 Tool Executor 阻止。
14. replay 能重建工具调用、progress、UI patch 和最终结果。
15. `DEMO_DESTRUCTIVE_ACTION` 缺少轻确认时不能执行。
16. 真实 `DELETION` 在 MVP 中必须被 Tool Executor 阻止，不能被 demo destructive action 规则放行。
17. `TOOL_EXECUTION_STARTED` 必须晚于 current-plan `TOOL_EXECUTION_AUTHORIZED`。
18. 缺少 resolved arguments / provenance 时必须产生 `TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS`，不能执行 demo backend call。
19. `DEMO_DESTRUCTIVE_ACTION` 的 `TOOL_EXECUTION_AUTHORIZED` 必须引用 current-plan `CONFIRMATION_ACCEPTED`。

## Open Questions

- 手电筒、备忘录、闹钟的前端状态是否都由 demo backend 作为 source of truth？
- `TOOL_PREVIEW_AVAILABLE` 是否所有 demo write/action 都必须有，还是只在高风险 demo action 中需要？
- webSearch 是否在 MVP-2 接真实搜索 API，还是先 mock 搜索结果？
- Tool manifest 是启动时一次性加载，还是按需渐进式加载？
- 前端 UI patch 的 patch granularity 如何划分，避免过大 patch 降低 replay 可读性？
