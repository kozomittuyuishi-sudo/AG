"""
directory_reader/context_builder.py
=====================================
Context Builder for the AB Directory Reader.

Assembles a prompt-ready context string from a list of FileContent objects.
The context is passed into the existing ask_brain() pipeline.

Design
------
- Format is minimal: file path header + content block per file.
- Truncation warnings are included so the brain knows content was cut.
- Total context is bounded to avoid exceeding model token limits.
- Does NOT call the brain. That is the caller's responsibility.
"""

from __future__ import annotations

from typing import List, Optional

from directory_reader.reader import FileContent, MAX_CONTEXT_BYTES


# ---------------------------------------------------------------------------
# Context header / separator
# ---------------------------------------------------------------------------

_FILE_SEPARATOR = "=" * 60
_MAX_HEADER_CHARS = 80


def build_context(
    file_contents: List[FileContent],
    question: str,
    directory: Optional[str] = None,
    max_bytes: int = MAX_CONTEXT_BYTES,
) -> str:
    """
    Build a context string suitable for injecting into a brain prompt.

    Parameters
    ----------
    file_contents : List[FileContent]
        Files to include. Files with errors are noted but skipped.
    question : str
        The user's question (used only for the header annotation).
    directory : str, optional
        The source directory path (for the header).
    max_bytes : int
        Hard cap on total context size.

    Returns
    -------
    str
        A formatted context block, or an explanatory message if no
        content could be assembled.
    """
    if not file_contents:
        return _no_content_message(directory)

    lines: List[str] = []
    total = 0
    included = 0
    skipped_errors: List[str] = []
    truncated_at_limit = False

    # Header
    header_parts = ["DIRECTORY CONTEXT"]
    if directory:
        header_parts.append(f"Source: {directory}")
    header_parts.append(f"Question: {question}")
    header = "\n".join(header_parts)
    lines.append(header)
    lines.append(_FILE_SEPARATOR)
    total += len(header.encode("utf-8")) + len(_FILE_SEPARATOR) + 2

    for fc in file_contents:
        if fc.error:
            skipped_errors.append(f"  {fc.entry.rel_path}: {fc.error}")
            continue

        if not fc.content.strip():
            # Empty file — note it but don't add noise
            continue

        # Build the file block
        file_header = f"FILE: {fc.entry.rel_path}"
        block_lines = [file_header, "-" * min(len(file_header), 60)]
        block_content = fc.content
        if fc.truncated:
            block_lines.append(f"[NOTE: File truncated at {len(fc.content)} bytes — larger than limit]")
        block_lines.append(block_content)
        block_lines.append("")  # blank line after each file

        block = "\n".join(block_lines)
        block_bytes = len(block.encode("utf-8"))

        if total + block_bytes > max_bytes:
            truncated_at_limit = True
            break

        lines.append(block)
        total += block_bytes
        included += 1

    # Append error notes
    if skipped_errors:
        lines.append("FILES SKIPPED (could not be read):")
        lines.extend(skipped_errors)
        lines.append("")

    if truncated_at_limit:
        lines.append(
            f"[NOTE: Context limit reached — only {included} of "
            f"{len(file_contents)} file(s) shown.]"
        )

    if included == 0 and not skipped_errors:
        return _no_content_message(directory)

    lines.append(_FILE_SEPARATOR)
    return "\n".join(lines)


def build_prompt(
    context: str,
    question: str,
) -> str:
    """
    Wrap the context block in a prompt suitable for ask_brain().

    Parameters
    ----------
    context : str
        The assembled context string from build_context().
    question : str
        The user's original question.

    Returns
    -------
    str
        A full prompt string to pass to ask_brain().
    """
    return (
        "You are answering a question using content from a directory "
        "that the user has explicitly provided.\n"
        "Use ONLY the file contents shown below to answer the question. "
        "If the answer is not present in the files, say so clearly.\n"
        "Do not invent information not found in the files.\n\n"
        f"{context}\n\n"
        f"User question: {question}"
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _no_content_message(directory: Optional[str]) -> str:
    """Standard message when no usable content could be assembled."""
    if directory:
        return (
            f"No readable content could be assembled from the directory: {directory}\n"
            "The directory may be empty, contain only unsupported file types, "
            "or all files may have failed to load."
        )
    return (
        "No readable content available. "
        "The directory may be empty or contain only unsupported file types."
    )
