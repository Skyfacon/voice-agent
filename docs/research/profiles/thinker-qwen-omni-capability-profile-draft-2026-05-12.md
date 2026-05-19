# Thinker Qwen-Omni Capability Profile Draft

## Status

draft_research_profile_metadata_only

This is a research capability profile draft. It is not runtime integration, not a business adapter implementation, and not approval to modify MVP runtime behavior.

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

This profile summarizes the already executed DashScope / Bailian Qwen-Omni Thinker probe as adapter-shaped research evidence.

In scope:

- Qwen-Omni as a Thinker / SemanticFrame evidence provider candidate.
- Text input, synthetic/local audio input, streaming text deltas, structured SemanticFrame JSON, emotion evidence, audio-caption evidence, uncertainty preservation, and provider-native tool proposal deltas observed in the metadata-only run report.
- Mapping to ADR-011 capability matrix fields.
- Mapping to ADR-008 ASR / Thinker evidence fusion boundaries.
- Mapping to ADR-009 Thinker-as-Composer boundaries.
- Replay-safe metadata and privacy boundaries.
- Gaps that must be closed before MVP-3 integration consideration.

Out of scope:

- No changes to `src/voice_agent/`, `tests/`, `docs/adr/`, or `docs/specs/`.
- No main runtime wiring.
- No real business adapter.
- No live provider call in this profile step.
- No committed audio recordings, provider response bodies, traces, replay caches, real user input, request headers, authorization header, API key, token, cookie, credential, or secret values.
- No provider-native tool execution.

Qwen-Omni is a Thinker / SemanticFrame evidence provider. It is not the turn ingress owner, not the Router, not SlowTask, not the semantic truth owner, not the confirmation owner, and not the tool authorization or task completion owner.

## Source Evidence

Primary evidence:

- `docs/research/spikes/thinker-dashscope-qwen-omni-run-2026-05-11.md`

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

Evidence limits:

- The primary run report is metadata-only.
- It records HTTP status, parser/schema pass/fail, stream event counts, latency values, safety summaries, and redacted failure categories.
- It does not store raw provider payload, raw audio, full transcripts, tool-call arguments, local traces, or local replay caches.
- It does not prove realtime microphone streaming input, audio timestamps, semantic close, assistant directedness, provider-confirmed cancellation, or Composer safety enforcement.

## Candidate Identity

| field | draft value | label | notes |
| --- | --- | --- | --- |
| `adapter_id` | `draft_thinker_dashscope_qwen_omni_2026_05_12` | not_applicable | Draft profile id only; not a runtime adapter id. |
| `adapter_type` | `thinker`; `thinker_as_composer` only for the separate Composer-role method | observed_real | Role matches the executed Thinker probe and the separate Composer safety case. |
| `provider` | DashScope / Bailian | observed_real | Provider used in the executed run. |
| `model_name` | `qwen3.5-omni-plus` | observed_real | Observed on 2026-05-11; recheck the exact model alias before hardening. |
| `deployment_mode` | `remote_api` | observed_real | Observed through the DashScope OpenAI-compatible Chat Completions surface. |
| `endpoint` | `dashscope-compatible-chat-completions` | observed_real | Endpoint ref only; no secret-bearing values. |
| `output_mode` | `real` for validated frames; `degraded` for timeout and unconfirmed cancellation | observed_real / observed_degraded | Runtime use would still need adapter event recording. |

## Capability Matrix Draft

Labels used here: `observed_real`, `observed_degraded`, `unsupported`, `unknown`, `not_applicable`, `docs_only_unobserved`.

