from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


TASK_FOCUS_EVENT_NAMES = frozenset({"ROUTER_DECISION_EMITTED"})


@dataclass
class TaskFocusState:
    active_task_id: str | None = None
    foreground_mode: str = "IDLE"
    side_conversation_allowed: bool = True
    default_patch_policy: str = "NO_ACTIVE_TASK"
    ambiguous_input_policy: str = "CLARIFY"
    last_focus_decision: str | None = None
    last_focus_confidence: float | None = None
    last_focus_event_id: str | None = None

    def reduce_event(self, event: Mapping[str, Any]) -> bool:
        event_name = str(event["event_name"])
        if event_name not in TASK_FOCUS_EVENT_NAMES:
            return False

        router_decision = str(event["router_decision"])
        task_focus = event.get("task_focus")
        if task_focus is None:
            task_focus = "FOREGROUND_CHAT" if router_decision == "FAST_ONLY" else "NON_ASSISTANT"

        self.active_task_id = _optional_str(event.get("active_task_id"))
        self.foreground_mode = "FAST_RESPONSE" if router_decision == "FAST_ONLY" else "IDLE"
        self.side_conversation_allowed = True
        self.default_patch_policy = "NO_ACTIVE_TASK"
        self.ambiguous_input_policy = "CLARIFY"
        self.last_focus_decision = str(task_focus)
        self.last_focus_confidence = _optional_float(event.get("confidence"))
        self.last_focus_event_id = str(event["event_id"])
        return True

    def to_digest_dict(self) -> dict[str, Any]:
        return asdict(self)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)
