from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import math
import re
from typing import Any
from urllib.parse import unquote, urlparse

from voice_agent.adapters.capabilities import CREDENTIAL_LIKE_REF_PATTERN, OUTPUT_MODES
from voice_agent.adapters.route_evidence_contract import (
    CANDIDATE_SAFETY_CONFIDENCE_THRESHOLD,
    MAX_CANDIDATE_UNICODE_SCALARS,
    ROUTE_CONFIDENCE_THRESHOLD,
    CandidateSafetyEvidenceV1,
    RouteEvidenceContractError,
    RouteEvidenceOutputV1,
)
from voice_agent.adapters.slow_llm_contract import SLOW_LLM_ALLOWED_SLOWTASK_BINDING_EVENTS
from voice_agent.composer.constants import (
    ALLOWED_PROGRESS_SOURCE_EVENTS,
    ALLOWED_SOURCE_MODULES_BY_EVENT,
    ALLOWED_TRUTHFULNESS_LEVELS,
)
from voice_agent.events.envelope import (
    COMMON_ENVELOPE_FIELDS,
    EventValidationError,
    validate_event_envelope,
)
from voice_agent.events.registry import (
    ADR018_EVENT_NAMES,
    MVP1_EVENT_NAMES,
    get_event_definition,
)
from voice_agent.privacy.redaction import (
    PayloadBlockedError,
    sanitize_event_payload,
)
from voice_agent.replay.manifest import ReplayManifest, validate_replay_manifest
from voice_agent.replay.state_digest import state_digest
from voice_agent.runtime.foreground_template_catalog import resolve_foreground_template
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
from voice_agent.state.qwen_parallel_state import QwenParallelState
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
    qwen_parallel_state: QwenParallelState
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
        "projection_ref",
        "facts_ref",
        "must_say_fields_ref",
        "forbidden_claims_ref",
        "independent_transcript_ref",
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
    qwen_parallel_state = QwenParallelState()

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
                qwen_parallel_state.reduce_event(event),
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
        foreground_authority=_stable_foreground_authority(ordered_events),
        qwen_parallel_state=(
            qwen_parallel_state
            if qwen_parallel_state.saw_adr018_event
            else None
        ),
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
        qwen_parallel_state=qwen_parallel_state,
        playback_state=playback_state,
        adapter_health_state=adapter_health_state,
        trace_privacy_state=trace_privacy_state,
        diagnostics=diagnostics,
        state_digest=digest,
        result_status=result_status,
    )


def _validate_and_order_events(raw_events: Sequence[object], *, manifest: ReplayManifest) -> list[dict[str, Any]]:
    is_adr018_session = any(
        isinstance(raw_event, Mapping)
        and _raw_event_is_adr018(raw_event)
        for raw_event in raw_events
    )
    if is_adr018_session:
        _validate_adr018_raw_canonical_value(raw_events)
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
    _validate_per_turn_authority_cardinality(ordered_events)
    _validate_router_decision_scope(ordered_events, manifest=manifest)
    _validate_task_focus_state_update_causality(ordered_events)
    _validate_task_focus_active_task_creation_order(ordered_events)
    _validate_post_commit_understanding_and_router_order(ordered_events)
    _validate_asr_transcript_output_contract(ordered_events)
    _validate_adr018_parallel_chain(ordered_events)
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


def _validate_unique_event_ids(
    ordered_events: Sequence[Mapping[str, Any]],
) -> None:
    seen: set[str] = set()
    for event in ordered_events:
        event_id = str(event["event_id"])
        if event_id in seen:
            raise ReplayValidationError(f"Duplicate event_id: {event_id}")
        seen.add(event_id)


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
            if (
                _is_slow_llm_adapter_seq_binding(
                    event,
                    events_by_id=events_by_id,
                )
                or _is_adr018_handoff_seq_binding(
                    event,
                    events_by_id=events_by_id,
                )
            ):
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


