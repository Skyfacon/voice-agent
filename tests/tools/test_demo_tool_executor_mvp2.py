from __future__ import annotations

from collections.abc import Mapping

import pytest

from voice_agent.demo_backend.in_memory import InMemoryDemoBackend
from voice_agent.runtime.session import start_mvp0_session
from voice_agent.tools.executor import DemoToolExecutor, ToolExecutionPolicyError, ToolExecutionRequest
from voice_agent.tools.manifest import (
    BLOCKED_SIDE_EFFECT_CLASSES,
    MVP_ALLOWED_SIDE_EFFECT_CLASSES,
    ToolManifest,
)
from voice_agent.tools.registry import ToolRegistry


def test_read_only_demo_tool_emits_progressive_events_without_slowtask_mutation() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([_weather_manifest()]),
        backend=backend,
    )

    result = executor.execute(
        ToolExecutionRequest(
            tool_call_id="tool_call_mvp2_slice2_weather",
            tool_name="weather",
            task_id="task_mvp2_slice2",
            plan_version=1,
            current_plan_version=1,
            start_task_event_seq=3,
            caused_by_event_id=caused_by_event_id,
            event_id_prefix="evt_mvp2_slice2_weather",
            created_monotonic_ms=100,
            created_wall_clock_ms=1700000040100,
            idempotency_key="idem://synthetic/mvp2/slice2/weather",
            arguments={"location": "Testville", "date": "2026-05-17"},
            argument_provenance={
                "location": "evt_mvp2_slice2_arguments_resolved",
                "date": "evt_mvp2_slice2_arguments_resolved",
            },
            resolved_arguments_ref="args://synthetic/mvp2/slice2/weather/ready",
            provenance_ref="provenance://synthetic/mvp2/slice2/weather/ready",
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
        "TOOL_RESULT_RECEIVED",
    ]
    assert "TOOL_UI_STATE_PATCHED" not in event_names
    assert "WAITING_FOR_TOOL" not in event_names
    assert all(event["source_module"] == "tool_executor" for event in result.produced_events)
    assert [
        event["task_event_seq"]
        for event in result.produced_events
        if "task_event_seq" in event
    ] == [3, 4, 5, 6, 7, 8]
    assert _task_bindings(result.produced_events) == {
        ("task_mvp2_slice2", 1, "tool_call_mvp2_slice2_weather")
    }

    manifest_event = result.produced_events[0]
    assert manifest_event["tool_category"] == "READ_ONLY_EXTERNAL"
    assert manifest_event["side_effect_class"] == "READ_ONLY"
    assert manifest_event["trust_level"] == "EXTERNAL_READ_PROVIDER_RESULT"
    assert manifest_event["execution_mode"] == "demo_sandbox"
    assert manifest_event["capability"] == "mock"

    authorized = result.produced_events[3]
    started = result.produced_events[4]
    assert authorized["authorization_basis"] == "current_plan_policy_allow"
    assert started["authorization_event_id"] == authorized["event_id"]

    result_event = result.produced_events[-1]
    assert result_event["result_status"] == "SUCCEEDED"
    assert result_event["result_ref"] == "result://synthetic/demo_backend/weather/weather_lookup_000001"
    assert result_event["trust_level"] == "EXTERNAL_READ_PROVIDER_RESULT"
    assert result_event["source_type"] == "READ_ONLY_EXTERNAL"
    assert backend.executed_calls == (("weather", {"date": "2026-05-17", "location": "Testville"}),)
    assert "Testville" not in repr(result.produced_events)
    assert "/2026-05-17" not in repr(result.produced_events)


def test_executor_rejects_reused_idempotency_key_before_backend_execution() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([_weather_manifest()]),
        backend=backend,
    )

    first = executor.execute(
        ToolExecutionRequest(
            tool_call_id="tool_call_mvp2_slice2_weather",
            tool_name="weather",
            task_id="task_mvp2_slice2",
            plan_version=1,
            current_plan_version=1,
            start_task_event_seq=3,
            caused_by_event_id=caused_by_event_id,
            event_id_prefix="evt_mvp2_slice2_weather",
            created_monotonic_ms=100,
            created_wall_clock_ms=1700000040100,
            idempotency_key="idem://synthetic/mvp2/slice2/weather",
            arguments={"location": "Testville", "date": "2026-05-17"},
            argument_provenance={
                "location": "evt_mvp2_slice2_arguments_resolved",
                "date": "evt_mvp2_slice2_arguments_resolved",
            },
            resolved_arguments_ref="args://synthetic/mvp2/slice2/weather/ready",
            provenance_ref="provenance://synthetic/mvp2/slice2/weather/ready",
        )
    )
    last_event = first.produced_events[-1]

    with pytest.raises(ToolExecutionPolicyError, match="idempotency_key"):
        executor.execute(
            ToolExecutionRequest(
                tool_call_id="tool_call_mvp2_slice2_weather_retry",
                tool_name="weather",
                task_id="task_mvp2_slice2",
                plan_version=1,
                current_plan_version=1,
                start_task_event_seq=9,
                caused_by_event_id=str(last_event["event_id"]),
                event_id_prefix="evt_mvp2_slice2_weather_retry",
                created_monotonic_ms=200,
                created_wall_clock_ms=1700000040200,
                idempotency_key="idem://synthetic/mvp2/slice2/weather",
                arguments={"location": "Testville", "date": "2026-05-17"},
                argument_provenance={
                    "location": "evt_mvp2_slice2_arguments_resolved",
                    "date": "evt_mvp2_slice2_arguments_resolved",
                },
                resolved_arguments_ref="args://synthetic/mvp2/slice2/weather/retry-ready",
                provenance_ref="provenance://synthetic/mvp2/slice2/weather/retry-ready",
            )
        )

    assert backend.executed_calls == (("weather", {"date": "2026-05-17", "location": "Testville"}),)
    assert [
        event["event_name"]
        for event in journal.events()
        if event["event_name"] == "TOOL_EXECUTION_STARTED"
    ] == ["TOOL_EXECUTION_STARTED"]
    assert not any(
        event["event_id"].startswith("evt_mvp2_slice2_weather_retry")
        for event in journal.events()
    )


