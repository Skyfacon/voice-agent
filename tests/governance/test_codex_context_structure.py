from __future__ import annotations

import json
import os
from pathlib import Path

from voice_agent.governance.codex_context.audit import (
    ACTIVE_BUNDLE_RECOMMENDED_BYTES,
    CANDIDATE_MAX_BYTES,
    CARD_MAX_BYTES,
    TASK_CARD_HEADINGS,
    WORK_PACKAGE_HEADINGS,
    audit_artifacts,
    audit_budgets,
    audit_cards,
    default_audit_paths,
)


ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / "docs/governance/codex-context/AGENTS.candidate.md"
BASELINE = ROOT / "docs/governance/codex-context/shadow-baseline.md"
MASTER_PLAN = (
    ROOT
    / "docs/superpowers/plans/"
    "2026-07-27-qwen-slice3b1-protocol-faithful-fake.md"
)


def test_budgets_count_utf8_bytes_and_enforce_6_12_20_kib(
    tmp_path: Path,
) -> None:
    paths = default_audit_paths(tmp_path)
    _write_bytes(paths.candidate_instruction, "é".encode("utf-8") * 3_072)
    card = paths.card_root / "TC-SYN-01.md"
    _write_bytes(card, "界".encode("utf-8") * 4_096)
    _write_bytes(paths.adr_register, b"r" * 2_048)

    assert len(paths.candidate_instruction.read_text(encoding="utf-8")) == 3_072
    assert len(paths.candidate_instruction.read_bytes()) == CANDIDATE_MAX_BYTES
    assert len(card.read_text(encoding="utf-8")) == 4_096
    assert len(card.read_bytes()) == CARD_MAX_BYTES
    assert (
        len(paths.candidate_instruction.read_bytes())
        + len(paths.adr_register.read_bytes())
        + len(card.read_bytes())
        == ACTIVE_BUNDLE_RECOMMENDED_BYTES
    )
    assert audit_budgets(paths).passed
    assert not audit_budgets(paths).issues

    _write_bytes(
        paths.candidate_instruction,
        paths.candidate_instruction.read_bytes() + b"x",
    )
    candidate_report = audit_budgets(paths)
    assert "CANDIDATE_BUDGET_EXCEEDED" in _issue_codes(candidate_report)
    assert "ACTIVE_BUNDLE_RECOMMENDATION_EXCEEDED" in _issue_codes(
        candidate_report
    )

    _write_bytes(paths.candidate_instruction, "é".encode("utf-8") * 3_072)
    _write_bytes(card, card.read_bytes() + b"x")
    card_report = audit_budgets(paths)
    assert "CARD_BUDGET_EXCEEDED" in _issue_codes(card_report)

    _write_bytes(card, "界".encode("utf-8") * 4_096)
    _write_bytes(paths.adr_register, b"r" * 2_049)
    bundle_report = audit_budgets(paths)
    assert bundle_report.passed
    bundle_issues = [
        issue
        for issue in bundle_report.issues
        if issue.code == "ACTIVE_BUNDLE_RECOMMENDATION_EXCEEDED"
    ]
    assert len(bundle_issues) == 1
    assert bundle_issues[0].severity == "warning"

    exception_card = paths.card_root / "TC-SYN-02-exception.md"
    _write_text(
        exception_card,
        "# TC-SYN-02\n\n"
        "## Budget exception\n\n"
        "- Required additional source: synthetic input\n",
    )
    assert "BUDGET_EXCEPTION_INCOMPLETE" in _issue_codes(
        audit_budgets(paths)
    )

    _write_text(
        exception_card,
        "# TC-SYN-02\n\n"
        "## Budget exception\n\n"
        "- Required additional source:   \n"
        "- Why it cannot be summarized or section-selected: reason\n"
        "- Bounded duration: one test\n"
        "- Semantic-equivalence verification: focused audit\n",
    )
    assert "BUDGET_EXCEPTION_INCOMPLETE" in _issue_codes(
        audit_budgets(paths)
    )

    _write_text(
        exception_card,
        "# TC-SYN-02\n\n"
        "## Budget exception\n\n"
        "### Required additional source\n\n"
        "- Why it cannot be summarized or section-selected: reason\n"
        "- Bounded duration: one test\n"
        "- Semantic-equivalence verification: focused audit\n",
    )
    assert "BUDGET_EXCEPTION_INCOMPLETE" in _issue_codes(
        audit_budgets(paths)
    )

    _write_text(
        exception_card,
        "# TC-SYN-02\n\n"
        "## Budget exception\n\n"
        "### Required additional source\n\nSynthetic input.\n\n"
        "- Why it cannot be summarized or section-selected: reason\n"
        "- Bounded duration: one test\n"
        "- Semantic-equivalence verification: focused audit\n",
    )
    assert "BUDGET_EXCEPTION_INCOMPLETE" in _issue_codes(
        audit_budgets(paths)
    )

    hidden_fields = (
        "- Required additional source: synthetic input\n"
        "- Why it cannot be summarized or section-selected: reason\n"
        "- Bounded duration: one test\n"
        "- Semantic-equivalence verification: focused audit\n"
    )
    _write_text(
        exception_card,
        "# TC-SYN-02\n\n"
        "## Budget exception\n\n"
        "```markdown\n"
        f"{hidden_fields}"
        "```\n",
    )
    assert "BUDGET_EXCEPTION_INCOMPLETE" in _issue_codes(
        audit_budgets(paths)
    )

    _write_text(
        exception_card,
        "# TC-SYN-02\n\n"
        "## Budget exception\n\n"
        "<!--\n"
        f"{hidden_fields}"
        "-->\n",
    )
    assert "BUDGET_EXCEPTION_INCOMPLETE" in _issue_codes(
        audit_budgets(paths)
    )

    complete_exception = (
        "# TC-SYN-02\n\n"
        "## Budget exception\n\n"
        "- Required additional source: synthetic input\n"
        "- Why it cannot be summarized or section-selected: boundary probe\n"
        "- Bounded duration: this test only\n"
        "- Semantic-equivalence verification: focused deterministic audit\n"
    )
    padding = "x" * (CARD_MAX_BYTES + 1)
    _write_text(exception_card, complete_exception + padding)
    exception_report = audit_budgets(paths)
    assert "BUDGET_EXCEPTION_INCOMPLETE" not in _issue_codes(exception_report)
    assert "CARD_BUDGET_EXCEEDED" in _issue_codes(exception_report)


