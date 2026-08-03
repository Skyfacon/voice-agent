# Qwen-Audio-Realtime Web Spike

This directory contains an isolated **Qwen Realtime model spike with an interactive browser shell**. It is not a new voice-agent runtime MVP number, is not MVP-7, and is not imported or started by the main runtime.

The spike validates this path:

```text
Browser AudioWorklet microphone
  -> PCM16 / 16 kHz / mono browser WebSocket frames
  -> loopback-only aiohttp gateway
  -> spike-local Qwen Realtime adapter (or fake provider)
  -> normalized transcript/status events
  -> PCM16 / 24 kHz / mono streaming playback
```

It deliberately does **not** integrate the Interaction Controller, Router, SlowTask, Composer, Tool Executor, the canonical Event Journal, or the existing UI. Its metadata-only timeline is ephemeral spike UI state, not a core runtime journal.

## Prerequisites

- Python 3.11 or newer.
- `aiohttp` available in the selected Python environment.
- A browser with AudioWorklet support (current Chrome is the primary manual-evaluation target).
- Headphones for `headset_full_duplex` evaluation.

The repository test entrypoint does not install dependencies. This workstation already has the required packages in `/Users/a123/anaconda3/bin/python`; verify without installing anything:

```bash
/Users/a123/anaconda3/bin/python -c "import aiohttp; print(aiohttp.__version__)"
```

## Run in fake mode

From the repository root:

```bash
/Users/a123/anaconda3/bin/python \
  experiments/qwen_audio_realtime_web/server.py \
  --provider fake \
  --host 127.0.0.1 \
  --port 8765
```

Open <http://127.0.0.1:8765/>. Connect first, then start the microphone. Browser permission is requested only when **Start microphone** is clicked.

The provider field in the page is read-only: the server's `--provider` flag is the authority. A browser query string cannot switch a fake process into real mode or vice versa.

Fake mode is provider-free and produces only synthetic/redacted transcripts and generated sine-wave PCM. It is suitable for protocol, backpressure, streaming playback, interrupt, cleanup, and UI testing.

## Run against Qwen-Audio-Realtime

Use a Beijing-region API key and Workspace ID. Keep credentials in the process environment; do not create a repository `.env` file.

On this workstation, the local secret declarations can be loaded without printing
their values:

```bash
source ~/.voice-agent-secrets/dashscope.env
[[ -n "$DASHSCOPE_API_KEY" && -n "$QWEN_REALTIME_WORKSPACE_ID" ]] \
  && echo "Qwen credentials configured" \
  || echo "Qwen credentials missing"
```

Keep `source` and the server command in the same shell so the child process inherits
the declarations. Do not inspect the secret file with `cat`, and do not paste either
value into browser DevTools.

On a different workstation without that local secret file, declare the values
manually instead:

```bash
export DASHSCOPE_API_KEY='<your Beijing-region API key>'
export QWEN_REALTIME_WORKSPACE_ID='<your Workspace ID>'
# Optional; defaults to longanqian.
export QWEN_REALTIME_VOICE='longanqian'
```

Then start the loopback server from that same shell:

```bash
/Users/a123/anaconda3/bin/python \
  experiments/qwen_audio_realtime_web/server.py \
  --provider real \
  --host 127.0.0.1 \
  --port 8765
```

The spike adapter connects to:

```text
wss://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime?model=qwen-audio-3.0-realtime-plus
```

If the console shows an OpenAI-compatible base URL shaped like
`https://<workspace-id>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`, the
first hostname label is the Workspace ID. Use only that identifier in
`QWEN_REALTIME_WORKSPACE_ID`; the realtime adapter deliberately builds the
different `/api-ws/v1/realtime` WebSocket path. The connection-only smoke on
this workstation verified that derivation without committing the actual value.

The adapter performs a bounded strict handshake: receive `session.created`, send a
minimal `session.update`, then wait for `session.updated` before declaring the
provider ready. The update requests text/audio output, the selected voice, fixed
spike instructions, `tools=[]`, and `turn_detection.type=smart_turn`. The API key
is used only in the upstream WebSocket Authorization header inside
`provider_adapter.py`; it is never returned to the browser or included in safe
metadata.

The page keeps **Start microphone** disabled until the upstream provider has
confirmed `session.updated`. After clicking **Connect**, wait for all of these before
starting capture:

- connection badge: `Connected`;
- provider badge: `real`;
- metadata timeline: `session.created`, followed by `session.updated`.

