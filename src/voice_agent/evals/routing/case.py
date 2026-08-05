from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass
import re
from typing import Any

from voice_agent.runtime.local_debug_text_safety import contains_likely_credential


ROUTING_CASE_SCHEMA_NAME = "voice_agent.routing_eval.case.v1"

ROUTING_SPLITS = frozenset({"prompt_dev", "validation", "locked_test"})
INPUT_MODALITIES = frozenset({"text", "audio"})
CONTEXT_TEMPLATES = frozenset(
    {
        "NO_ACTIVE_TASK",
        "ACTIVE_TASK_PLANNING",
        "ACTIVE_TASK_WAITING_TOOL",
        "ACTIVE_TASK_WAITING_CONFIRMATION",
        "ACTIVE_TASK_WAITING_SLOT",
        "ACTIVE_TASK_FINALIZING",
        "TERMINAL_TASK",
        "NON_ASSISTANT_BACKGROUND",
    }
)
ACTIVE_TASK_CONTEXT_TEMPLATES = frozenset(
    {
        "ACTIVE_TASK_PLANNING",
        "ACTIVE_TASK_WAITING_TOOL",
        "ACTIVE_TASK_WAITING_CONFIRMATION",
        "ACTIVE_TASK_WAITING_SLOT",
        "ACTIVE_TASK_FINALIZING",
        "TERMINAL_TASK",
    }
)
ACTIVE_TASK_LIFECYCLE_PHASES = frozenset(
    {
        "CREATED",
        "PLANNING",
        "WAITING_FOR_SLOT",
        "EXECUTING",
        "WAITING_FOR_USER_CONFIRMATION",
        "COMPLETED",
        "CANCELLED",
        "FAILED",
    }
)
PENDING_CONFIRMATION_SCOPES = frozenset(
    {
        "DEMO_DESTRUCTIVE_ACTION",
        "TASK_CANCEL",
        "SWITCH_TASK",
        "RISK_ACKNOWLEDGEMENT",
        "FINAL_ARGUMENT_CONFIRMATION",
    }
)
TERMINAL_TASK_LIFECYCLE_PHASES = frozenset({"COMPLETED", "CANCELLED", "FAILED"})
TASK_FOCUS_VALUES = frozenset(
    {
        "ACTIVE_TASK_PATCH",
        "FOREGROUND_CHAT",
        "NEW_TASK_CANDIDATE",
        "CANCEL_OR_PAUSE_CANDIDATE",
        "NON_ASSISTANT",
        "AMBIGUOUS",
    }
)
ROUTER_DECISIONS = frozenset(
    {"FAST_ONLY", "SPAWN_SLOW_TASK", "PATCH_ACTIVE_SLOW_TASK", "IGNORE"}
)
FOREGROUND_POLICIES = frozenset(
    {"ANSWER", "ACK_SLOW", "ACK_PATCH", "SILENCE", "CLARIFY"}
)
CRITICALITIES = frozenset({"low", "medium", "high"})
ANNOTATION_STATUSES = frozenset({"draft", "human_reviewed", "adjudicated"})

_SAFE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_LOCALE_PATTERN = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
_TAG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_SAFE_AUDIO_REF_PATTERN = re.compile(
    r"^audio-eval://(?:synthetic|local|locked)/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
)
_RAW_AUDIO_EXTENSIONS = (
    ".aac",
    ".aiff",
    ".flac",
    ".m4a",
    ".mp3",
    ".ogg",
    ".opus",
    ".wav",
    ".weba",
)
_UNSAFE_REF_FRAGMENTS = (
    "../",
    "..\\",
    "audio/raw",
    "diagnostics/",
    "traces/",
    "replays/local/",
    "file://",
    "http://",
    "https://",
    "provider://",
    "provider-url://",
)
_FORBIDDEN_KEY_PATTERN = re.compile(
    r"(?:raw[_-]?(?:audio|trace|prompt|transcript)|"
    r"provider[_-]?(?:body|payload|request|response|schema|text)|"
    r"authorization|cookie|credential|password|session[_-]?secret|"
    r"api[_-]?key|access[_-]?token|refresh[_-]?token)",
    re.IGNORECASE,
)


class RoutingCaseValidationError(ValueError):
    """Raised when a routing case is malformed or unsafe to commit/share."""


