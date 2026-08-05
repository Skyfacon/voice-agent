from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from voice_agent.evals.routing.loader import load_routing_cases_jsonl
from voice_agent.evals.routing.review_packet import (
    ReviewPacketSafetyError,
    build_human_review_packet,
    render_human_review_packet_markdown,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = REPO_ROOT / "evals" / "routing" / "manifests" / "prompt-dev.jsonl"


def _base_case() -> dict[str, object]:
    return {
        "schema_name": "voice_agent.routing_eval.case.v1",
        "case_id": "review_001",
        "scenario_family_id": "review_family_001",
        "split": "prompt_dev",
        "input": {
            "modality": "text",
            "locale": "zh-CN",
            "utterance_text": "请简单解释什么是回声。",
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
        "tags": ["minimal_pair", "simple_explanation"],
        "criticality": "low",
        "annotation_status": "draft",
    }


def test_review_packet_selects_all_high_ambiguous_or_contrast_set_cases() -> None:
    minimal = _base_case()
    high = deepcopy(minimal)
    high.update(
        case_id="review_002",
        scenario_family_id="review_family_002",
        tags=["high_risk_boundary"],
        criticality="high",
    )
    ambiguous = deepcopy(minimal)
    ambiguous.update(
        case_id="review_003",
        scenario_family_id="review_family_003",
        tags=["unclear_reference"],
    )
    ambiguous["gold"]["task_focus_allowed"] = ["AMBIGUOUS"]  # type: ignore[index]
    ambiguous["gold"]["foreground_policy"] = "CLARIFY"  # type: ignore[index]
    ordinary = deepcopy(minimal)
    ordinary.update(
        case_id="review_004",
        scenario_family_id="review_family_004",
        tags=["ordinary"],
    )

    packet = build_human_review_packet([minimal, high, ambiguous, ordinary])

    assert packet["review_case_count"] == 3
    assert [case["case_id"] for case in packet["cases"]] == [
        "review_001",
        "review_002",
        "review_003",
    ]
    assert set(packet["cases"][2]["review_reasons"]) == {"ambiguous"}
    assert packet["cases"][0]["review_reasons"] == ["contrast_set"]
    assert packet["selection_rule"] == ["high", "ambiguous", "contrast_set"]
    assert packet["safety"]["system_predictions_included"] is False
    json.dumps(packet, ensure_ascii=False)


def test_prompt_dev_packet_is_safe_projection_without_runtime_outputs() -> None:
    cases = load_routing_cases_jsonl(MANIFEST, expected_split="prompt_dev")

    packet = build_human_review_packet(cases)
    serialized = json.dumps(packet, ensure_ascii=False)

    assert packet["review_case_count"] == 80
    assert all(case["synthetic_input"]["modality"] == "text" for case in packet["cases"])
    for forbidden in (
        '"prediction"',
        '"model_output"',
        '"audio_ref"',
        '"raw_audio"',
        '"provider_body"',
        '"prompt_dump"',
        "/Users/",
        "audio-eval://local/",
    ):
        assert forbidden not in serialized


def test_review_packet_rejects_selected_audio_and_prediction_fields() -> None:
    audio = _base_case()
    audio["input"] = {
        "modality": "audio",
        "locale": "zh-CN",
        "audio_ref": "audio-eval://synthetic/review-001",
    }
    with pytest.raises(ReviewPacketSafetyError, match="audio refs are forbidden"):
        build_human_review_packet([audio])

    predicted = _base_case()
    predicted["model_prediction"] = {"router_decision": "FAST_ONLY"}
    with pytest.raises(ReviewPacketSafetyError, match="not safe v1 review input"):
        build_human_review_packet([predicted])


def test_review_packet_rejects_secret_or_local_path_without_echoing_value() -> None:
    local_path = _base_case()
    local_path["input"]["utterance_text"] = "读取 /Users/example/private.txt"  # type: ignore[index]
    with pytest.raises(ReviewPacketSafetyError, match="unsafe value"):
        build_human_review_packet([local_path])

    secret = _base_case()
    secret["input"]["utterance_text"] = "api_key=abcdefghijklmnop"  # type: ignore[index]
    with pytest.raises(ReviewPacketSafetyError) as caught:
        build_human_review_packet([secret])
    assert "abcdefghijklmnop" not in str(caught.value)


def test_markdown_renderer_is_deterministic_and_contains_only_packet_projection() -> None:
    packet = build_human_review_packet([_base_case()])

    markdown = render_human_review_packet_markdown(packet)

    assert markdown == render_human_review_packet_markdown(packet)
    assert "# Audio Routing Human Review Packet" in markdown
    assert "请简单解释什么是回声。" in markdown
    assert "FAST_ONLY" in markdown
    assert "/Users/" not in markdown
    assert "audio-eval://" not in markdown
