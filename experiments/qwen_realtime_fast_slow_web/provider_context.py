"""Credential and endpoint handling for the Slice 2 Qwen adapters.

The credential object is deliberately opaque and non-serializable.  Only this
module and the provider adapters may ask it for an Authorization header or the
Realtime endpoint.  Browser/timeline metadata receives presence flags and a
one-way workspace reference only.
"""

from __future__ import annotations

import hashlib
import os
import re
from typing import Any, Mapping
from urllib.parse import urlsplit


MODEL_NAME = "qwen-audio-3.0-realtime-plus"
BEIJING_REALTIME_HOST_SUFFIX = ".cn-beijing.maas.aliyuncs.com"
_ENDPOINT_TEMPLATE = (
    "wss://{workspace_id}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime"
    "?model=qwen-audio-3.0-realtime-plus"
)
_SAFE_WORKSPACE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class ProviderConfigurationError(ValueError):
    """A low-information configuration failure safe to expose by code only."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class CredentialHandle:
    """Opaque in-process Qwen credential holder.

    ``__slots__`` intentionally makes ``vars(handle)`` fail.  ``json.dumps``
    likewise has no implicit representation, while ``repr`` and metadata never
    include either raw value.
    """

    __slots__ = ("_api_key", "_workspace_id", "_workspace_source")

    def __init__(
        self,
        api_key: str,
        workspace_id: str,
        *,
        workspace_source: str = "explicit",
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ProviderConfigurationError("missing_dashscope_api_key")
        workspace_id = _validate_workspace_id(workspace_id)
        self._api_key = api_key.strip()
        self._workspace_id = workspace_id
        self._workspace_source = workspace_source

    @classmethod
    def resolve(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        safe_base_url: str | None = None,
        explicit_workspace_id: str | None = None,
        verified_workspace_id: str | None = None,
    ) -> "CredentialHandle":
        """Resolve credentials with the Slice 2 precedence contract.

        Workspace precedence is:

        1. ``QWEN_REALTIME_WORKSPACE_ID``;
        2. a validated Beijing Qwen base-URL hostname;
        3. the explicit CLI value supplied by the caller;
        4. a caller-supplied, previously verified workspace ID.

        No workstation-specific workspace identifier is compiled into the
        repository.  A known value must still arrive through a trusted runtime
        argument.
        """

        env = os.environ if environment is None else environment
        api_key = env.get("DASHSCOPE_API_KEY", "")

        env_workspace = _nonempty(env.get("QWEN_REALTIME_WORKSPACE_ID"))
        configured_base = _nonempty(safe_base_url) or _nonempty(
            env.get("QWEN_REALTIME_BASE_URL")
        )

        if env_workspace is not None:
            workspace_id = env_workspace
            source = "environment"
        elif configured_base is not None:
            workspace_id = workspace_id_from_safe_base_url(configured_base)
            source = "safe_base_url"
        elif _nonempty(explicit_workspace_id) is not None:
            workspace_id = str(explicit_workspace_id).strip()
            source = "explicit_cli"
        elif _nonempty(verified_workspace_id) is not None:
            workspace_id = str(verified_workspace_id).strip()
            source = "verified_fallback"
        else:
            raise ProviderConfigurationError("missing_qwen_realtime_workspace_id")

        return cls(api_key, workspace_id, workspace_source=source)

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> "CredentialHandle":
        return cls.resolve(environment)

    def _authorization_headers(self) -> dict[str, str]:
        """Provider-bound only; callers must never log or serialize this."""

        return {"Authorization": f"Bearer {self._api_key}"}

    def _endpoint(self) -> str:
        return _ENDPOINT_TEMPLATE.format(workspace_id=self._workspace_id)

    def to_metadata(self) -> dict[str, Any]:
        digest = hashlib.sha256(self._workspace_id.encode("utf-8")).hexdigest()[:12]
        return {
            "api_key_configured": True,
            "workspace_id_configured": True,
            "workspace_resolution_source": self._workspace_source,
            "workspace_ref": f"workspace-{digest}",
            "endpoint_ref": "aliyun-bailian/cn-beijing/realtime",
            "model_name": MODEL_NAME,
        }

    def __repr__(self) -> str:
        return (
            "CredentialHandle(api_key=<redacted>, workspace_id=<redacted>, "
            f"workspace_source={self._workspace_source!r})"
        )

    __str__ = __repr__

    def __reduce_ex__(self, _protocol: int) -> object:
        """Prevent pickle-based credential extraction from diagnostics code."""

        raise TypeError("credential_handle_not_serializable")


def workspace_id_from_safe_base_url(value: str) -> str:
    """Extract a workspace ID only from an expected Beijing Qwen host.

    Both the compatible-mode HTTPS URL and the Realtime WSS URL are accepted;
    their paths are ignored and the adapter always constructs the documented
    Realtime path itself.
    """

    if not isinstance(value, str) or not value.strip():
        raise ProviderConfigurationError("invalid_qwen_realtime_base_url")
    try:
        parsed = urlsplit(value.strip())
        parsed_port = parsed.port
    except ValueError:
        raise ProviderConfigurationError("invalid_qwen_realtime_base_url") from None
    if parsed.scheme not in {"https", "wss"}:
        raise ProviderConfigurationError("invalid_qwen_realtime_base_url")
    if parsed.username is not None or parsed.password is not None or parsed_port:
        raise ProviderConfigurationError("invalid_qwen_realtime_base_url")
    hostname = (parsed.hostname or "").lower()
    if not hostname.endswith(BEIJING_REALTIME_HOST_SUFFIX):
        raise ProviderConfigurationError("invalid_qwen_realtime_base_url")
    workspace_id = hostname[: -len(BEIJING_REALTIME_HOST_SUFFIX)]
    if not workspace_id or "." in workspace_id:
        raise ProviderConfigurationError("invalid_qwen_realtime_base_url")
    return _validate_workspace_id(workspace_id)


def _validate_workspace_id(value: object) -> str:
    if not isinstance(value, str):
        raise ProviderConfigurationError("invalid_qwen_realtime_workspace_id")
    stripped = value.strip()
    if not _SAFE_WORKSPACE_ID.fullmatch(stripped):
        raise ProviderConfigurationError("invalid_qwen_realtime_workspace_id")
    return stripped


def _nonempty(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


__all__ = [
    "BEIJING_REALTIME_HOST_SUFFIX",
    "CredentialHandle",
    "MODEL_NAME",
    "ProviderConfigurationError",
    "workspace_id_from_safe_base_url",
]
