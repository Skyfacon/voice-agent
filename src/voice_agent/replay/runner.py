from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from voice_agent.events.envelope import EventValidationError, validate_event_envelope
from voice_agent.events.registry import get_event_definition
from voice_agent.replay.manifest import ReplayManifest, validate_replay_manifest
from voice_agent.replay.state_digest import state_digest
from voice_agent.state.adapter_health_state import AdapterHealthState
from voice_agent.state.interaction_state import InteractionState
from voice_agent.state.playback_state import PlaybackState
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
    interaction_state: InteractionState
    task_focus_state: TaskFocusState
    playback_state: PlaybackState
    adapter_health_state: AdapterHealthState
    trace_privacy_state: TracePrivacyState
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
    ordered_events = _validate_and_order_events(raw_events)

    diagnostics: dict[str, Any] = {
        "ignored_events": [],
        "data_plane_refs": [],
    }
    interaction_state = InteractionState()
    task_focus_state = TaskFocusState()
    playback_state = PlaybackState()
    adapter_health_state = AdapterHealthState()
    trace_privacy_state = TracePrivacyState.from_manifest(manifest.to_dict())

    for event in ordered_events:
        diagnostics["data_plane_refs"].extend(_unavailable_data_plane_refs(event))
        handled = [
            interaction_state.reduce_event(event),
            task_focus_state.reduce_event(event),
            playback_state.reduce_event(event),
            adapter_health_state.reduce_event(event),
            trace_privacy_state.reduce_event(event),
        ]
        if not any(handled):
            diagnostics["ignored_events"].append(
                {
                    "event_id": event["event_id"],
                    "event_name": event["event_name"],
                    "reason": "no_slice3_reducer_owner",
                }
            )

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
    )

    return ReplayResult(
        replay_mode=manifest.replay_mode,
        fixture_domain=manifest.fixture_domain,
        manifest=manifest,
        ordered_events=tuple(deepcopy(ordered_events)),
        interaction_state=interaction_state,
        task_focus_state=task_focus_state,
        playback_state=playback_state,
        adapter_health_state=adapter_health_state,
        trace_privacy_state=trace_privacy_state,
        diagnostics=diagnostics,
        state_digest=digest,
        result_status=result_status,
    )


def _validate_and_order_events(raw_events: Sequence[object]) -> list[dict[str, Any]]:
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
    _validate_post_commit_understanding_and_router_order(ordered_events)
    return ordered_events


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
        if caused_by_event_id not in seen_event_ids:
            raise ReplayValidationError(
                f"caused_by_event_id must reference an earlier event_seq: {caused_by_event_id}"
            )
        seen_event_ids.add(event_id)


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
