from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

import pytest
from aiohttp import WSMsgType, WSServerHandshakeError
from aiohttp.test_utils import TestClient, TestServer

from experiments.qwen_realtime_fast_slow_web.fake_provider import (
    FakeProviderConfig,
    FakeRealtimeProvider,
)
from experiments.qwen_realtime_fast_slow_web.qwen_shadow_router_adapter import (
    FakeShadowControlProvider,
)
from experiments.qwen_realtime_fast_slow_web.server import _build_parser, create_app


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


async def receive_until(
    websocket,
    predicate: Callable[[dict[str, Any]], bool],
    *,
    timeout: float = 2.0,
) -> tuple[dict[str, Any], list[tuple[str, Any]]]:
    records: list[tuple[str, Any]] = []

    async def receive() -> dict[str, Any]:
        while True:
            message = await websocket.receive()
            if message.type == WSMsgType.BINARY:
                records.append(("binary", message.data))
                continue
            if message.type == WSMsgType.TEXT:
                payload = json.loads(message.data)
                records.append(("json", payload))
                if predicate(payload):
                    return payload
                continue
            raise AssertionError(
                f"websocket closed before expected message: {message.type} {message.data!r}"
            )

    result = await asyncio.wait_for(receive(), timeout=timeout)
    return result, records


async def receive_type(
    websocket, message_type: str, *, timeout: float = 2.0
) -> tuple[dict[str, Any], list[tuple[str, Any]]]:
    return await receive_until(
        websocket,
        lambda payload: payload.get("type") == message_type,
        timeout=timeout,
    )


def test_static_health_and_security_headers_are_provider_free() -> None:
    async def scenario() -> None:
        client = await open_client(create_app())
        try:
            index_response = await client.get("/")
            assert index_response.status == 200
            index = await index_response.text()
            assert "Qwen Realtime Fast / Slow Integration Spike" in index
            assert 'src="/static/app.js"' in index
            assert index_response.headers["Cache-Control"] == "no-store"
            assert index_response.headers["X-Content-Type-Options"] == "nosniff"
            assert index_response.headers["Referrer-Policy"] == "no-referrer"
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

            health_response = await client.get("/healthz")
            health = await health_response.json()
            serialized = json.dumps(health, sort_keys=True)
            assert health_response.status == 200
            assert health["status"] == "ok"
            assert health["provider_mode"] == "fake"
            assert health["routing_mode"] == "enforced"
            assert health["slow_runtime_mode"] == "mock"
            assert health["output_mode"] == "mock"
            assert health["degraded"] is False
            assert health["capabilities"]["supports_real_provider"] is False
            assert "DASHSCOPE" not in serialized
            assert "api_key" not in serialized.lower()
            assert "authorization" not in serialized.lower()
        finally:
            await client.close()

    run(scenario())


@pytest.mark.parametrize(
    "kwargs",
    (
        {"provider_mode": "real"},
        {"routing_mode": "advisory"},
        {"slow_runtime_mode": "real"},
        {"audio_output": "provider_direct"},
        {"shadow_control_mode": "single_session"},
        {"provider_mode": "qwen", "routing_mode": "enforced"},
        {"provider_mode": "qwen", "routing_mode": "shadow"},
    ),
)
def test_app_factory_rejects_unsupported_or_unsafe_slice2_modes(
    kwargs: dict[str, str]
) -> None:
    with pytest.raises(ValueError):
        create_app(**kwargs)


def test_cli_exposes_fake_enforced_and_qwen_dual_session_shadow_flags() -> None:
    parser = _build_parser()
    fake = parser.parse_args([])
    real_shadow = parser.parse_args(
        [
            "--provider",
            "qwen",
            "--routing",
            "shadow",
            "--slow-runtime",
            "mock",
            "--audio-output",
            "qwen",
            "--shadow-control",
            "dual_session",
            "--workspace-id",
            "ws-safe-cli",
        ]
    )

    assert fake.provider == "fake"
    assert fake.routing is None
    assert fake.slow_runtime == "mock"
    assert fake.audio_output is None
    assert fake.shadow_control == "dual_session"
    assert real_shadow.provider == "qwen"
    assert real_shadow.routing == "shadow"
    assert real_shadow.slow_runtime == "mock"
    assert real_shadow.audio_output == "qwen"
    assert real_shadow.shadow_control == "dual_session"
    assert real_shadow.workspace_id == "ws-safe-cli"


