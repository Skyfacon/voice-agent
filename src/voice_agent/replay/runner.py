from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from voice_agent.events.envelope import EventValidationError, validate_event_envelope
from voice_agent.events.registry import MVP1_EVENT_NAMES, get_event_definition
from voice_agent.replay.manifest import ReplayManifest, validate_replay_manifest
from voice_agent.replay.state_digest import state_digest
from voice_agent.router.router import (
    MVP0_TASK_FOCUS_BY_DECISION,
    MVP1_PATCH_FOCUS_VALUES,
    MVP1_ROUTER_DECISIONS,
    MVP1_TASK_FOCUS_VALUES,
)
from voice_agent.state.adapter_health_state import AdapterHealthState
from voice_agent.state.interaction_state import InteractionState
from voice_agent.state.playback_state import PlaybackState
from voice_agent.state.slowtask_state import SlowTaskState
from voice_agent.state.task_focus_state import TaskFocusState
from voice_agent.state.trace_privacy_state import TracePrivacyState


class ReplayValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ReplayResult:
    replay_mode: str
    fixture_domain: str
    manifest: ReplayManifest
    ordered_events: tuple[dict[str, Any], ...]
    replay_events: tuple[dict[str, Any], ...]
    interaction_state: InteractionState
    task_focus_state: TaskFocusState
    playback_state: PlaybackState
    adapter_health_state: AdapterHealthState
    trace_privacy_state: TracePrivacyState
    slowtask_state: SlowTaskState
    diagnostics: dict[str, Any]
    state_digest: dict[str, Any]
    result_status: str


DATA_PLANE_REF_FIELDS = frozenset(
    {
        "audio_ref",
        "tts_stream_ref",
        "audio_format_ref",
        "text_ref",
        "asr_frame_ref",
        "semantic_frame_ref",
        "runtime_config_ref",
        "capability_snapshot_ref",
        "failure_summary_ref",
    }
)


def run_replay_fixture(fixture: Mapping[str, Any]) -> ReplayResult:
    manifest = validate_replay_manifest(_required_mapping(fixture, "replay_manifest"))
    raw_events = _required_sequence(fixture, "events")
    ordered_events = _validate_and_order_events(raw_events, manifest=manifest)

    diagnostics: dict[str, Any] = {
        "ignored_events": [],
        "data_plane_refs": [],
    }
    interaction_state = InteractionState()
    task_focus_state = TaskFocusState()
    slowtask_state = SlowTaskState()
    playback_state = PlaybackState()
    adapter_health_state = AdapterHealthState()
    trace_privacy_state = TracePrivacyState.from_manifest(manifest.to_dict())

    for event in ordered_events:
        diagnostics["data_plane_refs"].extend(_unavailable_data_plane_refs(event))
        try:
            handled = [
                interaction_state.reduce_event(event),
                task_focus_state.reduce_event(event),
                slowtask_state.reduce_event(event),
                playback_state.reduce_event(event),
                adapter_health_state.reduce_event(event),
                trace_privacy_state.reduce_event(event),
            ]
        except ValueError as exc:
            raise ReplayValidationError(str(exc)) from exc
        if not any(handled):
            if event["event_name"] in MVP1_EVENT_NAMES:
                raise ReplayValidationError(
                    f"MVP-1 event requires reducer support before replay can pass: {event['event_name']}"
                )
            diagnostics["ignored_events"].append(
                {
                    "event_id": event["event_id"],
                    "event_name": event["event_name"],
                    "reason": "no_slice3_reducer_owner",
                }
            )

    try:
        slowtask_state.validate_replay_complete()
    except ValueError as exc:
        raise ReplayValidationError(str(exc)) from exc

    result_status = "degraded" if manifest.replay_mode == "degraded" else "passed"
    trace_privacy_state.mark_replay_completed(result_status=result_status)
    digest = state_digest(
        source_session_id=_source_session_id(ordered_events),
        last_event_seq=ordered_events[-1]["event_seq"] if ordered_events else 0,
        event_schema_version_range=manifest.event_schema_version_range,
        interaction_state=interaction_state,
        task_focus_state=task_focus_state,
        playback_state=playback_state,
        adapter_health_state=adapter_health_state,
        trace_privacy_state=trace_privacy_state,
        slowtask_state=slowtask_state,
    )
    replay_events = _build_replay_marker_events(
        manifest=manifest,
        ordered_events=ordered_events,
        state_digest_payload=digest,
        result_status=result_status,
    )

    return ReplayResult(
        replay_mode=manifest.replay_mode,
        fixture_domain=manifest.fixture_domain,
        manifest=manifest,
        ordered_events=tuple(deepcopy(ordered_events)),
        replay_events=replay_events,
        interaction_state=interaction_state,
        task_focus_state=task_focus_state,
        slowtask_state=slowtask_state,
        playback_state=playback_state,
        adapter_health_state=adapter_health_state,
        trace_privacy_state=trace_privacy_state,
        diagnostics=diagnostics,
        state_digest=digest,
        result_status=result_status,
    )


