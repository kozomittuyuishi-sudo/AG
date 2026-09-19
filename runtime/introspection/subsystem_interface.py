"""
introspection/subsystem_interface.py
======================================
Common Subsystem Interface

Every major AG subsystem that wishes to be inspectable at runtime must
implement ``IntrospectableSubsystem``.  The interface defines five methods:

    status()         — Current operational status.
    health()         — Health report with any active issues.
    capabilities()   — What this subsystem can do.
    limitations()    — Known constraints, missing deps, disabled features.
    diagnostics()    — Detailed runtime diagnostic data (arbitrary dict).

Design principles
-----------------
- All methods are safe to call at any time, including during errors.
- Methods never raise — return a degraded result instead.
- Stdlib only. No I/O. No LLM calls.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Status and health enumerations
# ---------------------------------------------------------------------------

class SubsystemStatus(str, Enum):
    """Coarse operational status for a subsystem."""
    ONLINE      = "online"       # Running normally
    DEGRADED    = "degraded"     # Running but with reduced capability
    OFFLINE     = "offline"      # Not running / unavailable
    UNKNOWN     = "unknown"      # Status cannot be determined


class HealthStatus(str, Enum):
    """Health classification."""
    HEALTHY   = "healthy"
    WARNING   = "warning"
    CRITICAL  = "critical"
    UNKNOWN   = "unknown"


# ---------------------------------------------------------------------------
# Health report
# ---------------------------------------------------------------------------

@dataclass
class SubsystemHealth:
    """
    Health report returned by IntrospectableSubsystem.health().

    Attributes
    ----------
    status : HealthStatus
        Overall health classification.
    issues : List[str]
        Human-readable descriptions of any active issues.
    checks_passed : int
        Number of internal health checks that passed.
    checks_total : int
        Total number of internal health checks performed.
    notes : List[str]
        Informational notes (non-issue observations).
    """
    status: HealthStatus
    issues: List[str] = field(default_factory=list)
    checks_passed: int = 0
    checks_total: int  = 0
    notes: List[str]   = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "issues": list(self.issues),
            "checks_passed": self.checks_passed,
            "checks_total": self.checks_total,
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class IntrospectableSubsystem(ABC):
    """
    Abstract base class for all AG subsystems that expose runtime state.

    Every method must be safe to call at any time.  Implementations
    should catch their own exceptions and return degraded results rather
    than propagating errors to the introspection layer.

    The introspection engine calls all five methods and assembles the
    results into a RuntimeSnapshot.  No ordering dependency exists
    between methods.
    """

    # ------------------------------------------------------------------
    # Required interface methods
    # ------------------------------------------------------------------

    @abstractmethod
    def status(self) -> SubsystemStatus:
        """
        Return the current operational status.

        This method must never raise.  If the subsystem cannot determine
        its status, return SubsystemStatus.UNKNOWN.
        """
        ...

    @abstractmethod
    def health(self) -> SubsystemHealth:
        """
        Return a health report describing any active issues.

        This method must never raise.  On internal error, return a
        SubsystemHealth with status=CRITICAL and the error in issues.
        """
        ...

    @abstractmethod
    def capabilities(self) -> List[str]:
        """
        Return a list of capability descriptions.

        Each entry is a human-readable string such as:
            "Token budget estimation"
            "Provider capability lookup"
            "Streaming responses"

        This method must never raise.  Return an empty list on error.
        """
        ...

    @abstractmethod
    def limitations(self) -> List[str]:
        """
        Return a list of known limitations or constraints.

        Each entry is a human-readable string such as:
            "No persistent storage"
            "Requires network access for cloud providers"
            "Max 4096 output tokens per request"

        This method must never raise.  Return an empty list on error.
        """
        ...

    @abstractmethod
    def diagnostics(self) -> Dict[str, Any]:
        """
        Return a dict of detailed runtime diagnostic data.

        Contents are subsystem-specific and may include:
            - Configuration summary
            - Request/response counts
            - Internal state snapshots
            - Component version strings

        This method must never raise.  Return an empty dict on error.
        """
        ...

    # ------------------------------------------------------------------
    # Convenience method (non-abstract — has a default implementation)
    # ------------------------------------------------------------------

    def subsystem_name(self) -> str:
        """
        Return a human-readable name for this subsystem.

        Defaults to the class name.  Override to provide a stable name
        that does not change if the class is renamed.
        """
        return self.__class__.__name__


# ---------------------------------------------------------------------------
# Null / stub implementation — useful for tests and placeholders
# ---------------------------------------------------------------------------

class NullSubsystem(IntrospectableSubsystem):
    """
    A no-op subsystem that reports OFFLINE with no capabilities.

    Useful as a placeholder when a real subsystem is not available.
    """

    def __init__(self, name: str = "NullSubsystem") -> None:
        self._name = name

    def subsystem_name(self) -> str:
        return self._name

    def status(self) -> SubsystemStatus:
        return SubsystemStatus.OFFLINE

    def health(self) -> SubsystemHealth:
        return SubsystemHealth(
            status=HealthStatus.UNKNOWN,
            notes=["Null subsystem — no health data available."],
        )

    def capabilities(self) -> List[str]:
        return []

    def limitations(self) -> List[str]:
        return ["Null subsystem — not operational."]

    def diagnostics(self) -> Dict[str, Any]:
        return {"subsystem": self._name, "operational": False}
