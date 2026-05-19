#!/usr/bin/env python3
"""Deterministic synthetic PCM fixtures for the Duplex/VAD model spike harness.

The default API returns in-memory sample arrays. Optional WAV export is local
debug only and is restricted to /private/tmp.
"""

from __future__ import annotations

import argparse
import math
import pathlib
import random
import struct
import wave
from dataclasses import dataclass
from typing import Mapping


DEFAULT_SAMPLE_RATE_HZ = 16_000
DEFAULT_SYNTHETIC_SEED = 20_260_511
PRIVATE_TMP = pathlib.Path("/private/tmp").resolve()


@dataclass(frozen=True)
class SyntheticCase:
    name: str
    signal: list[float]
    category: str
    expected_start_ms: int | None = None
    expected_end_ms: int | None = None
    raw_mic_signal: list[float] | None = None
    playback_reference_signal: list[float] | None = None
    fixture_note: str = ""


def samples_for_ms(ms: int, sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ) -> int:
    return int(sample_rate_hz * ms / 1000)


def silence(ms: int, sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ) -> list[float]:
    return [0.0] * samples_for_ms(ms, sample_rate_hz)


def speech_like(
    ms: int,
    *,
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
    amplitude: float = 0.58,
    f0: float = 145.0,
    phase: float = 0.0,
    seed: int = DEFAULT_SYNTHETIC_SEED,
) -> list[float]:
    rng = random.Random(seed)
    total_samples = samples_for_ms(ms, sample_rate_hz)
    fade_samples = max(1, samples_for_ms(12, sample_rate_hz))
    signal: list[float] = []

    for idx in range(total_samples):
        t = idx / sample_rate_hz
        fade = min(1.0, idx / fade_samples, (total_samples - idx - 1) / fade_samples)
        amplitude_mod = 0.72 + 0.18 * math.sin(2 * math.pi * 3.1 * t + phase)
        voiced = 0.0
        for harmonic, weight in (
            (1, 1.0),
            (2, 0.65),
            (3, 0.38),
            (4, 0.24),
            (6, 0.18),
            (8, 0.12),
            (11, 0.08),
        ):
            voiced += weight * math.sin(
                2 * math.pi * f0 * harmonic * t + phase * (harmonic + 1)
            )
        fricative = (rng.random() * 2.0 - 1.0) * 0.025
        value = amplitude * fade * amplitude_mod * ((voiced / 2.65) + fricative)
        signal.append(clamp_sample(value))

    return signal


def tone(
    ms: int,
    *,
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
    amplitude: float = 0.50,
    frequency_hz: float = 440.0,
) -> list[float]:
    return [
        amplitude * math.sin(2 * math.pi * frequency_hz * idx / sample_rate_hz)
        for idx in range(samples_for_ms(ms, sample_rate_hz))
    ]


def white_noise(
    ms: int,
    *,
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
    amplitude: float = 0.10,
    seed: int = DEFAULT_SYNTHETIC_SEED + 1,
) -> list[float]:
    rng = random.Random(seed)
    return [
        amplitude * (2.0 * rng.random() - 1.0)
        for _ in range(samples_for_ms(ms, sample_rate_hz))
    ]


def clamp_sample(value: float) -> float:
    return max(-0.98, min(0.98, value))


def mix(first: list[float], second: list[float]) -> list[float]:
    total_samples = max(len(first), len(second))
    output = [0.0] * total_samples
    for idx in range(total_samples):
        value = 0.0
        if idx < len(first):
            value += first[idx]
        if idx < len(second):
            value += second[idx]
        output[idx] = clamp_sample(value)
    return output


def pad_at(
    signal: list[float],
    offset_ms: int,
    *,
    total_ms: int | None = None,
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
) -> list[float]:
    offset_samples = samples_for_ms(offset_ms, sample_rate_hz)
    total_samples = (
        samples_for_ms(total_ms, sample_rate_hz)
        if total_ms is not None
        else offset_samples + len(signal)
    )
    output = [0.0] * max(total_samples, offset_samples + len(signal))
    for idx, value in enumerate(signal):
        output[offset_samples + idx] = clamp_sample(output[offset_samples + idx] + value)
    return output


def subtract(first: list[float], second: list[float]) -> list[float]:
    total_samples = max(len(first), len(second))
    output = [0.0] * total_samples
    for idx in range(total_samples):
        output[idx] = clamp_sample(
            (first[idx] if idx < len(first) else 0.0)
            - (second[idx] if idx < len(second) else 0.0)
        )
    return output


def pcm16_bytes(signal: list[float]) -> bytes:
    return b"".join(
        struct.pack("<h", int(max(-1.0, min(1.0, sample)) * 32767))
        for sample in signal
    )


