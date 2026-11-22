import unittest
from pathlib import Path

from branchline.git import Repository
from branchline.review import markdown


class ResolutionReportTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repository(Path("checkout"), {}, [])
        self.legacy_note = {
            "left": "refs/heads/main",
            "right": "refs/heads/feature",
            "left_tip": "base",
            "base": "base",
            "head": "tip",
            "path": "config.py",
            "old_path": "config.py",
            "old": [],
            "new": [7, 7],
            "excerpt": "+limit = 8",
            "body": "Raise the limit to 16.",
        }

    def test_open_applied_suggestion_and_resolved_proposal(self):
        applied = dict(
            self.legacy_note,
            suggestion="limit = 16",
            applied_location={"path": "config.py", "new": [9, 9], "branch": "refs/heads/feature"},
        )
        resolved = dict(self.legacy_note, body="Remove the limit.", suggestion="", resolved=True)
        report = markdown(self.repo, None, [resolved, applied])
        intro, comments = report.split("## Open comments")
        open_items, history = comments.split("## Resolved comments")
        self.assertIn("1 open · 1 resolved", intro)
        self.assertIn("Address the open comments.", intro)
        self.assertIn("Review status: Open", open_items)
        self.assertIn(applied["body"], open_items)
        self.assertIn("Suggestion status: applied to working file", open_items)
        self.assertIn("Applied at: config.py · L9 on feature", open_items)
        self.assertIn(applied["suggestion"], open_items)
        self.assertIn("Review status: Resolved", history)
        self.assertIn(resolved["body"], history)
        self.assertIn("Suggestion status: proposed", history)
        self.assertIn("Delete the selected lines.", history)

    def test_all_resolved_and_reopened(self):
        note = dict(self.legacy_note, resolved=True)
        report = markdown(self.repo, None, [note])
        self.assertIn("0 open · 1 resolved", report)
        self.assertIn("No open comments need work", report)
        self.assertNotIn("## Open comments", report)
        self.assertIn("## Resolved comments", report)
        self.assertIn(note["excerpt"], report)
        note["resolved"] = False
        reopened = markdown(self.repo, None, [note])
        self.assertIn("1 open · 0 resolved", reopened)
        self.assertIn("## Open comments", reopened)
        self.assertIn(note["body"], reopened)
        self.assertNotIn("## Resolved comments", reopened)

    def test_empty_scope(self):
        report = markdown(self.repo, [], [])
        self.assertIn("Scope: working tree", report)
        self.assertIn("0 open · 0 resolved", report)
        self.assertIn("No open comments need work", report)

    def test_open_only_keeps_open_suggestion_and_omits_resolved_details(self):
        applied = dict(
            self.legacy_note,
            id=1,
            suggestion="limit = 16",
            applied_location={"path": "config.py", "new": [7, 7]},
            applied_anchor={"path": "config.py"},
        )
        resolved = dict(
            self.legacy_note,
            id=2,
            resolved=True,
            head="retired-tip",
            path="retired.py",
            body="Remove the old limit.",
            excerpt="+old_limit = 8",
            suggestion="old_limit = 32",
        )
        dest = dict(applied, right="refs/heads/feature", head="current-tip", new=[11, 11], applied_text=True)
        report = markdown(self.repo, None, [resolved, applied], locations={1: [dest]}, open_only=True)
        self.assertIn("Open comments only", report)
        self.assertIn("**1 open**", report)
        self.assertIn("### 1. config.py", report)
        self.assertIn(applied["body"], report)
        self.assertIn(applied["suggestion"], report)
        self.assertIn("Applied at: config.py · L7", report)
        self.assertIn("Current location of replacement: Committed", report)
        self.assertIn("(head current-tip) · config.py · new L11", report)
        self.assertNotIn("resolved", report.lower())
        for value in (resolved["path"], resolved["body"], resolved["head"], "old_limit"):
            self.assertNotIn(value, report)

    def test_open_only_empty_review_has_no_history_or_suggestion_instructions(self):
        resolved = dict(self.legacy_note, resolved=True, suggestion="limit = 16")
        for notes in ([], [resolved]):
            with self.subTest(notes=notes):
                report = markdown(self.repo, [], notes, open_only=True)
                self.assertIn("Scope: working tree", report)
                self.assertIn("**0 open**", report)
                self.assertIn("No open comments need work", report)
                self.assertNotIn("## ", report)
                self.assertNotIn("suggestions", report)
                self.assertNotIn(resolved["body"], report)
