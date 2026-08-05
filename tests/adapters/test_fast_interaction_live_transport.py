from __future__ import annotations

import base64
import json
import urllib.error

import pytest

from voice_agent.adapters.fast_interaction_live_transport import (
    FAST_INTERACTION_DASHSCOPE_OPENAI_COMPATIBLE_CHAT_COMPLETIONS_URL,
    FAST_INTERACTION_DASHSCOPE_PROVIDER_URL_REF,
    FastInteractionCredentialHandle,
    FastInteractionLiveDirectHTTPTransport,
    FastInteractionLiveTransportError,
    resolve_fast_interaction_model_io_debug,
)


def test_direct_http_transport_builds_text_only_json_request_and_redacted_debug() -> None:
    provider_text = json.dumps(_provider_output(), separators=(",", ":"), sort_keys=True)
    opener = _CapturingOpener(
        response_lines=[
            b"data: "
            + json.dumps({"choices": [{"delta": {"content": provider_text[:40]}}]}).encode("utf-8")
            + b"\n",
            b"data: "
            + json.dumps({"choices": [{"message": {"content": provider_text[40:]}}]}).encode("utf-8")
            + b"\n",
            b"data: [DONE]\n",
        ]
    )
    transport = FastInteractionLiveDirectHTTPTransport(opener=opener)
    handle = FastInteractionCredentialHandle(
        credential_ref="secret-ref://runtime-env/dashscope-api-key",
    )

    returned_text = transport.complete(
        request_payload={
            "turn_id": "turn_fast_interaction_live_001",
            "utterance_id": "utt_fast_interaction_live_001",
            "input_modality": "audio",
            "asr_output_event_id": "evt_fast_interaction_live_asr_output",
            "text_ref": "text://synthetic/fast-interaction/live-001",
            "redacted_transcript": "tell me a tiny story",
        },
        credential_handle=handle,
        credential_value="runtime-secret-value-for-test-only",
        adapter_request_id="adapter_request_fast_interaction_live_001",
        timeout_ms=1500,
        model_alias="qwen3.5-omni-flash",
    )

    assert returned_text == provider_text
    assert opener.timeout == 1.5
    assert opener.request is not None
    assert opener.request.full_url == FAST_INTERACTION_DASHSCOPE_OPENAI_COMPATIBLE_CHAT_COMPLETIONS_URL
    assert opener.request.get_header("Authorization") == "Bearer runtime-secret-value-for-test-only"
    request_body = json.loads(opener.request.data.decode("utf-8"))
    assert request_body["model"] == "qwen3.5-omni-flash"
    assert request_body["stream"] is True
    assert request_body["stream_options"] == {"include_usage": True}
    assert request_body["modalities"] == ["text"]
    assert request_body["response_format"] == {"type": "json_object"}
    assert request_body["temperature"] == 0.2
    assert request_body["max_tokens"] == 450
    assert request_body["messages"][0]["role"] == "system"
    system_prompt = request_body["messages"][0]["content"]
    assert "Fast Interaction" in system_prompt
    assert "no markdown" in system_prompt
    assert "no tools" in system_prompt
    assert "runtime gate owns display" in system_prompt
    assert request_body["messages"][1]["role"] == "user"
    assert isinstance(request_body["messages"][1]["content"], str)
    user_payload = json.loads(request_body["messages"][1]["content"])
    assert user_payload["request_payload"]["text_ref"] == "text://synthetic/fast-interaction/live-001"
    skeleton = user_payload["required_output_skeleton"]
    assert skeleton["schema_name"] == "voice_agent.fast_interaction.output.v1"
    assert skeleton["route_hint"] == {}
    assert skeleton["route_prelude"] == {}
    assert skeleton["foreground_act"] == "ANSWER"
    assert skeleton["reply_candidate"] == ""
    assert skeleton["final_fast_evidence"] == {}
    assert skeleton["risk_tags"] == []
    assert skeleton["risk_class"] == "LOW"
    assert skeleton["confidence"] == 0.0
    assert skeleton["output_mode"] == "degraded"
    assert skeleton["boundary_assertions"] == {
        "candidate_is_not_semantic_commitment": True,
        "may_authorize_tools": False,
        "may_execute_tools": False,
        "may_accept_confirmation": False,
        "may_mutate_slowtask_facts": False,
        "runtime_gate_owns_display": True,
    }
    assert "raw_provider_request" not in repr(request_body)
    assert "runtime-secret-value-for-test-only" not in repr(request_body)

    debug = resolve_fast_interaction_model_io_debug("adapter_request_fast_interaction_live_001")
    assert debug is not None
    assert debug["adapter"] == "fast_interaction"
    assert debug["provider_url_ref"] == FAST_INTERACTION_DASHSCOPE_PROVIDER_URL_REF
    assert debug["request_shape"] == {
        "model": "qwen3.5-omni-flash",
        "response_format": {"type": "json_object"},
        "modalities": ["text"],
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_tokens": 450,
        "temperature": 0.2,
        "message_count": 2,
        "message_roles": ["system", "user"],
        "has_input_audio": False,
        "audio_format": None,
        "audio_bytes_included": False,
        "audio_base64_visible": False,
        "user_payload_included": False,
        "system_prompt_included": False,
        "raw_provider_request_included": False,
    }
    assert debug["local_only"] is True
    assert debug["saved_to_history"] is False
    assert debug["replay_included"] is False
    assert "request_body" not in debug
    assert "system_message" not in debug
    assert "tell me a tiny story" not in repr(debug)
    assert "provider_text" not in debug
    assert debug["provider_text_included"] is False
    assert debug["provider_response_shape"] == {
        "text_present": True,
        "text_char_count": len(provider_text),
        "json_object_like": True,
        "raw_provider_response_included": False,
    }
    assert provider_text not in repr(debug)
    assert "A tiny safe story." not in repr(debug)
    assert debug["raw_audio_visible"] is False
    assert debug["raw_provider_response_visible"] is False
    assert debug["authorization_header_visible"] is False
    assert "runtime-secret-value-for-test-only" not in repr(debug)
    assert "Authorization" not in repr(debug)

    metadata = transport.to_metadata()
    assert metadata == {
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
    assert "runtime-secret-value-for-test-only" not in repr(metadata)
    assert "Bearer " not in repr(metadata)


def test_complete_audio_with_timing_builds_audio_native_request_and_records_ttft() -> None:
    provider_text = json.dumps(_provider_output(), separators=(",", ":"), sort_keys=True)
    audio_bytes = b"RIFF0000WAVE"
    audio_base64 = base64.b64encode(audio_bytes).decode("ascii")
    opener = _CapturingOpener(
        response_lines=[
            b"data: "
            + json.dumps({"choices": [{"delta": {"content": provider_text[:12]}}]}).encode(
                "utf-8"
            )
            + b"\n",
            b"data: "
            + json.dumps({"choices": [{"delta": {"content": provider_text[12:]}}]}).encode(
                "utf-8"
            )
            + b"\n",
            b"data: [DONE]\n",
        ]
    )
    transport = FastInteractionLiveDirectHTTPTransport(opener=opener)
    fake_clock = _SequenceClock((1000, 1000, 1020, 1050, 1050))

    result = transport.complete_audio_with_timing(
        request_payload={"turn_ref": "turn://synthetic/mvp63/audio"},
        audio_bytes=audio_bytes,
        audio_format="wav",
        credential_handle=FastInteractionCredentialHandle("secret-ref://runtime/dashscope"),
        credential_value="synthetic-key",
        adapter_request_id="adapter_request_fast_audio_native",
        timeout_ms=8000,
        model_alias="qwen-audio-fast-interaction",
        turn_ingress_monotonic_ms=1000,
        now_ms=fake_clock,
    )

    assert result.provider_text.startswith("{")
    assert result.provider_text == provider_text
    assert result.timing.provider_ttft_ms == 20
    assert result.timing.provider_full_response_ms == 50
    assert result.timing.provider_generation_ms == 30
    assert result.timing.stream_decode_ms == 0
    assert result.timing.parse_validate_emit_ms == 0
    assert transport.to_metadata()["audio_input_supported"] is True
    assert opener.timeout == 8
    assert opener.request is not None
    request_body = json.loads(opener.request.data.decode("utf-8"))
    assert request_body["model"] == "qwen-audio-fast-interaction"
    assert request_body["stream"] is True
    assert request_body["response_format"] == {"type": "json_object"}
    assert request_body["modalities"] == ["text"]
    assert request_body["messages"][0]["role"] == "system"
    assert "voice_agent.fast_interaction.output.v1" in request_body["messages"][0]["content"]
    user_content = request_body["messages"][1]["content"]
    assert [part["type"] for part in user_content] == ["text", "input_audio"]
    assert user_content[1] == {
        "type": "input_audio",
        "input_audio": {
            "data": f"data:;base64,{audio_base64}",
            "format": "wav",
        },
    }
    user_payload = json.loads(user_content[0]["text"])
    assert user_payload["request_payload"] == {"turn_ref": "turn://synthetic/mvp63/audio"}
    assert user_payload["required_output_skeleton"]["schema_name"] == (
        "voice_agent.fast_interaction.output.v1"
    )

    debug = resolve_fast_interaction_model_io_debug("adapter_request_fast_audio_native")
    assert debug is not None
    assert debug["request_shape"] == {
        "model": "qwen-audio-fast-interaction",
        "response_format": {"type": "json_object"},
        "modalities": ["text"],
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_tokens": 450,
        "temperature": 0.2,
        "message_count": 2,
        "message_roles": ["system", "user"],
        "has_input_audio": True,
        "audio_format": "wav",
        "audio_bytes_included": False,
        "audio_base64_visible": False,
        "user_payload_included": False,
        "system_prompt_included": False,
        "raw_provider_request_included": False,
    }
    rendered_debug = repr(debug)
    assert "RIFF0000WAVE" not in rendered_debug
    assert audio_base64 not in rendered_debug
    assert provider_text not in rendered_debug
    assert "A tiny safe story." not in rendered_debug
    assert "synthetic-key" not in rendered_debug
    assert "Authorization" not in rendered_debug
    assert "request_body" not in debug
    assert "provider_text" not in debug
    assert debug["provider_text_included"] is False
    assert debug["provider_response_shape"]["text_char_count"] == len(provider_text)
    assert debug["saved_to_history"] is False
    assert debug["replay_included"] is False


def test_complete_with_timing_records_ttft_from_message_content_first_chunk() -> None:
    provider_text = json.dumps(_provider_output(), separators=(",", ":"), sort_keys=True)
    opener = _CapturingOpener(
        response_lines=[
            b"data: "
            + json.dumps({"choices": [{"message": {"content": provider_text}}]}).encode(
                "utf-8"
            )
            + b"\n",
            b"data: [DONE]\n",
        ]
    )
    transport = FastInteractionLiveDirectHTTPTransport(opener=opener)

    result = transport.complete_with_timing(
        request_payload={"text_ref": "text://synthetic/fast-interaction/message-ttft"},
        credential_handle=FastInteractionCredentialHandle("secret-ref://runtime/dashscope"),
        credential_value="synthetic-key",
        adapter_request_id="adapter_request_fast_message_ttft",
        timeout_ms=8000,
        model_alias="qwen-fast-interaction",
        turn_ingress_monotonic_ms=1000,
        now_ms=_SequenceClock((1000, 1000, 1020, 1050, 1050)),
    )

    assert result.provider_text == provider_text
    assert result.timing.provider_ttft_ms == 20
    assert result.timing.ttft_available is True


def test_complete_audio_rejects_credential_like_payload_before_opener_is_called() -> None:
    opener = _CapturingOpener(
        response_lines=[
            b"data: "
            + json.dumps({"choices": [{"delta": {"content": json.dumps(_provider_output())}}]}).encode(
                "utf-8"
            )
            + b"\n",
            b"data: [DONE]\n",
        ]
    )
    transport = FastInteractionLiveDirectHTTPTransport(opener=opener)

    with pytest.raises(FastInteractionLiveTransportError) as exc_info:
        transport.complete_audio_with_timing(
            request_payload={
                "turn_ref": "turn://synthetic/mvp63/audio",
                "credential_hint": "api_key=SHOULD_NOT_LEAK",
            },
            audio_bytes=b"RIFF0000WAVE",
            audio_format="wav",
            credential_handle=FastInteractionCredentialHandle("secret-ref://runtime/dashscope"),
            credential_value="synthetic-key",
            adapter_request_id="adapter_request_fast_audio_rejected",
            timeout_ms=8000,
            model_alias="qwen-audio-fast-interaction",
            turn_ingress_monotonic_ms=1000,
            now_ms=_SequenceClock((1000,)),
        )

    assert exc_info.value.category == "credential_like_content"
    assert opener.request is None


def test_transport_timeout_maps_to_safe_category_and_repr_excludes_secret_or_body() -> None:
    transport = FastInteractionLiveDirectHTTPTransport(
        opener=_RaisingOpener(TimeoutError("raw body runtime-secret-value-for-test-only"))
    )

    with pytest.raises(FastInteractionLiveTransportError) as exc_info:
        transport.complete(
            request_payload={"text_ref": "text://synthetic/fast-interaction/timeout"},
            credential_handle=FastInteractionCredentialHandle(
                credential_ref="secret-ref://runtime-env/dashscope-api-key",
            ),
            credential_value="runtime-secret-value-for-test-only",
            adapter_request_id="adapter_request_fast_interaction_timeout",
            timeout_ms=10,
            model_alias="qwen3.5-omni-flash",
        )

    exc = exc_info.value
    assert exc.category == "provider_timeout"
    assert exc.failure_reasons == ("provider_timeout",)
    assert exc.__cause__ is None
    assert exc.__suppress_context__ is True
    rendered = repr(exc)
    assert "provider_timeout" in rendered
    assert "runtime-secret-value-for-test-only" not in rendered
    assert "raw body" not in rendered
    assert "Bearer " not in rendered


def test_process_local_debug_does_not_expose_provider_text_with_secret_token_suffixes() -> None:
    provider_text = json.dumps(
        {
            **_provider_output(),
            "reply_candidate": (
                "Bearer SECRET_BEARER api_key=SECRET_API token=SECRET_TOKEN "
                "authorization: SECRET_AUTH cookie: SECRET_COOKIE"
            ),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    opener = _CapturingOpener(
        response_lines=[
            b"data: "
            + json.dumps({"choices": [{"delta": {"content": provider_text}}]}).encode("utf-8")
            + b"\n",
            b"data: [DONE]\n",
        ]
    )

    transport = FastInteractionLiveDirectHTTPTransport(opener=opener)
    transport.complete(
        request_payload={"text_ref": "text://synthetic/fast-interaction/redaction"},
        credential_handle=FastInteractionCredentialHandle(
            credential_ref="secret-ref://runtime-env/dashscope-api-key",
        ),
        credential_value="runtime-secret-value-for-test-only",
        adapter_request_id="adapter_request_fast_interaction_redaction",
        timeout_ms=1500,
        model_alias="qwen3.5-omni-flash",
    )

    debug = resolve_fast_interaction_model_io_debug("adapter_request_fast_interaction_redaction")
    assert debug is not None
    rendered = repr(debug)
    assert "provider_text" not in debug
    assert debug["provider_text_included"] is False
    assert debug["provider_response_shape"]["text_char_count"] == len(provider_text)
    assert "SECRET_BEARER" not in rendered
    assert "SECRET_API" not in rendered
    assert "SECRET_TOKEN" not in rendered
    assert "SECRET_AUTH" not in rendered
    assert "SECRET_COOKIE" not in rendered
    assert "Bearer SECRET" not in rendered
    assert "api_key=SECRET" not in rendered
    assert "token=SECRET" not in rendered
    assert "authorization: SECRET" not in rendered
    assert "cookie: SECRET" not in rendered


def test_process_local_debug_does_not_expose_colon_and_password_secret_shapes() -> None:
    provider_text = json.dumps(
        {
            **_provider_output(),
            "reply_candidate": (
                "api-key: SECRET_API_DASH authorization=SECRET_AUTH_EQ "
                "credential: SECRET_CREDENTIAL password=SECRET_PASSWORD "
                "cookie=SECRET_COOKIE_EQ sk-SECRET_KEY_MATERIAL"
            ),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    opener = _CapturingOpener(
        response_lines=[
            b"data: "
            + json.dumps({"choices": [{"delta": {"content": provider_text}}]}).encode("utf-8")
            + b"\n",
            b"data: [DONE]\n",
        ]
    )

    transport = FastInteractionLiveDirectHTTPTransport(opener=opener)
    transport.complete(
        request_payload={"text_ref": "text://synthetic/fast-interaction/redaction-shapes"},
        credential_handle=FastInteractionCredentialHandle(
            credential_ref="secret-ref://runtime-env/dashscope-api-key",
        ),
        credential_value="runtime-secret-value-for-test-only",
        adapter_request_id="adapter_request_fast_interaction_redaction_shapes",
        timeout_ms=1500,
        model_alias="qwen3.5-omni-flash",
    )

    debug = resolve_fast_interaction_model_io_debug(
        "adapter_request_fast_interaction_redaction_shapes"
    )
    assert debug is not None
    rendered = repr(debug)
    assert "provider_text" not in debug
    assert debug["provider_text_included"] is False
    assert debug["provider_response_shape"]["text_char_count"] == len(provider_text)
    assert "SECRET_API_DASH" not in rendered
    assert "SECRET_AUTH_EQ" not in rendered
    assert "SECRET_CREDENTIAL" not in rendered
    assert "SECRET_PASSWORD" not in rendered
    assert "SECRET_COOKIE_EQ" not in rendered
    assert "SECRET_KEY_MATERIAL" not in rendered
    assert "api-key: SECRET" not in rendered
    assert "authorization=SECRET" not in rendered
    assert "credential: SECRET" not in rendered
    assert "password=SECRET" not in rendered
    assert "cookie=SECRET" not in rendered
    assert "sk-SECRET" not in rendered


@pytest.mark.parametrize(
    ("unsafe_value", "expected_category", "safe_suffix"),
    (
        ("raw-prompt leaked", "local_only_artifact_ref", "raw_prompt"),
        ("provider-schema://internal", "local_only_artifact_ref", "provider_schema"),
        ("provider-payload://internal", "local_only_artifact_ref", "provider_payload"),
        ("provider-text://internal", "local_only_artifact_ref", "provider_text"),
        ("file://Users/a123/.env", "local_only_artifact_ref", "file_ref"),
        ("/Users/a123/voice-agent/.env", "local_only_artifact_ref", "users_path"),
        ("/private/tmp/trace.jsonl", "local_only_artifact_ref", "private_path"),
        ("token: SECRET_TOKEN", "credential_like_content", "token_colon"),
        ("api-key: SECRET_API", "credential_like_content", "api_key_colon"),
    ),
)
def test_transport_rejects_normalized_provider_and_local_artifact_markers(
    unsafe_value: str,
    expected_category: str,
    safe_suffix: str,
) -> None:
    opener = _CapturingOpener(
        response_lines=[
            b"data: "
            + json.dumps({"choices": [{"delta": {"content": json.dumps(_provider_output())}}]}).encode(
                "utf-8"
            )
            + b"\n",
            b"data: [DONE]\n",
        ]
    )
    transport = FastInteractionLiveDirectHTTPTransport(
        opener=opener
    )

    with pytest.raises(FastInteractionLiveTransportError) as exc_info:
        transport.complete(
            request_payload={
                "text_ref": "text://synthetic/fast-interaction/unsafe-marker",
                "redacted_transcript": unsafe_value,
            },
            credential_handle=FastInteractionCredentialHandle(
                credential_ref="secret-ref://runtime-env/dashscope-api-key",
            ),
            credential_value="runtime-secret-value-for-test-only",
            adapter_request_id=f"adapter_request_fast_interaction_unsafe_{safe_suffix}",
            timeout_ms=1500,
            model_alias="qwen3.5-omni-flash",
        )

    assert exc_info.value.category == expected_category
    assert opener.request is None


def test_transport_provider_failures_use_safe_categories_without_unsafe_causes() -> None:
    for index, (opener, category) in enumerate((
        (_RaisingOpener(urllib.error.URLError("raw body token=SECRET_TOKEN")), "provider_request_failed"),
        (
            _RaisingOpener(
                urllib.error.HTTPError(
                    url="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                    code=500,
                    msg="raw body token=SECRET_TOKEN",
                    hdrs={},
                    fp=None,
                )
            ),
            "provider_request_failed",
        ),
        (_CapturingOpener(response_lines=[b"data: {not-json token=SECRET_TOKEN}\n"]), "provider_response_parse_failed"),
        (_CapturingOpener(response_lines=[b"data: {\"choices\":[{\"delta\":{}}]}\n", b"data: [DONE]\n"]), "provider_response_text_missing"),
    )):
        transport = FastInteractionLiveDirectHTTPTransport(opener=opener)
        with pytest.raises(FastInteractionLiveTransportError) as exc_info:
            transport.complete(
                request_payload={"text_ref": "text://synthetic/fast-interaction/error"},
                credential_handle=FastInteractionCredentialHandle(
                    credential_ref="secret-ref://runtime-env/dashscope-api-key",
                ),
                credential_value="runtime-secret-value-for-test-only",
                adapter_request_id=f"adapter_request_fast_interaction_error_{index}",
                timeout_ms=10,
                model_alias="qwen3.5-omni-flash",
            )
        assert exc_info.value.category == category
        assert exc_info.value.__cause__ is None
        if category != "provider_response_text_missing":
            assert exc_info.value.__suppress_context__ is True
        assert "runtime-secret-value-for-test-only" not in repr(exc_info.value)
        assert "raw body" not in repr(exc_info.value)
        assert "SECRET_TOKEN" not in repr(exc_info.value)


def test_transport_invalid_utf8_stream_bytes_use_safe_parse_category_without_cause() -> None:
    transport = FastInteractionLiveDirectHTTPTransport(
        opener=_CapturingOpener(response_lines=[b"data: \xfftoken=SECRET_TOKEN\n"])
    )

    with pytest.raises(FastInteractionLiveTransportError) as exc_info:
        transport.complete(
            request_payload={"text_ref": "text://synthetic/fast-interaction/invalid-utf8"},
            credential_handle=FastInteractionCredentialHandle(
                credential_ref="secret-ref://runtime-env/dashscope-api-key",
            ),
            credential_value="runtime-secret-value-for-test-only",
            adapter_request_id="adapter_request_fast_interaction_invalid_utf8",
            timeout_ms=10,
            model_alias="qwen3.5-omni-flash",
        )

    exc = exc_info.value
    assert exc.category == "provider_response_parse_failed"
    assert exc.failure_reasons == ("provider_response_parse_failed",)
    assert exc.__cause__ is None
    assert exc.__suppress_context__ is True
    rendered = repr(exc)
    assert "SECRET_TOKEN" not in rendered
    assert "runtime-secret-value-for-test-only" not in rendered


def test_credential_handle_is_opaque_and_metadata_only() -> None:
    handle = FastInteractionCredentialHandle(
        credential_ref="secret-ref://runtime-env/dashscope-api-key",
    )

    assert handle.to_metadata() == {
        "credential_ref": "secret-ref://runtime-env/dashscope-api-key",
        "credential_present": True,
        "credential_source": "runtime_env_var:DASHSCOPE_API_KEY",
        "credential_value_included": False,
        "secret_materialized": False,
    }
    assert "runtime-secret-value-for-test-only" not in repr(handle)
    assert "secret_materialized=False" in repr(handle)
    with pytest.raises(FastInteractionLiveTransportError, match="opaque"):
        str(handle)


def _provider_output() -> dict[str, object]:
    return {
        "schema_name": "voice_agent.fast_interaction.output.v1",
        "route_hint": {"router_decision_candidate": "FAST_ONLY"},
        "route_prelude": {"summary": "low risk story request"},
        "foreground_act": "ANSWER",
        "reply_candidate": "A tiny safe story.",
        "final_fast_evidence": {"summary": "safe foreground answer"},
        "risk_tags": ["low_risk", "no_side_effects"],
        "risk_class": "LOW",
        "confidence": 0.91,
        "output_mode": "real",
        "boundary_assertions": {
            "candidate_is_not_semantic_commitment": True,
            "may_authorize_tools": False,
            "may_execute_tools": False,
            "may_accept_confirmation": False,
            "may_mutate_slowtask_facts": False,
            "runtime_gate_owns_display": True,
        },
    }


class _StreamingResponse:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    def __enter__(self) -> "_StreamingResponse":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def __iter__(self) -> object:
        return iter(self._lines)


class _CapturingOpener:
    def __init__(self, *, response_lines: list[bytes]) -> None:
        self._response_lines = response_lines
        self.request = None
        self.timeout = None

    def open(self, request: object, timeout: float) -> _StreamingResponse:
        self.request = request
        self.timeout = timeout
        return _StreamingResponse(self._response_lines)


class _RaisingOpener:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def open(self, request: object, timeout: float) -> object:
        raise self._exc


class _SequenceClock:
    def __init__(self, values: tuple[int, ...]) -> None:
        self._values = list(values)

    def __call__(self) -> int:
        assert self._values
        return self._values.pop(0)
