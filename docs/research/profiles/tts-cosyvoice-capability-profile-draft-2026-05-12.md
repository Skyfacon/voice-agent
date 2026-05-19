# TTS CosyVoice Capability Profile Draft

## Status

draft_research_profile_metadata_only

This is a research capability profile draft. It is not runtime integration, not a business adapter implementation, and not approval to modify MVP runtime behavior.

## Date

2026-05-12

## Contract Snapshot

- Default contract snapshot: `main@61e6afc`
- MVP-0 closeout reference: `22ddbf4 fix: harden mvp0 trace and replay safety`
- Capability contract reference: ADR-011 and `docs/specs/model-adapter-capabilities.md`
- Playback / truncate boundary reference: ADR-003 and `docs/specs/event-registry.md`
- SlowTask boundary reference: ADR-016
- Replay boundary reference: `docs/specs/replay-spec.md`

## Scope

This profile summarizes the already executed DashScope / Bailian CosyVoice TTS probe as adapter-shaped research evidence.

In scope:

- CosyVoice as a TTS / Talker audio provider candidate.
- Basic speech synthesis, streaming audio chunk, first-audio latency bucket, and word-timestamp evidence observed in the metadata-only run report.
- Mapping to ADR-011 capability matrix fields.
- Mapping to ADR-003 playback, truncate, and replay-safe metadata boundaries.
- Gaps that must be closed before MVP-3 integration consideration.

Out of scope:

- No changes to `src/voice_agent/`, `tests/`, `docs/adr/`, or `docs/specs/`.
- No main runtime wiring.
- No real business adapter.
- No live provider call in this profile step.
- No raw generated audio, provider response bodies, raw traces, local replay cache, real user input, request headers, or secret values.

## Source Evidence

Primary evidence:

- `docs/research/spikes/tts-dashscope-bailian-run-2026-05-11.md`

Supporting coordination and contract documents:

- `AGENTS.md`
- `docs/research/model-spike-phase-summary-2026-05-11.md`
- `docs/research/model-spike-execution-plan.md`
- `docs/research/model-spike-integration-ledger.md`
- `docs/research/model-spike-plan.md`
- `docs/research/model-selection.md`
- `docs/specs/model-adapter-capabilities.md`
- `docs/specs/event-registry.md`
- `docs/specs/replay-spec.md`
- `docs/adr/ADR-003 Barge-in and TTS Truncate Contract.md`
- `docs/adr/ADR-011 Model Adapter Capability Contract.md`
- `docs/adr/ADR-016 SlowTask Lifecycle and Confirmation State Contract.md`

Evidence limits:

- The primary run report is metadata-only.
- It records observed counts, byte totals, latency buckets, word timestamp availability, and failure category summaries.
- It does not store raw generated audio or raw provider response bodies.
- It does not prove playback-controller behavior.

## Candidate Identity

| field | draft value | label | notes |
| --- | --- | --- | --- |
| `adapter_id` | `draft_tts_dashscope_cosyvoice_2026_05_12` | not_applicable | Draft profile id only; not a runtime adapter id. |
| `adapter_type` | `tts_talker` | observed_real | Role matches the executed TTS probe. |
| `provider` | DashScope / Bailian | observed_real | Provider used in the executed run. |
| `model_name` | `cosyvoice-v3-flash` | observed_real | Observed on 2026-05-11; recheck the exact model alias before hardening. |
| `voice` | `longanyang` | observed_real | Observed voice in the probe; not a full voice catalog validation. |
| `deployment_mode` | `remote_api` | observed_real | Observed through the DashScope WebSocket inference surface. |
| `endpoint` | `dashscope-websocket-inference` | observed_real | Endpoint ref only; no secret-bearing values. |
| `output_mode` | `real` for successful audio chunks; `degraded` for client-close observation | observed_real / observed_degraded | Runtime use would still need adapter event recording. |

CosyVoice is a TTS / Talker audio provider candidate. It is not a playback controller, not an Interaction Controller, not SlowTask, and not a source of semantic acknowledgement.

## Capability Matrix Draft

Labels used here: `observed_real`, `observed_degraded`, `unsupported`, `unknown`, `not_applicable`, `docs_only_unobserved`.

