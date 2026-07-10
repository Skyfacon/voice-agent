from __future__ import annotations

import argparse
from collections.abc import Mapping
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from typing import Any

from voice_agent.runtime.mvp6_debug_console_api import (
    MVP6DebugConsoleConfig,
    MVP6DebugConsoleError,
    MVP6RunRequest,
    build_mvp6_status_response,
    run_mvp6_debug_console_audio,
)
from voice_agent.runtime.mvp6_debug_console_history import (
    clear_mvp6_qa_history,
    read_mvp6_qa_history,
)
from voice_agent.runtime.mvp6_debug_console_static import MVP6_DEBUG_CONSOLE_HTML


_LOCAL_BIND_HOSTS = {"127.0.0.1", "localhost", "::1"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the MVP6 local debug console.")
    parser.add_argument("--approval-packet", default=None, help="Local-only approval packet JSON path.")
    parser.add_argument(
        "--output-root",
        default="outputs/mvp6-debug-console",
        help="Ignored local output root.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Local bind host.")
    parser.add_argument("--port", type=int, default=8766, help="Local bind port.")
    args = parser.parse_args(argv)
    approval_packet = (
        _load_approval_packet(Path(args.approval_packet))
        if args.approval_packet
        else None
    )
    config = MVP6DebugConsoleConfig(
        output_root=Path(args.output_root),
        approval_packet=approval_packet,
        bind_host=args.host,
    )
    server = create_mvp6_http_server(
        config=config,
        env=os.environ,
        host=args.host,
        port=args.port,
    )
    print(f"MVP6 debug console listening on http://{args.host}:{server.server_address[1]}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    return 0


def create_mvp6_http_server(
    *,
    config: MVP6DebugConsoleConfig,
    env: Mapping[str, str],
    host: str,
    port: int,
) -> ThreadingHTTPServer:
    if host not in _LOCAL_BIND_HOSTS:
        raise ValueError("MVP6 debug console must bind to localhost")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/":
                self._send_html(MVP6_DEBUG_CONSOLE_HTML)
                return
            if self.path == "/api/status":
                self._send_json(build_mvp6_status_response(config, env=env))
                return
            if self.path == "/api/history":
                self._send_json({"entries": read_mvp6_qa_history(config.history_path)})
                return
            self._send_json_error(404, "not_found")

        def do_POST(self) -> None:
            if self.path == "/api/history/clear":
                clear_mvp6_qa_history(config.history_path)
                self._send_json({"status": "cleared"})
                return
            if self.path == "/api/runs":
                try:
                    fields = _parse_multipart(self)
                    audio = fields.get("audio")
                    if not isinstance(audio, bytes):
                        raise MVP6DebugConsoleError("audio is required")
                    payload = run_mvp6_debug_console_audio(
                        config=config,
                        request=MVP6RunRequest(
                            audio_bytes=audio,
                            audio_mime_type=str(fields.get("audio_content_type", "audio/wav")),
                            provider_mode=str(fields.get("provider_mode", "fake")),
                            expected_route=str(fields.get("expected_route", "auto")),
                            save_qa_history=_bool_field(fields.get("save_qa_history", "true")),
                            show_model_io=_bool_field(fields.get("show_model_io", "false")),
                            active_task_id=_optional_string(fields.get("active_task_id")),
                            active_plan_version=_optional_int(fields.get("active_plan_version")),
                            active_task_event_seq=_optional_int(
                                fields.get("active_task_event_seq")
                            ),
                            active_lifecycle_phase=str(
                                fields.get("active_lifecycle_phase", "PLANNING")
                            ),
                        ),
                        env=env,
                    )
                except MVP6DebugConsoleError as exc:
                    self._send_json_error(400, _safe_error_message(exc))
                    return
                except Exception as exc:
                    self._send_json_error(500, _safe_error_message(exc))
                    return
                self._send_json(payload)
                return
            self._send_json_error(404, "not_found")

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_json(self, payload: Mapping[str, Any]) -> None:
            body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_json_error(self, status: int, reason: str) -> None:
            body = json.dumps(
                {"status": "failed", "failure_reason": reason},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ThreadingHTTPServer((host, port), Handler)


def _parse_multipart(handler: BaseHTTPRequestHandler) -> dict[str, object]:
    content_type = handler.headers.get("Content-Type", "")
    if "multipart/form-data" not in content_type:
        raise MVP6DebugConsoleError("multipart form-data is required")
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError as exc:
        raise MVP6DebugConsoleError("content length is invalid") from exc
    if length <= 0:
        raise MVP6DebugConsoleError("request body is required")

    raw_body = handler.rfile.read(length)
    message = BytesParser(policy=default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("ascii")
        + raw_body
    )
    fields: dict[str, object] = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        payload = part.get_payload(decode=True) or b""
        if name == "audio":
            fields["audio"] = payload
            fields["audio_content_type"] = part.get_content_type()
        else:
            try:
                fields[name] = payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise MVP6DebugConsoleError("multipart text field is invalid") from exc
    return fields


def _optional_string(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value))
    except ValueError as exc:
        raise MVP6DebugConsoleError("integer field is invalid") from exc


def _bool_field(value: object) -> bool:
    return str(value).lower() == "true"


def _safe_error_message(exc: Exception) -> str:
    message = str(exc) or exc.__class__.__name__
    lowered = message.lower()
    if any(marker in lowered for marker in ("/users/", "/private/", "file://", "data:")):
        return "request_failed_safely"
    return message


def _load_approval_packet(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload, dict):
        raise MVP6DebugConsoleError("approval packet must be a JSON object")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
