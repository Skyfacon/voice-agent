# Duplex / Audio Spike: Qwen-Audio-Realtime Web

## Status

`provider_free_implemented`; `real_adapter_implemented`; `fake_browser_smoke=executed`; `real_connection_smoke=executed_no_audio`; `real_audio_turn_smoke=executed_synthetic`; `real_barge_in_smoke=executed_synthetic`; `pre_fix_real_device_smoke=executed_one_turn`; `post_fix_real_device_smoke=not_executed`; `real_10min_smoke=not_executed`。

本报告记录一个与 voice-agent 主 runtime 隔离的 **Qwen Realtime Model Spike + 可交互网页壳**。它不是新的主 runtime MVP 编号，不是 MVP-7，也不代表 ADR-001 或 ADR-003 的目标架构验收通过。

## Context

本 spike 只验证以下独立链路：浏览器持续麦克风采集、localhost Python WebSocket gateway、Qwen-Audio-Realtime 上游连接、实时用户/助手字幕、24 kHz PCM 流式播放，以及插话后的本地旧音频清理。

它不接入 Interaction Controller、Router、SlowTask、Composer、Tool Executor 或主 Event Journal；不修改 ADR-002 canonical event registry；不从主 runtime import，也不由主 runtime 启动。页面的 timeline 是 metadata-only ephemeral debug timeline，不是核心 Event Journal。

## Question

1. 浏览器是否能持续把设备采样率的单声道 Float32 重采样为 16 kHz PCM16，并以约 100 ms/chunk 有界地送到本地 gateway？
2. spike-local adapter 是否能把 Qwen provider 事件安全归一化为网页字幕、状态和 24 kHz PCM 输出？
3. 插话或显式取消时，前后端是否能用 `playback_epoch` 清除旧播放并丢弃迟到音频？
4. fake provider 是否足以在没有 credential 时重复验证协议、背压、断线和安全边界？

## Setup

- 检查日期：2026-07-15（Asia/Shanghai）
- 模型：`qwen-audio-3.0-realtime-plus`
- 实现形态：Python `asyncio` + `aiohttp` localhost gateway；浏览器 AudioWorklet capture/player；spike-local real/fake provider adapter
- 真实北京 endpoint 模板：`wss://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime?model=qwen-audio-3.0-realtime-plus`
- 输入：PCM16、16 kHz、mono
- 输出：PCM16、24 kHz、mono
- 默认 turn detection：`smart_turn`
- 默认评估模式：`headset_full_duplex`
- 无 tools、Function Calling、真实外部工具或持久化存储
- 自动化 fixture：仅 synthetic / redacted / minimal；不含 raw audio 文件或 provider 原始响应
- credential 通过本机 `~/.voice-agent-secrets/dashscope.env` 的 `DASHSCOPE_API_KEY`、`QWEN_REALTIME_WORKSPACE_ID` declarations 注入子进程；Workspace ID 从用户提供的同一北京 workspace compatible-mode endpoint hostname 前缀推导并配置。API Key、Workspace ID 实值和完整 endpoint 均未写入本报告或仓库。

## Official Sources Checked

以下四个阿里云官方页面于 2026-07-15 重新检查，HTTP 均为 200：

