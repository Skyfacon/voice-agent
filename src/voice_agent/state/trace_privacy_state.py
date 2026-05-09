from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


TRACE_PRIVACY_EVENT_NAMES = frozenset(
    {
        "SESSION_STARTED",
        "TRACE_WRITE_DEGRADED",
        "TRACE_SECRET_REDACTION_APPLIED",
        "TRACE_WRITE_BLOCKED_SECRET_DETECTED",
        "REPLAY_STARTED",
        "REPLAY_COMPLETED",
    }
)


@dataclass
class TracePrivacyState:
    fixture_domain: str | None = None
    replay_mode: str | None = None
    contains_raw_audio: bool | None = None
    contains_raw_trace: bool | None = None
    contains_real_user_input: bool | None = None
    contains_secrets: bool | None = None
    contains_unredacted_tool_result: bool | None = None
    contains_large_raw_web_content: bool | None = None
    runtime_config_ref: str | None = None
    trace_redaction_levels: dict[str, int] = field(default_factory=dict)
    redaction_count: int = 0
    blocked_write_count: int = 0
    trace_write_degraded_count: int = 0
    latest_degraded_storage_target: str | None = None
    replay_result_status: str | None = None
    replay_state_digest: dict[str, Any] | None = None
    last_trace_event_id: str | None = None

    @classmethod
    def from_manifest(cls, manifest: Mapping[str, Any]) -> TracePrivacyState:
        return cls(
            fixture_domain=str(manifest["fixture_domain"]),
            replay_mode=str(manifest["replay_mode"]),
            contains_raw_audio=bool(manifest["contains_raw_audio"]),
            contains_raw_trace=bool(manifest["contains_raw_trace"]),
            contains_real_user_input=bool(manifest["contains_real_user_input"]),
            contains_secrets=bool(manifest["contains_secrets"]),
            contains_unredacted_tool_result=bool(manifest["contains_unredacted_tool_result"]),
            contains_large_raw_web_content=bool(manifest["contains_large_raw_web_content"]),
        )

    def reduce_event(self, event: Mapping[str, Any]) -> bool:
        redaction_level = event.get("trace_redaction_level")
        if redaction_level is not None:
            key = str(redaction_level)
            self.trace_redaction_levels[key] = self.trace_redaction_levels.get(key, 0) + 1

        event_name = str(event["event_name"])
        if event_name not in TRACE_PRIVACY_EVENT_NAMES:
            return False

        if event_name == "SESSION_STARTED":
            self.runtime_config_ref = str(event["runtime_config_ref"])
        elif event_name == "TRACE_WRITE_DEGRADED":
            self.trace_write_degraded_count += 1
            self.latest_degraded_storage_target = str(event["storage_target"])
        elif event_name == "TRACE_SECRET_REDACTION_APPLIED":
            self.redaction_count += 1
        elif event_name == "TRACE_WRITE_BLOCKED_SECRET_DETECTED":
            self.blocked_write_count += 1
        elif event_name == "REPLAY_STARTED":
            self.replay_mode = str(event["replay_mode"])
        elif event_name == "REPLAY_COMPLETED":
            self.replay_result_status = str(event["result_status"])
            state_digest = event.get("state_digest")
            self.replay_state_digest = dict(state_digest) if isinstance(state_digest, Mapping) else None

        self.last_trace_event_id = str(event["event_id"])
        return True

    def mark_replay_completed(self, *, result_status: str) -> None:
        self.replay_result_status = result_status

    def to_digest_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["trace_redaction_levels"] = {
            key: self.trace_redaction_levels[key] for key in sorted(self.trace_redaction_levels)
        }
        return data
