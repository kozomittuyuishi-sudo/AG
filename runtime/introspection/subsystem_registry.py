"""
introspection/subsystem_registry.py
======================================
Subsystem Registry

Maintains a runtime map of name → IntrospectableSubsystem.
Any code can call ``registry.register(name, subsystem)`` to make a
subsystem discoverable by the IntrospectionEngine.

Design
------
- Discovery is entirely dynamic — no hardcoded names, no manifests.
- Registration order is preserved (Python 3.7+ dict insertion order).
- The registry does not own subsystems; it merely references them.
- Stdlib only. No I/O. No LLM calls.
"""

from __future__ import annotations

import logging
from typing import Dict, Iterator, List, Optional, Tuple

from runtime.introspection.subsystem_interface import IntrospectableSubsystem

logger = logging.getLogger(__name__)


class SubsystemRegistry:
    """
    Runtime registry of introspectable subsystems.

    Subsystems are stored by name.  If a name is registered twice,
    the second registration replaces the first (warn, not raise).

    Usage
    -----
    ::

        registry = SubsystemRegistry()
        registry.register("token_estimator", TokenEstimatorAdapter())
        registry.register("provider_registry", ProviderRegistryAdapter())

        for name, subsystem in registry.items():
            print(name, subsystem.status())
    """

    def __init__(self) -> None:
        self._subsystems: Dict[str, IntrospectableSubsystem] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, name: str, subsystem: IntrospectableSubsystem) -> None:
        """
        Register a subsystem under ``name``.

        Parameters
        ----------
        name : str
            Unique key for this subsystem.  Use a stable, human-readable
            identifier (e.g. "token_estimator", "provider_registry").
        subsystem : IntrospectableSubsystem
            The subsystem instance to register.

        Raises
        ------
        TypeError
            If ``subsystem`` is not an IntrospectableSubsystem.
        ValueError
            If ``name`` is empty.
        """
        if not name or not name.strip():
            raise ValueError("Subsystem name must be a non-empty string.")
        if not isinstance(subsystem, IntrospectableSubsystem):
            raise TypeError(
                f"Expected IntrospectableSubsystem, got {type(subsystem).__name__}."
            )
        if name in self._subsystems:
            logger.warning(
                "SubsystemRegistry: replacing existing registration for '%s'.", name
            )
        self._subsystems[name] = subsystem
        logger.debug("SubsystemRegistry: registered '%s'.", name)

    def unregister(self, name: str) -> bool:
        """
        Remove the subsystem registered under ``name``.

        Returns True if the name was registered, False otherwise.
        """
        existed = name in self._subsystems
        self._subsystems.pop(name, None)
        if existed:
            logger.debug("SubsystemRegistry: unregistered '%s'.", name)
        return existed

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, name: str) -> Optional[IntrospectableSubsystem]:
        """Return the subsystem registered under ``name``, or None."""
        return self._subsystems.get(name)

    def require(self, name: str) -> IntrospectableSubsystem:
        """
        Return the subsystem registered under ``name``.

        Raises
        ------
        KeyError
            If the name is not registered.
        """
        subsystem = self._subsystems.get(name)
        if subsystem is None:
            raise KeyError(
                f"No subsystem registered under '{name}'. "
                f"Known names: {self.names()}"
            )
        return subsystem

    # ------------------------------------------------------------------
    # Iteration / inspection
    # ------------------------------------------------------------------

    def names(self) -> List[str]:
        """Return all registered names in insertion order."""
        return list(self._subsystems.keys())

    def items(self) -> Iterator[Tuple[str, IntrospectableSubsystem]]:
        """Iterate over (name, subsystem) pairs in insertion order."""
        return iter(self._subsystems.items())

    def all_subsystems(self) -> List[IntrospectableSubsystem]:
        """Return all registered subsystems in insertion order."""
        return list(self._subsystems.values())

    def is_empty(self) -> bool:
        """Return True when no subsystems are registered."""
        return len(self._subsystems) == 0

    def clear(self) -> None:
        """Remove all registered subsystems."""
        self._subsystems.clear()
        logger.debug("SubsystemRegistry: cleared all registrations.")

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._subsystems)

    def __contains__(self, name: str) -> bool:
        return name in self._subsystems

    def __repr__(self) -> str:
        return (
            f"SubsystemRegistry({len(self._subsystems)} subsystems: "
            f"{self.names()})"
        )
