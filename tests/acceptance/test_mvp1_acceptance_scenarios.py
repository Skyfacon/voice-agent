from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from conftest import MVP1_REPLAY_FIXTURE_DIR, load_json_fixture
from voice_agent.replay.runner import ReplayValidationError
from voice_agent.replay.scenario_assertions import (
    MVP1AcceptanceError,
    assert_fixture_has_no_forbidden_mvp1_scope,
    assert_mvp1_fixture_is_repo_safe,
    run_mvp1_acceptance_manifest,
)


MANIFEST_INDEX = MVP1_REPLAY_FIXTURE_DIR / "manifest.index.json"
REQUIRED_SCENARIOS = [
    "MVP1-SPAWN-SLOWTASK-001",
    "MVP1-ACTIVE-PATCH-001",
    "MVP1-PLAN-ADVANCE-001",
    "MVP1-FOREGROUND-CHAT-001",
    "MVP1-AMBIGUOUS-NO-PATCH-001",
    "MVP1-WAITING-SLOT-001",
    "MVP1-STALE-RESULT-001",
    "MVP1-STALE-ADOPTED-001",
    "MVP1-CANCEL-001",
    "MVP1-SWITCH-TASK-001",
    "MVP1-FAILED-001",
    "MVP1-SEMANTIC-COMMITMENT-001",
]


def test_mvp1_acceptance_manifest_executes_required_scenarios_and_closeout_checks() -> None:
    result = run_mvp1_acceptance_manifest(
        load_json_fixture(MANIFEST_INDEX),
        fixture_dir=MVP1_REPLAY_FIXTURE_DIR,
    )

    assert [scenario.scenario_id for scenario in result.scenario_results] == REQUIRED_SCENARIOS
    assert {scenario.result_status for scenario in result.scenario_results} == {"passed"}
    assert result.summary["suite_id"] == "MVP1-ACCEPTANCE"
    assert result.summary["result_status"] == "passed"
    assert result.summary["scenario_count"] == len(REQUIRED_SCENARIOS)
    assert result.summary["blocking_readiness_findings"] == []
    assert result.summary["adr_update_required"] is False
    assert result.summary["hidden_future_scope_detected"] is False
    assert result.summary["validated_fixture_names"] == [
        "000-empty-mvp1-session.fixture.json",
        "002-task-focus-router.fixture.json",
        "003-slowtask-reducer-skeleton.fixture.json",
        "003-slowtask-failed-sticky.fixture.json",
        "004-spawn-planning-completed.fixture.json",
        "005-active-patch-evidence.fixture.json",
        "006-plan-advance-replanning.fixture.json",
        "007-evidence-review-waiting-slot.fixture.json",
        "008-stale-result-no-adoption.fixture.json",
        "008-stale-result-adopted.fixture.json",
        "009-cancel-confirmation.fixture.json",
        "009-switch-task-confirmation-accepted.fixture.json",
        "009-switch-task-confirmation-rejected.fixture.json",
    ]


def test_mvp1_acceptance_reports_synthetic_eval_table_metadata() -> None:
    result = run_mvp1_acceptance_manifest(
        load_json_fixture(MANIFEST_INDEX),
        fixture_dir=MVP1_REPLAY_FIXTURE_DIR,
    )

    assert result.synthetic_eval_table == (
        {
            "measurement": "patch_focus_correctness",
            "fixture": "005-active-patch-evidence.fixture.json",
            "output_mode": "mock",
            "result_status": "passed",
        },
        {
            "measurement": "ambiguity_no_patch_behavior",
            "fixture": "002-task-focus-router.fixture.json",
            "output_mode": "mock",
            "result_status": "passed",
        },
        {
            "measurement": "user_patch_interpretation_materiality",
            "fixture": "006-plan-advance-replanning.fixture.json",
            "output_mode": "mock",
            "result_status": "passed",
        },
    )


def test_mvp1_acceptance_rejects_real_output_mode_in_eval_metadata() -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)
    manifest["synthetic_eval_table"][0]["output_mode"] = "real"

    with pytest.raises(MVP1AcceptanceError, match="real"):
        run_mvp1_acceptance_manifest(
            manifest,
            fixture_dir=MVP1_REPLAY_FIXTURE_DIR,
        )


