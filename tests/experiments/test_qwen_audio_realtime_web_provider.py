from __future__ import annotations

import asyncio
import base64
import json
from types import SimpleNamespace

import aiohttp
import pytest

from experiments.qwen_audio_realtime_web import provider_adapter as provider_adapter_module
from experiments.qwen_audio_realtime_web.fake_provider import (
    FakeProviderConfig,
    FakeRealtimeProvider,
)
from experiments.qwen_audio_realtime_web.provider_adapter import (
    CredentialConfigurationError,
    CredentialHandle,
    NormalizedProviderEvent,
    ProviderConnectionError,
    QwenRealtimeProvider,
    SafeProviderError,
    build_session_update,
    normalize_qwen_event,
)


def run(coro):
    return asyncio.run(coro)


class RecordingWebSocket:
    def __init__(self, trace: list[str] | None = None) -> None:
        self.closed = False
        self.sent: list[dict[str, object]] = []
        self.trace = trace

    async def send_json(self, payload: dict[str, object]) -> None:
        self.sent.append(payload)
        if self.trace is not None:
            self.trace.append(f"send:{payload.get('type')}")

    async def close(self) -> None:
        self.closed = True


class ScriptedWebSocket(RecordingWebSocket):
    def __init__(
        self, messages: list[SimpleNamespace], trace: list[str] | None = None
    ) -> None:
        super().__init__(trace)
        self.messages = messages

    async def receive(self) -> SimpleNamespace:
        if not self.messages:
            await asyncio.Future()
        message = self.messages.pop(0)
        if self.trace is not None:
            if message.type == aiohttp.WSMsgType.TEXT:
                try:
                    event_type = json.loads(message.data).get("type", "invalid")
                except (TypeError, ValueError):
                    event_type = "malformed"
            else:
                event_type = str(message.type)
            self.trace.append(f"receive:{event_type}")
        return message


class ScriptedClientSession:
    def __init__(self, websocket: ScriptedWebSocket, trace: list[str]) -> None:
        self.websocket = websocket
        self.trace = trace
        self.closed = False

    async def ws_connect(self, *_args: object, **_kwargs: object) -> ScriptedWebSocket:
        self.trace.append("ws.open")
        return self.websocket

    async def close(self) -> None:
        self.closed = True


def text_message(payload: object) -> SimpleNamespace:
    return SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data=json.dumps(payload))


def voiced_frame(samples: int = 1_600, amplitude: int = 1_000) -> bytes:
    return amplitude.to_bytes(2, "little", signed=True) * samples


def test_session_update_uses_smart_turn_and_explicitly_disables_tools() -> None:
    update = build_session_update(voice="longanqian", instructions="Synthetic test")

    assert update == {
        "type": "session.update",
        "session": {
            "modalities": ["text", "audio"],
            "voice": "longanqian",
            "instructions": "Synthetic test",
            "turn_detection": {"type": "smart_turn"},
            "tools": [],
        },
    }


@pytest.mark.parametrize(
    ("voice", "instructions"),
    (("bad voice", "ok"), ("ok", ""), ("ok", "x" * 2_001)),
)
def test_session_update_rejects_unsafe_or_unbounded_configuration(
    voice: str, instructions: str
) -> None:
    with pytest.raises(CredentialConfigurationError):
        build_session_update(voice=voice, instructions=instructions)


def test_credential_handle_fails_closed_for_missing_or_invalid_values() -> None:
    with pytest.raises(CredentialConfigurationError, match="missing_dashscope_api_key"):
        CredentialHandle.from_environment({})
    with pytest.raises(CredentialConfigurationError, match="invalid_workspace_id"):
        CredentialHandle("configured-value", "unsafe.workspace.example")


