from __future__ import annotations

from copy import deepcopy
import importlib
import os
import random
import socket
import time
from typing import Any

import pytest

from conftest import REPO_ROOT, load_json_fixture
from tests.replay.test_fixture_safety import assert_fixture_is_github_safe
from voice_agent.replay.runner import run_replay_fixture
from voice_agent.runtime import mvp4_voice_e2e_orchestrator as mvp4


MVP4_REPLAY_FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "replay" / "mvp4"
PROVIDER_FREE_FIXTURE = MVP4_REPLAY_FIXTURE_DIR / "000-provider-free-voice-e2e.fixture.json"
REPLAY_SAFETY_FIXTURE = MVP4_REPLAY_FIXTURE_DIR / "008-replay-safety.fixture.json"
MANIFEST_INDEX = MVP4_REPLAY_FIXTURE_DIR / "manifest.index.json"
README = MVP4_REPLAY_FIXTURE_DIR / "README.md"

REQUIRED_MVP4_SCENARIOS = [
    "MVP4-VOICE-E2E-PROVIDER-FREE-001",
    "MVP4-VOICE-E2E-ROUTER-FAST-001",
    "MVP4-VOICE-E2E-ROUTER-SPAWN-SLOWTASK-001",
    "MVP4-VOICE-E2E-ROUTER-PATCH-SLOWTASK-001",
    "MVP4-VOICE-E2E-REPLAY-SAFETY-001",
    "MVP4-VOICE-E2E-RAW-ARTIFACT-BLOCK-001",
]
EXPECTED_FALSE_SAFETY_FLAGS = {
    "contains_raw_audio": False,
    "contains_raw_trace": False,
    "contains_real_user_input": False,
    "contains_secrets": False,
    "contains_unredacted_tool_result": False,
    "contains_large_raw_web_content": False,
}


@pytest.mark.parametrize("fixture_path", sorted(MVP4_REPLAY_FIXTURE_DIR.glob("*.fixture.json")))
def test_all_committed_mvp4_fixtures_are_safe_and_replayable(fixture_path) -> None:
    assert fixture_path.parent == MVP4_REPLAY_FIXTURE_DIR
    assert "replays/local" not in fixture_path.as_posix()

    fixture = load_json_fixture(fixture_path)
    assert_fixture_is_github_safe(fixture)
    mvp4.validate_mvp4_fixture_safety(fixture)

    result = run_replay_fixture(fixture)
    assert result.result_status == "passed"
    assert result.replay_mode == "deterministic"
    assert result.fixture_domain == "GITHUB_ALLOWED"


def test_mvp4_replay_safety_fixture_exists_and_replays_without_runtime_reruns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert REPLAY_SAFETY_FIXTURE.is_file()
    fixture = load_json_fixture(REPLAY_SAFETY_FIXTURE)
    assert_fixture_is_github_safe(fixture)
    mvp4.validate_mvp4_fixture_safety(fixture)

    _guard_replay_against_unsafe_runtime_components(monkeypatch)

    result = run_replay_fixture(fixture)
    assert result.result_status == "passed"
    assert [event["event_name"] for event in result.replay_events] == [
        "REPLAY_STARTED",
        "REPLAY_COMPLETED",
    ]
    assert "raw" not in repr(result.state_digest).lower()
    assert "secret" not in repr(result.state_digest).lower()
    assert "provider_body" not in repr(result.state_digest).lower()


def test_mvp4_manifest_index_is_metadata_only_and_covers_replay_safety_scenarios() -> None:
    manifest = load_json_fixture(MANIFEST_INDEX)

    assert README.is_file()
    assert manifest["manifest_index_schema_version"] == "1.0"
    assert manifest["suite_id"] == "MVP4-PROVIDER-FREE-VOICE-SPINE"
    assert manifest["fixture_domain"] == "GITHUB_ALLOWED"
    assert manifest["replay_mode"] == "deterministic"
    assert manifest["generated_fixtures_must_be"] == ["synthetic", "redacted", "minimal"]
    assert manifest["required_scenarios"] == REQUIRED_MVP4_SCENARIOS
    assert manifest["fixture_safety_flags"] == EXPECTED_FALSE_SAFETY_FLAGS
    assert manifest["safety_flags"] == EXPECTED_FALSE_SAFETY_FLAGS
    assert manifest["allowed_re_eval_components"] == []

    fixture_checks = {check["fixture"]: check["purpose"] for check in manifest["fixture_checks"]}
    assert fixture_checks == {
        "000-provider-free-voice-e2e.fixture.json": (
            "provider-free synthetic audio turn replay covering fake ASR, fake Thinker, "
            "and Router FAST/SPAWN/PATCH decisions"
        ),
        "008-replay-safety.fixture.json": (
            "deterministic MVP-4 replay safety fixture proving recorded refs are replayed "
            "without provider or runtime reruns"
        ),
    }


