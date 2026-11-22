"""Shared desktop controls, colors and vector artwork."""

import tkinter as tk
from functools import lru_cache
from tkinter import font as tkfont
from tkinter import ttk

RAIL = "#192823"
RAIL_SOFT = "#23362e"
RAIL_LINE = "#34483e"
RAIL_MUTED = "#a5b6ab"
MINT = "#b6f397"
INK = "#202d27"
SUB = "#52665b"
MUTED = "#64766b"
PAPER = "#f5f6f1"
WHITE = "#ffffff"
LINE = "#dbe1d8"
GREEN = "#286340"
PALE = "#e5f2de"
RED = "#a04445"
ADD = "#e7f5e7"
DELETE = "#fbecea"
UI = "TkDefaultFont"
MONO = "TkFixedFont"
_scale = 1.0


def px(value):
    return round(value * _scale)


def has_focus(widget):
    # Native Tk dialogs may focus a Tcl widget that has no Python wrapper.
    return str(widget.tk.call("focus", "-displayof", widget)) == str(widget)


def configure(root):
    global UI, MONO, _scale
    families = set(tkfont.families(root))
    UI = next((f for f in ("Inter", "Segoe UI", "Helvetica", "DejaVu Sans") if f in families), "Arial")
    MONO = next(
        (f for f in ("Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Courier New") if f in families),
        "Courier",
    )
    # XWayland can report 96 DPI while the desktop doubles the rendered fonts.
    # Size controls against the type the user actually sees.
    _scale = max(1.0, tkfont.Font(root=root, family=UI, size=10).metrics("linespace") / 17)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(
        "Treeview",
        font=(UI, 10),
        rowheight=px(32),
        borderwidth=0,
        relief="flat",
        background=WHITE,
        fieldbackground=WHITE,
        foreground=INK,
    )
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    style.map("Treeview", background=[("selected", PALE)], foreground=[("selected", GREEN)])
    style.configure(
        "TScrollbar",
        arrowsize=px(11),
        width=px(11),
        background=LINE,
        bordercolor=PAPER,
        troughcolor=PAPER,
        lightcolor=LINE,
        darkcolor=LINE,
    )
    style.configure("TCombobox", padding=5, fieldbackground=WHITE, foreground=INK, arrowsize=12)
    style.map("TCombobox", fieldbackground=[("readonly", WHITE)], foreground=[("readonly", INK)])
    root.option_add("*TCombobox*Listbox.font", (UI, 10))
    root.option_add("*TCombobox*Listbox.background", WHITE)


def frame(parent, bg=None, **kw):
    return tk.Frame(parent, bg=bg or parent["bg"], **kw)


def label(parent, value, size=10, color=INK, bold=False, mono=False, **kw):
    return tk.Label(
        parent,
        text=value,
        bg=parent["bg"],
        fg=color,
        bd=0,
        padx=0,
        pady=0,
        font=(MONO if mono else UI, size, "bold" if bold else "normal"),
        **kw,
    )


def rule(parent, color=LINE, **pack):
    frame(parent, color, height=1).pack(fill="x", **pack)


def icon(c, name, x, y, size, color):
    scale = size / 24

    def points(coords):
        return [v * scale + (y if i % 2 else x) for i, v in enumerate(coords)]

    def line(*coords, width=1.65):
        c.create_line(*points(coords), fill=color, width=width * scale, capstyle="round", joinstyle="round")

    def circle(cx, cy, radius):
        c.create_oval(
            *points((cx - radius, cy - radius, cx + radius, cy + radius)), outline=color, width=1.55 * scale
        )

    if name == "brand":
        line(4, 18, 4, 10, 11, 4, 18, 4, width=3.4)
        line(10, 20, 10, 14, 17, 8, 22, 8, width=3.4)
        line(16, 20, 16, 17, 21, 13, width=3.4)
    elif name == "folder":
        line(3, 7, 3, 5, 9, 5, 11, 8, 21, 8, 21, 19, 3, 19, 3, 7)
    elif name == "branch":
        circle(7, 5, 2.4)
        circle(7, 19, 2.4)
        circle(18, 6, 2.4)
        line(7, 7.5, 7, 16.5)
        line(7, 15, 10, 12, 15, 12, 18, 9, 18, 8.5)
    elif name == "changes":
        line(7, 3, 16, 3, 20, 7, 20, 20, 7, 20, 7, 3)
        line(4, 7, 4, 22, 16, 22)
        line(10, 10, 16, 10)
        line(10, 14, 14, 14)
    elif name == "commit":
        line(2, 12, 7, 12)
        circle(12, 12, 4.4)
        line(17, 12, 22, 12)
    elif name == "comment":
        line(4, 4, 20, 4, 20, 16, 11, 16, 6, 20, 6, 16, 4, 16, 4, 4)
    elif name == "export":
        line(12, 15, 12, 3)
        line(7, 8, 12, 3, 17, 8)
        line(4, 14, 4, 20, 20, 20, 20, 14)
    elif name == "refresh":
        c.create_arc(
            *points((4, 4, 20, 20)), start=55, extent=290, style="arc", outline=color, width=1.7 * scale
        )
        line(20, 3, 20, 9, 14, 9)
    elif name == "sliders":
        line(3, 7, 7, 7)
        circle(10, 7, 2.5)
        line(13, 7, 21, 7)
        line(3, 17, 12, 17)
        circle(15, 17, 2.5)
        line(18, 17, 21, 17)
    elif name == "check":
        line(4, 12, 9, 17, 20, 6, width=2.2)
    elif name == "file":
        line(5, 3, 14, 3, 19, 8, 19, 21, 5, 21, 5, 3)
        line(14, 3, 14, 8, 19, 8)
    elif name == "search":
        circle(10, 10, 6)
        line(15, 15, 21, 21)
    elif name == "split":
        line(3, 5, 21, 5, 21, 19, 3, 19, 3, 5)
        line(12, 5, 12, 19)
    elif name == "unified":
        line(3, 5, 21, 5, 21, 19, 3, 19, 3, 5)
        line(3, 12, 21, 12)
    elif name == "arrow":
        line(3, 12, 20, 12)
        line(14, 6, 20, 12, 14, 18)


