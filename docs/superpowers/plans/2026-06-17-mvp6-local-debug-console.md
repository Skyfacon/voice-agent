# MVP6 Local Debug Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build MVP6, a local-only Python debug console with browser microphone recording, explicit Run/Clear controls, provider-free and DashScope live routing modes, pipeline metadata display, and local-only QA history.

**Architecture:** Use a Python standard-library localhost server that serves embedded plain HTML/JS and exposes a small JSON/multipart API. The API writes uploaded audio to an ignored local output root, delegates routing to the existing MVP5 single-audio runtime, returns metadata/debug display only, and writes a local-only QA jsonl history without raw audio or provider bodies.

**Tech Stack:** Python 3.11 standard library HTTP, existing `voice_agent.runtime.mvp5_*` modules, plain HTML/CSS/JavaScript, repository test entrypoint `./scripts/test`.

---

## File Structure

- Create `src/voice_agent/runtime/mvp6_debug_console_history.py`
  - Owns QA history entry schema, redaction validation, append/read/clear operations.
- Create `src/voice_agent/runtime/mvp6_debug_console_api.py`
  - Owns status responses, run request validation, provider mode gating, temporary wav writes, MVP5 runtime delegation, question text resolution, and response safety validation.
- Create `src/voice_agent/runtime/mvp6_debug_console_static.py`
  - Owns embedded HTML/CSS/JS for the local debug console.
- Create `src/voice_agent/runtime/mvp6_debug_console_server.py`
  - Owns localhost HTTP server, route dispatch, JSON/multipart parsing, and CLI orchestration helpers.
- Create `scripts/mvp6-debug-console`
  - Thin executable wrapper around the server module.
- Create `tests/runtime/test_mvp6_debug_console_history.py`
  - Covers history writes, reads, clear behavior, and forbidden value rejection.
- Create `tests/runtime/test_mvp6_debug_console_status.py`
  - Covers safe startup status and live-provider readiness metadata.
- Create `tests/runtime/test_mvp6_debug_console_runs.py`
  - Covers run request validation, provider-free delegation, live gate failures, pipeline response shape, and safety validation.
- Create `tests/runtime/test_mvp6_debug_console_server.py`
  - Covers HTTP status/root/run/history endpoints without real provider calls.
- Create `tests/runtime/test_mvp6_debug_console_static.py`
  - Covers required page controls and browser-side state labels.
- Create `tests/acceptance/test_mvp6_acceptance_scenarios.py`
  - Covers the MVP6 acceptance scenario list and architecture stop conditions.
- Create `docs/implementation/mvp6-local-debug-console.md`
  - Documents how to run the local console, approval packet shape, safe output policy, QA history, and non-goals.
- Modify `src/voice_agent/runtime/mvp5_real_voice_e2e_smoke.py`
  - Add one public helper for deterministic provider-free transports so MVP6 does not import test helpers or duplicate transport construction.
- Modify `.gitignore` only if `outputs/` is not already ignored. Current repo already ignores `outputs/`, so this should remain unchanged unless verification proves otherwise.

## Implementation Notes

- Do not add canonical events or RouterDecision values.
- Do not call DashScope directly from MVP6 code. Live calls must continue through MVP5 adapter/runtime boundaries.
- Default tests must not call providers or read real secrets.
- Use `./scripts/test`, not direct `pytest`.
- Keep all local debug artifacts under `outputs/mvp6-debug-console/`.
- API responses may include `question_text` only as local debug data. Do not copy it into MVP5 summaries, replay fixtures, or committed artifacts.
- For real DashScope mode, resolve ASR question text only through a lazy process-local adapter resolver, and only for the local debug console response/history.
- Browser recording must create an `audio/wav` blob in memory before upload.

### Shared Test Helpers

When a task needs a wav fixture, place this helper in that test file or a local test helper block:

```python
from pathlib import Path
import wave


def _write_wav_file(path: Path) -> bytes:
    frames = b"\x00\x00" * 1600
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(frames)
    return path.read_bytes()
```

Use this approval packet helper in tests that need live-mode readiness metadata:

```python
def _approval_packet() -> dict[str, object]:
    return {
        "approval_id": "mvp6-local-debug-console-test",
        "live_provider_opt_in": True,
        "local_wav_opt_in": True,
        "metadata_only_output": True,
        "replay_reruns_provider": False,
        "provider_adapter_ids": ["mvp5_asr_adapter", "mvp5_thinker_adapter"],
        "credential_env_var_name": "MVP6_TEST_PROVIDER_KEY",
        "max_provider_calls": 2,
        "timeout_ms": 30000,
        "safe_output_ref": "summary://mvp6/debug-console/test",
    }
```

## Task 1: QA History Module

**Files:**
- Create: `src/voice_agent/runtime/mvp6_debug_console_history.py`
- Test: `tests/runtime/test_mvp6_debug_console_history.py`

- [ ] **Step 1: Write failing history tests**

Create `tests/runtime/test_mvp6_debug_console_history.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from voice_agent.runtime.mvp6_debug_console_history import (
    MVP6QAHistoryEntry,
    MVP6QAHistoryError,
    append_mvp6_qa_history,
    clear_mvp6_qa_history,
    read_mvp6_qa_history,
)


def test_append_and_read_history_saves_question_and_debug_answer(tmp_path: Path) -> None:
    history_path = tmp_path / "outputs" / "mvp6-debug-console" / "qa-history.jsonl"
    entry = MVP6QAHistoryEntry(
        run_id="mvp6_run_fast",
        created_at="2026-06-17T00:00:00Z",
        provider_mode="fake",
        question_source="asr_transcript",
        question_text="What is the weather?",
        answer_kind="debug_route_answer",
        answer_display="Router chose FAST_ONLY from FOREGROUND_CHAT evidence.",
        actual_route="FAST_ONLY",
        router_decision="FAST_ONLY",
        route_result_kind="direct_answer",
        asr_output_mode="real",
        thinker_output_mode="real",
        provider_call_used=False,
        fake_transport_used=True,
        event_ids=("evt_mvp6_fast",),
        safe_refs=("text://synthetic/mvp6/fast",),
    )

    append_mvp6_qa_history(history_path, entry)

    lines = history_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    saved = json.loads(lines[0])
    assert saved["question_text"] == "What is the weather?"
    assert saved["answer_display"] == "Router chose FAST_ONLY from FOREGROUND_CHAT evidence."
    assert saved["raw_audio_saved"] is False
    assert saved["provider_body_saved"] is False
    assert saved["secret_saved"] is False
    assert read_mvp6_qa_history(history_path) == [saved]


def test_history_read_caps_latest_entries(tmp_path: Path) -> None:
    history_path = tmp_path / "outputs" / "mvp6-debug-console" / "qa-history.jsonl"
    for index in range(25):
        append_mvp6_qa_history(
            history_path,
            MVP6QAHistoryEntry(
                run_id=f"mvp6_run_{index}",
                created_at="2026-06-17T00:00:00Z",
                provider_mode="fake",
                question_source="asr_transcript",
                question_text=f"Question {index}",
                answer_kind="debug_route_answer",
                answer_display="Router chose FAST_ONLY from FOREGROUND_CHAT evidence.",
                actual_route="FAST_ONLY",
                router_decision="FAST_ONLY",
                route_result_kind="direct_answer",
                asr_output_mode="real",
                thinker_output_mode="real",
                provider_call_used=False,
                fake_transport_used=True,
            ),
        )

    latest = read_mvp6_qa_history(history_path)

    assert len(latest) == 20
    assert latest[0]["run_id"] == "mvp6_run_5"
    assert latest[-1]["run_id"] == "mvp6_run_24"


def test_history_rejects_raw_audio_paths_provider_body_and_secrets(tmp_path: Path) -> None:
    history_path = tmp_path / "outputs" / "mvp6-debug-console" / "qa-history.jsonl"
    entry = MVP6QAHistoryEntry(
        run_id="mvp6_run_unsafe",
        created_at="2026-06-17T00:00:00Z",
        provider_mode="dashscope_live",
        question_source="asr_transcript",
        question_text="Question",
        answer_kind="debug_route_answer",
        answer_display="Router chose FAST_ONLY from FOREGROUND_CHAT evidence.",
        actual_route="FAST_ONLY",
        router_decision="FAST_ONLY",
        route_result_kind="direct_answer",
        asr_output_mode="real",
        thinker_output_mode="real",
        provider_call_used=True,
        fake_transport_used=False,
        safe_refs=("file:///Users/a123/private.wav",),
    )

    with pytest.raises(MVP6QAHistoryError, match="unsafe"):
        append_mvp6_qa_history(history_path, entry)


def test_clear_history_only_clears_configured_file(tmp_path: Path) -> None:
    history_path = tmp_path / "outputs" / "mvp6-debug-console" / "qa-history.jsonl"
    append_mvp6_qa_history(
        history_path,
        MVP6QAHistoryEntry(
            run_id="mvp6_run_clear",
            created_at="2026-06-17T00:00:00Z",
            provider_mode="fake",
            question_source="asr_transcript",
            question_text="Clear this?",
            answer_kind="debug_route_answer",
            answer_display="Router chose FAST_ONLY from FOREGROUND_CHAT evidence.",
            actual_route="FAST_ONLY",
            router_decision="FAST_ONLY",
            route_result_kind="direct_answer",
            asr_output_mode="real",
            thinker_output_mode="real",
            provider_call_used=False,
            fake_transport_used=True,
        ),
    )

    clear_mvp6_qa_history(history_path)

    assert read_mvp6_qa_history(history_path) == []
    assert history_path.exists()
    assert history_path.read_text(encoding="utf-8") == ""
```

