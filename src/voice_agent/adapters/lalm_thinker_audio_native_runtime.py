from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from voice_agent.adapters.lalm_thinker_binding import bind_lalm_thinker_request
from voice_agent.adapters.lalm_thinker_live_transport import (
    LALMThinkerCredentialHandle,
    LALMThinkerLiveTransportError,
)
from voice_agent.adapters.lalm_thinker_profile import (
    LALM_THINKER_RUNTIME_ADAPTER_ID,
    LALM_THINKER_RUNTIME_MODEL_ALIAS,
)
from voice_agent.adapters.lalm_thinker_skeleton import (
    build_lalm_thinker_live_request_payload,
    emit_lalm_thinker_provider_text_result,
    emit_lalm_thinker_request_failed,
)
from voice_agent.adapters.thinker_contract import ThinkerSemanticFrameEmission
from voice_agent.runtime.adapter_callback_boundary import AdapterCallbackAppendBoundary


LALM_THINKER_AUDIO_NATIVE_CREDENTIAL_REF = "secret-ref://runtime/lalm-thinker/audio-native"
LALM_THINKER_AUDIO_NATIVE_TIMEOUT_MS = 60_000


@dataclass(frozen=True)
class LALMThinkerAudioNativeEvidenceResult:
    success: bool
    adapter_request_id: str
    thinker_emission: ThinkerSemanticFrameEmission | None = None
    validation_failed_event: dict[str, Any] | None = None
    request_failed_event: dict[str, Any] | None = None
    failure_category: str | None = None

    def to_metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "success": self.success,
            "adapter_request_id": self.adapter_request_id,
            "adapter_path": "lalm_thinker_audio_native",
            "input_modality": "audio",
            "raw_audio_included": False,
            "raw_provider_request_included": False,
            "raw_provider_response_included": False,
            "candidate_text_included": False,
            "secret_included": False,
            "authorization_header_included": False,
            "semantic_commitment_owner": False,
            "semantic_evidence_role": "primary_semantic_evidence",
        }
        if self.thinker_emission is not None:
            metadata["thinker_event_id"] = self.thinker_emission.thinker_event["event_id"]
            metadata["output_mode"] = self.thinker_emission.thinker_event["output_mode"]
        if self.validation_failed_event is not None:
            metadata["validation_failed_event_id"] = self.validation_failed_event["event_id"]
        if self.request_failed_event is not None:
            metadata["request_failed_event_id"] = self.request_failed_event["event_id"]
        if self.failure_category is not None:
            metadata["failure_category"] = self.failure_category
        return metadata


