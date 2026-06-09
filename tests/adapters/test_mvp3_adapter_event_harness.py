from __future__ import annotations

from pathlib import Path
import socket
import urllib.request

import pytest

from tests.adapters.test_mvp3_adapter_profiles import (
    mvp3_real_capability,
    valid_mvp3_real_profiles,
)
from voice_agent.adapters.event_harness import (
    ADAPTER_EVENT_HARNESS_EVENT_NAMES,
    FakeRealAdapterEventHarness,
)
from voice_agent.events.envelope import validate_event_envelope
from voice_agent.privacy.redaction import PayloadBlockedError, REDACTED_SECRET_VALUE
from voice_agent.runtime.adapter_callback_boundary import AdapterCallbackAppendBoundary
from voice_agent.runtime.assembly import RuntimeAdapterAssemblyConfig
from voice_agent.runtime.session import start_configured_session


SPEC_PATH = Path("docs/specs/mvp3-acceptance-scenarios.md")
EXPECTED_ADAPTER_EVENT_NAMES = (
    "ADAPTER_HEALTHCHECK_FAILED",
    "ADAPTER_REQUEST_RETRYING",
    "ADAPTER_REQUEST_FAILED",
    "ADAPTER_OUTPUT_VALIDATION_FAILED",
    "ADAPTER_OUTPUT_DEGRADED",
)


def test_mvp3_adapter_event_harness_spec_names_slice2_contract() -> None:
    content = SPEC_PATH.read_text(encoding="utf-8")

    assert "MVP3-ADAPTER-EVENT-HARNESS-001" in content
    assert "AdapterCallbackAppendBoundary" in content
    for event_name in EXPECTED_ADAPTER_EVENT_NAMES:
        assert event_name in content
    for output_mode in ("real", "fallback", "degraded"):
        assert output_mode in content
    assert "No live provider request" in content


def test_fake_real_harness_emits_canonical_events_through_callback_boundary_without_network_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    startup = _start_mvp3_event_harness_session()
    boundary = AdapterCallbackAppendBoundary(startup.journal)
    snapshot_event_id = str(startup.journal.events()[1]["event_id"])
    network_calls: list[object] = []

    def fail_if_network_probe_is_attempted(*args: object, **kwargs: object) -> None:
        network_calls.append((args, kwargs))
        raise AssertionError("fake-real adapter harness must not probe provider endpoints")

    monkeypatch.setattr(socket, "create_connection", fail_if_network_probe_is_attempted)
    monkeypatch.setattr(urllib.request, "urlopen", fail_if_network_probe_is_attempted)

    real_asr = FakeRealAdapterEventHarness(
        boundary=boundary,
        adapter_id="mvp3_asr",
        adapter_type="asr",
        output_mode="real",
    )
    fallback_slow_llm = FakeRealAdapterEventHarness(
        boundary=boundary,
        adapter_id="mvp3_slow_llm_fallback",
        adapter_type="slow_llm",
        output_mode="fallback",
    )
    degraded_tts = FakeRealAdapterEventHarness(
        boundary=boundary,
        adapter_id="mvp3_tts_degraded",
        adapter_type="tts",
        output_mode="degraded",
    )

    health_failed = real_asr.emit_healthcheck_failed(
        event_id="evt_mvp3_slice2_healthcheck_failed",
        caused_by_event_id=snapshot_event_id,
        created_monotonic_ms=200,
        created_wall_clock_ms=1700000000200,
        failure_reason="synthetic_healthcheck_failure",
    )
    retrying = real_asr.emit_request_retrying(
        event_id="evt_mvp3_slice2_request_retrying",
        caused_by_event_id=str(health_failed["event_id"]),
        created_monotonic_ms=201,
        created_wall_clock_ms=1700000000201,
        adapter_request_id="adapter_request_mvp3_asr_001",
        retry_count=1,
        retry_reason="synthetic_retryable_timeout",
        timeout_ms=500,
    )
    failed = real_asr.emit_request_failed(
        event_id="evt_mvp3_slice2_request_failed",
        caused_by_event_id=str(retrying["event_id"]),
        created_monotonic_ms=202,
        created_wall_clock_ms=1700000000202,
        adapter_request_id="adapter_request_mvp3_asr_001",
        failure_reason="synthetic_final_failure",
        retryable=False,
        timeout_ms=500,
    )
    validation_failed = fallback_slow_llm.emit_output_validation_failed(
        event_id="evt_mvp3_slice2_output_validation_failed",
        caused_by_event_id=str(failed["event_id"]),
        created_monotonic_ms=203,
        created_wall_clock_ms=1700000000203,
        adapter_request_id="adapter_request_mvp3_slow_llm_fallback_001",
        schema_name="SlowTaskPlan",
        failure_reasons=("missing_required_field",),
    )
    degraded = degraded_tts.emit_output_degraded(
        event_id="evt_mvp3_slice2_output_degraded",
        caused_by_event_id=str(validation_failed["event_id"]),
        created_monotonic_ms=204,
        created_wall_clock_ms=1700000000204,
        adapter_request_id="adapter_request_mvp3_tts_degraded_001",
        degraded_reason="missing_tts_truncate",
        missing_capability="supports_tts_truncate",
        fallback_adapter_id="mvp3_tts_fallback",
    )

    emitted_events = (health_failed, retrying, failed, validation_failed, degraded)
    adapter_events = [
        event for event in startup.journal.events() if event["event_name"] in EXPECTED_ADAPTER_EVENT_NAMES
    ]

    assert ADAPTER_EVENT_HARNESS_EVENT_NAMES == frozenset(EXPECTED_ADAPTER_EVENT_NAMES)
    assert tuple(event["event_name"] for event in emitted_events) == EXPECTED_ADAPTER_EVENT_NAMES
    assert adapter_events == list(emitted_events)
    assert [event["event_seq"] for event in adapter_events] == [3, 4, 5, 6, 7]
    assert [event["adapter_callback_seq"] for event in adapter_events] == [1, 2, 3, 4, 5]
    assert {event["output_mode"] for event in emitted_events} == {"real", "fallback", "degraded"}
    assert all(validate_event_envelope(event) == event for event in emitted_events)
    assert network_calls == []


