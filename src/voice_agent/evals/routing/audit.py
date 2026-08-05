from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
import re
from typing import Any

from voice_agent.evals.routing.case import (
    CONTEXT_TEMPLATES,
    PENDING_CONFIRMATION_SCOPES,
    RoutingCase,
    RoutingCaseValidationError,
    validate_routing_case,
)


AUDIT_SCHEMA_NAME = "voice_agent.routing_eval.corpus_audit.v1"
MILESTONE1_BUCKET_QUOTAS = (
    ("fast", 20),
    ("spawn", 20),
    ("patch_control", 28),
    ("ignore_ambiguous", 12),
)

_LOCAL_PATH_PATTERN = re.compile(
    r"(?:^|[\s\"'])(?:/Users/|/home/|/private/|/tmp/|[A-Za-z]:\\)|"
    r"(?:file://|\.\./|\.\.\\)",
    re.IGNORECASE,
)
_RAW_ARTIFACT_PATTERN = re.compile(
    r"(?:diagnostics/|traces/|replays/local/|audio/raw/|"
    r"\.(?:wav|mp3|m4a|flac|ogg|opus|weba)(?:$|[?#\s]))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CorpusAuditPolicy:
    """Immutable corpus-wide expectations layered on top of case validation."""

    expected_case_count: int | None = None
    expected_split_counts: tuple[tuple[str, int], ...] = ()
    expected_bucket_counts: tuple[tuple[str, int], ...] = ()
    expected_status_counts: tuple[tuple[str, int], ...] = ()
    required_context_templates: tuple[str, ...] = tuple(sorted(CONTEXT_TEMPLATES))
    human_review_required_splits: tuple[str, ...] = ("validation", "locked_test")
    minimum_contrast_set_family_size: int = 2
    expected_contrast_set_family_count: int | None = None


def milestone1_prompt_dev_policy() -> CorpusAuditPolicy:
    """Return the accepted 80-case draft quota for Human Review Gate 1."""

    return CorpusAuditPolicy(
        expected_case_count=80,
        expected_split_counts=(("prompt_dev", 80),),
        expected_bucket_counts=MILESTONE1_BUCKET_QUOTAS,
        expected_status_counts=(("draft", 80),),
        expected_contrast_set_family_count=20,
    )


def audit_routing_corpus(
    cases: Iterable[RoutingCase | Mapping[str, Any]],
    *,
    policy: CorpusAuditPolicy | None = None,
) -> dict[str, Any]:
    """Return a deterministic, JSON-compatible corpus audit report.

    The function revalidates typed records so direct dataclass construction
    cannot bypass per-case safety or canonical confirmation-scope checks.
    Invalid values are reported by index without copying their contents into
    the report.
    """

    policy = policy or CorpusAuditPolicy()
    issues: list[dict[str, Any]] = []
    normalized: list[RoutingCase] = []
    noncanonical_confirmation_indexes: list[int] = []
    input_count = 0
    for index, value in enumerate(cases):
        input_count += 1
        try:
            raw = _case_revalidation_mapping(value) if isinstance(value, RoutingCase) else value
            if _has_noncanonical_confirmation_scope(raw):
                noncanonical_confirmation_indexes.append(index)
            normalized.append(validate_routing_case(raw))
        except (RoutingCaseValidationError, TypeError, ValueError) as exc:
            _add_issue(
                issues,
                code="invalid_case",
                message=f"case at index {index} failed v1 validation: {exc}",
                indexes=[index],
            )

    case_ids: dict[str, list[int]] = defaultdict(list)
    family_splits: dict[str, set[str]] = defaultdict(set)
    family_cases: dict[str, list[RoutingCase]] = defaultdict(list)
    for index, case in enumerate(normalized):
        case_ids[case.case_id].append(index)
        family_splits[case.scenario_family_id].add(case.split)
        family_cases[case.scenario_family_id].append(case)

    duplicate_ids = sorted(case_id for case_id, indexes in case_ids.items() if len(indexes) > 1)
    for case_id in duplicate_ids:
        _add_issue(
            issues,
            code="duplicate_case_id",
            message=f"case_id {case_id!r} appears more than once",
            case_ids=[case_id],
        )

    split_families = sorted(
        family for family, splits in family_splits.items() if len(splits) > 1
    )
    for family in split_families:
        _add_issue(
            issues,
            code="family_split_leakage",
            message=f"scenario family {family!r} appears in multiple splits",
            case_ids=sorted(case.case_id for case in family_cases[family]),
        )

    context_counts = Counter(case.context.template for case in normalized)
    missing_contexts = sorted(set(policy.required_context_templates) - set(context_counts))
    if missing_contexts:
        _add_issue(
            issues,
            code="missing_context_coverage",
            message="required context templates are missing",
            details={"missing_templates": missing_contexts},
        )

    # ``minimal_pair`` remains accepted as a legacy tag for older manifests, but
    # it is audited only as contrast-set membership.  Strict one-variable pair
    # semantics require a separate future rule and are not inferred from a tag.
    contrast_set_families = {
        case.scenario_family_id
        for case in normalized
        if "contrast_set" in case.tags or "minimal_pair" in case.tags
    }
    weak_contrast_set_families: list[str] = []
    for family in sorted(contrast_set_families):
        members = family_cases[family]
        route_signatures = {
            tuple(sorted(member.gold.router_decisions_allowed)) for member in members
        }
        if (
            len(members) < policy.minimum_contrast_set_family_size
            or len(route_signatures) < 2
        ):
            weak_contrast_set_families.append(family)
            _add_issue(
                issues,
                code="incomplete_contrast_set",
                message=(
                    f"contrast-set family {family!r} needs at least "
                    f"{policy.minimum_contrast_set_family_size} cases and two route signatures"
                ),
                case_ids=sorted(case.case_id for case in members),
            )
    contrast_set_count_mismatch = (
        policy.expected_contrast_set_family_count is not None
        and len(contrast_set_families) != policy.expected_contrast_set_family_count
    )
    if contrast_set_count_mismatch:
        _add_issue(
            issues,
            code="contrast_set_family_count_mismatch",
            message="corpus does not contain the expected number of contrast-set families",
            details={
                "expected": policy.expected_contrast_set_family_count,
                "actual": len(contrast_set_families),
            },
        )

    status_counts = Counter(case.annotation_status for case in normalized)
    draft_in_review_splits = sorted(
        case.case_id
        for case in normalized
        if case.split in policy.human_review_required_splits
        and case.annotation_status == "draft"
    )
    if draft_in_review_splits:
        _add_issue(
            issues,
            code="draft_in_human_review_split",
            message="validation and locked-test cases require human review",
            case_ids=draft_in_review_splits,
        )

    bad_confirmation_cases: list[str] = []
    for case in normalized:
        active_task = case.context.active_task
        if active_task is None:
            continue
        scope = active_task.pending_confirmation_scope
        if scope is not None and scope not in PENDING_CONFIRMATION_SCOPES:
            bad_confirmation_cases.append(case.case_id)
    if bad_confirmation_cases or noncanonical_confirmation_indexes:
        _add_issue(
            issues,
            code="noncanonical_confirmation_scope",
            message="pending confirmation scope is not canonical ADR-016 vocabulary",
            case_ids=sorted(bad_confirmation_cases),
            indexes=noncanonical_confirmation_indexes,
        )

    unsafe_cases: list[str] = []
    for case in normalized:
        if _case_has_unsafe_shareable_field(case):
            unsafe_cases.append(case.case_id)
    if unsafe_cases:
        _add_issue(
            issues,
            code="unsafe_shareable_field",
            message="case contains a local path or raw-artifact reference",
            case_ids=sorted(unsafe_cases),
        )

    bucket_counts = Counter(_routing_bucket(case) for case in normalized)
    split_counts = Counter(case.split for case in normalized)
    quota_mismatches: dict[str, Any] = {}
    if policy.expected_case_count is not None and input_count != policy.expected_case_count:
        quota_mismatches["case_count"] = {
            "expected": policy.expected_case_count,
            "actual": input_count,
        }
    _record_count_mismatches(
        quota_mismatches,
        name="splits",
        expected=policy.expected_split_counts,
        actual=split_counts,
    )
    _record_count_mismatches(
        quota_mismatches,
        name="buckets",
        expected=policy.expected_bucket_counts,
        actual=bucket_counts,
    )
    _record_count_mismatches(
        quota_mismatches,
        name="annotation_statuses",
        expected=policy.expected_status_counts,
        actual=status_counts,
    )
    if quota_mismatches:
        _add_issue(
            issues,
            code="quota_mismatch",
            message="corpus does not match configured quota",
            details=quota_mismatches,
        )

    checks = {
        "case_validation": {
            "passed": input_count == len(normalized),
            "input_count": input_count,
            "valid_count": len(normalized),
        },
        "unique_case_ids": {
            "passed": not duplicate_ids,
            "duplicate_case_ids": duplicate_ids,
        },
        "family_split_isolation": {
            "passed": not split_families,
            "leaking_families": split_families,
        },
        "quota": {
            "passed": not quota_mismatches,
            "mismatches": quota_mismatches,
        },
        "annotation_status": {
            "passed": not draft_in_review_splits,
            "counts": _counter_dict(status_counts),
            "draft_case_ids_in_review_splits": draft_in_review_splits,
        },
        "context_coverage": {
            "passed": not missing_contexts,
            "counts": _counter_dict(context_counts),
            "missing_templates": missing_contexts,
        },
        "contrast_set_coverage": {
            "passed": not weak_contrast_set_families and not contrast_set_count_mismatch,
            "family_count": len(contrast_set_families),
            "expected_family_count": policy.expected_contrast_set_family_count,
            "incomplete_families": weak_contrast_set_families,
        },
        "canonical_confirmation_scope": {
            "passed": not bad_confirmation_cases and not noncanonical_confirmation_indexes,
            "invalid_case_ids": sorted(bad_confirmation_cases),
            "invalid_indexes": noncanonical_confirmation_indexes,
        },
        "safe_shareable_fields": {
            "passed": not unsafe_cases,
            "invalid_case_ids": sorted(unsafe_cases),
        },
    }
    return {
        "schema_name": AUDIT_SCHEMA_NAME,
        "status": "passed" if not issues else "failed",
        "case_count": input_count,
        "valid_case_count": len(normalized),
        "family_count": len(family_cases),
        "split_counts": _counter_dict(split_counts),
        "bucket_counts": _counter_dict(bucket_counts),
        "criticality_counts": _counter_dict(
            Counter(case.criticality for case in normalized)
        ),
        "checks": checks,
        "issues": issues,
        "safe_to_share": not any(
            issue["code"] in {"invalid_case", "unsafe_shareable_field"}
            for issue in issues
        ),
    }


def _routing_bucket(case: RoutingCase) -> str:
    allowed = set(case.gold.router_decisions_allowed)
    focus = set(case.gold.task_focus_allowed)
    if allowed == {"SPAWN_SLOW_TASK"}:
        return "spawn"
    if allowed == {"PATCH_ACTIVE_SLOW_TASK"}:
        return "patch_control"
    if focus <= {"NON_ASSISTANT", "AMBIGUOUS"}:
        return "ignore_ambiguous"
    if allowed == {"FAST_ONLY"} and focus == {"FOREGROUND_CHAT"}:
        return "fast"
    return "other"


def _case_revalidation_mapping(case: RoutingCase) -> dict[str, Any]:
    raw = asdict(case)
    routing_input = raw["input"]
    if routing_input["utterance_text"] is None:
        del routing_input["utterance_text"]
    if routing_input["audio_ref"] is None:
        del routing_input["audio_ref"]
    context = raw["context"]
    if context["active_task"] is None:
        del context["active_task"]
    elif context["active_task"]["pending_confirmation_scope"] is None:
        del context["active_task"]["pending_confirmation_scope"]
    return raw


def _has_noncanonical_confirmation_scope(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    context = value.get("context")
    if not isinstance(context, Mapping):
        return False
    active_task = context.get("active_task")
    if not isinstance(active_task, Mapping):
        return False
    scope = active_task.get("pending_confirmation_scope")
    return scope is not None and scope not in PENDING_CONFIRMATION_SCOPES


def _case_has_unsafe_shareable_field(case: RoutingCase) -> bool:
    values = [case.input.utterance_text or ""]
    if case.context.active_task is not None:
        values.append(case.context.active_task.summary)
    return any(
        _LOCAL_PATH_PATTERN.search(value) is not None
        or _RAW_ARTIFACT_PATTERN.search(value) is not None
        for value in values
    )


def _record_count_mismatches(
    target: dict[str, Any],
    *,
    name: str,
    expected: tuple[tuple[str, int], ...],
    actual: Counter[str],
) -> None:
    if not expected:
        return
    expected_dict = dict(expected)
    keys = sorted(set(expected_dict) | set(actual))
    mismatch = {
        key: {"expected": expected_dict.get(key, 0), "actual": actual.get(key, 0)}
        for key in keys
        if expected_dict.get(key, 0) != actual.get(key, 0)
    }
    if mismatch:
        target[name] = mismatch


def _counter_dict(counter: Counter[str]) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def _add_issue(
    issues: list[dict[str, Any]],
    *,
    code: str,
    message: str,
    case_ids: list[str] | None = None,
    indexes: list[int] | None = None,
    details: Mapping[str, Any] | None = None,
) -> None:
    issue: dict[str, Any] = {
        "code": code,
        "severity": "error",
        "message": message,
    }
    if case_ids:
        issue["case_ids"] = case_ids
    if indexes:
        issue["indexes"] = indexes
    if details:
        issue["details"] = dict(details)
    issues.append(issue)
