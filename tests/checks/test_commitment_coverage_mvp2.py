from __future__ import annotations

from typing import Any

import pytest

from voice_agent.checks import CheckPolicyError, MockCommitmentCoverageChecker
from voice_agent.composer.thinker_as_composer import MockThinkerAsComposer
from voice_agent.events.journal import InMemoryEventJournal


def test_commitment_derived_spoken_plan_coverage_passes() -> None:
    journal, caused_by_event_id = _journal_with_session()
    commitment = _append_commitment(
        journal,
        caused_by_event_id=caused_by_event_id,
        task_event_seq=1,
        immutable_fields=["final_result.status"],
        must_say_fields=["final_result.summary"],
        forbidden_rewrite_fields=["resolved_arguments"],
    )
    spoken = _emit_commitment_spoken(journal, commitment)

    check = MockCommitmentCoverageChecker(journal).check(
        spoken_plan_event=spoken,
        event_id="evt_mvp2_slice7_coverage_passed",
        created_monotonic_ms=40,
        created_wall_clock_ms=1700000070040,
        check_result_ref="check://synthetic/mvp2/slice7/coverage/pass",
    )

    assert check["event_name"] == "COMMITMENT_COVERAGE_CHECK_PASSED"
    assert check["source_module"] == "coverage_checker"
    assert check["caused_by_event_id"] == spoken["event_id"]
    assert check["spoken_plan_id"] == spoken["spoken_plan_id"]
    assert check["source_commitment_id"] == commitment["commitment_id"]
    assert check["checked_fields"] == [
        "coverage_check_required",
        "source_commitment_id",
        "immutable_fields",
        "must_say_fields",
        "forbidden_rewrite_fields",
        "source_progress_event_ids",
    ]
    assert check["check_result_ref"] == "check://synthetic/mvp2/slice7/coverage/pass"
    assert check["output_mode"] == "mock"
    assert check["task_event_seq"] == 3


def test_commitment_derived_spoken_plan_coverage_fails_for_altered_symbolic_metadata() -> None:
    journal, caused_by_event_id = _journal_with_session()
    commitment = _append_commitment(
        journal,
        caused_by_event_id=caused_by_event_id,
        task_event_seq=1,
        immutable_fields=["final_result.status"],
        must_say_fields=["final_result.summary"],
        forbidden_rewrite_fields=["resolved_arguments"],
    )
    spoken = _append_commitment_spoken(
        journal,
        caused_by_event_id=commitment["event_id"],
        task_event_seq=2,
        source_commitment_id=commitment["commitment_id"],
        immutable_fields=["final_result.status"],
        must_say_fields=[],
        forbidden_rewrite_fields=["resolved_arguments"],
    )

    check = MockCommitmentCoverageChecker(journal).check(
        spoken_plan_event=spoken,
        event_id="evt_mvp2_slice7_coverage_failed",
        created_monotonic_ms=40,
        created_wall_clock_ms=1700000070040,
        check_result_ref="check://synthetic/mvp2/slice7/coverage/fail",
    )

    assert check["event_name"] == "COMMITMENT_COVERAGE_CHECK_FAILED"
    assert check["spoken_plan_id"] == spoken["spoken_plan_id"]
    assert check["source_commitment_id"] == commitment["commitment_id"]
    assert check["failure_reasons"] == ["must_say_fields_mismatch"]
    assert check["check_result_ref"] == "check://synthetic/mvp2/slice7/coverage/fail"
    assert check["output_mode"] == "mock"


def test_commitment_coverage_checker_records_output_mode_on_failure() -> None:
    journal, caused_by_event_id = _journal_with_session()
    commitment = _append_commitment(journal, caused_by_event_id=caused_by_event_id, task_event_seq=1)
    spoken = _append_commitment_spoken(
        journal,
        caused_by_event_id=commitment["event_id"],
        task_event_seq=2,
        source_commitment_id="commitment_wrong",
    )

    check = MockCommitmentCoverageChecker(journal).check(
        spoken_plan_event=spoken,
        event_id="evt_mvp2_slice7_coverage_failed_output_mode",
        created_monotonic_ms=40,
        created_wall_clock_ms=1700000070040,
        check_result_ref="check://synthetic/mvp2/slice7/coverage/fail-output-mode",
    )

    assert check["event_name"] == "COMMITMENT_COVERAGE_CHECK_FAILED"
    assert check["output_mode"] == "mock"
    assert check["source_commitment_id"] == "commitment_wrong"
    assert check["failure_reasons"] == ["source_commitment_id_mismatch"]


