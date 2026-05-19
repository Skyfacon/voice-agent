# Thinker Qwen-Omni Eval Harness Plan

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
- Thinker-as-Composer boundary reference: ADR-009
- SlowTask lifecycle and confirmation reference: ADR-016
- Event and replay boundary references: `docs/specs/event-registry.md` and `docs/specs/replay-spec.md`

## Scope

This plan defines the next eval evidence needed before DashScope / Bailian Qwen-Omni can move closer to MVP-3 Thinker integration consideration.

In scope:

- A future spike-local Thinker eval harness design.
- Synthetic text, synthetic audio metadata, and ASR / Thinker conflict cases.
- SemanticFrame schema stability checks.
- Evidence provenance, ambiguity, missing-slot, emotion, audio-caption, intent-hint, slot-hint, and uncertainty checks.
- Provider-native tool proposal checks as proposal evidence only.
- Thinker-as-Composer protected-field checks.
- Streaming output, timeout, retry, cancellation, and late-output metadata.
- Replay-safe metadata policy and future JSONL observation shape.

Out of scope:

- No changes to `src/voice_agent/`, `tests/`, `docs/adr/`, or `docs/specs/`.
- No main runtime wiring.
- No real business adapter.
- No harness code in this step.
- No provider calls in this step.
- No committed audio recordings, provider bodies, local traces, local replay caches, real user input, request headers, or secret-bearing values.
- No claim that Qwen-Omni is ready for MVP-3 integration.

If approved later, implementation should remain spike-local, for example under `tools/model_spikes/thinker_eval/`, and must not import or call main runtime modules.

Qwen-Omni is a Thinker / SemanticFrame evidence provider. It is not the turn ingress owner, not the Router, not SlowTask, not the semantic truth owner, not the confirmation owner, and not the tool authorization or task completion owner.

## Source Evidence

Primary evidence:

- `docs/research/spikes/thinker-dashscope-qwen-omni-run-2026-05-11.md`
- `docs/research/profiles/thinker-qwen-omni-capability-profile-draft-2026-05-12.md`
- `docs/research/spikes/asr-qwen-asr-eval-harness-plan-2026-05-12.md`

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
- `docs/adr/ADR-009 SemanticCommitment and Thinker-as-Composer Contract.md`
- `docs/adr/ADR-011 Model Adapter Capability Contract.md`
- `docs/adr/ADR-016 SlowTask Lifecycle and Confirmation State Contract.md`

Evidence already observed:

- `qwen3.5-omni-plus` returned validated structured SemanticFrame JSON for synthetic text cases.
- Synthetic/local WAV Data URL audio input was accepted for Thinker evidence cases.
- Streaming text deltas were observed.
- Provider-native tool-call-like deltas were observed as proposal-shaped evidence only.
- Ambiguity, missing slot, conflicting evidence, synthetic web evidence, emotion, audio caption, and Composer-role protected-field cases produced metadata-only validation summaries.
- Full structured response latency was slow, around seconds to many seconds, and is not suitable for Duplex hot path decisions.
- Client timeout was observed, but provider-confirmed cancellation was not.

## Candidate Identity

| field | draft value | label | notes |
| --- | --- | --- | --- |
| `adapter_id` | `draft_thinker_dashscope_qwen_omni_eval_2026_05_12` | not_applicable | Eval plan id only; not a runtime adapter id. |
| `adapter_type` | `thinker`; `thinker_as_composer` for composer-role probes | observed_real | Matches the prior Qwen-Omni profile and run report. |
| `provider` | DashScope / Bailian | observed_real | Provider used in prior metadata-only run. |
| `model_name` | `qwen3.5-omni-plus` | observed_real / needs_recheck | Observed on 2026-05-11; re-pin official current alias before any future live run. |
| `deployment_mode` | `remote_api` | observed_real | Observed through DashScope OpenAI-compatible Chat Completions surface. |
| `endpoint` | `dashscope-compatible-chat-completions` | observed_real | Endpoint ref only, without secret-bearing data. |
| `output_mode` | `real` for prior validated frames; `degraded` for timeout, latency, and unconfirmed cancellation | observed_real / observed_degraded | Future harness must record output mode per case. |

