"""
working_memory.py
=================
AG Working Memory (Phase A)

Role:
- Ephemeral, in-memory cognitive workspace ("RAM") for AG.
- Tracks active session objectives, current tasks, conversation references,
  temporary facts, reasoning scratchpad notes, decision cache, and pending states.
- Assembles unified context for the future Cognitive Engine via `build_context()`.

Boundaries:
- MUST NOT write to persistent storage files (e.g., memory.json, tasks.json).
- MUST NOT execute simulations, authorization checks, or direct LLM calls.
- Clears automatically upon reset or expiration.
"""

from copy import deepcopy
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
import uuid


class WorkingMemory:
    """Ephemeral cognitive RAM for AG session execution."""

    def __init__(self, session_id: Optional[str] = None, ttl_seconds: Optional[int] = 3600):
        """
        Initialize Working Memory session.
        
        :param session_id: Unique string ID for session. Auto-generated if None.
        :param ttl_seconds: Seconds until session expires. None for no expiry.
        """
        self._init_state(session_id=session_id, ttl_seconds=ttl_seconds)

    def _init_state(self, session_id: Optional[str] = None, ttl_seconds: Optional[int] = 3600) -> None:
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(seconds=ttl_seconds)) if ttl_seconds is not None else None

        self._state: Dict[str, Any] = {
            "session_id": session_id or f"wm_sess_{uuid.uuid4().hex[:10]}",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "current_objective": None,
            "current_task": None,
            "current_topic": None,
            "conversation_reference": {},
            "temporary_context": {},
            "retrieved_memories": [],
            "temporary_facts": {},
            "reasoning_scratchpad": [],
            "pending_questions": [],
            "pending_confirmation": None,
            "pending_action": None,
            "decision_cache": {},
            "expires_at": expires_at.isoformat() if expires_at else None
        }

    def _touch(self) -> None:
        """Update last modified timestamp."""
        self._state["updated_at"] = datetime.now(timezone.utc).isoformat()

    # ------------------------------------------------------------------
    # Session Management & Expiry
    # ------------------------------------------------------------------

    def create_session(self, session_id: Optional[str] = None, ttl_seconds: Optional[int] = 3600) -> Dict[str, Any]:
        """Reset and create a fresh session."""
        self._init_state(session_id=session_id, ttl_seconds=ttl_seconds)
        return self.to_document()

    def reset(self) -> None:
        """Completely reset Working Memory state."""
        self._init_state(session_id=self._state.get("session_id"), ttl_seconds=3600)

    def is_expired(self) -> bool:
        """Check if current session is past its expiration time."""
        exp_str = self._state.get("expires_at")
        if not exp_str:
            return False
        expires_at = datetime.fromisoformat(exp_str)
        return datetime.now(timezone.utc) >= expires_at

    def clear_expired(self) -> bool:
        """If session is expired, reset state and return True. Otherwise return False."""
        if self.is_expired():
            self.reset()
            return True
        return False

    # ------------------------------------------------------------------
    # Objective, Task & Topic Tracking
    # ------------------------------------------------------------------

    def set_objective(self, objective: Optional[str]) -> None:
        self._state["current_objective"] = objective
        self._touch()

    def get_objective(self) -> Optional[str]:
        return self._state.get("current_objective")

    def set_current_task(self, task: Optional[str]) -> None:
        self._state["current_task"] = task
        self._touch()

    def get_current_task(self) -> Optional[str]:
        return self._state.get("current_task")

    def set_topic(self, topic: Optional[str]) -> None:
        self._state["current_topic"] = topic
        self._touch()

    def get_topic(self) -> Optional[str]:
        return self._state.get("current_topic")

    # ------------------------------------------------------------------
    # Conversation Reference Tracking
    # ------------------------------------------------------------------

    def update_conversation_reference(self, ref_dict: Dict[str, Any]) -> None:
        """Sync resolved reference data from Conversation Manager."""
        if isinstance(ref_dict, dict):
            self._state["conversation_reference"].update(deepcopy(ref_dict))
            self._touch()

    def get_conversation_reference(self) -> Dict[str, Any]:
        return deepcopy(self._state.get("conversation_reference", {}))

    # ------------------------------------------------------------------
    # Temporary Facts & Context
    # ------------------------------------------------------------------

    def add_fact(self, key: str, value: Any) -> None:
        """Add temporary fact into working memory."""
        self._state["temporary_facts"][key] = deepcopy(value)
        self._touch()

    def get_fact(self, key: str, default: Any = None) -> Any:
        return deepcopy(self._state["temporary_facts"].get(key, default))

    def remove_fact(self, key: str) -> bool:
        if key in self._state["temporary_facts"]:
            del self._state["temporary_facts"][key]
            self._touch()
            return True
        return False

    def get_all_facts(self) -> Dict[str, Any]:
        return deepcopy(self._state["temporary_facts"])

    # ------------------------------------------------------------------
    # Retrieved Memories Cache
    # ------------------------------------------------------------------

    def cache_memory(self, doc: Any) -> None:
        """Cache retrieved document/memory in-RAM for session lifetime."""
        if doc is not None:
            self._state["retrieved_memories"].append(deepcopy(doc))
            self._touch()

    def get_cached_memories(self) -> List[Any]:
        return deepcopy(self._state["retrieved_memories"])

    def clear_cached_memories(self) -> None:
        self._state["retrieved_memories"] = []
        self._touch()

    # ------------------------------------------------------------------
    # Reasoning Scratchpad
    # ------------------------------------------------------------------

    def add_reasoning_note(self, note: str) -> None:
        """Record intermediate reasoning note or assumption."""
        if note and isinstance(note, str):
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "note": note
            }
            self._state["reasoning_scratchpad"].append(entry)
            self._touch()

    def get_reasoning_notes(self) -> List[Dict[str, str]]:
        return deepcopy(self._state["reasoning_scratchpad"])

    def clear_reasoning(self) -> None:
        self._state["reasoning_scratchpad"] = []
        self._touch()

    # ------------------------------------------------------------------
    # Pending States
    # ------------------------------------------------------------------

    def add_pending_question(self, question: str) -> None:
        if question and question not in self._state["pending_questions"]:
            self._state["pending_questions"].append(question)
            self._touch()

    def get_pending_questions(self) -> List[str]:
        return deepcopy(self._state["pending_questions"])

    def clear_pending_questions(self) -> None:
        self._state["pending_questions"] = []
        self._touch()

    def set_pending_confirmation(self, conf: Optional[Dict[str, Any]]) -> None:
        self._state["pending_confirmation"] = deepcopy(conf)
        self._touch()

    def get_pending_confirmation(self) -> Optional[Dict[str, Any]]:
        return deepcopy(self._state["pending_confirmation"])

    def clear_pending_confirmation(self) -> None:
        self._state["pending_confirmation"] = None
        self._touch()

    def set_pending_action(self, action: Optional[Dict[str, Any]]) -> None:
        self._state["pending_action"] = deepcopy(action)
        self._touch()

    def get_pending_action(self) -> Optional[Dict[str, Any]]:
        return deepcopy(self._state["pending_action"])

    def clear_pending_action(self) -> None:
        self._state["pending_action"] = None
        self._touch()

    # ------------------------------------------------------------------
    # Decision Cache
    # ------------------------------------------------------------------

    def cache_decision(self, key: str, value: Any) -> None:
        """Cache session decision (e.g. selected brain, resolved route)."""
        self._state["decision_cache"][key] = deepcopy(value)
        self._touch()

    def get_cached_decision(self, key: str, default: Any = None) -> Any:
        return deepcopy(self._state["decision_cache"].get(key, default))

    def clear_decision_cache(self) -> None:
        self._state["decision_cache"] = {}
        self._touch()

    # ------------------------------------------------------------------
    # Context Builder & Document Conversion
    # ------------------------------------------------------------------

    def build_context(self) -> Dict[str, Any]:
        """
        Build unified temporary Context snapshot for the Cognitive Engine.
        Returns a single zero-copy-safe dictionary representation.
        """
        self.clear_expired()
        return {
            "session_id": self._state["session_id"],
            "active_objective": self._state["current_objective"],
            "active_task": self._state["current_task"],
            "active_topic": self._state["current_topic"],
            "conversation_reference": deepcopy(self._state["conversation_reference"]),
            "temporary_facts": deepcopy(self._state["temporary_facts"]),
            "cached_memories": deepcopy(self._state["retrieved_memories"]),
            "scratchpad": deepcopy(self._state["reasoning_scratchpad"]),
            "pending_questions": deepcopy(self._state["pending_questions"]),
            "pending_confirmation": deepcopy(self._state["pending_confirmation"]),
            "pending_action": deepcopy(self._state["pending_action"]),
            "decisions": deepcopy(self._state["decision_cache"]),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    def to_document(self) -> Dict[str, Any]:
        """Export full internal state snapshot."""
        return deepcopy(self._state)


_global_wm_instance: Optional[WorkingMemory] = None


def get_working_memory() -> WorkingMemory:
    """Singleton getter for global Working Memory instance."""
    global _global_wm_instance
    if _global_wm_instance is None:
        _global_wm_instance = WorkingMemory()
    return _global_wm_instance