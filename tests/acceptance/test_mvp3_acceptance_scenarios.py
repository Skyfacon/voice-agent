from __future__ import annotations

from copy import deepcopy
import http.client
import json
import random
import re
import shutil
import socket
import time
import urllib.request

import pytest

from conftest import MVP3_REPLAY_FIXTURE_DIR, REPO_ROOT, load_json_fixture
from voice_agent.replay.runner import run_replay_fixture
from voice_agent.replay.scenario_assertions import (
    MVP3AcceptanceError,
    assert_mvp3_fixture_is_repo_safe,
    run_mvp3_acceptance_manifest,
)


MVP3_BACKLOG = REPO_ROOT / "docs" / "implementation" / "mvp3-backlog.md"
MVP3_CLOSEOUT = REPO_ROOT / "docs" / "implementation" / "mvp3-closeout.md"
SCENARIO_SPEC = REPO_ROOT / "docs" / "specs" / "mvp3-acceptance-scenarios.md"
MANIFEST_INDEX = MVP3_REPLAY_FIXTURE_DIR / "manifest.index.json"
EMPTY_FIXTURE = MVP3_REPLAY_FIXTURE_DIR / "000-empty-mvp3-session.fixture.json"
SLICE8_FIXTURE = MVP3_REPLAY_FIXTURE_DIR / "008-fallback-degraded-replay.fixture.json"

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
    "adapter_health_digest_distinguishes_output_modes_failure_retry_missing_capabilities_degradation",
    "fallback_degraded_replay_uses_recorded_refs_only",
    "all_mvp3_scenario_ids_are_manifest_mapped",
}


def test_mvp3_backlog_declares_slice_driven_plan_like_prior_mvps() -> None:
    content = MVP3_BACKLOG.read_text(encoding="utf-8")

    for heading in REQUIRED_SLICE_HEADINGS:
        assert f"## {heading}" in content
    assert "MVP-3 must not start with direct provider integration" in content
    assert "MVP-3 Slice 0" in content


def test_mvp3_acceptance_spec_and_manifest_register_current_slice_fixtures() -> None:
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
        },
        {
            "fixture": "008-fallback-degraded-replay.fixture.json",
            "purpose": "fallback/degraded adapter replay with recorded real/fallback/degraded outcomes",
        }
    ]
    assert manifest["scenarios"][0] == {
        "scenario_id": "MVP3-FIXTURE-SAFETY-001",
        "fixture": "000-empty-mvp3-session.fixture.json",
        "assertion": "MVP-3 Slice 0 fixtures are deterministic, GitHub-safe, synthetic/redacted/minimal, and contain no provider execution.",
    }
    assert {
        "scenario_id": "MVP3-FALLBACK-DEGRADED-REPLAY-001",
        "fixture": "008-fallback-degraded-replay.fixture.json",
        "assertion": (
            "Slice 8 replay distinguishes real/fallback/degraded adapter outcomes, "
            "canonical retry/failure/validation/degraded paths, and old-plan adapter output "
            "without provider rerun."
        ),
    } in manifest["scenarios"]


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


def test_mvp3_slice8_fixture_is_repo_safe_and_replays_without_runtime_execution() -> None:
    fixture = load_json_fixture(SLICE8_FIXTURE)

    _assert_mvp3_fixture_manifest_is_repo_safe(fixture)
    result = run_replay_fixture(fixture)

    assert result.result_status == "passed"
    assert set(result.adapter_health_state.output_event_modes.values()) == {
        "real",
        "fallback",
        "degraded",
    }
    assert result.slowtask_state.tasks["task_mvp3_slice8"].current_plan_version == 2


def test_mvp3_acceptance_manifest_executes_required_scenarios_fixture_checks_and_closeout_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _block_runtime_execution(monkeypatch)

    result = run_mvp3_acceptance_manifest(
        load_json_fixture(MANIFEST_INDEX),
        fixture_dir=MVP3_REPLAY_FIXTURE_DIR,
        required_scenario_ids=REQUIRED_SCENARIOS,
    )

    assert [scenario.scenario_id for scenario in result.scenario_results] == REQUIRED_SCENARIOS
    assert {scenario.result_status for scenario in result.scenario_results} == {"passed"}
    assert result.summary["suite_id"] == "MVP3-ACCEPTANCE"
    assert result.summary["result_status"] == "passed"
    assert result.summary["scenario_count"] == len(REQUIRED_SCENARIOS)
    assert result.summary["fixture_count"] == 2
    assert result.summary["deterministic_replay_verified"] is True
    assert result.summary["runtime_execution_detected"] is False
    assert result.summary["provider_execution_detected"] is False
    assert result.summary["adapter_health_digest_verified"] is True
    assert result.summary["fallback_degraded_contract_verified"] is True
    assert result.summary["adr_update_required"] is False
    assert result.summary["hidden_future_scope_detected"] is False
    assert result.summary["validated_fixture_names"] == [
        "000-empty-mvp3-session.fixture.json",
        "008-fallback-degraded-replay.fixture.json",
    ]

    scenarios = {scenario.scenario_id: scenario for scenario in result.scenario_results}
    assert scenarios["MVP3-RUNTIME-ASSEMBLY-001"].assertion_summary["adapter_types"] == [
        "asr",
        "thinker",
        "slow_llm",
        "tts",
    ]
    assert scenarios["MVP3-FALLBACK-DEGRADED-REPLAY-001"].assertion_summary["output_event_modes"] == {
        "evt_mvp3_slice8_asr_real_output": "real",
        "evt_mvp3_slice8_thinker_fallback_output": "fallback",
        "evt_mvp3_slice8_slow_llm_fallback_output": "fallback",
        "evt_mvp3_slice8_tts_degraded_output": "degraded",
    }


