from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shlex
import stat
from collections import Counter
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

from .markdown import (
    collect_candidate_invariants,
    collect_legacy_rules,
    load_invariant_map,
    normalize_requirement,
)
from .model import (
    AuditCheck,
    AuditIssue,
    AuditPaths,
    AuditReport,
    CheckReport,
    InvariantMapping,
    Severity,
)


CANDIDATE_MAX_BYTES = 6 * 1024
CARD_MAX_BYTES = 12 * 1024
ACTIVE_BUNDLE_RECOMMENDED_BYTES = 20 * 1024

CHECK_ORDER: tuple[AuditCheck, ...] = (
    "mapping",
    "references",
    "budgets",
    "cards",
    "artifacts",
)
TASK_CARD_HEADINGS: tuple[str, ...] = (
    "Task ID and title",
    "Goal",
    "Allowed write files",
    "Required read-only dependencies",
    "Exact ADR sections",
    "Input and output contracts",
    "Stable invariant IDs",
    "Non-goals",
    "Implementation outline",
    "Verification commands",
    "Pass criteria",
    "Stop conditions",
    "Evidence and handoff",
)
WORK_PACKAGE_HEADINGS: tuple[str, ...] = (
    "Work Package ID and goal",
    "Ordered or dependency-based Task Card list",
    "Entry criteria",
    "Cross-card invariants",
    "Per-card verification policy",
    "Stop, retry, and rollback conditions",
    "Package-level acceptance criteria",
    "Final evidence handoff",
)
BUDGET_EXCEPTION_HEADING = "Budget exception"
BUDGET_EXCEPTION_FIELDS: tuple[str, ...] = (
    "Required additional source",
    "Why it cannot be summarized or section-selected",
    "Bounded duration",
    "Semantic-equivalence verification",
)

_APPROVED_FAMILIES = frozenset(
    {
        "ADR",
        "ADAPTER",
        "JOURNAL",
        "PLAN",
        "TOOL",
        "COMMITMENT",
        "PRIVACY",
        "CONCURRENCY",
        "FOREGROUND",
        "VERIFY",
    }
)
_SWITCH_PREREQUISITE = "ADR015_EXPLICIT_OPERATIONAL_AUTHORITY_REQUIRED"
_SWITCH_PREREQUISITE_REFS = frozenset(
    {
        "LEGACY-CORE-12",
        *(f"LEGACY-CORE-12-{index:02d}" for index in range(1, 10)),
        *(f"LEGACY-REVIEW-{index:02d}" for index in range(12, 15)),
        "LEGACY-CORE-13",
        *(f"LEGACY-CORE-13-{index:02d}" for index in range(1, 5)),
    }
)
_REQUIRED_IGNORE_RULES = (
    "diagnostics/",
    "traces/",
    "replays/local/",
    "audio/raw/",
    ".env",
    ".env.*",
)
_MASTER_BASELINE_RE = re.compile(
    r"^\| Slice 3B\.1 master plan \| [\d,]+ \| `([0-9a-f]{64})` \|$",
    flags=re.MULTILINE,
)
_REGISTER_ROW_RE = re.compile(
    r"^\|\s*(ADR-\d{3})\s*\|.*\|\s*(accepted|proposed|rejected|superseded)"
    r"\s*\|.*\|\s*`([^`]+)`\s*\|$"
)
_ATX_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$")
_FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\((?:<)?([^)>#]+)(?:#[^)>]*)?(?:>)?\)")
_MARKDOWN_ADR_LINK_RE = re.compile(
    r"\[[^\]]+\]\((?:<)?([^)>#]+)#([^)>]+)(?:>)?\)"
)
_INLINE_CODE_RE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
_PATH_SUFFIXES = (
    ".md",
    ".py",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".sh",
    ".toml",
    ".txt",
)
_DATA_URI_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])data:[^\s,<>)\]]*,[^\s<>)\]]*",
    re.IGNORECASE,
)
_PEM_BOUNDARY_RE = re.compile(r"-----BEGIN [A-Z0-9][A-Z0-9 ]+-----")
_RAW_ARTIFACT_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])"
    r"(?:\./|/)?(?:diagnostics|traces|replays/local|audio/raw)/"
    r"[A-Za-z0-9_.-][A-Za-z0-9_./-]*"
)
_DOCUMENT_STEM_RE = re.compile(
    r"^(?P<id>(?P<kind>TC|WP)-[A-Z0-9]+-\d{2})(?:-[a-z0-9]+)*$"
)
_SAFE_OUTPUT_ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9_.:-]{0,127}$")
_SAFE_OUTPUT_PATH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,512}$")
_AUDIT_SCHEMA = "voice_agent.codex_context.audit.v1"


def default_audit_paths(repo_root: Path) -> AuditPaths:
    return AuditPaths(
        repo_root=repo_root,
        legacy_instruction=repo_root / "AGENTS.md",
        candidate_instruction=repo_root
        / "docs/governance/codex-context/AGENTS.candidate.md",
        invariant_map=repo_root
        / "docs/governance/codex-context/invariant-map.md",
        card_root=repo_root
        / "docs/governance/codex-task-cards/slice3b1",
        adr_register=repo_root / "stage_b_adr_register.md",
        master_plan=repo_root
        / "docs/superpowers/plans/"
        "2026-07-27-qwen-slice3b1-protocol-faithful-fake.md",
    )


def run_audit(
    paths: AuditPaths,
    checks: tuple[AuditCheck, ...] = CHECK_ORDER,
) -> AuditReport:
    """Run selected shadow checks without ambient or nondeterministic inputs."""

    ordered_checks, selection_valid = _ordered_checks(checks)
    reports_by_check: dict[AuditCheck, CheckReport] = {}
    for check in ordered_checks:
        reports_by_check[check] = _run_check(paths, check)

    if not selection_valid:
        failure_check = ordered_checks[0] if ordered_checks else CHECK_ORDER[0]
        current = reports_by_check.get(failure_check)
        issues = list(current.issues) if current is not None else []
        issues.append(
            AuditIssue(
                check=failure_check,
                code="AUDIT_CHECK_SELECTION_INVALID",
                rule_id=None,
                relative_path=None,
                line=None,
                severity="error",
            )
        )
        reports_by_check[failure_check] = _report(
            failure_check,
            issues,
            current.checked_count if current is not None else 0,
        )

    reports = tuple(
        reports_by_check[check]
        for check in CHECK_ORDER
        if check in reports_by_check
    )
    prerequisites, prerequisites_valid = _load_switch_prerequisites(paths)
    complete = (
        selection_valid
        and ordered_checks == CHECK_ORDER
        and tuple(report.check for report in reports) == CHECK_ORDER
    )
    switch_ready = (
        complete
        and prerequisites_valid
        and all(report.passed for report in reports)
        and not prerequisites
    )
    return AuditReport(
        reports=reports,
        switch_ready=switch_ready,
        switch_prerequisites=prerequisites,
    )


def render_audit_json(
    report: AuditReport,
    *,
    diagnostic: bool = False,
) -> str:
    """Render only the documented, redacted audit projection."""

    projected_checks = tuple(
        sorted(
            (_project_check(check_report) for check_report in report.reports),
            key=lambda item: CHECK_ORDER.index(item["name"]),
        )
    )
    prerequisites, prerequisites_valid = _project_prerequisites(
        report.switch_prerequisites
    )
    check_names = tuple(item["name"] for item in projected_checks)
    passed = bool(projected_checks) and all(
        item["passed"] for item in projected_checks
    )
    switch_ready = (
        report.switch_ready is True
        and check_names == CHECK_ORDER
        and passed
        and prerequisites_valid
        and not prerequisites
    )
    payload: dict[str, object] = {
        "checks": list(projected_checks),
        "passed": passed,
        "schema": _AUDIT_SCHEMA,
        "switch_prerequisites": list(prerequisites),
        "switch_ready": switch_ready,
    }
    if diagnostic:
        issues = [
            _project_issue(issue, fallback_check=check_report.check)
            for check_report in report.reports
            for issue in check_report.issues
        ]
        payload["issues"] = sorted(
            issues,
            key=lambda item: (
                CHECK_ORDER.index(item["check"]),
                item["code"],
                item["rule_id"] or "",
                item["relative_path"] or "",
                item["line"] or 0,
                item["severity"],
            ),
        )
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    )


