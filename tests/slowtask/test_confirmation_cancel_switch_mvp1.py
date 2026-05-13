from __future__ import annotations

from typing import Any

import pytest

from voice_agent.runtime.session import start_mvp0_session
from voice_agent.slowtask.mock_runtime import MockSlowTaskRuntime
from voice_agent.state.slowtask_state import SlowTaskState, SlowTaskStateError


def test_cancel_candidate_enters_slowtask_confirmation_before_terminal_cancel() -> None:
    journal, cancel_patch = _active_task_with_patch(
        suffix="cancel",
        task_focus="CANCEL_OR_PAUSE_CANDIDATE",
        candidate_patch_types=("cancel_candidate",),
        patch_id="patch_mvp1_slice9_cancel",
        evidence_ref="evidence://synthetic/mvp1/slice9/cancel",
    )

    request = MockSlowTaskRuntime(journal).interpret_user_patch(
        user_patch_event=cancel_patch,
        event_id_prefix="evt_mvp1_slice9_cancel",
        created_monotonic_ms=180,
        created_wall_clock_ms=1700000009180,
        current_lifecycle_state="PLANNING",
        confirmation_id="confirmation_mvp1_slice9_cancel",
        prompt_ref="prompt://synthetic/mvp1/slice9/cancel",
    )

    assert [event["event_name"] for event in request.produced_events] == [
        "USER_PATCH_INTERPRETED",
        "CONFIRMATION_REQUIRED",
        "WAITING_FOR_USER_CONFIRMATION",
        "SLOWTASK_STATE_CHANGED",
    ]
    interpreted, required, waiting, state_changed = request.produced_events
    assert interpreted["interpretation_type"] == "cancel"
    assert interpreted["materially_changes_task"] is False
    assert required["confirmation_scope"] == "TASK_CANCEL"
    assert required["required_for_event_id"] == interpreted["event_id"]
    assert waiting["confirmation_id"] == required["confirmation_id"]
    assert state_changed["from_state"] == "PLANNING"
    assert state_changed["to_state"] == "WAITING_FOR_USER_CONFIRMATION"

    confirm_patch = _append_user_patch_received(
        journal,
        caused_by_event_id="evt_mvp1_slice9_cancel_router",
        event_id="evt_mvp1_slice9_cancel_confirm_patch_received",
        patch_id="patch_mvp1_slice9_cancel_confirm",
        task_event_seq=9,
        evidence_ref="evidence://synthetic/mvp1/slice9/cancel-confirm",
        candidate_patch_types=("confirmation_candidate",),
        turn_id="turn_mvp1_slice9_cancel_confirm",
        utterance_id="utt_mvp1_slice9_cancel_confirm",
    )

    accepted = MockSlowTaskRuntime(journal).interpret_user_patch(
        user_patch_event=confirm_patch,
        event_id_prefix="evt_mvp1_slice9_cancel_accept",
        created_monotonic_ms=190,
        created_wall_clock_ms=1700000009190,
        current_lifecycle_state="WAITING_FOR_USER_CONFIRMATION",
        pending_confirmation_id="confirmation_mvp1_slice9_cancel",
        pending_confirmation_scope="TASK_CANCEL",
        confirmation_signal="accepted",
        authorization_ref="authorization://synthetic/mvp1/slice9/taskcancel",
    )

    assert [event["event_name"] for event in accepted.produced_events] == [
        "USER_PATCH_INTERPRETED",
        "USER_CONFIRMATION_RECEIVED",
        "CONFIRMATION_ACCEPTED",
        "SLOWTASK_CANCEL_REQUESTED",
        "SLOWTASK_CANCELLED",
        "SLOWTASK_STATE_CHANGED",
    ]
    assert accepted.produced_events[0]["interpretation_type"] == "confirmation"
    assert accepted.produced_events[1]["confirmation_signal"] == "accepted"
    assert accepted.produced_events[2]["accepted_scope"] == "TASK_CANCEL"
    assert accepted.produced_events[3]["cancel_reason"] == "task_cancel_accepted"
    assert accepted.produced_events[-1]["to_state"] == "CANCELLED"

    slowtask_state = _reduce_slowtask_events(journal.events())
    task = slowtask_state.tasks["task_mvp1_slice9_active"]
    assert task.lifecycle_state == "CANCELLED"
    assert task.terminal_outcome == "CANCELLED"
    assert task.cancel_reason == "task_cancel_accepted"
    assert task.confirmation_state.status == "accepted"
    assert task.confirmation_state.pending_confirmation_id is None

    for late_event in (
        _late_user_patch_received(task_event_seq=20),
        _late_user_patch_interpreted(task_event_seq=21),
        _late_user_confirmation_received(task_event_seq=22),
    ):
        assert slowtask_state.reduce_event(late_event)

    assert task.lifecycle_state == "CANCELLED"
    assert task.current_plan_version == 1
    assert [event.event_name for event in task.late_events[-3:]] == [
        "USER_PATCH_RECEIVED",
        "USER_PATCH_INTERPRETED",
        "USER_CONFIRMATION_RECEIVED",
    ]


