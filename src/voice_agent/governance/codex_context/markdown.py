from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from .model import LegacyRule, LegacySourceKind


_REQUIRED_HEADINGS = (
    "基本原则 / Core Rules",
    "MVP Scope Reminder",
    "Local Debug Artifacts",
    "Mandatory Repository Artifact Rules",
    "Code Review P0/P1 Checklist",
    "ADR Index",
)
_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$")
_ORDERED_RE = re.compile(r"^([ \t]*)(\d+)\.[ \t]+(.+)$")
_BULLET_RE = re.compile(r"^([ \t]*)-[ \t]+(.+)$")
_ANY_LIST_RE = re.compile(r"^[ \t]*(?:[-+*]|\d+[.)])[ \t]+")
_FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")

_MISSING_SECTIONS = "legacy_instruction_missing_required_sections"
_INVALID_HEADINGS = "legacy_instruction_invalid_heading_structure"
_MALFORMED_NESTING = "legacy_instruction_malformed_list_nesting"
_UNEXPECTED_CONTENT = "legacy_instruction_unexpected_governed_content"
_DUPLICATE_DIGEST = "legacy_instruction_duplicate_digest"
_UNEXPECTED_COUNT = "legacy_instruction_unexpected_rule_count"
_READ_FAILED = "legacy_instruction_read_failed"


@dataclass
class _Item:
    first: str
    continuation: list[str]

    def append(self, value: str) -> None:
        self.continuation.append(value.strip())

    @property
    def source(self) -> str:
        return "\n".join((self.first, *self.continuation))


def normalize_requirement(value: str) -> str:
    """Collapse wrapping whitespace without changing inline Markdown."""

    return " ".join(value.split())


def requirement_digest(value: str) -> str:
    """Return the stable SHA-256 digest of normalized requirement text."""

    normalized = normalize_requirement(value)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def collect_legacy_rules(path: Path) -> tuple[LegacyRule, ...]:
    """Collect the governed legacy rules from an ``AGENTS.md`` path."""

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise ValueError(_READ_FAILED) from None
    return collect_legacy_rules_from_text(text)


def collect_legacy_rules_from_text(text: str) -> tuple[LegacyRule, ...]:
    """Collect legacy rules from Markdown with deterministic, strict policies."""

    lines = text.splitlines()
    headings, fenced_lines = _scan_headings(lines)
    sections = _validate_and_split_sections(lines, headings)

    collected: list[LegacyRule] = []
    preamble_items = _parse_preamble(sections["AGENTS.md"], fenced_lines)
    _extend_rules(
        collected,
        preamble_items,
        heading="AGENTS.md",
        source_kind="preamble-rule",
        ref_prefix="LEGACY-PREAMBLE",
    )

    core_parents = _parse_core(
        sections["基本原则 / Core Rules"],
        fenced_lines,
    )
    for parent_index, (parent, children) in enumerate(core_parents, start=1):
        parent_ref = f"LEGACY-CORE-{parent_index:02d}"
        collected.append(
            _rule(
                parent_ref,
                "基本原则 / Core Rules",
                "ordered-rule",
                parent.source,
            )
        )
        for child_index, child in enumerate(children, start=1):
            collected.append(
                _rule(
                    f"{parent_ref}-{child_index:02d}",
                    "基本原则 / Core Rules",
                    "nested-rule",
                    child.source,
                )
            )

    _extend_rules(
        collected,
        _parse_list_only(
            sections["MVP Scope Reminder"],
            fenced_lines,
            expected_count=4,
        ),
        heading="MVP Scope Reminder",
        source_kind="section-rule",
        ref_prefix="LEGACY-SCOPE",
    )
    _, debug_items, _ = _parse_list_with_blocks(
        sections["Local Debug Artifacts"],
        fenced_lines,
        before_blocks=1,
        expected_items=6,
        after_blocks=0,
    )
    _extend_rules(
        collected,
        debug_items,
        heading="Local Debug Artifacts",
        source_kind="section-rule",
        ref_prefix="LEGACY-DEBUG",
    )

    artifact_rules, ignore_rules, fixture = _parse_artifact_section(
        sections["Mandatory Repository Artifact Rules"],
        fenced_lines,
    )
    _extend_rules(
        collected,
        artifact_rules,
        heading="Mandatory Repository Artifact Rules",
        source_kind="section-rule",
        ref_prefix="LEGACY-ARTIFACT",
    )
    _extend_rules(
        collected,
        ignore_rules,
        heading="Mandatory Repository Artifact Rules",
        source_kind="section-rule",
        ref_prefix="LEGACY-ARTIFACT-IGNORE",
    )
    collected.append(
        _rule(
            "LEGACY-ARTIFACT-FIXTURE-01",
            "Mandatory Repository Artifact Rules",
            "standalone-rule",
            fixture.source,
        )
    )

    _, review_items, _ = _parse_list_with_blocks(
        sections["Code Review P0/P1 Checklist"],
        fenced_lines,
        before_blocks=1,
        expected_items=22,
        after_blocks=0,
    )
    _extend_rules(
        collected,
        review_items,
        heading="Code Review P0/P1 Checklist",
        source_kind="section-rule",
        ref_prefix="LEGACY-REVIEW",
    )

    adr_index = _parse_standalone(
        sections["ADR Index"],
        fenced_lines,
    )
    collected.append(
        _rule(
            "LEGACY-ADR-INDEX-01",
            "ADR Index",
            "standalone-rule",
            adr_index.source,
        )
    )

    digests = [rule.normalized_digest for rule in collected]
    if len(digests) != len(set(digests)):
        raise ValueError(_DUPLICATE_DIGEST)
    if len(collected) != 111:
        raise ValueError(_UNEXPECTED_COUNT)
    return tuple(collected)


