from __future__ import annotations

import io
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote
import wave

from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.router.router import (
    MVP1Router,
    MVP1TaskFocusUpdateEmitter,
    RouterContext,
    TaskFocusSnapshot,
)
from voice_agent.runtime.adapter_callback_boundary import AdapterCallbackAppendBoundary
from voice_agent.runtime.assembly import RuntimeAdapterAssemblyConfig
from voice_agent.runtime.slowtask_orchestrator import MVP1SlowTaskHappyPathOrchestrator
from voice_agent.runtime.session import start_configured_session, start_mvp0_session
from voice_agent.slowtask.mock_runtime import MockSlowTaskRuntime
from voice_agent.understanding.mock_asr import emit_mock_asr_frame
from voice_agent.user_patch.evidence_pack import UserPatchEvidencePackRuntime


MVP4_SESSION_ID = "sess_mvp4_voice_e2e_provider_free"
MVP4_CONVERSATION_ID = "conv_mvp4_voice_e2e_provider_free"
MVP4_FIXTURE_REPLAY_ID = "replay_mvp4_provider_free_voice_e2e_000"
MVP4_FIXTURE_SOURCE_TRACE_REF = "fixture://mvp4/000-provider-free-voice-e2e"
MVP4_REAL_EVIDENCE_SESSION_ID = "sess_mvp4_voice_e2e_real_evidence"
MVP4_REAL_EVIDENCE_CONVERSATION_ID = "conv_mvp4_voice_e2e_real_evidence"
MVP4_REAL_EVIDENCE_REPLAY_ID = "replay_mvp4_real_evidence_paths_in_memory"
MVP4_REAL_EVIDENCE_SOURCE_TRACE_REF = "fixture://mvp4/in-memory-real-evidence-paths"
MVP4_REAL_EVIDENCE_CAPABILITY_REF = "capability://synthetic/mvp4/real-evidence-fake-transport"
MVP4_REAL_EVIDENCE_CAPABILITY_VERSION = "mvp4.real-evidence.fake-transport.v1"


class MVP4ArtifactSafetyError(ValueError):
    pass


@dataclass(frozen=True)
class MVP4AudioInputMetadata:
    fixture_id: str
    input_source: str
    duration_ms: int
    sample_rate_hz: int
    channel_count: int
    sample_width_bytes: int
    frame_count: int
    audio_format: str
    audio_format_ref: str
    safe_audio_ref: str
    replay_export_allowed: bool

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "input_source": self.input_source,
            "duration_ms": self.duration_ms,
            "sample_rate_hz": self.sample_rate_hz,
            "channel_count": self.channel_count,
            "sample_width_bytes": self.sample_width_bytes,
            "frame_count": self.frame_count,
            "audio_format": self.audio_format,
            "audio_format_ref": self.audio_format_ref,
            "safe_audio_ref": self.safe_audio_ref,
            "replay_export_allowed": self.replay_export_allowed,
            "raw_audio_included": False,
            "raw_path_included": False,
            "data_uri_included": False,
        }


@dataclass(frozen=True)
class MVP4ProviderFreeVoiceE2EResult:
    audio_input: MVP4AudioInputMetadata
    events: tuple[dict[str, Any], ...]

    @property
    def turn_committed_events(self) -> tuple[dict[str, Any], ...]:
        return self._events_named("TURN_INGRESS_COMMITTED")

    @property
    def asr_frame_events(self) -> tuple[dict[str, Any], ...]:
        return self._events_named("MOCK_ASR_FRAME_EMITTED")

    @property
    def thinker_frame_events(self) -> tuple[dict[str, Any], ...]:
        return self._events_named("MOCK_THINKER_FRAME_EMITTED")

    @property
    def router_decision_events(self) -> tuple[dict[str, Any], ...]:
        return self._events_named("ROUTER_DECISION_EMITTED")

    def to_replay_fixture(self) -> dict[str, Any]:
        if not self.audio_input.replay_export_allowed:
            raise MVP4ArtifactSafetyError("local wav metadata is blocked from replay export")
        fixture = {
            "replay_manifest": {
                "manifest_schema_version": "1.0",
                "replay_id": MVP4_FIXTURE_REPLAY_ID,
                "source_trace_ref": MVP4_FIXTURE_SOURCE_TRACE_REF,
                "replay_mode": "deterministic",
                "event_schema_version_range": ["1.0"],
                "fixture_domain": "GITHUB_ALLOWED",
                "generated_from": "synthetic",
                "contains_raw_audio": False,
                "contains_raw_trace": False,
                "contains_real_user_input": False,
                "contains_secrets": False,
                "contains_unredacted_tool_result": False,
                "contains_large_raw_web_content": False,
                "allowed_re_eval_components": [],
            },
            "events": deepcopy(list(self.events)),
        }
        validate_provider_free_fixture_safety(fixture)
        return fixture

    def _events_named(self, event_name: str) -> tuple[dict[str, Any], ...]:
        return tuple(
            deepcopy(event)
            for event in self.events
            if event.get("event_name") == event_name
        )


@dataclass(frozen=True)
class MVP4RealEvidenceVoiceE2EResult:
    audio_input: MVP4AudioInputMetadata
    events: tuple[dict[str, Any], ...]
    thinker_metadata: Mapping[str, Any]
    asr_metadata: Mapping[str, Any]

    @property
    def turn_committed_event(self) -> dict[str, Any]:
        return self._single_event_named("TURN_INGRESS_COMMITTED")

    @property
    def thinker_frame_event(self) -> dict[str, Any]:
        return self._single_event_named("THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED")

    @property
    def asr_frame_event(self) -> dict[str, Any]:
        return self._single_event_named("ASR_TRANSCRIPT_OUTPUT_EMITTED")

    @property
    def router_decision_event(self) -> dict[str, Any]:
        return self._single_event_named("ROUTER_DECISION_EMITTED")

    def to_replay_fixture(self) -> dict[str, Any]:
        if not self.audio_input.replay_export_allowed:
            raise MVP4ArtifactSafetyError("local wav metadata is blocked from replay export")
        fixture = {
            "replay_manifest": {
                "manifest_schema_version": "1.0",
                "replay_id": MVP4_REAL_EVIDENCE_REPLAY_ID,
                "source_trace_ref": MVP4_REAL_EVIDENCE_SOURCE_TRACE_REF,
                "replay_mode": "deterministic",
                "event_schema_version_range": ["1.0"],
                "fixture_domain": "GITHUB_ALLOWED",
                "generated_from": "synthetic",
                "contains_raw_audio": False,
                "contains_raw_trace": False,
                "contains_real_user_input": False,
                "contains_secrets": False,
                "contains_unredacted_tool_result": False,
                "contains_large_raw_web_content": False,
                "allowed_re_eval_components": [],
            },
            "events": deepcopy(list(self.events)),
        }
        validate_mvp4_fixture_safety(fixture)
        return fixture

    def _single_event_named(self, event_name: str) -> dict[str, Any]:
        matches = [event for event in self.events if event.get("event_name") == event_name]
        if len(matches) != 1:
            raise MVP4ArtifactSafetyError(f"expected exactly one {event_name} event")
        return deepcopy(matches[0])


