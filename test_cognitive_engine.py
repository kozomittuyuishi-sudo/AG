"""
test_cognitive_engine.py
========================
Unit tests for AG Cognitive Engine (Phase A).
Ensures deterministic context ingestion, intent classification,
brain demand framing, scratchpad evaluation, and payload assembly.
"""

from cognitive_engine import CognitiveEngine, CognitiveMode
from working_memory import WorkingMemory


def test_context_ingestion():
    wm = WorkingMemory(session_id="cog_test_01")
    wm.set_objective("Build AG Cognitive Engine")
    wm.set_current_task("Write unit tests")
    wm.add_fact("language", "Python")

    ctx = wm.build_context()
    engine = CognitiveEngine()
    cog_state = engine.ingest_context(ctx)

    assert cog_state["session_id"] == "cog_test_01"
    assert cog_state["objective"] == "Build AG Cognitive Engine"
    assert cog_state["task"] == "Write unit tests"
    assert cog_state["facts"]["language"] == "Python"
    print("✓ test_context_ingestion passed")


def test_intent_classification():
    engine = CognitiveEngine()
    empty_state = engine.ingest_context({})

    # Query Mode
    res_query = engine.classify_intent("What is the speed of light?", empty_state)
    assert res_query["mode"] == CognitiveMode.QUERY
    assert res_query["requires_simulation"] is False

    # Action Mode
    res_action = engine.classify_intent("Delete temporary log files", empty_state)
    assert res_action["mode"] == CognitiveMode.ACTION
    assert res_action["requires_simulation"] is True

   # Planning Mode
    res_plan = engine.classify_intent("Draft an architecture roadmap for AG", empty_state)
    assert res_plan["mode"] == CognitiveMode.PLANNING
    
    # Clarification Mode
    state_with_pending = engine.ingest_context({"pending_confirmation": {"action": "delete"}})
    res_clarify = engine.classify_intent("Yes", state_with_pending)
    assert res_clarify["mode"] == CognitiveMode.CLARIFICATION
    print("✓ test_intent_classification passed")


def test_brain_demand_specification():
    engine = CognitiveEngine()
    empty_state = engine.ingest_context({})

    query_intent = {"mode": CognitiveMode.QUERY}
    demand_query = engine.determine_brain_demand(query_intent, empty_state)
    assert demand_query["local_preferred"] is True

    action_intent = {"mode": CognitiveMode.ACTION}
    demand_action = engine.determine_brain_demand(action_intent, empty_state)
    assert demand_action["required_tier"] == "cloud_high_reasoning"
    assert demand_action["temperature"] == 0.1
    print("✓ test_brain_demand_specification passed")


def test_scratchpad_evaluation():
    engine = CognitiveEngine()
    entries = [
        {"timestamp": "2026-07-21T10:00:00Z", "note": "Idea A"},
        {"timestamp": "2026-07-21T10:01:00Z", "note": "Idea B"},
        {"timestamp": "2026-07-21T10:02:00Z", "note": "Idea A"},  # Most recent (10:02)
    ]

    evaluated = engine.evaluate_scratchpad(entries)
    assert len(evaluated) == 2  # Duplicate filtered out
    assert evaluated[0]["note"] == "Idea A"  # Most recent entry at 10:02:00Z
    assert evaluated[1]["note"] == "Idea B"
    assert evaluated[0]["priority"] == "high"
    print("✓ test_scratchpad_evaluation passed")


def test_payload_assembly():
    wm = WorkingMemory(session_id="payload_sess")
    wm.set_objective("Complete Beta Architecture")
    wm.add_reasoning_note("Use single file modules")

    engine = CognitiveEngine()
    cog_state = engine.ingest_context(wm.build_context())
    intent = engine.classify_intent("Plan next sprint", cog_state)
    demand = engine.determine_brain_demand(intent, cog_state)

    payload = engine.assemble_payload("Plan next sprint", cog_state, intent, demand)

    assert payload["mode"] == CognitiveMode.PLANNING
    assert payload["user_prompt"] == "Plan next sprint"
    assert payload["system_context"]["active_objective"] == "Complete Beta Architecture"
    assert "Use single file modules" in payload["system_context"]["evaluated_scratchpad"]
    print("✓ test_payload_assembly passed")


def run_all_tests():
    test_context_ingestion()
    test_intent_classification()
    test_brain_demand_specification()
    test_scratchpad_evaluation()
    test_payload_assembly()
    print("\nAll Cognitive Engine Phase A tests passed successfully!")


if __name__ == "__main__":
    run_all_tests()