@pytest.mark.parametrize(
    ("arguments", "argument_provenance", "expected_missing"),
    [
        ({}, {}, ("location", "date")),
        (
            {"location": "Testville", "date": "2026-05-17"},
            {"location": "evt_mvp2_slice2_arguments_resolved"},
            ("provenance.date",),
        ),
    ],
)
def test_missing_arguments_or_provenance_emit_partial_and_blocked_without_execution(
    arguments: Mapping[str, object],
    argument_provenance: Mapping[str, str],
    expected_missing: tuple[str, ...],
) -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([_weather_manifest()]),
        backend=backend,
    )

    result = executor.execute(
        ToolExecutionRequest(
            tool_call_id="tool_call_mvp2_slice2_blocked",
            tool_name="weather",
            task_id="task_mvp2_slice2",
            plan_version=1,
            current_plan_version=1,
            start_task_event_seq=10,
            caused_by_event_id=caused_by_event_id,
            event_id_prefix="evt_mvp2_slice2_blocked",
            created_monotonic_ms=200,
            created_wall_clock_ms=1700000040200,
            idempotency_key="idem://synthetic/mvp2/slice2/blocked",
            arguments=arguments,
            argument_provenance=argument_provenance,
            resolved_arguments_ref="args://synthetic/mvp2/slice2/blocked/ready",
            provenance_ref="provenance://synthetic/mvp2/slice2/blocked/ready",
        )
    )

    event_names = [event["event_name"] for event in result.produced_events]
    assert event_names == [
        "TOOL_MANIFEST_LOADED",
        "TOOL_ARGUMENTS_PARTIAL",
        "TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS",
    ]
    assert "TOOL_ARGUMENTS_READY" not in event_names
    assert "TOOL_EXECUTION_AUTHORIZED" not in event_names
    assert "TOOL_EXECUTION_STARTED" not in event_names
    assert backend.executed_calls == ()

    partial = result.produced_events[1]
    blocked = result.produced_events[2]
    assert tuple(partial["missing_fields"]) == expected_missing
    assert tuple(blocked["blocking_fields"]) == expected_missing
    assert blocked["source_event_id"] == partial["event_id"]
    assert blocked["caused_by_event_id"] == partial["event_id"]


def test_side_effect_class_gate_allows_only_mvp_demo_classes() -> None:
    for side_effect_class in MVP_ALLOWED_SIDE_EFFECT_CLASSES:
        ToolRegistry([_weather_manifest(side_effect_class=side_effect_class)])

    for side_effect_class in BLOCKED_SIDE_EFFECT_CLASSES:
        with pytest.raises(ToolExecutionPolicyError, match="side_effect_class is not allowed"):
            ToolRegistry([_weather_manifest(side_effect_class=side_effect_class)])


def test_registry_rejects_same_version_manifest_conflicts() -> None:
    ToolRegistry([_weather_manifest(), _weather_manifest()])

    with pytest.raises(ToolExecutionPolicyError, match="conflicting manifest fields"):
        ToolRegistry([_weather_manifest(), _weather_manifest(confirmation_required=True)])


def test_executor_refuses_blocked_manifest_before_journal_or_backend_execution() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry(
            [_weather_manifest(side_effect_class="EXTERNAL_WRITE")],
            validate_side_effect_classes=False,
        ),
        backend=backend,
    )

    with pytest.raises(ToolExecutionPolicyError, match="side_effect_class is not allowed"):
        executor.execute(
            ToolExecutionRequest(
                tool_call_id="tool_call_mvp2_slice2_external_write",
                tool_name="weather",
                task_id="task_mvp2_slice2",
                plan_version=1,
                current_plan_version=1,
                start_task_event_seq=3,
                caused_by_event_id=caused_by_event_id,
                event_id_prefix="evt_mvp2_slice2_external_write",
                created_monotonic_ms=300,
                created_wall_clock_ms=1700000040300,
                idempotency_key="idem://synthetic/mvp2/slice2/external-write",
                arguments={"location": "Testville", "date": "2026-05-17"},
                argument_provenance={
                    "location": "evt_mvp2_slice2_arguments_resolved",
                    "date": "evt_mvp2_slice2_arguments_resolved",
                },
                resolved_arguments_ref="args://synthetic/mvp2/slice2/external-write/ready",
                provenance_ref="provenance://synthetic/mvp2/slice2/external-write/ready",
            )
        )

    assert not any(event["event_name"].startswith("TOOL_") for event in journal.events())
    assert backend.executed_calls == ()


def test_stale_plan_request_is_rejected_before_journal_or_backend_execution() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([_weather_manifest()]),
        backend=backend,
    )

    with pytest.raises(ToolExecutionPolicyError, match="current plan_version"):
        executor.execute(
            ToolExecutionRequest(
                tool_call_id="tool_call_mvp2_slice2_stale",
                tool_name="weather",
                task_id="task_mvp2_slice2",
                plan_version=1,
                current_plan_version=2,
                start_task_event_seq=1,
                caused_by_event_id=caused_by_event_id,
                event_id_prefix="evt_mvp2_slice2_stale",
                created_monotonic_ms=350,
                created_wall_clock_ms=1700000040350,
                idempotency_key="idem://synthetic/mvp2/slice2/stale",
                arguments={"location": "Testville", "date": "2026-05-17"},
                argument_provenance={
                    "location": "evt_mvp2_slice2_arguments_resolved",
                    "date": "evt_mvp2_slice2_arguments_resolved",
                },
                resolved_arguments_ref="args://synthetic/mvp2/slice2/stale/ready",
                provenance_ref="provenance://synthetic/mvp2/slice2/stale/ready",
            )
        )

    assert not any(event["event_name"].startswith("TOOL_") for event in journal.events())
    assert backend.executed_calls == ()


