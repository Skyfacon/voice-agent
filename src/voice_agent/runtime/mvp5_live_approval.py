from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any


class LiveProviderApprovalError(ValueError):
    """Raised when MVP-5 live provider authorization fails closed."""


_ENV_VAR_NAME_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_UNSAFE_REF_MARKERS = (
    "file://",
    "data:",
    "/Users/",
    "audio/raw/",
    "diagnostics/",
    "traces/",
    "replays/local/",
    ".env",
    "authorization:",
    "cookie:",
    "token=",
    "api_key=",
)


@dataclass(frozen=True)
class MVP5LiveProviderApprovalRequest:
    live_provider: bool = False
    approval_packet: Mapping[str, Any] | None = None
    credential_env_var_name: str | None = None
    requested_provider_calls: int = 0
    max_provider_calls: int = 0
    timeout_ms: int = 30_000
    allow_local_wav: bool = False
    metadata_only_output: bool = True
    provider_adapter_ids: tuple[str, ...] = ()
    safe_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class MVP5LiveProviderApprovalGrant:
    credential_env_var_name: str
    requested_provider_calls: int
    max_provider_calls: int
    timeout_ms: int
    provider_adapter_ids: tuple[str, ...]
    safe_refs: tuple[str, ...]

    def to_metadata(self) -> dict[str, object]:
        return {
            "live_provider_allowed": True,
            "credential_env_var_name": self.credential_env_var_name,
            "credential_value_included": False,
            "requested_provider_calls": self.requested_provider_calls,
            "max_provider_calls": self.max_provider_calls,
            "timeout_ms": self.timeout_ms,
            "provider_adapter_ids": list(self.provider_adapter_ids),
            "safe_refs": list(self.safe_refs),
            "metadata_only_output": True,
            "raw_audio_included": False,
            "raw_transcript_included": False,
            "raw_provider_body_included": False,
            "prompt_dump_included": False,
            "secret_included": False,
            "local_wav_path_included": False,
            "replay_reruns_provider": False,
        }

    def __repr__(self) -> str:
        return (
            "MVP5LiveProviderApprovalGrant("
            f"credential_env_var_name={self.credential_env_var_name!r}, "
            f"requested_provider_calls={self.requested_provider_calls}, "
            f"max_provider_calls={self.max_provider_calls}, "
            f"timeout_ms={self.timeout_ms}, "
            f"provider_adapter_ids={self.provider_adapter_ids!r}, "
            "credential_value_redacted=True)"
        )


def validate_mvp5_live_provider_approval(
    request: MVP5LiveProviderApprovalRequest,
    *,
    env: Mapping[str, str],
) -> MVP5LiveProviderApprovalGrant:
    if not request.live_provider:
        raise LiveProviderApprovalError("live_provider opt-in is required before provider calls")
    if request.approval_packet is None:
        raise LiveProviderApprovalError("approval packet is required before provider calls")
    if not isinstance(request.approval_packet, Mapping):
        raise LiveProviderApprovalError("approval packet must be structured metadata")

    approval_packet = request.approval_packet
    _validate_approval_packet(approval_packet)
    credential_env_var_name = _select_credential_env_var_name(request, approval_packet)
    _validate_credential_env_var_name(credential_env_var_name)
    if not env.get(credential_env_var_name):
        raise LiveProviderApprovalError(
            f"credential env var name is not present: {credential_env_var_name}"
        )

    max_provider_calls = _select_positive_int(
        request.max_provider_calls,
        approval_packet.get("max_provider_calls"),
        field_name="request budget",
    )
    requested_provider_calls = request.requested_provider_calls
    if requested_provider_calls <= 0:
        raise LiveProviderApprovalError("request budget must include at least one provider call")
    if requested_provider_calls > max_provider_calls:
        raise LiveProviderApprovalError("request budget overflow before provider calls")

    approved_packet_budget = approval_packet.get("max_provider_calls")
    if isinstance(approved_packet_budget, int) and requested_provider_calls > approved_packet_budget:
        raise LiveProviderApprovalError("request budget exceeds approval packet before provider calls")

    timeout_ms = _select_positive_int(
        request.timeout_ms,
        approval_packet.get("timeout_ms"),
        field_name="timeout",
    )
    approved_timeout_ms = approval_packet.get("timeout_ms")
    if isinstance(approved_timeout_ms, int) and timeout_ms > approved_timeout_ms:
        raise LiveProviderApprovalError("timeout exceeds approval packet before provider calls")

    if request.allow_local_wav is not True or approval_packet.get("local_wav_opt_in") is not True:
        raise LiveProviderApprovalError("local wav opt-in is required before live provider calls")
    if request.metadata_only_output is not True or approval_packet.get("metadata_only_output") is not True:
        raise LiveProviderApprovalError("metadata-only output is required before provider calls")

    provider_adapter_ids = _select_provider_adapter_ids(request, approval_packet)
    safe_refs = tuple(request.safe_refs) + tuple(_packet_ref_values(approval_packet))
    for ref in safe_refs:
        if not is_safe_mvp5_live_ref(ref):
            raise LiveProviderApprovalError("unsafe ref rejected before provider calls")

    return MVP5LiveProviderApprovalGrant(
        credential_env_var_name=credential_env_var_name,
        requested_provider_calls=requested_provider_calls,
        max_provider_calls=max_provider_calls,
        timeout_ms=timeout_ms,
        provider_adapter_ids=provider_adapter_ids,
        safe_refs=safe_refs,
    )