def audit_mapping(paths: AuditPaths) -> CheckReport:
    check: AuditCheck = "mapping"
    issues: list[AuditIssue] = []
    if _contained_regular_file(paths, paths.legacy_instruction) is None:
        _add(issues, check, "LEGACY_INVENTORY_INVALID", paths=paths)
        return _report(check, issues, 0)
    try:
        legacy = collect_legacy_rules(paths.legacy_instruction)
    except (OSError, ValueError):
        _add(issues, check, "LEGACY_INVENTORY_INVALID", paths=paths)
        return _report(check, issues, 0)
    if _contained_regular_file(paths, paths.invariant_map) is None:
        _add(issues, check, "INVARIANT_MAP_INVALID", paths=paths)
        return _report(check, issues, len(legacy))
    try:
        mappings = load_invariant_map(paths.invariant_map)
    except (OSError, ValueError):
        _add(issues, check, "INVARIANT_MAP_INVALID", paths=paths)
        return _report(check, issues, len(legacy))
    if _contained_regular_file(paths, paths.candidate_instruction) is None:
        _add(issues, check, "CANDIDATE_DOCUMENT_INVALID", paths=paths)
        return _report(check, issues, len(mappings))
    try:
        candidates = collect_candidate_invariants(paths.candidate_instruction)
    except (OSError, ValueError):
        _add(issues, check, "CANDIDATE_DOCUMENT_INVALID", paths=paths)
        return _report(check, issues, len(mappings))

    legacy_by_ref = {rule.legacy_ref: rule for rule in legacy}
    candidate_by_id = {
        candidate.invariant_id: candidate for candidate in candidates
    }
    mapping_counts = Counter(mapping.legacy_ref for mapping in mappings)
    mapped_refs = set(mapping_counts)
    legacy_refs = set(legacy_by_ref)
    if mapped_refs != legacy_refs:
        _add(issues, check, "LEGACY_MAPPING_SET_MISMATCH", paths=paths)
    for legacy_ref, count in mapping_counts.items():
        if count != 1:
            _add(
                issues,
                check,
                "LEGACY_MAPPING_DUPLICATE",
                rule_id=legacy_ref,
                paths=paths,
            )

    mapped_invariants: set[str] = set()
    for mapping in mappings:
        rule = legacy_by_ref.get(mapping.legacy_ref)
        if rule is not None:
            if mapping.source_heading != rule.source_heading:
                _add_mapping_issue(
                    issues, "LEGACY_SOURCE_HEADING_MISMATCH", mapping, paths
                )
            if mapping.normalized_digest != rule.normalized_digest:
                _add_mapping_issue(
                    issues, "LEGACY_DIGEST_MISMATCH", mapping, paths
                )
        family = _invariant_family(mapping.invariant_id)
        if family not in _APPROVED_FAMILIES:
            _add_mapping_issue(
                issues, "INVARIANT_PREFIX_INVALID", mapping, paths
            )
        if not mapping.auto_context:
            _add_mapping_issue(
                issues, "AUTO_CONTEXT_REQUIRED", mapping, paths
            )
        candidate = candidate_by_id.get(mapping.invariant_id)
        if candidate is None:
            _add_mapping_issue(
                issues, "CANDIDATE_CLAUSE_MISSING", mapping, paths
            )
        else:
            mapped_invariants.add(mapping.invariant_id)
            if mapping.candidate_ref != candidate.heading:
                _add_mapping_issue(
                    issues, "CANDIDATE_HEADING_MISMATCH", mapping, paths
                )
            if (
                mapping.candidate_clause_digest
                != candidate.normalized_clause_digest
            ):
                _add_mapping_issue(
                    issues, "CANDIDATE_DIGEST_MISMATCH", mapping, paths
                )

    candidate_ids = set(candidate_by_id)
    if mapped_invariants != candidate_ids:
        _add(issues, check, "ORPHAN_CANDIDATE_CLAUSE", paths=paths)

    marked_refs = {
        mapping.legacy_ref
        for mapping in mappings
        if mapping.switch_prerequisite is not None
    }
    if marked_refs != _SWITCH_PREREQUISITE_REFS:
        _add(issues, check, "SWITCH_PREREQUISITE_SET_MISMATCH", paths=paths)
    for mapping in mappings:
        prerequisite = mapping.switch_prerequisite
        if prerequisite is None:
            continue
        if (
            prerequisite != _SWITCH_PREREQUISITE
            or _invariant_family(mapping.invariant_id)
            not in {"CONCURRENCY", "VERIFY"}
        ):
            _add_mapping_issue(
                issues, "SWITCH_PREREQUISITE_INVALID", mapping, paths
            )
    return _report(check, issues, len(mappings))


def audit_references(paths: AuditPaths) -> CheckReport:
    check: AuditCheck = "references"
    issues: list[AuditIssue] = []
    if _contained_regular_file(paths, paths.invariant_map) is None:
        _add(issues, check, "REFERENCE_MAP_INVALID", paths=paths)
        return _report(check, issues, 0)
    try:
        mappings = load_invariant_map(paths.invariant_map)
    except (OSError, ValueError):
        _add(issues, check, "REFERENCE_MAP_INVALID", paths=paths)
        return _report(check, issues, 0)
    if _contained_regular_file(paths, paths.candidate_instruction) is None:
        _add(issues, check, "CANDIDATE_DOCUMENT_INVALID", paths=paths)
        return _report(check, issues, len(mappings))
    try:
        candidates = collect_candidate_invariants(paths.candidate_instruction)
    except (OSError, ValueError):
        _add(issues, check, "CANDIDATE_DOCUMENT_INVALID", paths=paths)
        return _report(check, issues, len(mappings))

    register_text = (
        _read_text(paths.adr_register)
        if _contained_regular_file(paths, paths.adr_register) is not None
        else None
    )
    accepted_paths = (
        _accepted_register_paths(register_text) if register_text is not None else set()
    )
    if register_text is None or not accepted_paths:
        _add(issues, check, "ADR_REGISTER_NOT_ACCEPTED", paths=paths)
    candidate_by_id = {
        candidate.invariant_id: candidate for candidate in candidates
    }

    for mapping in mappings:
        candidate = candidate_by_id.get(mapping.invariant_id)
        if candidate is None:
            _add_reference_issue(
                issues, "CANDIDATE_CLAUSE_MISSING", mapping, paths
            )
        else:
            if mapping.candidate_ref != candidate.heading:
                _add_reference_issue(
                    issues, "CANDIDATE_HEADING_MISMATCH", mapping, paths
                )
            if (
                mapping.candidate_clause_digest
                != candidate.normalized_clause_digest
            ):
                _add_reference_issue(
                    issues, "CANDIDATE_DIGEST_MISMATCH", mapping, paths
                )

        for authority in mapping.authority_refs:
            relative = authority.path
            if not _is_adr_relative_path(relative):
                _add_reference_issue(
                    issues,
                    "AUTHORITY_ADR_PATH_INVALID",
                    mapping,
                    paths,
                    relative,
                )
                continue
            resolved = _contained_file(paths, relative)
            if resolved is None:
                _add_reference_issue(
                    issues,
                    "AUTHORITY_PATH_MISSING",
                    mapping,
                    paths,
                    relative,
                )
                continue
            relative_text = relative.as_posix()
            if relative_text not in accepted_paths:
                _add_reference_issue(
                    issues,
                    "AUTHORITY_ADR_NOT_REGISTERED",
                    mapping,
                    paths,
                    relative,
                )
            text = _read_text(resolved)
            if text is None:
                _add_reference_issue(
                    issues,
                    "AUTHORITY_PATH_MISSING",
                    mapping,
                    paths,
                    relative,
                )
                continue
            if not _document_status_is_accepted(text):
                _add_reference_issue(
                    issues,
                    "AUTHORITY_ADR_NOT_ACCEPTED",
                    mapping,
                    paths,
                    relative,
                )
            heading_matches = [
                heading
                for heading in _markdown_headings(text)
                if heading[1] == 2 and heading[2] == authority.heading
            ]
            if len(heading_matches) != 1:
                _add_reference_issue(
                    issues,
                    "AUTHORITY_HEADING_MISSING",
                    mapping,
                    paths,
                    relative,
                )

        for enforcement in mapping.enforcement_refs:
            relative = enforcement.path
            resolved = _contained_file(paths, relative)
            if resolved is None:
                _add_reference_issue(
                    issues,
                    "ENFORCEMENT_PATH_MISSING",
                    mapping,
                    paths,
                    relative,
                )
                continue
            if enforcement.kind == "pytest":
                code = _validate_pytest_symbol(resolved, enforcement.symbol)
            elif enforcement.kind == "script":
                code = _validate_script_symbol(
                    paths, resolved, enforcement.symbol
                )
            else:
                code = _validate_review_check(
                    paths,
                    relative,
                    resolved,
                    enforcement.symbol,
                    accepted_paths,
                )
            if code is not None:
                _add_reference_issue(
                    issues,
                    code,
                    mapping,
                    paths,
                    relative,
                )
    checked = sum(
        len(mapping.authority_refs) + len(mapping.enforcement_refs)
        for mapping in mappings
    )
    return _report(check, issues, checked)


