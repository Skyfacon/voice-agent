from __future__ import annotations

from copy import deepcopy

import pytest

from conftest import MVP1_REPLAY_FIXTURE_DIR, load_json_fixture
from voice_agent.replay.runner import ReplayValidationError, run_replay_fixture


NO_ADOPTION_FIXTURE = MVP1_REPLAY_FIXTURE_DIR / "008-stale-result-no-adoption.fixture.json"
ADOPTED_FIXTURE = MVP1_REPLAY_FIXTURE_DIR / "008-stale-result-adopted.fixture.json"
FORBIDDEN_NO_ADOPTION_EVENTS = {
    "STALE_EVIDENCE_ADOPTED",
    "ARGUMENTS_RESOLVED",
    "FINALIZING",
    "SEMANTIC_COMMITMENT_EMITTED",
    "TOOL_EXECUTION_STARTED",
    "TOOL_PROGRESS_UPDATED",
    "TOOL_UI_STATE_PATCHED",
}


def test_slice8_no_adoption_fixture_replays_stale_evidence_without_advancement() -> None:
    result = run_replay_fixture(load_json_fixture(NO_ADOPTION_FIXTURE))

    event_names = [event["event_name"] for event in result.ordered_events]
    assert event_names[-3:] == [
        "TOOL_RESULT_RECEIVED",
        "TOOL_RESULT_MARKED_STALE",
        "STALE_EVIDENCE_RECORDED",
    ]
    assert set(event_names).isdisjoint(FORBIDDEN_NO_ADOPTION_EVENTS)

    late_result = result.ordered_events[-3]
    marked = result.ordered_events[-2]
    recorded = result.ordered_events[-1]
    assert late_result["plan_version"] == 1
    assert late_result["task_event_seq"] == 11
    assert marked["caused_by_event_id"] == late_result["event_id"]
    assert marked["plan_version"] == 2
    assert marked["result_plan_version"] == 1
    assert marked["current_plan_version"] == 2
    assert marked["task_event_seq"] == 12
    assert recorded["caused_by_event_id"] == marked["event_id"]
    assert recorded["source_tool_result_event_id"] == late_result["event_id"]
    assert recorded["task_event_seq"] == 13

    task = result.slowtask_state.tasks["task_mvp1_slice8_no_adoption"]
    assert task.current_plan_version == 2
    assert task.lifecycle_state == "PLANNING"
    assert task.stale_evidence_refs == (
        "stale-evidence://synthetic/mvp1/slice8/no-adoption/old-tool-result",
    )
    assert task.adopted_evidence == ()
    assert task.resolved_arguments_refs == ()
    assert task.semantic_commitments == ()
    assert result.result_status == "passed"


def test_slice8_adopted_fixture_replays_adopted_evidence_and_commitment_metadata() -> None:
    result = run_replay_fixture(load_json_fixture(ADOPTED_FIXTURE))

    adoption = next(event for event in result.ordered_events if event["event_name"] == "STALE_EVIDENCE_ADOPTED")
    reviewed = next(event for event in result.ordered_events if event["event_name"] == "EVIDENCE_REVIEWED")
    arguments = next(event for event in result.ordered_events if event["event_name"] == "ARGUMENTS_RESOLVED")
    commitment = next(
        event for event in result.ordered_events if event["event_name"] == "SEMANTIC_COMMITMENT_EMITTED"
    )

    assert adoption["plan_version"] == 2
    assert adoption["adopted_from_plan_version"] == 1
    assert adoption["adoption_mode"] == "adopt_or_rebase"
    assert adoption["adopted_scope"] == ["destination", "availability_status"]
    assert reviewed["caused_by_event_id"] == adoption["event_id"]
    assert reviewed["evidence_refs"] == [adoption["stale_evidence_ref"]]
    assert arguments["plan_version"] == 2
    assert commitment["plan_version"] == 2
    assert adoption["event_id"] in commitment["source_events"]

    task = result.slowtask_state.tasks["task_mvp1_slice8_adopted"]
    assert task.current_plan_version == 2
    assert task.lifecycle_state == "COMPLETED"
    assert task.stale_evidence_refs == (
        "stale-evidence://synthetic/mvp1/slice8/adopted/old-tool-result",
    )
    assert task.adopted_evidence[-1].source_tool_result_event_id == adoption["source_tool_result_event_id"]
    assert task.adopted_evidence[-1].adopted_scope == ("destination", "availability_status")
    assert task.resolved_arguments_refs == ("args://synthetic/mvp1/slice8/adopted",)
    assert task.semantic_commitments[-1].commitment_id == "commitment_mvp1_slice8_adopted"
    assert adoption["event_id"] in task.semantic_commitments[-1].source_events
    assert result.result_status == "passed"


