from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass
import math
import re
from typing import Any, Protocol, runtime_checkable

from voice_agent.evals.routing.case import (
    ROUTER_DECISIONS,
    TASK_FOCUS_VALUES,
    RoutingCase,
    routing_case_to_model_input,
    validate_routing_case,
)
from voice_agent.evals.routing.event_factory import (
    PREDICTED_DIRECTEDNESS_VALUES,
    PREDICTED_FOREGROUND_ACTS,
    PREDICTED_RISK_CLASSES,
    PredictedRoutingEvidence,
)
from voice_agent.evals.routing.metrics import RoutingPrediction


MODEL_OUTPUT_MODES = frozenset({"mock", "real", "fallback", "degraded"})
MODEL_COMPLEXITY_HINTS = frozenset(
    {"simple", "medium", "task", "complex", "unknown"}
)
MODEL_EVIDENCE_UNCERTAINTY = frozenset(
    {"low", "medium", "high", "conflicting", "unknown"}
)
MODEL_OUTPUT_FIELDS = frozenset(
    {
        "task_focus_hint",
        "route_hint",
        "task_like",
        "complexity_hint",
        "evidence_uncertainty",
        "directedness",
        "foreground_act",
        "risk",
        "confidence",
        "schema_valid",
        "output_mode",
        "latency_ms",
        "profile_id",
        "profile_version",
        "profile_hash",
    }
)

_SAFE_PROFILE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")
_PROFILE_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")


class ModelRunnerError(ValueError):
    """Base error for the provider-neutral Model-layer harness."""


class ModelOutputValidationError(ModelRunnerError):
    """Raised when an adapter result cannot become routing evidence."""


@dataclass(frozen=True)
class ModelProfileMetadata:
    profile_id: str
    profile_version: str
    profile_hash: str

    def __post_init__(self) -> None:
        _validate_profile_token(self.profile_id, "profile_id")
        _validate_profile_token(self.profile_version, "profile_version")
        if not isinstance(self.profile_hash, str) or _PROFILE_HASH.fullmatch(
            self.profile_hash
        ) is None:
            raise ModelRunnerError("profile_hash must be a lowercase sha256 digest")

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class ModelRoutingOutput:
    """Strict normalized output from one model routing evaluation call."""

    case_id: str
    task_focus_hint: str
    route_hint: str
    task_like: bool
    complexity_hint: str
    evidence_uncertainty: str
    directedness: str
    foreground_act: str
    risk: str
    confidence: float
    schema_valid: bool
    output_mode: str
    latency_ms: float
    profile_id: str
    profile_version: str
    profile_hash: str

    @property
    def risk_class(self) -> str:
        return self.risk

    def to_predicted_evidence(self) -> PredictedRoutingEvidence:
        """Project model evidence without inventing a foreground candidate."""

        return PredictedRoutingEvidence(
            task_focus_hint=self.task_focus_hint,
            route_decision_hint=self.route_hint,
            task_like=self.task_like,
            complexity_hint=self.complexity_hint,
            evidence_uncertainty=self.evidence_uncertainty,
            directedness=self.directedness,
            foreground_act=self.foreground_act,
            risk_class=self.risk,
            confidence=self.confidence,
            emit_candidate=False,
        )

    def to_routing_prediction(self) -> RoutingPrediction:
        """Build a Model-layer prediction with foreground/effects unobserved."""

        return RoutingPrediction(
            case_id=self.case_id,
            task_focus=self.task_focus_hint,
            router_decision=self.route_hint,
            foreground_policy=None,
            slow_task_created=False,
            user_patch_emitted=False,
            external_side_effects=False,
            answer_candidate_committed=False,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@runtime_checkable
class ModelRunner(Protocol):
    """Callable boundary receiving only the gold-free runtime model input."""

    def __call__(self, model_input: Mapping[str, Any], /) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class ModelCaseRun:
    case_id: str
    output: ModelRoutingOutput
    predicted_evidence: PredictedRoutingEvidence
    prediction: RoutingPrediction
    provider_call_used: bool | None
    network_used: bool | None
    credential_env_var_read: bool | None
    gold_included_in_model_input: bool = False
    raw_audio_included: bool = False
    raw_provider_body_included: bool = False
    prompt_dump_included: bool = False
    secret_included: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "output": self.output.to_dict(),
            "predicted_evidence": asdict(self.predicted_evidence),
            "prediction": asdict(self.prediction),
            "provider_call_used": self.provider_call_used,
            "network_used": self.network_used,
            "credential_env_var_read": self.credential_env_var_read,
            "gold_included_in_model_input": self.gold_included_in_model_input,
            "raw_audio_included": self.raw_audio_included,
            "raw_provider_body_included": self.raw_provider_body_included,
            "prompt_dump_included": self.prompt_dump_included,
            "secret_included": self.secret_included,
        }


