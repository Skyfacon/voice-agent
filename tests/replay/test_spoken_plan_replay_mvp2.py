from __future__ import annotations

from copy import deepcopy

import pytest

from conftest import MVP2_REPLAY_FIXTURE_DIR, load_json_fixture
from voice_agent.replay.runner import ReplayValidationError, run_replay_fixture


SPOKEN_PLAN_FIXTURE = MVP2_REPLAY_FIXTURE_DIR / "006-thinker-as-composer.fixture.json"


def test_replay_accepts_valid_commitment_derived_spoken_plan() -> None:
    result = run_replay_fixture(load_json_fixture(SPOKEN_PLAN_FIXTURE))

    commitment_spoken = result.spoken_plan_state.spoken_plans["spoken_mvp2_slice6_commitment"]
    assert commitment_spoken.source == "semantic_commitment"
    assert commitment_spoken.output_mode == "mock"
    assert commitment_spoken.task_id == "task_mvp2_slice6"
    assert commitment_spoken.plan_version == 1
    assert commitment_spoken.source_commitment_id == "commitment_mvp2_slice6"
    assert commitment_spoken.source_events == ("evt_mvp2_slice6_semantic_commitment",)
    assert commitment_spoken.coverage_check_required is True
    assert commitment_spoken.truthfulness_check_required is False
    assert commitment_spoken.immutable_fields == ("final_result.status",)
    assert commitment_spoken.must_say_fields == ("final_result.summary",)
    assert commitment_spoken.forbidden_rewrite_fields == ("resolved_arguments",)


def test_replay_accepts_valid_progress_derived_spoken_plan() -> None:
    result = run_replay_fixture(load_json_fixture(SPOKEN_PLAN_FIXTURE))

    progress_spoken = result.spoken_plan_state.spoken_plans["spoken_mvp2_slice6_progress"]
    assert progress_spoken.source == "grounded_progress"
    assert progress_spoken.output_mode == "mock"
    assert progress_spoken.source_progress_event_ids == ("evt_mvp2_slice6_planning_started",)
    assert progress_spoken.coverage_check_required is False
    assert progress_spoken.truthfulness_check_required is True
    assert progress_spoken.truthfulness_level == "STATE_GROUNDED"
    assert result.diagnostics["ignored_events"] == []
    assert result.state_digest["spoken_plan_state_hash"]


