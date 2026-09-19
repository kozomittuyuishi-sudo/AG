"""
test_response_processor.py
==========================
Unit tests for AG Response Processor & Safety Layer (Phase A).
Ensures text sanitization, safety evaluation, action extraction,
and clean fallbacks for malformed Brain responses.
"""

from brains.brain_dispatcher import BrainResponse
from conversation.response_processor import ResponseProcessor, ProcessedResponse


def test_basic_processing_and_sanitization():
    processor = ResponseProcessor()
    raw = BrainResponse(
        content="  <|im_start|>Here is the explanation for gravity.<|im_end|>  ",
        brain_id="mock_v1",
        provider="local",
        mode="QUERY",
        latency_ms=10.0
    )

    processed = processor.process(raw)

    assert isinstance(processed, ProcessedResponse)
    assert processed.is_safe is True
    assert processed.sanitized_content == "Here is the explanation for gravity."
    assert processed.fallback_triggered is False
    print("✓ test_basic_processing_and_sanitization passed")


def test_action_extraction_and_confirmation_flag():
    processor = ResponseProcessor()
    raw = BrainResponse(
        content="I can delete this file. Please confirm deletion before proceeding.",
        brain_id="mock_v1",
        provider="local",
        mode="ACTION",
        latency_ms=12.0
    )

    processed = processor.process(raw)

    assert processed.requires_user_confirmation is True
    # Ensure extracted_pending_action is present before subscripting to avoid None issues
    assert processed.extracted_pending_action is not None
    assert isinstance(processed.extracted_pending_action, dict)
    assert processed.extracted_pending_action.get("type") == "unconfirmed_brain_action"
    print("✓ test_action_extraction_and_confirmation_flag passed")


def test_fallback_on_empty_or_unsafe_response():
    processor = ResponseProcessor()

    # Empty content
    raw_empty = BrainResponse(content="", brain_id="mock_v1", provider="local", mode="QUERY", latency_ms=1.0)
    proc_empty = processor.process(raw_empty)

    assert proc_empty.is_safe is False
    assert proc_empty.fallback_triggered is True
    # Fallback message should be a clean, user-facing string (no internal error text)
    assert proc_empty.sanitized_content.strip()
    assert "[AG Fallback]" not in proc_empty.sanitized_content  # raw internal text must not leak
    assert "Cloud brain" not in proc_empty.sanitized_content    # no internal provider mention
    assert "Exception" not in proc_empty.sanitized_content      # no raw exception text

    # None passed
    proc_none = processor.process(None)
    assert proc_none.fallback_triggered is True
    assert proc_none.sanitized_content.strip()
    print("✓ test_fallback_on_empty_or_unsafe_response passed")


def run_all_tests():
    test_basic_processing_and_sanitization()
    test_action_extraction_and_confirmation_flag()
    test_fallback_on_empty_or_unsafe_response()
    print("\nAll Response Processor Phase A tests passed successfully!")


if __name__ == "__main__":
    run_all_tests()
