from __future__ import annotations

from copy import deepcopy
from hashlib import sha256

from conftest import MVP2_REPLAY_FIXTURE_DIR, load_json_fixture
from voice_agent.demo_backend.in_memory import InMemoryDemoBackend
from voice_agent.replay.runner import run_replay_fixture


DEMO_TOOLS_FIXTURE = MVP2_REPLAY_FIXTURE_DIR / "004-demo-tools.fixture.json"


def test_mvp2_demo_tools_fixture_reconstructs_ui_state_without_backend_execution(
    monkeypatch,
) -> None:
    def fail_backend_execution(*args: object, **kwargs: object) -> object:
        raise AssertionError("deterministic replay must not execute demo backend")

    monkeypatch.setattr(InMemoryDemoBackend, "execute", fail_backend_execution)

    fixture = load_json_fixture(DEMO_TOOLS_FIXTURE)
    first = run_replay_fixture(fixture)
    second = run_replay_fixture(fixture)

    assert first.result_status == "passed"
    assert first.diagnostics["ignored_events"] == []
    assert first.state_digest == second.state_digest

    demo_state = first.demo_ui_state
    assert sorted(demo_state.namespaces) == ["alarm", "flashlight", "memo"]
    assert demo_state.namespaces["memo"].operation_counts == {"create": 1}
    assert demo_state.namespaces["alarm"].operation_counts == {"create": 1}
    assert demo_state.namespaces["flashlight"].operation_counts == {"set_on": 1}

    expected_memo_patch = _expected_ui_patch_id(
        namespace="memo",
        operation="create",
        idempotency_key="idem://synthetic/mvp2/slice4/memo-create",
    )
    expected_alarm_patch = _expected_ui_patch_id(
        namespace="alarm",
        operation="create",
        idempotency_key="idem://synthetic/mvp2/slice4/alarm-create",
    )
    expected_flashlight_patch = _expected_ui_patch_id(
        namespace="flashlight",
        operation="set_on",
        idempotency_key="idem://synthetic/mvp2/slice4/flashlight-on",
    )
    assert sorted(demo_state.patches_by_id) == [
        expected_alarm_patch,
        expected_flashlight_patch,
        expected_memo_patch,
    ]
    assert demo_state.patches_by_id[expected_memo_patch].patch_ref == (
        f"patch://synthetic/demo_backend/memo/create/{expected_memo_patch}"
    )
    assert demo_state.patches_by_id[expected_alarm_patch].patch_ref == (
        f"patch://synthetic/demo_backend/alarm/create/{expected_alarm_patch}"
    )
    assert demo_state.patches_by_id[expected_flashlight_patch].patch_ref == (
        f"patch://synthetic/demo_backend/flashlight/set_on/{expected_flashlight_patch}"
    )


def test_mvp2_demo_tools_fixture_records_tool_results_and_websearch_evidence_only() -> None:
    result = run_replay_fixture(load_json_fixture(DEMO_TOOLS_FIXTURE))

    tool_state = result.tool_execution_state
    assert sorted(tool_state.tool_manifests) == ["alarm", "flashlight", "memo", "weather", "webSearch"]

    memo = tool_state.tool_calls["tool_call_mvp2_slice4_memo_create"]
    alarm = tool_state.tool_calls["tool_call_mvp2_slice4_alarm_create"]
    flashlight = tool_state.tool_calls["tool_call_mvp2_slice4_flashlight_on"]
    weather = tool_state.tool_calls["tool_call_mvp2_slice4_weather"]
    websearch = tool_state.tool_calls["tool_call_mvp2_slice4_websearch"]

    assert memo.results[-1].trust_level == "TRUSTED_DEMO_TOOL_RESULT"
    assert memo.ui_patches[-1].patch_ref.startswith("patch://synthetic/demo_backend/memo/create/")
    assert alarm.results[-1].trust_level == "TRUSTED_DEMO_TOOL_RESULT"
    assert alarm.ui_patches[-1].patch_ref.startswith("patch://synthetic/demo_backend/alarm/create/")
    assert flashlight.results[-1].trust_level == "TRUSTED_DEMO_TOOL_RESULT"
    assert flashlight.ui_patches[-1].patch_ref.startswith("patch://synthetic/demo_backend/flashlight/set_on/")

    assert weather.results[-1].trust_level == "EXTERNAL_READ_PROVIDER_RESULT"
    assert weather.results[-1].source_type == "READ_ONLY_EXTERNAL"
    assert weather.ui_patches == ()

    assert websearch.results[-1].trust_level == "UNTRUSTED_WEB_EVIDENCE"
    assert websearch.results[-1].source_type == "EXTERNAL_READ_UNTRUSTED"
    assert websearch.ui_patches == ()
    assert "webSearch" not in result.demo_ui_state.namespaces

    task = result.slowtask_state.tasks["task_mvp2_slice4"]
    assert task.tool_results[-1].event_id == "evt_mvp2_slice4_websearch_result_received"
    assert any(
        event.event_name == "EVIDENCE_REVIEWED"
        and event.refs == ("result://synthetic/demo_backend/websearch/search_000001",)
        for event in task.evidence_events
    )


def test_replay_does_not_reconstruct_alarm_state_from_result_without_ui_patch() -> None:
    fixture = load_json_fixture(DEMO_TOOLS_FIXTURE)
    patch_event = _event_by_id(fixture["events"], "evt_mvp2_slice4_alarm_ui_state_patched")
    progress_event = _event_by_id(fixture["events"], "evt_mvp2_slice4_alarm_progress_updated")
    result_event = _event_by_id(fixture["events"], "evt_mvp2_slice4_alarm_result_received")
    fixture["events"] = [
        event
        for event in fixture["events"]
        if event["event_id"] != patch_event["event_id"]
    ]
    result_event["caused_by_event_id"] = progress_event["event_id"]
    result_event["task_event_seq"] = patch_event["task_event_seq"]

    result = run_replay_fixture(deepcopy(fixture))

    assert result.tool_execution_state.tool_calls["tool_call_mvp2_slice4_alarm_create"].results[-1].result_status == (
        "SUCCEEDED"
    )
    assert "alarm" not in result.demo_ui_state.namespaces


def _event_by_id(events: list[dict[str, object]], event_id: str) -> dict[str, object]:
    return next(event for event in events if event["event_id"] == event_id)


def _expected_ui_patch_id(*, namespace: str, operation: str, idempotency_key: str) -> str:
    digest = sha256(f"{namespace}:{operation}:{idempotency_key}".encode("utf-8")).hexdigest()[:16]
    return f"ui_patch_{namespace}_{operation}_{digest}"
