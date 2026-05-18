from __future__ import annotations

from typing import Any

import pytest

from voice_agent.composer.thinker_as_composer import ComposerPolicyError, MockThinkerAsComposer
from voice_agent.events.journal import InMemoryEventJournal


def test_semantic_commitment_emits_spoken_plan_with_coverage_metadata() -> None:
    journal, caused_by_event_id = _journal_with_session()
    commitment = _append_commitment(
        journal,
        caused_by_event_id=caused_by_event_id,
        task_event_seq=1,
        immutable_fields=["final_result.status"],
        must_say_fields=["final_result.summary"],
        forbidden_rewrite_fields=["resolved_arguments"],
    )

    spoken = MockThinkerAsComposer(journal).emit_from_commitment(
        source_event=commitment,
        spoken_plan_id="spoken_mvp2_slice6_commitment",
        event_id="evt_mvp2_slice6_commitment_spoken",
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000060030,
        text_ref="spoken://synthetic/mvp2/slice6/commitment",
        emotion="calm",
        speaking_style="concise",
        interruptible=True,
        priority="normal",
    )

    assert spoken["event_name"] == "SPOKEN_PLAN_EMITTED"
    assert spoken["source_module"] == "composer"
    assert spoken["output_mode"] == "mock"
    assert spoken["task_id"] == "task_mvp2_slice6"
    assert spoken["plan_version"] == 1
    assert spoken["task_event_seq"] == 2
    assert spoken["caused_by_event_id"] == commitment["event_id"]
    assert spoken["source_events"] == [commitment["event_id"]]
    assert spoken["source_commitment_id"] == "commitment_mvp2_slice6"
    assert spoken["source_progress_event_ids"] == []
    assert spoken["coverage_check_required"] is True
    assert spoken["truthfulness_check_required"] is False
    assert spoken["immutable_fields"] == ["final_result.status"]
    assert spoken["must_say_fields"] == ["final_result.summary"]
    assert spoken["forbidden_rewrite_fields"] == ["resolved_arguments"]


def test_progress_source_emits_spoken_plan_with_truthfulness_metadata() -> None:
    journal, caused_by_event_id = _journal_with_session()
    progress = journal.append(
        event_name="PLANNING_STARTED",
        event_id="evt_mvp2_slice6_planning_started",
        source_module="slowtask_runtime",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=20,
        created_wall_clock_ms=1700000060020,
        trace_redaction_level="metadata_only",
        task_id="task_mvp2_slice6",
        plan_version=1,
        task_event_seq=1,
        planning_reason="synthetic_initial_plan",
    )

    spoken = MockThinkerAsComposer(journal).emit_from_progress(
        source_events=[progress],
        spoken_plan_id="spoken_mvp2_slice6_progress",
        event_id="evt_mvp2_slice6_progress_spoken",
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000060030,
        text_ref="spoken://synthetic/mvp2/slice6/progress/planning",
        emotion="focused",
        speaking_style="brief",
        interruptible=True,
        priority="low",
        truthfulness_level="STATE_GROUNDED",
    )

    assert spoken["event_name"] == "SPOKEN_PLAN_EMITTED"
    assert spoken["output_mode"] == "mock"
    assert spoken["task_id"] == "task_mvp2_slice6"
    assert spoken["plan_version"] == 1
    assert spoken["task_event_seq"] == 2
    assert spoken["source_events"] == [progress["event_id"]]
    assert spoken["source_progress_event_ids"] == [progress["event_id"]]
    assert "source_commitment_id" not in spoken
    assert spoken["coverage_check_required"] is False
    assert spoken["truthfulness_check_required"] is True
    assert spoken["truthfulness_level"] == "STATE_GROUNDED"


def test_composer_event_records_task_plan_and_next_task_event_seq() -> None:
    journal, caused_by_event_id = _journal_with_session()
    progress = journal.append(
        event_name="FINALIZING",
        event_id="evt_mvp2_slice6_finalizing",
        source_module="slowtask_runtime",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=20,
        created_wall_clock_ms=1700000060020,
        trace_redaction_level="metadata_only",
        task_id="task_mvp2_slice6",
        plan_version=2,
        task_event_seq=7,
        source_events=[caused_by_event_id],
    )

    spoken = MockThinkerAsComposer(journal).emit_from_progress(
        source_events=[progress],
        spoken_plan_id="spoken_mvp2_slice6_finalizing",
        event_id="evt_mvp2_slice6_finalizing_spoken",
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000060030,
        text_ref="spoken://synthetic/mvp2/slice6/progress/finalizing",
        emotion="calm",
        speaking_style="brief",
        interruptible=True,
        priority="normal",
    )

    assert (spoken["task_id"], spoken["plan_version"], spoken["task_event_seq"]) == (
        "task_mvp2_slice6",
        2,
        8,
    )


