from __future__ import annotations

import base64
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
from voice_agent.adapters.lalm_thinker_prompt_rules import (
    LALM_THINKER_AUDIO_ROUTING_OUTPUT_RULES,
    LALM_THINKER_EVIDENCE_SCHEMA_INSTRUCTION,
    LALM_THINKER_ROUTING_OUTPUT_RULES,
    LALM_THINKER_ROUTING_PROMPT_PROFILE_METADATA,
)


LALM_THINKER_DASHSCOPE_OPENAI_COMPATIBLE_CHAT_COMPLETIONS_URL = (
    "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
)
LALM_THINKER_CREDENTIAL_SOURCE_METADATA = (
    "runtime_env_var:DASHSCOPE_API_KEY via ~/.voice-agent-secrets/dashscope.env"
)
_DISALLOWED_REF_MARKERS = (
    "audio/raw/",
    "diagnostics/",
    "traces/",
    "replays/local/",
)
_LOCAL_THINKER_MODEL_IO_BY_ADAPTER_REQUEST_ID: dict[str, dict[str, Any]] = {}


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


def resolve_lalm_thinker_live_model_io_debug(adapter_request_id: str) -> dict[str, Any] | None:
    _require_safe_token(adapter_request_id, "adapter_request_id")
    value = _LOCAL_THINKER_MODEL_IO_BY_ADAPTER_REQUEST_ID.get(adapter_request_id)
    return deepcopy(value) if value is not None else None


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
        _store_lalm_thinker_model_io_request(
            adapter_request_id=adapter_request_id,
            model_alias=model_alias,
            request_body=request_body,
        )
        provider_text = self._complete_streaming_request_body(
            request_body=request_body,
            credential_value=credential_value,
            timeout_ms=timeout_ms,
        )
        _store_lalm_thinker_model_io_response(
            adapter_request_id=adapter_request_id,
            provider_text=provider_text,
        )
        return provider_text

    def complete_audio(
        self,
        *,
        request_payload: Mapping[str, Any],
        audio_bytes: bytes,
        audio_format: str,
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
        _require_audio_bytes(audio_bytes)
        audio_format = _require_audio_format(audio_format)
        _reject_unsafe_request_payload(request_payload)

        request_body = _build_openai_compatible_audio_request_body(
            model_alias=model_alias,
            request_payload=request_payload,
            audio_bytes=audio_bytes,
            audio_format=audio_format,
        )
        _store_lalm_thinker_model_io_request(
            adapter_request_id=adapter_request_id,
            model_alias=model_alias,
            request_body=request_body,
        )
        provider_text = self._complete_streaming_request_body(
            request_body=request_body,
            credential_value=credential_value,
            timeout_ms=timeout_ms,
        )
        _store_lalm_thinker_model_io_response(
            adapter_request_id=adapter_request_id,
            provider_text=provider_text,
        )
        return provider_text

    def _complete_request_body(
        self,
        *,
        request_body: Mapping[str, Any],
        credential_value: str,
        timeout_ms: int,
    ) -> str:
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

    def _complete_streaming_request_body(
        self,
        *,
        request_body: Mapping[str, Any],
        credential_value: str,
        timeout_ms: int,
    ) -> str:
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
        text_parts: list[str] = []

        try:
            with self._opener.open(request, timeout=timeout_seconds) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8").strip()
                    if line == "" or not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        break
                    chunk_payload = json.loads(data)
                    text_delta = _extract_provider_stream_text_delta(chunk_payload)
                    if text_delta is not None:
                        text_parts.append(text_delta)
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

        provider_text = "".join(text_parts)
        if provider_text == "":
            raise LALMThinkerLiveTransportError(
                "provider response text missing",
                category="provider_response_text_missing",
                failure_reasons=(
                    "provider_response_text_missing",
                    "provider_response_stream_delta_content_missing",
                ),
            )
        return provider_text

    def to_metadata(self) -> dict[str, Any]:
        return {
            "provider_transport": "direct_http",
            "provider_url_ref": "provider-url://dashscope/openai-compatible-chat-completions",
            "audio_input_supported": True,
            "raw_provider_request_included": False,
            "raw_provider_response_included": False,
            "raw_audio_included": False,
            "audio_bytes_retained": False,
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
        "routing_prompt_profile": _routing_prompt_profile_metadata(request_payload_dict),
        "required_output_skeleton": _build_required_output_skeleton(request_payload_dict),
        "output_rules": _routing_output_rules(request_payload_dict),
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
        "stream": True,
        "stream_options": {"include_usage": True},
        "modalities": ["text"],
        "response_format": {"type": "json_object"},
        "max_tokens": 900,
        "temperature": 0.1,
    }


def _build_openai_compatible_audio_request_body(
    *,
    model_alias: str,
    request_payload: Mapping[str, Any],
    audio_bytes: bytes,
    audio_format: str,
) -> dict[str, Any]:
    request_payload_dict = deepcopy(dict(request_payload))
    user_payload = {
        "request_payload": request_payload_dict,
        "routing_prompt_profile": _routing_prompt_profile_metadata(request_payload_dict),
        "required_output_skeleton": _build_required_output_skeleton(request_payload_dict),
        "output_rules": _routing_audio_output_rules(request_payload_dict),
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
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(user_payload, separators=(",", ":"), sort_keys=True),
                    },
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": f"data:;base64,{base64.b64encode(audio_bytes).decode('ascii')}",
                            "format": audio_format,
                        },
                    },
                ],
            },
        ],
        "stream": True,
        "stream_options": {"include_usage": True},
        "modalities": ["text"],
        "response_format": {"type": "json_object"},
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
        "semantic_frame_hint": {
            "status": "available",
            "label": "semantic_frame_available",
        },
        "semantic_summary_hint": {
            "status": "available",
            "label": "semantic_summary_available",
        },
        "optional_evidence_refs": {
            "semantic_close": {"status": "unavailable"},
            "assistant_directedness": {"status": "unavailable"},
            "emotion": {"status": "unavailable"},
            "audio_caption": {"status": "unavailable"},
        },
        "task_focus_hint": {
            "focus": "AMBIGUOUS",
            "task_like": False,
            "complexity_hint": "unknown",
            "focus_confidence": 0.5,
            "evidence_uncertainty": "high",
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
            "owns_semantic_commitment": False,
            "owns_confirmation_state": False,
            "owns_tool_authorization": False,
            "owns_tool_execution": False,
            "owns_playback": False,
            "owns_coverage_truthfulness_checks": False,
        },
        "artifact_policy": {
            "retention": "refs_only",
            "raw_artifacts_retained": False,
        },
    }


