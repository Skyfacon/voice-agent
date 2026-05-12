from __future__ import annotations

import re
from typing import Any

import pytest

from conftest import MVP0_REPLAY_FIXTURE_DIR, MVP1_REPLAY_FIXTURE_DIR, REPO_ROOT, load_json_fixture
from voice_agent.events.registry import MVP1_EVENT_NAMES
from voice_agent.privacy.redaction import is_safe_authorization_ref
from voice_agent.replay.runner import run_replay_fixture


GITHUB_ALLOWED_FIXTURE = MVP0_REPLAY_FIXTURE_DIR / "000-empty-session.fixture.json"
MVP1_EMPTY_FIXTURE = MVP1_REPLAY_FIXTURE_DIR / "000-empty-mvp1-session.fixture.json"
MVP1_MANIFEST_INDEX = MVP1_REPLAY_FIXTURE_DIR / "manifest.index.json"

REQUIRED_GITIGNORE_LINES = {
    "diagnostics/",
    "traces/",
    "replays/local/",
    "audio/raw/",
    ".env",
    ".env.*",
}

FORBIDDEN_KEY_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"api[_-]?key",
        r"authorization",
        r"credential",
        r"cookie",
        r"password",
        r"secret",
        r"session[_-]?secret",
        r"token",
    )
)

RAW_AUDIO_EXTENSIONS = (".aac", ".aiff", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav", ".weba")
RAW_TRACE_KEY_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"raw[_-]?audio",
        r"raw[_-]?trace",
        r"raw[_-]?transcript",
        r"raw[_-]?user[_-]?text",
        r"raw[_-]?web",
    )
)
REAL_USER_TEXT_KEY_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"real[_-]?user[_-]?input",
        r"unredacted[_-]?user",
        r"user[_-]?utterance",
        r"user[_-]?text",
    )
)
ALLOWED_MANIFEST_SAFETY_FLAGS = {
    "contains_raw_audio",
    "contains_raw_trace",
    "contains_real_user_input",
    "contains_secrets",
    "contains_unredacted_tool_result",
    "contains_large_raw_web_content",
}
ALLOWED_SAFE_SECRET_METADATA_KEYS = {
    "secret_kind",
}
ALLOWED_SAFE_REF_KEYS = {
    "authorization_ref",
}
REQUIRED_REPLAY_MANIFEST_FIELDS = {
    "manifest_schema_version",
    "replay_id",
    "source_trace_ref",
    "replay_mode",
    "event_schema_version_range",
    "fixture_domain",
    "generated_from",
    "contains_raw_audio",
    "contains_raw_trace",
    "contains_real_user_input",
    "contains_secrets",
    "contains_unredacted_tool_result",
    "contains_large_raw_web_content",
}
MVP2_ONLY_EVENT_NAMES = frozenset(
    {
        "TOOL_EXECUTION_STARTED",
        "TOOL_PROGRESS_UPDATED",
        "TOOL_UI_STATE_PATCHED",
        "TOOL_MANIFEST_LOADED",
        "TOOL_EXECUTION_AUTHORIZED",
        "SPOKEN_PLAN_EMITTED",
        "COMMITMENT_COVERAGE_CHECK_PASSED",
        "COMMITMENT_COVERAGE_CHECK_FAILED",
        "PROGRESS_TRUTHFULNESS_CHECK_PASSED",
        "PROGRESS_TRUTHFULNESS_CHECK_FAILED",
    }
)
NON_CANONICAL_RELATIONSHIP_LABELS = frozenset(
    {
        "SEMANTIC_COMMITMENT_CREATED",
        "STALE_TOOL_RESULT_RECORDED",
        "SPOKEN_PLAN_CREATED",
    }
)


def iter_json_values(value: Any, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Any]]:
    values = [(path, value)]
    if isinstance(value, dict):
        for key, child in value.items():
            values.extend(iter_json_values(child, (*path, str(key))))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            values.extend(iter_json_values(child, (*path, str(index))))
    return values


def github_allowed_manifest(**overrides: Any) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "manifest_schema_version": "1.0",
        "replay_id": "replay_synthetic_inline",
        "source_trace_ref": "fixture://mvp0/synthetic-inline",
        "replay_mode": "deterministic",
        "event_schema_version_range": ["1.0"],
        "fixture_domain": "GITHUB_ALLOWED",
        "generated_from": "synthetic",
        "contains_raw_audio": False,
        "contains_raw_trace": False,
        "contains_real_user_input": False,
        "contains_secrets": False,
        "contains_unredacted_tool_result": False,
        "contains_large_raw_web_content": False,
        "allowed_re_eval_components": [],
    }
    manifest.update(overrides)
    return manifest


