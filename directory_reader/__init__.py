"""
directory_reader/
=================
AB Directory Reader

Allows AB to read and reason over a directory explicitly provided by the user.
Reads only supported text formats, selects only relevant files for the question,
and passes constructed context into the existing response pipeline.

Public API
----------
DirectoryReader     Core reader. Call .read_directory(path) to load, .get_context(question) to query.
DirectorySession    Holds the current active directory for a conversation session.
build_context       Build a prompt context string from files relevant to a question.
"""

from directory_reader.reader import DirectoryReader
from directory_reader.session import DirectorySession
from directory_reader.context_builder import build_context, build_prompt
from directory_reader.reader import _is_summary_query

__all__ = [
    "DirectoryReader",
    "DirectorySession",
    "build_context",
    "build_prompt",
    "_is_summary_query",
]