def audit_budgets(paths: AuditPaths) -> CheckReport:
    check: AuditCheck = "budgets"
    issues: list[AuditIssue] = []
    candidate_size = (
        _file_size(paths.candidate_instruction)
        if _contained_regular_file(paths, paths.candidate_instruction)
        is not None
        else None
    )
    register_size = (
        _file_size(paths.adr_register)
        if _contained_regular_file(paths, paths.adr_register) is not None
        else None
    )
    if candidate_size is None:
        _add(issues, check, "CANDIDATE_PATH_MISSING", paths=paths)
        candidate_size = 0
    elif candidate_size > CANDIDATE_MAX_BYTES:
        _add(
            issues,
            check,
            "CANDIDATE_BUDGET_EXCEEDED",
            path=paths.candidate_instruction,
            paths=paths,
        )
    if register_size is None:
        _add(issues, check, "ADR_REGISTER_PATH_MISSING", paths=paths)
        register_size = 0

    cards, packages = _card_documents(paths)
    if _path_exists(paths.card_root) and not _card_root_is_safe(paths):
        _add(
            issues,
            check,
            "CARD_ROOT_INVALID",
            rule_id="TASK-CARD-ROOT",
            path=paths.card_root,
            paths=paths,
        )
    for card in cards:
        stable_id = _stable_document_id(card.stem, "TC")
        if stable_id is None or _contained_regular_file(paths, card) is None:
            _add(
                issues,
                check,
                "CARD_PATH_INVALID",
                rule_id="INVALID-TASK-CARD",
                path=paths.card_root,
                paths=paths,
            )
            continue
        size = _file_size(card)
        if size is None:
            continue
        if size > CARD_MAX_BYTES:
            _add(
                issues,
                check,
                "CARD_BUDGET_EXCEEDED",
                rule_id=stable_id,
                path=card,
                paths=paths,
            )
        if candidate_size + register_size + size > ACTIVE_BUNDLE_RECOMMENDED_BYTES:
            _add(
                issues,
                check,
                "ACTIVE_BUNDLE_RECOMMENDATION_EXCEEDED",
                rule_id=stable_id,
                path=card,
                severity="warning",
                paths=paths,
            )
    for package in packages:
        stable_id = _stable_document_id(package.stem, "WP")
        if stable_id is None or _contained_regular_file(paths, package) is None:
            _add(
                issues,
                check,
                "WORK_PACKAGE_PATH_INVALID",
                rule_id="INVALID-WORK-PACKAGE",
                path=paths.card_root,
                paths=paths,
            )
            continue
        package_size = _file_size(package) or 0
        for card_path in _work_package_card_paths(paths, package):
            resolved_card = _contained_regular_file(paths, card_path)
            if resolved_card is None:
                continue
            card_size = _file_size(resolved_card) or 0
            if (
                candidate_size
                + register_size
                + package_size
                + card_size
                > ACTIVE_BUNDLE_RECOMMENDED_BYTES
            ):
                _add(
                    issues,
                    check,
                    "ACTIVE_BUNDLE_RECOMMENDATION_EXCEEDED",
                    rule_id=stable_id,
                    path=package,
                    severity="warning",
                    paths=paths,
                )
                break
    for document in (*cards, *packages):
        kind = "TC" if document.name.startswith("TC-") else "WP"
        stable_id = _stable_document_id(document.stem, kind)
        if (
            stable_id is None
            or _contained_regular_file(paths, document) is None
        ):
            continue
        text = _read_text(document)
        if text is not None and _has_incomplete_budget_exception(text):
            _add(
                issues,
                check,
                "BUDGET_EXCEPTION_INCOMPLETE",
                rule_id=stable_id,
                path=document,
                paths=paths,
            )
    return _report(check, issues, 2 + len(cards) + len(packages))


def audit_cards(paths: AuditPaths) -> CheckReport:
    check: AuditCheck = "cards"
    issues: list[AuditIssue] = []
    cards, packages = _card_documents(paths)
    if not _card_root_is_safe(paths):
        _add(
            issues,
            check,
            "CARD_ROOT_MISSING",
            path=paths.card_root,
            paths=paths,
        )
        return _report(check, issues, 0)

    candidate_text = (
        _read_text(paths.candidate_instruction)
        if _contained_regular_file(paths, paths.candidate_instruction)
        is not None
        else None
    )
    register_text = (
        _read_text(paths.adr_register)
        if _contained_regular_file(paths, paths.adr_register) is not None
        else ""
    )
    accepted_adr_paths = _accepted_register_paths(register_text or "")
    candidate_lines = (
        _normalized_nonheading_lines(candidate_text)
        if candidate_text is not None
        else Counter()
    )
    candidate_families = (
        _candidate_family_bodies(candidate_text)
        if candidate_text is not None
        else ()
    )

    for card in cards:
        stable_id = _stable_document_id(card.stem, "TC")
        if (
            stable_id is None
            or _contained_regular_file(paths, card) is None
        ):
            _add(
                issues,
                "cards",
                "TASK_CARD_PATH_INVALID",
                rule_id="INVALID-TASK-CARD",
                path=paths.card_root,
                paths=paths,
            )
            continue
        text = _read_text(card)
        if text is None:
            _add_card_issue(
                issues, "TASK_CARD_READ_FAILED", card, paths
            )
            continue
        if not _valid_contract_headings(
            text,
            stable_id,
            TASK_CARD_HEADINGS,
        ):
            _add_card_issue(
                issues,
                "TASK_CARD_HEADING_STRUCTURE_INVALID",
                card,
                paths,
            )
        if _copies_candidate(text, candidate_lines, candidate_families):
            _add_card_issue(
                issues, "TASK_CARD_COPIES_CANDIDATE", card, paths
            )
        _audit_card_paths(
            issues,
            paths,
            card,
            text,
            accepted_adr_paths,
        )

    card_text_by_path: dict[Path, str] = {}
    for card in cards:
        resolved = _contained_regular_file(paths, card)
        text = _read_text(card) if resolved is not None else None
        if resolved is not None and text is not None:
            card_text_by_path[resolved] = text
    for package in packages:
        stable_id = _stable_document_id(package.stem, "WP")
        if (
            stable_id is None
            or _contained_regular_file(paths, package) is None
        ):
            _add(
                issues,
                "cards",
                "WORK_PACKAGE_PATH_INVALID",
                rule_id="INVALID-WORK-PACKAGE",
                path=paths.card_root,
                paths=paths,
            )
            continue
        text = _read_text(package)
        if text is None:
            _add_card_issue(
                issues, "WORK_PACKAGE_READ_FAILED", package, paths
            )
            continue
        if not _valid_contract_headings(
            text,
            stable_id,
            WORK_PACKAGE_HEADINGS,
        ):
            _add_card_issue(
                issues,
                "WORK_PACKAGE_HEADING_STRUCTURE_INVALID",
                package,
                paths,
            )
        referenced = _work_package_card_paths(paths, package)
        if not referenced:
            _add_card_issue(
                issues, "WORK_PACKAGE_CARD_REFERENCE_MISSING", package, paths
            )
        for card_path in referenced:
            resolved = _contained_regular_file(paths, card_path)
            if (
                resolved is None
                or resolved.parent != _contained_path(paths, paths.card_root)
                or _stable_document_id(resolved.stem, "TC") is None
            ):
                _add_card_issue(
                    issues,
                    "WORK_PACKAGE_CARD_MISSING",
                    package,
                    paths,
                )
                continue
            card_text = card_text_by_path.get(resolved)
            if card_text is not None and _copies_document_body(
                text, card_text
            ):
                _add_card_issue(
                    issues,
                    "WORK_PACKAGE_COPIES_CARD_BODY",
                    package,
                    paths,
                )
    return _report(check, issues, len(cards) + len(packages))


