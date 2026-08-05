from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field, replace
import time
from typing import Any

from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.runtime.fast_foreground_gate import (
    CandidatePolicyDecision,
    FastForegroundGateContext,
    FastForegroundGateResult,
    commit_deferred_foreground_template,
    run_fast_foreground_gate,
    run_missing_fast_foreground_gate,
)
from voice_agent.runtime.foreground_template_catalog import get_foreground_template
from voice_agent.runtime.mvp5_live_approval import is_safe_mvp5_live_ref
from voice_agent.router.router import (
    MVP1_ROUTER_DECISIONS,
    MVP1Router,
    RouterContext,
    TaskFocusSnapshot,
)
from voice_agent.slowtask.mock_runtime import MockSlowTaskRuntime
from voice_agent.state.interaction_state import InteractionState
from voice_agent.state.slowtask_state import (
    SLOWTASK_EVENT_NAMES,
    SlowTaskRecord,
    SlowTaskState,
)
from voice_agent.user_patch.evidence_pack import UserPatchEvidencePackRuntime


class MVP5LiveRouterRunnerError(ValueError):
    """Raised when MVP-5 live Router result handling fails closed."""


@dataclass(frozen=True)
class MVP5ActiveSlowTaskContext:
    task_id: str
    current_plan_version: int
    current_task_event_seq: int
    lifecycle_phase: str = "PLANNING"
    terminal_status: str | None = None
    pending_confirmation_id: str | None = None
    pending_confirmation_scope: str | None = None


@dataclass(frozen=True)
class MVP5LiveRouterConfig:
    run_id: str = "mvp5-live-router-provider-free"
    expected_route: str | None = None
    active_task_context: MVP5ActiveSlowTaskContext | None = None
    fast_foreground_gate_context: FastForegroundGateContext | None = None


@dataclass(frozen=True)
class MVP5LiveRouteResult:
    run_id: str
    status: str
    route_result_kind: str
    router_decision: str | None
    events: tuple[dict[str, Any], ...] = ()
    expected_route: str | None = None
    expected_route_matched: bool | None = None
    turn_id: str | None = None
    utterance_id: str | None = None
    audio_span_id: str | None = None
    asr_event_id: str | None = None
    thinker_event_id: str | None = None
    fast_interaction_event_id: str | None = None
    foreground_candidate_event_id: str | None = None
    router_event_id: str | None = None
    task_focus_state_event_id: str | None = None
    foreground_gate_event_id: str | None = None
    foreground_output_event_id: str | None = None
    foreground_discard_event_id: str | None = None
    foreground_output_basis: str | None = None
    foreground_candidate_ref: str | None = None
    foreground_output_ref: str | None = None
    foreground_fallback_policy_ref: str | None = None
    foreground_fallback_reason: str | None = None
    foreground_gate_decision: str | None = None
    foreground_gate_failure_reason: str | None = None
    response_text_ref: str | None = None
    result_summary_ref: str | None = None
    evidence_ref_policy: str = "preserve_both_refs"
    task_id: str | None = None
    patch_id: str | None = None
    router_ms: int | None = None
    foreground_gate_ms: int | None = None
    foreground_output_finalize_ms: int | None = None
    slowtask_event_ids_by_name: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    user_patch_event_ids: tuple[str, ...] = ()
    provider_call_used: bool = False
    fake_transport_used: bool = False
    warnings: tuple[str, ...] = ()

    def to_metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "run_id": self.run_id,
            "status": self.status,
            "route_result_kind": self.route_result_kind,
            "router_decision": self.router_decision,
            "actual_route": self.router_decision,
            "expected_route": self.expected_route,
            "expected_route_matched": self.expected_route_matched,
            "event_names": [str(event["event_name"]) for event in self.events],
            "event_ids": [str(event["event_id"]) for event in self.events],
            "slowtask_event_ids_by_name": {
                str(name): list(event_ids)
                for name, event_ids in self.slowtask_event_ids_by_name.items()
            },
            "user_patch_event_ids": list(self.user_patch_event_ids),
            "provider_call_used": self.provider_call_used,
            "fake_transport_used": self.fake_transport_used,
            "raw_audio_included": False,
            "raw_transcript_included": False,
            "raw_provider_body_included": False,
            "prompt_dump_included": False,
            "secret_included": False,
            "local_wav_path_included": False,
            "replay_reruns_provider": False,
            "real_tts_used": False,
            "voice_output": "none",
            "evidence_ref_policy": self.evidence_ref_policy,
        }
        optional_fields = {
            "turn_id": self.turn_id,
            "utterance_id": self.utterance_id,
            "audio_span_id": self.audio_span_id,
            "asr_event_id": self.asr_event_id,
            "thinker_event_id": self.thinker_event_id,
            "fast_interaction_event_id": self.fast_interaction_event_id,
            "foreground_candidate_event_id": self.foreground_candidate_event_id,
            "router_event_id": self.router_event_id,
            "task_focus_state_event_id": self.task_focus_state_event_id,
            "foreground_gate_event_id": self.foreground_gate_event_id,
            "foreground_output_event_id": self.foreground_output_event_id,
            "foreground_discard_event_id": self.foreground_discard_event_id,
            "foreground_output_basis": self.foreground_output_basis,
            "foreground_candidate_ref": self.foreground_candidate_ref,
            "foreground_output_ref": self.foreground_output_ref,
            "foreground_fallback_policy_ref": self.foreground_fallback_policy_ref,
            "foreground_fallback_reason": self.foreground_fallback_reason,
            "foreground_gate_decision": self.foreground_gate_decision,
            "foreground_gate_failure_reason": self.foreground_gate_failure_reason,
            "response_text_ref": self.response_text_ref,
            "result_summary_ref": self.result_summary_ref,
            "task_id": self.task_id,
            "patch_id": self.patch_id,
            "router_ms": self.router_ms,
            "foreground_gate_ms": self.foreground_gate_ms,
            "foreground_output_finalize_ms": self.foreground_output_finalize_ms,
        }
        metadata.update({key: value for key, value in optional_fields.items() if value is not None})
        if self.warnings:
            metadata["warnings"] = list(self.warnings)
        _validate_summary_metadata(metadata)
        return metadata


