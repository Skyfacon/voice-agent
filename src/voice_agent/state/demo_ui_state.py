from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping
from urllib.parse import unquote, urlparse


class DemoUIStateError(ValueError):
    pass


@dataclass(frozen=True)
class DemoUIPatchRecord:
    event_id: str
    tool_call_id: str
    task_id: str
    plan_version: int
    task_event_seq: int
    ui_patch_id: str
    idempotency_key: str
    patch_ref: str
    state_namespace: str
    patch_operation: str


@dataclass
class DemoUINamespaceState:
    state_namespace: str
    applied_patch_ids: tuple[str, ...] = ()
    operation_counts: dict[str, int] = field(default_factory=dict)
    last_patch_id: str | None = None


@dataclass
class DemoUIState:
    patches_by_id: dict[str, DemoUIPatchRecord] = field(default_factory=dict)
    namespaces: dict[str, DemoUINamespaceState] = field(default_factory=dict)
    last_patch_event_id: str | None = None

    def reduce_event(self, event: Mapping[str, Any]) -> bool:
        if event["event_name"] != "TOOL_UI_STATE_PATCHED":
            return False

        patch_ref = str(event["patch_ref"])
        state_namespace, patch_operation = _parse_patch_ref(patch_ref)
        record = DemoUIPatchRecord(
            event_id=str(event["event_id"]),
            tool_call_id=str(event["tool_call_id"]),
            task_id=str(event["task_id"]),
            plan_version=_int_field(event, "plan_version"),
            task_event_seq=_int_field(event, "task_event_seq"),
            ui_patch_id=str(event["ui_patch_id"]),
            idempotency_key=str(event["idempotency_key"]),
            patch_ref=patch_ref,
            state_namespace=state_namespace,
            patch_operation=patch_operation,
        )
        existing = self.patches_by_id.get(record.ui_patch_id)
        if existing is not None:
            if existing != record:
                raise DemoUIStateError(
                    "ui_patch_id cannot be reused for different patch metadata or task binding"
                )
            self.last_patch_event_id = record.event_id
            return True

        self.patches_by_id[record.ui_patch_id] = record
        namespace = self.namespaces.get(record.state_namespace)
        if namespace is None:
            namespace = DemoUINamespaceState(state_namespace=record.state_namespace)
            self.namespaces[record.state_namespace] = namespace
        namespace.applied_patch_ids = (*namespace.applied_patch_ids, record.ui_patch_id)
        namespace.operation_counts[record.patch_operation] = (
            namespace.operation_counts.get(record.patch_operation, 0) + 1
        )
        namespace.last_patch_id = record.ui_patch_id
        self.last_patch_event_id = record.event_id
        return True

    def to_digest_dict(self) -> dict[str, Any]:
        return {
            "patches_by_id": {
                patch_id: asdict(self.patches_by_id[patch_id])
                for patch_id in sorted(self.patches_by_id)
            },
            "namespaces": {
                state_namespace: asdict(self.namespaces[state_namespace])
                for state_namespace in sorted(self.namespaces)
            },
            "last_patch_event_id": self.last_patch_event_id,
        }


def _parse_patch_ref(patch_ref: str) -> tuple[str, str]:
    parsed = urlparse(patch_ref)
    path_parts = tuple(unquote(part) for part in parsed.path.split("/") if part)
    if parsed.scheme == "patch" and parsed.netloc == "synthetic" and len(path_parts) >= 4:
        if path_parts[0] == "demo_backend":
            return path_parts[1], path_parts[2]
    if parsed.scheme == "patch" and parsed.netloc == "synthetic" and len(path_parts) >= 2:
        return path_parts[-2], path_parts[-1]
    raise DemoUIStateError("patch_ref must be a structured patch://synthetic ref")


def _int_field(event: Mapping[str, Any], field: str) -> int:
    value = event[field]
    if not isinstance(value, int) or isinstance(value, bool):
        raise DemoUIStateError(f"{field} must be an integer")
    return value
