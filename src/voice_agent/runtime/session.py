from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from voice_agent.adapters.capabilities import AdapterCapability
from voice_agent.adapters.mock_adapters import (
    mvp0_capability_snapshot,
    mvp0_mock_adapter_capabilities,
)
from voice_agent.events.journal import InMemoryEventJournal


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
    capability_snapshot = mvp0_capability_snapshot(capabilities)
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
        capabilities=capabilities,
        capability_snapshot=capability_snapshot,
    )
