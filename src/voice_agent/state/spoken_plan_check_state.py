from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


CHECK_EVENT_NAMES = frozenset(
    {
        "COMMITMENT_COVERAGE_CHECK_PASSED",
        "COMMITMENT_COVERAGE_CHECK_FAILED",
        "PROGRESS_TRUTHFULNESS_CHECK_PASSED",
        "PROGRESS_TRUTHFULNESS_CHECK_FAILED",
    }
)
PASSED_CHECK_EVENT_NAMES = frozenset(
    {
        "COMMITMENT_COVERAGE_CHECK_PASSED",
        "PROGRESS_TRUTHFULNESS_CHECK_PASSED",
    }
)


@dataclass(frozen=True)
class SpokenPlanCheckRecord:
    event_id: str
    event_name: str
    status: str
    spoken_plan_id: str
    output_mode: str
    check_result_ref: str
    source_commitment_id: str | None = None
    source_progress_event_ids: tuple[str, ...] = ()
    truthfulness_level: str | None = None
    checked_fields: tuple[str, ...] = ()
    failure_reasons: tuple[str, ...] = ()


@dataclass
class SpokenPlanCheckState:
    passed_checks: dict[str, SpokenPlanCheckRecord] = field(default_factory=dict)
    failed_checks: dict[str, SpokenPlanCheckRecord] = field(default_factory=dict)
    checks_by_spoken_plan_id: dict[str, tuple[str, ...]] = field(default_factory=dict)
    last_check_event_id: str | None = None

    def reduce_event(self, event: Mapping[str, Any]) -> bool:
        event_name = str(event["event_name"])
        if event_name not in CHECK_EVENT_NAMES:
            return False

        record = SpokenPlanCheckRecord(
            event_id=str(event["event_id"]),
            event_name=event_name,
            status="passed" if event_name in PASSED_CHECK_EVENT_NAMES else "failed",
            spoken_plan_id=str(event["spoken_plan_id"]),
            output_mode=str(event["output_mode"]),
            check_result_ref=str(event["check_result_ref"]),
            source_commitment_id=_optional_str(event.get("source_commitment_id")),
            source_progress_event_ids=_string_tuple(event.get("source_progress_event_ids", ())),
            truthfulness_level=_optional_str(event.get("truthfulness_level")),
            checked_fields=_string_tuple(event.get("checked_fields", ())),
            failure_reasons=_string_tuple(event.get("failure_reasons", ())),
        )
        if record.status == "passed":
            self.passed_checks[record.event_id] = record
        else:
            self.failed_checks[record.event_id] = record

        prior_checks = self.checks_by_spoken_plan_id.get(record.spoken_plan_id, ())
        self.checks_by_spoken_plan_id[record.spoken_plan_id] = (*prior_checks, record.event_id)
        self.last_check_event_id = record.event_id
        return True

    def to_digest_dict(self) -> dict[str, Any]:
        return {
            "passed_checks": {
                event_id: asdict(self.passed_checks[event_id])
                for event_id in sorted(self.passed_checks)
            },
            "failed_checks": {
                event_id: asdict(self.failed_checks[event_id])
                for event_id in sorted(self.failed_checks)
            },
            "checks_by_spoken_plan_id": {
                spoken_plan_id: list(self.checks_by_spoken_plan_id[spoken_plan_id])
                for spoken_plan_id in sorted(self.checks_by_spoken_plan_id)
            },
            "last_check_event_id": self.last_check_event_id,
        }


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        return (str(value),)
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value)