@dataclass(frozen=True)
class MVP4RouterOutcomeVoiceE2EResult:
    audio_input: MVP4AudioInputMetadata
    events: tuple[dict[str, Any], ...]
    turn_committed_event: dict[str, Any]
    asr_frame_event: dict[str, Any]
    thinker_frame_event: dict[str, Any]
    router_decision_event: dict[str, Any]
    task_focus_state_event: dict[str, Any]
    response_summary: Mapping[str, Any]
    control_plane_summary: Mapping[str, Any]


@dataclass(frozen=True)
class _TurnRuntimeResult:
    turn_committed_event: dict[str, Any]
    asr_frame_event: dict[str, Any]
    thinker_frame_event: dict[str, Any]
    router_decision_event: dict[str, Any]
    task_focus_state_event: dict[str, Any]


def load_synthetic_wav_metadata(
    *,
    fixture_id: str,
    duration_ms: int,
    sample_rate_hz: int,
    channel_count: int,
    sample_width_bytes: int = 2,
) -> MVP4AudioInputMetadata:
    safe_fixture_id = _safe_slug(_require_safe_token(fixture_id, "fixture_id"))
    duration = _positive_int(duration_ms, "duration_ms")
    sample_rate = _positive_int(sample_rate_hz, "sample_rate_hz")
    channels = _positive_int(channel_count, "channel_count")
    sample_width = _positive_int(sample_width_bytes, "sample_width_bytes")
    frame_count = max(1, round(sample_rate * duration / 1000))
    return MVP4AudioInputMetadata(
        fixture_id=safe_fixture_id,
        input_source="synthetic",
        duration_ms=duration,
        sample_rate_hz=sample_rate,
        channel_count=channels,
        sample_width_bytes=sample_width,
        frame_count=frame_count,
        audio_format="wav",
        audio_format_ref=_audio_format_ref("synthetic", safe_fixture_id, sample_rate, channels, sample_width),
        safe_audio_ref=f"audio://synthetic/mvp4/{safe_fixture_id}",
        replay_export_allowed=True,
    )


def load_local_wav_metadata(
    wav_path: str | Path,
    *,
    allow_local_wav: bool = False,
    fixture_id: str = "redacted-local-wav",
) -> MVP4AudioInputMetadata:
    if isinstance(wav_path, str) and wav_path.lower().startswith("data:"):
        raise ValueError("MVP4 local wav loader rejects data URI inputs")
    if not allow_local_wav:
        raise ValueError("MVP4 local wav loading requires explicit opt-in")

    path = Path(wav_path)
    if path.suffix.lower() != ".wav":
        raise ValueError("MVP4 local audio loader accepts wav metadata only")

    safe_fixture_id = _safe_slug(_require_safe_token(fixture_id, "fixture_id"))
    with wave.open(str(path), "rb") as wav_file:
        channel_count = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        frame_count = wav_file.getnframes()

    duration_ms = round(frame_count * 1000 / sample_rate)
    return MVP4AudioInputMetadata(
        fixture_id=safe_fixture_id,
        input_source="local_opt_in",
        duration_ms=duration_ms,
        sample_rate_hz=sample_rate,
        channel_count=channel_count,
        sample_width_bytes=sample_width,
        frame_count=frame_count,
        audio_format="wav",
        audio_format_ref=_audio_format_ref("redacted", safe_fixture_id, sample_rate, channel_count, sample_width),
        safe_audio_ref=f"audio://redacted/mvp4/{safe_fixture_id}",
        replay_export_allowed=False,
    )


def run_provider_free_voice_e2e(
    *,
    audio_input: MVP4AudioInputMetadata | None = None,
) -> MVP4ProviderFreeVoiceE2EResult:
    audio_input = audio_input or load_synthetic_wav_metadata(
        fixture_id="synthetic-voice-e2e-001",
        duration_ms=1000,
        sample_rate_hz=16000,
        channel_count=1,
    )
    if not isinstance(audio_input, MVP4AudioInputMetadata):
        raise TypeError("audio_input must be MVP4AudioInputMetadata")

    startup = start_mvp0_session(
        session_id=MVP4_SESSION_ID,
        conversation_id=MVP4_CONVERSATION_ID,
        runtime_config_ref="config://synthetic/mvp4/provider-free-voice-e2e",
        created_monotonic_ms=4100,
        created_wall_clock_ms=1700000004100,
    )
    journal = startup.journal
    caused_by_event_id = str(journal.events()[-1]["event_id"])

    fast = _emit_voice_turn(
        journal=journal,
        audio_input=audio_input,
        label="fast",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=4110,
        created_wall_clock_ms=1700000004110,
        router_context=RouterContext(task_focus_snapshot=TaskFocusSnapshot()),
        task_focus_hint="FOREGROUND_CHAT",
        task_like=False,
        complexity_hint="simple",
        focus_confidence=0.86,
        evidence_uncertainty="low",
    )

    spawn = _emit_voice_turn(
        journal=journal,
        audio_input=audio_input,
        label="spawn",
        caused_by_event_id=str(fast.task_focus_state_event["event_id"]),
        created_monotonic_ms=4210,
        created_wall_clock_ms=1700000004210,
        router_context=RouterContext(task_focus_snapshot=TaskFocusSnapshot()),
        task_focus_hint="NEW_TASK_CANDIDATE",
        task_like=True,
        complexity_hint="complex",
        focus_confidence=0.91,
        evidence_uncertainty="low",
    )
    active_task_id = "task_mvp4_voice_e2e_spawn"
    active_task = _append_minimal_active_slowtask(
        journal=journal,
        spawn_result=spawn,
        task_id=active_task_id,
        created_monotonic_ms=4300,
        created_wall_clock_ms=1700000004300,
    )
    active_focus = MVP1TaskFocusUpdateEmitter(journal).emit_update(
        router_decision_event=spawn.router_decision_event,
        event_id="evt_mvp4_voice_e2e_spawn_task_focus_active",
        created_monotonic_ms=4304,
        created_wall_clock_ms=1700000004304,
        active_task_id=active_task_id,
        foreground_mode="SLOWTASK_ACTIVE",
        default_patch_policy="ACTIVE_TASK_PATCH_ONLY",
    )

    _emit_voice_turn(
        journal=journal,
        audio_input=audio_input,
        label="patch",
        caused_by_event_id=str(active_focus["event_id"]),
        created_monotonic_ms=4410,
        created_wall_clock_ms=1700000004410,
        router_context=RouterContext(
            task_focus_snapshot=TaskFocusSnapshot(
                active_task_id=active_task_id,
                lifecycle_phase=str(active_task["to_state"]),
                terminal_status=None,
                current_plan_version=1,
            )
        ),
        task_focus_hint="ACTIVE_TASK_PATCH",
        task_like=False,
        complexity_hint="simple",
        focus_confidence=0.92,
        evidence_uncertainty="low",
    )

    return MVP4ProviderFreeVoiceE2EResult(
        audio_input=audio_input,
        events=tuple(journal.events()),
    )


