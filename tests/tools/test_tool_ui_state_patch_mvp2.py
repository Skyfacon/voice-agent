from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256

import pytest

from voice_agent.demo_backend.in_memory import InMemoryDemoBackend
from voice_agent.runtime.session import start_mvp0_session
from voice_agent.tools.executor import DemoToolExecutor, ToolExecutionPolicyError, ToolExecutionRequest
from voice_agent.tools.manifest import BLOCKED_SIDE_EFFECT_CLASSES, ToolManifest
from voice_agent.tools.registry import ToolRegistry


def test_ui_capable_demo_tool_emits_patch_between_progress_and_result() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([_memo_manifest()]),
        backend=backend,
    )
    idempotency_key = "idem://synthetic/mvp2/slice3/memo-create"

    result = executor.execute(
        _memo_request(
            caused_by_event_id=caused_by_event_id,
            idempotency_key=idempotency_key,
            arguments={"body": "Buy synthetic milk"},
            argument_provenance={"body": "evt_mvp2_slice3_arguments_resolved"},
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
    progress = result.produced_events[4]
    patch = result.produced_events[5]
    received = result.produced_events[6]
    expected_patch_id = _expected_ui_patch_id(
        namespace="memo",
        operation="create",
        idempotency_key=idempotency_key,
    )
    assert patch["caused_by_event_id"] == progress["event_id"]
    assert received["caused_by_event_id"] == patch["event_id"]
    assert patch["ui_patch_id"] == expected_patch_id
    assert patch["idempotency_key"] == idempotency_key
    assert patch["patch_ref"] == f"patch://synthetic/demo_backend/memo/create/{expected_patch_id}"
    assert patch["tool_call_id"] == "tool_call_mvp2_slice3_memo"
    assert patch["task_id"] == "task_mvp2_slice3"
    assert patch["plan_version"] == 1
    assert [
        event["task_event_seq"]
        for event in result.produced_events
        if "task_event_seq" in event
    ] == [3, 4, 5, 6, 7, 8]
    assert all(event["source_module"] == "tool_executor" for event in result.produced_events)
    assert not any(event["event_name"] == "SLOWTASK_STATE_CHANGED" for event in result.produced_events)
    assert backend.executed_calls == (("memo", {"body": "Buy synthetic milk"}),)
    assert "Buy synthetic milk" not in repr(result.produced_events)
    assert "Buy synthetic milk" not in str(patch["patch_ref"])
    assert result.result_ref == "result://synthetic/demo_backend/memo/memo_write_000001"
    assert result.result_status == "SUCCEEDED"

    second_journal, second_caused_by_event_id = _started_journal()
    second_backend = InMemoryDemoBackend()
    second_executor = DemoToolExecutor(
        journal=second_journal,
        registry=ToolRegistry([_memo_manifest()]),
        backend=second_backend,
    )
    second = second_executor.execute(
        _memo_request(
            caused_by_event_id=second_caused_by_event_id,
            idempotency_key=idempotency_key,
            arguments={"body": "Different synthetic memo body"},
            argument_provenance={"body": "evt_mvp2_slice3_arguments_resolved"},
        )
    )
    second_patch = next(event for event in second.produced_events if event["event_name"] == "TOOL_UI_STATE_PATCHED")
    assert second_patch["ui_patch_id"] == patch["ui_patch_id"]
    assert second_patch["patch_ref"] == patch["patch_ref"]


def test_non_ui_capable_manifest_does_not_emit_patch_even_when_backend_returns_patch_metadata() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([_memo_manifest(ui_patch_capable=False)]),
        backend=backend,
    )

    result = executor.execute(
        _memo_request(
            caused_by_event_id=caused_by_event_id,
            event_id_prefix="evt_mvp2_slice3_memo_non_ui",
            tool_call_id="tool_call_mvp2_slice3_memo_non_ui",
            idempotency_key="idem://synthetic/mvp2/slice3/memo-non-ui",
            arguments={"body": "Synthetic memo hidden from patch refs"},
            argument_provenance={"body": "evt_mvp2_slice3_arguments_resolved"},
        )
    )

    event_names = [event["event_name"] for event in result.produced_events]
    assert "TOOL_UI_STATE_PATCHED" not in event_names
    assert event_names[-2:] == ["TOOL_PROGRESS_UPDATED", "TOOL_RESULT_RECEIVED"]
    assert result.produced_events[-1]["caused_by_event_id"] == result.produced_events[-2]["event_id"]
    assert backend.executed_calls == (("memo", {"body": "Synthetic memo hidden from patch refs"}),)


def test_ui_capable_manifest_fails_backend_patch_namespace_mismatch_before_patch_event() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([_memo_manifest(sandbox_state_namespace="alarm")]),
        backend=backend,
    )

    result = executor.execute(
        _memo_request(
            caused_by_event_id=caused_by_event_id,
            event_id_prefix="evt_mvp2_slice3_memo_namespace_mismatch",
            tool_call_id="tool_call_mvp2_slice3_memo_namespace_mismatch",
            idempotency_key="idem://synthetic/mvp2/slice3/memo-namespace-mismatch",
            arguments={"body": "Synthetic memo"},
            argument_provenance={"body": "evt_mvp2_slice3_arguments_resolved"},
        )
    )

    event_names = [event["event_name"] for event in result.produced_events]
    assert event_names == [
        "TOOL_MANIFEST_LOADED",
        "TOOL_ARGUMENTS_READY",
        "TOOL_EXECUTION_AUTHORIZED",
        "TOOL_EXECUTION_STARTED",
        "TOOL_EXECUTION_FAILED",
    ]
    assert "TOOL_PROGRESS_UPDATED" not in event_names
    assert "TOOL_UI_STATE_PATCHED" not in event_names
    assert "TOOL_RESULT_RECEIVED" not in event_names
    failure = result.produced_events[-1]
    assert failure["failure_reason"] == "demo_backend_ui_patch_namespace_mismatch"
    assert result.result_status == "FAILED"
    assert backend.executed_calls == ()

    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([_memo_manifest()]),
        backend=backend,
    )
    valid = executor.execute(
        _memo_request(
            caused_by_event_id=str(failure["event_id"]),
            event_id_prefix="evt_mvp2_slice3_memo_after_namespace_mismatch",
            tool_call_id="tool_call_mvp2_slice3_memo_after_namespace_mismatch",
            start_task_event_seq=7,
            idempotency_key="idem://synthetic/mvp2/slice3/memo-after-namespace-mismatch",
            arguments={"body": "Synthetic memo after failed namespace check"},
            argument_provenance={"body": "evt_mvp2_slice3_arguments_resolved"},
        )
    )
    assert valid.result_ref == "result://synthetic/demo_backend/memo/memo_write_000001"
    assert backend.executed_calls == (
        ("memo", {"body": "Synthetic memo after failed namespace check"}),
    )


