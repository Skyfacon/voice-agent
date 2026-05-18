from __future__ import annotations

from copy import deepcopy

import pytest

from conftest import MVP2_REPLAY_FIXTURE_DIR, load_json_fixture
from voice_agent.demo_backend.in_memory import InMemoryDemoBackend
from voice_agent.replay.runner import ReplayValidationError, run_replay_fixture


DESTRUCTIVE_CONFIRMATION_FIXTURE = (
    MVP2_REPLAY_FIXTURE_DIR / "005-demo-destructive-confirmation.fixture.json"
)


def test_demo_destructive_confirmation_fixture_replays_without_backend_execution(monkeypatch) -> None:
    def fail_backend_execution(*args: object, **kwargs: object) -> object:
        raise AssertionError("deterministic replay must not execute demo backend")

    monkeypatch.setattr(InMemoryDemoBackend, "execute", fail_backend_execution)

    first = run_replay_fixture(load_json_fixture(DESTRUCTIVE_CONFIRMATION_FIXTURE))
    second = run_replay_fixture(load_json_fixture(DESTRUCTIVE_CONFIRMATION_FIXTURE))

    assert first.result_status == "passed"
    assert first.diagnostics["ignored_events"] == []
    assert first.state_digest == second.state_digest

    memo_call = first.tool_execution_state.tool_calls["tool_call_mvp2_slice5_memo_delete"]
    assert memo_call.lifecycle_status == "RESULT_RECEIVED"
    assert memo_call.authorizations[-1].authorization_basis == "current_plan_confirmation_acceptance"
    assert memo_call.authorizations[-1].confirmation_id == "confirmation_mvp2_slice5_memo_delete"
    assert memo_call.execution_started[-1].authorization_event_id == (
        "evt_mvp2_slice5_memo_delete_execution_authorized"
    )
    assert memo_call.ui_patches[-1].patch_ref.startswith("patch://synthetic/demo_backend/memo/delete/")
    assert memo_call.results[-1].result_ref == "result://synthetic/demo_backend/memo/memo_delete_000001"

    alarm_call = first.tool_execution_state.tool_calls["tool_call_mvp2_slice5_alarm_cancel"]
    assert alarm_call.authorizations[-1].confirmation_id == "confirmation_mvp2_slice5_alarm_cancel"
    assert alarm_call.ui_patches[-1].patch_ref.startswith("patch://synthetic/demo_backend/alarm/cancel/")
    assert alarm_call.results[-1].result_ref == "result://synthetic/demo_backend/alarm/alarm_cancel_000001"

    assert first.demo_ui_state.namespaces["memo"].operation_counts == {"delete": 1}
    assert first.demo_ui_state.namespaces["alarm"].operation_counts == {"cancel": 1}


