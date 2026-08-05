"""Isolated Qwen Audio Realtime Web Spike.

Nothing in the voice-agent runtime imports or starts this package.
"""

from .capability_profile import (
    CapabilityProfile,
    fake_capability_profile,
    qwen_capability_profile,
)
from .fake_provider import FakeProviderConfig, FakeRealtimeProvider
from .provider_adapter import (
    CredentialHandle,
    NormalizedProviderEvent,
    QwenRealtimeProvider,
)
from .server import create_app
from .session_bridge import BridgeConfig, SessionBridge

__all__ = [
    "BridgeConfig",
    "CapabilityProfile",
    "CredentialHandle",
    "FakeProviderConfig",
    "FakeRealtimeProvider",
    "NormalizedProviderEvent",
    "QwenRealtimeProvider",
    "SessionBridge",
    "create_app",
    "fake_capability_profile",
    "qwen_capability_profile",
]
