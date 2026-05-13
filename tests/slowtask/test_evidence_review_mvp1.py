from __future__ import annotations

from typing import Any

import pytest

from voice_agent.runtime.session import start_mvp0_session
from voice_agent.slowtask.mock_runtime import MockSlowTaskRuntime
from voice_agent.state.slowtask_state import SlowTaskState


FORBIDDEN_UNRESOLVED_EVENTS = {
    "TOOL_CALL_STARTED",
    "TOOL_RESULT_RECEIVED",
    "FINALIZING",
    "SEMANTIC_COMMITMENT_EMITTED",
}


def test_sufficient_evidence_resolves_arguments_with_provenance_refs() -> None:
    journal, cause = _active_planning_journal("task_mvp1_slice7_sufficient")

    result = MockSlowTaskRuntime(journal).review_evidence(
        task_id="task_mvp1_slice7_sufficient",
        plan_version=1,
        caused_by_event_id=cause["event_id"],
        event_id_prefix="evt_mvp1_slice7_sufficient",
        created_monotonic_ms=160,
        created_wall_clock_ms=1700000007160,
        start_task_event_seq=4,
        evidence_refs=(
            "asr://synthetic/mvp1/slice7/sufficient",
            "thinker://synthetic/mvp1/slice7/sufficient",
            "router://synthetic/mvp1/slice7/sufficient",
            "userpatch://synthetic/mvp1/slice7/sufficient",
        ),
        required_fields=("destination", "date"),
        resolved_fields=("destination", "date"),
        resolved_arguments_ref="args://synthetic/mvp1/slice7/sufficient",
        provenance_ref="provenance://synthetic/mvp1/slice7/sufficient",
        field_provenance_refs=(
            "provenance://synthetic/mvp1/slice7/field/destination",
            "provenance://synthetic/mvp1/slice7/field/date",
        ),
    )

    assert [event["event_name"] for event in result.produced_events] == [
        "EVIDENCE_REVIEWED",
        "ARGUMENTS_RESOLVED",
        "ARGUMENT_RESOLUTION_PROVENANCE",
    ]
    assert {event["source_module"] for event in result.produced_events} == {"slowtask_runtime"}

    reviewed, arguments, provenance = result.produced_events
    assert reviewed["review_result"] == "sufficient"
    assert reviewed["evidence_refs"] == [
        "asr://synthetic/mvp1/slice7/sufficient",
        "thinker://synthetic/mvp1/slice7/sufficient",
        "router://synthetic/mvp1/slice7/sufficient",
        "userpatch://synthetic/mvp1/slice7/sufficient",
    ]
    assert arguments["caused_by_event_id"] == reviewed["event_id"]
    assert arguments["resolved_arguments_ref"] == "args://synthetic/mvp1/slice7/sufficient"
    assert arguments["provenance_ref"] == "provenance://synthetic/mvp1/slice7/sufficient"
    assert provenance["caused_by_event_id"] == arguments["event_id"]
    assert provenance["field_provenance_refs"] == [
        "provenance://synthetic/mvp1/slice7/field/destination",
        "provenance://synthetic/mvp1/slice7/field/date",
    ]
    assert _event_names(result.produced_events).isdisjoint(FORBIDDEN_UNRESOLVED_EVENTS)

    task = _reduce(journal.events()).tasks["task_mvp1_slice7_sufficient"]
    assert task.lifecycle_state == "PLANNING"
    assert task.resolved_arguments_refs == ("args://synthetic/mvp1/slice7/sufficient",)
    assert task.argument_provenance_refs == (
        "provenance://synthetic/mvp1/slice7/sufficient",
        "provenance://synthetic/mvp1/slice7/field/destination",
        "provenance://synthetic/mvp1/slice7/field/date",
    )


