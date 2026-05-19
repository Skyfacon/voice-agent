from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256

import pytest

from voice_agent.demo_backend.in_memory import InMemoryDemoBackend
from voice_agent.runtime.session import start_mvp0_session
from voice_agent.tools.demo_manifests import (
    alarm_cancel_manifest,
    alarm_create_manifest,
    memo_create_manifest,
    memo_delete_manifest,
)
from voice_agent.tools.executor import DemoToolExecutor, ToolExecutionPolicyError, ToolExecutionRequest
from voice_agent.tools.manifest import BLOCKED_SIDE_EFFECT_CLASSES, ToolManifest
from voice_agent.tools.registry import ToolRegistry


def test_demo_destructive_action_without_confirmation_does_not_authorize_start_patch_result_or_mutate_backend() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([memo_delete_manifest()]),
        backend=backend,
    )

    with pytest.raises(ToolExecutionPolicyError, match="current-plan CONFIRMATION_ACCEPTED"):
        executor.execute(
            _request(
                tool_call_id="tool_call_mvp2_slice5_memo_delete_missing_confirmation",
                tool_name="memo.delete",
                caused_by_event_id=caused_by_event_id,
                event_id_prefix="evt_mvp2_slice5_memo_delete_missing_confirmation",
                idempotency_key="idem://synthetic/mvp2/slice5/memo-delete-missing-confirmation",
                arguments={"memo_item_id": "memo_item_000001"},
                argument_provenance={"memo_item_id": "evt_mvp2_slice5_arguments_resolved"},
            )
        )

    event_names = [event["event_name"] for event in journal.events()]
    assert "TOOL_MANIFEST_LOADED" in event_names
    assert "TOOL_ARGUMENTS_READY" in event_names
    assert "TOOL_PREVIEW_AVAILABLE" in event_names
    assert "TOOL_EXECUTION_AUTHORIZED" not in event_names
    assert "TOOL_EXECUTION_STARTED" not in event_names
    assert "TOOL_UI_STATE_PATCHED" not in event_names
    assert "TOOL_RESULT_RECEIVED" not in event_names
    assert backend.executed_calls == ()


def test_accepted_current_plan_confirmation_authorizes_memo_delete_sandbox_action() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([memo_create_manifest(), memo_delete_manifest()]),
        backend=backend,
    )
    created = executor.execute(
        _request(
            tool_call_id="tool_call_mvp2_slice5_memo_create",
            tool_name="memo",
            caused_by_event_id=caused_by_event_id,
            event_id_prefix="evt_mvp2_slice5_memo_create",
            idempotency_key="idem://synthetic/mvp2/slice5/memo-create",
            arguments={"body": "Synthetic memo body that must not enter refs"},
            argument_provenance={"body": "evt_mvp2_slice5_arguments_resolved"},
        )
    )
    assert created.payload is not None
    delete_trigger_event_id = str(created.produced_events[-1]["event_id"])
    preview_result = _preview_destructive_request(
        executor,
        _request(
            tool_call_id="tool_call_mvp2_slice5_memo_delete",
            tool_name="memo.delete",
            caused_by_event_id=delete_trigger_event_id,
            event_id_prefix="evt_mvp2_slice5_memo_delete_preview",
            start_task_event_seq=9,
            idempotency_key="idem://synthetic/mvp2/slice5/memo-delete",
            arguments={"memo_item_id": created.payload["memo_item_id"]},
            argument_provenance={"memo_item_id": "evt_mvp2_slice5_arguments_resolved"},
        ),
    )
    delete_preview = preview_result.produced_events[-1]
    confirmation = _append_confirmation_chain(
        journal,
        caused_by_event_id=str(delete_preview["event_id"]),
        confirmation_id="confirmation_mvp2_slice5_memo_delete",
        start_task_event_seq=12,
    )
    idempotency_key = "idem://synthetic/mvp2/slice5/memo-delete"

    deleted = executor.execute(
        _request(
            tool_call_id="tool_call_mvp2_slice5_memo_delete",
            tool_name="memo.delete",
            caused_by_event_id=str(delete_preview["event_id"]),
            event_id_prefix="evt_mvp2_slice5_memo_delete",
            start_task_event_seq=18,
            idempotency_key=idempotency_key,
            arguments={"memo_item_id": created.payload["memo_item_id"]},
            argument_provenance={"memo_item_id": "evt_mvp2_slice5_arguments_resolved"},
            accepted_confirmation_event_id=str(confirmation["event_id"]),
            accepted_confirmation_id="confirmation_mvp2_slice5_memo_delete",
            accepted_confirmation_scope="DEMO_DESTRUCTIVE_ACTION",
            accepted_confirmation_plan_version=1,
        )
    )

    event_names = [event["event_name"] for event in deleted.produced_events]
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
    authorized = deleted.produced_events[3]
    started = deleted.produced_events[4]
    patch = deleted.produced_events[6]
    received = deleted.produced_events[7]
    expected_patch_id = _expected_ui_patch_id(
        namespace="memo",
        operation="delete",
        idempotency_key=idempotency_key,
    )
    assert authorized["authorization_basis"] == "current_plan_confirmation_acceptance"
    assert authorized["confirmation_id"] == "confirmation_mvp2_slice5_memo_delete"
    assert authorized["caused_by_event_id"] == confirmation["event_id"]
    assert started["authorization_event_id"] == authorized["event_id"]
    assert patch["ui_patch_id"] == expected_patch_id
    assert patch["patch_ref"] == f"patch://synthetic/demo_backend/memo/delete/{expected_patch_id}"
    assert received["result_ref"] == "result://synthetic/demo_backend/memo/memo_delete_000001"
    assert received["trust_level"] == "TRUSTED_DEMO_TOOL_RESULT"
    assert received["source_type"] == "DEMO_SANDBOX"
    assert deleted.payload is not None
    assert deleted.payload["operation"] == "delete"
    assert backend.executed_calls == (
        ("memo", {"body": "Synthetic memo body that must not enter refs"}),
        ("memo.delete", {"memo_item_id": "memo_item_000001"}),
    )
    assert "memo_item_000001" not in repr(deleted.produced_events)
    assert not any(event["event_name"].startswith("SLOWTASK_") for event in deleted.produced_events)


