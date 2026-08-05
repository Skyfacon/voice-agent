from __future__ import annotations

from voice_agent.adapters.parallel_fast_interaction_profile import (
    build_parallel_fast_interaction_orchestrator_profile,
)


def test_parallel_orchestrator_profile_is_local_join_only() -> None:
    matrix = build_parallel_fast_interaction_orchestrator_profile().to_dict()

    assert matrix["adapter_type"] == "fast_interaction"
    assert matrix["provider"] == "local_parallel_orchestrator"
    assert matrix["deployment_mode"] == "provider_free"
    assert matrix["endpoint"].startswith("mock://")
    assert matrix["status"] == "mock"
    assert matrix["output_mode"] == "mock"
    assert matrix["supports_fast_interaction_output"] is True
    assert matrix["supports_reply_candidate"] is True
    assert matrix["supports_reply_delta_streaming"] is False
    assert matrix["supports_streaming_input"] is False
    assert matrix["supports_streaming_output"] is False
    assert matrix["supports_audio_input"] is False
    assert matrix["supports_audio_output"] is False
    assert matrix["supports_route_schema"] is False
    assert matrix["supports_candidate_safety_schema"] is False
    assert matrix["supports_risk_tags"] is False
    assert matrix["supports_confidence"] is False
    assert matrix["documentation_support"] is True
    assert matrix["provider_free_test_support"] is True
    assert matrix["real_live_support"] is False
