from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from typing import Any

from voice_agent.adapters.lalm_thinker_binding import bind_lalm_thinker_request
from voice_agent.adapters.lalm_thinker_live_transport import (
    LALMThinkerCredentialHandle,
    LALMThinkerLiveDirectHTTPTransport,
    LALMThinkerLiveTransportError,
)
from voice_agent.adapters.lalm_thinker_profile import (
    LALM_THINKER_RUNTIME_ADAPTER_ID,
    LALM_THINKER_RUNTIME_MODEL_ALIAS,
)
from voice_agent.adapters.lalm_thinker_skeleton import (
    LALMThinkerCandidateValidationError,
    emit_lalm_thinker_live_provider_result,
    emit_lalm_thinker_request_failed,
)
from voice_agent.adapters.thinker_contract import ThinkerSemanticFrameEmission
from voice_agent.runtime.adapter_callback_boundary import AdapterCallbackAppendBoundary


LALM_THINKER_RUNTIME_CREDENTIAL_ENV_VAR = "DASHSCOPE_API_KEY"
LALM_THINKER_RUNTIME_CREDENTIAL_REF = "secret-ref://runtime-env/dashscope-api-key"
LALM_THINKER_RUNTIME_TIMEOUT_MS = 60_000


@dataclass(frozen=True)
class LALMThinkerRuntimeAdapterResult:
    success: bool
    adapter_request_id: str
    thinker_emission: ThinkerSemanticFrameEmission | None = None
    validation_failed_event: dict[str, Any] | None = None
    request_failed_event: dict[str, Any] | None = None
    failure_category: str | None = None
    failure_ref: str | None = None

    def to_metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "success": self.success,
            "adapter_request_id": self.adapter_request_id,
            "raw_provider_request_included": False,
            "raw_provider_response_included": False,
            "candidate_text_included": False,
            "secret_included": False,
            "authorization_header_included": False,
            "bearer_token_included": False,
        }
        if self.thinker_emission is not None:
            metadata["thinker_event_id"] = self.thinker_emission.thinker_event["event_id"]
        if self.validation_failed_event is not None:
            metadata["validation_failed_event_id"] = self.validation_failed_event["event_id"]
        if self.request_failed_event is not None:
            metadata["request_failed_event_id"] = self.request_failed_event["event_id"]
        if self.failure_category is not None:
            metadata["failure_category"] = self.failure_category
        if self.failure_ref is not None:
            metadata["failure_ref"] = self.failure_ref
        return metadata


