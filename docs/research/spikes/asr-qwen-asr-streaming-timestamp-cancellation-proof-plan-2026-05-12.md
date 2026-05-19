# ASR Qwen-ASR Streaming / Timestamp / Cancellation Proof Plan

## Status

planned_research_proof_metadata_only_no_code

This document is a research proof plan. It is not runtime integration, not harness code, not a business adapter, and not approval to modify MVP runtime behavior.

## Date

2026-05-12

## Contract Snapshot

- Default contract snapshot: `main@61e6afc`
- Capability contract reference: ADR-011 and `docs/specs/model-adapter-capabilities.md`
- ASR / Thinker evidence boundary reference: ADR-008
- Event and replay boundary references: `docs/specs/event-registry.md` and `docs/specs/replay-spec.md`
- SlowTask lifecycle and stale evidence reference: ADR-016

## Scope

This plan defines the remaining ASR streaming, timestamp, timeout, retry, cancellation, and late-output proof needed before DashScope / Bailian Qwen-ASR can move closer to MVP-3 consideration.

In scope:

- Qwen-ASR as an ASR / text projection evidence provider candidate.
- Response streaming output proof and the separate true realtime microphone streaming input gap.
- Timestamp / alignment metadata proof for chat annotations and file transcription word-like structures.
- Timeout, retry, client close, provider-confirmed cancellation, and late result metadata.
- Replay-safe metadata-only JSONL shape for a future spike-local proof harness.
- ASR / Interaction / Router / Thinker / SlowTask boundary notes.

Out of scope:

- No changes to `src/voice_agent/`, `tests/`, `docs/adr/`, or `docs/specs/`.
- No main runtime wiring.
- No real business adapter.
- No harness implementation in this step.
- No live provider calls in this step.
- No committed audio recordings, provider request or response bodies, local traces, local replay caches, real user input, request headers, or sensitive access material.
- No claim that Qwen-ASR is ready for MVP-3 integration.

## Source Evidence

Primary evidence:

- `docs/research/spikes/asr-dashscope-bailian-run-2026-05-11.md`
- `docs/research/profiles/asr-qwen-asr-capability-profile-draft-2026-05-12.md`
- `docs/research/spikes/asr-qwen-asr-eval-harness-plan-2026-05-12.md`
- `docs/research/spikes/asr-capability-spike-2026-05-09.md`

Contract evidence:

- `AGENTS.md`
- `docs/specs/model-adapter-capabilities.md`
- `docs/specs/event-registry.md`
- `docs/specs/replay-spec.md`
- `docs/adr/ADR-008 ASR Thinker Evidence Fusion and SlowTask-led Conflict Resolution.md`
- `docs/adr/ADR-011 Model Adapter Capability Contract.md`
- `docs/adr/ADR-016 SlowTask Lifecycle and Confirmation State Contract.md`

Evidence already observed:

- `qwen3-asr-flash` produced final transcript-like output for short synthetic audio, mixed-language audio, clipped-start audio, and silence/non-speech input.
- `qwen3-asr-flash` produced response-layer streaming deltas for `short_command_streaming`.
- `qwen3-asr-flash-filetrans` produced timestamp-like fields and word-like arrays through async file transcription.
- The silence/non-speech probe returned a short non-empty transcript-like output, which is degraded quality evidence.
- A client timeout was observed, but provider-confirmed cancellation was not.

Evidence not yet observed:

- True realtime microphone streaming input.
- Provider-confirmed cancellation.
- Bounded retry behavior under transient provider failure.
- Late result handling after timeout, stream close, or superseded turn.
- Calibrated confidence, n-best alternatives, language confidence, punctuation behavior, and ITN behavior.
- Normalized timestamp units, offset basis, and alignment quality across provider surfaces.

## Candidate Identity

| field | draft value | label | notes |
| --- | --- | --- | --- |
| `proof_plan_id` | `asr_qwen_streaming_timestamp_cancellation_2026_05_12` | not_applicable | Research plan id only. |
| `adapter_type` | `asr` | observed_real | Role matches the executed ASR probe. |
| `provider` | DashScope / Bailian | observed_real | Provider used in prior metadata-only run. |
| `model_name` | `qwen3-asr-flash`; `qwen3-asr-flash-filetrans` | observed_real / needs_recheck | Observed on 2026-05-11; current aliases and limits need recheck before hardening. |
| `deployment_mode` | `remote_api` | observed_real | Observed through remote API surfaces. |
| `endpoint_ref` | `dashscope-compatible-chat-completions`; `dashscope-audio-asr-transcription`; `dashscope-task-polling` | observed_real | Endpoint refs only; no sensitive request data. |
| `output_mode` | `real` for successful observations; `degraded` for timeout and silence risk | observed_real / observed_degraded | Future proof output must label every case. |

