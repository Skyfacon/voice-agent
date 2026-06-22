from __future__ import annotations

import base64
import io
import json
import urllib.error

import pytest

from voice_agent.adapters.lalm_thinker_binding import bind_lalm_thinker_request
from voice_agent.adapters.lalm_thinker_prompt_rules import LALM_THINKER_ROUTING_OUTPUT_RULES
from voice_agent.adapters.lalm_thinker_live_transport import (
    LALMThinkerCredentialHandle,
    LALMThinkerLiveDirectHTTPTransport,
    LALMThinkerLiveTransportError,
    resolve_lalm_thinker_live_model_io_debug,
    validate_lalm_thinker_credential_handle,
)
from voice_agent.adapters.lalm_thinker_skeleton import (
    build_lalm_thinker_live_request_payload,
    fake_lalm_thinker_transport,
    request_lalm_thinker_provider_text,
)


def test_credential_handle_is_opaque_and_metadata_only() -> None:
    handle = LALMThinkerCredentialHandle(
        credential_ref="secret-ref://runtime-env/dashscope-api-key",
    )

    metadata = validate_lalm_thinker_credential_handle(handle).to_metadata()

    assert metadata == {
        "credential_ref": "secret-ref://runtime-env/dashscope-api-key",
        "credential_present": True,
        "credential_source": (
            "runtime_env_var:DASHSCOPE_API_KEY via ~/.voice-agent-secrets/dashscope.env"
        ),
        "credential_value_included": False,
        "secret_materialized": False,
    }
    assert "runtime-secret-value-for-test-only" not in repr(handle)
    assert "DASHSCOPE_API_KEY=" not in repr(handle)
    with pytest.raises(LALMThinkerLiveTransportError, match="opaque"):
        str(handle)


def test_request_provider_text_uses_fake_transport_without_network_or_sdk() -> None:
    binding = _binding()
    request_payload = build_lalm_thinker_live_request_payload(binding=binding)
    handle = LALMThinkerCredentialHandle(
        credential_ref="secret-ref://runtime-env/dashscope-api-key",
    )
    transport = _FakeTransport(fake_lalm_thinker_transport(binding, optional_refs_available=True))

    candidate = request_lalm_thinker_provider_text(
        transport=transport,
        credential_handle=handle,
        request_payload=request_payload,
        adapter_request_id=binding.adapter_request_id,
        timeout_ms=60_000,
        credential_value="runtime-secret-value-for-test-only",
        model_alias="qwen3.5-omni-plus",
    )

    assert candidate.adapter_request_id == binding.adapter_request_id
    assert candidate.output_mode == "real"
    assert candidate.to_metadata() == {
        "adapter_request_id": binding.adapter_request_id,
        "output_mode": "real",
        "text_present": True,
        "raw_provider_request_included": False,
        "raw_provider_response_included": False,
    }
    rendered_metadata = repr(candidate.to_metadata())
    assert "runtime-secret-value-for-test-only" not in rendered_metadata
    assert "Bearer " not in rendered_metadata
    assert "provider_text" not in rendered_metadata
    assert transport.calls == [
        {
            "adapter_request_id": binding.adapter_request_id,
            "timeout_ms": 60_000,
            "model_alias": "qwen3.5-omni-plus",
            "credential_handle_metadata": handle.to_metadata(),
        }
    ]


