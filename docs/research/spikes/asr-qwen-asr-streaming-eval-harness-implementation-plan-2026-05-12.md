# ASR Qwen-ASR Streaming Eval Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development before implementing this plan task-by-task. This document is a future implementation plan only; this thread does not create harness code.

**Goal:** Define a spike-local ASR proof harness that can produce replay-safe metadata for Qwen-ASR streaming output, timestamp normalization, cancellation boundaries, retry behavior, and late-output handling.

**Architecture:** The future harness lives outside the MVP runtime under `tools/model_spikes/asr_streaming_eval/`. It produces local-only run artifacts plus a small commit-safe markdown summary under `docs/research/spikes/`. Deterministic replay consumes recorded metadata or synthetic fixtures and never reruns ASR.

**Tech Stack:** Python standard library first, JSONL metadata, JSON Schema for validation, synthetic fixtures only by default. Any live provider path is disabled by default and requires separate human approval before use.

---

## Status

planned_spike_local_implementation_plan_metadata_only_no_code

This document is not harness implementation, not runtime integration, not a real business adapter, and not approval to call a live provider.

## Date

2026-05-12

## Contract Snapshot

- Default contract snapshot: `main@61e6afc`
- Capability contract reference: ADR-011 and `docs/specs/model-adapter-capabilities.md`
- ASR / Thinker evidence boundary reference: ADR-008
- Event and replay boundary references: `docs/specs/event-registry.md` and `docs/specs/replay-spec.md`
- SlowTask lifecycle and stale evidence reference: ADR-016

## Source Evidence

- `docs/research/spikes/asr-dashscope-bailian-run-2026-05-11.md`
- `docs/research/profiles/asr-qwen-asr-capability-profile-draft-2026-05-12.md`
- `docs/research/spikes/asr-qwen-asr-eval-harness-plan-2026-05-12.md`
- `docs/research/spikes/asr-qwen-asr-streaming-timestamp-cancellation-proof-plan-2026-05-12.md`
- `docs/research/spikes/asr-capability-spike-2026-05-09.md`
- `AGENTS.md`
- `docs/adr/ADR-008 ASR Thinker Evidence Fusion and SlowTask-led Conflict Resolution.md`
- `docs/adr/ADR-011 Model Adapter Capability Contract.md`
- `docs/adr/ADR-016 SlowTask Lifecycle and Confirmation State Contract.md`
- `docs/specs/model-adapter-capabilities.md`
- `docs/specs/event-registry.md`
- `docs/specs/replay-spec.md`

## Scope

In scope for a future approved implementation:

- A spike-local harness under `tools/model_spikes/asr_streaming_eval/`.
- Synthetic metadata fixtures for all proof cases.
- Optional local synthetic audio generation that writes only to temporary paths.
- JSONL observation output with one metadata-only object per case.
- Schema validation and summary generation.
- Dry-run mode that never calls a provider.
- A gated live-run shape for a later separately approved provider probe.

Out of scope:

- No changes to `src/voice_agent/`.
- No changes to `tests/`.
- No changes to `docs/adr/`.
- No changes to `docs/specs/`.
- No main runtime wiring.
- No real business adapter.
- No provider call by default.
- No committed audio recordings.
- No committed provider request or response bodies.
- No committed local traces or replay caches.
- No real user recordings or real user text.
- No request headers or secret-bearing values in output.

## Boundary Conclusions

- Qwen-ASR is an ASR / text projection evidence provider, not the turn ingress owner, not the Interaction Controller, not the Router, not the Thinker, not SlowTask, and not the semantic truth owner.
- ASR transcript output is evidence only. It is not `SemanticCommitment`, not confirmation, not tool authorization, not task completion, and not resolved arguments.
- Response streaming output is observed_real from the previous run, but true realtime microphone streaming input remains unknown/degraded until directly exercised.
- File transcription timestamp-like and word-like metadata is observed_real, but units, offset basis, and alignment quality still need normalization proof.
- Client timeout and client stream close are degraded local control observations unless the provider explicitly confirms cancellation.
- Silence/non-speech producing transcript-like text is degraded quality evidence and must be labeled as unreliable directed user input.

## Future File Layout

The future implementation should create only spike-local files:

| path | responsibility |
| --- | --- |
| `tools/model_spikes/asr_streaming_eval/README.md` | Explains local-only execution, privacy posture, case matrix, and allowed outputs. |
| `tools/model_spikes/asr_streaming_eval/__init__.py` | Makes the directory importable for local module execution. |
| `tools/model_spikes/asr_streaming_eval/__main__.py` | CLI entrypoint for dry-run, validation, summary, and gated live-run commands. |
| `tools/model_spikes/asr_streaming_eval/cases.py` | Defines case ids, fixture metadata, expected labels, and required checks. |
| `tools/model_spikes/asr_streaming_eval/schema.py` | Holds JSON Schema loading and validation helpers. |
| `tools/model_spikes/asr_streaming_eval/observations.py` | Builds and validates observation objects. |
| `tools/model_spikes/asr_streaming_eval/synthetic_fixtures.py` | Creates local-only synthetic metadata and, if approved later, temporary synthetic audio files. |
| `tools/model_spikes/asr_streaming_eval/provider_probe.py` | Reserved for separately approved live provider probe logic; default command must refuse live execution. |
| `tools/model_spikes/asr_streaming_eval/summarize.py` | Converts local JSONL observations into a commit-safe markdown run summary. |
| `tools/model_spikes/asr_streaming_eval/schemas/asr_streaming_observation.schema.json` | Commit-safe schema for metadata-only observations. |
| `tools/model_spikes/asr_streaming_eval/fixtures/README.md` | Describes fixture policy; no audio files are committed. |
| `tools/model_spikes/asr_streaming_eval/runs/README.md` | States that local run output is ignored or kept outside the repo. |

The future implementation should not create files under runtime or canonical test directories.

## CLI Shape

Recommended future commands:

```bash
python -m tools.model_spikes.asr_streaming_eval dry-run \
  --case-set smoke \
  --out /private/tmp/voice-agent-asr-streaming-eval/example/observations.jsonl
```

```bash
python -m tools.model_spikes.asr_streaming_eval validate \
  --schema tools/model_spikes/asr_streaming_eval/schemas/asr_streaming_observation.schema.json \
  --observations /private/tmp/voice-agent-asr-streaming-eval/example/observations.jsonl
```

```bash
python -m tools.model_spikes.asr_streaming_eval summarize \
  --observations /private/tmp/voice-agent-asr-streaming-eval/example/observations.jsonl \
  --out docs/research/spikes/asr-qwen-asr-streaming-eval-run-YYYY-MM-DD.md
```

```bash
python -m tools.model_spikes.asr_streaming_eval live-run \
  --case-set provider_probe \
  --out /private/tmp/voice-agent-asr-streaming-eval/provider/observations.jsonl
```

`live-run` must fail closed unless a future human-approved execution path explicitly enables it. The default safe path is `dry-run`.

## Observation Schema Contract

Every future JSONL row should include:

```json
{
  "schema_version": "asr_streaming_timestamp_cancellation_observation_v1",
  "contract_snapshot": "main@61e6afc",
  "observation_id": "obs_asr_qwen_example_001",
  "case_id": "streaming_output_delta_probe",
  "adapter_type": "asr",
  "provider": "dashscope_or_synthetic",
  "model_name": "qwen3-asr-flash_or_synthetic_fixture",
  "deployment_mode": "remote_api_or_synthetic",
  "endpoint_ref": "synthetic-dry-run",
  "output_mode": "mock_or_real_or_degraded",
  "input_fixture": {
    "fixture_kind": "synthetic_audio_metadata",
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
    "streaming_input_mode": "synthetic_or_data_url_or_file_url_or_realtime_probe",
    "streaming_output_requested": true,
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
    "response_streaming_output_observed": true,
    "delta_chunk_count": 4,
    "first_delta_ms": 1306,
    "final_delta_ms": 1322,
    "true_realtime_microphone_streaming_input_observed": false,
    "input_chunk_duration_ms": null,
    "input_cadence_ms": null,
    "backpressure_observed": "unknown"
  },
  "timestamp_observation": {
    "timestamp_source": "filetrans_words",
    "units": "ms",
    "audio_offset_basis": "audio_span_start",
    "segment_count": 1,
    "word_count": 3,
    "normalized": true,
    "normalization_status": "normalized",
    "degraded_reason": null
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

Validation rules:

- Required fields must be present.
- `adapter_type` must be `asr`.
- `output_mode` must be one of `mock`, `real`, `degraded`, or `fallback`.
- `stored_audio`, `stored_provider_body`, and `stored_sensitive_access_material` must be false for any commit-safe output.
- Non-speech cases with transcript text must set `non_speech_transcript_risk=true` and `reliable_directed_user_input=false`.
- Timestamp offsets must not be negative or descending.
- Missing timing must be represented as unavailable or degraded, not invented.

## Case Sets

`smoke` should include:

- `short_command_nonstream_baseline`
- `streaming_output_delta_probe`
- `filetrans_timestamp_probe`
- `silence_non_speech_probe`
- `client_timeout_probe`

`full_synthetic` should include:

- `short_command_nonstream_baseline`
- `mixed_language_nonstream_baseline`
- `clipped_start_probe`
- `low_volume_speech_probe`
- `longer_utterance_probe`
- `silence_non_speech_probe`
- `tone_non_speech_probe`
- `white_noise_non_speech_probe`
- `background_speech_not_directed_probe`
- `playback_only_echo_probe`
- `user_speech_over_playback_probe`
- `streaming_output_delta_probe`
- `true_realtime_mic_streaming_input_probe`
- `filetrans_timestamp_probe`
- `word_timestamp_granularity_probe`
- `timestamp_normalization_probe`
- `partial_transcript_replay_probe`
- `client_timeout_probe`
- `client_abort_stream_probe`
- `provider_cancellation_probe`
- `retryable_failure_probe`
- `late_transcript_after_superseded_turn_probe`
- `asr_not_semantic_truth_probe`

`provider_probe` should be unavailable by default until separately approved.

## Task Plan

### Task 1: Create Spike-Local Skeleton

**Files:**

- Create: `tools/model_spikes/asr_streaming_eval/README.md`
- Create: `tools/model_spikes/asr_streaming_eval/__init__.py`
- Create: `tools/model_spikes/asr_streaming_eval/__main__.py`
- Create: `tools/model_spikes/asr_streaming_eval/runs/README.md`

Steps:

- [ ] Add README sections for purpose, boundaries, allowed outputs, forbidden outputs, and command overview.
- [ ] Add an empty package marker.
- [ ] Add a CLI with subcommands `dry-run`, `validate`, `summarize`, and `live-run`.
- [ ] Make `live-run` exit with a clear refusal message unless a future approved enable flag is present.
- [ ] Confirm no runtime modules are imported.
- [ ] Confirm local run outputs are written under `/private/tmp/voice-agent-asr-streaming-eval/` by default.

### Task 2: Add Schema Validation

**Files:**

- Create: `tools/model_spikes/asr_streaming_eval/schemas/asr_streaming_observation.schema.json`
- Create: `tools/model_spikes/asr_streaming_eval/schema.py`

Steps:

- [ ] Add the JSON Schema for the observation shape in this document.
- [ ] Validate required top-level fields.
- [ ] Validate privacy fields are false for commit-safe output.
- [ ] Validate `output_mode` labels.
- [ ] Validate timestamp offsets and normalization status.
- [ ] Return validation errors as metadata summaries, not provider bodies.

### Task 3: Define Cases and Synthetic Metadata

**Files:**

- Create: `tools/model_spikes/asr_streaming_eval/cases.py`
- Create: `tools/model_spikes/asr_streaming_eval/synthetic_fixtures.py`
- Create: `tools/model_spikes/asr_streaming_eval/fixtures/README.md`

Steps:

- [ ] Define the `smoke`, `full_synthetic`, and disabled `provider_probe` case sets.
- [ ] For each case, define expected labels, fixture metadata, required checks, and expected risk flags.
- [ ] Keep generated audio local-only if audio generation is later enabled.
- [ ] Generate synthetic metadata without audio by default.
- [ ] Set non-speech risk flags explicitly for silence, tone, noise, background speech, and playback-only echo cases.

### Task 4: Build Observation Writer

**Files:**

- Create: `tools/model_spikes/asr_streaming_eval/observations.py`

Steps:

- [ ] Build one observation object per case.
- [ ] Attach stable `observation_id`, `case_id`, and `adapter_request_id`.
- [ ] Record transcript presence and length without storing full real transcripts.
- [ ] Record streaming chunk counts and timing buckets.
- [ ] Record timestamp source, units, offset basis, segment count, word count, and normalization status.
- [ ] Record timeout, retry, cancellation, client close, and late-output metadata.
- [ ] Validate each observation before writing JSONL.

### Task 5: Add Dry-Run Command

**Files:**

- Modify: `tools/model_spikes/asr_streaming_eval/__main__.py`

Steps:

- [ ] Implement `dry-run --case-set smoke --out <path>`.
- [ ] Create parent directories for the output path only under local temporary or explicitly supplied local paths.
- [ ] Write JSONL with one metadata-only object per case.
- [ ] Print only counts, case ids, and validation status.
- [ ] Do not print transcript text, request headers, provider bodies, local traces, or secrets.

### Task 6: Add Summary Command

**Files:**

- Create: `tools/model_spikes/asr_streaming_eval/summarize.py`
- Modify: `tools/model_spikes/asr_streaming_eval/__main__.py`

Steps:

- [ ] Read a validated JSONL observation file.
- [ ] Produce a markdown table with case id, output mode, capability label, key timings, and degradation reason.
- [ ] Include boundary conclusions from ADR-008 and ADR-011.
- [ ] Include replay-safe metadata conclusions.
- [ ] Write the summary only to a human-selected path, usually under `docs/research/spikes/`.

### Task 7: Reserve Provider Probe Behind Approval

**Files:**

- Create: `tools/model_spikes/asr_streaming_eval/provider_probe.py`
- Modify: `tools/model_spikes/asr_streaming_eval/__main__.py`

Steps:

- [ ] Add a provider probe module that refuses execution by default.
- [ ] Require a future approval path before enabling live provider execution.
- [ ] Keep provider-specific request details out of commit-safe output.
- [ ] Record only endpoint refs, model names, timing buckets, failure categories, and output labels.
- [ ] Keep provider-confirmed cancellation as `unknown` unless explicit provider evidence is returned.
- [ ] Keep client close and timeout as degraded local observations.

### Task 8: Verification and Guardrails

**Files:**

- No runtime or protected directory files.

Steps:

- [ ] Run `python -m tools.model_spikes.asr_streaming_eval dry-run --case-set smoke --out /private/tmp/voice-agent-asr-streaming-eval/smoke/observations.jsonl`.
- [ ] Run `python -m tools.model_spikes.asr_streaming_eval validate --schema tools/model_spikes/asr_streaming_eval/schemas/asr_streaming_observation.schema.json --observations /private/tmp/voice-agent-asr-streaming-eval/smoke/observations.jsonl`.
- [ ] Run `python -m tools.model_spikes.asr_streaming_eval summarize --observations /private/tmp/voice-agent-asr-streaming-eval/smoke/observations.jsonl --out docs/research/spikes/asr-qwen-asr-streaming-eval-run-YYYY-MM-DD.md`.
- [ ] Run `git status --short`.
- [ ] Run the repository sensitive-pattern scan specified by the active model spike thread.
- [ ] Run `git status --short -- src/voice_agent tests docs/adr docs/specs`.
- [ ] Run `git diff --check`.

If protected directories change, stop and revert only the unintended changes from the current task.

## Expected Commit-Safe Summary Shape

A future run summary under `docs/research/spikes/` should include:

- Status.
- Date.
- Contract Snapshot.
- Source Evidence.
- Harness Version.
- Case Matrix.
- Observed Capability Labels.
- Streaming Output Findings.
- Realtime Input Findings.
- Timestamp Normalization Findings.
- Non-Speech and Echo Risk Findings.
- Timeout / Retry / Cancellation / Late Output Findings.
- Replay-Safe Metadata Notes.
- Trace / Privacy Boundary.
- Fit to MVP-0 / MVP-1 / MVP-2 / MVP-3.
- Risks / Gaps.
- Recommendation.

The summary should not include audio recordings, provider request or response bodies, local traces, replay caches, request headers, real user input, or secret-bearing values.

## Acceptance Criteria

- The future harness is spike-local and does not import or modify MVP runtime modules.
- Dry-run works without provider access.
- JSONL output is metadata-only and schema-valid.
- Non-speech, echo, timeout, client close, cancellation, retry, and late-output cases are represented distinctly.
- Response streaming output is kept separate from true realtime microphone streaming input.
- Provider-confirmed cancellation is only marked observed when explicit evidence exists.
- Deterministic replay consumes metadata or synthetic fixtures and does not rerun ASR.
- Commit-safe summary output contains no audio recordings, provider bodies, local traces, replay caches, request headers, real user input, or secret-bearing values.

## Human Approval Gate

This plan is ready for human review as a future implementation task. Actual creation of `tools/model_spikes/asr_streaming_eval/` files, any live provider probe, and any generated local audio step require separate human approval.
