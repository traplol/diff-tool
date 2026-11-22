"""Branchline's native review workspace."""

from __future__ import annotations

import os
import queue
import sqlite3
import tempfile
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from . import git, suggestions, tracking, ui
from .diffview import DiffView
from .git import ref_name, show
from .review import (
    ReviewConflict,
    Store,
    comparisons,
    file_key,
    location,
    markdown,
    note_matches_file,
    suggestion_source,
)


def clear(widget):
    for child in widget.winfo_children():
        child.destroy()


def caption(parent, value, color=ui.MUTED):
    return ui.label(parent, value, 8, color, bold=True, mono=True, anchor="w")


def pill(parent, value, bg, fg):
    return tk.Label(parent, text=value, bg=bg, fg=fg, padx=7, pady=3, bd=0, font=(ui.MONO, 9))


class App:
    def __init__(self, root, path=None, store=None):
        self.root = root
        ui.configure(root)
        root.title("Branchline")
        root.configure(bg=ui.PAPER)
        width = min(ui.px(1380), root.winfo_screenwidth() - 40)
        height = min(ui.px(860), root.winfo_screenheight() - 80)
        root.geometry(f"{width}x{height}")
        root.minsize(850, 550)
        self.logo = tk.PhotoImage(width=32, height=32)
        self.logo.put(ui.RAIL, to=(0, 0, 32, 32))
        for x in range(5, 26):
            for y in range(4, 28):
                if any(
                    (0 <= (x - a) < 4 and b <= y < 26) or (0 <= b - y <= 7 and 0 <= x - a - (b - y) < 4)
                    for a, b in ((5, 14), (12, 18), (19, 22))
                ):
                    self.logo.put(ui.MINT, (x, y))
        root.iconphoto(True, self.logo)
        self.store = store if store is not None else Store()
        self.repo = self.comparison = self.current = None
        self.stack, self.notes, self.lines = [], [], None
        self.unsaved_receipts = {}
        self.note_locations = {}
        self.tracking_key = None
        self.pair = None
        self.viewed = set()
        self.tab, self.mode = "Changes", "Unified"
        self.comment_scope = tk.StringVar(value="Current stack")
        self.comment_status = tk.StringVar(value="Open")
        self.filter = tk.StringVar()
        self.filter.trace_add("write", lambda *_: self.fill_files() if self.tree is not None else None)
        self.tree = None
        self.commit_list = None
        self.error = ""
        self.work = ThreadPoolExecutor(max_workers=3, thread_name_prefix="git-read")
        self.results = queue.Queue()
        self.jobs = {}
        self.pending_jump = None
        self.status = tk.StringVar(value="Ready")
        self.layout_key = None
        self.pages = {}
        self.file_positions = {}
        self.collapse_overrides = {}
        self.body = self.diff = self.parked_layout = None
        self.shell = tk.PanedWindow(
            root,
            orient="horizontal",
            sashwidth=8,
            bg=ui.RAIL_LINE,
            bd=0,
            opaqueresize=True,
            showhandle=True,
            handlesize=6,
            handlepad=30,
        )
        self.shell.pack(fill="both", expand=True)
        self.sidebar = ui.frame(self.shell, ui.RAIL)
        self.sidebar.pack_propagate(False)
        self.shell.add(
            self.sidebar,
            width=min(self.store.sidebar_width(ui.px(320)), width - 488),
            minsize=174,
            stretch="never",
        )
        self.main = ui.frame(self.shell, ui.PAPER)
        self.shell.add(self.main, minsize=480, stretch="always")
        self.shell.bind(
            "<ButtonRelease-1>", lambda e: self.store.set_sidebar_width(self.shell.sash_coord(0)[0])
        )
        self.shortcuts()
        self.render()
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_id = root.after(35, self.poll)
        if path is not None:
            self.open(path, startup=True)

    def shortcuts(self, widget=None):
        for key, action in (
            ("<Control-o>", self.choose),
            ("<Control-e>", self.export),
            ("<Control-b>", self.stack_dialog),
            ("<F5>", self.refresh),
            ("<Control-f>", self.focus_filter),
            ("<Alt-Down>", lambda: self.next_file(1)),
            ("<Alt-Up>", lambda: self.next_file(-1)),
        ):

            def invoke(event, fn=action):
                if not self.root.tk.call("grab", "current", self.root):
                    fn()
                    return "break"

            (widget or self.root).bind(key, invoke)

    def close(self):
        self.root.after_cancel(self.poll_id)
        self.work.shutdown(wait=False, cancel_futures=True)
        self.store.db.close()
        self.root.destroy()

    def run(self, key, func, done, failed):
        if key is not None:
            self.cancel_job(key)
        future = self.work.submit(func)
        if key is not None:
            self.jobs[key] = future
        future.add_done_callback(lambda f: self.results.put((key, f, done, failed)))

    def cancel_job(self, key):
        future = self.jobs.pop(key, None)
        if future is not None:
            future.cancel()

    def poll(self):
        try:
            while True:
                key, future, done, failed = self.results.get_nowait()
                if key is not None:
                    if self.jobs.get(key) is not future:
                        continue
                    del self.jobs[key]
                error = future.exception()
                if error is None:
                    done(future.result())
                else:
                    failed(str(error))
        except queue.Empty:
            pass
        finally:
            if self.root.winfo_exists():
                self.poll_id = self.root.after(35, self.poll)

    def choose(self):
        p = filedialog.askdirectory(
            title="Open Git repository",
            parent=self.root,
            initialdir=str(self.repo.root if self.repo else Path.cwd()),
        )
        if p:
            self.open(p)

    def open(self, path, startup=False):
        self.status.set("Opening repository…")

        def opened(result):
            repo, suggested = result
            same = self.repo is not None and self.repo.root == repo.root
            previous = self.pair if same else None
            restore_path = file_key(self.current) if same and self.current else None
            for key in list(self.jobs):
                self.cancel_job(key)
            self.tracking_key = None
            self.repo, self.stack = repo, suggested
            self.root.title(f"{show(repo.root.name)} · Branchline")
            if not same:
                self.note_locations.clear()
                self.tab = "Changes"
                self.collapse_overrides.clear()
                self.comment_scope.set("Current stack")
                self.comment_status.set("Open")
                self.drop_pages()
                self.filter.set("")
            self.reload_notes()
            opts = self.review_pairs()
            if previous and previous[1] == git.WORKTREE:
                previous = opts[-1]
            self.load(previous if previous in opts else opts[0], restore_path)

        def failed(msg):
            self.status.set("Choose a Git working directory.")
            if not startup or "not a git repository" not in msg:
                messagebox.showerror("Could not open repository", msg, parent=self.root)

        def choose_stack(repo):
            saved = self.store.stack(repo, fallback=[])
            if saved or not repo.initial:
                opened((repo, saved))
                return

            def discover():
                branch = repo.initial[-1]
                stack, _ = git.discover_stack(repo, repo.default_branch or repo.initial[0], branch)
                return repo, stack if len(stack) >= 2 else repo.initial

            self.run("open", discover, opened, failed)

        self.run("open", lambda: git.open_repo(path), choose_stack, failed)

    def refresh(self):
        self.open(self.repo.root if self.repo else Path.cwd())

    def review_pairs(self):
        return [*comparisons(self.stack), (self.repo.checkout, git.WORKTREE)]

    def workspace_key(self):
        return (self.repo.root, self.repo.checkout, tuple(self.stack)) if self.repo else ()

    def load(self, pair, restore_path=None, jump=None):
        repo = self.repo
        stack, notes = self.stack.copy(), self.notes.copy()
        tracking_key = (stack, notes)
        cached = self.note_locations if self.tracking_key == tracking_key and pair[1] != git.WORKTREE else None
        self.status.set("Reading comparison…")
        if self.layout_key != self.workspace_key():
            self.pair = pair
            self.comparison = self.current = self.lines = self.commit_list = None
            self.error = ""
            self.render()

        def read():
            c = git.compare(repo, *pair)
            locations = cached if cached is not None else tracking.locate_notes(repo, stack, c, notes)
            anchor = None
            if jump:
                for f in c.files:
                    anchor = self.anchor_at(c, f, jump, locations)
                    if anchor is not None:
                        break
                target = f if anchor is not None else None
            else:
                target = next((f for f in c.files if file_key(f) == restore_path), None)
            target = target or next(iter(c.files), None)
            try:
                lines = git.patch(repo, c, target) if target and not target.binary else []
                return c, target, lines, "", locations, anchor
            except git.GitError as error:
                return c, target, None, str(error), locations, None

        def ready(result):
            c, target, lines, patch_error, self.note_locations, anchor = result
            self.tracking_key = tracking_key
            same_file = self.pair == pair and self.current == target and target is not None
            same_view = (
                self.comparison == c
                and self.current == target
                and self.lines == lines
                and not self.error
                and not patch_error
                and jump is None
            )
            self.pair, self.comparison = pair, c
            if same_view:
                self.status.set("Comparison up to date")
                self.render()
                if self.tree is not None:
                    new_viewed = self.store.viewed(repo, c)
                    if new_viewed != self.viewed:
                        self.viewed = new_viewed
                        self.fill_files()
                        self.update_progress()
                        if self.diff:
                            self.diff.viewed.set(file_key(target) in new_viewed)
                if self.diff:
                    self.diff.refresh_notes()
                if "Comments" in self.pages:
                    self.update_comments()
                return
            self.cancel_job("patch")
            self.cancel_job("commits")
            position = (
                self.diff.position()
                if same_file and target.group and self.diff and self.diff.file == target and not jump
                else None
            )
            self.current, self.lines, self.patch_error = target, lines, patch_error
            stale = jump is not None and anchor is None
            self.pending_jump, self.commit_list, self.error = anchor, None, ""
            self.viewed = self.store.viewed(repo, c)
            self.drop_pages()
            if position:
                self.file_positions[file_key(target)] = position
            self.status.set("Comparison up to date")
            self.render()
            if stale:
                self.status.set("The file has changed. Showing the saved comment.")
                self.compose(jump)
            if self.tab == "Commits":
                self.load_commits()

        def failed(message):
            self.tracking_key = None
            self.note_locations.clear()
            self.cancel_job("patch")
            self.cancel_job("commits")
            self.pair, self.comparison, self.current, self.lines = pair, None, None, None
            self.commit_list, self.error = None, message
            self.drop_pages()
            self.status.set("Comparison unavailable")
            self.render()

        self.run("comparison", read, ready, failed)

    def drop_pages(self):
        for page in self.pages.values():
            page.destroy()
        self.pages.clear()
        self.file_positions.clear()
        self.body = self.tree = self.diff = self.parked_layout = None

    def active_notes(self, notes=None):
        if notes is None:
            notes = self.notes
        if self.review_scope() == "Working tree":
            return [n for n in notes if (n["left"], n["right"]) == self.pair]
        pairs = comparisons(self.stack)
        pairs.extend((ref, git.WORKTREE) for ref in self.stack_refs())
        return [n for n in notes if (n["left"], n["right"]) in pairs]

    @staticmethod
    def anchor_at(comparison, file, note, locations):
        for dest in locations.get(note["id"], ()):
            if (dest["left"], dest["right"]) == (comparison.left, comparison.right):
                if dest["path"] == file.path and dest["group"] == file.group:
                    return dict(note, old=dest["old"], new=dest["new"])
                return None
        if note_matches_file(comparison, file, note):
            return note
        return None

    def original_note(self, note):
        return next(n for n in self.notes if n["id"] == note["id"])

    def read_notes(self):
        notes = self.store.notes(self.repo)
        for note in notes:
            receipt = self.unsaved_receipts.get((self.repo.root, note["id"]))
            if receipt is None:
                continue
            if receipt["suggestion"] == note.get("suggestion") and not note.get("applied_location"):
                note.update(
                    applied_location=receipt["applied_location"], applied_anchor=receipt["applied_anchor"]
                )
            elif receipt["applied_anchor"] != note.get("applied_anchor"):
                note["earlier_application"] = receipt
        return notes

    def reload_notes(self):
        self.notes = self.read_notes()
        # Drop a manual choice once the saved status supplies the same default.
        for note in self.notes:
            if self.collapse_overrides.get(note["id"]) == note["resolved"]:
                del self.collapse_overrides[note["id"]]

    def is_note_collapsed(self, note):
        return self.collapse_overrides.get(note["id"], note["resolved"])

    def set_note_collapsed(self, note, collapsed):
        if collapsed == note["resolved"]:
            self.collapse_overrides.pop(note["id"], None)
        else:
            self.collapse_overrides[note["id"]] = collapsed

    def locations_for(self, note):
        if note["id"] in self.note_locations:
            return self.note_locations[note["id"]]
        # A note saved since the last refresh already has an exact position.
        c = self.comparison
        if c:
            for f in c.files:
                if note_matches_file(c, f, note):
                    return [tracking.location_for(c, f, note)]
        return []

    def jump_location(self, note):
        locations = self.locations_for(note)
        if not locations:
            return None
        # Stay in the open comparison when possible. Otherwise prefer the
        # working copy, then the branch's own layer, then the full stack.
        return min(
            locations,
            key=lambda d: (
                (d["left"], d["right"]) != self.pair,
                d["right"] != git.WORKTREE,
                d["right"] != note["left"],
            ),
        )

    def stack_refs(self):
        return [self.repo.checkout if ref == "HEAD" else ref for ref in self.stack]

    def review_scope(self):
        if self.pair and self.pair[1] == git.WORKTREE and self.repo.checkout not in self.stack_refs():
            return "Working tree"
        return "Current stack"

    def showing_repository_notes(self):
        return self.tab == "Comments" and self.comment_scope.get() == "Entire repository"

    def navigate(self, tab):
        if self.tab == tab:
            return
        self.tab = tab
        if tab == "Commits" and self.pair[1] == git.WORKTREE and self.stack:
            self.load(comparisons(self.stack)[0])
            return
        self.render()
        if tab == "Commits" and self.commit_list is None and self.comparison:
            self.load_commits()

    def render(self):
        key = self.workspace_key()
        if key != self.layout_key:
            self.drop_pages()
            self.layout_key = key
            self.build_workspace()
        if not self.repo:
            return
        self.update_chrome()
        self.show_page()

    def build_workspace(self):
        clear(self.sidebar)
        clear(self.main)
        self.draw_sidebar()
        top = ui.frame(self.main, ui.WHITE, height=ui.px(58))
        top.pack(fill="x")
        top.pack_propagate(False)
        crumb = ui.frame(top)
        crumb.pack(side="left", padx=24, fill="y")
        ui.glyph(crumb, "folder", ui.MUTED, 16).pack(side="left", padx=(0, 8))
        ui.label(crumb, "Workspace", 9, ui.MUTED).pack(side="left")
        if self.repo:
            ui.label(crumb, " / ", 10, ui.MUTED).pack(side="left", padx=4)
            ui.label(crumb, show(self.repo.root.name), 9, ui.INK, True, anchor="w").pack(side="left")
        if self.repo:
            ui.Button(
                top,
                "Export Markdown",
                self.export,
                symbol="export",
                fill=ui.MINT,
                hover="#a4e584",
                color=ui.RAIL,
                bold=True,
            ).pack(side="right", padx=20, pady=12, before=crumb)
        ui.rule(self.main)
        foot = ui.frame(self.main, ui.PAPER)
        foot.pack(side="bottom", fill="x")
        ui.rule(foot)
        ui.label(foot, "●  Local Git", 8, ui.GREEN).pack(side="left", padx=(20, 12), pady=6)
        tk.Label(foot, textvariable=self.status, bg=ui.PAPER, fg=ui.MUTED, font=(ui.UI, 8), anchor="w").pack(
            side="left", fill="x", expand=True
        )
        if not self.repo:
            self.welcome()
            return
        hero = ui.frame(self.main, ui.PAPER)
        hero.pack(fill="x", padx=24, pady=(18, 16))
        if self.main.winfo_width() > ui.px(850):
            art = tk.Canvas(hero, width=215, height=75, bg=ui.PAPER, bd=0, highlightthickness=0)
            art.pack(side="right")
            art.bind("<Configure>", lambda e: ui.artwork(e.widget))
        self.hero_title = ui.label(hero, "", 24, ui.INK, True, anchor="w")
        self.hero_title.pack(anchor="w")
        refs = ui.frame(hero)
        refs.pack(anchor="w", fill="x", pady=(6, 0))
        opts = self.review_pairs()
        labels = [
            "Working tree" if right == git.WORKTREE else "Full stack" if i == 0 else f"Layer {i}"
            for i, (_, right) in enumerate(opts)
        ]
        select = ttk.Combobox(refs, values=labels, state="readonly", width=13, font=(ui.UI, 9))
        self.layer_select = select
        select.pack(side="left", padx=(0, 9))

        def choose_comparison(event):
            self.filter.set("")
            if opts[select.current()][1] == git.WORKTREE:
                self.tab = "Changes"
            self.load(opts[select.current()])

        select.bind("<<ComboboxSelected>>", choose_comparison)
        self.ref_labels = []
        if self.pair:
            ui.glyph(refs, "branch", ui.GREEN, 16).pack(side="left", padx=(0, 5))
            for i, ref in enumerate(self.pair):
                if i:
                    ui.glyph(refs, "arrow", ui.MUTED, 15).pack(side="left", padx=7)
                label = ui.label(refs, "", 9, ui.SUB, mono=True)
                label.pack(side="left")
                self.ref_labels.append(label)
        self.page_host = ui.frame(self.main, ui.WHITE, highlightthickness=1, highlightbackground=ui.LINE)
        self.page_host.pack(fill="both", expand=True, padx=22, pady=(0, 18))

    def update_chrome(self):
        titles = {"Changes": "Branch review", "Commits": "Commit history", "Comments": "Review comments"}
        self.hero_title.configure(
            text="Working tree" if self.tab == "Changes" and self.pair[1] == git.WORKTREE else titles[self.tab]
        )
        for label, ref in zip(self.ref_labels, self.pair):
            label.configure(text=show(ref_name(ref)))
        if self.layer_select:
            self.layer_select.current(self.review_pairs().index(self.pair))
        for tab, (control, badge) in self.nav.items():
            selected = tab == self.tab
            control.fill = ui.RAIL_LINE if selected else ui.RAIL
            control.color = ui.MINT if selected else "#c9d5cc"
            control.font.configure(weight="bold" if selected else "normal")
            control.paint()
            if tab == "Changes":
                badge.configure(text=str(len(self.comparison.files)) if self.comparison else "…")
            elif tab == "Comments":
                badge.configure(
                    text=str(len(self.notes if self.showing_repository_notes() else self.active_notes()))
                )

    def show_page(self):
        previous = self.body
        existing = self.pages.get(self.tab)
        if existing is not None and previous is existing:
            return
        self.body = existing if existing is not None else ui.frame(self.page_host, ui.WHITE)
        if existing is None:
            self.pages[self.tab] = self.body
            self.populate_page()
        if previous is not None:
            previous.pack_forget()
        self.body.pack(fill="both", expand=True)

    def populate_page(self):
        if self.tab == "Comments":
            self.comments_page()
        elif self.error:
            self.empty(self.body, "Comparison unavailable", self.error, "branch")
        elif not self.comparison:
            self.empty(self.body, "Reading comparison…", "", "branch")
        elif self.tab == "Commits":
            self.commits_page()
        else:
            self.changes_page()

    def draw_sidebar(self):
        side = self.sidebar
        brand = ui.frame(side)
        brand.pack(fill="x", padx=18, pady=(22, 25))
        mark = tk.Canvas(brand, width=32, height=32, bg=ui.RAIL, highlightthickness=0)
        mark.pack(side="left", padx=(0, 8))
        ui.rounded(mark, 0, 0, 32, 32, 8, ui.MINT)
        ui.icon(mark, "brand", 4, 3, 25, ui.RAIL)
        ui.label(brand, "Branchline", 18, "#f3f8ee", True).pack(side="left")
        caption(side, "REPOSITORY", ui.RAIL_MUTED).pack(anchor="w", padx=20, pady=(2, 7))
        repo_name = show(self.repo.root.name) if self.repo else "Open directory"
        ui.Button(
            side,
            repo_name + "   ▾",
            self.choose,
            symbol="folder",
            fill=ui.RAIL_SOFT,
            hover=ui.RAIL_LINE,
            color="#eef4ed",
            border=ui.RAIL_LINE,
            align="left",
            height=39,
            bold=True,
        ).pack(fill="x", padx=12)
        if self.repo:
            ui.rule(side, ui.RAIL_LINE, padx=16, pady=(15, 16))
            caption(side, "REVIEW", ui.RAIL_MUTED).pack(anchor="w", padx=20, pady=(0, 6))
            self.nav = {}
            for title, symbol in (("Changes", "changes"), ("Commits", "commit"), ("Comments", "comment")):
                if title == "Commits" and not self.stack:
                    continue
                selected = self.tab == title
                tab = ui.frame(side, ui.RAIL)
                tab.pack(fill="x", padx=10, pady=2)
                control = ui.Button(
                    tab,
                    title,
                    lambda t=title: self.navigate(t),
                    symbol=symbol,
                    color=ui.MINT if selected else "#c9d5cc",
                    fill=ui.RAIL_LINE if selected else ui.RAIL,
                    hover=ui.RAIL_SOFT,
                    align="left",
                    height=36,
                    bold=selected,
                    size=10,
                )
                control.pack(fill="x")
                badge = None
                if title != "Commits":
                    badge = tk.Label(
                        control,
                        text="",
                        font=(ui.MONO, 8),
                        bd=0,
                        padx=5,
                        bg=ui.RAIL_SOFT,
                        fg=ui.RAIL_MUTED,
                    )
                    badge.place(relx=1, x=-12, rely=0.5, anchor="e")
                    badge.bind("<Button-1>", lambda e, t=title: self.navigate(t))
                self.nav[title] = control, badge
        if self.stack:
            ui.rule(side, ui.RAIL_LINE, padx=16, pady=(16, 16))
            caption(side, "BRANCH STACK", ui.RAIL_MUTED).pack(anchor="w", padx=20, pady=(0, 5))
            # Keep the base and tip visible on short displays and long stacks.
            indices = (
                list(range(len(self.stack)))
                if len(self.stack) <= 5
                else [0, 1, None, len(self.stack) - 2, len(self.stack) - 1]
            )
            for i in indices:
                if i is None:
                    ui.label(side, f"       ···   {len(self.stack) - 4} more", 9, ui.RAIL_MUTED).pack(
                        anchor="w"
                    )
                    continue
                item = ui.frame(side)
                item.pack(fill="x", padx=(20, 12))
                node = tk.Canvas(item, width=15, height=40, bg=ui.RAIL, highlightthickness=0)
                node.pack(side="left", padx=(0, 8))
                if i > 0:
                    node.create_line(7, 0, 7, 20, fill="#648674", width=1.5)
                if i < len(self.stack) - 1:
                    node.create_line(7, 20, 7, 40, fill="#648674", width=1.5)
                node.create_oval(
                    3,
                    16,
                    11,
                    24,
                    outline=ui.MINT,
                    fill=ui.MINT if i == len(self.stack) - 1 else ui.RAIL,
                    width=1.5,
                )
                names = ui.frame(item)
                names.pack(side="left", fill="x", expand=True)
                ui.label(
                    names,
                    "Base" if i == 0 else "Head" if i == len(self.stack) - 1 else f"Layer {i}",
                    8,
                    ui.RAIL_MUTED,
                ).pack(anchor="w")
                name = show(ref_name(self.stack[i]))
                ui.label(
                    names,
                    name,
                    9,
                    "#e5eee5",
                    mono=True,
                    anchor="w",
                ).pack(fill="x")
            ui.Button(
                side,
                "Edit stack",
                self.stack_dialog,
                symbol="sliders",
                fill=ui.RAIL,
                hover=ui.RAIL_SOFT,
                color=ui.RAIL_MUTED,
                align="left",
                height=30,
            ).pack(fill="x", padx=13, pady=6)
        bottom = ui.frame(side)
        bottom.pack(side="bottom", fill="x", pady=12, padx=12)
        ui.rule(bottom, ui.RAIL_LINE, pady=(0, 8))
        ui.Button(
            bottom,
            "Refresh",
            self.refresh,
            symbol="refresh",
            fill=ui.RAIL,
            hover=ui.RAIL_SOFT,
            color=ui.RAIL_MUTED,
            height=29,
            align="left",
        ).pack(fill="x")

    def welcome(self):
        panel = ui.frame(self.main, ui.WHITE, highlightthickness=1, highlightbackground=ui.LINE)
        panel.pack(expand=True, fill="both", padx=26, pady=24)
        holder = ui.frame(panel)
        holder.place(relx=0.5, rely=0.48, anchor="center", relwidth=0.83)
        art = tk.Canvas(holder, height=150, highlightthickness=0, bd=0, bg="#e8efe4")
        art.pack(fill="x", pady=(0, 24))
        art.bind("<Configure>", lambda e: ui.artwork(e.widget, True))
        ui.label(holder, "Open a repository", 24, ui.INK, True).pack()
        ui.label(
            holder,
            "Choose a Git working directory to review local changes or a branch stack.",
            10,
            ui.MUTED,
            wraplength=490,
        ).pack(pady=(8, 18))
        actions = ui.frame(holder)
        actions.pack()
        ui.Button(
            actions,
            "Open repository",
            self.choose,
            symbol="folder",
            fill=ui.MINT,
            hover="#a4e584",
            bold=True,
            height=36,
        ).pack(side="left")

    def empty(self, parent, title, detail, symbol):
        content = ui.frame(parent)
        content.place(relx=0.5, rely=0.48, anchor="center", relwidth=0.92)
        ui.glyph(content, symbol, ui.MUTED, 27).pack(pady=(0, 9))
        ui.label(content, title, 15, ui.INK, True).pack()
        if detail:
            ui.label(content, detail, 10, ui.MUTED, wraplength=420).pack(pady=7)

    def changes_page(self):
        heading = ui.frame(self.body)
        heading.pack(fill="x", padx=16, pady=12)
        ui.glyph(heading, "changes", ui.GREEN).pack(side="left", padx=(0, 7))
        ui.label(heading, "Changed files", 12, ui.INK, True).pack(side="left")
        files = self.comparison.files
        self.file_count = pill(heading, str(len(files)), ui.PAPER, ui.SUB)
        self.file_count.pack(side="left", padx=8)
        pill(heading, f"−{sum(f.removed or 0 for f in files)}", ui.DELETE, ui.RED).pack(side="right")
        pill(heading, f"+{sum(f.added or 0 for f in files)}", ui.ADD, ui.GREEN).pack(side="right", padx=5)
        ui.rule(self.body)
        if not files:
            area = ui.frame(self.body)
            area.pack(fill="both", expand=True)
            if self.pair[1] == git.WORKTREE:
                self.empty(area, "Working tree is clean", "Refresh after editing or staging files.", "check")
            else:
                self.empty(area, "No changed files", "The compared snapshots have identical trees.", "check")
            return
        panes = tk.PanedWindow(
            self.body,
            orient="horizontal",
            sashwidth=4,
            sashrelief="flat",
            bg=ui.LINE,
            bd=0,
            showhandle=False,
            opaqueresize=True,
        )
        panes.pack(fill="both", expand=True)
        explorer = ui.frame(panes, ui.WHITE)
        panes.add(explorer, width=ui.px(222), minsize=140, stretch="never")
        self.detail = ui.frame(panes, ui.WHITE)
        panes.add(self.detail, minsize=290, stretch="always")
        search = ui.frame(explorer, ui.PAPER, highlightthickness=1, highlightbackground=ui.LINE)
        search.pack(fill="x", padx=10, pady=10)
        ui.glyph(search, "search", ui.MUTED, 15).pack(side="left", padx=(8, 2))
        self.search = tk.Entry(
            search,
            textvariable=self.filter,
            bg=ui.PAPER,
            fg=ui.INK,
            insertbackground=ui.INK,
            font=(ui.UI, 9),
            width=8,
            bd=0,
            highlightthickness=0,
        )
        self.search.pack(side="left", fill="x", expand=True, pady=6, padx=3)
        self.clear_filter = ui.Button(search, "×", self.reset_filter, fill=ui.PAPER, height=25, pad=6)
        self.hint = ui.label(self.search, "Filter files", 9, ui.MUTED)
        self.hint.bind("<Button-1>", lambda e: self.search.focus_set())
        self.search.bind("<FocusIn>", lambda e: self.hint.place_forget())
        self.search.bind("<FocusOut>", lambda e: self.search_hint())
        self.search.bind("<Escape>", self.reset_filter)
        self.search.bind("<Down>", lambda e: self.tree.focus_set() or "break")
        self.search.bind("<Return>", self.open_filtered_file)
        progress = ui.frame(explorer, ui.PAPER)
        progress.pack(side="bottom", fill="x")
        ui.rule(progress)
        self.progress_text = ui.label(progress, "", 9, ui.SUB, anchor="w")
        self.progress_text.pack(fill="x", padx=12, pady=(7, 4))
        track = ui.frame(progress, ui.LINE, height=3)
        track.pack(fill="x", padx=12, pady=(0, 9))
        self.progress_bar = ui.frame(track, "#70a065")
        self.update_progress()
        tree_area = ui.frame(explorer)
        tree_area.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tree_area, columns=("status",), show="tree", selectmode="browse", height=1)
        self.tree.column("#0", width=152, minwidth=60, stretch=True)
        self.tree.column("status", width=ui.px(26), minwidth=ui.px(24), stretch=False, anchor="center")
        sy = ttk.Scrollbar(tree_area, command=self.tree.yview)
        sy.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sy.set)
        self.tree.pack(fill="both", expand=True)
        self.tree.tag_configure("folder", foreground=ui.MUTED, font=(ui.UI, 9, "bold"))
        self.tree.tag_configure("seen", foreground=ui.MUTED)
        self.tree.tag_configure("A", foreground=ui.GREEN)
        self.tree.tag_configure("D", foreground=ui.RED)
        self.tree.bind("<<TreeviewSelect>>", self.tree_selected)
        self.tree.bind("<Return>", self.open_filtered_file)
        self.tree.bind("<Escape>", self.reset_filter)
        self.fill_files()
        self.draw_file()

    def search_hint(self):
        if not self.filter.get() and not ui.has_focus(self.search):
            self.hint.place(x=2, rely=0.5, anchor="w")
        else:
            self.hint.place_forget()

    def focus_filter(self):
        if self.comparison and self.comparison.files:
            if self.tab != "Changes":
                self.navigate("Changes")
            self.search.focus_set()
            self.search.select_range(0, "end")

    def reset_filter(self, event=None):
        self.filter.set("")
        self.search.focus_set()
        return "break"

    def open_filtered_file(self, event=None):
        if event and event.widget is self.tree and self.tree.focus() not in self.file_ids:
            return
        if self.current and self.current in self.file_ids.values():
            if self.lines is None:
                self.pick(self.current, focus_code=True)
            else:
                self.focus_code()
        return "break"

    def fill_files(self):
        tree = self.tree
        self.search_hint()
        tree.delete(*tree.get_children())
        self.file_ids = {}
        folders = {}
        groups = {}
        query = self.filter.get().casefold()
        if query:
            self.clear_filter.pack(side="right", before=self.search)
        else:
            self.clear_filter.pack_forget()
        for i, f in enumerate(self.comparison.files):
            if query not in f.path.casefold() and query not in f.old.casefold():
                continue
            parent, _, name = f.path.rpartition("/")
            if f.group and f.group not in groups:
                groups[f.group] = tree.insert("", "end", text=f.group, open=True, tags=("folder",))
            container = groups.get(f.group, "")
            if parent:
                folder = (f.group, parent)
                if folder not in folders:
                    folders[folder] = tree.insert(
                        container, "end", text=show(parent) + "/", open=True, tags=("folder",)
                    )
                container = folders[folder]
            iid = f"file{i}"
            done = file_key(f) in self.viewed
            tree.insert(
                container,
                "end",
                iid=iid,
                text=show(name),
                values=("✓" if done else f.status,),
                tags=("seen",) if done else (f.status,),
            )
            self.file_ids[iid] = f
            if self.current == f:
                tree.selection_set(iid)
                tree.focus(iid)
                tree.see(iid)
        count = len(self.file_ids)
        total = len(self.comparison.files)
        self.file_count.configure(text=f"{count} / {total}" if query else str(total))
        if not self.file_ids:
            tree.insert("", "end", text="No matching files", tags=("folder",))
            self.cancel_job("patch")
            self.remember_file()
            self.current = self.lines = self.pending_jump = None
            self.draw_file()
            self.status.set("No files match the filter")
        elif self.current not in self.file_ids.values():
            self.pending_jump = None
            self.pick(next(iter(self.file_ids.values())))

    def tree_selected(self, event):
        if event.widget != self.tree:
            return
        selected = self.tree.selection()
        if selected and selected[0] in self.file_ids:
            f = self.file_ids[selected[0]]
            if self.current != f:
                self.pick(f)

    def pick(self, f, *, focus_code=False):
        self.remember_file()
        self.current, self.lines = f, None
        self.patch_error = ""
        if self.tree is not None:
            iid = next((k for k, v in self.file_ids.items() if v == f), None)
            if iid:
                self.tree.selection_set(iid)
                self.tree.focus(iid)
                self.tree.see(iid)
        repo, c = self.repo, self.comparison
        self.status.set(f"Reading {show(f.path)}…")

        def got(lines):
            self.lines = lines
            self.status.set("Comparison up to date")
            if "Changes" in self.pages:
                self.draw_file()
                if focus_code and self.tab == "Changes":
                    self.focus_code()

        def failed(msg):
            self.patch_error = msg
            self.status.set("Could not read diff")
            if "Changes" in self.pages:
                self.draw_file()

        self.run("patch", lambda: git.patch(repo, c, f) if not f.binary else [], got, failed)

    def focus_code(self):
        if self.diff and self.diff.editors:
            col = self.diff.selection[0] if self.diff.selection else int(self.diff.dual)
            self.diff.editors[col].focus_set()
        elif self.tree is not None:
            self.tree.focus_set()

    def next_file(self, delta):
        if self.tab != "Changes" or self.tree is None or not self.file_ids:
            return
        files = list(self.file_ids.values())
        idx = files.index(self.current) if self.current in files else -1
        self.pick(files[(idx + delta) % len(files)])

    def remember_file(self):
        if self.diff and self.diff.winfo_viewable():
            self.file_positions[file_key(self.diff.file)] = self.diff.position()

    def draw_file(self):
        clear(self.detail)
        self.diff = self.parked_layout = None
        if not self.current:
            if self.filter.get():
                self.empty(
                    self.detail,
                    "No files match the filter",
                    "Change the search or press Escape in the filter to clear it.",
                    "search",
                )
            else:
                self.empty(self.detail, "Select a file", "", "file")
            return
        f = self.current
        top = ui.frame(self.detail)
        top.pack(fill="x", padx=13, pady=11)
        ui.glyph(top, "file", ui.SUB, 16).pack(side="left", padx=(0, 7))
        if f.added is not None:
            ui.label(top, f"−{f.removed}", 9, ui.RED, mono=True).pack(side="right", padx=(5, 0))
            ui.label(top, f"+{f.added}", 9, ui.GREEN, mono=True).pack(side="right", padx=(8, 0))
        status = {
            "A": "Added",
            "D": "Deleted",
            "R": "Renamed",
            "M": "Modified",
            "T": "Type changed",
            "U": "Unmerged",
        }.get(f.status, f.status)
        pill(top, status, ui.PAPER, ui.SUB).pack(side="right", padx=(5, 0))
        if f.group:
            pill(top, f.group, ui.PALE, ui.GREEN).pack(side="right", padx=(5, 0))
        ui.label(top, show(f.path), 10, ui.INK, True, mono=True, anchor="w").pack(
            side="left", fill="x", expand=True
        )
        if f.status == "R":
            ui.label(self.detail, "Renamed from " + show(f.old), 9, ui.MUTED, anchor="w").pack(
                fill="x", padx=14, pady=(0, 7)
            )
        ui.rule(self.detail)
        if self.lines is not None:
            self.diff = DiffView(
                self.detail, self, f, self.lines, self.pending_jump, self.file_positions.get(file_key(f))
            )
            self.diff.pack(fill="both", expand=True)
            self.pending_jump = None
        else:
            area = ui.frame(self.detail)
            area.pack(fill="both", expand=True)
            self.empty(
                area, "Could not read diff" if self.patch_error else "Reading diff…", self.patch_error, "file"
            )

    def set_mode(self, mode):
        if self.mode == mode:
            return
        self.mode = mode
        if self.lines is None:
            return
        self.remember_file()
        if not self.lines or not self.diff or self.pending_jump or not self.detail.winfo_viewable():
            self.draw_file()
        else:
            # Retain only the current file's opposite layout. Other draw paths destroy both.
            incoming, folds = self.parked_layout or (None, None)
            self.parked_layout = (self.diff, self.collapse_overrides.copy())
            self.diff.pack_forget()
            position = self.file_positions.get(file_key(self.current))
            if incoming and (folds != self.collapse_overrides or incoming.notes != incoming.file_notes()):
                incoming.destroy()
                incoming = None
            if incoming is None:
                incoming = DiffView(self.detail, self, self.current, self.lines, position=position)
            else:
                incoming.viewed.set(file_key(self.current) in self.viewed)
                incoming.restore_position(position)
            self.diff = incoming
            incoming.pack(fill="both", expand=True)
        self.focus_code()

    def mark_viewed(self, change, value):
        key = file_key(change)
        self.store.set_viewed(self.repo, self.comparison, change, value)
        if value:
            self.viewed.add(key)
        else:
            self.viewed.discard(key)
        self.update_progress()
        for iid, f in self.file_ids.items():
            if f == change:
                self.tree.item(
                    iid, values=("✓" if value else f.status,), tags=("seen",) if value else (f.status,)
                )

    def update_progress(self):
        total = len(self.comparison.files)
        self.progress_text.configure(text=f"{len(self.viewed)} of {total} files viewed")
        self.progress_bar.place(relheight=1, relwidth=len(self.viewed) / total)

    def load_commits(self):
        repo, c = self.repo, self.comparison
        if not c or c.right == git.WORKTREE:
            return

        def ready(value):
            self.commit_list = value
            if "Commits" in self.pages:
                self.fill_commits()

        def failed(msg):
            self.status.set(msg)
            if "Commits" in self.pages:
                self.commit_heading.configure(text="Could not read commits")

        self.run("commits", lambda: git.commits(repo, c), ready, failed)

    def commits_page(self):
        heading = ui.frame(self.body)
        heading.pack(fill="x", padx=16, pady=9)
        self.commit_heading = ui.label(heading, "Reading commits…", 12, ui.INK, True)
        self.commit_heading.pack(side="left")
        ui.rule(self.body)
        columns = ("subject", "author", "date", "sha")
        table = ttk.Treeview(self.body, columns=columns, show="headings", selectmode="browse")
        for col, name, width in zip(
            columns, ("Commit message", "Author", "Date", "Commit"), (320, 130, 100, 86)
        ):
            table.heading(col, text=name, anchor="w")
            table.column(col, width=ui.px(width), minwidth=45, stretch=col in ("subject", "author"))
        horizontal = ttk.Scrollbar(self.body, orient="horizontal", command=table.xview)
        horizontal.pack(side="bottom", fill="x")
        scroll = ttk.Scrollbar(self.body, command=table.yview)
        scroll.pack(side="right", fill="y")
        table.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        table.pack(fill="both", expand=True)
        self.commit_table = table
        if self.commit_list is not None:
            self.fill_commits()

        def fit():
            style = ttk.Style(table)
            cell_font = tkfont.Font(font=style.lookup("Treeview", "font") or "TkDefaultFont")
            heading_font = tkfont.Font(font=style.lookup("Treeview.Heading", "font") or "TkHeadingFont")
            rows = table.get_children()
            for col in columns:
                width = max(
                    heading_font.measure(table.heading(col, "text")),
                    max((cell_font.measure(table.set(row, col)) for row in rows), default=0),
                )
                table.column(col, width=width + 20, stretch=False)

        ui.Button(heading, "Fit columns to content", fit, border=ui.LINE, height=30).pack(side="right")
        menu = tk.Menu(table, tearoff=False)

        def context(event):
            region = table.identify_region(event.x, event.y)
            row = table.identify_row(event.y)
            menu.delete(0, "end")
            if region == "cell" and row:
                col = table.identify_column(event.x)
                table.selection_set(row)
                table.focus(row)
                menu.add_command(label="Copy value", command=lambda: self.copy_text(table.set(row, col)))
                menu.add_command(
                    label="Copy row",
                    command=lambda: self.copy_text("\t".join(table.set(row, k) for k in columns)),
                )
                menu.add_command(label="Copy full SHA", command=lambda: self.copy_text(row))
                menu.add_separator()
                menu.add_command(label="Commit details…", command=lambda: self.commit_details(row))
                menu.add_separator()
            menu.add_command(label="Fit columns to content", command=fit)
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()
            return "break"

        table.bind("<Button-3>", context)
        table.bind("<Return>", lambda e: self.commit_details(table.focus()) if table.focus() else None)

    def fill_commits(self):
        self.commit_heading.configure(text=f"Commits  ·  {len(self.commit_list)}")
        for sha, author, date, subject in self.commit_list:
            self.commit_table.insert("", "end", iid=sha, values=(subject, author, date, sha[:9]))

    def copy_text(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status.set("Copied to clipboard")

    def commit_details(self, sha):
        top = self.dialog("Commit details", 720, 510)
        ui.label(top, "Commit details", 18, ui.INK, True).pack(anchor="w", padx=16, pady=12)
        text = tk.Text(top, wrap="word", font=(ui.MONO, 10), bg=ui.WHITE, fg=ui.INK, bd=0, padx=12, pady=10)
        scroll = ttk.Scrollbar(top, command=text.yview)
        scroll.pack(side="right", fill="y")
        text.configure(yscrollcommand=scroll.set)
        text.pack(fill="both", expand=True)

        def display(value):
            if top.winfo_exists():
                text.configure(state="normal")
                text.delete("1.0", "end")
                text.insert("1.0", value)
                text.configure(state="disabled")

        display("Reading commit…")
        repo = self.repo
        self.run(
            "commit_details",
            lambda: git.git(
                repo.root,
                "show",
                "--format=fuller",
                "--stat",
                "--date=iso",
                "--no-color",
                "--no-ext-diff",
                "--no-textconv",
                "--no-show-signature",
                sha,
                "--",
            ).decode(errors="replace"),
            display,
            display,
        )

    def comments_page(self):
        heading = ui.frame(self.body)
        heading.pack(fill="x", padx=16, pady=10)
        self.comments_heading = ui.label(heading, "Comments", 12, ui.INK, True)
        self.comments_heading.pack(anchor="w")
        filters = ui.frame(heading)
        filters.pack(fill="x", pady=(6, 0))
        for status in ("Open", "Resolved", "All"):
            tk.Radiobutton(
                filters,
                text=status,
                value=status,
                variable=self.comment_status,
                command=self.update_comments,
                indicatoron=False,
                takefocus=True,
                font=(ui.UI, 9),
                bg=ui.WHITE,
                fg=ui.INK,
                selectcolor=ui.MINT,
                activebackground=ui.PALE,
                highlightcolor=ui.GREEN,
                highlightbackground=ui.LINE,
                borderwidth=1,
                relief="flat",
                offrelief="flat",
                padx=ui.px(10),
                pady=ui.px(3),
            ).pack(side="left")
        if self.comment_scope.get() != "Entire repository":
            self.comment_scope.set(self.review_scope())
        scope = ttk.Combobox(
            filters,
            textvariable=self.comment_scope,
            values=(self.review_scope(), "Entire repository"),
            state="readonly",
            width=17,
            font=(ui.UI, 9),
        )
        scope.pack(side="right")
        scope.bind("<<ComboboxSelected>>", lambda e: self.update_comments())
        ui.rule(self.body)
        area = ui.frame(self.body)
        table = ttk.Treeview(
            area,
            columns=("path", "comparison", "lines", "status", "body"),
            show="headings",
            selectmode="browse",
        )
        for col, txt, width in (
            ("path", "File", 210),
            ("comparison", "Comparison", 240),
            ("lines", "Lines", 120),
            ("status", "Status", 82),
            ("body", "Comment", 300),
        ):
            table.heading(col, text=txt, anchor="w")
            table.column(col, width=ui.px(width), minwidth=75, stretch=col != "status")

        def selected():
            ids = table.selection()
            return next((n for n in self.notes if ids and str(n["id"]) == ids[0]), None)

        actions = ui.frame(self.body, ui.PAPER)
        actions.pack(side="bottom", fill="x")
        open_button = ui.Button(
            actions,
            "Open comment",
            lambda: self.compose(selected()) if selected() else None,
            symbol="comment",
            border=ui.LINE,
        )
        jump_button = ui.Button(
            actions,
            "Show in diff",
            lambda: self.jump(selected()) if selected() else None,
            symbol="arrow",
            border=ui.LINE,
        )

        def change_status(resolved):
            note = selected()
            if note:
                self.set_note_resolved(note, resolved)

        resolve_button = ui.Button(actions, "Resolve", lambda: change_status(True), border=ui.LINE)
        reopen_button = ui.Button(actions, "Reopen", lambda: change_status(False), border=ui.LINE)
        snapshot_hint = ui.label(actions, "Saved excerpt available in Open comment", 9, ui.MUTED)

        def update_actions(event=None):
            note = selected()
            if not note:
                open_button.pack_forget()
                jump_button.pack_forget()
                resolve_button.pack_forget()
                reopen_button.pack_forget()
                snapshot_hint.pack_forget()
                return
            open_button.pack(side="left", padx=10, pady=8)
            active, inactive = (
                (reopen_button, resolve_button) if note.get("resolved") else (resolve_button, reopen_button)
            )
            inactive.pack_forget()
            active.pack(side="right", padx=10)
            if self.can_jump(note):
                snapshot_hint.pack_forget()
                jump_button.pack(side="left")
            else:
                jump_button.pack_forget()
                snapshot_hint.pack(side="left", padx=6)

        table.bind("<<TreeviewSelect>>", update_actions)
        self.update_note_actions = update_actions
        area.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(area, command=table.yview)
        scroll.pack(side="right", fill="y")
        table.configure(yscrollcommand=scroll.set)
        table.pack(fill="both", expand=True)
        self.notes_table = table
        self.notes_hint = ui.label(
            area, "Select lines in a diff and press C to add the first comment.", 10, ui.MUTED
        )
        self.update_comments()

        def open_row(event):
            if table.identify_region(event.x, event.y) in ("cell", "tree"):
                row = table.identify_row(event.y)
                note = next((n for n in self.notes if str(n["id"]) == row), None)
                if note is not None:
                    self.compose(note)

        table.bind("<Double-Button-1>", open_row)
        table.bind("<Return>", lambda e: self.compose(selected()) if selected() else None)

    def update_comments(self):
        table = self.notes_table
        all_branches = self.comment_scope.get() == "Entire repository"
        scoped = self.notes if all_branches else self.active_notes()
        if self.tab == "Comments":
            self.nav["Comments"][1].configure(text=str(len(scoped)))
        resolved = sum(bool(n.get("resolved")) for n in scoped)
        self.comments_heading.configure(
            text=f"Comments  ·  {len(scoped) - resolved} open  ·  {resolved} resolved"
        )
        status = self.comment_status.get()
        notes = (
            scoped
            if status == "All"
            else [n for n in scoped if bool(n.get("resolved")) == (status == "Resolved")]
        )
        table.configure(
            displaycolumns=("path", "comparison", "lines", "status", "body")
            if all_branches
            else ("path", "lines", "status", "body")
        )
        selection = table.selection()
        previous_index = table.index(selection[0]) if selection else 0
        ids = {str(n["id"]) for n in notes}
        for row in table.get_children():
            if row not in ids:
                table.delete(row)
        for index, n in enumerate(notes):
            row = str(n["id"])
            dest = self.jump_location(n) if n["right"] == git.WORKTREE or n.get("applied_anchor") else None
            shown = dest or n
            source = shown.get("group") or (ref_name(shown["right"]) if dest else "")
            summary = " ".join(n["body"].splitlines())
            if "suggestion" in n:
                label = "Applied suggestion" if n.get("applied_location") else "Suggested change"
                summary = f"{label} · {summary}" if summary else label
            values = (
                show(shown["path"]),
                show(ref_name(shown["left"])) + " → " + show(ref_name(shown["right"])),
                (show(source) + " · " if source else "") + location(shown),
                "Resolved" if n.get("resolved") else "Open",
                summary,
            )
            if table.exists(row):
                table.item(row, values=values)
            else:
                table.insert("", index, iid=row, values=values)
        if notes:
            self.notes_hint.place_forget()
            if not table.selection():
                row = str(notes[min(previous_index, len(notes) - 1)]["id"])
                table.selection_set(row)
                table.focus(row)
                table.see(row)
        else:
            if scoped:
                hint = f"No {status.lower()} comments in this scope. Choose All to see every comment."
            elif self.notes:
                hint = f"{len(self.notes)} saved on other comparisons. Choose Entire repository and All to see them."
            else:
                hint = "Select lines in a diff and press C to add the first comment."
            self.notes_hint.configure(
                text=hint, wraplength=min(ui.px(480), max(200, self.main.winfo_width() - 80))
            )
            self.notes_hint.place(relx=0.5, rely=0.5, anchor="center")
        self.update_note_actions()

    def set_note_resolved(self, note, resolved):
        try:
            found = self.store.set_resolved(self.repo, note["id"], resolved)
        except sqlite3.Error as error:
            messagebox.showerror("Could not update comment", str(error), parent=self.root)
            return
        self.collapse_overrides.pop(note["id"], None)
        if found:
            self.notes = [dict(n, resolved=resolved) if n["id"] == note["id"] else n for n in self.notes]
            self.status.set("Comment resolved" if resolved else "Comment reopened")
        else:
            self.notes = [n for n in self.notes if n["id"] != note["id"]]
            self.status.set("This comment was deleted in another window.")
        self.update_note_views()

    def update_note_views(self):
        self.update_chrome()
        if "Comments" in self.pages:
            self.update_comments()
        if self.diff and self.diff.winfo_exists():
            self.diff.refresh_notes()

    def can_jump(self, n):
        if n["right"] == git.WORKTREE or n.get("applied_anchor"):
            if self.locations_for(n):
                return True
            if n["right"] == git.WORKTREE:
                return False
        return (
            (n["left"], n["right"]) in comparisons(self.stack)
            and self.repo.refs.get(n["right"]) == n["head"]
            and (self.repo.refs.get(n["left"]) == n["left_tip"] or bool(self.locations_for(n)))
        )

    def jump(self, n):
        if not self.can_jump(n):
            self.status.set("Showing the excerpt saved with the comment.")
            self.compose(n)
            return
        dest = self.jump_location(n) or n
        pair = dest["left"], dest["right"]
        self.set_note_collapsed(n, False)
        self.tab = "Changes"
        self.filter.set("")
        if self.comparison and self.pair == pair:
            self.render()
            for f in self.comparison.files:
                anchor = self.anchor_at(self.comparison, f, n, self.note_locations)
                if anchor is not None:
                    self.pending_jump = anchor
                    self.pick(f)
                    return
            self.compose(n)
        else:
            self.load(pair, dest["path"], n)

    def can_apply_suggestion(self, note):
        c, f = self.comparison, self.current
        if (
            not c
            or not f
            or "suggestion" not in note
            or note.get("resolved")
            or note.get("applied_location")
            or not note["new"]
        ):
            return False
        checkout = "HEAD" if self.repo.checkout.startswith("HEAD@") else self.repo.checkout
        return f.mode in ("100644", "100755") and (c.right == git.WORKTREE or c.right == checkout)

    def apply_suggestion(self, note):
        if self.lines is None or not self.can_apply_suggestion(note):
            return
        n = self.original_note(note)
        c, f = self.comparison, self.current
        anchor = self.anchor_at(c, f, n, self.note_locations)
        if anchor is None or not self.can_apply_suggestion(anchor):
            return
        first, last = anchor["new"]
        expected = suggestion_source(n)
        replacement = n["suggestion"]
        lines = (replacement or expected).split("\n")
        sign = "+" if replacement else "-"
        updated = None
        try:
            with self.store.applying(self.repo, n) as current:
                head = c.left_tip if c.right == git.WORKTREE else c.head
                expected_checkout = (self.repo.checkout, None if head == self.repo.refs[git.EMPTY] else head)
                if git.checkout_state(self.repo.root) != expected_checkout:
                    raise suggestions.SuggestionError(
                        "The checked-out revision changed. Refresh before applying."
                    )
                result_oid = suggestions.apply_suggestion(
                    self.repo,
                    f.path,
                    first,
                    last,
                    expected,
                    replacement,
                    snapshot_oid=n["file_version"][1] if n["right"] == git.WORKTREE else f.oid,
                    reviewed_first=n["new"][0],
                )
                current["applied_location"] = {
                    "path": f.path,
                    "new": [first, last],
                    "branch": self.repo.checkout,
                }
                current["applied_anchor"] = {
                    "left": self.repo.checkout,
                    "right": git.WORKTREE,
                    "left_tip": head,
                    "path": f.path,
                    "old_path": f.path,
                    "old": [] if replacement else [first, last],
                    "new": [first, first + len(lines) - 1] if replacement else [],
                    "group": "Untracked" if f.group == "Untracked" else "Unstaged",
                    "file_version": [f.oid, result_oid, f.mode, f.mode],
                    "excerpt": "\n".join(sign + line for line in lines),
                }
                updated = dict(current, id=n["id"], resolved=False)
        except ReviewConflict as error:
            messagebox.showerror("Suggestion changed", str(error), parent=self.root)
            return
        except (git.GitError, suggestions.SuggestionError, OSError) as error:
            messagebox.showerror("Could not apply suggestion", str(error), parent=self.root)
            return
        except sqlite3.Error as error:
            if updated is None:
                messagebox.showerror("Could not apply suggestion", str(error), parent=self.root)
                return
            self.unsaved_receipts[(self.repo.root, n["id"])] = updated
            self.notes = [updated if item["id"] == n["id"] else item for item in self.notes]
            self.diff.refresh_notes()
            messagebox.showerror(
                "File updated · review could not be saved",
                f"The replacement was written to {show(f.path)}. Export this review before closing so you keep the application record.\n\n{error}",
                parent=self.root,
            )
            return
        self.reload_notes()
        self.refresh()

    def dialog(self, title, width, height):
        top = tk.Toplevel(self.root)
        top.title(title)
        top.configure(bg=ui.PAPER)
        top.transient(self.root)
        screen_w, screen_h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        width = min(ui.px(width), screen_w - 40)
        height = min(ui.px(height), screen_h - 80)
        x = self.root.winfo_rootx() + (self.root.winfo_width() - width) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - height) // 2
        top.geometry(
            f"{width}x{height}+{max(0, min(x, screen_w - width))}+{max(0, min(y, screen_h - height - 40))}"
        )
        top.minsize(min(width, 460), min(height, 360))
        top.grab_set()
        top.bind("<Escape>", lambda e: top.destroy())
        return top

    def compose(self, n):
        editing = "id" in n
        if self.root.grab_current() is not None:
            return
        if editing:
            n = self.original_note(n)
        suggestion = "suggestion" in n
        previous_focus = self.root.focus_get()
        host = self.main
        top = ui.frame(host, ui.WHITE, highlightthickness=2, highlightbackground=ui.GREEN)

        def position(event=None):
            top.place(
                relx=1,
                rely=1,
                x=-18,
                y=-40,
                anchor="se",
                width=min(ui.px(530), max(1, host.winfo_width() - 32)),
                height=min(max(ui.px(320), top.winfo_reqheight()), max(1, host.winfo_height() - 58)),
            )

        position()
        resize = host.bind("<Configure>", position, add="+")

        def dismiss(event=None):
            top.destroy()
            if previous_focus and previous_focus.winfo_exists():
                previous_focus.focus_set()
            return "break"

        wrap = ui.frame(top, ui.WHITE)
        wrap.pack(fill="both", expand=True, padx=16, pady=12)
        buttons = ui.frame(wrap)
        buttons.pack(side="bottom", fill="x", pady=(10, 0))
        title = (
            ("Edit suggestion" if editing else "Suggest change")
            if suggestion
            else ("Review comment" if editing else "Add comment")
        )
        ui.label(wrap, title, 19, ui.INK, True).pack(anchor="w")
        ui.label(wrap, show(n["path"]), 10, ui.SUB, True, mono=True, anchor="w").pack(fill="x", pady=(10, 3))
        revision = (
            n["group"] + " · " + show(ref_name(n["left"]))
            if n.get("group")
            else n["base"][:8] + " → " + n["head"][:8]
        )
        ui.label(wrap, location(n) + "   ·   " + revision, 9, ui.MUTED, anchor="w").pack(fill="x")
        if n["excerpt"]:
            excerpt_area = ui.frame(wrap)
            excerpt_area.pack(fill="x", pady=(10, 0))
            excerpt = tk.Text(
                excerpt_area,
                height=2,
                wrap="char",
                bg="#e9eee7",
                fg=ui.SUB,
                bd=0,
                padx=8,
                pady=5,
                font=(ui.MONO, 9),
                highlightthickness=0,
            )
            excerpt.insert("1.0", n["excerpt"])
            excerpt.configure(state="disabled")
            scroll = ttk.Scrollbar(excerpt_area, command=excerpt.yview)
            scroll.pack(side="right", fill="y")
            excerpt.configure(yscrollcommand=scroll.set)
            excerpt.pack(fill="x", expand=True)
        if suggestion:
            original_text = suggestion_source(n)
            applied = bool(n.get("applied_location"))
            caption = (
                "Replacement applied to working file"
                if applied
                else "Replacement · clear to delete selected lines"
            )
            replacement_caption = ui.label(wrap, caption, 10, ui.INK, True)
            replacement_caption.pack(anchor="w", pady=(10, 4))
            replacement_area = ui.frame(wrap)
            replacement_area.pack(fill="both", expand=True)
            replacement = tk.Text(
                replacement_area,
                name="replacement",
                wrap="char",
                undo=True,
                font=(ui.MONO, 10),
                bg=ui.WHITE,
                fg=ui.INK,
                height=4,
                width=1,
                padx=8,
                pady=5,
                bd=0,
                highlightthickness=1,
                highlightbackground=ui.LINE,
                highlightcolor=ui.GREEN,
            )
            scroll = ttk.Scrollbar(replacement_area, command=replacement.yview)
            scroll.pack(side="right", fill="y")
            replacement.configure(yscrollcommand=scroll.set)
            replacement.pack(expand=True, fill="both")
            replacement.insert("1.0", n["suggestion"])
            replacement.edit_reset()
            if applied:
                replacement.configure(state="disabled")
        ui.label(wrap, "Comment (optional)" if suggestion else "Comment", 10, ui.INK, True).pack(
            anchor="w", pady=(12, 5)
        )
        body = tk.Text(
            wrap,
            wrap="word",
            undo=True,
            bg=ui.WHITE,
            fg=ui.INK,
            font=(ui.UI, 11),
            padx=9,
            pady=8,
            insertbackground=ui.INK,
            height=2 if suggestion else 3,
            bd=0,
            highlightthickness=1,
            highlightbackground=ui.LINE,
            highlightcolor=ui.GREEN,
        )
        body.pack(fill="both", expand=True)
        body.insert("1.0", n["body"])
        repo = self.repo

        def finish():
            dismiss()
            self.reload_notes()
            self.update_note_views()

        def save(event=None):
            value = body.get("1.0", "end-1c").strip()
            note = dict(n, body=value)
            if suggestion:
                code = replacement.get("1.0", "end-1c")
                if code and code == original_text and not applied:
                    replacement_caption.configure(
                        text="Edit the replacement or clear it to delete these lines."
                    )
                    replacement.focus_set()
                    return "break"
                note["suggestion"] = code
            elif not value:
                body.focus_set()
                body.bell()
                return "break"
            try:
                self.store.save(repo, note, original=n if editing else None)
            except (ReviewConflict, sqlite3.Error) as error:
                messagebox.showerror(
                    "Could not save review", f"{error}\n\nYour draft is still open.", parent=top
                )
                return "break"
            self.status.set("Suggestion saved" if suggestion else "Comment saved")
            finish()
            return "break"

        def remove():
            if messagebox.askyesno("Delete comment", "Delete this review comment?", parent=top):
                self.store.delete(repo, n["id"])
                self.status.set("Comment deleted")
                finish()

        if editing:
            ui.Button(buttons, "Delete", remove, color=ui.RED, fill=ui.PAPER, hover=ui.DELETE).pack(side="left")
        ui.Button(
            buttons,
            "Save suggestion" if suggestion else "Save comment",
            save,
            fill=ui.MINT,
            hover="#a4e584",
            bold=True,
        ).pack(side="right")
        ui.Button(buttons, "Cancel", dismiss, fill=ui.PAPER).pack(side="right", padx=5)
        editors = [body]
        if n["excerpt"]:
            editors.append(excerpt)
        if suggestion:
            editors.append(replacement)
        for widget in (top, *editors, *buttons.winfo_children()):
            widget.bind("<Escape>", dismiss)
            widget.bind("<Control-Return>", save)
        layout = top.after_idle(position)

        def cleanup(event):
            if event.widget is top:
                top.after_cancel(layout)
                host.unbind("<Configure>", resize)

        top.bind("<Destroy>", cleanup)
        top.bind(
            "<Button-1>",
            lambda e: (
                dismiss()
                if not (0 <= e.x < top.winfo_width() and 0 <= e.y < top.winfo_height())
                and body.get("1.0", "end-1c") == n["body"]
                and (not suggestion or replacement.get("1.0", "end-1c") == n["suggestion"])
                else None
            ),
        )
        top.lift()
        # A double-click can arrive with the mouse button down. Tk needs a mapped frame to grab it.
        top.update_idletasks()
        top.grab_set()
        if suggestion and not applied:
            replacement.focus_set()
            if not editing:
                replacement.tag_add("sel", "1.0", "end-1c")
        else:
            body.focus_set()

    def stack_dialog(self):
        if not self.stack:
            return
        top = self.dialog("Edit branch stack", 740, 510)
        wrap = ui.frame(top)
        wrap.pack(fill="both", expand=True, padx=20, pady=18)
        ui.label(wrap, "Edit branch stack", 19, ui.INK, True).pack(anchor="w")
        ui.label(wrap, "Put the base first, then add branches in review order.", 10, ui.SUB).pack(
            anchor="w", pady=(5, 16)
        )
        bottom = ui.frame(wrap)
        bottom.pack(side="bottom", fill="x", pady=(12, 0))
        left = ui.frame(wrap)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        right = ui.frame(wrap)
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))
        refs = list(self.stack)
        available = []
        query = tk.StringVar()

        def box(parent):
            holder = ui.frame(parent, ui.WHITE, highlightthickness=1, highlightbackground=ui.LINE)
            holder.pack(fill="both", expand=True, pady=6)
            lst = tk.Listbox(
                holder,
                exportselection=False,
                selectmode="browse",
                activestyle="none",
                bd=0,
                bg=ui.WHITE,
                fg=ui.INK,
                selectbackground=ui.PALE,
                selectforeground=ui.GREEN,
                highlightthickness=0,
                font=(ui.MONO, 10),
                width=16,
                height=3,
            )
            across = ttk.Scrollbar(holder, orient="horizontal", command=lst.xview)
            across.pack(side="bottom", fill="x")
            sb = ttk.Scrollbar(holder, command=lst.yview)
            sb.pack(side="right", fill="y")
            lst.configure(yscrollcommand=sb.set, xscrollcommand=across.set)
            lst.pack(fill="both", expand=True)
            return lst

        caption(left, "AVAILABLE REFS").pack(anchor="w")
        entry = tk.Entry(
            left, textvariable=query, font=(ui.UI, 10), bg=ui.WHITE, fg=ui.INK, bd=1, relief="solid"
        )
        entry.pack(fill="x", pady=(6, 0), ipady=3)
        entry.focus_set()
        source = box(left)
        caption(right, "REVIEW ORDER").pack(anchor="w")
        order = box(right)

        def populate(*_):
            available[:] = [r for r in self.repo.refs if query.get().casefold() in ref_name(r).casefold()]
            source.delete(0, "end")
            for r in available:
                source.insert("end", "  " + show(ref_name(r)))
            if available:
                source.selection_set(0)

        query.trace_add("write", populate)
        populate()

        def redraw(index=0):
            order.delete(0, "end")
            for i, r in enumerate(refs):
                order.insert("end", ("  Base   " if i == 0 else f"  {i:>4}   ") + show(ref_name(r)))
            if refs:
                i = min(max(0, index), len(refs) - 1)
                order.selection_set(i)
                order.see(i)

        redraw()
        hint = tk.StringVar()

        def change(action):
            selected = order.curselection()
            i = selected[0] if selected else len(refs)
            if action in ("add", "replace"):
                if not source.curselection():
                    return
                r = available[source.curselection()[0]]
                if r in refs and (action != "replace" or not selected or refs[i] != r):
                    hint.set("That ref is already in the stack.")
                    return
                if action == "add" or not selected:
                    refs.append(r)
                    i = len(refs) - 1
                else:
                    refs[i] = r
            elif selected:
                if action == "remove":
                    refs.pop(i)
                else:
                    j = i + (-1 if action == "up" else 1)
                    if 0 <= j < len(refs):
                        refs[i], refs[j] = refs[j], refs[i]
                        i = j
            hint.set("")
            redraw(i)

        def discover():
            if not source.curselection():
                return
            branch = available[source.curselection()[0]]
            if branch == git.EMPTY:
                hint.set("Select a branch to find its stack.")
                return
            base = refs[0] if refs else self.repo.initial[0]
            repo = self.repo

            def found(result):
                if not top.winfo_exists():
                    return
                stack, forks = result
                refs[:] = stack
                redraw(stack.index(branch))
                if forks:
                    available[:] = forks
                    source.delete(0, "end")
                    for ref in forks:
                        source.insert("end", "  " + show(ref_name(ref)))
                    source.selection_set(0)
                hint.set(
                    "Multiple paths. Choose a branch on the left and find its stack."
                    if forks
                    else "Found the branch order from Git history."
                )

            hint.set("Finding parents and descendants…")
            self.run(
                "discovery",
                lambda: git.discover_stack(repo, base, branch),
                found,
                lambda msg: hint.set(msg) if top.winfo_exists() else None,
            )

        for parent, items in (
            (left, (("Add", "add"), ("Replace", "replace"))),
            (right, (("↑", "up"), ("↓", "down"), ("Remove", "remove"))),
        ):
            actions = ui.frame(parent)
            actions.pack(side="bottom", fill="x", before=(source if parent is left else order).master)
            if parent == left:
                ui.Button(actions, "Find stack", discover, height=29, border=ui.LINE).pack(
                    side="left", padx=(0, 4)
                )
            for title, cmd in items:
                ui.Button(actions, title, lambda a=cmd: change(a), height=29, border=ui.LINE).pack(
                    side="left", padx=(0, 4)
                )
        source.bind("<Double-Button-1>", lambda e: discover())

        def apply():
            if len(refs) < 2 or git.EMPTY in refs[1:]:
                hint.set("Choose a base and at least one branch. Empty tree can only be the base.")
                return
            self.store.set_stack(self.repo, refs)
            self.stack = refs
            top.destroy()
            self.filter.set("")
            self.load(comparisons(refs)[0])

        tk.Label(bottom, textvariable=hint, bg=ui.PAPER, fg=ui.RED, font=(ui.UI, 9), wraplength=350).pack(
            side="left"
        )
        ui.Button(
            bottom, "Review stack", apply, symbol="branch", fill=ui.MINT, hover="#a4e584", bold=True
        ).pack(side="right")
        ui.Button(bottom, "Cancel", top.destroy, fill=ui.PAPER).pack(side="right", padx=5)

    def export(self):
        if not self.repo:
            return
        top = self.dialog("Markdown preview", 820, 640)
        heading = ui.frame(top)
        heading.pack(fill="x", padx=16, pady=12)
        heading.columnconfigure(0, weight=1)
        ui.label(heading, "Markdown preview", 18, ui.INK, True).grid(row=0, column=0, columnspan=2, sticky="w")
        open_only = tk.BooleanVar(top, value=False)
        filter_button = tk.Checkbutton(
            heading,
            text="Open comments only",
            variable=open_only,
            font=(ui.UI, 10),
            bg=ui.PAPER,
            activebackground=ui.PAPER,
            fg=ui.INK,
            selectcolor=ui.WHITE,
            highlightcolor=ui.GREEN,
            highlightbackground=ui.PAPER,
            takefocus=True,
        )
        filter_button.grid(row=1, column=0, sticky="w", pady=(4, 0))
        actions = ui.frame(top)
        actions.pack(side="bottom", fill="x", padx=14, pady=10)
        text = tk.Text(
            top, wrap="word", undo=True, font=(ui.MONO, 10), bg=ui.WHITE, fg=ui.INK, padx=12, pady=10, bd=0
        )
        scroll = ttk.Scrollbar(top, command=text.yview)
        scroll.pack(side="right", fill="y")
        text.configure(yscrollcommand=scroll.set)
        text.pack(fill="both", expand=True, padx=(14, 0))
        repository_scope = self.showing_repository_notes()
        try:
            notes = self.read_notes()
        except sqlite3.Error:
            notes = self.notes
            self.status.set("Review database unavailable. Exporting the comments shown in this window.")
        if not repository_scope:
            notes = self.active_notes(notes)
        scope = "Entire repository" if repository_scope else self.review_scope()
        details = ui.label(heading, scope, 9, ui.MUTED)
        details.grid(row=1, column=1, sticky="e", pady=(4, 0))
        stack = None if repository_scope else [] if scope == "Working tree" else self.stack
        repo = self.repo

        def save(event=None):
            self.save_markdown(top, text.get("1.0", "end-1c"))
            return "break"

        ui.Button(actions, "Close", top.destroy).pack(side="left")

        def show_preview(locations=None):
            if not top.winfo_exists():
                return
            drafts = {}
            open_count = sum(not n.get("resolved") for n in notes)

            def display_draft():
                filtered = open_only.get()
                if drafts:
                    drafts[not filtered] = text.get("1.0", "end-1c")
                if filtered not in drafts:
                    drafts[filtered] = markdown(repo, stack, notes, locations=locations, open_only=filtered)
                text.replace("1.0", "end", drafts[filtered])
                text.edit_reset()
                text.mark_set("insert", "1.0")
                text.yview_moveto(0)
                count = open_count if filtered else len(notes)
                details.configure(text=f"{scope}  ·  {count} comment{'s' if count != 1 else ''}")

            text.configure(state="normal")
            display_draft()
            filter_button.configure(command=display_draft)
            text.focus_set()
            ui.Button(actions, "Save as…", save, fill=ui.MINT, bold=True).pack(side="right")
            ui.Button(
                actions, "Copy Markdown", lambda: self.copy_text(text.get("1.0", "end-1c")), border=ui.LINE
            ).pack(side="right", padx=6)
            top.bind("<Control-s>", save)

        if not any(n["right"] == git.WORKTREE or n.get("applied_anchor") for n in notes):
            show_preview()
            return
        text.insert("1.0", "Checking the working tree and stack for the reviewed lines…")
        text.configure(state="disabled")
        selected_stack = self.stack.copy()

        def find_locations():
            fresh = git.open_repo(repo.root)
            refs = selected_stack or fresh.initial
            if not all(ref in fresh.refs for ref in refs):
                refs = []
            return tracking.locate_notes(fresh, refs, None, notes)

        # A refresh in the main window can finish while this snapshot is read.
        # The preview belongs to its own dialog and retains its captured scope.
        self.run(None, find_locations, show_preview, lambda error: show_preview({}))

    def save_markdown(self, parent, content):
        target = filedialog.asksaveasfilename(
            title="Export review as Markdown",
            parent=parent,
            defaultextension=".md",
            initialfile=self.repo.root.name + "-review.md",
            filetypes=[("Markdown", "*.md"), ("All files", "*.*")],
        )
        if not target:
            return
        temp = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n", delete=False, dir=Path(target).parent
            ) as output:
                temp = output.name
                output.write(content)
            os.replace(temp, target)
            self.status.set(f"Exported review to {target}")
        except OSError as error:
            messagebox.showerror("Export failed", str(error), parent=parent)
        finally:
            if temp and os.path.exists(temp):
                os.unlink(temp)
