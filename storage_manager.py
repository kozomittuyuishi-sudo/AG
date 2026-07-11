"""
AG Beta — Storage Manager, Phase A.

Owns document persistence under data/collections/. Delegates normalization
and validation to schema_processor, and retrieval indexing to index_manager.

    Raw document -> schema_processor.process_document() -> canonical document
    -> Storage Manager (this file) -> collection JSON file -> Index Manager

Storage Manager may import Index Manager. Index Manager must never import
Storage Manager (avoids circular imports).

NOTE: this replaces the earlier, simpler key/value storage_manager.py from
an earlier session — that module's flat get/set/update/delete-by-key API
is superseded by this schema-aware, index-synchronized version.
"""

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import schema_processor
import index_manager

COLLECTIONS_DIR = os.path.join("data", "collections")

_VALID_COLLECTION_NAME = re.compile(r"^[A-Za-z0-9_]+$")


class StorageManagerError(Exception):
    pass


class InvalidCollectionNameError(StorageManagerError):
    def __init__(self, collection: Any):
        super().__init__(
            f"Invalid collection name: {collection!r}. "
            "Only letters, digits, and underscores are allowed."
        )
        self.collection = collection


class StorageCorruptionError(StorageManagerError):
    def __init__(self, collection: str, detail: str):
        super().__init__(f"[{collection}] Storage file is corrupt or malformed: {detail}")
        self.collection = collection
        self.detail = detail


class DocumentAlreadyExistsError(StorageManagerError):
    def __init__(self, collection: str, document_id: str):
        super().__init__(f"[{collection}] Document '{document_id}' already exists.")
        self.collection = collection
        self.document_id = document_id


class DocumentNotFoundError(StorageManagerError):
    def __init__(self, collection: str, document_id: str):
        super().__init__(f"[{collection}] Document '{document_id}' was not found.")
        self.collection = collection
        self.document_id = document_id


class IndexSynchronizationError(StorageManagerError):
    def __init__(self, collection: str, document_id: str, detail: str):
        super().__init__(
            f"[{collection}] Index synchronization failed for '{document_id}': {detail}"
        )
        self.collection = collection
        self.document_id = document_id
        self.detail = detail


# ======================================================================
# Public API
# ======================================================================


def create_document(collection: str, document_type: str, raw_document: Dict[str, Any]) -> Dict[str, Any]:
    _validate_collection_name(collection)
    canonical = schema_processor.process_document(document_type, raw_document)

    data = _load_collection_file(collection)
    document_id = canonical["id"]

    if document_id in data["documents"]:
        raise DocumentAlreadyExistsError(collection, document_id)

    data["documents"][document_id] = canonical
    data["collection"] = collection
    _save_collection_file(collection, data)

    try:
        index_manager.index_document(collection, canonical)
    except Exception as error:
        index_manager.mark_index_dirty(collection, f"index_document failed for {document_id}: {error}")
        raise IndexSynchronizationError(collection, document_id, str(error))

    return canonical


def get_document(collection: str, document_id: str) -> Optional[Dict[str, Any]]:
    _validate_collection_name(collection)
    data = _load_collection_file(collection)
    return data["documents"].get(document_id)


def update_document(collection: str, document_type: str, document_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    _validate_collection_name(collection)
    data = _load_collection_file(collection)

    old_document = data["documents"].get(document_id)
    if old_document is None:
        raise DocumentNotFoundError(collection, document_id)

    merged = dict(old_document)
    merged.update(updates)
    # Identity fields are preserved explicitly, regardless of what's in updates.
    merged["id"] = old_document["id"]
    merged["created_at"] = old_document.get("created_at")

    canonical = schema_processor.process_document(document_type, merged)

    data["documents"][document_id] = canonical
    _save_collection_file(collection, data)

    try:
        index_manager.reindex_document(collection, old_document, canonical)
    except Exception as error:
        index_manager.mark_index_dirty(collection, f"reindex failed for {document_id}: {error}")
        raise IndexSynchronizationError(collection, document_id, str(error))

    return canonical


def delete_document(collection: str, document_id: str) -> bool:
    _validate_collection_name(collection)
    data = _load_collection_file(collection)

    if document_id not in data["documents"]:
        return False

    data["documents"].pop(document_id)
    _save_collection_file(collection, data)

    try:
        index_manager.remove_document(collection, document_id)
    except Exception as error:
        index_manager.mark_index_dirty(collection, f"remove_document failed for {document_id}: {error}")
        # Deletion is already committed and remains valid even if index cleanup failed.

    return True


def list_documents(collection: str) -> List[Dict[str, Any]]:
    _validate_collection_name(collection)
    data = _load_collection_file(collection)
    return list(data["documents"].values())


def search_documents(collection: str, query: str, limit: int = 10) -> List[Dict[str, Any]]:
    _validate_collection_name(collection)
    hits = index_manager.search_index(collection, query, limit)

    data = _load_collection_file(collection)
    documents = data["documents"]

    results = []
    for hit in hits:
        document = documents.get(hit["document_id"])
        if document is None:
            continue  # stale index reference, ignored safely

        enriched = dict(document)
        enriched["_search"] = {"score": hit["score"], "matched_terms": hit["matched_terms"]}
        results.append(enriched)

    return results


def collection_exists(collection: str) -> bool:
    _validate_collection_name(collection)
    return os.path.exists(_collection_path(collection))


def backup_collection(collection: str) -> str:
    _validate_collection_name(collection)
    path = _collection_path(collection)

    if not os.path.exists(path):
        raise DocumentNotFoundError(collection, "<collection file does not exist>")

    backup_dir = os.path.join(COLLECTIONS_DIR, "backups")
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = os.path.join(backup_dir, f"{collection}.{timestamp}.bak.json")

    with open(path, "r", encoding="utf-8") as source_file:
        content = source_file.read()

    _atomic_write(backup_path, content)
    return backup_path


def rebuild_collection_index(collection: str) -> Dict[str, Any]:
    _validate_collection_name(collection)
    data = _load_collection_file(collection)
    documents = list(data["documents"].values())
    return index_manager.rebuild_index(collection, documents)


# ======================================================================
# Internal helpers
# ======================================================================


def _validate_collection_name(collection: str) -> None:
    if not isinstance(collection, str) or not _VALID_COLLECTION_NAME.match(collection):
        raise InvalidCollectionNameError(collection)


def _collection_path(collection: str) -> str:
    return os.path.join(COLLECTIONS_DIR, f"{collection}.json")


def _load_collection_file(collection: str) -> Dict[str, Any]:
    path = _collection_path(collection)

    if not os.path.exists(path):
        return {"collection": collection, "documents": {}}

    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except Exception as error:
        raise StorageCorruptionError(collection, str(error))

    if not isinstance(data, dict) or not isinstance(data.get("documents"), dict):
        raise StorageCorruptionError(collection, "expected a top-level object with a 'documents' dict")

    return data


def _save_collection_file(collection: str, data: Dict[str, Any]) -> None:
    path = _collection_path(collection)
    _atomic_write(path, json.dumps(data, indent=2))


def _atomic_write(path: str, content: str) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=directory or ".", prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(content)
            file.flush()
            try:
                os.fsync(file.fileno())
            except Exception:
                pass
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        raise