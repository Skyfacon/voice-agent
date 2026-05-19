# ASR Qwen-ASR Capability Profile Draft

## Status

draft_research_profile_metadata_only

This is a research capability profile draft. It is not runtime integration, not a business adapter implementation, and not approval to modify MVP runtime behavior.

## Date

2026-05-12

## Contract Snapshot

- Default contract snapshot: `main@61e6afc`
- MVP-0 closeout reference: `22ddbf4 fix: harden mvp0 trace and replay safety`
- Capability contract reference: ADR-011 and `docs/specs/model-adapter-capabilities.md`
- ASR / Thinker evidence boundary reference: ADR-008
- SlowTask lifecycle and confirmation reference: ADR-016
- Event and replay boundary references: `docs/specs/event-registry.md` and `docs/specs/replay-spec.md`

## Scope

This profile summarizes the already executed DashScope / Bailian Qwen-ASR probe as adapter-shaped research evidence.

In scope:

- Qwen-ASR as an ASR / text projection evidence provider candidate.
- Final transcript-like output, response streaming output, audio input, and timestamp/alignment metadata observed in the metadata-only run report.
- Mapping to ADR-011 capability matrix fields.
- Mapping to ADR-008 ASR / Thinker evidence fusion boundaries.
- Replay-safe metadata and privacy boundaries.
- Gaps that must be closed before MVP-3 integration consideration.

Out of scope:

- No changes to `src/voice_agent/`, `tests/`, `docs/adr/`, or `docs/specs/`.
- No main runtime wiring.
- No real business adapter.
- No live provider call in this profile step.
- No committed audio recordings, provider response bodies, traces, replay caches, real user input, request headers, or secret values.

Qwen-ASR is an ASR / text projection evidence provider. It is not the turn ingress owner, not the Router, not SlowTask, and not the semantic truth owner.

## Source Evidence

Primary evidence:

- `docs/research/spikes/asr-dashscope-bailian-run-2026-05-11.md`

Supporting coordination and contract documents:

- `AGENTS.md`
- `stage_b_adr_register.md`
- `docs/research/model-spike-phase-summary-2026-05-11.md`
- `docs/research/model-spike-execution-plan.md`
- `docs/research/model-spike-integration-ledger.md`
- `docs/research/model-spike-plan.md`
- `docs/research/model-selection.md`
- `docs/specs/model-adapter-capabilities.md`
- `docs/specs/event-registry.md`
- `docs/specs/replay-spec.md`
- `docs/adr/ADR-008 ASR Thinker Evidence Fusion and SlowTask-led Conflict Resolution.md`
- `docs/adr/ADR-011 Model Adapter Capability Contract.md`
- `docs/adr/ADR-016 SlowTask Lifecycle and Confirmation State Contract.md`

Evidence limits:

- The primary run report is metadata-only.
- It records latency buckets, transcript lengths, annotation presence, stream chunk counts, and timestamp structure presence.
- It does not store audio recordings, full transcripts, provider response bodies, or local replay caches.
- It does not prove true realtime microphone streaming input, provider-confirmed cancellation, confidence quality, or semantic interpretation quality.

## Candidate Identity

| field | draft value | label | notes |
| --- | --- | --- | --- |
| `adapter_id` | `draft_asr_dashscope_qwen_asr_2026_05_12` | not_applicable | Draft profile id only; not a runtime adapter id. |
| `adapter_type` | `asr` | observed_real | Role matches the executed ASR probe. |
| `provider` | DashScope / Bailian | observed_real | Provider used in the executed run. |
| `model_name` | `qwen3-asr-flash`; `qwen3-asr-flash-filetrans` | observed_real | Chat surface used `qwen3-asr-flash`; async timestamp probe used `qwen3-asr-flash-filetrans`. Recheck current aliases before hardening. |
| `deployment_mode` | `remote_api` | observed_real | Observed through DashScope remote API surfaces. |
| `endpoint` | `dashscope-compatible-chat-completions`; `dashscope-audio-asr-transcription`; `dashscope-task-polling` | observed_real | Endpoint refs only; no secret-bearing request data. |
| `output_mode` | `real` for successful transcript/timestamp observations; `degraded` for timeout and silence risk | observed_real / observed_degraded | Runtime use would still need adapter event recording. |