def test_replay_rejects_destructive_start_without_current_plan_accepted_confirmation() -> None:
    fixture = load_json_fixture(DESTRUCTIVE_CONFIRMATION_FIXTURE)
    removed_event_ids = {
        "evt_mvp2_slice5_memo_delete_confirmation_required",
        "evt_mvp2_slice5_memo_delete_waiting_for_confirmation",
        "evt_mvp2_slice5_memo_delete_confirmation_turn_committed",
        "evt_mvp2_slice5_memo_delete_confirmation_thinker",
        "evt_mvp2_slice5_memo_delete_confirmation_router",
        "evt_mvp2_slice5_memo_delete_confirmation_patch_received",
        "evt_mvp2_slice5_memo_delete_confirmation_patch_interpreted",
        "evt_mvp2_slice5_memo_delete_user_confirmation_received",
        "evt_mvp2_slice5_memo_delete_confirmation_accepted",
    }
    fixture["events"] = [
        event
        for event in fixture["events"]
        if event["event_id"] not in removed_event_ids
    ]
    authorized = _event_by_id(fixture["events"], "evt_mvp2_slice5_memo_delete_execution_authorized")
    authorized["authorization_basis"] = "current_plan_policy_allow"
    authorized.pop("confirmation_id", None)
    authorized["caused_by_event_id"] = "evt_mvp2_slice5_memo_delete_preview_available"

    with pytest.raises(ReplayValidationError, match="DEMO_DESTRUCTIVE_ACTION requires current-plan"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_destructive_confirmation_with_wrong_scope() -> None:
    fixture = load_json_fixture(DESTRUCTIVE_CONFIRMATION_FIXTURE)
    accepted = _event_by_id(fixture["events"], "evt_mvp2_slice5_memo_delete_confirmation_accepted")
    required = _event_by_id(fixture["events"], "evt_mvp2_slice5_memo_delete_confirmation_required")
    required["confirmation_scope"] = "TASK_CANCEL"
    accepted["accepted_scope"] = "TASK_CANCEL"

    with pytest.raises(ReplayValidationError, match="DEMO_DESTRUCTIVE_ACTION requires current-plan"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_destructive_confirmation_with_stale_plan() -> None:
    fixture = load_json_fixture(DESTRUCTIVE_CONFIRMATION_FIXTURE)
    accepted = _event_by_id(fixture["events"], "evt_mvp2_slice5_memo_delete_confirmation_accepted")
    accepted["plan_version"] = 0

    with pytest.raises(ReplayValidationError, match="DEMO_DESTRUCTIVE_ACTION requires current-plan"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_destructive_confirmation_for_different_required_event_id() -> None:
    fixture = load_json_fixture(DESTRUCTIVE_CONFIRMATION_FIXTURE)
    required = _event_by_id(fixture["events"], "evt_mvp2_slice5_memo_delete_confirmation_required")
    required["required_for_event_id"] = "evt_mvp2_slice5_unrelated_tool_request"

    with pytest.raises(ReplayValidationError, match="confirmation required_for_event_id"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_destructive_confirmation_with_broken_causal_chain() -> None:
    fixture = load_json_fixture(DESTRUCTIVE_CONFIRMATION_FIXTURE)
    patch_received = _event_by_id(fixture["events"], "evt_mvp2_slice5_memo_delete_confirmation_patch_received")
    patch_received["caused_by_event_id"] = "evt_mvp2_slice5_memo_delete_confirmation_required"

    with pytest.raises(ReplayValidationError, match="confirmation causal chain"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_destructive_confirmation_without_router_mediation() -> None:
    fixture = load_json_fixture(DESTRUCTIVE_CONFIRMATION_FIXTURE)
    patch_received = _event_by_id(fixture["events"], "evt_mvp2_slice5_memo_delete_confirmation_patch_received")
    patch_received["caused_by_event_id"] = "evt_mvp2_slice5_memo_delete_waiting_for_confirmation"

    with pytest.raises(ReplayValidationError, match="confirmation causal chain"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_confirmation_router_turn_not_caused_by_waiting_prompt() -> None:
    fixture = load_json_fixture(DESTRUCTIVE_CONFIRMATION_FIXTURE)
    turn = _event_by_id(fixture["events"], "evt_mvp2_slice5_memo_delete_confirmation_turn_committed")
    turn["caused_by_event_id"] = "evt_mvp2_slice5_memo_delete_confirmation_required"

    with pytest.raises(ReplayValidationError, match="confirmation causal chain"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_destructive_confirmation_with_different_preview_arguments() -> None:
    fixture = load_json_fixture(DESTRUCTIVE_CONFIRMATION_FIXTURE)
    _insert_memo_delete_execution_arguments_mismatch(fixture["events"])

    with pytest.raises(ReplayValidationError, match="previewed arguments"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_accepts_superseded_argument_snapshot_before_confirmed_preview() -> None:
    fixture = load_json_fixture(DESTRUCTIVE_CONFIRMATION_FIXTURE)
    _insert_superseded_memo_delete_arguments_before_preview(fixture["events"])

    replay = run_replay_fixture(deepcopy(fixture))

    memo_call = replay.tool_execution_state.tool_calls["tool_call_mvp2_slice5_memo_delete"]
    assert memo_call.lifecycle_status == "RESULT_RECEIVED"
    assert memo_call.authorizations[-1].confirmation_id == "confirmation_mvp2_slice5_memo_delete"


def test_replay_rejects_destructive_confirmation_with_same_refs_but_different_argument_fingerprint() -> None:
    fixture = load_json_fixture(DESTRUCTIVE_CONFIRMATION_FIXTURE)
    _insert_memo_delete_execution_arguments_mismatch(fixture["events"], keep_refs=True)

    with pytest.raises(ReplayValidationError, match="previewed arguments"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_accepts_destructive_confirmation_from_router_user_patch_pipeline() -> None:
    fixture = load_json_fixture(DESTRUCTIVE_CONFIRMATION_FIXTURE)
    _route_memo_confirmation_patch_through_router(fixture["events"])

    replay = run_replay_fixture(deepcopy(fixture))

    memo_call = replay.tool_execution_state.tool_calls["tool_call_mvp2_slice5_memo_delete"]
    assert memo_call.lifecycle_status == "RESULT_RECEIVED"
    assert memo_call.authorizations[-1].confirmation_id == "confirmation_mvp2_slice5_memo_delete"


def test_replay_reconstructs_demo_ui_state_from_tool_ui_state_patched_only() -> None:
    fixture = load_json_fixture(DESTRUCTIVE_CONFIRMATION_FIXTURE)
    patch = _event_by_id(fixture["events"], "evt_mvp2_slice5_memo_delete_ui_state_patched")
    progress = _event_by_id(fixture["events"], "evt_mvp2_slice5_memo_delete_progress_updated")
    result = _event_by_id(fixture["events"], "evt_mvp2_slice5_memo_delete_result_received")
    fixture["events"] = [
        event
        for event in fixture["events"]
        if event["event_id"] != "evt_mvp2_slice5_memo_delete_ui_state_patched"
    ]
    result["caused_by_event_id"] = progress["event_id"]
    result["task_event_seq"] = patch["task_event_seq"]

    replay = run_replay_fixture(deepcopy(fixture))

    assert replay.tool_execution_state.tool_calls["tool_call_mvp2_slice5_memo_delete"].results[-1].result_status == (
        "SUCCEEDED"
    )
    assert "memo" not in replay.demo_ui_state.namespaces
    assert replay.demo_ui_state.namespaces["alarm"].operation_counts == {"cancel": 1}


def test_destructive_fixture_refs_do_not_embed_raw_user_args_or_secret_like_values() -> None:
    fixture = load_json_fixture(DESTRUCTIVE_CONFIRMATION_FIXTURE)

    for event in fixture["events"]:
        for key, value in event.items():
            if key.endswith("_ref") or key in {"ui_patch_id", "idempotency_key"}:
                text = str(value).lower()
                assert "memo_item_000001" not in text
                assert "alarm_item_000001" not in text
                assert "secret" not in text
                assert "token" not in text
                assert "password" not in text


def _event_by_id(events: list[dict[str, object]], event_id: str) -> dict[str, object]:
    return next(event for event in events if event["event_id"] == event_id)


def _route_memo_confirmation_patch_through_router(events: list[dict[str, object]]) -> None:
    waiting = _event_by_id(events, "evt_mvp2_slice5_memo_delete_waiting_for_confirmation")
    patch = _event_by_id(events, "evt_mvp2_slice5_memo_delete_confirmation_patch_received")
    if patch["caused_by_event_id"] == "evt_mvp2_slice5_memo_delete_confirmation_router":
        return
    insert_at = events.index(patch)
    insert_seq = int(patch["event_seq"])
    for event in events[insert_at:]:
        event["event_seq"] = int(event["event_seq"]) + 3
        event["created_monotonic_ms"] = int(event["created_monotonic_ms"]) + 3
        event["created_wall_clock_ms"] = int(event["created_wall_clock_ms"]) + 3

    turn = {
        "event_name": "TURN_INGRESS_COMMITTED",
        "event_id": "evt_mvp2_slice5_memo_delete_confirmation_turn_committed",
        "event_seq": insert_seq,
        "event_schema_version": "1.0",
        "session_id": waiting["session_id"],
        "conversation_id": waiting["conversation_id"],
        "source_module": "interaction_controller",
        "created_monotonic_ms": int(waiting["created_monotonic_ms"]) + 1,
        "created_wall_clock_ms": int(waiting["created_wall_clock_ms"]) + 1,
        "caused_by_event_id": waiting["event_id"],
        "trace_redaction_level": "metadata_only",
        "turn_id": "turn_mvp2_slice5_memo_delete_confirm",
        "utterance_id": "utt_mvp2_slice5_memo_delete_confirm",
        "input_modality": "text",
        "input_span_id": "input_mvp2_slice5_memo_delete_confirm",
        "text_span_id": "text_mvp2_slice5_memo_delete_confirm",
        "directedness": "ASSUMED_DIRECTED",
        "semantic_close": "ASSUMED_CLOSED",
        "ingress_outcome": "COMMITTED",
    }
    thinker = {
        "event_name": "MOCK_THINKER_FRAME_EMITTED",
        "event_id": "evt_mvp2_slice5_memo_delete_confirmation_thinker",
        "event_seq": insert_seq + 1,
        "event_schema_version": "1.0",
        "session_id": waiting["session_id"],
        "conversation_id": waiting["conversation_id"],
        "source_module": "thinker_adapter",
        "created_monotonic_ms": int(waiting["created_monotonic_ms"]) + 2,
        "created_wall_clock_ms": int(waiting["created_wall_clock_ms"]) + 2,
        "caused_by_event_id": turn["event_id"],
        "trace_redaction_level": "metadata_only",
        "turn_id": turn["turn_id"],
        "utterance_id": turn["utterance_id"],
        "input_modality": "text",
        "semantic_frame_ref": "semantic-frame://synthetic/mvp2/slice5/memo-delete-confirmation",
        "output_mode": "mock",
    }
    router = {
        "event_name": "ROUTER_DECISION_EMITTED",
        "event_id": "evt_mvp2_slice5_memo_delete_confirmation_router",
        "event_seq": insert_seq + 2,
        "event_schema_version": "1.0",
        "session_id": waiting["session_id"],
        "conversation_id": waiting["conversation_id"],
        "source_module": "router",
        "created_monotonic_ms": int(waiting["created_monotonic_ms"]) + 3,
        "created_wall_clock_ms": int(waiting["created_wall_clock_ms"]) + 3,
        "caused_by_event_id": thinker["event_id"],
        "trace_redaction_level": "metadata_only",
        "turn_id": turn["turn_id"],
        "utterance_id": turn["utterance_id"],
        "router_decision": "PATCH_ACTIVE_SLOW_TASK",
        "task_focus": "ACTIVE_TASK_PATCH",
        "active_task_id": waiting["task_id"],
        "confidence": 0.91,
        "evidence_uncertainty": "low",
        "turn_committed_event_id": turn["event_id"],
        "thinker_frame_event_id": thinker["event_id"],
    }
    patch["caused_by_event_id"] = router["event_id"]
    events[insert_at:insert_at] = [turn, thinker, router]


def _insert_superseded_memo_delete_arguments_before_preview(events: list[dict[str, object]]) -> None:
    arguments = _event_by_id(events, "evt_mvp2_slice5_memo_delete_arguments_ready")
    insert_at = events.index(arguments)
    insert_event_seq = int(arguments["event_seq"])
    insert_task_event_seq = int(arguments["task_event_seq"])
    for event in events[insert_at:]:
        event["event_seq"] = int(event["event_seq"]) + 1
        event["created_monotonic_ms"] = int(event["created_monotonic_ms"]) + 1
        event["created_wall_clock_ms"] = int(event["created_wall_clock_ms"]) + 1
        if event.get("task_id") == "task_mvp2_slice5" and "task_event_seq" in event:
            event["task_event_seq"] = int(event["task_event_seq"]) + 1

    events.insert(
        insert_at,
        {
            "event_name": "TOOL_ARGUMENTS_READY",
            "event_id": "evt_mvp2_slice5_memo_delete_superseded_arguments_ready",
            "event_seq": insert_event_seq,
            "event_schema_version": "1.0",
            "session_id": arguments["session_id"],
            "conversation_id": arguments["conversation_id"],
            "source_module": "tool_executor",
            "created_monotonic_ms": int(arguments["created_monotonic_ms"]),
            "created_wall_clock_ms": int(arguments["created_wall_clock_ms"]),
            "caused_by_event_id": arguments["caused_by_event_id"],
            "trace_redaction_level": "metadata_only",
            "tool_call_id": "tool_call_mvp2_slice5_memo_delete",
            "task_id": "task_mvp2_slice5",
            "plan_version": 1,
            "task_event_seq": insert_task_event_seq,
            "tool_name": "memo.delete",
            "resolved_arguments_ref": "args://synthetic/mvp2/slice5/memo-delete/superseded",
            "provenance_ref": "provenance://synthetic/mvp2/slice5/memo-delete/superseded",
            "argument_fingerprint": "sha256:superseded-argument-snapshot",
        },
    )


def _insert_memo_delete_execution_arguments_mismatch(
    events: list[dict[str, object]],
    *,
    keep_refs: bool = False,
) -> None:
    authorization = _event_by_id(events, "evt_mvp2_slice5_memo_delete_execution_authorized")
    accepted = _event_by_id(events, "evt_mvp2_slice5_memo_delete_confirmation_accepted")
    preview_arguments = _event_by_id(events, "evt_mvp2_slice5_memo_delete_arguments_ready")
    insert_at = events.index(authorization)
    insert_event_seq = int(authorization["event_seq"])
    insert_task_event_seq = int(authorization["task_event_seq"])
    for event in events[insert_at:]:
        event["event_seq"] = int(event["event_seq"]) + 1
        event["created_monotonic_ms"] = int(event["created_monotonic_ms"]) + 1
        event["created_wall_clock_ms"] = int(event["created_wall_clock_ms"]) + 1
        if event.get("task_id") == "task_mvp2_slice5" and "task_event_seq" in event:
            event["task_event_seq"] = int(event["task_event_seq"]) + 1

    events.insert(
        insert_at,
        {
            "event_name": "TOOL_ARGUMENTS_READY",
            "event_id": "evt_mvp2_slice5_memo_delete_execute_arguments_ready_mismatch",
            "event_seq": insert_event_seq,
            "event_schema_version": "1.0",
            "session_id": accepted["session_id"],
            "conversation_id": accepted["conversation_id"],
            "source_module": "tool_executor",
            "created_monotonic_ms": int(accepted["created_monotonic_ms"]) + 1,
            "created_wall_clock_ms": int(accepted["created_wall_clock_ms"]) + 1,
            "caused_by_event_id": accepted["event_id"],
            "trace_redaction_level": "metadata_only",
            "tool_call_id": "tool_call_mvp2_slice5_memo_delete",
            "task_id": "task_mvp2_slice5",
            "plan_version": 1,
            "task_event_seq": insert_task_event_seq,
            "tool_name": "memo.delete",
            "resolved_arguments_ref": (
                preview_arguments["resolved_arguments_ref"]
                if keep_refs
                else "args://synthetic/mvp2/slice5/memo-delete/mismatch"
            ),
            "provenance_ref": (
                preview_arguments["provenance_ref"]
                if keep_refs
                else "provenance://synthetic/mvp2/slice5/memo-delete/mismatch"
            ),
            "argument_fingerprint": "sha256:different-runtime-arguments",
        },
    )
