"""Time file-tree selection and both layout switches on a committed, annotated patch."""

import gc
import hashlib
import json
import os
import runpy
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from time import monotonic, perf_counter, sleep

SHARED = Path(__file__).resolve().parent.parent / "review-latency" / "workload.py"
shared = runpy.run_path(str(SHARED))


def sample(repo, starts, state_dir, review, App):
    root = tk.Tk()
    errors = []
    root.report_callback_exception = lambda kind, err, trace: errors.append(err)
    app = App(root, store=review.Store(state_dir))
    root.geometry("1380x840+0+0")

    def wait_file(name):
        deadline = monotonic() + 10
        while monotonic() < deadline:
            root.update()
            if errors:
                raise errors[0]
            if app.error or getattr(app, "patch_error", ""):
                raise RuntimeError(app.error or app.patch_error)
            if app.diff and app.diff.file.path == name and app.lines is not None and app.diff.winfo_viewable():
                return
            sleep(0.001)
        raise TimeoutError(f"Waiting for {name}")

    def pick(name):
        row = next(key for key, f in app.file_ids.items() if f.path == name)
        app.tree.selection_set(row)
        wait_file(name)

    def check_layout(mode, selection, first):
        view = app.diff
        assert view.winfo_viewable() and app.mode == mode and view.page == 0
        assert len(view.editors) == (2 if mode == "Split" else 1)
        assert list(view.cards) == [n + 1 for n in starts[:8]]
        if selection:
            assert [line.new for line in view.selected()[0]] == selection
            actual_first = view.position()[0].new
            assert actual_first == first, (actual_first, first)
        row = starts[0] + 1
        card = view.cards[row]
        assert card.winfo_viewable() and card.winfo_width() > 1 and card.winfo_height() > 1
        if mode == "Split":
            y = [pane.dlineinfo(view.code_index(row + 1))[1] for pane in view.editors]
            assert abs(y[0] - y[1]) <= 1, y
        assert not errors, errors
        return shared["view_state"](view)

    def switch(mode):
        start = perf_counter()
        app.set_mode(mode)
        root.update()
        return (perf_counter() - start) * 1000

    try:
        app.repo, app.stack = repo, ["refs/heads/main", repo.checkout]
        app.reload_notes()
        app.load(tuple(app.stack), restore_path="small.py")
        wait_file("small.py")
        assert len(app.note_locations) == len(starts) == 160
        start = perf_counter()
        pick("policy.py")
        open_ms = (perf_counter() - start) * 1000
        assert len(app.lines) == 4001 and sum(line.kind == "+" for line in app.lines) == 4000
        states = [check_layout("Unified", [], None)]

        app.diff.select(0, 10, 11)
        app.diff.scroll(app.diff.code_index(3))
        root.update()
        first = app.diff.position()[0].new
        assert first == 3, first
        to_split_ms = switch("Split")
        states.append(check_layout("Split", [10, 11], first))
        # Carry a different selection and scroll position back into the previous layout.
        app.diff.select(1, 13, 14)
        app.diff.scroll(app.diff.code_index(5))
        root.update()
        first = app.diff.position()[0].new
        assert first == 5, first
        to_unified_ms = switch("Unified")
        states.append(check_layout("Unified", [13, 14], first))
        repeat_split_ms = switch("Split")
        states.append(check_layout("Split", [13, 14], first))

        pick("small.py")
        small_ms = switch("Unified")
        assert not app.diff.cards and len(app.diff.editors) == 1
        small = shared["view_state"](app.diff)
        assert "new disposition" in small[0][0][0]
        states.append(small)
        return {
            "open_ms": open_ms,
            "to_split_ms": to_split_ms,
            "to_unified_ms": to_unified_ms,
            "repeat_split_ms": repeat_split_ms,
            "small_ms": small_ms,
            "fingerprint": hashlib.sha256(json.dumps(states).encode()).hexdigest(),
        }
    finally:
        app.close()
        app.work.shutdown()


def main(source, run):
    sys.path.insert(0, str(source))
    from branchline import git, review
    from branchline.app import App

    assert Path(git.__file__).resolve().parent == source / "branchline"
    os.environ.update(
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_COUNT="0",
        GIT_AUTHOR_NAME="Reviewer",
        GIT_AUTHOR_EMAIL="test@example.invalid",
        GIT_COMMITTER_NAME="Reviewer",
        GIT_COMMITTER_EMAIL="test@example.invalid",
        GIT_AUTHOR_DATE="2024-01-01T12:00:00+0000",
        GIT_COMMITTER_DATE="2024-01-01T12:00:00+0000",
    )
    state_dir = run / "state"
    store = review.Store(state_dir)
    repo, starts = shared["fixture"](run, git, review, store)
    store.db.close()
    subprocess.run(["git", "-C", str(repo.root), "commit", "-qm", "Commit the reviewed settings"], check=True)
    repo = git.open_repo(repo.root)
    with (run / "samples.jsonl").open("x", encoding="utf-8") as output:
        for iteration in range(8):
            gc.collect()
            row = sample(repo, starts, state_dir, review, App)
            print(json.dumps(dict(row, warmup=iteration == 0)), file=output, flush=True)


if __name__ == "__main__":
    main(*(Path(arg).resolve() for arg in sys.argv[1:]))
