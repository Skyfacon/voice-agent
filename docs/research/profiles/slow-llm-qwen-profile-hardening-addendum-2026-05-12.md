# Slow LLM Qwen Profile Hardening Addendum

## Status

harden_next_research_addendum_metadata_only

This addendum applies `docs/research/model-spike-adapter-profile-hardening-checklist-2026-05-12.md` to the DashScope / Bailian Qwen Slow LLM profile. It is research hardening only. It does not authorize runtime integration, provider execution, business adapter work, ADR/spec changes, or MVP scope expansion.

## Date

2026-05-12

## Contract Snapshot

- Default contract snapshot: `main@61e6afc`
- MVP-0 closeout reference: `22ddbf4 fix: harden mvp0 trace and replay safety`
- Capability contract reference: ADR-011 and `docs/specs/model-adapter-capabilities.md`
- SlowTask lifecycle and confirmation reference: ADR-016
- Event and replay references: `docs/specs/event-registry.md` and `docs/specs/replay-spec.md`

## Scope

In scope:

- Harden the existing Qwen Slow LLM profile from draft evidence toward a profile candidate.
- Apply the common hardening gates: identity, capability labels, error taxonomy, retry/cancellation separation, stale policy, replay-safe metadata, and owner-boundary assertions.
- Classify which evidence is `observed_real`, `observed_degraded`, `synthetic_eval`, `docs_only_unobserved`, `unknown`, or `unsupported`.

Out of scope:

- No provider execution in this step.
- No runtime adapter implementation.
- No changes to `src/voice_agent/`, `tests/`, `docs/adr/`, or `docs/specs/`.
- No provider bodies, raw trace, local replay cache, real user input, or secret-bearing material.
- No claim that Qwen Slow LLM is ready for MVP-3 integration today.

## Source Evidence

- `docs/research/profiles/slow-llm-qwen-capability-profile-draft-2026-05-11.md`
- `docs/research/spikes/slow-llm-dashscope-qwen-json-run-2026-05-11.md`
- `docs/research/spikes/slow-llm-retry-cancellation-eval-plan-2026-05-12.md`
- `docs/research/spikes/slow-llm-retry-eval-dry-run-2026-05-12.md`
- `tools/model_spikes/slow_llm_retry_eval/`
- `docs/research/model-spike-adapter-profile-hardening-checklist-2026-05-12.md`
- `docs/research/model-spike-phase-summary-2026-05-12.md`

Fresh local dry-run check for this addendum:

| command class | result |
| --- | --- |
| `slow_llm_retry_eval dry-run --case-set full_synthetic` | 21 observations generated under `/private/tmp/.../hardening-full/observations.jsonl` |
| `slow_llm_retry_eval validate` | `valid=true`, 21 observations, zero errors |

## Hardening Decision

Recommendation: `harden_next`.

Reasoning:

- Qwen has the strongest observed evidence among the current Slow LLM candidates.
- Structured JSON, strict local validation, missing-evidence preservation, conflict preservation, untrusted evidence handling, tool proposal shape, and bounded repair are already observed.
- The spike-local retry eval adds repeatable metadata shape for timeout, retry budget, stale output, tool proposal, malformed output, late result, and deferred comparison cases.
- Remaining gaps are important but bounded: current model alias recheck, provider-confirmed cancellation, live transient failure taxonomy, and streaming structured JSON behavior.

This is not `ready_for_mvp3`. It is a research signal that this profile should be hardened first.

## Candidate Identity Disposition

| field | hardening label | disposition |
| --- | --- | --- |
| Adapter role | `observed_real` | Slow LLM planning evidence provider. |
| Provider | `observed_real` | DashScope / Bailian. |
| Model alias | `observed_real_needs_recheck` | `qwen3.6-plus` was observed on 2026-05-11; re-pin before any future live hardening run. |
| Deployment mode | `observed_real` | Remote API surface. |
| Endpoint ref | `observed_real` | DashScope-compatible chat completions ref, with no secret-bearing values. |
| Health observation | `observed_real` | HTTP success for observed structured JSON cases. |
| Output label | `observed_real_or_degraded` | Real only after local validation; degraded for timeout/failure. |
| Latency class | `observed_real_for_slowtask` | Full response latency fits background planning evidence, not Duplex hot path. |