Qwen-ASR is an ASR / text projection evidence provider. It is not the turn ingress owner, not the Interaction Controller, not the Router, not the Thinker, not SlowTask, and not the semantic truth owner.

## Proof Goals

The proof should answer:

- Can Qwen-ASR produce reliable metadata for final transcript evidence without storing audio or provider bodies?
- Does response streaming output provide partial/final evidence with useful chunk counts and first-delta timing?
- Does the provider support true realtime microphone streaming input, or should that remain unknown/degraded for MVP-3?
- Can timestamp-like outputs be normalized into explicit units, offset bases, segments, words, and degraded states?
- Can silence, non-speech, playback-only echo, clipped starts, and low-volume inputs be labeled safely?
- Can timeout, retry, client close, provider-confirmed cancellation, and late output be represented without mutating runtime state?
- Can future proof output stay deterministic-replay-safe by using recorded metadata or synthetic fixtures rather than rerunning ASR?

## Non-Goals

- Do not implement a harness in this step.
- Do not call a real provider in this step.
- Do not store or commit audio recordings.
- Do not store or commit provider request or response bodies.
- Do not create or modify runtime adapter code.
- Do not modify `tests/`, replay fixtures, ADRs, or specs.
- Do not evaluate real user recordings.
- Do not decide semantic close, assistant-directedness, confirmation, tool authorization, task completion, resolved arguments, or risk warnings.
- Do not treat transcript text as `SemanticCommitment`.
- Do not compare self-hosted ASR candidates in this proof plan.

## Current Evidence Classification

| capability | current label | evidence | integration caution |
| --- | --- | --- | --- |
| Final transcript-like output | observed_real | Non-stream short, mixed language, clipped start, and silence/non-speech produced transcript-like metadata. | Transcript is evidence only, not user intent or commitment. |
| Response streaming output | observed_real | `short_command_streaming` produced streamed deltas and a final transcript-like result. | This does not prove realtime microphone streaming input. |
| Audio input via Data URL / file URL | observed_real | Synthetic/local audio and public file URL probes succeeded. | This is not live mic chunk ingestion. |
| Timestamp-like metadata | observed_real | File transcription returned timestamp-like and word-like structures; chat annotations were present. | Exact units, offset basis, and alignment quality are unproven. |
| Silence / non-speech handling | observed_degraded | One-second silence produced non-empty transcript-like output. | Must be risk-labeled; not reliable directed user input. |
| Client timeout | observed_degraded | Client timeout returned no transcript. | Provider-confirmed cancellation remains unknown. |
| Provider-confirmed cancellation | unknown | No direct evidence. | Client close or timeout must not be claimed as cancellation success. |
| Retry behavior | unknown | Not exercised. | Needs bounded retry metadata and causal binding. |
| True realtime mic streaming input | unknown / degraded | Not exercised. | Needs separate proof or explicit unsupported/degraded mapping. |

## Synthetic Case Matrix

