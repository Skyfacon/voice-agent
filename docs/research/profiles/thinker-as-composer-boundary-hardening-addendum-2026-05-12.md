# Thinker-as-Composer Boundary Hardening Addendum

## Status

harden_after_gap_composer_boundary_research_addendum_metadata_only

This addendum applies the Composer-specific parts of `docs/research/model-spike-adapter-profile-hardening-checklist-2026-05-12.md` and ADR-009 to the Qwen-Omni Composer-role evidence. It is research hardening only. It does not authorize runtime integration, provider execution, business adapter work, ADR/spec changes, or MVP scope expansion.

## Date

2026-05-12

## Contract Snapshot

- Default contract snapshot: `main@61e6afc`
- MVP-0 closeout reference: `22ddbf4 fix: harden mvp0 trace and replay safety`
- SemanticCommitment and Composer boundary reference: ADR-009
- SlowTask lifecycle and confirmation reference: ADR-016
- ASR / Thinker evidence fusion reference: ADR-008
- Capability contract reference: ADR-011 and `docs/specs/model-adapter-capabilities.md`
- Event and replay references: `docs/specs/event-registry.md` and `docs/specs/replay-spec.md`

## Scope

In scope:

- Harden the Thinker-as-Composer role boundary separately from the Thinker / SemanticFrame evidence profile.
- Preserve the ADR-009 rule that Composer is a role contract, not a fact owner.
- Define how SpokenPlan candidates must reference SemanticCommitment or SlowTask progress sources.
- Define coverage, progress-truthfulness, protected-field, confirmation-state, tool/demo-status, stale-evidence, and playback-gate expectations.
- Classify evidence as `observed_real`, `observed_degraded`, `synthetic_eval`, `unknown`, or `unsupported`.

Out of scope:

- No provider execution in this step.
- No runtime adapter implementation.
- No changes to `src/voice_agent/`, `tests/`, `docs/adr/`, or `docs/specs/`.
- No audio recordings, provider bodies, raw trace, local replay cache, real user input, request headers, or sensitive access material.
- No provider-native tool execution.
- No claim that Thinker-as-Composer is ready for runtime integration today.

## Source Evidence

- `docs/adr/ADR-009 SemanticCommitment and Thinker-as-Composer Contract.md`
- `docs/research/profiles/thinker-qwen-omni-capability-profile-draft-2026-05-12.md`
- `docs/research/profiles/thinker-qwen-omni-profile-hardening-addendum-2026-05-12.md`
- `docs/research/spikes/thinker-dashscope-qwen-omni-run-2026-05-11.md`
- `docs/research/spikes/thinker-qwen-omni-eval-harness-plan-2026-05-12.md`
- `docs/research/spikes/thinker-composer-boundary-eval-dry-run-2026-05-12.md`
- `tools/model_spikes/thinker_composer_eval/`
- `docs/research/model-spike-adapter-profile-hardening-checklist-2026-05-12.md`
- `docs/research/model-spike-phase-summary-2026-05-12.md`

Fresh local dry-run check for this addendum:

| command class | result |
| --- | --- |
| `thinker_composer_eval dry-run --case-set full_synthetic` | 22 observations generated under `/private/tmp/.../composer-hardening-full/observations.jsonl` |
| `thinker_composer_eval validate` | `valid=true`, 22 observations, zero errors |

## Boundary Decision

Recommendation: `harden_after_gap` for Composer boundary; do not promote to runtime integration.

Reasoning:

- Qwen-Omni produced parseable Composer-role output in the prior real run, and the synthetic eval covers protected-field preservation, must-say coverage, risk warning preservation, confirmation-state preservation, stale-evidence rejection, demo-status truthfulness, and coverage failure blocking playback.
- This evidence is strong enough to define a profile boundary and future eval shape.
- It is not enough to prove runtime safety because coverage and progress-truthfulness checks are synthetic-only in this lane, and model self-report is not sufficient.
- ADR-009 requires an independent check chain before Talker playback for SemanticCommitment-derived SpokenPlan candidates.

The Composer role can remain a research candidate only if it stays downstream of SlowTask facts and upstream of Talker playback checks.

## Role Identity Disposition

| field | hardening label | disposition |
| --- | --- | --- |
| Role | `thinker_as_composer` | Separate role contract, even when implemented by the same Qwen-Omni model service. |
| Provider/model | `observed_real_needs_recheck` | Qwen-Omni alias observed in the prior Thinker run; recheck before any future live hardening run. |
| Primary input | `synthetic_eval` | SemanticCommitment or SlowTask progress refs, not open-ended context. |
| Primary output | `synthetic_eval` | SpokenPlan candidate plus source refs and check requirements. |
| Authority | `unsupported` | Composer has no fact, confirmation, tool, task, or playback authority. |
| Safety proof | `synthetic_eval` | Boundary shape is covered; runtime enforcement remains unproven. |

