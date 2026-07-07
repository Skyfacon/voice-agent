from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
from typing import Any

from voice_agent.adapters.lalm_thinker_binding import LALM_THINKER_CANDIDATE_SCHEMA_VERSION


class LALMThinkerRoutingProfileError(ValueError):
    pass


@dataclass(frozen=True)
class LALMThinkerRoutingPromptProfile:
    profile_id: str
    version: str
    locale: str
    candidate_schema_version: str
    output_rules: tuple[str, ...]
    audio_output_rules: tuple[str, ...]
    system_instruction: str
    profile_hash: str

    def to_metadata(self) -> dict[str, str]:
        return {
            "profile_id": self.profile_id,
            "profile_version": self.version,
            "profile_hash": self.profile_hash,
            "locale": self.locale,
            "candidate_schema_version": self.candidate_schema_version,
        }


_DEFAULT_PROFILE_ID = "lalm-thinker-routing-control"
_DEFAULT_PROFILE_VERSION = "mvp6.2.zh-CN.v1"
_DEFAULT_PROFILE_LOCALE = "zh-CN"

_ROUTING_OUTPUT_RULES_ZH = (
    "只输出一个 lalm_thinker_semantic_frame_candidate.v1 JSON object",
    "第一个响应字符必须是 {，最后一个响应字符必须是 }",
    "不要用 markdown、解释文本、数组或多个 object 包裹 JSON",
    "必须逐字复制 required_output_skeleton.request_binding",
    "不要回答用户，也不要和用户聊天；只把用户输入分类为 routing evidence",
    "FOREGROUND_CHAT 表示闲聊、轻问答、翻译一句话或小型单轮解释；不需要 plan、tracking、tool 或后续执行",
    "例子: 讲冷笑话 -> FOREGROUND_CHAT",
    "例子: 解释一个概念、翻译一句话、简单问答或寒暄 -> FOREGROUND_CHAT",
    "NEW_TASK_CANDIDATE 表示需要多步骤规划、持续跟踪、后续执行、外部工具或较大产物",
    "例子: 帮我规划一个三天旅行并列步骤 -> NEW_TASK_CANDIDATE",
    "例子: research report、monitor metrics 或 create an execution plan -> NEW_TASK_CANDIDATE",
    "ACTIVE_TASK_PATCH 只能在 active task context 存在，且用户明显是在补充、修正或修改当前 active task 时使用",
    "证据或任务归属不清楚时使用 AMBIGUOUS，不要猜测",
    "NON_ASSISTANT 表示明确不是对助手说的话",
    "只表达 evidence availability、短 safe labels 和 normalized hints",
    "available optional_evidence_refs entry 必须包含短且非空的 label；否则设置为 unavailable",
    (
        "把 task_focus_hint.focus 设置为 FOREGROUND_CHAT、NEW_TASK_CANDIDATE、"
        "ACTIVE_TASK_PATCH、AMBIGUOUS 或 NON_ASSISTANT 之一"
    ),
    "routing evidence 不清楚时使用 AMBIGUOUS，并设置 high evidence_uncertainty",
    "Thinker focus is evidence only; Router owns the final RouterDecision",
    "不要包含 final event refs；adapter 拥有 deterministic provider-neutral refs",
    "不要包含 raw provider request、raw provider response、provider schema 或 raw semantic payload",
    "transient_input_evidence 只能作为输入证据；不要把它的文本复制到 labels",
    "不要调用工具、请求 native tool execution，也不要包含 tool_calls/function_call",
    "不要声明拥有 SemanticCommitment、confirmation、tool、playback、coverage 或 truthfulness ownership",
)

_AUDIO_RULE = "使用随附的音频作为 Thinker candidate 的主要证据"
_AUDIO_RULE_INSERT_INDEX = 14