def test_mvp1_acceptance_replays_task_focus_slowtask_privacy_and_digest_state() -> None:
    result = run_mvp1_acceptance_manifest(
        load_json_fixture(MANIFEST_INDEX),
        fixture_dir=MVP1_REPLAY_FIXTURE_DIR,
    )
    active_patch = next(
        scenario
        for scenario in result.scenario_results
        if scenario.scenario_id == "MVP1-ACTIVE-PATCH-001"
    )
    stale_no_adoption = next(
        scenario
        for scenario in result.scenario_results
        if scenario.scenario_id == "MVP1-STALE-RESULT-001"
    )

    assert active_patch.assertion_summary["active_task_id"] == "task_mvp1_slice5_active"
    assert active_patch.assertion_summary["patch_count"] == 1
    assert active_patch.assertion_summary["current_plan_version"] == 1
    assert active_patch.state_digest["task_focus_state_hash"]
    assert active_patch.state_digest["slowtask_state_hash"]
    assert active_patch.state_digest["trace_privacy_state_hash"]

    assert stale_no_adoption.assertion_summary["current_plan_version"] == 2
    assert stale_no_adoption.assertion_summary["adopted_evidence_count"] == 0
    assert stale_no_adoption.assertion_summary["semantic_commitment_count"] == 0


def test_mvp1_acceptance_rejects_missing_required_scenario() -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)
    manifest["required_scenarios"] = manifest["required_scenarios"][:-1]

    with pytest.raises(MVP1AcceptanceError, match="required_scenarios"):
        run_mvp1_acceptance_manifest(
            manifest,
            fixture_dir=MVP1_REPLAY_FIXTURE_DIR,
        )


def test_mvp1_acceptance_rejects_manifest_that_weakens_forbidden_source_modules() -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)
    manifest["forbidden_source_modules"] = [
        source_module
        for source_module in manifest["forbidden_source_modules"]
        if source_module != "composer"
    ]

    with pytest.raises(MVP1AcceptanceError, match="forbidden_source_modules"):
        run_mvp1_acceptance_manifest(
            manifest,
            fixture_dir=MVP1_REPLAY_FIXTURE_DIR,
        )


def test_mvp1_acceptance_rejects_mvp2_only_behavior() -> None:
    fixture = load_json_fixture(MVP1_REPLAY_FIXTURE_DIR / "004-spawn-planning-completed.fixture.json")
    events = deepcopy(fixture["events"])
    events[-1]["event_name"] = "SPOKEN_PLAN_EMITTED"

    with pytest.raises(MVP1AcceptanceError, match="forbidden MVP-2"):
        assert_fixture_has_no_forbidden_mvp1_scope(events)


@pytest.mark.parametrize("event_name", ["TOOL_CALL_STARTED", "TOOL_RESULT_RECEIVED"])
def test_mvp1_acceptance_allows_mock_emitter_owned_synthetic_tool_markers(event_name: str) -> None:
    fixture = load_json_fixture(MVP1_REPLAY_FIXTURE_DIR / "008-stale-result-no-adoption.fixture.json")
    events = deepcopy(fixture["events"])
    tool_event = next(event for event in events if event["event_name"] == event_name)
    tool_event["source_module"] = "mock_tool_event_emitter"

    assert_fixture_has_no_forbidden_mvp1_scope(events)


@pytest.mark.parametrize("event_name", ["TOOL_CALL_STARTED", "TOOL_RESULT_RECEIVED"])
def test_mvp1_acceptance_rejects_tool_executor_owned_tool_markers(event_name: str) -> None:
    fixture = load_json_fixture(MVP1_REPLAY_FIXTURE_DIR / "008-stale-result-no-adoption.fixture.json")
    events = deepcopy(fixture["events"])
    tool_event = next(event for event in events if event["event_name"] == event_name)
    tool_event["source_module"] = "tool_executor"

    with pytest.raises(MVP1AcceptanceError, match="forbidden MVP-2 source_module"):
        assert_fixture_has_no_forbidden_mvp1_scope(events)