- [Qwen-Audio-Realtime 用户指南](https://help.aliyun.com/zh/model-studio/qwen-audio-realtime-user-guides)；页面 `lastModified=2026-07-14T10:13:16Z`
- [Qwen-Audio-Realtime WebSocket API](https://help.aliyun.com/zh/model-studio/qwen-audio-realtime-websocket-api)；页面 `lastModified=2026-07-14T10:12:31Z`
- [客户端事件](https://help.aliyun.com/zh/model-studio/fun-audiochat-client-events)；页面 `lastModified=2026-07-14T10:12:46Z`
- [服务端事件](https://help.aliyun.com/zh/model-studio/qwen-audio-realtime-server-events)；页面 `lastModified=2026-07-14T10:12:59Z`

复核结果：

- 北京 workspace endpoint、Bearer API Key、16 kHz PCM16 mono 输入、24 kHz PCM16 mono 输出与本 spike 假设一致。
- 客户端使用 `session.update` 和 `input_audio_buffer.append`；支持 `smart_turn`、`server_vad`、`manual` turn detection。
- 服务端包含 `session.created` / `session.updated`、`input_audio_buffer.speech_started` / `speech_stopped`、用户转写 `conversation.item.input_audio_transcription.delta` / `completed`、助手 `response.audio_transcript.delta` / `done`、`response.audio.delta` / `done`、`response.done` 和 `error`。
- 支持 `response.cancel`，但显式 cancel 仅在 response active 时合法；server turn detection 下 provider 也会自动取消 active response。
- `smart_turn` 无效轮可能返回 `speech_stopped(reason=turn_invalid)` 且不触发推理。
- `speech_started` / `speech_stopped` 带 `audio_start_ms` / `audio_end_ms`，可提供输入轮次级粗粒度时间；本次未确认输出音频到文本的精确 alignment。
- 用户指南说明上下文最多保留 50 轮、累计音频 300 秒。这是 context retention 说明，不等于单 turn 或 WebSocket session 的硬上限。
- 官方 provider 支持 Function Calling；本 spike 刻意使用 `tools=[]`，且 local adapter profile 不暴露 tool-calling 能力。provider capability 与本实现启用状态不可混写。
- 同一官方文档组存在 chunk 建议差异：用户指南给出约 100 ms，即 3200 bytes；客户端事件页建议 20–40 ms/帧。本 spike 遵循任务硬要求及用户指南，浏览器约每 100 ms 发送 3200-byte frame；后续 live eval 应比较 20–40 ms 对首转写延迟和开销的影响。

## Synthetic Inputs

自动化验证使用短小的内存合成值，不落盘：

- 多个 3200-byte PCM-like binary frame，用于持续转发与背压。
- redacted 用户转写 delta/final 和助手字幕 delta/done。
- 短 24 kHz PCM-like byte string，用于 `QAR1 + uint32_be(epoch) + PCM` framing。
- `speech_started`、`speech_stopped`、active response、cancel、late/out-of-order audio、provider/browser disconnect 和安全归一化 error。
- fake / real / degraded capability profile 与缺失/伪造 credential 配置。

真实 provider smoke 另使用 macOS 本地 TTS 生成的 synthetic 中文输入，经浏览器 `MediaStream`、capture AudioWorklet 和 gateway 发送。临时 AIFF/WAV 只位于 `/private/tmp`，不含真人语音；smoke 后已删除。页面/工具只记录事件是否出现、字符数、字节数、safe ref、延迟和状态，没有记录实际 provider 转写或回复原文。

这些值只用于协议测试，不是可播放的 raw audio fixture，也不包含真实用户输入或真实 provider body。

## Architecture and Local Protocol

数据路径：

```text
Browser AudioWorklet (capture/resample/PCM16)
  -> local WebSocket binary frame
  -> SessionBridge bounded input queue
  -> spike-local provider adapter
  -> Base64 input_audio_buffer.append

Provider event
  -> spike-local normalization
  -> SessionBridge bounded output/control path
  -> browser JSON status/transcript/timeline

Provider response.audio.delta
  -> Base64 decode
  -> QAR1 + uint32-be playback_epoch + PCM16 binary frame
  -> AudioWorklet streaming player
```

浏览器到 gateway：

- binary：raw PCM16/16 kHz/mono；推荐 3200 bytes，单帧硬上限 6400 bytes。
- JSON：`client.configure`、`client.cancel`、`client.microphone`、`client.ping`。

gateway 到浏览器：

- JSON：`session.ready`、`session.status`、`user.transcript.delta|final`、`assistant.transcript.delta|done`、`playback.started|clear`、`response.done`、`flow.dropped`、`session.error`、`timeline.event`。
- binary：4-byte ASCII magic `QAR1` + unsigned 32-bit big-endian `playback_epoch` + PCM16/24 kHz/mono payload。

`speech_started` 或显式 cancel 会递增后端 epoch、清空有界输出队列并发送 `playback.clear`；前端同步递增/采用新 epoch、立即清 AudioWorklet buffer，并丢弃 epoch 不匹配的迟到音频。`speaker_safe` 在助手播放期间不上送麦克风音频，因此明确不支持播放期间 barge-in；`headset_full_duplex` 持续上送，并提示佩戴耳机。

页面把用户转写和助手字幕投影到同一有界 QA 对话流，每轮 DOM 固定为 User -> Assistant，流式 delta 原位更新。助手侧用 safe `response_ref` 优先、`response_epoch` / `playback_epoch` 次优关联到 bubble；`completion_only` 的旧回复完成事件只终结自己的 bubble，不改变当前 response/activity。provider 当前没有为用户转写暴露稳定 turn/item ref，因此用户侧只能按 `speech.started` / `speech.stopped` 时间边界做 spike-local best effort 关联，不能把该投影称为 canonical turn 或核心 Event Journal。Disconnect 保留可见历史供检查，下次 Connect 才清空；内存上限为 32 轮、32,000 总字符、每 bubble 6,000 字符，所有 transcript 只通过 `textContent` 写入。

## Observations

### Provider-free / fake

- fake provider 路径不需要 API Key 或 workspace id，可产生 synthetic 用户转写、助手字幕和流式 24 kHz PCM-like 输出。
- 有界输入队列在超过约 500 ms backlog 时丢弃最旧 frame，并通过 drop counter / degraded 状态暴露，不无限保存音频。
- interrupt、cancel 和 late-audio 路径以 epoch 隔离；旧 epoch binary 不会重新进入当前播放。
- browser/provider 断线会结束 session tasks；旧麦克风音频不被静默重放。
- 统一 QA 投影在插话、显式取消、provider error 和 transport abort 后保留已显示 partial text，并以 interrupted / cancelled / error 标记对应 bubble；terminal 后迟到 delta 和重复 done 不会复活或复制旧回复。

### Real adapter

- provider endpoint 和 Authorization header 只在 spike-local real adapter 内构造。
- gateway 不向浏览器、timeline 或 capability metadata 返回 API Key、Authorization header、原始 provider error/body 或完整 `session.update` payload。
- provider event 被归一化后才进入 session bridge；未知事件只产生有界 metadata timeline 条目。
- `response.cancel` 是 active-response best effort；即便 provider 已自动取消或 response 已结束，本地 playback clear/epoch advance 仍立即执行。

### Browser / live smoke

本地 fake server 已用真实 Chromium/Playwright 页面执行 smoke：静态页与 AudioWorklet 加载、WebSocket Connect、`fake · mock` 标识、metadata timeline、`speaker_safe` 文案/配置、显式 Cancel、Disconnect 均正常，console 为 0 error / 0 warning。Cancel 在服务端确认前即把本地 epoch 从 0 推进到 1；一次观测的 `client.cancel -> AudioWorklet clear ack` 为 104 ms，随后同 epoch 服务端 clear ack 的 Worklet 确认为 13 ms。它们是单次本机 fake/control-path 观测，不是 `speech_started` 指标、真实网络延迟或 ADR-003 truncate 证据。

自动浏览器没有可用麦克风设备/授权；点击 Start microphone 后页面正确进入 `permission=denied` / `Error`，仍可正常 Disconnect。持续真实设备采集、声卡播放和 10 分钟资源趋势保留为人工验收项。

真实百炼已完成 **connection-only smoke**：本机 secret declarations 被安全加载，real server 连接成功；浏览器显示 `Provider=real`，metadata timeline 依次观察到归一化的 `session.created` 和 `session.updated`，console 为 0 error / 0 warning。这证明当前 credential、推导的北京 Workspace ID、上游 endpoint、Bearer 握手和 `session.update` 协商在本次检查中可用。

随后完成真实百炼 **synthetic-audio turn smoke**：合成语音从页面 `MediaStream` 进入 capture AudioWorklet，连续发送到本地 gateway 和真实 provider；观察到 `speech.started` / `speech.stopped`、用户转写 delta/final、助手字幕 delta/done、流式 `response.audio.delta` 和 `response.done(completed)`。页面渲染了非空用户/助手文本，但未记录原文；输入丢帧为 0，单轮结束时页面为 healthy。

真实百炼 **synthetic barge-in smoke** 也已执行：在长回复播放期间注入第二段合成语音，`playback_epoch` 从 1 推进到 2，AudioWorklet 本地 clear ack 为 2 ms，旧 provider response 到达 `status=cancelled`，新轮 response 随后 `completed`。本次没有观察到迟到旧音频 frame，因此“不回流”的 live 证据仍以 epoch/clear、cancel 状态和自动化 late-frame tests 为主。该长回复曾触发旧版两秒 player ring 的 `flow.output_dropped`；后续真人设备复现证明这不是 headless-only 限制。

真人设备随后完成一轮真实麦克风/耳机交互。使用者主观感受整体响应非常快，但 TTS 前段含混、破碎，尾段恢复清晰；页面 metadata 记录的 first audio 为 24 ms。页面只保留最后 80 条时间线，因此以下均为下限：可见 28 条 audio delta、合计至少 522,240 bytes（PCM16/24 kHz 下 10.88 秒），集中在约三秒内到达；峰值一秒 12 个 19,200-byte chunk，相当于 4.8 倍实时音频；同一 epoch/response ref 内出现 28 次播放器 `flow.output_dropped`，累计至少 204,800 samples（8.53 秒）被旧版 drop-oldest ring 删除。输入丢帧仍为 0。该时序与“突发阶段持续硬跳 PCM、provider 结束后尾部连续播放”一致，没有多 response 混音证据。未保留实际 provider 转写或回复原文、raw audio 或 raw provider payload。

已据此先把播放器改为 12 秒有界、保序 chunk queue：enqueue 不再逐 sample 复制，render quantum 按需转换；当前 epoch 的旧 PCM 不再为新 chunk 让位。使用者随后反馈此前“前段混杂、后段清晰”的主观问题基本解决，但某些真实回复出现安全错误 `OUTPUT_CAPACITY_EXCEEDED`。

对端口 8766 的本轮页面只读取 metadata、不读取转写：旧 hard capacity 为 288,000 samples（12 秒）；报错前已有 280,832 samples（11.701 秒），下一块为 19,200 bytes，即 9,600 samples（0.4 秒），入队后会达到 290,432，实际只超出 2,432 samples（约 101 ms）。同一 response/epoch 的可见记录包含 39 个 audio frame、合计 733,440 bytes（15.28 秒 PCM），约四秒内到达；平均约 3.8 倍实时，峰值一秒 14 块（5.6 倍实时）。Gateway output drop 为 0、queue high-water 为 5/32，且 response/epoch 一致，因此定位为 Qwen 快于实时突发耗尽浏览器旧 12 秒硬缓冲，而不是 gateway 拥塞、跨 epoch 混音或重复解码。页面随后按旧 hard guard 推进 epoch、clear/cancel，迟到音频均成为 stale；同页的 browser-local input drop 与稍后 provider receive timeout 是独立问题。

最新修复把 12 秒（288,000 samples）降级为 **soft watermark**：越线只发 metadata 告警、标记 degraded，并继续按 FIFO 播放；缓冲降到 9 秒以下后 rearm。真正的 **hard cap** 提高为 60 秒（1,440,000 samples，约 2.88 MB PCM16），只有命中该边界才整块拒绝新 frame、推进 epoch、clear 并请求 `response.cancel`。页面展示当前 / 本轮峰值 / soft / hard，并记录 AudioContext state；每次 response start 会 best-effort 恢复 suspended context。可执行 Worklet harness 使用 39 × 19,200-byte（15.6 秒）同时突发验证逐样本 FIFO、零 drop、单次 soft 告警、恢复/rearm，并继续覆盖 24/44.1/48 kHz、累计 chunk、underflow、clear/late epoch 和 60 秒 hard-cap fail-coherent。最新修复后的真人耳机复测和 10 分钟稳定性仍为 `not_executed`；synthetic/harness 证据不能外推为设备验收或生产 SLO。

## Capability Matrix Result

下表的 `health_status` 是代码中 capability profile 的静态初始值，不是一次浏览器会话的动态健康存储。此次已取得真实连接、synthetic audio/model response 和 barge-in 证据；profile 默认值仍保留 `not_executed`，运行时仅在当前连接内变为 ready/degraded，不把一次 smoke 持久化成生产健康声明。

| 字段 | real profile | fake profile | 证据 / 限制 |
| --- | --- | --- | --- |
| `adapter_id` | `qwen_audio_realtime_web.qwen_remote.v1` | `qwen_audio_realtime_web.fake.v1` | spike-local，不进入主 registry |
| `adapter_type` | `duplex_model_spike` | `duplex_model_spike` | real provider 同时提供转写、字幕和音频；不等于 ADR-001 Duplex owner |
| `provider` | `aliyun_bailian` | `spike_local_fake` | fake 为确定性 synthetic harness |
| `model_name` | `qwen-audio-3.0-realtime-plus` | `synthetic-qwen-realtime-fake` | real 名称来自 2026-07-15 官方复核 |
| `deployment_mode` | `remote_api` | `mock` | real `endpoint_ref=aliyun-bailian/cn-beijing/realtime`，不含 credential |
| `health_status` | profile default=`not_executed`；成功连接 runtime=`ready` | `ready` | real connection、synthetic audio/model response 已执行；设备/稳定性未验收 |
| `capability_version` | `qwen-audio-realtime-web-spike.v1` | `qwen-audio-realtime-web-spike.v1` | 独立 capability profile |
| `latency_class` | `remote_realtime_unmeasured` | `synthetic_configurable` | 有单次 synthetic live 观测，但不足以形成 SLO |
| `error_model` | timeout / connect / provider / schema / disconnect | deterministic fake error / disconnect | 浏览器只看到安全错误码 |
| `timeout_policy` | bounded connect/session timeouts | bounded deterministic waits | mid-turn 断线标 current turn failed |
| `retry_policy` | 当前 session 不自动重放；安全状态人工重连 | none | 不重放旧用户音频 |
| `output_mode` | `real`（仅配置态）/ failure 时 `degraded` | `mock` / 注入故障时 `degraded` | UI 和 metadata 必须明确标识 |
| `supports_streaming_input` | yes (official / adapter implemented) | yes (tested) | `input_audio_buffer.append` |
| `supports_streaming_output` | yes (official / adapter implemented) | yes (tested) | transcript/audio delta |
| `supports_audio_input` | yes | yes | PCM16/16 kHz/mono |
| `supports_audio_output` | yes | yes | PCM16/24 kHz/mono |
| `supports_audio_timestamps` | profile=false；官方有输入轮次级粗时间 | no | `audio_start_ms` / `audio_end_ms` 已文档化；输出 word/token/audio alignment 未验证，因此不提升通用 capability |
| `supports_structured_json` | not used | not used | provider events只做协议归一化 |
| `supports_tool_calling` | profile=false / disabled | no | 官方 provider 支持 Function Calling，但本 spike `tools=[]`，不实现、不归一化、不授权工具 |
| `supports_cancellation` | yes, active response only | yes | `response.cancel` + local epoch clear |
| `supports_emotion` | unknown | no | 未执行 |
| `supports_audio_caption` | unknown | no | 未执行 |
| `supports_tts` | yes | synthetic audio | provider audio reply，不拆成主 runtime TTS Adapter |
| `supports_tts_truncate` | **not proven for ADR-003** | local buffer clear only | cancel/epoch 没有 `actual_stop_offset_ms` 和 playback-reference contract |
| `supports_tts_pause_resume` | no / not evaluated | no | 明确 non-goal |
| `supports_semantic_close` | provider `smart_turn`, but target capability unproven | scripted only | 不能替代 ADR-001 ingress owner |
| `supports_assistant_directedness` | unknown | no | 未执行 |
| `max_audio_seconds` | profile=300（仅表示官方 context retention 累计 300 s） | profile=None；bounded by session queues, not persisted | 300 s 不是单 turn/session 硬上限；单 turn/session 上限仍 unknown |
| `max_context_tokens` | profile=None；官方 context retention=最多 50 轮 | n/a | 50 轮不是 token 上限 |
| `max_output_tokens` | unknown | n/a | 未执行 |
| `expected_first_token_latency_ms` | `not_calibrated` | synthetic only | 单次 real-provider synthetic 观测 8 ms，不是 expected SLO |
| `expected_first_audio_latency_ms` | `not_calibrated` | synthetic only | 单次 real-provider synthetic 观测 54 ms，不是 expected SLO |

## Latency and Resource Notes

一次 real-provider synthetic turn 的页面指标如下，仅用于证明观测链路可工作，不是生产 SLO 或真实设备质量结论：

- first user transcript delta：0 ms；表示当前本地 monotonic 量化下同毫秒到达，不表示网络延迟为零
- `speech_stopped -> first assistant transcript delta`：8 ms
- `speech_stopped -> first audio delta`：54 ms
- synthetic barge-in 的 `speech_started -> local playback cleared`：2 ms；满足本次 control-path 目标，但不是声卡实际停止出声时间或 ADR-003 truncate 证据
- synthetic live 输入丢帧：0；旧版两秒 player 在长回复中发生 output overflow；真人设备随后复现同类前段听感问题，先修复为保序 chunk queue
- 真人设备修复前页面 first audio：24 ms；同轮可见 timeline 中至少 10.88 秒音频在约三秒内突发到达，旧播放器累计丢弃至少 8.53 秒；这些是单次 metadata 诊断值，不是生产 SLO
- 使用者主观反馈旧版混杂/破碎问题在保序播放器后基本解决；随后另一真实轮次以约 3.8 倍实时突发 15.28 秒 PCM，旧 12 秒 hard guard 仅因约 101 ms 余量不足触发 `OUTPUT_CAPACITY_EXCEEDED`
- 最新 Worklet deterministic burst：39 × 19,200 bytes（15.6 秒）同时入队，逐样本 FIFO、player drop=0、soft warning 一次且恢复后可 rearm；hard guard 为 60 秒
- 本地 fake 显式 Cancel -> Worklet clear ack：单次 104 ms（服务端同 epoch clear 再确认 13 ms）；仅为 control-path smoke，不替代上一项
- 修复后真人麦克风/耳机复测、10 分钟连续运行、内存趋势和真实设备 AudioWorklet underrun：`not_executed`

资源边界来自实现而非 live 观察：输入/输出队列有界；浏览器只保留短期 worklet/ring buffer；停止会话和页面卸载时关闭 media tracks、AudioContext 和 WebSocket；gateway 不持久化 raw audio。

## Schema / Validation Notes

- provider-specific事件只在 `provider_adapter.py` 解析，业务桥接只消费 normalized event。
- Base64 音频 decode、event type、必需字段、output mode 和 epoch 在边界校验；malformed/unknown provider payload 不直接透传浏览器。
- 浏览器单帧、origin、JSON message shape 和 mode 均需校验；server CLI 仅允许绑定 `127.0.0.1` / `localhost`。
- 该 spike 的 local protocol 名称不是 ADR-002 canonical events；metadata timeline 不使用 `FAST_INTERACTION_OUTPUT`、`SEMANTIC_COMMITMENT`、approved `SPOKEN_PLAN` 等名称。

## Cancellation / Timeout / Retry Notes

- `speech_started`：立即本地 epoch advance + playback clear；active response 时向 provider best-effort `response.cancel`。
- 显式 `client.cancel`：无论 provider response 是否仍 active，都先完成本地清理；provider cancel 错误安全归一化。
- old/out-of-order audio：epoch 不匹配即丢弃，不允许重新播放。
- provider timeout/disconnect：current turn 标 failed/degraded，结束相关 tasks；不重放旧输入。
- browser disconnect：取消 session-owned tasks、清队列并关闭 provider；不保留音频。
- reconnect：仅由新的安全 session 发起；当前实现不做透明 mid-turn replay/retry。

## Trace and Privacy Notes

自动化和 code review 检查结果：

- API Key 只从后端环境读取；不进入浏览器 bundle、capability metadata、timeline、异常字符串、测试 fixture 或报告。
- Workspace ID 只在本机 secret 环境中配置；报告仅记录其从用户提供的 compatible-mode endpoint hostname 前缀推导，不记录实际值或完整 workspace endpoint。
- 不记录 Authorization header、完整 `session.update`、原始 provider payload/error/body。
- 不持久化 raw audio；测试仅构造短内存 bytes，仓库没有音频 fixture。
- timeline 默认仅含 event type、timestamp、byte length、safe session/response ref、latency、output mode 和 drop/error code 等 metadata。
- fake fixture synthetic / redacted / minimal；无真实转写或 provider response 原文。
- 未创建新的 raw audio / trace / replay-cache 目录；已有 `.gitignore` governance 保持有效。

## Automated Evaluation

统一入口：

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python \
  ./scripts/test -q tests/experiments/test_qwen_audio_realtime_web*.py
```

覆盖范围：session connect/update、连续 audio forwarding、用户 transcript delta/final、助手 transcript delta、QAR1+epoch PCM 输出、speech_started playback clear、response.cancel、old epoch discard、provider/browser disconnect、safe provider error、bounded queue/drop counter、gateway/player 分层 output-drop telemetry、真实突发节奏的逐样本 FIFO、24/44.1/48 kHz render、underflow、hard-cap fail-coherent、credential serialization safety、无 raw-audio fixture、real/fake/degraded 区分、Origin 与最大 frame 安全路径，以及统一 QA 的多轮顺序、delta/final 投影、response/epoch 关联、terminal 幂等、barge-in 文本保留、history bound 和 textContent 安全。

验证结果：

- 允许 loopback bind 的最终 spike 测试：`88 passed in 2.62s`，覆盖 aiohttp 静态资源、Origin、WebSocket max-frame、端到端 fake 流、严格 provider handshake、安全认证错误分类、直接执行真实 player worklet 的回归、soft/hard capacity 页面状态和统一 QA conversation cases。
- 全仓统一入口最终复跑（允许 loopback bind）：`1737 passed in 12.77s`，没有主 runtime 回归。
- JavaScript syntax：`app.js`、`mic-worklet.js`、`player-worklet.js`、Worklet harness 和 conversation harness 均通过 `node --check`；capture worklet 的 44.1 kHz 与 48 kHz 一秒合成输入均精确产生 16000 个 16 kHz output samples；player worklet 在 24/44.1/48 kHz 路径均通过一秒渲染断言。
- 最新 Chromium fake-page smoke：页面显示 soft=`12000 ms`、hard=`60000 ms`；Connect / disconnect 通过，player/Gateway output drop 均为 0，console 0 error / 0 warning；没有保留 Playwright snapshot/trace。
- 统一 QA Chromium smoke：synthetic 三段 `MediaStream` 实际经过 capture AudioWorklet、browser WebSocket、gateway 和 fake provider，页面得到三轮固定 User -> Assistant 对话；player/Gateway output drop 均为 0，Disconnect 后 3 轮仍可查看，重新 Connect 后清零，console 0 error / 0 warning。本次 fake 单次页面指标为 first user transcript 121 ms、speech stopped -> assistant text/audio 23 ms、speech started -> local clear 4 ms，只用于 UI/control-path 验证。Playwright snapshot/trace 已删除。
- 修复后 Chromium real connection-only smoke：页面 `Provider=real`；归一化 `session.created`、`session.updated` 依次到达；player/Gateway output drop 均为 0，console 0 error / 0 warning；未启动麦克风、未发送 audio/transcript、未触发 model response，也未保留 raw provider payload/trace。
- Chromium real synthetic turn smoke：真实 provider 收到页面 AudioWorklet 音频；speech/transcript/assistant/audio/done 全链路通过，输入丢帧 0；实际转写和回复原文未记录。
- 修复前 Chromium real synthetic barge-in smoke：epoch `1 -> 2`、本地 clear 2 ms、旧 response cancelled、新 response completed；旧两秒 player overflow 使该轮 degraded。修复后 connection-only 已复跑，但修复后 real audio/barge-in 尚未重跑，不能替代真实耳机验收。

## Manual Acceptance Checklist

真实 connection、修复前 synthetic audio/barge-in 与一轮修复前真人设备交互已完成；修复后的真人听感、多轮和稳定性仍需执行：

- [ ] `headset_full_duplex` 连续运行至少 10 分钟，无明显内存无限增长。
- [ ] 连续多轮均有用户 partial/final、助手字幕和首帧即时播放。
- [ ] 耳机模式下用户插话，`speech_started -> local playback cleared <=250 ms`。
- [ ] 人为制造迟到旧音频，旧 epoch 不重新播放。
- [ ] `speaker_safe` 播放期间不上送 mic，且 UI 不声称 full duplex/barge-in。
- [ ] 断开 provider、浏览器和麦克风权限拒绝均显示安全错误并完成清理。
- [ ] 页面、console、timeline、server log 和 repo 均找不到 API Key/Authorization。
- [ ] 10 分钟运行后 repo 中仍无 raw audio、raw provider trace 或真实转写。
- [ ] 比较 100 ms 与官方客户端事件页建议的 20–40 ms chunk，记录 latency/CPU/network trade-off。

## Degradation Proposal

- 无 credential：运行 fake，UI 明确 `mock`；real health 为 `not_executed`。
- provider timeout/error/disconnect：结束当前 turn，标 `degraded`/failed；不回放输入、不伪造回复。
- 输入 backlog：drop-oldest 并增加 dropped counter；UI 显示 degraded。
- player backlog：12 秒 soft 水位只告警并继续保序播放，降到 9 秒以下 rearm；60 秒 hard cap 才整块拒绝、推进 epoch、clear 并取消当轮，不做 mid-waveform drop-oldest 拼接。
- interrupt：立即清空旧 epoch chunk refs；不播放 stale response。
- speaker 环境：切换 `speaker_safe`，牺牲播放期间打断，避免把该模式误称 full duplex。
- provider不提供精确 playback truncate/offset：仅声明 spike-local cancel + buffer clear，不宣称 ADR-003 target-valid。

## Recommendation

当前实现适合作为本地 provider-free 开发壳和 Qwen live smoke harness；本次已经验证真实 credential/Workspace endpoint、synthetic audio/model response 和 synthetic barge-in 链路。下一步应在真人麦克风与耳机环境完成主观音质/转写、物理停止出声和人工 10 分钟验收，再决定是否进入主 runtime 适配讨论；不要直接 import 此 spike。

若未来接入主 runtime，至少需要新的/修订的 accepted ADR 来决定：

1. provider-native duplex model 与 ADR-001 Duplex、Interaction Controller、ASR、Thinker、Talker 的职责切分，尤其 provider `smart_turn` 如何映射到唯一 turn ingress owner。
2. provider ephemeral events 到 ADR-002 canonical journal 的映射、safe refs、deterministic replay 和 capability snapshot；不得把本 spike event names直接加入 registry。
3. `response.cancel`、browser playback epoch、provider自动取消与 ADR-003 `BARGE_IN_CANDIDATE -> TTS_TRUNCATE_REQUESTED -> TTS_TRUNCATED(actual_stop_offset_ms)` 的对齐，以及真实 playback-reference AEC。
4. 将 Qwen 作为一个复合 provider还是拆成 ASR / Fast Interaction / Thinker / TTS role adapters；若产生 fast answer，必须经 ADR-017 Fast Foreground Gate，不能把 provider直出回复标成 approved foreground output。
5. 真实用户音频/transcript/provider metadata 的生产隐私、retention、consent、export/redaction 策略；ADR-010 当前只覆盖 debug-first web demo边界。
6. remote session retry、reconnection、context continuation和账单/限流策略；禁止静默重放旧音频。

## Capabilities This Spike Does Not Validate

不能宣称：

- ADR-001 的 Duplex + deterministic Interaction Controller 唯一 ingress owner 已通过。
- ADR-003 的 playback-reference AEC、可审计 playback offsets、`TTS_TRUNCATED(actual_stop_offset_ms)` 或 target-valid truncate 已通过。
- ADR-002 per-session canonical Event Journal / deterministic replay 已通过；timeline 只是 spike-local metadata。
- ADR-017 Fast Foreground Gate 已应用；provider reply 不是 `FAST_INTERACTION_OUTPUT`、`SemanticCommitment` 或 approved `SpokenPlan`。
- Router、SlowTask、UserPatch、Composer、Tool Executor、真实工具、确认/授权或生产部署已验证。
- 浏览器 `echoCancellation` 等价于 playback-reference AEC。
- `speaker_safe` 支持 full duplex 或播放期间 barge-in。

## Open Questions

- 100 ms 与 20–40 ms upstream frame 在真实链路上的 first transcript、first audio、CPU 和网络开销差异多大？
- `smart_turn` 的 `turn_invalid`、自动 response cancel 和迟到 audio 在网络抖动下是否始终带足够 response/session ref 供 epoch 关联？
- provider 是否暴露足够精度的音频/文本 alignment，未来能否映射 ADR-003 playback offsets？
- 浏览器设备、蓝牙耳机和扬声器组合下的 capture/playback sample-rate drift 与 AudioWorklet underrun 情况如何？
- 长会话 context、官方限额、费用、rate limit 和安全 reconnect 窗口仍需 live 验证。