def test_composer_refuses_stale_plan_source() -> None:
    journal, caused_by_event_id = _journal_with_session()
    commitment = _append_commitment(
        journal,
        caused_by_event_id=caused_by_event_id,
        task_event_seq=1,
    )
    journal.append(
        event_name="PLAN_VERSION_ADVANCED",
        event_id="evt_mvp2_slice6_plan_advanced",
        source_module="slowtask_runtime",
        caused_by_event_id=commitment["event_id"],
        created_monotonic_ms=25,
        created_wall_clock_ms=1700000060025,
        trace_redaction_level="metadata_only",
        task_id="task_mvp2_slice6",
        plan_version=2,
        task_event_seq=2,
        from_plan_version=1,
        to_plan_version=2,
        planning_reason="synthetic_material_patch",
    )

    with pytest.raises(ComposerPolicyError, match="stale plan"):
        MockThinkerAsComposer(journal).emit_from_commitment(
            source_event=commitment,
            spoken_plan_id="spoken_stale",
            event_id="evt_mvp2_slice6_stale_spoken",
            created_monotonic_ms=30,
            created_wall_clock_ms=1700000060030,
            text_ref="spoken://synthetic/mvp2/slice6/stale",
            emotion="calm",
            speaking_style="brief",
            interruptible=True,
            priority="normal",
        )


@pytest.mark.parametrize(
    ("expected_task_id", "expected_plan_version", "match"),
    [
        ("task_other", 1, "task_id"),
        ("task_mvp2_slice6", 2, "plan_version"),
    ],
)
def test_composer_refuses_wrong_task_or_wrong_plan_source(
    expected_task_id: str,
    expected_plan_version: int,
    match: str,
) -> None:
    journal, caused_by_event_id = _journal_with_session()
    commitment = _append_commitment(
        journal,
        caused_by_event_id=caused_by_event_id,
        task_event_seq=1,
    )

    with pytest.raises(ComposerPolicyError, match=match):
        MockThinkerAsComposer(journal).emit_from_commitment(
            source_event=commitment,
            spoken_plan_id="spoken_wrong_binding",
            event_id="evt_mvp2_slice6_wrong_binding_spoken",
            created_monotonic_ms=30,
            created_wall_clock_ms=1700000060030,
            text_ref="spoken://synthetic/mvp2/slice6/wrong-binding",
            emotion="calm",
            speaking_style="brief",
            interruptible=True,
            priority="normal",
            expected_task_id=expected_task_id,
            expected_plan_version=expected_plan_version,
        )


def test_composer_refuses_unsupported_progress_source() -> None:
    journal, caused_by_event_id = _journal_with_session()
    unsupported = journal.append(
        event_name="SLOWTASK_CREATED",
        event_id="evt_mvp2_slice6_slowtask_created",
        source_module="slowtask_runtime",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=20,
        created_wall_clock_ms=1700000060020,
        trace_redaction_level="metadata_only",
        task_id="task_mvp2_slice6",
        plan_version=1,
        task_event_seq=1,
        initial_goal_ref="goal://synthetic/mvp2/slice6",
    )

    with pytest.raises(ComposerPolicyError, match="unsupported progress source"):
        MockThinkerAsComposer(journal).emit_from_progress(
            source_events=[unsupported],
            spoken_plan_id="spoken_unsupported",
            event_id="evt_mvp2_slice6_unsupported_spoken",
            created_monotonic_ms=30,
            created_wall_clock_ms=1700000060030,
            text_ref="spoken://synthetic/mvp2/slice6/unsupported",
            emotion="calm",
            speaking_style="brief",
            interruptible=True,
            priority="normal",
        )


def test_composer_refuses_missing_source_event() -> None:
    journal, _caused_by_event_id = _journal_with_session()
    missing_source = {
        "event_name": "PLANNING_STARTED",
        "event_id": "evt_mvp2_slice6_missing_source",
        "task_id": "task_mvp2_slice6",
        "plan_version": 1,
        "task_event_seq": 1,
    }

    with pytest.raises(ComposerPolicyError, match="source event does not exist"):
        MockThinkerAsComposer(journal).emit_from_progress(
            source_events=[missing_source],
            spoken_plan_id="spoken_missing",
            event_id="evt_mvp2_slice6_missing_spoken",
            created_monotonic_ms=30,
            created_wall_clock_ms=1700000060030,
            text_ref="spoken://synthetic/mvp2/slice6/missing",
            emotion="calm",
            speaking_style="brief",
            interruptible=True,
            priority="normal",
        )


def test_composer_refuses_missing_source_commitment_id() -> None:
    journal, caused_by_event_id = _journal_with_session()
    commitment = _append_commitment(
        journal,
        caused_by_event_id=caused_by_event_id,
        task_event_seq=1,
    )

    with pytest.raises(ComposerPolicyError, match="source_commitment_id"):
        MockThinkerAsComposer(journal).emit_from_commitment(
            source_event=commitment,
            spoken_plan_id="spoken_missing_commitment",
            event_id="evt_mvp2_slice6_missing_commitment_spoken",
            created_monotonic_ms=30,
            created_wall_clock_ms=1700000060030,
            text_ref="spoken://synthetic/mvp2/slice6/missing-commitment",
            emotion="calm",
            speaking_style="brief",
            interruptible=True,
            priority="normal",
            source_commitment_id="",
        )


