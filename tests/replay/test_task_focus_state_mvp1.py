from __future__ import annotations

import pytest

from conftest import MVP1_REPLAY_FIXTURE_DIR, load_json_fixture
from voice_agent.replay.runner import ReplayValidationError, run_replay_fixture
from voice_agent.state.task_focus_state import TaskFocusState


TASK_FOCUS_FIXTURE = MVP1_REPLAY_FIXTURE_DIR / "002-task-focus-router.fixture.json"


def test_task_focus_state_replays_router_decision_and_focus_snapshot_event() -> None:
    state = TaskFocusState()

    assert state.reduce_event(
        {
            "event_name": "ROUTER_DECISION_EMITTED",
            "event_id": "evt_mvp1_slice2_router_decision_inline",
            "router_decision": "PATCH_ACTIVE_SLOW_TASK",
            "task_focus": "ACTIVE_TASK_PATCH",
            "confidence": 0.9,
            "active_task_id": "task_mvp1_slice2_inline",
        }
    )
    assert state.last_focus_decision == "ACTIVE_TASK_PATCH"
    assert state.last_focus_confidence == 0.9
    assert state.router_decision_event_id == "evt_mvp1_slice2_router_decision_inline"
    assert state.last_focus_event_id == "evt_mvp1_slice2_router_decision_inline"

    assert state.reduce_event(
        {
            "event_name": "TASK_FOCUS_STATE_UPDATED",
            "event_id": "evt_mvp1_slice2_focus_update_inline",
            "active_task_id": "task_mvp1_slice2_inline",
            "foreground_mode": "SLOWTASK_ACTIVE",
            "side_conversation_allowed": True,
            "default_patch_policy": "ACTIVE_TASK_PATCH_ONLY",
            "ambiguous_input_policy": "CLARIFY",
            "last_focus_decision": "ACTIVE_TASK_PATCH",
            "last_focus_confidence": 0.9,
            "router_decision_event_id": "evt_mvp1_slice2_router_decision_inline",
            "last_focus_event_id": "evt_mvp1_slice2_router_decision_inline",
        }
    )

    assert state.active_task_id == "task_mvp1_slice2_inline"
    assert state.foreground_mode == "SLOWTASK_ACTIVE"
    assert state.side_conversation_allowed is True
    assert state.default_patch_policy == "ACTIVE_TASK_PATCH_ONLY"
    assert state.ambiguous_input_policy == "CLARIFY"
    assert state.last_focus_decision == "ACTIVE_TASK_PATCH"
    assert state.last_focus_confidence == 0.9
    assert state.router_decision_event_id == "evt_mvp1_slice2_router_decision_inline"
    assert state.last_focus_event_id == "evt_mvp1_slice2_router_decision_inline"


def test_mvp1_task_focus_router_fixture_replays_deterministically() -> None:
    result = run_replay_fixture(load_json_fixture(TASK_FOCUS_FIXTURE))

    event_names = [event["event_name"] for event in result.ordered_events]
    assert event_names.count("ROUTER_DECISION_EMITTED") == 3
    assert event_names.count("TASK_FOCUS_STATE_UPDATED") == 3
    assert "USER_PATCH_RECEIVED" not in event_names
    assert "SLOWTASK_CREATED" not in event_names
    assert "SLOWTASK_STATE_CHANGED" not in event_names

    assert result.task_focus_state.active_task_id == "task_mvp1_slice2_focus_001"
    assert result.task_focus_state.foreground_mode == "FAST_RESPONSE"
    assert result.task_focus_state.side_conversation_allowed is True
    assert result.task_focus_state.default_patch_policy == "ACTIVE_TASK_PATCH_ONLY"
    assert result.task_focus_state.ambiguous_input_policy == "CLARIFY"
    assert result.task_focus_state.last_focus_decision == "AMBIGUOUS"
    assert result.task_focus_state.last_focus_confidence == 0.51
    assert result.task_focus_state.router_decision_event_id == "evt_mvp1_slice2_router_ambiguous"
    assert result.task_focus_state.last_focus_event_id == "evt_mvp1_slice2_router_ambiguous"
    assert result.state_digest["task_focus_state_hash"]
    assert result.result_status == "passed"


def test_mvp1_replay_rejects_slowtask_state_change_without_prior_creation() -> None:
    fixture = load_json_fixture(TASK_FOCUS_FIXTURE)
    fixture["events"].append(
        {
            "event_name": "SLOWTASK_STATE_CHANGED",
            "event_id": "evt_mvp1_slice2_out_of_order_slowtask_state_changed",
            "event_seq": 27,
            "event_schema_version": "1.0",
            "session_id": "sess_mvp1_slice2_task_focus",
            "conversation_id": "conv_mvp1_slice2_task_focus",
            "source_module": "slowtask_runtime",
            "created_monotonic_ms": 270,
            "created_wall_clock_ms": 1700000000270,
            "caused_by_event_id": "evt_mvp1_slice2_focus_ambiguous",
            "trace_redaction_level": "metadata_only",
            "task_id": "task_mvp1_slice2_focus_001",
            "plan_version": 1,
            "task_event_seq": 1,
            "from_state": "PLANNING",
            "to_state": "COMPLETED",
            "reason": "out_of_order_state_change",
        }
    )

    with pytest.raises(ReplayValidationError, match="references unknown task_id"):
        run_replay_fixture(fixture)


def test_replay_rejects_task_focus_update_not_caused_by_its_router_decision() -> None:
    fixture = load_json_fixture(TASK_FOCUS_FIXTURE)
    focus_event = next(
        event for event in fixture["events"] if event["event_id"] == "evt_mvp1_slice2_focus_patch"
    )
    focus_event["caused_by_event_id"] = "evt_mvp1_slice2_thinker_patch"

    with pytest.raises(ReplayValidationError, match="TASK_FOCUS_STATE_UPDATED.*router_decision_event_id"):
        run_replay_fixture(fixture)


def test_replay_rejects_task_focus_update_with_unknown_router_decision_event_id() -> None:
    fixture = load_json_fixture(TASK_FOCUS_FIXTURE)
    focus_event = next(
        event for event in fixture["events"] if event["event_id"] == "evt_mvp1_slice2_focus_patch"
    )
    focus_event["router_decision_event_id"] = "evt_mvp1_slice2_missing_router_decision"

    with pytest.raises(ReplayValidationError, match="TASK_FOCUS_STATE_UPDATED.*router_decision_event_id"):
        run_replay_fixture(fixture)
