"""
core/conversation_frame.py
==========================
AG Phase 2 — ConversationFrame

Replaces raw ``{"question": ..., "answer": ...}`` dicts in the discussion
buffer with structured, queryable conversation turn records.

Every completed pipeline turn that produces a brain response should be
stored as a ConversationFrame.  The frame captures not just what was said
but *how it was understood* — the resolved question, the intent, the
active entities, and the confidence.  This makes every past turn
introspectable by the ContextResolver.

Design principles:
    - Immutable after creation (all fields set in __init__).
      Use ``with_response()`` to produce a new frame when the response
      arrives (functional update pattern).
    - Deterministic, in-memory, stdlib only.  No LLM calls.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid


class ConversationFrame:
    """
    Structured record of one conversational turn.

    Attributes
    ----------
    frame_id : str
        Unique identifier for this frame (auto-generated).
    timestamp : str
        ISO-8601 UTC timestamp when the frame was created.

    user_question : str
        The raw user utterance.
    resolved_question : str
        The context-enriched question that was actually sent to the Brain.
        Equals ``user_question`` when no resolution was performed.
    intent : Optional[str]
        The classified intent label for this turn.
    entities : List[Dict[str, Any]]
        Lightweight entity snapshots active during this turn.
        Each dict: {"name": str, "type": str, "confidence": float}.
    topics : List[str]
        Topic labels active during this turn (may include the current
        topic and any shift targets detected).
    confidence : float
        The context-resolution confidence for this turn (0.0–1.0).
    assistant_response : Optional[str]
        The final, verified response returned to the user.
        None if the frame was created before the response was available.
    was_clarification : bool
        True if this turn resulted in a clarification request rather than
        a brain response.
    metadata : Dict[str, Any]
        Arbitrary extra data (e.g. brain mode used, response time).
    """

    def __init__(
        self,
        user_question: str,
        resolved_question: Optional[str] = None,
        intent: Optional[str] = None,
        entities: Optional[List[Dict[str, Any]]] = None,
        topics: Optional[List[str]] = None,
        confidence: float = 1.0,
        assistant_response: Optional[str] = None,
        was_clarification: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.frame_id: str = f"frame_{uuid.uuid4().hex[:12]}"
        self.timestamp: str = datetime.now(timezone.utc).isoformat()

        self.user_question: str = str(user_question).strip()
        self.resolved_question: str = (
            str(resolved_question).strip() if resolved_question else self.user_question
        )
        self.intent: Optional[str] = intent
        self.entities: List[Dict[str, Any]] = deepcopy(entities or [])
        self.topics: List[str] = list(topics or [])
        self.confidence: float = max(0.0, min(1.0, float(confidence)))
        self.assistant_response: Optional[str] = assistant_response
        self.was_clarification: bool = bool(was_clarification)
        self.metadata: Dict[str, Any] = dict(metadata or {})

    # ------------------------------------------------------------------
    # Functional update
    # ------------------------------------------------------------------

    def with_response(self, response: str, metadata_updates: Optional[Dict[str, Any]] = None) -> "ConversationFrame":
        """
        Return a new ConversationFrame identical to this one but with
        ``assistant_response`` set.  Does not mutate the original frame.

        :param response: The verified response text.
        :param metadata_updates: Optional extra metadata to merge in.
        :returns: New ConversationFrame with response filled in.
        """
        updated_meta = dict(self.metadata)
        if metadata_updates:
            updated_meta.update(metadata_updates)

        return ConversationFrame(
            user_question=self.user_question,
            resolved_question=self.resolved_question,
            intent=self.intent,
            entities=deepcopy(self.entities),
            topics=list(self.topics),
            confidence=self.confidence,
            assistant_response=str(response),
            was_clarification=self.was_clarification,
            metadata=updated_meta,
        )

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def has_response(self) -> bool:
        """Return True if the assistant response has been set."""
        return self.assistant_response is not None

    def get_entity_names(self) -> List[str]:
        """Return the canonical names of all entities in this frame."""
        return [e.get("name", "") for e in self.entities if e.get("name")]

    def get_primary_topic(self) -> Optional[str]:
        """Return the first topic in the topic list, or None."""
        return self.topics[0] if self.topics else None

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "timestamp": self.timestamp,
            "user_question": self.user_question,
            "resolved_question": self.resolved_question,
            "intent": self.intent,
            "entities": deepcopy(self.entities),
            "topics": list(self.topics),
            "confidence": self.confidence,
            "assistant_response": self.assistant_response,
            "was_clarification": self.was_clarification,
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationFrame":
        """Reconstruct a ConversationFrame from a ``to_dict()`` snapshot."""
        frame = cls(
            user_question=data.get("user_question", ""),
            resolved_question=data.get("resolved_question"),
            intent=data.get("intent"),
            entities=data.get("entities", []),
            topics=data.get("topics", []),
            confidence=data.get("confidence", 1.0),
            assistant_response=data.get("assistant_response"),
            was_clarification=data.get("was_clarification", False),
            metadata=data.get("metadata", {}),
        )
        frame.frame_id = data.get("frame_id", frame.frame_id)
        frame.timestamp = data.get("timestamp", frame.timestamp)
        return frame

    @classmethod
    def from_thought(cls, thought: Any) -> "ConversationFrame":
        """
        Build a ConversationFrame from a completed Thought object.

        Accepts any object that exposes the Thought attribute names so
        that there is no hard import dependency in this module.
        """
        return cls(
            user_question=getattr(thought, "raw_input", ""),
            resolved_question=getattr(thought, "resolved_input", None),
            intent=getattr(thought, "intent", None),
            entities=deepcopy(getattr(thought, "detected_entities", [])),
            topics=[],  # populated by the caller using active context topics
            confidence=getattr(thought, "confidence", 1.0),
            assistant_response=getattr(thought, "final_response", None),
            was_clarification=getattr(thought, "ask_for_clarification", False),
        )

    def __repr__(self) -> str:
        snippet = self.user_question[:40].rstrip()
        has_resp = "+" if self.has_response() else "-"
        return (
            f"ConversationFrame(id={self.frame_id!r}, "
            f"intent={self.intent!r}, conf={self.confidence:.2f}, "
            f"resp={has_resp}, q={snippet!r})"
        )
