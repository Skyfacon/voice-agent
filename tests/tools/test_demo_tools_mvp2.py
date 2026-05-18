from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256

import pytest

from voice_agent.demo_backend.in_memory import InMemoryDemoBackend
from voice_agent.runtime.session import start_mvp0_session
from voice_agent.tools.demo_manifests import (
    alarm_create_manifest,
    alarm_list_manifest,
    flashlight_set_manifest,
    memo_create_manifest,
    memo_list_manifest,
    weather_manifest,
    web_search_manifest,
)
from voice_agent.tools.executor import DemoToolExecutor, ToolExecutionPolicyError, ToolExecutionRequest
from voice_agent.tools.manifest import BLOCKED_SIDE_EFFECT_CLASSES
from voice_agent.tools.registry import ToolRegistry


def test_memo_create_emits_deterministic_ui_patch_and_result_refs() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([memo_create_manifest()]),
        backend=backend,
    )
    idempotency_key = "idem://synthetic/mvp2/slice4/memo-create"

    result = executor.execute(
        _request(
            tool_call_id="tool_call_mvp2_slice4_memo_create",
            tool_name="memo",
            caused_by_event_id=caused_by_event_id,
            event_id_prefix="evt_mvp2_slice4_memo_create",
            idempotency_key=idempotency_key,
            arguments={"body": "Synthetic memo body that must stay out of refs"},
            argument_provenance={"body": "evt_mvp2_slice4_arguments_resolved"},
        )
    )

    event_names = [event["event_name"] for event in result.produced_events]
    assert event_names == [
        "TOOL_MANIFEST_LOADED",
        "TOOL_ARGUMENTS_READY",
        "TOOL_EXECUTION_AUTHORIZED",
        "TOOL_EXECUTION_STARTED",
        "TOOL_PROGRESS_UPDATED",
        "TOOL_UI_STATE_PATCHED",
        "TOOL_RESULT_RECEIVED",
    ]
    manifest = result.produced_events[0]
    assert manifest["tool_category"] == "DEMO_STATE_WRITE"
    assert manifest["side_effect_class"] == "SANDBOX_WRITE"
    assert manifest["ui_patch_capable"] is True

    patch = result.produced_events[5]
    expected_patch_id = _expected_ui_patch_id(
        namespace="memo",
        operation="create",
        idempotency_key=idempotency_key,
    )
    assert patch["ui_patch_id"] == expected_patch_id
    assert patch["patch_ref"] == f"patch://synthetic/demo_backend/memo/create/{expected_patch_id}"
    assert patch["idempotency_key"] == idempotency_key

    received = result.produced_events[-1]
    assert received["result_ref"] == "result://synthetic/demo_backend/memo/memo_write_000001"
    assert received["trust_level"] == "TRUSTED_DEMO_TOOL_RESULT"
    assert received["source_type"] == "DEMO_SANDBOX"
    assert result.payload is not None
    assert result.payload["memo_item_id"] == "memo_item_000001"
    assert backend.executed_calls == (
        ("memo", {"body": "Synthetic memo body that must stay out of refs"}),
    )
    assert "Synthetic memo body" not in repr(result.produced_events)
    assert "Synthetic memo body" not in str(received["result_ref"])
    assert not any(event["event_name"].startswith("SLOWTASK_") for event in result.produced_events)


def test_memo_list_is_read_only_and_emits_no_ui_patch() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([memo_create_manifest(), memo_list_manifest()]),
        backend=backend,
    )
    created = executor.execute(
        _request(
            tool_call_id="tool_call_mvp2_slice4_memo_create",
            tool_name="memo",
            caused_by_event_id=caused_by_event_id,
            event_id_prefix="evt_mvp2_slice4_memo_create",
            idempotency_key="idem://synthetic/mvp2/slice4/memo-create",
            arguments={"body": "Synthetic memo body"},
            argument_provenance={"body": "evt_mvp2_slice4_arguments_resolved"},
        )
    )

    listed = executor.execute(
        _request(
            tool_call_id="tool_call_mvp2_slice4_memo_list",
            tool_name="memo.list",
            caused_by_event_id=str(created.produced_events[-1]["event_id"]),
            event_id_prefix="evt_mvp2_slice4_memo_list",
            start_task_event_seq=9,
            idempotency_key="idem://synthetic/mvp2/slice4/memo-list",
            arguments={},
            argument_provenance={},
            resolved_arguments_ref="args://synthetic/mvp2/slice4/memo/list-ready",
            provenance_ref="provenance://synthetic/mvp2/slice4/memo/list-ready",
        )
    )

    event_names = [event["event_name"] for event in listed.produced_events]
    assert event_names == [
        "TOOL_MANIFEST_LOADED",
        "TOOL_ARGUMENTS_READY",
        "TOOL_EXECUTION_AUTHORIZED",
        "TOOL_EXECUTION_STARTED",
        "TOOL_PROGRESS_UPDATED",
        "TOOL_RESULT_RECEIVED",
    ]
    assert "TOOL_UI_STATE_PATCHED" not in event_names
    assert listed.produced_events[0]["side_effect_class"] == "READ_ONLY"
    assert listed.produced_events[-1]["result_ref"] == "result://synthetic/demo_backend/memo/memo_list_000001"
    assert listed.payload is not None
    assert listed.payload["item_count"] == 1


def test_alarm_create_emits_deterministic_ui_patch_and_result_refs() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([alarm_create_manifest()]),
        backend=backend,
    )
    idempotency_key = "idem://synthetic/mvp2/slice4/alarm-create"

    result = executor.execute(
        _request(
            tool_call_id="tool_call_mvp2_slice4_alarm_create",
            tool_name="alarm",
            caused_by_event_id=caused_by_event_id,
            event_id_prefix="evt_mvp2_slice4_alarm_create",
            idempotency_key=idempotency_key,
            arguments={
                "time": "07:30",
                "timezone": "Etc/UTC",
                "label": "Synthetic wake reminder",
            },
            argument_provenance={
                "time": "evt_mvp2_slice4_arguments_resolved",
                "timezone": "evt_mvp2_slice4_arguments_resolved",
                "label": "evt_mvp2_slice4_arguments_resolved",
            },
        )
    )

    event_names = [event["event_name"] for event in result.produced_events]
    assert event_names == [
        "TOOL_MANIFEST_LOADED",
        "TOOL_ARGUMENTS_READY",
        "TOOL_PREVIEW_AVAILABLE",
        "TOOL_EXECUTION_AUTHORIZED",
        "TOOL_EXECUTION_STARTED",
        "TOOL_PROGRESS_UPDATED",
        "TOOL_UI_STATE_PATCHED",
        "TOOL_RESULT_RECEIVED",
    ]
    expected_patch_id = _expected_ui_patch_id(
        namespace="alarm",
        operation="create",
        idempotency_key=idempotency_key,
    )
    patch = result.produced_events[-2]
    assert patch["ui_patch_id"] == expected_patch_id
    assert patch["patch_ref"] == f"patch://synthetic/demo_backend/alarm/create/{expected_patch_id}"
    assert result.produced_events[-1]["result_ref"] == (
        "result://synthetic/demo_backend/alarm/alarm_write_000001"
    )
    assert result.payload is not None
    assert result.payload["alarm_id"] == "alarm_item_000001"
    assert "Synthetic wake reminder" not in repr(result.produced_events)
    assert "07:30" not in repr(result.produced_events)


