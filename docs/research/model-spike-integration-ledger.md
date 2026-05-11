# Model Spike Integration Ledger

## Status

coordination_ledger

## Purpose

本文档用于对齐两条并行 worktree：

- MVP-0 主线：已经实现 Slice 0-9 的 mock runtime skeleton、event journal、replay、adapter capability snapshot、Interaction Controller、mock understanding、mock playback 与 barge-in truncate。
- Model spike research：验证真实或可自部署模型是否能够被压缩进主线 adapter contract，并产出 evidence、capability matrix、degradation proposal 与 integration risk。

本 ledger 不是 runtime implementation plan，不授权接入真实 provider，不改变 ADR、event registry、adapter spec 或 MVP scope。它只回答一个问题：以已完成的 MVP-0 contract shape 为准，model spike 需要提供哪些证据，后续 MVP-3 才能接得上。

## Contract Sources

- `AGENTS.md`
- `docs/implementation/mvp0-backlog.md`
- `docs/research/model-spike-plan.md`
- `docs/research/model-selection.md`
- `docs/specs/model-adapter-capabilities.md`
- `docs/specs/event-registry.md`
- `docs/specs/replay-spec.md`
- `docs/adr/ADR-001 Duplex Boundary and Interaction Controller.md`
- `docs/adr/ADR-003 Barge-in and TTS Truncate Contract.md`
- `docs/adr/ADR-008 ASR Thinker Evidence Fusion and SlowTask-led Conflict Resolution.md`
- `docs/adr/ADR-009 SemanticCommitment and Thinker-as-Composer Contract.md`
- `docs/adr/ADR-011 Model Adapter Capability Contract.md`
- `docs/adr/ADR-012 MVP Vertical Slice and Development SLOs.md`
- `docs/adr/ADR-014 webSearch Evidence Boundary for Demo Tools.md`
- `docs/adr/ADR-016 SlowTask Lifecycle and Confirmation State Contract.md`

如这些文档冲突，按 `AGENTS.md`、accepted ADR、`stage_b_adr_register.md` 优先。

## MVP-0 Contract Snapshot

当前对齐基线：

- Main branch snapshot：`main@61e6afc`。
- MVP-0 closeout implementation：`22ddbf4 fix: harden mvp0 trace and replay safety`。
- Mainline status document：`docs/implementation/mvp0-backlog.md` 已记录 MVP-0 Slice 0-9 完成。
- 主线 closeout 记录：`./scripts/test -q` 在 2026-05-10 通过 139 tests。

因此 model spike 的阶段已经从 “等待 MVP-0 contract 成型” 切换为 “按已完成 MVP-0 contract 产出 adapter-shaped evidence”。每份后续 run report 都应记录参考的 contract snapshot，默认使用 `main@61e6afc`，除非报告中显式声明更新的主线 commit。

当前实装 contract 中需要 model spike 特别贴合的字段包括：

- Capability matrix identity：`adapter_id`、`adapter_type`、`provider`、`model_name`、`deployment_mode`、`endpoint`、`health_status`、`capability_version`、`latency_class`、`error_model`、`timeout_policy`、`retry_policy`、`output_mode`、`config_ref`。
- Capability booleans：`supports_streaming_input`、`supports_streaming_output`、`supports_audio_input`、`supports_audio_output`、`supports_audio_timestamps`、`supports_structured_json`、`supports_tool_calling`、`supports_cancellation`、`supports_emotion`、`supports_audio_caption`、`supports_tts`、`supports_tts_truncate`、`supports_tts_pause_resume`、`supports_semantic_close`、`supports_assistant_directedness`。
- Numeric limits：`max_audio_seconds`、`max_context_tokens`、`max_output_tokens`、`expected_first_token_latency_ms`、`expected_first_audio_latency_ms`。
- Mock/profile bookkeeping：`mocked`、`mock_profile_ref`、`target_architecture_validation`、`unsupported_capabilities`。Real provider spike profiles should use equivalent profile bookkeeping in run reports even if they are not runtime `AdapterCapability` objects yet.
- MVP-0 event metadata refs：`asr_frame_ref`、`semantic_frame_ref`、`audio_ref`、`tts_stream_ref`、`playback_reference_ref`、`playback_span_id`、`audio_span_id`、`turn_id`、`utterance_id`、`output_mode`。

