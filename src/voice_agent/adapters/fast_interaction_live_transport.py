from __future__ import annotations

import base64
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import json
import re
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import unquote

from voice_agent.adapters.adapter_timing import AdapterTimingRecorder, AdapterTimingSnapshot
from voice_agent.adapters.capabilities import CREDENTIAL_LIKE_REF_PATTERN


FAST_INTERACTION_DASHSCOPE_OPENAI_COMPATIBLE_CHAT_COMPLETIONS_URL = (
    "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
)
FAST_INTERACTION_DASHSCOPE_PROVIDER_URL_REF = (
    "provider-url://dashscope/fast-interaction-openai-compatible-chat-completions"
)

_LOCAL_MODEL_IO_BY_ADAPTER_REQUEST_ID: dict[str, dict[str, Any]] = {}
_DISALLOWED_MARKERS = (
    "audio/raw/",
    "diagnostics/",
    "traces/",
    "replays/local/",
    "file://",
    "/users/",
    "\\users\\",
    "/private/",
    ".env",
    "raw_audio",
    "raw_prompt",
    "raw_provider",
    "provider_body",
    "provider_payload",
    "provider_request",
    "provider_response",
    "provider_schema",
    "provider_text",
)
_REQUEST_SECRET_PATTERN = re.compile(
    r"(?i)\b("
    r"sk-[A-Za-z0-9_-]+|"
    r"Bearer\s+\S+|"
    r"api[_-]?key\s*[:=]|"
    r"authorization\s*[:=]|"
    r"credential\s*[:=]|"
    r"token\s*[:=]|"
    r"password\s*[:=]|"
    r"cookie\s*[:=]"
    r")"
)

_SYSTEM_PROMPT = (
    "You are the Fast Interaction adapter for voice_agent.fast_interaction.output.v1. "
    "Return exactly one strict JSON object, no markdown, no prose, no tool calls. "
    "You may suggest route evidence and a low-risk foreground candidate, but no tools, "
    "no side effects, no confirmations, and no SlowTask fact mutation. The runtime gate "
    "owns display and may discard every candidate."
)


class FastInteractionLiveTransportError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        category: str,
        failure_reasons: Sequence[str] | None = None,
    ) -> None:
        self.category = category
        self.failure_ref = (
            "validation://synthetic/fast-interaction/live-transport/"
            f"{_slug(category)}"
        )
        self.failure_reasons = tuple(failure_reasons or (category,))
        super().__init__(
            "fast_interaction_live_transport_failed "
            f"category={self.category} failure_ref={self.failure_ref}"
        )


@dataclass(frozen=True)
class FastInteractionCredentialHandle:
    credential_ref: str

    def __post_init__(self) -> None:
        _require_safe_ref(self.credential_ref, "credential_ref")

    def __repr__(self) -> str:
        return (
            "FastInteractionCredentialHandle("
            f"credential_ref={self.credential_ref!r}, credential_present=True, "
            "secret_materialized=False)"
        )

    def __str__(self) -> str:
        raise FastInteractionLiveTransportError(
            "Fast Interaction credential handle is opaque and not string serializable",
            category="credential_handle_opaque",
            failure_reasons=("credential_handle_opaque",),
        )

    def to_metadata(self) -> dict[str, Any]:
        return {
            "credential_ref": self.credential_ref,
            "credential_present": True,
            "credential_source": "runtime_env_var:DASHSCOPE_API_KEY",
            "credential_value_included": False,
            "secret_materialized": False,
        }


@dataclass(frozen=True)
class FastInteractionProviderCompletion:
    provider_text: str
    timing: AdapterTimingSnapshot


def resolve_fast_interaction_model_io_debug(adapter_request_id: str) -> dict[str, Any] | None:
    _require_safe_token(adapter_request_id, "adapter_request_id")
    value = _LOCAL_MODEL_IO_BY_ADAPTER_REQUEST_ID.get(adapter_request_id)
    return deepcopy(value) if value is not None else None


