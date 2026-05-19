# ASR Qwen-ASR Eval Harness Plan

## Status

planned_research_eval_harness_metadata_only_no_code

This document is a research eval harness plan. It is not runtime integration, not harness implementation, not a business adapter, and not approval to modify MVP runtime behavior.

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

This plan defines the next eval evidence needed before DashScope / Bailian Qwen-ASR can move closer to MVP-3 integration consideration.

In scope:

- A future spike-local ASR eval harness design.
- Synthetic audio and metadata-only observation cases.
- Expected observation schema and JSONL shape.
- Transcript, silence/non-speech, timestamp, streaming, confidence, retry, timeout, cancellation, and late-output checks.
- Replay-safe metadata policy.
- ASR / Thinker / Interaction / Router / SlowTask ownership boundaries.

Out of scope:

- No changes to `src/voice_agent/`, `tests/`, `docs/adr/`, or `docs/specs/`.
- No main runtime wiring.
- No real business adapter.
- No harness code in this step.
- No provider calls in this step.
- No committed audio recordings, provider request/response bodies, local traces, local replay caches, real user input, request headers, or secret-bearing values.
- No claim that Qwen-ASR is ready for MVP-3 integration.

If approved later, implementation should remain spike-local, for example under `tools/model_spikes/asr_eval/`, and must not import or call main runtime modules.

## Source Evidence

Primary evidence:

- `docs/research/spikes/asr-dashscope-bailian-run-2026-05-11.md`
- `docs/research/profiles/asr-qwen-asr-capability-profile-draft-2026-05-12.md`

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

Evidence already observed:

- `qwen3-asr-flash` returned final transcript-like evidence for short synthetic audio.
- The chat surface produced response streaming deltas for a short command.
- `qwen3-asr-flash-filetrans` produced timestamp-like and word-like structures through async file transcription.
- A one-second silence input produced a short non-empty transcript-like output, which is degraded / risk evidence.
- Client timeout was observed, but provider-confirmed cancellation was not.

## Candidate Identity

| field | draft value | label | notes |
| --- | --- | --- | --- |
| `adapter_id` | `draft_asr_dashscope_qwen_asr_eval_2026_05_12` | not_applicable | Eval plan id only; not a runtime adapter id. |
| `adapter_type` | `asr` | observed_real | Role matches the executed Qwen-ASR probe. |
| `provider` | DashScope / Bailian | observed_real | Provider used in prior metadata-only run. |
| `model_name` | `qwen3-asr-flash`; `qwen3-asr-flash-filetrans` | observed_real / needs_recheck | Observed on 2026-05-11; re-pin official current aliases before any future live run. |
| `deployment_mode` | `remote_api` | observed_real | Observed through DashScope remote API surfaces. |
| `endpoint` | `dashscope-compatible-chat-completions`; `dashscope-audio-asr-transcription`; `dashscope-task-polling` | observed_real | Endpoint refs only, without secret-bearing data. |
| `output_mode` | `real` for prior successful observations; `degraded` for timeout and silence risk | observed_real / observed_degraded | Future harness must record output mode per case. |

Qwen-ASR is an ASR / text projection evidence provider. It is not the turn ingress owner, not the Router, not SlowTask, and not the semantic truth owner.

## Eval Goals

The eval harness should answer these questions before any MVP-3 consideration:

- Can Qwen-ASR reliably produce transcript/text projection evidence for short commands, mixed language, clipped starts, low-volume speech, and longer utterances?
- How often do silence, pure tones, white noise, background speech, or playback-only echo produce non-empty transcript-like output?
- Can output be normalized into replay-safe ASR evidence refs without storing audio or provider bodies?
- What timestamp structures exist across chat annotations and filetrans word-like arrays, and can they be normalized consistently?
- Does response streaming output provide useful partial/final evidence metadata, and what latency bucket does it occupy?
- Is true realtime microphone streaming input supported, or must it remain unknown / degraded?
- Are confidence, n-best, language, punctuation, and ITN fields available enough to drive conservative evidence labels?
- How do timeout, retry, cancellation, malformed output, async task failure, and late output map to adapter metadata?
- What minimum synthetic fixture shape is enough for deterministic replay without rerunning Qwen-ASR?

