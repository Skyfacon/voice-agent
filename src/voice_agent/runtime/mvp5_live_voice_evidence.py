from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import inspect
from pathlib import Path
from typing import Any

from voice_agent.adapters.asr_contract import AsrAdapterContract
from voice_agent.adapters.asr_fake_transport import AsrFakeTransportResult
from voice_agent.adapters.asr_normalization import AsrRequestBinding, emit_normalized_asr_candidate
from voice_agent.adapters.event_harness import FakeRealAdapterEventHarness
from voice_agent.adapters.lalm_thinker_binding import bind_lalm_thinker_request
from voice_agent.adapters.lalm_thinker_live_transport import (
    LALMThinkerCredentialHandle,
    LALMThinkerLiveTransportError,
)
from voice_agent.adapters.lalm_thinker_profile import (
    LALM_THINKER_RUNTIME_MODEL_ALIAS,
)
from voice_agent.adapters.lalm_thinker_runtime_adapter import (
    LALM_THINKER_RUNTIME_CREDENTIAL_REF,
)
from voice_agent.adapters.lalm_thinker_skeleton import (
    LALMThinkerCandidateValidationError,
    build_lalm_thinker_live_request_payload,
    emit_lalm_thinker_provider_text_result,
    emit_lalm_thinker_request_failed,
)
from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.runtime.adapter_callback_boundary import AdapterCallbackAppendBoundary
from voice_agent.runtime.mvp5_live_approval import (
    MVP5LiveProviderApprovalGrant,
    MVP5LiveProviderApprovalRequest,
    is_safe_mvp5_live_ref,
    validate_mvp5_live_provider_approval,
)
from voice_agent.runtime.mvp5_live_audio_input import load_local_wav_input


class MVP5LiveVoiceEvidenceError(ValueError):
    """Raised when the MVP-5 live evidence spine fails closed."""


@dataclass(frozen=True)
class MVP5LiveVoiceEvidenceConfig:
    run_id: str = "mvp5-live-voice-evidence-provider-free"
    live_provider: bool = False
    allow_local_wav: bool = False
    approval_packet: Mapping[str, Any] | None = None
    credential_env_var_name: str = "DASHSCOPE_API_KEY"
    requested_provider_calls: int = 0
    max_provider_calls: int = 0
    timeout_ms: int = 30_000
    asr_adapter_id: str = "mvp5_asr_adapter"
    thinker_adapter_id: str = "mvp5_thinker_adapter"
    session_id: str = "sess_mvp5_live_voice_evidence"
    conversation_id: str = "conv_mvp5_live_voice_evidence"
    runtime_config_ref: str = "config://mvp5/live-voice-evidence/provider-free"
    capability_snapshot_ref: str = "capability://mvp5/live-voice-evidence/provider-free"
    capability_version: str = "mvp5.live-voice-evidence.v1"


@dataclass(frozen=True)
class MVP5LiveVoiceEvidenceResult:
    run_id: str
    status: str
    events: tuple[dict[str, Any], ...] = ()
    turn_id: str | None = None
    utterance_id: str | None = None
    audio_span_id: str | None = None
    input_modality: str | None = None
    asr_event_id: str | None = None
    thinker_event_id: str | None = None
    asr_output_mode: str | None = None
    thinker_output_mode: str | None = None
    safe_refs: tuple[str, ...] = ()
    provider_call_used: bool = False
    fake_transport_used: bool = False
    local_wav_opt_in_used: bool = False
    live_provider_approval_used: bool = False
    failure_reasons: tuple[str, ...] = field(default_factory=tuple)

    def to_metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "run_id": self.run_id,
            "status": self.status,
            "event_names": [str(event["event_name"]) for event in self.events],
            "event_ids": [str(event["event_id"]) for event in self.events],
            "provider_call_used": self.provider_call_used,
            "fake_transport_used": self.fake_transport_used,
            "local_wav_opt_in_used": self.local_wav_opt_in_used,
            "live_provider_approval_used": self.live_provider_approval_used,
            "raw_audio_included": False,
            "raw_transcript_included": False,
            "raw_provider_body_included": False,
            "prompt_dump_included": False,
            "secret_included": False,
            "local_wav_path_included": False,
            "replay_reruns_provider": False,
            "real_tts_used": False,
            "voice_output": "none",
        }
        optional_fields = {
            "turn_id": self.turn_id,
            "utterance_id": self.utterance_id,
            "audio_span_id": self.audio_span_id,
            "input_modality": self.input_modality,
            "asr_event_id": self.asr_event_id,
            "thinker_event_id": self.thinker_event_id,
            "asr_output_mode": self.asr_output_mode,
            "thinker_output_mode": self.thinker_output_mode,
        }
        metadata.update({key: value for key, value in optional_fields.items() if value is not None})
        if self.safe_refs:
            metadata["safe_refs"] = list(self.safe_refs)
        if self.failure_reasons:
            metadata["failure_reasons"] = list(self.failure_reasons)
        _validate_summary_metadata(metadata)
        return metadata


