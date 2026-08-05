"""Real Qwen Voice adapter for Slice 2 shadow and Slice 3A enforced control.

Provider wire normalization is reused from the previously validated
``qwen_audio_realtime_web`` spike.  Enforced mode adds a contained transport
only because the shared core intentionally discards the raw item IDs needed
for deletion acknowledgement.  Natural-language Voice output is never routing
evidence.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
from collections import deque
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Callable, Literal, Mapping, Protocol

import aiohttp

from experiments.qwen_audio_realtime_web.provider_adapter import (
    NormalizedProviderEvent,
    QwenRealtimeProvider,
    build_session_update,
    normalize_qwen_event,
)

from .capability_profile import (
    CapabilityProfile,
    HealthStatus,
    qwen_voice_capability_profile,
)
from .provider_context import CredentialHandle


_SAFE_ERROR_TOKEN = re.compile(r"[^A-Za-z0-9_.:-]+")
_MAX_VOICE_OUTPUT_ITEMS = 8
_MAX_VOICE_RESPONSE_LIFECYCLES = 16
_MAX_VOICE_INPUT_ITEMS = 64
_MAX_VOICE_PROVIDER_IDS_PER_GENERATION = 64
_MAX_VOICE_OUTPUT_ITEM_IDS_PER_GENERATION = (
    _MAX_VOICE_RESPONSE_LIFECYCLES * _MAX_VOICE_OUTPUT_ITEMS
)
_MAX_PREFETCHED_EVENTS = 32
_MAX_PROVIDER_REF_CHARS = 256


class VoiceProviderError(RuntimeError):
    """Low-information Voice transport failure safe for metadata/UI."""

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        self.code = _safe_error_code(code)
        self.retryable = retryable
        super().__init__(self.code)


CancelTerminalOutcome = Literal[
    "cancelled_on_time",
    "cancelled_after_watchdog",
    "completed_after_cancel",
    "failed_after_cancel",
    "missing_terminal",
]


@dataclass(slots=True)
class VoiceSuppressionCounters:
    suppressed_text_delta_count: int = 0
    suppressed_audio_frame_count: int = 0
    suppressed_audio_byte_count: int = 0
    cancel_request_count: int = 0
    cancel_terminal_count: int = 0
    cancel_terminal_timeout_count: int = 0
    unsafe_cancel_terminal_count: int = 0
    completed_after_cancel_count: int = 0
    failed_after_cancel_count: int = 0
    context_delete_count: int = 0
    context_delete_ack_count: int = 0
    context_delete_failure_count: int = 0
    context_rebuild_count: int = 0
    audio_send_failure_count: int = 0
    rebuild_coalesced_count: int = 0
    rebuild_audio_drop_count: int = 0
    rebuild_audio_drop_byte_count: int = 0
    ingress_generation_drop_count: int = 0
    receiver_generation_discard_count: int = 0
    terminal_receiver_exit_count: int = 0
    provider_item_id_reuse_count: int = 0
    provider_item_id_horizon_count: int = 0
    late_event_discard_count: int = 0
    correlation_failure_count: int = 0
    quarantine_response_count: int = 0

    def to_metadata(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _CoreCleanupResult:
    confirmed: bool
    deleted_count: int = 0


@dataclass(slots=True)
class _RawResponseContext:
    raw_response_id: str = field(repr=False)
    safe_response_ref: str
    output_item_ids: set[str] = field(default_factory=set, repr=False)
    inventory_confirmed: bool = False
    overflowed: bool = False
    correlation_invalid: bool = False
    terminal_status: str | None = None


class _CorrelatedProviderEvent:
    """Transient core event with provider refs confined to this module.

    Tests may script this private shape at the provider-core boundary.  Its
    repr and metadata projection never expose the raw provider item ref,
    transcript, stash, or audio bytes.
    """

    __slots__ = (
        "normalized",
        "provider_item_ref",
        "audio_start_ms",
        "audio_end_ms",
        "session_generation",
        "provider_correlation_error",
    )

    def __init__(
        self,
        *,
        normalized: NormalizedProviderEvent,
        provider_item_ref: str | None = None,
        audio_start_ms: int | None = None,
        audio_end_ms: int | None = None,
        session_generation: int | None = None,
        provider_correlation_error: str | None = None,
    ) -> None:
        self.normalized = normalized
        self.provider_item_ref = provider_item_ref
        self.audio_start_ms = audio_start_ms
        self.audio_end_ms = audio_end_ms
        self.session_generation = session_generation
        self.provider_correlation_error = provider_correlation_error

    def __getattr__(self, name: str) -> Any:
        return getattr(self.normalized, name)

    def __repr__(self) -> str:
        return (
            "_CorrelatedProviderEvent("
            f"type={self.normalized.type!r}, "
            f"output_mode={self.normalized.output_mode!r}, "
            f"has_provider_item_ref={self.provider_item_ref is not None!r}, "
            "provider_correlation_error="
            f"{_safe_error_code(self.provider_correlation_error)!r})"
        )


@dataclass(slots=True)
class _InputItemContext:
    raw_item_id: str = field(repr=False)
    provider_item_id: str
    turn_ref: str
    utterance_ref: str
    audio_span_ref: str
    session_ref: str
    session_generation: int
    audio_start_ms: int
    audio_end_ms: int | None = None
    stopped: bool = False
    final_seen: bool = False
    invalid: bool = False
    interrupted: bool = False


@dataclass(slots=True)
class _SuppressedResponseLifecycle:
    response_id: str
    provider_item_id: str
    terminal_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    output_eligible: bool = False
    cancel_requested: bool = False
    terminal_seen: bool = False
    terminal_status: str | None = None
    cancel_terminal_success: bool = False
    cancel_terminal_outcome: CancelTerminalOutcome | None = None
    watchdog_expired: bool = False
    cleanup_confirmed: bool = False


class _EnforcedQwenVoiceCore:
    """Qwen Voice transport retaining correlation only for safe cleanup.

    The shared Slice 0 core intentionally discards raw output item IDs.  Slice
    3A needs those IDs solely to confirm deletion, so this contained transport
    keeps them in memory and never projects them beyond this module.
    """

    def __init__(
        self,
        credentials: CredentialHandle,
        *,
        voice: str,
        instructions: str | None,
        connect_timeout_seconds: float,
        receive_timeout_seconds: float,
        context_delete_timeout_seconds: float = 2.0,
        max_provider_message_bytes: int = 1_048_576,
    ) -> None:
        if min(
            connect_timeout_seconds,
            receive_timeout_seconds,
            context_delete_timeout_seconds,
        ) <= 0:
            raise ValueError("voice_timeouts_must_be_positive")
        self._credentials = credentials
        update_kwargs: dict[str, str] = {"voice": voice}
        if instructions is not None:
            update_kwargs["instructions"] = instructions
        self._session_update = build_session_update(**update_kwargs)
        self._connect_timeout_seconds = connect_timeout_seconds
        # Retained for constructor compatibility and future transport-level
        # liveness policy.  It is deliberately not a business-idle deadline:
        # Qwen documents continuous audio append and no server ``timeout``
        # event.  WebSocket heartbeat/close drives transport liveness instead.
        self._receive_timeout_seconds = receive_timeout_seconds
        self._context_delete_timeout_seconds = context_delete_timeout_seconds
        self._max_provider_message_bytes = max_provider_message_bytes
        self._http_session: aiohttp.ClientSession | None = None
        self._websocket: aiohttp.ClientWebSocketResponse | None = None
        self._prefetched: deque[
            NormalizedProviderEvent | _CorrelatedProviderEvent
        ] = deque(
            maxlen=_MAX_PREFETCHED_EVENTS
        )
        self._responses: dict[str, _RawResponseContext] = {}
        # Provider IDs are unique only within one physical Voice generation.
        # They remain remembered for that whole generation; reaching the
        # bounded horizon fails closed so the owner can rotate Voice rather
        # than evicting an ID and risking a late rebind.
        self._seen_raw_response_ids: set[str] = set()
        self._output_item_owners: dict[str, str] = {}
        self._delete_ack_waiters: dict[str, asyncio.Future[None]] = {}
        self._cleanup_lock = asyncio.Lock()
        self._active_raw_response_id: str | None = None
        self._active_response_ref: str | None = None
        self._cancel_sent_for: str | None = None
        self._connected = False
        self._closed = False

    @property
    def response_active(self) -> bool:
        return self._active_raw_response_id is not None

    async def connect(self) -> None:
        if self._connected:
            return
        if self._closed:
            raise VoiceProviderError("voice_core_closed")
        timeout = aiohttp.ClientTimeout(
            total=None,
            sock_connect=self._connect_timeout_seconds,
            sock_read=None,
        )
        self._http_session = aiohttp.ClientSession(timeout=timeout)
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
            created = await self._receive_handshake("session.created")
            await self._websocket.send_json(self._session_update)
            updated = await self._receive_handshake("session.updated")
            self._prefetched.extend((created, updated))
        except asyncio.TimeoutError:
            await self._close_transport()
            raise VoiceProviderError("voice_connect_timeout", retryable=True) from None
        except VoiceProviderError:
            await self._close_transport()
            raise
        except Exception:
            await self._close_transport()
            raise VoiceProviderError("voice_connect_failed", retryable=True) from None
        self._connected = True

    async def send_audio(self, pcm16le: bytes) -> None:
        websocket = self._require_websocket()
        if not pcm16le or len(pcm16le) % 2:
            raise VoiceProviderError("invalid_pcm_frame")
        try:
            await websocket.send_json(
                {
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(pcm16le).decode("ascii"),
                }
            )
        except Exception:
            raise VoiceProviderError("voice_send_failed", retryable=True) from None

    async def recv_event(self) -> NormalizedProviderEvent | _CorrelatedProviderEvent:
        if self._prefetched:
            return self._prefetched.popleft()
        try:
            # Wait directly so ordinary application idle remains healthy.
            # Cancellation propagates into aiohttp's single receive call; no
            # detached receiver task survives session close or caller timeout.
            payload = await self._receive_payload()
        except asyncio.CancelledError:
            raise
        except VoiceProviderError as error:
            self._connected = False
            return NormalizedProviderEvent(
                type="provider.disconnected",
                output_mode="degraded",
                error_code=error.code,
                terminal=True,
            )
        return self._normalize_and_track(payload)

    async def cancel_response(self) -> bool:
        raw_response_id = self._active_raw_response_id
        if raw_response_id is None or self._cancel_sent_for == raw_response_id:
            return False
        websocket = self._require_websocket()
        try:
            await websocket.send_json({"type": "response.cancel"})
        except Exception:
            raise VoiceProviderError("voice_cancel_failed", retryable=True) from None
        self._cancel_sent_for = raw_response_id
        return True

    async def delete_response_items(self, response_ref: str) -> _CoreCleanupResult:
        async with self._cleanup_lock:
            context = self._responses.get(response_ref)
            if (
                context is None
                or not context.inventory_confirmed
                or context.overflowed
                or context.correlation_invalid
            ):
                return _CoreCleanupResult(confirmed=False)
            item_ids = set(context.output_item_ids)
            if not item_ids:
                self._responses.pop(response_ref, None)
                return _CoreCleanupResult(confirmed=True)
            websocket = self._require_websocket()
            loop = asyncio.get_running_loop()
            waiters = {item_id: loop.create_future() for item_id in item_ids}
            if any(item_id in self._delete_ack_waiters for item_id in item_ids):
                context.correlation_invalid = True
                return _CoreCleanupResult(confirmed=False)
            self._delete_ack_waiters.update(waiters)
            try:
                for item_id in sorted(item_ids):
                    await websocket.send_json(
                        {"type": "conversation.item.delete", "item_id": item_id}
                    )
                await asyncio.wait_for(
                    asyncio.gather(*waiters.values()),
                    timeout=self._context_delete_timeout_seconds,
                )
                if context.correlation_invalid or context.overflowed:
                    return _CoreCleanupResult(confirmed=False)
            except Exception:
                return _CoreCleanupResult(confirmed=False)
            finally:
                for item_id, waiter in waiters.items():
                    if self._delete_ack_waiters.get(item_id) is waiter:
                        self._delete_ack_waiters.pop(item_id, None)
                    if not waiter.done():
                        waiter.cancel()
            self._responses.pop(response_ref, None)
            return _CoreCleanupResult(
                confirmed=True, deleted_count=len(item_ids)
            )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._connected = False
        self._responses.clear()
        self._seen_raw_response_ids.clear()
        self._output_item_owners.clear()
        for waiter in self._delete_ack_waiters.values():
            if not waiter.done():
                waiter.cancel()
        self._delete_ack_waiters.clear()
        self._prefetched.clear()
        self._active_raw_response_id = None
        self._active_response_ref = None
        self._cancel_sent_for = None
        await self._close_transport()

    async def _receive_handshake(self, expected_type: str) -> NormalizedProviderEvent:
        payload = await asyncio.wait_for(
            self._receive_payload(allow_connecting=True),
            timeout=self._connect_timeout_seconds,
        )
        event = normalize_qwen_event(payload)
        if event.type != expected_type:
            raise VoiceProviderError("voice_handshake_unexpected_event")
        return event

    async def _receive_payload(
        self, *, allow_connecting: bool = False
    ) -> Mapping[str, Any]:
        websocket = self._require_websocket(allow_connecting=allow_connecting)
        try:
            message = await websocket.receive()
        except Exception:
            raise VoiceProviderError("voice_receive_failed", retryable=True) from None
        if message.type != aiohttp.WSMsgType.TEXT:
            raise VoiceProviderError("voice_provider_disconnected", retryable=True)
        try:
            payload = json.loads(message.data)
        except (TypeError, ValueError, RecursionError):
            raise VoiceProviderError("voice_provider_json_malformed") from None
        if not isinstance(payload, Mapping) or not isinstance(payload.get("type"), str):
            raise VoiceProviderError("voice_provider_event_invalid")
        return payload

    def _normalize_and_track(
        self, payload: Mapping[str, Any]
    ) -> NormalizedProviderEvent | _CorrelatedProviderEvent:
        event = normalize_qwen_event(
            payload, active_response_ref=self._active_response_ref
        )
        event_type = payload.get("type")
        if event_type == "conversation.item.deleted":
            item_id = payload.get("item_id")
            waiter = (
                self._delete_ack_waiters.get(item_id)
                if _valid_provider_ref(item_id)
                else None
            )
            if waiter is not None and not waiter.done():
                waiter.set_result(None)
        explicit_raw_response_id = self._explicit_raw_response_id(payload)
        if (
            isinstance(event_type, str)
            and event_type.startswith("response.")
            and event_type != "response.created"
            and explicit_raw_response_id is None
        ):
            # Active-response fallback is adequate for Slice 2 presentation,
            # but insufficient to prove Slice 3A cancel/delete correlation.
            event = replace(
                event,
                output_mode="degraded",
                response_ref=None,
                error_code="voice_response_correlation_invalid",
            )
            active_context = self._context_for_raw_response(
                self._active_raw_response_id
            )
            if active_context is not None:
                active_context.correlation_invalid = True
        if event_type == "response.created":
            response = payload.get("response")
            raw_id = response.get("id") if isinstance(response, Mapping) else None
            if _valid_provider_ref(raw_id) and event.response_ref is not None:
                if raw_id in self._seen_raw_response_ids:
                    return self._correlated_input_event(
                        payload,
                        replace(
                            event,
                            output_mode="degraded",
                            response_ref=None,
                            error_code="voice_response_id_reused",
                        ),
                    )
                if (
                    len(self._seen_raw_response_ids)
                    >= _MAX_VOICE_PROVIDER_IDS_PER_GENERATION
                ):
                    return self._correlated_input_event(
                        payload,
                        replace(
                            event,
                            output_mode="degraded",
                            response_ref=None,
                            error_code="voice_response_id_horizon_reached",
                        ),
                    )
                if len(self._responses) >= _MAX_VOICE_RESPONSE_LIFECYCLES:
                    return self._correlated_input_event(
                        payload,
                        replace(
                            event,
                            output_mode="degraded",
                            response_ref=None,
                            error_code="voice_response_lifecycle_limit_exceeded",
                        ),
                    )
                existing = self._context_for_raw_response(raw_id)
                active_context = self._context_for_raw_response(
                    self._active_raw_response_id
                )
                if (
                    existing is not None
                    or event.response_ref in self._responses
                    or (
                        active_context is not None
                        and active_context.raw_response_id != raw_id
                    )
                ):
                    if existing is not None:
                        existing.correlation_invalid = True
                    if active_context is not None:
                        active_context.correlation_invalid = True
                    event = replace(
                        event,
                        output_mode="degraded",
                        response_ref=None,
                        error_code="voice_response_overlap_or_duplicate",
                    )
                    return self._correlated_input_event(payload, event)
                self._active_raw_response_id = raw_id
                self._active_response_ref = event.response_ref
                self._cancel_sent_for = None
                self._seen_raw_response_ids.add(str(raw_id))
                self._responses[event.response_ref] = _RawResponseContext(
                    raw_response_id=raw_id,
                    safe_response_ref=event.response_ref,
                )
            else:
                event = replace(
                    event,
                    output_mode="degraded",
                    response_ref=None,
                    error_code="voice_response_correlation_invalid",
                )
        self._track_output_items(payload)
        if event_type == "response.done":
            context = self._context_for_raw_response(explicit_raw_response_id)
            if (
                context is None
                or context.correlation_invalid
                or context.overflowed
            ):
                event = replace(
                    event,
                    output_mode="degraded",
                    response_ref=None,
                    error_code="voice_terminal_correlation_invalid",
                )
            elif explicit_raw_response_id == self._active_raw_response_id:
                self._active_raw_response_id = None
                self._active_response_ref = None
                self._cancel_sent_for = None
        return self._correlated_input_event(payload, event)

    def _track_output_items(self, payload: Mapping[str, Any]) -> None:
        raw_response_id = self._explicit_raw_response_id(payload)
        context = self._context_for_raw_response(raw_response_id)
        event_type = payload.get("type")
        if event_type in {"response.output_item.added", "response.output_item.done"}:
            item = payload.get("item")
            if context is not None and isinstance(item, Mapping):
                if context.terminal_status is not None:
                    context.correlation_invalid = True
                self._remember_output_item(context, item)
            elif context is not None:
                context.correlation_invalid = True
            else:
                self._invalidate_active_response_context()
        elif event_type == "response.done" and context is not None:
            response = payload.get("response")
            status = response.get("status") if isinstance(response, Mapping) else None
            context.terminal_status = (
                status if isinstance(status, str) and status else "unknown"
            )
            output = response.get("output") if isinstance(response, Mapping) else None
            if isinstance(output, list):
                for item in output:
                    if isinstance(item, Mapping):
                        self._remember_output_item(context, item)
                    else:
                        context.correlation_invalid = True
                context.inventory_confirmed = True
            elif output is not None:
                context.correlation_invalid = True
            elif context.terminal_status == "cancelled":
                # The documented cancelled terminal may omit ``output``.  The
                # single ordered receiver has already observed every preceding
                # response.output_item.added event, so cancelled closes the
                # bounded inventory.  Other statuses without an output array
                # remain incomplete and force a Voice rebuild.
                context.inventory_confirmed = True
        elif isinstance(event_type, str) and event_type.startswith("response."):
            if event_type != "response.created" and context is None:
                self._invalidate_active_response_context()

    def _remember_output_item(
        self, context: _RawResponseContext, item: Mapping[str, Any]
    ) -> None:
        item_id = item.get("id")
        if not _valid_provider_ref(item_id):
            context.correlation_invalid = True
            return
        owner = self._output_item_owners.get(item_id)
        if owner is not None and owner != context.safe_response_ref:
            context.correlation_invalid = True
            return
        if item_id in context.output_item_ids:
            return
        if (
            owner is None
            and len(self._output_item_owners)
            >= _MAX_VOICE_OUTPUT_ITEM_IDS_PER_GENERATION
        ):
            context.overflowed = True
            return
        if len(context.output_item_ids) >= _MAX_VOICE_OUTPUT_ITEMS:
            context.overflowed = True
            return
        self._output_item_owners[item_id] = context.safe_response_ref
        context.output_item_ids.add(item_id)

    @staticmethod
    def _explicit_raw_response_id(payload: Mapping[str, Any]) -> str | None:
        response = payload.get("response")
        if isinstance(response, Mapping) and _valid_provider_ref(response.get("id")):
            return str(response["id"])
        response_id = payload.get("response_id")
        if _valid_provider_ref(response_id):
            return response_id
        return None

    def _invalidate_active_response_context(self) -> None:
        context = self._context_for_raw_response(self._active_raw_response_id)
        if context is not None:
            context.correlation_invalid = True

    @staticmethod
    def _correlated_input_event(
        payload: Mapping[str, Any], event: NormalizedProviderEvent
    ) -> NormalizedProviderEvent | _CorrelatedProviderEvent:
        if event.type not in {
            "speech.started",
            "speech.stopped",
            "user.transcript.delta",
            "user.transcript.final",
        }:
            return event
        raw_item_id = payload.get("item_id")
        provider_item_ref = str(raw_item_id) if _valid_provider_ref(raw_item_id) else None
        audio_start_ms = _safe_audio_offset(payload.get("audio_start_ms"))
        audio_end_ms = _safe_audio_offset(payload.get("audio_end_ms"))
        error_code = None
        if provider_item_ref is None:
            error_code = "voice_input_item_missing"
        elif event.type == "speech.started" and audio_start_ms is None:
            error_code = "voice_audio_start_missing"
        elif event.type == "speech.stopped" and audio_end_ms is None:
            error_code = "voice_audio_end_missing"
        return _CorrelatedProviderEvent(
            normalized=event,
            provider_item_ref=provider_item_ref,
            audio_start_ms=audio_start_ms,
            audio_end_ms=audio_end_ms,
            provider_correlation_error=error_code,
        )

    def _context_for_raw_response(
        self, raw_response_id: str | None
    ) -> _RawResponseContext | None:
        if raw_response_id is None:
            return None
        for context in self._responses.values():
            if context.raw_response_id == raw_response_id:
                return context
        return None

    def _require_websocket(
        self, *, allow_connecting: bool = False
    ) -> aiohttp.ClientWebSocketResponse:
        websocket = self._websocket
        if (
            websocket is None
            or websocket.closed
            or (not allow_connecting and not self._connected)
        ):
            raise VoiceProviderError("voice_provider_not_connected")
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


class _VoiceProviderCore(Protocol):
    @property
    def response_active(self) -> bool: ...

    async def connect(self) -> None: ...

    async def send_audio(self, pcm16le: bytes) -> None: ...

    async def recv_event(self) -> NormalizedProviderEvent | _CorrelatedProviderEvent: ...

    async def cancel_response(self) -> bool: ...

    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class VoiceProviderEvent:
    """Provider-neutral event consumed by the Slice 2 coordinator.

    Transcript text and PCM are transient live-session values.  The safe
    metadata projection intentionally omits both, along with provider payloads.
    ``provider_item_id`` and ``turn_ref`` are local opaque correlation refs;
    provider-supplied IDs are never trusted as application bindings.
    """

    type: str
    output_mode: str
    response_id: str | None = None
    provider_item_id: str | None = None
    turn_ref: str | None = None
    utterance_ref: str | None = None
    audio_span_ref: str | None = None
    session_ref: str | None = None
    session_generation: int | None = None
    audio_start_ms: int | None = None
    audio_end_ms: int | None = None
    text: str | None = field(default=None, repr=False)
    stash: str | None = field(default=None, repr=False)
    audio: bytes | None = field(default=None, repr=False)
    status: str | None = None
    reason: str | None = None
    error_code: str | None = None
    terminal: bool = False
    interrupt_only: bool = False
    suppressed: bool = False
    quarantined: bool = False
    correlation_valid: bool = True

    @property
    def byte_length(self) -> int:
        return len(self.audio) if self.audio is not None else 0

    def to_safe_metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "type": self.type,
            "output_mode": self.output_mode,
            "audio_bytes": self.byte_length,
            "terminal": self.terminal,
            "interrupt_only": self.interrupt_only,
            "suppressed": self.suppressed,
            "quarantined": self.quarantined,
            "correlation_valid": self.correlation_valid,
        }
        for key in (
            "response_id",
            "provider_item_id",
            "turn_ref",
            "utterance_ref",
            "audio_span_ref",
            "session_ref",
            "session_generation",
            "audio_start_ms",
            "audio_end_ms",
            "status",
            "reason",
            "error_code",
        ):
            value = getattr(self, key)
            if value is not None:
                metadata[key] = value
        return metadata

    # The Slice 1 fake uses this spelling.  Keep both projections identical so
    # coordinator code never needs provider-specific metadata handling.
    safe_metadata = to_safe_metadata


class QwenVoiceAdapter:
    """One real smart-turn Qwen voice connection.

    Slice 2 shadow mode preserves the validated presentation behavior.  Slice
    3A enforced mode uses a separate transport that quarantines automatic
    assistant output, cancels it, requires a matching terminal, deletes only
    correlated output items, and otherwise rebuilds Voice without replaying
    microphone PCM.
    """

    def __init__(
        self,
        credentials: CredentialHandle | None = None,
        *,
        provider_core: _VoiceProviderCore | None = None,
        voice: str = "longanqian",
        instructions: str | None = None,
        connect_timeout_seconds: float = 10.0,
        receive_timeout_seconds: float = 90.0,
        context_delete_timeout_seconds: float = 2.0,
        cancel_terminal_timeout_seconds: float = 2.0,
        rebuild_timeout_seconds: float | None = None,
        enforced_output_suppression: bool = False,
        provider_core_factory: Callable[[], _VoiceProviderCore] | None = None,
    ) -> None:
        if cancel_terminal_timeout_seconds <= 0:
            raise ValueError("cancel_terminal_timeout_must_be_positive")
        resolved_rebuild_timeout = (
            max(1.0, connect_timeout_seconds * 3.0)
            if rebuild_timeout_seconds is None
            else float(rebuild_timeout_seconds)
        )
        if resolved_rebuild_timeout <= 0:
            raise ValueError("rebuild_timeout_must_be_positive")
        self._enforced_output_suppression = bool(enforced_output_suppression)
        self._cancel_terminal_timeout_seconds = float(
            cancel_terminal_timeout_seconds
        )
        self._rebuild_timeout_seconds = resolved_rebuild_timeout
        self._rebuild_lock = asyncio.Lock()
        self._receive_lock = asyncio.Lock()
        self._rebuild_attempted_generation: int | None = None
        self._provider_core_factory = provider_core_factory
        if provider_core is None:
            if credentials is None:
                raise ValueError("credentials_required")
            kwargs: dict[str, Any] = {
                "voice": voice,
                "connect_timeout_seconds": connect_timeout_seconds,
                "receive_timeout_seconds": receive_timeout_seconds,
            }
            if instructions is not None:
                kwargs["instructions"] = instructions
            if self._enforced_output_suppression:
                def build_enforced_core() -> _VoiceProviderCore:
                    return _EnforcedQwenVoiceCore(
                        credentials,
                        voice=voice,
                        instructions=instructions,
                        connect_timeout_seconds=connect_timeout_seconds,
                        receive_timeout_seconds=receive_timeout_seconds,
                        context_delete_timeout_seconds=(
                            context_delete_timeout_seconds
                        ),
                    )

                self._provider_core_factory = build_enforced_core
                provider_core = build_enforced_core()
            else:
                # CredentialHandle deliberately implements only the two
                # provider-bound methods used by the already-tested core.
                provider_core = QwenRealtimeProvider(  # type: ignore[arg-type]
                    credentials, **kwargs
                )
        self._core = provider_core
        self._profile = self._make_profile()
        self._connected = False
        self._closed = False
        self._context_tainted = False
        self._rebuilding = False
        self._session_generation = 0
        self._session_ref: str | None = None
        self._turn_counter = 0
        self._response_item_counter = 0
        self._current_turn_ref: str | None = None
        self._current_input_item_ref: str | None = None
        self._active_raw_input_item_id: str | None = None
        self._latest_audio_end_ms: int | None = None
        self._input_item_contexts: dict[str, _InputItemContext] = {}
        self._input_item_order: deque[str] = deque()
        self._response_item_refs: dict[str, str] = {}
        self._active_suppressed_response_id: str | None = None
        self._suppressed_responses: dict[str, _SuppressedResponseLifecycle] = {}
        self._seen_response_ids: set[str] = set()
        self._stale_response_ids: set[str] = set()
        self._terminal_generation: int | None = None
        self._counters = VoiceSuppressionCounters()
        self._cancel_terminal_outcome: CancelTerminalOutcome | None = None
        self._audio_send_failure_generation: int | None = None
        self.sent_audio_frames = 0
        self.sent_audio_bytes = 0

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        safe_base_url: str | None = None,
        explicit_workspace_id: str | None = None,
        verified_workspace_id: str | None = None,
        **kwargs: Any,
    ) -> "QwenVoiceAdapter":
        credentials = CredentialHandle.resolve(
            environment,
            safe_base_url=safe_base_url,
            explicit_workspace_id=explicit_workspace_id,
            verified_workspace_id=verified_workspace_id,
        )
        return cls(credentials, **kwargs)

    @property
    def profile(self) -> CapabilityProfile:
        return self._profile

    @property
    def counters(self) -> VoiceSuppressionCounters:
        return self._counters

    @property
    def cancel_count(self) -> int:
        """Compatibility alias used by the Slice 2 coordinator/tests."""

        return self._counters.cancel_request_count

    @property
    def context_tainted(self) -> bool:
        return self._context_tainted

    @property
    def rebuilding(self) -> bool:
        return self._rebuilding

    @property
    def cancel_terminal_outcome(self) -> CancelTerminalOutcome | None:
        """Last bounded cancel outcome, without provider payload or IDs."""

        return self._cancel_terminal_outcome

    @property
    def ingress_availability_code(self) -> str:
        """Typed current ingress availability for coalesced recovery handling."""

        if self._closed:
            return "voice_adapter_closed"
        if self._rebuilding:
            return "voice_context_rebuilding"
        if self._context_tainted:
            return "voice_context_tainted"
        if not self._connected:
            return "voice_provider_not_connected"
        return "available"

    @property
    def session_generation(self) -> int:
        """Local generation only; never a provider session identifier."""

        return self._session_generation

    @property
    def ingress_generation(self) -> int:
        """Generation that must be bound to newly accepted microphone PCM."""

        return self._session_generation

    @property
    def session_state(self) -> str:
        if self._closed:
            return "closed"
        if self._context_tainted:
            return "degraded"
        return "connected" if self._connected else "disconnected"

    @property
    def enforced_output_suppression(self) -> bool:
        return self._enforced_output_suppression

    @property
    def response_active(self) -> bool:
        if self._enforced_output_suppression:
            response_id = self._active_suppressed_response_id
            lifecycle = self._suppressed_responses.get(response_id or "")
            return lifecycle is not None and not lifecycle.terminal_seen
        return bool(self._core.response_active)

    @property
    def active_response_id(self) -> str | None:
        if self._enforced_output_suppression:
            return (
                self._active_suppressed_response_id
                if self.response_active
                else None
            )
        if not self.response_active or not self._response_item_refs:
            return None
        # Dict insertion order preserves the newest local response ref.
        return next(reversed(self._response_item_refs))

    async def connect(self) -> None:
        if self._connected:
            return
        if self._closed:
            raise RuntimeError("qwen_voice_adapter_closed")
        if self._session_generation > 0 and self._context_tainted:
            raise VoiceProviderError("voice_context_requires_rebuild")
        try:
            await self._core.connect()
        except Exception:
            self._profile = self._make_profile(health_status="unavailable")
            raise
        self._connected = True
        self._context_tainted = False
        self._session_generation += 1
        self._session_ref = f"voice-session-{self._session_generation:04d}"
        self._profile = self._make_profile(health_status="ready")

    async def send_audio(
        self,
        pcm16le: bytes,
        *,
        ingress_generation: int | None = None,
    ) -> None:
        """Send one generation-bound frame without replay or cross-core swap.

        Enforced mode requires the coordinator to bind the generation when it
        accepts the frame.  The same binding is checked before and after the
        provider await so a frame can never be dequeued onto a replacement
        core after a rebuild fence advances.
        """

        if self._enforced_output_suppression and ingress_generation is None:
            self._record_ingress_drop(len(pcm16le), rebuilding=self._rebuilding)
            raise VoiceProviderError("voice_ingress_generation_required")
        if ingress_generation is None:
            ingress_generation = self._session_generation
        if (
            isinstance(ingress_generation, bool)
            or not isinstance(ingress_generation, int)
            or ingress_generation <= 0
        ):
            self._record_ingress_drop(len(pcm16le), rebuilding=self._rebuilding)
            raise VoiceProviderError("voice_ingress_generation_invalid")

        generation = self._session_generation
        if ingress_generation != generation:
            self._record_ingress_drop(len(pcm16le), rebuilding=self._rebuilding)
            raise VoiceProviderError("voice_ingress_generation_stale")
        if self._closed:
            self._record_ingress_drop(len(pcm16le), rebuilding=self._rebuilding)
            raise VoiceProviderError("voice_adapter_closed")
        if self._rebuilding:
            self._record_ingress_drop(len(pcm16le), rebuilding=True)
            raise VoiceProviderError("voice_context_rebuilding", retryable=True)
        if not self._connected:
            self._record_ingress_drop(len(pcm16le), rebuilding=False)
            raise VoiceProviderError("voice_provider_not_connected", retryable=True)
        if self._context_tainted:
            self._record_ingress_drop(len(pcm16le), rebuilding=False)
            raise VoiceProviderError("voice_context_tainted")

        core = self._core
        try:
            await core.send_audio(pcm16le)
        except asyncio.CancelledError:
            raise
        except Exception:
            if (
                core is self._core
                and generation == self._session_generation
                and ingress_generation == self._session_generation
                and not self._closed
                and not self._rebuilding
                and self._connected
            ):
                if self._audio_send_failure_generation != generation:
                    self._audio_send_failure_generation = generation
                    self._counters.audio_send_failure_count += 1
                    self._mark_context_tainted("voice_send_failed")
                raise VoiceProviderError(
                    "voice_send_failed",
                    retryable=True,
                ) from None
            self._record_ingress_drop(
                len(pcm16le),
                rebuilding=self._rebuilding,
            )
            raise VoiceProviderError("voice_ingress_generation_retired") from None
        if (
            core is not self._core
            or generation != self._session_generation
            or ingress_generation != self._session_generation
            or self._closed
            or self._rebuilding
            or not self._connected
            or self._context_tainted
        ):
            self._record_ingress_drop(len(pcm16le), rebuilding=self._rebuilding)
            raise VoiceProviderError("voice_ingress_generation_retired")
        self.sent_audio_frames += 1
        self.sent_audio_bytes += len(pcm16le)

    async def recv_event(
        self, *, receiver_generation: int | None = None
    ) -> VoiceProviderEvent:
        """Receive exactly one event for one explicit Voice generation.

        Enforced-mode lifecycle owners must start a fresh receiver with the
        new generation after rebuild.  Once a transport terminal is returned,
        another receive for that generation fails immediately without calling
        the disconnected provider core, preventing a terminal hot loop.
        """

        if self._enforced_output_suppression and receiver_generation is None:
            raise VoiceProviderError("voice_receiver_generation_required")
        if receiver_generation is None:
            receiver_generation = self._session_generation
        if (
            isinstance(receiver_generation, bool)
            or not isinstance(receiver_generation, int)
            or receiver_generation <= 0
        ):
            raise VoiceProviderError("voice_receiver_generation_invalid")

        async with self._receive_lock:
            if receiver_generation != self._session_generation:
                self._counters.receiver_generation_discard_count += 1
                raise VoiceProviderError("voice_receiver_generation_stale")
            if self._terminal_generation == receiver_generation:
                self._counters.terminal_receiver_exit_count += 1
                raise VoiceProviderError("voice_receiver_generation_terminal")
            if self._closed:
                raise VoiceProviderError("voice_adapter_closed")
            if self._rebuilding:
                raise VoiceProviderError("voice_receiver_generation_rebuilding")
            if not self._connected:
                raise VoiceProviderError("voice_provider_not_connected")

            core = self._core
            receiver_session_ref = self._session_ref
            if not isinstance(receiver_session_ref, str) or not receiver_session_ref:
                raise VoiceProviderError("voice_receiver_session_ref_unavailable")
            event = await core.recv_event()
            if (
                core is not self._core
                or receiver_generation != self._session_generation
                or (
                    isinstance(event, _CorrelatedProviderEvent)
                    and event.session_generation is not None
                    and event.session_generation != receiver_generation
                )
            ):
                self._counters.correlation_failure_count += 1
                self._counters.late_event_discard_count += 1
                self._counters.receiver_generation_discard_count += 1
                return VoiceProviderEvent(
                    type="provider.ignored",
                    output_mode="degraded",
                    session_ref=receiver_session_ref,
                    session_generation=receiver_generation,
                    error_code="voice_event_session_generation_stale",
                    terminal=True,
                    suppressed=True,
                    quarantined=True,
                    correlation_valid=False,
                )
            normalized = self._project_event(event)
            if self._enforced_output_suppression:
                normalized = await self._suppress_voice_output(normalized)
            if normalized.type in {"provider.disconnected", "provider.timeout"} or (
                normalized.type == "provider.error" and normalized.terminal
            ):
                self._terminal_generation = receiver_generation
                self._connected = False
                self._context_tainted = True
                self._profile = self._make_profile(health_status="disconnected")
            elif normalized.output_mode == "degraded":
                self._profile = self._make_profile(health_status="degraded")
            return normalized

    async def cancel_response(self) -> bool:
        response_id = self.active_response_id
        cancelled = await self._core.cancel_response()
        if cancelled:
            self._counters.cancel_request_count += 1
            if response_id is not None:
                state = self._suppressed_responses.get(response_id)
                if state is not None:
                    state.cancel_requested = True
                    state.output_eligible = False
                    state.cancel_terminal_outcome = None
                    self._cancel_terminal_outcome = None
        return cancelled

    def mark_response_output_ineligible(self, response_id: str) -> bool:
        """Permanently fence output without discarding cleanup ownership."""

        state = self._suppressed_responses.get(response_id)
        if state is None:
            return False
        state.output_eligible = False
        return True

    def invalidate_current_input(self, *, reason: str = "interrupt") -> bool:
        """Fence the current ASR item so a late final cannot bind a new turn."""

        del reason  # Provider-controlled or transcript-derived reasons are not retained.
        raw_item_id = self._active_raw_input_item_id
        context = self._input_item_contexts.get(raw_item_id or "")
        self._active_raw_input_item_id = None
        self._current_turn_ref = None
        self._current_input_item_ref = None
        if context is None:
            return False
        context.invalid = True
        context.interrupted = True
        return True

    async def wait_for_cancel_terminal(
        self,
        response_id: str,
        *,
        timeout_seconds: float | None = None,
    ) -> bool:
        """Await a matching cancelled terminal without blocking the event loop.

        The caller/session owner owns the wait task and therefore also owns
        cancellation during close.  Timeout only mutates adapter-local
        lifecycle state: it taints Voice and leaves cleanup/rebuild policy to
        the coordinator outside its serialized state lock.
        """

        timeout = (
            self._cancel_terminal_timeout_seconds
            if timeout_seconds is None
            else float(timeout_seconds)
        )
        if timeout <= 0:
            raise ValueError("cancel_terminal_timeout_must_be_positive")
        state = self._suppressed_responses.get(response_id)
        if state is None:
            return False
        if not state.terminal_seen:
            try:
                await asyncio.wait_for(state.terminal_event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                if not state.terminal_seen and not state.watchdog_expired:
                    state.watchdog_expired = True
                    state.output_eligible = False
                    state.cancel_terminal_outcome = "missing_terminal"
                    self._cancel_terminal_outcome = "missing_terminal"
                    self._counters.cancel_terminal_timeout_count += 1
                    self._mark_context_tainted("voice_cancel_terminal_timeout")
                return False
        return state.cancel_terminal_success

    async def finish_turn(self, _scenario: str | None = None) -> bool:
        """Smart-turn voice sessions do not use a manual audio commit."""

        return False

    def configure(self, **_kwargs: Any) -> None:
        """Real voice configuration is immutable after the first audio frame."""

    def event_processed(self) -> None:
        """Compatibility no-op for the fake provider's queue accounting API."""

    async def cleanup_suppressed_response(self, response_id: str) -> bool:
        """Delete one quarantined Voice output only after matching terminal.

        ``False`` never means a best-effort cleanup succeeded.  Missing
        correlation, missing terminal, missing provider deletion support, or
        an unconfirmed acknowledgement taints this Voice context and requires
        a fresh connection before more microphone audio is accepted.
        """

        if not self._enforced_output_suppression:
            return False
        state = self._suppressed_responses.get(response_id)
        if state is None or not state.terminal_seen:
            self._mark_context_tainted("voice_cleanup_without_terminal")
            self._counters.correlation_failure_count += 1
            return False
        cleanup_core = self._core
        cleanup_generation = self._session_generation
        cleanup_session_ref = self._session_ref
        cleanup_lifecycle = state
        cleanup = getattr(cleanup_core, "delete_response_items", None)
        if not callable(cleanup):
            self._record_delete_failure()
            return False
        try:
            result = await cleanup(response_id)
        except Exception:
            if not self._cleanup_authority_is_current(
                response_id=response_id,
                core=cleanup_core,
                session_generation=cleanup_generation,
                session_ref=cleanup_session_ref,
                lifecycle=cleanup_lifecycle,
            ):
                return False
            self._record_delete_failure()
            return False
        if not self._cleanup_authority_is_current(
            response_id=response_id,
            core=cleanup_core,
            session_generation=cleanup_generation,
            session_ref=cleanup_session_ref,
            lifecycle=cleanup_lifecycle,
        ):
            return False
        if isinstance(result, _CoreCleanupResult):
            confirmed = result.confirmed
            deleted_count = result.deleted_count
        elif isinstance(result, bool):
            confirmed = result
            deleted_count = 1 if result else 0
        else:
            confirmed = False
            deleted_count = 0
        if not confirmed:
            self._record_delete_failure()
            return False
        acknowledged = max(0, int(deleted_count))
        self._counters.context_delete_count += acknowledged
        self._counters.context_delete_ack_count += acknowledged
        state.cleanup_confirmed = True
        self._suppressed_responses.pop(response_id, None)
        self._response_item_refs.pop(response_id, None)
        if self._active_suppressed_response_id == response_id:
            self._active_suppressed_response_id = None
        self._stale_response_ids.add(response_id)
        # A completed/failed/unknown terminal after our cancellation is not a
        # successful cancel even when every known output item was deleted.
        # Return False so the session owner rebuilds the tainted Voice context.
        return not self._context_tainted

    def _cleanup_authority_is_current(
        self,
        *,
        response_id: str,
        core: _VoiceProviderCore,
        session_generation: int,
        session_ref: str | None,
        lifecycle: _SuppressedResponseLifecycle,
    ) -> bool:
        return (
            core is self._core
            and session_generation == self._session_generation
            and isinstance(session_ref, str)
            and bool(session_ref)
            and session_ref == self._session_ref
            and self._suppressed_responses.get(response_id) is lifecycle
        )

    async def rebuild_if_tainted(self) -> bool:
        """Perform at most one bounded Voice rebuild per tainted generation.

        Concurrent callers coalesce on ``_rebuild_lock``.  A caller waiting on
        another successful rebuild observes that success without creating a
        second core.  A failed attempt is not retried in a loop for the same
        generation; the owner can close the degraded session deterministically.
        Accepted microphone PCM is never replayed.
        """

        requested_generation = self._session_generation
        if self._rebuild_lock.locked():
            self._counters.rebuild_coalesced_count += 1
        async with self._rebuild_lock:
            if self._closed:
                return False
            if not self._context_tainted:
                return self._session_generation != requested_generation
            factory = self._provider_core_factory
            if factory is None:
                return False
            generation = self._session_generation
            if self._rebuild_attempted_generation == generation:
                return False
            self._rebuild_attempted_generation = generation
            return await self._rebuild_tainted_generation(
                generation=generation,
                factory=factory,
            )

    async def _rebuild_tainted_generation(
        self,
        *,
        generation: int,
        factory: Callable[[], _VoiceProviderCore],
    ) -> bool:
        if generation != self._session_generation:
            return False
        # Fence the old core and every accepted/queued PCM frame before the
        # first rebuild await.  A failed rebuild keeps this newer generation
        # disconnected, so old PCM and provider events never regain validity.
        self._rebuilding = True
        self._connected = False
        self._session_generation += 1
        fenced_generation = self._session_generation
        self._session_ref = f"voice-session-{fenced_generation:04d}"
        deadline = (
            asyncio.get_running_loop().time() + self._rebuild_timeout_seconds
        )
        old_core = self._core
        new_core: _VoiceProviderCore | None = None
        try:
            await asyncio.wait_for(
                old_core.close(),
                timeout=self._remaining_rebuild_seconds(deadline),
            )
            new_core = factory()
            await asyncio.wait_for(
                new_core.connect(),
                timeout=self._remaining_rebuild_seconds(deadline),
            )
            if (
                self._closed
                or self._session_generation != fenced_generation
                or not self._context_tainted
            ):
                await self._close_core_after_failed_rebuild(new_core)
                return False

            self._core = new_core
            self._connected = True
            self._context_tainted = False
            self._current_turn_ref = None
            self._current_input_item_ref = None
            self._active_raw_input_item_id = None
            self._latest_audio_end_ms = None
            self._input_item_contexts.clear()
            self._input_item_order.clear()
            self._response_item_refs.clear()
            self._active_suppressed_response_id = None
            for lifecycle in self._suppressed_responses.values():
                lifecycle.terminal_event.set()
            self._suppressed_responses.clear()
            self._stale_response_ids.clear()
            self._seen_response_ids.clear()
            self._counters.context_rebuild_count += 1
            self._profile = self._make_profile(health_status="ready")
            return True
        except asyncio.CancelledError:
            if new_core is not None:
                await self._close_core_after_failed_rebuild(new_core)
            raise
        except Exception:
            if new_core is not None:
                await self._close_core_after_failed_rebuild(new_core)
            self._connected = False
            self._rebuild_attempted_generation = self._session_generation
            self._profile = self._make_profile(
                health_status="closed" if self._closed else "unavailable"
            )
            return False
        finally:
            self._rebuilding = False

    def _remaining_rebuild_seconds(self, deadline: float) -> float:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError
        return remaining

    async def _close_core_after_failed_rebuild(
        self, core: _VoiceProviderCore
    ) -> None:
        try:
            await asyncio.wait_for(
                core.close(),
                timeout=min(1.0, self._rebuild_timeout_seconds),
            )
        except Exception:
            pass

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._connected = False
        self._rebuilding = False
        # Disconnect is also an ingress/provider-event fence.  This increment
        # happens before awaiting transport close so in-flight work is stale.
        self._session_generation += 1
        self._session_ref = None
        self._current_turn_ref = None
        self._current_input_item_ref = None
        self._active_raw_input_item_id = None
        self._latest_audio_end_ms = None
        self._input_item_contexts.clear()
        self._input_item_order.clear()
        self._response_item_refs.clear()
        self._active_suppressed_response_id = None
        for lifecycle in self._suppressed_responses.values():
            lifecycle.terminal_event.set()
        self._suppressed_responses.clear()
        self._seen_response_ids.clear()
        self._stale_response_ids.clear()
        await self._core.close()
        self._profile = self._make_profile(health_status="closed")

    def _project_event(
        self, event: NormalizedProviderEvent | _CorrelatedProviderEvent
    ) -> VoiceProviderEvent:
        event_type = event.type
        if self._enforced_output_suppression and event_type in {
            "speech.started",
            "speech.stopped",
            "user.transcript.delta",
            "user.transcript.final",
        }:
            return self._project_correlated_input_event(event)

        # Slice 2 shadow presentation retains its legacy local sequencing.  It
        # is non-authoritative and its capability profile explicitly labels
        # provider-item correlation unsupported/unverified.  Enforced routing
        # never enters this fallback.
        if event_type == "speech.started":
            self._turn_counter += 1
            self._current_turn_ref = f"voice-turn-{self._turn_counter:04d}"
            self._current_input_item_ref = self._local_provider_item_ref(
                "input", self._turn_counter
            )
        elif event_type.startswith("user.transcript"):
            self._ensure_turn_ref()

        response_id = event.response_ref
        provider_item_id: str | None = None
        if event_type.startswith("user.transcript"):
            provider_item_id = self._current_input_item_ref
        elif response_id is not None:
            provider_item_id = self._response_item_refs.get(response_id)
            if (
                provider_item_id is None
                and event_type == "response.created"
                and len(self._response_item_refs)
                < _MAX_VOICE_RESPONSE_LIFECYCLES
            ):
                self._response_item_counter += 1
                provider_item_id = self._local_provider_item_ref(
                    "output", self._response_item_counter
                )
                self._response_item_refs[response_id] = provider_item_id

        projected = VoiceProviderEvent(
            type=event_type,
            output_mode=event.output_mode,
            response_id=response_id,
            provider_item_id=provider_item_id,
            turn_ref=self._current_turn_ref,
            utterance_ref=(
                f"voice-utterance-{self._turn_counter:04d}"
                if self._current_turn_ref is not None
                else None
            ),
            audio_span_ref=(
                f"voice-audio-span-{self._turn_counter:04d}"
                if self._current_turn_ref is not None
                else None
            ),
            session_ref=self._session_ref,
            session_generation=self._session_generation,
            text=event.text,
            stash=event.stash,
            audio=event.audio,
            status=event.status,
            reason=event.reason,
            error_code=event.error_code,
            terminal=event.terminal,
        )
        if (
            not self._enforced_output_suppression
            and event_type == "response.done"
            and response_id is not None
        ):
            self._response_item_refs.pop(response_id, None)
        return projected

    def _project_correlated_input_event(
        self, event: NormalizedProviderEvent | _CorrelatedProviderEvent
    ) -> VoiceProviderEvent:
        event_type = event.type
        raw_item_id = getattr(event, "provider_item_ref", None)
        audio_start_ms = _safe_audio_offset(getattr(event, "audio_start_ms", None))
        audio_end_ms = _safe_audio_offset(getattr(event, "audio_end_ms", None))
        correlation_error = getattr(event, "provider_correlation_error", None)
        if not _valid_provider_ref(raw_item_id):
            self._invalidate_active_input_after_mismatch()
            return self._invalid_input_event(
                event,
                code=correlation_error or "voice_input_item_missing",
            )

        raw_item_id = str(raw_item_id)
        if event_type == "speech.started":
            if (
                audio_start_ms is None
                or (
                    self._latest_audio_end_ms is not None
                    and audio_start_ms < self._latest_audio_end_ms
                )
            ):
                return self._invalid_input_event(
                    event,
                    code=(
                        correlation_error
                        or (
                            "voice_audio_start_reordered"
                            if audio_start_ms is not None
                            else "voice_audio_start_missing"
                        )
                    ),
                )
            existing = self._input_item_contexts.get(raw_item_id)
            if existing is not None:
                existing.invalid = True
                self._counters.provider_item_id_reuse_count += 1
                self._mark_context_tainted("voice_input_item_id_reused")
                return self._invalid_input_event(
                    event, code="voice_input_item_duplicate_start"
                )
            active = self._input_item_contexts.get(
                self._active_raw_input_item_id or ""
            )
            if active is not None and not active.final_seen:
                active.invalid = True
            self._turn_counter += 1
            context = _InputItemContext(
                raw_item_id=raw_item_id,
                provider_item_id=self._local_provider_item_ref(
                    "input", self._turn_counter
                ),
                turn_ref=f"voice-turn-{self._turn_counter:04d}",
                utterance_ref=f"voice-utterance-{self._turn_counter:04d}",
                audio_span_ref=f"voice-audio-span-{self._turn_counter:04d}",
                session_ref=self._session_ref or "voice-session-unavailable",
                session_generation=self._session_generation,
                audio_start_ms=int(audio_start_ms),
            )
            if not self._remember_input_context(context):
                return self._invalid_input_event(
                    event, code="voice_input_context_limit_exceeded"
                )
            self._active_raw_input_item_id = raw_item_id
            self._current_input_item_ref = context.provider_item_id
            self._current_turn_ref = context.turn_ref
            return self._input_event_from_context(event, context)

        context = self._input_item_contexts.get(raw_item_id)
        if not self._input_context_is_current(context):
            if context is None:
                self._invalidate_active_input_after_mismatch()
            return self._invalid_input_event(
                event, code="voice_input_item_unknown_old_or_mismatched"
            )
        assert context is not None

        if event_type == "speech.stopped":
            if (
                context.stopped
                or context.final_seen
                or audio_end_ms is None
                or int(audio_end_ms) < context.audio_start_ms
            ):
                context.invalid = True
                return self._invalid_input_event(
                    event, code="voice_audio_span_invalid"
                )
            context.audio_end_ms = int(audio_end_ms)
            context.stopped = True
            self._latest_audio_end_ms = context.audio_end_ms
            return self._input_event_from_context(event, context)

        if event_type == "user.transcript.delta":
            if context.final_seen:
                context.invalid = True
                return self._invalid_input_event(
                    event, code="voice_transcript_delta_after_final"
                )
            return self._input_event_from_context(event, context)

        if (
            event_type != "user.transcript.final"
            or not context.stopped
            or context.audio_end_ms is None
            or context.final_seen
        ):
            if context.final_seen:
                code = "voice_transcript_final_duplicate"
            else:
                code = "voice_transcript_final_audio_span_incomplete"
            context.invalid = True
            return self._invalid_input_event(event, code=code)
        context.final_seen = True
        self._active_raw_input_item_id = None
        return self._input_event_from_context(event, context)

    def _input_context_is_current(
        self, context: _InputItemContext | None
    ) -> bool:
        return bool(
            context is not None
            and not context.invalid
            and not context.interrupted
            and context.session_generation == self._session_generation
            and context.raw_item_id == self._active_raw_input_item_id
        )

    def _remember_input_context(self, context: _InputItemContext) -> bool:
        if len(self._input_item_contexts) >= _MAX_VOICE_INPUT_ITEMS:
            # Do not evict provider IDs inside a generation.  Once evicted,
            # the same raw ID could be rebound to a new local turn by a late
            # provider event.  Rotate Voice instead.
            self._counters.provider_item_id_horizon_count += 1
            self._mark_context_tainted("voice_input_item_horizon_reached")
            return False
        self._input_item_contexts[context.raw_item_id] = context
        self._input_item_order.append(context.raw_item_id)
        return True

    def _invalidate_active_input_after_mismatch(self) -> None:
        active = self._input_item_contexts.get(
            self._active_raw_input_item_id or ""
        )
        if active is not None:
            active.invalid = True

    def _invalid_input_event(
        self,
        event: NormalizedProviderEvent | _CorrelatedProviderEvent,
        *,
        code: str,
    ) -> VoiceProviderEvent:
        # Correlation failure retires this physical Voice generation.  The
        # coordinator schedules the rebuild, while adapter-local taint is the
        # authoritative prerequisite that makes rebuild_if_tainted advance the
        # generation instead of returning a no-op.
        self._mark_context_tainted(code)
        self._counters.correlation_failure_count += 1
        self._counters.late_event_discard_count += 1
        return VoiceProviderEvent(
            type=event.type,
            output_mode="degraded",
            session_ref=self._session_ref,
            session_generation=self._session_generation,
            text=None,
            stash=None,
            audio=None,
            status=event.status,
            reason=event.reason,
            error_code=_safe_error_code(code),
            terminal=event.terminal,
            suppressed=True,
            quarantined=True,
            correlation_valid=False,
        )

    def _input_event_from_context(
        self,
        event: NormalizedProviderEvent | _CorrelatedProviderEvent,
        context: _InputItemContext,
    ) -> VoiceProviderEvent:
        return VoiceProviderEvent(
            type=event.type,
            output_mode=event.output_mode,
            provider_item_id=context.provider_item_id,
            turn_ref=context.turn_ref,
            utterance_ref=context.utterance_ref,
            audio_span_ref=context.audio_span_ref,
            session_ref=context.session_ref,
            session_generation=context.session_generation,
            audio_start_ms=context.audio_start_ms,
            audio_end_ms=context.audio_end_ms,
            text=event.text,
            stash=event.stash,
            status=event.status,
            reason=event.reason,
            error_code=event.error_code,
            terminal=event.terminal,
            correlation_valid=True,
        )

    def _ensure_turn_ref(self) -> None:
        if self._current_turn_ref is not None:
            return
        self._turn_counter += 1
        self._current_turn_ref = f"voice-turn-{self._turn_counter:04d}"
        self._current_input_item_ref = self._local_provider_item_ref(
            "input", self._turn_counter
        )

    def _local_provider_item_ref(self, kind: str, counter: int) -> str:
        return (
            f"voice-g{self._session_generation:04d}-{kind}-{counter:04d}"
        )

    async def _suppress_voice_output(
        self, event: VoiceProviderEvent
    ) -> VoiceProviderEvent:
        response_id = event.response_id
        if event.type == "response.created":
            if (
                response_id is None
                or event.provider_item_id is None
                or response_id in self._seen_response_ids
                or response_id in self._stale_response_ids
                or response_id in self._suppressed_responses
                or len(self._seen_response_ids)
                >= _MAX_VOICE_PROVIDER_IDS_PER_GENERATION
                or len(self._suppressed_responses)
                >= _MAX_VOICE_RESPONSE_LIFECYCLES
            ):
                self._counters.correlation_failure_count += 1
                self._counters.late_event_discard_count += 1
                if response_id in self._seen_response_ids:
                    self._counters.provider_item_id_reuse_count += 1
                elif event.error_code in {
                    "voice_response_id_reused",
                    "voice_terminal_correlation_invalid",
                }:
                    self._counters.provider_item_id_reuse_count += 1
                elif (
                    len(self._seen_response_ids)
                    >= _MAX_VOICE_PROVIDER_IDS_PER_GENERATION
                    or event.error_code == "voice_response_id_horizon_reached"
                ):
                    self._counters.provider_item_id_horizon_count += 1
                self._mark_context_tainted("voice_response_correlation_invalid")
                if (
                    response_id is not None
                    and response_id not in self._suppressed_responses
                ):
                    self._response_item_refs.pop(response_id, None)
                return replace(
                    event,
                    text=None,
                    stash=None,
                    audio=None,
                    suppressed=True,
                    quarantined=True,
                    correlation_valid=False,
                )
            self._seen_response_ids.add(response_id)
            if any(
                not state.terminal_seen
                for existing_id, state in self._suppressed_responses.items()
                if existing_id != response_id
            ):
                self._counters.correlation_failure_count += 1
                self._mark_context_tainted("voice_overlapping_responses")
                for existing_id, state in self._suppressed_responses.items():
                    if existing_id != response_id and not state.terminal_seen:
                        state.output_eligible = False
            self._suppressed_responses[response_id] = _SuppressedResponseLifecycle(
                response_id=response_id,
                provider_item_id=event.provider_item_id,
                # Enforced Voice output is never eligible for playback.  This
                # bit exists separately from cleanup ownership so interrupt
                # cannot erase the lifecycle before terminal/delete.
                output_eligible=False,
            )
            self._cancel_terminal_outcome = None
            self._active_suppressed_response_id = response_id
            self._counters.quarantine_response_count += 1
            try:
                cancelled = await self.cancel_response()
            except Exception:
                cancelled = False
            if not cancelled:
                # A later matching terminal may still permit confirmed item
                # cleanup, but until then this context is not reusable.
                self._mark_context_tainted("voice_cancel_not_sent")
            return replace(
                event,
                output_mode=event.output_mode if cancelled else "degraded",
                error_code=(event.error_code if cancelled else "voice_cancel_not_sent"),
                suppressed=True,
                quarantined=True,
            )

        assistant_output = event.type in {
            "assistant.transcript.delta",
            "assistant.transcript.done",
            "response.audio.delta",
            "response.audio.done",
        }
        if assistant_output:
            state = self._suppressed_responses.get(response_id or "")
            correlation_valid = (
                response_id is not None
                and state is not None
                and response_id not in self._stale_response_ids
                and not state.cleanup_confirmed
                and not state.terminal_seen
            )
            if not correlation_valid:
                self._counters.correlation_failure_count += 1
                self._counters.late_event_discard_count += 1
                self._mark_context_tainted("voice_output_correlation_invalid")
            if event.type == "assistant.transcript.delta":
                self._counters.suppressed_text_delta_count += 1
            if event.type == "response.audio.delta":
                self._counters.suppressed_audio_frame_count += 1
                self._counters.suppressed_audio_byte_count += event.byte_length
            return replace(
                event,
                text=None,
                stash=None,
                audio=None,
                suppressed=True,
                quarantined=True,
                correlation_valid=correlation_valid,
            )

        if event.type == "response.done":
            state = (
                self._suppressed_responses.get(response_id)
                if response_id is not None
                else None
            )
            correlation_valid = (
                state is not None
                and response_id not in self._stale_response_ids
                and not state.terminal_seen
            )
            if not correlation_valid:
                self._counters.correlation_failure_count += 1
                self._counters.late_event_discard_count += 1
                self._mark_context_tainted("voice_terminal_correlation_invalid")
            else:
                assert state is not None
                state.terminal_seen = True
                state.terminal_status = event.status or "unknown"
                state.output_eligible = False
                if state.cancel_requested:
                    if (
                        state.terminal_status == "cancelled"
                        and not state.watchdog_expired
                    ):
                        outcome: CancelTerminalOutcome = "cancelled_on_time"
                        state.cancel_terminal_success = True
                        self._counters.cancel_terminal_count += 1
                    else:
                        self._counters.unsafe_cancel_terminal_count += 1
                        if state.terminal_status == "cancelled":
                            outcome = "cancelled_after_watchdog"
                            self._counters.late_event_discard_count += 1
                        elif state.terminal_status == "completed":
                            outcome = "completed_after_cancel"
                            self._counters.completed_after_cancel_count += 1
                        elif state.terminal_status == "failed":
                            outcome = "failed_after_cancel"
                            self._counters.failed_after_cancel_count += 1
                        else:
                            outcome = "missing_terminal"
                        self._mark_context_tainted(
                            "voice_cancel_terminal_status_unsafe"
                        )
                    state.cancel_terminal_outcome = outcome
                    self._cancel_terminal_outcome = outcome
                state.terminal_event.set()
                if self._active_suppressed_response_id == response_id:
                    self._active_suppressed_response_id = None
            return replace(
                event,
                output_mode=(
                    event.output_mode
                    if correlation_valid
                    and state is not None
                    and state.cancel_terminal_success
                    else "degraded"
                ),
                text=None,
                stash=None,
                audio=None,
                terminal=True,
                suppressed=True,
                quarantined=True,
                correlation_valid=correlation_valid,
            )
        return event

    def _record_delete_failure(self) -> None:
        self._counters.context_delete_failure_count += 1
        self._mark_context_tainted("voice_context_delete_unconfirmed")

    def _mark_context_tainted(self, _code: str) -> None:
        self._context_tainted = True
        self._profile = self._make_profile(health_status="degraded")

    def _record_ingress_drop(self, byte_count: int, *, rebuilding: bool) -> None:
        self._counters.ingress_generation_drop_count += 1
        if rebuilding:
            self._counters.rebuild_audio_drop_count += 1
            self._counters.rebuild_audio_drop_byte_count += max(0, int(byte_count))

    def _make_profile(
        self, *, health_status: HealthStatus = "not_executed"
    ) -> CapabilityProfile:
        profile = qwen_voice_capability_profile(
            health_status=health_status,
            enforced_output_suppression=self._enforced_output_suppression,
        )
        if not self._enforced_output_suppression:
            return profile
        if not callable(getattr(self._core, "delete_response_items", None)):
            profile = replace(
                profile,
                supports_provider_item_delete=False,
                provider_item_correlation="unavailable_fail_closed",
                provider_item_delete_verification="unsupported_or_unverified",
            )
        if self._provider_core_factory is None:
            profile = replace(
                profile,
                supports_context_rebuild=False,
                context_rebuild_verification="unsupported_or_unverified",
            )
        return profile


def _safe_error_code(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return "voice_provider_error"
    token = _SAFE_ERROR_TOKEN.sub("_", value)[:96]
    return token or "voice_provider_error"


def _valid_provider_ref(value: Any) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= _MAX_PROVIDER_REF_CHARS


def _safe_audio_offset(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0 or value > 86_400_000:
        return None
    return value


__all__ = [
    "QwenVoiceAdapter",
    "VoiceProviderError",
    "VoiceProviderEvent",
    "VoiceSuppressionCounters",
]
