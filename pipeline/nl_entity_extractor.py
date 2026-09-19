"""
pipeline/nl_entity_extractor.py
================================
Fixed NL entity extraction for AG.

Extracts structured entities (target path/name, secondary target, content)
from natural-language input strings using deterministic rules — no LLM.

Rules applied in order
----------------------
1. Quoted strings (single or double quotes) → target is the quoted content.
2. Angle-bracket wrappers ``<...>`` are stripped.
3. Boundary keywords trim trailing clauses:
       ' and ', ' with ', ':', ' that ', ' then '
   Text after the boundary (post-colon or post-'and') becomes ``content``.
4. Relative paths (``../`` or ``..\\``) are resolved against ``base_path``
   and validated to remain inside the workspace.
5. Leading noise prefixes are stripped from filenames and folder names.

Public API
----------
extract_target(text, base_path=None) -> dict
    Keys: target (str|None), content (str|None),
          path_type ('file'|'dir'|'new'|'unknown')

extract_filename(text) -> str
    Strip noise prefixes and return the cleaned filename token.

extract_foldername(text) -> str
    Strip noise prefixes and return the cleaned folder name token.

check_path_type(path, base_path) -> str
    Return 'file', 'dir', or 'new'.

Design rules
------------
- Stdlib only, no LLM calls.
- Never raises; degrades gracefully on bad input.
- Python 3.12 compatible.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Boundary keyword patterns (ordered — more specific first)
# ---------------------------------------------------------------------------

# The content extractor looks for these boundaries in the text.
# Each tuple is (boundary_text, produces_content).
# ':' is special — everything after ':' is content.
_CONTENT_BOUNDARIES: tuple[tuple[str, bool], ...] = (
    (" and write: ",  True),   # "create X and write: content" → content after ':'
    (" and write ",   True),   # "create X and write content" → content after 'write '
    (" with content:", True),
    (" with content ", True),
    (" that contains ", True),
    (" that says ",    True),
    (" then write ",   True),
    (" then ",         False),  # trim but no content
    (" and ",          False),  # trim but no content
    (" with ",         False),  # trim but no content
    (":",              True),   # bare colon → everything after is content
)

# Target noise prefixes — stripped from the remaining text to get the
# actual filename/foldername token.
_FILE_NOISE_PREFIXES: tuple[str, ...] = (
    "a file called ",
    "a file named ",
    "the file called ",
    "the file named ",
    "file called ",
    "file named ",
    "called ",
    "named ",
)

_FOLDER_NOISE_PREFIXES: tuple[str, ...] = (
    "a folder called ",
    "a folder named ",
    "a directory called ",
    "a directory named ",
    "the folder called ",
    "the folder named ",
    "folder called ",
    "folder named ",
    "directory called ",
    "directory named ",
    "called ",
    "named ",
)

# Combined set for generic target extraction (used when we don't know
# whether it's a file or folder context).
_GENERIC_NOISE_PREFIXES: tuple[str, ...] = (
    "a file called ",
    "a file named ",
    "a folder called ",
    "a folder named ",
    "a directory called ",
    "a directory named ",
    "the file called ",
    "the file named ",
    "the folder called ",
    "the folder named ",
    "file called ",
    "file named ",
    "folder called ",
    "folder named ",
    "directory called ",
    "directory named ",
    "called ",
    "named ",
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _strip_quotes(text: str) -> tuple[Optional[str], str]:
    """
    If ``text`` contains a quoted substring (single or double quotes),
    return (quoted_content, text_after_closing_quote).

    Returns (None, text) if no quotes are found.
    The first quote found (leftmost) is used.
    """
    for quote_char in ('"', "'"):
        start = text.find(quote_char)
        if start == -1:
            continue
        end = text.find(quote_char, start + 1)
        if end == -1:
            # Unclosed quote — take everything after the opening quote.
            return text[start + 1:].strip(), ""
        quoted = text[start + 1:end].strip()
        remainder = text[end + 1:].strip()
        return quoted, remainder
    return None, text


def _strip_angle_brackets(text: str) -> str:
    """Remove leading ``<`` and trailing ``>`` wrapper characters."""
    text = text.strip()
    if text.startswith("<") and text.endswith(">"):
        return text[1:-1].strip()
    # Also handle just a leading < or trailing >
    if text.startswith("<"):
        text = text[1:].strip()
    if text.endswith(">"):
        text = text[:-1].strip()
    return text


def _split_at_boundary(text: str) -> tuple[str, Optional[str]]:
    """
    Split ``text`` at the first recognised boundary keyword.

    Returns (target_part, content_part_or_None).
    The boundary keyword itself is consumed.
    """
    lower = text.lower()

    for boundary, produces_content in _CONTENT_BOUNDARIES:
        idx = lower.find(boundary)
        if idx == -1:
            continue

        target_part = text[:idx].strip()
        after = text[idx + len(boundary):].strip()

        if produces_content and after:
            # For 'and write X', the content is after 'write '
            if boundary in (" and write ", " then write "):
                content_part = after
            elif boundary == ":":
                content_part = after
            else:
                content_part = after
            return target_part, content_part if content_part else None
        else:
            return target_part, None

    return text.strip(), None


def _strip_noise_prefixes(text: str, prefixes: tuple[str, ...]) -> str:
    """Strip the first matching noise prefix from ``text`` (case-insensitive)."""
    lower = text.lower()
    for prefix in prefixes:
        if lower.startswith(prefix):
            return text[len(prefix):].strip()
    return text.strip()


def _resolve_relative_path(
    text: str,
    base_path: Optional[Path],
) -> tuple[str, str]:
    """
    If ``text`` looks like a relative path (starts with ../ or ..\\ ),
    resolve it against ``base_path`` and verify containment.

    Returns (resolved_str_or_original, path_type).
    ``path_type`` is one of: 'file', 'dir', 'new', 'unknown'.
    """
    if base_path is None:
        return text, "unknown"

    stripped = text.strip()
    is_relative = (
        stripped.startswith("../")
        or stripped.startswith("..\\")
        or stripped.startswith("./")
        or stripped.startswith(".\\")
    )
    if not is_relative:
        return text, "unknown"

    try:
        candidate = (base_path / stripped).resolve()
        # Validate containment
        ws = base_path.resolve()
        candidate.relative_to(ws)  # raises ValueError if outside
        return str(candidate), _path_type_str(candidate)
    except (ValueError, OSError):
        # Out of workspace or invalid → return original, flag unknown
        return text, "unknown"


def _path_type_str(path: Path) -> str:
    """Return 'file', 'dir', or 'new' for a Path object."""
    if not path.exists():
        return "new"
    if path.is_file():
        return "file"
    if path.is_dir():
        return "dir"
    return "new"


def _infer_path_type(text: str, base_path: Optional[Path]) -> str:
    """
    Given a target string and optional base_path, determine path type.

    Checks if the path exists within the workspace (if base_path provided)
    or falls back to extension-based heuristic.
    """
    if not text:
        return "unknown"

    if base_path is not None:
        try:
            candidate = (base_path / text).resolve()
            ws = base_path.resolve()
            candidate.relative_to(ws)
            return _path_type_str(candidate)
        except (ValueError, OSError):
            pass

    # Heuristic: presence of an extension suggests a file
    p = Path(text)
    if p.suffix:
        return "new"  # probably a file that doesn't exist yet

    return "unknown"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_filename(text: str) -> str:
    """
    Strip leading noise prefixes for a filename context and return the
    cleaned token.

    Example
    -------
    >>> extract_filename("a file called notes.txt")
    'notes.txt'
    >>> extract_filename("called readme.md")
    'readme.md'
    """
    return _strip_noise_prefixes(text.strip(), _FILE_NOISE_PREFIXES)


def extract_foldername(text: str) -> str:
    """
    Strip leading noise prefixes for a folder name context and return the
    cleaned token.

    Example
    -------
    >>> extract_foldername("a folder called projects")
    'projects'
    >>> extract_foldername("named archive")
    'archive'
    """
    return _strip_noise_prefixes(text.strip(), _FOLDER_NOISE_PREFIXES)


def check_path_type(path: str, base_path: Optional[Path] = None) -> str:
    """
    Return the type of ``path`` relative to ``base_path``.

    Returns
    -------
    'file'    — path exists and is a regular file.
    'dir'     — path exists and is a directory.
    'new'     — path does not exist (candidate for creation).
    'unknown' — cannot determine (no base_path and path is not absolute).
    """
    if not path:
        return "unknown"

    # Absolute path check
    p = Path(path)
    if p.is_absolute():
        return _path_type_str(p)

    if base_path is not None:
        try:
            candidate = (base_path / path).resolve()
            ws = base_path.resolve()
            candidate.relative_to(ws)
            return _path_type_str(candidate)
        except (ValueError, OSError):
            return "unknown"

    return "unknown"


def extract_target(
    text: str,
    base_path: Optional[Path] = None,
) -> dict:
    """
    Extract a structured target entity from a natural-language text fragment.

    The ``text`` should be the portion of the user input that follows any
    intent-identifying prefix (e.g. for "create file notes.txt", pass
    "notes.txt" or "a file called notes.txt").

    Parameters
    ----------
    text : str
        The text to parse.
    base_path : Path, optional
        Active workspace path for relative-path resolution and existence checks.

    Returns
    -------
    dict with keys:
        target     : str | None  — the extracted target (filename/path/foldername)
        content    : str | None  — content payload extracted after a boundary keyword
        path_type  : str         — 'file', 'dir', 'new', or 'unknown'
    """
    if not text or not isinstance(text, str):
        return {"target": None, "content": None, "path_type": "unknown"}

    working = text.strip()
    content: Optional[str] = None

    # ----------------------------------------------------------------
    # Rule 1: Extract quoted content as target
    # ----------------------------------------------------------------
    quoted, remainder_after_quote = _strip_quotes(working)
    if quoted is not None:
        target_raw = quoted
        # Content might follow after the closing quote
        # e.g. 'create "notes.txt" with content: hello'
        if remainder_after_quote:
            _, possible_content = _split_at_boundary(remainder_after_quote)
            if possible_content:
                content = possible_content
    else:
        # ----------------------------------------------------------------
        # Rule 2: Strip angle bracket wrappers
        # ----------------------------------------------------------------
        working = _strip_angle_brackets(working)

        # ----------------------------------------------------------------
        # Rule 3: Split at boundary keywords
        # ----------------------------------------------------------------
        target_raw, content = _split_at_boundary(working)

    # ----------------------------------------------------------------
    # Rule 5/6: Strip noise prefixes
    # ----------------------------------------------------------------
    target_clean = _strip_noise_prefixes(target_raw, _GENERIC_NOISE_PREFIXES)

    # Strip residual angle brackets that might remain after noise stripping
    target_clean = _strip_angle_brackets(target_clean)

    # Strip trailing punctuation that is part of sentence structure, not the path
    target_clean = target_clean.rstrip(".,")

    # ----------------------------------------------------------------
    # Rule 4: Resolve relative paths
    # ----------------------------------------------------------------
    is_relative = (
        target_clean.startswith("../")
        or target_clean.startswith("..\\")
        or target_clean.startswith("./")
        or target_clean.startswith(".\\")
    )
    if is_relative and base_path is not None:
        target_clean, path_type = _resolve_relative_path(target_clean, base_path)
    else:
        path_type = _infer_path_type(target_clean, base_path)

    # Normalise empty target to None
    if not target_clean:
        target_clean = None  # type: ignore[assignment]

    return {
        "target": target_clean,
        "content": content,
        "path_type": path_type,
    }