def test_live_budget_and_artifact_auditors_pass_before_cards() -> None:
    paths = default_audit_paths(ROOT)
    assert audit_budgets(paths).passed
    assert audit_artifacts(paths).passed


def test_repo_root_symlink_alias_remains_a_valid_logical_root(
    tmp_path: Path,
) -> None:
    real_root = tmp_path / "real-repo"
    _write_card_fixture(real_root)
    alias_root = tmp_path / "repo-alias"
    alias_root.symlink_to(real_root.name, target_is_directory=True)
    assert audit_cards(default_audit_paths(alias_root)).passed


def test_cards_require_every_task_card_contract_section(
    tmp_path: Path,
) -> None:
    paths = _write_card_fixture(tmp_path / "valid")
    assert audit_cards(paths).passed

    missing = _write_card_fixture(tmp_path / "missing")
    card = missing.card_root / "TC-SYN-01.md"
    card.write_text(
        card.read_text(encoding="utf-8").replace(
            "## Evidence and handoff\n",
            "",
            1,
        ),
        encoding="utf-8",
    )
    assert "TASK_CARD_HEADING_STRUCTURE_INVALID" in _issue_codes(
        audit_cards(missing)
    )

    reordered = _write_card_fixture(tmp_path / "reordered")
    card = reordered.card_root / "TC-SYN-01.md"
    text = card.read_text(encoding="utf-8")
    first = "## Goal\n\nComplete one bounded task.\n\n"
    second = "## Allowed write files\n\n- `src/generated.py`\n\n"
    assert text.count(first) == text.count(second) == 1
    card.write_text(
        text.replace(first + second, second + first, 1),
        encoding="utf-8",
    )
    assert "TASK_CARD_HEADING_STRUCTURE_INVALID" in _issue_codes(
        audit_cards(reordered)
    )

    missing_spaced_adr = _write_card_fixture(tmp_path / "missing-spaced-adr")
    (
        missing_spaced_adr.repo_root / "docs/adr/ADR-001 Synthetic.md"
    ).unlink()
    assert "TASK_CARD_ADR_REFERENCE_INVALID" in _issue_codes(
        audit_cards(missing_spaced_adr)
    )


