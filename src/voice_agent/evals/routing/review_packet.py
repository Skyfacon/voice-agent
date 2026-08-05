from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict
import json
import re
from typing import Any

from voice_agent.evals.routing.case import (
    RoutingCase,
    RoutingCaseValidationError,
    validate_routing_case,
)
from voice_agent.runtime.local_debug_text_safety import contains_likely_credential


REVIEW_PACKET_SCHEMA_NAME = "voice_agent.routing_eval.human_review_packet.v1"

_FORBIDDEN_PACKET_KEY = re.compile(
    r"(?:prediction|model[_-]?output|route[_-]?result|provider|prompt|"
    r"raw[_-]?(?:audio|trace|transcript)|audio[_-]?ref|"
    r"authorization|cookie|credential|password|secret|token|api[_-]?key)",
    re.IGNORECASE,
)
_FORBIDDEN_PACKET_VALUE = re.compile(
    r"(?:^|[\s\"'])(?:/Users/|/home/|/private/|/tmp/|[A-Za-z]:\\)|"
    r"(?:file://|https?://|provider://|\.\./|\.\.\\)|"
    r"(?:diagnostics/|traces/|replays/local/|audio/raw/)|"
    r"\.(?:wav|mp3|m4a|flac|ogg|opus|weba)(?:$|[?#\s])",
    re.IGNORECASE,
)


class ReviewPacketSafetyError(ValueError):
    """Raised when a Human Review Packet cannot be projected safely."""


def build_human_review_packet(
    cases: Iterable[RoutingCase | Mapping[str, Any]],
) -> dict[str, Any]:
    """Build an evaluator-only, text-only packet for Human Review Gate 1.

    The packet deliberately has no argument for model predictions. Only the
    v1 scenario's synthetic text, context, gold, safe rationale tags and review
    metadata are projected. Selected audio cases fail closed instead of
    exposing an audio reference or local path.
    """

    normalized: list[RoutingCase] = []
    seen_case_ids: set[str] = set()
    for index, value in enumerate(cases):
        try:
            raw = _case_revalidation_mapping(value) if isinstance(value, RoutingCase) else value
            case = validate_routing_case(raw)
        except (RoutingCaseValidationError, TypeError, ValueError) as exc:
            raise ReviewPacketSafetyError(
                f"case at index {index} is not safe v1 review input: {exc}"
            ) from exc
        if case.case_id in seen_case_ids:
            raise ReviewPacketSafetyError(f"duplicate case_id {case.case_id!r}")
        seen_case_ids.add(case.case_id)
        normalized.append(case)

    selected: list[tuple[RoutingCase, list[str]]] = []
    for case in normalized:
        reasons = _review_reasons(case)
        if reasons:
            selected.append((case, reasons))

    items: list[dict[str, Any]] = []
    for case, reasons in sorted(selected, key=lambda item: item[0].case_id):
        if case.input.modality != "text" or case.input.utterance_text is None:
            raise ReviewPacketSafetyError(
                f"selected case {case.case_id!r} is not synthetic text; audio refs are forbidden"
            )
        item = {
            "case_id": case.case_id,
            "scenario_family_id": case.scenario_family_id,
            "split": case.split,
            "criticality": case.criticality,
            "annotation_status": case.annotation_status,
            "review_reasons": reasons,
            "synthetic_input": {
                "modality": "text",
                "locale": case.input.locale,
                "utterance_text": case.input.utterance_text,
            },
            "context": asdict(case.context),
            "gold": asdict(case.gold),
            "rationale_tags": list(case.tags),
        }
        _assert_safe_packet_value(item)
        items.append(deepcopy(item))

    reason_counts = Counter(reason for _, reasons in selected for reason in reasons)
    packet = {
        "schema_name": REVIEW_PACKET_SCHEMA_NAME,
        "purpose": "human_routing_policy_adjudication",
        "source_case_count": len(normalized),
        "review_case_count": len(items),
        "selection_rule": ["high", "ambiguous", "contrast_set"],
        "review_reason_counts": {
            key: reason_counts[key] for key in sorted(reason_counts)
        },
        "cases": items,
        "safety": {
            "synthetic_text_only": True,
            "system_predictions_included": False,
            "raw_audio_included": False,
            "audio_refs_included": False,
            "provider_payload_included": False,
            "prompt_dump_included": False,
            "secret_included": False,
            "local_paths_included": False,
        },
    }
    _assert_safe_packet_value(packet, allow_safety_declarations=True)
    return packet


