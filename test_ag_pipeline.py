"""
test_ag_pipeline.py
===================
End-to-End Integration Tests for AG Cognitive Pipeline (`ag_pipeline.py`).
"""

from unittest.mock import MagicMock
from ag_pipeline import AGPipeline, AGPipelineResult


def test_normal_pipeline_flow():
    pipeline = AGPipeline()
    user_input = "Explain gravity and remember this rule"

    result = pipeline.process_input(user_input)

    if not result.success:
        print(f"\n❌ [PIPELINE ERROR DIAGNOSTIC]: {result.error}\n")

    assert result.success is True, f"Pipeline failed with error: {result.error}"
    assert result.processed_response is not None
    assert result.processed_response.is_safe is True
    assert result.brain_response is not None
    assert result.executive_decision is not None
    assert result.executive_decision.should_persist_long_term is True
    print("✓ test_normal_pipeline_flow passed")


def test_invalid_user_input():
    pipeline = AGPipeline()

    res_empty = pipeline.process_input("")
    assert res_empty.success is False
    assert res_empty.processed_response is not None
    assert res_empty.processed_response.fallback_triggered is True

    res_none = pipeline.process_input(None)
    assert res_none.success is False
    assert res_none.processed_response is not None
    assert res_none.processed_response.fallback_triggered is True
    print("✓ test_invalid_user_input passed")


def test_cognitive_engine_failure_recovery():
    pipeline = AGPipeline()
    for method in ("process_turn", "process_intent", "evaluate_turn"):
        if hasattr(pipeline.cognitive, method):
            setattr(pipeline.cognitive, method, MagicMock(side_effect=RuntimeError("Cognitive engine crash")))

    result = pipeline.process_input("Hello")

    assert result.success is False
    assert "CognitiveEngine failure" in (result.error or "")
    assert result.processed_response is not None
    assert result.processed_response.fallback_triggered is True
    print("✓ test_cognitive_engine_failure_recovery passed")


def test_brain_dispatcher_failure_recovery():
    pipeline = AGPipeline()
    pipeline.dispatcher.dispatch = MagicMock(side_effect=ConnectionError("Brain API unreachable"))

    result = pipeline.process_input("Run task")

    assert result.success is False
    assert "BrainDispatcher failure" in (result.error or "")
    assert result.processed_response is not None
    assert result.processed_response.fallback_triggered is True
    print("✓ test_brain_dispatcher_failure_recovery passed")


def test_response_processor_failure_recovery():
    pipeline = AGPipeline()
    pipeline.processor.process = MagicMock(side_effect=ValueError("Sanitization error"))

    result = pipeline.process_input("Process this")

    assert result.success is False
    assert "ResponseProcessor failure" in (result.error or "")
    assert result.processed_response is not None
    assert result.processed_response.fallback_triggered is True
    print("✓ test_response_processor_failure_recovery passed")


def test_executive_layer_failure_recovery():
    pipeline = AGPipeline()
    pipeline.executive.process_execution_cycle = MagicMock(side_effect=KeyError("Category failure"))

    result = pipeline.process_input("Save this project rule")

    assert result.success is False
    assert "ExecutiveLayer failure" in (result.error or "")
    assert result.processed_response is not None
    assert result.processed_response.is_safe is True
    print("✓ test_executive_layer_failure_recovery passed")


def test_malformed_brain_response():
    pipeline = AGPipeline()
    pipeline.dispatcher.dispatch = MagicMock(return_value={"malformed": True})

    result = pipeline.process_input("Test input")

    assert result.success is True
    assert result.processed_response is not None
    print("✓ test_malformed_brain_response passed")


def run_all_tests():
    test_normal_pipeline_flow()
    test_invalid_user_input()
    test_cognitive_engine_failure_recovery()
    test_brain_dispatcher_failure_recovery()
    test_response_processor_failure_recovery()
    test_executive_layer_failure_recovery()
    test_malformed_brain_response()
    print("\nAll AG Pipeline Integration tests passed successfully!")


if __name__ == "__main__":
    run_all_tests()