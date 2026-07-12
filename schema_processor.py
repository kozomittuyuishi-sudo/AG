"""
AG Beta — Schema Processor, Phase A.

Transforms raw dictionaries into canonical AG documents:

    Raw document -> normalize aliases -> add metadata -> validate -> canonical document

This module does NOT write files and is NOT a database. It's a pure
in-memory transformation/validation layer that Storage Manager consumes.

This is one cohesive subsystem and stays as a single runtime file
(see the architecture note at the bottom of this docstring). It is
organized internally into 9 clearly marked sections:

  1. Custom exceptions
  2. Common metadata constants and helpers
  3. Canonical schema definitions
  4. Schema registry
  5. Alias normalization
  6. Validation helpers
  7. Metadata generation
  8. Version checks
  9. Public API

Python standard library only. Deterministic. No LLM calls.

---
Architecture note: split into a package (schema_registry.py,
schema_validator.py, etc.) only if one of these becomes true:
  - this file exceeds roughly 700-1000 meaningful lines
  - schema migration becomes a substantial subsystem
  - schema definitions become independently maintained
  - the single file becomes genuinely hard to understand or test
Until then: one cohesive subsystem = one runtime file.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List


# ======================================================================
# 1. Custom exceptions
# ======================================================================


class SchemaProcessorError(Exception):
    """Base exception for all Schema Processor failures."""


class UnknownSchemaError(SchemaProcessorError):
    def __init__(self, document_type: Any):
        message = (
            f"Unknown schema '{document_type}'. "
            f"Registered types: {sorted(SCHEMA_REGISTRY.keys())}"
        )
        super().__init__(message)
        self.document_type = document_type


class SchemaValidationError(SchemaProcessorError):
    def __init__(self, document_type: str, field: str, expected: Any, received: Any):
        message = (
            f"[{document_type}] Field '{field}' failed validation. "
            f"Expected: {expected!r}, received: {received!r}"
        )
        super().__init__(message)
        self.document_type = document_type
        self.field = field
        self.expected = expected
        self.received = received


class SchemaConflictError(SchemaProcessorError):
    def __init__(self, document_type: str, field: str, expected_value: Any, received_values: List[Any]):
        message = (
            f"[{document_type}] Conflicting values for '{field}'. "
            f"Expected a single consistent value like {expected_value!r}, "
            f"but received differing values: {received_values!r}"
        )
        super().__init__(message)
        self.document_type = document_type
        self.field = field
        self.expected = expected_value
        self.received = received_values


# ======================================================================
# 2. Common metadata constants and helpers
# ======================================================================

LIST_OF_STR = "list[str]"
ANY_TYPE = "any"
METADATA_FIELDS = {"id", "type", "schema_version", "created_at", "updated_at", "extensions"}


def _is_valid_iso8601(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except Exception:
        return False


# ======================================================================
# 3. Canonical schema definitions
#
# Each document type below defines: canonical type name, id prefix,
# required fields, optional fields (with expected datatypes), alias
# mapping, default values, and the current schema version.
# ======================================================================


# ======================================================================
# 4. Schema registry — one dict entry per document type, no if/elif chain
# ======================================================================

SCHEMA_REGISTRY: Dict[str, Dict[str, Any]] = {
    "memory": {
        "type": "memory",
        "id_prefix": "mem",
        "version": 1,
        "required": {"topic": str, "summary": str},
        "optional": {
            "tags": LIST_OF_STR,
            "entities": LIST_OF_STR,
            "relations": list,
            "importance": float,
            "confidence": float,
            "source": str,
            "category": str,
        },
        "aliases": {
            "name": "topic", "title": "topic", "heading": "topic",
            "content": "summary", "body": "summary", "text": "summary", "description": "summary",
            "labels": "tags",
            "weight": "importance", "priority": "importance",
        },
        "defaults": {
            "tags": list, "entities": list, "relations": list,
            "importance": lambda: 0.5, "confidence": lambda: 1.0,
            "source": lambda: "unknown", "category": lambda: "general",
        },
    },
    "task": {
        "type": "task",
        "id_prefix": "task",
        "version": 1,
        "required": {"title": str, "status": str},
        "optional": {
            "description": str,
            "priority": int,
            "project_id": (str, type(None)),
            "dependencies": LIST_OF_STR,
            "completed": bool,
        },
        "aliases": {
            "name": "title", "task": "title", "task_text": "title",
            "details": "description", "body": "description", "content": "description",
            "done": "completed", "is_complete": "completed",
        },
        "defaults": {
            "description": lambda: "", "priority": lambda: 0,
            "project_id": lambda: None, "dependencies": list, "completed": lambda: False,
        },
    },
    "project": {
        "type": "project",
        "id_prefix": "proj",
        "version": 1,
        "required": {"name": str, "version": str, "current_milestone": str},
        "optional": {
            "next_step": str,
            "completed_milestones": LIST_OF_STR,
            "known_issues": LIST_OF_STR,
            "status": str,
        },
        "aliases": {},
        "defaults": {
            "next_step": lambda: "", "completed_milestones": list,
            "known_issues": list, "status": lambda: "active",
        },
    },
    "conversation": {
        "type": "conversation",
        "id_prefix": "conv",
        "version": 1,
        "required": {"current_topic": str, "turns": list},
        "optional": {
            "thread_summary": str,
            "entities": LIST_OF_STR,
            "references": LIST_OF_STR,
            "pending_clarification": bool,
        },
        "aliases": {},
        "defaults": {
            "thread_summary": lambda: "", "entities": list,
            "references": list, "pending_clarification": lambda: False,
        },
    },
    "action_plan": {
        "type": "action_plan",
        "id_prefix": "plan",
        "version": 1,
        "required": {"primary_intent": str, "actions": list},
        "optional": {
            "confidence": float,
            "missing_data": LIST_OF_STR,
            "requires_confirmation": bool,
            "status": str,
        },
        "aliases": {},
        "defaults": {
            "confidence": lambda: 1.0, "missing_data": list,
            "requires_confirmation": lambda: False, "status": lambda: "pending",
        },
    },
    "probe_report": {
        "type": "probe_report",
        "id_prefix": "probe",
        "version": 1,
        "required": {
            "should_proceed": bool, "risk_level": str, "confidence": float,
            "requires_confirmation": bool, "outcome": str, "risks": list,
            "dependencies": list, "alternatives": list, "recommendation": str,
        },
        "optional": {},
        "aliases": {},
        "defaults": {},
    },
    "warehouse_event": {
        "type": "warehouse_event",
        "id_prefix": "evt",
        "version": 1,
        "required": {"event_type": str, "payload": dict},
        "optional": {"topic": str, "success": bool},
        "aliases": {},
        "defaults": {"topic": lambda: "", "success": lambda: True},
    },
    "configuration": {
        "type": "configuration",
        "id_prefix": "cfg",
        "version": 1,
        "required": {"key": str, "value": ANY_TYPE},
        "optional": {},
        "aliases": {},
        "defaults": {},
    },
}


# ======================================================================
# 5. Alias normalization
# ======================================================================


def _normalize_aliases(document_type: str, document: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
    doc = dict(document)
    alias_map: Dict[str, str] = schema["aliases"]

    grouped: Dict[str, List[str]] = {}
    for alias_key, canonical_field in alias_map.items():
        grouped.setdefault(canonical_field, []).append(alias_key)

    for canonical_field, alias_keys in grouped.items():
        present_keys = [canonical_field] if canonical_field in doc else []
        present_keys += [key for key in alias_keys if key in doc]

        if not present_keys:
            continue

        values = [doc[key] for key in present_keys]
        first_value = values[0]

        if not all(value == first_value for value in values):
            raise SchemaConflictError(document_type, canonical_field, first_value, values)

        doc[canonical_field] = first_value

        for alias_key in alias_keys:
            doc.pop(alias_key, None)

    return doc


# ======================================================================
# 6. Validation helpers
# ======================================================================


def _check_field_type(document_type: str, field_name: str, value: Any, dtype: Any) -> None:
    if dtype == ANY_TYPE:
        return

    if dtype == LIST_OF_STR:
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise SchemaValidationError(document_type, field_name, "list[str]", value)
        return

    if isinstance(dtype, tuple):
        if not isinstance(value, dtype):
            expected = "/".join(t.__name__ for t in dtype)
            raise SchemaValidationError(document_type, field_name, expected, type(value).__name__)
        return

    if dtype is bool:
        if not isinstance(value, bool):
            raise SchemaValidationError(document_type, field_name, "bool", type(value).__name__)
        return

    if dtype is int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise SchemaValidationError(document_type, field_name, "int", type(value).__name__)
        return

    if dtype is float:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise SchemaValidationError(document_type, field_name, "float", type(value).__name__)
        return

    if not isinstance(value, dtype):
        raise SchemaValidationError(document_type, field_name, dtype.__name__, type(value).__name__)


def _validate_bounded_float(document_type: str, document: Dict[str, Any], field_name: str) -> None:
    if field_name not in document:
        return

    value = document[field_name]
    is_number = isinstance(value, (int, float)) and not isinstance(value, bool)

    if not is_number or not (0.0 <= float(value) <= 1.0):
        raise SchemaValidationError(document_type, field_name, "float between 0.0 and 1.0", value)


def _validate_enum_fields(document_type: str, document: Dict[str, Any]) -> None:
    """Document-type-specific enum checks that go beyond plain datatype checks."""
    if document_type == "probe_report" and document.get("risk_level") not in ("low", "medium", "high"):
        raise SchemaValidationError(
            document_type, "risk_level", "one of: low, medium, high", document.get("risk_level")
        )

    if document_type == "task" and "status" in document:
        allowed = {"pending", "active", "completed", "cancelled"}
        if document["status"] not in allowed:
            raise SchemaValidationError(document_type, "status", f"one of: {sorted(allowed)}", document["status"])


# ======================================================================
# 7. Metadata generation
# ======================================================================


def _apply_defaults(document: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
    doc = dict(document)
    for field_name, default_factory in schema["defaults"].items():
        if field_name not in doc:
            doc[field_name] = default_factory()
    return doc


def _apply_metadata(document: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
    doc = dict(document)
    now = datetime.now(timezone.utc).isoformat()

    existing_id = doc.get("id")
    doc["id"] = existing_id if isinstance(existing_id, str) and existing_id.strip() else f"{schema['id_prefix']}_{uuid.uuid4().hex[:12]}"

    doc["type"] = schema["type"]

    existing_version = doc.get("schema_version")
    doc["schema_version"] = existing_version if isinstance(existing_version, int) and not isinstance(existing_version, bool) else schema["version"]

    existing_created = doc.get("created_at")
    doc["created_at"] = existing_created if _is_valid_iso8601(existing_created) else now

    doc["updated_at"] = now

    return doc


def _move_unknown_fields_to_extensions(document: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
    doc = dict(document)
    known_fields = set(schema["required"].keys()) | set(schema["optional"].keys()) | METADATA_FIELDS

    extensions = doc.get("extensions")
    extensions = dict(extensions) if isinstance(extensions, dict) else {}

    for key in list(doc.keys()):
        if key not in known_fields and key != "extensions":
            extensions[key] = doc.pop(key)

    doc["extensions"] = extensions
    return doc


# ======================================================================
# 8. Version checks
# ======================================================================


def _check_schema_version(document_type: str, document: Dict[str, Any], schema: Dict[str, Any]) -> None:
    """No migrations yet (Phase A) - the only supported version is the schema's current version."""
    version = document.get("schema_version")
    if version != schema["version"]:
        raise SchemaValidationError(document_type, "schema_version", schema["version"], version)


