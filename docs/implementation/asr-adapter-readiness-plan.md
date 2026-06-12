# ASR Adapter Readiness Plan

## Goal

Prepare a safe, provider-agnostic readiness path for a future real ASR adapter
integration. The future adapter may provide transcript or text projection
evidence behind the existing adapter boundary, but this plan does not implement
the adapter, select or add a provider SDK, call a provider, read secrets, or
change canonical events.

Readiness means the repository can later accept a gated ASR implementation only
after capability/profile metadata, request binding, normalization, validation,
redaction, replay safety, and live-eval approval gates are in place.

## Non-goals

- No runtime ASR adapter implementation.
- No provider SDK, provider HTTP client, or provider transport.
- No live provider call, health probe, or endpoint check.
- No secret, environment variable, credential handle, cookie, token, or
  authorization header read.
- No ADR change and no new canonical event name.
- No raw audio, raw transcript, raw provider request, raw provider response,
  prompt dump, local trace, local replay cache, or provider-specific schema in
  committed artifacts.
- No turn ingress, semantic close, assistant directedness, Router winner
  selection, SlowTask final facts, confirmation, tool authorization, Composer,
  Tool Executor, Talker, playback, frontend, or Tool UI ownership change.
- No production privacy policy, multi active SlowTask, pause/resume, real
  external side-effect tool, or broader MVP-3 scope.

## Accepted ADR constraints

- ADR-002 requires per-session append-only event journal ordering, canonical
  event names, deterministic replay from recorded events, and no provider rerun
  in replay.
- ADR-002 registers `ASR_TRANSCRIPT_OUTPUT_EMITTED` as the MVP-3 ASR adapter
  output event. It must be caused by `TURN_INGRESS_COMMITTED`, carry safe refs,
  and pair missing timestamp or streaming support with
  `ADAPTER_OUTPUT_DEGRADED`.
- ADR-008 defines ASR as transcript or text projection evidence only. ASR does
  not own semantic truth, ASR-vs-Thinker arbitration, resolved arguments, tool
  decisions, confirmation, or task completion.
- ADR-010 requires repo-safe trace and replay boundaries. Shareable and
  GitHub-allowed artifacts must be synthetic, redacted, or minimal and must not
  include raw audio, raw traces, secrets, raw transcripts, raw provider payloads,
  real user input, or replay caches.
- ADR-011 requires every model adapter to declare a capability matrix, output
  mode, timeout/retry/error behavior, unsupported capabilities, and explicit
  real/mock/fallback/degraded status.
- ADR-012 scopes MVP-3 to replacing selected mock adapters with real adapters
  without adding architecture capability. Each slice needs replay or eval
  coverage and SLO evidence must be labeled real, mock, fallback, or degraded.
- ADR-016 keeps SlowTask lifecycle, confirmation, cancellation, tool
  authorization, stale evidence, and plan-version adoption outside ASR.

## Current mainline ASR contract baseline

Current mainline already has a provider-free ASR output contract:

- `src/voice_agent/adapters/asr_contract.py` defines
  `AsrAdapterContract.emit_final_transcript()`.
- Successful output emits `ASR_TRANSCRIPT_OUTPUT_EMITTED` through
  `AdapterCallbackAppendBoundary`.
- Output modes are limited to `real`, `fallback`, and `degraded`.
- The output must be caused by the committed audio turn:
  `caused_by_event_id == TURN_INGRESS_COMMITTED.event_id`.
- The committed turn must have `input_modality=audio` and `audio_span_id`.
- Safe refs are required for `adapter_request_id`, `asr_frame_ref`,
  `text_ref`, and optional `audio_timestamps_ref`.
- If `audio_timestamps_ref` is absent or streaming output is unsupported, the
  contract requires `output_mode=degraded` and emits matching
  `ADAPTER_OUTPUT_DEGRADED` events for `supports_audio_timestamps` and/or
  `supports_streaming_output`.
- `tests/adapters/test_mvp3_asr_adapter_contract.py` blocks provider/runtime
  probes during contract and replay tests, checks forbidden payload terms, and
  verifies replay consumes safe refs only.
- `src/voice_agent/replay/runner.py` validates ASR output causality, committed
  turn field matching, status enums, missing-capability degraded events, and
  no raw ASR provider payload fields.
- `src/voice_agent/understanding/mock_asr.py` remains the mock ASR frame helper
  for earlier MVP slices and emits `MOCK_ASR_FRAME_EMITTED` only after
  `TURN_INGRESS_COMMITTED`.