## Non-Goals

- Do not implement the harness in this document.
- Do not call a real provider in this step.
- Do not store or commit raw audio.
- Do not store or commit provider request/response bodies.
- Do not create or modify runtime adapter code.
- Do not modify `tests/` or replay fixtures in this step.
- Do not evaluate real user recordings.
- Do not decide turn ingress, semantic close, assistant directedness, confirmation, tool authorization, or task completion.
- Do not treat transcript text as `SemanticCommitment`.
- Do not compare self-hosted ASR candidates in this first plan; comparison can follow after Qwen-ASR harness shape is stable.

## Synthetic Case Matrix

| case_id | input class | target observation | expected safe output | main risk covered |
| --- | --- | --- | --- | --- |
| `short_command` | synthetic short Mandarin command | final transcript-like output, latency, annotations | transcript length, redacted/synthetic snippet optional, timing bucket | baseline ASR evidence |
| `mixed_language` | synthetic Mandarin/English phrase | language handling, punctuation/ITN behavior | transcript length, language hints if present | mixed-language robustness |
| `clipped_start` | synthetic command with first 200-400ms removed | partial word loss, evidence degradation | transcript length, missing-start flag, quality label | barge-in clipped audio |
| `one_second_silence` | generated silence | should not become reliable directed input | non-empty transcript flag, degraded label | silence false positive |
| `pure_tone_non_speech` | generated sine tone | non-speech rejection or degraded transcript | transcript presence flag, low-confidence/degraded label | acoustic false positive |
| `white_noise_non_speech` | seeded white noise | non-speech rejection or degraded transcript | transcript presence flag, low-confidence/degraded label | noise false positive |
| `background_speech_not_directed` | synthetic background-style speech fixture or metadata substitute | transcript may exist but directedness remains outside ASR | transcript presence plus `directedness_owner=interaction_or_duplex` | non-assistant speech |
| `playback_only_echo` | playback reference plus echo-like captured audio or metadata substitute | ASR may transcribe playback, but it is not user input | echo context flag, transcript presence, degraded ingress suitability | echo false turn risk |
| `user_speech_over_playback` | synthetic foreground speech mixed with playback reference | transcript evidence under overlap | overlap flags, transcript length, timing bucket | barge-in-like overlap |
| `longer_utterance` | synthetic 10-30s utterance | latency, truncation, timestamp quality | duration bucket, transcript length, timestamp coverage | longer context behavior |
| `low_volume_speech` | attenuated synthetic speech | robustness and confidence behavior | transcript presence, confidence availability, degradation label | low SNR input |
| `timestamp_probe` | filetrans-compatible synthetic or approved public sample | segment/word timing structure | normalized timestamp fields and units | timestamp normalization |
| `streaming_output_probe` | short command with response streaming | delta count, first delta, final transcript | chunk counts and latency buckets | streaming output evidence |
| `client_timeout_probe` | request with tiny client timeout | timeout metadata only | failure category, retryable flag, no transcript | timeout behavior |
| `late_result_probe` | simulated or controlled late result after timeout or superseded request | stale-friendly binding | original request id, stale/ignored label | late output handling |

All synthetic audio generation, if later implemented, should write only to local temporary storage and remove files after extracting metadata. The committed plan/report should store only metadata.

## Input Fixture Policy

Future harness input should be synthetic, deterministic, and privacy-safe.

Allowed future fixture sources:

- Locally generated silence, tone, seeded white noise, and simple speech-like clips.
- Locally generated synthetic speech from approved non-user text, stored only under a local temporary path during the run.
- Provider-approved public sample URL for filetrans timestamp structure, if documented and safe to cite.
- Metadata substitutes for playback reference and background directedness cases when raw audio would add privacy or implementation risk.

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
- `contains_raw_audio_in_report=false`
- optional `playback_reference_ref`
- optional `expected_non_speech=true`
- optional `expected_directedness_owner=interaction_or_duplex`

