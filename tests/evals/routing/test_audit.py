from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from voice_agent.evals.routing.audit import (
    CorpusAuditPolicy,
    audit_routing_corpus,
    milestone1_prompt_dev_policy,
)
from voice_agent.evals.routing.loader import load_routing_cases_jsonl


REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = REPO_ROOT / "evals" / "routing" / "manifests" / "prompt-dev.jsonl"


def _case(
    case_id: str,
    *,
    family: str = "family_001",
    split: str = "prompt_dev",
    template: str = "NO_ACTIVE_TASK",
    criticality: str = "low",
    annotation_status: str = "draft",
    tags: list[str] | None = None,
    focus: str = "FOREGROUND_CHAT",
    decision: str = "FAST_ONLY",
) -> dict[str, object]:
    decisions = {"FAST_ONLY", "SPAWN_SLOW_TASK", "PATCH_ACTIVE_SLOW_TASK", "IGNORE"}
    context: dict[str, object] = {"template": template}
    if template.startswith("ACTIVE_TASK_") or template == "TERMINAL_TASK":
        lifecycle = {
            "ACTIVE_TASK_WAITING_SLOT": "WAITING_FOR_SLOT",
            "ACTIVE_TASK_WAITING_CONFIRMATION": "WAITING_FOR_USER_CONFIRMATION",
            "ACTIVE_TASK_WAITING_TOOL": "EXECUTING",
            "ACTIVE_TASK_FINALIZING": "EXECUTING",
            "TERMINAL_TASK": "COMPLETED",
        }.get(template, "PLANNING")
        active_task: dict[str, object] = {
            "task_id": f"task_{case_id}",
            "task_type": "test_task",
            "summary": "合成任务上下文",
            "lifecycle_phase": lifecycle,
            "plan_version": 1,
        }
        if template == "ACTIVE_TASK_WAITING_CONFIRMATION":
            active_task["pending_confirmation_scope"] = "SWITCH_TASK"
        context["active_task"] = active_task
    slow_task_created = decision == "SPAWN_SLOW_TASK"
    user_patch_emitted = decision == "PATCH_ACTIVE_SLOW_TASK"
    return {
        "schema_name": "voice_agent.routing_eval.case.v1",
        "case_id": case_id,
        "scenario_family_id": family,
        "split": split,
        "input": {
            "modality": "text",
            "locale": "zh-CN",
            "utterance_text": "这是安全的合成测试文本。",
        },
        "context": context,
        "gold": {
            "task_focus_allowed": [focus],
            "router_decisions_allowed": [decision],
            "router_decisions_forbidden": sorted(decisions - {decision}),
            "foreground_policy": {
                "FAST_ONLY": "ANSWER",
                "SPAWN_SLOW_TASK": "ACK_SLOW",
                "PATCH_ACTIVE_SLOW_TASK": "ACK_PATCH",
                "IGNORE": "SILENCE",
            }[decision],
            "side_effect_expectations": {
                "slow_task_created": slow_task_created,
                "user_patch_emitted": user_patch_emitted,
                "external_side_effects": "FORBIDDEN",
            },
        },
        "tags": tags or [],
        "criticality": criticality,
        "annotation_status": annotation_status,
    }


def _relaxed_policy() -> CorpusAuditPolicy:
    return CorpusAuditPolicy(required_context_templates=())


def test_milestone1_prompt_dev_manifest_passes_complete_audit() -> None:
    cases = load_routing_cases_jsonl(MANIFEST, expected_split="prompt_dev")

    report = audit_routing_corpus(cases, policy=milestone1_prompt_dev_policy())

    assert report["status"] == "passed"
    assert report["case_count"] == 80
    assert report["family_count"] == 20
    assert report["bucket_counts"] == {
        "fast": 20,
        "ignore_ambiguous": 12,
        "patch_control": 28,
        "spawn": 20,
    }
    assert all(check["passed"] for check in report["checks"].values())
    json.dumps(report, ensure_ascii=False)


def test_audit_detects_duplicate_ids_and_family_split_leakage() -> None:
    first = _case("case_001", family="shared_family", tags=["minimal_pair"])
    duplicate = deepcopy(first)
    duplicate["split"] = "validation"
    duplicate["annotation_status"] = "human_reviewed"

    report = audit_routing_corpus([first, duplicate], policy=_relaxed_policy())

    assert report["status"] == "failed"
    codes = {issue["code"] for issue in report["issues"]}
    assert "duplicate_case_id" in codes
    assert "family_split_leakage" in codes


def test_audit_enforces_quota_status_and_context_coverage() -> None:
    case = _case(
        "case_001",
        split="locked_test",
        annotation_status="draft",
    )
    policy = CorpusAuditPolicy(
        expected_case_count=2,
        expected_split_counts=(("locked_test", 2),),
        expected_bucket_counts=(("fast", 2),),
        expected_status_counts=(("human_reviewed", 2),),
        required_context_templates=("NO_ACTIVE_TASK", "TERMINAL_TASK"),
    )

    report = audit_routing_corpus([case], policy=policy)

    assert report["checks"]["quota"]["passed"] is False
    assert report["checks"]["annotation_status"]["passed"] is False
    assert report["checks"]["context_coverage"]["missing_templates"] == [
        "TERMINAL_TASK"
    ]


def test_audit_requires_multiple_route_signatures_in_contrast_set_family() -> None:
    case = _case("case_001", family="weak_pair", tags=["minimal_pair"])

    report = audit_routing_corpus([case], policy=_relaxed_policy())

    assert report["checks"]["contrast_set_coverage"]["passed"] is False
    assert report["checks"]["contrast_set_coverage"]["incomplete_families"] == [
        "weak_pair"
    ]


def test_milestone1_audit_requires_exactly_twenty_contrast_set_families() -> None:
    report = audit_routing_corpus(
        [_case("case_001", family="only_family", tags=["minimal_pair"])],
        policy=CorpusAuditPolicy(
            required_context_templates=(),
            expected_contrast_set_family_count=20,
        ),
    )

    assert report["checks"]["contrast_set_coverage"]["passed"] is False
    assert report["checks"]["contrast_set_coverage"]["family_count"] == 1
    assert {issue["code"] for issue in report["issues"]} >= {
        "incomplete_contrast_set",
        "contrast_set_family_count_mismatch",
    }


def test_audit_revalidates_confirmation_scope_and_safe_fields() -> None:
    invalid_scope = _case(
        "case_scope",
        template="ACTIVE_TASK_WAITING_CONFIRMATION",
        focus="ACTIVE_TASK_PATCH",
        decision="PATCH_ACTIVE_SLOW_TASK",
    )
    invalid_scope["context"]["active_task"]["pending_confirmation_scope"] = "PLAN_APPROVAL"  # type: ignore[index]
    unsafe_path = _case("case_path")
    unsafe_path["input"]["utterance_text"] = "读取 /Users/example/private.txt"  # type: ignore[index]

    report = audit_routing_corpus(
        [invalid_scope, unsafe_path],
        policy=_relaxed_policy(),
    )

    codes = {issue["code"] for issue in report["issues"]}
    assert "invalid_case" in codes
    assert "noncanonical_confirmation_scope" in codes
    assert "unsafe_shareable_field" in codes
    assert report["checks"]["canonical_confirmation_scope"]["passed"] is False
    assert report["safe_to_share"] is False
