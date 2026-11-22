"""Canonical workload. Run with python -I workload.py SOURCE FRESH_RUN_DIR."""

import hashlib
import json
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from time import perf_counter


def fixture(directory, git, review, store):
    root = directory / "checkout"
    root.mkdir()

    def command(*args):
        subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True, timeout=30)

    command("init", "-q", "--object-format=sha1", "-b", "main")
    small = root / "small.py"
    original = [f"setting_{i} = 'initial {i}'\n" for i in range(24)]
    small.write_text("".join(original), encoding="utf-8")
    command("add", "small.py")
    command("commit", "-qm", "Base settings")
    command("switch", "-qc", "feature/settings")
    repo = git.open_repo(root)
    large = root / "policy.py"
    large.write_text(
        "".join(f'if enabled_{i}: return "café {i}"  # rule {i}\n' for i in range(1, 4001)),
        encoding="utf-8",
    )
    local = git.working_tree(repo, repo.checkout)
    (change,) = local.files
    assert (change.path, change.group) == ("policy.py", "Untracked")
    lines = git.patch(repo, local, change)
    by_number = {line.new: line for line in lines if line.new}
    starts = [10 + i * 65 for i in range(8)] + [650 + i * 22 for i in range(152)]
    for i, number in enumerate(starts):
        selected = [by_number[number], by_number[number + 1]]
        note = review.make_note(local, change, selected, "new", f"Review rules at {number}.", diff_lines=lines)
        key = store.save(repo, note)
        if i % 8 == 3:
            store.set_resolved(repo, key, True)
    original[6:8] = ["if enabled: return 'ready'  # new disposition\n"]
    original[19:19] = ["# Follow up on this setting.\n", "extra = True\n"]
    small.write_text("".join(original), encoding="utf-8")
    command("add", "policy.py", "small.py")
    return repo, starts


def view_state(view):
    panes = []
    for editor in view.editors:
        tags = [(name, [str(i) for i in editor.tag_ranges(name)]) for name in editor.tag_names()]
        panes.append((editor.get("1.0", "end-1c"), tags))
    cards = [
        (row, [n["id"] for n in card.notes], [label.cget("text") for label in card.bodies])
        for row, card in sorted(view.cards.items())
    ]
    return panes, cards


def main(source, run_dir):
    sys.path.insert(0, str(source))
    from branchline import git, review, tracking
    from branchline.app import App, clear

    assert Path(git.__file__).resolve().is_relative_to(source)
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
    store = review.Store(run_dir / "state")
    repo, starts = fixture(run_dir, git, review, store)
    root = tk.Tk()
    callback_errors = []
    root.report_callback_exception = lambda kind, err, trace: callback_errors.append(err)
    app = App(root, store=store)
    app.shell.pack_forget()
    app.detail = tk.Frame(root)
    app.detail.pack(fill="both", expand=True)
    root.geometry("1380x840+0+0")
    app.repo, app.stack = repo, ["refs/heads/main", repo.checkout]
    app.pair = (repo.checkout, git.WORKTREE)
    root.update()

    def empty_view():
        clear(app.detail)
        app.diff = None
        app.file_positions.clear()
        root.update()

    def elapsed(start):
        return (perf_counter() - start) * 1000

    try:
        with (run_dir / "samples.jsonl").open("x", encoding="utf-8") as output:
            for iteration in range(8):
                empty_view()
                app.reload_notes()
                original = app.notes[0]
                assert original["body"] == "Review rules at 10."
                start = perf_counter()
                c = git.working_tree(repo, repo.checkout)
                locations = tracking.locate_notes(repo, app.stack, c, app.notes)
                tracking_ms = elapsed(start)
                assert len(locations) == len(starts) == 160
                for note, line in zip(app.notes, starts, strict=True):
                    (dest,) = locations[note["id"]]
                    assert (dest["group"], dest["path"], dest["new"]) == (
                        "Staged",
                        "policy.py",
                        [line, line + 1],
                    )
                app.comparison, app.note_locations = c, locations
                app.current = next(f for f in c.files if f.path == "policy.py")
                app.lines = git.patch(repo, c, app.current)
                assert sum(line.kind == "+" for line in app.lines) == 4000
                app.mode = "Unified"
                start = perf_counter()
                app.draw_file()
                root.update()
                render_ms = elapsed(start)
                assert list(app.diff.cards) == [n + 1 for n in starts[:8]]
                unified = view_state(app.diff)
                start = perf_counter()
                app.set_mode("Split")
                root.update()
                render_ms += elapsed(start)
                assert len(app.diff.editors) == 2 and app.diff.page == 0
                split = view_state(app.diff)
                app.diff.select(1, 10, 11)
                changed = dict(original, body="Verify both rules before release.")
                start = perf_counter()
                store.save(repo, changed, original=original)
                app.reload_notes()
                app.diff.refresh_notes()
                root.update()
                edit_ms = elapsed(start)
                selected, side = app.diff.selected()
                assert side == "new" and [line.new for line in selected] == [10, 11]
                assert app.diff.cards[11].bodies[0].cget("text") == changed["body"]
                updated = view_state(app.diff)
                report = review.markdown(repo, app.stack, app.notes, locations=locations)
                assert report.count("Current location of reviewed code: Staged") == 160
                assert changed["body"] in report
                store.save(repo, original, original=changed)

                app.current = next(f for f in c.files if f.path == "small.py")
                app.lines = git.patch(repo, c, app.current)
                app.mode = "Unified"
                app.notes = []
                small_ms = 0
                for _ in range(3):
                    empty_view()
                    start = perf_counter()
                    app.draw_file()
                    root.update()
                    small_ms += elapsed(start) / 3
                assert not app.diff.cards
                small = view_state(app.diff)
                assert "new disposition" in small[0][0][0]
                assert not callback_errors, callback_errors
                parity = [
                    locations,
                    unified,
                    split,
                    updated,
                    report,
                    side,
                    [line.new for line in selected],
                    small,
                ]
                fingerprint = hashlib.sha256(json.dumps(parity, sort_keys=True).encode()).hexdigest()
                print(
                    json.dumps(
                        {
                            "warmup": iteration == 0,
                            "tracking_ms": tracking_ms,
                            "render_ms": render_ms,
                            "edit_ms": edit_ms,
                            "small_ms": small_ms,
                            "fingerprint": fingerprint,
                        }
                    ),
                    file=output,
                    flush=True,
                )
    finally:
        app.close()


if __name__ == "__main__":
    main(*(Path(arg).resolve() for arg in sys.argv[1:]))
