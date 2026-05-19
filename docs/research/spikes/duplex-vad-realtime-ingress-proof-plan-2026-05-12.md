# Duplex / VAD Realtime Ingress Proof Plan

## Status

planned_metadata_only_proof

This document is research planning only. It does not authorize runtime integration, real business adapter work, main harness code changes, provider calls, ADR changes, event registry changes, replay spec changes, or MVP scope expansion.

## Date

2026-05-12

## Contract Snapshot

- Default contract snapshot: `main@61e6afc`
- MVP-0 closeout reference: `22ddbf4 fix: harden mvp0 trace and replay safety`
- Duplex / Interaction boundary: ADR-001
- Playback / truncate boundary: ADR-003
- Adapter capability boundary: ADR-011 and `docs/specs/model-adapter-capabilities.md`
- Event and replay boundary: `docs/specs/event-registry.md` and `docs/specs/replay-spec.md`

## Scope

This plan defines the remaining realtime ingress evidence required before local WebRTC VAD / Duplex can move from repeatable synthetic harness evidence toward adapter profile hardening.

In scope:

- Realtime audio ingress proof requirements for local Duplex / VAD.
- Live-frame timing, scheduler, callback, and buffering metadata.
- Speech start, speech end, silence, non-speech, clipped speech, and short backchannel checks.
- Playback-reference and echo-overlap checks needed before target-valid barge-in claims.
- Event-shaped proof requirements for `AUDIO_SPAN_STARTED`, `SPEECH_START_DETECTED`, `SPEECH_END_DETECTED`, `BARGE_IN_CANDIDATE`, `INTERRUPT_CANDIDATE`, `TTS_TRUNCATE_REQUESTED`, and `TTS_TRUNCATED`.
- Boundary notes for assistant-directedness, semantic close, ASR, Thinker, Interaction Controller, Talker/playback, and deterministic replay.
- Metadata-only JSONL shape for a future approved proof run.

Out of scope:

- No changes to `src/voice_agent/`, `tests/`, `docs/adr/`, or `docs/specs/`.
- No main runtime wiring.
- No real business adapter.
- No provider call.
- No new code in this thread.
- No raw audio, raw trace, local replay cache, real user recording, secret, request header, or sensitive access artifact committed.
- No claim that WebRTC VAD provides semantic close, assistant-directedness, user acknowledgement, SemanticCommitment, task completion, confirmation, or tool authorization.

## Source Evidence

Primary Duplex/VAD evidence:

- `docs/research/spikes/duplex-vad-local-run-2026-05-11.md`
- `docs/research/spikes/duplex-vad-webrtcvad-local-run-2026-05-11.md`
- `docs/research/spikes/duplex-vad-webrtcvad-harness-plan-2026-05-11.md`
- `docs/research/spikes/duplex-vad-webrtcvad-harness-run-2026-05-11.md`
- `docs/research/spikes/duplex-capability-spike-2026-05-09.md`

Coordination evidence:

- `docs/research/model-spike-phase-summary-2026-05-11.md`
- `docs/research/model-spike-execution-plan.md`
- `docs/research/model-spike-integration-ledger.md`
- `docs/research/model-spike-plan.md`
- `docs/research/model-selection.md`

Contract evidence:

- `AGENTS.md`
- `docs/adr/ADR-001 Duplex Boundary and Interaction Controller.md`
- `docs/adr/ADR-003 Barge-in and TTS Truncate Contract.md`
- `docs/adr/ADR-011 Model Adapter Capability Contract.md`
- `docs/specs/model-adapter-capabilities.md`
- `docs/specs/event-registry.md`
- `docs/specs/replay-spec.md`

Current evidence labels:

| Evidence item | Current label | Notes |
| --- | --- | --- |
| WebRTC VAD frame decisions on synthetic PCM | `observed_real` | Existing harness emitted repeatable 10/20/30 ms, mode 0/2/3 frame observations. |
| 20 ms / mode 2 speech-start synthetic emit latency | `observed_real` for synthetic PCM | Existing harness observed 40 ms algorithmic emit latency; live device latency remains unknown. |
| Silence-only synthetic behavior | `observed_real` | Existing harness kept silence silent. |
| Tone / white-noise false-positive risk | `observed_degraded` | Existing harness observed non-speech false positives. |
| Playback-only raw mic VAD behavior | `observed_degraded` risk | Raw playback-only confidence reached 1.000 in harness reports. |
| Idealized playback-reference residual blocking | `observed_degraded` | Useful interface-shape evidence, not real AEC proof. |
| User speech over synthetic playback residual | `observed_real` for synthetic residual | Candidate offset evidence exists under idealized subtraction. |
| Natural speech quality | `unknown` | No real user recording or robust generated natural speech fixture was used. |
| Live microphone capture latency | `unknown` | Existing runs were offline/in-memory. |
| Live playback-device echo behavior | `unknown` | Existing echo handling was idealized. |
| Real AEC / residual estimator | `unknown` | Not validated. |
| `semantic_close` from WebRTC VAD | `unsupported` | WebRTC VAD cannot infer semantic completeness. |
| `assistant_directedness` from WebRTC VAD | `unsupported` | WebRTC VAD cannot infer addressee. |
| `TTS_TRUNCATED` from VAD | `unsupported` | Talker/playback owns actual stop confirmation. |

## Candidate Identity

| Field | Planned value | Evidence label | Notes |
| --- | --- | --- | --- |
| `adapter_type` | `duplex_model` / local realtime audio gate candidate | `observed_real` for harness role | Research profile shape only, not runtime adapter id. |
| `provider` | `local_webrtcvad` | `observed_real` | Existing harness used local package in a temporary environment. |
| `model_name` | `webrtcvad==2.0.10` | `observed_real` | Pin only if a future approved run uses the same dependency. |
| `deployment_mode` | `local` | `observed_real` | No remote provider required. |
| `endpoint_ref` | `local-process-no-endpoint` | `observed_real` | No external endpoint. |
| `sample_rate_hz` | `16000` primary | `observed_real` | Existing harness used 16-bit mono PCM at 16 kHz. |
| `frame_ms` | `20` primary, with `10/20/30` comparison | `observed_real` | 20 ms / mode 2 remains the practical default candidate. |
| `mode` | `2` primary, with `0/2/3` comparison | `observed_real` | Mode 3 can be conservative but may affect short utterances. |
| `output_mode` | `real` / `degraded` / `unknown` per field | case-specific | Synthetic VAD decisions are real; live ingress remains unknown until proven. |

WebRTC VAD is a local speech-activity evidence provider. It is not the Interaction Controller, not ASR, not Thinker, not Router, not SlowTask, not Talker/playback, and not a semantic truth owner.

## Proof Goals

1. Define what evidence is still missing before Duplex/VAD profile hardening.
2. Preserve the distinction between synthetic/offline VAD proof and realtime device ingress proof.
3. Validate live-frame timing metadata without committing raw audio.
4. Validate `SPEECH_START_DETECTED` and `SPEECH_END_DETECTED` required fields from realtime frame offsets.
5. Validate `BARGE_IN_CANDIDATE` shape with playback reference, echo likelihood, VAD confidence, and barge-in confidence.
6. Validate that Interaction Controller, not Duplex, owns `INTERRUPT_CANDIDATE` and `TTS_TRUNCATE_REQUESTED`.
7. Validate that Talker/playback, not Duplex, owns `TTS_TRUNCATED(actual_stop_offset_ms)`.
8. Define false-positive, false-negative, late-frame, overrun, underflow, and clock-drift metadata.
9. Keep deterministic replay metadata-only and prevent replay from rerunning VAD.

## Non-Goals

- No runtime integration or adapter implementation.
- No real user recording collection.
- No raw audio committed.
- No ASR transcript quality evaluation.
- No Thinker SemanticFrame evaluation.
- No semantic close or assistant-directedness claim from WebRTC VAD.
- No task cancellation, confirmation, tool authorization, or SemanticCommitment decision.
- No provider-side model cancellation, TTS synthesis, or playback-stop implementation.
- No target-valid barge-in claim without playback reference and Talker stop-offset proof.

## Synthetic / Controlled Case Matrix

