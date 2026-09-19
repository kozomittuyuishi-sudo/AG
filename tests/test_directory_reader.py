"""
tests/test_directory_reader.py
================================
Tests for the AB Directory Reader.

Covers:
 1.  Valid directory
 2.  Invalid directory
 3.  Empty directory (no supported files)
 4.  Directory containing supported files
 5.  Directory containing unsupported/binary files
 6.  File discovery
 7.  Specific-file retrieval
 8.  Directory-wide summary queries
 9.  Multiple relevant files
10.  Temporary directory context (DirectorySession)
11.  Follow-up questions use previously supplied directory
12.  Directory replacement
13.  Read-only behaviour
14.  Context handoff to response pipeline
15.  Missing information
16.  Existing fallback behaviour (import sanity)
"""

import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from directory_reader.reader import (
    DirectoryReader,
    SUPPORTED_EXTENSIONS,
    _is_summary_query,
)
from directory_reader.session import DirectorySession
from directory_reader.context_builder import build_context, build_prompt


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_dir():
    """A real, writeable temporary directory cleaned up after the test."""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture()
def populated_dir(tmp_dir):
    """Temporary directory with a mix of supported and unsupported files."""
    _write(tmp_dir, "readme.md", "# Project\nThis is the architecture overview.\n")
    _write(tmp_dir, "config.yaml", "version: 1\nname: test_project\n")
    _write(tmp_dir, "notes.txt", "Dispatcher routes intents to handlers.\n")
    _write(tmp_dir, "script.py", "def hello():\n    return 'hello'\n")
    # Unsupported file
    _write(tmp_dir, "image.png", b"\x89PNG\r\n\x1a\n\x00\x00binary")
    _write(tmp_dir, "binary.exe", b"\x4d\x5a\x90\x00binary")
    return tmp_dir


def _write(directory, filename, content):
    path = os.path.join(directory, filename)
    mode = "wb" if isinstance(content, bytes) else "w"
    with open(path, mode) as f:
        f.write(content)
    return path


# ===========================================================================
# 1. Valid directory
# ===========================================================================

def test_valid_directory(tmp_dir):
    reader = DirectoryReader()
    result = reader.read_directory(tmp_dir)
    assert result.success is True
    assert result.directory == tmp_dir
    assert result.error is None


# ===========================================================================
# 2. Invalid directory
# ===========================================================================

def test_invalid_directory():
    reader = DirectoryReader()
    result = reader.read_directory("Z:\\does_not_exist_ever_12345")
    assert result.success is False
    assert result.error is not None
    assert "does not exist" in result.error.lower() or "not" in result.error.lower()


def test_path_is_file_not_directory(tmp_dir):
    file_path = _write(tmp_dir, "file.txt", "content")
    reader = DirectoryReader()
    result = reader.read_directory(file_path)
    assert result.success is False
    assert result.error is not None


def test_empty_path():
    reader = DirectoryReader()
    result = reader.read_directory("")
    assert result.success is False


# ===========================================================================
# 3. Empty directory (no supported files)
# ===========================================================================

def test_empty_directory(tmp_dir):
    """A directory with no files at all."""
    reader = DirectoryReader()
    result = reader.read_directory(tmp_dir)
    assert result.success is True
    assert result.file_count == 0


def test_directory_only_binary_files(tmp_dir):
    """A directory with only binary files — no supported types."""
    _write(tmp_dir, "image.png", b"\x89PNG\r\nbinary")
    _write(tmp_dir, "archive.zip", b"PK\x03\x04binary")
    reader = DirectoryReader()
    result = reader.read_directory(tmp_dir)
    assert result.success is True
    assert result.file_count == 0


# ===========================================================================
# 4. Directory containing supported files
# ===========================================================================

def test_supported_files_discovered(populated_dir):
    reader = DirectoryReader()
    result = reader.read_directory(populated_dir)
    assert result.success is True
    extensions = {e.extension for e in result.files}
    assert extensions.issubset(SUPPORTED_EXTENSIONS)
    assert result.file_count >= 4  # readme.md, config.yaml, notes.txt, script.py


def test_all_supported_extensions_accepted(tmp_dir):
    """Each extension in SUPPORTED_EXTENSIONS is accepted."""
    for ext in SUPPORTED_EXTENSIONS:
        _write(tmp_dir, f"file{ext}", "content")
    reader = DirectoryReader()
    result = reader.read_directory(tmp_dir)
    assert result.success is True
    found_exts = {e.extension for e in result.files}
    assert found_exts == SUPPORTED_EXTENSIONS


# ===========================================================================
# 5. Unsupported/binary files are ignored
# ===========================================================================