def test_alarm_list_is_read_only_and_emits_no_ui_patch() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([alarm_create_manifest(), alarm_list_manifest()]),
        backend=backend,
    )
    created = executor.execute(
        _request(
            tool_call_id="tool_call_mvp2_slice4_alarm_create",
            tool_name="alarm",
            caused_by_event_id=caused_by_event_id,
            event_id_prefix="evt_mvp2_slice4_alarm_create",
            idempotency_key="idem://synthetic/mvp2/slice4/alarm-create",
            arguments={"time": "07:30", "timezone": "Etc/UTC", "label": "Synthetic alarm"},
            argument_provenance={
                "time": "evt_mvp2_slice4_arguments_resolved",
                "timezone": "evt_mvp2_slice4_arguments_resolved",
                "label": "evt_mvp2_slice4_arguments_resolved",
            },
        )
    )

    listed = executor.execute(
        _request(
            tool_call_id="tool_call_mvp2_slice4_alarm_list",
            tool_name="alarm.list",
            caused_by_event_id=str(created.produced_events[-1]["event_id"]),
            event_id_prefix="evt_mvp2_slice4_alarm_list",
            start_task_event_seq=10,
            idempotency_key="idem://synthetic/mvp2/slice4/alarm-list",
            arguments={},
            argument_provenance={},
            resolved_arguments_ref="args://synthetic/mvp2/slice4/alarm/list-ready",
            provenance_ref="provenance://synthetic/mvp2/slice4/alarm/list-ready",
        )
    )

    event_names = [event["event_name"] for event in listed.produced_events]
    assert "TOOL_UI_STATE_PATCHED" not in event_names
    assert listed.produced_events[0]["side_effect_class"] == "READ_ONLY"
    assert listed.produced_events[-1]["result_ref"] == "result://synthetic/demo_backend/alarm/alarm_list_000001"
    assert listed.payload is not None
    assert listed.payload["item_count"] == 1


def test_flashlight_on_and_off_emit_simulated_ui_patch_only() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([flashlight_set_manifest()]),
        backend=backend,
    )

    on_result = executor.execute(
        _request(
            tool_call_id="tool_call_mvp2_slice4_flashlight_on",
            tool_name="flashlight",
            caused_by_event_id=caused_by_event_id,
            event_id_prefix="evt_mvp2_slice4_flashlight_on",
            idempotency_key="idem://synthetic/mvp2/slice4/flashlight-on",
            arguments={"state": "on"},
            argument_provenance={"state": "evt_mvp2_slice4_arguments_resolved"},
        )
    )
    off_result = executor.execute(
        _request(
            tool_call_id="tool_call_mvp2_slice4_flashlight_off",
            tool_name="flashlight",
            caused_by_event_id=str(on_result.produced_events[-1]["event_id"]),
            event_id_prefix="evt_mvp2_slice4_flashlight_off",
            start_task_event_seq=9,
            idempotency_key="idem://synthetic/mvp2/slice4/flashlight-off",
            arguments={"state": "off"},
            argument_provenance={"state": "evt_mvp2_slice4_arguments_resolved"},
        )
    )

    on_patch = next(event for event in on_result.produced_events if event["event_name"] == "TOOL_UI_STATE_PATCHED")
    off_patch = next(event for event in off_result.produced_events if event["event_name"] == "TOOL_UI_STATE_PATCHED")
    assert on_patch["patch_ref"].startswith("patch://synthetic/demo_backend/flashlight/set_on/")
    assert off_patch["patch_ref"].startswith("patch://synthetic/demo_backend/flashlight/set_off/")
    assert on_result.payload is not None
    assert off_result.payload is not None
    assert on_result.payload["simulated_state"] == "on"
    assert off_result.payload["simulated_state"] == "off"
    assert on_result.payload["source"] == "in_memory_demo_backend"
    assert off_result.payload["source"] == "in_memory_demo_backend"
    assert not any("real_device" in repr(event).lower() for event in on_result.produced_events)


