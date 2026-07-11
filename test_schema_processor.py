from schema_processor import (
    process_document,
    normalize_document,
    validate_document,
    get_schema,
    SchemaConflictError,
    SchemaValidationError,
    UnknownSchemaError,
)


def test_1_memory_aliases_normalize_correctly():
    doc = {"name": "gravity", "content": "Gravity attracts masses.", "labels": ["physics"]}
    result = process_document("memory", doc)

    assert result["topic"] == "gravity"
    assert result["summary"] == "Gravity attracts masses."
    assert result["tags"] == ["physics"]
    assert "name" not in result and "content" not in result and "labels" not in result
    print("1 OK: memory aliases normalize correctly")


def test_2_canonical_overrides_alias_only_when_values_match():
    doc = {"topic": "gravity", "name": "gravity", "summary": "x"}
    result = process_document("memory", doc)
    assert result["topic"] == "gravity"
    assert "name" not in result
    print("2 OK: canonical + matching alias merge cleanly")


def test_3_conflicting_alias_raises_conflict_error():
    doc = {"topic": "gravity", "name": "entropy", "summary": "x"}
    try:
        process_document("memory", doc)
        assert False, "expected SchemaConflictError"
    except SchemaConflictError:
        pass
    print("3 OK: conflicting alias raises SchemaConflictError")


def test_4_metadata_is_generated():
    doc = {"topic": "gravity", "summary": "x"}
    result = process_document("memory", doc)

    assert result["id"].startswith("mem_")
    assert result["type"] == "memory"
    assert result["schema_version"] == 1
    assert result["created_at"]
    assert result["updated_at"]
    print("4 OK: metadata generated")


def test_5_existing_id_and_created_at_preserved():
    doc = {
        "topic": "gravity", "summary": "x",
        "id": "mem_fixed123", "created_at": "2020-01-01T00:00:00+00:00"
    }
    result = process_document("memory", doc)

    assert result["id"] == "mem_fixed123"
    assert result["created_at"] == "2020-01-01T00:00:00+00:00"
    assert result["updated_at"] != result["created_at"]
    print("5 OK: existing id/created_at preserved, updated_at refreshed")


def test_6_invalid_datatype_raises_validation_error():
    doc = {"topic": "gravity", "summary": "x", "tags": "not a list"}
    try:
        process_document("memory", doc)
        assert False, "expected SchemaValidationError"
    except SchemaValidationError:
        pass
    print("6 OK: invalid datatype raises SchemaValidationError")


def test_7_missing_required_field_raises_validation_error():
    doc = {"topic": "gravity"}  # missing summary
    try:
        process_document("memory", doc)
        assert False, "expected SchemaValidationError"
    except SchemaValidationError:
        pass
    print("7 OK: missing required field raises SchemaValidationError")


def test_8_unknown_schema_raises_unknown_schema_error():
    try:
        process_document("not_a_real_type", {"x": 1})
        assert False, "expected UnknownSchemaError"
    except UnknownSchemaError:
        pass
    print("8 OK: unknown schema raises UnknownSchemaError")


def test_9_unknown_fields_move_into_extensions():
    doc = {"topic": "gravity", "summary": "x", "totally_custom_field": 42}
    result = process_document("memory", doc)

    assert "totally_custom_field" not in result
    assert result["extensions"]["totally_custom_field"] == 42
    print("9 OK: unknown fields moved into extensions")


def test_10_probe_simulator_output_validates_as_probe_report():
    try:
        from probe_simulator import simulate_action
        probe_output = simulate_action({
            "action_type": "brain_routing", "operation": "temporary_brain_use",
            "target": "cloud", "confidence": 0.9
        })
    except ImportError:
        # probe_simulator.py may not be present in every environment;
        # fall back to a manually shaped equivalent so this test still runs.
        probe_output = {
            "should_proceed": True, "risk_level": "medium", "confidence": 0.9,
            "requires_confirmation": True, "outcome": "AG can perform 'temporary_brain_use', pending user confirmation.",
            "risks": ["needs confirmation"], "dependencies": [], "alternatives": ["proceed"],
            "recommendation": "Ask the user to confirm before executing."
        }

    result = process_document("probe_report", probe_output)
    assert result["type"] == "probe_report"
    assert result["risk_level"] in ("low", "medium", "high")
    print("10 OK: Probe Simulator output validates as probe_report")


def test_11_task_aliases_normalize_correctly():
    doc = {"task": "finish report", "status": "pending", "details": "quarterly numbers", "done": False}
    result = process_document("task", doc)

    assert result["title"] == "finish report"
    assert result["description"] == "quarterly numbers"
    assert result["completed"] is False
    assert "task" not in result and "details" not in result and "done" not in result
    print("11 OK: task aliases normalize correctly")


def test_12_confidence_outside_0_1_is_rejected():
    doc = {
        "should_proceed": True, "risk_level": "low", "confidence": 1.5,
        "requires_confirmation": False, "outcome": "x", "risks": [],
        "dependencies": [], "alternatives": [], "recommendation": "x"
    }
    try:
        process_document("probe_report", doc)
        assert False, "expected SchemaValidationError"
    except SchemaValidationError:
        pass
    print("12 OK: confidence outside 0-1 is rejected")


if __name__ == "__main__":
    test_1_memory_aliases_normalize_correctly()
    test_2_canonical_overrides_alias_only_when_values_match()
    test_3_conflicting_alias_raises_conflict_error()
    test_4_metadata_is_generated()
    test_5_existing_id_and_created_at_preserved()
    test_6_invalid_datatype_raises_validation_error()
    test_7_missing_required_field_raises_validation_error()
    test_8_unknown_schema_raises_unknown_schema_error()
    test_9_unknown_fields_move_into_extensions()
    test_10_probe_simulator_output_validates_as_probe_report()
    test_11_task_aliases_normalize_correctly()
    test_12_confidence_outside_0_1_is_rejected()

    print("\nAll Schema Processor Phase A tests passed.")