def _is_adr018_handoff_seq_binding(
    event: Mapping[str, Any],
    *,
    events_by_id: Mapping[str, Mapping[str, Any]],
) -> bool:
    if event.get("event_name") != "SLOW_TO_FAST_HANDOFF_EMITTED":
        return False
    source_event_ids = event.get("source_event_ids")
    if (
        not isinstance(source_event_ids, (list, tuple))
        or not source_event_ids
    ):
        return False
    source_events = [
        events_by_id.get(str(source_event_id))
        for source_event_id in source_event_ids
    ]
    return (
        all(
            source_event is not None
            and event.get("task_id") == source_event.get("task_id")
            and event.get("plan_version") == source_event.get("plan_version")
            and isinstance(source_event.get("task_event_seq"), int)
            and not isinstance(source_event.get("task_event_seq"), bool)
            and int(source_event["task_event_seq"])
            <= int(event["task_event_seq"])
            for source_event in source_events
        )
        and any(
            source_event is not None
            and source_event.get("task_event_seq")
            == event.get("task_event_seq")
            for source_event in source_events
        )
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


def _validate_per_turn_authority_cardinality(
    ordered_events: Sequence[Mapping[str, Any]],
) -> None:
    events_by_id = {
        str(event["event_id"]): event
        for event in ordered_events
    }
    router_events_by_id: dict[str, Mapping[str, Any]] = {}
    router_event_ids_by_turn: dict[tuple[str, str], str] = {}
    terminal_gate_event_ids_by_router: dict[str, str] = {}
    terminal_gate_event_ids_by_turn: dict[tuple[str, str], str] = {}
    foreground_commit_event_ids_by_turn: dict[tuple[str, str], str] = {}
    spawn_event_ids_by_turn: dict[tuple[str, str], str] = {}
    patch_event_ids_by_turn: dict[tuple[str, str], str] = {}

    for event in ordered_events:
        event_name = str(event["event_name"])
        event_id = str(event["event_id"])
        if event_name == "ROUTER_DECISION_EMITTED":
            key = _turn_key(event)
            if not _is_legacy_confirmed_switch_spawn_continuation(
                event,
                events_by_id=events_by_id,
            ):
                _record_single_authority_event(
                    router_event_ids_by_turn,
                    key,
                    event_id,
                    label="ROUTER_DECISION_EMITTED for turn_id and utterance_id",
                )
            router_events_by_id[event_id] = event
            continue

        if event_name in {"FOREGROUND_ACT_GATE_PASSED", "FOREGROUND_ACT_GATE_FAILED"}:
            router_event_id = str(event.get("router_decision_event_id", ""))
            router_event = router_events_by_id.get(router_event_id)
            if router_event is None:
                continue
            key = _turn_key(router_event)
            _record_single_authority_event(
                terminal_gate_event_ids_by_router,
                router_event_id,
                event_id,
                label="terminal foreground Gate for Router",
            )
            _record_single_authority_event(
                terminal_gate_event_ids_by_turn,
                key,
                event_id,
                label="terminal foreground Gate for turn_id and utterance_id",
            )
            continue

        if event_name == "FOREGROUND_OUTPUT_COMMITTED":
            _record_single_authority_event(
                foreground_commit_event_ids_by_turn,
                _turn_key(event),
                event_id,
                label="FOREGROUND_OUTPUT_COMMITTED for turn_id and utterance_id",
            )
            continue

        if event_name == "SLOWTASK_CREATED":
            router_event = router_events_by_id.get(str(event.get("caused_by_event_id", "")))
            if router_event is None or router_event.get("router_decision") != "SPAWN_SLOW_TASK":
                continue
            _record_single_authority_event(
                spawn_event_ids_by_turn,
                _turn_key(router_event),
                event_id,
                label="SPAWN mutation initiation for turn_id and utterance_id",
            )
            continue

        if event_name == "USER_PATCH_RECEIVED":
            router_event = router_events_by_id.get(str(event.get("caused_by_event_id", "")))
            if router_event is None or router_event.get("router_decision") != "PATCH_ACTIVE_SLOW_TASK":
                continue
            _record_single_authority_event(
                patch_event_ids_by_turn,
                _turn_key(router_event),
                event_id,
                label="PATCH/UserPatch mutation initiation for turn_id and utterance_id",
            )


def _record_single_authority_event(
    seen: dict[Any, str],
    key: Any,
    event_id: str,
    *,
    label: str,
) -> None:
    prior_event_id = seen.get(key)
    if prior_event_id is not None:
        raise ReplayValidationError(
            f"{label} must occur at most once; found {prior_event_id} and {event_id}"
        )
    seen[key] = event_id


def _is_legacy_confirmed_switch_spawn_continuation(
    event: Mapping[str, Any],
    *,
    events_by_id: Mapping[str, Mapping[str, Any]],
) -> bool:
    if event.get("router_decision") != "SPAWN_SLOW_TASK":
        return False
    focus_event = events_by_id.get(str(event.get("caused_by_event_id", "")))
    if (
        focus_event is None
        or focus_event.get("event_name") != "TASK_FOCUS_STATE_UPDATED"
        or focus_event.get("active_task_id") is not None
        or focus_event.get("foreground_mode") != "IDLE"
        or focus_event.get("default_patch_policy") != "NO_ACTIVE_TASK"
    ):
        return False
    prior_routers = [
        prior
        for prior in events_by_id.values()
        if prior.get("event_name") == "ROUTER_DECISION_EMITTED"
        and prior.get("event_id") != event.get("event_id")
        and _turn_key(prior) == _turn_key(event)
        and _event_seq_before(prior, event)
    ]
    if len(prior_routers) != 1:
        return False
    prior_router = prior_routers[0]
    task_id = prior_router.get("active_task_id")
    if (
        task_id in (None, "")
        or prior_router.get("router_decision") != "PATCH_ACTIVE_SLOW_TASK"
        or prior_router.get("task_focus") != "NEW_TASK_CANDIDATE"
        or any(
            event.get(field) != prior_router.get(field)
            for field in (
                "turn_committed_event_id",
                "asr_frame_event_id",
                "thinker_frame_event_id",
            )
        )
    ):
        return False

    initial_patch = _unique_event_caused_by(
        events_by_id,
        event_name="USER_PATCH_RECEIVED",
        caused_by_event_id=prior_router.get("event_id"),
    )
    initial_interpreted = _unique_event_caused_by(
        events_by_id,
        event_name="USER_PATCH_INTERPRETED",
        caused_by_event_id=_event_id(initial_patch),
    )
    required = _unique_event_caused_by(
        events_by_id,
        event_name="CONFIRMATION_REQUIRED",
        caused_by_event_id=_event_id(initial_interpreted),
    )
    waiting = _unique_event_caused_by(
        events_by_id,
        event_name="WAITING_FOR_USER_CONFIRMATION",
        caused_by_event_id=_event_id(required),
    )
    waiting_state = _unique_event_caused_by(
        events_by_id,
        event_name="SLOWTASK_STATE_CHANGED",
        caused_by_event_id=_event_id(waiting),
    )
    confirmation_turn = _unique_event_caused_by(
        events_by_id,
        event_name="TURN_INGRESS_COMMITTED",
        caused_by_event_id=_event_id(waiting_state),
    )
    confirmation_router = events_by_id.get(
        str(focus_event.get("router_decision_event_id", ""))
    )
    confirmation_thinker = events_by_id.get(
        str(
            confirmation_router.get("thinker_frame_event_id", "")
            if confirmation_router is not None
            else ""
        )
    )
    confirmation_patch = _unique_event_caused_by(
        events_by_id,
        event_name="USER_PATCH_RECEIVED",
        caused_by_event_id=_event_id(confirmation_router),
    )
    confirmation_interpreted = _unique_event_caused_by(
        events_by_id,
        event_name="USER_PATCH_INTERPRETED",
        caused_by_event_id=_event_id(confirmation_patch),
    )
    confirmation_received = _unique_event_caused_by(
        events_by_id,
        event_name="USER_CONFIRMATION_RECEIVED",
        caused_by_event_id=_event_id(confirmation_interpreted),
    )
    accepted = _unique_event_caused_by(
        events_by_id,
        event_name="CONFIRMATION_ACCEPTED",
        caused_by_event_id=_event_id(confirmation_received),
    )
    cancel_requested = _unique_event_caused_by(
        events_by_id,
        event_name="SLOWTASK_CANCEL_REQUESTED",
        caused_by_event_id=_event_id(accepted),
    )
    cancelled = _unique_event_caused_by(
        events_by_id,
        event_name="SLOWTASK_CANCELLED",
        caused_by_event_id=_event_id(cancel_requested),
    )
    cancelled_state = _unique_event_caused_by(
        events_by_id,
        event_name="SLOWTASK_STATE_CHANGED",
        caused_by_event_id=_event_id(cancelled),
    )
    chain = (
        prior_router,
        initial_patch,
        initial_interpreted,
        required,
        waiting,
        waiting_state,
        confirmation_turn,
        confirmation_thinker,
        confirmation_router,
        confirmation_patch,
        confirmation_interpreted,
        confirmation_received,
        accepted,
        cancel_requested,
        cancelled,
        cancelled_state,
        focus_event,
        event,
    )
    confirmation_id = required.get("confirmation_id") if required is not None else None
    plan_version = (
        initial_patch.get("plan_version") if initial_patch is not None else None
    )
    return bool(
        _event_matches(
            initial_patch,
            task_id=task_id,
            turn_id=event.get("turn_id"),
            utterance_id=event.get("utterance_id"),
            observed_plan_version=plan_version,
        )
        and "switch_task_candidate"
        in tuple(initial_patch.get("candidate_patch_types", ()))
        and _event_matches(
            initial_interpreted,
            task_id=task_id,
            patch_id=initial_patch.get("patch_id"),
            plan_version=plan_version,
            observed_plan_version=plan_version,
            interpreted_against_plan_version=plan_version,
            interpretation_type="switch_task",
        )
        and _event_matches(
            required,
            task_id=task_id,
            plan_version=plan_version,
            confirmation_id=confirmation_id,
            confirmation_scope="SWITCH_TASK",
            required_for_event_id=_event_id(initial_interpreted),
        )
        and _event_matches(
            waiting,
            task_id=task_id,
            plan_version=plan_version,
            confirmation_id=confirmation_id,
        )
        and _event_matches(
            waiting_state,
            task_id=task_id,
            plan_version=plan_version,
            to_state="WAITING_FOR_USER_CONFIRMATION",
        )
        and _event_matches(
            confirmation_thinker,
            event_name="MOCK_THINKER_FRAME_EMITTED",
            turn_id=confirmation_turn.get("turn_id") if confirmation_turn else None,
            utterance_id=(
                confirmation_turn.get("utterance_id")
                if confirmation_turn
                else None
            ),
        )
        and confirmation_thinker.get("caused_by_event_id")
        == _event_id(confirmation_turn)
        and _event_matches(
            confirmation_router,
            event_name="ROUTER_DECISION_EMITTED",
            router_decision="PATCH_ACTIVE_SLOW_TASK",
            task_focus="ACTIVE_TASK_PATCH",
            active_task_id=task_id,
            turn_committed_event_id=_event_id(confirmation_turn),
            thinker_frame_event_id=_event_id(confirmation_thinker),
        )
        and confirmation_router.get("caused_by_event_id")
        == _event_id(confirmation_thinker)
        and focus_event.get("caused_by_event_id")
        == _event_id(confirmation_router)
        and focus_event.get("last_focus_event_id")
        == _event_id(confirmation_router)
        and _event_matches(
            confirmation_patch,
            task_id=task_id,
            plan_version=plan_version,
            observed_plan_version=plan_version,
            turn_id=confirmation_router.get("turn_id")
            if confirmation_router
            else None,
            utterance_id=confirmation_router.get("utterance_id")
            if confirmation_router
            else None,
        )
        and "confirmation_candidate"
        in tuple(confirmation_patch.get("candidate_patch_types", ()))
        and _event_matches(
            confirmation_interpreted,
            task_id=task_id,
            patch_id=confirmation_patch.get("patch_id"),
            plan_version=plan_version,
            observed_plan_version=plan_version,
            interpreted_against_plan_version=plan_version,
            interpretation_type="confirmation",
        )
        and _event_matches(
            confirmation_received,
            task_id=task_id,
            patch_id=confirmation_patch.get("patch_id"),
            plan_version=plan_version,
            confirmation_id=confirmation_id,
            confirmation_signal="accepted",
        )
        and _event_matches(
            accepted,
            task_id=task_id,
            plan_version=plan_version,
            confirmation_id=confirmation_id,
            accepted_scope="SWITCH_TASK",
        )
        and _event_matches(
            cancel_requested,
            task_id=task_id,
            plan_version=plan_version,
            cancel_reason="switch_task_accepted",
            source_user_patch_event_id=_event_id(confirmation_patch),
        )
        and _event_matches(
            cancelled,
            task_id=task_id,
            plan_version=plan_version,
            cancel_reason="switch_task_accepted",
        )
        and _event_matches(
            cancelled_state,
            task_id=task_id,
            plan_version=plan_version,
            to_state="CANCELLED",
            reason="switch_task_accepted",
        )
        and _event_seq_strictly_increases(*chain)
    )


def _unique_event_caused_by(
    events_by_id: Mapping[str, Mapping[str, Any]],
    *,
    event_name: str,
    caused_by_event_id: object,
) -> Mapping[str, Any] | None:
    if caused_by_event_id in (None, ""):
        return None
    matches = [
        candidate
        for candidate in events_by_id.values()
        if candidate.get("event_name") == event_name
        and candidate.get("caused_by_event_id") == caused_by_event_id
    ]
    return matches[0] if len(matches) == 1 else None


def _event_id(event: Mapping[str, Any] | None) -> object | None:
    return event.get("event_id") if event is not None else None


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
    parallel_route_evidence_event_ids = {
        str(event["event_id"])
        for event in ordered_events
        if event.get("event_name") == "ROUTE_EVIDENCE_OUTPUT_EMITTED"
    }
    parallel_router_event_ids = {
        str(event["event_id"])
        for event in ordered_events
        if event.get("event_name") == "ROUTER_DECISION_EMITTED"
        and str(event.get("route_evidence_event_id", ""))
        in parallel_route_evidence_event_ids
    }
    committed_turn_events: dict[tuple[str, str], str] = {}
    asr_events: dict[tuple[str, str], str] = {}
    thinker_events: dict[tuple[str, str], str] = {}
    fast_interaction_events: dict[tuple[str, str], str] = {}
    fast_interaction_events_by_id: dict[str, Mapping[str, Any]] = {}
    foreground_candidates_by_id: dict[str, Mapping[str, Any]] = {}
    router_events_by_id: dict[str, Mapping[str, Any]] = {}
    foreground_gate_events_by_id: dict[str, Mapping[str, Any]] = {}
    committed_foreground_events_by_id: dict[str, Mapping[str, Any]] = {}
    pending_replacement_outputs: list[
        tuple[str, str, tuple[str, str]]
    ] = []

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
            _validate_fast_foreground_replay_payload(event)
            key = _turn_key(event)
            input_mode = _fast_interaction_input_mode(event)
            committed_event_id = committed_turn_events.get(key)
            if committed_event_id is None:
                raise ReplayValidationError(
                    "FAST_INTERACTION_OUTPUT_EMITTED requires prior TURN_INGRESS_COMMITTED"
                )
            if _is_adr018_parallel_event(event):
                continue
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
            event_id = str(event["event_id"])
            fast_interaction_events[key] = event_id
            fast_interaction_events_by_id[event_id] = event
        elif event_name == "FOREGROUND_REPLY_CANDIDATE_EMITTED":
            _validate_fast_foreground_replay_payload(event)
            if _is_adr018_parallel_event(event):
                continue
            _validate_foreground_candidate_replay_chain(
                event=event,
                committed_turn_events=committed_turn_events,
                fast_interaction_events_by_id=fast_interaction_events_by_id,
            )
            foreground_candidates_by_id[str(event["event_id"])] = event
        elif event_name == "ROUTER_DECISION_EMITTED":
            key = _turn_key(event)
            if key not in committed_turn_events:
                raise ReplayValidationError("ROUTER_DECISION_EMITTED requires prior TURN_INGRESS_COMMITTED")
            if str(event["event_id"]) in parallel_router_event_ids:
                router_events_by_id[str(event["event_id"])] = event
                continue
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
            router_events_by_id[str(event["event_id"])] = event
        elif event_name in {"FOREGROUND_ACT_GATE_PASSED", "FOREGROUND_ACT_GATE_FAILED"}:
            if _is_adr018_parallel_event(event):
                continue
            _validate_foreground_gate_replay_chain(
                event=event,
                foreground_candidates_by_id=foreground_candidates_by_id,
                router_events_by_id=router_events_by_id,
                fast_interaction_events_by_id=fast_interaction_events_by_id,
            )
            foreground_gate_events_by_id[str(event["event_id"])] = event
        elif event_name == "FOREGROUND_OUTPUT_DISCARDED":
            if _is_adr018_parallel_event(event):
                continue
            replacement_output = _validate_foreground_discard_replay_chain(
                event=event,
                foreground_candidates_by_id=foreground_candidates_by_id,
                router_events_by_id=router_events_by_id,
                fast_interaction_events_by_id=fast_interaction_events_by_id,
                foreground_gate_events_by_id=foreground_gate_events_by_id,
            )
            if replacement_output is not None:
                pending_replacement_outputs.append(replacement_output)
        elif event_name == "FOREGROUND_OUTPUT_COMMITTED":
            if _is_adr018_parallel_event(event):
                continue
            _validate_foreground_commit_replay_chain(
                event=event,
                router_events_by_id=router_events_by_id,
                foreground_candidates_by_id=foreground_candidates_by_id,
                foreground_gate_events_by_id=foreground_gate_events_by_id,
            )
            committed_foreground_events_by_id[str(event["event_id"])] = event

    for replacement_output_event_id, gate_event_id, turn_key in pending_replacement_outputs:
        replacement_event = committed_foreground_events_by_id.get(
            replacement_output_event_id
        )
        if replacement_event is None:
            raise ReplayValidationError(
                "FOREGROUND_OUTPUT_DISCARDED replacement_output_event_id must reference "
                "a FOREGROUND_OUTPUT_COMMITTED event"
            )
        if (
            replacement_event.get("gate_event_id") != gate_event_id
            or _turn_key(replacement_event) != turn_key
        ):
            raise ReplayValidationError(
                "FOREGROUND_OUTPUT_DISCARDED replacement_output_event_id must belong "
                "to the same Gate and turn"
            )


def _validate_foreground_candidate_replay_chain(
    *,
    event: Mapping[str, Any],
    committed_turn_events: Mapping[tuple[str, str], str],
    fast_interaction_events_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    key = _turn_key(event)
    if key not in committed_turn_events:
        raise ReplayValidationError(
            "FOREGROUND_REPLY_CANDIDATE_EMITTED requires prior TURN_INGRESS_COMMITTED"
        )
    fast_event_id = _required_event_ref(
        event,
        "fast_interaction_output_event_id",
        "FOREGROUND_REPLY_CANDIDATE_EMITTED",
    )
    fast_event = fast_interaction_events_by_id.get(fast_event_id)
    if fast_event is None:
        raise ReplayValidationError(
            "FOREGROUND_REPLY_CANDIDATE_EMITTED fast_interaction_output_event_id must "
            "reference prior FAST_INTERACTION_OUTPUT_EMITTED"
        )
    if event.get("caused_by_event_id") != fast_event_id:
        raise ReplayValidationError(
            "FOREGROUND_REPLY_CANDIDATE_EMITTED must be caused by FAST_INTERACTION_OUTPUT_EMITTED"
        )
    _require_same_turn(
        event,
        fast_event,
        "FOREGROUND_REPLY_CANDIDATE_EMITTED",
        "FAST_INTERACTION_OUTPUT_EMITTED",
    )
    input_mode = _fast_interaction_input_mode(event)
    fast_input_mode = _fast_interaction_input_mode(fast_event)
    if input_mode != fast_input_mode:
        raise ReplayValidationError(
            "FOREGROUND_REPLY_CANDIDATE_EMITTED input_mode must match FAST_INTERACTION_OUTPUT_EMITTED"
        )
    source_event_ids = _string_set_for_refs(
        event.get("source_event_ids"),
        error_prefix="FOREGROUND_REPLY_CANDIDATE_EMITTED source_event_ids",
    )
    if fast_event_id not in source_event_ids:
        raise ReplayValidationError(
            "FOREGROUND_REPLY_CANDIDATE_EMITTED source_event_ids must include "
            "FAST_INTERACTION_OUTPUT_EMITTED"
        )


def _validate_foreground_gate_replay_chain(
    *,
    event: Mapping[str, Any],
    foreground_candidates_by_id: Mapping[str, Mapping[str, Any]],
    router_events_by_id: Mapping[str, Mapping[str, Any]],
    fast_interaction_events_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    candidate_event_id = _required_event_ref(event, "candidate_event_id", str(event["event_name"]))
    router_event_id = _required_event_ref(
        event,
        "router_decision_event_id",
        str(event["event_name"]),
    )
    candidate_event = foreground_candidates_by_id.get(candidate_event_id)
    if candidate_event is None:
        raise ReplayValidationError(f"{event['event_name']} candidate_event_id must reference prior candidate")
    router_event = router_events_by_id.get(router_event_id)
    if router_event is None:
        raise ReplayValidationError(
            f"{event['event_name']} router_decision_event_id must reference prior Router decision"
        )
    if event.get("caused_by_event_id") != router_event_id:
        raise ReplayValidationError(f"{event['event_name']} must be caused by ROUTER_DECISION_EMITTED")
    fast_event_id = _required_event_ref(
        candidate_event,
        "fast_interaction_output_event_id",
        "FOREGROUND_REPLY_CANDIDATE_EMITTED",
    )
    fast_event = fast_interaction_events_by_id.get(fast_event_id)
    if fast_event is None:
        raise ReplayValidationError(f"{event['event_name']} candidate must reference prior Fast Interaction output")
    if router_event.get("fast_interaction_output_event_id") != fast_event_id:
        raise ReplayValidationError(f"{event['event_name']} Router decision must reference candidate Fast Interaction output")
    _require_same_turn(
        candidate_event,
        fast_event,
        str(event["event_name"]),
        "FAST_INTERACTION_OUTPUT_EMITTED",
    )
    _require_same_turn(
        router_event,
        fast_event,
        str(event["event_name"]),
        "FAST_INTERACTION_OUTPUT_EMITTED",
    )
    if event["event_name"] == "FOREGROUND_ACT_GATE_PASSED":
        if router_event.get("router_decision") != "FAST_ONLY":
            raise ReplayValidationError("FOREGROUND_ACT_GATE_PASSED requires FAST_ONLY Router decision")
        if router_event.get("task_focus") == "AMBIGUOUS":
            raise ReplayValidationError("FOREGROUND_ACT_GATE_PASSED rejects AMBIGUOUS task_focus")
        if event.get("foreground_act") != "ANSWER":
            raise ReplayValidationError("FOREGROUND_ACT_GATE_PASSED requires foreground_act=ANSWER")
        if event.get("risk_class") != "LOW":
            raise ReplayValidationError("FOREGROUND_ACT_GATE_PASSED requires risk_class=LOW")


def _validate_foreground_discard_replay_chain(
    *,
    event: Mapping[str, Any],
    foreground_candidates_by_id: Mapping[str, Mapping[str, Any]],
    router_events_by_id: Mapping[str, Mapping[str, Any]],
    fast_interaction_events_by_id: Mapping[str, Mapping[str, Any]],
    foreground_gate_events_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[str, str, tuple[str, str]] | None:
    candidate_event_id = _required_event_ref(
        event,
        "candidate_event_id",
        "FOREGROUND_OUTPUT_DISCARDED",
    )
    fast_event_id = _required_event_ref(
        event,
        "fast_interaction_output_event_id",
        "FOREGROUND_OUTPUT_DISCARDED",
    )
    router_event_id = _required_event_ref(
        event,
        "router_decision_event_id",
        "FOREGROUND_OUTPUT_DISCARDED",
    )
    gate_event_id = _required_event_ref(
        event,
        "caused_by_event_id",
        "FOREGROUND_OUTPUT_DISCARDED",
    )
    candidate_event = foreground_candidates_by_id.get(candidate_event_id)
    fast_event = fast_interaction_events_by_id.get(fast_event_id)
    router_event = router_events_by_id.get(router_event_id)
    gate_event = foreground_gate_events_by_id.get(gate_event_id)
    if candidate_event is None:
        raise ReplayValidationError("FOREGROUND_OUTPUT_DISCARDED candidate_event_id must reference prior candidate")
    if fast_event is None:
        raise ReplayValidationError(
            "FOREGROUND_OUTPUT_DISCARDED fast_interaction_output_event_id must reference prior Fast Interaction output"
        )
    if router_event is None:
        raise ReplayValidationError(
            "FOREGROUND_OUTPUT_DISCARDED router_decision_event_id must reference prior Router decision"
        )
    if gate_event is None or gate_event.get("event_name") != "FOREGROUND_ACT_GATE_FAILED":
        raise ReplayValidationError("FOREGROUND_OUTPUT_DISCARDED must be caused by FOREGROUND_ACT_GATE_FAILED")
    if candidate_event.get("fast_interaction_output_event_id") != fast_event_id:
        raise ReplayValidationError("FOREGROUND_OUTPUT_DISCARDED candidate must match discarded Fast Interaction output")
    if router_event.get("fast_interaction_output_event_id") != fast_event_id:
        raise ReplayValidationError("FOREGROUND_OUTPUT_DISCARDED Router decision must match discarded Fast Interaction output")
    if gate_event.get("candidate_event_id") != candidate_event_id:
        raise ReplayValidationError("FOREGROUND_OUTPUT_DISCARDED gate must reference discarded candidate")
    if gate_event.get("router_decision_event_id") != router_event_id:
        raise ReplayValidationError("FOREGROUND_OUTPUT_DISCARDED gate must reference discarded Router decision")
    replacement_output_event_id = event.get("replacement_output_event_id")
    if replacement_output_event_id in (None, ""):
        return None
    return (
        str(replacement_output_event_id),
        gate_event_id,
        _turn_key(router_event),
    )


def _validate_foreground_commit_replay_chain(
    *,
    event: Mapping[str, Any],
    router_events_by_id: Mapping[str, Mapping[str, Any]],
    foreground_candidates_by_id: Mapping[str, Mapping[str, Any]],
    foreground_gate_events_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    router_event_id = _required_event_ref(
        event,
        "router_decision_event_id",
        "FOREGROUND_OUTPUT_COMMITTED",
    )
    router_event = router_events_by_id.get(router_event_id)
    if router_event is None:
        raise ReplayValidationError(
            "FOREGROUND_OUTPUT_COMMITTED router_decision_event_id must reference prior Router decision"
        )
    _require_same_turn(
        event,
        router_event,
        "FOREGROUND_OUTPUT_COMMITTED",
        "ROUTER_DECISION_EMITTED",
    )
    gate_event_id = event.get("gate_event_id")
    fallback_policy_ref = event.get("fallback_policy_ref")
    fallback_reason = event.get("fallback_reason")
    if gate_event_id in (None, "") and (fallback_policy_ref in (None, "") or fallback_reason in (None, "")):
        raise ReplayValidationError(
            "FOREGROUND_OUTPUT_COMMITTED requires gate_event_id or fallback policy and reason"
        )
    caused_by_event_id = _required_event_ref(
        event,
        "caused_by_event_id",
        "FOREGROUND_OUTPUT_COMMITTED",
    )
    if gate_event_id not in (None, "") and caused_by_event_id != str(gate_event_id):
        raise ReplayValidationError("FOREGROUND_OUTPUT_COMMITTED caused_by_event_id must match gate_event_id")
    gate_event = foreground_gate_events_by_id.get(caused_by_event_id)
    if gate_event is None:
        raise ReplayValidationError("FOREGROUND_OUTPUT_COMMITTED must be caused by a prior foreground gate event")
    if gate_event.get("router_decision_event_id") != router_event_id:
        raise ReplayValidationError("FOREGROUND_OUTPUT_COMMITTED gate must reference committed Router decision")
    output_basis = event.get("output_basis")
    foreground_act = _required_event_ref(
        event,
        "foreground_act",
        "FOREGROUND_OUTPUT_COMMITTED",
    )
    if output_basis == "reply_candidate":
        if gate_event.get("event_name") != "FOREGROUND_ACT_GATE_PASSED":
            raise ReplayValidationError("reply_candidate FOREGROUND_OUTPUT_COMMITTED requires gate pass")
        if foreground_act != "ANSWER":
            raise ReplayValidationError(
                "reply_candidate FOREGROUND_OUTPUT_COMMITTED requires foreground_act=ANSWER"
            )
        candidate_event_id = _required_event_ref(
            gate_event,
            "candidate_event_id",
            "FOREGROUND_ACT_GATE_PASSED",
        )
        candidate_event = foreground_candidates_by_id.get(candidate_event_id)
        if candidate_event is None:
            raise ReplayValidationError(
                "reply_candidate FOREGROUND_OUTPUT_COMMITTED gate must reference prior candidate"
            )
        if event.get("output_ref") != candidate_event.get("candidate_ref"):
            raise ReplayValidationError(
                "reply_candidate FOREGROUND_OUTPUT_COMMITTED output_ref must match gated candidate_ref"
            )
    elif output_basis in {"template_ack", "template_clarify", "silence_policy"}:
        if gate_event.get("event_name") != "FOREGROUND_ACT_GATE_FAILED":
            raise ReplayValidationError("template FOREGROUND_OUTPUT_COMMITTED requires gate failure")
        if fallback_policy_ref in (None, "") or fallback_reason in (None, ""):
            raise ReplayValidationError("template FOREGROUND_OUTPUT_COMMITTED requires fallback policy and reason")
        if output_basis != "silence_policy":
            template = resolve_foreground_template(
                output_ref=event.get("output_ref"),
                output_basis=output_basis,
                fallback_policy_ref=fallback_policy_ref,
                router_decision=router_event.get("router_decision"),
            )
            if template is None:
                raise ReplayValidationError(
                    "template FOREGROUND_OUTPUT_COMMITTED must match the exact "
                    "versioned foreground template catalog"
                )
            if foreground_act != template.foreground_act:
                raise ReplayValidationError(
                    "template FOREGROUND_OUTPUT_COMMITTED foreground_act must "
                    "match the versioned foreground template catalog"
                )
        elif foreground_act != "SILENCE":
            raise ReplayValidationError(
                "silence_policy FOREGROUND_OUTPUT_COMMITTED requires foreground_act=SILENCE"
            )
    else:
        raise ReplayValidationError("FOREGROUND_OUTPUT_COMMITTED has unsupported output_basis")


def _required_event_ref(event: Mapping[str, Any], field: str, event_name: str) -> str:
    value = event.get(field)
    if value in (None, ""):
        raise ReplayValidationError(f"{event_name} requires {field}")
    return str(value)


def _require_same_turn(
    event: Mapping[str, Any],
    reference_event: Mapping[str, Any],
    event_name: str,
    reference_event_name: str,
) -> None:
    if _turn_key(event) != _turn_key(reference_event):
        raise ReplayValidationError(f"{event_name} must match {reference_event_name} turn_id and utterance_id")


FAST_FOREGROUND_FORBIDDEN_PAYLOAD_FIELDS = frozenset(
    {
        "raw_audio",
        "audio_bytes",
        "audio_payload",
        "raw_trace",
        "trace",
        "diagnostics",
        "raw_prompt",
        "prompt",
        "system_message",
        "developer_message",
        "raw_text",
        "text",
        "transcript_text",
        "reply_candidate",
        "candidate_text",
        "provider_request",
        "provider_response",
        "provider_body",
        "provider_payload",
        "provider_text",
        "provider_schema",
        "provider_specific_schema",
        "request_body",
        "response_body",
        "body",
        "payload",
        "authorization_header",
        "authorization",
        "cookie",
        "credential",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "local_path",
        "local_wav_path",
    }
)


def _validate_fast_foreground_replay_payload(event: Mapping[str, Any]) -> None:
    if _contains_forbidden_payload_field(
        event,
        forbidden_fields=FAST_FOREGROUND_FORBIDDEN_PAYLOAD_FIELDS,
    ):
        raise ReplayValidationError(f"{event['event_name']} contains raw Fast Interaction payload")


def _is_adr018_parallel_event(event: Mapping[str, Any]) -> bool:
    topology = event.get("fast_interaction_topology")
    return (
        isinstance(topology, str)
        and str(topology) == "speculative_candidate_parallel_route"
    )


def _raw_event_is_adr018(event: Mapping[str, Any]) -> bool:
    event_name = event.get("event_name")
    return (
        isinstance(event_name, str)
        and str(event_name) in ADR018_EVENT_NAMES
    ) or _is_adr018_parallel_event(event)


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
        "qwen_input_item_ref",
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

        if _contains_forbidden_payload_field(
            event,
            forbidden_fields=ASR_FORBIDDEN_PAYLOAD_FIELDS,
        ):
            raise ReplayValidationError(
                "ASR_TRANSCRIPT_OUTPUT_EMITTED must not contain raw audio, transcript, or provider payload"
            )
        _validate_asr_safe_refs(event)
        output_mode = str(event["output_mode"])
        provider_free_qwen_mock = _is_authorized_provider_free_qwen_mock_asr(
            event,
            ordered_events=ordered_events,
        )
        if output_mode not in {"real", "fallback", "degraded"} and not (
            output_mode == "mock" and provider_free_qwen_mock
        ):
            raise ReplayValidationError(
                "ASR_TRANSCRIPT_OUTPUT_EMITTED output_mode=mock requires exact "
                "provider-free Slice 3B.1 Qwen parallel capability evidence"
            )

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
            allowed_statuses=(
                {"provider_correlated"}
                if provider_free_qwen_mock
                else {"available", "unavailable"}
            ),
        )
        _validate_asr_status_enum(
            event,
            status_field="streaming_status",
            allowed_statuses=(
                {"complete"}
                if provider_free_qwen_mock
                else {"supported", "unsupported_final_only"}
            ),
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


def _is_authorized_provider_free_qwen_mock_asr(
    event: Mapping[str, Any],
    *,
    ordered_events: Sequence[Mapping[str, Any]],
) -> bool:
    if event.get("output_mode") != "mock":
        return False
    if event.get("adapter_id") != "slice3b1_qwen_realtime_asr_projection":
        return False
    if any(
        event.get(field) in (None, "")
        for field in (
            "provider_session_generation",
            "qwen_input_item_ref",
            "qwen_input_content_index",
        )
    ):
        return False
    provider_generation = event.get("provider_session_generation")
    content_index = event.get("qwen_input_content_index")
    if (
        isinstance(provider_generation, bool)
        or not isinstance(provider_generation, int)
        or provider_generation < 1
        or isinstance(content_index, bool)
        or not isinstance(content_index, int)
        or content_index < 0
    ):
        return False

    key = _turn_key(event)
    parallel_fast_events = [
        candidate
        for candidate in ordered_events
        if candidate.get("event_name") == "FAST_INTERACTION_OUTPUT_EMITTED"
        and _is_adr018_parallel_event(candidate)
        and _turn_key(candidate) == key
    ]
    if len(parallel_fast_events) > 1:
        return False
    fast_event = parallel_fast_events[0] if parallel_fast_events else None
    if fast_event is not None and (
        fast_event.get("provider_session_generation")
        != event.get("provider_session_generation")
        or fast_event.get("output_mode") != "mock"
        or fast_event.get("adapter_id")
        != "slice3b1_parallel_fast_interaction_orchestrator"
        or fast_event.get("qwen_candidate_adapter_id")
        != "slice3b1_qwen_realtime_fake"
    ):
        return False

    events_by_id = {
        str(candidate["event_id"]): candidate
        for candidate in ordered_events
    }
    committed_event = events_by_id.get(
        str(event.get("caused_by_event_id", ""))
    )
    if (
        committed_event is None
        or committed_event.get("event_name") != "TURN_INGRESS_COMMITTED"
        or _turn_key(committed_event) != key
        or not _event_seq_before(committed_event, event)
    ):
        return False
    provider_context_events = [
        candidate
        for candidate in ordered_events
        if candidate.get("event_name") == "PROVIDER_CONTEXT_STATE_CHANGED"
        and int(candidate["event_seq"]) < int(event["event_seq"])
    ]
    if not provider_context_events:
        return False
    provider_context = provider_context_events[-1]
    if (
        provider_context.get("adapter_id") != "slice3b1_qwen_realtime_fake"
        or provider_context.get("to_state") != "CLEAN"
        or provider_context.get("provider_session_generation")
        != event.get("provider_session_generation")
        or provider_context.get("output_mode") != "mock"
    ):
        return False
    if fast_event is not None:
        route_event = events_by_id.get(
            str(fast_event.get("route_evidence_event_id", ""))
        )
        safety_event = events_by_id.get(
            str(fast_event.get("candidate_safety_evidence_event_id", ""))
        )
    else:
        route_matches = [
            candidate
            for candidate in ordered_events
            if candidate.get("event_name") == "ROUTE_EVIDENCE_OUTPUT_EMITTED"
            and candidate.get("final_asr_event_id") == event.get("event_id")
            and _turn_key(candidate) == key
        ]
        if len(route_matches) > 1:
            return False
        route_event = route_matches[0] if route_matches else None
        safety_matches = [
            candidate
            for candidate in ordered_events
            if candidate.get("event_name")
            == "CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED"
            and candidate.get("route_evidence_event_id")
            == (
                route_event.get("event_id")
                if route_event is not None
                else None
            )
            and _turn_key(candidate) == key
        ]
        if len(safety_matches) > 1:
            return False
        safety_event = safety_matches[0] if safety_matches else None
    if fast_event is not None and route_event is None:
        return False
    if route_event is not None and (
        route_event.get("event_name") != "ROUTE_EVIDENCE_OUTPUT_EMITTED"
        or route_event.get("output_mode") != "mock"
        or route_event.get("adapter_id") != "slice3b1_route_evidence_fake"
        or route_event.get("provider_session_generation")
        != event.get("provider_session_generation")
    ):
        return False
    if safety_event is not None and (
        safety_event.get("event_name")
        != "CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED"
        or safety_event.get("output_mode") != "mock"
    ):
        return False

    snapshots = [
        candidate
        for candidate in ordered_events
        if candidate.get("event_name")
        == "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED"
        and int(candidate["event_seq"]) < int(event["event_seq"])
    ]
    if len(snapshots) != 1:
        return False
    snapshot = snapshots[0]
    if snapshot.get("capability_version") != "slice3b1.mock.v1":
        return False
    digest = snapshot.get("capability_matrix_digest")
    if (
        not isinstance(digest, str)
        or not digest.startswith("sha256:")
        or len(digest) != 71
        or any(
            character not in "0123456789abcdef"
            for character in digest.removeprefix("sha256:")
        )
    ):
        return False
    session_events = [
        candidate
        for candidate in ordered_events
        if candidate.get("event_name") == "SESSION_STARTED"
    ]
    if (
        len(session_events) != 1
        or session_events[0].get("capability_snapshot_ref")
        != snapshot.get("capability_snapshot_ref")
    ):
        return False

    try:
        adapter_ids = [str(value) for value in snapshot["adapter_ids"]]
        adapter_types = [str(value) for value in snapshot["adapter_types"]]
        deployment_modes = [
            str(value) for value in snapshot["deployment_modes"]
        ]
        output_modes = [str(value) for value in snapshot["output_modes"]]
    except (KeyError, TypeError):
        return False
    if len({len(adapter_ids), len(adapter_types), len(deployment_modes), len(output_modes)}) != 1:
        return False
    if len(adapter_ids) != 4 or len(set(adapter_ids)) != 4:
        return False
    profiles = {
        adapter_id: (adapter_type, deployment_mode, output_mode)
        for adapter_id, adapter_type, deployment_mode, output_mode in zip(
            adapter_ids,
            adapter_types,
            deployment_modes,
            output_modes,
            strict=True,
        )
    }
    expected_profiles = {
        "slice3b1_qwen_realtime_asr_projection": (
            "asr",
            "provider_free",
            "mock",
        ),
        "slice3b1_qwen_realtime_fake": (
            "duplex_model",
            "provider_free",
            "mock",
        ),
        "slice3b1_parallel_fast_interaction_orchestrator": (
            "fast_interaction",
            "provider_free",
            "mock",
        ),
        "slice3b1_route_evidence_fake": (
            "route_evidence",
            "provider_free",
            "mock",
        ),
    }
    return profiles == expected_profiles and (
        safety_event is None
        or (
            route_event is not None
            and safety_event.get("adapter_id") == route_event.get("adapter_id")
        )
    )


def _validate_adr018_parallel_chain(
    ordered_events: Sequence[Mapping[str, Any]],
) -> None:
    if not any(
        event.get("event_name") in ADR018_EVENT_NAMES
        or _is_adr018_parallel_event(event)
        for event in ordered_events
    ):
        return

    _validate_adr018_safe_payloads(ordered_events)
    _validate_unique_event_ids(ordered_events)
    events_by_id = {
        str(event["event_id"]): event
        for event in ordered_events
    }
    _validate_adr018_projection_prefixes(
        ordered_events,
        events_by_id=events_by_id,
    )
    _validate_adr018_provider_readiness(ordered_events)
    _validate_adr018_parallel_terminal_cardinality(
        ordered_events,
        events_by_id=events_by_id,
    )
    _validate_adr018_bound_request_terminal_exclusivity(
        ordered_events,
        events_by_id=events_by_id,
    )
    _validate_adr018_user_fast_delivery_retirement(
        ordered_events,
        events_by_id=events_by_id,
    )
    _validate_adr018_state_transitions(
        ordered_events,
        events_by_id=events_by_id,
    )
    _validate_adr018_rejected_turn_terminals(ordered_events)
    _validate_adr018_handoffs_and_delivery(
        ordered_events,
        events_by_id=events_by_id,
    )
    route_chains: dict[str, tuple[Mapping[str, Any], ...]] = {}
    for route_event in ordered_events:
        if route_event.get("event_name") != "ROUTE_EVIDENCE_OUTPUT_EMITTED":
            continue
        route_chains[str(route_event["event_id"])] = (
            _validate_adr018_route_chain(
                route_event,
                ordered_events=ordered_events,
                events_by_id=events_by_id,
            )
        )
    for safety_event in ordered_events:
        if (
            safety_event.get("event_name")
            != "CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED"
        ):
            continue
        _validate_adr018_candidate_safety_chain(
            safety_event,
            events_by_id=events_by_id,
        )

    parallel_fast_events = [
        event
        for event in ordered_events
        if event.get("event_name") == "FAST_INTERACTION_OUTPUT_EMITTED"
        and _is_adr018_parallel_event(event)
    ]
    parallel_turn_keys = [_turn_key(event) for event in parallel_fast_events]
    if len(parallel_turn_keys) != len(set(parallel_turn_keys)):
        raise ReplayValidationError(
            "ADR-018 parallel turn requires exactly one composite Fast "
            "Interaction output"
        )
    for fast_event in parallel_fast_events:
        _validate_one_adr018_parallel_turn(
            fast_event,
            ordered_events=ordered_events,
            events_by_id=events_by_id,
        )
    _validate_adr018_native_authority_closure(
        ordered_events,
        events_by_id=events_by_id,
        validated_parallel_fast_event_ids={
            str(event["event_id"])
            for event in parallel_fast_events
        },
    )

    orphan_parallel_events = [
        event
        for event in ordered_events
        if _is_adr018_parallel_event(event)
        and event.get("event_name") != "FAST_INTERACTION_OUTPUT_EMITTED"
        and _parallel_event_turn_key(
            event,
            events_by_id=events_by_id,
        )
        not in set(parallel_turn_keys)
    ]
    if orphan_parallel_events:
        raise ReplayValidationError(
            "ADR-018 parallel event requires one matching composite Fast "
            "Interaction output"
        )


def _validate_adr018_parallel_terminal_cardinality(
    ordered_events: Sequence[Mapping[str, Any]],
    *,
    events_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    qwen_asr_by_commit: dict[str, str] = {}
    qwen_asr_by_input: dict[tuple[int, str, int], str] = {}
    qwen_asr_by_request: dict[tuple[str, str], str] = {}
    route_by_commit: dict[str, str] = {}
    route_by_final_asr: dict[str, str] = {}
    route_by_request: dict[tuple[str, str], str] = {}
    safety_by_response: dict[str, str] = {}
    safety_by_response_digest: dict[tuple[str, str], str] = {}
    safety_by_request: dict[tuple[str, str], str] = {}
    evidence_requests: dict[tuple[str, str], str] = {}

    for event in ordered_events:
        event_name = str(event["event_name"])
        event_id = str(event["event_id"])
        if (
            event_name == "ASR_TRANSCRIPT_OUTPUT_EMITTED"
            and event.get("provider_session_generation") not in (None, "")
            and event.get("qwen_input_item_ref") not in (None, "")
        ):
            commit_id = _required_text(
                event,
                "caused_by_event_id",
                event_name=event_name,
            )
            committed = events_by_id.get(commit_id)
            if (
                committed is None
                or committed.get("event_name") != "TURN_INGRESS_COMMITTED"
            ):
                continue
            input_key = (
                _required_nonnegative_int(
                    event,
                    "provider_session_generation",
                    event_name=event_name,
                ),
                _required_text(
                    event,
                    "qwen_input_item_ref",
                    event_name=event_name,
                ),
                _required_nonnegative_int(
                    event,
                    "qwen_input_content_index",
                    event_name=event_name,
                ),
            )
            request_key = (
                _required_text(event, "adapter_id", event_name=event_name),
                _required_text(
                    event,
                    "adapter_request_id",
                    event_name=event_name,
                ),
            )
            if (
                commit_id in qwen_asr_by_commit
                or input_key in qwen_asr_by_input
                or request_key in qwen_asr_by_request
            ):
                raise ReplayValidationError(
                    "Qwen final ASR terminal cardinality requires exactly one "
                    "terminal per committed turn, input correlation, and "
                    "adapter request"
                )
            qwen_asr_by_commit[commit_id] = event_id
            qwen_asr_by_input[input_key] = event_id
            qwen_asr_by_request[request_key] = event_id
            continue

        if event_name == "ROUTE_EVIDENCE_OUTPUT_EMITTED":
            final_asr_id = _required_text(
                event,
                "final_asr_event_id",
                event_name=event_name,
            )
            final_asr = events_by_id.get(final_asr_id)
            commit_id = (
                str(final_asr.get("caused_by_event_id", ""))
                if final_asr is not None
                else ""
            )
            request_key = (
                _required_text(event, "adapter_id", event_name=event_name),
                _required_text(
                    event,
                    "adapter_request_id",
                    event_name=event_name,
                ),
            )
            if (
                commit_id in route_by_commit
                or final_asr_id in route_by_final_asr
                or request_key in route_by_request
                or request_key in evidence_requests
            ):
                raise ReplayValidationError(
                    "Route Evidence terminal cardinality requires exactly one "
                    "terminal per committed turn, final ASR, and adapter "
                    "request"
                )
            route_by_commit[commit_id] = event_id
            route_by_final_asr[final_asr_id] = event_id
            route_by_request[request_key] = event_id
            evidence_requests[request_key] = event_id
            continue

        if event_name == "CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED":
            response_id = _required_text(
                event,
                "qwen_response_id",
                event_name=event_name,
            )
            digest = _required_text(
                event,
                "candidate_transcript_digest",
                event_name=event_name,
            )
            response_digest_key = (response_id, digest)
            request_key = (
                _required_text(event, "adapter_id", event_name=event_name),
                _required_text(
                    event,
                    "adapter_request_id",
                    event_name=event_name,
                ),
            )
            if (
                response_id in safety_by_response
                or response_digest_key in safety_by_response_digest
                or request_key in safety_by_request
                or request_key in evidence_requests
            ):
                raise ReplayValidationError(
                    "candidate-safety terminal cardinality requires exactly "
                    "one terminal per response, transcript digest, and "
                    "adapter request"
                )
            safety_by_response[response_id] = event_id
            safety_by_response_digest[response_digest_key] = event_id
            safety_by_request[request_key] = event_id
            evidence_requests[request_key] = event_id


def _validate_adr018_bound_request_terminal_exclusivity(
    ordered_events: Sequence[Mapping[str, Any]],
    *,
    events_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    successful_request_keys: set[tuple[str, str]] = set()

    def record_bound_success(
        adapter_id: object,
        adapter_request_id: object,
        success_event: Mapping[str, Any] | None,
    ) -> None:
        if (
            success_event is None
            or success_event.get("output_mode") == "degraded"
            or not isinstance(adapter_id, str)
            or not adapter_id
            or not isinstance(adapter_request_id, str)
            or not adapter_request_id
        ):
            return
        successful_request_keys.add((adapter_id, adapter_request_id))

    for evidence_event in ordered_events:
        if evidence_event.get("event_name") not in {
            "ROUTE_EVIDENCE_OUTPUT_EMITTED",
            "CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED",
        }:
            continue
        record_bound_success(
            evidence_event.get("adapter_id"),
            evidence_event.get("adapter_request_id"),
            evidence_event,
        )

    for fast_event in ordered_events:
        if (
            fast_event.get("event_name")
            != "FAST_INTERACTION_OUTPUT_EMITTED"
            or not _is_adr018_parallel_event(fast_event)
            or fast_event.get("output_mode") == "degraded"
        ):
            continue
        candidate = next(
            (
                event
                for event in ordered_events
                if event.get("event_name")
                == "FOREGROUND_REPLY_CANDIDATE_EMITTED"
                and event.get("fast_interaction_output_event_id")
                == fast_event.get("event_id")
                and event.get("output_mode") != "degraded"
            ),
            None,
        )
        record_bound_success(
            fast_event.get("qwen_candidate_adapter_id"),
            fast_event.get("qwen_candidate_adapter_request_id"),
            candidate,
        )
        route_event = events_by_id.get(
            str(fast_event.get("route_evidence_event_id", ""))
        )
        record_bound_success(
            (
                route_event.get("adapter_id")
                if route_event is not None
                else None
            ),
            (
                route_event.get("adapter_request_id")
                if route_event is not None
                else None
            ),
            route_event,
        )
        safety_event = events_by_id.get(
            str(
                fast_event.get(
                    "candidate_safety_evidence_event_id",
                    "",
                )
            )
        )
        record_bound_success(
            (
                safety_event.get("adapter_id")
                if safety_event is not None
                else None
            ),
            (
                safety_event.get("adapter_request_id")
                if safety_event is not None
                else None
            ),
            safety_event,
        )

    terminal_names = {
        "ADAPTER_REQUEST_FAILED",
        "ADAPTER_OUTPUT_VALIDATION_FAILED",
        "ADAPTER_OUTPUT_DEGRADED",
    }
    for terminal in ordered_events:
        if terminal.get("event_name") not in terminal_names:
            continue
        adapter_id = terminal.get("adapter_id")
        adapter_request_id = terminal.get("adapter_request_id")
        if (
            isinstance(adapter_id, str)
            and isinstance(adapter_request_id, str)
            and (adapter_id, adapter_request_id)
            in successful_request_keys
        ):
            raise ReplayValidationError(
                "Slice3B1 bound adapter request cannot have both a "
                "non-degraded success authority and a terminal failure or "
                "degradation"
            )


ADR018_AMENDED_EVENT_NAMES = frozenset(
    {
        "ASR_TRANSCRIPT_OUTPUT_EMITTED",
        "INTERRUPT_CANDIDATE",
        "ROUTER_DECISION_EMITTED",
        "PLAYBACK_SPAN_STARTED",
        "PLAYBACK_COMMITTED",
        "PLAYBACK_FINISHED",
        "TTS_TRUNCATE_REQUESTED",
        "TTS_TRUNCATED",
        "FAST_INTERACTION_OUTPUT_EMITTED",
        "FOREGROUND_REPLY_CANDIDATE_EMITTED",
        "FOREGROUND_ACT_GATE_PASSED",
        "FOREGROUND_ACT_GATE_FAILED",
        "FOREGROUND_OUTPUT_COMMITTED",
        "FOREGROUND_OUTPUT_DISCARDED",
    }
)
ADR018_FORBIDDEN_PAYLOAD_FIELDS = (
    FAST_FOREGROUND_FORBIDDEN_PAYLOAD_FIELDS
    | frozenset(
        {
            "raw_pcm",
            "pcm",
            "pcm_bytes",
            "pcm_payload",
            "pcm_chunks",
            "audio_chunks",
            "audio_delta",
            "raw_user_text",
            "user_text",
            "user_utterance",
            "unredacted_user_text",
            "raw_transcript",
            "transcript",
            "candidate_transcript",
            "assistant_text",
            "slow_llm_text",
            "private_reasoning",
            "reasoning",
            "chain_of_thought",
            "provider_event",
            "provider_events",
            "provider_payload_ref",
            "provider_body_ref",
        }
    )
)
ADR018_SAFE_REF_PATTERN = re.compile(
    r"\A[a-z][a-z0-9-]{0,47}://[A-Za-z0-9._~:/-]{1,384}\Z"
)
ADR018_MAX_SAFE_REF_CHARS = 435
ADR018_MAX_METADATA_STRING_CHARS = 1_024
ADR018_MAX_REASON_CODE_CHARS = 128
ADR018_MAX_SEQUENCE_ITEMS = 256
ADR018_MAX_MAPPING_ITEMS = 128
ADR018_MAX_METADATA_DEPTH = 8
ADR018_SAFE_REASON_CODE_PATTERN = re.compile(
    r"\A[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z"
)
ADR018_SAFE_FAILURE_REASON_PATTERN = re.compile(
    r"\A[A-Za-z0-9][A-Za-z0-9._/-]{0,127}"
    r"(?:: [A-Za-z0-9][A-Za-z0-9._/-]{0,127})?\Z"
)
ADR018_SAFE_SYMBOLIC_METADATA_PATTERN = re.compile(
    r"\A[A-Za-z0-9][A-Za-z0-9._~:/-]{0,1023}\Z"
)

# The registry defines required and conditional fields. These are the
# backward-compatible optional fields accepted by the ADR-018 canonical
# additions and amendments. Keeping them per event makes the replay boundary
# closed-world without changing the global legacy envelope.
ADR018_ACCEPTED_OPTIONAL_FIELDS_BY_EVENT: dict[str, frozenset[str]] = {
    # Capability snapshots carry immutable, bounded profile metadata.
    "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED": frozenset(
        {"capability_version", "capability_matrix_digest"}
    ),
    # Request-bound degradation needs the exact request and missing capability;
    # fallback identity remains accepted legacy adapter metadata.
    "ADAPTER_OUTPUT_DEGRADED": frozenset(
        {
            "adapter_request_id",
            "missing_capability",
            "fallback_adapter_id",
        }
    ),
    # Accepted adapter lifecycle producers retain bounded timeout metadata and
    # validation failures retain their immutable SlowTask binding.
    "ADAPTER_REQUEST_FAILED": frozenset({"timeout_ms"}),
    "ADAPTER_REQUEST_RETRYING": frozenset({"timeout_ms"}),
    "ADAPTER_OUTPUT_VALIDATION_FAILED": frozenset(
        {
            "invalid_output_ref",
            "plan_version",
            "task_event_seq",
            "task_id",
        }
    ),
    "ADAPTER_HEALTHCHECK_FAILED": frozenset({"endpoint_ref"}),
    # Accepted MVP-0 registry options and exact producer metadata stay
    # available when a legacy event appears inside an ADR-018 session.
    "TEXT_INPUT_RECEIVED": frozenset(
        {"audio_span_id", "language_hint"}
    ),
    "LOW_CONFIDENCE_INGRESS": frozenset({"policy_ref"}),
    "AUDIO_SPAN_STARTED": frozenset({"input_span_id"}),
    "AUDIO_CHUNK_RECEIVED": frozenset({"audio_chunk_ref"}),
    "BARGE_IN_CANDIDATE": frozenset(
        {"mock_profile_ref", "output_mode", "playback_reference_ref"}
    ),
    "DIRECTEDNESS_CANDIDATE": frozenset({"evidence_ref"}),
    "SEMANTIC_CLOSE_CANDIDATE": frozenset({"evidence_ref"}),
    "NON_ASSISTANT_CANDIDATE": frozenset({"evidence_ref"}),
    "TURN_OPENED": frozenset({"text_span_id"}),
    "TURN_HELD": frozenset({"hold_reason"}),
    "TURN_INGRESS_ACCEPTED": frozenset({"text_span_id"}),
    "TURN_INGRESS_REJECTED": frozenset({"text_span_id"}),
    "WAITING_USER": frozenset({"turn_id"}),
    "MOCK_ASR_FRAME_EMITTED": frozenset(
        {"audio_span_id", "mock_profile_ref", "text_span_id"}
    ),
    "MOCK_THINKER_FRAME_EMITTED": frozenset(
        {"input_modality", "mock_profile_ref"}
    ),
    # Legacy ASR timestamp evidence remains a bounded opaque reference.
    "ASR_TRANSCRIPT_OUTPUT_EMITTED": frozenset({"audio_timestamps_ref"}),
    # Provider-backed speech detection adds only generation and opaque provider
    # event provenance; detection_basis is existing synthetic metadata.
    "SPEECH_START_DETECTED": frozenset(
        {
            "detection_basis",
            "provider_event_ref",
            "provider_session_generation",
        }
    ),
    "SPEECH_END_DETECTED": frozenset(
        {
            "detection_basis",
            "provider_event_ref",
            "provider_session_generation",
            "provider_stop_reason",
        }
    ),
    # ADR-018 fencing amendments bind interrupt/truncate to exact state.
    "INTERRUPT_CANDIDATE": frozenset(
        {
            "audio_span_id",
            "interaction_state_version",
            "playback_epoch",
        }
    ),
    "TTS_TRUNCATE_REQUESTED": frozenset(
        {
            "assistant_item_ref",
            "audio_span_id",
            "interaction_state_version",
            "playback_epoch",
            "release_token_ref",
        }
    ),
    "TTS_TRUNCATED": frozenset(
        {
            "assistant_item_ref",
            "final_playback_offset_ms",
            "interaction_state_version",
            "mock_profile_ref",
            "output_mode",
            "playback_epoch",
            "release_token_ref",
        }
    ),
    # Local Router amendments preserve exact evidence provenance.
    "ROUTER_DECISION_EMITTED": frozenset(
        {
            "active_task_id",
            "asr_frame_event_id",
            "confidence",
            "evidence_ref_policy",
            "evidence_uncertainty",
            "route_evidence_event_id",
            "task_focus",
            "thinker_frame_event_id",
            "turn_committed_event_id",
        }
    ),
    # Parallel evidence outputs optionally repeat their immutable snapshot and
    # provider-generation bindings; safety may also cite Route Evidence.
    "ROUTE_EVIDENCE_OUTPUT_EMITTED": frozenset(
        {"context_snapshot_id", "provider_session_generation"}
    ),
    "CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED": frozenset(
        {
            "context_snapshot_id",
            "provider_session_generation",
            "route_evidence_event_id",
        }
    ),
    # ContextSnapshotV1 carries optional current-task/confirmation identity.
    "MODEL_CONTEXT_PROJECTION_EMITTED": frozenset(
        {
            "active_task_ref",
            "active_task_state",
            "plan_version",
            "task_event_seq",
            "pending_confirmation_ref",
        }
    ),
    # SlowToFastHandoffV1 optional policy metadata remains codes/opaque refs,
    # never raw Slow LLM or tool output.
    "SLOW_TO_FAST_HANDOFF_EMITTED": frozenset(
        {
            "confirmation_state",
            "expires_at_monotonic_ms",
            "response_style_hint",
            "risk_warnings_ref",
        }
    ),
    "SLOW_TO_FAST_HANDOFF_DISPOSITIONED": frozenset(
        {
            "current_plan_version",
            "current_task_event_seq",
            "current_task_id",
            "replacement_handoff_id",
            "response_arbitration_event_id",
        }
    ),
    "RESPONSE_ARBITRATION_DECIDED": frozenset(
        {"selected_source_event_id"}
    ),
    "PROVIDER_CONTEXT_STATE_CHANGED": frozenset(
        {
            "cleanup_item_count",
            "cleanup_outcome",
            "delete_ack_count",
            "dropped_audio_frame_count",
        }
    ),
    "CANDIDATE_AUDIO_SHADOW_VERIFICATION_EMITTED": frozenset(
        {"shadow_policy_version"}
    ),
    "ASSISTANT_DELIVERY_DISPOSITIONED": frozenset(
        {
            "actual_stop_offset_ms",
            "playback_span_id",
            "release_token_ref",
        }
    ),
    # Existing parallel Fast fields are registry-conditional; these optional
    # evidence summaries and terminal metadata are accepted amendments.
    "FAST_INTERACTION_OUTPUT_EMITTED": frozenset(
        {"confidence", "risk_class", "risk_tags"}
    ),
    "FOREGROUND_REPLY_CANDIDATE_EMITTED": frozenset(
        {
            "candidate_safety_evidence_event_id",
            "route_evidence_event_id",
        }
    ),
    "FOREGROUND_ACT_GATE_PASSED": frozenset({"output_mode"}),
    "FOREGROUND_ACT_GATE_FAILED": frozenset(
        {
            "candidate_event_id",
            "downgrade_policy",
            "output_mode",
            "release_token_ref",
        }
    ),
    "FOREGROUND_OUTPUT_COMMITTED": frozenset(
        {"foreground_act", "output_mode"}
    ),
    "FOREGROUND_OUTPUT_DISCARDED": frozenset(
        {"fast_interaction_topology", "output_mode", "release_token_ref"}
    ),
    # Provider-native playback binds the complete immutable release identity.
    # The SpokenPlan/TTS fields retain ordinary non-native compatibility.
    "PLAYBACK_SPAN_STARTED": frozenset(
        {
            "approved_check_event_id",
            "assistant_item_ref",
            "candidate_id",
            "candidate_pcm_manifest_digest",
            "candidate_transcript_digest",
            "context_snapshot_id",
            "output_mode",
            "mock_profile_ref",
            "playback_epoch",
            "provider_session_generation",
            "qwen_content_index",
            "qwen_output_index",
            "qwen_output_item_id",
            "qwen_response_id",
            "release_token_ref",
            "spoken_plan_id",
            "turn_id",
            "tts_output_event_id",
            "utterance_id",
        }
    ),
    "PLAYBACK_PROGRESS": frozenset(
        {"mock_profile_ref", "output_mode", "progress_basis"}
    ),
    "PLAYBACK_COMMITTED": frozenset(
        {"mock_profile_ref", "output_mode", "release_token_ref"}
    ),
    "PLAYBACK_FINISHED": frozenset(
        {
            "finish_reason",
            "mock_profile_ref",
            "output_mode",
            "release_token_ref",
        }
    ),
    # Existing Composer/TTS fixtures carry these accepted immutable-fact and
    # check bindings when replayed in an ADR-018 session.
    "SEMANTIC_COMMITMENT_EMITTED": frozenset(
        {
            "commitment_ref",
            "forbidden_rewrite_fields",
            "immutable_fields",
            "must_say_fields",
        }
    ),
    "SPOKEN_PLAN_EMITTED": frozenset(
        {
            "forbidden_rewrite_fields",
            "immutable_fields",
            "must_say_fields",
            "source_commitment_id",
            "truthfulness_level",
        }
    ),
    "COMMITMENT_COVERAGE_CHECK_PASSED": frozenset(
        {"plan_version", "task_event_seq", "task_id"}
    ),
    "PROGRESS_TRUTHFULNESS_CHECK_PASSED": frozenset(
        {"plan_version", "task_event_seq", "task_id"}
    ),
    # Existing SlowTask, Slow LLM, and TTS producers use these canonical
    # identity/provenance fields; they remain explicit rather than learned
    # from replay fixture contents.
    "SLOWTASK_CREATED": frozenset({"source_evidence_refs"}),
    "SLOWTASK_DEGRADED": frozenset({"capability_or_tool_ref"}),
    "TASK_REPLANNED": frozenset({"superseded_plan_version"}),
    "SLOW_LLM_STRUCTURED_OUTPUT_EMITTED": frozenset(
        {"provenance_ref", "resolved_arguments_ref"}
    ),
    "TTS_SYNTHESIS_OUTPUT_EMITTED": frozenset(
        {"plan_version", "task_id"}
    ),
    # The accepted Thinker adapter contract emits these bounded refs, hints,
    # and confidence values in addition to the registry-required core.
    "THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED": frozenset(
        {
            "assistant_directedness_ref",
            "audio_caption_ref",
            "audio_span_id",
            "complexity_hint",
            "emotion_ref",
            "evidence_uncertainty",
            "focus_confidence",
            "semantic_close_ref",
            "task_focus_hint",
            "task_like",
            "text_span_id",
        }
    ),
    "USER_PATCH_RECEIVED": frozenset(
        {
            "authoritative_evidence_refs",
            "candidate_patch_types",
            "evidence_pack",
            "non_authoritative_hypothesis_refs",
            "turn_id",
            "utterance_id",
        }
    ),
    "USER_PATCH_INTERPRETED": frozenset(
        {"interpretation_reason", "source_evidence_refs"}
    ),
    "PLAN_VERSION_ADVANCED": frozenset(
        {"caused_by_user_patch_event_id"}
    ),
    "CONFIRMATION_REQUIRED": frozenset(
        {"expires_at_monotonic_ms"}
    ),
    "SLOWTASK_CANCEL_REQUESTED": frozenset(
        {"source_user_patch_event_id"}
    ),
    "TOOL_CALL_STARTED": frozenset({"tool_adapter_id"}),
    "TOOL_MANIFEST_LOADED": frozenset({"risk_class"}),
    "TOOL_EXECUTION_AUTHORIZED": frozenset({"confirmation_id"}),
    "TOOL_EXECUTION_STARTED": frozenset({"authorization_event_id"}),
    "TOOL_RESULT_RECEIVED": frozenset({"source_type", "trust_level"}),
    "REPLAY_STARTED": frozenset({"fixture_ref"}),
    "REPLAY_COMPLETED": frozenset({"failure_summary_ref"}),
    "COMMITMENT_COVERAGE_CHECK_FAILED": frozenset(
        {"plan_version", "task_event_seq", "task_id"}
    ),
    "PROGRESS_TRUTHFULNESS_CHECK_FAILED": frozenset(
        {
            "plan_version",
            "task_event_seq",
            "task_id",
            "truthfulness_level",
        }
    ),
}


def _registered_event_field_names(event_name: str) -> frozenset[str]:
    definition = get_event_definition(event_name)
    fields = set(COMMON_ENVELOPE_FIELDS)
    fields.update({"caused_by_event_id", "supersedes_event_id"})
    fields.update(definition.required_fields)
    fields.update(definition.literal_fields)
    fields.update(definition.enum_fields)
    for conditional in definition.conditional_required_fields:
        fields.add(conditional.when_field)
        fields.update(field for field, _ in conditional.and_conditions)
        fields.update(conditional.required_fields)
    for group in definition.all_or_none_fields:
        fields.update(group.fields)
    for group in (*definition.one_of_fields, *definition.any_of_field_sets):
        fields.update(group)
    fields.update(
        ADR018_ACCEPTED_OPTIONAL_FIELDS_BY_EVENT.get(event_name, ())
    )
    return frozenset(fields)


ADR018_NESTED_FIELDS_BY_PARENT: dict[str, frozenset[str]] = {
    "confidence_summary": frozenset(
        {
            "barge_in_confidence",
            "echo_likelihood",
            "vad_confidence",
        }
    ),
    "state_digest": frozenset(
        {
            "adapter_health_state_hash",
            "demo_ui_state_hash",
            "digest_schema_version",
            "event_schema_version_range",
            "foreground_authority_hash",
            "interaction_state_hash",
            "last_event_seq",
            "overall_digest",
            "playback_state_hash",
            "qwen_parallel_state_hash",
            "slowtask_state_hash",
            "source_session_id",
            "spoken_plan_check_state_hash",
            "spoken_plan_state_hash",
            "task_focus_state_hash",
            "tool_execution_state_hash",
            "trace_privacy_state_hash",
        }
    ),
    # UserPatch evidence is a canonical structured payload. Each nesting level
    # is closed over the fields emitted by UserPatchEvidencePackRuntime.
    "evidence_pack": frozenset(
        {
            "authoritative_evidence",
            "evidence_ref",
            "non_authoritative_hypothesis",
        }
    ),
    "authoritative_evidence": frozenset(
        {
            "asr_frame_ref",
            "asr_nbest",
            "asr_text_ref",
            "audio_span_id",
            "input_modality",
            "language_hint",
            "provenance",
            "redacted_text",
            "source_event_ids",
            "text_ref",
            "text_span_id",
            "transcript_hint_ref",
            "turn_id",
            "utterance_id",
        }
    ),
    "non_authoritative_hypothesis": frozenset(
        {
            "audio_summary_ref",
            "candidate_patch_types",
            "confidence",
            "evidence_uncertainty",
            "patch_hint",
            "provenance",
            "semantic_frame_ref",
            "semantic_summary_ref",
            "task_focus",
            "task_focus_confidence",
        }
    ),
    "provenance": frozenset(
        {
            "asr_nbest",
            "semantic_summary_ref",
            "task_focus",
            "text_ref",
        }
    ),
    "asr_nbest": frozenset(
        {
            "confidence",
            "evidence_ref",
            "redacted_text",
            "source",
            "source_event_id",
            "text_ref",
        }
    ),
    "semantic_summary_ref": frozenset(
        {"evidence_ref", "source", "source_event_id"}
    ),
    "task_focus": frozenset(
        {"evidence_ref", "source", "source_event_id"}
    ),
    "text_ref": frozenset(
        {"evidence_ref", "source", "source_event_id"}
    ),
}

ADR018_BOUNDED_PROSE_FIELDS = frozenset({"redacted_text"})
ADR018_MAX_COUNTER = 2_147_483_647
ADR018_MAX_TIMESTAMP_MS = 9_007_199_254_740_991
ADR018_TIMESTAMP_FIELDS = frozenset(
    {
        "created_monotonic_ms",
        "created_wall_clock_ms",
        "expires_at_monotonic_ms",
    }
)
ADR018_POSITIVE_INTEGER_FIELDS = frozenset(
    {
        "adopted_from_plan_version",
        "current_plan_version",
        "current_task_event_seq",
        "event_seq",
        "from_plan_version",
        "interpreted_against_plan_version",
        "observed_plan_version",
        "plan_version",
        "provider_session_generation",
        "result_plan_version",
        "retry_count",
        "source_event_seq",
        "superseded_plan_version",
        "task_event_seq",
        "to_plan_version",
    }
)
ADR018_NONNEGATIVE_INTEGER_FIELDS = frozenset(
    {
        "actual_stop_offset_ms",
        "audio_sample_offset",
        "candidate_audio_duration_ms",
        "chunk_duration_ms",
        "chunk_index",
        "cleanup_item_count",
        "cutoff_playback_offset_ms",
        "decoded_duration_ms",
        "delete_ack_count",
        "dropped_audio_frame_count",
        "duration_ms",
        "fast_interaction_adapter_event_emit_offset_ms",
        "fast_interaction_adapter_start_offset_ms",
        "fast_interaction_parse_validate_emit_ms",
        "fast_interaction_provider_first_chunk_offset_ms",
        "fast_interaction_provider_full_response_ms",
        "fast_interaction_provider_full_response_offset_ms",
        "fast_interaction_provider_generation_ms",
        "fast_interaction_provider_request_start_offset_ms",
        "fast_interaction_provider_ttft_ms",
        "fast_interaction_stream_decode_ms",
        "fast_interaction_total_ms",
        "final_playback_offset_ms",
        "interaction_state_version",
        "playback_epoch",
        "playback_offset_ms",
        "qwen_content_index",
        "qwen_input_content_index",
        "qwen_output_index",
        "silence_duration_ms",
        "task_focus_state_version",
        "timeout_ms",
    }
)


def _validate_adr018_safe_payloads(
    ordered_events: Sequence[Mapping[str, Any]],
) -> None:
    for event in ordered_events:
        event_name = str(event["event_name"])
        allowed_fields = _registered_event_field_names(event_name)
        unknown_fields = sorted(set(event).difference(allowed_fields))
        if unknown_fields:
            raise ReplayValidationError(
                f"{event_name} contains unregistered ADR-018 field "
                f"{unknown_fields[0]}"
            )
        if _contains_forbidden_adr018_payload_field(event):
            raise ReplayValidationError(
                f"{event_name} contains forbidden ADR-018 raw or "
                "provider payload"
            )
        try:
            sanitized, redacted_fields = sanitize_event_payload(event)
        except PayloadBlockedError as exc:
            raise ReplayValidationError(
                f"{event_name} contains unsafe ADR-018 payload: {exc}"
            ) from exc
        if redacted_fields or sanitized != dict(event):
            raise ReplayValidationError(
                f"{event_name} contains secret-bearing ADR-018 "
                "payload"
            )
        for field, value in event.items():
            _validate_adr018_bounded_metadata(
                value,
                event_name=event_name,
                field=str(field),
                depth=0,
            )
        _validate_adr018_safe_refs(event)


def _validate_adr018_bounded_metadata(
    value: object,
    *,
    event_name: str,
    field: str,
    depth: int,
) -> None:
    if depth > ADR018_MAX_METADATA_DEPTH:
        raise ReplayValidationError(
            f"ADR-018 {field} exceeds the bounded metadata depth"
        )
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise ReplayValidationError(
            f"ADR-018 {field} must not contain a binary payload container"
        )
    if _is_adr018_singular_reason_field(field):
        _validate_adr018_reason_code(value, field=field)
        return
    if _is_adr018_plural_reason_field(field):
        if isinstance(value, str) or not isinstance(value, Sequence):
            raise ReplayValidationError(
                f"ADR-018 {field} must be a bounded safe reason code sequence"
            )
        if len(value) > ADR018_MAX_SEQUENCE_ITEMS:
            raise ReplayValidationError(
                f"ADR-018 {field} exceeds the bounded metadata sequence limit"
            )
        for child in value:
            if field.casefold() == "failure_reasons":
                if (
                    not isinstance(child, str)
                    or ADR018_SAFE_FAILURE_REASON_PATTERN.fullmatch(child)
                    is None
                ):
                    raise ReplayValidationError(
                        "ADR-018 failure_reasons must contain symbolic codes "
                        "or structured code diagnostics"
                    )
            else:
                _validate_adr018_reason_code(child, field=field)
        return
    if _is_adr018_confidence_field(field):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or (
                isinstance(value, float)
                and not math.isfinite(value)
            )
            or not 0.0 <= value <= 1.0
        ):
            raise ReplayValidationError(
                f"ADR-018 {field} confidence must be a finite number "
                "in the inclusive range 0..1"
            )
        return
    if field in ADR018_TIMESTAMP_FIELDS:
        _validate_adr018_bounded_integer(
            value,
            field=field,
            minimum=0,
            maximum=ADR018_MAX_TIMESTAMP_MS,
        )
        return
    if field in ADR018_POSITIVE_INTEGER_FIELDS:
        _validate_adr018_bounded_integer(
            value,
            field=field,
            minimum=1,
            maximum=ADR018_MAX_COUNTER,
        )
        return
    if field in ADR018_NONNEGATIVE_INTEGER_FIELDS:
        _validate_adr018_bounded_integer(
            value,
            field=field,
            minimum=0,
            maximum=ADR018_MAX_COUNTER,
        )
        return
    if (
        event_name == "SLOW_TO_FAST_HANDOFF_EMITTED"
        and field == "priority"
    ):
        _validate_adr018_bounded_integer(
            value,
            field=field,
            minimum=0,
            maximum=ADR018_MAX_COUNTER,
        )
        return
    if isinstance(value, str):
        if len(value) > ADR018_MAX_METADATA_STRING_CHARS:
            raise ReplayValidationError(
                f"ADR-018 {field} exceeds the bounded metadata string limit"
            )
        if (
            field.casefold() not in ADR018_BOUNDED_PROSE_FIELDS
            and not _is_adr018_ref_field(field)
            and ADR018_SAFE_SYMBOLIC_METADATA_PATTERN.fullmatch(value) is None
        ):
            raise ReplayValidationError(
                f"ADR-018 {field} string metadata must be symbolic"
            )
        return
    if isinstance(value, Mapping):
        if len(value) > ADR018_MAX_MAPPING_ITEMS:
            raise ReplayValidationError(
                f"ADR-018 {field} exceeds the bounded metadata mapping limit"
            )
        allowed_nested_fields = ADR018_NESTED_FIELDS_BY_PARENT.get(field)
        if allowed_nested_fields is None:
            raise ReplayValidationError(
                f"ADR-018 {field} has no registered nested metadata schema"
            )
        nested_fields = set(value)
        unknown_nested_fields = sorted(
            str(nested_field)
            for nested_field in nested_fields.difference(
                allowed_nested_fields
            )
        )
        if unknown_nested_fields:
            raise ReplayValidationError(
                f"ADR-018 {field} contains unregistered nested field "
                f"{unknown_nested_fields[0]}"
            )
        if field == "confidence_summary" and (
            nested_fields != allowed_nested_fields
        ):
            raise ReplayValidationError(
                "ADR-018 confidence_summary must match its registered "
                "nested schema"
            )
        for nested_field, child in value.items():
            if not isinstance(nested_field, str):
                raise ReplayValidationError(
                    f"ADR-018 {field} contains unregistered nested field "
                    f"{nested_field}"
                )
            _validate_adr018_bounded_metadata(
                child,
                event_name=event_name,
                field=nested_field,
                depth=depth + 1,
            )
        return
    if isinstance(value, Sequence):
        if len(value) > ADR018_MAX_SEQUENCE_ITEMS:
            raise ReplayValidationError(
                f"ADR-018 {field} exceeds the bounded metadata sequence limit"
            )
        for child in value:
            _validate_adr018_bounded_metadata(
                child,
                event_name=event_name,
                field=field,
                depth=depth + 1,
            )
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise ReplayValidationError(
            f"ADR-018 {field} must contain a finite metadata number"
        )
    if value is None or type(value) is bool:
        return
    if type(value) in {int, float}:
        raise ReplayValidationError(
            f"ADR-018 {field} has no registered bounded numeric schema"
        )
    raise ReplayValidationError(
        f"ADR-018 {field} contains unsupported metadata type"
    )


def _validate_adr018_bounded_integer(
    value: object,
    *,
    field: str,
    minimum: int,
    maximum: int,
) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or value > maximum
    ):
        raise ReplayValidationError(
            f"ADR-018 {field} must be a bounded integer from "
            f"{minimum} to {maximum}"
        )


def _is_adr018_singular_reason_field(field: str) -> bool:
    folded = field.casefold()
    return folded == "reason" or folded.endswith("_reason")


def _is_adr018_plural_reason_field(field: str) -> bool:
    return field.casefold().endswith("_reasons")


def _validate_adr018_reason_code(value: object, *, field: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) > ADR018_MAX_REASON_CODE_CHARS
        or ADR018_SAFE_REASON_CODE_PATTERN.fullmatch(value) is None
    ):
        raise ReplayValidationError(
            f"ADR-018 {field} must be a bounded safe reason code string"
        )


def _is_adr018_confidence_field(field: str) -> bool:
    folded = field.casefold()
    return (
        folded == "confidence"
        or (
            folded.endswith("_confidence")
            and folded != "confidence_summary"
        )
    )


def _is_adr018_ref_field(field: str) -> bool:
    folded = field.casefold()
    return folded.endswith("_ref") or folded.endswith("_refs")


def _validate_adr018_raw_canonical_value(
    value: object,
    *,
    field: str = "events",
) -> None:
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise ReplayValidationError(
            f"ADR-018 {field} must not contain a binary payload container"
        )
    if type(value) is dict:
        for nested_field, child in value.items():
            if type(nested_field) is not str:
                raise ReplayValidationError(
                    f"ADR-018 {field} keys must be plain strings"
                )
            _validate_adr018_raw_canonical_value(
                child,
                field=nested_field,
            )
        return
    if isinstance(value, Mapping):
        raise ReplayValidationError(
            f"ADR-018 {field} must use a plain mapping container"
        )
    if type(value) in {list, tuple}:
        for child in value:
            _validate_adr018_raw_canonical_value(child, field=field)
        return
    if isinstance(value, Sequence) and not isinstance(value, str):
        raise ReplayValidationError(
            f"ADR-018 {field} must use a plain sequence container"
        )
    if isinstance(value, str):
        if type(value) is not str:
            raise ReplayValidationError(
                f"ADR-018 {field} must use a plain string"
            )
        return
    if value is None or type(value) in {bool, int, float}:
        return
    raise ReplayValidationError(
        f"ADR-018 {field} contains unsupported canonical metadata type"
    )


def _contains_forbidden_adr018_payload_field(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).casefold() in ADR018_FORBIDDEN_PAYLOAD_FIELDS:
                return True
            if _contains_forbidden_adr018_payload_field(child):
                return True
        return False
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return any(
            _contains_forbidden_adr018_payload_field(child)
            for child in value
        )
    return False


ADR018_STRUCTURED_REF_PARENT_SUFFIXES = frozenset(
    {
        ("provenance", "semantic_summary_ref"),
        ("provenance", "task_focus"),
        ("provenance", "text_ref"),
    }
)
ADR018_EVENT_ID_EVIDENCE_REF_SUFFIXES = frozenset(
    {
        ("provenance", "task_focus", "evidence_ref"),
    }
)
ADR018_SAFE_EVENT_ID_PATTERN = re.compile(
    r"\Aevt_[A-Za-z0-9][A-Za-z0-9._:-]{0,254}\Z"
)


def _validate_adr018_safe_refs(
    value: object,
    *,
    path: tuple[str, ...] = (),
) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = key
            key_fold = key_text.casefold()
            child_path = (*path, key_text)
            if key_fold.endswith("_ref"):
                if _path_has_suffix(
                    child_path,
                    ADR018_STRUCTURED_REF_PARENT_SUFFIXES,
                ):
                    if not isinstance(child, Mapping):
                        raise ReplayValidationError(
                            f"ADR-018 {key_text} must be structured provenance"
                        )
                elif _path_has_suffix(
                    child_path,
                    ADR018_EVENT_ID_EVIDENCE_REF_SUFFIXES,
                ):
                    _validate_one_adr018_event_id_ref(
                        child,
                        field=key_text,
                        expected_event_id=value.get("source_event_id"),
                    )
                else:
                    _validate_one_adr018_safe_ref(child, field=key_text)
            elif key_fold.endswith("_refs"):
                if (
                    isinstance(child, (str, bytes))
                    or not isinstance(child, Sequence)
                ):
                    raise ReplayValidationError(
                        f"ADR-018 {key_text} must be a safe ref sequence"
                    )
                for item in child:
                    _validate_one_adr018_safe_ref(item, field=key_text)
            _validate_adr018_safe_refs(child, path=child_path)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            _validate_adr018_safe_refs(child, path=path)


def _path_has_suffix(
    path: tuple[str, ...],
    suffixes: frozenset[tuple[str, ...]],
) -> bool:
    return any(
        len(path) >= len(suffix)
        and path[-len(suffix):] == suffix
        for suffix in suffixes
    )


def _validate_one_adr018_event_id_ref(
    value: object,
    *,
    field: str,
    expected_event_id: object,
) -> None:
    if (
        not isinstance(value, str)
        or ADR018_SAFE_EVENT_ID_PATTERN.fullmatch(value) is None
        or value != expected_event_id
    ):
        raise ReplayValidationError(
            f"ADR-018 {field} must match its canonical source event id"
        )


def _validate_one_adr018_safe_ref(value: object, *, field: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > ADR018_MAX_SAFE_REF_CHARS
        or ADR018_SAFE_REF_PATTERN.fullmatch(value) is None
    ):
        raise ReplayValidationError(f"ADR-018 {field} must be a safe ref")
    if any(
        _contains_unsafe_asr_ref_content(view)
        for view in _asr_ref_safety_views(value)
    ):
        raise ReplayValidationError(
            f"ADR-018 {field} contains an unsafe ref"
        )


def _validate_adr018_state_transitions(
    ordered_events: Sequence[Mapping[str, Any]],
    *,
    events_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    state = QwenParallelState()
    for event in ordered_events:
        if event.get("event_name") == "PROVIDER_CONTEXT_STATE_CHANGED":
            for source_event_id in _required_string_refs(
                event,
                "source_event_ids",
                event_name="PROVIDER_CONTEXT_STATE_CHANGED",
                allow_empty=True,
            ):
                _require_prior_event(
                    event,
                    source_event_id,
                    events_by_id=events_by_id,
                    label="source_event_ids",
                )
        try:
            state.reduce_event(event)
        except ValueError as exc:
            raise ReplayValidationError(str(exc)) from exc


def _validate_adr018_provider_readiness(
    ordered_events: Sequence[Mapping[str, Any]],
) -> None:
    provider_state = "CLOSED"
    provider_generation: int | None = None
    provider_generation_by_audio_span: dict[str, int] = {}
    speech_generation_evidence: dict[str, dict[str, int]] = {}
    provider_context_before_event: dict[str, tuple[str, int | None]] = {}
    events_by_id = {
        str(event["event_id"]): event
        for event in ordered_events
    }

    for event in ordered_events:
        event_name = str(event["event_name"])
        provider_context_before_event[str(event["event_id"])] = (
            provider_state,
            provider_generation,
        )
        if event_name == "PROVIDER_CONTEXT_STATE_CHANGED":
            provider_state = str(event.get("to_state"))
            generation = event.get("provider_session_generation")
            provider_generation = (
                int(generation)
                if isinstance(generation, int)
                and not isinstance(generation, bool)
                else None
            )
            continue

        if event_name in {
            "SPEECH_START_DETECTED",
            "SPEECH_END_DETECTED",
        } and event.get("provider_session_generation") not in (None, ""):
            generation = _required_nonnegative_int(
                event,
                "provider_session_generation",
                event_name=event_name,
            )
            audio_span_id = _required_text(
                event,
                "audio_span_id",
                event_name=event_name,
            )
            prior_generation = provider_generation_by_audio_span.get(
                audio_span_id
            )
            if (
                prior_generation is not None
                and prior_generation != generation
            ):
                raise ReplayValidationError(
                    "provider-backed audio span cannot change provider "
                    "generation"
                )
            provider_generation_by_audio_span[audio_span_id] = generation
            speech_generation_evidence.setdefault(audio_span_id, {})[
                event_name
            ] = generation

        if event_name in {"TURN_INGRESS_ACCEPTED", "TURN_INGRESS_COMMITTED"}:
            audio_span_id = event.get("audio_span_id")
            audio_generation = provider_generation_by_audio_span.get(
                str(audio_span_id)
            )
            if audio_generation is None:
                continue
            if (
                provider_state != "CLEAN"
                or provider_generation != audio_generation
            ):
                raise ReplayValidationError(
                    f"{event_name} provider-backed turn requires current CLEAN "
                    "provider generation"
                )
            continue

        if (
            event_name == "PLAYBACK_SPAN_STARTED"
            and event.get("release_token_ref") not in (None, "")
        ):
            playback_generation = _required_nonnegative_int(
                event,
                "provider_session_generation",
                event_name=event_name,
            )
            if (
                provider_state != "CLEAN"
                or provider_generation != playback_generation
            ):
                raise ReplayValidationError(
                    "provider-native first-byte playback requires current "
                    "CLEAN provider generation"
                )

    _validate_adr018_provider_backed_ingress(
        ordered_events,
        events_by_id=events_by_id,
        provider_context_before_event=provider_context_before_event,
    )

    for asr_event in ordered_events:
        if (
            asr_event.get("event_name")
            != "ASR_TRANSCRIPT_OUTPUT_EMITTED"
            or asr_event.get("provider_session_generation") in (None, "")
        ):
            continue
        committed_event = events_by_id.get(
            str(asr_event.get("caused_by_event_id", ""))
        )
        if (
            committed_event is None
            or committed_event.get("event_name")
            != "TURN_INGRESS_COMMITTED"
            or committed_event.get("input_modality") != "audio"
        ):
            raise ReplayValidationError(
                "Qwen final ASR must be caused by its exact audio "
                "TURN_INGRESS_COMMITTED event"
            )
        expected_generation = _required_nonnegative_int(
            asr_event,
            "provider_session_generation",
            event_name="ASR_TRANSCRIPT_OUTPUT_EMITTED",
        )
        audio_span_id = _required_text(
            committed_event,
            "audio_span_id",
            event_name="TURN_INGRESS_COMMITTED",
        )
        if asr_event.get("audio_span_id") != audio_span_id:
            raise ReplayValidationError(
                "Qwen final ASR must preserve its committed audio_span_id"
            )
        accepted_event = events_by_id.get(
            str(committed_event.get("caused_by_event_id", ""))
        )
        if (
            accepted_event is None
            or accepted_event.get("event_name") != "TURN_INGRESS_ACCEPTED"
        ):
            raise ReplayValidationError(
                "Qwen final ASR requires TURN_INGRESS_COMMITTED to reference "
                "the exact prior TURN_INGRESS_ACCEPTED event"
            )
        if (
            accepted_event.get("turn_id") != committed_event.get("turn_id")
            or accepted_event.get("audio_span_id") != audio_span_id
        ):
            raise ReplayValidationError(
                "Qwen final ASR TURN_INGRESS_ACCEPTED must match the "
                "committed turn_id and audio_span_id"
            )
        speech_end_event = events_by_id.get(
            str(accepted_event.get("caused_by_event_id", ""))
        )
        audio_ended_event = (
            events_by_id.get(
                str(speech_end_event.get("caused_by_event_id", ""))
            )
            if speech_end_event is not None
            else None
        )
        speech_start_event = (
            events_by_id.get(
                str(audio_ended_event.get("caused_by_event_id", ""))
            )
            if audio_ended_event is not None
            else None
        )
        if (
            speech_end_event is None
            or speech_end_event.get("event_name") != "SPEECH_END_DETECTED"
            or audio_ended_event is None
            or audio_ended_event.get("event_name") != "AUDIO_SPAN_ENDED"
            or speech_start_event is None
            or speech_start_event.get("event_name")
            != "SPEECH_START_DETECTED"
            or any(
                event.get("audio_span_id") != audio_span_id
                for event in (
                    speech_start_event,
                    audio_ended_event,
                    speech_end_event,
                )
            )
            or not _event_seq_strictly_increases(
                speech_start_event,
                audio_ended_event,
                speech_end_event,
                accepted_event,
                committed_event,
                asr_event,
            )
        ):
            raise ReplayValidationError(
                "Qwen final ASR requires the exact prior speech-start to "
                "ingress-commit causal topology for its audio_span_id"
            )
        expected_context = ("CLEAN", expected_generation)
        provider_checkpoints = (
            ("speech start", speech_start_event),
            ("speech end", speech_end_event),
            ("ingress acceptance", accepted_event),
            ("ingress commit", committed_event),
        )
        for checkpoint, checkpoint_event in provider_checkpoints:
            if provider_context_before_event.get(
                str(checkpoint_event["event_id"])
            ) != expected_context:
                raise ReplayValidationError(
                    f"Qwen final ASR requires CLEAN generation "
                    f"{expected_generation} at {checkpoint}"
                )
        for window_event in ordered_events:
            if (
                window_event.get("event_name")
                != "PROVIDER_CONTEXT_STATE_CHANGED"
                or not _event_seq_strictly_increases(
                    speech_start_event,
                    window_event,
                    committed_event,
                )
            ):
                continue
            if (
                window_event.get("to_state") != "CLEAN"
                or window_event.get("provider_session_generation")
                != expected_generation
            ):
                raise ReplayValidationError(
                    "Qwen final ASR requires an uninterrupted CLEAN provider "
                    "generation throughout the speech-start to ingress-commit "
                    "window"
                )
        commit_provider_context = provider_context_before_event.get(
            str(committed_event["event_id"])
        )
        generation_evidence = speech_generation_evidence.get(
            audio_span_id,
            {},
        )
        if (
            commit_provider_context != expected_context
            or any(
                generation != expected_generation
                for generation in generation_evidence.values()
            )
        ):
            raise ReplayValidationError(
                "Qwen final ASR requires every recorded speech generation to "
                "match the CLEAN provider context at ingress commit"
            )


def _validate_adr018_provider_backed_ingress(
    ordered_events: Sequence[Mapping[str, Any]],
    *,
    events_by_id: Mapping[str, Mapping[str, Any]],
    provider_context_before_event: Mapping[
        str,
        tuple[str, int | None],
    ],
) -> None:
    for speech_end in ordered_events:
        if speech_end.get("event_name") != "SPEECH_END_DETECTED":
            continue
        audio_ended = events_by_id.get(
            str(speech_end.get("caused_by_event_id", ""))
        )
        speech_start = (
            events_by_id.get(
                str(audio_ended.get("caused_by_event_id", ""))
            )
            if audio_ended is not None
            else None
        )
        if not (
            _is_adr018_qwen_speech_detection(speech_end)
            or (
                speech_start is not None
                and _is_adr018_qwen_speech_detection(speech_start)
            )
            or _has_adr018_qwen_provider_session_before(
                speech_end,
                ordered_events=ordered_events,
            )
        ):
            continue
        audio_span_id = _required_text(
            speech_end,
            "audio_span_id",
            event_name="SPEECH_END_DETECTED",
        )
        audio_started = (
            events_by_id.get(
                str(speech_start.get("caused_by_event_id", ""))
            )
            if speech_start is not None
            else None
        )
        if (
            audio_ended is None
            or audio_ended.get("event_name") != "AUDIO_SPAN_ENDED"
            or speech_start is None
            or speech_start.get("event_name") != "SPEECH_START_DETECTED"
            or audio_started is None
            or audio_started.get("event_name") != "AUDIO_SPAN_STARTED"
            or any(
                event.get("audio_span_id") != audio_span_id
                for event in (audio_started, speech_start, audio_ended)
            )
        ):
            raise ReplayValidationError(
                "Qwen provider-backed ingress requires exact "
                "AUDIO_SPAN_STARTED to speech-start/end causal topology"
            )
        for detection in (speech_start, speech_end):
            provider_event_ref = detection.get("provider_event_ref")
            if (
                provider_event_ref not in (None, "")
                and (
                    not isinstance(provider_event_ref, str)
                    or not provider_event_ref.startswith("qwen-event://")
                )
            ):
                raise ReplayValidationError(
                    "Qwen speech detection provider_event_ref must use the "
                    "canonical qwen-event ref namespace"
                )

        turn_opened_matches = [
            event
            for event in ordered_events
            if event.get("event_name") == "TURN_OPENED"
            and event.get("caused_by_event_id") == speech_start.get("event_id")
            and event.get("audio_span_id") == audio_span_id
            and event.get("input_modality") == "audio"
        ]
        if len(turn_opened_matches) != 1:
            raise ReplayValidationError(
                "Qwen provider-backed ingress requires exactly one audio "
                "TURN_OPENED caused by SPEECH_START_DETECTED"
            )
        turn_opened = turn_opened_matches[0]
        turn_id = _required_text(
            turn_opened,
            "turn_id",
            event_name="TURN_OPENED",
        )
        terminals = [
            event
            for event in ordered_events
            if event.get("event_name")
            in {"TURN_INGRESS_ACCEPTED", "TURN_INGRESS_REJECTED"}
            and event.get("turn_id") == turn_id
            and event.get("audio_span_id") == audio_span_id
            and _event_seq_before(speech_end, event)
        ]
        if len(terminals) != 1:
            raise ReplayValidationError(
                "Qwen provider-backed speech requires exactly one matching "
                "ACCEPTED or REJECTED ingress terminal"
            )
        terminal = terminals[0]
        expected_outcome = (
            "ACCEPTED"
            if terminal.get("event_name") == "TURN_INGRESS_ACCEPTED"
            else "REJECTED"
        )
        if (
            terminal.get("caused_by_event_id") != speech_end.get("event_id")
            or terminal.get("ingress_outcome") != expected_outcome
            or not _event_seq_strictly_increases(
                audio_started,
                speech_start,
                turn_opened,
                audio_ended,
                speech_end,
                terminal,
            )
        ):
            raise ReplayValidationError(
                "Qwen provider-backed ingress requires exact speech, "
                "TURN_OPENED, and terminal causal order"
            )

        commits = [
            event
            for event in ordered_events
            if event.get("event_name") == "TURN_INGRESS_COMMITTED"
            and event.get("turn_id") == turn_id
            and event.get("audio_span_id") == audio_span_id
            and _event_seq_before(terminal, event)
        ]
        if len(commits) > 1:
            raise ReplayValidationError(
                "Qwen provider-backed ingress allows at most one matching "
                "TURN_INGRESS_COMMITTED"
            )
        commit = commits[0] if commits else None
        if commit is not None and (
            terminal.get("event_name") != "TURN_INGRESS_ACCEPTED"
            or commit.get("caused_by_event_id") != terminal.get("event_id")
            or commit.get("input_modality") != "audio"
        ):
            raise ReplayValidationError(
                "Qwen provider-backed commit requires the exact prior "
                "TURN_INGRESS_ACCEPTED authority"
            )
        if (
            terminal.get("event_name") == "TURN_INGRESS_REJECTED"
            and commit is not None
        ):
            raise ReplayValidationError(
                "REJECTED Qwen provider-backed ingress cannot commit"
            )

        initial_context = provider_context_before_event.get(
            str(audio_started["event_id"])
        )
        expected_generation = (
            initial_context[1]
            if initial_context is not None
            else None
        )
        context_checkpoints = (
            audio_started,
            speech_start,
            turn_opened,
            audio_ended,
            speech_end,
            terminal,
            *((commit,) if commit is not None else ()),
        )
        clean_generation = (
            isinstance(expected_generation, int)
            and not isinstance(expected_generation, bool)
            and expected_generation >= 1
            and all(
                provider_context_before_event.get(str(event["event_id"]))
                == ("CLEAN", expected_generation)
                for event in context_checkpoints
            )
        )
        window_terminal = commit or terminal
        if clean_generation and any(
            event.get("event_name") == "PROVIDER_CONTEXT_STATE_CHANGED"
            and _event_seq_strictly_increases(
                audio_started,
                event,
                window_terminal,
            )
            and (
                event.get("to_state") != "CLEAN"
                or event.get("provider_session_generation")
                != expected_generation
            )
            for event in ordered_events
        ):
            clean_generation = False
        if expected_generation is not None:
            for detection in (speech_start, speech_end):
                recorded_generation = detection.get(
                    "provider_session_generation"
                )
                if (
                    recorded_generation not in (None, "")
                    and recorded_generation != expected_generation
                ):
                    raise ReplayValidationError(
                        "Qwen speech generation evidence must match its "
                        "provider session generation"
                    )

        stop_reason = speech_end.get("provider_stop_reason")
        invalid_stop = stop_reason not in (None, "")
        if (
            terminal.get("event_name") == "TURN_INGRESS_ACCEPTED"
            and (invalid_stop or not clean_generation)
        ):
            raise ReplayValidationError(
                "invalid, unknown, or non-CLEAN Qwen speech stop requires the "
                "exact TURN_INGRESS_REJECTED terminal"
            )


def _is_adr018_qwen_speech_detection(
    event: Mapping[str, Any],
) -> bool:
    provider_event_ref = event.get("provider_event_ref")
    return (
        event.get("provider_session_generation") not in (None, "")
        or (
            isinstance(provider_event_ref, str)
            and provider_event_ref.startswith("qwen-event://")
        )
        or event.get("provider_stop_reason") not in (None, "")
    )


def _has_adr018_qwen_provider_session_before(
    event: Mapping[str, Any],
    *,
    ordered_events: Sequence[Mapping[str, Any]],
) -> bool:
    event_seq = int(event["event_seq"])
    return any(
        candidate.get("event_name") == "PROVIDER_CONTEXT_STATE_CHANGED"
        and int(candidate["event_seq"]) < event_seq
        and isinstance(candidate.get("adapter_id"), str)
        and "qwen_realtime" in str(candidate["adapter_id"])
        and isinstance(candidate.get("provider_session_generation"), int)
        and not isinstance(
            candidate.get("provider_session_generation"),
            bool,
        )
        and int(candidate["provider_session_generation"]) >= 1
        for candidate in ordered_events
    )


ADR018_CONTEXT_SNAPSHOT_IDENTITY_FIELDS = (
    "provider_session_generation",
    "source_event_seq",
    "interaction_state_version",
    "task_focus_state_version",
    "active_task_ref",
    "active_task_state",
    "plan_version",
    "task_event_seq",
    "pending_confirmation_ref",
    "last_assistant_act",
    "recent_dialogue_refs",
    "session_summary_ref",
    "persona_profile_id",
    "policy_versions",
    "redaction_status",
)


def _validate_adr018_projection_prefixes(
    ordered_events: Sequence[Mapping[str, Any]],
    *,
    events_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    event_seqs = {int(event["event_seq"]) for event in ordered_events}
    projection_ids: dict[str, str] = {}
    projection_refs: dict[str, tuple[object, ...]] = {}
    snapshot_identities: dict[str, dict[str, object]] = {}

    for event in ordered_events:
        if event.get("event_name") != "MODEL_CONTEXT_PROJECTION_EMITTED":
            continue
        event_id = str(event["event_id"])
        event_seq = int(event["event_seq"])
        source_event_seq = _required_nonnegative_int(
            event,
            "source_event_seq",
            event_name="MODEL_CONTEXT_PROJECTION_EMITTED",
        )
        if source_event_seq not in event_seqs or source_event_seq >= event_seq:
            raise ReplayValidationError(
                "MODEL_CONTEXT_PROJECTION_EMITTED source_event_seq must point "
                "to an existing prior replay prefix"
            )
        source_event_ids = _required_string_refs(
            event,
            "source_event_ids",
            event_name="MODEL_CONTEXT_PROJECTION_EMITTED",
        )
        if not source_event_ids:
            raise ReplayValidationError(
                "MODEL_CONTEXT_PROJECTION_EMITTED source_event_ids must not be empty"
            )
        for source_event_id in source_event_ids:
            source_event = events_by_id.get(source_event_id)
            if (
                source_event is None
                or int(source_event["event_seq"]) > source_event_seq
            ):
                raise ReplayValidationError(
                    "MODEL_CONTEXT_PROJECTION_EMITTED source_event_ids must "
                    "belong to the declared immutable source prefix"
                )
        latest_fence_seq = max(
            (
                int(candidate["event_seq"])
                for candidate in ordered_events
                if int(candidate["event_seq"]) < event_seq
                and (
                    candidate.get("event_name") == "INTERRUPT_CANDIDATE"
                    or (
                        candidate.get("event_name")
                        == "PROVIDER_CONTEXT_STATE_CHANGED"
                        and candidate.get("to_state") == "REBUILDING"
                    )
                )
            ),
            default=0,
        )
        if (
            source_event_seq < latest_fence_seq
            or any(
                int(events_by_id[source_event_id]["event_seq"])
                < latest_fence_seq
                for source_event_id in source_event_ids
            )
        ):
            raise ReplayValidationError(
                "MODEL_CONTEXT_PROJECTION_EMITTED source prefix cannot cross "
                "the latest interrupt or provider-rebuild fence"
            )

        projection_id = _required_text(
            event,
            "projection_id",
            event_name="MODEL_CONTEXT_PROJECTION_EMITTED",
        )
        if projection_id in projection_ids:
            raise ReplayValidationError(
                "MODEL_CONTEXT_PROJECTION_EMITTED projection_id must be unique"
            )
        projection_ids[projection_id] = event_id

        projection_ref = _required_text(
            event,
            "projection_ref",
            event_name="MODEL_CONTEXT_PROJECTION_EMITTED",
        )
        fingerprint = (
            projection_id,
            event.get("target_role"),
            tuple(source_event_ids),
            event.get("context_snapshot_id"),
            source_event_seq,
            event.get("provider_session_generation"),
            event.get("policy_version"),
        )
        prior_fingerprint = projection_refs.get(projection_ref)
        if prior_fingerprint is not None and prior_fingerprint != fingerprint:
            raise ReplayValidationError(
                "MODEL_CONTEXT_PROJECTION_EMITTED projection_ref is immutable"
            )
        projection_refs[projection_ref] = fingerprint

        snapshot_id = _required_text(
            event,
            "context_snapshot_id",
            event_name="MODEL_CONTEXT_PROJECTION_EMITTED",
        )
        generation = _required_nonnegative_int(
            event,
            "provider_session_generation",
            event_name="MODEL_CONTEXT_PROJECTION_EMITTED",
        )
        snapshot_identity = {
            field: deepcopy(event.get(field))
            for field in ADR018_CONTEXT_SNAPSHOT_IDENTITY_FIELDS
        }
        prior_identity = snapshot_identities.get(snapshot_id)
        if (
            prior_identity is not None
            and prior_identity != snapshot_identity
        ):
            raise ReplayValidationError(
                "context_snapshot_id cannot be rebound to another provider "
                "generation, immutable source prefix, or task/session identity"
            )
        snapshot_identities[snapshot_id] = snapshot_identity


def _validate_adr018_rejected_turn_terminals(
    ordered_events: Sequence[Mapping[str, Any]],
) -> None:
    rejected_turns: dict[str, int] = {}
    downstream_names = {
        "TURN_INGRESS_COMMITTED",
        "ASR_TRANSCRIPT_OUTPUT_EMITTED",
        "ROUTE_EVIDENCE_OUTPUT_EMITTED",
        "ROUTER_DECISION_EMITTED",
        "CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED",
        "FAST_INTERACTION_OUTPUT_EMITTED",
        "FOREGROUND_REPLY_CANDIDATE_EMITTED",
        "FOREGROUND_ACT_GATE_PASSED",
        "FOREGROUND_ACT_GATE_FAILED",
        "FOREGROUND_OUTPUT_COMMITTED",
        "FOREGROUND_OUTPUT_DISCARDED",
        "PLAYBACK_SPAN_STARTED",
    }
    for event in ordered_events:
        event_name = str(event["event_name"])
        turn_id = event.get("turn_id")
        if event_name == "TURN_INGRESS_REJECTED":
            rejected_turns[str(turn_id)] = int(event["event_seq"])
            continue
        if (
            event_name in downstream_names
            and turn_id not in (None, "")
            and str(turn_id) in rejected_turns
            and int(event["event_seq"]) > rejected_turns[str(turn_id)]
        ):
            raise ReplayValidationError(
                "rejected smart-turn ingress cannot create downstream "
                "understanding, routing, Gate, output, or playback authority"
            )


ADR018_HANDOFF_SOURCE_EVENT_NAMES_BY_KIND = {
    "PROGRESS": (
        ALLOWED_PROGRESS_SOURCE_EVENTS
        - {
            "WAITING_FOR_USER_CONFIRMATION",
            "SLOWTASK_DEGRADED",
            "SLOWTASK_FAILED",
        }
    )
    | {"TASK_REPLANNED"},
    "CLARIFICATION": frozenset({"CLARIFICATION_REQUESTED"}),
    "CONFIRMATION": frozenset(
        {
            "CONFIRMATION_REQUIRED",
            "WAITING_FOR_USER_CONFIRMATION",
            "CONFIRMATION_ACCEPTED",
            "CONFIRMATION_REJECTED",
        }
    ),
    "FINAL": frozenset({"SEMANTIC_COMMITMENT_EMITTED"}),
    "DEGRADED": frozenset({"SLOWTASK_DEGRADED"}),
    "FAILED": frozenset({"SLOWTASK_FAILED"}),
}
ADR018_HANDOFF_SELECTED_SOURCE_TYPE_BY_KIND = {
    "PROGRESS": "progress",
    "CLARIFICATION": "clarification",
    "CONFIRMATION": "confirmation",
    "FINAL": "final",
    "DEGRADED": "final",
    "FAILED": "final",
}
ADR018_HANDOFF_SOURCE_MODULES_BY_EVENT = {
    **ALLOWED_SOURCE_MODULES_BY_EVENT,
    "TASK_REPLANNED": frozenset({"slowtask_runtime"}),
    "CLARIFICATION_REQUESTED": frozenset({"slowtask_runtime"}),
    "CONFIRMATION_REQUIRED": frozenset({"slowtask_runtime"}),
    "CONFIRMATION_ACCEPTED": frozenset({"slowtask_runtime"}),
    "CONFIRMATION_REJECTED": frozenset({"slowtask_runtime"}),
}


def _validate_adr018_handoffs_and_delivery(
    ordered_events: Sequence[Mapping[str, Any]],
    *,
    events_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    handoffs_by_id: dict[str, Mapping[str, Any]] = {}
    handoffs_by_event_id: dict[str, Mapping[str, Any]] = {}
    arbitrations_by_event_id: dict[str, Mapping[str, Any]] = {}
    arbitration_ids: set[str] = set()
    delivery_items: set[str] = set()
    dispositioned_handoff_ids: set[str] = set()
    queued_handoff_ids: set[str] = set()
    terminally_dispositioned_handoff_ids: set[str] = set()
    selected_dispositions_by_handoff_id: dict[str, Mapping[str, Any]] = {}

    for event in ordered_events:
        event_name = str(event["event_name"])
        if event_name == "SLOW_TO_FAST_HANDOFF_EMITTED":
            handoff_id = _required_text(
                event,
                "handoff_id",
                event_name=event_name,
            )
            if handoff_id in handoffs_by_id:
                raise ReplayValidationError(
                    "SLOW_TO_FAST_HANDOFF_EMITTED handoff_id must be unique"
                )
            _require_prior_source_event_ids(
                event,
                events_by_id=events_by_id,
            )
            _validate_adr018_handoff_sources(
                event,
                ordered_events=ordered_events,
                events_by_id=events_by_id,
            )
            handoffs_by_id[handoff_id] = event
            handoffs_by_event_id[str(event["event_id"])] = event
            continue

        if event_name == "RESPONSE_ARBITRATION_DECIDED":
            arbitration_id = _required_text(
                event,
                "arbitration_id",
                event_name=event_name,
            )
            if arbitration_id in arbitration_ids:
                raise ReplayValidationError(
                    "RESPONSE_ARBITRATION_DECIDED arbitration_id must be unique"
                )
            arbitration_ids.add(arbitration_id)
            trigger = _require_prior_event(
                event,
                _required_text(
                    event,
                    "caused_by_event_id",
                    event_name=event_name,
                ),
                events_by_id=events_by_id,
                label="caused_by_event_id",
            )
            if not _is_adr018_arbitration_trigger(
                trigger,
                handoffs_by_event_id=handoffs_by_event_id,
                arbitrations_by_event_id=arbitrations_by_event_id,
            ):
                raise ReplayValidationError(
                    "RESPONSE_ARBITRATION_DECIDED caused_by_event_id must be "
                    "a canonical arbitration trigger"
                )
            selected_source_type = _required_text(
                event,
                "selected_source_type",
                event_name=event_name,
            )
            selected_source_event_id = event.get("selected_source_event_id")
            selected_source_absent = selected_source_event_id in (None, "")
            if (selected_source_type == "none") != selected_source_absent:
                raise ReplayValidationError(
                    "RESPONSE_ARBITRATION_DECIDED selected_source_type=none "
                    "must exactly match an absent selected_source_event_id"
                )
            if selected_source_event_id not in (None, ""):
                selected_source = _require_prior_event(
                    event,
                    str(selected_source_event_id),
                    events_by_id=events_by_id,
                    label="selected_source_event_id",
                )
                selected_handoff = handoffs_by_event_id.get(
                    str(selected_source_event_id)
                )
                if selected_source_type == "user_fast":
                    _validate_adr018_user_fast_arbitration_source(
                        event,
                        selected_source=selected_source,
                        ordered_events=ordered_events,
                        events_by_id=events_by_id,
                    )
                elif selected_source_type != "none":
                    if selected_handoff is None:
                        raise ReplayValidationError(
                            "confirmation, clarification, progress, and final "
                            "arbitration must select a canonical handoff"
                        )
                    if selected_handoff.get("expiry_status") != "CURRENT":
                        raise ReplayValidationError(
                            "response arbitration cannot select an expired "
                            "handoff"
                        )
                    expected_source_type = (
                        ADR018_HANDOFF_SELECTED_SOURCE_TYPE_BY_KIND.get(
                            str(selected_handoff.get("kind"))
                        )
                    )
                    if selected_source_type != expected_source_type:
                        raise ReplayValidationError(
                            "response arbitration selected_source_type must "
                            "match slow-to-fast handoff kind"
                        )
                    selected_handoff_id = str(
                        selected_handoff["handoff_id"]
                    )
                    if (
                        selected_handoff_id
                        in terminally_dispositioned_handoff_ids
                        or _adr018_actual_slowtask_identity_before(
                            event,
                            ordered_events=ordered_events,
                        )
                        != (
                            selected_handoff.get("task_id"),
                            selected_handoff.get("plan_version"),
                            selected_handoff.get("task_event_seq"),
                        )
                    ):
                        raise ReplayValidationError(
                            "response arbitration requires an exact CURRENT "
                            "handoff from the actual SlowTask prefix"
                        )
            superseded_event_ids = _required_string_refs(
                event,
                "superseded_source_event_ids",
                event_name=event_name,
                allow_empty=True,
            )
            if (
                not selected_source_absent
                and str(selected_source_event_id) in superseded_event_ids
            ):
                raise ReplayValidationError(
                    "response arbitration cannot both select and supersede the "
                    "same source event"
                )
            for superseded_event_id in superseded_event_ids:
                superseded_source = _require_prior_event(
                    event,
                    superseded_event_id,
                    events_by_id=events_by_id,
                    label="superseded_source_event_ids",
                )
                if not _is_adr018_supersedable_authority(
                    superseded_source,
                    handoffs_by_event_id=handoffs_by_event_id,
                    arbitrations_by_event_id=arbitrations_by_event_id,
                ):
                    raise ReplayValidationError(
                        "response arbitration may supersede only canonical "
                        "active or selection authority events"
                    )
            arbitrations_by_event_id[str(event["event_id"])] = event
            continue

        if event_name == "SLOW_TO_FAST_HANDOFF_DISPOSITIONED":
            handoff_id = _required_text(
                event,
                "handoff_id",
                event_name=event_name,
            )
            handoff = handoffs_by_id.get(handoff_id)
            if handoff is None or not _event_seq_before(handoff, event):
                raise ReplayValidationError(
                    "SLOW_TO_FAST_HANDOFF_DISPOSITIONED requires prior matching "
                    "handoff"
                )
            disposition = event.get("disposition")
            if handoff_id in terminally_dispositioned_handoff_ids:
                raise ReplayValidationError(
                    "slow-to-fast handoff cannot advance after its terminal "
                    "disposition"
                )
            if disposition == "QUEUED":
                if handoff_id in queued_handoff_ids:
                    raise ReplayValidationError(
                        "slow-to-fast handoff cannot be QUEUED more than once"
                    )
                queued_handoff_ids.add(handoff_id)
            else:
                terminally_dispositioned_handoff_ids.add(handoff_id)
            dispositioned_handoff_ids.add(handoff_id)
            if (
                handoff.get("expiry_status") == "EXPIRED"
                and disposition != "EXPIRED"
            ):
                raise ReplayValidationError(
                    "EXPIRED handoff requires an EXPIRED disposition"
                )
            if disposition == "SELECTED":
                if handoff.get("expiry_status") != "CURRENT":
                    raise ReplayValidationError(
                        "only a CURRENT slow-to-fast handoff can be SELECTED"
                    )
                arbitration_event_id = _required_text(
                    event,
                    "response_arbitration_event_id",
                    event_name=event_name,
                )
                arbitration = arbitrations_by_event_id.get(
                    arbitration_event_id
                )
                if (
                    arbitration is None
                    or not _event_seq_before(arbitration, event)
                    or arbitration.get("selected_source_event_id")
                    != handoff.get("event_id")
                ):
                    raise ReplayValidationError(
                        "SELECTED slow-to-fast handoff requires matching prior "
                        "response arbitration"
                    )
                _validate_adr018_handoff_current_identity(
                    event,
                    handoff=handoff,
                    disposition="SELECTED",
                    require_match=True,
                    ordered_events=ordered_events,
                )
                if _adr018_has_later_arbitration_supersession(
                    ordered_events,
                    after_event=arbitration,
                    before_event=event,
                    authority_event_ids={
                        str(handoff["event_id"]),
                        str(arbitration["event_id"]),
                    },
                ):
                    raise ReplayValidationError(
                        "SELECTED handoff authority was superseded by a later "
                        "response arbitration"
                    )
                selected_dispositions_by_handoff_id[handoff_id] = event
            elif disposition == "COALESCED":
                replacement_handoff_id = _required_text(
                    event,
                    "replacement_handoff_id",
                    event_name=event_name,
                )
                replacement = handoffs_by_id.get(replacement_handoff_id)
                if (
                    replacement is None
                    or replacement_handoff_id == handoff_id
                    or not _event_seq_strictly_increases(
                        handoff,
                        replacement,
                        event,
                    )
                    or replacement.get("expiry_status") != "CURRENT"
                    or replacement.get("task_id") != handoff.get("task_id")
                    or replacement.get("plan_version")
                    != handoff.get("plan_version")
                    or not isinstance(
                        replacement.get("task_event_seq"),
                        int,
                    )
                    or isinstance(
                        replacement.get("task_event_seq"),
                        bool,
                    )
                    or int(replacement["task_event_seq"])
                    <= int(handoff["task_event_seq"])
                    or ADR018_HANDOFF_SELECTED_SOURCE_TYPE_BY_KIND.get(
                        str(replacement.get("kind"))
                    )
                    != ADR018_HANDOFF_SELECTED_SOURCE_TYPE_BY_KIND.get(
                        str(handoff.get("kind"))
                    )
                    or replacement_handoff_id
                    in terminally_dispositioned_handoff_ids
                    or _adr018_actual_slowtask_identity_before(
                        event,
                        ordered_events=ordered_events,
                    )
                    != (
                        replacement.get("task_id"),
                        replacement.get("plan_version"),
                        replacement.get("task_event_seq"),
                    )
                ):
                    raise ReplayValidationError(
                        "COALESCED handoff requires a later, newer, CURRENT, "
                        "compatible, lifecycle-eligible replacement from the "
                        "same current task and plan"
                    )
            elif disposition == "STALE":
                _validate_adr018_handoff_current_identity(
                    event,
                    handoff=handoff,
                    disposition="STALE",
                    require_match=False,
                    ordered_events=ordered_events,
                )
            continue

        if event_name == "ASSISTANT_DELIVERY_DISPOSITIONED":
            assistant_item_ref = _required_text(
                event,
                "assistant_item_ref",
                event_name=event_name,
            )
            if assistant_item_ref in delivery_items:
                raise ReplayValidationError(
                    "assistant delivery disposition must be terminal exactly once"
                )
            delivery_items.add(assistant_item_ref)
            _require_prior_event(
                event,
                _required_text(
                    event,
                    "source_output_event_id",
                    event_name=event_name,
                ),
                events_by_id=events_by_id,
                label="source_output_event_id",
            )
            _require_prior_source_event_ids(
                event,
                events_by_id=events_by_id,
            )

    _validate_adr018_composer_projections(
        ordered_events,
        events_by_id=events_by_id,
        handoffs_by_event_id=handoffs_by_event_id,
        arbitrations_by_event_id=arbitrations_by_event_id,
        selected_dispositions_by_handoff_id=(
            selected_dispositions_by_handoff_id
        ),
    )

    missing_dispositions = set(handoffs_by_id).difference(
        dispositioned_handoff_ids
    )
    if missing_dispositions:
        raise ReplayValidationError(
            "every slow-to-fast handoff requires a replayable disposition"
        )


def _validate_adr018_handoff_sources(
    handoff: Mapping[str, Any],
    *,
    ordered_events: Sequence[Mapping[str, Any]],
    events_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    event_name = "SLOW_TO_FAST_HANDOFF_EMITTED"
    kind = _required_text(handoff, "kind", event_name=event_name)
    allowed_source_names = ADR018_HANDOFF_SOURCE_EVENT_NAMES_BY_KIND.get(kind)
    if allowed_source_names is None:
        raise ReplayValidationError(
            "slow-to-fast handoff kind has no canonical source policy"
        )
    source_event_ids = _required_string_refs(
        handoff,
        "source_event_ids",
        event_name=event_name,
    )
    if not source_event_ids or len(source_event_ids) != len(
        set(source_event_ids)
    ):
        raise ReplayValidationError(
            "slow-to-fast handoff requires unique canonical source events"
        )
    identity = (
        _required_text(handoff, "task_id", event_name=event_name),
        _required_nonnegative_int(
            handoff,
            "plan_version",
            event_name=event_name,
        ),
        _required_nonnegative_int(
            handoff,
            "task_event_seq",
            event_name=event_name,
        ),
    )
    source_events = [events_by_id[source_id] for source_id in source_event_ids]
    if any(
        source.get("event_name") not in allowed_source_names
        or source.get("task_id") != identity[0]
        or source.get("plan_version") != identity[1]
        or not isinstance(source.get("task_event_seq"), int)
        or isinstance(source.get("task_event_seq"), bool)
        or int(source["task_event_seq"]) > identity[2]
        for source in source_events
    ) or not any(
        source.get("task_event_seq") == identity[2]
        for source in source_events
    ):
        raise ReplayValidationError(
            "slow-to-fast handoff requires canonical kind-matched sources "
            "from the current plan through its exact latest task_event_seq"
        )
    for source in source_events:
        allowed_modules = ADR018_HANDOFF_SOURCE_MODULES_BY_EVENT.get(
            str(source["event_name"])
        )
        if (
            allowed_modules is None
            or source.get("source_module") not in allowed_modules
        ):
            raise ReplayValidationError(
                "slow-to-fast handoff source event must preserve its "
                "canonical source_module owner"
            )
    prefix_state = SlowTaskState()
    try:
        for candidate in ordered_events:
            if int(candidate["event_seq"]) >= int(handoff["event_seq"]):
                break
            prefix_state.reduce_event(candidate)
    except ValueError as exc:
        raise ReplayValidationError(str(exc)) from exc
    task_record = prefix_state.tasks.get(identity[0])
    latest_source_task_event_seq = max(
        int(source["task_event_seq"])
        for source in source_events
    )
    if (
        task_record is None
        or task_record.current_plan_version != identity[1]
        or max(
            task_record.current_task_event_seq,
            latest_source_task_event_seq,
        )
        != identity[2]
    ):
        raise ReplayValidationError(
            "slow-to-fast handoff identity must match the latest current "
            "task plan at emission"
        )


def _validate_adr018_handoff_current_identity(
    disposition_event: Mapping[str, Any],
    *,
    handoff: Mapping[str, Any],
    disposition: str,
    require_match: bool,
    ordered_events: Sequence[Mapping[str, Any]],
) -> None:
    event_name = "SLOW_TO_FAST_HANDOFF_DISPOSITIONED"
    current_identity = (
        _required_text(
            disposition_event,
            "current_task_id",
            event_name=event_name,
        ),
        _required_nonnegative_int(
            disposition_event,
            "current_plan_version",
            event_name=event_name,
        ),
        _required_nonnegative_int(
            disposition_event,
            "current_task_event_seq",
            event_name=event_name,
        ),
    )
    handoff_identity = (
        handoff.get("task_id"),
        handoff.get("plan_version"),
        handoff.get("task_event_seq"),
    )
    actual_identity = _adr018_actual_slowtask_identity_before(
        disposition_event,
        ordered_events=ordered_events,
    )
    if actual_identity is None or current_identity != actual_identity:
        raise ReplayValidationError(
            f"{disposition} handoff current task identity must match the "
            "actual SlowTask replay prefix"
        )
    identities_match = current_identity == handoff_identity
    if identities_match != require_match:
        expectation = (
            "matching current task identity"
            if require_match
            else "a complete current task identity mismatch"
        )
        raise ReplayValidationError(
            f"{disposition} handoff requires {expectation}"
        )


def _adr018_actual_slowtask_identity_before(
    event: Mapping[str, Any],
    *,
    ordered_events: Sequence[Mapping[str, Any]],
) -> tuple[str, int, int] | None:
    prefix_state = SlowTaskState()
    try:
        for candidate in ordered_events:
            if int(candidate["event_seq"]) >= int(event["event_seq"]):
                break
            prefix_state.reduce_event(candidate)
    except ValueError as exc:
        raise ReplayValidationError(str(exc)) from exc
    task_id = prefix_state.last_task_id
    if task_id is None:
        return None
    task = prefix_state.tasks[task_id]
    return (
        task.task_id,
        task.current_plan_version,
        task.current_task_event_seq,
    )


def _validate_adr018_user_fast_delivery_retirement(
    ordered_events: Sequence[Mapping[str, Any]],
    *,
    events_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    for arbitration in ordered_events:
        if (
            arbitration.get("event_name")
            != "RESPONSE_ARBITRATION_DECIDED"
            or arbitration.get("selected_source_type") != "user_fast"
            or arbitration.get("selected_source_event_id") in (None, "")
        ):
            continue
        selected_source_event_id = str(
            arbitration["selected_source_event_id"]
        )
        arbitration_seq = int(arbitration["event_seq"])
        for output in ordered_events:
            if (
                output.get("event_name")
                != "FOREGROUND_OUTPUT_COMMITTED"
                or not _is_adr018_parallel_event(output)
                or output.get("user_visible_channel") != "audio_pending"
                or output.get("output_basis") != "reply_candidate"
                or int(output["event_seq"]) >= arbitration_seq
            ):
                continue
            gate = events_by_id.get(
                str(output.get("gate_event_id", ""))
            )
            candidate = (
                events_by_id.get(
                    str(gate.get("candidate_event_id", ""))
                )
                if gate is not None
                else None
            )
            if (
                gate is None
                or gate.get("event_name")
                != "FOREGROUND_ACT_GATE_PASSED"
                or candidate is None
                or candidate.get("event_name")
                != "FOREGROUND_REPLY_CANDIDATE_EMITTED"
                or selected_source_event_id
                not in {
                    str(candidate["event_id"]),
                    str(gate["event_id"]),
                    str(output["event_id"]),
                }
            ):
                continue
            retired = any(
                delivery.get("event_name")
                == "ASSISTANT_DELIVERY_DISPOSITIONED"
                and delivery.get("source_output_event_id")
                == output.get("event_id")
                and delivery.get("to_status")
                in {"FULL", "TRUNCATED", "NOT_STARTED"}
                and int(delivery["event_seq"]) < arbitration_seq
                for delivery in ordered_events
            )
            if retired:
                raise ReplayValidationError(
                    "user_fast authority retired by its assistant delivery "
                    "terminal cannot be selected again"
                )


def _is_adr018_arbitration_trigger(
    event: Mapping[str, Any],
    *,
    handoffs_by_event_id: Mapping[str, Mapping[str, Any]],
    arbitrations_by_event_id: Mapping[str, Mapping[str, Any]],
) -> bool:
    event_name = event.get("event_name")
    event_id = str(event.get("event_id", ""))
    if event_name in {
        "FOREGROUND_REPLY_CANDIDATE_EMITTED",
        "FOREGROUND_ACT_GATE_PASSED",
        "FOREGROUND_OUTPUT_COMMITTED",
        "INTERRUPT_CANDIDATE",
        "ASSISTANT_DELIVERY_DISPOSITIONED",
    }:
        return True
    if event_name == "SLOW_TO_FAST_HANDOFF_EMITTED":
        return event_id in handoffs_by_event_id
    if event_name == "RESPONSE_ARBITRATION_DECIDED":
        return event_id in arbitrations_by_event_id
    return (
        event_name == "SLOW_TO_FAST_HANDOFF_DISPOSITIONED"
        and event.get("disposition") in {"SELECTED", "CANCELLED"}
    )


def _is_adr018_supersedable_authority(
    event: Mapping[str, Any],
    *,
    handoffs_by_event_id: Mapping[str, Mapping[str, Any]],
    arbitrations_by_event_id: Mapping[str, Mapping[str, Any]],
) -> bool:
    event_name = event.get("event_name")
    event_id = str(event.get("event_id", ""))
    if event_name in {
        "FOREGROUND_REPLY_CANDIDATE_EMITTED",
        "FOREGROUND_ACT_GATE_PASSED",
        "FOREGROUND_OUTPUT_COMMITTED",
    }:
        return _is_adr018_parallel_event(event)
    if event_name == "SLOW_TO_FAST_HANDOFF_EMITTED":
        return event_id in handoffs_by_event_id
    if event_name == "RESPONSE_ARBITRATION_DECIDED":
        return event_id in arbitrations_by_event_id
    return (
        event_name == "SLOW_TO_FAST_HANDOFF_DISPOSITIONED"
        and event.get("disposition") == "SELECTED"
    )


def _validate_adr018_user_fast_arbitration_source(
    arbitration: Mapping[str, Any],
    *,
    selected_source: Mapping[str, Any],
    ordered_events: Sequence[Mapping[str, Any]],
    events_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    source_event_id = str(selected_source["event_id"])
    source_event_name = selected_source.get("event_name")
    if source_event_name == "FOREGROUND_REPLY_CANDIDATE_EMITTED":
        fast_event = events_by_id.get(
            str(
                selected_source.get(
                    "fast_interaction_output_event_id",
                    "",
                )
            )
        )

        def resolves_candidate(
            disposition: Mapping[str, Any],
        ) -> bool:
            if disposition.get("candidate_event_id") == source_event_id:
                return True
            gate_event = events_by_id.get(
                str(disposition.get("gate_event_id", ""))
            )
            return (
                gate_event is not None
                and gate_event.get("candidate_event_id") == source_event_id
            )

        terminal_dispositions = [
            event
            for event in ordered_events
            if int(event["event_seq"]) < int(arbitration["event_seq"])
            and (
                (
                    event.get("event_name")
                    in {
                        "FOREGROUND_ACT_GATE_FAILED",
                        "FOREGROUND_ACT_GATE_PASSED",
                    }
                    and event.get("candidate_event_id") == source_event_id
                    and event.get("event_name")
                    == "FOREGROUND_ACT_GATE_FAILED"
                )
                or (
                    event.get("event_name")
                    in {
                        "FOREGROUND_OUTPUT_COMMITTED",
                        "FOREGROUND_OUTPUT_DISCARDED",
                    }
                    and resolves_candidate(event)
                )
            )
        ]
        if (
            not _is_adr018_parallel_event(selected_source)
            or fast_event is None
            or fast_event.get("event_name")
            != "FAST_INTERACTION_OUTPUT_EMITTED"
            or not _is_adr018_parallel_event(fast_event)
            or terminal_dispositions
        ):
            raise ReplayValidationError(
                "user_fast arbitration candidate must be an active canonical "
                "parallel candidate authority"
            )
    elif source_event_name == "FOREGROUND_ACT_GATE_PASSED":
        candidate = events_by_id.get(
            str(selected_source.get("candidate_event_id", ""))
        )
        if (
            not _is_adr018_parallel_event(selected_source)
            or candidate is None
            or candidate.get("event_name")
            != "FOREGROUND_REPLY_CANDIDATE_EMITTED"
            or selected_source.get("release_token_ref") in (None, "")
        ):
            raise ReplayValidationError(
                "user_fast arbitration Gate source must be a canonical "
                "parallel Gate PASS authority"
            )
    elif source_event_name == "FOREGROUND_OUTPUT_COMMITTED":
        gate = events_by_id.get(
            str(selected_source.get("gate_event_id", ""))
        )
        if (
            not _is_adr018_parallel_event(selected_source)
            or gate is None
            or gate.get("event_name") != "FOREGROUND_ACT_GATE_PASSED"
            or selected_source.get("caused_by_event_id")
            != gate.get("event_id")
            or selected_source.get("output_basis") != "reply_candidate"
            or selected_source.get("user_visible_channel") != "audio_pending"
            or selected_source.get("release_token_ref")
            != gate.get("release_token_ref")
        ):
            raise ReplayValidationError(
                "user_fast arbitration output source must be the canonical "
                "active Gate-authorized audio-pending output"
            )
    else:
        raise ReplayValidationError(
            "user_fast arbitration may select only a canonical active "
            "candidate, Gate PASS, or committed output authority"
        )
    if any(
        event.get("event_name") == "RESPONSE_ARBITRATION_DECIDED"
        and int(event["event_seq"]) < int(arbitration["event_seq"])
        and source_event_id
        in set(event.get("superseded_source_event_ids", ()))
        for event in ordered_events
    ):
        raise ReplayValidationError(
            "user_fast arbitration cannot select superseded authority"
        )


def _adr018_has_later_arbitration_supersession(
    ordered_events: Sequence[Mapping[str, Any]],
    *,
    after_event: Mapping[str, Any],
    before_event: Mapping[str, Any],
    authority_event_ids: set[str],
) -> bool:
    return any(
        candidate.get("event_name") == "RESPONSE_ARBITRATION_DECIDED"
        and int(after_event["event_seq"])
        < int(candidate["event_seq"])
        < int(before_event["event_seq"])
        and authority_event_ids.intersection(
            set(candidate.get("superseded_source_event_ids", ()))
        )
        for candidate in ordered_events
    )


def _validate_adr018_composer_projections(
    ordered_events: Sequence[Mapping[str, Any]],
    *,
    events_by_id: Mapping[str, Mapping[str, Any]],
    handoffs_by_event_id: Mapping[str, Mapping[str, Any]],
    arbitrations_by_event_id: Mapping[str, Mapping[str, Any]],
    selected_dispositions_by_handoff_id: Mapping[
        str,
        Mapping[str, Any],
    ],
) -> None:
    for projection in ordered_events:
        if (
            projection.get("event_name")
            != "MODEL_CONTEXT_PROJECTION_EMITTED"
            or projection.get("target_role") != "composer"
        ):
            continue
        source_event_ids = set(
            _required_string_refs(
                projection,
                "source_event_ids",
                event_name="MODEL_CONTEXT_PROJECTION_EMITTED",
            )
        )
        source_handoffs = [
            handoff
            for event_id, handoff in handoffs_by_event_id.items()
            if event_id in source_event_ids
        ]
        if len(source_handoffs) != 1:
            raise ReplayValidationError(
                "composer projection requires exactly one selected "
                "slow-to-fast handoff source"
            )
        handoff = source_handoffs[0]
        handoff_id = str(handoff["handoff_id"])
        disposition = selected_dispositions_by_handoff_id.get(handoff_id)
        if disposition is None or handoff.get("expiry_status") != "CURRENT":
            raise ReplayValidationError(
                "composer projection requires a CURRENT SELECTED handoff"
            )
        arbitration_event_id = _required_text(
            disposition,
            "response_arbitration_event_id",
            event_name="SLOW_TO_FAST_HANDOFF_DISPOSITIONED",
        )
        arbitration = arbitrations_by_event_id.get(arbitration_event_id)
        required_sources = {
            str(handoff["event_id"]),
            arbitration_event_id,
            str(disposition["event_id"]),
        }
        if (
            arbitration is None
            or arbitration.get("selected_source_event_id")
            != handoff.get("event_id")
            or not required_sources.issubset(source_event_ids)
            or projection.get("caused_by_event_id")
            != disposition.get("event_id")
            or not _event_seq_strictly_increases(
                handoff,
                arbitration,
                disposition,
                projection,
            )
        ):
            raise ReplayValidationError(
                "composer projection must preserve exact selected handoff and "
                "response-arbitration causality"
            )
        if _adr018_has_later_arbitration_supersession(
            ordered_events,
            after_event=arbitration,
            before_event=projection,
            authority_event_ids={
                str(handoff["event_id"]),
                str(arbitration["event_id"]),
                str(disposition["event_id"]),
            },
        ):
            raise ReplayValidationError(
                "composer projection cannot consume superseded handoff "
                "authority"
            )
        actual_identity = _adr018_actual_slowtask_identity_before(
            projection,
            ordered_events=ordered_events,
        )
        if actual_identity != (
            handoff.get("task_id"),
            handoff.get("plan_version"),
            handoff.get("task_event_seq"),
        ):
            raise ReplayValidationError(
                "Composer projection selected handoff must remain the current "
                "SlowTask identity at the actual replay prefix"
            )
        for field in ("task_id", "plan_version", "task_event_seq"):
            if (
                projection.get(field) not in (None, "")
                and projection.get(field) != handoff.get(field)
            ):
                raise ReplayValidationError(
                    "composer projection current-plan identity must match its "
                    "selected handoff"
                )


def _validate_adr018_route_chain(
    route_event: Mapping[str, Any],
    *,
    ordered_events: Sequence[Mapping[str, Any]],
    events_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[
    Mapping[str, Any],
    Mapping[str, Any],
    Mapping[str, Any],
    Mapping[str, Any],
]:
    _validate_adr018_route_evidence_contract(route_event)
    key = _turn_key(route_event)
    final_asr = _required_referenced_event(
        route_event,
        "final_asr_event_id",
        expected_event_name="ASR_TRANSCRIPT_OUTPUT_EMITTED",
        events_by_id=events_by_id,
    )
    if _turn_key(final_asr) != key:
        raise ReplayValidationError(
            "Route Evidence final ASR must match turn_id and utterance_id"
        )
    committed_event = events_by_id.get(
        str(final_asr.get("caused_by_event_id", ""))
    )
    if (
        committed_event is None
        or committed_event.get("event_name") != "TURN_INGRESS_COMMITTED"
        or _turn_key(committed_event) != key
        or final_asr.get("transcript_finality") != "final"
    ):
        raise ReplayValidationError(
            "Route Evidence requires final Qwen ASR from the matching committed "
            "turn"
        )
    route_projection = _required_referenced_event(
        route_event,
        "context_projection_event_id",
        expected_event_name="MODEL_CONTEXT_PROJECTION_EMITTED",
        events_by_id=events_by_id,
    )
    if (
        route_projection.get("target_role") != "route_evidence"
        or route_projection.get("caused_by_event_id")
        != final_asr.get("event_id")
        or route_event.get("caused_by_event_id")
        != route_projection.get("event_id")
        or not _event_seq_strictly_increases(
            committed_event,
            final_asr,
            route_projection,
            route_event,
        )
    ):
        raise ReplayValidationError(
            "Route Evidence requires its final-ASR projection in exact causal "
            "order"
        )
    _require_source_refs_include(
        route_projection,
        {str(final_asr["event_id"])},
    )
    generation = route_projection.get("provider_session_generation")
    snapshot_id = route_projection.get("context_snapshot_id")
    if (
        final_asr.get("provider_session_generation") != generation
        or route_event.get("provider_session_generation") != generation
        or route_event.get("context_snapshot_id") != snapshot_id
    ):
        raise ReplayValidationError(
            "Route Evidence must preserve provider generation and context "
            "snapshot bindings"
        )

    routers = [
        event
        for event in ordered_events
        if event.get("event_name") == "ROUTER_DECISION_EMITTED"
        and event.get("route_evidence_event_id") == route_event.get("event_id")
    ]
    if len(routers) != 1:
        raise ReplayValidationError(
            "Route Evidence must feed exactly one local Router authority"
        )
    router_event = routers[0]
    if (
        _turn_key(router_event) != key
        or router_event.get("caused_by_event_id")
        != route_event.get("event_id")
        or router_event.get("turn_committed_event_id")
        != committed_event.get("event_id")
        or router_event.get("asr_frame_event_id") != final_asr.get("event_id")
        or router_event.get("router_decision") != route_event.get("route_hint")
        or router_event.get("task_focus") != route_event.get("task_focus_hint")
        or not _event_seq_before(route_event, router_event)
    ):
        raise ReplayValidationError(
            "Router authority must consume the exact matching Route Evidence "
            "chain"
        )
    return committed_event, final_asr, route_projection, router_event


def _validate_adr018_candidate_safety_chain(
    safety_event: Mapping[str, Any],
    *,
    events_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[Mapping[str, Any] | None, Mapping[str, Any]]:
    _validate_adr018_candidate_safety_contract(safety_event)
    safety_projection = _required_referenced_event(
        safety_event,
        "context_projection_event_id",
        expected_event_name="MODEL_CONTEXT_PROJECTION_EMITTED",
        events_by_id=events_by_id,
    )
    if (
        safety_projection.get("target_role") != "candidate_safety"
        or safety_event.get("caused_by_event_id")
        != safety_projection.get("event_id")
        or not _event_seq_before(safety_projection, safety_event)
    ):
        raise ReplayValidationError(
            "candidate-safety evidence requires its matching projection in "
            "exact causal order"
        )
    projection_source_ids = _required_string_refs(
        safety_projection,
        "source_event_ids",
        event_name="MODEL_CONTEXT_PROJECTION_EMITTED",
    )
    if not any(
        source_event is not None
        and source_event.get("event_name")
        in {
            "ASR_TRANSCRIPT_OUTPUT_EMITTED",
            "ROUTE_EVIDENCE_OUTPUT_EMITTED",
        }
        and _turn_key(source_event) == _turn_key(safety_event)
        for source_event in (
            events_by_id.get(source_event_id)
            for source_event_id in projection_source_ids
        )
    ):
        raise ReplayValidationError(
            "candidate-safety projection requires a matching turn-scoped "
            "understanding source"
        )
    route_event: Mapping[str, Any] | None = None
    route_event_id = safety_event.get("route_evidence_event_id")
    if route_event_id not in (None, ""):
        if not isinstance(route_event_id, str):
            raise ReplayValidationError(
                "candidate-safety route_evidence_event_id must be an opaque "
                "event id when present"
            )
        route_event = events_by_id.get(route_event_id)
        if (
            route_event is None
            or route_event.get("event_name") != "ROUTE_EVIDENCE_OUTPUT_EMITTED"
            or _turn_key(safety_event) != _turn_key(route_event)
            or not _event_seq_before(route_event, safety_projection)
        ):
            raise ReplayValidationError(
                "candidate-safety optional Route Evidence binding must "
                "reference the matching prior turn"
            )
        _require_source_refs_include(
            safety_projection,
            {str(route_event["event_id"])},
        )

    generation = safety_projection.get("provider_session_generation")
    snapshot_id = safety_projection.get("context_snapshot_id")
    if (
        safety_event.get("provider_session_generation") != generation
        or safety_event.get("context_snapshot_id") != snapshot_id
    ):
        raise ReplayValidationError(
            "candidate-safety evidence must preserve provider generation and "
            "context snapshot"
        )
    _required_text(
        safety_event,
        "qwen_response_id",
        event_name="CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED",
    )
    digest = _required_text(
        safety_event,
        "candidate_transcript_digest",
        event_name="CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED",
    )
    if (
        not digest.startswith("sha256:")
        or len(digest) != 71
        or any(
            character not in "0123456789abcdef"
            for character in digest.removeprefix("sha256:")
        )
    ):
        raise ReplayValidationError(
            "candidate-safety transcript digest must be a safe sha256 digest"
        )
    return route_event, safety_projection


def _validate_adr018_route_evidence_contract(
    route_event: Mapping[str, Any],
) -> None:
    try:
        RouteEvidenceOutputV1(
            route_hint=route_event.get("route_hint"),  # type: ignore[arg-type]
            task_focus_hint=route_event.get("task_focus_hint"),  # type: ignore[arg-type]
            foreground_act_hint=route_event.get("foreground_act_hint"),  # type: ignore[arg-type]
            ack_kind=route_event.get("ack_kind"),  # type: ignore[arg-type]
            risk_class=route_event.get("risk_class"),  # type: ignore[arg-type]
            risk_tags=route_event.get("risk_tags"),  # type: ignore[arg-type]
            evidence_uncertainty=route_event.get("evidence_uncertainty"),  # type: ignore[arg-type]
            confidence=route_event.get("confidence"),  # type: ignore[arg-type]
            schema_name=route_event.get("schema_name"),  # type: ignore[arg-type]
            normalization_status=route_event.get("normalization_status"),  # type: ignore[arg-type]
            output_mode=route_event.get("output_mode"),  # type: ignore[arg-type]
        )
    except (RouteEvidenceContractError, TypeError, ValueError) as exc:
        raise ReplayValidationError(
            "ROUTE_EVIDENCE_OUTPUT_EMITTED violates the canonical output "
            "contract"
        ) from exc


def _validate_adr018_candidate_safety_contract(
    safety_event: Mapping[str, Any],
) -> None:
    try:
        CandidateSafetyEvidenceV1(
            decision=safety_event.get("decision"),  # type: ignore[arg-type]
            semantic_categories=safety_event.get("semantic_categories"),  # type: ignore[arg-type]
            prohibited_flags=safety_event.get("prohibited_flags"),  # type: ignore[arg-type]
            confidence=safety_event.get("confidence"),  # type: ignore[arg-type]
            candidate_transcript_digest=safety_event.get(  # type: ignore[arg-type]
                "candidate_transcript_digest"
            ),
            schema_name=safety_event.get("schema_name"),  # type: ignore[arg-type]
            normalization_status=safety_event.get("normalization_status"),  # type: ignore[arg-type]
            output_mode=safety_event.get("output_mode"),  # type: ignore[arg-type]
        )
    except (RouteEvidenceContractError, TypeError, ValueError) as exc:
        raise ReplayValidationError(
            "CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED violates the canonical "
            "output contract"
        ) from exc


def _validate_one_adr018_parallel_turn(
    fast_event: Mapping[str, Any],
    *,
    ordered_events: Sequence[Mapping[str, Any]],
    events_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    key = _turn_key(fast_event)
    route_event = _required_referenced_event(
        fast_event,
        "route_evidence_event_id",
        expected_event_name="ROUTE_EVIDENCE_OUTPUT_EMITTED",
        events_by_id=events_by_id,
    )
    (
        committed_event,
        final_asr,
        route_projection,
        router_event,
    ) = _validate_adr018_route_chain(
        route_event,
        ordered_events=ordered_events,
        events_by_id=events_by_id,
    )
    if _turn_key(route_event) != key or not _event_seq_before(
        committed_event,
        fast_event,
    ):
        raise ReplayValidationError(
            "ADR-018 composite Fast output must match a prior Route Evidence "
            "committed-turn chain"
        )

    safety_event = _required_referenced_event(
        fast_event,
        "candidate_safety_evidence_event_id",
        expected_event_name="CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED",
        events_by_id=events_by_id,
    )
    safety_bound_route_event, safety_projection = (
        _validate_adr018_candidate_safety_chain(
            safety_event,
            events_by_id=events_by_id,
        )
    )
    if _turn_key(safety_event) != key:
        raise ReplayValidationError(
            "candidate-safety evidence must match composite Fast output turn"
        )
    if (
        safety_bound_route_event is not None
        and safety_bound_route_event.get("event_id")
        != route_event.get("event_id")
    ):
        raise ReplayValidationError(
            "ADR-018 composite Fast output cannot join candidate-safety "
            "evidence bound to another Route Evidence event"
        )

    if (
        fast_event.get("caused_by_event_id") != safety_event.get("event_id")
        or fast_event.get("route_evidence_adapter_request_id")
        != route_event.get("adapter_request_id")
        or fast_event.get("candidate_safety_adapter_request_id")
        != safety_event.get("adapter_request_id")
        or not _event_seq_before(safety_event, fast_event)
        or not _event_seq_before(router_event, fast_event)
    ):
        raise ReplayValidationError(
            "ADR-018 composite Fast output must join exact Route Evidence and "
            "candidate-safety adapter requests"
        )
    route_confidence = _required_confidence(
        route_event,
        event_name="ROUTE_EVIDENCE_OUTPUT_EMITTED",
    )
    safety_confidence = _required_confidence(
        safety_event,
        event_name="CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED",
    )
    fast_confidence = _required_confidence(
        fast_event,
        event_name="FAST_INTERACTION_OUTPUT_EMITTED",
    )
    route_risk_tags = _required_bounded_string_tuple(
        route_event,
        "risk_tags",
        event_name="ROUTE_EVIDENCE_OUTPUT_EMITTED",
    )
    fast_risk_tags = _required_bounded_string_tuple(
        fast_event,
        "risk_tags",
        event_name="FAST_INTERACTION_OUTPUT_EMITTED",
    )
    if (
        fast_event.get("foreground_act")
        != route_event.get("foreground_act_hint")
        or fast_event.get("risk_class") != route_event.get("risk_class")
        or fast_risk_tags != route_risk_tags
        or fast_confidence != min(route_confidence, safety_confidence)
        or router_event.get("confidence") != route_confidence
        or router_event.get("evidence_uncertainty")
        != route_event.get("evidence_uncertainty")
    ):
        raise ReplayValidationError(
            "ADR-018 composite Fast output and Router must preserve recorded "
            "Route Evidence risk, act, uncertainty, and confidence facts"
        )
    _require_source_refs_include(
        fast_event,
        {
            str(final_asr["event_id"]),
            str(route_event["event_id"]),
            str(safety_event["event_id"]),
        },
    )

    candidates = [
        event
        for event in ordered_events
        if event.get("event_name") == "FOREGROUND_REPLY_CANDIDATE_EMITTED"
        and _is_adr018_parallel_event(event)
        and _turn_key(event) == key
    ]
    if len(candidates) != 1:
        raise ReplayValidationError(
            "ADR-018 parallel turn requires exactly one foreground candidate"
        )
    candidate_event = candidates[0]
    candidate_confidence = _required_confidence(
        candidate_event,
        event_name="FOREGROUND_REPLY_CANDIDATE_EMITTED",
    )
    candidate_risk_tags = _required_bounded_string_tuple(
        candidate_event,
        "risk_tags",
        event_name="FOREGROUND_REPLY_CANDIDATE_EMITTED",
    )
    candidate_audio_duration_ms = _required_nonnegative_int(
        candidate_event,
        "candidate_audio_duration_ms",
        event_name="FOREGROUND_REPLY_CANDIDATE_EMITTED",
    )
    if not 1 <= candidate_audio_duration_ms <= 2_000:
        raise ReplayValidationError(
            "ADR-018 candidate_audio_duration_ms must be from 1 to 2000"
        )
    if "candidate_unicode_scalar_count" in candidate_event:
        scalar_count = _required_nonnegative_int(
            candidate_event,
            "candidate_unicode_scalar_count",
            event_name="FOREGROUND_REPLY_CANDIDATE_EMITTED",
        )
        if scalar_count > MAX_CANDIDATE_UNICODE_SCALARS:
            raise ReplayValidationError(
                "ADR-018 candidate_unicode_scalar_count exceeds the "
                "candidate policy limit"
            )
    if (
        candidate_event.get("fast_interaction_output_event_id")
        != fast_event.get("event_id")
        or candidate_event.get("caused_by_event_id")
        != fast_event.get("event_id")
        or candidate_event.get("qwen_response_id")
        != safety_event.get("qwen_response_id")
        or candidate_event.get("candidate_transcript_digest")
        != safety_event.get("candidate_transcript_digest")
        or candidate_event.get("route_evidence_event_id")
        != route_event.get("event_id")
        or candidate_event.get("candidate_safety_evidence_event_id")
        != safety_event.get("event_id")
        or _fast_interaction_input_mode(candidate_event)
        != _fast_interaction_input_mode(fast_event)
        or candidate_risk_tags != fast_risk_tags
        or candidate_confidence != fast_confidence
        or not _event_seq_before(fast_event, candidate_event)
    ):
        raise ReplayValidationError(
            "ADR-018 candidate must preserve composite, safety digest, and "
            "provider-response bindings"
        )
    _require_source_refs_include(
        candidate_event,
        {
            str(fast_event["event_id"]),
            str(route_event["event_id"]),
            str(safety_event["event_id"]),
        },
    )

    generation = _required_nonnegative_int(
        fast_event,
        "provider_session_generation",
        event_name="FAST_INTERACTION_OUTPUT_EMITTED",
    )
    snapshot_id = _required_text(
        fast_event,
        "context_snapshot_id",
        event_name="FAST_INTERACTION_OUTPUT_EMITTED",
    )
    for bound_event in (
        final_asr,
        route_projection,
        route_event,
        safety_projection,
        safety_event,
        candidate_event,
    ):
        if bound_event.get("provider_session_generation") != generation:
            raise ReplayValidationError(
                "ADR-018 parallel chain provider generation must match"
            )
    for bound_event in (
        route_projection,
        route_event,
        safety_projection,
        safety_event,
        candidate_event,
    ):
        if bound_event.get("context_snapshot_id") != snapshot_id:
            raise ReplayValidationError(
                "ADR-018 parallel chain context snapshot must match"
            )

    gate_events = [
        event
        for event in ordered_events
        if event.get("event_name")
        in {"FOREGROUND_ACT_GATE_PASSED", "FOREGROUND_ACT_GATE_FAILED"}
        and _is_adr018_parallel_event(event)
        and event.get("candidate_event_id") == candidate_event.get("event_id")
    ]
    if len(gate_events) != 1:
        raise ReplayValidationError(
            "ADR-018 parallel turn requires exactly one terminal Gate"
        )
    gate_event = gate_events[0]
    if (
        gate_event.get("caused_by_event_id") != router_event.get("event_id")
        or gate_event.get("router_decision_event_id")
        != router_event.get("event_id")
        or gate_event.get("route_evidence_event_id")
        != route_event.get("event_id")
        or gate_event.get("candidate_safety_evidence_event_id")
        != safety_event.get("event_id")
        or gate_event.get("provider_session_generation") != generation
        or gate_event.get("context_snapshot_id") != snapshot_id
        or gate_event.get("foreground_act")
        != fast_event.get("foreground_act")
        or gate_event.get("risk_class") != route_event.get("risk_class")
        or gate_event.get("confidence") != route_confidence
        or not _event_seq_before(candidate_event, gate_event)
    ):
        raise ReplayValidationError(
            "ADR-018 Gate must preserve Router, evidence, generation, and "
            "snapshot bindings"
        )
    if (
        gate_event.get("event_name") == "FOREGROUND_ACT_GATE_PASSED"
        and router_event.get("router_decision") != "FAST_ONLY"
    ):
        raise ReplayValidationError(
            "passed ADR-018 Gate requires FAST_ONLY Router authority"
        )
    if gate_event.get("event_name") == "FOREGROUND_ACT_GATE_PASSED":
        gate_check_fields = (
            "candidate_length_check",
            "candidate_duration_check",
            "candidate_terminal_check",
            "native_pcm_capability_check",
            "generation_check",
            "context_snapshot_check",
            "route_evidence_check",
            "candidate_safety_check",
            "transcript_digest_check",
            "pcm_manifest_check",
            "correlation_check",
        )
        if (
            any(gate_event.get(field) != "PASS" for field in gate_check_fields)
            or router_event.get("task_focus") != "FOREGROUND_CHAT"
            or candidate_event.get("candidate_status") != "complete"
            or safety_event.get("decision") != "SAFE"
            or tuple(safety_event.get("prohibited_flags", ()))
            or route_event.get("evidence_uncertainty") != "LOW"
            or router_event.get("evidence_uncertainty") != "LOW"
            or route_confidence < ROUTE_CONFIDENCE_THRESHOLD
            or safety_confidence < CANDIDATE_SAFETY_CONFIDENCE_THRESHOLD
            or fast_event.get("foreground_act") != "ANSWER"
            or fast_event.get("risk_class") != "LOW"
        ):
            raise ReplayValidationError(
                "passed ADR-018 Gate requires every deterministic candidate "
                "check and low-risk FAST_ONLY eligibility fact to pass"
            )
        _validate_adr018_native_capability_readiness(
            gate_event,
            final_asr=final_asr,
            route_projection=route_projection,
            route_event=route_event,
            safety_projection=safety_projection,
            safety_event=safety_event,
            fast_event=fast_event,
            candidate_event=candidate_event,
            ordered_events=ordered_events,
        )

    discarded_events = [
        event
        for event in ordered_events
        if event.get("event_name") == "FOREGROUND_OUTPUT_DISCARDED"
        and _is_adr018_parallel_event(event)
        and event.get("candidate_event_id") == candidate_event.get("event_id")
    ]
    committed_outputs = [
        event
        for event in ordered_events
        if event.get("event_name") == "FOREGROUND_OUTPUT_COMMITTED"
        and _is_adr018_parallel_event(event)
        and event.get("gate_event_id") == gate_event.get("event_id")
    ]
    if gate_event.get("event_name") == "FOREGROUND_ACT_GATE_FAILED":
        if len(discarded_events) != 1 or committed_outputs:
            raise ReplayValidationError(
                "failed ADR-018 Gate requires exactly one terminal discard"
            )
        _validate_adr018_discard(
            discarded_events[0],
            candidate_event=candidate_event,
            fast_event=fast_event,
            router_event=router_event,
            gate_event=gate_event,
        )
        return

    if discarded_events or len(committed_outputs) != 1:
        raise ReplayValidationError(
            "passed ADR-018 Gate requires exactly one terminal committed output"
        )
    _validate_adr018_native_commit_and_delivery(
        committed_outputs[0],
        candidate_event=candidate_event,
        fast_event=fast_event,
        router_event=router_event,
        gate_event=gate_event,
        ordered_events=ordered_events,
    )


def _validate_adr018_discard(
    event: Mapping[str, Any],
    *,
    candidate_event: Mapping[str, Any],
    fast_event: Mapping[str, Any],
    router_event: Mapping[str, Any],
    gate_event: Mapping[str, Any],
) -> None:
    if (
        event.get("caused_by_event_id") != gate_event.get("event_id")
        or event.get("candidate_event_id") != candidate_event.get("event_id")
        or event.get("fast_interaction_output_event_id")
        != fast_event.get("event_id")
        or event.get("router_decision_event_id") != router_event.get("event_id")
        or not _event_seq_before(gate_event, event)
        or int(event["event_seq"]) != int(gate_event["event_seq"]) + 1
    ):
        raise ReplayValidationError(
            "ADR-018 discard must preserve candidate, composite, Router, and "
            "failed-Gate bindings"
        )


def _validate_adr018_native_commit_and_delivery(
    output_event: Mapping[str, Any],
    *,
    candidate_event: Mapping[str, Any],
    fast_event: Mapping[str, Any],
    router_event: Mapping[str, Any],
    gate_event: Mapping[str, Any],
    ordered_events: Sequence[Mapping[str, Any]],
) -> None:
    candidate_audio_duration_ms = _required_nonnegative_int(
        candidate_event,
        "candidate_audio_duration_ms",
        event_name="FOREGROUND_REPLY_CANDIDATE_EMITTED",
    )
    release_token_ref = _required_text(
        gate_event,
        "release_token_ref",
        event_name="FOREGROUND_ACT_GATE_PASSED",
    )
    if (
        output_event.get("caused_by_event_id") != gate_event.get("event_id")
        or output_event.get("router_decision_event_id")
        != router_event.get("event_id")
        or output_event.get("release_token_ref") != release_token_ref
        or output_event.get("output_ref") != candidate_event.get("candidate_ref")
        or output_event.get("output_basis") != "reply_candidate"
        or not _event_seq_before(gate_event, output_event)
        or int(output_event["event_seq"]) != int(gate_event["event_seq"]) + 1
    ):
        raise ReplayValidationError(
            "ADR-018 committed output must preserve Gate, Router, candidate, "
            "and release-token authority"
        )
    if output_event.get("user_visible_channel") != "audio_pending":
        raise ReplayValidationError(
            "passed ADR-018 provider-native output must remain audio_pending "
            "until delivery reconciliation"
        )
    if output_event.get("output_mode") == "degraded":
        raise ReplayValidationError(
            "degraded foreground output cannot consume native PCM Gate "
            "authority"
        )

    playback_starts = [
        event
        for event in ordered_events
        if event.get("event_name") == "PLAYBACK_SPAN_STARTED"
        and event.get("caused_by_event_id") == output_event.get("event_id")
    ]
    deliveries = [
        event
        for event in ordered_events
        if event.get("event_name") == "ASSISTANT_DELIVERY_DISPOSITIONED"
        and event.get("source_output_event_id") == output_event.get("event_id")
    ]
    if len(deliveries) != 1:
        raise ReplayValidationError(
            "audio-pending ADR-018 output requires exactly one terminal "
            "assistant delivery disposition"
        )
    delivery = deliveries[0]
    related_playback_starts = [
        event
        for event in ordered_events
        if event.get("event_name") == "PLAYBACK_SPAN_STARTED"
        and (
            event.get("caused_by_event_id") == output_event.get("event_id")
            or event.get("release_token_ref") == release_token_ref
            or (
                event.get("assistant_item_ref") not in (None, "")
                and event.get("assistant_item_ref")
                == delivery.get("assistant_item_ref")
            )
        )
    ]
    if delivery.get("release_token_ref") != release_token_ref:
        raise ReplayValidationError(
            "assistant delivery release_token_ref must match Gate authority"
        )
    _validate_adr018_native_shadow_terminal(
        output_event=output_event,
        candidate_event=candidate_event,
        ordered_events=ordered_events,
    )
    delivery_status = delivery.get("to_status")
    if delivery_status == "NOT_STARTED":
        if related_playback_starts:
            raise ReplayValidationError(
                "NOT_STARTED assistant delivery cannot have begun playback"
            )
        if (
            delivery.get("delivery_offset_status") != "NOT_APPLICABLE"
            or delivery.get("actual_stop_offset_ms") not in (None, "")
        ):
            raise ReplayValidationError(
                "NOT_STARTED assistant delivery cannot claim playback coverage"
            )
        _validate_adr018_delivery_cleanup(
            delivery,
            ordered_events=ordered_events,
            require_cleanup=True,
            unknown_offset_requires_rebuild=False,
        )
        return
    if len(playback_starts) != 1:
        raise ReplayValidationError(
            "FULL or TRUNCATED assistant delivery requires exactly one "
            "provider-native playback start"
        )

    playback_start = playback_starts[0]
    playback_start_delta_ms = (
        int(playback_start["created_monotonic_ms"])
        - int(output_event["created_monotonic_ms"])
    )
    if not 0 <= playback_start_delta_ms <= 1_000:
        raise ReplayValidationError(
            "FULL or TRUNCATED native playback must start within the 1,000 ms "
            "audio-pending deadline"
        )
    release_authority_event_ids = {
        str(output_event["event_id"]),
        str(gate_event["event_id"]),
        str(candidate_event["event_id"]),
        str(fast_event["event_id"]),
        str(router_event["event_id"]),
        str(fast_event["route_evidence_event_id"]),
        str(fast_event["candidate_safety_evidence_event_id"]),
    }
    superseding_arbitrations = [
        event
        for event in ordered_events
        if event.get("event_name") == "RESPONSE_ARBITRATION_DECIDED"
        and int(output_event["event_seq"])
        < int(event["event_seq"])
        < int(playback_start["event_seq"])
        and release_authority_event_ids.intersection(
            set(event.get("superseded_source_event_ids", ()))
        )
    ]
    if superseding_arbitrations:
        raise ReplayValidationError(
            "superseded ADR-018 release authority cannot start provider-native "
            "playback"
        )
    expected_bindings = {
        "release_token_ref": release_token_ref,
        "provider_session_generation": candidate_event.get(
            "provider_session_generation"
        ),
        "context_snapshot_id": candidate_event.get("context_snapshot_id"),
        "turn_id": candidate_event.get("turn_id"),
        "utterance_id": candidate_event.get("utterance_id"),
        "candidate_id": candidate_event.get("candidate_id"),
        "qwen_response_id": candidate_event.get("qwen_response_id"),
        "qwen_output_item_id": candidate_event.get("qwen_output_item_id"),
        "qwen_output_index": candidate_event.get("qwen_output_index"),
        "qwen_content_index": candidate_event.get("qwen_content_index"),
        "candidate_transcript_digest": candidate_event.get(
            "candidate_transcript_digest"
        ),
        "candidate_pcm_manifest_digest": candidate_event.get(
            "candidate_pcm_manifest_digest"
        ),
    }
    if any(
        playback_start.get(field) != expected
        for field, expected in expected_bindings.items()
    ):
        raise ReplayValidationError(
            "native playback must preserve exact release-token provider "
            "correlation and digests"
        )
    gate_authorized_epoch, _ = _adr018_fence_before(
        ordered_events,
        event_seq=int(gate_event["event_seq"]),
    )
    expected_epoch, _ = _adr018_fence_before(
        ordered_events,
        event_seq=int(playback_start["event_seq"]),
    )
    if (
        playback_start.get("playback_epoch") != gate_authorized_epoch
        or expected_epoch != gate_authorized_epoch
    ):
        raise ReplayValidationError(
            "native playback epoch must match both immutable Gate authorization "
            "and current ADR-018 control authority"
        )
    playback_span_id = _required_text(
        playback_start,
        "playback_span_id",
        event_name="PLAYBACK_SPAN_STARTED",
    )
    if delivery.get("playback_span_id") != playback_span_id:
        raise ReplayValidationError(
            "assistant delivery playback_span_id must match authorized playback"
        )

    committed = [
        event
        for event in ordered_events
        if event.get("event_name") == "PLAYBACK_COMMITTED"
        and event.get("playback_span_id") == playback_span_id
    ]
    finished = [
        event
        for event in ordered_events
        if event.get("event_name") == "PLAYBACK_FINISHED"
        and event.get("playback_span_id") == playback_span_id
    ]
    truncate_requests = [
        event
        for event in ordered_events
        if event.get("event_name") == "TTS_TRUNCATE_REQUESTED"
        and event.get("playback_span_id") == playback_span_id
    ]
    truncations = [
        event
        for event in ordered_events
        if event.get("event_name") == "TTS_TRUNCATED"
        and event.get("playback_span_id") == playback_span_id
    ]
    if delivery_status == "FULL":
        superseding_after_start = [
            event
            for event in ordered_events
            if event.get("event_name") == "RESPONSE_ARBITRATION_DECIDED"
            and int(playback_start["event_seq"])
            < int(event["event_seq"])
            < int(delivery["event_seq"])
            and release_authority_event_ids.intersection(
                set(event.get("superseded_source_event_ids", ()))
            )
        ]
        if superseding_after_start:
            raise ReplayValidationError(
                "superseded in-flight ADR-018 release cannot finish as FULL"
            )
        if (
            not committed
            or len(finished) != 1
            or truncate_requests
            or truncations
        ):
            raise ReplayValidationError(
                "FULL assistant delivery requires playback commit coverage and "
                "finish and excludes truncate terminals"
            )
        finish = finished[0]
        ordered_commits = _validate_adr018_playback_commit_series(
            committed,
            playback_start=playback_start,
            terminal_event=delivery,
            release_token_ref=release_token_ref,
            ordered_events=ordered_events,
            maximum_offset_ms=candidate_audio_duration_ms,
            optional_finish=finish,
        )
        final_commit = ordered_commits[-1]
        terminal_predecessor = max(
            (finish, final_commit),
            key=lambda event: int(event["event_seq"]),
        )
        if (
            finish.get("release_token_ref") != release_token_ref
            or not _event_seq_before(playback_start, finish)
            or not _event_seq_before(finish, delivery)
            or (
                int(finish["event_seq"]) > int(final_commit["event_seq"])
                and finish.get("caused_by_event_id")
                != final_commit.get("event_id")
            )
            or (
                int(final_commit["event_seq"]) > int(finish["event_seq"])
                and final_commit.get("caused_by_event_id")
                != finish.get("event_id")
            )
            or delivery.get("caused_by_event_id")
            != terminal_predecessor.get("event_id")
        ):
            raise ReplayValidationError(
                "FULL native delivery must preserve release token and playback "
                "causal order"
            )
        final_offset = _required_nonnegative_int(
            finish,
            "final_playback_offset_ms",
            event_name="PLAYBACK_FINISHED",
        )
        if (
            final_commit.get("playback_offset_ms") != final_offset
            or delivery.get("delivery_offset_status") != "KNOWN"
            or delivery.get("actual_stop_offset_ms") != final_offset
            or final_offset != candidate_audio_duration_ms
        ):
            raise ReplayValidationError(
                "FULL assistant delivery requires exact complete candidate "
                "duration coverage across final commit, finish, and delivery"
            )
        if delivery.get("provider_item_cleanup_status") != "NOT_REQUIRED":
            raise ReplayValidationError(
                "FULL assistant delivery requires exact "
                "provider_item_cleanup_status=NOT_REQUIRED"
            )
        delivery_sources = set(
            _required_string_refs(
                delivery,
                "source_event_ids",
                event_name="ASSISTANT_DELIVERY_DISPOSITIONED",
            )
        )
        if not {
            str(final_commit["event_id"]),
            str(finish["event_id"]),
        }.issubset(delivery_sources):
            raise ReplayValidationError(
                "FULL assistant delivery must cite playback commit and finish"
            )
        return

    if delivery_status == "TRUNCATED":
        if finished:
            raise ReplayValidationError(
                "TRUNCATED assistant delivery excludes PLAYBACK_FINISHED/FULL "
                "terminal"
            )
        if len(truncations) != 1 or len(truncate_requests) != 1:
            raise ReplayValidationError(
                "TRUNCATED native delivery requires exactly one interrupt "
                "truncate request and terminal"
            )
        truncation = truncations[0]
        truncate_request = truncate_requests[0]
        interrupt_event_id = _required_text(
            truncate_request,
            "interrupt_candidate_event_id",
            event_name="TTS_TRUNCATE_REQUESTED",
        )
        interrupt_matches = [
            event
            for event in ordered_events
            if event.get("event_name") == "INTERRUPT_CANDIDATE"
            and event.get("event_id") == interrupt_event_id
        ]
        if len(interrupt_matches) != 1:
            raise ReplayValidationError(
                "TRUNCATED native delivery requires its exact interrupt "
                "candidate"
            )
        interrupt = interrupt_matches[0]
        truncate_fence = (
            _required_nonnegative_int(
                truncate_request,
                "playback_epoch",
                event_name="TTS_TRUNCATE_REQUESTED",
            ),
            _required_nonnegative_int(
                truncate_request,
                "interaction_state_version",
                event_name="TTS_TRUNCATE_REQUESTED",
            ),
        )
        interrupt_fence = (
            _required_nonnegative_int(
                interrupt,
                "playback_epoch",
                event_name="INTERRUPT_CANDIDATE",
            ),
            _required_nonnegative_int(
                interrupt,
                "interaction_state_version",
                event_name="INTERRUPT_CANDIDATE",
            ),
        )
        truncated_fence = (
            _required_nonnegative_int(
                truncation,
                "playback_epoch",
                event_name="TTS_TRUNCATED",
            ),
            _required_nonnegative_int(
                truncation,
                "interaction_state_version",
                event_name="TTS_TRUNCATED",
            ),
        )
        actual_stop_offset_ms = _required_nonnegative_int(
            truncation,
            "actual_stop_offset_ms",
            event_name="TTS_TRUNCATED",
        )
        interrupt_offset_ms = _required_nonnegative_int(
            interrupt,
            "playback_offset_ms",
            event_name="INTERRUPT_CANDIDATE",
        )
        requested_offset_ms = _required_nonnegative_int(
            truncate_request,
            "cutoff_playback_offset_ms",
            event_name="TTS_TRUNCATE_REQUESTED",
        )
        if (
            truncation.get("release_token_ref") != release_token_ref
            or truncate_request.get("release_token_ref") != release_token_ref
            or interrupt.get("playback_span_id") != playback_span_id
            or truncate_request.get("playback_span_id") != playback_span_id
            or truncation.get("playback_span_id") != playback_span_id
            or truncate_request.get("caused_by_event_id")
            != interrupt.get("event_id")
            or truncation.get("caused_by_event_id")
            != truncate_request.get("event_id")
            or truncation.get("truncate_request_event_id")
            != truncate_request.get("event_id")
            or interrupt_fence != truncate_fence
            or truncate_fence != truncated_fence
            or interrupt_offset_ms != requested_offset_ms
            or requested_offset_ms != actual_stop_offset_ms
            or actual_stop_offset_ms > candidate_audio_duration_ms
            or delivery.get("caused_by_event_id")
            != truncation.get("event_id")
            or not _event_seq_strictly_increases(
                playback_start,
                interrupt,
                truncate_request,
                truncation,
                delivery,
            )
        ):
            raise ReplayValidationError(
                "TRUNCATED native delivery requires exact release-token "
                "truncate chain"
            )
        delivery_sources = set(
            _required_string_refs(
                delivery,
                "source_event_ids",
                event_name="ASSISTANT_DELIVERY_DISPOSITIONED",
            )
        )
        if not {
            str(truncate_request["event_id"]),
            str(truncation["event_id"]),
        }.issubset(delivery_sources):
            raise ReplayValidationError(
                "TRUNCATED assistant delivery must cite truncate request and "
                "terminal"
            )
        if committed:
            ordered_commits = _validate_adr018_playback_commit_series(
                committed,
                playback_start=playback_start,
                terminal_event=truncation,
                release_token_ref=release_token_ref,
                ordered_events=ordered_events,
                maximum_offset_ms=candidate_audio_duration_ms,
            )
            last_commit = ordered_commits[-1]
            if (
                last_commit.get("playback_offset_ms")
                > actual_stop_offset_ms
                or str(last_commit["event_id"]) not in delivery_sources
            ):
                raise ReplayValidationError(
                    "TRUNCATED playback commit coverage must not exceed the "
                    "actual stop and must be cited by delivery"
                )
        if delivery.get("delivery_offset_status") == "KNOWN" and (
            delivery.get("actual_stop_offset_ms")
            != truncation.get("actual_stop_offset_ms")
        ):
            raise ReplayValidationError(
                "TRUNCATED assistant delivery known offset must match the "
                "actual truncate stop"
            )
        _validate_adr018_delivery_cleanup(
            delivery,
            ordered_events=ordered_events,
            require_cleanup=True,
            unknown_offset_requires_rebuild=(
                delivery.get("delivery_offset_status") == "UNKNOWN"
            ),
        )
        return
    raise ReplayValidationError(
        "assistant delivery disposition has unsupported terminal status"
    )


def _validate_adr018_native_capability_readiness(
    gate_event: Mapping[str, Any],
    *,
    final_asr: Mapping[str, Any],
    route_projection: Mapping[str, Any],
    route_event: Mapping[str, Any],
    safety_projection: Mapping[str, Any],
    safety_event: Mapping[str, Any],
    fast_event: Mapping[str, Any],
    candidate_event: Mapping[str, Any],
    ordered_events: Sequence[Mapping[str, Any]],
) -> None:
    bound_events = (
        final_asr,
        route_projection,
        route_event,
        safety_projection,
        safety_event,
        fast_event,
        candidate_event,
        gate_event,
    )
    if any(event.get("output_mode") == "degraded" for event in bound_events):
        raise ReplayValidationError(
            "native PCM Gate PASS cannot consume degraded bound output_mode"
        )

    request_success_seq: dict[tuple[str, str], int] = {}
    adapter_success_seq: dict[str, int] = {}

    def record_success(
        adapter_id: object,
        adapter_request_id: object,
        success_event: Mapping[str, Any],
    ) -> None:
        if adapter_id in (None, "") or adapter_request_id in (None, ""):
            return
        adapter_key = str(adapter_id)
        request_key = (adapter_key, str(adapter_request_id))
        success_seq = int(success_event["event_seq"])
        request_success_seq[request_key] = max(
            success_seq,
            request_success_seq.get(request_key, -1),
        )
        adapter_success_seq[adapter_key] = max(
            success_seq,
            adapter_success_seq.get(adapter_key, -1),
        )

    for successful_event in (
        final_asr,
        route_event,
        safety_event,
        fast_event,
    ):
        record_success(
            successful_event.get("adapter_id"),
            successful_event.get("adapter_request_id"),
            successful_event,
        )
    record_success(
        fast_event.get("qwen_candidate_adapter_id"),
        fast_event.get("qwen_candidate_adapter_request_id"),
        candidate_event,
    )

    gate_seq = int(gate_event["event_seq"])
    capability_snapshots = [
        event
        for event in ordered_events
        if event.get("event_name")
        == "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED"
        and int(event["event_seq"]) < gate_seq
    ]
    latest_snapshot = (
        max(
            capability_snapshots,
            key=lambda event: int(event["event_seq"]),
        )
        if capability_snapshots
        else None
    )
    snapshot_seq = (
        int(latest_snapshot["event_seq"])
        if latest_snapshot is not None
        else -1
    )
    if latest_snapshot is not None:
        try:
            snapshot_modes = {
                str(adapter_id): str(output_mode)
                for adapter_id, output_mode in zip(
                    latest_snapshot["adapter_ids"],
                    latest_snapshot["output_modes"],
                    strict=True,
                )
            }
        except (KeyError, TypeError, ValueError):
            snapshot_modes = {}
        if any(
            snapshot_modes.get(adapter_id) == "degraded"
            for adapter_id in adapter_success_seq
        ):
            raise ReplayValidationError(
                "native PCM Gate PASS cannot contradict the current degraded "
                "adapter capability snapshot"
            )
        if (
            gate_event.get("output_mode") != "mock"
            and any(
                latest_snapshot.get(field) is False
                for field in (
                    "supports_native_pcm",
                    "supports_provider_native_audio_release",
                )
            )
        ):
            raise ReplayValidationError(
                "native PCM Gate PASS requires explicit current provider "
                "native-audio capability"
            )

    native_capability_names = {
        "supports_native_pcm",
        "supports_provider_native_audio_release",
        "native_pcm_release",
    }
    adverse_event_names = {
        "ADAPTER_HEALTHCHECK_FAILED",
        "ADAPTER_REQUEST_FAILED",
        "ADAPTER_OUTPUT_VALIDATION_FAILED",
        "ADAPTER_OUTPUT_DEGRADED",
    }
    for event in ordered_events:
        event_seq = int(event["event_seq"])
        if (
            event.get("event_name") not in adverse_event_names
            or not snapshot_seq < event_seq < gate_seq
        ):
            continue
        adapter_id = str(event.get("adapter_id", ""))
        if adapter_id not in adapter_success_seq:
            continue
        event_name = str(event["event_name"])
        request_id = event.get("adapter_request_id")
        request_key = (
            (adapter_id, str(request_id))
            if request_id not in (None, "")
            else None
        )
        if (
            event_name == "ADAPTER_OUTPUT_DEGRADED"
            and event.get("missing_capability") in native_capability_names
        ):
            raise ReplayValidationError(
                "native PCM Gate PASS cannot contradict an explicit relevant "
                "Qwen native capability degradation"
            )
        if (
            event_name == "ADAPTER_OUTPUT_DEGRADED"
            and request_key is not None
            and request_key in request_success_seq
        ):
            raise ReplayValidationError(
                "native PCM Gate PASS cannot coexist with a terminal "
                "degradation for its bound adapter request"
            )
        if event_name in {
            "ADAPTER_REQUEST_FAILED",
            "ADAPTER_OUTPUT_VALIDATION_FAILED",
        }:
            if (
                request_key is not None
                and request_key in request_success_seq
            ):
                raise ReplayValidationError(
                    "native PCM Gate PASS cannot coexist with a terminal "
                    "failure for its bound adapter request"
                )
            continue
        if (
            event_name
            in {"ADAPTER_HEALTHCHECK_FAILED", "ADAPTER_OUTPUT_DEGRADED"}
            and event_seq > adapter_success_seq[adapter_id]
            and (
                request_key is None
                or request_key in request_success_seq
            )
        ):
            raise ReplayValidationError(
                "native PCM Gate PASS cannot follow a current relevant "
                "adapter health or degradation failure"
            )


def _validate_adr018_native_authority_closure(
    ordered_events: Sequence[Mapping[str, Any]],
    *,
    events_by_id: Mapping[str, Mapping[str, Any]],
    validated_parallel_fast_event_ids: set[str],
) -> None:
    authorities_by_token: dict[
        str,
        tuple[
            Mapping[str, Any],
            Mapping[str, Any],
            Mapping[str, Any],
        ],
    ] = {}
    authorities_by_output_id: dict[
        str,
        tuple[
            str,
            Mapping[str, Any],
            Mapping[str, Any],
            Mapping[str, Any],
        ],
    ] = {}
    for gate in ordered_events:
        if (
            gate.get("event_name") != "FOREGROUND_ACT_GATE_PASSED"
            or not _is_adr018_parallel_event(gate)
            or gate.get("release_token_ref") in (None, "")
        ):
            continue
        candidate = events_by_id.get(str(gate.get("candidate_event_id", "")))
        fast_event = (
            events_by_id.get(
                str(candidate.get("fast_interaction_output_event_id", ""))
            )
            if candidate is not None
            else None
        )
        if (
            candidate is None
            or candidate.get("event_name")
            != "FOREGROUND_REPLY_CANDIDATE_EMITTED"
            or fast_event is None
            or str(fast_event.get("event_id"))
            not in validated_parallel_fast_event_ids
        ):
            continue
        matching_outputs = [
            event
            for event in ordered_events
            if event.get("event_name") == "FOREGROUND_OUTPUT_COMMITTED"
            and _is_adr018_parallel_event(event)
            and event.get("caused_by_event_id") == gate.get("event_id")
            and event.get("gate_event_id") == gate.get("event_id")
            and event.get("release_token_ref")
            == gate.get("release_token_ref")
            and event.get("user_visible_channel") == "audio_pending"
        ]
        if len(matching_outputs) != 1:
            continue
        output = matching_outputs[0]
        token = str(gate["release_token_ref"])
        if token in authorities_by_token:
            raise ReplayValidationError(
                "provider-native release token must authorize exactly one "
                "parallel Gate and audio-pending output"
            )
        output_id = str(output["event_id"])
        if output_id in authorities_by_output_id:
            raise ReplayValidationError(
                "provider-native audio-pending output must have exactly one "
                "release-token authority"
            )
        authorities_by_token[token] = (gate, output, candidate)
        authorities_by_output_id[output_id] = (
            token,
            gate,
            output,
            candidate,
        )

    parallel_native_source_output_ids = {
        str(event["event_id"])
        for event in ordered_events
        if (
            event.get("event_name") == "FOREGROUND_OUTPUT_COMMITTED"
            and _is_adr018_parallel_event(event)
            and event.get("user_visible_channel") == "audio_pending"
        )
        or (
            event.get("event_name") == "FOREGROUND_OUTPUT_DISCARDED"
            and _is_adr018_parallel_event(event)
        )
    }
    native_start_marker_fields = {
        "candidate_id",
        "qwen_response_id",
        "qwen_output_item_id",
        "qwen_output_index",
        "qwen_content_index",
        "candidate_transcript_digest",
        "candidate_pcm_manifest_digest",
    }
    starts_by_token: dict[str, list[Mapping[str, Any]]] = {}
    starts_by_span: dict[str, tuple[str, Mapping[str, Any]]] = {}
    native_event_ids: set[str] = set()
    native_chain_event_names = {
        "PLAYBACK_SPAN_STARTED",
        "PLAYBACK_COMMITTED",
        "PLAYBACK_FINISHED",
        "TTS_TRUNCATE_REQUESTED",
        "TTS_TRUNCATED",
    }
    for event in ordered_events:
        event_name = str(event["event_name"])
        if event_name != "PLAYBACK_SPAN_STARTED":
            continue
        is_native_start = (
            event.get("release_token_ref") not in (None, "")
            or event.get("caused_by_event_id")
            in parallel_native_source_output_ids
            or any(
                event.get(field) not in (None, "")
                for field in native_start_marker_fields
            )
        )
        if not is_native_start:
            continue
        if event.get("release_token_ref") in (None, ""):
            raise ReplayValidationError(
                "provider-native PLAYBACK_SPAN_STARTED requires a release "
                "token and cannot downgrade to non-native playback"
            )
        token = _required_text(
            event,
            "release_token_ref",
            event_name=event_name,
        )
        authority = authorities_by_token.get(token)
        if authority is None:
            raise ReplayValidationError(
                f"orphan {event_name} requires a prior validated parallel "
                "Gate PASS and audio-pending output authority"
            )
        _, output, _ = authority
        if (
            event.get("caused_by_event_id") != output.get("event_id")
            or not _event_seq_before(output, event)
        ):
            raise ReplayValidationError(
                "provider-native playback start must consume its exact prior "
                "audio-pending output authority"
            )
        starts_by_token.setdefault(token, []).append(event)
        playback_span_id = _required_text(
            event,
            "playback_span_id",
            event_name=event_name,
        )
        if playback_span_id in starts_by_span:
            raise ReplayValidationError(
                "provider-native playback span must identify exactly one "
                "release-token start"
            )
        starts_by_span[playback_span_id] = (token, event)
        native_event_ids.add(str(event["event_id"]))

    for token, starts in starts_by_token.items():
        if len(starts) != 1:
            raise ReplayValidationError(
                "provider-native release token can start playback only once"
            )

    for event in ordered_events:
        event_name = str(event["event_name"])
        if (
            event_name not in native_chain_event_names
            or event_name == "PLAYBACK_SPAN_STARTED"
        ):
            continue
        playback_span_value = event.get("playback_span_id")
        is_native_chain_event = (
            event.get("release_token_ref") not in (None, "")
            or event.get("commit_basis") == "provider_native_pcm"
            or (
                playback_span_value not in (None, "")
                and str(playback_span_value) in starts_by_span
            )
            or str(event.get("caused_by_event_id", ""))
            in native_event_ids
        )
        if not is_native_chain_event:
            continue
        if event.get("release_token_ref") in (None, ""):
            raise ReplayValidationError(
                f"provider-native {event_name} requires its release token "
                "and cannot downgrade to a non-native chain"
            )
        token = _required_text(
            event,
            "release_token_ref",
            event_name=event_name,
        )
        if token not in authorities_by_token:
            raise ReplayValidationError(
                f"orphan {event_name} requires a prior validated parallel "
                "Gate PASS and audio-pending output authority"
            )
        playback_span_id = _required_text(
            event,
            "playback_span_id",
            event_name=event_name,
        )
        start_binding = starts_by_span.get(playback_span_id)
        if (
            start_binding is None
            or start_binding[0] != token
            or not _event_seq_before(start_binding[1], event)
        ):
            raise ReplayValidationError(
                f"{event_name} must resolve to the sole prior playback start "
                "for its release-token authority"
            )
        native_event_ids.add(str(event["event_id"]))

    deliveries_by_token: dict[str, Mapping[str, Any]] = {}
    deliveries_by_output_id: dict[str, Mapping[str, Any]] = {}
    assistant_items: dict[str, str] = {}
    for delivery in ordered_events:
        if delivery.get("event_name") != "ASSISTANT_DELIVERY_DISPOSITIONED":
            continue
        output_id_value = delivery.get("source_output_event_id")
        playback_span_value = delivery.get("playback_span_id")
        is_native_delivery = (
            delivery.get("release_token_ref") not in (None, "")
            or (
                output_id_value not in (None, "")
                and str(output_id_value)
                in parallel_native_source_output_ids
            )
            or (
                playback_span_value not in (None, "")
                and str(playback_span_value) in starts_by_span
            )
            or str(delivery.get("caused_by_event_id", ""))
            in native_event_ids
        )
        if not is_native_delivery:
            continue
        if delivery.get("release_token_ref") in (None, ""):
            raise ReplayValidationError(
                "provider-native assistant delivery requires its release "
                "token and cannot downgrade to non-native delivery"
            )
        token = _required_text(
            delivery,
            "release_token_ref",
            event_name="ASSISTANT_DELIVERY_DISPOSITIONED",
        )
        output_id = _required_text(
            delivery,
            "source_output_event_id",
            event_name="ASSISTANT_DELIVERY_DISPOSITIONED",
        )
        authority = authorities_by_output_id.get(output_id)
        if (
            authority is None
            or authority[0] != token
            or not _event_seq_before(authority[2], delivery)
        ):
            raise ReplayValidationError(
                "assistant delivery must resolve to one prior validated "
                "parallel Gate PASS and audio-pending output authority"
            )
        if token in deliveries_by_token or output_id in deliveries_by_output_id:
            raise ReplayValidationError(
                "release token and audio-pending output require exactly one "
                "assistant delivery terminal"
            )
        deliveries_by_token[token] = delivery
        deliveries_by_output_id[output_id] = delivery
        assistant_item_ref = _required_text(
            delivery,
            "assistant_item_ref",
            event_name="ASSISTANT_DELIVERY_DISPOSITIONED",
        )
        prior_token = assistant_items.get(assistant_item_ref)
        if prior_token is not None and prior_token != token:
            raise ReplayValidationError(
                "assistant item cannot be rebound to another release token"
            )
        assistant_items[assistant_item_ref] = token

        starts = starts_by_token.get(token, [])
        if delivery.get("to_status") == "NOT_STARTED":
            if starts:
                raise ReplayValidationError(
                    "NOT_STARTED delivery requires zero authorized playback "
                    "starts"
                )
        elif delivery.get("to_status") in {"FULL", "TRUNCATED"}:
            if len(starts) != 1:
                raise ReplayValidationError(
                    "FULL or TRUNCATED delivery requires exactly the sole "
                    "authorized playback start"
                )
            start_assistant_item_ref = starts[0].get(
                "assistant_item_ref"
            )
            if (
                start_assistant_item_ref not in (None, "")
                and start_assistant_item_ref != assistant_item_ref
            ):
                raise ReplayValidationError(
                    "provider-native playback start and assistant delivery "
                    "must preserve the exact assistant item"
                )
            if (
                delivery.get("playback_span_id")
                != starts[0].get("playback_span_id")
            ):
                raise ReplayValidationError(
                    "assistant delivery must preserve its sole authorized "
                    "playback span"
                )


def _validate_adr018_playback_commit_series(
    committed: Sequence[Mapping[str, Any]],
    *,
    playback_start: Mapping[str, Any],
    terminal_event: Mapping[str, Any],
    release_token_ref: str,
    ordered_events: Sequence[Mapping[str, Any]],
    maximum_offset_ms: int,
    optional_finish: Mapping[str, Any] | None = None,
) -> tuple[Mapping[str, Any], ...]:
    playback_span_id = playback_start.get("playback_span_id")
    ordered_commits = tuple(
        sorted(committed, key=lambda event: int(event["event_seq"]))
    )
    progress_events = [
        event
        for event in ordered_events
        if event.get("event_name") == "PLAYBACK_PROGRESS"
        and event.get("playback_span_id") == playback_span_id
        and _event_seq_before(playback_start, event)
        and _event_seq_before(event, terminal_event)
    ]
    allowed_predecessor_ids = {str(playback_start["event_id"])}
    prior_offset = -1
    for commit in ordered_commits:
        allowed_predecessor_ids.update(
            str(progress["event_id"])
            for progress in progress_events
            if _event_seq_before(progress, commit)
        )
        if (
            optional_finish is not None
            and _event_seq_before(optional_finish, commit)
        ):
            allowed_predecessor_ids.add(str(optional_finish["event_id"]))
        offset = _required_nonnegative_int(
            commit,
            "playback_offset_ms",
            event_name="PLAYBACK_COMMITTED",
        )
        if (
            commit.get("playback_span_id") != playback_span_id
            or commit.get("release_token_ref") != release_token_ref
            or commit.get("commit_basis") != "provider_native_pcm"
            or not _event_seq_before(playback_start, commit)
            or not _event_seq_before(commit, terminal_event)
            or str(commit.get("caused_by_event_id", ""))
            not in allowed_predecessor_ids
            or offset < prior_offset
            or offset > maximum_offset_ms
        ):
            raise ReplayValidationError(
                "provider-native playback commits must preserve span, release "
                "token, causal reachability, and monotonic offsets"
            )
        prior_offset = offset
        allowed_predecessor_ids.add(str(commit["event_id"]))
    return ordered_commits


def _validate_adr018_native_shadow_terminal(
    *,
    output_event: Mapping[str, Any],
    candidate_event: Mapping[str, Any],
    ordered_events: Sequence[Mapping[str, Any]],
) -> None:
    shadows = [
        event
        for event in ordered_events
        if event.get("event_name")
        == "CANDIDATE_AUDIO_SHADOW_VERIFICATION_EMITTED"
        and event.get("turn_id") == candidate_event.get("turn_id")
        and event.get("utterance_id") == candidate_event.get("utterance_id")
    ]
    if len(shadows) != 1:
        raise ReplayValidationError(
            "released provider-native PCM requires exactly one correlated "
            "shadow verification terminal"
        )
    shadow = shadows[0]
    exact_bindings = {
        "qwen_response_id": candidate_event.get("qwen_response_id"),
        "candidate_transcript_digest": candidate_event.get(
            "candidate_transcript_digest"
        ),
        "candidate_pcm_manifest_digest": candidate_event.get(
            "candidate_pcm_manifest_digest"
        ),
        "audio_format_ref": candidate_event.get("candidate_audio_format_ref"),
        "decoded_duration_ms": candidate_event.get(
            "candidate_audio_duration_ms"
        ),
    }
    shadow_matches = (
        _event_seq_before(output_event, shadow)
        and all(
            shadow.get(field) == expected
            for field, expected in exact_bindings.items()
        )
        and shadow.get("normalized_transcript_digest")
        == candidate_event.get("candidate_transcript_digest")
        and shadow.get("exact_numbers_entities_units_match") is True
        and shadow.get("equivalence") == "MATCH"
    )
    if shadow_matches:
        return

    rebuild = _require_adr018_taint_rebuild_after(
        shadow,
        ordered_events=ordered_events,
        reason="candidate audio shadow failure",
    )
    later_native_passes = [
        event
        for event in ordered_events
        if event.get("event_name") == "FOREGROUND_ACT_GATE_PASSED"
        and int(event["event_seq"]) > int(shadow["event_seq"])
        and event.get("native_pcm_capability_check") == "PASS"
    ]
    if later_native_passes:
        raise ReplayValidationError(
            "failed candidate audio shadow verification disables later native "
            "PCM release"
        )
    if int(rebuild["event_seq"]) <= int(shadow["event_seq"]):
        raise ReplayValidationError(
            "candidate audio shadow failure rebuild must follow the terminal"
        )


def _validate_adr018_delivery_cleanup(
    delivery: Mapping[str, Any],
    *,
    ordered_events: Sequence[Mapping[str, Any]],
    require_cleanup: bool,
    unknown_offset_requires_rebuild: bool,
) -> None:
    cleanup_status = delivery.get("provider_item_cleanup_status")
    if require_cleanup and cleanup_status not in {"ACKNOWLEDGED", "TAINTED"}:
        raise ReplayValidationError(
            f"{delivery.get('to_status')} assistant delivery requires "
            "acknowledged cleanup or taint/rebuild"
        )
    if delivery.get("to_status") == "TRUNCATED" and delivery.get(
        "delivery_offset_status"
    ) not in {"KNOWN", "UNKNOWN"}:
        raise ReplayValidationError(
            "TRUNCATED assistant delivery requires KNOWN or UNKNOWN offset"
        )
    if unknown_offset_requires_rebuild and cleanup_status != "TAINTED":
        raise ReplayValidationError(
            "TRUNCATED UNKNOWN delivery offset requires provider taint/rebuild"
        )
    if cleanup_status == "TAINTED":
        _require_adr018_taint_rebuild_after(
            delivery,
            ordered_events=ordered_events,
            reason="assistant item cleanup failure",
        )


def _require_adr018_taint_rebuild_after(
    source_event: Mapping[str, Any],
    *,
    ordered_events: Sequence[Mapping[str, Any]],
    reason: str,
) -> Mapping[str, Any]:
    source_event_id = str(source_event["event_id"])
    taints = [
        event
        for event in ordered_events
        if event.get("event_name") == "PROVIDER_CONTEXT_STATE_CHANGED"
        and event.get("to_state") == "TAINTED"
        and int(event["event_seq"]) > int(source_event["event_seq"])
        and (
            event.get("caused_by_event_id") == source_event_id
            or source_event_id in set(event.get("source_event_ids", ()))
        )
    ]
    if len(taints) != 1:
        raise ReplayValidationError(
            f"{reason} requires exactly one causally bound TAINTED transition"
        )
    taint = taints[0]
    taint_event_id = str(taint["event_id"])
    rebuilds = [
        event
        for event in ordered_events
        if event.get("event_name") == "PROVIDER_CONTEXT_STATE_CHANGED"
        and event.get("from_state") == "TAINTED"
        and event.get("to_state") == "REBUILDING"
        and int(event["event_seq"]) > int(taint["event_seq"])
        and (
            event.get("caused_by_event_id") == taint_event_id
            or taint_event_id in set(event.get("source_event_ids", ()))
        )
    ]
    if len(rebuilds) != 1:
        raise ReplayValidationError(
            f"{reason} requires exactly one causally bound REBUILDING "
            "transition"
        )
    return rebuilds[0]


def _adr018_fence_before(
    ordered_events: Sequence[Mapping[str, Any]],
    *,
    event_seq: int,
) -> tuple[int, int]:
    playback_epoch = 0
    interaction_state_version = 0
    for event in ordered_events:
        if int(event["event_seq"]) >= event_seq:
            break
        if event.get("event_name") not in {
            "PROVIDER_CONTEXT_STATE_CHANGED",
            "INTERRUPT_CANDIDATE",
        }:
            continue
        if event.get("playback_epoch") not in (None, ""):
            playback_epoch = int(event["playback_epoch"])
        if event.get("interaction_state_version") not in (None, ""):
            interaction_state_version = int(event["interaction_state_version"])
    return playback_epoch, interaction_state_version


def _parallel_event_turn_key(
    event: Mapping[str, Any],
    *,
    events_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[str, str] | None:
    if event.get("turn_id") not in (None, "") and event.get(
        "utterance_id"
    ) not in (None, ""):
        return _turn_key(event)
    candidate_event_id = event.get("candidate_event_id")
    candidate_event = events_by_id.get(str(candidate_event_id))
    if (
        candidate_event is not None
        and candidate_event.get("turn_id") not in (None, "")
        and candidate_event.get("utterance_id") not in (None, "")
    ):
        return _turn_key(candidate_event)
    gate_event = events_by_id.get(str(event.get("gate_event_id", "")))
    if gate_event is not None:
        candidate_event = events_by_id.get(
            str(gate_event.get("candidate_event_id", ""))
        )
        if candidate_event is not None:
            return _turn_key(candidate_event)
    return None


def _required_referenced_event(
    event: Mapping[str, Any],
    field: str,
    *,
    expected_event_name: str,
    events_by_id: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any]:
    event_id = _required_text(
        event,
        field,
        event_name=str(event["event_name"]),
    )
    referenced = events_by_id.get(event_id)
    if referenced is None or referenced.get("event_name") != expected_event_name:
        raise ReplayValidationError(
            f"{event['event_name']} {field} must reference "
            f"{expected_event_name}"
        )
    return referenced


def _required_text(
    event: Mapping[str, Any],
    field: str,
    *,
    event_name: str,
) -> str:
    value = event.get(field)
    if not isinstance(value, str) or not value:
        raise ReplayValidationError(f"{event_name} requires non-empty {field}")
    return value


def _required_nonnegative_int(
    event: Mapping[str, Any],
    field: str,
    *,
    event_name: str,
) -> int:
    value = event.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReplayValidationError(
            f"{event_name} {field} must be a non-negative integer"
        )
    return value


def _required_confidence(
    event: Mapping[str, Any],
    *,
    event_name: str,
) -> float:
    value = event.get("confidence")
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0.0 <= float(value) <= 1.0
    ):
        raise ReplayValidationError(
            f"{event_name} confidence must be a number from 0 to 1"
        )
    return float(value)


def _required_bounded_string_tuple(
    event: Mapping[str, Any],
    field: str,
    *,
    event_name: str,
) -> tuple[str, ...]:
    value = event.get(field)
    if (
        not isinstance(value, (list, tuple))
        or isinstance(value, (str, bytes))
        or len(value) > 32
        or any(not isinstance(item, str) or not item for item in value)
    ):
        raise ReplayValidationError(
            f"{event_name} {field} must be a bounded string sequence"
        )
    return tuple(value)


def _required_string_refs(
    event: Mapping[str, Any],
    field: str,
    *,
    event_name: str,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    value = event.get(field)
    if (
        not isinstance(value, (list, tuple))
        or isinstance(value, (str, bytes))
        or (not value and not allow_empty)
        or any(not isinstance(item, str) or not item for item in value)
    ):
        raise ReplayValidationError(
            f"{event_name} {field} must contain bounded event refs"
        )
    return tuple(value)


def _require_source_refs_include(
    event: Mapping[str, Any],
    required: set[str],
) -> None:
    source_event_ids = set(
        _required_string_refs(
            event,
            "source_event_ids",
            event_name=str(event["event_name"]),
        )
    )
    if not required.issubset(source_event_ids):
        raise ReplayValidationError(
            f"{event['event_name']} source_event_ids must preserve all joined "
            "ADR-018 authorities"
        )


def _require_prior_event(
    event: Mapping[str, Any],
    referenced_event_id: str,
    *,
    events_by_id: Mapping[str, Mapping[str, Any]],
    label: str,
) -> Mapping[str, Any]:
    referenced = events_by_id.get(referenced_event_id)
    if referenced is None or not _event_seq_before(referenced, event):
        raise ReplayValidationError(
            f"{event['event_name']} {label} must reference a prior event"
        )
    return referenced


def _require_prior_source_event_ids(
    event: Mapping[str, Any],
    *,
    events_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    for source_event_id in _required_string_refs(
        event,
        "source_event_ids",
        event_name=str(event["event_name"]),
    ):
        _require_prior_event(
            event,
            source_event_id,
            events_by_id=events_by_id,
            label="source_event_ids",
        )


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


def _stable_foreground_authority(
    ordered_events: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, str]]]:
    routers: list[dict[str, str]] = []
    terminal_gates: list[dict[str, str]] = []
    commits: list[dict[str, str]] = []
    for event in ordered_events:
        event_name = str(event["event_name"])
        if event_name == "ROUTER_DECISION_EMITTED":
            routers.append(
                {
                    "turn_id": str(event["turn_id"]),
                    "utterance_id": str(event["utterance_id"]),
                    "event_id": str(event["event_id"]),
                    "router_decision": str(event["router_decision"]),
                }
            )
        elif event_name in {"FOREGROUND_ACT_GATE_PASSED", "FOREGROUND_ACT_GATE_FAILED"}:
            terminal_gates.append(
                {
                    "event_id": str(event["event_id"]),
                    "gate_decision_id": str(event["gate_decision_id"]),
                    "router_decision_event_id": str(event["router_decision_event_id"]),
                    "gate_result": (
                        "passed"
                        if event_name == "FOREGROUND_ACT_GATE_PASSED"
                        else "failed"
                    ),
                }
            )
        elif event_name == "FOREGROUND_OUTPUT_COMMITTED":
            commits.append(
                {
                    "turn_id": str(event["turn_id"]),
                    "utterance_id": str(event["utterance_id"]),
                    "event_id": str(event["event_id"]),
                    "router_decision_event_id": str(event["router_decision_event_id"]),
                    "gate_event_id": str(event.get("gate_event_id", "")),
                    "output_basis": str(event["output_basis"]),
                    "output_ref": str(event["output_ref"]),
                    "foreground_act": str(event["foreground_act"]),
                }
            )
    return {
        "routers": routers,
        "terminal_gates": terminal_gates,
        "commits": commits,
    }


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