def _routing_prompt_profile_metadata(request_payload: Mapping[str, Any]) -> dict[str, Any]:
    metadata = request_payload.get("routing_prompt_profile")
    if isinstance(metadata, Mapping):
        return deepcopy(dict(metadata))
    return dict(LALM_THINKER_ROUTING_PROMPT_PROFILE_METADATA)


def _routing_output_rules(request_payload: Mapping[str, Any]) -> list[str]:
    rules = request_payload.get("output_rules")
    if isinstance(rules, Sequence) and not isinstance(rules, (str, bytes, bytearray)):
        return [str(rule) for rule in rules]
    return list(LALM_THINKER_ROUTING_OUTPUT_RULES)


def _routing_audio_output_rules(request_payload: Mapping[str, Any]) -> list[str]:
    profile_metadata = _routing_prompt_profile_metadata(request_payload)
    default_metadata = dict(LALM_THINKER_ROUTING_PROMPT_PROFILE_METADATA)
    if profile_metadata == default_metadata:
        return list(LALM_THINKER_AUDIO_ROUTING_OUTPUT_RULES)
    rules = _routing_output_rules(request_payload)
    if "使用随附的音频作为 Thinker candidate 的主要证据" in rules:
        return rules
    return [
        *rules[:14],
        "使用随附的音频作为 Thinker candidate 的主要证据",
        *rules[14:],
    ]


