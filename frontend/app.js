import { invoke } from "@tauri-apps/api/core";
import { canExpandFile, contextMenu, createDiff } from "./editor.js";
import { setupFind } from "./find.js";
import "./editor.css";
import {
  $,
  el,
  button,
  compose,
  details,
  preview,
  stackDialog,
  showBranchFile,
} from "./dialogs.js";
import {
  WORKTREE,
  EMPTY,
  commentRow,
  decodePatch,
  labelPath,
  noteDestination,
  setFold,
  refName,
  pairs,
  scopeNotes,
  localScope,
  fileNotes,
  suggestionSource,
} from "./review-ui.js";

let state,
  tab = "Changes",
  mode = "unified",
  fileIndex = -1,
  selectedNote,
  editor,
  openFilter = "Open";
let lines = [],
  commits = null,
  editLock = false,
  loading = false,
  sequence = 0;
const positions = new Map(),
  folds = new Map();
const files = () => state?.comparison?.files ?? [];
const currentFile = () => files()[fileIndex];
const names = ["Changes", "Commits", "Comments"];
const closedFolders = new Set(),
  closedSearchFolders = new Set();
const basename = (path) => path.split(/[\\/]/).filter(Boolean).at(-1) || path;
const request = (op, args = {}, snapshot = state?.snapshot) =>
  invoke("workspace", { request: { op, ...args }, snapshot: snapshot ?? null });
let preferenceWrite = Promise.resolve();
function savePreference(op, args) {
  preferenceWrite = preferenceWrite
    .then(() => request(op, args))
    .catch((err) => status(String(err), true));
  return preferenceWrite;
}
const status = (message = "", error = false) => {
  $("status").textContent = message;
  $("status").title = message;
  $("status").classList.toggle("error", error);
};
const handle =
  (fn) =>
  async (...args) => {
    try {
      return await fn(...args);
    } catch (err) {
      status(String(err), true);
    }
  };
const on = (id, fn) => {
  $(id).onclick = handle(fn);
};
function activate(node, active) {
  node.classList.toggle("active", active);
  node.setAttribute("aria-pressed", String(active));
}
function empty(node, message) {
  node.replaceChildren(el("p", message, "empty"));
}
function tableMessage(body, message) {
  const row = el("tr"),
    cell = el("td", message, "empty");
  cell.colSpan = body
    .closest("table")
    .tHead.querySelectorAll("th:not([hidden])").length;
  row.append(cell);
  body.replaceChildren(row);
}
async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const field = el("textarea");
    const previous = document.activeElement;
    (document.querySelector("dialog[open]") || document.body).append(field);
    field.value = text;
    field.select();
    const ok = document.execCommand("copy");
    field.remove();
    previous?.focus();
    if (!ok) throw Error("The clipboard is unavailable.");
  }
  status("Copied to clipboard");
}
function positionKey() {
  const f = currentFile(),
    c = state?.comparison;
  return (
    f &&
    c &&
    JSON.stringify([
      state.repo.root,
      c.left,
      c.right,
      f.group,
      f.path,
      f.old_oid,
      f.oid,
    ])
  );
}
function leaveFile() {
  if (editor) {
    positions.set(positionKey(), editor.getPosition());
    editor.destroy();
    editor = null;
  }
  lines = [];
  sequence++;
  $("full-file").disabled = true;
  contextButton({ full: false, expanded: false });
  find.fileChanged();
}
function choiceIndex() {
  return pairs(state.stack, state.repo.checkout).findIndex(
    ([, p]) => p[0] === state.pair[0] && p[1] === state.pair[1],
  );
}

