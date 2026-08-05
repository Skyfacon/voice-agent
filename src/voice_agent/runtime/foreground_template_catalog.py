from __future__ import annotations

from dataclasses import dataclass


FOREGROUND_TEMPLATE_CATALOG_VERSION = "mvp6.3.foreground_template_catalog.v1"


class ForegroundTemplateCatalogError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ForegroundTemplate:
    catalog_version: str
    router_decision: str
    output_basis: str
    template_ref: str
    fallback_policy_ref: str
    foreground_act: str
    text: str


def _template(
    *,
    router_decision: str,
    route_segment: str,
    output_basis: str,
    suffix: str,
    foreground_act: str,
    text: str,
) -> ForegroundTemplate:
    version_segment = FOREGROUND_TEMPLATE_CATALOG_VERSION.rsplit(".", 1)[-1]
    return ForegroundTemplate(
        catalog_version=FOREGROUND_TEMPLATE_CATALOG_VERSION,
        router_decision=router_decision,
        output_basis=output_basis,
        template_ref=(
            f"foreground-template://mvp6.3/{version_segment}/{route_segment}/{suffix}"
        ),
        fallback_policy_ref=(
            f"fallback-policy://mvp6.3/{version_segment}/{route_segment}/{output_basis}"
        ),
        foreground_act=foreground_act,
        text=text,
    )


_CLARIFY_TEXT = "我还不太确定你的意思，可以再说具体一点吗？"
_CATALOG = {
    ("FAST_ONLY", "template_clarify"): _template(
        router_decision="FAST_ONLY",
        route_segment="fast-only",
        output_basis="template_clarify",
        suffix="clarify",
        foreground_act="CLARIFY",
        text=_CLARIFY_TEXT,
    ),
    ("SPAWN_SLOW_TASK", "template_ack"): _template(
        router_decision="SPAWN_SLOW_TASK",
        route_segment="spawn-slow-task",
        output_basis="template_ack",
        suffix="ack",
        foreground_act="ACK_SLOW",
        text="我帮你看一下，请稍等。",
    ),
    ("SPAWN_SLOW_TASK", "template_clarify"): _template(
        router_decision="SPAWN_SLOW_TASK",
        route_segment="spawn-slow-task",
        output_basis="template_clarify",
        suffix="clarify",
        foreground_act="CLARIFY",
        text=_CLARIFY_TEXT,
    ),
    ("PATCH_ACTIVE_SLOW_TASK", "template_ack"): _template(
        router_decision="PATCH_ACTIVE_SLOW_TASK",
        route_segment="patch-active-slow-task",
        output_basis="template_ack",
        suffix="ack",
        foreground_act="ACK_PATCH",
        text="收到，我会把这点补充到当前任务里。",
    ),
    ("PATCH_ACTIVE_SLOW_TASK", "template_clarify"): _template(
        router_decision="PATCH_ACTIVE_SLOW_TASK",
        route_segment="patch-active-slow-task",
        output_basis="template_clarify",
        suffix="clarify",
        foreground_act="CLARIFY",
        text=_CLARIFY_TEXT,
    ),
}
_CATALOG_BY_REF = {template.template_ref: template for template in _CATALOG.values()}


def get_foreground_template(
    *,
    router_decision: object,
    output_basis: object,
) -> ForegroundTemplate:
    if not isinstance(router_decision, str) or not isinstance(output_basis, str):
        raise ForegroundTemplateCatalogError(
            "router_decision and output_basis must be strings"
        )
    template = _CATALOG.get((router_decision, output_basis))
    if template is None:
        raise ForegroundTemplateCatalogError(
            "unsupported foreground template route/basis combination"
        )
    return template


def foreground_template_by_ref(output_ref: object) -> ForegroundTemplate | None:
    if not isinstance(output_ref, str):
        return None
    return _CATALOG_BY_REF.get(output_ref)


def resolve_foreground_template(
    *,
    output_ref: object,
    output_basis: object,
    fallback_policy_ref: object,
    router_decision: object,
) -> ForegroundTemplate | None:
    if not all(
        isinstance(value, str) and value
        for value in (
            output_ref,
            output_basis,
            fallback_policy_ref,
            router_decision,
        )
    ):
        return None
    template = _CATALOG.get((router_decision, output_basis))
    if template is None:
        return None
    if output_ref != template.template_ref:
        return None
    if fallback_policy_ref != template.fallback_policy_ref:
        return None
    return template


def resolve_foreground_template_ref(
    *,
    output_ref: object,
    output_basis: object,
    fallback_policy_ref: object,
    fallback_reason: object,
    router_decision: object,
) -> str | None:
    """Compatibility projection for the debug console.

    The catalog record is the source of truth. This wrapper only returns text
    after exact route/basis/version/ref validation.
    """

    if not isinstance(fallback_reason, str) or not fallback_reason:
        return None
    template = resolve_foreground_template(
        output_ref=output_ref,
        output_basis=output_basis,
        fallback_policy_ref=fallback_policy_ref,
        router_decision=router_decision,
    )
    return template.text if template is not None else None