def test_replay_rejects_current_plan_review_of_stale_evidence_without_adoption() -> None:
    fixture = load_json_fixture(NO_ADOPTION_FIXTURE)
    events = list(fixture["events"])
    recorded = events[-1]
    events.append(
        {
            "event_name": "EVIDENCE_REVIEWED",
            "event_id": "evt_mvp1_slice8_no_adoption_illegal_review",
            "event_seq": recorded["event_seq"] + 1,
            "event_schema_version": "1.0",
            "session_id": recorded["session_id"],
            "conversation_id": recorded["conversation_id"],
            "source_module": "slowtask_runtime",
            "created_monotonic_ms": recorded["created_monotonic_ms"] + 1,
            "created_wall_clock_ms": recorded["created_wall_clock_ms"] + 1,
            "caused_by_event_id": recorded["event_id"],
            "trace_redaction_level": "metadata_only",
            "task_id": recorded["task_id"],
            "plan_version": recorded["plan_version"],
            "task_event_seq": recorded["task_event_seq"] + 1,
            "evidence_refs": [recorded["stale_evidence_ref"]],
            "review_result": "illegal_unadopted_stale_evidence",
        }
    )
    fixture["events"] = events

    with pytest.raises(ReplayValidationError, match="STALE_EVIDENCE_ADOPTED"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_current_plan_review_of_raw_old_tool_result_ref_without_adoption() -> None:
    fixture = load_json_fixture(NO_ADOPTION_FIXTURE)
    events = list(fixture["events"])
    late_result = next(event for event in events if event["event_name"] == "TOOL_RESULT_RECEIVED")
    recorded = events[-1]
    events.append(
        {
            "event_name": "EVIDENCE_REVIEWED",
            "event_id": "evt_mvp1_slice8_no_adoption_illegal_raw_result_review",
            "event_seq": recorded["event_seq"] + 1,
            "event_schema_version": "1.0",
            "session_id": recorded["session_id"],
            "conversation_id": recorded["conversation_id"],
            "source_module": "slowtask_runtime",
            "created_monotonic_ms": recorded["created_monotonic_ms"] + 1,
            "created_wall_clock_ms": recorded["created_wall_clock_ms"] + 1,
            "caused_by_event_id": recorded["event_id"],
            "trace_redaction_level": "metadata_only",
            "task_id": recorded["task_id"],
            "plan_version": recorded["plan_version"],
            "task_event_seq": recorded["task_event_seq"] + 1,
            "evidence_refs": [late_result["result_ref"]],
            "review_result": "illegal_raw_old_tool_result_ref",
        }
    )
    fixture["events"] = events

    with pytest.raises(ReplayValidationError, match="STALE_EVIDENCE_ADOPTED"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_result_ref_that_was_current_when_received_but_old_after_plan_advance() -> None:
    fixture, result_received, state_replanned = _current_then_old_result_fixture()
    fixture["events"].append(
        {
            "event_name": "EVIDENCE_REVIEWED",
            "event_id": "evt_mvp1_slice8_current_then_old_illegal_review",
            "event_seq": 14,
            "event_schema_version": "1.0",
            "session_id": state_replanned["session_id"],
            "conversation_id": state_replanned["conversation_id"],
            "source_module": "slowtask_runtime",
            "created_monotonic_ms": 46,
            "created_wall_clock_ms": 1700000008046,
            "caused_by_event_id": state_replanned["event_id"],
            "trace_redaction_level": "metadata_only",
            "task_id": state_replanned["task_id"],
            "plan_version": 2,
            "task_event_seq": 12,
            "evidence_refs": [result_received["result_ref"]],
            "review_result": "illegal_current_then_old_tool_result_ref",
        }
    )

    with pytest.raises(ReplayValidationError, match="STALE_EVIDENCE_ADOPTED"):
        run_replay_fixture(deepcopy(fixture))


@pytest.mark.parametrize(
    "event_name,extra_fields",
    [
        (
            "ARGUMENTS_RESOLVED",
            {
                "resolved_arguments_ref": "args://synthetic/mvp1/slice8/illegal-stale-bypass",
                "provenance_ref": "provenance://synthetic/mvp1/slice8/illegal-stale-bypass",
            },
        ),
        (
            "FINALIZING",
            {
                "source_events": ["evt_mvp1_slice8_no_adoption_stale_evidence_recorded"],
            },
        ),
        (
            "SEMANTIC_COMMITMENT_EMITTED",
            {
                "commitment_id": "commitment_mvp1_slice8_illegal_stale_bypass",
                "source_events": ["evt_mvp1_slice8_no_adoption_stale_evidence_recorded"],
            },
        ),
    ],
)
def test_replay_rejects_downstream_stale_advancement_without_review_or_adoption(
    event_name: str,
    extra_fields: dict[str, object],
) -> None:
    fixture = load_json_fixture(NO_ADOPTION_FIXTURE)
    recorded = fixture["events"][-1]
    fixture["events"].append(
        {
            "event_name": event_name,
            "event_id": f"evt_mvp1_slice8_no_adoption_illegal_{event_name.lower()}",
            "event_seq": recorded["event_seq"] + 1,
            "event_schema_version": "1.0",
            "session_id": recorded["session_id"],
            "conversation_id": recorded["conversation_id"],
            "source_module": "slowtask_runtime",
            "created_monotonic_ms": recorded["created_monotonic_ms"] + 1,
            "created_wall_clock_ms": recorded["created_wall_clock_ms"] + 1,
            "caused_by_event_id": recorded["event_id"],
            "trace_redaction_level": "metadata_only",
            "task_id": recorded["task_id"],
            "plan_version": recorded["plan_version"],
            "task_event_seq": recorded["task_event_seq"] + 1,
            **extra_fields,
        }
    )

    with pytest.raises(ReplayValidationError, match="STALE_EVIDENCE_ADOPTED"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_allows_current_then_old_result_to_be_marked_recorded_and_adopted() -> None:
    fixture, result_received, state_replanned = _current_then_old_result_fixture()
    marked = {
        "event_name": "TOOL_RESULT_MARKED_STALE",
        "event_id": "evt_mvp1_slice8_current_then_old_marked_stale",
        "event_seq": 14,
        "event_schema_version": "1.0",
        "session_id": state_replanned["session_id"],
        "conversation_id": state_replanned["conversation_id"],
        "source_module": "slowtask_runtime",
        "created_monotonic_ms": 46,
        "created_wall_clock_ms": 1700000008046,
        "caused_by_event_id": state_replanned["event_id"],
        "trace_redaction_level": "metadata_only",
        "tool_call_id": result_received["tool_call_id"],
        "task_id": state_replanned["task_id"],
        "plan_version": 2,
        "task_event_seq": 12,
        "result_plan_version": 1,
        "current_plan_version": 2,
        "stale_reason": "result_became_old_after_plan_advance",
    }
    recorded = {
        "event_name": "STALE_EVIDENCE_RECORDED",
        "event_id": "evt_mvp1_slice8_current_then_old_stale_evidence_recorded",
        "event_seq": 15,
        "event_schema_version": "1.0",
        "session_id": state_replanned["session_id"],
        "conversation_id": state_replanned["conversation_id"],
        "source_module": "slowtask_runtime",
        "created_monotonic_ms": 47,
        "created_wall_clock_ms": 1700000008047,
        "caused_by_event_id": marked["event_id"],
        "trace_redaction_level": "metadata_only",
        "task_id": state_replanned["task_id"],
        "plan_version": 2,
        "task_event_seq": 13,
        "stale_evidence_ref": "stale-evidence://synthetic/mvp1/slice8/current-then-old/result",
        "source_tool_result_event_id": result_received["event_id"],
    }
    adopted = {
        "event_name": "STALE_EVIDENCE_ADOPTED",
        "event_id": "evt_mvp1_slice8_current_then_old_stale_evidence_adopted",
        "event_seq": 16,
        "event_schema_version": "1.0",
        "session_id": state_replanned["session_id"],
        "conversation_id": state_replanned["conversation_id"],
        "source_module": "slowtask_runtime",
        "created_monotonic_ms": 48,
        "created_wall_clock_ms": 1700000008048,
        "caused_by_event_id": recorded["event_id"],
        "trace_redaction_level": "metadata_only",
        "task_id": state_replanned["task_id"],
        "plan_version": 2,
        "task_event_seq": 14,
        "stale_evidence_ref": recorded["stale_evidence_ref"],
        "source_tool_result_event_id": result_received["event_id"],
        "adopted_from_plan_version": 1,
        "adoption_mode": "adopt_or_rebase",
        "adoption_reason": "mock_current_then_old_result_reuse",
        "adopted_scope": ["availability_status"],
        "adopted_by_event_id": recorded["event_id"],
    }
    reviewed = {
        "event_name": "EVIDENCE_REVIEWED",
        "event_id": "evt_mvp1_slice8_current_then_old_reviewed",
        "event_seq": 17,
        "event_schema_version": "1.0",
        "session_id": state_replanned["session_id"],
        "conversation_id": state_replanned["conversation_id"],
        "source_module": "slowtask_runtime",
        "created_monotonic_ms": 49,
        "created_wall_clock_ms": 1700000008049,
        "caused_by_event_id": adopted["event_id"],
        "trace_redaction_level": "metadata_only",
        "task_id": state_replanned["task_id"],
        "plan_version": 2,
        "task_event_seq": 15,
        "evidence_refs": [result_received["result_ref"]],
        "review_result": "adopted_current_then_old_result_sufficient",
    }
    fixture["events"].extend([marked, recorded, adopted, reviewed])

    result = run_replay_fixture(deepcopy(fixture))

    task = result.slowtask_state.tasks["task_mvp1_slice8_no_adoption"]
    assert task.stale_evidence_refs == (recorded["stale_evidence_ref"],)
    assert task.adopted_evidence[-1].source_tool_result_event_id == result_received["event_id"]
    assert task.evidence_events[-1].refs == (result_received["result_ref"],)


def test_replay_allows_raw_old_tool_result_ref_after_matching_adoption() -> None:
    fixture = load_json_fixture(ADOPTED_FIXTURE)
    late_result = next(event for event in fixture["events"] if event["event_name"] == "TOOL_RESULT_RECEIVED")
    reviewed = next(event for event in fixture["events"] if event["event_name"] == "EVIDENCE_REVIEWED")
    reviewed["evidence_refs"] = [late_result["result_ref"]]

    result = run_replay_fixture(deepcopy(fixture))

    task = result.slowtask_state.tasks["task_mvp1_slice8_adopted"]
    assert task.lifecycle_state == "COMPLETED"
    assert task.adopted_evidence[-1].source_tool_result_event_id == late_result["event_id"]
    reviewed_state = next(event for event in task.evidence_events if event.event_name == "EVIDENCE_REVIEWED")
    assert reviewed_state.refs == (late_result["result_ref"],)


def _current_then_old_result_fixture() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    fixture = load_json_fixture(NO_ADOPTION_FIXTURE)
    events_by_name = {event["event_name"]: event for event in fixture["events"]}
    base_events = fixture["events"][:6]

    result_received = dict(events_by_name["TOOL_RESULT_RECEIVED"])
    result_received.update(
        {
            "event_id": "evt_mvp1_slice8_current_then_old_tool_result_received",
            "event_seq": 7,
            "caused_by_event_id": "evt_mvp1_slice8_no_adoption_tool_call_started",
            "created_monotonic_ms": 31,
            "created_wall_clock_ms": 1700000008031,
            "plan_version": 1,
            "task_event_seq": 5,
            "result_ref": "tool-result://synthetic/mvp1/slice8/current-then-old/result",
        }
    )

    patch_received = dict(events_by_name["USER_PATCH_RECEIVED"])
    patch_received.update(
        {
            "event_seq": 8,
            "caused_by_event_id": result_received["event_id"],
            "created_monotonic_ms": 40,
            "created_wall_clock_ms": 1700000008040,
            "task_event_seq": 6,
        }
    )
    patch_interpreted = dict(events_by_name["USER_PATCH_INTERPRETED"])
    patch_interpreted.update(
        {
            "event_seq": 9,
            "created_monotonic_ms": 41,
            "created_wall_clock_ms": 1700000008041,
            "task_event_seq": 7,
        }
    )
    advanced = dict(events_by_name["PLAN_VERSION_ADVANCED"])
    advanced.update(
        {
            "event_seq": 10,
            "created_monotonic_ms": 42,
            "created_wall_clock_ms": 1700000008042,
            "task_event_seq": 8,
        }
    )
    restarted = dict(events_by_name["PLANNING_RESTARTED"])
    restarted.update(
        {
            "event_seq": 11,
            "created_monotonic_ms": 43,
            "created_wall_clock_ms": 1700000008043,
            "task_event_seq": 9,
        }
    )
    replanned = dict(events_by_name["TASK_REPLANNED"])
    replanned.update(
        {
            "event_seq": 12,
            "created_monotonic_ms": 44,
            "created_wall_clock_ms": 1700000008044,
            "task_event_seq": 10,
        }
    )
    state_replanned = next(
        event for event in fixture["events"] if event["event_id"] == "evt_mvp1_slice8_no_adoption_state_replanned"
    )
    state_replanned = dict(state_replanned)
    state_replanned.update(
        {
            "event_seq": 13,
            "created_monotonic_ms": 45,
            "created_wall_clock_ms": 1700000008045,
            "task_event_seq": 11,
        }
    )

    fixture["events"] = [
        *base_events,
        result_received,
        patch_received,
        patch_interpreted,
        advanced,
        restarted,
        replanned,
        state_replanned,
    ]
    return fixture, result_received, state_replanned
