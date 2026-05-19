"""Fail-closed provider probe placeholder for future approved TTS live runs."""

from __future__ import annotations


class ProviderProbeDisabled(RuntimeError):
    """Raised when a live provider probe is requested without approval."""


def fail_closed() -> None:
    raise ProviderProbeDisabled(
        "live provider probing is disabled in this spike-local harness; "
        "use dry-run until a separate human-approved live execution path exists"
    )