@pytest.mark.parametrize(
    ("unsafe_field", "unsafe_value", "expected_error"),
    [
        ("raw_audio", "RIFF synthetic bytes", "raw_audio"),
        ("audio_bytes", b"RIFF", "audio_bytes"),
        ("audio_payload", "UklGRg==", "audio_payload"),
        ("raw_audio_bytes", b"RIFF", "raw_audio_bytes"),
        ("audio_base64", "UklGRg==", "audio_base64"),
        ("raw_transcript", "synthetic transcript", "raw_transcript"),
        ("transcript_text", "synthetic transcript", "transcript_text"),
        ("raw_text", "synthetic raw text", "raw_text"),
        ("provider_request", {"body": "unsafe"}, "provider_request"),
        ("provider_response", {"body": "unsafe"}, "provider_response"),
        ("provider_body", {"unsafe": True}, "provider_body"),
        ("provider_payload", {"unsafe": True}, "provider_payload"),
        ("provider_schema", {"type": "object"}, "provider_schema"),
        ("provider_specific_schema", {"type": "object"}, "provider_specific_schema"),
        ("prompt_dump", "full hidden prompt", "prompt_dump"),
        ("authorization_header", "Bearer sk-test-secret", "authorization_header"),
        ("cookie", "session=secret", "cookie"),
        ("credential", "sk-test-secret", "credential"),
        ("token", "sk-test-secret", "token"),
        ("api_key", "sk-test-secret", "api_key"),
    ],
)
def test_mvp4_safety_gate_rejects_unsafe_artifact_fields_one_at_a_time(
    unsafe_field: str,
    unsafe_value: object,
    expected_error: str,
) -> None:
    fixture = _provider_free_fixture()
    fixture["events"][0][unsafe_field] = unsafe_value

    with pytest.raises(mvp4.MVP4ArtifactSafetyError, match=expected_error):
        mvp4.validate_mvp4_fixture_safety(fixture)


@pytest.mark.parametrize(
    ("unsafe_value", "expected_error"),
    [
        ("data:audio/wav;base64,UklGRg==", "data URI"),
        ("file:///Users/a123/private/audio.wav", "file://"),
        ("audio/raw/private-input.wav", "audio/raw/"),
        ("diagnostics/mvp4/debug.jsonl", "diagnostics/"),
        ("traces/mvp4/raw-trace.jsonl", "traces/"),
        ("replays/local/mvp4/cache.json", "replays/local/"),
        ("/Users/a123/private/mvp4-trace.jsonl", "absolute local paths"),
        ("Bearer sk-test-secret", "bearer"),
        ("copied sk-test-secret into a ref", "secret-like"),
        ("AKIA1234567890ABCDEF", "secret-like"),
    ],
)
def test_mvp4_safety_gate_rejects_unsafe_string_refs_one_at_a_time(
    unsafe_value: str,
    expected_error: str,
) -> None:
    fixture = _provider_free_fixture()
    fixture["events"][0]["audio_format_ref"] = unsafe_value

    with pytest.raises(mvp4.MVP4ArtifactSafetyError, match=expected_error):
        mvp4.validate_mvp4_fixture_safety(fixture)


def _provider_free_fixture() -> dict[str, Any]:
    return deepcopy(load_json_fixture(PROVIDER_FREE_FIXTURE))


class _FailingEnviron(dict[str, str]):
    def __getitem__(self, key: str) -> str:
        pytest.fail(f"replay must not read env var {key}")

    def get(self, key: str, default: object = None) -> object:
        pytest.fail(f"replay must not read env var {key}")

    def keys(self):  # type: ignore[override]
        pytest.fail("replay must not enumerate environment variables")

    def items(self):  # type: ignore[override]
        pytest.fail("replay must not enumerate environment variables")

    def values(self):  # type: ignore[override]
        pytest.fail("replay must not enumerate environment variables")


def _guard_replay_against_unsafe_runtime_components(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "time", lambda: pytest.fail("replay must not call wall clock"))
    monkeypatch.setattr(time, "monotonic", lambda: pytest.fail("replay must not call monotonic clock"))
    monkeypatch.setattr(random, "random", lambda: pytest.fail("replay must not call randomness"))
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *args, **kwargs: pytest.fail("replay must not call network"),
    )
    monkeypatch.setattr(os, "environ", _FailingEnviron())
    _guard_optional_runtime_function(
        monkeypatch,
        "voice_agent.runtime.asr_session_hook",
        "run_asr_for_committed_audio_turn",
    )
    _guard_optional_runtime_function(
        monkeypatch,
        "voice_agent.adapters.lalm_thinker_audio_native_runtime",
        "emit_lalm_thinker_audio_native_evidence_for_turn",
    )
    _guard_optional_runtime_function(
        monkeypatch,
        "voice_agent.adapters.asr_runtime_adapter",
        "emit_asr_transcript_for_audio",
    )


def _guard_optional_runtime_function(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    function_name: str,
) -> None:
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError:
        return
    if not hasattr(module, function_name):
        return

    def _fail(*_args: object, **_kwargs: object) -> None:
        pytest.fail(f"replay must not call {module_name}.{function_name}")

    monkeypatch.setattr(module, function_name, _fail)