async function changeWorkspace(op, args, keepFind = false) {
  if (loading || editLock) return;
  loading = true;
  $("app").setAttribute("aria-busy", "true");
  status("Reading Git changes…");
  try {
    const previous = currentFile(),
      previousRoot = state?.repo.root;
    const pending = preferenceWrite;
    if (op === "open") await pending;
    const next = await request(op, args);
    leaveFile();
    if (
      previousRoot !== next.repo.root ||
      state?.pair[0] !== next.pair[0] ||
      state?.pair[1] !== next.pair[1]
    ) {
      closedFolders.clear();
      closedSearchFolders.clear();
    }
    state = next;
    for (const n of state.notes)
      if (folds.get(n.id) === !!n.resolved) folds.delete(n.id);
    if (previousRoot !== state.repo.root) {
      positions.clear();
      folds.clear();
      selectedNote = undefined;
      tab = "Changes";
      openFilter = "Open";
      $("filter").value = "";
      find.close();
      $("diff-search").value = "";
      $("scope").value = "current";
    }
    fileIndex = -1;
    commits = null;
    $("welcome").hidden = true;
    $("workspace").hidden = false;
    $("find").disabled = false;
    const name = basename(state.repo.root);
    document.title = name + " · Branchline";
    $("crumb").textContent = name;
    $("repo-name").textContent = name;
    $("choose").title = state.repo.root;
    if (op === "open" && pending === preferenceWrite) {
      setWidth(state.width);
      setMode(state.diff_layout);
    }
    const choices = pairs(state.stack, state.repo.checkout);
    $("pair").replaceChildren(
      ...choices.map(([label], i) => new Option(label, String(i))),
    );
    $("pair").selectedIndex = choiceIndex();
    $("range").textContent = state.pair.map(refName).join("  →  ");
    $("stack").replaceChildren(
      ...state.stack.map((ref, i) => {
        const li = el("li"),
          b = button(
            "",
            handle(() =>
              selectPair(state.stack.length === 2 || i === 0 ? 0 : i),
            ),
          );
        b.append(
          el(
            "small",
            i === 0
              ? "Base"
              : i === state.stack.length - 1
                ? "Head"
                : "Layer " + i,
          ),
          el("span", refName(ref)),
        );
        b.title = refName(ref);
        li.append(b);
        return li;
      }),
    );
    $("edit-stack").disabled = Object.keys(state.repo.refs).length < 2;
    $("scope").options[0].text = localScope(state)
      ? "Working tree"
      : "Current stack";
    $("export").disabled = false;
    $("refresh").disabled = false;
    for (const b of $("nav").querySelectorAll("button")) b.disabled = false;
    renderFiles();
    const ids = visibleFiles();
    const keep = ids.find(
      (i) =>
        previousRoot === state.repo.root &&
        previous &&
        files()[i].path === previous.path &&
        files()[i].group === previous.group,
    );
    fileIndex = keep ?? ids[0] ?? -1;
    await navigate(tab);
    if (!keepFind) find.refresh();
    const warning = [state.error, state.config_warning]
      .filter(Boolean)
      .join(" · ");
    status(warning || "Comparison up to date", !!warning);
  } finally {
    loading = false;
    $("app").removeAttribute("aria-busy");
    if (state) $("pair").selectedIndex = choiceIndex();
  }
}
async function choose() {
  if (loading) return;
  const path = await invoke("choose_repository");
  if (path) await changeWorkspace("open", { path });
}
function refresh() {
  if (state)
    return changeWorkspace("open", { path: state.repo.root, pair: state.pair });
}
function selectPair(i) {
  const pair = pairs(state.stack, state.repo.checkout)[i]?.[1];
  if (pair) return changeWorkspace("compare", { pair });
}
function setWidth(width) {
  document.documentElement.style.setProperty(
    "--side",
    Math.round(Math.max(150, Math.min(width, window.innerWidth * 0.48, 800))) +
      "px",
  );
}
async function navigate(name) {
  if (!state) return;
  tab = name;
  for (const n of names) $(n.toLowerCase()).hidden = n !== tab;
  for (const b of $("nav").querySelectorAll("button"))
    activate(b, b.dataset.tab === tab);
  $("page-title").textContent = {
    Changes: "Changes",
    Commits: "Commits",
    Comments: "Review comments",
  }[tab];
  chromeCounts();
  if (tab === "Changes") {
    if (!editor) await pick(fileIndex);
    else renderFiles();
  } else if (tab === "Comments") renderComments();
  else await renderCommits();
}
function chromeCounts() {
  $("nav").querySelector('[data-tab="Changes"] small').textContent =
    files().length;
  $("nav").querySelector('[data-tab="Comments"] small').textContent =
    scopeNotes(state, tab === "Comments" && $("scope").value === "all").length;
  $("progress").textContent = state.viewed.length + "/" + files().length;
}
function visibleFiles() {
  const q = $("filter").value.trim().toLowerCase();
  return files().flatMap((f, i) =>
    labelPath(f.path).toLowerCase().includes(q) ||
    labelPath(f.old).toLowerCase().includes(q)
      ? [i]
      : [],
  );
}
function renderFiles() {
  const list = $("file-list"),
    frag = document.createDocumentFragment();
  const containers = new Map();
  const closed = $("filter").value.trim() ? closedSearchFolders : closedFolders;
  function folder(parent, group, directory, label) {
    const key = JSON.stringify([group, directory]);
    if (!containers.has(key)) {
      const details = el("details"),
        summary = el("summary", label, "file-group");
      details.open = !closed.has(key);
      details.ontoggle = () => {
        if (!list.contains(details)) return;
        if (details.open) closed.delete(key);
        else closed.add(key);
      };
      details.append(summary);
      parent.append(details);
      containers.set(key, details);
    }
    return containers.get(key);
  }
  for (const i of visibleFiles()) {
    const f = files()[i],
      path = labelPath(f.path),
      parts = path.split("/");
    let parent = f.group ? folder(frag, f.group, null, f.group) : frag;
    let directory = "";
    for (const part of parts.slice(0, -1)) {
      directory += part + "/";
      parent = folder(parent, f.group, directory, part + "/");
    }
    const b = button(
      "",
      handle(() => pick(i, true)),
      "file-item",
    );
    b.dataset.file = i;
    b.title = f.old !== f.path ? labelPath(f.old) + " → " + path : path;
    b.setAttribute("aria-label", b.title);
    activate(b, fileIndex === i);
    b.append(el("span", f.status, "badge"), el("span", parts.at(-1), "path"));
    if (state.viewed.includes(i)) b.append(el("span", "✓"));
    parent.append(b);
  }
  list.replaceChildren(frag);
  if (!list.firstChild)
    empty(list, files().length ? "No matching files" : "No changed files");
  chromeCounts();
}
function canApply(note) {
  const f = currentFile();
  return (
    typeof note.suggestion === "string" &&
    !note.resolved &&
    !note.applied_location &&
    !!note.new?.length &&
    ["100644", "100755"].includes(f?.mode) &&
    (state.pair[1] === WORKTREE ||
      state.pair[1] ===
        (state.repo.checkout.startsWith("HEAD@")
          ? "HEAD"
          : state.repo.checkout))
  );
}
async function pick(index, focus = false, jump) {
  if (index === fileIndex && editor) {
    if (jump != null) editor.jump(jump);
    if (focus && tab === "Changes") editor.focus();
    return;
  }
  leaveFile();
  fileIndex = index;
  const f = currentFile(),
    token = sequence,
    snapshot = state.snapshot;
  renderFiles();
  $("filename").textContent = f ? labelPath(f.path) : "Diff";
  $("filename").title =
    f && f.old !== f.path
      ? labelPath(f.old) + " → " + labelPath(f.path)
      : labelPath(f?.path || "");
  $("file-stats").textContent =
    f && f.added != null ? "+" + f.added + "  −" + f.removed : "";
  $("viewed").checked = state.viewed.includes(index);
  $("viewed").disabled = !f;
  $("comment").disabled = true;
  $("suggest").disabled = true;
  $("selection").textContent = "Whole file";
  $("diff").replaceChildren();
  if (!f) {
    empty(
      $("diff"),
      state.error ||
        (files().length ? "Choose a file" : "No changes in this comparison"),
    );
    return;
  }
  try {
    const data = await request("display_patch", { file: index });
    if (sequence !== token) return;
    lines = decodePatch(data);
    editor = createDiff($("diff"), {
      file: f,
      emptyBase: state.comparison.base === state.repo.refs[EMPTY],
      lines,
      notes: fileNotes(state, f),
      loadContents: () => request("file_contents", { file: index }, snapshot),
      onContextChange: contextButton,
      mode,
      position: positions.get(positionKey()),
      folds,
      onCompose: newComment,
      onAction: handle(noteAction),
      onStatus: status,
      canApply,
      onCopy: copy,
      onSelection: ({ label, canSuggest, canComment = true }) => {
        $("comment").disabled = !canComment;
        if ($("selection").textContent !== label)
          $("selection").textContent = label;
        $("suggest").disabled = !canSuggest;
      },
    });
    $("full-file").disabled = !canExpandFile(f);
    find.fileChanged();
    if (jump != null) editor.jump(jump);
    if (focus && tab === "Changes") editor.focus();
  } catch (err) {
    if (sequence === token) {
      empty($("diff"), String(err));
      status(String(err), true);
    }
  }
}
function setMode(value, save = false) {
  const changed = mode !== value;
  mode = value;
  activate($("unified"), value === "unified");
  activate($("split"), value === "split");
  editor?.setMode(value);
  if (save && changed) return savePreference("layout", { layout: value });
}
function newComment(selection) {
  const file = currentFile(),
    snapshot = state.snapshot,
    index = fileIndex;
  const indices = new Map(lines.map((line, i) => [line, i]));
  const rows = selection.lines.map((l) => indices.get(l));
  const span = (side) => {
    if (selection.side !== "both" && selection.side !== side) return [];
    const nums = selection.lines.map((l) => l[side]).filter((n) => n != null);
    return nums.length ? [nums[0], nums.at(-1)] : [];
  };
  const n = {
    path: file.path,
    group: file.group,
    old: span("old"),
    new: span("new"),
    excerpt: selection.lines.map((l) => l.kind + l.text).join("\n"),
  };
  if (selection.suggestion) n.suggestion = suggestionSource(n);
  compose(n, {
    save: (body, suggestion) =>
      update(
        "create",
        { file: index, rows, side: selection.side, body, suggestion },
        snapshot,
      ),
  });
}
async function update(op, args, snapshot = state.snapshot) {
  if (editLock || loading)
    throw Error("Wait for the current operation to finish.");
  editLock = true;
  try {
    const changed = await request(op, args, snapshot);
    if (snapshot !== state.snapshot) return;
    Object.assign(state, changed);
    if (op === "resolve") folds.delete(args.id);
    editor?.setNotes(fileNotes(state, currentFile()));
    chromeCounts();
    if (tab === "Comments") renderComments();
    status(op === "delete" ? "Comment deleted" : "Review saved");
  } finally {
    editLock = false;
  }
}
function editNote(note) {
  const snapshot = state.snapshot;
  compose(note, {
    save: (body, suggestion) =>
      update("edit", { original: note, body, suggestion }, snapshot),
    remove: () => update("delete", { id: note.id }, snapshot),
  });
}
async function noteAction(action, projected) {
  const note = state.notes.find((n) => n.id === projected.id);
  if (!note) throw Error("This comment has been removed.");
  if (action === "edit") return editNote(note);
  if (action === "apply") {
    await update("apply", { original: note, file: fileIndex });
    await refresh();
    return;
  }
  if (action === "resolve" || action === "reopen")
    await update("resolve", { id: note.id, value: action === "resolve" });
}
async function jumpToNote(note) {
  const dest = noteDestination(state, note);
  if (!dest) return editNote(note);
  if (dest.left !== state.pair[0] || dest.right !== state.pair[1])
    await changeWorkspace("compare", { pair: [dest.left, dest.right] });
  const index = files().findIndex(
    (f) =>
      f.path === dest.path &&
      f.group === dest.group &&
      fileNotes(state, f).some((n) => n.id === note.id),
  );
  if (index < 0) return editNote(note);
  setFold(folds, note, false);
  $("filter").value = "";
  await navigate("Changes");
  editor?.setNotes(fileNotes(state, currentFile()));
  await pick(index, true, note.id);
  revealFileInTree(index);
}
function revealFileInTree(index) {
  for (
    let node = $("file-list").querySelector(
      '[data-file="' + index + '"]',
    )?.parentElement;
    node && node !== $("file-list");
    node = node.parentElement
  ) {
    if (node.tagName === "DETAILS") node.open = true;
  }
}
function renderComments() {
  chromeCounts();
  const entire = $("scope").value === "all";
  $("comparison-column").hidden = !entire;
  const notes = scopeNotes(state, entire),
    open = notes.filter((n) => !n.resolved).length;
  $("comments-title").textContent =
    open + " open · " + (notes.length - open) + " resolved";
  const rows = notes.filter(
    (n) => openFilter === "All" || n.resolved === (openFilter === "Resolved"),
  );
  const body = $("note-table").tBodies[0];
  const previousIndex = Math.max(
    0,
    Array.from(body.rows).findIndex(
      (row) => Number(row.dataset.id) === selectedNote,
    ),
  );
  const hadFocus = body.contains(document.activeElement);
  if (!rows.some((n) => n.id === selectedNote))
    selectedNote = rows[Math.min(previousIndex, rows.length - 1)]?.id;
  for (const b of $("filters").children)
    activate(b, b.textContent === openFilter);
  const select = (id) => {
    selectedNote = id;
    for (const row of body.rows)
      row.classList.toggle("selected", Number(row.dataset.id) === id);
    const n = rows.find((n) => n.id === id);
    $("open-comment").disabled = !n;
    $("show-diff").disabled = !n || !noteDestination(state, n);
    $("toggle-resolved").disabled = !n;
    $("toggle-resolved").textContent = n?.resolved ? "Reopen" : "Resolve";
  };
  body.replaceChildren(
    ...rows.map((n) => {
      const row = el("tr");
      row.dataset.id = n.id;
      row.tabIndex = 0;
      const chip = el("td");
      chip.append(
        el(
          "span",
          n.resolved ? "Resolved" : "Open",
          "status-chip" + (n.resolved ? " resolved" : ""),
        ),
      );
      const shown = commentRow(n, noteDestination(state, n));
      row.append(el("td", shown.path));
      if (entire) row.append(el("td", shown.comparison));
      row.append(el("td", shown.lines), chip, el("td", shown.summary));
      row.onclick = row.onfocus = () => select(n.id);
      row.ondblclick = () => editNote(n);
      row.onkeydown = (e) => {
        if (e.key === "Enter") editNote(n);
      };
      return row;
    }),
  );
  if (!rows.length)
    tableMessage(
      body,
      "No " +
        (openFilter === "All" ? "" : openFilter.toLowerCase() + " ") +
        "comments in this scope.",
    );
  select(selectedNote);
  if (hadFocus) body.querySelector("tr.selected")?.focus();
}
async function renderCommits() {
  const body = $("commit-table").tBodies[0],
    token = state.snapshot;
  if (!commits) {
    if (!state.comparison || state.pair[1] === WORKTREE) {
      tableMessage(body, "Choose a branch comparison to see its commits.");
      $("commits-title").textContent = "Commits";
      return;
    }
    tableMessage(body, "Reading commits…");
    const data = await request("commits");
    if (state.snapshot !== token) return;
    commits = data;
  }
  $("commits-title").textContent = "Commits · " + commits.length;
  body.replaceChildren(
    ...commits.map((c) => {
      const row = el("tr");
      row.tabIndex = 0;
      const values = [c.subject, c.author, c.date, c.sha.slice(0, 9)];
      const show = handle(async () =>
        details("Commit details", await request("details", { sha: c.sha })),
      );
      row.ondblclick = show;
      row.onkeydown = (e) => {
        if (e.key === "Enter") show();
      };
      values.forEach((value) => {
        const cell = el("td", value);
        cell.oncontextmenu = (e) => {
          e.preventDefault();
          contextMenu(e, [
            ["Copy value", handle(() => copy(value))],
            ["Copy row", handle(() => copy(values.join("\t")))],
            ["Copy full SHA", handle(() => copy(c.sha))],
            ["Commit details…", show],
            ["Fit columns to content", fitColumns],
          ]);
        };
        row.append(cell);
      });
      return row;
    }),
  );
  if (!commits.length) tableMessage(body, "No commits in this comparison.");
}
function fitColumns() {
  $("commit-table").classList.add("fit");
}
async function exportReview() {
  if (!state) return;
  const token = state.snapshot;
  status("Checking current comment locations…");
  const drafts = await request("export", {
    entire: tab === "Comments" && $("scope").value === "all",
  });
  if (state.snapshot !== token) return;
  preview(drafts, copy, async (content) => {
    if (await invoke("save_markdown", { content })) status("Markdown saved");
  });
  status(
    drafts.cached
      ? "Markdown preview uses the displayed comments. Git could not refresh their locations."
      : "Markdown preview ready",
  );
}
function contextButton({ full, expanded }) {
  activate($("full-file"), full);
  $("full-file").textContent = full ? "Changes only" : "Full file";
  $("collapse-context").hidden = full || !expanded;
}
on("full-file", () =>
  $("full-file").getAttribute("aria-pressed") === "true"
    ? editor?.collapseContext()
    : editor?.showFullFile(),
);
on("collapse-context", () => editor?.collapseContext());