def test_mvp3_manifest_safety_gates_reject_provider_execution_claims() -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)
    weakened = deepcopy(manifest)
    weakened["required_replay_properties"] = [
        prop for prop in weakened["required_replay_properties"] if prop != "mvp3_slice0_contains_no_provider_execution"
    ]

    with pytest.raises(MVP3AcceptanceError, match="mvp3_slice0_contains_no_provider_execution"):
        run_mvp3_acceptance_manifest(
            weakened,
            fixture_dir=MVP3_REPLAY_FIXTURE_DIR,
            required_scenario_ids=REQUIRED_SCENARIOS,
        )


def test_mvp3_acceptance_rejects_missing_required_scenario_mapping() -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)
    manifest["scenarios"] = [
        scenario
        for scenario in manifest["scenarios"]
        if scenario["scenario_id"] != "MVP3-TTS-CONTRACT-001"
    ]

    with pytest.raises(MVP3AcceptanceError, match="Missing scenario entries"):
        run_mvp3_acceptance_manifest(
            manifest,
            fixture_dir=MVP3_REPLAY_FIXTURE_DIR,
            required_scenario_ids=REQUIRED_SCENARIOS,
        )


def test_mvp3_acceptance_rejects_manifest_that_weakens_replay_scope_gates() -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)
    manifest["required_replay_properties"] = [
        prop
        for prop in manifest["required_replay_properties"]
        if prop != "fallback_degraded_replay_uses_recorded_refs_only"
    ]

    with pytest.raises(MVP3AcceptanceError, match="required_replay_properties"):
        run_mvp3_acceptance_manifest(
            manifest,
            fixture_dir=MVP3_REPLAY_FIXTURE_DIR,
            required_scenario_ids=REQUIRED_SCENARIOS,
        )


def test_mvp3_acceptance_rejects_missing_adapter_output_mode_label(tmp_path) -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)
    _copy_mvp3_fixtures(tmp_path)
    fixture_path = tmp_path / SLICE8_FIXTURE.name
    fixture = load_json_fixture(fixture_path)
    asr_output = _event_by_id(fixture["events"], "evt_mvp3_slice8_asr_real_output")
    del asr_output["output_mode"]
    fixture_path.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(MVP3AcceptanceError, match="output_mode"):
        run_mvp3_acceptance_manifest(
            manifest,
            fixture_dir=tmp_path,
            required_scenario_ids=REQUIRED_SCENARIOS,
        )


def test_mvp3_acceptance_rejects_repo_unsafe_direct_provider_refs() -> None:
    fixture = deepcopy(load_json_fixture(SLICE8_FIXTURE))
    fixture["events"][0]["runtime_config_ref"] = "https://provider.example.invalid/v1/models"

    with pytest.raises(MVP3AcceptanceError, match="provider"):
        assert_mvp3_fixture_is_repo_safe(fixture)


def test_mvp3_acceptance_rejects_non_string_raw_or_provider_payload_fields() -> None:
    fixture = deepcopy(load_json_fixture(SLICE8_FIXTURE))
    audio_started = _event_by_id(fixture["events"], "evt_mvp3_slice8_audio_started")
    audio_started["audio_bytes"] = [0, 1, 2, 3]

    with pytest.raises(MVP3AcceptanceError, match="audio_bytes"):
        assert_mvp3_fixture_is_repo_safe(fixture)

    fixture = deepcopy(load_json_fixture(SLICE8_FIXTURE))
    asr_output = _event_by_id(fixture["events"], "evt_mvp3_slice8_asr_real_output")
    asr_output["provider_response"] = {"choices": [{"text": "synthetic"}]}

    with pytest.raises(MVP3AcceptanceError, match="provider_response"):
        assert_mvp3_fixture_is_repo_safe(fixture)