@pytest.mark.parametrize(
    ("arguments", "argument_provenance", "expected_missing"),
    [
        ({}, {}, ("body",)),
        ({"body": "Synthetic memo"}, {}, ("provenance.body",)),
    ],
)
def test_missing_arguments_or_provenance_do_not_emit_patch_or_execute_backend(
    arguments: Mapping[str, object],
    argument_provenance: Mapping[str, str],
    expected_missing: tuple[str, ...],
) -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([_memo_manifest()]),
        backend=backend,
    )

    result = executor.execute(
        _memo_request(
            caused_by_event_id=caused_by_event_id,
            event_id_prefix="evt_mvp2_slice3_memo_blocked",
            tool_call_id="tool_call_mvp2_slice3_memo_blocked",
            idempotency_key="idem://synthetic/mvp2/slice3/memo-blocked",
            arguments=arguments,
            argument_provenance=argument_provenance,
        )
    )

    event_names = [event["event_name"] for event in result.produced_events]
    assert event_names == [
        "TOOL_MANIFEST_LOADED",
        "TOOL_ARGUMENTS_PARTIAL",
        "TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS",
    ]
    assert "TOOL_EXECUTION_STARTED" not in event_names
    assert "TOOL_UI_STATE_PATCHED" not in event_names
    assert result.blocking_fields == expected_missing
    assert backend.executed_calls == ()


@pytest.mark.parametrize("side_effect_class", BLOCKED_SIDE_EFFECT_CLASSES)
def test_blocked_side_effect_class_does_not_emit_patch_or_execute_backend(side_effect_class: str) -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry(
            [_memo_manifest(side_effect_class=side_effect_class)],
            validate_side_effect_classes=False,
        ),
        backend=backend,
    )

    with pytest.raises(ToolExecutionPolicyError, match="side_effect_class is not allowed"):
        executor.execute(
            _memo_request(
                caused_by_event_id=caused_by_event_id,
                idempotency_key=f"idem://synthetic/mvp2/slice3/{side_effect_class.lower()}",
                arguments={"body": "Synthetic memo"},
                argument_provenance={"body": "evt_mvp2_slice3_arguments_resolved"},
            )
        )

    assert not any(event["event_name"].startswith("TOOL_") for event in journal.events())
    assert backend.executed_calls == ()


