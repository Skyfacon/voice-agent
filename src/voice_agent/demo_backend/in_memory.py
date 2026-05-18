from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


class DemoBackendExecutionError(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class DemoBackendResult:
    result_status: str
    result_ref: str
    progress_type: str
    progress_ref: str
    payload: Mapping[str, Any]


class InMemoryDemoBackend:
    """Deterministic MVP-2 demo backend.

    This backend is intentionally tiny. It does not call networks, clocks,
    random sources, external apps, device APIs, or frontend mutation paths.
    """

    def __init__(self) -> None:
        self._executed_calls: list[tuple[str, dict[str, Any]]] = []
        self._next_result_index = 1

    @property
    def executed_calls(self) -> tuple[tuple[str, dict[str, Any]], ...]:
        return tuple((tool_name, dict(arguments)) for tool_name, arguments in self._executed_calls)

    def execute(
        self,
        *,
        tool_name: str,
        tool_adapter_id: str,
        arguments: Mapping[str, Any],
    ) -> DemoBackendResult:
        if tool_adapter_id == "demo.weather":
            return self._execute_weather(tool_name=tool_name, arguments=arguments)
        raise DemoBackendExecutionError("demo_backend_adapter_not_supported")

    def _execute_weather(
        self,
        *,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> DemoBackendResult:
        location = str(arguments["location"])
        date = str(arguments["date"])
        normalized_arguments = {key: arguments[key] for key in sorted(arguments)}
        self._executed_calls.append((tool_name, dict(normalized_arguments)))

        opaque_result_id = f"weather_lookup_{self._next_result_index:06d}"
        self._next_result_index += 1
        return DemoBackendResult(
            result_status="SUCCEEDED",
            result_ref=f"result://synthetic/demo_backend/weather/{opaque_result_id}",
            progress_type="read_only_lookup_completed",
            progress_ref=f"progress://synthetic/demo_backend/weather/{opaque_result_id}/lookup",
            payload={
                "location": location,
                "date": date,
                "condition": "synthetic_clear",
                "temperature_c": 21,
                "source": "in_memory_demo_backend",
            },
        )
