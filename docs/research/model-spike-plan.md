# 模型能力探针计划 Model Spike Plan

## Status

active research plan after MVP-0 closeout。

本文档定义模型能力探针路线。它不是 real adapter integration 方案，不授权接入主 runtime，不授权业务模块建立 provider endpoint 依赖。

## Source of Truth

- `AGENTS.md`
- `docs/specs/model-adapter-capabilities.md`
- `docs/specs/event-registry.md`
- `docs/specs/replay-spec.md`
- `docs/adr/ADR-003 Barge-in and TTS Truncate Contract.md`
- `docs/adr/ADR-008 ASR Thinker Evidence Fusion and SlowTask-led Conflict Resolution.md`
- `docs/adr/ADR-009 SemanticCommitment and Thinker-as-Composer Contract.md`
- `docs/adr/ADR-010 Trace Replay Debug Policy for Web Demo.md`
- `docs/adr/ADR-011 Model Adapter Capability Contract.md`
- `docs/adr/ADR-012 MVP Vertical Slice and Development SLOs.md`
- `docs/adr/ADR-014 webSearch Evidence Boundary for Demo Tools.md`
- `docs/adr/ADR-016 SlowTask Lifecycle and Confirmation State Contract.md`

## Context

System Spine 会先用 faithful mock 实现 MVP-0 walking skeleton。但 mock 只能证明架构边界，不能证明真实候选模型具备对应能力。

如果不提前做模型探针，MVP-3 可能才发现候选模型不支持 streaming、audio timestamps、structured JSON、cancellation、emotion、audio caption、TTS truncate、semantic_close 或 assistant-directedness。届时团队容易通过扩大 scope、越过 adapter boundary 或修改架构边界来补洞。

因此需要一条隔离的 Model Spikes 泳道：只回答能力问题，只沉淀 capability matrix 和 risk report，不进入主流程。

## MVP-0 Closeout Update

截至 2026-05-11，`main@61e6afc` 已合入 MVP-0 closeout。主线 `docs/implementation/mvp0-backlog.md` 记录 Slice 0-9 已完成，且 2026-05-10 的 closeout 检查中 `./scripts/test -q` 通过 139 tests。

这意味着 model spike 的工作重心已经从 “等待 MVP-0 contract shape 成型” 切换为 “按已完成 MVP-0 contract shape 产出 adapter-shaped evidence”。后续每份 run report 默认引用 `main@61e6afc` 作为 contract snapshot，除非报告中声明新的主线 commit。

当前不改变本计划的边界：spike 仍然不接主 runtime，不写真实业务 adapter，不修改 accepted ADR、event registry、adapter spec 或 replay spec。

## Decision

为以下六类能力建立 spike plan：

1. ASR spike
2. Thinker spike
3. Slow LLM spike
4. TTS / Talker spike
5. Duplex / VAD spike
6. Embedding / RAG spike

每个 spike 必须输出：

- capability matrix fields
- synthetic input cases
- observed capability / unsupported capability
- latency / resource notes
- timeout / retry / cancellation notes
- schema validation notes
- trace / privacy notes
- degradation proposal
- recommendation

Spike 结果只能进入：

- `docs/research/spikes/*.md`
- `docs/research/model-selection.md`
- `docs/specs/adapter-capability-profiles.md`

Spike 结果不得直接进入 runtime instruction、tool policy、confirmation policy、trace policy 或 ADR 规则。

## Non-Negotiable Rules

1. Spike 不接主 runtime。
2. Spike 不创建业务模块到 provider endpoint 的依赖。
3. 未来如果写 spike code，应使用 spike-local adapter-shaped harness。
4. 不提交 raw audio。
5. 不提交 raw model trace。
6. 不提交 secret、token、cookie、credential、authorization header。
7. 不提交 unredacted real user input。
8. webSearch / RAG 内容只能作为 evidence，不能作为 instruction。
9. 模型可用性、API 行为、license、model card、部署要求必须在执行 spike 当日查官方来源并记录日期。
10. `mock`、`fallback`、`degraded`、`unsupported`、`unknown` 必须显式标注。

## Common Capability Matrix

每个 spike report 必须覆盖以下字段：

