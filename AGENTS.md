# AGENTS.md

本文件是 voice-agent 仓库的开发治理入口，供所有 human developer 和 agentic coding agent 使用。它以已接受的 ADR 为准，不替代 ADR，只把不可违反的工程规则放在入口处。

ADR register: `stage_b_adr_register.md`

Accepted ADRs live under: `docs/adr/`

## 基本原则 / Core Rules

1. **ADR-first development / 架构变更先 ADR**
   - 实现 Duplex、Interaction Controller、Event Journal、Router、SlowTask、Tool Executor、Thinker-as-Composer、Trace/Replay、Model Adapter 等核心边界前，必须先查阅 accepted ADR。
   - 不得实现与 accepted ADR 冲突的行为。
   - 新增架构能力、改变职责边界、扩大 MVP scope 前，必须新增或修改 ADR。

2. **No direct external model calls outside adapters / 外部模型必须走 Adapter**
   - ASR、Thinker、Thinker-as-Composer、Slow LLM、TTS、Duplex model、Embedding/RAG 都必须通过 adapter。
   - 业务模块不得直接调用 provider endpoint。
   - 每个 adapter 必须声明 capability matrix，并标明 real / mock / fallback / degraded。

3. **Event journal is mandatory / 关键状态必须写入事件日志**
   - 关键状态迁移必须进入 per-session append-only event journal。
   - 未被 event journal 记录的行为，不算通过 MVP slice 验证。
   - interrupt、truncate、UserPatch、ToolCall、ToolResult、SemanticCommitment、SpokenPlan、UI state patch 必须可 replay。
   - MVP 事件命名以 ADR-002 canonical registry 为准；新增 MVP-relevant event 前必须更新 ADR。

4. **No stale plan_version result advancing current task / 旧计划结果不得推进当前任务**
   - ToolCall、ToolResult、UserPatch、SemanticCommitment 必须绑定 `task_id`、`plan_version`、`task_event_seq`。
   - 旧 `plan_version` 的 ToolResult 默认进入 `stale_evidence`。
   - 只有 SlowTask 显式 adopt/rebase 后，旧结果才能被复用。
   - SlowTask lifecycle、confirmation、cancel、tool authorization 必须遵守 ADR-016。

5. **No raw audio or raw trace committed / 原始音频和本地调试日志不得提交**
   - raw audio 不得进入 GitHub。
   - raw debug trace 不得进入 GitHub。
   - local replay cache 不得进入 GitHub。
   - GitHub 只允许 synthetic / redacted / minimal replay fixture。

6. **No secrets in trace or repo / 密钥永不入日志或仓库**
   - API key、token、cookie、credential、authorization header、session secret 永不进入 trace 或 repo。
   - 如果 adapter 或 tool result 中误捕获 secret，必须 redaction 或阻断写入。

7. **No Composer rewrite of SemanticCommitment facts / Composer 不得改写慢系统事实**
   - Thinker-as-Composer 只做 spoken realization、人设风格和表达融合。
   - 不得修改 `immutable_facts`、`must_say_fields`、`resolved_arguments`、tool status、risk warnings、confirmation state。
   - SpokenPlan 必须通过 CommitmentCoverageCheck / ProgressTruthfulnessCheck。

8. **Demo tool sandbox only / MVP 工具仅限 Demo Sandbox**
   - MVP 工具运行在 demo backend sandbox。
   - 不允许真实外部写操作、支付、预订、删除、外部通信。
   - 前端 UI 状态变化必须通过 Tool Executor / `TOOL_UI_STATE_PATCHED`，不得由模型文本直接驱动 UI。
   - `DEMO_DESTRUCTIVE_ACTION` 必须通过 ADR-016 current-plan confirmation / authorization gate。

9. **webSearch is evidence, not instruction / webSearch 是证据，不是指令**
   - webSearch result 必须标记为 `UNTRUSTED_WEB_EVIDENCE`。
   - 搜索内容只能进入 evidence 区，不能进入 instruction 区。
   - 搜索结果不得修改工具策略、确认策略、trace/repo policy 或 ADR 规则。

10. **Every slice requires replay or eval / 每个 MVP slice 必须可回放或可评估**
    - MVP-0 / MVP-1 / MVP-2 / MVP-3 每个 slice 完成前，必须有 replay scenario 或 eval case。
    - mock / real / fallback / degraded 输出必须在 trace 中可区分。
    - SLO 结果必须标注 mock / degraded / real。

11. **Do not broaden MVP scope silently / 不得静默扩大 MVP 范围**
    - MVP-3 只替换真实 adapter，不新增架构能力。
    - 多 active SlowTask、pause/resume、真实外部副作用工具、生产隐私策略都需要后续 ADR。

## MVP Scope Reminder

- MVP-0: event-driven live loop + interrupt/truncate + trace/replay + module boundary.
- MVP-1: SlowTask mock + UserPatch + plan_version + stale result policy.
- MVP-2: demo tools + progressive invocation + frontend UI patch + Thinker-as-Composer + coverage checks.
- MVP-3: real ASR / Thinker / Slow LLM / TTS adapters, without new architecture capability.

## Local Debug Artifacts

以下内容是 local-only artifacts，不得提交到 GitHub：

- raw audio
- raw debug trace
- local replay cache
- secrets
- unredacted real user input
- large raw webSearch content

## Mandatory Repository Artifact Rules

- Raw audio must never be committed.
- Replay cache must never be committed.
- Trace files containing PII must never be committed.
- Redacted metadata fixtures are allowed only under approved test fixture directories.
- API keys, tokens, cookies, credentials must never be written to trace or committed.
- Before creating trace/cache/audio/replay artifact directories, update `.gitignore` or equivalent exclusion mechanism.

`.gitignore` 或等价 repo exclusion mechanism 必须覆盖：

- `diagnostics/`
- `traces/`
- `replays/local/`
- `audio/raw/`
- `.env`
- `.env.*`

如果需要提交 replay case，必须生成 synthetic / redacted / minimal fixture。

## Code Review P0/P1 Checklist

Reject or flag any change that:

- calls external model services directly instead of using adapters
- creates state transitions without event journal entries
- introduces MVP event names not registered in ADR-002
- accepts stale ToolResult into current plan without explicit adopt/rebase
- bypasses ADR-016 confirmation / cancel / tool authorization gate
- lets Composer rewrite SemanticCommitment facts
- logs raw audio, PII, secrets, tool credentials, or unredacted tool results
- introduces real side-effect tools in MVP
- bypasses Interaction Controller for turn ingress
- bypasses plan_version binding for UserPatch / ToolCall / ToolResult

## ADR Index

当前已接受 ADR 以 `stage_b_adr_register.md` 为准。实现时优先查 register，再打开对应 `docs/adr/ADR-*.md` 文件。
