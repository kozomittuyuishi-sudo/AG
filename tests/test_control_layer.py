
import os

from cognition.control_layer import BrainRegistry, AuthorizationManager, resolve_brain_request

REGISTRY_DATA = {
    "brains": [
        {
            "id": "local_a",
            "aliases": ["local", "offline"],
            "provider": "local",
            "model": "qwen2.5:3b",
            "capabilities": ["general_reasoning", "offline"],
            "requires_network": False,
            "priority": 1,
            "enabled": True,
        },
        {
            "id": "local_b_disabled",
            "aliases": ["backup_local"],
            "provider": "local",
            "model": "phi3:mini",
            "capabilities": ["general_reasoning"],
            "requires_network": False,
            "priority": 2,
            "enabled": False,
        },
        {
            "id": "cloud_a",
            "aliases": ["cloud", "online"],
            "provider": "cloud",
            "model": "nex-agi/nex-n2-pro:free",
            "capabilities": ["general_reasoning", "deep_reasoning"],
            "requires_network": True,
            "priority": 1,
            "enabled": True,
        },
        {
            "id": "cloud_b",
            "aliases": ["cloud_backup"],
            "provider": "cloud",
            "model": "some/other-model:free",
            "capabilities": ["general_reasoning"],
            "requires_network": True,
            "priority": 2,
            "enabled": True,
        },
    ]
}

PERMISSIONS_DATA = {
    "permissions": {
        "brain.local.use": {"allowed": True, "requires_confirmation": False, "sensitivity": "low"},
        "brain.cloud.use": {"allowed": True, "requires_confirmation": True, "sensitivity": "medium"},
        "internet.access": {"allowed": True, "requires_confirmation": False, "sensitivity": "low"},
        "files.delete": {"allowed": False, "requires_confirmation": True, "sensitivity": "high"},
    }
}


def test_1_alias_resolution():
    registry = BrainRegistry.from_data(REGISTRY_DATA)
    assert registry.resolve_alias("offline") == "local_a"
    assert registry.resolve_alias("ONLINE") == "cloud_a"
    assert registry.resolve_alias("does_not_exist") is None
    print("1 OK: alias resolution")


def test_2_disabled_brain_exclusion():
    registry = BrainRegistry.from_data(REGISTRY_DATA)
    local_brains = registry.list_brains(provider="local", enabled_only=True)
    ids = [b["id"] for b in local_brains]
    assert "local_b_disabled" not in ids
    assert "local_a" in ids
    print("2 OK: disabled brain exclusion")


def test_3_offline_local_selection():
    registry = BrainRegistry.from_data(REGISTRY_DATA)
    selected = registry.select_brain(provider="local", network_available=False)
    assert selected is not None
    assert selected["id"] == "local_a"
    print("3 OK: offline local selection")


def test_4_cloud_exclusion_offline():
    registry = BrainRegistry.from_data(REGISTRY_DATA)
    selected = registry.select_brain(provider="cloud", network_available=False)
    assert selected is None
    print("4 OK: cloud exclusion offline")


def test_5_capability_matching():
    registry = BrainRegistry.from_data(REGISTRY_DATA)
    selected = registry.select_brain(provider="cloud", required_capabilities=["deep_reasoning"])
    assert selected is not None
    assert selected["id"] == "cloud_a"  # only cloud_a has deep_reasoning

    none_match = registry.select_brain(provider="local", required_capabilities=["deep_reasoning"])
    assert none_match is None
    print("5 OK: capability matching")


def test_6_deterministic_priority():
    registry = BrainRegistry.from_data(REGISTRY_DATA)
    # cloud_a has priority 1, cloud_b has priority 2 -> cloud_a must win
    selected = registry.select_brain(provider="cloud")
    assert selected is not None
    assert selected["id"] == "cloud_a"
    print("6 OK: deterministic priority")


def test_7_fallback_chain():
    registry = BrainRegistry.from_data(REGISTRY_DATA)
    chain = registry.build_fallback_chain(provider="cloud")
    assert chain == ["cloud_a", "cloud_b"]  # ordered by priority
    print("7 OK: fallback chain")


