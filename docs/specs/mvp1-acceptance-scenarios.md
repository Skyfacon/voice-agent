# MVP-1 Acceptance Scenarios

Source of truth: accepted ADR baseline, especially ADR-002, ADR-004, ADR-006, ADR-007, ADR-008, ADR-010, ADR-012, ADR-015, ADR-016, and the derived specs in `docs/specs/event-registry.md`, `docs/specs/state-reducers.md`, and `docs/specs/replay-spec.md`.

MVP-1 validates SlowTask mock and UserPatch consistency. It does not validate real tools, real external side effects, progressive Tool Executor behavior, Composer coverage, frontend UI patching, or real model adapter quality.

All fixtures for these scenarios must be synthetic, redacted, and minimal. Scenario ids are acceptance labels, not journal event names.

Event chains below are causal sketches. They may omit common envelope fields and repeated context bindings for readability, but those fields are not optional: committed fixtures and validators must still include every required field in `docs/specs/event-registry.md`, including `task_id`, `plan_version`, `task_event_seq`, `caused_by_event_id`, and required refs for SlowTask-relevant events. Fields shown inline are the scenario-specific bindings being asserted.

## Scenario MVP1-SPAWN-SLOWTASK-001

| Field | Spec |
| --- | --- |
| purpose | Validate that a committed complex-task turn with no active SlowTask spawns one SlowTask and completes the mock no-tool happy path with current-plan SemanticCommitment. |
| initial state | Session started; mock capability snapshot recorded; `TaskFocusState.active_task_id=null`; no `SlowTaskState`; `InteractionState` ready for a committed text or audio turn. |
| event chain | `TEXT_INPUT_RECEIVED` or audio ingress events -> `TURN_OPENED` -> `TURN_INGRESS_ACCEPTED` -> `TURN_INGRESS_COMMITTED` -> `MOCK_ASR_FRAME_EMITTED(output_mode=mock)` -> `MOCK_THINKER_FRAME_EMITTED(output_mode=mock)` -> `ROUTER_DECISION_EMITTED(router_decision=SPAWN_SLOW_TASK)` -> `SLOWTASK_CREATED(task_id=T1, plan_version=N, task_event_seq=1)` -> `SLOWTASK_STATE_CHANGED(to_state=CREATED)` -> `TASK_FOCUS_STATE_UPDATED(active_task_id=T1)` -> `PLANNING_STARTED(plan_version=N)` -> `SLOWTASK_STATE_CHANGED(to_state=PLANNING)` -> `EVIDENCE_REVIEWED` -> optional `ARGUMENTS_RESOLVED` / `ARGUMENT_RESOLUTION_PROVENANCE` -> `FINALIZING` -> `SEMANTIC_COMMITMENT_EMITTED(plan_version=N)` -> `SLOWTASK_STATE_CHANGED(to_state=COMPLETED)` -> `TASK_FOCUS_STATE_UPDATED(active_task_id=null)`. |
| required assertions | Exactly one non-terminal SlowTask exists during the active portion; `TASK_FOCUS_STATE_UPDATED(active_task_id=T1)` is not emitted before `SLOWTASK_CREATED(T1)`; all SlowTask events bind `task_id`, `plan_version`, and `task_event_seq`; SemanticCommitment uses current plan; every state transition has `SLOWTASK_STATE_CHANGED`; active focus cleanup is Router-owned. |
| replay expectations | Deterministic replay reconstructs `TaskFocusState.active_task_id` changes and final `SlowTaskState=COMPLETED` without re-running models, tools, clock, or random. |
| forbidden behavior | No UserPatch for initial spawn; no `TOOL_EXECUTION_STARTED`; no `TOOL_UI_STATE_PATCHED`; no `SPOKEN_PLAN_EMITTED`; no coverage/truthfulness events; no real Slow LLM output. |
| fixture privacy requirements | Initial goal, evidence, arguments, and commitment use synthetic/redacted refs; no raw audio, raw trace, secrets, or unredacted real user input. |

