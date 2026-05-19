# Slow LLM Qwen Capability Profile Draft

## Status

draft_research_profile_metadata_only

This is a research capability profile draft. It is not runtime integration, not a business adapter implementation, and not approval to modify MVP runtime behavior.

## Date

2026-05-11

## Contract Snapshot

- Default contract snapshot: `main@61e6afc`
- MVP-0 closeout reference: `22ddbf4 fix: harden mvp0 trace and replay safety`
- Capability contract reference: ADR-011 and `docs/specs/model-adapter-capabilities.md`
- SlowTask boundary reference: ADR-016 and `docs/specs/event-registry.md`
- Replay boundary reference: `docs/specs/replay-spec.md`

## Scope

This profile summarizes the already executed DashScope / Bailian Qwen Slow LLM structured JSON probe as adapter-shaped research evidence.

In scope:

- Slow LLM structured planning evidence.
- Local JSON parse and schema validation behavior.
- Bounded schema repair behavior.
- Tool-call-like proposal shape for demo sandbox planning.
- Timeout, retry, cancellation, stale-result, replay, and privacy boundary mapping.

Out of scope:

- No changes to `src/voice_agent/`, `tests/`, `docs/adr/`, or `docs/specs/`.
- No main runtime wiring.
- No real business adapter.
- No live provider call in this profile step.
- No raw provider payload, raw trace, replay cache, raw audio, or secret-bearing request metadata.

## Source Evidence

Primary evidence:

- `docs/research/spikes/slow-llm-dashscope-qwen-json-run-2026-05-11.md`

Supporting coordination and contract documents:

- `docs/research/model-spike-phase-summary-2026-05-11.md`
- `docs/research/model-spike-execution-plan.md`
- `docs/research/model-spike-integration-ledger.md`
- `docs/research/model-spike-plan.md`
- `docs/research/model-selection.md`
- `docs/specs/model-adapter-capabilities.md`
- `docs/specs/event-registry.md`
- `docs/specs/replay-spec.md`
- `docs/adr/ADR-011 Model Adapter Capability Contract.md`
- `docs/adr/ADR-014 webSearch Evidence Boundary for Demo Tools.md`
- `docs/adr/ADR-016 SlowTask Lifecycle and Confirmation State Contract.md`

Comparison context:

- `docs/research/spikes/slow-llm-deepseek-json-run-2026-05-11.md` records DeepSeek as not executed because the local secret was missing. It provides docs-only comparison context, not observed runtime evidence.

## Candidate Identity

| field | draft value | label | notes |
| --- | --- | --- | --- |
| `adapter_id` | `draft_slow_llm_dashscope_qwen_2026_05_11` | not_applicable | Draft profile id only; not a runtime adapter id. |
| `adapter_type` | `slow_llm` | observed_real | Role matches the executed structured JSON probe. |
| `provider` | DashScope / Bailian | observed_real | Provider used in the executed run. |
| `model_name` | `qwen3.6-plus` | observed_real | This was the observed model in the 2026-05-11 run, not a permanently fixed model name. Profile hardening must re-pin the official current model alias. |
| `deployment_mode` | `remote_api` | observed_real | Observed through the DashScope OpenAI-compatible surface. |
| `endpoint` | `dashscope-compatible-chat-completions` | observed_real | Endpoint ref only; no secret-bearing values. |
| `output_mode` | `real` for validated responses; `degraded` for timeout/failure | observed_real | Runtime use would still need adapter event recording. |

## Capability Matrix Draft

Labels used here: `observed_real`, `observed_degraded`, `unsupported`, `unknown`, `not_applicable`, `docs_only_unobserved`.