def test_qwen_shadow_health_and_websocket_plumbing_use_injected_fake_sessions() -> None:
    async def scenario() -> None:
        voices: list[FakeRealtimeProvider] = []
        shadows: list[FakeShadowControlProvider] = []

        def voice_factory() -> FakeRealtimeProvider:
            provider = FakeRealtimeProvider(FakeProviderConfig(event_delay_seconds=0))
            voices.append(provider)
            return provider

        def shadow_factory() -> FakeShadowControlProvider:
            provider = FakeShadowControlProvider()
            shadows.append(provider)
            return provider

        app = create_app(
            provider_mode="qwen",
            routing_mode="shadow",
            slow_runtime_mode="mock",
            audio_output="qwen",
            shadow_control_mode="dual_session",
            provider_factory=voice_factory,
            shadow_provider_factory=shadow_factory,
        )
        client = await open_client(app)
        try:
            health_response = await client.get("/healthz")
            health = await health_response.json()
            serialized_health = json.dumps(health, sort_keys=True)
            assert health_response.status == 200
            assert health["scope"] == (
                "qwen_realtime_fast_slow_integration_spike_slice2"
            )
            assert health["provider_mode"] == "qwen"
            assert health["routing_mode"] == "shadow"
            assert health["slow_runtime_mode"] == "mock"
            assert health["audio_output"] == "qwen"
            assert health["shadow_control_mode"] == "dual_session_shadow"
            assert health["output_mode"] == "not_executed"
            assert health["capabilities"]["supports_real_provider"] is True
            assert health["capabilities"]["route_proposal_authority"] == "none"
            assert health["shadow_capabilities"]["supports_function_calling"] is True
            assert health["shadow_capabilities"]["forced_route_function_call"] == (
                "unsupported_or_unverified"
            )
            assert "authorization" not in serialized_health.lower()
            assert "api_key" not in serialized_health.lower()

            websocket = await client.ws_connect(
                "/ws", headers={"Origin": client_origin(client)}
            )
            ready, _ = await receive_type(websocket, "session.ready")
            assert ready["provider_mode"] == "qwen"
            assert ready["routing_mode"] == "shadow"
            assert ready["audio_output"] == "qwen"
            assert ready["shadow_control_mode"] == "dual_session_shadow"
            assert ready["voice_session_status"] == "connected"
            assert ready["shadow_control_session_status"] == "connected"
            # Factories are test doubles: mode labels remain truthful instead
            # of pretending this was a real provider connection.
            assert ready["output_mode"] == "mock"
            assert ready["capabilities"]["supports_real_provider"] is False
            assert ready["shadow_capabilities"]["supports_real_provider"] is False
            assert len(voices) == len(shadows) == 1
            await websocket.close()
        finally:
            await client.close()

        assert voices[0].profile.health_status == "closed"
        assert shadows[0].profile.health_status == "closed"

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


def test_websocket_rejects_non_loopback_host_even_with_loopback_origin() -> None:
    async def scenario() -> None:
        client = await open_client(create_app())
        try:
            with pytest.raises(WSServerHandshakeError) as exc_info:
                await client.ws_connect(
                    "/ws",
                    headers={
                        "Origin": client_origin(client),
                        "Host": "example.invalid",
                    },
                )
            assert exc_info.value.status == 403
        finally:
            await client.close()

    run(scenario())