Thinker-as-Composer is not the semantic truth owner, not SlowTask, not Router, not Interaction Controller, not Tool Executor, and not Talker/playback. It only realizes approved content into spoken form.

## Evidence Disposition

| evidence area | label | disposition |
| --- | --- | --- |
| Composer-role parseable output | `observed_real_shape_degraded_safety` | Prior run produced parseable Composer-role JSON and a protected-field summary. |
| Immutable fact preservation | `observed_real_shape_degraded_safety` | Prior run showed no obvious rewrite; future checks must compare structured fields independently. |
| Must-say field coverage | `synthetic_eval` | Dry-run covers coverage pass and missing-field failure. |
| Coverage failure blocks playback | `synthetic_eval` | `composer_must_say_missing_failure` blocks Talker playback in dry-run metadata. |
| Risk warning preservation | `synthetic_eval` | Covered by `composer_risk_warning`. |
| Confirmation-state preservation | `synthetic_eval` | Covered by `composer_confirmation_state`. |
| Stale evidence rejection | `synthetic_eval` | Covered by `composer_stale_evidence_rejected`. |
| Demo-status truthfulness | `synthetic_eval` | Covered by `composer_demo_status_truthfulness`. |
| Progress-truthfulness chain | `synthetic_eval` | Shape is covered; runtime chain is not proven. |
| Model self-attestation | `unsupported_as_safety_proof` | May be metadata, but cannot be the validation mechanism. |

## Required Source Contract

A Composer request intended for task or progress speech must carry one or more of:

- `source_commitment_id`
- `source_progress_event_ids`
- source event refs
- task id
- plan version
- task event sequence
- confirmation state when relevant
- tool/demo status when relevant
- risk warning refs when relevant
- response style hints and allowed style transformations

Rules:

- SemanticCommitment remains the fact source.
- SlowTask progress events remain the progress source.
- Stale evidence must not be expressed as current fact unless SlowTask explicitly adopts or rebases it.
- Untrusted external evidence must be attributed or downgraded through SlowTask/commitment sources before Composer sees it.
- Composer must not freely consume unfiltered tool output or unscreened external text.

## SpokenPlan Candidate Requirements

A future Composer output should be treated as a candidate until checks pass.

Required metadata:

- spoken plan id
- source commitment id, when commitment-derived
- source progress event ids, when progress-derived
- source event refs
- text ref or redacted text summary
- emotion and speaking style
- interruptibility and priority
- immutable field refs
- coverage-check required flag
- progress-truthfulness-check required flag when progress claims are present

Rules:

- SpokenPlan is not SemanticCommitment.
- SpokenPlan is not user acknowledgement.
- SpokenPlan is not tool execution.
- SpokenPlan is not task completion.
- SpokenPlan cannot authorize Talker playback until required checks pass.

## Protected Field Rules

Composer must preserve:

- immutable facts
- must-say fields
- forbidden rewrite fields
- key numbers
- dates
- locations
- names
- contacts
- status values
- negations
- risk warnings
- confirmation state
- resolved arguments
- tool result refs
- demo tool status
- untrusted-evidence attribution
- source commitment id

Composer may transform:

- wording
- ordering
- segmentation
- style
- tone
- pace hints
- low-risk phrasing

Composer must not transform:

- facts into different facts
- pending confirmation into accepted confirmation
- dry-run/demo status into completed external operation
- untrusted evidence into system fact
- stale evidence into current fact
- missing data into resolved data

## Coverage / Truthfulness Gates

Required gates:

- `CommitmentCoverageCheck` for SemanticCommitment-derived speech.
- Progress truthfulness check for progress-derived speech.
- Protected-field comparison using structured source metadata.
- Coverage failure behavior that blocks Talker playback.

ADR-009 implications:

- Coverage check failure must prevent Talker playback.
- Coverage check pass must be recorded before Talker playback.
- Talker playback must reference the approved check event or result ref.
- The same model's self-report cannot replace the independent check.

Dry-run evidence:

- `composer_must_say_fields` covers successful must-say preservation shape.
- `composer_must_say_missing_failure` covers failed coverage and playback block shape.
- `composer_risk_warning` covers risk warning preservation shape.
- `composer_confirmation_state` covers pending confirmation preservation shape.
- `composer_stale_evidence_rejected` covers stale evidence exclusion shape.
- `composer_demo_status_truthfulness` covers demo/dry-run truthfulness shape.

## Confirmation / Tool / Demo Boundary

Confirmation boundary:

- SlowTask Runtime owns confirmation state.
- Composer may express that confirmation is required.
- Composer may express accepted or rejected confirmation only when the owner-provided source says so.
- Composer must not infer confirmation from raw user text.

