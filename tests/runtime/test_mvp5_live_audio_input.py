from __future__ import annotations

import json
from pathlib import Path
import wave

import pytest

from voice_agent.runtime.mvp5_live_audio_input import (
    LocalWavInputError,
    load_local_wav_input,
    validate_mvp5_audio_metadata_for_export,
)


def test_local_wav_loading_fails_closed_without_explicit_opt_in(tmp_path: Path) -> None:
    missing_wav = tmp_path / "missing-local-input.wav"

    with pytest.raises(LocalWavInputError, match="allow_local_wav"):
        load_local_wav_input(missing_wav)


def test_local_wav_opt_in_returns_path_redacted_metadata_and_local_only_handle(tmp_path: Path) -> None:
    wav_path = tmp_path / "safety-test-input.wav"
    wav_bytes = _write_wav_file(wav_path, sample_rate_hz=8000, channel_count=1, frame_count=800)

    loaded = load_local_wav_input(wav_path, allow_local_wav=True)

    metadata = loaded.to_metadata()
    rendered_metadata = json.dumps(metadata, sort_keys=True)
    assert metadata["input_source"] == "local_wav_opt_in"
    assert metadata["local_raw_audio_domain"] == "LOCAL_RAW_AUDIO"
    assert metadata["audio_mime_type"] == "audio/wav"
    assert metadata["duration_ms"] == 100
    assert metadata["sample_rate_hz"] == 8000
    assert metadata["channel_count"] == 1
    assert metadata["frame_count"] == 800
    assert metadata["safe_audio_ref"].startswith("local-audio://mvp5/")
    assert metadata["replay_export_allowed"] is False
    assert metadata["raw_audio_included"] is False
    assert metadata["local_wav_path_included"] is False
    assert metadata["file_name_included"] is False

    assert str(wav_path) not in rendered_metadata
    assert str(tmp_path) not in rendered_metadata
    assert wav_path.name not in rendered_metadata
    assert "safety-test-input" not in repr(loaded)
    assert loaded.audio_handle.open_bytes().read() == wav_bytes


def test_local_wav_gate_rejects_data_uri_and_file_uri_refs(tmp_path: Path) -> None:
    wav_path = tmp_path / "input.wav"
    _write_wav_file(wav_path)

    for unsafe_ref in (
        "data:audio/wav;base64,REDACTED",
        f"file://{wav_path}",
        "mic://default",
    ):
        with pytest.raises(LocalWavInputError, match="unsupported audio input ref"):
            load_local_wav_input(unsafe_ref, allow_local_wav=True)


def test_audio_metadata_export_gate_rejects_path_like_and_raw_audio_fields(tmp_path: Path) -> None:
    wav_path = tmp_path / "safe.wav"
    _write_wav_file(wav_path)
    loaded = load_local_wav_input(wav_path, allow_local_wav=True)

    validate_mvp5_audio_metadata_for_export(loaded.to_metadata())

    unsafe_metadata = dict(loaded.to_metadata())
    unsafe_metadata["safe_audio_ref"] = f"file://{wav_path}"
    with pytest.raises(LocalWavInputError, match="safe_audio_ref"):
        validate_mvp5_audio_metadata_for_export(unsafe_metadata)

    unsafe_metadata = dict(loaded.to_metadata())
    unsafe_metadata["raw_audio_bytes"] = b"RIFF"
    with pytest.raises(LocalWavInputError, match="raw_audio_bytes"):
        validate_mvp5_audio_metadata_for_export(unsafe_metadata)

    unsafe_metadata = dict(loaded.to_metadata())
    unsafe_metadata["local_wav_path_included"] = True
    with pytest.raises(LocalWavInputError, match="local_wav_path_included"):
        validate_mvp5_audio_metadata_for_export(unsafe_metadata)


def _write_wav_file(
    path: Path,
    *,
    sample_rate_hz: int = 16000,
    channel_count: int = 1,
    frame_count: int = 160,
) -> bytes:
    sample_width_bytes = 2
    silent_frame = b"\x00" * sample_width_bytes * channel_count
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channel_count)
        wav_file.setsampwidth(sample_width_bytes)
        wav_file.setframerate(sample_rate_hz)
        wav_file.writeframes(silent_frame * frame_count)
    return path.read_bytes()