def test_binary_files_excluded(populated_dir):
    reader = DirectoryReader()
    result = reader.read_directory(populated_dir)
    names = {e.name for e in result.files}
    assert "image.png" not in names
    assert "binary.exe" not in names


def test_skip_dirs_not_traversed(tmp_dir):
    """Files inside SKIP_DIRS are not indexed."""
    skip_subdir = os.path.join(tmp_dir, ".git")
    os.makedirs(skip_subdir)
    _write(skip_subdir, "config.txt", "git stuff")
    reader = DirectoryReader()
    result = reader.read_directory(tmp_dir)
    paths = [e.rel_path for e in result.files]
    assert not any(".git" in p for p in paths)


# ===========================================================================
# 6. File discovery
# ===========================================================================

def test_file_discovery_returns_metadata(populated_dir):
    """FileEntry objects have correct name, extension, and rel_path fields."""
    reader = DirectoryReader()
    reader.read_directory(populated_dir)
    entries = {e.name: e for e in reader.files}
    assert "readme.md" in entries
    assert entries["readme.md"].extension == ".md"
    assert entries["readme.md"].size_bytes > 0
    assert entries["readme.md"].rel_path == "readme.md"


def test_list_files_string(populated_dir):
    """list_files() returns a human-readable string listing all files."""
    reader = DirectoryReader()
    reader.read_directory(populated_dir)
    listing = reader.list_files()
    assert "readme.md" in listing
    assert "config.yaml" in listing
    assert "notes.txt" in listing


def test_list_files_empty_directory(tmp_dir):
    reader = DirectoryReader()
    reader.read_directory(tmp_dir)
    listing = reader.list_files()
    assert "No readable files" in listing


# ===========================================================================
# 7. Specific-file retrieval
# ===========================================================================

def test_specific_file_by_name(populated_dir):
    """Asking about 'readme' returns readme.md as the top result."""
    reader = DirectoryReader()
    reader.read_directory(populated_dir)
    relevant = reader.get_relevant_files("What does the readme say?")
    names = [e.name for e in relevant]
    assert "readme.md" in names
    assert relevant[0].name == "readme.md"


def test_specific_file_config(populated_dir):
    reader = DirectoryReader()
    reader.read_directory(populated_dir)
    relevant = reader.get_relevant_files("what is the config version?")
    names = [e.name for e in relevant]
    assert "config.yaml" in names


def test_specific_file_script(populated_dir):
    reader = DirectoryReader()
    reader.read_directory(populated_dir)
    relevant = reader.get_relevant_files("what does script.py do?")
    names = [e.name for e in relevant]
    assert "script.py" in names


def test_read_file_content(populated_dir):
    """read_file() returns the actual content of the file."""
    reader = DirectoryReader()
    reader.read_directory(populated_dir)
    entry = next(e for e in reader.files if e.name == "readme.md")
    fc = reader.read_file(entry)
    assert fc.error is None
    assert "architecture overview" in fc.content


# ===========================================================================
# 8. Directory-wide summary queries
# ===========================================================================

def test_summary_query_returns_all_files(populated_dir):
    """Summary queries return all indexed files, not just keyword-matched ones."""
    reader = DirectoryReader()
    reader.read_directory(populated_dir)

    # "Elaborate about the files" is the exact failing query from the bug report
    relevant = reader.get_relevant_files("Elaborate about the files in the directory and tell me what they accommodate?")
    names = {e.name for e in relevant}
    assert "readme.md" in names
    assert "config.yaml" in names
    assert "notes.txt" in names
    assert "script.py" in names


def test_is_summary_query_elaborate():
    assert _is_summary_query("Elaborate about the files in the directory and tell me what they accommodate?") is True


def test_is_summary_query_summarize():
    assert _is_summary_query("Summarize the directory contents") is True


def test_is_summary_query_overview():
    assert _is_summary_query("Give me an overview of what is here") is True


def test_is_summary_query_contents():
    assert _is_summary_query("What does this directory contain?") is True


def test_is_summary_query_specific_file_is_not_summary():
    """A specific-file question should NOT be detected as a summary query."""
    assert _is_summary_query("What does readme.md say about the architecture?") is False


def test_summary_query_context_includes_all_files(populated_dir):
    """build_context includes all files for a summary query."""
    reader = DirectoryReader()
    reader.read_directory(populated_dir)
    question = "Elaborate about the files in the directory and tell me what they accommodate?"
    contents = reader.read_relevant_files(question)
    ctx = build_context(contents, question=question, directory=populated_dir)
    assert "readme.md" in ctx
    assert "config.yaml" in ctx
    assert "notes.txt" in ctx
    assert "script.py" in ctx


# ===========================================================================
# 9. Multiple relevant files returned
# ===========================================================================