def build_synthetic_cases(
    *,
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
    seed: int = DEFAULT_SYNTHETIC_SEED,
) -> dict[str, SyntheticCase]:
    base_speech = speech_like(900, sample_rate_hz=sample_rate_hz, seed=seed)
    short_speech = speech_like(
        180,
        sample_rate_hz=sample_rate_hz,
        f0=165.0,
        phase=0.4,
        seed=seed + 1,
    )
    clipped_full = speech_like(
        900,
        sample_rate_hz=sample_rate_hz,
        f0=150.0,
        phase=0.8,
        seed=seed + 2,
    )
    clipped = clipped_full[samples_for_ms(250, sample_rate_hz) :]

    playback = speech_like(
        2600,
        sample_rate_hz=sample_rate_hz,
        amplitude=0.55,
        f0=135.0,
        phase=1.1,
        seed=seed + 3,
    )
    barge_user = speech_like(
        600,
        sample_rate_hz=sample_rate_hz,
        amplitude=0.56,
        f0=170.0,
        phase=1.8,
        seed=seed + 4,
    )
    near_user = speech_like(
        180,
        sample_rate_hz=sample_rate_hz,
        amplitude=0.56,
        f0=175.0,
        phase=2.1,
        seed=seed + 5,
    )

    playback_only_mic = playback
    playback_only_residual = subtract(playback_only_mic, playback)
    barge_mic = mix(
        playback,
        pad_at(barge_user, 1000, total_ms=2600, sample_rate_hz=sample_rate_hz),
    )
    barge_residual = subtract(barge_mic, playback)
    near_mic = mix(
        playback,
        pad_at(near_user, 2200, total_ms=2600, sample_rate_hz=sample_rate_hz),
    )
    near_residual = subtract(near_mic, playback)

    return {
        "speech_start_clean": SyntheticCase(
            name="speech_start_clean",
            signal=silence(500, sample_rate_hz) + base_speech + silence(500, sample_rate_hz),
            category="speech",
            expected_start_ms=500,
            expected_end_ms=1400,
            fixture_note="clean synthetic speech-like onset",
        ),
        "speech_end_clean": SyntheticCase(
            name="speech_end_clean",
            signal=silence(500, sample_rate_hz) + base_speech + silence(500, sample_rate_hz),
            category="speech",
            expected_start_ms=500,
            expected_end_ms=1400,
            fixture_note="same signal as clean start; used for end/hangover",
        ),
        "short_backchannel": SyntheticCase(
            name="short_backchannel",
            signal=silence(300, sample_rate_hz)
            + short_speech
            + silence(300, sample_rate_hz),
            category="speech",
            expected_start_ms=300,
            expected_end_ms=480,
            fixture_note="short 180 ms synthetic utterance",
        ),
        "silence_only": SyntheticCase(
            name="silence_only",
            signal=silence(2000, sample_rate_hz),
            category="non_speech",
            fixture_note="two seconds of silence",
        ),
        "noise_or_tone": SyntheticCase(
            name="noise_or_tone",
            signal=silence(500, sample_rate_hz)
            + tone(1000, sample_rate_hz=sample_rate_hz)
            + silence(500, sample_rate_hz),
            category="non_speech",
            fixture_note="pure tone false-positive probe",
        ),
        "white_noise": SyntheticCase(
            name="white_noise",
            signal=silence(500, sample_rate_hz)
            + white_noise(1000, sample_rate_hz=sample_rate_hz, seed=seed + 6)
            + silence(500, sample_rate_hz),
            category="non_speech",
            fixture_note="seeded broadband noise false-positive probe",
        ),
        "clipped_start": SyntheticCase(
            name="clipped_start",
            signal=silence(300, sample_rate_hz) + clipped + silence(500, sample_rate_hz),
            category="speech",
            expected_start_ms=300,
            expected_end_ms=950,
            fixture_note="speech-like waveform with initial 250 ms removed",
        ),
        "tts_playback_only": SyntheticCase(
            name="tts_playback_only",
            signal=playback_only_residual,
            raw_mic_signal=playback_only_mic,
            playback_reference_signal=playback,
            category="playback_only",
            fixture_note="synthetic playback reference subtracted from synthetic mic",
        ),
        "user_barge_in_over_tts": SyntheticCase(
            name="user_barge_in_over_tts",
            signal=barge_residual,
            raw_mic_signal=barge_mic,
            playback_reference_signal=playback,
            category="overlap",
            expected_start_ms=1000,
            expected_end_ms=1600,
            fixture_note="synthetic user speech over playback after residual subtraction",
        ),
        "near_end_barge_in": SyntheticCase(
            name="near_end_barge_in",
            signal=near_residual,
            raw_mic_signal=near_mic,
            playback_reference_signal=playback,
            category="overlap",
            expected_start_ms=2200,
            expected_end_ms=2380,
            fixture_note="short near-end synthetic user speech over playback",
        ),
        "client_stop_playback_simulation": SyntheticCase(
            name="client_stop_playback_simulation",
            signal=[],
            category="metadata_only",
            fixture_note="offset metadata only; no VAD decision",
        ),
    }


def require_private_tmp(path: pathlib.Path) -> pathlib.Path:
    resolved = path.expanduser().resolve()
    if resolved != PRIVATE_TMP and PRIVATE_TMP not in resolved.parents:
        raise ValueError(f"local audio export must stay under {PRIVATE_TMP}: {resolved}")
    return resolved


def write_cases_to_wav(
    cases: Mapping[str, SyntheticCase],
    output_dir: pathlib.Path,
    *,
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
) -> dict[str, pathlib.Path]:
    safe_output_dir = require_private_tmp(output_dir)
    safe_output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, pathlib.Path] = {}

    for name, case in cases.items():
        if not case.signal:
            continue
        path = safe_output_dir / f"{name}.wav"
        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate_hz)
            wav_file.writeframes(pcm16_bytes(case.signal))
        written[name] = path

    return written


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-rate-hz", type=int, default=DEFAULT_SAMPLE_RATE_HZ)
    parser.add_argument("--seed", type=int, default=DEFAULT_SYNTHETIC_SEED)
    parser.add_argument("--write-local-wav-dir", type=pathlib.Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cases = build_synthetic_cases(sample_rate_hz=args.sample_rate_hz, seed=args.seed)
    print(f"generated_cases={len(cases)}")
    print("case_names=" + ",".join(sorted(cases)))
    if args.write_local_wav_dir:
        written = write_cases_to_wav(
            cases,
            args.write_local_wav_dir,
            sample_rate_hz=args.sample_rate_hz,
        )
        print(f"wrote_local_wavs={len(written)}")
        print(f"local_wav_dir={args.write_local_wav_dir.expanduser().resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
