# TTS Run: DashScope / Bailian CosyVoice

## Status

executed_metadata_only

## Date

2026-05-11

## Contract Snapshot

- `main@61e6afc`
- MVP-0 closeout reference: `22ddbf4 fix: harden mvp0 trace and replay safety`
- This report is research evidence only. It is not runtime integration and does not change adapter, event, replay, or ADR contracts.

## Question

Can DashScope / Bailian TTS synthesize basic speech, stream audio chunks quickly enough for Talker-style playback metadata, expose timing/alignment evidence, and map failures or client close behavior to MVP-0 adapter-shaped metadata without storing raw audio?

## Provider and Model

- Provider: DashScope / Bailian
- Model observed: `cosyvoice-v3-flash`
- Voice observed: `longanyang`
- Endpoint surface observed: WebSocket inference
- Endpoint ref: `wss://dashscope.aliyuncs.com/api-ws/v1/inference`
- Deployment mode: `remote_api`
- Output mode for successful probe observations: `real`

## Official Sources Checked

- DashScope CosyVoice WebSocket API: [CosyVoice WebSocket API](https://help.aliyun.com/zh/model-studio/developer-reference/cosyvoice-websocket-api)
- DashScope error codes and request behavior: [Error code](https://help.aliyun.com/zh/model-studio/error-code)

Run-day notes from official sources:

- CosyVoice speech synthesis uses a WebSocket inference endpoint.
- The observed protocol uses `run-task`, `continue-task`, and `finish-task` messages for `SpeechSynthesizer`.
- Streaming audio is delivered as binary WebSocket frames with JSON task and sentence events.
- The API supports voice, rate, pitch, and instruction-style controls on the observed model surface.
- Word timestamp output can be requested through synthesis parameters and was observed in sentence events.

## Environment and Secret Handling

- `DASHSCOPE_API_KEY`: present
- The key was sourced from `~/.voice-agent-local/model-spike.env` in the same shell invocation as each API call.
- No credential-bearing request metadata was printed or written.
- Raw WebSocket payloads and raw audio chunks were not stored.
- Probe output was restricted to event counts, audio byte counts, latency buckets, and failure categories.

## Synthetic Inputs

- `short_ack`: short acknowledgement text.
- `spoken_plan_short`: one short SpokenPlan-like sentence.
- `spoken_plan_long`: multi-sentence SpokenPlan-like text.
- `style_or_voice_control`: voice/style/speed control metadata probe.
- `client_close_cancellation_probe`: client-side close after initial audio chunk.

## Request Shape

Observed request class:

```json
{
  "header": {
    "action": "run-task",
    "task_id": "synthetic-runtime-id",
    "streaming": "duplex"
  },
  "payload": {
    "task_group": "audio",
    "task": "tts",
    "function": "SpeechSynthesizer",
    "model": "cosyvoice-v3-flash",
    "parameters": {
      "text_type": "PlainText",
      "voice": "longanyang",
      "format": "mp3",
      "sample_rate": 22050,
      "volume": 50,
      "rate": 1,
      "pitch": 1,
      "word_timestamp_enabled": true
    },
    "input": {}
  }
}
```

The client then sent `continue-task` with synthetic text and `finish-task` for normal cases. Header values were never logged.

## Observed Outputs

No raw audio or raw WebSocket payload was stored. The observed summaries were:

| case | task finished | binary chunks | audio bytes | first audio | total | word timestamps | notes |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| `short_ack` | true | 15 | 36,453 | 556ms | 1,103ms | present | basic synthesis worked |
| `spoken_plan_short` | true | 23 | 55,679 | 493ms | 1,728ms | present | short SpokenPlan-like synthesis worked |
| `spoken_plan_long` | true | 61 | 148,466 | 705ms | 5,778ms | present | longer synthesis worked |
| `style_or_voice_control` | true | 17 | 43,976 | 553ms | 1,326ms | present | rate/pitch/instruction request accepted |
| `client_close_cancellation_probe` | false | 3 | 6,778 | 663ms | 679ms | present before close | client closed early; provider cancellation not confirmed |

Initial attempt with Node built-in WebSocket failed before task start because the client did not complete a useful connection. A manual WebSocket handshake using Node standard libraries confirmed HTTP 101, and the manual frame client succeeded. This is a probe harness detail, not a provider capability failure.

## Capability Matrix Observation

| field | observation |
| --- | --- |
| `adapter_type` | `tts_talker` |
| `provider` | `dashscope` |
| `model_name` | `cosyvoice-v3-flash` |
| `deployment_mode` | `remote_api` |
| `endpoint` | `dashscope-websocket-inference` |
| `health_status` | `healthy_for_observed_tts_probe` |
| `capability_version` | `research_observation_v1` |
| `latency_class` | `first_audio_about_0.5_to_0.7s_for_short_synthetic_inputs` |
| `error_model` | `websocket_error_or_task_failed_or_client_close_or_timeout` |
| `timeout_policy` | client timeout / close must be adapter-owned metadata |
| `retry_policy` | retry not exercised; reconnect/retry should be adapter-owned and bounded |
| `output_mode` | `real` for successful audio chunks; `degraded` for client-close cancellation observation |
| `supports_streaming_input` | real for streamed text submission over WebSocket |
| `supports_streaming_output` | real, observed binary audio chunks |
| `supports_audio_input` | unsupported for this TTS role |
| `supports_audio_output` | real, observed |
| `supports_audio_timestamps` | real/degraded; word timestamp events were present, but playback offset must still be owned by Talker |
| `supports_structured_json` | real for protocol metadata events, not a SlowTask JSON contract |
| `supports_tool_calling` | unsupported / not applicable |
| `supports_cancellation` | degraded / unknown; client close observed, provider-confirmed cancellation not observed |
| `supports_emotion` | degraded/real-by-parameter for instruction-style control; not quality-evaluated |
| `supports_audio_caption` | unsupported |
| `supports_tts` | real, observed |
| `supports_tts_truncate` | unsupported at model layer; playback controller must own truncate |
| `supports_tts_pause_resume` | unsupported / not tested; MVP non-goal |
| `supports_semantic_close` | unsupported / not applicable |
| `supports_assistant_directedness` | unsupported / not applicable |
| `max_audio_seconds` | null |
| `max_context_tokens` | null |
| `max_output_tokens` | null |
| `expected_first_token_latency_ms` | null |
| `expected_first_audio_latency_ms` | observed about 493ms to 705ms |

## Latency Observation

For short to medium synthetic text, first audio arrived in about 0.5s to 0.7s. Full synthesis time scaled with text length, from about 1.1s for the short acknowledgement to about 5.8s for the longer SpokenPlan-like text.

This is viable for a Talker/TTS adapter probe, but the development target for barge-in must still be validated by playback controller behavior rather than model request completion.

## Streaming Observation

Streaming output was observed as binary WebSocket chunks. Sentence-level JSON events were also observed. The run confirms chunked output is available for a Talker pipeline to consume, but it does not by itself validate frontend playback scheduling or `PLAYBACK_PROGRESS` cadence.

## Timestamp / Alignment Observation

`word_timestamp_enabled` yielded word timestamp events in all successful and early-close cases. This is useful alignment evidence, but ADR-003 still requires Talker/playback to report actual `playback_span_id`, `playback_offset_ms`, and `actual_stop_offset_ms`.

## Timeout / Retry / Cancellation Observation

- Client-side close after initial audio chunks was observed.
- Provider-confirmed cancellation was not observed.
- Model request cancellation must not be recorded as `TTS_TRUNCATED`.
- Adapter integration should record client close/timeout as degraded request metadata, and any late or partial output must be handled by Talker/playback state.

## Trace and Privacy Review

- No raw audio file was committed.
- No raw WebSocket payload or provider response was stored.
- No raw trace or replay cache was created.
- No real user input was used.
- `raw_audio_committed: false` for all cases.

## Degradation Mapping

| capability or failure | mapping |
| --- | --- |
| Client WebSocket error before task start | `ADAPTER_REQUEST_FAILED` with endpoint/client category |
| TTS task failure | `ADAPTER_REQUEST_FAILED` or `ADAPTER_OUTPUT_DEGRADED` depending on retryability |
| Client close / timeout | degraded cancellation; never `TTS_TRUNCATED` |
| No provider-confirmed truncate | `supports_tts_truncate=unsupported` at model layer; Talker playback must own truncate |
| Word timestamps unavailable in future run | degrade alignment metadata; keep playback offsets from Talker |

## Fit to MVP-0 Contract

Fit is good for future TTS/Talker adapter profile hardening:

- Produces real audio chunks suitable for a `tts_stream_ref`.
- Can map to `PLAYBACK_SPAN_STARTED` and `PLAYBACK_PROGRESS` only through Talker/playback, not directly from the model.
- Provides alignment evidence, but not authoritative playback delivery state.
- Does not need raw audio in replay-safe reports.
- Does not satisfy ADR-003 truncate on its own.

## Recommendation

Keep DashScope / Bailian CosyVoice on the TTS shortlist. Treat basic synthesis, streaming audio output, and timestamp metadata as observed real capabilities. Treat cancellation and TTS truncate as degraded/unsupported at the model layer until a playback controller proves actual stop offsets.