## Capability Matrix Draft

Labels used here: `observed_real`, `observed_degraded`, `unsupported`, `unknown`, `not_applicable`, `docs_only_unobserved`.

| ADR-011 field | draft label | draft value / behavior | evidence and notes |
| --- | --- | --- | --- |
| `adapter_type` | observed_real | `asr` | Executed as an ASR probe. |
| `provider` | observed_real | `dashscope` / Bailian | Run report executed against DashScope / Bailian. |
| `model_name` | observed_real | `qwen3-asr-flash`; `qwen3-asr-flash-filetrans` | Observed on 2026-05-11; re-pin current aliases before hardening. |
| `deployment_mode` | observed_real | `remote_api` | Remote API surfaces observed. |
| `endpoint` | observed_real | compatible chat completions, audio transcription, async task polling endpoint refs | Endpoint refs only, without secret-bearing values. |
| `health_status` | observed_real | `healthy_for_observed_asr_probe` | Successful transcript and timestamp probes returned usable metadata. |
| `capability_version` | not_applicable | `research_observation_v1` | Research profile version, not a runtime capability schema. |
| `latency_class` | observed_real | nonstream short audio about 0.4s to 0.5s; streaming first delta about 1.3s | Run-specific bucket, not a general SLO conclusion. |
| `error_model` | observed_degraded | provider failure, client timeout, unexpected transcript for non-speech, validation/normalization failure | Silence/non-speech produced a non-empty transcript-like result, which is quality risk evidence. |
| `timeout_policy` | observed_degraded | adapter-owned timeout metadata; no state advance | Client timeout observed; provider cancellation was not confirmed. |
| `retry_policy` | unknown | bounded adapter retry needed; not exercised | Future retry must be replay-visible and stale-friendly. |
| `output_mode` | observed_real / observed_degraded | `real` for successful ASR evidence; `degraded` for timeout and silence risk | Output mode is evidence labeling only, not runtime integration. |
| `supports_streaming_input` | observed_degraded | Data URL and file URL inputs were observed; true realtime mic streaming input remains unknown | Do not expand this into a realtime microphone streaming conclusion. |
| `supports_streaming_output` | observed_real | response stream deltas observed | `short_command_streaming` produced 4 delta chunks, final length 7, first delta about 1,306ms. |
| `supports_audio_input` | observed_real | true for synthetic/local audio Data URL and official public sample URL | Synthetic/local audio input succeeded; raw audio is not needed for replay-safe reporting. |
| `supports_audio_output` | not_applicable | false | ASR role does not output audio. |
| `supports_audio_timestamps` | observed_real | filetrans timestamp-like fields and word-like arrays observed; chat annotations present | Alignment evidence only; exact granularity still needs normalization. |
| `supports_structured_json` | not_applicable | false for ASR role-level semantic output | Provider protocol metadata can be structured, but ASR should not be treated as SlowTask structured JSON capability. Adapter normalization is still required. |
| `supports_tool_calling` | unsupported | false | ASR must not propose or execute tools. |
| `supports_cancellation` | observed_degraded | client timeout / stream close category only; provider-confirmed cancellation unknown | Do not claim cancellation success without provider-confirmed evidence. |
| `supports_emotion` | unknown | not evaluated for this Qwen-ASR run | Do not infer emotion support from transcript or annotations. |
| `supports_audio_caption` | unsupported | false / not evaluated for this ASR role | Non-speech summary or captioning is not observed ASR capability here. |
| `supports_tts` | unsupported | false | ASR does not synthesize speech. |
| `supports_tts_truncate` | not_applicable | false | TTS truncate is Talker/playback-owned, not ASR-owned. |
| `supports_tts_pause_resume` | not_applicable | false | Pause/resume is outside this ASR role and MVP non-goal. |
| `supports_semantic_close` | unsupported | false for ASR-owned authority; not directly verified as model evidence | ASR must not decide semantic close. |
| `supports_assistant_directedness` | unsupported | false for ASR-owned authority; not directly verified as model evidence | ASR must not decide assistant-directedness. |
| `max_audio_seconds` | unknown | recheck official limit during profile hardening | Not pinned in this run report. |
| `max_context_tokens` | not_applicable | null | ASR role does not consume text context windows in this profile. |
| `max_output_tokens` | not_applicable | null | Transcript length limits were not pinned as output-token limits. |
| `expected_first_token_latency_ms` | observed_real | about 1,306ms for first streamed transcript delta in the short synthetic case | This is response text delta latency, not LLM reasoning latency. |
| `expected_first_audio_latency_ms` | not_applicable | null | ASR does not output audio. |

