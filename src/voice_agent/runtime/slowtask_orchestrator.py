from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.router.router import MVP1TaskFocusUpdateEmitter
from voice_agent.slowtask.mock_runtime import MockSlowTaskRunResult, MockSlowTaskRuntime


class MVP1SlowTaskHappyPathOrchestrator:
    def __init__(self, journal: InMemoryEventJournal) -> None:
        self._slowtask_runtime = MockSlowTaskRuntime(journal)
        self._task_focus_emitter = MVP1TaskFocusUpdateEmitter(journal)

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
        created_result = self._slowtask_runtime.create_from_router_spawn(
            router_decision_event=router_decision_event,
            task_id=task_id,
            initial_goal_ref=initial_goal_ref,
            event_id_prefix=event_id_prefix,
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            source_evidence_refs=source_evidence_refs,
        )

        active_focus_event = self._task_focus_emitter.emit_update(
            router_decision_event=router_decision_event,
            event_id=f"{event_id_prefix}_focus_active",
            created_monotonic_ms=created_monotonic_ms + 2,
            created_wall_clock_ms=created_wall_clock_ms + 2,
            active_task_id=task_id,
            foreground_mode="SLOWTASK_ACTIVE",
            default_patch_policy="ACTIVE_TASK_PATCH_ONLY",
        )

        planning_result = self._slowtask_runtime.run_planning_completed(
            task_id=task_id,
            plan_version=created_result.plan_version,
            caused_by_event_id=str(created_result.produced_events[0]["event_id"]),
            event_id_prefix=event_id_prefix,
            created_monotonic_ms=created_monotonic_ms + 3,
            created_wall_clock_ms=created_wall_clock_ms + 3,
            start_task_event_seq=3,
            evidence_refs=evidence_refs or source_evidence_refs,
            resolved_arguments_ref=resolved_arguments_ref,
            provenance_ref=provenance_ref,
            field_provenance_refs=field_provenance_refs,
            commitment_id=commitment_id,
            commitment_ref=commitment_ref,
        )

        cleanup_focus_event = self._task_focus_emitter.emit_update(
            router_decision_event=router_decision_event,
            event_id=f"{event_id_prefix}_focus_cleared",
            created_monotonic_ms=created_monotonic_ms + 11,
            created_wall_clock_ms=created_wall_clock_ms + 11,
            active_task_id=None,
            foreground_mode="IDLE",
            default_patch_policy="NO_ACTIVE_TASK",
        )

        return MockSlowTaskRunResult(
            task_id=task_id,
            plan_version=created_result.plan_version,
            produced_events=(
                *created_result.produced_events,
                active_focus_event,
                *planning_result.produced_events,
                cleanup_focus_event,
            ),
        )
