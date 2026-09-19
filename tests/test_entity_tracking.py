"""
test_entity_tracking.py
========================
AG Phase 2.1 — Comprehensive pytest suite for Entity Tracking and
Follow-up Context Resolution.

Covers 7 required scenarios:
    1. Single entity — basic tracking, focus, turn metadata
    2. Multiple entities — simultaneous tracking, recency ordering
    3. Pronouns — he/she/they/it/him/her/them resolution
    4. Topic switching — focus shifts when a new entity is introduced
    5. Ambiguity — two equally-recent entities of the same type
    6. Clarification requests — below-threshold confidence triggers a question
    7. Confidence ranking — recency, frequency, grammatical type all factor in

Modules under test:
    core/entity_tracker.py         EntityTracker, TrackedEntity
    cognitive/reference_resolver.py ReferenceResolver, ResolutionResult
"""

import pytest

from conversation.core.entity_tracker import (
    EntityTracker,
    TrackedEntity,
    SUPPORTED_ENTITY_TYPES,
    DEFAULT_RECENCY_WINDOW,
)
from conversation.cognitive.reference_resolver import (
    ReferenceResolver,
    ResolutionResult,
    AUTO_RESOLVE_THRESHOLD,
    CLARIFICATION_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_tracker(*entity_specs) -> EntityTracker:
    """
    Build an EntityTracker from a list of (name, type, confidence) tuples.
    Each tuple occupies one turn.
    """
    tracker = EntityTracker()
    for name, etype, conf in entity_specs:
        tracker.advance_turn()
        tracker.record_entity(name, etype, conf)
        tracker.end_turn()
    return tracker


def fresh_resolver() -> ReferenceResolver:
    return ReferenceResolver()


# ===========================================================================
# SCENARIO 1 — Single Entity
# ===========================================================================

class TestSingleEntity:
    """Track one entity; verify all metadata fields are correct."""

    def test_first_and_last_turn_set_on_registration(self):
        tracker = EntityTracker()
        tracker.advance_turn()  # turn = 1
        te = tracker.record_entity("Elon Musk", "person", 1.0)
        tracker.end_turn()

        assert te.first_appearance_turn == 1
        assert te.last_appearance_turn == 1

    def test_frequency_increments_on_re_mention(self):
        tracker = EntityTracker()
        tracker.advance_turn()
        tracker.record_entity("Elon Musk", "person", 1.0)
        tracker.end_turn()

        tracker.advance_turn()
        te2 = tracker.record_entity("Elon Musk", "person", 1.0)
        tracker.end_turn()

        assert te2.frequency == 2
        assert te2.last_appearance_turn == 2

    def test_single_entity_is_focus(self):
        tracker = make_tracker(("Elon Musk", "person", 1.0))
        focus = tracker.get_focus()
        assert focus is not None
        assert focus.name == "Elon Musk"

    def test_single_entity_is_active(self):
        tracker = make_tracker(("Elon Musk", "person", 1.0))
        active = tracker.get_active()
        assert len(active) == 1
        assert active[0].name == "Elon Musk"
        assert active[0].active is True

    def test_entity_type_stored_correctly(self):
        tracker = make_tracker(("Elon Musk", "person", 0.9))
        te = tracker.get_focus()
        assert te.entity_type == "person"

    def test_pronoun_resolves_to_single_entity(self):
        tracker = make_tracker(("Elon Musk", "person", 1.0))
        resolver = fresh_resolver()

        result = resolver.resolve("Where was he born?", tracker)

        assert result.referent is not None
        assert result.referent.name == "Elon Musk"
        assert result.needs_clarification is False
        assert "Elon Musk" in result.resolved_text

    def test_it_pronoun_resolves_to_single_non_person_entity(self):
        tracker = make_tracker(("Tesla", "organization", 1.0))
        resolver = fresh_resolver()

        result = resolver.resolve("When was it founded?", tracker)

        assert result.referent is not None
        assert result.referent.name == "Tesla"
        assert "Tesla" in result.resolved_text

    def test_no_reference_words_returns_original(self):
        tracker = make_tracker(("Elon Musk", "person", 1.0))
        resolver = fresh_resolver()

        result = resolver.resolve("Tell me about SpaceX.", tracker)

        assert result.resolved_text == "Tell me about SpaceX."
        assert result.referent is None
        assert result.needs_clarification is False
        assert result.reference_words_found == []

    def test_serialise_and_restore(self):
        tracker = make_tracker(("Elon Musk", "person", 1.0))
        snapshot = tracker.to_dict()

        restored = EntityTracker.from_dict(snapshot)
        focus = restored.get_focus()
        assert focus is not None
        assert focus.name == "Elon Musk"
        assert focus.frequency == 1

    def test_tracked_entity_to_dict(self):
        tracker = make_tracker(("Elon Musk", "person", 0.95))
        te = tracker.get_focus()
        d = te.to_dict()

        assert d["name"] == "Elon Musk"
        assert d["entity_type"] == "person"
        assert d["frequency"] == 1
        assert d["active"] is True
        assert "confidence" in d


# ===========================================================================
# SCENARIO 2 — Multiple Entities
# ===========================================================================

class TestMultipleEntities:
    """Track several entities simultaneously; verify ordering and focus."""

    def test_most_recent_entity_is_focus(self):
        tracker = make_tracker(
            ("Elon Musk", "person", 1.0),
            ("Tesla", "organization", 1.0),
        )
        focus = tracker.get_focus()
        assert focus.name == "Tesla"

    def test_all_entities_present(self):
        tracker = make_tracker(
            ("Elon Musk", "person", 1.0),
            ("Tesla", "organization", 1.0),
            ("SpaceX", "organization", 1.0),
        )
        all_entities = tracker.get_all()
        names = [e.name for e in all_entities]
        assert "Elon Musk" in names
        assert "Tesla" in names
        assert "SpaceX" in names

    def test_count_matches_unique_entities(self):
        tracker = make_tracker(
            ("Elon Musk", "person", 1.0),
            ("Tesla", "organization", 1.0),
            ("SpaceX", "organization", 1.0),
        )
        assert tracker.count() == 3

    def test_get_focus_by_type_returns_correct_entity(self):
        tracker = make_tracker(
            ("Elon Musk", "person", 1.0),
            ("Tesla", "organization", 1.0),
            ("Jeff Bezos", "person", 1.0),
        )
        person_focus = tracker.get_focus_by_type("person")
        assert person_focus is not None
        assert person_focus.name == "Jeff Bezos"  # most recent person

        org_focus = tracker.get_focus_by_type("organization")
        assert org_focus is not None
        assert org_focus.name == "Tesla"

    def test_find_by_name(self):
        tracker = make_tracker(
            ("Elon Musk", "person", 1.0),
            ("Tesla", "organization", 1.0),
        )
        found = tracker.find("Tesla")
        assert found is not None
        assert found.name == "Tesla"
        assert tracker.find("Nonexistent") is None

    def test_he_resolves_to_most_recent_person(self):
        tracker = make_tracker(
            ("Elon Musk", "person", 1.0),
            ("Jeff Bezos", "person", 1.0),
        )
        resolver = fresh_resolver()
        result = resolver.resolve("Where did he go to school?", tracker)

        assert result.referent is not None
        assert result.referent.name == "Jeff Bezos"

    def test_it_resolves_to_most_recent_non_person(self):
        tracker = make_tracker(
            ("Elon Musk", "person", 1.0),
            ("Tesla", "organization", 1.0),
        )
        resolver = fresh_resolver()
        result = resolver.resolve("When was it founded?", tracker)

        assert result.referent is not None
        assert result.referent.name == "Tesla"




# ===========================================================================
# SCENARIO 3 — Pronouns
# ===========================================================================

class TestPronouns:
    """All supported pronouns resolve correctly."""

    def _person_tracker(self) -> EntityTracker:
        return make_tracker(("Marie Curie", "person", 1.0))

    def _org_tracker(self) -> EntityTracker:
        return make_tracker(("OpenAI", "organization", 1.0))

    def test_he_resolves(self):
        tracker = make_tracker(("Albert Einstein", "person", 1.0))
        result = fresh_resolver().resolve("Where did he work?", tracker)
        assert "Albert Einstein" in result.resolved_text

    def test_she_resolves(self):
        result = fresh_resolver().resolve("What did she discover?", self._person_tracker())
        assert "Marie Curie" in result.resolved_text

    def test_him_resolves(self):
        tracker = make_tracker(("Isaac Newton", "person", 1.0))
        result = fresh_resolver().resolve("Tell me about him.", tracker)
        assert "Isaac Newton" in result.resolved_text

    def test_her_resolves(self):
        result = fresh_resolver().resolve("What awards did her work earn?", self._person_tracker())
        assert "Marie Curie" in result.resolved_text

    def test_they_resolves(self):
        result = fresh_resolver().resolve("When did they win the Nobel Prize?", self._person_tracker())
        assert "Marie Curie" in result.resolved_text

    def test_them_resolves(self):
        result = fresh_resolver().resolve("I want to learn more about them.", self._person_tracker())
        assert "Marie Curie" in result.resolved_text

    def test_it_resolves(self):
        result = fresh_resolver().resolve("When was it founded?", self._org_tracker())
        assert "OpenAI" in result.resolved_text

    def test_this_resolves(self):
        result = fresh_resolver().resolve("Can you explain this?", self._org_tracker())
        assert "OpenAI" in result.resolved_text

    def test_that_resolves(self):
        result = fresh_resolver().resolve("Tell me more about that.", self._org_tracker())
        assert "OpenAI" in result.resolved_text

    def test_these_resolves(self):
        result = fresh_resolver().resolve("How are these different?", self._org_tracker())
        assert "OpenAI" in result.resolved_text

    def test_those_resolves(self):
        result = fresh_resolver().resolve("What do those include?", self._org_tracker())
        assert "OpenAI" in result.resolved_text

    def test_reference_words_found_populated(self):
        tracker = self._person_tracker()
        result = fresh_resolver().resolve("Where was she born?", tracker)
        assert "she" in result.reference_words_found

    def test_was_resolved_true_when_rewritten(self):
        tracker = self._person_tracker()
        result = fresh_resolver().resolve("Where was she born?", tracker)
        assert result.was_resolved() is True

    def test_natural_language_the_person_resolves(self):
        tracker = make_tracker(("Albert Einstein", "person", 1.0))
        result = fresh_resolver().resolve("What did the person invent?", tracker)
        assert "Albert Einstein" in result.resolved_text

    def test_natural_language_the_company_resolves(self):
        tracker = make_tracker(("Apple", "organization", 1.0))
        result = fresh_resolver().resolve("When was the company founded?", tracker)
        assert "Apple" in result.resolved_text

    def test_natural_language_the_city_resolves(self):
        tracker = make_tracker(("Paris", "place", 1.0))
        result = fresh_resolver().resolve("How many people live in the city?", tracker)
        assert "Paris" in result.resolved_text

    def test_natural_language_the_country_resolves(self):
        tracker = make_tracker(("France", "place", 1.0))
        result = fresh_resolver().resolve("What is the capital of the country?", tracker)
        assert "France" in result.resolved_text


# ===========================================================================
# SCENARIO 4 — Topic Switching
# ===========================================================================

class TestTopicSwitching:
    """When a new entity is introduced, the conversation focus shifts."""

    def test_focus_shifts_after_new_entity(self):
        tracker = EntityTracker()

        # Turn 1: Elon Musk introduced
        tracker.advance_turn()
        tracker.record_entity("Elon Musk", "person", 1.0)
        tracker.end_turn()

        # Turn 2: Tesla introduced — focus should shift
        tracker.advance_turn()
        tracker.record_entity("Tesla", "organization", 1.0)
        tracker.end_turn()

        focus = tracker.get_focus()
        assert focus.name == "Tesla"

    def test_pronoun_resolves_to_new_focus_after_switch(self):
        tracker = EntityTracker()
        resolver = fresh_resolver()

        tracker.advance_turn()
        tracker.record_entity("Elon Musk", "person", 1.0)
        tracker.end_turn()

        # Topic switches to Tesla
        tracker.advance_turn()
        tracker.record_entity("Tesla", "organization", 1.0)
        tracker.end_turn()

        # "it" should now refer to Tesla
        result = resolver.resolve("When was it founded?", tracker)
        assert result.referent is not None
        assert result.referent.name == "Tesla"

    def test_person_pronoun_still_resolves_to_person_after_org_switch(self):
        tracker = EntityTracker()
        resolver = fresh_resolver()

        tracker.advance_turn()
        tracker.record_entity("Elon Musk", "person", 1.0)
        tracker.end_turn()

        # Tesla is now the overall focus
        tracker.advance_turn()
        tracker.record_entity("Tesla", "organization", 1.0)
        tracker.end_turn()

        # But "he" should still prefer person-type → Elon Musk
        result = resolver.resolve("How old is he?", tracker)
        assert result.referent is not None
        assert result.referent.name == "Elon Musk"

    def test_old_entity_still_in_tracker_after_switch(self):
        tracker = EntityTracker()

        tracker.advance_turn()
        tracker.record_entity("Elon Musk", "person", 1.0)
        tracker.end_turn()

        tracker.advance_turn()
        tracker.record_entity("Tesla", "organization", 1.0)
        tracker.end_turn()

        assert tracker.count() == 2
        assert tracker.find("Elon Musk") is not None

    def test_entity_becomes_inactive_after_recency_window(self):
        tracker = EntityTracker(recency_window=2)

        tracker.advance_turn()
        tracker.record_entity("Elon Musk", "person", 1.0)
        tracker.end_turn()

        # Advance 3 more turns without mentioning Elon Musk
        for _ in range(3):
            tracker.advance_turn()
            tracker.record_entity("Tesla", "organization", 1.0)
            tracker.end_turn()

        te = tracker.find("Elon Musk")
        assert te is not None
        assert te.active is False


# ===========================================================================
# SCENARIO 5 — Ambiguity
# ===========================================================================

class TestAmbiguity:
    """When two equally-recent entities compete, expect clarification or ranked resolution."""

    def test_two_recent_persons_same_turn_gap_triggers_clarification(self):
        """
        Two persons mentioned equally recently with the same confidence.
        Resolution should either clarify or resolve to one via ranking.
        The key assertion: the result object is consistent — if needs_clarification
        is True, a question is provided; if False, a referent is provided.
        """
        tracker = EntityTracker()
        tracker.advance_turn()
        tracker.record_entity("Elon Musk", "person", 0.9)
        tracker.end_turn()

        tracker.advance_turn()
        tracker.record_entity("Jeff Bezos", "person", 0.9)
        tracker.end_turn()

        resolver = fresh_resolver()
        result = resolver.resolve("Where was he born?", tracker)

        if result.needs_clarification:
            assert result.clarification_question is not None
            assert len(result.clarification_question) > 0
        else:
            # Resolver picked one; must still have a referent
            assert result.referent is not None

    def test_clarification_question_lists_candidate_names(self):
        """If clarification is requested, the question should name the candidates."""
        # Build two equally confident persons only 1 turn apart
        tracker = EntityTracker()
        tracker.advance_turn()
        tracker.record_entity("Alice", "person", 0.5)
        tracker.end_turn()

        tracker.advance_turn()
        tracker.record_entity("Bob", "person", 0.5)
        tracker.end_turn()

        resolver = ReferenceResolver(
            auto_resolve_threshold=0.90,   # make it very hard to auto-resolve
            clarification_threshold=0.50,
        )
        result = resolver.resolve("What did he say?", tracker)

        assert result.needs_clarification is True
        assert result.clarification_question is not None
        # At least one of the names should appear in the question
        assert "Alice" in result.clarification_question or "Bob" in result.clarification_question

    def test_ambiguous_result_has_no_resolution_when_clarification_needed(self):
        tracker = EntityTracker()
        tracker.advance_turn()
        tracker.record_entity("Alice", "person", 0.5)
        tracker.end_turn()

        tracker.advance_turn()
        tracker.record_entity("Bob", "person", 0.5)
        tracker.end_turn()

        resolver = ReferenceResolver(
            auto_resolve_threshold=0.99,
            clarification_threshold=0.50,
        )
        result = resolver.resolve("What did he say?", tracker)

        assert result.needs_clarification is True
        # resolved_text should equal original when clarification is needed
        assert result.resolved_text == result.original_text

    def test_no_entities_tracked_produces_clarification(self):
        tracker = EntityTracker()  # empty
        resolver = fresh_resolver()

        result = resolver.resolve("What did he do?", tracker)

        assert result.needs_clarification is True
        assert result.clarification_question is not None
        assert result.referent is None

    def test_to_dict_includes_all_fields(self):
        tracker = EntityTracker()
        resolver = fresh_resolver()
        result = resolver.resolve("What did he do?", tracker)
        d = result.to_dict()

        for key in (
            "resolved_text", "original_text", "referent",
            "confidence", "needs_clarification",
            "clarification_question", "reference_words_found", "was_resolved"
        ):
            assert key in d


# ===========================================================================
# SCENARIO 6 — Clarification Requests
# ===========================================================================

class TestClarificationRequests:
    """Low-confidence situations produce well-formed clarification questions."""

    def test_no_context_triggers_person_clarification(self):
        tracker = EntityTracker()
        resolver = fresh_resolver()

        result = resolver.resolve("Where was he born?", tracker)

        assert result.needs_clarification is True
        assert result.clarification_question is not None
        q = result.clarification_question.lower()
        assert "person" in q or "referring" in q or "who" in q

    def test_no_context_triggers_company_clarification(self):
        tracker = EntityTracker()
        resolver = fresh_resolver()

        result = resolver.resolve("When was the company founded?", tracker)

        assert result.needs_clarification is True
        assert result.clarification_question is not None
        q = result.clarification_question.lower()
        assert "company" in q or "organisation" in q or "clarify" in q

    def test_clarification_not_triggered_when_confident(self):
        tracker = make_tracker(("Elon Musk", "person", 1.0))
        resolver = fresh_resolver()

        result = resolver.resolve("Where was he born?", tracker)

        assert result.needs_clarification is False

    def test_custom_threshold_controls_clarification(self):
        """A resolver with a very high clarification threshold always clarifies."""
        tracker = make_tracker(("Elon Musk", "person", 0.8))
        resolver = ReferenceResolver(
            auto_resolve_threshold=0.99,
            clarification_threshold=0.99,
        )

        result = resolver.resolve("Where was he born?", tracker)

        assert result.needs_clarification is True
        assert result.clarification_question is not None

    def test_clarification_question_non_empty_string(self):
        tracker = EntityTracker()
        resolver = fresh_resolver()

        result = resolver.resolve("What did she say?", tracker)

        assert isinstance(result.clarification_question, str)
        assert len(result.clarification_question.strip()) > 0

    def test_confidence_zero_when_no_entities(self):
        tracker = EntityTracker()
        resolver = fresh_resolver()

        result = resolver.resolve("Where did he go?", tracker)

        assert result.confidence == 0.0

    def test_result_resolved_text_unchanged_when_clarification(self):
        tracker = EntityTracker()
        resolver = fresh_resolver()

        original = "Who did he work for?"
        result = resolver.resolve(original, tracker)

        assert result.needs_clarification is True
        assert result.resolved_text == original


# ===========================================================================
# SCENARIO 7 — Confidence Ranking
# ===========================================================================

class TestConfidenceRanking:
    """Recency, frequency, grammatical type, and entity confidence drive ranking."""

    def test_more_recent_entity_ranked_higher(self):
        tracker = EntityTracker()

        tracker.advance_turn()
        tracker.record_entity("Albert Einstein", "person", 1.0)
        tracker.end_turn()

        # Einstein is now 2 turns old; Newton is fresh
        tracker.advance_turn()
        tracker.record_entity("Isaac Newton", "person", 1.0)
        tracker.end_turn()

        resolver = fresh_resolver()
        result = resolver.resolve("Where was he born?", tracker)

        assert result.referent is not None
        assert result.referent.name == "Isaac Newton"

    def test_higher_frequency_breaks_tie(self):
        """
        Frequency contributes to ranking alongside recency.

        Scoring formula: recency (0-4) + frequency (capped 0-2) + confidence (0-1)
        + grammatical match (1.5).

        When Elon Musk has freq=3 (score ~1.2 from frequency) and Jeff Bezos
        has freq=1 but is 1 turn more recent (score +0.5 from recency), Elon's
        frequency advantage (1.2) outweighs Jeff's recency advantage (0.5).
        Therefore Elon ranks higher despite being mentioned 1 turn earlier.
        """
        tracker = EntityTracker()

        # Mention Elon Musk 3 times (turns 1-3)
        for _ in range(3):
            tracker.advance_turn()
            tracker.record_entity("Elon Musk", "person", 0.8)
            tracker.end_turn()

        # Mention Jeff Bezos once (turn 4 — more recent by 1 turn)
        tracker.advance_turn()
        tracker.record_entity("Jeff Bezos", "person", 0.8)
        tracker.end_turn()

        candidates = tracker.get_active()
        ranked = tracker.rank_candidates(candidates, pronoun="he")

        # Elon Musk ranks first: frequency bonus (3×0.4=1.2) beats
        # Jeff Bezos's 1-turn recency advantage (0.5).
        assert ranked[0].name == "Elon Musk"
        assert len(ranked) == 2

        # In a scenario where both are equally recent and frequency differs:
        tracker2 = EntityTracker()
        tracker2.advance_turn()
        tracker2.record_entity("Alice", "person", 0.8)
        tracker2.record_entity("Bob", "person", 0.8)   # same turn as Alice

        # Mention Alice one extra time (freq = 2 for Alice, Bob stays at 1)
        tracker2.end_turn()
        tracker2.advance_turn()
        tracker2.record_entity("Alice", "person", 0.8)
        tracker2.end_turn()

        # Alice was last seen at turn 2, Bob at turn 1.
        # Alice is both more recent AND has higher frequency → Alice ranks first.
        cands2 = tracker2.get_all()
        ranked2 = tracker2.rank_candidates(cands2, pronoun="she")
        assert ranked2[0].name == "Alice"

    def test_person_pronoun_prefers_person_over_org(self):
        tracker = EntityTracker()

        tracker.advance_turn()
        tracker.record_entity("Elon Musk", "person", 0.9)
        tracker.end_turn()

        # Org mentioned more recently
        tracker.advance_turn()
        tracker.record_entity("Tesla", "organization", 0.9)
        tracker.end_turn()

        resolver = fresh_resolver()
        result = resolver.resolve("How old is he?", tracker)

        assert result.referent is not None
        assert result.referent.name == "Elon Musk"

    def test_thing_pronoun_prefers_org_over_person(self):
        tracker = EntityTracker()

        # Person mentioned more recently
        tracker.advance_turn()
        tracker.record_entity("Tesla", "organization", 0.9)
        tracker.end_turn()

        tracker.advance_turn()
        tracker.record_entity("Elon Musk", "person", 0.9)
        tracker.end_turn()

        resolver = fresh_resolver()
        result = resolver.resolve("When was it founded?", tracker)

        assert result.referent is not None
        assert result.referent.name == "Tesla"

    def test_higher_base_confidence_wins_when_all_else_equal(self):
        tracker = EntityTracker()

        tracker.advance_turn()
        tracker.record_entity("Alice", "person", 0.5)
        tracker.record_entity("Bob", "person", 0.95)  # both same turn
        tracker.end_turn()

        candidates = tracker.get_all()
        ranked = tracker.rank_candidates(candidates, pronoun="he")

        # Bob has higher confidence; same recency → Bob should rank first
        assert ranked[0].name == "Bob"

    def test_rank_candidates_returns_empty_for_empty_input(self):
        tracker = EntityTracker()
        result = tracker.rank_candidates([])
        assert result == []

    def test_resolution_confidence_high_for_single_recent_entity(self):
        tracker = make_tracker(("Elon Musk", "person", 1.0))
        resolver = fresh_resolver()

        result = resolver.resolve("Where was he born?", tracker)

        assert result.confidence >= AUTO_RESOLVE_THRESHOLD

    def test_resolution_confidence_lower_with_stale_entity(self):
        """An entity last seen many turns ago has lower resolution confidence."""
        tracker = EntityTracker(recency_window=10)

        tracker.advance_turn()
        tracker.record_entity("Elon Musk", "person", 1.0)
        tracker.end_turn()

        # Advance 6 more turns without mentioning Elon Musk
        for _ in range(6):
            tracker.advance_turn()
            tracker.end_turn()

        resolver = fresh_resolver()
        result = resolver.resolve("Where was he born?", tracker)

        # Should still resolve (entity is still active in 10-turn window)
        # but confidence is lower than a fresh mention
        assert result.confidence < 1.0

    def test_elon_musk_multi_turn_scenario(self):
        """
        Full multi-turn scenario:
          Turn 1: "Tell me about Elon Musk."
          Turn 2: "Where was he born?"      → resolves to Elon Musk
          Turn 3: "When did he start Tesla?" → resolves to Elon Musk
          Turn 4: "What companies does he own?" → resolves to Elon Musk
        """
        tracker = EntityTracker()
        resolver = fresh_resolver()

        # Turn 1
        tracker.advance_turn()
        tracker.record_entity("Elon Musk", "person", 1.0)
        tracker.end_turn()

        # Turn 2
        tracker.advance_turn()
        r2 = resolver.resolve("Where was he born?", tracker)
        tracker.end_turn()
        assert r2.referent.name == "Elon Musk"
        assert not r2.needs_clarification

        # Turn 3
        tracker.advance_turn()
        r3 = resolver.resolve("When did he start Tesla?", tracker)
        tracker.end_turn()
        assert r3.referent.name == "Elon Musk"
        assert not r3.needs_clarification

        # Turn 4
        tracker.advance_turn()
        r4 = resolver.resolve("What companies does he own?", tracker)
        tracker.end_turn()
        assert r4.referent.name == "Elon Musk"
        assert not r4.needs_clarification


# ===========================================================================
# EntityTracker: unit tests for core mechanics
# ===========================================================================

class TestEntityTrackerMechanics:
    """Low-level tracker behaviour: turn counter, reset, supported types."""

    def test_turn_counter_starts_at_zero(self):
        tracker = EntityTracker()
        assert tracker.current_turn() == 0

    def test_advance_turn_increments(self):
        tracker = EntityTracker()
        t1 = tracker.advance_turn()
        t2 = tracker.advance_turn()
        assert t1 == 1
        assert t2 == 2

    def test_record_entity_auto_advances_turn(self):
        tracker = EntityTracker()
        assert tracker.current_turn() == 0
        tracker.record_entity("X", "concept", 1.0)
        assert tracker.current_turn() == 1

    def test_end_turn_then_record_advances_again(self):
        tracker = EntityTracker()
        tracker.record_entity("X", "concept", 1.0)  # turn 1
        tracker.end_turn()
        tracker.record_entity("Y", "concept", 1.0)  # turn 2
        assert tracker.current_turn() == 2

    def test_reset_clears_all_state(self):
        tracker = make_tracker(("Elon Musk", "person", 1.0))
        tracker.reset()
        assert tracker.count() == 0
        assert tracker.current_turn() == 0
        assert tracker.get_focus() is None

    def test_unsupported_entity_type_becomes_unknown(self):
        tracker = EntityTracker()
        tracker.advance_turn()
        te = tracker.record_entity("X", "martian", 1.0)
        tracker.end_turn()
        assert te.entity_type == "unknown"

    def test_all_supported_types_accepted(self):
        tracker = EntityTracker()
        for i, etype in enumerate(SUPPORTED_ENTITY_TYPES):
            tracker.advance_turn()
            te = tracker.record_entity(f"Entity_{i}", etype, 1.0)
            tracker.end_turn()
            assert te.entity_type == etype

    def test_aliases_stored_on_entity(self):
        tracker = EntityTracker()
        tracker.advance_turn()
        tracker.record_entity("Elon Musk", "person", 1.0, aliases=["Musk"])
        tracker.end_turn()

        te = tracker.find("Musk")
        assert te is not None
        assert te.name == "Elon Musk"

    def test_count_active_decreases_after_recency_window(self):
        tracker = EntityTracker(recency_window=2)

        tracker.advance_turn()
        tracker.record_entity("A", "person", 1.0)
        tracker.end_turn()

        # 3 more turns with a different entity
        for _ in range(3):
            tracker.advance_turn()
            tracker.record_entity("B", "person", 1.0)
            tracker.end_turn()

        # A should be inactive now (3 turns since last mention, window=2)
        assert tracker.count_active() == 1  # only B
        assert tracker.count() == 2          # both still tracked

    def test_repr_contains_key_info(self):
        tracker = make_tracker(("X", "concept", 1.0))
        r = repr(tracker)
        assert "EntityTracker" in r
        assert "turn=" in r
