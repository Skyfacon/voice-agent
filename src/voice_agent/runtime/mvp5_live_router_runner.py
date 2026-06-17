from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.runtime.mvp5_live_approval import is_safe_mvp5_live_ref
from voice_agent.router.router import (
    MVP1_ROUTER_DECISIONS,
    MVP1Router,
    RouterContext,
    TaskFocusSnapshot,
)
from voice_agent.slowtask.mock_runtime import MockSlowTaskRuntime
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
    pending_confirmation_scope: str | None = None


@dataclass(frozen=True)
class MVP5LiveRouterConfig:
    run_id: str = "mvp5-live-router-provider-free"
    expected_route: str | None = None
    active_task_context: MVP5ActiveSlowTaskContext | None = None


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
    router_event_id: str | None = None
    task_focus_state_event_id: str | None = None
    response_text_ref: str | None = None
    result_summary_ref: str | None = None
    task_id: str | None = None
    patch_id: str | None = None
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
            "asr_thinker_winner_selected": False,
        }
        optional_fields = {
            "turn_id": self.turn_id,
            "utterance_id": self.utterance_id,
            "audio_span_id": self.audio_span_id,
            "asr_event_id": self.asr_event_id,
            "thinker_event_id": self.thinker_event_id,
            "router_event_id": self.router_event_id,
            "task_focus_state_event_id": self.task_focus_state_event_id,
            "response_text_ref": self.response_text_ref,
            "result_summary_ref": self.result_summary_ref,
            "task_id": self.task_id,
            "patch_id": self.patch_id,
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
    asr_event = _event_by_id_or_name(
        evidence_events,
        event_id=getattr(evidence_result, "asr_event_id", None),
        event_names=("ASR_TRANSCRIPT_OUTPUT_EMITTED", "MOCK_ASR_FRAME_EMITTED"),
    )
    thinker_event = _event_by_id_or_name(
        evidence_events,
        event_id=getattr(evidence_result, "thinker_event_id", None),
        event_names=("THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED", "MOCK_THINKER_FRAME_EMITTED"),
    )

    journal = _journal_from_recorded_events(evidence_events)
    router_context = _router_context(config.active_task_context)
    base_monotonic_ms = _last_int(evidence_events, "created_monotonic_ms") + 10
    base_wall_clock_ms = _last_int(evidence_events, "created_wall_clock_ms") + 10
    router_result = MVP1Router(journal).emit_decision(
        turn_committed_event=turn_event,
        asr_frame_event=asr_event,
        thinker_frame_event=thinker_event,
        router_context=router_context,
        event_id=f"evt_mvp5_live_route_{slug}_router_decision",
        task_focus_state_event_id=f"evt_mvp5_live_route_{slug}_task_focus_state",
        created_monotonic_ms=base_monotonic_ms,
        created_wall_clock_ms=base_wall_clock_ms,
    )
    router_event = router_result.router_decision_event
    route = str(router_event["router_decision"])
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
            router_event=router_event,
            task_focus_state_event=router_result.task_focus_state_event,
            provider_call_used=bool(getattr(evidence_result, "provider_call_used", False)),
            fake_transport_used=bool(getattr(evidence_result, "fake_transport_used", False)),
            warnings=(f"expected_route_mismatch:{expected_route}!={route}",),
        )

    if route == "FAST_ONLY":
        return _result_from_journal(
            run_id=run_id,
            status="routed",
            route_result_kind="direct_answer",
            router_decision=route,
            expected_route=expected_route,
            expected_route_matched=_expected_route_matched(expected_route, route),
            journal=journal,
            turn_event=turn_event,
            asr_event=asr_event,
            thinker_event=thinker_event,
            router_event=router_event,
            task_focus_state_event=router_result.task_focus_state_event,
            response_text_ref=f"response://synthetic/mvp5/{slug}/direct-answer",
            provider_call_used=bool(getattr(evidence_result, "provider_call_used", False)),
            fake_transport_used=bool(getattr(evidence_result, "fake_transport_used", False)),
        )

    if route == "SPAWN_SLOW_TASK":
        source_refs = _live_evidence_refs(asr_event=asr_event, thinker_event=thinker_event)
        task_id = f"task_mvp5_goal3_{slug}"
        MockSlowTaskRuntime(journal).run_spawn_planning_completed(
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
            router_event=router_event,
            task_focus_state_event=router_result.task_focus_state_event,
            result_summary_ref=f"summary://synthetic/mvp5/{slug}/slowtask-spawn",
            task_id=task_id,
            provider_call_used=bool(getattr(evidence_result, "provider_call_used", False)),
            fake_transport_used=bool(getattr(evidence_result, "fake_transport_used", False)),
        )

    if route == "PATCH_ACTIVE_SLOW_TASK":
        if config.active_task_context is None:
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
                router_event=router_event,
                task_focus_state_event=router_result.task_focus_state_event,
                provider_call_used=bool(getattr(evidence_result, "provider_call_used", False)),
                fake_transport_used=bool(getattr(evidence_result, "fake_transport_used", False)),
                warnings=("PATCH_ACTIVE_SLOW_TASK requires active_task_context",),
            )
        patch_id = f"patch_{slug.replace('-', '_')}"
        patch_result = UserPatchEvidencePackRuntime(journal).receive_patch_from_router_decision(
            router_decision_event=router_event,
            turn_committed_event=turn_event,
            asr_frame_event=asr_event,
            thinker_frame_event=thinker_event,
            task_id=config.active_task_context.task_id,
            current_plan_version=config.active_task_context.current_plan_version,
            next_task_event_seq=config.active_task_context.current_task_event_seq + 1,
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
            router_event=router_event,
            task_focus_state_event=router_result.task_focus_state_event,
            result_summary_ref=f"summary://synthetic/mvp5/{slug}/user-patch",
            task_id=config.active_task_context.task_id,
            patch_id=str(patch_result.user_patch_event["patch_id"]),
            provider_call_used=bool(getattr(evidence_result, "provider_call_used", False)),
            fake_transport_used=bool(getattr(evidence_result, "fake_transport_used", False)),
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
        router_event=router_event,
        task_focus_state_event=router_result.task_focus_state_event,
        result_summary_ref=f"summary://synthetic/mvp5/{slug}/ignore",
        provider_call_used=bool(getattr(evidence_result, "provider_call_used", False)),
        fake_transport_used=bool(getattr(evidence_result, "fake_transport_used", False)),
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
    asr_event: Mapping[str, Any],
    thinker_event: Mapping[str, Any],
    router_event: Mapping[str, Any],
    task_focus_state_event: Mapping[str, Any],
    provider_call_used: bool,
    fake_transport_used: bool,
    response_text_ref: str | None = None,
    result_summary_ref: str | None = None,
    task_id: str | None = None,
    patch_id: str | None = None,
    warnings: tuple[str, ...] = (),
) -> MVP5LiveRouteResult:
    events = tuple(journal.events())
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
        asr_event_id=str(asr_event["event_id"]),
        thinker_event_id=str(thinker_event["event_id"]),
        router_event_id=str(router_event["event_id"]),
        task_focus_state_event_id=str(task_focus_state_event["event_id"]),
        response_text_ref=response_text_ref,
        result_summary_ref=result_summary_ref,
        task_id=task_id,
        patch_id=patch_id,
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


def _live_evidence_refs(
    *,
    asr_event: Mapping[str, Any],
    thinker_event: Mapping[str, Any],
) -> tuple[str, ...]:
    refs = (
        f"event://mvp5/{asr_event['event_id']}",
        str(asr_event["asr_frame_ref"]),
        f"event://mvp5/{thinker_event['event_id']}",
        str(thinker_event["semantic_frame_ref"]),
    )
    for ref in refs:
        _require_safe_ref(ref, "source_evidence_ref")
    return refs


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
    if metadata.get("asr_thinker_winner_selected") is not False:
        raise MVP5LiveRouterRunnerError("Router must not select an ASR/Thinker winner")
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
