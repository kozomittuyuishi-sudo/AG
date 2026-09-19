"""
test_working_memory.py
======================
Unit tests for AG Working Memory (Phase A).
Ensures zero disk writes, deterministic behavior, proper expiry,
state lifecycle, decision caching, and context construction.
"""

from datetime import datetime, timezone, timedelta
import os
import time
from memory.working_memory import WorkingMemory, get_working_memory


def test_session_creation_and_reset():
    wm = WorkingMemory(session_id="test_sess_001", ttl_seconds=60)
    doc = wm.to_document()

    assert doc["session_id"] == "test_sess_001"
    assert doc["current_objective"] is None
    assert doc["current_task"] is None
    assert doc["expires_at"] is not None

    wm.set_objective("Build AG Working Memory")
    assert wm.get_objective() == "Build AG Working Memory"

    wm.reset()
    assert wm.get_objective() is None
    print("✓ test_session_creation_and_reset passed")


def test_objective_task_topic_tracking():
    wm = WorkingMemory()
    wm.set_objective("Refactor Executive Layer")
    wm.set_current_task("Write unit tests")
    wm.set_topic("Cognitive Architecture")

    assert wm.get_objective() == "Refactor Executive Layer"
    assert wm.get_current_task() == "Write unit tests"
    assert wm.get_topic() == "Cognitive Architecture"
    print("✓ test_objective_task_topic_tracking passed")


def test_temporary_facts_and_memory_cache():
    wm = WorkingMemory()
    wm.add_fact("user_pref_language", "Python")
    assert wm.get_fact("user_pref_language") == "Python"

    wm.cache_memory({"doc_id": "mem_101", "content": "AG system design"})
    memories = wm.get_cached_memories()
    assert len(memories) == 1
    assert memories[0]["doc_id"] == "mem_101"

    wm.remove_fact("user_pref_language")
    assert wm.get_fact("user_pref_language") is None
    print("✓ test_temporary_facts_and_memory_cache passed")


def test_reasoning_scratchpad_and_decisions():
    wm = WorkingMemory()
    wm.add_reasoning_note("Assumption 1: User wants high performance")
    wm.cache_decision("selected_brain", "cloud_brain_v1")

    notes = wm.get_reasoning_notes()
    assert len(notes) == 1
    assert "Assumption 1" in notes[0]["note"]
    assert wm.get_cached_decision("selected_brain") == "cloud_brain_v1"
    print("✓ test_reasoning_scratchpad_and_decisions passed")


def test_pending_states():
    wm = WorkingMemory()
    wm.set_pending_confirmation({"action": "delete_file", "path": "/tmp/test"})
    wm.set_pending_action({"type": "exec_cmd", "cmd": "pytest"})
    wm.add_pending_question("Should we proceed with execution?")

    pending_confirmation = wm.get_pending_confirmation()
    assert pending_confirmation is not None
    assert pending_confirmation["action"] == "delete_file"

    pending_action = wm.get_pending_action()
    assert pending_action is not None
    assert pending_action["type"] == "exec_cmd"

    assert "Should we proceed with execution?" in wm.get_pending_questions()

    wm.clear_pending_confirmation()
    assert wm.get_pending_confirmation() is None
    print("✓ test_pending_states passed")


def test_build_context():
    wm = WorkingMemory(session_id="ctx_sess")
    wm.set_objective("Complete Phase A")
    wm.set_current_task("Integrate context")
    wm.set_topic("Working Memory")
    wm.add_fact("env", "development")

    ctx = wm.build_context()

    assert ctx["session_id"] == "ctx_sess"
    assert ctx["active_objective"] == "Complete Phase A"
    assert ctx["active_task"] == "Integrate context"
    assert ctx["active_topic"] == "Working Memory"
    assert ctx["temporary_facts"]["env"] == "development"
    assert "timestamp" in ctx
    print("✓ test_build_context passed")


def test_session_expiry():
    wm = WorkingMemory(ttl_seconds=1)
    wm.set_objective("Short lived objective")
    assert not wm.is_expired()

    time.sleep(1.1)
    assert wm.is_expired()
    cleared = wm.clear_expired()
    assert cleared is True
    assert wm.get_objective() is None
    print("✓ test_session_expiry passed")


def test_no_disk_writes():
    """Verify Working Memory does NOT create or alter disk memory files."""
    forbidden_files = ["memory.json", "project_context.json", "tasks.json"]
    mtimes_before = {}
    for f in forbidden_files:
        if os.path.exists(f):
            mtimes_before[f] = os.path.getmtime(f)

    wm = WorkingMemory()
    wm.set_objective("Disk test")
    wm.add_fact("key", "val")
    wm.cache_memory({"data": "test"})
    wm.build_context()

    for f in forbidden_files:
        if os.path.exists(f):
            assert os.path.getmtime(f) == mtimes_before[f], f"Forbidden write detected on {f}"
        else:
            assert not os.path.exists(f), f"Forbidden file created: {f}"

    print("✓ test_no_disk_writes passed")


def run_all_tests():
    test_session_creation_and_reset()
    test_objective_task_topic_tracking()
    test_temporary_facts_and_memory_cache()
    test_reasoning_scratchpad_and_decisions()
    test_pending_states()
    test_build_context()
    test_session_expiry()
    test_no_disk_writes()
    print("\nAll Working Memory Phase A tests passed successfully!")


if __name__ == "__main__":
    run_all_tests()