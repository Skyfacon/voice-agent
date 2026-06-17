from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import io
from pathlib import Path
import re
from typing import Any
import wave


class LocalWavInputError(ValueError):
    """Raised when MVP-5 local audio input fails closed."""


_UNSUPPORTED_REF_PREFIXES = ("data:", "file://", "mic://", "microphone://")
_UNSAFE_STRING_MARKERS = (
    "data:",
    "file://",
    "/Users/",
    "audio/raw/",
    "diagnostics/",
    "traces/",
    "replays/local/",
    ".env",
)
_FORBIDDEN_EXPORT_KEYS = {
    "audio_bytes",
    "raw_audio_bytes",
    "wav_bytes",
    "pcm_samples",
    "local_path",
    "local_wav_path",
    "absolute_path",
    "file_name",
    "filename",
}
_BOOLEAN_FALSE_EXPORT_FLAGS = {
    "raw_audio_included",
    "local_wav_path_included",
    "file_name_included",
}


@dataclass(frozen=True)
class LocalOnlyAudioHandle:
    _audio_bytes: bytes
    audio_mime_type: str
    safe_audio_ref: str

    def open_bytes(self) -> io.BytesIO:
        return io.BytesIO(self._audio_bytes)

    @property
    def byte_length(self) -> int:
        return len(self._audio_bytes)

    def __repr__(self) -> str:
        return (
            "LocalOnlyAudioHandle("
            f"audio_mime_type={self.audio_mime_type!r}, "
            f"byte_length={self.byte_length}, "
            f"safe_audio_ref={self.safe_audio_ref!r}, "
            "local_path_redacted=True)"
        )


@dataclass(frozen=True)
class MVP5LocalWavInput:
    duration_ms: int
    sample_rate_hz: int
    channel_count: int
    sample_width_bytes: int
    frame_count: int
    safe_audio_ref: str
    audio_handle: LocalOnlyAudioHandle

    def to_metadata(self) -> dict[str, object]:
        return {
            "input_source": "local_wav_opt_in",
            "local_raw_audio_domain": "LOCAL_RAW_AUDIO",
            "audio_mime_type": self.audio_handle.audio_mime_type,
            "duration_ms": self.duration_ms,
            "sample_rate_hz": self.sample_rate_hz,
            "channel_count": self.channel_count,
            "sample_width_bytes": self.sample_width_bytes,
            "frame_count": self.frame_count,
            "byte_length": self.audio_handle.byte_length,
            "safe_audio_ref": self.safe_audio_ref,
            "replay_export_allowed": False,
            "raw_audio_included": False,
            "local_wav_path_included": False,
            "file_name_included": False,
            "data_uri_supported": False,
            "file_uri_supported": False,
            "realtime_mic_supported": False,
        }

    def __repr__(self) -> str:
        return (
            "MVP5LocalWavInput("
            f"duration_ms={self.duration_ms}, "
            f"sample_rate_hz={self.sample_rate_hz}, "
            f"channel_count={self.channel_count}, "
            f"safe_audio_ref={self.safe_audio_ref!r}, "
            "local_path_redacted=True)"
        )


def load_local_wav_input(
    local_wav: str | Path,
    *,
    allow_local_wav: bool = False,
) -> MVP5LocalWavInput:
    if not allow_local_wav:
        raise LocalWavInputError("allow_local_wav=True is required before reading local wav input")

    path = _coerce_local_wav_path(local_wav)
    if path.suffix.lower() != ".wav":
        raise LocalWavInputError("local audio input must be a wav file")
    if not path.is_file():
        raise LocalWavInputError("local wav file is missing or unreadable")

    audio_bytes = path.read_bytes()
    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
            channel_count = wav_file.getnchannels()
            sample_width_bytes = wav_file.getsampwidth()
            sample_rate_hz = wav_file.getframerate()
            frame_count = wav_file.getnframes()
    except (EOFError, wave.Error) as exc:
        raise LocalWavInputError("local wav metadata could not be parsed") from exc

    if sample_rate_hz <= 0:
        raise LocalWavInputError("local wav sample rate must be positive")
    duration_ms = round((frame_count / sample_rate_hz) * 1000)
    safe_audio_ref = _safe_audio_ref(audio_bytes)
    handle = LocalOnlyAudioHandle(
        _audio_bytes=audio_bytes,
        audio_mime_type="audio/wav",
        safe_audio_ref=safe_audio_ref,
    )
    loaded = MVP5LocalWavInput(
        duration_ms=duration_ms,
        sample_rate_hz=sample_rate_hz,
        channel_count=channel_count,
        sample_width_bytes=sample_width_bytes,
        frame_count=frame_count,
        safe_audio_ref=safe_audio_ref,
        audio_handle=handle,
    )
    validate_mvp5_audio_metadata_for_export(loaded.to_metadata())
    return loaded


def validate_mvp5_audio_metadata_for_export(metadata: Mapping[str, Any]) -> None:
    for key in _FORBIDDEN_EXPORT_KEYS:
        if key in metadata:
            raise LocalWavInputError(f"{key} is not allowed in MVP-5 audio metadata")
    for flag in _BOOLEAN_FALSE_EXPORT_FLAGS:
        if metadata.get(flag) is not False:
            raise LocalWavInputError(f"{flag} must be false in MVP-5 audio metadata")
    _reject_unsafe_values(metadata)


def _coerce_local_wav_path(local_wav: str | Path) -> Path:
    local_wav_text = str(local_wav)
    if local_wav_text.lower().startswith(_UNSUPPORTED_REF_PREFIXES):
        raise LocalWavInputError("unsupported audio input ref for MVP-5 local wav gate")
    return Path(local_wav)


def _safe_audio_ref(audio_bytes: bytes) -> str:
    digest = hashlib.sha256(audio_bytes).hexdigest()[:16]
    return f"local-audio://mvp5/{digest}"


def _reject_unsafe_values(value: Any, *, field_path: str = "metadata") -> None:
    if isinstance(value, bytes):
        raise LocalWavInputError(f"{field_path} raw bytes are not allowed in MVP-5 audio metadata")
    if isinstance(value, str):
        _reject_unsafe_string(value, field_path=field_path)
        return
    if isinstance(value, Mapping):
        for child_key, child_value in value.items():
            child_path = f"{field_path}.{child_key}"
            if str(child_key) in _FORBIDDEN_EXPORT_KEYS:
                raise LocalWavInputError(f"{child_key} is not allowed in MVP-5 audio metadata")
            _reject_unsafe_values(child_value, field_path=child_path)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _reject_unsafe_values(item, field_path=f"{field_path}[{index}]")


def _reject_unsafe_string(value: str, *, field_path: str) -> None:
    lowered = value.lower()
    for marker in _UNSAFE_STRING_MARKERS:
        if marker.lower() in lowered:
            raise LocalWavInputError(
                f"{field_path} unsafe string marker is not allowed in MVP-5 audio metadata"
            )
    if value.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", value):
        raise LocalWavInputError(
            f"{field_path} absolute local paths are not allowed in MVP-5 audio metadata"
        )