def test_request_created_before_plan_advance_is_rejected_against_journal_current_plan() -> None:
    journal, caused_by_event_id = _started_journal()
    advanced = _advance_journal_to_plan_2(journal, caused_by_event_id)
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([_weather_manifest()]),
        backend=backend,
    )

    with pytest.raises(ToolExecutionPolicyError, match="journal current plan_version"):
        executor.execute(
            ToolExecutionRequest(
                tool_call_id="tool_call_mvp2_slice2_stale_snapshot",
                tool_name="weather",
                task_id="task_mvp2_slice2",
                plan_version=1,
                current_plan_version=1,
                start_task_event_seq=4,
                caused_by_event_id=str(advanced["event_id"]),
                event_id_prefix="evt_mvp2_slice2_stale_snapshot",
                created_monotonic_ms=355,
                created_wall_clock_ms=1700000040355,
                idempotency_key="idem://synthetic/mvp2/slice2/stale-snapshot",
                arguments={"location": "Testville", "date": "2026-05-17"},
                argument_provenance={
                    "location": "evt_mvp2_slice2_arguments_resolved",
                    "date": "evt_mvp2_slice2_arguments_resolved",
                },
                resolved_arguments_ref="args://synthetic/mvp2/slice2/stale-snapshot/ready",
                provenance_ref="provenance://synthetic/mvp2/slice2/stale-snapshot/ready",
            )
        )

    assert "TOOL_EXECUTION_STARTED" not in [event["event_name"] for event in journal.events()]
    assert backend.executed_calls == ()


def test_stale_task_event_seq_is_rejected_before_journal_or_backend_execution() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([_weather_manifest()]),
        backend=backend,
    )

    with pytest.raises(ToolExecutionPolicyError, match="task_event_seq cursor"):
        executor.execute(
            ToolExecutionRequest(
                tool_call_id="tool_call_mvp2_slice2_old_cursor",
                tool_name="weather",
                task_id="task_mvp2_slice2",
                plan_version=1,
                current_plan_version=1,
                start_task_event_seq=2,
                caused_by_event_id=caused_by_event_id,
                event_id_prefix="evt_mvp2_slice2_old_cursor",
                created_monotonic_ms=355,
                created_wall_clock_ms=1700000040355,
                idempotency_key="idem://synthetic/mvp2/slice2/old-cursor",
                arguments={"location": "Testville", "date": "2026-05-17"},
                argument_provenance={
                    "location": "evt_mvp2_slice2_arguments_resolved",
                    "date": "evt_mvp2_slice2_arguments_resolved",
                },
                resolved_arguments_ref="args://synthetic/mvp2/slice2/old-cursor/ready",
                provenance_ref="provenance://synthetic/mvp2/slice2/old-cursor/ready",
            )
        )

    assert not any(event["event_name"].startswith("TOOL_") for event in journal.events())
    assert backend.executed_calls == ()


def test_terminal_task_is_rejected_before_tool_events_or_backend_execution() -> None:
    journal, caused_by_event_id = _started_journal()
    terminal = journal.append(
        event_name="SLOWTASK_STATE_CHANGED",
        event_id="evt_mvp2_slice2_state_completed",
        source_module="slowtask_runtime",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000040030,
        trace_redaction_level="metadata_only",
        task_id="task_mvp2_slice2",
        plan_version=1,
        task_event_seq=3,
        from_state="CREATED",
        to_state="COMPLETED",
        reason="synthetic_completed",
    )
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([_weather_manifest()]),
        backend=backend,
    )

    with pytest.raises(ToolExecutionPolicyError, match="terminal SlowTask"):
        executor.execute(
            ToolExecutionRequest(
                tool_call_id="tool_call_mvp2_slice2_terminal",
                tool_name="weather",
                task_id="task_mvp2_slice2",
                plan_version=1,
                current_plan_version=1,
                start_task_event_seq=4,
                caused_by_event_id=str(terminal["event_id"]),
                event_id_prefix="evt_mvp2_slice2_terminal",
                created_monotonic_ms=356,
                created_wall_clock_ms=1700000040356,
                idempotency_key="idem://synthetic/mvp2/slice2/terminal",
                arguments={"location": "Testville", "date": "2026-05-17"},
                argument_provenance={
                    "location": "evt_mvp2_slice2_arguments_resolved",
                    "date": "evt_mvp2_slice2_arguments_resolved",
                },
                resolved_arguments_ref="args://synthetic/mvp2/slice2/terminal/ready",
                provenance_ref="provenance://synthetic/mvp2/slice2/terminal/ready",
            )
        )

    assert not any(event["event_name"].startswith("TOOL_") for event in journal.events())
    assert backend.executed_calls == ()


def test_unjournaled_argument_provenance_blocks_before_arguments_ready() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([_weather_manifest()]),
        backend=backend,
    )

    result = executor.execute(
        ToolExecutionRequest(
            tool_call_id="tool_call_mvp2_slice2_unjournaled_provenance",
            tool_name="weather",
            task_id="task_mvp2_slice2",
            plan_version=1,
            current_plan_version=1,
            start_task_event_seq=3,
            caused_by_event_id=caused_by_event_id,
            event_id_prefix="evt_mvp2_slice2_unjournaled_provenance",
            created_monotonic_ms=356,
            created_wall_clock_ms=1700000040356,
            idempotency_key="idem://synthetic/mvp2/slice2/unjournaled-provenance",
            arguments={"location": "Testville", "date": "2026-05-17"},
            argument_provenance={
                "location": "evt_missing_argument_evidence",
                "date": "evt_mvp2_slice2_arguments_resolved",
            },
            resolved_arguments_ref="args://synthetic/mvp2/slice2/unjournaled-provenance/ready",
            provenance_ref="provenance://synthetic/mvp2/slice2/unjournaled-provenance/ready",
        )
    )

    event_names = [event["event_name"] for event in result.produced_events]
    assert event_names == [
        "TOOL_MANIFEST_LOADED",
        "TOOL_ARGUMENTS_PARTIAL",
        "TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS",
    ]
    assert result.blocking_fields == ("provenance.location",)
    assert backend.executed_calls == ()