def test_card_semantics_ignore_hidden_paths_but_keep_fenced_contract_content(
    tmp_path: Path,
) -> None:
    commented_write = _write_card_fixture(tmp_path / "commented-write")
    card = commented_write.card_root / "TC-SYN-01.md"
    card.write_text(
        card.read_text(encoding="utf-8").replace(
            "- `src/generated.py`",
            "<!-- - `src/generated.py` -->",
            1,
        ),
        encoding="utf-8",
    )
    assert "TASK_CARD_WRITE_PATH_REQUIRED" in _issue_codes(
        audit_cards(commented_write)
    )

    fenced_write = _write_card_fixture(tmp_path / "fenced-write")
    card = fenced_write.card_root / "TC-SYN-01.md"
    card.write_text(
        card.read_text(encoding="utf-8").replace(
            "- `src/generated.py`",
            "```markdown\n- `src/generated.py`\n```",
            1,
        ),
        encoding="utf-8",
    )
    assert "TASK_CARD_WRITE_PATH_REQUIRED" in _issue_codes(
        audit_cards(fenced_write)
    )

    hidden_dependency = _write_card_fixture(tmp_path / "hidden-dependency")
    card = hidden_dependency.card_root / "TC-SYN-01.md"
    card.write_text(
        card.read_text(encoding="utf-8").replace(
            "- `docs/reference.md`",
            "- `docs/reference.md`\n"
            "<!-- - `docs/missing-comment.md` -->\n"
            "```markdown\n"
            "- `docs/missing-fence.md`\n"
            "```",
            1,
        ),
        encoding="utf-8",
    )
    assert audit_cards(hidden_dependency).passed

    commented_goal = _write_card_fixture(tmp_path / "commented-goal")
    card = commented_goal.card_root / "TC-SYN-01.md"
    card.write_text(
        card.read_text(encoding="utf-8").replace(
            "Complete one bounded task.",
            "<!-- Complete one bounded task. -->",
            1,
        ),
        encoding="utf-8",
    )
    assert "TASK_CARD_HEADING_STRUCTURE_INVALID" in _issue_codes(
        audit_cards(commented_goal)
    )

    fenced_goal = _write_card_fixture(tmp_path / "fenced-goal")
    card = fenced_goal.card_root / "TC-SYN-01.md"
    card.write_text(
        card.read_text(encoding="utf-8").replace(
            "Complete one bounded task.",
            "```text\nComplete one bounded task.\n```",
            1,
        ),
        encoding="utf-8",
    )
    assert "TASK_CARD_HEADING_STRUCTURE_INVALID" not in _issue_codes(
        audit_cards(fenced_goal)
    )


