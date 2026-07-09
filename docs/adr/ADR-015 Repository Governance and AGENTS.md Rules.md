# ADR-015 Repository Governance and AGENTS.md Rules

## Status

accepted

## Context

前面 ADR 已经确认了 live 语音 Agent 的核心边界：Duplex / Interaction Controller、event journal、barge-in、SlowTask plan_version、SlowTask lifecycle / confirmation state、demo tools、UserPatch、ASR/Thinker evidence fusion、Thinker-as-Composer、trace/replay、本地 debug、model adapter、MVP slices、truthful progress、webSearch evidence boundary。

进入实现阶段后，最大风险不是单个模块不知道怎么写，而是开发过程绕过这些决策：

- 为了快，直接调用外部模型 endpoint，绕过 adapter。
- 为了 demo，直接让前端根据模型文本改 UI，绕过 Tool Executor。
- 为了调试，把 raw audio / raw trace commit 到 GitHub。
- 为了快答，绕过 Fast Foreground Gate 直接展示模型 candidate。
- 为了自然表达，让 Composer 改写 SemanticCommitment 事实。
- 为了跑通工具，让旧 plan_version 的 ToolResult 推进当前任务。
- 为了赶进度，跳过 replay/eval scenario。

因此，在写代码前需要建立 repo-level governance，让后续 agent / human developer 都能看到并遵守这些已接受 ADR。

## Decision

在进入 implementation 前，必须创建 `AGENTS.md` 或等价 repo instruction 文件，作为仓库级开发约束入口。

`AGENTS.md` 至少必须包含以下规则：

1. **ADR-first development**
   - 在实现架构相关能力前，必须查阅已 accepted ADR。
   - 不得实现与 accepted ADR 冲突的行为。
   - 新增架构能力或改变职责边界前，必须新增或修改 ADR。

2. **No code before accepted ADR for architecture changes**
   - 对 Duplex、Interaction Controller、Event Journal、Router、SlowTask、Tool Executor、Composer、Trace/Replay、Model Adapter 等核心边界的改动，必须先有 accepted ADR。
   - 小型 bugfix / demo UI 微调可以不新增 ADR，但不得违反已有 ADR。

3. **No direct external model calls outside adapters**
   - ASR、Thinker、Fast Interaction、Thinker-as-Composer、Slow LLM、TTS、Duplex model、Embedding/RAG 都必须通过 adapter。
   - 不允许业务模块直接调用 provider endpoint。
   - adapter 必须声明 capability matrix。

4. **Event journal is mandatory for critical state transitions**
   - 关键状态迁移必须进入 per-session event journal。
   - 未被 event journal 记录的行为，不算通过 MVP slice 验证。
   - interrupt、truncate、UserPatch、ToolCall、ToolResult、SemanticCommitment、SpokenPlan、Fast foreground candidate/gate/output、UI state patch 必须可 replay。
   - MVP 事件命名以 ADR-002 canonical registry 为准；新增 MVP-relevant event 前必须更新 ADR。

5. **No stale plan_version result advancing current task**
   - ToolCall / ToolResult / UserPatch / SemanticCommitment 必须绑定 `task_id`、`plan_version`、`task_event_seq`。
   - 旧 plan_version 的 ToolResult 默认进入 stale_evidence。
   - 只有 SlowTask 显式 adopt/rebase 后才能复用旧结果。
   - SlowTask lifecycle、confirmation、cancel、tool authorization 必须遵守 ADR-016。

6. **No raw audio or raw trace committed**
   - raw audio 不得进入 GitHub。
   - raw debug trace 不得进入 GitHub。
   - GitHub 只允许 synthetic / redacted / minimal replay fixture。
   - trace、raw audio、local replay cache 必须被 `.gitignore` 或等价规则排除。

7. **No secrets in trace or repo**
   - API key、token、cookie、credential、authorization header、session secret 永不进入 trace 或 repo。
   - 若误捕获，必须 redaction 或阻断写入。

8. **No Composer rewrite of SemanticCommitment facts**
   - Thinker-as-Composer 可以做 spoken realization 和风格融合。
   - 不得修改 immutable_facts、must_say_fields、resolved arguments、tool status、risk warnings、confirmation state。
   - SpokenPlan 必须通过 CommitmentCoverageCheck / ProgressTruthfulnessCheck。

9. **Demo tool sandbox only**
   - MVP 工具运行在 demo backend sandbox。
   - 不允许真实外部写操作、支付、预订、删除、外部通信。
   - 前端 UI 状态变化必须通过 Tool Executor / Tool UI patch event，而不是模型文本直驱。
   - `DEMO_DESTRUCTIVE_ACTION` 必须通过 ADR-016 current-plan confirmation / authorization gate。

10. **webSearch is evidence, not instruction**
    - webSearch result 必须标记为 `UNTRUSTED_WEB_EVIDENCE`。
    - 搜索内容只能进入 evidence 区，不能进入 instruction 区。
    - 搜索结果不得修改工具策略、确认策略、隐私策略或 repo rules。