## Observed Real Capabilities

- Final transcript / transcript-like output: observed_real. The run observed non-empty transcript-like output for short command, mixed language, clipped start, and silence/non-speech cases.
- Response streaming / partial-like output: observed_real. The chat streaming surface produced response deltas for `short_command_streaming`; this does not prove realtime microphone streaming input.
- Audio input: observed_real. Synthetic/local audio via Data URL and a public sample file URL both produced usable ASR metadata.
- Timestamp / word-like / filetrans metadata: observed_real. Async file transcription returned timestamp-like fields and word-like arrays; chat responses also included annotations.
- Short synthetic non-streaming latency: observed_real. Successful short clips returned in about 0.4s to 0.5s in the run environment.
- Metadata-only privacy posture: observed_real. The run report summarized observations without storing audio recordings or provider response bodies.

Observed run summary:

| case | surface | result | latency / timing | evidence label |
| --- | --- | --- | --- | --- |
| `short_command` | chat non-stream | non-empty transcript-like output, length 7; annotations present | about 0.490s | observed_real |
| `mixed_language` | chat non-stream | non-empty transcript-like output, length 22; annotations present | about 0.488s | observed_real |
| `clipped_start` | chat non-stream | non-empty transcript-like output, length 6; annotations present | about 0.436s | observed_real |
| `short_command_streaming` | chat stream | 4 delta chunks, final length 7; annotations seen | first delta about 1.306s, total about 1.322s | observed_real |
| `filetrans_timestamp_probe` | async filetrans | text field count 9; timestamp-like fields and word-like arrays present | task polling succeeded | observed_real |

## Degraded Capabilities

- `supports_streaming_input`: observed_degraded. The probe used Data URL and file URL inputs successfully, but did not exercise true realtime microphone streaming input.
- `supports_cancellation`: observed_degraded / unknown. A client timeout was observed, but provider-confirmed cancellation was not.
- Silence / non-speech handling: observed_degraded. A 1s silence input returned a short non-empty transcript-like output. This is a false-positive or quality-risk signal, not reliable directed user input.
- Timestamp / alignment use: observed_real for availability, degraded if treated as more than alignment evidence. Exact granularity and normalization are still unproven.
- Confidence quality: unknown / degraded for integration readiness. The run did not establish calibrated confidence, n-best quality, language confidence, or rejection thresholds.
- Timeout handling: observed_degraded. Timeout can become adapter failure metadata, but it must not mutate Interaction, Router, or SlowTask state.

## Unsupported Capabilities

These are unsupported or not applicable for this ASR role:

- `supports_audio_output`
- `supports_structured_json` as SlowTask-ready structured reasoning output
- `supports_tool_calling`
- `supports_audio_caption`
- `supports_tts`
- `supports_tts_truncate`
- `supports_tts_pause_resume`
- `supports_semantic_close` as ASR-owned authority
- `supports_assistant_directedness` as ASR-owned authority

Unsupported means the runtime must not silently rely on Qwen-ASR for these responsibilities. Interaction Controller, Router, Thinker, SlowTask Runtime, Tool Executor, Composer, and Talker/playback keep their existing ownership boundaries.

