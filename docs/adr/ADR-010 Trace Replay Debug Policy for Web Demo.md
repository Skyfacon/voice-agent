# ADR-010 Trace / Replay Debug Policy for Web Demo

## Status

accepted

## Context

当前 live 语音 Agent 的目标形态是网页 demo。Trace / replay 的主要价值是帮助本地开发、调试 live loop、复现 interrupt、验证 UserPatch、ToolCall、SpokenPlan、前端 UI patch 等链路。

因此，当前阶段不应采用过重的生产级隐私策略。调试便利性优先，但必须守住几个硬边界：

- raw audio 不进入 GitHub
- raw logs / traces 不进入 GitHub
- API key / token / cookie / credential 不进入 GitHub
- 可分享复现材料必须是 synthetic、redacted 或 minimal fixture

换句话说：本地 debug trace 可以详细；repo / GitHub / shareable artifact 必须严格受控。

## Decision

采用 debug-first, repo-safe trace policy。

Trace 数据按存储域分级：

1. `LOCAL_DEBUG_TRACE`
   本地详细 trace，用于开发调试和 replay。可以包含 event journal、ASR/Thinker output、Fast Interaction output、foreground candidate / gate / committed / discarded output、UserPatch、SlowTask state、ToolCall/ToolResult、demo backend state patch、SpokenPlan、coverage check result。

2. `LOCAL_RAW_AUDIO`
   本地原始音频，仅 dev/debug opt-in。用于排查 VAD、Duplex、barge-in、ASR/Thinker audio understanding 问题。

3. `SHAREABLE_REPLAY`
   可分享的复现材料，必须 synthetic、redacted 或最小化，不包含 raw audio、raw trace、secret、真实敏感输入。

4. `GITHUB_ALLOWED`
   可以进入仓库的内容，仅限 synthetic fixture、redacted sample、schema example、hand-written minimal replay case。

5. `NEVER_COMMIT`
   永远不得进入 GitHub / repo 的内容，包括 raw audio、raw trace、API key、token、cookie、credential、authorization header、session secret、真实用户敏感输入、大段外部网页原文。

默认策略：

- event journal / local debug trace 默认开启。
- raw audio 默认关闭，但 dev/debug 可以显式开启。
- raw audio 本地保留 TTL 建议不超过 7 天。
- raw audio 不自动上传、不自动同步、不 commit。
- raw trace 不 commit。
- secrets 永不记录；如果误捕获，必须 redaction 或阻断写入。
- demo backend state 可以进入 local debug trace。
- ToolCall / ToolResult 可以进入 local debug trace，便于复现 demo 工具状态。
- webSearch 结果可以在 local debug trace 中保留摘要和必要片段，但不应作为 GitHub fixture 原样提交大段真实网页内容。

Redaction timing：

- secret-like content 必须在写入 event journal、local debug trace、replay export 前剥离、redaction 或 blocked。secret 不允许以 raw form 进入任何 trace domain。
- PII / raw user text 可以只在 `LOCAL_DEBUG_TRACE` 中保存，并必须标记 `trace_redaction_level=local_debug`；进入 `SHAREABLE_REPLAY` / `GITHUB_ALLOWED` 前必须转成 synthetic、redacted、summary 或 metadata-only。
- event journal payload 应优先保存 `redacted_text`、`text_ref`、`audio_span_id`、`result_ref`、`evidence_ref`，避免把 raw transcript、raw web content、raw tool payload 无条件内联。
- redaction 失败或疑似 secret 无法安全剥离时，必须阻断写入并记录 `TRACE_WRITE_BLOCKED_SECRET_DETECTED`。

建议配置默认值：

- `local_debug_trace_enabled = true`
- `raw_audio_enabled = false`
- `raw_audio_retention_days = 0`
- `dev_debug_raw_audio_retention_days <= 7`
- `cross_machine_raw_audio_sync = false`
- `github_trace_upload = synthetic_or_redacted_only`
- `commit_raw_trace = false`
- `commit_raw_audio = false`
- `credential_trace_policy = never`

Repository boundary：

- trace 输出目录、raw audio 目录、local replay cache 必须进入 `.gitignore` 或等价 repo governance。
- 如果需要提交 replay case，必须从 local trace 派生出 synthetic / redacted fixture。
- 不允许把本地 debug trace 原样提交。
- 不允许把 raw audio 提交。
- 不允许提交真实 API response 中的大段敏感内容或 credential。
- AGENTS.md / repo rules 中必须写明这些约束。

Replay 策略：

