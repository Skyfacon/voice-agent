from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import importlib
import inspect
from pathlib import Path
import time
from typing import Any, Callable

from voice_agent.adapters.asr_contract import AsrAdapterContract
from voice_agent.adapters.asr_fake_transport import AsrFakeTransportResult
from voice_agent.adapters.asr_normalization import AsrRequestBinding, emit_normalized_asr_candidate
from voice_agent.adapters.asr_normalization import normalize_asr_candidate
from voice_agent.adapters.event_harness import FakeRealAdapterEventHarness
from voice_agent.adapters.lalm_thinker_binding import bind_lalm_thinker_request
from voice_agent.adapters.lalm_thinker_live_transport import (
    LALMThinkerCredentialHandle,
    LALMThinkerLiveDirectHTTPTransport,
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
    thinker_transient_asr_text_used: bool = False
    latency_debug: Mapping[str, Any] = field(default_factory=dict)
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
            "thinker_transient_asr_text_used": self.thinker_transient_asr_text_used,
            "latency_debug": _normalize_latency_debug(self.latency_debug),
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


@dataclass(frozen=True)
class _TimedProviderCallResult:
    value: object | None
    error: BaseException | None
    started_monotonic_ms: int
    finished_monotonic_ms: int
    elapsed_ms: int


class _AdapterCredentialMissingError(ValueError):
    pass


_LATENCY_MS_FIELDS = (
    "total_server_ms",
    "wav_validate_ms",
    "temp_wav_write_ms",
    "local_audio_gate_ms",
    "approval_gate_ms",
    "asr_provider_http_ms",
    "asr_normalize_emit_ms",
    "thinker_provider_http_ms",
    "thinker_parse_validate_emit_ms",
    "router_ms",
    "qa_history_ms",
)
_LATENCY_BOOL_FIELDS = (
    "provider_calls_parallel",
    "asr_started_before_thinker_finished",
    "thinker_started_before_asr_finished",
)


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

    latency_debug: dict[str, Any] = _normalize_latency_debug({})
    local_audio_gate_started = time.monotonic()
    loaded_audio = load_local_wav_input(local_wav, allow_local_wav=config.allow_local_wav)
    latency_debug["local_audio_gate_ms"] = _elapsed_ms(local_audio_gate_started)

    approval_gate_started = time.monotonic()
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
    latency_debug["approval_gate_ms"] = _elapsed_ms(approval_gate_started)

    injected_transport_used = asr_transport is not None or thinker_transport is not None
    if asr_transport is None:
        asr_transport = _default_asr_live_transport()
    if thinker_transport is None:
        thinker_transport = LALMThinkerLiveDirectHTTPTransport()

    journal = _build_journal(config)
    turn_committed_event = _append_committed_audio_turn(
        journal,
        config=config,
        run_id=run_id,
        audio_metadata=loaded_audio.to_metadata(),
    )
    audio_bytes = loaded_audio.audio_handle.open_bytes().read()
    boundary = AdapterCallbackAppendBoundary(journal)

    env_map = {} if env is None else env
    asr_binding = AsrRequestBinding.from_turn_committed_event(
        turn_committed_event,
        adapter_request_id=f"adapter-request-mvp5-asr-{_slug(run_id)}",
    )
    asr_event_base = f"evt_mvp5_live_evidence_{_slug(run_id)}_asr"
    thinker_binding = _build_thinker_audio_native_binding(
        turn_committed_event=turn_committed_event,
        run_id=run_id,
    )
    thinker_event_slug = _slug(run_id)

    asr_call = lambda: _call_asr_adapter_transport_provider(
        config=config,
        asr_transport=asr_transport,
        grant=grant,
        env=env_map,
        binding=asr_binding,
        audio_bytes=audio_bytes,
        audio_mime_type=loaded_audio.audio_handle.audio_mime_type,
    )
    thinker_call = lambda: _call_thinker_audio_native_provider(
        thinker_transport=thinker_transport,
        grant=grant,
        env=env_map,
        binding=thinker_binding,
        audio_bytes=audio_bytes,
    )
    asr_provider_result, thinker_provider_result = _run_provider_calls_in_parallel(
        asr_call=asr_call,
        thinker_call=thinker_call,
    )
    asr_started_before_thinker_finished = (
        asr_provider_result.started_monotonic_ms <= thinker_provider_result.finished_monotonic_ms
    )
    thinker_started_before_asr_finished = (
        thinker_provider_result.started_monotonic_ms <= asr_provider_result.finished_monotonic_ms
    )
    latency_debug.update(
        {
            "asr_provider_http_ms": asr_provider_result.elapsed_ms,
            "thinker_provider_http_ms": thinker_provider_result.elapsed_ms,
            "provider_calls_parallel": (
                asr_started_before_thinker_finished and thinker_started_before_asr_finished
            ),
            "asr_started_before_thinker_finished": asr_started_before_thinker_finished,
            "thinker_started_before_asr_finished": thinker_started_before_asr_finished,
        }
    )

    asr_emit_started = time.monotonic()
    asr_event = _emit_asr_adapter_transport_outcome(
        boundary=boundary,
        config=config,
        turn_committed_event=turn_committed_event,
        outcome=asr_provider_result,
        binding=asr_binding,
        event_base=asr_event_base,
        grant=grant,
        created_monotonic_ms=300,
        created_wall_clock_ms=1700000000300,
    )
    latency_debug["asr_normalize_emit_ms"] = _elapsed_ms(asr_emit_started)

    thinker_emit_started = time.monotonic()
    thinker_event = _emit_thinker_audio_native_outcome(
        boundary=boundary,
        config=config,
        turn_committed_event=turn_committed_event,
        outcome=thinker_provider_result,
        binding=thinker_binding,
        event_slug=thinker_event_slug,
        grant=grant,
        created_monotonic_ms=400,
        created_wall_clock_ms=1700000000400,
    )
    latency_debug["thinker_parse_validate_emit_ms"] = _elapsed_ms(thinker_emit_started)

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
        provider_call_used=not injected_transport_used,
        fake_transport_used=injected_transport_used,
        local_wav_opt_in_used=True,
        live_provider_approval_used=True,
        thinker_transient_asr_text_used=False,
        latency_debug=latency_debug,
        failure_reasons=()
        if asr_event is not None and thinker_event is not None
        else _failure_reasons_from_events(events),
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


def _run_provider_calls_in_parallel(
    *,
    asr_call: Callable[[], object],
    thinker_call: Callable[[], object],
) -> tuple[_TimedProviderCallResult, _TimedProviderCallResult]:
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="mvp5-provider-call") as executor:
        asr_future = executor.submit(_timed_provider_call, asr_call)
        thinker_future = executor.submit(_timed_provider_call, thinker_call)
        return asr_future.result(), thinker_future.result()