def _scan_headings(
    lines: list[str],
) -> tuple[list[tuple[int, int, str]], frozenset[int]]:
    headings: list[tuple[int, int, str]] = []
    fenced_lines: set[int] = set()
    fence_marker: str | None = None
    for index, line in enumerate(lines):
        fence_match = _FENCE_RE.match(line)
        if fence_marker is not None:
            fenced_lines.add(index)
            stripped = line.strip()
            if (
                stripped
                and set(stripped) == {fence_marker[0]}
                and len(stripped) >= len(fence_marker)
            ):
                fence_marker = None
            continue
        if fence_match:
            fence_marker = fence_match.group(1)
            fenced_lines.add(index)
            continue
        heading_match = _HEADING_RE.match(line)
        if heading_match:
            headings.append(
                (index, len(heading_match.group(1)), heading_match.group(2))
            )
    if fence_marker is not None:
        raise ValueError(_UNEXPECTED_CONTENT)
    return headings, frozenset(fenced_lines)


def _validate_and_split_sections(
    lines: list[str],
    headings: list[tuple[int, int, str]],
) -> dict[str, tuple[int, int, list[str]]]:
    required_titles = set(_REQUIRED_HEADINGS)
    found_required = [entry for entry in headings if entry[2] in required_titles]
    found_titles = [entry[2] for entry in found_required]
    if any(found_titles.count(title) != 1 for title in _REQUIRED_HEADINGS):
        raise ValueError(_MISSING_SECTIONS)
    if tuple(found_titles) != _REQUIRED_HEADINGS:
        raise ValueError(_INVALID_HEADINGS)
    if any(level != 2 for _, level, _ in found_required):
        raise ValueError(_INVALID_HEADINGS)

    h1_entries = [entry for entry in headings if entry[1] == 1]
    if h1_entries != [(0, 1, "AGENTS.md")]:
        raise ValueError(_INVALID_HEADINGS)
    allowed = {(0, 1, "AGENTS.md"), *found_required}
    if any(entry not in allowed for entry in headings):
        raise ValueError(_INVALID_HEADINGS)

    ordered_headings = [(0, 1, "AGENTS.md"), *found_required]
    sections: dict[str, tuple[int, int, list[str]]] = {}
    for position, (line_index, _, title) in enumerate(ordered_headings):
        end = (
            ordered_headings[position + 1][0]
            if position + 1 < len(ordered_headings)
            else len(lines)
        )
        sections[title] = (line_index + 1, end, lines[line_index + 1 : end])
    return sections


