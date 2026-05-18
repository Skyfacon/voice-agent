from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlparse

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
from voice_agent.state.demo_ui_state import DemoUIState
from voice_agent.state.interaction_state import InteractionState
from voice_agent.state.playback_state import PlaybackState
from voice_agent.state.slowtask_state import SlowTaskState
from voice_agent.state.task_focus_state import TaskFocusState
from voice_agent.state.tool_execution_state import ToolExecutionState
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
    tool_execution_state: ToolExecutionState
    demo_ui_state: DemoUIState
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
        "partial_arguments_ref",
        "resolved_arguments_ref",
        "provenance_ref",
        "preview_ref",
        "progress_ref",
        "patch_ref",
        "result_ref",
    }
)
MVP_ALLOWED_TOOL_SIDE_EFFECT_CLASSES = frozenset(
    {
        "READ_ONLY",
        "DRY_RUN",
        "SANDBOX_WRITE",
        "DEMO_DESTRUCTIVE_ACTION",
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
    tool_execution_state = ToolExecutionState()
    demo_ui_state = DemoUIState()

    for event in ordered_events:
        diagnostics["data_plane_refs"].extend(_unavailable_data_plane_refs(event))
        try:
            handled = [
                interaction_state.reduce_event(event),
                task_focus_state.reduce_event(event),
                slowtask_state.reduce_event(event),
                tool_execution_state.reduce_event(event),
                demo_ui_state.reduce_event(event),
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
        tool_execution_state=tool_execution_state,
        demo_ui_state=demo_ui_state,
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
        tool_execution_state=tool_execution_state,
        demo_ui_state=demo_ui_state,
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
    _validate_task_event_seq_monotonicity(ordered_events)
    _validate_audio_turn_opened_before_commit(ordered_events)
    _validate_router_decision_scope(ordered_events, manifest=manifest)
    _validate_task_focus_state_update_causality(ordered_events)
    _validate_task_focus_active_task_creation_order(ordered_events)
    _validate_post_commit_understanding_and_router_order(ordered_events)
    _validate_user_patch_evidence_pack_source_links(ordered_events)
    _validate_tool_execution_gate_links(ordered_events)
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


def _validate_task_event_seq_monotonicity(ordered_events: Sequence[Mapping[str, Any]]) -> None:
    latest_seq_by_task_id: dict[str, int] = {}
    for event in ordered_events:
        if event.get("task_id") in (None, "") or event.get("task_event_seq") in (None, ""):
            continue
        task_id = str(event["task_id"])
        task_event_seq = int(event["task_event_seq"])
        latest_seq = latest_seq_by_task_id.get(task_id)
        if latest_seq is not None and task_event_seq <= latest_seq:
            raise ReplayValidationError(
                f"{event['event_name']} task_event_seq must increase monotonically per task_id"
            )
        latest_seq_by_task_id[task_id] = task_event_seq


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


def _validate_user_patch_evidence_pack_source_links(ordered_events: Sequence[Mapping[str, Any]]) -> None:
    events_by_id = {str(event["event_id"]): event for event in ordered_events}
    for event in ordered_events:
        if event["event_name"] != "USER_PATCH_RECEIVED" or "evidence_pack" not in event:
            continue

        caused_by_event_id = str(event["caused_by_event_id"])
        router_event = events_by_id.get(caused_by_event_id)
        if router_event is None or router_event["event_name"] != "ROUTER_DECISION_EMITTED":
            raise ReplayValidationError("USER_PATCH_RECEIVED evidence_pack must be caused by ROUTER_DECISION_EMITTED")
        if router_event.get("router_decision") != "PATCH_ACTIVE_SLOW_TASK":
            raise ReplayValidationError("USER_PATCH_RECEIVED evidence_pack requires PATCH_ACTIVE_SLOW_TASK router decision")
        if router_event.get("active_task_id") != event.get("task_id"):
            raise ReplayValidationError("USER_PATCH_RECEIVED task_id must match router active_task_id")
        for field in ("turn_id", "utterance_id"):
            if event.get(field) != router_event.get(field):
                raise ReplayValidationError(f"USER_PATCH_RECEIVED {field} must match router decision")

        evidence_pack = event["evidence_pack"]
        if not isinstance(evidence_pack, Mapping):
            raise ReplayValidationError("USER_PATCH_RECEIVED evidence_pack must be an object")
        authoritative = evidence_pack.get("authoritative_evidence", {})
        hypothesis = evidence_pack.get("non_authoritative_hypothesis", {})
        if not isinstance(authoritative, Mapping) or not isinstance(hypothesis, Mapping):
            raise ReplayValidationError("USER_PATCH_RECEIVED evidence_pack sections must be objects")

        source_event_ids = _string_set(authoritative.get("source_event_ids", ()))
        _require_source_id_in_refs(
            router_event,
            source_id_field="turn_committed_event_id",
            source_event_ids=source_event_ids,
        )
        if authoritative.get("asr_frame_ref") not in (None, "") or authoritative.get("asr_nbest"):
            _require_source_id_in_refs(
                router_event,
                source_id_field="asr_frame_event_id",
                source_event_ids=source_event_ids,
            )

        if hypothesis.get("semantic_frame_ref") not in (None, "") or hypothesis.get("semantic_summary_ref") not in (None, ""):
            provenance = hypothesis.get("provenance", {})
            if not isinstance(provenance, Mapping):
                raise ReplayValidationError("USER_PATCH_RECEIVED hypothesis provenance must be an object")
            semantic_summary_provenance = provenance.get("semantic_summary_ref", {})
            if not isinstance(semantic_summary_provenance, Mapping):
                raise ReplayValidationError("USER_PATCH_RECEIVED semantic summary provenance must be an object")
            expected_thinker_event_id = router_event.get("thinker_frame_event_id")
            actual_thinker_event_id = semantic_summary_provenance.get("source_event_id")
            if expected_thinker_event_id in (None, "") or actual_thinker_event_id != expected_thinker_event_id:
                raise ReplayValidationError(
                    "USER_PATCH_RECEIVED thinker evidence must match router thinker_frame_event_id"
                )


def _validate_tool_execution_gate_links(ordered_events: Sequence[Mapping[str, Any]]) -> None:
    events_by_id: dict[str, Mapping[str, Any]] = {}
    authorizations_by_call_plan: dict[tuple[str, str, int], dict[str, Mapping[str, Any]]] = {}
    tool_manifests_by_name: dict[str, Mapping[str, Any]] = {}
    tool_names_by_call: dict[str, str] = {}
    accepted_destructive_confirmations_by_id: dict[str, Mapping[str, Any]] = {}
    started_tool_calls_by_task: dict[tuple[str, str], Mapping[str, Any]] = {}
    started_tool_calls_by_plan: dict[tuple[str, str, int], Mapping[str, Any]] = {}
    started_tool_manifests_by_plan: dict[tuple[str, str, int], Mapping[str, Any]] = {}
    cancel_requests_by_id: dict[str, Mapping[str, Any]] = {}

    for event in ordered_events:
        event_name = str(event["event_name"])
        event_id = str(event["event_id"])
        if event_name == "TOOL_MANIFEST_LOADED":
            _validate_tool_manifest_side_effect_allowed(event)
            tool_manifests_by_name[str(event["tool_name"])] = event
        elif event_name == "CONFIRMATION_ACCEPTED" and event.get("accepted_scope") == "DEMO_DESTRUCTIVE_ACTION":
            accepted_destructive_confirmations_by_id[event_id] = event
        elif event_name == "TOOL_CALL_STARTED":
            tool_names_by_call[str(event["tool_call_id"])] = str(event["tool_name"])
        elif "tool_call_id" in event and event.get("tool_name") not in (None, ""):
            tool_names_by_call.setdefault(str(event["tool_call_id"]), str(event["tool_name"]))

        if event_name == "TOOL_EXECUTION_AUTHORIZED":
            authorizations_by_call_plan.setdefault(_tool_call_plan_key(event), {})[event_id] = event
        elif event_name == "TOOL_EXECUTION_STARTED":
            authorization_events = authorizations_by_call_plan.get(_tool_call_plan_key(event), {})
            authorization_event_id = event.get("authorization_event_id")
            if authorization_event_id in (None, ""):
                authorization_event_id = event.get("caused_by_event_id")
            authorization_event = authorization_events.get(str(authorization_event_id))
            if authorization_event is None:
                raise ReplayValidationError(
                    "TOOL_EXECUTION_STARTED requires prior TOOL_EXECUTION_AUTHORIZED for the same "
                    "tool_call_id, task_id, and plan_version"
                )
            manifest = _validate_tool_start_manifest_gate(
                start_event=event,
                tool_names_by_call=tool_names_by_call,
                tool_manifests_by_name=tool_manifests_by_name,
            )
            _validate_destructive_tool_confirmation_gate(
                start_event=event,
                authorization_event=authorization_event,
                manifest=manifest,
                accepted_confirmations_by_id=accepted_destructive_confirmations_by_id,
            )
            tool_call_plan_key = _tool_call_plan_key(event)
            started_tool_calls_by_task[_tool_call_task_key(event)] = event
            started_tool_calls_by_plan[tool_call_plan_key] = event
            started_tool_manifests_by_plan[tool_call_plan_key] = manifest
        elif event_name == "TOOL_UI_STATE_PATCHED":
            tool_call_plan_key = _tool_call_plan_key(event)
            started_event = started_tool_calls_by_plan.get(tool_call_plan_key)
            if started_event is None:
                raise ReplayValidationError(
                    "TOOL_UI_STATE_PATCHED requires prior TOOL_EXECUTION_STARTED for the same "
                    "tool_call_id, task_id, and plan_version"
                )
            if event.get("idempotency_key") != started_event.get("idempotency_key"):
                raise ReplayValidationError("TOOL_UI_STATE_PATCHED idempotency_key must match TOOL_EXECUTION_STARTED")
            patch_manifest = started_tool_manifests_by_plan.get(tool_call_plan_key)
            if patch_manifest is None:
                raise ReplayValidationError(
                    "TOOL_UI_STATE_PATCHED requires manifest bound to prior TOOL_EXECUTION_STARTED"
                )
            patch_manifest = _validate_tool_ui_patch_manifest_gate(
                patch_event=event,
                manifest=patch_manifest,
            )
            _validate_ui_patch_namespace_matches_manifest(
                patch_event=event,
                manifest=patch_manifest,
            )
        elif event_name == "TOOL_EXECUTION_CANCEL_REQUESTED":
            caused_by_event = events_by_id.get(str(event["caused_by_event_id"]))
            if caused_by_event is None or caused_by_event["event_name"] not in {
                "PLAN_VERSION_ADVANCED",
                "SLOWTASK_CANCEL_REQUESTED",
                "SLOWTASK_CANCELLED",
            }:
                raise ReplayValidationError(
                    "TOOL_EXECUTION_CANCEL_REQUESTED requires prior SlowTask plan advance or cancel decision"
                )
            if caused_by_event.get("task_id") != event.get("task_id"):
                raise ReplayValidationError("TOOL_EXECUTION_CANCEL_REQUESTED task_id must match SlowTask decision")
            if caused_by_event.get("plan_version") != event.get("plan_version"):
                raise ReplayValidationError(
                    "TOOL_EXECUTION_CANCEL_REQUESTED plan_version must match SlowTask decision"
                )
            if int(event["task_event_seq"]) <= int(caused_by_event["task_event_seq"]):
                raise ReplayValidationError(
                    "TOOL_EXECUTION_CANCEL_REQUESTED task_event_seq must follow SlowTask decision"
                )
            if _tool_call_task_key(event) not in started_tool_calls_by_task:
                raise ReplayValidationError(
                    "TOOL_EXECUTION_CANCEL_REQUESTED requires prior TOOL_EXECUTION_STARTED for the same "
                    "tool_call_id and task_id"
                )
            cancel_requests_by_id[event_id] = event
        elif event_name == "TOOL_EXECUTION_CANCELLED":
            cancel_request_event_id = str(event["cancel_request_event_id"])
            cancel_request_event = cancel_requests_by_id.get(cancel_request_event_id)
            if cancel_request_event is None:
                raise ReplayValidationError(
                    "TOOL_EXECUTION_CANCELLED requires prior TOOL_EXECUTION_CANCEL_REQUESTED"
                )
            if event.get("caused_by_event_id") != cancel_request_event_id:
                raise ReplayValidationError(
                    "TOOL_EXECUTION_CANCELLED caused_by_event_id must match cancel_request_event_id"
                )
            if _tool_call_plan_key(event) != _tool_call_plan_key(cancel_request_event):
                raise ReplayValidationError(
                    "TOOL_EXECUTION_CANCELLED binding must match TOOL_EXECUTION_CANCEL_REQUESTED"
                )
        events_by_id[event_id] = event


def _validate_tool_start_manifest_gate(
    *,
    start_event: Mapping[str, Any],
    tool_names_by_call: Mapping[str, str],
    tool_manifests_by_name: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any]:
    tool_name = _tool_name_for_event(start_event, tool_names_by_call)
    if tool_name is None and len(tool_manifests_by_name) == 1:
        manifest = next(iter(tool_manifests_by_name.values()))
    else:
        manifest = tool_manifests_by_name.get(tool_name) if tool_name is not None else None
    if manifest is None:
        raise ReplayValidationError(
            "TOOL_EXECUTION_STARTED requires recorded TOOL_MANIFEST_LOADED for the same tool_call_id"
        )
    _validate_tool_manifest_side_effect_allowed(manifest)
    return manifest


def _validate_tool_ui_patch_manifest_gate(
    *,
    patch_event: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> Mapping[str, Any]:
    tool_name = patch_event.get("tool_name")
    if tool_name not in (None, "") and str(tool_name) != str(manifest["tool_name"]):
        raise ReplayValidationError("TOOL_UI_STATE_PATCHED tool_name must match started tool manifest")
    _validate_tool_manifest_side_effect_allowed(manifest)
    if manifest.get("ui_patch_capable") is not True:
        raise ReplayValidationError("TOOL_UI_STATE_PATCHED requires ui_patch_capable manifest")
    return manifest


def _validate_ui_patch_namespace_matches_manifest(
    *,
    patch_event: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> None:
    manifest_namespace = manifest.get("sandbox_state_namespace")
    if manifest_namespace in (None, ""):
        return
    patch_namespace = _patch_ref_namespace(str(patch_event["patch_ref"]))
    if patch_namespace is None:
        raise ReplayValidationError(
            "TOOL_UI_STATE_PATCHED patch_ref namespace must be parseable when manifest declares sandbox_state_namespace"
        )
    if patch_namespace != str(manifest_namespace):
        raise ReplayValidationError("TOOL_UI_STATE_PATCHED patch_ref namespace must match manifest namespace")


def _patch_ref_namespace(patch_ref: str) -> str | None:
    parsed = urlparse(patch_ref)
    if parsed.scheme != "patch" or parsed.netloc != "synthetic":
        return None
    path_parts = tuple(unquote(part) for part in parsed.path.split("/") if part)
    if len(path_parts) >= 4 and path_parts[0] == "demo_backend":
        return path_parts[1]
    if len(path_parts) >= 2:
        return path_parts[-2]
    return None


def _validate_tool_manifest_side_effect_allowed(manifest: Mapping[str, Any]) -> None:
    side_effect_class = str(manifest["side_effect_class"])
    if side_effect_class not in MVP_ALLOWED_TOOL_SIDE_EFFECT_CLASSES:
        raise ReplayValidationError(
            f"TOOL_MANIFEST_LOADED side_effect_class is not allowed in MVP replay: {side_effect_class}"
        )


def _validate_destructive_tool_confirmation_gate(
    *,
    start_event: Mapping[str, Any],
    authorization_event: Mapping[str, Any],
    manifest: Mapping[str, Any],
    accepted_confirmations_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    if manifest.get("side_effect_class") != "DEMO_DESTRUCTIVE_ACTION":
        return
    confirmation_event = accepted_confirmations_by_id.get(str(authorization_event.get("caused_by_event_id")))
    confirmation_id = authorization_event.get("confirmation_id")
    if (
        confirmation_event is None
        or authorization_event.get("authorization_basis") != "current_plan_confirmation_acceptance"
        or confirmation_id in (None, "")
        or confirmation_event.get("confirmation_id") != confirmation_id
        or confirmation_event.get("task_id") != start_event.get("task_id")
        or confirmation_event.get("plan_version") != start_event.get("plan_version")
    ):
        raise ReplayValidationError(
            "DEMO_DESTRUCTIVE_ACTION requires current-plan CONFIRMATION_ACCEPTED before TOOL_EXECUTION_STARTED"
        )


def _tool_name_for_event(event: Mapping[str, Any], tool_names_by_call: Mapping[str, str]) -> str | None:
    bound_tool_name = tool_names_by_call.get(str(event["tool_call_id"]))
    tool_name = event.get("tool_name")
    if bound_tool_name is not None:
        if tool_name not in (None, "") and str(tool_name) != bound_tool_name:
            raise ReplayValidationError("TOOL_EXECUTION_STARTED tool_name must match TOOL_CALL_STARTED")
        return bound_tool_name
    if tool_name not in (None, ""):
        return str(tool_name)
    return None


def _tool_call_plan_key(event: Mapping[str, Any]) -> tuple[str, str, int]:
    return str(event["tool_call_id"]), str(event["task_id"]), int(event["plan_version"])


def _tool_call_task_key(event: Mapping[str, Any]) -> tuple[str, str]:
    return str(event["tool_call_id"]), str(event["task_id"])


def _require_source_id_in_refs(
    router_event: Mapping[str, Any],
    *,
    source_id_field: str,
    source_event_ids: set[str],
) -> None:
    expected_event_id = router_event.get(source_id_field)
    if expected_event_id in (None, "") or str(expected_event_id) not in source_event_ids:
        raise ReplayValidationError(f"USER_PATCH_RECEIVED evidence_pack must include router {source_id_field}")


def _string_set(value: object) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, (str, bytes)):
        return {str(value)}
    if not isinstance(value, Sequence):
        raise ReplayValidationError("USER_PATCH_RECEIVED source_event_ids must be a list")
    return {str(item) for item in value}


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
