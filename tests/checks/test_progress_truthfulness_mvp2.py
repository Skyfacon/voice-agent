from __future__ import annotations

import pytest

from voice_agent.checks import CheckPolicyError, MockProgressTruthfulnessChecker
from voice_agent.composer.thinker_as_composer import MockThinkerAsComposer
from voice_agent.events.journal import InMemoryEventJournal


def test_progress_derived_spoken_plan_truthfulness_passes() -> None:
    journal, caused_by_event_id = _journal_with_session()
    progress = _append_progress(journal, caused_by_event_id=caused_by_event_id, task_event_seq=1)
    spoken = _emit_progress_spoken(journal, progress)

    check = MockProgressTruthfulnessChecker(journal).check(
        spoken_plan_event=spoken,
        event_id="evt_mvp2_slice7_truthfulness_passed",
        created_monotonic_ms=40,
        created_wall_clock_ms=1700000070040,
        check_result_ref="check://synthetic/mvp2/slice7/truthfulness/pass",
    )

    assert check["event_name"] == "PROGRESS_TRUTHFULNESS_CHECK_PASSED"
    assert check["source_module"] == "truthfulness_checker"
    assert check["caused_by_event_id"] == spoken["event_id"]
    assert check["spoken_plan_id"] == spoken["spoken_plan_id"]
    assert check["source_progress_event_ids"] == [progress["event_id"]]
    assert check["truthfulness_level"] == "STATE_GROUNDED"
    assert check["check_result_ref"] == "check://synthetic/mvp2/slice7/truthfulness/pass"
    assert check["output_mode"] == "mock"
    assert check["task_event_seq"] == 3


def test_progress_derived_spoken_plan_truthfulness_fails_for_unsupported_level() -> None:
    journal, caused_by_event_id = _journal_with_session()
    progress = _append_progress(journal, caused_by_event_id=caused_by_event_id, task_event_seq=1)
    spoken = _append_progress_spoken(
        journal,
        caused_by_event_id=progress["event_id"],
        task_event_seq=2,
        source_progress_event_ids=[progress["event_id"]],
        truthfulness_level="ESTIMATE_WITH_BASIS",
    )

    check = MockProgressTruthfulnessChecker(journal).check(
        spoken_plan_event=spoken,
        event_id="evt_mvp2_slice7_truthfulness_failed",
        created_monotonic_ms=40,
        created_wall_clock_ms=1700000070040,
        check_result_ref="check://synthetic/mvp2/slice7/truthfulness/fail",
    )

    assert check["event_name"] == "PROGRESS_TRUTHFULNESS_CHECK_FAILED"
    assert check["spoken_plan_id"] == spoken["spoken_plan_id"]
    assert check["source_progress_event_ids"] == [progress["event_id"]]
    assert check["truthfulness_level"] == "ESTIMATE_WITH_BASIS"
    assert check["failure_reasons"] == ["unsupported_truthfulness_level"]
    assert check["check_result_ref"] == "check://synthetic/mvp2/slice7/truthfulness/fail"
    assert check["output_mode"] == "mock"


def test_progress_truthfulness_checker_records_output_mode_on_missing_sources_failure() -> None:
    journal, caused_by_event_id = _journal_with_session()
    progress = _append_progress(journal, caused_by_event_id=caused_by_event_id, task_event_seq=1)
    spoken = _append_progress_spoken(
        journal,
        caused_by_event_id=progress["event_id"],
        task_event_seq=2,
        source_progress_event_ids=[],
        truthfulness_level="STATE_GROUNDED",
    )

    check = MockProgressTruthfulnessChecker(journal).check(
        spoken_plan_event=spoken,
        event_id="evt_mvp2_slice7_truthfulness_failed_output_mode",
        created_monotonic_ms=40,
        created_wall_clock_ms=1700000070040,
        check_result_ref="check://synthetic/mvp2/slice7/truthfulness/fail-output-mode",
    )

    assert check["event_name"] == "PROGRESS_TRUTHFULNESS_CHECK_FAILED"
    assert check["output_mode"] == "mock"
    assert check["failure_reasons"] == [
        "missing_source_progress_event_ids",
        "source_progress_event_ids_mismatch",
    ]


