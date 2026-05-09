# Thinker 能力探针

## Status

evidence_report

## Date

2026-05-09

## Scope

本文评估 Thinker-style evidence 的 audio semantic frame 候选：audio understanding、emotion、audio captioning、semantic close、assistant-directedness hints 与 structured output。同时评估 omni/audio model 是否适合 Thinker-as-Fast-System 或 Thinker-as-Composer。

## Architecture Role

Thinker 从 audio/text context 产生 SemanticFrame-style evidence。它可以帮助解释 user intent、emotion、assistant-directedness、uncertainty 与 semantic completeness。它不得拥有 turn ingress commit、final SlowTask facts、tool authorization 或 playback truncate policy。

## ADR Constraints

- ADR-001：Interaction Controller 拥有 turn ingress；Thinker evidence 不能自行 commit turn。
- ADR-008：Thinker evidence 与 ASR evidence 融合；conflict resolution 由 SlowTask 主导。
- ADR-009：Thinker-as-Composer 可以实现 spoken realization，但不能改写 immutable facts、required fields、resolved arguments、tool status、risk warnings 或 confirmation state。
- ADR-011：任何 audio/omni model 都必须在 adapter 后，并声明 capability matrix。
- ADR-016：SlowTask 拥有 confirmation state 与最终 plan/fact evolution。

## Candidate Shortlist

- Qwen3-Omni：multimodal audio understanding 与 audio captioning 的 primary candidate；官方项目暴露 Thinker/Talker architecture、multilingual audio 与 DashScope API path。
- Qwen2.5-Omni：fallback/earlier Qwen omni candidate，支持 end-to-end multimodal input 与 streaming text/speech output。
- MiniCPM-o 2.6 / current MiniCPM-o family：full-duplex multimodal interaction 的 local/A100 exploration candidate；当前官方材料重点转向 MiniCPM-o 4.5，同时保留 2.6 lineage。
- GLM-4-Voice：speech-dialogue candidate，支持中英文 speech understanding/generation；适合 voice-style experiments。
- Ultravox：audio-to-text multimodal LLM candidate；当 text output 足够生成 SemanticFrame evidence 时可用。
- Moshi 与 VITA-Audio：supplemental spoken-dialogue research candidates，不作为 first MVP-3 Thinker pick。

## Official Sources Checked

- Qwen3-Omni GitHub: https://github.com/QwenLM/Qwen3-Omni
- Qwen2.5-Omni GitHub: https://github.com/QwenLM/Qwen2.5-Omni
- MiniCPM-o GitHub: https://github.com/OpenBMB/MiniCPM-o
- GLM-4-Voice GitHub: https://github.com/THUDM/GLM-4-Voice
- Ultravox GitHub: https://github.com/fixie-ai/ultravox
- Moshi GitHub: https://github.com/kyutai-labs/moshi
- VITA GitHub: https://github.com/VITA-MLLM/VITA
- Qwen Omni API documentation linked from official Qwen repositories: https://help.aliyun.com/zh/model-studio/user-guide/qwen-omni

## Capability Matrix Assessment

| field | Qwen3-Omni | Qwen2.5-Omni | MiniCPM-o family | GLM-4-Voice | Ultravox | Moshi / VITA |
| --- | --- | --- | --- | --- | --- | --- |
| adapter_type | thinker | thinker | thinker | thinker | thinker | thinker |
| provider | Qwen / Alibaba | Qwen / Alibaba | OpenBMB | THUDM | Fixie | Kyutai / VITA |
| model_name | Qwen3-Omni | Qwen2.5-Omni | MiniCPM-o-2.6_or_4.5 | GLM-4-Voice | Ultravox | Moshi_or_VITA |
| deployment_mode | api_or_self_hosted | api_or_self_hosted | self_hosted | self_hosted | api_or_self_hosted | self_hosted |
| supports_streaming_input | real | real | real | real | real | real |
| supports_streaming_output | real | real | real | degraded | real | real |
| supports_audio_input | real | real | real | real | real | real |
| supports_audio_output | real | real | real | real | unsupported | real |
| supports_audio_timestamps | unknown | unknown | unknown | unknown | unknown | unknown |
| supports_structured_json | degraded | degraded | degraded | degraded | degraded | degraded |
| supports_tool_calling | unknown | unknown | unknown | unknown | unknown | unknown |
| supports_cancellation | degraded | degraded | degraded | degraded | degraded | degraded |
| supports_emotion | degraded | degraded | degraded | real | unknown | degraded |
| supports_audio_caption | real | degraded | unknown | unknown | unknown | unknown |
| supports_tts | real | real | real | real | unsupported | real |
| supports_tts_truncate | unsupported | unsupported | unsupported | unsupported | unsupported | unsupported |
| supports_tts_pause_resume | unsupported | unsupported | unsupported | unsupported | unsupported | unsupported |
| supports_semantic_close | degraded | degraded | degraded | degraded | degraded | degraded |
| supports_assistant_directedness | degraded | degraded | degraded | degraded | degraded | degraded |
| max_audio_seconds | unknown | unknown | unknown | unknown | unknown | unknown |
| max_context_tokens | unknown | unknown | unknown | unknown | model_dependent_unknown | unknown |
| max_output_tokens | unknown | unknown | unknown | unknown | model_dependent_unknown | unknown |
| expected_first_token_latency_ms | unknown | unknown | unknown | unknown | unknown | unknown |
| expected_first_audio_latency_ms | unknown | unknown | unknown | unknown | not_applicable | degraded |
| output_mode | real_or_degraded | fallback | degraded | degraded | fallback | degraded |
| degradation_notes | best primary candidate，但 JSON stability 需要 harness | good fallback；capability envelope 较旧 | promising local path，但 current 4.5 docs 提到 speech-output instability 与硬件需求 | strong speech style evidence，但与 JSON SemanticFrame 对齐较弱 | text-only output 仍可产生 SemanticFrame evidence | useful research；不是 first adapter candidate |

