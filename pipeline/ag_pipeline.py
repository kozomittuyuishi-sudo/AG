"""
ag_pipeline.py
==============
AG Pipeline Orchestration & Cognitive Pipeline Integration
"""

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from memory.working_memory import WorkingMemory
from cognition.executive_layer import ExecutiveLayer, ExecutiveDecision
from cognition.cognitive_engine import CognitiveEngine
from brains.brain_dispatcher import BrainDispatcher, BrainResponse
from conversation.response_processor import ResponseProcessor, ProcessedResponse
from pipeline.fallback_classifier import (
    FallbackClassifier,
    CATEGORY_PROCESSING_FAILURE,
    CATEGORY_BRAIN_FAILURE,
)

_classifier = FallbackClassifier()


class AGPipelineResult:
    """Structured container holding the full end-to-end execution trace and result."""

    def __init__(
        self,
        success: bool,
        user_input: str,
        processed_response: Optional[ProcessedResponse] = None,
        executive_decision: Optional[ExecutiveDecision] = None,
        brain_response: Optional[BrainResponse] = None,
        error: Optional[str] = None
    ):
        self.success = success
        self.user_input = user_input
        self.processed_response = processed_response
        self.executive_decision = executive_decision
        self.brain_response = brain_response
        self.error = error
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "user_input": self.user_input,
            "processed_response": self.processed_response.to_dict() if self.processed_response else None,
            "executive_decision": self.executive_decision.to_dict() if self.executive_decision else None,
            "brain_response": self.brain_response.to_dict() if self.brain_response else None,
            "error": self.error,
            "timestamp": self.timestamp
        }


class AGPipeline:
    """
    Orchestrates one pass of user input through the AG Beta Cognitive Subsystems.
    """

    def __init__(
        self,
        working_memory: Optional[Any] = None,
        executive_layer: Optional[Any] = None,
        cognitive_engine: Optional[Any] = None,
        brain_dispatcher: Optional[Any] = None,
        response_processor: Optional[Any] = None
    ):
        self.memory: Any = working_memory or WorkingMemory()
        self.executive: Any = executive_layer or ExecutiveLayer()
        self.cognitive: Any = cognitive_engine or CognitiveEngine()
        self.dispatcher: Any = brain_dispatcher or BrainDispatcher()
        self.processor: Any = response_processor or ResponseProcessor()

    def _get_memory_snapshot(self) -> Dict[str, Any]:
        """Safely retrieves state snapshot across different WorkingMemory method names."""
        for method_name in ("get_snapshot", "get_state", "to_dict"):
            method = getattr(self.memory, method_name, None)
            if callable(method):
                result = method()
                if isinstance(result, dict):
                    return result
        return {}

    def _add_memory_scratchpad(self, text: str, priority: int = 2) -> None:
        """Safely adds note across different WorkingMemory method names."""
        for method_name in ("add_scratchpad_item", "add_scratchpad_note", "add_note"):
            method = getattr(self.memory, method_name, None)
            if callable(method):
                method(text, priority)
                return

    def process_input(self, user_input: Optional[str]) -> AGPipelineResult:
        """
        Executes a single user turn through the integrated pipeline.
        """
        # 1. Input Validation
        if not user_input or not isinstance(user_input, str) or not user_input.strip():
            fallback_proc = ProcessedResponse(
                sanitized_content=_classifier.get_message(CATEGORY_PROCESSING_FAILURE),
                is_safe=False,
                fallback_triggered=True
            )
            return AGPipelineResult(
                success=False,
                user_input=str(user_input or ""),
                processed_response=fallback_proc,
                error="Invalid user input"
            )

        clean_input = user_input.strip()

        # 2. Extract Working Memory Snapshot safely
        try:
            mem_snapshot = self._get_memory_snapshot()
        except Exception as e:
            fallback_proc = ProcessedResponse(
                sanitized_content=_classifier.get_message(CATEGORY_PROCESSING_FAILURE),
                is_safe=False,
                fallback_triggered=True
            )
            return AGPipelineResult(
                success=False,
                user_input=clean_input,
                processed_response=fallback_proc,
                error=f"WorkingMemory failure: {str(e)}"
            )

        # 3. Cognitive Engine Processing
        try:
            cog_method = None
            for method_name in ("process_turn", "process_intent", "evaluate_turn", "process"):
                method = getattr(self.cognitive, method_name, None)
                if callable(method):
                    cog_method = method
                    break

            if cog_method:
                brain_payload = cog_method(clean_input, mem_snapshot)
            elif callable(self.cognitive):
                brain_payload = self.cognitive(clean_input, mem_snapshot)
            else:
                raise AttributeError("CognitiveEngine does not expose a supported processing method")
        except Exception as e:
            fallback_proc = ProcessedResponse(
                sanitized_content=_classifier.get_message(CATEGORY_PROCESSING_FAILURE),
                is_safe=False,
                fallback_triggered=True
            )
            return AGPipelineResult(
                success=False,
                user_input=clean_input,
                processed_response=fallback_proc,
                error=f"CognitiveEngine failure: {str(e)}"
            )

        # 4. Brain Dispatcher Routing & Execution
        try:
            raw_brain_response = self.dispatcher.dispatch(brain_payload)
        except Exception as e:
            fallback_proc = ProcessedResponse(
                sanitized_content=_classifier.get_message(CATEGORY_BRAIN_FAILURE),
                is_safe=False,
                fallback_triggered=True
            )
            return AGPipelineResult(
                success=False,
                user_input=clean_input,
                processed_response=fallback_proc,
                error=f"BrainDispatcher failure: {str(e)}"
            )

        # 5. Response Processor Verification & Sanitization
        try:
            processed_resp = self.processor.process(raw_brain_response)
        except Exception as e:
            processed_resp = ProcessedResponse(
                sanitized_content=_classifier.get_message(CATEGORY_PROCESSING_FAILURE),
                is_safe=False,
                fallback_triggered=True
            )
            return AGPipelineResult(
                success=False,
                user_input=clean_input,
                brain_response=raw_brain_response if isinstance(raw_brain_response, BrainResponse) else None,
                processed_response=processed_resp,
                error=f"ResponseProcessor failure: {str(e)}"
            )

        # 6. Executive Layer Storage & Category Decisions
        try:
            exec_decision = self.executive.process_execution_cycle(
                user_input=clean_input,
                processed_response=processed_resp,
                cog_state={"topic": mem_snapshot.get("active_topic")}
            )
        except Exception as e:
            exec_decision = ExecutiveDecision(should_persist_long_term=False)
            return AGPipelineResult(
                success=False,
                user_input=clean_input,
                brain_response=raw_brain_response,
                processed_response=processed_resp,
                executive_decision=exec_decision,
                error=f"ExecutiveLayer failure: {str(e)}"
            )

        # 7. Update Working Memory with State Side-Effects
        try:
            if processed_resp.extracted_pending_action:
                self._add_memory_scratchpad(
                    f"Pending Action: {processed_resp.extracted_pending_action.get('type')}",
                    priority=2
                )
            if exec_decision.target_category and exec_decision.target_category != "uncategorized":
                set_topic_fn = getattr(self.memory, "set_topic", None)
                if callable(set_topic_fn):
                    set_topic_fn(exec_decision.target_category)
        except Exception:
            pass

        return AGPipelineResult(
            success=True,
            user_input=clean_input,
            processed_response=processed_resp,
            executive_decision=exec_decision,
            brain_response=raw_brain_response
        )