def test_card_paths_and_ids_fail_closed(tmp_path: Path) -> None:
    slugged = _write_card_fixture(tmp_path / "slugged")
    card = slugged.card_root / "TC-SYN-01.md"
    card.rename(slugged.card_root / "TC-SYN-01-bounded-task.md")
    assert audit_cards(slugged).passed

    impostor = _write_card_fixture(tmp_path / "impostor")
    card = impostor.card_root / "TC-SYN-01.md"
    card.write_text(
        card.read_text(encoding="utf-8").replace(
            "TC-SYN-01",
            "TC-SYN-010",
        ),
        encoding="utf-8",
    )
    assert "TASK_CARD_HEADING_STRUCTURE_INVALID" in _issue_codes(
        audit_cards(impostor)
    )

    relative_links = _write_card_fixture(tmp_path / "relative-links")
    assert audit_cards(relative_links).passed

    inline_traversal = _write_card_fixture(tmp_path / "inline-traversal")
    card = inline_traversal.card_root / "TC-SYN-01.md"
    card.write_text(
        card.read_text(encoding="utf-8").replace(
            "`docs/reference.md`",
            "`../reference.md`",
            1,
        ),
        encoding="utf-8",
    )
    assert "TASK_CARD_DEPENDENCY_MISSING" in _issue_codes(
        audit_cards(inline_traversal)
    )

    outside_link = _write_card_fixture(tmp_path / "outside-link")
    card = outside_link.card_root / "TC-SYN-01.md"
    card.write_text(
        card.read_text(encoding="utf-8").replace(
            "[Root instruction](../../../../AGENTS.md)",
            "[Outside](../../../../../outside.md)",
            1,
        ),
        encoding="utf-8",
    )
    assert "TASK_CARD_DEPENDENCY_MISSING" in _issue_codes(
        audit_cards(outside_link)
    )

    unsafe_writes = _write_card_fixture(tmp_path / "unsafe-writes")
    card = unsafe_writes.card_root / "TC-SYN-01.md"
    card.write_text(
        card.read_text(encoding="utf-8").replace(
            "- `src/generated.py`",
            "- `https://example.test/file.py`\n"
            "- `src/*.py`\n"
            "- `$HOME/file.py`\n"
            "- `~/file.py`\n"
            "- `src/file.py;echo`\n"
            "- `src/control\u0001.py`",
            1,
        ),
        encoding="utf-8",
    )
    assert "TASK_CARD_WRITE_PATH_INVALID" in _issue_codes(
        audit_cards(unsafe_writes)
    )

    directory_scope = _write_card_fixture(tmp_path / "directory-scope")
    card = directory_scope.card_root / "TC-SYN-01.md"
    card.write_text(
        card.read_text(encoding="utf-8").replace(
            "- `src/generated.py`",
            "- `src/new-scope/`",
            1,
        ),
        encoding="utf-8",
    )
    assert "TASK_CARD_WRITE_PATH_INVALID" in _issue_codes(
        audit_cards(directory_scope)
    )

    prose_writes = _write_card_fixture(tmp_path / "prose-writes")
    card = prose_writes.card_root / "TC-SYN-01.md"
    card.write_text(
        card.read_text(encoding="utf-8").replace(
            "- `src/generated.py`",
            "No declared files.",
            1,
        ),
        encoding="utf-8",
    )
    assert "TASK_CARD_WRITE_PATH_REQUIRED" in _issue_codes(
        audit_cards(prose_writes)
    )

    regular_write = _write_card_fixture(tmp_path / "regular-write")
    _write_text(regular_write.repo_root / "src/generated.py", "value = 1\n")
    assert audit_cards(regular_write).passed

    directory_write = _write_card_fixture(tmp_path / "directory-write")
    (directory_write.repo_root / "src/generated.py").mkdir(parents=True)
    assert "TASK_CARD_WRITE_PATH_INVALID" in _issue_codes(
        audit_cards(directory_write)
    )

    symlink_write = _write_card_fixture(tmp_path / "symlink-write")
    target = _write_text(
        symlink_write.repo_root / "src/target.py",
        "value = 1\n",
    )
    (symlink_write.repo_root / "src/generated.py").symlink_to(target.name)
    assert "TASK_CARD_WRITE_PATH_INVALID" in _issue_codes(
        audit_cards(symlink_write)
    )

    fifo_write = _write_card_fixture(tmp_path / "fifo-write")
    target = fifo_write.repo_root / "src/generated.py"
    target.parent.mkdir(parents=True)
    os.mkfifo(target)
    assert "TASK_CARD_WRITE_PATH_INVALID" in _issue_codes(
        audit_cards(fifo_write)
    )

    directory_dependency = _write_card_fixture(
        tmp_path / "directory-dependency"
    )
    dependency = directory_dependency.repo_root / "docs/reference.md"
    dependency.unlink()
    dependency.mkdir()
    assert "TASK_CARD_DEPENDENCY_MISSING" in _issue_codes(
        audit_cards(directory_dependency)
    )

    fifo_dependency = _write_card_fixture(tmp_path / "fifo-dependency")
    dependency = fifo_dependency.repo_root / "docs/reference.md"
    dependency.unlink()
    os.mkfifo(dependency)
    assert "TASK_CARD_DEPENDENCY_MISSING" in _issue_codes(
        audit_cards(fifo_dependency)
    )

    symlink_dependency = _write_card_fixture(
        tmp_path / "symlink-dependency"
    )
    dependency = symlink_dependency.repo_root / "docs/reference.md"
    dependency.unlink()
    dependency.symlink_to(_write_text(tmp_path / "outside-dependency.md", "x\n"))
    assert "TASK_CARD_DEPENDENCY_MISSING" in _issue_codes(
        audit_cards(symlink_dependency)
    )

    loop_dependency = _write_card_fixture(tmp_path / "loop-dependency")
    dependency = loop_dependency.repo_root / "docs/reference.md"
    dependency.unlink()
    dependency.symlink_to(dependency.name)
    assert "TASK_CARD_DEPENDENCY_MISSING" in _issue_codes(
        audit_cards(loop_dependency)
    )

    special_cards = _write_card_fixture(tmp_path / "special-cards")
    outside = _write_text(tmp_path / "outside-card.md", "outside\n")
    (special_cards.card_root / "TC-SYN-02-link.md").symlink_to(outside)
    os.mkfifo(special_cards.card_root / "TC-SYN-03-fifo.md")
    codes = _issue_codes(audit_cards(special_cards))
    assert "TASK_CARD_PATH_INVALID" in codes

    marker = "DO_NOT_ECHO_MARKER"
    invalid_name = special_cards.card_root / f"TC-SYN-04-{marker}.md"
    _write_text(invalid_name, "invalid\n")
    invalid_report = audit_cards(special_cards)
    assert marker not in repr(invalid_report.issues)