def test_credential_handle_has_redacted_repr_and_secret_free_metadata() -> None:
    api_key = "PRIVATE_CREDENTIAL_SENTINEL"
    workspace_id = "workspace-private-sentinel"
    handle = CredentialHandle(api_key, workspace_id)

    rendered = repr(handle)
    metadata = handle.to_metadata()
    serialized = json.dumps(metadata, sort_keys=True)

    assert rendered == "CredentialHandle(api_key=<redacted>, workspace_id=<redacted>)"
    assert api_key not in rendered + serialized
    assert workspace_id not in rendered + serialized
    assert metadata == {
        "api_key_configured": True,
        "workspace_id_configured": True,
        "workspace_ref": metadata["workspace_ref"],
    }
    assert metadata["workspace_ref"].startswith("workspace-")
    with pytest.raises(TypeError):
        vars(handle)


@pytest.mark.parametrize(
    ("payload", "expected_type", "text"),
    (
        (
            {
                "type": "conversation.item.input_audio_transcription.delta",
                "delta": "synthetic partial",
                "stash": "redacted stash",
            },
            "user.transcript.delta",
            "synthetic partial",
        ),
        (
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "transcript": "synthetic final",
            },
            "user.transcript.final",
            "synthetic final",
        ),
        (
            {
                "type": "response.audio_transcript.delta",
                "response_id": "provider-response-id",
                "delta": "synthetic assistant",
            },
            "assistant.transcript.delta",
            "synthetic assistant",
        ),
    ),
)
def test_transcript_events_are_normalized(
    payload: dict[str, object], expected_type: str, text: str
) -> None:
    event = normalize_qwen_event(payload)

    assert event.type == expected_type
    assert event.text == text
    assert event.output_mode == "real"


def test_session_and_response_ids_are_hashed_into_safe_refs() -> None:
    raw_session_id = "provider-session-private-id"
    raw_response_id = "provider-response-private-id"

    session = normalize_qwen_event(
        {"type": "session.created", "session": {"id": raw_session_id}}
    )
    response = normalize_qwen_event(
        {"type": "response.created", "response": {"id": raw_response_id}}
    )
    serialized = json.dumps(
        [session.safe_metadata(), response.safe_metadata()], sort_keys=True
    )

    assert session.session_ref and session.session_ref.startswith("session-")
    assert response.response_ref and response.response_ref.startswith("response-")
    assert raw_session_id not in serialized
    assert raw_response_id not in serialized


def test_output_pcm_delta_is_base64_decoded_and_not_in_safe_metadata() -> None:
    pcm = b"\x01\x00\x02\x00"
    event = normalize_qwen_event(
        {
            "type": "response.audio.delta",
            "response_id": "synthetic-response",
            "delta": base64.b64encode(pcm).decode("ascii"),
        }
    )

    assert event.type == "response.audio.delta"
    assert event.audio == pcm
    assert event.byte_length == len(pcm)
    assert event.safe_metadata()["byte_length"] == len(pcm)
    assert "audio" not in event.safe_metadata()


@pytest.mark.parametrize(
    "delta",
    ("not-base64!", base64.b64encode(b"odd").decode("ascii"), ""),
)
def test_invalid_provider_audio_becomes_safe_degraded_error(delta: str) -> None:
    event = normalize_qwen_event(
        {"type": "response.audio.delta", "delta": delta},
        active_response_ref="response-safe",
    )

    assert event == NormalizedProviderEvent(
        type="provider.error",
        output_mode="degraded",
        response_ref="response-safe",
        error_code="invalid_provider_audio_delta",
    )


def test_safe_metadata_excludes_transcript_and_pcm_values() -> None:
    event = NormalizedProviderEvent(
        type="assistant.transcript.delta",
        output_mode="real",
        response_ref="response-safe",
        text="synthetic transcript is session-only",
        stash="redacted transient stash",
        audio=b"\x00\x00",
    )

    metadata = event.safe_metadata()
    serialized = json.dumps(metadata)

    assert "text" not in metadata
    assert "stash" not in metadata
    assert "audio" not in metadata
    assert "synthetic transcript" not in serialized
    assert metadata["byte_length"] == 2


