from __future__ import annotations

from collections.abc import Iterable

from voice_agent.tools.manifest import ToolExecutionPolicyError, ToolManifest, require_mvp_side_effect_class


class ToolRegistry:
    def __init__(
        self,
        manifests: Iterable[ToolManifest],
        *,
        validate_side_effect_classes: bool = True,
    ) -> None:
        self._manifests: dict[str, ToolManifest] = {}
        for manifest in manifests:
            self.register(manifest, validate_side_effect_class=validate_side_effect_classes)

    def register(
        self,
        manifest: ToolManifest,
        *,
        validate_side_effect_class: bool = True,
    ) -> None:
        if validate_side_effect_class:
            require_mvp_side_effect_class(manifest.side_effect_class)
        existing = self._manifests.get(manifest.tool_name)
        if existing is not None and existing.tool_manifest_version != manifest.tool_manifest_version:
            raise ToolExecutionPolicyError("duplicate tool_name with different manifest version")
        self._manifests[manifest.tool_name] = manifest

    def get(self, tool_name: str) -> ToolManifest:
        try:
            return self._manifests[tool_name]
        except KeyError as exc:
            raise ToolExecutionPolicyError(f"unknown tool_name: {tool_name}") from exc

    def manifests(self) -> tuple[ToolManifest, ...]:
        return tuple(self._manifests[tool_name] for tool_name in sorted(self._manifests))
