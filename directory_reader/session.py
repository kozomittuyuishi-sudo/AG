"""
directory_reader/session.py
============================
Directory Session State for AB.

Maintains the current active directory for a single conversation session.
The session is temporary — it is never persisted to disk and does not
modify any files.

Design
------
- One directory may be active at a time.
- set_directory() loads a new directory via the DirectoryReader.
- clear() removes the active directory.
- The session is NOT permanent memory; it does not write to memory.json.
"""

from __future__ import annotations

from typing import Optional

from directory_reader.reader import DirectoryReader, DirectoryReadResult


class DirectorySession:
    """
    Tracks the directory currently being used as an information source
    within a single conversation session.

    Usage
    -----
    session = DirectorySession()
    result = session.set_directory("D:/AG/docs")
    if session.is_active:
        contents = session.reader.read_relevant_files("what is the architecture?")
    session.clear()
    """

    def __init__(self) -> None:
        self._reader: DirectoryReader = DirectoryReader()
        self._active: bool = False
        self._last_error: Optional[str] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        """True if a valid directory is currently loaded."""
        return self._active

    @property
    def directory(self) -> Optional[str]:
        """The path of the active directory, or None."""
        return self._reader.directory if self._active else None

    @property
    def reader(self) -> DirectoryReader:
        """The underlying DirectoryReader (available even if not active)."""
        return self._reader

    @property
    def last_error(self) -> Optional[str]:
        """The last error message from set_directory(), or None."""
        return self._last_error

    def set_directory(self, path: str) -> DirectoryReadResult:
        """
        Load a new directory into the session.

        Replaces any previously active directory.
        Returns a DirectoryReadResult; inspect .success to check outcome.

        Parameters
        ----------
        path : str
            The directory path provided by the user.
        """
        self._active = False
        self._last_error = None

        result = self._reader.read_directory(path)

        if result.success:
            self._active = True
        else:
            self._last_error = result.error

        return result

    def clear(self) -> None:
        """
        Remove the active directory from the session.

        This does NOT delete or modify any files.
        """
        self._active = False
        self._last_error = None
        self._reader = DirectoryReader()

    def summary(self) -> str:
        """
        Return a one-line summary of the current session state.
        """
        if not self._active:
            return "No directory currently loaded."
        n = len(self._reader.files)
        return f"Active directory: {self.directory} ({n} readable file(s) indexed)."
