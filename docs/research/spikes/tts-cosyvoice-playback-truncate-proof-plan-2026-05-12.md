# TTS Playback / Truncate Proof Plan: DashScope / Bailian CosyVoice

## Status

planned_metadata_only_proof

This document is a research proof plan only. It does not authorize runtime integration, main harness code, real business adapter work, provider calls, ADR changes, event registry changes, replay spec changes, or MVP scope expansion.

## Date

2026-05-12

## Contract Snapshot

- Default contract snapshot: `main@61e6afc`
- MVP-0 closeout reference: `22ddbf4 fix: harden mvp0 trace and replay safety`
- Playback / truncate contract: ADR-003 and `docs/specs/event-registry.md`
- Composer / SemanticCommitment contract: ADR-009
- Adapter capability contract: ADR-011 and `docs/specs/model-adapter-capabilities.md`
- SlowTask ownership and confirmation contract: ADR-016
- Replay contract: `docs/specs/replay-spec.md`

## Scope

This plan defines the remaining playback and truncate evidence required before DashScope / Bailian CosyVoice can enter MVP-3 consideration as a TTS / Talker audio-provider candidate.

In scope:

- Basic synthesis proof requirements.
- First-audio latency, audio duration, format, sample rate, voice id, and streaming output checks.
- Talker playback progress metadata needed by ADR-003.
- Truncate / stop proof requirements for `PLAYBACK_SPAN_STARTED`, `PLAYBACK_PROGRESS`, `PLAYBACK_COMMITTED`, `TTS_TRUNCATE_REQUESTED`, and `TTS_TRUNCATED`.
- Distinguishing provider stream cancellation, client close, local playback stop, and Interaction truncate.
- Timeout, retry, cancellation, late audio, partial audio, and format mismatch observation shape.
- Replay-safe metadata-only report shape for a future spike-local proof.

Out of scope:

- No changes to `src/voice_agent/`, `tests/`, `docs/adr/`, or `docs/specs/`.
- No main runtime wiring.
- No real business adapter.
- No spike-local harness implementation in this thread.
- No live provider call in this thread.
- No committed generated audio, raw traces, provider response bodies, local replay cache, real user input, request metadata that can identify a secret, or provider audio content.
- No claim that playback committed is user acknowledgement.
- No claim that provider stream close equals provider-confirmed cancellation.

## Source Evidence

Primary evidence:

- `docs/research/spikes/tts-dashscope-bailian-run-2026-05-11.md`
- `docs/research/profiles/tts-cosyvoice-capability-profile-draft-2026-05-12.md`

Coordination evidence:

- `docs/research/model-spike-phase-summary-2026-05-11.md`
- `docs/research/model-spike-execution-plan.md`
- `docs/research/model-spike-integration-ledger.md`
- `docs/research/model-spike-plan.md`
- `docs/research/model-selection.md`

Contract evidence:

- `AGENTS.md`
- `docs/specs/model-adapter-capabilities.md`
- `docs/specs/event-registry.md`
- `docs/specs/replay-spec.md`
- `docs/adr/ADR-003 Barge-in and TTS Truncate Contract.md`
- `docs/adr/ADR-009 SemanticCommitment and Thinker-as-Composer Contract.md`
- `docs/adr/ADR-011 Model Adapter Capability Contract.md`
- `docs/adr/ADR-016 SlowTask Lifecycle and Confirmation State Contract.md`

Current evidence labels:

| Evidence item | Current label | Notes |
| --- | --- | --- |
| Basic CosyVoice synthesis | `observed_real` | The 2026-05-11 run observed completed synthesis for short and longer synthetic prompts. |
| First-audio latency bucket | `observed_real` | Observed about 493ms to 705ms for the synthetic run set; not a general SLO claim. |
| Streaming audio output | `observed_real` | Binary WebSocket audio chunks were directly observed. |
| Word timestamp / alignment events | `observed_real` | Useful alignment metadata, not playback delivery truth. |
| Voice id `longanyang` | `observed_real` | One voice id was observed; full voice catalog support is unproven. |
| Format `mp3` and sample rate `22050` | `observed_real` | Observed request accepted these values; broader format/rate matrix remains unproven. |
| Client close during stream | `observed_degraded` | Client close was observed; provider-confirmed cancellation was not. |
| Provider-confirmed cancellation | `unknown` | Must not be inferred from client close. |
| Talker playback progress | `unknown` | Existing run did not validate playback scheduling or progress events. |
| Local playback stop offset | `unknown` | Existing run did not validate actual stop offset. |
| Provider/model-layer TTS truncate | `unsupported` | ADR-003 truncate is playback/interaction control, not model semantics. |
| Pause/resume | `unsupported` | MVP non-goal. |

## Candidate Identity

| Field | Planned value | Evidence label | Notes |
| --- | --- | --- | --- |
| `adapter_type` | `tts_talker` | `observed_real` | CosyVoice is only considered for the TTS audio-provider role. |
| `provider` | DashScope / Bailian | `observed_real` | Provider used in the 2026-05-11 run. |
| `model_name` | `cosyvoice-v3-flash` | `observed_real` | Must be re-pinned on any future run day. |
| `voice_id` | `longanyang` plus probe variants | `observed_real` for `longanyang`; `unknown` for variants | Future proof should validate voice id acceptance and failure shape. |
| `deployment_mode` | `remote_api` | `observed_real` | WebSocket inference surface observed. |
| `endpoint_ref` | `dashscope-websocket-inference` | `observed_real` | Ref only, never a secret-bearing URL. |
| `output_mode` | `real` / `degraded` | case-specific | Successful audio is `real`; client close, timeout, partial, or mismatch observations are `degraded` unless failed. |

CosyVoice / TTS is audio synthesis evidence/provider only. It is not a turn ingress owner, not an Interaction Controller, not a Router, not SlowTask, and not a semantic truth owner.

## Proof Goals

1. Prove that a future TTS adapter observation can report basic synthesis without storing generated audio.
2. Prove first-audio latency, total synthesis duration, audio duration, format, sample rate, voice id, chunk count, and byte-count metadata can be recorded as replay-safe observations.
3. Prove streaming output metadata can be consumed by a Talker-like proof without claiming playback progress from provider chunks alone.
4. Prove Talker/playback can own `PLAYBACK_SPAN_STARTED`, `PLAYBACK_PROGRESS`, and `PLAYBACK_COMMITTED`.
5. Prove Interaction Controller can own `TTS_TRUNCATE_REQUESTED`, while Talker/playback owns `TTS_TRUNCATED(actual_stop_offset_ms)`.
6. Prove provider-side stream cancellation, client close, local playback stop, and Interaction truncate are separate observation classes.
7. Prove timeout, retry, cancellation, late audio, partial audio, and format mismatch can be recorded with adapter-shaped failure/degradation metadata.
8. Prove deterministic replay can consume recorded metadata or synthetic fixtures without rerunning TTS.

## Non-Goals

- No proof of user acknowledgement from TTS output or playback delivery.
- No proof of SemanticCommitment from spoken audio.
- No proof that CosyVoice can decide interrupt, barge-in, semantic close, assistant-directedness, confirmation, tool authorization, resolved arguments, risk warnings, or task completion.
- No proof of provider/model-layer target-valid truncate.
- No pause/resume validation.
- No quality evaluation of emotion, style, voice naturalness, pronunciation, or user preference.
- No generated audio committed as a replay-safe artifact.
- No production privacy policy, production observability design, or main runtime integration.

## Synthetic Case Matrix