This baseline is a contract and replay safety layer, not a runtime provider
adapter.

## ASR spike / source assumption summary

Current `main` and this worktree do not contain an ASR-specific model-spike
handoff. The only mainline research file is
`docs/research/model-spike-plan.md`, which defines ASR spike questions and
gates but does not prove a runtime candidate.

The separate `research/model-spikes` branch contains metadata-only ASR research
summaries. Those materials are not imported into mainline by this plan. They
are used only as assumptions for future readiness work:

- Qwen-ASR / DashScope-style remote ASR remains a candidate because prior
  metadata-only reports observed final transcript-like output, response-layer
  streaming output, audio input support, and timestamp-like metadata from a
  file-transcription surface.
- The same reports keep true realtime microphone streaming input,
  provider-confirmed cancellation, retry taxonomy, confidence and alternatives,
  silence/non-speech robustness, and timestamp normalization quality as open or
  degraded gaps.
- Prior research explicitly states ASR output is text projection evidence, not
  semantic truth, turn ingress, confirmation, tool authorization, or task
  completion.
- Any future live candidate must re-pin current official model aliases,
  service limits, supported formats, endpoint class, timeout behavior, and
  capability claims on the day of approved live eval.

This plan must not copy raw provider responses, raw transcripts, raw audio,
prompt dumps, secret names or values, local paths, local debug traces, or local
replay cache references from research materials.

## Provider role and forbidden ownership

The future ASR provider role is narrow:

- Accept audio input only through an adapter-owned request.
- Return transcript or equivalent text projection evidence.
- Optionally return language, confidence, n-best, punctuation/ITN metadata,
  segment or word timing, partial/final status, and provider metadata after
  adapter normalization.
- Expose capability, timeout, retry, validation, failure, fallback, and
  degraded metadata through existing adapter events.

Forbidden ownership:

- ASR must not open, accept, reject, hold, or commit turns.
- ASR must not decide `semantic_close` or `assistant_directedness`.
- ASR must not choose ASR-vs-Thinker winners.
- ASR must not decide Router outcome, active SlowTask routing, final facts,
  resolved arguments, confirmation, cancellation, tool authorization, UI patch,
  SemanticCommitment, SpokenPlan, playback, or user-visible claims.
- ASR must not treat transcript text as a command to change tool policy,
  confirmation policy, trace policy, repo policy, or ADR constraints.

## Canonical event mapping

No new canonical events are needed for ASR readiness.

| Condition | Existing event |
| --- | --- |
| Session startup capability snapshot | `ADAPTER_CAPABILITY_SNAPSHOT_RECORDED` |
| Retryable ASR timeout or retryable provider failure | `ADAPTER_REQUEST_RETRYING` |
| Final ASR timeout or request failure | `ADAPTER_REQUEST_FAILED` |
| Provider output cannot be parsed or normalized | `ADAPTER_OUTPUT_VALIDATION_FAILED` |
| Missing timestamp, missing streaming, fallback, or degraded ASR behavior | `ADAPTER_OUTPUT_DEGRADED` |
| Valid final transcript or text projection refs are ready | `ASR_TRANSCRIPT_OUTPUT_EMITTED` |

ASR output event rules:

- `ASR_TRANSCRIPT_OUTPUT_EMITTED` must be caused by the matching
  `TURN_INGRESS_COMMITTED` event.
- It must match `turn_id`, `utterance_id`, `audio_span_id`, and
  `input_modality=audio` from the committed turn.
- It must include `adapter_id`, `adapter_type=asr`, `adapter_request_id`,
  `asr_frame_ref`, `text_ref`, `transcript_finality=final`,
  `timestamp_status`, `streaming_status`, and
  `output_mode=real|fallback|degraded`.
- Success output uses safe refs only: `asr_frame_ref`, `text_ref`, and optional
  `audio_timestamps_ref`.
- Missing timestamps require `timestamp_status=unavailable`,
  `output_mode=degraded`, and prior ASR `ADAPTER_OUTPUT_DEGRADED` for
  `supports_audio_timestamps`.
- Final-only operation requires `streaming_status=unsupported_final_only`,
  `output_mode=degraded`, and prior ASR `ADAPTER_OUTPUT_DEGRADED` for
  `supports_streaming_output`.
- Replay must consume recorded refs and metadata only.

