"""
response_processor.py
=====================
AG Response Processor & Safety Layer (Phase A)

Role:
- Validates, sanitizes, and evaluates raw responses from the Brain Dispatcher
  before they are presented to the user.
- Extracts pending actions or confirmation requests to update Working Memory.
- Evaluates safety risk and flags unconfirmed critical operations.

Boundaries:
- MUST NOT invoke LLM calls.
- MUST NOT bypass Control Layer or Probe Simulator risk assessments.
- Serves as the final deterministic filter before user output.
"""

from copy import deepcopy
from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional


class ProcessedResponse:
    """Standardized output contract for processed and verified responses."""

    def __init__(
        self,
        sanitized_content: str,
        is_safe: bool = True,
        requires_user_confirmation: bool = False,
        extracted_pending_action: Optional[Dict[str, Any]] = None,
        fallback_triggered: bool = False,
        raw_brain_id: Optional[str] = None
    ):
        self.sanitized_content = sanitized_content
        self.is_safe = is_safe
        self.requires_user_confirmation = requires_user_confirmation
        self.extracted_pending_action = extracted_pending_action
        self.fallback_triggered = fallback_triggered
        self.raw_brain_id = raw_brain_id
        self.processed_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sanitized_content": self.sanitized_content,
            "is_safe": self.is_safe,
            "requires_user_confirmation": self.requires_user_confirmation,
            "extracted_pending_action": self.extracted_pending_action,
            "fallback_triggered": self.fallback_triggered,
            "raw_brain_id": self.raw_brain_id,
            "processed_at": self.processed_at
        }


class ResponseProcessor:
    """Deterministic response checker, sanitizer, and action extractor."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        # Keywords suggesting an unconfirmed critical operation in Brain output
        self._critical_action_patterns = [
            r"confirm\s+(deletion|delete|removal|remove)",
            r"are\s+you\s+sure\s+you\s+want\s+to",
            r"pending\s+confirmation",
            r"execute\s+command"
        ]

    def sanitize_text(self, text: str) -> str:
        """Strips harmful artifacts or leaked prompt tokens from text."""
        if not text or not isinstance(text, str):
            return ""

        cleaned = text.strip()
        # Remove raw prompt artifact leakages if present
        cleaned = re.sub(r"<\|im_start\|>|<\|im_end\|>|\[SYSTEM_CONTEXT\]", "", cleaned)
        return cleaned.strip()

    def evaluate_safety(self, text: str) -> bool:
        """Determines basic output safety (e.g. non-empty, no raw shell injection leakage)."""
        if not text or not text.strip():
            return False
        return True

    def extract_action_intent(self, text: str) -> Tuple_Action_Flag:
        """
        Detects if the Brain's output contains a pending system action or confirmation request.
        """
        text_lower = text.lower()
        requires_confirmation = False
        action_payload = None

        for pattern in self._critical_action_patterns:
            if re.search(pattern, text_lower):
                requires_confirmation = True
                action_payload = {
                    "type": "unconfirmed_brain_action",
                    "detected_pattern": pattern,
                    "snippet": text[:100]
                }
                break

        return requires_confirmation, action_payload

    def process(self, brain_response: Any) -> ProcessedResponse:
        """
        Main entry point. Consumes BrainResponse and returns ProcessedResponse.
        """
        if not brain_response:
            return ProcessedResponse(
                sanitized_content="[AG Fallback]: No response payload received.",
                is_safe=False,
                fallback_triggered=True
            )

        # Extract content & brain metadata regardless of whether dict or object passed
        if hasattr(brain_response, "content"):
            raw_content = brain_response.content
            brain_id = getattr(brain_response, "brain_id", "unknown")
        elif isinstance(brain_response, dict):
            raw_content = brain_response.get("content", "")
            brain_id = brain_response.get("brain_id", "unknown")
        else:
            raw_content = str(brain_response)
            brain_id = "unknown"

        sanitized = self.sanitize_text(raw_content)

        if not self.evaluate_safety(sanitized):
            return ProcessedResponse(
                sanitized_content="[AG Fallback]: Output failed safety verification or was empty.",
                is_safe=False,
                fallback_triggered=True,
                raw_brain_id=brain_id
            )

        req_confirm, action_payload = self.extract_action_intent(sanitized)

        return ProcessedResponse(
            sanitized_content=sanitized,
            is_safe=True,
            requires_user_confirmation=req_confirm,
            extracted_pending_action=action_payload,
            fallback_triggered=False,
            raw_brain_id=brain_id
        )


# Helper type alias for internal clarity
Tuple_Action_Flag = Any