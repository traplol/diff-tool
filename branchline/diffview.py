"""Selectable, paged unified and synchronized side-by-side diff views."""

import re
import tkinter as tk
from bisect import bisect_left, bisect_right
from collections import defaultdict
from pathlib import PurePosixPath
from tkinter import ttk

from . import ui
from .git import EMPTY, show, split_rows
from .review import file_key, line_ranges, location, make_note, suggestion_source

PAGE = 600
TOKEN = re.compile(
    r"""(?P<string>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|(?P<comment>\#.*|//.*)|(?P<keyword>\b(?:async|await|break|case|class|const|continue|def|else|elif|export|false|for|from|func|function|if|import|in|interface|let|new|None|null|private|public|raise|return|struct|throw|true|try|type|var|while|with|yield)\b)"""
)
CODE = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".go",
    ".h",
    ".hpp",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".swift",
    ".ts",
    ".tsx",
    ".json",
    ".toml",
}


class DiffView(tk.Frame):
    def __init__(self, parent, app, change, lines, jump=None, position=None):
        super().__init__(parent, bg=ui.WHITE)
        self.app, self.file = app, change
        self.lines = lines
        self.dual = bool(lines) and app.mode == "Split"
        self.rows = split_rows(lines) if self.dual else [(line,) for line in lines]
        self.notes = self.file_notes()
        self.note_rows = self.card_positions()
        self.page = 0
        self.selection = None
        self.editors = []
        self.syntax = PurePosixPath(change.path).suffix.lower() in CODE
        self.restore_position(position, jump)

    def restore_position(self, position, jump=None):
        token = self.restore_token = object()
        self.pending_position = position
        first, anchor = position or (None, None)
        if jump:
            first, anchor = None, jump
        col = int(bool(self.dual and anchor and anchor["new"]))
        start = (
            next((i for i, row in enumerate(self.rows) if first in row), None) if first is not None else None
        )
        card_row = self.note_rows.get(jump["id"]) if jump else None
        target = None
        if card_row is not None:
            target = max(card_row, 0)
        elif anchor:
            target = next((i for i, row in enumerate(self.rows) if self.matches(row[col], anchor, col)), None)
        page = (target if target is not None else start or 0) // PAGE
        if page != self.page or not self.editors:
            self.page, self.selection = page, None
            self.draw()
        else:
            self.clear_selection()
            self.anchor_label.configure(text="Select lines to comment")
            for pane in self.editors:
                pane.xview_moveto(0)
        if target is not None:
            hits = [i for i, row in enumerate(self.visible) if self.matches(row[col], anchor, col)]
            if hits:
                self.select(col, hits[0], hits[-1])
        if self.editors and (target is not None or start is not None):
            editor = self.editors[col]

            def restore():
                if token is not self.restore_token or not editor.winfo_exists() or not editor.winfo_viewable():
                    return
                self.pending_position = None
                # Tk estimates offscreen row heights until it has measured both panes.
                for pane in self.editors:
                    pane.count("1.0", "end", "update", "ypixels")
                if card_row is not None:
                    row = card_row % PAGE if card_row >= 0 else -1
                    editor.see(self.code_index(row + 1) + " -1 lines")
                elif start is not None and start // PAGE == self.page:
                    self.scroll(self.code_index(start % PAGE))
                elif target is not None:
                    editor.see(self.code_index(target % PAGE))

            def mapped(event):
                editor.unbind("<Map>", binding)
                self.app.root.after_idle(restore)

            if editor.winfo_viewable():
                self.app.root.after_idle(restore)
            else:
                binding = editor.bind("<Map>", mapped, add="+")
        else:
            self.pending_position = None

    def position(self):
        if self.pending_position is not None:
            return self.pending_position
        if not self.visible:
            return None
        index = min(len(self.visible) - 1, max(0, self.row_at(self.editors[0], 0, 0)))
        first = next(line for line in self.visible[index] if line is not None)
        lines, side = self.selected()
        return first, line_ranges(lines, side) if lines else None

    def destroy(self):
        super().destroy()
        # Release the Tcl variable on the UI thread when its checkbutton closes.
        self.viewed = None

    def file_notes(self):
        return [
            anchor
            for n in self.app.active_notes()
            if (anchor := self.app.anchor_at(self.app.comparison, self.file, n, self.app.note_locations))
            is not None
        ]

    def code_index(self, row):
        return f"{row + 1 + bisect_left(self.card_rows, row)}.0"

    def row_at(self, editor, x, y):
        display_row = int(editor.index(f"@{x},{y}").split(".")[0]) - 1
        return display_row - bisect_right(self.card_display_rows, display_row)

    def refresh_notes(self):
        notes = self.file_notes()
        if self.notes == notes:
            return
        self.notes = notes
        self.note_rows = self.card_positions()
        self.update_cards()
        for col, editor in enumerate(self.editors):
            pinned = self.pinned_rows(col)
            editor.configure(state="normal")
            for i, row in enumerate(self.visible):
                line = row[col]
                if line is None or line.kind not in " +-":
                    continue
                marker = "●" if i in pinned else " "
                index = self.code_index(i) + " + 1c"
                if editor.get(index) != marker:
                    tags = editor.tag_names(index)
                    editor.replace(index, index + " + 1c", marker, tags)
            editor.configure(state="disabled")
        if self.selection:
            self.select(*self.selection)

    def pinned_rows(self, col):
        """Visible row indices covered by at least one comment on this pane."""
        pinned = set()
        sides = ("old", "new")
        if self.dual:
            sides = (sides[col],)
        for side in sides:
            spans = [note[side] for note in self.notes if note[side]]
            if not spans:
                continue
            starts = sorted(first for first, _ in spans)
            ends = sorted(last for _, last in spans)
            for i, row in enumerate(self.visible):
                line = row[col]
                if line is None or (number := getattr(line, side)) is None:
                    continue
                # Inclusive ranges overlap here while more have started than ended.
                if bisect_right(starts, number) > bisect_left(ends, number):
                    pinned.add(i)
        return pinned

    def matches(self, line, note, col):
        if line is None or line.kind not in " +-":
            return False
        for side in ("old", "new"):
            if self.dual and side != ("old" if col == 0 else "new"):
                continue
            r, n = note[side], getattr(line, side)
            if r and n is not None and r[0] <= n <= r[1]:
                return True
        return False

    def draw(self):
        for child in self.winfo_children():
            child.destroy()
        self.editors.clear()
        self.cards = {}
        self.card_rows = []
        self.card_display_rows = []
        self.visible = self.rows[self.page * PAGE : (self.page + 1) * PAGE]
        bar = ui.frame(self)
        bar.pack(fill="x", padx=12, pady=7)
        self.viewed = tk.BooleanVar(value=file_key(self.file) in self.app.viewed)
        tk.Checkbutton(
            bar,
            text="Viewed",
            variable=self.viewed,
            command=self.toggle_viewed,
            bg=ui.WHITE,
            activebackground=ui.WHITE,
            fg=ui.SUB,
            selectcolor=ui.WHITE,
            font=(ui.UI, 9),
            highlightthickness=0,
            bd=0,
        ).pack(side="right", padx=(6, 0))
        for mode, symbol in (("Unified", "unified"), ("Split", "split")):
            active = mode == self.app.mode
            ui.Button(
                bar,
                mode,
                lambda m=mode: self.app.set_mode(m),
                symbol=symbol,
                fill=ui.PALE if active else ui.WHITE,
                color=ui.GREEN if active else ui.SUB,
                height=27,
                pad=7,
            ).pack(side="left", padx=(0, 3))
        if len(self.rows) > PAGE:
            for title, delta in (("‹", -1), ("›", 1)):
                if 0 <= self.page + delta <= (len(self.rows) - 1) // PAGE:
                    ui.Button(bar, title, lambda d=delta: self.turn(d), height=26, pad=6).pack(side="left")
            ui.label(bar, f"{self.page + 1}/{(len(self.rows) - 1) // PAGE + 1}", 8, ui.MUTED).pack(side="left")
        ui.rule(self)
        bottom = ui.frame(self, ui.PAPER)
        bottom.pack(side="bottom", fill="x")
        ui.rule(bottom)
        actions = ui.frame(bottom)
        actions.pack(side="bottom", fill="x", padx=12, pady=8)
        ui.Button(
            actions,
            "Comment",
            self.comment,
            symbol="comment",
            height=29,
            fill=ui.WHITE,
            border=ui.LINE,
            color=ui.GREEN,
            bold=True,
        ).pack(side="right")
        self.suggest_button = ui.Button(actions, "Suggest change", self.suggest, height=29, border=ui.LINE)
        self.anchor_label = ui.label(
            actions, "Select lines to comment" if self.rows else "Whole file", 9, ui.MUTED, anchor="w"
        )
        self.anchor_label.pack(side="left", fill="x", expand=True)
        area = ui.frame(self)
        area.pack(fill="both", expand=True)
        area.rowconfigure(1, weight=1)
        scroll = ttk.Scrollbar(area, orient="vertical", command=self.scroll)
        scroll.grid(row=1, column=2 if self.dual else 1, sticky="ns")
        sides = ("Base", "Head")
        if self.file.group == "Staged":
            base = "Empty" if self.app.comparison.base == self.app.repo.refs.get(EMPTY) else "HEAD"
            sides = (base, "Index")
        elif self.file.group == "Unstaged":
            sides = ("Ours" if self.file.status == "U" else "Index", "Working tree")
        elif self.file.group == "Untracked":
            sides = ("Empty", "Working tree")
        for col in range(2 if self.dual else 1):
            area.columnconfigure(col, weight=1, uniform="pane")
            if self.dual:
                head = ui.frame(area, ui.PAPER)
                head.grid(row=0, column=col, sticky="ew")
                ui.label(head, sides[col].upper(), 8, ui.SUB, True, True).pack(anchor="w", padx=12, pady=4)
            editor = tk.Text(
                area,
                wrap="none",
                bg=ui.WHITE,
                fg=ui.INK,
                font=(ui.MONO, 10),
                spacing1=3,
                spacing3=3,
                highlightthickness=0,
                bd=0,
                padx=0,
                width=1,
                height=1,
                cursor="xterm",
                takefocus=True,
                exportselection=False,
            )
            editor.configure(tabs=(tkfont_width(editor) * 4,))
            editor.grid(row=1, column=col, sticky="nsew", padx=(1 if col else 0, 0))
            xscroll = ttk.Scrollbar(area, orient="horizontal", command=editor.xview)
            xscroll.grid(row=2, column=col, sticky="ew")
            editor.configure(
                xscrollcommand=xscroll.set, yscrollcommand=lambda a, b, e=editor: self.sync(e, scroll, a, b)
            )
            self.editors.append(editor)
            if self.rows:
                self.fill(editor, col)
            else:
                self.empty_file(editor)
            editor.configure(state="disabled")
            editor.bind("<Button-1>", lambda e, k=col: self.mouse(e, k))
            editor.bind("<Shift-Button-1>", lambda e, k=col: self.mouse(e, k, True))
            editor.bind("<B1-Motion>", lambda e, k=col: self.mouse(e, k, True, True))
            for key, amount in (("Up", -1), ("Down", 1)):
                editor.bind(f"<{key}>", lambda e, k=col, a=amount: self.move(k, a, False))
                editor.bind(f"<Shift-{key}>", lambda e, k=col, a=amount: self.move(k, a, True))
            editor.bind("<Control-c>", self.copy)
            editor.bind("<Escape>", self.clear_selection)
            editor.bind("<Key-c>", lambda e: self.comment())
            editor.bind("<Key-s>", lambda e: self.suggest())
            editor.bind("<Return>", lambda e: self.comment())
            editor.bind("<Button-3>", lambda e, k=col: self.menu(e, k))
            self.app.shortcuts(editor)
            editor.bind("<Configure>", self.resize_cards)
        self.update_cards()

    def empty_file(self, editor):
        if self.file.binary:
            title, detail = "Binary file", "Git identified this file as binary."
        elif self.file.group == "Untracked" and self.file.mode == "160000":
            title = "Nested Git repository"
            detail = (
                f"Checked-out commit {self.file.oid[:12]}"
                if self.file.oid.strip("0")
                else "No readable HEAD commit."
            )
        elif self.file.status == "U":
            title, detail = "Unresolved conflict", "The working copy has no text changes against our side."
        elif self.file.status == "R":
            title, detail = "Renamed file", show(self.file.old) + " → " + show(self.file.path)
        elif self.file.old_mode != self.file.mode:
            title, detail = "No text changes", f"File mode  {self.file.old_mode} → {self.file.mode}"
        else:
            title, detail = "No text changes", "The file contents are identical."
        holder = ui.frame(editor)
        ui.label(holder, title, 14, bold=True).pack(anchor="w")
        ui.label(holder, detail, 9, ui.MUTED, wraplength=400).pack(anchor="w", pady=5)
        editor.window_create("1.0", window=holder, padx=12, pady=12)

    def fill(self, editor, col):
        for tag, bg in (
            ("+", ui.ADD),
            ("-", ui.DELETE),
            ("@", "#edf0ef"),
            ("\\", ui.PAPER),
            ("gap", "#f4f5f2"),
        ):
            editor.tag_configure(tag, background=bg)
        editor.tag_configure("@", foreground="#61736a")
        for tag, color in (
            ("gut", "#849388"),
            ("plus", ui.GREEN),
            ("minus", ui.RED),
            ("keyword", "#75508c"),
            ("string", "#386d56"),
            ("comment", "#718477"),
            ("pin", ui.GREEN),
        ):
            editor.tag_configure(tag, foreground=color)
        editor.tag_configure("picked", background="#d0e6f4")
        gutter = max(
            3,
            max(
                (
                    len(str(v))
                    for row in self.visible
                    for line in row
                    if line
                    for v in (line.old, line.new)
                    if v is not None
                ),
                default=1,
            ),
        )
        fragments = []
        ranges = defaultdict(list)
        pinned = self.pinned_rows(col)
        for i, row in enumerate(self.visible):
            line = row[col]
            start = f"{i + 1}.0"
            if line is None:
                fragments.extend((" \n", ("gap",)))
                continue
            if line.kind in "@\\":
                fragments.extend(("   " + line.text + "\n", (line.kind,)))
            else:
                nums = [line.old, line.new] if not self.dual else [line.old if col == 0 else line.new]
                numbers = " ".join(str(n if n is not None else "").rjust(gutter) for n in nums) + "  "
                fragments.extend(
                    (
                        " ●" if i in pinned else "  ",
                        "pin",
                        numbers,
                        "gut",
                        line.kind + " ",
                        {"+": "plus", "-": "minus"}.get(line.kind, "gut"),
                        line.text + "\n",
                        (),
                    )
                )
                offset = 2 + len(numbers) + 2  # pin, line numbers, and +/- sign
                if self.syntax and len(line.text) < 3000:
                    for m in TOKEN.finditer(line.text):
                        ranges[m.lastgroup].extend(
                            (f"{i + 1}.{offset + m.start()}", f"{i + 1}.{offset + m.end()}")
                        )
                if line.kind != " ":
                    ranges[line.kind].extend((start, f"{i + 2}.0"))
        editor.insert("end", *fragments)
        for tag, indices in ranges.items():
            editor.tag_add(tag, *indices)
        editor.tag_raise("picked")

    def sync(self, editor, scrollbar, first, last):
        scrollbar.set(first, last)
        for other in self.editors:
            if other != editor and abs(other.yview()[0] - float(first)) > 0.0001:
                other.yview_moveto(first)

    def scroll(self, *args):
        for editor in self.editors:
            editor.yview(*args)

    def turn(self, delta):
        self.page += delta
        self.selection = None
        self.draw()

    def toggle_viewed(self):
        self.app.mark_viewed(self.file, self.viewed.get())

    def mouse(self, e, col, extend=False, drag=False):
        e.widget.focus_set()
        if drag and (e.y < 0 or e.y > e.widget.winfo_height()):
            self.scroll("scroll", -1 if e.y < 0 else 1, "units")
        row = self.row_at(e.widget, e.x, e.y)
        if not self.visible or row < 0:
            return self.clear_selection()
        if not extend and row >= len(self.visible):
            return self.clear_selection()
        end = min(len(self.visible) - 1, row)
        anchor = self.selection[1] if extend and self.selection and self.selection[0] == col else end
        self.select(col, anchor, end)
        return "break"

    def move(self, col, delta, extend):
        if not self.visible:
            return "break"
        end = min(len(self.visible) - 1, max(0, self.selection[2] + delta if self.selection else 0))
        anchor = self.selection[1] if extend and self.selection and self.selection[0] == col else end
        self.select(col, anchor, end)
        self.editors[col].see(self.code_index(end))
        return "break"

    def selected(self):
        if not self.selection:
            return [], "file"
        col, a, b = self.selection
        lines = [r[col] for r in self.visible[min(a, b) : max(a, b) + 1] if r[col] and r[col].kind in " +-"]
        return lines, ("old" if col == 0 else "new") if self.dual else "unified"

    def clear_selection(self, event=None):
        self.selection = None
        self.suggest_button.pack_forget()
        for editor in self.editors:
            editor.tag_remove("picked", "1.0", "end")
        self.anchor_label.configure(text="Whole file")
        return "break"

    def select(self, col, anchor, end):
        self.selection = col, anchor, end
        self.editors[col].mark_set("insert", self.code_index(end))
        for editor in self.editors:
            editor.tag_remove("picked", "1.0", "end")
        self.editors[col].tag_add(
            "picked", self.code_index(min(anchor, end)), self.code_index(max(anchor, end)) + " +1 lines"
        )
        lines, side = self.selected()
        self.anchor_label.configure(text=location(line_ranges(lines, side)) if lines else "Select a code line")
        if self.can_suggest(lines, side):
            self.suggest_button.pack(side="right", padx=(0, 5), before=self.anchor_label)
        else:
            self.suggest_button.pack_forget()

    def card_positions(self):
        positions = {}
        ends = {(side, n[side][-1]) for n in self.notes for side in ("old", "new") if n[side]}
        end_rows = {}
        if ends:
            for i, row in enumerate(self.rows):
                for side, line in (("old", row[0]), ("new", row[-1])):
                    if line and (key := (side, getattr(line, side))) in ends:
                        end_rows[key] = i
        for note in self.notes:
            anchors = [
                end_rows[side, note[side][-1]]
                for side in ("old", "new")
                if note[side] and (side, note[side][-1]) in end_rows
            ]
            if anchors:
                positions[note["id"]] = max(anchors)
            elif not note["old"] and not note["new"]:
                positions[note["id"]] = -1
        return positions

    def update_cards(self):
        groups = {}
        for note in self.notes:
            absolute = self.note_rows.get(note["id"])
            if absolute is None or (absolute >= 0 and absolute // PAGE != self.page):
                continue
            row = absolute % PAGE if absolute >= 0 else -1
            groups.setdefault(row, []).append(note)

        for editor in self.editors:
            editor.configure(state="normal")
        for row in sorted(self.cards, reverse=True):
            card = self.cards[row]
            if row in groups:
                notes = groups[row]
                col = int(self.dual and any(n["new"] for n in notes))
                if card.master is self.editors[col]:
                    if card.notes != notes:
                        card.notes = notes
                        card.paint()
                    continue
            start = self.code_index(row + 1) + " -1 lines"
            card.destroy()
            for editor in self.editors:
                editor.delete(start, start + " +1 lines")
            del self.cards[row]
            self.card_rows.remove(row)
        for row, notes in sorted(groups.items()):
            if row in self.cards:
                continue
            col = int(self.dual and any(n["new"] for n in notes))
            card = InlineComments(
                self.editors[col], self.app, notes, self.editors[1 - col] if self.dual else None
            )
            index = self.code_index(row + 1)
            for side, editor in enumerate(self.editors):
                editor.insert(index, "\n", ())
                editor.window_create(index, window=card if side == col else card.spacer, padx=ui.px(5), pady=2)
            self.cards[row] = card
            self.card_rows.insert(bisect_left(self.card_rows, row), row)
        self.card_display_rows = [row + i + 1 for i, row in enumerate(self.card_rows)]
        for editor in self.editors:
            editor.configure(state="disabled")

    def resize_cards(self, event):
        for card in self.cards.values():
            if card.master is event.widget:
                card.fit(event.width)

    def copy(self, event=None):
        lines, _ = self.selected()
        if lines:
            self.clipboard_clear()
            self.clipboard_append("\n".join(l.text for l in lines))
        return "break"

    def menu(self, e, col):
        row = min(len(self.visible) - 1, self.row_at(e.widget, e.x, e.y))
        if row < 0:
            self.clear_selection()
        elif (
            not self.selection
            or self.selection[0] != col
            or not min(self.selection[1:]) <= row <= max(self.selection[1:])
        ):
            self.select(col, row, row)
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Add comment", command=self.comment)
        menu.add_command(
            label="Suggest change",
            command=self.suggest,
            state="normal" if self.can_suggest(*self.selected()) else "disabled",
        )
        menu.add_command(label="Comment on file", command=self.file_comment)
        menu.add_command(label="Copy selected lines", command=self.copy)
        try:
            menu.tk_popup(e.x_root, e.y_root)
        finally:
            menu.grab_release()

    def file_comment(self):
        self.clear_selection()
        return self.comment()

    def can_suggest(self, lines, side):
        return bool(
            lines
            and side != "old"
            and self.file.mode in ("100644", "100755")
            and lines[0].new is not None
            and lines[0].hunk == lines[-1].hunk
            and all(line.new == lines[0].new + i for i, line in enumerate(lines))
        )

    def suggest(self):
        lines, side = self.selected()
        if self.can_suggest(lines, side):
            note = make_note(self.app.comparison, self.file, lines, "new", "", diff_lines=self.lines)
            note["suggestion"] = suggestion_source(note)
            self.app.compose(note)
        else:
            self.app.status.set("Select consecutive lines on the new side to suggest a change.")
        return "break"

    def comment(self):
        lines, side = self.selected()
        if self.selection and not lines:
            self.app.status.set("Select a code line to add a line comment.")
        elif lines and lines[0].hunk != lines[-1].hunk:
            self.app.status.set("Select lines within one hunk so the comment has a continuous range.")
        else:
            self.app.compose(make_note(self.app.comparison, self.file, lines, side, "", diff_lines=self.lines))
        return "break"


class InlineComments(tk.Frame):
    def __init__(self, editor, app, notes, other_editor):
        super().__init__(editor, bg=ui.PALE, padx=ui.px(8), pady=ui.px(4))
        self.app, self.notes = app, notes
        self.spacer = ui.frame(other_editor, ui.PAPER, width=1, height=1) if other_editor else None
        self.bodies = []
        self.paint()
        if self.spacer is not None:
            self.bind_wheel(self.spacer)

    def paint(self, focus_note=None):
        refocus = str(self.tk.call("focus", "-displayof", self)).startswith(f"{self}.")
        for child in self.winfo_children():
            child.destroy()
        self.bodies.clear()
        collapsed = all(self.app.is_note_collapsed(note) for note in self.notes)
        count = len(self.notes)
        noun = "suggestion" if all("suggestion" in n for n in self.notes) else "comment"
        title = ("▸" if collapsed else "▾") + f"  {count} {noun}{'s' if count > 1 else ''}"
        if collapsed:
            open_count = sum(not note.get("resolved", False) for note in self.notes)
            if open_count == count:
                title += " · Open"
            elif open_count:
                title += f" · {open_count} open"
            else:
                title += " · Resolved"
        toggle = ui.Button(self, title, self.toggle, height=23, pad=4, bold=True, fill=ui.PALE, color=ui.GREEN)
        toggle.pack(anchor="w")
        if refocus:
            toggle.focus_set()
        if not collapsed:
            mixed_ranges = len({location(note) for note in self.notes}) > 1
            for i, note in enumerate(self.notes):
                if i:
                    ui.rule(self, color=ui.LINE, pady=3)
                if mixed_ranges:
                    ui.label(self, location(note), 8, ui.SUB, mono=True).pack(anchor="w", pady=(4, 0))
                resolved = note.get("resolved", False)
                status = "Resolved" if resolved else "Open"
                row = ui.frame(self, ui.PALE)
                row.pack(fill="x", pady=2)
                if count > 1:
                    folded = self.app.is_note_collapsed(note)
                    kind = "suggestion" if "suggestion" in note else "comment"
                    title = f"{'▸' if folded else '▾'}  {status} {kind}"
                    disclosure = ui.Button(
                        row,
                        title,
                        lambda n=note: self.toggle(n),
                        height=22,
                        pad=4,
                        fill=ui.PALE,
                        color=ui.GREEN,
                    )
                    disclosure.pack(side="left")
                    if refocus and focus_note is note:
                        disclosure.focus_set()
                    if folded:
                        continue
                else:
                    ui.label(row, status, 8, ui.SUB, bold=True).pack(side="left")
                ui.Button(
                    row,
                    "Edit",
                    lambda n=note: self.app.compose(n),
                    height=22,
                    pad=5,
                    color=ui.GREEN,
                    fill=ui.PALE,
                ).pack(side="right")
                ui.Button(
                    row,
                    "Reopen" if resolved else "Resolve",
                    lambda n=note: self.app.set_note_resolved(n, not n.get("resolved", False)),
                    height=22,
                    pad=5,
                    color=ui.GREEN,
                    fill=ui.PALE,
                ).pack(side="right", padx=(6, 3))
                if note["body"]:
                    body = ui.label(self, note["body"], 10, ui.INK, anchor="w", justify="left")
                    body.pack(fill="x", pady=2)
                    self.bodies.append(body)
                if "suggestion" in note:
                    self.show_suggestion(note)
        self.fit(self.master.winfo_width())
        self.bind_wheel(self)

    def show_suggestion(self, note):
        if not note["body"]:
            ui.label(self, "Suggested change", 10, ui.INK, bold=True).pack(anchor="w")
        old = "\n".join("− " + line for line in suggestion_source(note).split("\n"))
        texts = [(old, ui.RED, ui.DELETE)]
        if note["suggestion"]:
            new = "\n".join("+ " + line for line in note["suggestion"].split("\n"))
            texts.append((new, ui.GREEN, ui.ADD))
        for text, color, bg in texts:
            code = ui.label(self, text, 9, color, mono=True, anchor="w", justify="left")
            code.configure(bg=bg, padx=5, pady=2)
            code.pack(fill="x")
            self.bodies.append(code)
        if not note["suggestion"]:
            ui.label(self, "Delete selected lines", 9, ui.RED).pack(anchor="w")
        if note.get("applied_location"):
            ui.label(self, "Applied to working file", 9, ui.GREEN, bold=True).pack(anchor="w", pady=(4, 0))
        elif self.app.can_apply_suggestion(note):
            ui.Button(
                self,
                "Apply to working file",
                lambda: self.app.apply_suggestion(note),
                height=25,
                pad=7,
                fill=ui.MINT,
                color=ui.INK,
            ).pack(anchor="w", pady=(4, 0))

    def fit(self, width):
        # Allow for the embedded window, frame, and code label padding.
        wrap = max(ui.px(50), width - ui.px(40))
        for body in self.bodies:
            if int(body.cget("wraplength")) != wrap:
                body.configure(wraplength=wrap)
        if self.spacer is not None:
            # Text scrolls each pane by a fraction of its measured pixel height.
            # Give both panes the same height before Tk services a scroll event.
            self.update_idletasks()
            self.spacer.configure(height=self.winfo_reqheight())

    def toggle(self, note=None):
        notes = self.notes if note is None else [note]
        collapse = not all(self.app.is_note_collapsed(n) for n in notes)
        for n in notes:
            self.app.set_note_collapsed(n, collapse)
        self.paint(focus_note=note)

    def bind_wheel(self, widget):
        for sequence in ("<Button-4>", "<Button-5>", "<MouseWheel>"):
            if widget.bind(sequence):
                continue

            def forward(event, seq=sequence):
                options = {"delta": event.delta} if seq == "<MouseWheel>" else {}
                self.master.event_generate(seq, **options)
                return "break"

            widget.bind(sequence, forward)
        for child in widget.winfo_children():
            self.bind_wheel(child)

    def destroy(self):
        if self.spacer is not None:
            self.spacer.destroy()
        super().destroy()


def tkfont_width(widget):
    from tkinter import font

    return font.Font(font=widget["font"]).measure("0")
