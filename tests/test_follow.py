import tempfile
import unittest
from pathlib import Path

from test_review import command, record, write

from branchline import git
from branchline.review import make_note, project_file_note


class FollowTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        command(self.root, "init", "-q", "-b", "main")
        write(self.root, "settings", "top\nlimit = 1\nbottom\n")
        record(self.root, "Initial settings")
        command(self.root, "switch", "-qc", "feature")

    def snapshot(self, group=None, path="settings"):
        repo = git.open_repo(self.root)
        c = git.compare(repo, repo.checkout, git.WORKTREE) if group else git.compare(repo, *repo.initial)
        file = next(f for f in c.files if f.path == path and (not group or f.group == group))
        return c, file, git.patch(repo, c, file)

    def project(self, note, group=None, path="settings"):
        _, file, lines = self.snapshot(group, path)
        return project_file_note(file, lines, note)

    def test_partial_stage_then_commit_preserves_original_anchor(self):
        write(self.root, "settings", "top\nlimit = 2\nbottom\n")
        c, file, lines = self.snapshot("Unstaged")
        selected = [line for line in lines if line.kind in "+-"]
        note = make_note(c, file, selected, "unified", "Why double this?", diff_lines=lines)
        # Index and working file have different changes to the same path.
        write(self.root, "settings", "header\ntop\nlimit = 2\nbottom\n")
        command(self.root, "add", "settings")
        write(self.root, "settings", "header\ntop\nlimit = 2\nbottom\nfooter\n")
        staged = self.project(note, "Staged")
        self.assertEqual((staged["old"], staged["new"]), ([2, 2], [3, 3]))
        self.assertIsNone(self.project(note, "Unstaged"))
        command(self.root, "commit", "-qm", "Raise limit")
        projected = self.project(note)
        self.assertEqual((projected["old"], projected["new"]), ([2, 2], [3, 3]))
        self.assertEqual((note["old"], note["new"], note["group"]), ([2, 2], [2, 2], "Unstaged"))

    def test_repeated_code_needs_same_blob_or_distinguishing_context(self):
        write(self.root, "new", "first\nrepeat()\nsecond\nrepeat()\nthird\n")
        c, file, lines = self.snapshot("Untracked", "new")
        selected = [line for line in lines if line.new == 4]
        earlier_note = make_note(c, file, selected, "new", "Keep this one")
        note = make_note(c, file, selected, "new", "Keep this one", diff_lines=lines)
        command(self.root, "add", "new")
        self.assertEqual(self.project(earlier_note, "Staged", "new")["new"], [4, 4])
        write(self.root, "new", "header\nfirst\nrepeat()\nsecond\nrepeat()\nthird\n")
        command(self.root, "add", "new")
        self.assertIsNone(self.project(earlier_note, "Staged", "new"))
        self.assertEqual(self.project(note, "Staged", "new")["new"], [5, 5])
        write(self.root, "new", ("first\nrepeat()\nsecond\nrepeat()\nthird\n") * 2)
        command(self.root, "add", "new")
        self.assertIsNone(self.project(note, "Staged", "new"))
        # Losing the original occurrence must not silently relocate its note
        # to one surviving copy with entirely different surroundings.
        write(self.root, "new", "different block\nrepeat()\nunrelated end\n")
        command(self.root, "add", "new")
        self.assertIsNone(self.project(note, "Staged", "new"))

    def test_removed_side_follows_rename_and_never_matches_additions(self):
        original = "top\nlimit = 1\nbottom\n" + "".join(f"line {i}\n" for i in range(25))
        write(self.root, "settings", original)
        record(self.root, "Add other settings")
        command(self.root, "branch", "-f", "main", "HEAD")
        write(self.root, "settings", original.replace("limit = 1\n", ""))
        c, file, lines = self.snapshot("Unstaged")
        old = [line for line in lines if line.kind == "-"]
        note = make_note(c, file, old, "old", "Document the removal", diff_lines=lines)
        command(self.root, "mv", "settings", "tuning")
        record(self.root, "Move setting and remove old limit")
        projected = self.project(note, path="tuning")
        self.assertEqual((projected["old"], projected["new"]), ([2, 2], []))
        write(self.root, "tuning", original)
        self.assertIsNone(self.project(note, "Unstaged", "tuning"))
