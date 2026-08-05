# ADR-003 Barge-in and TTS Truncate Contract

## Status

accepted

## Context

live 语音 Agent 必须支持用户在 Talker 播放时随时打断。MVP 不追求完整 pause/resume，而是先验证 truncate-only barge-in：用户插话后，系统能尽快停止当前 TTS，并确保 event journal 能解释“打断发生在播放到哪里”。

同时，barge-in 不能只靠 mic VAD。全双工场景里，麦克风会收到 Talker 自己的播放声音。如果没有 playback reference，系统可能误把自己的声音识别成用户说话，造成 false barge-in。

## Decision

MVP 采用 truncate-only barge-in contract。事件命名以 ADR-002 canonical MVP-0 event registry 为准。

Talker 必须输出并持续更新：

- `playback_span_id`
- `playback_offset_ms`
- playback started / progress / committed / truncated events

Duplex / Realtime Conversation Gate 在判断 barge-in 时必须接收或保留接口：

- mic input reference
- playback reference
- `echo_likelihood`
- `vad_confidence`
- `barge_in_confidence`

Duplex 可以在 MVP 中 mock AEC，但接口必须保留 playback reference。没有 playback reference 的 barge-in 只能作为 demo mock，不能作为目标架构设计。

当检测到 barge-in 时：

1. Duplex 输出 `BARGE_IN_CANDIDATE`，携带：
   - `playback_span_id`
   - current `playback_offset_ms`
   - `echo_likelihood`
   - `vad_confidence`
   - `barge_in_confidence`

2. Interaction / Turn Controller 基于 InteractionState、assistant_speaking 状态和 Duplex candidate，产生：
   - `INTERRUPT_CANDIDATE`
   - `TTS_TRUNCATE_REQUESTED`

3. `TTS_TRUNCATE_REQUESTED` 必须携带：
   - `playback_span_id`
   - `cutoff_playback_offset_ms`
   - `caused_by_event_id`

`cutoff_playback_offset_ms` uses the Interaction Controller's latest known playback offset at the moment `TTS_TRUNCATE_REQUESTED` is emitted. The original `BARGE_IN_CANDIDATE.playback_offset_ms` remains the candidate-time offset; `TTS_TRUNCATED.actual_stop_offset_ms` is the Talker-confirmed stop offset. Replay / SLO analysis must keep these three offsets distinct.

4. Talker 收到 truncate request 后停止当前 playback span，并输出：
   - `TTS_TRUNCATED`
   - final `playback_offset_ms`

5. Event journal 记录从 barge-in candidate 到 truncate completed 的完整因果链。

MVP 明确不支持：

- pause/resume
- precise resume from semantic clause
- multi-track playback recovery
- model-side TTS cancellation guarantee

这些能力作为目标架构预留。

## Alternatives Considered

1. MVP 只靠 VAD 打断。
   实现最简单，但无法区分用户插话和 TTS echo，只能做 demo，不能作为真实架构基础。

2. MVP 直接实现 pause/resume。
   体验更完整，但需要更复杂的 playback buffer、语义断点、Talker state recovery，不适合作为 MVP-0 范围。

3. 不支持 barge-in，等真实模型集成后再做。
   会错过 live loop 最核心风险，MVP 无法验证全双工边界。

## Consequences

正向结果：

- MVP-0 能验证真实 live loop 的关键闭环。
- interrupt latency 可以被 event journal 量化。
- replay 可以判断 false barge-in 和 truncate 是否发生在正确 playback offset。
- Talker 不需要一开始支持复杂续播。
- Duplex 和 Talker 的接口不会被 demo mock 绑死。

代价：

- Talker 必须暴露 playback progress，而不是只返回 audio blob。
- Duplex 即使 mock AEC，也必须接受 playback reference。
- 用户打断后，旧回复只能截断，不能恢复。
- 已经播放出去的内容必须视为用户可能听到，后续回复要能承接或纠正。

## Impacted Modules

- Duplex / Realtime Conversation Gate
- Interaction / Turn Controller
- Talker
- TTSControlEvent
- Event Journal
- Access Layer
- Replay / Eval
- Development SLO Measurement

## Validation Method

MVP-0 必须验证：

1. Talker 每次播放都有唯一 `playback_span_id`。
2. Talker 周期性输出 `playback_offset_ms`。
3. 用户在 Talker 播放中插话时，Duplex 输出 barge-in candidate。
4. `TTS_TRUNCATE_REQUESTED` 必须包含 `cutoff_playback_offset_ms`。
5. Talker 收到 truncate request 后输出 `TTS_TRUNCATED`。
6. replay 能重建 barge-in 到 truncate 的因果链。
7. barge-in to truncate command latency 目标为 <= 250ms。
8. false barge-in rate 必须能在 replay/eval 中统计。
9. 没有 playback reference 的 barge-in 测试只能标记为 demo mock，不算目标架构验证通过。

## Open Questions

- MVP-0 中 playback progress 上报频率是多少，例如 50ms、100ms、200ms？
- Talker truncate 后是否需要返回“实际停止 offset”，用于修正 `PLAYBACK_COMMITTED`？
- 用户打断后，Composer 是否必须知道上一段 assistant audio 已播到哪个文本/token 位置？
- echo_likelihood 的 MVP mock 默认值如何设定，才能避免误导 eval？

## ADR-018 Accepted Addendum

`ForegroundReleaseTokenV1` binds provider generation, context snapshot, turn,
utterance, response, output item, transcript digest, PCM manifest digest, and
playback epoch. `FULL` requires playback finish/commit. `TRUNCATED` uses actual
stop offset. `NOT_STARTED` deletes the unheard provider item. Undelivered
suffixes never become shared conversational facts.
