import errno
import ntpath
import os
import stat
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path, PureWindowsPath
from unittest.mock import patch

from test_review import command, record

from branchline import git
from branchline.suggestions import SuggestionError, _working_path, apply_suggestion


class ApplySuggestionTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "repo"
        self.root.mkdir()
        command(self.root, "init", "-q", "-b", "main")
        self.file = self.root / "source.txt"
        self.file.write_bytes(b"a\r\nb\r\nc\r\nd")
        record(self.root, "Add original file")
        self.repo = git.open_repo(self.root)

    def apply(self, first, last, expected, replacement, **options):
        if "snapshot_oid" not in options:
            options["snapshot_oid"] = (
                command(self.root, "hash-object", "--no-filters", self.file.name).decode().strip()
            )
        return apply_suggestion(self.repo, self.file.name, first, last, expected, replacement, **options)

    def test_multiline_replacement_preserves_working_edits_line_endings_and_index(self):
        self.file.write_bytes(b"staged change\r\nb\r\nc\r\nd")
        command(self.root, "add", "source.txt")
        staged = command(self.root, "show", ":source.txt")
        staged_diff = command(self.root, "diff", "--cached")
        self.file.write_bytes(b"local edit\nb\r\nc\r\nd")
        if os.name != "nt":
            self.file.chmod(0o751)
        mode = stat.S_IMODE(self.file.stat().st_mode)
        applied_oid = self.apply(2, 3, "b\nc", "new\nextra\nlast")
        self.assertEqual(self.file.read_bytes(), b"local edit\nnew\r\nextra\r\nlast\r\nd")
        self.assertEqual(
            applied_oid, command(self.root, "hash-object", "--no-filters", "source.txt").decode().strip()
        )
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), mode)
        self.assertEqual(command(self.root, "show", ":source.txt"), staged)
        self.assertEqual(command(self.root, "diff", "--cached"), staged_diff)
        self.assertEqual(command(self.root, "rev-list", "--count", "HEAD").strip(), b"1")

    def test_deletion_and_replacement_preserve_eof_convention(self):
        self.apply(4, 4, "d", "x\ny")
        self.assertEqual(self.file.read_bytes(), b"a\r\nb\r\nc\r\nx\r\ny")
        self.apply(4, 5, "x\ny", "")
        self.assertEqual(self.file.read_bytes(), b"a\r\nb\r\nc")
        self.file.write_bytes(b"a\r\nb\r\n")
        self.apply(2, 2, "b", "")
        self.assertEqual(self.file.read_bytes(), b"a\r\n")
        self.apply(1, 1, "a", "")
        self.assertEqual(self.file.read_bytes(), b"")

    def test_stale_selection_and_unverified_duplicate_do_not_change_file(self):
        original = b"inserted\nx\ny\nx\ny\nend\n"
        self.file.write_bytes(original)
        for first, last, expected in ((1, 2, "x\ny"), (0, 0, "inserted"), (2, 12, "x")):
            with self.subTest(first=first, last=last), self.assertRaises(SuggestionError):
                self.apply(first, last, expected, "changed")
            self.assertEqual(self.file.read_bytes(), original)
        with self.assertRaises(SuggestionError):
            self.apply(2, 3, "x\ny", "changed", snapshot_oid=None)
        self.assertEqual(self.file.read_bytes(), original)
        oid = command(self.root, "hash-object", "source.txt").decode().strip()
        self.apply(4, 5, "x\ny", "changed", snapshot_oid=oid)
        self.assertEqual(self.file.read_bytes(), b"inserted\nx\ny\nchanged\nend\n")

    def test_stale_suggestion_cannot_edit_another_function_at_the_same_line(self):
        self.file.write_bytes(b"def read_timeout():\n    return 30\n\ndef write_timeout():\n    return 30\n")
        record(self.root, "Add both timeout settings")
        reviewed = command(self.root, "rev-parse", "HEAD:source.txt").decode().strip()
        current = b"def write_timeout():\n    return 30\n"
        self.file.write_bytes(current)
        with self.assertRaisesRegex(SuggestionError, "working.tree"):
            self.apply(2, 2, "    return 30", "    return 15", snapshot_oid=reviewed)
        self.assertEqual(self.file.read_bytes(), current)

    def test_apply_verifies_reviewed_context_and_keeps_unrelated_local_edits(self):
        self.file.write_bytes(b"def read_timeout():\n    return 30\n\nlimit = 32\n")
        record(self.root, "Add timeout setting")
        reviewed = command(self.root, "rev-parse", "HEAD:source.txt").decode().strip()
        current = b"# local header\n" + self.file.read_bytes().replace(b"32", b"64")
        self.file.write_bytes(current)
        self.apply(3, 3, "    return 30", "    return 15", snapshot_oid=reviewed, reviewed_first=2)
        self.assertEqual(self.file.read_bytes(), current.replace(b"30", b"15"))

    def test_apply_requires_fresh_review_if_only_matching_text_survives(self):
        self.file.write_bytes(b"def original():\n    return 30\n")
        reviewed = command(self.root, "hash-object", "--no-filters", "source.txt").decode().strip()
        current = b"def unrelated():\n    return 30\n"
        self.file.write_bytes(current)
        with self.assertRaisesRegex(SuggestionError, "working.tree"):
            self.apply(2, 2, "    return 30", "    return 15", snapshot_oid=reviewed)
        self.assertEqual(self.file.read_bytes(), current)

    def test_windows_path_validation_uses_the_available_runtime_api(self):
        legacy = (
            patch.object(PureWindowsPath, "is_reserved", side_effect=AttributeError, create=True)
            if hasattr(ntpath, "isreserved")
            else nullcontext()
        )
        with patch("branchline.suggestions.os.name", "nt"), legacy:
            self.assertEqual(_working_path(self.root, "source.txt"), self.file)
            for path in ("NUL.txt", "COM1", "CONIN$", "dir/source.", "source.txt:stream", "dir\\file"):
                with self.subTest(path=path), self.assertRaises(SuggestionError):
                    _working_path(self.root, path)

    def test_apply_refuses_to_break_hard_links(self):
        alias = self.root / "linked.txt"
        os.link(self.file, alias)
        before = self.file.read_bytes()
        with self.assertRaisesRegex(SuggestionError, "hard link"):
            self.apply(2, 2, "b", "new")
        self.assertTrue(alias.samefile(self.file))
        self.assertEqual(self.file.read_bytes(), before)

    @unittest.skipUnless(hasattr(os, "setxattr"), "requires extended attributes")
    def test_apply_preserves_extended_attributes_and_fails_closed_on_copy_error(self):
        try:
            os.setxattr(self.file, "user.review", b"metadata")
        except OSError as error:
            if error.errno in (errno.ENOTSUP, errno.EPERM):
                self.skipTest("test filesystem lacks user extended attributes")
            raise
        self.apply(2, 2, "b", "new")
        self.assertEqual(os.getxattr(self.file, "user.review"), b"metadata")
        before = self.file.read_bytes()
        with (
            patch("branchline.suggestions.os.setxattr", side_effect=PermissionError("attribute denied")),
            self.assertRaises(SuggestionError),
        ):
            self.apply(2, 2, "new", "another")
        self.assertEqual(self.file.read_bytes(), before)
        self.assertEqual(os.getxattr(self.file, "user.review"), b"metadata")
        self.assertFalse(list(self.root.glob(".branchline-*")))

    @unittest.skipUnless(os.name == "nt", "requires NTFS named streams")
    def test_apply_preserves_windows_named_stream(self):
        self.file = self.file.rename(self.root / "build.cmd")
        stream = Path(str(self.file) + ":review")
        stream.write_bytes(b"metadata")
        original_unlink = Path.unlink

        def sharing_violation(path, *args, **kwargs):
            if path.name.endswith(".original"):
                raise PermissionError("backup open in another process")
            return original_unlink(path, *args, **kwargs)

        with (
            patch.object(Path, "unlink", sharing_violation),
            self.assertLogs("branchline.suggestions", "WARNING"),
        ):
            result = self.apply(2, 2, "b", "new")
        expected_oid = command(self.root, "hash-object", "--no-filters", self.file.name).decode().strip()
        self.assertEqual(result, expected_oid)
        self.assertEqual(stream.read_bytes(), b"metadata")

    def test_reject_nontext_files_and_paths_outside_the_working_tree(self):
        for raw in (b"before\x00\na\n", b"bad\xff\na\n"):
            self.file.write_bytes(raw)
            with self.assertRaises(SuggestionError):
                self.apply(2, 2, "a", "b")
            self.assertEqual(self.file.read_bytes(), raw)
        for name in (
            ".git/HEAD",
            "../target",
            "/outside",
            "C:\\file",
            "source.txt/../source.txt",
            "",
            "missing",
        ):
            with self.subTest(name=name), self.assertRaises(SuggestionError):
                apply_suggestion(self.repo, name, 1, 1, "a", "b")

    @unittest.skipIf(os.name == "nt", "creating links requires Windows developer mode or elevated privileges")
    def test_symlinks_and_nonregular_files(self):
        outside = self.root.parent / "outside"
        outside.mkdir()
        target = outside / "target"
        target.write_text("a\n")
        (self.root / "link").symlink_to(target)
        (self.root / "directory").symlink_to(outside)
        os.mkfifo(self.root / "pipe")
        for name in ("link", "directory/target", "pipe"):
            with self.subTest(name=name), self.assertRaises(SuggestionError):
                apply_suggestion(self.repo, name, 1, 1, "a", "b")
        self.assertEqual(target.read_bytes(), b"a\n")

    def test_reject_editor_save_while_preparing_replacement(self):
        def concurrent_save(root, path):
            if list(root.glob(".branchline-*")):
                self.file.write_bytes(b"a\r\nb\r\nc\r\nother edit")
            return _working_path(root, path)

        with patch("branchline.suggestions._working_path", concurrent_save), self.assertRaises(SuggestionError):
            self.apply(2, 2, "b", "suggested")
        self.assertEqual(self.file.read_bytes(), b"a\r\nb\r\nc\r\nother edit")
        self.assertFalse(list(self.root.glob(".branchline-*")))
