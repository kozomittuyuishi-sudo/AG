"""
brain_dispatcher.py
===================
AG Brain Interface & Dispatcher (Phase A)

Role:
- Connects Cognitive Engine payloads (Brain Demand + Context + Prompt)
  to authorized Brain providers (local models, cloud LLMs, or mock test brains).
- Enforces standard execution contracts (`BrainResponse`) across all models.
- Integrates with Control Layer to ensure authorized model usage.

Boundaries:
- MUST NOT construct prompts or alter cognitive context (handled by Cognitive Engine).
- MUST NOT bypass Control Layer authorization.
- Provides fallback to MockBrainAdapter when external APIs are unavailable or during testing.
"""

from abc import ABC, abstractmethod
from copy import deepcopy
from datetime import datetime, timezone
import time
from typing import Any, Dict, Optional


class BrainResponse:
    """Standardized result returned by any Brain execution."""

    def __init__(
        self,
        content: str,
        brain_id: str,
        provider: str,
        mode: str,
        latency_ms: float,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.content = content
        self.brain_id = brain_id
        self.provider = provider
        self.mode = mode
        self.latency_ms = latency_ms
        self.metadata = metadata or {}
        self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "brain_id": self.brain_id,
            "provider": self.provider,
            "mode": self.mode,
            "latency_ms": self.latency_ms,
            "metadata": self.metadata,
            "created_at": self.created_at
        }


class BaseBrainAdapter(ABC):
    """Abstract contract for all AG Brain adapters (Local, Cloud, Mock)."""

    @abstractmethod
    def execute(self, payload: Dict[str, Any]) -> BrainResponse:
        """Executes a cognitive payload and returns a standardized BrainResponse."""
        pass


class MockBrainAdapter(BaseBrainAdapter):
    """Deterministic, zero-external-dependency mock adapter for testing & offline mode."""

    def __init__(self, brain_id: str = "mock_brain_v1", provider: str = "local_mock"):
        self.brain_id = brain_id
        self.provider = provider

    def execute(self, payload: Dict[str, Any]) -> BrainResponse:
        start_time = time.perf_counter()
        user_prompt = payload.get("user_prompt", "")
        mode = payload.get("mode", "QUERY")
        sys_context = payload.get("system_context", {})

        # Deterministic mock response generation
        objective = sys_context.get("active_objective")
        if objective:
            response_text = f"[Mock Brain: {mode}] Addressed prompt '{user_prompt}' aligned with objective '{objective}'."
        else:
            response_text = f"[Mock Brain: {mode}] Processed input: '{user_prompt}'."

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        return BrainResponse(
            content=response_text,
            brain_id=self.brain_id,
            provider=self.provider,
            mode=mode,
            latency_ms=round(elapsed_ms, 2),
            metadata={
                "tokens_used": len(user_prompt.split()) + len(response_text.split()),
                "simulated": True
            }
        )


class BrainDispatcher:
    """Orchestrates model selection, Control Layer checks, and dispatch execution."""

    def __init__(self, control_layer: Optional[Any] = None):
        self.control_layer = control_layer
        self._adapters: Dict[str, BaseBrainAdapter] = {
            "mock": MockBrainAdapter(),
            "local_default": MockBrainAdapter(brain_id="local_llama3", provider="ollama"),
            "cloud_default": MockBrainAdapter(brain_id="cloud_deepseek", provider="cloud_api")
        }

    def register_adapter(self, name: str, adapter: BaseBrainAdapter) -> None:
        """Register a custom brain adapter."""
        if isinstance(adapter, BaseBrainAdapter):
            self._adapters[name] = adapter

    def resolve_brain_target(self, brain_demand: Dict[str, Any]) -> str:
        """
        Determines the target brain key based on cognitive demand and Control Layer.
        """
        demand = brain_demand or {}
        local_preferred = demand.get("local_preferred", True)
        required_tier = demand.get("required_tier", "fast_local_or_cloud")

        if required_tier == "cloud_deep_thinking" or not local_preferred:
            return "cloud_default"
        return "local_default"

    def dispatch(self, payload: Dict[str, Any]) -> BrainResponse:
        """
        Dispatches a cognitive payload to the appropriate Brain Adapter.
        """
        payload = payload or {}
        brain_demand = payload.get("brain_demand", {})
        
        # Determine brain target key
        target_key = self.resolve_brain_target(brain_demand)

        # Fallback to default mock if target not found
        adapter = self._adapters.get(target_key, self._adapters["mock"])

        # Execute call
        return adapter.execute(payload)