This gate distinguishes a local browser WebSocket connection from an upstream Qwen
session that is ready to accept audio.

## Conversation modes

- `headset_full_duplex` (default): microphone frames continue while assistant audio is playing. Barge-in evaluation requires headphones. Browser `echoCancellation` remains enabled, but this is **not** playback-reference AEC and does not satisfy ADR-003 target-architecture validation.
- `speaker_safe`: microphone capture can remain active, but frames are not uploaded while an assistant response is playing. This reduces speaker echo and explicitly does not support interruption during playback.

Changing the mode configures spike-local behavior only. The upstream `smart_turn` configuration is fixed before the first audio frame, as required by the provider protocol.

## Unified live conversation

The page projects streaming user and assistant transcripts into one accessible
conversation log. Each visible turn always renders in `User -> Assistant` order;
partial text updates its existing bubble rather than creating another row. Completed,
interrupted, cancelled, and failed replies keep the text that was already visible so
multi-turn and barge-in sessions remain reviewable.

Assistant events are associated by safe `response_ref`, then by
`response_epoch`/`playback_epoch`. Qwen user transcript events currently expose no
stable user turn/item reference through this spike's normalized protocol, so user
association is an explicitly spike-local temporal best effort based on speech
start/stop boundaries. This UI projection is not a canonical turn model or Event
Journal.

The log follows the newest streaming text until the user scrolls away from the
bottom; **Back to latest** restores following. It is bounded to 32 turns, 32,000
total characters, and 6,000 characters per bubble. Transcript text is assigned only
through `textContent`. Disconnect preserves the current log for inspection and marks
an unfinished reply cancelled; the next Connect starts a fresh log.

## Browser-to-gateway protocol

The browser WebSocket is `/ws` on the same loopback origin.

Binary browser frames contain raw little-endian PCM16, 16 kHz, mono audio. The expected cadence is approximately 100 ms (3200 bytes); oversized or malformed frames are rejected. Browser and gateway queues are bounded, and dropped input frames are surfaced in the UI rather than silently accumulated.

Browser JSON control messages are spike-local:

- `client.configure` — select `headset_full_duplex` or `speaker_safe`.
- `client.microphone` — report microphone active/inactive state.
- `client.cancel` — explicitly clear local playback and cancel an active upstream response.
- `client.ping` — loopback liveness probe.

These names are not ADR-002 canonical events.

## Gateway-to-browser protocol

Normalized JSON messages include session state, transcript deltas/finals, playback clear/start state, response completion, drop counters, safe errors, and a metadata-only timeline. Provider headers, raw provider payloads, raw audio, and credentials are never included.

Each output audio WebSocket frame has this binary envelope:

```text
offset  size  value
0       4     ASCII "QAR1"
4       4     playback_epoch, unsigned big-endian integer
8       N     raw little-endian PCM16 / 24 kHz / mono
```

`playback_epoch` is a generation fence:

1. Each assistant response is bound to the current epoch.
2. New user speech or explicit cancellation advances the epoch.
3. The gateway clears its bounded output queue and sends `playback.clear`.
4. The browser clears the AudioWorklet ring buffer immediately.
5. Both sides discard audio associated with an older epoch, including late provider frames already in flight.

The player streams raw PCM directly through an AudioWorklet; it does not wait for `response.done` and does not call `decodeAudioData`.

## Flow control and failure behavior

- The gateway uses explicit asyncio tasks for browser input, provider input/output, and browser output; no thread advances session state.
- Input and output queues are bounded. Input overload drops the oldest audio frame and increments a visible degraded/drop counter.
- The browser player keeps a bounded 60-second (1,440,000 source-sample, about 2.88 MB PCM16) chunk queue. Provider bursts are enqueued in O(1) without copying every sample in the message callback, then converted incrementally by the render quantum. The first frame still plays immediately; there is no whole-response prebuffer.
- Twelve seconds (288,000 source samples) is a soft backlog watermark, not a failure boundary. Crossing it emits metadata-only `output_backlog_high`, marks the page degraded, and keeps the current response intact. Draining below nine seconds rearms the warning. It does not drop PCM, clear playback, advance the epoch, or cancel Qwen.
- Current-epoch playback is chronological: the player never evicts already queued speech to make room for a newer chunk. Only the 60-second hard bound rejects a whole incoming chunk, reports `output_capacity_exceeded`, advances the playback epoch, clears locally, and requests upstream cancellation. This remains a bounded fail-coherent guard instead of allowing unbounded memory or splicing unrelated phonemes together.
- The page distinguishes input backlog drops, gateway output-queue drops, player soft backlog, hard-capacity drops, and player underflow. It displays current / current-epoch peak / soft / hard buffered milliseconds plus cumulative output-drop counts; the timeline retains only bounded numeric metadata. AudioContext state changes are also metadata-only, and response start best-effort resumes a suspended player context.
- Interrupt clears pending output before any new response can play.
- Browser disconnect cancels the session tasks and closes the upstream socket.
- Provider disconnect or timeout fails the current turn safely. The spike never replays buffered microphone audio after reconnect.
- Provider errors are normalized to safe categories/codes. Raw upstream messages and headers are not sent to the page.
- The server CLI accepts only `127.0.0.1` or `localhost`; the WebSocket validates local Host and same-loopback Origin and enforces a maximum frame size.