def test_weather_returns_mock_structured_read_only_result_without_ui_patch_by_default() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([weather_manifest(ui_patch_capable=False)]),
        backend=backend,
    )

    result = executor.execute(
        _request(
            tool_call_id="tool_call_mvp2_slice4_weather",
            tool_name="weather",
            caused_by_event_id=caused_by_event_id,
            event_id_prefix="evt_mvp2_slice4_weather",
            idempotency_key="idem://synthetic/mvp2/slice4/weather",
            arguments={"location": "Testville", "date": "2026-05-18"},
            argument_provenance={
                "location": "evt_mvp2_slice4_arguments_resolved",
                "date": "evt_mvp2_slice4_arguments_resolved",
            },
        )
    )

    event_names = [event["event_name"] for event in result.produced_events]
    assert "TOOL_UI_STATE_PATCHED" not in event_names
    assert result.produced_events[0]["tool_category"] == "READ_ONLY_EXTERNAL"
    assert result.produced_events[0]["side_effect_class"] == "READ_ONLY"
    assert result.produced_events[-1]["trust_level"] == "EXTERNAL_READ_PROVIDER_RESULT"
    assert result.produced_events[-1]["source_type"] == "READ_ONLY_EXTERNAL"
    assert result.payload == {
        "location": "Testville",
        "date": "2026-05-18",
        "condition": "synthetic_clear",
        "temperature_c": 21,
        "source": "in_memory_demo_backend",
    }


def test_websearch_returns_untrusted_evidence_without_ui_patch() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([web_search_manifest()]),
        backend=backend,
    )

    result = executor.execute(
        _request(
            tool_call_id="tool_call_mvp2_slice4_websearch",
            tool_name="webSearch",
            caused_by_event_id=caused_by_event_id,
            event_id_prefix="evt_mvp2_slice4_websearch",
            idempotency_key="idem://synthetic/mvp2/slice4/websearch",
            arguments={"query": "synthetic demo query"},
            argument_provenance={"query": "evt_mvp2_slice4_arguments_resolved"},
        )
    )

    event_names = [event["event_name"] for event in result.produced_events]
    assert "TOOL_UI_STATE_PATCHED" not in event_names
    manifest = result.produced_events[0]
    assert manifest["tool_category"] == "EXTERNAL_READ_UNTRUSTED"
    assert manifest["side_effect_class"] == "READ_ONLY"
    assert manifest["trust_level"] == "UNTRUSTED_WEB_EVIDENCE"
    assert manifest["source_type"] == "EXTERNAL_READ_UNTRUSTED"
    assert manifest["ui_patch_capable"] is False

    received = result.produced_events[-1]
    assert received["trust_level"] == "UNTRUSTED_WEB_EVIDENCE"
    assert received["source_type"] == "EXTERNAL_READ_UNTRUSTED"
    assert received["result_ref"] == "result://synthetic/demo_backend/websearch/search_000001"
    assert result.payload is not None
    assert result.payload["trust_level"] == "UNTRUSTED_WEB_EVIDENCE"
    assert result.payload["source_type"] == "EXTERNAL_READ_UNTRUSTED"
    assert result.payload["redaction_status"] == "synthetic_minimal"
    assert "ignore previous rules" in result.payload["results"][0]["snippet_or_summary"]
    assert "synthetic demo query" not in repr(result.produced_events)
    assert "synthetic demo query" not in str(received["result_ref"])


def test_non_ui_capable_manifest_does_not_emit_patch_even_for_ui_backend_result() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([memo_create_manifest(ui_patch_capable=False)]),
        backend=backend,
    )

    result = executor.execute(
        _request(
            tool_call_id="tool_call_mvp2_slice4_memo_non_ui",
            tool_name="memo",
            caused_by_event_id=caused_by_event_id,
            event_id_prefix="evt_mvp2_slice4_memo_non_ui",
            idempotency_key="idem://synthetic/mvp2/slice4/memo-non-ui",
            arguments={"body": "Synthetic memo"},
            argument_provenance={"body": "evt_mvp2_slice4_arguments_resolved"},
        )
    )

    assert "TOOL_UI_STATE_PATCHED" not in [event["event_name"] for event in result.produced_events]
    assert result.produced_events[-1]["event_name"] == "TOOL_RESULT_RECEIVED"
    assert backend.executed_calls == (("memo", {"body": "Synthetic memo"}),)