@dataclass(frozen=True)
class RoutingInput:
    modality: str
    locale: str
    utterance_text: str | None = None
    audio_ref: str | None = None


@dataclass(frozen=True)
class ActiveTaskContext:
    task_id: str
    task_type: str
    summary: str
    lifecycle_phase: str
    plan_version: int
    pending_confirmation_scope: str | None = None


@dataclass(frozen=True)
class RoutingContext:
    template: str
    active_task: ActiveTaskContext | None = None


@dataclass(frozen=True)
class SideEffectExpectations:
    slow_task_created: bool
    user_patch_emitted: bool
    external_side_effects: str


@dataclass(frozen=True)
class RoutingGold:
    task_focus_allowed: tuple[str, ...]
    router_decisions_allowed: tuple[str, ...]
    router_decisions_forbidden: tuple[str, ...]
    foreground_policy: str
    side_effect_expectations: SideEffectExpectations


@dataclass(frozen=True)
class RoutingCase:
    schema_name: str
    case_id: str
    scenario_family_id: str
    split: str
    input: RoutingInput
    context: RoutingContext
    gold: RoutingGold
    tags: tuple[str, ...]
    criticality: str
    annotation_status: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible copy of the complete evaluator record."""

        return asdict(self)

    def to_model_input(self) -> dict[str, Any]:
        """Return only runtime-visible evidence, physically excluding gold.

        Case identifiers, tags, annotation metadata, and labels are evaluator
        concerns.  Excluding them as well as ``gold`` prevents accidental label
        leakage through suggestive family names or rationale tags.
        """

        return {
            "input": deepcopy(asdict(self.input)),
            "context": deepcopy(asdict(self.context)),
        }


def validate_routing_case(value: Mapping[str, Any]) -> RoutingCase:
    """Validate and normalize one ``voice_agent.routing_eval.case.v1`` record."""

    if not isinstance(value, Mapping):
        raise RoutingCaseValidationError("routing case must be a JSON object")
    raw = deepcopy(dict(value))
    _scan_for_unsafe_content(raw)
    _require_exact_keys(
        raw,
        required={
            "schema_name",
            "case_id",
            "scenario_family_id",
            "split",
            "input",
            "context",
            "gold",
            "tags",
            "criticality",
            "annotation_status",
        },
        path="case",
    )

    if raw["schema_name"] != ROUTING_CASE_SCHEMA_NAME:
        raise RoutingCaseValidationError(
            f"schema_name must be {ROUTING_CASE_SCHEMA_NAME!r}"
        )
    case_id = _safe_token(raw["case_id"], "case.case_id")
    scenario_family_id = _safe_token(
        raw["scenario_family_id"], "case.scenario_family_id"
    )
    split = _enum(raw["split"], ROUTING_SPLITS, "case.split")
    routing_input = _validate_input(raw["input"])
    context = _validate_context(raw["context"])
    gold = _validate_gold(raw["gold"])
    tags = _tag_tuple(raw["tags"], "case.tags")
    criticality = _enum(raw["criticality"], CRITICALITIES, "case.criticality")
    annotation_status = _enum(
        raw["annotation_status"], ANNOTATION_STATUSES, "case.annotation_status"
    )

    _validate_context_gold_relationship(context, gold)
    return RoutingCase(
        schema_name=ROUTING_CASE_SCHEMA_NAME,
        case_id=case_id,
        scenario_family_id=scenario_family_id,
        split=split,
        input=routing_input,
        context=context,
        gold=gold,
        tags=tags,
        criticality=criticality,
        annotation_status=annotation_status,
    )


def routing_case_to_model_input(case: RoutingCase | Mapping[str, Any]) -> dict[str, Any]:
    """Build adapter input without ever copying evaluator-only fields."""

    normalized = case if isinstance(case, RoutingCase) else validate_routing_case(case)
    return normalized.to_model_input()


def _validate_input(value: object) -> RoutingInput:
    raw = _mapping(value, "case.input")
    _require_exact_keys(
        raw,
        required={"modality", "locale"},
        optional={"utterance_text", "audio_ref"},
        path="case.input",
    )
    modality = _enum(raw["modality"], INPUT_MODALITIES, "case.input.modality")
    locale = _non_empty_str(raw["locale"], "case.input.locale", max_length=35)
    if _LOCALE_PATTERN.fullmatch(locale) is None:
        raise RoutingCaseValidationError("case.input.locale must be a BCP47-like locale")

    if modality == "text":
        if "audio_ref" in raw:
            raise RoutingCaseValidationError("text input must not include audio_ref")
        utterance_text = _non_empty_str(
            raw.get("utterance_text"), "case.input.utterance_text", max_length=2000
        )
        return RoutingInput(modality=modality, locale=locale, utterance_text=utterance_text)

    if "utterance_text" in raw:
        raise RoutingCaseValidationError("audio input must not include utterance_text")
    audio_ref = _safe_audio_ref(raw.get("audio_ref"), "case.input.audio_ref")
    return RoutingInput(modality=modality, locale=locale, audio_ref=audio_ref)


def _validate_context(value: object) -> RoutingContext:
    raw = _mapping(value, "case.context")
    _require_exact_keys(
        raw,
        required={"template"},
        optional={"active_task"},
        path="case.context",
    )
    template = _enum(raw["template"], CONTEXT_TEMPLATES, "case.context.template")
    active_task = (
        _validate_active_task(raw["active_task"]) if "active_task" in raw else None
    )
    if template in ACTIVE_TASK_CONTEXT_TEMPLATES and active_task is None:
        raise RoutingCaseValidationError(f"{template} context requires active_task")
    if template not in ACTIVE_TASK_CONTEXT_TEMPLATES and active_task is not None:
        raise RoutingCaseValidationError(f"{template} context must not include active_task")
    if template == "TERMINAL_TASK":
        assert active_task is not None
        if active_task.lifecycle_phase not in TERMINAL_TASK_LIFECYCLE_PHASES:
            raise RoutingCaseValidationError(
                "TERMINAL_TASK active_task.lifecycle_phase must be terminal"
            )
    elif active_task is not None and active_task.lifecycle_phase in TERMINAL_TASK_LIFECYCLE_PHASES:
        raise RoutingCaseValidationError(
            f"{template} active_task.lifecycle_phase must be non-terminal"
        )
    if template == "ACTIVE_TASK_WAITING_CONFIRMATION":
        assert active_task is not None
        if active_task.lifecycle_phase != "WAITING_FOR_USER_CONFIRMATION":
            raise RoutingCaseValidationError(
                "ACTIVE_TASK_WAITING_CONFIRMATION requires WAITING_FOR_USER_CONFIRMATION"
            )
        if active_task.pending_confirmation_scope is None:
            raise RoutingCaseValidationError(
                "ACTIVE_TASK_WAITING_CONFIRMATION requires pending_confirmation_scope"
            )
    elif active_task is not None and active_task.pending_confirmation_scope is not None:
        raise RoutingCaseValidationError(
            "pending_confirmation_scope is only valid for ACTIVE_TASK_WAITING_CONFIRMATION"
        )
    return RoutingContext(template=template, active_task=active_task)


def _validate_active_task(value: object) -> ActiveTaskContext:
    raw = _mapping(value, "case.context.active_task")
    _require_exact_keys(
        raw,
        required={"task_id", "task_type", "summary", "lifecycle_phase", "plan_version"},
        optional={"pending_confirmation_scope"},
        path="case.context.active_task",
    )
    plan_version = raw["plan_version"]
    if isinstance(plan_version, bool) or not isinstance(plan_version, int) or plan_version < 1:
        raise RoutingCaseValidationError(
            "case.context.active_task.plan_version must be an integer >= 1"
        )
    return ActiveTaskContext(
        task_id=_safe_token(raw["task_id"], "case.context.active_task.task_id"),
        task_type=_safe_token(raw["task_type"], "case.context.active_task.task_type"),
        summary=_non_empty_str(
            raw["summary"], "case.context.active_task.summary", max_length=2000
        ),
        lifecycle_phase=_enum(
            raw["lifecycle_phase"],
            ACTIVE_TASK_LIFECYCLE_PHASES,
            "case.context.active_task.lifecycle_phase",
        ),
        plan_version=plan_version,
        pending_confirmation_scope=(
            _enum(
                raw["pending_confirmation_scope"],
                PENDING_CONFIRMATION_SCOPES,
                "case.context.active_task.pending_confirmation_scope",
            )
            if "pending_confirmation_scope" in raw
            else None
        ),
    )


def _validate_gold(value: object) -> RoutingGold:
    raw = _mapping(value, "case.gold")
    _require_exact_keys(
        raw,
        required={
            "task_focus_allowed",
            "router_decisions_allowed",
            "router_decisions_forbidden",
            "foreground_policy",
            "side_effect_expectations",
        },
        path="case.gold",
    )
    task_focus = _enum_tuple(
        raw["task_focus_allowed"],
        TASK_FOCUS_VALUES,
        "case.gold.task_focus_allowed",
        require_non_empty=True,
    )
    decisions_allowed = _enum_tuple(
        raw["router_decisions_allowed"],
        ROUTER_DECISIONS,
        "case.gold.router_decisions_allowed",
        require_non_empty=True,
    )
    decisions_forbidden = _enum_tuple(
        raw["router_decisions_forbidden"],
        ROUTER_DECISIONS,
        "case.gold.router_decisions_forbidden",
        require_non_empty=False,
    )
    allowed_set = set(decisions_allowed)
    forbidden_set = set(decisions_forbidden)
    if allowed_set & forbidden_set:
        raise RoutingCaseValidationError(
            "case.gold router_decisions_allowed and router_decisions_forbidden must be disjoint"
        )
    if allowed_set | forbidden_set != ROUTER_DECISIONS:
        raise RoutingCaseValidationError(
            "case.gold allowed/forbidden router decisions must partition all router decisions"
        )
    side_effects = _validate_side_effect_expectations(raw["side_effect_expectations"])
    if side_effects.slow_task_created and "SPAWN_SLOW_TASK" not in allowed_set:
        raise RoutingCaseValidationError(
            "slow_task_created=true requires SPAWN_SLOW_TASK to be allowed"
        )
    if side_effects.user_patch_emitted and "PATCH_ACTIVE_SLOW_TASK" not in allowed_set:
        raise RoutingCaseValidationError(
            "user_patch_emitted=true requires PATCH_ACTIVE_SLOW_TASK to be allowed"
        )
    if allowed_set == {"SPAWN_SLOW_TASK"} and not side_effects.slow_task_created:
        raise RoutingCaseValidationError(
            "singleton SPAWN_SLOW_TASK gold requires slow_task_created=true"
        )
    if allowed_set == {"PATCH_ACTIVE_SLOW_TASK"} and not side_effects.user_patch_emitted:
        raise RoutingCaseValidationError(
            "singleton PATCH_ACTIVE_SLOW_TASK gold requires user_patch_emitted=true"
        )
    return RoutingGold(
        task_focus_allowed=task_focus,
        router_decisions_allowed=decisions_allowed,
        router_decisions_forbidden=decisions_forbidden,
        foreground_policy=_enum(
            raw["foreground_policy"],
            FOREGROUND_POLICIES,
            "case.gold.foreground_policy",
        ),
        side_effect_expectations=side_effects,
    )


def _validate_side_effect_expectations(value: object) -> SideEffectExpectations:
    raw = _mapping(value, "case.gold.side_effect_expectations")
    _require_exact_keys(
        raw,
        required={"slow_task_created", "user_patch_emitted", "external_side_effects"},
        path="case.gold.side_effect_expectations",
    )
    slow_task_created = _bool(
        raw["slow_task_created"],
        "case.gold.side_effect_expectations.slow_task_created",
    )
    user_patch_emitted = _bool(
        raw["user_patch_emitted"],
        "case.gold.side_effect_expectations.user_patch_emitted",
    )
    if raw["external_side_effects"] != "FORBIDDEN":
        raise RoutingCaseValidationError(
            "case.gold.side_effect_expectations.external_side_effects must be 'FORBIDDEN'"
        )
    return SideEffectExpectations(
        slow_task_created=slow_task_created,
        user_patch_emitted=user_patch_emitted,
        external_side_effects="FORBIDDEN",
    )


def _validate_context_gold_relationship(context: RoutingContext, gold: RoutingGold) -> None:
    focus = set(gold.task_focus_allowed)
    if focus & {"ACTIVE_TASK_PATCH", "CANCEL_OR_PAUSE_CANDIDATE"}:
        if context.active_task is None:
            raise RoutingCaseValidationError(
                "active-task patch/cancel focus requires an active task context"
            )
        if context.template == "TERMINAL_TASK":
            raise RoutingCaseValidationError(
                "terminal task context cannot allow active-task patch/cancel focus"
            )


def _mapping(value: object, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RoutingCaseValidationError(f"{path} must be a JSON object")
    if not all(isinstance(key, str) for key in value):
        raise RoutingCaseValidationError(f"{path} keys must be strings")
    return deepcopy(dict(value))


def _require_exact_keys(
    value: Mapping[str, Any],
    *,
    required: set[str],
    path: str,
    optional: set[str] | None = None,
) -> None:
    optional = optional or set()
    missing = required - set(value)
    if missing:
        raise RoutingCaseValidationError(f"{path} missing fields: {sorted(missing)}")
    unexpected = set(value) - required - optional
    if unexpected:
        raise RoutingCaseValidationError(f"{path} has unexpected fields: {sorted(unexpected)}")


def _enum(value: object, allowed: frozenset[str], path: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise RoutingCaseValidationError(f"{path} must be one of {sorted(allowed)}")
    return value


def _enum_tuple(
    value: object,
    allowed: frozenset[str],
    path: str,
    *,
    require_non_empty: bool,
) -> tuple[str, ...]:
    items = _sequence(value, path)
    if require_non_empty and not items:
        raise RoutingCaseValidationError(f"{path} must not be empty")
    normalized = tuple(_enum(item, allowed, f"{path}[{index}]") for index, item in enumerate(items))
    if len(set(normalized)) != len(normalized):
        raise RoutingCaseValidationError(f"{path} must contain unique values")
    return normalized


def _tag_tuple(value: object, path: str) -> tuple[str, ...]:
    items = _sequence(value, path)
    normalized: list[str] = []
    for index, item in enumerate(items):
        tag = _non_empty_str(item, f"{path}[{index}]", max_length=64)
        if _TAG_PATTERN.fullmatch(tag) is None:
            raise RoutingCaseValidationError(
                f"{path}[{index}] must be a lowercase safe tag token"
            )
        normalized.append(tag)
    if len(set(normalized)) != len(normalized):
        raise RoutingCaseValidationError(f"{path} must contain unique values")
    return tuple(normalized)


def _sequence(value: object, path: str) -> tuple[object, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise RoutingCaseValidationError(f"{path} must be a JSON array")
    return tuple(value)


def _safe_token(value: object, path: str) -> str:
    token = _non_empty_str(value, path, max_length=128)
    if _SAFE_TOKEN_PATTERN.fullmatch(token) is None:
        raise RoutingCaseValidationError(f"{path} must be a safe token")
    return token


def _safe_audio_ref(value: object, path: str) -> str:
    ref = _non_empty_str(value, path, max_length=180)
    lower_ref = ref.lower()
    if _SAFE_AUDIO_REF_PATTERN.fullmatch(ref) is None:
        raise RoutingCaseValidationError(
            f"{path} must be an audio-eval://synthetic|local|locked safe reference"
        )
    if lower_ref.endswith(_RAW_AUDIO_EXTENSIONS):
        raise RoutingCaseValidationError(f"{path} must not expose a raw audio filename")
    if any(fragment in lower_ref for fragment in _UNSAFE_REF_FRAGMENTS):
        raise RoutingCaseValidationError(f"{path} contains an unsafe path or provider reference")
    return ref


def _non_empty_str(value: object, path: str, *, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RoutingCaseValidationError(f"{path} must be a non-empty string")
    if value != value.strip():
        raise RoutingCaseValidationError(f"{path} must not have leading or trailing whitespace")
    if len(value) > max_length:
        raise RoutingCaseValidationError(f"{path} exceeds maximum length {max_length}")
    if "\x00" in value:
        raise RoutingCaseValidationError(f"{path} must not contain NUL")
    return value


def _bool(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        raise RoutingCaseValidationError(f"{path} must be a boolean")
    return value


def _scan_for_unsafe_content(value: object, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise RoutingCaseValidationError("routing case object keys must be strings")
            key_path = ".".join((*path, key))
            if _FORBIDDEN_KEY_PATTERN.search(key):
                raise RoutingCaseValidationError(f"unsafe secret/raw/provider field: {key_path}")
            _scan_for_unsafe_content(child, (*path, key))
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            _scan_for_unsafe_content(child, (*path, str(index)))
        return
    if isinstance(value, str) and contains_likely_credential(value):
        raise RoutingCaseValidationError(
            f"likely credential detected at {'.'.join(path) or 'case'}"
        )