def run_model_case(
    case: RoutingCase | Mapping[str, Any],
    adapter_callable: ModelRunner | Callable[[Mapping[str, Any]], Mapping[str, Any]],
    profile_metadata: ModelProfileMetadata | Mapping[str, str],
) -> ModelCaseRun:
    """Run one Model-layer case without consulting gold for prediction.

    The adapter receives exactly ``routing_case_to_model_input(case)`` as its
    sole argument. Profile metadata remains evaluator-side and the adapter's
    returned profile identifiers must match it exactly.
    """

    normalized = case if isinstance(case, RoutingCase) else validate_routing_case(case)
    profile = _normalize_profile_metadata(profile_metadata)
    model_input = routing_case_to_model_input(normalized)
    raw_output = adapter_callable(model_input)
    output = _validate_model_output(
        raw_output,
        case_id=normalized.case_id,
        expected_profile=profile,
    )
    evidence = output.to_predicted_evidence()
    prediction = output.to_routing_prediction()
    return ModelCaseRun(
        case_id=normalized.case_id,
        output=output,
        predicted_evidence=evidence,
        prediction=prediction,
        provider_call_used=_execution_flag(adapter_callable, "provider_call_used"),
        network_used=_execution_flag(adapter_callable, "network_used"),
        credential_env_var_read=_execution_flag(
            adapter_callable, "credential_env_var_read"
        ),
    )


class FakeInjectedModelAdapter:
    """Provider-free fake whose complete output is explicitly test-injected."""

    provider_call_used = False
    network_used = False
    credential_env_var_read = False

    def __init__(self, injected_output: Mapping[str, Any]) -> None:
        if not isinstance(injected_output, Mapping):
            raise TypeError("injected_output must be a mapping")
        self._injected_output = deepcopy(dict(injected_output))
        self.calls: list[dict[str, Any]] = []

    def __call__(self, model_input: Mapping[str, Any], /) -> Mapping[str, Any]:
        if not isinstance(model_input, Mapping):
            raise TypeError("model_input must be a mapping")
        self.calls.append(deepcopy(dict(model_input)))
        return deepcopy(self._injected_output)