def audit_artifacts(paths: AuditPaths) -> CheckReport:
    check: AuditCheck = "artifacts"
    issues: list[AuditIssue] = []
    ignore_path = paths.repo_root / ".gitignore"
    ignore_text = (
        _read_text(ignore_path)
        if _contained_regular_file(paths, ignore_path) is not None
        else None
    )
    normalized_ignore = (
        _normalized_ignore_rules(ignore_text) if ignore_text is not None else set()
    )
    for required in _REQUIRED_IGNORE_RULES:
        if required not in normalized_ignore:
            _add(
                issues,
                check,
                "ARTIFACT_IGNORE_RULE_MISSING",
                rule_id=f"IGNORE-{_safe_rule_fragment(required)}",
                path=paths.repo_root / ".gitignore",
                paths=paths,
            )

    baseline = paths.candidate_instruction.parent / "shadow-baseline.md"
    baseline_text = (
        _read_text(baseline)
        if _contained_regular_file(paths, baseline) is not None
        else None
    )
    matches = (
        _MASTER_BASELINE_RE.findall(baseline_text)
        if baseline_text is not None
        else []
    )
    if len(matches) != 1:
        _add(
            issues,
            check,
            "MASTER_PLAN_BASELINE_INVALID",
            path=baseline,
            paths=paths,
        )
    elif _contained_regular_file(paths, paths.master_plan) is None:
        _add(
            issues,
            check,
            "MASTER_PLAN_MISSING",
            path=paths.master_plan,
            paths=paths,
        )
    elif _sha256(paths.master_plan) != matches[0]:
        _add(
            issues,
            check,
            "MASTER_PLAN_DIGEST_MISMATCH",
            path=paths.master_plan,
            paths=paths,
        )

    cards, packages = _card_documents(paths)
    if _path_exists(paths.card_root) and not _card_root_is_safe(paths):
        _add(
            issues,
            check,
            "ARTIFACT_CARD_ROOT_INVALID",
            rule_id="TASK-CARD-ROOT",
            path=paths.card_root,
            paths=paths,
        )
    scan_paths = (paths.candidate_instruction, *cards, *packages)
    for document in scan_paths:
        is_candidate = document == paths.candidate_instruction
        kind = "TC" if document.name.startswith("TC-") else "WP"
        stable_id = (
            document.stem
            if is_candidate
            else _stable_document_id(document.stem, kind)
        )
        if (
            stable_id is None
            or _contained_regular_file(paths, document) is None
        ):
            _add(
                issues,
                check,
                "ARTIFACT_DOCUMENT_INVALID",
                rule_id=(
                    "CANDIDATE"
                    if is_candidate
                    else "INVALID-TASK-DOCUMENT"
                ),
                path=(
                    paths.candidate_instruction
                    if is_candidate
                    else paths.card_root
                ),
                paths=paths,
            )
            continue
        text = _read_text(document)
        if text is None:
            _add(
                issues,
                check,
                "ARTIFACT_DOCUMENT_MISSING",
                path=document,
                paths=paths,
            )
            continue
        if _DATA_URI_RE.search(text):
            _add(
                issues,
                check,
                "EMBEDDED_DATA_URI",
                rule_id=stable_id,
                path=document,
                paths=paths,
            )
        if _PEM_BOUNDARY_RE.search(text):
            _add(
                issues,
                check,
                "EMBEDDED_PEM_BOUNDARY",
                rule_id=stable_id,
                path=document,
                paths=paths,
            )
        if _RAW_ARTIFACT_PATH_RE.search(text):
            _add(
                issues,
                check,
                "EMBEDDED_RAW_ARTIFACT_PATH",
                rule_id=stable_id,
                path=document,
                paths=paths,
            )

    try:
        if _contained_regular_file(paths, paths.invariant_map) is None:
            raise ValueError("invalid map path")
        mappings = load_invariant_map(paths.invariant_map)
    except (OSError, ValueError):
        _add(
            issues,
            check,
            "ARTIFACT_INVARIANT_MAP_INVALID",
            path=paths.invariant_map,
            paths=paths,
        )
        mappings = ()
    for mapping in mappings:
        if not mapping.legacy_ref.startswith("LEGACY-ARTIFACT-FIXTURE-"):
            continue
        for enforcement in mapping.enforcement_refs:
            if _contained_file(paths, enforcement.path) is None:
                _add(
                    issues,
                    check,
                    "FIXTURE_ENFORCEMENT_PATH_MISSING",
                    rule_id=mapping.legacy_ref,
                    path=paths.repo_root / enforcement.path.as_posix(),
                    paths=paths,
                )
    return _report(check, issues, len(scan_paths) + len(_REQUIRED_IGNORE_RULES) + 1)


def _ordered_checks(
    checks: tuple[AuditCheck, ...],
) -> tuple[tuple[AuditCheck, ...], bool]:
    try:
        requested = tuple(checks)
    except Exception:
        return (), False
    selected: set[AuditCheck] = set()
    valid = bool(requested)
    for check in requested:
        if isinstance(check, str) and check in CHECK_ORDER:
            selected.add(check)
        else:
            valid = False
    return tuple(check for check in CHECK_ORDER if check in selected), valid


def _run_check(paths: AuditPaths, check: AuditCheck) -> CheckReport:
    try:
        if check == "mapping":
            return audit_mapping(paths)
        if check == "references":
            return audit_references(paths)
        if check == "budgets":
            return audit_budgets(paths)
        if check == "cards":
            return audit_cards(paths)
        if check == "artifacts":
            return audit_artifacts(paths)
    except Exception:
        pass
    return CheckReport(
        check=check,
        issues=(
            AuditIssue(
                check=check,
                code="AUDIT_CHECK_FAILED",
                rule_id=None,
                relative_path=None,
                line=None,
                severity="error",
            ),
        ),
        checked_count=0,
    )


def _load_switch_prerequisites(
    paths: AuditPaths,
) -> tuple[tuple[str, ...], bool]:
    if _contained_regular_file(paths, paths.invariant_map) is None:
        return (), False
    try:
        mappings = load_invariant_map(paths.invariant_map)
        values = tuple(
            mapping.switch_prerequisite
            for mapping in mappings
            if mapping.switch_prerequisite is not None
        )
    except Exception:
        return (), False
    if any(_safe_output_id(value) is None for value in values):
        return (), False
    return tuple(sorted(set(values))), True


def _project_check(report: CheckReport) -> dict[str, object]:
    name = _safe_check(report.check)
    severities = tuple(_safe_severity(issue.severity) for issue in report.issues)
    error_count = sum(severity == "error" for severity in severities)
    checked_count = (
        report.checked_count
        if type(report.checked_count) is int and report.checked_count >= 0
        else 0
    )
    return {
        "checked_count": checked_count,
        "error_count": error_count,
        "name": name,
        "passed": error_count == 0,
    }


def _project_issue(
    issue: AuditIssue,
    *,
    fallback_check: AuditCheck,
) -> dict[str, object]:
    check = (
        issue.check
        if isinstance(issue.check, str) and issue.check in CHECK_ORDER
        else _safe_check(fallback_check)
    )
    code = _safe_output_id(issue.code) or "AUDIT_ISSUE_REDACTED"
    rule_id = _safe_output_id(issue.rule_id)
    relative_path = _safe_relative_output_path(issue.relative_path)
    line = issue.line if type(issue.line) is int and issue.line > 0 else None
    return {
        "check": check,
        "code": code,
        "line": line,
        "relative_path": relative_path,
        "rule_id": rule_id,
        "severity": _safe_severity(issue.severity),
    }


def _project_prerequisites(
    prerequisites: tuple[str, ...],
) -> tuple[tuple[str, ...], bool]:
    try:
        values = tuple(prerequisites)
    except Exception:
        return (), False
    projected = tuple(_safe_output_id(value) for value in values)
    if any(value is None for value in projected):
        return (), False
    return tuple(sorted(set(value for value in projected if value is not None))), True


