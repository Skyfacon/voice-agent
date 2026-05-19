from __future__ import annotations

from copy import deepcopy
from hashlib import sha256

import pytest

from conftest import MVP2_REPLAY_FIXTURE_DIR, load_json_fixture
from voice_agent.demo_backend.in_memory import InMemoryDemoBackend
from voice_agent.replay.runner import ReplayValidationError, run_replay_fixture
from voice_agent.state.demo_ui_state import DemoUIState, DemoUIStateError


TOOL_UI_STATE_FIXTURE = MVP2_REPLAY_FIXTURE_DIR / "003-tool-ui-state-patch.fixture.json"
TOOL_EXECUTION_FIXTURE = MVP2_REPLAY_FIXTURE_DIR / "001-tool-execution-state.fixture.json"


def test_mvp2_tool_ui_state_fixture_reconstructs_demo_state_without_backend_execution(
    monkeypatch,
) -> None:
    def fail_backend_execution(*args: object, **kwargs: object) -> object:
        raise AssertionError("deterministic replay must not execute demo backend")

    monkeypatch.setattr(InMemoryDemoBackend, "execute", fail_backend_execution)

    fixture = load_json_fixture(TOOL_UI_STATE_FIXTURE)
    first = run_replay_fixture(fixture)
    second = run_replay_fixture(fixture)

    assert first.result_status == "passed"
    assert first.diagnostics["ignored_events"] == []
    assert first.state_digest == second.state_digest
    assert first.state_digest["demo_ui_state_hash"]

    expected_patch_id = _expected_ui_patch_id(
        namespace="memo",
        operation="create",
        idempotency_key="idem://synthetic/mvp2/slice3/memo-create",
    )
    demo_state = first.demo_ui_state
    assert sorted(demo_state.namespaces) == ["memo"]
    memo_state = demo_state.namespaces["memo"]
    assert memo_state.applied_patch_ids == (expected_patch_id,)
    assert memo_state.operation_counts == {"create": 1}
    assert memo_state.last_patch_id == expected_patch_id

    patch = demo_state.patches_by_id[expected_patch_id]
    assert patch.event_id == "evt_mvp2_slice3_memo_ui_state_patched"
    assert patch.tool_call_id == "tool_call_mvp2_slice3_memo"
    assert patch.task_id == "task_mvp2_slice3"
    assert patch.plan_version == 1
    assert patch.task_event_seq == 8
    assert patch.idempotency_key == "idem://synthetic/mvp2/slice3/memo-create"
    assert patch.patch_ref == f"patch://synthetic/demo_backend/memo/create/{expected_patch_id}"
    assert patch.state_namespace == "memo"
    assert patch.patch_operation == "create"

    tool_call = first.tool_execution_state.tool_calls["tool_call_mvp2_slice3_memo"]
    assert tool_call.ui_patches[-1].ui_patch_id == expected_patch_id
    assert tool_call.results[-1].event_id == "evt_mvp2_slice3_memo_result_received"
    assert tool_call.results[-1].task_event_seq == 9


def test_replay_does_not_reconstruct_demo_state_from_tool_result_without_patch_event() -> None:
    fixture = load_json_fixture(TOOL_UI_STATE_FIXTURE)
    patch_event = _event_by_id(fixture["events"], "evt_mvp2_slice3_memo_ui_state_patched")
    progress_event = _event_by_id(fixture["events"], "evt_mvp2_slice3_memo_progress_updated")
    result_event = _event_by_id(fixture["events"], "evt_mvp2_slice3_memo_result_received")
    fixture["events"] = [
        event
        for event in fixture["events"]
        if event["event_id"] != patch_event["event_id"]
    ]
    result_event["caused_by_event_id"] = progress_event["event_id"]
    result_event["task_event_seq"] = patch_event["task_event_seq"]

    result = run_replay_fixture(deepcopy(fixture))

    assert result.tool_execution_state.tool_calls["tool_call_mvp2_slice3_memo"].results[-1].result_status == "SUCCEEDED"
    assert result.demo_ui_state.namespaces == {}
    assert result.demo_ui_state.patches_by_id == {}


def test_replay_rejects_ui_patch_without_prior_execution_start() -> None:
    fixture = load_json_fixture(TOOL_UI_STATE_FIXTURE)
    arguments_ready = _event_by_id(fixture["events"], "evt_mvp2_slice3_memo_arguments_ready")
    patch_event = _event_by_id(fixture["events"], "evt_mvp2_slice3_memo_ui_state_patched")
    fixture["events"] = [
        event
        for event in fixture["events"]
        if event["event_name"]
        not in {
            "TOOL_EXECUTION_AUTHORIZED",
            "TOOL_EXECUTION_STARTED",
            "TOOL_PROGRESS_UPDATED",
            "TOOL_RESULT_RECEIVED",
        }
    ]
    patch_event["caused_by_event_id"] = arguments_ready["event_id"]
    patch_event["task_event_seq"] = int(arguments_ready["task_event_seq"]) + 1

    with pytest.raises(ReplayValidationError, match="TOOL_UI_STATE_PATCHED requires prior TOOL_EXECUTION_STARTED"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_ui_patch_with_plan_version_that_never_started() -> None:
    fixture = load_json_fixture(TOOL_UI_STATE_FIXTURE)
    patch_event = _event_by_id(fixture["events"], "evt_mvp2_slice3_memo_ui_state_patched")
    patch_event["plan_version"] = 2

    with pytest.raises(ReplayValidationError, match="TOOL_UI_STATE_PATCHED requires prior TOOL_EXECUTION_STARTED"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_ui_patch_when_manifest_is_not_ui_capable() -> None:
    fixture = load_json_fixture(TOOL_UI_STATE_FIXTURE)
    manifest = _event_by_id(fixture["events"], "evt_mvp2_slice3_memo_manifest_loaded")
    manifest["ui_patch_capable"] = False

    with pytest.raises(ReplayValidationError, match="TOOL_UI_STATE_PATCHED requires ui_patch_capable manifest"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_validates_ui_patch_against_started_call_manifest_not_later_manifest() -> None:
    fixture = load_json_fixture(TOOL_UI_STATE_FIXTURE)
    original_manifest = _event_by_id(fixture["events"], "evt_mvp2_slice3_memo_manifest_loaded")
    progress_event = _event_by_id(fixture["events"], "evt_mvp2_slice3_memo_progress_updated")
    patch_event = _event_by_id(fixture["events"], "evt_mvp2_slice3_memo_ui_state_patched")
    patch_event_seq = int(patch_event["event_seq"])
    later_manifest = deepcopy(original_manifest)
    later_manifest.update(
        {
            "event_id": "evt_mvp2_slice3_memo_later_manifest_loaded",
            "event_seq": patch_event_seq,
            "created_monotonic_ms": int(progress_event["created_monotonic_ms"]) + 1,
            "created_wall_clock_ms": int(progress_event["created_wall_clock_ms"]) + 1,
            "caused_by_event_id": progress_event["event_id"],
            "tool_manifest_version": "2026-05-18.slice3-later-disabled",
            "ui_patch_capable": False,
            "sandbox_state_namespace": "alarm",
        }
    )
    for event in fixture["events"]:
        if int(event["event_seq"]) >= patch_event_seq:
            event["event_seq"] = int(event["event_seq"]) + 1
    patch_index = fixture["events"].index(patch_event)
    fixture["events"].insert(patch_index, later_manifest)

    result = run_replay_fixture(deepcopy(fixture))

    assert result.result_status == "passed"
    assert result.demo_ui_state.namespaces["memo"].operation_counts == {"create": 1}


def test_replay_rejects_ui_patch_with_unparseable_patch_ref_when_manifest_requires_namespace() -> None:
    fixture = load_json_fixture(TOOL_UI_STATE_FIXTURE)
    patch_event = _event_by_id(fixture["events"], "evt_mvp2_slice3_memo_ui_state_patched")
    patch_event["patch_ref"] = "patch://synthetic/garbage"

    with pytest.raises(ReplayValidationError, match="patch_ref namespace must be parseable"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_preserves_operation_from_legacy_synthetic_patch_ref() -> None:
    result = run_replay_fixture(load_json_fixture(TOOL_EXECUTION_FIXTURE))

    memo_state = result.demo_ui_state.namespaces["memo"]
    assert memo_state.operation_counts == {"create": 1}
    patch = result.demo_ui_state.patches_by_id["ui_patch_mvp2_slice1_memo_create"]
    assert patch.patch_ref == "patch://synthetic/mvp2/slice1/memo/create"
    assert patch.state_namespace == "memo"
    assert patch.patch_operation == "create"


def test_demo_ui_state_rejects_duplicate_patch_id_with_different_task_binding() -> None:
    state = DemoUIState()
    first_event = {
        "event_name": "TOOL_UI_STATE_PATCHED",
        "event_id": "evt_mvp2_slice3_patch_first",
        "tool_call_id": "tool_call_mvp2_slice3_memo",
        "task_id": "task_mvp2_slice3",
        "plan_version": 1,
        "task_event_seq": 8,
        "ui_patch_id": "ui_patch_memo_create_same",
        "idempotency_key": "idem://synthetic/mvp2/slice3/memo-create",
        "patch_ref": "patch://synthetic/demo_backend/memo/create/ui_patch_memo_create_same",
    }
    state.reduce_event(first_event)

    second_event = {
        **first_event,
        "event_id": "evt_mvp2_slice3_patch_second",
        "task_id": "task_mvp2_slice3_other",
        "task_event_seq": 9,
    }
    with pytest.raises(DemoUIStateError, match="ui_patch_id cannot be reused"):
        state.reduce_event(second_event)


def _event_by_id(events: list[dict[str, object]], event_id: str) -> dict[str, object]:
    return next(event for event in events if event["event_id"] == event_id)


def _expected_ui_patch_id(*, namespace: str, operation: str, idempotency_key: str) -> str:
    digest = sha256(f"{namespace}:{operation}:{idempotency_key}".encode("utf-8")).hexdigest()[:16]
    return f"ui_patch_{namespace}_{operation}_{digest}"
