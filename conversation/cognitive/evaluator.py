"""
cognitive/evaluator.py
=======================
AG Phase 2 — CognitiveEvaluator

The CognitiveEvaluator is the first stage in the pipeline after a Thought
is created.  Its only job is to understand the user's message.

It NEVER answers questions.
It NEVER calls the Brain.
It NEVER generates responses.
It NEVER uses hardcoded keyword lists for pronouns ("he", "she", "it").

For every input it determines:
    1. What is the user's intent?
    2. Is the sentence grammatically / semantically complete?
    3. What information is missing to answer this question?
    4. Does context resolution need to happen?
    5. What entities are explicitly mentioned?
    6. How confident are we about the above?
    7. Should we ask the user for clarification before proceeding?

The evaluator uses structural reasoning rather than keyword matching:
    "What information is missing from this sentence to make it answerable?"

After evaluation, it populates the Thought object and returns it.

Design principles:
    - Deterministic. No LLM calls.
    - Reason structurally: detect information gaps, not specific words.
    - Feed the ContextResolver enough information to do its job.
    - Log every decision in the Thought's reasoning_log.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.thought import Thought

from conversation.cognitive.confidence_engine import ConfidenceEngine, ResolutionScore


# ---------------------------------------------------------------------------
# Sentence completeness patterns
#
# Rather than checking for specific pronouns, these patterns ask structural
# questions about the sentence:
#   - Does the sentence have an explicit subject?
#   - Is a subject-slot clearly occupied by a reference word?
#   - Could this sentence stand alone without prior context?
# ---------------------------------------------------------------------------

# Pattern: sentence begins with a verb (no explicit subject)
# e.g. "Tell me more", "Explain that", "Give me an example"
_IMPERATIVE_RE = re.compile(
    r"^(tell|show|give|explain|describe|compare|list|define|summarise|"
    r"summarize|find|search|calculate|translate|convert|what|where|when|"
    r"who|why|how)\b",
    re.IGNORECASE,
)

# Pattern: reference words that imply a subject not present in the sentence.
# These are not "magic keywords" — they are grammatical reference markers.
# We detect that a reference slot exists, not that a specific word was used.
_REFERENCE_WORD_RE = re.compile(
    r"\b(he|she|it|they|him|her|them|his|hers|its|their|theirs"
    r"|this|that|these|those"
    r"|there|here"
    r"|the one|the thing|the place|the person"
    r"|same|similar|aforementioned)\b",
    re.IGNORECASE,
)

# Short-continuation patterns: phrases that are grammatically dependent
# on a prior turn to be meaningful.
_CONTINUATION_RE = re.compile(
    r"^(tell me more|more about|what about|and|but|also|so|"
    r"go on|continue|another one|one more|next one|the other|"
    r"give me an example|give me examples?|"
    r"simplify (that|it|this)|why(\s+though)?|how so|"
    r"elaborate|expand on (that|it|this)|"
    r"is that right|really|seriously\??|"
    r"and (what|who|where|when|why|how)\b)(.*)$",
    re.IGNORECASE,
)

# Question words without a noun phrase — implies a missing subject
_BARE_WH_RE = re.compile(
    r"^(what|who|where|when|how|why)\s+(is|was|are|were|did|does|do)?\s*"
    r"(he|she|it|they|that|this|the \w+)?\s*\??$",
    re.IGNORECASE,
)

# Explicit entity name patterns (basic NER without an LLM)
# Detects:
#   - Capitalized multi-word names: "Albert Einstein", "Isaac Newton"
#   - Single capitalized names that aren't at sentence start: "Einstein said"
#   - Country / city names (heuristic: capitalized after common prepositions)
_CAPITALIZED_NAME_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")
_SINGLE_CAP_RE = re.compile(r"(?<!\.\s)(?<!\!\s)(?<!\?\s)(?<!\n)\b([A-Z][a-z]{2,})\b")

# Known entity-introducing phrases that help type the entity
_PERSON_INTRO_RE = re.compile(
    r"\b(who is|who was|tell me about|explain|about)\s+([A-Z][a-zA-Z\s]+?)(?:\?|$)",
    re.IGNORECASE,
)

_CONCEPT_INTRO_RE = re.compile(
    r"\b(what is|what are|explain|define|describe)\s+([a-z][a-zA-Z\s]+?)(?:\?|$)",
    re.IGNORECASE,
)


class MissingInformationReason:
    """Named reasons for missing information — used in reasoning logs."""
    NO_SUBJECT = "The sentence has no explicit subject."
    REFERENCE_WORD = "A reference word implies a subject not present in this sentence."
    CONTINUATION = "The sentence is a continuation fragment that depends on prior context."
    BARE_WH_QUESTION = "A wh-question is missing its noun subject."
    IMPLICIT_COMPARISON = "A comparison is implied but the referent is not stated."
    TOO_SHORT = "The sentence is too short to be self-contained."


class EvaluationResult:
    """
    Structured output of a single evaluation pass.
    The evaluator populates this before writing to the Thought.
    """

    def __init__(self) -> None:
        self.intent: Optional[str] = None
        self.requires_context: bool = False
        self.missing_information: List[str] = []
        self.detected_entities: List[Dict[str, Any]] = []
        self.confidence: float = 1.0
        self.ask_for_clarification: bool = False
        self.clarification_question: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "requires_context": self.requires_context,
            "missing_information": list(self.missing_information),
            "detected_entities": list(self.detected_entities),
            "confidence": self.confidence,
            "ask_for_clarification": self.ask_for_clarification,
            "clarification_question": self.clarification_question,
        }


class CognitiveEvaluator:
    """
    First pipeline stage after Thought creation.

    Analyses the user's input structurally to determine:
        - intent
        - whether context is needed
        - what information is missing
        - explicit entity mentions
        - whether to ask the user for clarification

    Usage
    -----
    ::

        evaluator = CognitiveEvaluator()
        thought = evaluator.evaluate(thought, intent_from_ag=detect_intent(raw))
        # thought.requires_context, thought.missing_information, etc. are now set
    """

    def __init__(self, confidence_engine: Optional[ConfidenceEngine] = None) -> None:
        self._confidence = confidence_engine or ConfidenceEngine()

    # ------------------------------------------------------------------
    # Primary entry point
    # ------------------------------------------------------------------

    def evaluate(self, thought: "Thought", intent_from_ag: Optional[str] = None) -> "Thought":
        """
        Evaluate the Thought and populate all evaluator-owned fields.

        :param thought: The Thought object to evaluate (mutated in-place).
        :param intent_from_ag: Optional intent label from Ag.py's ``detect_intent()``.
                                If provided it is used as the primary intent;
                                otherwise the evaluator classifies it internally.
        :returns: The mutated Thought (for chaining).
        """
        thought.log("evaluator", f"Evaluating input: {thought.raw_input!r}")

        # 1. Set intent
        intent = intent_from_ag or self._classify_intent(thought.raw_input)
        thought.set_intent(intent)
        thought.log("evaluator", f"Intent classified as: {intent!r}")

        # 2. Extract explicit entity mentions
        entities = self._extract_entities(thought.raw_input)
        for ent in entities:
            thought.add_entity(ent["name"], ent["type"])
        if entities:
            thought.log("evaluator", f"Entities extracted: {[e['name'] for e in entities]}")
        else:
            thought.log("evaluator", "No explicit entities detected in input.")

        # 3. Completeness analysis — what is missing?
        missing, requires_context = self._analyze_completeness(thought.raw_input, intent)
        thought.requires_context = requires_context
        for reason in missing:
            thought.flag_missing(reason)
        if missing:
            thought.log("evaluator", f"Missing information detected: {missing}")
        else:
            thought.log("evaluator", "Input appears self-contained.")

        # 4. Confidence scoring
        self_contained_score = self._confidence.score_self_contained(thought.raw_input)
        thought.confidence = self_contained_score.score
        thought.log(
            "evaluator",
            f"Self-containedness confidence: {self_contained_score.score:.2f} — {self_contained_score.reason}",
        )

        # 5. Clarification gate
        # We only ask immediately if there is NO prior context that could resolve it.
        # The ContextResolver will make the final call after inspecting WorkingMemory.
        # Here we just mark it if the input is extremely incomplete and standalone.
        if (
            requires_context
            and self_contained_score.score < self._confidence._clarification_threshold
            and not entities
        ):
            thought.log(
                "evaluator",
                "Low confidence + no entities + requires context: flagging for potential clarification.",
            )
            # Don't ask immediately — let ContextResolver try first
            # (it has access to WorkingMemory which we don't)

        thought.log("evaluator", "Evaluation complete.")
        return thought

    # ------------------------------------------------------------------
    # Intent classification (lightweight; Ag.py's detect_intent takes priority)
    # ------------------------------------------------------------------

    def _classify_intent(self, raw_input: str) -> str:
        """
        Classify the intent when Ag.py has not already done so.
        Returns a broad category string.
        """
        text = raw_input.strip().lower().replace("?", "")

        if not text:
            return "unknown"
        if text in {"exit", "quit", "shutdown", "bye"}:
            return "shutdown"
        if text in {"hello", "hi", "hey"}:
            return "greeting"
        if text.startswith("remember "):
            return "remember"
        if text.startswith("add task "):
            return "add_task"
        # Broad catch-all
        return "unknown"

    # ------------------------------------------------------------------
    # Completeness analysis
    # ------------------------------------------------------------------

    def _analyze_completeness(
        self, raw_input: str, intent: str
    ) -> tuple:
        """
        Determine what information is missing from the input.

        Returns (list_of_missing_reasons, requires_context: bool).

        Uses structural reasoning, not keyword matching.
        """
        text = raw_input.strip()
        missing: List[str] = []

        # Intents that are self-contained by definition
        ALWAYS_COMPLETE = {
            "greeting", "shutdown", "remember", "recall",
            "show_memory", "open_memory_file", "project_status",
            "project_name", "next_step", "completed_milestones",
            "add_task", "show_tasks", "complete_task",
            "show_completed_tasks", "current_version",
            "set_brain_local", "set_brain_cloud", "set_brain_auto",
            "brain_status", "cloud_brain",
        }
        if intent in ALWAYS_COMPLETE:
            return [], False

        # Check 1: Continuation fragment?
        if _CONTINUATION_RE.match(text):
            missing.append(MissingInformationReason.CONTINUATION)

        # Check 2: Reference words present?
        ref_matches = _REFERENCE_WORD_RE.findall(text)
        if ref_matches:
            unique_refs = list(dict.fromkeys(r.lower() for r in ref_matches))
            missing.append(
                f"{MissingInformationReason.REFERENCE_WORD} "
                f"(reference words: {unique_refs})"
            )

        # Check 3: Bare wh-question?
        if _BARE_WH_RE.match(text.rstrip("?")):
            missing.append(MissingInformationReason.BARE_WH_QUESTION)

        # Check 4: Very short input that isn't a named command?
        word_count = len(text.split())
        if word_count <= 2 and intent == "unknown":
            missing.append(
                f"{MissingInformationReason.TOO_SHORT} ({word_count} word(s))"
            )

        # Check 5: Implicit comparison?
        if re.search(r"\b(same|similar|different|better|worse|compared?)\b", text, re.IGNORECASE):
            if not re.search(r"\b(than|to|from|with)\b\s+\w+", text, re.IGNORECASE):
                missing.append(MissingInformationReason.IMPLICIT_COMPARISON)

        requires_context = len(missing) > 0
        return missing, requires_context

    # ------------------------------------------------------------------
    # Entity extraction
    # ------------------------------------------------------------------

    def _extract_entities(self, raw_input: str) -> List[Dict[str, Any]]:
        """
        Extract explicit entity mentions from the input.
        Returns a list of {"name": str, "type": str} dicts.

        Uses structural heuristics (capitalization, introducing phrases)
        rather than a fixed entity list.
        """
        entities: List[Dict[str, Any]] = []
        seen_names: set = set()

        def _add(name: str, entity_type: str) -> None:
            clean = name.strip()
            if clean and clean.lower() not in seen_names:
                seen_names.add(clean.lower())
                entities.append({"name": clean, "type": entity_type})

        # Pattern 1: person-introducing phrases
        for m in _PERSON_INTRO_RE.finditer(raw_input):
            _add(m.group(2).strip().rstrip("?. "), "person")

        # Pattern 2: concept-introducing phrases
        for m in _CONCEPT_INTRO_RE.finditer(raw_input):
            candidate = m.group(2).strip().rstrip("?. ")
            if candidate and candidate[0].islower():
                _add(candidate, "concept")

        # Pattern 3: multi-word capitalized names not already found
        for m in _CAPITALIZED_NAME_RE.finditer(raw_input):
            name = m.group(1)
            # Skip if already captured via person/concept patterns
            if name.lower() not in seen_names:
                _add(name, "person")  # Default to person for multi-word caps

        return entities

    # ------------------------------------------------------------------
    # Batch helper
    # ------------------------------------------------------------------

    def analyze_only(self, raw_input: str, intent: Optional[str] = None) -> EvaluationResult:
        """
        Run evaluation without mutating a Thought object.
        Useful for testing and for code that needs evaluation results
        before creating a Thought.
        """
        result = EvaluationResult()
        result.intent = intent or self._classify_intent(raw_input)
        result.detected_entities = self._extract_entities(raw_input)
        missing, requires_context = self._analyze_completeness(raw_input, result.intent)
        result.requires_context = requires_context
        result.missing_information = missing
        result.confidence = self._confidence.score_self_contained(raw_input).score
        return result