## Scenario MVP1-ACTIVE-PATCH-001

| Field | Spec |
| --- | --- |
| purpose | Validate that obvious active-task input becomes a UserPatch evidence pack and does not directly mutate SlowTask state. |
| initial state | Active SlowTask `T1` in `PLANNING` or `WAITING_FOR_SLOT`; current `plan_version=N`; `TaskFocusState.active_task_id=T1`. |
| event chain | New committed turn -> `MOCK_ASR_FRAME_EMITTED` -> `MOCK_THINKER_FRAME_EMITTED` -> `ROUTER_DECISION_EMITTED(router_decision=PATCH_ACTIVE_SLOW_TASK, task_focus=ACTIVE_TASK_PATCH)` -> `TASK_FOCUS_STATE_UPDATED(active_task_id=T1)` -> `USER_PATCH_RECEIVED(patch_id=P1, task_id=T1, plan_version=N, observed_plan_version=N, evidence_ref=E1)`. |
| required assertions | `USER_PATCH_RECEIVED` binds `patch_id`, `task_id`, pre-advance `plan_version`, `observed_plan_version`, `task_event_seq`, `turn_id`, `utterance_id`, and causal Router decision; evidence pack includes authoritative evidence plus non-authoritative hypotheses; SlowTask goal, constraints, resolved arguments, confirmation state, and `plan_version` are unchanged by receipt alone. |
| replay expectations | Replay reconstructs the patch evidence queue and `TaskFocusState` without interpreting the patch. |
| forbidden behavior | Router must not emit `USER_PATCH_INTERPRETED`, `PLAN_VERSION_ADVANCED`, cancel, confirmation, or resolved-argument events; UserPatch must not be encoded as `slot_update` / `goal_rewrite` mutation. |
| fixture privacy requirements | Text is synthetic/redacted or in `text_ref`; audio is `audio_span_id` only; ASR/Thinker evidence refs contain no secrets. |

## Scenario MVP1-PLAN-ADVANCE-001

| Field | Spec |
| --- | --- |
| purpose | Validate that a material UserPatch advances plan version only after SlowTask interpretation and triggers replayable replanning. |
| initial state | Active SlowTask `T1`; current `plan_version=N`; `USER_PATCH_RECEIVED(P1, observed_plan_version=N)` already recorded. |
| event chain | `USER_PATCH_INTERPRETED(patch_id=P1, task_id=T1, plan_version=N, task_event_seq=S, observed_plan_version=N, interpreted_against_plan_version=N, interpretation_type=constraint_update or slot_update, materially_changes_task=true)` -> `PLAN_VERSION_ADVANCED(task_id=T1, plan_version=N+1, task_event_seq=S+1, from_plan_version=N, to_plan_version=N+1, caused_by_user_patch_event_id=...)` -> `PLANNING_RESTARTED(plan_version=N+1)` -> `TASK_REPLANNED(plan_version=N+1, superseded_plan_version=N)` -> `SLOWTASK_STATE_CHANGED(to_state=PLANNING)`. |
| required assertions | `USER_PATCH_RECEIVED` uses pre-advance plan; `USER_PATCH_INTERPRETED` carries observed/current plan binding and `task_event_seq`; only `PLAN_VERSION_ADVANCED` changes current plan; `PLAN_VERSION_ADVANCED.plan_version` equals `to_plan_version`; `from_plan_version` and `to_plan_version` are monotonic; replanning references the superseded plan; no SemanticCommitment from old plan is emitted after advance. |
| replay expectations | Replay final `SlowTaskState.current_plan_version=N+1` and preserves the patch-to-plan-advance causal chain. |
| forbidden behavior | No plan advance before `USER_PATCH_INTERPRETED`; no Router-owned plan advance; no hidden direct slot/constraint mutation from UserPatch receipt. |
| fixture privacy requirements | Interpretation reason and evidence use synthetic/redacted refs; no raw task content is required. |

