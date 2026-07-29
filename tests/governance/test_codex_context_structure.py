from __future__ import annotations

import json
import os
import re
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
from voice_agent.governance.codex_context.markdown import (
    collect_candidate_invariants,
)


ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / "docs/governance/codex-context/AGENTS.candidate.md"
BASELINE = ROOT / "docs/governance/codex-context/shadow-baseline.md"
MASTER_PLAN = (
    ROOT
    / "docs/superpowers/plans/"
    "2026-07-27-qwen-slice3b1-protocol-faithful-fake.md"
)
LIVE_CARD_ROOT = ROOT / "docs/governance/codex-task-cards/slice3b1"
EXPECTED_LIVE_CARD_FILES = {
    "TC-S3B1-01": "TC-S3B1-01-events-and-envelopes.md",
    "TC-S3B1-02": "TC-S3B1-02-capabilities-and-assembly.md",
    "TC-S3B1-03": "TC-S3B1-03-protocol-and-transport.md",
    "TC-S3B1-04": "TC-S3B1-04-scripted-wire.md",
    "TC-S3B1-05": "TC-S3B1-05-candidate-quarantine.md",
    "TC-S3B1-06": "TC-S3B1-06-session-lifecycle.md",
    "TC-S3B1-07": "TC-S3B1-07-route-evidence-and-orchestration.md",
    "TC-S3B1-08": "TC-S3B1-08-gate-and-release.md",
    "TC-S3B1-09": "TC-S3B1-09-replay.md",
    "TC-S3B1-10": "TC-S3B1-10-scenario-runner.md",
    "TC-S3B1-11": "TC-S3B1-11-cli-and-acceptance.md",
}
EXPECTED_DEPENDENCIES = {
    "TC-S3B1-01": (),
    "TC-S3B1-02": ("TC-S3B1-01",),
    "TC-S3B1-03": (),
    "TC-S3B1-04": ("TC-S3B1-03",),
    "TC-S3B1-05": ("TC-S3B1-03",),
    "TC-S3B1-06": (
        "TC-S3B1-01",
        "TC-S3B1-02",
        "TC-S3B1-03",
        "TC-S3B1-04",
        "TC-S3B1-05",
    ),
    "TC-S3B1-07": (
        "TC-S3B1-01",
        "TC-S3B1-02",
        "TC-S3B1-05",
        "TC-S3B1-06",
    ),
    "TC-S3B1-08": (
        "TC-S3B1-01",
        "TC-S3B1-02",
        "TC-S3B1-05",
        "TC-S3B1-06",
        "TC-S3B1-07",
    ),
    "TC-S3B1-09": (
        "TC-S3B1-01",
        "TC-S3B1-06",
        "TC-S3B1-07",
        "TC-S3B1-08",
    ),
    "TC-S3B1-10": (
        "TC-S3B1-01",
        "TC-S3B1-02",
        "TC-S3B1-03",
        "TC-S3B1-04",
        "TC-S3B1-05",
        "TC-S3B1-06",
        "TC-S3B1-07",
        "TC-S3B1-08",
        "TC-S3B1-09",
    ),
    "TC-S3B1-11": ("TC-S3B1-09", "TC-S3B1-10"),
}
ALLOWED_LIVE_STATUSES = {
    "not-started",
    "in-progress",
    "blocked",
    "verified",
    "superseded",
}
EXPECTED_INTERFACE_MARKERS = {
    "TC-S3B1-01": (
        "base_canonical_event(...)",
        "valid_adr018_event(...)",
        "valid_asr_event(...)",
        "valid_legacy_candidate_event(...)",
        "valid_parallel_fast_event(...)",
        "valid_parallel_candidate_event(...)",
        "parallel_journal()",
    ),
    "TC-S3B1-02": (
        "ADR018_BOOLEAN_CAPABILITY_FIELDS",
        "ADR018_SUPPORT_FACT_FIELDS",
        "Card 01 does not produce a capability snapshot",
    ),
    "TC-S3B1-05": (
        "open_response(...)",
        "accept_assistant_item(...)",
        "accept_output_item(...)",
        "accept_content_part(...)",
        "bind_committed_turn(...)",
        "append_transcript_delta(...)",
        "append_pcm_delta(...)",
        "mark_transcript_done(...)",
        "mark_audio_done(...)",
        "mark_content_done(...)",
        "mark_output_item_done(...)",
        "mark_response_done(...)",
        "transcript_completion()",
        "completion()",
        "discard(...)",
    ),
    "TC-S3B1-06": (
        "fence_for_generation(",
        "attach_open_transport(",
        "stop_pump(",
        "append_audio(",
        "cancel_active_response(",
        "delete_assistant_item(",
        "bind_committed_turn(",
        "connect(",
        "rebuild(",
        "close(",
        "dispose_resources(",
        "current_epoch_snapshot(",
        "advance_playback_epoch_for_provider_rebuild(",
        'Literal["WAITING_PROVIDER_FINAL", "READY", "REJECTED"]',
        "final_asr_projection: FinalASRReadyProjectionV1 | None",
    ),
    "TC-S3B1-07": (
        "classify_route(",
        "classify_candidate_safety(",
    ),
    "TC-S3B1-08": (
        "_compare_authorize_and_enqueue_contract_only(...)",
        "valid_fast_router_event()",
        "valid_route_evidence_event()",
        "valid_safe_candidate_evidence_event()",
        "valid_default_parallel_context()",
        "gate_event_ids(case_id: str)",
    ),
    "TC-S3B1-10": (
        "InteractionController.resolve_audio_ingress(...) -> "
        "AudioIngressResolutionV1",
        "Slice3B1RunnerError",
    ),
}


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


