"""
self_info/
===========
AB Self-Info System

Provides AB with a verified internal source of information about itself.
Answers self-referential queries (identity, architecture, capabilities,
limitations, operational state, and task feasibility) from structured
factual data — not LLM-invented answers.

Public API
----------
SelfInfoEngine    Top-level engine. Call .answer(query) → SelfInfoResult.
SelfInfoResult    Structured result with context_block + assessment.
route_query       Classify a query and get a QueryRoute.
is_self_info_query  Quick gate: returns True for self-info queries.
assess_task       Assess whether AB can perform a described task.
TaskAssessment    Structured assessment result.
"""

from self_info.self_info_engine import SelfInfoEngine, SelfInfoResult
from self_info.query_router import route_query, is_self_info_query, QueryRoute
from self_info.task_assessor import assess_task, TaskAssessment

__all__ = [
    "SelfInfoEngine",
    "SelfInfoResult",
    "route_query",
    "is_self_info_query",
    "QueryRoute",
    "assess_task",
    "TaskAssessment",
]
