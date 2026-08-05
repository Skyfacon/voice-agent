from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
import hashlib
import json
import re
from typing import Any

from voice_agent.privacy.redaction import (
    is_safe_release_token_id,
    is_safe_release_token_ref,
)


DIGEST_SCHEMA_VERSION = "1.0"
SAFE_SENSITIVE_METADATA_KEYS = frozenset(
    {
        "contains_raw_audio",
        "contains_raw_trace",
        "contains_real_user_input",
        "contains_secrets",
        "contains_unredacted_tool_result",
        "contains_large_raw_web_content",
        "authorization_basis",
        "authorization_event_id",
        "secret_kind",
        "release_token_id",
        "release_token_ref",
    }
)
RAW_OR_SENSITIVE_KEY_PATTERN = re.compile(
    r"(^|[_-])("
    r"raw[_-]?(audio|trace|transcript|user[_-]?text|text|web|tool|content)"
    r"|unredacted[_-]?user"
    r"|api[_-]?key"
    r"|authorization"
    r"|credential"
    r"|cookie"
    r"|password"
    r"|session[_-]?secret"
    r"|token"
    r"|tool[_-]?credentials?"
    r")([_-]|$)",
    re.IGNORECASE,
)


def state_digest(
    *,
    source_session_id: str | None,
    last_event_seq: int,
    event_schema_version_range: list[str] | tuple[str, ...],
    interaction_state: Any,
    playback_state: Any,
    adapter_health_state: Any,
    trace_privacy_state: Any,
    task_focus_state: Any | None = None,
    slowtask_state: Any | None = None,
    tool_execution_state: Any | None = None,
    demo_ui_state: Any | None = None,
    spoken_plan_state: Any | None = None,
    spoken_plan_check_state: Any | None = None,
    foreground_authority: Any | None = None,
    qwen_parallel_state: Any | None = None,
) -> dict[str, Any]:
    digest_without_overall: dict[str, Any] = {
        "digest_schema_version": DIGEST_SCHEMA_VERSION,
        "source_session_id": source_session_id,
        "last_event_seq": last_event_seq,
        "event_schema_version_range": list(event_schema_version_range),
        "interaction_state_hash": stable_hash(interaction_state),
        "task_focus_state_hash": stable_hash(task_focus_state or {}),
        "slowtask_state_hash": stable_hash(slowtask_state or {}),
        "tool_execution_state_hash": stable_hash(tool_execution_state or {}),
        "demo_ui_state_hash": stable_hash(demo_ui_state or {}),
        "spoken_plan_state_hash": stable_hash(spoken_plan_state or {}),
        "spoken_plan_check_state_hash": stable_hash(spoken_plan_check_state or {}),
        "playback_state_hash": stable_hash(playback_state),
        "adapter_health_state_hash": stable_hash(adapter_health_state),
        "trace_privacy_state_hash": stable_hash(trace_privacy_state),
    }
    if foreground_authority is not None:
        digest_without_overall["foreground_authority_hash"] = stable_hash(
            foreground_authority
        )
    if qwen_parallel_state is not None:
        digest_without_overall["qwen_parallel_state_hash"] = stable_hash(
            qwen_parallel_state
        )
    return {
        **digest_without_overall,
        "overall_digest": stable_hash(digest_without_overall),
    }


def stable_hash(value: Any) -> str:
    canonical_json = json.dumps(
        canonical_digest_payload(value),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def canonical_digest_payload(value: Any) -> Any:
    if hasattr(value, "to_digest_dict"):
        return canonical_digest_payload(value.to_digest_dict())
    if is_dataclass(value) and not isinstance(value, type):
        return canonical_digest_payload(asdict(value))
    if isinstance(value, Mapping):
        canonical: dict[str, Any] = {}
        for key, child in sorted(value.items(), key=lambda item: str(item[0])):
            key_text = str(key)
            if _is_sensitive_digest_key(key_text):
                continue
            _validate_safe_sensitive_metadata(key_text, child)
            canonical[key_text] = canonical_digest_payload(child)
        return canonical
    if isinstance(value, (list, tuple)):
        return [canonical_digest_payload(item) for item in value]
    return value


def _is_sensitive_digest_key(key: str) -> bool:
    if key in SAFE_SENSITIVE_METADATA_KEYS:
        return False
    return RAW_OR_SENSITIVE_KEY_PATTERN.search(key) is not None


def _validate_safe_sensitive_metadata(key: str, value: Any) -> None:
    if key == "release_token_id" and (
        not isinstance(value, str) or not is_safe_release_token_id(value)
    ):
        raise ValueError("release_token_id is not safe digest metadata")
    if key == "release_token_ref" and (
        not isinstance(value, str) or not is_safe_release_token_ref(value)
    ):
        raise ValueError("release_token_ref is not safe digest metadata")
