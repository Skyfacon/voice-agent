from __future__ import annotations

import pytest

from voice_agent.state.slowtask_state import SlowTaskState, SlowTaskStateError


def slowtask_event(event_name: str, **overrides: object) -> dict[str, object]:
    event: dict[str, object] = {
        "event_name": event_name,
        "event_id": f"evt_{event_name.lower()}_{overrides.get('task_event_seq', 1)}",
        "task_id": "task_slice3_001",
        "plan_version": 1,
        "task_event_seq": 1,
    }
    event.update(overrides)
    return event


def created_event(**overrides: object) -> dict[str, object]:
    event = slowtask_event(
        "SLOWTASK_CREATED",
        initial_goal_ref="goal://synthetic/mvp1/slice3/initial",
    )
    event.update(overrides)
    return event


def create_planning_state() -> SlowTaskState:
    state = SlowTaskState()
    state.reduce_event(created_event())
    state.reduce_event(
        slowtask_event(
            "SLOWTASK_STATE_CHANGED",
            event_id="evt_slice3_planning",
            task_event_seq=2,
            from_state="CREATED",
            to_state="PLANNING",
            reason="initial_planning_started",
        )
    )
    return state


def test_slowtask_created_initializes_state_without_completing_task() -> None:
    state = SlowTaskState()

    assert state.reduce_event(created_event(source_evidence_refs=["evidence://synthetic/mvp1/source"]))

    task = state.tasks["task_slice3_001"]
    assert task.task_id == "task_slice3_001"
    assert task.lifecycle_state == "CREATED"
    assert task.current_plan_version == 1
    assert task.current_task_event_seq == 1
    assert task.initial_goal_ref == "goal://synthetic/mvp1/slice3/initial"
    assert task.source_evidence_refs == ("evidence://synthetic/mvp1/source",)
    assert task.terminal_outcome is None
    assert task.completed_event_id is None


def test_slowtask_created_rejects_second_non_terminal_task() -> None:
    state = SlowTaskState()
    state.reduce_event(created_event())

    with pytest.raises(SlowTaskStateError, match="single active SlowTask"):
        state.reduce_event(
            created_event(
                event_id="evt_slice3_second_created_while_first_active",
                task_id="task_slice3_second",
                initial_goal_ref="goal://synthetic/mvp1/slice3/second",
            )
        )

    state.reduce_event(
        slowtask_event(
            "SLOWTASK_STATE_CHANGED",
            event_id="evt_slice3_first_failed",
            task_event_seq=2,
            from_state="CREATED",
            to_state="FAILED",
            reason="synthetic_terminal_before_next_task",
        )
    )
    assert state.reduce_event(
        created_event(
            event_id="evt_slice3_second_created_after_first_terminal",
            task_id="task_slice3_second",
            initial_goal_ref="goal://synthetic/mvp1/slice3/second",
        )
    )


def test_state_changed_updates_state_only_for_legal_transitions() -> None:
    state = SlowTaskState()
    state.reduce_event(created_event())

    assert state.reduce_event(
        slowtask_event(
            "SLOWTASK_STATE_CHANGED",
            task_event_seq=2,
            from_state="CREATED",
            to_state="PLANNING",
            reason="initial_planning_started",
        )
    )
    assert state.tasks["task_slice3_001"].lifecycle_state == "PLANNING"

    with pytest.raises(SlowTaskStateError, match="Illegal SlowTask transition"):
        state.reduce_event(
            slowtask_event(
                "SLOWTASK_STATE_CHANGED",
                task_event_seq=3,
                from_state="PLANNING",
                to_state="CREATED",
                reason="illegal_backwards_transition",
            )
        )
    assert state.tasks["task_slice3_001"].lifecycle_state == "PLANNING"