class FastInteractionLiveDirectHTTPTransport:
    """Adapter-internal HTTP transport; tests must inject an opener."""

    def __init__(
        self,
        *,
        provider_url: str = FAST_INTERACTION_DASHSCOPE_OPENAI_COMPATIBLE_CHAT_COMPLETIONS_URL,
        opener: object | None = None,
    ) -> None:
        if not isinstance(provider_url, str) or provider_url == "":
            raise FastInteractionLiveTransportError(
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
        credential_handle: FastInteractionCredentialHandle,
        credential_value: str,
        adapter_request_id: str,
        timeout_ms: int,
        model_alias: str,
    ) -> str:
        return self.complete_with_timing(
            request_payload=request_payload,
            credential_handle=credential_handle,
            credential_value=credential_value,
            adapter_request_id=adapter_request_id,
            timeout_ms=timeout_ms,
            model_alias=model_alias,
            turn_ingress_monotonic_ms=0,
        ).provider_text

    def complete_with_timing(
        self,
        *,
        request_payload: Mapping[str, Any],
        credential_handle: FastInteractionCredentialHandle,
        credential_value: str,
        adapter_request_id: str,
        timeout_ms: int,
        model_alias: str,
        turn_ingress_monotonic_ms: int,
        now_ms: Callable[[], int] | None = None,
    ) -> FastInteractionProviderCompletion:
        timing = AdapterTimingRecorder(
            turn_ingress_monotonic_ms=turn_ingress_monotonic_ms,
            now_ms=now_ms,
        )
        timing.mark_adapter_started()
        _validate_credential_handle(credential_handle)
        _require_present_credential_value(credential_value)
        _require_safe_token(adapter_request_id, "adapter_request_id")
        _require_positive_int(timeout_ms, "timeout_ms")
        _require_safe_token(model_alias, "model_alias")
        _reject_unsafe_request_payload(request_payload)

        request_body = _build_request_body(
            model_alias=model_alias,
            request_payload=request_payload,
        )
        _store_model_io_request(
            adapter_request_id=adapter_request_id,
            model_alias=model_alias,
            request_body=request_body,
        )
        completion = self._complete_streaming_request_body_with_timing(
            request_body=request_body,
            credential_value=credential_value,
            timeout_ms=timeout_ms,
            timing=timing,
        )
        _store_model_io_response(
            adapter_request_id=adapter_request_id,
            provider_text=completion.provider_text,
        )
        return completion

    def complete_audio(
        self,
        *,
        request_payload: Mapping[str, Any],
        audio_bytes: bytes,
        audio_format: str,
        credential_handle: FastInteractionCredentialHandle,
        credential_value: str,
        adapter_request_id: str,
        timeout_ms: int,
        model_alias: str,
    ) -> str:
        return self.complete_audio_with_timing(
            request_payload=request_payload,
            audio_bytes=audio_bytes,
            audio_format=audio_format,
            credential_handle=credential_handle,
            credential_value=credential_value,
            adapter_request_id=adapter_request_id,
            timeout_ms=timeout_ms,
            model_alias=model_alias,
            turn_ingress_monotonic_ms=0,
        ).provider_text

    def complete_audio_with_timing(
        self,
        *,
        request_payload: Mapping[str, Any],
        audio_bytes: bytes,
        audio_format: str,
        credential_handle: FastInteractionCredentialHandle,
        credential_value: str,
        adapter_request_id: str,
        timeout_ms: int,
        model_alias: str,
        turn_ingress_monotonic_ms: int,
        now_ms: Callable[[], int] | None = None,
    ) -> FastInteractionProviderCompletion:
        timing = AdapterTimingRecorder(
            turn_ingress_monotonic_ms=turn_ingress_monotonic_ms,
            now_ms=now_ms,
        )
        timing.mark_adapter_started()
        _validate_credential_handle(credential_handle)
        _require_present_credential_value(credential_value)
        _require_safe_token(adapter_request_id, "adapter_request_id")
        _require_positive_int(timeout_ms, "timeout_ms")
        _require_safe_token(model_alias, "model_alias")
        _require_audio_bytes(audio_bytes)
        audio_format = _require_audio_format(audio_format)
        _reject_unsafe_request_payload(request_payload)

        request_body = _build_audio_request_body(
            model_alias=model_alias,
            request_payload=request_payload,
            audio_bytes=audio_bytes,
            audio_format=audio_format,
        )
        _store_model_io_request(
            adapter_request_id=adapter_request_id,
            model_alias=model_alias,
            request_body=request_body,
        )
        completion = self._complete_streaming_request_body_with_timing(
            request_body=request_body,
            credential_value=credential_value,
            timeout_ms=timeout_ms,
            timing=timing,
        )
        _store_model_io_response(
            adapter_request_id=adapter_request_id,
            provider_text=completion.provider_text,
        )
        return completion

    def _complete_streaming_request_body(
        self,
        *,
        request_body: Mapping[str, Any],
        credential_value: str,
        timeout_ms: int,
    ) -> str:
        timing = AdapterTimingRecorder(turn_ingress_monotonic_ms=0)
        timing.mark_adapter_started()
        return self._complete_streaming_request_body_with_timing(
            request_body=request_body,
            credential_value=credential_value,
            timeout_ms=timeout_ms,
            timing=timing,
        ).provider_text

    def _complete_streaming_request_body_with_timing(
        self,
        *,
        request_body: Mapping[str, Any],
        credential_value: str,
        timeout_ms: int,
        timing: AdapterTimingRecorder,
    ) -> FastInteractionProviderCompletion:
        request = urllib.request.Request(
            self._provider_url,
            data=json.dumps(request_body, separators=(",", ":"), sort_keys=True).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {credential_value}",
            },
            method="POST",
        )
        text_parts: list[str] = []
        first_content_chunk_seen = False
        try:
            timing.mark_provider_request_started()
            with self._opener.open(request, timeout=timeout_ms / 1000) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8").strip()
                    if line == "" or not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        break
                    chunk_payload = json.loads(data)
                    text_delta = _extract_stream_text_delta(chunk_payload)
                    if not first_content_chunk_seen and text_delta is not None and text_delta != "":
                        first_content_chunk_seen = True
                        timing.mark_provider_first_chunk()
                    if text_delta is not None:
                        text_parts.append(text_delta)
                timing.mark_provider_full_response()
        except TimeoutError:
            raise FastInteractionLiveTransportError(
                "provider timeout",
                category="provider_timeout",
                failure_reasons=("provider_timeout",),
            ) from None
        except urllib.error.HTTPError as exc:
            status_category = _http_status_class_category(exc.code)
            raise FastInteractionLiveTransportError(
                "provider request failed",
                category="provider_request_failed",
                failure_reasons=(
                    "provider_request_failed",
                    status_category,
                ),
            ) from None
        except urllib.error.URLError as exc:
            if isinstance(getattr(exc, "reason", None), TimeoutError):
                raise FastInteractionLiveTransportError(
                    "provider timeout",
                    category="provider_timeout",
                    failure_reasons=("provider_timeout",),
                ) from None
            raise FastInteractionLiveTransportError(
                "provider request failed",
                category="provider_request_failed",
                failure_reasons=("provider_request_failed",),
            ) from None
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise FastInteractionLiveTransportError(
                "provider response parse failed",
                category="provider_response_parse_failed",
                failure_reasons=("provider_response_parse_failed",),
            ) from None

        provider_text = "".join(text_parts)
        if provider_text == "":
            raise FastInteractionLiveTransportError(
                "provider response text missing",
                category="provider_response_text_missing",
                failure_reasons=(
                    "provider_response_text_missing",
                    "provider_response_stream_delta_content_missing",
                ),
            )
        return FastInteractionProviderCompletion(
            provider_text=provider_text,
            timing=timing.finish(parse_validate_emit_ms=0, stream_decode_ms=0),
        )

    def to_metadata(self) -> dict[str, Any]:
        return {
            "provider_transport": "direct_http",
            "provider_url_ref": FAST_INTERACTION_DASHSCOPE_PROVIDER_URL_REF,
            "audio_input_supported": True,
            "raw_provider_request_included": False,
            "raw_provider_response_included": False,
            "raw_audio_included": False,
            "audio_bytes_retained": False,
            "headers_included": False,
            "authorization_header_included": False,
            "secret_materialized": False,
        }


