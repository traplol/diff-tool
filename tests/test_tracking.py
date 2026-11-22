import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_review import command, record, write

from branchline import git
from branchline.review import make_note
from branchline.tracking import locate_notes


class StackTrackingTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        command(self.root, "init", "-q", "-b", "main")
        write(self.root, "settings", "count = 1\n")
        record(self.root, "Base")
        command(self.root, "switch", "-qc", "middle")
        write(self.root, "middle.txt", "middle\n")
        record(self.root, "Middle")
        command(self.root, "switch", "-qc", "top")
        write(self.root, "top.txt", "top\n")
        record(self.root, "Top")
        command(self.root, "switch", "middle")
        self.stack = ["refs/heads/" + b for b in ("main", "middle", "top")]

    def local_note(self):
        repo = git.open_repo(self.root)
        c = git.compare(repo, repo.checkout, git.WORKTREE)
        f = next(f for f in c.files if f.path == "settings")
        lines = git.patch(repo, c, f)
        return dict(
            make_note(
                c,
                f,
                [line for line in lines if line.kind == "+"],
                "new",
                "Explain the scaling",
                diff_lines=lines,
            ),
            id=7,
        )

    def locations(self, note):
        repo = git.open_repo(self.root)
        primary = git.compare(repo, self.stack[0], self.stack[-1])
        return {(l["right"], l["left"]): l for l in locate_notes(repo, self.stack, primary, [note])[note["id"]]}

    def test_middle_branch_note_follows_its_commit_only_after_descendant_inherits_it(self):
        main, middle, top = self.stack
        write(self.root, "settings", "count = 2\n")
        note = self.local_note()
        command(self.root, "add", "settings")
        self.assertEqual(self.locations(note)[git.WORKTREE, middle]["group"], "Staged")
        command(self.root, "commit", "-qm", "Double count")
        self.assertEqual(set(self.locations(note)), {(middle, main)})
        command(self.root, "switch", "top")
        command(self.root, "rebase", "middle")
        found = self.locations(note)
        self.assertEqual(set(found), {(middle, main), (top, main)})
        self.assertEqual(found[top, main]["new"], [1, 1])
        # Switching to a stack that excludes the source branch must hide its note.
        repo = git.open_repo(self.root)
        primary = git.compare(repo, main, top)
        with patch("branchline.tracking.git.compare", side_effect=AssertionError("unnecessary Git read")):
            self.assertEqual(locate_notes(repo, [main, top], primary, [note]), {})

    def test_identical_change_on_different_branch_and_unrelated_commit_do_not_adopt_note(self):
        middle = self.stack[1]
        command(self.root, "switch", "top")
        write(self.root, "settings", "count = 2\n")
        record(self.root, "Independently increase count")
        command(self.root, "switch", "middle")
        write(self.root, "settings", "count = 2\n")
        note = self.local_note()
        self.assertEqual(set(self.locations(note)), {(git.WORKTREE, middle)})
        write(self.root, "settings", "count = 1\nother = 8\n")
        record(self.root, "Change a different setting")
        command(self.root, "switch", "top")
        # Inherit the unrelated source commit while preserving top's own change.
        command(self.root, "merge", "-s", "ours", "--no-edit", "middle")
        self.assertEqual(self.locations(note), {})

    def test_applied_replacement_can_follow_a_committed_origin(self):
        main, middle = self.stack[:2]
        write(self.root, "settings", "count = 8\n")
        replacement = self.local_note()
        note = dict(replacement, left=main, right=middle, applied_anchor=replacement, id=99)
        found = self.locations(note)
        self.assertTrue(found[git.WORKTREE, middle]["applied_text"])
        record(self.root, "Apply proposed setting")
        found = self.locations(note)
        self.assertEqual(set(found), {(middle, main)})
        self.assertTrue(found[middle, main]["applied_text"])

    def test_recreated_branch_only_accepts_exact_local_snapshots(self):
        write(self.root, "settings", "count = 2\n")
        note = self.local_note()
        write(self.root, "settings", "count = 1\n")
        command(self.root, "switch", "--orphan", "separate")
        write(self.root, "settings", "count = 1\n")
        record(self.root, "Different repository history")
        command(self.root, "branch", "-f", "middle", "HEAD")
        command(self.root, "switch", "middle")
        write(self.root, "settings", "count = 2\n")
        repo = git.open_repo(self.root)

        def current():
            c = git.compare(repo, repo.checkout, git.WORKTREE)
            return locate_notes(repo, [git.EMPTY, repo.checkout], c, [note])[7]

        self.assertEqual([dest["group"] for dest in current()], ["Unstaged"])
        command(self.root, "add", "settings")
        self.assertEqual(current(), [])

    def test_applied_deletion_follows_the_removed_side(self):
        main, middle = self.stack[:2]
        write(self.root, "settings", "count = 1\nreport = True\n")
        record(self.root, "Add reporting")
        repo = git.open_repo(self.root)
        original = git.compare(repo, main, middle)
        file = next(f for f in original.files if f.path == "settings")
        first = next(line for line in git.patch(repo, original, file) if line.new == 1)
        note = dict(make_note(original, file, [first], "new", "Remove the default"), id=9)
        write(self.root, "settings", "report = True\n")
        local = git.compare(repo, middle, git.WORKTREE)
        removed = local.files[0]
        deletion = next(line for line in git.patch(repo, local, removed) if line.kind == "-")
        note["applied_anchor"] = make_note(local, removed, [deletion], "old", "")
        command(self.root, "add", "settings")
        staged = self.locations(note)[git.WORKTREE, middle]
        self.assertEqual(
            (staged["group"], staged["old"], staged["new"], staged["applied_text"]),
            ("Staged", [1, 1], [], True),
        )
        command(self.root, "commit", "-qm", "Drop the default")
        committed = self.locations(note)[middle, main]
        self.assertEqual((committed["old"], committed["new"], committed["applied_text"]), ([1, 1], [], True))
