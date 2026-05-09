# ASR 能力探针

## Status

evidence_report

## Date

2026-05-09

## Scope

本文评估 ASR 候选在中文、英文、中英混合短句、噪音、timestamps 与 streaming behavior 上的适配性。本文把 ASR 视为 text projection evidence，而不是唯一语义真相。

## Architecture Role

ASR 把音频转换为 textual evidence，供 Interaction Controller、Thinker 与 SlowTask evidence flow 使用。根据 ADR-008，ASR output 只是用户 utterance 的一个投影；Thinker audio evidence 与 SlowTask conflict resolution 可以覆盖或限定它。ASR 不应 commit turn ingress，也不应产生最终 task facts。

## ADR Constraints

- ADR-008：ASR text 是 evidence，必须与 Thinker evidence 在 SlowTask-led conflict resolution 下融合。
- ADR-011：real ASR 必须在 adapter 后，并带 capability matrix 与明确的 `real`、`fallback`、`degraded` 或 `mock` output mode。
- ADR-012：MVP-3 可以把 mock ASR 替换为 real adapter，但不能新增 architecture capability。
- ADR-016：绑定旧 task/plan metadata 的 late ASR evidence 不能推进 current task，除非显式 adopt 或 rebase。
- AGENTS.md：raw audio、secret、local trace artifact 不得进入提交。

## Candidate Shortlist

- DashScope / Bailian ASR service candidate：API-first option，适合中文 production-style evaluation；当前 ASR model、streaming contract 与 timestamp 行为需要在 platform console/docs 中做最终集成验证。
- FunASR Paraformer streaming：Mandarin 与 mixed command ASR 的 self-host candidate，官方 pipeline 支持 streaming。
- SenseVoiceSmall / FunAudioLLM：self-host candidate，覆盖 multilingual speech recognition、language、emotion 与 acoustic event labels；timestamp 可通过官方 alignment path，true streaming 在实测前应标 degraded。
- Whisper large-v3-turbo：稳健 multilingual fallback，支持 timestamp，但默认不是低延迟 streaming-first adapter。

## Official Sources Checked

- FunASR GitHub: https://github.com/alibaba-damo-academy/FunASR
- SenseVoice GitHub: https://github.com/FunAudioLLM/SenseVoice
- Whisper large-v3-turbo model card: https://huggingface.co/openai/whisper-large-v3-turbo
- OpenAI Whisper GitHub: https://github.com/openai/whisper
- Aliyun Model Studio / DashScope documentation entry point: https://help.aliyun.com/zh/model-studio/

## Capability Matrix Assessment

| field | DashScope ASR candidate | FunASR Paraformer streaming | SenseVoiceSmall | Whisper large-v3-turbo |
| --- | --- | --- | --- | --- |
| adapter_type | asr | asr | asr | asr |
| provider | Alibaba Cloud / DashScope | FunASR | FunAudioLLM | OpenAI |
| model_name | unknown_current_asr_service | paraformer-zh-streaming | SenseVoiceSmall | whisper-large-v3-turbo |
| deployment_mode | api | self_hosted | self_hosted | self_hosted_or_api_wrapped |
| supports_streaming_input | unknown | real | degraded | unsupported |
| supports_streaming_output | unknown | real | degraded | unsupported |
| supports_audio_input | real | real | real | real |
| supports_audio_output | unsupported | unsupported | unsupported | unsupported |
| supports_audio_timestamps | unknown | degraded | real | real |
| supports_structured_json | degraded | degraded | degraded | degraded |
| supports_tool_calling | unsupported | unsupported | unsupported | unsupported |
| supports_cancellation | unknown | degraded | degraded | degraded |
| supports_emotion | unknown | unsupported | real | unsupported |
| supports_audio_caption | unsupported | unsupported | degraded | unsupported |
| supports_tts | unsupported | unsupported | unsupported | unsupported |
| supports_tts_truncate | unsupported | unsupported | unsupported | unsupported |
| supports_tts_pause_resume | unsupported | unsupported | unsupported | unsupported |
| supports_semantic_close | unsupported | unsupported | unsupported | unsupported |
| supports_assistant_directedness | unsupported | unsupported | unsupported | unsupported |
| max_audio_seconds | unknown | streaming_window | 30s_direct_or_vad_wrapped | unknown |
| max_context_tokens | not_applicable | not_applicable | not_applicable | not_applicable |
| max_output_tokens | not_applicable | not_applicable | not_applicable | not_applicable |
| expected_first_token_latency_ms | unknown | degraded_600ms_display_granularity_example | unknown | unknown |
| expected_first_audio_latency_ms | not_applicable | not_applicable | not_applicable | not_applicable |
| output_mode | real_or_unknown | real | fallback | fallback |
| degradation_notes | MVP-3 前需验证 exact model、timestamps、cancellation 与 streaming | streaming promising；timestamp detail 可能需要 non-streaming 或 post alignment | rich labels；true streaming adapter 可能是 chunked/degraded | good fallback；不适合 live partial first |