def glyph(parent, name, color=SUB, size=18):
    size = px(size)
    c = tk.Canvas(parent, width=size, height=size, bg=parent["bg"], highlightthickness=0, bd=0)
    icon(c, name, 0, 0, size, color)
    return c


def rounded(c, x, y, x2, y2, r, fill, outline=""):
    c.create_polygon(
        x + r,
        y,
        x2 - r,
        y,
        x2,
        y,
        x2,
        y + r,
        x2,
        y2 - r,
        x2,
        y2,
        x2 - r,
        y2,
        x + r,
        y2,
        x,
        y2,
        x,
        y2 - r,
        x,
        y + r,
        x,
        y,
        smooth=True,
        splinesteps=12,
        fill=fill,
        outline=outline,
    )


def button_metrics(parent, font, title):
    root = parent._root()
    if not hasattr(root, "_branchline_button_metrics"):
        call = root.tk.call

        @lru_cache(maxsize=256)
        def measure(description, text, scaling):
            # Pixel measurements belong to this interpreter and display scale.
            width = int(call("font", "measure", description, text))
            height = int(call("font", "metrics", description, "-linespace"))
            return width, height

        root._branchline_button_metrics = measure
    return root._branchline_button_metrics(font, title, root.tk.call("tk", "scaling"))


class Button(tk.Canvas):
    def __init__(
        self,
        parent,
        title,
        command,
        *,
        symbol=None,
        color=INK,
        fill=WHITE,
        hover=PALE,
        border=None,
        height=32,
        size=9,
        pad=12,
        align="center",
        bold=False,
    ):
        weight = "bold" if bold else "normal"
        self.font = tkfont.Font(root=parent, family=UI, size=size, weight=weight)
        self.symbol, self.title, self.command = symbol, title, command
        self.color, self.fill, self.hover, self.border = color, fill, hover, border
        self.pad, self.align = px(pad), align
        width, line_height = button_metrics(parent, (UI, size, weight), title)
        self.content_width = width + px(22 if title and symbol else 17 if symbol else 0)
        super().__init__(
            parent,
            bg=parent["bg"],
            highlightthickness=0,
            bd=0,
            takefocus=1,
            width=self.content_width + self.pad * 2,
            height=max(px(height), line_height + 4),
            cursor="hand2",
        )
        self.over = False
        self.bind("<Configure>", self.paint)
        self.bind("<Enter>", lambda e: self.highlight(True))
        self.bind("<Leave>", lambda e: self.highlight(False))
        self.bind("<FocusIn>", self.paint)
        self.bind("<FocusOut>", self.paint)
        self.bind("<Button-1>", lambda e: self.focus_set())
        self.bind("<ButtonRelease-1>", self.clicked)
        self.bind("<Return>", lambda e: self.command())
        self.bind("<space>", lambda e: self.command())

    def clicked(self, event):
        if 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height():
            self.command()

    def highlight(self, value):
        self.over = value
        self.paint()

    def paint(self, event=None):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        rounded(
            self,
            1,
            1,
            w - 1,
            h - 1,
            7,
            self.hover if self.over else self.fill,
            "#799482" if has_focus(self) else (self.border or ""),
        )
        x = self.pad if self.align == "left" else max(4, (w - self.content_width) / 2)
        if self.symbol:
            icon(self, self.symbol, x, (h - px(17)) / 2, px(17), self.color)
            x += px(22)
        self.create_text(x, h / 2, text=self.title, fill=self.color, font=self.font, anchor="w")


def artwork(c, large=False):
    """Draw a branching commit history on a drafting grid."""
    c.delete("all")
    w, h = c.winfo_width(), c.winfo_height()
    if w < 10:
        return
    ground = "#e8efe4" if large else PAPER
    c.configure(bg=ground)
    for x in range(12, w, 15):
        for y in range(10, h, 15):
            c.create_line(x, y, x + 1, y, fill="#c9d7c8")
    unit = min((w - 25) / 10, h / 5.5)
    ox, oy = (w - unit * 10) / 2, h / 2

    def p(x, y):
        return ox + x * unit, oy + y * unit

    def route(coords, color):
        pts = [v for x, y in coords for v in p(x, y)]
        c.create_line(*pts, fill=color, width=2 if large else 1.5, smooth=True, splinesteps=20)

    dark, green, copper = "#366b54", "#6d9e68", "#b08258"
    route([(0, 0), (10, 0)], dark)
    route([(1, 0), (1.5, 0), (2, -1.25), (2.7, -1.25), (6, -1.25), (6.5, -1.25), (7, 0), (7.7, 0)], green)
    route([(3, 0), (3.45, 0), (4, 1.3), (4.7, 1.3), (7.2, 1.3), (7.8, 1.3), (8.4, 0), (9, 0)], copper)
    for x, y, color in [
        (1, 0, dark),
        (2.8, -1.25, green),
        (5, -1.25, green),
        (3.1, 0, dark),
        (5.3, 1.3, copper),
        (7.15, 1.3, copper),
        (7.6, 0, dark),
        (9.4, 0, dark),
    ]:
        a, b = p(x, y)
        r = 4.3 if large else 3
        c.create_oval(a - r, b - r, a + r, b + r, fill=ground, outline=color, width=2)