def run_real_evidence_voice_e2e(
    *,
    audio_input: MVP4AudioInputMetadata | None = None,
    thinker_transport: object,
    thinker_credential_value: str,
    asr_transport: object,
    asr_approval_packet: Mapping[str, Any],
    asr_env: Mapping[str, str],
    asr_credential_env_var: str,
    audio_payload: bytes | None = None,
) -> MVP4RealEvidenceVoiceE2EResult:
    audio_input = audio_input or load_synthetic_wav_metadata(
        fixture_id="synthetic-real-evidence-001",
        duration_ms=1000,
        sample_rate_hz=16000,
        channel_count=1,
    )
    if not isinstance(audio_input, MVP4AudioInputMetadata):
        raise TypeError("audio_input must be MVP4AudioInputMetadata")
    if not isinstance(asr_approval_packet, Mapping):
        raise TypeError("asr_approval_packet must be a mapping")
    if not isinstance(asr_env, Mapping):
        raise TypeError("asr_env must be a mapping")
    if not isinstance(asr_credential_env_var, str) or asr_credential_env_var == "":
        raise ValueError("asr_credential_env_var must be a non-empty string")

    payload = audio_payload if audio_payload is not None else _build_synthetic_wav_bytes(audio_input)
    startup, asr_config = _start_real_evidence_session(
        asr_approval_packet=asr_approval_packet,
        asr_credential_env_var=asr_credential_env_var,
    )
    journal = startup.journal
    caused_by_event_id = str(journal.events()[-1]["event_id"])
    committed = _append_audio_turn(
        journal=journal,
        audio_input=audio_input,
        label="real_evidence",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=5110,
        created_wall_clock_ms=1700000005110,
    )

    from voice_agent.adapters.lalm_thinker_audio_native_runtime import (
        emit_lalm_thinker_audio_native_evidence_for_turn,
    )

    thinker_result = emit_lalm_thinker_audio_native_evidence_for_turn(
        boundary=AdapterCallbackAppendBoundary(journal),
        turn_committed_event=committed,
        case_id="mvp4-real-evidence",
        transport=thinker_transport,
        audio_payload=payload,
        audio_format="wav",
        credential_value=thinker_credential_value,
        created_monotonic_ms=5150,
        created_wall_clock_ms=1700000005150,
        adapter_id="mvp4_lalm_thinker_audio_native",
    )
    if not thinker_result.success or thinker_result.thinker_emission is None:
        raise MVP4ArtifactSafetyError("Thinker audio-native evidence was not emitted")
    thinker_event = thinker_result.thinker_emission.thinker_event

    from voice_agent.runtime.asr_session_hook import run_asr_for_committed_audio_turn

    asr_summary = run_asr_for_committed_audio_turn(
        journal=journal,
        turn_committed_event=committed,
        case_id="mvp4-real-evidence",
        audio_payload=payload,
        audio_mime_type="audio/wav",
        config=asr_config,
        transport=asr_transport,
        approval_packet=asr_approval_packet,
        env=asr_env,
        created_monotonic_ms=5160,
        created_wall_clock_ms=1700000005160,
    )
    asr_event = _single_event_for_turn(
        journal.events(),
        event_name="ASR_TRANSCRIPT_OUTPUT_EMITTED",
        turn_committed_event=committed,
    )

    MVP1Router(journal).emit_decision(
        turn_committed_event=committed,
        asr_frame_event=asr_event,
        thinker_frame_event=thinker_event,
        router_context=RouterContext(task_focus_snapshot=TaskFocusSnapshot()),
        event_id="evt_mvp4_voice_e2e_real_evidence_router_decision",
        task_focus_state_event_id="evt_mvp4_voice_e2e_real_evidence_task_focus_state",
        created_monotonic_ms=5170,
        created_wall_clock_ms=1700000005170,
    )

    return MVP4RealEvidenceVoiceE2EResult(
        audio_input=audio_input,
        events=tuple(journal.events()),
        thinker_metadata=thinker_result.to_metadata(),
        asr_metadata=asr_summary.to_metadata(),
    )


def run_mvp4_router_fast_only_voice_e2e(
    *,
    audio_input: MVP4AudioInputMetadata | None = None,
) -> MVP4RouterOutcomeVoiceE2EResult:
    audio_input = audio_input or load_synthetic_wav_metadata(
        fixture_id="synthetic-router-fast-only-001",
        duration_ms=900,
        sample_rate_hz=16000,
        channel_count=1,
    )
    journal = _start_mvp4_router_outcome_journal(label="fast_only")
    turn = _emit_real_evidence_voice_turn(
        journal=journal,
        audio_input=audio_input,
        label="router_fast",
        caused_by_event_id=str(journal.events()[-1]["event_id"]),
        created_monotonic_ms=6110,
        created_wall_clock_ms=1700000006110,
        router_context=RouterContext(task_focus_snapshot=TaskFocusSnapshot()),
        task_focus_hint="FOREGROUND_CHAT",
        task_like=False,
        complexity_hint="simple",
        focus_confidence=0.88,
        evidence_uncertainty="low",
    )
    response_summary = {
        "response_kind": "runtime_summary",
        "route": "FAST_ONLY",
        "source_router_event_id": turn.router_decision_event["event_id"],
        "response_text_ref": "response-text://synthetic/mvp4/router-fast-only",
        "real_tts_used": False,
        "voice_output": "none",
    }
    return _router_outcome_result(
        audio_input=audio_input,
        journal=journal,
        turn=turn,
        response_summary=response_summary,
        control_plane_summary={"route": "FAST_ONLY"},
    )


def run_mvp4_router_spawn_slowtask_voice_e2e(
    *,
    audio_input: MVP4AudioInputMetadata | None = None,
) -> MVP4RouterOutcomeVoiceE2EResult:
    audio_input = audio_input or load_synthetic_wav_metadata(
        fixture_id="synthetic-router-spawn-job-001",
        duration_ms=1100,
        sample_rate_hz=16000,
        channel_count=1,
    )
    journal = _start_mvp4_router_outcome_journal(label="spawn_slowtask")
    turn = _emit_real_evidence_voice_turn(
        journal=journal,
        audio_input=audio_input,
        label="router_spawn",
        caused_by_event_id=str(journal.events()[-1]["event_id"]),
        created_monotonic_ms=6210,
        created_wall_clock_ms=1700000006210,
        router_context=RouterContext(task_focus_snapshot=TaskFocusSnapshot()),
        task_focus_hint="NEW_TASK_CANDIDATE",
        task_like=True,
        complexity_hint="complex",
        focus_confidence=0.91,
        evidence_uncertainty="low",
    )
    task_id = "task_mvp4_router_outcome_spawn"
    source_evidence_refs = _voice_evidence_refs(turn)
    slowtask_result = MVP1SlowTaskHappyPathOrchestrator(journal).run_spawn_planning_completed(
        router_decision_event=turn.router_decision_event,
        task_id=task_id,
        initial_goal_ref="goal://synthetic/mvp4/router-outcome/spawn",
        source_evidence_refs=source_evidence_refs,
        evidence_refs=source_evidence_refs,
        resolved_arguments_ref="args://synthetic/mvp4/router-outcome/spawn",
        provenance_ref="provenance://synthetic/mvp4/router-outcome/spawn",
        field_provenance_refs=(
            "provenance://synthetic/mvp4/router-outcome/spawn/asr",
            "provenance://synthetic/mvp4/router-outcome/spawn/thinker",
        ),
        commitment_id="commitment_mvp4_router_outcome_spawn",
        commitment_ref="commitment://synthetic/mvp4/router-outcome/spawn",
        event_id_prefix="evt_mvp4_router_outcome_spawn",
        created_monotonic_ms=6300,
        created_wall_clock_ms=1700000006300,
    )
    commitment = _single_event_named(journal.events(), "SEMANTIC_COMMITMENT_EMITTED")
    response_summary = {
        "response_kind": "runtime_summary",
        "route": "SPAWN_SLOW_TASK",
        "source_event_id": commitment["event_id"],
        "response_text_ref": f"response-text://synthetic/mvp4/slowtask-mock/{task_id}",
        "real_tts_used": False,
        "voice_output": "none",
    }
    return _router_outcome_result(
        audio_input=audio_input,
        journal=journal,
        turn=turn,
        response_summary=response_summary,
        control_plane_summary={
            "route": "SPAWN_SLOW_TASK",
            "task_id": slowtask_result.task_id,
            "plan_version": slowtask_result.plan_version,
        },
    )