| ADR-011 field | draft label | draft value / behavior | evidence and notes |
| --- | --- | --- | --- |
| `adapter_type` | observed_real | `thinker`; optional method profile `thinker_as_composer` | Executed as SemanticFrame and Composer-role safety probes. |
| `provider` | observed_real | `dashscope` / Bailian | Run report executed against DashScope / Bailian. |
| `model_name` | observed_real | `qwen3.5-omni-plus` | Observed on 2026-05-11; re-pin current alias before hardening. |
| `deployment_mode` | observed_real | `remote_api` | OpenAI-compatible Chat Completions surface. |
| `endpoint` | observed_real | `dashscope-compatible-chat-completions` | Endpoint ref without secret-bearing request data. |
| `health_status` | observed_real | `healthy_for_observed_thinker_probe` | HTTP 200 for validated text, audio, Composer-role, and tool proposal cases. |
| `capability_version` | not_applicable | `research_observation_v1` | Research profile version, not a runtime capability schema. |
| `latency_class` | observed_degraded | first text about 359ms to 920ms; full structured streams about 6.2s to 18.8s | First delta can support evidence flow; full response latency is too slow for Duplex hot path. |
| `error_model` | observed_degraded | schema validation failure, safety violation, provider error, client timeout, unconfirmed cancellation | Schema passed in observed cases; timeout was client-side only. |
| `timeout_policy` | observed_degraded | adapter-owned timeout metadata; no state advance | Client timeout observed; provider-confirmed cancellation not observed. |
| `retry_policy` | unknown | bounded schema repair should mirror Slow LLM profile; not exercised here | This Thinker run did not exercise schema repair retry. |
| `output_mode` | observed_real / observed_degraded | `real` for validated frames; `degraded` for timeout or missing capability | Output mode is evidence labeling only, not runtime integration. |
| `supports_streaming_input` | observed_degraded / unknown | Data URL audio input observed; true realtime microphone streaming input not exercised | Do not widen audio file/Data URL input into realtime mic streaming support. |
| `supports_streaming_output` | observed_real | SSE text deltas and usage events observed | Streaming output was observed for every successful request. |
| `supports_audio_input` | observed_real | true for synthetic/local WAV Data URL input | Short synthetic Mandarin command and silence WAV Data URL were accepted. |
| `supports_audio_output` | unsupported | false for this Thinker method | `modalities: ["text"]` was used; no audio output was requested or received. |
| `supports_audio_timestamps` | unknown | not observed for Qwen-Omni Thinker output | Use runtime event/audio span timing if model timing is unavailable. |
| `supports_structured_json` | observed_real | true for validated SemanticFrame and Composer-role JSON | All text and audio SemanticFrame cases parsed and passed the minimal schema. |
| `supports_tool_calling` | observed_real | provider-native tool-call-like deltas observed as proposal evidence only | Tool Executor remains the only execution and authorization owner. |
| `supports_cancellation` | observed_degraded / unknown | client timeout observed; provider-confirmed cancellation not observed | Do not claim cancel success without provider confirmation. |
| `supports_emotion` | observed_real / observed_degraded | emotion evidence schema observed; quality not evaluated | Emotion is evidence with confidence, not policy or final fact. |
| `supports_audio_caption` | observed_real / observed_degraded | audio-caption-style evidence observed for silence/non-speech; quality not evaluated | Audio caption is evidence, not final fact. |
| `supports_tts` | unsupported | false for this Thinker role | TTS belongs to TTS / Talker adapter candidates. |
| `supports_tts_truncate` | not_applicable | false | TTS truncate is Talker/playback-owned, not Thinker-owned. |
| `supports_tts_pause_resume` | not_applicable | false | Pause/resume is outside this Thinker role and MVP non-goal. |
| `supports_semantic_close` | unknown | not directly exercised as model evidence | Unsupported as authority; do not mark observed_real. |
| `supports_assistant_directedness` | unknown | not directly exercised as model evidence | Unsupported as authority; do not mark observed_real. |
| `max_audio_seconds` | unknown | recheck official limit during profile hardening | The run used short synthetic WAV Data URLs only. |
| `max_context_tokens` | unknown | recheck official limit during profile hardening | Not pinned in this run report. |
| `max_output_tokens` | observed_real / unknown | probe used `max_tokens: 900`; official limit not pinned | Recheck official maximum before profile hardening. |
| `expected_first_token_latency_ms` | observed_real | about 359ms to 920ms for SemanticFrame cases | This is first text delta latency, not full response latency. |
| `expected_first_audio_latency_ms` | not_applicable | null | No audio output for this Thinker method. |

## Observed Real Capabilities