## Candidate Comparison

Qwen3-Omni 是最强 primary Thinker candidate，因为官方材料强调 audio/video/text understanding、audio captioning、streaming 与 Thinker/Talker separation，天然贴合本项目 role split。Qwen2.5-Omni 是可信 fallback，架构类似但 capability claim 较旧。

MiniCPM-o 对 self-hosted full-duplex research 很有吸引力，尤其适合 A100-class hardware；但当前官方材料也提示 instability 与 demo latency constraints。GLM-4-Voice 对 expressive speech-dialogue experiments 有用，但 Thinker 更需要 stable semantic evidence，而不是 speech generation。Ultravox 在 audio input to streaming text 足够时很有价值。Moshi 与 VITA 是 full-duplex interaction 的重要 comparison points，但不应成为 initial MVP-3 Thinker adapter。

## Recommended MVP Usage

使用 Qwen3-Omni 作为 SemanticFrame experiments 的 primary Thinker candidate。根据是否需要 audio-only text evidence，使用 Qwen2.5-Omni 或 Ultravox 作为 fallback。MiniCPM-o 用于 self-hosted A100 research，不作为 first MVP-3 dependency。

Thinker 应输出 validated SemanticFrame candidate，例如 intent hypotheses、slots、uncertainty、emotion hints、audio caption、semantic-close hint 与 assistant-directedness hint。所有字段在被 Interaction Controller 与 SlowTask 按 ADR 消费前都只是 evidence。

## API / Deployment Notes

Qwen Omni 通过 DashScope/Bailian 有 API path，同时官方仓库也提供 open model path。Self-host candidates 需要 GPU isolation，且不得运行在 Interaction Controller loop 内。Adapters 应支持 `thinker_fast_system` 与 `thinker_composer` 两种独立 profile，避免同一 model family 混淆权限边界。

## Latency and Resource Notes

Thinker latency 可以高于 Duplex，因为它不在 barge-in hot path。Streaming partial SemanticFrame evidence 可能有用，但 first stable frame 需要结合 user interruption scenario 与 ASR partial churn 测量。Self-host omni models 可能 GPU-heavy；MiniCPM-o 当前文档对较新 variant 提到显著 memory requirements。

## Schema / Structured Output Notes

Structured JSON 在 schema-constrained harness 证明稳定前应视为 degraded。Adapter 应把 model output parse/validate 到本地 SemanticFrame schema；invalid JSON 时 retry；validation repair 后标记 output degraded。Model-native tool calling 对 Thinker role 应忽略，除非显式 normalize 为 evidence；Thinker 不执行 tools。

## Cancellation / Timeout / Retry Notes

如果 model-side cancellation 缺失，关闭 client stream，并把 late output 绑定为 stale evidence。Timeout 应保留 ASR/Duplex evidence，并发出 degraded missing-Thinker marker。Retries 必须使用同一个 evidence snapshot，且不得让后续 retry 修改已 committed task facts。

## Trace and Privacy Notes

只保存 structured SemanticFrame evidence 与 redacted metadata。避免 raw audio、包含敏感内容的 raw transcript、prompt secret 与 provider credential。Audio caption 可能泄露 private background context，因此 fixture 中应最小化并脱敏。

## Degradation Proposal

- 如果 JSON 失败，先用 schema-only prompt retry，再降级为 minimal key-value frame。
- 如果 audio input 失败，使用 ASR text-only Thinker fallback，并标记 audio evidence unavailable。
- 如果 emotion 或 assistant-directedness 不稳定，暴露 confidence，并保持 advisory。
- 如果 Qwen3-Omni API unavailable，使用 Qwen2.5-Omni 或 Ultravox 产生 text SemanticFrame evidence。

## Risks

- 单个 omni model 看起来可以同时解决 ASR、Thinker、TTS、Duplex 与 SlowTask，但这会压塌 adapter boundaries 与 replayability。
- Semantic-close hints 可能被误当成 turn ingress decisions。
- Composer prompts 如果没有 check，可能意外改写 SemanticCommitment facts。
- Audio caption 可能暴露 private environment information。
- Structured JSON reliability 在 project-specific harness 前仍是 unknown。

## Suggested Follow-up Experiments

- 用 synthetic Mandarin、English、mixed、noisy 与 interrupted clips 让 Qwen3-Omni 输出 SemanticFrame JSON。
- 比较 ASR-only 与 audio+ASR SemanticFrame conflicts。
- 用 labeled fixtures 评估 emotion 与 assistant-directedness calibration。
- 用 immutable facts 与 coverage checks 测 Composer role prompts。
- 在 interrupted audio streams 下测 timeout 与 stale-result behavior。

## Recommendation

Qwen3-Omni 作为第一 Thinker evidence candidate；Qwen2.5-Omni 或 Ultravox 作为 fallback；MiniCPM-o 保留给 self-hosted research。Thinker 权限必须收窄：只负责 evidence 与 spoken realization，不负责 turn ingress、tool authorization、truncate policy 或 SlowTask final facts。
