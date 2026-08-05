from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Literal, Protocol


_POSITIVE_INTEGER_FIELDS = frozenset(
    {
        "provider_session_generation",
        "transcript_unicode_scalar_count",
        "candidate_unicode_scalar_count",
        "candidate_audio_duration_ms",
    }
)
_NONNEGATIVE_INTEGER_FIELDS = frozenset(
    {
        "observed_audio_sample_offset",
        "qwen_input_content_index",
        "playback_epoch",
        "interaction_state_version",
        "dropped_audio_frame_count",
        "qwen_output_index",
        "qwen_content_index",
        "bound_playback_epoch",
    }
)
_OPTIONAL_STRING_FIELDS_BY_TYPE = {
    "SpeechBoundaryProjectionV1": frozenset({"stop_reason"}),
    "CandidateObservationProjectionV1": frozenset(
        {
            "candidate_ref",
            "candidate_transcript_digest",
            "candidate_pcm_manifest_digest",
        }
    ),
}


def _validate_projection(instance: object) -> None:
    optional_strings = _OPTIONAL_STRING_FIELDS_BY_TYPE.get(
        type(instance).__name__,
        frozenset(),
    )
    for definition in fields(instance):
        name = definition.name
        value = getattr(instance, name)
        if name in _POSITIVE_INTEGER_FIELDS:
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"invalid_{name}")
        elif name in _NONNEGATIVE_INTEGER_FIELDS:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"invalid_{name}")
        elif name == "source_event_id_refs":
            if (
                not isinstance(value, tuple)
                or not value
                or any(not isinstance(item, str) or not item.strip() for item in value)
            ):
                raise ValueError("invalid_source_event_id_refs")
        elif name == "reason" or name.endswith(
            ("_id", "_ref", "_digest", "_state", "_reason")
        ):
            if value is None and name in optional_strings:
                continue
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"invalid_{name}")


@dataclass(frozen=True, slots=True)
class SpeechBoundaryProjectionV1:
    provider_session_generation: int
    boundary: Literal["STARTED", "STOPPED"]
    qwen_input_item_ref: str
    observed_audio_sample_offset: int
    stop_reason: str | None = None

    def __post_init__(self) -> None:
        _validate_projection(self)
        if self.boundary not in {"STARTED", "STOPPED"}:
            raise ValueError("invalid_boundary")
        if self.boundary == "STARTED" and self.stop_reason is not None:
            raise ValueError("invalid_stop_reason")


@dataclass(frozen=True, slots=True)
class FinalASRReadyProjectionV1:
    provider_session_generation: int
    qwen_input_item_ref: str
    qwen_input_content_index: int
    turn_id: str
    utterance_id: str
    transcript_ref: str
    transcript_digest: str
    transcript_unicode_scalar_count: int

    def __post_init__(self) -> None:
        _validate_projection(self)


@dataclass(frozen=True, slots=True)
class AmbientTerminalProjectionV1:
    provider_session_generation: int
    temporary_item_ref: str
    terminal_status: Literal["completed", "failed"]

    def __post_init__(self) -> None:
        _validate_projection(self)
        if self.terminal_status not in {"completed", "failed"}:
            raise ValueError("invalid_terminal_status")


@dataclass(frozen=True, slots=True)
class ProviderContextProjectionV1:
    provider_session_generation: int
    playback_epoch: int
    interaction_state_version: int
    from_state: str
    to_state: str
    reason: str
    dropped_audio_frame_count: int

    def __post_init__(self) -> None:
        _validate_projection(self)


@dataclass(frozen=True, slots=True)
class RebuildRequestedProjectionV1:
    provider_session_generation: int
    reason: str
    source_event_id_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_projection(self)


@dataclass(frozen=True, slots=True)
class CandidateObservationProjectionV1:
    provider_session_generation: int
    candidate_id: str
    qwen_response_id: str
    observation: Literal["OPENED", "DISCARDED", "CANCELLED"]
    candidate_ref: str | None = None
    candidate_transcript_digest: str | None = None
    candidate_pcm_manifest_digest: str | None = None

    def __post_init__(self) -> None:
        _validate_projection(self)
        if self.observation not in {"OPENED", "DISCARDED", "CANCELLED"}:
            raise ValueError("invalid_observation")


@dataclass(frozen=True, slots=True)
class CandidateEligibilityFactsV1:
    provider_session_generation: int
    qwen_response_id: str
    qwen_output_item_id: str
    qwen_output_index: int
    qwen_content_index: int
    candidate_id: str
    turn_id: str
    utterance_id: str
    context_snapshot_id: str
    bound_playback_epoch: int
    candidate_transcript_digest: str
    candidate_unicode_scalar_count: int
    candidate_pcm_manifest_digest: str
    candidate_audio_format_ref: str
    candidate_audio_duration_ms: int
    provider_terminal_status: Literal["completed"]

    def __post_init__(self) -> None:
        _validate_projection(self)
        if self.provider_terminal_status != "completed":
            raise ValueError("invalid_provider_terminal_status")


@dataclass(frozen=True, slots=True)
class CandidateTranscriptCompleteV1:
    provider_session_generation: int
    qwen_response_id: str
    candidate_id: str
    turn_id: str
    utterance_id: str
    context_snapshot_id: str
    candidate_ref: str = field(repr=False)
    candidate_transcript_digest: str
    candidate_unicode_scalar_count: int

    def __post_init__(self) -> None:
        _validate_projection(self)


@dataclass(frozen=True, slots=True)
class CandidateCompletionV1:
    candidate_ref: str = field(repr=False)
    eligibility_facts: CandidateEligibilityFactsV1

    def __post_init__(self) -> None:
        _validate_projection(self)
        if not isinstance(self.eligibility_facts, CandidateEligibilityFactsV1):
            raise TypeError("invalid_eligibility_facts")


QwenProjectionFrameV1 = (
    SpeechBoundaryProjectionV1
    | FinalASRReadyProjectionV1
    | AmbientTerminalProjectionV1
    | ProviderContextProjectionV1
    | RebuildRequestedProjectionV1
    | CandidateObservationProjectionV1
    | CandidateTranscriptCompleteV1
    | CandidateCompletionV1
)


class QwenProjectionSink(Protocol):
    async def accept(self, frame: QwenProjectionFrameV1) -> None: ...


__all__ = [
    "AmbientTerminalProjectionV1",
    "CandidateCompletionV1",
    "CandidateEligibilityFactsV1",
    "CandidateObservationProjectionV1",
    "CandidateTranscriptCompleteV1",
    "FinalASRReadyProjectionV1",
    "ProviderContextProjectionV1",
    "QwenProjectionFrameV1",
    "QwenProjectionSink",
    "RebuildRequestedProjectionV1",
    "SpeechBoundaryProjectionV1",
]
