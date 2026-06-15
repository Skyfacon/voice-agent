from __future__ import annotations

import ast
import io
import json
from pathlib import Path
import urllib.error

import pytest

from voice_agent.adapters.asr_live_transport import (
    ASR_LIVE_DASHSCOPE_OPENAI_COMPATIBLE_CHAT_COMPLETIONS_URL,
    ASR_LIVE_DASHSCOPE_PROVIDER_URL_REF,
    ASR_LIVE_SELECTED_MODEL_ALIAS,
    AsrLiveCredentialHandle,
    DashScopeAsrLiveDirectHTTPTransport,
    DashScopeAsrLiveTransportError,
    resolve_asr_live_transcript_text_ref,
)


def test_direct_http_transport_builds_audio_request_without_sdk_or_raw_metadata() -> None:
    opener = _FakeHTTPOpener({"choices": [{"message": {"content": "synthetic transcript"}}]})
    transport = DashScopeAsrLiveDirectHTTPTransport(
        provider_url="https://example.invalid/compatible-mode/v1/chat/completions",
        opener=opener,
    )

    metadata = transport.transcribe(
        audio_payload=b"RIFF synthetic wav bytes",
        audio_mime_type="audio/wav",
        credential_handle=AsrLiveCredentialHandle(
            credential_ref="secret-ref://local/asr-live-eval/dashscope",
        ),
        credential_value="runtime-credential-value-for-test-only",
        adapter_request_id="adapter_request_asr_live_001",
        timeout_ms=30000,
        model_alias=ASR_LIVE_SELECTED_MODEL_ALIAS,
    ).to_metadata()

    assert opener.calls == [
        {
            "url": "https://example.invalid/compatible-mode/v1/chat/completions",
            "timeout": 30.0,
            "authorization_header_present": True,
        }
    ]
    request_body = opener.request_bodies[0]
    request_repr = repr(request_body)
    user_content = request_body["messages"][0]["content"][0]
    assert request_body["model"] == "qwen3-asr-flash"
    assert request_body["stream"] is False
    assert user_content["type"] == "input_audio"
    assert user_content["input_audio"]["format"] == "wav"
    assert str(user_content["input_audio"]["data"]).startswith(
        "data:audio/wav;base64,"
    )
    assert "runtime-credential-value-for-test-only" not in request_repr

    assert metadata == {
        "adapter_request_id": "adapter_request_asr_live_001",
        "provider_transport": "direct_http",
        "provider_url_ref": ASR_LIVE_DASHSCOPE_PROVIDER_URL_REF,
        "model_alias": "qwen3-asr-flash",
        "success": True,
        "transcript_present": True,
        "asr_frame_ref": "asr-frame://provider/dashscope/adapter_request_asr_live_001",
        "text_ref": "text://provider/dashscope/adapter_request_asr_live_001",
        "response_text_size_bucket": "small",
        "raw_audio_included": False,
        "raw_transcript_included": False,
        "raw_provider_request_included": False,
        "raw_provider_response_included": False,
        "headers_included": False,
        "authorization_header_included": False,
        "secret_included": False,
    }
    assert resolve_asr_live_transcript_text_ref(str(metadata["text_ref"])) == (
        "synthetic transcript"
    )
    assert "synthetic transcript" not in repr(metadata)
    assert "runtime-credential-value-for-test-only" not in repr(metadata)


def test_direct_http_transport_classifies_http_status_without_raw_body() -> None:
    transport = DashScopeAsrLiveDirectHTTPTransport(
        provider_url="https://example.invalid/compatible-mode/v1/chat/completions",
        opener=_RaisingHTTPOpener(
            urllib.error.HTTPError(
                url="https://example.invalid/compatible-mode/v1/chat/completions",
                code=429,
                msg="Too Many Requests",
                hdrs={},
                fp=io.BytesIO(b"raw_provider_body api_key=synthetic"),
            )
        ),
    )

    with pytest.raises(DashScopeAsrLiveTransportError) as captured:
        transport.transcribe(
            audio_payload=b"RIFF synthetic wav bytes",
            audio_mime_type="audio/wav",
            credential_handle=AsrLiveCredentialHandle(
                credential_ref="secret-ref://local/asr-live-eval/dashscope",
            ),
            credential_value="runtime-credential-value-for-test-only",
            adapter_request_id="adapter_request_asr_live_001",
            timeout_ms=30000,
            model_alias=ASR_LIVE_SELECTED_MODEL_ALIAS,
        )

    assert captured.value.failure_reasons == [
        "provider_request_failed",
        "provider_http_status_class_4xx",
    ]
    assert captured.value.retryable is False
    assert "raw_provider_body" not in repr(captured.value)
    assert "api_key" not in repr(captured.value).lower()
    assert "runtime-credential-value-for-test-only" not in repr(captured.value)