def _store_lalm_thinker_model_io_request(
    *,
    adapter_request_id: str,
    model_alias: str,
    request_body: Mapping[str, Any],
) -> None:
    _LOCAL_THINKER_MODEL_IO_BY_ADAPTER_REQUEST_ID[adapter_request_id] = {
        "adapter": "thinker",
        "adapter_request_id": adapter_request_id,
        "model_alias": model_alias,
        "provider_url_ref": "provider-url://dashscope/openai-compatible-chat-completions",
        "system_message": _extract_system_message(request_body),
        "request_body": _redact_model_io_value(request_body),
        "provider_text": None,
        "raw_audio_visible": False,
        "authorization_header_visible": False,
    }


def _store_lalm_thinker_model_io_response(
    *,
    adapter_request_id: str,
    provider_text: str,
) -> None:
    current = _LOCAL_THINKER_MODEL_IO_BY_ADAPTER_REQUEST_ID.setdefault(
        adapter_request_id,
        {
            "adapter": "thinker",
            "adapter_request_id": adapter_request_id,
            "provider_url_ref": "provider-url://dashscope/openai-compatible-chat-completions",
            "system_message": LALM_THINKER_EVIDENCE_SCHEMA_INSTRUCTION,
            "request_body": None,
            "raw_audio_visible": False,
            "authorization_header_visible": False,
        },
    )
    current["provider_text"] = _redact_debug_string(provider_text)


def _extract_system_message(request_body: Mapping[str, Any]) -> str:
    messages = request_body.get("messages")
    if isinstance(messages, Sequence) and not isinstance(messages, (str, bytes, bytearray)):
        for message in messages:
            if (
                isinstance(message, Mapping)
                and message.get("role") == "system"
                and isinstance(message.get("content"), str)
            ):
                return _redact_debug_string(str(message["content"]))
    return LALM_THINKER_EVIDENCE_SCHEMA_INSTRUCTION


def _redact_model_io_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _redact_model_io_value(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_redact_model_io_value(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_model_io_value(item) for item in value]
    if isinstance(value, str):
        if value.startswith("data:"):
            return "[redacted-audio-base64]"
        return _redact_debug_string(value)
    return value


def _redact_debug_string(value: str) -> str:
    redacted = value
    for marker in (
        "Bearer ",
        "authorization:",
        "cookie:",
        "api_key=",
        "token=",
        "file://",
        "/Users/",
        "\\Users\\",
        "/private/",
        ".env",
    ):
        redacted = redacted.replace(marker, "[redacted]")
        redacted = redacted.replace(marker.lower(), "[redacted]")
    return redacted


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


def _extract_provider_stream_text_delta(response_payload: Mapping[str, Any]) -> str | None:
    choices = response_payload.get("choices")
    if isinstance(choices, list) and choices:
        first_choice = choices[0]
        if isinstance(first_choice, Mapping):
            delta = first_choice.get("delta")
            if isinstance(delta, Mapping) and isinstance(delta.get("content"), str):
                return str(delta["content"])
            message = first_choice.get("message")
            if isinstance(message, Mapping) and isinstance(message.get("content"), str):
                return str(message["content"])

    output = response_payload.get("output")
    if isinstance(output, Mapping) and isinstance(output.get("text"), str):
        return str(output["text"])
    return None


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


def _require_audio_bytes(value: object) -> bytes:
    if not isinstance(value, bytes) or value == b"":
        raise LALMThinkerLiveTransportError(
            "audio_bytes must be non-empty bytes",
            category="audio_input_invalid",
            failure_reasons=("audio_input_invalid",),
        )
    return value


def _require_audio_format(value: object) -> str:
    if value not in {"wav", "mp3", "m4a", "aac", "ogg", "flac"}:
        raise LALMThinkerLiveTransportError(
            "audio_format unsupported",
            category="audio_input_invalid",
            failure_reasons=("audio_input_invalid",),
        )
    return str(value)


def _http_status_class_category(status_code: int | None) -> str:
    if isinstance(status_code, int):
        status_class = status_code // 100
        if status_class in {1, 2, 3, 4, 5}:
            return f"provider_http_status_class_{status_class}xx"
    return "provider_http_status_class_unknown"


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-") or "unknown"