def _parse_preamble(
    section: tuple[int, int, list[str]],
    fenced_lines: frozenset[int],
) -> list[_Item]:
    blocks = _paragraph_blocks(section, fenced_lines)
    if len(blocks) != 3:
        raise ValueError(_UNEXPECTED_COUNT)
    for block in blocks:
        if any(_ANY_LIST_RE.match(line) or _HEADING_RE.match(line) for line in block):
            raise ValueError(_UNEXPECTED_CONTENT)
    return [_Item(block[0].strip(), [line.strip() for line in block[1:]]) for block in blocks]


def _parse_core(
    section: tuple[int, int, list[str]],
    fenced_lines: frozenset[int],
) -> list[tuple[_Item, list[_Item]]]:
    start, _, lines = section
    result: list[tuple[_Item, list[_Item]]] = []
    active_parent: _Item | None = None
    active_children: list[_Item] | None = None
    active_item: _Item | None = None
    after_blank = True

    for offset, line in enumerate(lines):
        absolute_index = start + offset
        if absolute_index in fenced_lines:
            raise ValueError(_UNEXPECTED_CONTENT)
        if not line.strip():
            after_blank = True
            continue

        ordered = _ORDERED_RE.match(line)
        bullet = _BULLET_RE.match(line)
        if ordered:
            if ordered.group(1):
                raise ValueError(_MALFORMED_NESTING)
            ordinal = int(ordered.group(2))
            if ordinal != len(result) + 1:
                raise ValueError(_MALFORMED_NESTING)
            active_parent = _Item(ordered.group(3), [])
            active_children = []
            result.append((active_parent, active_children))
            active_item = active_parent
            after_blank = False
            continue
        if bullet:
            indent = len(bullet.group(1).expandtabs(8))
            if indent not in (3, 4) or active_parent is None or active_children is None:
                raise ValueError(_MALFORMED_NESTING)
            active_item = _Item(bullet.group(2), [])
            active_children.append(active_item)
            after_blank = False
            continue
        if _ANY_LIST_RE.match(line):
            raise ValueError(_MALFORMED_NESTING)
        if active_item is None or after_blank:
            raise ValueError(_UNEXPECTED_CONTENT)
        active_item.append(line)
        after_blank = False

    if len(result) != 13 or sum(len(children) for _, children in result) != 49:
        raise ValueError(_UNEXPECTED_COUNT)
    return result


def _parse_list_only(
    section: tuple[int, int, list[str]],
    fenced_lines: frozenset[int],
    *,
    expected_count: int,
) -> list[_Item]:
    before, items, after = _parse_list_with_blocks(
        section,
        fenced_lines,
        before_blocks=0,
        expected_items=expected_count,
        after_blocks=0,
    )
    if before or after:
        raise ValueError(_UNEXPECTED_CONTENT)
    return items


def _parse_list_with_blocks(
    section: tuple[int, int, list[str]],
    fenced_lines: frozenset[int],
    *,
    before_blocks: int,
    expected_items: int,
    after_blocks: int,
) -> tuple[list[_Item], list[_Item], list[_Item]]:
    start, _, lines = section
    before: list[_Item] = []
    items: list[_Item] = []
    after: list[_Item] = []
    phase = "before"
    active: _Item | None = None
    after_blank = True

    for offset, line in enumerate(lines):
        absolute_index = start + offset
        if absolute_index in fenced_lines:
            raise ValueError(_UNEXPECTED_CONTENT)
        if not line.strip():
            active = None
            after_blank = True
            continue
        bullet = _BULLET_RE.match(line)
        if bullet:
            if bullet.group(1):
                raise ValueError(_MALFORMED_NESTING)
            if phase == "after":
                raise ValueError(_UNEXPECTED_CONTENT)
            phase = "items"
            active = _Item(bullet.group(2), [])
            items.append(active)
            after_blank = False
            continue
        if _ANY_LIST_RE.match(line):
            raise ValueError(_MALFORMED_NESTING)
        if active is not None and not after_blank:
            active.append(line)
            after_blank = False
            continue
        paragraph = _Item(line.strip(), [])
        if phase == "before":
            before.append(paragraph)
        elif phase == "items":
            phase = "after"
            after.append(paragraph)
        else:
            after.append(paragraph)
        active = paragraph
        after_blank = False

    if (
        len(before) != before_blocks
        or len(items) != expected_items
        or len(after) != after_blocks
    ):
        raise ValueError(_UNEXPECTED_COUNT)
    return before, items, after


