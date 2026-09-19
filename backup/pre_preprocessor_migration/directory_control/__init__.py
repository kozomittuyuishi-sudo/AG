"""
directory_control/
==================
AB Directory Control subsystem.

Provides unified workspace management and file/directory operations for AB.

Public API
----------
DirectoryControl    Main controller. Set a workspace, then read/write/move/copy/rename.
path_security       resolve_workspace_path, validate_workspace, is_within_workspace
Exceptions          DirectoryControlError, WorkspaceViolationError,
                    NoActiveWorkspaceError, WorkspaceNotFoundError,
                    OperationError, FileNotFoundInWorkspace, NotAFileError,
                    VerificationError
"""

from directory_control.directory_control import (
    DirectoryControl,
    DirectoryControlError,
    OperationError,
    FileNotFoundInWorkspace,
    NotAFileError,
    VerificationError,
)
from directory_control.path_security import (
    resolve_workspace_path,
    validate_workspace,
    is_within_workspace,
    WorkspaceViolationError,
    NoActiveWorkspaceError,
    WorkspaceNotFoundError,
)

__all__ = [
    "DirectoryControl",
    "DirectoryControlError",
    "OperationError",
    "FileNotFoundInWorkspace",
    "NotAFileError",
    "VerificationError",
    "resolve_workspace_path",
    "validate_workspace",
    "is_within_workspace",
    "WorkspaceViolationError",
    "NoActiveWorkspaceError",
    "WorkspaceNotFoundError",
]
