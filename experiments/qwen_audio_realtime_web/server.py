"""Local-only aiohttp server for the Qwen Audio Realtime web spike."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Callable, Collection, Sequence
from urllib.parse import urlsplit

from aiohttp import web

if __package__ in {None, ""}:
    # Support the documented direct-file launch without importing the spike
    # from the voice-agent runtime.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from experiments.qwen_audio_realtime_web.capability_profile import (  # type: ignore
        fake_capability_profile,
        qwen_capability_profile,
    )
    from experiments.qwen_audio_realtime_web.fake_provider import (  # type: ignore
        FakeRealtimeProvider,
    )
    from experiments.qwen_audio_realtime_web.provider_adapter import (  # type: ignore
        QwenRealtimeProvider,
        RealtimeProviderSession,
        SafeProviderError,
    )
    from experiments.qwen_audio_realtime_web.session_bridge import (  # type: ignore
        BridgeConfig,
        SessionBridge,
    )
else:
    from .capability_profile import fake_capability_profile, qwen_capability_profile
    from .fake_provider import FakeRealtimeProvider
    from .provider_adapter import (
        QwenRealtimeProvider,
        RealtimeProviderSession,
        SafeProviderError,
    )
    from .session_bridge import BridgeConfig, SessionBridge


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
PROVIDER_MODES = frozenset({"fake", "real"})
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_STATIC_DIR = Path(__file__).resolve().parent / "static"

_PROVIDER_FACTORY_KEY = "qwen_spike.provider_factory"
_PROVIDER_MODE_KEY = "qwen_spike.provider_mode"
_BRIDGE_CONFIG_KEY = "qwen_spike.bridge_config"
_ALLOWED_ORIGINS_KEY = "qwen_spike.allowed_origins"
_ACTIVE_BRIDGES_KEY = "qwen_spike.active_bridges"

ProviderFactory = Callable[[], RealtimeProviderSession]


@web.middleware
async def _security_headers_middleware(
    request: web.Request, handler: Callable[[web.Request], object]
) -> web.StreamResponse:
    response = await handler(request)  # type: ignore[arg-type]
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "microphone=(self)"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "worker-src 'self'; connect-src 'self' ws://127.0.0.1:* "
        "ws://localhost:*; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    )
    return response


def create_app(
    *,
    provider_mode: str = "fake",
    bridge_config: BridgeConfig | None = None,
    provider_factory: ProviderFactory | None = None,
    allowed_origins: Collection[str] | None = None,
) -> web.Application:
    """Create a local static-site + browser WebSocket application.

    ``provider_factory`` is an explicit test seam and must create a fresh
    provider session for each browser connection.
    """

    if provider_mode not in PROVIDER_MODES:
        raise ValueError("provider_mode must be fake or real")
    config = bridge_config or BridgeConfig()
    if provider_factory is None:
        provider_factory = _default_provider_factory(provider_mode)

    app = web.Application(
        middlewares=[_security_headers_middleware],
        client_max_size=config.max_control_frame_bytes,
    )
    app[_PROVIDER_FACTORY_KEY] = provider_factory
    app[_PROVIDER_MODE_KEY] = provider_mode
    app[_BRIDGE_CONFIG_KEY] = config
    app[_ALLOWED_ORIGINS_KEY] = (
        frozenset(allowed_origins) if allowed_origins is not None else None
    )
    app[_ACTIVE_BRIDGES_KEY] = set()
    app.router.add_get("/", _index_handler)
    app.router.add_get("/favicon.ico", _favicon_handler)
    app.router.add_get("/healthz", _health_handler)
    app.router.add_get("/ws", _websocket_handler)
    if _STATIC_DIR.is_dir():
        app.router.add_static(
            "/static/",
            path=_STATIC_DIR,
            name="qwen-spike-static",
            show_index=False,
            follow_symlinks=False,
        )
    app.on_cleanup.append(_cleanup_bridges)
    return app


def _default_provider_factory(provider_mode: str) -> ProviderFactory:
    if provider_mode == "fake":
        return FakeRealtimeProvider
    return QwenRealtimeProvider.from_environment


async def _index_handler(_request: web.Request) -> web.StreamResponse:
    index_path = _STATIC_DIR / "index.html"
    if not index_path.is_file():
        raise web.HTTPServiceUnavailable(text="spike static assets unavailable")
    return web.FileResponse(index_path)


async def _favicon_handler(_request: web.Request) -> web.Response:
    """Avoid a noisy browser-console 404 without adding a tracked asset."""

    return web.Response(status=204)


async def _health_handler(request: web.Request) -> web.Response:
    provider_mode = request.app[_PROVIDER_MODE_KEY]
    profile = (
        fake_capability_profile()
        if provider_mode == "fake"
        else qwen_capability_profile()
    )
    return web.json_response(
        {
            "status": "ok",
            "scope": "isolated_qwen_audio_realtime_web_spike",
            "provider_mode": provider_mode,
            "output_mode": profile.output_mode,
            "capabilities": profile.to_metadata(),
        }
    )


async def _websocket_handler(request: web.Request) -> web.StreamResponse:
    if not _loopback_request_host(request.host):
        raise web.HTTPForbidden(text="loopback host required")
    if not _origin_allowed(request, request.app[_ALLOWED_ORIGINS_KEY]):
        raise web.HTTPForbidden(text="same-port loopback origin required")

    config: BridgeConfig = request.app[_BRIDGE_CONFIG_KEY]
    websocket = web.WebSocketResponse(
        heartbeat=15.0,
        autoping=True,
        autoclose=True,
        compress=False,
        max_msg_size=max(
            config.max_input_frame_bytes, config.max_control_frame_bytes
        ),
    )
    await websocket.prepare(request)

    try:
        provider = request.app[_PROVIDER_FACTORY_KEY]()
    except SafeProviderError as error:
        await websocket.send_json(
            {
                "type": "session.error",
                "code": error.code,
                "terminal": True,
                "retryable": error.retryable,
                "provider_mode": request.app[_PROVIDER_MODE_KEY],
                "output_mode": "degraded",
                "playback_epoch": 0,
            }
        )
        await websocket.close(code=1011, message=b"provider configuration failed")
        return websocket
    except Exception:
        await websocket.send_json(
            {
                "type": "session.error",
                "code": "provider_configuration_failed",
                "terminal": True,
                "retryable": False,
                "provider_mode": request.app[_PROVIDER_MODE_KEY],
                "output_mode": "degraded",
                "playback_epoch": 0,
            }
        )
        await websocket.close(code=1011, message=b"provider configuration failed")
        return websocket

    bridge = SessionBridge(websocket, provider, config=config)
    active_bridges: set[SessionBridge] = request.app[_ACTIVE_BRIDGES_KEY]
    active_bridges.add(bridge)
    try:
        await bridge.run()
    finally:
        active_bridges.discard(bridge)
    return websocket


async def _cleanup_bridges(app: web.Application) -> None:
    bridges: set[SessionBridge] = set(app[_ACTIVE_BRIDGES_KEY])
    if bridges:
        await asyncio.gather(*(bridge.close() for bridge in bridges))
    app[_ACTIVE_BRIDGES_KEY].clear()


def _loopback_request_host(host_header: str) -> bool:
    try:
        parsed = urlsplit(f"//{host_header}")
        return parsed.hostname in _LOOPBACK_HOSTS
    except ValueError:
        return False


def _origin_allowed(
    request: web.Request, configured_origins: frozenset[str] | None
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
        description="Run the isolated Qwen Audio Realtime browser spike."
    )
    parser.add_argument(
        "--provider",
        choices=sorted(PROVIDER_MODES),
        default=os.environ.get("QWEN_REALTIME_PROVIDER", "fake"),
        help="fake (default) or real",
    )
    parser.add_argument(
        "--host",
        choices=("127.0.0.1", "localhost"),
        default=DEFAULT_HOST,
        help="loopback bind host only",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.provider not in PROVIDER_MODES:
        parser.error("provider must be fake or real")
    if not 1 <= args.port <= 65_535:
        parser.error("port must be between 1 and 65535")
    app = create_app(provider_mode=args.provider)
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
