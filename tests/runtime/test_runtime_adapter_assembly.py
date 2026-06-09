from __future__ import annotations

import pytest

from tests.adapters.test_mvp3_adapter_profiles import valid_mvp3_real_profiles
from voice_agent.adapters.mock_adapters import mvp0_mock_adapter_capabilities
from voice_agent.events.envelope import validate_event_envelope
from voice_agent.runtime.assembly import (
    RuntimeAdapterAssemblyConfig,
    RuntimeAdapterAssemblyError,
    assemble_runtime_adapters,
)
from voice_agent.runtime.session import start_configured_session


def test_mvp3_runtime_assembly_rejects_mock_only_profiles() -> None:
    config = RuntimeAdapterAssemblyConfig(
        stage="mvp3",
        capability_snapshot_ref="capability://synthetic/mvp3/mock-only",
        capability_version="mvp3.contract.v1",
    )

    with pytest.raises(RuntimeAdapterAssemblyError, match="real adapter profile"):
        assemble_runtime_adapters(config, mvp0_mock_adapter_capabilities())


def test_mvp3_runtime_assembly_builds_snapshot_for_valid_profiles() -> None:
    config = RuntimeAdapterAssemblyConfig(
        stage="mvp3",
        capability_snapshot_ref="capability://synthetic/mvp3/contract-valid",
        capability_version="mvp3.contract.v1",
    )

    assembly = assemble_runtime_adapters(config, valid_mvp3_real_profiles())

    assert assembly.capability_snapshot == {
        "capability_snapshot_ref": "capability://synthetic/mvp3/contract-valid",
        "adapter_ids": ["mvp3_asr", "mvp3_thinker", "mvp3_slow_llm", "mvp3_tts"],
        "adapter_types": ["asr", "thinker", "slow_llm", "tts"],
        "deployment_modes": ["remote_api", "remote_api", "remote_api", "remote_api"],
        "output_modes": ["real", "real", "real", "real"],
        "capability_version": "mvp3.contract.v1",
    }


def test_start_configured_session_records_assembled_capability_snapshot() -> None:
    config = RuntimeAdapterAssemblyConfig(
        stage="mvp3",
        capability_snapshot_ref="capability://synthetic/mvp3/session-start",
        capability_version="mvp3.contract.v1",
    )

    startup = start_configured_session(
        session_id="sess_mvp3_contract_synthetic",
        conversation_id="conv_mvp3_contract_synthetic",
        runtime_config_ref="config://synthetic/mvp3/contract",
        created_monotonic_ms=100,
        created_wall_clock_ms=1700000000100,
        assembly_config=config,
        capabilities=valid_mvp3_real_profiles(),
    )

    events = startup.journal.events()

    assert [event["event_name"] for event in events] == [
        "SESSION_STARTED",
        "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
    ]
    assert events[1]["adapter_types"] == ["asr", "thinker", "slow_llm", "tts"]
    assert events[1]["output_modes"] == ["real", "real", "real", "real"]
    assert events[0]["capability_snapshot_ref"] == events[1]["capability_snapshot_ref"]
    for event in events:
        assert validate_event_envelope(event) == event