@pytest.mark.parametrize("event_name", ["TOOL_CALL_STARTED", "TOOL_RESULT_RECEIVED"])
def test_mvp1_acceptance_rejects_slowtask_owned_tool_markers(event_name: str) -> None:
    fixture = load_json_fixture(MVP1_REPLAY_FIXTURE_DIR / "008-stale-result-no-adoption.fixture.json")
    events = deepcopy(fixture["events"])
    tool_event = next(event for event in events if event["event_name"] == event_name)
    tool_event["source_module"] = "slowtask_runtime"

    with pytest.raises(MVP1AcceptanceError, match="Tool Executor"):
        assert_fixture_has_no_forbidden_mvp1_scope(events)


def test_mvp1_acceptance_rejects_tool_executor_owned_baseline_event() -> None:
    fixture = load_json_fixture(MVP1_REPLAY_FIXTURE_DIR / "004-spawn-planning-completed.fixture.json")
    events = deepcopy(fixture["events"])
    events[0]["source_module"] = "tool_executor"

    with pytest.raises(MVP1AcceptanceError, match="forbidden MVP-2 source_module"):
        assert_fixture_has_no_forbidden_mvp1_scope(events)


def test_mvp1_acceptance_rejects_real_adapter_capability_modes(tmp_path: Path) -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)
    _copy_mvp1_fixtures(tmp_path)
    fixture_path = tmp_path / "002-task-focus-router.fixture.json"
    fixture = load_json_fixture(fixture_path)
    capability = next(
        event
        for event in fixture["events"]
        if event["event_name"] == "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED"
    )
    capability["deployment_modes"] = ["real", "real"]
    capability["output_modes"] = ["real", "real"]
    fixture_path.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(MVP1AcceptanceError, match="real"):
        run_mvp1_acceptance_manifest(
            manifest,
            fixture_dir=tmp_path,
        )


def test_mvp1_acceptance_rejects_non_material_patch_plan_advance(tmp_path: Path) -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)
    _copy_mvp1_fixtures(tmp_path)
    fixture_path = tmp_path / "006-plan-advance-replanning.fixture.json"
    fixture = load_json_fixture(fixture_path)
    interpreted = _event_by_id(fixture["events"], "evt_mvp1_slice6_user_patch_interpreted")
    advance = _event_by_id(fixture["events"], "evt_mvp1_slice6_plan_version_advanced")
    interpreted["materially_changes_task"] = False
    interpreted["interpretation_reason"] = "mock_non_material_note"
    advance["planning_reason"] = "mock_periodic_replan"
    advance.pop("caused_by_user_patch_event_id", None)
    fixture_path.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(MVP1AcceptanceError, match="material"):
        run_mvp1_acceptance_manifest(
            manifest,
            fixture_dir=tmp_path,
        )


def test_mvp1_acceptance_rejects_stale_adoption_after_commitment(tmp_path: Path) -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)
    _copy_mvp1_fixtures(tmp_path)
    fixture_path = tmp_path / "008-stale-result-adopted.fixture.json"
    fixture = load_json_fixture(fixture_path)
    events = fixture["events"]
    adoption = _event_by_id(events, "evt_mvp1_slice8_adopted_stale_evidence_adopted")
    reviewed = _event_by_id(events, "evt_mvp1_slice8_adopted_evidence_reviewed")
    finalizing = _event_by_id(events, "evt_mvp1_slice8_adopted_finalizing")
    commitment = _event_by_id(events, "evt_mvp1_slice8_adopted_semantic_commitment")
    completed = _event_by_id(events, "evt_mvp1_slice8_adopted_state_completed")
    reviewed["caused_by_event_id"] = "evt_mvp1_slice8_adopted_task_replanned"
    reviewed["evidence_refs"] = ["evidence://synthetic/mvp1/slice8/adopted/current-plan-review"]
    finalizing["source_events"] = ["evt_mvp1_slice8_adopted_argument_provenance"]
    commitment["source_events"] = [
        "evt_mvp1_slice8_adopted_stale_evidence_adopted",
        "evt_mvp1_slice8_adopted_finalizing",
    ]
    adoption["event_seq"] = 22
    adoption["task_event_seq"] = 20
    adoption["created_monotonic_ms"] = 76
    adoption["created_wall_clock_ms"] = 1700000008276
    completed["event_seq"] = 23
    completed["task_event_seq"] = 21
    completed["created_monotonic_ms"] = 77
    completed["created_wall_clock_ms"] = 1700000008277
    fixture_path.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(MVP1AcceptanceError, match="STALE_EVIDENCE_ADOPTED"):
        run_mvp1_acceptance_manifest(
            manifest,
            fixture_dir=tmp_path,
        )