def _timed_provider_call(call: Callable[[], object]) -> _TimedProviderCallResult:
    started_monotonic_ms = _monotonic_ms()
    started = time.monotonic()
    try:
        value = call()
    except BaseException as exc:  # Returned to the main thread for deterministic event emission.
        return _TimedProviderCallResult(
            value=None,
            error=exc,
            started_monotonic_ms=started_monotonic_ms,
            finished_monotonic_ms=_monotonic_ms(),
            elapsed_ms=_elapsed_ms(started),
        )
    return _TimedProviderCallResult(
        value=value,
        error=None,
        started_monotonic_ms=started_monotonic_ms,
        finished_monotonic_ms=_monotonic_ms(),
        elapsed_ms=_elapsed_ms(started),
    )


def _call_asr_adapter_transport_provider(
    *,
    config: MVP5LiveVoiceEvidenceConfig,
    asr_transport: object,
    grant: MVP5LiveProviderApprovalGrant,
    env: Mapping[str, str],
    binding: AsrRequestBinding,
    audio_bytes: bytes,
    audio_mime_type: str,
) -> object:
    transcribe = getattr(asr_transport, "transcribe", None)
    if not callable(transcribe):
        raise MVP5LiveVoiceEvidenceError("ASR transport must provide transcribe")

    result = _maybe_call_fake_asr_transport(transcribe, binding)
    if isinstance(result, AsrFakeTransportResult):
        return result

    credential_value = env.get(grant.credential_env_var_name)
    if credential_value is None or credential_value == "":
        raise _AdapterCredentialMissingError("credential_missing")

    return transcribe(
        audio_payload=audio_bytes,
        audio_mime_type=audio_mime_type,
        credential_handle=_asr_live_credential_handle(
            credential_ref="secret-ref://local/asr-live-eval/dashscope",
        ),
        credential_value=credential_value,
        adapter_request_id=binding.adapter_request_id,
        timeout_ms=grant.timeout_ms,
        model_alias=_asr_live_selected_model_alias(),
    )