def test_multiple_relevant_files(tmp_dir):
    _write(tmp_dir, "arch_overview.md", "The dispatcher routes intents.")
    _write(tmp_dir, "arch_detail.txt", "Architecture detail: pipelines.")
    _write(tmp_dir, "unrelated.txt", "Shopping list: eggs, milk.")
    reader = DirectoryReader()
    reader.read_directory(tmp_dir)
    relevant = reader.get_relevant_files("tell me about the architecture", max_files=5)
    names = [e.name for e in relevant]
    assert "arch_overview.md" in names
    assert "arch_detail.txt" in names


# ===========================================================================
# 10. Temporary directory context (DirectorySession)
# ===========================================================================

def test_session_set_and_clear(tmp_dir):
    _write(tmp_dir, "doc.md", "Some content")
    session = DirectorySession()
    assert session.is_active is False
    assert session.directory is None

    result = session.set_directory(tmp_dir)
    assert result.success is True
    assert session.is_active is True
    assert session.directory == tmp_dir

    session.clear()
    assert session.is_active is False
    assert session.directory is None


def test_session_invalid_path():
    session = DirectorySession()
    result = session.set_directory("Z:\\nonexistent_9999")
    assert result.success is False
    assert session.is_active is False
    assert session.last_error is not None


def test_session_summary_when_active(tmp_dir):
    _write(tmp_dir, "a.txt", "hello")
    session = DirectorySession()
    session.set_directory(tmp_dir)
    summary = session.summary()
    assert "Active directory" in summary
    assert "1 readable file" in summary


def test_session_summary_when_inactive():
    session = DirectorySession()
    summary = session.summary()
    assert "No directory" in summary


# ===========================================================================
# 11. Follow-up questions use previously supplied directory
# ===========================================================================

def test_followup_uses_existing_session(tmp_dir):
    _write(tmp_dir, "facts.txt", "The capital of France is Paris.")
    session = DirectorySession()
    result = session.set_directory(tmp_dir)
    assert result.success is True

    # Follow-up question uses the same session
    assert session.is_active is True
    contents = session.reader.read_relevant_files("What is the capital of France?")
    assert len(contents) > 0
    assert "Paris" in contents[0].content


def test_followup_elaborate_uses_session(tmp_dir):
    """The exact failing query from the bug report must find content."""
    _write(tmp_dir, "overview.md", "# Overview\nThis system handles routing and dispatch.")
    _write(tmp_dir, "config.ini", "[settings]\nmode=production")
    session = DirectorySession()
    session.set_directory(tmp_dir)
    assert session.is_active is True

    question = "Elaborate about the files in the directory and tell me what they accommodate?"
    contents = session.reader.read_relevant_files(question)
    assert len(contents) >= 2  # Both files must be returned for a summary query
    names = {fc.entry.name for fc in contents}
    assert "overview.md" in names
    assert "config.ini" in names


# ===========================================================================
# 12. Directory replacement
# ===========================================================================

def test_session_replaces_previous(tmp_dir):
    """Loading a new directory replaces the old one completely."""
    _write(tmp_dir, "a.txt", "first directory")
    with tempfile.TemporaryDirectory() as tmp2:
        _write(tmp2, "b.md", "second directory")
        session = DirectorySession()
        session.set_directory(tmp_dir)
        assert session.directory == tmp_dir
        first_files = {e.name for e in session.reader.files}
        assert "a.txt" in first_files

        session.set_directory(tmp2)
        assert session.directory == tmp2
        second_files = {e.name for e in session.reader.files}
        assert "b.md" in second_files
        assert "a.txt" not in second_files  # Old directory no longer present


def test_directory_replacement_clears_old_context(tmp_dir):
    """After replacement, queries return content from the new directory only."""
    _write(tmp_dir, "old_doc.txt", "Old content about widgets.")
    with tempfile.TemporaryDirectory() as tmp2:
        _write(tmp2, "new_doc.txt", "New content about gadgets.")
        session = DirectorySession()
        session.set_directory(tmp_dir)
        session.set_directory(tmp2)

        contents = session.reader.read_relevant_files("widgets or gadgets")
        file_names = [fc.entry.name for fc in contents]
        assert "new_doc.txt" in file_names
        assert "old_doc.txt" not in file_names


# ===========================================================================
# 13. Read-only behaviour
# ===========================================================================

def test_reader_does_not_modify_files(tmp_dir):
    file_path = _write(tmp_dir, "original.txt", "Original content unchanged.")
    original_mtime = os.path.getmtime(file_path)
    original_size = os.path.getsize(file_path)

    reader = DirectoryReader()
    result = reader.read_directory(tmp_dir)
    assert result.success is True

    contents = reader.read_relevant_files("original content", max_files=5)

    assert os.path.getmtime(file_path) == original_mtime
    assert os.path.getsize(file_path) == original_size

    with open(file_path, "r") as f:
        text = f.read()
    assert text == "Original content unchanged."


