from __future__ import annotations

from copy import deepcopy

import pytest

from conftest import MVP2_REPLAY_FIXTURE_DIR, load_json_fixture
from voice_agent.replay.runner import ReplayValidationError, run_replay_fixture


TOOL_EXECUTION_FIXTURE = MVP2_REPLAY_FIXTURE_DIR / "001-tool-execution-state.fixture.json"


def test_mvp2_tool_execution_fixture_reconstructs_recorded_tool_state_without_runtime() -> None:
    fixture = load_json_fixture(TOOL_EXECUTION_FIXTURE)

    first = run_replay_fixture(fixture)
    second = run_replay_fixture(fixture)

    assert first.result_status == "passed"
    assert first.diagnostics["ignored_events"] == []
    assert first.state_digest == second.state_digest
    assert first.state_digest["tool_execution_state_hash"]

    tool_state = first.tool_execution_state
    assert sorted(tool_state.tool_manifests) == ["memo", "weather"]

    memo_call = tool_state.tool_calls["tool_call_mvp2_slice1_memo"]
    assert memo_call.lifecycle_status == "RESULT_RECEIVED"
    assert memo_call.tool_name == "memo"
    assert memo_call.task_id == "task_mvp2_slice1"
    assert memo_call.plan_version == 1
    assert memo_call.blocked_events[-1].blocking_fields == ("body",)
    assert memo_call.execution_started[-1].authorization_event_id == "evt_mvp2_slice1_memo_execution_authorized"
    assert memo_call.ui_patches[-1].patch_ref == "patch://synthetic/mvp2/slice1/memo/create"
    assert memo_call.results[-1].result_ref == "result://synthetic/mvp2/slice1/memo/create"
    assert memo_call.results[-1].trust_level == "TRUSTED_DEMO_TOOL_RESULT"

    weather_call = tool_state.tool_calls["tool_call_mvp2_slice1_weather"]
    assert weather_call.lifecycle_status == "CANCELLED"
    assert weather_call.execution_started[-1].authorization_event_id == (
        "evt_mvp2_slice1_weather_execution_authorized"
    )
    assert weather_call.failures[-1].failure_reason == "synthetic_timeout"
    assert weather_call.retries[-1].retry_count == 1
    assert weather_call.cancel_requests[-1].cancel_reason == "plan_superseded"
    assert weather_call.cancellations[-1].cancel_status == "cancelled_before_external_read"


def test_mvp2_tool_execution_digest_uses_metadata_refs_not_raw_payloads() -> None:
    result = run_replay_fixture(load_json_fixture(TOOL_EXECUTION_FIXTURE))

    digest_repr = repr(result.state_digest)
    assert "raw" not in digest_repr.lower()
    assert "credential" not in digest_repr.lower()
    assert "token" not in digest_repr.lower()
    assert "tool_execution_state_hash" in result.state_digest


def test_waiting_for_tool_replays_as_slowtask_progress_after_execution_start() -> None:
    fixture = load_json_fixture(TOOL_EXECUTION_FIXTURE)
    started = _event_by_id(fixture["events"], "evt_mvp2_slice1_memo_execution_started")
    waiting_for_tool = {
        "event_name": "WAITING_FOR_TOOL",
        "event_id": "evt_mvp2_slice1_memo_waiting_for_tool",
        "event_seq": int(started["event_seq"]) + 1,
        "event_schema_version": "1.0",
        "session_id": started["session_id"],
        "conversation_id": started["conversation_id"],
        "source_module": "slowtask_runtime",
        "created_monotonic_ms": int(started["created_monotonic_ms"]) + 1,
        "created_wall_clock_ms": int(started["created_wall_clock_ms"]) + 1,
        "caused_by_event_id": started["event_id"],
        "trace_redaction_level": "metadata_only",
        "task_id": started["task_id"],
        "plan_version": started["plan_version"],
        "task_event_seq": int(started["task_event_seq"]) + 1,
        "tool_call_id": started["tool_call_id"],
    }
    _insert_event_after(fixture["events"], started["event_id"], waiting_for_tool)

    result = run_replay_fixture(fixture)

    task = result.slowtask_state.tasks["task_mvp2_slice1"]
    assert any(
        event.event_name == "WAITING_FOR_TOOL"
        and event.refs == ("tool_call_mvp2_slice1_memo",)
        for event in task.progress_events
    )


