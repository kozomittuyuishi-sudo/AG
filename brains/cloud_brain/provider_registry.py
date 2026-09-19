"""
cloud_brain/provider_registry.py
=================================
Provider Capability Detector

Maintains a live registry of cloud provider capability profiles.
Each provider profile describes:

    - supported features (streaming, tools, vision, reasoning, etc.)
    - token limits (context window, max output)
    - retry support (whether the provider honours retry-after headers)
    - known restrictions (content policy, rate limits, etc.)

Design principles
-----------------
- No hardcoded numeric values in business logic — all limits live in
  ProviderProfile instances, which are registered at runtime.
- Profiles can be registered, updated, or removed without changing logic.
- The registry ships with sensible built-in profiles for common providers;
  callers may override or extend them.
- Stdlib only. No I/O. No LLM calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, FrozenSet, List, Optional, Set


# ---------------------------------------------------------------------------
# Provider features
# ---------------------------------------------------------------------------

class ProviderFeature(str, Enum):
    """Known capabilities that a provider may or may not support."""
    STREAMING          = "streaming"
    FUNCTION_CALLING   = "function_calling"
    TOOL_USE           = "tool_use"
    VISION             = "vision"
    AUDIO              = "audio"
    REASONING_BLOCKS   = "reasoning_blocks"
    SYSTEM_PROMPT      = "system_prompt"
    JSON_MODE          = "json_mode"
    LOGPROBS           = "logprobs"
    FINE_TUNING        = "fine_tuning"
    EMBEDDINGS         = "embeddings"
    MODERATION         = "moderation"
    RETRY_AFTER_HEADER = "retry_after_header"


# ---------------------------------------------------------------------------
# Provider profile
# ---------------------------------------------------------------------------

@dataclass
class ProviderProfile:
    """
    Immutable (after construction) description of a single provider's
    capabilities and constraints.

    Attributes
    ----------
    provider_id : str
        Unique key used in the registry (e.g. "openrouter", "anthropic").
    display_name : str
        Human-readable label.
    supported_features : FrozenSet[ProviderFeature]
        Features this provider supports.
    context_window : int
        Maximum input tokens (prompt + history).
    max_output_tokens : int
        Maximum tokens the provider will generate in one response.
    default_output_tokens : int
        Tokens requested when no explicit max_tokens is given.
    supports_retry : bool
        Whether the provider sends Retry-After headers on 429s.
    rate_limit_rpm : int
        Requests per minute (0 = unknown / unlimited).
    known_restrictions : List[str]
        Human-readable notes about content policy or API quirks.
    models : List[str]
        Model identifiers available under this provider.
    extra : Dict[str, Any]
        Arbitrary key-value metadata (e.g. pricing tier, region).
    """
    provider_id: str
    display_name: str
    supported_features: FrozenSet[ProviderFeature] = field(
        default_factory=frozenset
    )
    context_window: int = 8192
    max_output_tokens: int = 4096
    default_output_tokens: int = 512
    supports_retry: bool = True
    rate_limit_rpm: int = 0
    known_restrictions: List[str] = field(default_factory=list)
    models: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def supports(self, feature: ProviderFeature) -> bool:
        """Return True if this provider supports the given feature."""
        return feature in self.supported_features

    def clamp_output_tokens(self, requested: int) -> int:
        """
        Clamp ``requested`` to the provider's actual maximum output limit.

        Never returns a value larger than ``max_output_tokens``.
        """
        return min(max(1, requested), self.max_output_tokens)

    def has_model(self, model_id: str) -> bool:
        """Return True if ``model_id`` is in the known models list."""
        return model_id in self.models

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "supported_features": [f.value for f in sorted(self.supported_features)],
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
            "default_output_tokens": self.default_output_tokens,
            "supports_retry": self.supports_retry,
            "rate_limit_rpm": self.rate_limit_rpm,
            "known_restrictions": list(self.known_restrictions),
            "models": list(self.models),
            "extra": dict(self.extra),
        }


# ---------------------------------------------------------------------------
# Built-in provider definitions
# ---------------------------------------------------------------------------

def _openrouter_profile() -> ProviderProfile:
    return ProviderProfile(
        provider_id="openrouter",
        display_name="OpenRouter",
        supported_features=frozenset({
            ProviderFeature.STREAMING,
            ProviderFeature.FUNCTION_CALLING,
            ProviderFeature.TOOL_USE,
            ProviderFeature.VISION,
            ProviderFeature.SYSTEM_PROMPT,
            ProviderFeature.JSON_MODE,
            ProviderFeature.RETRY_AFTER_HEADER,
        }),
        context_window=128_000,
        max_output_tokens=8192,
        default_output_tokens=512,
        supports_retry=True,
        rate_limit_rpm=60,
        known_restrictions=[
            "402 on insufficient credits before request completes",
            "Model availability varies by subscription tier",
            "Some models require explicit reasoning_effort parameter",
        ],
        models=[
            "deepseek/deepseek-v4-flash-0731",
            "deepseek/deepseek-r1",
            "anthropic/claude-3-5-sonnet",
            "anthropic/claude-3-haiku",
            "openai/gpt-4o",
            "openai/gpt-4o-mini",
            "google/gemini-flash-1.5",
            "meta-llama/llama-3.1-70b-instruct",
        ],
    )


def _anthropic_profile() -> ProviderProfile:
    return ProviderProfile(
        provider_id="anthropic",
        display_name="Anthropic",
        supported_features=frozenset({
            ProviderFeature.STREAMING,
            ProviderFeature.TOOL_USE,
            ProviderFeature.VISION,
            ProviderFeature.REASONING_BLOCKS,
            ProviderFeature.SYSTEM_PROMPT,
        }),
        context_window=200_000,
        max_output_tokens=16_000,
        default_output_tokens=1024,
        supports_retry=True,
        rate_limit_rpm=50,
        known_restrictions=[
            "Extended thinking (reasoning blocks) adds latency",
            "Tool use requires separate beta header in some SDK versions",
        ],
        models=[
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
        ],
    )


def _openai_profile() -> ProviderProfile:
    return ProviderProfile(
        provider_id="openai",
        display_name="OpenAI",
        supported_features=frozenset({
            ProviderFeature.STREAMING,
            ProviderFeature.FUNCTION_CALLING,
            ProviderFeature.TOOL_USE,
            ProviderFeature.VISION,
            ProviderFeature.JSON_MODE,
            ProviderFeature.LOGPROBS,
            ProviderFeature.MODERATION,
            ProviderFeature.SYSTEM_PROMPT,
            ProviderFeature.RETRY_AFTER_HEADER,
        }),
        context_window=128_000,
        max_output_tokens=16_384,
        default_output_tokens=1024,
        supports_retry=True,
        rate_limit_rpm=500,
        known_restrictions=[
            "Rate limits vary by tier and model",
            "Older models have smaller context windows",
        ],
        models=[
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4-turbo",
            "gpt-3.5-turbo",
            "o1-preview",
            "o1-mini",
        ],
    )


def _ollama_profile() -> ProviderProfile:
    return ProviderProfile(
        provider_id="ollama",
        display_name="Ollama (Local)",
        supported_features=frozenset({
            ProviderFeature.STREAMING,
            ProviderFeature.SYSTEM_PROMPT,
        }),
        context_window=32_768,
        max_output_tokens=4096,
        default_output_tokens=512,
        supports_retry=False,
        rate_limit_rpm=0,
        known_restrictions=[
            "No internet access — fully local",
            "No tool use without custom function-call wrappers",
            "ANSI escape codes may appear in raw output",
        ],
        models=[
            "llama3.1",
            "llama3.2",
            "mistral",
            "phi3",
            "gemma2",
        ],
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class ProviderRegistry:
    """
    Runtime registry of provider capability profiles.

    Ships with built-in profiles for openrouter, anthropic, openai,
    and ollama.  Callers may register custom providers, override existing
    ones, or remove providers entirely.

    Thread safety: not guaranteed; intended for single-threaded middleware.
    """

    def __init__(self, load_defaults: bool = True) -> None:
        self._profiles: Dict[str, ProviderProfile] = {}
        if load_defaults:
            self._load_defaults()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_defaults(self) -> None:
        for profile in [
            _openrouter_profile(),
            _anthropic_profile(),
            _openai_profile(),
            _ollama_profile(),
        ]:
            self._profiles[profile.provider_id] = profile

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, profile: ProviderProfile) -> None:
        """Register or replace a provider profile."""
        if not isinstance(profile, ProviderProfile):
            raise TypeError(f"Expected ProviderProfile, got {type(profile)}")
        self._profiles[profile.provider_id] = profile

    def get(self, provider_id: str) -> Optional[ProviderProfile]:
        """Return the profile for ``provider_id``, or None if unknown."""
        return self._profiles.get(provider_id)

    def require(self, provider_id: str) -> ProviderProfile:
        """
        Return the profile for ``provider_id``.

        Raises
        ------
        KeyError
            If the provider is not registered.
        """
        profile = self._profiles.get(provider_id)
        if profile is None:
            raise KeyError(
                f"Provider '{provider_id}' is not registered. "
                f"Known providers: {sorted(self._profiles.keys())}"
            )
        return profile

    def remove(self, provider_id: str) -> bool:
        """Remove a provider. Returns True if it existed."""
        return self._profiles.pop(provider_id, None) is not None

    def all_providers(self) -> List[ProviderProfile]:
        """Return all registered profiles in registration order."""
        return list(self._profiles.values())

    def provider_ids(self) -> List[str]:
        """Return all registered provider IDs."""
        return list(self._profiles.keys())

    def supports_feature(
        self, provider_id: str, feature: ProviderFeature
    ) -> bool:
        """
        Return True if the provider supports ``feature``.

        Returns False (rather than raising) if the provider is unknown.
        """
        profile = self._profiles.get(provider_id)
        if profile is None:
            return False
        return profile.supports(feature)

    def providers_with_feature(
        self, feature: ProviderFeature
    ) -> List[ProviderProfile]:
        """Return all providers that support ``feature``."""
        return [p for p in self._profiles.values() if p.supports(feature)]

    def find_model(self, model_id: str) -> List[ProviderProfile]:
        """Return all providers that list ``model_id`` in their models."""
        return [p for p in self._profiles.values() if p.has_model(model_id)]

    def __len__(self) -> int:
        return len(self._profiles)

    def __contains__(self, provider_id: str) -> bool:
        return provider_id in self._profiles