def test_progress_truthfulness_checker_fails_commitment_metadata_on_progress_spoken_plan() -> None:
    journal, caused_by_event_id = _journal_with_session()
    progress = _append_progress(journal, caused_by_event_id=caused_by_event_id, task_event_seq=1)
    spoken = _append_progress_spoken(
        journal,
        caused_by_event_id=progress["event_id"],
        task_event_seq=2,
        source_progress_event_ids=[progress["event_id"]],
        truthfulness_level="STATE_GROUNDED",
        coverage_check_required=True,
        source_commitment_id="commitment_mvp2_slice7_unexpected",
    )

    check = MockProgressTruthfulnessChecker(journal).check(
        spoken_plan_event=spoken,
        event_id="evt_mvp2_slice7_truthfulness_failed_commitment_metadata",
        created_monotonic_ms=40,
        created_wall_clock_ms=1700000070040,
        check_result_ref="check://synthetic/mvp2/slice7/truthfulness/fail-commitment-metadata",
    )

    assert check["event_name"] == "PROGRESS_TRUTHFULNESS_CHECK_FAILED"
    assert check["failure_reasons"] == [
        "unexpected_coverage_check_required",
        "unexpected_source_commitment_id",
    ]


def test_progress_truthfulness_checker_refuses_stale_spoken_plan_after_plan_advance() -> None:
    journal, caused_by_event_id = _journal_with_session()
    progress = _append_progress(journal, caused_by_event_id=caused_by_event_id, task_event_seq=1)
    spoken = _emit_progress_spoken(journal, progress)
    journal.append(
        event_name="PLAN_VERSION_ADVANCED",
        event_id="evt_mvp2_slice7_truthfulness_plan_advanced_after_spoken",
        source_module="slowtask_runtime",
        caused_by_event_id=spoken["event_id"],
        created_monotonic_ms=35,
        created_wall_clock_ms=1700000070035,
        trace_redaction_level="metadata_only",
        task_id="task_mvp2_slice7",
        plan_version=2,
        task_event_seq=3,
        from_plan_version=1,
        to_plan_version=2,
        planning_reason="synthetic_late_patch",
    )

    with pytest.raises(CheckPolicyError, match="stale"):
        MockProgressTruthfulnessChecker(journal).check(
            spoken_plan_event=spoken,
            event_id="evt_mvp2_slice7_stale_truthfulness_check",
            created_monotonic_ms=40,
            created_wall_clock_ms=1700000070040,
            check_result_ref="check://synthetic/mvp2/slice7/truthfulness/stale",
        )


def test_progress_truthfulness_checker_refuses_commitment_spoken_plan() -> None:
    journal, caused_by_event_id = _journal_with_session()
    commitment = journal.append(
        event_name="SEMANTIC_COMMITMENT_EMITTED",
        event_id="evt_mvp2_slice7_commitment",
        source_module="slowtask_runtime",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=20,
        created_wall_clock_ms=1700000070020,
        trace_redaction_level="metadata_only",
        task_id="task_mvp2_slice7",
        plan_version=1,
        task_event_seq=1,
        commitment_id="commitment_mvp2_slice7",
        source_events=[caused_by_event_id],
        commitment_ref="commitment://synthetic/mvp2/slice7/final",
    )
    spoken = MockThinkerAsComposer(journal).emit_from_commitment(
        source_event=commitment,
        spoken_plan_id="spoken_mvp2_slice7_commitment",
        event_id="evt_mvp2_slice7_commitment_spoken",
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000070030,
        text_ref="spoken://synthetic/mvp2/slice7/commitment",
        emotion="calm",
        speaking_style="concise",
        interruptible=True,
        priority="normal",
    )

    with pytest.raises(CheckPolicyError, match="grounded_progress"):
        MockProgressTruthfulnessChecker(journal).check(
            spoken_plan_event=spoken,
            event_id="evt_mvp2_slice7_wrong_source_truthfulness",
            created_monotonic_ms=40,
            created_wall_clock_ms=1700000070040,
            check_result_ref="check://synthetic/mvp2/slice7/truthfulness/wrong-source",
        )


