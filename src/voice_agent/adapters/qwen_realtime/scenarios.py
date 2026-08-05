from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal


_MAX_SAFE_REF_LENGTH = 64
_MAX_SYNTHETIC_BYTE_COUNT = 64_000
_MAX_SYNTHETIC_DURATION_MS = 2_000


def _is_safe_opaque_ref(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= _MAX_SAFE_REF_LENGTH
        and value[0] in "abcdefghijklmnopqrstuvwxyz"
        and all(
            character in "abcdefghijklmnopqrstuvwxyz0123456789_"
            for character in value
        )
    )


def _require_safe_ref(value: object) -> str:
    if not _is_safe_opaque_ref(value):
        raise ValueError("invalid_qwen_wire_ref")
    assert isinstance(value, str)
    return value


def _nonnegative_count(value: object, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("invalid_qwen_wire_count")
    if value < 0 or value > maximum:
        raise ValueError("invalid_qwen_wire_count")
    return value


class SyntheticPayloadKind(str, Enum):
    NONE = "NONE"
    SESSION_DEFAULTS = "SESSION_DEFAULTS"
    SESSION_CONFIGURATION_ECHO = "SESSION_CONFIGURATION_ECHO"
    PCM_FRAME = "PCM_FRAME"
    TRANSCRIPT_FRAGMENT = "TRANSCRIPT_FRAGMENT"


@dataclass(frozen=True, slots=True)
class ClientEventTemplate:
    event_type: Literal[
        "session.update",
        "input_audio_buffer.append",
        "response.cancel",
        "conversation.item.delete",
    ]
    payload_kind: SyntheticPayloadKind = SyntheticPayloadKind.NONE
    item_id: str | None = None

    def __post_init__(self) -> None:
        expected_kind = {
            "session.update": SyntheticPayloadKind.NONE,
            "input_audio_buffer.append": SyntheticPayloadKind.PCM_FRAME,
            "response.cancel": SyntheticPayloadKind.NONE,
            "conversation.item.delete": SyntheticPayloadKind.NONE,
        }
        if (
            self.event_type not in expected_kind
            or self.payload_kind is not expected_kind[self.event_type]
        ):
            raise ValueError("invalid_qwen_client_template")
        if self.event_type == "conversation.item.delete":
            _require_safe_ref(self.item_id)
        elif self.item_id is not None:
            raise ValueError("invalid_qwen_client_template")


@dataclass(frozen=True, slots=True)
class ServerEventTemplate:
    event_type: Literal[
        "session.created",
        "session.updated",
        "response.audio.delta",
        "response.audio_transcript.delta",
        "response.done",
    ]
    payload_kind: SyntheticPayloadKind
    event_id: str
    session_id: str | None = None
    response_id: str | None = None
    item_id: str | None = None
    output_index: int | None = None
    content_index: int | None = None
    byte_count: int = 0
    duration_ms: int = 0
    terminal_status: Literal["completed", "cancelled", "failed"] | None = None

    def __post_init__(self) -> None:
        expected_kind = {
            "session.created": SyntheticPayloadKind.SESSION_DEFAULTS,
            "session.updated": SyntheticPayloadKind.SESSION_CONFIGURATION_ECHO,
            "response.audio.delta": SyntheticPayloadKind.PCM_FRAME,
            "response.audio_transcript.delta": SyntheticPayloadKind.TRANSCRIPT_FRAGMENT,
            "response.done": SyntheticPayloadKind.NONE,
        }
        if (
            self.event_type not in expected_kind
            or self.payload_kind is not expected_kind[self.event_type]
        ):
            raise ValueError("invalid_qwen_server_template")
        _require_safe_ref(self.event_id)
        for value in (self.session_id, self.response_id, self.item_id):
            if value is not None:
                _require_safe_ref(value)
        byte_count = _nonnegative_count(
            self.byte_count,
            maximum=_MAX_SYNTHETIC_BYTE_COUNT,
        )
        duration_ms = _nonnegative_count(
            self.duration_ms,
            maximum=_MAX_SYNTHETIC_DURATION_MS,
        )
        if self.output_index is not None:
            _nonnegative_count(self.output_index, maximum=_MAX_SYNTHETIC_BYTE_COUNT)
        if self.content_index is not None:
            _nonnegative_count(self.content_index, maximum=_MAX_SYNTHETIC_BYTE_COUNT)
        if self.event_type in {"session.created", "session.updated"}:
            if (
                self.session_id is None
                or self.response_id is not None
                or self.item_id is not None
                or self.output_index is not None
                or self.content_index is not None
                or byte_count
                or duration_ms
                or self.terminal_status is not None
            ):
                raise ValueError("invalid_qwen_server_template")
            return
        if self.event_type == "response.done":
            if (
                self.response_id is None
                or self.session_id is not None
                or self.item_id is not None
                or self.output_index is not None
                or self.content_index is not None
                or byte_count
                or duration_ms
                or self.terminal_status not in {"completed", "cancelled", "failed"}
            ):
                raise ValueError("invalid_qwen_server_template")
            return
        if (
            self.response_id is None
            or self.item_id is None
            or self.output_index is None
            or self.content_index is None
            or self.session_id is not None
            or self.terminal_status is not None
        ):
            raise ValueError("invalid_qwen_server_template")
        if self.event_type == "response.audio.delta":
            if byte_count == 0 or duration_ms == 0:
                raise ValueError("invalid_qwen_server_template")
        elif byte_count or duration_ms:
            raise ValueError("invalid_qwen_server_template")


@dataclass(frozen=True, slots=True)
class WireStep:
    wire_seq: int
    virtual_ms: int
    direction: Literal["client", "server"]
    event_template: ClientEventTemplate | ServerEventTemplate

    def __post_init__(self) -> None:
        _nonnegative_count(self.wire_seq, maximum=_MAX_SYNTHETIC_BYTE_COUNT)
        _nonnegative_count(self.virtual_ms, maximum=_MAX_SYNTHETIC_DURATION_MS)
        if self.direction not in {"client", "server"}:
            raise ValueError("invalid_qwen_wire_step")
        expected = (
            ClientEventTemplate if self.direction == "client" else ServerEventTemplate
        )
        if not isinstance(self.event_template, expected):
            raise ValueError("invalid_qwen_wire_step")


@dataclass(frozen=True, slots=True)
class QwenWireScript:
    scenario_id: str
    steps: tuple[WireStep, ...]
    fixture_domain: Literal["GITHUB_ALLOWED"] = "GITHUB_ALLOWED"
    generated_from: Literal["synthetic"] = "synthetic"
    scenario_source: Literal["SYNTHETIC"] = "SYNTHETIC"

    def __post_init__(self) -> None:
        _require_safe_ref(self.scenario_id)
        if (
            self.fixture_domain != "GITHUB_ALLOWED"
            or self.generated_from != "synthetic"
            or self.scenario_source != "SYNTHETIC"
        ):
            raise ValueError("invalid_qwen_wire_script")
        try:
            normalized_steps = tuple(self.steps)
        except TypeError as error:
            raise ValueError("invalid_qwen_wire_script") from error
        if not normalized_steps:
            raise ValueError("invalid_qwen_wire_script")
        object.__setattr__(self, "steps", normalized_steps)
        prior_seq = -1
        prior_ms = -1
        for step in normalized_steps:
            if not isinstance(step, WireStep):
                raise ValueError("invalid_qwen_wire_script")
            if step.wire_seq <= prior_seq or step.virtual_ms < prior_ms:
                raise ValueError("invalid_qwen_wire_script")
            prior_seq = step.wire_seq
            prior_ms = step.virtual_ms


_SESSION_ID = "sess_fake_001"


def _bootstrap_steps(*, append_count: int, include_cancel_tail: bool) -> tuple[WireStep, ...]:
    steps: list[WireStep] = [
        WireStep(
            wire_seq=0,
            virtual_ms=0,
            direction="server",
            event_template=ServerEventTemplate(
                event_type="session.created",
                payload_kind=SyntheticPayloadKind.SESSION_DEFAULTS,
                event_id="evt_fake_001",
                session_id=_SESSION_ID,
            ),
        ),
        WireStep(
            wire_seq=1,
            virtual_ms=1,
            direction="client",
            event_template=ClientEventTemplate(event_type="session.update"),
        ),
        WireStep(
            wire_seq=2,
            virtual_ms=2,
            direction="server",
            event_template=ServerEventTemplate(
                event_type="session.updated",
                payload_kind=SyntheticPayloadKind.SESSION_CONFIGURATION_ECHO,
                event_id="evt_fake_002",
                session_id=_SESSION_ID,
            ),
        ),
    ]
    for offset in range(append_count):
        steps.append(
            WireStep(
                wire_seq=3 + offset,
                virtual_ms=3 + offset,
                direction="client",
                event_template=ClientEventTemplate(
                    event_type="input_audio_buffer.append",
                    payload_kind=SyntheticPayloadKind.PCM_FRAME,
                ),
            )
        )
    if include_cancel_tail:
        tail_seq = 3 + append_count
        steps.extend(
            (
                WireStep(
                    wire_seq=tail_seq,
                    virtual_ms=tail_seq,
                    direction="client",
                    event_template=ClientEventTemplate(event_type="response.cancel"),
                ),
                WireStep(
                    wire_seq=tail_seq + 1,
                    virtual_ms=tail_seq + 1,
                    direction="client",
                    event_template=ClientEventTemplate(
                        event_type="conversation.item.delete",
                        item_id="output_item_1",
                    ),
                ),
            )
        )
    return tuple(steps)


_SCRIPTS = {
    "bootstrap_requires_session_update": QwenWireScript(
        scenario_id="bootstrap_requires_session_update",
        steps=_bootstrap_steps(append_count=0, include_cancel_tail=False),
    ),
    "multiple_audio_appends_without_ack": QwenWireScript(
        scenario_id="multiple_audio_appends_without_ack",
        steps=_bootstrap_steps(append_count=2, include_cancel_tail=True),
    ),
    "transport_contract_client_sequence": QwenWireScript(
        scenario_id="transport_contract_client_sequence",
        steps=_bootstrap_steps(append_count=1, include_cancel_tail=True),
    ),
}


def get_qwen_wire_script(scenario_id: str) -> QwenWireScript:
    try:
        return _SCRIPTS[scenario_id]
    except (KeyError, TypeError) as error:
        raise ValueError("unknown_qwen_wire_scenario") from error


__all__ = [
    "ClientEventTemplate",
    "QwenWireScript",
    "ServerEventTemplate",
    "SyntheticPayloadKind",
    "WireStep",
    "get_qwen_wire_script",
]