def test_switch_task_confirmation_accepts_by_cancelling_before_later_spawn() -> None:
    journal, switch_patch = _active_task_with_patch(
        suffix="switch",
        task_focus="NEW_TASK_CANDIDATE",
        candidate_patch_types=("switch_task_candidate",),
        patch_id="patch_mvp1_slice9_switch",
        evidence_ref="evidence://synthetic/mvp1/slice9/switch",
    )

    request = MockSlowTaskRuntime(journal).interpret_user_patch(
        user_patch_event=switch_patch,
        event_id_prefix="evt_mvp1_slice9_switch",
        created_monotonic_ms=180,
        created_wall_clock_ms=1700000009180,
        current_lifecycle_state="PLANNING",
        confirmation_id="confirmation_mvp1_slice9_switch",
        prompt_ref="prompt://synthetic/mvp1/slice9/switch",
    )
    assert request.produced_events[0]["interpretation_type"] == "switch_task"
    assert request.produced_events[1]["confirmation_scope"] == "SWITCH_TASK"

    slowtask_state = _reduce_slowtask_events(journal.events())
    with pytest.raises(SlowTaskStateError, match="single active SlowTask"):
        slowtask_state.reduce_event(
            _slowtask_created_event(
                event_id="evt_mvp1_slice9_spawn_before_cancel_created",
                task_id="task_mvp1_slice9_replacement",
            )
        )

    confirm_patch = _append_user_patch_received(
        journal,
        caused_by_event_id="evt_mvp1_slice9_switch_router",
        event_id="evt_mvp1_slice9_switch_confirm_patch_received",
        patch_id="patch_mvp1_slice9_switch_confirm",
        task_event_seq=9,
        evidence_ref="evidence://synthetic/mvp1/slice9/switch-confirm",
        candidate_patch_types=("confirmation_candidate",),
        turn_id="turn_mvp1_slice9_switch_confirm",
        utterance_id="utt_mvp1_slice9_switch_confirm",
    )

    accepted = MockSlowTaskRuntime(journal).interpret_user_patch(
        user_patch_event=confirm_patch,
        event_id_prefix="evt_mvp1_slice9_switch_accept",
        created_monotonic_ms=190,
        created_wall_clock_ms=1700000009190,
        current_lifecycle_state="WAITING_FOR_USER_CONFIRMATION",
        pending_confirmation_id="confirmation_mvp1_slice9_switch",
        pending_confirmation_scope="SWITCH_TASK",
        confirmation_signal="accepted",
        authorization_ref="authorization://synthetic/mvp1/slice9/switchtask",
    )

    assert [event["event_name"] for event in accepted.produced_events] == [
        "USER_PATCH_INTERPRETED",
        "USER_CONFIRMATION_RECEIVED",
        "CONFIRMATION_ACCEPTED",
        "SLOWTASK_CANCEL_REQUESTED",
        "SLOWTASK_CANCELLED",
        "SLOWTASK_STATE_CHANGED",
    ]
    assert accepted.produced_events[3]["cancel_reason"] == "switch_task_accepted"

    slowtask_state = _reduce_slowtask_events(journal.events())
    active = slowtask_state.tasks["task_mvp1_slice9_active"]
    assert active.lifecycle_state == "CANCELLED"
    assert active.terminal_outcome == "CANCELLED"
    assert active.cancel_reason == "switch_task_accepted"

    assert slowtask_state.reduce_event(
        _slowtask_created_event(
            event_id="evt_mvp1_slice9_spawn_after_cancel_created",
            task_id="task_mvp1_slice9_replacement",
            caused_by_event_id="evt_mvp1_slice9_switch_accept_state_cancelled",
        )
    )


