from __future__ import annotations

from copy import deepcopy

import pytest

from conftest import MVP2_REPLAY_FIXTURE_DIR, load_json_fixture
from voice_agent.replay.runner import ReplayValidationError, run_replay_fixture


COMPOSER_CHECK_FIXTURE = MVP2_REPLAY_FIXTURE_DIR / "007-composer-checks.fixture.json"


def test_replay_accepts_playback_after_valid_coverage_pass() -> None:
    result = run_replay_fixture(load_json_fixture(COMPOSER_CHECK_FIXTURE))

    coverage = result.spoken_plan_check_state.passed_checks["evt_mvp2_slice7_coverage_passed"]
    assert coverage.event_name == "COMMITMENT_COVERAGE_CHECK_PASSED"
    assert coverage.spoken_plan_id == "spoken_mvp2_slice7_commitment"
    assert coverage.source_commitment_id == "commitment_mvp2_slice7"
    assert coverage.output_mode == "mock"
    assert result.playback_state.current_playback_span_id == "playback_mvp2_slice7_commitment"
    assert result.playback_state.spoken_plan_id == "spoken_mvp2_slice7_commitment"
    assert result.playback_state.approved_check_event_id == "evt_mvp2_slice7_coverage_passed"


def test_replay_accepts_playback_after_valid_truthfulness_pass() -> None:
    result = run_replay_fixture(load_json_fixture(COMPOSER_CHECK_FIXTURE))

    truthfulness = result.spoken_plan_check_state.passed_checks["evt_mvp2_slice7_truthfulness_passed"]
    progress_playback = _event_by_id(result.ordered_events, "evt_mvp2_slice7_progress_playback_started")
    assert truthfulness.event_name == "PROGRESS_TRUTHFULNESS_CHECK_PASSED"
    assert truthfulness.spoken_plan_id == "spoken_mvp2_slice7_progress"
    assert truthfulness.source_progress_event_ids == ("evt_mvp2_slice7_planning_started",)
    assert truthfulness.truthfulness_level == "STATE_GROUNDED"
    assert truthfulness.output_mode == "mock"
    assert progress_playback["approved_check_event_id"] == "evt_mvp2_slice7_truthfulness_passed"


