from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal


AuditCheck = Literal["mapping", "references", "budgets", "cards", "artifacts"]
Severity = Literal["error", "warning"]
EnforcementKind = Literal["pytest", "script", "review-check"]
LegacySourceKind = Literal[
    "preamble-rule",
    "ordered-rule",
    "nested-rule",
    "section-rule",
    "standalone-rule",
]


@dataclass(frozen=True)
class LegacyRule:
    legacy_ref: str
    source_heading: str
    source_kind: LegacySourceKind
    normalized_digest: str


@dataclass(frozen=True)
class AuthorityRef:
    path: PurePosixPath
    heading: str


@dataclass(frozen=True)
class EnforcementRef:
    kind: EnforcementKind
    path: PurePosixPath
    symbol: str


@dataclass(frozen=True)
class CandidateInvariant:
    invariant_id: str
    heading: str
    normalized_clause_digest: str


@dataclass(frozen=True)
class InvariantMapping:
    legacy_ref: str
    legacy_summary: str
    source_heading: str
    normalized_digest: str
    invariant_id: str
    candidate_ref: str
    candidate_clause_digest: str
    authority_refs: tuple[AuthorityRef, ...]
    enforcement_refs: tuple[EnforcementRef, ...]
    auto_context: bool
    equivalence_note: str
    switch_prerequisite: str | None


@dataclass(frozen=True)
class AuditPaths:
    repo_root: Path
    legacy_instruction: Path
    candidate_instruction: Path
    invariant_map: Path
    card_root: Path
    adr_register: Path
    master_plan: Path


@dataclass(frozen=True)
class AuditIssue:
    check: AuditCheck
    code: str
    rule_id: str | None
    relative_path: PurePosixPath | None
    line: int | None
    severity: Severity = "error"


@dataclass(frozen=True)
class CheckReport:
    check: AuditCheck
    issues: tuple[AuditIssue, ...]
    checked_count: int

    @property
    def passed(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)


@dataclass(frozen=True)
class AuditReport:
    reports: tuple[CheckReport, ...]
    switch_ready: bool
    switch_prerequisites: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return all(report.passed for report in self.reports)


@dataclass(frozen=True)
class SnapshotRequest:
    repo_root: Path
    output_root: Path
    candidate_instruction: PurePosixPath
    baseline_entry: PurePosixPath
    candidate_entry: PurePosixPath
    selected_uncommitted: tuple[PurePosixPath, ...] = ()


@dataclass(frozen=True)
class SourceEntry:
    relative_path: PurePosixPath
    sha256: str
    size_bytes: int
    origin: Literal["tracked", "selected-uncommitted", "overlay"]


@dataclass(frozen=True)
class SnapshotPairManifest:
    schema: str
    pair_digest: str
    pair_name: str
    anchor_kind: Literal["system-temp", "ignored-repo-diagnostics"]
    anchor_digest: str
    source_entries: tuple[SourceEntry, ...]
    expected_differences: tuple[PurePosixPath, ...]


@dataclass(frozen=True)
class SnapshotVerification:
    passed: bool
    issue_codes: tuple[str, ...]
    observed_differences: tuple[PurePosixPath, ...]


__all__ = (
    "AuditCheck",
    "AuditIssue",
    "AuditPaths",
    "AuditReport",
    "AuthorityRef",
    "CandidateInvariant",
    "CheckReport",
    "EnforcementKind",
    "EnforcementRef",
    "InvariantMapping",
    "LegacyRule",
    "LegacySourceKind",
    "Severity",
    "SnapshotPairManifest",
    "SnapshotRequest",
    "SnapshotVerification",
    "SourceEntry",
)