@pytest.mark.parametrize(
    ("arguments", "argument_provenance", "expected_missing"),
    [
        ({}, {}, ("query",)),
        ({"query": "synthetic demo query"}, {}, ("provenance.query",)),
    ],
)
def test_missing_args_or_provenance_do_not_execute_backend_or_emit_ui_patch(
    arguments: Mapping[str, object],
    argument_provenance: Mapping[str, str],
    expected_missing: tuple[str, ...],
) -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([web_search_manifest()]),
        backend=backend,
    )

    result = executor.execute(
        _request(
            tool_call_id="tool_call_mvp2_slice4_websearch_blocked",
            tool_name="webSearch",
            caused_by_event_id=caused_by_event_id,
            event_id_prefix="evt_mvp2_slice4_websearch_blocked",
            idempotency_key="idem://synthetic/mvp2/slice4/websearch-blocked",
            arguments=arguments,
            argument_provenance=argument_provenance,
        )
    )

    assert [event["event_name"] for event in result.produced_events] == [
        "TOOL_MANIFEST_LOADED",
        "TOOL_ARGUMENTS_PARTIAL",
        "TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS",
    ]
    assert result.blocking_fields == expected_missing
    assert "TOOL_UI_STATE_PATCHED" not in [event["event_name"] for event in result.produced_events]
    assert backend.executed_calls == ()


@pytest.mark.parametrize("side_effect_class", BLOCKED_SIDE_EFFECT_CLASSES)
def test_blocked_side_effect_classes_do_not_execute_backend_or_emit_patch(side_effect_class: str) -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry(
            [alarm_create_manifest(side_effect_class=side_effect_class)],
            validate_side_effect_classes=False,
        ),
        backend=backend,
    )

    with pytest.raises(ToolExecutionPolicyError, match="side_effect_class is not allowed"):
        executor.execute(
            _request(
                tool_call_id="tool_call_mvp2_slice4_blocked_alarm",
                tool_name="alarm",
                caused_by_event_id=caused_by_event_id,
                event_id_prefix="evt_mvp2_slice4_blocked_alarm",
                idempotency_key=f"idem://synthetic/mvp2/slice4/{side_effect_class.lower()}",
                arguments={"time": "07:30", "timezone": "Etc/UTC", "label": "Synthetic alarm"},
                argument_provenance={
                    "time": "evt_mvp2_slice4_arguments_resolved",
                    "timezone": "evt_mvp2_slice4_arguments_resolved",
                    "label": "evt_mvp2_slice4_arguments_resolved",
                },
            )
        )

    assert not any(event["event_name"].startswith("TOOL_") for event in journal.events())
    assert backend.executed_calls == ()


def test_stale_plan_stale_cursor_and_terminal_task_do_not_execute_or_patch() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([flashlight_set_manifest()]),
        backend=backend,
    )

    with pytest.raises(ToolExecutionPolicyError, match="current plan_version"):
        executor.execute(
            _request(
                tool_call_id="tool_call_mvp2_slice4_stale_plan",
                tool_name="flashlight",
                caused_by_event_id=caused_by_event_id,
                event_id_prefix="evt_mvp2_slice4_stale_plan",
                current_plan_version=2,
                idempotency_key="idem://synthetic/mvp2/slice4/stale-plan",
                arguments={"state": "on"},
                argument_provenance={"state": "evt_mvp2_slice4_arguments_resolved"},
            )
        )
    with pytest.raises(ToolExecutionPolicyError, match="task_event_seq cursor"):
        executor.execute(
            _request(
                tool_call_id="tool_call_mvp2_slice4_stale_cursor",
                tool_name="flashlight",
                caused_by_event_id=caused_by_event_id,
                event_id_prefix="evt_mvp2_slice4_stale_cursor",
                start_task_event_seq=2,
                idempotency_key="idem://synthetic/mvp2/slice4/stale-cursor",
                arguments={"state": "on"},
                argument_provenance={"state": "evt_mvp2_slice4_arguments_resolved"},
            )
        )

    terminal = journal.append(
        event_name="SLOWTASK_STATE_CHANGED",
        event_id="evt_mvp2_slice4_state_completed",
        source_module="slowtask_runtime",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000060030,
        trace_redaction_level="metadata_only",
        task_id="task_mvp2_slice4",
        plan_version=1,
        task_event_seq=3,
        from_state="PLANNING",
        to_state="COMPLETED",
        reason="synthetic_completed",
    )
    with pytest.raises(ToolExecutionPolicyError, match="terminal SlowTask"):
        executor.execute(
            _request(
                tool_call_id="tool_call_mvp2_slice4_terminal",
                tool_name="flashlight",
                caused_by_event_id=str(terminal["event_id"]),
                event_id_prefix="evt_mvp2_slice4_terminal",
                start_task_event_seq=4,
                idempotency_key="idem://synthetic/mvp2/slice4/terminal",
                arguments={"state": "on"},
                argument_provenance={"state": "evt_mvp2_slice4_arguments_resolved"},
            )
        )

    assert not any(event["event_name"].startswith("TOOL_") for event in journal.events())
    assert backend.executed_calls == ()