| ADR-011 field | draft label | draft value / behavior | evidence and notes |
| --- | --- | --- | --- |
| `adapter_type` | observed_real | `tts_talker` | Executed as a TTS / Talker audio-provider probe. |
| `provider` | observed_real | `dashscope` / Bailian | Run report executed against DashScope / Bailian. |
| `model_name` | observed_real | `cosyvoice-v3-flash` | Observed on 2026-05-11; re-pin current alias before hardening. |
| `deployment_mode` | observed_real | `remote_api` | WebSocket inference surface. |
| `endpoint` | observed_real | `dashscope-websocket-inference` | Endpoint ref without secret-bearing request data. |
| `health_status` | observed_real | `healthy_for_observed_tts_probe` | Successful task completion observed for normal cases. |
| `capability_version` | not_applicable | `research_observation_v1` | Research profile version, not a runtime capability schema. |
| `latency_class` | observed_real | `first_audio_about_0.5_to_0.7s_for_synthetic_inputs` | Observed bucket only; not a general SLO conclusion. |
| `error_model` | observed_degraded | `websocket_error_or_task_failed_or_client_close_or_timeout` | Client close was observed; broader provider failures need recheck. |
| `timeout_policy` | observed_degraded | adapter-owned timeout metadata; no playback or task state implication | Timeout/close cannot become truncate confirmation. |
| `retry_policy` | unknown | reconnect/retry should be bounded and adapter-owned | Retry was not exercised in the run. |
| `output_mode` | observed_real / observed_degraded | `real` for completed audio chunks; `degraded` for client-close probe | Output mode is evidence labeling only, not runtime integration. |
| `supports_streaming_input` | observed_real | true for incremental text submission over WebSocket | Observed `continue-task` text submission; this is not audio input. |
| `supports_streaming_output` | observed_real | true | Binary audio chunks were observed. |
| `supports_audio_input` | unsupported | false | This TTS role does not accept audio input. |
| `supports_audio_output` | observed_real | true | Basic synthesized audio chunks were observed. |
| `supports_audio_timestamps` | observed_real | word timestamp / alignment events present | Alignment evidence only; not playback delivery truth. |
| `supports_structured_json` | not_applicable | false for this TTS role | Protocol metadata events are not SlowTask structured JSON capability. |
| `supports_tool_calling` | not_applicable | false | TTS does not propose or execute tools. |
| `supports_cancellation` | observed_degraded | client close observed; provider-confirmed cancellation not observed | Treat as degraded / unknown until provider semantics are proven. |
| `supports_emotion` | observed_degraded | rate, pitch, and instruction-style request accepted; quality not evaluated | Do not treat this as validated emotion control. |
| `supports_audio_caption` | unsupported | false | Audio captioning is outside this TTS role. |
| `supports_tts` | observed_real | true | Basic speech synthesis was observed. |
| `supports_tts_truncate` | unsupported | false at provider/model layer | ADR-003 truncate must be proven by Talker/playback controller. |
| `supports_tts_pause_resume` | unsupported | false / MVP non-goal | Pause/resume was not observed and is outside MVP. |
| `supports_semantic_close` | not_applicable | false | Semantic close belongs to Duplex/Thinker/Interaction evidence, not TTS. |
| `supports_assistant_directedness` | not_applicable | false | Directedness belongs to Duplex/Thinker/Interaction evidence, not TTS. |
| `max_audio_seconds` | not_applicable | null | Field is for audio input length; this TTS role has no audio input. |
| `max_context_tokens` | unknown | null | TTS text/input limits were not pinned in this profile. |
| `max_output_tokens` | unknown | null | TTS output length limits were not pinned in this profile. |
| `expected_first_token_latency_ms` | not_applicable | null | TTS has first-audio latency, not first-token latency. |
| `expected_first_audio_latency_ms` | observed_real | observed bucket: about 493ms to 705ms | Bucket from short synthetic cases only; not a universal SLO. |

## Observed Real Capabilities

