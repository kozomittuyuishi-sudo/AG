"""Focused regression coverage for Preprocessor Brain self-info routing."""

import pytest

from preprocessor_brain import Domain, Intent, PreprocessorBrain


@pytest.mark.parametrize(("query", "intent"), [
    ("What can you do?", Intent.GET_CAPABILITIES),
    ("What are your capabilities?", Intent.GET_CAPABILITIES),
    ("What can you currently do?", Intent.GET_CAPABILITIES),
    ("What functionality do you have?", Intent.GET_CAPABILITIES),
    ("What can you help me with?", Intent.GET_CAPABILITIES),
    ("What functions do you support?", Intent.GET_CAPABILITIES),
    ("What brains do you have?", Intent.GET_BRAIN_INFO),
    ("How many brains do you have?", Intent.GET_BRAIN_INFO),
    ("Which brains are available?", Intent.GET_BRAIN_INFO),
    ("What are your limitations?", Intent.GET_LIMITATIONS),
    ("What operations don't you support?", Intent.GET_LIMITATIONS),
    ("So what can you do?", Intent.GET_CAPABILITIES),
    ("Tell me about yourself.", Intent.GET_IDENTITY),
    ("What do you know about yourself?", Intent.GET_IDENTITY),
    ("Tell me who you are", Intent.GET_IDENTITY),
    ("What you're capable of", Intent.GET_CAPABILITIES),
    ("And what are you capable of?", Intent.GET_CAPABILITIES),
    ("What you can do", Intent.GET_CAPABILITIES),
    ("How you work internally", Intent.GET_ARCHITECTURE),
    ("How you work", Intent.GET_ARCHITECTURE),
    ("What happens internally?", Intent.GET_ARCHITECTURE),
    ("What systems do you have?", Intent.GET_ARCHITECTURE),
])
def test_self_info_queries_are_answered_deterministically(query, intent):
    result = PreprocessorBrain().process(query)

    assert result.domain == Domain.SELF_INFO
    assert result.intent == intent
    assert result.success
    assert result.result
    assert result.requires_llm is False


def test_identity_response_uses_project_context_version():
    result = PreprocessorBrain().process("Tell me about yourself")

    assert "v0.23" in result.result
    assert "0.4.0" not in result.result


def test_quips_self_info_subtype_is_answered_without_reclassifying_wording():
    result = PreprocessorBrain().process_self_info_intent(
        "ARCHITECTURE", "Tell me who you are, what you're capable of, and how you work internally."
    )

    assert result.success
    assert result.intent == Intent.GET_ARCHITECTURE
    assert result.requires_llm is False
    assert result.metadata["source"] == "QUIPS"