def is_safe_mvp5_live_ref(ref: str) -> bool:
    if not isinstance(ref, str) or not ref:
        return False
    lowered = ref.lower()
    if ref.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", ref):
        return False
    return not any(marker in lowered for marker in _UNSAFE_REF_MARKERS)


def _validate_approval_packet(approval_packet: Mapping[str, Any]) -> None:
    if approval_packet.get("live_provider_opt_in") is not True:
        raise LiveProviderApprovalError("approval packet must explicitly opt in to live provider")
    if approval_packet.get("metadata_only_output") is not True:
        raise LiveProviderApprovalError("approval packet must require metadata-only output")
    if approval_packet.get("replay_reruns_provider") is not False:
        raise LiveProviderApprovalError("approval packet must state replay never reruns provider")


def _select_credential_env_var_name(
    request: MVP5LiveProviderApprovalRequest,
    approval_packet: Mapping[str, Any],
) -> str:
    request_name = request.credential_env_var_name
    packet_name = approval_packet.get("credential_env_var_name")
    if not isinstance(request_name, str) or not request_name:
        raise LiveProviderApprovalError("credential env var name is required before provider calls")
    if packet_name is not None and packet_name != request_name:
        raise LiveProviderApprovalError("credential env var name must match approval packet")
    return request_name


def _validate_credential_env_var_name(credential_env_var_name: str) -> None:
    if not _ENV_VAR_NAME_PATTERN.fullmatch(credential_env_var_name):
        raise LiveProviderApprovalError("credential env var name is unsafe")


def _select_positive_int(
    request_value: int,
    approval_value: Any,
    *,
    field_name: str,
) -> int:
    value = request_value if request_value else approval_value
    if not isinstance(value, int) or value <= 0:
        raise LiveProviderApprovalError(f"{field_name} must be a positive integer")
    return value


def _select_provider_adapter_ids(
    request: MVP5LiveProviderApprovalRequest,
    approval_packet: Mapping[str, Any],
) -> tuple[str, ...]:
    request_ids = _validate_provider_adapter_ids(
        request.provider_adapter_ids,
        source="request",
    )
    packet_ids = _validate_provider_adapter_ids(
        approval_packet.get("provider_adapter_ids"),
        source="approval packet",
    )
    if request_ids != packet_ids:
        raise LiveProviderApprovalError(
            "request provider adapter ids must exactly match approval packet"
        )
    return request_ids


def _validate_provider_adapter_ids(value: Any, *, source: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise LiveProviderApprovalError(
            f"{source} provider adapter ids are required before provider calls"
        )
    adapter_ids = tuple(value)
    if not adapter_ids:
        raise LiveProviderApprovalError(
            f"{source} provider adapter ids are required before provider calls"
        )
    if any(
        not isinstance(adapter_id, str)
        or not adapter_id
        or not re.fullmatch(r"[A-Za-z0-9_.:-]+", adapter_id)
        for adapter_id in adapter_ids
    ):
        raise LiveProviderApprovalError("provider adapter ids must be safe metadata")
    if len(set(adapter_ids)) != len(adapter_ids):
        raise LiveProviderApprovalError("provider adapter ids must not contain duplicates")
    return adapter_ids


def _packet_ref_values(approval_packet: Mapping[str, Any]) -> tuple[str, ...]:
    refs: list[str] = []
    for key, value in approval_packet.items():
        if key.endswith("_ref") and isinstance(value, str):
            refs.append(value)
        elif key.endswith("_refs") and isinstance(value, Sequence) and not isinstance(
            value,
            (str, bytes, bytearray),
        ):
            refs.extend(str(item) for item in value)
    return tuple(refs)