def test_provider_error_is_normalized_without_raw_message_or_secret() -> None:
    raw_message = "Authorization: Bearer PRIVATE_CREDENTIAL_SENTINEL"
    raw_code = "PRIVATE_PROVIDER_CODE_SENTINEL"
    event = normalize_qwen_event(
        {
            "type": "error",
            "error": {
                "code": raw_code,
                "message": raw_message,
                "request_id": "private-request-id",
            },
        }
    )
    serialized = json.dumps(event.safe_metadata(), sort_keys=True)

    assert event.type == "provider.error"
    assert event.output_mode == "degraded"
    assert raw_message not in serialized
    assert raw_code not in serialized
    assert "PRIVATE_CREDENTIAL_SENTINEL" not in serialized


def test_authentication_error_uses_terminal_safe_category() -> None:
    event = normalize_qwen_event(
        {
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "code": "invalid_api_key",
                "message": "synthetic redacted authentication failure",
            },
        }
    )

    assert event.error_code == "provider_authentication_failed"
    assert event.terminal is True
    assert "invalid_api_key" not in json.dumps(event.safe_metadata())


def test_real_provider_connect_requires_ordered_handshake_and_prefetches_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        trace: list[str] = []
        websocket = ScriptedWebSocket(
            [
                text_message(
                    {"type": "session.created", "session": {"id": "session-one"}}
                ),
                text_message(
                    {"type": "session.updated", "session": {"id": "session-one"}}
                ),
                text_message(
                    {"type": "response.created", "response": {"id": "response-one"}}
                ),
            ],
            trace,
        )
        client = ScriptedClientSession(websocket, trace)
        monkeypatch.setattr(
            provider_adapter_module.aiohttp,
            "ClientSession",
            lambda **_kwargs: client,
        )
        provider = QwenRealtimeProvider(
            CredentialHandle("configured-value", "workspace-test")
        )

        await provider.connect()

        assert trace == [
            "ws.open",
            "receive:session.created",
            "send:session.update",
            "receive:session.updated",
        ]
        assert provider.profile.health_status == "ready"
        created = await provider.recv_event()
        updated = await provider.recv_event()
        assert [created.type, updated.type] == ["session.created", "session.updated"]
        # Prefetched delivery must not touch the wire a second time.
        assert trace[-1] == "receive:session.updated"
        response = await provider.recv_event()
        assert response.type == "response.created"
        assert trace[-1] == "receive:response.created"
        await provider.close()

    run(scenario())


def test_real_provider_handshake_timeout_is_bounded_and_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        trace: list[str] = []
        websocket = ScriptedWebSocket(
            [text_message({"type": "session.created", "session": {"id": "safe"}})],
            trace,
        )
        client = ScriptedClientSession(websocket, trace)
        monkeypatch.setattr(
            provider_adapter_module.aiohttp,
            "ClientSession",
            lambda **_kwargs: client,
        )
        provider = QwenRealtimeProvider(
            CredentialHandle("configured-value", "workspace-test"),
            connect_timeout_seconds=0.01,
        )

        with pytest.raises(ProviderConnectionError) as raised:
            await provider.connect()

        assert raised.value.code == "provider_connect_timeout"
        assert raised.value.retryable is True
        assert provider.profile.health_status == "unavailable"
        assert websocket.closed is True
        assert client.closed is True

    run(scenario())


def test_real_provider_handshake_error_keeps_provider_details_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        trace: list[str] = []
        raw_secret = "Bearer PRIVATE_CREDENTIAL_SENTINEL"
        websocket = ScriptedWebSocket(
            [
                text_message(
                    {"type": "session.created", "session": {"id": "session-one"}}
                ),
                text_message(
                    {
                        "type": "error",
                        "error": {
                            "code": "invalid_api_key",
                            "message": raw_secret,
                        },
                    }
                ),
            ],
            trace,
        )
        client = ScriptedClientSession(websocket, trace)
        monkeypatch.setattr(
            provider_adapter_module.aiohttp,
            "ClientSession",
            lambda **_kwargs: client,
        )
        provider = QwenRealtimeProvider(
            CredentialHandle("configured-value", "workspace-test")
        )

        with pytest.raises(ProviderConnectionError) as raised:
            await provider.connect()

        assert raised.value.code == "provider_authentication_failed"
        assert raised.value.retryable is False
        assert raw_secret not in str(raised.value)
        assert raw_secret not in repr(raised.value)
        assert provider.profile.health_status == "unavailable"
        assert websocket.closed is True
        assert client.closed is True

    run(scenario())