| ADR-011 field | draft label | draft value / behavior | evidence and notes |
| --- | --- | --- | --- |
| `adapter_type` | observed_real | `slow_llm` | Executed as Slow LLM structured JSON probe. |
| `provider` | observed_real | `dashscope` / Bailian | Run report executed against DashScope. |
| `model_name` | observed_real | `qwen3.6-plus` | Observed on 2026-05-11 only; re-pin official current alias before hardening. |
| `deployment_mode` | observed_real | `remote_api` | OpenAI-compatible Chat Completions surface. |
| `endpoint` | observed_real | `dashscope-compatible-chat-completions` | Endpoint ref without secret-bearing request data. |
| `health_status` | observed_real | `healthy_for_observed_json_probe` | HTTP 200 for observed JSON cases. |
| `capability_version` | not_applicable | `research_observation_v1` | Research profile version, not runtime capability schema. |
| `latency_class` | observed_real | `slow_llm_full_response_1_to_6_seconds_observed` | Non-streaming full-response latency was about 1.1s to 5.2s. |
| `error_model` | observed_real | schema validation failure and client timeout observed; provider error remains unknown | Weak-schema failure and client timeout were observed. |
| `timeout_policy` | observed_degraded | adapter-owned metadata-only timeout; no state advance | Client timeout observed; provider-confirmed cancellation was not observed. |
| `retry_policy` | observed_real | bounded schema repair, max two attempts in synthetic probe | Strict schema converged on repair attempt 2 after local validation errors. |
| `output_mode` | observed_real | `real` only after local validation; `degraded` for timeout/failure | Invalid or timed-out output must not advance SlowTask state. |
| `supports_streaming_input` | unsupported | false for this text Slow LLM role | No streaming input was tested or required. |
| `supports_streaming_output` | docs_only_unobserved | API surface supports streaming; Slow LLM JSON streaming not measured | Do not mark streaming output as observed real for this profile. |
| `supports_audio_input` | unsupported | false | Not applicable to this Slow LLM text role. |
| `supports_audio_output` | unsupported | false | Not applicable to this Slow LLM role. |
| `supports_audio_timestamps` | not_applicable | null / false | Audio timing is outside this role. |
| `supports_structured_json` | observed_real | true | JSON object mode plus local validation passed for main synthetic cases. |
| `supports_tool_calling` | observed_real and docs_only_unobserved | proposal-shaped output observed; provider-native tool docs exist but were not exercised | MVP use must normalize any tool-like output to `tool_call_proposal`; Tool Executor remains the only execution and authorization owner. |
| `supports_cancellation` | observed_degraded / unknown | client timeout observed; provider cancellation not confirmed | Do not claim provider-confirmed cancellation. |
| `supports_emotion` | unsupported | false | Unsupported / not applicable for this Slow LLM role. |
| `supports_audio_caption` | unsupported | false | Unsupported / not applicable for this Slow LLM role. |
| `supports_tts` | unsupported | false | Unsupported / not applicable for this Slow LLM role. |
| `supports_tts_truncate` | not_applicable | false | TTS truncate is Talker/playback-owned, not Slow LLM-owned. |
| `supports_tts_pause_resume` | not_applicable | false | Pause/resume is outside this role and MVP non-goal. |
| `supports_semantic_close` | unsupported | false | Unsupported / not applicable for this Slow LLM role. |
| `supports_assistant_directedness` | unsupported | false | Unsupported / not applicable for this Slow LLM role. |
| `max_audio_seconds` | not_applicable | null | No audio input. |
| `max_context_tokens` | unknown | recheck official limit during profile hardening | Not pinned in this profile. |
| `max_output_tokens` | unknown | recheck official limit during profile hardening | Probe used `max_tokens: 700`, but official model limit must be rechecked. |
| `expected_first_token_latency_ms` | unknown | not measured | Run used non-streaming full responses. |
| `expected_first_audio_latency_ms` | not_applicable | null | No audio output. |

## Observed Real Capabilities

- `supports_structured_json`: observed_real. Qwen returned parseable JSON in the main synthetic cases when prompted with JSON object mode and strict schema instructions.
- Schema validation: observed_real with local validator. Outputs were only counted as usable after local strict-schema validation passed.
- Bounded repair: observed_real within two repair attempts in the synthetic probe. A weak-schema failure was caught locally and converged after explicit validation errors were fed back.
- Missing evidence handling: observed_real. The `missing_required_slot` case emitted `INSUFFICIENT_EVIDENCE_FOR_ACTION` instead of guessing.
- Conflict preservation: observed_real. The `conflicting_evidence` case did not invent a resolved location when ASR and Thinker evidence disagreed.
- Synthetic web evidence boundary: observed_real in this probe. Synthetic `UNTRUSTED_WEB_EVIDENCE` was treated as evidence, not instruction.
- Tool proposal shape: observed_real at schema level. The model emitted a `tool_call_proposal`-shaped object with a confirmation flag, without provider-native execution.
- SlowTask binding fields: observed_real for the synthetic schema shape. The observed output could carry `task_id`, `plan_version`, and `task_event_seq`.

## Degraded Capabilities

- `supports_cancellation`: observed_degraded / unknown. A client timeout was observed, but provider-confirmed cancellation was not.
- Timeout behavior: observed_degraded. Timeout can be recorded as adapter metadata, but it must not imply provider cancellation or SlowTask state progress.
- Provider-native tool calling: docs_only_unobserved for the native API feature. The run intentionally constrained tool behavior to schema-level proposal evidence.
- Streaming JSON output: docs_only_unobserved. Official/API-surface streaming exists, but this run did not test streaming Slow LLM JSON or first-token latency.
- Latency: observed_real for SlowTask use, degraded for hot path. Full response latency fits background planning evidence but is too slow for Duplex or turn ingress.

## Unsupported Capabilities

These are unsupported or not applicable for this Slow LLM role:

- `supports_audio_input`
- `supports_audio_output`
- `supports_audio_timestamps`
- `supports_tts`
- `supports_tts_truncate`
- `supports_tts_pause_resume`
- `supports_emotion`
- `supports_audio_caption`
- `supports_semantic_close`
- `supports_assistant_directedness`

Unsupported means the runtime must not silently rely on the Qwen Slow LLM candidate for these responsibilities. ASR, TTS, Duplex, Thinker, Interaction Controller, SlowTask Runtime, Tool Executor, and Composer keep their existing ownership boundaries.

## Unknown / Needs Recheck

- Official current Qwen model alias and exact model limits. `qwen3.6-plus` was observed on 2026-05-11, but profile hardening must re-pin the official current alias.
- `max_context_tokens` and `max_output_tokens`.
- Streaming structured JSON behavior, including partial validity and first-token latency.
- Provider-confirmed cancellation behavior.
- Retry behavior under provider-side errors, rate limits, and transient failures.
- Stability over a larger synthetic eval set.
- Provider-native tool-call output format under larger tool schemas.
- Behavior when prompt/context grows near model limits.
- Cross-provider comparison with DeepSeek after its live run is available.

## Structured JSON / Schema Validation Notes

Slow LLM output must pass local schema validation before entering any SlowTask state transition.

Required mapping:

- Parse failure maps to `ADAPTER_OUTPUT_VALIDATION_FAILED`.
- Strict schema failure maps to `ADAPTER_OUTPUT_VALIDATION_FAILED`.
- Retryable validation failure may emit `ADAPTER_REQUEST_RETRYING` or equivalent adapter retry evidence, with bounded retry count and reason.
- Final validation failure becomes degraded or failed SlowTask evidence, not a current task update.
- Timeout, invalid JSON, and schema failure must be adapter metadata and must not advance the current task.

The model is evidence-producing. It is not the owner of `SlowTaskState`, current `plan_version`, confirmation state, tool authorization, or terminal task outcome.

## Tool Calling Boundary

DashScope / Qwen provider-native tool calling docs exist, but this run did not exercise provider-native tools.

MVP boundary:

- `supports_tool_calling` may be treated as observed_real only for schema-level `tool_call_proposal` output.
- Provider-native tool output, if tested later, must be normalized into `tool_call_proposal`.
- Tool Executor remains the only execution, validation, idempotency, retry, UI patch, and authorization owner.
- Model output must never directly emit or cause `TOOL_EXECUTION_STARTED`, `TOOL_UI_STATE_PATCHED`, external writes, payment, booking, deletion, or communication.
- `DEMO_DESTRUCTIVE_ACTION` still requires ADR-016 current-plan confirmation and authorization.
- Missing or ambiguous tool arguments must block execution and map to Tool Executor / SlowTask events, not model text.

## Timeout / Retry / Cancellation Mapping

Observed timeout evidence:

- The client timeout probe returned a client-side timeout category.
- Provider-confirmed cancellation was not observed.

Draft mapping:

- Client timeout records `ADAPTER_REQUEST_FAILED` with timeout metadata, retryability, `adapter_request_id`, and `output_mode=degraded`.
- Retryable schema or request failure records bounded retry metadata.
- Invalid output after retry budget records validation failure or degraded/failure metadata.
- If the adapter cannot confirm provider cancellation, it must not report cancellation success.
- Any late output stays bound to the original `task_id`, `plan_version`, and `task_event_seq`.

## SlowTask Boundary Mapping

Qwen Slow LLM may provide structured planning evidence for SlowTask, but it does not own SlowTask state.

Allowed evidence mapping:

- Missing required slots can support `INSUFFICIENT_EVIDENCE_FOR_ACTION`.
- Resolved fields can support later `ARGUMENTS_RESOLVED` only after local validation and SlowTask Runtime acceptance.
- Tool-like output can become a proposal for Tool Executor review.
- Conflict notes can support `AMBIGUITY_DETECTED`, `EVIDENCE_REVIEWED`, or clarification flow.

Forbidden boundary crossings:

- No direct SlowTask state mutation from raw model output.
- No confirmation acceptance from model text.
- No terminal task outcome from model text alone.
- No bypass of UserPatch interpretation.
- No bypass of current-plan confirmation state.
- No use of invalid or timed-out output to progress current state.

## Plan Version / Stale Result Mapping

Every Slow LLM request and result intended for task planning must be bound to:

- `task_id`
- `plan_version`
- `task_event_seq`
- `adapter_request_id`
- causal source event refs

Rules:

- Late output must retain its original binding.
- If the current plan has advanced, the late output defaults to stale evidence.
- Old `plan_version` results must not advance current task state.
- Only explicit SlowTask `STALE_EVIDENCE_ADOPTED` adopt/rebase can reuse old output.
- Adopt/rebase must record adopted scope, source result event, old plan version, current plan version, and adoption reason.

