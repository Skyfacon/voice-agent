# TTS CosyVoice Profile Hardening Addendum

## Status

harden_next_with_truncate_caveat_research_addendum_metadata_only

This addendum applies `docs/research/model-spike-adapter-profile-hardening-checklist-2026-05-12.md` to the DashScope / Bailian CosyVoice TTS profile. It is research hardening only. It does not authorize runtime integration, provider execution, business adapter work, ADR/spec changes, or MVP scope expansion.

## Date

2026-05-12

## Contract Snapshot

- Default contract snapshot: `main@61e6afc`
- MVP-0 closeout reference: `22ddbf4 fix: harden mvp0 trace and replay safety`
- Playback and truncate contract reference: ADR-003 and `docs/specs/event-registry.md`
- Composer and SemanticCommitment reference: ADR-009
- Capability contract reference: ADR-011 and `docs/specs/model-adapter-capabilities.md`
- SlowTask lifecycle and confirmation reference: ADR-016
- Event and replay references: `docs/specs/event-registry.md` and `docs/specs/replay-spec.md`

## Scope

In scope:

- Harden the existing CosyVoice TTS profile from draft evidence toward a profile candidate.
- Apply the common hardening gates: identity, capability labels, error taxonomy, cancellation separation, playback/truncate boundary, replay-safe metadata, and owner-boundary assertions.
- Classify which evidence is `observed_real`, `observed_degraded`, `synthetic_eval`, `unknown`, or `unsupported`.

Out of scope:

- No provider execution in this step.
- No runtime adapter implementation.
- No changes to `src/voice_agent/`, `tests/`, `docs/adr/`, or `docs/specs/`.
- No generated audio, provider bodies, raw trace, local replay cache, real user input, or secret-bearing material.
- No claim that CosyVoice is ready for MVP-3 integration today.

## Source Evidence

- `docs/research/profiles/tts-cosyvoice-capability-profile-draft-2026-05-12.md`
- `docs/research/spikes/tts-dashscope-bailian-run-2026-05-11.md`
- `docs/research/spikes/tts-cosyvoice-playback-truncate-proof-plan-2026-05-12.md`
- `docs/research/spikes/tts-cosyvoice-playback-eval-dry-run-2026-05-12.md`
- `tools/model_spikes/tts_playback_eval/`
- `docs/research/model-spike-adapter-profile-hardening-checklist-2026-05-12.md`
- `docs/research/model-spike-phase-summary-2026-05-12.md`

Fresh local dry-run check for this addendum:

| command class | result |
| --- | --- |
| `tts_playback_eval dry-run --case-set full_synthetic` | 20 observations generated under `/private/tmp/.../hardening-full/observations.jsonl` |
| `tts_playback_eval validate` | `valid=true`, 20 observations, zero errors |

## Hardening Decision

Recommendation: `harden_next` with truncate caveat.

Reasoning:

- CosyVoice has observed real evidence for basic synthesis, streaming audio output, word timestamp metadata, and first-audio latency buckets.
- The 2026-05-11 run directly observed successful short, longer, and SpokenPlan-like synthesis without storing generated audio.
- The spike-local playback eval adds repeatable metadata shape for playback progress, committed delivery, truncate chain, local stop, late audio, partial audio, timeout, retryable failure, format mismatch, and Composer-to-Talker boundary cases.
- The strongest gap remains playback and truncate: provider chunks, client close, and stream end events do not prove `PLAYBACK_PROGRESS`, `PLAYBACK_COMMITTED`, or `TTS_TRUNCATED`.

This is not `ready_for_mvp3`. It is a research signal that CosyVoice can remain on the TTS shortlist while Talker/playback and Interaction boundaries stay explicit.

## Candidate Identity Disposition

| field | hardening label | disposition |
| --- | --- | --- |
| Adapter role | `observed_real` | TTS / Talker audio-provider candidate. |
| Provider | `observed_real` | DashScope / Bailian. |
| Model alias | `observed_real_needs_recheck` | `cosyvoice-v3-flash` was observed on 2026-05-11; re-pin before any future live hardening run. |
| Voice id | `observed_real_narrow` | `longanyang` was observed; broader voice catalog behavior remains unknown. |
| Deployment mode | `observed_real` | Remote WebSocket inference surface. |
| Endpoint ref | `observed_real` | DashScope WebSocket inference ref, with no secret-bearing values. |
| Health observation | `observed_real` | Normal synthesis cases finished successfully. |
| Output label | `observed_real_or_degraded` | Real for completed audio chunks; degraded for client-close or partial-output observations. |
| Latency class | `observed_real_bucket` | First audio was observed around 493ms to 705ms for the synthetic run set. |

CosyVoice / TTS is audio synthesis evidence/provider only. It is not a turn ingress owner, not an Interaction Controller, not a Router, not SlowTask, and not a semantic truth owner.

## Capability Disposition