def test_switch_task_confirmation_rejection_preserves_current_task_without_plan_mutation() -> None:
    journal, switch_patch = _active_task_with_patch(
        suffix="switch_reject",
        task_focus="NEW_TASK_CANDIDATE",
        candidate_patch_types=("switch_task_candidate",),
        patch_id="patch_mvp1_slice9_switch_reject",
        evidence_ref="evidence://synthetic/mvp1/slice9/switch-reject",
        resolved_arguments_ref="args://synthetic/mvp1/slice9/current",
    )
    MockSlowTaskRuntime(journal).interpret_user_patch(
        user_patch_event=switch_patch,
        event_id_prefix="evt_mvp1_slice9_switch_reject",
        created_monotonic_ms=180,
        created_wall_clock_ms=1700000009180,
        current_lifecycle_state="PLANNING",
        confirmation_id="confirmation_mvp1_slice9_switch_reject",
        prompt_ref="prompt://synthetic/mvp1/slice9/switch-reject",
    )
    confirm_patch = _append_user_patch_received(
        journal,
        caused_by_event_id="evt_mvp1_slice9_switch_reject_router",
        event_id="evt_mvp1_slice9_switch_reject_patch_received",
        patch_id="patch_mvp1_slice9_switch_reject_confirm",
        task_event_seq=10,
        evidence_ref="evidence://synthetic/mvp1/slice9/switch-reject-confirm",
        candidate_patch_types=("confirmation_candidate",),
        turn_id="turn_mvp1_slice9_switch_reject_confirm",
        utterance_id="utt_mvp1_slice9_switch_reject_confirm",
    )

    rejected = MockSlowTaskRuntime(journal).interpret_user_patch(
        user_patch_event=confirm_patch,
        event_id_prefix="evt_mvp1_slice9_switch_reject_response",
        created_monotonic_ms=190,
        created_wall_clock_ms=1700000009190,
        current_lifecycle_state="WAITING_FOR_USER_CONFIRMATION",
        pending_confirmation_id="confirmation_mvp1_slice9_switch_reject",
        pending_confirmation_scope="SWITCH_TASK",
        confirmation_signal="rejected",
        return_to_state="PLANNING",
    )

    assert [event["event_name"] for event in rejected.produced_events] == [
        "USER_PATCH_INTERPRETED",
        "USER_CONFIRMATION_RECEIVED",
        "CONFIRMATION_REJECTED",
        "SLOWTASK_STATE_CHANGED",
    ]
    assert rejected.produced_events[0]["interpretation_type"] == "confirmation"
    assert rejected.produced_events[1]["confirmation_signal"] == "rejected"
    assert rejected.produced_events[2]["rejection_reason"] == "user_rejected_switch_task"
    assert rejected.produced_events[3]["from_state"] == "WAITING_FOR_USER_CONFIRMATION"
    assert rejected.produced_events[3]["to_state"] == "PLANNING"

    slowtask_state = _reduce_slowtask_events(journal.events())
    task = slowtask_state.tasks["task_mvp1_slice9_active"]
    assert task.lifecycle_state == "PLANNING"
    assert task.terminal_outcome is None
    assert task.current_plan_version == 1
    assert task.initial_goal_ref == "goal://synthetic/mvp1/slice9/initial"
    assert task.resolved_arguments_refs == ("args://synthetic/mvp1/slice9/current",)
    assert task.cancel_request_event_id is None
    assert task.cancelled_event_id is None
    assert task.confirmation_state.status == "rejected"