def test_replay_rejects_tool_execution_started_without_prior_authorization() -> None:
    fixture = load_json_fixture(TOOL_EXECUTION_FIXTURE)
    fixture["events"] = [
        event
        for event in fixture["events"]
        if event["event_id"] != "evt_mvp2_slice1_weather_execution_authorized"
    ]
    started = _event_by_id(fixture["events"], "evt_mvp2_slice1_weather_execution_started")
    started["caused_by_event_id"] = "evt_mvp2_slice1_weather_call_started"
    started.pop("authorization_event_id", None)

    with pytest.raises(ReplayValidationError, match="TOOL_EXECUTION_STARTED requires prior TOOL_EXECUTION_AUTHORIZED"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_destructive_tool_start_without_current_plan_confirmation() -> None:
    fixture = load_json_fixture(TOOL_EXECUTION_FIXTURE)
    manifest_loaded = _event_by_id(fixture["events"], "evt_mvp2_slice1_memo_manifest_loaded")
    manifest_loaded["side_effect_class"] = "DEMO_DESTRUCTIVE_ACTION"

    with pytest.raises(ReplayValidationError, match="DEMO_DESTRUCTIVE_ACTION requires current-plan CONFIRMATION_ACCEPTED"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_started_tool_name_that_conflicts_with_call_binding() -> None:
    fixture = load_json_fixture(TOOL_EXECUTION_FIXTURE)
    memo_manifest = _event_by_id(fixture["events"], "evt_mvp2_slice1_memo_manifest_loaded")
    memo_manifest["side_effect_class"] = "DEMO_DESTRUCTIVE_ACTION"
    read_only_manifest = {
        "event_name": "TOOL_MANIFEST_LOADED",
        "event_id": "evt_mvp2_slice1_read_only_manifest_loaded",
        "event_seq": int(memo_manifest["event_seq"]) + 1,
        "event_schema_version": "1.0",
        "session_id": memo_manifest["session_id"],
        "conversation_id": memo_manifest["conversation_id"],
        "source_module": "tool_executor",
        "created_monotonic_ms": int(memo_manifest["created_monotonic_ms"]) + 1,
        "created_wall_clock_ms": int(memo_manifest["created_wall_clock_ms"]) + 1,
        "caused_by_event_id": memo_manifest["event_id"],
        "trace_redaction_level": "metadata_only",
        "tool_name": "read_only_lookup",
        "tool_adapter_id": "demo.read_only_lookup",
        "tool_manifest_version": "2026-05-17.slice1",
        "side_effect_class": "READ_ONLY",
        "risk_class": "LOW",
    }
    _insert_non_task_event_after(fixture["events"], memo_manifest["event_id"], read_only_manifest)
    started = _event_by_id(fixture["events"], "evt_mvp2_slice1_memo_execution_started")
    started["tool_name"] = "read_only_lookup"

    with pytest.raises(ReplayValidationError, match="TOOL_EXECUTION_STARTED tool_name must match TOOL_CALL_STARTED"):
        run_replay_fixture(deepcopy(fixture))


@pytest.mark.parametrize(
    "side_effect_class",
    ["EXTERNAL_WRITE", "EXTERNAL_COMMUNICATION", "BOOKING_OR_PAYMENT", "DELETION"],
)
def test_replay_rejects_blocked_tool_side_effect_class_before_start(side_effect_class: str) -> None:
    fixture = load_json_fixture(TOOL_EXECUTION_FIXTURE)
    manifest_loaded = _event_by_id(fixture["events"], "evt_mvp2_slice1_memo_manifest_loaded")
    manifest_loaded["side_effect_class"] = side_effect_class

    with pytest.raises(ReplayValidationError, match="TOOL_MANIFEST_LOADED side_effect_class is not allowed"):
        run_replay_fixture(deepcopy(fixture))


@pytest.mark.parametrize(
    "side_effect_class",
    ["EXTERNAL_WRITE", "EXTERNAL_COMMUNICATION", "BOOKING_OR_PAYMENT", "DELETION"],
)
def test_replay_rejects_blocked_tool_manifest_even_without_execution_start(side_effect_class: str) -> None:
    fixture = _manifest_only_fixture(side_effect_class=side_effect_class)

    with pytest.raises(ReplayValidationError, match="TOOL_MANIFEST_LOADED side_effect_class is not allowed"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_tool_start_without_matching_manifest() -> None:
    fixture = load_json_fixture(TOOL_EXECUTION_FIXTURE)
    manifest_loaded = _event_by_id(fixture["events"], "evt_mvp2_slice1_memo_manifest_loaded")
    manifest_loaded["tool_name"] = "unrelated_manifest"

    with pytest.raises(ReplayValidationError, match="TOOL_EXECUTION_STARTED requires recorded TOOL_MANIFEST_LOADED"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_accepts_progressive_start_without_tool_call_started_when_manifest_is_unambiguous() -> None:
    fixture = _progressive_tool_fixture_without_call_marker()

    result = run_replay_fixture(fixture)

    call = result.tool_execution_state.tool_calls["tool_call_mvp2_progressive"]
    assert call.lifecycle_status == "RESULT_RECEIVED"
    assert call.ready_arguments[-1].event_id == "evt_mvp2_progressive_arguments_ready"
    assert call.execution_started[-1].authorization_event_id == "evt_mvp2_progressive_execution_authorized"
    assert result.slowtask_state.tasks["task_mvp2_progressive"].tool_results[-1].event_id == (
        "evt_mvp2_progressive_result_received"
    )


def test_replay_accepts_destructive_tool_start_after_current_plan_confirmation() -> None:
    fixture = load_json_fixture(TOOL_EXECUTION_FIXTURE)
    manifest_loaded = _event_by_id(fixture["events"], "evt_mvp2_slice1_memo_manifest_loaded")
    manifest_loaded["side_effect_class"] = "DEMO_DESTRUCTIVE_ACTION"

    preview = _event_by_id(fixture["events"], "evt_mvp2_slice1_memo_preview_available")
    confirmation_id = "confirmation_mvp2_slice1_memo_delete"
    patch_id = "patch_mvp2_slice1_memo_delete_confirm"
    confirmation_required = _task_event_after(
        preview,
        event_name="CONFIRMATION_REQUIRED",
        event_id="evt_mvp2_slice1_memo_confirmation_required",
        source_module="slowtask_runtime",
        confirmation_id=confirmation_id,
        confirmation_scope="DEMO_DESTRUCTIVE_ACTION",
        required_for_event_id=preview["event_id"],
        prompt_ref="prompt://synthetic/mvp2/slice1/memo/delete-confirmation",
    )
    waiting_for_confirmation = _task_event_after(
        confirmation_required,
        event_name="WAITING_FOR_USER_CONFIRMATION",
        event_id="evt_mvp2_slice1_memo_waiting_for_confirmation",
        source_module="slowtask_runtime",
        confirmation_id=confirmation_id,
    )
    patch_received = _task_event_after(
        waiting_for_confirmation,
        event_name="USER_PATCH_RECEIVED",
        event_id="evt_mvp2_slice1_memo_confirmation_patch_received",
        source_module="interaction_controller",
        patch_id=patch_id,
        observed_plan_version=1,
        evidence_ref="evidence://synthetic/mvp2/slice1/memo/delete-confirmation",
    )
    patch_interpreted = _task_event_after(
        patch_received,
        event_name="USER_PATCH_INTERPRETED",
        event_id="evt_mvp2_slice1_memo_confirmation_patch_interpreted",
        source_module="slowtask_runtime",
        patch_id=patch_id,
        observed_plan_version=1,
        interpreted_against_plan_version=1,
        interpretation_type="confirmation",
        materially_changes_task=False,
    )
    confirmation_received = _task_event_after(
        patch_interpreted,
        event_name="USER_CONFIRMATION_RECEIVED",
        event_id="evt_mvp2_slice1_memo_user_confirmation_received",
        source_module="slowtask_runtime",
        confirmation_id=confirmation_id,
        patch_id=patch_id,
        confirmation_signal="accepted",
    )
    confirmation_accepted = _task_event_after(
        confirmation_received,
        event_name="CONFIRMATION_ACCEPTED",
        event_id="evt_mvp2_slice1_memo_confirmation_accepted",
        source_module="slowtask_runtime",
        confirmation_id=confirmation_id,
        accepted_scope="DEMO_DESTRUCTIVE_ACTION",
        authorization_ref="authorization://synthetic/mvp2/slice1/memo/delete-confirmation",
    )
    prior_event_id = preview["event_id"]
    for inserted_event in (
        confirmation_required,
        waiting_for_confirmation,
        patch_received,
        patch_interpreted,
        confirmation_received,
        confirmation_accepted,
    ):
        _insert_event_after(fixture["events"], prior_event_id, inserted_event)
        prior_event_id = inserted_event["event_id"]

    authorized = _event_by_id(fixture["events"], "evt_mvp2_slice1_memo_execution_authorized")
    authorized["caused_by_event_id"] = confirmation_accepted["event_id"]
    authorized["authorization_basis"] = "current_plan_confirmation_acceptance"
    authorized["confirmation_id"] = confirmation_id

    result = run_replay_fixture(deepcopy(fixture))

    memo_call = result.tool_execution_state.tool_calls["tool_call_mvp2_slice1_memo"]
    assert memo_call.authorizations[-1].confirmation_id == confirmation_id
    assert memo_call.lifecycle_status == "RESULT_RECEIVED"


def test_replay_rejects_tool_cancel_request_without_slowtask_plan_or_cancel_decision() -> None:
    fixture = load_json_fixture(TOOL_EXECUTION_FIXTURE)
    cancel_requested = _event_by_id(fixture["events"], "evt_mvp2_slice1_weather_cancel_requested")
    cancel_requested["plan_version"] = 1
    cancel_requested["caused_by_event_id"] = "evt_mvp2_slice1_weather_call_retrying"

    with pytest.raises(ReplayValidationError, match="TOOL_EXECUTION_CANCEL_REQUESTED requires prior SlowTask"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_tool_cancel_request_for_call_that_never_started() -> None:
    fixture = load_json_fixture(TOOL_EXECUTION_FIXTURE)
    never_started_tool_call_id = "tool_call_mvp2_slice1_never_started"
    cancel_requested = _event_by_id(fixture["events"], "evt_mvp2_slice1_weather_cancel_requested")
    cancel_requested["tool_call_id"] = never_started_tool_call_id
    cancelled = _event_by_id(fixture["events"], "evt_mvp2_slice1_weather_execution_cancelled")
    cancelled["tool_call_id"] = never_started_tool_call_id

    with pytest.raises(ReplayValidationError, match="TOOL_EXECUTION_CANCEL_REQUESTED requires prior TOOL_EXECUTION_STARTED"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_tool_cancel_request_not_after_slowtask_decision_sequence() -> None:
    fixture = load_json_fixture(TOOL_EXECUTION_FIXTURE)
    plan_advanced = _event_by_id(fixture["events"], "evt_mvp2_slice1_weather_plan_version_advanced")
    cancel_requested = _event_by_id(fixture["events"], "evt_mvp2_slice1_weather_cancel_requested")
    cancel_requested["task_event_seq"] = plan_advanced["task_event_seq"]

    with pytest.raises(ReplayValidationError, match="task_event_seq must increase monotonically"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_tool_cancelled_with_mismatched_request_binding() -> None:
    fixture = load_json_fixture(TOOL_EXECUTION_FIXTURE)
    cancelled = _event_by_id(fixture["events"], "evt_mvp2_slice1_weather_execution_cancelled")
    cancelled["tool_call_id"] = "tool_call_mvp2_slice1_mismatched"

    with pytest.raises(ReplayValidationError, match="TOOL_EXECUTION_CANCELLED binding must match"):
        run_replay_fixture(deepcopy(fixture))


def _event_by_id(events: list[dict[str, object]], event_id: str) -> dict[str, object]:
    return next(event for event in events if event["event_id"] == event_id)


def _manifest_only_fixture(*, side_effect_class: str) -> dict[str, object]:
    return _fixture_with_events(
        [
            _session_event(),
            _tool_manifest_event(
                event_seq=2,
                event_id="evt_mvp2_manifest_only_tool_manifest_loaded",
                caused_by_event_id="evt_mvp2_minimal_session_started",
                side_effect_class=side_effect_class,
            ),
        ]
    )


def _progressive_tool_fixture_without_call_marker() -> dict[str, object]:
    session = _session_event()
    manifest = _tool_manifest_event(
        event_seq=2,
        event_id="evt_mvp2_progressive_tool_manifest_loaded",
        caused_by_event_id=session["event_id"],
        side_effect_class="READ_ONLY",
    )
    created = _minimal_task_event(
        event_seq=3,
        event_id="evt_mvp2_progressive_slowtask_created",
        event_name="SLOWTASK_CREATED",
        caused_by_event_id=manifest["event_id"],
        task_event_seq=1,
        initial_goal_ref="goal://synthetic/mvp2/progressive-tool",
        source_evidence_refs=["evidence://synthetic/mvp2/progressive-tool/spawn"],
    )
    planning = _minimal_task_event(
        event_seq=4,
        event_id="evt_mvp2_progressive_state_planning",
        event_name="SLOWTASK_STATE_CHANGED",
        caused_by_event_id=created["event_id"],
        task_event_seq=2,
        from_state="CREATED",
        to_state="PLANNING",
        reason="initial_planning_started",
    )
    arguments_ready = _minimal_task_event(
        event_seq=5,
        event_id="evt_mvp2_progressive_arguments_ready",
        event_name="TOOL_ARGUMENTS_READY",
        caused_by_event_id=planning["event_id"],
        task_event_seq=3,
        tool_call_id="tool_call_mvp2_progressive",
        resolved_arguments_ref="args://synthetic/mvp2/progressive-tool/ready",
        provenance_ref="provenance://synthetic/mvp2/progressive-tool/ready",
    )
    authorized = _minimal_task_event(
        event_seq=6,
        event_id="evt_mvp2_progressive_execution_authorized",
        event_name="TOOL_EXECUTION_AUTHORIZED",
        caused_by_event_id=arguments_ready["event_id"],
        task_event_seq=4,
        tool_call_id="tool_call_mvp2_progressive",
        authorization_basis="current_plan_policy_allow",
    )
    started = _minimal_task_event(
        event_seq=7,
        event_id="evt_mvp2_progressive_execution_started",
        event_name="TOOL_EXECUTION_STARTED",
        caused_by_event_id=authorized["event_id"],
        task_event_seq=5,
        tool_call_id="tool_call_mvp2_progressive",
        idempotency_key="idem://synthetic/mvp2/progressive-tool",
    )
    result = _minimal_task_event(
        event_seq=8,
        event_id="evt_mvp2_progressive_result_received",
        event_name="TOOL_RESULT_RECEIVED",
        caused_by_event_id=started["event_id"],
        task_event_seq=6,
        tool_call_id="tool_call_mvp2_progressive",
        result_status="SUCCEEDED",
        result_ref="result://synthetic/mvp2/progressive-tool",
        trust_level="TRUSTED_DEMO_TOOL_RESULT",
        source_type="DEMO_SANDBOX",
    )
    return _fixture_with_events([session, manifest, created, planning, arguments_ready, authorized, started, result])


def _fixture_with_events(events: list[dict[str, object]]) -> dict[str, object]:
    return {
        "replay_manifest": {
            "manifest_schema_version": "1.0",
            "replay_id": "replay_mvp2_minimal_inline",
            "source_trace_ref": "fixture://mvp2/minimal-inline",
            "replay_mode": "deterministic",
            "event_schema_version_range": ["1.0"],
            "fixture_domain": "GITHUB_ALLOWED",
            "generated_from": "hand_written_minimal",
            "contains_raw_audio": False,
            "contains_raw_trace": False,
            "contains_real_user_input": False,
            "contains_secrets": False,
            "contains_unredacted_tool_result": False,
            "contains_large_raw_web_content": False,
            "allowed_re_eval_components": [],
        },
        "events": events,
    }


def _session_event() -> dict[str, object]:
    return {
        "event_name": "SESSION_STARTED",
        "event_id": "evt_mvp2_minimal_session_started",
        "event_seq": 1,
        "event_schema_version": "1.0",
        "session_id": "sess_mvp2_minimal",
        "conversation_id": "conv_mvp2_minimal",
        "source_module": "session_runtime",
        "created_monotonic_ms": 10,
        "created_wall_clock_ms": 1700000030010,
        "trace_redaction_level": "metadata_only",
        "runtime_config_ref": "config://synthetic/mvp2/minimal",
        "capability_snapshot_ref": "capability://synthetic/mvp2/minimal",
    }


def _tool_manifest_event(
    *,
    event_seq: int,
    event_id: str,
    caused_by_event_id: object,
    side_effect_class: str,
) -> dict[str, object]:
    return {
        "event_name": "TOOL_MANIFEST_LOADED",
        "event_id": event_id,
        "event_seq": event_seq,
        "event_schema_version": "1.0",
        "session_id": "sess_mvp2_minimal",
        "conversation_id": "conv_mvp2_minimal",
        "source_module": "tool_executor",
        "created_monotonic_ms": 10 + event_seq,
        "created_wall_clock_ms": 1700000030010 + event_seq,
        "caused_by_event_id": caused_by_event_id,
        "trace_redaction_level": "metadata_only",
        "tool_name": "weather",
        "tool_adapter_id": "demo.weather",
        "tool_manifest_version": "2026-05-17.slice1",
        "side_effect_class": side_effect_class,
        "risk_class": "LOW",
    }


def _minimal_task_event(
    *,
    event_seq: int,
    event_id: str,
    event_name: str,
    caused_by_event_id: object,
    task_event_seq: int,
    **fields: object,
) -> dict[str, object]:
    event: dict[str, object] = {
        "event_name": event_name,
        "event_id": event_id,
        "event_seq": event_seq,
        "event_schema_version": "1.0",
        "session_id": "sess_mvp2_minimal",
        "conversation_id": "conv_mvp2_minimal",
        "source_module": "tool_executor" if event_name.startswith("TOOL_") else "slowtask_runtime",
        "created_monotonic_ms": 10 + event_seq,
        "created_wall_clock_ms": 1700000030010 + event_seq,
        "caused_by_event_id": caused_by_event_id,
        "trace_redaction_level": "metadata_only",
        "task_id": "task_mvp2_progressive",
        "plan_version": 1,
        "task_event_seq": task_event_seq,
    }
    event.update(fields)
    return event


def _insert_event_after(
    events: list[dict[str, object]],
    prior_event_id: object,
    inserted_event: dict[str, object],
) -> None:
    insert_at = next(index for index, event in enumerate(events) if event["event_id"] == prior_event_id) + 1
    inserted_event_seq = int(inserted_event["event_seq"])
    inserted_task_event_seq = int(inserted_event["task_event_seq"])
    for event in events[insert_at:]:
        if int(event["event_seq"]) >= inserted_event_seq:
            event["event_seq"] = int(event["event_seq"]) + 1
            event["created_monotonic_ms"] = int(event["created_monotonic_ms"]) + 1
            event["created_wall_clock_ms"] = int(event["created_wall_clock_ms"]) + 1
        if event.get("task_id") == inserted_event.get("task_id") and int(event.get("task_event_seq", 0)) >= inserted_task_event_seq:
            event["task_event_seq"] = int(event["task_event_seq"]) + 1
    events.insert(insert_at, inserted_event)


def _insert_non_task_event_after(
    events: list[dict[str, object]],
    prior_event_id: object,
    inserted_event: dict[str, object],
) -> None:
    insert_at = next(index for index, event in enumerate(events) if event["event_id"] == prior_event_id) + 1
    inserted_event_seq = int(inserted_event["event_seq"])
    for event in events[insert_at:]:
        if int(event["event_seq"]) >= inserted_event_seq:
            event["event_seq"] = int(event["event_seq"]) + 1
            event["created_monotonic_ms"] = int(event["created_monotonic_ms"]) + 1
            event["created_wall_clock_ms"] = int(event["created_wall_clock_ms"]) + 1
    events.insert(insert_at, inserted_event)


def _task_event_after(
    prior_event: dict[str, object],
    *,
    event_name: str,
    event_id: str,
    source_module: str,
    **fields: object,
) -> dict[str, object]:
    event = {
        "event_name": event_name,
        "event_id": event_id,
        "event_seq": int(prior_event["event_seq"]) + 1,
        "event_schema_version": "1.0",
        "session_id": prior_event["session_id"],
        "conversation_id": prior_event["conversation_id"],
        "source_module": source_module,
        "created_monotonic_ms": int(prior_event["created_monotonic_ms"]) + 1,
        "created_wall_clock_ms": int(prior_event["created_wall_clock_ms"]) + 1,
        "caused_by_event_id": prior_event["event_id"],
        "trace_redaction_level": "metadata_only",
        "task_id": prior_event["task_id"],
        "plan_version": prior_event["plan_version"],
        "task_event_seq": int(prior_event["task_event_seq"]) + 1,
    }
    event.update(fields)
    return event
