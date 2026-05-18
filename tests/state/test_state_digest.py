from __future__ import annotations

from voice_agent.replay.state_digest import canonical_digest_payload, state_digest, stable_hash


def test_state_digest_is_stable_for_equivalent_state_with_different_key_order() -> None:
    first = {
        "current_turn_id": "turn_001",
        "nested": {"b": 2, "a": 1},
    }
    second = {
        "nested": {"a": 1, "b": 2},
        "current_turn_id": "turn_001",
    }

    assert stable_hash(first) == stable_hash(second)


def test_state_digest_excludes_raw_sensitive_and_tool_credential_payloads() -> None:
    base_state = {
        "safe_ref": "text://synthetic/mvp0/redacted",
        "raw_audio_payload": "audio bytes must not affect digest",
        "raw_text": "private text must not affect digest",
        "api_key": "sk-one",
        "authorization_header": "Bearer one",
        "raw_web_content": "large webpage body must not affect digest",
        "tool_credentials": {"token": "tool-token-one"},
    }
    changed_sensitive_state = {
        **base_state,
        "raw_audio_payload": "different audio bytes",
        "raw_text": "different private text",
        "api_key": "sk-two",
        "authorization_header": "Bearer two",
        "raw_web_content": "different large webpage body",
        "tool_credentials": {"token": "tool-token-two"},
    }

    assert stable_hash(base_state) == stable_hash(changed_sensitive_state)
    canonical = canonical_digest_payload(base_state)
    assert "raw_audio_payload" not in canonical
    assert "raw_text" not in canonical
    assert "api_key" not in canonical
    assert "authorization_header" not in canonical
    assert "raw_web_content" not in canonical
    assert "tool_credentials" not in canonical


def test_state_digest_preserves_safe_authorization_metadata() -> None:
    policy_authorized = {
        "authorization_basis": "current_plan_policy_allow",
        "authorization_event_id": "evt_tool_execution_authorized_policy",
        "authorization_header": "Bearer secret-one",
    }
    confirmation_authorized = {
        "authorization_basis": "current_plan_confirmation_acceptance",
        "authorization_event_id": "evt_tool_execution_authorized_confirmation",
        "authorization_header": "Bearer secret-two",
    }

    assert stable_hash(policy_authorized) != stable_hash(confirmation_authorized)
    canonical = canonical_digest_payload(policy_authorized)
    assert canonical["authorization_basis"] == "current_plan_policy_allow"
    assert canonical["authorization_event_id"] == "evt_tool_execution_authorized_policy"
    assert "authorization_header" not in canonical


def test_state_digest_shape_includes_required_component_hashes_without_raw_payloads() -> None:
    digest = state_digest(
        source_session_id="sess_mvp0_synthetic",
        last_event_seq=7,
        event_schema_version_range=["1.0"],
        interaction_state={"turn_phase": "IDLE", "raw_text": "excluded"},
        playback_state={"phase": "NOT_PLAYING", "raw_audio": "excluded"},
        adapter_health_state={"adapters": {"mock_asr": {"output_mode": "mock"}}},
        trace_privacy_state={"fixture_domain": "GITHUB_ALLOWED", "contains_secrets": False},
    )

    assert set(digest) == {
        "digest_schema_version",
        "source_session_id",
        "last_event_seq",
        "event_schema_version_range",
        "interaction_state_hash",
        "task_focus_state_hash",
        "slowtask_state_hash",
        "tool_execution_state_hash",
        "demo_ui_state_hash",
        "spoken_plan_state_hash",
        "playback_state_hash",
        "adapter_health_state_hash",
        "trace_privacy_state_hash",
        "overall_digest",
    }
    assert digest["digest_schema_version"] == "1.0"
    assert digest["source_session_id"] == "sess_mvp0_synthetic"
    assert digest["last_event_seq"] == 7
    assert "excluded" not in repr(digest)