def run_mvp4_router_patch_active_slowtask_voice_e2e(
    *,
    audio_input: MVP4AudioInputMetadata | None = None,
) -> MVP4RouterOutcomeVoiceE2EResult:
    audio_input = audio_input or load_synthetic_wav_metadata(
        fixture_id="synthetic-router-patch-job-001",
        duration_ms=950,
        sample_rate_hz=16000,
        channel_count=1,
    )
    journal = _start_mvp4_router_outcome_journal(label="patch_slowtask")
    active_task_id = "task_mvp4_router_outcome_active"
    setup_turn = _emit_real_evidence_voice_turn(
        journal=journal,
        audio_input=audio_input,
        label="router_patch_setup_spawn",
        caused_by_event_id=str(journal.events()[-1]["event_id"]),
        created_monotonic_ms=6410,
        created_wall_clock_ms=1700000006410,
        router_context=RouterContext(task_focus_snapshot=TaskFocusSnapshot()),
        task_focus_hint="NEW_TASK_CANDIDATE",
        task_like=True,
        complexity_hint="complex",
        focus_confidence=0.9,
        evidence_uncertainty="low",
    )
    created = MockSlowTaskRuntime(journal).create_from_router_spawn(
        router_decision_event=setup_turn.router_decision_event,
        task_id=active_task_id,
        initial_goal_ref="goal://synthetic/mvp4/router-outcome/active",
        event_id_prefix="evt_mvp4_router_outcome_active_setup",
        created_monotonic_ms=6500,
        created_wall_clock_ms=1700000006500,
        source_evidence_refs=_voice_evidence_refs(setup_turn),
    )
    active_state = _append_active_slowtask_planning_state(
        journal=journal,
        created_event=created.produced_events[0],
        task_id=active_task_id,
        created_monotonic_ms=6502,
        created_wall_clock_ms=1700000006502,
    )
    active_focus = MVP1TaskFocusUpdateEmitter(journal).emit_update(
        router_decision_event=setup_turn.router_decision_event,
        event_id="evt_mvp4_router_outcome_active_focus_state",
        created_monotonic_ms=6504,
        created_wall_clock_ms=1700000006504,
        active_task_id=active_task_id,
        foreground_mode="SLOWTASK_ACTIVE",
        default_patch_policy="ACTIVE_TASK_PATCH_ONLY",
    )
    patch_turn = _emit_real_evidence_voice_turn(
        journal=journal,
        audio_input=audio_input,
        label="router_patch",
        caused_by_event_id=str(active_focus["event_id"]),
        created_monotonic_ms=6610,
        created_wall_clock_ms=1700000006610,
        router_context=RouterContext(
            task_focus_snapshot=TaskFocusSnapshot(
                active_task_id=active_task_id,
                lifecycle_phase=str(active_state["to_state"]),
                current_plan_version=created.plan_version,
            )
        ),
        task_focus_hint="ACTIVE_TASK_PATCH",
        task_like=False,
        complexity_hint="simple",
        focus_confidence=0.92,
        evidence_uncertainty="low",
    )
    next_task_event_seq = int(active_state["task_event_seq"]) + 1
    patch_result = UserPatchEvidencePackRuntime(journal).receive_patch_from_router_decision(
        router_decision_event=patch_turn.router_decision_event,
        turn_committed_event=patch_turn.turn_committed_event,
        asr_frame_event=patch_turn.asr_frame_event,
        thinker_frame_event=patch_turn.thinker_frame_event,
        task_id=active_task_id,
        current_plan_version=created.plan_version,
        next_task_event_seq=next_task_event_seq,
        patch_id="patch_mvp4_router_outcome_voice",
        event_id="evt_mvp4_router_outcome_voice_user_patch_received",
        evidence_ref="evidence://synthetic/mvp4/router-outcome/voice-patch",
        created_monotonic_ms=6670,
        created_wall_clock_ms=1700000006670,
        asr_nbest=(
            {
                "text_ref": patch_turn.asr_frame_event["text_ref"],
                "confidence": 0.81,
                "source_event_id": patch_turn.asr_frame_event["event_id"],
            },
        ),
        transcript_hint_ref=patch_turn.asr_frame_event["text_ref"],
        semantic_summary_ref=patch_turn.thinker_frame_event["semantic_summary_ref"],
        candidate_patch_types=("constraint_update_candidate",),
        patch_hint="voice_constraint_update_candidate",
    )
    response_summary = {
        "response_kind": "runtime_summary",
        "route": "PATCH_ACTIVE_SLOW_TASK",
        "source_event_id": patch_result.user_patch_event["event_id"],
        "response_text_ref": f"response-text://synthetic/mvp4/user-patch/{active_task_id}",
        "real_tts_used": False,
        "voice_output": "none",
    }
    return _router_outcome_result(
        audio_input=audio_input,
        journal=journal,
        turn=patch_turn,
        response_summary=response_summary,
        control_plane_summary={
            "route": "PATCH_ACTIVE_SLOW_TASK",
            "active_task_id": active_task_id,
            "plan_version": created.plan_version,
            "task_event_seq": next_task_event_seq,
        },
    )


def validate_provider_free_fixture_safety(fixture: Mapping[str, Any]) -> None:
    if not isinstance(fixture, Mapping):
        raise MVP4ArtifactSafetyError("MVP4 replay fixture must be a mapping")
    manifest = fixture.get("replay_manifest")
    if not isinstance(manifest, Mapping):
        raise MVP4ArtifactSafetyError("MVP4 replay fixture requires replay_manifest")
    if manifest.get("fixture_domain") != "GITHUB_ALLOWED":
        raise MVP4ArtifactSafetyError("MVP4 fixture_domain must be GITHUB_ALLOWED")
    if manifest.get("replay_mode") != "deterministic":
        raise MVP4ArtifactSafetyError("MVP4 replay_mode must be deterministic")
    if manifest.get("generated_from") not in {"synthetic", "redacted", "hand_written_minimal"}:
        raise MVP4ArtifactSafetyError("MVP4 fixture must be synthetic, redacted, or minimal")
    for flag in _MVP4_MANIFEST_FALSE_FLAGS:
        if manifest.get(flag) is not False:
            raise MVP4ArtifactSafetyError(f"{flag} must be false")

    events = fixture.get("events")
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes)):
        raise MVP4ArtifactSafetyError("MVP4 replay fixture events must be a sequence")

    for path, value in _iter_json_values(fixture):
        last_key = path[-1] if path else ""
        if path[:1] == ("replay_manifest",) and last_key in _MVP4_MANIFEST_FALSE_FLAGS:
            continue
        if last_key in _MVP4_ALLOWED_SAFE_FLAG_KEYS:
            if value is not False:
                raise MVP4ArtifactSafetyError(f"{last_key} must be false")
            continue
        if last_key in _MVP4_FORBIDDEN_KEYS:
            raise MVP4ArtifactSafetyError(f"{last_key} is not safe in MVP4 replay fixtures")
        if isinstance(value, bytes):
            raise MVP4ArtifactSafetyError("audio_bytes are not safe in MVP4 replay fixtures")
        if isinstance(value, str):
            _validate_safe_fixture_string(value)