def _validate_credential_handle(
    credential_handle: object,
) -> FastInteractionCredentialHandle:
    if not isinstance(credential_handle, FastInteractionCredentialHandle):
        raise FastInteractionLiveTransportError(
            "credential_handle must be an opaque credential handle",
            category="credential_handle_invalid",
            failure_reasons=("credential_handle_invalid",),
        )
    _require_safe_ref(credential_handle.credential_ref, "credential_ref")
    return credential_handle


def _build_request_body(
    *,
    model_alias: str,
    request_payload: Mapping[str, Any],
) -> dict[str, Any]:
    user_payload = {
        "request_payload": deepcopy(dict(request_payload)),
        "required_output_skeleton": _required_output_skeleton(),
    }
    return {
        "model": model_alias,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(user_payload, separators=(",", ":"), sort_keys=True),
            },
        ],
        "stream": True,
        "stream_options": {"include_usage": True},
        "modalities": ["text"],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
        "max_tokens": 450,
    }


def _build_audio_request_body(
    *,
    model_alias: str,
    request_payload: Mapping[str, Any],
    audio_bytes: bytes,
    audio_format: str,
) -> dict[str, Any]:
    user_payload = {
        "request_payload": deepcopy(dict(request_payload)),
        "required_output_skeleton": _required_output_skeleton(),
        "input_audio_policy": {
            "primary_input": "audio_native",
            "raw_audio_retained": False,
            "metadata_only_debug": True,
        },
    }
    return {
        "model": model_alias,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
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
        "temperature": 0.2,
        "max_tokens": 450,
    }