@pytest.mark.parametrize(
    "message",
    (
        SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data="not-json"),
        SimpleNamespace(type=aiohttp.WSMsgType.CLOSE, data=None),
    ),
)
def test_real_provider_rejects_malformed_or_disconnected_handshake_safely(
    monkeypatch: pytest.MonkeyPatch, message: SimpleNamespace
) -> None:
    async def scenario() -> None:
        trace: list[str] = []
        websocket = ScriptedWebSocket([message], trace)
        client = ScriptedClientSession(websocket, trace)
        monkeypatch.setattr(
            provider_adapter_module.aiohttp,
            "ClientSession",
            lambda **_kwargs: client,
        )
        provider = QwenRealtimeProvider(
            CredentialHandle("configured-value", "workspace-test")
        )

        with pytest.raises(ProviderConnectionError) as raised:
            await provider.connect()

        assert raised.value.code == "provider_connect_failed"
        assert "not-json" not in str(raised.value)
        assert provider.profile.health_status == "unavailable"
        assert websocket.closed is True
        assert client.closed is True

    run(scenario())


def test_send_audio_forwards_input_audio_buffer_append_without_retention() -> None:
    async def scenario() -> None:
        provider = QwenRealtimeProvider(
            CredentialHandle("configured-value", "workspace-test")
        )
        websocket = RecordingWebSocket()
        provider._websocket = websocket  # transport seam; no network access
        provider._connected = True
        pcm = voiced_frame()

        await provider.send_audio(pcm)

        assert websocket.sent == [
            {
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(pcm).decode("ascii"),
            }
        ]
        assert not hasattr(provider, "audio_frames")
        await provider.close()

    run(scenario())


def test_response_cancel_is_sent_only_once_while_response_is_active() -> None:
    async def scenario() -> None:
        provider = QwenRealtimeProvider(
            CredentialHandle("configured-value", "workspace-test")
        )
        websocket = RecordingWebSocket()
        provider._websocket = websocket
        provider._connected = True

        assert await provider.cancel_response() is False
        provider._active_response_id = "active-response"
        assert await provider.cancel_response() is True
        assert await provider.cancel_response() is False
        assert websocket.sent == [{"type": "response.cancel"}]
        await provider.close()

    run(scenario())


def test_fake_provider_connect_update_continuous_audio_and_streaming_outputs() -> None:
    async def scenario() -> None:
        provider = FakeRealtimeProvider(
            FakeProviderConfig(
                auto_stop_after_voiced_frames=3,
                transcript_delta_every_frames=1,
                event_delay_seconds=0,
                response_audio_chunks=3,
            )
        )
        await provider.connect()
        events = [await provider.recv_event(), await provider.recv_event()]

        for _ in range(3):
            await provider.send_audio(voiced_frame())

        while not any(event.type == "response.done" for event in events):
            events.append(await asyncio.wait_for(provider.recv_event(), timeout=1))

        types = [event.type for event in events]
        assert types[:2] == ["session.created", "session.updated"]
        assert provider.sent_audio_frames == 3
        assert provider.sent_audio_bytes == 3 * 3_200
        assert "speech.started" in types
        assert types.count("user.transcript.delta") == 3
        assert "speech.stopped" in types
        assert "user.transcript.final" in types
        assert "assistant.transcript.delta" in types
        assert "assistant.transcript.done" in types
        assert types.count("response.audio.delta") == 3
        assert types[-1] == "response.done"
        partials = [
            event.text or ""
            for event in events
            if event.type == "user.transcript.delta"
        ]
        assert all(
            current.startswith(previous)
            for previous, current in zip(partials, partials[1:])
        )
        for event in events:
            if event.type == "response.audio.delta":
                assert event.audio and len(event.audio) % 2 == 0
                assert event.output_mode == "mock"
        await provider.close()

    run(scenario())