## Scenario MVP1-FOREGROUND-CHAT-001

| Field | Spec |
| --- | --- |
| purpose | Validate that foreground chat during an active SlowTask does not patch or mutate the active task. |
| initial state | Active SlowTask `T1`; current `plan_version=N`; `TaskFocusState.side_conversation_allowed=true`. |
| event chain | New committed turn -> mock ASR/Thinker frames -> `ROUTER_DECISION_EMITTED(router_decision=FAST_ONLY, task_focus=FOREGROUND_CHAT)` -> `TASK_FOCUS_STATE_UPDATED(active_task_id=T1, foreground_mode=FAST_RESPONSE)`. Optional MVP-0 mock playback events may occur for the foreground reply. |
| required assertions | No `USER_PATCH_RECEIVED`; no `USER_PATCH_INTERPRETED`; no `PLAN_VERSION_ADVANCED`; no SlowTask state change; active task id remains `T1`. |
| replay expectations | Replay preserves foreground focus decision and unchanged `SlowTaskState`. |
| forbidden behavior | Foreground chat must not become UserPatch evidence; Router must not reinterpret it as task feedback unless explicitly classified as active-task patch. |
| fixture privacy requirements | Foreground text is synthetic/redacted; no raw audio or raw trace. |

## Scenario MVP1-AMBIGUOUS-NO-PATCH-001

| Field | Spec |
| --- | --- |
| purpose | Validate that ambiguous input with an active SlowTask does not patch the task by default. |
| initial state | Active SlowTask `T1`; current `plan_version=N`; `TaskFocusState.ambiguous_input_policy=CLARIFY`. |
| event chain | New committed turn -> mock ASR/Thinker frames with low or mixed focus confidence -> `ROUTER_DECISION_EMITTED(router_decision=FAST_ONLY, task_focus=AMBIGUOUS, evidence_uncertainty=high)` -> `TASK_FOCUS_STATE_UPDATED(active_task_id=T1, last_focus_decision=AMBIGUOUS)`. Optional `WAITING_USER(wait_reason=clarify_task_focus)` may be emitted if the runtime chooses to journal the clarification wait. |
| required assertions | No UserPatch is generated; no SlowTask state or plan changes; ambiguity is measurable through Router metadata. |
| replay expectations | Replay reconstructs ambiguous focus decision and unchanged active SlowTask. |
| forbidden behavior | No default patching on ambiguous input; no Router final conflict verdict; no SlowTask cancel or switch-task confirmation from ambiguity alone. |
| fixture privacy requirements | Ambiguous utterance is synthetic/redacted; uncertainty metadata contains no raw transcript. |

## Scenario MVP1-WAITING-SLOT-001

| Field | Spec |
| --- | --- |
| purpose | Validate SlowTask-led evidence review when critical information is missing and the task enters waiting-slot state. |
| initial state | Active SlowTask `T1` in `PLANNING`; current `plan_version=N`; evidence refs available but a critical slot is missing or ambiguous. |
| event chain | `EVIDENCE_REVIEWED(task_id=T1, plan_version=N, review_result=insufficient)` -> optional `AMBIGUITY_DETECTED` -> `INSUFFICIENT_EVIDENCE_FOR_ACTION(blocking_fields=[...])` -> `CLARIFICATION_REQUESTED(missing_or_ambiguous_fields=[...], clarification_prompt_ref=...)` -> `WAITING_FOR_SLOT(missing_fields=[...])` -> `SLOWTASK_STATE_CHANGED(from_state=PLANNING, to_state=WAITING_FOR_SLOT)`. |
| required assertions | SlowTask, not Router, owns missing/ambiguous field decision; no tool call or SemanticCommitment is emitted; `WAITING_FOR_SLOT` carries `task_id`, `plan_version`, and `task_event_seq`; clarification prompt is a ref. |
| replay expectations | Replay reconstructs missing fields, waiting-slot state, and evidence provenance without needing raw evidence. |
| forbidden behavior | No `TOOL_CALL_STARTED`, no `TOOL_EXECUTION_STARTED`, no `SEMANTIC_COMMITMENT_EMITTED`, no ASR/Thinker winner chosen by Router. |
| fixture privacy requirements | Missing field names are safe metadata; values are synthetic/redacted or omitted. |