- local replay 可以使用详细 local debug trace。
- 没有 raw audio 时，replay 重建事件状态，不重跑音频推理。
- 有 raw audio 且 dev opt-in 时，可以做 audio-level replay。
- Fast foreground replay 使用已记录的 candidate refs、gate decision 和 committed / discarded output，不重跑 Fast Interaction Adapter。
- shareable replay 必须使用 synthetic/redacted 数据。
- replay export 必须执行 repo-safe export gate，检查 raw audio、raw trace、secret、unredacted real user input、大段 raw web content、credential-like header。

Tool / web demo 策略：

- demo backend state patch 可以记录在 local debug trace，便于重建前端状态。
- `TOOL_UI_STATE_PATCHED` 必须可 replay。
- ToolResult 默认可本地记录完整结构，但 export 到 GitHub 前必须 redacted/minimized。
- webSearch 属于 untrusted external evidence，本地可记录用于 debug，但 GitHub fixture 应使用摘要、mock result 或 synthetic result。

Secrets 策略：

- API key、token、cookie、credential、authorization header、session secret 永不进入 trace。
- 如果某 adapter 或 tool result 包含 headers / auth payload，写入 trace 前必须剥离。
- 发现 secret-like 内容时，应产生 `TRACE_SECRET_REDACTION_APPLIED` 或 `TRACE_WRITE_BLOCKED_SECRET_DETECTED`。
- `TRACE_SECRET_REDACTION_APPLIED` 只能表示 secret-like content 已从即将写入或导出的 payload 中移除；不得保留原始 secret 值作为 event payload。

## Alternatives Considered

1. 生产级 privacy-by-default，默认所有文本和工具结果都 redacted。
   隐私最强，但对网页 demo 阶段调试不友好，会降低 replay/debug 效率。

2. 默认全量 trace，完全依赖开发者不要 commit。
   调试方便，但风险过高，尤其 raw audio、raw trace、secret 容易误进 GitHub。

3. 不做 replay trace，只用 console log。
   实现快，但无法系统性复现 interrupt、plan_version、tool progress 和 UI patch。

4. 所有 trace 都可以提交，只要项目是私人仓。
   被拒绝。私人仓也不应包含 raw audio、secret 或原始敏感日志。

## Consequences

正向结果：

- 本地调试体验好，适合网页 demo 快速迭代。
- repo / GitHub 边界明确，降低误提交风险。
- replay 能完整复现 demo tool 和 UI 状态。
- raw audio 可用于困难音频问题，但默认不积累。
- 未来转向生产隐私策略时，可以在此基础上收紧。

代价：

- 需要维护 local trace 与 shareable replay 两套输出语义。
- 需要 `.gitignore` / AGENTS.md / export check 兜底。
- local debug trace 仍可能包含敏感信息，需要开发机本地管理。
- redacted fixture 需要额外生成流程。

## Impacted Modules

- Event Journal
- Trace / Replay
- Access Layer
- Duplex
- ASR Adapter
- Thinker Adapter
- SlowTask
- Tool Executor
- Demo Backend
- Frontend Tool UI
- webSearch Tool
- Thinker-as-Composer
- Talker
- Evaluation Harness
- Config / Environment
- Repository Governance

## Validation Method

MVP-0 / MVP-2 必须验证：

1. local debug trace 默认开启。
2. raw audio 默认关闭。
3. raw audio 开启时只写入 local raw audio storage。
4. raw audio 目录被 repo governance 排除。
5. raw trace 目录被 repo governance 排除。
6. GitHub export 不包含 raw audio。
7. GitHub export 不包含 raw debug trace。
8. API key / token / cookie / credential 不进入 trace。
9. demo backend state patch 可以在 local replay 中重建。
10. `TOOL_UI_STATE_PATCHED` 可以 replay 到前端 demo 状态。
11. shareable replay fixture 必须 synthetic 或 redacted。
12. webSearch 原始大段结果不进入 GitHub fixture。
13. 发现 secret-like 内容时，trace 写入被 redacted 或 blocked。
14. shareable replay export gate 能阻止 unredacted real user input、credential-like header 和 raw tool auth payload。
15. Fast foreground candidate / gate / committed / discarded output 可在 local replay 中重建；shareable export 不包含 raw prompt、provider body、secret 或 unredacted real user input。
16. `TRACE_SECRET_REDACTION_APPLIED` / `TRACE_WRITE_BLOCKED_SECRET_DETECTED` event 本身不包含原始 secret 值。

## Open Questions

- local debug trace 默认采用 JSONL、SQLite，还是内存导出？
- raw audio opt-in 是 session 级开关还是全局 dev config？
- shareable replay export 是否在 MVP-0 就需要，还是 MVP-2 再做？
- secret detection MVP 用规则匹配是否足够？
- local debug trace 是否需要一键清理命令？
- 是否需要在 MVP-0 提供自动检查 `.gitignore` 覆盖范围的 repo governance test？