def validate_mvp4_fixture_safety(fixture: Mapping[str, Any]) -> None:
    validate_provider_free_fixture_safety(fixture)


def _start_mvp4_router_outcome_journal(*, label: str) -> InMemoryEventJournal:
    startup = start_mvp0_session(
        session_id=f"sess_mvp4_router_outcome_{label}",
        conversation_id=f"conv_mvp4_router_outcome_{label}",
        runtime_config_ref=f"config://synthetic/mvp4/router-outcome/{label}",
        created_monotonic_ms=6000,
        created_wall_clock_ms=1700000006000,
    )
    return startup.journal


def _emit_real_evidence_voice_turn(
    *,
    journal: InMemoryEventJournal,
    audio_input: MVP4AudioInputMetadata,
    label: str,
    caused_by_event_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    router_context: RouterContext,
    task_focus_hint: str,
    task_like: bool,
    complexity_hint: str,
    focus_confidence: float,
    evidence_uncertainty: str,
) -> _TurnRuntimeResult:
    committed = _append_audio_turn(
        journal=journal,
        audio_input=audio_input,
        label=label,
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
    )
    asr_event = _emit_real_asr_transcript_event(
        journal=journal,
        turn_committed_event=committed,
        event_id=f"evt_mvp4_voice_e2e_{label}_real_asr",
        adapter_request_id=f"adapter_request_mvp4_{label}_asr",
        created_monotonic_ms=created_monotonic_ms + 40,
        created_wall_clock_ms=created_wall_clock_ms + 40,
        asr_frame_ref=f"asr-frame://synthetic/mvp4/{audio_input.fixture_id}/{label}",
        text_ref=f"text://synthetic/mvp4/{audio_input.fixture_id}/{label}",
    )
    thinker_event = _emit_real_thinker_semantic_event(
        journal=journal,
        turn_committed_event=committed,
        event_id=f"evt_mvp4_voice_e2e_{label}_real_thinker",
        adapter_request_id=f"adapter_request_mvp4_{label}_thinker",
        created_monotonic_ms=created_monotonic_ms + 41,
        created_wall_clock_ms=created_wall_clock_ms + 41,
        semantic_frame_ref=f"semantic-frame://synthetic/mvp4/{audio_input.fixture_id}/{label}",
        semantic_summary_ref=f"summary://synthetic/mvp4/{audio_input.fixture_id}/{label}",
        task_focus_hint=task_focus_hint,
        task_like=task_like,
        complexity_hint=complexity_hint,
        focus_confidence=focus_confidence,
        evidence_uncertainty=evidence_uncertainty,
    )
    router_result = MVP1Router(journal).emit_decision(
        turn_committed_event=committed,
        asr_frame_event=asr_event,
        thinker_frame_event=thinker_event,
        router_context=router_context,
        event_id=f"evt_mvp4_voice_e2e_{label}_router_decision",
        task_focus_state_event_id=f"evt_mvp4_voice_e2e_{label}_task_focus_state",
        created_monotonic_ms=created_monotonic_ms + 50,
        created_wall_clock_ms=created_wall_clock_ms + 50,
    )
    return _TurnRuntimeResult(
        turn_committed_event=committed,
        asr_frame_event=asr_event,
        thinker_frame_event=thinker_event,
        router_decision_event=router_result.router_decision_event,
        task_focus_state_event=router_result.task_focus_state_event,
    )


def _emit_real_asr_transcript_event(
    *,
    journal: InMemoryEventJournal,
    turn_committed_event: Mapping[str, Any],
    event_id: str,
    adapter_request_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    asr_frame_ref: str,
    text_ref: str,
) -> dict[str, Any]:
    return journal.append(
        event_name="ASR_TRANSCRIPT_OUTPUT_EMITTED",
        event_id=event_id,
        source_module="asr_adapter",
        caused_by_event_id=str(turn_committed_event["event_id"]),
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        trace_redaction_level="metadata_only",
        adapter_id="mvp4_synthetic_real_asr",
        adapter_type="asr",
        adapter_request_id=adapter_request_id,
        turn_id=str(turn_committed_event["turn_id"]),
        utterance_id=str(turn_committed_event["utterance_id"]),
        input_modality="audio",
        audio_span_id=str(turn_committed_event["audio_span_id"]),
        asr_frame_ref=asr_frame_ref,
        text_ref=text_ref,
        transcript_finality="final",
        timestamp_status="available",
        streaming_status="supported",
        output_mode="real",
    )


def _emit_real_thinker_semantic_event(
    *,
    journal: InMemoryEventJournal,
    turn_committed_event: Mapping[str, Any],
    event_id: str,
    adapter_request_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    semantic_frame_ref: str,
    semantic_summary_ref: str,
    task_focus_hint: str,
    task_like: bool,
    complexity_hint: str,
    focus_confidence: float,
    evidence_uncertainty: str,
) -> dict[str, Any]:
    audio_span_id = str(turn_committed_event["audio_span_id"])
    return journal.append(
        event_name="THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED",
        event_id=event_id,
        source_module="thinker_adapter",
        caused_by_event_id=str(turn_committed_event["event_id"]),
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        trace_redaction_level="metadata_only",
        adapter_id="mvp4_synthetic_real_thinker",
        adapter_type="thinker",
        adapter_request_id=adapter_request_id,
        turn_id=str(turn_committed_event["turn_id"]),
        utterance_id=str(turn_committed_event["utterance_id"]),
        input_modality=str(turn_committed_event["input_modality"]),
        audio_span_id=audio_span_id,
        semantic_frame_schema="voice_agent.semantic_frame.v1",
        normalization_status="normalized",
        semantic_frame_ref=semantic_frame_ref,
        semantic_summary_ref=semantic_summary_ref,
        semantic_close_status="available",
        assistant_directedness_status="available",
        emotion_status="available",
        audio_caption_status="available",
        semantic_close_ref=f"semantic-close://synthetic/mvp4/{audio_span_id}",
        assistant_directedness_ref=f"assistant-directedness://synthetic/mvp4/{audio_span_id}",
        emotion_ref=f"emotion://synthetic/mvp4/{audio_span_id}",
        audio_caption_ref=f"audio-caption://synthetic/mvp4/{audio_span_id}",
        output_mode="real",
        task_focus_hint=task_focus_hint,
        task_like=task_like,
        complexity_hint=complexity_hint,
        focus_confidence=focus_confidence,
        evidence_uncertainty=evidence_uncertainty,
    )