def _required_output_skeleton() -> dict[str, Any]:
    return {
        "schema_name": "voice_agent.fast_interaction.output.v1",
        "route_hint": {},
        "route_prelude": {},
        "foreground_act": "ANSWER",
        "reply_candidate": "",
        "final_fast_evidence": {},
        "risk_tags": [],
        "risk_class": "LOW",
        "confidence": 0.0,
        "output_mode": "degraded",
        "boundary_assertions": {
            "candidate_is_not_semantic_commitment": True,
            "may_authorize_tools": False,
            "may_execute_tools": False,
            "may_accept_confirmation": False,
            "may_mutate_slowtask_facts": False,
            "runtime_gate_owns_display": True,
        },
    }


def _store_model_io_request(
    *,
    adapter_request_id: str,
    model_alias: str,
    request_body: Mapping[str, Any],
) -> None:
    _LOCAL_MODEL_IO_BY_ADAPTER_REQUEST_ID[adapter_request_id] = {
        "adapter": "fast_interaction",
        "adapter_request_id": adapter_request_id,
        "model_alias": model_alias,
        "provider_url_ref": FAST_INTERACTION_DASHSCOPE_PROVIDER_URL_REF,
        "local_only": True,
        "saved_to_history": False,
        "replay_included": False,
        "request_shape": _safe_request_shape(request_body),
        "provider_text_included": False,
        "provider_response_shape": None,
        "raw_audio_visible": False,
        "raw_provider_response_visible": False,
        "authorization_header_visible": False,
    }


def _store_model_io_response(
    *,
    adapter_request_id: str,
    provider_text: str,
) -> None:
    current = _LOCAL_MODEL_IO_BY_ADAPTER_REQUEST_ID.setdefault(
        adapter_request_id,
        {
            "adapter": "fast_interaction",
            "adapter_request_id": adapter_request_id,
            "provider_url_ref": FAST_INTERACTION_DASHSCOPE_PROVIDER_URL_REF,
            "local_only": True,
            "saved_to_history": False,
            "replay_included": False,
            "request_shape": None,
            "provider_text_included": False,
            "raw_audio_visible": False,
            "raw_provider_response_visible": False,
            "authorization_header_visible": False,
        },
    )
    current["provider_text_included"] = False
    current["provider_response_shape"] = _safe_provider_response_shape(provider_text)
    current["raw_provider_response_visible"] = False


