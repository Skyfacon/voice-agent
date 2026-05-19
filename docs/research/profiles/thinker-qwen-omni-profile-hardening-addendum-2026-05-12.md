# Thinker Qwen-Omni Profile Hardening Addendum

## Status

harden_after_gap_research_addendum_metadata_only

This addendum applies `docs/research/model-spike-adapter-profile-hardening-checklist-2026-05-12.md` to the DashScope / Bailian Qwen-Omni Thinker profile. It is research hardening only. It does not authorize runtime integration, provider execution, business adapter work, ADR/spec changes, or MVP scope expansion.

## Date

2026-05-12

## Contract Snapshot

- Default contract snapshot: `main@61e6afc`
- MVP-0 closeout reference: `22ddbf4 fix: harden mvp0 trace and replay safety`
- ASR / Thinker evidence fusion reference: ADR-008
- SemanticCommitment and Composer boundary reference: ADR-009
- Capability contract reference: ADR-011 and `docs/specs/model-adapter-capabilities.md`
- SlowTask lifecycle and confirmation reference: ADR-016
- Event and replay references: `docs/specs/event-registry.md` and `docs/specs/replay-spec.md`

## Scope

In scope:

- Harden the existing Qwen-Omni Thinker profile from draft evidence toward a profile candidate.
- Apply the common hardening gates: identity, capability labels, SemanticFrame schema stability, evidence provenance, timeout/retry/cancellation separation, Composer boundary, tool proposal boundary, replay-safe metadata, and owner-boundary assertions.
- Classify which evidence is `observed_real`, `observed_degraded`, `synthetic_eval`, `unknown`, or `unsupported`.

Out of scope:

- No provider execution in this step.
- No runtime adapter implementation.
- No changes to `src/voice_agent/`, `tests/`, `docs/adr/`, or `docs/specs/`.
- No audio recordings, provider bodies, raw trace, local replay cache, real user input, request headers, or secret-bearing material.
- No provider-native tool execution.
- No claim that Qwen-Omni is ready for MVP-3 integration today.

## Source Evidence

- `docs/research/profiles/thinker-qwen-omni-capability-profile-draft-2026-05-12.md`
- `docs/research/spikes/thinker-dashscope-qwen-omni-run-2026-05-11.md`
- `docs/research/spikes/thinker-qwen-omni-eval-harness-plan-2026-05-12.md`
- `docs/research/spikes/thinker-composer-boundary-eval-dry-run-2026-05-12.md`
- `tools/model_spikes/thinker_composer_eval/`
- `docs/research/model-spike-adapter-profile-hardening-checklist-2026-05-12.md`
- `docs/research/model-spike-phase-summary-2026-05-12.md`

Fresh local dry-run check for this addendum:

| command class | result |
| --- | --- |
| `thinker_composer_eval dry-run --case-set full_synthetic` | 22 observations generated under `/private/tmp/.../hardening-full/observations.jsonl` |
| `thinker_composer_eval validate` | `valid=true`, 22 observations, zero errors |

## Hardening Decision

Recommendation: `harden_after_gap`.

Reasoning:

- Qwen-Omni has observed real evidence for structured SemanticFrame JSON, streaming text deltas, synthetic/local audio Data URL input, evidence separation, uncertainty preservation, untrusted web evidence labeling, and provider-native tool proposal deltas as proposal evidence.
- The 2026-05-11 run directly observed valid text and audio SemanticFrame cases, Composer-role shape, and a client timeout category without storing audio recordings or provider bodies.
- The spike-local Thinker/Composer eval adds repeatable metadata shape for missing slots, ASR/Thinker conflict preservation, untrusted web evidence, emotion evidence, audio-caption evidence, tool proposal boundary, Composer protected-field cases, coverage failure, semantic close unknown, directedness unknown, client timeout, and late result staleness.
- The strongest gaps remain full-response latency, true realtime microphone streaming input, provider-confirmed cancellation, retry/schema repair behavior, semantic close evidence quality, assistant-directedness evidence quality, audio timestamp availability, and Composer safety enforcement.

This is not `ready_for_mvp3`. It is a research signal that Qwen-Omni can remain on the Thinker shortlist as a post-commit SemanticFrame evidence provider, not a Duplex hot-path or authority owner.

## Candidate Identity Disposition

