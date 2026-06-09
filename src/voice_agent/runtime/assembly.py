from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from voice_agent.adapters.capabilities import AdapterCapability
from voice_agent.adapters.profiles import (
    AdapterProfileValidationError,
    build_capability_snapshot,
    validate_adapter_profile_set,
    validate_mvp3_adapter_profile_set,
)


class RuntimeAdapterAssemblyError(ValueError):
    pass


@dataclass(frozen=True)
class RuntimeAdapterAssemblyConfig:
    stage: str
    capability_snapshot_ref: str
    capability_version: str


@dataclass(frozen=True)
class RuntimeAdapterAssemblyResult:
    capabilities: tuple[AdapterCapability, ...]
    capability_matrices: tuple[dict[str, Any], ...]
    capability_snapshot: dict[str, Any]


def assemble_runtime_adapters(
    config: RuntimeAdapterAssemblyConfig,
    capabilities: Iterable[AdapterCapability],
) -> RuntimeAdapterAssemblyResult:
    capability_tuple = tuple(capabilities)
    try:
        if config.stage == "mvp3":
            matrices = validate_mvp3_adapter_profile_set(capability_tuple)
        elif config.stage == "mvp0_mock":
            matrices = validate_adapter_profile_set(capability_tuple)
        else:
            raise RuntimeAdapterAssemblyError(f"Unsupported runtime adapter assembly stage: {config.stage!r}")
        snapshot = build_capability_snapshot(
            matrices,
            capability_snapshot_ref=config.capability_snapshot_ref,
            capability_version=config.capability_version,
        )
    except AdapterProfileValidationError as exc:
        raise RuntimeAdapterAssemblyError(str(exc)) from exc

    return RuntimeAdapterAssemblyResult(
        capabilities=capability_tuple,
        capability_matrices=matrices,
        capability_snapshot=snapshot,
    )
