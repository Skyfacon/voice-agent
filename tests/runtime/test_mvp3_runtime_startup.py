from __future__ import annotations

import http.client
from pathlib import Path
import socket
import urllib.request

import pytest

from tests.adapters.test_mvp3_adapter_profiles import (
    mvp3_real_capability,
    valid_mvp3_real_profiles,
)
from voice_agent.events.envelope import validate_event_envelope
from voice_agent.replay.runner import run_replay_fixture
from voice_agent.runtime.assembly import RuntimeAdapterAssemblyConfig, RuntimeAdapterAssemblyError
from voice_agent.runtime.session import start_configured_session


SPEC_PATH = Path("docs/specs/mvp3-acceptance-scenarios.md")


def test_mvp3_runtime_assembly_spec_names_slice3_snapshot_contract() -> None:
    runtime_section = SPEC_PATH.read_text(encoding="utf-8").split(
        "## Scenario MVP3-RUNTIME-ASSEMBLY-001",
        maxsplit=1,
    )[1].split("## Scenario", maxsplit=1)[0]

    for required_text in (
        "SESSION_STARTED",
        "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
        "capability_snapshot_ref",
        "adapter_ids",
        "adapter_types",
        "deployment_modes",
        "output_modes",
        "capability_version",
        "No startup network healthcheck",
    ):
        assert required_text in runtime_section


def test_mvp3_startup_records_session_then_snapshot_with_journal_owned_event_seq_and_explicit_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    network_calls = _block_network_probe_attempts(monkeypatch)

    startup = start_configured_session(
        session_id="sess_mvp3_slice3_runtime_synthetic",
        conversation_id="conv_mvp3_slice3_runtime_synthetic",
        runtime_config_ref="config://synthetic/mvp3/slice3-runtime",
        created_monotonic_ms=100,
        created_wall_clock_ms=1700000000100,
        assembly_config=_assembly_config(),
        capabilities=_profiles_with_explicit_real_fallback_degraded_modes(),
    )

    events = startup.journal.events()

    assert [event["event_name"] for event in events] == [
        "SESSION_STARTED",
        "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
    ]
    assert [event["event_seq"] for event in events] == [1, 2]
    assert "caused_by_event_id" not in events[0]
    assert events[1]["caused_by_event_id"] == events[0]["event_id"]
    assert events[0]["capability_snapshot_ref"] == events[1]["capability_snapshot_ref"]
    assert events[1]["capability_snapshot_ref"] == "capability://synthetic/mvp3/slice3-runtime"
    assert events[1]["adapter_ids"] == [
        "mvp3_asr",
        "mvp3_thinker",
        "mvp3_slow_llm",
        "mvp3_tts",
        "mvp3_slow_llm_fallback",
        "mvp3_tts_degraded",
    ]
    assert events[1]["adapter_types"] == [
        "asr",
        "thinker",
        "slow_llm",
        "tts",
        "slow_llm",
        "tts",
    ]
    assert events[1]["deployment_modes"] == [
        "remote_api",
        "remote_api",
        "remote_api",
        "remote_api",
        "remote_api",
        "remote_api",
    ]
    assert events[1]["output_modes"] == ["real", "real", "real", "real", "fallback", "degraded"]
    assert events[1]["capability_version"] == "mvp3.contract.v1"
    assert startup.capability_snapshot == {
        "capability_snapshot_ref": "capability://synthetic/mvp3/slice3-runtime",
        "adapter_ids": [
            "mvp3_asr",
            "mvp3_thinker",
            "mvp3_slow_llm",
            "mvp3_tts",
            "mvp3_slow_llm_fallback",
            "mvp3_tts_degraded",
        ],
        "adapter_types": ["asr", "thinker", "slow_llm", "tts", "slow_llm", "tts"],
        "deployment_modes": ["remote_api", "remote_api", "remote_api", "remote_api", "remote_api", "remote_api"],
        "output_modes": ["real", "real", "real", "real", "fallback", "degraded"],
        "capability_version": "mvp3.contract.v1",
    }
    assert all(validate_event_envelope(event) == event for event in events)
    assert network_calls == []


def test_mvp3_startup_replays_deterministically_without_provider_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    startup = start_configured_session(
        session_id="sess_mvp3_slice3_replay_synthetic",
        conversation_id="conv_mvp3_slice3_replay_synthetic",
        runtime_config_ref="config://synthetic/mvp3/slice3-replay",
        created_monotonic_ms=100,
        created_wall_clock_ms=1700000000100,
        assembly_config=_assembly_config(
            capability_snapshot_ref="capability://synthetic/mvp3/slice3-replay"
        ),
        capabilities=valid_mvp3_real_profiles(),
    )
    network_calls = _block_network_probe_attempts(monkeypatch)

    result = run_replay_fixture(
        {
            "replay_manifest": _github_allowed_replay_manifest(),
            "events": startup.journal.events(),
        }
    )

    assert result.result_status == "passed"
    assert result.replay_mode == "deterministic"
    assert [event["event_name"] for event in result.ordered_events] == [
        "SESSION_STARTED",
        "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
    ]
    assert result.state_digest["source_session_id"] == "sess_mvp3_slice3_replay_synthetic"
    assert result.state_digest["last_event_seq"] == 2
    assert [event["event_seq"] for event in result.replay_events] == [3, 4]
    assert network_calls == []


