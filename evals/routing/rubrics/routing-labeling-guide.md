# Audio Routing Labeling Guide

## 1. Purpose and authority

This guide defines how to label audio-routing scenarios without moving semantic interpretation, confirmation, cancellation, tool authorization or foreground-output ownership into the evaluator.

Accepted ADRs remain authoritative. In particular:

- ADR-006 defines `TaskFocusState`, single active SlowTask and the Router decision set.
- ADR-008 treats ASR, Thinker and Fast Interaction outputs as evidence; Router does not choose a field winner.
- ADR-016 gives SlowTask ownership of confirmation, cancellation, switching and task semantics.
- ADR-017 makes Fast Interaction output a candidate and the Fast Foreground Gate a deterministic runtime policy.

Labels describe expected behavior under those contracts. A dataset change must not silently create a new RouterDecision, event name, SlowTask lifecycle state, pause/resume behavior or external side effect.

## 2. Labels are split into semantics and policy

Annotate semantic focus separately from the Router action.

### Task focus labels

| Label | Meaning |
| --- | --- |
| `FOREGROUND_CHAT` | Brief chat or low-risk, self-contained question that does not update an active task. |
| `NEW_TASK_CANDIDATE` | A new task-like request. With an active task, it is a switch candidate rather than an immediate second task. |
| `ACTIVE_TASK_PATCH` | Clear supplement, correction, slot answer, constraint change or confirmation response for the active task. |
| `CANCEL_OR_PAUSE_CANDIDATE` | Possible stop, cancel, pause or replace control intent. MVP has no pause/resume implementation. |
| `NON_ASSISTANT` | Speech should not enter the assistant task chain. |
| `AMBIGUOUS` | Task ownership, directedness or intent cannot be determined reliably from available evidence. |

### Router decisions

The only Router decisions are:

- `FAST_ONLY`
- `SPAWN_SLOW_TASK`
- `PATCH_ACTIVE_SLOW_TASK`
- `IGNORE`

`AMBIGUOUS` is a TaskFocus label, not a fifth RouterDecision. Clarification is expressed through conservative Router policy plus foreground policy. Cancel, pause and task switching are not direct Router actions.

### Foreground policies

Use the ADR-017 protocol:

- `ANSWER`: a low-risk candidate may be committed only after `FAST_ONLY` and gate pass.
- `ACK_SLOW`: discard any answer candidate and use a truthful template acknowledgement or later SlowTask output.
- `ACK_PATCH`: discard any answer candidate and use a template acknowledgement or legitimate clarification.
- `CLARIFY`: discard answer candidate; only a short, non-committal clarification may be emitted.
- `SILENCE`: do not emit a candidate answer.

The foreground label does not authorize tool use, confirmation, task mutation or external effects.

`ACK_PATCH` only means that the input was received and forwarded as UserPatch evidence. It must not claim that a task was already paused, cancelled, switched, replanned or otherwise mutated. Pause-like input uses `CLARIFY` under the product policy below rather than `ACK_PATCH`.

## 3. Decision tree

Apply these questions in order and record a short rationale tag for the first decisive boundary.

### Step 1: Is the utterance directed to the assistant?

- Clearly not directed, background media, another person's conversation or rejected ingress evidence: `NON_ASSISTANT` + `IGNORE` + `SILENCE`.
- Directedness cannot be resolved: `AMBIGUOUS`; never patch or spawn solely to avoid asking.
- Clearly or acceptably directed: continue.

Post-commit `NON_ASSISTANT` remains valid for low-confidence or text-compatible cases, even though Duplex should reject many such cases before Router.

### Step 2: Is there a non-terminal active SlowTask?

- No: use Step 3.
- Yes: use Step 4.
- Only a terminal task exists: treat it as no active task. Late evidence may be recorded for debug but may not advance that task.

### Step 3: No active SlowTask

Classify as `FOREGROUND_CHAT` + `FAST_ONLY` + `ANSWER` only when all are true:

- the response is brief and self-contained;
- it requires no multi-step planning or persistent task state;
- it requires no tool, current external fact or side effect;
- it is low risk and has no unresolved critical field;
- the evidence is sufficiently confident.

Classify as `NEW_TASK_CANDIDATE` + `SPAWN_SLOW_TASK` + `ACK_SLOW` when the request needs planning, a durable artifact, a tool, external/current evidence, multiple steps, persistent follow-up, confirmation or high-risk review.

A complex request remains `SPAWN_SLOW_TASK` when its requested capability is unavailable or outside the current MVP, provided the request is otherwise clear and task-like. Capability limitation is interpreted by SlowTask, which may explain the limitation and offer a supported alternative; Router must not turn the request into `FAST_ONLY` or `IGNORE` merely because execution is unsupported.

If intent, directedness or ownership remains materially unclear, label `AMBIGUOUS`. Baseline policy is `FAST_ONLY` + `CLARIFY`; `IGNORE` + `SILENCE` may also be allowed only when the product rubric explicitly identifies a directedness/noise ambiguity. Never label an ambiguous utterance `SPAWN_SLOW_TASK` merely because it might be task-like.