## Capability Disposition

| capability area | hardening label | disposition |
| --- | --- | --- |
| Structured JSON | `observed_real` | Keep as primary capability, gated by local validation. |
| Local schema validation | `observed_real` | Required before any SlowTask consumption. |
| Bounded repair | `observed_real` | Existing run converged within two repair attempts; retry budget must be explicit. |
| Missing slot behavior | `observed_real` | Insufficient evidence was preserved instead of guessed. |
| Conflict preservation | `observed_real` | Conflicting ASR/Thinker evidence was not collapsed into a winner. |
| Untrusted external evidence boundary | `observed_real` | Synthetic external evidence stayed evidence, not instruction. |
| Tool-like output | `observed_real_for_proposal_shape` | Proposal only; Tool Executor remains execution and authorization owner. |
| Client timeout | `observed_degraded` | Timeout category observed; no provider-confirmed cancellation. |
| Old-plan stale behavior | `synthetic_eval` | Dry-run covers old-plan stale shape; not a real provider observation. |
| Provider-confirmed cancellation | `unknown` | Must remain unknown until directly observed. |
| Streaming structured JSON | `docs_only_unobserved` | Surface exists in docs/run notes, but usable streamed JSON was not validated in this lane. |
| Provider transient failures | `unknown` | 5xx/rate/config failure taxonomy is not directly observed. |
| Audio, TTS, semantic close, directedness | `unsupported` | Outside Slow LLM role and must not be silently used. |
| Context/output numeric limits | `unknown` | Must be rechecked on hardening day. |

## Checklist Result

| gate | status | notes |
| --- | --- | --- |
| Research boundary | pass | Addendum stays under `docs/research/`. |
| Candidate identity | partial pass | Identity is recorded; current model alias and limits still need recheck before live hardening. |
| Capability matrix coverage | partial pass | All major role capabilities are labeled; numeric limits and streamed JSON remain gaps. |
| Error taxonomy | partial pass | Client timeout and validation failure are covered; provider-side transient failures remain unknown. |
| Retry policy | pass for schema repair, partial for provider failures | Bounded schema repair is observed; live provider failure retry is not. |
| Cancellation separation | pass as boundary, gap as capability | Client timeout/abort is separated from provider-confirmed cancellation, which remains unknown. |
| Replay posture | pass | Dry-run and profile both require metadata/synthetic fixture consumption only. |
| Owner boundaries | pass | Slow LLM remains planning evidence, not state owner. |
| MVP-3 readiness | not ready | Integration requires a later approved branch, owner-boundary tests, health/error policy, and replay/eval fixtures. |

## Error / Retry / Cancellation Addendum

Required hardening behavior:

- Parse failure and schema failure become adapter validation failure metadata.
- Retryable validation failure may trigger bounded repair with recorded retry count and reason.
- Exhausted repair budget becomes degraded/failure metadata and cannot advance SlowTask.
- Client timeout is adapter failure metadata and does not imply provider-confirmed cancellation.
- Client abort is local control metadata and does not imply provider-confirmed cancellation.
- Provider-confirmed cancellation remains `unknown` unless an explicit provider confirmation surface is observed.
- Late output stays bound to its original request id, task id, plan version, task event sequence, and causal refs.
- If the current plan has advanced, late output is stale unless SlowTask explicitly adopts/rebases it.

## SlowTask / Plan Binding Addendum

Every future Slow LLM observation intended for task planning must carry:

- task id
- plan version
- task event sequence
- adapter request id
- causal source refs
- output label
- validation status
- failure or degradation category when applicable