def get_default_lalm_thinker_routing_profile() -> LALMThinkerRoutingPromptProfile:
    output_rules = tuple(_ROUTING_OUTPUT_RULES_ZH)
    audio_output_rules = (
        *output_rules[:_AUDIO_RULE_INSERT_INDEX],
        _AUDIO_RULE,
        *output_rules[_AUDIO_RULE_INSERT_INDEX:],
    )
    system_instruction = routing_rules_to_system_instruction(output_rules)
    return build_lalm_thinker_routing_profile(
        profile_id=_DEFAULT_PROFILE_ID,
        version=_DEFAULT_PROFILE_VERSION,
        locale=_DEFAULT_PROFILE_LOCALE,
        candidate_schema_version=LALM_THINKER_CANDIDATE_SCHEMA_VERSION,
        output_rules=output_rules,
        audio_output_rules=audio_output_rules,
        system_instruction=system_instruction,
    )


def routing_rules_to_system_instruction(rules: Sequence[str]) -> str:
    normalized_rules = tuple(_require_non_empty_string(rule, "rule") for rule in rules)
    return " ".join(_sentence(rule) for rule in normalized_rules)


def build_lalm_thinker_routing_profile(
    *,
    profile_id: str,
    version: str,
    locale: str,
    candidate_schema_version: str,
    output_rules: Sequence[str],
    audio_output_rules: Sequence[str],
    system_instruction: str,
) -> LALMThinkerRoutingPromptProfile:
    fields = {
        "profile_id": _require_safe_token(profile_id, "profile_id"),
        "version": _require_safe_token(version, "version"),
        "locale": _require_safe_token(locale, "locale"),
        "candidate_schema_version": _require_safe_token(
            candidate_schema_version,
            "candidate_schema_version",
        ),
        "output_rules": tuple(_require_non_empty_string(rule, "output_rule") for rule in output_rules),
        "audio_output_rules": tuple(
            _require_non_empty_string(rule, "audio_output_rule")
            for rule in audio_output_rules
        ),
        "system_instruction": _require_non_empty_string(
            system_instruction,
            "system_instruction",
        ),
    }
    if fields["candidate_schema_version"] != LALM_THINKER_CANDIDATE_SCHEMA_VERSION:
        raise LALMThinkerRoutingProfileError("unsupported candidate schema version")
    if not fields["output_rules"]:
        raise LALMThinkerRoutingProfileError("output_rules must be non-empty")
    if not fields["audio_output_rules"]:
        raise LALMThinkerRoutingProfileError("audio_output_rules must be non-empty")

    profile_hash = _profile_hash(fields)
    return LALMThinkerRoutingPromptProfile(
        profile_id=str(fields["profile_id"]),
        version=str(fields["version"]),
        locale=str(fields["locale"]),
        candidate_schema_version=str(fields["candidate_schema_version"]),
        output_rules=tuple(fields["output_rules"]),
        audio_output_rules=tuple(fields["audio_output_rules"]),
        system_instruction=str(fields["system_instruction"]),
        profile_hash=profile_hash,
    )


def _profile_hash(fields: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        fields,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _sentence(rule: str) -> str:
    return rule if rule.endswith(".") else f"{rule}."


def _require_non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise LALMThinkerRoutingProfileError(f"{field} must be a non-empty string")
    _reject_unsafe_text(value, field)
    return value


def _require_safe_token(value: object, field: str) -> str:
    token = _require_non_empty_string(value, field)
    if any(char.isspace() for char in token):
        raise LALMThinkerRoutingProfileError(f"{field} must not contain whitespace")
    return token


def _reject_unsafe_text(value: str, field: str) -> None:
    lowered = value.lower()
    for marker in (
        "audio/raw/",
        "diagnostics/",
        "traces/",
        "replays/local/",
        "file://",
        "/users/",
        "/private/",
        ".env",
        "authorization:",
        "cookie:",
        "api_key=",
        "token=",
        "bearer ",
    ):
        if marker in lowered:
            raise LALMThinkerRoutingProfileError(f"{field} contains unsafe content")