@pytest.mark.parametrize(
    "capabilities",
    (
        tuple(capability for capability in valid_mvp3_real_profiles() if capability.adapter_type != "tts"),
        (
            mvp3_real_capability("asr", supports_audio_input=False),
            *valid_mvp3_real_profiles()[1:],
        ),
    ),
)
def test_mvp3_startup_fails_closed_for_incomplete_or_unsupported_profile_sets(
    capabilities: tuple[object, ...],
) -> None:
    with pytest.raises(RuntimeAdapterAssemblyError):
        start_configured_session(
            session_id="sess_mvp3_slice3_fail_closed_synthetic",
            conversation_id="conv_mvp3_slice3_fail_closed_synthetic",
            runtime_config_ref="config://synthetic/mvp3/slice3-fail-closed",
            created_monotonic_ms=100,
            created_wall_clock_ms=1700000000100,
            assembly_config=_assembly_config(),
            capabilities=capabilities,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("unsafe_target", "unsafe_value"),
    (
        ("runtime_config_ref", "config://synthetic/mvp3/slice3?token=synthetic"),
        ("capability_snapshot_ref", "capability://synthetic/mvp3/slice3?api_key=synthetic"),
        ("endpoint", "endpoint://synthetic/mvp3/asr?authorization=synthetic"),
        ("config_ref", "config://synthetic/mvp3/asr?credential=synthetic"),
        ("mock_profile_ref", "profile://synthetic/mvp3/asr?token=synthetic"),
    ),
)
def test_mvp3_startup_fails_closed_for_credential_like_refs_before_startup(
    unsafe_target: str,
    unsafe_value: str,
) -> None:
    config = _assembly_config()
    runtime_config_ref = "config://synthetic/mvp3/slice3-ref-safety"
    capabilities = valid_mvp3_real_profiles()

    if unsafe_target == "runtime_config_ref":
        runtime_config_ref = unsafe_value
    elif unsafe_target == "capability_snapshot_ref":
        config = _assembly_config(capability_snapshot_ref=unsafe_value)
    else:
        capabilities = (
            mvp3_real_capability("asr", **{unsafe_target: unsafe_value}),
            *capabilities[1:],
        )

    with pytest.raises(RuntimeAdapterAssemblyError, match="credential"):
        start_configured_session(
            session_id="sess_mvp3_slice3_ref_safety_synthetic",
            conversation_id="conv_mvp3_slice3_ref_safety_synthetic",
            runtime_config_ref=runtime_config_ref,
            created_monotonic_ms=100,
            created_wall_clock_ms=1700000000100,
            assembly_config=config,
            capabilities=capabilities,
        )


def _assembly_config(
    *,
    capability_snapshot_ref: str = "capability://synthetic/mvp3/slice3-runtime",
) -> RuntimeAdapterAssemblyConfig:
    return RuntimeAdapterAssemblyConfig(
        stage="mvp3",
        capability_snapshot_ref=capability_snapshot_ref,
        capability_version="mvp3.contract.v1",
    )


def _profiles_with_explicit_real_fallback_degraded_modes() -> tuple[object, ...]:
    return (
        *valid_mvp3_real_profiles(),
        mvp3_real_capability(
            "slow_llm",
            adapter_id="mvp3_slow_llm_fallback",
            provider="synthetic_fallback",
            endpoint="endpoint://synthetic/mvp3/slow_llm/fallback",
            config_ref="config://synthetic/mvp3/slow_llm/fallback",
            output_mode="fallback",
        ),
        mvp3_real_capability(
            "tts",
            adapter_id="mvp3_tts_degraded",
            provider="synthetic_degraded",
            endpoint="endpoint://synthetic/mvp3/tts/degraded",
            config_ref="config://synthetic/mvp3/tts/degraded",
            output_mode="degraded",
        ),
    )


def _github_allowed_replay_manifest() -> dict[str, object]:
    return {
        "manifest_schema_version": "1.0",
        "replay_id": "replay_mvp3_runtime_assembly_001",
        "source_trace_ref": "fixture://mvp3/runtime-assembly-inline",
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


def _block_network_probe_attempts(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    network_calls: list[object] = []

    def fail_if_network_probe_is_attempted(*args: object, **kwargs: object) -> None:
        network_calls.append((args, kwargs))
        raise AssertionError("MVP-3 runtime startup/replay must not probe provider endpoints")

    monkeypatch.setattr(socket, "create_connection", fail_if_network_probe_is_attempted)
    monkeypatch.setattr(urllib.request, "urlopen", fail_if_network_probe_is_attempted)
    monkeypatch.setattr(http.client.HTTPConnection, "connect", fail_if_network_probe_is_attempted)
    monkeypatch.setattr(http.client.HTTPSConnection, "connect", fail_if_network_probe_is_attempted)
    return network_calls
