from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any


class DemoBackendExecutionError(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class DemoBackendUIPatchMetadata:
    ui_patch_id: str
    patch_ref: str
    state_namespace: str
    operation: str


@dataclass(frozen=True)
class DemoBackendResult:
    result_status: str
    result_ref: str
    progress_type: str
    progress_ref: str
    payload: Mapping[str, Any]
    ui_patch: DemoBackendUIPatchMetadata | None = None


class InMemoryDemoBackend:
    """Deterministic MVP-2 demo backend.

    This backend is intentionally tiny. It does not call networks, clocks,
    random sources, external apps, device APIs, or frontend mutation paths.
    """

    def __init__(self) -> None:
        self._executed_calls: list[tuple[str, dict[str, Any]]] = []
        self._next_result_index = 1
        self._next_memo_index = 1
        self._applied_ui_patches: list[dict[str, str]] = []

    @property
    def executed_calls(self) -> tuple[tuple[str, dict[str, Any]], ...]:
        return tuple((tool_name, dict(arguments)) for tool_name, arguments in self._executed_calls)

    def execute(
        self,
        *,
        tool_name: str,
        tool_adapter_id: str,
        arguments: Mapping[str, Any],
        idempotency_key: str | None = None,
        expected_state_namespace: str | None = None,
    ) -> DemoBackendResult:
        if tool_adapter_id == "demo.memo":
            return self._execute_memo_create(
                tool_name=tool_name,
                arguments=arguments,
                idempotency_key=idempotency_key,
                expected_state_namespace=expected_state_namespace,
            )
        if tool_adapter_id == "demo.weather":
            return self._execute_weather(tool_name=tool_name, arguments=arguments)
        raise DemoBackendExecutionError("demo_backend_adapter_not_supported")

    def _execute_memo_create(
        self,
        *,
        tool_name: str,
        arguments: Mapping[str, Any],
        idempotency_key: str | None,
        expected_state_namespace: str | None,
    ) -> DemoBackendResult:
        if idempotency_key in (None, ""):
            raise DemoBackendExecutionError("memo_write_requires_idempotency_key")
        if expected_state_namespace not in (None, "", "memo"):
            raise DemoBackendExecutionError("demo_backend_ui_patch_namespace_mismatch")

        normalized_arguments = {key: arguments[key] for key in sorted(arguments)}
        self._executed_calls.append((tool_name, dict(normalized_arguments)))

        opaque_result_id = f"memo_write_{self._next_memo_index:06d}"
        memo_item_id = f"memo_item_{self._next_memo_index:06d}"
        self._next_memo_index += 1

        ui_patch = _ui_patch_metadata(
            state_namespace="memo",
            operation="create",
            idempotency_key=str(idempotency_key),
        )
        self._applied_ui_patches.append(
            {
                "ui_patch_id": ui_patch.ui_patch_id,
                "patch_ref": ui_patch.patch_ref,
                "state_namespace": ui_patch.state_namespace,
                "operation": ui_patch.operation,
            }
        )
        return DemoBackendResult(
            result_status="SUCCEEDED",
            result_ref=f"result://synthetic/demo_backend/memo/{opaque_result_id}",
            progress_type="sandbox_write_completed",
            progress_ref=f"progress://synthetic/demo_backend/memo/{opaque_result_id}/write",
            payload={
                "state_namespace": "memo",
                "operation": "create",
                "memo_item_id": memo_item_id,
                "source": "in_memory_demo_backend",
            },
            ui_patch=ui_patch,
        )

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


def _ui_patch_metadata(
    *,
    state_namespace: str,
    operation: str,
    idempotency_key: str,
) -> DemoBackendUIPatchMetadata:
    digest = sha256(f"{state_namespace}:{operation}:{idempotency_key}".encode("utf-8")).hexdigest()[:16]
    ui_patch_id = f"ui_patch_{state_namespace}_{operation}_{digest}"
    return DemoBackendUIPatchMetadata(
        ui_patch_id=ui_patch_id,
        patch_ref=f"patch://synthetic/demo_backend/{state_namespace}/{operation}/{ui_patch_id}",
        state_namespace=state_namespace,
        operation=operation,
    )