| case_id | Purpose | Input shape | Expected evidence label | Required observations |
| --- | --- | --- | --- | --- |
| `basic_short_synthesis` | Confirm short text synthesis remains viable. | Short neutral synthetic sentence. | `observed_real` if completed. | task finished, first audio bucket, chunk count, byte count, audio duration bucket, format, sample rate, no generated audio stored. |
| `longer_sentence_synthesis` | Confirm longer SpokenPlan-like text scales. | Multi-sentence synthetic SpokenPlan-like text. | `observed_real` if completed. | total duration bucket, chunk cadence bucket, timestamp availability, partial/final events. |
| `voice_id_probe` | Validate accepted and rejected voice ids. | Known observed voice plus one synthetic invalid voice id. | `observed_real` for accepted; `observed_degraded` or failed for rejected. | voice id requested, acceptance/failure category, no provider body stored. |
| `format_probe` | Validate output format metadata. | Same text with format variants approved for the future run. | `observed_real` or `unknown` per variant. | requested format, observed container/ref metadata, mismatch category. |
| `sample_rate_probe` | Validate sample rate request and output metadata. | Same text with sample rate variants approved for the future run. | `observed_real` or `unknown` per variant. | requested sample rate, observed/decoded sample rate if locally inspected, mismatch category. |
| `streaming_audio_probe` | Confirm chunked output. | Short and medium text over streaming surface. | `observed_real` if binary chunks arrive before finish. | first chunk monotonic time, chunk count, chunk cadence bucket, stream end reason. |
| `first_audio_latency_probe` | Measure request-to-first-audio bucket. | Repeated short synthetic prompts. | `observed_real` bucket only. | request start, first audio time, timeout bound, bucket summary. |
| `playback_progress_probe` | Validate Talker progress metadata shape. | Synthetic stream ref or recorded metadata, not raw audio. | `unknown` until future proof runs. | playback span id, progress cadence, monotonic event times, progress basis. |
| `playback_committed_not_ack_probe` | Ensure delivery marker stays non-semantic. | Synthetic playback span reaches committed offset. | `observed_real` only for playback metadata if proof runs. | `PLAYBACK_COMMITTED` with `commit_basis`, no user acknowledgement, no commitment state mutation. |
| `truncate_mid_utterance_probe` | Validate ADR-003 truncate chain. | Playback span interrupted at mid offset. | `unknown` until playback proof runs. | distinct candidate, cutoff, and actual stop offsets; causal links. |
| `client_close_during_stream_probe` | Distinguish client close from provider cancellation. | Close client after first chunks. | `observed_degraded` if close observed. | client close reason, partial audio metadata, provider cancellation confirmed false/unknown. |
| `local_playback_stop_probe` | Validate local stop offset. | Stop playback without provider cancellation claim. | `unknown` until playback proof runs. | local stop command time, actual stop offset, final playback offset. |
| `provider_cancellation_probe` | Check whether provider confirms cancellation. | Future provider-supported cancel path if documented and approved. | `unknown` unless explicit provider confirmation exists. | cancellation request ref, provider confirmation flag, late audio behavior. |
| `timeout_probe` | Record timeout without state mutation. | Very short timeout or controlled delayed response. | `observed_degraded` or failed. | timeout_ms, retryable, partial output flag, no playback event synthesized from timeout. |
| `retryable_failure_probe` | Validate retry metadata shape. | Controlled retryable connection/task failure. | `observed_degraded` if retry path exercised. | retry count, retry reason, bounded retry policy, duplicate playback prevention. |
| `late_audio_after_truncate_probe` | Ensure late chunks do not revive stopped playback. | Truncate/stop while stream can still produce chunks. | `unknown` until proof runs. | late chunk count, ignored/stale label, playback span terminal state unchanged. |
| `partial_audio_replay_probe` | Prove replay uses metadata only. | Synthetic partial audio observation with refs. | `observed_real` for replay shape if proof runs. | contains no audio content, deterministic replay does not rerun provider. |
| `composer_approved_spoken_plan_probe` | Ensure TTS only consumes approved SpokenPlan. | SpokenPlan after coverage/truthfulness pass. | `unknown` until proof runs. | `spoken_plan_id`, approved check event id, no fact rewrite by TTS. |
| `risk_warning_spoken_plan_probe` | Ensure risk warning survives to playback request. | SpokenPlan with must-say risk warning. | `unknown` until proof runs. | coverage check ref, text ref or redacted summary, TTS request metadata only. |