## Unknown / Needs Recheck

- True realtime microphone streaming input support, input cadence, backpressure behavior, and partial transcript timing.
- Provider-confirmed cancellation semantics.
- Retry behavior under provider errors, rate limits, transient network failures, and async filetrans task failures.
- Official current model aliases, endpoint availability, supported formats, sample rates, file size limits, and maximum audio duration.
- Confidence, n-best, language detection, punctuation, ITN behavior, and rejection thresholds across a real eval set.
- Timestamp granularity, units, alignment quality, and normalization rules for chat annotations versus filetrans word-like structures.
- Behavior on longer clips, low-volume speech, clipped starts, noisy speech, overlapping playback, background speakers, and mixed languages.
- Cheap healthcheck shape for a future adapter.
- docs_only_unobserved: official service claims and limits that were not live-observed in this run must be rechecked before profile hardening.

## Transcript / Text Projection Notes

Qwen-ASR transcript output is text projection evidence. It is not the only semantic truth, and it must not directly advance SlowTask state.

Allowed future mapping:

- Normalize a final transcript-like result into ASR frame evidence with `asr_frame_ref`.
- Preserve source, model, audio span, timing, confidence if available, and output mode.
- Pass ASR evidence alongside Thinker, Duplex, Interaction, UserPatch, LiveContext, and task history evidence.
- Let SlowTask review ambiguity and provenance before resolved arguments or SemanticCommitment.

Forbidden mapping:

- Do not treat transcript text as final user intent.
- Do not let ASR decide `semantic_close`, `assistant_directedness`, confirmation, tool authorization, or task completion.
- Do not let ASR choose ASR-vs-Thinker winners for conflicting fields.
- Do not treat a silence/non-speech non-empty transcript as reliable directed user input.
- Do not promote timestamp or annotation metadata into user intent or semantic commitment.

ADR-008 requires ASR / Thinker differences to remain multi-source evidence for SlowTask-led review. Router may carry uncertainty, but it must not become a field-level conflict arbiter.

## Timestamp / Alignment Notes

Timestamp / word-like / filetrans metadata is observed_real as ASR alignment evidence.

Important boundary:

- Timestamp metadata can support replay-safe references, alignment diagnostics, and eval assertions.
- Timestamp metadata is not semantic truth.
- Timestamp metadata is not user intent.
- Timestamp metadata is not confirmation or task progress.
- Chat annotations and filetrans word-like arrays need adapter normalization before any MVP-3 consideration.

Future adapter profile hardening should define a normalized shape such as segment offsets, optional word offsets, source surface, units, and confidence/availability flags. If timestamps are missing or malformed, the adapter should record degraded timing metadata rather than invent offsets.

## Streaming Input / Output Notes

Streaming output:

- observed_real for response-layer streaming output.
- The run observed 4 streamed delta chunks and a final transcript-like result for a short synthetic command.
- This can support future partial/final ASR evidence events after adapter normalization.

Streaming input:

- observed_degraded / unknown for true realtime microphone streaming input.
- The run proved audio input via Data URL and public file URL, not live microphone chunk ingestion.
- Do not widen the observed streaming output result into a claim that Qwen-ASR supports full-duplex realtime mic input.

Audio input:

- observed_real for synthetic/local audio Data URL input.
- observed_real for async filetrans using an official public sample URL.
- Audio recordings do not need to enter replay-safe reports and must not be committed.

## Silence / Non-Speech Risk

The silence/non-speech probe returned a short non-empty transcript-like output. This must be recorded as degraded behavior and quality risk.

Policy implications:

- Silence/non-speech output should not be treated as reliable directed user input.
- Silence/non-speech output should not independently open, accept, or commit a turn.
- A future adapter should expose a low-confidence or degradation flag when ASR output is non-empty but the upstream Duplex/Interaction evidence indicates silence or non-speech.
- Eval coverage should include silence, tones/noise, background speech, playback-only echo, clipped starts, and short utterances.