| case_id | Purpose | Input / setup | Current label | Required future observations |
| --- | --- | --- | --- | --- |
| `live_silence_baseline` | Ensure idle capture does not open turns. | Live or loopback silence window. | `unknown` | audio span metadata, frame count, no speech candidate, ambient noise bucket. |
| `live_short_command` | Measure realtime speech-start latency. | Controlled short synthetic or human-approved local phrase, metadata only. | `unknown` | first active frame, emit latency, audio sample offset, callback latency bucket. |
| `live_short_backchannel` | Catch brief barge-in-like utterances. | Short "yes/no/wait" style local controlled input. | `unknown` | start detection, missed-speech flag, min duration sensitivity. |
| `live_clipped_start` | Detect speech with clipped onset. | Controlled clip or generated fixture injected at capture boundary. | `unknown` | start offset error, debounce impact, degradation label. |
| `live_speech_end_hangover` | Measure end detection and hangover. | Speech then silence. | `unknown` | end offset, silence duration, hangover budget, end emit latency. |
| `live_noise_non_speech` | Quantify false-positive risk. | Fan/keyboard/tone/noise fixture or safe controlled environment metadata. | `unknown` | false positive count, confidence bucket, low-confidence action. |
| `playback_only_echo` | Verify playback reference blocks self-audio. | Assistant playback without user speech. | `unknown` | raw mic activity, playback reference ref, residual bucket, no target-valid barge-in if no reference. |
| `user_speech_over_playback` | Validate barge-in candidate under overlap. | Controlled user speech while playback active. | `unknown` | `BARGE_IN_CANDIDATE` fields, candidate offset, echo likelihood, barge-in confidence. |
| `near_end_barge_in` | Check weak residual near playback end. | Short input over trailing playback. | `unknown` | weak-confidence policy, held/rejected/accepted candidate result. |
| `background_non_assistant_speech` | Preserve directedness boundary. | Background voice-like audio or synthetic substitute. | `unknown` | VAD evidence only; directedness remains `UNKNOWN` unless separate approved evidence exists. |
| `speech_not_semantically_closed` | Preserve semantic-close boundary. | Incomplete phrase or synthetic substitute. | `unknown` | VAD end is not semantic close; Interaction may hold only by explicit policy/evidence. |
| `text_during_playback_control` | Ensure text path also uses Interaction policy. | Synthetic text input while playback active. | `not_applicable_to_vad` | no audio span invented; Interaction owns interrupt decision. |
| `audio_callback_overrun` | Record realtime scheduling failure. | Inject or observe delayed callback. | `unknown` | overrun count, dropped frame count, degraded output. |
| `device_clock_drift` | Detect capture/playback clock mismatch. | Compare capture offsets with playback offsets. | `unknown` | drift bucket, alignment confidence, degrade if high. |
| `late_frame_after_span_end` | Ensure late audio does not reopen committed span. | Delayed frame after end. | `unknown` | late frame label, ignored/stale metadata, no hidden state mutation. |
| `barge_in_to_truncate_chain` | Validate end-to-end control shape. | Synthetic or controlled overlap plus playback stop metadata. | `unknown` | distinct `BARGE_IN_CANDIDATE`, `INTERRUPT_CANDIDATE`, `TTS_TRUNCATE_REQUESTED`, and `TTS_TRUNCATED` offsets. |

## Input Fixture Policy

- Prefer synthetic or controlled local inputs with metadata-only reports.
- Do not commit raw audio, raw local traces, or real user recordings.
- If generated or captured audio is needed for debugging, keep it under `/private/tmp` or another local-only ignored location and remove it after summarization.
- Use invented ids for `session_id`, `audio_span_id`, `playback_span_id`, `turn_id`, and event ids.
- Store only frame counts, offsets, latency buckets, confidence buckets, false-positive/false-negative categories, and refs.
- Do not store spoken content unless it is synthetic and redacted; Duplex proof should not need transcripts.
- Playback references must be metadata refs or synthetic hashes, not raw playback audio.

## Expected Observation Schema

A future approved proof should emit metadata-only JSONL. Each line should be safe to commit after review and should not be a runtime event.

