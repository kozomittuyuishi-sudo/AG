"""
introspection/snapshot_builder.py
====================================
Snapshot Builder

Iterates every subsystem registered in a SubsystemRegistry, calls the
five interface methods on each, aggregates the results, and assembles
a single immutable RuntimeSnapshot.

Discovery is entirely dynamic — the builder does not know about specific
subsystems in advance.  It calls all five methods defensively (wrapped in
try/except) so that a misbehaving subsystem never prevents snapshot
completion.

Design principles
-----------------
- Never raises; returns a partial snapshot with error notes if a
  subsystem method fails.
- Detects which subsystems are brains / memory based on naming
  conventions AND optional ``_subsystem_type`` class attribute.
- Discovers loaded modules via sys.modules (filtered to project modules).
- Stdlib only. No I/O. No LLM calls.
"""

from __future__ import annotations

import logging
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from runtime.introspection.subsystem_interface import (
    IntrospectableSubsystem,
    SubsystemStatus,
    HealthStatus,
    SubsystemHealth,
)
from runtime.introspection.subsystem_registry import SubsystemRegistry
from runtime.introspection.runtime_snapshot import (
    AggregatedHealth,
    RuntimeSnapshot,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Brain / memory name heuristics
# ---------------------------------------------------------------------------

_BRAIN_KEYWORDS = frozenset({
    "brain", "llm", "model", "inference", "language_model",
    "cloud_brain", "local_brain", "adaptive_brain",
})
_MEMORY_KEYWORDS = frozenset({
    "memory", "working_memory", "long_term", "storage", "index",
    "warehouse", "context",
})


def _is_brain_name(name: str) -> bool:
    lower = name.lower()
    return any(kw in lower for kw in _BRAIN_KEYWORDS)


def _is_memory_name(name: str) -> bool:
    lower = name.lower()
    return any(kw in lower for kw in _MEMORY_KEYWORDS)


# ---------------------------------------------------------------------------
# Builder configuration
# ---------------------------------------------------------------------------

class SnapshotBuilderConfig:
    """
    Configuration for the SnapshotBuilder.

    Attributes
    ----------
    identity_name : str
        The AG identity name to embed in every snapshot.
    identity_version : str
        The AG version string.
    module_prefix_filter : str
        Only modules whose names start with this prefix are recorded in
        loaded_modules (avoids listing the entire Python stdlib).
        Set to "" to disable filtering (record all modules).
    configuration_summary : Dict[str, Any]
        Static key-value pairs to include in every snapshot's
        'configuration' field.
    """

    def __init__(
        self,
        identity_name: str = "AG",
        identity_version: str = "0.0.0",
        module_prefix_filter: str = "",
        configuration_summary: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.identity_name        = identity_name
        self.identity_version     = identity_version
        self.module_prefix_filter = module_prefix_filter
        self.configuration_summary: Dict[str, Any] = configuration_summary or {}


# ---------------------------------------------------------------------------
# Snapshot Builder
# ---------------------------------------------------------------------------

class SnapshotBuilder:
    """
    Builds an immutable RuntimeSnapshot from a SubsystemRegistry.

    Usage
    -----
    ::

        registry = SubsystemRegistry()
        registry.register("cloud_brain", CloudBrainAdapter())
        registry.register("provider_registry", ProviderAdapter())

        config  = SnapshotBuilderConfig(identity_name="AG", identity_version="2.0.0")
        builder = SnapshotBuilder(config=config)
        snapshot = builder.build(registry)
    """

    def __init__(self, config: Optional[SnapshotBuilderConfig] = None) -> None:
        self._config = config or SnapshotBuilderConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self, registry: SubsystemRegistry) -> RuntimeSnapshot:
        """
        Collect data from all registered subsystems and build a snapshot.

        This method never raises.  If a subsystem method throws, the error
        is captured and included in diagnostics.
        """
        snapshot_id = uuid.uuid4().hex
        taken_at    = datetime.now(timezone.utc).isoformat()

        connected:    List[str] = []
        disconnected: List[str] = []
        brains:       Dict[str, str] = {}
        memory:       Dict[str, str] = {}
        all_caps:     Set[str] = set()
        all_limits:   Set[str] = set()
        all_issues:   List[str] = []
        diagnostics:  Dict[str, Any] = {}

        health_counts = {
            HealthStatus.HEALTHY:  0,
            HealthStatus.WARNING:  0,
            HealthStatus.CRITICAL: 0,
            HealthStatus.UNKNOWN:  0,
        }

        for name, subsystem in registry.items():
            sub_diag: Dict[str, Any] = {}

            # --- status() ---
            try:
                status = subsystem.status()
            except Exception as exc:
                logger.warning("SnapshotBuilder: %s.status() raised: %s", name, exc)
                status = SubsystemStatus.UNKNOWN
                sub_diag["status_error"] = str(exc)

            status_val = status.value if isinstance(status, SubsystemStatus) else str(status)
            sub_diag["status"] = status_val

            if status in (SubsystemStatus.ONLINE,):
                connected.append(name)
            else:
                disconnected.append(name)

            # --- health() ---
            try:
                health = subsystem.health()
            except Exception as exc:
                logger.warning("SnapshotBuilder: %s.health() raised: %s", name, exc)
                health = SubsystemHealth(
                    status=HealthStatus.CRITICAL,
                    issues=[f"{name}.health() raised: {exc}"],
                )

            h_status = health.status if isinstance(health.status, HealthStatus) else HealthStatus.UNKNOWN
            health_counts[h_status] = health_counts.get(h_status, 0) + 1
            all_issues.extend(health.issues)
            sub_diag["health"] = health.to_dict()

            # --- capabilities() ---
            try:
                caps = subsystem.capabilities() or []
            except Exception as exc:
                logger.warning("SnapshotBuilder: %s.capabilities() raised: %s", name, exc)
                caps = []
                sub_diag["capabilities_error"] = str(exc)
            all_caps.update(caps)
            sub_diag["capabilities"] = list(caps)

            # --- limitations() ---
            try:
                limits = subsystem.limitations() or []
            except Exception as exc:
                logger.warning("SnapshotBuilder: %s.limitations() raised: %s", name, exc)
                limits = []
                sub_diag["limitations_error"] = str(exc)
            all_limits.update(limits)
            sub_diag["limitations"] = list(limits)

            # --- diagnostics() ---
            try:
                sub_diagnostics = subsystem.diagnostics() or {}
            except Exception as exc:
                logger.warning("SnapshotBuilder: %s.diagnostics() raised: %s", name, exc)
                sub_diagnostics = {"error": str(exc)}
            sub_diag.update(sub_diagnostics)

            diagnostics[name] = sub_diag

            # Classify as brain or memory subsystem
            if _is_brain_name(name):
                brains[name] = status_val
            if _is_memory_name(name):
                memory[name] = status_val

        # Aggregate health
        runtime_health = self._aggregate_health(health_counts, all_issues)

        # Loaded modules
        loaded_modules = self._discover_modules()

        return RuntimeSnapshot(
            snapshot_id=snapshot_id,
            taken_at=taken_at,
            identity_name=self._config.identity_name,
            identity_version=self._config.identity_version,
            loaded_modules=tuple(sorted(loaded_modules)),
            connected_subsystems=tuple(connected),
            disconnected_subsystems=tuple(disconnected),
            brains=brains,
            memory=memory,
            runtime_health=runtime_health,
            capabilities=tuple(sorted(all_caps)),
            limitations=tuple(sorted(all_limits)),
            configuration=dict(self._config.configuration_summary),
            diagnostics=diagnostics,
            subsystem_count=len(registry),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _aggregate_health(
        self,
        counts: Dict[HealthStatus, int],
        issues: List[str],
    ) -> AggregatedHealth:
        """Determine overall health from per-subsystem health counts."""
        healthy  = counts.get(HealthStatus.HEALTHY, 0)
        warning  = counts.get(HealthStatus.WARNING, 0)
        critical = counts.get(HealthStatus.CRITICAL, 0)
        unknown  = counts.get(HealthStatus.UNKNOWN, 0)
        total    = healthy + warning + critical + unknown

        if total == 0:
            overall = "unknown"
        elif critical > 0:
            overall = "critical"
        elif warning > 0:
            overall = "warning"
        elif unknown == total:
            overall = "unknown"
        else:
            overall = "healthy"

        return AggregatedHealth(
            overall=overall,
            healthy_count=healthy,
            warning_count=warning,
            critical_count=critical,
            unknown_count=unknown,
            total_subsystems=total,
            issues=tuple(issues),
        )

    def _discover_modules(self) -> List[str]:
        """
        Return the list of currently loaded Python modules.

        When module_prefix_filter is non-empty, only modules whose
        __name__ starts with that prefix are included.
        """
        prefix = self._config.module_prefix_filter
        if prefix:
            return [
                name for name in sys.modules
                if name.startswith(prefix) and sys.modules[name] is not None
            ]
        return [
            name for name in sys.modules
            if sys.modules[name] is not None
        ]
