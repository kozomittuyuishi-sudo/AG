"""
brain_dispatcher.py
===================

AG Brain Interface & Dispatcher

Role:
- Connect Cognitive Engine payloads to authorized Brain providers.
- Enforce a standard BrainResponse contract across all adapters.
- Integrate with the Control Layer for authorization.
- Preserve brain failures as structured results.
- Never convert provider failures into fake successful responses.

Boundaries:
- MUST NOT construct prompts.
- MUST NOT alter cognitive context.
- MUST NOT bypass Control Layer authorization.
- MUST NOT generate user-facing fallback messages.
- MUST NOT decide whether an unsupported capability should be
  communicated to the user.
- Fallback classification belongs to the fallback system.

The dispatcher is responsible for:
    selection
        ↓
    authorization
        ↓
    execution
        ↓
    result normalization
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import time
from typing import Any, Dict, Optional


# ============================================================================
# BRAIN RESPONSE
# ============================================================================

class BrainResponse:
    """
    Standardized result returned by every Brain execution.

    A BrainResponse can represent either:

        SUCCESS
        EMPTY_RESPONSE
        PROVIDER_ERROR
        TIMEOUT
        INVALID_RESPONSE
        UNAVAILABLE
        AUTHORIZATION_ERROR
        EXECUTION_ERROR

    The dispatcher does not generate the final user-facing message.
    """

    VALID_STATUSES = {
        "SUCCESS",
        "EMPTY_RESPONSE",
        "PROVIDER_ERROR",
        "TIMEOUT",
        "INVALID_RESPONSE",
        "UNAVAILABLE",
        "AUTHORIZATION_ERROR",
        "EXECUTION_ERROR",
    }

    def __init__(
        self,
        content: str = "",
        brain_id: str = "",
        provider: str = "",
        mode: str = "QUERY",
        latency_ms: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
        status: str = "SUCCESS",
        error_code: Optional[str] = None,
        error_detail: Optional[str] = None,
    ):
        self.content = content or ""
        self.brain_id = brain_id
        self.provider = provider
        self.mode = mode
        self.latency_ms = latency_ms
        self.metadata = metadata or {}

        status = str(status).upper()

        if status not in self.VALID_STATUSES:
            status = "EXECUTION_ERROR"

        self.status = status
        self.error_code = error_code
        self.error_detail = error_detail

        self.created_at = datetime.now(timezone.utc).isoformat()

    # ---------------------------------------------------------------------

    @property
    def success(self) -> bool:
        """Return True only when a real response was produced."""
        return self.status == "SUCCESS"

    # ---------------------------------------------------------------------

    @property
    def failed(self) -> bool:
        """Return True when the brain execution failed."""
        return not self.success

    # ---------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a serializable representation of the BrainResponse."""

        return {
            "content": self.content,
            "brain_id": self.brain_id,
            "provider": self.provider,
            "mode": self.mode,
            "latency_ms": self.latency_ms,
            "metadata": self.metadata,
            "status": self.status,
            "error_code": self.error_code,
            "error_detail": self.error_detail,
            "created_at": self.created_at,
        }

    # ---------------------------------------------------------------------

    @classmethod
    def success_response(
        cls,
        content: str,
        brain_id: str,
        provider: str,
        mode: str,
        latency_ms: float,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Construct a successful BrainResponse.

        Empty content is NOT considered success.
        """

        if content is None or not str(content).strip():
            return cls(
                content="",
                brain_id=brain_id,
                provider=provider,
                mode=mode,
                latency_ms=latency_ms,
                metadata=metadata,
                status="EMPTY_RESPONSE",
                error_code="EMPTY_RESPONSE",
                error_detail=(
                    "Brain adapter returned empty or None content."
                ),
            )

        return cls(
            content=str(content),
            brain_id=brain_id,
            provider=provider,
            mode=mode,
            latency_ms=latency_ms,
            metadata=metadata,
            status="SUCCESS",
        )

    # ---------------------------------------------------------------------

    @classmethod
    def failure_response(
        cls,
        status: str,
        brain_id: str,
        provider: str,
        mode: str,
        latency_ms: float,
        error_code: str,
        error_detail: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Construct a standardized failed BrainResponse."""

        return cls(
            content="",
            brain_id=brain_id,
            provider=provider,
            mode=mode,
            latency_ms=latency_ms,
            metadata=metadata,
            status=status,
            error_code=error_code,
            error_detail=error_detail,
        )


# ============================================================================
# BASE ADAPTER
# ============================================================================

class BaseBrainAdapter(ABC):
    """
    Abstract contract for all AG Brain adapters.

    Adapters should return BrainResponse objects.

    The dispatcher still normalizes malformed adapter output so one
    broken adapter cannot corrupt the runtime result contract.
    """

    @abstractmethod
    def execute(self, payload: Dict[str, Any]) -> BrainResponse:
        """Execute a cognitive payload."""
        pass


# ============================================================================
# MOCK ADAPTER
# ============================================================================

class MockBrainAdapter(BaseBrainAdapter):
    """
    Deterministic, zero-external-dependency mock adapter.

    Used for:
    - testing
    - offline development
    - explicit mock mode

    It is intentionally not presented as a real cloud/local brain.
    """

    def __init__(
        self,
        brain_id: str = "mock_brain_v1",
        provider: str = "local_mock",
    ):
        self.brain_id = brain_id
        self.provider = provider

    # ---------------------------------------------------------------------

    def execute(self, payload: Dict[str, Any]) -> BrainResponse:

        start_time = time.perf_counter()

        payload = payload or {}

        user_prompt = payload.get("user_prompt", "")
        mode = payload.get("mode", "QUERY")

        sys_context = payload.get(
            "system_context",
            {},
        )

        objective = sys_context.get(
            "active_objective"
        )

        if objective:
            response_text = (
                f"[Mock Brain: {mode}] "
                f"Addressed prompt '{user_prompt}' "
                f"aligned with objective '{objective}'."
            )
        else:
            response_text = (
                f"[Mock Brain: {mode}] "
                f"Processed input: '{user_prompt}'."
            )

        elapsed_ms = (
            time.perf_counter() - start_time
        ) * 1000.0

        return BrainResponse.success_response(
            content=response_text,
            brain_id=self.brain_id,
            provider=self.provider,
            mode=mode,
            latency_ms=round(elapsed_ms, 2),
            metadata={
                "tokens_used": (
                    len(user_prompt.split())
                    + len(response_text.split())
                ),
                "simulated": True,
            },
        )


# ============================================================================
# BRAIN DISPATCHER
# ============================================================================

class BrainDispatcher:
    """
    Orchestrates:

        brain selection
            ↓
        authorization
            ↓
        adapter execution
            ↓
        response normalization

    It does NOT generate user-facing fallback messages.
    """

    def __init__(
        self,
        control_layer: Optional[Any] = None,
    ):
        self.control_layer = control_layer

        self._adapters: Dict[
            str,
            BaseBrainAdapter
        ] = {
            "mock": MockBrainAdapter(),

            # These remain mock adapters until the real adapters are
            # registered by the existing AG runtime.
            #
            # IMPORTANT:
            # Do not pretend these are real providers.
            "local_default": MockBrainAdapter(
                brain_id="local_llama3",
                provider="ollama",
            ),

            "cloud_default": MockBrainAdapter(
                brain_id="cloud_deepseek",
                provider="cloud_api",
            ),
        }

    # ========================================================================
    # ADAPTER REGISTRATION
    # ========================================================================

    def register_adapter(
        self,
        name: str,
        adapter: BaseBrainAdapter,
    ) -> None:
        """
        Register a Brain adapter.

        Invalid registrations are ignored rather than corrupting
        the adapter registry.
        """

        if not name:
            return

        if isinstance(adapter, BaseBrainAdapter):
            self._adapters[name] = adapter

    # ========================================================================
    # BRAIN TARGET RESOLUTION
    # ========================================================================

    def resolve_brain_target(
        self,
        brain_demand: Dict[str, Any],
    ) -> str:
        """
        Determine the target brain key based on cognitive demand.

        This function selects a target.

        It does NOT execute the brain.
        """

        demand = brain_demand or {}

        local_preferred = demand.get(
            "local_preferred",
            True,
        )

        required_tier = demand.get(
            "required_tier",
            "fast_local_or_cloud",
        )

        if (
            required_tier == "cloud_deep_thinking"
            or not local_preferred
        ):
            return "cloud_default"

        return "local_default"

    # ========================================================================
    # CONTROL LAYER AUTHORIZATION
    # ========================================================================

    def _authorize(
        self,
        payload: Dict[str, Any],
        target_key: str,
    ) -> Optional[BrainResponse]:
        """
        Check Control Layer authorization if one exists.

        The dispatcher does not bypass authorization.

        Because the exact Control Layer API is not visible in this file,
        support the common authorization method shapes without inventing
        a new control system.
        """

        if self.control_layer is None:
            return None

        try:
            # Preferred explicit authorization method.
            authorize = getattr(
                self.control_layer,
                "authorize_brain",
                None,
            )

            if callable(authorize):
                authorized = authorize(
                    target_key,
                    payload,
                )

                if authorized is False:
                    return BrainResponse.failure_response(
                        status="AUTHORIZATION_ERROR",
                        brain_id=target_key,
                        provider="control_layer",
                        mode=payload.get(
                            "mode",
                            "QUERY",
                        ),
                        latency_ms=0.0,
                        error_code="BRAIN_NOT_AUTHORIZED",
                        error_detail=(
                            f"Brain target '{target_key}' "
                            "was rejected by Control Layer."
                        ),
                    )

                return None

            # Secondary common authorization shape.
            check = getattr(
                self.control_layer,
                "is_authorized",
                None,
            )

            if callable(check):
                authorized = check(
                    target_key,
                    payload,
                )

                if authorized is False:
                    return BrainResponse.failure_response(
                        status="AUTHORIZATION_ERROR",
                        brain_id=target_key,
                        provider="control_layer",
                        mode=payload.get(
                            "mode",
                            "QUERY",
                        ),
                        latency_ms=0.0,
                        error_code="BRAIN_NOT_AUTHORIZED",
                        error_detail=(
                            f"Brain target '{target_key}' "
                            "was rejected by Control Layer."
                        ),
                    )

                return None

            # No known authorization interface exists.
            #
            # Do not invent a new authorization architecture.
            # Existing behavior is preserved.
            return None

        except Exception as error:

            return BrainResponse.failure_response(
                status="AUTHORIZATION_ERROR",
                brain_id=target_key,
                provider="control_layer",
                mode=payload.get(
                    "mode",
                    "QUERY",
                ),
                latency_ms=0.0,
                error_code="AUTHORIZATION_CHECK_FAILED",
                error_detail=str(error),
            )

    # ========================================================================
    # RESULT NORMALIZATION
    # ========================================================================

    def _normalize_response(
        self,
        response: Any,
        target_key: str,
        mode: str,
        latency_ms: float,
    ) -> BrainResponse:
        """
        Normalize adapter output into BrainResponse.

        This protects the runtime from adapters returning:

        - None
        - strings
        - malformed BrainResponse objects
        - empty responses
        """

        # --------------------------------------------------------------
        # Proper BrainResponse
        # --------------------------------------------------------------

        if isinstance(
            response,
            BrainResponse,
        ):

            # A BrainResponse marked SUCCESS but containing no content
            # is actually an empty-response failure.
            if (
                response.status == "SUCCESS"
                and not response.content.strip()
            ):

                return BrainResponse.failure_response(
                    status="EMPTY_RESPONSE",
                    brain_id=response.brain_id or target_key,
                    provider=response.provider or "unknown",
                    mode=response.mode or mode,
                    latency_ms=latency_ms,
                    error_code="EMPTY_RESPONSE",
                    error_detail=(
                        "Adapter returned a successful "
                        "BrainResponse with empty content."
                    ),
                    metadata=response.metadata,
                )

            return response

        # --------------------------------------------------------------
        # None
        # --------------------------------------------------------------

        if response is None:

            return BrainResponse.failure_response(
                status="EMPTY_RESPONSE",
                brain_id=target_key,
                provider="unknown",
                mode=mode,
                latency_ms=latency_ms,
                error_code="EMPTY_RESPONSE",
                error_detail=(
                    "Brain adapter returned None."
                ),
            )

        # --------------------------------------------------------------
        # Raw string
        # --------------------------------------------------------------

        if isinstance(
            response,
            str,
        ):

            if not response.strip():

                return BrainResponse.failure_response(
                    status="EMPTY_RESPONSE",
                    brain_id=target_key,
                    provider="unknown",
                    mode=mode,
                    latency_ms=latency_ms,
                    error_code="EMPTY_RESPONSE",
                    error_detail=(
                        "Brain adapter returned an empty string."
                    ),
                )

            return BrainResponse.success_response(
                content=response,
                brain_id=target_key,
                provider="unknown",
                mode=mode,
                latency_ms=latency_ms,
            )

        # --------------------------------------------------------------
        # Unknown adapter return type
        # --------------------------------------------------------------

        return BrainResponse.failure_response(
            status="INVALID_RESPONSE",
            brain_id=target_key,
            provider="unknown",
            mode=mode,
            latency_ms=latency_ms,
            error_code="INVALID_ADAPTER_RESPONSE",
            error_detail=(
                f"Adapter returned unsupported type: "
                f"{type(response).__name__}"
            ),
        )

    # ========================================================================
    # ERROR CLASSIFICATION
    # ========================================================================

    @staticmethod
    def _classify_exception(
        error: Exception,
    ) -> tuple[str, str]:
        """
        Convert a provider/adapter exception into a Brain error class.

        Returns:

            (status, error_code)
        """

        error_text = str(error).lower()

        timeout_signals = (
            "timeout",
            "timed out",
            "read timeout",
            "connect timeout",
        )

        if any(
            signal in error_text
            for signal in timeout_signals
        ):
            return (
                "TIMEOUT",
                "BRAIN_TIMEOUT",
            )

        unavailable_signals = (
            "connection refused",
            "connection error",
            "connection aborted",
            "unreachable",
            "dns",
            "network",
        )

        if any(
            signal in error_text
            for signal in unavailable_signals
        ):
            return (
                "UNAVAILABLE",
                "BRAIN_UNAVAILABLE",
            )

        provider_signals = (
            "api",
            "provider",
            "rate limit",
            "quota",
            "billing",
            "credits",
            "insufficient",
            "unauthorized",
            "forbidden",
            "401",
            "402",
            "403",
            "429",
            "500",
            "502",
            "503",
        )

        if any(
            signal in error_text
            for signal in provider_signals
        ):
            return (
                "PROVIDER_ERROR",
                "BRAIN_PROVIDER_ERROR",
            )

        return (
            "EXECUTION_ERROR",
            "BRAIN_EXECUTION_ERROR",
        )

    # ========================================================================
    # DISPATCH
    # ========================================================================

    def dispatch(
        self,
        payload: Dict[str, Any],
    ) -> BrainResponse:
        """
        Dispatch a cognitive payload to the appropriate Brain Adapter.

        Execution contract:

            payload
                ↓
            resolve target
                ↓
            authorize
                ↓
            adapter
                ↓
            normalize result
                ↓
            BrainResponse
        """

        start_time = time.perf_counter()

        payload = payload or {}

        brain_demand = payload.get(
            "brain_demand",
            {},
        )

        mode = payload.get(
            "mode",
            "QUERY",
        )

        # --------------------------------------------------------------
        # Resolve target
        # --------------------------------------------------------------

        try:

            target_key = self.resolve_brain_target(
                brain_demand
            )

        except Exception as error:

            latency_ms = (
                time.perf_counter()
                - start_time
            ) * 1000.0

            return BrainResponse.failure_response(
                status="EXECUTION_ERROR",
                brain_id="dispatcher",
                provider="dispatcher",
                mode=mode,
                latency_ms=round(
                    latency_ms,
                    2,
                ),
                error_code="TARGET_RESOLUTION_FAILED",
                error_detail=str(error),
            )

        # --------------------------------------------------------------
        # Authorization
        # --------------------------------------------------------------

        authorization_error = self._authorize(
            payload,
            target_key,
        )

        if authorization_error is not None:
            authorization_error.latency_ms = round(
                (
                    time.perf_counter()
                    - start_time
                ) * 1000.0,
                2,
            )

            return authorization_error

        # --------------------------------------------------------------
        # Adapter lookup
        # --------------------------------------------------------------

        adapter = self._adapters.get(
            target_key
        )

        if adapter is None:

            latency_ms = (
                time.perf_counter()
                - start_time
            ) * 1000.0

            return BrainResponse.failure_response(
                status="UNAVAILABLE",
                brain_id=target_key,
                provider="dispatcher",
                mode=mode,
                latency_ms=round(
                    latency_ms,
                    2,
                ),
                error_code="BRAIN_ADAPTER_NOT_REGISTERED",
                error_detail=(
                    f"No adapter is registered "
                    f"for brain target '{target_key}'."
                ),
            )

        # --------------------------------------------------------------
        # Execute adapter
        # --------------------------------------------------------------

        try:

            raw_response = adapter.execute(
                payload
            )

        except Exception as error:

            latency_ms = (
                time.perf_counter()
                - start_time
            ) * 1000.0

            status, error_code = (
                self._classify_exception(error)
            )

            return BrainResponse.failure_response(
                status=status,
                brain_id=getattr(
                    adapter,
                    "brain_id",
                    target_key,
                ),
                provider=getattr(
                    adapter,
                    "provider",
                    "unknown",
                ),
                mode=mode,
                latency_ms=round(
                    latency_ms,
                    2,
                ),
                error_code=error_code,
                error_detail=str(error),
            )

        # --------------------------------------------------------------
        # Normalize result
        # --------------------------------------------------------------

        latency_ms = (
            time.perf_counter()
            - start_time
        ) * 1000.0

        return self._normalize_response(
            response=raw_response,
            target_key=target_key,
            mode=mode,
            latency_ms=round(
                latency_ms,
                2,
            ),
        )