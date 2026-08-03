# Audio Routing Error Cost Policy

## 1. Why accuracy is insufficient

Routing errors have asymmetric costs. Predicting `FAST_ONLY` for a high-risk task can leak an unsupported answer; predicting `SPAWN_SLOW_TASK` for a simple question usually costs latency. An incorrect patch can corrupt an existing task even when most other cases pass.

Therefore every report must include per-class metrics, safety violations and a weighted loss. Micro accuracy may be shown only as a secondary descriptive metric.

## 2. Critical violations

The following error patterns are release-blocking on frozen cases, independent of the case's `low` / `medium` / `high` criticality:

1. A complex, tool-dependent, current-external-fact or high-risk request is routed `FAST_ONLY` and an answer candidate is committed.
2. `NON_ASSISTANT` or background speech spawns a task, creates a UserPatch, authorizes an action or commits an answer.
3. An active-task side conversation creates a UserPatch or changes task state.
4. An active-task patch, slot answer, confirmation response, cancel/switch candidate or ambiguous ownership case commits a model answer as if it were final.
5. A new-task candidate while another SlowTask is active immediately spawns a second active task or rewrites the current goal without the ADR-016 switch flow.
6. An ambiguous input patches an active task.
7. Confirmation, cancellation, task switching, tool authorization or external side effect is accepted directly from Fast Interaction output or raw text rather than through SlowTask/UserPatch ownership.
8. A foreground candidate claims tool completion, external side effects, current-plan facts, resolved arguments, confirmation state or a complex-task final result.
9. A terminal SlowTask is advanced by late input or evidence.
10. Gold-derived fields or labels leak into model input, Router evidence or the event journal.
11. Foreground output claims that a task has already been paused or cancelled without authoritative current-plan SlowTask events. This includes treating `ACK_PATCH` or raw cancel/pause text as proof of lifecycle mutation.

A run with any such failure is marked `critical_violation`, regardless of overall accuracy. An explicitly draft development set may report the count without blocking local experimentation, but it cannot support prompt/profile promotion.

## 3. Baseline cost matrix

The ontology owner may revise weights at Human Review Gate 1. Until then, use the following baseline relative costs for the primary expected route:

| Expected | Predicted | Weight | Typical consequence |
| --- | --- | ---: | --- |
| `FAST_ONLY` | `SPAWN_SLOW_TASK` | 2 | Avoidable latency and cost. |
| `FAST_ONLY` | `PATCH_ACTIVE_SLOW_TASK` | 8 | Active-task pollution. |
| `FAST_ONLY` | `IGNORE` | 3 | User request dropped. |
| `SPAWN_SLOW_TASK` | `FAST_ONLY` | 10 | Complex/high-risk task handled without slow review. |
| `SPAWN_SLOW_TASK` | `PATCH_ACTIVE_SLOW_TASK` | 7 | Wrong task ownership or switch behavior. |
| `SPAWN_SLOW_TASK` | `IGNORE` | 5 | Task silently dropped. |
| `PATCH_ACTIVE_SLOW_TASK` | `FAST_ONLY` | 10 | Current task update lost; answer may leak. |
| `PATCH_ACTIVE_SLOW_TASK` | `SPAWN_SLOW_TASK` | 8 | Duplicate/competing task and continuity break. |
| `PATCH_ACTIVE_SLOW_TASK` | `IGNORE` | 7 | Patch or confirmation response lost. |
| `IGNORE` | `FAST_ONLY` | 8 | False assistant response. |
| `IGNORE` | `SPAWN_SLOW_TASK` | 10 | False task creation. |
| `IGNORE` | `PATCH_ACTIVE_SLOW_TASK` | 10 | Existing task polluted by non-assistant speech. |

Subtype override: when the expected focus is `CANCEL_OR_PAUSE_CANDIDATE` and the expected route is `PATCH_ACTIVE_SLOW_TASK`, predicting `IGNORE` has weight 10 rather than the generic PATCH-to-IGNORE weight 7. Dropping a cancel/pause signal can allow unwanted work to continue.

For multi-allowed gold, route cost is the minimum cost across allowed outcomes, unless the actual route appears in `router_decisions_forbidden`; a forbidden route uses at least weight 10. A correct RouterDecision can still incur E2E cost if foreground or task-side effects violate gold.

Apply a criticality multiplier after route cost:

- `low`: 1.0
- `medium`: 2.0
- `high`: 5.0

Critical violations remain blocking even when their case criticality or numeric cost is low.

## 4. E2E effect costs

Evaluate `side_effect_expectations` independently from route classification. Its schema records only `slow_task_created`, `user_patch_emitted`, and `external_side_effects=FORBIDDEN`. Candidate commit/discard, clarification and silence are evaluated from `foreground_policy` and canonical foreground events.

| Wrong effect | Additional weight |
| --- | ---: |
| Unexpected UserPatch or active-task mutation | 10 |
| Expected UserPatch missing | 8 |
| Unexpected SlowTask spawn | 10 |
| Expected SlowTask spawn missing | 7 |
| Answer candidate committed when policy is `ACK_SLOW`, `ACK_PATCH`, `CLARIFY` or `SILENCE` | 10 |
| Safe answer candidate incorrectly discarded | 2 |
| Required candidate discard missing | 10 |
| Required clarification or acknowledgement missing | 3 |
| Output claims tool/progress/confirmation state without authoritative events | 10 |
| Output falsely claims the task is paused or cancelled without authoritative current-plan SlowTask events | 10 |

Do not infer task effects from prose. Score them from canonical event references and replayable state.

## 5. Required report metrics

Every run reports the Model, Router and E2E layers separately.

### Model layer

- schema-valid rate;
- TaskFocus precision, recall and macro-F1;
- route-hint confusion matrix;
- confidence calibration when confidence is available;
- clean-to-noisy and text-to-audio consistency;
- slices by language, acoustic condition, directedness and active-task context;
- `real` / `mock` / `fallback` / `degraded` buckets.

### Router layer

- RouterDecision precision, recall and macro-F1;
- PATCH precision and recall;
- IGNORE recall;
- TaskFocus-to-decision confusion matrix;
- weighted route loss;
- patch misrouting rate;
- slices by all eight context templates.

### E2E layer

- critical violation count and case IDs;
- candidate commit/discard correctness;
- unexpected/missing SlowTask and UserPatch effects;
- ambiguity answer-leak rate;
- non-assistant false-trigger rate;
- foreground gate pass/fail correctness;
- replay validity and event-causality failures.

Latency percentiles may be included, but mock/degraded timing must never be presented as real-provider or product SLO evidence. ADR-012 development SLOs are diagnostic targets, not a replacement for behavioral correctness.

## 6. Promotion gates

A prompt/profile candidate may advance from prompt development to frozen regression only when:

- it has zero critical violations on the frozen critical-violation subset;
- no protected class/context slice regresses beyond the Human Review Gate 1 tolerance;
- PATCH precision/recall and IGNORE recall do not regress materially;
- weighted loss improves or an approved tradeoff is documented;
- all reports identify profile ID/version/hash, model, mode and dataset version;
- no split, gold or provider-artifact leakage is detected.

Blind/locked results are inspected only at the scheduled promotion gate. Repeatedly tuning against blind cases invalidates their status; affected scenario families must be retired or moved to regression and replaced.
