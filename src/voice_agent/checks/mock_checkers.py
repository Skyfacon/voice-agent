from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from voice_agent.adapters.capabilities import OUTPUT_MODES
from voice_agent.composer.constants import (
    ALLOWED_PROGRESS_SOURCE_EVENTS,
    ALLOWED_SOURCE_MODULES_BY_EVENT,
    ALLOWED_TRUTHFULNESS_LEVELS,
)
from voice_agent.events.journal import InMemoryEventJournal


CHECK_OUTPUT_MODE = "mock"
COMMITMENT_CHECKED_FIELDS = [
    "coverage_check_required",
    "source_commitment_id",
    "immutable_fields",
    "must_say_fields",
    "forbidden_rewrite_fields",
    "source_progress_event_ids",
]
COMMITMENT_SYMBOLIC_METADATA_FIELDS = (
    "immutable_fields",
    "must_say_fields",
    "forbidden_rewrite_fields",
)


class CheckPolicyError(ValueError):
    pass


class MockCommitmentCoverageChecker:
    """Deterministic MVP-2 coverage checker.

    The checker verifies recorded metadata and causal refs only. It does not
    read spoken text, call a model/provider, synthesize audio, or authorize
    playback.
    """

    def __init__(self, journal: InMemoryEventJournal) -> None:
        self._journal = journal

    def check(
        self,
        *,
        spoken_plan_event: Mapping[str, Any],
        event_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        check_result_ref: str,
    ) -> dict[str, Any]:
        spoken = _validated_spoken_plan_event(self._journal, spoken_plan_event)
        if spoken.get("source") != "semantic_commitment":
            raise CheckPolicyError("Commitment coverage check requires semantic_commitment SpokenPlan source")

        source_commitment = _source_event_for_spoken_plan(
            self._journal,
            spoken,
            expected_event_name="SEMANTIC_COMMITMENT_EMITTED",
        )
        failure_reasons = _commitment_coverage_failure_reasons(spoken, source_commitment)
        source_commitment_id = _safe_source_commitment_id(spoken)

        if failure_reasons:
            return _append_check_event(
                self._journal,
                event_name="COMMITMENT_COVERAGE_CHECK_FAILED",
                event_id=event_id,
                source_module="coverage_checker",
                spoken=spoken,
                created_monotonic_ms=created_monotonic_ms,
                created_wall_clock_ms=created_wall_clock_ms,
                check_result_ref=check_result_ref,
                source_commitment_id=source_commitment_id,
                failure_reasons=failure_reasons,
                output_mode=CHECK_OUTPUT_MODE,
            )

        return _append_check_event(
            self._journal,
            event_name="COMMITMENT_COVERAGE_CHECK_PASSED",
            event_id=event_id,
            source_module="coverage_checker",
            spoken=spoken,
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            check_result_ref=check_result_ref,
            source_commitment_id=source_commitment_id,
            checked_fields=COMMITMENT_CHECKED_FIELDS,
            output_mode=CHECK_OUTPUT_MODE,
        )


class MockProgressTruthfulnessChecker:
    """Deterministic MVP-2 progress truthfulness checker."""

    def __init__(self, journal: InMemoryEventJournal) -> None:
        self._journal = journal

    def check(
        self,
        *,
        spoken_plan_event: Mapping[str, Any],
        event_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        check_result_ref: str,
    ) -> dict[str, Any]:
        spoken = _validated_spoken_plan_event(self._journal, spoken_plan_event)
        if spoken.get("source") != "grounded_progress":
            raise CheckPolicyError("Progress truthfulness check requires grounded_progress SpokenPlan source")

        source_progress_events = _source_progress_events_for_spoken_plan(self._journal, spoken)
        source_progress_event_ids = _string_list(spoken.get("source_progress_event_ids"))
        truthfulness_level = _optional_string(spoken.get("truthfulness_level"))
        failure_reasons = _progress_truthfulness_failure_reasons(
            spoken,
            source_progress_events=source_progress_events,
            source_progress_event_ids=source_progress_event_ids,
            truthfulness_level=truthfulness_level,
        )

        if failure_reasons:
            failure_fields: dict[str, Any] = {
                "source_progress_event_ids": source_progress_event_ids,
                "failure_reasons": failure_reasons,
            }
            if truthfulness_level is not None:
                failure_fields["truthfulness_level"] = truthfulness_level
            return _append_check_event(
                self._journal,
                event_name="PROGRESS_TRUTHFULNESS_CHECK_FAILED",
                event_id=event_id,
                source_module="truthfulness_checker",
                spoken=spoken,
                created_monotonic_ms=created_monotonic_ms,
                created_wall_clock_ms=created_wall_clock_ms,
                check_result_ref=check_result_ref,
                output_mode=CHECK_OUTPUT_MODE,
                **failure_fields,
            )

        if truthfulness_level is None:
            raise CheckPolicyError("truthfulness_level is required for passed truthfulness check")
        return _append_check_event(
            self._journal,
            event_name="PROGRESS_TRUTHFULNESS_CHECK_PASSED",
            event_id=event_id,
            source_module="truthfulness_checker",
            spoken=spoken,
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            check_result_ref=check_result_ref,
            source_progress_event_ids=source_progress_event_ids,
            truthfulness_level=truthfulness_level,
            output_mode=CHECK_OUTPUT_MODE,
        )