## Input Fixture Policy

- Use only synthetic, deterministic, privacy-safe text.
- Prefer short neutral sentences and minimal SpokenPlan-like text.
- Use invented ids for sessions, turns, playback spans, spoken plans, and adapter requests.
- Do not use real user utterances, real private data, or provider-generated audio as a committed fixture.
- If a future local harness generates audio for playback debugging, keep it local-only and outside commit scope.
- Request metadata in reports should include provider alias, model alias, endpoint ref, voice id, format, sample rate, and timing buckets only.
- Text refs or redacted summaries are allowed when needed to prove Composer-to-Talker causality.

## Expected Observation Schema

A future spike-local harness, if approved, should emit metadata-only JSONL. Each line should be self-contained, schema-versioned, and safe to commit after review.

```json
{
  "schema_version": "tts_playback_proof_observation.v1",
  "contract_snapshot": "main@61e6afc",
  "case_id": "basic_short_synthesis",
  "observation_id": "obs_tts_playback_2026_05_12_001",
  "run_mode": "real_provider_or_synthetic_playback_metadata",
  "adapter_observation": {
    "adapter_type": "tts_talker",
    "provider": "dashscope",
    "model_name": "cosyvoice-v3-flash",
    "deployment_mode": "remote_api",
    "endpoint_ref": "dashscope-websocket-inference",
    "output_mode": "real"
  },
  "request_metadata": {
    "synthetic_input_ref": "text_ref://synthetic/tts/basic_short_synthesis",
    "voice_id": "longanyang",
    "format_requested": "mp3",
    "sample_rate_requested_hz": 22050,
    "word_timestamps_requested": true
  },
  "stream_metadata": {
    "first_audio_latency_ms": 556,
    "chunk_count": 15,
    "audio_byte_count": 36453,
    "stream_end_reason": "task_finished",
    "provider_cancel_confirmed": false
  },
  "playback_metadata": {
    "playback_span_id": "playback_synthetic_001",
    "playback_started": false,
    "progress_events": [],
    "committed_offset_ms": null,
    "actual_stop_offset_ms": null
  },
  "privacy": {
    "generated_audio_stored": false,
    "provider_response_body_stored": false,
    "request_secret_material_stored": false,
    "deterministic_replay_reruns_tts": false
  }
}
```

JSONL event observations should also allow event-shaped records:

```json
{
  "schema_version": "tts_playback_event_observation.v1",
  "case_id": "truncate_mid_utterance_probe",
  "event_name": "TTS_TRUNCATED",
  "source_module": "Talker",
  "required_fields_present": true,
  "payload": {
    "playback_span_id": "playback_synthetic_001",
    "actual_stop_offset_ms": 1280,
    "truncate_request_event_id": "evt_tts_truncate_requested_001",
    "final_playback_offset_ms": 1280
  },
  "raw_audio_required_for_replay": false
}
```

## Basic Synthesis Checks

The future proof should verify:

- The TTS request uses the expected provider alias, model alias, endpoint ref, voice id, format, and sample rate.
- The provider returns usable audio output for `basic_short_synthesis` and `longer_sentence_synthesis`.
- First-audio latency is measured from request start to first audio chunk.
- Total synthesis time is measured separately from playback duration.
- Audio duration is estimated from decoded metadata or safe local inspection, not by storing audio content.
- Word timestamp availability is recorded as alignment evidence only.
- A failed synthesis records failure category, retryability, timeout bound if present, and `output_mode`.

The existing run already supports `observed_real` for basic synthesis, first-audio latency bucket, streaming chunks, and word timestamp availability. The proof plan should not repeat that as playback truncate validation.

## Streaming Audio Output Checks

The future proof should verify:

- Binary audio chunks arrive before the provider task finish event for streaming cases.
- `first_audio_latency_ms`, `chunk_count`, `audio_byte_count`, and chunk cadence buckets are recorded.
- `stream_end_reason` distinguishes `task_finished`, `client_closed`, `provider_cancel_confirmed`, `timeout`, `provider_failed`, and `local_stop_without_provider_cancel`.
- Partial output is recorded with byte count and chunk count only.
- Late chunks after local stop or truncate are marked ignored/stale at the playback boundary.

Streaming audio output can be marked `observed_real` when directly observed, as in the existing run. That label must not be expanded into "playback progress validated" or "truncate validated."

## Playback Progress Checks

Talker/playback owns playback span state. A future proof should verify event-shaped metadata for:

| Event | Owner | Required fields to verify | Required notes |
| --- | --- | --- | --- |
| `PLAYBACK_SPAN_STARTED` | Talker/playback | `playback_span_id`, `audio_ref` or `tts_stream_ref` | Must reference approved SpokenPlan/check when semantic content comes from Composer. |
| `PLAYBACK_PROGRESS` | Talker/playback | `playback_span_id`, `playback_offset_ms` | Offset must be playback delivery progress, not provider chunk duration alone. |
| `PLAYBACK_COMMITTED` | Talker/playback | `playback_span_id`, `playback_offset_ms`, `commit_basis` | Delivery marker only; not user acknowledgement and not SemanticCommitment. |

Playback progress replay depends on offsets, durations, span ids, and refs. It does not depend on raw audio. Provider word timestamps can help alignment analysis, but they do not create playback progress or committed delivery.

## Truncate / Stop Checks

Interaction Controller owns truncate request. Talker/playback owns truncate completion. TTS adapter only provides audio stream/file metadata.

The future proof should verify:

| Event / condition | Owner | Required fields | Proof requirement |
| --- | --- | --- | --- |
| `BARGE_IN_CANDIDATE` | Duplex / realtime controller | `audio_span_id`, `playback_span_id`, `playback_offset_ms`, `echo_likelihood`, `vad_confidence`, `barge_in_confidence` | May be synthetic in this TTS proof, but offsets must remain distinct. |
| `INTERRUPT_CANDIDATE` | Interaction Controller | `playback_span_id`, `playback_offset_ms`, `policy_reason`, `confidence_summary` | Must be caused by barge-in or text-during-playback policy. |
| `TTS_TRUNCATE_REQUESTED` | Interaction Controller | `playback_span_id`, `cutoff_playback_offset_ms`, `interrupt_candidate_event_id` | Playback/interaction control event, not a model semantic event. |
| `TTS_TRUNCATED` | Talker/playback | `playback_span_id`, `actual_stop_offset_ms`, `truncate_request_event_id` | Must confirm actual local stop offset; provider close alone cannot satisfy it. |

The proof must preserve three offsets:

- Candidate-time `BARGE_IN_CANDIDATE.playback_offset_ms`.
- Interaction-time `TTS_TRUNCATE_REQUESTED.cutoff_playback_offset_ms`.
- Talker-confirmed `TTS_TRUNCATED.actual_stop_offset_ms`.

`TTS_TRUNCATE_REQUESTED` and `TTS_TRUNCATED` are playback/interaction control events. They are not model semantic events.

## Cancellation / Timeout / Retry / Late Audio Checks

The proof must distinguish:

| Observation class | Owner | Label guidance | Forbidden interpretation |
| --- | --- | --- | --- |
| Provider-side stream cancellation | Provider/TTS adapter observation | `observed_real` only if explicit provider confirmation exists; otherwise `unknown` | Do not infer from client close. |
| Client close | TTS adapter/client observation | `observed_degraded` | Do not treat as `TTS_TRUNCATED`. |
| Local playback stop | Talker/playback | `observed_real` only if local stop offset is measured | Do not treat as provider cancellation. |
| Interaction truncate | Interaction Controller plus Talker/playback | `observed_real` only with request and stop events | Do not treat as SemanticCommitment or user acknowledgement. |
| Timeout | TTS adapter/client observation | `observed_degraded` or failed | Do not synthesize playback events from timeout. |
| Retry | TTS adapter/client observation | `observed_degraded` until bounded retry proof exists | Do not create duplicate playback spans without Talker approval. |
| Late audio after stop/truncate | TTS adapter plus Talker/playback | ignored/stale metadata | Do not revive or advance a terminal playback span. |
| Partial audio | TTS adapter plus Talker/playback | `observed_degraded` unless intended partial playback is proven | Do not imply full delivery. |
| Format mismatch | TTS adapter validation | `ADAPTER_OUTPUT_DEGRADED` or failed-equivalent observation | Do not play with unverified assumptions. |

