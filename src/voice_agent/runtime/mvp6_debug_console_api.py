from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any


class MVP6DebugConsoleError(ValueError):
    """Raised when MVP-6 debug console input or output is unsafe."""


_LOCAL_BIND_HOSTS = {"127.0.0.1", "localhost", "::1"}
_DEFAULT_PROVIDER_MODES = ("fake", "dashscope_live")
_CREDENTIAL_ENV_VAR_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_SAFE_RESPONSE_KEYS = frozenset(
    {
        "approval_loaded",
        "credential_env_var_name",
        "credential_present",
        "default_provider_mode",
        "max_provider_calls",
        "metadata_only_output",
        "provider_modes",
        "qa_history_enabled_default",
        "status",
        "timeout_ms",
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


def validate_mvp6_safe_response(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested_value in value.items():
            if not isinstance(key, str) or key not in _SAFE_RESPONSE_KEYS:
                raise MVP6DebugConsoleError("unsafe response key rejected")
            validate_mvp6_safe_response(nested_value)
        return

    if isinstance(value, (bytes, bytearray)):
        raise MVP6DebugConsoleError("unsafe response bytes rejected")

    if isinstance(value, str):
        value_lower = value.lower()
        for marker in _UNSAFE_RESPONSE_MARKERS:
            if marker in value_lower:
                raise MVP6DebugConsoleError("unsafe response value rejected")
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
