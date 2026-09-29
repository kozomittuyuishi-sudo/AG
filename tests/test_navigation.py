"""
tests/test_navigation.py
=========================
Phase 8 — Regression tests for AG's complete navigation capability.

Covers the NAVIGATE contract (Phase 2–7):

  1.  Absolute navigation
  2.  Relative navigation (bare name, multi-segment)
  3.  Parent navigation (go up, go back, go to .., go to parent)
  4.  Current-location navigation (go to .)
  5.  Current-location queries (where am I?, what directory am I in?, …)
  6.  Windows path variants (forward slash, backslash, mixed)
  7.  Paths containing spaces
  8.  Invalid targets (nonexistent, file-not-dir, malformed)
  9.  State preserved after failed navigation
 10.  State transitions (multi-hop)
 11.  NAVIGATE vs READ distinction
 12.  NAVIGATE vs SET_WORKSPACE distinction
 13.  IntentRouter navigation routing
 14.  PreprocessorBrain end-to-end NAVIGATE results
 15.  DirectoryControl.navigate_directory() unit tests
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from directory_control import (
    DirectoryControl,
    NoActiveWorkspaceError,
    WorkspaceNotFoundError,
)
from preprocessor_brain import (
    Domain,
    Intent,
    DirErrorCode,
    PreprocessorBrain,
)
from pipeline.intent_router import classify as route_intent, Intent as RouterIntent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def ws_tree():
    """
    A temporary workspace with the following layout:

        <root>/
            backup/
                pre_preprocessor_migration/
            automation timeline/       <- has a space
            test.txt                   <- file (not navigable)
            subdir/
    """
    with tempfile.TemporaryDirectory() as root_str:
        root = Path(root_str)
        (root / "backup" / "pre_preprocessor_migration").mkdir(parents=True)
        (root / "automation timeline").mkdir()
        (root / "subdir").mkdir()
        (root / "test.txt").write_text("not a directory", encoding="utf-8")
        yield root


@pytest.fixture()
def dc(ws_tree):
    """A DirectoryControl with the workspace already set."""
    ctrl = DirectoryControl()
    ctrl.set_directory(str(ws_tree))
    return ctrl


@pytest.fixture()
def pb(ws_tree):
    """A PreprocessorBrain connected to a DirectoryControl in ws_tree."""
    ctrl = DirectoryControl()
    ctrl.set_directory(str(ws_tree))
    return PreprocessorBrain(directory_control=ctrl)


# ===========================================================================
# 1. DirectoryControl.navigate_directory — unit tests
# ===========================================================================

class TestNavigateDirectoryUnit:

    def test_navigate_to_absolute_path(self, ws_tree):
        ctrl = DirectoryControl()
        backup = ws_tree / "backup"
        result = ctrl.navigate_directory(str(backup))
        assert Path(result).resolve() == backup.resolve()
        assert Path(ctrl.get_active_directory()).resolve() == backup.resolve()

    def test_navigate_to_child_dir_relative(self, dc, ws_tree):
        result = dc.navigate_directory("backup")
        assert Path(result).resolve() == (ws_tree / "backup").resolve()
        assert Path(dc.get_active_directory()).resolve() == (ws_tree / "backup").resolve()

    def test_navigate_to_multi_segment_relative(self, dc, ws_tree):
        result = dc.navigate_directory("backup/pre_preprocessor_migration")
        expected = ws_tree / "backup" / "pre_preprocessor_migration"
        assert Path(result).resolve() == expected.resolve()

    def test_navigate_to_backslash_multi_segment(self, dc, ws_tree):
        result = dc.navigate_directory("backup\\pre_preprocessor_migration")
        expected = ws_tree / "backup" / "pre_preprocessor_migration"
        assert Path(result).resolve() == expected.resolve()

    def test_navigate_to_dotdot_goes_to_parent(self, dc, ws_tree):
        # First go into backup
        dc.navigate_directory("backup")
        # Then go up
        result = dc.navigate_directory("..")
        assert Path(result).resolve() == ws_tree.resolve()
        assert Path(dc.get_active_directory()).resolve() == ws_tree.resolve()

    def test_navigate_to_dot_stays_in_current(self, dc, ws_tree):
        result = dc.navigate_directory(".")
        assert Path(result).resolve() == ws_tree.resolve()
        assert Path(dc.get_active_directory()).resolve() == ws_tree.resolve()

    def test_navigate_to_parent_keyword(self, dc, ws_tree):
        dc.navigate_directory("backup")
        result = dc.navigate_directory("parent")
        assert Path(result).resolve() == ws_tree.resolve()

    def test_navigate_to_path_with_space(self, dc, ws_tree):
        result = dc.navigate_directory("automation timeline")
        expected = ws_tree / "automation timeline"
        assert Path(result).resolve() == expected.resolve()

    def test_navigate_to_absolute_with_forward_slashes(self, ws_tree):
        ctrl = DirectoryControl()
        path_fwd = str(ws_tree / "backup").replace("\\", "/")
        result = ctrl.navigate_directory(path_fwd)
        assert Path(result).resolve() == (ws_tree / "backup").resolve()

    def test_navigate_to_nonexistent_raises(self, dc):
        with pytest.raises(WorkspaceNotFoundError):
            dc.navigate_directory("does_not_exist")

    def test_navigate_to_file_raises(self, dc):
        with pytest.raises(WorkspaceNotFoundError):
            dc.navigate_directory("test.txt")

    def test_navigate_to_nonexistent_absolute_raises(self, dc):
        with pytest.raises(WorkspaceNotFoundError):
            dc.navigate_directory("Z:\\does_not_exist_99999")

    def test_navigate_preserves_state_on_failure(self, dc, ws_tree):
        """A failed navigate must leave the active directory unchanged."""
        initial = dc.get_active_directory()
        with pytest.raises(WorkspaceNotFoundError):
            dc.navigate_directory("nonexistent_xyz")
        assert dc.get_active_directory() == initial

    def test_navigate_without_workspace_raises_for_relative(self):
        ctrl = DirectoryControl()
        with pytest.raises(NoActiveWorkspaceError):
            ctrl.navigate_directory("backup")

    def test_navigate_absolute_without_workspace_succeeds(self, ws_tree):
        ctrl = DirectoryControl()
        result = ctrl.navigate_directory(str(ws_tree))
        assert Path(result).resolve() == ws_tree.resolve()

    def test_navigate_dotdot_without_workspace_raises(self):
        ctrl = DirectoryControl()
        with pytest.raises(NoActiveWorkspaceError):
            ctrl.navigate_directory("..")


# ===========================================================================
# 2. PreprocessorBrain — NAVIGATE intent detection
# ===========================================================================

class TestPreprocessorNavigateIntentDetection:

    @pytest.mark.parametrize("query", [
        "go to backup",
        "go to D:/AG",
        "navigate to backup",
        "navigate to D:/AG",
        "move into backup",
        "go to backup/pre_preprocessor_migration",
    ])
    def test_navigate_queries_classified_as_directory(self, query):
        b = PreprocessorBrain()
        result = b.process(query)
        assert result.domain == Domain.DIRECTORY, (
            f"[{query}] domain={result.domain!r}, expected DIRECTORY"
        )

    @pytest.mark.parametrize("query", [
        "go up",
        "go back",
        "go to ..",
        "go to parent",
        "navigate to parent",
        "navigate to ..",
        "move to parent",
    ])
    def test_parent_navigation_classified_as_navigate(self, query):
        b = PreprocessorBrain()
        from preprocessor_brain import IntentDetector
        detected = IntentDetector().detect(query)
        assert detected.intent == Intent.NAVIGATE, (
            f"[{query}] detected as {detected.intent!r}, expected NAVIGATE"
        )

    @pytest.mark.parametrize("query", [
        "go to backup",
        "navigate to backup",
        "move into backup",
    ])
    def test_navigate_verb_classified_as_navigate_intent(self, query):
        from preprocessor_brain import IntentDetector
        detected = IntentDetector().detect(query)
        assert detected.intent == Intent.NAVIGATE, (
            f"[{query}] detected as {detected.intent!r}, expected NAVIGATE"
        )


# ===========================================================================
# 3. PreprocessorBrain — NAVIGATE command parsing
# ===========================================================================

class TestPreprocessorNavigateParsing:

    @pytest.mark.parametrize(("query", "expected_target"), [
        ("go to backup", "backup"),
        ("navigate to backup", "backup"),
        ("move into backup", "backup"),
        ("go to pre_preprocessor_migration", "pre_preprocessor_migration"),
        ("go to backup/pre_preprocessor_migration", "backup/pre_preprocessor_migration"),
        ("go to automation timeline", "automation timeline"),
        ('go to "automation timeline"', "automation timeline"),
    ])
    def test_navigate_target_extracted(self, query, expected_target):
        b = PreprocessorBrain()
        from preprocessor_brain import CommandParser
        cmd = CommandParser().parse(Intent.NAVIGATE, query)
        assert cmd.intent == Intent.NAVIGATE
        assert cmd.target == expected_target, (
            f"[{query}] got target={cmd.target!r}, expected {expected_target!r}"
        )

    @pytest.mark.parametrize("query", [
        "go up",
        "go back",
        "go to ..",
        "go to parent",
        "navigate to parent",
        "navigate to ..",
        "move to parent",
    ])
    def test_parent_navigation_target_is_dotdot(self, query):
        from preprocessor_brain import CommandParser
        cmd = CommandParser().parse(Intent.NAVIGATE, query)
        assert cmd.intent == Intent.NAVIGATE
        assert cmd.target == "..", (
            f"[{query}] got target={cmd.target!r}, expected '..'")

    def test_dot_target_stays_current(self):
        from preprocessor_brain import CommandParser
        cmd = CommandParser().parse(Intent.NAVIGATE, "go to .")
        assert cmd.intent == Intent.NAVIGATE
        assert cmd.target == "."

    def test_absolute_windows_path_preserved(self, ws_tree):
        from preprocessor_brain import CommandParser
        path = str(ws_tree).replace("\\", "/")
        cmd = CommandParser().parse(Intent.NAVIGATE, f"go to {path}")
        assert cmd.intent == Intent.NAVIGATE
        # The parsed target should contain the drive letter
        assert ":" in cmd.target

    def test_absolute_path_with_backslash_preserved(self, ws_tree):
        from preprocessor_brain import CommandParser
        path = str(ws_tree)
        cmd = CommandParser().parse(Intent.NAVIGATE, f"go to {path}")
        assert cmd.intent == Intent.NAVIGATE
        assert cmd.target is not None
        assert len(cmd.target) > 1


# ===========================================================================
# 4. PreprocessorBrain — NAVIGATE end-to-end
# ===========================================================================

class TestPreprocessorNavigateEndToEnd:

    def test_go_to_child_dir(self, pb, ws_tree):
        result = pb.process("go to backup")
        assert result.success, f"Expected success; got error={result.error}, meta={result.metadata}"
        assert result.intent == Intent.NAVIGATE
        assert Path(result.result).resolve() == (ws_tree / "backup").resolve()

    def test_navigate_to_child_dir(self, pb, ws_tree):
        result = pb.process("navigate to backup")
        assert result.success
        assert result.intent == Intent.NAVIGATE
        assert Path(result.result).resolve() == (ws_tree / "backup").resolve()

    def test_go_to_multi_segment_relative(self, pb, ws_tree):
        result = pb.process("go to backup/pre_preprocessor_migration")
        assert result.success
        expected = ws_tree / "backup" / "pre_preprocessor_migration"
        assert Path(result.result).resolve() == expected.resolve()

    def test_go_up_from_child(self, pb, ws_tree):
        pb.process("go to backup")
        result = pb.process("go up")
        assert result.success
        assert result.intent == Intent.NAVIGATE
        assert Path(result.result).resolve() == ws_tree.resolve()

    def test_go_back_from_child(self, pb, ws_tree):
        pb.process("go to backup")
        result = pb.process("go back")
        assert result.success
        assert Path(result.result).resolve() == ws_tree.resolve()

    def test_go_to_parent_from_child(self, pb, ws_tree):
        pb.process("go to backup")
        result = pb.process("go to parent")
        assert result.success
        assert Path(result.result).resolve() == ws_tree.resolve()

    def test_navigate_to_parent(self, pb, ws_tree):
        pb.process("go to backup")
        result = pb.process("navigate to parent")
        assert result.success
        assert Path(result.result).resolve() == ws_tree.resolve()

    def test_go_to_dot_stays_in_place(self, pb, ws_tree):
        result = pb.process("go to .")
        assert result.success
        assert Path(result.result).resolve() == ws_tree.resolve()

    def test_go_to_absolute_path(self, pb, ws_tree):
        path = str(ws_tree / "backup").replace("\\", "/")
        result = pb.process(f"go to {path}")
        assert result.success
        assert Path(result.result).resolve() == (ws_tree / "backup").resolve()

    def test_go_to_absolute_path_backslash(self, pb, ws_tree):
        path = str(ws_tree / "backup")
        result = pb.process(f"go to {path}")
        assert result.success
        assert Path(result.result).resolve() == (ws_tree / "backup").resolve()

    def test_go_to_path_with_spaces(self, pb, ws_tree):
        result = pb.process('go to "automation timeline"')
        assert result.success
        assert Path(result.result).resolve() == (ws_tree / "automation timeline").resolve()

    def test_go_to_path_with_spaces_unquoted(self, pb, ws_tree):
        result = pb.process("go to automation timeline")
        assert result.success
        assert Path(result.result).resolve() == (ws_tree / "automation timeline").resolve()

    def test_go_to_nonexistent_returns_failure(self, pb):
        result = pb.process("go to nonexistent_xyz_999")
        assert not result.success
        assert result.error in (DirErrorCode.NOT_FOUND, DirErrorCode.NOT_A_DIRECTORY)

    def test_go_to_file_returns_failure(self, pb):
        result = pb.process("go to test.txt")
        assert not result.success

    def test_failed_navigation_preserves_active_directory(self, pb, ws_tree):
        """Critical: a failed navigate must not clobber the active directory."""
        initial = pb.directory_ops.get_active_directory()
        pb.process("go to nonexistent_xyz_999")
        after = pb.directory_ops.get_active_directory()
        assert initial == after, (
            f"Active directory changed after failed navigation: "
            f"was {initial!r}, now {after!r}"
        )

    def test_failed_navigate_to_file_preserves_state(self, pb, ws_tree):
        initial = pb.directory_ops.get_active_directory()
        pb.process("go to test.txt")
        assert pb.directory_ops.get_active_directory() == initial


# ===========================================================================
# 5. Current-location queries
# ===========================================================================

class TestCurrentLocationQueries:

    @pytest.mark.parametrize("query", [
        "where am I?",
        "what directory am I in?",
        "what folder am I in?",
        "where are you working?",
        "what is the current workspace?",
        "what is my current workspace?",
        "what is the current directory?",
    ])
    def test_location_query_returns_active_directory(self, ws_tree, query):
        ctrl = DirectoryControl()
        ctrl.set_directory(str(ws_tree))
        brain = PreprocessorBrain(directory_control=ctrl)
        result = brain.process(query)
        assert result.success, (
            f"[{query}] failed with error={result.error}, meta={result.metadata}"
        )
        assert result.intent == Intent.CURRENT_DIRECTORY, (
            f"[{query}] wrong intent: {result.intent!r}"
        )
        assert Path(result.result).resolve() == ws_tree.resolve()

    def test_location_query_after_navigation_shows_new_dir(self, pb, ws_tree):
        pb.process("go to backup")
        result = pb.process("where am I?")
        assert result.success
        assert Path(result.result).resolve() == (ws_tree / "backup").resolve()

    def test_location_query_with_no_workspace(self):
        b = PreprocessorBrain()
        result = b.process("where am I?")
        # No workspace set — should return failure with NO_ACTIVE_WORKSPACE
        assert not result.success
        assert result.error == DirErrorCode.NO_ACTIVE_WORKSPACE


# ===========================================================================
# 6. State transition sequences
# ===========================================================================

class TestStateTransitionSequences:

    def test_multi_hop_navigation_and_recovery(self, pb, ws_tree):
        """
        D:\\ws
          ↓ go to backup
        D:\\ws\\backup
          ↓ go to pre_preprocessor_migration
        D:\\ws\\backup\\pre_preprocessor_migration
          ↓ go up (→ ../)
        D:\\ws\\backup
          ↓ go up
        D:\\ws
        """
        def active():
            return Path(pb.directory_ops.get_active_directory()).resolve()

        r1 = pb.process("go to backup")
        assert r1.success
        assert active() == (ws_tree / "backup").resolve()

        r2 = pb.process("go to pre_preprocessor_migration")
        assert r2.success
        assert active() == (ws_tree / "backup" / "pre_preprocessor_migration").resolve()

        r3 = pb.process("go up")
        assert r3.success
        assert active() == (ws_tree / "backup").resolve()

        r4 = pb.process("go up")
        assert r4.success
        assert active() == ws_tree.resolve()

    def test_read_after_navigate_uses_new_location(self, pb, ws_tree):
        """After navigation, a list operation should see the new directory."""
        (ws_tree / "backup" / "notes.txt").write_text("backup notes", encoding="utf-8")

        pb.process("go to backup")
        result = pb.process("list the files")
        assert result.success
        names = {e["name"] for e in result.result}
        # "pre_preprocessor_migration" is a subdir in backup, notes.txt is a file
        assert "notes.txt" in names or "pre_preprocessor_migration" in names

    def test_set_workspace_then_navigate_then_back(self, pb, ws_tree):
        """
        set workspace  →  navigate to child  →  navigate to parent
        The parent should match the original set workspace.
        """
        r1 = pb.process(f"set workspace to {ws_tree}")
        assert r1.success

        r2 = pb.process("go to backup")
        assert r2.success
        assert Path(pb.directory_ops.get_active_directory()).resolve() == (ws_tree / "backup").resolve()

        r3 = pb.process("go up")
        assert r3.success
        assert Path(pb.directory_ops.get_active_directory()).resolve() == ws_tree.resolve()

    def test_absolute_navigation_overrides_relative_chain(self, pb, ws_tree):
        """An absolute path should always override the current position."""
        pb.process("go to backup")
        pb.process("go to pre_preprocessor_migration")
        # Now navigate to absolute root of ws
        path = str(ws_tree).replace("\\", "/")
        r = pb.process(f"go to {path}")
        assert r.success
        assert Path(pb.directory_ops.get_active_directory()).resolve() == ws_tree.resolve()


# ===========================================================================
# 7. NAVIGATE vs READ distinction
# ===========================================================================

class TestNavigateVsRead:

    def test_go_to_classified_as_navigate_not_read(self):
        from preprocessor_brain import IntentDetector
        assert IntentDetector().detect("go to backup").intent == Intent.NAVIGATE

    def test_read_classified_as_read_file_not_navigate(self):
        from preprocessor_brain import IntentDetector
        assert IntentDetector().detect("read backup").intent == Intent.READ_FILE

    def test_navigate_does_not_break_read_after_nav(self, pb, ws_tree):
        (ws_tree / "backup" / "notes.md").write_text("# Notes\n", encoding="utf-8")
        pb.process("go to backup")
        result = pb.process("read notes.md")
        assert result.success
        assert result.intent == Intent.READ_FILE
        assert "Notes" in result.result


# ===========================================================================
# 8. NAVIGATE vs SET_WORKSPACE distinction
# ===========================================================================

class TestNavigateVsSetWorkspace:

    def test_set_workspace_classified_as_switch_directory(self):
        from preprocessor_brain import IntentDetector
        assert IntentDetector().detect("set workspace to D:/AG").intent == Intent.SWITCH_DIRECTORY

    def test_go_to_classified_as_navigate(self):
        from preprocessor_brain import IntentDetector
        assert IntentDetector().detect("go to D:/AG").intent == Intent.NAVIGATE

    def test_both_use_same_state(self, pb, ws_tree):
        """
        set workspace and navigate both update the same _active_directory.
        """
        r1 = pb.process(f"set workspace to {ws_tree}")
        assert r1.success
        r2 = pb.process("go to backup")
        assert r2.success
        result = pb.process("where am I?")
        assert Path(result.result).resolve() == (ws_tree / "backup").resolve()


# ===========================================================================
# 9. IntentRouter navigation routing
# ===========================================================================

class TestIntentRouterNavigation:

    @pytest.mark.parametrize(("query", "expected_sub_op"), [
        ("go to backup", "navigate"),
        ("go to D:/AG", "navigate"),
        ("navigate to backup", "navigate"),
        ("move into backup", "navigate"),
    ])
    def test_navigate_queries_route_to_directory_op_navigate(self, query, expected_sub_op):
        result = route_intent(query)
        assert result.intent == RouterIntent.DIRECTORY_OP
        assert result.sub_op == expected_sub_op, (
            f"[{query}] got sub_op={result.sub_op!r}"
        )

    @pytest.mark.parametrize("query", [
        "go back",
        "go up",
        "go to parent",
        "go to ..",
        "navigate to parent",
        "navigate to ..",
        "move to parent",
        "move to ..",
    ])
    def test_parent_navigation_routes_to_go_back(self, query):
        result = route_intent(query)
        assert result.intent == RouterIntent.DIRECTORY_OP
        assert result.sub_op == "go_back", (
            f"[{query}] got sub_op={result.sub_op!r}"
        )

    @pytest.mark.parametrize("query", [
        "where am I?",
        "what directory am I in?",
        "where are you working?",
        "what is the current workspace?",
        "what is my current workspace?",
    ])
    def test_location_queries_route_to_local_state_query(self, query):
        normalized = query.lower().strip().rstrip("?!. ")
        result = route_intent(normalized)
        assert result.intent == RouterIntent.LOCAL_STATE_QUERY, (
            f"[{query}] got intent={result.intent!r}"
        )


# ===========================================================================
# 10. Windows path variant handling
# ===========================================================================

class TestWindowsPathVariants:

    def test_absolute_forward_slash_path(self, dc, ws_tree):
        backup = str(ws_tree / "backup").replace("\\", "/")
        result = dc.navigate_directory(backup)
        assert Path(result).resolve() == (ws_tree / "backup").resolve()

    def test_absolute_backslash_path(self, dc, ws_tree):
        backup = str(ws_tree / "backup")
        result = dc.navigate_directory(backup)
        assert Path(result).resolve() == (ws_tree / "backup").resolve()

    def test_relative_forward_slash_multisegment(self, dc, ws_tree):
        result = dc.navigate_directory("backup/pre_preprocessor_migration")
        expected = ws_tree / "backup" / "pre_preprocessor_migration"
        assert Path(result).resolve() == expected.resolve()

    def test_relative_backslash_multisegment(self, dc, ws_tree):
        result = dc.navigate_directory("backup\\pre_preprocessor_migration")
        expected = ws_tree / "backup" / "pre_preprocessor_migration"
        assert Path(result).resolve() == expected.resolve()

    def test_preprocessor_handles_forward_slash_absolute(self, pb, ws_tree):
        path = str(ws_tree / "backup").replace("\\", "/")
        result = pb.process(f"go to {path}")
        assert result.success


# ===========================================================================
# 11. Invalid target handling
# ===========================================================================

class TestInvalidTargetHandling:

    def test_nonexistent_directory_name(self, pb):
        result = pb.process("go to nonexistent_xyz_999")
        assert not result.success
        assert result.intent == Intent.NAVIGATE

    def test_file_as_navigation_target(self, pb):
        result = pb.process("go to test.txt")
        assert not result.success

    def test_nonexistent_absolute_path(self, pb):
        result = pb.process("go to Z:\\does_not_exist_99999")
        assert not result.success

    def test_empty_target_after_go_to(self, pb):
        result = pb.process("go to")
        # Should either be incomplete (clarification) or an error — never success
        assert not result.success

    def test_active_directory_unchanged_after_nonexistent_navigate(self, pb, ws_tree):
        initial = pb.directory_ops.get_active_directory()
        pb.process("go to Z:\\does_not_exist_99999")
        assert pb.directory_ops.get_active_directory() == initial

    def test_active_directory_unchanged_after_file_navigate(self, pb, ws_tree):
        initial = pb.directory_ops.get_active_directory()
        pb.process("go to test.txt")
        assert pb.directory_ops.get_active_directory() == initial