def test_confirmation_for_memo_delete_cannot_authorize_alarm_cancel_with_same_trigger() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([alarm_create_manifest(), memo_delete_manifest(), alarm_cancel_manifest()]),
        backend=backend,
    )
    created = executor.execute(
        _request(
            tool_call_id="tool_call_mvp2_slice5_alarm_create_for_wrong_tool",
            tool_name="alarm",
            caused_by_event_id=caused_by_event_id,
            event_id_prefix="evt_mvp2_slice5_alarm_create_for_wrong_tool",
            idempotency_key="idem://synthetic/mvp2/slice5/alarm-create-for-wrong-tool",
            arguments={"time": "07:30", "timezone": "Etc/UTC", "label": "Synthetic alarm"},
            argument_provenance={
                "time": "evt_mvp2_slice5_arguments_resolved",
                "timezone": "evt_mvp2_slice5_arguments_resolved",
                "label": "evt_mvp2_slice5_arguments_resolved",
            },
        )
    )
    assert created.payload is not None
    shared_trigger_event_id = str(created.produced_events[-1]["event_id"])
    memo_preview = _preview_destructive_request(
        executor,
        _request(
            tool_call_id="tool_call_mvp2_slice5_memo_delete_wrong_tool_preview",
            tool_name="memo.delete",
            caused_by_event_id=shared_trigger_event_id,
            event_id_prefix="evt_mvp2_slice5_memo_delete_wrong_tool_preview",
            start_task_event_seq=10,
            idempotency_key="idem://synthetic/mvp2/slice5/memo-delete-wrong-tool",
            arguments={"memo_item_id": "memo_item_000001"},
            argument_provenance={"memo_item_id": "evt_mvp2_slice5_arguments_resolved"},
        ),
    ).produced_events[-1]
    confirmation = _append_confirmation_chain(
        journal,
        caused_by_event_id=str(memo_preview["event_id"]),
        confirmation_id="confirmation_mvp2_slice5_memo_delete_wrong_tool",
        start_task_event_seq=13,
    )

    with pytest.raises(ToolExecutionPolicyError, match="pending tool request"):
        executor.execute(
            _request(
                tool_call_id="tool_call_mvp2_slice5_alarm_cancel_wrong_tool",
                tool_name="alarm.cancel",
                caused_by_event_id=str(memo_preview["event_id"]),
                event_id_prefix="evt_mvp2_slice5_alarm_cancel_wrong_tool",
                start_task_event_seq=19,
                idempotency_key="idem://synthetic/mvp2/slice5/alarm-cancel-wrong-tool",
                arguments={"alarm_id": created.payload["alarm_id"]},
                argument_provenance={"alarm_id": "evt_mvp2_slice5_arguments_resolved"},
                accepted_confirmation_event_id=str(confirmation["event_id"]),
                accepted_confirmation_id="confirmation_mvp2_slice5_memo_delete_wrong_tool",
                accepted_confirmation_scope="DEMO_DESTRUCTIVE_ACTION",
                accepted_confirmation_plan_version=1,
            )
        )

    event_names = [event["event_name"] for event in journal.events()]
    assert "evt_mvp2_slice5_alarm_cancel_wrong_tool_execution_authorized" not in {
        str(event["event_id"]) for event in journal.events()
    }
    assert event_names.count("TOOL_EXECUTION_STARTED") == 1
    assert backend.executed_calls == (
        (
            "alarm",
            {"label": "Synthetic alarm", "time": "07:30", "timezone": "Etc/UTC"},
        ),
    )


def test_destructive_confirmation_accepts_standard_router_user_patch_causality() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([memo_create_manifest(), memo_delete_manifest()]),
        backend=backend,
    )
    created = executor.execute(
        _request(
            tool_call_id="tool_call_mvp2_slice5_memo_create_router_confirmation",
            tool_name="memo",
            caused_by_event_id=caused_by_event_id,
            event_id_prefix="evt_mvp2_slice5_memo_create_router_confirmation",
            idempotency_key="idem://synthetic/mvp2/slice5/memo-create-router-confirmation",
            arguments={"body": "Synthetic memo body"},
            argument_provenance={"body": "evt_mvp2_slice5_arguments_resolved"},
        )
    )
    assert created.payload is not None
    memo_preview = _preview_destructive_request(
        executor,
        _request(
            tool_call_id="tool_call_mvp2_slice5_memo_delete_router_confirmation",
            tool_name="memo.delete",
            caused_by_event_id=str(created.produced_events[-1]["event_id"]),
            event_id_prefix="evt_mvp2_slice5_memo_delete_router_confirmation_preview",
            start_task_event_seq=9,
            idempotency_key="idem://synthetic/mvp2/slice5/memo-delete-router-confirmation",
            arguments={"memo_item_id": created.payload["memo_item_id"]},
            argument_provenance={"memo_item_id": "evt_mvp2_slice5_arguments_resolved"},
        ),
    ).produced_events[-1]
    confirmation = _append_confirmation_chain(
        journal,
        caused_by_event_id=str(memo_preview["event_id"]),
        confirmation_id="confirmation_mvp2_slice5_memo_delete_router",
        start_task_event_seq=12,
        patch_caused_by_event_id="evt_mvp2_slice5_router_confirmation_patch",
    )

    result = executor.execute(
        _request(
            tool_call_id="tool_call_mvp2_slice5_memo_delete_router_confirmation",
            tool_name="memo.delete",
            caused_by_event_id=str(memo_preview["event_id"]),
            event_id_prefix="evt_mvp2_slice5_memo_delete_router_confirmation",
            start_task_event_seq=18,
            idempotency_key="idem://synthetic/mvp2/slice5/memo-delete-router-confirmation",
            arguments={"memo_item_id": created.payload["memo_item_id"]},
            argument_provenance={"memo_item_id": "evt_mvp2_slice5_arguments_resolved"},
            accepted_confirmation_event_id=str(confirmation["event_id"]),
            accepted_confirmation_id="confirmation_mvp2_slice5_memo_delete_router",
            accepted_confirmation_scope="DEMO_DESTRUCTIVE_ACTION",
            accepted_confirmation_plan_version=1,
        )
    )

    authorized = next(event for event in result.produced_events if event["event_name"] == "TOOL_EXECUTION_AUTHORIZED")
    assert authorized["confirmation_id"] == "confirmation_mvp2_slice5_memo_delete_router"
    assert backend.executed_calls[-1] == ("memo.delete", {"memo_item_id": "memo_item_000001"})