def test_plan_version_advanced_is_the_only_current_plan_mutator() -> None:
    state = create_planning_state()
    task = state.tasks["task_slice3_001"]

    state.reduce_event(
        slowtask_event(
            "USER_PATCH_RECEIVED",
            event_id="evt_slice3_patch_received",
            task_event_seq=3,
            patch_id="patch_slice3_001",
            observed_plan_version=1,
            evidence_ref="evidence://synthetic/mvp1/slice3/patch",
        )
    )
    state.reduce_event(
        slowtask_event(
            "USER_PATCH_INTERPRETED",
            event_id="evt_slice3_patch_interpreted",
            task_event_seq=4,
            patch_id="patch_slice3_001",
            observed_plan_version=1,
            interpreted_against_plan_version=1,
            interpretation_type="constraint_update",
            materially_changes_task=True,
        )
    )
    assert task.current_plan_version == 1

    state.reduce_event(
        slowtask_event(
            "PLAN_VERSION_ADVANCED",
            event_id="evt_slice3_plan_advanced",
            task_event_seq=5,
            plan_version=2,
            from_plan_version=1,
            to_plan_version=2,
            planning_reason="material_user_patch",
        )
    )

    assert task.current_plan_version == 2
    assert task.current_task_event_seq == 5


def test_user_patch_received_appends_evidence_only_without_mutating_task_semantics() -> None:
    state = create_planning_state()
    task = state.tasks["task_slice3_001"]
    before = (
        task.initial_goal_ref,
        task.constraints_ref,
        task.resolved_arguments_refs,
        task.confirmation_state,
        task.current_plan_version,
    )

    state.reduce_event(
        slowtask_event(
            "USER_PATCH_RECEIVED",
            event_id="evt_slice3_patch_received",
            task_event_seq=3,
            patch_id="patch_slice3_001",
            observed_plan_version=1,
            evidence_ref="evidence://synthetic/mvp1/slice3/patch",
            turn_id="turn_slice3_patch",
            utterance_id="utt_slice3_patch",
            initial_goal_ref="goal://synthetic/mvp1/slice3/ignored-rewrite",
            resolved_arguments_ref="args://synthetic/mvp1/slice3/ignored",
            confirmation_id="confirmation_slice3_ignored",
        )
    )

    assert (
        task.initial_goal_ref,
        task.constraints_ref,
        task.resolved_arguments_refs,
        task.confirmation_state,
        task.current_plan_version,
    ) == before
    assert [patch.patch_id for patch in task.user_patch_evidence] == ["patch_slice3_001"]
    assert task.user_patch_evidence[0].evidence_ref == "evidence://synthetic/mvp1/slice3/patch"


def test_user_patch_received_observed_plan_version_must_match_current_plan() -> None:
    state = create_planning_state()

    with pytest.raises(SlowTaskStateError, match="observed_plan_version"):
        state.reduce_event(
            slowtask_event(
                "USER_PATCH_RECEIVED",
                event_id="evt_slice3_patch_received_stale_observed_plan",
                task_event_seq=3,
                patch_id="patch_slice3_stale_observed",
                observed_plan_version=0,
                evidence_ref="evidence://synthetic/mvp1/slice3/stale-observed-plan",
            )
        )


def test_user_patch_interpreted_observed_plan_version_must_match_current_plan() -> None:
    state = create_planning_state()

    with pytest.raises(SlowTaskStateError, match="observed_plan_version"):
        state.reduce_event(
            slowtask_event(
                "USER_PATCH_INTERPRETED",
                event_id="evt_slice3_patch_interpreted_stale_observed_plan",
                task_event_seq=3,
                patch_id="patch_slice3_stale_observed",
                observed_plan_version=0,
                interpreted_against_plan_version=0,
                interpretation_type="constraint_update",
                materially_changes_task=True,
            )
        )


def test_user_patch_interpreted_requires_prior_user_patch_evidence() -> None:
    state = create_planning_state()

    with pytest.raises(SlowTaskStateError, match="USER_PATCH_RECEIVED"):
        state.reduce_event(
            slowtask_event(
                "USER_PATCH_INTERPRETED",
                event_id="evt_slice3_patch_interpreted_without_evidence",
                task_event_seq=3,
                patch_id="patch_slice3_missing_evidence",
                observed_plan_version=1,
                interpreted_against_plan_version=1,
                interpretation_type="constraint_update",
                materially_changes_task=True,
            )
        )

    state.reduce_event(
        slowtask_event(
            "USER_PATCH_RECEIVED",
            event_id="evt_slice3_patch_received",
            task_event_seq=3,
            patch_id="patch_slice3_with_evidence",
            observed_plan_version=1,
            evidence_ref="evidence://synthetic/mvp1/slice3/patch-with-evidence",
        )
    )
    assert state.reduce_event(
        slowtask_event(
            "USER_PATCH_INTERPRETED",
            event_id="evt_slice3_patch_interpreted",
            task_event_seq=4,
            patch_id="patch_slice3_with_evidence",
            observed_plan_version=1,
            interpreted_against_plan_version=1,
            interpretation_type="constraint_update",
            materially_changes_task=True,
        )
    )


