"""
executive_layer.py
==================
AG Executive Layer (Stage 5 - Phase A)

Role:
- High-level decision manager for Storage and Category routing.
- Consumes processed responses / cognitive payloads and decides:
  1. Storage Routing (Long-term memory.json vs Session Memory vs Temporary Context).
  2. Category Routing (Structured Categories vs Dynamic Categories created on the fly).
  3. Task & Objective persistence triggers.

Boundaries:
- Does not modify LLM reasoning or prompt text directly.
- Directs state mutation decisions to lower-level storage and memory handlers.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Type alias: return type for evaluate_category_decision
Tuple_Cat_Decision = Any


class ExecutiveDecision:
    """Standard payload containing operational routing decisions made by Executive Layer."""

    def __init__(

        self,
        should_persist_long_term: bool = False,
        target_category: Optional[str] = None,
        is_dynamic_category: bool = False,
        task_update: Optional[Dict[str, Any]] = None,
        memory_entry: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.should_persist_long_term = should_persist_long_term
        self.target_category = target_category
        self.is_dynamic_category = is_dynamic_category
        self.task_update = task_update
        self.memory_entry = memory_entry
        self.metadata = metadata or {}
        self.decided_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "should_persist_long_term": self.should_persist_long_term,
            "target_category": self.target_category,
            "is_dynamic_category": self.is_dynamic_category,
            "task_update": self.task_update,
            "memory_entry": self.memory_entry,
            "metadata": self.metadata,
            "decided_at": self.decided_at
        }


class ExecutiveLayer:
    """Stage 5 Manager handling Storage & Category Decisions."""

    # Default structured categories in AG
    STRUCTURED_CATEGORIES = {"core_facts", "project_metadata", "task_rules", "user_preferences"}

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    def evaluate_storage_decision(self, user_input: str, processed_content: str, mode: str) -> bool:
        """
        Determines whether an interaction should be stored in long-term memory (memory.json).
        """
        # Triggers for long-term persistence:
        # 1. Action mode or explicitly marked persistent facts/tasks
        # 2. Key phrases like "remember", "save this", "project rule"
        if mode in ("ACTION", "PLANNING"):
            return True

        text_lower = (user_input + " " + processed_content).lower()
        persistence_triggers = ["remember", "save this", "always", "never forget", "objective:", "rule:"]
        
        return any(trigger in text_lower for trigger in persistence_triggers)

    def evaluate_category_decision(self, category_candidate: Optional[str]) -> Tuple_Cat_Decision:
        """
        Determines whether a category is structured or requires a dynamic category creation on the fly.
        """
        if not category_candidate or not category_candidate.strip():
            return "uncategorized", False

        clean_cat = category_candidate.strip().lower().replace(" ", "_")

        if clean_cat in self.STRUCTURED_CATEGORIES:
            return clean_cat, False
        else:
            # Dynamic category created on the fly
            return clean_cat, True

    def process_execution_cycle(
        self,
        user_input: str,
        processed_response: Any,
        cog_state: Optional[Dict[str, Any]] = None
    ) -> ExecutiveDecision:
        """
        Consumes cognitive state & processed output to generate a consolidated ExecutiveDecision.
        """
        cog_state = cog_state or {}
        
        # Extract response content & mode safely
        if hasattr(processed_response, "sanitized_content"):
            content = processed_response.sanitized_content
            mode = getattr(processed_response, "mode", "QUERY")
        elif isinstance(processed_response, dict):
            content = processed_response.get("sanitized_content", "")
            mode = processed_response.get("mode", "QUERY")
        else:
            content = str(processed_response)
            mode = "QUERY"

        # 1. Storage Decision
        persist = self.evaluate_storage_decision(user_input, content, mode)

        # 2. Category Decision
        raw_topic = cog_state.get("topic") or cog_state.get("category")
        cat_name, is_dynamic = self.evaluate_category_decision(raw_topic)

        # 3. Construct Memory Entry if long-term persistence triggered
        memory_entry = None
        if persist:
            memory_entry = {
                "input": user_input,
                "summary": content[:200],
                "category": cat_name,
                "is_dynamic_category": is_dynamic,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        return ExecutiveDecision(
            should_persist_long_term=persist,
            target_category=cat_name,
            is_dynamic_category=is_dynamic,
            memory_entry=memory_entry,
            metadata={"processed_mode": mode}
        )