class LALMThinkerRuntimeAdapter:
    """Runtime LALM Thinker adapter path backed by DashScope direct HTTP."""

    def __init__(
        self,
        *,
        boundary: AdapterCallbackAppendBoundary,
        env: Mapping[str, str] | None = None,
        transport: object | None = None,
        adapter_id: str = LALM_THINKER_RUNTIME_ADAPTER_ID,
        model_alias: str = LALM_THINKER_RUNTIME_MODEL_ALIAS,
        timeout_ms: int = LALM_THINKER_RUNTIME_TIMEOUT_MS,
    ) -> None:
        self._boundary = boundary
        self._env = os.environ if env is None else env
        self._transport = transport if transport is not None else LALMThinkerLiveDirectHTTPTransport()
        self._adapter_id = _require_safe_token(adapter_id, "adapter_id")
        self._model_alias = _require_safe_token(model_alias, "model_alias")
        if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool) or timeout_ms < 1:
            raise ValueError("timeout_ms must be a positive integer")
        self._timeout_ms = timeout_ms

    def to_metadata(self) -> dict[str, Any]:
        transport_metadata: dict[str, Any]
        to_metadata = getattr(self._transport, "to_metadata", None)
        if callable(to_metadata):
            raw_transport_metadata = to_metadata()
            transport_metadata = (
                dict(raw_transport_metadata)
                if isinstance(raw_transport_metadata, Mapping)
                else {"provider_transport": "unknown"}
            )
        else:
            transport_metadata = {
                "provider_transport": "injected_transport",
                "raw_provider_request_included": False,
                "raw_provider_response_included": False,
                "headers_included": False,
                "authorization_header_included": False,
                "secret_materialized": False,
            }
        metadata: dict[str, Any] = {
            "adapter_id": self._adapter_id,
            "adapter_type": "thinker",
            "output_mode": "real",
            "deployment_mode": "remote_api",
            "model_alias": self._model_alias,
            "credential_ref": LALM_THINKER_RUNTIME_CREDENTIAL_REF,
            "credential_value_included": False,
            "secret_materialized": False,
            "timeout_ms": self._timeout_ms,
            **transport_metadata,
        }
        metadata["raw_provider_request_included"] = False
        metadata["raw_provider_response_included"] = False
        metadata["authorization_header_included"] = False
        return metadata

    def handle_turn_ingress_committed(
        self,
        turn_committed_event: Mapping[str, Any],
        *,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        transient_input_text: str | None = None,
    ) -> LALMThinkerRuntimeAdapterResult:
        event_id = str(turn_committed_event.get("event_id", "unknown"))
        event_slug = _slug(event_id)
        adapter_request_id = f"adapter-request-lalm-thinker-runtime-{event_slug}"
        binding = bind_lalm_thinker_request(
            turn_committed_event=turn_committed_event,
            adapter_request_id=adapter_request_id,
            request_metadata_ref=f"request-metadata://runtime/lalm-thinker/{event_slug}",
            input_ref=_input_ref_for_turn(turn_committed_event),
            policy_ref="policy://runtime/lalm-thinker/evidence-only",
            expected_turn_committed_event_id=event_id,
        )
        credential_value = self._env.get(LALM_THINKER_RUNTIME_CREDENTIAL_ENV_VAR)
        if credential_value is None or credential_value == "":
            return self._emit_request_failed_result(
                adapter_request_id=adapter_request_id,
                caused_by_event_id=event_id,
                created_monotonic_ms=created_monotonic_ms,
                created_wall_clock_ms=created_wall_clock_ms,
                event_slug=event_slug,
                failure_category="credential_missing",
                timeout_ms=None,
            )
        if turn_committed_event.get("input_modality") != "text":
            return self._emit_request_failed_result(
                adapter_request_id=adapter_request_id,
                caused_by_event_id=event_id,
                created_monotonic_ms=created_monotonic_ms,
                created_wall_clock_ms=created_wall_clock_ms,
                event_slug=event_slug,
                failure_category="provider_request_failed",
                timeout_ms=self._timeout_ms,
            )
        if not isinstance(transient_input_text, str) or transient_input_text.strip() == "":
            return self._emit_request_failed_result(
                adapter_request_id=adapter_request_id,
                caused_by_event_id=event_id,
                created_monotonic_ms=created_monotonic_ms,
                created_wall_clock_ms=created_wall_clock_ms,
                event_slug=event_slug,
                failure_category="provider_request_failed",
                timeout_ms=self._timeout_ms,
            )

        credential_handle = LALMThinkerCredentialHandle(
            credential_ref=LALM_THINKER_RUNTIME_CREDENTIAL_REF,
        )
        try:
            provider_result = emit_lalm_thinker_live_provider_result(
                transport=self._transport,
                credential_handle=credential_handle,
                credential_value=credential_value,
                model_alias=self._model_alias,
                timeout_ms=self._timeout_ms,
                boundary=self._boundary,
                adapter_id=self._adapter_id,
                binding=binding,
                success_event_id=f"evt_lalm_thinker_runtime_{event_slug}_semantic_frame",
                validation_failed_event_id=(
                    f"evt_lalm_thinker_runtime_{event_slug}_validation_failed"
                ),
                caused_by_event_id=event_id,
                created_monotonic_ms=created_monotonic_ms,
                created_wall_clock_ms=created_wall_clock_ms,
                turn_committed_event=turn_committed_event,
                transient_input_text=transient_input_text,
            )
        except LALMThinkerLiveTransportError as exc:
            return self._emit_request_failed_result(
                adapter_request_id=adapter_request_id,
                caused_by_event_id=event_id,
                created_monotonic_ms=created_monotonic_ms,
                created_wall_clock_ms=created_wall_clock_ms,
                event_slug=event_slug,
                failure_category=exc.category,
                timeout_ms=self._timeout_ms,
            )
        except LALMThinkerCandidateValidationError as exc:
            return self._emit_request_failed_result(
                adapter_request_id=adapter_request_id,
                caused_by_event_id=event_id,
                created_monotonic_ms=created_monotonic_ms,
                created_wall_clock_ms=created_wall_clock_ms,
                event_slug=event_slug,
                failure_category=exc.category,
                timeout_ms=self._timeout_ms,
            )

        if provider_result.success:
            return LALMThinkerRuntimeAdapterResult(
                success=True,
                adapter_request_id=adapter_request_id,
                thinker_emission=provider_result.thinker_emission,
            )
        return LALMThinkerRuntimeAdapterResult(
            success=False,
            adapter_request_id=adapter_request_id,
            validation_failed_event=provider_result.validation_failed_event,
            failure_category="provider_output_validation_failed",
            failure_ref=_runtime_failure_ref("provider_output_validation_failed"),
        )

    def _emit_request_failed_result(
        self,
        *,
        adapter_request_id: str,
        caused_by_event_id: str,
        created_monotonic_ms: int,
        created_wall_clock_ms: int,
        event_slug: str,
        failure_category: str,
        timeout_ms: int | None,
    ) -> LALMThinkerRuntimeAdapterResult:
        safe_category = _safe_failure_category(failure_category)
        event = emit_lalm_thinker_request_failed(
            boundary=self._boundary,
            event_id=f"evt_lalm_thinker_runtime_{event_slug}_request_failed",
            caused_by_event_id=caused_by_event_id,
            created_monotonic_ms=created_monotonic_ms,
            created_wall_clock_ms=created_wall_clock_ms,
            adapter_request_id=adapter_request_id,
            failure_reason=safe_category,
            retryable=False,
            timeout_ms=timeout_ms,
            adapter_id=self._adapter_id,
        )
        return LALMThinkerRuntimeAdapterResult(
            success=False,
            adapter_request_id=adapter_request_id,
            request_failed_event=event,
            failure_category=safe_category,
            failure_ref=_runtime_failure_ref(safe_category),
        )


