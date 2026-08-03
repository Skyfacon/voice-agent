from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any

from voice_agent.evals.routing.case import (
    ROUTING_SPLITS,
    RoutingCase,
    RoutingCaseValidationError,
    validate_routing_case,
)


MAX_MANIFEST_BYTES = 32 * 1024 * 1024
MAX_JSONL_LINE_BYTES = 1024 * 1024


class RoutingCaseLoadError(ValueError):
    """Raised when a JSONL routing manifest cannot be loaded safely."""


def load_routing_cases_jsonl(
    path: str | Path,
    *,
    expected_split: str | None = None,
) -> tuple[RoutingCase, ...]:
    """Load a UTF-8 JSONL manifest using only the standard library.

    The loader rejects symlinks, duplicate JSON keys, duplicate case IDs, very
    large inputs, and raw-audio/provider file types.  Blank lines are allowed so
    hand-reviewed manifests can retain visual grouping without affecting order.
    """

    manifest_path = _safe_manifest_path(path)
    if expected_split is not None and expected_split not in ROUTING_SPLITS:
        raise RoutingCaseLoadError(
            f"expected_split must be one of {sorted(ROUTING_SPLITS)}"
        )
    try:
        size = manifest_path.stat().st_size
    except OSError as exc:
        raise RoutingCaseLoadError(f"cannot stat routing manifest: {manifest_path}") from exc
    if size > MAX_MANIFEST_BYTES:
        raise RoutingCaseLoadError(
            f"routing manifest exceeds {MAX_MANIFEST_BYTES} byte safety limit"
        )

    cases: list[RoutingCase] = []
    case_ids: set[str] = set()
    try:
        with manifest_path.open("r", encoding="utf-8", newline="") as handle:
            for line_number, line in enumerate(handle, start=1):
                if len(line.encode("utf-8")) > MAX_JSONL_LINE_BYTES:
                    raise RoutingCaseLoadError(
                        f"line {line_number} exceeds {MAX_JSONL_LINE_BYTES} byte safety limit"
                    )
                if not line.strip():
                    continue
                raw = _load_json_object(line, line_number=line_number)
                try:
                    case = validate_routing_case(raw)
                except RoutingCaseValidationError as exc:
                    raise RoutingCaseLoadError(f"line {line_number}: {exc}") from exc
                if case.case_id in case_ids:
                    raise RoutingCaseLoadError(
                        f"line {line_number}: duplicate case_id {case.case_id!r}"
                    )
                if expected_split is not None and case.split != expected_split:
                    raise RoutingCaseLoadError(
                        f"line {line_number}: case split {case.split!r} does not match "
                        f"expected_split {expected_split!r}"
                    )
                case_ids.add(case.case_id)
                cases.append(case)
    except UnicodeDecodeError as exc:
        raise RoutingCaseLoadError("routing manifest must be valid UTF-8") from exc
    except OSError as exc:
        raise RoutingCaseLoadError(f"cannot read routing manifest: {manifest_path}") from exc
    if not cases:
        raise RoutingCaseLoadError("routing manifest must contain at least one case")
    return tuple(cases)


def _safe_manifest_path(path: str | Path) -> Path:
    if not isinstance(path, (str, Path)):
        raise RoutingCaseLoadError("routing manifest path must be str or Path")
    raw_path = str(path)
    if not raw_path or "\x00" in raw_path:
        raise RoutingCaseLoadError("routing manifest path must be non-empty and NUL-free")
    manifest_path = Path(path)
    lower_path = raw_path.lower().replace("\\", "/")
    if manifest_path.suffix.lower() != ".jsonl":
        raise RoutingCaseLoadError("routing manifest path must end in .jsonl")
    if any(
        fragment in lower_path
        for fragment in ("audio/raw/", "diagnostics/", "traces/", "replays/local/")
    ):
        raise RoutingCaseLoadError("routing manifest path points into an unsafe artifact directory")
    if manifest_path.is_symlink():
        raise RoutingCaseLoadError("routing manifest must not be a symlink")
    if not manifest_path.is_file():
        raise RoutingCaseLoadError(f"routing manifest does not exist: {manifest_path}")
    return manifest_path


def _load_json_object(line: str, *, line_number: int) -> Mapping[str, Any]:
    try:
        value = json.loads(line, object_pairs_hook=_reject_duplicate_keys)
    except (json.JSONDecodeError, RoutingCaseLoadError) as exc:
        raise RoutingCaseLoadError(f"line {line_number}: invalid JSON: {exc}") from exc
    if not isinstance(value, Mapping):
        raise RoutingCaseLoadError(f"line {line_number}: routing case must be a JSON object")
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RoutingCaseLoadError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result