- `supports_tts`: observed_real. CosyVoice synthesized basic speech for short and longer synthetic prompts.
- `supports_audio_output`: observed_real. Successful cases produced binary audio chunks.
- `supports_streaming_output`: observed_real. The WebSocket stream delivered chunked audio suitable for a future Talker pipeline to consume.
- `supports_streaming_input`: observed_real for incremental text submission. The observed surface accepted streamed synthetic text via task messages; this does not imply audio input.
- `supports_audio_timestamps`: observed_real for word timestamp / alignment events. These are alignment metadata, not playback delivery truth.
- First-audio latency bucket: observed_real as a run-specific bucket. Successful synthetic cases saw first audio at about 493ms to 705ms.
- Voice / style request acceptance: observed_real for request acceptance in the run, with quality and emotion semantics still degraded.

Observed run summary:

| case | task finished | binary chunks | audio bytes | first audio | total | timestamp evidence |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `short_ack` | true | 15 | 36,453 | 556ms | 1,103ms | present |
| `spoken_plan_short` | true | 23 | 55,679 | 493ms | 1,728ms | present |
| `spoken_plan_long` | true | 61 | 148,466 | 705ms | 5,778ms | present |
| `style_or_voice_control` | true | 17 | 43,976 | 553ms | 1,326ms | present |

## Degraded Capabilities

- `supports_cancellation`: observed_degraded / unknown. Client-side close after initial audio was observed, but provider-confirmed cancellation was not.
- `supports_emotion`: observed_degraded. The request accepted rate, pitch, and instruction-style control fields, but the run did not evaluate whether emotional delivery quality is reliable.
- Timeout handling: observed_degraded. Timeout or close can be adapter metadata, but it cannot imply playback stop or task progress.
- Alignment metadata: observed_real for timestamps, degraded if treated as delivery truth. Word timestamps can help map generated text/audio alignment, but only Talker/playback can confirm what reached the user.
- Playback integration: observed_degraded / unproven. The run did not validate frontend playback scheduling, `PLAYBACK_PROGRESS` cadence, or actual stopped offsets.

## Unsupported Capabilities

These are unsupported or not applicable for this TTS role:

- `supports_audio_input`
- `supports_structured_json`
- `supports_tool_calling`
- `supports_audio_caption`
- `supports_tts_truncate` at the provider/model layer
- `supports_tts_pause_resume`
- `supports_semantic_close`
- `supports_assistant_directedness`

Unsupported means the runtime must not silently rely on CosyVoice for these responsibilities. ASR, Thinker, Duplex, Interaction Controller, SlowTask Runtime, Tool Executor, Composer, and Talker/playback keep their existing ownership boundaries.

## Unknown / Needs Recheck

- Current official model alias, voice catalog, supported formats, sample rates, and exact text/output limits.
- Provider-confirmed cancellation semantics.
- Retry behavior under transient WebSocket, task, quota, and timeout failures.
- Longer text behavior, chunk cadence stability, and output duration limits.
- Alignment quality across longer, multilingual, interrupted, or punctuation-heavy SpokenPlan text.
- Whether any documented broader voice/style/emotion features work reliably enough for product use; current evidence is not quality evaluation.
- Playback-controller stop accuracy and replayable `actual_stop_offset_ms`.
- Whether future adapter healthcheck should use a cheap metadata-only probe or a short synthesis probe.

Docs-only notes that still need live observation before hardening:

- Wider voice/style controls beyond the observed request acceptance.
- Official service limits and error categories beyond the run's observed summaries.

## Audio Output / Streaming Notes

The run observed streaming binary audio chunks for all successful synthetic cases. The successful outputs produced 15 to 61 chunks and 36,453 to 148,466 audio bytes, depending on text length.

This is enough to mark streaming audio output as `observed_real` for research profile purposes. It is not enough to claim that playback scheduling, frontend buffer behavior, playback progress cadence, or target-valid barge-in has been proven.

Raw generated audio is not needed for this profile and must not be committed. A future replay-safe report should use `tts_stream_ref`, chunk counts, duration buckets, byte counts, and synthetic playback spans rather than audio content.

## Timestamp / Alignment Notes

Word timestamp events were observed in all successful cases and in the early client-close case before close. Mark this as `observed_real` for provider alignment metadata.

Important boundary:

- Word timestamp / alignment metadata is not playback delivery truth.
- It does not prove what audio reached the user.
- It does not create `PLAYBACK_PROGRESS`.
- It does not create `PLAYBACK_COMMITTED`.
- It does not create `TTS_TRUNCATED(actual_stop_offset_ms)`.

Only Talker/playback can emit delivery and stop-offset events.

## Playback / Truncate Boundary

CosyVoice is not the playback controller. It can provide synthesized audio and alignment evidence to Talker, but it cannot own playback state.

Required ADR-003 ownership:

- `PLAYBACK_SPAN_STARTED` must be produced by Talker/playback.
- `PLAYBACK_PROGRESS` must be produced by Talker/playback.
- `PLAYBACK_COMMITTED` must be produced by Talker/playback and is only a delivery marker, not user acknowledgement or semantic commitment.
- `TTS_TRUNCATE_REQUESTED` must be produced by Interaction Controller.
- `TTS_TRUNCATED` must be produced by Talker/playback with `actual_stop_offset_ms`.

Provider request close, client timeout, stream close, or provider-side request cancellation cannot be recorded as `TTS_TRUNCATED(actual_stop_offset_ms)`. They also cannot prove target-valid truncate. `supports_tts_truncate` must not be marked `observed_real` for the provider itself.

TTS output must not advance SlowTask state. It can serve spoken realization and playback only. It cannot own semantic acknowledgement, confirmation acceptance, task completion, or user intent.

## Timeout / Retry / Cancellation Mapping

Observed cancellation-related case:

- `client_close_cancellation_probe` produced 3 chunks, 6,778 audio bytes, first audio at 663ms, total observed duration 679ms, and timestamp evidence before client close.
- The task did not finish normally.
- This proves client-side close behavior in the probe harness, not provider-confirmed cancellation and not playback truncate.

Draft mapping for a future adapter:

| condition | metadata mapping | forbidden interpretation |
| --- | --- | --- |
| WebSocket/task failure before usable audio | `ADAPTER_REQUEST_FAILED` or retry metadata | Do not synthesize playback events from failure alone. |
| Client timeout | timeout/failure metadata with `output_mode=degraded` | Do not treat timeout as provider cancellation success. |
| Client stream close | degraded cancellation metadata | Do not treat close as `TTS_TRUNCATED`. |
| Late or partial audio after close | discard or mark stale/ignored at Talker boundary | Do not advance SlowTask state. |
| Missing timestamp events | `ADAPTER_OUTPUT_DEGRADED` for alignment metadata if timing expected | Do not invent playback offsets. |

Retry was not exercised. Any future retry policy should be bounded, adapter-owned, replay-visible, and unable to create duplicate playback spans without Talker approval.

## Replay-Safe Metadata Shape

Provider response bodies and raw generated audio do not need to enter a replay-safe report. Deterministic replay must not rerun CosyVoice; it should consume recorded metadata or a synthetic/minimal fixture.

Draft metadata shape:

```json
{
  "profile_id": "draft_tts_dashscope_cosyvoice_2026_05_12",
  "contract_snapshot": "main@61e6afc",
  "adapter_type": "tts_talker",
  "provider": "dashscope",
  "model_name_observed": "cosyvoice-v3-flash",
  "model_name_pin_required": true,
  "deployment_mode": "remote_api",
  "endpoint_ref": "dashscope-websocket-inference",
  "output_mode": "real_or_degraded",
  "synthesis": {
    "label": "observed_real",
    "successful_cases": 4,
    "audio_chunks_observed": true,
    "audio_bytes_bucket": "36k_to_149k",
    "raw_audio_stored": false
  },
  "streaming_output": {
    "label": "observed_real",
    "binary_audio_chunks_observed": true,
    "playback_controller_validated": false
  },
  "first_audio_latency": {
    "label": "observed_real",
    "observed_bucket_ms": "493_to_705",
    "general_slo_claim": false
  },
  "alignment": {
    "label": "observed_real",
    "word_timestamp_events_observed": true,
    "playback_delivery_truth": false
  },
  "truncate": {
    "provider_supports_tts_truncate_label": "unsupported",
    "playback_controller_proof_required": true,
    "provider_close_is_tts_truncated": false
  },
  "cancellation": {
    "label": "observed_degraded",
    "client_close_observed": true,
    "provider_confirmed_cancellation_observed": false
  },
  "request_headers_stored": false,
  "secret_values_stored": false,
  "provider_response_body_stored": false,
  "deterministic_replay_reruns_provider": false
}
```