def _parse_artifact_section(
    section: tuple[int, int, list[str]],
    fenced_lines: frozenset[int],
) -> tuple[list[_Item], list[_Item], _Item]:
    start, _, lines = section
    groups: list[tuple[str, _Item]] = []
    active: _Item | None = None
    active_kind: str | None = None
    after_blank = True

    for offset, line in enumerate(lines):
        absolute_index = start + offset
        if absolute_index in fenced_lines:
            raise ValueError(_UNEXPECTED_CONTENT)
        if not line.strip():
            active = None
            active_kind = None
            after_blank = True
            continue
        bullet = _BULLET_RE.match(line)
        if bullet:
            if bullet.group(1):
                raise ValueError(_MALFORMED_NESTING)
            active = _Item(bullet.group(2), [])
            active_kind = "bullet"
            groups.append((active_kind, active))
            after_blank = False
            continue
        if _ANY_LIST_RE.match(line):
            raise ValueError(_MALFORMED_NESTING)
        if active is not None and not after_blank:
            active.append(line)
            continue
        active = _Item(line.strip(), [])
        active_kind = "paragraph"
        groups.append((active_kind, active))
        after_blank = False

    expected_kinds = ["bullet"] * 6 + ["paragraph"] + ["bullet"] * 6 + [
        "paragraph"
    ]
    if [kind for kind, _ in groups] != expected_kinds:
        raise ValueError(_UNEXPECTED_COUNT)
    artifact_rules = [item for _, item in groups[:6]]
    ignore_rules = [item for _, item in groups[7:13]]
    return artifact_rules, ignore_rules, groups[-1][1]


def _parse_standalone(
    section: tuple[int, int, list[str]],
    fenced_lines: frozenset[int],
) -> _Item:
    blocks = _paragraph_blocks(section, fenced_lines)
    if len(blocks) != 1:
        raise ValueError(_UNEXPECTED_COUNT)
    block = blocks[0]
    if any(_ANY_LIST_RE.match(line) or _HEADING_RE.match(line) for line in block):
        raise ValueError(_UNEXPECTED_CONTENT)
    return _Item(block[0].strip(), [line.strip() for line in block[1:]])


def _paragraph_blocks(
    section: tuple[int, int, list[str]],
    fenced_lines: frozenset[int],
) -> list[list[str]]:
    start, _, lines = section
    blocks: list[list[str]] = []
    active: list[str] | None = None
    for offset, line in enumerate(lines):
        if start + offset in fenced_lines:
            raise ValueError(_UNEXPECTED_CONTENT)
        if not line.strip():
            active = None
            continue
        if active is None:
            active = []
            blocks.append(active)
        active.append(line)
    return blocks


def _extend_rules(
    destination: list[LegacyRule],
    items: list[_Item],
    *,
    heading: str,
    source_kind: LegacySourceKind,
    ref_prefix: str,
) -> None:
    for index, item in enumerate(items, start=1):
        destination.append(
            _rule(
                f"{ref_prefix}-{index:02d}",
                heading,
                source_kind,
                item.source,
            )
        )


def _rule(
    legacy_ref: str,
    heading: str,
    source_kind: LegacySourceKind,
    source: str,
) -> LegacyRule:
    return LegacyRule(
        legacy_ref=legacy_ref,
        source_heading=heading,
        source_kind=source_kind,
        normalized_digest=requirement_digest(source),
    )


__all__ = (
    "collect_legacy_rules",
    "collect_legacy_rules_from_text",
    "normalize_requirement",
    "requirement_digest",
)