def test_old_plan_argument_provenance_blocks_without_adoption() -> None:
    journal, caused_by_event_id = _started_journal()
    advanced = _advance_journal_to_plan_2(journal, caused_by_event_id)
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([_weather_manifest()]),
        backend=backend,
    )

    result = executor.execute(
        ToolExecutionRequest(
            tool_call_id="tool_call_mvp2_slice2_old_plan_provenance",
            tool_name="weather",
            task_id="task_mvp2_slice2",
            plan_version=2,
            current_plan_version=2,
            start_task_event_seq=4,
            caused_by_event_id=str(advanced["event_id"]),
            event_id_prefix="evt_mvp2_slice2_old_plan_provenance",
            created_monotonic_ms=357,
            created_wall_clock_ms=1700000040357,
            idempotency_key="idem://synthetic/mvp2/slice2/old-plan-provenance",
            arguments={"location": "Testville", "date": "2026-05-17"},
            argument_provenance={
                "location": "evt_mvp2_slice2_arguments_resolved",
                "date": "evt_mvp2_slice2_arguments_resolved",
            },
            resolved_arguments_ref="args://synthetic/mvp2/slice2/old-plan-provenance/ready",
            provenance_ref="provenance://synthetic/mvp2/slice2/old-plan-provenance/ready",
        )
    )

    event_names = [event["event_name"] for event in result.produced_events]
    assert "TOOL_ARGUMENTS_READY" not in event_names
    assert "TOOL_EXECUTION_STARTED" not in event_names
    assert result.blocking_fields == ("provenance.location", "provenance.date")
    assert backend.executed_calls == ()


def test_stale_evidence_adoption_is_not_argument_level_provenance() -> None:
    journal, caused_by_event_id = _started_journal()
    adopted = journal.append(
        event_name="STALE_EVIDENCE_ADOPTED",
        event_id="evt_mvp2_slice2_stale_evidence_adopted",
        source_module="slowtask_runtime",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=358,
        created_wall_clock_ms=1700000040358,
        trace_redaction_level="metadata_only",
        task_id="task_mvp2_slice2",
        plan_version=1,
        task_event_seq=3,
        stale_evidence_ref="stale://synthetic/mvp2/slice2/adopted",
        source_tool_result_event_id="evt_mvp2_slice2_old_tool_result",
        adopted_from_plan_version=0,
        adoption_reason="synthetic_stale_evidence_reviewed",
        adopted_scope="evidence_only",
        adopted_by_event_id=caused_by_event_id,
        adoption_mode="adopt_or_rebase",
    )
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([_weather_manifest()]),
        backend=backend,
    )

    result = executor.execute(
        ToolExecutionRequest(
            tool_call_id="tool_call_mvp2_slice2_adoption_provenance",
            tool_name="weather",
            task_id="task_mvp2_slice2",
            plan_version=1,
            current_plan_version=1,
            start_task_event_seq=4,
            caused_by_event_id=str(adopted["event_id"]),
            event_id_prefix="evt_mvp2_slice2_adoption_provenance",
            created_monotonic_ms=359,
            created_wall_clock_ms=1700000040359,
            idempotency_key="idem://synthetic/mvp2/slice2/adoption-provenance",
            arguments={"location": "Testville", "date": "2026-05-17"},
            argument_provenance={
                "location": "evt_mvp2_slice2_stale_evidence_adopted",
                "date": "evt_mvp2_slice2_stale_evidence_adopted",
            },
            resolved_arguments_ref="args://synthetic/mvp2/slice2/adoption-provenance/ready",
            provenance_ref="provenance://synthetic/mvp2/slice2/adoption-provenance/ready",
        )
    )

    event_names = [event["event_name"] for event in result.produced_events]
    assert "TOOL_ARGUMENTS_READY" not in event_names
    assert "TOOL_EXECUTION_STARTED" not in event_names
    assert result.blocking_fields == ("provenance.location", "provenance.date")
    assert backend.executed_calls == ()


def test_confirmation_required_manifest_does_not_authorize_without_current_plan_confirmation() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([_weather_manifest(confirmation_required=True)]),
        backend=backend,
    )

    with pytest.raises(ToolExecutionPolicyError, match="current-plan CONFIRMATION_ACCEPTED"):
        executor.execute(
            ToolExecutionRequest(
                tool_call_id="tool_call_mvp2_slice2_confirmation_required",
                tool_name="weather",
                task_id="task_mvp2_slice2",
                plan_version=1,
                current_plan_version=1,
                start_task_event_seq=3,
                caused_by_event_id=caused_by_event_id,
                event_id_prefix="evt_mvp2_slice2_confirmation_required",
                created_monotonic_ms=360,
                created_wall_clock_ms=1700000040360,
                idempotency_key="idem://synthetic/mvp2/slice2/confirmation-required",
                arguments={"location": "Testville", "date": "2026-05-17"},
                argument_provenance={
                    "location": "evt_mvp2_slice2_arguments_resolved",
                    "date": "evt_mvp2_slice2_arguments_resolved",
                },
                resolved_arguments_ref="args://synthetic/mvp2/slice2/confirmation-required/ready",
                provenance_ref="provenance://synthetic/mvp2/slice2/confirmation-required/ready",
            )
        )

    event_names = [event["event_name"] for event in journal.events()]
    assert "TOOL_PREVIEW_AVAILABLE" in event_names
    assert "TOOL_EXECUTION_AUTHORIZED" not in event_names
    assert "TOOL_EXECUTION_STARTED" not in event_names
    assert backend.executed_calls == ()