def test_context_resolvable_ambiguity_records_resolution_then_arguments() -> None:
    journal, cause = _active_planning_journal("task_mvp1_slice7_context")

    result = MockSlowTaskRuntime(journal).review_evidence(
        task_id="task_mvp1_slice7_context",
        plan_version=1,
        caused_by_event_id=cause["event_id"],
        event_id_prefix="evt_mvp1_slice7_context",
        created_monotonic_ms=160,
        created_wall_clock_ms=1700000007160,
        start_task_event_seq=4,
        evidence_refs=(
            "asr://synthetic/mvp1/slice7/context-downtown",
            "thinker://synthetic/mvp1/slice7/context-airport",
            "router://synthetic/mvp1/slice7/context",
        ),
        required_fields=("destination",),
        resolved_fields=("destination",),
        ambiguous_fields=("destination",),
        context_resolved_fields=("destination",),
        resolution_reason="mock_context_prefers_recent_user_patch",
        resolved_arguments_ref="args://synthetic/mvp1/slice7/context",
        provenance_ref="provenance://synthetic/mvp1/slice7/context",
        field_provenance_refs=("provenance://synthetic/mvp1/slice7/field/destination",),
    )

    assert [event["event_name"] for event in result.produced_events] == [
        "EVIDENCE_REVIEWED",
        "AMBIGUITY_DETECTED",
        "AMBIGUITY_RESOLVED",
        "ARGUMENTS_RESOLVED",
        "ARGUMENT_RESOLUTION_PROVENANCE",
    ]
    reviewed, detected, resolved, arguments, provenance = result.produced_events
    assert reviewed["review_result"] == "context_resolvable_ambiguity"
    assert detected["ambiguous_fields"] == ["destination"]
    assert detected["source_evidence_refs"] == list(reviewed["evidence_refs"])
    assert detected["caused_by_event_id"] == reviewed["event_id"]
    assert resolved["resolved_fields"] == ["destination"]
    assert resolved["resolution_reason"] == "mock_context_prefers_recent_user_patch"
    assert resolved["source_evidence_refs"] == list(reviewed["evidence_refs"])
    assert resolved["caused_by_event_id"] == detected["event_id"]
    assert arguments["caused_by_event_id"] == resolved["event_id"]
    assert provenance["caused_by_event_id"] == arguments["event_id"]
    assert _event_names(result.produced_events).isdisjoint(FORBIDDEN_UNRESOLVED_EVENTS)

    task = _reduce(journal.events()).tasks["task_mvp1_slice7_context"]
    assert task.resolved_arguments_refs == ("args://synthetic/mvp1/slice7/context",)
    assert task.argument_provenance_refs == (
        "provenance://synthetic/mvp1/slice7/context",
        "provenance://synthetic/mvp1/slice7/field/destination",
    )
    assert [event.event_name for event in task.evidence_events[-5:]] == [
        "EVIDENCE_REVIEWED",
        "AMBIGUITY_DETECTED",
        "AMBIGUITY_RESOLVED",
        "ARGUMENTS_RESOLVED",
        "ARGUMENT_RESOLUTION_PROVENANCE",
    ]


def test_obvious_unresolved_ambiguity_does_not_resolve_arguments_or_commit() -> None:
    journal, cause = _active_planning_journal("task_mvp1_slice7_ambiguous")

    result = MockSlowTaskRuntime(journal).review_evidence(
        task_id="task_mvp1_slice7_ambiguous",
        plan_version=1,
        caused_by_event_id=cause["event_id"],
        event_id_prefix="evt_mvp1_slice7_ambiguous",
        created_monotonic_ms=160,
        created_wall_clock_ms=1700000007160,
        start_task_event_seq=4,
        evidence_refs=(
            "asr://synthetic/mvp1/slice7/ambiguous/date-a",
            "thinker://synthetic/mvp1/slice7/ambiguous/date-b",
        ),
        required_fields=("date",),
        ambiguous_fields=("date",),
        clarification_prompt_ref="prompt://synthetic/mvp1/slice7/ambiguous-date",
    )

    assert [event["event_name"] for event in result.produced_events] == [
        "EVIDENCE_REVIEWED",
        "AMBIGUITY_DETECTED",
        "INSUFFICIENT_EVIDENCE_FOR_ACTION",
        "CLARIFICATION_REQUESTED",
        "WAITING_FOR_SLOT",
        "SLOWTASK_STATE_CHANGED",
    ]
    reviewed, detected, insufficient, clarification, waiting, state_changed = result.produced_events
    assert reviewed["review_result"] == "ambiguous"
    assert detected["ambiguous_fields"] == ["date"]
    assert detected["source_evidence_refs"] == list(reviewed["evidence_refs"])
    assert insufficient["caused_by_event_id"] == detected["event_id"]
    assert insufficient["blocking_fields"] == ["date"]
    assert insufficient["source_evidence_refs"] == list(reviewed["evidence_refs"])
    assert clarification["caused_by_event_id"] == insufficient["event_id"]
    assert clarification["missing_or_ambiguous_fields"] == ["date"]
    assert clarification["clarification_prompt_ref"] == "prompt://synthetic/mvp1/slice7/ambiguous-date"
    assert waiting["caused_by_event_id"] == clarification["event_id"]
    assert waiting["missing_fields"] == ["date"]
    assert state_changed["caused_by_event_id"] == waiting["event_id"]
    assert state_changed["from_state"] == "PLANNING"
    assert state_changed["to_state"] == "WAITING_FOR_SLOT"
    assert _event_names(result.produced_events).isdisjoint(FORBIDDEN_UNRESOLVED_EVENTS)

    task = _reduce(journal.events()).tasks["task_mvp1_slice7_ambiguous"]
    assert task.lifecycle_state == "WAITING_FOR_SLOT"
    assert task.resolved_arguments_refs == ()
    assert task.argument_provenance_refs == ()
    assert [event.event_name for event in task.evidence_events[-4:]] == [
        "EVIDENCE_REVIEWED",
        "AMBIGUITY_DETECTED",
        "INSUFFICIENT_EVIDENCE_FOR_ACTION",
        "CLARIFICATION_REQUESTED",
    ]
    assert task.progress_events[-1].event_name == "WAITING_FOR_SLOT"


