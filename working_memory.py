import re
from typing import Any, Dict, List, Optional

# ── Deterministic topic extraction (no LLM — Phase A stays simple/fast) ──

_TOPIC_PATTERNS = [
    r"^what is (.+)$",
    r"^what are (.+)$",
    r"^who is (.+)$",
    r"^explain (.+)$",
    r"^define (.+)$",
    r"^how does (.+) work$",
    r"^why does (.+) happen$",
    r"^tell me about (.+)$",
]

_FOLLOWUP_TRIGGERS = [
    "how does it work", "how does that work", "how does this work",
    "explain that", "explain it", "explain this",
    "give examples", "give an example", "give some examples",
    "why does it happen", "why does that happen", "why does this happen",
    "tell me more", "more about it", "what about it",
    "how is it used", "how is that used",
]

_PRONOUNS = ("it", "that", "this")


def extract_topic(user_input: str) -> Optional[str]:
    text = user_input.strip().lower().rstrip("?").strip()

    for pattern in _TOPIC_PATTERNS:
        match = re.match(pattern, text)
        if match:
            topic = match.group(1).strip()
            if topic:
                return topic

    return None


def summarize(ag_response: str, max_len: int = 160) -> str:
    text = ag_response.strip()
    first_sentence = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]

    if len(first_sentence) <= max_len:
        return first_sentence

    return first_sentence[:max_len].rstrip() + "..."


class WorkingMemory:
    """
    Session-only context tracker. Never touches memory.json.
    Resets automatically whenever AG restarts (it's just an object in RAM).
    """

    def __init__(self):
        self.current_topic: Optional[str] = None
        self.last_user_question: Optional[str] = None
        self.last_ag_answer_summary: Optional[str] = None
        self.active_context: List[str] = []
        self.recent_entities: List[str] = []
        self.conversation_goal: Optional[str] = None
        self.turn_count: int = 0

        # Session-only discussion buffer. Never written to memory.json
        # automatically — only flushed there if the user confirms at shutdown.
        self.discussion_buffer: List[Dict[str, str]] = []

    def update(self, user_input: str, ag_response: str, intent: str) -> None:
        self.turn_count += 1

        if intent in ("unknown", "cloud_brain", "recall"):
            topic = extract_topic(user_input)
            if topic:
                self.current_topic = topic
                if topic not in self.recent_entities:
                    self.recent_entities.append(topic)
                    self.recent_entities = self.recent_entities[-5:]

        self.last_user_question = user_input
        self.last_ag_answer_summary = summarize(ag_response) if ag_response else None

        self.active_context.append(user_input)
        self.active_context = self.active_context[-5:]

    def reset(self) -> None:
        self.__init__()

    def add_to_discussion(self, user_input: str, ag_response: str) -> None:
        self.discussion_buffer.append({"question": user_input, "answer": ag_response})

    def has_unsaved_discussion(self) -> bool:
        return len(self.discussion_buffer) > 0

    def clear_discussion(self) -> None:
        self.discussion_buffer = []

    def discussion_topic(self) -> str:
        return self.current_topic or "this discussion"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_topic": self.current_topic,
            "last_user_question": self.last_user_question,
            "last_ag_answer_summary": self.last_ag_answer_summary,
            "active_context": list(self.active_context),
            "recent_entities": list(self.recent_entities),
            "conversation_goal": self.conversation_goal,
            "turn_count": self.turn_count,
        }


def update_working_memory(working_memory: WorkingMemory, user_input: str, ag_response: str, intent: str) -> None:
    """Module-level convenience wrapper around WorkingMemory.update()."""
    working_memory.update(user_input, ag_response, intent)


def resolve_followup(user_input: str, working_memory: WorkingMemory) -> str:
    """
    Rewrites vague follow-ups using the tracked current_topic.
    Returns user_input unchanged if there's no topic to resolve against,
    or if the input doesn't look like a vague follow-up.
    """
    topic = working_memory.current_topic

    if not topic:
        return user_input

    text = user_input.strip()
    had_question_mark = text.endswith("?")
    lowered = text.rstrip("?").strip().lower()

    # Case 1: exact match against a known vague follow-up phrase
    for trigger in _FOLLOWUP_TRIGGERS:
        if lowered == trigger:
            rewritten = trigger
            for pronoun in _PRONOUNS:
                rewritten = rewritten.replace(pronoun, topic)

            if topic not in rewritten:
                rewritten = f"{rewritten} about {topic}"

            suffix = "?" if (had_question_mark or "how" in rewritten or "why" in rewritten) else ""
            return rewritten + suffix

    # Case 2: standalone pronoun substitution for short inputs
    # (e.g. "explain that simply" -> "explain gravity simply")
    words = lowered.split()
    if len(words) <= 6 and any(word in _PRONOUNS for word in words):
        replaced = [topic if word in _PRONOUNS else word for word in words]
        result = " ".join(replaced)
        return result + ("?" if had_question_mark else "")

    return user_input