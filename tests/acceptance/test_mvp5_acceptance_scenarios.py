from __future__ import annotations

from copy import deepcopy
import json
import re
from pathlib import Path
from typing import Any

import pytest

from conftest import REPO_ROOT, load_json_fixture


SCENARIO_SPEC = REPO_ROOT / "docs" / "specs" / "mvp5-acceptance-scenarios.md"
MVP5_MANIFEST = REPO_ROOT / "tests" / "fixtures" / "replay" / "mvp5" / "manifest.index.json"
APPROVAL_TEMPLATE = REPO_ROOT / "docs" / "implementation" / "mvp5-live-eval-approval-template.md"

MVP4_PREREQUISITES = {
    "provider_free_voice_e2e_orchestrator": REPO_ROOT
    / "src"
    / "voice_agent"
    / "runtime"
    / "mvp4_voice_e2e_orchestrator.py",
    "provider_free_voice_e2e_tests": REPO_ROOT
    / "tests"
    / "runtime"
    / "test_mvp4_voice_e2e_provider_free.py",
    "real_evidence_path_tests": REPO_ROOT
    / "tests"
    / "runtime"
    / "test_mvp4_voice_e2e_real_evidence_paths.py",
    "router_outcome_handling_tests": REPO_ROOT
    / "tests"
    / "runtime"
    / "test_mvp4_router_outcome_handling.py",
    "voice_router_fusion_tests": REPO_ROOT
    / "tests"
    / "router"
    / "test_mvp4_voice_router_fusion.py",
    "acceptance_replay_tests": REPO_ROOT
    / "tests"
    / "replay"
    / "test_mvp4_acceptance_scenarios.py",
    "voice_evidence_replay_tests": REPO_ROOT
    / "tests"
    / "replay"
    / "test_mvp4_voice_evidence_replay.py",
    "fixture_safety_tests": REPO_ROOT / "tests" / "replay" / "test_mvp4_fixture_safety.py",
    "mvp4_manifest_index": REPO_ROOT / "tests" / "fixtures" / "replay" / "mvp4" / "manifest.index.json",
    "mvp4_fixture_readme": REPO_ROOT / "tests" / "fixtures" / "replay" / "mvp4" / "README.md",
}

REQUIRED_FORBIDDEN_BEHAVIORS = {
    "default_provider_call",
    "provider_call_without_live_provider_opt_in",
    "local_wav_read_without_explicit_opt_in",
    "realtime_mic_capture",
    "replay_reruns_provider",
    "env_secret_read_in_provider_free_tests",
    "raw_audio_fixture",
    "raw_transcript_fixture",
    "provider_body_fixture",
    "prompt_dump_fixture",
    "local_wav_path_fixture",
    "secret_or_credential_fixture",
    "new_canonical_event_without_adr",
}

REQUIRED_REPLAY_PROPERTIES = {
    "deterministic_replay_uses_recorded_refs_only",
    "mvp5_acceptance_is_provider_free_by_default",
    "mvp5_fixtures_are_metadata_only",
    "mvp5_live_provider_requires_explicit_approval",
    "mvp5_local_wav_requires_explicit_opt_in",
    "mvp5_runtime_goals_fail_closed_when_mvp4_prerequisites_missing",
}

REQUIRED_SAFETY_FLAGS = {
    "contains_raw_audio": False,
    "contains_raw_trace": False,
    "contains_real_user_input": False,
    "contains_secrets": False,
    "contains_unredacted_tool_result": False,
    "contains_large_raw_web_content": False,
    "contains_raw_transcript": False,
    "contains_provider_body": False,
    "contains_prompt_dump": False,
    "contains_local_wav_path": False,
    "provider_execution_allowed_by_default": False,
    "local_wav_read_allowed_by_default": False,
    "replay_reruns_provider": False,
}


class MVP5AcceptanceError(AssertionError):
    pass