## Eval Goals

The eval harness should answer these questions before any MVP-3 consideration:

- Can Qwen-Omni produce stable SemanticFrame JSON across synthetic text and audio-metadata cases?
- Does every SemanticFrame field preserve provenance and remain evidence rather than becoming `SemanticCommitment`?
- Can ASR / Thinker conflicts be preserved in an evidence pack without Router winner selection?
- Can ambiguity, missing required slots, and uncertainty be represented conservatively?
- Are emotion, audio caption, intent hint, and slot hints useful as evidence with confidence and degradation labels?
- Can synthetic webSearch / external evidence be held as `UNTRUSTED_WEB_EVIDENCE` only?
- Can provider-native tool proposals be normalized as proposal evidence without implying execution or authorization?
- Can Thinker-as-Composer preserve `immutable_facts`, `must_say_fields`, `resolved_arguments`, tool status, risk warnings, and confirmation state?
- What streaming output, timeout, retry, cancellation, and late-output metadata should a future adapter record?
- What minimum metadata-only JSONL shape is enough for deterministic replay without rerunning Qwen-Omni?

## Non-Goals

- Do not implement the harness in this document.
- Do not call a real provider in this step.
- Do not store or commit raw audio.
- Do not store or commit provider bodies.
- Do not create or modify runtime adapter code.
- Do not modify `tests/` or replay fixtures in this step.
- Do not evaluate real user recordings.
- Do not decide turn ingress, Router task focus, SlowTask state, confirmation, tool authorization, task completion, or final facts.
- Do not treat SemanticFrame as `SemanticCommitment`.
- Do not treat provider-native tool proposal deltas as Tool Executor execution.
- Do not compare non-Qwen Thinker candidates in this first plan.

## Synthetic Case Matrix

| case_id | input class | target observation | expected safe output | main risk covered |
| --- | --- | --- | --- | --- |
| `foreground_chat` | synthetic foreground text | SemanticFrame baseline, intent hint, slot hints, uncertainty | valid frame, provenance refs, evidence-only label | baseline Thinker evidence |
| `ambiguous_slot` | synthetic text with under-specified date/location/contact | missing slot preservation | insufficient-evidence fields, clarification candidate evidence | overconfident slot filling |
| `conflicting_asr_thinker_location` | ASR frame ref plus Thinker prompt context with different location evidence | ASR / Thinker conflict preservation | evidence pack with both refs; no winner | premature conflict arbitration |
| `missing_required_contact` | synthetic tool-like request lacking recipient/contact | missing critical argument evidence | blocking field evidence; no resolved argument | unsafe tool progression |
| `web_evidence_injection` | synthetic external evidence marked as webSearch result | untrusted evidence boundary | `UNTRUSTED_WEB_EVIDENCE`, `trusted_as_instruction=false` | external content as instruction |
| `emotion_text_hint` | synthetic user text with emotional cue | emotion evidence schema and uncertainty | emotion label/confidence/degradation as evidence | treating emotion as policy |
| `audio_caption_non_speech` | synthetic audio metadata for silence/non-speech | audio caption evidence and uncertainty | non-speech caption evidence; no directed input claim | non-speech false semantic frame |
| `audio_short_command` | synthetic short command audio metadata | audio input SemanticFrame stability | frame metadata with audio fixture refs only | audio metadata projection |
| `asr_silence_false_positive_with_thinker_uncertainty` | ASR transcript risk ref plus Thinker non-speech uncertainty | disagreement preservation | silence false positive risk plus Thinker uncertainty | ASR false positive treated as user intent |
| `tool_calling_proposal_probe` | provider-native tool proposal prompt | tool-call-like delta normalization | proposal evidence only; no execution event | tool proposal mistaken for execution |
| `composer_immutable_facts` | synthetic SemanticCommitment with immutable facts | protected-field preservation | spoken realization candidate plus unchanged facts summary | Composer fact rewrite |
| `composer_must_say_fields` | commitment with required statements | coverage preservation evidence | must-say coverage metadata | omitted required fields |
| `composer_risk_warning` | commitment with risk warning | risk warning preservation | risk warning preserved or failed coverage | warning removal |
| `composer_confirmation_state` | commitment requiring confirmation | pending confirmation expression | pending state preserved; no execution claim | confirmation invented by Composer |
| `semantic_close_probe` | synthetic partial / complete utterance examples | semantic-close evidence availability | availability/degradation only | unsupported field marked real |
| `assistant_directedness_probe` | directed, not-directed, and ambiguous metadata examples | directedness evidence availability | availability/degradation only | ingress ownership leak |
| `streaming_output_probe` | short structured output with streaming enabled | delta count, first delta latency, final schema result | streaming metadata plus valid/invalid parse status | response streaming stability |
| `client_timeout_probe` | tiny client timeout or simulated timeout metadata | adapter failure metadata | timeout category; no frame; no state advance | timeout mutation |
| `late_result_probe` | simulated or controlled late output after timeout/supersession | stale-friendly request binding | original request id plus stale/ignored label | late evidence advances current task |

