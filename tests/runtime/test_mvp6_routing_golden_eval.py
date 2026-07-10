from __future__ import annotations

import json
import subprocess


def test_provider_free_routing_golden_eval_covers_required_cases_without_provider_calls() -> None:
    from voice_agent.runtime.mvp6_routing_golden_eval import run_mvp6_routing_golden_eval

    summary = run_mvp6_routing_golden_eval()

    assert summary["status"] == "passed"
    assert summary["profile_id"] == "lalm-thinker-routing-control"
    assert summary["profile_version"] == "mvp6.2.zh-CN.v1"
    assert str(summary["profile_hash"]).startswith("sha256:")
    assert summary["case_count"] == 7
    assert summary["passed_count"] == 7
    assert summary["failed_count"] == 0
    assert summary["provider_call_used"] is False
    assert summary["network_used"] is False
    assert summary["credential_env_var_read"] is False
    assert summary["raw_audio_included"] is False
    assert summary["raw_provider_body_included"] is False
    assert summary["prompt_dump_included"] is False
    assert summary["secret_included"] is False

    cases = {case["case_id"]: case for case in summary["cases"]}
    assert cases["zh_foreground_simple"]["actual_task_focus"] == "FOREGROUND_CHAT"
    assert cases["zh_foreground_simple"]["actual_router_decision"] == "FAST_ONLY"
    assert cases["zh_foreground_story_fast_interaction"]["actual_task_focus"] == (
        "FOREGROUND_CHAT"
    )
    assert cases["zh_foreground_story_fast_interaction"]["actual_router_decision"] == "FAST_ONLY"
    assert cases["zh_foreground_story_fast_interaction"]["fast_interaction_output_mode"] == "real"
    assert cases["zh_foreground_story_fast_interaction"]["actual_foreground_gate_decision"] == (
        "passed"
    )
    assert cases["zh_foreground_story_fast_interaction"]["actual_output_basis"] == (
        "reply_candidate"
    )
    assert "SLOWTASK_CREATED" not in cases["zh_foreground_story_fast_interaction"]["event_names"]
    assert "USER_PATCH_RECEIVED" not in cases["zh_foreground_story_fast_interaction"]["event_names"]
    assert cases["zh_complex_new_task"]["actual_task_focus"] == "NEW_TASK_CANDIDATE"
    assert cases["zh_complex_new_task"]["actual_router_decision"] == "SPAWN_SLOW_TASK"
    assert cases["zh_active_task_patch"]["actual_task_focus"] == "ACTIVE_TASK_PATCH"
    assert cases["zh_active_task_patch"]["actual_router_decision"] == "PATCH_ACTIVE_SLOW_TASK"
    assert cases["zh_ambiguous"]["actual_task_focus"] == "AMBIGUOUS"
    assert cases["zh_ambiguous"]["actual_router_decision"] == "FAST_ONLY"
    assert cases["zh_non_assistant"]["actual_task_focus"] == "NON_ASSISTANT"
    assert cases["zh_non_assistant"]["actual_router_decision"] == "IGNORE"
    assert cases["zh_active_task_new_task_candidate"]["actual_task_focus"] == (
        "NEW_TASK_CANDIDATE"
    )
    assert cases["zh_active_task_new_task_candidate"]["actual_router_decision"] == (
        "PATCH_ACTIVE_SLOW_TASK"
    )


def test_routing_golden_eval_cli_outputs_profile_metadata_and_eval_result() -> None:
    result = subprocess.run(
        ["scripts/mvp6-routing-eval"],
        check=True,
        text=True,
        capture_output=True,
    )

    payload = json.loads(result.stdout)

    assert payload["status"] == "passed"
    assert payload["profile_id"] == "lalm-thinker-routing-control"
    assert payload["profile_version"] == "mvp6.2.zh-CN.v1"
    assert payload["profile_hash"].startswith("sha256:")
    assert payload["provider_call_used"] is False
    assert payload["network_used"] is False
    assert payload["credential_env_var_read"] is False
    assert "DASHSCOPE_API_KEY" not in result.stdout