def test_confirmation_acceptance_requires_matching_pending_confirmation_and_user_signal() -> None:
    state = create_planning_state()

    with pytest.raises(SlowTaskStateError, match="pending confirmation"):
        state.reduce_event(
            slowtask_event(
                "CONFIRMATION_ACCEPTED",
                event_id="evt_slice3_confirmation_accepted_without_gate",
                task_event_seq=3,
                confirmation_id="confirmation_slice3_missing_gate",
                accepted_scope="TASK_CANCEL",
                authorization_ref="authorization://synthetic/mvp1/slice3/missing-gate",
            )
        )

    state.reduce_event(
        slowtask_event(
            "CONFIRMATION_REQUIRED",
            event_id="evt_slice3_confirmation_required",
            task_event_seq=3,
            confirmation_id="confirmation_slice3_gate",
            confirmation_scope="TASK_CANCEL",
            required_for_event_id="evt_slice3_required_action",
            prompt_ref="prompt://synthetic/mvp1/slice3/confirm",
        )
    )
    with pytest.raises(SlowTaskStateError, match="USER_CONFIRMATION_RECEIVED"):
        state.reduce_event(
            slowtask_event(
                "CONFIRMATION_ACCEPTED",
                event_id="evt_slice3_confirmation_accepted_without_signal",
                task_event_seq=4,
                confirmation_id="confirmation_slice3_gate",
                accepted_scope="TASK_CANCEL",
                authorization_ref="authorization://synthetic/mvp1/slice3/no-signal",
            )
        )

    state.reduce_event(
        slowtask_event(
            "USER_PATCH_RECEIVED",
            event_id="evt_slice3_confirm_patch_received",
            task_event_seq=4,
            patch_id="patch_slice3_confirm",
            observed_plan_version=1,
            evidence_ref="evidence://synthetic/mvp1/slice3/confirm-patch",
        )
    )
    state.reduce_event(
        slowtask_event(
            "USER_PATCH_INTERPRETED",
            event_id="evt_slice3_confirm_patch_interpreted",
            task_event_seq=5,
            patch_id="patch_slice3_confirm",
            observed_plan_version=1,
            interpreted_against_plan_version=1,
            interpretation_type="confirmation",
            materially_changes_task=False,
        )
    )
    state.reduce_event(
        slowtask_event(
            "USER_CONFIRMATION_RECEIVED",
            event_id="evt_slice3_user_confirmation_received",
            task_event_seq=6,
            confirmation_id="confirmation_slice3_gate",
            patch_id="patch_slice3_confirm",
            confirmation_signal="accepted",
        )
    )
    assert state.reduce_event(
        slowtask_event(
            "CONFIRMATION_ACCEPTED",
            event_id="evt_slice3_confirmation_accepted",
            task_event_seq=7,
            confirmation_id="confirmation_slice3_gate",
            accepted_scope="TASK_CANCEL",
            authorization_ref="authorization://synthetic/mvp1/slice3/current-plan-confirmation",
        )
    )
    assert state.tasks["task_slice3_001"].confirmation_state.status == "accepted"