def assert_fixture_is_github_safe(fixture: dict[str, Any]) -> None:
    manifest = fixture["replay_manifest"]
    assert REQUIRED_REPLAY_MANIFEST_FIELDS <= set(manifest), sorted(
        REQUIRED_REPLAY_MANIFEST_FIELDS - set(manifest)
    )
    assert manifest["manifest_schema_version"] == "1.0"
    assert manifest["replay_id"].startswith("replay_")
    assert manifest["source_trace_ref"].startswith("fixture://")
    assert manifest["replay_mode"] in {"deterministic", "degraded", "re_eval"}
    assert manifest["event_schema_version_range"] == ["1.0"]
    assert manifest["fixture_domain"] == "GITHUB_ALLOWED"
    assert manifest["generated_from"] in {"synthetic", "redacted", "hand_written_minimal"}
    assert manifest["contains_raw_audio"] is False
    assert manifest["contains_raw_trace"] is False
    assert manifest["contains_real_user_input"] is False
    assert manifest["contains_secrets"] is False
    assert manifest["contains_unredacted_tool_result"] is False
    assert manifest["contains_large_raw_web_content"] is False

    for path, value in iter_json_values(fixture):
        key_path = ".".join(path)
        last_key = path[-1] if path else ""

        if path[:1] == ("replay_manifest",) and last_key in ALLOWED_MANIFEST_SAFETY_FLAGS:
            assert value is False, key_path
            continue
        if last_key in ALLOWED_SAFE_SECRET_METADATA_KEYS:
            assert isinstance(value, str), key_path
            assert not value.lower().startswith(("sk-", "bearer ")), key_path
            continue
        if last_key in ALLOWED_SAFE_REF_KEYS:
            assert isinstance(value, str), key_path
            _assert_safe_string_fixture_value(value, key_path)
            if last_key == "authorization_ref":
                assert is_safe_authorization_ref(value, allow_local=False), key_path
            continue

        assert not any(pattern.search(last_key) for pattern in FORBIDDEN_KEY_PATTERNS), key_path
        assert not any(pattern.search(last_key) for pattern in RAW_TRACE_KEY_PATTERNS), key_path
        assert not any(pattern.search(last_key) for pattern in REAL_USER_TEXT_KEY_PATTERNS), key_path

        if isinstance(value, str):
            _assert_safe_string_fixture_value(value, key_path)


def _assert_safe_string_fixture_value(value: str, key_path: str) -> None:
    lower_value = value.lower()
    assert not lower_value.startswith(("sk-", "bearer ")), key_path
    assert not any(lower_value.endswith(extension) for extension in RAW_AUDIO_EXTENSIONS), key_path
    assert "audio/raw/" not in lower_value, key_path
    assert "traces/" not in lower_value, key_path
    assert "diagnostics/" not in lower_value, key_path
    assert "replays/local/" not in lower_value, key_path
    assert "raw trace" not in lower_value, key_path
    assert "real user" not in lower_value, key_path


def test_local_debug_artifacts_are_ignored_before_runtime_writes() -> None:
    gitignore_lines = {
        line.strip()
        for line in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }

    assert REQUIRED_GITIGNORE_LINES <= gitignore_lines


def test_runtime_artifact_policy_defaults_do_not_create_local_artifacts() -> None:
    artifact_paths = {
        REPO_ROOT / "diagnostics",
        REPO_ROOT / "traces",
        REPO_ROOT / "replays" / "local",
        REPO_ROOT / "audio" / "raw",
    }
    existence_before_import = {path: path.exists() for path in artifact_paths}

    from voice_agent.config.runtime_config import DEFAULT_RUNTIME_ARTIFACT_POLICY

    assert DEFAULT_RUNTIME_ARTIFACT_POLICY.local_debug_trace_enabled is True
    assert DEFAULT_RUNTIME_ARTIFACT_POLICY.raw_audio_enabled is False
    assert DEFAULT_RUNTIME_ARTIFACT_POLICY.raw_audio_retention_days == 0
    assert DEFAULT_RUNTIME_ARTIFACT_POLICY.cross_machine_raw_audio_sync is False
    assert DEFAULT_RUNTIME_ARTIFACT_POLICY.github_trace_upload == "synthetic_or_redacted_only"
    assert DEFAULT_RUNTIME_ARTIFACT_POLICY.commit_raw_trace is False
    assert DEFAULT_RUNTIME_ARTIFACT_POLICY.commit_raw_audio is False
    assert DEFAULT_RUNTIME_ARTIFACT_POLICY.credential_trace_policy == "never"
    assert set(DEFAULT_RUNTIME_ARTIFACT_POLICY.local_only_artifact_paths) == {
        "diagnostics/",
        "traces/",
        "replays/local/",
        "audio/raw/",
    }

    assert {path: path.exists() for path in artifact_paths} == existence_before_import