- Text input to SemanticFrame JSON: observed_real. Five text-only cases returned parseable, schema-valid SemanticFrame JSON.
- Synthetic/local audio input: observed_real. A short synthetic Mandarin WAV Data URL and a one-second synthetic silence WAV Data URL were accepted and returned text-only JSON.
- Structured SemanticFrame JSON: observed_real. Required top-level keys, slot hints, emotion, audio caption fields, evidence review entries, uncertainty fields, and degradation fields passed local validation in the run.
- Streaming text output: observed_real. Successful requests used SSE and emitted text deltas plus usage events.
- First text delta latency: observed_real for the run-specific bucket, about 359ms to 920ms for SemanticFrame cases.
- Evidence separation: observed_real. The run preserved ASR/context refs in conflicting evidence and marked synthetic web evidence as `UNTRUSTED_WEB_EVIDENCE` with `trusted_as_instruction=false`.
- Ambiguity preservation: observed_real. Missing slots used insufficient-evidence style values rather than guessing.
- Intent, slot, emotion, audio-caption, and uncertainty evidence fields: observed_real for schema presence and validation; quality/calibration remains degraded.
- Composer-role JSON shape: observed_real for parseable output and metadata-only protected-field summary in the `composer_immutable_facts` case.
- Provider-native tool-call-like deltas: observed_real as proposal evidence. No tool response was sent and no tool was executed.

Observed run summary:

| case | result | first text | full stream | evidence label |
| --- | --- | ---: | ---: | --- |
| `foreground_chat` | valid foreground-chat frame | 920ms | 12,302ms | observed_real |
| `ambiguous_slot` | preserved insufficient evidence for missing slots | 359ms | 12,088ms | observed_real |
| `conflicting_evidence` | retained separate ASR/context refs | 379ms | 18,746ms | observed_real |
| `web_evidence_injection` | marked web evidence untrusted and non-instructional | 514ms | 12,572ms | observed_real |
| `emotion_text_hint` | emitted emotion evidence summary | 446ms | 6,214ms | observed_real / observed_degraded |
| `audio_short_command` | accepted synthetic WAV audio input | 723ms | 6,503ms | observed_real |
| `audio_caption_non_speech` | conservative silence/non-speech audio-caption evidence | 572ms | 15,115ms | observed_real / observed_degraded |
| `composer_immutable_facts` | parseable Composer-role safety summary | 433ms | 7,800ms | observed_real / observed_degraded |
| `tool_calling_proposal_probe` | streamed provider-native tool-call deltas only | n/a | 1,375ms | observed_real as proposal evidence |

## Degraded Capabilities

- `supports_streaming_input`: observed_degraded / unknown. The run used message content with local WAV Data URLs, not realtime microphone chunk streaming.
- `supports_cancellation`: observed_degraded / unknown. Client timeout was observed, but provider-confirmed cancellation was not.
- Latency for hot path: observed_degraded. Full structured responses took seconds to many seconds and are not suitable for Duplex hot-path decisions.
- `supports_emotion`: observed_real for schema evidence, degraded for quality/calibration. Emotion must remain evidence with confidence.
- `supports_audio_caption`: observed_real for schema evidence, degraded for quality/calibration. Silence/non-speech behavior was conservative but not a quality eval.
- Composer safety: observed_degraded. The model produced a protected-field preservation summary, but this does not replace independent `CommitmentCoverageCheck` or `ProgressTruthfulnessCheck`.
- Tool proposal deltas: observed_real as proposal evidence, degraded if treated as execution or authorization.
- Timeout handling: observed_degraded. Timeout can become adapter failure metadata, but it must not mutate Interaction, Router, SlowTask, Tool Executor, or Composer state.

## Unsupported Capabilities

These are unsupported or not applicable for this Thinker role:

- `supports_audio_output`
- `supports_tts`
- `supports_tts_truncate`
- `supports_tts_pause_resume`
- `supports_semantic_close` as Thinker-owned authority
- `supports_assistant_directedness` as Thinker-owned authority
- confirmation ownership
- tool authorization ownership
- tool execution ownership
- SlowTask final facts, resolved arguments, terminal task outcome, or current `plan_version` ownership
- turn ingress ownership
- Router ownership

