from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from voice_agent.composer.constants import (
    ALLOWED_PROGRESS_SOURCE_EVENTS,
    ALLOWED_SOURCE_MODULES_BY_EVENT,
    ALLOWED_TRUTHFULNESS_LEVELS,
)
from voice_agent.events.journal import InMemoryEventJournal


COMPOSER_SOURCE_MODULE = "composer"
SYMBOLIC_COMMITMENT_METADATA_FIELDS = (
    "immutable_fields",
    "must_say_fields",
    "forbidden_rewrite_fields",
)


class ComposerPolicyError(ValueError):
    pass


class MockThinkerAsComposer:
    """Deterministic MVP-2 Thinker-as-Composer.

    This runtime only records a SpokenPlan draft from already-journaled
    current-plan sources. It does not call a provider, run coverage/truthfulness
    checks, authorize tools, or start playback.
    """

    def __init__(self, journal: InMemoryEventJournal) -> None:
        self._journal = journal

    def emit_from_commitment(
        self,
        *,
        source_event: Mapping[str, Any],
        spoken_plan_id: str,
        event_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        text_ref: str,
        emotion: str,
        speaking_style: str,
        interruptible: bool,
        priority: str,
        expected_task_id: str | None = None,
        expected_plan_version: int | None = None,
        source_commitment_id: str | None = None,
    ) -> dict[str, Any]:
        source = self._validated_source_event(source_event)
        if source["event_name"] != "SEMANTIC_COMMITMENT_EMITTED":
            raise ComposerPolicyError("commitment-derived speech requires SEMANTIC_COMMITMENT_EMITTED")
        _require_allowed_source_module(source)
        binding = self._validated_current_plan_binding(
            source_events=[source],
            expected_task_id=expected_task_id,
            expected_plan_version=expected_plan_version,
        )
        commitment_id = _optional_non_empty_string(source_commitment_id)
        if commitment_id is None:
            commitment_id = _required_string(source, "commitment_id")
        if commitment_id != _required_string(source, "commitment_id"):
            raise ComposerPolicyError("source_commitment_id must match source commitment_id")

        symbolic_metadata = {
            field: _string_list_field(source, field)
            for field in SYMBOLIC_COMMITMENT_METADATA_FIELDS
            if field in source
        }
        return self._append_spoken_plan(
            event_id=event_id,
            spoken_plan_id=spoken_plan_id,
            caused_by_event_id=_required_string(source, "event_id"),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            text_ref=text_ref,
            emotion=emotion,
            speaking_style=speaking_style,
            interruptible=interruptible,
            priority=priority,
            source="semantic_commitment",
            task_id=binding["task_id"],
            plan_version=binding["plan_version"],
            task_event_seq=binding["next_task_event_seq"],
            source_events=[_required_string(source, "event_id")],
            source_progress_event_ids=[],
            coverage_check_required=True,
            truthfulness_check_required=False,
            source_commitment_id=commitment_id,
            **symbolic_metadata,
        )

    def emit_from_progress(
        self,
        *,
        source_events: Sequence[Mapping[str, Any]],
        spoken_plan_id: str,
        event_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        text_ref: str,
        emotion: str,
        speaking_style: str,
        interruptible: bool,
        priority: str,
        truthfulness_level: str = "STATE_GROUNDED",
        expected_task_id: str | None = None,
        expected_plan_version: int | None = None,
        source_progress_event_ids: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        if not source_events:
            raise ComposerPolicyError("progress-derived speech requires source events")
        validated_sources = [self._validated_source_event(source_event) for source_event in source_events]
        for source in validated_sources:
            if source["event_name"] not in ALLOWED_PROGRESS_SOURCE_EVENTS:
                raise ComposerPolicyError(f"unsupported progress source event: {source['event_name']}")
            _require_allowed_source_module(source)
        if truthfulness_level not in ALLOWED_TRUTHFULNESS_LEVELS:
            raise ComposerPolicyError("truthfulness_level must be STATE_GROUNDED or STYLE_ONLY_ACK")

        derived_source_ids = [_required_string(source, "event_id") for source in validated_sources]
        if source_progress_event_ids is None:
            progress_source_ids = derived_source_ids
        else:
            progress_source_ids = [str(source_event_id) for source_event_id in source_progress_event_ids]
        if not progress_source_ids:
            raise ComposerPolicyError("source_progress_event_ids are required for progress-derived speech")
        if progress_source_ids != derived_source_ids:
            raise ComposerPolicyError("source_progress_event_ids must match source progress events")

        binding = self._validated_current_plan_binding(
            source_events=validated_sources,
            expected_task_id=expected_task_id,
            expected_plan_version=expected_plan_version,
        )
        return self._append_spoken_plan(
            event_id=event_id,
            spoken_plan_id=spoken_plan_id,
            caused_by_event_id=derived_source_ids[-1],
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            text_ref=text_ref,
            emotion=emotion,
            speaking_style=speaking_style,
            interruptible=interruptible,
            priority=priority,
            source="grounded_progress",
            task_id=binding["task_id"],
            plan_version=binding["plan_version"],
            task_event_seq=binding["next_task_event_seq"],
            source_events=derived_source_ids,
            source_progress_event_ids=progress_source_ids,
            coverage_check_required=False,
            truthfulness_check_required=True,
            truthfulness_level=truthfulness_level,
        )

    def _append_spoken_plan(
        self,
        *,
        event_id: str,
        spoken_plan_id: str,
        caused_by_event_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        text_ref: str,
        emotion: str,
        speaking_style: str,
        interruptible: bool,
        priority: str,
        source: str,
        task_id: str,
        plan_version: int,
        task_event_seq: int,
        source_events: list[str],
        source_progress_event_ids: list[str],
        coverage_check_required: bool,
        truthfulness_check_required: bool,
        **fields: Any,
    ) -> dict[str, Any]:
        return self._journal.append(
            event_name="SPOKEN_PLAN_EMITTED",
            event_id=event_id,
            source_module=COMPOSER_SOURCE_MODULE,
            caused_by_event_id=caused_by_event_id,
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            trace_redaction_level="metadata_only",
            spoken_plan_id=spoken_plan_id,
            task_id=task_id,
            plan_version=plan_version,
            task_event_seq=task_event_seq,
            source_events=source_events,
            source_progress_event_ids=source_progress_event_ids,
            coverage_check_required=coverage_check_required,
            truthfulness_check_required=truthfulness_check_required,
            text_ref=text_ref,
            emotion=emotion,
            speaking_style=speaking_style,
            interruptible=interruptible,
            priority=priority,
            source=source,
            output_mode="mock",
            **fields,
        )

    def _validated_source_event(self, source_event: Mapping[str, Any]) -> Mapping[str, Any]:
        source_event_id = _required_string(source_event, "event_id")
        for journal_event in self._journal.events():
            if journal_event["event_id"] == source_event_id:
                return journal_event
        raise ComposerPolicyError("source event does not exist in journal")

    def _validated_current_plan_binding(
        self,
        *,
        source_events: Sequence[Mapping[str, Any]],
        expected_task_id: str | None,
        expected_plan_version: int | None,
    ) -> dict[str, Any]:
        task_id = _required_string(source_events[0], "task_id")
        plan_version = _required_int(source_events[0], "plan_version")
        latest_plan_version = plan_version
        latest_task_event_seq = _required_int(source_events[0], "task_event_seq")

        for source in source_events:
            if _required_string(source, "task_id") != task_id:
                raise ComposerPolicyError("all source events must share task_id")
            if _required_int(source, "plan_version") != plan_version:
                raise ComposerPolicyError("all source events must share plan_version")

        if expected_task_id is not None and expected_task_id != task_id:
            raise ComposerPolicyError("source task_id does not match expected task_id")
        if expected_plan_version is not None and expected_plan_version != plan_version:
            raise ComposerPolicyError("source plan_version does not match expected plan_version")

        for event in self._journal.events():
            if event.get("task_id") != task_id:
                continue
            if isinstance(event.get("plan_version"), int) and not isinstance(event.get("plan_version"), bool):
                latest_plan_version = max(latest_plan_version, int(event["plan_version"]))
            if isinstance(event.get("task_event_seq"), int) and not isinstance(event.get("task_event_seq"), bool):
                latest_task_event_seq = max(latest_task_event_seq, int(event["task_event_seq"]))

        if plan_version != latest_plan_version:
            raise ComposerPolicyError("stale plan source cannot emit a SpokenPlan")

        return {
            "task_id": task_id,
            "plan_version": plan_version,
            "next_task_event_seq": latest_task_event_seq + 1,
        }


def _required_string(event: Mapping[str, Any], field: str) -> str:
    value = event.get(field)
    if not isinstance(value, str) or not value:
        raise ComposerPolicyError(f"{field} is required")
    return value


def _optional_non_empty_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ComposerPolicyError("source_commitment_id is required")
    return value


def _require_allowed_source_module(event: Mapping[str, Any]) -> None:
    event_name = _required_string(event, "event_name")
    source_module = _required_string(event, "source_module")
    allowed_source_modules = ALLOWED_SOURCE_MODULES_BY_EVENT.get(event_name)
    if allowed_source_modules is None:
        raise ComposerPolicyError(f"{event_name} is not a supported Composer source event")
    if source_module not in allowed_source_modules:
        allowed = ", ".join(sorted(allowed_source_modules))
        raise ComposerPolicyError(f"{event_name} source_module must be {allowed}")


def _string_list_field(event: Mapping[str, Any], field: str) -> list[str]:
    value = event.get(field)
    if value is None:
        return []
    if isinstance(value, str):
        if not value:
            raise ComposerPolicyError(f"{field} must not contain empty field paths")
        return [value]
    if isinstance(value, bytes) or not isinstance(value, Sequence):
        raise ComposerPolicyError(f"{field} must be a string or list of strings")
    values = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ComposerPolicyError(f"{field} must contain only non-empty string field paths")
        values.append(item)
    return values


def _required_int(event: Mapping[str, Any], field: str) -> int:
    value = event.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ComposerPolicyError(f"{field} must be an integer")
    return value