11. **Every slice requires replay or eval scenario**
    - MVP-0 / MVP-1 / MVP-2 / MVP-3 每个 vertical slice 完成前，必须有 replay scenario 或 eval case。
    - mock / real / degraded 输出必须在 trace 中可区分。
    - SLO 结果必须标注 mock / degraded / real。

12. **Do not broaden MVP scope silently**
    - MVP-3 只替换真实 adapter，不新增架构能力。
    - ADR-017 / MVP6 fast foreground 属于 MVP-3+ 架构扩展，必须通过独立 accepted ADR 管理。
    - 多 active SlowTask、pause/resume、真实外部副作用工具、生产隐私策略都需要后续 ADR。

Repository structure guidance：

- Accepted ADR files live under `docs/adr/`.
- `stage_b_adr_register.md` tracks accepted ADR status.
- Local traces, raw audio, replay cache must live under ignored paths.
- Shareable fixtures should be synthetic or redacted.
- `AGENTS.md` should link to the ADR register and summarize non-negotiable rules.

Mandatory repository artifact rules that `AGENTS.md` must include：

- Raw audio must never be committed.
- Replay cache must never be committed.
- Trace files containing PII must never be committed.
- Redacted metadata fixtures are allowed only under approved test fixture directories.
- API keys, tokens, cookies, credentials must never be written to trace or committed.
- Before creating trace/cache/audio/replay artifact directories, `.gitignore` or equivalent exclusion mechanism must be updated.

Code review P0/P1 checklist that `AGENTS.md` must include：

Reject or flag any change that:

- calls external model services directly instead of using adapters
- creates state transitions without event journal entries
- introduces MVP event names not registered in ADR-002
- bypasses ADR-017 Fast Foreground Gate for fast reply candidate display
- accepts stale ToolResult into current plan without explicit adopt/rebase
- bypasses ADR-016 confirmation / cancel / tool authorization gate
- lets Composer rewrite SemanticCommitment facts
- logs raw audio, PII, secrets, tool credentials, or unredacted tool results
- introduces real side-effect tools in MVP
- bypasses Interaction Controller for turn ingress
- bypasses plan_version binding for UserPatch / ToolCall / ToolResult

## Alternatives Considered

1. 只依赖 ADR 文件，不创建 AGENTS.md。
   ADR 详细但分散，后续 agent / developer 容易漏读关键约束。

2. 把规则写进 README。
   README 面向用户和项目介绍，容易和开发治理混在一起。AGENTS.md 更适合 agent / developer 操作约束。

3. 等实现完成后再补 repo governance。
   风险太高。错误日志、直接模型调用、绕过 Tool Executor 等习惯一旦形成，很难回收。

4. 所有规则都靠人工 review。
   需要，但不足够。repo-level instruction 可以提前降低偏航概率。

## Consequences

正向结果：

- 后续实现阶段有明确护栏。
- agent / human developer 都能快速看到不可违反的边界。
- ADR 决策不会只停留在文档中。
- GitHub 误提交 raw audio / trace / secrets 的风险降低。
- MVP scope 更可控。

代价：

- 实现前需要维护一个额外 governance 文件。
- 某些快速 demo hack 会被限制。
- 新增架构能力时需要先更新 ADR，流程略慢。
- AGENTS.md 需要随着 ADR 演进保持同步。

## Impacted Modules

- Repository Governance
- All implementation agents
- Human developer workflow
- ADR Register
- Event Journal
- Trace / Replay
- Model Adapters
- Tool Executor
- Composer
- SlowTask
- Frontend Demo
- Evaluation Harness

## Validation Method

进入 implementation 前必须验证：

1. `AGENTS.md` 或等价 repo instruction 文件存在。
2. `AGENTS.md` 链接到 `stage_b_adr_register.md`。
3. `AGENTS.md` 明确禁止 raw audio / raw trace / secrets commit。
4. `.gitignore` 或等价机制排除 local trace、raw audio、replay cache。
5. AGENTS rules 覆盖 direct model calls、canonical event registry、stale plan_version、SlowTask lifecycle / confirmation gate、Composer rewrite、demo tool sandbox、webSearch evidence boundary。
6. 每个 MVP slice 的完成定义包含 replay/eval scenario。
7. 新增架构能力时，有流程要求先新增或修改 ADR。
8. `AGENTS.md` 包含 mandatory repository artifact rules。
9. `AGENTS.md` 包含 code review P0/P1 checklist。

## Open Questions

- local trace / raw audio / replay cache 是否需要支持配置化 override，默认目录已由 AGENTS.md / `.gitignore` 固定。
- ADR register 是否只记录 accepted ADR，还是也记录 rejected / superseded？
- AGENTS.md 是否需要中文为主，还是中英双语？