All cases should use synthetic text, synthetic metadata, or local-only temporary audio if future implementation is approved. The committed report should store only metadata.

## Input Fixture Policy

Future harness input should be synthetic, deterministic, and privacy-safe.

Allowed future fixture sources:

- Hand-written synthetic text prompts.
- Synthetic ASR frame refs with transcript presence, confidence availability, timestamp availability, and known conflict fields.
- Synthetic audio metadata records for short command, silence, non-speech, and caption probes.
- Local-only temporary audio generated during an approved run, removed after metadata extraction.
- Synthetic `SemanticCommitment` objects for Composer boundary cases.
- Synthetic external evidence snippets explicitly marked as untrusted evidence.

Required fixture metadata:

- `case_id`
- `fixture_kind`
- `input_modality`
- `synthetic_text_ref` or `fixture_description_ref`
- optional `asr_frame_ref`
- optional `audio_fixture_ref`
- optional `semantic_commitment_ref`
- optional `external_evidence_ref`
- `contains_real_user_input=false`
- `contains_raw_audio_in_report=false`
- `contains_provider_body_in_report=false`
- `expected_owner_boundary`

Forbidden fixture behavior:

- No committed raw audio.
- No real user recordings.
- No unredacted user text.
- No provider bodies.
- No secret-bearing environment dumps or request metadata.
- No fixture content that implies a real external side effect.

## Expected Observation Schema

The future harness should emit one metadata-only JSON object per case, preferably JSONL. This is a proposed research schema, not a runtime `AdapterCapability` object.