def test_commitment_coverage_checker_fails_unexpected_truthfulness_requirement() -> None:
    journal, caused_by_event_id = _journal_with_session()
    commitment = _append_commitment(journal, caused_by_event_id=caused_by_event_id, task_event_seq=1)
    spoken = _append_commitment_spoken(
        journal,
        caused_by_event_id=commitment["event_id"],
        task_event_seq=2,
        source_commitment_id=commitment["commitment_id"],
        truthfulness_check_required=True,
    )

    check = MockCommitmentCoverageChecker(journal).check(
        spoken_plan_event=spoken,
        event_id="evt_mvp2_slice7_coverage_failed_truthfulness_required",
        created_monotonic_ms=40,
        created_wall_clock_ms=1700000070040,
        check_result_ref="check://synthetic/mvp2/slice7/coverage/fail-truthfulness-required",
    )

    assert check["event_name"] == "COMMITMENT_COVERAGE_CHECK_FAILED"
    assert "unexpected_truthfulness_check_required" in check["failure_reasons"]


def test_commitment_coverage_checker_refuses_non_composer_spoken_plan() -> None:
    journal, caused_by_event_id = _journal_with_session()
    commitment = _append_commitment(journal, caused_by_event_id=caused_by_event_id, task_event_seq=1)
    spoken = _append_commitment_spoken(
        journal,
        caused_by_event_id=commitment["event_id"],
        task_event_seq=2,
        source_commitment_id=commitment["commitment_id"],
        source_module="slowtask_runtime",
    )

    with pytest.raises(CheckPolicyError, match="source_module"):
        MockCommitmentCoverageChecker(journal).check(
            spoken_plan_event=spoken,
            event_id="evt_mvp2_slice7_non_composer_coverage_check",
            created_monotonic_ms=40,
            created_wall_clock_ms=1700000070040,
            check_result_ref="check://synthetic/mvp2/slice7/coverage/non-composer",
        )