Forbidden fixture behavior:

- No committed raw audio.
- No real user recordings.
- No unredacted user text.
- No provider request/response bodies.
- No secret-bearing environment dumps or request metadata.
- No fixture content that implies a real external side effect.

## Expected Observation Schema

The future harness should emit one metadata-only JSON object per case, preferably JSONL. This is a proposed research schema, not a runtime `AdapterCapability` object.

```json
{
  "schema_version": "asr_eval_observation_v1",
  "contract_snapshot": "main@61e6afc",
  "observation_id": "obs_asr_qwen_eval_2026_05_12_short_command_001",
  "case_id": "short_command",
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
    "contains_raw_audio_in_report": false,
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
    "redacted_or_synthetic_snippet_ref": "asr-snippet://synthetic/short_command/001",
    "reliable_directed_user_input": false
  },
  "timestamp_observation": {
    "timestamp_source": "chat_annotations_or_filetrans_words_or_unavailable",
    "units": "ms_or_seconds_or_unknown",
    "segment_count": 0,
    "word_count": 0,
    "normalized": false,
    "degraded_reason": "not_normalized_yet"
  },
  "streaming_observation": {
    "response_streaming_output_observed": false,
    "delta_chunk_count": 0,
    "first_delta_ms": null,
    "true_realtime_microphone_streaming_input_observed": false
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
    "punctuation_available": "unknown"
  },
  "failure_observation": {
    "failure_category": null,
    "retryable": null,
    "provider_confirmed_cancellation": "unknown",
    "late_output_policy": "not_applicable"
  },
  "privacy": {
    "stored_audio": false,
    "stored_provider_body": false,
    "stored_secret_material": false
  }
}
```

Required validation rules for future JSONL:

- `schema_version`, `contract_snapshot`, `observation_id`, `case_id`, `adapter_type`, `provider`, `model_name`, `deployment_mode`, `endpoint_ref`, and `output_mode` are required.
- `adapter_type` must be `asr`.
- `output_mode` must distinguish `real`, `degraded`, `fallback`, or `mock` if used.
- `stored_audio`, `stored_provider_body`, and `stored_secret_material` must be false for commit-safe reports.
- Any non-speech case with transcript text must set `non_speech_transcript_risk=true` and `reliable_directed_user_input=false`.
- Timestamp fields may be unavailable, but unavailable timing must be explicit rather than invented.
- Realtime microphone streaming input must remain false or unknown unless directly exercised.

## Transcript / Text Projection Checks

Transcript evidence checks:

- Record whether transcript-like output exists.
- Record transcript length and optional synthetic/redacted snippet ref.
- Record output mode and case-specific degradation label.
- Record whether transcript was produced from non-streaming, response streaming, file URL, or future realtime input.
- Record whether adapter normalization succeeded into an ASR-frame-like metadata shape.

Transcript evidence must not:

- become final user intent;
- create `SemanticCommitment`;
- resolve arguments;
- accept confirmation;
- authorize or execute tools;
- open, accept, or commit a turn by itself;
- choose a winner when ASR and Thinker evidence disagree.

Acceptance for eval evidence:

- `short_command`, `mixed_language`, `clipped_start`, `longer_utterance`, and `low_volume_speech` should produce measurable text projection evidence or explicit degraded/failure metadata.
- Non-speech and playback-only cases may produce transcript-like text, but those outputs must be marked degraded / risk evidence.
- Transcript presence alone is not a pass condition for user-facing behavior.

## Silence / Non-Speech Checks

The prior run observed a one-second silence input producing a short non-empty transcript-like output. The future eval must treat that as a first-class risk.

Required checks:

- `one_second_silence`: record transcript presence, length, and degradation label.
- `pure_tone_non_speech`: record whether deterministic tone produces transcript-like output.
- `white_noise_non_speech`: record whether seeded noise produces transcript-like output.
- `background_speech_not_directed`: record transcript presence but keep directedness outside ASR.
- `playback_only_echo`: record whether playback-only input produces transcript-like output and require playback-reference context.

Required flags:

- `expected_non_speech=true`
- `non_speech_transcript_risk=true` if transcript exists
- `reliable_directed_user_input=false`
- `ingress_owner=Interaction Controller`
- `semantic_truth_owner=SlowTask for complex tasks`

Forbidden conclusions:

- Do not treat non-empty silence/non-speech transcript as reliable directed user input.
- Do not let ASR output independently open or commit a turn.
- Do not use ASR transcript to infer assistant directedness.
- Do not use ASR transcript to infer semantic close.

## Timestamp Normalization Checks

Timestamp evidence is alignment evidence. It is not user intent, confirmation, task progress, or final fact.

The future eval should normalize these candidate timestamp sources:

- Chat annotations from `qwen3-asr-flash`.
- Filetrans timestamp-like fields from `qwen3-asr-flash-filetrans`.
- Word-like arrays when `enable_words=true`.
- Missing or malformed timing as explicit unavailable/degraded metadata.

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

Checks:

- Units must be explicit.
- Offset basis must be explicit.
- Segment and word counts must be recorded.
- Negative, overlapping, or descending offsets must fail normalization.
- Missing timing should produce `normalization_status=unavailable`, not invented offsets.
- Timestamp availability can support eval assertions and replay-safe refs, but cannot become semantic truth.

## Streaming Input / Output Checks

Response streaming output:

- Already observed for `short_command_streaming`.
- Future eval should record stream done status, delta count, first delta latency, final transcript length, annotations presence, and output mode.
- This can be marked as response-layer streaming output evidence after normalization.

Realtime microphone streaming input:

- Not proven by prior run.
- The eval plan should keep this as a separate future probe.
- A future realtime probe, if approved and supported by the provider surface, should record input chunk duration, input cadence, backpressure behavior, first partial timing, final transcript timing, and stream close behavior.

Boundary:

- Response streaming output must not be expanded into a claim that realtime microphone streaming input works.
- Data URL and file URL input are observed audio-input modes, not realtime microphone streaming.
- Streaming ASR output remains evidence; it is not turn ingress ownership.

## Confidence / N-best / Language / Punctuation Checks

The prior run did not validate confidence quality, n-best alternatives, language detection, punctuation, or ITN behavior.

Future eval should record availability rather than assuming support:

| capability | check | output label |
| --- | --- | --- |
| confidence | Does provider output confidence at segment, word, utterance, or metadata level? | `observed_real`, `observed_degraded`, `unsupported`, or `unknown` |
| n-best | Does provider expose alternatives? | availability plus count only; no raw alternatives required |
| language | Does provider expose language or language confidence? | language label, confidence availability, degradation |
| punctuation | Does output contain punctuation or a punctuation flag? | punctuation mode and observed text-length effect |
| ITN | Compare `enable_itn=false` and a future `enable_itn=true` case if approved | normalization effect and risk label |

Rules:

- Absence of confidence must not default to high confidence.
- Absence of language metadata must not default to known language.
- Absence of n-best must not collapse uncertainty.
- Punctuation and ITN are transcript formatting evidence, not semantic truth.
- Low confidence or unavailable confidence should support conservative downstream evidence labels.

## Timeout / Retry / Cancellation / Late Output Checks

Observed prior behavior:

- Client timeout occurred.
- Provider-confirmed cancellation was not observed.
- Retry was not exercised.

Future eval should cover:

| condition | future harness observation | required mapping |
| --- | --- | --- |
| `client_timeout_probe` | timeout category, elapsed bucket, no transcript | adapter failure metadata; no state advance |
| transient provider failure | failure category and retryability | bounded retry metadata before final failure |
| malformed provider output for normalized schema | validation failure reasons | output validation failure metadata |
| async filetrans task failure | task status, failure category | adapter failure metadata |
| provider-confirmed cancellation if available | explicit provider confirmation field | only then mark cancellation observed; otherwise degraded / unknown |
| client stream close without provider confirmation | close category only | degraded cancellation; do not claim success |
| `late_result_probe` | result arrives after timeout or superseded request | original request binding plus stale/ignored label |