## Scenario MVP1-STALE-RESULT-001

| Field | Spec |
| --- | --- |
| purpose | Validate that an old-plan ToolResult is recorded as stale and cannot advance the current plan without adoption. |
| initial state | Active SlowTask `T1`; current `plan_version=N`; mock `TOOL_CALL_STARTED(tool_call_id=C1, plan_version=N)` recorded; no real tool execution. |
| event chain | `USER_PATCH_RECEIVED(P1, plan_version=N)` -> `USER_PATCH_INTERPRETED(P1, plan_version=N, task_event_seq=S, materially_changes_task=true)` -> `PLAN_VERSION_ADVANCED(plan_version=N+1, task_event_seq=S+1, from_plan_version=N, to_plan_version=N+1)` -> `PLANNING_RESTARTED(plan_version=N+1)` -> `TASK_REPLANNED(plan_version=N+1)` -> `TOOL_RESULT_RECEIVED(tool_call_id=C1, task_id=T1, plan_version=N, result_ref=R1)` -> `TOOL_RESULT_MARKED_STALE(tool_call_id=C1, task_id=T1, plan_version=N+1, task_event_seq=Sx, result_plan_version=N, current_plan_version=N+1)` -> `STALE_EVIDENCE_RECORDED(task_id=T1, plan_version=N+1, task_event_seq=Sx+1, source_tool_result_event_id=...)`. |
| required assertions | Old result keeps original plan binding; stale chain is emitted with current-plan and `task_event_seq` binding; `SlowTaskState.current_plan_version` remains `N+1`; no resolved arguments or commitment are produced from stale evidence. |
| replay expectations | Replay records stale evidence and leaves current plan state unchanged except for stale evidence metadata. |
| forbidden behavior | No `STALE_EVIDENCE_ADOPTED`; no SemanticCommitment or plan advance caused by stale result; no fake tool cancellation success. |
| fixture privacy requirements | Tool result is synthetic/minimized; no external API payload, credential, or side effect. |

## Scenario MVP1-STALE-ADOPTED-001

| Field | Spec |
| --- | --- |
| purpose | Validate the explicit adoption path for stale evidence and prove that adoption metadata gates reuse. |
| initial state | Same as `MVP1-STALE-RESULT-001` after `STALE_EVIDENCE_RECORDED`; current `plan_version=N+1`; stale evidence ref `S1`. |
| event chain | `STALE_EVIDENCE_ADOPTED(task_id=T1, plan_version=N+1, task_event_seq=S_adopt, stale_evidence_ref=S1, source_tool_result_event_id=..., adopted_from_plan_version=N, adoption_mode=adopt_or_rebase, adoption_reason=..., adopted_scope=..., adopted_by_event_id=...)` -> `EVIDENCE_REVIEWED(plan_version=N+1, evidence_refs=[S1])` -> optional `ARGUMENTS_RESOLVED` / `ARGUMENT_RESOLUTION_PROVENANCE` -> optional `FINALIZING` -> optional `SEMANTIC_COMMITMENT_EMITTED(task_id=T1, plan_version=N+1, task_event_seq=S_commit, source_events includes STALE_EVIDENCE_ADOPTED)`. |
| required assertions | Adoption event is required before stale evidence affects current plan; adopted scope is bounded; current-plan commitment references the adoption source if used. |
| replay expectations | Replay reconstructs stale evidence, adopted evidence metadata, and any current-plan use of adopted evidence. |
| forbidden behavior | No cross-plan reuse without `STALE_EVIDENCE_ADOPTED`; no adoption with missing source result event; no unbounded adoption scope. |
| fixture privacy requirements | Stale/adopted evidence refs are synthetic/minimized and contain no real tool payload. |

