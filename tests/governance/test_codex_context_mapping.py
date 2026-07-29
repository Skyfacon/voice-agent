from __future__ import annotations

import ast
import json
import re
from collections import Counter
from pathlib import Path

import pytest

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
