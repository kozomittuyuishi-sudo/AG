"""
introspection/
==============
Runtime Introspection Engine — Part B

Allows AG to inspect itself at runtime.  Everything is discovered
dynamically — no hardcoded capability files, no manifests.

Architecture
------------

Every subsystem that wishes to be inspectable must implement
``IntrospectableSubsystem``.  The ``SubsystemRegistry`` holds a live
map of name → subsystem.  The ``SnapshotBuilder`` iterates every
registered subsystem, collects runtime data, and assembles an
immutable ``RuntimeSnapshot``.  The ``IntrospectionEngine`` ties
everything together and exposes one public method: ``build_snapshot()``.

Public API
----------
IntrospectionEngine       Top-level engine.
IntrospectableSubsystem   Abstract base for all inspectable subsystems.
SubsystemRegistry         Runtime registry.
RuntimeSnapshot           Immutable snapshot of AG's runtime state.
SnapshotBuilder           Collects data and builds the snapshot.

Usage
-----
::

    from introspection import IntrospectionEngine, SubsystemRegistry
    from introspection import IntrospectableSubsystem

    registry = SubsystemRegistry()
    registry.register("my_module", MyModuleAdapter())

    engine   = IntrospectionEngine(registry=registry)
    snapshot = engine.build_snapshot()
"""

from runtime.introspection.subsystem_interface import (
    IntrospectableSubsystem,
    SubsystemStatus,
    HealthStatus,
    SubsystemHealth,
)
from runtime.introspection.subsystem_registry import SubsystemRegistry
from runtime.introspection.runtime_snapshot import RuntimeSnapshot
from runtime.introspection.snapshot_builder import SnapshotBuilder
from runtime.introspection.introspection_engine import IntrospectionEngine

__all__ = [
    "IntrospectionEngine",
    "IntrospectableSubsystem",
    "SubsystemStatus",
    "HealthStatus",
    "SubsystemHealth",
    "SubsystemRegistry",
    "RuntimeSnapshot",
    "SnapshotBuilder",
]