## Current Research Baseline

当前 research worktree 已有以下 model spike baseline：

- `docs/research/spikes/duplex-capability-spike-2026-05-09.md`
- `docs/research/spikes/asr-capability-spike-2026-05-09.md`
- `docs/research/spikes/tts-capability-spike-2026-05-09.md`
- `docs/research/spikes/thinker-capability-spike-2026-05-09.md`
- `docs/research/spikes/slow-llm-capability-spike-2026-05-09.md`
- `docs/research/model-selection.md`

这些文档目前是 evidence research，不是 adapter profile，也不是 integration approval。它们提供 candidate shortlist 与初始 risk map；下一阶段应使用 `main@61e6afc` 的 MVP-0 contract shape，通过 spike-local experiments 产生 observed capability。

## Mainline Sync Points

MVP-0 已完成，因此以下同步点现在都可作为 spike run 的 contract input：

| Sync point | 主线来源 | 当前状态 | spike 使用方式 |
| --- | --- | --- | --- |
| Capability snapshot shape | MVP-0 Slice 2 / `src/voice_agent/adapters/capabilities.py` / `docs/specs/model-adapter-capabilities.md` | 已实现 | 确认 spike result 是否能填满 required capability fields，并显式列出 `unsupported_capabilities`。 |
| Audio ingress and Duplex evidence shape | MVP-0 Slice 5 / `src/voice_agent/duplex/mock_duplex.py` | 已实现 | 对齐 VAD、speech_start、speech_end、audio span refs、raw audio exclusion。 |
| Mock ASR/Thinker frame shape | MVP-0 Slice 6 / `src/voice_agent/understanding/` | 已实现 | 对齐 transcript evidence、SemanticFrame evidence、Router 之前/之后的 causal order。 |
| Playback span and progress shape | MVP-0 Slice 7 / `src/voice_agent/talker/mock_talker.py` | 已实现 | 对齐 TTS span id、playback offset、first audio latency、progress metadata。 |
| Barge-in truncate shape | MVP-0 Slice 8 / `tests/fixtures/replay/mvp0/008-barge-in-truncate.fixture.json` | 已实现 | 对齐 `BARGE_IN_CANDIDATE`、`TTS_TRUNCATE_REQUESTED`、`TTS_TRUNCATED` 与 offset semantics。 |
| Acceptance fixture conventions | MVP-0 Slice 9 / `tests/fixtures/replay/mvp0/manifest.index.json` | 已实现 | 将 spike observations 转为 synthetic/redacted replay or eval evidence，而不是 raw trace。 |

每次 spike run report 应记录它参考的主线 commit 或 contract snapshot 日期。若主线 contract 变化，旧 spike result 保持历史 evidence，不自动升级为当前可集成事实。

## MVP-0 Slice to Model Spike Ledger