def test_mvp1_acceptance_rejects_cancel_requested_before_confirmation_acceptance(tmp_path: Path) -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)
    _copy_mvp1_fixtures(tmp_path)
    fixture_path = tmp_path / "009-cancel-confirmation.fixture.json"
    fixture = load_json_fixture(fixture_path)
    events = fixture["events"]
    accepted = _event_by_id(events, "evt_mvp1_slice9_cancel_confirmation_accepted")
    cancel_requested = _event_by_id(events, "evt_mvp1_slice9_cancel_requested")
    cancel_requested["event_seq"] = 23
    cancel_requested["task_event_seq"] = 12
    cancel_requested["created_monotonic_ms"] = 58
    cancel_requested["created_wall_clock_ms"] = 1700000009058
    cancel_requested["caused_by_event_id"] = "evt_mvp1_slice9_cancel_user_confirmation_received"
    accepted["event_seq"] = 24
    accepted["task_event_seq"] = 13
    accepted["created_monotonic_ms"] = 59
    accepted["created_wall_clock_ms"] = 1700000009059
    fixture_path.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(MVP1AcceptanceError, match="confirmation"):
        run_mvp1_acceptance_manifest(
            manifest,
            fixture_dir=tmp_path,
        )


def test_mvp1_acceptance_rejects_router_owned_slowtask_confirmation(tmp_path: Path) -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)
    _copy_mvp1_fixtures(tmp_path)
    fixture_path = tmp_path / "009-cancel-confirmation.fixture.json"
    fixture = load_json_fixture(fixture_path)
    confirmation = _event_by_id(fixture["events"], "evt_mvp1_slice9_cancel_confirmation_required")
    confirmation["source_module"] = "router"
    fixture_path.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(MVP1AcceptanceError, match="source_module"):
        run_mvp1_acceptance_manifest(
            manifest,
            fixture_dir=tmp_path,
        )


def test_mvp1_acceptance_rejects_foreground_chat_slowtask_mutation(tmp_path: Path) -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)
    _copy_mvp1_fixtures(tmp_path)
    fixture_path = tmp_path / "002-task-focus-router.fixture.json"
    fixture = load_json_fixture(fixture_path)
    _insert_event_and_shift_following(
        fixture["events"],
        after_event_id="evt_mvp1_slice2_turn_chat_committed",
        new_event={
            "event_name": "SLOWTASK_STATE_CHANGED",
            "event_id": "evt_mvp1_slice2_invalid_foreground_state_change",
            "event_schema_version": "1.0",
            "session_id": "sess_mvp1_slice2_task_focus",
            "conversation_id": "conv_mvp1_slice2_task_focus",
            "source_module": "slowtask_runtime",
            "created_monotonic_ms": 166,
            "created_wall_clock_ms": 1700000000166,
            "caused_by_event_id": "evt_mvp1_slice2_turn_chat_committed",
            "trace_redaction_level": "metadata_only",
            "task_id": "task_mvp1_slice2_focus_001",
            "plan_version": 1,
            "task_event_seq": 5,
            "from_state": "PLANNING",
            "to_state": "PLANNING",
            "reason": "invalid_foreground_mutation",
        },
    )
    fixture_path.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(MVP1AcceptanceError, match="foreground chat"):
        run_mvp1_acceptance_manifest(
            manifest,
            fixture_dir=tmp_path,
        )