## Scenario MVP1-CANCEL-001

| Field | Spec |
| --- | --- |
| purpose | Validate ADR-016 cancel confirmation path: cancel intent enters as UserPatch evidence and SlowTask owns confirmation and terminal cancellation. |
| initial state | Active SlowTask `T1`; current `plan_version=N`; no terminal outcome; no pending confirmation. |
| event chain | Cancel-like committed turn -> mock ASR/Thinker frames -> `ROUTER_DECISION_EMITTED(router_decision=PATCH_ACTIVE_SLOW_TASK, task_focus=CANCEL_OR_PAUSE_CANDIDATE)` -> `TASK_FOCUS_STATE_UPDATED(active_task_id=T1)` -> `USER_PATCH_RECEIVED(P_cancel, plan_version=N)` -> `USER_PATCH_INTERPRETED(P_cancel, interpretation_type=cancel, materially_changes_task=false)` -> `CONFIRMATION_REQUIRED(confirmation_scope=TASK_CANCEL)` -> `WAITING_FOR_USER_CONFIRMATION` -> `SLOWTASK_STATE_CHANGED(to_state=WAITING_FOR_USER_CONFIRMATION)` -> confirmation committed turn -> `USER_PATCH_RECEIVED(P_confirm, plan_version=N)` -> `USER_PATCH_INTERPRETED(P_confirm, interpretation_type=confirmation)` -> `USER_CONFIRMATION_RECEIVED` -> `CONFIRMATION_ACCEPTED` -> `SLOWTASK_CANCEL_REQUESTED(cancel_reason=...)` -> `SLOWTASK_CANCELLED` -> `SLOWTASK_STATE_CHANGED(to_state=CANCELLED)` -> `TASK_FOCUS_STATE_UPDATED(active_task_id=null)`. |
| required assertions | Router does not cancel; raw text is not accepted as confirmation; confirmation is current-plan; terminal cancellation is sticky; late UserPatch/ToolResult/confirmation cannot revive or advance the task. |
| replay expectations | Replay reconstructs pending confirmation, accepted confirmation, cancellation request, cancellation terminal state, and focus cleanup. |
| forbidden behavior | No direct `SLOWTASK_CANCELLED` from Router; no pause/resume; no switch to a new task before active task is terminal; no tool authorization side effect. |
| fixture privacy requirements | Cancel and confirmation utterances are synthetic/redacted; prompt and authorization fields are refs without secrets. |

## Scenario MVP1-SWITCH-TASK-001