def test_empty_session_fixture_lives_in_github_allowed_fixture_dir() -> None:
    assert GITHUB_ALLOWED_FIXTURE.parent == MVP0_REPLAY_FIXTURE_DIR
    assert "replays/local" not in GITHUB_ALLOWED_FIXTURE.as_posix()
    assert GITHUB_ALLOWED_FIXTURE.is_file()


def test_empty_session_fixture_is_synthetic_minimal_and_github_safe() -> None:
    fixture = load_json_fixture(GITHUB_ALLOWED_FIXTURE)

    assert_fixture_is_github_safe(fixture)
    assert fixture["events"] == []


def test_empty_mvp1_fixture_lives_in_github_allowed_fixture_dir() -> None:
    assert MVP1_EMPTY_FIXTURE.parent == MVP1_REPLAY_FIXTURE_DIR
    assert "replays/local" not in MVP1_EMPTY_FIXTURE.as_posix()
    assert MVP1_EMPTY_FIXTURE.is_file()


def test_empty_mvp1_fixture_is_synthetic_minimal_and_github_safe() -> None:
    fixture = load_json_fixture(MVP1_EMPTY_FIXTURE)

    assert_fixture_is_github_safe(fixture)
    assert fixture["replay_manifest"]["replay_id"] == "replay_mvp1_empty_session_000"
    assert fixture["replay_manifest"]["source_trace_ref"] == "fixture://mvp1/000-empty-mvp1-session"
    assert fixture["replay_manifest"]["replay_mode"] == "deterministic"
    assert fixture["replay_manifest"]["fixture_domain"] == "GITHUB_ALLOWED"
    assert fixture["replay_manifest"]["generated_from"] == "hand_written_minimal"
    assert fixture["events"] == []


def test_empty_mvp1_fixture_replays_with_empty_task_and_slowtask_digest_fields() -> None:
    result = run_replay_fixture(load_json_fixture(MVP1_EMPTY_FIXTURE))

    assert result.replay_mode == "deterministic"
    assert result.fixture_domain == "GITHUB_ALLOWED"
    assert result.ordered_events == ()
    assert result.state_digest["source_session_id"] is None
    assert result.state_digest["last_event_seq"] == 0
    assert result.state_digest["task_focus_state_hash"]
    assert result.state_digest["slowtask_state_hash"]
    assert [event["event_name"] for event in result.replay_events] == [
        "REPLAY_STARTED",
        "REPLAY_COMPLETED",
    ]


def test_mvp1_manifest_index_is_slice0_3_and_repo_safe() -> None:
    manifest_index = load_json_fixture(MVP1_MANIFEST_INDEX)

    assert manifest_index["manifest_index_schema_version"] == "1.0"
    assert manifest_index["suite_id"] == "MVP1-SLICE0-3"
    assert manifest_index["fixture_domain"] == "GITHUB_ALLOWED"
    assert manifest_index["replay_mode"] == "deterministic"
    assert manifest_index["required_scenarios"] == []
    assert manifest_index["fixture_checks"] == [
        {
            "fixture": "000-empty-mvp1-session.fixture.json",
            "purpose": "empty MVP-1 replay safety skeleton",
        },
        {
            "fixture": "002-task-focus-router.fixture.json",
            "purpose": "TaskFocusState router decision replay for MVP-1 Slice 2",
        },
        {
            "fixture": "003-slowtask-reducer-skeleton.fixture.json",
            "purpose": "SlowTaskState deterministic replay skeleton for completed and cancelled terminal tasks",
        },
        {
            "fixture": "003-slowtask-failed-sticky.fixture.json",
            "purpose": "SlowTaskState failed terminal stickiness with late metadata-only events",
        },
    ]
    assert MVP2_ONLY_EVENT_NAMES <= set(manifest_index["forbidden_event_names"])
    assert NON_CANONICAL_RELATIONSHIP_LABELS <= set(manifest_index["forbidden_event_names"])