def test_replay_rejects_playback_without_approved_check_event_id() -> None:
    fixture = load_json_fixture(COMPOSER_CHECK_FIXTURE)
    playback = _event_by_id(fixture["events"], "evt_mvp2_slice7_progress_playback_started")
    playback.pop("approved_check_event_id")

    with pytest.raises(ReplayValidationError, match="approved_check_event_id"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_playback_referencing_failed_check() -> None:
    fixture = load_json_fixture(COMPOSER_CHECK_FIXTURE)
    truthfulness = _event_by_id(fixture["events"], "evt_mvp2_slice7_truthfulness_passed")
    truthfulness["event_name"] = "PROGRESS_TRUTHFULNESS_CHECK_FAILED"
    truthfulness["failure_reasons"] = ["unsupported_truthfulness_level"]

    with pytest.raises(ReplayValidationError, match="failed checker event cannot authorize playback"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_playback_caused_by_failed_check_when_spoken_plan_id_is_omitted() -> None:
    fixture = load_json_fixture(COMPOSER_CHECK_FIXTURE)
    truthfulness = _event_by_id(fixture["events"], "evt_mvp2_slice7_truthfulness_passed")
    truthfulness["event_name"] = "PROGRESS_TRUTHFULNESS_CHECK_FAILED"
    truthfulness["failure_reasons"] = ["synthetic_blocked_progress"]
    playback = _event_by_id(fixture["events"], "evt_mvp2_slice7_progress_playback_started")
    playback.pop("spoken_plan_id")
    playback.pop("approved_check_event_id")

    with pytest.raises(ReplayValidationError, match="SpokenPlan playback"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_playback_caused_directly_by_spoken_plan_when_ids_are_omitted() -> None:
    fixture = load_json_fixture(COMPOSER_CHECK_FIXTURE)
    playback = _event_by_id(fixture["events"], "evt_mvp2_slice7_progress_playback_started")
    playback["caused_by_event_id"] = "evt_mvp2_slice7_progress_spoken"
    playback.pop("spoken_plan_id")
    playback.pop("approved_check_event_id")

    with pytest.raises(ReplayValidationError, match="SpokenPlan playback"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_playback_referencing_wrong_spoken_plan_id() -> None:
    fixture = load_json_fixture(COMPOSER_CHECK_FIXTURE)
    playback = _event_by_id(fixture["events"], "evt_mvp2_slice7_commitment_playback_started")
    playback["spoken_plan_id"] = "spoken_mvp2_slice7_progress"

    with pytest.raises(ReplayValidationError, match="spoken_plan_id must match"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_invalid_spoken_plan_with_both_failed_and_passed_checks() -> None:
    fixture = load_json_fixture(COMPOSER_CHECK_FIXTURE)
    spoken = _event_by_id(fixture["events"], "evt_mvp2_slice7_commitment_spoken")
    spoken["must_say_fields"] = []
    _insert_event_before(
        fixture["events"],
        before_event_id="evt_mvp2_slice7_coverage_passed",
        new_event={
            "event_name": "COMMITMENT_COVERAGE_CHECK_FAILED",
            "event_id": "evt_mvp2_slice7_coverage_failed_before_pass",
            "event_schema_version": "1.0",
            "session_id": "sess_mvp2_slice7",
            "conversation_id": "conv_mvp2_slice7",
            "source_module": "coverage_checker",
            "created_monotonic_ms": 105,
            "created_wall_clock_ms": 1700000070105,
            "caused_by_event_id": "evt_mvp2_slice7_commitment_spoken",
            "trace_redaction_level": "metadata_only",
            "task_id": "task_mvp2_slice7",
            "plan_version": 1,
            "task_event_seq": 8,
            "spoken_plan_id": "spoken_mvp2_slice7_commitment",
            "source_commitment_id": "commitment_mvp2_slice7",
            "failure_reasons": [
                "must_say_fields_mismatch"
            ],
            "check_result_ref": "check://synthetic/mvp2/slice7/coverage/fail-before-pass",
            "output_mode": "mock",
        },
    )
    coverage_pass = _event_by_id(fixture["events"], "evt_mvp2_slice7_coverage_passed")
    coverage_pass["task_event_seq"] = 9

    with pytest.raises(ReplayValidationError, match="must_say_fields"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_stale_spoken_plan_check_after_plan_advance() -> None:
    fixture = load_json_fixture(COMPOSER_CHECK_FIXTURE)
    _insert_event_before(
        fixture["events"],
        before_event_id="evt_mvp2_slice7_coverage_passed",
        new_event={
            "event_name": "PLAN_VERSION_ADVANCED",
            "event_id": "evt_mvp2_slice7_plan_advanced_before_coverage_check",
            "event_schema_version": "1.0",
            "session_id": "sess_mvp2_slice7",
            "conversation_id": "conv_mvp2_slice7",
            "source_module": "slowtask_runtime",
            "created_monotonic_ms": 105,
            "created_wall_clock_ms": 1700000070105,
            "caused_by_event_id": "evt_mvp2_slice7_commitment_spoken",
            "trace_redaction_level": "metadata_only",
            "task_id": "task_mvp2_slice7",
            "plan_version": 2,
            "task_event_seq": 8,
            "from_plan_version": 1,
            "to_plan_version": 2,
            "planning_reason": "synthetic_late_patch",
        },
    )
    coverage = _event_by_id(fixture["events"], "evt_mvp2_slice7_coverage_passed")
    coverage["task_event_seq"] = 9

    with pytest.raises(ReplayValidationError, match="stale SpokenPlan"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_accepts_coverage_failure_trace_for_invalid_commitment_spoken_plan() -> None:
    fixture = load_json_fixture(COMPOSER_CHECK_FIXTURE)
    spoken = _event_by_id(fixture["events"], "evt_mvp2_slice7_commitment_spoken")
    spoken["must_say_fields"] = []
    coverage = _event_by_id(fixture["events"], "evt_mvp2_slice7_coverage_passed")
    coverage["event_name"] = "COMMITMENT_COVERAGE_CHECK_FAILED"
    coverage["failure_reasons"] = ["must_say_fields_mismatch"]
    coverage.pop("checked_fields")
    _remove_events(
        fixture["events"],
        {
            "evt_mvp2_slice7_commitment_playback_started",
        },
    )

    result = run_replay_fixture(deepcopy(fixture))

    assert "evt_mvp2_slice7_coverage_passed" in result.spoken_plan_check_state.failed_checks
    assert "evt_mvp2_slice7_coverage_passed" not in result.spoken_plan_check_state.passed_checks


def test_replay_accepts_truthfulness_failure_trace_for_unsupported_progress_level() -> None:
    fixture = load_json_fixture(COMPOSER_CHECK_FIXTURE)
    spoken = _event_by_id(fixture["events"], "evt_mvp2_slice7_progress_spoken")
    spoken["truthfulness_level"] = "ESTIMATE_WITH_BASIS"
    truthfulness = _event_by_id(fixture["events"], "evt_mvp2_slice7_truthfulness_passed")
    truthfulness["event_name"] = "PROGRESS_TRUTHFULNESS_CHECK_FAILED"
    truthfulness["truthfulness_level"] = "ESTIMATE_WITH_BASIS"
    truthfulness["failure_reasons"] = ["unsupported_truthfulness_level"]
    _remove_events(
        fixture["events"],
        {
            "evt_mvp2_slice7_progress_playback_started",
            "evt_mvp2_slice7_progress_playback_finished",
        },
    )

    result = run_replay_fixture(deepcopy(fixture))

    failed = result.spoken_plan_check_state.failed_checks["evt_mvp2_slice7_truthfulness_passed"]
    assert failed.truthfulness_level == "ESTIMATE_WITH_BASIS"
    assert failed.failure_reasons == ("unsupported_truthfulness_level",)


def test_replay_rejects_coverage_check_for_progress_derived_speech() -> None:
    fixture = load_json_fixture(COMPOSER_CHECK_FIXTURE)
    truthfulness = _event_by_id(fixture["events"], "evt_mvp2_slice7_truthfulness_passed")
    truthfulness["event_name"] = "COMMITMENT_COVERAGE_CHECK_PASSED"
    truthfulness["source_module"] = "coverage_checker"
    truthfulness["source_commitment_id"] = "commitment_mvp2_slice7"
    truthfulness["checked_fields"] = ["source_commitment_id"]
    truthfulness.pop("source_progress_event_ids")
    truthfulness.pop("truthfulness_level")

    with pytest.raises(ReplayValidationError, match="coverage check requires semantic_commitment"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_truthfulness_check_for_commitment_derived_speech() -> None:
    fixture = load_json_fixture(COMPOSER_CHECK_FIXTURE)
    coverage = _event_by_id(fixture["events"], "evt_mvp2_slice7_coverage_passed")
    coverage["event_name"] = "PROGRESS_TRUTHFULNESS_CHECK_PASSED"
    coverage["source_module"] = "truthfulness_checker"
    coverage["source_progress_event_ids"] = ["evt_mvp2_slice7_planning_started"]
    coverage["truthfulness_level"] = "STATE_GROUNDED"
    coverage.pop("source_commitment_id")
    coverage.pop("checked_fields")

    with pytest.raises(ReplayValidationError, match="truthfulness check requires grounded_progress"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_check_for_missing_source_spoken_plan() -> None:
    fixture = load_json_fixture(COMPOSER_CHECK_FIXTURE)
    coverage = _event_by_id(fixture["events"], "evt_mvp2_slice7_coverage_passed")
    coverage["spoken_plan_id"] = "spoken_mvp2_slice7_missing"

    with pytest.raises(ReplayValidationError, match="source spoken plan"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_check_without_output_mode() -> None:
    fixture = load_json_fixture(COMPOSER_CHECK_FIXTURE)
    coverage = _event_by_id(fixture["events"], "evt_mvp2_slice7_coverage_passed")
    coverage.pop("output_mode")

    with pytest.raises(ReplayValidationError, match="output_mode"):
        run_replay_fixture(deepcopy(fixture))


def test_composer_check_fixture_refs_do_not_embed_raw_user_args_pii_or_secret_like_values() -> None:
    fixture = load_json_fixture(COMPOSER_CHECK_FIXTURE)

    for event in fixture["events"]:
        for key, value in event.items():
            if key.endswith("_ref") or key in {"text_ref", "spoken_plan_id", "check_result_ref"}:
                text = str(value).lower()
                assert "testville" not in text
                assert "real_user" not in text
                assert "secret" not in text
                assert "token" not in text
                assert "password" not in text


def _event_by_id(events, event_id: str):
    return next(event for event in events if event["event_id"] == event_id)


def _insert_event_before(events, *, before_event_id: str, new_event: dict[str, object]) -> None:
    index = next(index for index, event in enumerate(events) if event["event_id"] == before_event_id)
    inserted_event_seq = int(events[index]["event_seq"])
    for event in events[index:]:
        event["event_seq"] = int(event["event_seq"]) + 1
    new_event["event_seq"] = inserted_event_seq
    events.insert(index, new_event)


def _remove_events(events, event_ids: set[str]) -> None:
    events[:] = [event for event in events if event["event_id"] not in event_ids]
