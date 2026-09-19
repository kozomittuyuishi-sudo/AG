"""
directory_reader/reader.py
===========================
Core Directory Reader for AB.

Responsibilities:
- Accept a user-provided directory path.
- Validate the directory exists and is accessible.
- Discover supported readable files (ignoring binaries, caches, .git, etc.).
- Identify files relevant to a given question using keyword matching.
- Read only the content of relevant files.
- Return structured file data for context construction.

READ-ONLY. Does not modify, execute, or delete any files.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional, Dict


# ---------------------------------------------------------------------------
# Supported text-readable file extensions
# ---------------------------------------------------------------------------

SUPPORTED_EXTENSIONS: frozenset = frozenset({
    ".txt", ".md", ".py", ".json",
    ".yaml", ".yml", ".ini", ".cfg", ".toml",
})

# Directories to always skip
SKIP_DIRS: frozenset = frozenset({
    ".git", ".venv", "__pycache__", ".pytest_cache",
    ".aider.tags.cache.v4", "node_modules", ".mypy_cache",
    ".tox", "dist", "build", ".eggs",
})

# Max bytes to read from a single file (128 KB) — prevents token overflow
MAX_FILE_BYTES: int = 131_072

# Max total context bytes across all files (512 KB)
MAX_CONTEXT_BYTES: int = 524_288


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class FileEntry:
    """A single readable file discovered in the directory."""
    path: str           # Absolute path
    rel_path: str       # Relative to the root directory
    name: str           # Filename only
    extension: str      # e.g. ".py"
    size_bytes: int     # On-disk size


@dataclass
class FileContent:
    """Content of a single file, read for context."""
    entry: FileEntry
    content: str        # Decoded text content
    truncated: bool     # True if content was cut at MAX_FILE_BYTES
    error: Optional[str] = None  # Set if the file could not be read


@dataclass
class DirectoryReadResult:
    """Result of loading a directory."""
    success: bool
    directory: str
    files: List[FileEntry] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def file_count(self) -> int:
        return len(self.files)


# ---------------------------------------------------------------------------
# Core reader
# ---------------------------------------------------------------------------

class DirectoryReader:
    """
    Reads and indexes a user-provided directory.

    Usage
    -----
    reader = DirectoryReader()
    result = reader.read_directory("D:/AG/docs")
    if result.success:
        contents = reader.get_relevant_files("what does the readme say")
    """

    def __init__(self) -> None:
        self._directory: Optional[str] = None
        self._files: List[FileEntry] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def read_directory(self, path: str) -> DirectoryReadResult:
        """
        Validate and index a directory.

        Parameters
        ----------
        path : str
            The directory path provided by the user.

        Returns
        -------
        DirectoryReadResult
            success=True and a list of FileEntry objects if valid.
            success=False with an error message otherwise.
        """
        self._directory = None
        self._files = []

        path = path.strip()

        if not path:
            return DirectoryReadResult(
                success=False,
                directory=path,
                error="No directory path provided.",
            )

        if not os.path.exists(path):
            return DirectoryReadResult(
                success=False,
                directory=path,
                error=f"Directory does not exist: {path}",
            )

        if not os.path.isdir(path):
            return DirectoryReadResult(
                success=False,
                directory=path,
                error=f"Path is not a directory: {path}",
            )

        if not os.access(path, os.R_OK):
            return DirectoryReadResult(
                success=False,
                directory=path,
                error=f"Directory is not accessible (permission denied): {path}",
            )

        try:
            entries = self._discover_files(path)
        except PermissionError as exc:
            return DirectoryReadResult(
                success=False,
                directory=path,
                error=f"Permission denied while scanning directory: {exc}",
            )
        except Exception as exc:
            return DirectoryReadResult(
                success=False,
                directory=path,
                error=f"Error scanning directory: {exc}",
            )

        self._directory = path
        self._files = entries

        return DirectoryReadResult(
            success=True,
            directory=path,
            files=entries,
        )

    @property
    def directory(self) -> Optional[str]:
        """The currently loaded directory path, or None."""
        return self._directory

    @property
    def files(self) -> List[FileEntry]:
        """All indexed readable files in the current directory."""
        return list(self._files)

    def get_relevant_files(
        self,
        question: str,
        max_files: int = 5,
    ) -> List[FileEntry]:
        """
        Return up to `max_files` FileEntries most likely relevant to `question`.

        Strategy
        --------
        - If the question is a directory-wide summary request (e.g. "elaborate
          about the files", "what does this directory contain", "summarize"),
          return ALL indexed files so the brain can produce a full overview.
          The context_builder enforces the token cap.
        - Otherwise score files by keyword overlap with the question.  If
          nothing scores > 0, return all files so a broad question is still
          answerable.

        Parameters
        ----------
        question : str
            The user's question.
        max_files : int
            Maximum number of files to return.  Ignored for summary queries
            (all files are returned) so the caller should rely on the
            context_builder's byte cap for token safety.
        """
        if not self._files:
            return []

        # --- Summary / overview queries: return everything ----------------
        if _is_summary_query(question):
            return list(self._files)

        question_lower = question.lower()
        keywords = set(_tokenise(question_lower))

        scored: List[tuple] = []
        for entry in self._files:
            score = _score_entry(entry, keywords)
            scored.append((score, entry))

        scored.sort(key=lambda t: t[0], reverse=True)

        best_score = scored[0][0] if scored else 0

        if best_score == 0:
            # No keyword match — return all files so broad questions are
            # still answerable (e.g. "elaborate about…").
            return list(self._files)

        top = [e for _, e in scored[:max_files]]
        return top

    def read_file(self, entry: FileEntry) -> FileContent:
        """
        Read the content of a single FileEntry.

        Returns a FileContent with error set if the file cannot be decoded.
        Never raises.
        """
        try:
            size = os.path.getsize(entry.path)
            truncated = size > MAX_FILE_BYTES

            with open(entry.path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read(MAX_FILE_BYTES)

            return FileContent(entry=entry, content=content, truncated=truncated)

        except PermissionError:
            return FileContent(
                entry=entry,
                content="",
                truncated=False,
                error=f"Permission denied reading: {entry.rel_path}",
            )
        except Exception as exc:
            return FileContent(
                entry=entry,
                content="",
                truncated=False,
                error=f"Could not read {entry.rel_path}: {exc}",
            )

    def read_relevant_files(
        self,
        question: str,
        max_files: int = 5,
    ) -> List[FileContent]:
        """
        Convenience: find relevant files and read their contents.

        Returns a list of FileContent objects. Files that fail to read
        will have error set rather than raising.
        """
        entries = self.get_relevant_files(question, max_files=max_files)
        return [self.read_file(e) for e in entries]

    def list_files(self) -> str:
        """
        Return a human-readable listing of all discovered files.
        Used when the user asks "what files are there?".
        """
        if not self._files:
            return "No readable files found in the directory."

        lines = [f"Files in {self._directory}:", ""]
        for entry in self._files:
            size_kb = entry.size_bytes / 1024
            lines.append(f"  {entry.rel_path}  ({size_kb:.1f} KB)")
        lines.append(f"\nTotal: {len(self._files)} file(s).")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _discover_files(self, root: str) -> List[FileEntry]:
        """Walk the directory tree and collect supported readable files."""
        found: List[FileEntry] = []

        for dirpath, dirnames, filenames in os.walk(root):
            # Prune skip-dirs in-place so os.walk doesn't descend into them
            dirnames[:] = [
                d for d in dirnames
                if d not in SKIP_DIRS and not d.startswith(".")
            ]

            for filename in filenames:
                _, ext = os.path.splitext(filename)
                if ext.lower() not in SUPPORTED_EXTENSIONS:
                    continue

                full_path = os.path.join(dirpath, filename)

                # Skip symlinks pointing outside the tree (security)
                if os.path.islink(full_path):
                    try:
                        real = os.path.realpath(full_path)
                        if not real.startswith(os.path.realpath(root)):
                            continue
                    except Exception:
                        continue

                try:
                    size = os.path.getsize(full_path)
                except OSError:
                    size = 0

                rel = os.path.relpath(full_path, root)

                found.append(FileEntry(
                    path=full_path,
                    rel_path=rel,
                    name=filename,
                    extension=ext.lower(),
                    size_bytes=size,
                ))

        return found


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _tokenise(text: str) -> List[str]:
    """Split text into lowercase alpha tokens, min length 3."""
    import re
    return [w for w in re.split(r"[^a-z0-9]+", text.lower()) if len(w) >= 3]


def _score_entry(entry: FileEntry, keywords: set) -> int:
    """
    Score a FileEntry against a set of keywords.
    Higher = more relevant.
    """
    score = 0
    name_tokens = set(_tokenise(entry.name))
    path_tokens = set(_tokenise(entry.rel_path))

    for kw in keywords:
        if kw in name_tokens:
            score += 3   # filename match is strongest signal
        elif kw in path_tokens:
            score += 1   # path match is weaker

    return score


# ---------------------------------------------------------------------------
# Summary query detection
# ---------------------------------------------------------------------------

_SUMMARY_KEYWORDS: frozenset = frozenset({
    "elaborate", "summarize", "summarise", "overview", "summary",
    "everything", "all files", "all the files", "contents",
    "what does this directory contain", "what is in this directory",
    "what does the directory contain", "what does it contain",
    "tell me about all", "explain all", "describe all",
    "accommodate", "accommodate?",
})

_SUMMARY_STARTERS: tuple = (
    "elaborate about",
    "elaborate on",
    "give me an overview",
    "give an overview",
    "summarize the",
    "summarise the",
    "summarize all",
    "summarise all",
    "what do these files",
    "what do all",
    "explain all the files",
    "tell me about all the files",
    "describe all",
    "what does this directory",
    "what is in the directory",
    "what is in this directory",
    "what does the directory",
    "what files are",
    "list all",
)


def _is_summary_query(question: str) -> bool:
    """
    Return True if the question is asking for a directory-wide summary,
    meaning all files should be included in the context rather than
    keyword-selected ones.
    """
    norm = question.strip().lower()

    # Check full-phrase keywords
    for kw in _SUMMARY_KEYWORDS:
        if kw in norm:
            return True

    # Check starter patterns
    for starter in _SUMMARY_STARTERS:
        if norm.startswith(starter):
            return True

    return False
