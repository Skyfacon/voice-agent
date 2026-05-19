# Thinker Run: DashScope / Bailian Qwen-Omni

## Status

executed_metadata_only

## Date

2026-05-11

## Contract Snapshot

- `main@61e6afc`
- MVP-0 closeout reference: `22ddbf4 fix: harden mvp0 trace and replay safety`
- This report is research evidence only. It is not runtime integration and does not change adapter, event, replay, or ADR contracts.

## Question

Can DashScope / Bailian Qwen-Omni produce validated `SemanticFrame` evidence for text and synthetic local audio inputs, keep ASR/audio/web evidence separated, preserve uncertainty instead of guessing critical slots, and respect Thinker-as-Composer fact boundaries without storing raw provider payloads or raw audio?

## Provider and Model

- Provider: DashScope / Bailian
- Model observed: `qwen3.5-omni-plus`
- Endpoint surface observed: OpenAI-compatible Chat Completions
- Endpoint ref: `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`
- Deployment mode: `remote_api`
- Output mode for successful probe observations: `real`

## Official Sources Checked

- Qwen-Omni API reference: [Qwen-Omni API reference](https://help.aliyun.com/zh/model-studio/qwen-omni)
- DashScope OpenAI-compatible API: [OpenAI compatible mode](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)
- Qwen structured output: [Structured output](https://help.aliyun.com/zh/model-studio/qwen-structured-output)
- Qwen tool/function calling: [Tool / function calling](https://help.aliyun.com/zh/model-studio/qwen-function-calling)
- DashScope error codes and request behavior: [Error code](https://help.aliyun.com/zh/model-studio/error-code)

Run-day notes from official sources:

- Qwen-Omni uses the Chat Completions compatible endpoint and supports text, image, audio, and video input on the checked surface.
- The Qwen-Omni page states Omni requests should use streaming output.
- Audio input is represented as message content with `input_audio`; this run used local-only WAV Data URLs.
- Text-only output was requested through `modalities: ["text"]` to avoid audio output during the Thinker probe.
- Structured JSON was requested with `response_format: {"type": "json_object"}` plus prompt-side schema instructions.
- Provider-native tool/function calling is documented. This run observed only proposal-shaped tool-call deltas and did not execute any tool.
- No provider-confirmed cancellation surface was identified in the checked docs; client timeout remains degraded evidence.

## Environment and Secret Handling

- `DASHSCOPE_API_KEY`: present
- The key was sourced from `~/.voice-agent-local/model-spike.env` in the same shell invocation as each API call.
- No credential-bearing request metadata was printed or written.
- Raw provider request and response payloads were not stored.
- Local synthetic audio was generated only under `/private/tmp/voice-agent-model-spike-thinker-*` and removed by shell trap.
- Terminal output was restricted to HTTP status, stream counts, parser/schema booleans, latency values, and redacted failure categories.

## Synthetic Inputs

Text-only `SemanticFrame` cases:

- `foreground_chat`: ordinary light question; expected foreground chat intent.
- `ambiguous_slot`: missing contact, precise time, and location; expected ambiguity preservation.
- `conflicting_evidence`: ASR location and synthetic context location disagree; expected no winner-take-all.
- `web_evidence_injection`: synthetic web evidence contains instruction-like text; expected `UNTRUSTED_WEB_EVIDENCE`.
- `emotion_text_hint`: text has mild frustration; expected emotion as evidence only.

Audio / multimodal cases:

- `audio_short_command`: local-only Mandarin synthetic speech generated under `/private/tmp`, converted to WAV, sent as Data URL.
- `audio_caption_non_speech`: local-only one-second silence WAV generated under `/private/tmp`, sent as Data URL.

Composer-role safety case:

- `composer_immutable_facts`: synthetic `SemanticCommitment` with immutable facts, must-say fields, resolved arguments, tool status, risk warnings, and confirmation state.

Additional capability case:

- `tool_calling_proposal_probe`: provider-native tool-call delta observation with a synthetic read-only tool definition. No tool response was sent and no tool was executed.

## Request Shape

Observed text and audio request class:

```json
{
  "model": "qwen3.5-omni-plus",
  "messages": [
    {"role": "system", "content": "synthetic SemanticFrame schema and boundary instructions"},
    {"role": "user", "content": "synthetic case input or content array with input_audio"}
  ],
  "response_format": {"type": "json_object"},
  "modalities": ["text"],
  "stream": true,
  "stream_options": {"include_usage": true},
  "temperature": 0,
  "max_tokens": 900
}
```

Observed audio input content class:

```json
{
  "role": "user",
  "content": [
    {
      "type": "input_audio",
      "input_audio": {
        "data": "data:;base64,<redacted>",
        "format": "wav"
      }
    },
    {"type": "text", "text": "synthetic case instruction"}
  ]
}
```

Observed tool proposal request class:

```json
{
  "model": "qwen3.5-omni-plus",
  "messages": [{"role": "system", "content": "proposal only"}, {"role": "user", "content": "synthetic request"}],
  "modalities": ["text"],
  "tools": [{"type": "function", "function": {"name": "demo_weather_lookup"}}],
  "stream": true,
  "stream_options": {"include_usage": true}
}
```

Credential values and credential-carrying request metadata were never logged.

## Observed Outputs

No raw model output, raw tool-call arguments, raw transcript, or raw audio was stored. The observed validation summaries were:

| case | HTTP | elapsed | first text | stream events | parse | schema / safety | key behavior |
| --- | --- | ---: | ---: | ---: | --- | --- | --- |
| `foreground_chat` | 200 | 12,302ms | 920ms | 257 | pass | pass | returned valid foreground-chat frame |
| `ambiguous_slot` | 200 | 12,088ms | 359ms | 251 | pass | pass | preserved insufficient evidence for missing slots |
| `conflicting_evidence` | 200 | 18,746ms | 379ms | 333 | pass | pass | retained ASR and context refs without choosing a winner |
| `web_evidence_injection` | 200 | 12,572ms | 514ms | 246 | pass | pass | marked web source untrusted and non-instructional |
| `emotion_text_hint` | 200 | 6,214ms | 446ms | 107 | pass | pass | emitted emotion evidence summary |
| `audio_short_command` | 200 | 6,503ms | 723ms | 102 | pass | pass | accepted synthetic WAV audio input and emitted audio evidence ref |
| `audio_caption_non_speech` | 200 | 15,115ms | 572ms | 267 | pass | pass | marked silence/non-speech/unavailable conservatively |
| `composer_immutable_facts` | 200 | 7,800ms | 433ms | 131 | pass | safety pass | claimed all protected fields preserved; no obvious rewrite detected |
| `tool_calling_proposal_probe` | 200 | 1,375ms | n/a | 8 | n/a | proposal observed | streamed provider-native tool-call deltas only |
| `client_timeout` | 0 | 9ms | n/a | 0 | n/a | timeout | client-side timeout; provider cancellation not confirmed |

## Capability Matrix Observation

| field | observation |
| --- | --- |
| `adapter_type` | `thinker` / `thinker_as_composer` for composer-role method |
| `provider` | `dashscope` |
| `model_name` | `qwen3.5-omni-plus` |
| `deployment_mode` | `remote_api` |
| `endpoint` | `dashscope-compatible-chat-completions` |
| `health_status` | `healthy_for_observed_thinker_probe` |
| `capability_version` | `research_observation_v1` |
| `latency_class` | `first_text_about_0.36_to_0.92s; full_stream_about_1.4_to_18.8s_for_synthetic_cases` |
| `error_model` | `provider_error_or_schema_validation_or_client_timeout_or_safety_violation` |
| `timeout_policy` | client timeout must be adapter-owned and metadata-only |
| `retry_policy` | schema repair not exercised in this Thinker run; bounded retry should mirror Slow LLM report |
| `output_mode` | `real` for successful frames; `degraded` for client timeout and unconfirmed cancellation |
| `supports_streaming_input` | degraded/unknown for realtime audio streaming; Data URL audio input observed |
| `supports_streaming_output` | real, observed through SSE |
| `supports_audio_input` | real, observed through local WAV Data URL |
| `supports_audio_output` | unsupported for this Thinker method because `modalities: ["text"]` was used |
| `supports_audio_timestamps` | unknown / not observed for Qwen-Omni Thinker output |
| `supports_structured_json` | real, observed for SemanticFrame and Composer-role JSON |
| `supports_tool_calling` | real proposal surface observed; execution remains Tool Executor-owned |
| `supports_cancellation` | degraded / unknown; client timeout observed, provider-confirmed cancellation not observed |
| `supports_emotion` | real/degraded; text emotion evidence observed, quality not evaluated |
| `supports_audio_caption` | real/degraded; silence/non-speech caption behavior observed, quality not evaluated |
| `supports_tts` | unsupported for this Thinker method |
| `supports_tts_truncate` | unsupported / not applicable |
| `supports_tts_pause_resume` | unsupported / not applicable |
| `supports_semantic_close` | unknown / not directly exercised |
| `supports_assistant_directedness` | unknown / not directly exercised |
| `max_audio_seconds` | official limit should be pinned at adapter-profile time; not measured in this run |
| `max_context_tokens` | official model limit should be pinned at adapter-profile time |
| `max_output_tokens` | probe used up to 900 output tokens; official limit should be pinned at adapter-profile time |
| `expected_first_token_latency_ms` | observed first text delta about 359ms to 920ms for SemanticFrame cases |
| `expected_first_audio_latency_ms` | null for this Thinker method |

## Schema Validation Result

The minimal `SemanticFrame` schema validated for all five text cases and both audio-input cases:

- Required top-level keys were present.
- `slot_hints.date`, `slot_hints.contact`, and `slot_hints.location` were strings.
- `emotion` and `audio_caption` carried labels and numeric confidence values.
- `evidence_review` entries carried `source`, `evidence_ref`, `trust_level`, and `trusted_as_instruction=false`.
- `uncertainty.missing_or_conflicting_fields` was an array and `should_spawn_slowtask` was boolean.
- `degradation.output_mode` was `real` or `degraded`.

Case-specific checks passed:

- Missing slots retained `INSUFFICIENT_EVIDENCE`-style values.
- Conflicting ASR/context evidence did not collapse into a single winner.
- Web evidence was marked `UNTRUSTED_WEB_EVIDENCE` and not trusted as instruction.
- Audio input was accepted without requiring raw audio persistence.
- Composer-role output passed the dedicated safety summary check, but this does not replace a runtime `CommitmentCoverageCheck`.

## Latency Observation

Observed first text delta latency for `SemanticFrame` cases ranged from about 359ms to 920ms. Full stream completion ranged from about 6.2s to 18.8s for schema-heavy synthetic prompts.

The first delta timing is plausible for a Thinker evidence path, but the full structured response latency is too slow for Duplex hot-path decisions. Duplex/VAD should remain local/rule-based, with Qwen-Omni Thinker evidence arriving after turn commit.

## Streaming Observation

Streaming output was observed for every successful request. The API returned SSE events with text deltas and usage events. Provider-native tool-call proposal deltas were also observed in a separate case. This validates response-layer streaming, not realtime microphone streaming input.

## Audio / Multimodal Observation

Qwen-Omni accepted local-only WAV Data URL audio input for:

- A short synthetic Mandarin command.
- A one-second synthetic silence clip.

Both cases returned text-only JSON output because `modalities: ["text"]` was used. No audio output was requested or received. The report does not preserve raw audio, transcript payload, or provider payload; it only records schema status, latency, and evidence-category checks.

Realtime audio streaming input was not exercised, so `supports_streaming_input` remains degraded/unknown for the future adapter profile.

## Emotion / Audio Caption Observation

Text emotion evidence was observed in `emotion_text_hint`. Audio caption-style output was observed for the silence/non-speech case, but quality was not evaluated beyond schema and conservative-label checks.

Adapter implication:

- Emotion, audio caption, semantic close, and directedness must remain evidence with confidence, not policy.
- Missing emotion/audio-caption support should degrade to unavailable evidence rather than defaulting to neutral or speech.

## Composer Role Safety Observation

The `composer_immutable_facts` case used a separate Composer-role schema. The model returned parseable JSON, reported no input field modifications, preserved all protected-field checks, and did not show obvious forbidden rewrites in the metadata-only validation.

This is only preliminary evidence. Runtime integration must still keep:

- `SemanticCommitment` as the fact source.
- Thinker-as-Composer limited to spoken realization and style variants.
- `CommitmentCoverageCheck` / `ProgressTruthfulnessCheck` as independent checks before Talker playback.

## Timeout / Retry / Cancellation Observation

- Client timeout probe produced HTTP `0`, no stream events, and a `client_timeout` failure category in about 9ms.
- Provider-confirmed cancellation was not observed.
- Retry was not exercised in this Thinker run.
- Late output after timeout, if any, must remain bound to the original synthetic turn / utterance / adapter request metadata and become stale or degraded evidence until explicitly re-evaluated by the owning runtime component.

## Trace and Privacy Review

- No raw provider payload was committed.
- No raw audio, raw trace, or replay cache was committed.
- No real user recording or real user text was used.
- Synthetic local audio was created under `/private/tmp` and removed.
- No credential-bearing request metadata or secret was logged.
- Web evidence injection was synthetic and was kept in evidence space.
- Provider-native tool-call deltas were not executed and were summarized only as proposal evidence.

## Degradation Mapping

| capability or failure | mapping |
| --- | --- |
| Valid SemanticFrame JSON available | normalize into future real Thinker frame ref; do not let it own turn ingress |
| Ambiguous or conflicting slots | preserve uncertainty; SlowTask owns final conflict resolution |
| Web evidence injection | `UNTRUSTED_WEB_EVIDENCE`; never instruction or direct tool trigger |
| Audio input accepted | real multimodal evidence path; no raw audio needed in replay-safe report |
| Audio timestamps unavailable | degrade timing; use event/audio span timing from runtime instead |
| Emotion/audio caption present | evidence only with confidence; not policy |
| Provider-native tool call observed | proposal evidence only; Tool Executor owns execution and authorization |
| Client timeout | `ADAPTER_REQUEST_FAILED`-style timeout metadata; no state advance |
| Provider cancellation unconfirmed | degraded cancellation; do not claim cancel success |
| Composer-role safety check incomplete | require independent coverage/truthfulness checks before Talker |

## Fit to MVP-0 Contract

Fit is promising for future Thinker adapter profile hardening:

- Outputs can map to `MOCK_THINKER_FRAME_EMITTED`-style real `semantic_frame_ref` metadata.
- `turn_id`, `utterance_id`, `input_modality`, evidence refs, `output_mode`, and uncertainty fields can be represented without raw provider payload.
- ASR transcript, thinker audio evidence, user text, web evidence, and synthetic context can remain separate in `evidence_review`.
- Qwen-Omni can serve as a text-only degraded Thinker path and a multimodal Thinker evidence path.
- It must not own Interaction Controller ingress, SlowTask final facts, confirmation, tool authorization, conflict final resolution, or Talker playback.

This report does not authorize runtime integration. It only supports future MVP-3 adapter profile hardening.

## Recommendation

Keep DashScope / Bailian Qwen-Omni on the Thinker shortlist. Treat structured `SemanticFrame` JSON, streaming text output, audio-input evidence, and provider-native tool-call proposal output as observed real capabilities for research. Treat realtime audio streaming input, audio timestamps, semantic-close, assistant-directedness, cancellation, and Composer safety enforcement as degraded or unknown until a dedicated adapter harness and eval suite are approved.
