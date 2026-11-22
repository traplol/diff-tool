import tkinter as tk
from threading import Event
from unittest.mock import patch

from test_desktop import DesktopCase, button, descend
from test_review import command, record, write

from branchline import git


class WorkingTreeDesktopTest(DesktopCase):
    def select_comparison(self, label):
        picker = self.app.layer_select
        picker.current(list(picker["values"]).index(label))
        picker.event_generate("<<ComboboxSelected>>")
        self.wait(
            lambda: (
                self.app.comparison
                and self.app.layer_select.get() == label
                and (self.app.comparison.right == git.WORKTREE) == (label == "Working tree")
            )
        )

    def select_file(self, group, path):
        app = self.app
        row, change = next((row, f) for row, f in app.file_ids.items() if (f.group, f.path) == (group, path))
        app.tree.see(row)
        self.root.update()
        x, y, w, h = app.tree.bbox(row, "#0")
        app.tree.event_generate("<Button-1>", x=x + w - 5, y=y + h // 2)
        app.tree.event_generate("<ButtonRelease-1>", x=x + w - 5, y=y + h // 2)
        self.wait(lambda: app.diff and app.diff.file == change)

    def comment(self, body, added=None):
        diff = self.app.diff
        if added:
            row = next(i for i, (line,) in enumerate(diff.visible) if line.kind == "+" and line.text == added)
            editor = diff.editors[0]
            editor.see(f"{row + 1}.0")
            self.root.update()
            x, y, _, h = editor.bbox(f"{row + 1}.0")
            editor.event_generate("<Button-1>", x=x + 4, y=y + h // 2)
            editor.event_generate("<ButtonRelease-1>", x=x + 4, y=y + h // 2)
        button(diff, "Comment").command()
        form = self.root.grab_current() or self.app.body
        text = next(w for w in descend(form) if isinstance(w, tk.Text) and w["state"] == "normal")
        text.insert("1.0", body)
        save = button(form, "Save comment")
        self.visible(save)
        save.command()
        return next(n for n in self.app.active_notes() if n["body"] == body)

    def preview(self):
        button(self.root, "Export Markdown").command()
        dialog = self.root.grab_current()
        editor = next(w for w in descend(dialog) if isinstance(w, tk.Text))
        self.wait(lambda: editor["state"] == "normal")
        report = editor.get("1.0", "end-1c")
        button(dialog, "Close").command()
        return report

    def test_layer_navigation_reuses_locations_and_export_reads_fresh_reviewed_files(self):
        app, repo = self.app, self.repo.root
        write(repo, "reviewed.txt", "First draft\n")
        self.select_comparison("Working tree")
        note = self.comment("Test this draft.", "First draft")
        for i in range(12):
            write(repo, f"scratch/{i}.txt", "Unrelated\n")
        with patch.object(git, "working_tree", wraps=git.working_tree) as scans:
            self.select_comparison("Full stack")
            self.assertEqual(scans.call_count, 1)
            self.assertEqual(scans.call_args.kwargs["untracked_paths"], {"reviewed.txt"})
            layer = tuple(app.stack[:2])
            app.load(layer)
            self.wait(lambda: app.pair == layer)
            self.assertEqual(scans.call_count, 1)
            command(repo, "add", "reviewed.txt")
            self.assertIn("Current location of reviewed code: Staged", self.preview())
            self.assertEqual(scans.call_count, 2)
            self.assertEqual(scans.call_args.kwargs["untracked_paths"], {"reviewed.txt"})
            app.refresh()
            self.wait(lambda: app.status.get() == "Comparison up to date")
            self.assertEqual(app.locations_for(note)[0]["group"], "Staged")
            self.select_comparison("Working tree")
            self.assertTrue(any(f.path == "scratch/11.txt" for f in app.comparison.files))

    def test_superseded_queued_reads_do_not_run(self):
        app = self.app
        release = Event()
        started = [Event() for _ in range(app.work._max_workers)]
        ran, delivered = [], []

        def occupy_worker(ready):
            ready.set()
            release.wait(5)

        try:
            for ready in started:
                app.work.submit(occupy_worker, ready)
            self.assertTrue(all(ready.wait(2) for ready in started))
            for n in range(8):

                def read(value=n):
                    ran.append(value)
                    return value

                app.run("comparison", read, delivered.append, self.fail)
        finally:
            release.set()
        self.wait(lambda: delivered)
        self.assertEqual(ran, [7])
        self.assertEqual(delivered, [7])

    def test_unborn_nested_checkout_explains_empty_diff(self):
        nested = self.repo.root / "nested"
        nested.mkdir()
        command(nested, "init", "-q", "-b", "main")
        self.select_comparison("Working tree")
        self.select_file("Untracked", "nested")
        labels = [w["text"] for w in descend(self.app.diff) if isinstance(w, tk.Label)]
        self.assertIn("Nested Git repository", labels)
        self.assertIn("No readable HEAD commit.", labels)

    def test_review_partially_staged_file_with_its_stack(self):
        app, repo = self.app, self.repo.root
        middle = app.stack[1]
        command(repo, "switch", "feature/cache-policy")
        write(repo, "config.toml", "capacity = 512\n")
        command(repo, "add", "config.toml")
        write(repo, "config.toml", "capacity = 1024\n")
        write(repo, "limits.txt", "Review the upper bound.\n")
        app.refresh()
        self.wait(lambda: app.repo.checkout == middle and app.status.get() == "Comparison up to date")
        self.assertTrue(app.stack[-1].endswith("/cache-metrics"))
        committed = self.comment("Review the committed default.")

        self.select_comparison("Working tree")
        self.assertEqual(app.tab, "Changes")
        self.assertEqual(app.comparison.left, middle)
        self.assertEqual(
            [(f.group, f.path) for f in app.file_ids.values()],
            [("Staged", "config.toml"), ("Unstaged", "config.toml"), ("Untracked", "limits.txt")],
        )
        self.select_file("Staged", "config.toml")
        staged = self.comment("Is 512 the shipping value?", "capacity = 512")
        app.diff.viewed.set(True)
        app.diff.toggle_viewed()
        self.select_file("Unstaged", "config.toml")
        self.assertFalse(app.diff.viewed.get())
        self.assertEqual([line.text for line in app.lines if line.kind == "-"], ["capacity = 512"])
        unstaged = self.comment("Is 1024 just for this machine?", "capacity = 1024")
        self.assertNotIn(staged["id"], [n["id"] for n in app.diff.notes])

        write(repo, "limits.txt", "Try a smaller upper bound.\n")
        before = app.comparison.head
        button(self.root, "Refresh").command()
        self.wait(lambda: app.comparison and app.comparison.head != before)
        self.assertEqual(app.layer_select.get(), "Working tree")
        self.select_comparison("Full stack")
        app.navigate("Comments")
        self.assertEqual(len(app.notes_table.get_children()), 3)
        report = self.preview()
        for note in (committed, staged, unstaged):
            self.assertIn(note["body"], report)
        for text in ("Staged", "Unstaged", "+capacity = 512", "+capacity = 1024"):
            self.assertIn(text, report)

        app.notes_table.selection_set(str(unstaged["id"]))
        self.root.update()
        button(app.body, "Show in diff").command()
        self.wait(lambda: app.diff and app.diff.file.group == "Unstaged" and app.diff.selection)
        self.assertEqual([line.text for line in app.diff.selected()[0]], ["capacity = 1024"])
        self.assertEqual(app.diff.notes, [unstaged])
        (card,) = app.diff.cards.values()
        button(card, "Resolve").command()
        self.assertTrue(app.diff.notes[0]["resolved"])

        command(repo, "add", "config.toml")
        before = app.comparison.head
        app.refresh()
        self.wait(lambda: app.comparison and app.comparison.head != before)
        app.navigate("Comments")
        next(w for w in descend(app.body) if isinstance(w, tk.Radiobutton) and w["value"] == "All").invoke()
        app.notes_table.selection_set(str(unstaged["id"]))
        self.root.update()
        self.assertEqual(app.notes_table.set(str(unstaged["id"]), "status"), "Resolved")
        self.visible(button(app.body, "Show in diff"))
        button(app.body, "Show in diff").command()
        self.wait(lambda: app.diff and app.diff.file.group == "Staged" and app.diff.selection)
        self.assertEqual([line.text for line in app.diff.selected()[0]], ["capacity = 1024"])
        self.assertEqual([n["id"] for n in app.diff.notes], [unstaged["id"]])
        # Export scans the live refs even before an F5 refresh.
        command(repo, "commit", "-qm", "Publish the updated cache capacity")
        report = self.preview()
        self.assertIn("Current location of reviewed code: Committed", report)
        self.assertIn(command(repo, "rev-parse", "HEAD").decode().strip(), report)
        self.assertIn("no unambiguous match", report)  # The 512 proposal was superseded.
        self.assertIn(unstaged["body"], report.split("## Resolved comments")[1])
        app.refresh()
        self.wait(
            lambda: (
                app.comparison
                and app.comparison.right == git.WORKTREE
                and all(f.group == "Untracked" for f in app.comparison.files)
            )
        )
        app.navigate("Comments")
        app.notes_table.selection_set(str(unstaged["id"]))
        self.root.update()
        button(app.body, "Show in diff").command()
        self.wait(lambda: app.comparison and app.comparison.right == middle and app.diff and app.diff.selection)
        self.assertEqual([line.text for line in app.diff.selected()[0]], ["capacity = 1024"])
        self.assertIn(unstaged["id"], [n["id"] for n in app.diff.notes])
        self.visible(button(app.diff, "Reopen"))
        app.navigate("Comments")
        app.notes_table.selection_set(str(unstaged["id"]))
        self.root.update()
        reopen = button(app.body, "Reopen")
        self.visible(reopen)
        reopen.command()
        self.assertEqual(app.notes_table.set(str(unstaged["id"]), "status"), "Open")
        reopened = self.preview()
        self.assertIn(unstaged["body"], reopened.split("## Open comments")[1])
        self.assertNotIn("## Resolved comments", reopened)
        button(app.body, "Open comment").command()
        excerpt = next(
            w for w in descend(self.root.grab_current()) if isinstance(w, tk.Text) and w["state"] == "disabled"
        )
        self.assertEqual(excerpt.get("1.0", "end-1c"), "+capacity = 1024")
        cancel = button(self.root.grab_current(), "Cancel")
        self.visible(cancel)
        cancel.command()

    def test_unborn_review_survives_first_commit(self):
        app = self.app
        repo = self.tmp / "new"
        repo.mkdir()
        command(repo, "init", "-q", "-b", "main")
        write(repo, "plan.txt", "First draft\n")
        app.open(repo)
        self.wait(lambda: app.repo.root == repo and app.diff and app.diff.file.path == "plan.txt")
        self.assertEqual(app.layer_select.get(), "Working tree")
        note = self.comment("Clarify the first step.", "First draft")
        record(repo, "Add the plan")
        app.refresh()
        self.wait(lambda: app.stack and app.comparison and not app.comparison.files)
        self.assertEqual(app.layer_select.get(), "Working tree")
        app.navigate("Comments")
        self.assertEqual(app.notes_table.get_children(), (str(note["id"]),))
        self.assertIn("+First draft", self.preview())

    def test_checkout_outside_selected_stack_exports_separately(self):
        app = self.app
        stack = app.stack[:2]
        app.store.set_stack(app.repo, stack)
        write(app.repo.root, "experiment.txt", "Try a shorter expiry.\n")
        app.refresh()
        self.wait(lambda: app.diff and app.stack == stack and app.comparison.right == stack[-1])
        stack_note = self.comment("Keep the original policy.")
        self.select_comparison("Working tree")
        local_note = self.comment("Measure expiry first.", "Try a shorter expiry.")
        app.navigate("Comments")
        self.assertEqual(app.notes_table.get_children(), (str(local_note["id"]),))
        report = self.preview()
        self.assertIn(local_note["body"], report)
        self.assertNotIn(stack_note["body"], report)

        scope = next(w for w in descend(app.body) if w.winfo_class() == "TCombobox")
        scope.set("Entire repository")
        scope.event_generate("<<ComboboxSelected>>")
        self.wait(lambda: len(app.notes_table.get_children()) == 2)
        report = self.preview()
        self.assertIn(stack_note["body"], report)
        self.assertIn(local_note["body"], report)
