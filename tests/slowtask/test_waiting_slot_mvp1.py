from __future__ import annotations

from voice_agent.slowtask.mock_runtime import MockSlowTaskRuntime

from tests.slowtask.test_evidence_review_mvp1 import (
    FORBIDDEN_UNRESOLVED_EVENTS,
    _active_planning_journal,
    _event_names,
    _reduce,
)


def test_missing_critical_slot_requests_clarification_and_waits_for_slot() -> None:
    journal, cause = _active_planning_journal("task_mvp1_slice7_waiting")

    result = MockSlowTaskRuntime(journal).review_evidence(
        task_id="task_mvp1_slice7_waiting",
        plan_version=1,
        caused_by_event_id=cause["event_id"],
        event_id_prefix="evt_mvp1_slice7_waiting",
        created_monotonic_ms=160,
        created_wall_clock_ms=1700000007160,
        start_task_event_seq=4,
        evidence_refs=(
            "asr://synthetic/mvp1/slice7/waiting",
            "thinker://synthetic/mvp1/slice7/waiting",
            "router://synthetic/mvp1/slice7/waiting",
        ),
        required_fields=("destination", "date"),
        missing_fields=("date",),
        clarification_prompt_ref="prompt://synthetic/mvp1/slice7/missing-date",
    )

    assert [event["event_name"] for event in result.produced_events] == [
        "EVIDENCE_REVIEWED",
        "INSUFFICIENT_EVIDENCE_FOR_ACTION",
        "CLARIFICATION_REQUESTED",
        "WAITING_FOR_SLOT",
        "SLOWTASK_STATE_CHANGED",
    ]
    reviewed, insufficient, clarification, waiting, state_changed = result.produced_events
    assert reviewed["review_result"] == "insufficient"
    assert insufficient["caused_by_event_id"] == reviewed["event_id"]
    assert insufficient["blocking_fields"] == ["date"]
    assert insufficient["source_evidence_refs"] == list(reviewed["evidence_refs"])
    assert clarification["caused_by_event_id"] == insufficient["event_id"]
    assert clarification["missing_or_ambiguous_fields"] == ["date"]
    assert clarification["clarification_prompt_ref"] == "prompt://synthetic/mvp1/slice7/missing-date"
    assert waiting["caused_by_event_id"] == clarification["event_id"]
    assert waiting["missing_fields"] == ["date"]
    assert state_changed["caused_by_event_id"] == waiting["event_id"]
    assert state_changed["from_state"] == "PLANNING"
    assert state_changed["to_state"] == "WAITING_FOR_SLOT"
    assert state_changed["reason"] == "missing_critical_slot"
    assert _event_names(result.produced_events).isdisjoint(FORBIDDEN_UNRESOLVED_EVENTS)

    task = _reduce(journal.events()).tasks["task_mvp1_slice7_waiting"]
    assert task.lifecycle_state == "WAITING_FOR_SLOT"
    assert task.current_plan_version == 1
    assert task.current_task_event_seq == 8
    assert task.resolved_arguments_refs == ()
    assert task.argument_provenance_refs == ()
    assert task.progress_events[-1].event_name == "WAITING_FOR_SLOT"
    assert task.progress_events[-1].refs == ("date",)


def test_missing_critical_slot_rejects_empty_prompt_ref_before_appending() -> None:
    journal, cause = _active_planning_journal("task_mvp1_slice7_waiting_empty_prompt")
    event_count_before = len(journal.events())

    try:
        MockSlowTaskRuntime(journal).review_evidence(
            task_id="task_mvp1_slice7_waiting_empty_prompt",
            plan_version=1,
            caused_by_event_id=cause["event_id"],
            event_id_prefix="evt_mvp1_slice7_waiting_empty_prompt",
            created_monotonic_ms=160,
            created_wall_clock_ms=1700000007160,
            start_task_event_seq=4,
            evidence_refs=("asr://synthetic/mvp1/slice7/waiting-empty-prompt",),
            required_fields=("date",),
            missing_fields=("date",),
            clarification_prompt_ref="",
        )
    except ValueError as exc:
        assert "clarification_prompt_ref" in str(exc)
    else:
        raise AssertionError("empty clarification_prompt_ref should be rejected")

    assert journal.events()[event_count_before:] == []
