import { EditorState, Text } from "@codemirror/state";
import { Decoration, EditorView, lineNumbers } from "@codemirror/view";
import {
  EMPTY,
  appendReplies,
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
export function commentStatus(resolved) {
  return el(
    "span",
    resolved ? "Resolved" : "Open",
    "status-chip" + (resolved ? " resolved" : ""),
  );
}
const dlg = () => $("dialog");
const memoryDrafts = new Map();

function draftStorage(kind, key) {
  const id = "branchline:draft:v1:" + kind + ":" + key;
  return {
    load() {
      if (memoryDrafts.has(id)) return memoryDrafts.get(id);
      try {
        return JSON.parse(localStorage.getItem(id));
      } catch {
        return null;
      }
    },
    write(value) {
      try {
        if (value == null) localStorage.removeItem(id);
        else localStorage.setItem(id, JSON.stringify(value));
        memoryDrafts.delete(id);
        return true;
      } catch {
        memoryDrafts.set(id, value);
        return false;
      }
    },
  };
}

function draftNotice(body) {
  const notice = el("p");
  notice.setAttribute("role", "status");
  notice.hidden = true;
  body.append(notice);
  return (text) => {
    if (notice.textContent !== text) notice.textContent = text;
    notice.hidden = !text;
  };
}

function dialog(title, style = "") {
  if (dlg().open) dlg().close();
  dlg().className = style;
  dlg().setAttribute("aria-label", title);
  dlg().querySelector("h2").textContent = title;
  $("dialog-body").replaceChildren();
  $("dialog-actions").replaceChildren();
  $("dialog-error").textContent = "";
  dlg().onkeydown = null;
  dlg().oncancel = null;
  dlg().querySelector(".dialog-top button").disabled = false;
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
export function showBranchFile(hit, file, branch, note) {
  const body = dialog(labelPath(hit.path), "branch-source");
  body.append(
    el(
      "p",
      `${refName(branch)} · ${hit.revision.slice(0, 10)}${hit.line ? ` · Line ${hit.line}` : ""}`,
    ),
  );
  if (note) {
    const original = el("details");
    original.append(el("summary", "Original comment"), el("p", note.body));
    if (note.excerpt) original.append(el("pre", note.excerpt));
    body.append(original);
  }
  if (file.kind !== "text") {
    body.append(el("p", file.kind === "binary"
      ? `Binary file · ${file.bytes} bytes`
      : "Git submodule"));
    if (file.kind === "submodule") body.append(el("pre", file.oid));
    action("Close", close);
    return;
  }
  const doc = file.lines.length ? Text.of(file.lines) : Text.empty;
  const line = hit.line ? doc.line(hit.line) : null;
  const from = line ? line.from + hit.from : 0,
    to = line ? line.from + hit.to : 0;
  const view = new EditorView({
    parent: body,
    state: EditorState.create({
      doc,
      extensions: [
        EditorState.readOnly.of(true),
        EditorView.editable.of(false),
        lineNumbers(),
        EditorView.decorations.of(
          Decoration.set(from < to ? [
            Decoration.mark({ class: "bl-find-current" }).range(from, to),
          ] : []),
        ),
      ],
    }),
  });
  view.dispatch({ effects: EditorView.scrollIntoView(from, { y: "center" }) });
  dlg().addEventListener("close", () => view.destroy(), { once: true });
  action("Close", close);
}
export function compose(note, callbacks, draftKey) {
  const existing = note.id != null;
  const suggestion = Object.hasOwn(note, "suggestion");
  const body = dialog(
    (existing ? "Edit " : "New ") + (suggestion ? "suggestion" : "comment"),
    "popover",
  );
  const location = el("div", null, "comment-location");
  location.append(
    el("code", labelPath(note.path)),
    el("span", [note.group, spans(note)].filter(Boolean).join(" · ")),
  );
  if (existing) location.append(commentStatus(note.resolved));
  body.append(location);
  if (note.excerpt) body.append(el("pre", note.excerpt));
  const code = suggestion
    ? inputArea(body, "Proposed replacement", note.suggestion, 4)
    : null;
  const applied = Boolean(note.applied_location);
  if (code) code.className = "replacement";
  if (code && applied) {
    code.readOnly = true;
    body.append(el("p", "Applied to working file"));
  }
  const message = inputArea(
    body,
    suggestion ? "Comment (optional)" : "Comment",
    note.body || "",
    3,
  );
  const originalBody = message.value;
  const originalReplacement = code?.value;
  appendReplies(body, note);
  const showNotice = draftNotice(body);
  const storage = draftStorage("compose", draftKey);
  const recovered = storage.load();
  if (typeof recovered?.body === "string") message.value = recovered.body;
  if (code && !applied && typeof recovered?.replacement === "string")
    code.value = recovered.replacement;

  let pending = false;
  const topClose = dlg().querySelector(".dialog-top button");
  async function finish(commit) {
    pending = true;
    const controls = [
      ...$("dialog-actions").querySelectorAll("button:not(:disabled)"),
      topClose,
    ];
    for (const control of controls) control.disabled = true;
    message.readOnly = true;
    if (code) code.readOnly = true;
    try {
      await commit();
      storage.write(null);
      if (message.isConnected) close();
    } finally {
      pending = false;
      for (const control of controls) control.disabled = false;
      message.readOnly = false;
      if (code) code.readOnly = applied;
    }
  }

  if (existing) {
    const deleteButton = action(
      "Delete",
      async () => {
        const label = "Confirm delete";
        if (deleteButton.textContent !== label) {
          deleteButton.textContent = label;
          return;
        }
        await finish(callbacks.remove);
      },
      "danger",
    );
  }
  const dismiss = action("Cancel", close);
  const discard = action("Discard draft", () => {
    storage.write(null);
    close();
  });
  function refreshDraft(restored = false) {
    const replacement = code && !applied ? code.value : undefined;
    const dirty =
      message.value !== originalBody ||
      (replacement !== undefined && replacement !== originalReplacement);
    const persisted =
      restored ||
      storage.write(dirty ? { body: message.value, replacement } : null);
    discard.hidden = !dirty;
    dismiss.textContent = dirty ? "Keep draft" : "Cancel";
    showNotice(
      dirty
        ? restored
          ? "Draft restored."
          : persisted
            ? "Draft saved on this device."
            : "Draft kept while Branchline stays open."
        : "",
    );
  }
  message.oninput = () => refreshDraft();
  if (code && !applied) code.oninput = message.oninput;
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
      await finish(() => callbacks.save(message.value, code?.value));
    },
    "primary",
  );
  dlg().oncancel = (e) => {
    if (pending) e.preventDefault();
  };
  dlg().onkeydown = (e) => {
    if (e.ctrlKey && e.key === "Enter") {
      e.preventDefault();
      save.click();
    }
  };
  refreshDraft(true);
  (code && !applied ? code : message).focus();
}
export function preview(drafts, copy, save, draftKey) {
  const body = dialog("Markdown preview", "preview");
  const label = el("label", null, "preview-filter"),
    only = el("input");
  only.type = "checkbox";
  label.append(only, " Open comments only");
  body.append(label);
  const showNotice = draftNotice(body);
  const field = inputArea(body, "Review Markdown", "", 18);
  function markdownVersion(version) {
    const storage = draftStorage("markdown-" + version, draftKey);
    const saved = storage.load();
    return {
      storage,
      generated: drafts[version].replace(/\r\n?/g, "\n"),
      edited: typeof saved === "string" ? saved : undefined,
    };
  }
  const versions = {
    full: markdownVersion("full"),
    open: markdownVersion("open"),
  };
  let key = "full";
  const dismiss = action("Close", close);
  const reset = action("Reset this version", () => {
    const version = versions[key];
    version.edited = undefined;
    version.storage.write(null);
    showDraft();
    field.focus();
  });
  function refreshActions(notice) {
    reset.hidden = versions[key].edited === undefined;
    const hasEdits = Object.values(versions).some(
      (version) => version.edited !== undefined,
    );
    dismiss.textContent = hasEdits ? "Keep drafts" : "Close";
    showNotice(notice);
  }
  function showDraft() {
    const { edited, generated } = versions[key];
    field.value = edited ?? generated;
    field.setSelectionRange(0, 0);
    field.scrollTop = 0;
    refreshActions(
      edited === undefined
        ? ""
        : "Edited draft. Reset this version to regenerate it from the review.",
    );
  }
  field.oninput = () => {
    const version = versions[key];
    version.edited = field.value === version.generated ? undefined : field.value;
    const persisted = version.storage.write(version.edited);
    refreshActions(
      version.edited === undefined
        ? ""
        : persisted
          ? "Draft saved on this device."
          : "Draft kept while Branchline stays open.",
    );
  };
  only.onchange = () => {
    key = only.checked ? "open" : "full";
    showDraft();
  };
  action("Copy Markdown", () => copy(field.value));
  const saveButton = action("Save as…", () => save(field.value), "primary");
  dlg().onkeydown = (e) => {
    if (e.ctrlKey && e.key.toLowerCase() === "s") {
      e.preventDefault();
      saveButton.click();
    }
  };
  field.focus();
  showDraft();
}
export function stackDialog(state, discover, apply) {
  const body = dialog("Edit branch stack", "stack-editor");
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
  filter.setAttribute("aria-label", "Filter available refs");
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