def test_confirmation_required_manifest_authorizes_only_recorded_current_plan_confirmation() -> None:
    journal, caused_by_event_id = _started_journal()
    confirmation = _append_confirmation_chain(
        journal,
        caused_by_event_id=caused_by_event_id,
        confirmation_id="confirmation_mvp2_slice2_weather",
        confirmation_scope="FINAL_ARGUMENT_CONFIRMATION",
        start_task_event_seq=3,
    )
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([_weather_manifest(confirmation_required=True)]),
        backend=backend,
    )

    result = executor.execute(
        ToolExecutionRequest(
            tool_call_id="tool_call_mvp2_slice2_confirmation_accepted",
            tool_name="weather",
            task_id="task_mvp2_slice2",
            plan_version=1,
            current_plan_version=1,
            start_task_event_seq=8,
            caused_by_event_id=caused_by_event_id,
            event_id_prefix="evt_mvp2_slice2_confirmation_accepted_tool",
            created_monotonic_ms=370,
            created_wall_clock_ms=1700000040370,
            idempotency_key="idem://synthetic/mvp2/slice2/confirmation-accepted",
            arguments={"location": "Testville", "date": "2026-05-17"},
            argument_provenance={
                "location": "evt_mvp2_slice2_arguments_resolved",
                "date": "evt_mvp2_slice2_arguments_resolved",
            },
            resolved_arguments_ref="args://synthetic/mvp2/slice2/confirmation-accepted/ready",
            provenance_ref="provenance://synthetic/mvp2/slice2/confirmation-accepted/ready",
            accepted_confirmation_event_id=str(confirmation["event_id"]),
            accepted_confirmation_id="confirmation_mvp2_slice2_weather",
            accepted_confirmation_scope="FINAL_ARGUMENT_CONFIRMATION",
            accepted_confirmation_plan_version=1,
        )
    )

    authorized = next(
        event for event in result.produced_events if event["event_name"] == "TOOL_EXECUTION_AUTHORIZED"
    )
    assert authorized["authorization_basis"] == "current_plan_confirmation_acceptance"
    assert authorized["confirmation_id"] == "confirmation_mvp2_slice2_weather"
    assert authorized["caused_by_event_id"] == confirmation["event_id"]
    assert "TOOL_EXECUTION_STARTED" in [event["event_name"] for event in result.produced_events]
    assert backend.executed_calls == (("weather", {"date": "2026-05-17", "location": "Testville"}),)


def test_confirmation_required_manifest_rejects_confirmation_for_different_trigger() -> None:
    journal, caused_by_event_id = _started_journal()
    confirmation = _append_confirmation_chain(
        journal,
        caused_by_event_id=caused_by_event_id,
        confirmation_id="confirmation_mvp2_slice2_weather_wrong_trigger",
        confirmation_scope="FINAL_ARGUMENT_CONFIRMATION",
        start_task_event_seq=3,
        required_for_event_id="evt_mvp2_slice2_unrelated_tool_trigger",
    )
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([_weather_manifest(confirmation_required=True)]),
        backend=backend,
    )

    with pytest.raises(ToolExecutionPolicyError, match="current-plan CONFIRMATION_ACCEPTED"):
        executor.execute(
            ToolExecutionRequest(
                tool_call_id="tool_call_mvp2_slice2_wrong_trigger_confirmation",
                tool_name="weather",
                task_id="task_mvp2_slice2",
                plan_version=1,
                current_plan_version=1,
                start_task_event_seq=8,
                caused_by_event_id=caused_by_event_id,
                event_id_prefix="evt_mvp2_slice2_wrong_trigger_confirmation",
                created_monotonic_ms=371,
                created_wall_clock_ms=1700000040371,
                idempotency_key="idem://synthetic/mvp2/slice2/wrong-trigger-confirmation",
                arguments={"location": "Testville", "date": "2026-05-17"},
                argument_provenance={
                    "location": "evt_mvp2_slice2_arguments_resolved",
                    "date": "evt_mvp2_slice2_arguments_resolved",
                },
                resolved_arguments_ref="args://synthetic/mvp2/slice2/wrong-trigger-confirmation/ready",
                provenance_ref="provenance://synthetic/mvp2/slice2/wrong-trigger-confirmation/ready",
                accepted_confirmation_event_id=str(confirmation["event_id"]),
                accepted_confirmation_id="confirmation_mvp2_slice2_weather_wrong_trigger",
                accepted_confirmation_scope="FINAL_ARGUMENT_CONFIRMATION",
                accepted_confirmation_plan_version=1,
            )
        )

    assert "TOOL_EXECUTION_STARTED" not in [event["event_name"] for event in journal.events()]
    assert backend.executed_calls == ()