## Candidate Comparison

FunASR Paraformer 是最清晰的 self-host streaming ASR 候选，因为官方 examples 覆盖 streaming chunk 行为与 Mandarin-oriented pipelines。SenseVoiceSmall 对短中文与中英混合很有吸引力，因为它增加了 language、emotion 与 acoustic event evidence；但 direct inference duration 与 streaming semantics 需要谨慎 adapter design。Whisper large-v3-turbo 仍是强 multilingual fallback 与 benchmark baseline，但常见部署形态偏 offline/chunked。

如果 DashScope/Bailian 当前服务暴露稳定 realtime input、partial output、timestamps 与 operational controls，应优先评估为 API-first MVP-3 候选。exact service contract 应在 integration time 确认并写入 adapter capability matrix。

## Recommended MVP Usage

MVP-3 优先选择 DashScope/Bailian API-first ASR adapter，前提是其提供稳定 Mandarin/mixed speech realtime endpoint。FunASR Paraformer streaming 作为 self-host fallback。SenseVoiceSmall 作为 rich labels 与 short-utterance quality 的第二 self-host 路径。Whisper large-v3-turbo 作为 offline multilingual fallback 与 regression benchmark。

ASR 永远不应作为唯一语义真相。Transcript 应标记为 evidence，并与 audio SemanticFrame evidence 融合。

## API / Deployment Notes

API candidate 应暴露 adapter-level fields：provider、model、request id、streaming mode、timestamp mode、output mode。Self-host FunASR/SenseVoice adapter 应把 model inference 从 event loop 与 Interaction Controller 隔离。GPU 与 CPU deployment 必须在 chunking、timestamp 或 cancellation 弱于 nominal capability 时报告 degraded output。

## Latency and Resource Notes

FunASR streaming examples 描述了 chunked online recognition，带 display granularity 与 lookahead；这适合作为 partial transcript evidence，但不是 sub-150 ms barge-in signal。SenseVoice 官方材料报告短音频推理很快，但需要在目标硬件上测量。Whisper large-v3-turbo 预期更重，除非 dedicated streaming wrapper 被证明可靠，否则应作为 live command loop fallback。

## Schema / Structured Output Notes

ASR output 应由 adapter normalize，而不是信任 model-native schema。最小字段包括 transcript text、language、confidence when available、segment timestamps when available、partial/final flag、provider metadata 与 output mode。SenseVoice 的 emotion 与 acoustic event labels 应作为独立 evidence fields，而不是合并进 transcript text。

## Cancellation / Timeout / Retry Notes

当 provider-side cancellation 不可用或未验证时，adapter cancellation 表示 local stream close 与 stale-result handling。Late partial/final transcript 必须绑定 utterance id、task id where applicable、plan version where applicable 与 event sequence context。旧结果进入 stale evidence，除非 SlowTask 显式 adopt 或 rebase。

## Trace and Privacy Notes

不要在 repo fixture 中持久化 raw audio 或未脱敏用户语音。Research fixture 应为 synthetic 或 redacted，仅在安全时保存 transcript snippet。API request id 可以保存，前提是不含 secret。Authorization header、cookie 与 provider token 绝不进入 trace。

## Degradation Proposal

- 缺少 streaming：只使用 final transcript，并标记 partial transcript unsupported。
- 缺少 timestamps：timestamp mode 设为 `unknown`，避免 timestamp-dependent replay assertions。
- 缺少 cancellation：关闭 local stream，并依赖 stale evidence policy。
- Transcript noisy 或 low-confidence：带 confidence notes 作为 evidence 传递，由 Thinker/SlowTask 做 conflict resolution。

## Risks

- Streaming partials 在中英混合中可能不稳定。
- Timestamp precision 在 provider 与 self-host model 间可能差异很大。
- SenseVoice rich labels 有用，但可能诱发语义越权。
- API terms、model availability 与 current endpoint names 会变化。
- 如果 debug trace 捕获 audio 或完整 transcript，speech privacy 风险很高。

## Suggested Follow-up Experiments

- Benchmark Mandarin、English、mixed、numbers、names 与 short corrections。
- 比较 DashScope ASR 与 FunASR streaming 的 partial-final churn。
- 在带已知 word boundary 的 synthetic clips 上测 timestamp drift。
- 通过 mid-utterance interrupt 测 cancellation，并验证 stale handling。
- 用 noisy command clips 测 SenseVoice labels，并与 Thinker evidence 对照。

## Recommendation

把 ASR 作为 adapter-normalized evidence source。若 exact realtime contract 验证通过，DashScope/Bailian ASR 是第一个 API integration candidate；FunASR Paraformer streaming 作为 primary self-host fallback；SenseVoiceSmall 用于 enriched short-utterance evidence；Whisper large-v3-turbo 作为稳健 offline fallback。