def test_progress_truthfulness_checker_refuses_missing_source_spoken_plan() -> None:
    journal, _caused_by_event_id = _journal_with_session()
    missing_spoken = {
        "event_name": "SPOKEN_PLAN_EMITTED",
        "event_id": "evt_mvp2_slice7_missing_spoken",
        "spoken_plan_id": "spoken_mvp2_slice7_missing",
        "source": "grounded_progress",
    }

    with pytest.raises(CheckPolicyError, match="spoken plan event does not exist"):
        MockProgressTruthfulnessChecker(journal).check(
            spoken_plan_event=missing_spoken,
            event_id="evt_mvp2_slice7_missing_spoken_check",
            created_monotonic_ms=40,
            created_wall_clock_ms=1700000070040,
            check_result_ref="check://synthetic/mvp2/slice7/truthfulness/missing-spoken",
        )


def _journal_with_session() -> tuple[InMemoryEventJournal, str]:
    journal = InMemoryEventJournal(
        session_id="sess_mvp2_slice7_truthfulness",
        conversation_id="conv_mvp2_slice7_truthfulness",
    )
    session_started = journal.append(
        event_name="SESSION_STARTED",
        event_id="evt_mvp2_slice7_truthfulness_session_started",
        source_module="session_runtime",
        created_monotonic_ms=10,
        created_wall_clock_ms=1700000070010,
        trace_redaction_level="metadata_only",
        runtime_config_ref="config://synthetic/mvp2/slice7",
        capability_snapshot_ref="capability://synthetic/mvp2/slice7/mock",
    )
    return journal, str(session_started["event_id"])


def _append_progress(
    journal: InMemoryEventJournal,
    *,
    caused_by_event_id: str,
    task_event_seq: int,
) -> dict[str, object]:
    return journal.append(
        event_name="PLANNING_STARTED",
        event_id=f"evt_mvp2_slice7_truthfulness_planning_{task_event_seq}",
        source_module="slowtask_runtime",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=20,
        created_wall_clock_ms=1700000070020,
        trace_redaction_level="metadata_only",
        task_id="task_mvp2_slice7",
        plan_version=1,
        task_event_seq=task_event_seq,
        planning_reason="synthetic_initial_plan",
    )


def _emit_progress_spoken(
    journal: InMemoryEventJournal,
    progress: dict[str, object],
) -> dict[str, object]:
    return MockThinkerAsComposer(journal).emit_from_progress(
        source_events=[progress],
        spoken_plan_id="spoken_mvp2_slice7_progress",
        event_id="evt_mvp2_slice7_progress_spoken",
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000070030,
        text_ref="spoken://synthetic/mvp2/slice7/progress",
        emotion="focused",
        speaking_style="brief",
        interruptible=True,
        priority="low",
        truthfulness_level="STATE_GROUNDED",
    )


def _append_progress_spoken(
    journal: InMemoryEventJournal,
    *,
    caused_by_event_id: str,
    task_event_seq: int,
    source_progress_event_ids: list[object],
    truthfulness_level: str,
    coverage_check_required: bool = False,
    source_commitment_id: str | None = None,
) -> dict[str, object]:
    fields: dict[str, object] = {}
    if source_commitment_id is not None:
        fields["source_commitment_id"] = source_commitment_id
    return journal.append(
        event_name="SPOKEN_PLAN_EMITTED",
        event_id=f"evt_mvp2_slice7_progress_spoken_{task_event_seq}",
        source_module="composer",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000070030,
        trace_redaction_level="metadata_only",
        spoken_plan_id=f"spoken_mvp2_slice7_progress_{task_event_seq}",
        task_id="task_mvp2_slice7",
        plan_version=1,
        task_event_seq=task_event_seq,
        source_events=[caused_by_event_id],
        source_progress_event_ids=source_progress_event_ids,
        coverage_check_required=coverage_check_required,
        truthfulness_check_required=True,
        truthfulness_level=truthfulness_level,
        text_ref="spoken://synthetic/mvp2/slice7/progress",
        emotion="focused",
        speaking_style="brief",
        interruptible=True,
        priority="low",
        source="grounded_progress",
        output_mode="mock",
        **fields,
    )