def _validate_and_order_events(raw_events: Sequence[object], *, manifest: ReplayManifest) -> list[dict[str, Any]]:
    validated_events: list[dict[str, Any]] = []
    for raw_event in raw_events:
        if not isinstance(raw_event, Mapping):
            raise ReplayValidationError("events must contain objects")
        try:
            validated_events.append(validate_event_envelope(raw_event))
        except EventValidationError as exc:
            raise ReplayValidationError(str(exc)) from exc

    ordered_events = sorted(validated_events, key=lambda event: event["event_seq"])
    _validate_unique_event_seq(ordered_events)
    _validate_single_session(ordered_events)
    _validate_causal_links_after_sort(ordered_events)
    _validate_audio_turn_opened_before_commit(ordered_events)
    _validate_router_decision_scope(ordered_events, manifest=manifest)
    _validate_task_focus_state_update_causality(ordered_events)
    _validate_task_focus_active_task_creation_order(ordered_events)
    _validate_post_commit_understanding_and_router_order(ordered_events)
    return ordered_events


def _build_replay_marker_events(
    *,
    manifest: ReplayManifest,
    ordered_events: Sequence[Mapping[str, Any]],
    state_digest_payload: Mapping[str, Any],
    result_status: str,
) -> tuple[dict[str, Any], ...]:
    marker_context = _replay_marker_context(manifest=manifest, ordered_events=ordered_events)
    replay_started_payload: dict[str, Any] = {
        "event_name": "REPLAY_STARTED",
        "event_id": f"evt_{manifest.replay_id}_started",
        "event_seq": marker_context["started_event_seq"],
        "event_schema_version": marker_context["event_schema_version"],
        "session_id": marker_context["session_id"],
        "conversation_id": marker_context["conversation_id"],
        "source_module": "replay_runtime",
        "created_monotonic_ms": marker_context["created_monotonic_ms"],
        "created_wall_clock_ms": marker_context["created_wall_clock_ms"],
        "trace_redaction_level": "metadata_only",
        "replay_id": manifest.replay_id,
        "source_trace_ref": manifest.source_trace_ref,
        "replay_mode": manifest.replay_mode,
    }
    if marker_context["caused_by_event_id"] is not None:
        replay_started_payload["caused_by_event_id"] = marker_context["caused_by_event_id"]

    replay_started = validate_event_envelope(replay_started_payload)
    replay_completed = validate_event_envelope(
        {
            "event_name": "REPLAY_COMPLETED",
            "event_id": f"evt_{manifest.replay_id}_completed",
            "event_seq": marker_context["completed_event_seq"],
            "event_schema_version": marker_context["event_schema_version"],
            "session_id": marker_context["session_id"],
            "conversation_id": marker_context["conversation_id"],
            "source_module": "replay_runtime",
            "created_monotonic_ms": marker_context["created_monotonic_ms"],
            "created_wall_clock_ms": marker_context["created_wall_clock_ms"],
            "caused_by_event_id": replay_started["event_id"],
            "trace_redaction_level": "metadata_only",
            "replay_id": manifest.replay_id,
            "result_status": result_status,
            "state_digest": deepcopy(dict(state_digest_payload)),
        }
    )
    return (replay_started, replay_completed)


