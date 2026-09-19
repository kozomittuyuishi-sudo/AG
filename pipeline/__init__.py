# pipeline — Pipeline execution and coordination.
from pipeline.fallback_classifier import (
    FallbackClassifier,
    FallbackResult,
    classify_failure,
    get_fallback_classifier,
    CATEGORY_CAPABILITY_UNAVAILABLE,
    CATEGORY_INFORMATION_UNAVAILABLE,
    CATEGORY_PROCESSING_FAILURE,
    CATEGORY_BRAIN_FAILURE,
    CATEGORY_INVALID_RESPONSE,
    CATEGORY_UNKNOWN_CAPABILITY,
)

__all__ = [
    "FallbackClassifier",
    "FallbackResult",
    "classify_failure",
    "get_fallback_classifier",
    "CATEGORY_CAPABILITY_UNAVAILABLE",
    "CATEGORY_INFORMATION_UNAVAILABLE",
    "CATEGORY_PROCESSING_FAILURE",
    "CATEGORY_BRAIN_FAILURE",
    "CATEGORY_INVALID_RESPONSE",
    "CATEGORY_UNKNOWN_CAPABILITY",
]
