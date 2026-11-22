"""Check layout state across edits and navigation. Run with python -I check_switches.py SOURCE."""

import sys
import unittest
from pathlib import Path

source = Path(sys.argv[1]).resolve()
sys.path[:0] = [str(source), str(Path(__file__).resolve().parents[3] / "tests")]
from test_desktop import DesktopCase
from test_review import write

from branchline import git
from branchline.review import make_note

assert Path(git.__file__).resolve().parent == source / "branchline"


class SwitchStateTest(DesktopCase):
    def switch(self, mode):
        self.app.set_mode(mode)
        self.root.update()
        self.assertTrue(self.app.diff.winfo_viewable())
        self.assertEqual(len(self.app.diff.editors), 2 if mode == "Split" else 1)

    def setUp(self):
        super().setUp()
        self.path = self.repo.root / "draft.py"
        write(self.repo.root, self.path.name, "".join(f"value_{i} = {i}\n" for i in range(1, 1451)))
        write(self.repo.root, "another.py", "secondary = True\n")
        self.app.load((self.repo.checkout, git.WORKTREE))
        self.wait(lambda: self.app.comparison and self.app.comparison.right == git.WORKTREE)
        f = next(f for f in self.app.comparison.files if f.path == self.path.name)
        self.app.pick(f)
        self.wait(lambda: self.app.diff and self.app.diff.file == f and self.app.lines)

    def test_comment_and_viewed_state_cross_layouts(self):
        app = self.app
        line = next(line for line in app.lines if line.new == 4)
        note = make_note(app.comparison, app.current, [line], "new", "Old wording", diff_lines=app.lines)
        key = self.store.save(app.repo, note)
        app.reload_notes()
        app.update_note_views()
        self.switch("Split")
        self.switch("Unified")
        original = next(n for n in app.notes if n["id"] == key)
        self.store.save(app.repo, dict(original, body="New wording"), original=original)
        app.reload_notes()
        app.update_note_views()
        app.diff.viewed.set(True)
        app.diff.toggle_viewed()
        self.switch("Split")
        self.assertEqual([body["text"] for body in app.diff.cards[4].bodies], ["New wording"])
        self.assertTrue(app.diff.viewed.get())
        app.set_note_resolved(original, True)
        self.switch("Unified")
        self.assertTrue(app.diff.cards[4].notes[0]["resolved"])
        self.assertFalse(app.diff.cards[4].bodies)
        app.set_note_resolved(original, False)
        self.switch("Split")
        card = app.diff.cards[4]
        self.assertFalse(card.notes[0]["resolved"])
        self.assertEqual([body["text"] for body in card.bodies], ["New wording"])
        card.toggle()
        self.switch("Unified")
        self.assertFalse(app.diff.cards[4].bodies)

    def test_page_selection_resize_refresh_and_file_switch(self):
        app = self.app
        self.switch("Split")
        self.switch("Unified")
        app.diff.turn(1)
        app.diff.select(0, 320, 321)
        app.diff.scroll(app.diff.code_index(312))
        self.root.update()
        before = app.diff.position()
        self.root.geometry("1040x640+0+0")
        self.root.update()
        app.set_mode("Split")
        app.set_mode("Unified")
        self.switch("Split")
        self.assertEqual(app.diff.page, 1)
        self.assertEqual(app.diff.position(), before)
        self.assertEqual([line.new for line in app.diff.selected()[0]], [920, 921])
        contents = self.path.read_text().replace("value_920 = 920", "refreshed_value = 920")
        self.path.write_text(contents)
        app.refresh()
        self.wait(lambda: app.lines and any(line.text == "refreshed_value = 920" for line in app.lines))
        self.switch("Unified")
        if app.diff.page == 0:
            app.diff.turn(1)
            self.root.update()
        self.assertIn("refreshed_value = 920", app.diff.editors[0].get("1.0", "end"))
        other = next(f for f in app.comparison.files if f.path == "another.py")
        app.pick(other)
        self.wait(lambda: app.diff and app.diff.file == other and app.lines)
        self.switch("Split")
        self.assertEqual(app.diff.page, 0)
        text = app.diff.editors[-1].get("1.0", "end")
        self.assertIn("secondary = True", text)
        self.assertNotIn("refreshed_value", text)


if __name__ == "__main__":
    result = unittest.main(argv=[sys.argv[0]], exit=False).result
    sys.exit(0 if result.wasSuccessful() and not result.skipped else 1)