def test_direct_http_transport_classifies_timeout_as_retryable_redacted_failure() -> None:
    transport = DashScopeAsrLiveDirectHTTPTransport(
        provider_url="https://example.invalid/compatible-mode/v1/chat/completions",
        opener=_RaisingHTTPOpener(TimeoutError("synthetic timeout api_key=synthetic")),
    )

    with pytest.raises(DashScopeAsrLiveTransportError) as captured:
        transport.transcribe(
            audio_payload=b"RIFF synthetic wav bytes",
            audio_mime_type="audio/wav",
            credential_handle=AsrLiveCredentialHandle(
                credential_ref="secret-ref://local/asr-live-eval/dashscope",
            ),
            credential_value="runtime-credential-value-for-test-only",
            adapter_request_id="adapter_request_asr_live_001",
            timeout_ms=30000,
            model_alias=ASR_LIVE_SELECTED_MODEL_ALIAS,
        )

    assert captured.value.failure_reasons == ["provider_timeout"]
    assert captured.value.retryable is True
    assert captured.value.timeout is True
    assert "api_key" not in repr(captured.value).lower()


def test_direct_http_transport_classifies_response_shape_without_transcript_leak() -> None:
    transport = DashScopeAsrLiveDirectHTTPTransport(
        provider_url="https://example.invalid/compatible-mode/v1/chat/completions",
        opener=_FakeHTTPOpener(
            {
                "choices": [{"message": {"role": "assistant"}}],
                "raw_transcript": "forbidden transcript marker",
                "raw_provider_body": "forbidden body marker",
            }
        ),
    )

    with pytest.raises(DashScopeAsrLiveTransportError) as captured:
        transport.transcribe(
            audio_payload=b"RIFF synthetic wav bytes",
            audio_mime_type="audio/wav",
            credential_handle=AsrLiveCredentialHandle(
                credential_ref="secret-ref://local/asr-live-eval/dashscope",
            ),
            credential_value="runtime-credential-value-for-test-only",
            adapter_request_id="adapter_request_asr_live_001",
            timeout_ms=30000,
            model_alias=ASR_LIVE_SELECTED_MODEL_ALIAS,
        )

    assert captured.value.failure_reasons == [
        "provider_response_text_missing",
        "provider_response_shape_choices_message_content_missing",
        "provider_response_shape_output_text_missing",
    ]
    assert "forbidden transcript marker" not in repr(captured.value)
    assert "forbidden body marker" not in repr(captured.value)


def test_asr_live_transport_does_not_import_provider_sdk_or_requests() -> None:
    source = Path("src/voice_agent/adapters/asr_live_transport.py").read_text(
        encoding="utf-8"
    )
    imported_modules = _imported_modules(source)

    assert imported_modules.isdisjoint(
        {
            "dashscope",
            "requests",
            "http.client",
            "socket",
            "websocket",
            "websockets",
        }
    )
    assert ASR_LIVE_DASHSCOPE_OPENAI_COMPATIBLE_CHAT_COMPLETIONS_URL == (
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    )


class _FakeHTTPOpener:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.calls: list[dict[str, object]] = []
        self.request_bodies: list[dict[str, object]] = []

    def open(self, request: object, timeout: float) -> "_FakeHTTPResponse":
        self.calls.append(
            {
                "url": getattr(request, "full_url"),
                "timeout": timeout,
                "authorization_header_present": getattr(request, "has_header")(
                    "Authorization"
                ),
            }
        )
        self.request_bodies.append(
            json.loads(getattr(request, "data").decode("utf-8"))
        )
        return _FakeHTTPResponse(self._payload)


class _RaisingHTTPOpener:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def open(self, request: object, timeout: float) -> object:
        raise self._exc


class _FakeHTTPResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def _imported_modules(source: str) -> set[str]:
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported
