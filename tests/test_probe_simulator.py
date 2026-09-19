from diagnostics.probe_simulator import simulate_action


def check(label, action, context=None, expect=None):
    result = simulate_action(action, context)
    print(f"--- {label} ---")
    print(result)
    if expect:
        for key, value in expect.items():
            assert result[key] == value, f"{label}: expected {key}={value}, got {result[key]}"
    print("OK\n")


# 1. Permanent brain switch -> high risk, confirmation required
check(
    "set_default_brain (permanent switch)",
    {"action_type": "brain_mode_change", "operation": "set_default_brain", "target": "cloud", "confidence": 0.95},
    expect={"risk_level": "high", "requires_confirmation": True, "should_proceed": True}
)

# 2. Temporary cloud use -> medium risk, confirmation required
check(
    "temporary_brain_use",
    {"action_type": "brain_routing", "operation": "temporary_brain_use", "target": "cloud", "confidence": 0.9},
    expect={"risk_level": "medium", "requires_confirmation": True, "should_proceed": True}
)

# 3. Normal explanation/continuation -> low risk, no confirmation needed
check(
    "continuation (normal explanation)",
    {"action_type": "continuation", "operation": "explain", "target": "gravity", "confidence": 0.95},
    expect={"risk_level": "low", "requires_confirmation": False, "should_proceed": True}
)

# 4. Low confidence -> confirmation required even if risk is low
check(
    "low confidence summary",
    {"action_type": "summary", "operation": "summarize", "target": "thread", "confidence": 0.5},
    expect={"risk_level": "low", "requires_confirmation": True, "should_proceed": True}
)

# 5. Missing data -> should_proceed False
check(
    "missing data",
    {"action_type": "task", "operation": "add_task", "target": None, "confidence": 0.9, "missing_data": ["task description"]},
    expect={"should_proceed": False}
)

# 6. Unknown action type -> should_proceed False, high risk
check(
    "unknown action type",
    {"action_type": "unknown", "operation": "unclear", "target": None, "confidence": 0.4},
    expect={"should_proceed": False, "risk_level": "high"}
)

# 7. Deletion-style operation -> high risk, confirmation required
check(
    "delete memory entry",
    {"action_type": "storage", "operation": "delete_document", "target": "physics", "confidence": 0.9},
    expect={"risk_level": "high", "requires_confirmation": True}
)

# 8. Dependencies surface correctly
check(
    "dependencies present",
    {"action_type": "storage", "operation": "store_answer", "target": "physics", "confidence": 0.9, "depends_on": ["category must exist"]},
)

print("All checks passed.")