If a future run observes only client close or local stop, provider-confirmed cancellation must remain degraded / unknown.

## Audio Format / Duration / Alignment Checks

The future proof should record:

- `format_requested` and safe observed format metadata.
- `sample_rate_requested_hz` and safe observed sample rate metadata when locally inspected.
- `voice_id_requested` and acceptance/failure category.
- `audio_duration_ms_estimated`, with basis such as decoded header, provider metadata, or synthetic playback fixture.
- `first_audio_latency_ms` and `total_synthesis_latency_ms` as distinct fields.
- `playback_duration_ms` and `final_playback_offset_ms` as Talker/playback fields, not provider fields.
- `word_timestamp_events_observed` and optional timestamp count/bucket.
- `alignment_quality_label`, initially `unknown` unless separately evaluated.

Generated audio is not required for replay-safe reporting and must not be committed. Alignment metadata is advisory evidence for mapping text/audio; it is not delivery truth, acknowledgement, or semantic truth.

## SemanticCommitment / Composer / Talker Boundary Notes

- TTS output / playback committed is not user acknowledgement and is not SemanticCommitment.
- Thinker-as-Composer is responsible for spoken text realization from approved progress or SemanticCommitment inputs.
- TTS only turns an approved SpokenPlan/audio request into audio.
- TTS must not decide confirmation, tool authorization, task completion, resolved arguments, risk warnings, semantic close, assistant-directedness, interrupt, or barge-in.
- Composer must not rewrite `immutable_facts`, `must_say_fields`, `resolved_arguments`, tool status, risk warnings, or confirmation state.
- Talker can start playback only from an approved SpokenPlan/check path when the spoken text derives from SemanticCommitment.
- Talker/playback owns playback span state. Interaction Controller owns truncate request. TTS adapter only provides audio stream/file metadata.

## Replay-Safe Metadata Shape

Deterministic replay does not rerun TTS. It consumes recorded metadata or synthetic fixtures.

A replay-safe proof output should contain:

```json
{
  "proof_report_id": "tts_cosyvoice_playback_truncate_proof_2026_05_12",
  "contract_snapshot": "main@61e6afc",
  "candidate": {
    "provider": "dashscope",
    "model_name": "cosyvoice-v3-flash",
    "endpoint_ref": "dashscope-websocket-inference",
    "voice_id": "longanyang"
  },
  "case_results": [
    {
      "case_id": "basic_short_synthesis",
      "capability_labels": {
        "basic_synthesis": "observed_real",
        "streaming_output": "observed_real",
        "playback_progress": "unknown",
        "truncate": "unsupported_at_model_layer"
      },
      "metadata_refs": {
        "synthetic_input_ref": "text_ref://synthetic/tts/basic_short_synthesis",
        "tts_stream_ref": "tts_stream_ref://synthetic/report/basic_short_synthesis",
        "playback_span_id": null
      },
      "privacy": {
        "generated_audio_stored": false,
        "provider_response_body_stored": false,
        "secret_material_stored": false
      }
    }
  ],
  "replay": {
    "deterministic_replay_reruns_tts": false,
    "playback_progress_uses_offsets_and_refs": true,
    "raw_audio_required": false
  }
}
```

For a future JSONL file, recommended line types are:

- `adapter_synthesis_observation`
- `stream_chunk_summary`
- `playback_event_observation`
- `truncate_event_observation`
- `adapter_failure_observation`
- `privacy_review`
- `case_verdict`

Each line should carry `case_id`, `observation_id`, `contract_snapshot`, `output_mode`, and a privacy object.

## Trace / Privacy Boundary

- Store only synthetic refs, redacted summaries, event-shaped metadata, latency buckets, chunk counts, byte counts, duration buckets, format/sample-rate metadata, and failure categories.
- Do not store generated audio, provider response bodies, raw traces, local replay cache, real user input, secret-bearing request metadata, or large external content.
- If future local debug needs generated audio, it must remain local-only and outside commit scope.
- Replay fixtures must be synthetic / redacted / minimal.
- Deterministic replay must not rerun CosyVoice or any real provider.
- Playback progress replay depends on offsets, duration estimates, ids, and refs, not audio content.

## Fit to MVP-0 / MVP-1 / MVP-2 / MVP-3

| Slice | Fit | Notes |
| --- | --- | --- |
| MVP-0 | Required proof shape is directly relevant. | MVP-0 replay requires playback and truncate causal events. This proof stays research-only and does not modify fixtures. |
| MVP-1 | Mostly not applicable. | TTS does not advance `task_id`, `plan_version`, `task_event_seq`, stale evidence, or confirmation state. |
| MVP-2 | Supports Composer-to-Talker delivery only. | TTS may synthesize approved SpokenPlan text after coverage/truthfulness checks, but cannot modify facts or tool state. |
| MVP-3 | Candidate only after proof gaps close. | Basic synthesis and streaming output are promising; playback progress, truncate stop offset, retry/cancellation, and replay-safe eval shape remain required before integration consideration. |

## Risks / Gaps

- Existing run proves provider audio output, not Talker playback scheduling.
- Existing run proves word timestamp availability, not playback delivery truth.
- Existing run proves client close only as degraded cancellation evidence, not provider-confirmed cancellation.
- Provider/model-layer TTS truncate remains unsupported.
- Local playback stop offset is unproven.
- `PLAYBACK_PROGRESS` cadence and `PLAYBACK_COMMITTED` basis are unproven.
- `TTS_TRUNCATED(actual_stop_offset_ms)` is unproven.
- Late audio after truncate or local stop has not been tested.
- Retry behavior has not been exercised.
- Format and sample-rate variants beyond the observed `mp3` / `22050` path are not proven.
- Alignment quality is not evaluated beyond timestamp presence.
- Official model alias, supported voices, formats, rates, limits, and error categories can drift and need recheck before any future run.

## Recommendation

Keep DashScope / Bailian CosyVoice on the TTS shortlist as an audio synthesis provider candidate, with narrow labels:

- Mark basic synthesis, first-audio latency bucket, audio output, streaming audio chunks, observed voice id, observed format/sample rate path, and word timestamp events as `observed_real` based on the 2026-05-11 metadata-only run.
- Mark client-close behavior as `observed_degraded`.
- Mark provider-confirmed cancellation, playback progress, local stop offset, late audio handling, and retry behavior as `unknown` until directly verified.
- Mark provider/model-layer TTS truncate and pause/resume as `unsupported` for MVP purposes.

Do not move CosyVoice into MVP-3 consideration until a spike-local playback/truncate proof can show event-shaped playback progress, Interaction truncate request, Talker-confirmed stop offset, timeout/retry/cancellation categories, and replay-safe metadata output.

## Next Implementation Step, gated on human approval

If a human approves a follow-up implementation thread, create a spike-local harness design under a path such as:

```text
tools/model_spikes/tts_playback_eval/
```

The approved follow-up should remain isolated from the main runtime. It should emit metadata-only JSONL using the schema shape above, keep any generated audio local-only, use synthetic text fixtures, validate event-shaped required fields, and report per-case verdicts without changing `src/voice_agent/`, `tests/`, `docs/adr/`, or `docs/specs/`.

Until that approval exists, the next step is documentation review only.
