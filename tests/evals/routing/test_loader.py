from __future__ import annotations

import json
from pathlib import Path

import pytest

from voice_agent.evals.routing.case import ROUTING_CASE_SCHEMA_NAME
from voice_agent.evals.routing.loader import RoutingCaseLoadError, load_routing_cases_jsonl


def _case(case_id: str = "routing_fast_001", split: str = "prompt_dev") -> dict[str, object]:
    return {
        "schema_name": ROUTING_CASE_SCHEMA_NAME,
        "case_id": case_id,
        "scenario_family_id": "simple_explanation_001",
        "split": split,
        "input": {
            "modality": "text",
            "locale": "zh-CN",
            "utterance_text": "简单解释一下什么是回声。",
        },
        "context": {"template": "NO_ACTIVE_TASK"},
        "gold": {
            "task_focus_allowed": ["FOREGROUND_CHAT"],
            "router_decisions_allowed": ["FAST_ONLY"],
            "router_decisions_forbidden": [
                "SPAWN_SLOW_TASK",
                "PATCH_ACTIVE_SLOW_TASK",
                "IGNORE",
            ],
            "foreground_policy": "ANSWER",
            "side_effect_expectations": {
                "slow_task_created": False,
                "user_patch_emitted": False,
                "external_side_effects": "FORBIDDEN",
            },
        },
        "tags": ["foreground_chat"],
        "criticality": "low",
        "annotation_status": "draft",
    }


def _write_jsonl(path: Path, values: list[dict[str, object]]) -> None:
    text = "\n".join(json.dumps(value, ensure_ascii=False) for value in values) + "\n"
    path.write_text(text, encoding="utf-8")


def test_loads_jsonl_in_order_and_allows_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    path.write_text(
        json.dumps(_case("case_001"), ensure_ascii=False)
        + "\n\n"
        + json.dumps(_case("case_002"), ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )

    cases = load_routing_cases_jsonl(path, expected_split="prompt_dev")

    assert tuple(case.case_id for case in cases) == ("case_001", "case_002")


def test_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    _write_jsonl(path, [_case(), _case()])

    with pytest.raises(RoutingCaseLoadError, match="duplicate case_id"):
        load_routing_cases_jsonl(path)


def test_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    serialized = json.dumps(_case(), ensure_ascii=False)
    path.write_text(serialized[:-1] + ', "case_id": "duplicate"}\n', encoding="utf-8")

    with pytest.raises(RoutingCaseLoadError, match="duplicate JSON key"):
        load_routing_cases_jsonl(path)


def test_reports_line_number_for_invalid_case(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    invalid = _case("case_002")
    invalid["split"] = "train"
    _write_jsonl(path, [_case("case_001"), invalid])

    with pytest.raises(RoutingCaseLoadError, match="line 2"):
        load_routing_cases_jsonl(path)


def test_rejects_wrong_expected_split(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    _write_jsonl(path, [_case(split="validation")])

    with pytest.raises(RoutingCaseLoadError, match="does not match expected_split"):
        load_routing_cases_jsonl(path, expected_split="prompt_dev")


def test_rejects_empty_manifest(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    path.write_text("\n", encoding="utf-8")

    with pytest.raises(RoutingCaseLoadError, match="at least one case"):
        load_routing_cases_jsonl(path)


def test_rejects_non_jsonl_and_symlink_paths(tmp_path: Path) -> None:
    json_path = tmp_path / "cases.json"
    json_path.write_text("{}", encoding="utf-8")
    with pytest.raises(RoutingCaseLoadError, match="end in .jsonl"):
        load_routing_cases_jsonl(json_path)

    target = tmp_path / "target.jsonl"
    _write_jsonl(target, [_case()])
    link = tmp_path / "link.jsonl"
    link.symlink_to(target)
    with pytest.raises(RoutingCaseLoadError, match="symlink"):
        load_routing_cases_jsonl(link)


def test_rejects_non_object_json_line(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    path.write_text("[]\n", encoding="utf-8")

    with pytest.raises(RoutingCaseLoadError, match="must be a JSON object"):
        load_routing_cases_jsonl(path)