def test_mvp1_acceptance_rejects_foreground_chat_slowtask_reasoning(tmp_path: Path) -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)
    _copy_mvp1_fixtures(tmp_path)
    fixture_path = tmp_path / "002-task-focus-router.fixture.json"
    fixture = load_json_fixture(fixture_path)
    _insert_event_and_shift_following(
        fixture["events"],
        after_event_id="evt_mvp1_slice2_focus_chat",
        new_event={
            "event_name": "EVIDENCE_REVIEWED",
            "event_id": "evt_mvp1_slice2_invalid_foreground_evidence_reviewed",
            "event_schema_version": "1.0",
            "session_id": "sess_mvp1_slice2_task_focus",
            "conversation_id": "conv_mvp1_slice2_task_focus",
            "source_module": "slowtask_runtime",
            "created_monotonic_ms": 166,
            "created_wall_clock_ms": 1700000000166,
            "caused_by_event_id": "evt_mvp1_slice2_focus_chat",
            "trace_redaction_level": "metadata_only",
            "task_id": "task_mvp1_slice2_focus_001",
            "plan_version": 1,
            "task_event_seq": 5,
            "evidence_refs": ["evidence://synthetic/mvp1/slice2/invalid-foreground-review"],
            "review_result": "invalid_foreground_reasoning",
        },
    )
    fixture_path.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(MVP1AcceptanceError, match="foreground chat"):
        run_mvp1_acceptance_manifest(
            manifest,
            fixture_dir=tmp_path,
        )


def test_mvp1_acceptance_rejects_ambiguous_input_slowtask_mutation(tmp_path: Path) -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)
    _copy_mvp1_fixtures(tmp_path)
    fixture_path = tmp_path / "002-task-focus-router.fixture.json"
    fixture = load_json_fixture(fixture_path)
    max_event_seq = max(int(event["event_seq"]) for event in fixture["events"])
    fixture["events"].append(
        {
            "event_name": "SLOWTASK_STATE_CHANGED",
            "event_id": "evt_mvp1_slice2_invalid_ambiguous_state_change",
            "event_seq": max_event_seq + 1,
            "event_schema_version": "1.0",
            "session_id": "sess_mvp1_slice2_task_focus",
            "conversation_id": "conv_mvp1_slice2_task_focus",
            "source_module": "slowtask_runtime",
            "created_monotonic_ms": 246,
            "created_wall_clock_ms": 1700000000246,
            "caused_by_event_id": "evt_mvp1_slice2_focus_ambiguous",
            "trace_redaction_level": "metadata_only",
            "task_id": "task_mvp1_slice2_focus_001",
            "plan_version": 1,
            "task_event_seq": 5,
            "from_state": "PLANNING",
            "to_state": "PLANNING",
            "reason": "invalid_ambiguous_mutation",
        }
    )
    fixture_path.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(MVP1AcceptanceError, match="ambiguous input"):
        run_mvp1_acceptance_manifest(
            manifest,
            fixture_dir=tmp_path,
        )


def test_mvp1_acceptance_rejects_repo_unsafe_fixture_content() -> None:
    fixture = load_json_fixture(MVP1_REPLAY_FIXTURE_DIR / "005-active-patch-evidence.fixture.json")
    fixture["events"][-1]["payload"] = {"raw_audio_ref": "audio/raw/session.wav"}

    with pytest.raises(MVP1AcceptanceError, match="repo-unsafe"):
        assert_mvp1_fixture_is_repo_safe(fixture)


def _synthetic_slack_token_like_value() -> str:
    return "xo" + "xb-" + "1234567890-SlackTokenLikeValue"


def _synthetic_aws_key_like_value() -> str:
    return "AKIA" + "1234567890ABCDEF"


@pytest.mark.parametrize(
    "secret_value",
    [
        "copied sk-test-secret into a harmless note",
        f"captured {_synthetic_slack_token_like_value()}",
        f"copied {_synthetic_aws_key_like_value()} from a shell",
    ],
)
def test_mvp1_acceptance_rejects_embedded_secret_like_values(secret_value: str) -> None:
    fixture = load_json_fixture(MVP1_REPLAY_FIXTURE_DIR / "005-active-patch-evidence.fixture.json")
    fixture["events"][-1]["note"] = secret_value

    with pytest.raises(MVP1AcceptanceError, match="repo-unsafe"):
        assert_mvp1_fixture_is_repo_safe(fixture)