| MVP-0 slice | 主线产物 | spike 需要提供的 evidence | 是否阻塞 MVP-0 | 未来融合点 |
| --- | --- | --- | --- | --- |
| Slice 0: Repo Safety and Runtime Skeleton | `.gitignore`、fixture safety、local artifact boundary | 确认 spike code/report 不提交 raw audio、raw trace、secret、credential、unredacted real user input。 | 不阻塞 | Spike run artifact policy 与 repo safety 对齐。 |
| Slice 1: Event Envelope and Append-Only Journal | event envelope、per-session `event_seq`、journal validation | 确认 model output metadata 可引用 event ids、request ids、redacted refs，而不需要 raw provider payload。 | 不阻塞 | Adapter event metadata 与 journal envelope 对齐。 |
| Slice 2: Capability Snapshot and Mock Adapter Contracts | mock adapter capability matrices、`ADAPTER_CAPABILITY_SNAPSHOT_RECORDED` | 每个候选模型能否填充 required capability fields；不能填充的字段标 `unknown`、`degraded`、`unsupported` 或 `fallback`。 | 不阻塞 | 后续 `adapter-capability-profiles` 与 MVP-3 healthcheck。 |
| Slice 3: Deterministic State Reducers and Replay Core | deterministic replay、state digest、no model rerun | 确认 spike result 可转换为 replay-safe metadata；真实模型不得在 replay 中重跑。 | 不阻塞 | Spike run report 转 synthetic fixture 或 eval assertion。 |
| Slice 4: Text Ingress Through Interaction Controller | text ingress、turn open/accept/commit、assumed directedness | Slow LLM / Thinker text-only fallback 是否能消费 redacted text evidence；web/RAG evidence 不进入 instruction area。 | 不阻塞 | Text-only degraded path 与 SlowTask/Thinker fallback。 |
| Slice 5: Audio Span and Duplex Mock Accept Path | audio span、mock/rule speech start/end、turn commit | VAD speech_start latency、speech_end hangover、audio refs、semantic_close/assistant-directedness degradation。 | 不阻塞 | MVP-3 Duplex/VAD adapter candidate。 |
| Slice 6: Mock Understanding and Router FAST_ONLY Skeleton | mock ASR frame、mock Thinker frame、Router decision | ASR partial/final transcript、timestamp、confidence；Thinker SemanticFrame JSON、emotion/audio caption hints。 | 不阻塞 | ASR/Thinker real adapter replacement after MVP-3 gate。 |
| Slice 7: Mock Talker Playback Progress and Delivery Markers | playback span、progress、commit marker | TTS first-audio latency、stream chunk cadence、span id compatibility、audio output mode。 | 不阻塞 | TTS adapter plus Talker playback integration. |
| Slice 8: Barge-in Candidate to Truncate Flow | barge-in candidate、interrupt candidate、truncate request、truncate confirmation | Duplex VAD/AEC latency、echo likelihood、TTS playback stop offset accuracy、model request cancellation limits。 | 不阻塞，但强相关 | ADR-003 target-valid truncate evidence. |
| Slice 9: MVP-0 Replay Fixtures and Acceptance Runner | acceptance fixtures、scenario assertions | 将 spike observations 精炼为 synthetic/redacted eval cases；确认 no raw artifacts。 | 不阻塞 | MVP-3 pre-integration eval suite. |

## Model Capability Evidence Dependencies

| Model area | 依赖的主线 contract | spike evidence 输出 | 当前时机 |
| --- | --- | --- | --- |
| Duplex / VAD | Slice 5、Slice 8 | speech_start latency、barge-in latency、echo likelihood、directedness/semantic_close degradation。 | 现在可按 MVP-0 audio/barge-in metadata 做实验设计。 |
| ASR | Slice 2、Slice 6 | final/partial transcript、timestamps、streaming support、cancellation/stale policy。 | 现在可按 `MOCK_ASR_FRAME_EMITTED` refs 设计 adapter-shaped output。 |
| TTS / Talker | Slice 2、Slice 7、Slice 8 | first audio latency、streaming output、playback span compatibility、truncate compatibility。 | 现在可按 playback span / truncate offsets 做实验设计。 |
| Thinker | Slice 2、Slice 6 | SemanticFrame JSON validity、emotion、audio caption、assistant-directedness、Composer role risk。 | 现在可按 `MOCK_THINKER_FRAME_EMITTED` refs 设计 SemanticFrame output。 |
| Slow LLM | Slice 2；MVP-1 SlowTask contracts | structured JSON validity、schema retry、tool proposal normalization、plan_version stale behavior。 | 现在可先跑结构化 JSON；plan_version/stale 部分等 MVP-1 contract 补齐。 |
| Embedding / RAG | ADR-014；后续 evidence boundary | source attribution、untrusted evidence labeling、redaction、timeout/cancellation。 | 不阻塞 MVP-0；等 evidence boundary 更稳后。 |

## Integration Gates

### Gate 0: Research-only readiness

通过条件：

- Worktree 在 `research/model-spikes`。
- Spike 文档只写入 `docs/research/` 或明确批准的 spike-local 目录。
- 不修改 `src/voice_agent/`、`tests/`、`docs/adr/`、`docs/specs/`。
- 没有 raw audio、raw trace、secret、token、cookie、credential、authorization header。

