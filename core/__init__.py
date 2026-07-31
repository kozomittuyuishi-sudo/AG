"""
core/
=====
AG Phase 2 — Core data objects.

Contains the structured domain objects that flow through
the cognitive pipeline. No LLM calls. No I/O. Stdlib only.

Modules
-------
thought             Central pipeline carrier object.
conversation_context  Active conversational state (replaces current_topic).
entity              Structured entity representation.
conversation_frame  Structured turn record (replaces raw Q/A pairs).
"""