Rules:

- Validated output can become evidence for SlowTask review, not direct state mutation.
- Missing required arguments can support insufficient-evidence or clarification flow.
- Conflicting fields can support ambiguity review.
- Resolved arguments require SlowTask acceptance and provenance, not model text alone.
- Old-plan output cannot advance current task without explicit adopt/rebase metadata.

## Tool / Confirmation Boundary Addendum

Tool-like output from Qwen remains proposal evidence only.

Allowed:

- Proposal metadata for Tool Executor review.
- Required confirmation flag as evidence.
- Missing/ambiguous field evidence for SlowTask review.
- Current-plan binding for any proposal.

Forbidden:

- Model-owned tool execution.
- Model-owned tool authorization.
- Model-owned confirmation acceptance.
- Model-owned UI mutation.
- Model-owned external side effect.
- Model-owned terminal task outcome.

## Replay-Safe Metadata Shape

A hardened Slow LLM profile should use a metadata shape like:

```json
{
  "profile_id": "slow_llm_qwen_hardening_2026_05_12",
  "contract_snapshot": "main@61e6afc",
  "candidate": {
    "adapter_type": "slow_llm",
    "provider": "dashscope",
    "model_name_observed": "qwen3.6-plus",
    "model_alias_recheck_required": true,
    "deployment_mode": "remote_api",
    "endpoint_ref": "dashscope-compatible-chat-completions",
    "output_mode": "real_or_degraded"
  },
  "validation": {
    "structured_json_label": "observed_real",
    "local_schema_validation_required": true,
    "bounded_repair_label": "observed_real",
    "max_repair_attempts_observed": 2
  },
  "task_binding": {
    "task_id_required": true,
    "plan_version_required": true,
    "task_event_seq_required": true,
    "adapter_request_id_required": true,
    "causal_refs_required": true
  },
  "late_output_policy": {
    "old_plan_defaults_to_stale": true,
    "explicit_adopt_or_rebase_required": true
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

Deterministic replay must consume recorded metadata or synthetic fixtures only. It must not rerun the real provider.

## Event Mapping Addendum

The hardened profile should be able to map future observations to existing event families without creating new event names:

| condition | future event-compatible mapping | state effect |
| --- | --- | --- |
| Validated planning evidence | adapter output ref plus SlowTask review input | No direct state mutation by model output. |
| Parse/schema failure | adapter validation failure metadata | Block downstream consumption. |
| Retryable validation failure | adapter retry metadata with count/reason | No state change until final validation passes. |
| Timeout/final request failure | adapter request failure metadata | No state change. |
| Old-plan late output | stale evidence metadata | No current-plan advance without explicit adopt/rebase. |
| Tool proposal | Tool Executor review input | No execution or authorization by model. |

## MVP Fit

| slice | addendum fit |
| --- | --- |
| MVP-0 | Supports future real adapter profile shape; not needed by current mock runtime. |
| MVP-1 | Strong fit for SlowTask planning evidence if plan binding and stale policy remain owner-controlled. |
| MVP-2 | Supports proposal-only demo tool planning, with Tool Executor and confirmation gates preserved. |
| MVP-3 | Candidate for first Slow LLM integration consideration after remaining hardening gaps are closed. |

## Remaining Blockers

- Current model alias and service limits must be rechecked on any live hardening day.
- Provider-confirmed cancellation remains unknown.
- Streaming structured JSON behavior remains unvalidated.
- Provider-side transient failure taxonomy remains unknown.
- Larger schema pressure and longer context behavior remain under-tested.
- DeepSeek comparison remains deferred.
- No runtime replay/eval fixture has been approved in this research lane.

## Recommendation

Keep DashScope / Bailian Qwen as `harden_next` for Slow LLM profile hardening.

Do not start runtime integration from this addendum. The next research step is to apply the same addendum pattern to TTS CosyVoice, while keeping playback/truncate proof separate from provider synthesis evidence.
