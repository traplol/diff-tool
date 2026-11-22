import tkinter as tk
from unittest.mock import patch

from test_desktop import DesktopCase, button, descend
from test_review import command

from branchline import git
from branchline.app import App
from branchline.review import Store


class SuggestionDesktopTest(DesktopCase):
    def working_file(self, text):
        self.path = self.repo.root / "rules.py"
        self.path.write_text(text, encoding="utf-8")
        app = self.app
        app.load((app.repo.checkout, git.WORKTREE))
        self.wait(lambda: app.diff and app.diff.file.path == self.path.name)
        return app.diff

    def compose_suggestion(self, diff, first=1, last=1):
        rows = {line.new: i for i, (line,) in enumerate(diff.visible) if line.new is not None}
        diff.select(0, rows[first], rows[last])
        self.root.update()
        self.visible(button(diff, "Suggest change"))
        button(diff, "Suggest change").command()
        form = self.root.grab_current()
        replacement = next(w for w in descend(form) if w.winfo_name() == "replacement")
        self.visible(button(form, "Save suggestion"))
        return form, replacement

    def preview(self):
        self.app.export()
        preview = self.root.grab_current()
        editor = next(w for w in descend(preview) if isinstance(w, tk.Text))
        self.wait(lambda: editor["state"] == "normal")
        text = editor.get("1.0", "end-1c")
        button(preview, "Close").command()
        return text

    def test_apply_requires_explicit_click_and_export_records_effect(self):
        diff = self.working_file("def limit():\n    return 8\n")
        form, field = self.compose_suggestion(diff, 2, 2)
        self.assertEqual(field.get("1.0", "end-1c"), "    return 8")
        field.delete("1.0", "end")
        field.insert("1.0", "    # Raise the limit\n    return 16\n")
        button(form, "Save suggestion").command()
        self.root.update()
        (note,) = self.store.notes(self.app.repo)
        self.assertEqual(note["body"], "")
        self.assertEqual(note["suggestion"], "    # Raise the limit\n    return 16\n")
        self.assertEqual(self.path.read_text(), "def limit():\n    return 8\n")
        report = self.preview()
        self.assertIn("Suggestion status: proposed", report)
        self.assertIn("    return 8", report)
        self.assertIn("```suggestion\n    # Raise the limit\n    return 16\n\n```", report)
        (card,) = diff.cards.values()
        action = button(card, "Apply to working file")
        self.visible(action)
        action.command()
        self.wait(lambda: self.store.notes(self.app.repo)[0].get("applied_location"))
        self.assertEqual(self.path.read_text(), "def limit():\n    # Raise the limit\n    return 16\n\n")
        self.assertEqual(command(self.repo.root, "ls-files", "--", self.path.name), b"")
        report = self.preview()
        self.assertIn("Suggestion status: applied to working file", report)
        self.assertIn("Applied at: rules.py", report)

        # Export should describe Git's current state even when the open review predates the commit.
        checkout = self.app.repo.checkout
        before_commit = self.app.repo.refs[checkout]
        command(self.repo.root, "add", "--", self.path.name)
        self.assertIn("- Current location of replacement: Staged", self.preview())
        command(self.repo.root, "commit", "-qm", "Raise the rule limit")
        report = self.preview()
        self.assertEqual(self.app.repo.refs[checkout], before_commit)
        self.assertIn("- Current location of replacement: Committed", report)
        self.assertIn(command(self.repo.root, "rev-parse", "HEAD").decode().strip(), report)
        self.assertIn("Suggestion status: applied to working file", report)
        self.assertNotIn("Suggestion status: proposed", report)

    def test_apply_on_refreshed_diff_checks_the_original_suggestion(self):
        diff = self.working_file(
            "def read_timeout():\n    log()\n    return 30\n\ndef write_timeout():\n    log()\n    return 30\n"
        )
        form, field = self.compose_suggestion(diff, 3, 3)
        field.delete("1.0", "end")
        field.insert("1.0", "    return 15")
        button(form, "Save suggestion").command()
        (note,) = self.store.notes(self.app.repo)
        current = "def write_timeout():\n    log()\n    return 30\n"
        self.path.write_text(current, encoding="utf-8")
        self.app.refresh()
        self.wait(
            lambda: self.app.diff and self.app.diff.file.oid != note["file_version"][1] and self.app.diff.cards
        )
        with patch("branchline.app.messagebox.showerror") as error:
            button(self.app.diff, "Apply to working file").command()
        self.assertIn("working-tree", error.call_args.args[1])
        self.assertEqual(self.path.read_text(encoding="utf-8"), current)
        self.assertEqual(self.store.notes(self.app.repo), [note])

    def test_edit_suggestion_after_staging_preserves_original_anchor(self):
        diff = self.working_file("one\ntwo\nthree\n")
        form, field = self.compose_suggestion(diff, 2, 3)
        field.delete("1.0", "end")
        button(form, "Save suggestion").command()
        (original,) = self.store.notes(self.app.repo)
        self.assertEqual(original["suggestion"], "")
        self.assertIn("Delete the selected lines.", self.preview())
        command(self.repo.root, "add", "--", self.path.name)
        self.app.refresh()
        self.wait(lambda: self.app.diff and self.app.diff.file.group == "Staged" and self.app.diff.cards)
        (card,) = self.app.diff.cards.values()
        button(card, "Edit").command()
        form = self.root.grab_current()
        field = next(w for w in descend(form) if w.winfo_name() == "replacement")
        field.insert("1.0", "  one combined rule")
        button(form, "Save suggestion").command()
        (edited,) = self.store.notes(self.app.repo)
        self.assertEqual(edited, dict(original, suggestion="  one combined rule"))
        self.assertEqual(self.path.read_text(), "one\ntwo\nthree\n")

    def test_export_keeps_unsaved_apply_receipt_and_latest_resolution(self):
        diff = self.working_file("limit = 8\n")
        form, field = self.compose_suggestion(diff)
        field.delete("1.0", "end")
        field.insert("end", "limit = 16")
        button(form, "Save suggestion").command()
        self.store.db.execute("""
            CREATE TRIGGER fail_receipt BEFORE UPDATE OF data ON notes
            BEGIN SELECT RAISE(FAIL, 'disk full'); END
        """)
        with patch("branchline.app.messagebox.showerror") as error:
            button(diff, "Apply to working file").command()
        self.assertIn("File updated", error.call_args.args[0])
        self.assertEqual(self.path.read_text(), "limit = 16\n")
        (saved,) = self.store.notes(self.app.repo)
        self.assertNotIn("applied_location", saved)
        self.store.db.execute("DROP TRIGGER fail_receipt")
        other = Store(self.tmp / "state")
        self.addCleanup(other.db.close)
        other.save(self.repo, dict(saved, body="Checked in a second window"), original=saved)
        other.set_resolved(self.repo, saved["id"], True)
        self.app.refresh()
        self.wait(lambda: self.app.notes[0]["body"] == "Checked in a second window")
        self.assertIn("applied_location", self.app.notes[0])
        report = self.preview()
        self.assertIn("0 open · 1 resolved", report)
        self.assertIn("Checked in a second window", report)
        self.assertIn("Suggestion status: applied to working file", report)
        other.save(self.repo, dict(saved, suggestion="limit = 64"), original=saved)
        report = self.preview()
        self.assertIn("Suggestion status: proposed", report)
        self.assertIn("```suggestion\nlimit = 64\n```", report)
        self.assertIn("Earlier replacement applied to working file", report)
        self.assertIn("\nlimit = 16\n", report)

    def test_two_windows_keep_the_applied_replacement_and_export_the_new_comment(self):
        diff = self.working_file("limit = 8\n")
        form, field = self.compose_suggestion(diff)
        field.delete("1.0", "end")
        field.insert("end", "limit = 16")
        button(form, "Save suggestion").command()

        other = App(tk.Toplevel(self.root), self.repo.root, Store(self.tmp / "state"))
        self.addCleanup(other.work.shutdown)
        self.addCleanup(other.close)
        self.wait(lambda: other.lines is not None)
        other.load((other.repo.checkout, git.WORKTREE))
        self.wait(lambda: other.diff and other.diff.cards)

        self.app.navigate("Comments")
        button(self.app.body, "Open comment").command()
        form = self.root.grab_current()
        body = next(
            widget
            for widget in descend(form)
            if isinstance(widget, tk.Text)
            and widget.winfo_name() != "replacement"
            and widget["state"] == "normal"
        )
        field = next(w for w in descend(form) if w.winfo_name() == "replacement")
        body.insert("end", "Check the updated limit.")
        field.insert("end", "0")
        button(other.diff, "Apply to working file").command()
        self.assertEqual(self.path.read_text(), "limit = 16\n")
        (applied,) = other.store.notes(self.repo)
        self.assertIn("applied_anchor", applied)

        with patch("branchline.app.messagebox.showerror") as error:
            button(form, "Save suggestion").command()
        self.assertIn("applied", error.call_args.args[1])
        self.assertIs(self.root.grab_current(), form)
        self.assertEqual(field.get("1.0", "end-1c"), "limit = 160")
        self.assertEqual(body.get("1.0", "end-1c"), "Check the updated limit.")
        self.assertEqual(self.store.notes(self.repo), [applied])
        field.delete("1.0", "end")
        field.insert("end", "limit = 16")
        button(form, "Save suggestion").command()
        self.assertEqual(self.store.notes(self.repo), [dict(applied, body="Check the updated limit.")])
        report = self.preview()
        self.assertIn("Suggestion status: applied to working file", report)
        self.assertIn("Check the updated limit.", report)
        self.assertNotIn("Suggestion status: proposed", report)

    def test_saving_a_deleted_comment_leaves_the_draft_open(self):
        self.app.diff.comment()
        form = self.root.grab_current()
        body = next(w for w in descend(form) if isinstance(w, tk.Text) and w["state"] == "normal")
        body.insert("end", "Review the default")
        button(form, "Save comment").command()
        self.app.navigate("Comments")
        button(self.app.body, "Open comment").command()
        form = self.root.grab_current()
        body = next(w for w in descend(form) if isinstance(w, tk.Text) and w["state"] == "normal")
        body.insert("end", " again")
        (original,) = self.store.notes(self.repo)
        other = Store(self.tmp / "state")
        self.addCleanup(other.db.close)
        other.delete(self.repo, original["id"])
        with patch("branchline.app.messagebox.showerror") as error:
            button(form, "Save comment").command()
        self.assertIn("deleted", error.call_args.args[1])
        self.assertIs(self.root.grab_current(), form)
        self.assertEqual(body.get("1.0", "end-1c"), "Review the default again")
        self.assertEqual(self.store.notes(self.repo), [])