def test_replay_rejects_spoken_plan_with_missing_source_commitment_id() -> None:
    fixture = load_json_fixture(SPOKEN_PLAN_FIXTURE)
    spoken = _event_by_id(fixture["events"], "evt_mvp2_slice6_commitment_spoken")
    spoken.pop("source_commitment_id")

    with pytest.raises(ReplayValidationError, match="source_commitment_id"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_spoken_plan_with_wrong_source_commitment_id() -> None:
    fixture = load_json_fixture(SPOKEN_PLAN_FIXTURE)
    spoken = _event_by_id(fixture["events"], "evt_mvp2_slice6_commitment_spoken")
    spoken["source_commitment_id"] = "commitment_wrong"

    with pytest.raises(ReplayValidationError, match="source_commitment_id"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_commitment_spoken_plan_that_drops_symbolic_metadata() -> None:
    fixture = load_json_fixture(SPOKEN_PLAN_FIXTURE)
    spoken = _event_by_id(fixture["events"], "evt_mvp2_slice6_commitment_spoken")
    spoken.pop("must_say_fields")

    with pytest.raises(ReplayValidationError, match="must_say_fields"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_commitment_spoken_plan_that_rewrites_symbolic_metadata() -> None:
    fixture = load_json_fixture(SPOKEN_PLAN_FIXTURE)
    spoken = _event_by_id(fixture["events"], "evt_mvp2_slice6_commitment_spoken")
    spoken["forbidden_rewrite_fields"] = ["resolved_arguments", "risk_warnings"]

    with pytest.raises(ReplayValidationError, match="forbidden_rewrite_fields"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_commitment_spoken_plan_that_adds_symbolic_metadata() -> None:
    fixture = load_json_fixture(SPOKEN_PLAN_FIXTURE)
    commitment = _event_by_id(fixture["events"], "evt_mvp2_slice6_semantic_commitment")
    spoken = _event_by_id(fixture["events"], "evt_mvp2_slice6_commitment_spoken")
    commitment.pop("immutable_fields")
    spoken["immutable_fields"] = ["final_result.status"]

    with pytest.raises(ReplayValidationError, match="immutable_fields"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_spoken_plan_with_wrong_plan_source() -> None:
    fixture = load_json_fixture(SPOKEN_PLAN_FIXTURE)
    spoken = _event_by_id(fixture["events"], "evt_mvp2_slice6_commitment_spoken")
    spoken["plan_version"] = 2

    with pytest.raises(ReplayValidationError, match="plan_version"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_spoken_plan_with_missing_source_event() -> None:
    fixture = load_json_fixture(SPOKEN_PLAN_FIXTURE)
    spoken = _event_by_id(fixture["events"], "evt_mvp2_slice6_progress_spoken")
    spoken["source_events"] = ["evt_mvp2_slice6_missing_progress"]
    spoken["source_progress_event_ids"] = ["evt_mvp2_slice6_missing_progress"]

    with pytest.raises(ReplayValidationError, match="source event"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_progress_spoken_plan_from_unsupported_source_event() -> None:
    fixture = load_json_fixture(SPOKEN_PLAN_FIXTURE)
    spoken = _event_by_id(fixture["events"], "evt_mvp2_slice6_progress_spoken")
    spoken["caused_by_event_id"] = "evt_mvp2_slice6_slowtask_created"
    spoken["source_events"] = ["evt_mvp2_slice6_slowtask_created"]
    spoken["source_progress_event_ids"] = ["evt_mvp2_slice6_slowtask_created"]

    with pytest.raises(ReplayValidationError, match="unsupported progress source"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_progress_spoken_plan_with_unsupported_truthfulness_level() -> None:
    fixture = load_json_fixture(SPOKEN_PLAN_FIXTURE)
    spoken = _event_by_id(fixture["events"], "evt_mvp2_slice6_progress_spoken")
    spoken["truthfulness_level"] = "ESTIMATE_WITH_BASIS"

    with pytest.raises(ReplayValidationError, match="truthfulness_level"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_spoken_plan_without_output_mode() -> None:
    fixture = load_json_fixture(SPOKEN_PLAN_FIXTURE)
    spoken = _event_by_id(fixture["events"], "evt_mvp2_slice6_commitment_spoken")
    spoken.pop("output_mode", None)

    with pytest.raises(ReplayValidationError, match="output_mode"):
        run_replay_fixture(deepcopy(fixture))


def test_replay_rejects_spoken_plan_with_unsupported_output_mode() -> None:
    fixture = load_json_fixture(SPOKEN_PLAN_FIXTURE)
    spoken = _event_by_id(fixture["events"], "evt_mvp2_slice6_progress_spoken")
    spoken["output_mode"] = "unlabeled"

    with pytest.raises(ReplayValidationError, match="output_mode"):
        run_replay_fixture(deepcopy(fixture))


def test_spoken_plan_fixture_does_not_emit_checks_or_playback() -> None:
    fixture = load_json_fixture(SPOKEN_PLAN_FIXTURE)
    emitted = {event["event_name"] for event in fixture["events"]}

    assert "SPOKEN_PLAN_EMITTED" in emitted
    assert "COMMITMENT_COVERAGE_CHECK_PASSED" not in emitted
    assert "COMMITMENT_COVERAGE_CHECK_FAILED" not in emitted
    assert "PROGRESS_TRUTHFULNESS_CHECK_PASSED" not in emitted
    assert "PROGRESS_TRUTHFULNESS_CHECK_FAILED" not in emitted
    assert not any(event_name.startswith("PLAYBACK_") for event_name in emitted)


def test_spoken_plan_fixture_refs_do_not_embed_raw_user_args_pii_or_secret_like_values() -> None:
    fixture = load_json_fixture(SPOKEN_PLAN_FIXTURE)

    for event in fixture["events"]:
        for key, value in event.items():
            if key.endswith("_ref") or key in {"text_ref", "spoken_plan_id"}:
                text = str(value).lower()
                assert "testville" not in text
                assert "real_user" not in text
                assert "secret" not in text
                assert "token" not in text
                assert "password" not in text


def _event_by_id(events: list[dict[str, object]], event_id: str) -> dict[str, object]:
    return next(event for event in events if event["event_id"] == event_id)