def test_commitment_coverage_checker_refuses_stale_spoken_plan_after_plan_advance() -> None:
    journal, caused_by_event_id = _journal_with_session()
    commitment = _append_commitment(journal, caused_by_event_id=caused_by_event_id, task_event_seq=1)
    spoken = _emit_commitment_spoken(journal, commitment)
    journal.append(
        event_name="PLAN_VERSION_ADVANCED",
        event_id="evt_mvp2_slice7_plan_advanced_after_spoken",
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
        MockCommitmentCoverageChecker(journal).check(
            spoken_plan_event=spoken,
            event_id="evt_mvp2_slice7_stale_coverage_check",
            created_monotonic_ms=40,
            created_wall_clock_ms=1700000070040,
            check_result_ref="check://synthetic/mvp2/slice7/coverage/stale",
        )


def test_commitment_coverage_checker_refuses_progress_spoken_plan() -> None:
    journal, caused_by_event_id = _journal_with_session()
    progress = _append_progress(journal, caused_by_event_id=caused_by_event_id, task_event_seq=1)
    spoken = MockThinkerAsComposer(journal).emit_from_progress(
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
    )

    with pytest.raises(CheckPolicyError, match="semantic_commitment"):
        MockCommitmentCoverageChecker(journal).check(
            spoken_plan_event=spoken,
            event_id="evt_mvp2_slice7_wrong_source_coverage",
            created_monotonic_ms=40,
            created_wall_clock_ms=1700000070040,
            check_result_ref="check://synthetic/mvp2/slice7/coverage/wrong-source",
        )


def test_commitment_coverage_checker_refuses_missing_source_spoken_plan() -> None:
    journal, _caused_by_event_id = _journal_with_session()
    missing_spoken = {
        "event_name": "SPOKEN_PLAN_EMITTED",
        "event_id": "evt_mvp2_slice7_missing_spoken",
        "spoken_plan_id": "spoken_mvp2_slice7_missing",
        "source": "semantic_commitment",
    }

    with pytest.raises(CheckPolicyError, match="spoken plan event does not exist"):
        MockCommitmentCoverageChecker(journal).check(
            spoken_plan_event=missing_spoken,
            event_id="evt_mvp2_slice7_missing_spoken_check",
            created_monotonic_ms=40,
            created_wall_clock_ms=1700000070040,
            check_result_ref="check://synthetic/mvp2/slice7/coverage/missing-spoken",
        )


def _journal_with_session() -> tuple[InMemoryEventJournal, str]:
    journal = InMemoryEventJournal(
        session_id="sess_mvp2_slice7_checks",
        conversation_id="conv_mvp2_slice7_checks",
    )
    session_started = journal.append(
        event_name="SESSION_STARTED",
        event_id="evt_mvp2_slice7_session_started",
        source_module="session_runtime",
        created_monotonic_ms=10,
        created_wall_clock_ms=1700000070010,
        trace_redaction_level="metadata_only",
        runtime_config_ref="config://synthetic/mvp2/slice7",
        capability_snapshot_ref="capability://synthetic/mvp2/slice7/mock",
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
        event_id=f"evt_mvp2_slice7_commitment_{task_event_seq}",
        source_module="slowtask_runtime",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=20,
        created_wall_clock_ms=1700000070020,
        trace_redaction_level="metadata_only",
        task_id="task_mvp2_slice7",
        plan_version=1,
        task_event_seq=task_event_seq,
        commitment_id="commitment_mvp2_slice7",
        source_events=[caused_by_event_id],
        commitment_ref="commitment://synthetic/mvp2/slice7/final",
        **fields,
    )


def _emit_commitment_spoken(
    journal: InMemoryEventJournal,
    commitment: dict[str, Any],
) -> dict[str, Any]:
    return MockThinkerAsComposer(journal).emit_from_commitment(
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


def _append_commitment_spoken(
    journal: InMemoryEventJournal,
    *,
    caused_by_event_id: str,
    task_event_seq: int,
    source_commitment_id: str,
    source_module: str = "composer",
    immutable_fields: list[str] | None = None,
    must_say_fields: list[str] | None = None,
    forbidden_rewrite_fields: list[str] | None = None,
    truthfulness_check_required: bool = False,
) -> dict[str, Any]:
    return journal.append(
        event_name="SPOKEN_PLAN_EMITTED",
        event_id=f"evt_mvp2_slice7_commitment_spoken_{task_event_seq}",
        source_module=source_module,
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=30,
        created_wall_clock_ms=1700000070030,
        trace_redaction_level="metadata_only",
        spoken_plan_id=f"spoken_mvp2_slice7_commitment_{task_event_seq}",
        task_id="task_mvp2_slice7",
        plan_version=1,
        task_event_seq=task_event_seq,
        source_events=[caused_by_event_id],
        source_commitment_id=source_commitment_id,
        source_progress_event_ids=[],
        coverage_check_required=True,
        truthfulness_check_required=truthfulness_check_required,
        text_ref="spoken://synthetic/mvp2/slice7/commitment",
        emotion="calm",
        speaking_style="concise",
        interruptible=True,
        priority="normal",
        source="semantic_commitment",
        output_mode="mock",
        immutable_fields=immutable_fields or [],
        must_say_fields=must_say_fields or [],
        forbidden_rewrite_fields=forbidden_rewrite_fields or [],
    )


def _append_progress(
    journal: InMemoryEventJournal,
    *,
    caused_by_event_id: str,
    task_event_seq: int,
) -> dict[str, Any]:
    return journal.append(
        event_name="PLANNING_STARTED",
        event_id=f"evt_mvp2_slice7_planning_started_{task_event_seq}",
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