Late output rules:

- Preserve original `adapter_request_id`, audio ref, input fixture ref, and case id.
- If associated with a task in future integration, preserve original `task_id`, `plan_version`, and `task_event_seq`.
- Late output must not advance current task state.
- Reuse requires explicit SlowTask adopt/rebase in runtime; this eval plan only records metadata.

Retry rules:

- Retry count and reason must be explicit.
- Retries must not create duplicate ASR frame facts without causal binding.
- Final failure must remain replay-visible.

## ASR / Thinker Evidence Boundary Notes

Qwen-ASR is an ASR / text projection evidence provider. It is not the turn ingress owner, not the Router, not SlowTask, and not the semantic truth owner.

ASR output may provide:

- transcript or text projection evidence;
- optional transcript hints;
- optional timing alignment metadata;
- optional confidence, n-best, language, punctuation, or ITN metadata if observed;
- provenance refs for SlowTask evidence review.

ASR output must not provide:

- `SemanticCommitment`;
- final resolved arguments;
- final task facts;
- confirmation acceptance or rejection;
- tool authorization or execution;
- task completion;
- semantic close;
- assistant directedness;
- turn ingress commitment.

ASR / Thinker conflicts:

- ASR and Thinker evidence should remain separate.
- Router may carry uncertainty but must not select field winners.
- SlowTask owns ambiguity/conflict review for complex tasks.
- Tool Executor must block execution when resolved arguments or provenance are missing.

Silence/non-speech:

- A non-empty transcript from silence/non-speech is degraded / risk evidence.
- It cannot be treated as reliable directed user input.
- It should support low-confidence or degraded ingress diagnostics, not direct state progress.

## Replay-Safe Metadata Shape

Deterministic replay must not rerun Qwen-ASR. Replay should consume recorded metadata, redacted refs, or synthetic fixtures.

Draft replay-safe bundle:

```json
{
  "replay_eval_manifest": {
    "manifest_schema_version": "1.0",
    "replay_id": "replay_asr_qwen_eval_synthetic_001",
    "source_trace_ref": "asr-eval://synthetic/qwen/2026-05-12",
    "replay_mode": "deterministic",
    "event_schema_version_range": ["1.0"],
    "fixture_domain": "GITHUB_ALLOWED",
    "generated_from": "synthetic",
    "contains_raw_audio": false,
    "contains_raw_trace": false,
    "contains_real_user_input": false,
    "contains_secrets": false,
    "contains_unredacted_tool_result": false,
    "contains_large_raw_web_content": false,
    "allowed_re_eval_components": []
  },
  "asr_eval_observations_ref": "asr-eval-observations://synthetic/qwen/2026-05-12",
  "observation_count": 15,
  "rerun_provider_in_deterministic_replay": false
}
```

Replay-safe observations may include:

- invented ids;
- case ids;
- transcript presence flags;
- transcript lengths;
- short synthetic/redacted snippet refs if needed;
- timestamp availability and normalized timing metadata;
- stream event counts;
- latency buckets;
- confidence availability flags;
- degradation labels;
- failure categories;
- causal refs.

Replay-safe observations must not include:

- raw audio;
- provider request/response bodies;
- real user input;
- request headers;
- secret-bearing values;
- unredacted full transcripts from real inputs;
- local debug traces or replay caches.

## Trace / Privacy Boundary

The future eval harness should write only metadata summaries suitable for a research report.

Required privacy posture:

- Keep generated audio local-only and temporary.
- Store no audio recordings in GitHub-allowed output.
- Store no provider request/response bodies.
- Store no request headers.
- Store no secret-bearing values.
- Store no real user recordings or real user text.
- Store no local debug traces or replay caches.
- Use synthetic ids, redacted refs, transcript lengths, timing buckets, and capability labels.

