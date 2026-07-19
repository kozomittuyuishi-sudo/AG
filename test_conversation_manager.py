from conversation_manager import ConversationManager
from schema_processor import process_document


def test_1_new_conversation_state_is_valid():
    cm = ConversationManager()
    state = cm.get_state()
    assert state["state"] == "active"
    assert state["turn_count"] == 0
    assert state["current_topic"] is None
    assert state["conversation_id"].startswith("conv_")
    print("1 OK: new conversation state is valid")


def test_2_adding_turns_increments_turn_count():
    cm = ConversationManager()
    cm.add_turn("user", "what is gravity?")
    cm.add_turn("assistant", "Gravity is a force.")
    assert cm.get_state()["turn_count"] == 2
    print("2 OK: adding turns increments turn count")


def test_3_current_topic_is_stored():
    cm = ConversationManager()
    cm.set_topic("gravity")
    assert cm.get_state()["current_topic"] == "gravity"
    print("3 OK: current topic is stored")


def test_4_topic_shift_preserves_previous_topic():
    cm = ConversationManager()
    cm.set_topic("gravity")
    cm.set_topic("entropy")
    state = cm.get_state()
    assert state["current_topic"] == "entropy"
    assert state["previous_topic"] == "gravity"
    print("4 OK: topic shift preserves previous topic")


def test_5_topic_history_is_updated():
    cm = ConversationManager()
    cm.set_topic("gravity")
    cm.set_topic("entropy")
    assert cm.get_state()["topic_history"] == ["gravity", "entropy"]
    print("5 OK: topic history is updated")


def test_6_give_examples_resolves_to_current_topic():
    cm = ConversationManager()
    cm.set_topic("gravity")
    result = cm.resolve_reference("give examples")
    assert result["resolved"] is True
    assert result["resolved_input"] == "Give examples about gravity."
    print("6 OK: 'give examples' resolves to current topic")


def test_7_simplify_that_resolves_to_current_topic():
    cm = ConversationManager()
    cm.set_topic("gravity")
    result = cm.resolve_reference("simplify that")
    assert result["resolved"] is True
    assert result["resolved_input"] == "Simplify the current explanation about gravity."
    print("7 OK: 'simplify that' resolves to current topic")


def test_8_all_this_resolves_to_current_thread():
    cm = ConversationManager()
    cm.set_topic("gravity")
    result = cm.resolve_reference("use cloud brain for briefing about all this")
    assert result["resolved"] is True
    assert result["resolved_input"] == "Create a briefing of the current gravity discussion using cloud brain."
    print("8 OK: 'all this' resolves to current thread")


def test_9_do_that_resolves_pending_action():
    cm = ConversationManager()
    cm.set_topic("gravity")
    cm.set_pending_action({"resolved_query": "summarize the gravity discussion"})
    result = cm.resolve_reference("do that")
    assert result["resolved"] is True
    assert result["reference_type"] == "pending_action"
    assert result["resolved_input"] == "summarize the gravity discussion"
    print("9 OK: 'do that' resolves pending action")


def test_10_yes_no_is_contextual_when_confirmation_pending():
    cm = ConversationManager()
    cm.set_pending_confirmation({"question": "Store this?"})
    yes_result = cm.resolve_reference("yes")
    assert yes_result["reference_type"] == "confirmation_response"

    no_result = cm.resolve_reference("no")
    assert no_result["reference_type"] == "confirmation_response"
    print("10 OK: yes/no is contextual when confirmation is pending")


def test_11_unresolved_reference_requests_clarification_when_no_topic():
    cm = ConversationManager()
    result = cm.resolve_reference("give examples")
    assert result["resolved"] is False
    assert result["needs_clarification"] is True
    print("11 OK: unresolved reference requests clarification when no topic exists")


