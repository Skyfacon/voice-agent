"""Commit-safe markdown summary generation for ASR streaming eval observations."""

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
        streaming = record["streaming_observation"]
        timestamps = record["timestamp_observation"]
        failure = record["failure_observation"]
        rows.append(
            "| {case} | {mode} | {label} | {chunks} | {first} | {ts} | {failure} |".format(
                case=record["case_id"],
                mode=record["output_mode"],
                label=record.get("expected_evidence_label", "unknown"),
                chunks=streaming["delta_chunk_count"],
                first=streaming["first_delta_ms"],
                ts=timestamps["normalization_status"],
                failure=failure["failure_category"],
            )
        )

    label_lines = [
        f"- `{label}`: {value}"
        for label, value in sorted(labels.items(), key=lambda item: item[0])
    ]

    return "\n".join(
        [
            "# ASR Qwen-ASR Streaming Eval Dry-Run Summary",
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
            "| case | output mode | expected evidence label | chunks | first delta ms | timestamp status | failure |",
            "| --- | --- | --- | ---: | ---: | --- | --- |",
            *rows,
            "",
            "## Boundary Notes",
            "",
            "- Qwen-ASR is ASR text projection evidence, not turn ingress owner.",
            "- ASR transcript output is not SemanticCommitment.",
            "- Response streaming output does not prove true realtime microphone streaming input.",
            "- Client close or timeout is not provider-confirmed cancellation.",
            "- Deterministic replay consumes metadata or synthetic fixtures and does not rerun ASR.",
            "",
            "## Privacy Notes",
            "",
            "- No audio recordings are stored.",
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
