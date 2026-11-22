"""Shared committed fixtures and Tk timings for the desktop layout comparison."""

import gc
import hashlib
import json
import os
import runpy
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from time import monotonic, sleep
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from branchline import git, review
from branchline.app import App

LAYOUT = ROOT / "tools/autoresearch/diff-layout"
SHARED = runpy.run_path(str(LAYOUT.parent / "review-latency" / "workload.py"))
MIXED_FINGERPRINT = "565362e5b802b3d670d3447ba7226d27eb4d443a3606fc9e41e9230bce72001c"


def command(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, timeout=30
    )


def mixed_fixture(repo):
    repo.mkdir()
    command(repo, "init", "-q", "-b", "main", "--object-format=sha1")
    policy, small = repo / "policy.py", repo / "small.py"
    lines = [
        f'if rule_{i}: return "before {i}"  # policy {i}\n' for i in range(1, 40001)
    ]
    policy.write_text("".join(lines), encoding="utf-8")
    small.write_text("setting = False\n", encoding="utf-8")
    command(repo, "add", ".")
    command(repo, "commit", "-qm", "Initial policy")
    command(repo, "switch", "-qc", "feature/policy")
    for i in range(3, 40000, 4):
        lines[i] = lines[i].replace("before", "after")
    policy.write_text("".join(lines), encoding="utf-8")
    small.write_text("setting = True\n", encoding="utf-8")
    command(repo, "commit", "-qam", "Update every fourth policy")


def prepare(run: Path, large: bool) -> tuple[Path, Path]:
    """Create a fresh fixture. Both apps must open this checkout and review database."""
    run = run.resolve()
    run.mkdir(parents=True, exist_ok=True)
    repo, data = run / "checkout", run / "data"
    if repo.exists() or data.exists():
        raise FileExistsError(f"Benchmark fixture already exists in {run}")
    env = {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_COUNT": "0",
        "GIT_AUTHOR_NAME": "Reviewer",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Reviewer",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
        "GIT_AUTHOR_DATE": "2024-01-01T12:00:00+0000",
        "GIT_COMMITTER_DATE": "2024-01-01T12:00:00+0000",
    }
    with patch.dict(os.environ, env):
        store = review.Store(data / "branchline")
        try:
            if large:
                mixed_fixture(repo)
            else:
                SHARED["fixture"](run, git, review, store)
                command(repo, "commit", "-qm", "Commit the reviewed settings")
        finally:
            store.db.close()
        # The default first changed file must be the compact control in both UIs.
        # This leaves policy.py unopened until the measured action in each fresh app.
        order = repo / ".git/info/benchmark-order"
        order.write_text("small.py\n", encoding="utf-8")
        command(repo, "config", "diff.orderFile", str(order))
        opened = git.open_repo(repo)
        comparison = git.compare(opened, "refs/heads/main", opened.checkout)
        assert [f.path for f in comparison.files] == ["small.py", "policy.py"]
    return repo, data


