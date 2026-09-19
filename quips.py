"""QUIPS — deterministic request structure analysis for AG.

QUIPS identifies whether an input contains independent request units.  It
does not answer requests, perform operations, call an LLM, or replace AG's
existing intent routing.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Callable, Dict, List, Optional, Tuple

from self_info.query_router import (
    ROUTE_ARCHITECTURE,
    ROUTE_CAPABILITIES,
    ROUTE_IDENTITY,
    ROUTE_LIMITATIONS,
    ROUTE_OPERATIONAL,
    route_query,
)


class RequestCategory:
    SELF_INFO = "SELF_INFO"
    FILE_OPERATION = "FILE_OPERATION"
    MEMORY = "MEMORY"
    TASK = "TASK"
    PROJECT = "PROJECT"
    WORKSPACE_QUERY = "WORKSPACE_QUERY"
    EXPLANATION = "EXPLANATION"
    GENERAL = "GENERAL"
    UNKNOWN = "UNKNOWN"


class RoutingDecision:
    """Downstream ownership selected by deterministic request analysis."""

    DETERMINISTIC_SELF_INFO = "DETERMINISTIC_SELF_INFO"
    LEGACY_INTENT_ROUTER = "LEGACY_INTENT_ROUTER"
    LLM_FALLBACK = "LLM_FALLBACK"


@dataclass(frozen=True)
class RequestUnit:
    """One independently routable request extracted from user input."""

    original_text: str
    text: str
    index: int
    is_compound: bool
    category: str
    intent: str
    confidence: str
    legacy_intent: Optional[str] = None
    routing_decision: str = RoutingDecision.LEGACY_INTENT_ROUTER
    context_references: Tuple[str, ...] = ()
    depends_on: Tuple[int, ...] = ()
    processing_status: str = "PENDING"
    result_state: Optional[str] = None

    @property
    def route_intent(self) -> Optional[str]:
        """Backward-compatible name for the legacy single-request route."""
        return self.legacy_intent

    def to_dict(self) -> Dict[str, Optional[str]]:
        return asdict(self)


@dataclass(frozen=True)
class UnitProcessingResult:
    """Outcome recorded by the router after a request unit is processed."""

    unit_index: int
    handler: str
    status: str
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Optional[str]]:
        return asdict(self)


@dataclass(frozen=True)
class QUIPSResult:
    """Structured, side-effect-free result from :func:`analyze_request`."""

    original_text: str
    is_compound: bool
    requests: List[RequestUnit]

    @property
    def request_count(self) -> int:
        return len(self.requests)

    def to_dict(self) -> Dict[str, object]:
        return {
            "original_text": self.original_text,
            "is_compound": self.is_compound,
            "request_count": self.request_count,
            "requests": [request.to_dict() for request in self.requests],
        }


_BOUNDARY = re.compile(r"\s*,\s*(?:and\s+)?|\s+(?:and|also|then)\s+", re.IGNORECASE)
_REQUEST_START = re.compile(
    r"^(?:what|who|where|when|why|how|tell|describe|explain|list|show|"
    r"create|make|write|read|open|delete|remove|rename|move|copy|find|"
    r"search|remember|recall|add|complete|finish|mark|set|switch)\b",
    re.IGNORECASE,
)
_WORKFLOW = re.compile(
    r"\b(?:create|make)\s+(?:a\s+)?(?:folder|directory)\b.*\band\s+"
    r"(?:put|place|move|copy|create|write)\b.*\b(?:inside|into|there)\b",
    re.IGNORECASE,
)


def analyze_request(
    user_input: str,
    intent_classifier: Optional[Callable[[str], str]] = None,
) -> QUIPSResult:
    """Return a deterministic structural analysis of *user_input*.

    ``intent_classifier`` is normally AG's existing ``detect_intent``.  It is
    injected to keep QUIPS independent from ``Ag.py`` and to avoid a circular
    import.  QUIPS records that existing route in ``route_intent``; it does not
    duplicate the legacy intent system.
    """
    text = (user_input or "").strip()
    parts = _split_independent_requests(text)
    is_compound = len(parts) > 1
    units = [
        _classify_unit(text, part, index, is_compound, intent_classifier)
        for index, part in enumerate(parts)
    ]
    return QUIPSResult(original_text=text, is_compound=is_compound, requests=units)


def _split_independent_requests(text: str) -> List[str]:
    """Split only obvious coordinated requests; keep operational workflows whole."""
    if not text or _WORKFLOW.search(text):
        return [text] if text else []

    candidates = [part.strip(" ,") for part in _BOUNDARY.split(text) if part.strip(" ,")]
    if len(candidates) < 2 or not all(_REQUEST_START.search(part) for part in candidates):
        return [text]
    return candidates


def _classify_unit(
    original_text: str,
    text: str,
    index: int,
    is_compound: bool,
    intent_classifier: Optional[Callable[[str], str]],
) -> RequestUnit:
    normalized = text.lower().strip().rstrip("?!. ")
    category, intent, routing_decision = _classify_broad_category(normalized)
    legacy_intent = intent_classifier(text) if intent_classifier is not None else None
    depends_on = (index - 1,) if index > 0 and intent == "EXPLAIN_RESULT" else ()
    return RequestUnit(
        original_text=original_text,
        text=text,
        index=index,
        is_compound=is_compound,
        category=category,
        intent=intent,
        confidence="high" if category != RequestCategory.UNKNOWN else "low",
        legacy_intent=legacy_intent,
        routing_decision=routing_decision,
        context_references=_extract_context_references(normalized),
        depends_on=depends_on,
    )


def _classify_broad_category(text: str) -> tuple[str, str, str]:
    """Classify ownership before consulting the legacy flat intent router.

    Self-info ownership is delegated to the existing self-info query router,
    which remains the single source for self-info semantics.  Once ownership
    is known, it cannot be overwritten by an unrecognised legacy intent.
    """
    self_info = route_query(text)
    self_info_intents = {
        ROUTE_IDENTITY: "IDENTITY",
        ROUTE_CAPABILITIES: "CAPABILITIES",
        ROUTE_LIMITATIONS: "LIMITATIONS",
        ROUTE_ARCHITECTURE: "ARCHITECTURE",
        ROUTE_OPERATIONAL: "BRAINS" if self_info.sub_topic == "brains" else "OPERATIONAL",
    }
    if self_info.is_self_info and self_info.category in self_info_intents:
        return (
            RequestCategory.SELF_INFO,
            self_info_intents[self_info.category],
            RoutingDecision.DETERMINISTIC_SELF_INFO,
        )

    if re.search(r"\b(?:create|make|write|read|open|delete|remove|rename|move|copy)\b.*"
                 r"(?:\bfile\b|\bfolder\b|\bdirectory\b|\.[a-z0-9]{1,8}\b)", text):
        if re.search(r"\b(?:create|make)\b.*\b(?:folder|directory)\b", text):
            return RequestCategory.FILE_OPERATION, "CREATE_FOLDER", RoutingDecision.LEGACY_INTENT_ROUTER
        if re.search(r"\b(?:create|make)\b", text):
            return RequestCategory.FILE_OPERATION, "CREATE_FILE", RoutingDecision.LEGACY_INTENT_ROUTER
        return RequestCategory.FILE_OPERATION, "FILE_OPERATION", RoutingDecision.LEGACY_INTENT_ROUTER
    if re.search(r"\b(?:remember|recall|memory|memories)\b", text):
        return RequestCategory.MEMORY, "MEMORY", RoutingDecision.LEGACY_INTENT_ROUTER
    if re.search(r"\b(?:current|active|my)\s+workspace\b|\bwhere am i\b", text):
        return RequestCategory.WORKSPACE_QUERY, "WORKSPACE_QUERY", RoutingDecision.LEGACY_INTENT_ROUTER
    if re.search(r"\b(?:tell|explain|describe)\b.*\b(?:what|which|the)\b.*"
                 r"\b(?:created|made|wrote|changed|result|results|it)\b", text):
        return RequestCategory.EXPLANATION, "EXPLAIN_RESULT", RoutingDecision.LLM_FALLBACK
    if re.search(r"\b(?:task|tasks|todo|to-do|complete|finish)\b", text):
        return RequestCategory.TASK, "TASK", RoutingDecision.LEGACY_INTENT_ROUTER
    if re.search(r"\b(?:project|milestone|version|phase|objective|progress)\b", text):
        return RequestCategory.PROJECT, "PROJECT", RoutingDecision.LEGACY_INTENT_ROUTER
    if text:
        return RequestCategory.GENERAL, "GENERAL_REASONING", RoutingDecision.LLM_FALLBACK
    return RequestCategory.UNKNOWN, "UNKNOWN", RoutingDecision.LLM_FALLBACK


def _extract_context_references(text: str) -> Tuple[str, ...]:
    """Preserve reference words for the conversation layer; never resolve them."""
    phrases = ("the local one", "the cloud one", "the other one")
    found = [phrase for phrase in phrases if phrase in text]
    found.extend(word for word in ("it", "this", "that") if re.search(rf"\b{word}\b", text))
    return tuple(found)