def _commitment_coverage_failure_reasons(
    spoken: Mapping[str, Any],
    source_commitment: Mapping[str, Any] | None,
) -> list[str]:
    failure_reasons: list[str] = []
    if spoken.get("coverage_check_required") is not True:
        failure_reasons.append("coverage_check_not_required")
    if spoken.get("truthfulness_check_required") is not False:
        failure_reasons.append("unexpected_truthfulness_check_required")
    if _string_list(spoken.get("source_progress_event_ids")):
        failure_reasons.append("unexpected_progress_source_ids")

    spoken_commitment_id = _optional_string(spoken.get("source_commitment_id"))
    source_commitment_id = _optional_string(source_commitment.get("commitment_id")) if source_commitment else None
    if spoken_commitment_id is None:
        failure_reasons.append("missing_source_commitment_id")
    elif source_commitment_id is None:
        failure_reasons.append("missing_source_commitment_event")
    elif spoken_commitment_id != source_commitment_id:
        failure_reasons.append("source_commitment_id_mismatch")

    if source_commitment is not None:
        for field in COMMITMENT_SYMBOLIC_METADATA_FIELDS:
            if _string_list(spoken.get(field)) != _string_list(source_commitment.get(field)):
                failure_reasons.append(f"{field}_mismatch")
    return failure_reasons


def _progress_truthfulness_failure_reasons(
    spoken: Mapping[str, Any],
    *,
    source_progress_events: list[Mapping[str, Any]],
    source_progress_event_ids: list[str],
    truthfulness_level: str | None,
) -> list[str]:
    failure_reasons: list[str] = []
    if spoken.get("truthfulness_check_required") is not True:
        failure_reasons.append("truthfulness_check_not_required")
    if spoken.get("coverage_check_required") is not False:
        failure_reasons.append("unexpected_coverage_check_required")
    if spoken.get("source_commitment_id") not in (None, ""):
        failure_reasons.append("unexpected_source_commitment_id")
    if not source_progress_event_ids:
        failure_reasons.append("missing_source_progress_event_ids")

    source_events = _string_list(spoken.get("source_events"))
    if source_progress_event_ids != source_events:
        failure_reasons.append("source_progress_event_ids_mismatch")

    found_source_ids = {str(event["event_id"]) for event in source_progress_events}
    for source_event_id in source_progress_event_ids:
        if source_event_id not in found_source_ids:
            failure_reasons.append("missing_source_progress_event")
            break

    for source_event in source_progress_events:
        event_name = str(source_event["event_name"])
        if event_name not in ALLOWED_PROGRESS_SOURCE_EVENTS:
            failure_reasons.append("unsupported_progress_source_event")
            continue
        allowed_source_modules = ALLOWED_SOURCE_MODULES_BY_EVENT.get(event_name, frozenset())
        if source_event.get("source_module") not in allowed_source_modules:
            failure_reasons.append("progress_source_module_mismatch")

    if truthfulness_level is None:
        failure_reasons.append("missing_truthfulness_level")
    elif truthfulness_level not in ALLOWED_TRUTHFULNESS_LEVELS:
        failure_reasons.append("unsupported_truthfulness_level")
    return _dedupe_preserving_order(failure_reasons)