Unsupported means the runtime must not silently rely on Qwen-Omni for these responsibilities. Interaction Controller, Router, SlowTask Runtime, Tool Executor, Coverage Checker, Composer boundary checks, and Talker/playback keep their existing ownership boundaries.

## Unknown / Needs Recheck

- True realtime microphone streaming input support, input cadence, backpressure behavior, and first partial evidence timing.
- Provider-confirmed cancellation semantics.
- Retry behavior under provider errors, rate limits, transient network failures, invalid JSON, and schema validation failures.
- Official current model alias, endpoint surface, modality constraints, supported formats, file size limits, maximum audio duration, context limit, and output limit.
- Audio timestamp availability and normalized timing granularity for Qwen-Omni Thinker output.
- Semantic close evidence quality. It was not directly validated and must not be marked observed_real.
- Assistant-directedness evidence quality. It was not directly validated and must not be marked observed_real.
- Stability over a larger SemanticFrame eval set with natural speech, background noise, mixed language, ambiguous tool requests, and long contexts.
- Tool-call-like delta behavior under larger synthetic tool schemas.
- Whether a future adapter should expose Qwen-Omni as one adapter with role-specific methods or separate Thinker and Composer profile ids.
- docs_only_unobserved: official service claims and limits that were not live-observed in this run must be rechecked before profile hardening.

## SemanticFrame / Evidence Projection Notes

Qwen-Omni can provide SemanticFrame evidence, but it must not directly produce `SemanticCommitment`.

Allowed future mapping:

- Normalize validated model output into a real Thinker frame ref such as `semantic_frame_ref`.
- Preserve `turn_id`, `utterance_id`, input modality, adapter request id, output mode, latency metadata, and source evidence refs.
- Carry `intent_hint`, `slot_hints`, `emotion`, `audio_caption`, `utterance_summary`, confidence, and uncertainty as evidence.
- Preserve ASR, audio, context, web, and synthetic evidence as separate entries with provenance.
- Mark synthetic or real webSearch-derived material as `UNTRUSTED_WEB_EVIDENCE` and never as instruction.
- Let Router pass uncertainty and evidence packs forward without selecting ASR-vs-Thinker winners.
- Let SlowTask own conflict review, resolved arguments, confirmation, final facts, and SemanticCommitment.

Forbidden mapping:

- Do not treat `SemanticFrame` as `SemanticCommitment`.
- Do not let Thinker decide final task facts, `resolved_arguments`, `task_status`, `plan_version`, `task_event_seq`, confirmation, tool authorization, or task completion.
- Do not let Thinker bypass Interaction Controller or Router.
- Do not use Thinker output as direct tool input without SlowTask / Tool Executor validation and provenance.
- Do not treat emotion, audio caption, intent hints, slot hints, uncertainty, semantic close, or directedness as final facts.

ADR-008 requires ASR / Thinker differences to remain multi-source evidence for SlowTask-led review. Router may preserve uncertainty, but it must not become a field-level conflict arbiter.

## Thinker-as-Composer Boundary Notes

The `composer_immutable_facts` case is useful preliminary evidence, not a Composer safety proof.

Observed:

- The model returned parseable Composer-role JSON.
- The metadata-only validation reported protected fields preserved.
- No obvious forbidden rewrite was detected in the run summary.

Required runtime boundary:

- `SemanticCommitment` remains the fact source.
- Thinker-as-Composer may do spoken realization, expression fusion, persona/style adaptation, shortening, and ordering.
- Thinker-as-Composer must not modify `immutable_facts`, remove `must_say_fields`, rewrite `resolved_arguments`, change tool status, remove risk warnings, infer confirmation state, or alter `confirmation_state`.
- Thinker-as-Composer must not turn pending confirmation into completed execution.
- Thinker-as-Composer must not use stale evidence as current fact unless SlowTask has explicitly adopted/rebased it.
- `CommitmentCoverageCheck` and `ProgressTruthfulnessCheck` remain required independent checks before Talker playback.

## Audio Input / Multimodal Notes

Text input:

- observed_real. The run validated multiple text-only SemanticFrame cases.

