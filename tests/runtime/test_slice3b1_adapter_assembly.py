from __future__ import annotations

from dataclasses import replace

import pytest

from voice_agent.adapters.parallel_fast_interaction_profile import (
    build_parallel_fast_interaction_orchestrator_profile,
)
from voice_agent.adapters.profiles import (
    AdapterProfileValidationError,
    validate_slice3b1_adapter_profile_set,
)
from voice_agent.adapters.qwen_realtime.profile import (
    build_qwen_realtime_asr_fake_profile,
    build_qwen_realtime_fake_profile,
)
from voice_agent.adapters.route_evidence_profile import (
    build_route_evidence_fake_profile,
)
from voice_agent.runtime.adapter_callback_boundary import ADAPTER_CALLBACK_EVENT_NAMES
from voice_agent.runtime.assembly import (
    RuntimeAdapterAssemblyConfig,
    RuntimeAdapterAssemblyError,
    assemble_runtime_adapters,
)
from voice_agent.runtime.session import start_configured_session


def _slice3b1_profiles():
    return (
        build_qwen_realtime_fake_profile(),
        build_qwen_realtime_asr_fake_profile(),
        build_route_evidence_fake_profile(),
        build_parallel_fast_interaction_orchestrator_profile(),
    )


def _slice3b1_config() -> RuntimeAdapterAssemblyConfig:
    return RuntimeAdapterAssemblyConfig(
        stage="slice3b1_mock",
        capability_snapshot_ref="capability://synthetic/slice3b1/provider-free",
        capability_version="slice3b1.mock.v1",
    )


def test_slice3b1_assembly_has_stable_compact_capability_digest() -> None:
    profiles = _slice3b1_profiles()

    forward = assemble_runtime_adapters(_slice3b1_config(), profiles)
    reverse = assemble_runtime_adapters(_slice3b1_config(), tuple(reversed(profiles)))

    assert forward.capability_matrices == reverse.capability_matrices
    assert forward.capability_snapshot == reverse.capability_snapshot
    assert set(forward.capability_snapshot) == {
        "capability_snapshot_ref",
        "adapter_ids",
        "adapter_types",
        "deployment_modes",
        "output_modes",
        "capability_version",
        "capability_matrix_digest",
    }
    assert forward.capability_snapshot["adapter_types"] == [
        "asr",
        "duplex_model",
        "fast_interaction",
        "route_evidence",
    ]
    digest = forward.capability_snapshot["capability_matrix_digest"]
    assert isinstance(digest, str)
    assert digest.startswith("sha256:")
    assert len(digest) == 71


def test_slice3b1_digest_changes_when_a_capability_fact_changes() -> None:
    profiles = _slice3b1_profiles()
    changed_profiles = (
        replace(profiles[0], supports_context_rebuild=False),
        *profiles[1:],
    )

    baseline = assemble_runtime_adapters(_slice3b1_config(), profiles)
    changed = assemble_runtime_adapters(_slice3b1_config(), changed_profiles)

    assert (
        baseline.capability_snapshot["capability_matrix_digest"]
        != changed.capability_snapshot["capability_matrix_digest"]
    )


@pytest.mark.parametrize(
    ("profile_index", "field", "value", "message"),
    (
        (0, "supports_provider_native_audio_release", True, "native provider audio release"),
        (0, "real_live_support", True, "real_live_support=false"),
        (1, "provider_free_test_support", False, "provider_free_test_support=true"),
        (2, "output_mode", "degraded", "output_mode=mock"),
    ),
)
def test_slice3b1_profile_set_fails_closed_for_non_mock_claims(
    profile_index: int,
    field: str,
    value: object,
    message: str,
) -> None:
    profiles = list(_slice3b1_profiles())
    profiles[profile_index] = replace(profiles[profile_index], **{field: value})

    with pytest.raises(AdapterProfileValidationError, match=message):
        validate_slice3b1_adapter_profile_set(profiles)


def test_slice3b1_profile_set_requires_each_role_exactly_once() -> None:
    profiles = _slice3b1_profiles()

    with pytest.raises(AdapterProfileValidationError, match="missing adapter types"):
        validate_slice3b1_adapter_profile_set(profiles[:-1])
    duplicate_asr_role = replace(profiles[1], adapter_id="slice3b1_second_asr_projection")
    with pytest.raises(AdapterProfileValidationError, match="exactly one asr"):
        validate_slice3b1_adapter_profile_set((*profiles, duplicate_asr_role))


def test_slice3b1_snapshot_event_contains_digest_but_no_capability_body() -> None:
    startup = start_configured_session(
        session_id="sess_slice3b1_capabilities",
        conversation_id="conv_slice3b1_capabilities",
        runtime_config_ref="config://synthetic/slice3b1/provider-free",
        created_monotonic_ms=100,
        created_wall_clock_ms=1_700_000_000_100,
        assembly_config=_slice3b1_config(),
        capabilities=_slice3b1_profiles(),
    )

    snapshot_event = startup.journal.events()[1]

    assert snapshot_event["capability_matrix_digest"] == (
        startup.capability_snapshot["capability_matrix_digest"]
    )
    assert "endpoint" not in snapshot_event
    assert "supports_provider_native_audio_release" not in snapshot_event
    assert "capability_matrices" not in snapshot_event


def test_slice3b1_route_and_safety_outputs_use_adapter_callback_boundary() -> None:
    assert "ROUTE_EVIDENCE_OUTPUT_EMITTED" in ADAPTER_CALLBACK_EVENT_NAMES
    assert "CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED" in ADAPTER_CALLBACK_EVENT_NAMES
    assert "FOREGROUND_ACT_GATE_PASSED" not in ADAPTER_CALLBACK_EVENT_NAMES
    assert "FOREGROUND_OUTPUT_COMMITTED" not in ADAPTER_CALLBACK_EVENT_NAMES


def test_runtime_assembly_rejects_slice_profiles_under_unknown_stage() -> None:
    bad_config = replace(_slice3b1_config(), stage="slice3b1")

    with pytest.raises(RuntimeAdapterAssemblyError, match="Unsupported"):
        assemble_runtime_adapters(bad_config, _slice3b1_profiles())