def run_mvp5_live_voice_evidence(
    *,
    local_wav: str | Path,
    config: MVP5LiveVoiceEvidenceConfig | None = None,
    env: Mapping[str, str] | None = None,
    asr_transport: object | None = None,
    thinker_transport: object | None = None,
) -> MVP5LiveVoiceEvidenceResult:
    config = config or MVP5LiveVoiceEvidenceConfig()
    run_id = _require_safe_token(config.run_id, "run_id")

    if not config.live_provider:
        return MVP5LiveVoiceEvidenceResult(
            run_id=run_id,
            status="provider_free_skipped",
        )

    loaded_audio = load_local_wav_input(local_wav, allow_local_wav=config.allow_local_wav)
    grant = validate_mvp5_live_provider_approval(
        MVP5LiveProviderApprovalRequest(
            live_provider=config.live_provider,
            approval_packet=config.approval_packet,
            credential_env_var_name=config.credential_env_var_name,
            requested_provider_calls=config.requested_provider_calls,
            max_provider_calls=config.max_provider_calls,
            timeout_ms=config.timeout_ms,
            allow_local_wav=config.allow_local_wav,
            metadata_only_output=True,
            provider_adapter_ids=(config.asr_adapter_id, config.thinker_adapter_id),
            safe_refs=(loaded_audio.safe_audio_ref,),
        ),
        env={} if env is None else env,
    )

    if asr_transport is None or thinker_transport is None:
        return MVP5LiveVoiceEvidenceResult(
            run_id=run_id,
            status="blocked_missing_fake_transport",
            provider_call_used=False,
            fake_transport_used=False,
            local_wav_opt_in_used=True,
            live_provider_approval_used=True,
            safe_refs=(loaded_audio.safe_audio_ref,),
            failure_reasons=("fake_transport_required_for_provider_free_goal2_default",),
        )

    journal = _build_journal(config)
    turn_committed_event = _append_committed_audio_turn(
        journal,
        config=config,
        run_id=run_id,
        audio_metadata=loaded_audio.to_metadata(),
    )
    audio_bytes = loaded_audio.audio_handle.open_bytes().read()
    boundary = AdapterCallbackAppendBoundary(journal)

    asr_event = _run_asr_adapter_fake_transport(
        boundary=boundary,
        config=config,
        turn_committed_event=turn_committed_event,
        asr_transport=asr_transport,
        run_id=run_id,
        created_monotonic_ms=300,
        created_wall_clock_ms=1700000000300,
    )
    thinker_event = _run_thinker_audio_native_transport(
        boundary=boundary,
        config=config,
        turn_committed_event=turn_committed_event,
        thinker_transport=thinker_transport,
        grant=grant,
        env={} if env is None else env,
        audio_bytes=audio_bytes,
        run_id=run_id,
        created_monotonic_ms=400,
        created_wall_clock_ms=1700000000400,
    )

    events = tuple(journal.events())
    safe_refs = _collect_safe_refs(
        events,
        extra_refs=(loaded_audio.safe_audio_ref, *grant.safe_refs),
    )
    asr_output_mode = str(asr_event["output_mode"]) if asr_event is not None else None
    thinker_output_mode = str(thinker_event["output_mode"]) if thinker_event is not None else None
    return MVP5LiveVoiceEvidenceResult(
        run_id=run_id,
        status=_result_status(asr_output_mode, thinker_output_mode),
        events=events,
        turn_id=str(turn_committed_event["turn_id"]),
        utterance_id=str(turn_committed_event["utterance_id"]),
        audio_span_id=str(turn_committed_event["audio_span_id"]),
        input_modality=str(turn_committed_event["input_modality"]),
        asr_event_id=str(asr_event["event_id"]) if asr_event is not None else None,
        thinker_event_id=str(thinker_event["event_id"]) if thinker_event is not None else None,
        asr_output_mode=asr_output_mode,
        thinker_output_mode=thinker_output_mode,
        safe_refs=safe_refs,
        provider_call_used=False,
        fake_transport_used=True,
        local_wav_opt_in_used=True,
        live_provider_approval_used=True,
        failure_reasons=()
        if asr_event is not None and thinker_event is not None
        else ("adapter_evidence_incomplete",),
    )