def test_card_adr_contract_requires_registered_accepted_exact_section(
    tmp_path: Path,
) -> None:
    linked = _write_card_fixture(tmp_path / "linked")
    card = linked.card_root / "TC-SYN-01.md"
    card.write_text(
        card.read_text(encoding="utf-8").replace(
            "`docs/adr/ADR-001 Synthetic.md` — `Decision`",
            "[Decision](../../../adr/ADR-001%20Synthetic.md#Decision)",
            1,
        ),
        encoding="utf-8",
    )
    assert audit_cards(linked).passed

    absent = _write_card_fixture(tmp_path / "absent")
    card = absent.card_root / "TC-SYN-01.md"
    card.write_text(
        card.read_text(encoding="utf-8").replace(
            "- `docs/adr/ADR-001 Synthetic.md` — `Decision`",
            "No ADR reference.",
            1,
        ),
        encoding="utf-8",
    )
    assert "TASK_CARD_ADR_REFERENCE_REQUIRED" in _issue_codes(
        audit_cards(absent)
    )

    wrong_heading = _write_card_fixture(tmp_path / "wrong-heading")
    card = wrong_heading.card_root / "TC-SYN-01.md"
    card.write_text(
        card.read_text(encoding="utf-8").replace(
            " — `Decision`",
            " — `Decisions`",
            1,
        ),
        encoding="utf-8",
    )
    assert "TASK_CARD_ADR_REFERENCE_INVALID" in _issue_codes(
        audit_cards(wrong_heading)
    )

    proposed = _write_card_fixture(tmp_path / "proposed")
    adr = proposed.repo_root / "docs/adr/ADR-001 Synthetic.md"
    adr.write_text(
        adr.read_text(encoding="utf-8").replace(
            "\naccepted\n",
            "\nproposed\n",
            1,
        ),
        encoding="utf-8",
    )
    assert "TASK_CARD_ADR_REFERENCE_INVALID" in _issue_codes(
        audit_cards(proposed)
    )

    unregistered = _write_card_fixture(tmp_path / "unregistered")
    register = unregistered.adr_register
    register.write_text(
        register.read_text(encoding="utf-8").replace(
            " accepted ",
            " proposed ",
            1,
        ),
        encoding="utf-8",
    )
    assert "TASK_CARD_ADR_REFERENCE_INVALID" in _issue_codes(
        audit_cards(unregistered)
    )


