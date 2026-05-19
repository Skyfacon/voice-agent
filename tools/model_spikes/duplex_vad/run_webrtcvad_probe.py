#!/usr/bin/env python3
"""Run the spike-local WebRTC VAD probe and emit metadata-only JSONL."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import uuid
from typing import Any, Iterable

import generate_synthetic_audio as synth


DEFAULT_CONTRACT_SNAPSHOT = "main@61e6afc"
DEFAULT_CANDIDATE = "webrtcvad"
DEFAULT_FRAME_MS = (10, 20, 30)
DEFAULT_MODES = (0, 2, 3)
DEFAULT_START_CONSECUTIVE_FRAMES = 2
DEFAULT_END_HANGOVER_FRAMES = 10
OBSERVATION_SCHEMA_VERSION = "duplex_vad_observation.v1"


def parse_int_list(raw: str) -> list[int]:
    values: list[int] = []
    for part in raw.split(","):
        stripped = part.strip()
        if not stripped:
            continue
        values.append(int(stripped))
    if not values:
        raise ValueError("expected at least one integer")
    return values


def load_webrtcvad() -> Any:
    try:
        import webrtcvad  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "webrtcvad is required for this probe. Install it in a temporary "
            "environment, for example: python -m pip install -r "
            "tools/model_spikes/duplex_vad/requirements.txt"
        ) from exc
    return webrtcvad


def observe_signal(
    signal: list[float],
    *,
    frame_ms: int,
    mode: int,
    sample_rate_hz: int,
    expected_start_ms: int | None,
    expected_end_ms: int | None,
) -> dict[str, int | float | None]:
    webrtcvad = load_webrtcvad()
    vad = webrtcvad.Vad(mode)
    raw = synth.pcm16_bytes(signal)
    frame_samples = synth.samples_for_ms(frame_ms, sample_rate_hz)
    frame_bytes = frame_samples * 2

    if frame_bytes <= 0:
        raise ValueError(f"invalid frame_ms={frame_ms}")
    if raw and len(raw) % frame_bytes:
        raw += b"\x00" * (frame_bytes - len(raw) % frame_bytes)

    flags: list[bool] = []
    for offset in range(0, len(raw), frame_bytes):
        flags.append(vad.is_speech(raw[offset : offset + frame_bytes], sample_rate_hz))

    start_idx: int | None = None
    emit_idx: int | None = None
    consecutive = 0
    for idx, flag in enumerate(flags):
        consecutive = consecutive + 1 if flag else 0
        if consecutive >= DEFAULT_START_CONSECUTIVE_FRAMES:
            start_idx = idx - DEFAULT_START_CONSECUTIVE_FRAMES + 1
            emit_idx = idx + 1
            break

    active_indices = [idx for idx, flag in enumerate(flags) if flag]
    start_ms = start_idx * frame_ms if start_idx is not None else None
    emit_ms = emit_idx * frame_ms if emit_idx is not None else None
    end_ms = (active_indices[-1] + 1) * frame_ms if active_indices else None

    return {
        "speech_start_ms": start_ms,
        "speech_start_emit_latency_ms": (
            emit_ms - expected_start_ms
            if emit_ms is not None and expected_start_ms is not None
            else None
        ),
        "speech_end_ms": end_ms,
        "speech_end_offset_error_ms": (
            end_ms - expected_end_ms
            if end_ms is not None and expected_end_ms is not None
            else None
        ),
        "speech_end_hangover_ms": (
            DEFAULT_END_HANGOVER_FRAMES * frame_ms if end_ms is not None else None
        ),
        "vad_confidence_summary": (
            round(sum(1 for flag in flags if flag) / len(flags), 3) if flags else 0.0
        ),
        "active_frame_count": sum(1 for flag in flags if flag),
        "total_frame_count": len(flags),
    }


def output_mode_for_case(case: synth.SyntheticCase) -> str:
    if case.category in {"playback_only", "overlap"}:
        return "degraded"
    return "real"


def echo_likelihood_mode_for_case(case: synth.SyntheticCase) -> str:
    if case.category in {"playback_only", "overlap"}:
        return "degraded_playback_reference_required"
    return "not_applicable"


def playback_reference_residual_for_case(case: synth.SyntheticCase) -> str:
    if case.category in {"playback_only", "overlap"}:
        return "idealized_subtraction"
    return "not_applicable"


def observation_for_case(
    case: synth.SyntheticCase,
    *,
    contract_snapshot: str,
    frame_ms: int,
    mode: int,
    synthetic_seed: int,
    sample_rate_hz: int,
) -> dict[str, Any]:
    observed = observe_signal(
        case.signal,
        frame_ms=frame_ms,
        mode=mode,
        sample_rate_hz=sample_rate_hz,
        expected_start_ms=case.expected_start_ms,
        expected_end_ms=case.expected_end_ms,
    )
    raw_observed = (
        observe_signal(
            case.raw_mic_signal,
            frame_ms=frame_ms,
            mode=mode,
            sample_rate_hz=sample_rate_hz,
            expected_start_ms=None,
            expected_end_ms=None,
        )
        if case.raw_mic_signal is not None
        else None
    )

    record: dict[str, Any] = {
        "observation_schema_version": OBSERVATION_SCHEMA_VERSION,
        "observation_id": f"obs_duplex_vad_{uuid.uuid4().hex}",
        "contract_snapshot": contract_snapshot,
        "candidate": DEFAULT_CANDIDATE,
        "deployment_mode": "local",
        "output_mode": output_mode_for_case(case),
        "sample_rate_hz": sample_rate_hz,
        "frame_ms": frame_ms,
        "mode": mode,
        "synthetic_case": case.name,
        "synthetic_category": case.category,
        "synthetic_seed": synthetic_seed,
        "expected_speech_start_ms": case.expected_start_ms,
        "expected_speech_end_ms": case.expected_end_ms,
        "echo_likelihood_mode": echo_likelihood_mode_for_case(case),
        "playback_reference_residual": playback_reference_residual_for_case(case),
        "raw_vad_confidence_summary": (
            raw_observed["vad_confidence_summary"] if raw_observed is not None else None
        ),
        "raw_audio_committed": False,
        "contains_real_user_input": False,
        "contains_raw_trace": False,
        "deterministic_replay_reruns_vad": False,
        "fixture_note": case.fixture_note,
    }
    record.update(observed)
    validate_observation(record)
    return record


def client_stop_playback_observation(
    *,
    contract_snapshot: str,
    synthetic_seed: int,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "observation_schema_version": OBSERVATION_SCHEMA_VERSION,
        "observation_id": f"obs_duplex_vad_{uuid.uuid4().hex}",
        "contract_snapshot": contract_snapshot,
        "candidate": DEFAULT_CANDIDATE,
        "deployment_mode": "local",
        "output_mode": "degraded",
        "sample_rate_hz": synth.DEFAULT_SAMPLE_RATE_HZ,
        "frame_ms": None,
        "mode": None,
        "synthetic_case": "client_stop_playback_simulation",
        "synthetic_category": "metadata_only",
        "synthetic_seed": synthetic_seed,
        "expected_speech_start_ms": None,
        "expected_speech_end_ms": None,
        "speech_start_ms": None,
        "speech_start_emit_latency_ms": None,
        "speech_end_ms": None,
        "speech_end_offset_error_ms": None,
        "speech_end_hangover_ms": None,
        "vad_confidence_summary": None,
        "raw_vad_confidence_summary": None,
        "active_frame_count": None,
        "total_frame_count": None,
        "echo_likelihood_mode": "not_applicable",
        "playback_reference_residual": "not_applicable",
        "request_offset_ms": 1040,
        "actual_stop_offset_ms": 1100,
        "tts_truncated_owner": "talker_playback_controller",
        "raw_audio_committed": False,
        "contains_real_user_input": False,
        "contains_raw_trace": False,
        "deterministic_replay_reruns_vad": False,
        "fixture_note": "metadata-only playback stop simulation; no VAD decision",
    }
    validate_observation(record)
    return record


def validate_observation(record: dict[str, Any]) -> None:
    required_keys = {
        "observation_schema_version",
        "observation_id",
        "contract_snapshot",
        "candidate",
        "deployment_mode",
        "output_mode",
        "sample_rate_hz",
        "frame_ms",
        "mode",
        "synthetic_case",
        "synthetic_seed",
        "raw_audio_committed",
        "contains_real_user_input",
        "contains_raw_trace",
        "deterministic_replay_reruns_vad",
    }
    missing = sorted(required_keys.difference(record))
    if missing:
        raise ValueError(f"missing observation keys: {missing}")

    for flag_key in (
        "raw_audio_committed",
        "contains_real_user_input",
        "contains_raw_trace",
        "deterministic_replay_reruns_vad",
    ):
        if record[flag_key] is not False:
            raise ValueError(f"{flag_key} must be false")

    if record["deployment_mode"] != "local":
        raise ValueError("deployment_mode must be local")
    if record["candidate"] != DEFAULT_CANDIDATE:
        raise ValueError(f"candidate must be {DEFAULT_CANDIDATE}")
    if record["output_mode"] not in {"real", "degraded", "real_or_degraded"}:
        raise ValueError(f"invalid output_mode={record['output_mode']}")
    if record["synthetic_case"] != "client_stop_playback_simulation":
        if record["frame_ms"] not in {10, 20, 30}:
            raise ValueError(f"invalid frame_ms={record['frame_ms']}")
        if record["mode"] not in {0, 1, 2, 3}:
            raise ValueError(f"invalid mode={record['mode']}")
        confidence = record["vad_confidence_summary"]
        if not isinstance(confidence, float) or not 0.0 <= confidence <= 1.0:
            raise ValueError(f"invalid vad_confidence_summary={confidence}")


def select_cases(
    all_cases: dict[str, synth.SyntheticCase],
    requested_case_names: Iterable[str],
) -> list[synth.SyntheticCase]:
    requested = list(requested_case_names)
    if requested == ["all"] or "all" in requested:
        return [all_cases[name] for name in all_cases]
    unknown = sorted(set(requested).difference(all_cases))
    if unknown:
        raise ValueError(f"unknown synthetic case names: {unknown}")
    return [all_cases[name] for name in requested]


def make_observations(
    *,
    contract_snapshot: str,
    frame_ms_values: list[int],
    mode_values: list[int],
    case_names: list[str],
    synthetic_seed: int,
    sample_rate_hz: int,
) -> list[dict[str, Any]]:
    cases = synth.build_synthetic_cases(
        sample_rate_hz=sample_rate_hz,
        seed=synthetic_seed,
    )
    observations: list[dict[str, Any]] = []
    for case in select_cases(cases, case_names):
        if case.name == "client_stop_playback_simulation":
            observations.append(
                client_stop_playback_observation(
                    contract_snapshot=contract_snapshot,
                    synthetic_seed=synthetic_seed,
                )
            )
            continue
        for frame_ms in frame_ms_values:
            for mode in mode_values:
                observations.append(
                    observation_for_case(
                        case,
                        contract_snapshot=contract_snapshot,
                        frame_ms=frame_ms,
                        mode=mode,
                        synthetic_seed=synthetic_seed,
                        sample_rate_hz=sample_rate_hz,
                    )
                )
    return observations


def write_jsonl(records: list[dict[str, Any]], output_path: pathlib.Path) -> None:
    resolved = output_path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with resolved.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
            handle.write("\n")


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    case_names = sorted({record["synthetic_case"] for record in records})
    return {
        "observation_count": len(records),
        "case_count": len(case_names),
        "case_names": case_names,
        "raw_audio_committed": any(record["raw_audio_committed"] for record in records),
        "contains_real_user_input": any(
            record["contains_real_user_input"] for record in records
        ),
        "contains_raw_trace": any(record["contains_raw_trace"] for record in records),
        "deterministic_replay_reruns_vad": any(
            record["deterministic_replay_reruns_vad"] for record in records
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract-snapshot", default=DEFAULT_CONTRACT_SNAPSHOT)
    parser.add_argument("--candidate", default=DEFAULT_CANDIDATE)
    parser.add_argument("--sample-rate-hz", type=int, default=synth.DEFAULT_SAMPLE_RATE_HZ)
    parser.add_argument("--frame-ms", default=",".join(str(value) for value in DEFAULT_FRAME_MS))
    parser.add_argument("--mode", default=",".join(str(value) for value in DEFAULT_MODES))
    parser.add_argument("--cases", default="all")
    parser.add_argument("--synthetic-seed", type=int, default=synth.DEFAULT_SYNTHETIC_SEED)
    parser.add_argument("--metadata-out", type=pathlib.Path)
    parser.add_argument("--summary-out", type=pathlib.Path)
    parser.add_argument("--write-local-wav-dir", type=pathlib.Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.candidate != DEFAULT_CANDIDATE:
        raise SystemExit(f"unsupported candidate for this harness: {args.candidate}")

    frame_ms_values = parse_int_list(args.frame_ms)
    mode_values = parse_int_list(args.mode)
    case_names = [part.strip() for part in args.cases.split(",") if part.strip()]
    observations = make_observations(
        contract_snapshot=args.contract_snapshot,
        frame_ms_values=frame_ms_values,
        mode_values=mode_values,
        case_names=case_names or ["all"],
        synthetic_seed=args.synthetic_seed,
        sample_rate_hz=args.sample_rate_hz,
    )

    if args.write_local_wav_dir:
        cases = synth.build_synthetic_cases(
            sample_rate_hz=args.sample_rate_hz,
            seed=args.synthetic_seed,
        )
        synth.write_cases_to_wav(cases, args.write_local_wav_dir)

    summary = summarize(observations)
    if args.metadata_out:
        write_jsonl(observations, args.metadata_out)
        summary["metadata_out"] = str(args.metadata_out.expanduser().resolve())
    if args.summary_out:
        args.summary_out.expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.expanduser().resolve().write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