Tool boundary:

- Tool Executor owns execution and authorization.
- Composer may express tool status from approved source refs.
- Composer must not create tool calls.
- Composer must not authorize tool actions.
- Composer must not convert a proposal into execution.

Demo boundary:

- Demo dry-run status must remain dry-run status.
- Demo backend status must not be described as a real external system effect.
- Missing or pending demo state must remain missing or pending.

## Playback Boundary

Talker/playback remains the only owner of playback span state.

Rules:

- Composer does not own playback.
- Composer does not emit playback progress.
- Composer does not confirm that audio reached the user.
- Talker can only play SemanticCommitment-derived speech after the required check pass.
- Failed coverage blocks playback.
- Playback committed is delivery metadata, not acknowledgement and not SemanticCommitment.

## Replay-Safe Metadata Shape

A focused Composer boundary report should use metadata like:

```json
{
  "profile_id": "thinker_as_composer_boundary_hardening_2026_05_12",
  "contract_snapshot": "main@61e6afc",
  "role_contract": "thinker_as_composer",
  "source": {
    "source_commitment_id_required": true,
    "source_progress_event_ids_allowed": true,
    "task_binding_required": true,
    "stale_evidence_allowed_without_adopt_or_rebase": false
  },
  "spoken_plan_candidate": {
    "spoken_plan_id_required": true,
    "coverage_check_required": true,
    "truthfulness_check_required_for_progress": true,
    "talker_playback_allowed_before_checks": false
  },
  "protected_fields": {
    "immutable_facts_preserved": "required",
    "must_say_fields_preserved": "required",
    "resolved_arguments_preserved": "required",
    "risk_warnings_preserved": "required",
    "confirmation_state_preserved": "required",
    "tool_status_preserved": "required",
    "demo_status_truthful": "required"
  },
  "evidence": {
    "composer_shape_label": "observed_real_shape_degraded_safety",
    "boundary_cases_label": "synthetic_eval",
    "model_self_report_sufficient": false
  },
  "privacy": {
    "audio_recording_stored": false,
    "provider_body_stored": false,
    "raw_trace_stored": false,
    "local_replay_cache_stored": false,
    "real_user_input_stored": false,
    "sensitive_access_material_stored": false,
    "deterministic_replay_reruns_provider": false
  }
}
```

Deterministic replay consumes recorded metadata or synthetic fixtures only. It does not rerun Composer or TTS.

## Event Mapping Addendum

The focused boundary should map future observations without creating new event names:

| condition | future event-compatible mapping | state effect |
| --- | --- | --- |
| Composer candidate generated | SpokenPlan candidate metadata with source refs | No playback yet. |
| Coverage pass | coverage pass event/result ref | Talker may be eligible to play. |
| Coverage failure | coverage failure metadata | Talker playback blocked. |
| Progress truthfulness pass | progress check result ref | Progress speech may proceed. |
| Protected field mismatch | validation failure metadata | Candidate rejected or regenerated. |
| Pending confirmation preserved | source-bound SpokenPlan metadata | No confirmation accepted. |
| Tool/demo status preserved | source-bound SpokenPlan metadata | No tool execution or external effect. |
| Stale evidence detected | stale/ignored metadata | No current fact expression. |
| Talker playback starts | playback owner event with approved check ref | Playback state only. |

## MVP Fit

| slice | addendum fit |
| --- | --- |
| MVP-0 | Research-only; helps preserve Talker playback and replay metadata boundaries. |
| MVP-1 | Requires SlowTask source binding, plan version, task event sequence, and stale policy. |
| MVP-2 | Directly relevant to Composer, coverage checks, demo tool truthfulness, and spoken progress. |
| MVP-3 | Supports later Composer-role adapter consideration only if independent checks and owner boundaries are implemented in an approved lane. |

## Remaining Blockers

- Runtime `CommitmentCoverageCheck` chain is not proven in this research lane.
- Runtime progress-truthfulness chain is not proven in this research lane.
- Protected-field diff checking is synthetic-only.
- Confirmation-state safety requires SlowTask owner-chain proof.
- Tool/demo status truthfulness requires Tool Executor and demo sandbox owner-chain proof.
- Stale evidence rejection requires SlowTask adopt/rebase owner-chain proof.
- Talker playback gating is synthetic-only in this lane.
- No runtime replay/eval fixture has been approved in this research lane.

## Recommendation

Keep Thinker-as-Composer as `harden_after_gap` for the Composer boundary.

Do not start runtime integration from this addendum. The next research step should move to Duplex/VAD local harness work if the focus is realtime ingress and playback-reference proof, or to a consolidated MVP-3 readiness gap review if the focus is integration planning.
