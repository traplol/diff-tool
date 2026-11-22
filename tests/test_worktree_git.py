import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_review import command, record, write

from branchline import git


class WorkingTreeGitTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        command(self.root, "init", "-qb", "main")

    def read(self):
        repo = git.open_repo(self.root)
        comparison = git.compare(repo, repo.checkout, git.WORKTREE)
        return repo, comparison, {(f.group, f.path): f for f in comparison.files}

    def test_partially_staged_immutable_read_only_snapshots(self):
        write(self.root, "code", "original\n")
        write(self.root, ".gitignore", "ignored/\n")
        record(self.root, "Start")
        write(self.root, "code", "staged\n")
        command(self.root, "add", "code")
        write(self.root, "code", "on disk\n")
        write(self.root, "-", "untracked\n")
        write(self.root, "ignored/tmp", "skip\n")

        index = self.root / ".git/index"
        original_index = index.read_bytes()
        objects = self.root / ".git/objects"
        original_objects = set(objects.rglob("*"))
        repo, c, files = self.read()
        self.assertEqual(set(files), {("Staged", "code"), ("Unstaged", "code"), ("Untracked", "-")})
        staged, unstaged, untracked = c.files
        self.assertEqual(staged.oid, unstaged.old_oid)
        self.assertNotEqual(staged.oid, unstaged.oid)
        self.assertEqual(c.left_tip, command(self.root, "rev-parse", "HEAD").decode().strip())
        self.assertEqual(original_index, index.read_bytes())
        self.assertEqual(original_objects, set(objects.rglob("*")))

        write(self.root, "code", "later edit\n")
        (self.root / "-").unlink()
        command(self.root, "add", "code")
        for change, expected in (
            (staged, ["original", "staged"]),
            (unstaged, ["staged", "on disk"]),
            (untracked, ["untracked"]),
        ):
            self.assertEqual([line.text for line in git.patch(repo, c, change) if line.kind in "+-"], expected)
        self.assertNotEqual(self.read()[1].head, c.head)

    def test_unborn_untracked_and_staged_then_detached_and_switched_checkout(self):
        write(self.root, "staged", "first\n")
        command(self.root, "add", "staged")
        write(self.root, "new [üni]", "second\n")
        repo, c, files = self.read()
        self.assertEqual(repo.checkout, "refs/heads/main")
        self.assertEqual(c.base, repo.refs[git.EMPTY])
        self.assertEqual(set(files), {("Staged", "staged"), ("Untracked", "new [üni]")})
        record(self.root, "Initial commit")
        with self.assertRaisesRegex(git.GitError, "Refresh"):
            git.compare(repo, repo.checkout, git.WORKTREE)
        repo, _, files = self.read()
        self.assertFalse(files)
        command(self.root, "switch", "-qc", "same-commit")
        with self.assertRaisesRegex(git.GitError, "Refresh"):
            git.compare(repo, repo.checkout, git.WORKTREE)
        command(self.root, "switch", "--detach")
        repo, c, _ = self.read()
        self.assertEqual(repo.checkout, "HEAD@" + c.base)
        command(self.root, "switch", "--orphan", "clean-slate")
        repo, c, _ = self.read()
        self.assertEqual(repo.checkout, "refs/heads/clean-slate")
        self.assertTrue(repo.initial)
        self.assertEqual(c.left_tip, repo.refs[git.EMPTY])

    def test_staged_rename_deletion_file_type_and_binary(self):
        write(self.root, "before", "renamed\n")
        write(self.root, "deleted", "gone\n")
        write(self.root, "type", "regular\n")
        record(self.root, "Base")
        command(self.root, "mv", "before", "after")
        (self.root / "deleted").unlink()
        (self.root / "image.bin").write_bytes(b"\0binary")
        (self.root / "empty").touch()
        if os.name != "nt":
            (self.root / "type").unlink()
            (self.root / "type").symlink_to("after")
            (self.root / "link-to-dir").symlink_to(".")
        repo, c, files = self.read()
        self.assertEqual(files["Staged", "after"].old, "before")
        self.assertEqual(files["Staged", "after"].status, "R")
        deleted = files["Unstaged", "deleted"]
        self.assertEqual(deleted.status, "D")
        self.assertEqual(git.patch(repo, c, deleted)[-1].text, "gone")
        self.assertTrue(files["Untracked", "image.bin"].binary)
        self.assertNotEqual(files["Untracked", "image.bin"].oid, files["Untracked", "empty"].oid)
        self.assertEqual(files["Untracked", "empty"].added, 0)
        if os.name != "nt":
            link = files["Untracked", "link-to-dir"]
            self.assertEqual(link.mode, "120000")
            self.assertEqual([l.text for l in git.patch(repo, c, link) if l.kind == "+"], ["."])
            changed_type = files["Unstaged", "type"]
            self.assertEqual(changed_type.mode, "120000")
            self.assertEqual(
                [l.text for l in git.patch(repo, c, changed_type) if l.kind in "+-"], ["regular", "after"]
            )

    def test_untracked_nested_repository_before_and_after_first_commit(self):
        nested = self.root / "nested"
        nested.mkdir()
        command(nested, "init", "-qb", "inside")
        write(nested, "inner.txt", "nested contents\n")
        repo, unborn, files = self.read()
        self.assertEqual(set(files), {("Untracked", "nested")})
        change = files["Untracked", "nested"]
        self.assertEqual((change.mode, change.oid), ("160000", "0" * len(unborn.base)))
        self.assertEqual(git.patch(repo, unborn, change), [])
        record(nested, "First nested commit")
        _, committed, files = self.read()
        self.assertEqual(set(files), {("Untracked", "nested")})
        self.assertEqual(
            files["Untracked", "nested"].oid, command(nested, "rev-parse", "HEAD").decode().strip()
        )
        self.assertNotEqual(unborn.head, committed.head)

    def test_scoped_worktree_only_reads_requested_untracked_files(self):
        write(self.root, "tracked", "base\n")
        record(self.root, "Base")
        write(self.root, "tracked", "modified\n")
        write(self.root, "new[1]", "reviewed\n")
        write(self.root, "other", "unrelated\n")
        repo = git.open_repo(self.root)
        with patch.object(git, "local_changes", wraps=git.local_changes) as reads:
            scoped = git.working_tree(repo, repo.checkout, untracked_paths={"new[1]"})
        self.assertEqual(
            [(f.group, f.path) for f in scoped.files], [("Unstaged", "tracked"), ("Untracked", "new[1]")]
        )
        self.assertEqual([c.args[-1] for c in reads.call_args_list if c.args[1] == "Untracked"], ["./new[1]"])
        self.assertEqual(
            [f.path for f in git.working_tree(repo, repo.checkout, untracked_paths=set()).files], ["tracked"]
        )

    def test_merge_conflict_keeps_other_files_reviewable(self):
        write(self.root, "conflict.txt", "base\n")
        record(self.root, "Base")
        command(self.root, "switch", "-qc", "other")
        write(self.root, "conflict.txt", "theirs\n")
        record(self.root, "Other side")
        command(self.root, "switch", "main")
        write(self.root, "conflict.txt", "ours\n")
        record(self.root, "Our side")
        with self.assertRaises(subprocess.CalledProcessError):
            command(self.root, "merge", "other")
        write(self.root, "new", "staged\n")
        command(self.root, "add", "new")
        repo, c, files = self.read()
        self.assertEqual(set(files), {("Unstaged", "conflict.txt"), ("Staged", "new")})
        f = files["Unstaged", "conflict.txt"]
        self.assertEqual(f.status, "U")
        self.assertIn("<<<<<<< HEAD", [l.text for l in git.patch(repo, c, f) if l.kind == "+"])