def test_confirmation_required_manifest_rejects_broken_confirmation_causal_chain() -> None:
    journal, caused_by_event_id = _started_journal()
    confirmation = _append_confirmation_chain(
        journal,
        caused_by_event_id=caused_by_event_id,
        confirmation_id="confirmation_mvp2_slice2_weather_broken_chain",
        confirmation_scope="FINAL_ARGUMENT_CONFIRMATION",
        start_task_event_seq=3,
        patch_caused_by_event_id=caused_by_event_id,
    )
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([_weather_manifest(confirmation_required=True)]),
        backend=backend,
    )

    with pytest.raises(ToolExecutionPolicyError, match="current-plan CONFIRMATION_ACCEPTED"):
        executor.execute(
            ToolExecutionRequest(
                tool_call_id="tool_call_mvp2_slice2_broken_chain_confirmation",
                tool_name="weather",
                task_id="task_mvp2_slice2",
                plan_version=1,
                current_plan_version=1,
                start_task_event_seq=8,
                caused_by_event_id=caused_by_event_id,
                event_id_prefix="evt_mvp2_slice2_broken_chain_confirmation",
                created_monotonic_ms=372,
                created_wall_clock_ms=1700000040372,
                idempotency_key="idem://synthetic/mvp2/slice2/broken-chain-confirmation",
                arguments={"location": "Testville", "date": "2026-05-17"},
                argument_provenance={
                    "location": "evt_mvp2_slice2_arguments_resolved",
                    "date": "evt_mvp2_slice2_arguments_resolved",
                },
                resolved_arguments_ref="args://synthetic/mvp2/slice2/broken-chain-confirmation/ready",
                provenance_ref="provenance://synthetic/mvp2/slice2/broken-chain-confirmation/ready",
                accepted_confirmation_event_id=str(confirmation["event_id"]),
                accepted_confirmation_id="confirmation_mvp2_slice2_weather_broken_chain",
                accepted_confirmation_scope="FINAL_ARGUMENT_CONFIRMATION",
                accepted_confirmation_plan_version=1,
            )
        )

    assert "TOOL_EXECUTION_STARTED" not in [event["event_name"] for event in journal.events()]
    assert backend.executed_calls == ()


def test_confirmation_required_manifest_rejects_standalone_wrong_scope_acceptance() -> None:
    journal, caused_by_event_id = _started_journal()
    confirmation = journal.append(
        event_name="CONFIRMATION_ACCEPTED",
        event_id="evt_mvp2_slice2_task_cancel_confirmation_accepted",
        source_module="slowtask_runtime",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=50,
        created_wall_clock_ms=1700000040050,
        trace_redaction_level="metadata_only",
        confirmation_id="confirmation_mvp2_slice2_task_cancel",
        task_id="task_mvp2_slice2",
        plan_version=1,
        task_event_seq=3,
        accepted_scope="TASK_CANCEL",
        authorization_ref="authorization://synthetic/mvp2/slice2/scope-check",
    )
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([_weather_manifest(confirmation_required=True)]),
        backend=backend,
    )

    with pytest.raises(ToolExecutionPolicyError, match="current-plan CONFIRMATION_ACCEPTED"):
        executor.execute(
            ToolExecutionRequest(
                tool_call_id="tool_call_mvp2_slice2_scope_confirmation",
                tool_name="weather",
                task_id="task_mvp2_slice2",
                plan_version=1,
                current_plan_version=1,
                start_task_event_seq=4,
                caused_by_event_id=str(confirmation["event_id"]),
                event_id_prefix="evt_mvp2_slice2_scope_confirmation",
                created_monotonic_ms=375,
                created_wall_clock_ms=1700000040375,
                idempotency_key="idem://synthetic/mvp2/slice2/scope-confirmation",
                arguments={"location": "Testville", "date": "2026-05-17"},
                argument_provenance={
                    "location": "evt_mvp2_slice2_arguments_resolved",
                    "date": "evt_mvp2_slice2_arguments_resolved",
                },
                resolved_arguments_ref="args://synthetic/mvp2/slice2/scope-confirmation/ready",
                provenance_ref="provenance://synthetic/mvp2/slice2/scope-confirmation/ready",
                accepted_confirmation_event_id=str(confirmation["event_id"]),
                accepted_confirmation_id="confirmation_mvp2_slice2_task_cancel",
                accepted_confirmation_scope="TASK_CANCEL",
                accepted_confirmation_plan_version=1,
            )
        )

    assert "TOOL_EXECUTION_STARTED" not in [event["event_name"] for event in journal.events()]
    assert backend.executed_calls == ()


def test_confirmation_required_manifest_rejects_standalone_accepted_event_without_chain() -> None:
    journal, caused_by_event_id = _started_journal()
    confirmation = journal.append(
        event_name="CONFIRMATION_ACCEPTED",
        event_id="evt_mvp2_slice2_standalone_confirmation_accepted",
        source_module="slowtask_runtime",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=55,
        created_wall_clock_ms=1700000040055,
        trace_redaction_level="metadata_only",
        confirmation_id="confirmation_mvp2_slice2_standalone",
        task_id="task_mvp2_slice2",
        plan_version=1,
        task_event_seq=3,
        accepted_scope="FINAL_ARGUMENT_CONFIRMATION",
        authorization_ref="authorization://synthetic/mvp2/slice2/standalone-final",
    )
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([_weather_manifest(confirmation_required=True)]),
        backend=backend,
    )

    with pytest.raises(ToolExecutionPolicyError, match="current-plan CONFIRMATION_ACCEPTED"):
        executor.execute(
            ToolExecutionRequest(
                tool_call_id="tool_call_mvp2_slice2_standalone_confirmation",
                tool_name="weather",
                task_id="task_mvp2_slice2",
                plan_version=1,
                current_plan_version=1,
                start_task_event_seq=4,
                caused_by_event_id=str(confirmation["event_id"]),
                event_id_prefix="evt_mvp2_slice2_standalone_confirmation",
                created_monotonic_ms=376,
                created_wall_clock_ms=1700000040376,
                idempotency_key="idem://synthetic/mvp2/slice2/standalone-confirmation",
                arguments={"location": "Testville", "date": "2026-05-17"},
                argument_provenance={
                    "location": "evt_mvp2_slice2_arguments_resolved",
                    "date": "evt_mvp2_slice2_arguments_resolved",
                },
                resolved_arguments_ref="args://synthetic/mvp2/slice2/standalone-confirmation/ready",
                provenance_ref="provenance://synthetic/mvp2/slice2/standalone-confirmation/ready",
                accepted_confirmation_event_id=str(confirmation["event_id"]),
                accepted_confirmation_id="confirmation_mvp2_slice2_standalone",
                accepted_confirmation_scope="FINAL_ARGUMENT_CONFIRMATION",
                accepted_confirmation_plan_version=1,
            )
        )

    assert "TOOL_EXECUTION_STARTED" not in [event["event_name"] for event in journal.events()]
    assert backend.executed_calls == ()