def _build_journal(config: MVP5LiveVoiceEvidenceConfig) -> InMemoryEventJournal:
    journal = InMemoryEventJournal(
        session_id=_require_safe_token(config.session_id, "session_id"),
        conversation_id=_require_safe_token(config.conversation_id, "conversation_id"),
    )
    session_started = journal.append(
        event_name="SESSION_STARTED",
        event_id="evt_mvp5_live_voice_evidence_session_started",
        source_module="session_runtime",
        created_monotonic_ms=100,
        created_wall_clock_ms=1700000000100,
        trace_redaction_level="metadata_only",
        runtime_config_ref=_require_safe_ref(config.runtime_config_ref, "runtime_config_ref"),
        capability_snapshot_ref=_require_safe_ref(
            config.capability_snapshot_ref,
            "capability_snapshot_ref",
        ),
    )
    journal.append(
        event_name="ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
        event_id="evt_mvp5_live_voice_evidence_capability_snapshot",
        source_module="adapter_registry",
        caused_by_event_id=str(session_started["event_id"]),
        created_monotonic_ms=101,
        created_wall_clock_ms=1700000000101,
        trace_redaction_level="metadata_only",
        capability_snapshot_ref=_require_safe_ref(
            config.capability_snapshot_ref,
            "capability_snapshot_ref",
        ),
        adapter_ids=[config.asr_adapter_id, config.thinker_adapter_id],
        adapter_types=["asr", "thinker"],
        deployment_modes=["provider_free_fake_transport", "provider_free_fake_transport"],
        output_modes=["real", "degraded"],
        capability_version=_require_safe_token(config.capability_version, "capability_version"),
    )
    return journal