def test_work_packages_reference_existing_cards_without_copying_card_bodies(
    tmp_path: Path,
) -> None:
    paths = _write_card_fixture(tmp_path / "valid", include_work_package=True)
    assert audit_cards(paths).passed

    slugged = _write_card_fixture(
        tmp_path / "slugged-package",
        include_work_package=True,
    )
    package = slugged.card_root / "WP-SYN-01.md"
    package.rename(slugged.card_root / "WP-SYN-01-package.md")
    assert audit_cards(slugged).passed

    impostor = _write_card_fixture(
        tmp_path / "impostor-package",
        include_work_package=True,
    )
    package = impostor.card_root / "WP-SYN-01.md"
    package.write_text(
        package.read_text(encoding="utf-8").replace(
            "WP-SYN-01",
            "WP-SYN-010",
        ),
        encoding="utf-8",
    )
    assert "WORK_PACKAGE_HEADING_STRUCTURE_INVALID" in _issue_codes(
        audit_cards(impostor)
    )

    missing = _write_card_fixture(
        tmp_path / "missing-card",
        include_work_package=True,
        work_package_card="TC-SYN-99.md",
    )
    assert "WORK_PACKAGE_CARD_MISSING" in _issue_codes(audit_cards(missing))

    commented_reference = _write_card_fixture(
        tmp_path / "commented-reference",
        include_work_package=True,
    )
    package = commented_reference.card_root / "WP-SYN-01.md"
    package.write_text(
        package.read_text(encoding="utf-8").replace(
            "- [TC-SYN-01](TC-SYN-01.md)",
            "<!-- - [TC-SYN-01](TC-SYN-01.md) -->",
            1,
        ),
        encoding="utf-8",
    )
    assert "WORK_PACKAGE_CARD_REFERENCE_MISSING" in _issue_codes(
        audit_cards(commented_reference)
    )

    fenced_reference = _write_card_fixture(
        tmp_path / "fenced-reference",
        include_work_package=True,
    )
    package = fenced_reference.card_root / "WP-SYN-01.md"
    package.write_text(
        package.read_text(encoding="utf-8").replace(
            "- [TC-SYN-01](TC-SYN-01.md)",
            "```markdown\n- [TC-SYN-01](TC-SYN-01.md)\n```",
            1,
        ),
        encoding="utf-8",
    )
    assert "WORK_PACKAGE_CARD_REFERENCE_MISSING" in _issue_codes(
        audit_cards(fenced_reference)
    )

    copied = _write_card_fixture(
        tmp_path / "copied",
        include_work_package=True,
    )
    card = copied.card_root / "TC-SYN-01.md"
    package = copied.card_root / "WP-SYN-01.md"
    copied_lines = [
        line
        for line in card.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    package.write_text(
        package.read_text(encoding="utf-8")
        + "\n"
        + "\n".join(copied_lines)
        + "\n",
        encoding="utf-8",
    )
    assert "WORK_PACKAGE_COPIES_CARD_BODY" in _issue_codes(
        audit_cards(copied)
    )


def test_card_rejects_embedded_full_candidate_instruction(tmp_path: Path) -> None:
    paths = _write_card_fixture(tmp_path)
    card = paths.card_root / "TC-SYN-01.md"
    card.write_text(
        card.read_text(encoding="utf-8")
        + "\n"
        + CANDIDATE.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    report = audit_cards(paths)
    assert "TASK_CARD_COPIES_CANDIDATE" in _issue_codes(report)


def test_artifacts_require_ignored_paths_and_historical_master_plan(
    tmp_path: Path,
) -> None:
    valid = _write_artifact_fixture(tmp_path / "valid")
    assert audit_artifacts(valid).passed

    missing_ignore = _write_artifact_fixture(tmp_path / "missing-ignore")
    ignore = missing_ignore.repo_root / ".gitignore"
    ignore.write_text(
        ignore.read_text(encoding="utf-8").replace("traces/\n", "", 1),
        encoding="utf-8",
    )
    assert "ARTIFACT_IGNORE_RULE_MISSING" in _issue_codes(
        audit_artifacts(missing_ignore)
    )

    negated_ignore = _write_artifact_fixture(tmp_path / "negated-ignore")
    ignore = negated_ignore.repo_root / ".gitignore"
    ignore.write_text(
        ignore.read_text(encoding="utf-8")
        + "!diagnostics/\n"
        + "!.env\n"
        + "!.env*\n",
        encoding="utf-8",
    )
    assert "ARTIFACT_IGNORE_RULE_MISSING" in _issue_codes(
        audit_artifacts(negated_ignore)
    )

    broad_negation = _write_artifact_fixture(tmp_path / "broad-negation")
    ignore = broad_negation.repo_root / ".gitignore"
    ignore.write_text(
        ignore.read_text(encoding="utf-8") + "!*\n",
        encoding="utf-8",
    )
    assert "ARTIFACT_IGNORE_RULE_MISSING" in _issue_codes(
        audit_artifacts(broad_negation)
    )

    reignored = _write_artifact_fixture(tmp_path / "reignored")
    ignore = reignored.repo_root / ".gitignore"
    ignore.write_text(
        ignore.read_text(encoding="utf-8")
        + "!diagnostics/\n"
        + "diagnostics/\n"
        + "!.env\n"
        + ".env\n",
        encoding="utf-8",
    )
    assert audit_artifacts(reignored).passed

    drifted_plan = _write_artifact_fixture(tmp_path / "drifted-plan")
    drifted_plan.master_plan.write_text("changed\n", encoding="utf-8")
    assert "MASTER_PLAN_DIGEST_MISMATCH" in _issue_codes(
        audit_artifacts(drifted_plan)
    )

    unsafe = _write_artifact_fixture(tmp_path / "unsafe")
    unsafe.candidate_instruction.write_text(
        unsafe.candidate_instruction.read_text(encoding="utf-8")
        + "\n[local trace](diagnostics/session/raw.jsonl)\n"
        + "data:text/plain,synthetic-marker\n"
        + "data:;base64,U0VOU0lUSVZF\n"
        + "-----BEGIN PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    unsafe_report = audit_artifacts(unsafe)
    assert {
        "EMBEDDED_DATA_URI",
        "EMBEDDED_PEM_BOUNDARY",
        "EMBEDDED_RAW_ARTIFACT_PATH",
    } <= _issue_codes(unsafe_report)

    safe_path_mentions = _write_artifact_fixture(tmp_path / "safe-path-mentions")
    safe_path_mentions.candidate_instruction.write_text(
        safe_path_mentions.candidate_instruction.read_text(encoding="utf-8")
        + "\n`src/diagnostics/helper.py`\n"
        + "`diagnostics/`,\n"
        + "Input data: synthetic metadata.\n",
        encoding="utf-8",
    )
    assert "EMBEDDED_RAW_ARTIFACT_PATH" not in _issue_codes(
        audit_artifacts(safe_path_mentions)
    )
    assert "EMBEDDED_DATA_URI" not in _issue_codes(
        audit_artifacts(safe_path_mentions)
    )

    missing_fixture = _write_artifact_fixture(tmp_path / "missing-fixture")
    (missing_fixture.repo_root / "tests/fixtures/test_fixture.py").unlink()
    assert "FIXTURE_ENFORCEMENT_PATH_MISSING" in _issue_codes(
        audit_artifacts(missing_fixture)
    )


def _write_card_fixture(
    root: Path,
    *,
    include_work_package: bool = False,
    work_package_card: str = "TC-SYN-01.md",
):
    paths = default_audit_paths(root)
    _write_text(paths.candidate_instruction, CANDIDATE.read_text(encoding="utf-8"))
    _write_text(paths.legacy_instruction, "# AGENTS.md\n")
    _write_text(
        paths.adr_register,
        "# Register\n\n"
        "## ADR Register\n\n"
        "| ADR | Title | Status | Scope | File |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| ADR-001 | Synthetic | accepted | MVP-0 | "
        "`docs/adr/ADR-001 Synthetic.md` |\n",
    )
    _write_text(root / "docs/reference.md", "# Reference\n")
    _write_text(
        root / "docs/adr/ADR-001 Synthetic.md",
        "# ADR\n\n## Status\n\naccepted\n\n## Decision\n\nDecision.\n",
    )
    _write_text(
        paths.card_root / "TC-SYN-01.md",
        _task_card_text("TC-SYN-01"),
    )
    if include_work_package:
        _write_text(
            paths.card_root / "WP-SYN-01.md",
            _work_package_text(work_package_card),
        )
    return paths


def _task_card_text(task_id: str) -> str:
    bodies = {
        "Task ID and title": f"`{task_id}` — Synthetic bounded task.",
        "Goal": "Complete one bounded task.",
        "Allowed write files": "- `src/generated.py`",
        "Required read-only dependencies": (
            "- `docs/reference.md`\n"
            "- `AGENTS.md`\n"
            "- [Root instruction](../../../../AGENTS.md)"
        ),
        "Exact ADR sections": (
            "- `docs/adr/ADR-001 Synthetic.md` — `Decision`"
        ),
        "Input and output contracts": (
            "Input is a stable synthetic contract; output is a verified result."
        ),
        "Stable invariant IDs": "- `INV-ADR-01`",
        "Non-goals": "- No runtime or provider change.",
        "Implementation outline": "Implement the bounded local change.",
        "Verification commands": (
            "```bash\n"
            "VOICE_AGENT_PYTHON=/path/to/python ./scripts/test tests/unit -q\n"
            "```"
        ),
        "Pass criteria": "The focused local verification passes.",
        "Stop conditions": "Stop on ADR conflict or write-set expansion.",
        "Evidence and handoff": "Record safe test counts and changed paths.",
    }
    lines = [f"# {task_id} Synthetic Task Card", ""]
    for heading in TASK_CARD_HEADINGS:
        lines.extend((f"## {heading}", "", bodies[heading], ""))
    return "\n".join(lines)


def _work_package_text(card_name: str) -> str:
    bodies = {
        "Work Package ID and goal": "`WP-SYN-01` — Complete the synthetic goal.",
        "Ordered or dependency-based Task Card list": (
            f"- [TC-SYN-01]({card_name})"
        ),
        "Entry criteria": "The accepted ADR and clean index are verified.",
        "Cross-card invariants": "`INV-ADR-01` remains true.",
        "Per-card verification policy": "Verify each card before the next.",
        "Stop, retry, and rollback conditions": (
            "Stop on failure; retry only after bounded diagnosis."
        ),
        "Package-level acceptance criteria": "All card gates pass.",
        "Final evidence handoff": "Return safe counts and relative paths.",
    }
    lines = ["# WP-SYN-01 Synthetic Work Package", ""]
    for heading in WORK_PACKAGE_HEADINGS:
        lines.extend((f"## {heading}", "", bodies[heading], ""))
    return "\n".join(lines)


def _write_artifact_fixture(root: Path):
    paths = default_audit_paths(root)
    _write_text(paths.candidate_instruction, CANDIDATE.read_text(encoding="utf-8"))
    _write_text(
        paths.candidate_instruction.parent / "shadow-baseline.md",
        BASELINE.read_text(encoding="utf-8"),
    )
    _write_text(paths.master_plan, MASTER_PLAN.read_text(encoding="utf-8"))
    _write_text(
        root / ".gitignore",
        "diagnostics/\n"
        "traces/\n"
        "replays/local/\n"
        "audio/raw/\n"
        ".env\n"
        ".env.*\n",
    )
    _write_text(paths.card_root / "TC-SYN-01.md", _task_card_text("TC-SYN-01"))
    _write_text(root / "tests/fixtures/test_fixture.py", "def test_fixture():\n    pass\n")
    _write_text(paths.invariant_map, _fixture_invariant_map())
    return paths


def _fixture_invariant_map() -> str:
    document = {
        "schema": "voice_agent.codex_context.invariant_map.v1",
        "rows": [
            {
                "legacy_ref": "LEGACY-ARTIFACT-FIXTURE-01",
                "legacy_summary": "Synthetic minimal fixture.",
                "source_heading": "Mandatory Repository Artifact Rules",
                "normalized_digest": "a" * 64,
                "invariant_id": "INV-PRIVACY-03",
                "candidate_ref": "INV-PRIVACY — Privacy/artifacts",
                "candidate_clause_digest": "b" * 64,
                "authority_refs": [
                    {
                        "path": "docs/adr/ADR-001 Synthetic.md",
                        "heading": "Decision",
                    }
                ],
                "enforcement_refs": [
                    {
                        "kind": "pytest",
                        "path": "tests/fixtures/test_fixture.py",
                        "symbol": "test_fixture",
                    }
                ],
                "auto_context": True,
                "equivalence_note": "Synthetic fixture enforcement.",
                "switch_prerequisite": None,
            }
        ],
    }
    return (
        "<!-- codex-context-map:v1 begin -->\n"
        "```json\n"
        f"{json.dumps(document, ensure_ascii=False)}\n"
        "```\n"
        "<!-- codex-context-map:v1 end -->\n"
    )


def _write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_bytes(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _issue_codes(report: object) -> set[str]:
    return {issue.code for issue in report.issues}
