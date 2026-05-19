"""Fail-closed provider probe for the Thinker / Composer eval harness."""

from __future__ import annotations


class ProviderProbeDisabled(RuntimeError):
    """Raised when a live provider probe is requested without explicit approval."""


def fail_closed() -> None:
    raise ProviderProbeDisabled(
        "live Thinker / Composer provider probe is disabled; keep this step metadata-only"
    )