def test_cancel_candidate_while_confirmation_pending_rejects_existing_confirmation() -> None:
    journal, switch_patch = _active_task_with_patch(
        suffix="pending_cancel_response",
        task_focus="NEW_TASK_CANDIDATE",
        candidate_patch_types=("switch_task_candidate",),
        patch_id="patch_mvp1_slice9_pending_switch",
        evidence_ref="evidence://synthetic/mvp1/slice9/pending-switch",
    )
    MockSlowTaskRuntime(journal).interpret_user_patch(
        user_patch_event=switch_patch,
        event_id_prefix="evt_mvp1_slice9_pending_switch",
        created_monotonic_ms=180,
        created_wall_clock_ms=1700000009180,
        current_lifecycle_state="PLANNING",
        confirmation_id="confirmation_mvp1_slice9_pending_switch",
        prompt_ref="prompt://synthetic/mvp1/slice9/pending-switch",
    )
    cancel_response_patch = _append_user_patch_received(
        journal,
        caused_by_event_id="evt_mvp1_slice9_pending_cancel_response_router",
        event_id="evt_mvp1_slice9_pending_cancel_response_patch_received",
        patch_id="patch_mvp1_slice9_pending_cancel_response",
        task_event_seq=9,
        evidence_ref="evidence://synthetic/mvp1/slice9/pending-cancel-response",
        candidate_patch_types=("cancel_candidate",),
        turn_id="turn_mvp1_slice9_pending_cancel_response",
        utterance_id="utt_mvp1_slice9_pending_cancel_response",
    )

    rejected = MockSlowTaskRuntime(journal).interpret_user_patch(
        user_patch_event=cancel_response_patch,
        event_id_prefix="evt_mvp1_slice9_pending_cancel_response",
        created_monotonic_ms=190,
        created_wall_clock_ms=1700000009190,
        current_lifecycle_state="WAITING_FOR_USER_CONFIRMATION",
        pending_confirmation_id="confirmation_mvp1_slice9_pending_switch",
        pending_confirmation_scope="SWITCH_TASK",
        return_to_state="PLANNING",
    )

    assert [event["event_name"] for event in rejected.produced_events] == [
        "USER_PATCH_INTERPRETED",
        "USER_CONFIRMATION_RECEIVED",
        "CONFIRMATION_REJECTED",
        "SLOWTASK_STATE_CHANGED",
    ]
    assert rejected.produced_events[0]["interpretation_type"] == "cancel"
    assert rejected.produced_events[1]["confirmation_id"] == "confirmation_mvp1_slice9_pending_switch"
    assert rejected.produced_events[1]["confirmation_signal"] == "rejected"
    assert rejected.produced_events[2]["rejection_reason"] == "user_rejected_switch_task"

    event_names = [event["event_name"] for event in journal.events()]
    assert event_names.count("CONFIRMATION_REQUIRED") == 1

    slowtask_state = _reduce_slowtask_events(journal.events())
    task = slowtask_state.tasks["task_mvp1_slice9_active"]
    assert task.lifecycle_state == "PLANNING"
    assert task.current_plan_version == 1
    assert task.confirmation_state.status == "rejected"
    assert task.confirmation_state.pending_confirmation_id is None