def run_mvp5_live_router_runner(
    evidence_result: Any,
    *,
    config: MVP5LiveRouterConfig | None = None,
    journal: InMemoryEventJournal | None = None,
) -> MVP5LiveRouteResult:
    config = config or MVP5LiveRouterConfig()
    run_id = _require_safe_token(config.run_id, "run_id")
    expected_route = _normalize_expected_route(config.expected_route)
    slug = _slug(run_id)

    evidence_events = tuple(deepcopy(tuple(getattr(evidence_result, "events", ()))))
    if not evidence_events:
        return _blocked_result(
            run_id=run_id,
            status="blocked_missing_evidence_events",
            warning="Goal 2 evidence events are required before Router can run",
            provider_call_used=bool(getattr(evidence_result, "provider_call_used", False)),
            fake_transport_used=bool(getattr(evidence_result, "fake_transport_used", False)),
        )

    turn_event = _single_event(evidence_events, "TURN_INGRESS_COMMITTED")
    asr_event = _optional_event_by_id_or_name(
        evidence_events,
        event_id=getattr(evidence_result, "asr_event_id", None),
        event_names=("ASR_TRANSCRIPT_OUTPUT_EMITTED", "MOCK_ASR_FRAME_EMITTED"),
    )
    routing_asr_event = (
        None
        if bool(getattr(evidence_result, "asr_observation_enabled", False))
        else asr_event
    )
    fast_interaction_event = _optional_event_by_id_or_name(
        evidence_events,
        event_id=getattr(evidence_result, "fast_interaction_event_id", None),
        event_names=("FAST_INTERACTION_OUTPUT_EMITTED",),
    )
    foreground_candidate_event = _optional_event_by_id_or_name(
        evidence_events,
        event_id=getattr(evidence_result, "foreground_candidate_event_id", None),
        event_names=("FOREGROUND_REPLY_CANDIDATE_EMITTED",),
    )
    thinker_event = _optional_event_by_id_or_name(
        evidence_events,
        event_id=getattr(evidence_result, "thinker_event_id", None),
        event_names=("THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED", "MOCK_THINKER_FRAME_EMITTED"),
    )
    if thinker_event is None and fast_interaction_event is None:
        raise MVP5LiveRouterRunnerError(
            "expected Thinker or Fast Interaction evidence before Router can run"
        )
    if thinker_event is not None and routing_asr_event is None:
        raise MVP5LiveRouterRunnerError("expected ASR evidence with Thinker evidence")
    # Observation-only ASR stays in the journal but is not Router/SlowTask evidence.
    asr_event = routing_asr_event

    if journal is None:
        journal = _journal_from_recorded_events(evidence_events)
    else:
        journal_events = tuple(journal.events())
        if journal_events[: len(evidence_events)] != evidence_events:
            raise MVP5LiveRouterRunnerError(
                "in-place journal must preserve the supplied evidence snapshot prefix"
            )
    authoritative_active_task, _ = (
        _active_task_authority_from_journal(
            events=tuple(journal.events()),
            fallback=config.active_task_context,
            target_task_id=(
                config.active_task_context.task_id
                if config.active_task_context is not None
                else None
            ),
        )
    )
    if config.active_task_context is not None and authoritative_active_task is None:
        return MVP5LiveRouteResult(
            run_id=run_id,
            status="blocked_missing_canonical_active_task_authority",
            route_result_kind="degraded",
            router_decision=None,
            expected_route=expected_route,
            expected_route_matched=False if expected_route is not None else None,
            events=tuple(journal.events()),
            turn_id=str(turn_event["turn_id"]),
            utterance_id=str(turn_event["utterance_id"]),
            audio_span_id=(
                str(turn_event.get("audio_span_id"))
                if turn_event.get("audio_span_id")
                else None
            ),
            asr_event_id=(
                str(asr_event["event_id"]) if asr_event is not None else None
            ),
            thinker_event_id=(
                str(thinker_event["event_id"]) if thinker_event is not None else None
            ),
            fast_interaction_event_id=(
                str(fast_interaction_event["event_id"])
                if fast_interaction_event is not None
                else None
            ),
            foreground_candidate_event_id=(
                str(foreground_candidate_event["event_id"])
                if foreground_candidate_event is not None
                else None
            ),
            provider_call_used=bool(
                getattr(evidence_result, "provider_call_used", False)
            ),
            fake_transport_used=bool(
                getattr(evidence_result, "fake_transport_used", False)
            ),
            warnings=(
                "active_task_context requires canonical SlowTask journal authority",
            ),
        )
    router_context = _router_context(authoritative_active_task)
    base_monotonic_ms = _last_int(evidence_events, "created_monotonic_ms") + 10
    base_wall_clock_ms = _last_int(evidence_events, "created_wall_clock_ms") + 10
    router_started = time.monotonic()
    try:
        router_result = MVP1Router(journal).emit_decision(
            turn_committed_event=turn_event,
            asr_frame_event=routing_asr_event,
            thinker_frame_event=thinker_event,
            fast_interaction_output_event=fast_interaction_event,
            router_context=router_context,
            event_id=f"evt_mvp5_live_route_{slug}_router_decision",
            task_focus_state_event_id=f"evt_mvp5_live_route_{slug}_task_focus_state",
            created_monotonic_ms=base_monotonic_ms,
            created_wall_clock_ms=base_wall_clock_ms,
        )
    except ValueError as exc:
        if "active non-terminal SlowTask" not in str(exc):
            raise
        return MVP5LiveRouteResult(
            run_id=run_id,
            status="blocked_missing_active_task_context",
            route_result_kind="degraded",
            router_decision=None,
            expected_route=expected_route,
            expected_route_matched=False if expected_route is not None else None,
            events=tuple(journal.events()),
            turn_id=str(turn_event["turn_id"]),
            utterance_id=str(turn_event["utterance_id"]),
            audio_span_id=str(turn_event.get("audio_span_id")) if turn_event.get("audio_span_id") else None,
            asr_event_id=str(asr_event["event_id"]) if asr_event is not None else None,
            thinker_event_id=str(thinker_event["event_id"]) if thinker_event is not None else None,
            fast_interaction_event_id=(
                str(fast_interaction_event["event_id"])
                if fast_interaction_event is not None
                else None
            ),
            foreground_candidate_event_id=(
                str(foreground_candidate_event["event_id"])
                if foreground_candidate_event is not None
                else None
            ),
            provider_call_used=bool(getattr(evidence_result, "provider_call_used", False)),
            fake_transport_used=bool(getattr(evidence_result, "fake_transport_used", False)),
            warnings=("PATCH_ACTIVE_SLOW_TASK requires active_task_context",),
        )
    router_ms = _elapsed_ms(router_started)
    router_event = router_result.router_decision_event
    route = str(router_event["router_decision"])
    foreground_gate_result = _run_fast_foreground_gate_if_available(
        journal=journal,
        fast_interaction_event=fast_interaction_event,
        foreground_candidate_event=foreground_candidate_event,
        router_event=router_event,
        configured_context=config.fast_foreground_gate_context,
        active_task_context=authoritative_active_task,
        fake_transport_used=bool(getattr(evidence_result, "fake_transport_used", False)),
        event_id_prefix=f"evt_mvp63_live_route_{_safe_segment(run_id)}_foreground_gate",
        created_monotonic_ms=base_monotonic_ms + 2,
        created_wall_clock_ms=base_wall_clock_ms + 2,
    )
    if foreground_candidate_event is None and fast_interaction_event is not None:
        foreground_candidate_event = _optional_event_by_id_or_name(
            tuple(journal.events()),
            event_id=None,
            event_names=("FOREGROUND_REPLY_CANDIDATE_EMITTED",),
        )
    foreground_gate_ms = (
        foreground_gate_result.gate_decision_ms
        if foreground_gate_result is not None
        else None
    )
    foreground_output_finalize_ms = (
        foreground_gate_result.output_finalize_ms
        if foreground_gate_result is not None
        else None
    )

    if expected_route is not None and expected_route != route:
        return _result_from_journal(
            run_id=run_id,
            status="route_mismatch",
            route_result_kind="mismatch",
            router_decision=route,
            expected_route=expected_route,
            expected_route_matched=False,
            journal=journal,
            turn_event=turn_event,
            asr_event=asr_event,
            thinker_event=thinker_event,
            fast_interaction_event=fast_interaction_event,
            foreground_candidate_event=foreground_candidate_event,
            router_event=router_event,
            task_focus_state_event=router_result.task_focus_state_event,
            foreground_gate_result=foreground_gate_result,
            provider_call_used=bool(getattr(evidence_result, "provider_call_used", False)),
            fake_transport_used=bool(getattr(evidence_result, "fake_transport_used", False)),
            warnings=(f"expected_route_mismatch:{expected_route}!={route}",),
            router_ms=router_ms,
            foreground_gate_ms=foreground_gate_ms,
            foreground_output_finalize_ms=foreground_output_finalize_ms,
        )

    if route == "FAST_ONLY":
        if (
            foreground_gate_result is None
            or foreground_gate_result.committed_event is None
        ):
            raise MVP5LiveRouterRunnerError(
                "FAST_ONLY requires terminal Gate and foreground commit"
            )
        committed_basis = str(
            foreground_gate_result.committed_event["output_basis"]
        )
        response_text_ref = str(
            foreground_gate_result.committed_event["output_ref"]
        )
        return _result_from_journal(
            run_id=run_id,
            status="routed",
            route_result_kind=(
                "direct_answer"
                if committed_basis == "reply_candidate"
                else "foreground_clarify"
            ),
            router_decision=route,
            expected_route=expected_route,
            expected_route_matched=_expected_route_matched(expected_route, route),
            journal=journal,
            turn_event=turn_event,
            asr_event=asr_event,
            thinker_event=thinker_event,
            fast_interaction_event=fast_interaction_event,
            foreground_candidate_event=foreground_candidate_event,
            router_event=router_event,
            task_focus_state_event=router_result.task_focus_state_event,
            foreground_gate_result=foreground_gate_result,
            response_text_ref=response_text_ref,
            provider_call_used=bool(getattr(evidence_result, "provider_call_used", False)),
            fake_transport_used=bool(getattr(evidence_result, "fake_transport_used", False)),
            router_ms=router_ms,
            foreground_gate_ms=foreground_gate_ms,
            foreground_output_finalize_ms=foreground_output_finalize_ms,
        )

    if route == "SPAWN_SLOW_TASK":
        source_refs = _live_evidence_refs(
            asr_event=asr_event,
            thinker_event=thinker_event,
            fast_interaction_event=fast_interaction_event,
        )
        task_id = f"task_mvp5_goal3_{slug}"
        try:
            slowtask_result = MockSlowTaskRuntime(journal).run_spawn_planning_completed(
                router_decision_event=router_event,
                task_id=task_id,
                initial_goal_ref=f"goal://synthetic/mvp5/{slug}/initial",
                commitment_id=f"commitment_mvp5_goal3_{slug}",
                event_id_prefix=f"evt_mvp5_live_route_{slug}",
                created_monotonic_ms=base_monotonic_ms + 10,
                created_wall_clock_ms=base_wall_clock_ms + 10,
                source_evidence_refs=source_refs,
                evidence_refs=source_refs,
                commitment_ref=f"commitment://synthetic/mvp5/{slug}/metadata-only",
            )
        except Exception:
            foreground_gate_result = _finalize_failed_mutation_foreground(
                journal=journal,
                gate_result=foreground_gate_result,
                router_event=router_event,
                event_id_prefix=(
                    f"evt_mvp63_live_route_{_safe_segment(run_id)}_foreground_failure"
                ),
                created_monotonic_ms=base_monotonic_ms + 30,
                created_wall_clock_ms=base_wall_clock_ms + 30,
            )
            return _result_from_journal(
                run_id=run_id,
                status="degraded_mutation_failed",
                route_result_kind="degraded",
                router_decision=route,
                expected_route=expected_route,
                expected_route_matched=_expected_route_matched(expected_route, route),
                journal=journal,
                turn_event=turn_event,
                asr_event=asr_event,
                thinker_event=thinker_event,
                fast_interaction_event=fast_interaction_event,
                foreground_candidate_event=foreground_candidate_event,
                router_event=router_event,
                task_focus_state_event=router_result.task_focus_state_event,
                foreground_gate_result=foreground_gate_result,
                task_id=task_id,
                provider_call_used=bool(getattr(evidence_result, "provider_call_used", False)),
                fake_transport_used=bool(getattr(evidence_result, "fake_transport_used", False)),
                warnings=("SPAWN_SLOW_TASK mutation failed; success ACK suppressed",),
                router_ms=router_ms,
                foreground_gate_ms=foreground_gate_ms,
                foreground_output_finalize_ms=foreground_output_finalize_ms,
            )
        if foreground_gate_result is not None:
            created_events = [
                event
                for event in slowtask_result.produced_events
                if event.get("event_name") == "SLOWTASK_CREATED"
            ]
            if len(created_events) != 1:
                raise MVP5LiveRouterRunnerError(
                    "successful spawn must produce one SLOWTASK_CREATED"
                )
            foreground_gate_result = commit_deferred_foreground_template(
                journal,
                gate_result=foreground_gate_result,
                router_decision_event=router_event,
                output_basis="template_ack",
                mutation_event=created_events[0],
                fallback_reason="slowtask_mutation_completed",
                event_id_prefix=(
                    f"evt_mvp63_live_route_{_safe_segment(run_id)}_foreground_success"
                ),
                created_monotonic_ms=base_monotonic_ms + 30,
                created_wall_clock_ms=base_wall_clock_ms + 30,
            )
        return _result_from_journal(
            run_id=run_id,
            status="routed",
            route_result_kind="slowtask_spawn",
            router_decision=route,
            expected_route=expected_route,
            expected_route_matched=_expected_route_matched(expected_route, route),
            journal=journal,
            turn_event=turn_event,
            asr_event=asr_event,
            thinker_event=thinker_event,
            fast_interaction_event=fast_interaction_event,
            foreground_candidate_event=foreground_candidate_event,
            router_event=router_event,
            task_focus_state_event=router_result.task_focus_state_event,
            foreground_gate_result=foreground_gate_result,
            result_summary_ref=f"summary://synthetic/mvp5/{slug}/slowtask-spawn",
            task_id=task_id,
            provider_call_used=bool(getattr(evidence_result, "provider_call_used", False)),
            fake_transport_used=bool(getattr(evidence_result, "fake_transport_used", False)),
            router_ms=router_ms,
            foreground_gate_ms=foreground_gate_ms,
            foreground_output_finalize_ms=foreground_output_finalize_ms,
        )

    if route == "PATCH_ACTIVE_SLOW_TASK":
        if authoritative_active_task is None:
            foreground_gate_result = _finalize_failed_mutation_foreground(
                journal=journal,
                gate_result=foreground_gate_result,
                router_event=router_event,
                event_id_prefix=(
                    f"evt_mvp63_live_route_{_safe_segment(run_id)}_foreground_missing_task"
                ),
                created_monotonic_ms=base_monotonic_ms + 20,
                created_wall_clock_ms=base_wall_clock_ms + 20,
            )
            return _result_from_journal(
                run_id=run_id,
                status="blocked_missing_active_task_context",
                route_result_kind="degraded",
                router_decision=route,
                expected_route=expected_route,
                expected_route_matched=_expected_route_matched(expected_route, route),
                journal=journal,
                turn_event=turn_event,
                asr_event=asr_event,
                thinker_event=thinker_event,
                fast_interaction_event=fast_interaction_event,
                foreground_candidate_event=foreground_candidate_event,
                router_event=router_event,
                task_focus_state_event=router_result.task_focus_state_event,
                foreground_gate_result=foreground_gate_result,
                provider_call_used=bool(getattr(evidence_result, "provider_call_used", False)),
                fake_transport_used=bool(getattr(evidence_result, "fake_transport_used", False)),
                warnings=("PATCH_ACTIVE_SLOW_TASK requires active_task_context",),
                router_ms=router_ms,
                foreground_gate_ms=foreground_gate_ms,
                foreground_output_finalize_ms=foreground_output_finalize_ms,
            )
        if thinker_event is None:
            foreground_gate_result = _finalize_failed_mutation_foreground(
                journal=journal,
                gate_result=foreground_gate_result,
                router_event=router_event,
                event_id_prefix=(
                    f"evt_mvp63_live_route_{_safe_segment(run_id)}_foreground_missing_thinker"
                ),
                created_monotonic_ms=base_monotonic_ms + 20,
                created_wall_clock_ms=base_wall_clock_ms + 20,
            )
            return _result_from_journal(
                run_id=run_id,
                status="blocked_missing_thinker_patch_evidence",
                route_result_kind="degraded",
                router_decision=route,
                expected_route=expected_route,
                expected_route_matched=_expected_route_matched(expected_route, route),
                journal=journal,
                turn_event=turn_event,
                asr_event=asr_event,
                thinker_event=thinker_event,
                fast_interaction_event=fast_interaction_event,
                foreground_candidate_event=foreground_candidate_event,
                router_event=router_event,
                task_focus_state_event=router_result.task_focus_state_event,
                foreground_gate_result=foreground_gate_result,
                provider_call_used=bool(getattr(evidence_result, "provider_call_used", False)),
                fake_transport_used=bool(getattr(evidence_result, "fake_transport_used", False)),
                warnings=("PATCH_ACTIVE_SLOW_TASK requires Thinker evidence for UserPatch",),
                router_ms=router_ms,
                foreground_gate_ms=foreground_gate_ms,
                foreground_output_finalize_ms=foreground_output_finalize_ms,
            )
        patch_id = f"patch_{slug.replace('-', '_')}"
        try:
            patch_result = UserPatchEvidencePackRuntime(
                journal
            ).receive_patch_from_router_decision(
                router_decision_event=router_event,
                turn_committed_event=turn_event,
                asr_frame_event=asr_event,
                thinker_frame_event=thinker_event,
                task_id=authoritative_active_task.task_id,
                current_plan_version=authoritative_active_task.current_plan_version,
                next_task_event_seq=authoritative_active_task.current_task_event_seq + 1,
                patch_id=patch_id,
                event_id=f"evt_mvp5_live_route_{slug}_user_patch_received",
                evidence_ref=f"evidence://synthetic/mvp5/{slug}/user-patch",
                created_monotonic_ms=base_monotonic_ms + 10,
                created_wall_clock_ms=base_wall_clock_ms + 10,
                transcript_hint_ref=str(asr_event.get("text_ref", "")) or None,
                semantic_summary_ref=str(thinker_event.get("semantic_summary_ref", "")) or None,
                audio_summary_ref=f"audio-summary://synthetic/mvp5/{slug}/metadata-only",
                candidate_patch_types=("constraint_update_candidate",),
                patch_hint="live_voice_active_task_patch_candidate",
            )
            interpretation_result = MockSlowTaskRuntime(journal).interpret_user_patch(
                user_patch_event=patch_result.user_patch_event,
                event_id_prefix=f"evt_mvp5_live_route_{slug}_patch_mutation",
                created_monotonic_ms=base_monotonic_ms + 11,
                created_wall_clock_ms=base_wall_clock_ms + 11,
                current_lifecycle_state=authoritative_active_task.lifecycle_phase,
            )
            patch_completion_event = _reconcile_patch_mutation(
                journal=journal,
                active_task_context=authoritative_active_task,
                patch_event=patch_result.user_patch_event,
                produced_events=interpretation_result.produced_events,
            )
            if foreground_gate_result is not None:
                foreground_gate_result = commit_deferred_foreground_template(
                    journal,
                    gate_result=foreground_gate_result,
                    router_decision_event=router_event,
                    output_basis="template_ack",
                    mutation_event=patch_result.user_patch_event,
                    mutation_completion_event=patch_completion_event,
                    fallback_reason="user_patch_mutation_completed",
                    event_id_prefix=(
                        f"evt_mvp63_live_route_{_safe_segment(run_id)}_foreground_success"
                    ),
                    created_monotonic_ms=base_monotonic_ms + 30,
                    created_wall_clock_ms=base_wall_clock_ms + 30,
                )
        except Exception:
            foreground_gate_result = _finalize_failed_mutation_foreground(
                journal=journal,
                gate_result=foreground_gate_result,
                router_event=router_event,
                event_id_prefix=(
                    f"evt_mvp63_live_route_{_safe_segment(run_id)}_foreground_failure"
                ),
                created_monotonic_ms=base_monotonic_ms + 20,
                created_wall_clock_ms=base_wall_clock_ms + 20,
            )
            return _result_from_journal(
                run_id=run_id,
                status="degraded_mutation_failed",
                route_result_kind="degraded",
                router_decision=route,
                expected_route=expected_route,
                expected_route_matched=_expected_route_matched(expected_route, route),
                journal=journal,
                turn_event=turn_event,
                asr_event=asr_event,
                thinker_event=thinker_event,
                fast_interaction_event=fast_interaction_event,
                foreground_candidate_event=foreground_candidate_event,
                router_event=router_event,
                task_focus_state_event=router_result.task_focus_state_event,
                foreground_gate_result=foreground_gate_result,
                task_id=authoritative_active_task.task_id,
                patch_id=patch_id,
                provider_call_used=bool(getattr(evidence_result, "provider_call_used", False)),
                fake_transport_used=bool(getattr(evidence_result, "fake_transport_used", False)),
                warnings=("PATCH_ACTIVE_SLOW_TASK mutation failed; success ACK suppressed",),
                router_ms=router_ms,
                foreground_gate_ms=foreground_gate_ms,
                foreground_output_finalize_ms=foreground_output_finalize_ms,
            )
        return _result_from_journal(
            run_id=run_id,
            status="routed",
            route_result_kind="user_patch",
            router_decision=route,
            expected_route=expected_route,
            expected_route_matched=_expected_route_matched(expected_route, route),
            journal=journal,
            turn_event=turn_event,
            asr_event=asr_event,
            thinker_event=thinker_event,
            fast_interaction_event=fast_interaction_event,
            foreground_candidate_event=foreground_candidate_event,
            router_event=router_event,
            task_focus_state_event=router_result.task_focus_state_event,
            foreground_gate_result=foreground_gate_result,
            result_summary_ref=f"summary://synthetic/mvp5/{slug}/user-patch",
            task_id=authoritative_active_task.task_id,
            patch_id=str(patch_result.user_patch_event["patch_id"]),
            provider_call_used=bool(getattr(evidence_result, "provider_call_used", False)),
            fake_transport_used=bool(getattr(evidence_result, "fake_transport_used", False)),
            router_ms=router_ms,
            foreground_gate_ms=foreground_gate_ms,
            foreground_output_finalize_ms=foreground_output_finalize_ms,
        )

    return _result_from_journal(
        run_id=run_id,
        status="routed",
        route_result_kind="ignore",
        router_decision=route,
        expected_route=expected_route,
        expected_route_matched=_expected_route_matched(expected_route, route),
        journal=journal,
        turn_event=turn_event,
        asr_event=asr_event,
        thinker_event=thinker_event,
        fast_interaction_event=fast_interaction_event,
        foreground_candidate_event=foreground_candidate_event,
        router_event=router_event,
        task_focus_state_event=router_result.task_focus_state_event,
        foreground_gate_result=foreground_gate_result,
        result_summary_ref=f"summary://synthetic/mvp5/{slug}/ignore",
        provider_call_used=bool(getattr(evidence_result, "provider_call_used", False)),
        fake_transport_used=bool(getattr(evidence_result, "fake_transport_used", False)),
        router_ms=router_ms,
        foreground_gate_ms=foreground_gate_ms,
        foreground_output_finalize_ms=foreground_output_finalize_ms,
    )


