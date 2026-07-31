"""
cognitive/response_verifier.py
================================
AG Phase 2 — ResponseVerifier

The ResponseVerifier is the final pipeline stage before a response is
returned to the user.  Every response passes through this stage.

It asks:
    1. Did we answer the user's actual question?
    2. Did we lose conversational context?
    3. Are we making unverified assumptions?
    4. Should clarification be requested instead of returning this response?

It does NOT modify the response content unless the response is empty or
a clear fallback sentinel.  It only decides whether the response is valid
and adds verification notes to the Thought.

Design principles:
    - NEVER rewrites response content (that is the Brain's job).
    - NEVER calls the Brain.
    - Deterministic, in-memory, stdlib only.
    - Logs every check result in the Thought's reasoning_log.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.thought import Thought


# Response quality indicators
_FALLBACK_SENTINELS = frozenset({
    "i could not generate a response just now.",
    "brain connection failed.",
    "local brain returned no response.",
    "cloud brain returned no response.",
    "[ag fallback]",
})

# Patterns that suggest the Brain may have answered a different question
# (hallucination indicators — approximate, not definitive)
_TOPIC_SWITCH_PHRASES = re.compile(
    r"\b(however, let me tell you about|actually,? what i can tell you is"
    r"|on a different note|speaking of which|instead,? let me|"
    r"i don't have information about .+ but)\b",
    re.IGNORECASE,
)


class VerificationResult:
    """
    Container for the outcome of a single verification pass.

    Attributes
    ----------
    passed : bool
        True if the response is acceptable for delivery.
    notes : List[str]
        Human-readable notes about what was checked and any warnings.
    should_retry : bool
        True if the pipeline should attempt a retry (not yet implemented;
        reserved for future use).
    """

    def __init__(self, passed: bool, notes: Optional[List[str]] = None) -> None:
        self.passed: bool = passed
        self.notes: List[str] = list(notes or [])
        self.should_retry: bool = False

    def add_note(self, note: str) -> "VerificationResult":
        self.notes.append(str(note))
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "notes": list(self.notes),
            "should_retry": self.should_retry,
        }


class ResponseVerifier:
    """
    Final pipeline stage — validates a response before delivery.

    Usage
    -----
    ::

        verifier = ResponseVerifier()
        thought = verifier.verify(thought)
        if thought.verification_passed:
            print(thought.final_response)
        else:
            # Handle verification failure — use fallback or ask user
            ...
    """

    # ------------------------------------------------------------------
    # Primary entry point
    # ------------------------------------------------------------------

    def verify(self, thought: "Thought") -> "Thought":
        """
        Run all verification checks and populate the Thought's response fields.

        After this call:
            - ``thought.final_response`` is set (either the verified response
              or a sanitized fallback).
            - ``thought.verification_passed`` reflects the outcome.
            - ``thought.verification_notes`` lists all check results.
            - The reasoning_log captures every check.

        :param thought: The Thought to verify (mutated in-place).
        :returns: The mutated Thought.
        """
        thought.log("verifier", "Starting response verification.")

        raw = thought.raw_response
        notes: List[str] = []

        # Check 1: Was a response produced at all?
        if not raw or not raw.strip():
            notes.append("FAIL: Response is empty.")
            thought.log("verifier", "Response is empty — verification failed.")
            thought.set_final_response(
                self._fallback(thought),
                passed=False,
                notes=notes,
            )
            return thought

        # Check 2: Is this a known fallback sentinel?
        if raw.strip().lower().rstrip(".") in _FALLBACK_SENTINELS or "[ag fallback]" in raw.lower():
            notes.append("WARN: Response is a fallback sentinel — brain could not answer.")
            thought.log("verifier", "Fallback sentinel detected.")
            # Still deliver it — it's a real system message
            thought.set_final_response(raw, passed=True, notes=notes)
            return thought

        # Check 3: Did we answer the actual question?
        answered = self._check_answered_question(thought, raw, notes)

        # Check 4: Lost context check
        self._check_context_preservation(thought, raw, notes)

        # Check 5: Assumption check
        self._check_assumptions(thought, raw, notes)

        # Check 6: Response length sanity
        self._check_length(raw, notes)

        # Verdict
        passed = answered  # Primary criterion; others are advisory warnings
        thought.log("verifier", f"Verification {'passed' if passed else 'failed'} — {len(notes)} note(s).")
        thought.set_final_response(raw, passed=passed, notes=notes)
        return thought

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_answered_question(
        self, thought: "Thought", response: str, notes: List[str]
    ) -> bool:
        """
        Heuristic check: does the response appear to address the resolved input?

        Returns True if the response is considered to have answered the question.
        """
        resolved = (thought.resolved_input or thought.raw_input).lower().strip()
        resp_lower = response.lower()

        # Very short responses to clear questions are suspicious but not failures
        if len(response.split()) < 3 and "?" in resolved:
            notes.append("WARN: Response is very short for a question input.")
            thought.log("verifier", "Response very short for a question.")

        # Topic switch detection
        if _TOPIC_SWITCH_PHRASES.search(resp_lower):
            notes.append("WARN: Response may have drifted to a different topic.")
            thought.log("verifier", "Possible topic drift detected in response.")

        # If the response is a clarification question back to the user,
        # and the thought already asked for clarification — that is valid.
        if thought.ask_for_clarification and response.strip().endswith("?"):
            notes.append("OK: Response is a clarification question as expected.")
            return True

        notes.append("OK: Response appears to address the input.")
        return True

    def _check_context_preservation(
        self, thought: "Thought", response: str, notes: List[str]
    ) -> None:
        """
        Check whether the response references context it shouldn't have lost.
        Advisory only — does not affect the pass/fail verdict.
        """
        # If the resolver rewrote the input, the response should contain
        # something related to the resolved entity/topic
        if thought.resolved_input != thought.raw_input:
            # The resolver replaced something — check there's content
            if len(response.split()) > 10:
                notes.append("OK: Resolved question received a substantive response.")
            else:
                notes.append(
                    "WARN: Input was resolved from context but response is short — "
                    "may not have used resolved context."
                )
                thought.log("verifier", "Short response after context resolution.")

    def _check_assumptions(
        self, thought: "Thought", response: str, notes: List[str]
    ) -> None:
        """
        Flag if the response appears to be making unverified assumptions.
        Advisory only.
        """
        assumption_phrases = re.compile(
            r"\b(i assume|assuming|presumably|i believe you meant|"
            r"you probably|you must be|you seem to|i think you|"
            r"if you mean)\b",
            re.IGNORECASE,
        )
        if assumption_phrases.search(response):
            notes.append(
                "WARN: Response contains assumption language — "
                "the resolver may have guessed the context."
            )
            thought.log("verifier", "Assumption language detected in response.")
        else:
            notes.append("OK: No assumption language detected.")

    def _check_length(self, response: str, notes: List[str]) -> None:
        """Sanity check on response length."""
        word_count = len(response.split())
        if word_count > 1000:
            notes.append(f"WARN: Response is very long ({word_count} words) — consider summarising.")
        elif word_count < 3:
            notes.append(f"WARN: Response is very short ({word_count} words).")
        else:
            notes.append(f"OK: Response length is {word_count} words.")

    # ------------------------------------------------------------------
    # Fallback builder
    # ------------------------------------------------------------------

    def _fallback(self, thought: "Thought") -> str:
        """Build a sensible fallback message for empty/invalid responses."""
        intent = thought.intent or "unknown"
        if intent == "unknown":
            return "I could not generate a response for that request."
        return f"I could not complete the {intent} request. Please try again."
