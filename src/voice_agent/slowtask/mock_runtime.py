from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from voice_agent.events.journal import InMemoryEventJournal


MOCK_SLOWTASK_SOURCE_MODULE = "slowtask_runtime"
INITIAL_PLAN_VERSION = 1
MATERIAL_PATCH_CANDIDATES = {
    "slot_update_candidate": ("slot_update", "mock_slot_update_candidate"),
    "constraint_update_candidate": ("constraint_update", "mock_constraint_update_candidate"),
    "goal_rewrite_candidate": ("goal_rewrite", "mock_goal_rewrite_candidate"),
}
NON_MATERIAL_PATCH_CANDIDATES = {
    "feedback_candidate": ("feedback", "mock_feedback_candidate"),
    "irrelevant_candidate": ("irrelevant", "mock_irrelevant_candidate"),
}
CONTROL_PATCH_CANDIDATES = frozenset(
    {
        "confirmation_candidate",
        "cancel_candidate",
        "switch_task_candidate",
    }
)


@dataclass(frozen=True)
class MockSlowTaskRunResult:
    task_id: str
    plan_version: int
    produced_events: tuple[dict[str, Any], ...]


class MockSlowTaskRuntime:
    """Minimal MVP-1 Slice 4 mock lifecycle.

    The runtime only records deterministic happy-path lifecycle events. It does
    not call models, tools, Composer, or external systems.
    """

    def __init__(self, journal: InMemoryEventJournal) -> None:
        self._journal = journal

    def run_spawn_planning_completed(
        self,
        *,
        router_decision_event: Mapping[str, Any],
        task_id: str,
        initial_goal_ref: str,
        commitment_id: str,
        event_id_prefix: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        source_evidence_refs: Sequence[str] = (),
        evidence_refs: Sequence[str] = (),
        resolved_arguments_ref: str | None = None,
        provenance_ref: str | None = None,
        field_provenance_refs: Sequence[str] = (),
        commitment_ref: str | None = None,
    ) -> MockSlowTaskRunResult:
        created_result = self.create_from_router_spawn(
            router_decision_event=router_decision_event,
            task_id=task_id,
            initial_goal_ref=initial_goal_ref,
            event_id_prefix=event_id_prefix,
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            source_evidence_refs=source_evidence_refs,
        )
        planning_result = self.run_planning_completed(
            task_id=task_id,
            plan_version=created_result.plan_version,
            caused_by_event_id=str(created_result.produced_events[0]["event_id"]),
            event_id_prefix=event_id_prefix,
            created_monotonic_ms=created_monotonic_ms + 2,
            created_wall_clock_ms=created_wall_clock_ms + 2,
            start_task_event_seq=3,
            evidence_refs=evidence_refs or source_evidence_refs,
            resolved_arguments_ref=resolved_arguments_ref,
            provenance_ref=provenance_ref,
            field_provenance_refs=field_provenance_refs,
            commitment_id=commitment_id,
            commitment_ref=commitment_ref,
        )

        return MockSlowTaskRunResult(
            task_id=task_id,
            plan_version=created_result.plan_version,
            produced_events=(*created_result.produced_events, *planning_result.produced_events),
        )

    def create_from_router_spawn(
        self,
        *,
        router_decision_event: Mapping[str, Any],
        task_id: str,
        initial_goal_ref: str,
        event_id_prefix: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        source_evidence_refs: Sequence[str] = (),
    ) -> MockSlowTaskRunResult:
        _validate_spawn_router_decision(router_decision_event)
        if not task_id:
            raise ValueError("task_id is required")
        if not event_id_prefix:
            raise ValueError("event_id_prefix is required")

        source_refs = tuple(str(ref) for ref in source_evidence_refs)
        plan_version = INITIAL_PLAN_VERSION
        produced_events: list[dict[str, Any]] = []

        created = self._append_slowtask_event(
            event_name="SLOWTASK_CREATED",
            event_id=f"{event_id_prefix}_slowtask_created",
            caused_by_event_id=str(router_decision_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            task_id=task_id,
            plan_version=plan_version,
            task_event_seq=1,
            initial_goal_ref=initial_goal_ref,
            source_evidence_refs=list(source_refs),
        )
        produced_events.append(created)

        created_state = self._append_slowtask_event(
            event_name="SLOWTASK_STATE_CHANGED",
            event_id=f"{event_id_prefix}_state_created",
            caused_by_event_id=str(created["event_id"]),
            created_monotonic_ms=created_monotonic_ms + 1,
            created_wall_clock_ms=created_wall_clock_ms + 1,
            task_id=task_id,
            plan_version=plan_version,
            task_event_seq=2,
            from_state="CREATED",
            to_state="CREATED",
            reason="created_snapshot",
        )
        produced_events.append(created_state)

        return MockSlowTaskRunResult(
            task_id=task_id,
            plan_version=plan_version,
            produced_events=tuple(produced_events),
        )

    def run_planning_completed(
        self,
        *,
        task_id: str,
        plan_version: int,
        caused_by_event_id: str,
        event_id_prefix: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        start_task_event_seq: int,
        commitment_id: str,
        evidence_refs: Sequence[str] = (),
        resolved_arguments_ref: str | None = None,
        provenance_ref: str | None = None,
        field_provenance_refs: Sequence[str] = (),
        commitment_ref: str | None = None,
    ) -> MockSlowTaskRunResult:
        produced_events: list[dict[str, Any]] = []
        reviewed_refs = tuple(str(ref) for ref in evidence_refs)

        planning_started = self._append_slowtask_event(
            event_name="PLANNING_STARTED",
            event_id=f"{event_id_prefix}_planning_started",
            caused_by_event_id=caused_by_event_id,
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            task_id=task_id,
            plan_version=plan_version,
            task_event_seq=start_task_event_seq,
            planning_reason="initial_goal_accepted",
        )
        produced_events.append(planning_started)

        planning_state = self._append_slowtask_event(
            event_name="SLOWTASK_STATE_CHANGED",
            event_id=f"{event_id_prefix}_state_planning",
            caused_by_event_id=str(planning_started["event_id"]),
            created_monotonic_ms=created_monotonic_ms + 1,
            created_wall_clock_ms=created_wall_clock_ms + 1,
            task_id=task_id,
            plan_version=plan_version,
            task_event_seq=start_task_event_seq + 1,
            from_state="CREATED",
            to_state="PLANNING",
            reason="initial_planning_started",
        )
        produced_events.append(planning_state)

        evidence_reviewed = self._append_slowtask_event(
            event_name="EVIDENCE_REVIEWED",
            event_id=f"{event_id_prefix}_evidence_reviewed",
            caused_by_event_id=str(planning_state["event_id"]),
            created_monotonic_ms=created_monotonic_ms + 2,
            created_wall_clock_ms=created_wall_clock_ms + 2,
            task_id=task_id,
            plan_version=plan_version,
            task_event_seq=start_task_event_seq + 2,
            evidence_refs=list(reviewed_refs),
            review_result="sufficient",
        )
        produced_events.append(evidence_reviewed)

        previous_event_id = str(evidence_reviewed["event_id"])
        next_task_event_seq = start_task_event_seq + 3
        next_time_offset = 3
        if resolved_arguments_ref is not None and provenance_ref is not None:
            arguments_resolved = self._append_slowtask_event(
                event_name="ARGUMENTS_RESOLVED",
                event_id=f"{event_id_prefix}_arguments_resolved",
                caused_by_event_id=previous_event_id,
                created_monotonic_ms=created_monotonic_ms + next_time_offset,
                created_wall_clock_ms=created_wall_clock_ms + next_time_offset,
                task_id=task_id,
                plan_version=plan_version,
                task_event_seq=next_task_event_seq,
                resolved_arguments_ref=resolved_arguments_ref,
                provenance_ref=provenance_ref,
            )
            produced_events.append(arguments_resolved)
            previous_event_id = str(arguments_resolved["event_id"])
            next_task_event_seq += 1
            next_time_offset += 1

            provenance = self._append_slowtask_event(
                event_name="ARGUMENT_RESOLUTION_PROVENANCE",
                event_id=f"{event_id_prefix}_argument_provenance",
                caused_by_event_id=previous_event_id,
                created_monotonic_ms=created_monotonic_ms + next_time_offset,
                created_wall_clock_ms=created_wall_clock_ms + next_time_offset,
                task_id=task_id,
                plan_version=plan_version,
                task_event_seq=next_task_event_seq,
                field_provenance_refs=list(str(ref) for ref in field_provenance_refs),
            )
            produced_events.append(provenance)
            previous_event_id = str(provenance["event_id"])
            next_task_event_seq += 1
            next_time_offset += 1

        finalizing = self._append_slowtask_event(
            event_name="FINALIZING",
            event_id=f"{event_id_prefix}_finalizing",
            caused_by_event_id=previous_event_id,
            created_monotonic_ms=created_monotonic_ms + next_time_offset,
            created_wall_clock_ms=created_wall_clock_ms + next_time_offset,
            task_id=task_id,
            plan_version=plan_version,
            task_event_seq=next_task_event_seq,
            source_events=[previous_event_id],
        )
        produced_events.append(finalizing)
        next_task_event_seq += 1
        next_time_offset += 1

        commitment_fields: dict[str, Any] = {}
        if commitment_ref is not None:
            commitment_fields["commitment_ref"] = commitment_ref
        commitment = self._append_slowtask_event(
            event_name="SEMANTIC_COMMITMENT_EMITTED",
            event_id=f"{event_id_prefix}_semantic_commitment",
            caused_by_event_id=str(finalizing["event_id"]),
            created_monotonic_ms=created_monotonic_ms + next_time_offset,
            created_wall_clock_ms=created_wall_clock_ms + next_time_offset,
            task_id=task_id,
            plan_version=plan_version,
            task_event_seq=next_task_event_seq,
            commitment_id=commitment_id,
            source_events=[str(finalizing["event_id"])],
            **commitment_fields,
        )
        produced_events.append(commitment)
        next_task_event_seq += 1
        next_time_offset += 1

        completed_state = self._append_slowtask_event(
            event_name="SLOWTASK_STATE_CHANGED",
            event_id=f"{event_id_prefix}_state_completed",
            caused_by_event_id=str(commitment["event_id"]),
            created_monotonic_ms=created_monotonic_ms + next_time_offset,
            created_wall_clock_ms=created_wall_clock_ms + next_time_offset,
            task_id=task_id,
            plan_version=plan_version,
            task_event_seq=next_task_event_seq,
            from_state="PLANNING",
            to_state="COMPLETED",
            reason="synthetic_commitment_complete",
        )
        produced_events.append(completed_state)

        return MockSlowTaskRunResult(
            task_id=task_id,
            plan_version=plan_version,
            produced_events=tuple(produced_events),
        )

    def interpret_user_patch(
        self,
        *,
        user_patch_event: Mapping[str, Any],
        event_id_prefix: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        current_lifecycle_state: str = "PLANNING",
        supersedes_event_id: str | None = None,
    ) -> MockSlowTaskRunResult:
        _validate_user_patch_received_event(user_patch_event)
        if not event_id_prefix:
            raise ValueError("event_id_prefix is required")

        task_id = str(user_patch_event["task_id"])
        patch_id = str(user_patch_event["patch_id"])
        observed_plan_version = _int_field(user_patch_event, "observed_plan_version")
        current_plan_version = _int_field(user_patch_event, "plan_version")
        next_task_event_seq = _int_field(user_patch_event, "task_event_seq") + 1
        interpretation_type, materially_changes_task, interpretation_reason = (
            _mock_interpretation_from_user_patch(user_patch_event)
        )
        source_evidence_refs = _source_evidence_refs_from_user_patch(user_patch_event)
        produced_events: list[dict[str, Any]] = []

        interpreted = self._append_slowtask_event(
            event_name="USER_PATCH_INTERPRETED",
            event_id=f"{event_id_prefix}_user_patch_interpreted",
            caused_by_event_id=str(user_patch_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            patch_id=patch_id,
            task_id=task_id,
            plan_version=current_plan_version,
            task_event_seq=next_task_event_seq,
            observed_plan_version=observed_plan_version,
            interpreted_against_plan_version=observed_plan_version,
            interpretation_type=interpretation_type,
            materially_changes_task=materially_changes_task,
            interpretation_reason=interpretation_reason,
            source_evidence_refs=list(source_evidence_refs),
        )
        produced_events.append(interpreted)

        if not materially_changes_task:
            return MockSlowTaskRunResult(
                task_id=task_id,
                plan_version=current_plan_version,
                produced_events=tuple(produced_events),
            )

        planning_reason = f"material_user_patch:{interpretation_type}"
        advance_task_event_seq = next_task_event_seq + 1
        time_offset = 1
        advance_fields: dict[str, Any] = {}
        if supersedes_event_id is not None:
            advance_fields["supersedes_event_id"] = supersedes_event_id
        advanced = self._append_slowtask_event(
            event_name="PLAN_VERSION_ADVANCED",
            event_id=f"{event_id_prefix}_plan_version_advanced",
            caused_by_event_id=str(interpreted["event_id"]),
            created_monotonic_ms=created_monotonic_ms + time_offset,
            created_wall_clock_ms=created_wall_clock_ms + time_offset,
            task_id=task_id,
            plan_version=current_plan_version + 1,
            task_event_seq=advance_task_event_seq,
            from_plan_version=current_plan_version,
            to_plan_version=current_plan_version + 1,
            planning_reason=planning_reason,
            caused_by_user_patch_event_id=str(user_patch_event["event_id"]),
            **advance_fields,
        )
        produced_events.append(advanced)

        restarted = self._append_slowtask_event(
            event_name="PLANNING_RESTARTED",
            event_id=f"{event_id_prefix}_planning_restarted",
            caused_by_event_id=str(advanced["event_id"]),
            created_monotonic_ms=created_monotonic_ms + time_offset + 1,
            created_wall_clock_ms=created_wall_clock_ms + time_offset + 1,
            task_id=task_id,
            plan_version=current_plan_version + 1,
            task_event_seq=advance_task_event_seq + 1,
            restart_reason=planning_reason,
        )
        produced_events.append(restarted)

        replanned = self._append_slowtask_event(
            event_name="TASK_REPLANNED",
            event_id=f"{event_id_prefix}_task_replanned",
            caused_by_event_id=str(advanced["event_id"]),
            created_monotonic_ms=created_monotonic_ms + time_offset + 2,
            created_wall_clock_ms=created_wall_clock_ms + time_offset + 2,
            task_id=task_id,
            plan_version=current_plan_version + 1,
            task_event_seq=advance_task_event_seq + 2,
            planning_reason=planning_reason,
            superseded_plan_version=current_plan_version,
        )
        produced_events.append(replanned)

        planning_state = self._append_slowtask_event(
            event_name="SLOWTASK_STATE_CHANGED",
            event_id=f"{event_id_prefix}_state_planning",
            caused_by_event_id=str(replanned["event_id"]),
            created_monotonic_ms=created_monotonic_ms + time_offset + 3,
            created_wall_clock_ms=created_wall_clock_ms + time_offset + 3,
            task_id=task_id,
            plan_version=current_plan_version + 1,
            task_event_seq=advance_task_event_seq + 3,
            from_state=current_lifecycle_state,
            to_state="PLANNING",
            reason="material_user_patch_replanning",
        )
        produced_events.append(planning_state)

        return MockSlowTaskRunResult(
            task_id=task_id,
            plan_version=current_plan_version + 1,
            produced_events=tuple(produced_events),
        )

    def _append_slowtask_event(
        self,
        *,
        event_name: str,
        event_id: str,
        caused_by_event_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        **fields: Any,
    ) -> dict[str, Any]:
        return self._journal.append(
            event_name=event_name,
            event_id=event_id,
            source_module=MOCK_SLOWTASK_SOURCE_MODULE,
            caused_by_event_id=caused_by_event_id,
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            trace_redaction_level="metadata_only",
            **fields,
        )


def _validate_spawn_router_decision(event: Mapping[str, Any]) -> None:
    if event.get("event_name") != "ROUTER_DECISION_EMITTED":
        raise ValueError("MockSlowTaskRuntime requires a ROUTER_DECISION_EMITTED event")
    if event.get("router_decision") != "SPAWN_SLOW_TASK":
        raise ValueError("MockSlowTaskRuntime requires router_decision=SPAWN_SLOW_TASK")


def _validate_user_patch_received_event(event: Mapping[str, Any]) -> None:
    if event.get("event_name") != "USER_PATCH_RECEIVED":
        raise ValueError("MockSlowTaskRuntime requires a USER_PATCH_RECEIVED event")
    for field in ("event_id", "patch_id", "task_id", "plan_version", "task_event_seq", "observed_plan_version"):
        if field not in event:
            raise ValueError(f"USER_PATCH_RECEIVED missing required field: {field}")


def _mock_interpretation_from_user_patch(event: Mapping[str, Any]) -> tuple[str, bool, str]:
    candidate_types = _string_tuple(event.get("candidate_patch_types", ()))
    control_candidates = CONTROL_PATCH_CANDIDATES.intersection(candidate_types)
    if control_candidates:
        raise ValueError(
            "Slice 6 mock runtime does not handle control UserPatch candidate; "
            f"defer to ADR-016 confirmation/cancel slice: {sorted(control_candidates)}"
        )
    for candidate_type, (interpretation_type, reason) in MATERIAL_PATCH_CANDIDATES.items():
        if candidate_type in candidate_types:
            return interpretation_type, True, reason
    for candidate_type, (interpretation_type, reason) in NON_MATERIAL_PATCH_CANDIDATES.items():
        if candidate_type in candidate_types:
            return interpretation_type, False, reason
    return "irrelevant", False, "mock_no_material_candidate"


def _source_evidence_refs_from_user_patch(event: Mapping[str, Any]) -> tuple[str, ...]:
    refs: list[str] = []
    for field in ("evidence_ref", "authoritative_evidence_refs", "non_authoritative_hypothesis_refs"):
        refs.extend(_string_tuple(event.get(field)))
    return tuple(dict.fromkeys(ref for ref in refs if ref))


def _int_field(event: Mapping[str, Any], field: str) -> int:
    value = event[field]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    return value


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        return (str(value),)
    if not isinstance(value, Sequence):
        raise ValueError("expected a sequence of strings")
    return tuple(str(item) for item in value)