def _voice_evidence_refs(turn: _TurnRuntimeResult) -> tuple[str, str]:
    return (
        str(turn.asr_frame_event["asr_frame_ref"]),
        str(turn.thinker_frame_event["semantic_frame_ref"]),
    )


def _append_active_slowtask_planning_state(
    *,
    journal: InMemoryEventJournal,
    created_event: Mapping[str, Any],
    task_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
) -> dict[str, Any]:
    planning_started = journal.append(
        event_name="PLANNING_STARTED",
        event_id="evt_mvp4_router_outcome_active_planning_started",
        source_module="slowtask_runtime",
        caused_by_event_id=str(created_event["event_id"]),
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        trace_redaction_level="metadata_only",
        task_id=task_id,
        plan_version=1,
        task_event_seq=3,
        planning_reason="synthetic_mvp4_active_task_setup",
    )
    return journal.append(
        event_name="SLOWTASK_STATE_CHANGED",
        event_id="evt_mvp4_router_outcome_active_state_planning",
        source_module="slowtask_runtime",
        caused_by_event_id=str(planning_started["event_id"]),
        created_monotonic_ms=created_monotonic_ms + 1,
        created_wall_clock_ms=created_wall_clock_ms + 1,
        trace_redaction_level="metadata_only",
        task_id=task_id,
        plan_version=1,
        task_event_seq=4,
        from_state="CREATED",
        to_state="PLANNING",
        reason="synthetic_mvp4_active_task_setup",
    )


def _single_event_named(events: Sequence[Mapping[str, Any]], event_name: str) -> dict[str, Any]:
    matches = [event for event in events if event.get("event_name") == event_name]
    if len(matches) != 1:
        raise MVP4ArtifactSafetyError(f"expected exactly one {event_name} event")
    return deepcopy(dict(matches[0]))


def _router_outcome_result(
    *,
    audio_input: MVP4AudioInputMetadata,
    journal: InMemoryEventJournal,
    turn: _TurnRuntimeResult,
    response_summary: Mapping[str, Any],
    control_plane_summary: Mapping[str, Any],
) -> MVP4RouterOutcomeVoiceE2EResult:
    return MVP4RouterOutcomeVoiceE2EResult(
        audio_input=audio_input,
        events=tuple(journal.events()),
        turn_committed_event=deepcopy(turn.turn_committed_event),
        asr_frame_event=deepcopy(turn.asr_frame_event),
        thinker_frame_event=deepcopy(turn.thinker_frame_event),
        router_decision_event=deepcopy(turn.router_decision_event),
        task_focus_state_event=deepcopy(turn.task_focus_state_event),
        response_summary=deepcopy(dict(response_summary)),
        control_plane_summary=deepcopy(dict(control_plane_summary)),
    )


def _emit_voice_turn(
    *,
    journal: InMemoryEventJournal,
    audio_input: MVP4AudioInputMetadata,
    label: str,
    caused_by_event_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    router_context: RouterContext,
    task_focus_hint: str,
    task_like: bool,
    complexity_hint: str,
    focus_confidence: float,
    evidence_uncertainty: str,
) -> _TurnRuntimeResult:
    committed = _append_audio_turn(
        journal=journal,
        audio_input=audio_input,
        label=label,
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
    )
    asr_event = emit_mock_asr_frame(
        journal,
        committed,
        event_id=f"evt_mvp4_voice_e2e_{label}_mock_asr",
        created_monotonic_ms=created_monotonic_ms + 40,
        created_wall_clock_ms=created_wall_clock_ms + 40,
        asr_frame_ref=f"asr-frame://synthetic/mvp4/{audio_input.fixture_id}/{label}",
    )
    thinker_event = _emit_mock_thinker_frame(
        journal=journal,
        turn_committed_event=committed,
        event_id=f"evt_mvp4_voice_e2e_{label}_mock_thinker",
        created_monotonic_ms=created_monotonic_ms + 41,
        created_wall_clock_ms=created_wall_clock_ms + 41,
        semantic_frame_ref=f"semantic-frame://synthetic/mvp4/{audio_input.fixture_id}/{label}",
        task_focus_hint=task_focus_hint,
        task_like=task_like,
        complexity_hint=complexity_hint,
        focus_confidence=focus_confidence,
        evidence_uncertainty=evidence_uncertainty,
    )
    router_result = MVP1Router(journal).emit_decision(
        turn_committed_event=committed,
        asr_frame_event=asr_event,
        thinker_frame_event=thinker_event,
        router_context=router_context,
        event_id=f"evt_mvp4_voice_e2e_{label}_router_decision",
        task_focus_state_event_id=f"evt_mvp4_voice_e2e_{label}_task_focus_state",
        created_monotonic_ms=created_monotonic_ms + 50,
        created_wall_clock_ms=created_wall_clock_ms + 50,
    )
    return _TurnRuntimeResult(
        turn_committed_event=committed,
        asr_frame_event=asr_event,
        thinker_frame_event=thinker_event,
        router_decision_event=router_result.router_decision_event,
        task_focus_state_event=router_result.task_focus_state_event,
    )


