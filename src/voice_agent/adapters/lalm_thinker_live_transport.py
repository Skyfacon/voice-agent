from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import unquote

from voice_agent.adapters.capabilities import CREDENTIAL_LIKE_REF_PATTERN
from voice_agent.adapters.lalm_thinker_binding import (
    LALM_THINKER_CANDIDATE_SCHEMA_VERSION,
    LALMThinkerRequestBinding,
)


LALM_THINKER_DASHSCOPE_OPENAI_COMPATIBLE_CHAT_COMPLETIONS_URL = (
    "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
)
LALM_THINKER_CREDENTIAL_SOURCE_METADATA = (
    "runtime_env_var:DASHSCOPE_API_KEY via ~/.voice-agent-secrets/dashscope.env"
)
LALM_THINKER_EVIDENCE_SCHEMA_INSTRUCTION = (
    "Return only one JSON object. No markdown or prose. Copy request_binding "
    "exactly from required_output_skeleton. The output is evidence only and "
    "must not claim commitment, confirmation, tool, playback, or checker ownership."
)

_DISALLOWED_REF_MARKERS = (
    "audio/raw/",
    "diagnostics/",
    "traces/",
    "replays/local/",
)


class LALMThinkerLiveTransportError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        category: str,
        failure_reasons: Sequence[str] | None = None,
    ) -> None:
        self.category = category
        self.failure_ref = f"validation://synthetic/lalm-thinker/live-transport/{_slug(category)}"
        self.failure_reasons = tuple(failure_reasons or (category,))
        super().__init__(
            "lalm_thinker_live_transport_failed "
            f"category={self.category} failure_ref={self.failure_ref}"
        )


@dataclass(frozen=True)
class LALMThinkerCredentialHandle:
    credential_ref: str

    def __post_init__(self) -> None:
        _require_safe_ref(self.credential_ref, "credential_ref")

    def __repr__(self) -> str:
        return (
            "LALMThinkerCredentialHandle("
            f"credential_ref={self.credential_ref!r}, credential_present=True, "
            "secret_materialized=False)"
        )

    def __str__(self) -> str:
        raise LALMThinkerLiveTransportError(
            "LALM Thinker credential handle is opaque and not string serializable",
            category="credential_handle_opaque",
            failure_reasons=("credential_handle_opaque",),
        )

    def to_metadata(self) -> dict[str, Any]:
        return {
            "credential_ref": self.credential_ref,
            "credential_present": True,
            "credential_source": LALM_THINKER_CREDENTIAL_SOURCE_METADATA,
            "credential_value_included": False,
            "secret_materialized": False,
        }