def test_websocket_connect_configure_and_fast_gate_before_visible_acceptance() -> None:
    async def scenario() -> None:
        providers: list[FakeRealtimeProvider] = []

        def factory() -> FakeRealtimeProvider:
            provider = FakeRealtimeProvider(
                FakeProviderConfig(
                    response_audio_chunks=2,
                    event_delay_seconds=0,
                )
            )
            providers.append(provider)
            return provider

        client = await open_client(create_app(provider_factory=factory))
        try:
            websocket = await client.ws_connect(
                "/ws", headers={"Origin": client_origin(client)}
            )
            ready, _ = await receive_type(websocket, "session.ready")
            assert ready["provider_mode"] == "fake"
            assert ready["output_mode"] == "mock"

            await websocket.send_json(
                {
                    "type": "session.configure",
                    "protocol_version": 2,
                    "scenario": "fast",
                    "playback_enabled": True,
                }
            )
            configured, _ = await receive_until(
                websocket,
                lambda item: item.get("type") == "state.changed"
                and item.get("reason") == "session_configured",
            )
            assert configured["scenario"] == "fast"

            await websocket.send_json(
                {
                    "type": "synthetic.turn",
                    "protocol_version": 2,
                    "scenario": "fast",
                }
            )
            playback_end, records = await receive_type(
                websocket, "playback.end", timeout=3
            )
            assert playback_end["status"] == "completed"
            json_records = [value for kind, value in records if kind == "json"]
            types = [value["type"] for value in json_records]
            assert "transcript.user.delta" in types
            assert "transcript.user.final" in types
            assert "route.proposed" in types
            assert "route.decided" in types
            assert "gate.result" in types
            assert "transcript.assistant.done" in types
            decision = next(
                item for item in json_records if item["type"] == "route.decided"
            )
            gate = next(item for item in json_records if item["type"] == "gate.result")
            assistant = next(
                item
                for item in json_records
                if item["type"] == "transcript.assistant.done"
            )
            assert decision["router_decision"] == "FAST_ONLY"
            assert gate["gate_status"] == "passed"
            assert assistant["source"] == "provider_candidate"
            gate_index = next(
                index
                for index, (kind, value) in enumerate(records)
                if kind == "json" and value.get("type") == "gate.result"
            )
            visible_indexes = [
                index
                for index, (kind, value) in enumerate(records)
                if kind == "binary"
                or (kind == "json" and value.get("type", "").startswith("transcript.assistant"))
            ]
            assert visible_indexes and min(visible_indexes) > gate_index
            assert providers[0].profile.supports_real_provider is False
            await websocket.close()
        finally:
            await client.close()

    run(scenario())


def test_websocket_continuous_binary_audio_is_forwarded_to_fake_provider() -> None:
    async def scenario() -> None:
        providers: list[FakeRealtimeProvider] = []

        def factory() -> FakeRealtimeProvider:
            provider = FakeRealtimeProvider(
                FakeProviderConfig(
                    auto_stop_after_voiced_frames=3,
                    transcript_delta_every_frames=1,
                    response_audio_chunks=1,
                    event_delay_seconds=0,
                )
            )
            providers.append(provider)
            return provider

        client = await open_client(create_app(provider_factory=factory))
        try:
            websocket = await client.ws_connect(
                "/ws", headers={"Origin": client_origin(client)}
            )
            await receive_type(websocket, "session.ready")
            await websocket.send_json(
                {"type": "microphone.start", "protocol_version": 2}
            )
            await receive_until(
                websocket,
                lambda item: item.get("type") == "state.changed"
                and item.get("reason") == "microphone_started",
            )
            for _ in range(3):
                await websocket.send_bytes(voiced_frame())

            final, records = await receive_type(
                websocket, "transcript.user.final", timeout=3
            )
            assert final["text"].startswith("[synthetic]")
            assert any(
                kind == "json" and value.get("type") == "transcript.user.delta"
                for kind, value in records
            )
            for _ in range(100):
                if providers[0].sent_audio_frames == 3:
                    break
                await asyncio.sleep(0)
            assert providers[0].sent_audio_frames == 3
            assert providers[0].sent_audio_bytes == 9_600
            await websocket.close()
        finally:
            await client.close()

    run(scenario())


def test_websocket_protocol_errors_are_safe_and_connection_remains_usable() -> None:
    async def scenario() -> None:
        client = await open_client(create_app())
        try:
            websocket = await client.ws_connect(
                "/ws", headers={"Origin": client_origin(client)}
            )
            await receive_type(websocket, "session.ready")

            await websocket.send_str("{")
            invalid_json, _ = await receive_type(websocket, "safe_error")
            assert invalid_json["code"] == "control_json_invalid"
            assert invalid_json["terminal"] is False

            await websocket.send_json(
                {
                    "type": "synthetic.turn",
                    "protocol_version": 2,
                    "scenario": "fast",
                    "risk_class": "Bearer credential from provider body",
                }
            )
            invalid_value, _ = await receive_type(websocket, "safe_error")
            assert invalid_value["code"] == "synthetic_override_invalid"
            serialized = json.dumps(invalid_value)
            assert "Bearer" not in serialized
            assert "credential" not in serialized.lower()

            await websocket.send_json(
                {"type": "microphone.start", "protocol_version": 2}
            )
            state, _ = await receive_until(
                websocket,
                lambda item: item.get("type") == "state.changed"
                and item.get("reason") == "microphone_started",
            )
            assert state["microphone_active"] is True
            await websocket.close()
        finally:
            await client.close()

    run(scenario())


