import tempfile
import unittest
from pathlib import Path

from test_review import command, fixture, record, write

from branchline import git
from branchline.review import Store, file_key, make_note, markdown, note_matches_file


class WorkingTreeNotesTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.repo = fixture(Path(directory.name) / "relay")
        self.store = Store(Path(directory.name) / "state")
        self.addCleanup(self.store.db.close)

    def snapshot(self):
        c = git.compare(self.repo, self.repo.checkout, git.WORKTREE)
        files = {(f.group, f.path): f for f in c.files}
        return c, files

    def test_partially_staged_anchors_and_viewed_survive_unrelated_edits(self):
        path = "config.toml"
        write(self.repo.root, path, "capacity = 512\n")
        command(self.repo.root, "add", path)
        write(self.repo.root, path, "capacity = 1024\n")
        c, files = self.snapshot()
        staged = files["Staged", path]
        unstaged = files["Unstaged", path]
        saved = []
        for file in (staged, unstaged):
            new_line = next(line for line in git.patch(self.repo, c, file) if line.kind == "+")
            note = make_note(c, file, [new_line], "new", f"Check {new_line.text}")
            self.store.save(self.repo, note)
            saved.append(note)
        self.store.set_viewed(self.repo, c, staged, True)
        self.assertEqual(self.store.viewed(self.repo, c), {file_key(staged)})
        self.store.set_viewed(self.repo, c, unstaged, True)

        write(self.repo.root, "unrelated.md", "# Draft\n")
        refreshed, files = self.snapshot()
        self.assertNotEqual(c.head, refreshed.head)
        for note in saved:
            self.assertTrue(note_matches_file(refreshed, files[note["group"], path], note))
        self.assertFalse(note_matches_file(refreshed, files["Staged", path], saved[1]))
        self.assertEqual(self.store.viewed(self.repo, refreshed), {file_key(staged), file_key(unstaged)})

        write(self.repo.root, path, "capacity = 2048\n")
        edited, files = self.snapshot()
        self.assertTrue(note_matches_file(edited, files["Staged", path], saved[0]))
        self.assertFalse(note_matches_file(edited, files["Unstaged", path], saved[1]))
        self.assertEqual(self.store.viewed(self.repo, edited), {file_key(staged)})
        self.store.set_viewed(self.repo, edited, files["Staged", path], False)
        self.assertEqual(self.store.viewed(self.repo, edited), set())
        record(self.repo.root, "Commit revised settings")
        notes = self.store.notes(git.open_repo(self.repo.root))
        report = markdown(self.repo, self.repo.initial, notes)
        self.assertIn("Branch stack:", report)
        for note in notes:
            self.assertIn(f"Working tree: feature/cache-metrics · {note['group']}", report)
            self.assertIn(note["excerpt"], report)
            self.assertIn(note["body"], report)
        self.assertIn(f"Checkout base: {c.left_tip}", report)
        self.assertIn(f"Working tree snapshot: {c.head}", report)

    def test_export_before_first_commit(self):
        root = self.repo.root.parent / "new"
        root.mkdir()
        command(root, "init", "-q", "-b", "main")
        write(root, "plan.md", "Review before publishing\n")
        repo = git.open_repo(root)
        c = git.compare(repo, repo.checkout, git.WORKTREE)
        (file,) = c.files
        note = make_note(c, file, [], "file", "Keep this private until launch.")
        report = markdown(repo, repo.initial, [note])
        self.assertIn("Scope: working tree", report)
        self.assertIn("Working tree: main · Untracked", report)
        self.assertIn("Lines: Whole file", report)
