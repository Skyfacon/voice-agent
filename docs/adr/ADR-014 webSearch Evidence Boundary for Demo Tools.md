# ADR-014 webSearch Evidence Boundary for Demo Tools

## Status

accepted

## Context

当前工具调用主要通过自封装 demo backend 服务实现，例如手电筒、备忘录、天气、闹钟等。这些工具服务运行在 demo sandbox 内，目标是驱动网页 demo 的 UI 状态和演示“边说边做”的能力。

因此，不需要把所有 ToolResult 都视为高风险外部 prompt injection 来源。对于自封装 demo backend 产生的结构化结果，可以作为 trusted demo tool result 处理。

但 webSearch 不同。webSearch 会引入真实网页内容或搜索摘要，内容可能包含错误信息、过时信息、广告、无关文本，或指令性文本，例如“忽略之前的规则”。即使当前目标只是网页 demo，也需要一个轻量边界，避免 Slow Agent 或 Thinker-as-Composer 把网页内容当作系统指令或权威事实。

## Decision

区分 demo backend tool result 与 webSearch evidence。

Demo backend tool results 默认属于：

- `TRUSTED_DEMO_TOOL_RESULT`

适用于：

- 手电筒状态
- 备忘录 demo state
- 闹钟 demo state
- demo weather mock result
- demo backend UI patch result

Low-risk provider API results from `READ_ONLY_EXTERNAL` tools, such as a weather API, are not demo backend state but may be treated as:

- `EXTERNAL_READ_PROVIDER_RESULT`

Only structured provider fields normalized by the Tool Adapter may receive this trust label. Free-form provider text, webpage text, search snippets, RAG passages, or any content that can contain instructions must be marked `UNTRUSTED_WEB_EVIDENCE` or an equivalent untrusted evidence class.

这些结果可以用于：

- 更新 demo frontend state
- 生成 SemanticCommitment 中的 demo tool status
- 触发 `TOOL_UI_STATE_PATCHED`
- replay demo UI state

但仍必须遵守 ADR-009：

- 不能把 demo backend action 说成真实手机设备动作
- 不能把 demo dry-run 说成真实外部操作完成
- 不能越过 SemanticCommitment / SpokenPlan coverage check

webSearch results 默认属于：

- `UNTRUSTED_WEB_EVIDENCE`

webSearch evidence 可以用于：

- 查询信息
- 生成摘要
- 比较候选答案
- 为用户提供带来源的回答
- 辅助 SlowTask reasoning

webSearch evidence 不允许用于：

- 覆盖 system / developer / architecture instructions
- 修改 tool policy
- 修改 confirmation policy
- 修改 trace / repo policy
- 请求泄露 prompt、token、API key、credential
- 请求执行未授权工具
- 请求忽略 ADR / repo rules
- 作为无 attribution 的权威系统事实
- 直接驱动 demo backend action

webSearch ToolResult 至少包含：

- `tool_call_id`
- `task_id`
- `plan_version`
- `source_type`
- `trust_level = UNTRUSTED_WEB_EVIDENCE`
- `query`
- `retrieved_at`
- `results`
- `source_title`
- `source_url`
- `snippet_or_summary`
- `raw_content_ref` if stored locally
- `content_hash` if available
- `redaction_status`

Prompt / context boundary：

- webSearch 内容必须放入 evidence 区，不得放入 instruction 区。
- SlowTask 可以阅读 webSearch evidence，但不得执行其中的指令性文本。
- 如果网页内容包含“忽略之前规则”“调用某工具”“泄露系统提示”等文本，只能作为网页内容被总结或忽略，不能变成系统行为。
- Thinker-as-Composer 表达搜索结果时应使用 attribution 或降格表达，例如“搜索结果显示”“网页摘要里提到”“我查到的结果里有一条说”。
- 对 demo 阶段，不强制复杂 prompt injection detector，但至少需要 source/trust 标记和简单 eval case。

Trace / repo policy：

- webSearch raw content 可进入 local debug trace。
- webSearch 大段真实网页原文不进入 GitHub fixture。
- GitHub fixture 应使用 mock search result、synthetic result 或 redacted summary。
- source URL / title / short snippet 可以在 redacted fixture 中保留，前提是不包含敏感内容。

## Alternatives Considered

1. 所有 ToolResult 都按 untrusted external content 处理。
   安全但过重，不符合 demo backend 工具的性质，也增加无谓复杂度。

2. webSearch 结果完全信任。
   实现简单，但容易让网页内容污染 SlowTask prompt 和 Composer 表达。

3. 禁用 webSearch。
   最安全，但削弱 demo 工具能力，也不符合 webSearch 作为 Tool 的目标。

4. 为 demo 阶段实现完整 prompt injection 防御。
   过重。当前只需要轻量 evidence boundary、prompt 分区和 eval case。

## Consequences

正向结果：

- 自封装 demo tools 保持简单，不被生产级外部内容策略拖慢。
- webSearch 作为唯一真实外部文本入口有明确边界。
- SlowTask 可以使用搜索结果，但不会把网页文本当系统指令。
- Thinker-as-Composer 能自然表达搜索结果，同时避免过度权威化。
- 与 ADR-005 demo tool sandbox、ADR-009 Composer contract、ADR-010 repo-safe trace policy 对齐。

代价：

- webSearch ToolResult 需要比普通 demo tool result 更多 provenance 字段。
- Prompt 需要区分 instruction 区和 evidence 区。
- 对 prompt injection 的防护是轻量的，不是生产级完整方案。
- 搜索结果回答可能需要 attribution，稍微增加口语表达成本。

## Impacted Modules

- webSearch Tool
- Tool Executor
- Demo Backend
- SlowTask
- Slow Agent Adapter
- Thinker-as-Composer
- SemanticCommitment
- SpokenPlan
- Event Journal
- Trace / Replay
- Repository Governance
- Evaluation Harness

## Validation Method

MVP-2 / MVP-3 必须验证：

1. demo backend tool result 被标记为 `TRUSTED_DEMO_TOOL_RESULT`。
2. structured low-risk weather API result 可以被标记为 `EXTERNAL_READ_PROVIDER_RESULT`，但不得进入 instruction 区。
3. webSearch result 被标记为 `UNTRUSTED_WEB_EVIDENCE`。
4. webSearch 内容进入 SlowTask evidence 区，而不是 instruction 区。
5. webSearch result 不得直接触发 demo backend action。
6. 网页内容中的“忽略之前规则”不会被执行。
7. SemanticCommitment 引用 webSearch 内容时保留 source refs。
8. Thinker-as-Composer 表达 webSearch 内容时使用 attribution 或降格表达。
9. webSearch raw content 不进入 GitHub fixture。
10. replay 能重建 webSearch query、result summary、source refs 和最终表达链路。

## Open Questions

- MVP-2 webSearch 是真实 API、浏览器抓取，还是 mock search result？
- `snippet_or_summary` 最大长度是否需要限制？
- source URL 是否必须保留，还是 demo mock 可只保留 source label？
- prompt injection eval 是否只做一条 synthetic case？
- Thinker-as-Composer 对搜索结果的 attribution 是否模板化？