def test_fake_real_harness_redacts_secret_like_adapter_metadata_before_trace_exposure() -> None:
    startup = _start_mvp3_event_harness_session(session_id="sess_mvp3_slice2_redaction_synthetic")
    boundary = AdapterCallbackAppendBoundary(startup.journal)
    snapshot_event_id = str(startup.journal.events()[1]["event_id"])
    harness = FakeRealAdapterEventHarness(
        boundary=boundary,
        adapter_id="mvp3_asr",
        adapter_type="asr",
        output_mode="real",
    )

    failed = harness.emit_request_failed(
        event_id="evt_mvp3_slice2_redacted_request_failed",
        caused_by_event_id=snapshot_event_id,
        created_monotonic_ms=200,
        created_wall_clock_ms=1700000000200,
        adapter_request_id="adapter_request_mvp3_redacted_001",
        failure_reason="synthetic_final_failure",
        retryable=False,
        adapter_metadata={"authorization_header": "Bearer synthetic-token"},
    )

    events = startup.journal.events()

    assert failed["adapter_metadata"]["authorization_header"] == REDACTED_SECRET_VALUE
    assert failed["redaction_metadata"] == {
        "redacted_fields": ["adapter_metadata.authorization_header"],
        "redaction_reason": "secret-like payload field",
    }
    assert [event["event_name"] for event in events] == [
        "SESSION_STARTED",
        "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
        "ADAPTER_REQUEST_FAILED",
        "TRACE_SECRET_REDACTION_APPLIED",
    ]
    assert events[-1]["caused_by_event_id"] == failed["event_id"]
    assert "Bearer synthetic-token" not in repr(events)


def test_fake_real_harness_blocks_unredactable_secret_like_adapter_metadata() -> None:
    startup = _start_mvp3_event_harness_session(session_id="sess_mvp3_slice2_block_synthetic")
    boundary = AdapterCallbackAppendBoundary(startup.journal)
    snapshot_event_id = str(startup.journal.events()[1]["event_id"])
    harness = FakeRealAdapterEventHarness(
        boundary=boundary,
        adapter_id="mvp3_asr",
        adapter_type="asr",
        output_mode="real",
    )

    with pytest.raises(PayloadBlockedError):
        harness.emit_request_failed(
            event_id="evt_mvp3_slice2_blocked_request_failed",
            caused_by_event_id=snapshot_event_id,
            created_monotonic_ms=200,
            created_wall_clock_ms=1700000000200,
            adapter_request_id="adapter_request_mvp3_blocked_001",
            failure_reason="synthetic_final_failure",
            retryable=False,
            adapter_metadata={"provider_debug_note": "Bearer synthetic-token"},
        )

    events = startup.journal.events()

    assert [event["event_name"] for event in events] == [
        "SESSION_STARTED",
        "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
        "TRACE_WRITE_BLOCKED_SECRET_DETECTED",
    ]
    assert events[-1]["caused_by_event_id"] == snapshot_event_id
    assert "Bearer synthetic-token" not in repr(events)
    assert "ADAPTER_REQUEST_FAILED" not in [event["event_name"] for event in events]


def _start_mvp3_event_harness_session(
    *,
    session_id: str = "sess_mvp3_slice2_event_harness_synthetic",
) -> object:
    capabilities = (
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
    return start_configured_session(
        session_id=session_id,
        conversation_id="conv_mvp3_slice2_event_harness_synthetic",
        runtime_config_ref="config://synthetic/mvp3/slice2-event-harness",
        created_monotonic_ms=100,
        created_wall_clock_ms=1700000000100,
        assembly_config=RuntimeAdapterAssemblyConfig(
            stage="mvp3",
            capability_snapshot_ref="capability://synthetic/mvp3/slice2-event-harness",
            capability_version="mvp3.contract.v1",
        ),
        capabilities=capabilities,
    )
