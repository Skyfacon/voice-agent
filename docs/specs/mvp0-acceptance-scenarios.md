# MVP-0 验收场景

Source of truth: frozen ADR Baseline v0.4。本文件承载 P1-B-005，是从 ADR baseline 派生的实现规格。

MVP-0 目标是证明 event-driven live loop skeleton、module boundaries、interrupt/truncate、trace/replay 和 mock capability labeling。

MVP-0 明确排除：

- real ASR requirement
- real TTS requirement
- real Qwen3-Omni requirement
- real GLM requirement
- real external tool
- real side-effect tool
- booking / payment / deletion
- full assistant-directedness
- full semantic_close
- pause / resume TTS

## Scenario MVP0-TEXT-INGRESS-001

| 字段 | 规格 |
| --- | --- |
| `scenario_id` | `MVP0-TEXT-INGRESS-001` |
| 目标 | 验证文本输入先进入 Access Layer 和 Interaction Controller，再进入 Router。 |
| 非目标 | 不涉及 Duplex、不创建 synthetic audio span、不要求真实模型、不涉及 SlowTask/tool。 |
| 初始状态 | Session started；mock ASR/Thinker/TTS capability snapshot recorded；`InteractionState.turn_phase=IDLE`；`playback_phase=NOT_PLAYING`；无 active SlowTask。 |
| input_events | `SESSION_STARTED`; `ADAPTER_CAPABILITY_SNAPSHOT_RECORDED`; `TEXT_INPUT_RECEIVED(input_modality=text, text_span_id=TXT1, audio_span_id=null, directedness=ASSUMED_DIRECTED, semantic_close=ASSUMED_CLOSED)`。 |
| expected_output_events | `TURN_OPENED`; `TURN_INGRESS_ACCEPTED`; `TURN_INGRESS_COMMITTED`; `MOCK_THINKER_FRAME_EMITTED(output_mode=mock)`; `ROUTER_DECISION_EMITTED`; 若 demo loop 产生回复，可有 mock playback events。 |
| expected_state_changes | `current_text_span_id=TXT1`; `current_audio_span_id=null`; `directedness=ASSUMED_DIRECTED`; `semantic_close=ASSUMED_CLOSED`; `last_ingress_outcome=COMMITTED`; `turn_phase=TURN_COMMITTED`。 |
| trace 要求 | envelope fields valid；interaction events caused by `TEXT_INPUT_RECEIVED`；text 使用 redacted text 或 `text_ref`。 |
| replay_assertions | deterministic replay 重建相同 `InteractionState`；Router 不得早于 `TURN_INGRESS_COMMITTED`；text 不创建 audio reducer state。 |
| privacy_assertions | fixture 使用 synthetic/redacted text；无 raw audio；无 secrets。 |
| pass/fail | 通过条件是文本完整经过 Interaction Controller；若 Access Layer 直接路由到 Router 或 ASR/Thinker before commit，则失败。 |

## Scenario MVP0-AUDIO-INGRESS-001

| 字段 | 规格 |
| --- | --- |
| `scenario_id` | `MVP0-AUDIO-INGRESS-001` |
| 目标 | 验证 audio span、Duplex speech detection、Interaction commit、mock ASR/Thinker 的顺序。 |
| 非目标 | 不要求 real ASR / Thinker / semantic_close / assistant-directedness / raw audio fixture / SlowTask。 |
| 初始状态 | Session started；mock adapter snapshot recorded；`InteractionState.turn_phase=IDLE`；无 active playback。 |
| input_events | `AUDIO_SPAN_STARTED(A1)`; `SPEECH_START_DETECTED(A1)`; `AUDIO_SPAN_ENDED(A1)`; `SPEECH_END_DETECTED(A1)`。 |
| expected_output_events | `TURN_OPENED`; `TURN_INGRESS_ACCEPTED`; `TURN_INGRESS_COMMITTED`; `MOCK_ASR_FRAME_EMITTED(output_mode=mock)`; `MOCK_THINKER_FRAME_EMITTED(output_mode=mock)`; `ROUTER_DECISION_EMITTED`。 |
| expected_state_changes | speech start 后 `turn_phase=COLLECTING_INPUT`；最终 `turn_phase=TURN_COMMITTED`；`current_audio_span_id=A1`; `last_ingress_outcome=COMMITTED`。 |
| trace 要求 | audio span events 包含 offsets 且无 raw audio；mock output mode visible；causal chain 完整。 |
| replay_assertions | replay 重建 `InteractionState`；`TURN_INGRESS_COMMITTED` 前不得有 ASR/Thinker frame。 |
| privacy_assertions | shareable fixture 不包含 raw audio，只包含 audio metadata。 |
| pass/fail | mock ASR/Thinker 只在 committed audio turn 后产生；若 audio 直接进入 ASR/Thinker 或 replay 需要 raw audio，则失败。 |

## Scenario MVP0-BARGE-IN-TRUNCATE-001

