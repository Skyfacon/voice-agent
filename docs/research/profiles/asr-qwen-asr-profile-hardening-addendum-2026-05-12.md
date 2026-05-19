# ASR Qwen-ASR Profile Hardening Addendum

## Status

harden_after_gap_research_addendum_metadata_only

This addendum applies `docs/research/model-spike-adapter-profile-hardening-checklist-2026-05-12.md` to the DashScope / Bailian Qwen-ASR profile. It is research hardening only. It does not authorize runtime integration, provider execution, business adapter work, ADR/spec changes, or MVP scope expansion.

## Date

2026-05-12

## Contract Snapshot

- Default contract snapshot: `main@61e6afc`
- MVP-0 closeout reference: `22ddbf4 fix: harden mvp0 trace and replay safety`
- ASR / Thinker evidence fusion reference: ADR-008
- Capability contract reference: ADR-011 and `docs/specs/model-adapter-capabilities.md`
- SlowTask lifecycle and confirmation reference: ADR-016
- Event and replay references: `docs/specs/event-registry.md` and `docs/specs/replay-spec.md`

## Scope

In scope:

- Harden the existing Qwen-ASR profile from draft evidence toward a profile candidate.
- Apply the common hardening gates: identity, capability labels, streaming distinction, timestamp normalization, timeout/retry/cancellation separation, replay-safe metadata, and owner-boundary assertions.
- Classify which evidence is `observed_real`, `observed_degraded`, `synthetic_eval`, `unknown`, or `unsupported`.

Out of scope:

- No provider execution in this step.
- No runtime adapter implementation.
- No changes to `src/voice_agent/`, `tests/`, `docs/adr/`, or `docs/specs/`.
- No audio recordings, provider bodies, raw trace, local replay cache, real user input, or secret-bearing material.
- No claim that Qwen-ASR is ready for MVP-3 integration today.

## Source Evidence

- `docs/research/profiles/asr-qwen-asr-capability-profile-draft-2026-05-12.md`
- `docs/research/spikes/asr-dashscope-bailian-run-2026-05-11.md`
- `docs/research/spikes/asr-qwen-asr-streaming-timestamp-cancellation-proof-plan-2026-05-12.md`
- `docs/research/spikes/asr-qwen-asr-streaming-eval-dry-run-2026-05-12.md`
- `tools/model_spikes/asr_streaming_eval/`
- `docs/research/model-spike-adapter-profile-hardening-checklist-2026-05-12.md`
- `docs/research/model-spike-phase-summary-2026-05-12.md`

Fresh local dry-run check for this addendum:

| command class | result |
| --- | --- |
| `asr_streaming_eval dry-run --case-set full_synthetic` | 23 observations generated under `/private/tmp/.../hardening-full/observations.jsonl` |
| `asr_streaming_eval validate` | `valid=true`, 23 observations, zero errors |

## Hardening Decision

Recommendation: `harden_after_gap`.

Reasoning:

- Qwen-ASR has observed real evidence for final transcript-like output, response streaming output, audio input through prior synthetic/file inputs, and file transcription timestamp-like metadata.
- The 2026-05-11 run directly observed non-streaming transcript-like output, streaming response deltas, async timestamp-like structures, and a client timeout category without storing audio recordings or provider bodies.
- The spike-local streaming eval adds repeatable metadata shape for transcript baseline, mixed language, clipped starts, low volume, longer utterances, non-speech cases, playback/echo contexts, response streaming, timestamp normalization, partial replay, timeout, client abort, provider cancellation, retryable failure, late transcript, and ASR-not-semantic-truth cases.
- The strongest gaps remain true realtime microphone streaming input, silence/non-speech policy, confidence calibration, timestamp normalization quality, provider-confirmed cancellation, and live retry taxonomy.

This is not `ready_for_mvp3`. It is a research signal that Qwen-ASR remains viable for ASR profile hardening only if the realtime and quality gaps stay explicit.

## Candidate Identity Disposition

