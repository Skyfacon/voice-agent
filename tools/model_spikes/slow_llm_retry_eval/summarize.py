"""Commit-safe markdown summary generation for Slow LLM retry observations."""

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
        adapter = record["adapter_result"]
        effect = record["slowtask_effect"]
        tool = record["tool_boundary"]
        rows.append(
            "| {case} | {kind} | {label} | {parse} | {schema} | {retry} | {stale} | {advance} | {tool} | {failure} |".format(
                case=record["case_id"],
                kind=record["observation_kind"],
                label=record.get("expected_evidence_label", "unknown"),
                parse=adapter["parse_status"],
                schema=adapter["schema_status"],
                retry=adapter["retry_count"],
                stale=effect["should_mark_stale"],
                advance=effect["may_advance_current_task"],
                tool=tool["tool_proposal_present"],
                failure=adapter["failure_category"],
            )
        )

    label_lines = [
        f"- `{label}`: {value}"
        for label, value in sorted(labels.items(), key=lambda item: item[0])
    ]

    return "\n".join(
        [
            "# Slow LLM Retry Eval Dry-Run Summary",
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
            "| case | kind | expected evidence label | parse | schema | retry count | stale | may advance current task | tool proposal | failure |",
            "| --- | --- | --- | --- | --- | ---: | --- | --- | --- | --- |",
            *rows,
            "",
            "## Boundary Notes",
            "",
            "- Slow LLM output is planning evidence, not SlowTask state.",
            "- Local validation must pass before SlowTask consumption.",
            "- Client timeout or abort is not provider-confirmed cancellation.",
            "- Old-plan and terminal late results are stale/debug metadata by default.",
            "- Stale output requires explicit SlowTask adopt/rebase before reuse.",
            "- Tool-like output remains proposal evidence only.",
            "- Model output cannot accept confirmation, authorize tools, mutate UI, or complete tasks.",
            "- Deterministic replay consumes metadata or synthetic fixtures and does not rerun providers.",
            "",
            "## Privacy Notes",
            "",
            "- No provider request or response bodies are stored.",
            "- No local traces or replay caches are stored.",
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