def test_direct_http_transport_uses_injected_opener_and_does_not_retain_raw_body() -> None:
    binding = _binding()
    expected_provider_text = fake_lalm_thinker_transport(
        binding,
        optional_refs_available=True,
    )
    response_payload = {
        "choices": [
            {
                "delta": {
                    "content": expected_provider_text,
                }
            }
        ]
    }
    opener = _CapturingOpener(response_lines=_streaming_response_lines(response_payload))
    transport = LALMThinkerLiveDirectHTTPTransport(opener=opener)

    provider_text = transport.complete(
        request_payload=build_lalm_thinker_live_request_payload(
            binding=binding,
            transient_input_text="turn on the desk lamp",
        ),
        credential_handle=LALMThinkerCredentialHandle(
            credential_ref="secret-ref://runtime-env/dashscope-api-key",
        ),
        credential_value="runtime-secret-value-for-test-only",
        adapter_request_id=binding.adapter_request_id,
        timeout_ms=60_000,
        model_alias="qwen3.5-omni-plus",
    )

    assert provider_text == expected_provider_text
    assert opener.timeout == 60
    captured_request = opener.request
    assert captured_request is not None
    assert captured_request.full_url.endswith("/compatible-mode/v1/chat/completions")
    assert captured_request.get_header("Authorization") == (
        "Bearer runtime-secret-value-for-test-only"
    )
    request_body = json.loads(captured_request.data.decode("utf-8"))
    assert request_body["model"] == "qwen3.5-omni-plus"
    assert request_body["stream"] is True
    assert request_body["stream_options"] == {"include_usage": True}
    assert request_body["modalities"] == ["text"]
    assert request_body["response_format"] == {"type": "json_object"}
    assert request_body["messages"][0]["role"] == "system"
    assert request_body["messages"][1]["role"] == "user"
    assert "lalm_thinker_semantic_frame_candidate.v1" in request_body["messages"][0]["content"]
    assert "Do not wrap JSON in markdown" in request_body["messages"][0]["content"]
    assert "tool_calls" in request_body["messages"][0]["content"]
    assert "Example: 讲冷笑话 -> FOREGROUND_CHAT" in request_body["messages"][0]["content"]
    assert (
        "Example: 帮我规划一个三天旅行并列步骤 -> NEW_TASK_CANDIDATE"
        in request_body["messages"][0]["content"]
    )
    user_payload = json.loads(request_body["messages"][1]["content"])
    skeleton = user_payload["required_output_skeleton"]
    assert "semantic_frame_ref" not in skeleton
    assert "semantic_summary_ref" not in skeleton
    assert skeleton["semantic_frame_hint"] == {
        "status": "available",
        "label": "semantic_frame_available",
    }
    assert skeleton["semantic_summary_hint"] == {
        "status": "available",
        "label": "semantic_summary_available",
    }
    assert skeleton["task_focus_hint"] == {
        "focus": "AMBIGUOUS",
        "task_like": False,
        "complexity_hint": "unknown",
        "focus_confidence": 0.5,
        "evidence_uncertainty": "high",
    }
    assert user_payload["output_rules"] == list(LALM_THINKER_ROUTING_OUTPUT_RULES)
    assert user_payload["request_payload"]["transient_input_evidence"] == {
        "input_modality": "text",
        "input_ref": "text://synthetic/lalm-thinker/live-001",
        "retention": "transient_adapter_memory_only",
        "event_journal_retention": False,
        "summary_retention": False,
        "text": {
            "present": True,
            "content": "turn on the desk lamp",
            "max_chars": 1000,
        },
    }
    assert "raw_provider_request" not in repr(request_body)
    assert "runtime-secret-value-for-test-only" not in repr(request_body)
    model_io = resolve_lalm_thinker_live_model_io_debug(binding.adapter_request_id)
    assert model_io is not None
    assert model_io["adapter"] == "thinker"
    assert "lalm_thinker_semantic_frame_candidate.v1" in model_io["system_message"]
    assert model_io["request_body"]["response_format"] == {"type": "json_object"}
    assert model_io["provider_text"] == expected_provider_text
    assert model_io["raw_audio_visible"] is False
    assert model_io["authorization_header_visible"] is False
    assert "runtime-secret-value-for-test-only" not in repr(model_io)

    metadata = transport.to_metadata()
    assert metadata == {
        "provider_transport": "direct_http",
        "provider_url_ref": (
            "provider-url://dashscope/openai-compatible-chat-completions"
        ),
        "audio_input_supported": True,
        "raw_provider_request_included": False,
        "raw_provider_response_included": False,
        "raw_audio_included": False,
        "audio_bytes_retained": False,
        "headers_included": False,
        "authorization_header_included": False,
        "secret_materialized": False,
    }
    assert "runtime-secret-value-for-test-only" not in repr(metadata)
    assert "Bearer " not in repr(metadata)


