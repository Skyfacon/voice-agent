from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlparse

from voice_agent.adapters.capabilities import CREDENTIAL_LIKE_REF_PATTERN, OUTPUT_MODES
from voice_agent.adapters.slow_llm_contract import SLOW_LLM_ALLOWED_SLOWTASK_BINDING_EVENTS
from voice_agent.composer.constants import (
    ALLOWED_PROGRESS_SOURCE_EVENTS,
    ALLOWED_SOURCE_MODULES_BY_EVENT,
    ALLOWED_TRUTHFULNESS_LEVELS,
)
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
from voice_agent.state.spoken_plan_check_state import SpokenPlanCheckState
from voice_agent.state.slowtask_state import SlowTaskState
from voice_agent.state.spoken_plan_state import SpokenPlanState
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
    spoken_plan_state: SpokenPlanState
    spoken_plan_check_state: SpokenPlanCheckState
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
        "audio_timestamps_ref",
        "semantic_frame_ref",
        "semantic_summary_ref",
        "semantic_close_ref",
        "assistant_directedness_ref",
        "emotion_ref",
        "audio_caption_ref",
        "slow_llm_output_ref",
        "structured_output_ref",
        "validation_result_ref",
        "synthesis_result_ref",
        "audio_summary_ref",
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
        "commitment_ref",
        "check_result_ref",
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
COMMITMENT_SYMBOLIC_METADATA_FIELDS = (
    "immutable_fields",
    "must_say_fields",
    "forbidden_rewrite_fields",
)
COMMITMENT_CHECK_EVENT_NAMES = frozenset(
    {
        "COMMITMENT_COVERAGE_CHECK_PASSED",
        "COMMITMENT_COVERAGE_CHECK_FAILED",
    }
)
PROGRESS_CHECK_EVENT_NAMES = frozenset(
    {
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
FAILED_CHECK_EVENT_NAMES = frozenset(
    {
        "COMMITMENT_COVERAGE_CHECK_FAILED",
        "PROGRESS_TRUTHFULNESS_CHECK_FAILED",
    }
)
CHECK_EVENT_NAMES = COMMITMENT_CHECK_EVENT_NAMES | PROGRESS_CHECK_EVENT_NAMES


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
    spoken_plan_state = SpokenPlanState()
    spoken_plan_check_state = SpokenPlanCheckState()

    for event in ordered_events:
        diagnostics["data_plane_refs"].extend(_unavailable_data_plane_refs(event))
        try:
            handled = [
                interaction_state.reduce_event(event),
                task_focus_state.reduce_event(event),
                slowtask_state.reduce_event(event),
                tool_execution_state.reduce_event(event),
                demo_ui_state.reduce_event(event),
                spoken_plan_state.reduce_event(event),
                spoken_plan_check_state.reduce_event(event),
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

    diagnostics["adapter_outcomes"] = adapter_health_state.to_digest_dict()

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
        spoken_plan_state=spoken_plan_state,
        spoken_plan_check_state=spoken_plan_check_state,
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
        spoken_plan_state=spoken_plan_state,
        spoken_plan_check_state=spoken_plan_check_state,
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
    _validate_asr_transcript_output_contract(ordered_events)
    _validate_thinker_semantic_frame_output_contract(ordered_events)
    _validate_slow_llm_structured_output_contract(ordered_events)
    _validate_tts_synthesis_output_contract(ordered_events)
    _validate_slowtask_spawn_voice_evidence_refs(ordered_events, manifest=manifest)
    _validate_user_patch_evidence_pack_source_links(ordered_events)
    _validate_tool_execution_gate_links(ordered_events)
    _validate_spoken_plan_source_links(ordered_events)
    _validate_composer_check_and_playback_links(ordered_events)
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
    events_by_id: dict[str, Mapping[str, Any]] = {}
    for event in ordered_events:
        if event.get("task_id") in (None, "") or event.get("task_event_seq") in (None, ""):
            events_by_id[str(event["event_id"])] = event
            continue
        task_id = str(event["task_id"])
        task_event_seq = int(event["task_event_seq"])
        latest_seq = latest_seq_by_task_id.get(task_id)
        if latest_seq is not None and task_event_seq <= latest_seq:
            if _is_slow_llm_adapter_seq_binding(event, events_by_id=events_by_id):
                events_by_id[str(event["event_id"])] = event
                continue
            raise ReplayValidationError(
                f"{event['event_name']} task_event_seq must increase monotonically per task_id"
            )
        latest_seq_by_task_id[task_id] = task_event_seq
        events_by_id[str(event["event_id"])] = event


def _is_slow_llm_adapter_seq_binding(
    event: Mapping[str, Any],
    *,
    events_by_id: Mapping[str, Mapping[str, Any]],
) -> bool:
    event_name = str(event["event_name"])
    if event_name != "SLOW_LLM_STRUCTURED_OUTPUT_EMITTED" and not (
        _is_slow_llm_structured_validation_failed_event(event)
    ):
        return False
    bound_event = events_by_id.get(str(event.get("caused_by_event_id", "")))
    if bound_event is None:
        return False
    if bound_event.get("event_name") not in SLOW_LLM_ALLOWED_SLOWTASK_BINDING_EVENTS:
        return False
    return all(
        event.get(field) == bound_event.get(field)
        for field in ("task_id", "plan_version", "task_event_seq")
    )


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
    asr_events: dict[tuple[str, str], str] = {}
    thinker_events: dict[tuple[str, str], str] = {}
    fast_interaction_events: dict[tuple[str, str], str] = {}

    for event in ordered_events:
        event_name = str(event["event_name"])
        if event_name == "TURN_INGRESS_COMMITTED":
            committed_turn_events[_turn_key(event)] = str(event["event_id"])
        elif event_name in {"MOCK_ASR_FRAME_EMITTED", "ASR_TRANSCRIPT_OUTPUT_EMITTED"}:
            key = _turn_key(event)
            committed_event_id = committed_turn_events.get(key)
            if committed_event_id is None:
                raise ReplayValidationError(f"{event_name} requires prior TURN_INGRESS_COMMITTED")
            if event.get("caused_by_event_id") != committed_event_id:
                raise ReplayValidationError(f"{event_name} must be caused by TURN_INGRESS_COMMITTED")
            asr_events[key] = str(event["event_id"])
        elif event_name in {"MOCK_THINKER_FRAME_EMITTED", "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED"}:
            key = _turn_key(event)
            committed_event_id = committed_turn_events.get(key)
            if committed_event_id is None:
                raise ReplayValidationError(f"{event_name} requires prior TURN_INGRESS_COMMITTED")
            if event.get("caused_by_event_id") != committed_event_id:
                raise ReplayValidationError(f"{event_name} must be caused by TURN_INGRESS_COMMITTED")
            thinker_events[key] = str(event["event_id"])
        elif event_name == "FAST_INTERACTION_OUTPUT_EMITTED":
            key = _turn_key(event)
            input_mode = _fast_interaction_input_mode(event)
            committed_event_id = committed_turn_events.get(key)
            if committed_event_id is None:
                raise ReplayValidationError(
                    "FAST_INTERACTION_OUTPUT_EMITTED requires prior TURN_INGRESS_COMMITTED"
                )
            if input_mode == "audio_native":
                if event.get("caused_by_event_id") != committed_event_id:
                    raise ReplayValidationError(
                        "audio-native FAST_INTERACTION_OUTPUT_EMITTED must be caused by TURN_INGRESS_COMMITTED"
                    )
            elif input_mode == "asr_text_fallback":
                asr_event_id = asr_events.get(key)
                if asr_event_id is None:
                    raise ReplayValidationError(
                        "ASR-text fallback FAST_INTERACTION_OUTPUT_EMITTED requires prior ASR evidence"
                    )
                if event.get("caused_by_event_id") != asr_event_id:
                    raise ReplayValidationError(
                        "ASR-text fallback FAST_INTERACTION_OUTPUT_EMITTED must be caused by prior ASR evidence"
                    )
            fast_interaction_events[key] = str(event["event_id"])
        elif event_name == "ROUTER_DECISION_EMITTED":
            key = _turn_key(event)
            if key not in committed_turn_events:
                raise ReplayValidationError("ROUTER_DECISION_EMITTED requires prior TURN_INGRESS_COMMITTED")
            asr_event_id = asr_events.get(key)
            thinker_event_id = thinker_events.get(key)
            fast_interaction_event_id = fast_interaction_events.get(key)
            if asr_event_id is None and thinker_event_id is None and fast_interaction_event_id is None:
                raise ReplayValidationError(
                    "ROUTER_DECISION_EMITTED requires prior MOCK_ASR_FRAME_EMITTED or "
                    "MOCK_THINKER_FRAME_EMITTED, ASR_TRANSCRIPT_OUTPUT_EMITTED, or "
                    "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED, or FAST_INTERACTION_OUTPUT_EMITTED"
                )
            if event.get("asr_frame_event_id") is not None and asr_event_id is None:
                raise ReplayValidationError(
                    "ROUTER_DECISION_EMITTED asr_frame_event_id requires prior mock ASR or ASR transcript evidence"
                )
            if event.get("asr_frame_event_id") not in (None, asr_event_id):
                raise ReplayValidationError("ROUTER_DECISION_EMITTED asr_frame_event_id must reference prior ASR evidence")
            if event.get("thinker_frame_event_id") is not None and thinker_event_id is None:
                raise ReplayValidationError(
                    "ROUTER_DECISION_EMITTED thinker_frame_event_id requires prior Thinker evidence"
                )
            if event.get("thinker_frame_event_id") not in (None, thinker_event_id):
                raise ReplayValidationError(
                    "ROUTER_DECISION_EMITTED thinker_frame_event_id must reference prior Thinker evidence"
                )
            if event.get("fast_interaction_output_event_id") is not None and fast_interaction_event_id is None:
                raise ReplayValidationError(
                    "ROUTER_DECISION_EMITTED fast_interaction_output_event_id requires prior Fast Interaction evidence"
                )
            if event.get("fast_interaction_output_event_id") not in (None, fast_interaction_event_id):
                raise ReplayValidationError(
                    "ROUTER_DECISION_EMITTED fast_interaction_output_event_id must reference prior Fast Interaction evidence"
                )


def _fast_interaction_input_mode(event: Mapping[str, Any]) -> str:
    fast_interaction_input_mode = event.get("fast_interaction_input_mode")
    input_mode = event.get("input_mode")
    if fast_interaction_input_mode in (None, "") and input_mode in (None, ""):
        raise ReplayValidationError("FAST_INTERACTION_OUTPUT_EMITTED requires input_mode")
    if (
        fast_interaction_input_mode not in (None, "")
        and input_mode not in (None, "")
        and fast_interaction_input_mode != input_mode
    ):
        raise ReplayValidationError(
            "FAST_INTERACTION_OUTPUT_EMITTED input_mode must match fast_interaction_input_mode"
        )
    resolved = str(fast_interaction_input_mode or input_mode)
    if resolved not in {"audio_native", "asr_text_fallback"}:
        raise ReplayValidationError("FAST_INTERACTION_OUTPUT_EMITTED has unsupported input_mode")
    return resolved


ASR_FORBIDDEN_PAYLOAD_FIELDS = frozenset(
    {
        "raw_audio",
        "audio_bytes",
        "audio_payload",
        "raw_trace",
        "raw_transcript",
        "raw_text",
        "transcript_text",
        "text",
        "provider_request",
        "provider_response",
        "provider_body",
        "provider_payload",
        "provider_schema",
        "provider_specific_schema",
        "request_body",
        "response_body",
        "body",
        "payload",
    }
)
ASR_SAFE_REF_FIELDS = frozenset(
    {
        "asr_frame_ref",
        "text_ref",
        "audio_timestamps_ref",
    }
)
ASR_UNSAFE_REF_TERMS = frozenset(
    {
        "raw_audio",
        "audio/raw",
        "raw transcript",
        "raw_transcript",
        "provider_request",
        "provider_response",
        "provider_payload",
        "provider schema",
        "provider_schema",
        "data:",
        "file://",
        "http://",
        "https://",
        "traces/",
        "diagnostics/",
        "replays/local",
        "/users/",
        "\\users\\",
    }
)


def _validate_asr_transcript_output_contract(ordered_events: Sequence[Mapping[str, Any]]) -> None:
    events_by_id: dict[str, Mapping[str, Any]] = {}
    degraded_by_request_capability: set[tuple[str, str, str]] = set()

    for event in ordered_events:
        event_name = str(event["event_name"])
        event_id = str(event["event_id"])
        if event_name == "ADAPTER_OUTPUT_DEGRADED" and event.get("adapter_type") == "asr":
            request_id = event.get("adapter_request_id")
            missing_capability = event.get("missing_capability")
            if request_id not in (None, "") and missing_capability not in (None, ""):
                degraded_by_request_capability.add(
                    (str(event["adapter_id"]), str(request_id), str(missing_capability))
                )

        if event_name != "ASR_TRANSCRIPT_OUTPUT_EMITTED":
            events_by_id[event_id] = event
            continue

        if ASR_FORBIDDEN_PAYLOAD_FIELDS.intersection(event):
            raise ReplayValidationError(
                "ASR_TRANSCRIPT_OUTPUT_EMITTED must not contain raw audio, transcript, or provider payload"
            )
        _validate_asr_safe_refs(event)
        output_mode = str(event["output_mode"])
        if output_mode not in {"real", "fallback", "degraded"}:
            raise ReplayValidationError("ASR_TRANSCRIPT_OUTPUT_EMITTED output_mode must be real, fallback, or degraded")

        turn_event = events_by_id.get(str(event["caused_by_event_id"]))
        if turn_event is None or turn_event["event_name"] != "TURN_INGRESS_COMMITTED":
            raise ReplayValidationError("ASR_TRANSCRIPT_OUTPUT_EMITTED requires prior TURN_INGRESS_COMMITTED")
        if turn_event.get("input_modality") != "audio":
            raise ReplayValidationError("ASR_TRANSCRIPT_OUTPUT_EMITTED requires committed audio turn metadata")
        for field in ("turn_id", "utterance_id", "audio_span_id", "input_modality"):
            if event.get(field) != turn_event.get(field):
                raise ReplayValidationError(f"ASR_TRANSCRIPT_OUTPUT_EMITTED {field} must match committed turn")

        _validate_asr_status_enum(
            event,
            status_field="timestamp_status",
            allowed_statuses={"available", "unavailable"},
        )
        _validate_asr_status_enum(
            event,
            status_field="streaming_status",
            allowed_statuses={"supported", "unsupported_final_only"},
        )
        _validate_asr_missing_capability_degradation(
            event,
            output_mode=output_mode,
            degraded_by_request_capability=degraded_by_request_capability,
            status_field="timestamp_status",
            missing_status="unavailable",
            missing_capability="supports_audio_timestamps",
        )
        _validate_asr_missing_capability_degradation(
            event,
            output_mode=output_mode,
            degraded_by_request_capability=degraded_by_request_capability,
            status_field="streaming_status",
            missing_status="unsupported_final_only",
            missing_capability="supports_streaming_output",
        )
        events_by_id[event_id] = event


def _validate_asr_safe_refs(event: Mapping[str, Any]) -> None:
    for field in ASR_SAFE_REF_FIELDS:
        value = event.get(field)
        if value in (None, ""):
            continue
        if not isinstance(value, str):
            raise ReplayValidationError(f"ASR_TRANSCRIPT_OUTPUT_EMITTED {field} must be a safe ref string")
        if any(_contains_unsafe_asr_ref_content(view) for view in _asr_ref_safety_views(value)):
            raise ReplayValidationError(f"ASR_TRANSCRIPT_OUTPUT_EMITTED {field} must be a safe ref")


def _asr_ref_safety_views(value: str) -> tuple[str, ...]:
    views = [value]
    decoded = value
    for _ in range(3):
        next_decoded = unquote(decoded)
        if next_decoded == decoded:
            break
        views.append(next_decoded)
        decoded = next_decoded
    return tuple(views)


def _contains_unsafe_asr_ref_content(value: str) -> bool:
    lowered = value.lower()
    return CREDENTIAL_LIKE_REF_PATTERN.search(value) is not None or any(
        term in lowered for term in ASR_UNSAFE_REF_TERMS
    ) or lowered.startswith(("/", "~/"))


def _validate_asr_status_enum(
    event: Mapping[str, Any],
    *,
    status_field: str,
    allowed_statuses: set[str],
) -> None:
    status = event.get(status_field)
    if status not in allowed_statuses:
        raise ReplayValidationError(
            f"ASR_TRANSCRIPT_OUTPUT_EMITTED {status_field} must be one of {sorted(allowed_statuses)}"
        )


def _validate_asr_missing_capability_degradation(
    event: Mapping[str, Any],
    *,
    output_mode: str,
    degraded_by_request_capability: set[tuple[str, str, str]],
    status_field: str,
    missing_status: str,
    missing_capability: str,
) -> None:
    if event.get(status_field) != missing_status:
        return
    if output_mode != "degraded":
        raise ReplayValidationError(
            f"ASR_TRANSCRIPT_OUTPUT_EMITTED {status_field}={missing_status} requires output_mode=degraded"
        )
    degradation_key = (
        str(event["adapter_id"]),
        str(event["adapter_request_id"]),
        missing_capability,
    )
    if degradation_key not in degraded_by_request_capability:
        raise ReplayValidationError(
            f"ASR_TRANSCRIPT_OUTPUT_EMITTED missing {missing_capability} requires prior ADAPTER_OUTPUT_DEGRADED"
        )


THINKER_OPTIONAL_STATUS_FIELDS = (
    (
        "semantic_close_status",
        "semantic_close_ref",
        "supports_semantic_close",
    ),
    (
        "assistant_directedness_status",
        "assistant_directedness_ref",
        "supports_assistant_directedness",
    ),
    (
        "emotion_status",
        "emotion_ref",
        "supports_emotion",
    ),
    (
        "audio_caption_status",
        "audio_caption_ref",
        "supports_audio_caption",
    ),
)


THINKER_FORBIDDEN_PAYLOAD_FIELDS = frozenset(
    {
        "raw_audio",
        "audio_bytes",
        "audio_payload",
        "raw_trace",
        "raw_thinker_output",
        "provider_response",
        "provider_payload",
        "provider_schema",
        "provider_specific_schema",
        "raw_semantic_frame",
        "raw_semantic_summary",
        "semantic_frame",
        "semantic_summary",
        "semantic_close",
        "assistant_directedness",
        "emotion",
        "audio_caption",
    }
)
THINKER_REF_FIELDS = (
    "semantic_frame_ref",
    "semantic_summary_ref",
    "semantic_close_ref",
    "assistant_directedness_ref",
    "emotion_ref",
    "audio_caption_ref",
)
THINKER_UNSAFE_REF_TERMS = (
    "audio/raw/",
    "diagnostics/",
    "traces/",
    "replays/local/",
    "raw_audio",
    "raw_trace",
    "raw_thinker_output",
    "http://",
    "https://",
    "file://",
    "provider-url://",
    "provider://",
    "dashscope",
    "aliyuncs.com",
)


def _validate_thinker_semantic_frame_output_contract(ordered_events: Sequence[Mapping[str, Any]]) -> None:
    events_by_id: dict[str, Mapping[str, Any]] = {}
    degraded_by_request_capability: set[tuple[str, str, str]] = set()

    for event in ordered_events:
        event_name = str(event["event_name"])
        event_id = str(event["event_id"])
        if event_name == "ADAPTER_OUTPUT_DEGRADED" and event.get("adapter_type") == "thinker":
            request_id = event.get("adapter_request_id")
            missing_capability = event.get("missing_capability")
            if request_id not in (None, "") and missing_capability not in (None, ""):
                degraded_by_request_capability.add(
                    (str(event["adapter_id"]), str(request_id), str(missing_capability))
                )

        if event_name != "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED":
            events_by_id[event_id] = event
            continue

        if _contains_forbidden_payload_field(event, forbidden_fields=THINKER_FORBIDDEN_PAYLOAD_FIELDS):
            raise ReplayValidationError(
                "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED must not contain provider-specific schema or raw payload"
            )
        output_mode = str(event["output_mode"])
        if output_mode not in {"real", "fallback", "degraded"}:
            raise ReplayValidationError(
                "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED output_mode must be real, fallback, or degraded"
            )

        turn_event = events_by_id.get(str(event["caused_by_event_id"]))
        if turn_event is None or turn_event["event_name"] != "TURN_INGRESS_COMMITTED":
            raise ReplayValidationError(
                "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED requires prior TURN_INGRESS_COMMITTED"
            )
        for field in ("turn_id", "utterance_id", "input_modality"):
            if event.get(field) != turn_event.get(field):
                raise ReplayValidationError(
                    f"THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED {field} must match committed turn"
                )
        for optional_turn_field in ("audio_span_id", "text_span_id"):
            if event.get(optional_turn_field) not in (None, "") and event.get(optional_turn_field) != turn_event.get(
                optional_turn_field
            ):
                raise ReplayValidationError(
                    f"THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED {optional_turn_field} must match committed turn"
                )

        for status_field, ref_field, missing_capability in THINKER_OPTIONAL_STATUS_FIELDS:
            _validate_thinker_status_enum(event, status_field=status_field)
            _validate_thinker_optional_ref_status(event, status_field=status_field, ref_field=ref_field)
            _validate_thinker_missing_capability_degradation(
                event,
                output_mode=output_mode,
                degraded_by_request_capability=degraded_by_request_capability,
                status_field=status_field,
                missing_capability=missing_capability,
            )
        _validate_thinker_refs_are_safe(event)
        events_by_id[event_id] = event


def _validate_thinker_status_enum(
    event: Mapping[str, Any],
    *,
    status_field: str,
) -> None:
    status = event.get(status_field)
    if status not in {"available", "unavailable"}:
        raise ReplayValidationError(
            f"THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED {status_field} must be available or unavailable"
        )


def _validate_thinker_optional_ref_status(
    event: Mapping[str, Any],
    *,
    status_field: str,
    ref_field: str,
) -> None:
    status = event.get(status_field)
    ref_value = event.get(ref_field)
    if status == "available" and ref_value in (None, ""):
        raise ReplayValidationError(
            f"THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED {status_field}=available requires {ref_field}"
        )
    if status == "unavailable" and ref_value not in (None, ""):
        raise ReplayValidationError(
            f"THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED {status_field}=unavailable must not include {ref_field}"
        )


def _validate_thinker_missing_capability_degradation(
    event: Mapping[str, Any],
    *,
    output_mode: str,
    degraded_by_request_capability: set[tuple[str, str, str]],
    status_field: str,
    missing_capability: str,
) -> None:
    if event.get(status_field) != "unavailable":
        return
    if output_mode != "degraded":
        raise ReplayValidationError(
            f"THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED {status_field}=unavailable requires output_mode=degraded"
        )
    degradation_key = (
        str(event["adapter_id"]),
        str(event["adapter_request_id"]),
        missing_capability,
    )
    if degradation_key not in degraded_by_request_capability:
        raise ReplayValidationError(
            f"THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED missing {missing_capability} requires prior ADAPTER_OUTPUT_DEGRADED"
        )


def _validate_thinker_refs_are_safe(event: Mapping[str, Any]) -> None:
    for field in THINKER_REF_FIELDS:
        value = event.get(field)
        if value in (None, ""):
            continue
        if not isinstance(value, str):
            raise ReplayValidationError(f"THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED {field} must be a string ref")
        if "://" not in value:
            raise ReplayValidationError(f"THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED {field} must be a safe ref")
        for view in _replay_ref_safety_views(value):
            lowered = view.lower()
            if (
                CREDENTIAL_LIKE_REF_PATTERN.search(view)
                or lowered.startswith(("/", "~", "\\"))
                or any(term in lowered for term in THINKER_UNSAFE_REF_TERMS)
            ):
                raise ReplayValidationError(
                    f"THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED {field} must be a safe ref; unsafe ref content detected"
                )


def _replay_ref_safety_views(value: str) -> tuple[str, ...]:
    views = [value]
    decoded = value
    for _ in range(3):
        next_decoded = unquote(decoded)
        if next_decoded == decoded:
            break
        views.append(next_decoded)
        decoded = next_decoded
    return tuple(views)


SLOW_LLM_STRUCTURED_OUTPUT_SCHEMA = "voice_agent.slowtask.structured_output.v1"
SLOW_LLM_FORBIDDEN_PAYLOAD_FIELDS = frozenset(
    {
        "raw_audio",
        "audio_bytes",
        "audio_payload",
        "raw_trace",
        "raw_slow_llm_output",
        "raw_structured_output",
        "provider_response",
        "provider_payload",
        "provider_schema",
        "provider_specific_schema",
        "provider_tool_calls",
        "structured_output",
        "resolved_arguments",
        "argument_provenance",
    }
)
SLOW_LLM_CONSUMER_EVENTS = frozenset(
    {
        "ARGUMENTS_RESOLVED",
        "ARGUMENT_RESOLUTION_PROVENANCE",
        "CLARIFICATION_REQUESTED",
        "SEMANTIC_COMMITMENT_EMITTED",
    }
)


def _validate_slow_llm_structured_output_contract(ordered_events: Sequence[Mapping[str, Any]]) -> None:
    events_by_id: dict[str, Mapping[str, Any]] = {}
    valid_outputs_by_id: dict[str, Mapping[str, Any]] = {}
    slow_llm_task_plan_keys: set[tuple[str, int]] = set()
    validation_failed_ids: set[str] = set()

    for event in ordered_events:
        event_name = str(event["event_name"])
        event_id = str(event["event_id"])

        if _is_slow_llm_structured_validation_failed_event(event):
            if event.get("output_mode") not in {"real", "fallback", "degraded"}:
                raise ReplayValidationError(
                    "ADAPTER_OUTPUT_VALIDATION_FAILED slow_llm output_mode must be real, fallback, or degraded"
                )
            _validate_slow_llm_validation_failure_event(event, events_by_id)
            slow_llm_task_plan_keys.add(_task_plan_key(event))
            validation_failed_ids.add(event_id)

        if event_name == "SLOW_LLM_STRUCTURED_OUTPUT_EMITTED":
            _validate_slow_llm_output_event(event, events_by_id)
            slow_llm_task_plan_keys.add(_task_plan_key(event))
            valid_outputs_by_id[event_id] = event

        if event_name in SLOW_LLM_CONSUMER_EVENTS:
            caused_by_event_id = str(event.get("caused_by_event_id", ""))
            if caused_by_event_id in validation_failed_ids:
                raise ReplayValidationError(
                    f"{event_name} must not consume Slow LLM validation failed output"
                )
            slow_llm_output = valid_outputs_by_id.get(caused_by_event_id)
            if event_name == "ARGUMENTS_RESOLVED" and _task_plan_key(event) in slow_llm_task_plan_keys:
                if slow_llm_output is None:
                    raise ReplayValidationError(
                        "ARGUMENTS_RESOLVED requires validated Slow LLM structured output"
                    )
                _validate_arguments_resolved_consumes_slow_llm_refs(event, slow_llm_output)

        events_by_id[event_id] = event


def _task_plan_key(event: Mapping[str, Any]) -> tuple[str, int]:
    return str(event["task_id"]), int(event["plan_version"])


def _is_slow_llm_structured_validation_failed_event(event: Mapping[str, Any]) -> bool:
    return (
        event.get("event_name") == "ADAPTER_OUTPUT_VALIDATION_FAILED"
        and event.get("adapter_type") == "slow_llm"
        and event.get("schema_name") == SLOW_LLM_STRUCTURED_OUTPUT_SCHEMA
    )


def _validate_slow_llm_validation_failure_event(
    event: Mapping[str, Any],
    events_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    bound_event = events_by_id.get(str(event.get("caused_by_event_id", "")))
    if bound_event is None:
        raise ReplayValidationError("ADAPTER_OUTPUT_VALIDATION_FAILED slow_llm requires prior SlowTask event")
    if bound_event.get("event_name") not in SLOW_LLM_ALLOWED_SLOWTASK_BINDING_EVENTS:
        raise ReplayValidationError(
            "ADAPTER_OUTPUT_VALIDATION_FAILED slow_llm requires prior allowed SlowTask event"
        )
    for field in ("task_id", "plan_version", "task_event_seq"):
        if event.get(field) != bound_event.get(field):
            raise ReplayValidationError(
                f"ADAPTER_OUTPUT_VALIDATION_FAILED slow_llm {field} must match bound SlowTask event"
            )
    failure_reasons = event.get("failure_reasons")
    if (
        not isinstance(failure_reasons, Sequence)
        or isinstance(failure_reasons, (str, bytes))
        or not failure_reasons
        or not all(isinstance(reason, str) and reason for reason in failure_reasons)
    ):
        raise ReplayValidationError(
            "ADAPTER_OUTPUT_VALIDATION_FAILED slow_llm failure_reasons must be non-empty strings"
        )
    if any(CREDENTIAL_LIKE_REF_PATTERN.search(reason) for reason in failure_reasons):
        raise ReplayValidationError(
            "ADAPTER_OUTPUT_VALIDATION_FAILED slow_llm failure_reasons must not contain credential-like content"
        )


def _validate_slow_llm_output_event(
    event: Mapping[str, Any],
    events_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    if _contains_forbidden_payload_field(event, forbidden_fields=SLOW_LLM_FORBIDDEN_PAYLOAD_FIELDS):
        raise ReplayValidationError(
            "SLOW_LLM_STRUCTURED_OUTPUT_EMITTED must not contain provider-specific schema or raw payload"
        )
    output_mode = str(event["output_mode"])
    if output_mode not in {"real", "fallback", "degraded"}:
        raise ReplayValidationError(
            "SLOW_LLM_STRUCTURED_OUTPUT_EMITTED output_mode must be real, fallback, or degraded"
        )
    if event.get("schema_name") != SLOW_LLM_STRUCTURED_OUTPUT_SCHEMA:
        raise ReplayValidationError("SLOW_LLM_STRUCTURED_OUTPUT_EMITTED schema_name must be system-owned")
    if event.get("normalization_status") != "normalized":
        raise ReplayValidationError("SLOW_LLM_STRUCTURED_OUTPUT_EMITTED must be normalized before SlowTask use")

    slowtask_event = events_by_id.get(str(event["caused_by_event_id"]))
    if slowtask_event is None:
        raise ReplayValidationError(
            "SLOW_LLM_STRUCTURED_OUTPUT_EMITTED requires prior SlowTask event"
        )
    if slowtask_event.get("event_name") not in SLOW_LLM_ALLOWED_SLOWTASK_BINDING_EVENTS:
        raise ReplayValidationError(
            "SLOW_LLM_STRUCTURED_OUTPUT_EMITTED requires prior allowed SlowTask event"
        )
    for field in ("task_id", "plan_version", "task_event_seq"):
        if event.get(field) != slowtask_event.get(field):
            raise ReplayValidationError(
                f"SLOW_LLM_STRUCTURED_OUTPUT_EMITTED {field} must match bound SlowTask event"
            )

    resolved_ref = event.get("resolved_arguments_ref")
    provenance_ref = event.get("provenance_ref")
    if (resolved_ref in (None, "")) != (provenance_ref in (None, "")):
        raise ReplayValidationError(
            "SLOW_LLM_STRUCTURED_OUTPUT_EMITTED resolved_arguments_ref and provenance_ref must be paired"
        )


def _contains_forbidden_payload_field(
    value: object,
    *,
    forbidden_fields: frozenset[str],
) -> bool:
    if isinstance(value, Mapping):
        for key, nested_value in value.items():
            if str(key) in forbidden_fields:
                return True
            if _contains_forbidden_payload_field(nested_value, forbidden_fields=forbidden_fields):
                return True
        return False
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return any(
            _contains_forbidden_payload_field(item, forbidden_fields=forbidden_fields)
            for item in value
        )
    return False


def _validate_arguments_resolved_consumes_slow_llm_refs(
    event: Mapping[str, Any],
    slow_llm_output: Mapping[str, Any],
) -> None:
    for field in ("task_id", "plan_version"):
        if event.get(field) != slow_llm_output.get(field):
            raise ReplayValidationError(
                f"ARGUMENTS_RESOLVED {field} must match referenced Slow LLM output"
            )
    for field in ("resolved_arguments_ref", "provenance_ref"):
        if field not in slow_llm_output:
            raise ReplayValidationError(
                f"ARGUMENTS_RESOLVED requires referenced Slow LLM output {field}"
            )
        if event.get(field) != slow_llm_output.get(field):
            raise ReplayValidationError(
                f"ARGUMENTS_RESOLVED {field} must match referenced Slow LLM output"
            )


TTS_SYNTHESIS_OUTPUT_EVENT_NAME = "TTS_SYNTHESIS_OUTPUT_EMITTED"
TTS_APPROVED_CHECK_EVENT_NAMES = frozenset(
    {
        "COMMITMENT_COVERAGE_CHECK_PASSED",
        "PROGRESS_TRUTHFULNESS_CHECK_PASSED",
    }
)
TTS_TRUNCATE_STATUSES = frozenset({"supported", "unsupported_blocked"})
TTS_FORBIDDEN_PAYLOAD_FIELDS = frozenset(
    {
        "raw_audio",
        "audio_bytes",
        "audio_payload",
        "raw_trace",
        "raw_tts_output",
        "raw_synthesis_output",
        "provider_response",
        "provider_payload",
        "provider_schema",
        "provider_specific_schema",
        "synthesis_result",
        "audio_samples",
        "wav_bytes",
        "pcm_bytes",
    }
)
TTS_SAFE_REF_FIELDS = frozenset(
    {
        "adapter_request_id",
        "audio_ref",
        "tts_stream_ref",
        "audio_format_ref",
        "synthesis_result_ref",
    }
)
TTS_UNSAFE_REF_TERMS = frozenset(
    {
        "raw_audio",
        "audio/raw",
        "data:",
        "traces/",
        "diagnostics/",
        "replays/local",
    }
)


def _validate_tts_synthesis_output_contract(ordered_events: Sequence[Mapping[str, Any]]) -> None:
    events_by_id: dict[str, Mapping[str, Any]] = {}
    tts_outputs_by_id: dict[str, Mapping[str, Any]] = {}
    tts_output_by_playback_span_id: dict[str, Mapping[str, Any]] = {}
    degraded_by_request_capability: set[tuple[str, str, str]] = set()
    tts_output_required_for_spoken_plan_playback = False

    for event in ordered_events:
        event_name = str(event["event_name"])
        event_id = str(event["event_id"])

        if event_name == "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED" and _snapshot_requires_tts_output_linkage(event):
            tts_output_required_for_spoken_plan_playback = True

        if event_name == "ADAPTER_OUTPUT_DEGRADED" and event.get("adapter_type") == "tts":
            request_id = event.get("adapter_request_id")
            missing_capability = event.get("missing_capability")
            if request_id not in (None, "") and missing_capability not in (None, ""):
                degraded_by_request_capability.add(
                    (str(event["adapter_id"]), str(request_id), str(missing_capability))
                )

        if event_name == TTS_SYNTHESIS_OUTPUT_EVENT_NAME:
            _validate_tts_output_event(
                event,
                events_by_id=events_by_id,
                degraded_by_request_capability=degraded_by_request_capability,
            )
            tts_outputs_by_id[event_id] = event
        elif event_name == "PLAYBACK_SPAN_STARTED":
            tts_output = _tts_output_for_playback(event, tts_outputs_by_id)
            if tts_output is None and _playback_requires_tts_output_linkage(
                event,
                tts_output_required_for_spoken_plan_playback=tts_output_required_for_spoken_plan_playback,
            ):
                raise ReplayValidationError(
                    "PLAYBACK_SPAN_STARTED for MVP-3 TTS playback must reference exactly one prior TTS output"
                )
            if tts_output is not None:
                _validate_playback_consumes_tts_refs(event, tts_output)
                tts_output_by_playback_span_id[str(event["playback_span_id"])] = tts_output
        elif event_name == "TTS_TRUNCATE_REQUESTED":
            tts_output = tts_output_by_playback_span_id.get(str(event["playback_span_id"]))
            if tts_output is not None and tts_output.get("truncate_status") == "unsupported_blocked":
                raise ReplayValidationError(
                    "TTS_TRUNCATE_REQUESTED cannot pass target validation when TTS truncate capability is blocked"
                )

        events_by_id[event_id] = event


def _validate_tts_output_event(
    event: Mapping[str, Any],
    *,
    events_by_id: Mapping[str, Mapping[str, Any]],
    degraded_by_request_capability: set[tuple[str, str, str]],
) -> None:
    if _contains_forbidden_payload_field(event, forbidden_fields=TTS_FORBIDDEN_PAYLOAD_FIELDS):
        raise ReplayValidationError(
            "TTS_SYNTHESIS_OUTPUT_EMITTED must not contain raw audio or provider-specific payload"
        )
    output_mode = str(event["output_mode"])
    if output_mode not in {"real", "fallback", "degraded"}:
        raise ReplayValidationError("TTS_SYNTHESIS_OUTPUT_EMITTED output_mode must be real, fallback, or degraded")
    if event.get("normalization_status") != "normalized":
        raise ReplayValidationError("TTS_SYNTHESIS_OUTPUT_EMITTED must be normalized before playback use")
    truncate_status = event.get("truncate_status")
    if truncate_status not in TTS_TRUNCATE_STATUSES:
        raise ReplayValidationError("TTS_SYNTHESIS_OUTPUT_EMITTED truncate_status must be supported or unsupported_blocked")

    _validate_tts_safe_refs(event)

    approved_check = events_by_id.get(str(event.get("caused_by_event_id", "")))
    if approved_check is None or approved_check.get("event_name") not in TTS_APPROVED_CHECK_EVENT_NAMES:
        raise ReplayValidationError("TTS_SYNTHESIS_OUTPUT_EMITTED requires prior passed SpokenPlan check event")
    if event.get("approved_check_event_id") != approved_check.get("event_id"):
        raise ReplayValidationError("TTS_SYNTHESIS_OUTPUT_EMITTED approved_check_event_id must match caused_by_event_id")
    if event.get("spoken_plan_id") != approved_check.get("spoken_plan_id"):
        raise ReplayValidationError("TTS_SYNTHESIS_OUTPUT_EMITTED spoken_plan_id must match approved check")
    for optional_field in ("task_id", "plan_version"):
        if event.get(optional_field) not in (None, "") and event.get(optional_field) != approved_check.get(optional_field):
            raise ReplayValidationError(f"TTS_SYNTHESIS_OUTPUT_EMITTED {optional_field} must match approved check")

    if truncate_status == "unsupported_blocked":
        if output_mode != "degraded":
            raise ReplayValidationError(
                "TTS_SYNTHESIS_OUTPUT_EMITTED unsupported truncate capability requires output_mode=degraded"
            )
        degradation_key = (
            str(event["adapter_id"]),
            str(event["adapter_request_id"]),
            "supports_tts_truncate",
        )
        if degradation_key not in degraded_by_request_capability:
            raise ReplayValidationError(
                "TTS_SYNTHESIS_OUTPUT_EMITTED missing truncate capability requires prior ADAPTER_OUTPUT_DEGRADED"
            )


def _validate_tts_safe_refs(event: Mapping[str, Any]) -> None:
    for field in TTS_SAFE_REF_FIELDS:
        value = event.get(field)
        if value in (None, ""):
            continue
        if not isinstance(value, str):
            raise ReplayValidationError(f"TTS_SYNTHESIS_OUTPUT_EMITTED {field} must be a safe ref string")
        if any(_contains_unsafe_tts_ref_content(view) for view in _tts_ref_safety_views(value)):
            raise ReplayValidationError(f"TTS_SYNTHESIS_OUTPUT_EMITTED {field} must be a safe ref")


def _validate_playback_consumes_tts_refs(
    playback_event: Mapping[str, Any],
    tts_output: Mapping[str, Any],
) -> None:
    if playback_event.get("caused_by_event_id") != tts_output.get("approved_check_event_id"):
        raise ReplayValidationError("PLAYBACK_SPAN_STARTED caused_by_event_id must match TTS approved check")
    if playback_event.get("spoken_plan_id") != tts_output.get("spoken_plan_id"):
        raise ReplayValidationError("PLAYBACK_SPAN_STARTED spoken_plan_id must match TTS output")
    if playback_event.get("approved_check_event_id") != tts_output.get("approved_check_event_id"):
        raise ReplayValidationError("PLAYBACK_SPAN_STARTED approved_check_event_id must match TTS output")
    consumed_ref_matched = False
    for ref_field in ("audio_ref", "tts_stream_ref"):
        playback_ref = playback_event.get(ref_field)
        if playback_ref in (None, ""):
            continue
        if playback_ref != tts_output.get(ref_field):
            raise ReplayValidationError(f"PLAYBACK_SPAN_STARTED {ref_field} must match TTS output")
        consumed_ref_matched = True
    if not consumed_ref_matched:
        raise ReplayValidationError("PLAYBACK_SPAN_STARTED must consume a TTS output ref")


def _tts_output_for_playback(
    playback_event: Mapping[str, Any],
    tts_outputs_by_id: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    tts_output_event_id = playback_event.get("tts_output_event_id")
    if tts_output_event_id not in (None, ""):
        tts_output = tts_outputs_by_id.get(str(tts_output_event_id))
        if tts_output is None:
            raise ReplayValidationError("PLAYBACK_SPAN_STARTED tts_output_event_id must reference prior TTS output")
        return tts_output

    matching_outputs = [
        tts_output
        for tts_output in tts_outputs_by_id.values()
        if _tts_output_refs_match_playback(playback_event, tts_output)
    ]
    if len(matching_outputs) > 1:
        raise ReplayValidationError("PLAYBACK_SPAN_STARTED TTS output refs are ambiguous without tts_output_event_id")
    if matching_outputs:
        return matching_outputs[0]
    return None


def _tts_output_refs_match_playback(
    playback_event: Mapping[str, Any],
    tts_output: Mapping[str, Any],
) -> bool:
    if playback_event.get("spoken_plan_id") != tts_output.get("spoken_plan_id"):
        return False
    if playback_event.get("approved_check_event_id") != tts_output.get("approved_check_event_id"):
        return False
    return any(
        playback_event.get(ref_field) not in (None, "")
        and playback_event.get(ref_field) == tts_output.get(ref_field)
        for ref_field in ("audio_ref", "tts_stream_ref")
    )


def _snapshot_requires_tts_output_linkage(event: Mapping[str, Any]) -> bool:
    if not str(event.get("capability_version", "")).startswith("mvp3."):
        return False
    adapter_types = _string_list_for_replay(event.get("adapter_types"))
    output_modes = _string_list_for_replay(event.get("output_modes"))
    return any(
        adapter_type == "tts" and output_mode != "mock"
        for adapter_type, output_mode in zip(adapter_types, output_modes, strict=False)
    )


def _playback_requires_tts_output_linkage(
    event: Mapping[str, Any],
    *,
    tts_output_required_for_spoken_plan_playback: bool,
) -> bool:
    if not tts_output_required_for_spoken_plan_playback:
        return False
    if event.get("approved_check_event_id") in (None, ""):
        return False
    return event.get("audio_ref") not in (None, "") or event.get("tts_stream_ref") not in (None, "")


def _tts_ref_safety_views(value: str) -> tuple[str, ...]:
    views = [value]
    decoded = value
    for _ in range(3):
        next_decoded = unquote(decoded)
        if next_decoded == decoded:
            break
        views.append(next_decoded)
        decoded = next_decoded
    return tuple(views)


def _contains_unsafe_tts_ref_content(value: str) -> bool:
    lowered = value.lower()
    return CREDENTIAL_LIKE_REF_PATTERN.search(value) is not None or any(
        term in lowered for term in TTS_UNSAFE_REF_TERMS
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
            _validate_user_patch_asr_evidence_matches_router(
                authoritative=authoritative,
                router_event=router_event,
                events_by_id=events_by_id,
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
            thinker_event = events_by_id.get(str(expected_thinker_event_id))
            if thinker_event is not None and thinker_event["event_name"] == "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED":
                if _contains_forbidden_payload_field(
                    hypothesis,
                    forbidden_fields=THINKER_FORBIDDEN_PAYLOAD_FIELDS,
                ):
                    raise ReplayValidationError(
                        "USER_PATCH_RECEIVED Thinker hypothesis must not contain provider-specific schema or raw payload"
                    )
                if hypothesis.get("semantic_frame_ref") != thinker_event.get("semantic_frame_ref"):
                    raise ReplayValidationError(
                        "USER_PATCH_RECEIVED semantic_frame_ref must match referenced Thinker output"
                    )
                if hypothesis.get("semantic_summary_ref") != thinker_event.get("semantic_summary_ref"):
                    raise ReplayValidationError(
                        "USER_PATCH_RECEIVED semantic_summary_ref must match referenced Thinker output"
                    )
                expected_hypothesis_refs = _hypothesis_ref_set(hypothesis)
                actual_hypothesis_refs = _string_set(event.get("non_authoritative_hypothesis_refs", ()))
                if actual_hypothesis_refs != expected_hypothesis_refs:
                    raise ReplayValidationError(
                        "USER_PATCH_RECEIVED non_authoritative_hypothesis_refs must match evidence_pack hypothesis refs"
                    )


def _validate_slowtask_spawn_voice_evidence_refs(
    ordered_events: Sequence[Mapping[str, Any]],
    *,
    manifest: ReplayManifest,
) -> None:
    if not _is_mvp4_fixture_manifest(manifest):
        return
    events_by_id = {str(event["event_id"]): event for event in ordered_events}
    expected_refs_by_task_id: dict[str, tuple[str, str]] = {}
    reviewed_tasks: set[str] = set()

    for event in ordered_events:
        event_name = str(event["event_name"])
        if event_name == "SLOWTASK_CREATED":
            router_event = events_by_id.get(str(event.get("caused_by_event_id")))
            if not _is_spawn_router_event_with_voice_evidence(router_event):
                continue
            expected_refs = _router_voice_evidence_refs(router_event, events_by_id)
            if expected_refs is None:
                continue
            _require_refs_contain(
                event.get("source_evidence_refs", ()),
                expected_refs=expected_refs,
                error_prefix="SLOWTASK_CREATED source_evidence_refs",
            )
            expected_refs_by_task_id[str(event["task_id"])] = expected_refs
            continue

        if event_name != "EVIDENCE_REVIEWED":
            continue
        task_id = str(event.get("task_id", ""))
        expected_refs = expected_refs_by_task_id.get(task_id)
        if expected_refs is None or task_id in reviewed_tasks:
            continue
        _require_refs_contain(
            event.get("evidence_refs", ()),
            expected_refs=expected_refs,
            error_prefix="EVIDENCE_REVIEWED evidence_refs",
        )
        reviewed_tasks.add(task_id)


def _is_mvp4_fixture_manifest(manifest: ReplayManifest) -> bool:
    return manifest.replay_id.startswith("replay_mvp4") or manifest.source_trace_ref.startswith("fixture://mvp4/")


def _is_spawn_router_event_with_voice_evidence(event: Mapping[str, Any] | None) -> bool:
    if event is None or event.get("event_name") != "ROUTER_DECISION_EMITTED":
        return False
    if event.get("router_decision") != "SPAWN_SLOW_TASK":
        return False
    return event.get("asr_frame_event_id") not in (None, "") and event.get("thinker_frame_event_id") not in (None, "")


def _router_voice_evidence_refs(
    router_event: Mapping[str, Any],
    events_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[str, str] | None:
    asr_event = events_by_id.get(str(router_event["asr_frame_event_id"]))
    thinker_event = events_by_id.get(str(router_event["thinker_frame_event_id"]))
    if asr_event is None or thinker_event is None:
        return None
    asr_ref = asr_event.get("asr_frame_ref")
    thinker_ref = thinker_event.get("semantic_frame_ref")
    if not isinstance(asr_ref, str) or asr_ref == "":
        return None
    if not isinstance(thinker_ref, str) or thinker_ref == "":
        return None
    return asr_ref, thinker_ref


def _require_refs_contain(
    refs: object,
    *,
    expected_refs: tuple[str, ...],
    error_prefix: str,
) -> None:
    actual_refs = _string_set_for_refs(refs, error_prefix=error_prefix)
    missing_refs = [ref for ref in expected_refs if ref not in actual_refs]
    if missing_refs:
        raise ReplayValidationError(f"{error_prefix} must contain Router voice evidence refs")


def _validate_user_patch_asr_evidence_matches_router(
    *,
    authoritative: Mapping[str, Any],
    router_event: Mapping[str, Any],
    events_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    expected_asr_event_id = router_event.get("asr_frame_event_id")
    if expected_asr_event_id in (None, ""):
        raise ReplayValidationError("USER_PATCH_RECEIVED ASR evidence requires router asr_frame_event_id")
    expected_asr_event_id = str(expected_asr_event_id)
    asr_event = events_by_id.get(expected_asr_event_id)
    if asr_event is None or asr_event.get("event_name") not in {
        "MOCK_ASR_FRAME_EMITTED",
        "ASR_TRANSCRIPT_OUTPUT_EMITTED",
    }:
        raise ReplayValidationError("USER_PATCH_RECEIVED ASR evidence must reference prior ASR output")

    if authoritative.get("asr_frame_ref") not in (None, ""):
        if authoritative.get("asr_frame_ref") != asr_event.get("asr_frame_ref"):
            raise ReplayValidationError(
                "USER_PATCH_RECEIVED asr_frame_ref must match referenced ASR output"
            )
    if authoritative.get("asr_text_ref") not in (None, ""):
        if authoritative.get("asr_text_ref") != asr_event.get("text_ref"):
            raise ReplayValidationError(
                "USER_PATCH_RECEIVED asr_text_ref must match referenced ASR output"
            )
    if authoritative.get("transcript_hint_ref") not in (None, "") and asr_event.get("text_ref") not in (None, ""):
        if authoritative.get("transcript_hint_ref") != asr_event.get("text_ref"):
            raise ReplayValidationError(
                "USER_PATCH_RECEIVED transcript_hint_ref must match referenced ASR output"
            )

    _validate_user_patch_asr_nbest_matches_router(
        authoritative.get("asr_nbest", ()),
        expected_asr_event_id=expected_asr_event_id,
        asr_event=asr_event,
        label="asr_nbest",
    )

    provenance = authoritative.get("provenance", {})
    if provenance not in (None, "") and not isinstance(provenance, Mapping):
        raise ReplayValidationError("USER_PATCH_RECEIVED ASR provenance must be an object")
    if isinstance(provenance, Mapping):
        _validate_user_patch_asr_nbest_matches_router(
            provenance.get("asr_nbest", ()),
            expected_asr_event_id=expected_asr_event_id,
            asr_event=asr_event,
            label="asr_nbest provenance",
        )


def _validate_user_patch_asr_nbest_matches_router(
    value: object,
    *,
    expected_asr_event_id: str,
    asr_event: Mapping[str, Any],
    label: str,
) -> None:
    if value in (None, ""):
        return
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ReplayValidationError(f"USER_PATCH_RECEIVED {label} must be a list")
    for item in value:
        if not isinstance(item, Mapping):
            raise ReplayValidationError(f"USER_PATCH_RECEIVED {label} entries must be objects")
        if str(item.get("source_event_id", "")) != expected_asr_event_id:
            raise ReplayValidationError(
                f"USER_PATCH_RECEIVED {label} source_event_id must match router asr_frame_event_id"
            )
        if item.get("text_ref") not in (None, "") and asr_event.get("text_ref") not in (None, ""):
            if item.get("text_ref") != asr_event.get("text_ref"):
                raise ReplayValidationError(
                    f"USER_PATCH_RECEIVED {label} text_ref must match referenced ASR output"
                )
        if item.get("evidence_ref") not in (None, "") and asr_event.get("asr_frame_ref") not in (None, ""):
            if item.get("evidence_ref") != asr_event.get("asr_frame_ref"):
                raise ReplayValidationError(
                    f"USER_PATCH_RECEIVED {label} evidence_ref must match referenced ASR output"
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
                events_by_id=events_by_id,
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


def _validate_spoken_plan_source_links(ordered_events: Sequence[Mapping[str, Any]]) -> None:
    events_by_id: dict[str, Mapping[str, Any]] = {}
    latest_plan_version_by_task_id: dict[str, int] = {}
    failed_check_event_names_by_spoken_plan_id = _failed_check_event_names_by_spoken_plan_id(ordered_events)
    passed_check_event_names_by_spoken_plan_id = _passed_check_event_names_by_spoken_plan_id(ordered_events)

    for event in ordered_events:
        event_name = str(event["event_name"])
        if event_name == "SPOKEN_PLAN_EMITTED":
            _validate_spoken_plan_event(
                event,
                events_by_id=events_by_id,
                latest_plan_version_by_task_id=latest_plan_version_by_task_id,
                failed_check_event_names_by_spoken_plan_id=failed_check_event_names_by_spoken_plan_id,
                passed_check_event_names_by_spoken_plan_id=passed_check_event_names_by_spoken_plan_id,
            )
        _record_latest_task_plan(event, latest_plan_version_by_task_id)
        events_by_id[str(event["event_id"])] = event


def _failed_check_event_names_by_spoken_plan_id(
    ordered_events: Sequence[Mapping[str, Any]],
) -> dict[str, frozenset[str]]:
    return _check_event_names_by_spoken_plan_id(ordered_events, event_names=FAILED_CHECK_EVENT_NAMES)


def _passed_check_event_names_by_spoken_plan_id(
    ordered_events: Sequence[Mapping[str, Any]],
) -> dict[str, frozenset[str]]:
    return _check_event_names_by_spoken_plan_id(ordered_events, event_names=PASSED_CHECK_EVENT_NAMES)


def _check_event_names_by_spoken_plan_id(
    ordered_events: Sequence[Mapping[str, Any]],
    *,
    event_names: frozenset[str],
) -> dict[str, frozenset[str]]:
    names_by_spoken_plan_id: dict[str, set[str]] = {}
    for event in ordered_events:
        if event["event_name"] not in event_names:
            continue
        spoken_plan_id = event.get("spoken_plan_id")
        if spoken_plan_id in (None, ""):
            continue
        names_by_spoken_plan_id.setdefault(str(spoken_plan_id), set()).add(str(event["event_name"]))
    return {
        spoken_plan_id: frozenset(event_names)
        for spoken_plan_id, event_names in names_by_spoken_plan_id.items()
    }


def _validate_composer_check_and_playback_links(ordered_events: Sequence[Mapping[str, Any]]) -> None:
    spoken_plans_by_id: dict[str, Mapping[str, Any]] = {}
    passed_checks_by_id: dict[str, Mapping[str, Any]] = {}
    failed_checks_by_id: dict[str, Mapping[str, Any]] = {}
    latest_plan_version_by_task_id: dict[str, int] = {}
    spoken_plan_event_ids: set[str] = set()

    for event in ordered_events:
        event_name = str(event["event_name"])
        if event_name == "SPOKEN_PLAN_EMITTED":
            spoken_plans_by_id[str(event["spoken_plan_id"])] = event
            spoken_plan_event_ids.add(str(event["event_id"]))
            _record_latest_task_plan(event, latest_plan_version_by_task_id)
            continue

        if event_name in CHECK_EVENT_NAMES:
            _validate_composer_check_event(
                event,
                spoken_plans_by_id=spoken_plans_by_id,
                latest_plan_version_by_task_id=latest_plan_version_by_task_id,
            )
            if event_name in PASSED_CHECK_EVENT_NAMES:
                passed_checks_by_id[str(event["event_id"])] = event
            else:
                failed_checks_by_id[str(event["event_id"])] = event
            _record_latest_task_plan(event, latest_plan_version_by_task_id)
            continue

        if event_name == "PLAYBACK_SPAN_STARTED":
            _validate_checked_playback_event(
                event,
                spoken_plans_by_id=spoken_plans_by_id,
                passed_checks_by_id=passed_checks_by_id,
                failed_checks_by_id=failed_checks_by_id,
                latest_plan_version_by_task_id=latest_plan_version_by_task_id,
                spoken_plan_event_ids=spoken_plan_event_ids,
            )
        _record_latest_task_plan(event, latest_plan_version_by_task_id)


def _validate_composer_check_event(
    event: Mapping[str, Any],
    *,
    spoken_plans_by_id: Mapping[str, Mapping[str, Any]],
    latest_plan_version_by_task_id: Mapping[str, int],
) -> None:
    if event.get("output_mode") not in OUTPUT_MODES:
        raise ReplayValidationError("checker event output_mode must be real, mock, fallback, or degraded")

    spoken_plan_id = str(event["spoken_plan_id"])
    spoken_plan = spoken_plans_by_id.get(spoken_plan_id)
    if spoken_plan is None:
        raise ReplayValidationError("checker event source spoken plan must exist and precede check")
    if event.get("caused_by_event_id") != spoken_plan.get("event_id"):
        raise ReplayValidationError("checker event caused_by_event_id must match source spoken plan")
    if event.get("task_id") != spoken_plan.get("task_id"):
        raise ReplayValidationError("checker event task_id must match source spoken plan")
    if event.get("plan_version") != spoken_plan.get("plan_version"):
        raise ReplayValidationError("checker event plan_version must match source spoken plan")

    latest_plan_version = latest_plan_version_by_task_id.get(str(spoken_plan["task_id"]))
    if latest_plan_version is not None and int(spoken_plan["plan_version"]) != latest_plan_version:
        raise ReplayValidationError("stale SpokenPlan cannot be checked after plan advance")

    event_name = str(event["event_name"])
    if event_name in COMMITMENT_CHECK_EVENT_NAMES:
        _validate_commitment_check_event(event, spoken_plan=spoken_plan)
    elif event_name in PROGRESS_CHECK_EVENT_NAMES:
        _validate_progress_check_event(event, spoken_plan=spoken_plan)


def _validate_commitment_check_event(
    event: Mapping[str, Any],
    *,
    spoken_plan: Mapping[str, Any],
) -> None:
    if event.get("source_module") != "coverage_checker":
        raise ReplayValidationError("commitment coverage check source_module must be coverage_checker")
    if spoken_plan.get("source") != "semantic_commitment":
        raise ReplayValidationError("coverage check requires semantic_commitment SpokenPlan source")
    expected_source_commitment_id = _check_source_commitment_id(spoken_plan)
    if event.get("source_commitment_id") != expected_source_commitment_id:
        raise ReplayValidationError("coverage check source_commitment_id must match SpokenPlan")
    if event["event_name"] == "COMMITMENT_COVERAGE_CHECK_PASSED":
        if not _string_list_for_replay(event.get("checked_fields")):
            raise ReplayValidationError("COMMITMENT_COVERAGE_CHECK_PASSED requires checked_fields")
        if event.get("check_result_ref") in (None, ""):
            raise ReplayValidationError("COMMITMENT_COVERAGE_CHECK_PASSED requires check_result_ref")
    else:
        if not _string_list_for_replay(event.get("failure_reasons")):
            raise ReplayValidationError("COMMITMENT_COVERAGE_CHECK_FAILED requires failure_reasons")


def _check_source_commitment_id(spoken_plan: Mapping[str, Any]) -> str:
    source_commitment_id = _optional_string_for_replay(spoken_plan.get("source_commitment_id"))
    if source_commitment_id is not None:
        return source_commitment_id
    return "missing_source_commitment_id"


def _validate_progress_check_event(
    event: Mapping[str, Any],
    *,
    spoken_plan: Mapping[str, Any],
) -> None:
    if event.get("source_module") != "truthfulness_checker":
        raise ReplayValidationError("progress truthfulness check source_module must be truthfulness_checker")
    if spoken_plan.get("source") != "grounded_progress":
        raise ReplayValidationError("truthfulness check requires grounded_progress SpokenPlan source")

    event_source_progress_ids = _string_list_for_replay(event.get("source_progress_event_ids"))
    spoken_source_progress_ids = _string_list_for_replay(spoken_plan.get("source_progress_event_ids"))
    if event_source_progress_ids != spoken_source_progress_ids:
        raise ReplayValidationError("truthfulness check source_progress_event_ids must match SpokenPlan")

    event_truthfulness_level = _optional_string_for_replay(event.get("truthfulness_level"))
    spoken_truthfulness_level = _optional_string_for_replay(spoken_plan.get("truthfulness_level"))
    if event_truthfulness_level != spoken_truthfulness_level:
        raise ReplayValidationError("truthfulness check truthfulness_level must match SpokenPlan")
    if event["event_name"] == "PROGRESS_TRUTHFULNESS_CHECK_PASSED":
        if event_truthfulness_level not in ALLOWED_TRUTHFULNESS_LEVELS:
            raise ReplayValidationError("truthfulness check truthfulness_level must be STATE_GROUNDED or STYLE_ONLY_ACK")
        if event.get("check_result_ref") in (None, ""):
            raise ReplayValidationError("PROGRESS_TRUTHFULNESS_CHECK_PASSED requires check_result_ref")
    else:
        if not _string_list_for_replay(event.get("failure_reasons")):
            raise ReplayValidationError("PROGRESS_TRUTHFULNESS_CHECK_FAILED requires failure_reasons")


def _validate_checked_playback_event(
    event: Mapping[str, Any],
    *,
    spoken_plans_by_id: Mapping[str, Mapping[str, Any]],
    passed_checks_by_id: Mapping[str, Mapping[str, Any]],
    failed_checks_by_id: Mapping[str, Mapping[str, Any]],
    latest_plan_version_by_task_id: Mapping[str, int],
    spoken_plan_event_ids: set[str],
) -> None:
    spoken_plan_id = event.get("spoken_plan_id")
    approved_check_event_id = event.get("approved_check_event_id")
    if spoken_plan_id in (None, ""):
        if approved_check_event_id not in (None, ""):
            raise ReplayValidationError("PLAYBACK_SPAN_STARTED approved_check_event_id requires spoken_plan_id")
        caused_by_event_id = event.get("caused_by_event_id")
        if (
            caused_by_event_id in spoken_plan_event_ids
            or caused_by_event_id in passed_checks_by_id
            or caused_by_event_id in failed_checks_by_id
        ):
            raise ReplayValidationError(
                "PLAYBACK_SPAN_STARTED requires spoken_plan_id and approved_check_event_id for SpokenPlan playback"
            )
        return

    spoken_plan_id = str(spoken_plan_id)
    spoken_plan = spoken_plans_by_id.get(spoken_plan_id)
    if spoken_plan is None:
        raise ReplayValidationError("PLAYBACK_SPAN_STARTED spoken_plan_id must reference a prior SpokenPlan")
    latest_plan_version = latest_plan_version_by_task_id.get(str(spoken_plan["task_id"]))
    if latest_plan_version is not None and int(spoken_plan["plan_version"]) != latest_plan_version:
        raise ReplayValidationError("stale SpokenPlan cannot authorize playback after plan advance")
    if approved_check_event_id in (None, ""):
        raise ReplayValidationError("PLAYBACK_SPAN_STARTED requires approved_check_event_id for SpokenPlan playback")
    approved_check_event_id = str(approved_check_event_id)
    if approved_check_event_id in failed_checks_by_id:
        raise ReplayValidationError("failed checker event cannot authorize playback")

    approved_check = passed_checks_by_id.get(approved_check_event_id)
    if approved_check is None:
        raise ReplayValidationError("approved_check_event_id must reference a passed checker event")
    if event.get("caused_by_event_id") != approved_check_event_id:
        raise ReplayValidationError("PLAYBACK_SPAN_STARTED caused_by_event_id must match approved_check_event_id")
    if approved_check.get("spoken_plan_id") != spoken_plan_id:
        raise ReplayValidationError("PLAYBACK_SPAN_STARTED spoken_plan_id must match approved checker event")

    spoken_source = spoken_plan.get("source")
    approved_event_name = approved_check.get("event_name")
    if spoken_source == "semantic_commitment" and approved_event_name != "COMMITMENT_COVERAGE_CHECK_PASSED":
        raise ReplayValidationError("commitment-derived playback requires COMMITMENT_COVERAGE_CHECK_PASSED")
    if spoken_source == "grounded_progress" and approved_event_name != "PROGRESS_TRUTHFULNESS_CHECK_PASSED":
        raise ReplayValidationError("progress-derived playback requires PROGRESS_TRUTHFULNESS_CHECK_PASSED")


def _validate_spoken_plan_event(
    event: Mapping[str, Any],
    *,
    events_by_id: Mapping[str, Mapping[str, Any]],
    latest_plan_version_by_task_id: Mapping[str, int],
    failed_check_event_names_by_spoken_plan_id: Mapping[str, frozenset[str]],
    passed_check_event_names_by_spoken_plan_id: Mapping[str, frozenset[str]],
) -> None:
    if event.get("source_module") != "composer":
        raise ReplayValidationError("SPOKEN_PLAN_EMITTED source_module must be composer")
    if event.get("output_mode") not in OUTPUT_MODES:
        raise ReplayValidationError("SPOKEN_PLAN_EMITTED output_mode must be real, mock, fallback, or degraded")

    source_event_ids = _string_list_for_replay(event.get("source_events"))
    if not source_event_ids:
        raise ReplayValidationError("SPOKEN_PLAN_EMITTED source_events are required")
    source_events = []
    for source_event_id in source_event_ids:
        source_event = events_by_id.get(source_event_id)
        if source_event is None:
            raise ReplayValidationError("SPOKEN_PLAN_EMITTED source event must exist and precede spoken plan")
        source_events.append(source_event)

    if event.get("caused_by_event_id") not in source_event_ids:
        raise ReplayValidationError("SPOKEN_PLAN_EMITTED caused_by_event_id must reference a source event")

    task_id = str(event["task_id"])
    plan_version = int(event["plan_version"])
    latest_plan_version = latest_plan_version_by_task_id.get(task_id)
    if latest_plan_version is not None and plan_version != latest_plan_version:
        raise ReplayValidationError("SPOKEN_PLAN_EMITTED plan_version must match current source plan_version")

    for source_event in source_events:
        if source_event.get("task_id") != task_id:
            raise ReplayValidationError("SPOKEN_PLAN_EMITTED task_id must match source event task_id")
        if source_event.get("plan_version") != plan_version:
            raise ReplayValidationError("SPOKEN_PLAN_EMITTED plan_version must match source event plan_version")

    source = event.get("source")
    spoken_plan_id = str(event["spoken_plan_id"])
    failure_check_names = failed_check_event_names_by_spoken_plan_id.get(spoken_plan_id, frozenset())
    passed_check_names = passed_check_event_names_by_spoken_plan_id.get(spoken_plan_id, frozenset())
    if source == "semantic_commitment":
        _validate_commitment_spoken_plan(
            event,
            source_events,
            allow_check_failure=(
                "COMMITMENT_COVERAGE_CHECK_FAILED" in failure_check_names
                and "COMMITMENT_COVERAGE_CHECK_PASSED" not in passed_check_names
            ),
        )
    elif source == "grounded_progress":
        _validate_progress_spoken_plan(
            event,
            source_event_ids,
            source_events,
            allow_check_failure=(
                "PROGRESS_TRUTHFULNESS_CHECK_FAILED" in failure_check_names
                and "PROGRESS_TRUTHFULNESS_CHECK_PASSED" not in passed_check_names
            ),
        )
    else:
        raise ReplayValidationError("SPOKEN_PLAN_EMITTED source must be semantic_commitment or grounded_progress")


def _validate_commitment_spoken_plan(
    event: Mapping[str, Any],
    source_events: Sequence[Mapping[str, Any]],
    *,
    allow_check_failure: bool,
) -> None:
    if len(source_events) != 1 or source_events[0].get("event_name") != "SEMANTIC_COMMITMENT_EMITTED":
        raise ReplayValidationError("commitment-derived SPOKEN_PLAN_EMITTED requires source commitment event")
    _validate_spoken_plan_source_event_module(source_events[0])
    source_commitment_id = event.get("source_commitment_id")
    violations: list[str] = []
    if source_commitment_id in (None, ""):
        violations.append("commitment-derived SPOKEN_PLAN_EMITTED requires source_commitment_id")
    elif source_commitment_id != source_events[0].get("commitment_id"):
        violations.append("SPOKEN_PLAN_EMITTED source_commitment_id must match commitment_id")
    if event.get("coverage_check_required") is not True:
        violations.append("commitment-derived SPOKEN_PLAN_EMITTED requires coverage_check_required=true")
    if event.get("truthfulness_check_required") is not False:
        violations.append("commitment-derived SPOKEN_PLAN_EMITTED must not require progress truthfulness")
    if _string_list_for_replay(event.get("source_progress_event_ids")):
        violations.append("commitment-derived SPOKEN_PLAN_EMITTED must not claim progress source ids")
    violations.extend(_commitment_symbolic_metadata_violations(event, source_events[0]))
    if violations and not allow_check_failure:
        raise ReplayValidationError(violations[0])


def _commitment_symbolic_metadata_violations(
    event: Mapping[str, Any],
    source_commitment: Mapping[str, Any],
) -> list[str]:
    violations: list[str] = []
    for field in COMMITMENT_SYMBOLIC_METADATA_FIELDS:
        spoken_values = _string_list_for_replay(event.get(field))
        commitment_values = _string_list_for_replay(source_commitment.get(field))
        if spoken_values != commitment_values:
            violations.append(
                f"commitment-derived SPOKEN_PLAN_EMITTED {field} must match source commitment"
            )
    return violations


def _validate_progress_spoken_plan(
    event: Mapping[str, Any],
    source_event_ids: Sequence[str],
    source_events: Sequence[Mapping[str, Any]],
    *,
    allow_check_failure: bool,
) -> None:
    violations: list[str] = []
    source_progress_event_ids = _string_list_for_replay(event.get("source_progress_event_ids"))
    if not source_progress_event_ids:
        violations.append("progress-derived SPOKEN_PLAN_EMITTED requires source_progress_event_ids")
    if list(source_progress_event_ids) != list(source_event_ids):
        violations.append("source_progress_event_ids must match SPOKEN_PLAN source_events")
    unsupported_sources = sorted(
        str(source_event["event_name"])
        for source_event in source_events
        if source_event["event_name"] not in ALLOWED_PROGRESS_SOURCE_EVENTS
    )
    if unsupported_sources:
        violations.append(f"unsupported progress source event for SPOKEN_PLAN_EMITTED: {unsupported_sources}")
    for source_event in source_events:
        try:
            _validate_spoken_plan_source_event_module(source_event)
        except ReplayValidationError as exc:
            violations.append(str(exc))
    if event.get("truthfulness_check_required") is not True:
        violations.append("progress-derived SPOKEN_PLAN_EMITTED requires truthfulness_check_required=true")
    if event.get("coverage_check_required") is not False:
        violations.append("progress-derived SPOKEN_PLAN_EMITTED must not require commitment coverage")
    truthfulness_level = event.get("truthfulness_level")
    if truthfulness_level not in ALLOWED_TRUTHFULNESS_LEVELS:
        violations.append("truthfulness_level must be STATE_GROUNDED or STYLE_ONLY_ACK")
    if event.get("source_commitment_id") not in (None, ""):
        violations.append("progress-derived SPOKEN_PLAN_EMITTED must not claim source_commitment_id")
    if violations and not allow_check_failure:
        raise ReplayValidationError(violations[0])


def _validate_spoken_plan_source_event_module(source_event: Mapping[str, Any]) -> None:
    event_name = str(source_event["event_name"])
    source_module = source_event.get("source_module")
    allowed_source_modules = ALLOWED_SOURCE_MODULES_BY_EVENT.get(event_name)
    if allowed_source_modules is None:
        raise ReplayValidationError(f"SPOKEN_PLAN source event {event_name} has no canonical source_module owner")
    if source_module not in allowed_source_modules:
        allowed = ", ".join(sorted(allowed_source_modules))
        raise ReplayValidationError(
            f"SPOKEN_PLAN source event {event_name} source_module must be {allowed}"
        )


def _record_latest_task_plan(
    event: Mapping[str, Any],
    latest_plan_version_by_task_id: dict[str, int],
) -> None:
    task_id = event.get("task_id")
    plan_version = event.get("plan_version")
    if task_id in (None, "") or not isinstance(plan_version, int) or isinstance(plan_version, bool):
        return
    previous_plan_version = latest_plan_version_by_task_id.get(str(task_id))
    if previous_plan_version is None or plan_version > previous_plan_version:
        latest_plan_version_by_task_id[str(task_id)] = plan_version


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
    events_by_id: Mapping[str, Mapping[str, Any]],
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
    received = events_by_id.get(str(confirmation_event.get("caused_by_event_id")))
    interpreted = events_by_id.get(str(received.get("caused_by_event_id"))) if received else None
    patch_received = events_by_id.get(str(interpreted.get("caused_by_event_id"))) if interpreted else None
    required = _matching_destructive_confirmation_required(
        events_by_id.values(),
        accepted=confirmation_event,
        start=start_event,
    )
    waiting = _matching_destructive_waiting_for_confirmation(
        events_by_id.values(),
        required=required,
        start=start_event,
        before_event=patch_received,
    )
    if not _matches_destructive_confirmation_chain(
        required=required,
        waiting=waiting,
        patch_received=patch_received,
        interpreted=interpreted,
        received=received,
        accepted=confirmation_event,
        authorization=authorization_event,
        start=start_event,
        events_by_id=events_by_id,
    ):
        raise ReplayValidationError("DEMO_DESTRUCTIVE_ACTION confirmation causal chain is broken")
    _validate_destructive_confirmation_required_for_event(
        required=required,
        start_event=start_event,
        events_by_id=events_by_id,
    )


def _matching_destructive_confirmation_required(
    events: Sequence[Mapping[str, Any]],
    *,
    accepted: Mapping[str, Any],
    start: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    matching_required: Mapping[str, Any] | None = None
    for event in events:
        if (
            _event_matches(
                event,
                event_name="CONFIRMATION_REQUIRED",
                task_id=start.get("task_id"),
                plan_version=start.get("plan_version"),
                confirmation_id=accepted.get("confirmation_id"),
                confirmation_scope="DEMO_DESTRUCTIVE_ACTION",
            )
            and _event_seq_before(event, accepted)
        ):
            matching_required = event
    return matching_required


def _matching_destructive_waiting_for_confirmation(
    events: Sequence[Mapping[str, Any]],
    *,
    required: Mapping[str, Any] | None,
    start: Mapping[str, Any],
    before_event: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    if required is None or before_event is None:
        return None
    matching_waiting: Mapping[str, Any] | None = None
    for event in events:
        if (
            _event_matches(
                event,
                event_name="WAITING_FOR_USER_CONFIRMATION",
                task_id=start.get("task_id"),
                plan_version=start.get("plan_version"),
                confirmation_id=required.get("confirmation_id"),
            )
            and event.get("caused_by_event_id") == required.get("event_id")
            and _event_seq_strictly_increases(required, event)
            and _event_seq_before(event, before_event)
        ):
            matching_waiting = event
    return matching_waiting


def _matches_destructive_confirmation_chain(
    *,
    required: Mapping[str, Any] | None,
    waiting: Mapping[str, Any] | None,
    patch_received: Mapping[str, Any] | None,
    interpreted: Mapping[str, Any] | None,
    received: Mapping[str, Any] | None,
    accepted: Mapping[str, Any],
    authorization: Mapping[str, Any],
    start: Mapping[str, Any],
    events_by_id: Mapping[str, Mapping[str, Any]],
) -> bool:
    patch_id = received.get("patch_id") if received is not None else None
    confirmation_id = accepted.get("confirmation_id")
    chain = (required, waiting, patch_received, interpreted, received, accepted, authorization, start)
    return bool(
        _event_matches(
            required,
            event_name="CONFIRMATION_REQUIRED",
            task_id=start.get("task_id"),
            plan_version=start.get("plan_version"),
            confirmation_id=confirmation_id,
            confirmation_scope="DEMO_DESTRUCTIVE_ACTION",
        )
        and _event_matches(
            waiting,
            event_name="WAITING_FOR_USER_CONFIRMATION",
            task_id=start.get("task_id"),
            plan_version=start.get("plan_version"),
            confirmation_id=confirmation_id,
        )
        and _event_matches(
            patch_received,
            event_name="USER_PATCH_RECEIVED",
            task_id=start.get("task_id"),
            plan_version=start.get("plan_version"),
            patch_id=patch_id,
            observed_plan_version=start.get("plan_version"),
        )
        and _event_matches(
            interpreted,
            event_name="USER_PATCH_INTERPRETED",
            task_id=start.get("task_id"),
            plan_version=start.get("plan_version"),
            patch_id=patch_id,
            observed_plan_version=start.get("plan_version"),
            interpreted_against_plan_version=start.get("plan_version"),
            interpretation_type="confirmation",
        )
        and _event_matches(
            received,
            event_name="USER_CONFIRMATION_RECEIVED",
            task_id=start.get("task_id"),
            plan_version=start.get("plan_version"),
            confirmation_id=confirmation_id,
            patch_id=patch_id,
            confirmation_signal="accepted",
        )
        and _event_matches(
            accepted,
            event_name="CONFIRMATION_ACCEPTED",
            task_id=start.get("task_id"),
            plan_version=start.get("plan_version"),
            confirmation_id=confirmation_id,
            accepted_scope="DEMO_DESTRUCTIVE_ACTION",
        )
        and _causal_chain_matches(required, waiting)
        and _patch_received_is_caused_by_confirmation_path(
            patch_received,
            waiting=waiting,
            start=start,
            events_by_id=events_by_id,
        )
        and _causal_chain_matches(patch_received, interpreted, received, accepted, authorization, start)
        and _event_seq_strictly_increases(*chain)
    )


def _patch_received_is_caused_by_confirmation_path(
    patch_received: Mapping[str, Any] | None,
    *,
    waiting: Mapping[str, Any] | None,
    start: Mapping[str, Any],
    events_by_id: Mapping[str, Mapping[str, Any]],
) -> bool:
    if patch_received is None or waiting is None:
        return False
    caused_by_event_id = patch_received.get("caused_by_event_id")
    router_event = events_by_id.get(str(caused_by_event_id))
    return bool(
        _event_matches(
            router_event,
            event_name="ROUTER_DECISION_EMITTED",
            router_decision="PATCH_ACTIVE_SLOW_TASK",
            task_focus="ACTIVE_TASK_PATCH",
            active_task_id=start.get("task_id"),
        )
        and _confirmation_router_has_turn_evidence(
            router_event,
            waiting=waiting,
            events_by_id=events_by_id,
        )
        and _event_seq_strictly_increases(waiting, router_event, patch_received)
    )


def _validate_destructive_confirmation_required_for_event(
    *,
    required: Mapping[str, Any] | None,
    start_event: Mapping[str, Any],
    events_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    if required is None:
        raise ReplayValidationError("DEMO_DESTRUCTIVE_ACTION confirmation required_for_event_id is missing")
    required_for_event_id = required.get("required_for_event_id")
    if required_for_event_id in (None, "") or required.get("caused_by_event_id") != required_for_event_id:
        raise ReplayValidationError(
            "DEMO_DESTRUCTIVE_ACTION confirmation required_for_event_id must match caused_by_event_id"
        )
    required_for_event = events_by_id.get(str(required_for_event_id))
    if (
        required_for_event is None
        or required_for_event.get("event_name") != "TOOL_PREVIEW_AVAILABLE"
        or required_for_event.get("task_id") != start_event.get("task_id")
        or required_for_event.get("plan_version") != start_event.get("plan_version")
        or required_for_event.get("tool_call_id") != start_event.get("tool_call_id")
        or required_for_event.get("tool_name") != start_event.get("tool_name")
    ):
        raise ReplayValidationError(
            "DEMO_DESTRUCTIVE_ACTION confirmation required_for_event_id must bind the pending tool request"
        )
    preview_arguments = events_by_id.get(str(required_for_event.get("caused_by_event_id")))
    if not _matches_tool_arguments_ready(
        preview_arguments,
        required_for_event=required_for_event,
    ):
        raise ReplayValidationError(
            "DEMO_DESTRUCTIVE_ACTION confirmation required_for_event_id must bind the previewed arguments"
        )
    preview_fingerprint = preview_arguments.get("argument_fingerprint")
    if (
        preview_fingerprint in (None, "")
        or required_for_event.get("argument_fingerprint") != preview_fingerprint
    ):
        raise ReplayValidationError(
            "DEMO_DESTRUCTIVE_ACTION confirmation required_for_event_id must bind the previewed arguments"
        )
    for event in events_by_id.values():
        if (
            event.get("event_name") == "TOOL_ARGUMENTS_READY"
            and event.get("task_id") == start_event.get("task_id")
            and event.get("plan_version") == start_event.get("plan_version")
            and event.get("tool_call_id") == start_event.get("tool_call_id")
            and event.get("tool_name") == start_event.get("tool_name")
            and _event_seq_before(required_for_event, event)
            and _event_seq_before(event, start_event)
            and (
                event.get("resolved_arguments_ref") != preview_arguments.get("resolved_arguments_ref")
                or event.get("provenance_ref") != preview_arguments.get("provenance_ref")
                or event.get("argument_fingerprint") != preview_fingerprint
            )
        ):
            raise ReplayValidationError(
                "DEMO_DESTRUCTIVE_ACTION confirmation required_for_event_id must bind the previewed arguments"
    )


def _confirmation_router_has_turn_evidence(
    router_event: Mapping[str, Any] | None,
    *,
    waiting: Mapping[str, Any],
    events_by_id: Mapping[str, Mapping[str, Any]],
) -> bool:
    if router_event is None:
        return False
    turn_event = events_by_id.get(str(router_event.get("turn_committed_event_id")))
    thinker_event = events_by_id.get(str(router_event.get("thinker_frame_event_id")))
    return bool(
        _event_matches(
            turn_event,
            event_name="TURN_INGRESS_COMMITTED",
            turn_id=router_event.get("turn_id"),
            utterance_id=router_event.get("utterance_id"),
        )
        and _event_matches(
            thinker_event,
            event_name="MOCK_THINKER_FRAME_EMITTED",
            turn_id=router_event.get("turn_id"),
            utterance_id=router_event.get("utterance_id"),
        )
        and turn_event.get("caused_by_event_id") == waiting.get("event_id")
        and thinker_event.get("caused_by_event_id") == turn_event.get("event_id")
        and router_event.get("caused_by_event_id") == thinker_event.get("event_id")
        and _event_seq_strictly_increases(waiting, turn_event, thinker_event, router_event)
    )


def _matches_tool_arguments_ready(
    event: Mapping[str, Any] | None,
    *,
    required_for_event: Mapping[str, Any],
) -> bool:
    return bool(
        event is not None
        and event.get("event_name") == "TOOL_ARGUMENTS_READY"
        and event.get("task_id") == required_for_event.get("task_id")
        and event.get("plan_version") == required_for_event.get("plan_version")
        and event.get("tool_call_id") == required_for_event.get("tool_call_id")
        and event.get("tool_name") == required_for_event.get("tool_name")
        and event.get("resolved_arguments_ref") not in (None, "")
        and event.get("provenance_ref") not in (None, "")
        and event.get("argument_fingerprint") not in (None, "")
    )


def _event_seq_before(event: Mapping[str, Any] | None, before_event: Mapping[str, Any] | None) -> bool:
    if event is None or before_event is None:
        return False
    event_seq = event.get("event_seq")
    before_event_seq = before_event.get("event_seq")
    return (
        isinstance(event_seq, int)
        and not isinstance(event_seq, bool)
        and isinstance(before_event_seq, int)
        and not isinstance(before_event_seq, bool)
        and event_seq < before_event_seq
    )


def _event_matches(event: Mapping[str, Any] | None, /, **expected_fields: object) -> bool:
    if event is None:
        return False
    return all(event.get(field_name) == expected_value for field_name, expected_value in expected_fields.items())


def _causal_chain_matches(*events: Mapping[str, Any] | None) -> bool:
    previous_event_id: object | None = None
    for event in events:
        if event is None:
            return False
        if previous_event_id is not None and event.get("caused_by_event_id") != previous_event_id:
            return False
        previous_event_id = event.get("event_id")
        if previous_event_id in (None, ""):
            return False
    return True


def _event_seq_strictly_increases(*events: Mapping[str, Any] | None) -> bool:
    previous_event_seq: int | None = None
    for event in events:
        if event is None:
            return False
        event_seq = event.get("event_seq")
        if not isinstance(event_seq, int) or isinstance(event_seq, bool):
            return False
        if previous_event_seq is not None and event_seq <= previous_event_seq:
            return False
        previous_event_seq = event_seq
    return True


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


def _hypothesis_ref_set(hypothesis: Mapping[str, Any]) -> set[str]:
    return {
        str(value)
        for field in ("semantic_frame_ref", "semantic_summary_ref", "audio_summary_ref")
        if (value := hypothesis.get(field)) not in (None, "")
    }


def _string_list_for_replay(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        return [str(value)]
    if not isinstance(value, Sequence):
        raise ReplayValidationError("event ids must be a list")
    return [str(item) for item in value]


def _optional_string_for_replay(value: object) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _string_set(value: object) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, (str, bytes)):
        return {str(value)}
    if not isinstance(value, Sequence):
        raise ReplayValidationError("USER_PATCH_RECEIVED source_event_ids must be a list")
    return {str(item) for item in value}


def _string_set_for_refs(value: object, *, error_prefix: str) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, (str, bytes)):
        return {str(value)}
    if not isinstance(value, Sequence):
        raise ReplayValidationError(f"{error_prefix} must be a list")
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
