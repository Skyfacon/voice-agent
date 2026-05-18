from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ToolExecutionPolicyError(ValueError):
    pass


MVP_ALLOWED_SIDE_EFFECT_CLASSES = (
    "READ_ONLY",
    "DRY_RUN",
    "SANDBOX_WRITE",
    "DEMO_DESTRUCTIVE_ACTION",
)
BLOCKED_SIDE_EFFECT_CLASSES = (
    "EXTERNAL_WRITE",
    "EXTERNAL_COMMUNICATION",
    "BOOKING_OR_PAYMENT",
    "DELETION",
)
KNOWN_SIDE_EFFECT_CLASSES = frozenset(MVP_ALLOWED_SIDE_EFFECT_CLASSES + BLOCKED_SIDE_EFFECT_CLASSES)


@dataclass(frozen=True)
class ToolManifest:
    tool_name: str
    tool_adapter_id: str
    tool_manifest_version: str
    tool_category: str
    side_effect_class: str
    risk_class: str
    required_arguments: tuple[str, ...]
    optional_arguments: tuple[str, ...]
    argument_provenance_requirements: tuple[str, ...]
    result_type: str
    trust_level: str
    source_type: str
    preview_required: bool
    confirmation_required: bool
    ui_patch_capable: bool
    idempotency_required: bool
    sandbox_state_namespace: str
    capability: str
    execution_mode: str = "demo_sandbox"

    def __post_init__(self) -> None:
        for field_name in (
            "tool_name",
            "tool_adapter_id",
            "tool_manifest_version",
            "tool_category",
            "side_effect_class",
            "risk_class",
            "result_type",
            "trust_level",
            "source_type",
            "sandbox_state_namespace",
            "capability",
            "execution_mode",
        ):
            if not str(getattr(self, field_name)):
                raise ToolExecutionPolicyError(f"{field_name} is required")
        if self.side_effect_class not in KNOWN_SIDE_EFFECT_CLASSES:
            raise ToolExecutionPolicyError(f"unknown side_effect_class: {self.side_effect_class}")
        if self.execution_mode != "demo_sandbox":
            raise ToolExecutionPolicyError("MVP-2 tool execution_mode must be demo_sandbox")

    def manifest_event_fields(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "tool_adapter_id": self.tool_adapter_id,
            "tool_manifest_version": self.tool_manifest_version,
            "tool_category": self.tool_category,
            "side_effect_class": self.side_effect_class,
            "risk_class": self.risk_class,
            "result_type": self.result_type,
            "trust_level": self.trust_level,
            "source_type": self.source_type,
            "preview_required": self.preview_required,
            "confirmation_required": self.confirmation_required,
            "ui_patch_capable": self.ui_patch_capable,
            "idempotency_required": self.idempotency_required,
            "sandbox_state_namespace": self.sandbox_state_namespace,
            "capability": self.capability,
            "execution_mode": self.execution_mode,
        }


def require_mvp_side_effect_class(side_effect_class: str) -> None:
    if side_effect_class not in MVP_ALLOWED_SIDE_EFFECT_CLASSES:
        raise ToolExecutionPolicyError(
            f"side_effect_class is not allowed in MVP demo Tool Executor: {side_effect_class}"
        )