### Gate 1: Spike-local experiment readiness

通过条件：

- 已确认 provider key 只通过本地环境变量传入，不进入 repo。
- 已定义 synthetic inputs 与 redaction rules。
- 已定义 run report 路径，例如 `docs/research/spikes/<domain>-<candidate>-run-<yyyy-mm-dd>.md`。
- 已定义 timeout、retry、cancellation、output validation 的记录字段。
- Harness 输出 adapter-shaped metadata，而不是自由格式 demo log。
- Harness output 至少能映射到 MVP-0 `AdapterCapability` required fields、event refs、`output_mode` 与 `unsupported_capabilities`。

### Gate 2: Adapter profile hardening

通过条件：

- 每个候选至少有一份 observed run report，或明确 deferred。
- Capability matrix 覆盖 ADR-011 required fields。
- unsupported / unknown / degraded 能力有对应 degradation proposal。
- Late result、timeout、schema failure、provider failure 的处理可映射到 adapter events。
- Trace/privacy notes 明确说明不需要 raw provider payload。

### Gate 3: MVP-3 integration consideration

通过条件：

- MVP-0/1/2 主线 contract 已稳定到足够接入 real adapter。
- 候选 profile 能写入未来 adapter capability profile，而不是只停留在调研描述。
- Integration 不新增 architecture capability。
- Deterministic replay 不重跑真实模型，只消费 recorded metadata or synthetic fixture。
- Tool proposal、confirmation、truncate、plan_version stale policy 均不越过主线 owner。

## Do Not Cross Boundaries

- Model spike 不接主 runtime。
- Model spike 不修改 accepted ADR、event registry、adapter spec 或 replay spec。
- Model spike 不提交 raw audio、raw model trace、secret、token、cookie、credential、authorization header。
- Provider result、webSearch、RAG、model card 内容只能作为 evidence，不能作为 instruction 或 policy。
- Omni model 不吸收 ASR、Thinker、TTS、Duplex 与 SlowTask 的架构职责。
- TTS truncate 仍由 Talker/playback 确认；model request cancellation 不是 `TTS_TRUNCATED` 的事实来源。
- Slow LLM tool calling 只能变成 tool proposal；Tool Executor 仍是 execution / authorization owner。

## Open Coordination Items

| Item | 当前建议 | Owner |
| --- | --- | --- |
| 主线 contract snapshot 记录方式 | 默认记录 `main@61e6afc`；若主线更新，再写明新的 commit。 | spike thread |
| Spike code 目录 | 优先后续单独设计 `tools/model_spikes/` 或 `research/model_spikes/`，不进入 `src/voice_agent/`。 | spike thread |
| API key 管理 | 只使用 local env vars；报告只记录 present/missing 与 provider alias。 | human + spike thread |
| 首批 API 实验 | 先跑 Slow LLM structured JSON，因为无 raw audio，风险最低。 | spike thread |
| ASR/TTS audio fixture | 使用 synthetic generated clips；不提交 raw audio。 | spike thread |
| Profile 落点 | 等 Gate 2 后再讨论是否新增 `docs/specs/adapter-capability-profiles.md`。 | mainline + spike coordination |

## Recommended Next Actions

1. 保持当前 research docs 为 baseline，不再分中英文双份维护。
2. 将 `research/model-spikes` 对齐到最新 `main@61e6afc`，让 spike worktree 能读取已完成的 MVP-0 implementation contracts。
3. 使用 `docs/research/model-spike-execution-plan.md` 作为 Phase 0 / Phase 1 / Phase 2 的执行入口。
4. 第一批实验优先 Slow LLM structured JSON：DashScope Qwen 与 DeepSeek。
5. 每次实验产出 run report，并在报告中引用本 ledger 的相关 slice、gate 与 `main@61e6afc` contract snapshot。

## Recommendation

两条 worktree 的融合方式应是：主线产出 contract shape，model spike 产出 observed evidence，双方通过 adapter capability matrix、run report 与 integration gates 对齐。短期内，本 ledger 是对账本；中期产出 adapter profile draft；长期在 MVP-3 integration branch 中逐个接入真实 adapter。