def test_stale_plan_does_not_emit_patch_or_execute_backend() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([_memo_manifest()]),
        backend=backend,
    )

    with pytest.raises(ToolExecutionPolicyError, match="current plan_version"):
        executor.execute(
            _memo_request(
                caused_by_event_id=caused_by_event_id,
                plan_version=1,
                current_plan_version=2,
                idempotency_key="idem://synthetic/mvp2/slice3/stale-plan",
                arguments={"body": "Synthetic memo"},
                argument_provenance={"body": "evt_mvp2_slice3_arguments_resolved"},
            )
        )

    assert not any(event["event_name"].startswith("TOOL_") for event in journal.events())
    assert backend.executed_calls == ()


def test_stale_task_event_seq_does_not_emit_patch_or_execute_backend() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([_memo_manifest()]),
        backend=backend,
    )

    with pytest.raises(ToolExecutionPolicyError, match="task_event_seq cursor"):
        executor.execute(
            _memo_request(
                caused_by_event_id=caused_by_event_id,
                start_task_event_seq=2,
                idempotency_key="idem://synthetic/mvp2/slice3/stale-cursor",
                arguments={"body": "Synthetic memo"},
                argument_provenance={"body": "evt_mvp2_slice3_arguments_resolved"},
            )
        )

    assert not any(event["event_name"].startswith("TOOL_") for event in journal.events())
    assert backend.executed_calls == ()


def test_terminal_task_does_not_emit_patch_or_execute_backend() -> None:
    journal, caused_by_event_id = _started_journal()
    terminal = journal.append(
        event_name="SLOWTASK_STATE_CHANGED",
        event_id="evt_mvp2_slice3_state_completed",
        source_module="slowtask_runtime",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000050030,
        trace_redaction_level="metadata_only",
        task_id="task_mvp2_slice3",
        plan_version=1,
        task_event_seq=3,
        from_state="PLANNING",
        to_state="COMPLETED",
        reason="synthetic_completed",
    )
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([_memo_manifest()]),
        backend=backend,
    )

    with pytest.raises(ToolExecutionPolicyError, match="terminal SlowTask"):
        executor.execute(
            _memo_request(
                caused_by_event_id=str(terminal["event_id"]),
                start_task_event_seq=4,
                idempotency_key="idem://synthetic/mvp2/slice3/terminal",
                arguments={"body": "Synthetic memo"},
                argument_provenance={"body": "evt_mvp2_slice3_arguments_resolved"},
            )
        )

    assert not any(event["event_name"].startswith("TOOL_") for event in journal.events())
    assert backend.executed_calls == ()


def test_backend_failure_does_not_emit_ui_patch() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([_unsupported_ui_manifest()]),
        backend=backend,
    )

    result = executor.execute(
        ToolExecutionRequest(
            tool_call_id="tool_call_mvp2_slice3_unsupported",
            tool_name="unsupportedUi",
            task_id="task_mvp2_slice3",
            plan_version=1,
            current_plan_version=1,
            start_task_event_seq=3,
            caused_by_event_id=caused_by_event_id,
            event_id_prefix="evt_mvp2_slice3_unsupported",
            created_monotonic_ms=300,
            created_wall_clock_ms=1700000050300,
            idempotency_key="idem://synthetic/mvp2/slice3/unsupported",
            arguments={"query": "synthetic"},
            argument_provenance={"query": "evt_mvp2_slice3_arguments_resolved"},
            resolved_arguments_ref="args://synthetic/mvp2/slice3/unsupported/ready",
            provenance_ref="provenance://synthetic/mvp2/slice3/unsupported/ready",
        )
    )

    event_names = [event["event_name"] for event in result.produced_events]
    assert event_names[-2:] == ["TOOL_EXECUTION_STARTED", "TOOL_EXECUTION_FAILED"]
    assert "TOOL_UI_STATE_PATCHED" not in event_names
    assert "TOOL_RESULT_RECEIVED" not in event_names
    assert backend.executed_calls == ()