Audio input:

- observed_real for synthetic/local WAV Data URL input.
- The run used local-only audio generated under `/private/tmp` and removed it after the probe.
- The report records only schema status, latency, and evidence-category checks.
- Raw audio is not needed for replay-safe reporting and must not be committed.

Audio output:

- unsupported for this Thinker method. The run used `modalities: ["text"]`.
- TTS, TTS truncate, TTS pause/resume, and first-audio latency are not applicable to this Thinker role.

Audio timestamps:

- unknown. The run did not observe Qwen-Omni audio timestamp output.
- Future adapters should use runtime audio span timing when model timing is unavailable.

True realtime microphone streaming input:

- unknown / observed_degraded. The run did not exercise live microphone chunk streaming or backpressure behavior.

## Streaming Input / Output Notes

Streaming output:

- observed_real. Successful requests returned SSE events with text deltas and usage events.
- Provider-native tool-call proposal deltas were observed in a separate streaming case.
- This supports response-layer streaming evidence, not realtime audio input support.

Streaming input:

- observed_degraded / unknown. The run used message payloads and local WAV Data URLs, not live input streaming.
- Do not expand the observed text/audio request shape into a conclusion that the candidate supports realtime microphone streaming input.

Latency:

- First text deltas were in a plausible evidence-path bucket for the synthetic cases.
- Full structured completion latency was slow, about 6.2s to 18.8s for SemanticFrame cases.
- Qwen-Omni is not suitable for Duplex hot path, speech-start, immediate barge-in, or truncate decisions.

## Tool Proposal Notes

Provider-native tool-call-like deltas were observed, but only as proposal evidence.

Allowed future mapping:

- Preserve provider-native tool proposals as evidence or normalize them into a proposal-only schema.
- Require Tool Executor validation before any tool action.
- Require current `task_id`, `plan_version`, `task_event_seq`, resolved arguments, provenance, side-effect policy, and current-plan confirmation where applicable.

Forbidden mapping:

- Do not treat provider-native tool proposal as Tool Executor execution.
- Do not emit `TOOL_EXECUTION_STARTED` from model output.
- Do not patch UI state from model text or provider-native tool deltas.
- Do not let the model authorize tools, confirm destructive actions, perform external writes, send communications, book, pay, delete, or mutate external systems.
- `DEMO_DESTRUCTIVE_ACTION` still requires ADR-016 current-plan confirmation and authorization gate.

## Semantic Close / Assistant Directedness Notes

Semantic close and assistant directedness were not directly validated in the run report.

Profile mapping:

- `supports_semantic_close`: unknown as evidence, unsupported as authority.
- `supports_assistant_directedness`: unknown as evidence, unsupported as authority.
- Neither field should be marked `observed_real` in this profile.

Boundary:

- Interaction Controller owns turn ingress.
- Duplex / Interaction evidence and policy decide whether a turn is opened, accepted, held, rejected, or committed.
- Thinker may later provide conservative evidence hints if directly validated, but those hints must not silently become ingress policy.

## Cancellation / Timeout / Retry Mapping

Observed:

- Client timeout produced HTTP `0`, no stream events, and a `client_timeout` category in about 9ms.
- Provider-confirmed cancellation was not observed.
- Retry was not exercised.

Draft mapping for a future adapter:

| condition | metadata mapping | forbidden interpretation |
| --- | --- | --- |
| Client timeout before usable output | `ADAPTER_REQUEST_FAILED` with timeout metadata and `output_mode=degraded` | Do not mutate Interaction, Router, SlowTask, Tool Executor, Composer, or Talker state. |
| Provider error | `ADAPTER_REQUEST_FAILED`; retryable cases may first record retry metadata | Do not silently replace with mock or guessed SemanticFrame. |
| Retryable validation or provider failure | bounded `ADAPTER_REQUEST_RETRYING` with retry count and reason | Do not create duplicate Thinker frames without causal binding. |
| Provider output malformed for adapter schema | `ADAPTER_OUTPUT_VALIDATION_FAILED` | Do not pass invalid output downstream. |
| Provider-confirmed cancellation absent | cancellation remains observed_degraded / unknown | Do not claim cancel success. |
| Late output after timeout or plan change | keep original turn/request binding; mark stale, ignored, or degraded according to owner policy | Do not advance current task state. |