class LALMThinkerLiveDirectHTTPTransport:
    """Adapter-internal direct HTTP transport; tests inject an opener."""

    def __init__(
        self,
        *,
        provider_url: str = LALM_THINKER_DASHSCOPE_OPENAI_COMPATIBLE_CHAT_COMPLETIONS_URL,
        opener: object | None = None,
    ) -> None:
        if not isinstance(provider_url, str) or provider_url == "":
            raise LALMThinkerLiveTransportError(
                "provider_url must be a non-empty string",
                category="transport_config_invalid",
                failure_reasons=("transport_config_invalid",),
            )
        self._provider_url = provider_url
        self._opener = opener if opener is not None else urllib.request.build_opener()

    def complete(
        self,
        *,
        request_payload: Mapping[str, Any],
        credential_handle: LALMThinkerCredentialHandle,
        credential_value: str,
        adapter_request_id: str,
        timeout_ms: int,
        model_alias: str,
    ) -> str:
        validate_lalm_thinker_credential_handle(credential_handle)
        _require_present_credential_value(credential_value)
        _require_safe_token(adapter_request_id, "adapter_request_id")
        _require_positive_int(timeout_ms, "timeout_ms")
        _require_safe_token(model_alias, "model_alias")
        _reject_unsafe_request_payload(request_payload)

        request_body = _build_openai_compatible_request_body(
            model_alias=model_alias,
            request_payload=request_payload,
        )
        request = urllib.request.Request(
            self._provider_url,
            data=json.dumps(request_body, separators=(",", ":"), sort_keys=True).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {credential_value}",
            },
            method="POST",
        )
        timeout_seconds = timeout_ms / 1000

        try:
            with self._opener.open(request, timeout=timeout_seconds) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except TimeoutError as exc:
            raise LALMThinkerLiveTransportError(
                "provider timeout",
                category="provider_timeout",
                failure_reasons=("provider_timeout",),
            ) from exc
        except urllib.error.HTTPError as exc:
            raise LALMThinkerLiveTransportError(
                "provider request failed",
                category="provider_request_failed",
                failure_reasons=(
                    "provider_request_failed",
                    _http_status_class_category(exc.code),
                ),
            ) from exc
        except urllib.error.URLError as exc:
            if isinstance(getattr(exc, "reason", None), TimeoutError):
                raise LALMThinkerLiveTransportError(
                    "provider timeout",
                    category="provider_timeout",
                    failure_reasons=("provider_timeout",),
                ) from exc
            raise LALMThinkerLiveTransportError(
                "provider request failed",
                category="provider_request_failed",
                failure_reasons=("provider_request_failed",),
            ) from exc
        except json.JSONDecodeError as exc:
            raise LALMThinkerLiveTransportError(
                "provider response parse failed",
                category="provider_response_parse_failed",
                failure_reasons=("provider_response_parse_failed",),
            ) from exc

        return _extract_provider_text(response_payload)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "provider_transport": "direct_http",
            "provider_url_ref": "provider-url://dashscope/openai-compatible-chat-completions",
            "raw_provider_request_included": False,
            "raw_provider_response_included": False,
            "headers_included": False,
            "authorization_header_included": False,
            "secret_materialized": False,
        }


def validate_lalm_thinker_credential_handle(
    credential_handle: object,
) -> LALMThinkerCredentialHandle:
    if not isinstance(credential_handle, LALMThinkerCredentialHandle):
        raise LALMThinkerLiveTransportError(
            "credential_handle must be an opaque credential handle",
            category="credential_handle_invalid",
            failure_reasons=("credential_handle_invalid",),
        )
    _require_safe_ref(credential_handle.credential_ref, "credential_ref")
    return credential_handle


def _build_openai_compatible_request_body(
    *,
    model_alias: str,
    request_payload: Mapping[str, Any],
) -> dict[str, Any]:
    request_payload_dict = deepcopy(dict(request_payload))
    user_payload = {
        "request_payload": request_payload_dict,
        "required_output_skeleton": _build_required_output_skeleton(request_payload_dict),
        "output_rules": [
            "copy required_output_skeleton.request_binding exactly",
            "return evidence candidate only",
            "do not execute tools or patch UI",
            "do not include provider request or response bodies",
            "do not wrap JSON in markdown",
            "keep string fields short and ref-like",
        ],
    }
    return {
        "model": model_alias,
        "messages": [
            {
                "role": "system",
                "content": LALM_THINKER_EVIDENCE_SCHEMA_INSTRUCTION,
            },
            {
                "role": "user",
                "content": json.dumps(user_payload, separators=(",", ":"), sort_keys=True),
            },
        ],
        "max_tokens": 900,
        "temperature": 0.1,
    }