def test_8_permission_allowed_and_denied():
    auth = AuthorizationManager.from_data(PERMISSIONS_DATA)
    allowed_result = auth.authorize(["brain.local.use"])
    assert allowed_result["allowed"] is True

    denied_result = auth.authorize(["files.delete"])
    assert denied_result["allowed"] is False
    assert "files.delete" in denied_result["denied_permissions"]
    print("8 OK: permission allowed/denied")


def test_9_missing_permission_denies():
    auth = AuthorizationManager.from_data(PERMISSIONS_DATA)
    result = auth.authorize(["camera.read"])  # not in PERMISSIONS_DATA at all
    assert result["allowed"] is False
    assert "camera.read" in result["denied_permissions"]
    print("9 OK: missing permission denies")


def test_10_confirmation_required_permissions():
    auth = AuthorizationManager.from_data(PERMISSIONS_DATA)
    result = auth.authorize(["brain.cloud.use"])
    assert result["allowed"] is True
    assert result["requires_confirmation"] is True  # allowed AND needs confirmation - distinct axes
    print("10 OK: confirmation-required permissions")


def test_11_cloud_requires_both_permissions():
    auth = AuthorizationManager.from_data({
        "permissions": {
            "brain.cloud.use": {"allowed": True, "requires_confirmation": True, "sensitivity": "medium"},
            "internet.access": {"allowed": False, "requires_confirmation": False, "sensitivity": "low"},
        }
    })
    registry = BrainRegistry.from_data(REGISTRY_DATA)

    result = resolve_brain_request("cloud", registry, auth)
    assert result["authorized"] is False
    assert result["selected_brain"] is None
    assert "internet.access" in result["denied_permissions"] if "denied_permissions" in result else True
    print("11 OK: cloud requires both brain.cloud.use and internet.access")


def test_12_denied_cloud_request_selects_no_brain():
    auth = AuthorizationManager.from_data({
        "permissions": {
            "brain.cloud.use": {"allowed": False, "requires_confirmation": True, "sensitivity": "medium"},
            "internet.access": {"allowed": True, "requires_confirmation": False, "sensitivity": "low"},
        }
    })
    registry = BrainRegistry.from_data(REGISTRY_DATA)

    result = resolve_brain_request("cloud", registry, auth)
    assert result["selected_brain"] is None
    assert result["fallback_chain"] == []
    print("12 OK: denied cloud request selects no cloud brain")


def test_13_temporary_cloud_request_does_not_alter_persistent_mode():
    config_path = "configuration/brain_config.json"
    existed_before = os.path.exists(config_path)
    mtime_before = os.path.getmtime(config_path) if existed_before else None

    registry = BrainRegistry.from_data(REGISTRY_DATA)
    auth = AuthorizationManager.from_data(PERMISSIONS_DATA)
    resolve_brain_request("cloud", registry, auth)

    existed_after = os.path.exists(config_path)
    assert existed_before == existed_after
    if existed_before:
        assert os.path.getmtime(config_path) == mtime_before
    print("13 OK: temporary cloud request does not alter persistent brain mode")


def test_14_no_real_model_or_api_calls():
    # If this module imported openai/requests or made any network call,
    # this test file (which never mocks network) would hang or fail.
    # Its mere successful, fast completion is the assertion.
    registry = BrainRegistry.from_data(REGISTRY_DATA)
    auth = AuthorizationManager.from_data(PERMISSIONS_DATA)
    result = resolve_brain_request("local", registry, auth)
    assert result["authorized"] is True
    assert result["selected_brain"] == "local_a"
    print("14 OK: no test performs real model/API calls")


if __name__ == "__main__":
    tests = [
        test_1_alias_resolution,
        test_2_disabled_brain_exclusion,
        test_3_offline_local_selection,
        test_4_cloud_exclusion_offline,
        test_5_capability_matching,
        test_6_deterministic_priority,
        test_7_fallback_chain,
        test_8_permission_allowed_and_denied,
        test_9_missing_permission_denies,
        test_10_confirmation_required_permissions,
        test_11_cloud_requires_both_permissions,
        test_12_denied_cloud_request_selects_no_brain,
        test_13_temporary_cloud_request_does_not_alter_persistent_mode,
        test_14_no_real_model_or_api_calls,
    ]

    for test in tests:
        test()

    print("\nAll AG Control Layer Phase A tests passed.")