from __future__ import annotations

from pathlib import Path

from voice_agent.governance.codex_context.markdown import (
    collect_legacy_rules,
    collect_legacy_rules_from_text,
    normalize_requirement,
)


ROOT = Path(__file__).resolve().parents[2]


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
