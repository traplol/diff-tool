import { EditorState, Text } from "@codemirror/state";
import { Decoration, EditorView, lineNumbers } from "@codemirror/view";
import {
  EMPTY,
  labelPath,
  refName,
  spans,
  suggestionSource,
} from "./review-ui.js";

export const $ = (id) => document.getElementById(id);
export function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
export function button(label, fn, cls) {
  const node = el("button", label, cls);
  node.type = "button";
  node.onclick = fn;
  return node;
}
const dlg = () => $("dialog");

function dialog(title, style = "") {
  if (dlg().open) dlg().close();
  dlg().className = style;
  dlg().querySelector("h2").textContent = title;
  $("dialog-body").replaceChildren();
  $("dialog-actions").replaceChildren();
  $("dialog-error").textContent = "";
  dlg().onkeydown = null;
  dlg().showModal();
  return $("dialog-body");
}
function action(title, fn, cls) {
  const node = button(
    title,
    async () => {
      node.disabled = true;
      $("dialog-error").textContent = "";
      try {
        await fn();
      } catch (err) {
        $("dialog-error").textContent = String(err);
      } finally {
        node.disabled = false;
      }
    },
    cls,
  );
  $("dialog-actions").append(node);
  return node;
}
function close() {
  dlg().close();
}
function inputArea(parent, title, text, rows) {
  const label = el("label", title);
  const field = el("textarea");
  field.value = text;
  field.rows = rows;
  label.append(field);
  parent.append(label);
  return field;
}
export function details(title, content) {
  dialog(title).append(el("pre", content));
  action("Close", close);
}
export function showBranchFile(hit, lines, branch) {
  const doc = Text.of(lines);
  const line = doc.line(hit.line);
  const from = line.from + hit.from,
    to = line.from + hit.to;
  const body = dialog(labelPath(hit.path), "branch-source");
  body.append(
    el(
      "p",
      `${refName(branch)} · ${hit.revision.slice(0, 10)} · Line ${hit.line}`,
    ),
  );
  const view = new EditorView({
    parent: body,
    state: EditorState.create({
      doc,
      extensions: [
        EditorState.readOnly.of(true),
        EditorView.editable.of(false),
        lineNumbers(),
        EditorView.decorations.of(
          Decoration.set([
            Decoration.mark({ class: "bl-find-current" }).range(from, to),
          ]),
        ),
      ],
    }),
  });
  view.dispatch({ effects: EditorView.scrollIntoView(from, { y: "center" }) });
  dlg().addEventListener("close", () => view.destroy(), { once: true });
  action("Close", close);
}
export function compose(note, callbacks) {
  const existing = note.id != null;
  const suggestion = Object.hasOwn(note, "suggestion");
  const body = dialog(
    (existing ? "Edit " : "New ") + (suggestion ? "suggestion" : "comment"),
    "popover",
  );
  body.append(
    el("strong", labelPath(note.path)),
    el(
      "div",
      [
        note.group,
        spans(note),
        existing ? (note.resolved ? "Resolved" : "Open") : "",
      ]
        .filter(Boolean)
        .join(" · "),
    ),
  );
  if (note.excerpt) body.append(el("pre", note.excerpt));
  const code = suggestion
    ? inputArea(body, "Proposed replacement", note.suggestion, 4)
    : null;
  if (code && note.applied_location) {
    code.readOnly = true;
    body.append(el("p", "Applied to working file"));
  }
  const message = inputArea(
    body,
    suggestion ? "Comment (optional)" : "Comment",
    note.body || "",
    3,
  );
  if (existing)
    action(
      "Delete",
      async () => {
        const label = "Confirm delete";
        if (deleteButton.textContent !== label) {
          deleteButton.textContent = label;
          return;
        }
        await callbacks.remove();
        close();
      },
      "danger",
    );
  const deleteButton = $("dialog-actions").firstElementChild;
  action("Cancel", close);
  const save = action(
    suggestion ? "Save suggestion" : "Save comment",
    async () => {
      if (!suggestion && !message.value.trim()) throw Error("Enter a comment.");
      if (
        code &&
        !code.readOnly &&
        code.value &&
        code.value === suggestionSource(note)
      )
        throw Error(
          "Edit the replacement or clear it to propose deleting the lines.",
        );
      await callbacks.save(message.value, code?.value);
      close();
    },
    "primary",
  );
  dlg().onkeydown = (e) => {
    if (e.ctrlKey && e.key === "Enter") {
      e.preventDefault();
      save.click();
    }
  };
  (code && !code.readOnly ? code : message).focus();
}
export function preview(drafts, copy, save) {
  const body = dialog("Markdown preview", "preview");
  const label = el("label"),
    only = el("input");
  only.type = "checkbox";
  label.append(only, " Open comments only");
  body.append(label);
  const field = inputArea(body, "Review Markdown", drafts.full, 18);
  let key = "full";
  only.onchange = () => {
    drafts[key] = field.value;
    key = only.checked ? "open" : "full";
    field.value = drafts[key];
  };
  action("Close", close);
  action("Copy Markdown", () => copy(field.value));
  const saveButton = action("Save as…", () => save(field.value), "primary");
  dlg().onkeydown = (e) => {
    if (e.ctrlKey && e.key.toLowerCase() === "s") {
      e.preventDefault();
      saveButton.click();
    }
  };
  field.focus();
}
export function stackDialog(state, discover, apply) {
  const body = dialog("Edit branch stack");
  let refs = [...state.stack];
  const grid = el("div", null, "stack-columns");
  body.append(grid);
  const column = (title) => {
    const panel = el("div"),
      heading = el("label", title),
      select = el("select"),
      controls = el("div", null, "stack-controls");
    select.size = 9;
    select.setAttribute("aria-label", title);
    panel.append(heading, select, controls);
    grid.append(panel);
    return { panel, select, controls };
  };
  const left = column("Available refs"),
    right = column("Review order");
  const filter = el("input");
  filter.type = "search";
  filter.placeholder = "Filter refs…";
  left.panel.insertBefore(filter, left.select);
  const hint = el("p");
  body.append(hint);
  function showRefs(list) {
    left.select.replaceChildren(
      ...list.map((ref) => new Option(refName(ref), ref)),
    );
    left.select.selectedIndex = 0;
  }
  filter.oninput = () =>
    showRefs(
      Object.keys(state.repo.refs).filter((r) =>
        refName(r).toLowerCase().includes(filter.value.toLowerCase()),
      ),
    );
  filter.oninput();
  function order(i = 0) {
    right.select.replaceChildren(
      ...refs.map(
        (r, i) =>
          new Option((i === 0 ? "Base" : "Layer " + i) + " · " + refName(r), r),
      ),
    );
    right.select.selectedIndex = Math.min(Math.max(i, 0), refs.length - 1);
  }
  order();
  function change(replace) {
    const r = left.select.value,
      i = right.select.selectedIndex;
    if (!r) return;
    if (refs.includes(r) && !(replace && refs[i] === r)) {
      hint.textContent = "That ref is already in the stack.";
      return;
    }
    if (replace && i >= 0) refs[i] = r;
    else refs.push(r);
    hint.textContent = "";
    order(replace ? i : refs.length - 1);
  }
  async function find() {
    const ref = left.select.value;
    if (!ref || ref === EMPTY) return;
    try {
      const [found, forks] = await discover(
        refs[0] || state.repo.default_branch || EMPTY,
        ref,
      );
      refs = found;
      order(found.indexOf(ref));
      if (forks.length) showRefs(forks);
      hint.textContent = forks.length
        ? "Multiple paths. Select a branch and find its stack."
        : "Found the branch order from Git history.";
    } catch (err) {
      hint.textContent = String(err);
    }
  }
  left.select.ondblclick = find;
  left.controls.append(
    button("Find stack", find),
    button("Add", () => change(false)),
    button("Replace", () => change(true)),
  );
  for (const [title, delta] of [
    ["Up", -1],
    ["Down", 1],
  ])
    right.controls.append(
      button(title, () => {
        const i = right.select.selectedIndex,
          j = i + delta;
        if (i >= 0 && j >= 0 && j < refs.length) {
          [refs[i], refs[j]] = [refs[j], refs[i]];
          order(j);
        }
      }),
    );
  right.controls.append(
    button("Remove", () => {
      const i = right.select.selectedIndex;
      if (i >= 0) {
        refs.splice(i, 1);
        order(i);
      }
    }),
  );
  action("Cancel", close);
  action(
    "Review stack",
    async () => {
      await apply(refs);
      close();
    },
    "primary",
  );
  filter.focus();
}