def render_human_review_packet_markdown(packet: Mapping[str, Any]) -> str:
    """Render a safe packet as deterministic Markdown without adding data."""

    copied = deepcopy(dict(packet))
    if copied.get("schema_name") != REVIEW_PACKET_SCHEMA_NAME:
        raise ReviewPacketSafetyError("unexpected review packet schema_name")
    _assert_safe_packet_value(copied, allow_safety_declarations=True)
    cases = copied.get("cases")
    if not isinstance(cases, Sequence) or isinstance(cases, (str, bytes, bytearray)):
        raise ReviewPacketSafetyError("review packet cases must be a JSON array")

    lines = [
        "# Audio Routing Human Review Packet",
        "",
        f"Cases requiring review: {copied.get('review_case_count', 0)}",
        "",
        "Selection: high criticality, ambiguous focus, or contrast-set membership.",
    ]
    for item in cases:
        if not isinstance(item, Mapping):
            raise ReviewPacketSafetyError("review packet case must be a JSON object")
        lines.extend(
            [
                "",
                f"## {_inline(str(item.get('case_id', 'unknown')))}",
                "",
                f"- Family: `{_inline(str(item.get('scenario_family_id', 'unknown')))}`",
                f"- Split: `{_inline(str(item.get('split', 'unknown')))}`",
                f"- Criticality: `{_inline(str(item.get('criticality', 'unknown')))}`",
                f"- Status: `{_inline(str(item.get('annotation_status', 'unknown')))}`",
                "- Review reasons: "
                + ", ".join(
                    f"`{_inline(str(reason))}`" for reason in item.get("review_reasons", [])
                ),
                "",
                "### Synthetic input",
                "",
            ]
        )
        synthetic_input = item.get("synthetic_input", {})
        utterance = (
            synthetic_input.get("utterance_text", "")
            if isinstance(synthetic_input, Mapping)
            else ""
        )
        lines.append(f"> {_quote(str(utterance))}")
        lines.extend(["", "### Context", ""])
        lines.extend(_indented_json(item.get("context", {})))
        lines.extend(["", "### Gold", ""])
        lines.extend(_indented_json(item.get("gold", {})))
        lines.extend(["", "### Rationale tags", ""])
        lines.append(
            ", ".join(
                f"`{_inline(str(tag))}`" for tag in item.get("rationale_tags", [])
            )
            or "(none)"
        )
    return "\n".join(lines) + "\n"


def _review_reasons(case: RoutingCase) -> list[str]:
    reasons: list[str] = []
    if case.criticality == "high":
        reasons.append("high")
    if "AMBIGUOUS" in case.gold.task_focus_allowed:
        reasons.append("ambiguous")
    # ``minimal_pair`` remains a legacy compatibility tag.  It denotes contrast-
    # set membership here and must not be presented as a strict one-variable pair.
    if "contrast_set" in case.tags or "minimal_pair" in case.tags:
        reasons.append("contrast_set")
    return reasons


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


def _assert_safe_packet_value(
    value: object,
    *,
    path: tuple[str, ...] = (),
    allow_safety_declarations: bool = False,
) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ReviewPacketSafetyError("review packet keys must be strings")
            if _FORBIDDEN_PACKET_KEY.search(key):
                allowed_declaration = (
                    allow_safety_declarations
                    and path == ("safety",)
                    and child is False
                )
                if not allowed_declaration:
                    raise ReviewPacketSafetyError(
                        f"forbidden review packet field at {'.'.join((*path, key))}"
                    )
            _assert_safe_packet_value(
                child,
                path=(*path, key),
                allow_safety_declarations=allow_safety_declarations,
            )
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            _assert_safe_packet_value(
                child,
                path=(*path, str(index)),
                allow_safety_declarations=allow_safety_declarations,
            )
        return
    if isinstance(value, str):
        if contains_likely_credential(value) or _FORBIDDEN_PACKET_VALUE.search(value):
            raise ReviewPacketSafetyError(
                f"unsafe value detected at {'.'.join(path) or 'packet'}"
            )


def _inline(value: str) -> str:
    return value.replace("`", "'").replace("\n", " ").replace("\r", " ")


def _quote(value: str) -> str:
    return _inline(value).replace(">", "\\>")


def _indented_json(value: object) -> list[str]:
    serialized = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    return [f"    {line}" for line in serialized.splitlines()]