```json
{
  "schema_version": "thinker_eval_observation_v1",
  "contract_snapshot": "main@61e6afc",
  "observation_id": "obs_thinker_qwen_eval_2026_05_12_foreground_chat_001",
  "case_id": "foreground_chat",
  "adapter_type": "thinker",
  "provider": "dashscope",
  "model_name": "qwen3.5-omni-plus",
  "deployment_mode": "remote_api",
  "endpoint_ref": "dashscope-compatible-chat-completions",
  "output_mode": "real_or_degraded",
  "role_contract": "thinker_semantic_frame",
  "input_fixture": {
    "fixture_kind": "synthetic_text",
    "input_modality": "text",
    "synthetic_text_ref": "thinker-fixture://synthetic/foreground_chat/001",
    "asr_frame_ref": null,
    "semantic_commitment_ref": null,
    "external_evidence_ref": null,
    "contains_real_user_input": false,
    "contains_raw_audio_in_report": false,
    "contains_provider_body_in_report": false
  },
  "request_observation": {
    "adapter_request_id": "adapter_req_synthetic_001",
    "streaming_output_requested": true,
    "streaming_input_mode": "text_or_data_url_or_metadata_only",
    "true_realtime_microphone_streaming_input_observed": false,
    "timeout_ms": 20000,
    "retry_count": 0
  },
  "semantic_frame_observation": {
    "schema_parse_passed": true,
    "schema_validation_passed": true,
    "semantic_frame_not_commitment": true,
    "provenance_preserved": true,
    "intent_hint_present": true,
    "slot_hints_present": true,
    "emotion_present": "available_or_unavailable",
    "audio_caption_present": "available_or_unavailable",
    "uncertainty_present": true,
    "semantic_close_present": "unknown_or_unavailable_or_eval_observed",
    "assistant_directedness_present": "unknown_or_unavailable_or_eval_observed"
  },
  "boundary_observation": {
    "router_selected_winner": false,
    "slowtask_required_for_resolved_arguments": true,
    "tool_executor_required_for_execution": true,
    "tool_proposal_only": true,
    "composer_protected_fields_preserved": null
  },
  "streaming_observation": {
    "streaming_output_observed": true,
    "delta_chunk_count": 42,
    "first_delta_ms": 500,
    "full_response_ms": 8000,
    "full_response_suitable_for_duplex_hot_path": false
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
- `adapter_type` must be `thinker` or `thinker_as_composer`.
- `output_mode` must distinguish `real`, `degraded`, `fallback`, or `mock` if used.
- `stored_audio`, `stored_provider_body`, and `stored_secret_material` must be false for commit-safe reports.
- `semantic_frame_not_commitment` must be true for SemanticFrame cases.
- Tool proposal cases must set `tool_proposal_only=true`.
- Composer cases must record protected-field comparison results and must not rely on model self-attestation alone.
- Realtime microphone streaming input must remain false or unknown unless directly exercised.

## SemanticFrame Schema Checks

Qwen-Omni can provide SemanticFrame evidence, but it must not directly produce `SemanticCommitment`.

Future eval should validate:

- Required top-level SemanticFrame fields are present.
- `intent_hint`, `slot_hints`, `emotion`, `audio_caption`, `utterance_summary`, `evidence_review`, `uncertainty`, and `degradation` fields follow the expected schema.
- Every evidence-bearing field carries source/provenance metadata or a clear unavailable marker.
- Missing slots remain missing or insufficient-evidence rather than guessed.
- Confidence and uncertainty are represented as evidence and do not become final facts.
- `output_mode` and degraded reasons are explicit.
- Schema validation failure produces validation-failure metadata, not downstream consumption.

SemanticFrame evidence must preserve provenance and cannot directly advance `resolved_arguments`.

Forbidden checks:

- Do not accept a valid JSON frame as a task commitment.
- Do not let a frame emit `SEMANTIC_COMMITMENT_EMITTED`.
- Do not let a frame decide confirmation, tool authorization, task completion, or SlowTask terminal outcome.

## ASR / Thinker Evidence Boundary Checks

ADR-008 requires ASR / Thinker differences to remain multi-source evidence for SlowTask-led review.

Future eval should verify:

- `conflicting_asr_thinker_location` keeps ASR and Thinker location evidence as separate refs.
- `asr_silence_false_positive_with_thinker_uncertainty` records the ASR false-positive risk without treating it as reliable directed input.
- Router-facing metadata may carry uncertainty, but must not select a field winner.
- SlowTask is the only owner that can review ambiguity and form `ARGUMENTS_RESOLVED`.
- Tool Executor blocks execution when resolved arguments or provenance are missing.

Rules:

- ASR transcript is evidence, not semantic truth.
- Thinker SemanticFrame is evidence, not semantic truth.
- ASR and Thinker conflicts enter the evidence pack.
- Router does not choose the winner.
- SlowTask owns conflict review, missing-slot review, resolved arguments, final facts, confirmation, and SemanticCommitment.

## Ambiguity / Missing Slot Checks

Future eval should include ambiguity and missing-required-field pressure:

- `ambiguous_slot`: under-specified date/location/contact should remain unresolved.
- `missing_required_contact`: recipient/contact must be marked missing or ambiguous.
- `conflicting_asr_thinker_location`: conflict must be preserved rather than collapsed.
- `foreground_chat`: low-risk foreground chat can be summarized without inventing task facts.

Expected metadata:

- `ambiguous_fields`
- `missing_fields`
- `field_provenance_refs`
- `uncertainty_reason`
- `needs_slowtask_review_candidate`
- `safe_to_resolve_arguments=false` when required data is missing

Forbidden outcomes:

- No guessed date, contact, location, amount, identity, or action argument.
- No direct `resolved_arguments`.
- No tool proposal treated as ready arguments.
- No confirmation inferred from ambiguous wording.

## Emotion / Audio Caption Checks

Emotion, audio caption, intent hint, slot hints, and uncertainty are evidence. They are not final facts.

Future eval should verify:

- `emotion_text_hint` emits emotion evidence with confidence/degradation metadata.
- `audio_caption_non_speech` emits conservative audio-caption evidence or unavailable metadata.
- `audio_short_command` can preserve audio fixture provenance while producing a valid frame.
- Non-speech audio caption evidence does not become assistant-directed input.
- Emotion evidence does not change confirmation, tool authorization, risk policy, or task completion.

Quality limits:

- The prior run observed schema presence, not calibrated quality.
- Future eval should label quality as `observed_degraded` until a larger fixture set exists.
- Missing emotion/audio-caption support should become unavailable/degraded evidence, not a default neutral value.

## Semantic Close / Assistant Directedness Checks

Semantic close and assistant directedness were not directly validated in the prior run report and must not be marked `observed_real` yet.

Future eval should design:

- `semantic_close_probe` with partial, complete, and ambiguous synthetic utterance examples.
- `assistant_directedness_probe` with directed, not-directed, playback-only, and ambiguous metadata examples.

Allowed conclusion after eval:

- `observed_real` only if the run directly validates stable evidence fields and records provenance.
- `observed_degraded` if fields exist but are unstable, low confidence, or partial.
- `unsupported` if the model does not provide usable fields.
- `unknown` if not exercised.

Boundary:

- Interaction Controller owns turn ingress.
- Duplex / Interaction policy owns whether a turn is opened, held, rejected, accepted, or committed.
- Thinker may provide evidence hints only if directly validated.
- Thinker must not own semantic close or assistant directedness as authority.

## Tool Proposal Checks

Provider-native tool proposal / tool-call-like deltas can only be proposal evidence. Tool Executor remains the only execution and authorization owner.

Future eval should verify:

- `tool_calling_proposal_probe` records proposal delta presence, proposal count, and schema-like shape.
- Proposal arguments are summarized or referenced safely rather than stored as executable arguments.
- No `TOOL_EXECUTION_STARTED`, `TOOL_EXECUTION_AUTHORIZED`, or UI patch event is implied by model output.
- Tool proposal evidence requires SlowTask resolved arguments and Tool Executor validation before any action in a future runtime.

Required proposal metadata:

- `tool_proposal_observed`
- `proposal_count`
- `proposal_shape_valid`
- `tool_executor_execution_observed=false`
- `authorization_owner=tool_executor`
- `proposal_arguments_stored=false` for commit-safe reports unless fully synthetic/minimized

Forbidden conclusions:

- Do not treat provider-native tool proposal as execution.
- Do not let Thinker authorize tools.
- Do not let Thinker patch UI state.
- Do not let Thinker bypass current-plan `task_id`, `plan_version`, `task_event_seq`, provenance, confirmation, or side-effect policy.

## Thinker-as-Composer Boundary Checks

Thinker-as-Composer may do spoken realization and expression fusion. It must not rewrite protected facts or state.

Future eval should include:

- `composer_immutable_facts`: protected facts must remain unchanged.
- `composer_must_say_fields`: required statements must be covered.
- `composer_risk_warning`: warnings must remain present and not softened into a false safety claim.
- `composer_confirmation_state`: pending confirmation must remain pending; accepted/rejected states must not be invented.

Checks:

- Compare output against synthetic `SemanticCommitment` fields.
- Verify `source_commitment_id` and source event refs remain intact.
- Verify `immutable_facts`, `must_say_fields`, `resolved_arguments`, tool status, risk warnings, and confirmation state are preserved.
- Verify stale or untrusted evidence is not expressed as current fact.
- Treat model self-report as insufficient; independent coverage/truthfulness checks remain required.

Forbidden outcomes:

- No changes to `immutable_facts`.
- No deletion of `must_say_fields`.
- No rewrite of `resolved_arguments`.
- No changed tool status.
- No removed risk warning.
- No inferred confirmation state.
- No claim that pending work is complete.

## Streaming Input / Output Checks

Streaming output:

- Prior run observed streaming text deltas and usage events.
- Future eval should record stream done status, delta count, first delta latency, final schema validity, and full response latency.
- Streaming text deltas may be marked `observed_real` when directly observed in the eval.

Streaming input:

- Prior run observed text input and synthetic/local audio input through request payload shape.
- True realtime microphone streaming input was not proven.
- Future eval should keep realtime microphone streaming input as a separate optional probe only after provider surface review and human approval.

Boundary:

- Response streaming output does not prove realtime audio streaming input.
- Data URL or local temporary audio input does not prove live microphone backpressure handling.
- Full response latency is slow and not suitable for Duplex hot path, speech-start detection, barge-in, or TTS truncate decisions.

## Timeout / Retry / Cancellation / Late Output Checks

Observed prior behavior:

- Client timeout occurred.
- Provider-confirmed cancellation was not observed.
- Retry was not exercised.

Future eval should cover:

| condition | future harness observation | required mapping |
| --- | --- | --- |
| `client_timeout_probe` | timeout category, elapsed bucket, no frame | adapter failure metadata; no state advance |
| transient provider failure | failure category and retryability | bounded retry metadata before final failure |
| malformed structured output | validation failure reasons | output validation failure metadata |
| provider-confirmed cancellation if available | explicit provider confirmation field | only then mark cancellation observed; otherwise degraded / unknown |
| client stream close without provider confirmation | close category only | degraded cancellation; do not claim success |
| `late_result_probe` | result arrives after timeout or superseded request | original request binding plus stale/ignored label |

Late output rules:

- Preserve original `adapter_request_id`, input fixture ref, case id, and output mode.
- If associated with a task in future integration, preserve original `task_id`, `plan_version`, and `task_event_seq`.
- Late output must not advance current task state.
- Reuse requires explicit SlowTask adopt/rebase in runtime; this eval plan only records metadata.

Retry rules:

- Retry count and reason must be explicit.
- Retries must not create duplicate SemanticFrame facts without causal binding.
- Final failure must remain replay-visible.

## Replay-Safe Metadata Shape

Deterministic replay must not rerun Qwen-Omni. Replay should consume recorded metadata, redacted refs, or synthetic fixtures.

Draft replay-safe bundle:

```json
{
  "replay_eval_manifest": {
    "manifest_schema_version": "1.0",
    "replay_id": "replay_thinker_qwen_eval_synthetic_001",
    "source_trace_ref": "thinker-eval://synthetic/qwen/2026-05-12",
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
  "thinker_eval_observations_ref": "thinker-eval-observations://synthetic/qwen/2026-05-12",
  "observation_count": 19,
  "rerun_provider_in_deterministic_replay": false
}
```

Replay-safe observations may include:

- invented ids;
- case ids;
- schema pass/fail flags;
- field presence flags;
- confidence/degradation labels;
- evidence provenance refs;
- stream event counts;
- latency buckets;
- timeout/failure categories;
- protected-field comparison summaries;
- proposal-only tool metadata;
- causal refs.

Replay-safe observations must not include:

- raw audio;
- provider bodies;
- real user input;
- request headers;
- secret-bearing values;
- local debug traces or replay caches;
- raw tool arguments unless fully synthetic/minimized.

## Trace / Privacy Boundary

The future eval harness should write only metadata summaries suitable for a research report.

Required privacy posture:

- Keep generated audio local-only and temporary.
- Store no audio recordings in GitHub-allowed output.
- Store no provider bodies.
- Store no request headers.
- Store no secret-bearing values.
- Store no real user recordings or real user text.
- Store no local debug traces or replay caches.
- Use synthetic ids, redacted refs, schema flags, latency buckets, and capability labels.

If future harness code writes local generated audio, it must use a temporary path outside the repo and remove it after the run. If future debugging needs local audio retention, that must be a separate explicit local-only step and remain outside commit scope.

## Fit to MVP-0 / MVP-1 / MVP-2 / MVP-3

MVP-0:

- Supports future replacement analysis for mock Thinker frame shape.
- Eval output can map to `MOCK_THINKER_FRAME_EMITTED`-style `semantic_frame_ref` metadata.
- Does not change MVP-0 runtime.
- Deterministic replay consumes metadata and does not rerun Qwen-Omni.

MVP-1:

- Thinker SemanticFrame can become one evidence source for Router uncertainty and SlowTask review.
- Eval should make provenance and stale-friendly request binding explicit.
- Thinker cannot directly advance `plan_version`, resolve arguments, adopt stale evidence, or mutate SlowTask state.

MVP-2:

- Qwen-Omni may support Thinker-as-Composer experiments only under strict role separation.
- It cannot authorize tools, confirm actions, patch UI, or drive demo tool execution.
- Composer outputs still require independent coverage/truthfulness checks before Talker playback.

MVP-3:

- This plan is a prerequisite for stronger Qwen-Omni integration consideration.
- MVP-3 consideration still needs executed eval results, schema stability, provider failure/cancellation mapping, streaming-input decision, and Composer boundary evidence.
- MVP-3 may replace mock adapters with real adapters only without adding architecture capability.

## Risks / Gaps

- Full structured response latency is too slow for Duplex hot path.
- True realtime microphone streaming input is not proven.
- Audio timestamp output is not proven for this Thinker role.
- Provider-confirmed cancellation is not proven.
- Retry behavior is unknown.
- Semantic close and assistant directedness are not directly validated.
- Emotion and audio-caption evidence are schema-observed but not quality-calibrated.
- Composer-role safety is preliminary and cannot replace independent coverage/truthfulness checks.
- Provider-native tool-call-like deltas can be misread as execution unless the proposal-only boundary is explicit.
- Current official model alias, limits, modality rules, and service behavior must be rechecked before hardening.
- No committed replay/eval fixture should be created until the harness design is approved.

## Recommendation

Approve this Thinker eval harness plan as the next research step before further Qwen-Omni profile hardening.

Recommended evaluation priority:

1. Run schema and evidence-boundary cases first: `foreground_chat`, `ambiguous_slot`, `conflicting_asr_thinker_location`, `missing_required_contact`, and `web_evidence_injection`.
2. Run multimodal/evidence-quality cases: `emotion_text_hint`, `audio_caption_non_speech`, `audio_short_command`, and `asr_silence_false_positive_with_thinker_uncertainty`.
3. Run tool and Composer boundary cases: `tool_calling_proposal_probe`, `composer_immutable_facts`, `composer_must_say_fields`, `composer_risk_warning`, and `composer_confirmation_state`.
4. Run unsupported-or-unknown evidence probes: `semantic_close_probe`, `assistant_directedness_probe`, and optional streaming-input review if separately approved.
5. Run streaming output, timeout, retry, cancellation, and late-output checks last, with explicit provider access approval.

Do not proceed to runtime integration from this plan. Treat Qwen-Omni as promising but not yet MVP-3 ready.

## Next Implementation Step, Gated on Human Approval

After human approval, create a spike-local implementation plan for `tools/model_spikes/thinker_eval/` without touching runtime modules.

Proposed future files:

- `tools/model_spikes/thinker_eval/README.md`
- `tools/model_spikes/thinker_eval/requirements.txt`
- `tools/model_spikes/thinker_eval/run_qwen_omni_eval.py`
- `tools/model_spikes/thinker_eval/schemas/thinker_eval_observation.schema.json`
- `tools/model_spikes/thinker_eval/runs/README.md`

Future implementation constraints:

- keep generated audio under a local temporary path;
- emit metadata-only JSONL;
- validate each observation against a small schema;
- summarize observations into `docs/research/spikes/`;
- never import main runtime modules;
- never write provider bodies;
- require explicit human approval before any provider call.