| case_id | input class | proof target | expected metadata-only output | risk covered |
| --- | --- | --- | --- | --- |
| `short_command_nonstream_baseline` | synthetic short Mandarin command | final transcript, latency, annotations | transcript presence, length, latency bucket, output mode | baseline ASR evidence |
| `mixed_language_nonstream_baseline` | synthetic Mandarin/English phrase | mixed-language transcript behavior | transcript length, language metadata availability | mixed language robustness |
| `clipped_start_probe` | synthetic command with first audio removed | partial word loss, degradation | transcript length, clipped-start flag, quality label | barge-in clipped audio |
| `low_volume_speech_probe` | attenuated synthetic speech | robustness and confidence availability | transcript presence, confidence availability, degradation | low SNR input |
| `longer_utterance_probe` | 10-30s synthetic utterance | duration, latency, timestamp coverage | duration bucket, transcript length, timing coverage | longer input behavior |
| `silence_non_speech_probe` | generated silence | false positive detection | transcript presence, non-speech risk flag | silence false turn risk |
| `tone_non_speech_probe` | generated tone | non-speech rejection or degraded transcript | transcript presence, quality label | acoustic false positive |
| `white_noise_non_speech_probe` | seeded white noise | non-speech rejection or degraded transcript | transcript presence, quality label | noise false positive |
| `background_speech_not_directed_probe` | synthetic background-style speech or metadata substitute | directedness boundary | transcript presence, directedness owner outside ASR | non-directed speech |
| `playback_only_echo_probe` | playback reference plus echo-like capture or metadata substitute | echo false turn risk | echo context flag, transcript presence, degraded ingress suitability | playback echo |
| `user_speech_over_playback_probe` | foreground synthetic speech mixed with playback reference | overlap transcript evidence | overlap flags, transcript length, timing bucket | barge-in-like overlap |
| `streaming_output_delta_probe` | short command with response streaming | delta cadence and first delta | chunk count, first delta ms, final transcript length | partial evidence timing |
| `true_realtime_mic_streaming_input_probe` | approved future live mic chunk path or simulated provider surface | realtime input support | input chunk duration, cadence, first partial timing | realtime input gap |
| `filetrans_timestamp_probe` | file transcription compatible synthetic or approved public sample | timestamp availability | timestamp source, segment count, word count, units | filetrans alignment |
| `word_timestamp_granularity_probe` | known-boundary synthetic phrase | word timing granularity and drift | word count, drift bucket, normalization status | timestamp quality |
| `timestamp_normalization_probe` | mixed chat/filetrans observations | unit and offset normalization | units, offset basis, rejected invalid offsets | replay-safe alignment |
| `partial_transcript_replay_probe` | synthetic partial/final metadata fixture | replay without ASR rerun | partial refs, final refs, no provider call | deterministic replay |
| `client_timeout_probe` | tiny client-side timeout | timeout metadata | failure category, elapsed bucket, no transcript | timeout handling |
| `client_abort_stream_probe` | client closes output stream | local close category | close reason, no cancellation success claim | client close boundary |
| `provider_cancellation_probe` | provider-supported cancel path if available | provider-confirmed cancellation | explicit provider confirmation flag or unknown | cancellation proof |
| `retryable_failure_probe` | controlled retryable failure | bounded retry metadata | retry count, reason, final outcome | retry policy |
| `late_transcript_after_superseded_turn_probe` | delayed output after timeout or superseded request | stale/ignored mapping | original request binding, stale/ignored label | late result safety |
| `asr_not_semantic_truth_probe` | transcript conflicts with synthetic Thinker evidence | evidence boundary | separate evidence refs, no field winner | ADR-008 boundary |

## Input Fixture Policy

Future proof input must be synthetic, deterministic, and privacy-safe.

Allowed future fixture sources:

- Locally generated silence, tone, seeded white noise, and simple speech-like clips.
- Locally generated synthetic speech from approved non-user text, stored only under local temporary paths during the run.
- Provider-approved public sample URLs for timestamp structure proof, if safe to cite.
- Metadata substitutes for playback reference, background speech, and directedness cases when audio would add privacy or implementation risk.

Required fixture metadata:

- `case_id`
- `fixture_kind`
- `input_modality=audio`
- `synthetic_text_ref` or `fixture_description_ref`
- `audio_duration_ms`
- `sample_rate_hz`
- `channels`
- `audio_format`
- `generation_method`
- `contains_real_user_input=false`
- `contains_audio_in_report=false`
- optional `expected_non_speech=true`
- optional `playback_reference_ref`
- optional `expected_directedness_owner=interaction_or_duplex`

Forbidden fixture behavior:

- No committed audio recordings.
- No real user recordings.
- No unredacted user text.
- No provider request or response bodies.
- No secret-bearing environment dumps or request metadata.
- No fixture content that implies a real external side effect.

## Expected Observation Schema

The future proof harness should emit one metadata-only JSON object per case, preferably JSONL. This is a research schema proposal, not a runtime adapter object.