@pytest.mark.parametrize(
    "overrides,error",
    [
        ({"resolved_fields": ("destination",)}, "resolved_fields"),
        ({"resolved_arguments_ref": None}, "resolved_arguments_ref"),
        ({"resolved_arguments_ref": ""}, "resolved_arguments_ref"),
        ({"provenance_ref": None}, "provenance_ref"),
        ({"provenance_ref": ""}, "provenance_ref"),
    ],
)
def test_sufficient_review_validation_failure_does_not_append_partial_events(
    overrides: dict[str, object],
    error: str,
) -> None:
    journal, cause = _active_planning_journal("task_mvp1_slice7_validation")
    event_count_before = len(journal.events())
    kwargs: dict[str, object] = {
        "task_id": "task_mvp1_slice7_validation",
        "plan_version": 1,
        "caused_by_event_id": cause["event_id"],
        "event_id_prefix": "evt_mvp1_slice7_validation",
        "created_monotonic_ms": 160,
        "created_wall_clock_ms": 1700000007160,
        "start_task_event_seq": 4,
        "evidence_refs": ("asr://synthetic/mvp1/slice7/validation",),
        "required_fields": ("destination", "date"),
        "resolved_fields": ("destination", "date"),
        "resolved_arguments_ref": "args://synthetic/mvp1/slice7/validation",
        "provenance_ref": "provenance://synthetic/mvp1/slice7/validation",
        "field_provenance_refs": ("provenance://synthetic/mvp1/slice7/field/destination",),
    }
    kwargs.update(overrides)

    with pytest.raises(ValueError, match=error):
        MockSlowTaskRuntime(journal).review_evidence(**kwargs)

    assert journal.events()[event_count_before:] == []


def test_partially_context_resolved_ambiguity_is_recorded_as_unresolved_ambiguous() -> None:
    journal, cause = _active_planning_journal("task_mvp1_slice7_partial_ambiguity")

    result = MockSlowTaskRuntime(journal).review_evidence(
        task_id="task_mvp1_slice7_partial_ambiguity",
        plan_version=1,
        caused_by_event_id=cause["event_id"],
        event_id_prefix="evt_mvp1_slice7_partial_ambiguity",
        created_monotonic_ms=160,
        created_wall_clock_ms=1700000007160,
        start_task_event_seq=4,
        evidence_refs=(
            "asr://synthetic/mvp1/slice7/partial-ambiguity",
            "thinker://synthetic/mvp1/slice7/partial-ambiguity",
        ),
        required_fields=("destination", "date"),
        ambiguous_fields=("destination", "date"),
        context_resolved_fields=("destination",),
        clarification_prompt_ref="prompt://synthetic/mvp1/slice7/partial-ambiguity",
    )

    assert [event["event_name"] for event in result.produced_events] == [
        "EVIDENCE_REVIEWED",
        "AMBIGUITY_DETECTED",
        "INSUFFICIENT_EVIDENCE_FOR_ACTION",
        "CLARIFICATION_REQUESTED",
        "WAITING_FOR_SLOT",
        "SLOWTASK_STATE_CHANGED",
    ]
    assert result.produced_events[0]["review_result"] == "ambiguous"
    assert _event_names(result.produced_events).isdisjoint(
        {"AMBIGUITY_RESOLVED", "ARGUMENTS_RESOLVED", "ARGUMENT_RESOLUTION_PROVENANCE"}
    )
    assert result.produced_events[2]["blocking_fields"] == ["destination", "date"]
    assert result.produced_events[3]["missing_or_ambiguous_fields"] == ["destination", "date"]