| Field | Spec |
| --- | --- |
| purpose | Validate ADR-006/016 switch-task handling: a new-task candidate while another SlowTask is active becomes UserPatch control evidence, then SlowTask-owned `SWITCH_TASK` confirmation controls cancel-then-spawn. |
| initial state | Active SlowTask `T1`; current `plan_version=N`; `TaskFocusState.active_task_id=T1`; no terminal outcome. |
| event chain | New-task-like committed turn -> mock ASR/Thinker frames -> `ROUTER_DECISION_EMITTED(router_decision=PATCH_ACTIVE_SLOW_TASK, task_focus=NEW_TASK_CANDIDATE)` -> `TASK_FOCUS_STATE_UPDATED(active_task_id=T1)` -> `USER_PATCH_RECEIVED(P_switch, plan_version=N, candidate_patch_types includes switch_task_candidate)` -> `USER_PATCH_INTERPRETED(P_switch, interpretation_type=switch_task, materially_changes_task=false)` -> `CONFIRMATION_REQUIRED(confirmation_scope=SWITCH_TASK)` -> `WAITING_FOR_USER_CONFIRMATION` -> `SLOWTASK_STATE_CHANGED(to_state=WAITING_FOR_USER_CONFIRMATION)`. Accepted branch: confirmation committed turn -> `USER_PATCH_RECEIVED(P_accept, plan_version=N)` -> `USER_PATCH_INTERPRETED(P_accept, interpretation_type=confirmation)` -> `USER_CONFIRMATION_RECEIVED` -> `CONFIRMATION_ACCEPTED(accepted_scope=SWITCH_TASK)` -> `SLOWTASK_CANCEL_REQUESTED(cancel_reason=switch_task_accepted)` -> `SLOWTASK_CANCELLED` -> `SLOWTASK_STATE_CHANGED(to_state=CANCELLED)` -> `TASK_FOCUS_STATE_UPDATED(active_task_id=null)` -> later `ROUTER_DECISION_EMITTED(router_decision=SPAWN_SLOW_TASK)` for the preserved new-task evidence -> `SLOWTASK_CREATED(task_id=T2)` -> `TASK_FOCUS_STATE_UPDATED(active_task_id=T2)`. Rejected branch: confirmation committed turn -> `USER_PATCH_RECEIVED(P_reject, plan_version=N)` -> `USER_PATCH_INTERPRETED(P_reject, interpretation_type=confirmation or feedback)` -> `USER_CONFIRMATION_RECEIVED` -> `CONFIRMATION_REJECTED` -> `SLOWTASK_STATE_CHANGED(to_state=PLANNING or previous non-terminal state)` with `active_task_id=T1` preserved. |
| required assertions | Router does not spawn `T2` while `T1` is non-terminal; new-task candidate is non-authoritative UserPatch evidence; accepted switch cancels `T1` before spawn; rejected switch does not mutate `T1` goal, constraints, resolved arguments, or plan version unless a separate material patch is later interpreted. |
| replay expectations | Replay reconstructs both accepted and rejected switch fixtures, including confirmation state, terminal cancellation for accepted switch, preserved active task for rejected switch, and no active-task overlap. |
| forbidden behavior | No automatic task replacement; no multiple active SlowTasks; no pause/resume; no spawn before `T1` reaches terminal state; no Router-owned cancel. |
| fixture privacy requirements | New-task candidate, confirmation, and rejected-switch utterances are synthetic/redacted or referenced; preserved evidence refs contain no secrets. |

## Scenario MVP1-FAILED-001

| Field | Spec |
| --- | --- |
| purpose | Validate failed-state replay and terminal stickiness required by ADR-016. |
| initial state | Active SlowTask `T1` in `PLANNING` or `EXECUTING`; current `plan_version=N`; no terminal outcome. |
| event chain | `EVIDENCE_REVIEWED(task_id=T1, plan_version=N, task_event_seq=S-1, review_result=mock_unrecoverable_failure)` -> `SLOWTASK_FAILED(task_id=T1, plan_version=N, task_event_seq=S, failure_reason=mock_unrecoverable_failure)` -> `SLOWTASK_STATE_CHANGED(from_state=PLANNING or EXECUTING, to_state=FAILED, reason=mock_unrecoverable_failure)` -> optional late `USER_PATCH_RECEIVED` / `TOOL_RESULT_RECEIVED` / `USER_CONFIRMATION_RECEIVED` events for diagnostics only. |
| required assertions | Failed state is terminal and sticky; late UserPatch, ToolResult, or confirmation cannot advance plan, resolve arguments, emit SemanticCommitment, or change state away from `FAILED`; active focus cleanup, if emitted, remains Router-owned. |
| replay expectations | Replay reconstructs `SlowTaskState=FAILED`, terminal outcome metadata, and late-event diagnostics without re-running tools or models. |
| forbidden behavior | No retry loop, no automatic degrade-to-complete, no stale adoption after terminal failure, no hidden state recovery. |
| fixture privacy requirements | Failure reason is metadata only; late evidence refs are synthetic/minimal and contain no raw user input or tool payload. |