| field | hardening label | disposition |
| --- | --- | --- |
| Adapter role | `observed_real` | ASR / text projection evidence provider. |
| Provider | `observed_real` | DashScope / Bailian. |
| Chat ASR model alias | `observed_real_needs_recheck` | `qwen3-asr-flash` was observed on 2026-05-11; re-pin before any future live hardening run. |
| File transcription model alias | `observed_real_needs_recheck` | `qwen3-asr-flash-filetrans` was observed on 2026-05-11; re-pin before any future live hardening run. |
| Deployment mode | `observed_real` | Remote API surfaces. |
| Endpoint refs | `observed_real` | Chat completions, audio transcription, and task polling refs, with no secret-bearing values. |
| Health observation | `observed_real` | Successful transcript and timestamp probes returned usable metadata. |
| Output label | `observed_real_or_degraded` | Real for successful ASR evidence; degraded for timeout and silence/non-speech risk. |
| Latency class | `observed_real_bucket` | Short non-streaming clips returned around 0.4s to 0.5s; response streaming first delta was around 1.3s. |

Qwen-ASR is text projection evidence only. It is not a turn ingress owner, not an Interaction Controller, not a Router, not a Thinker, not SlowTask, and not a semantic truth owner.

## Capability Disposition

| capability area | hardening label | disposition |
| --- | --- | --- |
| Final transcript-like output | `observed_real` | Non-streaming synthetic cases produced transcript-like metadata. |
| Response streaming output | `observed_real` | One streaming case produced four response deltas and a final transcript-like result. |
| Audio input | `observed_real` | Prior synthetic/local Data URL and public sample URL inputs succeeded. |
| File transcription timestamp-like metadata | `observed_real` | Async file transcription returned timestamp-like fields and word-like arrays. |
| Chat annotations | `observed_real` | Chat responses included annotation metadata. |
| Short-input latency bucket | `observed_real_bucket` | Run-specific bucket only; not a general product SLO. |
| True realtime microphone streaming input | `unknown_or_degraded` | Not directly exercised; response streaming output must not be widened into live mic support. |
| Silence/non-speech handling | `observed_degraded` | Silence produced a short non-empty transcript-like result, so this remains false-positive risk evidence. |
| Client timeout | `observed_degraded` | Timeout category observed; no provider-confirmed cancellation. |
| Provider-confirmed cancellation | `unknown` | Must remain unknown unless directly observed. |
| Retry behavior | `unknown` | Retryable provider failures were not live-exercised. |
| Confidence and alternatives | `unknown` | Confidence calibration, alternative hypotheses, language confidence, punctuation, and ITN behavior remain unproven. |
| Timestamp normalization quality | `synthetic_eval_plus_unknown_quality` | Dry-run covers normalized shape; live quality and cross-surface consistency remain unproven. |
| Structured task reasoning | `unsupported` | ASR transcript is not SlowTask-ready structured reasoning output. |
| Tool calling | `unsupported` | ASR must not propose, authorize, or execute tools. |
| TTS / playback | `unsupported` | Outside ASR role. |
| Semantic close and directedness | `unsupported` | Outside ASR authority. |
| Confirmation and task completion | `unsupported` | Outside ASR authority. |
| Audio duration and format limits | `unknown` | Must be rechecked on any live hardening day. |

## Checklist Result

| gate | status | notes |
| --- | --- | --- |
| Research boundary | pass | Addendum stays under `docs/research/`. |
| Candidate identity | partial pass | Identity is recorded; current aliases, supported formats, limits, and endpoint details still need recheck before live hardening. |
| Capability matrix coverage | partial pass | Core ASR evidence is labeled; realtime input, cancellation, retry, confidence, and normalized timing quality remain gaps. |
| Error taxonomy | partial pass | Client timeout, client abort, retryable failure, late transcript, and provider cancellation have metadata shapes; live provider taxonomy remains incomplete. |
| Realtime input distinction | pass as boundary, gap as capability | Response streaming output is separated from true realtime microphone input, which remains unknown/degraded. |
| Silence/non-speech policy | partial pass | Risk is explicit; future thresholds and eval policy are still needed. |
| Replay posture | pass | Dry-run and profile require metadata/synthetic fixture consumption only. |
| Owner boundaries | pass | ASR remains text projection evidence, not semantic or control authority. |
| MVP-3 readiness | not ready | Integration requires a later approved branch, realtime proof or explicit degraded policy, health/error policy, and replay/eval fixtures. |

