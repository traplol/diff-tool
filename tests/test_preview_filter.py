import tkinter as tk
from tkinter import ttk
from unittest.mock import patch

from test_desktop import DesktopCase, button, descend

from branchline import git
from branchline.review import make_note


class PreviewFilterTest(DesktopCase):
    def open_preview(self):
        button(self.root, "Export Markdown").command()
        dialog = self.root.grab_current()
        editor = next(w for w in descend(dialog) if isinstance(w, tk.Text))
        self.wait(lambda: editor["state"] == "normal")
        toggle = next(
            w
            for w in descend(dialog)
            if isinstance(w, (tk.Checkbutton, ttk.Checkbutton)) and w["text"] == "Open comments only"
        )
        self.visible(toggle)
        return dialog, editor, toggle

    def save_resolved_note(self):
        note = make_note(self.app.comparison, self.app.current, [], "file", "The cache limit is documented.")
        key = self.store.save(self.repo, note)
        self.store.set_resolved(self.repo, key, True)
        return note["body"]

    def test_filtered_draft_keeps_open_worktree_locations_and_exports_edits(self):
        resolved = self.save_resolved_note()
        (self.repo.root / "timeout.py").write_text("timeout = 0\n", encoding="utf-8")
        c = git.compare(self.repo, self.repo.checkout, git.WORKTREE)
        change = next(f for f in c.files if f.path == "timeout.py")
        note = make_note(c, change, [], "file", "How should a zero timeout behave?")
        self.store.save(self.repo, note)
        self.app.refresh()
        self.wait(lambda: len(self.app.notes) == 2 and self.app.status.get() == "Comparison up to date")
        self.app.navigate("Comments")
        next(
            w for w in descend(self.app.body) if isinstance(w, tk.Radiobutton) and w["text"] == "Resolved"
        ).invoke()

        dialog, editor, toggle = self.open_preview()
        full = editor.get("1.0", "end-1c")
        self.assertIn(note["body"], full)
        self.assertIn(resolved, full)
        full_postscript = "\nArchive this complete review."
        editor.insert("end", full_postscript)
        toggle.invoke()
        filtered = editor.get("1.0", "end-1c")
        self.assertIn(note["body"], filtered)
        self.assertIn("Current location of reviewed code: Untracked", filtered)
        self.assertNotIn(resolved, filtered)
        self.assertNotIn(full_postscript, filtered)
        instruction = "\nCheck the timeout at 0 µs.\n"
        editor.insert("end", instruction)
        toggle.invoke()
        self.assertEqual(editor.get("1.0", "end-1c"), full + full_postscript)
        toggle.invoke()
        expected = filtered + instruction
        self.assertEqual(editor.get("1.0", "end-1c"), expected)
        button(dialog, "Copy Markdown").command()
        self.assertEqual(self.root.clipboard_get(), expected)
        output = self.tmp / "remaining.md"
        with patch("branchline.app.filedialog.asksaveasfilename", return_value=str(output)):
            button(dialog, "Save as…").command()
        self.assertEqual(output.read_text(encoding="utf-8"), expected)

    def test_all_resolved_and_intentionally_empty_filtered_draft(self):
        resolved = self.save_resolved_note()
        _, editor, toggle = self.open_preview()
        toggle.invoke()
        filtered = editor.get("1.0", "end-1c")
        self.assertIn("No open comments", filtered)
        self.assertNotIn(resolved, filtered)
        editor.delete("1.0", "end")
        toggle.invoke()
        self.assertIn(resolved, editor.get("1.0", "end-1c"))
        toggle.invoke()
        self.assertEqual(editor.get("1.0", "end-1c"), "")