If future harness code writes local generated audio, it must use a temporary path outside the repo and remove it after the run. If future debugging needs local audio retention, that must be a separate explicit local-only step and remain outside commit scope.

## Fit to MVP-0 / MVP-1 / MVP-2 / MVP-3

MVP-0:

- Supports future replacement analysis for mock ASR frame shape.
- Eval output can map to `MOCK_ASR_FRAME_EMITTED`-style `asr_frame_ref` metadata.
- Does not change MVP-0 runtime.
- Deterministic replay consumes metadata and does not rerun Qwen-ASR.

MVP-1:

- ASR transcript can become one evidence source for UserPatch / SlowTask review.
- Eval should make late-output and stale-friendly request binding explicit.
- ASR cannot directly advance `plan_version`, resolve arguments, adopt stale evidence, or mutate SlowTask state.

MVP-2:

- ASR cannot authorize tools, confirm actions, patch UI, or drive demo tool execution.
- Tool-relevant transcript evidence must pass through Interaction, Router, UserPatch, SlowTask review, and Tool Executor authorization.
- Silence/non-speech false positives must be evaluated before any confirmation or tool-related flow relies on ASR evidence.

MVP-3:

- This plan is a prerequisite for stronger Qwen-ASR integration consideration.
- MVP-3 consideration still needs executed eval results, timestamp normalization, provider failure/cancellation mapping, and true realtime input decision.
- MVP-3 may replace mock adapters with real adapters only without adding architecture capability.

## Risks / Gaps

- True realtime microphone streaming input may remain unsupported or provider-surface-specific.
- Silence/non-speech false positives are already observed as a risk.
- Playback-only echo may produce transcript evidence that is not user input.
- Confidence, n-best, language, punctuation, and ITN support may be missing or inconsistent across surfaces.
- Timestamp structures may differ between chat annotations and filetrans outputs.
- Client timeout does not prove provider-confirmed cancellation.
- Retry behavior is unknown.
- Async filetrans task failure behavior is unknown.
- Longer utterances and low-volume inputs may change latency and quality materially.
- Synthetic audio may not represent real device acoustics.
- No committed replay/eval fixture should be created until the harness design is approved.

## Recommendation

Approve this ASR eval harness plan as the next research step before further ASR profile hardening.

Recommended evaluation priority:

1. Run the non-speech and echo-risk cases first: `one_second_silence`, `pure_tone_non_speech`, `white_noise_non_speech`, `background_speech_not_directed`, and `playback_only_echo`.
2. Run core transcript cases: `short_command`, `mixed_language`, `clipped_start`, `longer_utterance`, and `low_volume_speech`.
3. Run timestamp and streaming checks: `timestamp_probe` and `streaming_output_probe`.
4. Run timeout, retry, cancellation, and late-output checks last, with explicit provider access approval.

Do not proceed to runtime integration from this plan. Treat Qwen-ASR as promising but not yet MVP-3 ready.

## Next Implementation Step, Gated on Human Approval

After human approval, create a spike-local implementation plan for `tools/model_spikes/asr_eval/` without touching runtime modules.

Proposed future files:

- `tools/model_spikes/asr_eval/README.md`
- `tools/model_spikes/asr_eval/requirements.txt`
- `tools/model_spikes/asr_eval/generate_synthetic_audio.py`
- `tools/model_spikes/asr_eval/run_qwen_asr_eval.py`
- `tools/model_spikes/asr_eval/schemas/asr_eval_observation.schema.json`
- `tools/model_spikes/asr_eval/runs/README.md`

Future implementation constraints:

- keep all generated audio under a local temporary path;
- emit metadata-only JSONL;
- validate each observation against a small schema;
- summarize observations into `docs/research/spikes/`;
- never import main runtime modules;
- never write provider request/response bodies;
- require explicit human approval before any provider call.
