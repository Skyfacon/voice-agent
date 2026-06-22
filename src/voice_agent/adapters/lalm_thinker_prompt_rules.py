from __future__ import annotations


LALM_THINKER_ROUTING_OUTPUT_RULES = [
    "return exactly one lalm_thinker_semantic_frame_candidate.v1 JSON object",
    "the first response character must be { and the last response character must be }",
    "do not wrap JSON in markdown, prose, arrays, or multiple objects",
    "copy required_output_skeleton.request_binding exactly",
    "do not answer or chat with the user; classify the utterance as routing evidence only",
    "FOREGROUND_CHAT is for one-turn direct answers that need no plan, tracking, tool, or follow-up execution",
    "Example: 讲冷笑话 -> FOREGROUND_CHAT",
    "Example: explain one concept, translate one sentence, simple Q&A, or small talk -> FOREGROUND_CHAT",
    "NEW_TASK_CANDIDATE is for multi-step planning, ongoing tracking, follow-up execution, external tools, or larger artifacts",
    "Example: 帮我规划一个三天旅行并列步骤 -> NEW_TASK_CANDIDATE",
    "Example: research report, monitor metrics, or create an execution plan -> NEW_TASK_CANDIDATE",
    "ACTIVE_TASK_PATCH only when active task context exists and the user clearly supplements, corrects, or modifies that current task",
    "use AMBIGUOUS instead of guessing when routing evidence or task ownership is unclear",
    "NON_ASSISTANT for clearly non-assistant-directed input",
    "express only evidence availability, short safe labels, and normalized hints",
    "available optional_evidence_refs entry must include a short non-empty label; otherwise set status unavailable",
    (
        "set task_focus_hint.focus to one of FOREGROUND_CHAT, NEW_TASK_CANDIDATE, "
        "ACTIVE_TASK_PATCH, AMBIGUOUS, or NON_ASSISTANT"
    ),
    "use AMBIGUOUS with high evidence_uncertainty when routing evidence is unclear",
    "Thinker focus is evidence only; Router owns the final RouterDecision",
    "do not include final event refs; adapter owns deterministic provider-neutral refs",
    "do not include raw provider request, raw provider response, provider schema, or raw semantic payload",
    "use transient_input_evidence only as input evidence; do not copy its text into labels",
    "do not call tools, request native tool execution, or include tool_calls/function_call",
    "do not claim SemanticCommitment, confirmation, tool, playback, coverage, or truthfulness ownership",
]


LALM_THINKER_AUDIO_ROUTING_OUTPUT_RULES = [
    *LALM_THINKER_ROUTING_OUTPUT_RULES[:14],
    "use the attached audio as primary evidence for the Thinker candidate",
    *LALM_THINKER_ROUTING_OUTPUT_RULES[14:],
]


LALM_THINKER_EVIDENCE_SCHEMA_INSTRUCTION = " ".join(
    rule[0].upper() + rule[1:] + "."
    if rule and rule[0].islower() and not rule.endswith(".")
    else rule if rule.endswith(".") else f"{rule}."
    for rule in LALM_THINKER_ROUTING_OUTPUT_RULES
)
