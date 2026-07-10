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

from voice_agent.adapters.lalm_thinker_routing_profiles import (
    get_default_lalm_thinker_routing_profile,
)
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
        "provider_text",
        "raw_provider_request",
        "raw_provider_response",
        "request_body",
        "response_body",
        "raw_prompt",
        "system_message",
        "developer_message",
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
_LATENCY_DEBUG_MS_FIELDS = (
    "total_server_ms",
    "wav_validate_ms",
    "temp_wav_write_ms",
    "local_audio_gate_ms",
    "approval_gate_ms",
    "asr_provider_http_ms",
    "asr_normalize_emit_ms",
    "thinker_provider_http_ms",
    "thinker_adapter_start_offset_ms",
    "thinker_provider_request_start_offset_ms",
    "thinker_provider_first_chunk_offset_ms",
    "thinker_provider_full_response_offset_ms",
    "thinker_adapter_event_emit_offset_ms",
    "thinker_provider_ttft_ms",
    "thinker_provider_full_response_ms",
    "thinker_provider_generation_ms",
    "thinker_stream_decode_ms",
    "thinker_parse_validate_emit_ms",
    "fast_interaction_provider_http_ms",
    "fast_interaction_adapter_start_offset_ms",
    "fast_interaction_provider_request_start_offset_ms",
    "fast_interaction_provider_first_chunk_offset_ms",
    "fast_interaction_provider_full_response_offset_ms",
    "fast_interaction_adapter_event_emit_offset_ms",
    "fast_interaction_provider_ttft_ms",
    "fast_interaction_provider_full_response_ms",
    "fast_interaction_provider_generation_ms",
    "fast_interaction_stream_decode_ms",
    "fast_interaction_parse_validate_emit_ms",
    "fast_interaction_total_ms",
    "fast_interaction_timeout_ms",
    "foreground_gate_ms",
    "router_ms",
    "qa_history_ms",
)
_LATENCY_DEBUG_BOOL_FIELDS = (
    "provider_calls_parallel",
    "asr_started_before_thinker_finished",
    "thinker_started_before_asr_finished",
    "thinker_ttft_available",
    "fast_interaction_timed_out",
    "fast_interaction_ttft_available",
)
_LATENCY_DEBUG_STRING_FIELDS = (
    "thinker_ttft_source",
    "fast_interaction_input_mode",
    "fast_interaction_timing_mode",
    "fast_interaction_ttft_source",
    "fast_interaction_failure_category",
)
_LATENCY_DEBUG_FIELDS = frozenset(
    (
        *_LATENCY_DEBUG_MS_FIELDS,
        *_LATENCY_DEBUG_BOOL_FIELDS,
        *_LATENCY_DEBUG_STRING_FIELDS,
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
    show_model_io: bool = False
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
        "routing_prompt_profile": get_default_lalm_thinker_routing_profile().to_metadata(),
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
    total_started = time.monotonic()
    latency_debug = _normalize_mvp6_latency_debug({})
    provider_mode = _provider_mode(request.provider_mode)
    expected_route = _expected_route(request.expected_route)
    if expected_route == "PATCH_ACTIVE_SLOW_TASK" and not request.active_task_id:
        return _blocked_missing_active_task_context(provider_mode=provider_mode)
    if provider_mode == "dashscope_live":
        failure = _live_gate_failure(config=config, env=env)
        if failure is not None:
            return _safe_failure_response(status=failure, provider_mode=provider_mode)

    wav_validate_started = time.monotonic()
    _require_wav_upload(request.audio_bytes, request.audio_mime_type)
    wav_validate_ms = _elapsed_ms(wav_validate_started)
    latency_debug["wav_validate_ms"] = wav_validate_ms
    run_id = _run_id(request.audio_bytes)
    temp_wav_write_started = time.monotonic()
    audio_path = _write_temp_wav(config.output_root, run_id, request.audio_bytes)
    temp_wav_write_ms = _elapsed_ms(temp_wav_write_started)
    latency_debug["temp_wav_write_ms"] = temp_wav_write_ms
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
        fast_interaction_enabled=provider_mode == "dashscope_live",
        audio_native_thinker_enabled=provider_mode != "dashscope_live",
        active_task_context=active_context,
    )
    latency_debug.update(_normalize_mvp6_latency_debug(metadata.get("latency_debug", {})))
    latency_debug["wav_validate_ms"] = wav_validate_ms
    latency_debug["temp_wav_write_ms"] = temp_wav_write_ms
    question_text = resolve_mvp6_question_text(metadata, provider_mode=provider_mode)
    response = _response_from_mvp5_metadata(
        metadata,
        provider_mode=provider_mode,
        question_text=question_text,
        history_written=False,
    )
    if request.show_model_io:
        response["model_io_debug"] = _resolve_mvp6_model_io_debug(metadata)
    qa_history_started = time.monotonic()
    if request.save_qa_history:
        append_mvp6_qa_history(config.history_path, _history_entry_from_response(response))
        response["pipeline"][-1]["status"] = "completed"
        response["history_written"] = True
    latency_debug["qa_history_ms"] = _elapsed_ms(qa_history_started)
    latency_debug["total_server_ms"] = _elapsed_ms(total_started)
    response["latency_debug"] = latency_debug
    validate_mvp6_safe_response(response)
    return response


def resolve_mvp6_question_text(
    metadata: Mapping[str, Any],
    *,
    provider_mode: str,
) -> str | None:
    if provider_mode == "fake":
        return _synthetic_question_text(str(metadata.get("actual_route") or "FAST_ONLY"))
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
    status = "completed" if metadata.get("status") == "routed" else metadata.get("status")
    response: dict[str, Any] = {
        "status": status,
        "run_id": metadata.get("run_id"),
        "provider_mode": provider_mode,
        "actual_route": actual_route,
        "router_decision": _optional_string(metadata.get("router_decision")),
        "route_result_kind": _optional_string(metadata.get("route_result_kind")),
        "expected_route": _optional_string(metadata.get("expected_route")),
        "expected_route_matched": metadata.get("expected_route_matched"),
        "question_text": question_text,
        "answer_display": _answer_display(actual_route, task_focus_hint, metadata),
        "provider_call_used": bool(metadata.get("provider_call_used")),
        "fake_transport_used": bool(metadata.get("fake_transport_used")),
        "thinker_transient_asr_text_used": bool(
            metadata.get("thinker_transient_asr_text_used", False)
        ),
        "asr_output_mode": _optional_string(metadata.get("asr_output_mode")),
        "thinker_output_mode": _optional_string(metadata.get("thinker_output_mode")),
        "fast_interaction_output_mode": _optional_string(
            metadata.get("fast_interaction_output_mode")
        ),
        "fast_interaction_adapter_request_id": _optional_string(
            metadata.get("fast_interaction_adapter_request_id")
        ),
        "foreground_act": _optional_string(metadata.get("foreground_act")),
        "foreground_risk_class": _optional_string(metadata.get("foreground_risk_class")),
        "foreground_risk_tags": [
            str(tag) for tag in metadata.get("foreground_risk_tags", ())
        ],
        "foreground_confidence": metadata.get("foreground_confidence"),
        "foreground_gate_decision": _optional_string(
            metadata.get("foreground_gate_decision")
        ),
        "foreground_gate_event_id": _optional_string(
            metadata.get("foreground_gate_event_id")
        ),
        "foreground_gate_failure_reason": _optional_string(
            metadata.get("foreground_gate_failure_reason")
        ),
        "foreground_output_event_id": _optional_string(
            metadata.get("foreground_output_event_id")
        ),
        "foreground_output_ref": _optional_string(
            metadata.get("foreground_output_ref") or metadata.get("response_text_ref")
        ),
        "foreground_output_basis": _optional_string(
            metadata.get("foreground_output_basis")
        ),
        "foreground_discard_event_id": _optional_string(
            metadata.get("foreground_discard_event_id")
        ),
        "foreground_fallback_reason": _optional_string(
            metadata.get("foreground_fallback_reason")
        ),
        "failure_reasons": [str(reason) for reason in metadata.get("failure_reasons", ())],
        "thinker_io_shape": _thinker_io_shape(
            transient_asr_text_used=bool(
                metadata.get("thinker_transient_asr_text_used", False)
            ),
            failure_reasons=metadata.get("failure_reasons", ()),
        ),
        "event_ids": [str(event_id) for event_id in metadata.get("event_ids", ())],
        "safe_refs": [str(ref) for ref in metadata.get("safe_refs", ())],
        "pipeline": _pipeline_from_mvp5_metadata(
            metadata,
            actual_route=actual_route,
            history_written=history_written,
        ),
        "history_written": history_written,
        "latency_debug": _normalize_mvp6_latency_debug(metadata.get("latency_debug", {})),
        "safety": _safety_flags(),
    }
    validate_mvp6_safe_response(response)
    return response


def _thinker_io_shape(
    *,
    transient_asr_text_used: bool,
    failure_reasons: object,
) -> dict[str, Any]:
    return {
        "input_modality": "audio",
        "audio_passed_to_adapter": True,
        "transient_asr_text_present": transient_asr_text_used,
        "candidate_schema": "lalm_thinker_semantic_frame_candidate.v1",
        "expected_output": "single_json_object",
        "routing_hint_field": "task_focus_hint.focus",
        "provider_text_visible": False,
        "raw_audio_visible": False,
        "failure_reasons": [str(reason) for reason in failure_reasons]
        if isinstance(failure_reasons, Sequence)
        and not isinstance(failure_reasons, (str, bytes, bytearray))
        else [],
    }


def _resolve_mvp6_model_io_debug(metadata: Mapping[str, Any]) -> dict[str, Any]:
    asr_debug = None
    asr_adapter_request_id = _asr_adapter_request_id_from_refs(metadata)
    if asr_adapter_request_id is not None:
        module = importlib.import_module("voice_agent.adapters.asr_live_transport")
        resolver = getattr(module, "resolve_asr_live_model_io_debug")
        asr_debug = resolver(asr_adapter_request_id)

    thinker_debug = None
    run_id = metadata.get("run_id")
    if isinstance(run_id, str) and run_id:
        thinker_adapter_request_id = f"adapter-request-mvp5-thinker-{_slug(run_id)}"
        module = importlib.import_module("voice_agent.adapters.lalm_thinker_live_transport")
        resolver = getattr(module, "resolve_lalm_thinker_live_model_io_debug")
        thinker_debug = resolver(thinker_adapter_request_id)

    return {
        "local_only": True,
        "saved_to_history": False,
        "replay_included": False,
        "raw_audio_visible": False,
        "authorization_header_visible": False,
        "asr": _metadata_only_model_io_debug(asr_debug),
        "thinker": _metadata_only_model_io_debug(thinker_debug),
    }


def _metadata_only_model_io_debug(debug: object) -> dict[str, Any] | None:
    if not isinstance(debug, Mapping):
        return None
    provider_response_shape = debug.get("provider_response_shape")
    text_char_count = 0
    provider_output_available = False
    if isinstance(provider_response_shape, Mapping):
        provider_output_available = bool(provider_response_shape.get("text_present", False))
        text_char_count = _non_negative_int(
            provider_response_shape.get("text_char_count", 0),
            "provider_response_text_char_count",
        )
    elif isinstance(debug.get("provider_text"), str):
        provider_output_available = bool(debug.get("provider_text"))
        text_char_count = len(str(debug.get("provider_text")))

    return {
        "metadata_only": True,
        "content_redacted": True,
        "request_payload_available": isinstance(debug.get("request_body"), Mapping)
        or isinstance(debug.get("request_shape"), Mapping),
        "system_instruction_available": isinstance(debug.get("system_message"), str)
        and bool(str(debug.get("system_message"))),
        "provider_output_available": provider_output_available,
        "provider_output_char_count": text_char_count,
        "raw_audio_visible": False,
        "authorization_header_visible": False,
        "saved_to_history": False,
    }


def _asr_adapter_request_id_from_refs(metadata: Mapping[str, Any]) -> str | None:
    for ref in metadata.get("safe_refs", ()):
        if isinstance(ref, str) and ref.startswith("text://provider/dashscope/"):
            adapter_request_id = ref.rsplit("/", 1)[-1]
            return _require_safe_model_io_id(adapter_request_id, "asr_adapter_request_id")
    return None


def _require_safe_model_io_id(value: object, field_name: str) -> str:
    if not isinstance(value, str) or value == "":
        raise MVP6DebugConsoleError(f"{field_name} must be a safe id")
    _validate_safe_string(value)
    return value


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-") or "unknown"


def _pipeline_from_mvp5_metadata(
    metadata: Mapping[str, Any],
    *,
    actual_route: str | None,
    history_written: bool,
) -> list[dict[str, Any]]:
    asr_output_mode = metadata.get("asr_output_mode")
    thinker_output_mode = metadata.get("thinker_output_mode")
    fast_interaction_output_mode = metadata.get("fast_interaction_output_mode")
    foreground_gate_decision = metadata.get("foreground_gate_decision")
    routed = metadata.get("status") == "routed"
    asr_status = "completed" if asr_output_mode else "failed"
    thinker_status = "completed" if thinker_output_mode else (
        "failed" if asr_output_mode else "not_run"
    )
    fast_status = "completed" if fast_interaction_output_mode else (
        "failed" if asr_output_mode and not thinker_output_mode else "not_run"
    )
    router_status = "completed" if routed else "not_run"
    pipeline = [
        {"stage": "local_audio_gate", "status": "passed"},
        {"stage": "asr", "status": asr_status, "output_mode": asr_output_mode},
    ]
    if fast_interaction_output_mode or foreground_gate_decision:
        pipeline.append(
            {
                "stage": "fast_interaction",
                "status": fast_status,
                "output_mode": fast_interaction_output_mode,
            }
        )
    else:
        pipeline.append(
            {
                "stage": "thinker",
                "status": thinker_status,
                "output_mode": thinker_output_mode,
            }
        )
    pipeline.append({"stage": "router", "status": router_status, "actual_route": actual_route})
    if fast_interaction_output_mode or foreground_gate_decision:
        pipeline.append(
            {
                "stage": "foreground_gate",
                "status": "completed" if foreground_gate_decision else "not_run",
                "decision": foreground_gate_decision,
            }
        )
    pipeline.append({"stage": "qa_history", "status": "completed" if history_written else "skipped"})
    return pipeline


def _synthetic_question_text(actual_route: str) -> str:
    if actual_route == "SPAWN_SLOW_TASK":
        return "Plan a multi-step task"
    if actual_route == "PATCH_ACTIVE_SLOW_TASK":
        return "Update the active task"
    return "Ask a short foreground question"


def _answer_display(
    actual_route: object,
    task_focus_hint: object,
    metadata: Mapping[str, Any],
) -> str:
    if actual_route in (None, ""):
        return "Run did not reach router."
    if actual_route == "FAST_ONLY":
        foreground_text = metadata.get("foreground_display_text")
        if (
            metadata.get("foreground_gate_decision") == "passed"
            and isinstance(foreground_text, str)
            and foreground_text.strip()
        ):
            return foreground_text
        resolved_text = _resolve_foreground_display_text(metadata)
        if resolved_text is not None:
            return resolved_text
        return "FAST_ONLY selected; real fast answer is not implemented in MVP6.1 debug console."
    if actual_route == "SPAWN_SLOW_TASK":
        return "我帮你看一下，请稍等。"
    if actual_route == "PATCH_ACTIVE_SLOW_TASK":
        return "收到，我会把这点补充到当前任务里。"
    if actual_route == "IGNORE":
        return "Debug: input ignored as non-assistant or unsupported."
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
    provider_mode = str(response["provider_mode"])
    live_provider = provider_mode != "fake"
    return MVP6QAHistoryEntry(
        run_id=str(response["run_id"]),
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        provider_mode=provider_mode,
        question_source="asr_transcript_ref" if live_provider else "asr_transcript",
        question_text="" if live_provider else str(response.get("question_text") or ""),
        answer_kind="debug_route_answer",
        answer_display=(
            _live_history_answer_summary(response)
            if live_provider
            else str(response.get("answer_display") or "")
        ),
        actual_route=_optional_string(response.get("actual_route")),
        router_decision=_optional_string(response.get("router_decision")),
        route_result_kind=_optional_string(response.get("route_result_kind")),
        asr_output_mode=_optional_string(response.get("asr_output_mode")),
        thinker_output_mode=_optional_string(response.get("thinker_output_mode")),
        fast_interaction_output_mode=_optional_string(
            response.get("fast_interaction_output_mode")
        ),
        foreground_gate_decision=_optional_string(response.get("foreground_gate_decision")),
        foreground_output_basis=_optional_string(response.get("foreground_output_basis")),
        foreground_gate_failure_reason=_optional_string(
            response.get("foreground_gate_failure_reason")
        ),
        latency_debug=response.get("latency_debug", {}),
        provider_call_used=bool(response.get("provider_call_used")),
        fake_transport_used=bool(response.get("fake_transport_used")),
        event_ids=tuple(str(event_id) for event_id in response.get("event_ids", ())),
        safe_refs=tuple(str(ref) for ref in response.get("safe_refs", ())),
    )


def _resolve_foreground_display_text(metadata: Mapping[str, Any]) -> str | None:
    if metadata.get("foreground_gate_decision") != "passed":
        return None
    output_ref = metadata.get("foreground_output_ref") or metadata.get("response_text_ref")
    if not isinstance(output_ref, str) or output_ref == "":
        return None
    module = importlib.import_module("voice_agent.adapters.fast_interaction_runtime_adapter")
    resolver = getattr(module, "resolve_fast_interaction_reply_candidate_ref")
    resolved = resolver(output_ref)
    if not isinstance(resolved, str) or not resolved.strip():
        return None
    _validate_safe_string(resolved)
    return resolved


def _live_history_answer_summary(response: Mapping[str, Any]) -> str:
    if response.get("foreground_gate_decision") == "passed":
        return "[foreground output committed]"
    if response.get("foreground_output_basis") in {"template_ack", "template_clarify"}:
        return str(response.get("foreground_output_basis"))
    return str(response.get("status") or "")


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


def _normalize_mvp6_latency_debug(value: object) -> dict[str, Any]:
    if value in (None, ""):
        source: Mapping[str, Any] = {}
    elif isinstance(value, Mapping):
        source = value
    else:
        raise MVP6DebugConsoleError("latency_debug must be metadata-only")
    unknown_fields = set(source) - _LATENCY_DEBUG_FIELDS
    if unknown_fields:
        raise MVP6DebugConsoleError("latency_debug contains unsafe field")

    latency_debug: dict[str, Any] = {}
    for field in _LATENCY_DEBUG_MS_FIELDS:
        latency_debug[field] = _non_negative_int(source.get(field, 0), field)
    for field in _LATENCY_DEBUG_BOOL_FIELDS:
        latency_debug[field] = bool(source.get(field, False))
    for field in _LATENCY_DEBUG_STRING_FIELDS:
        raw_value = source.get(field, "")
        if raw_value is None:
            latency_debug[field] = ""
        elif isinstance(raw_value, str):
            latency_debug[field] = _require_safe_token(raw_value, field) if raw_value else ""
        else:
            raise MVP6DebugConsoleError(f"{field} must be metadata-only")
    validate_mvp6_safe_response(latency_debug)
    return latency_debug


def _non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise MVP6DebugConsoleError(f"{field_name} must be a non-negative integer")
    if isinstance(value, float):
        if not value.is_integer():
            raise MVP6DebugConsoleError(f"{field_name} must be a non-negative integer")
        value = int(value)
    if not isinstance(value, int) or value < 0:
        raise MVP6DebugConsoleError(f"{field_name} must be a non-negative integer")
    return value


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _require_safe_token(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or not _SAFE_TOKEN_RE.fullmatch(value):
        raise MVP6DebugConsoleError(f"{field_name} must be a safe token")
    _validate_safe_string(value)
    return value


def _validate_safe_string(value: str) -> None:
    value_lower = value.lower()
    if value_lower.startswith("data:"):
        raise MVP6DebugConsoleError("unsafe response value rejected")
    for marker in _UNSAFE_RESPONSE_MARKERS:
        if marker in value_lower:
            raise MVP6DebugConsoleError("unsafe response value rejected")
    if value.startswith("/") or value.startswith("~") or re.match(r"^[A-Za-z]:[\\/]", value):
        raise MVP6DebugConsoleError("unsafe response value rejected")


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