| field | hardening label | disposition |
| --- | --- | --- |
| Adapter role | `observed_real` | Thinker / SemanticFrame evidence provider. |
| Composer role | `observed_real_shape_degraded_safety` | Separate role contract for spoken realization experiments only. |
| Provider | `observed_real` | DashScope / Bailian. |
| Model alias | `observed_real_needs_recheck` | `qwen3.5-omni-plus` was observed on 2026-05-11; re-pin before any future live hardening run. |
| Deployment mode | `observed_real` | Remote Chat Completions-compatible surface. |
| Endpoint ref | `observed_real` | DashScope-compatible chat completions ref, with no secret-bearing values. |
| Health observation | `observed_real` | HTTP success for observed SemanticFrame, audio-input, Composer-role, and tool proposal cases. |
| Output label | `observed_real_or_degraded` | Real for validated frames; degraded for timeout, latency caveats, and unconfirmed cancellation. |
| Latency class | `observed_degraded_for_hot_path` | First text deltas were about 359ms to 920ms; full structured streams were about 6.2s to 18.8s. |

Qwen-Omni / Thinker output is SemanticFrame evidence only. It is not a turn ingress owner, not an Interaction Controller, not a Router, not SlowTask, not a semantic truth owner, not a confirmation owner, and not a tool authorization or task completion owner.

## Capability Disposition

| capability area | hardening label | disposition |
| --- | --- | --- |
| Text SemanticFrame JSON | `observed_real` | Five text cases returned parseable, schema-valid SemanticFrame JSON. |
| Synthetic/local audio input | `observed_real` | WAV Data URL audio input was accepted for short command and silence cases. |
| Streaming text output | `observed_real` | SSE text deltas and usage events were observed. |
| Evidence separation | `observed_real` | ASR/context conflicts and untrusted web evidence stayed separated. |
| Ambiguity preservation | `observed_real` | Missing slots stayed insufficient-evidence style rather than guessed. |
| Emotion evidence schema | `observed_real_degraded_quality` | Schema presence observed; quality/calibration unproven. |
| Audio-caption evidence schema | `observed_real_degraded_quality` | Schema presence observed; quality/calibration unproven. |
| Provider-native tool proposal deltas | `observed_real_proposal_only` | Proposal evidence only; Tool Executor remains required. |
| Composer-role JSON shape | `observed_real_shape_degraded_safety` | Parseable output observed; independent coverage/truthfulness chain still required. |
| Full structured latency | `observed_degraded` | Too slow for Duplex hot path, speech-start, barge-in, or truncate decisions. |
| True realtime microphone streaming input | `unknown_or_degraded` | Not directly exercised. |
| Audio timestamps | `unknown` | Not observed for Thinker output. |
| Semantic close | `unknown_as_evidence_unsupported_as_authority` | Must not be marked real without direct validation. |
| Assistant directedness | `unknown_as_evidence_unsupported_as_authority` | Must not be marked real without direct validation. |
| Provider-confirmed cancellation | `unknown` | Client timeout was observed; provider confirmation was not. |
| Retry and schema repair | `unknown` | Not exercised for Thinker in the live run. |
| TTS / playback | `unsupported` | Outside Thinker role. |
| SlowTask final facts and resolved arguments | `unsupported` | Outside Thinker authority. |
| Confirmation, tool authorization, task completion | `unsupported` | Outside Thinker authority. |
| Official service limits | `unknown` | Must be rechecked on any live hardening day. |

## Checklist Result

| gate | status | notes |
| --- | --- | --- |
| Research boundary | pass | Addendum stays under `docs/research/`. |
| Candidate identity | partial pass | Identity is recorded; current alias, limits, modality rules, and service behavior still need recheck before live hardening. |
| Capability matrix coverage | partial pass | Core Thinker evidence is labeled; semantic close, directedness, audio timing, cancellation, retry, and Composer enforcement remain gaps. |
| Error taxonomy | partial pass | Client timeout and late result have metadata shapes; live provider taxonomy and retry behavior remain incomplete. |
| SemanticFrame boundary | pass as boundary, gap as quality | SemanticFrame stays evidence only; larger schema stability still needs coverage. |
| Tool proposal boundary | pass as boundary | Provider-native tool deltas are proposal evidence only. |
| Composer boundary | partial pass | Dry-run covers protected-field cases; runtime coverage/truthfulness chain is not proven. |
| Replay posture | pass | Dry-run and profile require metadata/synthetic fixture consumption only. |
| Owner boundaries | pass | Thinker remains evidence, not semantic or control authority. |
| MVP-3 readiness | not ready | Integration requires a later approved branch, health/error policy, owner-boundary tests, and replay/eval fixtures. |

## SemanticFrame Boundary Addendum

Allowed future mapping:

- Normalize validated model output into Thinker frame evidence.
- Preserve turn id, utterance id, input modality, adapter request id, output label, latency metadata, and source evidence refs.
- Carry intent hint, slot hints, emotion, audio caption, utterance summary, confidence, and uncertainty as evidence.
- Preserve ASR, audio, context, web, and synthetic evidence as separate entries with provenance.
- Mark webSearch-derived material as untrusted evidence and never as instruction.
- Let Router pass uncertainty and evidence packs forward without selecting ASR-vs-Thinker winners.
- Let SlowTask own conflict review, resolved arguments, confirmation, final facts, and SemanticCommitment.

Forbidden mapping:

- Thinker output must not be treated as SemanticCommitment.
- Thinker must not decide final task facts.
- Thinker must not decide resolved arguments.
- Thinker must not decide task status.
- Thinker must not decide plan version or task event sequence.
- Thinker must not decide confirmation.
- Thinker must not decide tool authorization.
- Thinker must not decide task completion.
- Thinker must not bypass Interaction Controller, Router, SlowTask, Tool Executor, Coverage Checker, or Talker/playback.

## ASR / Thinker Evidence Boundary Addendum

ADR-008 requires ASR / Thinker differences to remain multi-source evidence for SlowTask-led review.

Required hardening behavior:

- Conflicting ASR and Thinker fields remain separate evidence refs.
- Silence/non-speech ASR false-positive risk stays visible as risk metadata.
- Router-facing metadata may carry uncertainty, but must not choose field-level winners.
- SlowTask owns ambiguity review, missing-slot review, resolved arguments, final facts, confirmation, and SemanticCommitment.
- Tool Executor blocks execution when resolved arguments, provenance, authorization, or confirmation are missing.

## Semantic Close / Directedness Addendum

Semantic close and assistant directedness were not directly validated in the real run.

Current labels:

- `supports_semantic_close`: `unknown` as evidence, `unsupported` as authority.
- `supports_assistant_directedness`: `unknown` as evidence, `unsupported` as authority.

Rules:

- Do not mark either field `observed_real` without direct proof.
- Do not let Thinker open, accept, hold, reject, or commit a turn.
- Do not let Thinker own directedness policy.
- If future proof adds conservative hints, they remain evidence only and must pass through Interaction/Router ownership.

## Tool Proposal Addendum

Provider-native tool-call-like deltas were observed, but only as proposal evidence.

Allowed:

- Preserve provider-native tool proposals as evidence.
- Normalize proposal metadata for Tool Executor review.
- Require current task binding, provenance, resolved arguments, side-effect policy, and current-plan confirmation where applicable.

Forbidden:

- Model-owned tool execution.
- Model-owned tool authorization.
- Model-owned UI mutation.
- Model-owned external side effect.
- Model-owned terminal task outcome.
- Treating provider-native tool deltas as Tool Executor events.

## Thinker-as-Composer Boundary Addendum

The Composer-role case is useful preliminary evidence, not a Composer safety proof.

Required boundaries:

- SemanticCommitment remains the fact source.
- Thinker-as-Composer may do spoken realization, expression fusion, persona/style adaptation, shortening, and ordering.
- Thinker-as-Composer must not modify immutable facts.
- Thinker-as-Composer must not remove must-say fields.
- Thinker-as-Composer must not rewrite resolved arguments.
- Thinker-as-Composer must not change tool status.
- Thinker-as-Composer must not remove risk warnings.
- Thinker-as-Composer must not infer confirmation acceptance.
- Thinker-as-Composer must not turn pending confirmation into completed execution.
- Stale evidence must not be expressed as current fact unless SlowTask explicitly adopts or rebases it.
- Coverage and progress-truthfulness checks remain independent gates before Talker playback.
- Failed coverage blocks Talker playback.

## Error / Retry / Cancellation Addendum

Required hardening behavior:

- Client timeout becomes adapter failure or degraded-output metadata and cannot mutate Interaction, Router, SlowTask, Tool Executor, Composer, or Talker state.
- Provider-confirmed cancellation remains `unknown` unless an explicit provider confirmation surface is observed.
- Retryable provider or validation failure records retry count, retry reason, and final outcome.
- Exhausted retry budget becomes degraded/failure metadata and cannot create a valid Thinker frame.
- Malformed output becomes validation failure metadata and cannot pass downstream.
- Late output after timeout or superseded turn stays bound to the original turn/request refs and is stale or ignored for current state.

## Replay-Safe Metadata Shape

A hardened Thinker profile should use a metadata shape like:

```json
{
  "profile_id": "thinker_qwen_omni_hardening_2026_05_12",
  "contract_snapshot": "main@61e6afc",
  "candidate": {
    "adapter_type": "thinker",
    "provider": "dashscope",
    "model_name_observed": "qwen3.5-omni-plus",
    "model_alias_recheck_required": true,
    "deployment_mode": "remote_api",
    "endpoint_ref": "dashscope-compatible-chat-completions",
    "output_mode": "real_or_degraded"
  },
  "semantic_frame": {
    "structured_json_label": "observed_real",
    "schema_validation_required": true,
    "semantic_frame_not_commitment": true,
    "provenance_preserved": true,
    "uncertainty_preserved": true,
    "untrusted_web_boundary_preserved": true
  },
  "modality": {
    "text_input_label": "observed_real",
    "audio_data_url_input_label": "observed_real",
    "true_realtime_microphone_streaming_input": "unknown_or_degraded",
    "audio_timestamp_output": "unknown"
  },
  "boundary": {
    "router_winner_selection": false,
    "slowtask_required_for_resolved_arguments": true,
    "semantic_commitment_owner": "slowtask",
    "tool_executor_required_for_execution": true,
    "tool_proposal_only": true
  },
  "composer": {
    "composer_shape_label": "observed_real_shape_degraded_safety",
    "coverage_check_required": true,
    "truthfulness_check_required": true,
    "model_self_report_sufficient": false
  },
  "failure": {
    "client_timeout_label": "observed_degraded",
    "provider_cancel_confirmed": "unknown",
    "retry_behavior": "unknown",
    "late_result_policy": "stale_or_ignored"
  },
  "privacy": {
    "audio_recording_stored": false,
    "provider_body_stored": false,
    "raw_trace_stored": false,
    "local_replay_cache_stored": false,
    "real_user_input_stored": false,
    "secret_bearing_material_stored": false,
    "deterministic_replay_reruns_provider": false
  }
}
```

Deterministic replay must not rerun Qwen-Omni; it consumes recorded metadata or synthetic fixtures only.

## Event Mapping Addendum

The hardened profile should be able to map future observations to existing event families without creating new event names:

| condition | future event-compatible mapping | state effect |
| --- | --- | --- |
| Valid SemanticFrame output | Thinker frame ref plus adapter output metadata | Evidence only. |
| Missing or ambiguous slots | uncertainty and missing-field metadata | SlowTask review required. |
| ASR/Thinker conflict | separate evidence refs | No Router field arbitration. |
| Untrusted web evidence | evidence entry with untrusted label | Not instruction. |
| Emotion or audio-caption evidence | evidence field with confidence/degradation | Not policy or final fact. |
| Tool proposal delta | proposal evidence for Tool Executor review | No execution or authorization. |
| Composer spoken realization | SpokenPlan candidate plus check refs | No fact ownership. |
| Coverage failure | degraded Composer output or no playback | Talker playback blocked. |
| Client timeout | adapter degraded/failure metadata | No state advance. |
| Provider-confirmed cancellation absent | cancellation remains unknown/degraded | No cancel success claim. |
| Late result | stale or ignored output metadata | No current-state advance. |

## MVP Fit

| slice | addendum fit |
| --- | --- |
| MVP-0 | Supports future real Thinker adapter profile shape; current mock Thinker remains sufficient for runtime. |
| MVP-1 | Thinker evidence can feed Router uncertainty and SlowTask review, but cannot advance plan state or final facts. |
| MVP-2 | Qwen-Omni can support Composer experiments only behind coverage/truthfulness checks and Tool Executor boundaries. |
| MVP-3 | Candidate for Thinker integration consideration only after alias/limits recheck, health/error policy, larger eval coverage, cancellation/retry proof, and owner-boundary tests in an approved integration lane. |

## Remaining Blockers

- Current model alias, endpoint surface, modality rules, service limits, context limit, output limit, audio duration limit, tool proposal format, and error categories must be rechecked on any live hardening day.
- Full structured response latency is too slow for Duplex hot path.
- True realtime microphone streaming input remains unknown/degraded.
- Audio timestamp output remains unknown.
- Provider-confirmed cancellation remains unknown.
- Retry and schema repair behavior remain unproven for Thinker.
- Semantic close and assistant directedness remain unknown as evidence and unsupported as authority.
- Emotion and audio-caption quality are not calibrated.
- Composer safety enforcement is synthetic-only and cannot replace independent coverage/truthfulness checks.
- Larger schema stability coverage remains incomplete.
- No runtime replay/eval fixture has been approved in this research lane.

## Recommendation

Keep DashScope / Bailian Qwen-Omni as `harden_after_gap` for Thinker profile hardening.

Do not start runtime integration from this addendum. The next research step is to either harden the Thinker-as-Composer boundary as its own addendum, or move to a local Duplex/VAD harness if the focus shifts to realtime ingress and playback-reference proof.