```json
{
  "schema_version": "asr_streaming_timestamp_cancellation_observation_v1",
  "contract_snapshot": "main@61e6afc",
  "observation_id": "obs_asr_qwen_2026_05_12_short_command_001",
  "case_id": "short_command_nonstream_baseline",
  "adapter_type": "asr",
  "provider": "dashscope",
  "model_name": "qwen3-asr-flash",
  "deployment_mode": "remote_api",
  "endpoint_ref": "dashscope-compatible-chat-completions",
  "output_mode": "real_or_degraded",
  "input_fixture": {
    "fixture_kind": "synthetic_audio",
    "input_modality": "audio",
    "audio_duration_ms": 1200,
    "sample_rate_hz": 16000,
    "channels": 1,
    "audio_format": "wav",
    "contains_real_user_input": false,
    "contains_audio_in_report": false,
    "playback_reference_ref": null
  },
  "request_observation": {
    "adapter_request_id": "adapter_req_synthetic_001",
    "streaming_input_mode": "data_url_or_file_url_or_realtime_probe",
    "streaming_output_requested": false,
    "timeout_ms": 10000,
    "retry_count": 0
  },
  "transcript_observation": {
    "transcript_present": true,
    "transcript_length_chars": 7,
    "stored_full_transcript": false,
    "synthetic_snippet_ref": "asr-snippet://synthetic/short_command/001",
    "reliable_directed_user_input": false
  },
  "streaming_observation": {
    "response_streaming_output_observed": false,
    "delta_chunk_count": 0,
    "first_delta_ms": null,
    "final_delta_ms": null,
    "true_realtime_microphone_streaming_input_observed": false,
    "input_chunk_duration_ms": null,
    "input_cadence_ms": null,
    "backpressure_observed": "unknown"
  },
  "timestamp_observation": {
    "timestamp_source": "chat_annotations_or_filetrans_words_or_unavailable",
    "units": "ms_or_seconds_or_unknown",
    "audio_offset_basis": "audio_span_start_or_unknown",
    "segment_count": 0,
    "word_count": 0,
    "normalized": false,
    "normalization_status": "normalized_or_degraded_or_unavailable",
    "degraded_reason": "not_normalized_yet"
  },
  "quality_flags": {
    "expected_non_speech": false,
    "non_speech_transcript_risk": false,
    "clipped_start_case": false,
    "playback_echo_context": false,
    "low_volume_case": false,
    "confidence_available": "unknown",
    "n_best_available": "unknown",
    "language_available": "unknown",
    "punctuation_available": "unknown",
    "itn_available": "unknown"
  },
  "failure_observation": {
    "failure_category": null,
    "retryable": null,
    "provider_confirmed_cancellation": "unknown",
    "client_close_observed": false,
    "late_output_policy": "not_applicable"
  },
  "privacy": {
    "stored_audio": false,
    "stored_provider_body": false,
    "stored_sensitive_access_material": false
  }
}
```

Required validation rules:

- `schema_version`, `contract_snapshot`, `observation_id`, `case_id`, `adapter_type`, `provider`, `model_name`, `deployment_mode`, `endpoint_ref`, and `output_mode` are required.
- `adapter_type` must be `asr`.
- `output_mode` must distinguish `real`, `degraded`, `fallback`, or `mock` when used.
- `stored_audio`, `stored_provider_body`, and `stored_sensitive_access_material` must be false for commit-safe reports.
- Non-speech cases with transcript text must set `non_speech_transcript_risk=true` and `reliable_directed_user_input=false`.
- Timestamp fields may be unavailable, but unavailable timing must be explicit.
- True realtime microphone streaming input must remain false or unknown unless directly exercised.

## Final Transcript Checks

Transcript evidence checks:

- Record transcript presence, length, output surface, latency bucket, and output mode.
- Record whether output came from non-streaming chat, response streaming, file transcription, or future realtime input.
- Record optional synthetic snippet refs only for approved synthetic text.
- Record confidence, n-best, language, punctuation, and ITN availability without assuming support.
- Record validation success or failure against the proposed metadata schema.

Transcript evidence must not:

- become final user intent;
- create `SemanticCommitment`;
- resolve arguments;
- accept confirmation;
- authorize or execute tools;
- open, accept, or commit a turn by itself;
- choose a winner when ASR and Thinker evidence disagree.

## Streaming Output Checks

Response streaming output is already observed_real for `short_command_streaming`, but it still needs proof-quality metadata.

Required checks:

- `stream_done` status.
- Delta chunk count.
- First delta latency.
- Final delta latency.
- Final transcript length.
- Whether annotations were present.
- Whether partials were monotonic, revised, duplicated, or empty.
- Whether the final result can be bound to the same `adapter_request_id` as the partials.

Boundary:

- Response streaming output is ASR evidence only.
- Response streaming output is not turn ingress ownership.
- Response streaming output does not prove true realtime microphone streaming input.