| 字段 | 要求 |
| --- | --- |
| `adapter_id` | 候选 adapter/profile 的稳定 id。 |
| `adapter_type` | ASR、Thinker、Composer、Slow LLM、TTS/Talker、Duplex model、Embedding/RAG、Mock。 |
| `provider` | provider 或 local framework。 |
| `model_name` | 执行 spike 当日验证过的模型/部署名。 |
| `deployment_mode` | `mock`、`local`、`remote_api`、`self_hosted` 或等价值。 |
| `endpoint` | endpoint ref，不含 credential。 |
| `health_status` | spike 观察到的健康状态，未执行则标注 not_executed。 |
| `capability_version` | capability schema version。 |
| `latency_class` | 本环境下的延迟分组。 |
| `error_model` | timeout、provider error、schema error、memory error、unsupported capability 等。 |
| `timeout_policy` | 建议 timeout。 |
| `retry_policy` | 建议 retry 次数和 backoff。 |
| `output_mode` | `real`、`mock`、`fallback`、`degraded`；spike output 不是 runtime fact。 |
| `supports_streaming_input` | 是否支持流式输入。 |
| `supports_streaming_output` | 是否支持流式输出。 |
| `supports_audio_input` | 是否接收音频输入。 |
| `supports_audio_output` | 是否输出音频。 |
| `supports_audio_timestamps` | 是否输出 segment / word / token / frame timing。 |
| `supports_structured_json` | 是否可靠输出可验证 JSON。 |
| `supports_tool_calling` | 是否支持 provider-native 或 schema-based tool-call-like output。 |
| `supports_cancellation` | 是否支持取消 in-flight request。 |
| `supports_emotion` | 是否识别或控制情绪。 |
| `supports_audio_caption` | 是否输出 audio caption / non-speech summary。 |
| `supports_tts` | 是否支持 speech synthesis。 |
| `supports_tts_truncate` | 是否支持 ADR-003 所需 truncate path。 |
| `supports_tts_pause_resume` | 是否支持 pause/resume；MVP 仍为 non-goal。 |
| `supports_semantic_close` | 是否支持 semantic end-of-turn。 |
| `supports_assistant_directedness` | 是否支持 assistant-directedness。 |
| `max_audio_seconds` | 最大音频输入长度。 |
| `max_context_tokens` | 最大上下文。 |
| `max_output_tokens` | 最大输出。 |
| `expected_first_token_latency_ms` | 观测或估计 first token latency。 |
| `expected_first_audio_latency_ms` | 观测或估计 first audio latency。 |

## Spike Report Template

每次执行 spike 后，建议创建：

```text
docs/research/spikes/<domain>-<candidate>-<yyyy-mm-dd>.md
```

报告结构：

```markdown
# <Domain> Spike: <Candidate>

## Status

## Context

## Question

## Setup

## Official Sources Checked

## Synthetic Inputs

## Observations

## Capability Matrix Result

## Latency and Resource Notes

## Schema / Validation Notes

## Cancellation / Timeout / Retry Notes

## Trace and Privacy Notes

## Degradation Proposal

## Recommendation

## Open Questions
```

## ASR Spike

**候选**

- SenseVoiceSmall / 当前等价候选。
- Whisper large-v3-turbo / 当前等价候选。
- FunASR / 当前等价候选。

**目标问题**

- 能否输出 final transcript 或 text projection？
- 是否支持 streaming input？
- 是否支持 partial / streaming output？
- 是否提供 audio timestamps？粒度是 segment、word、token 还是 frame？
- 是否提供 n-best、confidence、language detection、punctuation？
- 是否能处理短 barge-in、clipped start、噪声、静音、非语音？
- 是否支持 cancellation？不支持时是否只能等待 late result 并进入 stale policy？
- first partial、final transcript、total latency 分别是多少？

**必须验证的 capability fields**

- `supports_streaming_input`
- `supports_streaming_output`
- `supports_audio_input`
- `supports_audio_timestamps`
- `supports_structured_json`
- `supports_cancellation`
- `max_audio_seconds`
- `expected_first_token_latency_ms`

**Synthetic cases**

- 短命令。
- 播放中插话短句。
- 容易混淆的人名 / 地名。
- 静音 / 非语音。
- 中英混合或目标用户需要的多语言样本。

**产物**

- ASR capability report。
- ASR adapter profile 草案。
- timestamps / streaming / cancellation 风险记录。

**边界**

ASR 只是 text projection evidence，不是唯一语义真相，不得决定 turn ingress。