# ======================================================================
# 9. Public API
# ======================================================================


def get_schema(document_type: str) -> Dict[str, Any]:
    schema = SCHEMA_REGISTRY.get(document_type)
    if schema is None:
        raise UnknownSchemaError(document_type)
    return schema


def normalize_document(document_type: str, document: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(document, dict):
        raise SchemaProcessorError(
            f"[{document_type}] Expected a dict, got {type(document).__name__}."
        )

    schema = get_schema(document_type)

    doc = _normalize_aliases(document_type, document, schema)
    doc = _apply_defaults(doc, schema)
    doc = _apply_metadata(doc, schema)
    doc = _move_unknown_fields_to_extensions(doc, schema)

    return doc


def validate_document(document_type: str, document: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(document, dict):
        raise SchemaProcessorError(
            f"[{document_type}] Expected a dict, got {type(document).__name__}."
        )

    schema = get_schema(document_type)

    doc_id = document.get("id")
    if not isinstance(doc_id, str) or not doc_id.strip():
        raise SchemaValidationError(document_type, "id", "non-empty str", doc_id)

    _check_schema_version(document_type, document, schema)

    for field_name, dtype in schema["required"].items():
        if field_name not in document:
            raise SchemaValidationError(document_type, field_name, dtype, "<missing>")

    all_fields = {**schema["required"], **schema["optional"]}
    for field_name, dtype in all_fields.items():
        if field_name in document:
            _check_field_type(document_type, field_name, document[field_name], dtype)

    _validate_bounded_float(document_type, document, "confidence")
    _validate_bounded_float(document_type, document, "importance")
    _validate_enum_fields(document_type, document)

    return document


def process_document(document_type: str, document: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(document, dict):
        raise SchemaProcessorError(
            f"[{document_type}] Expected a dict, got {type(document).__name__}."
        )

    get_schema(document_type)  # raises UnknownSchemaError early for bad types

    normalized = normalize_document(document_type, document)
    validated = validate_document(document_type, normalized)
    return validated