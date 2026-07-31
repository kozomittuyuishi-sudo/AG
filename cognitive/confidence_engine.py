"""
cognitive/confidence_engine.py
===============================
AG Phase 2 — ConfidenceEngine

Every context resolution produces a confidence score.  The ConfidenceEngine
centralises all confidence decisions so they are consistent, auditable, and
easy to tune.

Scoring contract
----------------
    1.0 — Certain.  The input is self-contained; no resolution needed.
    0.9–0.99 — Very high.  A single, unambiguous referent was found.
    0.7–0.89 — High.  A plausible referent was found; some residual ambiguity.
    0.5–0.69 — Medium.  Multiple candidates; one was selected heuristically.
    0.3–0.49 — Low.  Weak evidence; a clarification question is preferred.
    0.0–0.29 — Very low.  No useful context found.  Ask the user.

Thresholds
----------
    AUTO_RESOLVE_THRESHOLD  (default 0.70)
        At or above this score the resolver rewrites automatically.
    CLARIFICATION_THRESHOLD (default 0.50)
        Below this score the pipeline asks the user for clarification.
        Between CLARIFICATION_THRESHOLD and AUTO_RESOLVE_THRESHOLD the
        resolver still rewrites but marks the resolution as tentative.

Design principles:
    - No LLM calls. Purely algorithmic.
    - All decisions are explained in the Thought's reasoning_log.
    - Thresholds are configurable at construction time.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.thought import Thought

# Default thresholds
AUTO_RESOLVE_THRESHOLD: float = 0.70
CLARIFICATION_THRESHOLD: float = 0.50


class ResolutionScore:
    """
    Container for the result of a single confidence evaluation.

    Attributes
    ----------
    score : float
        Numeric confidence in [0.0, 1.0].
    should_auto_resolve : bool
        True if the resolver should rewrite without asking the user.
    should_ask_user : bool
        True if the resolver should request clarification before proceeding.
    reason : str
        One-sentence human-readable explanation.
    evidence : List[str]
        Supporting evidence items that contributed to this score.
    """

    def __init__(
        self,
        score: float,
        reason: str,
        evidence: Optional[List[str]] = None,
        auto_threshold: float = AUTO_RESOLVE_THRESHOLD,
        clarification_threshold: float = CLARIFICATION_THRESHOLD,
    ) -> None:
        self.score: float = max(0.0, min(1.0, float(score)))
        self.reason: str = str(reason)
        self.evidence: List[str] = list(evidence or [])
        self.should_auto_resolve: bool = self.score >= auto_threshold
        self.should_ask_user: bool = self.score < clarification_threshold

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "reason": self.reason,
            "evidence": list(self.evidence),
            "should_auto_resolve": self.should_auto_resolve,
            "should_ask_user": self.should_ask_user,
        }

    def __repr__(self) -> str:
        return (
            f"ResolutionScore(score={self.score:.2f}, "
            f"auto={self.should_auto_resolve}, ask={self.should_ask_user}, "
            f"reason={self.reason!r})"
        )


class ConfidenceEngine:
    """
    Centralized confidence scoring for context resolution decisions.

    Usage
    -----
    ::

        engine = ConfidenceEngine()
        score = engine.score_entity_resolution(
            referent_text="he",
            candidate_entity="Albert Einstein",
            candidate_confidence=0.95,
            turns_since_mention=1,
        )
        if score.should_auto_resolve:
            ...
        elif score.should_ask_user:
            ...
    """

    def __init__(
        self,
        auto_threshold: float = AUTO_RESOLVE_THRESHOLD,
        clarification_threshold: float = CLARIFICATION_THRESHOLD,
    ) -> None:
        self._auto_threshold = auto_threshold
        self._clarification_threshold = clarification_threshold

    # ------------------------------------------------------------------
    # Primary scoring methods
    # ------------------------------------------------------------------

    def score_entity_resolution(
        self,
        referent_text: str,
        candidate_entity: str,
        candidate_confidence: float,
        turns_since_mention: int = 0,
        alternative_candidates: Optional[List[str]] = None,
    ) -> ResolutionScore:
        """
        Score how confident we are that ``referent_text`` (e.g. "he", "she",
        "the scientist") refers to ``candidate_entity``.

        :param referent_text: The pronoun or short reference from the user.
        :param candidate_entity: The entity name we think it refers to.
        :param candidate_confidence: The EntityRegistry confidence for the candidate.
        :param turns_since_mention: How many turns ago the entity was last mentioned.
                                     0 = mentioned this turn or last turn.
        :param alternative_candidates: Other possible referents (reduces score).
        :returns: ResolutionScore.
        """
        evidence: List[str] = []
        score = float(candidate_confidence)

        # Recency penalty: each turn of distance costs 0.12 confidence
        recency_penalty = min(turns_since_mention * 0.12, 0.48)
        if recency_penalty > 0:
            score -= recency_penalty
            evidence.append(
                f"Recency penalty: -{recency_penalty:.2f} "
                f"({turns_since_mention} turns since last mention)"
            )

        # Ambiguity penalty: multiple candidates reduce confidence
        alternatives = list(alternative_candidates or [])
        if alternatives:
            n = len(alternatives)
            ambiguity_penalty = min(n * 0.15, 0.45)
            score -= ambiguity_penalty
            evidence.append(
                f"Ambiguity penalty: -{ambiguity_penalty:.2f} "
                f"({n} alternative candidate(s): {alternatives})"
            )
        else:
            evidence.append("No competing candidates — unambiguous referent.")

        # Boost for very short/clear pronouns with a single recent candidate
        if (
            referent_text.lower().strip() in {"he", "she", "they", "it", "his", "her", "their"}
            and turns_since_mention <= 1
            and not alternatives
        ):
            score = min(score + 0.05, 1.0)
            evidence.append("Pronoun + recent single candidate: small boost applied.")

        score = max(0.0, min(1.0, score))
        reason = (
            f"'{referent_text}' → '{candidate_entity}' "
            f"(base confidence {candidate_confidence:.2f}, "
            f"final {score:.2f})"
        )
        return self._make_score(score, reason, evidence)

    def score_topic_continuation(
        self,
        user_input: str,
        current_topic: str,
        turns_on_topic: int = 1,
    ) -> ResolutionScore:
        """
        Score confidence that the user is continuing the current topic.

        :param user_input: The raw user utterance.
        :param current_topic: The active topic label.
        :param turns_on_topic: Number of consecutive turns already on this topic.
        :returns: ResolutionScore.
        """
        evidence: List[str] = []
        base = 0.80

        # Longer threads increase confidence
        thread_boost = min(turns_on_topic * 0.04, 0.16)
        base += thread_boost
        if thread_boost > 0:
            evidence.append(f"Thread depth boost: +{thread_boost:.2f} ({turns_on_topic} turns on topic).")

        # Short input is more likely a continuation
        word_count = len(str(user_input).split())
        if word_count <= 4:
            base += 0.05
            evidence.append(f"Short input ({word_count} words): likely continuation.")

        # Input already contains the topic — very high confidence
        if current_topic.lower() in user_input.lower():
            base = min(base + 0.10, 1.0)
            evidence.append(f"Topic label '{current_topic}' appears in input: strong signal.")

        base = max(0.0, min(1.0, base))
        reason = f"Continuation of topic '{current_topic}' (score {base:.2f})."
        return self._make_score(base, reason, evidence)

    def score_self_contained(self, user_input: str) -> ResolutionScore:
        """
        Score how self-contained an input is — i.e. how little context
        resolution it needs.

        A high score here means the brain can receive the raw input unchanged.

        :param user_input: The raw user utterance.
        :returns: ResolutionScore.
        """
        evidence: List[str] = []
        text = str(user_input).strip()
        words = text.lower().split()
        word_count = len(words)

        score = 1.0

        # Pronoun presence reduces self-containedness
        PRONOUNS = {"he", "she", "it", "they", "his", "her", "their", "this", "that", "those", "these"}
        found_pronouns = [w for w in words if w in PRONOUNS]
        if found_pronouns:
            penalty = min(len(found_pronouns) * 0.20, 0.60)
            score -= penalty
            evidence.append(
                f"Pronouns found: {found_pronouns} — penalty -{penalty:.2f}."
            )

        # Very short inputs are often incomplete
        if word_count <= 3:
            score -= 0.15
            evidence.append(f"Very short input ({word_count} words): likely incomplete.")
        elif word_count <= 6:
            score -= 0.05
            evidence.append(f"Short input ({word_count} words): possibly incomplete.")

        # Questions ending with a pronoun are almost certainly incomplete
        if text.endswith("?") and words and words[-2] in PRONOUNS:
            score -= 0.20
            evidence.append("Question ends with a pronoun — almost certainly needs context.")

        score = max(0.0, min(1.0, score))
        reason = f"Input self-containedness score: {score:.2f}."
        return self._make_score(score, reason, evidence)

    def score_no_context_available(self) -> ResolutionScore:
        """
        Return a zero-confidence score used when there is no context to
        resolve against (empty entity registry, no topic, no history).

        :returns: ResolutionScore with score 0.0.
        """
        return self._make_score(
            0.0,
            "No context available — cannot resolve reference.",
            ["Entity registry empty.", "No active topic.", "No conversation history."],
        )

    def combine(self, scores: List[ResolutionScore], weights: Optional[List[float]] = None) -> ResolutionScore:
        """
        Combine multiple ResolutionScores into a single weighted score.

        :param scores: List of ResolutionScore objects.
        :param weights: Optional weights (same length as scores). Equal weights used if None.
        :returns: Combined ResolutionScore.
        """
        if not scores:
            return self.score_no_context_available()

        if weights is None:
            weights = [1.0] * len(scores)

        if len(weights) != len(scores):
            weights = [1.0] * len(scores)

        total_weight = sum(weights) or 1.0
        combined = sum(s.score * w for s, w in zip(scores, weights)) / total_weight

        evidence = []
        for s in scores:
            evidence.extend(s.evidence)

        reason = f"Combined score {combined:.2f} from {len(scores)} source(s)."
        return self._make_score(combined, reason, evidence)

    # ------------------------------------------------------------------
    # Thought annotation helper
    # ------------------------------------------------------------------

    def annotate_thought(self, thought: "Thought", score: ResolutionScore) -> None:
        """
        Write a ResolutionScore into a Thought object's confidence field
        and reasoning log.

        :param thought: The Thought to annotate.
        :param score: The ResolutionScore produced by any scoring method.
        """
        thought.confidence = score.score
        thought.log("confidence_engine", score.reason)
        for ev in score.evidence:
            thought.log("confidence_engine.evidence", ev)
        if score.should_ask_user:
            thought.log("confidence_engine", "Confidence below clarification threshold — will ask user.")
        elif score.should_auto_resolve:
            thought.log("confidence_engine", "Confidence above auto-resolve threshold — will rewrite automatically.")
        else:
            thought.log("confidence_engine", "Confidence is in the tentative range — resolving with caution.")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _make_score(self, score: float, reason: str, evidence: List[str]) -> ResolutionScore:
        return ResolutionScore(
            score=score,
            reason=reason,
            evidence=evidence,
            auto_threshold=self._auto_threshold,
            clarification_threshold=self._clarification_threshold,
        )
