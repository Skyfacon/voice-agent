# ASR Run: DashScope / Bailian Qwen-ASR

## Status

executed_metadata_only

## Date

2026-05-11

## Contract Snapshot

- `main@61e6afc`
- MVP-0 closeout reference: `22ddbf4 fix: harden mvp0 trace and replay safety`
- This report is research evidence only. It is not runtime integration and does not change adapter, event, replay, or ADR contracts.

## Question

Can DashScope / Bailian ASR return final transcript evidence, support streaming output, expose timestamp metadata, and map timeout/cancellation behavior to MVP-0 adapter-shaped metadata without storing raw audio or treating transcript as the only semantic truth?

## Provider and Model

- Provider: DashScope / Bailian
- Models observed:
  - `qwen3-asr-flash` through OpenAI-compatible Chat Completions
  - `qwen3-asr-flash-filetrans` through async file transcription
- Endpoint surfaces observed:
  - `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`
  - `https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription`
  - `https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}` for async task polling
- Deployment mode: `remote_api`
- Output mode for successful probe observations: `real`

## Official Sources Checked

- Qwen-ASR API reference: [Qwen-ASR API reference](https://help.aliyun.com/zh/model-studio/qwen-asr-api-reference)
- Recording file recognition: [Recording file recognition](https://help.aliyun.com/zh/model-studio/recording-file-recognition)
- DashScope error codes and request behavior: [Error code](https://help.aliyun.com/zh/model-studio/error-code)

Run-day notes from official sources:

- `qwen3-asr-flash` supports OpenAI-compatible Chat Completions with audio input.
- The compatible surface supports non-streaming and streaming response modes.
- `qwen3-asr-flash-filetrans` supports async file transcription through a task API.
- File transcription results can expose timestamp-like and word-like structures.
- Cancellation was not provider-confirmed in this run.

## Environment and Secret Handling

- `DASHSCOPE_API_KEY`: present
- The key was sourced from `~/.voice-agent-local/model-spike.env` in the same shell invocation as each API call.
- No credential-bearing request metadata was printed or written.
- Local synthetic audio was generated only under `/private/tmp/voice-agent-model-spike-asr-*` and removed by shell trap.
- No raw audio, raw response, raw trace, or replay cache was committed.

## Synthetic Inputs

- `short_command`: locally generated Mandarin TTS clip, converted to mono 16 kHz wav, sent as Data URL.
- `mixed_language`: locally generated Mandarin/English mixed clip, converted to mono 16 kHz wav, sent as Data URL.
- `silence_or_non_speech`: locally generated 1s silence wav, sent as Data URL.
- `clipped_start`: locally generated short command clipped by about 300ms, sent as Data URL.
- `client_timeout`: short command input with intentionally tiny client timeout.
- `short_command_streaming`: short command input with `stream: true`.
- `filetrans_timestamp_probe`: official public sample URL used for async filetrans timestamp structure observation.

## Request Shape

Observed non-streaming request class:

```json
{
  "model": "qwen3-asr-flash",
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "type": "input_audio",
          "input_audio": {
            "data": "data:audio/wav;base64,<redacted>"
          }
        }
      ]
    }
  ],
  "stream": false,
  "asr_options": {
    "enable_itn": false
  }
}
```

Observed streaming request used the same shape with `stream: true`.

Observed filetrans request class:

```json
{
  "model": "qwen3-asr-flash-filetrans",
  "input": {
    "file_url": "official-public-sample-url"
  },
  "parameters": {
    "channel_id": [0],
    "enable_itn": false,
    "enable_words": true
  }
}
```

## Observed Outputs

No raw transcript or raw provider response was stored. The observed summaries were:

| case | surface | HTTP / status | latency | transcript | metadata |
| --- | --- | --- | --- | --- | --- |
| `short_command` | chat non-stream | 200 | 0.490s | non-empty, length 7 | annotations present, audio tokens 36 |
| `mixed_language` | chat non-stream | 200 | 0.488s | non-empty, length 22 | annotations present, audio tokens 78 |
| `silence_or_non_speech` | chat non-stream | 200 | 0.407s | non-empty, length 2 | annotations present; should be treated cautiously |
| `clipped_start` | chat non-stream | 200 | 0.436s | non-empty, length 6 | annotations present, audio tokens 28 |
| `client_timeout` | chat non-stream | curl exit 28 / HTTP 000 | 0.001s | none | provider cancellation not confirmed |
| `short_command_streaming` | chat stream | done | 1.322s total | 4 delta chunks, final length 7 | first delta 1.306s, annotations seen |
| `filetrans_timestamp_probe` | async filetrans | succeeded | polled task | text field count 9 | timestamp-like fields and word-like arrays present |

The silence/non-speech case returning a short non-empty transcript-like output should be treated as quality risk evidence. Runtime integration must not treat ASR transcript as final semantic truth.

## Capability Matrix Observation

| field | observation |
| --- | --- |
| `adapter_type` | `asr` |
| `provider` | `dashscope` |
| `model_name` | `qwen3-asr-flash`; `qwen3-asr-flash-filetrans` for async timestamp probe |
| `deployment_mode` | `remote_api` |
| `endpoint` | `dashscope-compatible-chat-completions`; `dashscope-audio-asr-transcription` |
| `health_status` | `healthy_for_observed_asr_probe` |
| `capability_version` | `research_observation_v1` |
| `latency_class` | `nonstream_short_audio_about_0.4_to_0.5s; streaming_first_delta_about_1.3s` |
| `error_model` | `provider_error_or_client_timeout_or_unexpected_transcript` |
| `timeout_policy` | client timeout must be adapter-owned and metadata-only |
| `retry_policy` | not exercised; retries should be bounded and stale-friendly |
| `output_mode` | `real` for successful transcript outputs; `degraded` for timeout and silence quality concern |
| `supports_streaming_input` | degraded/unknown for true realtime input; Data URL and file URL observed, not microphone streaming |
| `supports_streaming_output` | real, observed through Chat Completions stream |
| `supports_audio_input` | real, observed through Data URL and official sample URL |
| `supports_audio_output` | unsupported / not applicable |
| `supports_audio_timestamps` | real through filetrans timestamp-like and word-like output; chat surface annotations also present |
| `supports_structured_json` | degraded/real for structured protocol metadata; transcript text still needs adapter normalization |
| `supports_tool_calling` | unsupported / not applicable |
| `supports_cancellation` | degraded / unknown; client timeout observed, provider cancellation not confirmed |
| `supports_emotion` | unknown / not evaluated for ASR role |
| `supports_audio_caption` | unsupported / not evaluated |
| `supports_tts` | unsupported / not applicable |
| `supports_tts_truncate` | unsupported / not applicable |
| `supports_tts_pause_resume` | unsupported / not applicable |
| `supports_semantic_close` | unsupported / not ASR-owned |
| `supports_assistant_directedness` | unsupported / not ASR-owned |
| `max_audio_seconds` | unknown in this run; pin official model limits at adapter-profile time |
| `max_context_tokens` | null |
| `max_output_tokens` | null |
| `expected_first_token_latency_ms` | observed first streaming delta about 1,306ms for short synthetic input |
| `expected_first_audio_latency_ms` | null |

## Latency Observation

Short non-streaming synthetic clips returned in about 0.4s to 0.5s. Streaming output produced the first text delta at about 1.3s for the short synthetic input. Async file transcription succeeded through task polling, but this run records only structure presence rather than detailed async latency.

## Streaming Observation

`qwen3-asr-flash` produced streamed Chat Completions deltas for the short command case:

- stream done: true
- delta chunks: 4
- first delta: about 1,306ms
- final transcript length: 7
- annotations seen: true

This validates streaming output at the response layer, not true realtime microphone streaming input.

## Timestamp / Alignment Observation

`qwen3-asr-flash-filetrans` succeeded and returned timestamp-like fields plus word-like arrays in the fetched transcription result. The chat surface also returned annotations. This is enough to mark timestamp support as observed real for filetrans, but adapter integration must normalize the exact timestamp granularity before using it in replay/eval.

## Timeout / Retry / Cancellation Observation

- Client timeout probe produced curl exit `28`, HTTP `000`, and about 0.001s total time.
- Provider-confirmed cancellation was not observed.
- Retry was not exercised.
- Timeout must not mutate current task state. Late outputs, if any, must remain bound to their original audio span / task metadata and be stale-friendly.

## Trace and Privacy Review

- No real user recording was used.
- Synthetic local audio was generated under `/private/tmp` and deleted.
- No raw audio, raw provider response, raw transcript payload, raw trace, or replay cache was committed.
- No credential-bearing request metadata or secret was logged.
- Transcript evidence was summarized by length and metadata presence only.

## Degradation Mapping

| capability or failure | mapping |
| --- | --- |
| ASR final transcript available | normalize into ASR frame evidence; never sole semantic truth |
| Streaming output available | adapter may expose partial/final evidence; still not turn ingress owner |
| Silence returns non-empty transcript-like output | quality degradation / false-positive risk; needs eval guard |
| Filetrans timestamps available | normalize into `asr_frame_ref` metadata; no raw transcript required |
| Client timeout | `ADAPTER_REQUEST_FAILED` with timeout metadata; no state advance |
| Provider cancellation not confirmed | degraded cancellation; do not claim cancel success |

## Fit to MVP-0 Contract

Fit is promising for future ASR adapter profile hardening:

- Can produce final transcript-like text projection.
- Can produce streaming output deltas.
- Can expose timestamp-like and word-like metadata through filetrans.
- Output can map to `MOCK_ASR_FRAME_EMITTED`-style real ASR frame refs in a future adapter.
- Transcript must remain evidence only and cannot bypass Interaction Controller, Router, or Thinker/SlowTask conflict handling.
- Replay-safe reports do not require raw audio or raw provider payload.

## Recommendation

Keep DashScope / Bailian Qwen-ASR on the ASR shortlist. Treat final transcript, streaming output, and filetrans timestamp metadata as observed real capabilities. Treat true realtime microphone streaming input, cancellation, confidence quality, silence handling, and exact timestamp granularity as degraded/unknown until a dedicated ASR harness and eval set are approved.