## Scenario MVP1-SEMANTIC-COMMITMENT-001

| Field | Spec |
| --- | --- |
| purpose | Validate that SemanticCommitment is emitted only by SlowTask from current-plan resolved facts and remains separate from MVP-2 Composer behavior. |
| initial state | Active SlowTask `T1`; current `plan_version=N`; evidence reviewed and critical arguments resolved, or adopted stale evidence already recorded via `STALE_EVIDENCE_ADOPTED`. |
| event chain | `EVIDENCE_REVIEWED(task_id=T1, plan_version=N, task_event_seq=S1)` -> `ARGUMENTS_RESOLVED(task_id=T1, plan_version=N, task_event_seq=S2, resolved_arguments_ref=...)` -> `ARGUMENT_RESOLUTION_PROVENANCE(task_id=T1, plan_version=N, task_event_seq=S3)` -> `FINALIZING(task_id=T1, plan_version=N, task_event_seq=S4)` -> `SEMANTIC_COMMITMENT_EMITTED(commitment_id=K1, task_id=T1, plan_version=N, task_event_seq=S5, source_events=[...])` -> `SLOWTASK_STATE_CHANGED(to_state=COMPLETED)`. |
| required assertions | Commitment binds current `task_id`, `plan_version`, and `task_event_seq`; source events explain resolved facts; if adopted stale evidence is used, source events include `STALE_EVIDENCE_ADOPTED`; final state is completed. |
| replay expectations | Replay reconstructs commitment metadata and final SlowTask state without generating spoken text or coverage checks. |
| forbidden behavior | No `SPOKEN_PLAN_EMITTED`; no `COMMITMENT_COVERAGE_CHECK_PASSED`; no `PROGRESS_TRUTHFULNESS_CHECK_PASSED`; no Composer rewrite; no commitment from stale evidence unless adopted. |
| fixture privacy requirements | Commitment uses `commitment_ref` with synthetic/redacted/minimal facts; no raw user input, raw tool payload, or secret. |

## MVP-1 Scenario Suite Requirements

- The acceptance runner must cover all scenario ids listed in this document.
- Required ids are `MVP1-SPAWN-SLOWTASK-001`, `MVP1-ACTIVE-PATCH-001`, `MVP1-PLAN-ADVANCE-001`, `MVP1-FOREGROUND-CHAT-001`, `MVP1-AMBIGUOUS-NO-PATCH-001`, `MVP1-WAITING-SLOT-001`, `MVP1-STALE-RESULT-001`, `MVP1-STALE-ADOPTED-001`, `MVP1-CANCEL-001`, `MVP1-SWITCH-TASK-001`, `MVP1-FAILED-001`, and `MVP1-SEMANTIC-COMMITMENT-001`.
- Every scenario must replay deterministically from recorded events and refs.
- Every scenario must preserve `event_seq` ordering and SlowTask `task_event_seq` monotonicity.
- Every SlowTask-relevant scenario must fail if required current-plan binding or `task_event_seq` is missing from critical events.
- Every committed fixture must declare `fixture_domain=GITHUB_ALLOWED` or an equivalent repo-safe fixture domain.
- The suite must fail if a fixture contains raw audio, raw debug trace, secrets, unredacted real user input, unredacted sensitive tool results, or large raw web content.
- The suite must fail if an MVP-1 fixture uses unregistered MVP-relevant journal event names.
- The suite must fail if MVP-2-only behavior appears, including `TOOL_EXECUTION_STARTED`, `TOOL_UI_STATE_PATCHED`, `SPOKEN_PLAN_EMITTED`, CommitmentCoverageCheck, ProgressTruthfulnessCheck, demo tools, frontend UI patching, or real external side effects.
- The suite should emit a lightweight synthetic eval table from fixture metadata for patch focus, ambiguity handling, and UserPatch interpretation/materiality. These rows are acceptance measurements, not real-model quality claims.
