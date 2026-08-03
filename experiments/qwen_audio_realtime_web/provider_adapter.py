"""Spike-local adapter for the Qwen Audio Realtime WebSocket API.

This is the *only* module in the web spike allowed to know the provider URL,
Authorization header, or provider wire schema.  The rest of the spike consumes
``NormalizedProviderEvent`` values and never receives provider headers or raw
error payloads.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import os
import re
from collections import deque
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

import aiohttp

from .capability_profile import CapabilityProfile, qwen_capability_profile


MODEL_NAME = "qwen-audio-3.0-realtime-plus"
_ENDPOINT_TEMPLATE = (
    "wss://{workspace_id}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime"
    "?model=qwen-audio-3.0-realtime-plus"
)
DEFAULT_VOICE = "longanqian"
DEFAULT_INSTRUCTIONS = (
    "Respond concisely in the user's language. Do not call tools or claim "
    "external actions."
)

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SAFE_VOICE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SAFE_ERROR_TOKEN = re.compile(r"[^A-Za-z0-9_.:-]+")
_MAX_TRANSCRIPT_CHARS = 16_384
_MAX_PROVIDER_AUDIO_BYTES = 262_144


class SafeProviderError(RuntimeError):
    """An intentionally low-information exception safe for local UI display."""

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        self.code = _safe_token(code, fallback="provider_error")
        self.retryable = retryable
        super().__init__(self.code)


class CredentialConfigurationError(SafeProviderError):
    pass


class ProviderConnectionError(SafeProviderError):
    pass


class ProviderDisconnected(SafeProviderError):
    pass


class CredentialHandle:
    """Opaque in-process credential holder with secret-free metadata/repr.

    The raw values intentionally have no public properties and the class uses
    slots so accidental ``vars(handle)`` serialization fails closed.
    """

    __slots__ = ("_api_key", "_workspace_id")

    def __init__(self, api_key: str, workspace_id: str) -> None:
        api_key = api_key.strip()
        workspace_id = workspace_id.strip()
        if not api_key:
            raise CredentialConfigurationError("missing_dashscope_api_key")
        if not _SAFE_IDENTIFIER.fullmatch(workspace_id):
            raise CredentialConfigurationError("invalid_workspace_id")
        self._api_key = api_key
        self._workspace_id = workspace_id

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> "CredentialHandle":
        env = os.environ if environment is None else environment
        return cls(
            env.get("DASHSCOPE_API_KEY", ""),
            env.get("QWEN_REALTIME_WORKSPACE_ID", ""),
        )

    def _authorization_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _endpoint(self) -> str:
        return _ENDPOINT_TEMPLATE.format(workspace_id=self._workspace_id)

    def to_metadata(self) -> dict[str, Any]:
        """Return only presence and a one-way workspace reference."""

        workspace_ref = hashlib.sha256(self._workspace_id.encode("utf-8")).hexdigest()[:12]
        return {
            "api_key_configured": True,
            "workspace_id_configured": True,
            "workspace_ref": f"workspace-{workspace_ref}",
        }

    def __repr__(self) -> str:
        return "CredentialHandle(api_key=<redacted>, workspace_id=<redacted>)"

    __str__ = __repr__


@dataclass(frozen=True, slots=True)
class NormalizedProviderEvent:
    """Provider-neutral transient event consumed by ``SessionBridge``.

    Transcript text and PCM may exist in memory for the live browser session,
    but ``safe_metadata`` never includes either value.
    """

    type: str
    output_mode: str
    response_ref: str | None = None
    session_ref: str | None = None
    text: str | None = None
    stash: str | None = None
    audio: bytes | None = None
    status: str | None = None
    reason: str | None = None
    error_code: str | None = None
    terminal: bool = False

    @property
    def byte_length(self) -> int:
        return len(self.audio) if self.audio is not None else 0

    def safe_metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "type": self.type,
            "output_mode": self.output_mode,
            "byte_length": self.byte_length,
        }
        for key in (
            "response_ref",
            "session_ref",
            "status",
            "reason",
            "error_code",
        ):
            value = getattr(self, key)
            if value is not None:
                metadata[key] = value
        metadata["terminal"] = self.terminal
        return metadata


@runtime_checkable
class RealtimeProviderSession(Protocol):
    """Async provider session contract used by the isolated bridge."""

    @property
    def profile(self) -> CapabilityProfile: ...

    @property
    def response_active(self) -> bool: ...

    async def connect(self) -> None: ...

    async def send_audio(self, pcm16le: bytes) -> None: ...

    async def recv_event(self) -> NormalizedProviderEvent: ...

    async def cancel_response(self) -> bool: ...

    async def close(self) -> None: ...


def build_session_update(
    *, voice: str = DEFAULT_VOICE, instructions: str = DEFAULT_INSTRUCTIONS
) -> dict[str, Any]:
    """Build the minimal, documented Qwen session configuration.

    Input/output PCM formats are documented defaults (16 kHz and 24 kHz,
    respectively).  They are intentionally not duplicated in this payload.
    Voice is sent only in this initial update.
    """

    if not _SAFE_VOICE.fullmatch(voice):
        raise CredentialConfigurationError("invalid_voice")
    if not isinstance(instructions, str) or not (1 <= len(instructions) <= 2_000):
        raise CredentialConfigurationError("invalid_instructions")
    return {
        "type": "session.update",
        "session": {
            "modalities": ["text", "audio"],
            "voice": voice,
            "instructions": instructions,
            "turn_detection": {"type": "smart_turn"},
            "tools": [],
        },
    }


class QwenRealtimeProvider:
    """One remote Qwen WebSocket session.

    There is no reconnect loop: a disconnect ends the browser session, so
    already accepted microphone frames can never be silently replayed.
    """

    def __init__(
        self,
        credentials: CredentialHandle,
        *,
        voice: str = DEFAULT_VOICE,
        instructions: str = DEFAULT_INSTRUCTIONS,
        connect_timeout_seconds: float = 10.0,
        receive_timeout_seconds: float = 90.0,
        max_provider_message_bytes: int = 1_048_576,
    ) -> None:
        if connect_timeout_seconds <= 0 or receive_timeout_seconds <= 0:
            raise ValueError("provider timeouts must be positive")
        if max_provider_message_bytes < 1024:
            raise ValueError("max_provider_message_bytes is too small")
        self._credentials = credentials
        self._session_update = build_session_update(
            voice=voice, instructions=instructions
        )
        self._connect_timeout_seconds = connect_timeout_seconds
        self._receive_timeout_seconds = receive_timeout_seconds
        self._max_provider_message_bytes = max_provider_message_bytes
        self._http_session: aiohttp.ClientSession | None = None
        self._websocket: aiohttp.ClientWebSocketResponse | None = None
        self._profile = qwen_capability_profile()
        self._active_response_id: str | None = None
        self._active_response_ref: str | None = None
        self._cancel_sent_for: str | None = None
        self._prefetched_events: deque[NormalizedProviderEvent] = deque(maxlen=4)
        self._connected = False
        self._closed = False

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> "QwenRealtimeProvider":
        env = os.environ if environment is None else environment
        voice = env.get("QWEN_REALTIME_VOICE", DEFAULT_VOICE)
        return cls(
            CredentialHandle.from_environment(env),
            voice=voice,
            **kwargs,
        )

    @property
    def profile(self) -> CapabilityProfile:
        return self._profile

    @property
    def response_active(self) -> bool:
        return self._active_response_id is not None

    async def connect(self) -> None:
        if self._connected:
            return
        if self._closed:
            raise ProviderConnectionError("provider_session_closed")
        timeout = aiohttp.ClientTimeout(
            total=None,
            sock_connect=self._connect_timeout_seconds,
            sock_read=None,
        )
        self._http_session = aiohttp.ClientSession(timeout=timeout)
        self._prefetched_events.clear()
        try:
            self._websocket = await asyncio.wait_for(
                self._http_session.ws_connect(
                    self._credentials._endpoint(),
                    headers=self._credentials._authorization_headers(),
                    heartbeat=20.0,
                    autoping=True,
                    max_msg_size=self._max_provider_message_bytes,
                ),
                timeout=self._connect_timeout_seconds,
            )
            created = await asyncio.wait_for(
                self._receive_handshake_event("session.created"),
                timeout=self._connect_timeout_seconds,
            )
            await self._websocket.send_json(self._session_update)
            updated = await asyncio.wait_for(
                self._receive_handshake_event("session.updated"),
                timeout=self._connect_timeout_seconds,
            )
            self._prefetched_events.extend((created, updated))
        except asyncio.TimeoutError:
            self._prefetched_events.clear()
            await self._close_transport()
            self._profile = qwen_capability_profile(health_status="unavailable")
            raise ProviderConnectionError("provider_connect_timeout", retryable=True) from None
        except SafeProviderError:
            self._prefetched_events.clear()
            await self._close_transport()
            self._profile = qwen_capability_profile(health_status="unavailable")
            raise
        except Exception:
            # Never include provider exception strings: aiohttp request objects
            # may contain the endpoint or headers.
            self._prefetched_events.clear()
            await self._close_transport()
            self._profile = qwen_capability_profile(health_status="unavailable")
            raise ProviderConnectionError("provider_connect_failed", retryable=True) from None
        self._connected = True
        self._profile = qwen_capability_profile(health_status="ready")

    async def send_audio(self, pcm16le: bytes) -> None:
        websocket = self._require_websocket()
        if not pcm16le or len(pcm16le) % 2:
            raise SafeProviderError("invalid_pcm_frame")
        encoded = base64.b64encode(pcm16le).decode("ascii")
        try:
            await websocket.send_json(
                {"type": "input_audio_buffer.append", "audio": encoded}
            )
        except Exception:
            raise ProviderDisconnected("provider_send_failed", retryable=True) from None

    async def recv_event(self) -> NormalizedProviderEvent:
        websocket = self._require_websocket()
        if self._prefetched_events:
            return self._prefetched_events.popleft()
        try:
            message = await asyncio.wait_for(
                websocket.receive(), timeout=self._receive_timeout_seconds
            )
        except asyncio.TimeoutError:
            self._profile = qwen_capability_profile(health_status="degraded")
            return NormalizedProviderEvent(
                type="provider.timeout",
                output_mode="degraded",
                error_code="provider_receive_timeout",
                terminal=True,
            )
        except Exception:
            return self._disconnected_event("provider_receive_failed")

        if message.type == aiohttp.WSMsgType.TEXT:
            try:
                payload = json.loads(message.data)
            except (TypeError, ValueError):
                return NormalizedProviderEvent(
                    type="provider.error",
                    output_mode="degraded",
                    error_code="malformed_provider_json",
                )
            event = normalize_qwen_event(
                payload, active_response_ref=self._active_response_ref
            )
            self._update_response_state(payload, event)
            return event
        if message.type in (
            aiohttp.WSMsgType.CLOSE,
            aiohttp.WSMsgType.CLOSED,
            aiohttp.WSMsgType.ERROR,
        ):
            return self._disconnected_event("provider_disconnected")
        return NormalizedProviderEvent(
            type="provider.ignored",
            output_mode=self.profile.output_mode,
            reason="non_text_provider_frame",
        )

    async def cancel_response(self) -> bool:
        if (
            self._active_response_id is None
            or self._cancel_sent_for == self._active_response_id
        ):
            return False
        websocket = self._require_websocket()
        try:
            # Official contract requires only the type. Sending this without an
            # active response returns invalid_request_error, hence the guard.
            await websocket.send_json({"type": "response.cancel"})
        except Exception:
            raise ProviderDisconnected("provider_cancel_failed", retryable=True) from None
        self._cancel_sent_for = self._active_response_id
        return True

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._connected = False
        self._active_response_id = None
        self._active_response_ref = None
        self._prefetched_events.clear()
        await self._close_transport()
        self._profile = qwen_capability_profile(health_status="closed")

    def _require_websocket(self) -> aiohttp.ClientWebSocketResponse:
        websocket = self._websocket
        if not self._connected or websocket is None or websocket.closed:
            raise ProviderDisconnected("provider_not_connected", retryable=False)
        return websocket

    async def _close_transport(self) -> None:
        websocket, self._websocket = self._websocket, None
        http_session, self._http_session = self._http_session, None
        if websocket is not None and not websocket.closed:
            try:
                await websocket.close()
            except Exception:
                pass
        if http_session is not None and not http_session.closed:
            try:
                await http_session.close()
            except Exception:
                pass

    async def _receive_handshake_event(
        self, expected_type: str
    ) -> NormalizedProviderEvent:
        """Receive one required handshake event without retaining raw payloads."""

        websocket = self._websocket
        if websocket is None or websocket.closed:
            raise ProviderConnectionError("provider_connect_failed", retryable=True)
        try:
            message = await websocket.receive()
        except Exception:
            raise ProviderConnectionError(
                "provider_connect_failed", retryable=True
            ) from None
        if message.type != aiohttp.WSMsgType.TEXT:
            raise ProviderConnectionError("provider_connect_failed", retryable=True)
        try:
            payload = json.loads(message.data)
        except (TypeError, ValueError):
            raise ProviderConnectionError("provider_connect_failed") from None

        event = normalize_qwen_event(payload)
        if event.type == "provider.error":
            raise ProviderConnectionError(
                event.error_code or "provider_connect_failed",
                retryable=not event.terminal,
            )
        if event.type != expected_type:
            raise ProviderConnectionError("provider_connect_failed")
        return event

    def _disconnected_event(self, code: str) -> NormalizedProviderEvent:
        self._connected = False
        self._active_response_id = None
        self._active_response_ref = None
        self._profile = qwen_capability_profile(health_status="unavailable")
        return NormalizedProviderEvent(
            type="provider.disconnected",
            output_mode="degraded",
            error_code=code,
            terminal=True,
        )

    def _update_response_state(
        self, payload: Any, event: NormalizedProviderEvent
    ) -> None:
        if not isinstance(payload, dict):
            return
        event_type = payload.get("type")
        if event_type == "response.created":
            response_id = _response_id(payload)
            if response_id:
                self._active_response_id = response_id
                self._active_response_ref = event.response_ref
                self._cancel_sent_for = None
        elif event_type == "response.done":
            self._active_response_id = None
            self._active_response_ref = None
            self._cancel_sent_for = None


def normalize_qwen_event(
    payload: Any, *, active_response_ref: str | None = None
) -> NormalizedProviderEvent:
    """Normalize one Qwen server event without retaining its raw payload."""

    if not isinstance(payload, dict) or not isinstance(payload.get("type"), str):
        return NormalizedProviderEvent(
            type="provider.error",
            output_mode="degraded",
            error_code="invalid_provider_event",
        )

    event_type = payload["type"]
    session_ref = _safe_ref(_session_id(payload), "session")
    response_ref = _safe_ref(_response_id(payload), "response") or active_response_ref

    if event_type == "session.created":
        return NormalizedProviderEvent(
            type="session.created",
            output_mode="real",
            session_ref=session_ref,
        )
    if event_type == "session.updated":
        return NormalizedProviderEvent(
            type="session.updated",
            output_mode="real",
            session_ref=session_ref,
        )
    if event_type == "input_audio_buffer.speech_started":
        return NormalizedProviderEvent(
            type="speech.started",
            output_mode="real",
        )
    if event_type == "input_audio_buffer.speech_stopped":
        return NormalizedProviderEvent(
            type="speech.stopped",
            output_mode="real",
            reason=_known_reason(payload.get("reason")),
        )

    if event_type in {
        "conversation.item.input_audio_transcription.delta",
        "input_audio_buffer.transcription.delta",
    }:
        return NormalizedProviderEvent(
            type="user.transcript.delta",
            output_mode="real",
            text=_safe_text(payload.get("text", payload.get("delta", ""))),
            stash=_safe_text(payload.get("stash", "")),
        )
    if event_type in {
        "conversation.item.input_audio_transcription.completed",
        "conversation.item.input_audio_transcription.done",
        "input_audio_buffer.transcription.completed",
    }:
        return NormalizedProviderEvent(
            type="user.transcript.final",
            output_mode="real",
            text=_safe_text(payload.get("transcript", payload.get("text", ""))),
        )
    if event_type == "response.created":
        return NormalizedProviderEvent(
            type="response.created",
            output_mode="real",
            response_ref=response_ref,
        )
    if event_type == "response.audio.delta":
        audio = _decode_provider_audio(payload.get("delta"))
        if audio is None:
            return NormalizedProviderEvent(
                type="provider.error",
                output_mode="degraded",
                response_ref=response_ref,
                error_code="invalid_provider_audio_delta",
            )
        return NormalizedProviderEvent(
            type="response.audio.delta",
            output_mode="real",
            response_ref=response_ref,
            audio=audio,
        )
    if event_type == "response.audio.done":
        return NormalizedProviderEvent(
            type="response.audio.done",
            output_mode="real",
            response_ref=response_ref,
        )
    if event_type == "response.audio_transcript.delta":
        return NormalizedProviderEvent(
            type="assistant.transcript.delta",
            output_mode="real",
            response_ref=response_ref,
            text=_safe_text(payload.get("delta", payload.get("text", ""))),
        )
    if event_type == "response.audio_transcript.done":
        return NormalizedProviderEvent(
            type="assistant.transcript.done",
            output_mode="real",
            response_ref=response_ref,
            text=_safe_text(payload.get("transcript", payload.get("text", ""))),
        )
    if event_type == "response.done":
        response = payload.get("response")
        response = response if isinstance(response, dict) else {}
        status = _safe_token(response.get("status"), fallback="unknown")
        reason = _response_reason(response)
        output_mode = "real" if status in {"completed", "cancelled"} else "degraded"
        return NormalizedProviderEvent(
            type="response.done",
            output_mode=output_mode,
            response_ref=response_ref,
            status=status,
            reason=reason,
        )
    if event_type == "error":
        error = payload.get("error")
        error = error if isinstance(error, dict) else {}
        category, terminal = _provider_error_category(error)
        return NormalizedProviderEvent(
            type="provider.error",
            output_mode="degraded",
            error_code=category,
            terminal=terminal,
        )

    return NormalizedProviderEvent(
        type="provider.ignored",
        output_mode="real",
        reason=_safe_token(event_type, fallback="unknown_event"),
    )


def _safe_token(value: Any, *, fallback: str) -> str:
    if not isinstance(value, str) or not value:
        return fallback
    return _SAFE_ERROR_TOKEN.sub("_", value)[:96] or fallback


def _safe_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value[:_MAX_TRANSCRIPT_CHARS]


def _safe_ref(value: str | None, prefix: str) -> str | None:
    if not value:
        return None
    digest = hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _session_id(payload: Mapping[str, Any]) -> str | None:
    session = payload.get("session")
    if isinstance(session, dict) and isinstance(session.get("id"), str):
        return session["id"]
    value = payload.get("session_id")
    return value if isinstance(value, str) else None


def _response_id(payload: Mapping[str, Any]) -> str | None:
    response = payload.get("response")
    if isinstance(response, dict) and isinstance(response.get("id"), str):
        return response["id"]
    value = payload.get("response_id")
    return value if isinstance(value, str) else None


def _response_reason(response: Mapping[str, Any]) -> str | None:
    details = response.get("status_details")
    if not isinstance(details, dict):
        return None
    reason = details.get("reason")
    if reason is None:
        error = details.get("error")
        if isinstance(error, dict):
            reason = error.get("type") or error.get("code")
    return _known_reason(reason) if reason is not None else None


def _known_reason(value: Any) -> str | None:
    """Map provider-controlled reason text to a fixed local vocabulary."""

    if not isinstance(value, str):
        return None
    known = {
        "turn_detected",
        "turn_invalid",
        "client_cancelled",
        "max_output_tokens",
        "content_filter",
    }
    return value if value in known else "provider_reason_other"


def _provider_error_category(error: Mapping[str, Any]) -> tuple[str, bool]:
    """Classify errors without forwarding raw provider code/message text."""

    error_type = error.get("type")
    error_code = error.get("code")
    tokens = {
        token.lower()
        for token in (error_type, error_code)
        if isinstance(token, str)
    }
    if "server_error" in tokens:
        return "provider_server_error", True
    if any(
        marker in token
        for token in tokens
        for marker in (
            "auth",
            "credential",
            "permission",
            "api_key",
            "unauthorized",
            "forbidden",
        )
    ):
        return "provider_authentication_failed", True
    if any("rate" in token and "limit" in token for token in tokens):
        return "provider_rate_limited", False
    if "invalid_request_error" in tokens:
        return "provider_invalid_request", False
    return "provider_error", False


def _decode_provider_audio(value: Any) -> bytes | None:
    if not isinstance(value, str) or len(value) > (_MAX_PROVIDER_AUDIO_BYTES * 2):
        return None
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None
    if not decoded or len(decoded) > _MAX_PROVIDER_AUDIO_BYTES or len(decoded) % 2:
        return None
    return decoded


__all__ = [
    "CredentialConfigurationError",
    "CredentialHandle",
    "DEFAULT_INSTRUCTIONS",
    "DEFAULT_VOICE",
    "MODEL_NAME",
    "NormalizedProviderEvent",
    "ProviderConnectionError",
    "ProviderDisconnected",
    "QwenRealtimeProvider",
    "RealtimeProviderSession",
    "SafeProviderError",
    "build_session_update",
    "normalize_qwen_event",
]
