from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any


class ReplayManifestError(ValueError):
    pass


REQUIRED_MANIFEST_FIELDS = frozenset(
    {
        "manifest_schema_version",
        "replay_id",
        "source_trace_ref",
        "replay_mode",
        "event_schema_version_range",
        "fixture_domain",
        "generated_from",
        "contains_raw_audio",
        "contains_raw_trace",
        "contains_real_user_input",
        "contains_secrets",
        "contains_unredacted_tool_result",
        "contains_large_raw_web_content",
    }
)
REPLAY_MODES = frozenset({"deterministic", "degraded", "re_eval"})
FIXTURE_DOMAINS = frozenset({"LOCAL_DEBUG_TRACE", "SHAREABLE_REPLAY", "GITHUB_ALLOWED"})
GENERATED_FROM_VALUES = frozenset({"local_trace", "synthetic", "redacted", "hand_written_minimal"})
SHAREABLE_SAFETY_FLAGS = (
    "contains_raw_audio",
    "contains_raw_trace",
    "contains_real_user_input",
    "contains_unredacted_tool_result",
    "contains_large_raw_web_content",
)


@dataclass(frozen=True)
class ReplayManifest:
    manifest_schema_version: str
    replay_id: str
    source_trace_ref: str
    replay_mode: str
    event_schema_version_range: tuple[str, ...]
    fixture_domain: str
    generated_from: str
    contains_raw_audio: bool
    contains_raw_trace: bool
    contains_real_user_input: bool
    contains_secrets: bool
    contains_unredacted_tool_result: bool
    contains_large_raw_web_content: bool
    allowed_re_eval_components: tuple[str, ...] = ()
    expected_state_digest_ref: str | None = None
    redaction_report_ref: str | None = None
    raw_audio_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["event_schema_version_range"] = list(self.event_schema_version_range)
        data["allowed_re_eval_components"] = list(self.allowed_re_eval_components)
        return data


def validate_replay_manifest(manifest: Mapping[str, Any]) -> ReplayManifest:
    normalized = deepcopy(dict(manifest))
    missing = REQUIRED_MANIFEST_FIELDS - set(normalized)
    if missing:
        raise ReplayManifestError(f"Missing replay manifest fields: {sorted(missing)}")

    _require_literal(normalized, "manifest_schema_version", "1.0")
    _require_non_empty_str(normalized, "replay_id")
    _require_non_empty_str(normalized, "source_trace_ref")
    _require_member(normalized, "replay_mode", REPLAY_MODES)
    _require_member(normalized, "fixture_domain", FIXTURE_DOMAINS)
    _require_member(normalized, "generated_from", GENERATED_FROM_VALUES)

    event_versions = _string_tuple(normalized["event_schema_version_range"], "event_schema_version_range")
    if not event_versions:
        raise ReplayManifestError("event_schema_version_range must not be empty")

    for flag in (
        "contains_raw_audio",
        "contains_raw_trace",
        "contains_real_user_input",
        "contains_secrets",
        "contains_unredacted_tool_result",
        "contains_large_raw_web_content",
    ):
        _require_bool(normalized, flag)

    if normalized["contains_secrets"] is not False:
        raise ReplayManifestError("contains_secrets must always be false")

    fixture_domain = str(normalized["fixture_domain"])
    if fixture_domain in {"SHAREABLE_REPLAY", "GITHUB_ALLOWED"}:
        for flag in SHAREABLE_SAFETY_FLAGS:
            if normalized[flag] is not False:
                raise ReplayManifestError(f"{flag} must be false for {fixture_domain} fixtures")
        if normalized["generated_from"] == "local_trace":
            raise ReplayManifestError(f"generated_from=local_trace is not allowed for {fixture_domain}")
        if normalized.get("raw_audio_ref"):
            raise ReplayManifestError(f"raw_audio_ref is not allowed for {fixture_domain}")

    allowed_re_eval_components = _string_tuple(
        normalized.get("allowed_re_eval_components", ()),
        "allowed_re_eval_components",
    )
    if normalized["replay_mode"] in {"deterministic", "degraded"} and allowed_re_eval_components:
        raise ReplayManifestError("allowed_re_eval_components must be empty outside re_eval mode")

    return ReplayManifest(
        manifest_schema_version=str(normalized["manifest_schema_version"]),
        replay_id=str(normalized["replay_id"]),
        source_trace_ref=str(normalized["source_trace_ref"]),
        replay_mode=str(normalized["replay_mode"]),
        event_schema_version_range=event_versions,
        fixture_domain=fixture_domain,
        generated_from=str(normalized["generated_from"]),
        contains_raw_audio=bool(normalized["contains_raw_audio"]),
        contains_raw_trace=bool(normalized["contains_raw_trace"]),
        contains_real_user_input=bool(normalized["contains_real_user_input"]),
        contains_secrets=bool(normalized["contains_secrets"]),
        contains_unredacted_tool_result=bool(normalized["contains_unredacted_tool_result"]),
        contains_large_raw_web_content=bool(normalized["contains_large_raw_web_content"]),
        allowed_re_eval_components=allowed_re_eval_components,
        expected_state_digest_ref=_optional_str(normalized.get("expected_state_digest_ref")),
        redaction_report_ref=_optional_str(normalized.get("redaction_report_ref")),
        raw_audio_ref=_optional_str(normalized.get("raw_audio_ref")),
    )


def _require_literal(manifest: Mapping[str, Any], field: str, expected: str) -> None:
    if manifest.get(field) != expected:
        raise ReplayManifestError(f"{field} must be {expected!r}")


def _require_non_empty_str(manifest: Mapping[str, Any], field: str) -> None:
    value = manifest.get(field)
    if not isinstance(value, str) or value == "":
        raise ReplayManifestError(f"{field} must be a non-empty string")


def _require_bool(manifest: Mapping[str, Any], field: str) -> None:
    if not isinstance(manifest.get(field), bool):
        raise ReplayManifestError(f"{field} must be a boolean")


def _require_member(manifest: Mapping[str, Any], field: str, allowed_values: frozenset[str]) -> None:
    value = manifest.get(field)
    if value not in allowed_values:
        raise ReplayManifestError(f"{field} must be one of {sorted(allowed_values)}")


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ReplayManifestError(f"{field} must be a list of strings")
    if not all(isinstance(item, str) and item for item in value):
        raise ReplayManifestError(f"{field} must be a list of non-empty strings")
    return tuple(value)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value == "":
        raise ReplayManifestError("optional manifest refs must be non-empty strings when present")
    return value