def _validate_model_output(
    value: object,
    *,
    case_id: str,
    expected_profile: ModelProfileMetadata,
) -> ModelRoutingOutput:
    if not isinstance(value, Mapping):
        raise ModelOutputValidationError("model output must be a mapping")
    raw = dict(value)
    missing = MODEL_OUTPUT_FIELDS - set(raw)
    unexpected = set(raw) - MODEL_OUTPUT_FIELDS
    if missing or unexpected:
        raise ModelOutputValidationError(
            "model output must contain exactly the v1 routing output fields"
        )

    schema_valid = _require_bool(raw["schema_valid"], "schema_valid")
    if not schema_valid:
        raise ModelOutputValidationError("model output schema_valid must be true")
    task_focus = _require_enum(
        raw["task_focus_hint"], TASK_FOCUS_VALUES, "task_focus_hint"
    )
    route_hint = _require_enum(raw["route_hint"], ROUTER_DECISIONS, "route_hint")
    task_like = _require_bool(raw["task_like"], "task_like")
    complexity_hint = _require_enum(
        raw["complexity_hint"], MODEL_COMPLEXITY_HINTS, "complexity_hint"
    )
    evidence_uncertainty = _require_enum(
        raw["evidence_uncertainty"],
        MODEL_EVIDENCE_UNCERTAINTY,
        "evidence_uncertainty",
    )
    directedness = _require_enum(
        raw["directedness"], PREDICTED_DIRECTEDNESS_VALUES, "directedness"
    )
    foreground_act = _require_enum(
        raw["foreground_act"], PREDICTED_FOREGROUND_ACTS, "foreground_act"
    )
    risk = _require_enum(raw["risk"], PREDICTED_RISK_CLASSES, "risk")
    confidence = _require_finite_number(
        raw["confidence"], "confidence", minimum=0.0, maximum=1.0
    )
    latency_ms = _require_finite_number(raw["latency_ms"], "latency_ms", minimum=0.0)
    output_mode = _require_enum(raw["output_mode"], MODEL_OUTPUT_MODES, "output_mode")

    try:
        profile = ModelProfileMetadata(
            profile_id=_require_profile_string(raw["profile_id"], "profile_id"),
            profile_version=_require_profile_string(
                raw["profile_version"], "profile_version"
            ),
            profile_hash=_require_profile_string(raw["profile_hash"], "profile_hash"),
        )
    except ModelRunnerError as exc:
        raise ModelOutputValidationError(
            "model output contains invalid profile metadata"
        ) from exc
    if profile != expected_profile:
        raise ModelOutputValidationError(
            "model output profile metadata does not match requested profile"
        )

    return ModelRoutingOutput(
        case_id=case_id,
        task_focus_hint=task_focus,
        route_hint=route_hint,
        task_like=task_like,
        complexity_hint=complexity_hint,
        evidence_uncertainty=evidence_uncertainty,
        directedness=directedness,
        foreground_act=foreground_act,
        risk=risk,
        confidence=confidence,
        schema_valid=True,
        output_mode=output_mode,
        latency_ms=latency_ms,
        profile_id=profile.profile_id,
        profile_version=profile.profile_version,
        profile_hash=profile.profile_hash,
    )


def _normalize_profile_metadata(
    value: ModelProfileMetadata | Mapping[str, str],
) -> ModelProfileMetadata:
    if isinstance(value, ModelProfileMetadata):
        return value
    required = {"profile_id", "profile_version", "profile_hash"}
    allowed = required | {"locale", "candidate_schema_version"}
    if (
        not isinstance(value, Mapping)
        or not required <= set(value)
        or set(value) - allowed
    ):
        raise ModelRunnerError(
            "profile metadata must contain only supported profile metadata fields"
        )
    return ModelProfileMetadata(
        profile_id=value["profile_id"],
        profile_version=value["profile_version"],
        profile_hash=value["profile_hash"],
    )


def _execution_flag(adapter: object, field: str) -> bool | None:
    value = getattr(adapter, field, None)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ModelRunnerError(f"adapter {field} flag must be a boolean when present")
    return value


def _require_enum(value: object, allowed: frozenset[str], field: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ModelOutputValidationError(f"{field} must be one of {sorted(allowed)}")
    return value


def _require_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ModelOutputValidationError(f"{field} must be a boolean")
    return value


def _require_finite_number(
    value: object,
    field: str,
    *,
    minimum: float,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ModelOutputValidationError(f"{field} must be a finite number")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < minimum:
        raise ModelOutputValidationError(f"{field} is outside the allowed range")
    if maximum is not None and normalized > maximum:
        raise ModelOutputValidationError(f"{field} is outside the allowed range")
    return normalized


def _require_profile_string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ModelOutputValidationError(f"{field} must be a string")
    return value


def _validate_profile_token(value: object, field: str) -> None:
    if not isinstance(value, str) or _SAFE_PROFILE_TOKEN.fullmatch(value) is None:
        raise ModelRunnerError(f"{field} must be an opaque safe token")
