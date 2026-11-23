import { setFold, spans, suggestionSource } from "./review-ui.js";
import { icon } from "./icons.js";
import {
  CONTEXT_STEP,
  contextGaps,
  displayContext,
  expandGap,
  gapLength,
} from "./context.js";
import {
  Compartment,
  EditorSelection,
  EditorState,
  StateEffect,
  Text,
} from "@codemirror/state";
import {
  Decoration,
  EditorView,
  GutterMarker,
  ViewPlugin,
  WidgetType,
  gutter,
} from "@codemirror/view";

const repaint = StateEffect.define();
const codeFiles =
  /\.(c|cc|cpp|cs|go|h|hpp|java|js|jsx|json|kt|php|py|rb|rs|sh|swift|toml|ts|tsx)$/i;
const tokens =
  /(?<string>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|(?<comment>#.*|\/\/.*)|(?<keyword>\b(?:async|await|break|case|class|const|continue|def|else|elif|export|false|for|from|fn|func|function|if|import|in|interface|let|match|new|None|null|private|pub|public|raise|return|struct|throw|true|try|type|var|while|with|yield)\b)/g;
const rowClasses = { "+": "add", "-": "del", "@": "hunk", "\\": "meta" };

function element(name, className, text) {
  const node = document.createElement(name);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function button(label, run) {
  const node = element("button", "", label);
  node.type = "button";
  node.addEventListener("click", run);
  return node;
}

// Each cell refers to the original Git line, even when a replacement pairs
// rows with different offsets in the unified patch. Empty split cells use -1.
export function diffRows(lines, split) {
  if (!split) return lines.map((_, i) => [i]);
  const rows = [],
    minus = [],
    plus = [];
  function flush() {
    for (let i = 0; i < Math.max(minus.length, plus.length); i++) {
      rows.push([minus[i] ?? -1, plus[i] ?? -1]);
    }
    plus.length = minus.length = 0;
  }
  lines.forEach((line, i) => {
    if (line.kind === "-") minus.push(i);
    else if (line.kind === "+") plus.push(i);
    else {
      flush();
      rows.push([i, i]);
    }
  });
  flush();
  return rows;
}

// Keep matches on patch lines so a shared context line counts once in Split.
export function findDiffMatches(lines, query, limit = Infinity) {
  const matches = [],
    firstByLine = new Map();
  if (query) {
    const literal = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const pattern = new RegExp(literal, "giu");
    let line = -1;
    for (const { text, contextOnly, kind } of lines) {
      line++;
      if (contextOnly || kind === "@" || kind === "\\") continue;
      const first = matches.length;
      for (const hit of text.matchAll(pattern)) {
        matches.push({ line, from: hit.index, to: hit.index + hit[0].length });
        if (matches.length === limit) {
          firstByLine.set(line, first);
          return { matches, firstByLine };
        }
      }
      if (matches.length > first) firstByLine.set(line, first);
    }
  }
  return { matches, firstByLine };
}

function codeLine(line) {
  return line && (line.kind === " " || line.kind === "+" || line.kind === "-");
}

function includesLine(selection, index, line) {
  return (
    selection &&
    codeLine(line) &&
    index >= Math.min(selection.anchor, selection.head) &&
    index <= Math.max(selection.anchor, selection.head) &&
    (selection.side === "both" || line[selection.side] != null)
  );
}

export function selectedLines(lines, selection) {
  if (!selection) return [];
  const result = [];
  const start = Math.max(0, Math.min(selection.anchor, selection.head));
  const end = Math.min(
    lines.length - 1,
    Math.max(selection.anchor, selection.head),
  );
  for (let i = start; i <= end; i++) {
    if (includesLine(selection, i, lines[i])) result.push(lines[i]);
  }
  return result;
}

function commentDisabledReason(selected, hasSelection) {
  if (!hasSelection) return "";
  if (!selected.length) return "Select a code line to add a line comment.";
  if (selected.some((line) => line.contextOnly))
    return "Select lines within a diff hunk to add a line comment.";
  if (selected[0].hunk !== selected[selected.length - 1].hunk)
    return "Select lines within one hunk to comment.";
  return "";
}

export function canSuggest(file, side, selected) {
  return (
    side !== "old" &&
    ["100644", "100755"].includes(file.mode) &&
    selected.length > 0 &&
    selected[0].new != null &&
    selected.every(
      (l, i) =>
        !l.contextOnly &&
        l.new === selected[0].new + i &&
        l.hunk === selected[0].hunk,
    )
  );
}

export function canExpandFile(file) {
  return (
    !!file &&
    !file.binary &&
    file.added != null &&
    file.removed != null &&
    file.mode !== "160000" &&
    file.old_mode !== "160000"
  );
}

class ContextBlock extends WidgetType {
  constructor(control, hidden, toggle) {
    super();
    this.control = control;
    this.hidden = hidden;
    this.toggle = toggle;
  }
  get canStep() {
    const { remaining } = this.control;
    return remaining === null || remaining > CONTEXT_STEP;
  }

  eq(other) {
    const { gap, count, remaining, open } = this.control;
    const next = other.control;
    return (
      this.hidden === other.hidden &&
      gap === next.gap &&
      count === next.count &&
      remaining === next.remaining &&
      open === next.open
    );
  }

  get estimatedHeight() {
    return 28;
  }

  addButton(box, action, glyph, label, title) {
    const { gap } = this.control;
    const control = button(label, () => this.toggle(gap, action, box));
    control.className = "bl-expand";
    control.prepend(icon(glyph));
    control.title = title;
    if (!label) control.setAttribute("aria-label", title);
    if (!this.hidden) {
      control.dataset.contextAt = gap.at;
      control.dataset.contextAction = action;
    }
    box.append(control);
  }

  arrows() {
    const box = element("span", "bl-gap-arrows");
    const { remaining } = this.control;
    box.setAttribute("role", "group");
    box.setAttribute(
      "aria-label",
      remaining === null ? "Unchanged lines" : `${remaining} hidden lines`,
    );
    this.addButton(
      box,
      "top",
      "expand-down",
      "",
      `Show the first ${CONTEXT_STEP} hidden lines`,
    );
    this.addButton(
      box,
      "bottom",
      "expand-up",
      "",
      `Show the last ${CONTEXT_STEP} hidden lines`,
    );
    return box;
  }

  toDOM(view) {
    const { count, remaining, open } = this.control;
    const box = element("div", "bl-context");
    function lineCount(n) {
      return `${n.toLocaleString()} ${n === 1 ? "line" : "lines"}`;
    }
    // An empty patch (e.g. a rename) has no editor or line-number gutter.
    if (!view && this.canStep) box.append(this.arrows());
    if (!open) {
      const label =
        remaining === null
          ? "Show remaining lines"
          : `${lineCount(remaining)} hidden`;
      this.addButton(
        box,
        "all",
        "expand",
        label,
        "Show all remaining lines in this gap",
      );
    }
    if (open || (remaining !== null && remaining < count)) {
      this.addButton(
        box,
        "collapse",
        "collapse",
        open ? `Collapse ${lineCount(count)}` : "",
        "Collapse this gap",
      );
    }
    if (this.hidden) {
      box.classList.add("bl-spacer");
      box.inert = true;
      box.setAttribute("aria-hidden", "true");
    }
    return box;
  }
}

class GapArrows extends GutterMarker {
  constructor(widget) {
    super();
    this.widget = widget;
    this.elementClass = "bl-gutter-hunk bl-gutter-arrows";
  }
  eq(other) {
    return this.widget.eq(other.widget);
  }
  toDOM() {
    return this.widget.arrows();
  }
}

function gapFocusBounds(button) {
  const scroller = button.closest(".cm-scroller, .bl-diff-empty");
  if (!scroller) return;
  const bounds = scroller.getBoundingClientRect();
  const gutter = button.closest(".bl-gap-arrows")
    ? null
    : scroller.querySelector(".cm-gutters")?.getBoundingClientRect();
  return {
    scroller,
    top: bounds.top,
    bottom: bounds.top + scroller.clientHeight,
    left: Math.max(bounds.left, gutter?.right ?? 0),
    right: bounds.left + scroller.clientWidth,
  };
}

function revealGapFocus(button) {
  const bounds = gapFocusBounds(button);
  if (!bounds) return;
  const { scroller, top, bottom, left, right } = bounds;
  const box = button.getBoundingClientRect();
  // Scrolling the editor explicitly avoids scrolling the whole window and
  // keeps the sticky line numbers from covering the focused label.
  if (box.top < top) scroller.scrollTop += box.top - top;
  else if (box.bottom > bottom) scroller.scrollTop += box.bottom - bottom;
  if (box.left < left) scroller.scrollLeft += box.left - left;
  else if (box.right > right) scroller.scrollLeft += box.right - right;
}

function focusGapAction(root, at, action, fallback) {
  if (
    !root.isConnected ||
    root.closest("[inert]") ||
    document.activeElement !== document.body
  )
    return;
  const gap = `[data-context-at="${at}"]`;
  const visible = (button) => {
    if (!button || button.closest("[inert]")) return false;
    const box = button.getBoundingClientRect();
    const bounds = gapFocusBounds(button);
    if (!bounds || box.height <= 0) return false;
    const x = (box.left + box.right) / 2;
    const y = (box.top + box.bottom) / 2;
    return (
      box.top >= bounds.top &&
      box.bottom <= bounds.bottom &&
      x >= bounds.left &&
      x < bounds.right &&
      button.contains(document.elementFromPoint(x, y))
    );
  };
  const matching = root.querySelector(`${gap}[data-context-action="${action}"]`);
  const target = visible(matching)
    ? matching
    : [...root.querySelectorAll(gap)].find(visible) ?? fallback;
  target?.focus({ preventScroll: true });
}

function numberRange(lines, side) {
  const first = lines.find((l) => l[side] != null);
  if (!first) return [];
  let i = lines.length - 1;
  while (lines[i][side] == null) --i;
  return [first[side], lines[i][side]];
}

class NumberMarker extends GutterMarker {
  constructor(value, elementClass = "") {
    super();
    this.value = value;
    this.elementClass = elementClass;
  }
  eq(other) {
    return (
      other.value === this.value && other.elementClass === this.elementClass
    );
  }
  toDOM() {
    const label = element("span", "", this.value);
    label.setAttribute("aria-hidden", "true");
    return label;
  }
}

const gapGutter = new NumberMarker("", "bl-gutter-hunk");

class CommentBlock extends WidgetType {
  constructor(notes, hidden, controller) {
    super();
    this.notes = notes;
    this.hidden = hidden;
    this.controller = controller;
    this.collapsed = notes.map((n) => controller.folded(n));
  }

  // Both split panes reserve exactly the same space. Only the pane containing
  // the anchor exposes the card to pointer, keyboard and assistive technology.
  toDOM() {
    const box = element("div", "bl-comments");
    if (this.hidden) {
      box.classList.add("bl-spacer");
      box.inert = true;
      box.setAttribute("aria-hidden", "true");
    }
    this.notes.forEach((note, i) => {
      const card = element(
        "article",
        note.resolved ? "bl-card bl-resolved" : "bl-card",
      );
      const isSuggestion = typeof note.suggestion === "string";
      const title =
        (note.resolved ? "Resolved " : "Open ") +
        (isSuggestion ? "suggestion" : "comment");
      if (!this.hidden) card.dataset.note = note.id;
      const head = element("div", "bl-card-head");
      const toggle = button(title, () => this.controller.toggle(note));
      toggle.className = "bl-disclosure";
      toggle.setAttribute("aria-expanded", String(!this.collapsed[i]));
      head.append(toggle, element("span", "bl-location", spans(note)));
      card.append(head);
      if (!this.collapsed[i]) {
        if (note.body) card.append(element("p", "bl-body", note.body));
        if (isSuggestion) {
          const original = element("pre", "bl-before", suggestionSource(note));
          original.setAttribute("aria-label", "Original code");
          const proposed = element(
            "pre",
            "bl-after",
            note.suggestion || "Delete selected lines",
          );
          proposed.setAttribute("aria-label", "Suggested change");
          card.append(original, proposed);
        }
        const actions = element("div", "bl-card-actions");
        actions.append(
          button("Edit", () => this.controller.action("edit", note)),
        );
        actions.append(
          button(note.resolved ? "Reopen" : "Resolve", () =>
            this.controller.action(note.resolved ? "reopen" : "resolve", note),
          ),
        );
        if (isSuggestion && note.applied_location) {
          actions.append(
            element("span", "bl-applied", "Applied to working file"),
          );
        } else if (isSuggestion && this.controller.canApply(note)) {
          actions.append(
            button("Apply to working file", () =>
              this.controller.action("apply", note),
            ),
          );
        }
        card.append(actions);
      }
      box.append(card);
    });
    return box;
  }
}

export function isContextMenuKey(e) {
  return e.key === "ContextMenu" || (e.shiftKey && e.key === "F10");
}

export function contextMenu(event, items) {
  const returnFocus = event.target.closest(".cm-content,button,[tabindex]");
  const restoreFocus = () => {
    if (returnFocus?.isConnected) returnFocus.focus({ preventScroll: true });
  };
  const popup = element("div", "bl-diff-menu");
  popup.setAttribute("role", "menu");
  const close = () => {
    popup.remove();
    document.removeEventListener("pointerdown", outside, true);
    window.removeEventListener("blur", close);
  };
  function outside(e) {
    if (!popup.contains(e.target)) close();
  }
  for (const [label, run, enabled = true] of items) {
    const entry = button(label, () => {
      close();
      restoreFocus();
      run();
    });
    entry.setAttribute("role", "menuitem");
    entry.disabled = !enabled;
    popup.append(entry);
  }
  popup.addEventListener("keydown", (e) => {
    const entries = [...popup.querySelectorAll("button:enabled")];
    if (e.key === "Escape" || e.key === "Tab" || e.code === "Tab") {
      close();
      restoreFocus();
      if (e.key === "Escape") e.preventDefault();
      e.stopPropagation();
      return;
    }
    const direction = { ArrowDown: 1, ArrowUp: -1 }[e.key];
    if (direction) {
      e.preventDefault();
      e.stopPropagation();
      entries[
        (entries.indexOf(document.activeElement) + entries.length + direction) %
          entries.length
      ]?.focus();
    }
  });
  document.body.append(popup);
  popup.style.left =
    Math.max(
      0,
      Math.min(event.clientX, window.innerWidth - popup.offsetWidth),
    ) + "px";
  popup.style.top =
    Math.max(
      0,
      Math.min(event.clientY, window.innerHeight - popup.offsetHeight),
    ) + "px";
  popup.querySelector("button:enabled")?.focus();
  document.addEventListener("pointerdown", outside, true);
  window.addEventListener("blur", close);
  return close;
}

function emptyMessage(file) {
  if (file.binary || file.added === null || file.removed === null)
    return ["Binary file", "Git identified this file as binary."];
  if (file.group === "Untracked" && file.mode === "160000") {
    return [
      "Nested Git repository",
      file.oid?.replace(/0/g, "")
        ? "Checked-out commit " + file.oid.slice(0, 12)
        : "No readable HEAD commit.",
    ];
  }
  if (file.status === "R")
    return ["Renamed file", file.old + " → " + file.path];
  if (file.status === "U")
    return [
      "Unresolved conflict",
      "The working copy has no text changes against our side.",
    ];
  if (file.mode !== file.old_mode)
    return [
      "No text changes",
      "File mode " + file.old_mode + " → " + file.mode,
    ];
  return ["No text changes", "The file contents are identical."];
}

export function createDiff(parent, options) {
  const { lines: patch, file, folds = new Map() } = options;
  const gaps =
    canExpandFile(file) && options.loadContents ? contextGaps(patch, file) : [];
  const expanded = new Map();
  let { lines, controls } = displayContext(patch, gaps, expanded);
  let contents,
    loadingContents,
    disposed = false,
    contextVersion = 0,
    searchVersion = 0,
    full = false;
  let explicitHit;
  let notes = options.notes || [];
  let selection = options.position?.selection ?? null,
    activeCol = 0;
  const layouts = new Map();
  let layout, closeMenu, paintFrame, restoreFrame, pendingPosition;
  let notesVersion = 0;
  const isCode = codeFiles.test(file.path);
  const numbered = { old: new Map(), new: new Map() };
  let digits = 2;
  function indexLines() {
    numbered.old.clear();
    numbered.new.clear();
    lines.forEach((line, i) => {
      for (const side of ["old", "new"]) {
        if (line[side] != null) {
          numbered[side].set(line[side], i);
          digits = Math.max(digits, String(line[side]).length);
        }
      }
    });
  }
  indexLines();

  let resumeFromGap = false;
  const controller = {
    folded: (n) => folds.get(n.id) ?? !!n.resolved,
    canApply: (n) => !!options.canApply?.(n),
    action: (action, note) => options.onAction?.(action, note),
    toggle(note) {
      setFold(folds, note, !controller.folded(note));
      refreshNotes();
    },
  };

  function colSide(col) {
    return layout.split ? (col === 0 ? "old" : "new") : "both";
  }

  function paintSelection() {
    if (layout.drawnSelection === selection) return;
    layout.drawnSelection = selection;
    for (const { view } of layout.panes)
      view.dispatch({ effects: repaint.of(null) });
  }

  function changedSelection(next) {
    resumeFromGap = false;
    selection = next;
    if (!paintFrame)
      paintFrame = requestAnimationFrame(() => {
        paintFrame = null;
        paintSelection();
        announceSelection();
      });
  }

  function announceSelection() {
    const selected = selectedLines(lines, selection);
    const side = selection?.side ?? "both";
    const label =
      selection && !selected.length
        ? "Select a code line"
        : spans({
            old: side === "new" ? [] : numberRange(selected, "old"),
            new: side === "old" ? [] : numberRange(selected, "new"),
          });
    const reason = commentDisabledReason(selected, !!selection);
    options.onSelection?.({
      label,
      canComment: !reason,
      commentDisabledReason: reason,
      canSuggest: canSuggest(file, side, selected),
    });
  }

  function compose(suggestion = false, wholeFile = false) {
    const selected = wholeFile ? [] : selectedLines(lines, selection);
    const side = selection?.side ?? "both";
    const reason = commentDisabledReason(selected, !wholeFile && !!selection);
    if (reason) return options.onStatus?.(reason);
    if (suggestion && !canSuggest(file, side, selected))
      return options.onStatus?.(
        "Select consecutive lines on the new side to suggest a change.",
      );
    options.onCompose?.({
      lines: selected,
      side: suggestion ? "new" : wholeFile ? "both" : side,
      suggestion,
    });
  }

  function syncSelection(view, col) {
    const { rows } = layout;
    const { anchor, head } = view.state.selection.main;
    const a = view.state.doc.lineAt(anchor).number - 1,
      b = view.state.doc.lineAt(head).number - 1;
    const step = a <= b ? 1 : -1;
    let first = a,
      last = b;
    while (rows[first][col] === -1 && first !== b) first += step;
    while (rows[last][col] === -1 && last !== a) last -= step;
    activeCol = col;
    const start = rows[first][col],
      end = rows[last][col];
    changedSelection(
      start < 0 || end < 0
        ? null
        : { anchor: start, head: end, side: colSide(col) },
    );
  }

  function selectRow(col, row, extend) {
    const index = layout.rows[row]?.[col];
    if (index == null || index < 0) return;
    activeCol = col;
    const side = colSide(col);
    changedSelection({
      side,
      anchor: extend && selection?.side === side ? selection.anchor : index,
      head: index,
    });
  }

  function copySelected() {
    const selected = selectedLines(lines, selection);
    if (!selected.length) return;
    const text = selected.map((l) => l.text).join("\n");
    const result = options.onCopy
      ? options.onCopy(text)
      : navigator.clipboard?.writeText(text);
    if (result?.catch)
      result.catch((error) => options.onStatus?.(String(error)));
  }

  function menuAt(event, col, row) {
    const index = layout.rows[row]?.[col];
    if (index >= 0 && !includesLine(selection, index, lines[index]))
      selectRow(col, row, false);
    const selected = selectedLines(lines, selection);
    closeMenu?.();
    closeMenu = contextMenu(event, [
      [
        "Add comment",
        () => compose(),
        !commentDisabledReason(selected, !!selection),
      ],
      [
        "Suggest change",
        () => compose(true),
        canSuggest(file, selection?.side, selected),
      ],
      [
        "Comment on file",
        () => {
          changedSelection(null);
          compose(false, true);
        },
      ],
      ["Copy selected lines", copySelected, selected.length > 0],
    ]);
  }

  function arrow(view, col, delta, extend) {
    const { rows, rowForLine } = layout;
    const doc = view.state.doc;
    const top = view.scrollDOM.scrollTop;
    const head = selection && rowForLine[selection.head];
    const block =
      Number.isInteger(head) && view.lineBlockAt(doc.line(head + 1).from);
    const continueFromHead =
      block &&
      (!resumeFromGap ||
        (block.bottom > top && block.top < top + view.scrollDOM.clientHeight));
    const visible = () => doc.lineAt(view.lineBlockAtHeight(top).from).number - 1;
    let row = continueFromHead ? head + delta : visible();
    const fromGap = resumeFromGap && !continueFromHead;
    resumeFromGap = false;
    row = Math.max(0, Math.min(rows.length - 1, row));
    const direction = continueFromHead ? delta : 1;
    while (
      row >= 0 &&
      row < rows.length &&
      (rows[row][col] < 0 || (fromGap && !codeLine(lines[rows[row][col]])))
    )
      row += direction;
    if (!rows[row]) return;
    selectRow(col, row, extend);
    view.dispatch({
      effects: EditorView.scrollIntoView(doc.line(row + 1).from),
    });
  }

  function collectAnchors(owner) {
    const { rowForLine } = owner;
    owner.anchorRows = new Map();
    owner.pinned = [];
    owner.notesVersion = notesVersion;
    const groups = new Map();
    for (const note of notes) {
      const ends = [];
      for (const side of ["old", "new"]) {
        const range = note[side];
        if (!range?.length) continue;
        const start = rowForLine[numbered[side].get(range[0])];
        const end = rowForLine[numbered[side].get(range[1])];
        if (end == null) continue;
        ends.push(end);
        for (let i = start ?? end; i <= end; i++)
          owner.pinned[i] = (owner.pinned[i] ?? 0) | (side === "old" ? 1 : 2);
      }
      if (!ends.length && (note.old?.length || note.new?.length)) continue;
      const row = ends.length ? Math.max(...ends) : -1;
      owner.anchorRows.set(note.id, row);
      if (!groups.has(row)) groups.set(row, []);
      groups.get(row).push(note);
    }
    return groups;
  }

  function noteDecorations(owner, doc, groups, col) {
    const ranges = [];
    for (const control of controls) {
      const atEnd = control.before === lines.length;
      const row = owner.rowForLine[control.before];
      const pos = atEnd ? doc.length : doc.line(row + 1).from;
      ranges.push(
        Decoration.widget({
          widget: new ContextBlock(control, col !== 0, toggleGap),
          block: true,
          side: atEnd ? 2 : -2,
        }).range(pos),
      );
    }
    for (const [row, group] of groups) {
      const visibleCol = owner.split && group.some((n) => n.new?.length) ? 1 : 0;
      const pos = row < 0 ? 0 : doc.line(row + 1).to;
      ranges.push(
        Decoration.widget({
          widget: new CommentBlock(group, col !== visibleCol, controller),
          block: true,
          side: row < 0 ? -1 : 1,
        }).range(pos),
      );
    }
    return EditorView.decorations.of(Decoration.set(ranges, true));
  }

  function marks(view, col, owner, side) {
    const ranges = [];
    const { rows, drawnSelection } = owner;
    const current = owner.controls === controls;
    for (const range of view.visibleRanges) {
      let row = view.state.doc.lineAt(range.from);
      while (true) {
        const index = rows[row.number - 1]?.[col];
        const line = owner.lines[index];
        let cls = line ? rowClasses[line.kind] : "gap";
        let attrs = cls ? "bl-row-" + cls : "";
        if (
          current &&
          (drawnSelection?.side === "both" ||
            side === "both" ||
            drawnSelection?.side === side) &&
          includesLine(drawnSelection, index, line)
        )
          attrs += " bl-row-picked";
        if (attrs)
          ranges.push(Decoration.line({ class: attrs.trim() }).range(row.from));
        if (isCode && codeLine(line) && line.text.length < 3000) {
          tokens.lastIndex = 0;
          for (const match of line.text.matchAll(tokens)) {
            const token = Object.keys(match.groups).find(
              (k) => match.groups[k] !== undefined,
            );
            ranges.push(
              Decoration.mark({ class: "bl-token-" + token }).range(
                row.from + match.index,
                row.from + match.index + match[0].length,
              ),
            );
          }
        }
        if (
          current &&
          line &&
          explicitHit?.line === line &&
          sideMatches(side, explicitHit.side)
        ) {
          const { from, to } = explicitHit;
          if (from < to)
            ranges.push(
              Decoration.mark({ class: "bl-find-current" }).range(
                row.from + from,
                row.from + to,
              ),
            );
        }
        if (row.to >= range.to || row.number === view.state.doc.lines) break;
        row = view.state.doc.line(row.number + 1);
      }
    }
    return Decoration.set(ranges, true);
  }

  function headerNames() {
    if (file.group === "Staged")
      return [options.emptyBase ? "Empty" : "HEAD", "Index"];
    if (file.group === "Unstaged")
      return [file.status === "U" ? "Ours" : "Index", "Working tree"];
    if (file.group === "Untracked") return ["Empty", "Working tree"];
    return ["Base", "Head"];
  }

  function makePane(col, groups) {
    // Each editor keeps its own row and gutter data while the other layout is visible.
    const owner = layout;
    const { split, rows } = owner;
    const side = colSide(col);
    const container = element("section", "bl-pane");
    if (split)
      container.append(element("div", "bl-pane-heading", headerNames()[col]));
    layout.root.append(container);
    const doc = Text.of(rows.map((row) => lines[row[col]]?.text ?? ""));
    const cardConfig = new Compartment();
    const numberText = (line, row) => {
      const visibleSides =
        (line?.new != null ? 2 : 0) | (line?.old != null ? 1 : 0);
      const pin =
        (owner.pinned[row] || 0) & visibleSides & (split ? (col ? 2 : 1) : 3);
      const fmt = (n) => String(n ?? "").padStart(digits);
      const number = split
        ? fmt(line?.[side])
        : fmt(line?.old) + " " + fmt(line?.new);
      return (
        (pin ? "• " : "  ") + number + " " + (codeLine(line) ? line.kind : " ")
      );
    };
    const render = ViewPlugin.fromClass(
      class {
        constructor(view) {
          this.decorations = marks(view, col, owner, side);
        }
        update(update) {
          // The gutter plugin can detach its entire DOM during this update.
          // Only recover focus if it was actually on an arrow in this pane.
          const active = document.activeElement;
          if (
            active?.matches(".bl-gap-arrows button") &&
            update.view.dom.contains(active)
          ) {
            const { contextAt, contextAction } = active.dataset;
            queueMicrotask(() =>
              focusGapAction(update.view.dom, contextAt, contextAction),
            );
          }
          if (
            update.viewportChanged ||
            update.transactions.some((tr) =>
              tr.effects.some((e) => e.is(repaint)),
            )
          ) {
            this.decorations = marks(update.view, col, owner, side);
          }
        }
      },
      { decorations: (plugin) => plugin.decorations },
    );
    const view = new EditorView({
      parent: container,
      state: EditorState.create({
        doc,
        extensions: [
          EditorState.readOnly.of(true),
          EditorState.tabSize.of(4),
          EditorView.contentAttributes.of({
            "aria-label": (split ? headerNames()[col] : "Unified") + " diff",
            "aria-readonly": "true",
            spellcheck: "false",
          }),
          render,
          cardConfig.of(noteDecorations(owner, doc, groups, col)),
          gutter({
            class: "bl-line-numbers",
            initialSpacer: () => new NumberMarker(numberText(null, -1)),
            updateSpacer: () => new NumberMarker(numberText(null, -1)),
            lineMarker: (view, block) => {
              const n = view.state.doc.lineAt(block.from).number - 1;
              const line = owner.lines[owner.rows[n]?.[col]];
              const kind = line && rowClasses[line.kind];
              return new NumberMarker(
                numberText(line, n),
                kind ? "bl-gutter-" + kind : "",
              );
            },
            widgetMarker: (_view, widget) => {
              if (!(widget instanceof ContextBlock)) return null;
              return !widget.hidden && widget.canStep
                ? new GapArrows(widget)
                : gapGutter;
            },
            lineMarkerChange: (update) =>
              update.transactions.some((tr) =>
                tr.effects.some((e) => e.is(repaint)),
              ),
            domEventHandlers: {
              mousedown(view, block, event) {
                if (
                  event.button !== 0 ||
                  event.target.closest(".bl-gap-arrows")
                )
                  return false;
                view.focus();
                selectRow(
                  col,
                  view.state.doc.lineAt(block.from).number - 1,
                  event.shiftKey,
                );
                event.preventDefault();
                return true;
              },
              contextmenu(view, block, event) {
                if (event.target.closest(".bl-gap-arrows")) return false;
                event.preventDefault();
                view.focus();
                menuAt(
                  {
                    target: view.contentDOM,
                    clientX: event.clientX,
                    clientY: event.clientY,
                  },
                  col,
                  view.state.doc.lineAt(block.from).number - 1,
                );
                return true;
              },
            },
          }),
          EditorView.updateListener.of((update) => {
            if (layout === owner && update.selectionSet && update.view.hasFocus)
              syncSelection(update.view, col);
          }),
          EditorView.domEventHandlers({
            focus() {
              activeCol = col;
              return false;
            },
            mousedown(e, view) {
              if (e.button !== 0) return false;
              const pos = view.posAtCoords(
                { x: e.clientX, y: e.clientY },
                false,
              );
              if (pos != null) {
                const row = view.state.doc.lineAt(pos).number - 1;
                if (e.shiftKey && selection) {
                  selectRow(col, row, true);
                  e.preventDefault();
                  return true;
                }
                selectRow(col, row, false);
              }
              return false; // CodeMirror owns pointer dragging and autoscroll.
            },
            keydown(e, view) {
              if (e.metaKey || e.ctrlKey || e.altKey) return false;
              if (isContextMenuKey(e)) {
                e.preventDefault();
                const rect = view.scrollDOM.getBoundingClientRect();
                const row = selection && owner.rowForLine[selection.head];
                const point =
                  Number.isInteger(row) &&
                  view.coordsAtPos(view.state.doc.line(row + 1).from);
                menuAt({
                  target: view.contentDOM,
                  clientX: Math.max(rect.left, point?.left ?? rect.left) + 8,
                  clientY:
                    point && point.bottom >= rect.top && point.bottom <= rect.bottom
                      ? point.bottom
                      : rect.top + 12,
                });
                return true;
              }
              if (e.key === "ArrowDown" || e.key === "ArrowUp")
                arrow(view, col, e.key === "ArrowDown" ? 1 : -1, e.shiftKey);
              else if (e.key === "Escape") changedSelection(null);
              else if (e.key === "c" || e.key === "Enter") compose();
              else if (e.key === "s") compose(true);
              else return false;
              e.preventDefault();
              return true;
            },
            copy(e) {
              const selected = selectedLines(lines, selection);
              if (!selected.length || !e.clipboardData) return false;
              e.clipboardData.setData(
                "text/plain",
                selected.map((l) => l.text).join("\n"),
              );
              e.preventDefault();
              return true;
            },
            contextmenu(e, view) {
              e.preventDefault();
              const pos = view.posAtCoords(
                { x: e.clientX, y: e.clientY },
                false,
              );
              menuAt(
                e,
                col,
                pos == null ? -1 : view.state.doc.lineAt(pos).number - 1,
              );
              return true;
            },
          }),
        ],
      }),
    });
    // CodeMirror hides its gutters from assistive technology by default.
    // The directional buttons belong in the tab order. The numbers are visual.
    if (col === 0 && gaps.length)
      view.scrollDOM
        .querySelector(".cm-gutters")
        ?.removeAttribute("aria-hidden");
    view.scrollDOM.addEventListener("scroll", () => {
      if (layout !== owner || pendingPosition) return;
      const other = owner.panes[1 - col]?.view;
      if (
        other &&
        other !== view &&
        Math.abs(other.scrollDOM.scrollTop - view.scrollDOM.scrollTop) > 1
      ) {
        other.scrollDOM.scrollTop = view.scrollDOM.scrollTop;
      }
    });
    return { view, cardConfig };
  }

  function empty(groups) {
    const box = element("div", "bl-diff-empty");
    const [title, detail] = emptyMessage(file);
    box.append(
      element("h3", "", title),
      element("p", "", detail),
      button("Comment on file", () => compose(false, true)),
    );
    if (controls.length)
      box.append(new ContextBlock(controls[0], false, toggleGap).toDOM());
    if (groups.has(-1))
      box.append(new CommentBlock(groups.get(-1), false, controller).toDOM());
    layout.root.replaceChildren(box);
  }

  function refreshNotes() {
    const active = document.activeElement;
    const note = active?.closest("[data-note]");
    const focusedId = note && layout.root.contains(note) ? note.dataset.note : null;
    notesVersion++;
    drawNotes();
    if (!focusedId || document.activeElement !== document.body) return;
    const replacement = layout.root.querySelector(
      `[data-note="${focusedId}"] .bl-disclosure`,
    );
    const fallback =
      layout.panes[activeCol]?.view.contentDOM ??
      layout.root.querySelector(".bl-diff-empty > button");
    (replacement ?? fallback)?.focus({ preventScroll: true });
  }

  function drawNotes() {
    const groups = collectAnchors(layout);
    layout.drawnSelection = selection;
    if (!layout.rows.length) return empty(groups);
    layout.panes.forEach(({ view, cardConfig }, col) => {
      view.dispatch({
        effects: [
          cardConfig.reconfigure(
            noteDecorations(layout, view.state.doc, groups, col),
          ),
          repaint.of(null),
        ],
      });
    });
  }

  function position() {
    if (pendingPosition)
      return { ...pendingPosition, selection, side: colSide(activeCol) };
    const { panes, rows } = layout;
    const view = panes[activeCol]?.view || panes[0]?.view;
    if (!view) return { selection };
    const block = view.lineBlockAtHeight(view.scrollDOM.scrollTop);
    const row = rows[view.state.doc.lineAt(block.from).number - 1];
    const top = row[activeCol] >= 0 ? row[activeCol] : row.find((i) => i >= 0);
    return {
      top,
      offset: view.scrollDOM.scrollTop - block.top,
      x: view.scrollDOM.scrollLeft,
      side: colSide(activeCol),
      selection,
    };
  }

  function cancelRestore() {
    cancelAnimationFrame(restoreFrame);
    pendingPosition = null;
  }

  async function loadContents() {
    if (!contents) {
      loadingContents ??= options
        .loadContents()
        .then((result) => (contents = result))
        .finally(() => {
          loadingContents = null;
        });
      await loadingContents;
    }
    return contents;
  }

  function dropLayouts() {
    cancelAnimationFrame(paintFrame);
    paintFrame = null;
    cancelRestore();
    closeMenu?.();
    for (const { panes, root } of layouts.values()) {
      for (const { view } of panes) view.destroy();
      root.remove();
    }
    layouts.clear();
    layout = undefined;
  }

  // Persisted positions use patch indices. Expanded positions refer to the
  // display list, where the same Git line can have a different index.
  function remapPosition(saved, source, target) {
    if (source === target) return saved;
    const indexOf = (i) => {
      const line = source[i];
      if (!line) return -1;
      if (!line.contextOnly) return target.indexOf(line);
      return target.findIndex(
        (candidate) => candidate.new === line.new && candidate.old === line.old,
      );
    };
    const anchor = indexOf(saved.selection?.anchor),
      head = indexOf(saved.selection?.head);
    let top = indexOf(saved.top);
    if (top < 0 && source[saved.top]?.contextOnly) {
      // Stay at the hunk bordering a gap when collapsing the row at the top.
      let i = saved.top;
      while (i < source.length && source[i].contextOnly) i++;
      if (i === source.length) {
        i = saved.top - 1;
        while (i >= 0 && source[i].contextOnly) i--;
      }
      top = indexOf(i);
    }
    return {
      ...saved,
      top,
      selection:
        anchor >= 0 && head >= 0 ? { ...saved.selection, anchor, head } : null,
    };
  }

  function rebuildContext(anchor, restored) {
    const split = layout.split,
      previous = lines,
      saved = position();
    const next = displayContext(patch, gaps, expanded, contents);
    const restore = remapPosition(saved, previous, next.lines);
    if (anchor) {
      const control = next.controls.find((c) => c.gap === anchor.gap);
      if (control) {
        // When the last hidden lines appear, stay where the gap used to be.
        const at = control.before + (control.open ? anchor.previousTop : 0);
        restore.top = Math.min(at, next.lines.length - 1);
        restore.offset = -anchor.y;
      }
    }
    // Only an empty patch, such as a pure rename, changes the editor surface.
    const retainsPanes = previous.length > 0 && next.lines.length > 0;
    if (!retainsPanes) dropLayouts();
    else {
      cancelRestore();
      closeMenu?.();
    }
    ({ lines, controls } = next);
    selection = restore.selection;
    indexLines();
    if (explicitHit?.line.contextOnly) {
      const current = lines[numbered.new.get(explicitHit.line.new)];
      explicitHit = current ? { ...explicitHit, line: current } : undefined;
    }
    if (retainsPanes) {
      // Catch the other layout up when opened, outside expansion's hot path.
      updateContextRows(layout);
      restorePosition(restore, { restored });
      announceSelection();
    } else showLayout(split, restore, restored);
    if (controls.length) full = controls.every((control) => control.open);
    options.onContextChange?.({ full, expanded: expanded.size > 0 });
  }

  function indexLayout(owner) {
    owner.root.style.setProperty("--bl-line-number-digits", digits);
    owner.lines = lines;
    owner.controls = controls;
    owner.rows = diffRows(lines, owner.split);
    owner.rowForLine = Array(lines.length);
    owner.rows.forEach((cells, i) => {
      for (const cell of cells) if (cell >= 0) owner.rowForLine[cell] = i;
    });
  }

  function updateContextRows(owner) {
    const { rows: oldRows, lines: previous } = owner;
    indexLayout(owner);
    owner.drawnSelection = selection;
    const { rows } = owner;
    const sameRow = (a, b) =>
      rows[b].every((index, col) => {
        const before = previous[oldRows[a][col]];
        const after = lines[index];
        return (
          before === after ||
          (before?.contextOnly &&
            after?.contextOnly &&
            before.old === after.old &&
            before.new === after.new)
        );
      });
    let start = 0,
      oldEnd = oldRows.length,
      end = rows.length;
    while (start < oldEnd && start < end && sameRow(start, start)) start++;
    while (oldEnd > start && end > start && sameRow(oldEnd - 1, end - 1)) {
      oldEnd--;
      end--;
    }
    const groups = collectAnchors(owner);
    owner.panes.forEach(({ view, cardConfig }, col) => {
      const doc = view.state.doc;
      let changes;
      // Keep all matching rows before and after the reveal in CodeMirror.
      if (start !== oldEnd || start !== end) {
        const offset = (row) =>
          row < oldRows.length ? doc.line(row + 1).from : doc.length;
        let from = offset(start);
        const insert = rows
          .slice(start, end)
          .map((row) => lines[row[col]]?.text ?? "");
        if (oldEnd < oldRows.length) insert.push("");
        else if (start > 0) {
          if (start < oldRows.length) from--;
          insert.unshift("");
        }
        changes = view.state.changes({
          from,
          to: offset(oldEnd),
          insert: Text.of(insert),
        });
      }
      view.dispatch({
        changes,
        effects: [
          cardConfig.reconfigure(
            noteDecorations(owner, changes?.apply(doc) ?? doc, groups, col),
          ),
          repaint.of(null),
        ],
      });
    });
  }

  async function toggleGap(gap, action, box) {
    const turn = ++contextVersion;
    const fromFocus = box.contains(document.activeElement);
    searchVersion++;
    try {
      await loadContents();
      if (disposed || turn !== contextVersion) return;
      const scroller = box.closest(".cm-scroller");
      let y = scroller
        ? box.getBoundingClientRect().top - scroller.getBoundingClientRect().top
        : 0;
      // Leave space to read the newly revealed rows on the side that grew.
      if (scroller && action === "top")
        y = Math.max(y, scroller.clientHeight / 3);
      if (scroller && action === "bottom")
        y = Math.min(y, (scroller.clientHeight * 2) / 3);
      const previousTop = expanded.get(gap.at)?.top ?? 0;
      const count = gapLength(gap, contents);
      expandGap(expanded, gap, count, action);
      rebuildContext({ gap, y, previousTop }, () => {
        if (disposed || turn !== contextVersion) return;
        if (fromFocus && document.activeElement === document.body)
          resumeFromGap = true;
        focusGapAction(
          layout.root,
          gap.at,
          action,
          layout.panes[0]?.view.contentDOM ??
            layout.root.querySelector(".bl-diff-empty button"),
        );
      });
      if (!count) options.onStatus?.("This hunk reaches the end of the file.");
    } catch (error) {
      if (!disposed) options.onStatus?.(String(error));
    }
  }

  function sideMatches(column, side) {
    return column === "both" || side === "both" || column === side;
  }
  function paintFind() {
    for (const owner of layouts.values()) {
      if (owner.controls !== controls) continue;
      for (const { view } of owner.panes)
        view.dispatch({ effects: repaint.of(null) });
    }
  }
  function scrollToMatch(index, side, from, to) {
    cancelRestore();
    const row = layout.rowForLine[index],
      cells = layout.rows[row];
    if (layout.split && side !== "both") activeCol = side === "new" ? 1 : 0;
    if (cells[activeCol] !== index) activeCol = cells.indexOf(index);
    const view = layout.panes[activeCol].view;
    const start = view.state.doc.line(row + 1).from;
    const match = EditorSelection.range(start + from, start + to);
    if (layout.split) {
      restorePosition(
        {
          top: index,
          offset: (view.defaultLineHeight - view.scrollDOM.clientHeight) / 2,
          x: view.scrollDOM.scrollLeft,
          side: colSide(activeCol),
          selection,
        },
        { match },
      );
      return;
    }
    view.dispatch({
      effects: EditorView.scrollIntoView(match, { y: "center" }),
    });
  }
  function reveal(index, side, from, to) {
    const line = lines[index];
    if (!line) return false;
    const start = Math.max(0, Math.min(from ?? 0, line.text.length));
    const end = Math.max(start, Math.min(to ?? line.text.length, line.text.length));
    explicitHit = { line, side, from: start, to: end };
    paintFind();
    scrollToMatch(index, side, start, end);
    return true;
  }

  function restorePosition(saved, { measured, restored, match } = {}) {
    const row = layout.rowForLine[saved?.top];
    if (row == null) return restored?.();
    const views = layout.panes.map(({ view }) => view);
    const source = views[activeCol];
    const sourcePos = source.state.doc.line(row + 1).from;
    const offset = saved.offset || 0;
    const horizontal = views.map((view) =>
      view === source ? saved.x || 0 : view.scrollDOM.scrollLeft,
    );

    function align() {
      const top = source.lineBlockAt(sourcePos).top + offset;
      for (const [i, view] of views.entries()) {
        if (view.scrollDOM.scrollTop !== top) view.scrollDOM.scrollTop = top;
        // Keep the horizontal reveal of the matching text in its source pane.
        if (view === source && match) continue;
        if (view.scrollDOM.scrollLeft !== horizontal[i])
          view.scrollDOM.scrollLeft = horizontal[i];
      }
    }

    // Reopening a measured pane can stay synchronous when its anchor is visible.
    if (
      measured &&
      sourcePos >= source.viewport.from &&
      sourcePos <= source.viewport.to
    ) {
      align();
      return restored?.();
    }

    // Each pane needs to measure this row before either can drive scroll sync.
    // Otherwise one pane can clamp a copied offset to zero during its update.
    pendingPosition = saved;
    for (const view of views) {
      const pos = view.state.doc.line(row + 1).from;
      const target = view === source && match ? match : pos;
      view.dispatch({
        effects: EditorView.scrollIntoView(target, {
          y: "start",
          yMargin: -offset,
        }),
      });
    }
    restoreFrame = requestAnimationFrame(() => {
      align();
      restoreFrame = requestAnimationFrame(() => {
        pendingPosition = null;
        restored?.();
      });
    });
  }

  function showLayout(split, saved, restored) {
    cancelRestore();
    closeMenu?.();
    const width = parent.clientWidth,
      height = parent.clientHeight;
    if (layout) {
      layout.width = width;
      layout.height = height;
      layout.scale = window.devicePixelRatio;
      layout.root.inert = true;
    }
    layout = layouts.get(split);
    const staleContext = layout && layout.controls !== controls;
    // A resize can wrap a comment and change every row position below it.
    const measured =
      layout &&
      !staleContext &&
      layout.notesVersion === notesVersion &&
      width > 0 &&
      height > 0 &&
      layout.width === width &&
      layout.height === height &&
      layout.scale === window.devicePixelRatio;
    if (layout) {
      layout.root.inert = false;
      if (staleContext) updateContextRows(layout);
      else if (layout.notesVersion !== notesVersion) drawNotes();
      else paintSelection();
    } else {
      const root = element("div", "bl-diff");
      root.addEventListener("focusin", (event) => {
        const action = event.target.closest("[data-context-action]");
        if (!action) return;
        requestAnimationFrame(() => {
          if (document.activeElement === action) revealGapFocus(action);
        });
      });
      root.addEventListener("keydown", (event) => {
        if (
          !event.target.closest("[data-context-action]") ||
          !["ArrowDown", "ArrowUp"].includes(event.key) ||
          event.altKey ||
          event.ctrlKey ||
          event.metaKey
        )
          return;
        const pane = layout.panes[activeCol];
        if (!pane) return;
        event.preventDefault();
        event.stopPropagation();
        pane.view.focus();
        resumeFromGap = true;
        arrow(pane.view, activeCol, event.key === "ArrowDown" ? 1 : -1, event.shiftKey);
      }, true);
      root.classList.toggle("bl-split", split && lines.length > 0);
      root.setAttribute("role", "region");
      root.setAttribute("aria-label", split ? "Split diff" : "Unified diff");
      parent.append(root);
      layout = {
        root,
        split,
        panes: [],
        drawnSelection: selection,
      };
      indexLayout(layout);
      layouts.set(split, layout);
      const groups = collectAnchors(layout);
      if (layout.rows.length) {
        layout.panes.push(makePane(0, groups));
        if (split) layout.panes.push(makePane(1, groups));
      } else empty(groups);
    }
    activeCol =
      split &&
      ((saved?.side ?? selection?.side) === "new" ||
        (saved?.side === "both" &&
          selection &&
          lines[selection.head]?.new != null))
        ? 1
        : 0;
    restorePosition(saved, { measured, restored });
    announceSelection();
  }

  showLayout(options.mode?.toLowerCase() === "split", options.position);
  return {
    contents: loadContents,
    async showFullFile() {
      const turn = ++contextVersion;
      searchVersion++;
      if (gaps.length) await loadContents();
      if (disposed || turn !== contextVersion) return;
      full = true;
      if (!gaps.length)
        return options.onContextChange?.({ full, expanded: false });
      for (const gap of gaps)
        expandGap(expanded, gap, gapLength(gap, contents), "all");
      rebuildContext();
    },
    collapseContext() {
      contextVersion++;
      searchVersion++;
      full = false;
      if (!expanded.size)
        return options.onContextChange?.({ full, expanded: false });
      expanded.clear();
      rebuildContext();
    },
    async revealLine(side, number, from, to) {
      const turn = ++searchVersion;
      if (!numbered[side]?.has(number)) {
        await loadContents();
        if (disposed || turn !== searchVersion) return false;
        const gap = gaps.find(
          (g) => number >= g[side] && number < g[side] + gapLength(g, contents),
        );
        if (!gap) return false;
        expandGap(expanded, gap, gapLength(gap, contents), "all");
        rebuildContext();
      }
      return reveal(numbered[side].get(number), side, from, to);
    },
    revealPatchRow(index, from, to) {
      searchVersion++;
      const line = patch[index];
      return reveal(
        lines === patch ? index : lines.indexOf(line),
        line?.kind === "-" ? "old" : line?.kind === "+" ? "new" : "both",
        from,
        to,
      );
    },
    setMode(value) {
      const split = value.toLowerCase() === "split";
      if (split !== layout.split) showLayout(split, position());
    },
    setNotes(next) {
      const previous = new Map(notes.map((n) => [n.id, !!n.resolved]));
      for (const note of next) {
        if (previous.has(note.id) && previous.get(note.id) !== !!note.resolved)
          folds.delete(note.id);
      }
      notes = next;
      refreshNotes();
    },
    getPosition() {
      return remapPosition(position(), lines, patch);
    },
    jump(id) {
      const row = layout.anchorRows.get(id);
      if (row == null) return false;
      const note = notes.find((n) => n.id === id);
      setFold(folds, note, false);
      refreshNotes();
      const { panes } = layout;
      if (!panes.length) return true;
      const side = note.new?.length ? "new" : "old";
      activeCol = layout.split && side === "new" ? 1 : 0;
      const span = note[side],
        start = numbered[side].get(span?.[0]),
        end = numbered[side].get(span?.[1]);
      changedSelection(
        start != null && end != null
          ? { anchor: start, head: end, side }
          : null,
      );
      const view = panes[activeCol].view;
      cancelRestore();
      const pos = row < 0 ? 0 : view.state.doc.line(row + 1).to;
      view.dispatch({
        effects: EditorView.scrollIntoView(pos, { y: "center" }),
      });
      if (row < 0) view.scrollDOM.scrollTop = 0;
      view.focus();
      return true;
    },
    focus() {
      layout.panes[activeCol]?.view.focus();
    },
    comment() {
      compose();
    },
    suggest() {
      compose(true);
    },
    destroy() {
      disposed = true;
      dropLayouts();
    },
  };
}