@pytest.mark.parametrize("fixture_path", sorted(MVP0_REPLAY_FIXTURE_DIR.glob("*.fixture.json")))
def test_all_mvp0_replay_fixtures_are_github_safe(fixture_path) -> None:
    assert fixture_path.parent == MVP0_REPLAY_FIXTURE_DIR
    assert "replays/local" not in fixture_path.as_posix()

    assert_fixture_is_github_safe(load_json_fixture(fixture_path))


@pytest.mark.parametrize("fixture_path", sorted(MVP1_REPLAY_FIXTURE_DIR.glob("*.fixture.json")))
def test_all_mvp1_replay_fixtures_are_github_safe(fixture_path) -> None:
    assert fixture_path.parent == MVP1_REPLAY_FIXTURE_DIR
    assert "replays/local" not in fixture_path.as_posix()

    assert_fixture_is_github_safe(load_json_fixture(fixture_path))


def test_mvp0_manifest_forbids_mvp1_and_later_event_names() -> None:
    manifest_index = load_json_fixture(MVP0_REPLAY_FIXTURE_DIR / "manifest.index.json")
    forbidden_event_names = set(manifest_index["forbidden_event_names"])

    assert MVP1_EVENT_NAMES <= forbidden_event_names
    assert MVP2_ONLY_EVENT_NAMES <= forbidden_event_names

    for fixture_path in MVP0_REPLAY_FIXTURE_DIR.glob("*.fixture.json"):
        fixture = load_json_fixture(fixture_path)
        emitted_event_names = {event["event_name"] for event in fixture["events"]}
        assert emitted_event_names.isdisjoint(MVP1_EVENT_NAMES | MVP2_ONLY_EVENT_NAMES), fixture_path.name


def test_fixture_safety_gate_allows_blocked_secret_metadata_without_secret_value() -> None:
    fixture = {
        "replay_manifest": github_allowed_manifest(),
        "events": [
            {
                "event_name": "TRACE_WRITE_BLOCKED_SECRET_DETECTED",
                "event_id": "evt_synthetic_blocked_secret",
                "secret_kind": "api_key",
                "blocking_reason": "synthetic secret-like field blocked before append",
            }
        ],
    }

    assert_fixture_is_github_safe(fixture)


def test_fixture_safety_gate_allows_redacted_authorization_ref_without_secret_value() -> None:
    fixture = {
        "replay_manifest": github_allowed_manifest(),
        "events": [
            {
                "event_name": "CONFIRMATION_ACCEPTED",
                "event_id": "evt_synthetic_confirmation_accepted",
                "authorization_ref": "authorization://synthetic/mvp1/current-plan-confirmation",
            }
        ],
    }

    assert_fixture_is_github_safe(fixture)


@pytest.mark.parametrize(
    "authorization_ref",
    [
        "authorization://sk-live-secret",
        "authorization://synthetic/mvp1/current?token=abc123",
        "authorization://synthetic/mvp1/current?access_token=abc123",
        "authorization://synthetic/mvp1/current#token=abc123",
        "authorization://synthetic/mvp1/%3Faccess_token=abc123",
        "authorization://synthetic/mvp1/%23token=abc123",
        "authorization://synthetic/mvp1/%26token=abc123",
        "authorization://synthetic/mvp1/bearer abc123",
    ],
)
def test_fixture_safety_gate_rejects_authorization_ref_with_embedded_secret(
    authorization_ref: str,
) -> None:
    fixture = {
        "replay_manifest": github_allowed_manifest(),
        "events": [
            {
                "event_name": "CONFIRMATION_ACCEPTED",
                "event_id": "evt_synthetic_confirmation_accepted",
                "authorization_ref": authorization_ref,
            }
        ],
    }

    with pytest.raises(AssertionError):
        assert_fixture_is_github_safe(fixture)


@pytest.mark.parametrize(
    "payload",
    [
        {"raw_audio_ref": "audio/raw/session.wav"},
        {"raw_trace_payload": {"debug": "trace data should stay local"}},
        {"api_key": "sk-test-secret"},
        {"authorization_header": "Bearer sk-test-secret"},
        {"user_text": "unredacted input"},
    ],
)
def test_fixture_safety_gate_rejects_disallowed_payloads(payload: dict[str, Any]) -> None:
    unsafe_fixture = {
        "replay_manifest": github_allowed_manifest(),
        "events": [
            {
                "event_id": "evt_synthetic_unsafe",
                "payload": payload,
            }
        ],
    }

    with pytest.raises(AssertionError):
        assert_fixture_is_github_safe(unsafe_fixture)
