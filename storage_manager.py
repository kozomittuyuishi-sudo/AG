"""
NoSQL-style document storage over AG's existing JSON files.
This does NOT replace memory.json/tasks.json/etc — it's a thin
key/value access layer over them, plus an append-only JSONL
collection for warehouse events.
"""

import json
import os

COLLECTION_FILES = {
    "memory": "memory.json",
    "tasks": "tasks.json",
    "projects": "project_context.json",
    "brain_config": "brain_config.json",
    "warehouse_events": os.path.join("data", "warehouse", "events.jsonl"),
}


def _resolve_path(name: str) -> str:
    path = COLLECTION_FILES.get(name, f"{name}.json")
    directory = os.path.dirname(path)

    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)

    return path


def load_collection(name: str) -> dict:
    path = _resolve_path(name)

    if not os.path.exists(path):
        return {}

    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_collection(name: str, data: dict) -> None:
    path = _resolve_path(name)

    try:
        with open(path, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=4)
    except Exception:
        pass


def get_document(collection: str, key: str, default=None):
    data = load_collection(collection)
    return data.get(key, default)


def set_document(collection: str, key: str, value) -> None:
    data = load_collection(collection)
    data[key] = value
    save_collection(collection, data)


def update_document(collection: str, key: str, updates: dict) -> None:
    data = load_collection(collection)
    existing = data.get(key)

    if isinstance(existing, dict) and isinstance(updates, dict):
        existing.update(updates)
        data[key] = existing
    else:
        data[key] = updates

    save_collection(collection, data)


def delete_document(collection: str, key: str) -> bool:
    data = load_collection(collection)

    if key not in data:
        return False

    del data[key]
    save_collection(collection, data)
    return True


def search_collection(collection: str, keyword: str) -> list:
    data = load_collection(collection)
    keyword = str(keyword).strip().lower()
    results = []

    for key, value in data.items():
        haystack = f"{key} {value}".lower()
        if keyword in haystack:
            results.append({"key": key, "value": value})

    return results


def append_event(collection: str, event: dict) -> None:
    """Append-only writer for JSONL-style collections (e.g. warehouse_events)."""
    path = _resolve_path(collection)

    try:
        with open(path, "a", encoding="utf-8") as file:
            file.write(json.dumps(event) + "\n")
    except Exception:
        pass