"""
test_executive_layer.py
========================
Unit tests for AG Executive Layer (Stage 5 - Phase A).
Tests Storage Decisions (long-term memory.json trigger) and
Category Decisions (Structured vs Dynamic on the fly).
"""

from cognition.executive_layer import ExecutiveLayer, ExecutiveDecision


def test_storage_decision_triggers():
    exec_layer = ExecutiveLayer()

    # ACTION mode -> should persist long-term
    assert exec_layer.evaluate_storage_decision("Run script", "Executed", "ACTION") is True

    # QUERY mode without trigger phrase -> temporary
    assert exec_layer.evaluate_storage_decision("What is 2+2?", "4", "QUERY") is False

    # Explicit trigger word in QUERY mode -> should persist
    assert exec_layer.evaluate_storage_decision("Remember that AG is v0.23", "Saved", "QUERY") is True
    print("✓ test_storage_decision_triggers passed")


def test_category_decision_structured_vs_dynamic():
    exec_layer = ExecutiveLayer()

    # Known structured category
    cat_structured, is_dyn1 = exec_layer.evaluate_category_decision("core_facts")
    assert cat_structured == "core_facts"
    assert is_dyn1 is False

    # Dynamic category created on the fly
    cat_dynamic, is_dyn2 = exec_layer.evaluate_category_decision("quantum_physics_notes")
    assert cat_dynamic == "quantum_physics_notes"
    assert is_dyn2 is True
    print("✓ test_category_decision_structured_vs_dynamic passed")


def test_process_execution_cycle():
    exec_layer = ExecutiveLayer()
    
    mock_processed = {
        "sanitized_content": "Rule: AG uses zero-dependency modules.",
        "mode": "PLANNING"
    }
    cog_state = {"topic": "system_design_rules"}

    decision = exec_layer.process_execution_cycle(
        user_input="Define system design rules",
        processed_response=mock_processed,
        cog_state=cog_state
    )

    assert isinstance(decision, ExecutiveDecision)
    assert decision.should_persist_long_term is True
    assert decision.target_category == "system_design_rules"
    assert decision.is_dynamic_category is True
    assert decision.memory_entry is not None
    print("✓ test_process_execution_cycle passed")


def run_all_tests():
    test_storage_decision_triggers()
    test_category_decision_structured_vs_dynamic()
    test_process_execution_cycle()
    print("\nAll Executive Layer Phase A tests passed successfully!")


if __name__ == "__main__":
    run_all_tests()