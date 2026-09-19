"""
core/entity_tracker.py
=======================
AG Phase 2.1 — EntityTracker

Extends the EntityRegistry with conversational turn-awareness.

While EntityRegistry stores rich Entity objects, EntityTracker wraps it with:
  - A per-turn counter so every registered mention is stamped with a turn number.
  - Per-entity turn metadata: first_appearance_turn, last_appearance_turn, frequency.
  - An active_status flag (True while the entity is within the recency window).
  - A conversation_focus: the single most-recently active entity name.

The tracker is the authoritative source for the ReferenceResolver.
WorkingMemory should hold one EntityTracker per session.

Design principles:
    - Deterministic, in-memory, stdlib only. No LLM calls.
    - Does NOT replace EntityRegistry — it delegates to it for entity storage.
    - Multiple entities can be active simultaneously.
    - Recency window is configurable (default: 5 turns).
    - Thread-tracking metadata is stored in each Entity's metadata dict so
      serialisation reuses the existing Entity.to_dict() / from_dict() path.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional

from conversation.core.entity import (
    Entity,
    EntityRegistry,
    ENTITY_TYPE_PERSON,
    ENTITY_TYPE_UNKNOWN,
)


# Keys used inside Entity.metadata for tracker-owned fields
_FIRST_TURN_KEY = "_tracker_first_turn"
_LAST_TURN_KEY = "_tracker_last_turn"
_FREQUENCY_KEY = "_tracker_frequency"
_ACTIVE_KEY = "_tracker_active"

# Supported entity types (canonical labels)
SUPPORTED_ENTITY_TYPES = {
    "person",
    "organization",
    "place",
    "object",
    "event",
    "concept",
}

# How many turns back an entity is still considered "active"
DEFAULT_RECENCY_WINDOW = 5


class TrackedEntity:
    """
    A lightweight, tracker-specific view of an entity's conversational status.

    This is a read-only snapshot — it wraps an Entity object without
    mutating it.  The tracker produces these on demand for the resolver.
    """

    __slots__ = (
        "entity_id",
        "name",
        "entity_type",
        "aliases",
        "confidence",
        "first_appearance_turn",
        "last_appearance_turn",
        "frequency",
        "active",
    )

    def __init__(
        self,
        entity: Entity,
        current_turn: int,
        recency_window: int,
    ) -> None:
        self.entity_id: str = entity.entity_id
        self.name: str = entity.name
        self.entity_type: str = entity.entity_type
        self.aliases: List[str] = list(entity.aliases)
        self.confidence: float = entity.confidence

        meta = entity.metadata
        self.first_appearance_turn: int = int(meta.get(_FIRST_TURN_KEY, current_turn))
        self.last_appearance_turn: int = int(meta.get(_LAST_TURN_KEY, current_turn))
        self.frequency: int = int(meta.get(_FREQUENCY_KEY, 1))

        # Active if last mention is within the recency window
        turns_since = current_turn - self.last_appearance_turn
        self.active: bool = bool(meta.get(_ACTIVE_KEY, True)) and turns_since <= recency_window

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "entity_type": self.entity_type,
            "aliases": list(self.aliases),
            "confidence": self.confidence,
            "first_appearance_turn": self.first_appearance_turn,
            "last_appearance_turn": self.last_appearance_turn,
            "frequency": self.frequency,
            "active": self.active,
        }

    def __repr__(self) -> str:
        return (
            f"TrackedEntity(name={self.name!r}, type={self.entity_type!r}, "
            f"turn={self.last_appearance_turn}, freq={self.frequency}, "
            f"active={self.active}, confidence={self.confidence:.2f})"
        )


class EntityTracker:
    """
    Turn-aware entity tracker for a single conversation session.

    Public API
    ----------
    record_entity(name, entity_type, confidence, aliases)
        Register or refresh an entity for the current turn.
        Advances the internal turn counter on the first call per turn.

    advance_turn()
        Explicitly advance the turn counter (call once per user message).
        record_entity() also advances the turn if you haven't called this yet.

    get_all() -> List[TrackedEntity]
        All tracked entities, oldest first.

    get_active() -> List[TrackedEntity]
        Only entities within the recency window, most recent last.

    get_focus() -> Optional[TrackedEntity]
        The single most recently mentioned entity (conversation focus).

    get_focus_by_type(entity_type) -> Optional[TrackedEntity]
        The most recently mentioned entity of the given type.

    find(text) -> Optional[TrackedEntity]
        Case-insensitive lookup by name or alias.

    reset()
        Clear all entities and reset the turn counter.

    to_dict() / from_dict()
        Serialise / restore the full tracker state.
    """

    def __init__(self, recency_window: int = DEFAULT_RECENCY_WINDOW) -> None:
        self._registry: EntityRegistry = EntityRegistry()
        self._turn: int = 0
        self._turn_advanced_this_cycle: bool = False
        self._recency_window: int = max(1, int(recency_window))

    # ------------------------------------------------------------------
    # Turn management
    # ------------------------------------------------------------------

    def advance_turn(self) -> int:
        """
        Explicitly advance the turn counter by 1.

        Call this once at the start of each new user message before
        calling record_entity() for that turn.

        :returns: The new turn number.
        """
        self._turn += 1
        self._turn_advanced_this_cycle = True
        return self._turn

    def current_turn(self) -> int:
        """Return the current turn number (0-indexed: 0 = no turns yet)."""
        return self._turn

    # ------------------------------------------------------------------
    # Recording entities
    # ------------------------------------------------------------------

    def record_entity(
        self,
        name: str,
        entity_type: str = ENTITY_TYPE_UNKNOWN,
        confidence: float = 1.0,
        aliases: Optional[List[str]] = None,
    ) -> TrackedEntity:
        """
        Record an entity mention in the current conversational turn.

        If this is the first call to record_entity() since the last
        advance_turn() call, the turn counter is advanced automatically.

        :param name: Canonical entity name (e.g. "Elon Musk").
        :param entity_type: One of the SUPPORTED_ENTITY_TYPES.
        :param confidence: Extraction confidence in [0.0, 1.0].
        :param aliases: Additional surface forms (e.g. ["Musk", "he"]).
        :returns: A TrackedEntity snapshot for this entity.
        """
        # Auto-advance turn if the caller hasn't done it yet this cycle
        if not self._turn_advanced_this_cycle:
            self._turn += 1
            self._turn_advanced_this_cycle = True

        # Normalise entity type
        clean_type = str(entity_type).lower().strip()
        if clean_type not in SUPPORTED_ENTITY_TYPES:
            clean_type = ENTITY_TYPE_UNKNOWN

        # Register or update in the underlying registry
        entity = self._registry.register(
            name=name,
            entity_type=clean_type,
            confidence=confidence,
            aliases=aliases or [],
        )

        # Update tracker metadata inside the entity
        meta = entity.metadata
        if _FIRST_TURN_KEY not in meta:
            meta[_FIRST_TURN_KEY] = self._turn
        meta[_LAST_TURN_KEY] = self._turn
        meta[_FREQUENCY_KEY] = meta.get(_FREQUENCY_KEY, 0) + 1
        meta[_ACTIVE_KEY] = True

        # Mark all other entities' active status based on recency window
        self._refresh_active_statuses()

        return TrackedEntity(entity, self._turn, self._recency_window)

    def _refresh_active_statuses(self) -> None:
        """Recompute active flags for all entities based on current turn."""
        for entity in self._registry.all_entities():
            last = entity.metadata.get(_LAST_TURN_KEY, 0)
            turns_since = self._turn - last
            entity.metadata[_ACTIVE_KEY] = turns_since <= self._recency_window

    # ------------------------------------------------------------------
    # Turn boundary signal — call after every user turn is fully processed
    # ------------------------------------------------------------------

    def end_turn(self) -> None:
        """
        Signal the end of the current turn processing cycle.

        After calling this, the next call to record_entity() will advance
        the turn counter automatically.

        Call this after processing each complete user message.
        """
        self._turn_advanced_this_cycle = False

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def get_all(self) -> List[TrackedEntity]:
        """Return all tracked entities (oldest first)."""
        return [
            TrackedEntity(e, self._turn, self._recency_window)
            for e in self._registry.all_entities()
        ]

    def get_active(self) -> List[TrackedEntity]:
        """Return only entities that are within the recency window (oldest first)."""
        self._refresh_active_statuses()
        return [
            TrackedEntity(e, self._turn, self._recency_window)
            for e in self._registry.all_entities()
            if e.metadata.get(_ACTIVE_KEY, False)
        ]

    def get_focus(self) -> Optional[TrackedEntity]:
        """
        Return the conversation focus — the most recently mentioned entity.

        This is what the resolver uses as the primary candidate when
        resolving bare pronouns (he/she/it/they/this/that/etc.).
        """
        entity = self._registry.most_recent()
        if entity is None:
            return None
        return TrackedEntity(entity, self._turn, self._recency_window)

    def get_focus_by_type(self, entity_type: str) -> Optional[TrackedEntity]:
        """
        Return the most recently mentioned entity of the given type.

        Used by the resolver to resolve type-specific references
        (e.g. "the company" → most recent organization-type entity).
        """
        clean_type = str(entity_type).lower().strip()
        entities = self._registry.find_by_type(clean_type)
        if not entities:
            return None
        # Most recent is last (registry keeps insertion/recency order)
        return TrackedEntity(entities[-1], self._turn, self._recency_window)

    def find(self, text: str) -> Optional[TrackedEntity]:
        """
        Case-insensitive lookup by canonical name or any alias.

        :returns: TrackedEntity or None.
        """
        entity = self._registry.find(text)
        if entity is None:
            return None
        return TrackedEntity(entity, self._turn, self._recency_window)

    def count(self) -> int:
        """Return the total number of tracked entities."""
        return len(self._registry)

    def count_active(self) -> int:
        """Return the number of active (recently mentioned) entities."""
        return len(self.get_active())

    # ------------------------------------------------------------------
    # Ranking helpers (used by ReferenceResolver)
    # ------------------------------------------------------------------

    def rank_candidates(
        self,
        candidates: List[TrackedEntity],
        pronoun: Optional[str] = None,
    ) -> List[TrackedEntity]:
        """
        Rank resolution candidates by:
          1. Recency   — turns since last mention (fewer = better)
          2. Frequency — how often mentioned (more = better)
          3. Grammatical compatibility — person pronouns prefer person-type entities
          4. Entity confidence — higher confidence wins ties

        :param candidates: The entities to rank.
        :param pronoun: Optional pronoun hint for grammatical compatibility scoring.
        :returns: Candidates sorted best-first (index 0 = best).
        """
        if not candidates:
            return []

        person_pronouns = {
            "he", "she", "him", "her", "his", "hers",
            "they", "them", "their", "theirs",
        }
        thing_pronouns = {"it", "its", "this", "that", "these", "those"}

        pronoun_lower = (pronoun or "").lower().strip()
        is_person_pronoun = pronoun_lower in person_pronouns
        is_thing_pronoun = pronoun_lower in thing_pronouns

        def _score(te: TrackedEntity) -> float:
            score = 0.0

            # Recency: more recent = higher score (0–4 points)
            turns_since = self._turn - te.last_appearance_turn
            recency_score = max(0.0, 4.0 - turns_since * 0.5)
            score += recency_score

            # Frequency: capped at 2 points
            freq_score = min(te.frequency * 0.4, 2.0)
            score += freq_score

            # Grammatical compatibility: +1.5 for perfect match
            if is_person_pronoun and te.entity_type == "person":
                score += 1.5
            elif is_thing_pronoun and te.entity_type in {
                "organization", "object", "event", "concept", "place"
            }:
                score += 1.5
            elif not is_person_pronoun and not is_thing_pronoun:
                # No pronoun hint: no preference
                pass
            else:
                # Mismatch: slight penalty
                score -= 0.5

            # Base confidence: 0–1 point
            score += te.confidence

            return score

        return sorted(candidates, key=_score, reverse=True)

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear all entities and reset the turn counter."""
        self._registry.clear()
        self._turn = 0
        self._turn_advanced_this_cycle = False

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn": self._turn,
            "recency_window": self._recency_window,
            "entities": self._registry.to_list(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EntityTracker":
        """Restore an EntityTracker from a to_dict() snapshot."""
        tracker = cls(recency_window=data.get("recency_window", DEFAULT_RECENCY_WINDOW))
        tracker._turn = int(data.get("turn", 0))
        tracker._registry = EntityRegistry.from_list(data.get("entities", []))
        tracker._refresh_active_statuses()
        return tracker

    def __repr__(self) -> str:
        return (
            f"EntityTracker(turn={self._turn}, "
            f"entities={self.count()}, active={self.count_active()})"
        )