def test_user_confirmation_received_requires_matching_interpreted_user_patch() -> None:
    state = create_planning_state()
    state.reduce_event(
        slowtask_event(
            "CONFIRMATION_REQUIRED",
            event_id="evt_slice3_confirmation_required",
            task_event_seq=3,
            confirmation_id="confirmation_slice3_gate",
            confirmation_scope="TASK_CANCEL",
            required_for_event_id="evt_slice3_required_action",
            prompt_ref="prompt://synthetic/mvp1/slice3/confirm",
        )
    )

    with pytest.raises(SlowTaskStateError, match="USER_PATCH_INTERPRETED"):
        state.reduce_event(
            slowtask_event(
                "USER_CONFIRMATION_RECEIVED",
                event_id="evt_slice3_user_confirmation_without_interpretation",
                task_event_seq=4,
                confirmation_id="confirmation_slice3_gate",
                patch_id="patch_slice3_missing_interpretation",
                confirmation_signal="accepted",
            )
        )

    state.reduce_event(
        slowtask_event(
            "USER_PATCH_RECEIVED",
            event_id="evt_slice3_confirmation_patch_received",
            task_event_seq=4,
            patch_id="patch_slice3_confirmation",
            observed_plan_version=1,
            evidence_ref="evidence://synthetic/mvp1/slice3/confirmation-patch",
        )
    )
    state.reduce_event(
        slowtask_event(
            "USER_PATCH_INTERPRETED",
            event_id="evt_slice3_confirmation_patch_interpreted",
            task_event_seq=5,
            patch_id="patch_slice3_confirmation",
            observed_plan_version=1,
            interpreted_against_plan_version=1,
            interpretation_type="confirmation",
            materially_changes_task=False,
        )
    )
    assert state.reduce_event(
        slowtask_event(
            "USER_CONFIRMATION_RECEIVED",
            event_id="evt_slice3_user_confirmation_received",
            task_event_seq=6,
            confirmation_id="confirmation_slice3_gate",
            patch_id="patch_slice3_confirmation",
            confirmation_signal="accepted",
        )
    )


def test_plan_version_advance_rejects_or_supersedes_pending_confirmation() -> None:
    state = create_planning_state()
    state.reduce_event(
        slowtask_event(
            "CONFIRMATION_REQUIRED",
            event_id="evt_slice3_confirmation_required",
            task_event_seq=3,
            confirmation_id="confirmation_slice3_stale",
            confirmation_scope="TASK_CANCEL",
            required_for_event_id="evt_slice3_required_action",
            prompt_ref="prompt://synthetic/mvp1/slice3/confirm",
        )
    )

    with pytest.raises(SlowTaskStateError, match="pending confirmation"):
        state.reduce_event(
            slowtask_event(
                "PLAN_VERSION_ADVANCED",
                event_id="evt_slice3_plan_advance_with_pending_confirmation",
                task_event_seq=4,
                plan_version=2,
                from_plan_version=1,
                to_plan_version=2,
                planning_reason="material_user_patch",
            )
        )

    state.reduce_event(
        slowtask_event(
            "CONFIRMATION_REJECTED",
            event_id="evt_slice3_confirmation_rejected_superseded",
            task_event_seq=4,
            confirmation_id="confirmation_slice3_stale",
            rejection_reason="plan_version_superseded",
        )
    )
    assert state.reduce_event(
        slowtask_event(
            "PLAN_VERSION_ADVANCED",
            event_id="evt_slice3_plan_advance_after_supersede",
            task_event_seq=5,
            plan_version=2,
            from_plan_version=1,
            to_plan_version=2,
            planning_reason="material_user_patch",
        )
    )
    assert state.tasks["task_slice3_001"].confirmation_state.pending_confirmation_id is None
    assert state.tasks["task_slice3_001"].current_plan_version == 2


def test_waiting_for_user_confirmation_progress_event_is_reduced() -> None:
    state = create_planning_state()
    state.reduce_event(
        slowtask_event(
            "CONFIRMATION_REQUIRED",
            event_id="evt_slice3_confirmation_required",
            task_event_seq=3,
            confirmation_id="confirmation_slice3_waiting",
            confirmation_scope="TASK_CANCEL",
            required_for_event_id="evt_slice3_required_action",
            prompt_ref="prompt://synthetic/mvp1/slice3/confirm",
        )
    )

    assert state.reduce_event(
        slowtask_event(
            "WAITING_FOR_USER_CONFIRMATION",
            event_id="evt_slice3_waiting_for_user_confirmation",
            task_event_seq=4,
            confirmation_id="confirmation_slice3_waiting",
        )
    )

    task = state.tasks["task_slice3_001"]
    assert task.current_task_event_seq == 4
    assert task.progress_events[-1].event_name == "WAITING_FOR_USER_CONFIRMATION"
    assert task.progress_events[-1].refs == ("confirmation_slice3_waiting",)


