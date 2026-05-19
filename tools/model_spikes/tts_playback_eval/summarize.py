"""Commit-safe markdown summary generation for TTS playback eval observations."""

from __future__ import annotations

import pathlib
from collections import Counter
from typing import Any

from .schema import validate_records


def build_summary(records: list[dict[str, Any]]) -> str:
    count, errors = validate_records(records)
    if errors:
        raise ValueError(f"cannot summarize invalid observations: {errors}")

    labels = Counter(record.get("expected_evidence_label", "unknown") for record in records)
    rows = []
    for record in records:
        stream = record["stream_metadata"]
        playback = record["playback_metadata"]
        control = record["control_metadata"]
        rows.append(
            "| {case} | {kind} | {mode} | {label} | {chunks} | {progress} | {requested} | {stopped} | {reason} |".format(
                case=record["case_id"],
                kind=record["observation_kind"],
                mode=record["output_mode"],
                label=record.get("expected_evidence_label", "unknown"),
                chunks=stream["chunk_count"],
                progress=len(playback["progress_offsets_ms"]),
                requested=control["truncate_requested"],
                stopped=control["actual_stop_offset_ms"],
                reason=stream["stream_end_reason"],
            )
        )

    label_lines = [
        f"- `{label}`: {value}"
        for label, value in sorted(labels.items(), key=lambda item: item[0])
    ]

    return "\n".join(
        [
            "# TTS CosyVoice Playback Eval Dry-Run Summary",
            "",
            "## Status",
            "",
            "dry_run_metadata_only",
            "",
            "## Observation Count",
            "",
            f"- observations: {count}",
            f"- unique cases: {len({record['case_id'] for record in records})}",
            "",
            "## Capability Labels",
            "",
            *label_lines,
            "",
            "## Case Results",
            "",
            "| case | kind | output mode | expected evidence label | chunks | progress events | truncate requested | actual stop offset ms | stream end reason |",
            "| --- | --- | --- | --- | ---: | ---: | --- | ---: | --- |",
            *rows,
            "",
            "## Boundary Notes",
            "",
            "- CosyVoice/TTS is audio synthesis evidence, not turn ingress owner.",
            "- TTS output and playback committed are not user acknowledgement.",
            "- TTS output and playback committed are not SemanticCommitment.",
            "- Talker/playback owns playback span state.",
            "- Interaction Controller owns truncate request.",
            "- TTS adapter only provides audio stream/file metadata.",
            "- Client close or provider stream close is not TTS_TRUNCATED.",
            "- TTS_TRUNCATED requires Talker-confirmed actual stop offset.",
            "- Deterministic replay consumes metadata or synthetic fixtures and does not rerun TTS.",
            "",
            "## Privacy Notes",
            "",
            "- No generated audio is stored.",
            "- No provider request or response bodies are stored.",
            "- No local traces or replay caches are stored.",
            "- No real user input is used.",
            "",
        ]
    )


def write_summary(records: list[dict[str, Any]], output_path: pathlib.Path) -> pathlib.Path:
    resolved = output_path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(build_summary(records), encoding="utf-8")
    return resolved