| capability area | hardening label | disposition |
| --- | --- | --- |
| Basic synthesis | `observed_real` | Completed synthesis observed for short and longer synthetic prompts. |
| Audio output | `observed_real` | Successful cases produced binary audio chunks. |
| Streaming output | `observed_real` | Chunked WebSocket audio output was directly observed. |
| First-audio latency | `observed_real_bucket` | Run-specific bucket only; not a general product SLO. |
| Word timestamp / alignment metadata | `observed_real` | Useful alignment metadata, not playback delivery truth. |
| Incremental text submission | `observed_real` | Observed text submission over the TTS stream; this is not audio input. |
| Voice/style request acceptance | `observed_degraded` | Request acceptance observed; quality and catalog coverage remain unproven. |
| Format and sample rate | `observed_real_narrow` | `mp3` and `22050` were requested in the observed run; broader matrix remains unknown. |
| Client close during stream | `observed_degraded` | Client close after initial audio was observed; provider-confirmed cancellation was not. |
| Playback progress | `synthetic_eval` | Dry-run covers event shape only. Real playback scheduling is unproven. |
| Playback committed delivery marker | `synthetic_eval` | Dry-run covers field shape and non-ack boundary only. |
| Truncate chain | `synthetic_eval` | Dry-run covers request/confirmation shape only. Real stop-offset proof is missing. |
| Provider-confirmed cancellation | `unknown` | Must remain unknown unless directly observed. |
| Retry behavior | `unknown` | Retryable provider failures were not live-exercised. |
| Provider/model-layer TTS truncate | `unsupported` | ADR-003 truncate is playback/interaction control, not a model capability. |
| Pause/resume | `unsupported` | MVP non-goal and not observed. |
| Semantic close and directedness | `unsupported` | Outside TTS authority. |
| Tool calling, confirmation, task completion | `unsupported` | Outside TTS authority. |
| Text/output length limits | `unknown` | Must be rechecked on any live hardening day. |

## Checklist Result

| gate | status | notes |
| --- | --- | --- |
| Research boundary | pass | Addendum stays under `docs/research/`. |
| Candidate identity | partial pass | Identity is recorded; current model alias, voice catalog, and service limits still need recheck before live hardening. |
| Capability matrix coverage | partial pass | Core TTS capabilities are labeled; playback/truncate, cancellation, retry, and broader format/rate coverage remain gaps. |
| Error taxonomy | partial pass | Client close, timeout, retryable failure, late audio, partial audio, and format mismatch have metadata shapes; live provider taxonomy remains incomplete. |
| Cancellation separation | pass as boundary, gap as capability | Client close and local stop are separated from provider-confirmed cancellation, which remains unknown. |
| Playback/truncate separation | pass as boundary, gap as proof | Provider chunks do not create playback progress or truncate confirmation. |
| Replay posture | pass | Dry-run and profile require metadata/synthetic fixture consumption only. |
| Owner boundaries | pass | TTS remains audio synthesis evidence, not semantic or control authority. |
| MVP-3 readiness | not ready | Integration requires a later approved branch, Talker/playback proof, health/error policy, and replay/eval fixtures. |

## Playback / Truncate Boundary Addendum

Required owner boundaries:

- Talker/playback owns `PLAYBACK_SPAN_STARTED`.
- Talker/playback owns `PLAYBACK_PROGRESS`.
- Talker/playback owns `PLAYBACK_COMMITTED`.
- Interaction Controller owns `TTS_TRUNCATE_REQUESTED`.
- Talker/playback owns `TTS_TRUNCATED` and must provide `actual_stop_offset_ms`.

Required interpretation:

- `PLAYBACK_COMMITTED` is a playback delivery marker only.
- TTS output / playback committed is not user acknowledgement.
- TTS output / playback committed is not SemanticCommitment.
- `TTS_TRUNCATE_REQUESTED` and `TTS_TRUNCATED` are playback/interaction control events, not model semantic events.
- Provider stream close, client close, request timeout, or local request abort cannot be recorded as `TTS_TRUNCATED`.
- If only client close or local stop is observed, provider cancellation remains degraded or unknown.
- Playback progress replay depends on offsets, duration, ids, and refs. It does not depend on generated audio content.

## Error / Retry / Cancellation Addendum

Required hardening behavior:

- Timeout becomes adapter failure or degraded-output metadata and cannot imply playback stop.
- Retryable failure records retry count, retry reason, and final outcome.
- Exhausted retry budget becomes degraded/failure metadata and cannot create playback events.
- Client close is local client-control metadata, not provider-confirmed cancellation.
- Local playback stop is Talker/playback metadata, not model cancellation.
- Interaction truncate starts at `TTS_TRUNCATE_REQUESTED` and completes only when Talker/playback reports `TTS_TRUNCATED`.
- Late audio after stop/truncate is stale or ignored for the stopped playback span.
- Partial audio is recorded with chunk count, byte count, timing bucket, and stream end reason only.
- Format or sample-rate mismatch is degraded/failure metadata and must not be hidden by playback success.

## Composer / Talker Input Boundary

Thinker-as-Composer is responsible for spoken text realization. TTS is responsible only for synthesizing audio from an approved SpokenPlan or equivalent audio request.

Required future input refs:

- spoken plan id or redacted synthetic text ref
- Composer coverage check ref when facts derive from SemanticCommitment
- progress truthfulness check ref when spoken progress claims are present
- voice id, format, sample rate, and output mode metadata
- adapter request id and playback span id

Forbidden TTS behavior:

- TTS must not decide confirmation.
- TTS must not decide tool authorization.
- TTS must not decide task completion.
- TTS must not decide resolved arguments.
- TTS must not remove or reinterpret risk warnings.
- TTS must not decide interrupt, barge-in, semantic close, or assistant-directedness.
- TTS must not bypass Interaction Controller, Playback owner, or Event Journal.

## Replay-Safe Metadata Shape

A hardened TTS profile should use a metadata shape like:

```json
{
  "profile_id": "tts_cosyvoice_hardening_2026_05_12",
  "contract_snapshot": "main@61e6afc",
  "candidate": {
    "adapter_type": "tts_talker",
    "provider": "dashscope",
    "model_name_observed": "cosyvoice-v3-flash",
    "model_alias_recheck_required": true,
    "voice_id_observed": "longanyang",
    "deployment_mode": "remote_api",
    "endpoint_ref": "dashscope-websocket-inference",
    "output_mode": "real_or_degraded"
  },
  "synthesis": {
    "basic_synthesis_label": "observed_real",
    "streaming_output_label": "observed_real",
    "first_audio_latency_label": "observed_real_bucket",
    "word_timestamp_label": "observed_real",
    "generated_audio_stored": false
  },
  "stream_metadata": {
    "format_requested": "mp3",
    "sample_rate_requested_hz": 22050,
    "chunk_count": 15,
    "audio_byte_count": 36453,
    "first_audio_latency_ms": 556,
    "stream_end_reason": "task_finished",
    "provider_cancel_confirmed": "unknown_or_false"
  },
  "playback_boundary": {
    "playback_progress_label": "synthetic_eval_until_real_playback_proof",
    "truncate_chain_label": "synthetic_eval_until_real_stop_offset_proof",
    "actual_stop_offset_source": "talker_playback_only"
  },
  "privacy": {
    "provider_body_stored": false,
    "raw_trace_stored": false,
    "local_replay_cache_stored": false,
    "real_user_input_stored": false,
    "secret_bearing_material_stored": false,
    "deterministic_replay_reruns_provider": false
  }
}
```

Generated audio is not a replay-safe artifact and must not be committed. Deterministic replay must not rerun TTS; it consumes recorded metadata or synthetic fixtures only.

## Event Mapping Addendum

The hardened profile should be able to map future observations to existing event families without creating new event names:

| condition | future event-compatible mapping | state effect |
| --- | --- | --- |
| Successful synthesis | TTS stream/file ref plus adapter output metadata | No playback event until Talker starts playback. |
| First audio observed | timing metadata on TTS observation | No user acknowledgement or semantic commitment. |
| Playback started | `PLAYBACK_SPAN_STARTED` from Talker/playback | Playback state starts. |
| Playback progress | `PLAYBACK_PROGRESS` from Talker/playback | Delivery progress only. |
| Playback committed | `PLAYBACK_COMMITTED` from Talker/playback | Delivery marker only, no acknowledgement. |
| Interaction truncate request | `TTS_TRUNCATE_REQUESTED` from Interaction Controller | Request to stop playback. |
| Playback stopped | `TTS_TRUNCATED` from Talker/playback with actual stop offset | Stop confirmed for playback span. |
| Client close or provider stream close | adapter degraded/failure metadata | Not truncate confirmation. |
| Late audio | stale or ignored output metadata | No state revival. |
| Partial audio | degraded output metadata | No task state advancement. |

## MVP Fit

| slice | addendum fit |
| --- | --- |
| MVP-0 | Supports future real TTS adapter profile shape; current mock Talker remains the owner of playback events. |
| MVP-1 | No direct SlowTask fit; TTS must not advance task state or confirmation state. |
| MVP-2 | Can synthesize approved Composer SpokenPlans after coverage/truthfulness gates, but cannot rewrite facts. |
| MVP-3 | Candidate for TTS integration consideration only after playback/truncate and provider health/error gaps are closed in an approved integration lane. |

## Remaining Blockers

- Current model alias, service limits, voice catalog, format matrix, and sample-rate matrix must be rechecked on any live hardening day.
- Provider-confirmed cancellation remains unknown.
- Retry behavior under live transient provider failures remains unknown.
- Playback progress and actual stop offset are synthetic-only in this research lane.
- Late audio after local stop/truncate is synthetic-only.
- Word timestamp quality is not validated as playback delivery truth.
- No runtime replay/eval fixture has been approved in this research lane.

## Recommendation

Keep DashScope / Bailian CosyVoice as `harden_next` for TTS profile hardening, with truncate caveat.

Do not start runtime integration from this addendum. The next research step is to apply the same addendum pattern to ASR Qwen-ASR while keeping realtime microphone input, silence/non-speech risk, timestamp normalization, and provider cancellation gaps explicit.
