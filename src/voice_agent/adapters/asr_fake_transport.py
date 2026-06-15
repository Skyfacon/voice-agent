from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from voice_agent.adapters.asr_normalization import (
    ASR_NORMALIZED_TRANSCRIPT_SCHEMA,
    AsrNormalizationError,
    AsrRequestBinding,
    NormalizedAsrTranscriptCandidate,
    normalize_asr_candidate,
)
from voice_agent.adapters.capabilities import CREDENTIAL_LIKE_REF_PATTERN


class FakeAsrTransportError(ValueError):
    pass


@dataclass(frozen=True)
class FakeAsrProviderResponse:
    kind: str
    payload: dict[str, Any]

    @classmethod
    def success(
        cls,
        *,
        asr_frame_ref: str,
        text_ref: str,
        audio_timestamps_ref: str | None = None,
        streaming_status: str = "supported",
        quality_flags: tuple[str, ...] = (),
        confidence_score: float | None = None,
    ) -> FakeAsrProviderResponse:
        return cls(
            kind="success",
            payload={
                "asr_frame_ref": asr_frame_ref,
                "text_ref": text_ref,
                "audio_timestamps_ref": audio_timestamps_ref,
                "streaming_status": streaming_status,
                "quality_flags": quality_flags,
                "confidence_score": confidence_score,
            },
        )

    @classmethod
    def malformed(cls, *failure_reasons: str) -> FakeAsrProviderResponse:
        return cls(kind="malformed", payload={"failure_reasons": tuple(failure_reasons)})

    @classmethod
    def timeout(cls, *, timeout_ms: int) -> FakeAsrProviderResponse:
        return cls(kind="timeout", payload={"timeout_ms": timeout_ms})

    @classmethod
    def request_failure(cls, failure_reason: str) -> FakeAsrProviderResponse:
        return cls(kind="request_failure", payload={"failure_reason": failure_reason})

    @classmethod
    def late_result(
        cls,
        *,
        asr_frame_ref: str,
        text_ref: str,
    ) -> FakeAsrProviderResponse:
        return cls(
            kind="late_result",
            payload={"asr_frame_ref": asr_frame_ref, "text_ref": text_ref},
        )


@dataclass(frozen=True)
class AsrFakeTransportResult:
    candidate: NormalizedAsrTranscriptCandidate | None = None
    validation_failure_metadata: dict[str, Any] | None = None
    request_failure_metadata: dict[str, Any] | None = None
    late_result_metadata: dict[str, Any] | None = None


class FakeAsrTransport:
    def __init__(self, responses: Sequence[FakeAsrProviderResponse]) -> None:
        if not responses:
            raise FakeAsrTransportError("FakeAsrTransport requires at least one response")
        self._responses = tuple(responses)
        self._next_index = 0

    def transcribe(self, binding: AsrRequestBinding) -> AsrFakeTransportResult:
        response = self._next_response()
        if response.kind == "success":
            return self._success_result(binding, response.payload)
        if response.kind == "malformed":
            return AsrFakeTransportResult(
                validation_failure_metadata=_validation_failure_metadata(
                    binding,
                    _safe_reasons(response.payload.get("failure_reasons", ())),
                )
            )
        if response.kind == "timeout":
            return AsrFakeTransportResult(
                request_failure_metadata={
                    "adapter_request_id": binding.adapter_request_id,
                    "failure_reason": "timeout",
                    "retryable": True,
                    "timeout_ms": response.payload.get("timeout_ms"),
                    "output_mode": "degraded",
                }
            )
        if response.kind == "request_failure":
            return AsrFakeTransportResult(
                request_failure_metadata={
                    "adapter_request_id": binding.adapter_request_id,
                    "failure_reason": _safe_reason(response.payload.get("failure_reason")),
                    "retryable": False,
                    "timeout_ms": None,
                    "output_mode": "degraded",
                }
            )
        if response.kind == "late_result":
            return self._late_result(binding, response.payload)
        raise FakeAsrTransportError(f"Unsupported fake ASR response kind: {response.kind!r}")

    def _next_response(self) -> FakeAsrProviderResponse:
        if self._next_index >= len(self._responses):
            return self._responses[-1]
        response = self._responses[self._next_index]
        self._next_index += 1
        return response

    def _success_result(
        self,
        binding: AsrRequestBinding,
        payload: dict[str, Any],
    ) -> AsrFakeTransportResult:
        audio_timestamps_ref = payload.get("audio_timestamps_ref")
        streaming_status = str(payload.get("streaming_status", "supported"))
        output_mode = (
            "degraded"
            if audio_timestamps_ref is None or streaming_status == "unsupported_final_only"
            else "real"
        )
        confidence_score = payload.get("confidence_score")
        confidence_status = "available" if confidence_score is not None else "unavailable"
        try:
            candidate = normalize_asr_candidate(
                binding=binding,
                asr_frame_ref=payload.get("asr_frame_ref"),
                text_ref=payload.get("text_ref"),
                audio_timestamps_ref=audio_timestamps_ref,
                confidence_status=confidence_status,
                confidence_score=confidence_score,
                timestamp_status="available" if audio_timestamps_ref is not None else "unavailable",
                streaming_status=streaming_status,
                output_mode=output_mode,
                quality_flags=payload.get("quality_flags", ()),
            )
        except AsrNormalizationError as exc:
            return AsrFakeTransportResult(
                validation_failure_metadata=_validation_failure_metadata(binding, (str(exc),))
            )
        return AsrFakeTransportResult(candidate=candidate)

    def _late_result(
        self,
        binding: AsrRequestBinding,
        payload: dict[str, Any],
    ) -> AsrFakeTransportResult:
        try:
            candidate = normalize_asr_candidate(
                binding=binding,
                asr_frame_ref=payload.get("asr_frame_ref"),
                text_ref=payload.get("text_ref"),
                audio_timestamps_ref=None,
                timestamp_status="unavailable",
                streaming_status="unsupported_final_only",
                output_mode="degraded",
                quality_flags=("late_result_stale",),
            )
        except AsrNormalizationError as exc:
            return AsrFakeTransportResult(
                validation_failure_metadata=_validation_failure_metadata(binding, (str(exc),))
            )
        return AsrFakeTransportResult(
            late_result_metadata={
                "adapter_request_id": binding.adapter_request_id,
                "turn_id": binding.turn_id,
                "utterance_id": binding.utterance_id,
                "audio_span_id": binding.audio_span_id,
                "late_result_status": "stale_ignored",
                "stale_reason": "result_returned_after_current_request_window",
                "asr_frame_ref": candidate.asr_frame_ref,
                "text_ref": candidate.text_ref,
            }
        )


def _validation_failure_metadata(
    binding: AsrRequestBinding,
    failure_reasons: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "adapter_request_id": binding.adapter_request_id,
        "schema_name": ASR_NORMALIZED_TRANSCRIPT_SCHEMA,
        "failure_reasons": failure_reasons,
        "output_mode": "degraded",
    }


def _safe_reasons(reasons: Any) -> tuple[str, ...]:
    if isinstance(reasons, (str, bytes)) or not isinstance(reasons, Sequence):
        return ("malformed_output",)
    normalized = tuple(_safe_reason(reason) for reason in reasons)
    return normalized or ("malformed_output",)


def _safe_reason(reason: Any) -> str:
    if not isinstance(reason, str) or reason == "":
        return "request_failed"
    if CREDENTIAL_LIKE_REF_PATTERN.search(reason):
        return "redacted_failure"
    return reason