- [ ] **Step 2: Run the history tests and verify they fail**

Run:

```bash
./scripts/test tests/runtime/test_mvp6_debug_console_history.py -q
```

Expected: fail with `ModuleNotFoundError` or missing `mvp6_debug_console_history`.

- [ ] **Step 3: Implement the history module**

Create `src/voice_agent/runtime/mvp6_debug_console_history.py`:

```python
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


class MVP6QAHistoryError(ValueError):
    """Raised when MVP6 local QA history would contain unsafe data."""


_FORBIDDEN_KEYS = {
    "audio_bytes",
    "raw_audio",
    "raw_audio_bytes",
    "wav_bytes",
    "pcm_samples",
    "local_path",
    "local_wav_path",
    "temp_audio_path",
    "file_name",
    "filename",
    "approval_packet_path",
    "provider_body",
    "provider_payload",
    "provider_request",
    "provider_response",
    "prompt_dump",
    "authorization_header",
    "cookie",
    "credential",
    "token",
    "api_key",
}
_UNSAFE_STRING_MARKERS = (
    "file://",
    "data:",
    "/Users/",
    "\\Users\\",
    "/private/",
    "audio/raw/",
    "diagnostics/",
    "traces/",
    "replays/local/",
    ".env",
    "authorization:",
    "cookie:",
    "api_key=",
    "token=",
    "bearer ",
    "provider body",
    "provider payload",
    "prompt dump",
)


@dataclass(frozen=True)
class MVP6QAHistoryEntry:
    run_id: str
    created_at: str
    provider_mode: str
    question_source: str
    question_text: str
    answer_kind: str
    answer_display: str
    actual_route: str | None
    router_decision: str | None
    route_result_kind: str | None
    asr_output_mode: str | None
    thinker_output_mode: str | None
    provider_call_used: bool
    fake_transport_used: bool
    event_ids: tuple[str, ...] = ()
    safe_refs: tuple[str, ...] = ()

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "provider_mode": self.provider_mode,
            "question_source": self.question_source,
            "question_text": self.question_text,
            "answer_kind": self.answer_kind,
            "answer_display": self.answer_display,
            "actual_route": self.actual_route,
            "router_decision": self.router_decision,
            "route_result_kind": self.route_result_kind,
            "asr_output_mode": self.asr_output_mode,
            "thinker_output_mode": self.thinker_output_mode,
            "provider_call_used": self.provider_call_used,
            "fake_transport_used": self.fake_transport_used,
            "event_ids": list(self.event_ids),
            "safe_refs": list(self.safe_refs),
            "raw_audio_saved": False,
            "provider_body_saved": False,
            "secret_saved": False,
            "local_path_saved": False,
        }
        validate_mvp6_history_record(record)
        return record


def append_mvp6_qa_history(path: str | Path, entry: MVP6QAHistoryEntry) -> dict[str, Any]:
    history_path = Path(path)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    record = entry.to_record()
    with history_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
        stream.write("\n")
    return record


def read_mvp6_qa_history(path: str | Path, *, limit: int = 20) -> list[dict[str, Any]]:
    history_path = Path(path)
    if not history_path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in history_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise MVP6QAHistoryError("history record must be an object")
        validate_mvp6_history_record(value)
        records.append(value)
    return records[-limit:]


def clear_mvp6_qa_history(path: str | Path) -> None:
    history_path = Path(path)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text("", encoding="utf-8")


def validate_mvp6_history_record(record: Mapping[str, Any]) -> None:
    for key in _FORBIDDEN_KEYS:
        if key in record:
            raise MVP6QAHistoryError(f"unsafe history key rejected: {key}")
    _reject_unsafe_value(record)


def _reject_unsafe_value(value: Any, *, field_path: str = "history") -> None:
    if isinstance(value, bytes):
        raise MVP6QAHistoryError(f"{field_path} raw bytes are unsafe")
    if isinstance(value, str):
        _reject_unsafe_string(value, field_path=field_path)
        return
    if isinstance(value, Mapping):
        for child_key, child_value in value.items():
            if str(child_key) in _FORBIDDEN_KEYS:
                raise MVP6QAHistoryError(f"unsafe history key rejected: {child_key}")
            _reject_unsafe_value(child_value, field_path=f"{field_path}.{child_key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _reject_unsafe_value(item, field_path=f"{field_path}[{index}]")


def _reject_unsafe_string(value: str, *, field_path: str) -> None:
    lowered = value.lower()
    for marker in _UNSAFE_STRING_MARKERS:
        if marker.lower() in lowered:
            raise MVP6QAHistoryError(f"{field_path} unsafe string marker rejected")
```

- [ ] **Step 4: Run history tests and verify they pass**

Run:

```bash
./scripts/test tests/runtime/test_mvp6_debug_console_history.py -q
```

Expected: `4 passed`.

- [ ] **Step 5: Commit Task 1**

Run:

```bash
git add src/voice_agent/runtime/mvp6_debug_console_history.py tests/runtime/test_mvp6_debug_console_history.py
git commit -m "feat: add MVP6 QA history"
```

## Task 2: Status API and Live Provider Readiness

**Files:**
- Create: `src/voice_agent/runtime/mvp6_debug_console_api.py`
- Test: `tests/runtime/test_mvp6_debug_console_status.py`

- [ ] **Step 1: Write failing status tests**

Create `tests/runtime/test_mvp6_debug_console_status.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from voice_agent.runtime.mvp6_debug_console_api import (
    MVP6DebugConsoleConfig,
    MVP6DebugConsoleError,
    build_mvp6_status_response,
)


def test_status_defaults_to_fake_and_redacts_paths_and_secrets(tmp_path: Path) -> None:
    config = MVP6DebugConsoleConfig(output_root=tmp_path / "outputs" / "mvp6-debug-console")

    status = build_mvp6_status_response(config, env={"MVP6_TEST_PROVIDER_KEY": "SECRET"})

    rendered = json.dumps(status, sort_keys=True)
    assert status["status"] == "ready"
    assert status["provider_modes"] == ["fake", "dashscope_live"]
    assert status["default_provider_mode"] == "fake"
    assert status["approval_loaded"] is False
    assert status["credential_present"] is False
    assert status["metadata_only_output"] is True
    assert status["qa_history_enabled_default"] is True
    assert str(tmp_path) not in rendered
    assert "SECRET" not in rendered
    assert "approval_packet_path" not in rendered


def test_status_reports_live_provider_readiness_without_secret_value(tmp_path: Path) -> None:
    config = MVP6DebugConsoleConfig(
        output_root=tmp_path / "outputs" / "mvp6-debug-console",
        approval_packet=_approval_packet(),
    )

    status = build_mvp6_status_response(
        config,
        env={"MVP6_TEST_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK"},
    )

    rendered = json.dumps(status, sort_keys=True)
    assert status["approval_loaded"] is True
    assert status["credential_env_var_name"] == "MVP6_TEST_PROVIDER_KEY"
    assert status["credential_present"] is True
    assert status["max_provider_calls"] == 2
    assert status["timeout_ms"] == 30000
    assert "DUMMY_TEST_CREDENTIAL_THAT_MUST_NOT_LEAK" not in rendered


def test_config_rejects_non_local_bind_host(tmp_path: Path) -> None:
    with pytest.raises(MVP6DebugConsoleError, match="localhost"):
        MVP6DebugConsoleConfig(
            output_root=tmp_path / "outputs" / "mvp6-debug-console",
            bind_host="0.0.0.0",
        )


def _approval_packet() -> dict[str, object]:
    return {
        "approval_id": "mvp6-local-debug-console-test",
        "live_provider_opt_in": True,
        "local_wav_opt_in": True,
        "metadata_only_output": True,
        "replay_reruns_provider": False,
        "provider_adapter_ids": ["mvp5_asr_adapter", "mvp5_thinker_adapter"],
        "credential_env_var_name": "MVP6_TEST_PROVIDER_KEY",
        "max_provider_calls": 2,
        "timeout_ms": 30000,
        "safe_output_ref": "summary://mvp6/debug-console/test",
    }
```