def test_destructive_confirmation_rejects_direct_waiting_to_user_patch_chain() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([memo_create_manifest(), memo_delete_manifest()]),
        backend=backend,
    )
    created = executor.execute(
        _request(
            tool_call_id="tool_call_mvp2_slice5_memo_create_direct_confirmation",
            tool_name="memo",
            caused_by_event_id=caused_by_event_id,
            event_id_prefix="evt_mvp2_slice5_memo_create_direct_confirmation",
            idempotency_key="idem://synthetic/mvp2/slice5/memo-create-direct-confirmation",
            arguments={"body": "Synthetic memo body"},
            argument_provenance={"body": "evt_mvp2_slice5_arguments_resolved"},
        )
    )
    assert created.payload is not None
    memo_preview = _preview_destructive_request(
        executor,
        _request(
            tool_call_id="tool_call_mvp2_slice5_memo_delete_direct_confirmation",
            tool_name="memo.delete",
            caused_by_event_id=str(created.produced_events[-1]["event_id"]),
            event_id_prefix="evt_mvp2_slice5_memo_delete_direct_confirmation_preview",
            start_task_event_seq=9,
            idempotency_key="idem://synthetic/mvp2/slice5/memo-delete-direct-confirmation",
            arguments={"memo_item_id": created.payload["memo_item_id"]},
            argument_provenance={"memo_item_id": "evt_mvp2_slice5_arguments_resolved"},
        ),
    ).produced_events[-1]
    confirmation = _append_confirmation_chain(
        journal,
        caused_by_event_id=str(memo_preview["event_id"]),
        confirmation_id="confirmation_mvp2_slice5_memo_delete_direct",
        start_task_event_seq=12,
        route_through_router=False,
    )

    with pytest.raises(ToolExecutionPolicyError, match="current-plan CONFIRMATION_ACCEPTED"):
        executor.execute(
            _request(
                tool_call_id="tool_call_mvp2_slice5_memo_delete_direct_confirmation",
                tool_name="memo.delete",
                caused_by_event_id=str(memo_preview["event_id"]),
                event_id_prefix="evt_mvp2_slice5_memo_delete_direct_confirmation",
                start_task_event_seq=18,
                idempotency_key="idem://synthetic/mvp2/slice5/memo-delete-direct-confirmation-execute",
                arguments={"memo_item_id": created.payload["memo_item_id"]},
                argument_provenance={"memo_item_id": "evt_mvp2_slice5_arguments_resolved"},
                accepted_confirmation_event_id=str(confirmation["event_id"]),
                accepted_confirmation_id="confirmation_mvp2_slice5_memo_delete_direct",
                accepted_confirmation_scope="DEMO_DESTRUCTIVE_ACTION",
                accepted_confirmation_plan_version=1,
            )
        )

    assert backend.executed_calls == (
        ("memo", {"body": "Synthetic memo body"}),
    )


def test_destructive_confirmation_rejects_router_event_without_turn_evidence() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([memo_create_manifest(), memo_delete_manifest()]),
        backend=backend,
    )
    created = executor.execute(
        _request(
            tool_call_id="tool_call_mvp2_slice5_memo_create_router_without_turn",
            tool_name="memo",
            caused_by_event_id=caused_by_event_id,
            event_id_prefix="evt_mvp2_slice5_memo_create_router_without_turn",
            idempotency_key="idem://synthetic/mvp2/slice5/memo-create-router-without-turn",
            arguments={"body": "Synthetic memo body"},
            argument_provenance={"body": "evt_mvp2_slice5_arguments_resolved"},
        )
    )
    assert created.payload is not None
    memo_preview = _preview_destructive_request(
        executor,
        _request(
            tool_call_id="tool_call_mvp2_slice5_memo_delete_router_without_turn",
            tool_name="memo.delete",
            caused_by_event_id=str(created.produced_events[-1]["event_id"]),
            event_id_prefix="evt_mvp2_slice5_memo_delete_router_without_turn_preview",
            start_task_event_seq=9,
            idempotency_key="idem://synthetic/mvp2/slice5/memo-delete-router-without-turn",
            arguments={"memo_item_id": created.payload["memo_item_id"]},
            argument_provenance={"memo_item_id": "evt_mvp2_slice5_arguments_resolved"},
        ),
    ).produced_events[-1]
    confirmation = _append_confirmation_chain(
        journal,
        caused_by_event_id=str(memo_preview["event_id"]),
        confirmation_id="confirmation_mvp2_slice5_memo_delete_router_without_turn",
        start_task_event_seq=12,
        router_has_turn_evidence=False,
    )

    with pytest.raises(ToolExecutionPolicyError, match="current-plan CONFIRMATION_ACCEPTED"):
        executor.execute(
            _request(
                tool_call_id="tool_call_mvp2_slice5_memo_delete_router_without_turn",
                tool_name="memo.delete",
                caused_by_event_id=str(memo_preview["event_id"]),
                event_id_prefix="evt_mvp2_slice5_memo_delete_router_without_turn",
                start_task_event_seq=18,
                idempotency_key="idem://synthetic/mvp2/slice5/memo-delete-router-without-turn-execute",
                arguments={"memo_item_id": created.payload["memo_item_id"]},
                argument_provenance={"memo_item_id": "evt_mvp2_slice5_arguments_resolved"},
                accepted_confirmation_event_id=str(confirmation["event_id"]),
                accepted_confirmation_id="confirmation_mvp2_slice5_memo_delete_router_without_turn",
                accepted_confirmation_scope="DEMO_DESTRUCTIVE_ACTION",
                accepted_confirmation_plan_version=1,
            )
        )

    assert backend.executed_calls == (
        ("memo", {"body": "Synthetic memo body"}),
    )


