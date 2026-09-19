"""
directory_control/path_security.py
====================================
Path resolution and workspace containment validation for AB Directory Control.

All filesystem operations must pass through resolve_workspace_path() before
acting. The workspace boundary is enforced by resolving both the workspace
root and the requested path to their real (canonical) forms, then verifying
containment.

Rules
-----
- The requested path may be relative (resolved against the workspace root) or
  absolute.
- Symlinks are resolved so that link targets pointing outside the workspace
  are rejected.
- The resolved target must remain strictly inside the authorized workspace.
- Raises DirectoryControlError (a subclass of PermissionError) on any
  containment violation.

No filesystem mutations occur here. Validation only.
"""

from __future__ import annotations

from pathlib import Path


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class DirectoryControlError(Exception):
    """Base exception for Directory Control failures."""


class WorkspaceViolationError(DirectoryControlError, PermissionError):
    """
    Raised when a requested path resolves to a location outside the
    authorized workspace.

    User-facing message is always clean — no internal path details are
    included unless the workspace itself is safe to show.
    """

    def __init__(self, message: str = "That path is outside the active workspace.") -> None:
        super().__init__(message)


class NoActiveWorkspaceError(DirectoryControlError):
    """Raised when a workspace-dependent operation is attempted but no workspace is set."""

    def __init__(self) -> None:
        super().__init__("No active workspace is set. Use 'work in <path>' to set one.")


class WorkspaceNotFoundError(DirectoryControlError):
    """Raised when the workspace directory does not exist or is not accessible."""

    def __init__(self, path: str) -> None:
        super().__init__(f"Workspace directory does not exist or is not accessible: {path}")


# ---------------------------------------------------------------------------
# Core validation
# ---------------------------------------------------------------------------

def resolve_workspace_path(workspace: str | Path, requested_path: str | Path) -> Path:
    """
    Resolve ``requested_path`` relative to ``workspace`` and verify it stays
    inside the workspace boundary.

    Parameters
    ----------
    workspace : str or Path
        The authorized workspace root (must exist and be a directory).
    requested_path : str or Path
        The user-supplied path. May be relative or absolute.

    Returns
    -------
    Path
        The fully resolved, validated absolute path.

    Raises
    ------
    WorkspaceViolationError
        If the resolved target is outside the workspace.
    NoActiveWorkspaceError
        If workspace is None or empty.
    WorkspaceNotFoundError
        If the workspace directory does not exist.
    """
    if workspace is None or str(workspace).strip() == "":
        raise NoActiveWorkspaceError()

    ws = Path(workspace).resolve()

    if not ws.exists() or not ws.is_dir():
        raise WorkspaceNotFoundError(str(workspace))

    target = Path(requested_path)

    # Relative paths are resolved against the workspace root
    if not target.is_absolute():
        target = ws / target

    # Resolve fully — follows symlinks and normalises .. components
    target = target.resolve()

    # Containment check: target must be the workspace or a descendant
    try:
        target.relative_to(ws)
    except ValueError:
        raise WorkspaceViolationError(
            "That path is outside the active workspace."
        )

    return target


def validate_workspace(path: str | Path) -> Path:
    """
    Validate that a proposed workspace root exists and is a directory.

    Returns the resolved Path if valid.

    Raises
    ------
    WorkspaceNotFoundError
        If the path does not exist or is not a directory.
    """
    p = Path(path).resolve()

    if not p.exists():
        raise WorkspaceNotFoundError(str(path))

    if not p.is_dir():
        raise WorkspaceNotFoundError(f"Path is not a directory: {path}")

    return p


def is_within_workspace(workspace: str | Path, target: str | Path) -> bool:
    """
    Return True if ``target`` (after resolving) is inside ``workspace``.

    Does not raise — returns False for any error condition, including a
    missing workspace.
    """
    try:
        ws = Path(workspace).resolve()
        tgt = Path(target).resolve()
        tgt.relative_to(ws)
        return True
    except (ValueError, TypeError, OSError):
        return False
