import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from branchline.review import ReviewConflict, Store


class ResolutionStoreTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.repo = SimpleNamespace(root=self.directory / "checkout")

    def open_store(self):
        store = Store(self.directory)
        self.addCleanup(store.db.close)
        return store

    def test_legacy_comment_survives_migration_and_reopening_the_database(self):
        note = {"body": "Check timeout", "new": [17, 19], "head": "previous-tip"}
        legacy = sqlite3.connect(self.directory / "reviews.sqlite3")
        with legacy:
            legacy.execute(
                "CREATE TABLE notes (id INTEGER PRIMARY KEY, repo BLOB NOT NULL, data TEXT NOT NULL)"
            )
            legacy.execute("INSERT INTO notes VALUES (37,?,?)", (os.fsencode(self.repo.root), json.dumps(note)))
        legacy.close()

        store = self.open_store()
        self.assertEqual(store.notes(self.repo), [dict(note, id=37, resolved=False)])
        self.assertTrue(store.set_resolved(self.repo, 37, True))
        reopened = self.open_store()
        self.assertEqual(reopened.notes(self.repo), [dict(note, id=37, resolved=True)])
        self.assertTrue(reopened.set_resolved(self.repo, 37, False))
        self.assertEqual(store.notes(self.repo), [dict(note, id=37, resolved=False)])

    def test_independent_edits_and_apply_receipt_preserve_each_other_and_resolution(self):
        editor = self.open_store()
        reviewer = self.open_store()
        key = editor.save(self.repo, {"body": "Trim input", "suggestion": "name.strip()", "head": "original"})
        (original,) = editor.notes(self.repo)
        editor.save(self.repo, dict(original, body="Keep trimming"), original=original)
        reviewer.save(self.repo, dict(original, suggestion="name.lstrip()"), original=original)
        (before_apply,) = editor.notes(self.repo)
        self.assertEqual(before_apply, dict(original, body="Keep trimming", suggestion="name.lstrip()"))
        receipt = {"path": "main.py", "new": [12, 12]}
        anchor = {"left_tip": "abc", "path": "main.py"}
        reviewer.db.execute("PRAGMA busy_timeout=0")
        with editor.applying(self.repo, before_apply) as current:
            with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                reviewer.save(self.repo, dict(before_apply, suggestion="different code"), original=before_apply)
            current.update(applied_location=receipt, applied_anchor=anchor)
        self.assertTrue(reviewer.set_resolved(self.repo, key, True))
        editor.save(self.repo, dict(before_apply, body="Looks good"), original=before_apply)
        self.assertEqual(
            reviewer.notes(self.repo),
            [
                dict(
                    before_apply,
                    body="Looks good",
                    resolved=True,
                    applied_location=receipt,
                    applied_anchor=anchor,
                )
            ],
        )

    def test_conflicting_or_deleted_edits_report_failure_without_partial_writes(self):
        store = self.open_store()
        other = self.open_store()
        key = store.save(self.repo, {"body": "Review", "suggestion": "a"})
        (original,) = store.notes(self.repo)
        other.save(self.repo, dict(original, suggestion="b"), original=original)
        with self.assertRaises(ReviewConflict):
            store.save(self.repo, dict(original, body="New body", suggestion="c"), original=original)
        self.assertEqual(store.notes(self.repo), [dict(original, suggestion="b")])
        with self.assertRaises(ReviewConflict), store.applying(self.repo, original):
            self.fail("A stale replacement reached the file edit")
        other.set_resolved(self.repo, key, True)
        with self.assertRaises(ReviewConflict), store.applying(self.repo, dict(original, suggestion="b")):
            self.fail("A resolved replacement reached the file edit")
        other.delete(self.repo, key)
        with self.assertRaisesRegex(ReviewConflict, "deleted"):
            store.save(self.repo, dict(original, body="Keep this draft"), original=original)
        self.assertEqual(other.notes(self.repo), [])

    def test_wrong_checkout_and_stale_ids_cannot_resolve_another_comment(self):
        store = self.open_store()
        key = store.save(self.repo, {"body": "Original"})
        other = SimpleNamespace(root=self.directory / "other-checkout")
        self.assertFalse(store.set_resolved(other, key, True))
        self.assertFalse(store.notes(self.repo)[0]["resolved"])
        store.delete(self.repo, key)
        replacement = store.save(self.repo, {"body": "Replacement"})
        self.assertFalse(store.set_resolved(self.repo, key, True))
        self.assertEqual(
            store.notes(self.repo), [{"body": "Replacement", "id": replacement, "resolved": False}]
        )