def _replay_marker_context(
    *,
    manifest: ReplayManifest,
    ordered_events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if ordered_events:
        final_source_event = ordered_events[-1]
        final_event_seq = int(final_source_event["event_seq"])
        return {
            "started_event_seq": final_event_seq + 1,
            "completed_event_seq": final_event_seq + 2,
            "event_schema_version": final_source_event["event_schema_version"],
            "session_id": final_source_event["session_id"],
            "conversation_id": final_source_event["conversation_id"],
            "created_monotonic_ms": final_source_event["created_monotonic_ms"],
            "created_wall_clock_ms": final_source_event["created_wall_clock_ms"],
            "caused_by_event_id": final_source_event["event_id"],
        }

    return {
        "started_event_seq": 1,
        "completed_event_seq": 2,
        "event_schema_version": manifest.event_schema_version_range[0],
        "session_id": f"sess_{manifest.replay_id}",
        "conversation_id": f"conv_{manifest.replay_id}",
        "created_monotonic_ms": 0,
        "created_wall_clock_ms": 0,
        "caused_by_event_id": None,
    }


def _validate_unique_event_seq(ordered_events: Sequence[Mapping[str, Any]]) -> None:
    seen: set[int] = set()
    for event in ordered_events:
        event_seq = int(event["event_seq"])
        if event_seq in seen:
            raise ReplayValidationError(f"Duplicate event_seq: {event_seq}")
        seen.add(event_seq)


def _validate_single_session(ordered_events: Sequence[Mapping[str, Any]]) -> None:
    session_ids = {event["session_id"] for event in ordered_events}
    conversation_ids = {event["conversation_id"] for event in ordered_events}
    if len(session_ids) > 1:
        raise ReplayValidationError("Replay fixture must contain a single session_id")
    if len(conversation_ids) > 1:
        raise ReplayValidationError("Replay fixture must contain a single conversation_id")


def _validate_causal_links_after_sort(ordered_events: Sequence[Mapping[str, Any]]) -> None:
    seen_event_ids: set[str] = set()
    for event in ordered_events:
        event_id = str(event["event_id"])
        definition = get_event_definition(str(event["event_name"]))
        caused_by_event_id = event.get("caused_by_event_id")
        if definition.is_root:
            seen_event_ids.add(event_id)
            continue
        if caused_by_event_id in (None, ""):
            if definition.caused_by_event_required:
                raise ReplayValidationError("caused_by_event_id must be present for non-root events")
            seen_event_ids.add(event_id)
            continue
        if caused_by_event_id not in seen_event_ids:
            raise ReplayValidationError(
                f"caused_by_event_id must reference an earlier event_seq: {caused_by_event_id}"
            )
        seen_event_ids.add(event_id)


def _validate_audio_turn_opened_before_commit(ordered_events: Sequence[Mapping[str, Any]]) -> None:
    opened_audio_turns: set[tuple[str, str]] = set()
    for event in ordered_events:
        event_name = str(event["event_name"])
        if event_name == "TURN_OPENED" and event.get("input_modality") == "audio":
            audio_span_id = event.get("audio_span_id")
            if audio_span_id not in (None, ""):
                opened_audio_turns.add((str(event["turn_id"]), str(audio_span_id)))
        elif event_name in {"TURN_INGRESS_ACCEPTED", "TURN_INGRESS_COMMITTED"} and _is_audio_ingress_event(event):
            audio_span_id = event.get("audio_span_id")
            if audio_span_id in (None, ""):
                raise ReplayValidationError(f"{event_name} audio ingress requires audio_span_id")
            if (str(event["turn_id"]), str(audio_span_id)) not in opened_audio_turns:
                raise ReplayValidationError(f"{event_name} requires prior matching audio TURN_OPENED")


def _validate_router_decision_scope(
    ordered_events: Sequence[Mapping[str, Any]],
    *,
    manifest: ReplayManifest,
) -> None:
    for event in ordered_events:
        if event["event_name"] != "ROUTER_DECISION_EMITTED":
            continue

        router_decision = str(event["router_decision"])
        if _is_mvp0_fixture(manifest):
            expected_task_focus = MVP0_TASK_FOCUS_BY_DECISION.get(router_decision)
            if expected_task_focus is None:
                raise ReplayValidationError("MVP0 router_decision must be FAST_ONLY or IGNORE")

            task_focus = event.get("task_focus")
            if task_focus is not None and str(task_focus) != expected_task_focus:
                raise ReplayValidationError("MVP0 task_focus must match FAST_ONLY/IGNORE skeleton labels")
            continue

        if router_decision not in MVP1_ROUTER_DECISIONS:
            raise ReplayValidationError("MVP-1 router_decision must be a canonical RouterDecision")

        task_focus = event.get("task_focus")
        if task_focus in (None, ""):
            raise ReplayValidationError("MVP-1 router_decision requires task_focus")
        task_focus = str(task_focus)
        if task_focus not in MVP1_TASK_FOCUS_VALUES:
            raise ReplayValidationError("MVP-1 task_focus must be an ADR-006 focus value")
        if router_decision == "PATCH_ACTIVE_SLOW_TASK":
            if task_focus not in MVP1_PATCH_FOCUS_VALUES:
                raise ReplayValidationError("PATCH_ACTIVE_SLOW_TASK requires active-task task_focus")
            if event.get("active_task_id") in (None, ""):
                raise ReplayValidationError("PATCH_ACTIVE_SLOW_TASK requires active_task_id")


def _is_mvp0_fixture(manifest: ReplayManifest) -> bool:
    return manifest.source_trace_ref.startswith("fixture://mvp0/")


def _validate_task_focus_state_update_causality(ordered_events: Sequence[Mapping[str, Any]]) -> None:
    seen_router_decision_event_ids: set[str] = set()
    for event in ordered_events:
        event_name = str(event["event_name"])
        event_id = str(event["event_id"])
        if event_name == "ROUTER_DECISION_EMITTED":
            seen_router_decision_event_ids.add(event_id)
            continue
        if event_name != "TASK_FOCUS_STATE_UPDATED":
            continue

        router_decision_event_id = str(event["router_decision_event_id"])
        if router_decision_event_id not in seen_router_decision_event_ids:
            raise ReplayValidationError(
                "TASK_FOCUS_STATE_UPDATED router_decision_event_id must reference an earlier "
                "ROUTER_DECISION_EMITTED"
            )
        if event.get("caused_by_event_id") != router_decision_event_id:
            raise ReplayValidationError(
                "TASK_FOCUS_STATE_UPDATED caused_by_event_id must match router_decision_event_id"
            )

        last_focus_event_id = event.get("last_focus_event_id")
        if last_focus_event_id not in (None, "", router_decision_event_id):
            raise ReplayValidationError(
                "TASK_FOCUS_STATE_UPDATED last_focus_event_id must match router_decision_event_id"
            )


def _validate_task_focus_active_task_creation_order(ordered_events: Sequence[Mapping[str, Any]]) -> None:
    seen_created_task_ids: set[str] = set()
    for event in ordered_events:
        event_name = str(event["event_name"])
        if event_name == "SLOWTASK_CREATED":
            seen_created_task_ids.add(str(event["task_id"]))
            continue
        if event_name not in {"ROUTER_DECISION_EMITTED", "TASK_FOCUS_STATE_UPDATED"}:
            continue

        active_task_id = event.get("active_task_id")
        if active_task_id in (None, ""):
            continue
        if str(active_task_id) not in seen_created_task_ids:
            raise ReplayValidationError(
                f"{event_name} active_task_id must not be exposed before "
                f"corresponding SLOWTASK_CREATED exists: {active_task_id}"
            )


def _is_audio_ingress_event(event: Mapping[str, Any]) -> bool:
    if event.get("input_modality") == "audio":
        return True
    return event.get("audio_span_id") not in (None, "") and event.get("text_span_id") in (None, "")


def _validate_post_commit_understanding_and_router_order(ordered_events: Sequence[Mapping[str, Any]]) -> None:
    committed_turn_events: dict[tuple[str, str], str] = {}
    mock_asr_events: dict[tuple[str, str], str] = {}
    mock_thinker_events: dict[tuple[str, str], str] = {}

    for event in ordered_events:
        event_name = str(event["event_name"])
        if event_name == "TURN_INGRESS_COMMITTED":
            committed_turn_events[_turn_key(event)] = str(event["event_id"])
        elif event_name == "MOCK_ASR_FRAME_EMITTED":
            key = _turn_key(event)
            committed_event_id = committed_turn_events.get(key)
            if committed_event_id is None:
                raise ReplayValidationError("MOCK_ASR_FRAME_EMITTED requires prior TURN_INGRESS_COMMITTED")
            if event.get("caused_by_event_id") != committed_event_id:
                raise ReplayValidationError("MOCK_ASR_FRAME_EMITTED must be caused by TURN_INGRESS_COMMITTED")
            mock_asr_events[key] = str(event["event_id"])
        elif event_name == "MOCK_THINKER_FRAME_EMITTED":
            key = _turn_key(event)
            committed_event_id = committed_turn_events.get(key)
            if committed_event_id is None:
                raise ReplayValidationError("MOCK_THINKER_FRAME_EMITTED requires prior TURN_INGRESS_COMMITTED")
            if event.get("caused_by_event_id") != committed_event_id:
                raise ReplayValidationError("MOCK_THINKER_FRAME_EMITTED must be caused by TURN_INGRESS_COMMITTED")
            mock_thinker_events[key] = str(event["event_id"])
        elif event_name == "ROUTER_DECISION_EMITTED":
            key = _turn_key(event)
            if key not in committed_turn_events:
                raise ReplayValidationError("ROUTER_DECISION_EMITTED requires prior TURN_INGRESS_COMMITTED")
            mock_asr_event_id = mock_asr_events.get(key)
            mock_thinker_event_id = mock_thinker_events.get(key)
            if mock_asr_event_id is None and mock_thinker_event_id is None:
                raise ReplayValidationError(
                    "ROUTER_DECISION_EMITTED requires prior MOCK_ASR_FRAME_EMITTED or MOCK_THINKER_FRAME_EMITTED"
                )
            if event.get("asr_frame_event_id") is not None and mock_asr_event_id is None:
                raise ReplayValidationError("ROUTER_DECISION_EMITTED asr_frame_event_id requires prior mock ASR")
            if event.get("asr_frame_event_id") not in (None, mock_asr_event_id):
                raise ReplayValidationError("ROUTER_DECISION_EMITTED asr_frame_event_id must reference prior mock ASR")
            if event.get("thinker_frame_event_id") is not None and mock_thinker_event_id is None:
                raise ReplayValidationError(
                    "ROUTER_DECISION_EMITTED thinker_frame_event_id requires prior mock Thinker"
                )
            if event.get("thinker_frame_event_id") not in (None, mock_thinker_event_id):
                raise ReplayValidationError(
                    "ROUTER_DECISION_EMITTED thinker_frame_event_id must reference prior mock Thinker"
                )


def _turn_key(event: Mapping[str, Any]) -> tuple[str, str]:
    return str(event["turn_id"]), str(event["utterance_id"])


def _unavailable_data_plane_refs(event: Mapping[str, Any]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for field in DATA_PLANE_REF_FIELDS:
        value = event.get(field)
        if isinstance(value, str) and value:
            refs.append(
                {
                    "event_id": str(event["event_id"]),
                    "field": field,
                    "ref": value,
                    "status": "unavailable",
                }
            )
    return sorted(refs, key=lambda item: (item["event_id"], item["field"]))


def _source_session_id(ordered_events: Sequence[Mapping[str, Any]]) -> str | None:
    if not ordered_events:
        return None
    return str(ordered_events[0]["session_id"])


def _required_mapping(fixture: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    value = fixture.get(field)
    if not isinstance(value, Mapping):
        raise ReplayValidationError(f"{field} must be an object")
    return value


def _required_sequence(fixture: Mapping[str, Any], field: str) -> Sequence[object]:
    value = fixture.get(field)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ReplayValidationError(f"{field} must be a list")
    return value