## Replay-Safe Metadata Shape

Provider raw payload does not need to enter a replay-safe report. Deterministic replay must not rerun Qwen; it should consume recorded metadata or synthetic fixtures.

Draft metadata shape:

```json
{
  "profile_id": "draft_slow_llm_dashscope_qwen_2026_05_11",
  "contract_snapshot": "main@61e6afc",
  "adapter_type": "slow_llm",
  "provider": "dashscope",
  "model_name_observed": "qwen3.6-plus",
  "model_name_pin_required": true,
  "deployment_mode": "remote_api",
  "endpoint_ref": "dashscope-compatible-chat-completions",
  "output_mode": "real_or_degraded",
  "task_binding_required": ["task_id", "plan_version", "task_event_seq"],
  "structured_json": {
    "label": "observed_real",
    "local_schema_validation": "observed_real",
    "bounded_repair": "observed_real_within_two_attempts"
  },
  "tool_calling": {
    "label": "observed_real_for_tool_call_proposal",
    "provider_native_label": "docs_only_unobserved",
    "execution_owner": "Tool Executor"
  },
  "cancellation": {
    "label": "observed_degraded_unknown",
    "client_timeout_observed": true,
    "provider_confirmed_cancellation_observed": false
  },
  "raw_provider_payload_stored": false,
  "deterministic_replay_reruns_provider": false
}
```

## Trace / Privacy Boundary

- Store only metadata, validation summaries, synthetic refs, latency buckets, and redacted failure categories.
- Do not store raw provider payload in GitHub-allowed research output.
- Do not store raw trace, replay cache, raw audio, real user input, or secret-bearing request metadata.
- webSearch and RAG evidence must be marked `UNTRUSTED_WEB_EVIDENCE`.
- webSearch/RAG content can enter evidence space only. It must not enter instruction space or alter tool policy, confirmation policy, trace policy, repository policy, or ADR rules.
- Deterministic replay does not rerun Qwen. It consumes recorded metadata or synthetic/minimal fixtures.

## Fit to MVP-0 / MVP-1 / MVP-2 / MVP-3

| slice | fit | notes |
| --- | --- | --- |
| MVP-0 | supportive, not required | Profile maps to adapter capability snapshot ideas and replay-safe metadata, but MVP-0 remains mock/runtime-only. |
| MVP-1 | promising with owner boundaries | Structured output can support SlowTask mock/profile hardening, but SlowTask Runtime owns state, plan versioning, stale evidence, and confirmation state. |
| MVP-2 | promising for proposal-only tool flow | `tool_call_proposal` can support demo tool planning, but Tool Executor owns execution and ADR-016 authorization. |
| MVP-3 | candidate, not ready | Suitable for integration consideration only after current model alias pinning, replay/eval fixtures, cancellation hardening, and larger schema validation evidence. |

## Risks / Gaps

- Model alias drift: `qwen3.6-plus` must be rechecked before hardening.
- Cancellation remains degraded / unknown.
- Streaming output is docs-only unobserved for Slow LLM JSON.
- Full-response latency is acceptable for SlowTask planning but not hot-path turn ingress.
- Local schema validation is mandatory; prompt-only JSON compliance is not enough.
- Tool-call proposal output must not blur into Tool Executor execution authority.
- Larger schemas, longer contexts, rate limits, and provider errors remain under-tested.
- No replay/eval fixture has been created from this profile yet.
- DeepSeek comparison remains not executed.

## Recommendation

Keep DashScope / Bailian Qwen on the first Slow LLM shortlist as a structured JSON planning candidate.

Use this profile only as research evidence for later adapter profile hardening. Do not integrate it into runtime yet. The hardening path should require:

- re-pin the official current Qwen text model alias;
- keep thinking disabled or otherwise validated for strict JSON mode if that remains required by the chosen surface;
- enforce local schema validation before SlowTask consumption;
- bound repair attempts and record validation errors as adapter metadata;
- treat cancellation as degraded until provider-confirmed behavior is observed;
- normalize all tool-like output to `tool_call_proposal`;
- keep Tool Executor as the only execution and authorization owner.

## Next Evidence Needed

1. Recheck official DashScope / Bailian Qwen model alias, context limit, output limit, JSON mode, streaming surface, and tool-call surface on the hardening day.
2. Run a streaming structured JSON probe without marking it observed real until local validation confirms usable behavior.
3. Run provider-confirmed cancellation or late-result behavior probes.
4. Add more synthetic cases for material UserPatch, old-plan late output, confirmation-required demo destructive action, and larger schema pressure.
5. Convert selected observations into synthetic or redacted replay/eval-safe fixtures, without changing `tests/` in this research step.
6. Run the deferred DeepSeek comparison when the local environment is ready.
7. Draft the next profile for TTS CosyVoice if the team continues following the recommended profile-hardening order.
