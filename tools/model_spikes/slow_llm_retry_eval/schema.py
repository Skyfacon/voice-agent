"""Manual validation helpers for Slow LLM retry eval observations."""

from __future__ import annotations

import json
import pathlib
from collections.abc import Iterable
from typing import Any


SCHEMA_VERSION = "slow_llm_retry_cancellation_observation.v1"
OUTPUT_MODES = {"mock", "real", "degraded", "fallback"}
STATUSES = {"pass", "fail", "not_applicable"}

REQUIRED_TOP_LEVEL = {
    "schema_version",
    "contract_snapshot",
    "observation_id",
    "case_id",
    "observation_kind",
    "candidate",
    "task_binding",
    "adapter_result",
    "slowtask_effect",
    "tool_boundary",
    "privacy",
    "boundary_assertions",
}


def load_jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.expanduser().resolve().open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {line_number}: invalid JSON") from exc
            if not isinstance(value, dict):
                raise ValueError(f"line {line_number}: expected JSON object")
            records.append(value)
    return records


def validate_observation(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    missing = sorted(REQUIRED_TOP_LEVEL.difference(record))
    if missing:
        errors.append(f"missing top-level fields: {missing}")

    if record.get("schema_version") != SCHEMA_VERSION:
        errors.append("invalid schema_version")

    candidate = _object(record, "candidate", errors)
    task = _object(record, "task_binding", errors)
    adapter = _object(record, "adapter_result", errors)
    effect = _object(record, "slowtask_effect", errors)
    tool = _object(record, "tool_boundary", errors)
    privacy = _object(record, "privacy", errors)
    boundary = _object(record, "boundary_assertions", errors)

    if candidate.get("adapter_type") != "slow_llm":
        errors.append("candidate.adapter_type must be slow_llm")
    if candidate.get("output_mode") not in OUTPUT_MODES:
        errors.append("candidate.output_mode must be mock, real, degraded, or fallback")

    for key in ("task_id", "plan_version", "task_event_seq", "adapter_request_id"):
        if task.get(key) is None:
            errors.append(f"task_binding.{key} is required")
    for key in ("plan_version", "task_event_seq", "current_plan_version_at_arrival"):
        value = task.get(key) if key != "current_plan_version_at_arrival" else effect.get(key)
        if not isinstance(value, int) or value < 0:
            errors.append(f"{key} must be a non-negative integer")

    if adapter.get("parse_status") not in STATUSES:
        errors.append("parse_status must be pass, fail, or not_applicable")
    if adapter.get("schema_status") not in STATUSES:
        errors.append("schema_status must be pass, fail, or not_applicable")
    if adapter.get("final_validation_status") not in STATUSES:
        errors.append("final_validation_status must be pass, fail, or not_applicable")
    if adapter.get("provider_cancel_confirmed") not in {"true", "false", "unknown"}:
        errors.append("provider_cancel_confirmed must be true, false, or unknown")
    _require_false(adapter, "raw_provider_body_stored", errors)

    if adapter.get("schema_status") == "fail" and adapter.get("failure_category") is None:
        errors.append("schema failure requires failure_category")
    if adapter.get("parse_status") == "fail" and adapter.get("schema_status") != "not_applicable":
        errors.append("parse failure should not run schema validation")
    if adapter.get("retry_budget_exhausted") and adapter.get("final_validation_status") == "pass":
        errors.append("retry budget exhausted cannot have final pass")

    if effect.get("should_mark_stale"):
        if effect.get("may_advance_current_task") is not False:
            errors.append("stale result cannot advance current task")
        if effect.get("requires_explicit_adopt_or_rebase") is not True:
            errors.append("stale result requires explicit adopt/rebase")
    if effect.get("adoption_recorded") and not effect.get("requires_explicit_adopt_or_rebase"):
        errors.append("adoption_recorded requires adopt/rebase flag")

    if tool.get("tool_execution_started") is not False:
        errors.append("tool execution must not start from eval observation")
    if tool.get("confirmation_accepted") is not False:
        errors.append("confirmation must not be accepted from model output")
    if tool.get("tool_proposal_present") and not tool.get("confirmation_required"):
        errors.append("tool proposal should require confirmation in this eval")
    if tool.get("web_evidence_trusted_as_instruction") is not False:
        errors.append("web evidence must not be trusted as instruction")

    _require_false(privacy, "raw_trace_stored", errors)
    _require_false(privacy, "real_user_input_stored", errors)
    _require_false(privacy, "secret_material_stored", errors)
    _require_false(privacy, "deterministic_replay_reruns_provider", errors)

    for key in (
        "model_output_owns_slowtask_state",
        "model_output_accepts_confirmation",
        "model_output_authorizes_tools",
        "model_output_mutates_ui",
        "model_output_sets_terminal_task_status",
    ):
        if boundary.get(key) is not False:
            errors.append(f"{key} must be false")

    return errors


def validate_records(records: Iterable[dict[str, Any]]) -> tuple[int, list[str]]:
    count = 0
    errors: list[str] = []
    for count, record in enumerate(records, start=1):
        for error in validate_observation(record):
            errors.append(f"record {count} {record.get('case_id', '<unknown>')}: {error}")
    return count, errors


def _object(record: dict[str, Any], key: str, errors: list[str]) -> dict[str, Any]:
    value = record.get(key)
    if isinstance(value, dict):
        return value
    if key in record:
        errors.append(f"{key} must be an object")
    return {}


def _require_false(record: dict[str, Any], key: str, errors: list[str]) -> None:
    if record.get(key) is not False:
        errors.append(f"{key} must be false")