def test_direct_http_transport_audio_uses_input_audio_without_retaining_raw_audio() -> None:
    binding = _audio_binding()
    expected_provider_text = fake_lalm_thinker_transport(
        binding,
        optional_refs_available=True,
    )
    response_payload = {
        "choices": [
            {
                "delta": {
                    "content": expected_provider_text,
                }
            }
        ]
    }
    opener = _CapturingOpener(response_lines=_streaming_response_lines(response_payload))
    transport = LALMThinkerLiveDirectHTTPTransport(opener=opener)
    audio_bytes = b"synthetic-test-audio-bytes"

    provider_text = transport.complete_audio(
        request_payload=build_lalm_thinker_live_request_payload(binding=binding),
        audio_bytes=audio_bytes,
        audio_format="wav",
        credential_handle=LALMThinkerCredentialHandle(
            credential_ref="secret-ref://runtime-env/dashscope-api-key",
        ),
        credential_value="runtime-secret-value-for-test-only",
        adapter_request_id=binding.adapter_request_id,
        timeout_ms=60_000,
        model_alias="qwen3.5-omni-plus",
    )

    assert provider_text == expected_provider_text
    captured_request = opener.request
    assert captured_request is not None
    request_body = json.loads(captured_request.data.decode("utf-8"))
    assert request_body["model"] == "qwen3.5-omni-plus"
    assert request_body["stream"] is True
    assert request_body["stream_options"] == {"include_usage": True}
    assert request_body["modalities"] == ["text"]
    assert request_body["response_format"] == {"type": "json_object"}
    user_content = request_body["messages"][1]["content"]
    assert [part["type"] for part in user_content] == ["text", "input_audio"]
    expected_audio_data_url = f"data:;base64,{base64.b64encode(audio_bytes).decode('ascii')}"
    assert user_content[1] == {
        "type": "input_audio",
        "input_audio": {
            "data": expected_audio_data_url,
            "format": "wav",
        },
    }
    user_payload = json.loads(user_content[0]["text"])
    assert user_payload["required_output_skeleton"]["request_binding"] == binding.to_dict()
    assert (
        "do not answer or chat with the user; classify the utterance as routing evidence only"
        in user_payload["output_rules"]
    )
    model_io = resolve_lalm_thinker_live_model_io_debug(binding.adapter_request_id)
    assert model_io is not None
    assert model_io["request_body"]["messages"][1]["content"][1]["input_audio"]["data"] == (
        "[redacted-audio-base64]"
    )
    assert model_io["provider_text"] == expected_provider_text
    assert base64.b64encode(audio_bytes).decode("ascii") not in repr(model_io)
    metadata = transport.to_metadata()
    assert metadata["audio_input_supported"] is True
    assert metadata["raw_audio_included"] is False
    assert metadata["audio_bytes_retained"] is False
    rendered_metadata = repr(metadata)
    assert expected_audio_data_url not in rendered_metadata
    assert "runtime-secret-value-for-test-only" not in rendered_metadata
    assert "Bearer " not in rendered_metadata


def test_direct_http_transport_maps_http_errors_to_safe_categories() -> None:
    opener = _RaisingOpener(
        urllib.error.HTTPError(
            url="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            code=429,
            msg="rate limited",
            hdrs={},
            fp=io.BytesIO(b'{"raw":"provider body must not leak"}'),
        )
    )
    transport = LALMThinkerLiveDirectHTTPTransport(opener=opener)

    with pytest.raises(LALMThinkerLiveTransportError) as captured:
        transport.complete(
            request_payload=build_lalm_thinker_live_request_payload(binding=_binding()),
            credential_handle=LALMThinkerCredentialHandle(
                credential_ref="secret-ref://runtime-env/dashscope-api-key",
            ),
            credential_value="runtime-secret-value-for-test-only",
            adapter_request_id="adapter-request-lalm-thinker-001",
            timeout_ms=60_000,
            model_alias="qwen3.5-omni-plus",
        )

    assert captured.value.category == "provider_request_failed"
    assert captured.value.failure_reasons == (
        "provider_request_failed",
        "provider_http_status_class_4xx",
    )
    assert "provider body" not in str(captured.value)
    assert "runtime-secret-value-for-test-only" not in str(captured.value)


