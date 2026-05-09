# Duplex 能力探针

## Status

evidence_report

## Date

2026-05-09

## Scope

本文覆盖 Duplex / VAD / realtime audio gate 的 MVP research 候选：本地 VAD、唤醒词、echo likelihood，以及轻量语义提示。本文不提出主 runtime、accepted ADR 或 canonical event name 的修改。

## Architecture Role

Duplex 是 ASR 与 Thinker evidence 之前的低延迟 live audio gate。它可以产生 speech start、speech end、wake/attention hint、echo likelihood 等 pre-ASR 信号；但 Interaction Controller 仍然拥有 turn ingress policy 与 truncate decision。大型 audio-language model 可以提供后置 evidence，不应拥有热路径权限。

## ADR Constraints

- ADR-001：Duplex 位于 Interaction Controller 权限边界之外；Interaction Controller 拥有 turn ingress 与 policy decision。
- ADR-003：barge-in 必须触发 `TTS_TRUNCATE_REQUESTED`，之后由 playback 确认 `TTS_TRUNCATED`；truncate 是 Talker/playback control contract。
- ADR-008：ASR/Thinker evidence fusion 由 SlowTask 处理冲突；Duplex hint 是 evidence，不是最终语义事实。
- ADR-011：任何外部模型路径都必须以 adapter 接入，并声明 capability matrix 与 output mode。
- ADR-012：MVP SLO 要求低延迟 barge-in，因此热路径必须足够确定、足够本地化，并可 replay。
- ADR-014：web evidence 只能作为 untrusted evidence。

## Candidate Shortlist

- Silero VAD：本地轻量 VAD；官方 README 提到 30 ms 及更大 chunk、CPU 友好推理、ONNX/PyTorch，以及 8 kHz / 16 kHz 采样支持。
- WebRTC VAD + WebRTC Audio Processing / AEC3：成熟 realtime voice stack，可覆盖 VAD、noise suppression、AGC 与 acoustic echo cancellation reference handling。
- openWakeWord：本地 wake-word detector，支持 ONNX/TFLite model，并可选用 Silero VAD gating。
- SpeexDSP / RNNoise 类 preprocessing：可作为 noise suppression 或 echo-adjacent preprocessing 候选，但不足以单独承担主要 echo policy。
- 延后语义提示模型：Qwen-Omni、MiniCPM-o、Moshi、Ultravox 可在后续提供 semantic-close 或 assistant-directedness evidence，但不进入 truncate 热路径。

## Official Sources Checked

- Silero VAD GitHub: https://github.com/snakers4/silero-vad
- openWakeWord GitHub: https://github.com/dscripka/openWakeWord
- WebRTC Audio Processing source tree: https://webrtc.googlesource.com/src/+/refs/heads/main/modules/audio_processing/
- SpeexDSP project: https://www.speex.org/
- Moshi GitHub, used only as non-hot-path spoken-dialogue comparison: https://github.com/kyutai-labs/moshi

## Capability Matrix Assessment

| field | Silero VAD | WebRTC VAD / AEC3 | openWakeWord | deferred audio LLM hint |
| --- | --- | --- | --- | --- |
| adapter_type | duplex | duplex | duplex | thinker_or_duplex_evidence |
| provider | snakers4 | WebRTC project | dscripka | Qwen / MiniCPM / Moshi class |
| model_name | silero-vad | webrtc-vad-aec3 | openwakeword | unknown |
| deployment_mode | self_hosted_local | self_hosted_local | self_hosted_local | api_or_self_hosted |
| supports_streaming_input | real | real | real | degraded |
| supports_streaming_output | real | real | real | degraded |
| supports_audio_input | real | real | real | real |
| supports_audio_output | unsupported | unsupported | unsupported | degraded |
| supports_audio_timestamps | degraded | degraded | unsupported | unknown |
| supports_structured_json | unsupported | unsupported | unsupported | degraded |
| supports_tool_calling | unsupported | unsupported | unsupported | unsupported |
| supports_cancellation | real | real | real | degraded |
| supports_emotion | unsupported | unsupported | unsupported | unknown |
| supports_audio_caption | unsupported | unsupported | unsupported | degraded |
| supports_tts | unsupported | unsupported | unsupported | unsupported |
| supports_tts_truncate | unsupported | unsupported | unsupported | unsupported |
| supports_tts_pause_resume | unsupported | unsupported | unsupported | unsupported |
| supports_semantic_close | unsupported | unsupported | unsupported | degraded |
| supports_assistant_directedness | unsupported | degraded | degraded | degraded |
| max_audio_seconds | streaming_window | streaming_window | streaming_window | unknown |
| max_context_tokens | not_applicable | not_applicable | not_applicable | unknown |
| max_output_tokens | not_applicable | not_applicable | not_applicable | unknown |
| expected_first_token_latency_ms | not_applicable | not_applicable | not_applicable | unknown |
| expected_first_audio_latency_ms | not_applicable | not_applicable | not_applicable | not_applicable |
| output_mode | real | real | fallback | degraded |
| degradation_notes | 只做 VAD；不覆盖 echo 或语义 | echo-reference 最强候选，但集成细节必须实测 | 只做 wake/attention；上游预训练覆盖偏英文 | 只作为 advisory evidence；不得进入 barge-in 热路径 |

## Candidate Comparison

Silero VAD 是最强的第一阶段 VAD 候选，因为它小、本地化，并支持 30 ms chunk。WebRTC VAD/AEC3 是最强的 echo-reference 与 realtime audio-processing 候选，因为它能在成熟音频 pipeline 中处理 playback reference、residual echo 与 voice activity。openWakeWord 适合做显式 wake/attention 实验，但不应替代 barge-in VAD。

Audio-language model 对 Duplex 角色反而较弱。它们可以在音频已缓冲后帮助判断片段是否 assistant-directed 或是否 semantic complete，但推理延迟与非确定性使其不适合即时 truncate。

## Recommended MVP Usage

建议使用 rule-based local hot path：

- Primary speech gate：Silero VAD 或 WebRTC VAD。
- Echo likelihood：WebRTC AEC/AEC3 playback reference，加 residual echo / energy / correlation telemetry。
- Wake/attention：openWakeWord 可选实验，MVP-0 不强依赖。
- Semantic close 与 assistant-directedness：在 Thinker 实验证明稳定前保持 mock 或 degraded evidence。

`speech_start <=150ms` 在 10-30 ms frame、本地推理、合理 buffering/hangover policy 下是现实目标，但仍需在真实 device/browser 上测量。

`barge-in -> truncate command <=250ms` 只有在路径保持本地时现实：mic frame -> VAD/echo gate -> Interaction Controller -> playback stop request。它不应等待 ASR、Thinker 或 omni model。

## API / Deployment Notes

Silero VAD 与 openWakeWord 可通过 ONNX/PyTorch/TFLite wrapper 在 Duplex adapter 后本地运行。WebRTC Audio Processing 可能需要 native 或 sidecar integration；若未来引入，也必须经 Duplex event interface 或 adapter boundary 进入，且不得改变 canonical event semantics。

## Latency and Resource Notes

Silero 官方 README 宣称单 CPU thread 上处理 30 ms audio chunk 可低于 1 ms。openWakeWord 处理 80 ms frame，并面向 modest CPU。WebRTC AEC 面向 realtime，但需要仔细处理 audio device timing、playback reference availability 与 thread isolation，避免阻塞 Interaction Controller 或 replay runner。

## Schema / Structured Output Notes

Duplex output 应是很小的 typed evidence，例如 speech start/end、confidence、echo likelihood、playback reference id。它不应输出 SemanticCommitment。Semantic close 与 assistant-directedness 应作为 optional hint fields，并在验证前标记为 `degraded` 或 `mock` output mode。

## Cancellation / Timeout / Retry Notes

本地 VAD/AEC processing 可通过丢弃 frame 与关闭 session stream 取消。如果 audio LLM 用于延迟 hint，late result 必须绑定原始 turn/task metadata；当 current plan 已前进时进入 stale evidence。

## Trace and Privacy Notes

不要在 repo fixture 中保存 raw audio。只保留 synthetic/redacted metadata，例如 frame time、VAD confidence bucket、echo likelihood bucket、playback span id 与 adapter output mode。Playback reference hash 或 id 不应暴露用户内容。

## Degradation Proposal

- 如果 AEC 不可用，echo likelihood 标记为 `unknown`，并在 TTS playback 期间使用更严格的 VAD threshold。
- 如果 VAD 噪声高，要求连续 voiced frames 后再触发 barge-in。
- 如果 wake-word 不可用，省略 wake hint，而不是阻塞 speech detection。
- 如果 semantic-close hint 不可用，保留 `unknown`；后续仍由 SlowTask/Thinker 解决冲突。

## Risks

- AEC 质量强依赖 playback reference routing 与 device timing。
- 过激 VAD 可能把 assistant echo 误判为用户插话。
- 过保守 VAD 可能错过快速 barge-in。
- Native audio component 若产生非结构化 side effect，会威胁 deterministic replay。
- 把 semantic hint 当成 policy 会与 ADR-001 和 ADR-008 冲突。

## Suggested Follow-up Experiments

- 在 synthetic Mandarin、English、mixed speech、noise、TTS echo 上测量 speech-start latency。
- 使用 local playback reference id 测量 barge-in-to-playback-stop latency。
- 比较 Silero VAD 与 WebRTC VAD 在 assistant playback 期间的 false positive。
- 在不保存 raw audio 的前提下 prototype echo likelihood bucket。
- 只把 Thinker 产生的 assistant-directedness 作为 post-hoc evidence 评估。

## Recommendation

优先使用 local rule-based Duplex：Silero 或 WebRTC VAD，加 WebRTC-style playback reference 与 echo likelihood。Semantic close 与 assistant-directedness 在 Thinker adapter 证明可靠前保持 mock/degraded evidence。不要把大型 omni model 放入 truncate 热路径。