def _blocked_result(
    *,
    run_id: str,
    status: str,
    warning: str,
    provider_call_used: bool,
    fake_transport_used: bool,
) -> MVP5LiveRouteResult:
    return MVP5LiveRouteResult(
        run_id=run_id,
        status=status,
        route_result_kind="degraded",
        router_decision=None,
        provider_call_used=provider_call_used,
        fake_transport_used=fake_transport_used,
        warnings=(warning,),
    )


def _result_from_journal(
    *,
    run_id: str,
    status: str,
    route_result_kind: str,
    router_decision: str,
    expected_route: str | None,
    expected_route_matched: bool | None,
    journal: InMemoryEventJournal,
    turn_event: Mapping[str, Any],
    asr_event: Mapping[str, Any] | None,
    thinker_event: Mapping[str, Any] | None,
    router_event: Mapping[str, Any],
    task_focus_state_event: Mapping[str, Any],
    provider_call_used: bool,
    fake_transport_used: bool,
    fast_interaction_event: Mapping[str, Any] | None = None,
    foreground_candidate_event: Mapping[str, Any] | None = None,
    foreground_gate_result: FastForegroundGateResult | None = None,
    response_text_ref: str | None = None,
    result_summary_ref: str | None = None,
    task_id: str | None = None,
    patch_id: str | None = None,
    warnings: tuple[str, ...] = (),
    router_ms: int | None = None,
    foreground_gate_ms: int | None = None,
    foreground_output_finalize_ms: int | None = None,
) -> MVP5LiveRouteResult:
    events = tuple(journal.events())
    gate_event = foreground_gate_result.gate_event if foreground_gate_result is not None else None
    committed_event = (
        foreground_gate_result.committed_event if foreground_gate_result is not None else None
    )
    discarded_event = (
        foreground_gate_result.discarded_event if foreground_gate_result is not None else None
    )
    return MVP5LiveRouteResult(
        run_id=run_id,
        status=status,
        route_result_kind=route_result_kind,
        router_decision=router_decision,
        expected_route=expected_route,
        expected_route_matched=expected_route_matched,
        events=events,
        turn_id=str(turn_event["turn_id"]),
        utterance_id=str(turn_event["utterance_id"]),
        audio_span_id=str(turn_event.get("audio_span_id")) if turn_event.get("audio_span_id") else None,
        asr_event_id=str(asr_event["event_id"]) if asr_event is not None else None,
        thinker_event_id=str(thinker_event["event_id"]) if thinker_event is not None else None,
        fast_interaction_event_id=(
            str(fast_interaction_event["event_id"])
            if fast_interaction_event is not None
            else None
        ),
        foreground_candidate_event_id=(
            str(foreground_candidate_event["event_id"])
            if foreground_candidate_event is not None
            else None
        ),
        router_event_id=str(router_event["event_id"]),
        task_focus_state_event_id=str(task_focus_state_event["event_id"]),
        foreground_gate_event_id=str(gate_event["event_id"]) if gate_event is not None else None,
        foreground_output_event_id=(
            str(committed_event["event_id"]) if committed_event is not None else None
        ),
        foreground_discard_event_id=(
            str(discarded_event["event_id"]) if discarded_event is not None else None
        ),
        foreground_output_basis=(
            str(committed_event["output_basis"]) if committed_event is not None else None
        ),
        foreground_candidate_ref=(
            str(foreground_candidate_event["candidate_ref"])
            if foreground_candidate_event is not None
            else None
        ),
        foreground_output_ref=(
            str(committed_event["output_ref"]) if committed_event is not None else None
        ),
        foreground_fallback_policy_ref=(
            str(committed_event["fallback_policy_ref"])
            if committed_event is not None
            and committed_event.get("fallback_policy_ref") not in (None, "")
            else None
        ),
        foreground_fallback_reason=(
            str(committed_event["fallback_reason"])
            if committed_event is not None
            and committed_event.get("fallback_reason") not in (None, "")
            else None
        ),
        foreground_gate_decision=(
            _foreground_gate_decision(gate_event) if gate_event is not None else None
        ),
        foreground_gate_failure_reason=(
            str(gate_event["failure_reason"])
            if gate_event is not None and gate_event.get("event_name") == "FOREGROUND_ACT_GATE_FAILED"
            else None
        ),
        response_text_ref=response_text_ref,
        result_summary_ref=result_summary_ref,
        evidence_ref_policy=_route_evidence_ref_policy(
            asr_event=asr_event,
            thinker_event=thinker_event,
            fast_interaction_event=fast_interaction_event,
        ),
        task_id=task_id,
        patch_id=patch_id,
        router_ms=router_ms,
        foreground_gate_ms=foreground_gate_ms,
        foreground_output_finalize_ms=foreground_output_finalize_ms,
        slowtask_event_ids_by_name=_slowtask_event_ids_by_name(events),
        user_patch_event_ids=tuple(
            str(event["event_id"])
            for event in events
            if event["event_name"] == "USER_PATCH_RECEIVED"
        ),
        provider_call_used=provider_call_used,
        fake_transport_used=fake_transport_used,
        warnings=warnings,
    )