def test_confirmation_cannot_authorize_different_resolved_arguments_than_preview() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([memo_create_manifest(), memo_delete_manifest()]),
        backend=backend,
    )
    first = executor.execute(
        _request(
            tool_call_id="tool_call_mvp2_slice5_memo_create_arg_bind_one",
            tool_name="memo",
            caused_by_event_id=caused_by_event_id,
            event_id_prefix="evt_mvp2_slice5_memo_create_arg_bind_one",
            idempotency_key="idem://synthetic/mvp2/slice5/memo-create-arg-bind-one",
            arguments={"body": "Synthetic memo body one"},
            argument_provenance={"body": "evt_mvp2_slice5_arguments_resolved"},
        )
    )
    second = executor.execute(
        _request(
            tool_call_id="tool_call_mvp2_slice5_memo_create_arg_bind_two",
            tool_name="memo",
            caused_by_event_id=str(first.produced_events[-1]["event_id"]),
            event_id_prefix="evt_mvp2_slice5_memo_create_arg_bind_two",
            start_task_event_seq=12,
            idempotency_key="idem://synthetic/mvp2/slice5/memo-create-arg-bind-two",
            arguments={"body": "Synthetic memo body two"},
            argument_provenance={"body": "evt_mvp2_slice5_arguments_resolved"},
        )
    )
    assert first.payload is not None
    assert second.payload is not None
    memo_preview = _preview_destructive_request(
        executor,
        _request(
            tool_call_id="tool_call_mvp2_slice5_memo_delete_arg_bind",
            tool_name="memo.delete",
            caused_by_event_id=str(second.produced_events[-1]["event_id"]),
            event_id_prefix="evt_mvp2_slice5_memo_delete_arg_bind_preview",
            start_task_event_seq=21,
            idempotency_key="idem://synthetic/mvp2/slice5/memo-delete-arg-bind-preview",
            arguments={"memo_item_id": first.payload["memo_item_id"]},
            argument_provenance={"memo_item_id": "evt_mvp2_slice5_arguments_resolved"},
            resolved_arguments_ref="args://synthetic/mvp2/slice5/memo-delete/arg-bind-one",
            provenance_ref="provenance://synthetic/mvp2/slice5/memo-delete/arg-bind-one",
        ),
    ).produced_events[-1]
    confirmation = _append_confirmation_chain(
        journal,
        caused_by_event_id=str(memo_preview["event_id"]),
        confirmation_id="confirmation_mvp2_slice5_memo_delete_arg_bind",
        start_task_event_seq=24,
    )

    with pytest.raises(ToolExecutionPolicyError, match="previewed arguments"):
        executor.execute(
            _request(
                tool_call_id="tool_call_mvp2_slice5_memo_delete_arg_bind",
                tool_name="memo.delete",
                caused_by_event_id=str(memo_preview["event_id"]),
                event_id_prefix="evt_mvp2_slice5_memo_delete_arg_bind",
                start_task_event_seq=31,
                idempotency_key="idem://synthetic/mvp2/slice5/memo-delete-arg-bind",
                arguments={"memo_item_id": second.payload["memo_item_id"]},
                argument_provenance={"memo_item_id": "evt_mvp2_slice5_arguments_resolved"},
                resolved_arguments_ref="args://synthetic/mvp2/slice5/memo-delete/arg-bind-two",
                provenance_ref="provenance://synthetic/mvp2/slice5/memo-delete/arg-bind-two",
                accepted_confirmation_event_id=str(confirmation["event_id"]),
                accepted_confirmation_id="confirmation_mvp2_slice5_memo_delete_arg_bind",
                accepted_confirmation_scope="DEMO_DESTRUCTIVE_ACTION",
                accepted_confirmation_plan_version=1,
            )
        )

    assert backend.executed_calls == (
        ("memo", {"body": "Synthetic memo body one"}),
        ("memo", {"body": "Synthetic memo body two"}),
    )


def test_confirmation_cannot_authorize_different_runtime_arguments_with_same_argument_refs() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([memo_create_manifest(), memo_delete_manifest()]),
        backend=backend,
    )
    first = executor.execute(
        _request(
            tool_call_id="tool_call_mvp2_slice5_memo_create_arg_fingerprint_one",
            tool_name="memo",
            caused_by_event_id=caused_by_event_id,
            event_id_prefix="evt_mvp2_slice5_memo_create_arg_fingerprint_one",
            idempotency_key="idem://synthetic/mvp2/slice5/memo-create-arg-fingerprint-one",
            arguments={"body": "Synthetic memo body one"},
            argument_provenance={"body": "evt_mvp2_slice5_arguments_resolved"},
        )
    )
    second = executor.execute(
        _request(
            tool_call_id="tool_call_mvp2_slice5_memo_create_arg_fingerprint_two",
            tool_name="memo",
            caused_by_event_id=str(first.produced_events[-1]["event_id"]),
            event_id_prefix="evt_mvp2_slice5_memo_create_arg_fingerprint_two",
            start_task_event_seq=12,
            idempotency_key="idem://synthetic/mvp2/slice5/memo-create-arg-fingerprint-two",
            arguments={"body": "Synthetic memo body two"},
            argument_provenance={"body": "evt_mvp2_slice5_arguments_resolved"},
        )
    )
    assert first.payload is not None
    assert second.payload is not None
    shared_arguments_ref = "args://synthetic/mvp2/slice5/memo-delete/arg-fingerprint"
    shared_provenance_ref = "provenance://synthetic/mvp2/slice5/memo-delete/arg-fingerprint"
    memo_preview = _preview_destructive_request(
        executor,
        _request(
            tool_call_id="tool_call_mvp2_slice5_memo_delete_arg_fingerprint",
            tool_name="memo.delete",
            caused_by_event_id=str(second.produced_events[-1]["event_id"]),
            event_id_prefix="evt_mvp2_slice5_memo_delete_arg_fingerprint_preview",
            start_task_event_seq=21,
            idempotency_key="idem://synthetic/mvp2/slice5/memo-delete-arg-fingerprint-preview",
            arguments={"memo_item_id": first.payload["memo_item_id"]},
            argument_provenance={"memo_item_id": "evt_mvp2_slice5_arguments_resolved"},
            resolved_arguments_ref=shared_arguments_ref,
            provenance_ref=shared_provenance_ref,
        ),
    ).produced_events[-1]
    confirmation = _append_confirmation_chain(
        journal,
        caused_by_event_id=str(memo_preview["event_id"]),
        confirmation_id="confirmation_mvp2_slice5_memo_delete_arg_fingerprint",
        start_task_event_seq=24,
    )

    with pytest.raises(ToolExecutionPolicyError, match="previewed arguments"):
        executor.execute(
            _request(
                tool_call_id="tool_call_mvp2_slice5_memo_delete_arg_fingerprint",
                tool_name="memo.delete",
                caused_by_event_id=str(memo_preview["event_id"]),
                event_id_prefix="evt_mvp2_slice5_memo_delete_arg_fingerprint",
                start_task_event_seq=31,
                idempotency_key="idem://synthetic/mvp2/slice5/memo-delete-arg-fingerprint",
                arguments={"memo_item_id": second.payload["memo_item_id"]},
                argument_provenance={"memo_item_id": "evt_mvp2_slice5_arguments_resolved"},
                resolved_arguments_ref=shared_arguments_ref,
                provenance_ref=shared_provenance_ref,
                accepted_confirmation_event_id=str(confirmation["event_id"]),
                accepted_confirmation_id="confirmation_mvp2_slice5_memo_delete_arg_fingerprint",
                accepted_confirmation_scope="DEMO_DESTRUCTIVE_ACTION",
                accepted_confirmation_plan_version=1,
            )
        )

    assert backend.executed_calls == (
        ("memo", {"body": "Synthetic memo body one"}),
        ("memo", {"body": "Synthetic memo body two"}),
    )


