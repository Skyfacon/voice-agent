from __future__ import annotations

from conftest import MVP1_REPLAY_FIXTURE_DIR, load_json_fixture
from voice_agent.replay.runner import run_replay_fixture


CANCEL_FIXTURE = MVP1_REPLAY_FIXTURE_DIR / "009-cancel-confirmation.fixture.json"
SWITCH_ACCEPTED_FIXTURE = MVP1_REPLAY_FIXTURE_DIR / "009-switch-task-confirmation-accepted.fixture.json"
SWITCH_REJECTED_FIXTURE = MVP1_REPLAY_FIXTURE_DIR / "009-switch-task-confirmation-rejected.fixture.json"


def test_cancel_confirmation_fixture_replays_terminal_cancel_and_sticky_late_events() -> None:
    result = run_replay_fixture(load_json_fixture(CANCEL_FIXTURE))

    event_names = [event["event_name"] for event in result.ordered_events]
    assert _event_names_after(event_names, "USER_PATCH_RECEIVED")[:11] == [
        "USER_PATCH_RECEIVED",
        "USER_PATCH_INTERPRETED",
        "CONFIRMATION_REQUIRED",
        "WAITING_FOR_USER_CONFIRMATION",
        "SLOWTASK_STATE_CHANGED",
        "TURN_INGRESS_COMMITTED",
        "MOCK_ASR_FRAME_EMITTED",
        "MOCK_THINKER_FRAME_EMITTED",
        "ROUTER_DECISION_EMITTED",
        "TASK_FOCUS_STATE_UPDATED",
        "USER_PATCH_RECEIVED",
    ]
    assert "TOOL_EXECUTION_STARTED" not in event_names
    assert "TOOL_PROGRESS_UPDATED" not in event_names
    assert "TOOL_UI_STATE_PATCHED" not in event_names

    task = result.slowtask_state.tasks["task_mvp1_slice9_cancel"]
    assert task.lifecycle_state == "CANCELLED"
    assert task.terminal_outcome == "CANCELLED"
    assert task.cancel_reason == "task_cancel_accepted"
    assert task.confirmation_state.status == "accepted"
    assert task.confirmation_state.accepted_scope == "TASK_CANCEL"
    assert [event.event_name for event in task.late_events] == [
        "USER_PATCH_RECEIVED",
        "USER_PATCH_INTERPRETED",
        "USER_CONFIRMATION_RECEIVED",
    ]
    assert result.task_focus_state.active_task_id is None
    assert result.result_status == "passed"


def test_switch_task_accepted_fixture_replays_cancel_then_later_spawn_without_overlap() -> None:
    result = run_replay_fixture(load_json_fixture(SWITCH_ACCEPTED_FIXTURE))
    events = result.ordered_events
    event_names = [event["event_name"] for event in events]

    cancelled_index = _index_of_event_id(events, "evt_mvp1_slice9_switch_accept_state_cancelled")
    replacement_router_index = _index_of_event_id(events, "evt_mvp1_slice9_switch_spawn_router")
    replacement_created_index = _index_of_event_id(events, "evt_mvp1_slice9_switch_replacement_created")
    replacement_focus_index = _index_of_event_id(events, "evt_mvp1_slice9_switch_focus_replacement")
    assert cancelled_index < replacement_router_index < replacement_created_index < replacement_focus_index
    assert event_names.count("SLOWTASK_CREATED") == 2

    cancelled = result.slowtask_state.tasks["task_mvp1_slice9_switch_active"]
    replacement = result.slowtask_state.tasks["task_mvp1_slice9_switch_replacement"]
    assert cancelled.lifecycle_state == "CANCELLED"
    assert cancelled.cancel_reason == "switch_task_accepted"
    assert replacement.lifecycle_state == "CREATED"
    assert result.task_focus_state.active_task_id == "task_mvp1_slice9_switch_replacement"
    assert result.task_focus_state.last_focus_decision == "NEW_TASK_CANDIDATE"


def test_switch_task_rejected_fixture_preserves_active_task_and_current_plan() -> None:
    result = run_replay_fixture(load_json_fixture(SWITCH_REJECTED_FIXTURE))

    assert set(result.slowtask_state.tasks) == {"task_mvp1_slice9_switch_rejected"}
    task = result.slowtask_state.tasks["task_mvp1_slice9_switch_rejected"]
    assert task.lifecycle_state == "PLANNING"
    assert task.terminal_outcome is None
    assert task.current_plan_version == 1
    assert task.initial_goal_ref == "goal://synthetic/mvp1/slice9/switch-rejected-initial"
    assert task.resolved_arguments_refs == ("args://synthetic/mvp1/slice9/switch-rejected-current",)
    assert task.confirmation_state.status == "rejected"
    assert task.confirmation_state.rejection_reason == "user_rejected_switch_task"
    assert task.cancel_request_event_id is None
    assert task.cancelled_event_id is None
    assert result.task_focus_state.active_task_id == "task_mvp1_slice9_switch_rejected"


def _event_names_after(event_names: list[str], first_event_name: str) -> list[str]:
    start = event_names.index(first_event_name)
    return event_names[start:]


def _index_of_event_id(events: tuple[dict[str, object], ...], event_id: str) -> int:
    return next(index for index, event in enumerate(events) if event["event_id"] == event_id)