def _safe_check(value: object) -> AuditCheck:
    if isinstance(value, str) and value in CHECK_ORDER:
        return value
    return CHECK_ORDER[0]


def _safe_severity(value: object) -> Severity:
    return "warning" if value == "warning" else "error"


def _safe_output_id(value: object) -> str | None:
    if not isinstance(value, str) or _SAFE_OUTPUT_ID_RE.fullmatch(value) is None:
        return None
    return value


def _safe_relative_output_path(value: object) -> str | None:
    if not isinstance(value, PurePosixPath):
        return None
    rendered = value.as_posix()
    if (
        value.is_absolute()
        or rendered in {"", "."}
        or ".." in value.parts
        or _SAFE_OUTPUT_PATH_RE.fullmatch(rendered) is None
    ):
        return None
    return rendered


def _add_mapping_issue(
    issues: list[AuditIssue],
    code: str,
    mapping: InvariantMapping,
    paths: AuditPaths,
) -> None:
    _add(
        issues,
        "mapping",
        code,
        rule_id=mapping.legacy_ref,
        path=paths.invariant_map,
        paths=paths,
    )


def _add_reference_issue(
    issues: list[AuditIssue],
    code: str,
    mapping: InvariantMapping,
    paths: AuditPaths,
    relative: PurePosixPath | None = None,
) -> None:
    path = (
        paths.repo_root / relative.as_posix()
        if relative is not None
        else paths.invariant_map
    )
    _add(
        issues,
        "references",
        code,
        rule_id=mapping.legacy_ref,
        path=path,
        paths=paths,
    )


def _add_card_issue(
    issues: list[AuditIssue],
    code: str,
    document: Path,
    paths: AuditPaths,
) -> None:
    kind = "TC" if document.name.startswith("TC-") else "WP"
    _add(
        issues,
        "cards",
        code,
        rule_id=_stable_document_id(document.stem, kind) or "TASK-DOCUMENT",
        path=document,
        paths=paths,
    )


def _add(
    issues: list[AuditIssue],
    check: AuditCheck,
    code: str,
    *,
    rule_id: str | None = None,
    path: Path | PurePosixPath | None = None,
    line: int | None = None,
    severity: Severity = "error",
    paths: AuditPaths,
) -> None:
    issues.append(
        AuditIssue(
            check=check,
            code=code,
            rule_id=rule_id,
            relative_path=_relative_path(paths.repo_root, path),
            line=line,
            severity=severity,
        )
    )


def _report(
    check: AuditCheck,
    issues: list[AuditIssue],
    checked_count: int,
) -> CheckReport:
    return CheckReport(
        check=check,
        issues=tuple(sorted(issues, key=_issue_sort_key)),
        checked_count=checked_count,
    )


def _issue_sort_key(
    issue: AuditIssue,
) -> tuple[str, str, str, str, int]:
    return (
        issue.check,
        issue.code,
        issue.rule_id or "",
        issue.relative_path.as_posix() if issue.relative_path is not None else "",
        issue.line or 0,
    )


def _relative_path(
    root: Path,
    path: Path | PurePosixPath | None,
) -> PurePosixPath | None:
    if path is None:
        return None
    candidate = Path(path.as_posix()) if isinstance(path, PurePosixPath) else path
    try:
        resolved_root = root.resolve()
        absolute_candidate = (
            candidate if candidate.is_absolute() else root / candidate
        )
        resolved_candidate = absolute_candidate.resolve()
        return PurePosixPath(
            resolved_candidate.relative_to(resolved_root).as_posix()
        )
    except (OSError, RuntimeError, ValueError):
        return None


def _invariant_family(invariant_id: str) -> str:
    parts = invariant_id.split("-")
    return parts[1] if len(parts) >= 3 else ""


def _read_text(path: Path) -> str | None:
    try:
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode) or path.is_symlink():
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _file_size(path: Path) -> int | None:
    try:
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode) or path.is_symlink():
            return None
        return len(path.read_bytes())
    except OSError:
        return None


def _contained_path(paths: AuditPaths, path: Path) -> Path | None:
    try:
        root = paths.repo_root.resolve()
        candidate = path if path.is_absolute() else paths.repo_root / path
        resolved = candidate.resolve()
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved


def _path_exists(path: Path) -> bool:
    try:
        path.lstat()
    except OSError:
        return False
    return True


def _contained_regular_file(
    paths: AuditPaths,
    path: Path,
) -> Path | None:
    resolved = _contained_path(paths, path)
    lexical = _lexical_repo_path(paths, path)
    if (
        resolved is None
        or lexical is None
        or _has_symlink_below_repo(paths, lexical)
    ):
        return None
    try:
        mode = lexical.lstat().st_mode
    except OSError:
        return None
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        return None
    return resolved


def _lexical_repo_path(paths: AuditPaths, path: Path) -> Path | None:
    try:
        root = Path(os.path.abspath(paths.repo_root))
        candidate = path if path.is_absolute() else paths.repo_root / path
        lexical = Path(os.path.abspath(candidate))
        lexical.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None
    return lexical


def _has_symlink_below_repo(paths: AuditPaths, path: Path) -> bool:
    lexical = _lexical_repo_path(paths, path)
    if lexical is None:
        return True
    root = Path(os.path.abspath(paths.repo_root))
    try:
        relative = lexical.relative_to(root)
    except ValueError:
        return True
    cursor = root
    for component in relative.parts:
        cursor /= component
        try:
            mode = cursor.lstat().st_mode
        except FileNotFoundError:
            return False
        except OSError:
            return True
        if stat.S_ISLNK(mode):
            return True
    return False


def _contained_file(
    paths: AuditPaths,
    relative: PurePosixPath,
) -> Path | None:
    candidate = paths.repo_root / relative.as_posix()
    return _contained_regular_file(paths, candidate)


def _markdown_headings(text: str) -> tuple[tuple[int, int, str], ...]:
    headings: list[tuple[int, int, str]] = []
    fence_marker: str | None = None
    html_comment = False
    for line_number, line in enumerate(text.splitlines(), start=1):
        if fence_marker is not None:
            stripped = line.strip()
            if (
                stripped
                and set(stripped) == {fence_marker[0]}
                and len(stripped) >= len(fence_marker)
            ):
                fence_marker = None
            continue
        if html_comment:
            if "-->" in line:
                html_comment = False
            continue
        if "<!--" in line:
            if "-->" not in line.split("<!--", 1)[1]:
                html_comment = True
            continue
        fence = _FENCE_RE.match(line)
        if fence:
            fence_marker = fence.group(1)
            continue
        match = _ATX_HEADING_RE.fullmatch(line)
        if match:
            headings.append(
                (line_number, len(match.group(1)), match.group(2))
            )
    return tuple(headings)


def _fenced_line_numbers(text: str) -> frozenset[int]:
    fenced: set[int] = set(_html_hidden_line_numbers(text))
    fence_marker: str | None = None
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line_number in fenced:
            continue
        fence = _FENCE_RE.match(line)
        if fence_marker is not None:
            fenced.add(line_number)
            stripped = line.strip()
            if (
                stripped
                and set(stripped) == {fence_marker[0]}
                and len(stripped) >= len(fence_marker)
            ):
                fence_marker = None
            continue
        if fence:
            fence_marker = fence.group(1)
            fenced.add(line_number)
    return frozenset(fenced)


def _html_hidden_line_numbers(text: str) -> frozenset[int]:
    hidden: set[int] = set()
    html_comment = False
    fence_marker: str | None = None
    for line_number, line in enumerate(text.splitlines(), start=1):
        if fence_marker is not None:
            stripped = line.strip()
            if (
                stripped
                and set(stripped) == {fence_marker[0]}
                and len(stripped) >= len(fence_marker)
            ):
                fence_marker = None
            continue
        if html_comment:
            hidden.add(line_number)
            if "-->" in line:
                html_comment = False
            continue
        if "<!--" in line:
            hidden.add(line_number)
            if "-->" not in line.split("<!--", 1)[1]:
                html_comment = True
            continue
        fence = _FENCE_RE.match(line)
        if fence:
            fence_marker = fence.group(1)
    return frozenset(hidden)