## Cancellation / Timeout / Retry Mapping

Observed timeout evidence:

- The client timeout probe returned curl exit `28`, HTTP `000`, and no transcript.
- Provider-confirmed cancellation was not observed.
- Retry was not exercised.

Draft mapping for a future adapter:

| condition | metadata mapping | forbidden interpretation |
| --- | --- | --- |
| Client timeout before usable output | `ADAPTER_REQUEST_FAILED` with timeout metadata and `output_mode=degraded` | Do not mutate turn, Router, or SlowTask state. |
| Provider error or async task failure | `ADAPTER_REQUEST_FAILED`; retryable cases may first record retry metadata | Do not silently replace with mock or guessed transcript. |
| Retryable transient failure | bounded `ADAPTER_REQUEST_RETRYING` with retry count and reason | Do not create duplicate ASR frames without causal binding. |
| Provider output malformed for adapter schema | `ADAPTER_OUTPUT_VALIDATION_FAILED` | Do not pass invalid output downstream. |
| Provider-confirmed cancellation absent | cancellation remains observed_degraded / unknown | Do not claim cancel success. |
| Late output after timeout or plan change | keep original audio/request binding; mark stale or ignored according to owner policy | Do not advance current task state. |

ASR cancellation is adapter request control only. It is not SlowTask cancel, tool cancel, confirmation rejection, or task completion.

## Replay-Safe Metadata Shape

Deterministic replay must not rerun Qwen-ASR. Replay should consume recorded metadata, redacted refs, or synthetic fixtures.

Draft metadata shape:

```json
{
  "profile_id": "draft_asr_dashscope_qwen_asr_2026_05_12",
  "contract_snapshot": "main@61e6afc",
  "adapter_type": "asr",
  "provider": "dashscope",
  "model_name_observed": "qwen3-asr-flash",
  "timestamp_model_name_observed": "qwen3-asr-flash-filetrans",
  "model_name_pin_required": true,
  "deployment_mode": "remote_api",
  "endpoint_refs": [
    "dashscope-compatible-chat-completions",
    "dashscope-audio-asr-transcription",
    "dashscope-task-polling"
  ],
  "output_mode": "real_or_degraded",
  "observations": {
    "final_transcript_like_output": {
      "label": "observed_real",
      "successful_synthetic_cases": 4,
      "stored_transcript": false,
      "stored_transcript_length_only": true
    },
    "response_streaming_output": {
      "label": "observed_real",
      "delta_chunk_count": 4,
      "first_delta_ms": 1306,
      "final_transcript_length": 7
    },
    "audio_input": {
      "label": "observed_real",
      "data_url_input_observed": true,
      "file_url_input_observed": true,
      "true_realtime_microphone_streaming": "unknown"
    },
    "timestamp_alignment": {
      "label": "observed_real",
      "filetrans_timestamp_like_fields_present": true,
      "word_like_arrays_present": true,
      "chat_annotations_present": true,
      "normalized_granularity": "unknown"
    },
    "silence_non_speech": {
      "label": "observed_degraded",
      "non_empty_transcript_like_output": true,
      "reliable_directed_user_input": false
    },
    "cancellation": {
      "label": "observed_degraded",
      "client_timeout_observed": true,
      "provider_confirmed_cancellation": "unknown"
    }
  },
  "replay_policy": {
    "rerun_provider_in_deterministic_replay": false,
    "requires_audio_recording_for_replay": false,
    "use_recorded_metadata_or_synthetic_fixture": true
  }
}
```

A future shareable fixture should use invented ids, synthetic transcript snippets if needed, transcript lengths, timestamp availability flags, latency buckets, and causal event refs. It should not require audio recordings or provider response bodies.

## Trace / Privacy Boundary

This profile preserves the run report's metadata-only boundary:

- No real user recording was used.
- Synthetic local audio was generated under local temporary paths and removed by the run harness.
- No audio recording, provider response body, full transcript, local trace, replay cache, request header, or secret value is needed for this profile.
- Transcript evidence is summarized by length and metadata presence unless a future synthetic fixture explicitly needs a short invented transcript.
- Deterministic replay must consume recorded metadata or synthetic fixture data and must not call Qwen-ASR.
- Re-eval, if later approved, must be explicit opt-in and must label regenerated output as re-eval output, not original runtime fact.

## Fit to MVP-0 / MVP-1 / MVP-2 / MVP-3

MVP-0:

- Fit is promising for future replacement of mock ASR evidence shape.
- Qwen-ASR could map to a future real `ASRFrame` / `asr_frame_ref` style output.
- It must not alter MVP-0 runtime now.
- Replay remains metadata-only and does not rerun the provider.

MVP-1:

- ASR transcript can become one evidence source for UserPatch / SlowTask review.
- It cannot directly advance `plan_version`, resolve arguments, or accept stale evidence.
- Old or late ASR results must keep their original request/audio binding and be handled by owner policy.

MVP-2:

- ASR cannot authorize tools, confirm actions, patch UI state, or drive demo tool execution.
- Any tool-relevant user intent must pass through Interaction, Router, UserPatch, SlowTask review, and Tool Executor authorization.
- Silence/non-speech false positives need eval coverage before they can safely influence confirmation or tool-related flows.

MVP-3:

- Qwen-ASR can remain on the shortlist for real ASR adapter consideration.
- Before integration consideration, it needs profile hardening, eval fixtures, timestamp normalization, cancellation policy proof, and true realtime input evidence.
- MVP-3 may replace selected mock adapters with real adapters only without adding new architecture capability.

## Risks / Gaps

- True realtime microphone streaming input is not proven.
- Silence/non-speech produced a non-empty transcript-like result.
- Provider-confirmed cancellation is not proven.
- Retry behavior is not exercised.
- Confidence, n-best, language detection, punctuation, and rejection thresholds are not validated.
- Timestamp granularity and alignment quality are not normalized.
- Streaming output first delta around 1.3s may be usable as evidence but is not hot-path Duplex ownership.
- ASR transcript quality across natural speech, background noise, overlapping playback, clipped starts, and longer utterances is unknown.
- Current official model aliases, limits, formats, and service behavior must be rechecked before hardening.
- The run does not validate semantic close, assistant-directedness, confirmation, tool authorization, or task completion.

## Recommendation

Keep DashScope / Bailian Qwen-ASR on the ASR shortlist as a promising ASR / text projection evidence provider.

Treat the following as observed real for research profile purposes:

- final transcript / transcript-like output;
- response streaming / partial-like output;
- audio input via synthetic/local Data URL and public sample file URL;
- filetrans timestamp-like and word-like metadata.

Treat the following as degraded or unknown before MVP-3 integration consideration:

- true realtime microphone streaming input;
- silence/non-speech robustness;
- provider-confirmed cancellation;
- retry behavior;
- confidence and quality thresholds;
- exact timestamp normalization.

Do not enter runtime integration from this profile alone.

## Next Evidence Needed

- Spike-local ASR eval harness plan using synthetic clips only, with cases for short command, mixed language, clipped start, silence, non-speech, background noise, playback-only echo, and longer utterances.
- True realtime microphone streaming input probe, if the provider surface supports it, with input cadence and first partial timing recorded.
- Timestamp normalization proposal covering filetrans timestamp-like fields, word-like arrays, chat annotations, units, offset references, and unavailable/degraded states.
- Provider-confirmed cancellation or explicit documentation that cancellation remains unsupported/degraded.
- Bounded retry behavior under timeout, transient provider failure, malformed output, and async task failure.
- Confidence / n-best / language / punctuation evidence, or explicit unsupported mapping if unavailable.
- Replay-safe synthetic ASR fixture proposal that records metadata and causal refs without audio recordings or provider response bodies.
- Current official model alias and service limit recheck before any profile hardening or MVP-3 integration discussion.
