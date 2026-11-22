import tkinter as tk

from test_desktop import DesktopCase, button, descend
from test_review import fixture

from branchline import git, ui


class InlineResolutionTest(DesktopCase):
    def add_comment(self, body):
        self.app.diff.comment()
        form = self.root.grab_current()
        editor = next(w for w in descend(form) if isinstance(w, tk.Text) and w["state"] == "normal")
        editor.insert("end", body)
        button(form, "Save comment").command()
        self.root.update()

    def test_suggestion_and_comment_on_same_line_resolve_independently(self):
        path = self.repo.root / "limit.py"
        path.write_text("limit = 1\n")
        self.app.load((self.repo.checkout, git.WORKTREE))
        self.wait(lambda: self.app.diff and self.app.diff.file.path == path.name)
        self.app.set_mode("Split")
        self.root.update()
        diff = self.app.diff
        row = next(i for i, (_, line) in enumerate(diff.visible) if line and line.new == 1)
        diff.select(1, row, row)
        diff.suggest()
        form = self.root.grab_current()
        replacement = next(w for w in descend(form) if w.winfo_name() == "replacement")
        replacement.delete("1.0", "end")
        replacement.insert("end", "limit = 2")
        button(form, "Save suggestion").command()
        self.root.update()
        self.add_comment("Which workloads reach this limit?")
        card = diff.cards[row]
        editor = diff.editors[1]
        self.visible(button(card, "Resolve"))
        button(card, "Resolve").command()
        self.root.update()
        suggestion, comment = self.store.notes(self.repo)
        self.assertTrue(suggestion["resolved"])
        self.assertEqual(suggestion["suggestion"], "limit = 2")
        self.assertFalse(comment["resolved"])
        self.assertEqual([body["text"] for body in card.bodies], [comment["body"]])
        folded = button(card, "▸  Resolved suggestion")
        self.visible(folded)
        folded.command()
        self.visible(button(card, "Reopen"))
        self.assertIn("+ limit = 2", [body["text"] for body in card.bodies])
        self.assertFalse(
            any(isinstance(w, ui.Button) and w.title == "Apply to working file" for w in descend(card))
        )
        button(card, "▾  Resolved suggestion").command()
        self.assertEqual([body["text"] for body in card.bodies], [comment["body"]])
        self.assertIs(diff.editors[1], editor)
        self.assertEqual(diff.selection, (1, row, row))
        card.toggle()
        self.visible(button(card, "▸  2 comments · 1 open"))
        card.toggle()
        self.visible(button(card, "Reopen"))
        button(card, "Reopen").command()
        self.root.update()
        self.assertFalse(any(n["resolved"] for n in self.store.notes(self.repo)))
        self.visible(button(card, "Apply to working file"))
        self.assertEqual(path.read_text(), "limit = 1\n")

    def test_resolved_binary_file_comment_can_be_reopened(self):
        change = next(f for f in self.app.comparison.files if f.binary)
        self.app.pick(change)
        self.wait(lambda: self.app.diff and self.app.diff.file == change)
        self.add_comment("Confirm the artwork.")
        card = self.app.diff.cards[-1]
        button(card, "Resolve").command()
        self.root.update()
        self.assertFalse(card.bodies)
        folded = button(card, "▸  1 comment · Resolved")
        self.visible(folded)
        folded.command()
        self.assertEqual([body["text"] for body in card.bodies], ["Confirm the artwork."])
        other = fixture(self.tmp / "other")
        self.app.open(other.root)
        self.wait(lambda: self.app.repo.root == other.root and self.app.diff)
        self.app.open(self.repo.root)
        self.wait(lambda: self.app.repo.root == self.repo.root and self.app.diff)
        self.app.pick(change)
        self.wait(lambda: self.app.diff and self.app.diff.file == change)
        card = self.app.diff.cards[-1]
        self.assertFalse(card.bodies)
        button(card, "▸  1 comment · Resolved").command()
        button(card, "Reopen").command()
        self.root.update()
        card.toggle()
        self.visible(button(card, "▸  1 comment · Open"))
        (note,) = self.store.notes(self.repo)
        self.assertFalse(note["resolved"])
        self.assertEqual(note["body"], "Confirm the artwork.")