def _document_status_is_accepted(text: str) -> bool:
    lines = text.splitlines()
    hidden_lines = _fenced_line_numbers(text)
    status_headings = [
        heading
        for heading in _markdown_headings(text)
        if heading[1] == 2 and heading[2] == "Status"
    ]
    if len(status_headings) != 1:
        return False
    start = status_headings[0][0]
    for line_number, line in enumerate(lines[start:], start=start + 1):
        if line_number in hidden_lines:
            continue
        if _ATX_HEADING_RE.fullmatch(line):
            return False
        if line.strip():
            return line.strip() == "accepted"
    return False


def _accepted_register_paths(text: str) -> set[str]:
    headings = [
        heading
        for heading in _markdown_headings(text)
        if heading[1] == 2 and heading[2] == "ADR Register"
    ]
    if len(headings) != 1:
        return set()
    lines = text.splitlines()
    start = headings[0][0]
    end = len(lines)
    for heading in _markdown_headings(text):
        if heading[0] > start and heading[1] == 2:
            end = heading[0] - 1
            break
    fenced = _fenced_line_numbers(text)
    rows: list[tuple[str, str, str]] = []
    for line_number, line in enumerate(lines[start:end], start=start + 1):
        if line_number in fenced:
            continue
        match = _REGISTER_ROW_RE.fullmatch(line)
        if match:
            rows.append((match.group(1), match.group(2), match.group(3)))
    adr_ids = [row[0] for row in rows]
    paths = [row[2] for row in rows]
    if len(adr_ids) != len(set(adr_ids)) or len(paths) != len(set(paths)):
        return set()
    for adr_id, _, path in rows:
        basename_match = re.fullmatch(
            r"(ADR-\d{3})(?: [^/]+)?\.md",
            PurePosixPath(path).name,
        )
        if basename_match is None or basename_match.group(1) != adr_id:
            return set()
    return {
        path
        for _, status, path in rows
        if status == "accepted"
        and re.fullmatch(r"docs/adr/ADR-[^/]+\.md", path)
    }


def _is_adr_relative_path(path: PurePosixPath) -> bool:
    return (
        re.fullmatch(r"docs/adr/ADR-[^/]+\.md", path.as_posix())
        is not None
    )


def _validate_pytest_symbol(path: Path, symbol: str) -> str | None:
    if path.suffix != ".py" or not symbol.startswith("test_"):
        return "ENFORCEMENT_PYTEST_SYMBOL_INVALID"
    text = _read_text(path)
    if text is None:
        return "ENFORCEMENT_PATH_MISSING"
    try:
        module = ast.parse(text)
    except (SyntaxError, ValueError):
        return "ENFORCEMENT_PYTEST_SYMBOL_INVALID"
    matches = 0
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            matches += int(node.name == symbol and node.name.startswith("test_"))
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    matches += int(
                        child.name == symbol and child.name.startswith("test_")
                    )
    return None if matches == 1 else "ENFORCEMENT_PYTEST_SYMBOL_INVALID"


def _validate_script_symbol(
    paths: AuditPaths,
    path: Path,
    symbol: str,
) -> str | None:
    try:
        mode = path.stat().st_mode
    except OSError:
        return "ENFORCEMENT_PATH_MISSING"
    if not stat.S_ISREG(mode) or not (mode & 0o111) or not os.access(path, os.X_OK):
        return "ENFORCEMENT_SCRIPT_NOT_EXECUTABLE"
    if symbol == "__entrypoint__":
        return None
    sources = [path]
    text = _read_text(path)
    if text is None:
        return "ENFORCEMENT_PATH_MISSING"
    for invoked in _direct_cli_modules(paths, path, text):
        if invoked not in sources:
            sources.append(invoked)
    tokens: set[str] = set()
    for source in sources:
        source_text = _read_text(source)
        if source_text is not None:
            tokens.update(_supported_command_tokens(source_text))
    return None if symbol in tokens else "ENFORCEMENT_SCRIPT_SYMBOL_INVALID"


def _direct_cli_modules(
    paths: AuditPaths,
    script: Path,
    text: str,
) -> tuple[Path, ...]:
    discovered: list[Path] = []
    for logical_line in _shell_executable_lines(text):
        try:
            tokens = shlex.split(logical_line, comments=True, posix=True)
        except ValueError:
            continue
        if not tokens:
            continue
        if tokens[0] == "exec":
            tokens = tokens[1:]
        while tokens and re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*=[^;\n]*", tokens[0]
        ):
            tokens = tokens[1:]
        if len(tokens) < 2:
            continue
        executable = Path(tokens[0]).name
        if re.fullmatch(r"python(?:3(?:\.\d+)?)?", executable) is None:
            continue
        arguments = tokens[1:]
        if len(arguments) >= 2 and arguments[0] == "-m":
            module_name = arguments[1]
            if re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_.]*", module_name
            ) is None:
                continue
            relative = Path(*module_name.split(".")).with_suffix(".py")
            candidates = (
                paths.repo_root / relative,
                paths.repo_root / "src" / relative,
            )
        elif arguments[0].endswith(".py") and re.fullmatch(
            r"[A-Za-z0-9_./-]+\.py", arguments[0]
        ):
            candidates = (
                paths.repo_root / arguments[0],
                script.parent / arguments[0],
            )
        else:
            continue
        for candidate in candidates:
            resolved = _contained_regular_file(paths, candidate)
            if resolved is not None:
                discovered.append(resolved)
                break
    return tuple(discovered)


def _shell_logical_lines(text: str) -> tuple[str, ...]:
    logical: list[str] = []
    pending = ""
    for physical in text.splitlines():
        stripped = physical.rstrip()
        if stripped.endswith("\\"):
            pending += stripped[:-1] + " "
            continue
        logical.append(pending + physical)
        pending = ""
    if pending:
        logical.append(pending)
    return tuple(logical)


def _shell_executable_lines(text: str) -> tuple[str, ...]:
    visible: list[str] = []
    heredoc_delimiter: str | None = None
    heredoc_tabs = False
    heredoc_re = re.compile(
        r"<<(?P<tabs>-)?[ \t]*(?:'(?P<single>[^']+)'|"
        r'"(?P<double>[^"]+)"|(?P<plain>[A-Za-z_][A-Za-z0-9_]*))'
    )
    for line in text.splitlines():
        if heredoc_delimiter is not None:
            terminator = line.lstrip("\t") if heredoc_tabs else line
            if terminator == heredoc_delimiter:
                heredoc_delimiter = None
                heredoc_tabs = False
            continue
        visible.append(line)
        match = heredoc_re.search(line)
        if match is not None:
            heredoc_delimiter = (
                match.group("single")
                or match.group("double")
                or match.group("plain")
            )
            heredoc_tabs = match.group("tabs") is not None
    return _shell_logical_lines("\n".join(visible))


def _supported_command_tokens(text: str) -> set[str]:
    try:
        module = ast.parse(text)
    except (SyntaxError, ValueError):
        return _shell_case_tokens(_shell_executable_lines(text))
    tokens: set[str] = set()
    for node in ast.walk(module):
        if not isinstance(node, ast.Call):
            continue
        name = (
            node.func.attr
            if isinstance(node.func, ast.Attribute)
            else node.func.id
            if isinstance(node.func, ast.Name)
            else ""
        )
        if name == "add_parser" and node.args:
            value = node.args[0]
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                tokens.add(value.value)
        if name == "add_argument":
            for keyword in node.keywords:
                if keyword.arg != "choices":
                    continue
                if isinstance(keyword.value, (ast.List, ast.Tuple, ast.Set)):
                    for item in keyword.value.elts:
                        if isinstance(item, ast.Constant) and isinstance(
                            item.value, str
                        ):
                            tokens.add(item.value)
    return tokens


def _shell_case_tokens(lines: tuple[str, ...]) -> set[str]:
    completed: set[str] = set()
    stack: list[set[str]] = []
    for line in lines:
        stripped = line.strip()
        if re.fullmatch(r"case\b.+\bin", stripped):
            stack.append(set())
            continue
        if stripped == "esac":
            if not stack:
                continue
            block = stack.pop()
            if stack:
                stack[-1].update(block)
            else:
                completed.update(block)
            continue
        if not stack:
            continue
        pattern = re.fullmatch(
            r"([A-Za-z][A-Za-z0-9_-]*(?:\|[A-Za-z][A-Za-z0-9_-]*)*)"
            r"\)[ \t]*(?:#.*)?",
            stripped,
        )
        if pattern is not None:
            stack[-1].update(pattern.group(1).split("|"))
    return completed