## Realtime Streaming Input Checks

True realtime microphone streaming input remains unknown/degraded until directly exercised or explicitly ruled out.

Required proof if a future provider surface supports it:

- Input chunk duration in ms.
- Input cadence in ms.
- Audio sample rate, channel count, and format.
- Backpressure behavior.
- First partial latency from first speech chunk.
- Final transcript latency from input close.
- Stream close reason.
- Whether partial and final outputs preserve one request/audio span binding.

Fallback if not supported:

- Record `true_realtime_microphone_streaming_input_observed=false`.
- Record `supports_streaming_input=unsupported` or `observed_degraded`, depending on official/provider evidence.
- Continue treating Data URL and file URL inputs as audio-input evidence, not realtime input evidence.

## Timestamp / Alignment Checks

Timestamp metadata is alignment evidence. It is not user intent, confirmation, task progress, or final fact.

Required checks:

- Timestamp source: chat annotations, filetrans segments, filetrans words, or unavailable.
- Units: milliseconds, seconds, samples, or unknown.
- Offset basis: audio span start, provider file start, segment start, or unknown.
- Segment count and word count.
- Negative offset rejection.
- Descending offset rejection.
- Overlapping offset warning or rejection, depending on field.
- Missing timing as `normalization_status=unavailable`, not invented offsets.
- Drift bucket for known-boundary synthetic phrases if available.

Proposed normalized shape:

```json
{
  "timestamp_source": "filetrans_words",
  "units": "ms",
  "audio_offset_basis": "audio_span_start",
  "segments": [
    {
      "segment_index": 0,
      "start_ms": 0,
      "end_ms": 1200,
      "text_ref": "asr-segment://synthetic/001/0",
      "confidence": null
    }
  ],
  "words": [
    {
      "word_index": 0,
      "start_ms": 0,
      "end_ms": 300,
      "text_ref": "asr-word://synthetic/001/0",
      "confidence": null
    }
  ],
  "normalization_status": "normalized_or_degraded_or_unavailable",
  "degraded_reason": null
}
```

## Silence / Non-Speech / Echo Checks

The prior run observed a one-second silence input producing a short non-empty transcript-like output. That result is degraded quality evidence and must be kept visible.

Required checks:

- `silence_non_speech_probe`: transcript presence, length, and degradation label.
- `tone_non_speech_probe`: whether deterministic tone produces transcript-like output.
- `white_noise_non_speech_probe`: whether seeded noise produces transcript-like output.
- `background_speech_not_directed_probe`: transcript presence plus directedness owner outside ASR.
- `playback_only_echo_probe`: transcript presence plus playback reference context.
- `user_speech_over_playback_probe`: overlap flags, transcript length, timing bucket, and output mode.

Required flags:

- `expected_non_speech=true` for non-speech cases.
- `non_speech_transcript_risk=true` if transcript exists.
- `reliable_directed_user_input=false`.
- `ingress_owner=Interaction Controller`.
- `semantic_truth_owner=SlowTask for complex tasks`.

Forbidden conclusions:

- Do not treat a non-empty silence/non-speech transcript as reliable directed user input.
- Do not let ASR output independently open or commit a turn.
- Do not use ASR transcript to infer assistant-directedness.
- Do not use ASR transcript to infer semantic close.

## Cancellation / Timeout / Retry / Late Output Checks

Observed prior behavior:

- Client timeout occurred.
- Provider-confirmed cancellation was not observed.
- Retry was not exercised.

Required future proof matrix:

| condition | future observation | required mapping | forbidden interpretation |
| --- | --- | --- | --- |
| `client_timeout_probe` | timeout category, elapsed bucket, no transcript | adapter failure metadata; no state advance | Do not treat as provider-confirmed cancellation. |
| `client_abort_stream_probe` | client close category, partial count, final status | degraded cancellation metadata | Do not claim remote cancellation success. |
| provider-confirmed cancellation if available | explicit provider confirmation field | only then mark cancellation observed_real | Do not infer from local close. |
| transient provider failure | failure category and retryability | bounded retry metadata before final failure | Do not silently replace with guessed transcript. |
| malformed provider output | schema validation reasons | validation failure metadata | Do not pass invalid output downstream. |
| async filetrans task failure | task status and failure category | adapter failure metadata | Do not mutate Interaction or SlowTask state. |
| late result after timeout or superseded turn | original request binding, stale/ignored label | stale-friendly evidence metadata | Do not advance current task state. |

