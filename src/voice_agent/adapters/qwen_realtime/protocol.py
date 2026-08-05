from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields
from typing import Any, ClassVar, Literal, TypeAlias


CLIENT_EVENT_TYPES = frozenset(
    {
        "session.update",
        "input_audio_buffer.append",
        "response.cancel",
        "conversation.item.delete",
    }
)
SERVER_EVENT_TYPES = frozenset(
    {
        "session.created",
        "session.updated",
        "input_audio_buffer.speech_started",
        "input_audio_buffer.speech_stopped",
        "input_audio_buffer.committed",
        "conversation.item.created",
        "conversation.item.deleted",
        "conversation.item.input_audio_transcription.delta",
        "conversation.item.input_audio_transcription.completed",
        "conversation.item.input_audio_transcription.failed",
        "conversation.item.ambient_audio_transcription.delta",
        "conversation.item.ambient_audio_transcription.completed",
        "response.created",
        "response.output_item.added",
        "response.content_part.added",
        "response.audio_transcript.delta",
        "response.audio.delta",
        "response.audio_transcript.done",
        "response.audio.done",
        "response.content_part.done",
        "response.output_item.done",
        "response.done",
        "error",
    }
)

class QwenProtocolError(ValueError):
    """Fail-closed schema error with a bounded, payload-free error code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _nonempty(value: object, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise QwenProtocolError(code)
    return value


def _optional_nonempty(value: object, code: str) -> str | None:
    if value is None:
        return None
    return _nonempty(value, code)


def _index(value: object, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise QwenProtocolError(code)
    return value


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise QwenProtocolError(code)
    return value


def _sequence(value: object, code: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, Sequence
    ):
        raise QwenProtocolError(code)
    return value


@dataclass(frozen=True, slots=True, repr=False)
class _FrozenJSONObject:
    items: tuple[tuple[str, object], ...]


@dataclass(frozen=True, slots=True, repr=False)
class _FrozenJSONArray:
    items: tuple[object, ...]


FrozenJSONMapping: TypeAlias = (
    _FrozenJSONObject
    | tuple[tuple[str, object], ...]
    | Mapping[str, object]
)


def _freeze_json(value: object, code: str) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        keys = tuple(value.keys())
        if any(not isinstance(key, str) for key in keys):
            raise QwenProtocolError(code)
        frozen: list[tuple[str, object]] = []
        for key in sorted(keys):
            frozen.append((key, _freeze_json(value[key], code)))
        return _FrozenJSONObject(tuple(frozen))
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return _FrozenJSONArray(
            tuple(_freeze_json(item, code) for item in value)
        )
    raise QwenProtocolError(code)


def _validate_frozen_json(value: object, code: str) -> None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return
    if isinstance(value, _FrozenJSONObject):
        keys = [item[0] for item in value.items]
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            raise QwenProtocolError(code)
        for _, nested in value.items:
            _validate_frozen_json(nested, code)
        return
    if isinstance(value, _FrozenJSONArray):
        for nested in value.items:
            _validate_frozen_json(nested, code)
        return
    raise QwenProtocolError(code)


def _freeze_legacy_json(value: object, code: str) -> object:
    if isinstance(value, (_FrozenJSONObject, _FrozenJSONArray)):
        _validate_frozen_json(value, code)
        return value
    if isinstance(value, tuple):
        if value and all(
            isinstance(item, tuple)
            and len(item) == 2
            and isinstance(item[0], str)
            for item in value
        ):
            return _coerce_frozen_mapping(value, code)
        return _FrozenJSONArray(
            tuple(_freeze_legacy_json(item, code) for item in value)
        )
    return _freeze_json(value, code)


def _coerce_frozen_mapping(
    value: object,
    code: str,
) -> _FrozenJSONObject:
    if isinstance(value, _FrozenJSONObject):
        _validate_frozen_json(value, code)
        return value
    if isinstance(value, Mapping):
        frozen = _freeze_json(value, code)
        if isinstance(frozen, _FrozenJSONObject):
            return frozen
        raise QwenProtocolError(code)
    if not isinstance(value, tuple):
        raise QwenProtocolError(code)
    entries: list[tuple[str, object]] = []
    for item in value:
        if (
            not isinstance(item, tuple)
            or len(item) != 2
            or not isinstance(item[0], str)
        ):
            raise QwenProtocolError(code)
        entries.append((item[0], _freeze_legacy_json(item[1], code)))
    keys = [key for key, _ in entries]
    if len(keys) != len(set(keys)):
        raise QwenProtocolError(code)
    return _FrozenJSONObject(tuple(sorted(entries)))


def _thaw_json(value: object) -> object:
    if isinstance(value, _FrozenJSONObject):
        return {
            key: _thaw_json(nested)
            for key, nested in value.items
        }
    if isinstance(value, _FrozenJSONArray):
        return [_thaw_json(nested) for nested in value.items]
    return value


def _thaw_mapping(value: FrozenJSONMapping) -> dict[str, object]:
    frozen = _coerce_frozen_mapping(value, "invalid_frozen_mapping")
    return {
        key: _thaw_json(nested)
        for key, nested in frozen.items
    }


@dataclass(frozen=True, slots=True)
class QwenSessionConfiguration:
    turn_detection_type: Literal["smart_turn"]
    modalities: tuple[str, ...]
    voice: str
    input_audio_transcription: FrozenJSONMapping = field(repr=False)
    tools: tuple[FrozenJSONMapping, ...] = field(repr=False)
    fast_role_profile: str

    def __post_init__(self) -> None:
        if self.turn_detection_type != "smart_turn":
            raise QwenProtocolError("invalid_turn_detection_type")
        if (
            not isinstance(self.modalities, tuple)
            or not self.modalities
            or any(not isinstance(item, str) or not item for item in self.modalities)
            or len(set(self.modalities)) != len(self.modalities)
        ):
            raise QwenProtocolError("invalid_modalities")
        _nonempty(self.voice, "invalid_voice")
        frozen_input = _coerce_frozen_mapping(
            self.input_audio_transcription,
            "invalid_input_audio_transcription",
        )
        object.__setattr__(
            self,
            "input_audio_transcription",
            frozen_input,
        )
        if not isinstance(self.tools, tuple):
            raise QwenProtocolError("invalid_tools")
        frozen_tools = tuple(
            _coerce_frozen_mapping(tool, "invalid_tools")
            for tool in self.tools
        )
        object.__setattr__(self, "tools", frozen_tools)
        _nonempty(self.fast_role_profile, "invalid_fast_role_profile")

    @classmethod
    def from_session_mapping(
        cls,
        session: Mapping[str, object],
    ) -> QwenSessionConfiguration:
        turn_detection = _mapping(
            session.get("turn_detection"),
            "invalid_turn_detection",
        )
        modalities = _sequence(
            session.get("modalities"),
            "invalid_modalities",
        )
        input_transcription = _mapping(
            session.get("input_audio_transcription"),
            "invalid_input_audio_transcription",
        )
        tools = _sequence(session.get("tools"), "invalid_tools")
        frozen_tools: list[_FrozenJSONObject] = []
        for tool in tools:
            tool_mapping = _mapping(tool, "invalid_tools")
            frozen_tools.append(
                _coerce_frozen_mapping(tool_mapping, "invalid_tools")
            )
        frozen_input = _coerce_frozen_mapping(
            input_transcription,
            "invalid_input_audio_transcription",
        )
        return cls(
            turn_detection_type=_nonempty(
                turn_detection.get("type"),
                "invalid_turn_detection_type",
            ),
            modalities=tuple(
                _nonempty(item, "invalid_modalities") for item in modalities
            ),
            voice=_nonempty(session.get("voice"), "invalid_voice"),
            input_audio_transcription=frozen_input,
            tools=tuple(frozen_tools),
            fast_role_profile=_nonempty(
                session.get("fast_role_profile"),
                "invalid_fast_role_profile",
            ),
        )

    def to_session_mapping(self) -> dict[str, object]:
        return {
            "turn_detection": {"type": self.turn_detection_type},
            "modalities": list(self.modalities),
            "voice": self.voice,
            "input_audio_transcription": _thaw_mapping(
                self.input_audio_transcription
            ),
            "tools": [_thaw_mapping(tool) for tool in self.tools],
            "fast_role_profile": self.fast_role_profile,
        }


@dataclass(frozen=True, slots=True)
class SessionUpdateClientEvent:
    type: ClassVar[Literal["session.update"]] = "session.update"
    configuration: QwenSessionConfiguration = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.configuration, QwenSessionConfiguration):
            raise QwenProtocolError("invalid_session_configuration")


@dataclass(frozen=True, slots=True)
class InputAudioBufferAppendClientEvent:
    type: ClassVar[Literal["input_audio_buffer.append"]] = (
        "input_audio_buffer.append"
    )
    pcm16le: bytearray = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.pcm16le, bytearray) or not self.pcm16le:
            raise QwenProtocolError("invalid_input_audio")


@dataclass(frozen=True, slots=True)
class ResponseCancelClientEvent:
    type: ClassVar[Literal["response.cancel"]] = "response.cancel"


@dataclass(frozen=True, slots=True)
class ConversationItemDeleteClientEvent:
    type: ClassVar[Literal["conversation.item.delete"]] = (
        "conversation.item.delete"
    )
    item_id: str

    def __post_init__(self) -> None:
        _nonempty(self.item_id, "invalid_item_id")


QwenClientEvent = (
    SessionUpdateClientEvent
    | InputAudioBufferAppendClientEvent
    | ResponseCancelClientEvent
    | ConversationItemDeleteClientEvent
)


def encode_client_event(event: QwenClientEvent) -> dict[str, object]:
    if isinstance(event, SessionUpdateClientEvent):
        return {
            "type": event.type,
            "session": event.configuration.to_session_mapping(),
        }
    if isinstance(event, InputAudioBufferAppendClientEvent):
        return {
            "type": event.type,
            "audio": base64.b64encode(event.pcm16le).decode("ascii"),
        }
    if isinstance(event, ResponseCancelClientEvent):
        return {"type": event.type}
    if isinstance(event, ConversationItemDeleteClientEvent):
        return {"type": event.type, "item_id": event.item_id}
    raise QwenProtocolError("unsupported_client_event")


@dataclass(frozen=True, slots=True)
class QwenContentPartSnapshot:
    content_type: str
    text: str = field(default="", repr=False)
    transcript: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        _nonempty(self.content_type, "invalid_content_type")
        if not isinstance(self.text, str) or not isinstance(self.transcript, str):
            raise QwenProtocolError("invalid_content_payload")


@dataclass(frozen=True, slots=True)
class QwenOutputItemSnapshot:
    item_id: str
    item_type: str
    item_status: str | None
    role: str | None
    content_parts: tuple[QwenContentPartSnapshot, ...] = field(
        default=(),
        repr=False,
    )

    def __post_init__(self) -> None:
        _nonempty(self.item_id, "invalid_item_id")
        _nonempty(self.item_type, "invalid_item_type")
        _optional_nonempty(self.item_status, "invalid_item_status")
        _optional_nonempty(self.role, "invalid_item_role")
        if (
            not isinstance(self.content_parts, tuple)
            or any(
                not isinstance(item, QwenContentPartSnapshot)
                for item in self.content_parts
            )
        ):
            raise QwenProtocolError("invalid_item_content")


@dataclass(frozen=True, slots=True)
class _ServerEventBase:
    event_id: str
    type: ClassVar[str]

    def __post_init__(self) -> None:
        _nonempty(self.event_id, "invalid_event_id")
        for definition in fields(self):
            name = definition.name
            value = getattr(self, name)
            if name.endswith("_id") and name != "event_id":
                if name == "previous_item_id":
                    _optional_nonempty(value, f"invalid_{name}")
                else:
                    _nonempty(value, f"invalid_{name}")
            elif name.endswith("_index"):
                _index(value, f"invalid_{name}")


@dataclass(frozen=True, slots=True)
class SessionCreatedServerEvent(_ServerEventBase):
    type: ClassVar[Literal["session.created"]] = "session.created"
    session_id: str


@dataclass(frozen=True, slots=True)
class SessionUpdatedServerEvent(_ServerEventBase):
    type: ClassVar[Literal["session.updated"]] = "session.updated"
    session_id: str
    configuration: QwenSessionConfiguration = field(repr=False)

    def __post_init__(self) -> None:
        _ServerEventBase.__post_init__(self)
        if not isinstance(self.configuration, QwenSessionConfiguration):
            raise QwenProtocolError("invalid_session_configuration")


@dataclass(frozen=True, slots=True)
class SpeechStartedServerEvent(_ServerEventBase):
    type: ClassVar[Literal["input_audio_buffer.speech_started"]] = (
        "input_audio_buffer.speech_started"
    )
    item_id: str
    audio_start_ms: int

    def __post_init__(self) -> None:
        _ServerEventBase.__post_init__(self)
        _index(self.audio_start_ms, "invalid_audio_start_ms")


@dataclass(frozen=True, slots=True)
class SpeechStoppedServerEvent(_ServerEventBase):
    type: ClassVar[Literal["input_audio_buffer.speech_stopped"]] = (
        "input_audio_buffer.speech_stopped"
    )
    item_id: str
    audio_end_ms: int
    stop_reason: Literal["turn_invalid"] | None = None

    def __post_init__(self) -> None:
        _ServerEventBase.__post_init__(self)
        _index(self.audio_end_ms, "invalid_audio_end_ms")
        if self.stop_reason not in {None, "turn_invalid"}:
            raise QwenProtocolError("invalid_stop_reason")


@dataclass(frozen=True, slots=True)
class InputAudioCommittedServerEvent(_ServerEventBase):
    type: ClassVar[Literal["input_audio_buffer.committed"]] = (
        "input_audio_buffer.committed"
    )
    item_id: str
    previous_item_id: str | None = None


@dataclass(frozen=True, slots=True)
class ConversationItemCreatedServerEvent(_ServerEventBase):
    type: ClassVar[Literal["conversation.item.created"]] = (
        "conversation.item.created"
    )
    item_id: str
    item_type: str
    item_status: str | None
    role: str | None
    previous_item_id: str | None = None
    content_parts: tuple[QwenContentPartSnapshot, ...] = field(
        default=(),
        repr=False,
    )

    def __post_init__(self) -> None:
        _ServerEventBase.__post_init__(self)
        QwenOutputItemSnapshot(
            item_id=self.item_id,
            item_type=self.item_type,
            item_status=self.item_status,
            role=self.role,
            content_parts=self.content_parts,
        )


@dataclass(frozen=True, slots=True)
class ConversationItemDeletedServerEvent(_ServerEventBase):
    type: ClassVar[Literal["conversation.item.deleted"]] = (
        "conversation.item.deleted"
    )
    item_id: str


@dataclass(frozen=True, slots=True)
class InputTranscriptionDeltaServerEvent(_ServerEventBase):
    type: ClassVar[
        Literal["conversation.item.input_audio_transcription.delta"]
    ] = "conversation.item.input_audio_transcription.delta"
    item_id: str
    content_index: int
    text: str = field(repr=False)
    stash: str = field(repr=False)

    def __post_init__(self) -> None:
        _ServerEventBase.__post_init__(self)
        if not isinstance(self.text, str) or not isinstance(self.stash, str):
            raise QwenProtocolError("invalid_transcription_payload")


@dataclass(frozen=True, slots=True)
class InputTranscriptionCompletedServerEvent(_ServerEventBase):
    type: ClassVar[
        Literal["conversation.item.input_audio_transcription.completed"]
    ] = "conversation.item.input_audio_transcription.completed"
    item_id: str
    content_index: int
    transcript: str = field(repr=False)

    def __post_init__(self) -> None:
        _ServerEventBase.__post_init__(self)
        if not isinstance(self.transcript, str):
            raise QwenProtocolError("invalid_transcript")


@dataclass(frozen=True, slots=True)
class InputTranscriptionFailedServerEvent(_ServerEventBase):
    type: ClassVar[
        Literal["conversation.item.input_audio_transcription.failed"]
    ] = "conversation.item.input_audio_transcription.failed"
    item_id: str
    content_index: int
    error_type: str = field(repr=False)
    error_code: str = field(repr=False)
    error_message: str = field(repr=False)

    def __post_init__(self) -> None:
        _ServerEventBase.__post_init__(self)
        _nonempty(self.error_type, "invalid_error_type")
        _nonempty(self.error_code, "invalid_error_code")
        if not isinstance(self.error_message, str):
            raise QwenProtocolError("invalid_error_message")


@dataclass(frozen=True, slots=True)
class AmbientTranscriptionDeltaServerEvent(_ServerEventBase):
    type: ClassVar[
        Literal["conversation.item.ambient_audio_transcription.delta"]
    ] = "conversation.item.ambient_audio_transcription.delta"
    item_id: str
    content_index: int
    text: str = field(repr=False)
    stash: str = field(repr=False)

    def __post_init__(self) -> None:
        _ServerEventBase.__post_init__(self)
        if not isinstance(self.text, str) or not isinstance(self.stash, str):
            raise QwenProtocolError("invalid_transcription_payload")


@dataclass(frozen=True, slots=True)
class AmbientTranscriptionCompletedServerEvent(_ServerEventBase):
    type: ClassVar[
        Literal["conversation.item.ambient_audio_transcription.completed"]
    ] = "conversation.item.ambient_audio_transcription.completed"
    item_id: str
    content_index: int
    transcript: str = field(repr=False)

    def __post_init__(self) -> None:
        _ServerEventBase.__post_init__(self)
        if not isinstance(self.transcript, str):
            raise QwenProtocolError("invalid_transcript")


@dataclass(frozen=True, slots=True)
class ResponseCreatedServerEvent(_ServerEventBase):
    type: ClassVar[Literal["response.created"]] = "response.created"
    response_id: str
    response_status: str

    def __post_init__(self) -> None:
        _ServerEventBase.__post_init__(self)
        _nonempty(self.response_status, "invalid_response_status")


@dataclass(frozen=True, slots=True)
class ResponseOutputItemAddedServerEvent(_ServerEventBase):
    type: ClassVar[Literal["response.output_item.added"]] = (
        "response.output_item.added"
    )
    response_id: str
    output_index: int
    item_id: str
    item_type: str
    item_status: str | None
    role: str | None
    content_parts: tuple[QwenContentPartSnapshot, ...] = field(
        default=(),
        repr=False,
    )

    def __post_init__(self) -> None:
        _ServerEventBase.__post_init__(self)
        QwenOutputItemSnapshot(
            item_id=self.item_id,
            item_type=self.item_type,
            item_status=self.item_status,
            role=self.role,
            content_parts=self.content_parts,
        )


@dataclass(frozen=True, slots=True)
class ResponseContentPartAddedServerEvent(_ServerEventBase):
    type: ClassVar[Literal["response.content_part.added"]] = (
        "response.content_part.added"
    )
    response_id: str
    item_id: str
    output_index: int
    content_index: int
    content_type: str
    text: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        _ServerEventBase.__post_init__(self)
        _nonempty(self.content_type, "invalid_content_type")
        if not isinstance(self.text, str):
            raise QwenProtocolError("invalid_content_payload")


@dataclass(frozen=True, slots=True)
class ResponseAudioTranscriptDeltaServerEvent(_ServerEventBase):
    type: ClassVar[Literal["response.audio_transcript.delta"]] = (
        "response.audio_transcript.delta"
    )
    response_id: str
    item_id: str
    output_index: int
    content_index: int
    delta: str = field(repr=False)

    def __post_init__(self) -> None:
        _ServerEventBase.__post_init__(self)
        if not isinstance(self.delta, str):
            raise QwenProtocolError("invalid_transcript_delta")


@dataclass(frozen=True, slots=True)
class ResponseAudioDeltaServerEvent(_ServerEventBase):
    type: ClassVar[Literal["response.audio.delta"]] = "response.audio.delta"
    response_id: str
    item_id: str
    output_index: int
    content_index: int
    pcm: bytearray = field(repr=False)

    def __post_init__(self) -> None:
        _ServerEventBase.__post_init__(self)
        if not isinstance(self.pcm, bytearray) or not self.pcm:
            raise QwenProtocolError("invalid_audio_delta")


@dataclass(frozen=True, slots=True)
class ResponseAudioTranscriptDoneServerEvent(_ServerEventBase):
    type: ClassVar[Literal["response.audio_transcript.done"]] = (
        "response.audio_transcript.done"
    )
    response_id: str
    item_id: str
    output_index: int
    content_index: int
    transcript: str = field(repr=False)

    def __post_init__(self) -> None:
        _ServerEventBase.__post_init__(self)
        if not isinstance(self.transcript, str):
            raise QwenProtocolError("invalid_transcript")


@dataclass(frozen=True, slots=True)
class ResponseAudioDoneServerEvent(_ServerEventBase):
    type: ClassVar[Literal["response.audio.done"]] = "response.audio.done"
    response_id: str
    item_id: str
    output_index: int
    content_index: int


@dataclass(frozen=True, slots=True)
class ResponseContentPartDoneServerEvent(_ServerEventBase):
    type: ClassVar[Literal["response.content_part.done"]] = (
        "response.content_part.done"
    )
    response_id: str
    item_id: str
    output_index: int
    content_index: int
    content_type: str
    text: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        _ServerEventBase.__post_init__(self)
        _nonempty(self.content_type, "invalid_content_type")
        if not isinstance(self.text, str):
            raise QwenProtocolError("invalid_content_payload")


@dataclass(frozen=True, slots=True)
class ResponseOutputItemDoneServerEvent(_ServerEventBase):
    type: ClassVar[Literal["response.output_item.done"]] = (
        "response.output_item.done"
    )
    response_id: str
    output_index: int
    item_id: str
    item_type: str
    item_status: str | None
    role: str | None
    content_parts: tuple[QwenContentPartSnapshot, ...] = field(
        default=(),
        repr=False,
    )

    def __post_init__(self) -> None:
        _ServerEventBase.__post_init__(self)
        QwenOutputItemSnapshot(
            item_id=self.item_id,
            item_type=self.item_type,
            item_status=self.item_status,
            role=self.role,
            content_parts=self.content_parts,
        )


@dataclass(frozen=True, slots=True)
class ResponseDoneServerEvent(_ServerEventBase):
    type: ClassVar[Literal["response.done"]] = "response.done"
    response_id: str
    terminal_status: Literal["completed", "cancelled", "failed"]
    response_terminal_reason: (
        Literal["turn_detected", "client_cancelled"] | None
    ) = None
    output_items: tuple[QwenOutputItemSnapshot, ...] = field(
        default=(),
        repr=False,
    )

    def __post_init__(self) -> None:
        _ServerEventBase.__post_init__(self)
        if self.terminal_status not in {"completed", "cancelled", "failed"}:
            raise QwenProtocolError("invalid_terminal_status")
        if self.response_terminal_reason not in {
            None,
            "turn_detected",
            "client_cancelled",
        }:
            raise QwenProtocolError("invalid_terminal_reason")
        if self.terminal_status == "completed" and (
            self.response_terminal_reason is not None
        ):
            raise QwenProtocolError("invalid_terminal_reason")
        if (
            not isinstance(self.output_items, tuple)
            or any(
                not isinstance(item, QwenOutputItemSnapshot)
                for item in self.output_items
            )
        ):
            raise QwenProtocolError("invalid_response_output")


@dataclass(frozen=True, slots=True)
class ErrorServerEvent(_ServerEventBase):
    type: ClassVar[Literal["error"]] = "error"
    error_type: Literal["invalid_request_error", "server_error"] = field(
        repr=False
    )
    error_code: str = field(repr=False)
    error_param: str | None = field(default=None, repr=False)
    error_message: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        _ServerEventBase.__post_init__(self)
        if self.error_type not in {"invalid_request_error", "server_error"}:
            raise QwenProtocolError("invalid_error_type")
        _nonempty(self.error_code, "invalid_error_code")
        _optional_nonempty(self.error_param, "invalid_error_param")
        if not isinstance(self.error_message, str):
            raise QwenProtocolError("invalid_error_message")

    @property
    def terminal(self) -> bool:
        return self.error_type == "server_error"


QwenServerEvent = (
    SessionCreatedServerEvent
    | SessionUpdatedServerEvent
    | SpeechStartedServerEvent
    | SpeechStoppedServerEvent
    | InputAudioCommittedServerEvent
    | ConversationItemCreatedServerEvent
    | ConversationItemDeletedServerEvent
    | InputTranscriptionDeltaServerEvent
    | InputTranscriptionCompletedServerEvent
    | InputTranscriptionFailedServerEvent
    | AmbientTranscriptionDeltaServerEvent
    | AmbientTranscriptionCompletedServerEvent
    | ResponseCreatedServerEvent
    | ResponseOutputItemAddedServerEvent
    | ResponseContentPartAddedServerEvent
    | ResponseAudioTranscriptDeltaServerEvent
    | ResponseAudioDeltaServerEvent
    | ResponseAudioTranscriptDoneServerEvent
    | ResponseAudioDoneServerEvent
    | ResponseContentPartDoneServerEvent
    | ResponseOutputItemDoneServerEvent
    | ResponseDoneServerEvent
    | ErrorServerEvent
)


def _parse_content_parts(value: object) -> tuple[QwenContentPartSnapshot, ...]:
    content = _sequence(value, "invalid_item_content")
    parsed: list[QwenContentPartSnapshot] = []
    for raw_part in content:
        part = _mapping(raw_part, "invalid_item_content")
        parsed.append(
            QwenContentPartSnapshot(
                content_type=_nonempty(
                    part.get("type"),
                    "invalid_content_type",
                ),
                text=part.get("text", "")
                if isinstance(part.get("text", ""), str)
                else _raise("invalid_content_payload"),
                transcript=part.get("transcript", "")
                if isinstance(part.get("transcript", ""), str)
                else _raise("invalid_content_payload"),
            )
        )
    return tuple(parsed)


def _raise(code: str) -> Any:
    raise QwenProtocolError(code)


def _parse_item(value: object) -> QwenOutputItemSnapshot:
    item = _mapping(value, "invalid_item")
    content_value = item.get("content", ())
    return QwenOutputItemSnapshot(
        item_id=_nonempty(item.get("id"), "invalid_item_id"),
        item_type=_nonempty(item.get("type"), "invalid_item_type"),
        item_status=_optional_nonempty(
            item.get("status"),
            "invalid_item_status",
        ),
        role=_optional_nonempty(item.get("role"), "invalid_item_role"),
        content_parts=_parse_content_parts(content_value),
    )


def _common_response_identity(
    payload: Mapping[str, object],
) -> tuple[str, str, int, int]:
    return (
        _nonempty(payload.get("response_id"), "invalid_response_id"),
        _nonempty(payload.get("item_id"), "invalid_item_id"),
        _index(payload.get("output_index"), "invalid_output_index"),
        _index(payload.get("content_index"), "invalid_content_index"),
    )


def parse_server_event(payload: Mapping[str, object]) -> QwenServerEvent:
    if not isinstance(payload, Mapping):
        raise QwenProtocolError("invalid_server_event")
    event_id = _nonempty(payload.get("event_id"), "invalid_event_id")
    event_type = payload.get("type")
    if not isinstance(event_type, str) or event_type not in SERVER_EVENT_TYPES:
        raise QwenProtocolError("unsupported_server_event")

    if event_type == "session.created":
        session = _mapping(payload.get("session"), "invalid_session")
        return SessionCreatedServerEvent(
            event_id=event_id,
            session_id=_nonempty(session.get("id"), "invalid_session_id"),
        )
    if event_type == "session.updated":
        session = _mapping(payload.get("session"), "invalid_session")
        return SessionUpdatedServerEvent(
            event_id=event_id,
            session_id=_nonempty(session.get("id"), "invalid_session_id"),
            configuration=QwenSessionConfiguration.from_session_mapping(session),
        )
    if event_type == "input_audio_buffer.speech_started":
        return SpeechStartedServerEvent(
            event_id=event_id,
            item_id=_nonempty(payload.get("item_id"), "invalid_item_id"),
            audio_start_ms=_index(
                payload.get("audio_start_ms"),
                "invalid_audio_start_ms",
            ),
        )
    if event_type == "input_audio_buffer.speech_stopped":
        reason = payload.get("reason")
        if reason not in {None, "turn_invalid"}:
            raise QwenProtocolError("invalid_stop_reason")
        return SpeechStoppedServerEvent(
            event_id=event_id,
            item_id=_nonempty(payload.get("item_id"), "invalid_item_id"),
            audio_end_ms=_index(
                payload.get("audio_end_ms"),
                "invalid_audio_end_ms",
            ),
            stop_reason=reason,
        )
    if event_type == "input_audio_buffer.committed":
        return InputAudioCommittedServerEvent(
            event_id=event_id,
            item_id=_nonempty(payload.get("item_id"), "invalid_item_id"),
            previous_item_id=_optional_nonempty(
                payload.get("previous_item_id"),
                "invalid_previous_item_id",
            ),
        )
    if event_type == "conversation.item.created":
        item = _parse_item(payload.get("item"))
        return ConversationItemCreatedServerEvent(
            event_id=event_id,
            previous_item_id=_optional_nonempty(
                payload.get("previous_item_id"),
                "invalid_previous_item_id",
            ),
            item_id=item.item_id,
            item_type=item.item_type,
            item_status=item.item_status,
            role=item.role,
            content_parts=item.content_parts,
        )
    if event_type == "conversation.item.deleted":
        return ConversationItemDeletedServerEvent(
            event_id=event_id,
            item_id=_nonempty(payload.get("item_id"), "invalid_item_id"),
        )
    if event_type in {
        "conversation.item.input_audio_transcription.delta",
        "conversation.item.ambient_audio_transcription.delta",
    }:
        item_id = _nonempty(payload.get("item_id"), "invalid_item_id")
        content_index = _index(
            payload.get("content_index"),
            "invalid_content_index",
        )
        text = payload.get("text")
        stash = payload.get("stash")
        if not isinstance(text, str) or not isinstance(stash, str):
            raise QwenProtocolError("invalid_transcription_payload")
        event_class = (
            InputTranscriptionDeltaServerEvent
            if event_type.startswith("conversation.item.input_")
            else AmbientTranscriptionDeltaServerEvent
        )
        return event_class(
            event_id=event_id,
            item_id=item_id,
            content_index=content_index,
            text=text,
            stash=stash,
        )
    if event_type in {
        "conversation.item.input_audio_transcription.completed",
        "conversation.item.ambient_audio_transcription.completed",
    }:
        transcript = payload.get("transcript")
        if not isinstance(transcript, str):
            raise QwenProtocolError("invalid_transcript")
        event_class = (
            InputTranscriptionCompletedServerEvent
            if event_type.startswith("conversation.item.input_")
            else AmbientTranscriptionCompletedServerEvent
        )
        return event_class(
            event_id=event_id,
            item_id=_nonempty(payload.get("item_id"), "invalid_item_id"),
            content_index=_index(
                payload.get("content_index"),
                "invalid_content_index",
            ),
            transcript=transcript,
        )
    if event_type == "conversation.item.input_audio_transcription.failed":
        error = _mapping(payload.get("error"), "invalid_error")
        message = error.get("message", "")
        if not isinstance(message, str):
            raise QwenProtocolError("invalid_error_message")
        return InputTranscriptionFailedServerEvent(
            event_id=event_id,
            item_id=_nonempty(payload.get("item_id"), "invalid_item_id"),
            content_index=_index(
                payload.get("content_index"),
                "invalid_content_index",
            ),
            error_type=_nonempty(error.get("type"), "invalid_error_type"),
            error_code=_nonempty(error.get("code"), "invalid_error_code"),
            error_message=message,
        )
    if event_type == "response.created":
        response = _mapping(payload.get("response"), "invalid_response")
        return ResponseCreatedServerEvent(
            event_id=event_id,
            response_id=_nonempty(
                response.get("id"),
                "invalid_response_id",
            ),
            response_status=_nonempty(
                response.get("status"),
                "invalid_response_status",
            ),
        )
    if event_type in {
        "response.output_item.added",
        "response.output_item.done",
    }:
        item = _parse_item(payload.get("item"))
        arguments = {
            "event_id": event_id,
            "response_id": _nonempty(
                payload.get("response_id"),
                "invalid_response_id",
            ),
            "output_index": _index(
                payload.get("output_index"),
                "invalid_output_index",
            ),
            "item_id": item.item_id,
            "item_type": item.item_type,
            "item_status": item.item_status,
            "role": item.role,
            "content_parts": item.content_parts,
        }
        if event_type == "response.output_item.added":
            return ResponseOutputItemAddedServerEvent(**arguments)
        return ResponseOutputItemDoneServerEvent(**arguments)
    if event_type in {
        "response.content_part.added",
        "response.content_part.done",
    }:
        response_id, item_id, output_index, content_index = (
            _common_response_identity(payload)
        )
        part = _mapping(payload.get("part"), "invalid_content_part")
        text = part.get("text", "")
        if not isinstance(text, str):
            raise QwenProtocolError("invalid_content_payload")
        arguments = {
            "event_id": event_id,
            "response_id": response_id,
            "item_id": item_id,
            "output_index": output_index,
            "content_index": content_index,
            "content_type": _nonempty(
                part.get("type"),
                "invalid_content_type",
            ),
            "text": text,
        }
        if event_type == "response.content_part.added":
            return ResponseContentPartAddedServerEvent(**arguments)
        return ResponseContentPartDoneServerEvent(**arguments)
    if event_type in {
        "response.audio_transcript.delta",
        "response.audio.delta",
        "response.audio_transcript.done",
        "response.audio.done",
    }:
        response_id, item_id, output_index, content_index = (
            _common_response_identity(payload)
        )
        arguments = {
            "event_id": event_id,
            "response_id": response_id,
            "item_id": item_id,
            "output_index": output_index,
            "content_index": content_index,
        }
        if event_type == "response.audio_transcript.delta":
            delta = payload.get("delta")
            if not isinstance(delta, str):
                raise QwenProtocolError("invalid_transcript_delta")
            return ResponseAudioTranscriptDeltaServerEvent(
                **arguments,
                delta=delta,
            )
        if event_type == "response.audio.delta":
            pcm = payload.get("pcm")
            if not isinstance(pcm, bytearray) or not pcm:
                raise QwenProtocolError("invalid_audio_delta")
            return ResponseAudioDeltaServerEvent(**arguments, pcm=pcm)
        if event_type == "response.audio_transcript.done":
            transcript = payload.get("transcript")
            if not isinstance(transcript, str):
                raise QwenProtocolError("invalid_transcript")
            return ResponseAudioTranscriptDoneServerEvent(
                **arguments,
                transcript=transcript,
            )
        return ResponseAudioDoneServerEvent(**arguments)
    if event_type == "response.done":
        response = _mapping(payload.get("response"), "invalid_response")
        status = response.get("status")
        if status not in {"completed", "cancelled", "failed"}:
            raise QwenProtocolError("invalid_terminal_status")
        details_value = response.get("status_details")
        reason: object = None
        if details_value is not None:
            details = _mapping(details_value, "invalid_status_details")
            reason = details.get("reason")
        if reason not in {None, "turn_detected", "client_cancelled"}:
            raise QwenProtocolError("invalid_terminal_reason")
        output_value = response.get("output", ())
        output = tuple(
            _parse_item(item)
            for item in _sequence(output_value, "invalid_response_output")
        )
        return ResponseDoneServerEvent(
            event_id=event_id,
            response_id=_nonempty(
                response.get("id"),
                "invalid_response_id",
            ),
            terminal_status=status,
            response_terminal_reason=reason,
            output_items=output,
        )
    if event_type == "error":
        error = _mapping(payload.get("error"), "invalid_error")
        error_type = error.get("type")
        if error_type not in {"invalid_request_error", "server_error"}:
            raise QwenProtocolError("invalid_error_type")
        message = error.get("message", "")
        if not isinstance(message, str):
            raise QwenProtocolError("invalid_error_message")
        return ErrorServerEvent(
            event_id=event_id,
            error_type=error_type,
            error_code=_nonempty(error.get("code"), "invalid_error_code"),
            error_param=_optional_nonempty(
                error.get("param"),
                "invalid_error_param",
            ),
            error_message=message,
        )
    raise QwenProtocolError("unsupported_server_event")


def response_audio_delta(
    *,
    event_id: str,
    response_id: str,
    item_id: str,
    output_index: int,
    content_index: int,
    pcm: bytearray,
) -> ResponseAudioDeltaServerEvent:
    return ResponseAudioDeltaServerEvent(
        event_id=event_id,
        response_id=response_id,
        item_id=item_id,
        output_index=output_index,
        content_index=content_index,
        pcm=pcm,
    )


def safe_wire_metadata(
    event: QwenClientEvent | QwenServerEvent,
) -> dict[str, object]:
    metadata: dict[str, object] = {"type": event.type}
    if hasattr(event, "event_id"):
        metadata["provider_event_id_ref"] = event.event_id
    if hasattr(event, "session_id"):
        metadata["provider_session_ref"] = event.session_id
    if hasattr(event, "response_id"):
        metadata["qwen_response_id"] = event.response_id
    if hasattr(event, "item_id"):
        metadata["qwen_item_ref"] = event.item_id
    if hasattr(event, "previous_item_id") and event.previous_item_id is not None:
        metadata["previous_qwen_item_ref"] = event.previous_item_id
    if hasattr(event, "output_index"):
        metadata["qwen_output_index"] = event.output_index
    if hasattr(event, "content_index"):
        metadata["qwen_content_index"] = event.content_index
    if hasattr(event, "terminal_status"):
        metadata["terminal_status"] = event.terminal_status
    if (
        hasattr(event, "response_terminal_reason")
        and event.response_terminal_reason is not None
    ):
        metadata["terminal_reason"] = event.response_terminal_reason
    if hasattr(event, "stop_reason") and event.stop_reason is not None:
        metadata["terminal_reason"] = event.stop_reason
    if isinstance(
        event,
        (InputAudioBufferAppendClientEvent, ResponseAudioDeltaServerEvent),
    ):
        payload = event.pcm16le if hasattr(event, "pcm16le") else event.pcm
        metadata["byte_count"] = len(payload)
    if isinstance(event, ErrorServerEvent):
        metadata["terminal_status"] = (
            "terminal" if event.terminal else "non_terminal"
        )
    return metadata


__all__ = [
    "AmbientTranscriptionCompletedServerEvent",
    "AmbientTranscriptionDeltaServerEvent",
    "CLIENT_EVENT_TYPES",
    "ConversationItemCreatedServerEvent",
    "ConversationItemDeleteClientEvent",
    "ConversationItemDeletedServerEvent",
    "ErrorServerEvent",
    "InputAudioBufferAppendClientEvent",
    "InputAudioCommittedServerEvent",
    "InputTranscriptionCompletedServerEvent",
    "InputTranscriptionDeltaServerEvent",
    "InputTranscriptionFailedServerEvent",
    "QwenClientEvent",
    "QwenContentPartSnapshot",
    "QwenOutputItemSnapshot",
    "QwenProtocolError",
    "QwenServerEvent",
    "QwenSessionConfiguration",
    "ResponseAudioDeltaServerEvent",
    "ResponseAudioDoneServerEvent",
    "ResponseAudioTranscriptDeltaServerEvent",
    "ResponseAudioTranscriptDoneServerEvent",
    "ResponseCancelClientEvent",
    "ResponseContentPartAddedServerEvent",
    "ResponseContentPartDoneServerEvent",
    "ResponseCreatedServerEvent",
    "ResponseDoneServerEvent",
    "ResponseOutputItemAddedServerEvent",
    "ResponseOutputItemDoneServerEvent",
    "SERVER_EVENT_TYPES",
    "SessionCreatedServerEvent",
    "SessionUpdateClientEvent",
    "SessionUpdatedServerEvent",
    "SpeechStartedServerEvent",
    "SpeechStoppedServerEvent",
    "encode_client_event",
    "parse_server_event",
    "response_audio_delta",
    "safe_wire_metadata",
]
