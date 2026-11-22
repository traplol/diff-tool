import gc
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk
from unittest.mock import patch

from test_review import command, fixture, record, write

from branchline import ui
from branchline.app import App
from branchline.review import Store


def descend(widget):
    for child in widget.winfo_children():
        yield child
        yield from descend(child)


def button(parent, name):
    return next(w for w in descend(parent) if isinstance(w, ui.Button) and w.title == name)


class DesktopCase(unittest.TestCase):
    def setUp(self):
        # Release the previous test's Tk objects on the GUI thread.
        gc.collect()
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        errors = []
        root.report_callback_exception = lambda t, e, b: errors.append(e)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        tmp = Path(temp.name)
        repo = fixture(tmp / "relay")
        store = Store(tmp / "state")
        app = App(root, repo.root / "src", store)
        self.addCleanup(app.work.shutdown)
        self.addCleanup(app.close)
        root.geometry(f"{root.winfo_screenwidth()}x{root.winfo_screenheight()}+0+0")

        def wait(predicate):
            deadline = time.monotonic() + 5
            while not predicate() and time.monotonic() < deadline and not errors:
                root.update()
                time.sleep(0.01)
            if errors:
                raise errors[0]
            self.assertTrue(predicate())
            root.update()

        def visible(widget):
            root.update()
            self.assertTrue(widget.winfo_viewable(), str(widget))
            x, y = widget.winfo_rootx(), widget.winfo_rooty()
            w, h = widget.winfo_width(), widget.winfo_height()
            self.assertGreater(w, 1)
            self.assertGreater(h, 1)
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + w, root.winfo_screenwidth())
            self.assertLessEqual(y + h, root.winfo_screenheight())
            # A desktop compositor can raise a mapped dialog after Tk returns.
            wait(
                lambda: (
                    root.winfo_containing(widget.winfo_rootx() + w // 2, widget.winfo_rooty() + h // 2)
                    == widget
                )
            )

        self.root, self.repo, self.app = root, repo, app
        self.store, self.tmp, self.errors = store, tmp, errors
        self.wait, self.visible = wait, visible
        wait(lambda: app.lines is not None)


class DesktopTest(DesktopCase):
    def test_stack_selection_comment_export_and_reopen(self):
        root, app, tmp, store = self.root, self.app, self.tmp, self.store
        wait, visible = self.wait, self.visible
        before = app.sidebar.winfo_width()
        self.assertGreaterEqual(before, 300)
        sx, sy = app.shell.sash_coord(0)
        for seq, offset in (("<Button-1>", 2), ("<B1-Motion>", 82), ("<ButtonRelease-1>", 82)):
            app.shell.event_generate(seq, x=sx + offset, y=sy + 60)
            root.update()
        self.assertEqual(app.sidebar.winfo_width(), before + 80)
        self.assertEqual(store.sidebar_width(), before + 80)
        self.assertEqual(
            app.stack, ["refs/heads/" + s for s in ("main", "feature/cache-policy", "feature/cache-metrics")]
        )
        app.stack_dialog()
        root.update()
        dialog = root.grab_current()
        lists = [w for w in descend(dialog) if isinstance(w, tk.Listbox)]
        source, _ = lists
        for name in ("Find stack", "Add", "Remove", "Review stack"):
            visible(button(dialog, name))
        source.selection_clear(0, "end")
        source.selection_set(source.get(0, "end").index("  feature/cache-policy"))
        order = lists[1]
        order.selection_clear(0, "end")
        order.selection_set(2)
        button(dialog, "Remove").command()
        button(dialog, "Find stack").command()
        wait(lambda: order.size() == 3)
        button(dialog, "Review stack").command()
        wait(lambda: app.lines is not None and len(app.stack) == 3)
        self.assertEqual(app.stack[1], "refs/heads/feature/cache-policy")
        pair_picker = next(w for w in descend(root) if isinstance(w, ttk.Combobox))
        pair_picker.current(2)
        pair_picker.event_generate("<<ComboboxSelected>>")
        wait(lambda: app.lines is not None and app.pair == tuple(app.stack[1:]))
        self.assertFalse(any(f.path == "config.toml" for f in app.comparison.files))
        app.load((app.stack[0], app.stack[-1]), "src/cache.py")
        wait(lambda: app.lines is not None and app.current.path == "src/cache.py")
        pick = next(
            i for i, (line,) in enumerate(app.diff.visible) if line.kind == "+" and "metrics.hits" in line.text
        )
        editor = app.diff.editors[0]
        editor.see(f"{pick + 2}.0")
        root.update()
        for seq, idx in (("<Button-1>", pick), ("<B1-Motion>", pick + 1), ("<ButtonRelease-1>", pick + 1)):
            bbox = editor.bbox(f"{idx + 1}.0")
            self.assertIsNotNone(bbox)
            editor.event_generate(seq, x=bbox[0] + 15, y=bbox[1] + 6)
        selected, _ = app.diff.selected()
        self.assertEqual(len(selected), 2)
        app.diff.comment()
        dialog = root.grab_current()
        body = next(w for w in descend(dialog) if isinstance(w, tk.Text) and w["state"] == "normal")
        self.assertEqual(dialog.winfo_toplevel(), root)
        root.update()
        save_btn = button(dialog, "Save comment")
        visible(save_btn)
        self.assertLessEqual(save_btn.winfo_rooty() + save_btn.winfo_height(), root.winfo_screenheight())
        body.insert("1.0", "Should a cached None count as a hit?")
        toolbar_button = button(root, "Export Markdown")
        file_tree = app.tree
        button(dialog, "Save comment").command()
        self.assertTrue(toolbar_button.winfo_exists(), "Saving a comment tore down the workspace toolbar")
        self.assertTrue(file_tree.winfo_exists(), "Saving a comment tore down the file browser")
        self.assertTrue(editor.winfo_exists(), "Saving a comment tore down the visible diff")
        self.assertEqual(len(app.active_notes()), 1)
        app.diff.viewed.set(True)
        app.diff.toggle_viewed()
        self.assertIn("src/cache.py", app.viewed)
        app.set_mode("Split")
        self.assertEqual(len(app.diff.editors), 2)
        app.navigate("Comments")
        root.update()
        notes_table = next(w for w in descend(app.body) if isinstance(w, ttk.Treeview))
        x, y, _, h = notes_table.bbox(notes_table.get_children()[0], "#1")
        self.assertEqual(
            root.winfo_containing(notes_table.winfo_rootx() + x + 10, notes_table.winfo_rooty() + y + h // 2),
            notes_table,
        )
        button(root, "Show in diff").command()
        wait(lambda: app.lines is not None and app.diff.selection)
        app.navigate("Commits")
        wait(lambda: app.commit_list is not None)
        self.assertEqual(len(app.commit_list), 2)
        root.update()
        table = next(w for w in descend(app.body) if isinstance(w, ttk.Treeview))
        fit = button(app.body, "Fit columns to content")
        visible(fit)
        table.column("subject", width=50, stretch=False)
        table.column("author", width=400, stretch=False)
        fit.command()
        widths = tkfont.Font(font=ttk.Style(table).lookup("Treeview", "font"))
        self.assertGreaterEqual(
            table.column("subject", "width"),
            max(widths.measure(table.set(i, "subject")) for i in table.get_children()),
        )
        self.assertLess(table.column("author", "width"), 400)
        row = table.get_children()[0]
        x, y, _, h = table.bbox(row, "author")
        table.event_generate("<Button-3>", x=x + 8, y=y + h // 2)
        menu = next(w for w in table.winfo_children() if isinstance(w, tk.Menu))
        menu.unpost()
        menu.invoke("Copy value")
        self.assertEqual(root.clipboard_get(), "Alex Chen")
        menu.invoke("Copy full SHA")
        self.assertEqual(root.clipboard_get(), row)
        menu.invoke("Copy row")
        self.assertEqual(root.clipboard_get(), "\t".join(table.set(row, k) for k in table["columns"]))
        menu.invoke("Commit details…")
        details = root.grab_current()
        detail_text = next(w for w in descend(details) if isinstance(w, tk.Text))
        wait(lambda: row in detail_text.get("1.0", "end"))
        details.destroy()
        app.navigate("Comments")
        app.navigate("Commits")
        self.assertTrue(table.winfo_exists())
        self.assertTrue(toolbar_button.winfo_exists())
        app.navigate("Changes")
        app.load((app.stack[1], app.stack[2]), "src/metrics.py")
        wait(lambda: app.lines is not None and app.current.path == "src/metrics.py")
        app.diff.comment()
        dialog = root.grab_current()
        body = next(w for w in descend(dialog) if isinstance(w, tk.Text) and w["state"] == "normal")
        body.insert("1.0", "Document when the counters reset.")
        button(dialog, "Save comment").command()
        out = tmp / "review.md"
        with patch("branchline.app.filedialog.asksaveasfilename", return_value=str(out)) as picker:
            app.export()
            picker.assert_not_called()
            preview = root.grab_current()
            self.assertIsInstance(preview, tk.Toplevel)
            text = next(w for w in descend(preview) if isinstance(w, tk.Text))
            text.insert("end", "\nA final review question.")
            visible(button(preview, "Copy Markdown"))
            visible(button(preview, "Save as…"))
            button(preview, "Copy Markdown").command()
            self.assertEqual(root.clipboard_get(), text.get("1.0", "end-1c"))
            button(preview, "Save as…").command()
            self.assertEqual(out.read_text(encoding="utf-8"), text.get("1.0", "end-1c"))
            button(preview, "Close").command()
        report = out.read_text(encoding="utf-8")
        self.assertIn("Should a cached None count as a hit?", report)
        self.assertIn("+            self.metrics.hits += 1", report)
        self.assertIn("Document when the counters reset.", report)
        self.assertIn("Whole file", report)
        app.refresh()
        wait(
            lambda: (
                app.comparison is not None
                and app.stack[1].endswith("cache-policy")
                and app.status.get() == "Comparison up to date"
            )
        )
        self.assertEqual(len(app.active_notes()), 2)
        self.assertFalse(self.errors)

    def test_filter_and_preserve_deep_selection(self):
        root, app = self.root, self.app
        write(self.repo.root, "src/registry.py", "".join(f"rule_{i} = {i}\n" for i in range(1500)))
        record(self.repo.root, "Add rule registry")
        app.refresh()
        self.wait(lambda: any(f.path == "src/registry.py" for f in app.comparison.files))
        app.focus_filter()
        app.search.insert("end", "registry")
        self.wait(lambda: app.diff and app.diff.file.path == "src/registry.py")
        app.search.focus_force()
        app.search.event_generate("<Return>")
        self.wait(lambda: root.focus_get() in app.diff.editors)
        app.diff.turn(1)
        d = app.diff
        start = next(i for i, (line,) in enumerate(d.visible) if line.new == 775)
        d.select(0, start, start + 4)
        d.editors[0].yview(f"{start - 4}.0")
        root.update()
        first, selection = d.position()
        app.set_mode("Split")
        root.update()
        self.assertEqual(app.diff.position(), (first, selection))
        editor = app.diff.editors[1]
        editor.focus_force()
        editor.event_generate("<Control-f>")
        self.wait(lambda: root.focus_get() == app.search)
        self.assertEqual(app.diff.position(), (first, selection))
        app.filter.set("does-not-match")
        self.wait(lambda: app.diff is None and app.current is None)
        app.search.event_generate("<Escape>")
        self.wait(lambda: app.diff is not None and not app.filter.get())
        app.filter.set("registry")
        self.wait(lambda: app.diff and app.diff.file.path == "src/registry.py")
        self.assertEqual(app.diff.position(), (first, selection))
        editor = app.diff.editors[1]
        editor.focus_force()
        editor.event_generate("<Escape>")
        self.assertEqual(app.diff.selected(), ([], "file"))
        editor.event_generate("<Key-c>")
        self.wait(lambda: root.grab_current() is not None)
        self.assertTrue(
            any("Whole file" in w["text"] for w in descend(root.grab_current()) if isinstance(w, tk.Label))
        )

    def test_export_saved_comment_after_branch_rename(self):
        root, app = self.root, self.app
        app.diff.comment()
        popover = root.grab_current()
        next(w for w in descend(popover) if isinstance(w, tk.Text) and w["state"] == "normal").insert(
            "1.0", "Verify the eviction order"
        )
        button(popover, "Save comment").command()
        command(self.repo.root, "branch", "-m", "feature/renamed")
        app.refresh()
        self.wait(
            lambda: (
                app.comparison and app.stack[-1].endswith("/renamed") and app.comparison.right == app.stack[-1]
            )
        )
        app.navigate("Comments")
        self.assertFalse(app.notes_table.get_children())
        scope = next(w for w in descend(app.body) if isinstance(w, ttk.Combobox))
        scope.current(1)
        scope.event_generate("<<ComboboxSelected>>")
        self.wait(lambda: len(app.notes_table.get_children()) == 1)
        self.visible(button(app.body, "Open comment"))
        self.assertFalse(button(app.body, "Show in diff").winfo_viewable())
        self.assertEqual(app.nav["Comments"][1]["text"], "1")
        resolve = button(app.body, "Resolve")
        self.visible(resolve)
        (row,) = app.notes_table.selection()
        resolve.command()
        self.assertFalse(app.notes_table.get_children())
        # A second reviewer can reopen the same archived comment before export.
        other = Store(self.tmp / "state")
        self.addCleanup(other.db.close)
        other.set_resolved(app.repo, int(row), False)
        app.export()
        top = root.grab_current()
        preview = next(w for w in descend(top) if isinstance(w, tk.Text)).get("1.0", "end")
        self.assertIn("Scope: entire repository", preview)
        self.assertIn("1 open · 0 resolved", preview)
        self.assertIn("Verify the eviction order", preview)
        self.assertIn("feature/cache-metrics", preview)
        # Tk's native file chooser focuses Tcl widgets with no Python wrapper.
        entry = str(top) + ".native_entry"
        root.tk.call("entry", entry)
        root.tk.call("pack", entry)
        root.update()
        root.tk.call("focus", "-force", entry)
        button(top, "Save as…").paint()
        self.assertFalse(self.errors)


if __name__ == "__main__":
    unittest.main()