Late output rules:

- Preserve original `adapter_request_id`, audio ref, fixture ref, and case id.
- If associated with a task in future integration, preserve original `task_id`, `plan_version`, and `task_event_seq`.
- Late output must not advance current task state.
- Reuse requires explicit SlowTask adopt/rebase in runtime; this proof plan only records metadata.

Retry rules:

- Retry count and reason must be explicit.
- Retries must not create duplicate ASR frame facts without causal binding.
- Final failure must remain replay-visible.

## ASR / Interaction / Router / Thinker / SlowTask Boundary Notes

Qwen-ASR / ASR:

- Provides transcript or text projection evidence.
- Provides optional timing alignment metadata.
- Provides optional confidence, n-best, language, punctuation, or ITN metadata only if observed.
- Provides provenance refs for downstream evidence review.
- Does not own turn ingress, semantic close, assistant-directedness, confirmation, tool authorization, task completion, resolved arguments, risk warnings, or semantic truth.

Interaction Controller:

- Owns turn ingress acceptance, rejection, hold, and commit.
- Owns whether low-confidence ingress remains held or rejected.
- Must not be bypassed by ASR transcript presence.

Router:

- May carry uncertainty and route evidence.
- Must not choose ASR-vs-Thinker field winners.
- Must not produce final conflict verdicts for complex tasks.

Thinker:

- Provides separate speech-native semantic/audio evidence when available.
- Does not become ASR normalization.
- May disagree with ASR; that disagreement remains evidence.

SlowTask:

- Owns ambiguity review, resolved arguments, confirmation state, tool authorization readiness, and task progress for complex tasks.
- Must receive provenance for fields that affect tools or commitments.
- Must not advance from stale ASR output without explicit adopt/rebase.

## Event Mapping Notes

Existing contract events relevant to this proof:

- `AUDIO_SPAN_STARTED`, `AUDIO_CHUNK_RECEIVED`, `AUDIO_SPAN_ENDED` for audio span metadata.
- `SPEECH_START_DETECTED`, `SPEECH_END_DETECTED`, `LOW_CONFIDENCE_INGRESS` for Duplex/Interaction diagnostics.
- `TURN_INGRESS_ACCEPTED`, `TURN_INGRESS_REJECTED`, `TURN_INGRESS_COMMITTED` for Interaction ownership.
- `MOCK_ASR_FRAME_EMITTED` as the current MVP mock shape reference for ASR frame metadata.
- `ADAPTER_REQUEST_RETRYING`, `ADAPTER_REQUEST_FAILED`, `ADAPTER_OUTPUT_VALIDATION_FAILED`, `ADAPTER_OUTPUT_DEGRADED` for provider/control failures.
- `USER_PATCH_RECEIVED`, `USER_PATCH_INTERPRETED`, and SlowTask events for downstream task handling, not ASR ownership.

This plan does not introduce new canonical events. If future real ASR event names are needed, they must go through the accepted event registry process before runtime use.

## Replay-Safe Metadata Shape

Deterministic replay must not rerun Qwen-ASR. Replay should consume recorded metadata, redacted refs, or synthetic fixtures.

Draft proof bundle:

```json
{
  "replay_eval_manifest": {
    "manifest_schema_version": "1.0",
    "replay_id": "replay_asr_qwen_streaming_timestamp_cancellation_001",
    "source_trace_ref": "asr-proof://synthetic/qwen/2026-05-12",
    "replay_mode": "deterministic",
    "event_schema_version_range": ["1.0"],
    "fixture_domain": "GITHUB_ALLOWED",
    "generated_from": "synthetic",
    "contains_audio": false,
    "contains_trace": false,
    "contains_real_user_input": false,
    "contains_sensitive_access_material": false,
    "contains_unredacted_tool_result": false,
    "contains_large_web_content": false,
    "allowed_re_eval_components": []
  },
  "asr_observations_ref": "asr-proof-observations://synthetic/qwen/2026-05-12",
  "observation_count": 22,
  "rerun_provider_in_deterministic_replay": false
}
```

Replay-safe observations may include:

- invented ids;
- case ids;
- transcript presence flags;
- transcript lengths;
- synthetic snippet refs;
- timestamp availability and normalized timing metadata;
- stream event counts;
- latency buckets;
- confidence availability flags;
- degradation labels;
- failure categories;
- causal refs.

