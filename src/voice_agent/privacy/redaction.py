from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import re
from typing import Any


REDACTED_SECRET_VALUE = "[REDACTED_SECRET]"


class PayloadBlockedError(ValueError):
    pass


SECRET_FIELD_PATTERN = re.compile(
    r"(^|[_-])(api[_-]?key|authorization|credential|cookie|password|secret|session[_-]?secret|token)([_-]|$)",
    re.IGNORECASE,
)
ALLOWED_SECRET_METADATA_FIELDS = {"secret_kind"}
BLOCKED_RAW_FIELD_PATTERN = re.compile(
    r"(^|[_-])(raw[_-]?audio|raw[_-]?trace|raw[_-]?transcript|raw[_-]?user[_-]?text|raw[_-]?text|user[_-]?text|user[_-]?utterance|unredacted[_-]?user)([_-]|$)",
    re.IGNORECASE,
)
SECRET_VALUE_PATTERN = re.compile(
    r"(sk-[A-Za-z0-9_-]+|Bearer\s+\S+|xox[baprs]-\S+|AKIA[0-9A-Z]{16})"
)
LOCAL_ONLY_PATH_PATTERN = re.compile(r"(^|/)(audio/raw|traces|diagnostics|replays/local)(/|$)", re.IGNORECASE)


def sanitize_event_payload(payload: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    redacted_fields: list[str] = []
    sanitized = _sanitize_mapping(deepcopy(dict(payload)), (), redacted_fields)
    return sanitized, redacted_fields


def _sanitize_mapping(value: dict[str, Any], path: tuple[str, ...], redacted_fields: list[str]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, child in value.items():
        key_path = (*path, str(key))
        key_path_label = ".".join(key_path)
        if BLOCKED_RAW_FIELD_PATTERN.search(str(key)):
            raise PayloadBlockedError(f"Blocked unsafe raw payload field: {key_path_label}")
        if str(key) in ALLOWED_SECRET_METADATA_FIELDS:
            sanitized[key] = _sanitize_value(child, key_path, redacted_fields)
            continue
        if SECRET_FIELD_PATTERN.search(str(key)):
            sanitized[key] = REDACTED_SECRET_VALUE
            redacted_fields.append(key_path_label)
            continue
        sanitized[key] = _sanitize_value(child, key_path, redacted_fields)
    return sanitized


def _sanitize_value(value: Any, path: tuple[str, ...], redacted_fields: list[str]) -> Any:
    if isinstance(value, Mapping):
        return _sanitize_mapping(dict(value), path, redacted_fields)
    if isinstance(value, list):
        return [_sanitize_value(child, (*path, str(index)), redacted_fields) for index, child in enumerate(value)]
    if isinstance(value, tuple):
        return tuple(_sanitize_value(child, (*path, str(index)), redacted_fields) for index, child in enumerate(value))
    if isinstance(value, str) and SECRET_VALUE_PATTERN.search(value):
        key_path_label = ".".join(path)
        raise PayloadBlockedError(f"Blocked unredactable secret-like value at: {key_path_label}")
    if isinstance(value, str) and LOCAL_ONLY_PATH_PATTERN.search(value):
        key_path_label = ".".join(path)
        raise PayloadBlockedError(f"Blocked local-only artifact path at: {key_path_label}")
    return value