def _validated_spoken_plan_event(
    journal: InMemoryEventJournal,
    spoken_plan_event: Mapping[str, Any],
) -> Mapping[str, Any]:
    spoken_event_id = _required_string(spoken_plan_event, "event_id")
    for event in journal.events():
        if event["event_id"] == spoken_event_id:
            if event["event_name"] != "SPOKEN_PLAN_EMITTED":
                raise CheckPolicyError("check source must be a SPOKEN_PLAN_EMITTED event")
            if event.get("source_module") != "composer":
                raise CheckPolicyError("SPOKEN_PLAN_EMITTED source_module must be composer")
            if event.get("output_mode") not in OUTPUT_MODES:
                raise CheckPolicyError("SpokenPlan output_mode must be real, mock, fallback, or degraded")
            _raise_if_spoken_plan_stale(journal, event)
            return event
    raise CheckPolicyError("spoken plan event does not exist in journal")


def _raise_if_spoken_plan_stale(
    journal: InMemoryEventJournal,
    spoken: Mapping[str, Any],
) -> None:
    task_id = _required_string(spoken, "task_id")
    spoken_plan_version = int(spoken["plan_version"])
    latest_plan_version = spoken_plan_version
    for event in journal.events():
        if event.get("task_id") != task_id:
            continue
        plan_version = event.get("plan_version")
        if isinstance(plan_version, int) and not isinstance(plan_version, bool):
            latest_plan_version = max(latest_plan_version, plan_version)
    if spoken_plan_version != latest_plan_version:
        raise CheckPolicyError("stale SpokenPlan cannot be checked after plan advance")


def _source_event_for_spoken_plan(
    journal: InMemoryEventJournal,
    spoken: Mapping[str, Any],
    *,
    expected_event_name: str,
) -> Mapping[str, Any] | None:
    source_event_ids = _string_list(spoken.get("source_events"))
    if len(source_event_ids) != 1:
        return None
    source_event = _event_by_id(journal, source_event_ids[0])
    if source_event is None or source_event.get("event_name") != expected_event_name:
        return None
    if int(source_event["event_seq"]) >= int(spoken["event_seq"]):
        return None
    allowed_source_modules = ALLOWED_SOURCE_MODULES_BY_EVENT.get(expected_event_name, frozenset())
    if source_event.get("source_module") not in allowed_source_modules:
        return None
    return source_event


def _source_progress_events_for_spoken_plan(
    journal: InMemoryEventJournal,
    spoken: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    spoken_event_seq = int(spoken["event_seq"])
    source_progress_event_ids = _string_list(spoken.get("source_progress_event_ids"))
    source_events: list[Mapping[str, Any]] = []
    for source_event_id in source_progress_event_ids:
        source_event = _event_by_id(journal, source_event_id)
        if source_event is not None and int(source_event["event_seq"]) < spoken_event_seq:
            source_events.append(source_event)
    return source_events


def _append_check_event(
    journal: InMemoryEventJournal,
    *,
    event_name: str,
    event_id: str,
    source_module: str,
    spoken: Mapping[str, Any],
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    check_result_ref: str,
    output_mode: str,
    **fields: Any,
) -> dict[str, Any]:
    return journal.append(
        event_name=event_name,
        event_id=event_id,
        source_module=source_module,
        caused_by_event_id=str(spoken["event_id"]),
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        trace_redaction_level="metadata_only",
        task_id=str(spoken["task_id"]),
        plan_version=int(spoken["plan_version"]),
        task_event_seq=_next_task_event_seq(journal, str(spoken["task_id"])),
        spoken_plan_id=str(spoken["spoken_plan_id"]),
        check_result_ref=check_result_ref,
        output_mode=output_mode,
        **fields,
    )


def _next_task_event_seq(journal: InMemoryEventJournal, task_id: str) -> int:
    latest_task_event_seq = 0
    for event in journal.events():
        if event.get("task_id") != task_id:
            continue
        task_event_seq = event.get("task_event_seq")
        if isinstance(task_event_seq, int) and not isinstance(task_event_seq, bool):
            latest_task_event_seq = max(latest_task_event_seq, task_event_seq)
    return latest_task_event_seq + 1


def _safe_source_commitment_id(spoken: Mapping[str, Any]) -> str:
    spoken_commitment_id = _optional_string(spoken.get("source_commitment_id"))
    if spoken_commitment_id is not None:
        return spoken_commitment_id
    return "missing_source_commitment_id"


def _event_by_id(journal: InMemoryEventJournal, event_id: str) -> Mapping[str, Any] | None:
    for event in journal.events():
        if event["event_id"] == event_id:
            return event
    return None


def _required_string(event: Mapping[str, Any], field: str) -> str:
    value = event.get(field)
    if not isinstance(value, str) or not value:
        raise CheckPolicyError(f"{field} is required")
    return value


def _optional_string(value: object) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, bytes) or not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value]


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