def sample(repo: Path, data_home: Path, large: bool) -> dict:
    """Click through the visible Tk window, checking the rendered editor after every phase."""
    from display import capture_click

    gc.collect()
    repo = git.open_repo(repo)
    root = tk.Tk()
    errors = []
    root.report_callback_exception = lambda _kind, error, _trace: errors.append(error)
    app = App(root, store=review.Store(data_home / "branchline"))
    root.geometry("1380x840+0+0")
    elapsed = {"gap_ms": {}}
    states = []
    view_state = SHARED["view_state"]

    def wait_for(name, mode):
        deadline = monotonic() + 20
        while monotonic() < deadline:
            root.update()
            if errors:
                raise errors[0]
            if app.error or getattr(app, "patch_error", ""):
                raise RuntimeError(app.error or app.patch_error)
            if (
                app.diff
                and app.diff.file.path == name
                and app.lines is not None
                and app.mode == mode
                and app.diff.dual == (mode == "Split")
                and app.diff.winfo_viewable()
            ):
                return
            sleep(0.001)
        raise TimeoutError(f"Waiting for {name} in {mode}")

    def click(key, xy, name, mode):
        first, last = app.diff.editors[0], app.diff.editors[-1]
        left = first.winfo_rootx() + 4
        right = last.winfo_rootx() + last.winfo_width() - 16
        box = (left, first.winfo_rooty() + 40, right - left, 96)
        with capture_click(*xy, box) as shot:
            wait_for(name, mode)
        elapsed[key] = shot.elapsed_ms
        elapsed["gap_ms"][key] = shot.gap_ms

    def switch(key, mode):
        bar = app.diff.winfo_children()[0]
        button = next(
            b for b in bar.winfo_children() if getattr(b, "title", None) == mode
        )
        center = (
            button.winfo_rootx() + button.winfo_width() // 2,
            button.winfo_rooty() + button.winfo_height() // 2,
        )
        click(key, center, "policy.py", mode)

    def choose_range(first, last, scroll_to, col):
        view = app.diff

        def index(number):
            return next(
                i
                for i, cells in enumerate(view.visible)
                if cells[col] and cells[col].new == number and cells[col].kind == "+"
            )

        view.select(col, index(first), index(last))
        if scroll_to:
            view.scroll(view.code_index(scroll_to))
        root.update()

    def check(mode, numbers, top):
        view = app.diff
        assert app.mode == mode and view.winfo_viewable() and view.page == 0
        assert len(view.editors) == (2 if mode == "Split" else 1)
        if numbers:
            assert [line.new for line in view.selected()[0]] == numbers
        if large:
            assert len(view.rows) == (40001 if mode == "Split" else 50001)
            assert not view.cards
        else:
            assert list(view.cards) == [n + 1 for n in starts[:8]]
            first = starts[0] + 1
            assert (
                view.cards[first].winfo_viewable()
                and view.cards[first].winfo_height() > 1
            )
            if top:
                assert view.position()[0].new == top, (view.position()[0].new, top)
            if mode == "Split":
                ys = [
                    pane.dlineinfo(view.code_index(first + 1))[1]
                    for pane in view.editors
                ]
                assert abs(ys[0] - ys[1]) <= 1
        states.append(view_state(view))

    try:
        app.repo, app.stack = repo, ["refs/heads/main", repo.checkout]
        app.reload_notes()
        starts = [n["new"][0] for n in app.notes]
        app.load(tuple(app.stack))
        wait_for("small.py", "Unified")
        assert len(app.note_locations) == len(starts) == (0 if large else 160)
        row = next(key for key, f in app.file_ids.items() if f.path == "policy.py")
        x, y, width, height = app.tree.bbox(row)
        click(
            "open_ms",
            (
                app.tree.winfo_rootx() + x + width // 2,
                app.tree.winfo_rooty() + y + height // 2,
            ),
            "policy.py",
            "Unified",
        )
        assert len(app.lines) == (50001 if large else 4001)
        assert app.current.added == (10000 if large else 4000)
        assert app.current.removed == (10000 if large else 0)
        check("Unified", [], None)
        numbers, top = ([16], None) if large else ([10, 11], 3)
        choose_range(numbers[0], numbers[-1], top, 0)
        switch("to_split_ms", "Split")
        check("Split", numbers, top)
        if not large:
            numbers, top = [13, 14], 5
            choose_range(13, 14, top, 1)
        switch("to_unified_ms", "Unified")
        check("Unified", numbers, top)
        switch("repeat_split_ms", "Split")
        check("Split", numbers, top)

        if not large:
            # The original annotated oracle includes this untimed small-file control.
            small = next(key for key, f in app.file_ids.items() if f.path == "small.py")
            app.tree.selection_set(small)
            wait_for("small.py", "Split")
            app.set_mode("Unified")
            root.update()
            states.append(view_state(app.diff))
        elapsed["fingerprint"] = hashlib.sha256(json.dumps(states).encode()).hexdigest()
        expected = (
            MIXED_FINGERPRINT
            if large
            else (LAYOUT / "expected.sha256").read_text().strip()
        )
        assert elapsed["fingerprint"] == expected, (elapsed["fingerprint"], expected)
        return elapsed
    finally:
        app.close()
        app.work.shutdown()
