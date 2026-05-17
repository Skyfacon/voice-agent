from __future__ import annotations

import pytest

from voice_agent.state.tool_execution_state import ToolExecutionState, ToolExecutionStateError


def tool_event(event_name: str, **overrides: object) -> dict[str, object]:
    event: dict[str, object] = {
        "event_name": event_name,
        "event_id": f"evt_{event_name.lower()}_{overrides.get('task_event_seq', 1)}",
        "tool_call_id": "tool_call_slice1_001",
        "task_id": "task_slice1_001",
        "plan_version": 3,
        "task_event_seq": 1,
    }
    event.update(overrides)
    return event


def test_manifest_loaded_records_safe_manifest_metadata_without_tool_call() -> None:
    state = ToolExecutionState()

    assert state.reduce_event(
        {
            "event_name": "TOOL_MANIFEST_LOADED",
            "event_id": "evt_slice1_manifest_memo",
            "tool_name": "memo",
            "tool_adapter_id": "demo.memo",
            "tool_manifest_version": "2026-05-17.slice1",
            "side_effect_class": "SANDBOX_WRITE",
            "risk_class": "LOW",
        }
    )

    assert list(state.tool_manifests) == ["memo"]
    manifest = state.tool_manifests["memo"]
    assert manifest.event_id == "evt_slice1_manifest_memo"
    assert manifest.tool_adapter_id == "demo.memo"
    assert manifest.tool_manifest_version == "2026-05-17.slice1"
    assert manifest.side_effect_class == "SANDBOX_WRITE"
    assert state.tool_calls == {}


def test_progressive_tool_events_are_archived_by_tool_call_id_with_task_binding() -> None:
    state = ToolExecutionState()

    for event in (
        tool_event(
            "TOOL_CALL_STARTED",
            tool_name="memo",
            tool_adapter_id="demo.memo",
            idempotency_key="idem://synthetic/mvp2/slice1/memo-create",
        ),
        tool_event(
            "TOOL_ARGUMENTS_PARTIAL",
            task_event_seq=2,
            partial_arguments_ref="args://synthetic/mvp2/slice1/memo/partial",
            missing_fields=["body"],
        ),
        tool_event(
            "TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS",
            task_event_seq=3,
            blocking_fields=["body"],
            source_event_id="evt_tool_arguments_partial_2",
        ),
        tool_event(
            "TOOL_ARGUMENTS_READY",
            task_event_seq=4,
            resolved_arguments_ref="args://synthetic/mvp2/slice1/memo/ready",
            provenance_ref="provenance://synthetic/mvp2/slice1/memo/ready",
        ),
        tool_event(
            "TOOL_PREVIEW_AVAILABLE",
            task_event_seq=5,
            preview_ref="preview://synthetic/mvp2/slice1/memo/create",
            requires_confirmation=False,
        ),
        tool_event(
            "TOOL_EXECUTION_AUTHORIZED",
            task_event_seq=6,
            authorization_basis="current_plan_policy_allow",
        ),
        tool_event(
            "TOOL_EXECUTION_STARTED",
            task_event_seq=7,
            idempotency_key="idem://synthetic/mvp2/slice1/memo-create",
            authorization_event_id="evt_tool_execution_authorized_6",
        ),
        tool_event(
            "TOOL_PROGRESS_UPDATED",
            task_event_seq=8,
            progress_type="sandbox_write_pending",
            progress_ref="progress://synthetic/mvp2/slice1/memo/pending",
        ),
        tool_event(
            "TOOL_UI_STATE_PATCHED",
            task_event_seq=9,
            ui_patch_id="ui_patch_slice1_memo_create",
            idempotency_key="idem://synthetic/mvp2/slice1/memo-create",
            patch_ref="patch://synthetic/mvp2/slice1/memo/create",
        ),
        tool_event(
            "TOOL_RESULT_RECEIVED",
            task_event_seq=10,
            result_status="SUCCEEDED",
            result_ref="result://synthetic/mvp2/slice1/memo/create",
            trust_level="TRUSTED_DEMO_TOOL_RESULT",
            source_type="DEMO_SANDBOX",
        ),
    ):
        assert state.reduce_event(event)

    call = state.tool_calls["tool_call_slice1_001"]
    assert call.lifecycle_status == "RESULT_RECEIVED"
    assert call.tool_name == "memo"
    assert call.task_id == "task_slice1_001"
    assert call.plan_version == 3
    assert call.current_task_event_seq == 10
    assert [event.event_name for event in call.events] == [
        "TOOL_CALL_STARTED",
        "TOOL_ARGUMENTS_PARTIAL",
        "TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS",
        "TOOL_ARGUMENTS_READY",
        "TOOL_PREVIEW_AVAILABLE",
        "TOOL_EXECUTION_AUTHORIZED",
        "TOOL_EXECUTION_STARTED",
        "TOOL_PROGRESS_UPDATED",
        "TOOL_UI_STATE_PATCHED",
        "TOOL_RESULT_RECEIVED",
    ]
    assert call.partial_arguments[-1].missing_fields == ("body",)
    assert call.blocked_events[-1].blocking_fields == ("body",)
    assert call.ready_arguments[-1].resolved_arguments_ref == "args://synthetic/mvp2/slice1/memo/ready"
    assert call.preview_events[-1].preview_ref == "preview://synthetic/mvp2/slice1/memo/create"
    assert call.authorizations[-1].authorization_basis == "current_plan_policy_allow"
    assert call.execution_started[-1].authorization_event_id == "evt_tool_execution_authorized_6"
    assert call.progress_updates[-1].progress_ref == "progress://synthetic/mvp2/slice1/memo/pending"
    assert call.ui_patches[-1].patch_ref == "patch://synthetic/mvp2/slice1/memo/create"
    assert call.results[-1].result_ref == "result://synthetic/mvp2/slice1/memo/create"
    assert call.results[-1].task_event_seq == 10