def _started_journal() -> tuple[object, str]:
    startup = start_mvp0_session(
        session_id="sess_mvp2_slice3",
        conversation_id="conv_mvp2_slice3",
        runtime_config_ref="config://synthetic/mvp2/slice3",
        created_monotonic_ms=1,
        created_wall_clock_ms=1700000050001,
    )
    created = startup.journal.append(
        event_name="SLOWTASK_CREATED",
        event_id="evt_mvp2_slice3_slowtask_created",
        source_module="slowtask_runtime",
        caused_by_event_id=str(startup.journal.events()[-1]["event_id"]),
        created_monotonic_ms=10,
        created_wall_clock_ms=1700000050010,
        trace_redaction_level="metadata_only",
        task_id="task_mvp2_slice3",
        plan_version=1,
        task_event_seq=1,
        initial_goal_ref="goal://synthetic/mvp2/slice3/tool-ui-state-patch",
        source_evidence_refs=["evidence://synthetic/mvp2/slice3/spawn"],
    )
    arguments_resolved = startup.journal.append(
        event_name="ARGUMENTS_RESOLVED",
        event_id="evt_mvp2_slice3_arguments_resolved",
        source_module="slowtask_runtime",
        caused_by_event_id=str(created["event_id"]),
        created_monotonic_ms=11,
        created_wall_clock_ms=1700000050011,
        trace_redaction_level="metadata_only",
        task_id="task_mvp2_slice3",
        plan_version=1,
        task_event_seq=2,
        resolved_arguments_ref="args://synthetic/mvp2/slice3/current-plan/ready",
        provenance_ref="provenance://synthetic/mvp2/slice3/current-plan/ready",
    )
    return startup.journal, str(arguments_resolved["event_id"])


def _memo_request(
    *,
    caused_by_event_id: str,
    idempotency_key: str,
    arguments: Mapping[str, object],
    argument_provenance: Mapping[str, str],
    tool_call_id: str = "tool_call_mvp2_slice3_memo",
    event_id_prefix: str = "evt_mvp2_slice3_memo",
    plan_version: int = 1,
    current_plan_version: int = 1,
    start_task_event_seq: int = 3,
) -> ToolExecutionRequest:
    return ToolExecutionRequest(
        tool_call_id=tool_call_id,
        tool_name="memo",
        task_id="task_mvp2_slice3",
        plan_version=plan_version,
        current_plan_version=current_plan_version,
        start_task_event_seq=start_task_event_seq,
        caused_by_event_id=caused_by_event_id,
        event_id_prefix=event_id_prefix,
        created_monotonic_ms=100,
        created_wall_clock_ms=1700000050100,
        idempotency_key=idempotency_key,
        arguments=arguments,
        argument_provenance=argument_provenance,
        resolved_arguments_ref="args://synthetic/mvp2/slice3/memo/ready",
        provenance_ref="provenance://synthetic/mvp2/slice3/memo/ready",
    )


def _memo_manifest(
    *,
    side_effect_class: str = "SANDBOX_WRITE",
    ui_patch_capable: bool = True,
    sandbox_state_namespace: str = "memo",
) -> ToolManifest:
    return ToolManifest(
        tool_name="memo",
        tool_adapter_id="demo.memo",
        tool_manifest_version="2026-05-18.slice3",
        tool_category="DEMO_STATE_WRITE",
        side_effect_class=side_effect_class,
        risk_class="LOW",
        required_arguments=("body",),
        optional_arguments=(),
        argument_provenance_requirements=("body",),
        result_type="memo_write",
        trust_level="TRUSTED_DEMO_TOOL_RESULT",
        source_type="DEMO_SANDBOX",
        preview_required=False,
        confirmation_required=False,
        ui_patch_capable=ui_patch_capable,
        idempotency_required=True,
        sandbox_state_namespace=sandbox_state_namespace,
        capability="mock",
    )


def _unsupported_ui_manifest() -> ToolManifest:
    return ToolManifest(
        tool_name="unsupportedUi",
        tool_adapter_id="demo.unsupported_ui",
        tool_manifest_version="2026-05-18.slice3",
        tool_category="DEMO_STATE_WRITE",
        side_effect_class="SANDBOX_WRITE",
        risk_class="LOW",
        required_arguments=("query",),
        optional_arguments=(),
        argument_provenance_requirements=("query",),
        result_type="unsupported_ui",
        trust_level="TRUSTED_DEMO_TOOL_RESULT",
        source_type="DEMO_SANDBOX",
        preview_required=False,
        confirmation_required=False,
        ui_patch_capable=True,
        idempotency_required=True,
        sandbox_state_namespace="unsupported",
        capability="mock",
    )


def _expected_ui_patch_id(*, namespace: str, operation: str, idempotency_key: str) -> str:
    digest = sha256(f"{namespace}:{operation}:{idempotency_key}".encode("utf-8")).hexdigest()[:16]
    return f"ui_patch_{namespace}_{operation}_{digest}"