Replay-safe observations must not include:

- audio recordings;
- provider request or response bodies;
- real user input;
- request headers;
- sensitive access material;
- unredacted full transcripts from real inputs;
- local debug traces or replay caches.

## Trace / Privacy Boundary

The future proof harness should write only metadata summaries suitable for a research report.

Required privacy posture:

- Keep generated audio local-only and temporary.
- Store no audio recordings in GitHub-allowed output.
- Store no provider request or response bodies.
- Store no request headers.
- Store no sensitive access material.
- Store no real user recordings or real user text.
- Store no local debug traces or replay caches.
- Use synthetic ids, redacted refs, transcript lengths, timing buckets, and capability labels.

If future harness code writes local generated audio, it must use a temporary path outside the repo and remove it after metadata extraction. If future debugging needs local audio retention, that must be a separate explicit local-only step and remain outside commit scope.

## Fit to MVP-0 / MVP-1 / MVP-2 / MVP-3

MVP-0:

- The proof can validate future replacement shape for mock ASR metadata.
- It should map cleanly to `asr_frame_ref`-style evidence.
- It must not change MVP-0 runtime.
- Replay consumes metadata and does not rerun ASR.

MVP-1:

- ASR transcript can become one evidence source for UserPatch / SlowTask review.
- Late-output and stale-friendly request binding are required before integration consideration.
- ASR cannot directly advance `plan_version`, resolve arguments, adopt stale evidence, or mutate SlowTask state.

MVP-2:

- ASR cannot authorize tools, confirm actions, patch UI, or drive demo tool execution.
- Tool-relevant transcript evidence must pass through Interaction, Router, UserPatch, SlowTask review, and Tool Executor authorization.
- Non-speech and echo false positives must be evaluated before ASR evidence influences confirmation or tool-related paths.

MVP-3:

- This proof is a prerequisite for stronger Qwen-ASR integration consideration.
- MVP-3 consideration still needs executed results, timestamp normalization, provider failure/cancellation mapping, and a true realtime input decision.
- MVP-3 may replace mock adapters with real adapters only without adding architecture capability.

## Risks / Gaps

- True realtime microphone streaming input may remain unsupported or provider-surface-specific.
- Silence/non-speech false positives are already observed as a risk.
- Playback-only echo may produce transcript evidence that is not user input.
- Timestamp structures may differ between chat annotations and file transcription outputs.
- Timestamp units and offset bases may be unclear or inconsistent.
- Client timeout and client stream close do not prove provider-confirmed cancellation.
- Retry behavior is unknown.
- Async file transcription task failure behavior is unknown.
- Confidence, n-best, language, punctuation, and ITN support may be missing or inconsistent.
- Longer utterances, low-volume inputs, clipped starts, and overlap with playback may change latency and quality materially.
- Synthetic audio may not represent real device acoustics.
- No committed replay/eval fixture should be created until harness design is separately approved.

## Recommendation

Keep DashScope / Bailian Qwen-ASR on the ASR shortlist, but do not move it into MVP-3 integration from the current evidence alone.

Treat the following as observed_real for research purposes:

- final transcript-like output;
- response streaming output;
- audio input through Data URL and file URL surfaces;
- file transcription timestamp-like and word-like metadata.

Treat the following as degraded or unknown before MVP-3 consideration:

- true realtime microphone streaming input;
- silence/non-speech robustness;
- playback-only echo rejection;
- provider-confirmed cancellation;
- retry behavior;
- late-output handling;
- confidence and quality thresholds;
- exact timestamp normalization.

The next approved research action should produce metadata-only proof results for the synthetic case matrix, not runtime code.

## Next Implementation Step, Gated on Human Approval

After human approval, create a spike-local implementation plan for a proof harness under a path such as `tools/model_spikes/asr_streaming_eval/`.

Future harness implementation should remain spike-local and should not import or modify MVP runtime modules. Suggested future outputs:

- `README.md` describing local-only execution and privacy posture.
- `schemas/asr_streaming_observation.schema.json` for metadata validation.
- `fixtures/README.md` describing synthetic input generation policy without committing audio.
- JSONL observations with one metadata-only object per case.
- A redacted run summary markdown report that stores no audio recordings, provider bodies, local traces, replay caches, real user input, request headers, or sensitive access material.

This thread does not create those files or code.