| 字段 | 规格 |
| --- | --- |
| `scenario_id` | `MVP0-BARGE-IN-TRUNCATE-001` |
| 目标 | 验证 truncate-only barge-in causal chain 和 distinct playback offsets。 |
| 非目标 | 不支持 pause/resume、semantic-clause resume、multi-track recovery、real TTS model cancellation guarantee。 |
| 初始状态 | mock TTS/Talker 支持 playback progress and truncate；`PlaybackState=PLAYING` for `playback_span_id=P1`。 |
| input_events | `PLAYBACK_SPAN_STARTED(P1)`; `PLAYBACK_PROGRESS(P1, 900ms)`; `PLAYBACK_COMMITTED(P1, 850ms)`; `AUDIO_SPAN_STARTED(A2)`; `SPEECH_START_DETECTED(A2)`; `BARGE_IN_CANDIDATE(A2, P1, 910ms, echo_likelihood=low, vad_confidence=high, barge_in_confidence=high)`。 |
| expected_output_events | `INTERRUPT_CANDIDATE`; `TTS_TRUNCATE_REQUESTED`; `TTS_TRUNCATED`; 如果用户仍在说话，可继续 input collection 并后续 commit。 |
| expected_state_changes | InteractionState 短暂 `turn_phase=INTERRUPTING`；PlaybackState 从 `TRUNCATE_REQUESTED` 到 `TRUNCATED`。 |
| trace 要求 | candidate-time offset、request cutoff offset、actual stop offset 是独立字段；causal links 完整。 |
| replay_assertions | replay 重建 candidate -> interrupt -> request -> truncated；latency 可计算且 passing fixture <=250ms；`PLAYBACK_COMMITTED` 不是 semantic acknowledgement。 |
| privacy_assertions | 无 raw mic audio 或 playback audio；echo/barge confidence 只是 metadata。 |
| pass/fail | 有匹配 `playback_span_id` 的 truncate request 和 Talker confirmation；缺 playback reference、未 journal truncate、需要 pause/resume 均失败。 |

## Scenario MVP0-MOCK-ADAPTER-CAPABILITY-001

| 字段 | 规格 |
| --- | --- |
| `scenario_id` | `MVP0-MOCK-ADAPTER-CAPABILITY-001` |
| 目标 | 验证所有 MVP-0 mock adapters 声明 capability matrices，且 output 标记 mock。 |
| 非目标 | 不要求 real provider health、real endpoint、unsupported mocked capabilities 的 target validation。 |
| 初始状态 | Empty session before startup。 |
| input_events | `SESSION_STARTED`; adapter registry startup probe/config load。 |
| expected_output_events | `ADAPTER_CAPABILITY_SNAPSHOT_RECORDED`; 后续 scenario 中 `MOCK_ASR_FRAME_EMITTED(output_mode=mock)` 和 `MOCK_THINKER_FRAME_EMITTED(output_mode=mock)`。 |
| expected_state_changes | `AdapterHealthState` 存储 capability snapshot refs、deployment modes、output modes、missing/unsupported capabilities。 |
| trace 要求 | matrix 包含 required capability booleans 和 mock markers；无 provider credentials。 |
| replay_assertions | replay 从 snapshot 重建 `AdapterHealthState`，不 probe adapters；mock 与 real/fallback/degraded 可区分。 |
| privacy_assertions | endpoint/config refs 不含 API key、token、cookie、credential、authorization header、session secret。 |
| pass/fail | startup snapshot 存在且所有 mock outputs 标记 mock；mock 冒充 real 或 unsupported capability 静默使用则失败。 |

## Scenario MVP0-LOCAL-TRACE-SAFETY-001

| 字段 | 规格 |
| --- | --- |
| `scenario_id` | `MVP0-LOCAL-TRACE-SAFETY-001` |
| 目标 | 验证 MVP-0 local trace defaults 和 shareable fixture boundary。 |
| 非目标 | 不定义 production privacy policy，不导出 raw audio，不使用真实 webSearch fixture。 |
| 初始状态 | `local_debug_trace_enabled=true`; `raw_audio_enabled=false`; `credential_trace_policy=never`。 |
| input_events | representative text/audio ingress + trace write；可选 synthetic secret-like payload attempt。 |
| expected_output_events | normal journal events；必要时 `TRACE_WRITE_DEGRADED`, `TRACE_SECRET_REDACTION_APPLIED`, `TRACE_WRITE_BLOCKED_SECRET_DETECTED`; replay emits `REPLAY_STARTED` and `REPLAY_COMPLETED`。 |
| expected_state_changes | `TracePrivacyState` 记录 raw audio disabled、无 secrets stored、redaction/block counters、replay status。 |
| trace 要求 | local debug trace 可含 event journal/mock outputs；shareable fixture 只含 synthetic/redacted/minimal metadata and refs。 |
| replay_assertions | deterministic replay 无 raw audio 也可运行；state digest 排除 raw audio/text/secret/tool credential。 |
| privacy_assertions | shareable/GitHub fixture 不含 raw audio、raw trace、secrets、unredacted real input、large raw web content。 |
| pass/fail | local trace 对 replay 有用且 raw audio 默认关闭、secrets redacted/blocked；若 deterministic replay 依赖 raw audio 或 fixture 泄露 secrets，则失败。 |

## MVP-0 Completion Summary

MVP-0 仅在以下场景全部通过时 accepted：

- Text ingress through Interaction Controller。
- Audio ingress through Duplex and Interaction Controller。
- Truncate-only barge-in causal replay。
- Mock adapter capability snapshot and output mode labeling。
- Local trace safety and deterministic replay without raw audio。

所有 SLO measurement 必须标注 mock / degraded / real。