def test_confirmation_required_manifest_rejects_non_confirmation_event_as_authorization() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([_weather_manifest(confirmation_required=True)]),
        backend=backend,
    )

    with pytest.raises(ToolExecutionPolicyError, match="current-plan CONFIRMATION_ACCEPTED"):
        executor.execute(
            ToolExecutionRequest(
                tool_call_id="tool_call_mvp2_slice2_bogus_confirmation",
                tool_name="weather",
                task_id="task_mvp2_slice2",
                plan_version=1,
                current_plan_version=1,
                start_task_event_seq=3,
                caused_by_event_id=caused_by_event_id,
                event_id_prefix="evt_mvp2_slice2_bogus_confirmation",
                created_monotonic_ms=380,
                created_wall_clock_ms=1700000040380,
                idempotency_key="idem://synthetic/mvp2/slice2/bogus-confirmation",
                arguments={"location": "Testville", "date": "2026-05-17"},
                argument_provenance={
                    "location": "evt_mvp2_slice2_arguments_resolved",
                    "date": "evt_mvp2_slice2_arguments_resolved",
                },
                resolved_arguments_ref="args://synthetic/mvp2/slice2/bogus-confirmation/ready",
                provenance_ref="provenance://synthetic/mvp2/slice2/bogus-confirmation/ready",
                accepted_confirmation_event_id=caused_by_event_id,
                accepted_confirmation_id="confirmation_mvp2_slice2_weather",
                accepted_confirmation_scope="FINAL_ARGUMENT_CONFIRMATION",
                accepted_confirmation_plan_version=1,
            )
        )

    assert "TOOL_EXECUTION_STARTED" not in [event["event_name"] for event in journal.events()]
    assert backend.executed_calls == ()


def test_backend_failure_is_recorded_as_tool_execution_failed_without_result() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([_unsupported_manifest()]),
        backend=backend,
    )

    result = executor.execute(
        ToolExecutionRequest(
            tool_call_id="tool_call_mvp2_slice2_unsupported",
            tool_name="unsupportedLookup",
            task_id="task_mvp2_slice2",
            plan_version=1,
            current_plan_version=1,
            start_task_event_seq=20,
            caused_by_event_id=caused_by_event_id,
            event_id_prefix="evt_mvp2_slice2_unsupported",
            created_monotonic_ms=400,
            created_wall_clock_ms=1700000040400,
            idempotency_key="idem://synthetic/mvp2/slice2/unsupported",
            arguments={"query": "synthetic"},
            argument_provenance={"query": "evt_mvp2_slice2_arguments_resolved"},
            resolved_arguments_ref="args://synthetic/mvp2/slice2/unsupported/ready",
            provenance_ref="provenance://synthetic/mvp2/slice2/unsupported/ready",
        )
    )

    event_names = [event["event_name"] for event in result.produced_events]
    assert event_names[-2:] == ["TOOL_EXECUTION_STARTED", "TOOL_EXECUTION_FAILED"]
    assert "TOOL_RESULT_RECEIVED" not in event_names
    failure = result.produced_events[-1]
    assert failure["failure_reason"] == "demo_backend_adapter_not_supported"
    assert failure["retryable"] is False
    assert backend.executed_calls == ()


def _started_journal() -> tuple[object, str]:
    startup = start_mvp0_session(
        session_id="sess_mvp2_slice2",
        conversation_id="conv_mvp2_slice2",
        runtime_config_ref="config://synthetic/mvp2/slice2",
        created_monotonic_ms=1,
        created_wall_clock_ms=1700000040001,
    )
    created = startup.journal.append(
        event_name="SLOWTASK_CREATED",
        event_id="evt_mvp2_slice2_slowtask_created",
        source_module="slowtask_runtime",
        caused_by_event_id=str(startup.journal.events()[-1]["event_id"]),
        created_monotonic_ms=10,
        created_wall_clock_ms=1700000040010,
        trace_redaction_level="metadata_only",
        task_id="task_mvp2_slice2",
        plan_version=1,
        task_event_seq=1,
        initial_goal_ref="goal://synthetic/mvp2/slice2/tool-executor",
        source_evidence_refs=["evidence://synthetic/mvp2/slice2/spawn"],
    )
    arguments_resolved = startup.journal.append(
        event_name="ARGUMENTS_RESOLVED",
        event_id="evt_mvp2_slice2_arguments_resolved",
        source_module="slowtask_runtime",
        caused_by_event_id=str(created["event_id"]),
        created_monotonic_ms=11,
        created_wall_clock_ms=1700000040011,
        trace_redaction_level="metadata_only",
        task_id="task_mvp2_slice2",
        plan_version=1,
        task_event_seq=2,
        resolved_arguments_ref="args://synthetic/mvp2/slice2/current-plan/ready",
        provenance_ref="provenance://synthetic/mvp2/slice2/current-plan/ready",
    )
    return startup.journal, str(arguments_resolved["event_id"])


def _advance_journal_to_plan_2(journal: object, caused_by_event_id: str) -> dict[str, object]:
    return journal.append(
        event_name="PLAN_VERSION_ADVANCED",
        event_id="evt_mvp2_slice2_plan_version_advanced",
        source_module="slowtask_runtime",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=20,
        created_wall_clock_ms=1700000040020,
        trace_redaction_level="metadata_only",
        task_id="task_mvp2_slice2",
        plan_version=2,
        task_event_seq=3,
        from_plan_version=1,
        to_plan_version=2,
        planning_reason="material_user_patch:synthetic_change",
    )