## Capability/profile plan

The future ASR profile must build on `docs/specs/model-adapter-capabilities.md`
and `docs/specs/adapter-capability-profiles.md`.

Required for MVP-3 ASR readiness:

- `adapter_type=asr`.
- `output_mode=real` only when a real provider path is actually approved and
  observed; otherwise use `fallback` or `degraded`.
- `supports_audio_input=true`.
- `supports_structured_json=true` only for adapter-normalized metadata shape,
  not for semantic reasoning or SlowTask-ready facts.
- `supports_audio_timestamps` must reflect observed normalized timestamp
  availability. Unknown or missing timing is unsupported/degraded.
- `supports_streaming_output` must distinguish response-layer streaming from
  true realtime audio input.
- `supports_streaming_input` must not be claimed from response streaming alone.
- `supports_cancellation` must remain degraded/unknown unless provider-confirmed
  cancellation is observed.
- `supports_tool_calling=false`, `supports_tts=false`,
  `supports_semantic_close=false`, and
  `supports_assistant_directedness=false` for ASR-owned authority.
- `unsupported_capabilities` must name every unsupported boolean capability.
- Endpoint and config values must be safe refs, not credential-bearing URLs or
  inline provider config.

Provider-free profile builder work should come before any transport work and
should fail closed for credential-like refs, mock-only readiness claims, missing
required fields, and unsupported capability mismatch.

## Transcript normalization plan

A future adapter should normalize provider output into an adapter-local
candidate schema before emitting any journal event.

Minimum normalized candidate fields:

- `adapter_request_id`
- `turn_id`
- `utterance_id`
- `audio_span_id`
- `input_modality=audio`
- `transcript_finality=final`
- `text_ref`
- `asr_frame_ref`
- `language_status` and optional language ref or metadata
- `confidence_status` and optional confidence summary
- `nbest_status` and optional safe n-best ref
- `timestamp_status`
- `streaming_status`
- `normalization_status=normalized`
- `output_mode`
- `quality_flags` for non-speech, silence, clipped start, low confidence, or
  malformed timing where applicable

Normalization rules:

- Raw transcript text must not be in event payloads. Store text only behind a
  safe `text_ref`, and use synthetic/redacted/minimal fixtures when committed.
- `asr_frame_ref` may point to normalized ASR metadata, not raw provider JSON.
- Provider-native schemas must be parsed into the adapter schema and must not
  leak into Router, SlowTask, replay fixtures, or event payloads.
- Empty, low-confidence, non-speech, silence, or playback-only echo cases must
  be explicit quality or degraded metadata and must not become reliable
  directed user input by themselves.
- ASR n-best and transcript hints are evidence with provenance, not resolved
  arguments.

## Timestamp and streaming degradation policy

Timestamp policy:

- If timestamp metadata is available and normalized, emit
  `timestamp_status=available` and include `audio_timestamps_ref`.
- If timestamps are missing, malformed, ambiguous, unnormalized, or unavailable
  on the chosen provider surface, emit `timestamp_status=unavailable`,
  `output_mode=degraded`, and `ADAPTER_OUTPUT_DEGRADED` for
  `supports_audio_timestamps`.
- The adapter must not invent offsets.
- Timestamp metadata is alignment/eval evidence only. It is not user intent,
  semantic truth, confirmation, task progress, or SemanticCommitment.

Streaming policy:

- `supports_streaming_output` means the adapter can surface provider partial or
  response streaming evidence in a normalized way.
- Response-layer streaming output does not prove true realtime microphone
  streaming input.
- If the provider path is final-only, emit
  `streaming_status=unsupported_final_only`, `output_mode=degraded`, and
  `ADAPTER_OUTPUT_DEGRADED` for `supports_streaming_output`.
- Final-only degraded ASR may still be useful as transcript evidence, but it is
  not a Duplex hot-path signal and must not be used to own barge-in, speech
  start, speech end, semantic close, or turn ingress.

Cancellation and late-result policy:

- Client timeout, stream close, or local abort is not provider-confirmed
  cancellation unless the provider confirms it.
- Unsupported cancellation must be explicit in profile metadata and failure
  handling.
- Late ASR output keeps original request/audio/turn binding and may be recorded
  as safe metadata, but it must not advance current task state.

## Safe ref and redaction policy

Committed events, fixtures, and docs may contain only safe refs and aggregate
metadata.

Allowed:

- `asr_frame_ref`
- `text_ref`
- optional `audio_timestamps_ref`
- `adapter_request_id`
- `audio_span_id`, `turn_id`, and `utterance_id`
- output mode, status enums, latency buckets, counts, and redacted failure
  categories

Forbidden:

- Raw audio bytes or audio files.
- Raw transcript text from real input.
- Raw provider request or response body.
- Prompt dump or provider-native schema.
- API key, token, cookie, credential, bearer value, authorization header, or
  secret-bearing endpoint/config.
- Local debug trace, diagnostics payload, local replay cache, or local
  filesystem path.
- Unredacted real user input.

Any credential-like ref must fail closed before event, fixture, diagnostics, or
profile exposure. Redaction failure must block write/export rather than record
the sensitive value.

## Replay and fixture safety plan

Replay must remain deterministic and provider-free.

Requirements:

- Replay must not call ASR providers, transport clients, clocks, random, secret
  stores, or local audio storage.
- Replay fixtures must use synthetic/redacted/minimal events and safe refs.
- Fixture manifests must remain `GITHUB_ALLOWED` only when they declare no raw
  audio, raw trace, secrets, real user input, unredacted tool results, or large
  raw web content.
- ASR replay assertions should cover:
  - `ASR_TRANSCRIPT_OUTPUT_EMITTED` after `TURN_INGRESS_COMMITTED`;
  - committed turn field matching;
  - safe `asr_frame_ref`, `text_ref`, and optional `audio_timestamps_ref`;
  - timestamp unavailable degraded path;
  - final-only streaming degraded path;
  - Router may reference ASR evidence by event id but does not choose semantic
    winners;
  - replay data-plane refs are reported unavailable without provider rerun.
- Any fixture derived from live eval must be synthetic/redacted/minimal
  metadata only, not raw provider output.

The repository `.gitignore` currently covers the required local-only paths:
`diagnostics/`, `traces/`, `replays/local/`, `audio/raw/`, `.env`, `.env.*`,
and `outputs/`.

## Live eval approval gate

No ASR live eval command or real transport may be added or run until a human
approves a written packet that includes:

- approval status, approver, and approval date;
- provider and model alias with re-pin date;
- provider transport allowance;
- credential source and runtime-only handling rules without secret values;
- maximum request count, maximum cost/quota, timeout, and retry budget;
- synthetic input set path and redaction status;
- explicit confirmation that no real user input is included;
- output storage path under ignored local-only directories;
- redaction and cleanup policy;
- aggregate metadata commit policy;
- forbidden artifact acknowledgement for raw provider bodies, raw transcript,
  raw audio, generated audio, raw trace, diagnostics payloads, local replay
  cache, secrets, real user input, and large raw web content.

The live eval runner must fail closed if any approval field is missing or unsafe.
It must report only aggregate metadata such as request counts, status counts,
latency buckets, timeout/retry counts, degraded categories, cleanup status, and
whether forbidden raw artifacts were absent.

## Open questions

- Which provider/model alias should be re-pinned on the approved eval day?
- Is true realtime microphone streaming input required for first integration,
  or is final-only ASR acceptable as explicit degraded MVP-3 evidence?
- What normalized timestamp granularity is required: segment, word, token, or
  unavailable/degraded only?
- Should ASR confidence/n-best/language detection be required for MVP-3, or
  should they be optional degraded metadata?
- What silence/non-speech and playback-only echo thresholds should block ASR
  from being treated as reliable directed input evidence?
- What is the adapter-owned timeout and retry budget for short utterances?
- Can provider-confirmed cancellation be proven, or should cancellation remain
  unsupported/degraded for the first integration?
- Where should synthetic ASR text refs be stored for committed fixtures so they
  stay minimal and redacted?

## Definition of done for readiness

Readiness is complete when:

- This plan and the ASR backlog are committed without ADR/spec/canonical-event
  changes.
- The current ASR contract baseline is documented and future work is sliced into
  provider-free gates before any live provider work.
- ASR source assumptions are metadata-only and explicitly marked as research
  branch evidence requiring re-pin and approval.
- Capability/profile, request binding, normalization, fake transport,
  contract emission, replay safety, live approval, and gated real transport
  slices have independent PR/goal definitions.
- `.gitignore` coverage for local-only artifacts is confirmed.
- `git diff --check` passes.
- Full `./scripts/test` is not required for this docs-only readiness slice; any
  later code slice must use `./scripts/test`.