def test_live_slice3b1_cards_match_declared_dependency_dag() -> None:
    for card_id, expected_dependencies in EXPECTED_DEPENDENCIES.items():
        card = LIVE_CARD_ROOT / EXPECTED_LIVE_CARD_FILES[card_id]
        assert card.is_file(), card_id
        dependency_body = _h2_body(
            card.read_text(encoding="utf-8"),
            "Required read-only dependencies",
        )
        observed_dependencies = tuple(
            (match.group(1), match.group(2))
            for match in re.finditer(
                r"\[(TC-S3B1-\d{2})\]\(([^)]+)\)",
                dependency_body,
            )
        )
        expected_links = tuple(
            (dependency, EXPECTED_LIVE_CARD_FILES[dependency])
            for dependency in expected_dependencies
        )
        assert observed_dependencies == expected_links
        for dependency, target in observed_dependencies:
            assert target == EXPECTED_LIVE_CARD_FILES[dependency]
            assert (LIVE_CARD_ROOT / target).is_file()


def test_live_slice3b1_cards_stay_within_write_sets_and_budgets() -> None:
    paths = default_audit_paths(ROOT)
    assert audit_cards(paths).passed
    budget_report = audit_budgets(paths)
    assert budget_report.passed
    assert budget_report.issues == ()
    candidate_ids = {
        invariant.invariant_id
        for invariant in collect_candidate_invariants(CANDIDATE)
    }
    for task_number, (card_id, filename) in enumerate(
        EXPECTED_LIVE_CARD_FILES.items(),
        start=1,
    ):
        card = LIVE_CARD_ROOT / filename
        text = card.read_text(encoding="utf-8")
        assert card.stat().st_size <= CARD_MAX_BYTES
        assert _h2_body(
            text,
            "Allowed write files",
        ).strip() == _historical_files_block(task_number)
        invariant_body = _h2_body(text, "Stable invariant IDs")
        invariant_ids = set(re.findall(r"`(INV-[A-Z]+-\d{2})`", invariant_body))
        assert invariant_ids
        assert invariant_ids <= candidate_ids

        stop_body = " ".join(_h2_body(text, "Stop conditions").split())
        for required_stop in (
            "ADR conflict",
            "write-set expansion",
            "new architecture capability or event",
            "runtime/provider/network scope expansion",
            "sensitive artifact discovery",
            "focused/overlap test failure",
        ):
            assert required_stop in stop_body, (card_id, required_stop)

        contract_body = " ".join(
            _h2_body(text, "Input and output contracts").split()
        )
        for marker in EXPECTED_INTERFACE_MARKERS.get(card_id, ()):
            assert marker in contract_body, (card_id, marker)

        verification_body = " ".join(
            _h2_body(text, "Verification commands").split()
        )
        if EXPECTED_DEPENDENCIES[card_id]:
            assert "before editing and again after this card's focused command" in (
                verification_body
            )
        else:
            assert "No dependency-overlap command applies" in verification_body

        if card_id == "TC-S3B1-05":
            exact_adr_body = _h2_body(text, "Exact ADR sections")
            for heading in (
                "Decision",
                "Commit Boundary Definition",
                "ADR-018 Accepted Addendum",
            ):
                assert (
                    "`docs/adr/ADR-001 Duplex Boundary and Interaction "
                    f"Controller.md` — `{heading}`"
                ) in exact_adr_body

        historical_files = _historical_files_block(task_number)
        if "- Regression test:" in historical_files:
            non_goals = " ".join(_h2_body(text, "Non-goals").split())
            assert (
                "Only paths labeled `Create:` or `Modify:` above are writable."
                in non_goals
            )
            assert (
                "Rows labeled `Regression test:` are read-only verification "
                "surfaces and do not grant mutation authority."
                in non_goals
            )
            assert (
                "Editing a `Regression test:` path is write-set expansion "
                "and requires stopping."
                in stop_body
            )