## Tests

Use the canonical repository entrypoint:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python \
  ./scripts/test tests/experiments -q
```

The fake-provider suite covers the normalized provider protocol, continuous audio forwarding, transcripts, PCM output, playback epochs and late-audio discard, cancellation, disconnects, bounded queues, safe errors, credential serialization, and output-mode labeling. One Node VM harness executes the real player worklet against the observed 39 × 19,200-byte burst profile and checks sample-for-sample FIFO continuity, soft-watermark latch/recovery, queue rotation, hard-cap behavior, underflow classification, epoch clear, and 24/44.1/48 kHz output paths. A second harness executes the real page script against a minimal DOM and verifies multi-turn QA ordering, incremental transcript projection, response/epoch association, barge-in and terminal states, idempotence, bounded history, disconnect/reset behavior, and `textContent`-only rendering. A third page harness verifies that a soft backlog preserves the streaming response, a hard-capacity event still clears/cancels coherently, and a suspended AudioContext resumes at response start. All run through the canonical Python test entrypoint.

Current verification on this workstation:

- spike suite with loopback sockets enabled: `88 passed in 2.62s`, including the executable player-worklet, soft/hard capacity UI, and unified-conversation cases;
- complete repository suite: `1737 passed in 12.77s`;
- post-capacity-fix Chromium fake-page smoke: the page exposed the 12,000 ms soft and 60,000 ms hard bounds; Connect and Disconnect passed, player/Gateway output drops remained zero, and the console had zero errors/warnings;
- unified-conversation Chromium smoke: a synthetic three-cycle `MediaStream` ran through the real capture AudioWorklet, browser WebSocket, gateway, and fake provider. The page rendered three fixed User -> Assistant turns, both output-drop counters stayed zero, Disconnect preserved all three turns, reconnect reset the log, and the console had zero errors/warnings;
- real Qwen connection-only smoke: executed with locally configured credentials;
  the browser showed `Provider=real`, and normalized `session.created` then
  `session.updated` were observed with zero console errors/warnings and zero
  player/Gateway output drops. This post-fix check did not start the microphone;
- real Qwen synthetic-audio turn: executed through the browser capture worklet and
  local gateway. Speech start/stop, user transcript delta/final, assistant
  transcript delta/done, streaming PCM, and `response.done` were all observed;
  dropped input frames remained zero;
- real Qwen synthetic barge-in: old response `status=cancelled`, playback epoch
  `1 -> 2`, local worklet clear acknowledgement `2 ms`, and the following response
  completed. The old two-second player overflowed during this long response;
- real-device microphone/headphone follow-up before the player fix: one interactive
  turn was executed. The page reported first audio at 24 ms and the bounded timeline
  showed a provider burst of at least 10.88 seconds of PCM arriving in about three
  seconds, with at least 8.53 seconds deleted by 28 old-player overflow events. The
  response kept one epoch/ref; the audible symptom was unclear/chopped speech in the
  first part and a clear tail. No transcript text, raw audio, or provider payload was
  retained;
- a later real-device session on port 8766 exposed the old 12-second hard guard:
  280,832 buffered samples plus one 9,600-sample frame would have reached 290,432,
  exceeding 288,000 by only 2,432 samples (about 101 ms). The same response/epoch
  delivered 39 visible audio frames totaling 733,440 bytes (15.28 seconds of PCM)
  in roughly four seconds. Gateway output drops were zero, so this was player burst
  capacity rather than gateway congestion or cross-epoch mixing. No transcript,
  raw audio, credential, or provider payload was retained;
- post-capacity-fix executable player regression: 39 × 19,200-byte (15.6-second)
  simultaneous input is FIFO-complete with zero drop, emits one soft warning, recovers
  and rearms, while the 60-second hard guard remains bounded. A real-device run after
  this latest capacity change and the ten-minute resource run remain `not_executed`.

## Debug the page end to end

1. Load the declarations and run the server in real mode using the commands above.
   Confirm the terminal prints only the loopback URL and safe lifecycle messages;
   never print environment values or upstream headers.
2. Open <http://127.0.0.1:8765/> and open Chrome DevTools (**Console** and
   **Network > WS**). Click **Connect** only.
3. Verify `Connected`, `Provider=real`, `session.created`, and `session.updated`.
   The microphone button should become enabled only after the final event. A local
   `Connected` badge without `session.updated` is not upstream readiness.
4. For a connection-only check, click **Disconnect** now. This sends no microphone
   audio and is the safest credential/endpoint diagnostic.
5. For a real audio turn, choose `headset_full_duplex`, wear headphones, click
   **Start microphone**, grant permission, and speak. Watch for user transcript
   delta/final and assistant transcript delta updating the same QA turn, binary
   `QAR1` audio frames, and `response.done`. The page should stream audio before the
   response completes.
6. Speak during playback to test interruption. `speech_started` must advance the
   playback epoch and clear the player immediately; old-epoch binary frames must be
   discarded. Use `speaker_safe` separately to verify upload pauses during playback
   and the UI does not claim barge-in support.
7. Click **Stop microphone**, then **Disconnect**. Confirm the browser track,
   AudioContexts, and WebSocket close. For errors, use the safe page status/timeline
   and normalized error code; do not capture or commit raw provider frames.

After changing the player worklet, disconnect and hard-reload the page before a
real-device retest so the old AudioWorklet module and AudioContext cannot remain in
the tab. On the next Connect, **播放缓冲（当前 / 本轮峰值 / soft / hard）** must show
`0 / 0 / 12000 / 60000 ms`. During a provider burst, `flow.output_backlog_high` is
now diagnostic only: the assistant bubble should keep streaming, the epoch should
not advance, and no cancel/clear should occur. `flow.output_capacity_exceeded`
should appear only near the 60,000 ms hard bound. If it recurs, retain only the
metadata rows for `playback.buffer`, `flow.output_backlog_high`,
`flow.output_capacity_exceeded`, `player.context_state`, and gateway drop/queue
counters; do not copy transcript text or raw WebSocket payloads.

## Manual evaluation checklist

1. Run fake mode and verify Connect/Disconnect and Start/Stop microphone cleanup.
2. Verify multiple QA turns stay in User -> Assistant order, streaming text updates in place, terminal states preserve partial text, and scrolling away reveals **Back to latest**.
3. Confirm PCM starts playing before the response completes.
4. In headset mode, speak during playback and verify local clear occurs promptly and old audio does not resume.
5. In speaker-safe mode, verify the page states that playback-time interruption is unavailable and microphone upload pauses while responding.
6. With approved credentials, repeat in real mode for at least ten minutes and record observed latencies and memory behavior in the spike report.
7. Search the page, logs, and repository for credential values, raw audio artifacts, and raw provider traces.

## Capability and architecture limits

The adapter capability profile distinguishes `mock`, `real`, `fallback`, and `degraded` output. Real mode implements streaming audio input/output, ASR transcript projection, assistant captions, and response cancellation. Fake mode faithfully exercises the local transport and safety mechanics but is not evidence of provider latency or quality.

This spike cannot claim:

- ADR-001 turn-ingress ownership or Interaction Controller validation;
- ADR-002 canonical Event Journal/replay validation;
- ADR-003 playback-reference AEC, Talker-confirmed `actual_stop_offset_ms`, or target-architecture truncate validation;
- ADR-017 Fast Interaction output or Fast Foreground Gate validation;
- SemanticCommitment, approved SpokenPlan, SlowTask, tool authorization, or external side effects;
- production privacy, authentication, deployment, reconnect continuity, or multi-session support.

Any future main-runtime integration must begin with an ADR proposal that maps provider-native turn detection/cancellation into the existing Duplex, Interaction Controller, Event Journal, Talker truncate, adapter capability, and replay boundaries. The spike itself does not authorize those changes.

See the dated research report at `docs/research/spikes/qwen-audio-realtime-2026-07-15.md` for official-source checks, capability details, test evidence, live-smoke status, and remaining risks.