## Trace / Privacy Boundary

- Store only metadata, redacted summaries, synthetic refs, latency buckets, chunk counts, byte counts, and failure categories.
- Do not store raw generated audio in GitHub-allowed research output.
- Do not store provider response bodies, raw traces, local replay cache, real user input, request headers, or secret-bearing request metadata.
- Replay fixtures should be synthetic / redacted / minimal.
- Deterministic replay does not rerun CosyVoice. It consumes recorded metadata or synthetic/minimal fixtures.
- If a future local harness writes generated audio for debugging, it must remain local-only and outside commit scope.

## Fit to MVP-0 / MVP-1 / MVP-2 / MVP-3

| slice | fit | notes |
| --- | --- | --- |
| MVP-0 | supportive, not required | Profile maps to adapter capability snapshot and Talker playback refs, but MVP-0 remains mock/runtime-only. |
| MVP-1 | mostly not applicable | TTS output does not advance SlowTask state, `plan_version`, stale evidence, or confirmation state. |
| MVP-2 | supportive for spoken realization only | Can synthesize SpokenPlan audio after Composer and coverage/truthfulness checks, but cannot alter facts or tool state. |
| MVP-3 | candidate, not ready | Basic synthesis and streaming output are promising, but integration consideration needs playback-controller truncate proof, cancellation/error hardening, and replay/eval fixtures. |

## Risks / Gaps

- The observed first-audio latency bucket is not a general SLO result.
- Playback scheduling and `PLAYBACK_PROGRESS` cadence were not validated.
- `TTS_TRUNCATED(actual_stop_offset_ms)` was not validated and cannot be inferred from provider close/timeout.
- Provider-confirmed cancellation is unknown.
- Retry behavior was not exercised.
- Style/emotion behavior was request-accepted but not quality-evaluated.
- Word timestamp alignment quality was not evaluated beyond presence.
- Official model alias, limits, and service behavior can drift.
- No synthetic replay/eval fixture has been created from this profile yet.
- Raw generated audio is unnecessary for the profile and must remain out of commit scope.

## Recommendation

Keep DashScope / Bailian CosyVoice on the TTS shortlist as a TTS / Talker audio provider candidate.

Treat these as observed real capabilities for profile hardening: basic speech synthesis, streaming audio chunks, audio output, run-specific first-audio latency bucket, and word timestamp / alignment metadata.

Treat cancellation as degraded / unknown, and treat provider/model-layer TTS truncate as unsupported. Target-valid truncate requires Talker/playback proof of `actual_stop_offset_ms` under ADR-003.

Do not integrate CosyVoice into the runtime in this step. Do not let TTS own playback state, SlowTask state, semantic acknowledgement, confirmation, tool behavior, semantic close, or assistant directedness.

## Next Evidence Needed

1. Recheck official DashScope / Bailian CosyVoice model alias, endpoint surface, voice/style options, service limits, formats, and error categories on the hardening day.
2. Build or specify a spike-local playback-controller proof that can emit `PLAYBACK_PROGRESS`, `TTS_TRUNCATE_REQUESTED`, and `TTS_TRUNCATED(actual_stop_offset_ms)` from synthetic metadata without committing raw audio.
3. Run a bounded timeout/retry/cancellation probe that distinguishes client close, provider failure, provider-confirmed cancellation if available, and late partial audio.
4. Measure chunk cadence and first-audio latency across a larger synthetic set; report buckets only until a controlled SLO eval exists.
5. Validate word timestamp alignment quality against synthetic text and confirm it remains advisory alignment evidence.
6. Define a replay-safe synthetic fixture proposal for TTS playback span compatibility and truncate ownership separation, without changing `tests/` in this research step.
7. Decide whether MVP-3 should use a remote CosyVoice adapter first or defer to a self-hosted CosyVoice2 comparison after equivalent metadata-only evidence exists.
