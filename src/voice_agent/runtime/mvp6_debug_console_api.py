from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import importlib
import io
from pathlib import Path
import re
import time
from typing import Any
import wave

from voice_agent.runtime.mvp5_live_router_runner import MVP5ActiveSlowTaskContext
from voice_agent.runtime.mvp5_real_voice_e2e_smoke import (
    build_mvp5_provider_free_fake_transports,
    run_mvp5_real_voice_e2e_single,
)
from voice_agent.runtime.mvp6_debug_console_history import (
    MVP6QAHistoryEntry,
    append_mvp6_qa_history,
)


class MVP6DebugConsoleError(ValueError):
    """Raised when MVP-6 debug console input or output is unsafe."""


_LOCAL_BIND_HOSTS = {"127.0.0.1", "localhost", "::1"}
_DEFAULT_PROVIDER_MODES = ("fake", "dashscope_live")
_CREDENTIAL_ENV_VAR_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
_UNSAFE_RESPONSE_KEYS = frozenset(
    {
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
        "authorization",
        "cookie",
        "credential",
        "secret",
        "password",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
    }
)
_UNSAFE_RESPONSE_MARKERS = tuple(
    marker.lower()
    for marker in (
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
        "approval_packet_path",
    )
)


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
    validate_mvp6_safe_response(status)
    return status


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
    if provider_mode == "dashscope_live":
        failure = _live_gate_failure(config=config, env=env)
        if failure is not None:
            return _safe_failure_response(status=failure, provider_mode=provider_mode)

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
    validate_mvp6_safe_response(response)
    return response


def resolve_mvp6_question_text(
    metadata: Mapping[str, Any],
    *,
    provider_mode: str,
) -> str | None:
    if provider_mode == "fake":
        return _synthetic_question_text(str(metadata.get("actual_route") or "FAST_ONLY"))
    for ref in metadata.get("safe_refs", ()):
        if isinstance(ref, str) and ref.startswith("text://provider/dashscope/"):
            module = importlib.import_module("voice_agent.adapters.asr_live_transport")
            resolver = getattr(module, "resolve_asr_live_transcript_text_ref")
            text = resolver(ref)
            if isinstance(text, str) and text.strip():
                return text
    return None


def validate_mvp6_safe_response(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested_value in value.items():
            if not isinstance(key, str) or key.lower() in _UNSAFE_RESPONSE_KEYS:
                raise MVP6DebugConsoleError("unsafe response key rejected")
            _validate_safe_string(key)
            validate_mvp6_safe_response(nested_value)
        return

    if isinstance(value, (bytes, bytearray)):
        raise MVP6DebugConsoleError("unsafe response bytes rejected")

    if isinstance(value, str):
        _validate_safe_string(value)
        return

    if isinstance(value, Sequence):
        for item in value:
            validate_mvp6_safe_response(item)
        return

    if value is None or isinstance(value, (bool, int, float)):
        return

    raise MVP6DebugConsoleError("unsupported response value rejected")


def _credential_env_var_name(packet: Mapping[str, Any] | None) -> str | None:
    if packet is None:
        return None
    value = packet.get("credential_env_var_name")
    if value is None:
        return None
    if not isinstance(value, str) or not _CREDENTIAL_ENV_VAR_RE.match(value):
        raise MVP6DebugConsoleError("credential env var name is unsafe")
    return value


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise MVP6DebugConsoleError(f"{field_name} must be positive")
    return value


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
        with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
            if wav_file.getframerate() <= 0 or wav_file.getnframes() <= 0:
                raise MVP6DebugConsoleError("uploaded wav metadata is invalid")
    except (EOFError, wave.Error) as exc:
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
        task_id=_require_safe_token(request.active_task_id, "active_task_id"),
        current_plan_version=_positive_int(request.active_plan_version, "active_plan_version"),
        current_task_event_seq=_positive_int(
            request.active_task_event_seq,
            "active_task_event_seq",
        ),
        lifecycle_phase=_require_safe_token(
            request.active_lifecycle_phase,
            "active_lifecycle_phase",
        ),
    )


def _response_from_mvp5_metadata(
    metadata: Mapping[str, Any],
    *,
    provider_mode: str,
    question_text: str | None,
    history_written: bool,
) -> dict[str, Any]:
    actual_route = _optional_string(metadata.get("actual_route"))
    task_focus_hint = metadata.get("task_focus_hint")
    response: dict[str, Any] = {
        "status": "completed" if metadata.get("status") == "routed" else metadata.get("status"),
        "run_id": metadata.get("run_id"),
        "provider_mode": provider_mode,
        "actual_route": actual_route,
        "router_decision": _optional_string(metadata.get("router_decision")),
        "route_result_kind": _optional_string(metadata.get("route_result_kind")),
        "expected_route": _optional_string(metadata.get("expected_route")),
        "expected_route_matched": metadata.get("expected_route_matched"),
        "question_text": question_text,
        "answer_display": _answer_display(actual_route, task_focus_hint),
        "provider_call_used": bool(metadata.get("provider_call_used")),
        "fake_transport_used": bool(metadata.get("fake_transport_used")),
        "asr_output_mode": _optional_string(metadata.get("asr_output_mode")),
        "thinker_output_mode": _optional_string(metadata.get("thinker_output_mode")),
        "event_ids": [str(event_id) for event_id in metadata.get("event_ids", ())],
        "safe_refs": [str(ref) for ref in metadata.get("safe_refs", ())],
        "pipeline": [
            {"stage": "local_audio_gate", "status": "passed"},
            {"stage": "asr", "status": "completed", "output_mode": metadata.get("asr_output_mode")},
            {
                "stage": "thinker",
                "status": "completed",
                "output_mode": metadata.get("thinker_output_mode"),
            },
            {"stage": "router", "status": "completed", "actual_route": actual_route},
            {"stage": "qa_history", "status": "completed" if history_written else "skipped"},
        ],
        "history_written": history_written,
        "safety": _safety_flags(),
    }
    validate_mvp6_safe_response(response)
    return response


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
    return f"Router chose {actual_route} from {focus} evidence."


def _history_entry_from_response(response: Mapping[str, Any]) -> MVP6QAHistoryEntry:
    return MVP6QAHistoryEntry(
        run_id=str(response["run_id"]),
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        provider_mode=str(response["provider_mode"]),
        question_source="asr_transcript",
        question_text=str(response.get("question_text") or ""),
        answer_kind="debug_route_answer",
        answer_display=str(response.get("answer_display") or ""),
        actual_route=_optional_string(response.get("actual_route")),
        router_decision=_optional_string(response.get("router_decision")),
        route_result_kind=_optional_string(response.get("route_result_kind")),
        asr_output_mode=_optional_string(response.get("asr_output_mode")),
        thinker_output_mode=_optional_string(response.get("thinker_output_mode")),
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
    response: dict[str, Any] = {
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
    validate_mvp6_safe_response(response)
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


def _require_safe_token(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or not _SAFE_TOKEN_RE.fullmatch(value):
        raise MVP6DebugConsoleError(f"{field_name} must be a safe token")
    _validate_safe_string(value)
    return value


def _validate_safe_string(value: str) -> None:
    value_lower = value.lower()
    for marker in _UNSAFE_RESPONSE_MARKERS:
        if marker in value_lower:
            raise MVP6DebugConsoleError("unsafe response value rejected")
    if value.startswith("/") or value.startswith("~") or re.match(r"^[A-Za-z]:[\\/]", value):
        raise MVP6DebugConsoleError("unsafe response value rejected")


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
