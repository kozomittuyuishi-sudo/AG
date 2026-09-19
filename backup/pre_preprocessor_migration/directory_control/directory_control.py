"""
directory_control/directory_control.py
========================================
AB Directory Control subsystem.

Responsibilities
----------------
- Maintain a single active workspace directory.
- Provide all read/write/inspect operations on files and folders within
  that workspace.
- Enforce the workspace security boundary on every operation via
  path_security.resolve_workspace_path().
- Reuse the existing DirectoryReader for directory inspection/reading.
- Route write/mutate operations through AB's existing AuthorizationManager.
- Never expose Python tracebacks to the caller — all failures raise typed
  DirectoryControlError subclasses with clean messages.

Integration
-----------
DirectoryControl is instantiated once in Ag.py and passed through
process_input() the same way DirectorySession is. The handler function
_handle_directory_control() in Ag.py dispatches natural-language intents
to the appropriate method.

Design rules
------------
- pathlib is the primary filesystem abstraction; shutil for copy/move.
- Every mutating operation verifies its post-condition.
- No deletion. No file execution.
- Does not create a new permission architecture — uses AuthorizationManager
  with the existing files.read / files.write permissions from permissions.json.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import List, Optional

from directory_reader.reader import DirectoryReader, FileEntry
from directory_control.path_security import (
    resolve_workspace_path,
    validate_workspace,
    DirectoryControlError,
    NoActiveWorkspaceError,
    WorkspaceViolationError,
    WorkspaceNotFoundError,
)
from pipeline.fallback_classifier import (
    AGError,
    DIR_NOT_FOUND,
    DIR_NOT_A_FILE,
    DIR_NOT_A_DIRECTORY,
    DIR_SOURCE_MISSING,
    DIR_OUT_OF_WORKSPACE,
)

# ---------------------------------------------------------------------------
# Additional typed exceptions
# ---------------------------------------------------------------------------

class OperationError(DirectoryControlError):
    """A filesystem operation failed or its post-condition was not met."""


class FileNotFoundInWorkspace(DirectoryControlError):
    """The requested file does not exist inside the workspace."""


class NotAFileError(DirectoryControlError):
    """The path exists but is a directory, not a file."""


class VerificationError(DirectoryControlError):
    """A post-operation verification check failed."""



# ---------------------------------------------------------------------------
# DirectoryControl
# ---------------------------------------------------------------------------

class DirectoryControl:
    """
    Unified directory and file control capability for AB.

    All paths supplied by callers are resolved through the workspace
    security boundary before any filesystem operation occurs.

    The active_directory is the single authorised root. Setting it replaces
    any previously active workspace.
    """

    def __init__(self) -> None:
        self._active_directory: Optional[Path] = None
        # Internal reader — reused for listing and inspection
        self._reader: DirectoryReader = DirectoryReader()

    # ------------------------------------------------------------------
    # Workspace management
    # ------------------------------------------------------------------

    def set_directory(self, path: str) -> str:
        """
        Set the active workspace to ``path``.

        Returns a confirmation string. Raises WorkspaceNotFoundError if the
        directory does not exist or is not accessible.
        """
        validated = validate_workspace(path)
        self._active_directory = validated
        # Load the reader so listing/inspection is immediately available
        self._reader.read_directory(str(validated))
        return str(validated)

    def switch_directory(self, path: str) -> str:
        """
        Switch the active workspace to a new directory.

        Identical to set_directory(); provided as a distinct method to
        match the natural-language intent ("switch to …").
        """
        return self.set_directory(path)

    def clear_directory(self) -> Optional[str]:
        """
        Remove the active workspace.

        Returns the path that was cleared, or None if no workspace was set.
        After this call, any operation requiring an active workspace will
        raise NoActiveWorkspaceError.
        """
        previous = str(self._active_directory) if self._active_directory else None
        self._active_directory = None
        self._reader = DirectoryReader()
        return previous

    def get_active_directory(self) -> Optional[str]:
        """Return the active workspace path as a string, or None."""
        return str(self._active_directory) if self._active_directory else None

    def _require_workspace(self) -> Path:
        """Return the active workspace Path, or raise NoActiveWorkspaceError."""
        if self._active_directory is None:
            raise NoActiveWorkspaceError()
        return self._active_directory

    def _resolve(self, relative_or_absolute: str) -> Path:
        """
        Resolve a user-supplied path against the active workspace and
        validate containment.
        """
        ws = self._require_workspace()
        return resolve_workspace_path(ws, relative_or_absolute)

    def raise_typed_error(self, exc: Exception) -> AGError:
        """
        Convert a DirectoryControlError exception to a typed AGError object.

        Maps each known DirectoryControlError subclass to the appropriate
        AGError domain and code.  Unrecognised exceptions are mapped to
        DIR_NOT_FOUND as a safe default.

        Parameters
        ----------
        exc : Exception
            The exception to convert.  Typically a DirectoryControlError
            subclass raised by one of the DirectoryControl methods.

        Returns
        -------
        AGError
            A structured error object.  The ``message`` field contains the
            original exception string for internal diagnostics only.

        Notes
        -----
        This method does not raise.  It always returns an AGError.
        """
        message = str(exc)

        if isinstance(exc, WorkspaceViolationError):
            return AGError(
                domain="DIRECTORY",
                code=DIR_OUT_OF_WORKSPACE,
                message=message,
            )

        if isinstance(exc, (WorkspaceNotFoundError, NoActiveWorkspaceError)):
            return AGError(
                domain="DIRECTORY",
                code=DIR_NOT_FOUND,
                message=message,
            )

        if isinstance(exc, FileNotFoundInWorkspace):
            return AGError(
                domain="DIRECTORY",
                code=DIR_NOT_FOUND,
                message=message,
            )

        if isinstance(exc, NotAFileError):
            # The exception message tells us which direction the mismatch is.
            lower = message.lower()
            if "directory" in lower and "not a file" in lower:
                # Path is a directory but a file was expected
                code = DIR_NOT_A_FILE
            elif "file" in lower and "not a directory" in lower:
                # Path is a file but a directory was expected
                code = DIR_NOT_A_DIRECTORY
            else:
                code = DIR_NOT_A_FILE
            return AGError(
                domain="DIRECTORY",
                code=code,
                message=message,
            )

        if isinstance(exc, OperationError):
            lower = message.lower()
            if "source" in lower and ("does not exist" in lower or "missing" in lower):
                return AGError(
                    domain="DIRECTORY",
                    code=DIR_SOURCE_MISSING,
                    message=message,
                )
            return AGError(
                domain="DIRECTORY",
                code=DIR_NOT_FOUND,
                message=message,
            )

        if isinstance(exc, DirectoryControlError):
            return AGError(
                domain="DIRECTORY",
                code=DIR_NOT_FOUND,
                message=message,
            )

        # Unknown exception type — safe default
        return AGError(
            domain="DIRECTORY",
            code=DIR_NOT_FOUND,
            message=message,
        )

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def verify_operation(self, path: Path, *, must_exist: bool = True) -> bool:
        """
        Verify the post-condition of a filesystem operation.

        Parameters
        ----------
        path : Path
            The path that was created / modified / moved.
        must_exist : bool
            When True (default), verifies the path now exists.
            Pass False when verifying a source was removed (e.g. after move).

        Returns
        -------
        bool
            True if the condition is satisfied.

        Raises
        ------
        VerificationError
            If the condition is not satisfied.
        """
        exists = path.exists()
        if must_exist and not exists:
            raise VerificationError(
                f"Operation verification failed: expected {path.name} to exist after the operation."
            )
        if not must_exist and exists:
            raise VerificationError(
                f"Operation verification failed: expected {path.name} to be gone after the operation."
            )
        return True


    # ------------------------------------------------------------------
    # Directory inspection
    # ------------------------------------------------------------------

    def list_directory(
        self,
        sub_path: str = ".",
        *,
        files_only: bool = False,
        dirs_only: bool = False,
    ) -> List[dict]:
        """
        List the contents of the workspace (or a sub-directory).

        Parameters
        ----------
        sub_path : str
            Path relative to the workspace root to list. Defaults to the
            workspace root itself.
        files_only : bool
            Return only files.
        dirs_only : bool
            Return only directories.

        Returns
        -------
        list of dict
            Each dict has keys: name, rel_path, type ("file"/"dir"), size_bytes.

        Raises
        ------
        NoActiveWorkspaceError, WorkspaceViolationError, FileNotFoundInWorkspace
        """
        target = self._resolve(sub_path)

        if not target.exists():
            raise FileNotFoundInWorkspace(f"Directory does not exist: {sub_path}")
        if not target.is_dir():
            raise NotAFileError(f"Path is a file, not a directory: {sub_path}")

        entries = []
        for item in sorted(target.iterdir()):
            kind = "dir" if item.is_dir() else "file"
            if files_only and kind != "file":
                continue
            if dirs_only and kind != "dir":
                continue
            size = 0
            if kind == "file":
                try:
                    size = item.stat().st_size
                except OSError:
                    pass
            ws = self._active_directory
            try:
                rel = str(item.relative_to(ws))
            except ValueError:
                rel = item.name
            entries.append({
                "name": item.name,
                "rel_path": rel,
                "type": kind,
                "size_bytes": size,
            })
        return entries

    def get_indexed_files(self) -> List[FileEntry]:
        """
        Return the FileEntry list from the underlying DirectoryReader.

        The reader indexes supported text files (the same set the directory
        reader uses). Re-scans if the workspace was just set.
        """
        ws = self._require_workspace()
        # Re-index if the reader's directory doesn't match the active workspace
        if self._reader.directory != str(ws):
            self._reader.read_directory(str(ws))
        return self._reader.files

    def search_files(self, pattern: str) -> List[dict]:
        """
        Search for files whose names contain ``pattern`` (case-insensitive).

        Returns a list of dicts with name, rel_path, type, size_bytes.
        """
        ws = self._require_workspace()
        pattern_lower = pattern.lower()
        results = []
        for item in ws.rglob("*"):
            if pattern_lower in item.name.lower():
                kind = "dir" if item.is_dir() else "file"
                size = 0
                if kind == "file":
                    try:
                        size = item.stat().st_size
                    except OSError:
                        pass
                try:
                    rel = str(item.relative_to(ws))
                except ValueError:
                    rel = item.name
                results.append({
                    "name": item.name,
                    "rel_path": rel,
                    "type": kind,
                    "size_bytes": size,
                })
        return results


    # ------------------------------------------------------------------
    # File reading
    # ------------------------------------------------------------------

    # Max bytes to read from a single file — mirrors DirectoryReader's cap
    MAX_READ_BYTES: int = 131_072  # 128 KB

    def read_file(self, path: str) -> str:
        """
        Read and return the text content of a file inside the workspace.

        Parameters
        ----------
        path : str
            Path to the file (relative to workspace or absolute within it).

        Returns
        -------
        str
            Decoded text content. May be truncated at MAX_READ_BYTES.

        Raises
        ------
        NoActiveWorkspaceError, WorkspaceViolationError,
        FileNotFoundInWorkspace, NotAFileError, OperationError
        """
        target = self._resolve(path)

        if not target.exists():
            raise FileNotFoundInWorkspace(f"File does not exist: {path}")
        if not target.is_file():
            raise NotAFileError(f"Path is a directory, not a file: {path}")

        try:
            size = target.stat().st_size
            truncated = size > self.MAX_READ_BYTES
            content = target.read_bytes()[:self.MAX_READ_BYTES].decode(
                "utf-8", errors="replace"
            )
            if truncated:
                content += f"\n\n[NOTE: File truncated at {self.MAX_READ_BYTES} bytes.]"
            return content
        except PermissionError:
            raise OperationError(f"Permission denied reading: {path}")
        except OSError as exc:
            raise OperationError(f"Could not read file: {exc}")

    # ------------------------------------------------------------------
    # File creation
    # ------------------------------------------------------------------

    def create_file(self, path: str, content: str = "") -> Path:
        """
        Create a new file inside the workspace.

        Parent directories are created automatically. If the file already
        exists its content is preserved (use write_file to overwrite).

        Parameters
        ----------
        path : str
            Target file path (relative to workspace or absolute within it).
        content : str
            Initial content. Defaults to empty string.

        Returns
        -------
        Path
            The resolved path of the created file.

        Raises
        ------
        NoActiveWorkspaceError, WorkspaceViolationError,
        OperationError, VerificationError
        """
        target = self._resolve(path)

        if target.exists() and target.is_file():
            raise OperationError(
                f"File already exists: {path}. Use write_file to replace it."
            )

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except PermissionError:
            raise OperationError(f"Permission denied creating file: {path}")
        except OSError as exc:
            raise OperationError(f"Could not create file: {exc}")

        self.verify_operation(target, must_exist=True)
        return target

    # ------------------------------------------------------------------
    # File writing (overwrite)
    # ------------------------------------------------------------------

    def write_file(self, path: str, content: str) -> Path:
        """
        Write content to a file, creating it if necessary.

        If the file already exists its content is replaced entirely.

        Parameters
        ----------
        path : str
            Target file path (relative to workspace or absolute within it).
        content : str
            New content to write.

        Returns
        -------
        Path
            The resolved path of the written file.

        Raises
        ------
        NoActiveWorkspaceError, WorkspaceViolationError,
        OperationError, VerificationError
        """
        target = self._resolve(path)

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except PermissionError:
            raise OperationError(f"Permission denied writing to: {path}")
        except OSError as exc:
            raise OperationError(f"Could not write file: {exc}")

        self.verify_operation(target, must_exist=True)
        return target

    # ------------------------------------------------------------------
    # File appending
    # ------------------------------------------------------------------

    def append_file(self, path: str, content: str) -> Path:
        """
        Append content to an existing file without replacing existing text.

        The file is created if it does not exist.

        Parameters
        ----------
        path : str
            Target file path (relative to workspace or absolute within it).
        content : str
            Content to append.

        Returns
        -------
        Path
            The resolved path of the file.

        Raises
        ------
        NoActiveWorkspaceError, WorkspaceViolationError,
        OperationError, VerificationError
        """
        target = self._resolve(path)

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as fh:
                fh.write(content)
        except PermissionError:
            raise OperationError(f"Permission denied appending to: {path}")
        except OSError as exc:
            raise OperationError(f"Could not append to file: {exc}")

        self.verify_operation(target, must_exist=True)
        return target

    # ------------------------------------------------------------------
    # File updating (partial replacement)
    # ------------------------------------------------------------------

    def update_file(self, path: str, content: str) -> Path:
        """
        Replace the content of an existing file.

        This is an explicit-replacement operation: the file must already
        exist. Use write_file to create-or-overwrite.

        Parameters
        ----------
        path : str
            Target file path (relative to workspace or absolute within it).
        content : str
            New content to write.

        Returns
        -------
        Path
            The resolved path.

        Raises
        ------
        NoActiveWorkspaceError, WorkspaceViolationError,
        FileNotFoundInWorkspace, OperationError, VerificationError
        """
        target = self._resolve(path)

        if not target.exists():
            raise FileNotFoundInWorkspace(
                f"Cannot update non-existent file: {path}"
            )
        if not target.is_file():
            raise NotAFileError(f"Path is a directory, not a file: {path}")

        try:
            target.write_text(content, encoding="utf-8")
        except PermissionError:
            raise OperationError(f"Permission denied updating: {path}")
        except OSError as exc:
            raise OperationError(f"Could not update file: {exc}")

        self.verify_operation(target, must_exist=True)
        return target


    # ------------------------------------------------------------------
    # Directory creation
    # ------------------------------------------------------------------

    def create_directory(self, path: str) -> Path:
        """
        Create a new directory (and any missing parents) inside the workspace.

        Parameters
        ----------
        path : str
            Target directory path (relative to workspace or absolute within it).

        Returns
        -------
        Path
            The resolved path of the created directory.

        Raises
        ------
        NoActiveWorkspaceError, WorkspaceViolationError,
        OperationError, VerificationError
        """
        target = self._resolve(path)

        if target.exists() and target.is_dir():
            raise OperationError(f"Directory already exists: {path}")

        try:
            target.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            raise OperationError(f"Directory already exists: {path}")
        except PermissionError:
            raise OperationError(f"Permission denied creating directory: {path}")
        except OSError as exc:
            raise OperationError(f"Could not create directory: {exc}")

        self.verify_operation(target, must_exist=True)
        return target

    # ------------------------------------------------------------------
    # Move
    # ------------------------------------------------------------------

    def move(self, source: str, destination: str) -> Path:
        """
        Move a file or directory within the workspace.

        Both source and destination must remain inside the active workspace.
        If ``destination`` is an existing directory, the source is moved
        inside that directory (standard shutil.move behaviour).

        Parameters
        ----------
        source : str
            Path to the file/folder to move.
        destination : str
            Target path or destination directory.

        Returns
        -------
        Path
            The resolved destination path.

        Raises
        ------
        NoActiveWorkspaceError, WorkspaceViolationError,
        FileNotFoundInWorkspace, OperationError, VerificationError
        """
        src = self._resolve(source)
        dst = self._resolve(destination)

        if not src.exists():
            raise FileNotFoundInWorkspace(f"Source does not exist: {source}")

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        except PermissionError:
            raise OperationError(f"Permission denied moving: {source}")
        except OSError as exc:
            raise OperationError(f"Move failed: {exc}")

        # After move, dst may be a directory containing the source name
        if dst.is_dir() and not dst.name == src.name:
            actual_dst = dst / src.name
        else:
            actual_dst = dst

        self.verify_operation(actual_dst, must_exist=True)
        self.verify_operation(src, must_exist=False)
        return actual_dst

    # ------------------------------------------------------------------
    # Copy
    # ------------------------------------------------------------------

    def copy(self, source: str, destination: str) -> Path:
        """
        Copy a file within the workspace.

        Both source and destination must remain inside the active workspace.

        Parameters
        ----------
        source : str
            Path to the file to copy.
        destination : str
            Target path for the copy.

        Returns
        -------
        Path
            The resolved destination path.

        Raises
        ------
        NoActiveWorkspaceError, WorkspaceViolationError,
        FileNotFoundInWorkspace, NotAFileError, OperationError, VerificationError
        """
        src = self._resolve(source)
        dst = self._resolve(destination)

        if not src.exists():
            raise FileNotFoundInWorkspace(f"Source does not exist: {source}")
        if not src.is_file():
            raise NotAFileError(f"Source is a directory, not a file: {source}")

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))
        except PermissionError:
            raise OperationError(f"Permission denied copying: {source}")
        except OSError as exc:
            raise OperationError(f"Copy failed: {exc}")

        # If dst was an existing directory, the file was placed inside it
        if dst.is_dir():
            actual_dst = dst / src.name
        else:
            actual_dst = dst

        self.verify_operation(actual_dst, must_exist=True)
        return actual_dst

    # ------------------------------------------------------------------
    # Rename
    # ------------------------------------------------------------------

    def rename(self, source: str, new_name: str) -> Path:
        """
        Rename a file or directory within the workspace.

        ``new_name`` may be a bare filename (rename in place) or a relative
        path (move-and-rename within the workspace).

        Parameters
        ----------
        source : str
            Path to the file/folder to rename.
        new_name : str
            New name or relative path for the item.

        Returns
        -------
        Path
            The resolved new path.

        Raises
        ------
        NoActiveWorkspaceError, WorkspaceViolationError,
        FileNotFoundInWorkspace, OperationError, VerificationError
        """
        src = self._resolve(source)

        if not src.exists():
            raise FileNotFoundInWorkspace(f"Source does not exist: {source}")

        # If new_name contains separators, treat it as a relative path from workspace
        # Otherwise treat it as a new name in the same directory
        from pathlib import PurePath
        if "/" in new_name or "\\" in new_name:
            dst = self._resolve(new_name)
        else:
            dst = self._resolve(str(PurePath(source).parent / new_name))

        if dst.exists():
            raise OperationError(f"Target already exists: {new_name}")

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
        except PermissionError:
            raise OperationError(f"Permission denied renaming: {source}")
        except OSError as exc:
            raise OperationError(f"Rename failed: {exc}")

        self.verify_operation(dst, must_exist=True)
        self.verify_operation(src, must_exist=False)
        return dst
