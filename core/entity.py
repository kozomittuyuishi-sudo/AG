"""
core/entity.py
==============
AG Phase 2 — Entity Object

Structured representation of a named entity extracted from conversation.

Instead of storing plain strings ("Einstein was mentioned"), the pipeline
stores rich Entity objects that track identity across turns, accumulate
aliases, record confidence, and support future reference resolution without
keyword matching.

Design principles:
    - Entities are identified by a canonical ``name`` (e.g. "Albert Einstein").
    - Aliases record all surface forms seen so far (e.g. "Einstein", "he",
      "the physicist").  Alias matching is done by ContextResolver, not here.
    - ``confidence`` reflects how certain we are about the entity extraction.
    - Deterministic, in-memory, stdlib only. No LLM calls.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid


# Recognised entity type labels.  Open-ended — any string is accepted,
# but these are the canonical labels used by the evaluator.
ENTITY_TYPE_PERSON = "person"
ENTITY_TYPE_CONCEPT = "concept"
ENTITY_TYPE_PLACE = "place"
ENTITY_TYPE_OBJECT = "object"
ENTITY_TYPE_EVENT = "event"
ENTITY_TYPE_TOPIC = "topic"
ENTITY_TYPE_UNKNOWN = "unknown"


class Entity:
    """
    Structured, conversationally-aware entity.

    Attributes
    ----------
    entity_id : str
        Unique identifier (auto-generated).
    name : str
        Canonical name (the most complete, unambiguous form).
    entity_type : str
        Category: person, concept, place, object, event, topic, or unknown.
    aliases : List[str]
        All surface forms through which this entity has been referenced.
        The canonical ``name`` is always included.
    confidence : float
        Extraction confidence in [0.0, 1.0].
    first_seen : str
        ISO-8601 UTC timestamp of the first reference.
    last_seen : str
        ISO-8601 UTC timestamp of the most recent reference.
    metadata : Dict[str, Any]
        Arbitrary structured data (e.g. {"role": "physicist", "era": "20th century"}).
    """

    def __init__(
        self,
        name: str,
        entity_type: str = ENTITY_TYPE_UNKNOWN,
        confidence: float = 1.0,
        aliases: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.entity_id: str = f"ent_{uuid.uuid4().hex[:10]}"
        self.name: str = str(name).strip()
        self.entity_type: str = str(entity_type)
        self.confidence: float = max(0.0, min(1.0, float(confidence)))
        self.first_seen: str = now
        self.last_seen: str = now
        self.metadata: Dict[str, Any] = dict(metadata or {})

        # Seed the alias list with the canonical name
        self.aliases: List[str] = []
        self._add_alias_raw(self.name)
        for alias in (aliases or []):
            self._add_alias_raw(alias)

    # ------------------------------------------------------------------
    # Alias management
    # ------------------------------------------------------------------

    def _add_alias_raw(self, alias: str) -> None:
        """Internal: add an alias without updating last_seen."""
        clean = str(alias).strip()
        if clean and clean not in self.aliases:
            self.aliases.append(clean)

    def add_alias(self, alias: str) -> "Entity":
        """
        Add a new surface form for this entity and update last_seen.

        :param alias: The surface form to add (e.g. "Einstein", "he").
        :returns: self.
        """
        self._add_alias_raw(alias)
        self.last_seen = datetime.now(timezone.utc).isoformat()
        return self

    def matches(self, text: str) -> bool:
        """
        Return True if ``text`` (case-insensitive) matches the canonical
        name or any registered alias.
        """
        text_lower = str(text).strip().lower()
        return any(a.lower() == text_lower for a in self.aliases)

    # ------------------------------------------------------------------
    # Update helpers
    # ------------------------------------------------------------------

    def touch(self) -> "Entity":
        """Update last_seen to now. Call whenever this entity is referenced."""
        self.last_seen = datetime.now(timezone.utc).isoformat()
        return self

    def update_confidence(self, new_confidence: float) -> "Entity":
        """
        Update confidence, clamped to [0.0, 1.0].
        Higher confidence replaces lower — we never downgrade a confirmed entity.
        """
        clamped = max(0.0, min(1.0, float(new_confidence)))
        if clamped > self.confidence:
            self.confidence = clamped
        return self

    def update_metadata(self, key: str, value: Any) -> "Entity":
        """Add or update a metadata field."""
        self.metadata[str(key)] = value
        return self

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "entity_type": self.entity_type,
            "aliases": list(self.aliases),
            "confidence": self.confidence,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Entity":
        """Reconstruct an Entity from a ``to_dict()`` snapshot."""
        e = cls(
            name=data.get("name", "unknown"),
            entity_type=data.get("entity_type", ENTITY_TYPE_UNKNOWN),
            confidence=data.get("confidence", 1.0),
            aliases=data.get("aliases", []),
            metadata=data.get("metadata", {}),
        )
        e.entity_id = data.get("entity_id", e.entity_id)
        e.first_seen = data.get("first_seen", e.first_seen)
        e.last_seen = data.get("last_seen", e.last_seen)
        return e

    def __repr__(self) -> str:
        return (
            f"Entity(name={self.name!r}, type={self.entity_type!r}, "
            f"confidence={self.confidence:.2f}, aliases={self.aliases!r})"
        )


class EntityRegistry:
    """
    In-memory collection of Entity objects for a single conversation session.

    Provides lookup by name / alias and maintains recency ordering so
    the most recently active entity can be retrieved as the default
    referent for pronoun resolution.
    """

    def __init__(self) -> None:
        self._entities: List[Entity] = []

    # ------------------------------------------------------------------
    # Adding and updating
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        entity_type: str = ENTITY_TYPE_UNKNOWN,
        confidence: float = 1.0,
        aliases: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Entity:
        """
        Register a new entity or update an existing one.

        If an entity with a matching name or alias already exists, its
        confidence is upgraded (if higher), aliases are merged, and
        last_seen is refreshed.  Otherwise a new Entity is created.

        :returns: The registered or updated Entity.
        """
        existing = self.find(name)
        if existing is not None:
            existing.touch()
            existing.update_confidence(confidence)
            for alias in (aliases or []):
                existing.add_alias(alias)
            if metadata:
                for k, v in metadata.items():
                    existing.update_metadata(k, v)
            # Move to end so it becomes the most recent
            self._entities.remove(existing)
            self._entities.append(existing)
            return existing

        entity = Entity(
            name=name,
            entity_type=entity_type,
            confidence=confidence,
            aliases=aliases,
            metadata=metadata,
        )
        self._entities.append(entity)
        return entity

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def find(self, text: str) -> Optional[Entity]:
        """
        Return the first Entity whose canonical name or any alias
        matches ``text`` (case-insensitive), or None.
        """
        text_lower = str(text).strip().lower()
        for entity in self._entities:
            if entity.matches(text_lower):
                return entity
        return None

    def find_by_type(self, entity_type: str) -> List[Entity]:
        """Return all entities of the given type."""
        return [e for e in self._entities if e.entity_type == entity_type]

    def most_recent(self) -> Optional[Entity]:
        """Return the most recently active entity, or None if the registry is empty."""
        return self._entities[-1] if self._entities else None

    def most_recent_person(self) -> Optional[Entity]:
        """Return the most recently active person-type entity, or None."""
        persons = self.find_by_type(ENTITY_TYPE_PERSON)
        return persons[-1] if persons else None

    def all_entities(self) -> List[Entity]:
        """Return a copy of all registered entities (oldest first)."""
        return list(self._entities)

    def recent(self, n: int = 5) -> List[Entity]:
        """Return the n most recently active entities (most recent last)."""
        return list(self._entities[-n:])

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_list(self) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self._entities]

    @classmethod
    def from_list(cls, data: List[Dict[str, Any]]) -> "EntityRegistry":
        registry = cls()
        for item in data:
            entity = Entity.from_dict(item)
            registry._entities.append(entity)
        return registry

    def clear(self) -> None:
        self._entities = []

    def __len__(self) -> int:
        return len(self._entities)

    def __repr__(self) -> str:
        return f"EntityRegistry({len(self._entities)} entities)"