def test_old_plan_tool_result_requires_stale_mark_and_record_before_replay_completes() -> None:
    state = create_planning_state()
    state.reduce_event(
        slowtask_event(
            "PLAN_VERSION_ADVANCED",
            event_id="evt_slice3_plan_advanced",
            task_event_seq=3,
            plan_version=2,
            from_plan_version=1,
            to_plan_version=2,
            planning_reason="material_user_patch",
        )
    )
    state.reduce_event(
        slowtask_event(
            "TOOL_RESULT_RECEIVED",
            event_id="evt_slice3_old_plan_tool_result",
            task_event_seq=4,
            plan_version=1,
            tool_call_id="tool_call_slice3_old_plan",
            result_status="succeeded",
            result_ref="tool-result://synthetic/mvp1/slice3/old-plan",
        )
    )

    with pytest.raises(SlowTaskStateError, match="stale evidence"):
        state.validate_replay_complete()

    state.reduce_event(
        slowtask_event(
            "TOOL_RESULT_MARKED_STALE",
            event_id="evt_slice3_old_plan_marked_stale",
            task_event_seq=5,
            plan_version=2,
            tool_call_id="tool_call_slice3_old_plan",
            result_plan_version=1,
            current_plan_version=2,
            stale_reason="old_plan_result",
        )
    )
    with pytest.raises(SlowTaskStateError, match="stale evidence"):
        state.validate_replay_complete()

    state.reduce_event(
        slowtask_event(
            "STALE_EVIDENCE_RECORDED",
            event_id="evt_slice3_stale_evidence_recorded",
            task_event_seq=6,
            plan_version=2,
            stale_evidence_ref="stale-evidence://synthetic/mvp1/slice3/old-plan",
            source_tool_result_event_id="evt_slice3_old_plan_tool_result",
        )
    )
    state.validate_replay_complete()
    assert state.tasks["task_slice3_001"].stale_evidence_refs == (
        "stale-evidence://synthetic/mvp1/slice3/old-plan",
    )


def test_stale_evidence_adoption_requires_recorded_stale_evidence() -> None:
    state = create_planning_state()
    state.reduce_event(
        slowtask_event(
            "PLAN_VERSION_ADVANCED",
            event_id="evt_slice3_plan_advanced",
            task_event_seq=3,
            plan_version=2,
            from_plan_version=1,
            to_plan_version=2,
            planning_reason="material_user_patch",
        )
    )

    with pytest.raises(SlowTaskStateError, match="recorded stale evidence"):
        state.reduce_event(
            slowtask_event(
                "STALE_EVIDENCE_ADOPTED",
                event_id="evt_slice3_stale_adopted_without_record",
                task_event_seq=4,
                plan_version=2,
                stale_evidence_ref="stale-evidence://synthetic/mvp1/slice3/missing",
                source_tool_result_event_id="evt_slice3_missing_tool_result",
                adopted_from_plan_version=1,
                adoption_mode="adopt_or_rebase",
                adoption_reason="synthetic_reuse",
                adopted_scope=["synthetic_field"],
                adopted_by_event_id="evt_slice3_adoption_decision",
            )
        )

    state.reduce_event(
        slowtask_event(
            "TOOL_RESULT_RECEIVED",
            event_id="evt_slice3_old_plan_tool_result",
            task_event_seq=4,
            plan_version=1,
            tool_call_id="tool_call_slice3_old_plan",
            result_status="succeeded",
            result_ref="tool-result://synthetic/mvp1/slice3/old-plan",
        )
    )
    state.reduce_event(
        slowtask_event(
            "TOOL_RESULT_MARKED_STALE",
            event_id="evt_slice3_old_plan_marked_stale",
            task_event_seq=5,
            plan_version=2,
            tool_call_id="tool_call_slice3_old_plan",
            result_plan_version=1,
            current_plan_version=2,
            stale_reason="old_plan_result",
        )
    )
    state.reduce_event(
        slowtask_event(
            "STALE_EVIDENCE_RECORDED",
            event_id="evt_slice3_stale_evidence_recorded",
            task_event_seq=6,
            plan_version=2,
            stale_evidence_ref="stale-evidence://synthetic/mvp1/slice3/old-plan",
            source_tool_result_event_id="evt_slice3_old_plan_tool_result",
        )
    )
    assert state.reduce_event(
        slowtask_event(
            "STALE_EVIDENCE_ADOPTED",
            event_id="evt_slice3_stale_adopted",
            task_event_seq=7,
            plan_version=2,
            stale_evidence_ref="stale-evidence://synthetic/mvp1/slice3/old-plan",
            source_tool_result_event_id="evt_slice3_old_plan_tool_result",
            adopted_from_plan_version=1,
            adoption_mode="adopt_or_rebase",
            adoption_reason="synthetic_reuse",
            adopted_scope=["synthetic_field"],
            adopted_by_event_id="evt_slice3_adoption_decision",
        )
    )
    assert state.tasks["task_slice3_001"].adopted_evidence[-1].stale_evidence_ref == (
        "stale-evidence://synthetic/mvp1/slice3/old-plan"
    )


def test_slowtask_cancelled_requires_prior_cancel_request() -> None:
    state = create_planning_state()

    with pytest.raises(SlowTaskStateError, match="SLOWTASK_CANCEL_REQUESTED"):
        state.reduce_event(
            slowtask_event(
                "SLOWTASK_CANCELLED",
                event_id="evt_slice3_cancelled_without_request",
                task_event_seq=3,
                cancel_reason="synthetic_cancel",
                inflight_tool_policy="no_inflight_tools",
            )
        )

    state.reduce_event(
        slowtask_event(
            "USER_PATCH_RECEIVED",
            event_id="evt_slice3_cancel_patch_received",
            task_event_seq=3,
            patch_id="patch_slice3_cancel",
            observed_plan_version=1,
            evidence_ref="evidence://synthetic/mvp1/slice3/cancel-patch",
        )
    )
    state.reduce_event(
        slowtask_event(
            "USER_PATCH_INTERPRETED",
            event_id="evt_slice3_cancel_patch_interpreted",
            task_event_seq=4,
            patch_id="patch_slice3_cancel",
            observed_plan_version=1,
            interpreted_against_plan_version=1,
            interpretation_type="cancel",
            materially_changes_task=True,
        )
    )
    state.reduce_event(
        slowtask_event(
            "SLOWTASK_CANCEL_REQUESTED",
            event_id="evt_slice3_cancel_requested",
            task_event_seq=5,
            cancel_reason="synthetic_cancel",
        )
    )
    assert state.reduce_event(
        slowtask_event(
            "SLOWTASK_CANCELLED",
            event_id="evt_slice3_cancelled",
            task_event_seq=6,
            cancel_reason="synthetic_cancel",
            inflight_tool_policy="no_inflight_tools",
        )
    )


def test_reused_task_event_seq_is_rejected_for_mutating_slowtask_events() -> None:
    state = SlowTaskState()
    state.reduce_event(created_event(task_event_seq=1))

    with pytest.raises(SlowTaskStateError, match="task_event_seq"):
        state.reduce_event(
            slowtask_event(
                "SLOWTASK_STATE_CHANGED",
                task_event_seq=1,
                from_state="CREATED",
                to_state="PLANNING",
                reason="reused_task_event_seq",
            )
        )


def test_slowtask_failed_then_state_changed_failed_produces_terminal_failed_state() -> None:
    state = create_planning_state()
    task = state.tasks["task_slice3_001"]

    state.reduce_event(
        slowtask_event(
            "SLOWTASK_FAILED",
            event_id="evt_slice3_failed",
            task_event_seq=3,
            failure_reason="synthetic_unrecoverable_failure",
        )
    )
    assert task.lifecycle_state == "PLANNING"
    assert task.terminal_outcome is None
    assert task.failure_reason == "synthetic_unrecoverable_failure"

    state.reduce_event(
        slowtask_event(
            "SLOWTASK_STATE_CHANGED",
            event_id="evt_slice3_failed_state",
            task_event_seq=4,
            from_state="PLANNING",
            to_state="FAILED",
            reason="synthetic_unrecoverable_failure",
        )
    )

    assert task.lifecycle_state == "FAILED"
    assert task.terminal_outcome == "FAILED"
    assert task.completed_event_id == "evt_slice3_failed_state"


@pytest.mark.parametrize(
    "terminal_event,terminal_transition,expected_state",
    [
        (
            None,
            {
                "event_id": "evt_slice3_completed_state",
                "task_event_seq": 3,
                "from_state": "PLANNING",
                "to_state": "COMPLETED",
                "reason": "synthetic_commitment_complete",
            },
            "COMPLETED",
        ),
        (
            {
                "event_name": "SLOWTASK_CANCEL_REQUESTED",
                "event_id": "evt_slice3_cancel_requested",
                "task_event_seq": 3,
                "cancel_reason": "synthetic_cancel",
            },
            {
                "event_id": "evt_slice3_cancelled_state",
                "task_event_seq": 5,
                "from_state": "PLANNING",
                "to_state": "CANCELLED",
                "reason": "synthetic_cancel",
            },
            "CANCELLED",
        ),
        (
            {
                "event_name": "SLOWTASK_FAILED",
                "event_id": "evt_slice3_failed",
                "task_event_seq": 3,
                "failure_reason": "synthetic_unrecoverable_failure",
            },
            {
                "event_id": "evt_slice3_failed_state",
                "task_event_seq": 4,
                "from_state": "PLANNING",
                "to_state": "FAILED",
                "reason": "synthetic_unrecoverable_failure",
            },
            "FAILED",
        ),
    ],
)
def test_terminal_states_are_sticky_for_late_user_patch_tool_result_and_confirmation_events(
    terminal_event: dict[str, object] | None,
    terminal_transition: dict[str, object],
    expected_state: str,
) -> None:
    state = create_planning_state()
    if terminal_event is not None:
        state.reduce_event(slowtask_event(**terminal_event))
    if expected_state == "CANCELLED":
        state.reduce_event(
            slowtask_event(
                "SLOWTASK_CANCELLED",
                event_id="evt_slice3_cancelled",
                task_event_seq=4,
                cancel_reason="synthetic_cancel",
                inflight_tool_policy="no_inflight_tools",
            )
        )
    state.reduce_event(slowtask_event("SLOWTASK_STATE_CHANGED", **terminal_transition))
    task = state.tasks["task_slice3_001"]
    terminal_plan = task.current_plan_version

    for late_event in (
        slowtask_event(
            "USER_PATCH_RECEIVED",
            event_id=f"evt_slice3_late_patch_{expected_state.lower()}",
            task_event_seq=20,
            patch_id=f"patch_late_{expected_state.lower()}",
            observed_plan_version=terminal_plan,
            evidence_ref=f"evidence://synthetic/mvp1/slice3/late-{expected_state.lower()}",
        ),
        slowtask_event(
            "TOOL_RESULT_RECEIVED",
            event_id=f"evt_slice3_late_tool_result_{expected_state.lower()}",
            task_event_seq=21,
            tool_call_id=f"tool_call_late_{expected_state.lower()}",
            result_status="succeeded",
            result_ref=f"tool-result://synthetic/mvp1/slice3/late-{expected_state.lower()}",
        ),
        slowtask_event(
            "CONFIRMATION_REQUIRED",
            event_id=f"evt_slice3_late_confirmation_{expected_state.lower()}",
            task_event_seq=22,
            confirmation_id=f"confirmation_late_{expected_state.lower()}",
            confirmation_scope="TASK_CANCEL",
            required_for_event_id="evt_slice3_late_tool_result",
            prompt_ref=f"prompt://synthetic/mvp1/slice3/late-{expected_state.lower()}",
        ),
    ):
        assert state.reduce_event(late_event)

    assert task.lifecycle_state == expected_state
    assert task.terminal_outcome == expected_state
    assert task.current_plan_version == terminal_plan
    assert task.user_patch_evidence == ()
    assert task.tool_results == ()
    assert task.confirmation_state.pending_confirmation_id is None
    assert [event.event_name for event in task.late_events] == [
        "USER_PATCH_RECEIVED",
        "TOOL_RESULT_RECEIVED",
        "CONFIRMATION_REQUIRED",
    ]