def _append_committed_audio_turn(
    journal: InMemoryEventJournal,
    *,
    config: MVP5LiveVoiceEvidenceConfig,
    run_id: str,
    audio_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    slug = _slug(run_id)
    audio_span_id = f"audio_mvp5_live_evidence_{slug}"
    turn_id = f"turn_mvp5_live_evidence_{slug}"
    utterance_id = f"utt_mvp5_live_evidence_{slug}"
    started = journal.append(
        event_name="AUDIO_SPAN_STARTED",
        event_id=f"evt_mvp5_live_evidence_{slug}_audio_started",
        source_module="access_layer",
        caused_by_event_id="evt_mvp5_live_voice_evidence_capability_snapshot",
        created_monotonic_ms=110,
        created_wall_clock_ms=1700000000110,
        trace_redaction_level="metadata_only",
        audio_span_id=audio_span_id,
        input_modality="audio",
        audio_sample_offset=0,
        audio_format_ref="audio-format://mvp5/live-voice-evidence/wav",
    )
    speech_started = journal.append(
        event_name="SPEECH_START_DETECTED",
        event_id=f"evt_mvp5_live_evidence_{slug}_speech_started",
        source_module="duplex",
        caused_by_event_id=str(started["event_id"]),
        created_monotonic_ms=120,
        created_wall_clock_ms=1700000000120,
        trace_redaction_level="metadata_only",
        audio_span_id=audio_span_id,
        audio_sample_offset=0,
        vad_confidence=0.99,
    )
    journal.append(
        event_name="TURN_OPENED",
        event_id=f"evt_mvp5_live_evidence_{slug}_turn_opened",
        source_module="interaction_controller",
        caused_by_event_id=str(speech_started["event_id"]),
        created_monotonic_ms=130,
        created_wall_clock_ms=1700000000130,
        trace_redaction_level="metadata_only",
        turn_id=turn_id,
        audio_span_id=audio_span_id,
        input_modality="audio",
        turn_phase="COLLECTING_INPUT",
    )
    ended = journal.append(
        event_name="AUDIO_SPAN_ENDED",
        event_id=f"evt_mvp5_live_evidence_{slug}_audio_ended",
        source_module="access_layer",
        caused_by_event_id=str(started["event_id"]),
        created_monotonic_ms=160,
        created_wall_clock_ms=1700000000160,
        trace_redaction_level="metadata_only",
        audio_span_id=audio_span_id,
        audio_sample_offset=int(audio_metadata["frame_count"]),
        duration_ms=int(audio_metadata["duration_ms"]),
        end_reason="local_wav_opt_in_complete",
    )
    speech_ended = journal.append(
        event_name="SPEECH_END_DETECTED",
        event_id=f"evt_mvp5_live_evidence_{slug}_speech_ended",
        source_module="duplex",
        caused_by_event_id=str(ended["event_id"]),
        created_monotonic_ms=170,
        created_wall_clock_ms=1700000000170,
        trace_redaction_level="metadata_only",
        audio_span_id=audio_span_id,
        audio_sample_offset=int(audio_metadata["frame_count"]),
        vad_confidence=0.99,
        silence_duration_ms=520,
    )
    accepted = journal.append(
        event_name="TURN_INGRESS_ACCEPTED",
        event_id=f"evt_mvp5_live_evidence_{slug}_ingress_accepted",
        source_module="interaction_controller",
        caused_by_event_id=str(speech_ended["event_id"]),
        created_monotonic_ms=180,
        created_wall_clock_ms=1700000000180,
        trace_redaction_level="metadata_only",
        turn_id=turn_id,
        audio_span_id=audio_span_id,
        ingress_outcome="ACCEPTED",
    )
    return journal.append(
        event_name="TURN_INGRESS_COMMITTED",
        event_id=f"evt_mvp5_live_evidence_{slug}_ingress_committed",
        source_module="interaction_controller",
        caused_by_event_id=str(accepted["event_id"]),
        created_monotonic_ms=190,
        created_wall_clock_ms=1700000000190,
        trace_redaction_level="metadata_only",
        turn_id=turn_id,
        utterance_id=utterance_id,
        audio_span_id=audio_span_id,
        input_modality="audio",
        directedness="ASSUMED_DIRECTED",
        semantic_close="ASSUMED_CLOSED",
        ingress_outcome="COMMITTED",
    )


def _run_asr_adapter_fake_transport(
    *,
    boundary: AdapterCallbackAppendBoundary,
    config: MVP5LiveVoiceEvidenceConfig,
    turn_committed_event: Mapping[str, Any],
    asr_transport: object,
    run_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
) -> dict[str, Any] | None:
    binding = AsrRequestBinding.from_turn_committed_event(
        turn_committed_event,
        adapter_request_id=f"adapter-request-mvp5-asr-{_slug(run_id)}",
    )
    transcribe = getattr(asr_transport, "transcribe", None)
    if not callable(transcribe):
        raise MVP5LiveVoiceEvidenceError("ASR fake transport must provide transcribe")
    result = _call_fake_asr_transport(transcribe, binding)
    if not isinstance(result, AsrFakeTransportResult):
        raise MVP5LiveVoiceEvidenceError("ASR fake transport returned unsupported result")

    event_base = f"evt_mvp5_live_evidence_{_slug(run_id)}_asr"
    if result.candidate is not None:
        contract = AsrAdapterContract(
            boundary=boundary,
            adapter_id=config.asr_adapter_id,
            output_mode=result.candidate.output_mode,
            source_module="mvp5_asr_adapter",
        )
        emission = emit_normalized_asr_candidate(
            contract=contract,
            candidate=result.candidate,
            turn_committed_event=turn_committed_event,
            event_id=f"{event_base}_transcript",
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
        )
        return emission.transcript_event
    if result.validation_failure_metadata is not None:
        metadata = result.validation_failure_metadata
        _adapter_harness(
            boundary=boundary,
            adapter_id=config.asr_adapter_id,
            adapter_type="asr",
            output_mode=str(metadata.get("output_mode", "degraded")),
            source_module="mvp5_asr_adapter",
        ).emit_output_validation_failed(
            event_id=f"{event_base}_validation_failed",
            caused_by_event_id=str(turn_committed_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            adapter_request_id=str(metadata["adapter_request_id"]),
            schema_name=str(metadata["schema_name"]),
            failure_reasons=tuple(str(reason) for reason in metadata["failure_reasons"]),
        )
    elif result.request_failure_metadata is not None:
        metadata = result.request_failure_metadata
        _adapter_harness(
            boundary=boundary,
            adapter_id=config.asr_adapter_id,
            adapter_type="asr",
            output_mode=str(metadata.get("output_mode", "degraded")),
            source_module="mvp5_asr_adapter",
        ).emit_request_failed(
            event_id=f"{event_base}_request_failed",
            caused_by_event_id=str(turn_committed_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            adapter_request_id=str(metadata["adapter_request_id"]),
            failure_reason=str(metadata["failure_reason"]),
            retryable=bool(metadata["retryable"]),
            timeout_ms=metadata.get("timeout_ms"),
        )
    return None


def _run_thinker_audio_native_transport(
    *,
    boundary: AdapterCallbackAppendBoundary,
    config: MVP5LiveVoiceEvidenceConfig,
    turn_committed_event: Mapping[str, Any],
    thinker_transport: object,
    grant: MVP5LiveProviderApprovalGrant,
    env: Mapping[str, str],
    audio_bytes: bytes,
    run_id: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
) -> dict[str, Any] | None:
    event_slug = _slug(run_id)
    adapter_request_id = f"adapter-request-mvp5-thinker-{event_slug}"
    binding = bind_lalm_thinker_request(
        turn_committed_event=turn_committed_event,
        adapter_request_id=adapter_request_id,
        request_metadata_ref=f"request-metadata://mvp5/live-voice-evidence/{event_slug}",
        input_ref=f"audio://mvp5/live-voice-evidence/{event_slug}",
        policy_ref="policy://mvp5/live-voice-evidence/evidence-only",
        expected_turn_committed_event_id=str(turn_committed_event["event_id"]),
    )
    credential_value = env.get(grant.credential_env_var_name)
    if credential_value is None or credential_value == "":
        request_failed = emit_lalm_thinker_request_failed(
            boundary=boundary,
            event_id=f"evt_mvp5_live_evidence_{event_slug}_thinker_request_failed",
            caused_by_event_id=str(turn_committed_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            adapter_request_id=adapter_request_id,
            failure_reason="credential_missing",
            retryable=False,
            timeout_ms=grant.timeout_ms,
            adapter_id=config.thinker_adapter_id,
        )
        return None if request_failed else None

    complete_audio = getattr(thinker_transport, "complete_audio", None)
    if not callable(complete_audio):
        raise MVP5LiveVoiceEvidenceError("Thinker fake transport must provide complete_audio")
    try:
        provider_text = complete_audio(
            request_payload=build_lalm_thinker_live_request_payload(binding=binding),
            audio_bytes=audio_bytes,
            audio_format="wav",
            credential_handle=LALMThinkerCredentialHandle(
                credential_ref=LALM_THINKER_RUNTIME_CREDENTIAL_REF,
            ),
            credential_value=credential_value,
            adapter_request_id=adapter_request_id,
            timeout_ms=grant.timeout_ms,
            model_alias=LALM_THINKER_RUNTIME_MODEL_ALIAS,
        )
    except LALMThinkerLiveTransportError as exc:
        emit_lalm_thinker_request_failed(
            boundary=boundary,
            event_id=f"evt_mvp5_live_evidence_{event_slug}_thinker_request_failed",
            caused_by_event_id=str(turn_committed_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            adapter_request_id=adapter_request_id,
            failure_reason=exc.category,
            retryable=False,
            timeout_ms=grant.timeout_ms,
            adapter_id=config.thinker_adapter_id,
        )
        return None

    try:
        result = emit_lalm_thinker_provider_text_result(
            boundary=boundary,
            adapter_id=config.thinker_adapter_id,
            provider_text=provider_text,
            expected_binding=binding,
            success_event_id=f"evt_mvp5_live_evidence_{event_slug}_thinker_semantic_frame",
            validation_failed_event_id=f"evt_mvp5_live_evidence_{event_slug}_thinker_validation_failed",
            caused_by_event_id=str(turn_committed_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            turn_committed_event=turn_committed_event,
        )
    except LALMThinkerCandidateValidationError:
        return None
    if result.thinker_emission is not None:
        return result.thinker_emission.thinker_event
    return None


def _call_fake_asr_transport(transcribe: object, binding: AsrRequestBinding) -> object:
    signature = inspect.signature(transcribe)
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()):
        return transcribe(binding=binding)
    if "binding" in signature.parameters:
        return transcribe(binding=binding)
    return transcribe(binding)


def _adapter_harness(
    *,
    boundary: AdapterCallbackAppendBoundary,
    adapter_id: str,
    adapter_type: str,
    output_mode: str,
    source_module: str,
) -> FakeRealAdapterEventHarness:
    return FakeRealAdapterEventHarness(
        boundary=boundary,
        adapter_id=adapter_id,
        adapter_type=adapter_type,
        output_mode=output_mode,
        source_module=source_module,
    )


def _collect_safe_refs(
    events: tuple[dict[str, Any], ...],
    *,
    extra_refs: tuple[str, ...],
) -> tuple[str, ...]:
    refs: list[str] = []
    for ref in extra_refs:
        _append_safe_ref(refs, ref)
    for event in events:
        for key, value in event.items():
            if key.endswith("_ref") and isinstance(value, str):
                _append_safe_ref(refs, value)
    return tuple(dict.fromkeys(refs))


def _append_safe_ref(refs: list[str], ref: str) -> None:
    if not is_safe_mvp5_live_ref(ref):
        raise MVP5LiveVoiceEvidenceError(f"unsafe ref in MVP-5 live evidence summary: {ref!r}")
    refs.append(ref)


def _result_status(asr_output_mode: str | None, thinker_output_mode: str | None) -> str:
    if asr_output_mode is None or thinker_output_mode is None:
        return "evidence_failed"
    if "degraded" in {asr_output_mode, thinker_output_mode}:
        return "degraded_evidence_emitted"
    return "evidence_emitted"


def _validate_summary_metadata(metadata: Mapping[str, Any]) -> None:
    forbidden_true_flags = (
        "raw_audio_included",
        "raw_transcript_included",
        "raw_provider_body_included",
        "prompt_dump_included",
        "secret_included",
        "local_wav_path_included",
        "replay_reruns_provider",
    )
    for flag in forbidden_true_flags:
        if metadata.get(flag) is not False:
            raise MVP5LiveVoiceEvidenceError(f"{flag} must be false in MVP-5 evidence summary")
    _reject_unsafe_summary_values(metadata)


def _reject_unsafe_summary_values(value: Any) -> None:
    if isinstance(value, bytes):
        raise MVP5LiveVoiceEvidenceError("raw bytes are not allowed in MVP-5 evidence summary")
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
            )
        ):
            raise MVP5LiveVoiceEvidenceError(
                "unsafe string marker is not allowed in MVP-5 evidence summary"
            )
        if value.startswith("/") or value.startswith("~"):
            raise MVP5LiveVoiceEvidenceError(
                "local paths are not allowed in MVP-5 evidence summary"
            )
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
                raise MVP5LiveVoiceEvidenceError(
                    "unsafe summary key is not allowed in MVP-5 evidence summary"
                )
            _reject_unsafe_summary_values(child_value)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_unsafe_summary_values(item)


def _require_safe_ref(value: object, field: str) -> str:
    token = _require_safe_token(value, field)
    if "://" not in token:
        raise MVP5LiveVoiceEvidenceError(f"{field} must be a safe ref")
    if not is_safe_mvp5_live_ref(token):
        raise MVP5LiveVoiceEvidenceError(f"{field} must be safe MVP-5 metadata")
    return token


def _require_safe_token(value: object, field: str) -> str:
    if not isinstance(value, str) or value == "":
        raise MVP5LiveVoiceEvidenceError(f"{field} must be a non-empty string")
    if any(marker in value.lower() for marker in ("api_key=", "authorization=", "token=", "bearer ")):
        raise MVP5LiveVoiceEvidenceError(f"{field} must not contain credential-like content")
    if value.startswith("/") or value.startswith("~"):
        raise MVP5LiveVoiceEvidenceError(f"{field} must not be a local path")
    return value


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-") or "unknown"
