"""
AG Beta — Index Manager, Phase A.

Owns deterministic retrieval indexes (keyword/tag/entity/metadata) under
data/indexes/. Stores document ID references only, never full documents.

Must NOT import storage_manager (Storage Manager imports this module,
not the other way around, to avoid circular imports).
"""

import json
import os
import re
import tempfile
from typing import Any, Dict, List

INDEXES_DIR = os.path.join("data", "indexes")

_VALID_NAME = re.compile(r"^[A-Za-z0-9_]+$")
_TOKEN_RE = re.compile(r"[a-z0-9]+")

STOP_WORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for",
    "is", "are", "with", "this", "that", "it", "as", "by", "at",
    "be", "was", "were",
}

SEARCHABLE_TEXT_FIELDS = [
    "topic", "title", "name", "summary", "description",
    "current_milestone", "next_step", "event_type",
]
LABEL_FIELDS = ["topic", "title", "name"]


class IndexManagerError(Exception):
    pass


# ======================================================================
# Public API
# ======================================================================


def index_document(collection: str, document: Dict[str, Any]) -> None:
    _validate_collection_name(collection)
    document_id = document.get("id")
    if not document_id:
        raise IndexManagerError(f"[{collection}] Cannot index a document without an 'id'.")

    index = _load_index_file(collection)

    if document_id in index["doc_terms"]:
        _remove_postings(index, document_id)

    terms = _extract_terms(document)
    index["doc_terms"][document_id] = terms

    for token in terms["keywords"]:
        bucket = index["keyword_index"].setdefault(token, [])
        if document_id not in bucket:
            bucket.append(document_id)

    for tag in terms["tags"]:
        bucket = index["tag_index"].setdefault(tag, [])
        if document_id not in bucket:
            bucket.append(document_id)

    for entity in terms["entities"]:
        bucket = index["entity_index"].setdefault(entity, [])
        if document_id not in bucket:
            bucket.append(document_id)

    index["metadata_index"][document_id] = {
        "type": document.get("type"),
        "updated_at": document.get("updated_at"),
    }

    _save_index_file(collection, index)


def remove_document(collection: str, document_id: str) -> None:
    _validate_collection_name(collection)
    index = _load_index_file(collection)

    if document_id in index["doc_terms"]:
        _remove_postings(index, document_id)
        index["doc_terms"].pop(document_id, None)
        index["metadata_index"].pop(document_id, None)

    _save_index_file(collection, index)


def reindex_document(collection: str, old_document: Dict[str, Any], new_document: Dict[str, Any]) -> None:
    _validate_collection_name(collection)
    old_id = (old_document or {}).get("id")
    if old_id:
        remove_document(collection, old_id)
    index_document(collection, new_document)


def search_index(collection: str, query: str, limit: int = 10) -> List[Dict[str, Any]]:
    _validate_collection_name(collection)
    index = _load_index_file(collection)

    query_tokens = _tokenize(query)
    normalized_query = str(query).strip().lower()

    if not query_tokens and not normalized_query:
        return []

    candidate_ids = set()
    for token in query_tokens:
        candidate_ids.update(index["keyword_index"].get(token, []))
        candidate_ids.update(index["tag_index"].get(token, []))
        candidate_ids.update(index["entity_index"].get(token, []))

    for doc_id, terms in index["doc_terms"].items():
        if normalized_query and terms.get("primary_label") == normalized_query:
            candidate_ids.add(doc_id)

    scored = []
    for doc_id in candidate_ids:
        terms = index["doc_terms"].get(doc_id, {})
        score = 0
        matched_terms = []

        if terms.get("primary_label") and normalized_query == terms["primary_label"]:
            score += 10
            matched_terms.append(terms["primary_label"])

        for token in query_tokens:
            if token in terms.get("entities", []):
                score += 6
                matched_terms.append(token)
            elif token in terms.get("tags", []):
                score += 4
                matched_terms.append(token)
            elif token in terms.get("keywords", []):
                score += 2
                matched_terms.append(token)

        if score > 0:
            updated_at = index["metadata_index"].get(doc_id, {}).get("updated_at") or ""
            scored.append({
                "document_id": doc_id,
                "collection": collection,
                "score": score,
                "matched_terms": sorted(set(matched_terms)),
                "_updated_at": updated_at,
            })

    if scored:
        max_updated = max(item["_updated_at"] for item in scored)
        if max_updated:
            for item in scored:
                if item["_updated_at"] == max_updated:
                    item["score"] += 1

    # Stable multi-pass sort: least significant key first.
    scored.sort(key=lambda item: item["document_id"])
    scored.sort(key=lambda item: item["_updated_at"], reverse=True)
    scored.sort(key=lambda item: item["score"], reverse=True)

    return [
        {
            "document_id": item["document_id"],
            "collection": item["collection"],
            "score": item["score"],
            "matched_terms": item["matched_terms"],
        }
        for item in scored[:limit]
    ]