def test_mvp3_acceptance_rejects_percent_encoded_provider_refs() -> None:
    fixture = deepcopy(load_json_fixture(SLICE8_FIXTURE))
    asr_output = _event_by_id(fixture["events"], "evt_mvp3_slice8_asr_real_output")
    asr_output["text_ref"] = "h%74%74ps%3a%2f%2fapi%2eopenai%2ecom%2fv1%2fmodels"

    with pytest.raises(MVP3AcceptanceError, match="provider"):
        assert_mvp3_fixture_is_repo_safe(fixture)


def test_mvp3_acceptance_rejects_qualified_provider_source_modules(tmp_path) -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)
    _copy_mvp3_fixtures(tmp_path)
    fixture_path = tmp_path / SLICE8_FIXTURE.name
    fixture = load_json_fixture(fixture_path)
    asr_output = _event_by_id(fixture["events"], "evt_mvp3_slice8_asr_real_output")
    asr_output["source_module"] = "provider_client.openai"
    fixture_path.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(MVP3AcceptanceError, match="provider_client.openai"):
        run_mvp3_acceptance_manifest(
            manifest,
            fixture_dir=tmp_path,
            required_scenario_ids=REQUIRED_SCENARIOS,
        )


def test_mvp3_acceptance_rejects_provider_specific_payload_keys() -> None:
    fixture = deepcopy(load_json_fixture(SLICE8_FIXTURE))
    asr_output = _event_by_id(fixture["events"], "evt_mvp3_slice8_asr_real_output")
    asr_output["provider_specific_schema"] = {"shape": "provider-native"}

    with pytest.raises(MVP3AcceptanceError, match="provider_specific_schema"):
        assert_mvp3_fixture_is_repo_safe(fixture)

    fixture = deepcopy(load_json_fixture(SLICE8_FIXTURE))
    slow_llm_output = _event_by_id(fixture["events"], "evt_mvp3_slice8_slow_llm_fallback_output")
    slow_llm_output["provider_tool_calls"] = [{"name": "native_tool"}]

    with pytest.raises(MVP3AcceptanceError, match="provider_tool_calls"):
        assert_mvp3_fixture_is_repo_safe(fixture)


def test_mvp3_closeout_document_records_scope_risks_and_verification_commands() -> None:
    content = MVP3_CLOSEOUT.read_text(encoding="utf-8")

    for required in (
        "MVP-3 Slice 0-9 Coverage",
        "Non-Goals",
        "Remaining Risks",
        "Verification Commands",
        "./scripts/test tests/acceptance/test_mvp3_acceptance_scenarios.py -q",
        "./scripts/test tests/replay -q",
        "./scripts/test tests/adapters -q",
        "./scripts/test tests/events -q",
        "./scripts/test -q",
    ):
        assert required in content


def _scenario_ids_from_spec() -> list[str]:
    text = SCENARIO_SPEC.read_text(encoding="utf-8")
    scenario_ids = re.findall(r"^## Scenario (MVP3-[A-Z0-9-]+)$", text, flags=re.MULTILINE)
    assert scenario_ids, "MVP-3 acceptance scenario spec must declare required scenario ids"
    return scenario_ids


def _assert_mvp3_fixture_is_repo_safe(fixture: dict[str, object]) -> None:
    _assert_mvp3_fixture_manifest_is_repo_safe(fixture)
    manifest = fixture["replay_manifest"]
    assert manifest["replay_id"] == "replay_mvp3_empty_session_000"
    assert manifest["source_trace_ref"] == "fixture://mvp3/000-empty-mvp3-session"
    assert fixture["events"] == []


def _assert_mvp3_fixture_manifest_is_repo_safe(fixture: dict[str, object]) -> None:
    manifest = fixture["replay_manifest"]
    assert isinstance(manifest, dict)
    assert manifest["manifest_schema_version"] == "1.0"
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


def _copy_mvp3_fixtures(target_dir) -> None:
    for fixture_path in MVP3_REPLAY_FIXTURE_DIR.glob("*.fixture.json"):
        shutil.copy(fixture_path, target_dir / fixture_path.name)


def _event_by_id(events: list[dict[str, object]], event_id: str) -> dict[str, object]:
    return next(event for event in events if event["event_id"] == event_id)


def _block_runtime_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "time", lambda: pytest.fail("acceptance replay must not call wall clock"))
    monkeypatch.setattr(time, "monotonic", lambda: pytest.fail("acceptance replay must not call monotonic clock"))
    monkeypatch.setattr(random, "random", lambda: pytest.fail("acceptance replay must not call randomness"))
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *args, **kwargs: pytest.fail("acceptance replay must not create sockets"),
    )
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *args, **kwargs: pytest.fail("acceptance replay must not call HTTP"),
    )
    monkeypatch.setattr(
        http.client.HTTPConnection,
        "request",
        lambda *args, **kwargs: pytest.fail("acceptance replay must not call HTTP clients"),
    )
