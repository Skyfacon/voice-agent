from __future__ import annotations

from copy import deepcopy
import re

import pytest

from conftest import MVP3_REPLAY_FIXTURE_DIR, REPO_ROOT, load_json_fixture
from voice_agent.replay.runner import run_replay_fixture


MVP3_BACKLOG = REPO_ROOT / "docs" / "implementation" / "mvp3-backlog.md"
SCENARIO_SPEC = REPO_ROOT / "docs" / "specs" / "mvp3-acceptance-scenarios.md"
MANIFEST_INDEX = MVP3_REPLAY_FIXTURE_DIR / "manifest.index.json"
EMPTY_FIXTURE = MVP3_REPLAY_FIXTURE_DIR / "000-empty-mvp3-session.fixture.json"

REQUIRED_SLICE_HEADINGS = [
    "Slice 0: MVP-3 fixture / replay safety skeleton",
    "Slice 1: Adapter profile spec",
    "Slice 2: Adapter health/error/degraded event harness",
    "Slice 3: Runtime assembly and startup",
    "Slice 4: ASR adapter contract",
    "Slice 5: Thinker adapter contract",
    "Slice 6: Slow LLM structured output",
    "Slice 7: TTS adapter contract",
    "Slice 8: Fallback/degraded replay",
    "Slice 9: MVP-3 acceptance runner and closeout",
]
REQUIRED_SCENARIOS = [
    "MVP3-FIXTURE-SAFETY-001",
    "MVP3-ADAPTER-PROFILE-001",
    "MVP3-ADAPTER-EVENT-HARNESS-001",
    "MVP3-RUNTIME-ASSEMBLY-001",
    "MVP3-ASR-CONTRACT-001",
    "MVP3-THINKER-CONTRACT-001",
    "MVP3-SLOW-LLM-STRUCTURED-001",
    "MVP3-TTS-CONTRACT-001",
    "MVP3-FALLBACK-DEGRADED-REPLAY-001",
    "MVP3-ACCEPTANCE-SCOPE-SAFETY-001",
]
FORBIDDEN_MVP3_SLICE0_BEHAVIORS = {
    "provider_sdk_dependency",
    "provider_network_probe",
    "direct_external_model_call",
    "real_external_tool_side_effect",
    "raw_audio_fixture",
    "raw_trace_fixture",
    "secret_or_credential_fixture",
    "unredacted_real_user_input",
    "replay_calls_provider",
    "new_architecture_capability",
}
REQUIRED_REPLAY_PROPERTIES = {
    "deterministic_replay_does_not_rerun_models_tools_network_clock_or_random",
    "mvp3_slice0_contains_no_provider_execution",
    "mvp3_fixtures_are_synthetic_redacted_minimal",
    "mock_real_fallback_degraded_modes_must_be_explicit",
}


def test_mvp3_backlog_declares_slice_driven_plan_like_prior_mvps() -> None:
    content = MVP3_BACKLOG.read_text(encoding="utf-8")

    for heading in REQUIRED_SLICE_HEADINGS:
        assert f"## {heading}" in content
    assert "MVP-3 must not start with direct provider integration" in content
    assert "MVP-3 Slice 0" in content


def test_mvp3_acceptance_spec_and_manifest_start_with_slice0_skeleton() -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)
    scenario_ids = _scenario_ids_from_spec()

    assert scenario_ids == REQUIRED_SCENARIOS
    assert manifest["manifest_index_schema_version"] == "1.0"
    assert manifest["suite_id"] == "MVP3-ACCEPTANCE"
    assert manifest["fixture_domain"] == "GITHUB_ALLOWED"
    assert manifest["replay_mode"] == "deterministic"
    assert manifest["scope"].startswith("MVP-3 acceptance skeleton")
    assert manifest["generated_fixtures_must_be"] == ["synthetic", "redacted", "minimal"]
    assert manifest["required_scenarios"] == REQUIRED_SCENARIOS
    assert set(manifest["forbidden_behaviors"]) >= FORBIDDEN_MVP3_SLICE0_BEHAVIORS
    assert set(manifest["required_replay_properties"]) >= REQUIRED_REPLAY_PROPERTIES
    assert manifest["fixture_checks"] == [
        {
            "fixture": "000-empty-mvp3-session.fixture.json",
            "purpose": "empty MVP-3 replay safety skeleton with no provider execution",
        }
    ]
    assert manifest["scenarios"][0] == {
        "scenario_id": "MVP3-FIXTURE-SAFETY-001",
        "fixture": "000-empty-mvp3-session.fixture.json",
        "assertion": "MVP-3 Slice 0 fixtures are deterministic, GitHub-safe, synthetic/redacted/minimal, and contain no provider execution.",
    }


def test_mvp3_empty_fixture_is_repo_safe_and_replays_without_runtime_execution() -> None:
    fixture = load_json_fixture(EMPTY_FIXTURE)

    _assert_mvp3_fixture_is_repo_safe(fixture)
    result = run_replay_fixture(fixture)

    assert result.result_status == "passed"
    assert result.replay_mode == "deterministic"
    assert result.fixture_domain == "GITHUB_ALLOWED"
    assert result.ordered_events == ()
    assert result.diagnostics["ignored_events"] == []
    assert result.diagnostics["data_plane_refs"] == []
    assert result.state_digest["source_session_id"] is None
    assert result.state_digest["last_event_seq"] == 0


def test_mvp3_manifest_safety_gates_reject_provider_execution_claims() -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)
    weakened = deepcopy(manifest)
    weakened["required_replay_properties"] = [
        prop for prop in weakened["required_replay_properties"] if prop != "mvp3_slice0_contains_no_provider_execution"
    ]

    with pytest.raises(AssertionError, match="mvp3_slice0_contains_no_provider_execution"):
        assert set(weakened["required_replay_properties"]) >= REQUIRED_REPLAY_PROPERTIES


def _scenario_ids_from_spec() -> list[str]:
    text = SCENARIO_SPEC.read_text(encoding="utf-8")
    scenario_ids = re.findall(r"^## Scenario (MVP3-[A-Z0-9-]+)$", text, flags=re.MULTILINE)
    assert scenario_ids, "MVP-3 acceptance scenario spec must declare required scenario ids"
    return scenario_ids


def _assert_mvp3_fixture_is_repo_safe(fixture: dict[str, object]) -> None:
    manifest = fixture["replay_manifest"]
    assert isinstance(manifest, dict)
    assert manifest["manifest_schema_version"] == "1.0"
    assert manifest["replay_id"] == "replay_mvp3_empty_session_000"
    assert manifest["source_trace_ref"] == "fixture://mvp3/000-empty-mvp3-session"
    assert manifest["replay_mode"] == "deterministic"
    assert manifest["event_schema_version_range"] == ["1.0"]
    assert manifest["fixture_domain"] == "GITHUB_ALLOWED"
    assert manifest["generated_from"] == "hand_written_minimal"
    assert manifest["contains_raw_audio"] is False
    assert manifest["contains_raw_trace"] is False
    assert manifest["contains_real_user_input"] is False
    assert manifest["contains_secrets"] is False
    assert manifest["contains_unredacted_tool_result"] is False
    assert manifest["contains_large_raw_web_content"] is False
    assert manifest["allowed_re_eval_components"] == []
    assert fixture["events"] == []
