"""
core/conversation_context.py
=============================
AG Phase 2 — ConversationContext

Replaces the single ``current_topic`` string with a rich, structured
representation of the active conversational state.

The ContextResolver reads from ConversationContext to decide how to
rewrite incomplete questions.  WorkingMemory owns the authoritative
instance and updates it after every turn.

Design principles:
    - Mutable state object — the pipeline mutates it in-place as the
      conversation progresses.
    - ``active_entities`` references the names of the most recently
      active entities (the EntityRegistry holds the full objects).
    - ``history`` is a bounded list of ConversationFrame dicts so the
      resolver can read past turns without importing WorkingMemory.
    - Deterministic, in-memory, stdlib only.  No LLM calls.
"""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

MAX_HISTORY = 20   # maximum number of frames kept in context history


class ConversationContext:
    """
    Structured representation of the active conversational state.

    Attributes
    ----------
    active_entities : List[str]
        Canonical names of the most recently mentioned entities,
        ordered from oldest to newest (last = most recent).
    active_topics : List[str]
        Topic labels currently in scope (first = oldest, last = most recent).
    current_goal : Optional[str]
        What the user is trying to accomplish in this thread, if known.
    last_answer : Optional[str]
        The most recently delivered assistant response (truncated to 400 chars).
    history : Deque[Dict[str, Any]]
        Bounded FIFO of ConversationFrame dicts, oldest first.
    active_thread : Optional[str]
        Identifier of the current thread of conversation (e.g. a topic label
        or a ConversationFrame.frame_id).
    """

    def __init__(self) -> None:
        self.active_entities: List[str] = []
        self.active_topics: List[str] = []
        self.current_goal: Optional[str] = None
        self.last_answer: Optional[str] = None
        self.history: Deque[Dict[str, Any]] = deque(maxlen=MAX_HISTORY)
        self.active_thread: Optional[str] = None
        self._updated_at: str = _now()

    # ------------------------------------------------------------------
    # Entity tracking
    # ------------------------------------------------------------------

    def add_entity(self, name: str) -> "ConversationContext":
        """
        Add an entity name to the active entity list.
        Duplicates are moved to the end (most-recent position).
        """
        clean = str(name).strip()
        if not clean:
            return self
        if clean in self.active_entities:
            self.active_entities.remove(clean)
        self.active_entities.append(clean)
        # Keep at most 10 recent entities
        if len(self.active_entities) > 10:
            self.active_entities = self.active_entities[-10:]
        self._touch()
        return self

    def most_recent_entity(self) -> Optional[str]:
        """Return the most recently active entity name, or None."""
        return self.active_entities[-1] if self.active_entities else None

    # ------------------------------------------------------------------
    # Topic tracking
    # ------------------------------------------------------------------

    def push_topic(self, topic: str) -> "ConversationContext":
        """
        Add a topic to the active topic list.
        Duplicates are moved to the end (most-recent position).
        """
        clean = str(topic).strip()
        if not clean:
            return self
        if clean in self.active_topics:
            self.active_topics.remove(clean)
        self.active_topics.append(clean)
        if len(self.active_topics) > 10:
            self.active_topics = self.active_topics[-10:]
        self._touch()
        return self

    def current_topic(self) -> Optional[str]:
        """Return the most recently active topic, or None."""
        return self.active_topics[-1] if self.active_topics else None

    # ------------------------------------------------------------------
    # Answer / goal tracking
    # ------------------------------------------------------------------

    def set_last_answer(self, answer: str) -> "ConversationContext":
        """Store a truncated copy of the most recent assistant response."""
        text = str(answer).strip()
        self.last_answer = text[:400] + ("..." if len(text) > 400 else "")
        self._touch()
        return self

    def set_goal(self, goal: str) -> "ConversationContext":
        """Set the inferred goal for the current thread."""
        self.current_goal = str(goal).strip() or None
        self._touch()
        return self

    def set_thread(self, thread_id: str) -> "ConversationContext":
        """Set the active thread identifier."""
        self.active_thread = str(thread_id).strip() or None
        self._touch()
        return self

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def add_frame(self, frame_dict: Dict[str, Any]) -> "ConversationContext":
        """Append a ConversationFrame dict (from ``frame.to_dict()``) to history."""
        if isinstance(frame_dict, dict):
            self.history.append(deepcopy(frame_dict))
        self._touch()
        return self

    def recent_frames(self, n: int = 5) -> List[Dict[str, Any]]:
        """Return the n most recent frames (most recent last)."""
        frames = list(self.history)
        return frames[-n:]

    def last_frame(self) -> Optional[Dict[str, Any]]:
        """Return the most recent frame, or None."""
        return deepcopy(self.history[-1]) if self.history else None

    # ------------------------------------------------------------------
    # Bulk update (called after every completed turn)
    # ------------------------------------------------------------------

    def update_from_frame(self, frame_dict: Dict[str, Any]) -> "ConversationContext":
        """
        Update the context from a completed ConversationFrame dict.

        This is the primary integration point: after each turn, WorkingMemory
        calls this method so the context reflects the latest state.

        :param frame_dict: A dict as returned by ``ConversationFrame.to_dict()``.
        """
        if not isinstance(frame_dict, dict):
            return self

        # Update topics from frame
        for topic in frame_dict.get("topics", []):
            if topic:
                self.push_topic(topic)

        # Update entities from frame
        for ent in frame_dict.get("entities", []):
            name = ent.get("name") if isinstance(ent, dict) else str(ent)
            if name:
                self.add_entity(name)

        # Update last answer
        response = frame_dict.get("assistant_response")
        if response:
            self.set_last_answer(response)

        # Update thread to the frame's id
        frame_id = frame_dict.get("frame_id")
        if frame_id:
            self.set_thread(frame_id)

        # Add to history
        self.add_frame(frame_dict)
        return self

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> "ConversationContext":
        """Clear all state, starting a fresh conversational context."""
        self.active_entities = []
        self.active_topics = []
        self.current_goal = None
        self.last_answer = None
        self.history = deque(maxlen=MAX_HISTORY)
        self.active_thread = None
        self._touch()
        return self

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "active_entities": list(self.active_entities),
            "active_topics": list(self.active_topics),
            "current_goal": self.current_goal,
            "last_answer": self.last_answer,
            "history": [deepcopy(f) for f in self.history],
            "active_thread": self.active_thread,
            "updated_at": self._updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationContext":
        ctx = cls()
        ctx.active_entities = list(data.get("active_entities", []))
        ctx.active_topics = list(data.get("active_topics", []))
        ctx.current_goal = data.get("current_goal")
        ctx.last_answer = data.get("last_answer")
        ctx.active_thread = data.get("active_thread")
        ctx._updated_at = data.get("updated_at", _now())
        for frame in data.get("history", []):
            ctx.history.append(deepcopy(frame))
        return ctx

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _touch(self) -> None:
        self._updated_at = _now()

    def __repr__(self) -> str:
        return (
            f"ConversationContext("
            f"entities={self.active_entities!r}, "
            f"topic={self.current_topic()!r}, "
            f"frames={len(self.history)})"
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