## Streaming / Realtime Boundary Addendum

Required interpretation:

- Response streaming output is `observed_real` for response deltas only.
- Response streaming output does not prove true realtime microphone streaming input.
- Data URL and file URL inputs are `observed_real` for audio input, but not for live microphone chunk ingestion.
- True realtime microphone streaming input remains `unknown_or_degraded` until directly exercised.
- If future realtime input remains unavailable, the ASR profile must state the degraded ingestion path rather than silently implying full-duplex input.

Required future metadata:

- input mode
- output stream mode
- input chunk duration if live chunks are used
- input cadence and backpressure status if live chunks are used
- first partial timing
- final transcript timing
- stream close reason
- output label

## Timestamp / Alignment Addendum

Timestamp-like metadata is observed as alignment evidence, not semantic truth.

Required normalized shape:

- timestamp source surface
- units
- audio offset basis
- segment count
- word count
- optional confidence availability
- normalized or degraded status
- malformed or missing timing reason

Rules:

- Missing timestamps must be recorded as unavailable or degraded.
- Malformed timestamps must be rejected or degraded.
- Adapter logic must not invent offsets.
- Timestamp metadata must not create user intent, confirmation, task progress, or SemanticCommitment.
- Chat annotations and file transcription word-like structures need cross-surface normalization before MVP-3 consideration.

## Silence / Non-Speech Addendum

The prior silence/non-speech probe returned a short non-empty transcript-like result. This is observed degraded evidence.

Required hardening behavior:

- Silence, tone, noise, playback-only echo, and background speech cases must be represented as risk cases.
- Non-speech transcript-like output must set a degradation or risk flag.
- Non-speech transcript-like output must not independently open, accept, or commit a turn.
- Non-speech transcript-like output must not be treated as reliable directed user input.
- Duplex/Interaction evidence must remain available to reject or downgrade false turns.

## Error / Retry / Cancellation Addendum

Required hardening behavior:

- Client timeout becomes adapter failure or degraded-output metadata and cannot mutate Interaction, Router, or SlowTask state.
- Client stream abort is local client-control metadata, not provider-confirmed cancellation.
- Provider-confirmed cancellation remains `unknown` unless an explicit provider confirmation surface is observed.
- Retryable failure records retry count, retry reason, and final outcome.
- Exhausted retry budget becomes degraded/failure metadata and cannot create a successful ASR frame.
- Late transcript after timeout, abort, or superseded turn stays bound to the original audio/request refs and is stale or ignored for current state.
- Provider output that cannot be normalized becomes validation failure metadata and cannot pass downstream.

## ASR / Thinker / SlowTask Boundary Addendum

ASR output is evidence. It is not the only semantic truth.

Allowed:

- Normalize transcript-like output into ASR frame evidence.
- Preserve transcript length, optional synthetic snippet ref, timing refs, source surface, output label, and quality flags.
- Pass ASR evidence alongside Thinker, Duplex, Interaction, UserPatch, LiveContext, and task history evidence.
- Preserve ASR/Thinker disagreement for SlowTask-led review.

Forbidden:

- ASR must not own turn ingress.
- ASR must not decide semantic close.
- ASR must not decide assistant-directedness.
- ASR transcript must not become SemanticCommitment.
- ASR must not decide confirmation.
- ASR must not decide tool authorization.
- ASR must not decide task completion.
- ASR must not decide resolved arguments.
- ASR must not remove or reinterpret risk warnings.
- ASR must not choose a field-level winner when ASR and Thinker disagree.

## Replay-Safe Metadata Shape

A hardened ASR profile should use a metadata shape like:

```json
{
  "profile_id": "asr_qwen_asr_hardening_2026_05_12",
  "contract_snapshot": "main@61e6afc",
  "candidate": {
    "adapter_type": "asr",
    "provider": "dashscope",
    "model_name_observed": "qwen3-asr-flash",
    "timestamp_model_name_observed": "qwen3-asr-flash-filetrans",
    "model_alias_recheck_required": true,
    "deployment_mode": "remote_api",
    "endpoint_refs": [
      "dashscope-compatible-chat-completions",
      "dashscope-audio-asr-transcription",
      "dashscope-task-polling"
    ],
    "output_mode": "real_or_degraded"
  },
  "transcript": {
    "final_transcript_label": "observed_real",
    "response_streaming_output_label": "observed_real",
    "transcript_length_only_allowed": true,
    "full_transcript_stored": false,
    "reliable_directed_user_input": false
  },
  "audio_input": {
    "data_url_input_label": "observed_real",
    "file_url_input_label": "observed_real",
    "true_realtime_microphone_streaming_input": "unknown_or_degraded"
  },
  "timestamp_alignment": {
    "timestamp_label": "observed_real",
    "normalization_label": "synthetic_eval_until_live_quality_proof",
    "timestamp_source": "chat_annotations_or_filetrans_words",
    "units": "ms_or_seconds_or_unknown",
    "audio_offset_basis": "audio_span_start_or_unknown"
  },
  "quality": {
    "silence_non_speech_label": "observed_degraded",
    "confidence_calibration": "unknown",
    "language_confidence": "unknown",
    "false_positive_policy_required": true
  },
  "failure": {
    "client_timeout_label": "observed_degraded",
    "provider_cancel_confirmed": "unknown",
    "retry_behavior": "unknown",
    "late_transcript_policy": "stale_or_ignored"
  },
  "privacy": {
    "audio_recording_stored": false,
    "provider_body_stored": false,
    "raw_trace_stored": false,
    "local_replay_cache_stored": false,
    "real_user_input_stored": false,
    "secret_bearing_material_stored": false,
    "deterministic_replay_reruns_provider": false
  }
}
```

Audio recordings are not replay-safe artifacts and must not be committed. Deterministic replay must not rerun ASR; it consumes recorded metadata or synthetic fixtures only.

## Event Mapping Addendum

The hardened profile should be able to map future observations to existing event families without creating new event names:

| condition | future event-compatible mapping | state effect |
| --- | --- | --- |
| Final transcript-like output | ASR frame ref plus adapter output metadata | Evidence only. |
| Response streaming delta | Partial ASR evidence ref after adapter normalization | No turn commit by ASR. |
| Timestamp-like metadata | ASR timing metadata with normalized/degraded status | No semantic truth. |
| Silence/non-speech transcript | degraded ASR evidence with false-positive risk | No reliable directed input by itself. |
| ASR/Thinker disagreement | separate evidence refs for SlowTask-led review | No Router field arbitration by ASR. |
| Client timeout or stream abort | adapter degraded/failure metadata | No state advance. |
| Provider-confirmed cancellation absent | cancellation remains unknown/degraded | No cancel success claim. |
| Late transcript | stale or ignored output metadata | No current-state advance. |

## MVP Fit

| slice | addendum fit |
| --- | --- |
| MVP-0 | Supports future real ASR adapter profile shape; current mock understanding remains sufficient for runtime. |
| MVP-1 | ASR evidence can feed SlowTask review only after owner-controlled binding and stale policy. |
| MVP-2 | ASR can provide evidence for Composer/Tool flows, but cannot decide facts, authorization, or confirmation. |
| MVP-3 | Candidate for ASR integration consideration only after realtime input or degraded-ingress policy, timestamp normalization, false-positive policy, and provider health/error gaps are closed in an approved integration lane. |

## Remaining Blockers

- Current model aliases, service limits, audio formats, sample rates, file size limits, and maximum audio duration must be rechecked on any live hardening day.
- True realtime microphone streaming input remains unknown/degraded.
- Silence/non-speech, tone/noise, background speech, and playback-only echo need explicit eval thresholds.
- Confidence calibration, alternatives, language confidence, punctuation, and ITN behavior remain unproven.
- Timestamp normalization quality across chat annotations and file transcription remains incomplete.
- Provider-confirmed cancellation remains unknown.
- Retry behavior under live transient provider failures remains unknown.
- Late transcript behavior after superseded turn is synthetic-only.
- No runtime replay/eval fixture has been approved in this research lane.

## Recommendation

Keep DashScope / Bailian Qwen-ASR as `harden_after_gap` for ASR profile hardening.

Do not start runtime integration from this addendum. The next research step is to apply the same addendum pattern to Thinker Qwen-Omni while keeping SemanticFrame evidence separate from Router authority, SemanticCommitment, confirmation, and tool authorization.