def _journal_from_recorded_events(events: Sequence[Mapping[str, Any]]) -> InMemoryEventJournal:
    if not events:
        raise MVP5LiveRouterRunnerError("events are required")
    ordered = sorted((deepcopy(dict(event)) for event in events), key=lambda event: int(event["event_seq"]))
    session_id = str(ordered[0]["session_id"])
    conversation_id = str(ordered[0]["conversation_id"])
    journal = InMemoryEventJournal(session_id=session_id, conversation_id=conversation_id)
    seen_ids: set[str] = set()
    for expected_seq, event in enumerate(ordered, start=1):
        if int(event["event_seq"]) != expected_seq:
            raise MVP5LiveRouterRunnerError("Goal 2 evidence events must have contiguous event_seq")
        if event["session_id"] != session_id or event["conversation_id"] != conversation_id:
            raise MVP5LiveRouterRunnerError("Goal 2 evidence events must belong to one session")
        event_id = str(event["event_id"])
        if event_id in seen_ids:
            raise MVP5LiveRouterRunnerError("Goal 2 evidence events must not duplicate event_id")
        seen_ids.add(event_id)
        journal._append_validated_event(event)
    return journal


def _router_context(active_task_context: MVP5ActiveSlowTaskContext | None) -> RouterContext:
    if active_task_context is None:
        return RouterContext(task_focus_snapshot=TaskFocusSnapshot())
    if active_task_context.current_plan_version < 1:
        raise MVP5LiveRouterRunnerError("active task current_plan_version must be positive")
    if active_task_context.current_task_event_seq < 1:
        raise MVP5LiveRouterRunnerError("active task current_task_event_seq must be positive")
    return RouterContext(
        task_focus_snapshot=TaskFocusSnapshot(
            active_task_id=_require_safe_token(active_task_context.task_id, "task_id"),
            lifecycle_phase=active_task_context.lifecycle_phase,
            terminal_status=active_task_context.terminal_status,
            current_plan_version=active_task_context.current_plan_version,
            pending_confirmation_scope=active_task_context.pending_confirmation_scope,
        )
    )


