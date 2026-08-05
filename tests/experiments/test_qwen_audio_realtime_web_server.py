from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from aiohttp import WSMsgType, WSServerHandshakeError
from aiohttp.test_utils import TestClient, TestServer

from experiments.qwen_audio_realtime_web.fake_provider import (
    FakeProviderConfig,
    FakeRealtimeProvider,
)
from experiments.qwen_audio_realtime_web.provider_adapter import (
    CredentialConfigurationError,
)
from experiments.qwen_audio_realtime_web.server import create_app
from experiments.qwen_audio_realtime_web.session_bridge import unpack_output_audio


def run(coro):
    return asyncio.run(coro)


def voiced_frame(samples: int = 1_600, amplitude: int = 1_000) -> bytes:
    return amplitude.to_bytes(2, "little", signed=True) * samples


def client_origin(client: TestClient) -> str:
    return str(client.make_url("/").origin())


async def open_client(app) -> TestClient:
    client = TestClient(TestServer(app))
    try:
        await client.start_server()
    except PermissionError:
        await client.close()
        pytest.skip("sandbox does not permit binding a loopback test port")
    return client


async def receive_until_json_type(
    websocket, event_type: str, *, timeout: float = 1.0
) -> tuple[dict[str, Any], list[bytes], list[dict[str, Any]]]:
    binary: list[bytes] = []
    seen_json: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        while True:
            message = await websocket.receive()
            if message.type == WSMsgType.BINARY:
                binary.append(message.data)
                continue
            if message.type == WSMsgType.TEXT:
                payload = json.loads(message.data)
                seen_json.append(payload)
                if payload.get("type") == event_type:
                    return payload
                continue
            raise AssertionError(
                f"websocket closed before {event_type}: {message.type} {message.data!r}"
            )

    payload = await asyncio.wait_for(receive(), timeout=timeout)
    return payload, binary, seen_json


def test_static_page_assets_health_and_security_headers_are_served() -> None:
    async def scenario() -> None:
        client = await open_client(create_app(provider_mode="fake"))
        try:
            index_response = await client.get("/")
            assert index_response.status == 200
            index = await index_response.text()
            assert 'href="/static/styles.css"' in index
            assert 'src="/static/app.js"' in index
            assert index_response.headers["Cache-Control"] == "no-store"
            assert index_response.headers["X-Content-Type-Options"] == "nosniff"
            assert index_response.headers["Permissions-Policy"] == "microphone=(self)"
            assert "object-src 'none'" in index_response.headers[
                "Content-Security-Policy"
            ]

            for asset in (
                "/static/styles.css",
                "/static/app.js",
                "/static/mic-worklet.js",
                "/static/player-worklet.js",
            ):
                response = await client.get(asset)
                assert response.status == 200, asset
                assert await response.read(), asset

            favicon_response = await client.get("/favicon.ico")
            assert favicon_response.status == 204

            health_response = await client.get("/healthz")
            assert health_response.status == 200
            health = await health_response.json()
            assert health["status"] == "ok"
            assert health["scope"] == "isolated_qwen_audio_realtime_web_spike"
            assert health["provider_mode"] == "fake"
            assert health["output_mode"] == "mock"
            assert health["capabilities"]["adapter_id"] == (
                "qwen_audio_realtime_web.fake.v1"
            )
            assert "api_key" not in json.dumps(health).lower()
            assert "authorization" not in json.dumps(health).lower()
        finally:
            await client.close()

    run(scenario())


def test_health_real_profile_is_not_executed_without_opening_provider() -> None:
    async def scenario() -> None:
        client = await open_client(create_app(provider_mode="real"))
        try:
            response = await client.get("/healthz")
            health = await response.json()

            assert response.status == 200
            assert health["provider_mode"] == "real"
            assert health["output_mode"] == "real"
            assert health["capabilities"]["health_status"] == "not_executed"
            assert health["capabilities"]["model_name"] == (
                "qwen-audio-3.0-realtime-plus"
            )
        finally:
            await client.close()

    run(scenario())


@pytest.mark.parametrize(
    "origin",
    (None, "https://evil.example", "http://127.0.0.1:1"),
)
def test_websocket_rejects_missing_cross_site_or_wrong_port_origin(
    origin: str | None,
) -> None:
    async def scenario() -> None:
        client = await open_client(create_app())
        try:
            headers = {} if origin is None else {"Origin": origin}
            with pytest.raises(WSServerHandshakeError) as exc_info:
                await client.ws_connect("/ws", headers=headers)
            assert exc_info.value.status == 403
        finally:
            await client.close()

    run(scenario())


def test_websocket_accepts_same_loopback_origin_and_publishes_ready() -> None:
    async def scenario() -> None:
        client = await open_client(create_app(provider_mode="fake"))
        try:
            websocket = await client.ws_connect(
                "/ws", headers={"Origin": client_origin(client)}
            )
            ready, _, _ = await receive_until_json_type(websocket, "session.ready")

            assert ready["state"] == "connected"
            assert ready["mode"] == "headset_full_duplex"
            assert ready["output_mode"] == "mock"
            assert ready["capabilities"]["health_status"] == "ready"
            await websocket.close()
        finally:
            await client.close()

    run(scenario())