## Thinker Spike

**候选**

- Qwen3-Omni / 当前等价候选。
- Qwen2.5-Omni / 当前等价候选。
- MiniCPM-o / 当前等价候选。

**目标问题**

- 是否支持 audio / multimodal input？
- 是否能输出稳定 SemanticFrame？
- 是否能输出 intent_hint、slot_hints、emotion、audio_caption、utterance_summary、confidence？
- 是否能区分 Thinker-as-Fast-System 和 Thinker-as-Composer 两个 role contract？
- 是否支持 structured JSON 和 schema retry？
- 是否支持 semantic_close / assistant-directedness hint？
- 是否支持 streaming output 和低 first token latency？
- 是否支持 cancellation？
- 是否会在 FAST_ONLY 中过度承诺不确定关键字段？

**必须验证的 capability fields**

- `supports_streaming_input`
- `supports_streaming_output`
- `supports_audio_input`
- `supports_structured_json`
- `supports_tool_calling`
- `supports_cancellation`
- `supports_emotion`
- `supports_audio_caption`
- `supports_semantic_close`
- `supports_assistant_directedness`
- `max_context_tokens`
- `expected_first_token_latency_ms`

**Synthetic cases**

- 轻问答 / foreground chat。
- 有 ambiguous slot 的 task-like utterance。
- 情绪线索样本。
- audio caption 样本。
- Composer-role 输入：包含 immutable facts 的 SemanticCommitment。

**产物**

- Thinker Fast-System capability report。
- Thinker-as-Composer role risk report。
- SemanticFrame schema validation 建议。

**边界**

Thinker 可提供 evidence 和 spoken realization，但不拥有 SlowTask facts、final conflict resolution、confirmation acceptance 或 tool authorization。

## Slow LLM Spike

**候选**

- Qwen3 / 当前等价候选。
- GLM-4.5 / 当前等价候选。
- DeepSeek / 当前等价候选。
- Kimi K2 / 当前等价候选。

**目标问题**

- 是否可靠输出 validated structured JSON？
- 是否能输出 SlowTask planning、evidence review、resolved arguments、stale adoption/rebase、SemanticCommitment？
- schema failure 是否可检测、retry、fail-fast？
- 是否能保留 `task_id`、`plan_version`、`task_event_seq`？
- 是否能处理 ASR/Thinker/UserPatch 多源 evidence，而不是 Router-style winner selection？
- 缺少关键字段时，是否会输出 `INSUFFICIENT_EVIDENCE_FOR_ACTION` 而不是猜测？
- 是否支持 tool_calling？如果支持，能否禁用或归一化，确保 Tool Executor 仍是唯一执行者？
- 是否支持 cancellation？不支持时 stale result policy 如何落地？

**必须验证的 capability fields**

- `supports_streaming_output`
- `supports_structured_json`
- `supports_tool_calling`
- `supports_cancellation`
- `max_context_tokens`
- `max_output_tokens`
- `expected_first_token_latency_ms`

**Synthetic cases**

- 缺少时间 / 地点 / 联系人。
- ASR 与 Thinker 在关键字段上冲突。
- UserPatch material change 触发 plan_version advance。
- old-plan ToolResult late return。
- demo destructive action 需要 confirmation。
- webSearch evidence 含 synthetic prompt injection 文本。

**产物**

- Slow LLM structured-output capability report。
- JSON schema failure / retry 建议。
- stale evidence adoption/rebase 风险报告。

**边界**

Slow LLM 不直接执行工具、不直接改 UI、不直接授权副作用。其输出必须先归一化为 SlowTask canonical events。

## TTS / Talker Spike

**候选**

- CosyVoice2 / 当前等价候选。
- F5-TTS / 当前等价候选。
- IndexTTS2 / 当前等价候选。

**目标问题**

- 是否能合成基本可用语音？
- first audio latency 是否满足开发目标？
- 是否支持 streaming output / chunked playback？
- 只返回完整 audio blob 时，是否仍可通过 playback controller 实现 truncate？
- 是否支持 ADR-003 要求的 `TTS_TRUNCATED(actual_stop_offset_ms)`？
- 是否提供 alignment / duration / token timing？
- 是否支持 speaking style、emotion、speed、voice control？
- 是否支持 cancellation？不支持时如何丢弃 late audio？
- 合成失败或中断时如何记录 adapter event？