def _active_task_with_patch(
    *,
    suffix: str,
    task_focus: str,
    candidate_patch_types: tuple[str, ...],
    patch_id: str,
    evidence_ref: str,
    resolved_arguments_ref: str | None = None,
) -> tuple[Any, dict[str, Any]]:
    startup = start_mvp0_session(
        session_id=f"sess_mvp1_slice9_{suffix}",
        conversation_id=f"conv_mvp1_slice9_{suffix}",
        runtime_config_ref="config://synthetic/mvp1/default",
        created_monotonic_ms=100,
        created_wall_clock_ms=1700000009100,
    )
    journal = startup.journal

    created = journal.append(
        event_name="SLOWTASK_CREATED",
        event_id="evt_mvp1_slice9_slowtask_created",
        source_module="slowtask_runtime",
        caused_by_event_id=str(journal.events()[-1]["event_id"]),
        created_monotonic_ms=120,
        created_wall_clock_ms=1700000009120,
        trace_redaction_level="metadata_only",
        task_id="task_mvp1_slice9_active",
        plan_version=1,
        task_event_seq=1,
        initial_goal_ref="goal://synthetic/mvp1/slice9/initial",
        source_evidence_refs=["evidence://synthetic/mvp1/slice9/spawn"],
    )
    planning_started = journal.append(
        event_name="PLANNING_STARTED",
        event_id="evt_mvp1_slice9_planning_started",
        source_module="slowtask_runtime",
        caused_by_event_id=str(created["event_id"]),
        created_monotonic_ms=121,
        created_wall_clock_ms=1700000009121,
        trace_redaction_level="metadata_only",
        task_id="task_mvp1_slice9_active",
        plan_version=1,
        task_event_seq=2,
        planning_reason="initial_goal_accepted",
    )
    state_planning = journal.append(
        event_name="SLOWTASK_STATE_CHANGED",
        event_id="evt_mvp1_slice9_state_planning",
        source_module="slowtask_runtime",
        caused_by_event_id=str(planning_started["event_id"]),
        created_monotonic_ms=122,
        created_wall_clock_ms=1700000009122,
        trace_redaction_level="metadata_only",
        task_id="task_mvp1_slice9_active",
        plan_version=1,
        task_event_seq=3,
        from_state="CREATED",
        to_state="PLANNING",
        reason="initial_planning_started",
    )
    if resolved_arguments_ref is not None:
        journal.append(
            event_name="ARGUMENTS_RESOLVED",
            event_id="evt_mvp1_slice9_arguments_resolved",
            source_module="slowtask_runtime",
            caused_by_event_id=str(state_planning["event_id"]),
            created_monotonic_ms=123,
            created_wall_clock_ms=1700000009123,
            trace_redaction_level="metadata_only",
            task_id="task_mvp1_slice9_active",
            plan_version=1,
            task_event_seq=4,
            resolved_arguments_ref=resolved_arguments_ref,
            provenance_ref="provenance://synthetic/mvp1/slice9/current",
        )
        patch_task_event_seq = 5
    else:
        patch_task_event_seq = 4

    router = journal.append(
        event_name="ROUTER_DECISION_EMITTED",
        event_id=f"evt_mvp1_slice9_{suffix}_router",
        source_module="router",
        caused_by_event_id=str(state_planning["event_id"]),
        created_monotonic_ms=150,
        created_wall_clock_ms=1700000009150,
        trace_redaction_level="metadata_only",
        turn_id=f"turn_mvp1_slice9_{suffix}",
        utterance_id=f"utt_mvp1_slice9_{suffix}",
        router_decision="PATCH_ACTIVE_SLOW_TASK",
        task_focus=task_focus,
        active_task_id="task_mvp1_slice9_active",
        confidence=0.91,
        evidence_uncertainty="low",
    )
    assert router["router_decision"] == "PATCH_ACTIVE_SLOW_TASK"
    assert router["task_focus"] == task_focus
    return journal, _append_user_patch_received(
        journal,
        caused_by_event_id=str(router["event_id"]),
        event_id="evt_mvp1_slice9_user_patch_received",
        patch_id=patch_id,
        task_event_seq=patch_task_event_seq,
        evidence_ref=evidence_ref,
        candidate_patch_types=candidate_patch_types,
        turn_id=str(router["turn_id"]),
        utterance_id=str(router["utterance_id"]),
    )


