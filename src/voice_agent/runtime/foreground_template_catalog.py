from __future__ import annotations


_TEMPLATE_SUFFIX_BY_BASIS = {
    "template_ack": "ack",
    "template_clarify": "clarify",
}


def resolve_foreground_template_ref(
    *,
    output_ref: object,
    output_basis: object,
    fallback_policy_ref: object,
    fallback_reason: object,
    router_decision: object,
) -> str | None:
    if not all(
        isinstance(value, str) and value
        for value in (
            output_ref,
            output_basis,
            fallback_policy_ref,
            fallback_reason,
            router_decision,
        )
    ):
        return None
    suffix = _TEMPLATE_SUFFIX_BY_BASIS.get(output_basis)
    if suffix is None:
        return None
    if not output_ref.startswith("foreground-template://synthetic/"):
        return None
    if not output_ref.endswith(f"/{suffix}"):
        return None
    if not fallback_policy_ref.startswith("fallback-policy://synthetic/"):
        return None
    if not fallback_policy_ref.endswith(f"/{output_basis}"):
        return None
    if output_basis == "template_clarify":
        return "我还不太确定你的意思，可以再说具体一点吗？"
    if router_decision == "SPAWN_SLOW_TASK":
        return "我帮你看一下，请稍等。"
    if router_decision == "PATCH_ACTIVE_SLOW_TASK":
        return "收到，我会把这点补充到当前任务里。"
    return "我先确认一下，再继续回答。"
