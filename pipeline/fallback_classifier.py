"""
fallback_classifier.py
======================
AB Global Response Fallback Classifier

Classifies the reason a response failed and returns a clean,
user-facing fallback message that corresponds to the actual failure
category — without leaking internal error details.

Failure categories
------------------
CAPABILITY_UNAVAILABLE  — AB does not possess the required capability.
INFORMATION_UNAVAILABLE — Required information is not available.
PROCESSING_FAILURE      — AB could not complete processing.
BRAIN_FAILURE           — An available brain/provider failed.
INVALID_RESPONSE        — A brain/system returned empty, malformed, or unusable output.
UNKNOWN_CAPABILITY      — AB cannot determine whether it supports the capability.

Design rules
------------
- No LLM calls.
- Never raises — degrades to PROCESSING_FAILURE on unexpected errors.
- Internal error text is classified; it never propagates to user output.
- Stdlib only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional, Any, Dict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Typed error objects (Step 3)
# ---------------------------------------------------------------------------

@dataclass
class AGError:
    """
    Typed, structured error object for AG internal error propagation.

    The ``message`` field is for internal diagnostics only — it must never
    be surfaced directly in user-facing output.  Use FallbackClassifier
    .get_typed_message() to obtain the appropriate user message.
    """
    domain: str          # 'DIRECTORY' | 'BRAIN' | 'CAPABILITY'
    code: str            # domain-specific error code constant
    message: str         # internal detail — never shown to user
    context: Dict[str, Any] = field(default_factory=dict)


# Directory error codes
DIR_NOT_FOUND          = "NOT_FOUND"
DIR_NOT_A_FILE         = "NOT_A_FILE"
DIR_NOT_A_DIRECTORY    = "NOT_A_DIRECTORY"
DIR_SOURCE_MISSING     = "SOURCE_MISSING"
DIR_OUT_OF_WORKSPACE   = "OUT_OF_WORKSPACE_BOUNDS"

# Brain error codes
BRAIN_TIMEOUT          = "TIMEOUT"
BRAIN_EMPTY_RESPONSE   = "EMPTY_RESPONSE"
BRAIN_INVALID_RESPONSE = "INVALID_RESPONSE"
BRAIN_PROVIDER_ERROR   = "PROVIDER_ERROR"

# Capability error code
CAP_NOT_IMPLEMENTED    = "NOT_IMPLEMENTED"

# ---------------------------------------------------------------------------
# Category constants
# ---------------------------------------------------------------------------

CATEGORY_CAPABILITY_UNAVAILABLE  = "CAPABILITY_UNAVAILABLE"
CATEGORY_INFORMATION_UNAVAILABLE = "INFORMATION_UNAVAILABLE"
CATEGORY_PROCESSING_FAILURE      = "PROCESSING_FAILURE"
CATEGORY_BRAIN_FAILURE           = "BRAIN_FAILURE"
CATEGORY_INVALID_RESPONSE        = "INVALID_RESPONSE"
CATEGORY_UNKNOWN_CAPABILITY      = "UNKNOWN_CAPABILITY"

# User-facing messages for each category.
# Never contain internal error details.
_FALLBACK_MESSAGES = {
    CATEGORY_CAPABILITY_UNAVAILABLE:  "My current capabilities aren't equipped to handle that yet.",
    CATEGORY_INFORMATION_UNAVAILABLE: "I don't currently have the information needed to answer that.",
    CATEGORY_PROCESSING_FAILURE:      "I wasn't able to complete that request with my current systems.",
    CATEGORY_BRAIN_FAILURE:           "I couldn't complete that request with my currently available processing systems.",
    CATEGORY_INVALID_RESPONSE:        "I wasn't able to produce a usable response for that request.",
    CATEGORY_UNKNOWN_CAPABILITY:      "I can't currently determine whether I have that capability.",
}

# ---------------------------------------------------------------------------
# Typed error message lookup table (Step 4)
# ---------------------------------------------------------------------------
# Keyed on (domain, code) → user-facing message template.
# Templates may contain a single ``{target}`` placeholder.

_DOMAIN_CODE_MESSAGES: dict[tuple[str, str], str] = {
    ("DIRECTORY", "NOT_FOUND"):              "{target} wasn't found in the current workspace.",
    ("DIRECTORY", "NOT_A_FILE"):             "That path is a directory, not a file.",
    ("DIRECTORY", "NOT_A_DIRECTORY"):        "That path is a file, not a directory.",
    ("DIRECTORY", "SOURCE_MISSING"):         "The source path doesn't exist in the current workspace.",
    ("DIRECTORY", "OUT_OF_WORKSPACE_BOUNDS"): "That path is outside the active workspace boundary.",
    ("BRAIN",     "TIMEOUT"):                "My cloud reasoning service timed out.",
    ("BRAIN",     "EMPTY_RESPONSE"):         "My cloud reasoning service didn't return a usable response.",
    ("BRAIN",     "INVALID_RESPONSE"):       "The response from my reasoning service was malformed.",
    ("BRAIN",     "PROVIDER_ERROR"):         "My cloud reasoning provider returned an error.",
    ("CAPABILITY", "NOT_IMPLEMENTED"):       "My current capabilities aren't coded for that yet.",
}


# ---------------------------------------------------------------------------
# Classification result
# ---------------------------------------------------------------------------

@dataclass
class FallbackResult:
    """Result returned by FallbackClassifier.classify()."""

    category: str
    """One of the CATEGORY_* constants."""

    user_message: str
    """Clean, user-facing fallback message."""

    internal_reason: Optional[str] = None
    """Original internal error string — for debug logging only, never shown to user."""


# ---------------------------------------------------------------------------
# Signal maps used by _classify_raw_text
# ---------------------------------------------------------------------------

# Signals that indicate the brain/provider itself failed (not a missing
# capability or empty response, but an actual provider/transport error).
_BRAIN_FAILURE_SIGNALS = (
    "brain failed",
    "brain failed:",
    "cloud brain failed",
    "local brain failed",
    "forced cloud brain failed",
    "brain connection failed",
    "api error",
    "apierror",
    "http error",
    "httperror",
    "connectionerror",
    "timeout",
    "timed out",
    "exception",
    "traceback",
    "error:",
    "local error:",
    "cloud error:",
    "status code",
    "502",
    "503",
    "504",
    "401",
    "403",
    "429",
    "quota",
    "rate limit",
    "billing",
    "credits",
    "insufficient",
)

# Signals that indicate an empty / unusable response was returned (but the
# provider didn't necessarily throw an error — it just returned nothing useful).
_INVALID_RESPONSE_SIGNALS = (
    "returned no response",
    "cloud brain returned no response",
    "local brain returned no response",
    "no response",
    "none returned",
    "empty response",
    "unusable response",
    "malformed",
)

# Signals that indicate a capability / feature is not implemented.
_CAPABILITY_UNAVAILABLE_SIGNALS = (
    "not implemented",
    "not currently implemented",
    "capability unavailable",
    "feature not available",
    "not supported",
    "unsupported",
    "cannot handle",
    "can't handle",
    "not equipped",
)

# Signals that indicate missing information (not a provider failure, but the
# data simply isn't there).
_INFORMATION_UNAVAILABLE_SIGNALS = (
    "information unavailable",
    "information not available",
    "data unavailable",
    "data not available",
    "i do not have",
    "no data",
    "not found",
    "cannot find",
    "can't find",
    "context unavailable",
)


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

class FallbackClassifier:
    """
    Classifies a failure reason and returns a clean user-facing message.

    Usage
    -----
    ::

        classifier = FallbackClassifier()
        result = classifier.classify(raw_error="Cloud brain failed: timeout")
        # result.category    → "BRAIN_FAILURE"
        # result.user_message → "I couldn't complete that request ..."
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify(
        self,
        raw_error: Optional[str] = None,
        *,
        category: Optional[str] = None,
    ) -> FallbackResult:
        """
        Classify a failure and return a FallbackResult.

        Parameters
        ----------
        raw_error : str, optional
            The raw internal error/response string (e.g. from ask_brain).
            Used for auto-detection when ``category`` is not provided.
        category : str, optional
            Force a specific category (one of the CATEGORY_* constants).
            When provided, ``raw_error`` is still recorded for debug logging
            but is not used to infer the category.

        Returns
        -------
        FallbackResult
            Always returns a result; never raises.
        """
        try:
            # Log internally regardless of outcome — never shown to user.
            if raw_error:
                logger.debug("[AG FALLBACK] raw_error=%r", raw_error)

            resolved_category = self._resolve_category(raw_error, category)
            user_message = _FALLBACK_MESSAGES.get(
                resolved_category,
                _FALLBACK_MESSAGES[CATEGORY_PROCESSING_FAILURE],
            )
            return FallbackResult(
                category=resolved_category,
                user_message=user_message,
                internal_reason=raw_error,
            )

        except Exception as exc:
            # Safety net — classifier itself must never raise.
            logger.debug("[AG FALLBACK] classifier error: %r", exc)
            return FallbackResult(
                category=CATEGORY_PROCESSING_FAILURE,
                user_message=_FALLBACK_MESSAGES[CATEGORY_PROCESSING_FAILURE],
                internal_reason=str(exc),
            )

    def get_message(self, category: str) -> str:
        """Return the user-facing message for a known category."""
        return _FALLBACK_MESSAGES.get(
            category,
            _FALLBACK_MESSAGES[CATEGORY_PROCESSING_FAILURE],
        )

    def get_typed_message(self, error: AGError) -> str:
        """
        Return the user-facing message for a typed AGError.

        Looks up the (domain, code) pair in ``_DOMAIN_CODE_MESSAGES``.
        Falls back to the PROCESSING_FAILURE generic message if the pair
        is not found.

        The ``{target}`` placeholder in the template is filled with
        ``error.context['target']`` when present, or 'The item' otherwise.

        Parameters
        ----------
        error : AGError
            The typed error to resolve.

        Returns
        -------
        str
            A clean, user-facing message string.
        """
        key = (error.domain, error.code)
        template = _DOMAIN_CODE_MESSAGES.get(key)
        if template is None:
            return _FALLBACK_MESSAGES.get(CATEGORY_PROCESSING_FAILURE)
        target = error.context.get("target", "The item")
        try:
            return template.format(target=target)
        except (KeyError, IndexError):
            return template

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_category(
        self,
        raw_error: Optional[str],
        forced_category: Optional[str],
    ) -> str:
        """Determine the failure category from the provided inputs."""
        # Explicit category override takes priority.
        if forced_category and forced_category in _FALLBACK_MESSAGES:
            return forced_category

        if not raw_error or not isinstance(raw_error, str):
            # No signal at all — generic processing failure.
            return CATEGORY_PROCESSING_FAILURE

        return self._classify_raw_text(raw_error)

    @staticmethod
    def _classify_raw_text(text: str) -> str:
        """
        Inspect the raw error/response text and map it to a category.

        Order of precedence:
        1. Brain/provider transport errors     → BRAIN_FAILURE
        2. Empty/unusable response signals     → INVALID_RESPONSE
        3. Missing capability signals          → CAPABILITY_UNAVAILABLE
        4. Missing information signals         → INFORMATION_UNAVAILABLE
        5. Anything else                       → PROCESSING_FAILURE
        """
        lower = text.strip().lower()

        if any(sig in lower for sig in _BRAIN_FAILURE_SIGNALS):
            return CATEGORY_BRAIN_FAILURE

        if any(sig in lower for sig in _INVALID_RESPONSE_SIGNALS):
            return CATEGORY_INVALID_RESPONSE

        if any(sig in lower for sig in _CAPABILITY_UNAVAILABLE_SIGNALS):
            return CATEGORY_CAPABILITY_UNAVAILABLE

        if any(sig in lower for sig in _INFORMATION_UNAVAILABLE_SIGNALS):
            return CATEGORY_INFORMATION_UNAVAILABLE

        return CATEGORY_PROCESSING_FAILURE


# ---------------------------------------------------------------------------
# Module-level singleton (optional convenience)
# ---------------------------------------------------------------------------

_default_classifier: Optional[FallbackClassifier] = None


def get_fallback_classifier() -> FallbackClassifier:
    """Return the shared FallbackClassifier instance (created on first call)."""
    global _default_classifier
    if _default_classifier is None:
        _default_classifier = FallbackClassifier()
    return _default_classifier


def classify_failure(
    raw_error: Optional[str] = None,
    *,
    category: Optional[str] = None,
) -> FallbackResult:
    """
    Module-level convenience function.

    Equivalent to ``get_fallback_classifier().classify(...)``.
    """
    return get_fallback_classifier().classify(raw_error=raw_error, category=category)