def test_direct_http_transport_rejects_missing_credential_before_request() -> None:
    opener = _CapturingOpener(response_payload={"choices": []})
    transport = LALMThinkerLiveDirectHTTPTransport(opener=opener)

    with pytest.raises(LALMThinkerLiveTransportError) as captured:
        transport.complete(
            request_payload=build_lalm_thinker_live_request_payload(binding=_binding()),
            credential_handle=LALMThinkerCredentialHandle(
                credential_ref="secret-ref://runtime-env/dashscope-api-key",
            ),
            credential_value="",
            adapter_request_id="adapter-request-lalm-thinker-001",
            timeout_ms=60_000,
            model_alias="qwen3.5-omni-plus",
        )

    assert captured.value.category == "credential_missing"
    assert opener.request is None


class _FakeTransport:
    def __init__(self, provider_text: str) -> None:
        self._provider_text = provider_text
        self.calls: list[dict[str, object]] = []

    def complete(
        self,
        *,
        request_payload: object,
        credential_handle: LALMThinkerCredentialHandle,
        credential_value: str,
        adapter_request_id: str,
        timeout_ms: int,
        model_alias: str,
    ) -> str:
        assert isinstance(request_payload, dict)
        self.calls.append(
            {
                "adapter_request_id": adapter_request_id,
                "timeout_ms": timeout_ms,
                "model_alias": model_alias,
                "credential_handle_metadata": credential_handle.to_metadata(),
            }
        )
        assert credential_value == "runtime-secret-value-for-test-only"
        return self._provider_text


class _CapturingOpener:
    def __init__(
        self,
        *,
        response_payload: object | None = None,
        response_lines: tuple[bytes, ...] | None = None,
    ) -> None:
        self._response_payload = response_payload
        self._response_lines = response_lines
        self.request: object | None = None
        self.timeout: float | None = None

    def open(self, request: object, timeout: float) -> object:
        self.request = request
        self.timeout = timeout
        return _FakeResponse(self._response_payload, self._response_lines)


class _RaisingOpener:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def open(self, request: object, timeout: float) -> object:
        raise self._exc


class _FakeResponse:
    def __init__(self, payload: object | None, lines: tuple[bytes, ...] | None) -> None:
        self._payload = payload
        self._lines = lines

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def read(self) -> bytes:
        assert self._payload is not None
        return json.dumps(self._payload).encode("utf-8")

    def __iter__(self) -> object:
        assert self._lines is not None
        return iter(self._lines)


def _streaming_response_lines(response_payload: object) -> tuple[bytes, ...]:
    return (
        f"data: {json.dumps(response_payload, separators=(',', ':'))}\n\n".encode("utf-8"),
        b"data: [DONE]\n\n",
    )


def _binding() -> object:
    return bind_lalm_thinker_request(
        turn_committed_event={
            "event_name": "TURN_INGRESS_COMMITTED",
            "event_id": "evt_turn_committed_text_001",
            "turn_id": "turn_text_001",
            "utterance_id": "utt_text_001",
            "input_modality": "text",
            "input_span_id": "input_text_001",
            "text_span_id": "text_span_001",
        },
        adapter_request_id="adapter-request-lalm-thinker-001",
        request_metadata_ref="request-metadata://synthetic/lalm-thinker/live-001",
        input_ref="text://synthetic/lalm-thinker/live-001",
        policy_ref="policy://synthetic/lalm-thinker/evidence-only",
    )


def _audio_binding() -> object:
    return bind_lalm_thinker_request(
        turn_committed_event={
            "event_name": "TURN_INGRESS_COMMITTED",
            "event_id": "evt_turn_committed_audio_001",
            "turn_id": "turn_audio_001",
            "utterance_id": "utt_audio_001",
            "input_modality": "audio",
            "input_span_id": "input_audio_001",
            "audio_span_id": "audio_span_001",
        },
        adapter_request_id="adapter-request-lalm-thinker-audio-001",
        request_metadata_ref="request-metadata://synthetic/lalm-thinker/audio-live-001",
        input_ref="audio://synthetic/lalm-thinker/audio-live-001",
        policy_ref="policy://synthetic/lalm-thinker/evidence-only",
    )