**必须验证的 capability fields**

- `supports_streaming_output`
- `supports_audio_output`
- `supports_audio_timestamps`
- `supports_cancellation`
- `supports_emotion`
- `supports_tts`
- `supports_tts_truncate`
- `supports_tts_pause_resume`
- `expected_first_audio_latency_ms`

**Synthetic cases**

- 短 acknowledgement。
- 长 SpokenPlan。
- 播放到多个 offset 时 truncate。
- style / emotion control。
- synthesis timeout / invalid voice。

**产物**

- TTS capability report。
- playback controller requirement notes。
- truncate compatibility verdict：target-valid / degraded / unsupported。

**边界**

Talker / Playback 拥有 playback progress 和 truncate confirmation。`PLAYBACK_COMMITTED` 只是 delivery marker，不是 semantic acknowledgement。

## Duplex / VAD Spike

**候选**

- Silero VAD / 当前等价候选。
- WebRTC VAD / AEC / 当前等价候选。
- openWakeWord / 当前等价候选。
- 后续可选 lightweight directedness / semantic_close classifier。

**目标问题**

- speech_start latency 是否能接近 <=150ms development SLO？
- speech_end after silence 是否可配置到 500-800ms？
- 播放回声存在时，是否能保留 playback reference？
- 是否能估计 echo_likelihood？
- false barge-in rate 如何评估？
- 是否支持 assistant-directedness / semantic_close？若不支持，如何标注 mock/rule/degraded？
- 在本地开发环境 CPU 占用和 latency 是否可接受？

**必须验证的 capability fields**

- `supports_streaming_input`
- `supports_audio_input`
- `supports_audio_timestamps`
- `supports_cancellation`
- `supports_semantic_close`
- `supports_assistant_directedness`
- latency fields

**Synthetic cases**

- silence -> speech start。
- speech -> silence end。
- playback echo only。
- user speech over playback。
- non-assistant background speech。
- wake-word / directedness positive-negative cases。

**产物**

- Duplex/VAD capability report。
- false barge-in measurement plan。
- playback reference interface 建议。

**边界**

Duplex 只产出 realtime candidates。Interaction Controller 仍是 turn ingress 和 playback interrupt policy 的唯一 owner。

## Embedding / RAG Spike

**候选**

- local embedding candidates。
- remote embedding candidates。
- reranker / retrieval components，需在 evidence boundary 明确后再做。

**目标问题**

- embedding / retrieval latency 是否适合未来 RAG evidence？
- retrieval result 是否能带 source attribution？
- raw retrieved content 如何避免进入 GitHub fixture？
- untrusted / stale retrieval result 如何标注？
- 是否支持 cancellation、timeout、retry？
- RAG 输出能否保持在 evidence context，而不是 instruction context？

**必须验证的 capability fields**

- `supports_structured_json`
- `supports_cancellation`
- `max_context_tokens`
- retrieval latency equivalent
- adapter identity / error / timeout / retry / output mode fields

**Synthetic cases**

- synthetic document retrieval。
- retrieval result 含 instruction-like text。
- missing source attribution。
- large raw content redaction/export。

**产物**

- Embedding/RAG capability report。
- evidence boundary 建议。
- redaction and fixture policy notes。

**边界**

RAG 与 webSearch 一样是 evidence，不是 instruction。不得修改 tool、confirmation、trace、repo 或 ADR policy。

## Cross-Spike Evaluation Matrix

| 维度 | ASR | Thinker | Slow LLM | TTS | Duplex/VAD | Embedding/RAG |
| --- | --- | --- | --- | --- | --- | --- |
| streaming input | 重点 | 重点 | 通常非重点 | 非重点 | 重点 | 可选 |
| streaming output | partial/final | foreground latency | 可选 | 重点 | event stream | 可选 |
| audio timestamps | 重点 | 有用 | 非重点 | alignment 有用 | 重点 | 非重点 |
| structured JSON | wrapper | SemanticFrame | 核心 | metadata | candidate metadata | source refs |
| tool calling | 不直接用 | 不执行 | 归一化，不执行 | 不适用 | 不适用 | 不适用 |
| cancellation | 重要 | 重要 | 重要 | 重要 | stream stop | 有用 |
| emotion | 不适用 | 重要 | 可选 | style control | 不适用 | 不适用 |
| audio caption | 不适用 | 重要 | 不适用 | 不适用 | 不适用 | 不适用 |
| TTS truncate | 不适用 | 不适用 | 不适用 | 核心 | 校验 barge-in 链路 | 不适用 |
| semantic_close | 不适用 | evidence only | 不适用 | 不适用 | 可选 | 不适用 |
| assistant-directedness | 不适用 | evidence only | 不适用 | 不适用 | 可选 | 不适用 |
| replay impact | refs | refs | structured decisions | playback refs | timing refs | evidence refs |

## Decision Gates

### Gate A: 进入 Adapter Contract Hardening

通过条件：

- 每个 domain 至少有一份 spike report，或明确 defer。
- unsupported capability 有记录。
- degradation proposal 映射到 ADR-011 行为。
- 未提交 raw/sensitive artifacts。

### Gate B: 进入 MVP-3 shortlist

通过条件：

- ASR 至少能提供 final transcript / text projection。
- Thinker 至少能提供 basic SemanticFrame，或有 approved mock-compatible fallback。
- Slow LLM 能输出 validated structured JSON，或有 fail-fast/degraded plan。
- TTS 能合成基本 audio；truncate 是 target-valid 或显式 degraded。
- adapter error / timeout / retry / validation failure / degradation events 有映射。

### Gate C: 进入主 runtime integration

通过条件：

- System Spine 已经有 adapter capability snapshot、output mode labeling、adapter error/degradation replay。
- 候选 profile 已进入 `docs/specs/adapter-capability-profiles.md`。
- integration 不新增架构能力。
- deterministic replay 不会重跑真实模型。

## Recommended Execution Order

MVP-0 closeout 后，建议把实操顺序调整为先低隐私风险、低音频复杂度，再进入 audio-heavy experiments：

1. Slow LLM spike：先验证 structured JSON、schema retry、tool proposal normalization；不涉及 raw audio，最适合作为第一批 API probe。
2. TTS / Talker spike：ADR-003 truncate 是 live loop 核心风险；先测 first audio latency、streaming、playback span compatibility。
3. ASR spike：明确 transcript、timestamp、streaming、cancellation，并把 output 映射到 MVP-0 `MOCK_ASR_FRAME_EMITTED` shape。
4. Thinker spike：验证 SemanticFrame JSON、emotion、audio caption、assistant-directedness，并映射到 MVP-0 `MOCK_THINKER_FRAME_EMITTED` refs。
5. Duplex / VAD spike：barge-in 质量依赖 playback overlap 和 echo handling；需要更贴近 Slice 8 fixture 的 local audio setup。
6. Embedding / RAG spike：不阻塞 MVP-0，应等 evidence boundary 更稳后做。

## Validation Method

| 检查项 | 结果 |
| --- | --- |
| 是否和 accepted ADR 冲突 | 否。Spike 只服务 ADR-011 adapter profiles。 |
| 是否扩大 MVP scope | 否。Spike 是 research，不是 runtime feature。 |
| 是否把 mock 当成 real capability | 否。必须标注 mock/fallback/degraded/unsupported/unknown。 |
| 是否遗漏 replay/eval | 否。Spike 产出 eval evidence；runtime replay 需后续 synthetic fixture 转换。 |
| 是否允许模型越过 adapter boundary | 否。未来 runtime integration 必须走 adapter。 |
| 是否让 webSearch/RAG 进入 instruction 区 | 否。外部内容只作为 evidence。 |
| 是否允许真实外部副作用 | 否。本文不授权 tool execution。 |

## Consequences

正向结果：

- MVP-3 model selection 有证据，不靠单次 demo 印象。
- adapter contract 能提前吸收真实能力缺口。
- mock 能力不会被误认为真实验证。

代价：

- 需要维护 spike report 和 capability profiles。
- 每个候选都要记录版本、来源、环境和日期。
- 模型信息易变化，执行 spike 时必须重新查官方来源。

## Open Questions

- 每个 domain 首批是否只选 2 个候选，还是保留 3 个？
- spike code 是否需要独立目录，还是先只做外部笔记和报告？
- 模型 license / 商用限制是否纳入 shortlist hard gate？
- 本地 GPU / A100 / remote API 的优先级如何排？
- 是否需要单独的 `docs/research/spikes/README.md` 约束报告格式和敏感数据规则？