```json
{
  "schema_version": "duplex_realtime_ingress_observation.v1",
  "contract_snapshot": "main@61e6afc",
  "case_id": "user_speech_over_playback",
  "observation_id": "obs_duplex_realtime_2026_05_12_001",
  "candidate": {
    "adapter_type": "duplex_model",
    "provider": "local_webrtcvad",
    "model_name": "webrtcvad==2.0.10",
    "deployment_mode": "local",
    "output_mode": "real_or_degraded"
  },
  "audio_input": {
    "audio_span_id": "audio_synthetic_001",
    "sample_rate_hz": 16000,
    "sample_format": "pcm_s16le_mono",
    "frame_ms": 20,
    "frame_count": 95,
    "raw_audio_stored": false
  },
  "timing": {
    "capture_start_monotonic_ms": 100000,
    "first_speech_sample_offset": 16000,
    "speech_start_emit_latency_ms": 40,
    "callback_overrun_count": 0,
    "dropped_frame_count": 0,
    "clock_drift_bucket_ms": "0_to_20"
  },
  "duplex_evidence": {
    "vad_confidence": 0.269,
    "echo_likelihood": 0.18,
    "barge_in_confidence": 0.73,
    "detection_basis": "webrtcvad_frame_mode_2_with_playback_reference_residual"
  },
  "playback_context": {
    "playback_span_id": "playback_synthetic_001",
    "playback_reference_ref": "playback_ref://synthetic/realtime/001",
    "candidate_playback_offset_ms": 1040,
    "raw_playback_audio_stored": false
  },
  "privacy": {
    "contains_raw_audio": false,
    "contains_real_user_input": false,
    "contains_raw_trace": false,
    "contains_secrets": false,
    "deterministic_replay_reruns_vad": false
  }
}
```

Event-shaped observations may be represented separately:

```json
{
  "schema_version": "duplex_realtime_event_shape_observation.v1",
  "case_id": "barge_in_to_truncate_chain",
  "event_name": "BARGE_IN_CANDIDATE",
  "event_owner": "Duplex / Realtime Audio Controller",
  "required_fields_present": true,
  "payload": {
    "audio_span_id": "audio_synthetic_001",
    "playback_span_id": "playback_synthetic_001",
    "playback_offset_ms": 1040,
    "echo_likelihood": 0.18,
    "vad_confidence": 0.269,
    "barge_in_confidence": 0.73,
    "playback_reference_ref": "playback_ref://synthetic/realtime/001"
  },
  "raw_audio_required_for_replay": false
}
```

## Realtime Ingress Checks

The future proof should verify:

- `AUDIO_SPAN_STARTED` can be represented with `audio_span_id`, `input_modality=audio`, `audio_sample_offset`, and `audio_format_ref`.
- `AUDIO_CHUNK_RECEIVED`-like local observations can track chunk index, sample offset, chunk duration, dropped frames, and callback timing without entering a shareable fixture as raw chunks.
- `SPEECH_START_DETECTED` carries `audio_span_id`, `audio_sample_offset`, `vad_confidence`, and `detection_basis`.
- `SPEECH_END_DETECTED` carries `audio_span_id`, `audio_sample_offset`, `vad_confidence`, `silence_duration_ms`, and `detection_basis`.
- Live emission latency is measured separately from frame offset accuracy.
- Device/callback latency is not hidden inside the VAD algorithmic latency number.
- Low-confidence ingress can be represented without committing raw audio.

Existing synthetic harness results support WebRTC VAD frame evidence. They do not prove live microphone ingress latency, live callback scheduling, or device echo behavior.

## VAD Frame / Latency Checks

The future proof should preserve the existing matrix while adding realtime timing:

- Keep 20 ms / mode 2 as the default candidate.
- Retain 10/20/30 ms and mode 0/2/3 comparison for repeatability.
- Record debounce frames, hangover frames, frame duration, and sample rate.
- Record start emit latency, end emit latency, end hangover, and offset error.
- Record false-positive and false-negative categories.
- Record CPU/runtime timing bucket if a future harness runs live processing.
- Mark live-device latency as `unknown` until measured with a real capture path.

Target interpretation:

- Synthetic 40 ms speech-start emit latency is promising algorithmic evidence.
- It is not an end-to-end `speech_start <=150ms` SLO proof.
- SLO-like claims require capture callback, buffering, scheduler, and event append timing.

## Playback Reference / Echo Checks

The proof must treat playback reference as mandatory for target-valid barge-in.

Required observations:

- `playback_span_id` active at candidate time.
- `playback_reference_ref` present for playback-overlap cases.
- Raw mic activity bucket before reference handling.
- Residual activity bucket after reference handling.
- `echo_likelihood` or `echo_likelihood_mode`.
- VAD confidence and barge-in confidence computed after echo handling.
- Explicit degraded label if playback reference is missing.

Rules:

- Playback-only raw VAD activity is a false barge-in risk, not user speech.
- Idealized subtraction is degraded interface evidence, not real AEC proof.
- Without playback reference, overlap cases can be demo/mock only and cannot validate target architecture.
- WebRTC VAD alone must not trigger `TTS_TRUNCATE_REQUESTED`.