### Step 4: A non-terminal SlowTask is active

- Clear update, correction, slot answer or confirmation response, including confirmation rejection or modification: `ACTIVE_TASK_PATCH` + `PATCH_ACTIVE_SLOW_TASK` + `ACK_PATCH` or `CLARIFY`. Rejecting a pending confirmation is not by itself a request to cancel the task.
- Clear cancel instruction: `CANCEL_OR_PAUSE_CANDIDATE` + `PATCH_ACTIVE_SLOW_TASK` + `ACK_PATCH`. The acknowledgement only confirms receipt; the patch carries control evidence and SlowTask owns interpretation, confirmation and cancellation.
- Pause-like or stop-for-now instruction: `CANCEL_OR_PAUSE_CANDIDATE` + `PATCH_ACTIVE_SLOW_TASK` + `CLARIFY`. MVP has no pause/resume state, so the clarification asks whether the user means cancel or merely stop foreground output. The system must not claim that the task has been paused.
- New complex request unrelated to the active task: `NEW_TASK_CANDIDATE` + `PATCH_ACTIVE_SLOW_TASK` + `ACK_PATCH`. It enters switch-candidate evidence and must not immediately spawn or rewrite the active goal.
- Brief unrelated side conversation: `FOREGROUND_CHAT` + `FAST_ONLY` + `ANSWER`; no UserPatch may be produced.
- Non-assistant speech: `NON_ASSISTANT` + `IGNORE` + `SILENCE`.
- Unclear ownership: `AMBIGUOUS` + `FAST_ONLY` + `CLARIFY`; do not patch.

For an accepted switch, cancel-then-spawn is a later SlowTask-controlled event sequence. It is not the initial Router label.

### Step 5: Cancel and pause execution policy

Router never cancels or pauses a task directly. Every cancel/pause candidate first becomes a UserPatch evidence pack and is interpreted by SlowTask.

- For an explicit cancel received while the task is in `PLANNING`, with no pending side effect and no unfinished tool call, SlowTask may cancel after `USER_PATCH_INTERPRETED(interpretation_type=cancel)` without an additional confirmation round.
- For an explicit cancel received while the task is `EXECUTING`, represented by the `ACTIVE_TASK_FINALIZING` template, or has any pending side effect or unfinished tool call, SlowTask must require current-plan `TASK_CANCEL` confirmation before cancellation. Tool cancellation and stale-result handling remain governed by ADR-016.
- Pause-like language always uses the conservative clarification path because pause/resume is outside MVP scope. The UserPatch records evidence only and must not mutate lifecycle state or authorize a synthetic pause.
- `ACK_PATCH` is never proof of cancellation. A user-visible statement that the task is cancelled requires authoritative SlowTask cancellation events.

## 4. Eight context templates

Each case selects one template and supplies only scenario-specific values. The event factory is responsible for canonical envelopes and deterministic IDs/timestamps.

| Template | Required precondition | Labeling emphasis |
| --- | --- | --- |
| `NO_ACTIVE_TASK` | No non-terminal SlowTask | FAST versus SPAWN, directedness and ambiguity. |
| `ACTIVE_TASK_PLANNING` | Active task in `PLANNING` | Constraint patches, side chat, switch and cancel candidates. |
| `ACTIVE_TASK_WAITING_TOOL` | Active task in `EXECUTING` with recorded tool wait | Late corrections, cancellation and unrelated foreground chat. |
| `ACTIVE_TASK_WAITING_CONFIRMATION` | `WAITING_FOR_USER_CONFIRMATION` with current-plan confirmation scope | Accept/reject/modify utterances must enter UserPatch interpretation; never accept raw text directly. |
| `ACTIVE_TASK_WAITING_SLOT` | Active task in `WAITING_FOR_SLOT` with requested slot reference | Slot answers, unrelated speech and underspecified replies. |
| `ACTIVE_TASK_FINALIZING` | Current-plan `FINALIZING` evidence before terminal commitment | Last-moment patch/cancel versus side chat; no invented terminal result. |
| `TERMINAL_TASK` | `COMPLETED`, `CANCELLED` or `FAILED` | The terminal task cannot be advanced or patched. New requests are evaluated as no active task. |
| `NON_ASSISTANT_BACKGROUND` | No active-task object; audio/context marks background or other-speaker evidence | Directedness, false trigger and silence behavior. Active-task non-assistant minimal pairs use an active-task template and clearly observable other-speaker evidence in the input. |

`ACTIVE_TASK_WAITING_TOOL` and `ACTIVE_TASK_FINALIZING` are evaluation templates, not new SlowTask lifecycle states. They must be represented with the accepted ADR-016 states and canonical events.

## 5. Gold fields

Every case uses the stable top-level DSL:

- `schema_name`: exactly `voice_agent.routing_eval.case.v1`.
- `case_id`: globally stable identifier.
- `scenario_family_id`: semantic family shared by minimal pairs, paraphrases and audio variants.
- `split`: one of the approved dataset splits.
- `input`: `modality`, `locale`, and exactly one of synthetic/redacted `utterance_text` or safe `audio_ref`. The ref scheme is limited to `audio-eval://synthetic/<token>`, `audio-eval://local/<token>` and `audio-eval://locked/<token>`.
- `context`: one `template` and optional `active_task`. Active-task fields are `task_id`, `task_type`, `summary`, `lifecycle_phase`, `plan_version`, and optional `pending_confirmation_scope`. The confirmation scope is present only for `ACTIVE_TASK_WAITING_CONFIRMATION` and is one of ADR-016's `DEMO_DESTRUCTIVE_ACTION`, `TASK_CANCEL`, `SWITCH_TASK`, `RISK_ACKNOWLEDGEMENT`, or `FINAL_ARGUMENT_CONFIRMATION`.
- `gold`: evaluator-only allowed/forbidden outcomes.
- `tags`: diagnostic dimensions and rationale tags.
- `criticality`: `low`, `medium` or `high`.
- `annotation_status`: `draft`, `human_reviewed` or `adjudicated`. Dataset freezing is version metadata outside the record status.

Within `gold`:

- `task_focus_allowed` lists all acceptable semantic focus labels.
- `router_decisions_allowed` lists all acceptable Router outcomes.
- `router_decisions_forbidden` records outcomes that violate the policy even if multiple outcomes are otherwise acceptable. It must be disjoint from the allowed set, and the two sets must together cover all four Router decisions.
- `foreground_policy` identifies the one allowed user-visible behavior class.
- `side_effect_expectations` contains exactly `slow_task_created` (boolean), `user_patch_emitted` (boolean) and `external_side_effects`, which must be `FORBIDDEN`. Candidate commit/discard, clarification and silence are derived from `foreground_policy` and scored from foreground events rather than duplicated here.

Allowed sets are not a way to hide annotator disagreement. If disagreement is a missing product decision, keep `annotation_status=draft`, tag `needs_product_policy`, and send the case to Human Review Gate 1.

## 6. Minimal-pair construction

Prefer scenario families that change one decisive variable:

- the same utterance with and without an active task;
- explanation of a tool versus request to use a tool;
- static knowledge versus current external fact;
- side chat versus a constraint update;
- a cancellation response with and without pending confirmation;
- assistant-directed request versus the same sentence in background dialogue;
- a clean utterance versus noise, far-field, overlap or truncation;
- a first request versus a self-correction in the same turn.

All members of a family stay in the same split. A model must not see a clean/text variant during prompt development and then be scored on its noisy/TTS paraphrase in a locked split.

## 7. Annotation workflow

Use AI for draft generation and triage, not for final authority over high-criticality, critical-violation-triggering or genuinely ambiguous labels.

1. Generate the scenario from an approved taxonomy and context template.
2. Produce a rule-based or AI draft label with rationale tags.
3. Run an independent AI review that does not expose the first label as authority.
4. Keep clear AI agreement as `draft`; AI agreement alone is not a human review status and is not locked gold.
5. Send all high-criticality or critical-violation-triggering cases, ambiguous cases, minimal-pair policy boundaries, reviewer disagreements and low-confidence cases to human adjudication.
6. A human records the final allowed/forbidden set and rationale as `human_reviewed` or `adjudicated`, or leaves it `draft` with tag `needs_product_policy`.
7. Freeze the dataset version only after the relevant review gate; later changes require an explicit ontology/profile version update and changelog.

Do not use the system under test as the sole judge of its own gold labels. Do not copy blind-holdout failures into prompt examples.

## 8. Human review gates

### Human Review Gate 1: ontology and policy

After the first 80 text/context cases, humans approve:

- FAST versus SPAWN boundaries;
- active-task patch, side-chat and switch policy;
- cancel/pause treatment;
- ambiguous clarification versus silence policy;
- critical violation list and cost weights;
- representative minimal pairs and label consistency.

Only then may the ontology be frozen and expanded to 288 semantic cases.

### Human Review Gate 2: synthetic-to-real promotion

After synthetic audio evaluation and the consented real-human locked holdout, humans review:

- performance gaps by speaker/environment and audio condition;
- all release-blocking real-audio errors;
- spontaneous-speech annotation disputes;
- whether prompt/profile changes generalize beyond synthetic data;
- whether the locked set remains uncompromised.

Only a human-approved result can promote a prompt/profile for broader use.

## 9. Human recording and privacy

Synthetic audio may cover most semantic and acoustic permutations. Human recording is reserved for natural phrasing, directedness, spontaneous corrections, real microphones, accents and overlap that synthetic pipelines cannot faithfully represent.

Scripted readings may inherit the semantic label only after a human checks that the reading did not change meaning. Spontaneous recordings require fresh annotation. Consent, provider transmission approval and retention decisions are human responsibilities.

Raw synthetic and human audio remains local-only. The repository may contain a safe content hash/reference, generation recipe and redacted metadata, but never raw audio, raw trace, provider body, secret or unredacted real-user content.