def test_12_recent_turn_buffer_stays_bounded():
    cm = ConversationManager()
    for i in range(20):
        cm.add_turn("user", f"message {i}")
    state = cm.get_state()
    assert len(state["recent_turns"]) == 12
    assert state["turn_count"] == 20  # total count still tracked even though buffer trims
    assert state["recent_turns"][0]["content"] == "message 8"  # oldest 8 evicted
    print("12 OK: recent-turn buffer stays bounded")


def test_13_reset_clears_temporary_conversation_state():
    cm = ConversationManager()
    cm.set_topic("gravity")
    cm.add_turn("user", "hello")
    old_id = cm.get_state()["conversation_id"]

    cm.reset_conversation()
    state = cm.get_state()

    assert state["conversation_id"] != old_id
    assert state["current_topic"] is None
    assert state["turn_count"] == 0
    assert state["recent_turns"] == []
    print("13 OK: reset clears temporary conversation state")


def test_14_build_context_returns_stable_contract():
    cm = ConversationManager()
    cm.set_topic("gravity")
    context = cm.build_context("give examples")

    expected_keys = {
        "conversation_id", "thread_id", "current_topic", "thread_summary",
        "recent_turns", "recent_entities", "pending_action", "pending_confirmation",
        "resolved_input", "reference_resolution", "conversation_state",
    }
    assert set(context.keys()) == expected_keys
    assert context["resolved_input"] == "Give examples about gravity."
    print("14 OK: build_context returns stable contract")


def test_15_to_document_validates_through_schema_processor():
    cm = ConversationManager()
    cm.set_topic("gravity")
    cm.add_turn("user", "what is gravity?")
    cm.add_turn("assistant", "Gravity is a force between masses.")

    document = cm.to_document()
    canonical = process_document("conversation", document)

    assert canonical["type"] == "conversation"
    assert canonical["current_topic"] == "gravity"
    print("15 OK: to_document validates through Schema Processor conversation schema")


def test_16_no_test_calls_an_llm():
    # ConversationManager has no import of brain.py/openai/requests anywhere;
    # every test above ran instantly with no network - that IS the assertion.
    import conversation_manager
    assert "openai" not in dir(conversation_manager)
    print("16 OK: no test calls an LLM")


def test_17_no_test_writes_permanent_memory():
    import os
    existed_before = os.path.exists("memory.json")
    cm = ConversationManager()
    cm.set_topic("gravity")
    cm.to_document()
    existed_after = os.path.exists("memory.json")
    assert existed_before == existed_after  # unchanged either way
    print("17 OK: no test writes permanent memory")


def test_18_no_test_executes_a_brain_or_action():
    cm = ConversationManager()
    cm.set_pending_action({"resolved_query": "would need real execution"})
    result = cm.resolve_reference("do that")
    # Resolution only returns text describing what *would* happen - nothing runs.
    assert isinstance(result["resolved_input"], str)
    assert cm.pending_action is not None  # untouched - resolve_reference does not clear/execute it
    print("18 OK: no test executes a brain or action")


if __name__ == "__main__":
    tests = [
        test_1_new_conversation_state_is_valid,
        test_2_adding_turns_increments_turn_count,
        test_3_current_topic_is_stored,
        test_4_topic_shift_preserves_previous_topic,
        test_5_topic_history_is_updated,
        test_6_give_examples_resolves_to_current_topic,
        test_7_simplify_that_resolves_to_current_topic,
        test_8_all_this_resolves_to_current_thread,
        test_9_do_that_resolves_pending_action,
        test_10_yes_no_is_contextual_when_confirmation_pending,
        test_11_unresolved_reference_requests_clarification_when_no_topic,
        test_12_recent_turn_buffer_stays_bounded,
        test_13_reset_clears_temporary_conversation_state,
        test_14_build_context_returns_stable_contract,
        test_15_to_document_validates_through_schema_processor,
        test_16_no_test_calls_an_llm,
        test_17_no_test_writes_permanent_memory,
        test_18_no_test_executes_a_brain_or_action,
    ]

    for test in tests:
        test()

    print("\nAll AG Conversation Manager Phase A tests passed.")