def _single_event(events: Sequence[Mapping[str, Any]], event_name: str) -> dict[str, Any]:
    matches = [dict(event) for event in events if event["event_name"] == event_name]
    if len(matches) != 1:
        raise MVP5LiveRouterRunnerError(f"expected exactly one {event_name}")
    return matches[0]


def _event_by_id_or_name(
    events: Sequence[Mapping[str, Any]],
    *,
    event_id: object,
    event_names: tuple[str, ...],
) -> dict[str, Any]:
    if event_id not in (None, ""):
        matches = [dict(event) for event in events if event.get("event_id") == event_id]
        if len(matches) != 1:
            raise MVP5LiveRouterRunnerError(f"evidence event_id not found: {event_id}")
        if matches[0].get("event_name") not in event_names:
            raise MVP5LiveRouterRunnerError("evidence event_id has unexpected event_name")
        return matches[0]
    matches = [dict(event) for event in events if event["event_name"] in event_names]
    if len(matches) != 1:
        raise MVP5LiveRouterRunnerError(f"expected exactly one of {event_names}")
    return matches[0]


def _optional_event_by_id_or_name(
    events: Sequence[Mapping[str, Any]],
    *,
    event_id: object,
    event_names: tuple[str, ...],
) -> dict[str, Any] | None:
    if event_id not in (None, ""):
        return _event_by_id_or_name(events, event_id=event_id, event_names=event_names)
    matches = [dict(event) for event in events if event["event_name"] in event_names]
    if not matches:
        return None
    if len(matches) != 1:
        raise MVP5LiveRouterRunnerError(f"expected at most one of {event_names}")
    return matches[0]


