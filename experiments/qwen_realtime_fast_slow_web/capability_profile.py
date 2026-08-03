"""Secret-free capability declarations for the Fast/Slow integration spike.

The profile is experiment-local metadata.  It does not register adapters or
extend the ADR-002 canonical event registry.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Literal


OutputMode = Literal["real", "mock", "fallback", "degraded", "not_executed"]
VerificationStatus = Literal[
    "protocol_declared",
    "implementation_supported",
    "provider_free_verified",
    "real_live_verified",
    "unsupported_or_unverified",
    "degraded",
    "not_executed",
    "not_applicable",
]
HealthStatus = Literal[
    "ready",
    "not_executed",
    "degraded",
    "disconnected",
    "unavailable",
    "closed",
]


@dataclass(frozen=True, slots=True)
class CapabilityProfile:
    adapter_id: str
    provider: str
    deployment_mode: str
    output_mode: OutputMode
    health_status: HealthStatus
    capability_version: str

    duplex_projection: OutputMode
    asr_projection: OutputMode
    fast_interaction_projection: OutputMode

    supports_streaming_input: bool
    supports_streaming_output: bool
    supports_response_cancel: bool
    supports_candidate_quarantine: bool
    supports_playback_epoch: bool
    supports_local_playback_clear: bool
    supports_provider_item_delete: bool
    supports_context_rebuild: bool
    supports_direct_provider_audio_before_gate: bool
    supports_playback_reference_aec: bool
    supports_real_provider: bool

    input_audio_format: str
    output_audio_format: str
    tools_enabled: bool
    persistence_enabled: bool

    # Slice 2 shadow-routing distinctions.  Defaults preserve the Slice 1
    # factory/API while ensuring an omitted value never implies real support.
    routing_mode: str = "enforced"
    shadow_control_mode: str = "none"
    supports_text_only_output: bool = False
    supports_function_calling: bool = False
    forced_route_function_call: str = "unsupported_or_unverified"
    function_call_schema_validation: str = "not_applicable"
    route_proposal_authority: str = "none"
    context_cleanup_policy: str = "none"

    # Slice 3A topology and output-control declarations.  Defaults are
    # deliberately conservative so older Slice 1/2 callers do not inherit a
    # capability merely by omitting a new field.
    control_topology: str = "not_applicable"
    audio_output_mode: str = "provider_pcm"
    slow_runtime: str = "none"
    provider_native_audio_authorized: bool = False
    supports_auto_response_suppression: bool = False
    auto_response_suppression_mode: str = "unsupported_or_unverified"
    supports_cancel_terminal_correlation: bool = False
    supports_voice_output_quarantine: bool = False
    provider_item_correlation: str = "unsupported_or_unverified"
    cancel_terminal_semantics: str = "unsupported_or_unverified"

    # Support, qualification, and per-connection health are intentionally
    # separate.  A documented protocol or provider-free implementation test
    # must never be presented as a completed real-provider live check.
    protocol_declared: bool = False
    implementation_supported: bool = False
    provider_free_verified: bool = False
    real_live_verified: bool = False
    verification_status: VerificationStatus = "not_executed"
    asr_item_correlation_verification: VerificationStatus = (
        "unsupported_or_unverified"
    )
    response_cancel_verification: VerificationStatus = (
        "unsupported_or_unverified"
    )
    cancel_terminal_verification: VerificationStatus = (
        "unsupported_or_unverified"
    )
    provider_item_delete_verification: VerificationStatus = (
        "unsupported_or_unverified"
    )
    context_rebuild_verification: VerificationStatus = (
        "unsupported_or_unverified"
    )

    def to_metadata(self) -> dict[str, Any]:
        return asdict(self)

    def with_health(self, health_status: HealthStatus) -> "CapabilityProfile":
        if not self.supports_real_provider:
            return replace(self, health_status=health_status)
        output_mode = _remote_output_mode(health_status)
        updates: dict[str, Any] = {
            "health_status": health_status,
            "output_mode": output_mode,
            "verification_status": _remote_verification_status(
                health_status, real_live_verified=self.real_live_verified
            ),
        }
        for projection in (
            "duplex_projection",
            "asr_projection",
            "fast_interaction_projection",
        ):
            if getattr(self, projection) == self.output_mode:
                updates[projection] = output_mode
        return replace(self, **updates)


def fake_capability_profile() -> CapabilityProfile:
    """Return the only provider profile authorized in Slice 1."""

    return CapabilityProfile(
        adapter_id="qwen_realtime_fast_slow.fake.v1",
        provider="local_synthetic_fake",
        deployment_mode="mock",
        output_mode="mock",
        health_status="ready",
        capability_version="qwen-realtime-fast-slow-spike.v2",
        duplex_projection="mock",
        asr_projection="mock",
        fast_interaction_projection="mock",
        supports_streaming_input=True,
        supports_streaming_output=True,
        supports_response_cancel=True,
        supports_candidate_quarantine=True,
        supports_playback_epoch=True,
        supports_local_playback_clear=True,
        supports_provider_item_delete=True,
        # The fake can delete in-memory candidates.  It deliberately marks
        # provider context rebuild unavailable so Slice 2 cannot inherit an
        # unverified real-provider claim.
        supports_context_rebuild=False,
        supports_direct_provider_audio_before_gate=False,
        supports_playback_reference_aec=False,
        supports_real_provider=False,
        input_audio_format="pcm16le/16000/mono",
        output_audio_format="pcm16le/24000/mono",
        tools_enabled=False,
        persistence_enabled=False,
        routing_mode="enforced",
        shadow_control_mode="none",
        supports_text_only_output=False,
        supports_function_calling=False,
        forced_route_function_call="unsupported_or_unverified",
        function_call_schema_validation="not_applicable",
        route_proposal_authority="synthetic_evidence_only",
        context_cleanup_policy="in_memory_delete",
        control_topology="fake_enforced",
        audio_output_mode="synthetic_pcm",
        protocol_declared=True,
        implementation_supported=True,
        provider_free_verified=True,
        verification_status="provider_free_verified",
        asr_item_correlation_verification="provider_free_verified",
        response_cancel_verification="provider_free_verified",
        cancel_terminal_verification="provider_free_verified",
        provider_item_delete_verification="provider_free_verified",
        context_rebuild_verification="not_applicable",
    )


def qwen_voice_capability_profile(
    *,
    health_status: HealthStatus = "not_executed",
    enforced_output_suppression: bool = False,
    real_live_verified: bool = False,
) -> CapabilityProfile:
    """Real Qwen voice-session projection used beside shadow control.

    This profile describes transport capability, not authorization for a Qwen
    routing proposal to control Router, Gate, SlowTask, UserPatch, or playback.
    """

    output_mode = _remote_output_mode(health_status)
    verification_status = _remote_verification_status(
        health_status, real_live_verified=real_live_verified
    )
    if enforced_output_suppression:
        return CapabilityProfile(
            adapter_id="qwen_realtime_fast_slow.qwen_voice_ingress.v1",
            provider="aliyun_bailian",
            deployment_mode="remote_api",
            output_mode=output_mode,
            health_status=health_status,
            capability_version="qwen-realtime-fast-slow-spike.slice3a.v1",
            duplex_projection=output_mode,
            asr_projection=output_mode,
            fast_interaction_projection="degraded",
            supports_streaming_input=True,
            # Provider output may arrive on the wire but is quarantined and is
            # never an application streaming-output capability.
            supports_streaming_output=False,
            supports_response_cancel=True,
            supports_candidate_quarantine=True,
            supports_playback_epoch=True,
            supports_local_playback_clear=True,
            supports_provider_item_delete=True,
            supports_context_rebuild=True,
            supports_direct_provider_audio_before_gate=False,
            supports_playback_reference_aec=False,
            supports_real_provider=True,
            input_audio_format="pcm16le/16000/mono",
            output_audio_format="none",
            tools_enabled=False,
            persistence_enabled=False,
            routing_mode="enforced",
            shadow_control_mode="dual_session_enforced_control",
            supports_text_only_output=False,
            supports_function_calling=False,
            forced_route_function_call="unsupported_or_unverified",
            function_call_schema_validation="not_applicable",
            route_proposal_authority="none",
            context_cleanup_policy="cancel_terminal_delete_confirm_or_rebuild",
            control_topology="dual_session_enforced_control",
            audio_output_mode="none",
            slow_runtime="mock",
            provider_native_audio_authorized=False,
            # The official session contract still has no verified switch that
            # retains smart-turn ASR while preventing response creation.
            supports_auto_response_suppression=False,
            auto_response_suppression_mode=(
                "bounded_quarantine_cancel_terminal_delete_or_rebuild"
            ),
            supports_cancel_terminal_correlation=True,
            supports_voice_output_quarantine=True,
            provider_item_correlation="runtime_required_fail_closed",
            cancel_terminal_semantics="cancelled_status_only_delete_or_rebuild",
            protocol_declared=True,
            implementation_supported=True,
            provider_free_verified=True,
            real_live_verified=real_live_verified,
            verification_status=verification_status,
            asr_item_correlation_verification=(
                "real_live_verified"
                if real_live_verified
                else "provider_free_verified"
            ),
            response_cancel_verification=(
                "real_live_verified"
                if real_live_verified
                else "provider_free_verified"
            ),
            cancel_terminal_verification=(
                "real_live_verified"
                if real_live_verified
                else "provider_free_verified"
            ),
            provider_item_delete_verification=(
                "real_live_verified"
                if real_live_verified
                else "provider_free_verified"
            ),
            context_rebuild_verification=(
                "real_live_verified"
                if real_live_verified
                else "provider_free_verified"
            ),
        )

    return CapabilityProfile(
        adapter_id="qwen_realtime_fast_slow.qwen_voice.v1",
        provider="aliyun_bailian",
        deployment_mode="remote_api",
        output_mode=output_mode,
        health_status=health_status,
        capability_version="qwen-realtime-fast-slow-spike.slice2.v1",
        duplex_projection=output_mode,
        asr_projection=output_mode,
        # The separate control connection is the only routing source in this
        # slice and remains non-authoritative.
        fast_interaction_projection="degraded",
        supports_streaming_input=True,
        supports_streaming_output=True,
        supports_response_cancel=True,
        supports_candidate_quarantine=False,
        supports_playback_epoch=True,
        supports_local_playback_clear=True,
        supports_provider_item_delete=False,
        # A failed voice connection requires a fresh browser/coordinator
        # session; only the independent shadow-control connection rebuilds.
        supports_context_rebuild=False,
        supports_direct_provider_audio_before_gate=False,
        supports_playback_reference_aec=False,
        supports_real_provider=True,
        input_audio_format="pcm16le/16000/mono",
        output_audio_format="pcm16le/24000/mono",
        tools_enabled=False,
        persistence_enabled=False,
        routing_mode="shadow",
        shadow_control_mode="dual_session_shadow",
        supports_text_only_output=False,
        supports_function_calling=False,
        forced_route_function_call="unsupported_or_unverified",
        function_call_schema_validation="not_applicable",
        route_proposal_authority="none",
        context_cleanup_policy="fresh_browser_session_no_audio_replay",
        control_topology="dual_session_shadow",
        audio_output_mode="provider_pcm",
        protocol_declared=True,
        implementation_supported=True,
        provider_free_verified=True,
        real_live_verified=real_live_verified,
        verification_status=verification_status,
        asr_item_correlation_verification=(
            "real_live_verified" if real_live_verified else "not_executed"
        ),
        response_cancel_verification=(
            "real_live_verified"
            if real_live_verified
            else "not_executed"
        ),
        cancel_terminal_verification=(
            "real_live_verified" if real_live_verified else "not_executed"
        ),
        provider_item_delete_verification="not_applicable",
        context_rebuild_verification="not_applicable",
    )


def qwen_shadow_capability_profile(
    *,
    health_status: HealthStatus = "not_executed",
    real_live_verified: bool = False,
) -> CapabilityProfile:
    """Real, text-only and non-authoritative Qwen shadow-control profile."""

    output_mode = _remote_output_mode(health_status)
    verification_status = _remote_verification_status(
        health_status, real_live_verified=real_live_verified
    )
    return CapabilityProfile(
        adapter_id="qwen_realtime_fast_slow.qwen_shadow_control.v1",
        provider="aliyun_bailian",
        deployment_mode="remote_api",
        output_mode=output_mode,
        health_status=health_status,
        capability_version="qwen-realtime-fast-slow-spike.slice2.v1",
        duplex_projection="degraded",
        asr_projection="degraded",
        fast_interaction_projection=output_mode,
        supports_streaming_input=False,
        supports_streaming_output=True,
        supports_response_cancel=True,
        supports_candidate_quarantine=False,
        supports_playback_epoch=False,
        supports_local_playback_clear=False,
        supports_provider_item_delete=True,
        supports_context_rebuild=True,
        supports_direct_provider_audio_before_gate=False,
        supports_playback_reference_aec=False,
        supports_real_provider=True,
        input_audio_format="text/redacted-transcript",
        output_audio_format="none",
        tools_enabled=True,
        persistence_enabled=False,
        routing_mode="shadow",
        shadow_control_mode="dual_session_shadow",
        supports_text_only_output=True,
        supports_function_calling=True,
        # The 2026-07-22 official pages document tools but no tool_choice or
        # other protocol-level forced-call control.  Prompt compliance is not
        # elevated into a capability claim.
        forced_route_function_call="unsupported_or_unverified",
        function_call_schema_validation="strict_local_fail_closed",
        route_proposal_authority="non_authoritative_provider_proposal",
        context_cleanup_policy="delete_confirm_or_taint_and_rebuild",
        control_topology="dual_session_shadow",
        audio_output_mode="provider_pcm",
        supports_cancel_terminal_correlation=True,
        provider_item_correlation="strict_runtime_binding",
        cancel_terminal_semantics="matching_response_done_required",
        protocol_declared=True,
        implementation_supported=True,
        provider_free_verified=True,
        real_live_verified=real_live_verified,
        verification_status=verification_status,
        response_cancel_verification=(
            "real_live_verified"
            if real_live_verified
            else "provider_free_verified"
        ),
        cancel_terminal_verification=(
            "real_live_verified"
            if real_live_verified
            else "provider_free_verified"
        ),
        provider_item_delete_verification=(
            "real_live_verified"
            if real_live_verified
            else "provider_free_verified"
        ),
        context_rebuild_verification=(
            "real_live_verified"
            if real_live_verified
            else "provider_free_verified"
        ),
    )


def qwen_enforced_control_capability_profile(
    *,
    health_status: HealthStatus = "not_executed",
    real_live_verified: bool = False,
) -> CapabilityProfile:
    """Text-only Qwen evidence session for Slice 3A enforced routing.

    This is not a Router capability claim.  The Function Call remains
    non-authoritative evidence and provider-native PCM remains prohibited.
    """

    shadow = qwen_shadow_capability_profile(
        health_status=health_status,
        real_live_verified=real_live_verified,
    )
    return replace(
        shadow,
        adapter_id="qwen_realtime_fast_slow.qwen_enforced_control.v1",
        capability_version="qwen-realtime-fast-slow-spike.slice3a.v1",
        routing_mode="enforced",
        shadow_control_mode="dual_session_enforced_control",
        supports_candidate_quarantine=True,
        route_proposal_authority="non_authoritative_provider_evidence",
        control_topology="dual_session_enforced_control",
        audio_output_mode="none",
        slow_runtime="mock",
        provider_native_audio_authorized=False,
    )


def fake_shadow_capability_profile() -> CapabilityProfile:
    """Deterministic provider-free shadow-control profile for automation."""

    return CapabilityProfile(
        adapter_id="qwen_realtime_fast_slow.fake_shadow_control.v1",
        provider="local_synthetic_fake",
        deployment_mode="mock",
        output_mode="mock",
        health_status="ready",
        capability_version="qwen-realtime-fast-slow-spike.slice2.v1",
        duplex_projection="degraded",
        asr_projection="degraded",
        fast_interaction_projection="mock",
        supports_streaming_input=False,
        supports_streaming_output=True,
        supports_response_cancel=True,
        supports_candidate_quarantine=False,
        supports_playback_epoch=False,
        supports_local_playback_clear=False,
        supports_provider_item_delete=True,
        supports_context_rebuild=True,
        supports_direct_provider_audio_before_gate=False,
        supports_playback_reference_aec=False,
        supports_real_provider=False,
        input_audio_format="text/synthetic-redacted",
        output_audio_format="none",
        tools_enabled=True,
        persistence_enabled=False,
        routing_mode="shadow",
        shadow_control_mode="dual_session_shadow",
        supports_text_only_output=True,
        supports_function_calling=True,
        forced_route_function_call="unsupported_or_unverified",
        function_call_schema_validation="strict_local_fail_closed",
        route_proposal_authority="synthetic_non_authoritative_proposal",
        context_cleanup_policy="in_memory_delete_or_rebuild",
        control_topology="dual_session_shadow",
        audio_output_mode="none",
        supports_cancel_terminal_correlation=True,
        provider_item_correlation="synthetic_strict_binding",
        cancel_terminal_semantics="synthetic_matching_response_done",
        protocol_declared=True,
        implementation_supported=True,
        provider_free_verified=True,
        verification_status="provider_free_verified",
        response_cancel_verification="provider_free_verified",
        cancel_terminal_verification="provider_free_verified",
        provider_item_delete_verification="provider_free_verified",
        context_rebuild_verification="provider_free_verified",
    )


def _remote_output_mode(health_status: HealthStatus) -> OutputMode:
    if health_status == "ready":
        return "real"
    if health_status == "not_executed":
        return "not_executed"
    return "degraded"


def _remote_verification_status(
    health_status: HealthStatus, *, real_live_verified: bool
) -> VerificationStatus:
    if health_status in {"degraded", "disconnected", "unavailable", "closed"}:
        return "degraded"
    if real_live_verified:
        return "real_live_verified"
    return "not_executed"


__all__ = [
    "CapabilityProfile",
    "HealthStatus",
    "OutputMode",
    "VerificationStatus",
    "fake_capability_profile",
    "fake_shadow_capability_profile",
    "qwen_enforced_control_capability_profile",
    "qwen_shadow_capability_profile",
    "qwen_voice_capability_profile",
]