def _input_ref_for_turn(turn_committed_event: Mapping[str, Any]) -> str:
    if turn_committed_event.get("input_modality") == "audio":
        source_id = (
            turn_committed_event.get("audio_span_id")
            or turn_committed_event.get("input_span_id")
            or turn_committed_event.get("turn_id")
            or "unknown"
        )
        return f"audio://runtime/lalm-thinker/{_slug(str(source_id))}"
    source_id = (
        turn_committed_event.get("text_span_id")
        or turn_committed_event.get("input_span_id")
        or turn_committed_event.get("turn_id")
        or "unknown"
    )
    return f"text://runtime/lalm-thinker/{_slug(str(source_id))}"


def _safe_failure_category(value: object) -> str:
    if not isinstance(value, str) or value == "":
        return "provider_request_failed"
    if value not in {
        "credential_missing",
        "provider_timeout",
        "provider_request_failed",
        "provider_response_parse_failed",
        "provider_response_text_missing",
        "provider_output_validation_failed",
    }:
        return "provider_request_failed"
    return value


def _runtime_failure_ref(category: str) -> str:
    return f"validation://synthetic/lalm-thinker/runtime/{_slug(category)}"


def _require_safe_token(value: object, field: str) -> str:
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{field} must be a non-empty string")
    lowered = value.lower()
    if any(marker in lowered for marker in ("bearer ", "api_key=", "authorization=", "token=")):
        raise ValueError(f"{field} must not contain credential-like content")
    return value


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-") or "unknown"