def test_websocket_invalid_pcm_gets_safe_error_and_hard_message_limit_closes() -> None:
    async def scenario() -> None:
        client = await open_client(create_app())
        try:
            websocket = await client.ws_connect(
                "/ws", headers={"Origin": client_origin(client)}
            )
            await receive_type(websocket, "session.ready")

            await websocket.send_bytes(b"\x00")
            error, _ = await receive_type(websocket, "safe_error")
            assert error["code"] == "audio_frame_size_invalid"
            assert set(error) == {
                "type",
                "protocol_version",
                "code",
                "terminal",
                "retryable",
                "playback_epoch",
            }

            await websocket.send_bytes(b"\x00\x00" * 20_000)
            message = await asyncio.wait_for(websocket.receive(), timeout=2)
            while message.type in {WSMsgType.TEXT, WSMsgType.BINARY}:
                message = await asyncio.wait_for(websocket.receive(), timeout=2)
            assert message.type in {
                WSMsgType.CLOSE,
                WSMsgType.CLOSED,
                WSMsgType.CLOSING,
                WSMsgType.ERROR,
            }
        finally:
            await client.close()

    run(scenario())


@pytest.mark.parametrize(
    ("scenario_name", "expected_code", "terminal"),
    (
        ("provider_error", "synthetic_provider_error", False),
        ("provider_disconnect", "synthetic_provider_disconnect", True),
    ),
)
def test_websocket_provider_failure_is_degraded_and_normalized(
    scenario_name: str, expected_code: str, terminal: bool
) -> None:
    async def scenario() -> None:
        client = await open_client(create_app())
        try:
            websocket = await client.ws_connect(
                "/ws", headers={"Origin": client_origin(client)}
            )
            await receive_type(websocket, "session.ready")
            await websocket.send_json(
                {
                    "type": "synthetic.turn",
                    "protocol_version": 2,
                    "scenario": scenario_name,
                }
            )
            error, records = await receive_type(websocket, "safe_error")
            degraded = next(
                value
                for kind, value in records
                if kind == "json" and value.get("type") == "degraded"
            )
            assert degraded["output_mode"] == "degraded"
            assert degraded["code"] == expected_code
            assert error["code"] == expected_code
            assert error["terminal"] is terminal
            await websocket.close()
        finally:
            await client.close()

    run(scenario())


def test_browser_disconnect_closes_provider_and_session_coordinator() -> None:
    async def scenario() -> None:
        providers: list[FakeRealtimeProvider] = []

        def factory() -> FakeRealtimeProvider:
            provider = FakeRealtimeProvider(FakeProviderConfig(event_delay_seconds=0))
            providers.append(provider)
            return provider

        app = create_app(provider_factory=factory)
        client = await open_client(app)
        try:
            websocket = await client.ws_connect(
                "/ws", headers={"Origin": client_origin(client)}
            )
            await receive_type(websocket, "session.ready")
            await websocket.send_json(
                {"type": "disconnect", "protocol_version": 2}
            )
            message = await asyncio.wait_for(websocket.receive(), timeout=2)
            while message.type in {WSMsgType.TEXT, WSMsgType.BINARY}:
                message = await asyncio.wait_for(websocket.receive(), timeout=2)
            assert message.type in {
                WSMsgType.CLOSE,
                WSMsgType.CLOSED,
                WSMsgType.CLOSING,
                WSMsgType.ERROR,
            }
            for _ in range(100):
                if providers[0].profile.health_status == "closed":
                    break
                await asyncio.sleep(0)
            assert providers[0].profile.health_status == "closed"
        finally:
            await client.close()

    run(scenario())