## Barge-in / Truncate Chain Checks

A target-shaped proof should preserve ownership:

| Event | Owner | Required fields | Boundary |
| --- | --- | --- | --- |
| `BARGE_IN_CANDIDATE` | Duplex / Realtime Audio Controller | `audio_span_id`, `playback_span_id`, `playback_offset_ms`, `echo_likelihood`, `vad_confidence`, `barge_in_confidence`, optional `playback_reference_ref` | Candidate evidence only. |
| `INTERRUPT_CANDIDATE` | Interaction Controller | `playback_span_id`, `playback_offset_ms`, `policy_reason`, `confidence_summary`, optional `audio_span_id` | Deterministic policy output. |
| `TTS_TRUNCATE_REQUESTED` | Interaction Controller | `playback_span_id`, `cutoff_playback_offset_ms`, `interrupt_candidate_event_id`, optional `audio_span_id` | Playback control request, not VAD output. |
| `TTS_TRUNCATED` | Talker/playback | `playback_span_id`, `actual_stop_offset_ms`, `truncate_request_event_id`, optional `final_playback_offset_ms` | Actual local stop confirmation. |

The proof must keep these offsets distinct:

- `BARGE_IN_CANDIDATE.playback_offset_ms`
- `INTERRUPT_CANDIDATE.playback_offset_ms`
- `TTS_TRUNCATE_REQUESTED.cutoff_playback_offset_ms`
- `TTS_TRUNCATED.actual_stop_offset_ms`

VAD cannot confirm `TTS_TRUNCATED`, cannot decide playback stop success, and cannot convert provider/client cancellation into playback truncate.

## Directedness / Semantic Close Boundary

WebRTC VAD does not provide `assistant_directedness` or `semantic_close`.

The future proof should record:

- `supports_assistant_directedness=unsupported` for WebRTC VAD itself.
- `supports_semantic_close=unsupported` for WebRTC VAD itself.
- Any `DIRECTEDNESS_CANDIDATE`, `NON_ASSISTANT_CANDIDATE`, or `SEMANTIC_CLOSE_CANDIDATE` must come from a separate approved Duplex capability or explicit rule/mock policy, not from raw VAD activity.
- Interaction Controller may hold, reject, or accept by deterministic policy, but it must not pretend VAD is semantic understanding.
- ASR/Thinker outputs occur only after `TURN_INGRESS_COMMITTED`; they cannot be prerequisites for first ingress commit.

## Failure / Degradation Checks

The proof should classify:

| Failure / degradation | Required metadata | Expected handling |
| --- | --- | --- |
| Missing playback reference during active playback | `missing_capability=playback_reference`, overlap case id | block target-valid barge-in claim or mark demo/mock. |
| Callback overrun | overrun count, max callback delay bucket | mark `ADAPTER_OUTPUT_DEGRADED`-equivalent observation. |
| Dropped frame | dropped count, affected offsets | degrade timing confidence. |
| Clock drift | drift bucket, basis | degrade playback alignment / echo confidence. |
| Noise false positive | case id, confidence bucket | record false-positive risk; avoid automatic turn commit. |
| Missed short utterance | expected window, no candidate | record false negative; tune only in future approved harness. |
| Late frame after span end | late frame count, span id | ignore or mark stale; do not reopen committed span silently. |
| Audio format mismatch | expected vs observed format metadata | fail/degrade before VAD frame decisions. |
| VAD dependency unavailable | dependency status | degrade to existing synthetic/metadata baseline only. |

Local VAD frame processing should not retry state transitions. It should process fresh frames or stop the stream; retries are relevant to setup/dependency/probe execution, not to canonical ingress events.

## Replay-Safe Metadata Shape

Deterministic replay must not rerun WebRTC VAD. It should consume recorded metadata or synthetic fixture data.

Recommended proof summary shape:

```json
{
  "proof_report_id": "duplex_vad_realtime_ingress_proof_2026_05_12",
  "contract_snapshot": "main@61e6afc",
  "candidate": {
    "provider": "local_webrtcvad",
    "model_name": "webrtcvad==2.0.10",
    "deployment_mode": "local",
    "primary_frame_ms": 20,
    "primary_mode": 2
  },
  "case_results": [
    {
      "case_id": "playback_only_echo",
      "capability_labels": {
        "vad_frame_decision": "observed_real_for_synthetic_or_controlled_input",
        "playback_reference_required": "observed_degraded_risk",
        "real_aec": "unknown",
        "semantic_close": "unsupported",
        "assistant_directedness": "unsupported",
        "tts_truncate_confirmation": "unsupported_at_vad_layer"
      },
      "metadata_refs": {
        "audio_span_id": "audio_synthetic_001",
        "playback_span_id": "playback_synthetic_001",
        "playback_reference_ref": "playback_ref://synthetic/realtime/001"
      },
      "privacy": {
        "raw_audio_stored": false,
        "raw_trace_stored": false,
        "real_user_input_stored": false
      }
    }
  ],
  "replay": {
    "deterministic_replay_reruns_vad": false,
    "raw_audio_required": false,
    "uses_recorded_offsets_and_refs": true
  }
}
```

Recommended JSONL line types:

- `audio_capture_observation`
- `vad_frame_summary`
- `speech_start_event_shape`
- `speech_end_event_shape`
- `barge_in_candidate_event_shape`
- `interaction_truncate_chain_shape`
- `failure_degradation_observation`
- `privacy_review`
- `case_verdict`

## Trace / Privacy Boundary

- Store only synthetic/control metadata, offsets, buckets, confidence summaries, refs, and verdict labels.
- Do not store raw audio, raw traces, local replay cache, real user recordings, secrets, or request/header metadata.
- Keep any future local audio files under `/private/tmp` or another ignored local-only path.
- Do not commit playback audio, mic capture audio, residual audio, or generated speech files.
- Shareable reports must use synthetic/redacted/minimal metadata.
- Replay does not load raw audio and does not rerun VAD by default.

## Fit to MVP-0 / MVP-1 / MVP-2 / MVP-3

| Slice | Fit | Notes |
| --- | --- | --- |
| MVP-0 | Strongly relevant, not runtime-changing | Proof maps to audio span, Duplex, Interaction, playback, and replay event shapes. |
| MVP-1 | Mostly not applicable | VAD does not advance `task_id`, `plan_version`, `task_event_seq`, stale evidence, or confirmation state. |
| MVP-2 | Supportive only for live interaction around spoken output | VAD can produce barge-in candidates during playback, but tools, confirmation, Composer, and UI state stay with their owners. |
| MVP-3 | Candidate after realtime proof | WebRTC VAD can be considered for local Duplex adapter profile only after live ingress, playback reference, false-positive, and timing evidence are stronger. |

## Risks / Gaps

- Existing harness results are offline/in-memory and synthetic.
- Natural speech quality is not proven.
- Live microphone capture latency is not proven.
- Device callback timing, scheduler delay, buffer sizes, and event append timing are not measured.
- Real playback echo and room/device AEC behavior are not proven.
- Idealized reference subtraction may be too optimistic.
- Tone and white-noise false positives remain visible.
- Short backchannels may be sensitive to frame size and mode.
- WebRTC VAD cannot identify whether speech is addressed to the assistant.
- WebRTC VAD cannot know whether the utterance is semantically complete.
- VAD cannot own turn commit, interrupt policy, truncate request, truncate completion, or task semantics.

## Recommendation

Proceed with a realtime ingress proof plan before Duplex/VAD adapter profile hardening.

Use the existing WebRTC VAD harness evidence as the synthetic/offline baseline, but require a separate future approved proof for:

- live capture/callback timing,
- playback reference availability,
- playback-only false-positive prevention,
- user speech over playback candidate metadata,
- barge-in to truncate causal shape,
- `TTS_TRUNCATED(actual_stop_offset_ms)` from Talker/playback,
- replay-safe metadata output with no raw audio.

Keep WebRTC VAD on the Duplex shortlist as a local speech-activity provider. Treat semantic close, assistant-directedness, real AEC, and target-valid truncate as unsupported or unknown until separate evidence exists.

## Next Implementation Step, gated on human approval

If a human approves a follow-up implementation thread, extend the spike-local Duplex/VAD research path without touching the main runtime. A suitable location would remain:

```text
tools/model_spikes/duplex_vad/
```

The approved follow-up should add only spike-local realtime proof support or a documented manual run procedure, emit metadata-only JSONL, keep all audio local-only, validate observation schemas, and produce a run report under `docs/research/spikes/`.

Until that approval exists, this thread stops at the proof plan.