def _extract_stream_text_delta(response_payload: Mapping[str, Any]) -> str | None:
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
                raise FastInteractionLiveTransportError(
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


def _require_present_credential_value(value: object) -> str:
    if not isinstance(value, str) or value == "":
        raise FastInteractionLiveTransportError(
            "credential value missing",
            category="credential_missing",
            failure_reasons=("credential_missing",),
        )
    return value


def _require_safe_ref(value: object, field: str) -> str:
    token = _require_safe_token(value, field)
    if "://" not in token:
        raise FastInteractionLiveTransportError(
            f"{field} must be a safe ref",
            category="unsafe_ref",
            failure_reasons=("unsafe_ref",),
        )
    return token


def _require_safe_token(value: object, field: str) -> str:
    if not isinstance(value, str) or value == "":
        raise FastInteractionLiveTransportError(
            f"{field} must be a non-empty string",
            category="invalid_field",
            failure_reasons=("invalid_field",),
        )
    _reject_unsafe_string(value)
    return value


def _require_positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise FastInteractionLiveTransportError(
            f"{field} must be a positive integer",
            category="invalid_budget",
            failure_reasons=("invalid_budget",),
        )
    return value


def _require_audio_bytes(value: object) -> bytes:
    if not isinstance(value, bytes) or value == b"":
        raise FastInteractionLiveTransportError(
            "audio_bytes must be non-empty bytes",
            category="audio_input_invalid",
            failure_reasons=("audio_input_invalid",),
        )
    return value


def _require_audio_format(value: object) -> str:
    token = _require_safe_token(value, "audio_format")
    if token not in {"wav", "mp3", "m4a", "ogg", "flac"}:
        raise FastInteractionLiveTransportError(
            "audio_format unsupported",
            category="audio_format_unsupported",
            failure_reasons=("audio_format_unsupported",),
        )
    return token


def _reject_unsafe_string(value: str) -> None:
    for variant in (value, unquote(value)):
        if CREDENTIAL_LIKE_REF_PATTERN.search(variant) or _REQUEST_SECRET_PATTERN.search(variant):
            raise FastInteractionLiveTransportError(
                "credential-like content",
                category="credential_like_content",
                failure_reasons=("credential_like_content",),
            )
        lowered = variant.lower()
        normalized = lowered.replace("-", "_").replace(" ", "_")
        if any(marker in lowered or marker in normalized for marker in _DISALLOWED_MARKERS):
            raise FastInteractionLiveTransportError(
                "local-only artifact or provider body reference",
                category="local_only_artifact_ref",
                failure_reasons=("local_only_artifact_ref",),
            )


def _safe_request_shape(request_body: Mapping[str, Any]) -> dict[str, Any]:
    messages = request_body.get("messages")
    message_roles: list[str] = []
    has_input_audio = False
    audio_format: str | None = None
    if isinstance(messages, Sequence) and not isinstance(messages, (str, bytes, bytearray)):
        for message in messages:
            if isinstance(message, Mapping) and isinstance(message.get("role"), str):
                message_roles.append(str(message["role"]))
            content = message.get("content") if isinstance(message, Mapping) else None
            if isinstance(content, Sequence) and not isinstance(content, (str, bytes, bytearray)):
                for part in content:
                    if not isinstance(part, Mapping) or part.get("type") != "input_audio":
                        continue
                    has_input_audio = True
                    input_audio = part.get("input_audio")
                    if isinstance(input_audio, Mapping) and isinstance(input_audio.get("format"), str):
                        audio_format = str(input_audio["format"])
    return {
        "model": request_body.get("model"),
        "response_format": deepcopy(request_body.get("response_format")),
        "modalities": deepcopy(request_body.get("modalities")),
        "stream": request_body.get("stream"),
        "stream_options": deepcopy(request_body.get("stream_options")),
        "max_tokens": request_body.get("max_tokens"),
        "temperature": request_body.get("temperature"),
        "message_count": len(message_roles),
        "message_roles": message_roles,
        "has_input_audio": has_input_audio,
        "audio_format": audio_format,
        "audio_bytes_included": False,
        "audio_base64_visible": False,
        "user_payload_included": False,
        "system_prompt_included": False,
        "raw_provider_request_included": False,
    }


def _safe_provider_response_shape(provider_text: str) -> dict[str, Any]:
    stripped = provider_text.strip()
    return {
        "text_present": provider_text != "",
        "text_char_count": len(provider_text),
        "json_object_like": stripped.startswith("{") and stripped.endswith("}"),
        "raw_provider_response_included": False,
    }


def _http_status_class_category(status_code: int | None) -> str:
    if isinstance(status_code, int):
        status_class = status_code // 100
        if status_class in {1, 2, 3, 4, 5}:
            return f"provider_http_status_class_{status_class}xx"
    return "provider_http_status_class_unknown"


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-") or "unknown"