@pytest.mark.parametrize(
    "secret_kind",
    [
        f"blocked {_synthetic_slack_token_like_value()}",
        f"blocked {_synthetic_aws_key_like_value()}",
    ],
)
def test_mvp1_acceptance_rejects_secret_like_secret_kind_metadata(secret_kind: str) -> None:
    fixture = load_json_fixture(MVP1_REPLAY_FIXTURE_DIR / "005-active-patch-evidence.fixture.json")
    fixture["events"][-1]["secret_kind"] = secret_kind

    with pytest.raises(MVP1AcceptanceError, match="repo-unsafe"):
        assert_mvp1_fixture_is_repo_safe(fixture)


def test_mvp1_acceptance_rejects_switch_task_without_accepted_confirmation(tmp_path: Path) -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)
    _copy_mvp1_fixtures(tmp_path)
    accepted_fixture_path = tmp_path / "009-switch-task-confirmation-accepted.fixture.json"
    fixture = load_json_fixture(accepted_fixture_path)
    fixture["events"] = _remove_switch_task_confirmation_gate(fixture["events"])
    accepted_fixture_path.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(
        (MVP1AcceptanceError, ReplayValidationError),
        match="SWITCH_TASK confirmation|ROUTER_DECISION_EMITTED",
    ):
        run_mvp1_acceptance_manifest(
            manifest,
            fixture_dir=tmp_path,
        )


def test_mvp1_acceptance_rejects_switch_task_rejection_that_clears_focus(tmp_path: Path) -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)
    _copy_mvp1_fixtures(tmp_path)
    rejected_fixture_path = tmp_path / "009-switch-task-confirmation-rejected.fixture.json"
    fixture = load_json_fixture(rejected_fixture_path)
    focus = next(
        event
        for event in fixture["events"]
        if event["event_id"] == "evt_mvp1_slice9_switch_rejected_confirm_focus"
    )
    focus["active_task_id"] = None
    focus["foreground_mode"] = "IDLE"
    focus["default_patch_policy"] = "NO_ACTIVE_TASK"
    rejected_fixture_path.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(MVP1AcceptanceError, match="active focus"):
        run_mvp1_acceptance_manifest(
            manifest,
            fixture_dir=tmp_path,
        )


def test_mvp1_acceptance_rejects_switch_task_respawn_without_focus_cleanup(tmp_path: Path) -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)
    _copy_mvp1_fixtures(tmp_path)
    accepted_fixture_path = tmp_path / "009-switch-task-confirmation-accepted.fixture.json"
    fixture = load_json_fixture(accepted_fixture_path)
    fixture["events"] = [
        event
        for event in fixture["events"]
        if event["event_id"] != "evt_mvp1_slice9_switch_focus_cleared"
    ]
    spawn_router = _event_by_id(fixture["events"], "evt_mvp1_slice9_switch_spawn_router")
    spawn_router["caused_by_event_id"] = "evt_mvp1_slice9_switch_accept_state_cancelled"
    accepted_fixture_path.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(
        (MVP1AcceptanceError, ReplayValidationError),
        match="focus|ROUTER_DECISION_EMITTED",
    ):
        run_mvp1_acceptance_manifest(
            manifest,
            fixture_dir=tmp_path,
        )


