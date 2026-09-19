"""
cognitive/reference_resolver.py
================================
AG Phase 2.1 — ReferenceResolver

Resolves conversational references in a user utterance to specific entities
tracked by the EntityTracker.

Supported reference forms
--------------------------
Pronouns:
    he, she, they, it, this, that, those, these, him, her, them

Natural-language references:
    the company, the person, the city, the place, the country,
    the organization, the thing, the event, the concept, the object

Resolution algorithm
--------------------
1. Detect which reference words are present in the input.
2. For each reference word, determine its grammatical type hint
   (person pronoun → prefer person-type entities; it/this/that → prefer
   non-person entities).
3. Collect all active candidate entities from the EntityTracker.
4. Rank candidates using EntityTracker.rank_candidates().
5. If the top candidate's confidence-adjusted score exceeds
   AUTO_RESOLVE_THRESHOLD → rewrite the input.
6. If the top candidate's score is below CLARIFICATION_THRESHOLD → ask.
7. If no candidates exist → ask for clarification.

Output
------
Each call to ``resolve()`` returns a ``ResolutionResult``:
    resolved_text        : str   — rewritten input (original if nothing changed)
    referent             : Optional[TrackedEntity] — the entity resolved to
    confidence           : float — resolution confidence 0–1
    needs_clarification  : bool  — True if confidence too low to auto-resolve
    clarification_question: Optional[str] — question to ask the user

Design principles
-----------------
- Deterministic, in-memory, stdlib only. No LLM calls.
- Does NOT mutate the EntityTracker.
- Works independently of the Thought pipeline — the ReferenceResolver can
  be called directly without a Thought object.
- The existing ContextResolver (cognitive/context_resolver.py) is NOT
  modified. This module is additive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from conversation.core.entity_tracker import EntityTracker, TrackedEntity


# ---------------------------------------------------------------------------
# Confidence thresholds
# ---------------------------------------------------------------------------

AUTO_RESOLVE_THRESHOLD: float = 0.65   # At or above: auto-rewrite
CLARIFICATION_THRESHOLD: float = 0.40  # Below: ask the user


# ---------------------------------------------------------------------------
# Reference word tables
# ---------------------------------------------------------------------------

# Pronouns that grammatically prefer a PERSON entity
_PERSON_PRONOUNS: frozenset = frozenset({
    "he", "she", "him", "her", "his", "hers",
    "they", "them", "their", "theirs",
})

# Pronouns that grammatically prefer a NON-PERSON entity (org/place/object/event/concept)
_THING_PRONOUNS: frozenset = frozenset({
    "it", "its", "this", "that", "these", "those",
})

# All pronouns supported by this resolver
_ALL_PRONOUNS: frozenset = _PERSON_PRONOUNS | _THING_PRONOUNS

# Natural-language references → preferred entity type for lookup
_NL_REFERENCES: Dict[str, str] = {
    "the company":      "organization",
    "the organisation": "organization",
    "the organization": "organization",
    "the business":     "organization",
    "the firm":         "organization",
    "the person":       "person",
    "the individual":   "person",
    "the man":          "person",
    "the woman":        "person",
    "the city":         "place",
    "the place":        "place",
    "the location":     "place",
    "the country":      "place",
    "the region":       "place",
    "the town":         "place",
    "the event":        "event",
    "the occasion":     "event",
    "the thing":        "object",
    "the object":       "object",
    "the concept":      "concept",
    "the idea":         "concept",
    "the topic":        "concept",
}

# Type label → clarification question template
_TYPE_CLARIFICATION: Dict[str, str] = {
    "person":       "Which person are you referring to?",
    "organization": "Could you clarify which company or organisation you mean?",
    "place":        "Which place are you referring to?",
    "event":        "Which event are you referring to?",
    "object":       "Which thing are you referring to?",
    "concept":      "Which concept are you referring to?",
}

# Regex to detect pronouns at word boundaries (built once at module load)
_PRONOUN_RE = re.compile(
    r"\b("
    + "|".join(re.escape(p) for p in sorted(_ALL_PRONOUNS, key=len, reverse=True))
    + r")\b",
    re.IGNORECASE,
)

# Regex for natural-language references (longest first to avoid partial matches)
_NL_REF_RE = re.compile(
    r"\b("
    + "|".join(
        re.escape(ref)
        for ref in sorted(_NL_REFERENCES.keys(), key=len, reverse=True)
    )
    + r")\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Result object
# ---------------------------------------------------------------------------

@dataclass
class ResolutionResult:
    """
    Outcome of a single reference resolution attempt.

    Attributes
    ----------
    resolved_text : str
        The rewritten input with references replaced by entity names.
        Equals ``original_text`` if nothing was resolved.
    referent : Optional[TrackedEntity]
        The entity the primary reference was resolved to, or None.
    confidence : float
        Resolution confidence in [0.0, 1.0].
    needs_clarification : bool
        True when confidence is below the clarification threshold.
    clarification_question : Optional[str]
        The question to present to the user when needs_clarification is True.
    original_text : str
        The raw, unmodified input text.
    reference_words_found : List[str]
        All reference words that were detected in the input.
    """
    resolved_text: str
    original_text: str
    referent: Optional[TrackedEntity]
    confidence: float
    needs_clarification: bool
    clarification_question: Optional[str]
    reference_words_found: List[str] = field(default_factory=list)

    def was_resolved(self) -> bool:
        """Return True if the text was actually rewritten."""
        return self.resolved_text != self.original_text

    def to_dict(self) -> dict:
        return {
            "resolved_text": self.resolved_text,
            "original_text": self.original_text,
            "referent": self.referent.to_dict() if self.referent else None,
            "confidence": self.confidence,
            "needs_clarification": self.needs_clarification,
            "clarification_question": self.clarification_question,
            "reference_words_found": list(self.reference_words_found),
            "was_resolved": self.was_resolved(),
        }


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

class ReferenceResolver:
    """
    Resolves pronouns and natural-language references to tracked entities.

    Usage
    -----
    ::

        tracker = EntityTracker()
        tracker.advance_turn()
        tracker.record_entity("Elon Musk", "person", confidence=1.0)
        tracker.end_turn()

        tracker.advance_turn()
        # User asks a follow-up:
        resolver = ReferenceResolver()
        result = resolver.resolve("Where was he born?", tracker)

        print(result.resolved_text)          # "Where was Elon Musk born?"
        print(result.confidence)             # e.g. 0.85
        print(result.needs_clarification)    # False
    """

    def __init__(
        self,
        auto_resolve_threshold: float = AUTO_RESOLVE_THRESHOLD,
        clarification_threshold: float = CLARIFICATION_THRESHOLD,
    ) -> None:
        self._auto_threshold = float(auto_resolve_threshold)
        self._clarification_threshold = float(clarification_threshold)

    # ------------------------------------------------------------------
    # Primary entry point
    # ------------------------------------------------------------------

    def resolve(
        self,
        text: str,
        tracker: EntityTracker,
    ) -> ResolutionResult:
        """
        Resolve all reference words in ``text`` using the entity tracker.

        :param text: The raw user utterance.
        :param tracker: The active EntityTracker for this session.
        :returns: A ResolutionResult describing what was done.
        """
        raw = str(text).strip()

        # Step 1: Detect reference words
        pronouns_found, nl_refs_found = self._detect_references(raw)
        all_refs = pronouns_found + nl_refs_found

        if not all_refs:
            # No reference words → return unchanged
            return ResolutionResult(
                resolved_text=raw,
                original_text=raw,
                referent=None,
                confidence=1.0,
                needs_clarification=False,
                clarification_question=None,
                reference_words_found=[],
            )

        # Step 2: Find the primary reference (first one in text that drives resolution)
        primary_ref, preferred_type = self._primary_reference(
            raw, pronouns_found, nl_refs_found
        )

        # Step 3: Collect candidates
        candidates = self._collect_candidates(tracker, preferred_type)

        # Step 4: Handle empty tracker
        if not candidates:
            return self._no_candidates_result(raw, all_refs, primary_ref, preferred_type)

        # Step 5: Rank candidates
        pronoun_hint = primary_ref if primary_ref.lower() in _ALL_PRONOUNS else None
        ranked = tracker.rank_candidates(candidates, pronoun=pronoun_hint)
        best = ranked[0]

        # Step 6: Compute confidence
        confidence = self._compute_confidence(
            best=best,
            ranked=ranked,
            tracker=tracker,
            primary_ref=primary_ref,
        )

        # Step 7: Decide action
        if confidence >= self._auto_threshold:
            resolved = self._rewrite(raw, all_refs, best.name)
            return ResolutionResult(
                resolved_text=resolved,
                original_text=raw,
                referent=best,
                confidence=confidence,
                needs_clarification=False,
                clarification_question=None,
                reference_words_found=all_refs,
            )

        elif confidence < self._clarification_threshold:
            question = self._build_clarification_question(
                raw, ranked, primary_ref, preferred_type
            )
            return ResolutionResult(
                resolved_text=raw,
                original_text=raw,
                referent=best,
                confidence=confidence,
                needs_clarification=True,
                clarification_question=question,
                reference_words_found=all_refs,
            )

        else:
            # Tentative: rewrite but flag low confidence
            resolved = self._rewrite(raw, all_refs, best.name)
            return ResolutionResult(
                resolved_text=resolved,
                original_text=raw,
                referent=best,
                confidence=confidence,
                needs_clarification=False,
                clarification_question=None,
                reference_words_found=all_refs,
            )

    # ------------------------------------------------------------------
    # Reference detection
    # ------------------------------------------------------------------

    def _detect_references(
        self, text: str
    ) -> Tuple[List[str], List[str]]:
        """
        Detect pronoun references and natural-language references in text.

        Returns (pronouns_found, nl_refs_found) — each is a list of the
        matched reference strings in the order they appear in text.
        """
        pronouns: List[str] = []
        seen_pronouns: set = set()
        for m in _PRONOUN_RE.finditer(text):
            word = m.group(1).lower()
            if word not in seen_pronouns:
                seen_pronouns.add(word)
                pronouns.append(word)

        nl_refs: List[str] = []
        seen_nl: set = set()
        for m in _NL_REF_RE.finditer(text):
            ref = m.group(1).lower()
            if ref not in seen_nl:
                seen_nl.add(ref)
                nl_refs.append(ref)

        return pronouns, nl_refs

    def _primary_reference(
        self,
        text: str,
        pronouns: List[str],
        nl_refs: List[str],
    ) -> Tuple[str, Optional[str]]:
        """
        Determine the primary reference driving resolution and its preferred
        entity type.

        Returns (primary_ref_string, preferred_entity_type_or_None).

        Priority: first pronoun in text, then first NL reference.
        """
        # Find which appears first in text
        first_pronoun_pos = len(text) + 1
        first_pronoun = None
        if pronouns:
            for p in pronouns:
                m = re.search(r"\b" + re.escape(p) + r"\b", text, re.IGNORECASE)
                if m and m.start() < first_pronoun_pos:
                    first_pronoun_pos = m.start()
                    first_pronoun = p

        first_nl_pos = len(text) + 1
        first_nl = None
        if nl_refs:
            for ref in nl_refs:
                m = re.search(re.escape(ref), text, re.IGNORECASE)
                if m and m.start() < first_nl_pos:
                    first_nl_pos = m.start()
                    first_nl = ref

        if first_pronoun is not None and first_pronoun_pos <= first_nl_pos:
            # Pronoun wins
            if first_pronoun in _PERSON_PRONOUNS:
                return first_pronoun, "person"
            else:
                return first_pronoun, None  # No preferred type for thing pronouns
        elif first_nl is not None:
            preferred = _NL_REFERENCES.get(first_nl.lower())
            return first_nl, preferred
        else:
            # Fallback (shouldn't happen if called only when references exist)
            return (pronouns + nl_refs)[0], None

    # ------------------------------------------------------------------
    # Candidate collection
    # ------------------------------------------------------------------

    def _collect_candidates(
        self,
        tracker: EntityTracker,
        preferred_type: Optional[str],
    ) -> List[TrackedEntity]:
        """
        Build the candidate list.

        If a preferred_type is given, active entities of that type come
        first, then all other active entities.  If there are no active
        entities at all, fall back to all entities.
        """
        active = tracker.get_active()
        if not active:
            # Fallback to all entities when nothing is active
            active = tracker.get_all()

        if not preferred_type:
            return active

        # Put preferred-type entities first, then the rest
        preferred = [e for e in active if e.entity_type == preferred_type]
        others = [e for e in active if e.entity_type != preferred_type]
        return preferred + others

    # ------------------------------------------------------------------
    # Confidence computation
    # ------------------------------------------------------------------

    def _compute_confidence(
        self,
        best: TrackedEntity,
        ranked: List[TrackedEntity],
        tracker: EntityTracker,
        primary_ref: str,
    ) -> float:
        """
        Compute the overall resolution confidence.

        Factors:
        - Entity's own confidence (base)
        - Recency: penalty for entities mentioned many turns ago
        - Ambiguity: penalty when multiple strong candidates exist
        - Boost for unique, very recent, single-candidate resolution
        """
        score = best.confidence

        # Recency penalty
        turns_since = tracker.current_turn() - best.last_appearance_turn
        recency_penalty = min(turns_since * 0.12, 0.48)
        score -= recency_penalty

        # Ambiguity penalty: if second candidate is close in score
        if len(ranked) > 1:
            n_close = sum(
                1 for e in ranked[1:]
                if abs(e.confidence - best.confidence) < 0.20
                and (tracker.current_turn() - e.last_appearance_turn) <= 3
            )
            if n_close > 0:
                ambiguity_penalty = min(n_close * 0.18, 0.36)
                score -= ambiguity_penalty

        # Boost: single active entity, mentioned very recently
        if len(ranked) == 1 and turns_since <= 1:
            score = min(score + 0.08, 1.0)

        return max(0.0, min(1.0, score))

    # ------------------------------------------------------------------
    # Text rewriting
    # ------------------------------------------------------------------

    def _rewrite(
        self,
        text: str,
        references: List[str],
        referent_name: str,
    ) -> str:
        """
        Replace the FIRST occurrence of each detected reference word in
        ``text`` with ``referent_name``.

        We replace the first occurrence regardless of sentence position so
        that object-position references (e.g. "tell me about them",
        "explain this") are also rewritten correctly.  Subsequent
        occurrences of the same word are left unchanged to avoid over-
        substitution in rare repeated-reference sentences.
        """
        result = text

        # Sort references longest-first to avoid partial replacements
        # (e.g. replace "the company" before "the")
        for ref in sorted(references, key=len, reverse=True):
            pattern = re.compile(r"\b" + re.escape(ref) + r"\b", re.IGNORECASE)
            m = pattern.search(result)
            if m:
                result = result[:m.start()] + referent_name + result[m.end():]

        # Clean up double spaces
        result = re.sub(r" {2,}", " ", result).strip()
        return result

    # ------------------------------------------------------------------
    # Clarification question builder
    # ------------------------------------------------------------------

    def _build_clarification_question(
        self,
        text: str,
        ranked: List[TrackedEntity],
        primary_ref: str,
        preferred_type: Optional[str],
    ) -> str:
        """
        Build a natural clarification question for the user.

        If multiple candidates exist, list the top 2-3 by name.
        Otherwise fall back to a type-based or generic question.
        """
        base = text.rstrip("?.!").strip()

        if len(ranked) >= 2:
            # List the top candidates
            names = [e.name for e in ranked[:3]]
            if len(names) == 2:
                listed = f"{names[0]} or {names[1]}"
            else:
                listed = f"{', '.join(names[:-1])}, or {names[-1]}"
            return f"Are you referring to {listed}? (in: '{base}')"

        if ranked:
            # Single candidate but low confidence
            if preferred_type:
                q = _TYPE_CLARIFICATION.get(
                    preferred_type,
                    f"Could you clarify which {preferred_type} you mean?"
                )
            else:
                q = _TYPE_CLARIFICATION.get("person", "Who are you referring to?")
            return q

        # No candidates at all
        if preferred_type:
            return _TYPE_CLARIFICATION.get(
                preferred_type,
                f"Could you clarify which {preferred_type} you mean?"
            )

        text_lower = text.lower()
        if any(p in text_lower.split() for p in ["he", "she", "him", "her", "his", "hers"]):
            return "Which person are you referring to?"
        if "the company" in text_lower or "the organisation" in text_lower:
            return "Could you clarify which company or organisation you mean?"
        return "Could you clarify what you're referring to? I want to make sure I answer the right question."

    def _no_candidates_result(
        self,
        raw: str,
        all_refs: List[str],
        primary_ref: str,
        preferred_type: Optional[str],
    ) -> ResolutionResult:
        """Return a clarification result when no candidate entities are available."""
        question = _TYPE_CLARIFICATION.get(
            preferred_type or "",
            "Could you clarify what you're referring to?"
        )
        if not preferred_type:
            if primary_ref in _PERSON_PRONOUNS:
                question = "Which person are you referring to?"
            elif primary_ref in _NL_REFERENCES:
                t = _NL_REFERENCES[primary_ref]
                question = _TYPE_CLARIFICATION.get(t, question)

        return ResolutionResult(
            resolved_text=raw,
            original_text=raw,
            referent=None,
            confidence=0.0,
            needs_clarification=True,
            clarification_question=question,
            reference_words_found=all_refs,
        )
