import json
import os
import shutil
import tempfile

import storage.storage_manager as sm
import storage.index_manager as im

# Redirect both modules at fresh temp directories so production AG data
# (and the real data/ dir from other modules) is never touched.
TEST_ROOT = tempfile.mkdtemp(prefix="ag_storage_index_test_")
sm.COLLECTIONS_DIR = os.path.join(TEST_ROOT, "collections")
im.INDEXES_DIR = os.path.join(TEST_ROOT, "indexes")


def reset():
    if os.path.exists(TEST_ROOT):
        shutil.rmtree(TEST_ROOT)
    os.makedirs(sm.COLLECTIONS_DIR, exist_ok=True)
    os.makedirs(im.INDEXES_DIR, exist_ok=True)


def test_1_create_memory_through_schema_processor():
    reset()
    doc = sm.create_document("memory", "memory", {"topic": "gravity", "summary": "Gravity attracts masses."})
    assert doc["type"] == "memory"
    assert doc["topic"] == "gravity"
    print("1 OK: create memory document through Schema Processor")


def test_2_stored_document_is_canonical_and_retrievable():
    reset()
    created = sm.create_document("memory", "memory", {"topic": "gravity", "summary": "x"})
    fetched = sm.get_document("memory", created["id"])
    assert fetched == created
    print("2 OK: stored document is canonical and retrievable")


def test_3_duplicate_create_is_rejected():
    reset()
    doc = sm.create_document("memory", "memory", {"topic": "gravity", "summary": "x", "id": "mem_fixed"})
    try:
        sm.create_document("memory", "memory", {"topic": "gravity", "summary": "y", "id": "mem_fixed"})
        assert False, "expected DocumentAlreadyExistsError"
    except sm.DocumentAlreadyExistsError:
        pass
    print("3 OK: duplicate create is rejected")


def test_4_update_preserves_id_and_created_at():
    reset()
    created = sm.create_document("memory", "memory", {"topic": "gravity", "summary": "x"})
    updated = sm.update_document("memory", "memory", created["id"], {"summary": "new summary"})
    assert updated["id"] == created["id"]
    assert updated["created_at"] == created["created_at"]
    print("4 OK: update preserves id and created_at")


def test_5_update_refreshes_updated_at():
    reset()
    created = sm.create_document("memory", "memory", {"topic": "gravity", "summary": "x"})
    updated = sm.update_document("memory", "memory", created["id"], {"summary": "new summary"})
    assert updated["updated_at"] != created["updated_at"]
    print("5 OK: update refreshes updated_at")


def test_6_delete_removes_document():
    reset()
    created = sm.create_document("memory", "memory", {"topic": "gravity", "summary": "x"})
    result = sm.delete_document("memory", created["id"])
    assert result is True
    assert sm.get_document("memory", created["id"]) is None
    print("6 OK: delete removes document")


def test_7_missing_delete_returns_false():
    reset()
    assert sm.delete_document("memory", "mem_does_not_exist") is False
    print("7 OK: missing delete returns False")


def test_8_invalid_collection_name_is_rejected():
    reset()
    for bad_name in ["../etc", "mem ory", "mem/ory", ""]:
        try:
            sm.list_documents(bad_name)
            assert False, f"expected InvalidCollectionNameError for {bad_name!r}"
        except sm.InvalidCollectionNameError:
            pass
    print("8 OK: invalid collection name is rejected")


def test_9_malformed_json_raises_storage_corruption_error():
    reset()
    path = sm._collection_path("memory")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not valid json")

    try:
        sm.list_documents("memory")
        assert False, "expected StorageCorruptionError"
    except sm.StorageCorruptionError:
        pass
    print("9 OK: malformed JSON raises StorageCorruptionError")


def test_10_keyword_index_finds_memory_by_topic():
    reset()
    sm.create_document("memory", "memory", {"topic": "gravity", "summary": "Gravity attracts masses."})
    results = sm.search_documents("memory", "gravity")
    assert len(results) == 1
    assert results[0]["topic"] == "gravity"
    print("10 OK: keyword index finds memory by topic")


def test_11_tag_index_finds_memory_by_tag():
    reset()
    sm.create_document("memory", "memory", {"topic": "gravity", "summary": "x", "tags": ["physics"]})
    results = sm.search_documents("memory", "physics")
    assert len(results) == 1
    print("11 OK: tag index finds memory by tag")


def test_12_entity_index_finds_memory_by_entity():
    reset()
    sm.create_document("memory", "memory", {"topic": "gravity", "summary": "x", "entities": ["newton"]})
    results = sm.search_documents("memory", "newton")
    assert len(results) == 1
    print("12 OK: entity index finds memory by entity")