def test_composer_refuses_missing_source_progress_event_ids() -> None:
    journal, caused_by_event_id = _journal_with_session()
    progress = journal.append(
        event_name="WAITING_FOR_TOOL",
        event_id="evt_mvp2_slice6_waiting_for_tool",
        source_module="slowtask_runtime",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=20,
        created_wall_clock_ms=1700000060020,
        trace_redaction_level="metadata_only",
        task_id="task_mvp2_slice6",
        plan_version=1,
        task_event_seq=1,
        tool_call_id="tool_call_mvp2_slice6",
    )

    with pytest.raises(ComposerPolicyError, match="source_progress_event_ids"):
        MockThinkerAsComposer(journal).emit_from_progress(
            source_events=[progress],
            spoken_plan_id="spoken_missing_progress_ids",
            event_id="evt_mvp2_slice6_missing_progress_ids_spoken",
            created_monotonic_ms=30,
            created_wall_clock_ms=1700000060030,
            text_ref="spoken://synthetic/mvp2/slice6/missing-progress-ids",
            emotion="calm",
            speaking_style="brief",
            interruptible=True,
            priority="normal",
            source_progress_event_ids=[],
        )


def test_composer_does_not_emit_checks_or_playback_events() -> None:
    journal, caused_by_event_id = _journal_with_session()
    commitment = _append_commitment(
        journal,
        caused_by_event_id=caused_by_event_id,
        task_event_seq=1,
    )

    MockThinkerAsComposer(journal).emit_from_commitment(
        source_event=commitment,
        spoken_plan_id="spoken_no_playback",
        event_id="evt_mvp2_slice6_no_playback_spoken",
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000060030,
        text_ref="spoken://synthetic/mvp2/slice6/no-playback",
        emotion="calm",
        speaking_style="brief",
        interruptible=True,
        priority="normal",
    )

    emitted = [event["event_name"] for event in journal.events()]
    assert "SPOKEN_PLAN_EMITTED" in emitted
    assert "COMMITMENT_COVERAGE_CHECK_PASSED" not in emitted
    assert "COMMITMENT_COVERAGE_CHECK_FAILED" not in emitted
    assert "PROGRESS_TRUTHFULNESS_CHECK_PASSED" not in emitted
    assert "PROGRESS_TRUTHFULNESS_CHECK_FAILED" not in emitted
    assert not any(event_name.startswith("PLAYBACK_") for event_name in emitted)


def test_composer_text_refs_do_not_embed_raw_user_args_or_secret_like_values() -> None:
    journal, caused_by_event_id = _journal_with_session()
    commitment = _append_commitment(
        journal,
        caused_by_event_id=caused_by_event_id,
        task_event_seq=1,
    )

    spoken = MockThinkerAsComposer(journal).emit_from_commitment(
        source_event=commitment,
        spoken_plan_id="spoken_safe_ref",
        event_id="evt_mvp2_slice6_safe_ref_spoken",
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000060030,
        text_ref="spoken://synthetic/mvp2/slice6/safe-ref",
        emotion="calm",
        speaking_style="brief",
        interruptible=True,
        priority="normal",
    )

    for field in ("text_ref", "spoken_plan_id"):
        value = str(spoken[field]).lower()
        assert "testville" not in value
        assert "secret" not in value
        assert "token" not in value
        assert "password" not in value


def _journal_with_session() -> tuple[InMemoryEventJournal, str]:
    journal = InMemoryEventJournal(
        session_id="sess_mvp2_slice6",
        conversation_id="conv_mvp2_slice6",
    )
    session_started = journal.append(
        event_name="SESSION_STARTED",
        event_id="evt_mvp2_slice6_session_started",
        source_module="session_runtime",
        created_monotonic_ms=10,
        created_wall_clock_ms=1700000060010,
        trace_redaction_level="metadata_only",
        runtime_config_ref="config://synthetic/mvp2/slice6",
        capability_snapshot_ref="capability://synthetic/mvp2/slice6/mock",
    )
    return journal, str(session_started["event_id"])


def _append_commitment(
    journal: InMemoryEventJournal,
    *,
    caused_by_event_id: str,
    task_event_seq: int,
    **fields: Any,
) -> dict[str, Any]:
    return journal.append(
        event_name="SEMANTIC_COMMITMENT_EMITTED",
        event_id=f"evt_mvp2_slice6_commitment_{task_event_seq}",
        source_module="slowtask_runtime",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=20,
        created_wall_clock_ms=1700000060020,
        trace_redaction_level="metadata_only",
        task_id="task_mvp2_slice6",
        plan_version=1,
        task_event_seq=task_event_seq,
        commitment_id="commitment_mvp2_slice6",
        source_events=[caused_by_event_id],
        commitment_ref="commitment://synthetic/mvp2/slice6/final",
        **fields,
    )
