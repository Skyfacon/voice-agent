"""Loopback-only server for Fake/enforced and Qwen dual-session modes."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable, Collection, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from aiohttp import WSMsgType, web

if __package__ in {None, ""}:
    _REPO_ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(_REPO_ROOT))
    sys.path.insert(0, str(_REPO_ROOT / "src"))
    from experiments.qwen_realtime_fast_slow_web.browser_protocol import (  # type: ignore
        BrowserProtocolError,
        DEFAULT_MAX_CONTROL_FRAME_BYTES,
        DEFAULT_MAX_INPUT_FRAME_BYTES,
        decode_browser_control,
        safe_code,
        safe_error_message,
        validate_input_audio_frame,
    )
    from experiments.qwen_realtime_fast_slow_web.capability_profile import (  # type: ignore
        fake_capability_profile,
        fake_shadow_capability_profile,
        qwen_enforced_control_capability_profile,
        qwen_shadow_capability_profile,
        qwen_voice_capability_profile,
    )
    from experiments.qwen_realtime_fast_slow_web.fake_provider import (  # type: ignore
        FakeRealtimeProvider,
    )
    from experiments.qwen_realtime_fast_slow_web.provider_context import (  # type: ignore
        CredentialHandle,
        ProviderConfigurationError,
    )
    from experiments.qwen_realtime_fast_slow_web.qwen_shadow_router_adapter import (  # type: ignore
        ENFORCED_CONTROL_MODE,
        FakeShadowControlProvider,
        QwenShadowRouterAdapter,
    )
    from experiments.qwen_realtime_fast_slow_web.qwen_voice_adapter import (  # type: ignore
        QwenVoiceAdapter,
    )
    from experiments.qwen_realtime_fast_slow_web.session_coordinator import (  # type: ignore
        CoordinatorConfig,
        RealtimeSessionCoordinator,
    )
else:
    from .browser_protocol import (
        BrowserProtocolError,
        DEFAULT_MAX_CONTROL_FRAME_BYTES,
        DEFAULT_MAX_INPUT_FRAME_BYTES,
        decode_browser_control,
        safe_code,
        safe_error_message,
        validate_input_audio_frame,
    )
    from .capability_profile import (
        fake_capability_profile,
        fake_shadow_capability_profile,
        qwen_enforced_control_capability_profile,
        qwen_shadow_capability_profile,
        qwen_voice_capability_profile,
    )
    from .fake_provider import FakeRealtimeProvider
    from .provider_context import CredentialHandle, ProviderConfigurationError
    from .qwen_shadow_router_adapter import (
        ENFORCED_CONTROL_MODE,
        FakeShadowControlProvider,
        QwenShadowRouterAdapter,
    )
    from .qwen_voice_adapter import QwenVoiceAdapter
    from .session_coordinator import CoordinatorConfig, RealtimeSessionCoordinator


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8767
PROVIDER_MODES = frozenset({"fake", "qwen"})
ROUTING_MODES = frozenset({"enforced", "shadow"})
SLOW_RUNTIME_MODES = frozenset({"mock"})
AUDIO_OUTPUT_MODES = frozenset({"qwen", "fake_pcm", "none"})
SHADOW_CONTROL_MODES = frozenset({"dual_session", "dual_session_shadow"})
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_STATIC_DIR = Path(__file__).resolve().parent / "static"

_PROVIDER_FACTORY_KEY = "qfs.provider_factory"
_SHADOW_PROVIDER_FACTORY_KEY = "qfs.shadow_provider_factory"
_PROVIDER_MODE_KEY = "qfs.provider_mode"
_ROUTING_MODE_KEY = "qfs.routing_mode"
_SLOW_RUNTIME_MODE_KEY = "qfs.slow_runtime_mode"
_AUDIO_OUTPUT_KEY = "qfs.audio_output"
_SHADOW_CONTROL_MODE_KEY = "qfs.shadow_control_mode"
_COORDINATOR_CONFIG_KEY = "qfs.coordinator_config"
_ALLOWED_ORIGINS_KEY = "qfs.allowed_origins"
_ACTIVE_COORDINATORS_KEY = "qfs.active_coordinators"

ProviderFactory = Callable[[], Any]
ShadowProviderFactory = Callable[[], Any]


@web.middleware
async def _security_headers_middleware(
    request: web.Request,
    handler: Callable[[web.Request], Any],
) -> web.StreamResponse:
    response = await handler(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "microphone=(self)"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "worker-src 'self'; connect-src 'self' ws://127.0.0.1:* "
        "ws://localhost:*; object-src 'none'; base-uri 'none'; "
        "frame-ancestors 'none'"
    )
    return response


def create_app(
    *,
    provider_mode: str = "fake",
    routing_mode: str = "enforced",
    slow_runtime_mode: str = "mock",
    audio_output: str | None = None,
    shadow_control_mode: str = "dual_session",
    coordinator_config: CoordinatorConfig | None = None,
    provider_factory: ProviderFactory | None = None,
    shadow_provider_factory: ShadowProviderFactory | None = None,
    allowed_origins: Collection[str] | None = None,
) -> web.Application:
    """Create a static page + WebSocket app with one coordinator per socket."""

    if provider_mode not in PROVIDER_MODES:
        raise ValueError("provider_mode must be fake or qwen")
    if routing_mode not in ROUTING_MODES:
        raise ValueError("routing_mode must be enforced or shadow")
    if slow_runtime_mode not in SLOW_RUNTIME_MODES:
        raise ValueError("slow_runtime_mode must be mock")
    resolved_audio_output = audio_output or (
        "qwen" if provider_mode == "qwen" else "fake_pcm"
    )
    if resolved_audio_output not in AUDIO_OUTPUT_MODES:
        raise ValueError("audio_output must be qwen, fake_pcm, or none")
    if provider_mode == "qwen" and routing_mode == "enforced":
        if resolved_audio_output != "none":
            raise ValueError("qwen_enforced_provider_audio_unsupported")
        if slow_runtime_mode != "mock":
            raise ValueError("qwen_enforced_slow_runtime_mock_required")
    if shadow_control_mode not in SHADOW_CONTROL_MODES:
        raise ValueError("shadow_control_mode_unsupported")
    resolved_shadow_control_mode = (
        "dual_session_enforced_control"
        if provider_mode == "qwen" and routing_mode == "enforced"
        else ("dual_session_shadow" if routing_mode == "shadow" else "none")
    )
    config = coordinator_config or CoordinatorConfig()
    if provider_mode == "qwen" and provider_factory is None:
        raise ValueError("qwen_provider_factory_required")
    factory = provider_factory or FakeRealtimeProvider
    if routing_mode == "shadow" or (
        provider_mode == "qwen" and routing_mode == "enforced"
    ):
        if shadow_provider_factory is None and provider_mode == "qwen":
            raise ValueError("qwen_shadow_provider_factory_required")
        shadow_factory = shadow_provider_factory or FakeShadowControlProvider
    else:
        shadow_factory = None
    app = web.Application(
        middlewares=[_security_headers_middleware],
        client_max_size=max(
            DEFAULT_MAX_CONTROL_FRAME_BYTES,
            DEFAULT_MAX_INPUT_FRAME_BYTES,
        ),
    )
    app[_PROVIDER_FACTORY_KEY] = factory
    app[_SHADOW_PROVIDER_FACTORY_KEY] = shadow_factory
    app[_PROVIDER_MODE_KEY] = provider_mode
    app[_ROUTING_MODE_KEY] = routing_mode
    app[_SLOW_RUNTIME_MODE_KEY] = slow_runtime_mode
    app[_AUDIO_OUTPUT_KEY] = resolved_audio_output
    app[_SHADOW_CONTROL_MODE_KEY] = resolved_shadow_control_mode
    app[_COORDINATOR_CONFIG_KEY] = config
    app[_ALLOWED_ORIGINS_KEY] = (
        frozenset(allowed_origins) if allowed_origins is not None else None
    )
    app[_ACTIVE_COORDINATORS_KEY] = set()
    app.router.add_get("/", _index_handler)
    app.router.add_get("/favicon.ico", _favicon_handler)
    app.router.add_get("/healthz", _health_handler)
    app.router.add_get("/ws", _websocket_handler)
    if _STATIC_DIR.is_dir():
        app.router.add_static(
            "/static/",
            path=_STATIC_DIR,
            name="qfs-static",
            show_index=False,
            follow_symlinks=False,
        )
    app.on_cleanup.append(_cleanup_coordinators)
    return app


async def _index_handler(_request: web.Request) -> web.StreamResponse:
    index_path = _STATIC_DIR / "index.html"
    if not index_path.is_file():
        raise web.HTTPServiceUnavailable(text="spike static assets unavailable")
    return web.FileResponse(index_path)


async def _favicon_handler(_request: web.Request) -> web.Response:
    return web.Response(status=204)


async def _health_handler(request: web.Request) -> web.Response:
    provider_mode = request.app[_PROVIDER_MODE_KEY]
    routing_mode = request.app[_ROUTING_MODE_KEY]
    if provider_mode == "qwen":
        profile = qwen_voice_capability_profile(
            enforced_output_suppression=(routing_mode == "enforced")
        )
    else:
        profile = fake_capability_profile()
    shadow_profile = None
    if routing_mode == "shadow" or (
        provider_mode == "qwen" and routing_mode == "enforced"
    ):
        if provider_mode == "qwen" and routing_mode == "enforced":
            shadow_profile = qwen_enforced_control_capability_profile()
        elif provider_mode == "qwen":
            shadow_profile = qwen_shadow_capability_profile()
        else:
            shadow_profile = fake_shadow_capability_profile()
    profiles_ready = profile.health_status == "ready" and (
        shadow_profile is None or shadow_profile.health_status == "ready"
    )
    return web.json_response(
        {
            "status": "ok" if profiles_ready else str(profile.health_status),
            "scope": (
                "qwen_realtime_fast_slow_integration_spike_slice3a"
                if provider_mode == "qwen" and routing_mode == "enforced"
                else "qwen_realtime_fast_slow_integration_spike_slice2"
            ),
            "provider_mode": provider_mode,
            "routing_mode": routing_mode,
            "slow_runtime_mode": request.app[_SLOW_RUNTIME_MODE_KEY],
            "audio_output": request.app[_AUDIO_OUTPUT_KEY],
            "shadow_control_mode": request.app[_SHADOW_CONTROL_MODE_KEY],
            "control_topology": request.app[_SHADOW_CONTROL_MODE_KEY],
            "experimental": provider_mode == "qwen" and routing_mode == "enforced",
            "provider_native_audio_disabled": (
                provider_mode == "qwen" and routing_mode == "enforced"
            ),
            "output_mode": profile.output_mode,
            "degraded": not profiles_ready,
            "capabilities": profile.to_metadata(),
            "shadow_capabilities": (
                shadow_profile.to_metadata() if shadow_profile is not None else None
            ),
        }
    )


async def _websocket_handler(request: web.Request) -> web.StreamResponse:
    if not _loopback_request_host(request.host):
        raise web.HTTPForbidden(text="loopback host required")
    if not _origin_allowed(request, request.app[_ALLOWED_ORIGINS_KEY]):
        raise web.HTTPForbidden(text="same-port loopback origin required")
    websocket = web.WebSocketResponse(
        heartbeat=15.0,
        autoping=True,
        autoclose=True,
        compress=False,
        max_msg_size=max(
            DEFAULT_MAX_CONTROL_FRAME_BYTES,
            DEFAULT_MAX_INPUT_FRAME_BYTES,
        ),
    )
    await websocket.prepare(request)
    coordinator: RealtimeSessionCoordinator | None = None
    try:
        provider = request.app[_PROVIDER_FACTORY_KEY]()
        shadow_factory = request.app[_SHADOW_PROVIDER_FACTORY_KEY]
        shadow_provider = shadow_factory() if shadow_factory is not None else None
        coordinator = RealtimeSessionCoordinator(
            websocket,
            provider,
            shadow_provider=shadow_provider,
            provider_mode=request.app[_PROVIDER_MODE_KEY],
            routing_mode=request.app[_ROUTING_MODE_KEY],
            audio_output=request.app[_AUDIO_OUTPUT_KEY],
            shadow_control_mode=request.app[_SHADOW_CONTROL_MODE_KEY],
            config=request.app[_COORDINATOR_CONFIG_KEY],
        )
        await coordinator.start()
    except Exception:
        if coordinator is not None:
            await coordinator.close()
        await websocket.send_json(
            safe_error_message(
                "session_initialization_failed",
                terminal=True,
                retryable=False,
                playback_epoch=0,
            )
        )
        await websocket.close(code=1011, message=b"session initialization failed")
        return websocket

    assert coordinator is not None
    active: set[RealtimeSessionCoordinator] = request.app[_ACTIVE_COORDINATORS_KEY]
    active.add(coordinator)
    try:
        async for message in websocket:
            if message.type == WSMsgType.TEXT:
                try:
                    payload = decode_browser_control(message.data)
                    await coordinator.handle_control(payload)
                except BrowserProtocolError as error:
                    await coordinator.report_safe_error(error.code)
                except ValueError as error:
                    await coordinator.report_safe_error(
                        safe_code(str(error), fallback="control_value_invalid")
                    )
                except Exception:
                    await coordinator.report_safe_error("control_processing_failed")
                if coordinator.state.disconnect_requested:
                    break
                continue
            if message.type == WSMsgType.BINARY:
                try:
                    frame = validate_input_audio_frame(message.data)
                    await coordinator.submit_audio(frame)
                except BrowserProtocolError as error:
                    await coordinator.report_safe_error(error.code)
                except Exception:
                    await coordinator.report_safe_error("audio_frame_processing_failed")
                continue
            if message.type in {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR}:
                break
    finally:
        active.discard(coordinator)
        await coordinator.close()
        if not websocket.closed:
            await websocket.close(code=1000, message=b"session closed")
    return websocket


async def _cleanup_coordinators(app: web.Application) -> None:
    coordinators: set[RealtimeSessionCoordinator] = set(
        app[_ACTIVE_COORDINATORS_KEY]
    )
    if coordinators:
        await asyncio.gather(
            *(coordinator.close() for coordinator in coordinators),
            return_exceptions=True,
        )
    app[_ACTIVE_COORDINATORS_KEY].clear()


def _loopback_request_host(host_header: str) -> bool:
    try:
        return urlsplit(f"//{host_header}").hostname in _LOOPBACK_HOSTS
    except ValueError:
        return False


def _origin_allowed(
    request: web.Request,
    configured_origins: frozenset[str] | None,
) -> bool:
    origin = request.headers.get("Origin")
    if not origin:
        return False
    if configured_origins is not None:
        return origin in configured_origins
    try:
        origin_parts = urlsplit(origin)
        request_parts = urlsplit(f"//{request.host}")
        if origin_parts.scheme not in {"http", "https"}:
            return False
        if origin_parts.hostname not in _LOOPBACK_HOSTS:
            return False
        if request_parts.hostname not in _LOOPBACK_HOSTS:
            return False
        origin_port = origin_parts.port or (443 if origin_parts.scheme == "https" else 80)
        request_port = request_parts.port or (443 if request.secure else 80)
        return origin_port == request_port
    except ValueError:
        return False


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the Qwen Realtime Fast/Slow Slice 3A spike. Qwen proposals are "
            "non-authoritative; the local Router and Gate remain authoritative."
        )
    )
    parser.add_argument("--provider", choices=("fake", "qwen"), default="fake")
    parser.add_argument("--routing", choices=("enforced", "shadow"), default=None)
    parser.add_argument("--slow-runtime", choices=("mock",), default="mock")
    parser.add_argument(
        "--audio-output", choices=("qwen", "fake_pcm", "none"), default=None
    )
    parser.add_argument(
        "--shadow-control",
        choices=("dual_session", "dual_session_shadow"),
        default="dual_session",
    )
    parser.add_argument("--workspace-id", default=None)
    parser.add_argument("--qwen-base-url", default=None)
    parser.add_argument("--verified-workspace-id", default=None)
    parser.add_argument("--voice", default="longanqian")
    parser.add_argument(
        "--host",
        choices=("127.0.0.1", "localhost"),
        default=DEFAULT_HOST,
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65_535:
        parser.error("port must be between 1 and 65535")
    routing_mode = args.routing or (
        "shadow" if args.provider == "qwen" else "enforced"
    )
    audio_output = args.audio_output or (
        "qwen" if args.provider == "qwen" else "fake_pcm"
    )
    provider_factory: ProviderFactory | None = None
    shadow_provider_factory: ShadowProviderFactory | None = None
    if args.provider == "qwen":
        if routing_mode == "enforced" and args.audio_output != "none":
            parser.error("qwen_enforced_provider_audio_unsupported")
        try:
            credentials = CredentialHandle.resolve(
                safe_base_url=args.qwen_base_url,
                explicit_workspace_id=args.workspace_id,
                verified_workspace_id=args.verified_workspace_id,
            )
        except ProviderConfigurationError as error:
            parser.error(error.code)
        provider_factory = lambda: QwenVoiceAdapter(
            credentials,
            voice=args.voice,
            enforced_output_suppression=(routing_mode == "enforced"),
        )
        shadow_provider_factory = lambda: QwenShadowRouterAdapter(
            credentials,
            control_mode=(
                ENFORCED_CONTROL_MODE
                if routing_mode == "enforced"
                else "dual_session_shadow"
            ),
        )
    elif routing_mode == "shadow":
        provider_factory = FakeRealtimeProvider
        shadow_provider_factory = FakeShadowControlProvider
    app = create_app(
        provider_mode=args.provider,
        routing_mode=routing_mode,
        slow_runtime_mode=args.slow_runtime,
        audio_output=audio_output,
        shadow_control_mode=args.shadow_control,
        provider_factory=provider_factory,
        shadow_provider_factory=shadow_provider_factory,
    )
    web.run_app(
        app,
        host=args.host,
        port=args.port,
        access_log=None,
        print=lambda message: print(message, flush=True),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "PROVIDER_MODES",
    "ProviderFactory",
    "create_app",
    "main",
]
