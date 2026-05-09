from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


ADAPTER_HEALTH_EVENT_NAMES = frozenset(
    {
        "SESSION_STARTED",
        "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
        "ADAPTER_HEALTHCHECK_FAILED",
        "ADAPTER_REQUEST_RETRYING",
        "ADAPTER_REQUEST_FAILED",
        "ADAPTER_OUTPUT_VALIDATION_FAILED",
        "ADAPTER_OUTPUT_DEGRADED",
        "MOCK_ASR_FRAME_EMITTED",
        "MOCK_THINKER_FRAME_EMITTED",
    }
)


@dataclass
class AdapterRecord:
    adapter_id: str
    adapter_type: str
    deployment_mode: str
    output_mode: str
    health_status: str | None = None
    retry_count: int = 0
    failure_count: int = 0
    missing_capabilities: tuple[str, ...] = ()
    latest_degradation_reason: str | None = None


@dataclass
class AdapterHealthState:
    capability_snapshot_ref: str | None = None
    capability_version: str | None = None
    adapters: dict[str, AdapterRecord] = field(default_factory=dict)
    output_event_modes: dict[str, str] = field(default_factory=dict)
    last_adapter_event_id: str | None = None

    def reduce_event(self, event: Mapping[str, Any]) -> bool:
        event_name = str(event["event_name"])
        if event_name not in ADAPTER_HEALTH_EVENT_NAMES:
            return False

        if event_name == "SESSION_STARTED":
            self.capability_snapshot_ref = str(event["capability_snapshot_ref"])
        elif event_name == "ADAPTER_CAPABILITY_SNAPSHOT_RECORDED":
            self._record_capability_snapshot(event)
        elif event_name in {"ADAPTER_HEALTHCHECK_FAILED", "ADAPTER_REQUEST_FAILED"}:
            adapter = self._ensure_adapter(event)
            adapter.health_status = _optional_str(event.get("health_status")) or "failed"
            adapter.failure_count += 1
        elif event_name == "ADAPTER_REQUEST_RETRYING":
            self._ensure_adapter(event).retry_count += 1
        elif event_name == "ADAPTER_OUTPUT_VALIDATION_FAILED":
            adapter = self._ensure_adapter(event)
            adapter.failure_count += 1
            adapter.latest_degradation_reason = "output_validation_failed"
        elif event_name == "ADAPTER_OUTPUT_DEGRADED":
            adapter = self._ensure_adapter(event)
            adapter.latest_degradation_reason = str(event["degraded_reason"])
            if event.get("missing_capability"):
                adapter.missing_capabilities = tuple(
                    sorted({*adapter.missing_capabilities, str(event["missing_capability"])})
                )
        elif event_name in {"MOCK_ASR_FRAME_EMITTED", "MOCK_THINKER_FRAME_EMITTED"}:
            self.output_event_modes[str(event["event_id"])] = str(event["output_mode"])

        self.last_adapter_event_id = str(event["event_id"])
        return True

    def to_digest_dict(self) -> dict[str, Any]:
        return {
            "capability_snapshot_ref": self.capability_snapshot_ref,
            "capability_version": self.capability_version,
            "adapters": {
                adapter_id: asdict(self.adapters[adapter_id])
                for adapter_id in sorted(self.adapters)
            },
            "output_event_modes": {
                event_id: self.output_event_modes[event_id]
                for event_id in sorted(self.output_event_modes)
            },
            "last_adapter_event_id": self.last_adapter_event_id,
        }

    def _record_capability_snapshot(self, event: Mapping[str, Any]) -> None:
        adapter_ids = _string_list(event["adapter_ids"])
        adapter_types = _string_list(event["adapter_types"])
        deployment_modes = _string_list(event["deployment_modes"])
        output_modes = _string_list(event["output_modes"])
        lengths = {len(adapter_ids), len(adapter_types), len(deployment_modes), len(output_modes)}
        if len(lengths) != 1:
            raise ValueError("adapter capability snapshot fields must have matching lengths")

        self.capability_snapshot_ref = str(event["capability_snapshot_ref"])
        self.capability_version = _optional_str(event.get("capability_version"))
        self.adapters = {
            adapter_id: AdapterRecord(
                adapter_id=adapter_id,
                adapter_type=adapter_type,
                deployment_mode=deployment_mode,
                output_mode=output_mode,
                health_status="snapshot_recorded",
            )
            for adapter_id, adapter_type, deployment_mode, output_mode in zip(
                adapter_ids,
                adapter_types,
                deployment_modes,
                output_modes,
                strict=True,
            )
        }

    def _ensure_adapter(self, event: Mapping[str, Any]) -> AdapterRecord:
        adapter_id = str(event["adapter_id"])
        if adapter_id not in self.adapters:
            self.adapters[adapter_id] = AdapterRecord(
                adapter_id=adapter_id,
                adapter_type=str(event["adapter_type"]),
                deployment_mode="unknown",
                output_mode=str(event.get("output_mode", "degraded")),
            )
        return self.adapters[adapter_id]


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("capability snapshot fields must be lists")
    return [str(item) for item in value]
