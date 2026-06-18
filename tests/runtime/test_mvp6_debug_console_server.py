from __future__ import annotations

import http.client
import json
from pathlib import Path
import threading
import wave

from voice_agent.runtime.mvp6_debug_console_api import MVP6DebugConsoleConfig
from voice_agent.runtime.mvp6_debug_console_server import create_mvp6_http_server


def test_status_endpoint_returns_json(tmp_path: Path) -> None:
    server, thread = _start_server(tmp_path)
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
        connection.request("GET", "/api/status")
        response = connection.getresponse()
        body = json.loads(response.read().decode("utf-8"))
        assert response.status == 200
        assert body["default_provider_mode"] == "fake"
        assert body["metadata_only_output"] is True
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_root_serves_debug_console_html(tmp_path: Path) -> None:
    server, thread = _start_server(tmp_path)
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
        connection.request("GET", "/")
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        assert response.status == 200
        assert "MVP6 Local Debug Console" in body
        assert "Record" in body
        assert "Run" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_run_endpoint_accepts_multipart_audio(tmp_path: Path) -> None:
    wav_path = tmp_path / "http-run.wav"
    wav_bytes = _write_wav_file(wav_path)
    boundary = "mvp6boundary"
    body = _multipart_body(
        boundary=boundary,
        fields={
            "provider_mode": "fake",
            "expected_route": "FAST_ONLY",
            "save_qa_history": "true",
        },
        file_field="audio",
        file_name="browser-draft.wav",
        file_content_type="audio/wav",
        file_bytes=wav_bytes,
    )
    server, thread = _start_server(tmp_path)
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
        connection.request(
            "POST",
            "/api/runs",
            body=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        assert response.status == 200
        assert payload["status"] == "completed"
        assert payload["actual_route"] == "FAST_ONLY"
        assert "browser-draft.wav" not in json.dumps(payload, sort_keys=True)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_run_endpoint_rejects_non_utf8_text_field_safely(tmp_path: Path) -> None:
    wav_path = tmp_path / "http-run-invalid-field.wav"
    wav_bytes = _write_wav_file(wav_path)
    boundary = "mvp6boundary"
    body = _multipart_body(
        boundary=boundary,
        fields={},
        file_field="audio",
        file_name="browser-draft.wav",
        file_content_type="audio/wav",
        file_bytes=wav_bytes,
    )
    body = body.replace(
        f"--{boundary}--\r\n".encode("ascii"),
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="provider_mode"\r\n\r\n'
        ).encode("ascii")
        + b"\xff\r\n"
        + f"--{boundary}--\r\n".encode("ascii"),
    )
    server, thread = _start_server(tmp_path)
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
        connection.request(
            "POST",
            "/api/runs",
            body=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        assert response.status == 400
        assert payload["status"] == "failed"
        assert "browser-draft.wav" not in json.dumps(payload, sort_keys=True)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_cli_help_lists_local_console_options() -> None:
    import subprocess

    result = subprocess.run(
        ["scripts/mvp6-debug-console", "--help"],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "--approval-packet" in result.stdout
    assert "--output-root" in result.stdout
    assert "--host" in result.stdout
    assert "--port" in result.stdout


def _start_server(tmp_path: Path):
    config = MVP6DebugConsoleConfig(output_root=tmp_path / "outputs" / "mvp6-debug-console")
    server = create_mvp6_http_server(config=config, env={}, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _write_wav_file(path: Path) -> bytes:
    frames = b"\x00\x00" * 1600
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(frames)
    return path.read_bytes()


def _multipart_body(
    *,
    boundary: str,
    fields: dict[str, str],
    file_field: str,
    file_name: str,
    file_content_type: str,
    file_bytes: bytes,
) -> bytes:
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode("ascii"))
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"))
        chunks.append(value.encode("utf-8") + b"\r\n")
    chunks.append(f"--{boundary}\r\n".encode("ascii"))
    chunks.append(
        (
            f'Content-Disposition: form-data; name="{file_field}"; filename="{file_name}"\r\n'
            f"Content-Type: {file_content_type}\r\n\r\n"
        ).encode("ascii")
    )
    chunks.append(file_bytes + b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks)