def test_13_ranking_prefers_exact_topic_match():
    reset()
    sm.create_document("memory", "memory", {"topic": "gravity", "summary": "A short note that also mentions gravity in passing."})
    sm.create_document("memory", "memory", {"topic": "orbital mechanics", "summary": "gravity gravity gravity is discussed here."})
    results = sm.search_documents("memory", "gravity")
    assert results[0]["topic"] == "gravity"  # exact topic match must rank first
    print("13 OK: ranking prefers exact topic match")


def test_14_update_removes_old_index_terms():
    reset()
    created = sm.create_document("memory", "memory", {"topic": "gravity", "summary": "x", "tags": ["physics"]})
    sm.update_document("memory", "memory", created["id"], {"tags": ["biology"]})
    results = sm.search_documents("memory", "physics")
    assert results == []
    print("14 OK: update removes old index terms")


def test_15_update_adds_new_index_terms():
    reset()
    created = sm.create_document("memory", "memory", {"topic": "gravity", "summary": "x", "tags": ["physics"]})
    sm.update_document("memory", "memory", created["id"], {"tags": ["biology"]})
    results = sm.search_documents("memory", "biology")
    assert len(results) == 1
    print("15 OK: update adds new index terms")


def test_16_delete_removes_index_references():
    reset()
    created = sm.create_document("memory", "memory", {"topic": "gravity", "summary": "x"})
    sm.delete_document("memory", created["id"])
    results = sm.search_documents("memory", "gravity")
    assert results == []
    print("16 OK: delete removes index references")


def test_17_stale_index_id_is_ignored_safely():
    reset()
    created = sm.create_document("memory", "memory", {"topic": "gravity", "summary": "x"})
    # Simulate a stale index entry by removing the document directly from
    # storage without going through delete_document (index is now stale).
    data = sm._load_collection_file("memory")
    data["documents"].pop(created["id"])
    sm._save_collection_file("memory", data)

    results = sm.search_documents("memory", "gravity")
    assert results == []  # stale ID ignored, not crashed
    print("17 OK: stale index ID is ignored safely")


def test_18_rebuild_index_restores_search():
    reset()
    created = sm.create_document("memory", "memory", {"topic": "gravity", "summary": "x"})
    # Corrupt/clear the index directly, bypassing Storage Manager.
    shutil.rmtree(im.INDEXES_DIR)
    os.makedirs(im.INDEXES_DIR, exist_ok=True)
    assert sm.search_documents("memory", "gravity") == []

    report = sm.rebuild_collection_index("memory")
    assert report["documents_indexed"] == 1

    results = sm.search_documents("memory", "gravity")
    assert len(results) == 1
    print("18 OK: rebuild_index restores search")


def test_19_unknown_fields_follow_schema_processor_extensions():
    reset()
    created = sm.create_document("memory", "memory", {"topic": "gravity", "summary": "x", "custom_field": 42})
    assert "custom_field" not in created
    assert created["extensions"]["custom_field"] == 42
    print("19 OK: unknown fields follow Schema Processor extensions behaviour")


def test_20_probe_report_can_be_stored_and_retrieved():
    reset()
    probe_output = {
        "should_proceed": True, "risk_level": "medium", "confidence": 0.9,
        "requires_confirmation": True, "outcome": "x", "risks": [],
        "dependencies": [], "alternatives": [], "recommendation": "x"
    }
    created = sm.create_document("probe_reports", "probe_report", probe_output)
    fetched = sm.get_document("probe_reports", created["id"])
    assert fetched is not None and fetched["risk_level"] == "medium"
    print("20 OK: Probe report can be stored and retrieved")


if __name__ == "__main__":
    tests = [
        test_1_create_memory_through_schema_processor,
        test_2_stored_document_is_canonical_and_retrievable,
        test_3_duplicate_create_is_rejected,
        test_4_update_preserves_id_and_created_at,
        test_5_update_refreshes_updated_at,
        test_6_delete_removes_document,
        test_7_missing_delete_returns_false,
        test_8_invalid_collection_name_is_rejected,
        test_9_malformed_json_raises_storage_corruption_error,
        test_10_keyword_index_finds_memory_by_topic,
        test_11_tag_index_finds_memory_by_tag,
        test_12_entity_index_finds_memory_by_entity,
        test_13_ranking_prefers_exact_topic_match,
        test_14_update_removes_old_index_terms,
        test_15_update_adds_new_index_terms,
        test_16_delete_removes_index_references,
        test_17_stale_index_id_is_ignored_safely,
        test_18_rebuild_index_restores_search,
        test_19_unknown_fields_follow_schema_processor_extensions,
        test_20_probe_report_can_be_stored_and_retrieved,
    ]

    for test in tests:
        test()

    shutil.rmtree(TEST_ROOT, ignore_errors=True)
    print("\nAll Storage Manager and Index Manager Phase A tests passed.")