def test_accepted_current_plan_confirmation_authorizes_alarm_cancel_sandbox_action() -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([alarm_create_manifest(), alarm_cancel_manifest()]),
        backend=backend,
    )
    created = executor.execute(
        _request(
            tool_call_id="tool_call_mvp2_slice5_alarm_create",
            tool_name="alarm",
            caused_by_event_id=caused_by_event_id,
            event_id_prefix="evt_mvp2_slice5_alarm_create",
            idempotency_key="idem://synthetic/mvp2/slice5/alarm-create",
            arguments={"time": "07:30", "timezone": "Etc/UTC", "label": "Synthetic alarm"},
            argument_provenance={
                "time": "evt_mvp2_slice5_arguments_resolved",
                "timezone": "evt_mvp2_slice5_arguments_resolved",
                "label": "evt_mvp2_slice5_arguments_resolved",
            },
        )
    )
    assert created.payload is not None
    cancel_trigger_event_id = str(created.produced_events[-1]["event_id"])
    preview_result = _preview_destructive_request(
        executor,
        _request(
            tool_call_id="tool_call_mvp2_slice5_alarm_cancel",
            tool_name="alarm.cancel",
            caused_by_event_id=cancel_trigger_event_id,
            event_id_prefix="evt_mvp2_slice5_alarm_cancel_preview",
            start_task_event_seq=10,
            idempotency_key="idem://synthetic/mvp2/slice5/alarm-cancel",
            arguments={"alarm_id": created.payload["alarm_id"]},
            argument_provenance={"alarm_id": "evt_mvp2_slice5_arguments_resolved"},
        ),
    )
    cancel_preview = preview_result.produced_events[-1]
    confirmation = _append_confirmation_chain(
        journal,
        caused_by_event_id=str(cancel_preview["event_id"]),
        confirmation_id="confirmation_mvp2_slice5_alarm_cancel",
        start_task_event_seq=13,
    )
    idempotency_key = "idem://synthetic/mvp2/slice5/alarm-cancel"

    cancelled = executor.execute(
        _request(
            tool_call_id="tool_call_mvp2_slice5_alarm_cancel",
            tool_name="alarm.cancel",
            caused_by_event_id=str(cancel_preview["event_id"]),
            event_id_prefix="evt_mvp2_slice5_alarm_cancel",
            start_task_event_seq=19,
            idempotency_key=idempotency_key,
            arguments={"alarm_id": created.payload["alarm_id"]},
            argument_provenance={"alarm_id": "evt_mvp2_slice5_arguments_resolved"},
            accepted_confirmation_event_id=str(confirmation["event_id"]),
            accepted_confirmation_id="confirmation_mvp2_slice5_alarm_cancel",
            accepted_confirmation_scope="DEMO_DESTRUCTIVE_ACTION",
            accepted_confirmation_plan_version=1,
        )
    )

    patch = next(event for event in cancelled.produced_events if event["event_name"] == "TOOL_UI_STATE_PATCHED")
    expected_patch_id = _expected_ui_patch_id(
        namespace="alarm",
        operation="cancel",
        idempotency_key=idempotency_key,
    )
    assert patch["ui_patch_id"] == expected_patch_id
    assert patch["patch_ref"] == f"patch://synthetic/demo_backend/alarm/cancel/{expected_patch_id}"
    assert cancelled.produced_events[-1]["result_ref"] == (
        "result://synthetic/demo_backend/alarm/alarm_cancel_000001"
    )
    assert cancelled.payload is not None
    assert cancelled.payload["operation"] == "cancel"
    assert backend.executed_calls == (
        (
            "alarm",
            {"label": "Synthetic alarm", "time": "07:30", "timezone": "Etc/UTC"},
        ),
        ("alarm.cancel", {"alarm_id": "alarm_item_000001"}),
    )
    assert "alarm_item_000001" not in repr(cancelled.produced_events)


