"""
test_brain_dispatcher.py
=========================
Unit tests for AG Brain Interface & Dispatcher (Phase A).
Ensures zero-network deterministic mock execution, target resolution based on
Brain Demand, and standardized BrainResponse structure.
"""

from brains.brain_dispatcher import BrainDispatcher, MockBrainAdapter, BrainResponse


def test_mock_brain_adapter():
    adapter = MockBrainAdapter()
    payload = {
        "mode": "QUERY",
        "user_prompt": "Explain gravity",
        "system_context": {"active_objective": "Physics Study"}
    }

    response = adapter.execute(payload)

    assert isinstance(response, BrainResponse)
    assert response.brain_id == "mock_brain_v1"
    assert "Physics Study" in response.content
    assert response.latency_ms >= 0.0
    assert response.metadata["simulated"] is True
    print("✓ test_mock_brain_adapter passed")


def test_brain_target_resolution():
    dispatcher = BrainDispatcher()

    # Fast / local query demand
    local_demand = {"local_preferred": True, "required_tier": "fast_local_or_cloud"}
    target_local = dispatcher.resolve_brain_target(local_demand)
    assert target_local == "local_default"

    # Deep thinking / cloud demand
    cloud_demand = {"local_preferred": False, "required_tier": "cloud_deep_thinking"}
    target_cloud = dispatcher.resolve_brain_target(cloud_demand)
    assert target_cloud == "cloud_default"
    print("✓ test_brain_target_resolution passed")


def test_dispatcher_dispatch_flow():
    dispatcher = BrainDispatcher()
    payload = {
        "mode": "PLANNING",
        "user_prompt": "Draft system architecture",
        "brain_demand": {"local_preferred": False, "required_tier": "cloud_deep_thinking"},
        "system_context": {"active_objective": "AG Beta"}
    }

    response = dispatcher.dispatch(payload)

    assert isinstance(response, BrainResponse)
    assert response.provider == "cloud_api"
    assert "AG Beta" in response.content
    print("✓ test_dispatcher_dispatch_flow passed")


def run_all_tests():
    test_mock_brain_adapter()
    test_brain_target_resolution()
    test_dispatcher_dispatch_flow()
    print("\nAll Brain Dispatcher Phase A tests passed successfully!")


if __name__ == "__main__":
    run_all_tests()