def _validate_review_check(
    paths: AuditPaths,
    relative: PurePosixPath,
    path: Path,
    symbol: str,
    accepted_paths: set[str],
) -> str | None:
    permitted: set[Path] = set()
    for candidate in (
        paths.legacy_instruction,
        paths.candidate_instruction,
        *(paths.repo_root / accepted for accepted in accepted_paths),
    ):
        resolved = _contained_regular_file(paths, candidate)
        if resolved is not None:
            permitted.add(resolved)
    if (
        relative.as_posix() == paths.adr_register.name
        or path not in permitted
    ):
        return "ENFORCEMENT_SURFACE_INVALID"
    text = _read_text(path)
    if text is None:
        return "ENFORCEMENT_PATH_MISSING"
    if (
        relative.as_posix() in accepted_paths
        and not _document_status_is_accepted(text)
    ):
        return "ENFORCEMENT_REVIEW_ADR_NOT_ACCEPTED"
    matches = [
        heading
        for heading in _markdown_headings(text)
        if heading[2] == symbol
    ]
    return None if len(matches) == 1 else "ENFORCEMENT_REVIEW_HEADING_INVALID"


def _card_documents(paths: AuditPaths) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    if not _card_root_is_safe(paths):
        return (), ()

    try:
        entries = tuple(paths.card_root.iterdir())
    except OSError:
        return (), ()
    cards = tuple(
        sorted(
            (
                entry
                for entry in entries
                if entry.name.startswith("TC-") and entry.suffix == ".md"
            ),
            key=lambda path: path.name,
        )
    )
    packages = tuple(
        sorted(
            (
                entry
                for entry in entries
                if entry.name.startswith("WP-") and entry.suffix == ".md"
            ),
            key=lambda path: path.name,
        )
    )
    return cards, packages


def _card_root_is_safe(paths: AuditPaths) -> bool:
    try:
        root_mode = paths.card_root.lstat().st_mode
    except OSError:
        return False
    return not (
        paths.card_root.is_symlink()
        or not stat.S_ISDIR(root_mode)
        or _contained_path(paths, paths.card_root) is None
        or _has_symlink_below_repo(paths, paths.card_root)
    )


def _valid_contract_headings(
    text: str,
    document_id: str,
    required: tuple[str, ...],
) -> bool:
    headings = _markdown_headings(text)
    h1 = [heading for heading in headings if heading[1] == 1]
    h2 = [heading for heading in headings if heading[1] == 2]
    first_nonempty_line = next(
        (
            index
            for index, line in enumerate(text.splitlines(), start=1)
            if line.strip()
        ),
        0,
    )
    if (
        len(h1) != 1
        or not headings
        or headings[0] != h1[0]
        or h1[0][0] != first_nonempty_line
        or not _contains_exact_id(h1[0][2], document_id)
    ):
        return False
    allowed_h2 = list(required)
    if any(heading[2] == BUDGET_EXCEPTION_HEADING for heading in h2):
        allowed_h2.append(BUDGET_EXCEPTION_HEADING)
    if [heading[2] for heading in h2] != allowed_h2:
        return False
    if len({heading[2] for heading in h2}) != len(h2):
        return False
    lines = text.splitlines()
    html_hidden = _html_hidden_line_numbers(text)
    for index, heading in enumerate(h2):
        start = heading[0]
        end = h2[index + 1][0] - 1 if index + 1 < len(h2) else len(lines)
        section_lines = (
            (line_number, lines[line_number - 1])
            for line_number in range(start + 1, end + 1)
        )
        if not any(
            line_number not in html_hidden
            and line.strip()
            and _ATX_HEADING_RE.fullmatch(line) is None
            for line_number, line in section_lines
        ):
            return False
    first_section = _section_text(text, required[0])
    first_hidden = _html_hidden_line_numbers(first_section)
    first_body = "\n".join(
        line
        for line_number, line in enumerate(
            first_section.splitlines(),
            start=1,
        )
        if line_number not in first_hidden
    )
    return _contains_exact_id(first_body, document_id)


def _stable_document_id(stem: str, kind: str) -> str | None:
    match = _DOCUMENT_STEM_RE.fullmatch(stem)
    if match is None or match.group("kind") != kind:
        return None
    return match.group("id")


def _contains_exact_id(value: str, document_id: str) -> bool:
    return (
        re.search(
            rf"(?<![A-Za-z0-9_-]){re.escape(document_id)}"
            r"(?![A-Za-z0-9_-])",
            value,
        )
        is not None
    )


def _section_text(text: str, heading_name: str) -> str:
    headings = _markdown_headings(text)
    target = next(
        (
            heading
            for heading in headings
            if heading[1] == 2 and heading[2] == heading_name
        ),
        None,
    )
    if target is None:
        return ""
    lines = text.splitlines()
    start = target[0]
    end = len(lines)
    for heading in headings:
        if heading[0] > target[0] and heading[1] == 2:
            end = heading[0] - 1
            break
    return "\n".join(lines[start:end])


def _adr_section_references(
    text: str,
) -> tuple[tuple[str, bool, str], ...]:
    references: list[tuple[str, bool, str]] = []
    fenced = _fenced_line_numbers(text)
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line_number in fenced:
            continue
        for match in _MARKDOWN_ADR_LINK_RE.finditer(line):
            path_token = unquote(match.group(1).strip())
            heading_name = unquote(match.group(2).strip())
            if (
                Path(path_token).name.startswith("ADR-")
                and path_token.endswith(".md")
                and heading_name
            ):
                references.append((path_token, True, heading_name))
        spans = tuple(_INLINE_CODE_RE.finditer(line))
        for index, path_match in enumerate(spans[:-1]):
            path_token = path_match.group(1).strip()
            if (
                not Path(path_token).name.startswith("ADR-")
                or not path_token.endswith(".md")
            ):
                continue
            heading_match = spans[index + 1]
            separator = line[path_match.end() : heading_match.start()]
            if re.fullmatch(r"[ \t]*(?:—|-)[ \t]*", separator) is None:
                continue
            heading_name = heading_match.group(1).strip()
            if heading_name:
                references.append((path_token, False, heading_name))
    return tuple(dict.fromkeys(references))


def _audit_card_paths(
    issues: list[AuditIssue],
    paths: AuditPaths,
    card: Path,
    text: str,
    accepted_adr_paths: set[str],
) -> None:
    allowed = _section_text(text, "Allowed write files")
    write_references = _path_references(allowed)
    if not write_references:
        _add_card_issue(
            issues, "TASK_CARD_WRITE_PATH_REQUIRED", card, paths
        )
    for token, is_link in write_references:
        candidate = _declared_path(paths, card, token, is_link)
        if candidate is None or (
            _path_exists(candidate)
            and _contained_regular_file(paths, candidate) is None
        ):
            _add_card_issue(
                issues, "TASK_CARD_WRITE_PATH_INVALID", card, paths
            )
    dependencies = _section_text(text, "Required read-only dependencies")
    for token, is_link in _path_references(dependencies):
        candidate = _declared_path(paths, card, token, is_link)
        if candidate is None or _contained_regular_file(paths, candidate) is None:
            _add_card_issue(
                issues, "TASK_CARD_DEPENDENCY_MISSING", card, paths
            )
    adr_section = _section_text(text, "Exact ADR sections")
    adr_references = _adr_section_references(adr_section)
    if not adr_references:
        _add_card_issue(
            issues, "TASK_CARD_ADR_REFERENCE_REQUIRED", card, paths
        )
    for token, is_link, heading_name in adr_references:
        candidate = _declared_path(paths, card, token, is_link)
        resolved = (
            _contained_regular_file(paths, candidate)
            if candidate is not None
            else None
        )
        relative = (
            _relative_path(paths.repo_root, resolved)
            if resolved is not None
            else None
        )
        adr_text = _read_text(resolved) if resolved is not None else None
        heading_matches = (
            [
                item
                for item in _markdown_headings(adr_text)
                if item[1] == 2 and item[2] == heading_name
            ]
            if adr_text is not None
            else []
        )
        if (
            resolved is None
            or relative is None
            or not _is_adr_relative_path(relative)
            or relative.as_posix() not in accepted_adr_paths
            or adr_text is None
            or not _document_status_is_accepted(adr_text)
            or len(heading_matches) != 1
        ):
            _add_card_issue(
                issues, "TASK_CARD_ADR_REFERENCE_INVALID", card, paths
            )