- [ ] **Step 2: Run status tests and verify they fail**

Run:

```bash
./scripts/test tests/runtime/test_mvp6_debug_console_status.py -q
```

Expected: fail because `mvp6_debug_console_api` does not exist.

- [ ] **Step 3: Implement config and status response**

Create `src/voice_agent/runtime/mvp6_debug_console_api.py` with this first slice:

```python
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any


class MVP6DebugConsoleError(ValueError):
    """Raised when MVP6 debug console input or output is unsafe."""


_LOCAL_BIND_HOSTS = {"127.0.0.1", "localhost", "::1"}
_DEFAULT_PROVIDER_MODES = ["fake", "dashscope_live"]
_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")


@dataclass(frozen=True)
class MVP6DebugConsoleConfig:
    output_root: Path
    approval_packet: Mapping[str, Any] | None = None
    bind_host: str = "127.0.0.1"
    default_provider_mode: str = "fake"
    qa_history_enabled_default: bool = True

    def __post_init__(self) -> None:
        if self.bind_host not in _LOCAL_BIND_HOSTS:
            raise MVP6DebugConsoleError("MVP6 debug console must bind to localhost")
        if self.default_provider_mode != "fake":
            raise MVP6DebugConsoleError("MVP6 debug console default provider mode must be fake")

    @property
    def history_path(self) -> Path:
        return self.output_root / "qa-history.jsonl"


def build_mvp6_status_response(
    config: MVP6DebugConsoleConfig,
    *,
    env: Mapping[str, str],
) -> dict[str, Any]:
    credential_env_var_name = _credential_env_var_name(config.approval_packet)
    status: dict[str, Any] = {
        "status": "ready",
        "provider_modes": list(_DEFAULT_PROVIDER_MODES),
        "default_provider_mode": config.default_provider_mode,
        "approval_loaded": config.approval_packet is not None,
        "credential_env_var_name": credential_env_var_name,
        "credential_present": bool(credential_env_var_name and env.get(credential_env_var_name)),
        "metadata_only_output": True,
        "qa_history_enabled_default": config.qa_history_enabled_default,
    }
    if config.approval_packet is not None:
        status["max_provider_calls"] = _positive_int(
            config.approval_packet.get("max_provider_calls"),
            "max_provider_calls",
        )
        status["timeout_ms"] = _positive_int(
            config.approval_packet.get("timeout_ms"),
            "timeout_ms",
        )
    _validate_safe_response(status)
    return status


def _credential_env_var_name(packet: Mapping[str, Any] | None) -> str | None:
    if packet is None:
        return None
    value = packet.get("credential_env_var_name")
    if value is None:
        return None
    if not isinstance(value, str) or not re.match(r"^[A-Z_][A-Z0-9_]*$", value):
        raise MVP6DebugConsoleError("credential env var name is unsafe")
    return value


def _positive_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise MVP6DebugConsoleError(f"{field_name} must be positive")
    return value


def _validate_safe_response(value: Any) -> None:
    rendered = repr(value).lower()
    for marker in ("file://", "data:", "/users/", "/private/", "authorization:", "cookie:", "api_key=", "token=", "bearer "):
        if marker in rendered:
            raise MVP6DebugConsoleError("unsafe response value rejected")
```

- [ ] **Step 4: Run status tests and verify they pass**

Run:

```bash
./scripts/test tests/runtime/test_mvp6_debug_console_status.py -q
```

Expected: `3 passed`.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add src/voice_agent/runtime/mvp6_debug_console_api.py tests/runtime/test_mvp6_debug_console_status.py
git commit -m "feat: add MVP6 debug console status API"
```

## Task 3: Provider-Free Run Orchestration

**Files:**
- Modify: `src/voice_agent/runtime/mvp5_real_voice_e2e_smoke.py`
- Modify: `src/voice_agent/runtime/mvp6_debug_console_api.py`
- Test: `tests/runtime/test_mvp6_debug_console_runs.py`

- [ ] **Step 1: Write failing provider-free run tests**

Create `tests/runtime/test_mvp6_debug_console_runs.py`:

```python
from __future__ import annotations

import base64
import json
from pathlib import Path
import wave

import pytest

from voice_agent.runtime.mvp6_debug_console_api import (
    MVP6DebugConsoleConfig,
    MVP6DebugConsoleError,
    MVP6RunRequest,
    run_mvp6_debug_console_audio,
)


def test_provider_free_run_delegates_to_mvp5_and_returns_safe_pipeline(tmp_path: Path) -> None:
    wav_path = tmp_path / "draft.wav"
    wav_bytes = _write_wav_file(wav_path)
    config = MVP6DebugConsoleConfig(output_root=tmp_path / "outputs" / "mvp6-debug-console")

    response = run_mvp6_debug_console_audio(
        config=config,
        request=MVP6RunRequest(
            audio_bytes=wav_bytes,
            audio_mime_type="audio/wav",
            provider_mode="fake",
            expected_route="FAST_ONLY",
            save_qa_history=True,
        ),
        env={},
    )

    rendered = json.dumps(response, sort_keys=True)
    assert response["status"] == "completed"
    assert response["provider_mode"] == "fake"
    assert response["actual_route"] == "FAST_ONLY"
    assert response["router_decision"] == "FAST_ONLY"
    assert response["expected_route_matched"] is True
    assert response["provider_call_used"] is False
    assert response["fake_transport_used"] is True
    assert response["question_text"]
    assert response["answer_display"] == "Router chose FAST_ONLY from FOREGROUND_CHAT evidence."
    assert [stage["stage"] for stage in response["pipeline"]] == [
        "local_audio_gate",
        "asr",
        "thinker",
        "router",
        "qa_history",
    ]
    assert response["safety"]["raw_audio_returned"] is False
    assert response["safety"]["raw_audio_saved_to_history"] is False
    assert str(tmp_path) not in rendered
    assert "draft.wav" not in rendered
    assert base64.b64encode(wav_bytes).decode("ascii") not in rendered


def test_patch_run_requires_active_task_context(tmp_path: Path) -> None:
    wav_path = tmp_path / "patch.wav"
    wav_bytes = _write_wav_file(wav_path)
    config = MVP6DebugConsoleConfig(output_root=tmp_path / "outputs" / "mvp6-debug-console")

    response = run_mvp6_debug_console_audio(
        config=config,
        request=MVP6RunRequest(
            audio_bytes=wav_bytes,
            audio_mime_type="audio/wav",
            provider_mode="fake",
            expected_route="PATCH_ACTIVE_SLOW_TASK",
            save_qa_history=False,
        ),
        env={},
    )

    assert response["status"] == "blocked_missing_active_task_context"
    assert response["actual_route"] is None
    assert response["safety"]["raw_audio_returned"] is False


def test_rejects_non_wav_upload_without_calling_runtime(tmp_path: Path) -> None:
    config = MVP6DebugConsoleConfig(output_root=tmp_path / "outputs" / "mvp6-debug-console")

    with pytest.raises(MVP6DebugConsoleError, match="wav"):
        run_mvp6_debug_console_audio(
            config=config,
            request=MVP6RunRequest(
                audio_bytes=b"not a wav",
                audio_mime_type="audio/webm",
                provider_mode="fake",
                expected_route="auto",
                save_qa_history=False,
            ),
            env={},
        )


def _write_wav_file(path: Path) -> bytes:
    frames = b"\x00\x00" * 1600
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(frames)
    return path.read_bytes()
```

- [ ] **Step 2: Run run tests and verify they fail**

Run:

```bash
./scripts/test tests/runtime/test_mvp6_debug_console_runs.py -q
```

Expected: fail because `MVP6RunRequest` and `run_mvp6_debug_console_audio` do not exist.

- [ ] **Step 3: Expose deterministic MVP5 provider-free transports**

Modify `src/voice_agent/runtime/mvp5_real_voice_e2e_smoke.py`:

```python
def build_mvp5_provider_free_fake_transports(
    *,
    fake_route: str,
    route_slug: str,
) -> TransportPair:
    """Build deterministic adapter fake transports for local debug/runtime tests."""

    return _provider_free_fake_transports(fake_route=fake_route, route_slug=route_slug)
