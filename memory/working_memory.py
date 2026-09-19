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
            "expires_at": expires_at.isoformat() if expires_at else None,
            # Discussion buffer: list of {question, answer} dicts
            # Accumulates Q&A pairs within the current topic for optional
            # long-term storage at session end (no disk writes from here).
            "discussion_buffer": [],
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
    # Discussion Buffer
    # ------------------------------------------------------------------

    def add_to_discussion(self, question: str, answer: str) -> None:
        """
        Record a Q&A pair in the discussion buffer.

        The buffer accumulates entries for the current topic so the main
        loop can offer to persist the whole discussion at session end.
        Does NOT write to disk.
        """
        entry = {
            "question": str(question).strip(),
            "answer": str(answer).strip(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._state["discussion_buffer"].append(entry)
        self._touch()

    def get_discussion_entries(self) -> List[Dict[str, Any]]:
        """Return a copy of all buffered discussion entries."""
        return deepcopy(self._state.get("discussion_buffer", []))

    def has_unsaved_discussion(self) -> bool:
        """Return True if the discussion buffer contains at least one entry."""
        return len(self._state.get("discussion_buffer", [])) > 0

    def clear_discussion(self) -> None:
        """Empty the discussion buffer (e.g. after the user saves or discards it)."""
        self._state["discussion_buffer"] = []
        self._touch()

    def discussion_topic(self) -> str:
        """
        Return the current topic label for the discussion.

        Falls back to inferring a topic from the first buffered entry's
        question if ``current_topic`` is not set.
        """
        topic = self._state.get("current_topic")
        if topic:
            return topic

        entries = self._state.get("discussion_buffer", [])
        if entries:
            # Use a truncated version of the first question as the topic label.
            first_q = entries[0].get("question", "").strip()
            if first_q:
                return first_q[:60].rstrip() + ("..." if len(first_q) > 60 else "")

        return "general"

    # ------------------------------------------------------------------
    # Update Working Memory (main-loop integration helper)
    # ------------------------------------------------------------------

    def update_working_memory(self, user_input: str, answer: str, intent: str) -> None:
        """
        Convenience updater called after every main-loop turn.

        - Extracts or refreshes ``current_topic`` from the user's input
          and the resolved intent.
        - Stores the latest Q&A pair in ``conversation_reference`` so
          that follow-up resolution has something to attach to.
        - Does NOT write to disk.

        :param user_input: The raw user utterance for this turn.
        :param answer:     The response text produced by AG.
        :param intent:     The intent label returned by ``detect_intent``.
        """
        text = str(user_input).strip()
        intent = str(intent).strip() if intent else "unknown"

        # --- Topic extraction ---
        # Intents that carry meaningful topic signals:
        _topic_intents = {
            "unknown", "cloud_brain", "recall", "remember", "project_status",
            "next_step", "project_name",
        }
        if intent in _topic_intents and text:
            # Derive a short topic label from the utterance.
            topic_candidate = text[:80].rstrip()
            # Strip common question starters for cleaner labels.
            for starter in (
                "what is ", "who is ", "tell me about ", "explain ",
                "how does ", "why does ", "cloud ",
            ):
                if topic_candidate.lower().startswith(starter):
                    topic_candidate = topic_candidate[len(starter):].strip()
                    break
            if topic_candidate:
                self._state["current_topic"] = topic_candidate

        # --- Conversation reference ---
        self._state["conversation_reference"]["last_input"] = text
        self._state["conversation_reference"]["last_answer"] = str(answer).strip()
        self._state["conversation_reference"]["last_intent"] = intent
        self._touch()

    # ------------------------------------------------------------------
    # Thread Reference Resolution
    # ------------------------------------------------------------------

    # Pronoun / short-reference patterns that indicate the user is
    # continuing the previous topic rather than starting a new one.
    _CONTINUATION_PRONOUNS = frozenset({"it", "that", "this", "them", "those", "these"})

    _CONTINUATION_PREFIXES = (
        "tell me more",
        "more about",
        "can you explain",
        "give me examples",
        "simplify that",
        "expand on",
        "go deeper",
        "elaborate",
        "why",
        "how so",
        "what about",
        "and",
    )

    def resolve_thread_reference(self, user_input: str) -> str:
        """
        Attempt to resolve a follow-up / contextual reference using the
        current topic and conversation reference stored in Working Memory.

        Returns the enriched input string if a reference was resolved,
        or the original ``user_input`` unchanged if no resolution was
        possible.

        This is a lightweight, deterministic helper — it does NOT call
        any LLM and does NOT modify internal state.
        """
        if not user_input or not isinstance(user_input, str):
            return user_input

        text = user_input.strip()
        text_lower = text.lower()
        words = text_lower.split()

        topic = self._state.get("current_topic")
        last_input = self._state.get("conversation_reference", {}).get("last_input", "")

        if not topic:
            return user_input  # nothing to attach to

        # 1. Single-pronoun reference: "it", "that", "this" → replace with topic
        if len(words) == 1 and words[0] in self._CONTINUATION_PRONOUNS:
            return f"{text} about {topic}"

        # 2. Known continuation prefix: "tell me more", "explain that", etc.
        for prefix in self._CONTINUATION_PREFIXES:
            if text_lower.startswith(prefix):
                # Avoid double-appending if the topic is already in the text
                if topic.lower() not in text_lower:
                    return f"{text} (about {topic})"
                return user_input

        # 3. Very short input (≤ 4 words) that doesn't match a known intent
        if len(words) <= 4:
            if topic.lower() not in text_lower:
                return f"{text} (continuing the {topic} discussion)"

        return user_input

    # ------------------------------------------------------------------
    # Pipeline / Snapshot Aliases
    # ------------------------------------------------------------------

    def get_snapshot(self) -> Dict[str, Any]:
        """
        Alias for ``build_context()``.

        ``AGPipeline._get_memory_snapshot()`` probes for ``get_snapshot``
        first, so this keeps the pipeline working against WorkingMemory
        without needing any adapter.
        """
        return self.build_context()

    def get_state(self) -> Dict[str, Any]:
        """
        Alias for ``to_document()``.

        Provides a second name the pipeline and tests can use
        interchangeably with ``to_document``.
        """
        return self.to_document()

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


# ---------------------------------------------------------------------------
# Module-level free functions
#
# These are imported directly by Ag.py and conversation_manager.py.
# They delegate to the WorkingMemory instance passed as an argument so
# that callers don't have to interact with the singleton themselves.
# ---------------------------------------------------------------------------

def resolve_thread_reference(user_input: str, working_memory: WorkingMemory) -> str:
    """
    Free-function wrapper around ``WorkingMemory.resolve_thread_reference``.

    ``conversation_manager.py`` imports this as:
        from working_memory import resolve_thread_reference

    :param user_input:     The raw user utterance to resolve.
    :param working_memory: The active WorkingMemory instance.
    :returns:              Enriched input string, or ``user_input`` unchanged.
    """
    if not isinstance(working_memory, WorkingMemory):
        return user_input
    return working_memory.resolve_thread_reference(user_input)


def resolve_followup(user_input: str, working_memory: WorkingMemory) -> str:
    """
    Resolves a conversational follow-up by trying both the conversation
    reference stored in Working Memory and the lightweight thread-reference
    resolver.

    ``Ag.py`` calls this as a free function on every turn whose intent is
    ``"unknown"`` *before* falling back to the method-level resolver:

        resolved_input = resolve_followup(user_input, working_memory)
        if resolved_input == user_input:
            resolved_input = working_memory.resolve_thread_reference(user_input)

    :param user_input:     The raw user utterance.
    :param working_memory: The active WorkingMemory instance.
    :returns:              Enriched input string, or ``user_input`` unchanged.
    """
    if not isinstance(working_memory, WorkingMemory):
        return user_input

    text = str(user_input).strip()
    text_lower = text.lower()
    words = text_lower.split()

    # -- Attempt 1: conversation_reference -----------------------------------
    conv_ref = working_memory.get_conversation_reference()
    last_input = conv_ref.get("last_input", "")
    last_answer = conv_ref.get("last_answer", "")
    topic = working_memory.get_topic()

    # If the user is clearly referring back to the previous answer/topic,
    # prepend helpful context so the brain can make sense of it.
    BACK_REF_WORDS = frozenset({
        "it", "that", "this", "them", "those", "these",
        "why", "how", "really", "seriously",
    })

    if words and all(w in BACK_REF_WORDS for w in words):
        if topic:
            return f"{text} (about {topic})"
        if last_input:
            return f"{text} (following up on: {last_input[:60]})"

    # -- Attempt 2: lightweight thread-reference resolver --------------------
    resolved = working_memory.resolve_thread_reference(text)
    if resolved != text:
        return resolved

    # -- No resolution found -------------------------------------------------
    return user_input