def test_mvp5_manifest_covers_all_spec_scenarios_and_records_mvp4_blocker() -> None:
    manifest = _load_manifest()
    required_scenarios = _scenario_ids_from_spec()
    missing_prerequisites = _missing_mvp4_prerequisites()

    assert manifest["manifest_index_schema_version"] == "1.0"
    assert manifest["suite_id"] == "MVP5-ACCEPTANCE"
    assert manifest["fixture_domain"] == "GITHUB_ALLOWED"
    assert manifest["replay_mode"] == "deterministic"
    assert manifest["generated_fixtures_must_be"] == ["synthetic", "redacted", "minimal"]
    assert manifest["required_scenarios"] == required_scenarios
    assert [scenario["scenario_id"] for scenario in manifest["scenarios"]] == required_scenarios
    assert set(manifest["forbidden_behaviors"]) >= REQUIRED_FORBIDDEN_BEHAVIORS
    assert set(manifest["required_replay_properties"]) >= REQUIRED_REPLAY_PROPERTIES

    prerequisite_status = manifest["mvp4_prerequisite_status"]
    assert prerequisite_status["checked_artifacts"] == sorted(MVP4_PREREQUISITES)
    if missing_prerequisites:
        assert prerequisite_status["status"] == "blocked"
        assert prerequisite_status["runtime_goal_blocked"] is True
        assert prerequisite_status["missing"] == missing_prerequisites
        assert all(scenario["runtime_prerequisite_status"] == "blocked" for scenario in manifest["scenarios"])
    else:
        assert prerequisite_status["status"] == "present"
        assert prerequisite_status["runtime_goal_blocked"] is False
        assert prerequisite_status["missing"] == []


def test_mvp5_manifest_is_metadata_only_and_github_safe() -> None:
    manifest = _load_manifest()

    _assert_manifest_is_repo_safe(manifest)
    for field_name, expected in REQUIRED_SAFETY_FLAGS.items():
        assert manifest[field_name] is expected
    assert manifest["fixture_checks"] == []
    assert manifest["safe_ref_examples"] == [
        "fixture://mvp5/metadata-only-placeholder",
        "summary://mvp5/live-redacted-placeholder",
    ]


def test_mvp5_manifest_safety_gate_rejects_unsafe_refs() -> None:
    manifest = deepcopy(_load_manifest())
    manifest["safe_ref_examples"].append("file://redacted-local-wav")

    with pytest.raises(MVP5AcceptanceError, match="unsafe ref"):
        _assert_manifest_is_repo_safe(manifest)

    manifest = deepcopy(_load_manifest())
    manifest["safe_ref_examples"].append("data:audio/wav;base64,REDACTED")

    with pytest.raises(MVP5AcceptanceError, match="unsafe ref"):
        _assert_manifest_is_repo_safe(manifest)


def test_mvp5_acceptance_template_is_safe_and_explicit_opt_in_only() -> None:
    content = APPROVAL_TEMPLATE.read_text(encoding="utf-8")

    for required in (
        "live provider smoke opt-in only",
        "request budget",
        "timeout",
        "provider adapter",
        "local wav opt-in",
        "metadata-only output",
        "Replay never reruns provider",
    ):
        assert required in content
    for forbidden in (
        "sk-",
        "api_key_value",
        "credential value",
        "BEGIN SECRET",
        "local/path/to/real.wav",
    ):
        assert forbidden not in content


def _load_manifest() -> dict[str, Any]:
    return load_json_fixture(MVP5_MANIFEST)


def _scenario_ids_from_spec() -> list[str]:
    text = SCENARIO_SPEC.read_text(encoding="utf-8")
    scenario_ids = re.findall(r"^### (MVP5-[A-Z0-9-]+)$", text, flags=re.MULTILINE)
    assert scenario_ids, "MVP-5 acceptance scenario spec must declare scenario ids"
    return scenario_ids


def _missing_mvp4_prerequisites() -> list[str]:
    return sorted(name for name, path in MVP4_PREREQUISITES.items() if not path.exists())


def _assert_manifest_is_repo_safe(manifest: dict[str, Any]) -> None:
    for key, expected in REQUIRED_SAFETY_FLAGS.items():
        if manifest.get(key) is not expected:
            raise MVP5AcceptanceError(f"{key} must be {expected!r}")
    rendered = json.dumps(manifest.get("safe_ref_examples", []), sort_keys=True)
    unsafe_markers = (
        "file://",
        "data:",
        "/Users/",
        "audio/raw/",
        "diagnostics/",
        "traces/",
        "replays/local/",
        ".env",
    )
    for marker in unsafe_markers:
        if marker in rendered:
            raise MVP5AcceptanceError(f"unsafe ref marker found: {marker}")