def _append_audio_turn(
    *,
    journal: InMemoryEventJournal,
    audio_input: MVP4AudioInputMetadata,
    label: str,
    caused_by_event_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
) -> dict[str, Any]:
    audio_span_id = f"audio_mvp4_voice_e2e_{label}"
    span_started = journal.append(
        event_name="AUDIO_SPAN_STARTED",
        event_id=f"evt_mvp4_voice_e2e_{label}_audio_started",
        source_module="access_layer",
        caused_by_event_id=caused_by_event_id,
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        trace_redaction_level="metadata_only",
        audio_span_id=audio_span_id,
        input_modality="audio",
        audio_sample_offset=0,
        audio_format_ref=audio_input.audio_format_ref,
        audio_input_ref=audio_input.safe_audio_ref,
        duration_ms=audio_input.duration_ms,
        sample_rate_hz=audio_input.sample_rate_hz,
        channel_count=audio_input.channel_count,
        input_source=audio_input.input_source,
    )
    speech_start = journal.append(
        event_name="SPEECH_START_DETECTED",
        event_id=f"evt_mvp4_voice_e2e_{label}_speech_start",
        source_module="duplex_mock",
        caused_by_event_id=str(span_started["event_id"]),
        created_monotonic_ms=created_monotonic_ms + 1,
        created_wall_clock_ms=created_wall_clock_ms + 1,
        trace_redaction_level="metadata_only",
        audio_span_id=audio_span_id,
        audio_sample_offset=0,
        vad_confidence=0.99,
        detection_basis="mock_rule:metadata_only_speech_start",
    )
    turn_opened = journal.append(
        event_name="TURN_OPENED",
        event_id=f"evt_mvp4_voice_e2e_{label}_turn_opened",
        source_module="interaction_controller",
        caused_by_event_id=str(speech_start["event_id"]),
        created_monotonic_ms=created_monotonic_ms + 2,
        created_wall_clock_ms=created_wall_clock_ms + 2,
        trace_redaction_level="metadata_only",
        turn_id=f"turn_mvp4_voice_e2e_{label}",
        audio_span_id=audio_span_id,
        turn_phase="COLLECTING_INPUT",
        input_modality="audio",
    )
    span_ended = journal.append(
        event_name="AUDIO_SPAN_ENDED",
        event_id=f"evt_mvp4_voice_e2e_{label}_audio_ended",
        source_module="access_layer",
        caused_by_event_id=str(turn_opened["event_id"]),
        created_monotonic_ms=created_monotonic_ms + 20,
        created_wall_clock_ms=created_wall_clock_ms + 20,
        trace_redaction_level="metadata_only",
        audio_span_id=audio_span_id,
        audio_sample_offset=audio_input.frame_count,
        duration_ms=audio_input.duration_ms,
        end_reason="metadata_only_audio_complete",
    )
    speech_end = journal.append(
        event_name="SPEECH_END_DETECTED",
        event_id=f"evt_mvp4_voice_e2e_{label}_speech_end",
        source_module="duplex_mock",
        caused_by_event_id=str(span_ended["event_id"]),
        created_monotonic_ms=created_monotonic_ms + 21,
        created_wall_clock_ms=created_wall_clock_ms + 21,
        trace_redaction_level="metadata_only",
        audio_span_id=audio_span_id,
        audio_sample_offset=audio_input.frame_count,
        vad_confidence=0.98,
        silence_duration_ms=240,
        detection_basis="mock_rule:metadata_only_speech_end",
    )
    accepted = journal.append(
        event_name="TURN_INGRESS_ACCEPTED",
        event_id=f"evt_mvp4_voice_e2e_{label}_ingress_accepted",
        source_module="interaction_controller",
        caused_by_event_id=str(speech_end["event_id"]),
        created_monotonic_ms=created_monotonic_ms + 22,
        created_wall_clock_ms=created_wall_clock_ms + 22,
        trace_redaction_level="metadata_only",
        turn_id=f"turn_mvp4_voice_e2e_{label}",
        audio_span_id=audio_span_id,
        ingress_outcome="ACCEPTED",
        acceptance_basis="mock_rule:assumed_directed_and_closed",
    )
    return journal.append(
        event_name="TURN_INGRESS_COMMITTED",
        event_id=f"evt_mvp4_voice_e2e_{label}_ingress_committed",
        source_module="interaction_controller",
        caused_by_event_id=str(accepted["event_id"]),
        created_monotonic_ms=created_monotonic_ms + 23,
        created_wall_clock_ms=created_wall_clock_ms + 23,
        trace_redaction_level="metadata_only",
        turn_id=f"turn_mvp4_voice_e2e_{label}",
        utterance_id=f"utt_mvp4_voice_e2e_{label}",
        audio_span_id=audio_span_id,
        input_modality="audio",
        directedness="ASSUMED_DIRECTED",
        semantic_close="ASSUMED_CLOSED",
        ingress_outcome="COMMITTED",
        audio_input_ref=audio_input.safe_audio_ref,
    )


def _start_real_evidence_session(
    *,
    asr_approval_packet: Mapping[str, Any],
    asr_credential_env_var: str,
) -> tuple[Any, Any]:
    from voice_agent.adapters.asr_runtime_adapter import (
        ASR_RUNTIME_MODE_APPROVED_REAL_LIVE_EVAL,
        AsrRuntimeConfig,
        build_asr_runtime_capability_profile,
    )
    from voice_agent.adapters.lalm_thinker_profile import build_lalm_thinker_capability
    from voice_agent.runtime.asr_session_hook import (
        ASR_SESSION_ASR_MODE_APPROVED_REAL_LIVE_EVAL,
        AsrSessionAsrConfig,
    )

    asr_adapter_id = "mvp4_asr_audio_evidence"
    asr_runtime_config = AsrRuntimeConfig(
        mode=ASR_RUNTIME_MODE_APPROVED_REAL_LIVE_EVAL,
        adapter_id=asr_adapter_id,
        output_mode="real",
        credential_env_var=asr_credential_env_var,
        credential_ref="secret-ref://local/mvp4/asr/fake-transport",
        runtime_config_ref="config://synthetic/mvp4/asr/real-evidence-fake-transport",
        capability_snapshot_ref=MVP4_REAL_EVIDENCE_CAPABILITY_REF,
        capability_version=MVP4_REAL_EVIDENCE_CAPABILITY_VERSION,
    )
    asr_session_config = AsrSessionAsrConfig(
        mode=ASR_SESSION_ASR_MODE_APPROVED_REAL_LIVE_EVAL,
        adapter_id=asr_adapter_id,
        output_mode="real",
        credential_env_var=asr_credential_env_var,
        credential_ref="secret-ref://local/mvp4/asr/fake-transport",
        runtime_config_ref="config://synthetic/mvp4/asr/real-evidence-fake-transport",
        capability_snapshot_ref=MVP4_REAL_EVIDENCE_CAPABILITY_REF,
        capability_version=MVP4_REAL_EVIDENCE_CAPABILITY_VERSION,
    )
    startup = start_configured_session(
        session_id=MVP4_REAL_EVIDENCE_SESSION_ID,
        conversation_id=MVP4_REAL_EVIDENCE_CONVERSATION_ID,
        runtime_config_ref="config://synthetic/mvp4/real-evidence-fake-transport",
        created_monotonic_ms=5100,
        created_wall_clock_ms=1700000005100,
        assembly_config=RuntimeAdapterAssemblyConfig(
            stage="mvp0_mock",
            capability_snapshot_ref=MVP4_REAL_EVIDENCE_CAPABILITY_REF,
            capability_version=MVP4_REAL_EVIDENCE_CAPABILITY_VERSION,
        ),
        capabilities=(
            build_asr_runtime_capability_profile(
                asr_runtime_config,
                approval_packet=asr_approval_packet,
            ),
            build_lalm_thinker_capability(
                adapter_id="mvp4_lalm_thinker_audio_native",
                config_ref="config://synthetic/mvp4/lalm-thinker/audio-native-fake-transport",
            ),
        ),
    )
    return startup, asr_session_config


def _single_event_for_turn(
    events: Sequence[Mapping[str, Any]],
    *,
    event_name: str,
    turn_committed_event: Mapping[str, Any],
) -> dict[str, Any]:
    matches = [
        dict(event)
        for event in events
        if event.get("event_name") == event_name
        and event.get("caused_by_event_id") == turn_committed_event.get("event_id")
    ]
    if len(matches) != 1:
        raise MVP4ArtifactSafetyError(f"expected exactly one {event_name} for committed turn")
    return matches[0]


def _build_synthetic_wav_bytes(audio_input: MVP4AudioInputMetadata) -> bytes:
    buffer = io.BytesIO()
    bytes_per_frame = audio_input.channel_count * audio_input.sample_width_bytes
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(audio_input.channel_count)
        wav_file.setsampwidth(audio_input.sample_width_bytes)
        wav_file.setframerate(audio_input.sample_rate_hz)
        wav_file.writeframes(b"\x00" * audio_input.frame_count * bytes_per_frame)
    return buffer.getvalue()


