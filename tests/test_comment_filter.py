import tkinter as tk
from tkinter import ttk
from unittest.mock import patch

from test_desktop import DesktopCase, button, descend
from test_review import command, record, write

from branchline.review import make_note


class CommentFilterTest(DesktopCase):
    def save_note(self, text, *, resolved=False, archived=False):
        note = make_note(self.app.comparison, self.app.current, [], "file", text)
        if archived:
            note["right"] = "refs/heads/retired"
        key = self.store.save(self.repo, note)
        if resolved:
            self.store.set_resolved(self.repo, key, True)
        return str(key)

    def open_comments(self):
        self.app.refresh()
        self.wait(lambda: self.app.status.get() == "Comparison up to date")
        self.app.navigate("Comments")
        self.root.update()
        return self.app.notes_table

    def filters(self):
        return {w["text"]: w for w in descend(self.app.body) if isinstance(w, tk.Radiobutton)}

    def test_double_click_below_rows_or_on_heading_keeps_editor_closed(self):
        key = self.save_note("Review the first row.")
        table = self.open_comments()
        table.selection_set(key)
        x, y, _, height = table.bbox(key, "path")
        for timestamp, click_y in ((1000, y + 2 * height), (2000, y - 4)):
            for t in (timestamp, timestamp + 100):
                for event in ("<ButtonPress-1>", "<ButtonRelease-1>"):
                    table.event_generate(event, x=x + 10, y=click_y, time=t)
                    self.root.update()
            self.assertIsNone(self.root.grab_current())
        table.selection_set(key)
        table.focus_force()
        table.event_generate("<KeyPress-Return>")
        self.wait(lambda: self.root.grab_current() is not None)

    def test_show_in_diff_after_base_advances_independently(self):
        app, repo = self.app, self.repo.root
        key = self.save_note("Keep this comparison available.")
        left, right = app.pair
        command(repo, "switch", "main")
        write(repo, "release.txt", "Independent release work\n")
        record(repo, "Advance main")
        command(repo, "switch", right.removeprefix("refs/heads/"))
        self.open_comments()
        # The comment belongs to the full stack while another layer is open.
        app.load(tuple(app.stack[1:]))
        self.wait(lambda: app.pair == tuple(app.stack[1:]))
        app.notes_table.selection_set(key)
        self.root.update()
        jump = button(app.body, "Show in diff")
        self.visible(jump)
        jump.command()
        self.wait(lambda: app.pair == (left, right) and app.diff and app.diff.cards)
        self.assertEqual(app.diff.cards[-1].notes[0]["id"], int(key))
        # Merging the reviewed head into main advances the actual merge base too.
        command(repo, "switch", "main")
        command(repo, "merge", "--no-edit", right)
        command(repo, "switch", right.removeprefix("refs/heads/"))
        self.open_comments()
        self.assertFalse(app.can_jump(app.notes[0]))

    def test_double_click_opens_clicked_comments_text_and_excerpt(self):
        other = self.save_note("Check the capacity.")
        line = next(line for line in self.app.lines if line.kind == "+")
        note = make_note(self.app.comparison, self.app.current, [line], "new", "Confirmed the policy.")
        key = self.store.save(self.repo, note)
        self.store.set_resolved(self.repo, key, True)
        table = self.open_comments()
        self.filters()["All"].invoke()
        self.root.update()
        self.assertEqual(table.selection(), (other,))
        x, y, width, height = table.bbox(str(key), "body")
        native_grab = tk.Misc.grab_set

        def grab_visible(widget):
            # X11 can refuse the grab during a real double-click if the frame is still unmapped.
            self.assertTrue(widget.winfo_viewable(), "Comment editor requested a grab before it was visible")
            native_grab(widget)

        with patch.object(tk.Misc, "grab_set", grab_visible):
            for timestamp in (1000, 1100):
                for event in ("<ButtonPress-1>", "<ButtonRelease-1>"):
                    table.event_generate(event, x=x + width // 2, y=y + height // 2, time=timestamp)
                    self.root.update()
            self.wait(lambda: self.root.grab_current() is not None)
        popover = self.root.grab_current()
        editors = {w["state"]: w for w in descend(popover) if isinstance(w, tk.Text)}
        for state, expected in (("normal", note["body"]), ("disabled", note["excerpt"])):
            self.assertIn(state, editors, "The comment popover opened without its editor")
            self.visible(editors[state])
            self.assertEqual(editors[state].get("1.0", "end-1c"), expected)
        editors["normal"].insert("end", " Verified locally.")
        save = button(popover, "Save comment")
        self.visible(save)
        save.command()
        self.assertEqual(table.set(str(key), "body"), "Confirmed the policy. Verified locally.")
        self.assertEqual(table.set(str(key), "status"), "Resolved")

    def test_resolve_selects_next_open_and_filters_keep_comment_order(self):
        first = self.save_note("Review the default.")
        second = self.save_note("Verified by the cache test.", resolved=True)
        third = self.save_note("Check eviction.")
        fourth = self.save_note("Check metrics.")
        table = self.open_comments()
        filters = self.filters()
        for control in filters.values():
            self.visible(control)
        self.assertEqual(table.get_children(), (first, third, fourth))
        table.selection_set(third)
        self.root.update()
        button(self.app.body, "Resolve").command()
        self.assertEqual(table.get_children(), (first, fourth))
        self.assertEqual(table.selection(), (fourth,))
        self.assertEqual(table.focus(), fourth)
        self.assertIn("2 open  ·  2 resolved", self.app.comments_heading["text"])
        self.assertEqual(self.app.nav["Comments"][1]["text"], "4")

        filters["All"].focus_force()
        filters["All"].event_generate("<KeyPress-space>")
        filters["All"].event_generate("<KeyRelease-space>")
        self.wait(lambda: table.get_children() == (first, second, third, fourth))
        self.assertEqual(table.selection(), (fourth,))
        filters["Resolved"].invoke()
        self.assertEqual(table.get_children(), (second, third))
        table.selection_set(second)
        button(self.app.body, "Reopen").command()
        self.assertEqual(table.selection(), (third,))
        button(self.app.body, "Reopen").command()
        self.root.update()
        self.assertEqual(table.get_children(), ())
        self.assertIn("No resolved comments", self.app.notes_hint["text"])
        self.assertFalse(button(self.app.body, "Reopen").winfo_viewable())
        filters["Open"].invoke()
        self.assertEqual(table.get_children(), (first, second, third, fourth))

    def test_status_combines_with_scope_and_export_keeps_review_history(self):
        local = self.save_note("Open in the stack")
        self.save_note("Open on the retired branch", archived=True)
        archived = self.save_note("Resolved on the retired branch", resolved=True, archived=True)
        table = self.open_comments()
        self.assertEqual(table.get_children(), (local,))
        self.filters()["Resolved"].invoke()
        self.assertEqual(table.get_children(), ())

        scope = next(w for w in descend(self.app.body) if isinstance(w, ttk.Combobox))
        self.visible(scope)
        scope.set("Entire repository")
        scope.event_generate("<<ComboboxSelected>>")
        self.assertEqual(table.get_children(), (archived,))
        self.assertEqual(self.app.nav["Comments"][1]["text"], "3")
        self.app.export()
        dialog = self.root.grab_current()
        preview = next(w for w in descend(dialog) if isinstance(w, tk.Text)).get("1.0", "end-1c")
        self.assertIn("2 open · 1 resolved", preview)
        for body in ("Open in the stack", "Open on the retired branch", "Resolved on the retired branch"):
            self.assertIn(body, preview)
        button(dialog, "Close").command()
