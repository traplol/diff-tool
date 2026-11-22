import tkinter as tk

from test_desktop import DesktopCase, button, descend
from test_review import command, record, write

from branchline import ui


class InlineCommentsTest(DesktopCase):
    def save_note(self, body):
        self.app.diff.comment()
        popover = self.root.grab_current()
        editor = next(w for w in descend(popover) if isinstance(w, tk.Text) and w["state"] == "normal")
        editor.insert("end", body)
        button(popover, "Save comment").command()
        self.root.update()

    def toggle(self, card):
        next(w for w in descend(card) if isinstance(w, ui.Button) and "comment" in w.title.lower()).command()
        self.root.update()

    def bodies(self, card):
        return [w["text"] for w in descend(card) if isinstance(w, tk.Label) and w.winfo_viewable()]

    def test_inline_thread_survives_layout_switch_and_keeps_code_selectable(self):
        app = self.app
        app.pick(next(f for f in app.comparison.files if f.path == "src/cache.py"))
        self.wait(lambda: app.diff and app.diff.file.path == "src/cache.py")
        diff = app.diff
        row = next(
            i
            for i, (line,) in enumerate(diff.visible)
            if line.kind == "+" and "self.metrics.hits +=" in line.text
        )
        editor = diff.editors[0]
        editor.see(f"{row + 1}.0")
        diff.select(0, row, row)
        self.save_note("Check cache misses.\nWhat happens on eviction?")
        self.save_note("Document this counter.")
        card = diff.cards[row]
        editor.see(diff.code_index(row + 1))
        self.root.update()
        self.assertEqual(len(diff.cards), 1)
        self.assertIn("Check cache misses.\nWhat happens on eviction?", self.bodies(card))
        self.assertIn("Document this counter.", self.bodies(card))
        self.assertLess(editor.dlineinfo(diff.code_index(row))[1] + editor.winfo_rooty(), card.winfo_rooty())
        self.assertLessEqual(
            card.winfo_rooty() + card.winfo_height(),
            editor.dlineinfo(diff.code_index(row + 1))[1] + editor.winfo_rooty(),
        )
        self.toggle(card)
        self.assertNotIn("Document this counter.", self.bodies(diff.cards[row]))
        self.assertIs(app.diff.editors[0], editor)

        app.set_mode("Split")
        self.root.update()
        diff = app.diff
        row, card = next(iter(diff.cards.items()))
        self.assertNotIn("Document this counter.", self.bodies(card))
        self.toggle(card)
        index = diff.code_index(row + 1)
        diff.editors[1].see(index)
        self.root.update()
        self.assertEqual(diff.editors[0].dlineinfo(index)[1], diff.editors[1].dlineinfo(index)[1])
        x, y, _, height = diff.editors[1].bbox(index)
        diff.editors[1].event_generate("<Button-1>", x=x + 3, y=y + height // 2)
        selected, side = diff.selected()
        self.assertEqual((selected, side), ([diff.visible[row + 1][1]], "new"))
        diff.copy()
        self.assertEqual(self.root.clipboard_get(), selected[0].text)

    def test_file_comment_can_collapse_on_binary_file(self):
        app = self.app
        change = next(f for f in app.comparison.files if f.binary)
        app.pick(change)
        self.wait(lambda: app.diff and app.diff.file == change)
        self.save_note("Check the original artwork.")
        diff = app.diff
        self.assertIn("Check the original artwork.", self.bodies(diff.cards[-1]))
        self.toggle(diff.cards[-1])
        self.assertNotIn("Check the original artwork.", self.bodies(diff.cards[-1]))

    def test_show_in_diff_reveals_card_when_range_spans_unified_pages(self):
        app, repo = self.app, self.repo.root
        # Split packs each removed/added pair onto one row. Unified doubles the row count.
        command(repo, "switch", "-qc", "paginate-base")
        write(repo, "long.txt", "".join(f"old value {i}\n" for i in range(580)))
        record(repo, "Old values")
        command(repo, "switch", "-qc", "paginate-head")
        write(repo, "long.txt", "".join(f"new value {i}\n" for i in range(580)))
        record(repo, "New values")
        app.refresh()
        self.wait(
            lambda: app.repo.checkout.endswith("/paginate-head") and app.status.get() == "Comparison up to date"
        )
        app.stack = ["refs/heads/paginate-base", "refs/heads/paginate-head"]
        app.load(tuple(app.stack))
        self.wait(lambda: app.diff and app.current.path == "long.txt" and app.comparison.left == app.stack[0])
        app.set_mode("Split")
        self.root.update()
        app.diff.select(1, 1, 50)
        self.save_note("Review new lines 1 through 50.")
        app.set_mode("Unified")
        app.navigate("Comments")
        app.notes_table.selection_set(str(app.notes[0]["id"]))
        self.root.update()
        button(app.body, "Show in diff").command()
        self.wait(lambda: app.diff and app.diff.cards and app.tab == "Changes")
        self.assertEqual(app.diff.page, 1)
        (card,) = app.diff.cards.values()
        self.visible(button(card, "Resolve"))
        self.assertEqual(app.diff.selected()[0][-1].new, 50)