```

Update `_provider_free_fake_pack_transport_factory` and CLI fake-route setup only if useful; existing private calls may remain.

- [ ] **Step 4: Implement provider-free run orchestration**

Extend `src/voice_agent/runtime/mvp6_debug_console_api.py`:

```python
from dataclasses import dataclass
import hashlib
import time

from voice_agent.runtime.mvp5_live_router_runner import MVP5ActiveSlowTaskContext
from voice_agent.runtime.mvp5_real_voice_e2e_smoke import (
    build_mvp5_provider_free_fake_transports,
    run_mvp5_real_voice_e2e_single,
)
from voice_agent.runtime.mvp6_debug_console_history import (
    MVP6QAHistoryEntry,
    append_mvp6_qa_history,
)


@dataclass(frozen=True)
class MVP6RunRequest:
    audio_bytes: bytes
    audio_mime_type: str
    provider_mode: str
    expected_route: str
    save_qa_history: bool
    active_task_id: str | None = None
    active_plan_version: int | None = None
    active_task_event_seq: int | None = None
    active_lifecycle_phase: str = "PLANNING"


def run_mvp6_debug_console_audio(
    *,
    config: MVP6DebugConsoleConfig,
    request: MVP6RunRequest,
    env: Mapping[str, str],
) -> dict[str, Any]:
    provider_mode = _provider_mode(request.provider_mode)
    expected_route = _expected_route(request.expected_route)
    if expected_route == "PATCH_ACTIVE_SLOW_TASK" and not request.active_task_id:
        return _blocked_missing_active_task_context(provider_mode=provider_mode)
    _require_wav_upload(request.audio_bytes, request.audio_mime_type)
    run_id = _run_id(request.audio_bytes)
    audio_path = _write_temp_wav(config.output_root, run_id, request.audio_bytes)
    active_context = _active_task_context(request)
    asr_transport = None
    thinker_transport = None
    approval_packet = config.approval_packet
    runtime_env = env
    live_provider = provider_mode == "dashscope_live"
    if provider_mode == "fake":
        fake_route = "FAST_ONLY" if expected_route == "auto" else expected_route
        asr_transport, thinker_transport = build_mvp5_provider_free_fake_transports(
            fake_route=fake_route,
            route_slug=run_id,
        )
        approval_packet = _fake_approval_packet()
        runtime_env = {"MVP6_FAKE_PROVIDER_KEY": "DUMMY_TEST_CREDENTIAL"}
        live_provider = True
    metadata = run_mvp5_real_voice_e2e_single(
        local_wav=audio_path,
        live_provider=live_provider,
        allow_local_wav=True,
        approval_packet=approval_packet or {},
        expected_route=expected_route,
        run_id=run_id,
        env=runtime_env,
        asr_transport=asr_transport,
        thinker_transport=thinker_transport,
        active_task_context=active_context,
    )
    response = _response_from_mvp5_metadata(
        metadata,
        provider_mode=provider_mode,
        question_text=resolve_mvp6_question_text(metadata, provider_mode=provider_mode),
        history_written=False,
    )
    if request.save_qa_history:
        append_mvp6_qa_history(config.history_path, _history_entry_from_response(response))
        response["pipeline"][-1]["status"] = "completed"
        response["history_written"] = True
    _validate_safe_response(response)
    return response
```

Use focused helpers for `_require_wav_upload`, `_write_temp_wav`, `_active_task_context`, `_response_from_mvp5_metadata`, `resolve_mvp6_question_text`, `_history_entry_from_response`, and `_blocked_missing_active_task_context`. In Task 3, `resolve_mvp6_question_text` only needs fake-mode synthetic text; Task 4 extends it to live DashScope ASR text refs. Keep these helpers in the same module until there is real pressure to split them.

Add concrete helper implementations in the same module:

```python
def _provider_mode(value: str) -> str:
    if value not in {"fake", "dashscope_live"}:
        raise MVP6DebugConsoleError("provider_mode must be fake or dashscope_live")
    return value


def _expected_route(value: str) -> str:
    allowed = {"auto", "FAST_ONLY", "SPAWN_SLOW_TASK", "PATCH_ACTIVE_SLOW_TASK"}
    if value not in allowed:
        raise MVP6DebugConsoleError("expected_route is not supported by MVP6")
    return value


def _require_wav_upload(audio_bytes: bytes, audio_mime_type: str) -> None:
    if audio_mime_type != "audio/wav":
        raise MVP6DebugConsoleError("uploaded audio must be audio/wav")
    if not audio_bytes:
        raise MVP6DebugConsoleError("uploaded wav must be non-empty")
    try:
        import io
        import wave

        with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
            if wav_file.getframerate() <= 0 or wav_file.getnframes() <= 0:
                raise MVP6DebugConsoleError("uploaded wav metadata is invalid")
    except wave.Error as exc:
        raise MVP6DebugConsoleError("uploaded wav metadata could not be parsed") from exc


def _run_id(audio_bytes: bytes) -> str:
    digest = hashlib.sha256(audio_bytes).hexdigest()[:12]
    return f"mvp6_run_{digest}"


def _write_temp_wav(output_root: Path, run_id: str, audio_bytes: bytes) -> Path:
    audio_dir = output_root / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    path = audio_dir / f"{run_id}.wav"
    path.write_bytes(audio_bytes)
    return path


def _fake_approval_packet() -> dict[str, object]:
    return {
        "approval_id": "mvp6-provider-free-fake",
        "live_provider_opt_in": True,
        "local_wav_opt_in": True,
        "metadata_only_output": True,
        "replay_reruns_provider": False,
        "provider_adapter_ids": ["mvp5_asr_adapter", "mvp5_thinker_adapter"],
        "credential_env_var_name": "MVP6_FAKE_PROVIDER_KEY",
        "max_provider_calls": 2,
        "timeout_ms": 30000,
        "safe_output_ref": "summary://mvp6/provider-free-fake",
    }


def _active_task_context(request: MVP6RunRequest) -> MVP5ActiveSlowTaskContext | None:
    if request.active_task_id in (None, ""):
        return None
    if request.active_plan_version is None or request.active_task_event_seq is None:
        raise MVP6DebugConsoleError("active task context requires plan version and event seq")
    return MVP5ActiveSlowTaskContext(
        task_id=request.active_task_id,
        current_plan_version=request.active_plan_version,
        current_task_event_seq=request.active_task_event_seq,
        lifecycle_phase=request.active_lifecycle_phase,
    )


def _response_from_mvp5_metadata(
    metadata: Mapping[str, Any],
    *,
    provider_mode: str,
    question_text: str | None,
    history_written: bool,
) -> dict[str, Any]:
    actual_route = metadata.get("actual_route")
    task_focus_hint = metadata.get("task_focus_hint")
    response = {
        "status": "completed" if metadata.get("status") == "routed" else metadata.get("status"),
        "run_id": metadata.get("run_id"),
        "provider_mode": provider_mode,
        "actual_route": actual_route,
        "router_decision": metadata.get("router_decision"),
        "route_result_kind": metadata.get("route_result_kind"),
        "expected_route": metadata.get("expected_route"),
        "expected_route_matched": metadata.get("expected_route_matched"),
        "question_text": question_text,
        "answer_display": _answer_display(actual_route, task_focus_hint),
        "provider_call_used": bool(metadata.get("provider_call_used")),
        "fake_transport_used": bool(metadata.get("fake_transport_used")),
        "asr_output_mode": metadata.get("asr_output_mode"),
        "thinker_output_mode": metadata.get("thinker_output_mode"),
        "event_ids": list(metadata.get("event_ids", ())),
        "safe_refs": list(metadata.get("safe_refs", ())),
        "pipeline": [
            {"stage": "local_audio_gate", "status": "passed"},
            {"stage": "asr", "status": "completed", "output_mode": metadata.get("asr_output_mode")},
            {"stage": "thinker", "status": "completed", "output_mode": metadata.get("thinker_output_mode")},
            {"stage": "router", "status": "completed", "actual_route": actual_route},
            {"stage": "qa_history", "status": "completed" if history_written else "skipped"},
        ],
        "history_written": history_written,
        "safety": _safety_flags(),
    }
    _validate_safe_response(response)
    return response


def resolve_mvp6_question_text(metadata: Mapping[str, Any], *, provider_mode: str) -> str | None:
    if provider_mode == "fake":
        return _synthetic_question_text(str(metadata.get("actual_route") or "FAST_ONLY"))
    return None


def _synthetic_question_text(actual_route: str) -> str:
    if actual_route == "SPAWN_SLOW_TASK":
        return "Plan a multi-step task"
    if actual_route == "PATCH_ACTIVE_SLOW_TASK":
        return "Update the active task"
    return "Ask a short foreground question"


def _answer_display(actual_route: object, task_focus_hint: object) -> str:
    if isinstance(task_focus_hint, str) and task_focus_hint:
        focus = task_focus_hint
    elif actual_route == "SPAWN_SLOW_TASK":
        focus = "NEW_TASK_CANDIDATE"
    elif actual_route == "PATCH_ACTIVE_SLOW_TASK":
        focus = "ACTIVE_TASK_PATCH"
    else:
        focus = "FOREGROUND_CHAT"
    return f"Router chose {actual_route} from {focus}."


def _history_entry_from_response(response: Mapping[str, Any]) -> MVP6QAHistoryEntry:
    return MVP6QAHistoryEntry(
        run_id=str(response["run_id"]),
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        provider_mode=str(response["provider_mode"]),
        question_source="asr_transcript",
        question_text=str(response.get("question_text") or ""),
        answer_kind="debug_route_answer",
        answer_display=str(response.get("answer_display") or ""),
        actual_route=response.get("actual_route"),
        router_decision=response.get("router_decision"),
        route_result_kind=response.get("route_result_kind"),
        asr_output_mode=response.get("asr_output_mode"),
        thinker_output_mode=response.get("thinker_output_mode"),
        provider_call_used=bool(response.get("provider_call_used")),
        fake_transport_used=bool(response.get("fake_transport_used")),
        event_ids=tuple(str(event_id) for event_id in response.get("event_ids", ())),
        safe_refs=tuple(str(ref) for ref in response.get("safe_refs", ())),
    )


def _blocked_missing_active_task_context(*, provider_mode: str) -> dict[str, Any]:
    return _safe_failure_response(
        status="blocked_missing_active_task_context",
        provider_mode=provider_mode,
    )


def _safe_failure_response(*, status: str, provider_mode: str) -> dict[str, Any]:
    response = {
        "status": status,
        "provider_mode": provider_mode,
        "actual_route": None,
        "router_decision": None,
        "route_result_kind": "blocked",
        "provider_call_used": False,
        "fake_transport_used": False,
        "pipeline": [{"stage": "router", "status": status}],
        "safety": _safety_flags(),
    }
    _validate_safe_response(response)
    return response


def _safety_flags() -> dict[str, bool]:
    return {
        "raw_audio_returned": False,
        "raw_audio_saved_to_history": False,
        "provider_body_returned": False,
        "secret_returned": False,
        "local_path_returned": False,
        "replay_reruns_provider": False,
    }
```

- [ ] **Step 5: Run run tests and fix compile errors**

Run:

```bash
./scripts/test tests/runtime/test_mvp6_debug_console_runs.py -q
```

Expected: `3 passed`.

- [ ] **Step 6: Run Task 1-3 runtime tests together**

Run:

```bash
./scripts/test tests/runtime/test_mvp6_debug_console_history.py tests/runtime/test_mvp6_debug_console_status.py tests/runtime/test_mvp6_debug_console_runs.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit Task 3**

Run:

```bash
git add src/voice_agent/runtime/mvp5_real_voice_e2e_smoke.py src/voice_agent/runtime/mvp6_debug_console_api.py tests/runtime/test_mvp6_debug_console_runs.py
git commit -m "feat: add MVP6 provider-free run API"
```

## Task 4: DashScope Live Gate and Debug Question Text

**Files:**
- Modify: `src/voice_agent/runtime/mvp6_debug_console_api.py`
- Test: `tests/runtime/test_mvp6_debug_console_runs.py`

- [ ] **Step 1: Add failing live gate tests**

Append to `tests/runtime/test_mvp6_debug_console_runs.py`:

```python
def test_live_provider_mode_requires_approval_and_credential(tmp_path: Path) -> None:
    wav_path = tmp_path / "live.wav"
    wav_bytes = _write_wav_file(wav_path)
    config = MVP6DebugConsoleConfig(output_root=tmp_path / "outputs" / "mvp6-debug-console")

    response = run_mvp6_debug_console_audio(
        config=config,
        request=MVP6RunRequest(
            audio_bytes=wav_bytes,
            audio_mime_type="audio/wav",
            provider_mode="dashscope_live",
            expected_route="auto",
            save_qa_history=False,
        ),
        env={},
    )

    assert response["status"] == "approval_missing"
    assert response["provider_call_used"] is False
    assert response["fake_transport_used"] is False


def test_live_provider_mode_reports_credential_missing_without_provider_call(tmp_path: Path) -> None:
    wav_path = tmp_path / "live-missing-credential.wav"
    wav_bytes = _write_wav_file(wav_path)
    config = MVP6DebugConsoleConfig(
        output_root=tmp_path / "outputs" / "mvp6-debug-console",
        approval_packet=_approval_packet(),
    )

    response = run_mvp6_debug_console_audio(
        config=config,
        request=MVP6RunRequest(
            audio_bytes=wav_bytes,
            audio_mime_type="audio/wav",
            provider_mode="dashscope_live",
            expected_route="auto",
            save_qa_history=False,
        ),
        env={},
    )

    assert response["status"] == "credential_missing"
    assert response["provider_call_used"] is False
    assert response["fake_transport_used"] is False


def test_live_question_text_resolves_from_process_local_asr_ref(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from voice_agent.runtime import mvp6_debug_console_api as api

    class FakeAsrLiveModule:
        @staticmethod
        def resolve_asr_live_transcript_text_ref(text_ref: str) -> str | None:
            assert text_ref == "text://provider/dashscope/adapter-request-mvp6"
            return "Plan a three day Tokyo trip"

    monkeypatch.setattr(api.importlib, "import_module", lambda name: FakeAsrLiveModule)
    metadata = {
        "safe_refs": ["text://provider/dashscope/adapter-request-mvp6"],
        "asr_output_mode": "degraded",
    }

    assert api.resolve_mvp6_question_text(metadata, provider_mode="dashscope_live") == "Plan a three day Tokyo trip"
```

- [ ] **Step 2: Run the live gate tests and verify they fail**

Run:

```bash
./scripts/test tests/runtime/test_mvp6_debug_console_runs.py -q
```

Expected: fail because live gate statuses and live ASR text-ref resolution are missing.

- [ ] **Step 3: Implement live gate statuses and lazy ASR text resolver**

Modify `src/voice_agent/runtime/mvp6_debug_console_api.py`:

```python
import importlib


def resolve_mvp6_question_text(metadata: Mapping[str, Any], *, provider_mode: str) -> str | None:
    if provider_mode == "fake":
        return _synthetic_question_text(metadata.get("actual_route"))
    for ref in metadata.get("safe_refs", ()):
        if isinstance(ref, str) and ref.startswith("text://provider/dashscope/"):
            module = importlib.import_module("voice_agent.adapters.asr_live_transport")
            resolver = getattr(module, "resolve_asr_live_transcript_text_ref")
            text = resolver(ref)
            if isinstance(text, str) and text.strip():
                return text
    return None


def _live_gate_failure(
    *,
    config: MVP6DebugConsoleConfig,
    env: Mapping[str, str],
) -> str | None:
    if config.approval_packet is None:
        return "approval_missing"
    credential_name = _credential_env_var_name(config.approval_packet)
    if not credential_name or not env.get(credential_name):
        return "credential_missing"
    return None
```

In `run_mvp6_debug_console_audio`, before writing temp audio for live provider mode:

```python
if provider_mode == "dashscope_live":
    failure = _live_gate_failure(config=config, env=env)
    if failure is not None:
        return _safe_failure_response(status=failure, provider_mode=provider_mode)
```

- [ ] **Step 4: Run run tests and verify they pass**

Run:

```bash
./scripts/test tests/runtime/test_mvp6_debug_console_runs.py -q
```

Expected: all run tests pass.

- [ ] **Step 5: Commit Task 4**

Run:

```bash
git add src/voice_agent/runtime/mvp6_debug_console_api.py tests/runtime/test_mvp6_debug_console_runs.py
git commit -m "feat: gate MVP6 live provider mode"
```

## Task 5: Local HTTP Server

**Files:**
- Create: `src/voice_agent/runtime/mvp6_debug_console_static.py` with a minimal HTML shell
- Create: `src/voice_agent/runtime/mvp6_debug_console_server.py`
- Test: `tests/runtime/test_mvp6_debug_console_server.py`

- [ ] **Step 1: Write failing server tests**

Create `tests/runtime/test_mvp6_debug_console_server.py`:

```python
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
```

- [ ] **Step 2: Run server tests and verify they fail**

Run:

```bash
./scripts/test tests/runtime/test_mvp6_debug_console_server.py -q
```

Expected: fail because `mvp6_debug_console_server` does not exist.

- [ ] **Step 3: Implement local HTTP server**

Create a minimal `src/voice_agent/runtime/mvp6_debug_console_static.py` shell that Task 6 will expand:

```python
from __future__ import annotations


MVP6_DEBUG_CONSOLE_HTML = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>MVP6 Local Debug Console</title></head>
<body>
  <h1>MVP6 Local Debug Console</h1>
  <button>Record</button>
  <button>Run</button>
</body>
</html>
"""
```

Create `src/voice_agent/runtime/mvp6_debug_console_server.py`:

```python
from __future__ import annotations

from collections.abc import Mapping
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from typing import Any

from voice_agent.runtime.mvp6_debug_console_api import (
    MVP6DebugConsoleConfig,
    MVP6RunRequest,
    build_mvp6_status_response,
    run_mvp6_debug_console_audio,
)
from voice_agent.runtime.mvp6_debug_console_history import read_mvp6_qa_history, clear_mvp6_qa_history
from voice_agent.runtime.mvp6_debug_console_static import MVP6_DEBUG_CONSOLE_HTML


def create_mvp6_http_server(
    *,
    config: MVP6DebugConsoleConfig,
    env: Mapping[str, str],
    host: str,
    port: int,
) -> ThreadingHTTPServer:
    if host not in {"127.0.0.1", "localhost", "::1"}:
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
            self.send_error(404)

        def do_POST(self) -> None:
            if self.path == "/api/history/clear":
                clear_mvp6_qa_history(config.history_path)
                self._send_json({"status": "cleared"})
                return
            if self.path == "/api/runs":
                fields = _parse_multipart(self)
                audio = fields.get("audio")
                if not isinstance(audio, bytes):
                    self.send_error(400, "audio is required")
                    return
                payload = run_mvp6_debug_console_audio(
                    config=config,
                    request=MVP6RunRequest(
                        audio_bytes=audio,
                        audio_mime_type=str(fields.get("audio_content_type", "audio/wav")),
                        provider_mode=str(fields.get("provider_mode", "fake")),
                        expected_route=str(fields.get("expected_route", "auto")),
                        save_qa_history=str(fields.get("save_qa_history", "true")).lower() == "true",
                        active_task_id=_optional_string(fields.get("active_task_id")),
                        active_plan_version=_optional_int(fields.get("active_plan_version")),
                        active_task_event_seq=_optional_int(fields.get("active_task_event_seq")),
                        active_lifecycle_phase=str(fields.get("active_lifecycle_phase", "PLANNING")),
                    ),
                    env=env,
                )
                self._send_json(payload)
                return
            self.send_error(404)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_json(self, payload: Mapping[str, Any]) -> None:
            body = json.dumps(payload, sort_keys=True).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ThreadingHTTPServer((host, port), Handler)
```

Also implement `_parse_multipart`, `_optional_string`, and `_optional_int` in the same file. Use `BytesParser(policy=default)` with a synthetic MIME header:

```python
def _parse_multipart(handler: BaseHTTPRequestHandler) -> dict[str, object]:
    content_type = handler.headers.get("Content-Type", "")
    length = int(handler.headers.get("Content-Length", "0"))
    raw_body = handler.rfile.read(length)
    message = BytesParser(policy=default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("ascii") + raw_body
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
            fields[name] = payload.decode("utf-8")
    return fields
```

- [ ] **Step 4: Run server tests and verify they pass**

Run:

```bash
./scripts/test tests/runtime/test_mvp6_debug_console_server.py -q
```

Expected: `3 passed`.

- [ ] **Step 5: Commit Task 5**

Run:

```bash
git add src/voice_agent/runtime/mvp6_debug_console_server.py tests/runtime/test_mvp6_debug_console_server.py
git commit -m "feat: add MVP6 local HTTP server"
```

## Task 6: Static HTML and Browser Recording UI

**Files:**
- Modify: `src/voice_agent/runtime/mvp6_debug_console_static.py`
- Test: `tests/runtime/test_mvp6_debug_console_static.py`

- [ ] **Step 1: Write failing static UI tests**

Create `tests/runtime/test_mvp6_debug_console_static.py`:

```python
from __future__ import annotations

from voice_agent.runtime.mvp6_debug_console_static import MVP6_DEBUG_CONSOLE_HTML


def test_static_html_contains_core_controls_and_provider_state() -> None:
    html = MVP6_DEBUG_CONSOLE_HTML
    assert "MVP6 Local Debug Console" in html
    assert "id=\"recordButton\"" in html
    assert "id=\"stopButton\"" in html
    assert "id=\"clearRecordingButton\"" in html
    assert "id=\"runButton\"" in html
    assert "id=\"providerMode\"" in html
    assert "dashscope_live" in html
    assert "id=\"expectedRoute\"" in html
    assert "PATCH_ACTIVE_SLOW_TASK" in html


def test_static_html_contains_pipeline_and_history_surfaces() -> None:
    html = MVP6_DEBUG_CONSOLE_HTML
    assert "local_audio_gate" in html
    assert "asr" in html
    assert "thinker" in html
    assert "router" in html
    assert "qa_history" in html
    assert "QA history is local-only" in html


def test_static_js_encodes_wav_and_requires_explicit_run() -> None:
    html = MVP6_DEBUG_CONSOLE_HTML
    assert "function startRecording" in html
    assert "function stopRecording" in html
    assert "function clearRecording" in html
    assert "function runDraft" in html
    assert "function encodeWav" in html
    assert "new Blob([wavBytes], { type: 'audio/wav' })" in html
```

- [ ] **Step 2: Run static tests and verify they fail**

Run:

```bash
./scripts/test tests/runtime/test_mvp6_debug_console_static.py -q
```

Expected: fail because the minimal static shell does not yet contain the full controls, pipeline surfaces, or wav encoder.

- [ ] **Step 3: Implement embedded static page**

Create `src/voice_agent/runtime/mvp6_debug_console_static.py`:

```python
from __future__ import annotations


MVP6_DEBUG_CONSOLE_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MVP6 Local Debug Console</title>
  <style>
    body { margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f6f7f9; color: #17202a; }
    header { display: flex; align-items: center; justify-content: space-between; padding: 14px 18px; background: #ffffff; border-bottom: 1px solid #d8dee8; }
    main { display: grid; grid-template-columns: minmax(320px, 440px) minmax(420px, 1fr); gap: 16px; padding: 16px; }
    section { background: #ffffff; border: 1px solid #d8dee8; border-radius: 8px; padding: 14px; }
    button, select, input { font: inherit; }
    button { min-height: 36px; border: 1px solid #aeb8c6; background: #ffffff; border-radius: 6px; padding: 0 12px; }
    button.primary { background: #174ea6; color: #ffffff; border-color: #174ea6; }
    button.danger { border-color: #ba1a1a; color: #ba1a1a; }
    .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .grid { display: grid; gap: 10px; }
    .status { display: flex; gap: 12px; font-size: 13px; }
    .stage { display: grid; grid-template-columns: 160px 1fr; gap: 8px; padding: 8px 0; border-bottom: 1px solid #edf0f5; }
    pre { white-space: pre-wrap; overflow-wrap: anywhere; background: #f3f5f8; padding: 10px; border-radius: 6px; }
    label { display: grid; gap: 4px; font-size: 13px; }
  </style>
</head>
<body>
  <header>
    <h1>MVP6 Local Debug Console</h1>
    <div class="status">
      <span id="providerStatus">Provider: Fake</span>
      <span id="approvalStatus">Approval: unknown</span>
      <span id="credentialStatus">Credential: unknown</span>
    </div>
  </header>
  <main>
    <section class="grid">
      <h2>Run</h2>
      <div class="row">
        <button id="recordButton" class="primary" onclick="startRecording()">Record</button>
        <button id="stopButton" onclick="stopRecording()" disabled>Stop</button>
        <button id="clearRecordingButton" class="danger" onclick="clearRecording()" disabled>Clear Recording</button>
        <button id="runButton" class="primary" onclick="runDraft()" disabled>Run</button>
      </div>
      <div id="draftStatus">No recording draft</div>
      <label>Provider mode
        <select id="providerMode">
          <option value="fake">Fake</option>
          <option value="dashscope_live">DashScope Live</option>
        </select>
      </label>
      <label>Expected route
        <select id="expectedRoute">
          <option value="auto">auto</option>
          <option value="FAST_ONLY">FAST_ONLY</option>
          <option value="SPAWN_SLOW_TASK">SPAWN_SLOW_TASK</option>
          <option value="PATCH_ACTIVE_SLOW_TASK">PATCH_ACTIVE_SLOW_TASK</option>
        </select>
      </label>
      <label>Active task id <input id="activeTaskId" autocomplete="off"></label>
      <label>Active plan version <input id="activePlanVersion" type="number" min="1"></label>
      <label>Active task event seq <input id="activeTaskEventSeq" type="number" min="1"></label>
      <label><input id="saveQaHistory" type="checkbox" checked> Save QA history locally</label>
      <p>QA history is local-only and may contain ASR user text.</p>
    </section>
    <section class="grid">
      <h2>Latest Result</h2>
      <div id="answerDisplay">No run yet</div>
      <div class="stage"><strong>local_audio_gate</strong><span id="stage-local_audio_gate">waiting</span></div>
      <div class="stage"><strong>asr</strong><span id="stage-asr">waiting</span></div>
      <div class="stage"><strong>thinker</strong><span id="stage-thinker">waiting</span></div>
      <div class="stage"><strong>router</strong><span id="stage-router">waiting</span></div>
      <div class="stage"><strong>qa_history</strong><span id="stage-qa_history">waiting</span></div>
      <pre id="metadataPanel">{}</pre>
    </section>
  </main>
  <script>
    let audioContext = null;
    let mediaStream = null;
    let processor = null;
    let source = null;
    let recordedBuffers = [];
    let draftBlob = null;
    let recordingStartedAt = 0;

    async function loadStatus() {
      const response = await fetch('/api/status');
      const status = await response.json();
      document.getElementById('approvalStatus').textContent = 'Approval: ' + (status.approval_loaded ? 'loaded' : 'missing');
      document.getElementById('credentialStatus').textContent = 'Credential: ' + (status.credential_present ? 'present' : 'missing');
    }

    async function startRecording() {
      clearRecording();
      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioContext = new AudioContext();
      source = audioContext.createMediaStreamSource(mediaStream);
      processor = audioContext.createScriptProcessor(4096, 1, 1);
      recordedBuffers = [];
      processor.onaudioprocess = (event) => recordedBuffers.push(new Float32Array(event.inputBuffer.getChannelData(0)));
      source.connect(processor);
      processor.connect(audioContext.destination);
      recordingStartedAt = Date.now();
      document.getElementById('recordButton').disabled = true;
      document.getElementById('stopButton').disabled = false;
      document.getElementById('draftStatus').textContent = 'Recording';
    }

    async function stopRecording() {
      if (processor) processor.disconnect();
      if (source) source.disconnect();
      if (mediaStream) mediaStream.getTracks().forEach((track) => track.stop());
      const samples = mergeBuffers(recordedBuffers);
      const wavBytes = encodeWav(samples, audioContext.sampleRate);
      draftBlob = new Blob([wavBytes], { type: 'audio/wav' });
      await audioContext.close();
      const durationMs = Date.now() - recordingStartedAt;
      document.getElementById('draftStatus').textContent = 'Recorded draft: ' + Math.round(durationMs / 1000) + 's';
      document.getElementById('recordButton').disabled = false;
      document.getElementById('stopButton').disabled = true;
      document.getElementById('clearRecordingButton').disabled = false;
      document.getElementById('runButton').disabled = false;
    }

    function clearRecording() {
      draftBlob = null;
      recordedBuffers = [];
      if (mediaStream) mediaStream.getTracks().forEach((track) => track.stop());
      document.getElementById('draftStatus').textContent = 'No recording draft';
      document.getElementById('recordButton').disabled = false;
      document.getElementById('stopButton').disabled = true;
      document.getElementById('clearRecordingButton').disabled = true;
      document.getElementById('runButton').disabled = true;
    }

    async function runDraft() {
      if (!draftBlob) return;
      const form = new FormData();
      form.append('audio', draftBlob, 'browser-draft.wav');
      form.append('provider_mode', document.getElementById('providerMode').value);
      form.append('expected_route', document.getElementById('expectedRoute').value);
      form.append('active_task_id', document.getElementById('activeTaskId').value);
      form.append('active_plan_version', document.getElementById('activePlanVersion').value);
      form.append('active_task_event_seq', document.getElementById('activeTaskEventSeq').value);
      form.append('save_qa_history', document.getElementById('saveQaHistory').checked ? 'true' : 'false');
      const response = await fetch('/api/runs', { method: 'POST', body: form });
      const payload = await response.json();
      renderResult(payload);
    }

    function renderResult(payload) {
      document.getElementById('answerDisplay').textContent = payload.answer_display || payload.status;
      for (const stage of payload.pipeline || []) {
        const element = document.getElementById('stage-' + stage.stage);
        if (element) element.textContent = stage.status + (stage.output_mode ? ' / ' + stage.output_mode : '');
      }
      document.getElementById('metadataPanel').textContent = JSON.stringify(payload, null, 2);
    }

    function mergeBuffers(buffers) {
      const length = buffers.reduce((sum, buffer) => sum + buffer.length, 0);
      const result = new Float32Array(length);
      let offset = 0;
      for (const buffer of buffers) {
        result.set(buffer, offset);
        offset += buffer.length;
      }
      return result;
    }

    function encodeWav(samples, sampleRate) {
      const buffer = new ArrayBuffer(44 + samples.length * 2);
      const view = new DataView(buffer);
      writeString(view, 0, 'RIFF');
      view.setUint32(4, 36 + samples.length * 2, true);
      writeString(view, 8, 'WAVE');
      writeString(view, 12, 'fmt ');
      view.setUint32(16, 16, true);
      view.setUint16(20, 1, true);
      view.setUint16(22, 1, true);
      view.setUint32(24, sampleRate, true);
      view.setUint32(28, sampleRate * 2, true);
      view.setUint16(32, 2, true);
      view.setUint16(34, 16, true);
      writeString(view, 36, 'data');
      view.setUint32(40, samples.length * 2, true);
      let offset = 44;
      for (const sample of samples) {
        const clamped = Math.max(-1, Math.min(1, sample));
        view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
        offset += 2;
      }
      return new Uint8Array(buffer);
    }

    function writeString(view, offset, value) {
      for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i));
    }

    loadStatus();
  </script>
</body>
</html>
"""
```

- [ ] **Step 4: Run static and server tests**

Run:

```bash
./scripts/test tests/runtime/test_mvp6_debug_console_static.py tests/runtime/test_mvp6_debug_console_server.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 6**

Run:

```bash
git add src/voice_agent/runtime/mvp6_debug_console_static.py tests/runtime/test_mvp6_debug_console_static.py src/voice_agent/runtime/mvp6_debug_console_server.py
git commit -m "feat: add MVP6 debug console UI"
```

## Task 7: CLI Entrypoint

**Files:**
- Create: `scripts/mvp6-debug-console`
- Modify: `src/voice_agent/runtime/mvp6_debug_console_server.py`
- Test: `tests/runtime/test_mvp6_debug_console_server.py`

- [ ] **Step 1: Add failing CLI help test**

Append to `tests/runtime/test_mvp6_debug_console_server.py`:

```python
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
```

- [ ] **Step 2: Run CLI help test and verify it fails**

Run:

```bash
./scripts/test tests/runtime/test_mvp6_debug_console_server.py::test_cli_help_lists_local_console_options -q
```

Expected: fail because `scripts/mvp6-debug-console` does not exist.

- [ ] **Step 3: Implement CLI main**

Add to `src/voice_agent/runtime/mvp6_debug_console_server.py`:

```python
import argparse
import os
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the MVP6 local debug console.")
    parser.add_argument("--approval-packet", default=None, help="Local-only approval packet JSON path.")
    parser.add_argument("--output-root", default="outputs/mvp6-debug-console", help="Ignored local output root.")
    parser.add_argument("--host", default="127.0.0.1", help="Local bind host.")
    parser.add_argument("--port", type=int, default=8766, help="Local bind port.")
    args = parser.parse_args(argv)
    approval_packet = _load_approval_packet(Path(args.approval_packet)) if args.approval_packet else None
    config = MVP6DebugConsoleConfig(
        output_root=Path(args.output_root),
        approval_packet=approval_packet,
        bind_host=args.host,
    )
    server = create_mvp6_http_server(config=config, env=os.environ, host=args.host, port=args.port)
    print(f"MVP6 debug console listening on http://{args.host}:{server.server_address[1]}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    return 0


def _load_approval_packet(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload, dict):
        raise MVP6DebugConsoleError("approval packet must be a JSON object")
    return payload
```

Create `scripts/mvp6-debug-console`:

```python
#!/usr/bin/env python3
from voice_agent.runtime.mvp6_debug_console_server import main


if __name__ == "__main__":
    raise SystemExit(main())
```

Make it executable:

```bash
chmod +x scripts/mvp6-debug-console
```

- [ ] **Step 4: Run CLI tests**

Run:

```bash
./scripts/test tests/runtime/test_mvp6_debug_console_server.py -q
scripts/mvp6-debug-console --help
```

Expected: tests pass and help exits 0.

- [ ] **Step 5: Commit Task 7**

Run:

```bash
git add scripts/mvp6-debug-console src/voice_agent/runtime/mvp6_debug_console_server.py tests/runtime/test_mvp6_debug_console_server.py
git commit -m "feat: add MVP6 debug console CLI"
```

## Task 8: Acceptance Tests and Operating Documentation

**Files:**
- Create: `tests/acceptance/test_mvp6_acceptance_scenarios.py`
- Create: `docs/implementation/mvp6-local-debug-console.md`
- Modify: `docs/implementation/mvp6-local-debug-console.md`

- [ ] **Step 1: Write failing acceptance tests**

Create `tests/acceptance/test_mvp6_acceptance_scenarios.py`:

```python
from __future__ import annotations

from pathlib import Path


SCENARIOS = (
    "MVP6-LOCAL-CONSOLE-STARTUP-001",
    "MVP6-MIC-DRAFT-RUN-001",
    "MVP6-PROVIDER-FREE-RUN-001",
    "MVP6-LIVE-PROVIDER-GATE-001",
    "MVP6-PIPELINE-INSPECTOR-001",
    "MVP6-QA-HISTORY-001",
    "MVP6-SAFETY-REDACTION-001",
    "MVP6-NO-ARCHITECTURE-EXPANSION-001",
)


def test_mvp6_operating_doc_lists_all_acceptance_scenarios() -> None:
    doc = Path("docs/implementation/mvp6-local-debug-console.md").read_text(encoding="utf-8")
    for scenario in SCENARIOS:
        assert scenario in doc


def test_mvp6_operating_doc_states_non_goals_and_safe_artifacts() -> None:
    doc = Path("docs/implementation/mvp6-local-debug-console.md").read_text(encoding="utf-8")
    required_phrases = (
        "No realtime microphone streaming",
        "No real TTS",
        "No real Slow LLM",
        "No new canonical event",
        "No new RouterDecision",
        "outputs/mvp6-debug-console/qa-history.jsonl",
        "QA history is local-only",
        "raw audio is not saved to QA history",
    )
    for phrase in required_phrases:
        assert phrase in doc
```

- [ ] **Step 2: Run acceptance tests and verify they fail**

Run:

```bash
./scripts/test tests/acceptance/test_mvp6_acceptance_scenarios.py -q
```

Expected: fail because `docs/implementation/mvp6-local-debug-console.md` does not exist.

- [ ] **Step 3: Write operating documentation**

Create `docs/implementation/mvp6-local-debug-console.md` with these sections:

````markdown
# MVP6 Local Developer Debug Console

## Goal

MVP6 provides a local-only developer debug console for the MVP5 single-audio
routing path.

## Start The Console

```bash
scripts/mvp6-debug-console \
  --approval-packet outputs/mvp6-debug-console/approval.json
```

Provider-free mode is the default. DashScope Live mode is visible in the page
but requires server-side approval and credential readiness.

## Approval Packet

```json
{
  "approval_id": "mvp6-local-debug-console-local",
  "live_provider_opt_in": true,
  "local_wav_opt_in": true,
  "metadata_only_output": true,
  "replay_reruns_provider": false,
  "provider_adapter_ids": ["mvp5_asr_adapter", "mvp5_thinker_adapter"],
  "credential_env_var_name": "DASHSCOPE_API_KEY",
  "max_provider_calls": 2,
  "timeout_ms": 30000,
  "safe_output_ref": "summary://mvp6/debug-console/local"
}
```

## QA History

QA history is local-only and may contain ASR user text. It is written to:

```text
outputs/mvp6-debug-console/qa-history.jsonl
```

raw audio is not saved to QA history. Provider request bodies, provider response
bodies, prompt dumps, local paths, and secrets are also not saved.

## Acceptance Scenarios

- MVP6-LOCAL-CONSOLE-STARTUP-001
- MVP6-MIC-DRAFT-RUN-001
- MVP6-PROVIDER-FREE-RUN-001
- MVP6-LIVE-PROVIDER-GATE-001
- MVP6-PIPELINE-INSPECTOR-001
- MVP6-QA-HISTORY-001
- MVP6-SAFETY-REDACTION-001
- MVP6-NO-ARCHITECTURE-EXPANSION-001

## Non-Goals

- No realtime microphone streaming.
- No real TTS.
- No real Slow LLM.
- No production demo UI claim.
- No real external side-effect tool execution.
- No new canonical event.
- No new RouterDecision.
````

- [ ] **Step 4: Run acceptance tests**

Run:

```bash
./scripts/test tests/acceptance/test_mvp6_acceptance_scenarios.py -q
```

Expected: `2 passed`.

- [ ] **Step 5: Commit Task 8**

Run:

```bash
git add tests/acceptance/test_mvp6_acceptance_scenarios.py docs/implementation/mvp6-local-debug-console.md
git commit -m "docs: add MVP6 debug console operating guide"
```

## Task 9: Final Verification and Browser Smoke

**Files:**
- Verify all files from Tasks 1-8.

- [ ] **Step 1: Run focused MVP6 tests**

Run:

```bash
./scripts/test tests/runtime/test_mvp6_debug_console_history.py -q
./scripts/test tests/runtime/test_mvp6_debug_console_status.py -q
./scripts/test tests/runtime/test_mvp6_debug_console_runs.py -q
./scripts/test tests/runtime/test_mvp6_debug_console_server.py -q
./scripts/test tests/runtime/test_mvp6_debug_console_static.py -q
./scripts/test tests/acceptance/test_mvp6_acceptance_scenarios.py -q
```

Expected: all focused tests pass.

- [ ] **Step 2: Run existing MVP5 smoke tests to catch regressions**

Run:

```bash
./scripts/test tests/runtime/test_mvp5_real_voice_e2e_smoke.py tests/runtime/test_mvp5_live_voice_evidence.py tests/runtime/test_mvp5_live_route_results.py -q
```

Expected: all selected MVP5 tests pass.

- [ ] **Step 3: Run full suite**

Run:

```bash
./scripts/test
```

Expected: full suite passes.

- [ ] **Step 4: Run CLI help**

Run:

```bash
scripts/mvp6-debug-console --help
```

Expected: exits 0 and lists `--approval-packet`, `--output-root`, `--host`, and `--port`.

- [ ] **Step 5: Start local server for manual/browser verification**

Run:

```bash
scripts/mvp6-debug-console --port 8766
```

Open:

```text
http://127.0.0.1:8766
```

Verify:

- Page loads.
- Status bar shows Provider Fake by default.
- Record/Stop/Clear/Run controls are visible.
- Expected route control includes `auto`, `FAST_ONLY`, `SPAWN_SLOW_TASK`, and `PATCH_ACTIVE_SLOW_TASK`.
- Pipeline rows show `local_audio_gate`, `asr`, `thinker`, `router`, and `qa_history`.
- No secret, local path, provider body, prompt dump, or raw audio bytes appear in the page.

- [ ] **Step 6: Run whitespace and status checks**

Run:

```bash
git diff --check
git status --short --branch
```

Expected: no whitespace errors; status shows only intended MVP6 commits or a clean branch.

- [ ] **Step 7: Final commit if manual verification required documentation edits**

If Task 9 required doc or test updates, run:

```bash
git add docs/implementation/mvp6-local-debug-console.md tests/runtime/test_mvp6_debug_console_static.py
git commit -m "test: close MVP6 debug console verification"
```

If no edits were made, do not create an empty commit.

## Self-Review Checklist

- Each spec requirement maps to a task:
  - local Python server: Tasks 5 and 7.
  - plain HTML/JS mic page: Task 6.
  - default provider-free mode: Tasks 2 and 3.
  - explicit DashScope live mode: Task 4.
  - QA history with ASR question text: Tasks 1 and 3.
  - metadata/pipeline response: Tasks 3 and 5.
  - redaction and no raw audio/history safety: Tasks 1, 3, 5, and 8.
  - acceptance coverage: Task 8.
- No plan step requires real provider calls in default tests.
- No plan step adds canonical events or RouterDecision values.
- No plan step writes raw audio, provider bodies, prompt dumps, secrets, or local paths to committed artifacts.
- All Python verification commands use `./scripts/test`.