def _path_references(text: str) -> tuple[tuple[str, bool], ...]:
    references: list[tuple[str, bool]] = []
    hidden = _fenced_line_numbers(text)
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line_number in hidden:
            continue
        link_spans: list[tuple[int, int]] = []
        for match in _MARKDOWN_LINK_RE.finditer(line):
            references.append((match.group(1).strip(), True))
            link_spans.append(match.span())
        for match in _INLINE_CODE_RE.finditer(line):
            if any(start <= match.start() < end for start, end in link_spans):
                continue
            token = match.group(1).strip()
            if _looks_like_path(token):
                references.append((token, False))
    return tuple(references)


def _looks_like_path(token: str) -> bool:
    return (
        "/" in token
        or token.startswith(".")
        or token.endswith(_PATH_SUFFIXES)
    )


def _declared_path(
    paths: AuditPaths,
    document: Path,
    token: str,
    is_link: bool,
) -> Path | None:
    if (
        not token
        or token.endswith("/")
        or "\\" in token
        or Path(token).is_absolute()
        or any(ord(character) < 32 or ord(character) == 127 for character in token)
        or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", token) is not None
        or any(character in token for character in "*?[")
        or token.startswith("~")
        or any(character in token for character in "$;&|><!{}()`\"'")
    ):
        return None
    if not is_link and ".." in Path(token).parts:
        return None
    if is_link:
        candidate = document.parent / token
    else:
        candidate = paths.repo_root / token
    return (
        candidate
        if _contained_path(paths, candidate) is not None
        else None
    )


def _work_package_card_paths(
    paths: AuditPaths,
    package: Path,
) -> tuple[Path, ...]:
    text = _read_text(package)
    if text is None:
        return ()
    section = _section_text(
        text, "Ordered or dependency-based Task Card list"
    )
    discovered: list[Path] = []
    for token, is_link in _path_references(section):
        if "TC-" not in Path(token).name or not token.endswith(".md"):
            continue
        path = _declared_path(paths, package, token, is_link)
        if path is not None and path not in discovered:
            discovered.append(path)
        elif path is None:
            discovered.append(package.parent / token)
    return tuple(discovered)


def _normalized_nonheading_lines(text: str) -> Counter[str]:
    return Counter(
        normalize_requirement(line)
        for line in text.splitlines()
        if line.strip() and _ATX_HEADING_RE.fullmatch(line) is None
    )


def _candidate_family_bodies(text: str) -> tuple[Counter[str], ...]:
    headings = _markdown_headings(text)
    lines = text.splitlines()
    bodies: list[Counter[str]] = []
    families = [
        heading
        for heading in headings
        if heading[1] == 3 and heading[2].startswith("INV-")
    ]
    for family in families:
        start = family[0]
        end = len(lines)
        for heading in headings:
            if heading[0] > family[0] and heading[1] <= 3:
                end = heading[0] - 1
                break
        body = Counter(
            normalize_requirement(line)
            for line in lines[start:end]
            if line.strip() and _ATX_HEADING_RE.fullmatch(line) is None
        )
        if body:
            bodies.append(body)
    return tuple(bodies)


def _copies_candidate(
    card_text: str,
    candidate_lines: Counter[str],
    candidate_families: tuple[Counter[str], ...],
) -> bool:
    if not candidate_lines:
        return False
    card_lines = _normalized_nonheading_lines(card_text)
    matched = sum((card_lines & candidate_lines).values())
    over_seventy_percent = matched * 100 > sum(candidate_lines.values()) * 70
    contains_all_families = (
        len(candidate_families) == 10
        and all((body - card_lines) == Counter() for body in candidate_families)
    )
    return over_seventy_percent or contains_all_families


def _copies_document_body(container_text: str, source_text: str) -> bool:
    source_lines = _normalized_nonheading_lines(source_text)
    if not source_lines:
        return False
    container_lines = _normalized_nonheading_lines(container_text)
    matched = sum((container_lines & source_lines).values())
    return matched * 100 > sum(source_lines.values()) * 70


def _has_incomplete_budget_exception(text: str) -> bool:
    headings = _markdown_headings(text)
    exception = next(
        (
            heading
            for heading in headings
            if heading[1] == 2 and heading[2] == BUDGET_EXCEPTION_HEADING
        ),
        None,
    )
    if exception is None:
        return False
    section = _section_text(text, BUDGET_EXCEPTION_HEADING)
    hidden = _fenced_line_numbers(section)
    bullet_values: dict[str, list[str]] = {
        field: [] for field in BUDGET_EXCEPTION_FIELDS
    }
    for line_number, line in enumerate(section.splitlines(), start=1):
        if line_number in hidden:
            continue
        for field in BUDGET_EXCEPTION_FIELDS:
            match = re.fullmatch(
                rf"[ \t]*-[ \t]+{re.escape(field)}:[ \t]*(.*)",
                line,
            )
            if match is not None:
                bullet_values[field].append(match.group(1).strip())

    h3 = [
        heading
        for heading in _markdown_headings(section)
        if heading[1] == 3
    ]
    has_bullets = any(bullet_values.values())
    has_h3 = bool(h3)
    if has_bullets and has_h3:
        return True
    if has_bullets:
        return any(
            len(bullet_values[field]) != 1
            or not bullet_values[field][0]
            for field in BUDGET_EXCEPTION_FIELDS
        )
    if not has_h3 or [heading[2] for heading in h3] != list(
        BUDGET_EXCEPTION_FIELDS
    ):
        return True

    lines = section.splitlines()
    known_bullet_re = re.compile(
        r"^[ \t]*-[ \t]+(?:"
        + "|".join(re.escape(field) for field in BUDGET_EXCEPTION_FIELDS)
        + r"):[ \t]*"
    )
    for index, heading in enumerate(h3):
        start = heading[0]
        end = h3[index + 1][0] - 1 if index + 1 < len(h3) else len(lines)
        values = [
            line.strip()
            for line_number, line in enumerate(
                lines[start:end],
                start=start + 1,
            )
            if line_number not in hidden
            and line.strip()
            and _ATX_HEADING_RE.fullmatch(line) is None
        ]
        if (
            not values
            or known_bullet_re.match(values[0]) is not None
        ):
            return True
    return False


def _normalized_ignore_rules(text: str) -> set[str]:
    active: set[str] = set()
    representatives = {
        "diagnostics/": "diagnostics/probe.jsonl",
        "traces/": "traces/probe.jsonl",
        "replays/local/": "replays/local/probe.json",
        "audio/raw/": "audio/raw/probe.wav",
        ".env": ".env",
        ".env.*": ".env.secret",
    }
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        negated = stripped.startswith("!")
        body = stripped[1:] if negated else stripped
        normalized = body.removeprefix("/")
        if normalized.endswith("/**"):
            normalized = normalized[:-2]
        for required in _REQUIRED_IGNORE_RULES:
            affects_required = normalized == required
            if required.endswith("/") and normalized.startswith(required):
                affects_required = True
            if required == ".env":
                affects_required = normalized in {".env", ".env*"}
            if required == ".env.*":
                affects_required = normalized in {".env.*", ".env*"} or (
                    negated and normalized.startswith(".env.")
                )
            if negated and fnmatchcase(
                representatives[required],
                normalized,
            ):
                affects_required = True
            if not affects_required:
                continue
            if negated:
                active.discard(required)
            elif normalized == required or normalized == ".env*":
                active.add(required)
    return active


def _safe_rule_fragment(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").upper()


def _sha256(path: Path) -> str | None:
    try:
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode) or path.is_symlink():
            return None
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(64 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


__all__ = (
    "ACTIVE_BUNDLE_RECOMMENDED_BYTES",
    "BUDGET_EXCEPTION_FIELDS",
    "BUDGET_EXCEPTION_HEADING",
    "CANDIDATE_MAX_BYTES",
    "CARD_MAX_BYTES",
    "CHECK_ORDER",
    "TASK_CARD_HEADINGS",
    "WORK_PACKAGE_HEADINGS",
    "audit_artifacts",
    "audit_budgets",
    "audit_cards",
    "audit_mapping",
    "audit_references",
    "default_audit_paths",
    "render_audit_json",
    "run_audit",
)
