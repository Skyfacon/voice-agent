from __future__ import annotations

import random
import socket
import time

import pytest

from conftest import MVP1_REPLAY_FIXTURE_DIR, load_json_fixture
from voice_agent.replay.runner import ReplayValidationError, run_replay_fixture


SKELETON_FIXTURE = MVP1_REPLAY_FIXTURE_DIR / "003-slowtask-reducer-skeleton.fixture.json"
FAILED_STICKY_FIXTURE = MVP1_REPLAY_FIXTURE_DIR / "003-slowtask-failed-sticky.fixture.json"


def test_mvp1_slowtask_slice3_fixture_replays_completed_and_cancelled_tasks() -> None:
    result = run_replay_fixture(load_json_fixture(SKELETON_FIXTURE))

    completed = result.slowtask_state.tasks["task_mvp1_slice3_completed"]
    assert completed.lifecycle_state == "COMPLETED"
    assert completed.current_plan_version == 2
    assert completed.terminal_outcome == "COMPLETED"
    assert [patch.patch_id for patch in completed.user_patch_evidence] == [
        "patch_mvp1_slice3_material"
    ]
    assert completed.resolved_arguments_refs == ("args://synthetic/mvp1/slice3/resolved",)
    assert [commitment.commitment_id for commitment in completed.semantic_commitments] == [
        "commitment_mvp1_slice3_completed"
    ]

    cancelled = result.slowtask_state.tasks["task_mvp1_slice3_cancelled"]
    assert cancelled.lifecycle_state == "CANCELLED"
    assert cancelled.current_plan_version == 1
    assert cancelled.terminal_outcome == "CANCELLED"
    assert cancelled.cancel_reason == "synthetic_user_cancel"

    assert result.state_digest["slowtask_state_hash"]
    assert result.result_status == "passed"


def test_mvp1_failed_sticky_fixture_keeps_late_events_from_advancing_state() -> None:
    result = run_replay_fixture(load_json_fixture(FAILED_STICKY_FIXTURE))

    task = result.slowtask_state.tasks["task_mvp1_slice3_failed"]
    assert task.lifecycle_state == "FAILED"
    assert task.terminal_outcome == "FAILED"
    assert task.failure_reason == "synthetic_unrecoverable_failure"
    assert task.current_plan_version == 1
    assert task.user_patch_evidence == ()
    assert task.tool_results == ()
    assert task.confirmation_state.pending_confirmation_id is None
    assert [event.event_name for event in task.late_events] == [
        "USER_PATCH_RECEIVED",
        "TOOL_RESULT_RECEIVED",
        "CONFIRMATION_ACCEPTED",
    ]


def test_slowtask_replay_digest_is_stable_and_excludes_raw_or_secret_payloads() -> None:
    fixture = load_json_fixture(SKELETON_FIXTURE)

    first = run_replay_fixture(fixture)
    second = run_replay_fixture(fixture)

    assert first.state_digest == second.state_digest
    assert "raw" not in repr(first.state_digest).lower()
    assert "secret" not in repr(first.state_digest).lower()
    assert "credential" not in repr(first.state_digest).lower()
    assert "synthetic active-task patch" not in repr(first.state_digest).lower()


def test_slowtask_replay_does_not_call_network_clock_or_random(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = load_json_fixture(SKELETON_FIXTURE)

    monkeypatch.setattr(time, "time", lambda: pytest.fail("replay must not call wall clock"))
    monkeypatch.setattr(time, "monotonic", lambda: pytest.fail("replay must not call monotonic clock"))
    monkeypatch.setattr(random, "random", lambda: pytest.fail("replay must not call randomness"))
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *args, **kwargs: pytest.fail("replay must not call network"),
    )

    assert run_replay_fixture(fixture).state_digest["slowtask_state_hash"]


def test_slowtask_replay_rejects_illegal_state_transitions_instead_of_silently_passing() -> None:
    fixture = load_json_fixture(SKELETON_FIXTURE)
    transition = next(
        event for event in fixture["events"] if event["event_id"] == "evt_mvp1_slice3_state_replanned"
    )
    transition["to_state"] = "CREATED"
    transition["reason"] = "illegal_backwards_transition"

    with pytest.raises(ReplayValidationError, match="Illegal SlowTask transition"):
        run_replay_fixture(fixture)


