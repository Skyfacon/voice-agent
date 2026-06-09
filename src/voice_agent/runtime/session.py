from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from voice_agent.adapters.capabilities import AdapterCapability
from voice_agent.adapters.mock_adapters import (
    MVP0_MOCK_CAPABILITY_SNAPSHOT_REF,
    MVP0_MOCK_CAPABILITY_VERSION,
    mvp0_mock_adapter_capabilities,
)
from voice_agent.events.journal import InMemoryEventJournal
from voice_agent.runtime.assembly import RuntimeAdapterAssemblyConfig, assemble_runtime_adapters


@dataclass(frozen=True)
class SessionStartupResult:
    journal: InMemoryEventJournal
    capabilities: tuple[AdapterCapability, ...]
    capability_snapshot: dict[str, Any]


def start_mvp0_session(
    *,
    session_id: str,
    conversation_id: str,
    runtime_config_ref: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
) -> SessionStartupResult:
    capabilities = mvp0_mock_adapter_capabilities()
    assembly_config = RuntimeAdapterAssemblyConfig(
        stage="mvp0_mock",
        capability_snapshot_ref=MVP0_MOCK_CAPABILITY_SNAPSHOT_REF,
        capability_version=MVP0_MOCK_CAPABILITY_VERSION,
    )
    return start_configured_session(
        session_id=session_id,
        conversation_id=conversation_id,
        runtime_config_ref=runtime_config_ref,
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        assembly_config=assembly_config,
        capabilities=capabilities,
    )


def start_configured_session(
    *,
    session_id: str,
    conversation_id: str,
    runtime_config_ref: str,
    created_monotonic_ms: int,
    created_wall_clock_ms: int,
    assembly_config: RuntimeAdapterAssemblyConfig,
    capabilities: tuple[AdapterCapability, ...],
) -> SessionStartupResult:
    assembly = assemble_runtime_adapters(assembly_config, capabilities)
    capability_snapshot = assembly.capability_snapshot
    journal = InMemoryEventJournal(session_id=session_id, conversation_id=conversation_id)

    session_started = journal.append(
        event_name="SESSION_STARTED",
        event_id=f"evt_{session_id}_session_started",
        source_module="session_runtime",
        created_monotonic_ms=created_monotonic_ms,
        created_wall_clock_ms=created_wall_clock_ms,
        trace_redaction_level="metadata_only",
        runtime_config_ref=runtime_config_ref,
        capability_snapshot_ref=capability_snapshot["capability_snapshot_ref"],
    )
    journal.append(
        event_name="ADAPTER_CAPABILITY_SNAPSHOT_RECORDED",
        event_id=f"evt_{session_id}_capability_snapshot",
        source_module="adapter_registry",
        caused_by_event_id=str(session_started["event_id"]),
        created_monotonic_ms=created_monotonic_ms + 1,
        created_wall_clock_ms=created_wall_clock_ms + 1,
        trace_redaction_level="metadata_only",
        **capability_snapshot,
    )

    return SessionStartupResult(
        journal=journal,
        capabilities=assembly.capabilities,
        capability_snapshot=capability_snapshot,
    )