Thinker cancellation is adapter request control only. It is not SlowTask cancel, tool cancel, confirmation rejection, TTS truncate, or task completion.

## Replay-Safe Metadata Shape

Deterministic replay must not rerun Qwen-Omni. Replay should consume recorded metadata, redacted refs, or synthetic fixtures.

Draft metadata shape:

```json
{
  "profile_id": "draft_thinker_dashscope_qwen_omni_2026_05_12",
  "contract_snapshot": "main@61e6afc",
  "adapter_type": "thinker",
  "provider": "dashscope",
  "model_name_observed": "qwen3.5-omni-plus",
  "model_name_pin_required": true,
  "deployment_mode": "remote_api",
  "endpoint_ref": "dashscope-compatible-chat-completions",
  "output_mode": "real_or_degraded",
  "observations": {
    "text_semantic_frame_json": {
      "label": "observed_real",
      "validated_cases": 5,
      "local_schema_validation_passed": true,
      "stored_provider_payload": false
    },
    "audio_input": {
      "label": "observed_real",
      "synthetic_wav_data_url_observed": true,
      "true_realtime_microphone_streaming": "unknown",
      "raw_audio_stored": false
    },
    "streaming_output": {
      "label": "observed_real",
      "text_delta_events_observed": true,
      "tool_proposal_deltas_observed": true
    },
    "evidence_projection": {
      "label": "observed_real",
      "semantic_frame_not_commitment": true,
      "web_evidence_marked_untrusted": true,
      "uncertainty_preserved": true
    },
    "emotion_audio_caption": {
      "label": "observed_real_observed_degraded",
      "emotion_schema_evidence_observed": true,
      "audio_caption_schema_evidence_observed": true,
      "quality_eval_completed": false
    },
    "semantic_close": {
      "label": "unknown",
      "directly_validated": false
    },
    "assistant_directedness": {
      "label": "unknown",
      "directly_validated": false
    },
    "cancellation": {
      "label": "observed_degraded",
      "client_timeout_observed": true,
      "provider_confirmed_cancellation": "unknown"
    }
  },
  "replay_policy": {
    "rerun_provider_in_deterministic_replay": false,
    "requires_audio_recording_for_replay": false,
    "use_recorded_metadata_or_synthetic_fixture": true
  }
}
```

A future shareable fixture should use invented ids, synthetic SemanticFrame snippets, schema pass/fail flags, latency buckets, evidence labels, and causal event refs. It should not require audio recordings, provider response bodies, or raw tool-call arguments.

## Trace / Privacy Boundary

This profile preserves the run report's metadata-only boundary:

- No real user recording was used.
- Synthetic local audio was generated under local temporary paths and removed by the run harness.
- No raw audio, provider response body, full transcript, local trace, replay cache, request header, authorization header, API key, token, cookie, credential, or secret value is needed for this profile.
- No raw provider payload is needed in a replay-safe report.
- Tool-call-like deltas are summarized as proposal evidence only; raw arguments are not stored.
- Web evidence injection was synthetic and kept in evidence space as `UNTRUSTED_WEB_EVIDENCE`.
- Deterministic replay must consume recorded metadata or synthetic fixture data and must not call Qwen-Omni.
- Re-eval, if later approved, must be explicit opt-in and must label regenerated output as re-eval output, not original runtime fact.

## Fit to MVP-0 / MVP-1 / MVP-2 / MVP-3

MVP-0:

- Fit is promising for future replacement of mock Thinker evidence shape.
- Qwen-Omni could map to a future real `SemanticFrame` / `semantic_frame_ref` style output.
- It must not alter MVP-0 runtime now.
- Replay remains metadata-only and does not rerun the provider.

MVP-1:

- Thinker output can become one evidence source for Router uncertainty and SlowTask review.
- It cannot directly advance `plan_version`, resolve final arguments, accept stale evidence, or own current task facts.
- Any old or late Thinker result must keep its original request/turn binding and be handled by owner policy.