def _append_confirmation_chain(
    journal: object,
    *,
    caused_by_event_id: str,
    confirmation_id: str,
    confirmation_scope: str,
    start_task_event_seq: int,
    required_for_event_id: str | None = None,
    patch_caused_by_event_id: str | None = None,
) -> dict[str, object]:
    required = journal.append(
        event_name="CONFIRMATION_REQUIRED",
        event_id=f"evt_mvp2_slice2_{confirmation_id}_required",
        source_module="slowtask_runtime",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=50,
        created_wall_clock_ms=1700000040050,
        trace_redaction_level="metadata_only",
        confirmation_id=confirmation_id,
        task_id="task_mvp2_slice2",
        plan_version=1,
        task_event_seq=start_task_event_seq,
        confirmation_scope=confirmation_scope,
        required_for_event_id=required_for_event_id or caused_by_event_id,
        prompt_ref=f"prompt://synthetic/mvp2/slice2/{confirmation_id}",
    )
    patch_received = journal.append(
        event_name="USER_PATCH_RECEIVED",
        event_id=f"evt_mvp2_slice2_{confirmation_id}_patch_received",
        source_module="user_patch_pipeline",
        caused_by_event_id=patch_caused_by_event_id or str(required["event_id"]),
        created_monotonic_ms=51,
        created_wall_clock_ms=1700000040051,
        trace_redaction_level="metadata_only",
        patch_id=f"patch_mvp2_slice2_{confirmation_id}",
        task_id="task_mvp2_slice2",
        plan_version=1,
        task_event_seq=start_task_event_seq + 1,
        observed_plan_version=1,
        evidence_ref=f"evidence://synthetic/mvp2/slice2/{confirmation_id}/confirmation",
    )
    interpreted = journal.append(
        event_name="USER_PATCH_INTERPRETED",
        event_id=f"evt_mvp2_slice2_{confirmation_id}_patch_interpreted",
        source_module="slowtask_runtime",
        caused_by_event_id=str(patch_received["event_id"]),
        created_monotonic_ms=52,
        created_wall_clock_ms=1700000040052,
        trace_redaction_level="metadata_only",
        patch_id=f"patch_mvp2_slice2_{confirmation_id}",
        task_id="task_mvp2_slice2",
        plan_version=1,
        task_event_seq=start_task_event_seq + 2,
        observed_plan_version=1,
        interpreted_against_plan_version=1,
        interpretation_type="confirmation",
        materially_changes_task=False,
        interpretation_reason="synthetic_confirmation_acceptance",
        source_evidence_refs=[f"evidence://synthetic/mvp2/slice2/{confirmation_id}/confirmation"],
    )
    received = journal.append(
        event_name="USER_CONFIRMATION_RECEIVED",
        event_id=f"evt_mvp2_slice2_{confirmation_id}_received",
        source_module="slowtask_runtime",
        caused_by_event_id=str(interpreted["event_id"]),
        created_monotonic_ms=53,
        created_wall_clock_ms=1700000040053,
        trace_redaction_level="metadata_only",
        confirmation_id=confirmation_id,
        patch_id=f"patch_mvp2_slice2_{confirmation_id}",
        task_id="task_mvp2_slice2",
        plan_version=1,
        task_event_seq=start_task_event_seq + 3,
        confirmation_signal="accepted",
    )
    return journal.append(
        event_name="CONFIRMATION_ACCEPTED",
        event_id=f"evt_mvp2_slice2_{confirmation_id}_accepted",
        source_module="slowtask_runtime",
        caused_by_event_id=str(received["event_id"]),
        created_monotonic_ms=54,
        created_wall_clock_ms=1700000040054,
        trace_redaction_level="metadata_only",
        confirmation_id=confirmation_id,
        task_id="task_mvp2_slice2",
        plan_version=1,
        task_event_seq=start_task_event_seq + 4,
        accepted_scope=confirmation_scope,
        authorization_ref=f"authorization://synthetic/mvp2/slice2/{confirmation_id}",
    )


def _weather_manifest(
    *,
    side_effect_class: str = "READ_ONLY",
    confirmation_required: bool = False,
) -> ToolManifest:
    return ToolManifest(
        tool_name="weather",
        tool_adapter_id="demo.weather",
        tool_manifest_version="2026-05-17.slice2",
        tool_category="READ_ONLY_EXTERNAL",
        side_effect_class=side_effect_class,
        risk_class="LOW",
        required_arguments=("location", "date"),
        optional_arguments=(),
        argument_provenance_requirements=("location", "date"),
        result_type="weather_snapshot",
        trust_level="EXTERNAL_READ_PROVIDER_RESULT",
        source_type="READ_ONLY_EXTERNAL",
        preview_required=True,
        confirmation_required=confirmation_required,
        ui_patch_capable=False,
        idempotency_required=True,
        sandbox_state_namespace="weather",
        capability="mock",
    )


def _unsupported_manifest() -> ToolManifest:
    return ToolManifest(
        tool_name="unsupportedLookup",
        tool_adapter_id="demo.unsupported_lookup",
        tool_manifest_version="2026-05-17.slice2",
        tool_category="READ_ONLY_DEMO",
        side_effect_class="READ_ONLY",
        risk_class="LOW",
        required_arguments=("query",),
        optional_arguments=(),
        argument_provenance_requirements=("query",),
        result_type="unsupported_lookup",
        trust_level="TRUSTED_DEMO_TOOL_RESULT",
        source_type="DEMO_SANDBOX",
        preview_required=False,
        confirmation_required=False,
        ui_patch_capable=False,
        idempotency_required=True,
        sandbox_state_namespace="unsupported",
        capability="mock",
    )


def _task_bindings(events: tuple[dict[str, object], ...]) -> set[tuple[str, int, str]]:
    return {
        (str(event["task_id"]), int(event["plan_version"]), str(event["tool_call_id"]))
        for event in events
        if "task_id" in event
    }
