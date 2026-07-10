"""
Conversation Manager / Action Pattern Analyzer.

Deterministic (no LLM) pattern detection for structural commands like
brain-mode switching. Kept rule-based on purpose: these commands need
to be recognized reliably and fast, before normal intent detection runs.
"""

import re
import uuid
from typing import Any, Dict

PERMANENT_PATTERNS = [
    r"^switch to (cloud|local)( brain)?$",
    r"^go (online|offline)$",
    r"^set (default )?brain to (cloud|local)$",
]

TEMPORARY_PATTERNS = [
    r"\buse (cloud|local) brain\b",
    r"\banswer this using (cloud|local) brain\b",
    r"\brespond with (cloud|local) brain\b",
]


def _new_action_id() -> str:
    return uuid.uuid4().hex[:8]


def _empty_result() -> Dict[str, Any]:
    return {
        "is_action_request": False,
        "primary_intent": "none",
        "actions": [],
        "confidence": 0.0,
        "missing_data": [],
        "requires_confirmation": False
    }


def _base_action(action_type: str, operation: str, scope: str, target, resolved_query: str) -> Dict[str, Any]:
    return {
        "id": _new_action_id(),
        "action_type": action_type,
        "operation": operation,
        "scope": scope,
        "target": target,
        "mode_change": action_type == "brain_mode_change",
        "topic": None,
        "resolved_query": resolved_query,
        "parameters": {},
        "constraints": {},
        "context_refs": [],
        "depends_on": [],
        "execution_policy": {"requires_confirmation": False},
        "confidence": 0.85
    }


def analyze_action_pattern(user_input: str, working_memory=None) -> Dict[str, Any]:
    text = str(user_input).strip().lower()

    # --- Permanent brain mode change ---
    for pattern in PERMANENT_PATTERNS:
        match = re.search(pattern, text)
        if match:
            groups = [g for g in match.groups() if g]
            target = "cloud" if ("cloud" in groups or "online" in groups) else "local"

            action = _base_action("brain_mode_change", "set_default_brain", "global", target, user_input)
            action["parameters"] = {"persistent": True}
            action["confidence"] = 0.95

            return {
                "is_action_request": True,
                "primary_intent": "brain_mode_change",
                "actions": [action],
                "confidence": 0.95,
                "missing_data": [],
                "requires_confirmation": False
            }

    # --- Temporary brain use (current thread/request only) ---
    for pattern in TEMPORARY_PATTERNS:
        match = re.search(pattern, text)
        if match:
            target = match.group(1)

            topic_match = re.search(r"\bfor\s+(.+)$", text)
            topic = topic_match.group(1).strip() if topic_match else None
            resolved_query = topic if topic else user_input

            if working_memory is not None:
                from working_memory import resolve_thread_reference
                resolved_query = resolve_thread_reference(resolved_query, working_memory)

            action = _base_action("brain_routing", "temporary_brain_use", "current_thread", target, resolved_query)
            action["topic"] = topic
            action["parameters"] = {
                "brain": target,
                "temporary": True,
                "restore_previous_mode": True
            }
            action["execution_policy"] = {"requires_confirmation": True}
            action["confidence"] = 0.9

            return {
                "is_action_request": True,
                "primary_intent": "brain_routing",
                "actions": [action],
                "confidence": 0.9,
                "missing_data": [],
                "requires_confirmation": True
            }

    return _empty_result()