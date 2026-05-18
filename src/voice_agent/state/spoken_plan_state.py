from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


class SpokenPlanStateError(ValueError):
    pass


@dataclass(frozen=True)
class SpokenPlanRecord:
    event_id: str
    spoken_plan_id: str
    task_id: str
    plan_version: int
    task_event_seq: int
    source_events: tuple[str, ...]
    source_commitment_id: str | None
    source_progress_event_ids: tuple[str, ...]
    coverage_check_required: bool
    truthfulness_check_required: bool
    text_ref: str
    emotion: str
    speaking_style: str
    interruptible: bool
    priority: str
    source: str
    output_mode: str
    truthfulness_level: str | None = None
    immutable_fields: tuple[str, ...] = ()
    must_say_fields: tuple[str, ...] = ()
    forbidden_rewrite_fields: tuple[str, ...] = ()


@dataclass
class SpokenPlanState:
    spoken_plans: dict[str, SpokenPlanRecord] = field(default_factory=dict)
    last_spoken_plan_event_id: str | None = None

    def reduce_event(self, event: Mapping[str, Any]) -> bool:
        if event["event_name"] != "SPOKEN_PLAN_EMITTED":
            return False

        spoken_plan_id = str(event["spoken_plan_id"])
        if spoken_plan_id in self.spoken_plans:
            raise SpokenPlanStateError(f"Duplicate spoken_plan_id: {spoken_plan_id}")

        self.spoken_plans[spoken_plan_id] = SpokenPlanRecord(
            event_id=str(event["event_id"]),
            spoken_plan_id=spoken_plan_id,
            task_id=str(event["task_id"]),
            plan_version=_int_field(event, "plan_version"),
            task_event_seq=_int_field(event, "task_event_seq"),
            source_events=_string_tuple(event.get("source_events", ())),
            source_commitment_id=_optional_str(event.get("source_commitment_id")),
            source_progress_event_ids=_string_tuple(event.get("source_progress_event_ids", ())),
            coverage_check_required=bool(event["coverage_check_required"]),
            truthfulness_check_required=bool(event["truthfulness_check_required"]),
            text_ref=str(event["text_ref"]),
            emotion=str(event["emotion"]),
            speaking_style=str(event["speaking_style"]),
            interruptible=bool(event["interruptible"]),
            priority=str(event["priority"]),
            source=str(event["source"]),
            output_mode=str(event["output_mode"]),
            truthfulness_level=_optional_str(event.get("truthfulness_level")),
            immutable_fields=_string_tuple(event.get("immutable_fields", ())),
            must_say_fields=_string_tuple(event.get("must_say_fields", ())),
            forbidden_rewrite_fields=_string_tuple(event.get("forbidden_rewrite_fields", ())),
        )
        self.last_spoken_plan_event_id = str(event["event_id"])
        return True

    def to_digest_dict(self) -> dict[str, Any]:
        return {
            "spoken_plans": {
                spoken_plan_id: asdict(self.spoken_plans[spoken_plan_id])
                for spoken_plan_id in sorted(self.spoken_plans)
            },
            "last_spoken_plan_event_id": self.last_spoken_plan_event_id,
        }


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _int_field(event: Mapping[str, Any], field: str) -> int:
    value = event[field]
    if not isinstance(value, int) or isinstance(value, bool):
        raise SpokenPlanStateError(f"{field} must be an integer")
    return value


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        return (str(value),)
    if not isinstance(value, (list, tuple)):
        raise SpokenPlanStateError("expected a list of string refs")
    return tuple(str(item) for item in value)