def _emit_mock_thinker_frame(
    *,
    journal: InMemoryEventJournal,
    turn_committed_event: Mapping[str, Any],
    event_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    semantic_frame_ref: str,
    task_focus_hint: str,
    task_like: bool,
    complexity_hint: str,
    focus_confidence: float,
    evidence_uncertainty: str,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "turn_id": str(turn_committed_event["turn_id"]),
        "utterance_id": str(turn_committed_event["utterance_id"]),
        "input_modality": str(turn_committed_event["input_modality"]),
        "semantic_frame_ref": semantic_frame_ref,
        "output_mode": "mock",
        "task_focus_hint": task_focus_hint,
        "task_like": task_like,
        "complexity_hint": complexity_hint,
        "focus_confidence": focus_confidence,
        "evidence_uncertainty": evidence_uncertainty,
    }
    if turn_committed_event.get("audio_span_id") is not None:
        fields["audio_span_id"] = str(turn_committed_event["audio_span_id"])
    return journal.append(
        event_name="MOCK_THINKER_FRAME_EMITTED",
        event_id=event_id,
        source_module="mock_thinker_adapter",
        caused_by_event_id=str(turn_committed_event["event_id"]),
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        trace_redaction_level="metadata_only",
        **fields,
    )


def _append_minimal_active_slowtask(
    *,
    journal: InMemoryEventJournal,
    spawn_result: _TurnRuntimeResult,
    task_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
) -> dict[str, Any]:
    created = journal.append(
        event_name="SLOWTASK_CREATED",
        event_id="evt_mvp4_voice_e2e_spawn_slowtask_created",
        source_module="slowtask_runtime",
        caused_by_event_id=str(spawn_result.router_decision_event["event_id"]),
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        trace_redaction_level="metadata_only",
        task_id=task_id,
        plan_version=1,
        task_event_seq=1,
        initial_goal_ref="goal://synthetic/mvp4/provider-free-voice-e2e/spawn",
        source_evidence_refs=[
            str(spawn_result.asr_frame_event["asr_frame_ref"]),
            str(spawn_result.thinker_frame_event["semantic_frame_ref"]),
        ],
    )
    journal.append(
        event_name="SLOWTASK_STATE_CHANGED",
        event_id="evt_mvp4_voice_e2e_spawn_slowtask_created_state",
        source_module="slowtask_runtime",
        caused_by_event_id=str(created["event_id"]),
        created_monotonic_ms=created_monotonic_ms + 1,
        created_wall_clock_ms=created_wall_clock_ms + 1,
        trace_redaction_level="metadata_only",
        task_id=task_id,
        plan_version=1,
        task_event_seq=2,
        from_state="CREATED",
        to_state="CREATED",
        reason="created_snapshot",
    )
    planning = journal.append(
        event_name="PLANNING_STARTED",
        event_id="evt_mvp4_voice_e2e_spawn_planning_started",
        source_module="slowtask_runtime",
        caused_by_event_id=str(created["event_id"]),
        created_monotonic_ms=created_monotonic_ms + 2,
        created_wall_clock_ms=created_wall_clock_ms + 2,
        trace_redaction_level="metadata_only",
        task_id=task_id,
        plan_version=1,
        task_event_seq=3,
        planning_reason="synthetic_provider_free_spawn",
    )
    return journal.append(
        event_name="SLOWTASK_STATE_CHANGED",
        event_id="evt_mvp4_voice_e2e_spawn_slowtask_planning_state",
        source_module="slowtask_runtime",
        caused_by_event_id=str(planning["event_id"]),
        created_monotonic_ms=created_monotonic_ms + 3,
        created_wall_clock_ms=created_wall_clock_ms + 3,
        trace_redaction_level="metadata_only",
        task_id=task_id,
        plan_version=1,
        task_event_seq=4,
        from_state="CREATED",
        to_state="PLANNING",
        reason="synthetic_provider_free_spawn",
    )


def _audio_format_ref(
    source: str,
    fixture_id: str,
    sample_rate: int,
    channel_count: int,
    sample_width: int,
) -> str:
    channel_label = "mono" if channel_count == 1 else f"{channel_count}ch"
    return (
        f"audio-format://{source}/mvp4/{fixture_id}/"
        f"wav-pcm{sample_width * 8}-{channel_label}-{sample_rate}hz"
    )


def _positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _require_safe_token(value: object, field: str) -> str:
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{field} must be a non-empty string")
    lowered = value.lower()
    if any(marker in lowered for marker in ("bearer ", "api_key=", "authorization=", "token=", "data:")):
        raise ValueError(f"{field} must not contain unsafe content")
    return value


def _safe_slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-") or "unknown"


_MVP4_MANIFEST_FALSE_FLAGS = frozenset(
    {
        "contains_raw_audio",
        "contains_raw_trace",
        "contains_real_user_input",
        "contains_secrets",
        "contains_unredacted_tool_result",
        "contains_large_raw_web_content",
    }
)
_MVP4_ALLOWED_SAFE_FLAG_KEYS = frozenset(
    {
        "raw_audio_included",
        "raw_path_included",
        "data_uri_included",
    }
)
_MVP4_FORBIDDEN_KEYS = frozenset(
    {
        "raw_audio",
        "audio_bytes",
        "audio_payload",
        "raw_audio_bytes",
        "audio_base64",
        "raw_trace",
        "raw_transcript",
        "raw_text",
        "transcript_text",
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
        "prompt_dump",
        "raw_user_input",
        "authorization_header",
        "cookie",
        "credential",
        "token",
        "api_key",
    }
)
_MVP4_UNSAFE_STRING_TERMS = (
    "audio/raw/",
    "diagnostics/",
    "traces/",
    "replays/local/",
    "raw_audio",
    "raw trace",
    "raw_trace",
    "raw transcript",
    "raw_transcript",
    "provider_request",
    "provider_response",
    "provider_body",
    "provider_payload",
    "provider_schema",
    "api_key=",
    "authorization=",
    "credential=",
    "token=",
    "bearer ",
)


def _iter_json_values(value: object, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], object]]:
    values = [(path, value)]
    if isinstance(value, Mapping):
        for key, child in value.items():
            values.extend(_iter_json_values(child, (*path, str(key))))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, child in enumerate(value):
            values.extend(_iter_json_values(child, (*path, str(index))))
    return values


def _validate_safe_fixture_string(value: str) -> None:
    for view in _fixture_string_safety_views(value):
        lowered = view.lower()
        if lowered.startswith("data:"):
            raise MVP4ArtifactSafetyError("data URI is not safe in MVP4 replay fixtures")
        if lowered.startswith("file://"):
            raise MVP4ArtifactSafetyError("file:// refs are not safe in MVP4 replay fixtures")
        if lowered.startswith(("/", "~/", "\\")) or "/users/" in lowered or "\\users\\" in lowered:
            raise MVP4ArtifactSafetyError("absolute local paths are not safe in MVP4 replay fixtures")
        for term in _MVP4_UNSAFE_STRING_TERMS:
            if term in lowered:
                raise MVP4ArtifactSafetyError(f"{term} is not safe in MVP4 replay fixtures")


def _fixture_string_safety_views(value: str) -> tuple[str, ...]:
    views = [value]
    decoded = value
    for _ in range(3):
        next_decoded = unquote(decoded)
        if next_decoded == decoded:
            break
        views.append(next_decoded)
        decoded = next_decoded
    return tuple(views)
