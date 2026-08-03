from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from voice_agent.evals.routing.loader import load_routing_cases_jsonl


REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = REPO_ROOT / "evals" / "routing" / "manifests" / "prompt-dev.jsonl"
ROUTER_DECISIONS = {
    "FAST_ONLY",
    "SPAWN_SLOW_TASK",
    "PATCH_ACTIVE_SLOW_TASK",
    "IGNORE",
}
ACTIVE_REQUIRED_FOCUS = {
    "ACTIVE_TASK_PATCH",
    "CANCEL_OR_PAUSE_CANDIDATE",
}
TERMINAL_PHASES = {"COMPLETED", "CANCELLED", "FAILED"}
CONFIRMATION_SCOPES = {
    "DEMO_DESTRUCTIVE_ACTION",
    "TASK_CANCEL",
    "SWITCH_TASK",
    "RISK_ACKNOWLEDGEMENT",
    "FINAL_ARGUMENT_CONFIRMATION",
}
FORBIDDEN_TEXT = re.compile(
    r"(?i)(authorization\s*:|api[-_ ]?key|password|secret|bearer\s+|cookie\s*:|"
    r"provider.{0,12}(body|payload)|(?:^|\s)(?:/Users/|/home/|[A-Z]:\\\\)|"
    r"\.\./|BEGIN [A-Z ]*PRIVATE KEY)"
)


def _load_cases() -> list[dict[str, Any]]:
    lines = [line for line in MANIFEST.read_text(encoding="utf-8").splitlines() if line]
    return [json.loads(line) for line in lines]


def _bucket(case: dict[str, Any]) -> str:
    allowed = set(case["gold"]["router_decisions_allowed"])
    focus = set(case["gold"]["task_focus_allowed"])
    if allowed == {"SPAWN_SLOW_TASK"}:
        return "spawn"
    if allowed == {"PATCH_ACTIVE_SLOW_TASK"}:
        return "patch_control"
    if focus <= {"NON_ASSISTANT", "AMBIGUOUS"}:
        return "ignore_ambiguous"
    if allowed == {"FAST_ONLY"} and focus == {"FOREGROUND_CHAT"}:
        return "fast"
    raise AssertionError(f"unclassified case: {case['case_id']}")


def test_prompt_dev_manifest_conforms_to_v1_loader_contract() -> None:
    cases = load_routing_cases_jsonl(MANIFEST, expected_split="prompt_dev")

    assert len(cases) == 80


def test_prompt_dev_manifest_has_exact_draft_quota_and_family_isolation() -> None:
    cases = _load_cases()

    assert len(cases) == 80
    assert len({case["case_id"] for case in cases}) == 80
    assert Counter(_bucket(case) for case in cases) == {
        "fast": 20,
        "spawn": 20,
        "patch_control": 28,
        "ignore_ambiguous": 12,
    }
    assert {case["split"] for case in cases} == {"prompt_dev"}
    assert {case["annotation_status"] for case in cases} == {"draft"}

    family_splits: dict[str, set[str]] = defaultdict(set)
    family_sizes: Counter[str] = Counter()
    for case in cases:
        family_splits[case["scenario_family_id"]].add(case["split"])
        family_sizes[case["scenario_family_id"]] += 1
    assert len(family_splits) >= 20
    assert all(splits == {"prompt_dev"} for splits in family_splits.values())
    assert all(size >= 2 for size in family_sizes.values())


def test_prompt_dev_manifest_uses_complete_gold_sets_and_safe_text() -> None:
    for case in _load_cases():
        assert case["schema_name"] == "voice_agent.routing_eval.case.v1"
        assert case["input"]["modality"] == "text"
        assert case["input"]["locale"] == "zh-CN"
        assert case["input"]["utterance_text"].strip()
        assert "audio_ref" not in case["input"]
        assert not FORBIDDEN_TEXT.search(json.dumps(case, ensure_ascii=False))

        gold = case["gold"]
        allowed = set(gold["router_decisions_allowed"])
        forbidden = set(gold["router_decisions_forbidden"])
        assert allowed
        assert not (allowed & forbidden)
        assert allowed | forbidden == ROUTER_DECISIONS
        assert gold["side_effect_expectations"]["external_side_effects"] == "FORBIDDEN"


def test_prompt_dev_active_task_invariants_match_router_contract() -> None:
    for case in _load_cases():
        context = case["context"]
        active_task = context.get("active_task")
        allowed = set(case["gold"]["router_decisions_allowed"])
        focus = set(case["gold"]["task_focus_allowed"])
        effects = case["gold"]["side_effect_expectations"]

        if context["template"] == "ACTIVE_TASK_WAITING_CONFIRMATION":
            assert active_task["lifecycle_phase"] == "WAITING_FOR_USER_CONFIRMATION"
            assert active_task["pending_confirmation_scope"] in CONFIRMATION_SCOPES
        elif active_task is not None:
            assert "pending_confirmation_scope" not in active_task

        if focus & ACTIVE_REQUIRED_FOCUS:
            assert active_task is not None, case["case_id"]
        if "PATCH_ACTIVE_SLOW_TASK" in allowed:
            assert active_task is not None, case["case_id"]
            assert active_task["lifecycle_phase"] not in TERMINAL_PHASES
            assert effects["user_patch_emitted"] is True
            assert effects["slow_task_created"] is False
        if "SPAWN_SLOW_TASK" in allowed:
            assert active_task is None, case["case_id"]
            assert effects["slow_task_created"] is True
            assert effects["user_patch_emitted"] is False
        if focus == {"NON_ASSISTANT"}:
            assert allowed == {"IGNORE"}
            assert effects["slow_task_created"] is False
            assert effects["user_patch_emitted"] is False
        if focus == {"AMBIGUOUS"}:
            assert "PATCH_ACTIVE_SLOW_TASK" not in allowed
            assert effects["user_patch_emitted"] is False
