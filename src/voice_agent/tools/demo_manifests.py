from __future__ import annotations

from voice_agent.tools.manifest import ToolManifest


MVP2_DEMO_TOOL_MANIFEST_VERSION = "2026-05-18.slice4"


def memo_create_manifest(
    *,
    side_effect_class: str = "SANDBOX_WRITE",
    ui_patch_capable: bool = True,
) -> ToolManifest:
    return ToolManifest(
        tool_name="memo",
        tool_adapter_id="demo.memo.create",
        tool_manifest_version=MVP2_DEMO_TOOL_MANIFEST_VERSION,
        tool_category="DEMO_STATE_WRITE",
        side_effect_class=side_effect_class,
        risk_class="LOW",
        required_arguments=("body",),
        optional_arguments=(),
        argument_provenance_requirements=("body",),
        result_type="memo_write",
        trust_level="TRUSTED_DEMO_TOOL_RESULT",
        source_type="DEMO_SANDBOX",
        preview_required=False,
        confirmation_required=False,
        ui_patch_capable=ui_patch_capable,
        idempotency_required=True,
        sandbox_state_namespace="memo",
        capability="mock",
    )


def memo_list_manifest() -> ToolManifest:
    return ToolManifest(
        tool_name="memo.list",
        tool_adapter_id="demo.memo.list",
        tool_manifest_version=MVP2_DEMO_TOOL_MANIFEST_VERSION,
        tool_category="READ_ONLY_DEMO",
        side_effect_class="READ_ONLY",
        risk_class="LOW",
        required_arguments=(),
        optional_arguments=(),
        argument_provenance_requirements=(),
        result_type="memo_list",
        trust_level="TRUSTED_DEMO_TOOL_RESULT",
        source_type="DEMO_SANDBOX",
        preview_required=False,
        confirmation_required=False,
        ui_patch_capable=False,
        idempotency_required=True,
        sandbox_state_namespace="memo",
        capability="mock",
    )


def alarm_create_manifest(*, side_effect_class: str = "SANDBOX_WRITE") -> ToolManifest:
    return ToolManifest(
        tool_name="alarm",
        tool_adapter_id="demo.alarm.create",
        tool_manifest_version=MVP2_DEMO_TOOL_MANIFEST_VERSION,
        tool_category="DEMO_SCHEDULE_ACTION",
        side_effect_class=side_effect_class,
        risk_class="LOW",
        required_arguments=("time", "timezone", "label"),
        optional_arguments=(),
        argument_provenance_requirements=("time", "timezone", "label"),
        result_type="alarm_write",
        trust_level="TRUSTED_DEMO_TOOL_RESULT",
        source_type="DEMO_SANDBOX",
        preview_required=True,
        confirmation_required=False,
        ui_patch_capable=True,
        idempotency_required=True,
        sandbox_state_namespace="alarm",
        capability="mock",
    )


def alarm_list_manifest() -> ToolManifest:
    return ToolManifest(
        tool_name="alarm.list",
        tool_adapter_id="demo.alarm.list",
        tool_manifest_version=MVP2_DEMO_TOOL_MANIFEST_VERSION,
        tool_category="READ_ONLY_DEMO",
        side_effect_class="READ_ONLY",
        risk_class="LOW",
        required_arguments=(),
        optional_arguments=(),
        argument_provenance_requirements=(),
        result_type="alarm_list",
        trust_level="TRUSTED_DEMO_TOOL_RESULT",
        source_type="DEMO_SANDBOX",
        preview_required=False,
        confirmation_required=False,
        ui_patch_capable=False,
        idempotency_required=True,
        sandbox_state_namespace="alarm",
        capability="mock",
    )


def flashlight_set_manifest() -> ToolManifest:
    return ToolManifest(
        tool_name="flashlight",
        tool_adapter_id="demo.flashlight.set",
        tool_manifest_version=MVP2_DEMO_TOOL_MANIFEST_VERSION,
        tool_category="DEMO_DEVICE_ACTION",
        side_effect_class="SANDBOX_WRITE",
        risk_class="LOW",
        required_arguments=("state",),
        optional_arguments=(),
        argument_provenance_requirements=("state",),
        result_type="flashlight_state",
        trust_level="TRUSTED_DEMO_TOOL_RESULT",
        source_type="DEMO_SANDBOX",
        preview_required=False,
        confirmation_required=False,
        ui_patch_capable=True,
        idempotency_required=True,
        sandbox_state_namespace="flashlight",
        capability="mock",
    )


def weather_manifest(*, ui_patch_capable: bool = False) -> ToolManifest:
    return ToolManifest(
        tool_name="weather",
        tool_adapter_id="demo.weather",
        tool_manifest_version=MVP2_DEMO_TOOL_MANIFEST_VERSION,
        tool_category="READ_ONLY_EXTERNAL",
        side_effect_class="READ_ONLY",
        risk_class="LOW",
        required_arguments=("location", "date"),
        optional_arguments=(),
        argument_provenance_requirements=("location", "date"),
        result_type="weather_snapshot",
        trust_level="EXTERNAL_READ_PROVIDER_RESULT",
        source_type="READ_ONLY_EXTERNAL",
        preview_required=True,
        confirmation_required=False,
        ui_patch_capable=ui_patch_capable,
        idempotency_required=True,
        sandbox_state_namespace="weather",
        capability="mock",
    )


def web_search_manifest() -> ToolManifest:
    return ToolManifest(
        tool_name="webSearch",
        tool_adapter_id="demo.web_search",
        tool_manifest_version=MVP2_DEMO_TOOL_MANIFEST_VERSION,
        tool_category="EXTERNAL_READ_UNTRUSTED",
        side_effect_class="READ_ONLY",
        risk_class="LOW",
        required_arguments=("query",),
        optional_arguments=(),
        argument_provenance_requirements=("query",),
        result_type="web_search_evidence",
        trust_level="UNTRUSTED_WEB_EVIDENCE",
        source_type="EXTERNAL_READ_UNTRUSTED",
        preview_required=False,
        confirmation_required=False,
        ui_patch_capable=False,
        idempotency_required=True,
        sandbox_state_namespace="webSearch",
        capability="mock",
    )


def mvp2_demo_tool_manifests() -> tuple[ToolManifest, ...]:
    return (
        memo_create_manifest(),
        memo_list_manifest(),
        alarm_create_manifest(),
        alarm_list_manifest(),
        flashlight_set_manifest(),
        weather_manifest(),
        web_search_manifest(),
    )