def test_unresolved_ambiguity_requires_prompt_ref_before_appending() -> None:
    journal, cause = _active_planning_journal("task_mvp1_slice7_ambiguity_prompt")
    event_count_before = len(journal.events())

    with pytest.raises(ValueError, match="clarification_prompt_ref"):
        MockSlowTaskRuntime(journal).review_evidence(
            task_id="task_mvp1_slice7_ambiguity_prompt",
            plan_version=1,
            caused_by_event_id=cause["event_id"],
            event_id_prefix="evt_mvp1_slice7_ambiguity_prompt",
            created_monotonic_ms=160,
            created_wall_clock_ms=1700000007160,
            start_task_event_seq=4,
            evidence_refs=("asr://synthetic/mvp1/slice7/ambiguity-prompt",),
            required_fields=("date",),
            ambiguous_fields=("date",),
            clarification_prompt_ref="",
        )

    assert journal.events()[event_count_before:] == []


def _active_planning_journal(task_id: str) -> tuple[Any, dict[str, Any]]:
    startup = start_mvp0_session(
        session_id=f"sess_{task_id}",
        conversation_id=f"conv_{task_id}",
        runtime_config_ref="config://synthetic/mvp1/default",
        created_monotonic_ms=100,
        created_wall_clock_ms=1700000007100,
    )
    journal = startup.journal
    created = journal.append(
        event_name="SLOWTASK_CREATED",
        event_id=f"evt_{task_id}_created",
        source_module="slowtask_runtime",
        caused_by_event_id=str(journal.events()[-1]["event_id"]),
        created_monotonic_ms=120,
        created_wall_clock_ms=1700000007120,
        trace_redaction_level="metadata_only",
        task_id=task_id,
        plan_version=1,
        task_event_seq=1,
        initial_goal_ref=f"goal://synthetic/mvp1/slice7/{task_id}",
        source_evidence_refs=[f"evidence://synthetic/mvp1/slice7/{task_id}/spawn"],
    )
    planning_started = journal.append(
        event_name="PLANNING_STARTED",
        event_id=f"evt_{task_id}_planning_started",
        source_module="slowtask_runtime",
        caused_by_event_id=str(created["event_id"]),
        created_monotonic_ms=122,
        created_wall_clock_ms=1700000007122,
        trace_redaction_level="metadata_only",
        task_id=task_id,
        plan_version=1,
        task_event_seq=2,
        planning_reason="initial_goal_accepted",
    )
    state_planning = journal.append(
        event_name="SLOWTASK_STATE_CHANGED",
        event_id=f"evt_{task_id}_state_planning",
        source_module="slowtask_runtime",
        caused_by_event_id=str(planning_started["event_id"]),
        created_monotonic_ms=123,
        created_wall_clock_ms=1700000007123,
        trace_redaction_level="metadata_only",
        task_id=task_id,
        plan_version=1,
        task_event_seq=3,
        from_state="CREATED",
        to_state="PLANNING",
        reason="initial_planning_started",
    )
    return journal, state_planning


def _reduce(events: list[dict[str, Any]]) -> SlowTaskState:
    state = SlowTaskState()
    for event in events:
        state.reduce_event(event)
    return state


def _event_names(events: tuple[dict[str, Any], ...]) -> set[str]:
    return {str(event["event_name"]) for event in events}