def _started_journal() -> tuple[object, str]:
    startup = start_mvp0_session(
        session_id="sess_mvp2_slice4",
        conversation_id="conv_mvp2_slice4",
        runtime_config_ref="config://synthetic/mvp2/slice4",
        created_monotonic_ms=1,
        created_wall_clock_ms=1700000060001,
    )
    created = startup.journal.append(
        event_name="SLOWTASK_CREATED",
        event_id="evt_mvp2_slice4_slowtask_created",
        source_module="slowtask_runtime",
        caused_by_event_id=str(startup.journal.events()[-1]["event_id"]),
        created_monotonic_ms=10,
        created_wall_clock_ms=1700000060010,
        trace_redaction_level="metadata_only",
        task_id="task_mvp2_slice4",
        plan_version=1,
        task_event_seq=1,
        initial_goal_ref="goal://synthetic/mvp2/slice4/demo-tools",
        source_evidence_refs=["evidence://synthetic/mvp2/slice4/spawn"],
    )
    arguments_resolved = startup.journal.append(
        event_name="ARGUMENTS_RESOLVED",
        event_id="evt_mvp2_slice4_arguments_resolved",
        source_module="slowtask_runtime",
        caused_by_event_id=str(created["event_id"]),
        created_monotonic_ms=11,
        created_wall_clock_ms=1700000060011,
        trace_redaction_level="metadata_only",
        task_id="task_mvp2_slice4",
        plan_version=1,
        task_event_seq=2,
        resolved_arguments_ref="args://synthetic/mvp2/slice4/current-plan/ready",
        provenance_ref="provenance://synthetic/mvp2/slice4/current-plan/ready",
    )
    return startup.journal, str(arguments_resolved["event_id"])


def _request(
    *,
    tool_call_id: str,
    tool_name: str,
    caused_by_event_id: str,
    event_id_prefix: str,
    idempotency_key: str,
    arguments: Mapping[str, object],
    argument_provenance: Mapping[str, str],
    plan_version: int = 1,
    current_plan_version: int = 1,
    start_task_event_seq: int = 3,
    resolved_arguments_ref: str = "args://synthetic/mvp2/slice4/tool/ready",
    provenance_ref: str = "provenance://synthetic/mvp2/slice4/tool/ready",
) -> ToolExecutionRequest:
    return ToolExecutionRequest(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        task_id="task_mvp2_slice4",
        plan_version=plan_version,
        current_plan_version=current_plan_version,
        start_task_event_seq=start_task_event_seq,
        caused_by_event_id=caused_by_event_id,
        event_id_prefix=event_id_prefix,
        created_monotonic_ms=100,
        created_wall_clock_ms=1700000060100,
        idempotency_key=idempotency_key,
        arguments=arguments,
        argument_provenance=argument_provenance,
        resolved_arguments_ref=resolved_arguments_ref,
        provenance_ref=provenance_ref,
    )


def _expected_ui_patch_id(*, namespace: str, operation: str, idempotency_key: str) -> str:
    digest = sha256(f"{namespace}:{operation}:{idempotency_key}".encode("utf-8")).hexdigest()[:16]
    return f"ui_patch_{namespace}_{operation}_{digest}"