def test_mvp1_acceptance_rejects_rejected_switch_task_argument_mutation(tmp_path: Path) -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)
    _copy_mvp1_fixtures(tmp_path)
    rejected_fixture_path = tmp_path / "009-switch-task-confirmation-rejected.fixture.json"
    fixture = load_json_fixture(rejected_fixture_path)
    max_event_seq = max(int(event["event_seq"]) for event in fixture["events"])
    fixture["events"].append(
        {
            "event_name": "ARGUMENTS_RESOLVED",
            "event_id": "evt_mvp1_slice9_switch_rejected_invalid_arguments",
            "event_seq": max_event_seq + 1,
            "event_schema_version": "1.0",
            "session_id": "sess_mvp1_slice9_switch_rejected",
            "conversation_id": "conv_mvp1_slice9_switch_rejected",
            "source_module": "slowtask_runtime",
            "created_monotonic_ms": 66,
            "created_wall_clock_ms": 1700000009266,
            "caused_by_event_id": "evt_mvp1_slice9_switch_rejected_state_planning",
            "trace_redaction_level": "metadata_only",
            "task_id": "task_mvp1_slice9_switch_rejected",
            "plan_version": 1,
            "task_event_seq": 15,
            "resolved_arguments_ref": "args://synthetic/mvp1/slice9/switch-rejected-invalid",
            "provenance_ref": "provenance://synthetic/mvp1/slice9/switch-rejected-invalid",
        }
    )
    rejected_fixture_path.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(MVP1AcceptanceError, match="rejected switch"):
        run_mvp1_acceptance_manifest(
            manifest,
            fixture_dir=tmp_path,
        )


def _copy_mvp1_fixtures(target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    for fixture_path in MVP1_REPLAY_FIXTURE_DIR.glob("*.fixture.json"):
        fixture = load_json_fixture(fixture_path)
        (target_dir / fixture_path.name).write_text(
            json.dumps(fixture, indent=2) + "\n",
            encoding="utf-8",
        )


def _event_by_id(events: list[dict[str, object]], event_id: str) -> dict[str, object]:
    return next(event for event in events if event["event_id"] == event_id)


def _insert_event_and_shift_following(
    events: list[dict[str, object]],
    *,
    after_event_id: str,
    new_event: dict[str, object],
) -> None:
    insert_index = next(index + 1 for index, event in enumerate(events) if event["event_id"] == after_event_id)
    inserted_event_seq = int(events[insert_index - 1]["event_seq"]) + 1
    for event in events[insert_index:]:
        event["event_seq"] = int(event["event_seq"]) + 1
    new_event["event_seq"] = inserted_event_seq
    events.insert(insert_index, new_event)


def _remove_switch_task_confirmation_gate(events: list[dict[str, object]]) -> list[dict[str, object]]:
    removed_event_names = {
        "CONFIRMATION_REQUIRED",
        "WAITING_FOR_USER_CONFIRMATION",
        "USER_CONFIRMATION_RECEIVED",
        "CONFIRMATION_ACCEPTED",
    }
    removed_event_ids = {
        "evt_mvp1_slice9_switch_confirmation_required",
        "evt_mvp1_slice9_switch_waiting",
        "evt_mvp1_slice9_switch_state_waiting",
        "evt_mvp1_slice9_switch_confirm_turn_committed",
        "evt_mvp1_slice9_switch_confirm_asr",
        "evt_mvp1_slice9_switch_confirm_thinker",
        "evt_mvp1_slice9_switch_confirm_router",
        "evt_mvp1_slice9_switch_confirm_focus",
        "evt_mvp1_slice9_switch_confirm_patch_received",
        "evt_mvp1_slice9_switch_confirm_interpreted",
        "evt_mvp1_slice9_switch_user_confirmation_received",
        "evt_mvp1_slice9_switch_confirmation_accepted",
    }
    mutated_events: list[dict[str, object]] = []
    for event in events:
        if event["event_id"] in removed_event_ids or event["event_name"] in removed_event_names:
            continue
        event = dict(event)
        if event["event_id"] == "evt_mvp1_slice9_switch_cancel_requested":
            event["caused_by_event_id"] = "evt_mvp1_slice9_switch_interpreted"
            event["source_user_patch_event_id"] = "evt_mvp1_slice9_switch_patch_received"
        elif event["event_id"] == "evt_mvp1_slice9_switch_accept_state_cancelled":
            event["from_state"] = "PLANNING"
        elif event["event_id"] == "evt_mvp1_slice9_switch_focus_cleared":
            event["caused_by_event_id"] = "evt_mvp1_slice9_switch_router"
            event["router_decision_event_id"] = "evt_mvp1_slice9_switch_router"
            event["last_focus_event_id"] = "evt_mvp1_slice9_switch_router"
        mutated_events.append(event)
    return mutated_events