def _build_required_output_skeleton(request_payload: Mapping[str, Any]) -> dict[str, Any]:
    request_metadata = request_payload.get("request_metadata")
    request_binding: object = {}
    if isinstance(request_metadata, Mapping):
        request_binding = request_metadata.get("request_binding", {})
    return {
        "schema_version": LALM_THINKER_CANDIDATE_SCHEMA_VERSION,
        "request_binding": request_binding,
        "candidate_role": "evidence_only",
        "output_mode": "degraded",
        "semantic_frame_ref": "semantic-frame://synthetic/lalm-thinker/provider-live/frame",
        "semantic_summary_ref": "summary://synthetic/lalm-thinker/provider-live/summary",
        "optional_evidence_refs": {
            "semantic_close": {"status": "unavailable"},
            "assistant_directedness": {"status": "unavailable"},
            "emotion": {"status": "unavailable"},
            "audio_caption": {"status": "unavailable"},
        },
        "task_focus_hint": {
            "task_like": True,
            "complexity_hint": "complex",
            "focus_confidence": 0.75,
            "evidence_uncertainty": "medium",
        },
        "boundary_assertions": {
            "candidate_is_evidence_only": True,
            "may_emit_event_journal_events": False,
            "may_create_semantic_commitments": False,
            "may_accept_confirmation": False,
            "may_authorize_tools": False,
            "may_execute_tools": False,
            "may_control_playback": False,
            "may_emit_coverage_or_truthfulness_verdicts": False,
        },
        "artifact_policy": {
            "retention": "refs_only",
            "raw_artifacts_retained": False,
        },
        "validation_ref": "validation://synthetic/lalm-thinker/provider-live/candidate",
    }


def _extract_provider_text(response_payload: Mapping[str, Any]) -> str:
    choices = response_payload.get("choices")
    if isinstance(choices, list) and choices:
        first_choice = choices[0]
        if isinstance(first_choice, Mapping):
            message = first_choice.get("message")
            if isinstance(message, Mapping) and isinstance(message.get("content"), str):
                return str(message["content"])

    output = response_payload.get("output")
    if isinstance(output, Mapping) and isinstance(output.get("text"), str):
        return str(output["text"])

    raise LALMThinkerLiveTransportError(
        "provider response text missing",
        category="provider_response_text_missing",
        failure_reasons=(
            "provider_response_text_missing",
            "provider_response_shape_choices_message_content_missing",
            "provider_response_shape_output_text_missing",
        ),
    )


def _reject_unsafe_request_payload(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise LALMThinkerLiveTransportError(
                    "request payload keys must be strings",
                    category="request_payload_invalid",
                    failure_reasons=("request_payload_invalid",),
                )
            _reject_unsafe_string(key)
            _reject_unsafe_request_payload(child)
    elif isinstance(value, str):
        _reject_unsafe_string(value)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _reject_unsafe_request_payload(item)


def _reject_unsafe_string(value: str) -> None:
    variants = {value, unquote(value)}
    for variant in variants:
        if CREDENTIAL_LIKE_REF_PATTERN.search(variant):
            raise LALMThinkerLiveTransportError(
                "credential-like request payload content",
                category="credential_like_content",
                failure_reasons=("credential_like_content",),
            )
        lowered = variant.lower()
        if any(marker in lowered for marker in _DISALLOWED_REF_MARKERS):
            raise LALMThinkerLiveTransportError(
                "request payload references local-only artifacts",
                category="local_only_artifact_ref",
                failure_reasons=("local_only_artifact_ref",),
            )


def _require_present_credential_value(value: object) -> str:
    if not isinstance(value, str) or value == "":
        raise LALMThinkerLiveTransportError(
            "credential value missing",
            category="credential_missing",
            failure_reasons=("credential_missing",),
        )
    return value


def _require_safe_ref(value: object, field: str) -> str:
    token = _require_safe_token(value, field)
    if "://" not in token:
        raise LALMThinkerLiveTransportError(
            f"{field} must be a safe ref",
            category="unsafe_ref",
            failure_reasons=("unsafe_ref",),
        )
    return token


def _require_safe_token(value: object, field: str) -> str:
    if not isinstance(value, str) or value == "":
        raise LALMThinkerLiveTransportError(
            f"{field} must be a non-empty string",
            category="invalid_field",
            failure_reasons=("invalid_field",),
        )
    _reject_unsafe_string(value)
    return value


def _require_positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise LALMThinkerLiveTransportError(
            f"{field} must be a positive integer",
            category="invalid_budget",
            failure_reasons=("invalid_budget",),
        )
    return value


def _http_status_class_category(status_code: int | None) -> str:
    if isinstance(status_code, int):
        status_class = status_code // 100
        if status_class in {1, 2, 3, 4, 5}:
            return f"provider_http_status_class_{status_class}xx"
    return "provider_http_status_class_unknown"


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-") or "unknown"