def test_execution_started_preserves_authorization_link_from_caused_by_event_id() -> None:
    state = ToolExecutionState()

    state.reduce_event(
        tool_event(
            "TOOL_EXECUTION_AUTHORIZED",
            event_id="evt_tool_execution_authorized_via_caused_by",
            task_event_seq=1,
            authorization_basis="current_plan_policy_allow",
        )
    )
    state.reduce_event(
        tool_event(
            "TOOL_EXECUTION_STARTED",
            event_id="evt_tool_execution_started_via_caused_by",
            task_event_seq=2,
            caused_by_event_id="evt_tool_execution_authorized_via_caused_by",
            idempotency_key="idem://synthetic/mvp2/slice1/caused-by-auth",
        )
    )

    call = state.tool_calls["tool_call_slice1_001"]
    assert call.execution_started[-1].authorization_event_id == "evt_tool_execution_authorized_via_caused_by"


def test_task_event_seq_is_monotonic_across_tool_calls_in_same_task() -> None:
    state = ToolExecutionState()

    state.reduce_event(
        tool_event(
            "TOOL_CALL_STARTED",
            event_id="evt_tool_call_started_first_call",
            task_event_seq=3,
            tool_call_id="tool_call_slice1_first",
            tool_name="memo",
            tool_adapter_id="demo.memo",
            idempotency_key="idem://synthetic/mvp2/slice1/first-call",
        )
    )

    with pytest.raises(ToolExecutionStateError, match="task_event_seq must increase monotonically per task_id"):
        state.reduce_event(
            tool_event(
                "TOOL_CALL_STARTED",
                event_id="evt_tool_call_started_second_call_duplicate_seq",
                task_event_seq=3,
                tool_call_id="tool_call_slice1_second",
                tool_name="weather",
                tool_adapter_id="demo.weather",
                idempotency_key="idem://synthetic/mvp2/slice1/second-call",
            )
        )


def test_failure_retry_and_cancel_metadata_remain_recorded_not_executed() -> None:
    state = ToolExecutionState()

    for event in (
        tool_event(
            "TOOL_CALL_STARTED",
            tool_name="weather",
            idempotency_key="idem://synthetic/mvp2/slice1/weather",
        ),
        tool_event(
            "TOOL_EXECUTION_STARTED",
            task_event_seq=2,
            idempotency_key="idem://synthetic/mvp2/slice1/weather",
        ),
        tool_event(
            "TOOL_EXECUTION_FAILED",
            task_event_seq=3,
            failure_reason="synthetic_timeout",
            retryable=True,
        ),
        tool_event(
            "TOOL_CALL_RETRYING",
            task_event_seq=4,
            retry_count=1,
            retry_reason="retryable_synthetic_timeout",
        ),
        tool_event(
            "TOOL_EXECUTION_CANCEL_REQUESTED",
            task_event_seq=5,
            cancel_reason="plan_superseded",
        ),
        tool_event(
            "TOOL_EXECUTION_CANCELLED",
            task_event_seq=6,
            cancel_request_event_id="evt_tool_execution_cancel_requested_5",
            cancel_status="cancelled_before_side_effect",
        ),
    ):
        assert state.reduce_event(event)

    call = state.tool_calls["tool_call_slice1_001"]
    assert call.lifecycle_status == "CANCELLED"
    assert call.failures[-1].failure_reason == "synthetic_timeout"
    assert call.failures[-1].retryable is True
    assert call.retries[-1].retry_count == 1
    assert call.cancel_requests[-1].cancel_reason == "plan_superseded"
    assert call.cancellations[-1].cancel_status == "cancelled_before_side_effect"
    assert "demo_state" not in state.to_digest_dict()


def test_unknown_events_are_ignored_by_tool_execution_state() -> None:
    state = ToolExecutionState()

    assert not state.reduce_event({"event_name": "SESSION_STARTED", "event_id": "evt_session"})
