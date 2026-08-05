from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ADR_018 = ROOT / (
    "docs/adr/ADR-018 Single-session Qwen Realtime Parallel Route Evidence "
    "and Slow-to-Fast Context Projection.md"
)
ADR_002 = ROOT / "docs/adr/ADR-002 Event Journal, Timing Model, and Replay Foundation.md"
ADR_011 = ROOT / "docs/adr/ADR-011 Model Adapter Capability Contract.md"
ADR_012 = ROOT / "docs/adr/ADR-012 MVP Vertical Slice and Development SLOs.md"
REGISTER = ROOT / "stage_b_adr_register.md"
AGENTS = ROOT / "AGENTS.md"
EVENT_SPEC = ROOT / "docs/specs/event-registry.md"
CAPABILITY_SPEC = ROOT / "docs/specs/model-adapter-capabilities.md"

NEW_EVENTS = {
    "ROUTE_EVIDENCE_OUTPUT_EMITTED",
    "CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED",
    "MODEL_CONTEXT_PROJECTION_EMITTED",
    "SLOW_TO_FAST_HANDOFF_EMITTED",
    "SLOW_TO_FAST_HANDOFF_DISPOSITIONED",
    "RESPONSE_ARBITRATION_DECIDED",
    "PROVIDER_CONTEXT_STATE_CHANGED",
    "CANDIDATE_AUDIO_SHADOW_VERIFICATION_EMITTED",
    "ASSISTANT_DELIVERY_DISPOSITIONED",
}

CAPABILITY_TERMS = {
    "route_evidence",
    "supports_route_schema",
    "supports_task_focus",
    "supports_foreground_act_hint",
    "supports_ack_kind",
    "supports_candidate_safety_schema",
    "supports_prohibited_claim_detection",
    "supports_candidate_output_audio_shadow_verification",
    "supports_provider_context_readiness",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_adr018_is_accepted_and_registered_only_as_post_adr017_mvp6x() -> None:
    adr = _read(ADR_018)
    register = _read(REGISTER)
    vertical_slice = _read(ADR_012)

    assert "## Status\n\naccepted" in adr
    assert "| ADR-018 |" in register
    assert "Post-ADR-017 / MVP6.x" in adr
    assert "Post-ADR-017 / MVP6.x" in vertical_slice
    assert "Slice 3A.2.1 remains" in adr


def test_canonical_events_are_synchronized_across_adr_and_derived_spec() -> None:
    adr = _read(ADR_018)
    registry_adr = _read(ADR_002)
    derived = _read(EVENT_SPEC)

    for event_name in NEW_EVENTS:
        assert event_name in adr
        assert event_name in registry_adr
        assert event_name in derived


def test_capability_terms_are_synchronized() -> None:
    adr = _read(ADR_018)
    capability_adr = _read(ADR_011)
    derived = _read(CAPABILITY_SPEC)

    for term in CAPABILITY_TERMS:
        assert term in adr
        assert term in capability_adr
        assert term in derived


def test_online_pcm_policy_is_low_latency_and_fail_closed() -> None:
    sources = "\n".join((_read(ADR_018), _read(AGENTS)))

    assert "no per-turn independent PCM back-transcription" in sources
    assert "candidate_transcript_digest" in sources
    assert "candidate_pcm_manifest_digest" in sources
    assert "non-blocking live PCM shadow verification" in sources
    assert "shadow mismatch disables native PCM" in sources
    assert "Local Router" in sources
    assert "Fast Foreground Gate" in sources