def test_session_clear_does_not_delete_files(tmp_dir):
    file_path = _write(tmp_dir, "keep_me.txt", "Important content.")
    session = DirectorySession()
    session.set_directory(tmp_dir)
    session.clear()

    assert os.path.exists(file_path), "clear() must not delete files"
    with open(file_path, "r") as f:
        assert f.read() == "Important content."


# ===========================================================================
# 14. Context handoff to response pipeline
# ===========================================================================

def test_context_handoff_build_context(populated_dir):
    """build_context produces a string containing file content, not just metadata."""
    reader = DirectoryReader()
    reader.read_directory(populated_dir)
    contents = reader.read_relevant_files("architecture", max_files=3)
    ctx = build_context(contents, question="What is the architecture?", directory=populated_dir)
    assert "DIRECTORY CONTEXT" in ctx
    assert "FILE:" in ctx
    # Must contain actual file content, not just a path reference
    assert "architecture overview" in ctx or "dispatcher" in ctx or "version" in ctx


def test_build_prompt_structure(populated_dir):
    """build_prompt wraps context correctly so the brain receives retrieved content."""
    reader = DirectoryReader()
    reader.read_directory(populated_dir)
    contents = reader.read_relevant_files("readme")
    ctx = build_context(contents, question="What is this?")
    prompt = build_prompt(ctx, "What is this?")
    # Prompt must include both the context block and the user question
    assert "User question:" in prompt
    assert "DIRECTORY CONTEXT" in prompt
    # Must include actual content (not just metadata)
    assert "FILE:" in prompt


def test_context_handoff_contains_file_content(tmp_dir):
    """The context passed to the brain must contain actual file content."""
    _write(tmp_dir, "info.txt", "The system uses an event-driven dispatcher.")
    reader = DirectoryReader()
    reader.read_directory(tmp_dir)
    contents = reader.read_relevant_files("what does the system use?")
    ctx = build_context(contents, question="what does the system use?", directory=tmp_dir)
    prompt = build_prompt(ctx, "what does the system use?")
    # The brain must receive the actual file content
    assert "event-driven dispatcher" in prompt


def test_build_context_empty_list():
    ctx = build_context([], question="anything")
    assert "No readable content" in ctx


# ===========================================================================
# 15. Missing information
# ===========================================================================

def test_missing_information_response(tmp_dir):
    """When queried content doesn't exist in the directory, context is truthful."""
    _write(tmp_dir, "doc.txt", "This file talks about weather only.")
    reader = DirectoryReader()
    reader.read_directory(tmp_dir)
    contents = reader.read_relevant_files("quantum entanglement theory", max_files=5)
    # All files are returned (no keyword match → return all) so contents is non-empty
    # but the actual content about quantum entanglement is absent
    if contents:
        all_content = " ".join(fc.content for fc in contents)
        assert "quantum" not in all_content.lower()


def test_build_context_error_files(tmp_dir):
    """Files with read errors are noted but do not crash context building."""
    from directory_reader.reader import FileContent, FileEntry

    fake_entry = FileEntry(
        path="/nonexistent/file.txt",
        rel_path="file.txt",
        name="file.txt",
        extension=".txt",
        size_bytes=100,
    )
    errored = FileContent(entry=fake_entry, content="", truncated=False, error="Permission denied")
    ctx = build_context([errored], question="anything")
    # Should note the error, not crash
    assert "SKIPPED" in ctx or "No readable content" in ctx


# ===========================================================================
# 16. Existing fallback behaviour (import sanity)
# ===========================================================================

def test_existing_pipeline_imports_unaffected():
    """Verify that importing directory_reader does not break the pipeline."""
    from pipeline.ag_pipeline import AGPipeline
    from directory_reader import DirectoryReader, DirectorySession, build_context, build_prompt
    from directory_reader.reader import _is_summary_query
    assert AGPipeline is not None
    assert DirectoryReader is not None
    assert DirectorySession is not None
    assert build_context is not None
    assert build_prompt is not None
    assert _is_summary_query is not None


def test_ag_pipeline_unaffected_by_directory_reader():
    """AGPipeline instantiation and process_input still work after directory_reader changes."""
    from pipeline.ag_pipeline import AGPipeline
    pipeline = AGPipeline()
    result = pipeline.process_input("hello test")
    # Must return a result object (not crash)
    assert result is not None
    assert hasattr(result, "success")
    assert hasattr(result, "user_input")
