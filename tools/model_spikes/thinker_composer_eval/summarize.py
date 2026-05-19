"""Commit-safe markdown summary generation for Thinker / Composer observations."""

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
        candidate = record["candidate"]
        semantic = record["semantic_frame_observation"]
        composer = record["composer_observation"]
        boundary = record["boundary_observation"]
        failure = record["failure_observation"]
        rows.append(
            "| {case} | {role} | {label} | {parse} | {schema} | {conflict} | {coverage} | {playback} | {failure} |".format(
                case=record["case_id"],
                role=candidate["role_contract"],
                label=record.get("expected_evidence_label", "unknown"),
                parse=semantic["schema_parse_passed"],
                schema=semantic["schema_validation_passed"],
                conflict=semantic["asr_thinker_conflict_preserved"],
                coverage=composer["coverage_check_passed"],
                playback=boundary["talker_playback_allowed"],
                failure=failure["failure_category"],
            )
        )

    label_lines = [
        f"- `{label}`: {value}"
        for label, value in sorted(labels.items(), key=lambda item: item[0])
    ]

    return "\n".join(
        [
            "# Thinker / Composer Boundary Eval Dry-Run Summary",
            "",
            "## Status",
            "",
            "dry_run_metadata_only",
            "",
            "## Date",
            "",
            "2026-05-12",
            "",
            "## Contract Snapshot",
            "",
            "- `main@61e6afc`",
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
            "| case | role contract | expected evidence label | parse | schema | ASR/Thinker conflict preserved | coverage passed | Talker playback allowed | failure |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            *rows,
            "",
            "## Boundary Notes",
            "",
            "- Qwen-Omni / Thinker output is SemanticFrame evidence, not SemanticCommitment.",
            "- SlowTask remains the owner of SemanticCommitment, resolved arguments, confirmation, and task outcome.",
            "- Thinker-as-Composer may realize approved content as SpokenPlan, but cannot rewrite protected facts.",
            "- Coverage and truthfulness checks are independent gates; model self-report is not enough.",
            "- Failed coverage blocks Talker playback.",
            "- Tool-like output remains proposal evidence only; Tool Executor remains required for execution.",
            "- Semantic close and assistant directedness remain unknown unless directly exercised by a future proof.",
            "- Full structured Thinker responses are not Duplex hot-path decisions.",
            "- Deterministic replay consumes recorded metadata or synthetic fixtures and does not rerun providers.",
            "",
            "## Privacy Notes",
            "",
            "- No provider request or response bodies are stored.",
            "- No raw audio is stored.",
            "- No local traces or replay cache are stored.",
            "- No real user input is used.",
            "- No tools are executed.",
            "",
        ]
    )


def write_summary(records: list[dict[str, Any]], output_path: pathlib.Path) -> pathlib.Path:
    resolved = output_path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(build_summary(records), encoding="utf-8")
    return resolved
