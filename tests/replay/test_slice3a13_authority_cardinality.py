from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from voice_agent.replay.runner import ReplayValidationError, run_replay_fixture


_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_replay_rejects_second_spawn_mutation_initiation_for_same_turn() -> None:
    fixture = _load_fixture("tests/fixtures/replay/mvp1/004-spawn-planning-completed.fixture.json")
    router = _only_event(fixture, "ROUTER_DECISION_EMITTED")
    created = deepcopy(_only_event(fixture, "SLOWTASK_CREATED"))
    created["event_id"] = "evt_slice3a13_duplicate_slowtask_created"
    created["task_id"] = "task_slice3a13_duplicate_spawn"
    created["caused_by_event_id"] = router["event_id"]
    created["task_event_seq"] = 1
    _append_with_contiguous_metadata(fixture, created)

    with pytest.raises(ReplayValidationError, match="SPAWN mutation initiation"):
        run_replay_fixture(fixture)


def test_replay_rejects_second_user_patch_initiation_for_same_turn() -> None:
    fixture = _load_fixture("tests/fixtures/replay/mvp1/005-active-patch-evidence.fixture.json")
    received = deepcopy(_only_event(fixture, "USER_PATCH_RECEIVED"))
    received["event_id"] = "evt_slice3a13_duplicate_user_patch_received"
    received["patch_id"] = "patch_slice3a13_duplicate"
    received["task_event_seq"] = _next_task_event_seq(fixture, str(received["task_id"]))
    _append_with_contiguous_metadata(fixture, received)

    with pytest.raises(ReplayValidationError, match="PATCH/UserPatch mutation initiation"):
        run_replay_fixture(fixture)


def test_replay_rejects_legacy_second_router_when_switch_confirmation_chain_is_unrelated() -> None:
    fixture = _load_fixture(
        "tests/fixtures/replay/mvp1/009-switch-task-confirmation-accepted.fixture.json"
    )
    focus_cleared = _event_by_id(
        fixture,
        "evt_mvp1_slice9_switch_focus_cleared",
    )
    unrelated_old_router_id = "evt_mvp1_slice9_switch_router"
    focus_cleared["caused_by_event_id"] = unrelated_old_router_id
    focus_cleared["router_decision_event_id"] = unrelated_old_router_id
    focus_cleared["last_focus_event_id"] = unrelated_old_router_id

    with pytest.raises(
        ReplayValidationError,
        match="ROUTER_DECISION_EMITTED.*turn_id.*utterance_id",
    ):
        run_replay_fixture(fixture)


def _load_fixture(relative_path: str) -> dict[str, object]:
    loaded = json.loads((_REPO_ROOT / relative_path).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _only_event(fixture: dict[str, object], event_name: str) -> dict[str, object]:
    events = fixture["events"]
    assert isinstance(events, list)
    matches = [event for event in events if event["event_name"] == event_name]
    assert len(matches) == 1
    return matches[0]


def _event_by_id(fixture: dict[str, object], event_id: str) -> dict[str, object]:
    events = fixture["events"]
    assert isinstance(events, list)
    matches = [event for event in events if event["event_id"] == event_id]
    assert len(matches) == 1
    return matches[0]


def _next_task_event_seq(fixture: dict[str, object], task_id: str) -> int:
    events = fixture["events"]
    assert isinstance(events, list)
    return (
        max(
            int(event["task_event_seq"])
            for event in events
            if event.get("task_id") == task_id and event.get("task_event_seq") is not None
        )
        + 1
    )


def _append_with_contiguous_metadata(
    fixture: dict[str, object],
    event: dict[str, object],
) -> None:
    events = fixture["events"]
    assert isinstance(events, list)
    last = events[-1]
    event["event_seq"] = int(last["event_seq"]) + 1
    event["created_monotonic_ms"] = int(last["created_monotonic_ms"]) + 1
    event["created_wall_clock_ms"] = int(last["created_wall_clock_ms"]) + 1
    events.append(event)