@pytest.mark.parametrize(
    "confirmation_variant",
    [
        "rejected",
        "wrong_scope",
        "stale_plan",
        "wrong_required_for_event_id",
        "broken_chain",
    ],
)
def test_invalid_confirmation_variants_do_not_authorize_or_execute(confirmation_variant: str) -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([memo_delete_manifest()]),
        backend=backend,
    )
    confirmation_id = f"confirmation_mvp2_slice5_{confirmation_variant}"
    if confirmation_variant == "rejected":
        terminal_confirmation = _append_confirmation_chain(
            journal,
            caused_by_event_id=caused_by_event_id,
            confirmation_id=confirmation_id,
            start_task_event_seq=3,
            accepted=False,
        )
        accepted_scope = "DEMO_DESTRUCTIVE_ACTION"
        accepted_plan_version = 1
    elif confirmation_variant == "wrong_scope":
        terminal_confirmation = _append_confirmation_chain(
            journal,
            caused_by_event_id=caused_by_event_id,
            confirmation_id=confirmation_id,
            confirmation_scope="TASK_CANCEL",
            start_task_event_seq=3,
        )
        accepted_scope = "TASK_CANCEL"
        accepted_plan_version = 1
    elif confirmation_variant == "stale_plan":
        terminal_confirmation = _append_confirmation_chain(
            journal,
            caused_by_event_id=caused_by_event_id,
            confirmation_id=confirmation_id,
            start_task_event_seq=3,
        )
        accepted_scope = "DEMO_DESTRUCTIVE_ACTION"
        accepted_plan_version = 0
    elif confirmation_variant == "wrong_required_for_event_id":
        terminal_confirmation = _append_confirmation_chain(
            journal,
            caused_by_event_id=caused_by_event_id,
            confirmation_id=confirmation_id,
            start_task_event_seq=3,
            required_for_event_id="evt_mvp2_slice5_unrelated_tool_request",
        )
        accepted_scope = "DEMO_DESTRUCTIVE_ACTION"
        accepted_plan_version = 1
    else:
        terminal_confirmation = _append_confirmation_chain(
            journal,
            caused_by_event_id=caused_by_event_id,
            confirmation_id=confirmation_id,
            start_task_event_seq=3,
            patch_caused_by_event_id=caused_by_event_id,
        )
        accepted_scope = "DEMO_DESTRUCTIVE_ACTION"
        accepted_plan_version = 1

    with pytest.raises(ToolExecutionPolicyError, match="current-plan CONFIRMATION_ACCEPTED"):
        executor.execute(
            _request(
                tool_call_id=f"tool_call_mvp2_slice5_{confirmation_variant}",
                tool_name="memo.delete",
                caused_by_event_id=caused_by_event_id,
                event_id_prefix=f"evt_mvp2_slice5_{confirmation_variant}",
                start_task_event_seq=9,
                idempotency_key=f"idem://synthetic/mvp2/slice5/{confirmation_variant}",
                arguments={"memo_item_id": "memo_item_000001"},
                argument_provenance={"memo_item_id": "evt_mvp2_slice5_arguments_resolved"},
                accepted_confirmation_event_id=str(terminal_confirmation["event_id"]),
                accepted_confirmation_id=confirmation_id,
                accepted_confirmation_scope=accepted_scope,
                accepted_confirmation_plan_version=accepted_plan_version,
            )
        )

    event_names = [event["event_name"] for event in journal.events()]
    assert "TOOL_EXECUTION_AUTHORIZED" not in event_names
    assert "TOOL_EXECUTION_STARTED" not in event_names
    assert "TOOL_UI_STATE_PATCHED" not in event_names
    assert backend.executed_calls == ()


