# Qwen Realtime Fast/Slow Slice 1 Acceptance

日期：2026-07-21

状态：自动化验收与真实浏览器 Fake smoke 均通过；本文只覆盖 provider-free Slice 0 + Slice 1。ADR proposal 状态仍为 `proposed`，不得据此接入真实 Qwen 或宣称 accepted。

## 验收边界

- 包含：浏览器 AudioWorklet、本地 loopback WebSocket v2、Fake Provider、RealtimeSessionCoordinator、canonical Event Journal、Router 四分支、Fast Foreground Gate、MockSlowTask、UserPatch、候选 quarantine、interrupt/playback epoch、脱敏 UI metadata。
- 不包含：真实百炼/Qwen endpoint、provider credential、真实外部工具、生产认证与隐私策略、直接播放未通过 Gate 的 provider-native 音频。
- `route.decided`、`gate.result` 等是 experiment-local 浏览器协议；canonical replay 只消费 ADR-002 registry 中的事件。

## 自动化覆盖矩阵

| 验收项 | 自动化证据 | 当前状态 |
| --- | --- | --- |
| WebSocket v2 控制解码、版本/大小限制、QFS2 PCM 打包 | `test_browser_protocol.py` | executed_pass |
| local browser message 与 canonical registry 分离 | `test_browser_protocol.py` | executed_pass |
| 16 kHz PCM16 mono、100 ms AudioWorklet 采集 | `worklet_harness.js` / `test_browser_assets.py` | executed_pass |
| 24 kHz 播放、bounded output、epoch clear、late audio drop | `worklet_harness.js` / `test_browser_assets.py` | executed_pass |
| proposal candidate 在授权 transcript 前不可见 | `app_harness.js` / `test_browser_assets.py` | executed_pass |
| UI task state 只由 `slowtask.state` / `userpatch.accepted` 更新 | `app_harness.js` / `test_browser_assets.py` | executed_pass |
| metadata timeline allowlist 与 100 行上限 | `app_harness.js` / `test_browser_assets.py` | executed_pass |
| capability 不 overclaim real/AEC/direct-before-gate | `test_contracts.py` | executed_pass |
| turn/utterance/audio span/provider item/response/epoch correlation | `test_contracts.py` | executed_pass |
| quarantine text/audio/response bounds、overflow fail closed、epoch mismatch discard | `test_contracts.py` | executed_pass |
| Fake connect、continuous PCM forwarding、ASR delta/final、candidate text/audio、response done | `test_fake_provider.py` | executed_pass |
| response.cancel、late old-response audio、provider error/disconnect | `test_fake_provider.py` | executed_pass |
| server connect/configure、Router/Gate/SlowTask/UserPatch/canonical journal | `test_session_coordinator.py` / `test_server.py` | executed_pass |
| raw audio/trace fixture、真实 endpoint、secret lookup、runtime 反向 import 检查 | `test_security.py` | executed_pass |

完整新实验测试在允许 loopback 临时端口的本机环境中执行，aiohttp 测试没有 skip：

```text
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python \
  ./scripts/test tests/experiments/qwen_realtime_fast_slow -q

108 passed in 1.65s
```

相关控制面回归：

```text
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python \
  ./scripts/test \
  tests/interaction \
  tests/router \
  tests/runtime/test_mvp63_fast_foreground_gate.py \
  tests/user_patch \
  tests/slowtask -q

82 passed in 0.30s
```

## Browser 与人工状态

- Node AudioWorklet/DOM projection harness：`executed_pass`。
- 真实 Playwright 页面 smoke：`executed_pass`。主 agent 启动 `127.0.0.1:8767` 后验证 Connect、FAST、SPAWN、PATCH、IGNORE、AMBIGUOUS、cancel/confirm、late audio、Disconnect/Reconnect；console 为 0 errors / 0 warnings。
- 实测结果：FAST Gate passed；SPAWN/PATCH candidate 均未泄漏且 plan version `1 -> 2`；IGNORE 未新增 assistant 行；AMBIGUOUS 只显示受控 CLARIFY；confirmation 保持 PATCH；late discard counter 上升；重连后 task/conversation/epoch/counters 归零。
- 真人麦克风、真实扬声器/耳机、物理 truncate/AEC：`not_executed`。

人工验收清单：

1. Connect 后收到 `session.ready`；Disconnect 后 microphone track、AudioContext、WebSocket、pending queues 全部清理。
2. Start/Stop microphone；确认浏览器持续发送 3,200-byte PCM frame，停止与 page unload 后不再发送。
3. Fast：先看到 proposal/local decision/Gate，再看到 assistant transcript 与音频；Gate 前 QA 与播放器没有 candidate。
4. Spawn：candidate discarded，只出现受控 `ACK_SLOW`，页面出现一个 active task、`plan_version=1`。
5. Patch：candidate discarded，先出现 `userpatch.accepted`，plan version 只在 SlowTask/UserPatch 解释后推进。
6. Ignore：无 assistant 输出；Ambiguous：只出现受控 `CLARIFY`。
7. Cancel 后出现 pending confirmation；Confirm/Reject 仍走 PATCH/UserPatch，不走普通 FAST reply。
8. 播放时 Interrupt 或新 `speech_started`：epoch 递增、播放器立即 clear、旧 epoch 音频不恢复，clear latency 与 discard counter 更新。
9. Provider error/disconnect：页面只显示固定 safe code 与 degraded 状态，不显示 provider body。
10. Timeline 只含 enum、safe id、计数与 latency；不含 PCM、credential、authorization、raw payload 或未脱敏真实转写。

## 安全检查

- 不读取 `DASHSCOPE_API_KEY` / workspace credential；可执行代码不包含真实 Qwen endpoint 或 outbound WebSocket client。
- 不创建 `.env`；`.gitignore` 覆盖 `diagnostics/`、`traces/`、`replays/local/`、`audio/raw/`、`.env`、`.env.*`。
- Spike 与测试目录没有 raw audio、trace 或 local replay artifact。
- Fake text/PCM 全部 synthetic；PCM 只在有界内存结构中暂存。
- `src/voice_agent` 不 import experiment；experiment 复用现有 contract/runtime，不新增 canonical event name。
- `safe_error` 对 credential-like、URL、path 与自由文本错误 fail closed；timeline 使用 allowlist。

## 当前不能宣称通过

- ADR-001：真实 semantic directedness/semantic-close、真实 pre-ASR rejection、目标 Duplex 质量。
- ADR-003：playback-reference AEC、echo discrimination、真实 provider/Talker 物理 stop、真实设备 truncate SLO。
- ADR-017：真实 Fast Interaction 模型质量、safe token-stream gate-before-leak、直接 provider-native streaming audio。
- 完整 canonical session-end replay：accepted ADR 文本中的 `SESSION_ENDED` 尚未出现在当前 event registry，本 Spike 没有擅自新增。
- 真实 Qwen capability、latency、cancel、delete/rebuild、privacy/auth、生产稳定性。

## Slice 2 handoff

下一线程只允许添加真实 Qwen **shadow routing**：真实投影只能作为非权威证据记录，不能改变 Router/Gate 或用户可见输出。开始前需要验证 provider item/response delete 或 context rebuild、cancel/late-event 语义、三种逻辑投影 capability、metadata-only redaction；直接 Qwen 音频仍须后续 ADR 接受后才可播放。