async function openSearchHit(hit, scope, valid) {
  if (scope === "branch") {
    const contents = await request("branch_file", {
      path: hit.path,
      revision: hit.revision,
    });
    if (valid())
      showBranchFile(
        hit,
        contents,
        state.pair[1] === WORKTREE ? state.repo.checkout : state.pair[1],
      );
    return;
  }
  if (state.pair[0] !== hit.pair[0] || state.pair[1] !== hit.pair[1]) {
    await changeWorkspace("compare", { pair: hit.pair }, true);
  }
  if (!valid()) return;
  const c = state.comparison;
  if (
    !c ||
    c.left !== hit.pair[0] ||
    c.right !== hit.pair[1] ||
    c.base !== hit.base ||
    c.head !== hit.head
  ) {
    throw Error(
      "This comparison changed. Refresh the search to locate this match.",
    );
  }
  const i = files().findIndex(
    (f) => f.path === hit.path && f.group === hit.group,
  );
  if (i < 0) throw Error("This file changed. Refresh the search.");
  $("filter").value = "";
  renderFiles();
  await pick(i);
  if (valid() && fileIndex === i && editor) {
    revealFileInTree(i);
    editor.revealPatchRow(hit.row, hit.from, hit.to);
  }
}
const find = setupFind({
  activeEditor: () => editor,
  patchLines: () => lines,
  searchReview: (scope, query) =>
    invoke("search_review", { snapshot: state.snapshot, scope, query }),
  openHit: openSearchHit,
});

