from __future__ import annotations

import ast
import json
import os
import re
from collections import Counter
from pathlib import Path

import pytest

from voice_agent.governance.codex_context.audit import (
    audit_mapping,
    audit_references,
    default_audit_paths,
)
from voice_agent.governance.codex_context.markdown import (
    collect_candidate_invariants,
    collect_candidate_invariants_from_text,
    collect_legacy_rules,
    collect_legacy_rules_from_text,
    load_invariant_map,
    load_invariant_map_from_text,
    normalize_requirement,
)
from voice_agent.governance.codex_context.model import InvariantMapping


ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / "docs/governance/codex-context/AGENTS.candidate.md"
INVARIANT_MAP = ROOT / "docs/governance/codex-context/invariant-map.md"
ADR_REGISTER = ROOT / "stage_b_adr_register.md"
APPROVED_FAMILIES = {
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
INVARIANT_ID_RE = re.compile(
    r"^INV-(ADR|ADAPTER|JOURNAL|PLAN|TOOL|COMMITMENT|PRIVACY|"
    r"CONCURRENCY|FOREGROUND|VERIFY)-\d{2}$"
)


def test_normalization_is_independent_of_line_wrapping_and_line_numbers() -> None:
    assert normalize_requirement("alpha\n  beta  `x`") == "alpha beta `x`"
    assert normalize_requirement("alpha beta `x`") == "alpha beta `x`"


def test_live_legacy_inventory_has_exact_expected_coverage() -> None:
    rules = collect_legacy_rules(ROOT / "AGENTS.md")
    assert len(rules) == 111
    assert len({rule.legacy_ref for rule in rules}) == 111
    assert len({rule.normalized_digest for rule in rules}) == 111
    assert {rule.source_kind for rule in rules} == {
        "preamble-rule",
        "ordered-rule",
        "nested-rule",
        "section-rule",
        "standalone-rule",
    }


def test_inventory_rejects_a_missing_governance_section(tmp_path: Path) -> None:
    path = tmp_path / "AGENTS.md"
    path.write_text("# AGENTS.md\n\n## Core Rules\n\n1. rule\n", encoding="utf-8")
    try:
        collect_legacy_rules(path)
    except ValueError as exc:
        assert str(exc) == "legacy_instruction_missing_required_sections"
    else:
        raise AssertionError("missing governance sections must fail closed")


def test_collector_is_invariant_to_lazy_and_indented_item_rewrapping() -> None:
    original = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    rewrapped = original
    replacements = {
        "本文件是 voice-agent 仓库的开发治理入口": (
            "本文件是 voice-agent\n仓库的开发治理入口"
        ),
        "2. **No direct external model calls outside adapters": (
            "2. **No direct external model calls\noutside adapters"
        ),
        "   - 每个 adapter 必须声明 capability matrix": (
            "   - 每个 adapter 必须声明\n     capability matrix"
        ),
        "- MVP-0: event-driven live loop": "- MVP-0: event-driven\n  live loop",
        "- raw debug trace\n- local replay cache": (
            "- raw\n  debug trace\n- local replay cache"
        ),
        "- Raw audio must never be committed.": (
            "- Raw audio must never\n  be committed."
        ),
        "- calls external model services directly instead of using adapters": (
            "- calls external model services directly\n  instead of using adapters"
        ),
        "当前已接受 ADR 以 `stage_b_adr_register.md` 为准。": (
            "当前已接受 ADR 以 `stage_b_adr_register.md`\n为准。"
        ),
    }
    for compact, wrapped in replacements.items():
        assert rewrapped.count(compact) == 1
        rewrapped = rewrapped.replace(compact, wrapped)

    assert collect_legacy_rules_from_text(rewrapped) == (
        collect_legacy_rules_from_text(original)
    )


def test_mapping_requires_exactly_one_primary_row_per_legacy_rule() -> None:
    legacy = collect_legacy_rules(ROOT / "AGENTS.md")
    mappings = load_invariant_map(INVARIANT_MAP)
    legacy_by_ref = {rule.legacy_ref: rule for rule in legacy}
    counts = Counter(mapping.legacy_ref for mapping in mappings)

    assert len(mappings) == 111
    assert set(counts) == set(legacy_by_ref)
    assert set(counts.values()) == {1}
    assert Counter(
        mapping.invariant_id.split("-")[1] for mapping in mappings
    ) == {
        "ADR": 16,
        "ADAPTER": 5,
        "JOURNAL": 8,
        "PLAN": 7,
        "TOOL": 11,
        "COMMITMENT": 5,
        "PRIVACY": 28,
        "CONCURRENCY": 13,
        "FOREGROUND": 9,
        "VERIFY": 9,
    }
    for mapping in mappings:
        source = legacy_by_ref[mapping.legacy_ref]
        assert mapping.source_heading == source.source_heading
        assert mapping.normalized_digest == source.normalized_digest
        match = INVARIANT_ID_RE.fullmatch(mapping.invariant_id)
        assert match is not None
        assert match.group(1) in APPROVED_FAMILIES


def test_mapping_rejects_candidate_invariant_without_accepted_authority() -> None:
    mappings = load_invariant_map(INVARIANT_MAP)
    candidates = collect_candidate_invariants(CANDIDATE)
    accepted_paths = _accepted_adr_paths()
    mappings_by_invariant: dict[str, list[object]] = {}
    for mapping in mappings:
        mappings_by_invariant.setdefault(mapping.invariant_id, []).append(mapping)

    assert {candidate.invariant_id for candidate in candidates} == set(
        mappings_by_invariant
    )
    for candidate in candidates:
        rows = mappings_by_invariant[candidate.invariant_id]
        assert rows
        for row in rows:
            assert row.authority_refs
            for authority in row.authority_refs:
                relative_path = authority.path.as_posix()
                assert relative_path in accepted_paths
                text = (ROOT / relative_path).read_text(encoding="utf-8")
                assert f"## {authority.heading}" in text.splitlines()


def test_mapping_requires_existing_enforcement_reference() -> None:
    mappings = load_invariant_map(INVARIANT_MAP)
    for mapping in mappings:
        assert mapping.enforcement_refs
        for enforcement in mapping.enforcement_refs:
            path = ROOT / enforcement.path.as_posix()
            assert path.is_file()
            if enforcement.kind == "pytest":
                module = ast.parse(path.read_text(encoding="utf-8"))
                functions = {
                    node.name
                    for node in module.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
                assert enforcement.symbol in functions
            elif enforcement.kind == "review-check":
                assert f"## {enforcement.symbol}" in path.read_text(
                    encoding="utf-8"
                ).splitlines()
            elif enforcement.kind == "script":
                assert path.stat().st_mode & 0o111
                if enforcement.symbol != "__entrypoint__":
                    assert enforcement.symbol in path.read_text(encoding="utf-8")
            else:
                raise AssertionError(f"unexpected enforcement kind: {enforcement.kind}")


def test_high_risk_rows_use_truthful_authority_and_enforcement() -> None:
    mappings = load_invariant_map(INVARIANT_MAP)
    by_ref = {mapping.legacy_ref: mapping for mapping in mappings}

    adapter_refs = _enforcement_keys(by_ref["LEGACY-CORE-02-03"])
    assert adapter_refs == {
        (
            "pytest",
            "tests/adapters/test_mock_capability_snapshot.py",
            "test_mvp0_mock_adapters_declare_required_capability_fields",
        ),
        (
            "pytest",
            "tests/adapters/test_mock_capability_snapshot.py",
            "test_startup_snapshot_records_modes_needed_for_replay_without_adapter_probe",
        ),
        (
            "review-check",
            "docs/adr/ADR-011 Model Adapter Capability Contract.md",
            "Validation Method",
        ),
    }

    privacy_required = {
        (
            "pytest",
            "tests/events/test_event_journal.py",
            "test_journal_redacts_secret_like_payload_fields_before_append",
        ),
        (
            "pytest",
            "tests/events/test_event_journal.py",
            "test_journal_blocks_raw_or_unredactable_sensitive_payloads",
        ),
        (
            "review-check",
            "docs/adr/ADR-010 Trace Replay Debug Policy for Web Demo.md",
            "Validation Method",
        ),
    }
    for legacy_ref in (
        "LEGACY-CORE-06-01",
        "LEGACY-CORE-06-02",
        "LEGACY-ARTIFACT-05",
        "LEGACY-REVIEW-08",
    ):
        assert privacy_required <= _enforcement_keys(by_ref[legacy_ref])

    assert (
        "pytest",
        "tests/replay/test_fixture_safety.py",
        "test_empty_session_fixture_lives_in_github_allowed_fixture_dir",
    ) in _enforcement_keys(by_ref["LEGACY-ARTIFACT-04"])

    adr018_review = (
        "review-check",
        "docs/adr/ADR-015 Repository Governance and AGENTS.md Rules.md",
        "ADR-018 Repository Review Addendum",
    )
    assert _enforcement_keys(by_ref["LEGACY-REVIEW-21"]) == {adr018_review}
    assert adr018_review in _enforcement_keys(by_ref["LEGACY-REVIEW-22"])
    assert (
        "pytest",
        "tests/runtime/test_slice3b1_context_projection.py",
        "test_projection_rejects_cross_session_uncommitted_or_over_bound_input",
    ) in _enforcement_keys(by_ref["LEGACY-REVIEW-22"])
    for legacy_ref in (
        "LEGACY-REVIEW-10",
        "LEGACY-REVIEW-17",
        "LEGACY-REVIEW-18",
    ):
        assert adr018_review in _enforcement_keys(by_ref[legacy_ref])

    adr015_decision = (
        "docs/adr/ADR-015 Repository Governance and AGENTS.md Rules.md",
        "Decision",
    )
    for mapping in mappings:
        if mapping.invariant_id == "INV-ADR-02":
            assert adr015_decision in {
                (ref.path.as_posix(), ref.heading)
                for ref in mapping.authority_refs
            }

    verify_enforcement = {
        (
            "pytest",
            "tests/governance/test_codex_context_mapping.py",
            "test_candidate_states_reviewed_operational_terms_directly",
        ),
        ("script", "scripts/test", "__entrypoint__"),
        ("review-check", "AGENTS.md", "基本原则 / Core Rules"),
    }
    for legacy_ref in (
        "LEGACY-CORE-13",
        *(f"LEGACY-CORE-13-{index:02d}" for index in range(1, 5)),
    ):
        assert verify_enforcement <= _enforcement_keys(by_ref[legacy_ref])


def test_candidate_states_reviewed_operational_terms_directly() -> None:
    candidate = normalize_requirement(CANDIDATE.read_text(encoding="utf-8"))
    required = (
        "Quick = local/reversible, one boundary, direct existing validation, "
        "no ADR/architecture change.",
        "Any accepted-boundary touch uses a linked Task Card",
        "Work Package = dependencies across multiple independent cards only.",
        "New architecture/scope: stop for ADR/mode upgrade, not automatic "
        "Work Package.",
        "truthful capability matrix",
        "per-session append-only journal",
        "ADR-016 gates confirmation/cancel/tool authorization",
        "every SpokenPlan passes both CommitmentCoverageCheck and "
        "ProgressTruthfulnessCheck",
        "enters trace/repo; redact/block captured adapter/tool results "
        "before any write",
        "metadata replay fixtures in approved test-fixture directories",
        "neither threads nor async scheduling order advances critical state",
        "slice threads never try multiple network install paths",
    )
    for phrase in required:
        assert phrase in candidate


def test_mapping_marks_only_known_operational_authority_gaps() -> None:
    mappings = load_invariant_map(INVARIANT_MAP)
    expected_refs = {
        "LEGACY-CORE-12",
        *(f"LEGACY-CORE-12-{index:02d}" for index in range(1, 10)),
        *(f"LEGACY-REVIEW-{index:02d}" for index in range(12, 15)),
        "LEGACY-CORE-13",
        *(f"LEGACY-CORE-13-{index:02d}" for index in range(1, 5)),
    }
    marked = {
        mapping.legacy_ref
        for mapping in mappings
        if mapping.switch_prerequisite is not None
    }

    assert marked == expected_refs
    assert {
        mapping.switch_prerequisite
        for mapping in mappings
        if mapping.switch_prerequisite is not None
    } == {"ADR015_EXPLICIT_OPERATIONAL_AUTHORITY_REQUIRED"}
    assert all(
        mapping.invariant_id.startswith(("INV-CONCURRENCY-", "INV-VERIFY-"))
        for mapping in mappings
        if mapping.switch_prerequisite is not None
    )


def test_mapping_resolves_every_candidate_ref_and_invariant_clause() -> None:
    mappings = load_invariant_map(INVARIANT_MAP)
    candidates = collect_candidate_invariants(CANDIDATE)
    candidate_by_id = {
        candidate.invariant_id: candidate for candidate in candidates
    }

    _assert_candidate_mapping_is_closed(mappings, candidates)
    assert len(CANDIDATE.read_bytes()) <= 6_144
    assert len({candidate.heading for candidate in candidates}) == 10
    for mapping in mappings:
        candidate = candidate_by_id[mapping.invariant_id]
        assert mapping.candidate_ref == candidate.heading
        assert mapping.candidate_clause_digest == candidate.normalized_clause_digest
        if mapping.auto_context:
            assert mapping.invariant_id in candidate_by_id


def test_mapping_rejects_orphan_candidate_invariant(tmp_path: Path) -> None:
    candidate_text = CANDIDATE.read_text(encoding="utf-8")
    orphaned = candidate_text.replace(
        "### INV-ADAPTER —",
        "- INV-ADR-99: An intentionally unmapped candidate clause.\n\n"
        "### INV-ADAPTER —",
        1,
    )
    orphan_path = tmp_path / "AGENTS.candidate.md"
    orphan_path.write_text(orphaned, encoding="utf-8")

    with pytest.raises(AssertionError, match="candidate invariant set"):
        _assert_candidate_mapping_is_closed(
            load_invariant_map(INVARIANT_MAP),
            collect_candidate_invariants(orphan_path),
        )


def test_invariant_map_parser_rejects_invalid_markers_and_fences() -> None:
    document = _valid_map_document()
    valid = _map_markdown(document)
    invalid_documents = (
        valid.replace("<!-- codex-context-map:v1 begin -->", "", 1),
        valid.replace(
            "<!-- codex-context-map:v1 begin -->",
            "<!-- codex-context-map:v1 begin -->\n"
            "<!-- codex-context-map:v1 begin -->",
            1,
        ),
        valid.replace("```json", "```JSON", 1),
        valid.replace("```json", "```json\n```json", 1),
        f"{valid}\n```json\n{{}}\n```\n",
    )
    for malformed in invalid_documents:
        with pytest.raises(
            ValueError,
            match=r"^invariant_map_(?:marker_count|json_fence)_invalid$",
        ):
            load_invariant_map_from_text(malformed)


@pytest.mark.parametrize(
    ("case", "error_code"),
    (
        ("schema", "invariant_map_schema_invalid"),
        ("root-field", "invariant_map_fields_invalid"),
        ("row-field", "invariant_map_fields_invalid"),
        ("authority-field", "invariant_map_fields_invalid"),
        ("enforcement-field", "invariant_map_fields_invalid"),
        ("boolean", "invariant_map_boolean_invalid"),
        ("absolute-path", "invariant_map_path_invalid"),
        ("parent-path", "invariant_map_path_invalid"),
        ("backslash-path", "invariant_map_path_invalid"),
        ("newline-authority-path", "invariant_map_path_invalid"),
        ("nul-authority-path", "invariant_map_path_invalid"),
        ("newline-enforcement-path", "invariant_map_path_invalid"),
        ("unicode-path", "invariant_map_path_invalid"),
        ("uppercase-digest", "invariant_map_digest_invalid"),
        ("short-digest", "invariant_map_digest_invalid"),
        ("enforcement-kind", "invariant_map_enforcement_invalid"),
    ),
)
def test_invariant_map_parser_rejects_malformed_values(
    case: str,
    error_code: str,
) -> None:
    document = _valid_map_document()
    row = document["rows"][0]
    if case == "schema":
        document["schema"] = "voice_agent.codex_context.invariant_map.v2"
    elif case == "root-field":
        document["extra"] = True
    elif case == "row-field":
        row["extra"] = True
    elif case == "authority-field":
        row["authority_refs"][0]["extra"] = True
    elif case == "enforcement-field":
        row["enforcement_refs"][0]["extra"] = True
    elif case == "boolean":
        row["auto_context"] = 1
    elif case == "absolute-path":
        row["authority_refs"][0]["path"] = "/tmp/ADR.md"
    elif case == "parent-path":
        row["authority_refs"][0]["path"] = "../ADR.md"
    elif case == "backslash-path":
        row["authority_refs"][0]["path"] = r"docs\adr\ADR.md"
    elif case == "newline-authority-path":
        row["authority_refs"][0]["path"] = "docs/adr/\nADR.md"
    elif case == "nul-authority-path":
        row["authority_refs"][0]["path"] = "docs/adr/\0ADR.md"
    elif case == "newline-enforcement-path":
        row["enforcement_refs"][0]["path"] = "tests/\nunsafe.py"
    elif case == "unicode-path":
        row["authority_refs"][0]["path"] = "docs/adr/ＡDR.md"
    elif case == "uppercase-digest":
        row["normalized_digest"] = "A" * 64
    elif case == "short-digest":
        row["candidate_clause_digest"] = "a" * 63
    elif case == "enforcement-kind":
        row["enforcement_refs"][0]["kind"] = "document"
    else:
        raise AssertionError(f"unknown case: {case}")

    with pytest.raises(ValueError, match=f"^{error_code}$"):
        load_invariant_map_from_text(_map_markdown(document))


@pytest.mark.parametrize(
    ("needle", "duplicate"),
    (
        (
            '"schema": "voice_agent.codex_context.invariant_map.v1", "rows":',
            '"schema": "voice_agent.codex_context.invariant_map.v1", '
            '"schema": "voice_agent.codex_context.invariant_map.v1", "rows":',
        ),
        (
            '"legacy_ref": "LEGACY-CORE-01", "legacy_summary":',
            '"legacy_ref": "LEGACY-CORE-01", '
            '"legacy_ref": "LEGACY-CORE-01", "legacy_summary":',
        ),
        (
            '"path": "docs/adr/ADR-015 Repository Governance '
            'and AGENTS.md Rules.md", "heading":',
            '"path": "docs/adr/ADR-015 Repository Governance '
            'and AGENTS.md Rules.md", '
            '"path": "docs/adr/ADR-015 Repository Governance '
            'and AGENTS.md Rules.md", "heading":',
        ),
        (
            '"kind": "pytest", "path":',
            '"kind": "pytest", "kind": "pytest", "path":',
        ),
    ),
)
def test_invariant_map_parser_rejects_duplicate_keys_at_every_level(
    needle: str,
    duplicate: str,
) -> None:
    valid = _map_markdown(_valid_map_document())
    assert valid.count(needle) == 1
    malformed = valid.replace(needle, duplicate, 1)

    with pytest.raises(
        ValueError,
        match="^invariant_map_duplicate_json_key$",
    ):
        load_invariant_map_from_text(malformed)


def test_candidate_parser_rejects_duplicate_outside_and_unmarked_clauses() -> None:
    original = CANDIDATE.read_text(encoding="utf-8")
    assert original.count("### INV-ADAPTER —") == 1
    assert original.count("- INV-ADR-03:") == 1
    assert original.count("- INV-ADR-03: This repository") == 1
    malformed_candidates = (
        original.replace(
            "### INV-ADAPTER —",
            "- INV-ADR-01: Duplicate clause.\n\n### INV-ADAPTER —",
            1,
        ),
        original.replace(
            "- INV-ADR-03:",
            "- INV-TOOL-99:",
            1,
        ),
        original.replace(
            "### INV-ADAPTER —",
            "- An unaddressable policy bullet.\n\n### INV-ADAPTER —",
            1,
        ),
        original.replace(
            "- INV-ADR-03: This repository",
            "An unaddressable policy paragraph.\n"
            "- INV-ADR-03: This repository",
            1,
        ),
    )
    expected_codes = (
        "candidate_instruction_duplicate_invariant_id",
        "candidate_instruction_invariant_outside_family",
        "candidate_instruction_clause_invalid",
        "candidate_instruction_clause_invalid",
    )
    for malformed, error_code in zip(
        malformed_candidates,
        expected_codes,
        strict=True,
    ):
        with pytest.raises(ValueError, match=f"^{error_code}$"):
            collect_candidate_invariants_from_text(malformed)


def test_candidate_parser_ignores_fenced_heading_and_clause_examples() -> None:
    original = CANDIDATE.read_text(encoding="utf-8")
    fenced = original.replace(
        "## Verification and detailed checks",
        "```markdown\n"
        "### INV-FAKE — not a real family\n"
        "- INV-ADR-99: not a real clause\n"
        "```\n\n"
        "## Verification and detailed checks",
        1,
    )
    assert collect_candidate_invariants_from_text(fenced) == (
        collect_candidate_invariants_from_text(original)
    )


def test_candidate_parser_requires_h1_at_byte_zero() -> None:
    original = CANDIDATE.read_text(encoding="utf-8")
    for prefix in ("\n", "Unmapped governance text.\n", "<!-- preface -->\n"):
        with pytest.raises(
            ValueError,
            match="^candidate_instruction_heading_structure_invalid$",
        ):
            collect_candidate_invariants_from_text(prefix + original)


def test_references_require_exact_heading_and_registered_accepted_adr(
    tmp_path: Path,
) -> None:
    valid = _write_reference_fixture(tmp_path / "valid")
    assert audit_references(valid).passed

    missing_heading = _write_reference_fixture(
        tmp_path / "missing-heading",
        adr_heading="Decisions",
    )
    assert "AUTHORITY_HEADING_MISSING" in _issue_codes(
        audit_references(missing_heading)
    )

    proposed = _write_reference_fixture(
        tmp_path / "proposed",
        adr_status="proposed",
    )
    assert "AUTHORITY_ADR_NOT_ACCEPTED" in _issue_codes(
        audit_references(proposed)
    )

    unregistered = _write_reference_fixture(
        tmp_path / "unregistered",
        register_path="docs/adr/ADR-002 Other.md",
    )
    assert "AUTHORITY_ADR_NOT_REGISTERED" in _issue_codes(
        audit_references(unregistered)
    )

    duplicate_register = _write_reference_fixture(
        tmp_path / "duplicate-register"
    )
    register = duplicate_register.adr_register
    row = (
        "| ADR-001 | Synthetic | accepted | MVP-0 | "
        "`docs/adr/ADR-001 Synthetic.md` |\n"
    )
    register.write_text(
        register.read_text(encoding="utf-8") + row,
        encoding="utf-8",
    )
    assert "ADR_REGISTER_NOT_ACCEPTED" in _issue_codes(
        audit_references(duplicate_register)
    )

    fenced_only = _write_reference_fixture(tmp_path / "fenced-register")
    register = fenced_only.adr_register
    register.write_text(
        register.read_text(encoding="utf-8").replace(
            row,
            row.replace(" accepted ", " proposed ")
            + "\n```markdown\n"
            + row
            + "```\n",
            1,
        ),
        encoding="utf-8",
    )
    assert "AUTHORITY_ADR_NOT_REGISTERED" in _issue_codes(
        audit_references(fenced_only)
    )

    duplicate_section = _write_reference_fixture(
        tmp_path / "duplicate-section"
    )
    duplicate_section.adr_register.write_text(
        duplicate_section.adr_register.read_text(encoding="utf-8")
        + "\n## ADR Register\n",
        encoding="utf-8",
    )
    assert "ADR_REGISTER_NOT_ACCEPTED" in _issue_codes(
        audit_references(duplicate_section)
    )

    mismatched_id = _write_reference_fixture(tmp_path / "mismatched-id")
    register = mismatched_id.adr_register
    register.write_text(
        register.read_text(encoding="utf-8").replace(
            "| ADR-001 | Synthetic |",
            "| ADR-002 | Synthetic |",
            1,
        ),
        encoding="utf-8",
    )
    assert "ADR_REGISTER_NOT_ACCEPTED" in _issue_codes(
        audit_references(mismatched_id)
    )

    non_adr_surface = _write_reference_fixture(
        tmp_path / "non-adr-authority",
        authority_path="docs/policies/ADR-001 Synthetic.md",
        register_path="docs/policies/ADR-001 Synthetic.md",
    )
    assert "AUTHORITY_ADR_PATH_INVALID" in _issue_codes(
        audit_references(non_adr_surface)
    )

    commented_adr = _write_reference_fixture(tmp_path / "commented-adr")
    adr = commented_adr.repo_root / "docs/adr/ADR-001 Synthetic.md"
    adr.write_text(
        "# ADR-001 Synthetic\n\n"
        "<!--\n"
        "## Status\n\naccepted\n\n"
        "## Decision\n\nHidden decision.\n"
        "-->\n",
        encoding="utf-8",
    )
    commented_codes = _issue_codes(audit_references(commented_adr))
    assert "AUTHORITY_ADR_NOT_ACCEPTED" in commented_codes
    assert "AUTHORITY_HEADING_MISSING" in commented_codes


def test_live_mapping_and_reference_auditors_pass_in_shadow() -> None:
    paths = default_audit_paths(ROOT)
    assert audit_mapping(paths).passed
    assert audit_references(paths).passed


def test_reference_rejects_parent_traversal_and_absolute_paths(
    tmp_path: Path,
) -> None:
    for index, unsafe_path in enumerate(("../ADR.md", "/tmp/ADR.md"), start=1):
        paths = _write_reference_fixture(
            tmp_path / f"unsafe-{index}",
            authority_path=unsafe_path,
        )
        report = audit_references(paths)
        assert not report.passed
        assert _issue_codes(report) == {"REFERENCE_MAP_INVALID"}

    fifo_map = _write_reference_fixture(tmp_path / "fifo-map")
    fifo_map.invariant_map.unlink()
    os.mkfifo(fifo_map.invariant_map)
    assert _issue_codes(audit_references(fifo_map)) == {
        "REFERENCE_MAP_INVALID"
    }

    symlink_candidate = _write_reference_fixture(
        tmp_path / "symlink-candidate"
    )
    outside = tmp_path / "outside-candidate.md"
    outside.write_text(CANDIDATE.read_text(encoding="utf-8"), encoding="utf-8")
    symlink_candidate.candidate_instruction.unlink()
    symlink_candidate.candidate_instruction.symlink_to(outside)
    assert _issue_codes(audit_references(symlink_candidate)) == {
        "CANDIDATE_DOCUMENT_INVALID"
    }

    symlink_adr_parent = _write_reference_fixture(
        tmp_path / "symlink-adr-parent"
    )
    adr_parent = symlink_adr_parent.repo_root / "docs/adr"
    real_adr_parent = symlink_adr_parent.repo_root / "docs/real-adr"
    adr_parent.rename(real_adr_parent)
    adr_parent.symlink_to(real_adr_parent.name, target_is_directory=True)
    assert "AUTHORITY_PATH_MISSING" in _issue_codes(
        audit_references(symlink_adr_parent)
    )

    symlink_pytest_parent = _write_reference_fixture(
        tmp_path / "symlink-pytest-parent"
    )
    pytest_parent = symlink_pytest_parent.repo_root / "tests"
    real_pytest_parent = symlink_pytest_parent.repo_root / "real-tests"
    pytest_parent.rename(real_pytest_parent)
    pytest_parent.symlink_to(real_pytest_parent.name, target_is_directory=True)
    assert "ENFORCEMENT_PATH_MISSING" in _issue_codes(
        audit_references(symlink_pytest_parent)
    )


def test_enforcement_reference_requires_existing_symbol(tmp_path: Path) -> None:
    top_level = _write_reference_fixture(tmp_path / "top-level")
    assert audit_references(top_level).passed

    class_method = _write_reference_fixture(
        tmp_path / "class-method",
        enforcement_symbol="test_class_rule",
    )
    assert audit_references(class_method).passed

    missing_pytest = _write_reference_fixture(
        tmp_path / "missing-pytest",
        enforcement_symbol="helper",
    )
    assert "ENFORCEMENT_PYTEST_SYMBOL_INVALID" in _issue_codes(
        audit_references(missing_pytest)
    )

    script_token = _write_reference_fixture(
        tmp_path / "script-token",
        enforcement_kind="script",
        enforcement_path="scripts/check-policy",
        enforcement_symbol="verify",
    )
    assert audit_references(script_token).passed

    missing_script_token = _write_reference_fixture(
        tmp_path / "missing-script-token",
        enforcement_kind="script",
        enforcement_path="scripts/check-policy",
        enforcement_symbol="apply",
    )
    assert "ENFORCEMENT_SCRIPT_SYMBOL_INVALID" in _issue_codes(
        audit_references(missing_script_token)
    )

    echo_only = _write_reference_fixture(
        tmp_path / "echo-only",
        enforcement_kind="script",
        enforcement_path="scripts/check-policy",
        enforcement_symbol="verify",
    )
    script = echo_only.repo_root / "scripts/check-policy"
    script.write_text(
        "#!/bin/sh\n"
        "# python3 tools/check_policy_cli.py \"$@\"\n"
        "echo 'python3 tools/check_policy_cli.py verify'\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    assert "ENFORCEMENT_SCRIPT_SYMBOL_INVALID" in _issue_codes(
        audit_references(echo_only)
    )

    heredoc_only = _write_reference_fixture(
        tmp_path / "heredoc-only",
        enforcement_kind="script",
        enforcement_path="scripts/check-policy",
        enforcement_symbol="verify",
    )
    script = heredoc_only.repo_root / "scripts/check-policy"
    script.write_text(
        "#!/bin/sh\n"
        "cat <<'EOF'\n"
        "python3 tools/check_policy_cli.py verify\n"
        "verify)\n"
        "EOF\n"
        "exit 0\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    assert "ENFORCEMENT_SCRIPT_SYMBOL_INVALID" in _issue_codes(
        audit_references(heredoc_only)
    )

    complete_case = _write_reference_fixture(
        tmp_path / "complete-case",
        enforcement_kind="script",
        enforcement_path="scripts/check-policy",
        enforcement_symbol="verify",
    )
    script = complete_case.repo_root / "scripts/check-policy"
    script.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        "verify)\n"
        "  exit 0\n"
        "  ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    assert audit_references(complete_case).passed

    bare_case_arm = _write_reference_fixture(
        tmp_path / "bare-case-arm",
        enforcement_kind="script",
        enforcement_path="scripts/check-policy",
        enforcement_symbol="verify",
    )
    script = bare_case_arm.repo_root / "scripts/check-policy"
    script.write_text(
        "#!/bin/sh\n"
        "verify)\n"
        "  exit 0\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    assert "ENFORCEMENT_SCRIPT_SYMBOL_INVALID" in _issue_codes(
        audit_references(bare_case_arm)
    )

    non_executable = _write_reference_fixture(
        tmp_path / "non-executable",
        enforcement_kind="script",
        enforcement_path="scripts/check-policy",
        enforcement_symbol="__entrypoint__",
        script_executable=False,
    )
    assert "ENFORCEMENT_SCRIPT_NOT_EXECUTABLE" in _issue_codes(
        audit_references(non_executable)
    )


def test_enforcement_rejects_register_and_generic_document_references(
    tmp_path: Path,
) -> None:
    register = _write_reference_fixture(
        tmp_path / "register",
        enforcement_kind="review-check",
        enforcement_path="stage_b_adr_register.md",
        enforcement_symbol="ADR Register",
    )
    assert "ENFORCEMENT_SURFACE_INVALID" in _issue_codes(
        audit_references(register)
    )

    generic = _write_reference_fixture(
        tmp_path / "generic",
        enforcement_kind="review-check",
        enforcement_path="docs/generic.md",
        enforcement_symbol="Review",
    )
    assert "ENFORCEMENT_SURFACE_INVALID" in _issue_codes(
        audit_references(generic)
    )

    loop_guard = _write_reference_fixture(
        tmp_path / "loop-guard",
        enforcement_kind="review-check",
        enforcement_path="AGENTS.md",
        enforcement_symbol="Review",
    )
    register = loop_guard.adr_register
    register.write_text(
        register.read_text(encoding="utf-8")
        + "| ADR-002 | Loop | accepted | MVP-0 | "
        "`docs/adr/ADR-002 Loop.md` |\n",
        encoding="utf-8",
    )
    loop = loop_guard.repo_root / "docs/adr/ADR-002 Loop.md"
    loop.symlink_to(loop.name)
    assert audit_references(loop_guard).passed

    proposed_review = _write_reference_fixture(
        tmp_path / "proposed-review",
        adr_status="proposed",
        enforcement_kind="review-check",
        enforcement_path="docs/adr/ADR-001 Synthetic.md",
        enforcement_symbol="Decision",
    )
    assert "ENFORCEMENT_REVIEW_ADR_NOT_ACCEPTED" in _issue_codes(
        audit_references(proposed_review)
    )

    path_only = _write_reference_fixture(
        tmp_path / "path-only",
        enforcement_kind="review-check",
        enforcement_path="docs/generic.md",
        enforcement_symbol="",
    )
    assert _issue_codes(audit_references(path_only)) == {
        "REFERENCE_MAP_INVALID"
    }


def test_candidate_reference_rejects_missing_heading_clause_or_digest_drift(
    tmp_path: Path,
) -> None:
    missing_heading = _write_reference_fixture(
        tmp_path / "candidate-heading",
        candidate_ref="INV-ADR — missing heading",
    )
    assert "CANDIDATE_HEADING_MISMATCH" in _issue_codes(
        audit_references(missing_heading)
    )

    missing_clause = _write_reference_fixture(
        tmp_path / "candidate-clause",
        candidate_invariant_id="INV-ADR-99",
    )
    assert "CANDIDATE_CLAUSE_MISSING" in _issue_codes(
        audit_references(missing_clause)
    )

    digest_drift = _write_reference_fixture(
        tmp_path / "candidate-digest",
        candidate_digest="0" * 64,
    )
    assert "CANDIDATE_DIGEST_MISMATCH" in _issue_codes(
        audit_references(digest_drift)
    )


def _accepted_adr_paths() -> set[str]:
    register = ADR_REGISTER.read_text(encoding="utf-8")
    return {
        match.group(1)
        for match in re.finditer(
            r"^\| ADR-\d{3} \| .* \| accepted \| .* \| `([^`]+)` \|$",
            register,
            flags=re.MULTILINE,
        )
    }


def _assert_candidate_mapping_is_closed(
    mappings: tuple[object, ...],
    candidates: tuple[object, ...],
) -> None:
    mapped_ids = {mapping.invariant_id for mapping in mappings}
    candidate_ids = {candidate.invariant_id for candidate in candidates}
    assert mapped_ids == candidate_ids, "candidate invariant set must equal mapped set"


def _enforcement_keys(mapping: InvariantMapping) -> set[tuple[str, str, str]]:
    return {
        (ref.kind, ref.path.as_posix(), ref.symbol)
        for ref in mapping.enforcement_refs
    }


def _valid_map_document() -> dict[str, object]:
    return {
        "schema": "voice_agent.codex_context.invariant_map.v1",
        "rows": [
            {
                "legacy_ref": "LEGACY-CORE-01",
                "legacy_summary": "Accepted ADRs govern architecture.",
                "source_heading": "基本原则 / Core Rules",
                "normalized_digest": "a" * 64,
                "invariant_id": "INV-ADR-01",
                "candidate_ref": "INV-ADR — ADR and scope governance",
                "candidate_clause_digest": "b" * 64,
                "authority_refs": [
                    {
                        "path": (
                            "docs/adr/ADR-015 Repository Governance "
                            "and AGENTS.md Rules.md"
                        ),
                        "heading": "Decision",
                    }
                ],
                "enforcement_refs": [
                    {
                        "kind": "pytest",
                        "path": "tests/events/test_event_journal.py",
                        "symbol": (
                            "test_journal_allocates_strictly_increasing_"
                            "event_seq_per_session"
                        ),
                    }
                ],
                "auto_context": True,
                "equivalence_note": "The candidate preserves the governed rule.",
                "switch_prerequisite": None,
            }
        ],
    }


def _map_markdown(document: dict[str, object]) -> str:
    return (
        "<!-- codex-context-map:v1 begin -->\n"
        "```json\n"
        f"{json.dumps(document, ensure_ascii=False)}\n"
        "```\n"
        "<!-- codex-context-map:v1 end -->\n"
    )


def _write_reference_fixture(
    root: Path,
    *,
    authority_path: str = "docs/adr/ADR-001 Synthetic.md",
    adr_heading: str = "Decision",
    adr_status: str = "accepted",
    register_path: str = "docs/adr/ADR-001 Synthetic.md",
    enforcement_kind: str = "pytest",
    enforcement_path: str = "tests/test_policy.py",
    enforcement_symbol: str = "test_top_level_rule",
    script_executable: bool = True,
    candidate_ref: str = "INV-ADR — ADR and scope governance",
    candidate_invariant_id: str = "INV-ADR-01",
    candidate_digest: str | None = None,
):
    paths = default_audit_paths(root)
    candidate_text = CANDIDATE.read_text(encoding="utf-8")
    _write_fixture_text(paths.candidate_instruction, candidate_text)
    first_candidate = collect_candidate_invariants(paths.candidate_instruction)[0]

    document = _valid_map_document()
    row = document["rows"][0]
    row["invariant_id"] = candidate_invariant_id
    row["candidate_ref"] = candidate_ref
    row["candidate_clause_digest"] = (
        candidate_digest or first_candidate.normalized_clause_digest
    )
    row["authority_refs"] = [
        {"path": authority_path, "heading": "Decision"}
    ]
    row["enforcement_refs"] = [
        {
            "kind": enforcement_kind,
            "path": enforcement_path,
            "symbol": enforcement_symbol,
        }
    ]
    _write_fixture_text(paths.invariant_map, _map_markdown(document))
    _write_fixture_text(paths.legacy_instruction, "# AGENTS.md\n\n## Review\n")
    _write_fixture_text(
        paths.adr_register,
        "# Register\n\n"
        "## Status\n\naccepted\n\n"
        "## ADR Register\n\n"
        "| ADR | Title | Status | Scope | File |\n"
        "| --- | --- | --- | --- | --- |\n"
        f"| ADR-001 | Synthetic | accepted | MVP-0 | `{register_path}` |\n",
    )
    if not Path(authority_path).is_absolute() and ".." not in Path(
        authority_path
    ).parts:
        _write_fixture_text(
            root / authority_path,
            "# ADR-001 Synthetic\n\n"
            "## Status\n\n"
            f"{adr_status}\n\n"
            f"## {adr_heading}\n\nSynthetic decision.\n",
        )
    _write_fixture_text(
        root / "tests/test_policy.py",
        "def test_top_level_rule():\n"
        "    pass\n\n"
        "def helper():\n"
        "    pass\n\n"
        "class TestPolicy:\n"
        "    def test_class_rule(self):\n"
        "        pass\n",
    )
    script = _write_fixture_text(
        root / "scripts/check-policy",
        "#!/bin/sh\nexec python3 tools/check_policy_cli.py \"$@\"\n",
    )
    script.chmod(0o755 if script_executable else 0o644)
    _write_fixture_text(
        root / "tools/check_policy_cli.py",
        "import argparse\n"
        "parser = argparse.ArgumentParser()\n"
        "subcommands = parser.add_subparsers()\n"
        "subcommands.add_parser(\"verify\")\n",
    )
    _write_fixture_text(
        root / "docs/generic.md",
        "# Generic\n\n## Review\n\nNot a permitted governance surface.\n",
    )
    return paths


def _write_fixture_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _issue_codes(report: object) -> set[str]:
    return {issue.code for issue in report.issues}