def test_fake_websocket_acceptance_forwards_frames_transcripts_and_qar1_audio() -> None:
    async def scenario() -> None:
        providers: list[FakeRealtimeProvider] = []

        def factory() -> FakeRealtimeProvider:
            provider = FakeRealtimeProvider(
                FakeProviderConfig(
                    auto_stop_after_voiced_frames=3,
                    transcript_delta_every_frames=1,
                    event_delay_seconds=0,
                    response_audio_chunks=3,
                )
            )
            providers.append(provider)
            return provider

        client = await open_client(
            create_app(provider_mode="fake", provider_factory=factory)
        )
        try:
            websocket = await client.ws_connect(
                "/ws", headers={"Origin": client_origin(client)}
            )
            await receive_until_json_type(websocket, "session.ready")
            for _ in range(3):
                await websocket.send_bytes(voiced_frame())

            done, binary, seen = await receive_until_json_type(
                websocket, "response.done", timeout=2
            )
            types = [item["type"] for item in seen]

            assert providers[0].sent_audio_frames == 3
            assert providers[0].sent_audio_bytes == 9_600
            assert "speech.started" in types
            assert "speech.stopped" in types
            assert "user.transcript.delta" in types
            assert "user.transcript.final" in types
            assert "assistant.transcript.delta" in types
            assert "assistant.transcript.done" in types
            assert done["status"] == "completed"
            assert binary
            unpacked = [unpack_output_audio(frame) for frame in binary]
            assert {epoch for epoch, _pcm in unpacked} == {1}
            assert all(pcm and len(pcm) % 2 == 0 for _epoch, pcm in unpacked)

            await websocket.close()
            for _ in range(100):
                if providers[0].profile.health_status == "closed":
                    break
                await asyncio.sleep(0)
            assert providers[0].profile.health_status == "closed"
        finally:
            await client.close()

    run(scenario())


def test_websocket_cancel_clears_epoch_and_discards_fake_late_audio() -> None:
    async def scenario() -> None:
        providers: list[FakeRealtimeProvider] = []

        def factory() -> FakeRealtimeProvider:
            provider = FakeRealtimeProvider(
                FakeProviderConfig(
                    auto_stop_after_voiced_frames=1,
                    transcript_delta_every_frames=1,
                    event_delay_seconds=0.01,
                    response_audio_chunks=8,
                    late_audio_after_cancel=True,
                )
            )
            providers.append(provider)
            return provider

        client = await open_client(create_app(provider_factory=factory))
        try:
            websocket = await client.ws_connect(
                "/ws", headers={"Origin": client_origin(client)}
            )
            await receive_until_json_type(websocket, "session.ready")
            await websocket.send_bytes(voiced_frame())
            started, _, _ = await receive_until_json_type(
                websocket, "playback.started", timeout=1
            )
            assert started["playback_epoch"] == 1

            await websocket.send_json({"type": "client.cancel"})
            clear, binary_before_clear, _ = await receive_until_json_type(
                websocket, "playback.clear", timeout=1
            )
            assert clear["reason"] == "client_cancel"
            assert clear["playback_epoch"] == 2
            assert clear["cancel_requested"] is True

            done, binary_after_clear, seen_after_clear = await receive_until_json_type(
                websocket, "response.done", timeout=2
            )
            assert done["status"] == "cancelled"
            assert providers[0].cancel_count == 1
            assert binary_after_clear == []
            assert all(
                unpack_output_audio(frame)[0] < clear["playback_epoch"]
                for frame in binary_before_clear
            )
            assert any(
                item["type"] == "flow.dropped"
                and item["reason"] == "stale_response_audio"
                for item in seen_after_clear
            )
            await websocket.close()
        finally:
            await client.close()

    run(scenario())


def test_oversized_pcm_frame_is_rejected_and_websocket_has_hard_message_limit() -> None:
    async def scenario() -> None:
        client = await open_client(create_app())
        try:
            websocket = await client.ws_connect(
                "/ws", headers={"Origin": client_origin(client)}
            )
            await receive_until_json_type(websocket, "session.ready")

            await websocket.send_bytes(b"\x00\x00" * 3_201)
            error, _, _ = await receive_until_json_type(
                websocket, "session.error"
            )
            assert error["code"] == "invalid_browser_audio_frame"
            assert error["retryable"] is True

            await websocket.send_bytes(b"\x00" * 8_193)
            message = await asyncio.wait_for(websocket.receive(), timeout=1)
            while message.type in {WSMsgType.TEXT, WSMsgType.BINARY}:
                message = await asyncio.wait_for(websocket.receive(), timeout=1)
            assert message.type in {
                WSMsgType.CLOSE,
                WSMsgType.CLOSED,
                WSMsgType.CLOSING,
                WSMsgType.ERROR,
            }
        finally:
            await client.close()

    run(scenario())


def test_provider_configuration_error_is_safe_and_contains_no_secret() -> None:
    async def scenario() -> None:
        secret = "PRIVATE_CREDENTIAL_SENTINEL"

        def failing_factory():
            # The secret is deliberately not included in the safe exception.
            assert secret
            raise CredentialConfigurationError("missing_dashscope_api_key")

        client = await open_client(
            create_app(provider_mode="real", provider_factory=failing_factory)
        )
        try:
            websocket = await client.ws_connect(
                "/ws", headers={"Origin": client_origin(client)}
            )
            message = await asyncio.wait_for(websocket.receive(), timeout=1)
            payload = json.loads(message.data)
            serialized = json.dumps(payload, sort_keys=True)

            assert payload["type"] == "session.error"
            assert payload["code"] == "missing_dashscope_api_key"
            assert payload["terminal"] is True
            assert payload["output_mode"] == "degraded"
            assert payload["provider_mode"] == "real"
            assert secret not in serialized
            assert "Authorization" not in serialized
        finally:
            await client.close()

    run(scenario())