for (const id of ["choose", "welcome-open"]) on(id, choose);
on("refresh", refresh);
on("export", exportReview);
on("fit", fitColumns);
on("edit-stack", () =>
  stackDialog(
    state,
    (base, branch) => request("discover", { base, branch }),
    (refs) => changeWorkspace("set_stack", { refs }),
  ),
);
on("split", () => setMode("split", true));
on("unified", () => setMode("unified", true));
on("comment", () => editor?.comment());
on("suggest", () => editor?.suggest());
on("toggle-resolved", () => {
  const n = state.notes.find((n) => n.id === selectedNote);
  if (n) return update("resolve", { id: n.id, value: !n.resolved });
});
on("open-comment", () => {
  const n = state.notes.find((n) => n.id === selectedNote);
  if (n) editNote(n);
});
on("show-diff", () => {
  const n = state.notes.find((n) => n.id === selectedNote);
  if (n) return jumpToNote(n);
});
$("pair").onchange = handle(() => selectPair($("pair").selectedIndex));
$("scope").onchange = renderComments;
for (const b of $("filters").children)
  b.onclick = () => {
    openFilter = b.textContent;
    renderComments();
  };
for (const b of $("nav").querySelectorAll("button")) {
  b.disabled = true;
  b.onclick = handle(() => navigate(b.dataset.tab));
}
$("viewed").onchange = handle(async () => {
  const file = fileIndex,
    value = $("viewed").checked,
    token = state.snapshot;
  try {
    await request("viewed", { file, value }, token);
    if (state.snapshot !== token) return;
    state.viewed = state.viewed.filter((i) => i !== file);
    if (value) state.viewed.push(file);
    renderFiles();
  } catch (err) {
    if (state.snapshot === token && fileIndex === file)
      $("viewed").checked = state.viewed.includes(file);
    throw err;
  }
});
$("filter").oninput = handle(async () => {
  closedSearchFolders.clear();
  const ids = visibleFiles();
  if (!ids.includes(fileIndex)) await pick(ids[0] ?? -1);
  else renderFiles();
});
$("filter").onkeydown = (e) => {
  if (e.key === "Enter") editor?.focus();
  if (e.key === "Escape") {
    e.preventDefault();
    $("filter").value = "";
    $("filter").oninput();
  }
};
let dragging = false;
const divider = $("divider");
const persistWidth = handle(
  () =>
    state &&
    savePreference("width", {
      width: Math.round($("sidebar").getBoundingClientRect().width),
    }),
);
divider.onpointerdown = (e) => {
  dragging = true;
  divider.setPointerCapture(e.pointerId);
  e.preventDefault();
};
divider.onpointermove = (e) => {
  if (dragging) setWidth(e.clientX);
};
divider.onpointerup = () => {
  dragging = false;
  persistWidth();
};
divider.onpointercancel = () => {
  dragging = false;
};
divider.onkeydown = (e) => {
  if (["ArrowLeft", "ArrowRight"].includes(e.key)) {
    e.preventDefault();
    setWidth($("sidebar").offsetWidth + (e.key === "ArrowRight" ? 12 : -12));
    persistWidth();
  }
};
document.addEventListener(
  "keydown",
  handle(async (e) => {
    if ($("dialog").open) return;
    const key = e.key.toLowerCase();
    if ((e.ctrlKey || e.metaKey) && ["o", "b", "e", "f", "p"].includes(key)) {
      e.preventDefault();
      if (key === "o") return choose();
      if (!state) return;
      if (key === "b") return $("edit-stack").click();
      if (key === "e") return exportReview();
      await navigate("Changes");
      if (key === "f") return find.open(e.shiftKey ? "comparison" : undefined);
      $("filter").focus();
      $("filter").select();
      return;
    }
    if (e.key === "F5") {
      e.preventDefault();
      return refresh();
    }
    if (state && e.altKey && ["ArrowDown", "ArrowUp"].includes(e.key)) {
      e.preventDefault();
      await navigate("Changes");
      const ids = Array.from(
        $("file-list").querySelectorAll("button[data-file]"),
      )
        .filter(
          (b) => b.getClientRects().length && !b.closest("details:not([open])"),
        )
        .map((b) => Number(b.dataset.file));
      if (!ids.length) return;
      const direction = e.key === "ArrowDown" ? 1 : -1,
        from = ids.indexOf(fileIndex);
      const next =
        from < 0
          ? direction > 0
            ? 0
            : ids.length - 1
          : (from + direction + ids.length) % ids.length;
      await pick(ids[next], true);
    }
  }),
);
setMode("unified");
for (const id of ["export", "edit-stack", "refresh"]) $(id).disabled = true;
handle(async () =>
  changeWorkspace("open", { path: await invoke("startup_path") }),
)();