@pytest.mark.parametrize(
    ("arguments", "argument_provenance", "expected_missing"),
    [
        ({}, {}, ("memo_item_id",)),
        ({"memo_item_id": "memo_item_000001"}, {}, ("provenance.memo_item_id",)),
    ],
)
def test_missing_args_or_provenance_blocks_before_confirmation_or_backend_execution(
    arguments: Mapping[str, object],
    argument_provenance: Mapping[str, str],
    expected_missing: tuple[str, ...],
) -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry([memo_delete_manifest()]),
        backend=backend,
    )

    result = executor.execute(
        _request(
            tool_call_id="tool_call_mvp2_slice5_memo_delete_blocked",
            tool_name="memo.delete",
            caused_by_event_id=caused_by_event_id,
            event_id_prefix="evt_mvp2_slice5_memo_delete_blocked",
            idempotency_key="idem://synthetic/mvp2/slice5/memo-delete-blocked",
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
    assert "TOOL_EXECUTION_AUTHORIZED" not in [event["event_name"] for event in result.produced_events]
    assert "TOOL_EXECUTION_STARTED" not in [event["event_name"] for event in result.produced_events]
    assert backend.executed_calls == ()


@pytest.mark.parametrize("side_effect_class", BLOCKED_SIDE_EFFECT_CLASSES)
def test_blocked_side_effect_classes_remain_blocked_before_destructive_backend_execution(
    side_effect_class: str,
) -> None:
    journal, caused_by_event_id = _started_journal()
    backend = InMemoryDemoBackend()
    executor = DemoToolExecutor(
        journal=journal,
        registry=ToolRegistry(
            [_memo_delete_manifest_with_side_effect(side_effect_class)],
            validate_side_effect_classes=False,
        ),
        backend=backend,
    )

    with pytest.raises(ToolExecutionPolicyError, match="side_effect_class is not allowed"):
        executor.execute(
            _request(
                tool_call_id="tool_call_mvp2_slice5_blocked_side_effect",
                tool_name="memo.delete",
                caused_by_event_id=caused_by_event_id,
                event_id_prefix="evt_mvp2_slice5_blocked_side_effect",
                idempotency_key=f"idem://synthetic/mvp2/slice5/{side_effect_class.lower()}",
                arguments={"memo_item_id": "memo_item_000001"},
                argument_provenance={"memo_item_id": "evt_mvp2_slice5_arguments_resolved"},
            )
        )

    assert not any(event["event_name"].startswith("TOOL_") for event in journal.events())
    assert backend.executed_calls == ()


def _started_journal() -> tuple[object, str]:
    startup = start_mvp0_session(
        session_id="sess_mvp2_slice5",
        conversation_id="conv_mvp2_slice5",
        runtime_config_ref="config://synthetic/mvp2/slice5",
        created_monotonic_ms=1,
        created_wall_clock_ms=1700000070001,
    )
    created = startup.journal.append(
        event_name="SLOWTASK_CREATED",
        event_id="evt_mvp2_slice5_slowtask_created",
        source_module="slowtask_runtime",
        caused_by_event_id=str(startup.journal.events()[-1]["event_id"]),
        created_monotonic_ms=10,
        created_wall_clock_ms=1700000070010,
        trace_redaction_level="metadata_only",
        task_id="task_mvp2_slice5",
        plan_version=1,
        task_event_seq=1,
        initial_goal_ref="goal://synthetic/mvp2/slice5/demo-destructive-confirmation",
        source_evidence_refs=["evidence://synthetic/mvp2/slice5/spawn"],
    )
    arguments_resolved = startup.journal.append(
        event_name="ARGUMENTS_RESOLVED",
        event_id="evt_mvp2_slice5_arguments_resolved",
        source_module="slowtask_runtime",
        caused_by_event_id=str(created["event_id"]),
        created_monotonic_ms=11,
        created_wall_clock_ms=1700000070011,
        trace_redaction_level="metadata_only",
        task_id="task_mvp2_slice5",
        plan_version=1,
        task_event_seq=2,
        resolved_arguments_ref="args://synthetic/mvp2/slice5/current-plan/ready",
        provenance_ref="provenance://synthetic/mvp2/slice5/current-plan/ready",
    )
    return startup.journal, str(arguments_resolved["event_id"])


def _append_confirmation_chain(
    journal: object,
    *,
    caused_by_event_id: str,
    confirmation_id: str,
    start_task_event_seq: int,
    confirmation_scope: str = "DEMO_DESTRUCTIVE_ACTION",
    required_for_event_id: str | None = None,
    patch_caused_by_event_id: str | None = None,
    route_through_router: bool = True,
    router_has_turn_evidence: bool = True,
    accepted: bool = True,
) -> dict[str, object]:
    required = journal.append(
        event_name="CONFIRMATION_REQUIRED",
        event_id=f"evt_mvp2_slice5_{confirmation_id}_required",
        source_module="slowtask_runtime",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=50,
        created_wall_clock_ms=1700000070050,
        trace_redaction_level="metadata_only",
        confirmation_id=confirmation_id,
        task_id="task_mvp2_slice5",
        plan_version=1,
        task_event_seq=start_task_event_seq,
        confirmation_scope=confirmation_scope,
        required_for_event_id=required_for_event_id or caused_by_event_id,
        prompt_ref=f"prompt://synthetic/mvp2/slice5/{confirmation_id}",
    )
    waiting = journal.append(
        event_name="WAITING_FOR_USER_CONFIRMATION",
        event_id=f"evt_mvp2_slice5_{confirmation_id}_waiting",
        source_module="slowtask_runtime",
        caused_by_event_id=str(required["event_id"]),
        created_monotonic_ms=51,
        created_wall_clock_ms=1700000070051,
        trace_redaction_level="metadata_only",
        task_id="task_mvp2_slice5",
        plan_version=1,
        task_event_seq=start_task_event_seq + 1,
        confirmation_id=confirmation_id,
    )
    if route_through_router and patch_caused_by_event_id is None:
        patch_caused_by_event_id = f"evt_mvp2_slice5_router_{confirmation_id}"
    if patch_caused_by_event_id is not None and patch_caused_by_event_id.startswith("evt_mvp2_slice5_router"):
        router_caused_by_event_id = str(waiting["event_id"])
        turn_id = f"turn_mvp2_slice5_{confirmation_id}"
        utterance_id = f"utt_mvp2_slice5_{confirmation_id}"
        turn_event_id = f"evt_mvp2_slice5_turn_{confirmation_id}"
        thinker_event_id = f"evt_mvp2_slice5_thinker_{confirmation_id}"
        if router_has_turn_evidence:
            turn = journal.append(
                event_name="TURN_INGRESS_COMMITTED",
                event_id=turn_event_id,
                source_module="interaction_controller",
                caused_by_event_id=str(waiting["event_id"]),
                created_monotonic_ms=52,
                created_wall_clock_ms=1700000070052,
                trace_redaction_level="metadata_only",
                turn_id=turn_id,
                utterance_id=utterance_id,
                input_modality="text",
                input_span_id=f"input_mvp2_slice5_{confirmation_id}",
                text_span_id=f"text_mvp2_slice5_{confirmation_id}",
                directedness="ASSUMED_DIRECTED",
                semantic_close="ASSUMED_CLOSED",
                ingress_outcome="COMMITTED",
            )
            thinker = journal.append(
                event_name="MOCK_THINKER_FRAME_EMITTED",
                event_id=thinker_event_id,
                source_module="thinker_adapter",
                caused_by_event_id=str(turn["event_id"]),
                created_monotonic_ms=53,
                created_wall_clock_ms=1700000070053,
                trace_redaction_level="metadata_only",
                turn_id=turn_id,
                utterance_id=utterance_id,
                input_modality="text",
                semantic_frame_ref=f"semantic-frame://synthetic/mvp2/slice5/{confirmation_id}",
                output_mode="mock",
            )
            router_caused_by_event_id = str(thinker["event_id"])
        journal.append(
            event_name="ROUTER_DECISION_EMITTED",
            event_id=patch_caused_by_event_id,
            source_module="router",
            caused_by_event_id=router_caused_by_event_id,
            created_monotonic_ms=54,
            created_wall_clock_ms=1700000070054,
            trace_redaction_level="metadata_only",
            turn_id=turn_id,
            utterance_id=utterance_id,
            router_decision="PATCH_ACTIVE_SLOW_TASK",
            task_focus="ACTIVE_TASK_PATCH",
            active_task_id="task_mvp2_slice5",
            confidence=0.91,
            evidence_uncertainty="low",
            turn_committed_event_id=turn_event_id,
            thinker_frame_event_id=thinker_event_id,
        )
    patch_received = journal.append(
        event_name="USER_PATCH_RECEIVED",
        event_id=f"evt_mvp2_slice5_{confirmation_id}_patch_received",
        source_module="user_patch_pipeline",
        caused_by_event_id=patch_caused_by_event_id or str(waiting["event_id"]),
        created_monotonic_ms=52,
        created_wall_clock_ms=1700000070052,
        trace_redaction_level="metadata_only",
        patch_id=f"patch_mvp2_slice5_{confirmation_id}",
        task_id="task_mvp2_slice5",
        plan_version=1,
        task_event_seq=start_task_event_seq + 2,
        observed_plan_version=1,
        evidence_ref=f"evidence://synthetic/mvp2/slice5/{confirmation_id}/confirmation",
    )
    interpreted = journal.append(
        event_name="USER_PATCH_INTERPRETED",
        event_id=f"evt_mvp2_slice5_{confirmation_id}_patch_interpreted",
        source_module="slowtask_runtime",
        caused_by_event_id=str(patch_received["event_id"]),
        created_monotonic_ms=53,
        created_wall_clock_ms=1700000070053,
        trace_redaction_level="metadata_only",
        patch_id=f"patch_mvp2_slice5_{confirmation_id}",
        task_id="task_mvp2_slice5",
        plan_version=1,
        task_event_seq=start_task_event_seq + 3,
        observed_plan_version=1,
        interpreted_against_plan_version=1,
        interpretation_type="confirmation",
        materially_changes_task=False,
        interpretation_reason="synthetic_confirmation",
        source_evidence_refs=[f"evidence://synthetic/mvp2/slice5/{confirmation_id}/confirmation"],
    )
    received = journal.append(
        event_name="USER_CONFIRMATION_RECEIVED",
        event_id=f"evt_mvp2_slice5_{confirmation_id}_received",
        source_module="slowtask_runtime",
        caused_by_event_id=str(interpreted["event_id"]),
        created_monotonic_ms=54,
        created_wall_clock_ms=1700000070054,
        trace_redaction_level="metadata_only",
        confirmation_id=confirmation_id,
        patch_id=f"patch_mvp2_slice5_{confirmation_id}",
        task_id="task_mvp2_slice5",
        plan_version=1,
        task_event_seq=start_task_event_seq + 4,
        confirmation_signal="accepted" if accepted else "rejected",
    )
    if not accepted:
        return journal.append(
            event_name="CONFIRMATION_REJECTED",
            event_id=f"evt_mvp2_slice5_{confirmation_id}_rejected",
            source_module="slowtask_runtime",
            caused_by_event_id=str(received["event_id"]),
            created_monotonic_ms=55,
            created_wall_clock_ms=1700000070055,
            trace_redaction_level="metadata_only",
            confirmation_id=confirmation_id,
            task_id="task_mvp2_slice5",
            plan_version=1,
            task_event_seq=start_task_event_seq + 5,
            rejection_reason="synthetic_rejected",
        )
    return journal.append(
        event_name="CONFIRMATION_ACCEPTED",
        event_id=f"evt_mvp2_slice5_{confirmation_id}_accepted",
        source_module="slowtask_runtime",
        caused_by_event_id=str(received["event_id"]),
        created_monotonic_ms=55,
        created_wall_clock_ms=1700000070055,
        trace_redaction_level="metadata_only",
        confirmation_id=confirmation_id,
        task_id="task_mvp2_slice5",
        plan_version=1,
        task_event_seq=start_task_event_seq + 5,
        accepted_scope=confirmation_scope,
        authorization_ref=f"authorization://synthetic/mvp2/slice5/{confirmation_id}",
    )


def _request(
    *,
    tool_call_id: str,
    tool_name: str,
    caused_by_event_id: str,
    event_id_prefix: str,
    idempotency_key: str,
    arguments: Mapping[str, object],
    argument_provenance: Mapping[str, str],
    start_task_event_seq: int = 3,
    plan_version: int = 1,
    current_plan_version: int = 1,
    accepted_confirmation_event_id: str | None = None,
    accepted_confirmation_id: str | None = None,
    accepted_confirmation_scope: str | None = None,
    accepted_confirmation_plan_version: int | None = None,
    resolved_arguments_ref: str = "args://synthetic/mvp2/slice5/tool/ready",
    provenance_ref: str = "provenance://synthetic/mvp2/slice5/tool/ready",
) -> ToolExecutionRequest:
    return ToolExecutionRequest(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        task_id="task_mvp2_slice5",
        plan_version=plan_version,
        current_plan_version=current_plan_version,
        start_task_event_seq=start_task_event_seq,
        caused_by_event_id=caused_by_event_id,
        event_id_prefix=event_id_prefix,
        created_monotonic_ms=100,
        created_wall_clock_ms=1700000070100,
        idempotency_key=idempotency_key,
        arguments=arguments,
        argument_provenance=argument_provenance,
        resolved_arguments_ref=resolved_arguments_ref,
        provenance_ref=provenance_ref,
        preview_ref=f"preview://synthetic/mvp2/slice5/{tool_name}",
        accepted_confirmation_event_id=accepted_confirmation_event_id,
        accepted_confirmation_id=accepted_confirmation_id,
        accepted_confirmation_scope=accepted_confirmation_scope,
        accepted_confirmation_plan_version=accepted_confirmation_plan_version,
    )


def _preview_destructive_request(
    executor: DemoToolExecutor,
    request: ToolExecutionRequest,
) -> object:
    before = len(executor._journal.events())  # type: ignore[attr-defined]
    with pytest.raises(ToolExecutionPolicyError, match="current-plan CONFIRMATION_ACCEPTED"):
        executor.execute(request)
    produced_events = tuple(executor._journal.events()[before:])  # type: ignore[attr-defined]
    assert [event["event_name"] for event in produced_events] == [
        "TOOL_MANIFEST_LOADED",
        "TOOL_ARGUMENTS_READY",
        "TOOL_PREVIEW_AVAILABLE",
    ]
    return type("PreviewResult", (), {"produced_events": produced_events})()


def _memo_delete_manifest_with_side_effect(side_effect_class: str) -> ToolManifest:
    return ToolManifest(
        tool_name="memo.delete",
        tool_adapter_id="demo.memo.delete",
        tool_manifest_version="2026-05-18.slice5",
        tool_category="DEMO_STATE_WRITE",
        side_effect_class=side_effect_class,
        risk_class="LOW",
        required_arguments=("memo_item_id",),
        optional_arguments=(),
        argument_provenance_requirements=("memo_item_id",),
        result_type="memo_delete",
        trust_level="TRUSTED_DEMO_TOOL_RESULT",
        source_type="DEMO_SANDBOX",
        preview_required=True,
        confirmation_required=True,
        ui_patch_capable=True,
        idempotency_required=True,
        sandbox_state_namespace="memo",
        capability="mock",
    )


def _expected_ui_patch_id(*, namespace: str, operation: str, idempotency_key: str) -> str:
    digest = sha256(f"{namespace}:{operation}:{idempotency_key}".encode("utf-8")).hexdigest()[:16]
    return f"ui_patch_{namespace}_{operation}_{digest}"