def _emit_asr_adapter_transport_outcome(
    *,
    boundary: AdapterCallbackAppendBoundary,
    config: MVP5LiveVoiceEvidenceConfig,
    turn_committed_event: Mapping[str, Any],
    outcome: _TimedProviderCallResult,
    binding: AsrRequestBinding,
    event_base: str,
    grant: MVP5LiveProviderApprovalGrant,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
) -> dict[str, Any] | None:
    if isinstance(outcome.error, _AdapterCredentialMissingError):
        _adapter_harness(
            boundary=boundary,
            adapter_id=config.asr_adapter_id,
            adapter_type="asr",
            output_mode="degraded",
            source_module="mvp5_asr_adapter",
        ).emit_request_failed(
            event_id=f"{event_base}_request_failed",
            caused_by_event_id=str(turn_committed_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            adapter_request_id=binding.adapter_request_id,
            failure_reason="credential_missing",
            retryable=False,
            timeout_ms=grant.timeout_ms,
        )
        return None
    if isinstance(outcome.error, _asr_live_transport_error_type()):
        exc = outcome.error
        _adapter_harness(
            boundary=boundary,
            adapter_id=config.asr_adapter_id,
            adapter_type="asr",
            output_mode="degraded",
            source_module="mvp5_asr_adapter",
        ).emit_request_failed(
            event_id=f"{event_base}_request_failed",
            caused_by_event_id=str(turn_committed_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            adapter_request_id=binding.adapter_request_id,
            failure_reason=_safe_provider_failure_reason(exc.failure_reasons),
            retryable=exc.retryable,
            timeout_ms=grant.timeout_ms if exc.timeout else None,
        )
        return None
    if outcome.error is not None:
        raise outcome.error

    if isinstance(outcome.value, AsrFakeTransportResult):
        return _emit_asr_fake_transport_result(
            boundary=boundary,
            config=config,
            turn_committed_event=turn_committed_event,
            result=outcome.value,
            event_base=event_base,
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
        )

    return _emit_asr_provider_metadata_result(
        boundary=boundary,
        config=config,
        turn_committed_event=turn_committed_event,
        metadata=outcome.value,
        binding=binding,
        event_base=event_base,
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
    )


def _emit_asr_provider_metadata_result(
    *,
    boundary: AdapterCallbackAppendBoundary,
    config: MVP5LiveVoiceEvidenceConfig,
    turn_committed_event: Mapping[str, Any],
    metadata: object,
    binding: AsrRequestBinding,
    event_base: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
) -> dict[str, Any] | None:
    metadata_map = _metadata_from_transport_result(metadata)
    if metadata_map.get("transcript_present") is not True:
        _adapter_harness(
            boundary=boundary,
            adapter_id=config.asr_adapter_id,
            adapter_type="asr",
            output_mode="degraded",
            source_module="mvp5_asr_adapter",
        ).emit_output_validation_failed(
            event_id=f"{event_base}_validation_failed",
            caused_by_event_id=str(turn_committed_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            adapter_request_id=binding.adapter_request_id,
            schema_name="voice_agent.asr.normalized_transcript.v1",
            failure_reasons=("provider_output_validation_failed",),
        )
        return None

    try:
        candidate = normalize_asr_candidate(
            binding=binding,
            asr_frame_ref=str(metadata_map["asr_frame_ref"]),
            text_ref=str(metadata_map["text_ref"]),
            audio_timestamps_ref=None,
            timestamp_status="unavailable",
            streaming_status="unsupported_final_only",
            output_mode="degraded",
        )
    except Exception:
        _adapter_harness(
            boundary=boundary,
            adapter_id=config.asr_adapter_id,
            adapter_type="asr",
            output_mode="degraded",
            source_module="mvp5_asr_adapter",
        ).emit_output_validation_failed(
            event_id=f"{event_base}_validation_failed",
            caused_by_event_id=str(turn_committed_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            adapter_request_id=binding.adapter_request_id,
            schema_name="voice_agent.asr.normalized_transcript.v1",
            failure_reasons=("provider_output_validation_failed",),
        )
        return None

    contract = AsrAdapterContract(
        boundary=boundary,
        adapter_id=config.asr_adapter_id,
        output_mode=candidate.output_mode,
        source_module="mvp5_asr_adapter",
    )
    emission = emit_normalized_asr_candidate(
        contract=contract,
        candidate=candidate,
        turn_committed_event=turn_committed_event,
        event_id=f"{event_base}_transcript",
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
    )
    return emission.transcript_event


def _build_thinker_audio_native_binding(
    *,
    turn_committed_event: Mapping[str, Any],
    run_id: str,
) -> Any:
    event_slug = _slug(run_id)
    adapter_request_id = f"adapter-request-mvp5-thinker-{event_slug}"
    return bind_lalm_thinker_request(
        turn_committed_event=turn_committed_event,
        adapter_request_id=adapter_request_id,
        request_metadata_ref=f"request-metadata://mvp5/live-voice-evidence/{event_slug}",
        input_ref=f"audio://mvp5/live-voice-evidence/{event_slug}",
        policy_ref="policy://mvp5/live-voice-evidence/evidence-only",
        expected_turn_committed_event_id=str(turn_committed_event["event_id"]),
    )


def _call_thinker_audio_native_provider(
    *,
    thinker_transport: object,
    grant: MVP5LiveProviderApprovalGrant,
    env: Mapping[str, str],
    binding: Any,
    audio_bytes: bytes,
) -> str:
    credential_value = env.get(grant.credential_env_var_name)
    if credential_value is None or credential_value == "":
        raise _AdapterCredentialMissingError("credential_missing")

    complete_audio = getattr(thinker_transport, "complete_audio", None)
    if not callable(complete_audio):
        raise MVP5LiveVoiceEvidenceError("Thinker fake transport must provide complete_audio")

    return complete_audio(
        request_payload=build_lalm_thinker_live_request_payload(
            binding=binding,
            transient_input_text=None,
        ),
        audio_bytes=audio_bytes,
        audio_format="wav",
        credential_handle=LALMThinkerCredentialHandle(
            credential_ref=LALM_THINKER_RUNTIME_CREDENTIAL_REF,
        ),
        credential_value=credential_value,
        adapter_request_id=binding.adapter_request_id,
        timeout_ms=grant.timeout_ms,
        model_alias=LALM_THINKER_RUNTIME_MODEL_ALIAS,
    )


def _emit_thinker_audio_native_outcome(
    *,
    boundary: AdapterCallbackAppendBoundary,
    config: MVP5LiveVoiceEvidenceConfig,
    turn_committed_event: Mapping[str, Any],
    outcome: _TimedProviderCallResult,
    binding: Any,
    event_slug: str,
    grant: MVP5LiveProviderApprovalGrant,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
) -> dict[str, Any] | None:
    adapter_request_id = binding.adapter_request_id
    if isinstance(outcome.error, _AdapterCredentialMissingError):
        emit_lalm_thinker_request_failed(
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
        return None
    if isinstance(outcome.error, LALMThinkerLiveTransportError):
        emit_lalm_thinker_request_failed(
            boundary=boundary,
            event_id=f"evt_mvp5_live_evidence_{event_slug}_thinker_request_failed",
            caused_by_event_id=str(turn_committed_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            adapter_request_id=adapter_request_id,
            failure_reason=outcome.error.category,
            retryable=False,
            timeout_ms=grant.timeout_ms,
            adapter_id=config.thinker_adapter_id,
        )
        return None
    if outcome.error is not None:
        raise outcome.error

    try:
        result = emit_lalm_thinker_provider_text_result(
            boundary=boundary,
            adapter_id=config.thinker_adapter_id,
            provider_text=str(outcome.value),
            expected_binding=binding,
            success_event_id=f"evt_mvp5_live_evidence_{event_slug}_thinker_semantic_frame",
            validation_failed_event_id=(
                f"evt_mvp5_live_evidence_{event_slug}_thinker_validation_failed"
            ),
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


def _run_asr_adapter_transport(
    *,
    boundary: AdapterCallbackAppendBoundary,
    config: MVP5LiveVoiceEvidenceConfig,
    turn_committed_event: Mapping[str, Any],
    asr_transport: object,
    grant: MVP5LiveProviderApprovalGrant,
    env: Mapping[str, str],
    audio_bytes: bytes,
    audio_mime_type: str,
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
        raise MVP5LiveVoiceEvidenceError("ASR transport must provide transcribe")
    event_base = f"evt_mvp5_live_evidence_{_slug(run_id)}_asr"
    result = _maybe_call_fake_asr_transport(transcribe, binding)
    if isinstance(result, AsrFakeTransportResult):
        return _emit_asr_fake_transport_result(
            boundary=boundary,
            config=config,
            turn_committed_event=turn_committed_event,
            result=result,
            event_base=event_base,
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
        )

    credential_value = env.get(grant.credential_env_var_name)
    if credential_value is None or credential_value == "":
        _adapter_harness(
            boundary=boundary,
            adapter_id=config.asr_adapter_id,
            adapter_type="asr",
            output_mode="degraded",
            source_module="mvp5_asr_adapter",
        ).emit_request_failed(
            event_id=f"{event_base}_request_failed",
            caused_by_event_id=str(turn_committed_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            adapter_request_id=binding.adapter_request_id,
            failure_reason="credential_missing",
            retryable=False,
            timeout_ms=grant.timeout_ms,
        )
        return None

    try:
        metadata = transcribe(
            audio_payload=audio_bytes,
            audio_mime_type=audio_mime_type,
            credential_handle=_asr_live_credential_handle(
                credential_ref="secret-ref://local/asr-live-eval/dashscope",
            ),
            credential_value=credential_value,
            adapter_request_id=binding.adapter_request_id,
            timeout_ms=grant.timeout_ms,
            model_alias=_asr_live_selected_model_alias(),
        )
    except _asr_live_transport_error_type() as exc:
        _adapter_harness(
            boundary=boundary,
            adapter_id=config.asr_adapter_id,
            adapter_type="asr",
            output_mode="degraded",
            source_module="mvp5_asr_adapter",
        ).emit_request_failed(
            event_id=f"{event_base}_request_failed",
            caused_by_event_id=str(turn_committed_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            adapter_request_id=binding.adapter_request_id,
            failure_reason=_safe_provider_failure_reason(exc.failure_reasons),
            retryable=exc.retryable,
            timeout_ms=grant.timeout_ms if exc.timeout else None,
        )
        return None

    metadata_map = _metadata_from_transport_result(metadata)
    if metadata_map.get("transcript_present") is not True:
        _adapter_harness(
            boundary=boundary,
            adapter_id=config.asr_adapter_id,
            adapter_type="asr",
            output_mode="degraded",
            source_module="mvp5_asr_adapter",
        ).emit_output_validation_failed(
            event_id=f"{event_base}_validation_failed",
            caused_by_event_id=str(turn_committed_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            adapter_request_id=binding.adapter_request_id,
            schema_name="voice_agent.asr.normalized_transcript.v1",
            failure_reasons=("provider_output_validation_failed",),
        )
        return None

    try:
        candidate = normalize_asr_candidate(
            binding=binding,
            asr_frame_ref=str(metadata_map["asr_frame_ref"]),
            text_ref=str(metadata_map["text_ref"]),
            audio_timestamps_ref=None,
            timestamp_status="unavailable",
            streaming_status="unsupported_final_only",
            output_mode="degraded",
        )
    except Exception:
        _adapter_harness(
            boundary=boundary,
            adapter_id=config.asr_adapter_id,
            adapter_type="asr",
            output_mode="degraded",
            source_module="mvp5_asr_adapter",
        ).emit_output_validation_failed(
            event_id=f"{event_base}_validation_failed",
            caused_by_event_id=str(turn_committed_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            adapter_request_id=binding.adapter_request_id,
            schema_name="voice_agent.asr.normalized_transcript.v1",
            failure_reasons=("provider_output_validation_failed",),
        )
        return None

    contract = AsrAdapterContract(
        boundary=boundary,
        adapter_id=config.asr_adapter_id,
        output_mode=candidate.output_mode,
        source_module="mvp5_asr_adapter",
    )
    emission = emit_normalized_asr_candidate(
        contract=contract,
        candidate=candidate,
        turn_committed_event=turn_committed_event,
        event_id=f"{event_base}_transcript",
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
    )
    return emission.transcript_event


def _emit_asr_fake_transport_result(
    *,
    boundary: AdapterCallbackAppendBoundary,
    config: MVP5LiveVoiceEvidenceConfig,
    turn_committed_event: Mapping[str, Any],
    result: AsrFakeTransportResult,
    event_base: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
) -> dict[str, Any] | None:
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
    asr_event: Mapping[str, Any] | None,
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
        transient_input_text = _transient_asr_text(asr_event)
        provider_text = complete_audio(
            request_payload=build_lalm_thinker_live_request_payload(
                binding=binding,
                transient_input_text=transient_input_text,
            ),
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


def _maybe_call_fake_asr_transport(
    transcribe: object,
    binding: AsrRequestBinding,
) -> object | None:
    signature = inspect.signature(transcribe)
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()):
        return None
    if "binding" in signature.parameters:
        return transcribe(binding=binding)
    if len(signature.parameters) == 1:
        return transcribe(binding)
    return None


def _metadata_from_transport_result(value: object) -> Mapping[str, Any]:
    to_metadata = getattr(value, "to_metadata", None)
    metadata = to_metadata() if callable(to_metadata) else value
    if not isinstance(metadata, Mapping):
        raise MVP5LiveVoiceEvidenceError("ASR transport must return safe metadata")
    return metadata


def _asr_live_transport_module() -> Any:
    return importlib.import_module("voice_agent.adapters.asr_live_transport")


def _default_asr_live_transport() -> object:
    return _asr_live_transport_module().DashScopeAsrLiveDirectHTTPTransport()


def _asr_live_transport_error_type() -> type[Exception]:
    return _asr_live_transport_module().DashScopeAsrLiveTransportError


def _asr_live_credential_handle(*, credential_ref: str) -> object:
    return _asr_live_transport_module().AsrLiveCredentialHandle(
        credential_ref=credential_ref,
    )


def _asr_live_selected_model_alias() -> str:
    return str(_asr_live_transport_module().ASR_LIVE_SELECTED_MODEL_ALIAS)


def _resolve_asr_live_transcript_text_ref(text_ref: str) -> str | None:
    return _asr_live_transport_module().resolve_asr_live_transcript_text_ref(text_ref)


def _transient_asr_text(asr_event: Mapping[str, Any] | None) -> str | None:
    if asr_event is None:
        return None
    text_ref = asr_event.get("text_ref")
    if not isinstance(text_ref, str) or text_ref == "":
        return None
    return _resolve_asr_live_transcript_text_ref(text_ref)


def _safe_provider_failure_reason(reasons: Sequence[str]) -> str:
    for reason in reasons:
        if reason in {
            "credential_missing",
            "provider_timeout",
            "provider_request_failed",
            "provider_response_parse_failed",
            "provider_output_validation_failed",
            "unsupported_audio",
        }:
            return reason
        if reason == "unsupported_audio_mime_type":
            return "unsupported_audio"
        if reason == "provider_response_text_missing":
            return "provider_response_parse_failed"
        if "credential" in reason:
            return "credential_missing"
    return "provider_request_failed"


def _failure_reasons_from_events(events: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    reasons: list[str] = []
    for event in events:
        if event.get("event_name") == "ADAPTER_REQUEST_FAILED":
            reason = event.get("failure_reason")
            if isinstance(reason, str) and reason:
                reasons.append(reason)
        elif event.get("event_name") == "ADAPTER_OUTPUT_VALIDATION_FAILED":
            failure_reasons = event.get("failure_reasons")
            if isinstance(failure_reasons, Sequence) and not isinstance(
                failure_reasons,
                (str, bytes, bytearray),
            ):
                reasons.extend(str(reason) for reason in failure_reasons)
            else:
                reasons.append("provider_output_validation_failed")
    if not reasons:
        reasons.append("adapter_evidence_incomplete")
    return tuple(dict.fromkeys(reasons))


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


def _normalize_latency_debug(value: Mapping[str, Any]) -> dict[str, Any]:
    latency_debug: dict[str, Any] = {}
    for field in _LATENCY_MS_FIELDS:
        latency_debug[field] = _non_negative_int(value.get(field, 0), field)
    for field in _LATENCY_BOOL_FIELDS:
        latency_debug[field] = bool(value.get(field, False))
    return latency_debug


def _non_negative_int(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise MVP5LiveVoiceEvidenceError(f"{field} must be a non-negative integer")
    if isinstance(value, float):
        if not value.is_integer():
            raise MVP5LiveVoiceEvidenceError(f"{field} must be a non-negative integer")
        value = int(value)
    if not isinstance(value, int) or value < 0:
        raise MVP5LiveVoiceEvidenceError(f"{field} must be a non-negative integer")
    return value


def _monotonic_ms() -> int:
    return int(time.monotonic() * 1000)


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


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