MVP-2:

- Qwen-Omni may support Thinker-as-Composer experiments for spoken realization after strict role separation.
- It cannot authorize tools, confirm actions, patch UI state, drive demo tool execution, or turn `SemanticFrame` into `SemanticCommitment`.
- Composer outputs still require `CommitmentCoverageCheck` and `ProgressTruthfulnessCheck` before Talker playback.

MVP-3:

- Qwen-Omni can remain on the shortlist for real Thinker adapter consideration.
- Before integration consideration, it needs profile hardening, eval fixtures, streaming-input clarification, cancellation policy proof, semantic-close / directedness evidence decisions, and Composer boundary tests.
- MVP-3 may replace selected mock adapters with real adapters only without adding new architecture capability.

## Risks / Gaps

- Full structured response latency is too slow for Duplex hot path.
- True realtime microphone streaming input is not proven.
- Audio timestamp output is not proven.
- Provider-confirmed cancellation is not proven.
- Retry behavior is not exercised.
- Semantic close and assistant directedness are not directly validated.
- Emotion and audio-caption evidence are schema-observed but not quality-calibrated.
- Composer-role safety is preliminary and cannot replace independent coverage/truthfulness checks.
- Provider-native tool-call-like deltas can be misread as tool execution unless the proposal-only boundary is explicit.
- Current official model alias, limits, modality rules, and service behavior must be rechecked before hardening.
- No synthetic replay/eval fixture has been created from this profile yet.

## Recommendation

Keep DashScope / Bailian Qwen-Omni on the Thinker shortlist as a promising SemanticFrame evidence provider.

Treat the following as observed real for research profile purposes:

- text input to validated SemanticFrame JSON;
- synthetic/local WAV Data URL audio input;
- streaming text deltas;
- structured JSON for SemanticFrame and preliminary Composer-role output;
- evidence separation, uncertainty preservation, untrusted web evidence labeling, intent/slot hints, emotion evidence schema, audio-caption evidence schema;
- provider-native tool-call-like deltas as proposal evidence only.

Treat the following as degraded, unsupported, or unknown before MVP-3 integration consideration:

- full-response latency for Duplex hot path: observed_degraded;
- true realtime microphone streaming input: unknown / observed_degraded;
- provider-confirmed cancellation: observed_degraded / unknown;
- semantic close: unknown as evidence and unsupported as authority;
- assistant directedness: unknown as evidence and unsupported as authority;
- audio timestamps: unknown;
- TTS, TTS truncate, and TTS pause/resume: unsupported / not_applicable for this Thinker role;
- SlowTask final facts, resolved arguments, confirmation, tool authorization, tool execution, task completion, Router ownership, and turn ingress ownership: unsupported.

Do not integrate Qwen-Omni into the runtime in this step. Do not let Thinker bypass Interaction Controller, Router, SlowTask, Tool Executor, Coverage Checker, or Talker/playback ownership.

## Next Evidence Needed

1. Recheck official DashScope / Bailian Qwen-Omni model alias, endpoint surface, modality requirements, service limits, context limits, output limits, audio duration limits, tool-call format, and error categories on the hardening day.
2. Run a spike-local SemanticFrame eval suite with synthetic text and audio-only metadata cases for ambiguity, conflicting ASR/Thinker evidence, emotion, audio caption, web evidence injection, missing critical slots, and larger schema pressure.
3. Probe true realtime microphone streaming input only if the provider surface supports it, recording input cadence, backpressure, first partial timing, and degradation behavior.
4. Probe provider-confirmed cancellation or explicitly document that cancellation remains unsupported/degraded.
5. Exercise bounded retry and schema repair behavior for malformed JSON and validation failures.
6. Decide whether semantic_close and assistant_directedness should remain conservative runtime policy fields or get a dedicated evidence probe; do not mark either observed_real without direct validation.
7. Add Composer boundary eval cases for immutable facts, must-say fields, resolved arguments, tool status, risk warnings, confirmation state, stale evidence, and untrusted external evidence.
8. Draft replay-safe synthetic fixture proposals for Thinker evidence projection and Composer boundary checks, without changing `tests/` in this research step.