def test_replay_rejects_old_plan_tool_result_without_stale_evidence_chain() -> None:
    fixture = {
        "replay_manifest": {
            "manifest_schema_version": "1.0",
            "replay_id": "replay_mvp1_old_plan_tool_result_without_stale_chain",
            "source_trace_ref": "fixture://mvp1/old-plan-tool-result-without-stale-chain",
            "replay_mode": "deterministic",
            "event_schema_version_range": ["1.0"],
            "fixture_domain": "GITHUB_ALLOWED",
            "generated_from": "synthetic",
            "contains_raw_audio": False,
            "contains_raw_trace": False,
            "contains_real_user_input": False,
            "contains_secrets": False,
            "contains_unredacted_tool_result": False,
            "contains_large_raw_web_content": False,
            "allowed_re_eval_components": [],
        },
        "events": [
            {
                "event_name": "SESSION_STARTED",
                "event_id": "evt_slice3_old_result_session",
                "event_seq": 1,
                "event_schema_version": "1.0",
                "session_id": "sess_slice3_old_result",
                "conversation_id": "conv_slice3_old_result",
                "source_module": "session_runtime",
                "created_monotonic_ms": 10,
                "created_wall_clock_ms": 1700000003010,
                "trace_redaction_level": "metadata_only",
                "runtime_config_ref": "config://synthetic/mvp1/default",
                "capability_snapshot_ref": "capability://synthetic/mvp1/mock-adapters-v1",
            },
            {
                "event_name": "SLOWTASK_CREATED",
                "event_id": "evt_slice3_old_result_created",
                "event_seq": 2,
                "event_schema_version": "1.0",
                "session_id": "sess_slice3_old_result",
                "conversation_id": "conv_slice3_old_result",
                "source_module": "slowtask_runtime",
                "created_monotonic_ms": 20,
                "created_wall_clock_ms": 1700000003020,
                "caused_by_event_id": "evt_slice3_old_result_session",
                "trace_redaction_level": "metadata_only",
                "task_id": "task_slice3_old_result",
                "plan_version": 1,
                "task_event_seq": 1,
                "initial_goal_ref": "goal://synthetic/mvp1/slice3/old-result",
            },
            {
                "event_name": "SLOWTASK_STATE_CHANGED",
                "event_id": "evt_slice3_old_result_planning",
                "event_seq": 3,
                "event_schema_version": "1.0",
                "session_id": "sess_slice3_old_result",
                "conversation_id": "conv_slice3_old_result",
                "source_module": "slowtask_runtime",
                "created_monotonic_ms": 30,
                "created_wall_clock_ms": 1700000003030,
                "caused_by_event_id": "evt_slice3_old_result_created",
                "trace_redaction_level": "metadata_only",
                "task_id": "task_slice3_old_result",
                "plan_version": 1,
                "task_event_seq": 2,
                "from_state": "CREATED",
                "to_state": "PLANNING",
                "reason": "initial_planning_started",
            },
            {
                "event_name": "TOOL_CALL_STARTED",
                "event_id": "evt_slice3_old_result_tool_call",
                "event_seq": 4,
                "event_schema_version": "1.0",
                "session_id": "sess_slice3_old_result",
                "conversation_id": "conv_slice3_old_result",
                "source_module": "slowtask_runtime",
                "created_monotonic_ms": 40,
                "created_wall_clock_ms": 1700000003040,
                "caused_by_event_id": "evt_slice3_old_result_planning",
                "trace_redaction_level": "metadata_only",
                "task_id": "task_slice3_old_result",
                "plan_version": 1,
                "task_event_seq": 3,
                "tool_call_id": "tool_call_slice3_old_result",
                "tool_name": "demo.synthetic",
                "idempotency_key": "idem://synthetic/mvp1/slice3/old-result",
            },
            {
                "event_name": "PLAN_VERSION_ADVANCED",
                "event_id": "evt_slice3_old_result_plan_advanced",
                "event_seq": 5,
                "event_schema_version": "1.0",
                "session_id": "sess_slice3_old_result",
                "conversation_id": "conv_slice3_old_result",
                "source_module": "slowtask_runtime",
                "created_monotonic_ms": 50,
                "created_wall_clock_ms": 1700000003050,
                "caused_by_event_id": "evt_slice3_old_result_tool_call",
                "trace_redaction_level": "metadata_only",
                "task_id": "task_slice3_old_result",
                "plan_version": 2,
                "task_event_seq": 4,
                "from_plan_version": 1,
                "to_plan_version": 2,
                "planning_reason": "synthetic_old_plan_stale_result_probe",
            },
            {
                "event_name": "TOOL_RESULT_RECEIVED",
                "event_id": "evt_slice3_old_result_without_stale",
                "event_seq": 6,
                "event_schema_version": "1.0",
                "session_id": "sess_slice3_old_result",
                "conversation_id": "conv_slice3_old_result",
                "source_module": "slowtask_runtime",
                "created_monotonic_ms": 60,
                "created_wall_clock_ms": 1700000003060,
                "caused_by_event_id": "evt_slice3_old_result_plan_advanced",
                "trace_redaction_level": "metadata_only",
                "tool_call_id": "tool_call_slice3_old_result",
                "task_id": "task_slice3_old_result",
                "plan_version": 1,
                "task_event_seq": 5,
                "result_status": "succeeded",
                "result_ref": "tool-result://synthetic/mvp1/slice3/old-result",
            },
        ],
    }

    with pytest.raises(ReplayValidationError, match="stale evidence"):
        run_replay_fixture(fixture)