def test_fake_provider_supports_two_turns_after_silence_reset() -> None:
    async def scenario() -> None:
        provider = FakeRealtimeProvider(
            FakeProviderConfig(
                auto_stop_after_voiced_frames=1,
                transcript_delta_every_frames=1,
                event_delay_seconds=0,
                response_audio_chunks=1,
            )
        )
        await provider.connect()
        await provider.recv_event()
        await provider.recv_event()

        async def run_turn() -> list[NormalizedProviderEvent]:
            await provider.send_audio(voiced_frame())
            events: list[NormalizedProviderEvent] = []
            while not any(event.type == "response.done" for event in events):
                events.append(
                    await asyncio.wait_for(provider.recv_event(), timeout=1)
                )
            return events

        first_turn = await run_turn()
        # The fake intentionally requires one silent frame after auto-stop,
        # matching a continuous microphone stream before a new speech start.
        await provider.send_audio(b"\x00\x00" * 1_600)
        second_turn = await run_turn()

        first_response = next(
            event.response_ref
            for event in first_turn
            if event.type == "response.created"
        )
        second_response = next(
            event.response_ref
            for event in second_turn
            if event.type == "response.created"
        )
        assert [
            sum(event.type == "speech.started" for event in events)
            for events in (first_turn, second_turn)
        ] == [1, 1]
        assert first_response != second_response
        assert provider.sent_audio_frames == 3
        await provider.close()

    run(scenario())


def test_fake_provider_cancel_emits_one_late_audio_then_cancelled_done() -> None:
    async def scenario() -> None:
        provider = FakeRealtimeProvider(
            FakeProviderConfig(
                auto_stop_after_voiced_frames=1,
                transcript_delta_every_frames=1,
                event_delay_seconds=0.01,
                response_audio_chunks=3,
                late_audio_after_cancel=True,
            )
        )
        await provider.connect()
        await provider.recv_event()
        await provider.recv_event()
        await provider.send_audio(voiced_frame())

        event = await provider.recv_event()
        while event.type != "response.created":
            event = await provider.recv_event()
        assert provider.response_active is True
        assert await provider.cancel_response() is True
        assert await provider.cancel_response() is False

        after_cancel: list[NormalizedProviderEvent] = []
        while not any(item.type == "response.done" for item in after_cancel):
            after_cancel.append(
                await asyncio.wait_for(provider.recv_event(), timeout=1)
            )
        assert [item.type for item in after_cancel] == [
            "response.audio.delta",
            "response.done",
        ]
        assert after_cancel[-1].status == "cancelled"
        assert provider.cancel_count == 1
        await provider.close()

    run(scenario())


def test_fake_provider_error_and_disconnect_are_terminal_safe_metadata() -> None:
    async def scenario() -> None:
        provider = FakeRealtimeProvider()
        await provider.connect()
        await provider.recv_event()
        await provider.recv_event()

        await provider.trigger_error("synthetic rate limit", terminal=False)
        error = await provider.recv_event()
        assert error.safe_metadata() == {
            "type": "provider.error",
            "output_mode": "degraded",
            "byte_length": 0,
            "error_code": "synthetic_rate_limit",
            "terminal": False,
        }

        await provider.trigger_disconnect()
        disconnect = await provider.recv_event()
        assert disconnect.type == "provider.disconnected"
        assert disconnect.output_mode == "degraded"
        assert disconnect.error_code == "synthetic_provider_disconnect"
        assert disconnect.terminal is True
        await provider.close()

    run(scenario())


def test_fake_provider_rejects_invalid_pcm_without_counting_or_retaining_it() -> None:
    async def scenario() -> None:
        provider = FakeRealtimeProvider()
        await provider.connect()
        await provider.recv_event()
        await provider.recv_event()

        with pytest.raises(SafeProviderError, match="invalid_pcm_frame"):
            await provider.send_audio(b"\x01")
        assert provider.sent_audio_frames == 0
        assert provider.sent_audio_bytes == 0
        await provider.close()

    run(scenario())