def _append_user_patch_received(
    journal: Any,
    *,
    caused_by_event_id: str,
    event_id: str,
    patch_id: str,
    task_event_seq: int,
    evidence_ref: str,
    candidate_patch_types: tuple[str, ...],
    turn_id: str,
    utterance_id: str,
) -> dict[str, Any]:
    return journal.append(
        event_name="USER_PATCH_RECEIVED",
        event_id=event_id,
        source_module="user_patch_pipeline",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=160 + task_event_seq,
        created_wall_clock_ms=1700000009160 + task_event_seq,
        trace_redaction_level="redacted_fixture",
        patch_id=patch_id,
        task_id="task_mvp1_slice9_active",
        plan_version=1,
        observed_plan_version=1,
        task_event_seq=task_event_seq,
        turn_id=turn_id,
        utterance_id=utterance_id,
        evidence_ref=evidence_ref,
        authoritative_evidence_refs=[evidence_ref],
        non_authoritative_hypothesis_refs=["summary://synthetic/mvp1/slice9/control"],
        candidate_patch_types=list(candidate_patch_types),
    )


def _reduce_slowtask_events(events: list[dict[str, Any]]) -> SlowTaskState:
    slowtask_state = SlowTaskState()
    for event in events:
        slowtask_state.reduce_event(event)
    return slowtask_state


def _slowtask_created_event(
    *,
    event_id: str,
    task_id: str,
    caused_by_event_id: str = "evt_mvp1_slice9_spawn_router",
) -> dict[str, Any]:
    return {
        "event_name": "SLOWTASK_CREATED",
        "event_id": event_id,
        "task_id": task_id,
        "plan_version": 1,
        "task_event_seq": 1,
        "initial_goal_ref": "goal://synthetic/mvp1/slice9/replacement",
        "caused_by_event_id": caused_by_event_id,
    }


def _late_user_patch_received(*, task_event_seq: int) -> dict[str, Any]:
    return {
        "event_name": "USER_PATCH_RECEIVED",
        "event_id": "evt_mvp1_slice9_late_patch_received",
        "task_id": "task_mvp1_slice9_active",
        "plan_version": 1,
        "task_event_seq": task_event_seq,
        "patch_id": "patch_mvp1_slice9_late",
        "observed_plan_version": 1,
        "evidence_ref": "evidence://synthetic/mvp1/slice9/late",
    }


def _late_user_patch_interpreted(*, task_event_seq: int) -> dict[str, Any]:
    return {
        "event_name": "USER_PATCH_INTERPRETED",
        "event_id": "evt_mvp1_slice9_late_patch_interpreted",
        "task_id": "task_mvp1_slice9_active",
        "plan_version": 1,
        "task_event_seq": task_event_seq,
        "patch_id": "patch_mvp1_slice9_late",
        "observed_plan_version": 1,
        "interpreted_against_plan_version": 1,
        "interpretation_type": "confirmation",
        "materially_changes_task": False,
    }


def _late_user_confirmation_received(*, task_event_seq: int) -> dict[str, Any]:
    return {
        "event_name": "USER_CONFIRMATION_RECEIVED",
        "event_id": "evt_mvp1_slice9_late_user_confirmation",
        "task_id": "task_mvp1_slice9_active",
        "plan_version": 1,
        "task_event_seq": task_event_seq,
        "confirmation_id": "confirmation_mvp1_slice9_cancel",
        "patch_id": "patch_mvp1_slice9_late",
        "confirmation_signal": "accepted",
    }