def _run_fast_foreground_gate_if_available(
    *,
    journal: InMemoryEventJournal,
    fast_interaction_event: Mapping[str, Any] | None,
    foreground_candidate_event: Mapping[str, Any] | None,
    router_event: Mapping[str, Any],
    configured_context: FastForegroundGateContext | None,
    active_task_context: MVP5ActiveSlowTaskContext | None,
    fake_transport_used: bool,
    event_id_prefix: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
) -> FastForegroundGateResult | None:
    if fast_interaction_event is None:
        if router_event.get("router_decision") == "FAST_ONLY":
            return run_missing_fast_foreground_gate(
                journal,
                router_decision_event=router_event,
                event_id_prefix=event_id_prefix,
                created_monotonic_ms=created_monotonic_ms,
                created_wall_clock_ms=created_wall_clock_ms,
            )
        return None
    candidate_was_missing = foreground_candidate_event is None
    if (
        foreground_candidate_event is None
        and router_event.get("router_decision") == "IGNORE"
    ):
        return None
    if foreground_candidate_event is None:
        template = get_foreground_template(
            router_decision=str(router_event["router_decision"]),
            output_basis="template_clarify",
        )
        safe_segment = _safe_segment(event_id_prefix)
        foreground_candidate_event = journal.append(
            event_name="FOREGROUND_REPLY_CANDIDATE_EMITTED",
            event_id=f"{event_id_prefix}_local_template_candidate",
            source_module="foreground_template_catalog",
            caused_by_event_id=str(fast_interaction_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            trace_redaction_level="metadata_only",
            candidate_id=f"local_template_candidate_{safe_segment}",
            fast_interaction_output_event_id=str(fast_interaction_event["event_id"]),
            turn_id=str(fast_interaction_event["turn_id"]),
            utterance_id=str(fast_interaction_event["utterance_id"]),
            candidate_ref=template.template_ref,
            candidate_status="complete",
            input_mode=str(fast_interaction_event["input_mode"]),
            fast_interaction_input_mode=str(fast_interaction_event["input_mode"]),
            source_event_ids=(str(fast_interaction_event["event_id"]),),
            risk_tags=tuple(fast_interaction_event.get("risk_tags", ())),
            confidence=float(fast_interaction_event.get("confidence", 0.0)),
        )
    context = _authority_bound_gate_context(
        journal=journal,
        configured_context=configured_context,
        fast_interaction_event=fast_interaction_event,
        router_event=router_event,
        active_task_context=active_task_context,
        fake_transport_used=fake_transport_used,
    )
    if candidate_was_missing:
        context = replace(
            context,
            candidate_policy_decision=CandidatePolicyDecision.trusted_local_template(
                reason_code="missing_provider_candidate_fail_closed"
            ),
        )
    return run_fast_foreground_gate(
        journal,
        candidate_event=foreground_candidate_event,
        fast_interaction_output_event=fast_interaction_event,
        router_decision_event=router_event,
        context=context,
        event_id_prefix=event_id_prefix,
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
    )


def _authority_bound_gate_context(
    *,
    journal: InMemoryEventJournal,
    configured_context: FastForegroundGateContext | None,
    fast_interaction_event: Mapping[str, Any],
    router_event: Mapping[str, Any],
    active_task_context: MVP5ActiveSlowTaskContext | None,
    fake_transport_used: bool,
) -> FastForegroundGateContext:
    if configured_context is None:
        return FastForegroundGateContext(
            authority_mode="live_runtime",
            authority_binding_status="missing",
            interaction_state=None,
            interaction_state_ref=None,
            task_focus=None,
            task_focus_snapshot_ref=None,
            has_active_slowtask=None,
            active_task_id=None,
            active_slowtask_lifecycle=None,
            pending_confirmation=None,
            pending_confirmation_id=None,
            pending_confirmation_scope=None,
            capability_snapshot_ref=None,
            capability_health_status=None,
            capability_output_mode=None,
            capability_verification_status=None,
            candidate_policy_decision=CandidatePolicyDecision.quarantined_provider(
                reason_code="missing_live_gate_context"
            ),
            schema_valid=None,
            confidence_threshold=None,
        )

    binding_status = "bound"
    events = tuple(journal.events())
    turn_events = [
        event
        for event in events
        if event.get("event_name") == "TURN_INGRESS_COMMITTED"
        and event.get("event_id") == router_event.get("turn_committed_event_id")
    ]
    focus_events = [
        event
        for event in events
        if event.get("event_name") == "TASK_FOCUS_STATE_UPDATED"
        and event.get("router_decision_event_id") == router_event.get("event_id")
    ]
    interaction_state = InteractionState()
    for event in events:
        interaction_state.reduce_event(event)
    authoritative_interaction_state: str | None = interaction_state.turn_phase
    authoritative_interaction_ref: str | None = (
        interaction_state.last_interaction_event_id
    )
    authoritative_task_focus: str | None = None
    authoritative_task_focus_ref: str | None = None
    if (
        len(turn_events) != 1
        or len(focus_events) != 1
        or interaction_state.current_turn_id != router_event.get("turn_id")
        or authoritative_interaction_ref is None
    ):
        binding_status = "mismatch"
    else:
        authoritative_task_focus = str(
            focus_events[0].get("last_focus_decision", "")
        )
        authoritative_task_focus_ref = str(focus_events[0]["event_id"])
    capability_events = [
        event
        for event in events
        if event.get("event_name") == "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED"
    ]
    authoritative_output_mode: str | None = None
    if len(capability_events) != 1:
        binding_status = "mismatch"
    else:
        capability_event = capability_events[0]
        if (
            configured_context.capability_snapshot_ref
            != capability_event.get("capability_snapshot_ref")
        ):
            binding_status = "mismatch"
        adapter_ids = capability_event.get("adapter_ids")
        adapter_types = capability_event.get("adapter_types")
        output_modes = capability_event.get("output_modes")
        if not all(isinstance(value, (list, tuple)) for value in (
            adapter_ids,
            adapter_types,
            output_modes,
        )):
            binding_status = "mismatch"
        else:
            matches = [
                index
                for index, (adapter_id, adapter_type) in enumerate(
                    zip(adapter_ids, adapter_types, strict=False)
                )
                if adapter_id == fast_interaction_event.get("adapter_id")
                and adapter_type == "fast_interaction"
            ]
            if len(matches) != 1 or matches[0] >= len(output_modes):
                binding_status = "mismatch"
            else:
                mode = output_modes[matches[0]]
                if isinstance(mode, str) and mode:
                    authoritative_output_mode = mode
                else:
                    binding_status = "mismatch"

    authoritative_active_task, task_authority_matches = (
        _active_task_authority_from_journal(
            events=events,
            fallback=active_task_context,
            target_task_id=(
                str(router_event["active_task_id"])
                if router_event.get("active_task_id") not in (None, "")
                else None
            ),
        )
    )
    if not task_authority_matches:
        binding_status = "mismatch"
    expected_has_active = authoritative_active_task is not None
    if configured_context.has_active_slowtask is not expected_has_active:
        binding_status = "mismatch"
    if authoritative_active_task is None:
        if any(
            value is not None
            for value in (
                configured_context.active_task_id,
                configured_context.active_slowtask_lifecycle,
                configured_context.active_plan_version,
                configured_context.active_task_event_seq,
                configured_context.pending_confirmation_id,
                configured_context.pending_confirmation_scope,
            )
        ) or configured_context.pending_confirmation is not False:
            binding_status = "mismatch"
    else:
        pending_confirmation = (
            authoritative_active_task.pending_confirmation_scope is not None
        )
        if (
            configured_context.active_task_id != authoritative_active_task.task_id
            or configured_context.active_slowtask_lifecycle
            != authoritative_active_task.lifecycle_phase
            or configured_context.active_plan_version
            != authoritative_active_task.current_plan_version
            or configured_context.active_task_event_seq
            != authoritative_active_task.current_task_event_seq
            or configured_context.pending_confirmation != pending_confirmation
            or configured_context.pending_confirmation_id
            != authoritative_active_task.pending_confirmation_id
            or configured_context.pending_confirmation_scope
            != authoritative_active_task.pending_confirmation_scope
        ):
            binding_status = "mismatch"
        if (
            router_event.get("active_task_id") != authoritative_active_task.task_id
            or focus_events
            and focus_events[0].get("active_task_id")
            != authoritative_active_task.task_id
        ):
            binding_status = "mismatch"

    policy = configured_context.candidate_policy_decision
    if policy.provenance == "trusted_synthetic" and not fake_transport_used:
        binding_status = "mismatch"

    return replace(
        configured_context,
        authority_binding_status=binding_status,
        interaction_state=authoritative_interaction_state,
        interaction_state_ref=authoritative_interaction_ref,
        task_focus=authoritative_task_focus,
        task_focus_snapshot_ref=authoritative_task_focus_ref,
        capability_output_mode=authoritative_output_mode,
    )


def _active_task_authority_from_journal(
    *,
    events: Sequence[Mapping[str, Any]],
    fallback: MVP5ActiveSlowTaskContext | None,
    target_task_id: str | None,
) -> tuple[MVP5ActiveSlowTaskContext | None, bool]:
    task_events = [
        event
        for event in events
        if event.get("event_name") in SLOWTASK_EVENT_NAMES
    ]
    if not task_events:
        return None, fallback is None
    state = SlowTaskState()
    try:
        for event in task_events:
            state.reduce_event(event)
    except ValueError:
        return None, False
    task_id = (
        target_task_id
        or (fallback.task_id if fallback is not None else None)
        or state.last_task_id
    )
    if task_id is None:
        return None, fallback is None
    record = state.tasks.get(task_id)
    if record is None:
        return None, False
    confirmation = record.confirmation_state
    derived = MVP5ActiveSlowTaskContext(
        task_id=task_id,
        current_plan_version=record.current_plan_version,
        current_task_event_seq=record.current_task_event_seq,
        lifecycle_phase=record.lifecycle_state,
        terminal_status=(
            record.terminal_outcome or record.lifecycle_state
            if record.is_terminal
            else None
        ),
        pending_confirmation_id=confirmation.pending_confirmation_id,
        pending_confirmation_scope=confirmation.confirmation_scope,
    )
    return derived, fallback is None or fallback == derived


def _finalize_failed_mutation_foreground(
    *,
    journal: InMemoryEventJournal,
    gate_result: FastForegroundGateResult | None,
    router_event: Mapping[str, Any],
    event_id_prefix: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
) -> FastForegroundGateResult | None:
    if gate_result is None:
        return None
    return commit_deferred_foreground_template(
        journal,
        gate_result=gate_result,
        router_decision_event=router_event,
        output_basis="template_clarify",
        mutation_event=None,
        fallback_reason="mutation_failed",
        event_id_prefix=event_id_prefix,
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
    )


def _reconcile_patch_mutation(
    *,
    journal: InMemoryEventJournal,
    active_task_context: MVP5ActiveSlowTaskContext,
    patch_event: Mapping[str, Any],
    produced_events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    expected_names = (
        "USER_PATCH_INTERPRETED",
        "PLAN_VERSION_ADVANCED",
        "PLANNING_RESTARTED",
        "TASK_REPLANNED",
        "SLOWTASK_STATE_CHANGED",
    )
    if tuple(event.get("event_name") for event in produced_events) != expected_names:
        raise MVP5LiveRouterRunnerError(
            "PATCH mutation did not produce the complete canonical tail"
        )
    if active_task_context.terminal_status is not None:
        raise MVP5LiveRouterRunnerError("PATCH cannot advance terminal task authority")
    task_id = active_task_context.task_id
    state = SlowTaskState(
        tasks={
            task_id: SlowTaskRecord(
                task_id=task_id,
                lifecycle_state=active_task_context.lifecycle_phase,
                current_plan_version=active_task_context.current_plan_version,
                current_task_event_seq=active_task_context.current_task_event_seq,
                initial_goal_ref=(
                    f"goal://current-authority/mvp5/{_safe_segment(task_id)}"
                ),
            )
        },
        last_task_id=task_id,
    )
    canonical_events = {
        str(event["event_id"]): event for event in journal.events()
    }
    mutation_events = (patch_event, *produced_events)
    for event in mutation_events:
        canonical = canonical_events.get(str(event.get("event_id", "")))
        if canonical is None or canonical != dict(event):
            raise MVP5LiveRouterRunnerError(
                "PATCH mutation mapping differs from canonical journal"
            )
        state.reduce_event(event)
    record = state.tasks[task_id]
    if (
        record.current_plan_version
        != active_task_context.current_plan_version + 1
        or record.current_task_event_seq
        != active_task_context.current_task_event_seq + 6
        or record.lifecycle_state != "PLANNING"
        or record.is_terminal
        or len(record.user_patch_evidence) != 1
        or len(record.user_patch_interpretations) != 1
        or record.user_patch_evidence[0].patch_id != patch_event.get("patch_id")
        or record.user_patch_interpretations[0].patch_id
        != patch_event.get("patch_id")
    ):
        raise MVP5LiveRouterRunnerError(
            "PATCH reducer reconciliation did not reach expected current authority"
        )
    return dict(produced_events[-1])


def _live_evidence_refs(
    *,
    asr_event: Mapping[str, Any] | None,
    thinker_event: Mapping[str, Any] | None,
    fast_interaction_event: Mapping[str, Any] | None = None,
) -> tuple[str, ...]:
    refs: tuple[str, ...] = ()
    if asr_event is not None:
        refs = (
            f"event://mvp5/{asr_event['event_id']}",
            str(asr_event["asr_frame_ref"]),
        )
    if thinker_event is not None:
        refs = (
            *refs,
            f"event://mvp5/{thinker_event['event_id']}",
            str(thinker_event["semantic_frame_ref"]),
        )
    if fast_interaction_event is not None:
        refs = (
            *refs,
            f"event://mvp63/{fast_interaction_event['event_id']}",
            str(fast_interaction_event["final_fast_evidence_ref"]),
        )
    for ref in refs:
        _require_safe_ref(ref, "source_evidence_ref")
    return refs


def _route_evidence_ref_policy(
    *,
    asr_event: Mapping[str, Any] | None,
    thinker_event: Mapping[str, Any] | None,
    fast_interaction_event: Mapping[str, Any] | None,
) -> str:
    if asr_event is not None and thinker_event is not None and fast_interaction_event is not None:
        return "preserve_asr_thinker_and_fast_refs"
    if asr_event is not None and fast_interaction_event is not None:
        return "preserve_asr_and_fast_refs"
    if fast_interaction_event is not None:
        return "preserve_fast_ref"
    return "preserve_both_refs"


def _slowtask_event_ids_by_name(events: Sequence[Mapping[str, Any]]) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = {}
    for event in events:
        event_name = str(event["event_name"])
        if event_name in {
            "SLOWTASK_CREATED",
            "SLOWTASK_STATE_CHANGED",
            "PLANNING_STARTED",
            "EVIDENCE_REVIEWED",
            "ARGUMENTS_RESOLVED",
            "ARGUMENT_RESOLUTION_PROVENANCE",
            "FINALIZING",
            "SEMANTIC_COMMITMENT_EMITTED",
        }:
            grouped.setdefault(event_name, []).append(str(event["event_id"]))
    return {name: tuple(ids) for name, ids in grouped.items()}


def _normalize_expected_route(expected_route: str | None) -> str | None:
    if expected_route in (None, "", "auto"):
        return None
    if expected_route not in MVP1_ROUTER_DECISIONS:
        raise MVP5LiveRouterRunnerError("expected_route must be auto or an existing RouterDecision")
    return str(expected_route)


def _expected_route_matched(expected_route: str | None, actual_route: str) -> bool | None:
    if expected_route is None:
        return None
    return expected_route == actual_route


def _foreground_gate_decision(gate_event: Mapping[str, Any]) -> str:
    event_name = gate_event.get("event_name")
    if event_name == "FOREGROUND_ACT_GATE_PASSED":
        return "passed"
    if event_name == "FOREGROUND_ACT_GATE_FAILED":
        return "failed"
    raise MVP5LiveRouterRunnerError("unexpected foreground gate event")


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _last_int(events: Sequence[Mapping[str, Any]], field: str) -> int:
    values = [int(event[field]) for event in events if event.get(field) not in (None, "")]
    if not values:
        raise MVP5LiveRouterRunnerError(f"Goal 2 evidence events missing {field}")
    return max(values)


def _validate_summary_metadata(metadata: Mapping[str, Any]) -> None:
    for flag in (
        "raw_audio_included",
        "raw_transcript_included",
        "raw_provider_body_included",
        "prompt_dump_included",
        "secret_included",
        "local_wav_path_included",
        "replay_reruns_provider",
        "real_tts_used",
    ):
        if metadata.get(flag) is not False:
            raise MVP5LiveRouterRunnerError(f"{flag} must be false in MVP-5 route summary")
    if metadata.get("voice_output") != "none":
        raise MVP5LiveRouterRunnerError("voice_output must be none in MVP-5 route summary")
    if metadata.get("evidence_ref_policy") not in {
        "preserve_both_refs",
        "preserve_fast_ref",
        "preserve_asr_and_fast_refs",
        "preserve_asr_thinker_and_fast_refs",
    }:
        raise MVP5LiveRouterRunnerError("evidence_ref_policy must preserve recorded evidence refs")
    _reject_unsafe_summary_values(metadata)


def _reject_unsafe_summary_values(value: Any) -> None:
    if isinstance(value, bytes):
        raise MVP5LiveRouterRunnerError("raw bytes are not allowed in MVP-5 route summary")
    if isinstance(value, str):
        lowered = value.lower()
        if any(
            marker in lowered
            for marker in (
                "file://",
                "data:",
                "/users/",
                "audio/raw/",
                "diagnostics/",
                "traces/",
                "replays/local/",
                ".env",
                "authorization:",
                "cookie:",
                "api_key=",
                "token=",
                "bearer ",
                "raw transcript",
                "provider body",
                "prompt dump",
            )
        ):
            raise MVP5LiveRouterRunnerError("unsafe string marker is not allowed in MVP-5 route summary")
        if value.startswith("/") or value.startswith("~"):
            raise MVP5LiveRouterRunnerError("local paths are not allowed in MVP-5 route summary")
        return
    if isinstance(value, Mapping):
        for child_key, child_value in value.items():
            if str(child_key) in {
                "raw_audio",
                "raw_transcript",
                "provider_body",
                "prompt_dump",
                "local_wav_path",
                "secret",
            }:
                raise MVP5LiveRouterRunnerError("unsafe summary key is not allowed in MVP-5 route summary")
            _reject_unsafe_summary_values(child_value)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_unsafe_summary_values(item)


def _require_safe_ref(value: object, field: str) -> str:
    token = _require_safe_token(value, field)
    if "://" not in token:
        raise MVP5LiveRouterRunnerError(f"{field} must be a safe ref")
    if not is_safe_mvp5_live_ref(token):
        raise MVP5LiveRouterRunnerError(f"{field} must be safe MVP-5 metadata")
    return token


def _require_safe_token(value: object, field: str) -> str:
    if not isinstance(value, str) or value == "":
        raise MVP5LiveRouterRunnerError(f"{field} must be a non-empty string")
    if any(marker in value.lower() for marker in ("api_key=", "authorization=", "token=", "bearer ")):
        raise MVP5LiveRouterRunnerError(f"{field} must not contain credential-like content")
    if value.startswith("/") or value.startswith("~"):
        raise MVP5LiveRouterRunnerError(f"{field} must not be a local path")
    return value


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-") or "unknown"


def _safe_segment(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in value).strip("_") or "unknown"