def emit_lalm_thinker_audio_native_evidence_for_turn(
    *,
    boundary: AdapterCallbackAppendBoundary,
    turn_committed_event: Mapping[str, Any],
    case_id: str,
    transport: object,
    audio_payload: bytes,
    audio_format: str,
    credential_value: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    adapter_id: str = LALM_THINKER_RUNTIME_ADAPTER_ID,
    model_alias: str = LALM_THINKER_RUNTIME_MODEL_ALIAS,
    credential_ref: str = LALM_THINKER_AUDIO_NATIVE_CREDENTIAL_REF,
    timeout_ms: int = LALM_THINKER_AUDIO_NATIVE_TIMEOUT_MS,
) -> LALMThinkerAudioNativeEvidenceResult:
    _validate_committed_audio_turn(turn_committed_event)
    _validate_audio_payload(audio_payload=audio_payload, audio_format=audio_format)
    if not isinstance(credential_value, str) or credential_value == "":
        raise ValueError("credential_value must be a non-empty string supplied by the caller")

    event_slug = _slug(str(turn_committed_event["event_id"]))
    case_slug = _slug(case_id)
    adapter_request_id = (
        f"adapter-request-mvp4-thinker-audio-native-{case_slug}-{event_slug}"
    )
    binding = bind_lalm_thinker_request(
        turn_committed_event=turn_committed_event,
        adapter_request_id=adapter_request_id,
        request_metadata_ref=f"request-metadata://runtime/lalm-thinker/audio-native/{case_slug}/{event_slug}",
        input_ref=_audio_input_ref(turn_committed_event),
        policy_ref="policy://runtime/lalm-thinker/evidence-only",
        expected_turn_committed_event_id=str(turn_committed_event["event_id"]),
    )
    request_payload = build_lalm_thinker_live_request_payload(binding=binding)
    complete_audio = getattr(transport, "complete_audio", None)
    if not callable(complete_audio):
        raise ValueError("transport must provide complete_audio")

    try:
        provider_text = complete_audio(
            request_payload=request_payload,
            audio_bytes=audio_payload,
            audio_format=audio_format,
            credential_handle=LALMThinkerCredentialHandle(credential_ref=credential_ref),
            credential_value=credential_value,
            adapter_request_id=adapter_request_id,
            timeout_ms=timeout_ms,
            model_alias=model_alias,
        )
    except LALMThinkerLiveTransportError as exc:
        request_failed = emit_lalm_thinker_request_failed(
            boundary=boundary,
            event_id=f"evt_mvp4_lalm_thinker_audio_native_{case_slug}_{event_slug}_request_failed",
            caused_by_event_id=str(turn_committed_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            adapter_request_id=adapter_request_id,
            failure_reason=exc.category,
            retryable=False,
            timeout_ms=timeout_ms,
            adapter_id=adapter_id,
        )
        return LALMThinkerAudioNativeEvidenceResult(
            success=False,
            adapter_request_id=adapter_request_id,
            request_failed_event=request_failed,
            failure_category=str(request_failed["failure_reason"]),
        )

    if not isinstance(provider_text, str):
        request_failed = emit_lalm_thinker_request_failed(
            boundary=boundary,
            event_id=f"evt_mvp4_lalm_thinker_audio_native_{case_slug}_{event_slug}_request_failed",
            caused_by_event_id=str(turn_committed_event["event_id"]),
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            adapter_request_id=adapter_request_id,
            failure_reason="provider_response_text_missing",
            retryable=False,
            timeout_ms=timeout_ms,
            adapter_id=adapter_id,
        )
        return LALMThinkerAudioNativeEvidenceResult(
            success=False,
            adapter_request_id=adapter_request_id,
            request_failed_event=request_failed,
            failure_category=str(request_failed["failure_reason"]),
        )

    provider_result = emit_lalm_thinker_provider_text_result(
        boundary=boundary,
        adapter_id=adapter_id,
        provider_text=provider_text,
        expected_binding=binding,
        success_event_id=f"evt_mvp4_lalm_thinker_audio_native_{case_slug}_{event_slug}_semantic_frame",
        validation_failed_event_id=(
            f"evt_mvp4_lalm_thinker_audio_native_{case_slug}_{event_slug}_validation_failed"
        ),
        caused_by_event_id=str(turn_committed_event["event_id"]),
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        turn_committed_event=turn_committed_event,
    )
    return LALMThinkerAudioNativeEvidenceResult(
        success=provider_result.success,
        adapter_request_id=adapter_request_id,
        thinker_emission=provider_result.thinker_emission,
        validation_failed_event=provider_result.validation_failed_event,
        failure_category=None if provider_result.success else "provider_output_validation_failed",
    )


def _validate_committed_audio_turn(event: Mapping[str, Any]) -> None:
    if event.get("event_name") != "TURN_INGRESS_COMMITTED":
        raise ValueError("audio-native Thinker evidence requires TURN_INGRESS_COMMITTED")
    if event.get("input_modality") != "audio" or event.get("audio_span_id") in (None, ""):
        raise ValueError("audio-native Thinker evidence requires committed audio turn metadata")


def _validate_audio_payload(*, audio_payload: bytes, audio_format: str) -> None:
    if not isinstance(audio_payload, bytes) or audio_payload == b"":
        raise ValueError("audio_payload must be non-empty bytes")
    if audio_format != "wav":
        raise ValueError("audio-native Thinker evidence currently accepts wav payloads only")


def _audio_input_ref(turn_committed_event: Mapping[str, Any]) -> str:
    value = turn_committed_event.get("audio_input_ref")
    if isinstance(value, str) and value != "":
        return value
    return f"audio://runtime/lalm-thinker/{_slug(str(turn_committed_event['audio_span_id']))}"


def _slug(value: object) -> str:
    text = str(value)
    return "".join(char.lower() if char.isalnum() else "-" for char in text).strip("-") or "unknown"
