from probe_simulator import simulate_action


def test_delete_memory_requires_confirmation() -> None:
    result = simulate_action(
        {
            "action_type": "storage",
            "operation": "delete_all_memories",
            "scope": "global",
            "parameters": {},
        }
    )

    assert result is not None
    assert result["requires_confirmation"] is True
    assert result["should_proceed"] is True
    assert result["risk_level"] == "high"
    assert len(result["risks"]) > 0


def test_add_task_is_safe() -> None:
    result = simulate_action(
        {
            "action_type": "task",
            "operation": "add_task",
            "scope": "global",
            "parameters": {
                "title": "Test Probe Simulator",
            },
        }
    )

    assert result is not None
    assert result["should_proceed"] is True
    assert result["requires_confirmation"] is False
    assert result["risk_level"] == "low"


def test_temporary_cloud_requires_confirmation() -> None:
    result = simulate_action(
        {
            "action_type": "brain_routing",
            "operation": "temporary_brain_use",
            "scope": "current_thread",
            "target": "cloud",
            "parameters": {
                "brain": "cloud",
                "restore_previous_mode": True,
            },
        }
    )

    assert result is not None
    assert result["should_proceed"] is True
    assert result["requires_confirmation"] is True
    assert result["risk_level"] == "medium"

    dependencies = " ".join(result.get("dependencies", [])).lower()
    assert "provider" in dependencies or "reachable" in dependencies


def test_missing_data_blocks_execution() -> None:
    result = simulate_action(
        {
            "action_type": "brain_routing",
            "operation": "temporary_brain_use",
            "scope": "single_query",
            "parameters": {},
            "missing_data": ["brain"],
        }
    )

    assert result is not None
    assert result["should_proceed"] is False
    assert result["requires_confirmation"] is True

    risks = " ".join(result.get("risks", [])).lower()
    assert "missing" in risks
    assert "brain" in risks


def test_unknown_action_is_blocked() -> None:
    result = simulate_action(
        {
            "action_type": "unknown",
            "operation": "unclear",
            "target": None,
            "confidence": 0.4,
        }
    )

    assert result is not None
    assert result["should_proceed"] is False
    assert result["risk_level"] == "high"
    assert result["requires_confirmation"] is True


if __name__ == "__main__":
    test_delete_memory_requires_confirmation()
    test_add_task_is_safe()
    test_temporary_cloud_requires_confirmation()
    test_missing_data_blocks_execution()
    test_unknown_action_is_blocked()

    print("All Probe Simulator assertion tests passed.")