def test_live_work_package_promotes_master_plan_task12_to_package_gate() -> None:
    package = LIVE_CARD_ROOT / "WP-S3B1-01.md"
    assert package.is_file()
    text = package.read_text(encoding="utf-8")
    assert 2 * 1024 <= package.stat().st_size <= 4 * 1024
    assert not (LIVE_CARD_ROOT / "TC-S3B1-12.md").exists()
    acceptance = _h2_body(text, "Package-level acceptance criteria")
    for required in (
        "focused suite",
        "overlap regressions",
        "./scripts/test -q",
        "deterministic repository safety audit",
        "pre/post worktree comparison",
        "independent review",
        "final acceptance-criterion mapping",
    ):
        assert required in acceptance
    normalized_acceptance = " ".join(acceptance.split())
    assert "full `./scripts/test -q` is green" in normalized_acceptance
    assert "leave the package `blocked`, never `verified`" in (
        normalized_acceptance
    )
    card_list = _h2_body(
        text,
        "Ordered or dependency-based Task Card list",
    )
    observed_links = tuple(
        (match.group(1), match.group(2))
        for match in re.finditer(
            r"\[(TC-S3B1-\d{2})\]\(([^)]+)\)",
            card_list,
        )
    )
    assert len(observed_links) == len(EXPECTED_LIVE_CARD_FILES)
    assert dict(observed_links) == EXPECTED_LIVE_CARD_FILES
    package_order = {
        card_id: index for index, (card_id, _) in enumerate(observed_links)
    }
    for card_id, dependencies in EXPECTED_DEPENDENCIES.items():
        assert all(
            package_order[dependency] < package_order[card_id]
            for dependency in dependencies
        )


def test_live_work_package_requires_verify_first_resume_audit() -> None:
    package = (LIVE_CARD_ROOT / "WP-S3B1-01.md").read_text(encoding="utf-8")
    entry = _h2_body(package, "Entry criteria")
    normalized_entry = " ".join(entry.split())
    assert "verify-first resume audit" in entry
    assert "File existence is never completion evidence." in entry
    assert "ADR-018 remains accepted and registered." in entry
    assert "active Task Card execution must not stage" in normalized_entry
    assert "Status: `not-started`" in package

    index = (LIVE_CARD_ROOT / "index.md").read_text(encoding="utf-8")
    assert index.count("| ID | Title | Dependencies | Status | Link |") == 1
    expected_targets = {
        **EXPECTED_LIVE_CARD_FILES,
        "WP-S3B1-01": "WP-S3B1-01.md",
    }
    rows = [
        match.groupdict()
        for line in index.splitlines()
        if (
            match := re.fullmatch(
                r"\| `(?P<id>(?:TC|WP)-S3B1-\d{2})` \| "
                r"[^|]+ \| [^|]+ \| `(?P<status>[^`]+)` \| "
                r"\[[^\]]+\]\((?P<target>[^)]+)\) \|",
                line,
            )
        )
    ]
    assert len(rows) == len(expected_targets)
    assert {row["id"] for row in rows} == set(expected_targets)
    for row in rows:
        assert row["status"] in ALLOWED_LIVE_STATUSES
        assert row["status"] == "not-started"
        assert row["target"] == expected_targets[row["id"]]
        assert (LIVE_CARD_ROOT / row["target"]).is_file()
    historical_target = (
        "../../../superpowers/plans/"
        "2026-07-27-qwen-slice3b1-protocol-faithful-fake.md"
    )
    assert f"]({historical_target})" in index
    assert (LIVE_CARD_ROOT / historical_target).resolve().is_file()
    assert "## " not in index
    assert "- [ ]" not in index
    for forbidden in (
        "data:",
        "-----BEGIN ",
        "diagnostics/",
        "traces/",
        "replays/local/",
        "audio/raw/",
    ):
        assert forbidden not in index


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


def _h2_body(text: str, heading: str) -> str:
    marker = f"## {heading}\n"
    assert text.count(marker) == 1
    after = text.split(marker, 1)[1]
    return after.split("\n## ", 1)[0]


def _historical_files_block(task_number: int) -> str:
    text = MASTER_PLAN.read_text(encoding="utf-8")
    task_marker = f"### Task {task_number}:"
    assert text.count(task_marker) == 1
    task = text.split(task_marker, 1)[1]
    if task_number < 12:
        task = task.split(f"\n### Task {task_number + 1}:", 1)[0]
    files_marker = "**Files:**\n\n"
    assert task.count(files_marker) == 1
    return task.split(files_marker, 1)[1].split("\n\n**Interfaces:**", 1)[0].strip()


def _write_bytes(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _issue_codes(report: object) -> set[str]:
    return {issue.code for issue in report.issues}