def rebuild_index(collection: str, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
    _validate_collection_name(collection)
    index = _empty_index(collection)

    for document in documents:
        document_id = document.get("id")
        if not document_id:
            continue

        terms = _extract_terms(document)
        index["doc_terms"][document_id] = terms

        for token in terms["keywords"]:
            index["keyword_index"].setdefault(token, []).append(document_id)
        for tag in terms["tags"]:
            index["tag_index"].setdefault(tag, []).append(document_id)
        for entity in terms["entities"]:
            index["entity_index"].setdefault(entity, []).append(document_id)

        index["metadata_index"][document_id] = {
            "type": document.get("type"),
            "updated_at": document.get("updated_at"),
        }

    _save_index_file(collection, index)

    return {
        "collection": collection,
        "documents_indexed": len(index["doc_terms"]),
        "dirty": False,
    }


def get_index_status(collection: str) -> Dict[str, Any]:
    _validate_collection_name(collection)
    index = _load_index_file(collection)
    return {
        "collection": collection,
        "dirty": index.get("dirty", False),
        "dirty_reasons": index.get("dirty_reasons", []),
        "document_count": len(index.get("doc_terms", {})),
        "keyword_count": len(index.get("keyword_index", {})),
        "tag_count": len(index.get("tag_index", {})),
        "entity_count": len(index.get("entity_index", {})),
    }


def mark_index_dirty(collection: str, reason: str) -> None:
    _validate_collection_name(collection)
    index = _load_index_file(collection)
    index["dirty"] = True
    index.setdefault("dirty_reasons", []).append(str(reason))
    _save_index_file(collection, index)


# ======================================================================
# Internal helpers
# ======================================================================


def _validate_collection_name(collection: str) -> None:
    if not isinstance(collection, str) or not _VALID_NAME.match(collection):
        raise IndexManagerError(f"Invalid collection name: {collection!r}")


def _tokenize(text: Any) -> List[str]:
    if not text:
        return []
    tokens = _TOKEN_RE.findall(str(text).lower())
    return [token for token in tokens if token not in STOP_WORDS]


def _extract_terms(document: Dict[str, Any]) -> Dict[str, Any]:
    keywords = set()
    for field in SEARCHABLE_TEXT_FIELDS:
        value = document.get(field)
        if isinstance(value, str):
            keywords.update(_tokenize(value))

    tags = {v.strip().lower() for v in (document.get("tags") or []) if isinstance(v, str) and v.strip()}
    entities = {v.strip().lower() for v in (document.get("entities") or []) if isinstance(v, str) and v.strip()}

    primary_label = ""
    for field in LABEL_FIELDS:
        value = document.get(field)
        if isinstance(value, str) and value.strip():
            primary_label = value.strip().lower()
            break

    return {
        "keywords": sorted(keywords),
        "tags": sorted(tags),
        "entities": sorted(entities),
        "primary_label": primary_label,
    }


def _remove_postings(index: Dict[str, Any], document_id: str) -> None:
    terms = index["doc_terms"].get(document_id, {})

    for token in terms.get("keywords", []):
        bucket = index["keyword_index"].get(token)
        if bucket and document_id in bucket:
            bucket.remove(document_id)
            if not bucket:
                del index["keyword_index"][token]

    for tag in terms.get("tags", []):
        bucket = index["tag_index"].get(tag)
        if bucket and document_id in bucket:
            bucket.remove(document_id)
            if not bucket:
                del index["tag_index"][tag]

    for entity in terms.get("entities", []):
        bucket = index["entity_index"].get(entity)
        if bucket and document_id in bucket:
            bucket.remove(document_id)
            if not bucket:
                del index["entity_index"][entity]


def _empty_index(collection: str) -> Dict[str, Any]:
    return {
        "collection": collection,
        "dirty": False,
        "dirty_reasons": [],
        "keyword_index": {},
        "tag_index": {},
        "entity_index": {},
        "metadata_index": {},
        "doc_terms": {},
    }


def _index_path(collection: str) -> str:
    return os.path.join(INDEXES_DIR, f"{collection}.index.json")


def _load_index_file(collection: str) -> Dict[str, Any]:
    path = _index_path(collection)

    if not os.path.exists(path):
        return _empty_index(collection)

    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except Exception as error:
        raise IndexManagerError(f"[{collection}] Corrupt index file: {error}")

    if not isinstance(data, dict):
        raise IndexManagerError(f"[{collection}] Malformed index file structure.")

    for key, default in _empty_index(collection).items():
        data.setdefault(key, default)

    return data


def _save_index_file(collection: str, index: Dict[str, Any]) -> None:
    path = _index_path(collection)
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(json.dumps(index, indent=2))
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